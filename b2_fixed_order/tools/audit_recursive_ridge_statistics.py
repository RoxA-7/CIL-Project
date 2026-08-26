from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import uuid
from typing import Any, Mapping

import torch
import torch.nn.functional as F

from lwf_revision.balanced_global_ridge_oof import assign_balanced_folds


_BUSINESS_FILES = [
    "request.json",
    "input_sha256.json",
    "equivalence.json",
    "sufficient_statistics.pt",
    "memory_report.json",
]
_TREE_FILES = set(_BUSINESS_FILES) | {"artifact_sha256.json", "COMPLETE.json"}
_STAT_FIELDS = {"n", "sum_x", "sum_y", "sum_xx", "sum_xy"}
_FORMAL_SCHEMAS = {"b2_feature_input_v1"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str):
        raise ValueError(f"non-finite JSON constant: {value}")

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    return payload


def _verify_tree(root: Path) -> None:
    if not root.is_dir() or {path.name for path in root.iterdir()} != _TREE_FILES:
        raise ValueError("audit mismatch: statistics tree files")
    manifest = _read_json(root / "artifact_sha256.json")
    if set(manifest) != set(_BUSINESS_FILES):
        raise ValueError("audit mismatch: artifact manifest fields")
    for name in _BUSINESS_FILES:
        if manifest[name] != _sha256(root / name):
            raise ValueError("audit mismatch: artifact SHA256")
    complete = _read_json(root / "COMPLETE.json")
    if complete != {
        "schema": "recursive_ridge_statistics_complete_v1",
        "status": "complete",
        "artifact_manifest_sha256": _sha256(root / "artifact_sha256.json"),
    }:
        raise ValueError("audit mismatch: COMPLETE binding")


def _matrix(value: Any, *, name: str) -> torch.Tensor:
    if not isinstance(value, torch.Tensor) or value.ndim != 2:
        raise ValueError(f"audit mismatch: {name}")
    result = value.detach().cpu().to(torch.float64)
    if result.shape[0] == 0 or result.shape[1] == 0 or not torch.isfinite(result).all():
        raise ValueError(f"audit mismatch: {name}")
    return result.contiguous()


def _labels(value: Any, *, rows: int, classes: int, name: str) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.ndim != 1
        or value.dtype == torch.bool
        or value.is_floating_point()
    ):
        raise ValueError(f"audit mismatch: {name}")
    result = value.detach().cpu().to(torch.long)
    if result.shape != (rows,) or torch.any(result < 0) or torch.any(result >= classes):
        raise ValueError(f"audit mismatch: {name}")
    return result.contiguous()


def _load_input(path: Path, *, seed: int, classes: int, mode: str) -> dict[str, Any]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict):
        raise ValueError("audit mismatch: input root")
    allowed = _FORMAL_SCHEMAS | {"recursive_ridge_contract_test_input_v1"}
    if payload.get("schema") not in allowed:
        raise ValueError("audit mismatch: input schema")
    if mode == "formal" and payload.get("schema") not in _FORMAL_SCHEMAS:
        raise ValueError("audit mismatch: formal input schema")
    if payload.get("seed") != seed or type(payload.get("seed")) is not int:
        raise ValueError("audit mismatch: input seed")
    source_x = _matrix(payload.get("source_features"), name="source_features")
    target_x = _matrix(payload.get("target_features"), name="target_features")
    if source_x.shape[1] != target_x.shape[1]:
        raise ValueError("audit mismatch: feature dimension")
    source_y = _labels(
        payload.get("source_labels"), rows=source_x.shape[0], classes=classes, name="source_labels"
    )
    target_y = _labels(
        payload.get("target_labels"), rows=target_x.shape[0], classes=classes, name="target_labels"
    )
    source_paths = payload.get("source_paths")
    target_paths = payload.get("target_paths")
    mapping = payload.get("source_to_target")
    if (
        not isinstance(source_paths, (list, tuple))
        or len(source_paths) != source_x.shape[0]
        or not isinstance(target_paths, (list, tuple))
        or len(target_paths) != target_x.shape[0]
        or not isinstance(mapping, (list, tuple))
        or len(mapping) != source_x.shape[0]
    ):
        raise ValueError("audit mismatch: identity dimensions")
    if any(not isinstance(path_value, str) or not path_value for path_value in source_paths):
        raise ValueError("audit mismatch: source identities")
    if any(not isinstance(path_value, str) or not path_value for path_value in target_paths):
        raise ValueError("audit mismatch: target identities")
    target_by_path = {path_value: index for index, path_value in enumerate(target_paths)}
    expected_mapping = []
    for index, path_value in enumerate(source_paths):
        target_index = target_by_path.get(path_value)
        if target_index is None or int(source_y[index]) != int(target_y[target_index]):
            raise ValueError("audit mismatch: identity alignment")
        expected_mapping.append(target_index)
    if list(mapping) != expected_mapping:
        raise ValueError("audit mismatch: source_to_target")
    if set(source_y.tolist()) != set(range(classes - 1)):
        raise ValueError("audit mismatch: source class coverage")
    if set(target_y.tolist()) != set(range(classes)):
        raise ValueError("audit mismatch: target class coverage")
    return {
        "source_x": source_x,
        "source_y": source_y,
        "source_paths": list(source_paths),
        "target_x": target_x,
        "target_y": target_y,
        "target_paths": list(target_paths),
        "mapping": expected_mapping,
    }


