from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid
from typing import Any

import torch

from lwf_revision.balanced_global_ridge_oof import assign_balanced_folds
from lwf_revision.recursive_centered_ridge import RidgeSufficientStatistics
from lwf_revision.recursive_ridge_equivalence import (
    RecursiveEquivalenceDataset,
    StageBlock,
    evaluate_recursive_equivalence,
)


_FORMAL_SCHEMAS = {"b2_feature_input_v1"}
_BUSINESS_FILES = [
    "request.json",
    "input_sha256.json",
    "equivalence.json",
    "sufficient_statistics.pt",
    "memory_report.json",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sync_file(path: Path) -> None:
    # Windows requires a writable descriptor for fsync; no bytes are modified.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _write_json(path: Path, payload: Any) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _validated_matrix(value: Any, *, name: str) -> torch.Tensor:
    if not isinstance(value, torch.Tensor) or value.ndim != 2:
        raise ValueError(f"{name} must be a matrix tensor")
    result = value.detach().cpu().to(torch.float64)
    if result.shape[0] == 0 or result.shape[1] == 0 or not torch.isfinite(result).all():
        raise ValueError(f"{name} must be non-empty and finite")
    return result.contiguous()


def _validated_labels(
    value: Any, *, name: str, rows: int, classes: int
) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.ndim != 1
        or value.dtype == torch.bool
        or value.is_floating_point()
    ):
        raise ValueError(f"{name} must be an integer vector tensor")
    result = value.detach().cpu().to(torch.long)
    if result.shape != (rows,):
        raise ValueError(f"{name} row count mismatch")
    if torch.any(result < 0) or torch.any(result >= classes):
        raise ValueError(f"{name} class range mismatch")
    return result.contiguous()


def _validated_paths(value: Any, *, name: str, rows: int) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) != rows:
        raise ValueError(f"{name} identity count mismatch")
    result = list(value)
    if any(not isinstance(path, str) or not path for path in result):
        raise ValueError(f"{name} identities must be non-empty strings")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} identities must be unique")
    return result


def _load_input(
    path: Path, *, mode: str, seed: int, classes: int
) -> dict[str, Any]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict):
        raise ValueError("input artifact must be a mapping")
    allowed_schemas = _FORMAL_SCHEMAS | {"recursive_ridge_contract_test_input_v1"}
    if payload.get("schema") not in allowed_schemas:
        raise ValueError("input artifact schema is not approved")
    if mode == "formal" and payload.get("schema") not in _FORMAL_SCHEMAS:
        raise ValueError("formal input artifact schema is not approved")
    if type(payload.get("seed")) is not int or payload["seed"] != seed:
        raise ValueError("input seed mismatch")

    source_x = _validated_matrix(payload.get("source_features"), name="source_features")
    target_x = _validated_matrix(payload.get("target_features"), name="target_features")
    if source_x.shape[1] != target_x.shape[1]:
        raise ValueError("source and target feature dimensions differ")
    source_y = _validated_labels(
        payload.get("source_labels"),
        name="source_labels",
        rows=source_x.shape[0],
        classes=classes,
    )
    target_y = _validated_labels(
        payload.get("target_labels"),
        name="target_labels",
        rows=target_x.shape[0],
        classes=classes,
    )
    source_paths = _validated_paths(
        payload.get("source_paths"), name="source_paths", rows=source_x.shape[0]
    )
    target_paths = _validated_paths(
        payload.get("target_paths"), name="target_paths", rows=target_x.shape[0]
    )
    if set(source_y.tolist()) != set(range(classes - 1)):
        raise ValueError("source labels must cover all old classes only")
    if set(target_y.tolist()) != set(range(classes)):
        raise ValueError("target labels must cover every class")
    if torch.any(source_y == classes - 1):
        raise ValueError("source must not contain the newest class")

    mapping = payload.get("source_to_target")
    if not isinstance(mapping, (list, tuple)) or len(mapping) != source_x.shape[0]:
        raise ValueError("source_to_target mapping is invalid")
    target_by_path = {path: index for index, path in enumerate(target_paths)}
    expected_mapping = []
    for index, path_value in enumerate(source_paths):
        target_index = target_by_path.get(path_value)
        if target_index is None or int(source_y[index]) != int(target_y[target_index]):
            raise ValueError("source and target identities do not align")
        expected_mapping.append(target_index)
    if list(mapping) != expected_mapping:
        raise ValueError("source_to_target mapping does not match identities")
    return {
        "source_x": source_x,
        "source_y": source_y,
        "source_paths": source_paths,
        "target_x": target_x,
        "target_y": target_y,
        "target_paths": target_paths,
        "source_to_target": expected_mapping,
    }


