"""C0-C3 equivalence checks for aggregate centered Ridge updates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Sequence

import torch

from lwf_revision.frozen_head_reconstruction import fit_centered_ridge, ridge_scores
from lwf_revision.recursive_centered_ridge import RidgeSufficientStatistics


WEIGHT_BIAS_ATOL = 1e-10
LOGIT_ATOL = 1e-9


@dataclass(frozen=True)
class StageBlock:
    features: torch.Tensor
    labels: torch.Tensor
    classes: int


@dataclass(frozen=True)
class RecursiveEquivalenceDataset:
    fit_x: torch.Tensor
    fit_y: torch.Tensor
    holdout_x: torch.Tensor
    holdout_y: torch.Tensor
    stage_blocks: Sequence[StageBlock]


@dataclass(frozen=True)
class RecursiveEquivalenceResult:
    all_pass: bool
    predictions_exact: bool
    confusions_exact: bool
    metrics_exact: bool
    weight_max_abs: float
    bias_max_abs: float
    logit_max_abs: float
    head_sha256: dict[str, str]
    predictions: dict[str, list[int]]
    confusion_matrices: dict[str, list[list[int]]]
    metrics: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "recursive_ridge_equivalence_v1",
            "all_pass": self.all_pass,
            "predictions_exact": self.predictions_exact,
            "confusions_exact": self.confusions_exact,
            "metrics_exact": self.metrics_exact,
            "weight_max_abs": self.weight_max_abs,
            "bias_max_abs": self.bias_max_abs,
            "logit_max_abs": self.logit_max_abs,
            "head_sha256": self.head_sha256,
            "predictions": self.predictions,
            "confusion_matrices": self.confusion_matrices,
            "metrics": self.metrics,
            "tolerances": {
                "weight_bias_atol": WEIGHT_BIAS_ATOL,
                "logit_atol": LOGIT_ATOL,
            },
        }


def _validate_matrix(value: torch.Tensor, *, name: str) -> torch.Tensor:
    if not isinstance(value, torch.Tensor) or value.ndim != 2:
        raise ValueError(f"{name} must be a matrix tensor")
    if value.shape[0] == 0 or value.shape[1] == 0:
        raise ValueError(f"{name} must not be empty")
    result = value.detach().cpu().to(torch.float64)
    if not torch.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite values")
    return result.contiguous()


def _validate_labels(
    value: torch.Tensor,
    *,
    name: str,
    rows: int,
    classes: int,
) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.ndim != 1
        or value.dtype == torch.bool
        or value.is_floating_point()
    ):
        raise ValueError(f"{name} must be an integer vector tensor")
    result = value.detach().cpu().to(torch.long)
    if result.shape[0] != rows:
        raise ValueError(f"{name} row count mismatch")
    if torch.any(result < 0) or torch.any(result >= classes):
        raise ValueError(f"{name} is outside the configured class range")
    return result.contiguous()


def _row_identity_multiset(features: torch.Tensor, labels: torch.Tensor) -> list[str]:
    identities = []
    for index in range(features.shape[0]):
        digest = hashlib.sha256()
        digest.update(int(labels[index]).to_bytes(8, "little", signed=True))
        digest.update(features[index].contiguous().numpy().tobytes())
        identities.append(digest.hexdigest())
    return sorted(identities)


def _confusion(
    labels: torch.Tensor, predictions: torch.Tensor, *, classes: int
) -> list[list[int]]:
    matrix = torch.zeros((classes, classes), dtype=torch.int64)
    for actual, predicted in zip(labels.tolist(), predictions.tolist(), strict=True):
        matrix[actual, predicted] += 1
    return matrix.tolist()


def _metrics(
    labels: torch.Tensor, predictions: torch.Tensor, *, classes: int
) -> dict[str, Any]:
    matrix = torch.tensor(_confusion(labels, predictions, classes=classes))
    totals = matrix.sum(dim=1)
    if torch.any(totals == 0):
        raise ValueError("holdout must contain every class")
    per_class = [
        int(matrix[label, label]) / int(totals[label]) for label in range(classes)
    ]
    return {
        "overall_accuracy": int(matrix.diagonal().sum()) / int(matrix.sum()),
        "per_class_accuracy": per_class,
        "total_count": int(matrix.sum()),
        "total_correct": int(matrix.diagonal().sum()),
    }


def _head_sha256(weight: torch.Tensor, bias: torch.Tensor) -> str:
    digest = hashlib.sha256()
    digest.update(str(tuple(weight.shape)).encode("ascii"))
    digest.update(weight.contiguous().numpy().tobytes())
    digest.update(str(tuple(bias.shape)).encode("ascii"))
    digest.update(bias.contiguous().numpy().tobytes())
    return digest.hexdigest()


def _fit_c3(
    blocks: Sequence[tuple[torch.Tensor, torch.Tensor, int]], *, final_classes: int, l2: float
) -> tuple[torch.Tensor, torch.Tensor]:
    aggregate: RidgeSufficientStatistics | None = None
    previous_classes = 0
    for features, labels, stage_classes in blocks:
        if stage_classes <= previous_classes:
            raise ValueError("stage classes must expand monotonically")
        if stage_classes > final_classes:
            raise ValueError("stage classes exceed final classes")
        current = RidgeSufficientStatistics.from_samples(
            features, labels, classes=stage_classes
        )
        if aggregate is None:
            aggregate = current
        else:
            aggregate = aggregate.expand_classes(stage_classes).merge(current)
        previous_classes = stage_classes
    if aggregate is None:
        raise ValueError("stage blocks must not be empty")
    return aggregate.expand_classes(final_classes).solve(l2=l2)


def evaluate_recursive_equivalence(
    dataset: RecursiveEquivalenceDataset,
    *,
    classes: int,
    l2: float,
) -> RecursiveEquivalenceResult:
    """Compare batch, one-block, per-class, and real-stage aggregate fits."""

    if isinstance(classes, bool) or not isinstance(classes, int) or classes < 2:
        raise ValueError("classes must be an integer no smaller than two")
    if not isinstance(dataset, RecursiveEquivalenceDataset):
        raise ValueError("dataset must use RecursiveEquivalenceDataset")
    fit_x = _validate_matrix(dataset.fit_x, name="fit_x")
    fit_y = _validate_labels(
        dataset.fit_y, name="fit_y", rows=fit_x.shape[0], classes=classes
    )
    holdout_x = _validate_matrix(dataset.holdout_x, name="holdout_x")
    holdout_y = _validate_labels(
        dataset.holdout_y,
        name="holdout_y",
        rows=holdout_x.shape[0],
        classes=classes,
    )
    if fit_x.shape[1] != holdout_x.shape[1]:
        raise ValueError("fit and holdout feature dimensions differ")
    if set(fit_y.tolist()) != set(range(classes)):
        raise ValueError("fit data must contain every class")
    if set(holdout_y.tolist()) != set(range(classes)):
        raise ValueError("holdout data must contain every class")

    validated_blocks: list[tuple[torch.Tensor, torch.Tensor, int]] = []
    previous_classes = 0
    for block in dataset.stage_blocks:
        if not isinstance(block, StageBlock):
            raise ValueError("stage blocks must use StageBlock")
        if (
            isinstance(block.classes, bool)
            or not isinstance(block.classes, int)
            or block.classes < 2
        ):
            raise ValueError("stage classes are invalid")
        if block.classes <= previous_classes:
            raise ValueError("stage classes must expand monotonically")
        block_x = _validate_matrix(block.features, name="stage features")
        block_y = _validate_labels(
            block.labels,
            name="stage labels",
            rows=block_x.shape[0],
            classes=block.classes,
        )
        if block_x.shape[1] != fit_x.shape[1]:
            raise ValueError("stage feature dimension mismatch")
        validated_blocks.append((block_x, block_y, block.classes))
        previous_classes = block.classes
    if not validated_blocks or validated_blocks[-1][2] != classes:
        raise ValueError("stage classes must end at final classes")
    stage_x = torch.cat([row[0] for row in validated_blocks], dim=0)
    stage_y = torch.cat([row[1] for row in validated_blocks], dim=0)
    if _row_identity_multiset(stage_x, stage_y) != _row_identity_multiset(fit_x, fit_y):
        raise ValueError("stage coverage does not exactly match fit data")

    heads: dict[str, tuple[torch.Tensor, torch.Tensor]] = {}
    heads["c0"] = fit_centered_ridge(fit_x, fit_y, classes=classes, l2=l2)
    heads["c1"] = RidgeSufficientStatistics.from_samples(
        fit_x, fit_y, classes=classes
    ).solve(l2=l2)

    class_blocks = [
        RidgeSufficientStatistics.from_samples(
            fit_x[fit_y == label], fit_y[fit_y == label], classes=classes
        )
        for label in range(classes)
    ]
    class_aggregate = class_blocks[0]
    for block in class_blocks[1:]:
        class_aggregate = class_aggregate.merge(block)
    heads["c2"] = class_aggregate.solve(l2=l2)
    heads["c3"] = _fit_c3(validated_blocks, final_classes=classes, l2=l2)

    scores = {
        name: ridge_scores(holdout_x, weight, bias)
        for name, (weight, bias) in heads.items()
    }
    prediction_tensors = {name: value.argmax(dim=1) for name, value in scores.items()}
    predictions = {name: value.tolist() for name, value in prediction_tensors.items()}
    confusions = {
        name: _confusion(holdout_y, value, classes=classes)
        for name, value in prediction_tensors.items()
    }
    metrics = {
        name: _metrics(holdout_y, value, classes=classes)
        for name, value in prediction_tensors.items()
    }
    reference_weight, reference_bias = heads["c0"]
    weight_max_abs = max(
        float(torch.max(torch.abs(weight - reference_weight)))
        for name, (weight, _) in heads.items()
        if name != "c0"
    )
    bias_max_abs = max(
        float(torch.max(torch.abs(bias - reference_bias)))
        for name, (_, bias) in heads.items()
        if name != "c0"
    )
    reference_scores = scores["c0"]
    logit_max_abs = max(
        float(torch.max(torch.abs(value - reference_scores)))
        for name, value in scores.items()
        if name != "c0"
    )
    predictions_exact = all(value == predictions["c0"] for value in predictions.values())
    confusions_exact = all(value == confusions["c0"] for value in confusions.values())
    metrics_exact = all(value == metrics["c0"] for value in metrics.values())
    all_pass = (
        predictions_exact
        and confusions_exact
        and metrics_exact
        and weight_max_abs <= WEIGHT_BIAS_ATOL
        and bias_max_abs <= WEIGHT_BIAS_ATOL
        and logit_max_abs <= LOGIT_ATOL
    )
    return RecursiveEquivalenceResult(
        all_pass=all_pass,
        predictions_exact=predictions_exact,
        confusions_exact=confusions_exact,
        metrics_exact=metrics_exact,
        weight_max_abs=weight_max_abs,
        bias_max_abs=bias_max_abs,
        logit_max_abs=logit_max_abs,
        head_sha256={name: _head_sha256(*head) for name, head in heads.items()},
        predictions=predictions,
        confusion_matrices=confusions,
        metrics=metrics,
    )