def _stats(x: torch.Tensor, y: torch.Tensor, *, classes: int) -> dict[str, Any]:
    targets = F.one_hot(y, num_classes=classes).to(torch.float64)
    return {
        "n": int(x.shape[0]),
        "sum_x": x.sum(dim=0),
        "sum_y": targets.sum(dim=0),
        "sum_xx": x.T @ x,
        "sum_xy": x.T @ targets,
    }


def _expand(state: dict[str, Any], classes: int) -> dict[str, Any]:
    current = int(state["sum_y"].shape[0])
    if classes < current:
        raise ValueError("audit mismatch: class shrink")
    result = {name: value.clone() if isinstance(value, torch.Tensor) else value for name, value in state.items()}
    if classes > current:
        result["sum_y"] = F.pad(state["sum_y"], (0, classes - current))
        result["sum_xy"] = F.pad(state["sum_xy"], (0, classes - current))
    return result


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if left["sum_x"].shape != right["sum_x"].shape or left["sum_y"].shape != right["sum_y"].shape:
        raise ValueError("audit mismatch: aggregate dimensions")
    return {
        "n": left["n"] + right["n"],
        "sum_x": left["sum_x"] + right["sum_x"],
        "sum_y": left["sum_y"] + right["sum_y"],
        "sum_xx": left["sum_xx"] + right["sum_xx"],
        "sum_xy": left["sum_xy"] + right["sum_xy"],
    }


def _solve(state: dict[str, Any]) -> tuple[torch.Tensor, torch.Tensor]:
    n = state["n"]
    x_mean = state["sum_x"] / n
    y_mean = state["sum_y"] / n
    gram = state["sum_xx"] - torch.outer(state["sum_x"], state["sum_x"]) / n
    rhs = state["sum_xy"] - torch.outer(state["sum_x"], state["sum_y"]) / n
    regularized = gram.clone()
    regularized.diagonal().add_(1.0)
    weight = torch.linalg.solve(regularized, rhs)
    bias = y_mean - x_mean @ weight
    return weight.contiguous(), bias.contiguous()


def _batch(x: torch.Tensor, y: torch.Tensor, *, classes: int) -> tuple[torch.Tensor, torch.Tensor]:
    targets = F.one_hot(y, num_classes=classes).to(torch.float64)
    x_mean = x.mean(dim=0)
    y_mean = targets.mean(dim=0)
    centered_x = x - x_mean
    centered_y = targets - y_mean
    gram = centered_x.T @ centered_x
    gram.diagonal().add_(1.0)
    weight = torch.linalg.solve(gram, centered_x.T @ centered_y)
    return weight.contiguous(), (y_mean - x_mean @ weight).contiguous()


def _head_sha(weight: torch.Tensor, bias: torch.Tensor) -> str:
    digest = hashlib.sha256()
    digest.update(str(tuple(weight.shape)).encode("ascii"))
    digest.update(weight.contiguous().numpy().tobytes())
    digest.update(str(tuple(bias.shape)).encode("ascii"))
    digest.update(bias.contiguous().numpy().tobytes())
    return digest.hexdigest()