def _aggregate_bytes(stats: RidgeSufficientStatistics) -> int:
    return sum(
        tensor.numel() * tensor.element_size()
        for tensor in (stats.sum_x, stats.sum_y, stats.sum_xx, stats.sum_xy)
    )


def _finalize_tree(root: Path) -> None:
    manifest = {name: _sha256(root / name) for name in _BUSINESS_FILES}
    _write_json(root / "artifact_sha256.json", manifest)
    _write_json(
        root / "COMPLETE.json",
        {
            "schema": "recursive_ridge_statistics_complete_v1",
            "status": "complete",
            "artifact_manifest_sha256": _sha256(root / "artifact_sha256.json"),
        },
    )


def build_recursive_ridge_statistics(
    *,
    input_path: Path,
    output_root: Path,
    seed: int,
    expected_sha256: str,
    classes: int = 12,
    n_folds: int = 5,
    mode: str = "formal",
) -> None:
    """Build a signed per-fold learner state and evaluator equivalence report."""

    input_path = Path(input_path)
    output_root = Path(output_root)
    if mode not in {"formal", "contract-test"}:
        raise ValueError("mode must be formal or contract-test")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(classes) is not int or classes < 4:
        raise ValueError("classes must be an integer no smaller than four")
    if type(n_folds) is not int or n_folds < 2:
        raise ValueError("n_folds must be an integer no smaller than two")
    if not input_path.is_file():
        raise FileNotFoundError("input artifact does not exist")
    if output_root.exists():
        raise FileExistsError("output root already exists")
    actual_input_sha = _sha256(input_path)
    if actual_input_sha.lower() != expected_sha256.lower():
        raise ValueError("input SHA256 mismatch")

    data = _load_input(input_path, mode=mode, seed=seed, classes=classes)
    fold_ids = assign_balanced_folds(
        data["target_y"],
        data["target_paths"],
        seed=seed,
        n_folds=n_folds,
        classes=classes,
    )
    source_fold_ids = [fold_ids[index] for index in data["source_to_target"]]
    learner_folds = []
    equivalence_folds = []
    fold_memory_bytes = []
    for fold in range(n_folds):
        source_fit_indices = torch.tensor(
            [index for index, assigned in enumerate(source_fold_ids) if assigned != fold],
            dtype=torch.long,
        )
        newest_fit_indices = torch.tensor(
            [
                index
                for index, (assigned, label) in enumerate(
                    zip(fold_ids, data["target_y"].tolist(), strict=True)
                )
                if assigned != fold and label == classes - 1
            ],
            dtype=torch.long,
        )
        holdout_indices = torch.tensor(
            [index for index, assigned in enumerate(fold_ids) if assigned == fold],
            dtype=torch.long,
        )
        fit_x = torch.cat(
            [data["source_x"][source_fit_indices], data["target_x"][newest_fit_indices]],
            dim=0,
        )
        fit_y = torch.cat(
            [data["source_y"][source_fit_indices], data["target_y"][newest_fit_indices]],
            dim=0,
        )
        old_base = fit_y < classes - 2
        penultimate = fit_y == classes - 2
        newest = fit_y == classes - 1
        stages = (
            StageBlock(fit_x[old_base], fit_y[old_base], classes=classes - 2),
            StageBlock(fit_x[penultimate], fit_y[penultimate], classes=classes - 1),
            StageBlock(fit_x[newest], fit_y[newest], classes=classes),
        )
        equivalence = evaluate_recursive_equivalence(
            RecursiveEquivalenceDataset(
                fit_x=fit_x,
                fit_y=fit_y,
                holdout_x=data["target_x"][holdout_indices],
                holdout_y=data["target_y"][holdout_indices],
                stage_blocks=stages,
            ),
            classes=classes,
            l2=1.0,
        )
        aggregate = RidgeSufficientStatistics.from_samples(
            stages[0].features, stages[0].labels, classes=classes - 2
        )
        aggregate = aggregate.expand_classes(classes - 1).merge(
            RidgeSufficientStatistics.from_samples(
                stages[1].features, stages[1].labels, classes=classes - 1
            )
        )
        aggregate = aggregate.expand_classes(classes).merge(
            RidgeSufficientStatistics.from_samples(
                stages[2].features, stages[2].labels, classes=classes
            )
        )
        aggregate_payload = aggregate.to_dict()
        aggregate_payload.update(
            {
                "fold": fold,
                "feature_dimension": aggregate.feature_dimension,
                "classes": aggregate.classes,
            }
        )
        learner_folds.append(aggregate_payload)
        equivalence_payload = equivalence.to_dict()
        equivalence_payload["fold"] = fold
        equivalence_folds.append(equivalence_payload)
        fold_memory_bytes.append(_aggregate_bytes(aggregate))

    all_equivalent = all(row["all_pass"] is True for row in equivalence_folds)
    if not all_equivalent:
        raise ValueError("recursive Ridge equivalence gate failed")

    temp_root = output_root.with_name(output_root.name + ".tmp." + uuid.uuid4().hex)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir()
    _write_json(
        temp_root / "request.json",
        {
            "schema": "recursive_ridge_statistics_request_v1",
            "mode": mode,
            "seed": seed,
            "classes": classes,
            "n_folds": n_folds,
            "l2": 1.0,
            "access": {
                "validation": False,
                "official_test": False,
                "final": False,
            },
        },
    )
    _write_json(
        temp_root / "input_sha256.json",
        {"input_path": str(input_path), "input_sha256": actual_input_sha},
    )
    _write_json(
        temp_root / "equivalence.json",
        {
            "schema": "recursive_ridge_equivalence_folds_v1",
            "seed": seed,
            "all_pass": all_equivalent,
            "folds": equivalence_folds,
        },
    )
    torch.save(
        {
            "schema": "recursive_ridge_sufficient_statistics_v1",
            "seed": seed,
            "folds": learner_folds,
        },
        temp_root / "sufficient_statistics.pt",
    )
    _sync_file(temp_root / "sufficient_statistics.pt")
    per_sample_feature_bytes = data["source_x"].numel() * data["source_x"].element_size()
    deployment_bytes = max(fold_memory_bytes)
    _write_json(
        temp_root / "memory_report.json",
        {
            "schema": "recursive_ridge_memory_report_v1",
            "aggregate_bytes": deployment_bytes,
            "published_all_folds_aggregate_bytes": sum(fold_memory_bytes),
            "per_sample_feature_bytes": per_sample_feature_bytes,
            "aggregate_to_feature_ratio": deployment_bytes / per_sample_feature_bytes,
            "fold_aggregate_bytes": fold_memory_bytes,
        },
    )
    _finalize_tree(temp_root)
    os.replace(temp_root, output_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--classes", type=int, default=12)
    parser.add_argument("--n-folds", type=int, default=5)
    parser.add_argument("--mode", choices=("formal", "contract-test"), default="formal")
    args = parser.parse_args()
    build_recursive_ridge_statistics(
        input_path=args.input,
        output_root=args.output,
        seed=args.seed,
        expected_sha256=args.expected_sha256,
        classes=args.classes,
        n_folds=args.n_folds,
        mode=args.mode,
    )
    print("RECURSIVE_RIDGE_STATISTICS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
