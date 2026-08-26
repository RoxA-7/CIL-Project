from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid
from typing import Any, Mapping

import torch

from lwf_revision.b2_class12_multiseed import (
    b2_confirmation_checks,
    old_class_risk_flags,
)
from lwf_revision.recursive_centered_ridge import RidgeSufficientStatistics
from lwf_revision.recursive_ridge_class12_sequence import summarize_class12_predictions


BUSINESS_FILES = (
    "request.json",
    "protocol.json",
    "input_sha256.json",
    "fold_metrics.json",
    "predictions.jsonl",
    "confusion_matrices.json",
    "gate.json",
    "memory_report.json",
)
ACCESS = {
    "validation": False,
    "official_test": False,
    "final": False,
    "class12_test": False,
}
RIDGE = {
    "dtype": "float64",
    "l2": 1.0,
    "centered": True,
    "weight_bias_atol": 1e-10,
    "logit_atol": 1e-9,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _head_sha256(weight: torch.Tensor, bias: torch.Tensor) -> str:
    digest = hashlib.sha256()
    digest.update(str(tuple(weight.shape)).encode("ascii"))
    digest.update(weight.detach().cpu().contiguous().numpy().tobytes())
    digest.update(str(tuple(bias.shape)).encode("ascii"))
    digest.update(bias.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _verify_tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise ValueError("signed input tree is missing")
    manifest = _read_json(root / "artifact_sha256.json")
    if (
        not manifest
        or {path.name for path in root.iterdir()}
        != set(manifest) | {"artifact_sha256.json", "COMPLETE.json"}
    ):
        raise ValueError("signed input tree contents mismatch")
    for name, digest in manifest.items():
        if Path(name).name != name or _sha256(root / name) != digest:
            raise ValueError("signed input tree SHA256 mismatch")
    complete = _read_json(root / "COMPLETE.json")
    if (
        complete.get("status") != "complete"
        or complete.get("artifact_manifest_sha256")
        != _sha256(root / "artifact_sha256.json")
    ):
        raise ValueError("signed input tree COMPLETE mismatch")
    return {str(name): str(digest) for name, digest in manifest.items()}


def _binding_valid(binding: Mapping[str, Any], *, n_folds: int) -> bool:
    hashes = binding.get("fold_head_sha256")
    return bool(
        binding.get("schema") == "b2_class12_head_binding_v1"
        and binding.get("heads_frozen_before_holdout") is True
        and type(binding.get("freeze_event")) is int
        and type(binding.get("holdout_access_event")) is int
        and binding["freeze_event"] < binding["holdout_access_event"]
        and isinstance(hashes, list)
        and len(hashes) == n_folds
        and all(isinstance(value, str) and len(value) == 64 for value in hashes)
    )


def load_canonical_heads(
    *,
    canonical_root: Path,
    statistics: Mapping[str, Any],
    learner: Mapping[str, Any],
    seed: int,
    classes: int,
    n_folds: int,
) -> tuple[list[tuple[torch.Tensor, torch.Tensor]], dict[str, Any]]:
    canonical_root = Path(canonical_root)
    _verify_tree(canonical_root)
    payload = torch.load(
        canonical_root / "canonical_heads.pt", map_location="cpu", weights_only=False
    )
    binding = _read_json(canonical_root / "head_binding.json")
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "b2_class12_canonical_heads_v1"
        or payload.get("seed") != seed
        or payload.get("classes") != classes
        or len(payload.get("folds", [])) != n_folds
        or binding.get("schema") != "b2_class12_canonical_head_binding_v1"
        or binding.get("seed") != seed
        or binding.get("threads") != 1
    ):
        raise ValueError("canonical head contract mismatch")
    heads = []
    max_weight = 0.0
    max_bias = 0.0
    for fold in range(n_folds):
        row = payload["folds"][fold]
        weight, bias = row.get("weight"), row.get("bias")
        if (
            row.get("fold") != fold
            or not isinstance(weight, torch.Tensor)
            or not isinstance(bias, torch.Tensor)
            or weight.shape[1] != classes
            or bias.shape != (classes,)
            or _head_sha256(weight, bias) != row.get("sha256")
            or row.get("sha256") != binding["fold_head_sha256"][fold]
        ):
            raise ValueError("canonical head artifact mismatch")
        stats_row = statistics["folds"][fold]
        learner_row = learner["folds"][fold]
        old = RidgeSufficientStatistics.from_dict(
            {name: stats_row[name] for name in ("n", "sum_x", "sum_y", "sum_xx", "sum_xy")}
        )
        current = RidgeSufficientStatistics.from_samples(
            learner_row["features"], learner_row["labels"], classes=classes
        )
        recomputed_weight, recomputed_bias = old.expand_classes(classes).merge(current).solve(l2=1.0)
        max_weight = max(max_weight, float(torch.max(torch.abs(weight - recomputed_weight))))
        max_bias = max(max_bias, float(torch.max(torch.abs(bias - recomputed_bias))))
        heads.append((weight, bias))
    if max_weight > RIDGE["weight_bias_atol"] or max_bias > RIDGE["weight_bias_atol"]:
        raise ValueError("canonical head numerical equivalence mismatch")
    return heads, {
        "used": True,
        "max_weight_abs": max_weight,
        "max_bias_abs": max_bias,
        "manifest_sha256": _sha256(canonical_root / "artifact_sha256.json"),
    }


def run_b2_class12_seed(
    *,
    protocol_path: Path,
    expected_protocol_sha256: str,
    statistics_root: Path,
    statistics_audit_root: Path,
    learner_root: Path,
    evaluation_root: Path,
    result_root: Path,
    seed: int,
    canonical_head_root: Path | None = None,
    classes: int = 13,
    n_folds: int = 5,
    mode: str = "formal",
) -> None:
    protocol_path, statistics_root, statistics_audit_root = map(
        Path, (protocol_path, statistics_root, statistics_audit_root)
    )
    learner_root, evaluation_root, result_root = map(
        Path, (learner_root, evaluation_root, result_root)
    )
    if result_root.exists() or any(result_root.parent.glob(result_root.name + ".tmp.*")):
        raise FileExistsError("output root conflict")
    if _sha256(protocol_path) != expected_protocol_sha256.lower():
        raise ValueError("protocol SHA256 mismatch")
    protocol = _read_json(protocol_path)
    if (
        protocol.get("schema") != "b2_class12_multiseed_protocol_v1"
        or protocol.get("status") != "implementation_plan_approved_not_run"
        or protocol.get("schemes") != ["b0", "b1_audit_only", "b2"]
        or protocol.get("ridge") != RIDGE
        or protocol.get("access") != ACCESS
        or protocol.get("no_rerun_369_diagnostic") is not True
        or seed not in protocol.get("formal_seeds", [])
        or mode not in {"formal", "contract-test"}
        or classes != 13
        or n_folds != 5
    ):
        raise ValueError("protocol binding is invalid")
    _verify_tree(statistics_root)
    _verify_tree(statistics_audit_root)
    _verify_tree(learner_root)
    _verify_tree(evaluation_root)
    if _read_json(statistics_audit_root / "audit_report.json").get("all_pass") is not True:
        raise ValueError("statistics audit must pass")
    binding = _read_json(evaluation_root / "head_binding.json")
    if not _binding_valid(binding, n_folds=n_folds):
        raise ValueError("frozen head binding is invalid")

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
    expected_schemas = (
        (statistics, "recursive_ridge_sufficient_statistics_v1"),
        (learner, "b2_class12_fit_features_v1"),
        (evaluator, "b2_class12_outer_holdout_v1"),
    )
    for payload, schema in expected_schemas:
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != schema
            or payload.get("seed") != seed
            or len(payload.get("folds", [])) != n_folds
        ):
            raise ValueError("seed input schema mismatch")
    canonical_heads = None
    canonical_report = {"used": False}
    if canonical_head_root is not None:
        canonical_heads, canonical_report = load_canonical_heads(
            canonical_root=canonical_head_root,
            statistics=statistics,
            learner=learner,
            seed=seed,
            classes=classes,
            n_folds=n_folds,
        )

    rows: list[dict[str, Any]] = []
    fold_metrics = []
    aggregate_labels: list[int] = []
    aggregate_predictions = {"b0": [], "b2": []}
    computed_head_sha = []
    for fold in range(n_folds):
        stats_row = statistics["folds"][fold]
        learner_row = learner["folds"][fold]
        evaluator_row = evaluator["folds"][fold]
        if any(row.get("fold") != fold for row in (stats_row, learner_row, evaluator_row)):
            raise ValueError("fold order mismatch")
        old_stats = RidgeSufficientStatistics.from_dict(
            {
                name: stats_row[name]
                for name in ("n", "sum_x", "sum_y", "sum_xx", "sum_xy")
            }
        )
        fit_x = learner_row.get("features")
        fit_y = learner_row.get("labels")
        if not isinstance(fit_x, torch.Tensor) or not isinstance(fit_y, torch.Tensor):
            raise ValueError("learner fold is invalid")
        current_stats = RidgeSufficientStatistics.from_samples(
            fit_x, fit_y, classes=classes
        )
        weight, bias = old_stats.expand_classes(classes).merge(current_stats).solve(
            l2=1.0
        )
        computed_head_sha.append(_head_sha256(weight, bias))
        if canonical_heads is not None:
            weight, bias = canonical_heads[fold]
        features = evaluator_row.get("features")
        labels = evaluator_row.get("labels")
        raw_scores = evaluator_row.get("raw_scores")
        paths = evaluator_row.get("paths")
        if (
            not isinstance(features, torch.Tensor)
            or not isinstance(labels, torch.Tensor)
            or not isinstance(raw_scores, torch.Tensor)
            or not isinstance(paths, list)
            or features.shape[0] != labels.shape[0]
            or raw_scores.shape != (features.shape[0], classes)
            or len(paths) != features.shape[0]
            or len(set(paths)) != len(paths)
        ):
            raise ValueError("evaluation fold is invalid")
        values = features.detach().cpu().to(torch.float64)
        ridge_scores = values @ weight + bias
        predictions = {
            "b0": raw_scores.argmax(1).to(torch.long),
            "b2": ridge_scores.argmax(1).to(torch.long),
        }
        truth = labels.detach().cpu().to(torch.long)
        metrics = {
            name: summarize_class12_predictions(truth, prediction, classes=classes)
            for name, prediction in predictions.items()
        }
        fold_metrics.append({"fold": fold, **metrics})
        aggregate_labels.extend(truth.tolist())
        for name in aggregate_predictions:
            aggregate_predictions[name].extend(predictions[name].tolist())
        for index, path_value in enumerate(paths):
            rows.append(
                {
                    "path": path_value,
                    "label": int(truth[index]),
                    "fold": fold,
                    "raw_scores": raw_scores[index]
                    .detach()
                    .cpu()
                    .to(torch.float64)
                    .tolist(),
                    "ridge_scores": ridge_scores[index].tolist(),
                    "b0_prediction": int(predictions["b0"][index]),
                    "b2_prediction": int(predictions["b2"][index]),
                }
            )
    legacy_binding_exact = computed_head_sha == binding["fold_head_sha256"]
    if not legacy_binding_exact and canonical_heads is None:
        raise ValueError("frozen head binding does not match computed heads")
    if len({row["path"] for row in rows}) != len(rows):
        raise ValueError("OOF identities are duplicated")
    truth = torch.tensor(aggregate_labels, dtype=torch.long)
    aggregate = {
        name: summarize_class12_predictions(
            truth, torch.tensor(values, dtype=torch.long), classes=classes
        )
        for name, values in aggregate_predictions.items()
    }
    deltas = [
        row["b2"]["triple_harmonic_accuracy"]
        - row["b0"]["triple_harmonic_accuracy"]
        for row in fold_metrics
    ]
    provisional_checks = b2_confirmation_checks(
        b0=aggregate["b0"],
        b2=aggregate["b2"],
        triple_h_fold_deltas=deltas,
        truth_passed=True,
        equivalence_passed=True,
        audit_passed=True,
    )
    old_risk = old_class_risk_flags(b0=aggregate["b0"], b2=aggregate["b2"])
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
    temporary = result_root.with_name(result_root.name + ".tmp." + uuid.uuid4().hex)
    result_root.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()
    try:
        _write_json(
            temporary / "request.json",
            {
                "schema": "b2_class12_seed_request_v1",
                "mode": mode,
                "seed": seed,
                "schemes": ["b0", "b2"],
                "b1_role": "independent_auditor_only",
                "access": ACCESS,
            },
        )
        _write_json(temporary / "protocol.json", protocol)
        _write_json(
            temporary / "input_sha256.json",
            {
                "protocol": expected_protocol_sha256.lower(),
                "statistics_manifest": _sha256(
                    statistics_root / "artifact_sha256.json"
                ),
                "statistics_audit_manifest": _sha256(
                    statistics_audit_root / "artifact_sha256.json"
                ),
                "learner_manifest": _sha256(learner_root / "artifact_sha256.json"),
                "evaluation_manifest": _sha256(
                    evaluation_root / "artifact_sha256.json"
                ),
                "computed_fold_head_sha256": computed_head_sha,
                "legacy_binding_exact": legacy_binding_exact,
                "canonical_head": canonical_report,
            },
        )
        _write_json(
            temporary / "fold_metrics.json",
            {"folds": fold_metrics, "aggregate": aggregate},
        )
        _write_jsonl(temporary / "predictions.jsonl", rows)
        _write_json(
            temporary / "confusion_matrices.json",
            {
                name: metrics["confusion_matrix"]
                for name, metrics in aggregate.items()
            },
        )
        _write_json(
            temporary / "gate.json",
            {
                "schema": "b2_class12_seed_runner_gate_v1",
                "status": "pending_independent_audit",
                "provisional_checks_assuming_equivalence_and_audit": provisional_checks,
                "fold_triple_h_deltas": deltas,
                "old_class_risk": old_risk,
            },
        )
        _write_json(
            temporary / "memory_report.json",
            {
                "old_aggregate_bytes": stats_bytes,
                "class12_current_fit_bytes": class12_bytes,
                "learner_total_bytes": stats_bytes + class12_bytes,
                "old_class_per_sample_available_to_learner": False,
            },
        )
        _write_json(
            temporary / "artifact_sha256.json",
            {name: _sha256(temporary / name) for name in BUSINESS_FILES},
        )
        _write_json(
            temporary / "COMPLETE.json",
            {
                "schema": "b2_class12_seed_complete_v1",
                "status": "complete",
                "artifact_manifest_sha256": _sha256(
                    temporary / "artifact_sha256.json"
                ),
            },
        )
        os.replace(temporary, result_root)
    except Exception:
        if temporary.exists():
            for path in temporary.iterdir():
                path.unlink()
            temporary.rmdir()
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--statistics-root", type=Path, required=True)
    parser.add_argument("--statistics-audit-root", type=Path, required=True)
    parser.add_argument("--learner-root", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--canonical-head-root", type=Path)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    run_b2_class12_seed(
        protocol_path=args.protocol,
        expected_protocol_sha256=args.protocol_sha256,
        statistics_root=args.statistics_root,
        statistics_audit_root=args.statistics_audit_root,
        learner_root=args.learner_root,
        evaluation_root=args.evaluation_root,
        result_root=args.result_root,
        canonical_head_root=args.canonical_head_root,
        seed=args.seed,
    )
    print("B2_CLASS12_SEED_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