def _confusion(labels: torch.Tensor, predictions: torch.Tensor, classes: int) -> list[list[int]]:
    matrix = torch.zeros((classes, classes), dtype=torch.int64)
    for actual, predicted in zip(labels.tolist(), predictions.tolist(), strict=True):
        matrix[actual, predicted] += 1
    return matrix.tolist()


def _metrics(labels: torch.Tensor, predictions: torch.Tensor, classes: int) -> dict[str, Any]:
    matrix = torch.tensor(_confusion(labels, predictions, classes))
    totals = matrix.sum(dim=1)
    return {
        "overall_accuracy": int(matrix.diagonal().sum()) / int(matrix.sum()),
        "per_class_accuracy": [
            int(matrix[label, label]) / int(totals[label]) for label in range(classes)
        ],
        "total_count": int(matrix.sum()),
        "total_correct": int(matrix.diagonal().sum()),
    }


def _equivalence(
    fit_x: torch.Tensor,
    fit_y: torch.Tensor,
    holdout_x: torch.Tensor,
    holdout_y: torch.Tensor,
    *,
    classes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    one = _stats(fit_x, fit_y, classes=classes)
    class_states = [_stats(fit_x[fit_y == label], fit_y[fit_y == label], classes=classes) for label in range(classes)]
    by_class = class_states[0]
    for state in class_states[1:]:
        by_class = _merge(by_class, state)
    base = fit_y < classes - 2
    penultimate = fit_y == classes - 2
    newest = fit_y == classes - 1
    by_stage = _stats(fit_x[base], fit_y[base], classes=classes - 2)
    by_stage = _merge(
        _expand(by_stage, classes - 1),
        _stats(fit_x[penultimate], fit_y[penultimate], classes=classes - 1),
    )
    by_stage = _merge(
        _expand(by_stage, classes),
        _stats(fit_x[newest], fit_y[newest], classes=classes),
    )
    heads = {
        "c0": _batch(fit_x, fit_y, classes=classes),
        "c1": _solve(one),
        "c2": _solve(by_class),
        "c3": _solve(by_stage),
    }
    scores = {name: holdout_x @ head[0] + head[1] for name, head in heads.items()}
    predictions_t = {name: value.argmax(dim=1) for name, value in scores.items()}
    predictions = {name: value.tolist() for name, value in predictions_t.items()}
    confusions = {name: _confusion(holdout_y, value, classes) for name, value in predictions_t.items()}
    metrics = {name: _metrics(holdout_y, value, classes) for name, value in predictions_t.items()}
    reference_weight, reference_bias = heads["c0"]
    weight_max = max(float(torch.max(torch.abs(head[0] - reference_weight))) for name, head in heads.items() if name != "c0")
    bias_max = max(float(torch.max(torch.abs(head[1] - reference_bias))) for name, head in heads.items() if name != "c0")
    logit_max = max(float(torch.max(torch.abs(value - scores["c0"]))) for name, value in scores.items() if name != "c0")
    pred_exact = all(value == predictions["c0"] for value in predictions.values())
    confusion_exact = all(value == confusions["c0"] for value in confusions.values())
    metrics_exact = all(value == metrics["c0"] for value in metrics.values())
    all_pass = pred_exact and confusion_exact and metrics_exact and weight_max <= 1e-10 and bias_max <= 1e-10 and logit_max <= 1e-9
    return (
        {
            "schema": "recursive_ridge_equivalence_v1",
            "all_pass": all_pass,
            "predictions_exact": pred_exact,
            "confusions_exact": confusion_exact,
            "metrics_exact": metrics_exact,
            "weight_max_abs": weight_max,
            "bias_max_abs": bias_max,
            "logit_max_abs": logit_max,
            "head_sha256": {name: _head_sha(*head) for name, head in heads.items()},
            "predictions": predictions,
            "confusion_matrices": confusions,
            "metrics": metrics,
            "tolerances": {"weight_bias_atol": 1e-10, "logit_atol": 1e-9},
        },
        by_stage,
    )


def _same_stats(published: dict[str, Any], expected: dict[str, Any], *, fold: int, classes: int, dimension: int) -> bool:
    if set(published) != _STAT_FIELDS | {"fold", "feature_dimension", "classes"}:
        return False
    if published.get("fold") != fold or published.get("classes") != classes or published.get("feature_dimension") != dimension:
        return False
    if published.get("n") != expected["n"]:
        return False
    return all(
        isinstance(published.get(name), torch.Tensor)
        and published[name].dtype == torch.float64
        and published[name].device.type == "cpu"
        and torch.equal(published[name], expected[name])
        for name in ("sum_x", "sum_y", "sum_xx", "sum_xy")
    )


def _equivalence_reports_match(
    published: Mapping[str, Any], independently_recomputed: Mapping[str, Any]
) -> bool:
    """Compare registered semantics while allowing BLAS-level bit variation.

    CPU linear solvers can return different last bits across separate processes.
    The protocol registers numeric tolerances, exact predictions/confusions/metrics,
    and not bit-identical head bytes across independent solver invocations.
    """

    exact_fields = (
        "schema",
        "all_pass",
        "predictions_exact",
        "confusions_exact",
        "metrics_exact",
        "predictions",
        "confusion_matrices",
        "metrics",
        "tolerances",
        "fold",
    )
    if any(published.get(name) != independently_recomputed.get(name) for name in exact_fields):
        return False
    if any(
        independently_recomputed.get(name) is not True
        for name in ("all_pass", "predictions_exact", "confusions_exact", "metrics_exact")
    ):
        return False
    tolerances = independently_recomputed.get("tolerances")
    if tolerances != {"weight_bias_atol": 1e-10, "logit_atol": 1e-9}:
        return False
    limits = {
        "weight_max_abs": 1e-10,
        "bias_max_abs": 1e-10,
        "logit_max_abs": 1e-9,
    }
    for report in (published, independently_recomputed):
        for name, limit in limits.items():
            value = report.get(name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0.0
                or float(value) > limit
            ):
                return False
        hashes = report.get("head_sha256")
        if not isinstance(hashes, Mapping) or set(hashes) != {"c0", "c1", "c2", "c3"}:
            return False
        if any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in hashes.values()
        ):
            return False
    return True


