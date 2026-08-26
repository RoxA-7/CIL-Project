"""Centered multi-class Ridge using aggregate sufficient statistics only."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import torch
import torch.nn.functional as F


_FIELDS = {"n", "sum_x", "sum_y", "sum_xx", "sum_xy"}


def _validated_classes(classes: int) -> int:
    if isinstance(classes, bool) or not isinstance(classes, int) or classes < 2:
        raise ValueError("classes must be an integer no smaller than two")
    return classes


def _validated_samples(
    features: torch.Tensor,
    labels: torch.Tensor,
    *,
    classes: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    class_count = _validated_classes(classes)
    if not isinstance(features, torch.Tensor) or features.ndim != 2:
        raise ValueError("features must be a matrix tensor")
    if not isinstance(labels, torch.Tensor) or labels.ndim != 1:
        raise ValueError("labels must be a vector tensor")
    if features.shape[0] != labels.shape[0]:
        raise ValueError("features and labels must have matching rows")
    if features.shape[0] == 0 or features.shape[1] == 0:
        raise ValueError("features must not be empty")
    if labels.dtype == torch.bool or labels.is_floating_point():
        raise ValueError("labels must use an integer dtype")
    values = features.detach().cpu().to(torch.float64)
    integer_labels = labels.detach().cpu().to(torch.long)
    if not torch.isfinite(values).all():
        raise ValueError("features must contain only finite values")
    if torch.any(integer_labels < 0) or torch.any(integer_labels >= class_count):
        raise ValueError("labels are outside the configured class range")
    return values, integer_labels


def _validated_l2(l2: float) -> float:
    if isinstance(l2, bool) or not isinstance(l2, (int, float)):
        raise ValueError("l2 must be a finite positive number")
    value = float(l2)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("l2 must be a finite positive number")
    return value


@dataclass(frozen=True)
class RidgeSufficientStatistics:
    """Immutable aggregate state for a centered multi-class Ridge head."""

    n: int
    sum_x: torch.Tensor
    sum_y: torch.Tensor
    sum_xx: torch.Tensor
    sum_xy: torch.Tensor

    def __post_init__(self) -> None:
        if isinstance(self.n, bool) or not isinstance(self.n, int) or self.n <= 0:
            raise ValueError("n must be a positive integer")
        values = {
            "sum_x": self.sum_x,
            "sum_y": self.sum_y,
            "sum_xx": self.sum_xx,
            "sum_xy": self.sum_xy,
        }
        for name, tensor in values.items():
            if not isinstance(tensor, torch.Tensor):
                raise ValueError(f"{name} must be a tensor")
            if tensor.dtype != torch.float64:
                raise ValueError(f"{name} must use float64")
            if tensor.device.type != "cpu":
                raise ValueError(f"{name} must be stored on CPU")
            if not torch.isfinite(tensor).all():
                raise ValueError(f"{name} must contain only finite values")

        if self.sum_x.ndim != 1 or self.sum_y.ndim != 1:
            raise ValueError("sum_x and sum_y must be vectors")
        feature_dimension = self.sum_x.shape[0]
        classes = self.sum_y.shape[0]
        if feature_dimension == 0 or classes < 2:
            raise ValueError("statistics dimensions are invalid")
        if self.sum_xx.shape != (feature_dimension, feature_dimension):
            raise ValueError("sum_xx feature dimension mismatch")
        if self.sum_xy.shape != (feature_dimension, classes):
            raise ValueError("sum_xy feature or classes dimension mismatch")
        if torch.any(self.sum_y < 0):
            raise ValueError("sum_y must be non-negative")
        if not torch.isclose(
            self.sum_y.sum(),
            torch.tensor(float(self.n), dtype=torch.float64),
            atol=1e-9,
            rtol=0,
        ):
            raise ValueError("sum_y must sum to n")
        if not torch.allclose(self.sum_xx, self.sum_xx.T, atol=1e-10, rtol=0):
            raise ValueError("sum_xx must be symmetric")

        for name, tensor in values.items():
            object.__setattr__(self, name, tensor.detach().clone().contiguous())

    @property
    def feature_dimension(self) -> int:
        return int(self.sum_x.shape[0])

    @property
    def classes(self) -> int:
        return int(self.sum_y.shape[0])

    @classmethod
    def from_samples(
        cls,
        features: torch.Tensor,
        labels: torch.Tensor,
        *,
        classes: int,
    ) -> "RidgeSufficientStatistics":
        values, integer_labels = _validated_samples(features, labels, classes=classes)
        targets = F.one_hot(integer_labels, num_classes=classes).to(torch.float64)
        return cls(
            n=int(values.shape[0]),
            sum_x=values.sum(dim=0),
            sum_y=targets.sum(dim=0),
            sum_xx=values.T @ values,
            sum_xy=values.T @ targets,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RidgeSufficientStatistics":
        if not isinstance(payload, Mapping) or set(payload) != _FIELDS:
            raise ValueError("statistics fields must match the aggregate schema exactly")
        return cls(
            n=payload["n"],
            sum_x=payload["sum_x"],
            sum_y=payload["sum_y"],
            sum_xx=payload["sum_xx"],
            sum_xy=payload["sum_xy"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "sum_x": self.sum_x.clone(),
            "sum_y": self.sum_y.clone(),
            "sum_xx": self.sum_xx.clone(),
            "sum_xy": self.sum_xy.clone(),
        }

    def expand_classes(self, classes: int) -> "RidgeSufficientStatistics":
        target_classes = _validated_classes(classes)
        if target_classes < self.classes:
            raise ValueError("classes cannot shrink aggregate statistics")
        if target_classes == self.classes:
            return RidgeSufficientStatistics.from_dict(self.to_dict())
        sum_y = torch.zeros(target_classes, dtype=torch.float64)
        sum_y[: self.classes] = self.sum_y
        sum_xy = torch.zeros(
            (self.feature_dimension, target_classes), dtype=torch.float64
        )
        sum_xy[:, : self.classes] = self.sum_xy
        return RidgeSufficientStatistics(
            n=self.n,
            sum_x=self.sum_x,
            sum_y=sum_y,
            sum_xx=self.sum_xx,
            sum_xy=sum_xy,
        )

    def merge(
        self, other: "RidgeSufficientStatistics"
    ) -> "RidgeSufficientStatistics":
        if not isinstance(other, RidgeSufficientStatistics):
            raise ValueError("other statistics must use the same aggregate type")
        if self.feature_dimension != other.feature_dimension:
            raise ValueError("feature dimension mismatch")
        if self.classes != other.classes:
            raise ValueError("classes dimension mismatch")
        return RidgeSufficientStatistics(
            n=self.n + other.n,
            sum_x=self.sum_x + other.sum_x,
            sum_y=self.sum_y + other.sum_y,
            sum_xx=self.sum_xx + other.sum_xx,
            sum_xy=self.sum_xy + other.sum_xy,
        )

    def solve(self, *, l2: float) -> tuple[torch.Tensor, torch.Tensor]:
        l2_value = _validated_l2(l2)
        if torch.any(self.sum_y == 0):
            raise ValueError("every class must have at least one sample before solve")
        x_mean = self.sum_x / self.n
        y_mean = self.sum_y / self.n
        gram = self.sum_xx - torch.outer(self.sum_x, self.sum_x) / self.n
        rhs = self.sum_xy - torch.outer(self.sum_x, self.sum_y) / self.n
        regularized = gram.clone()
        regularized.diagonal().add_(l2_value)
        weight = torch.linalg.solve(regularized, rhs)
        bias = y_mean - x_mean @ weight
        if not torch.isfinite(weight).all() or not torch.isfinite(bias).all():
            raise ValueError("Ridge solution must contain only finite values")
        return weight.contiguous(), bias.contiguous()
