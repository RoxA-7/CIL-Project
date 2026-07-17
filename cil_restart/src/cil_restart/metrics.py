from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class MetricSummary:
    aia: float
    final_aa: float
    forgetting: float


def arithmetic_mean(values: Iterable[float]) -> float:
    xs = np.asarray(list(values), dtype=float)
    if xs.size == 0 or np.isnan(xs).any():
        raise ValueError("metric values must be non-empty and contain no NaN")
    return float(xs.mean())


def average_incremental_accuracy(stage_aa: Sequence[float]) -> float:
    """AIA is the arithmetic mean of AA at every evaluated task."""
    return arithmetic_mean(stage_aa)


def class_forgetting(per_class_history: Sequence[Sequence[float]]) -> float:
    """Average max-past minus final accuracy over classes seen before final task.

    NaN denotes a class not introduced yet. Classes introduced in the final task
    are excluded because they have no opportunity to be forgotten.
    """
    matrix = np.asarray(per_class_history, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2:
        raise ValueError("per_class_history must be a task-by-class matrix with >=2 tasks")
    final = matrix[-1]
    eligible = ~np.isnan(matrix[-2])
    if not eligible.any():
        return 0.0
    maxima = np.nanmax(matrix[:-1, eligible], axis=0)
    return float(np.mean(np.maximum(0.0, maxima - final[eligible])))


def summarize(stage_aa: Sequence[float], per_class_history: Sequence[Sequence[float]]) -> MetricSummary:
    if len(stage_aa) != len(per_class_history):
        raise ValueError("stage_aa and per_class_history must have the same task count")
    return MetricSummary(
        aia=average_incremental_accuracy(stage_aa),
        final_aa=float(stage_aa[-1]),
        forgetting=class_forgetting(per_class_history),
    )


def mean_std(values: Sequence[float], min_seeds: int = 3) -> tuple[float, float]:
    xs = np.asarray(values, dtype=float)
    if xs.size < min_seeds:
        raise ValueError(f"need at least {min_seeds} seeds, got {xs.size}")
    return float(xs.mean()), float(xs.std(ddof=1))