def audit_recursive_statistics(
    *,
    tree_root: Path,
    input_path: Path,
    expected_input_sha256: str,
    audit_root: Path,
    seed: int,
    classes: int = 12,
    n_folds: int = 5,
    mode: str = "formal",
) -> dict[str, Any]:
    tree_root = Path(tree_root)
    input_path = Path(input_path)
    audit_root = Path(audit_root)
    if audit_root.exists():
        raise FileExistsError("audit output root already exists")
    if _sha256(input_path) != expected_input_sha256.lower():
        raise ValueError("audit mismatch: input SHA256")
    _verify_tree(tree_root)
    request = _read_json(tree_root / "request.json")
    if request != {
        "schema": "recursive_ridge_statistics_request_v1",
        "mode": mode,
        "seed": seed,
        "classes": classes,
        "n_folds": n_folds,
        "l2": 1.0,
        "access": {"validation": False, "official_test": False, "final": False},
    }:
        raise ValueError("audit mismatch: request")
    if _read_json(tree_root / "input_sha256.json") != {
        "input_path": str(input_path),
        "input_sha256": expected_input_sha256.lower(),
    }:
        raise ValueError("audit mismatch: input binding")
    data = _load_input(input_path, seed=seed, classes=classes, mode=mode)
    folds = assign_balanced_folds(
        data["target_y"], data["target_paths"], seed=seed, n_folds=n_folds, classes=classes
    )
    source_folds = [folds[index] for index in data["mapping"]]
    state = torch.load(tree_root / "sufficient_statistics.pt", map_location="cpu", weights_only=False)
    if not isinstance(state, dict) or set(state) != {"schema", "seed", "folds"} or state.get("schema") != "recursive_ridge_sufficient_statistics_v1" or state.get("seed") != seed or not isinstance(state.get("folds"), list) or len(state["folds"]) != n_folds:
        raise ValueError("audit mismatch: learner state schema")
    published_equivalence = _read_json(tree_root / "equivalence.json")
    expected_equivalence_folds = []
    aggregate_bytes = []
    for fold in range(n_folds):
        source_idx = torch.tensor([index for index, value in enumerate(source_folds) if value != fold], dtype=torch.long)
        newest_idx = torch.tensor([index for index, (value, label) in enumerate(zip(folds, data["target_y"].tolist(), strict=True)) if value != fold and label == classes - 1], dtype=torch.long)
        holdout_idx = torch.tensor([index for index, value in enumerate(folds) if value == fold], dtype=torch.long)
        fit_x = torch.cat([data["source_x"][source_idx], data["target_x"][newest_idx]], dim=0)
        fit_y = torch.cat([data["source_y"][source_idx], data["target_y"][newest_idx]], dim=0)
        equivalence, expected_stats = _equivalence(
            fit_x,
            fit_y,
            data["target_x"][holdout_idx],
            data["target_y"][holdout_idx],
            classes=classes,
        )
        equivalence["fold"] = fold
        expected_equivalence_folds.append(equivalence)
        if not _same_stats(state["folds"][fold], expected_stats, fold=fold, classes=classes, dimension=fit_x.shape[1]):
            raise ValueError("audit mismatch: sufficient statistic pollution")
        aggregate_bytes.append(sum(expected_stats[name].numel() * expected_stats[name].element_size() for name in ("sum_x", "sum_y", "sum_xx", "sum_xy")))
    expected_equivalence = {
        "schema": "recursive_ridge_equivalence_folds_v1",
        "seed": seed,
        "all_pass": all(row["all_pass"] for row in expected_equivalence_folds),
        "folds": expected_equivalence_folds,
    }
    if (
        published_equivalence.get("schema") != expected_equivalence["schema"]
        or published_equivalence.get("seed") != seed
        or published_equivalence.get("all_pass") is not True
        or not isinstance(published_equivalence.get("folds"), list)
        or len(published_equivalence["folds"]) != n_folds
        or any(
            not _equivalence_reports_match(published, expected)
            for published, expected in zip(
                published_equivalence["folds"], expected_equivalence_folds, strict=True
            )
        )
    ):
        raise ValueError("audit mismatch: equivalence report")
    per_sample_bytes = data["source_x"].numel() * data["source_x"].element_size()
    deployment_bytes = max(aggregate_bytes)
    expected_memory = {
        "schema": "recursive_ridge_memory_report_v1",
        "aggregate_bytes": deployment_bytes,
        "published_all_folds_aggregate_bytes": sum(aggregate_bytes),
        "per_sample_feature_bytes": per_sample_bytes,
        "aggregate_to_feature_ratio": deployment_bytes / per_sample_bytes,
        "fold_aggregate_bytes": aggregate_bytes,
    }
    if _read_json(tree_root / "memory_report.json") != expected_memory:
        raise ValueError("audit mismatch: memory report")
    report = {
        "schema": "recursive_ridge_statistics_audit_v1",
        "all_pass": True,
        "statistics_exact": True,
        "equivalence_all_pass": expected_equivalence["all_pass"],
        "tree_sha256_pass": True,
        "forbidden_fields_absent": True,
        "access_flags_pass": True,
        "seed": seed,
        "folds": n_folds,
    }
    temp = audit_root.with_name(audit_root.name + ".tmp." + uuid.uuid4().hex)
    audit_root.parent.mkdir(parents=True, exist_ok=True)
    temp.mkdir()
    _write_json(temp / "audit_report.json", report)
    _write_json(temp / "artifact_sha256.json", {"audit_report.json": _sha256(temp / "audit_report.json")})
    _write_json(
        temp / "COMPLETE.json",
        {
            "schema": "recursive_ridge_statistics_audit_complete_v1",
            "status": "complete",
            "artifact_manifest_sha256": _sha256(temp / "artifact_sha256.json"),
        },
    )
    os.replace(temp, audit_root)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-input-sha256", required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--classes", type=int, default=12)
    parser.add_argument("--n-folds", type=int, default=5)
    parser.add_argument("--mode", choices=("formal", "contract-test"), default="formal")
    args = parser.parse_args()
    audit_recursive_statistics(
        tree_root=args.tree,
        input_path=args.input,
        expected_input_sha256=args.expected_input_sha256,
        audit_root=args.audit_output,
        seed=args.seed,
        classes=args.classes,
        n_folds=args.n_folds,
        mode=args.mode,
    )
    print("RECURSIVE_RIDGE_STATISTICS_AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
