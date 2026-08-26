from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import uuid
from typing import Any, Mapping, Sequence

import torch

from tools.audit_recursive_ridge_statistics import _batch, _expand, _merge, _solve, _stats


RESULT_BUSINESS = {
    "request.json",
    "protocol.json",
    "input_sha256.json",
    "fold_metrics.json",
    "predictions.jsonl",
    "confusion_matrices.json",
    "gate.json",
    "memory_report.json",
}
ACCESS = {
    "validation": False,
    "official_test": False,
    "final": False,
    "class12_test": False,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("audit mismatch: JSON root")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError("audit mismatch: JSONL row")
        rows.append(payload)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _verify_tree(root: Path, expected_business: set[str] | None = None) -> None:
    if not root.is_dir():
        raise ValueError("audit mismatch: signed tree missing")
    manifest = _read_json(root / "artifact_sha256.json")
    if expected_business is not None and set(manifest) != expected_business:
        raise ValueError("audit mismatch: signed tree business files")
    if {path.name for path in root.iterdir()} != set(manifest) | {
        "artifact_sha256.json",
        "COMPLETE.json",
    }:
        raise ValueError("audit mismatch: signed tree contents")
    for name, digest in manifest.items():
        if _sha256(root / name) != digest:
            raise ValueError("audit mismatch: signed tree SHA256")
    complete = _read_json(root / "COMPLETE.json")
    if (
        complete.get("status") != "complete"
        or complete.get("artifact_manifest_sha256")
        != _sha256(root / "artifact_sha256.json")
    ):
        raise ValueError("audit mismatch: signed tree COMPLETE")


def _harmonic(values: Sequence[float]) -> float:
    numbers = [float(value) for value in values]
    if not numbers or any(value == 0.0 for value in numbers):
        return 0.0
    return len(numbers) / sum(1.0 / value for value in numbers)


def _summary(labels: torch.Tensor, predictions: torch.Tensor) -> dict[str, Any]:
    matrix = torch.zeros((13, 13), dtype=torch.int64)
    for actual, predicted in zip(labels.tolist(), predictions.tolist(), strict=True):
        matrix[actual, predicted] += 1
    totals = matrix.sum(1)
    if torch.any(totals == 0):
        raise ValueError("audit mismatch: class coverage")
    per_class = [int(matrix[index, index]) / int(totals[index]) for index in range(13)]
    triple = (per_class[10], per_class[11], per_class[12])
    return {
        "per_class_accuracy": per_class,
        "old_macro_accuracy": sum(per_class[:10]) / 10.0,
        "class10_accuracy": per_class[10],
        "class11_accuracy": per_class[11],
        "class12_accuracy": per_class[12],
        "pair_harmonic_accuracy": _harmonic((per_class[10], per_class[11])),
        "triple_harmonic_accuracy": _harmonic(triple),
        "triple_macro_accuracy": sum(triple) / 3.0,
        "triple_worst_accuracy": min(triple),
        "overall_accuracy": int(matrix.diagonal().sum()) / int(matrix.sum()),
        "total_count": int(matrix.sum()),
        "total_correct": int(matrix.diagonal().sum()),
        "flow_10_to_11": int(matrix[10, 11]),
        "flow_11_to_10": int(matrix[11, 10]),
        "flow_10_11_to_12": int(matrix[10, 12] + matrix[11, 12]),
        "flow_12_to_10": int(matrix[12, 10]),
        "flow_12_to_11": int(matrix[12, 11]),
        "old_to_recent": int(matrix[:10, 10:13].sum()),
        "recent_to_old": int(matrix[10:13, :10].sum()),
        "confusion_matrix": matrix.tolist(),
    }


def _prediction_rows_match(
    published: list[dict[str, Any]], expected: list[dict[str, Any]], *, atol: float
) -> bool:
    if len(published) != len(expected):
        return False
    exact = ("path", "label", "fold", "b0_prediction", "b2_prediction")
    scores = ("raw_scores", "ridge_scores")
    required = set(exact) | set(scores)
    for left, right in zip(published, expected, strict=True):
        if set(left) != required or set(right) != required:
            return False
        if any(left[name] != right[name] for name in exact):
            return False
        for name in scores:
            if not isinstance(left[name], list) or len(left[name]) != len(right[name]):
                return False
            for lhs, rhs in zip(left[name], right[name], strict=True):
                if (
                    isinstance(lhs, bool)
                    or not isinstance(lhs, (int, float))
                    or not math.isfinite(float(lhs))
                    or abs(float(lhs) - float(rhs)) > atol
                ):
                    return False
    return True


def _checks(
    b0: Mapping[str, Any], b2: Mapping[str, Any], deltas: Sequence[float]
) -> dict[str, Any]:
    original = {
        "class12_minimum": float(b2["class12_accuracy"]) >= 0.50,
        "recent_classes_nonzero": min(
            float(b2["class10_accuracy"]),
            float(b2["class11_accuracy"]),
            float(b2["class12_accuracy"]),
        )
        > 0.0,
        "triple_worst_vs_b0": float(b2["triple_worst_accuracy"])
        >= float(b0["triple_worst_accuracy"]),
        "old_macro_budget": float(b2["old_macro_accuracy"])
        >= float(b0["old_macro_accuracy"]) - 0.005,
        "batch_recursive_equivalence": True,
        "independent_audit": True,
    }
    balance = {
        "recent_triad_minimum": min(
            float(b2["class10_accuracy"]),
            float(b2["class11_accuracy"]),
            float(b2["class12_accuracy"]),
        )
        >= 0.50,
        "pair_harmonic_strict_gain": float(b2["pair_harmonic_accuracy"])
        > float(b0["pair_harmonic_accuracy"]),
        "triple_harmonic_strict_gain": float(b2["triple_harmonic_accuracy"])
        > float(b0["triple_harmonic_accuracy"]),
        "overall_no_drop": float(b2["overall_accuracy"])
        >= float(b0["overall_accuracy"]),
        "positive_fold_direction": sum(float(value) > 0.0 for value in deltas) >= 4,
    }
    return {
        "truth_passed": True,
        "original_checks": original,
        "balance_checks": balance,
        "positive_fold_count": sum(float(value) > 0.0 for value in deltas),
        "passed": all(original.values()) and all(balance.values()),
    }


def _old_risk(b0: Mapping[str, Any], b2: Mapping[str, Any]) -> dict[str, Any]:
    drops = [
        float(b0["per_class_accuracy"][label])
        - float(b2["per_class_accuracy"][label])
        for label in range(10)
    ]
    classes = [label for label, drop in enumerate(drops) if drop > 0.02]
    return {
        "threshold": 0.02,
        "drops": drops,
        "classes": classes,
        "flagged": bool(classes),
        "changes_gate": False,
    }


def _load_original(path: Path, expected_sha: str, seed: int) -> dict[str, Any]:
    if _sha256(path) != expected_sha.lower():
        raise ValueError("audit mismatch: original input SHA256")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    required = (
        "source_features",
        "source_labels",
        "source_paths",
        "target_features",
        "target_labels",
        "target_paths",
    )
    if (
        not isinstance(payload, dict)
        or payload.get("seed") != seed
        or any(name not in payload for name in required)
    ):
        raise ValueError("audit mismatch: original input")
    return payload


def audit_b2_class12_seed(
    *,
    result_root: Path,
    statistics_root: Path,
    learner_root: Path,
    evaluation_root: Path,
    original_input_path: Path,
    expected_original_input_sha256: str,
    audit_root: Path,
    seed: int,
    classes: int = 13,
    n_folds: int = 5,
    mode: str = "formal",
) -> dict[str, Any]:
    result_root, statistics_root, learner_root, evaluation_root = map(
        Path, (result_root, statistics_root, learner_root, evaluation_root)
    )
    original_input_path, audit_root = map(Path, (original_input_path, audit_root))
    if audit_root.exists() or any(audit_root.parent.glob(audit_root.name + ".tmp.*")):
        raise FileExistsError("audit output root already exists")
    if classes != 13 or n_folds != 5 or mode not in {"formal", "contract-test"}:
        raise ValueError("audit mismatch: formal dimensions")
    _verify_tree(result_root, RESULT_BUSINESS)
    _verify_tree(statistics_root)
    _verify_tree(learner_root)
    _verify_tree(evaluation_root)
    request = _read_json(result_root / "request.json")
    protocol = _read_json(result_root / "protocol.json")
    if (
        request.get("schema") != "b2_class12_seed_request_v1"
        or request.get("mode") != mode
        or request.get("seed") != seed
        or request.get("schemes") != ["b0", "b2"]
        or request.get("b1_role") != "independent_auditor_only"
        or request.get("access") != ACCESS
        or protocol.get("no_rerun_369_diagnostic") is not True
    ):
        raise ValueError("audit mismatch: access or protocol")
    original = _load_original(
        original_input_path, expected_original_input_sha256, seed
    )
    statistics = torch.load(
        statistics_root / "sufficient_statistics.pt",
        map_location="cpu",
        weights_only=False,
    )
    learner = torch.load(
        learner_root / "class12_fit.pt", map_location="cpu", weights_only=False
    )
    evaluator = torch.load(
        evaluation_root / "outer_holdout.pt", map_location="cpu", weights_only=False
    )
    if any(
        not isinstance(payload, dict)
        or payload.get("seed") != seed
        or len(payload.get("folds", [])) != n_folds
        for payload in (statistics, learner, evaluator)
    ):
        raise ValueError("audit mismatch: input schemas")
    published_rows = _read_jsonl(result_root / "predictions.jsonl")
    expected_rows = []
    fold_metrics = []
    aggregate_labels: list[int] = []
    aggregate_predictions = {"b0": [], "b2": []}
    b1_b2_weight_max = 0.0
    b1_b2_bias_max = 0.0
    b1_b2_logit_max = 0.0
    evaluator_path_to_fold = {}
    for fold_row in evaluator["folds"]:
        for path_value in fold_row["paths"]:
            if path_value in evaluator_path_to_fold:
                raise ValueError("audit mismatch: evaluator identity duplication")
            evaluator_path_to_fold[path_value] = fold_row["fold"]
    try:
        source_folds = [evaluator_path_to_fold[path] for path in original["source_paths"]]
        target_folds = [evaluator_path_to_fold[path] for path in original["target_paths"]]
    except KeyError as error:
        raise ValueError("audit mismatch: original identity coverage") from error
    for fold in range(n_folds):
        stats_row = statistics["folds"][fold]
        class12_x = learner["folds"][fold]["features"].detach().cpu().to(torch.float64)
        class12_y = learner["folds"][fold]["labels"].detach().cpu().to(torch.long)
        old_state = {
            name: stats_row[name]
            for name in ("n", "sum_x", "sum_y", "sum_xx", "sum_xy")
        }
        b2_state = _merge(
            _expand(old_state, classes), _stats(class12_x, class12_y, classes=classes)
        )
        b2_weight, b2_bias = _solve(b2_state)
        source_indices = torch.tensor(
            [index for index, assigned in enumerate(source_folds) if assigned != fold],
            dtype=torch.long,
        )
        class11_indices = torch.tensor(
            [
                index
                for index, (assigned, label) in enumerate(
                    zip(target_folds, original["target_labels"].tolist(), strict=True)
                )
                if assigned != fold and label == 11
            ],
            dtype=torch.long,
        )
        batch_x = torch.cat(
            [
                original["source_features"][source_indices].to(torch.float64),
                original["target_features"][class11_indices].to(torch.float64),
                class12_x,
            ]
        )
        batch_y = torch.cat(
            [
                original["source_labels"][source_indices].to(torch.long),
                original["target_labels"][class11_indices].to(torch.long),
                class12_y,
            ]
        )
        b1_weight, b1_bias = _batch(batch_x, batch_y, classes=classes)
        b1_b2_weight_max = max(
            b1_b2_weight_max,
            float(torch.max(torch.abs(b1_weight - b2_weight))),
        )
        b1_b2_bias_max = max(
            b1_b2_bias_max, float(torch.max(torch.abs(b1_bias - b2_bias)))
        )
        evaluator_row = evaluator["folds"][fold]
        features = evaluator_row["features"].detach().cpu().to(torch.float64)
        labels = evaluator_row["labels"].detach().cpu().to(torch.long)
        raw_scores = evaluator_row["raw_scores"].detach().cpu().to(torch.float64)
        b1_scores = features @ b1_weight + b1_bias
        b2_scores = features @ b2_weight + b2_bias
        b1_b2_logit_max = max(
            b1_b2_logit_max, float(torch.max(torch.abs(b1_scores - b2_scores)))
        )
        b1_predictions = b1_scores.argmax(1)
        b2_predictions = b2_scores.argmax(1)
        if not torch.equal(b1_predictions, b2_predictions):
            raise ValueError("audit mismatch: B1/B2 predictions")
        predictions = {"b0": raw_scores.argmax(1), "b2": b2_predictions}
        metrics = {
            name: _summary(labels, prediction)
            for name, prediction in predictions.items()
        }
        fold_metrics.append({"fold": fold, **metrics})
        aggregate_labels.extend(labels.tolist())
        for name in aggregate_predictions:
            aggregate_predictions[name].extend(predictions[name].tolist())
        for index, path_value in enumerate(evaluator_row["paths"]):
            expected_rows.append(
                {
                    "path": path_value,
                    "label": int(labels[index]),
                    "fold": fold,
                    "raw_scores": raw_scores[index].tolist(),
                    "ridge_scores": b2_scores[index].tolist(),
                    "b0_prediction": int(predictions["b0"][index]),
                    "b2_prediction": int(predictions["b2"][index]),
                }
            )
    if (
        b1_b2_weight_max > 1e-10
        or b1_b2_bias_max > 1e-10
        or b1_b2_logit_max > 1e-9
    ):
        raise ValueError("audit mismatch: B1/B2 equivalence")
    if not _prediction_rows_match(published_rows, expected_rows, atol=1e-9):
        raise ValueError("audit mismatch: predictions")
    truth = torch.tensor(aggregate_labels, dtype=torch.long)
    aggregate = {
        name: _summary(truth, torch.tensor(values, dtype=torch.long))
        for name, values in aggregate_predictions.items()
    }
    expected_metrics = {"folds": fold_metrics, "aggregate": aggregate}
    if _read_json(result_root / "fold_metrics.json") != expected_metrics:
        raise ValueError("audit mismatch: metrics")
    expected_confusions = {
        name: summary["confusion_matrix"] for name, summary in aggregate.items()
    }
    if _read_json(result_root / "confusion_matrices.json") != expected_confusions:
        raise ValueError("audit mismatch: confusion")
    deltas = [
        row["b2"]["triple_harmonic_accuracy"]
        - row["b0"]["triple_harmonic_accuracy"]
        for row in fold_metrics
    ]
    checks = _checks(aggregate["b0"], aggregate["b2"], deltas)
    risk = _old_risk(aggregate["b0"], aggregate["b2"])
    expected_gate = {
        "schema": "b2_class12_seed_runner_gate_v1",
        "status": "pending_independent_audit",
        "provisional_checks_assuming_equivalence_and_audit": checks,
        "fold_triple_h_deltas": deltas,
        "old_class_risk": risk,
    }
    if _read_json(result_root / "gate.json") != expected_gate:
        raise ValueError("audit mismatch: gate")
    stats_bytes = max(
        sum(
            row[name].numel() * row[name].element_size()
            for name in ("sum_x", "sum_y", "sum_xx", "sum_xy")
        )
        for row in statistics["folds"]
    )
    class12_bytes = max(
        row["features"].numel() * row["features"].element_size()
        for row in learner["folds"]
    )
    expected_memory = {
        "old_aggregate_bytes": stats_bytes,
        "class12_current_fit_bytes": class12_bytes,
        "learner_total_bytes": stats_bytes + class12_bytes,
        "old_class_per_sample_available_to_learner": False,
    }
    if _read_json(result_root / "memory_report.json") != expected_memory:
        raise ValueError("audit mismatch: memory")
    report = {
        "schema": "b2_class12_seed_audit_v1",
        "all_pass": True,
        "seed": seed,
        "b1_b2_equivalence_passed": True,
        "b1_b2_weight_max_abs": b1_b2_weight_max,
        "b1_b2_bias_max_abs": b1_b2_bias_max,
        "b1_b2_logit_max_abs": b1_b2_logit_max,
        "predictions_exact": True,
        "confusions_exact": True,
        "metrics_exact": True,
        "gate_exact": True,
        "access_flags_pass": True,
    }
    audited_gate = {
        "schema": "b2_class12_seed_audited_gate_v1",
        "seed": seed,
        "checks": checks,
        "old_class_risk": risk,
        "performance_passed": checks["passed"],
    }
    temporary = audit_root.with_name(audit_root.name + ".tmp." + uuid.uuid4().hex)
    audit_root.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()
    try:
        _write_json(temporary / "audit_report.json", report)
        _write_json(temporary / "audited_gate.json", audited_gate)
        _write_json(
            temporary / "artifact_sha256.json",
            {
                name: _sha256(temporary / name)
                for name in ("audit_report.json", "audited_gate.json")
            },
        )
        _write_json(
            temporary / "COMPLETE.json",
            {
                "schema": "b2_class12_seed_audit_complete_v1",
                "status": "complete",
                "artifact_manifest_sha256": _sha256(
                    temporary / "artifact_sha256.json"
                ),
            },
        )
        os.replace(temporary, audit_root)
    except Exception:
        if temporary.exists():
            for path in temporary.iterdir():
                path.unlink()
            temporary.rmdir()
        raise
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--statistics-root", type=Path, required=True)
    parser.add_argument("--learner-root", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument("--original-input", type=Path, required=True)
    parser.add_argument("--original-input-sha256", required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    audit_b2_class12_seed(
        result_root=args.result_root,
        statistics_root=args.statistics_root,
        learner_root=args.learner_root,
        evaluation_root=args.evaluation_root,
        original_input_path=args.original_input,
        expected_original_input_sha256=args.original_input_sha256,
        audit_root=args.audit_root,
        seed=args.seed,
    )
    print("B2_CLASS12_SEED_AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
