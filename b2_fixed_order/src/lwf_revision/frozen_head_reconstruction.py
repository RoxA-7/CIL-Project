"""冻结骨干分类头重建的纯张量计算与预注册判定。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

import torch
from torch.nn import functional as F


EXPECTED_SEEDS = frozenset({"2026", "2027", "2028"})
SUMMARY_KEYS = frozenset(
    {
        "class10_correct",
        "class10_total",
        "class11_correct",
        "class11_total",
        "old_classes_correct",
        "old_classes_total",
        "total_correct",
        "total_count",
        "macro_accuracy",
        "worst_class_accuracy",
        "class10_to_class11",
        "class11_to_class10",
    }
)
CANDIDATES = (
    "oracle_target_ridge",
    "stored_source_ridge",
    "stored_source_ncm",
)


def _validated_features_and_labels(
    features: torch.Tensor,
    labels: torch.Tensor,
    *,
    classes: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    if not isinstance(features, torch.Tensor) or features.ndim != 2:
        raise ValueError("features必须为二维张量")
    if not isinstance(labels, torch.Tensor) or labels.ndim != 1:
        raise ValueError("labels必须为一维张量")
    if features.shape[0] != labels.shape[0]:
        raise ValueError("features与labels数量不一致")
    if features.shape[0] == 0 or features.shape[1] == 0:
        raise ValueError("features不能为空")
    if isinstance(classes, bool) or not isinstance(classes, int) or classes < 2:
        raise ValueError("classes必须为不小于2的整数")
    if not torch.isfinite(features).all():
        raise ValueError("features必须全部有限")
    if labels.dtype == torch.bool or labels.is_floating_point():
        raise ValueError("labels必须为整数张量")
    labels_cpu = labels.detach().cpu().to(torch.long)
    if torch.any(labels_cpu < 0) or torch.any(labels_cpu >= classes):
        raise ValueError("labels超出类别范围")
    counts = torch.bincount(labels_cpu, minlength=classes)
    if counts.shape[0] != classes or torch.any(counts == 0):
        raise ValueError("每个类别必须至少有一个样本")
    return features.detach().cpu().to(torch.float64), labels_cpu


def fit_centered_ridge(
    features: torch.Tensor,
    labels: torch.Tensor,
    *,
    classes: int = 12,
    l2: float = 1.0,
) -> tuple[torch.Tensor, torch.Tensor]:
    """以固定中心化闭式解拟合多类岭回归头。"""

    if isinstance(l2, bool) or not isinstance(l2, (int, float)):
        raise ValueError("l2必须为有限正数")
    l2_value = float(l2)
    if not math.isfinite(l2_value) or l2_value <= 0:
        raise ValueError("l2必须为有限正数")
    x, y = _validated_features_and_labels(features, labels, classes=classes)
    targets = F.one_hot(y, num_classes=classes).to(torch.float64)
    x_mean = x.mean(dim=0)
    y_mean = targets.mean(dim=0)
    centered_x = x - x_mean
    centered_y = targets - y_mean
    gram = centered_x.T @ centered_x
    gram.diagonal().add_(l2_value)
    rhs = centered_x.T @ centered_y
    weight = torch.linalg.solve(gram, rhs)
    bias = y_mean - x_mean @ weight
    if not torch.isfinite(weight).all() or not torch.isfinite(bias).all():
        raise ValueError("岭回归解必须全部有限")
    return weight.contiguous(), bias.contiguous()


def ridge_scores(
    features: torch.Tensor,
    weight: torch.Tensor,
    bias: torch.Tensor,
) -> torch.Tensor:
    if not all(isinstance(value, torch.Tensor) for value in (features, weight, bias)):
        raise ValueError("features、weight和bias必须为张量")
    if features.ndim != 2 or weight.ndim != 2 or bias.ndim != 1:
        raise ValueError("ridge张量形状错误")
    if features.shape[1] != weight.shape[0] or weight.shape[1] != bias.shape[0]:
        raise ValueError("ridge张量维度不匹配")
    values = features.detach().cpu().to(torch.float64)
    weights = weight.detach().cpu().to(torch.float64)
    biases = bias.detach().cpu().to(torch.float64)
    if not all(torch.isfinite(value).all() for value in (values, weights, biases)):
        raise ValueError("ridge输入必须全部有限")
    return values @ weights + biases


def ncm_centroids(
    features: torch.Tensor,
    labels: torch.Tensor,
    *,
    classes: int = 12,
) -> torch.Tensor:
    x, y = _validated_features_and_labels(features, labels, classes=classes)
    centroids = torch.stack([x[y == label].mean(dim=0) for label in range(classes)])
    if not torch.isfinite(centroids).all():
        raise ValueError("NCM质心必须全部有限")
    return centroids.contiguous()


def ncm_scores(features: torch.Tensor, centroids: torch.Tensor) -> torch.Tensor:
    if not isinstance(features, torch.Tensor) or features.ndim != 2:
        raise ValueError("features必须为二维张量")
    if not isinstance(centroids, torch.Tensor) or centroids.ndim != 2:
        raise ValueError("centroids必须为二维张量")
    if features.shape[1] != centroids.shape[1]:
        raise ValueError("features与centroids维度不匹配")
    x = features.detach().cpu().to(torch.float64)
    centers = centroids.detach().cpu().to(torch.float64)
    if not torch.isfinite(x).all() or not torch.isfinite(centers).all():
        raise ValueError("NCM输入必须全部有限")
    return -torch.sum((x[:, None, :] - centers[None, :, :]) ** 2, dim=2)


def _integer_vector(values: torch.Tensor | Sequence[int], *, label: str) -> list[int]:
    if isinstance(values, torch.Tensor):
        if values.ndim != 1 or values.dtype == torch.bool or values.is_floating_point():
            raise ValueError(f"{label}必须为一维整数张量")
        result = [int(value) for value in values.detach().cpu().tolist()]
    elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        result = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{label}必须为整数序列")
            result.append(value)
    else:
        raise ValueError(f"{label}必须为一维整数序列")
    return result


def summarize_predictions(
    labels: torch.Tensor | Sequence[int],
    predictions: torch.Tensor | Sequence[int],
    *,
    classes: int = 12,
    recent_class: int = 10,
    newest_class: int = 11,
) -> dict[str, object]:
    truth = _integer_vector(labels, label="labels")
    predicted = _integer_vector(predictions, label="predictions")
    if len(truth) == 0 or len(truth) != len(predicted):
        raise ValueError("labels与predictions数量必须相同且非空")
    if not 0 <= recent_class < newest_class < classes:
        raise ValueError("recent_class和newest_class范围错误")
    if any(value < 0 or value >= classes for value in truth + predicted):
        raise ValueError("labels或predictions超出类别范围")
    totals = [sum(value == label for value in truth) for label in range(classes)]
    if any(total == 0 for total in totals):
        raise ValueError("每个类别必须至少有一个评价样本")
    correct = [
        sum(actual == label and guess == label for actual, guess in zip(truth, predicted, strict=True))
        for label in range(classes)
    ]
    recalls = [correct[label] / totals[label] for label in range(classes)]
    total_correct = sum(actual == guess for actual, guess in zip(truth, predicted, strict=True))
    return {
        "class10_correct": correct[recent_class],
        "class10_total": totals[recent_class],
        "class11_correct": correct[newest_class],
        "class11_total": totals[newest_class],
        "old_classes_correct": sum(correct[:recent_class]),
        "old_classes_total": sum(totals[:recent_class]),
        "total_correct": total_correct,
        "total_count": len(truth),
        "macro_accuracy": sum(recalls) / classes,
        "worst_class_accuracy": min(recalls),
        "per_class_recall": {str(label): recalls[label] for label in range(classes)},
        "class10_to_class11": sum(
            actual == recent_class and guess == newest_class
            for actual, guess in zip(truth, predicted, strict=True)
        ),
        "class11_to_class10": sum(
            actual == newest_class and guess == recent_class
            for actual, guess in zip(truth, predicted, strict=True)
        ),
    }


def _normalized_summary(value: object) -> dict[str, int | float] | None:
    if not isinstance(value, Mapping) or not SUMMARY_KEYS.issubset(value):
        return None
    integers: dict[str, int] = {}
    for key in SUMMARY_KEYS - {"macro_accuracy", "worst_class_accuracy"}:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            return None
        integers[key] = item
    metrics: dict[str, float] = {}
    for key in ("macro_accuracy", "worst_class_accuracy"):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        metric = float(item)
        if not math.isfinite(metric) or not 0.0 <= metric <= 1.0:
            return None
        metrics[key] = metric
    if integers["class10_total"] != 20 or integers["class11_total"] != 20:
        return None
    if integers["old_classes_total"] != 200 or integers["total_count"] != 240:
        return None
    if integers["total_correct"] != (
        integers["class10_correct"]
        + integers["class11_correct"]
        + integers["old_classes_correct"]
    ):
        return None
    for correct_key, total_key in (
        ("class10_correct", "class10_total"),
        ("class11_correct", "class11_total"),
        ("old_classes_correct", "old_classes_total"),
        ("total_correct", "total_count"),
    ):
        if integers[correct_key] > integers[total_key]:
            return None
    if integers["class10_to_class11"] > 20 or integers["class11_to_class10"] > 20:
        return None
    return {**integers, **metrics}


def _normalized_rows(
    per_seed: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, dict[str, int | float]]] | None:
    if set(per_seed) != EXPECTED_SEEDS:
        return None
    normalized: dict[str, dict[str, dict[str, int | float]]] = {}
    for seed in sorted(EXPECTED_SEEDS):
        row = per_seed.get(seed)
        if not isinstance(row, Mapping) or row.get("invalid") is not False:
            return None
        current: dict[str, dict[str, int | float]] = {}
        for name in ("raw_target_head", *CANDIDATES):
            summary = _normalized_summary(row.get(name))
            if summary is None:
                return None
            current[name] = summary
        normalized[seed] = current
    return normalized


def _per_seed_pass(raw: Mapping[str, int | float], candidate: Mapping[str, int | float]) -> bool:
    return (
        int(candidate["class10_correct"]) >= 10
        and int(candidate["class10_correct"]) - int(raw["class10_correct"]) >= 5
        and int(raw["class10_to_class11"]) - int(candidate["class10_to_class11"]) >= 8
        and int(raw["class11_correct"]) - int(candidate["class11_correct"]) <= 2
        and int(raw["old_classes_correct"]) - int(candidate["old_classes_correct"]) <= 4
        and int(candidate["total_correct"]) > int(raw["total_correct"])
        and float(candidate["macro_accuracy"]) >= float(raw["macro_accuracy"])
        and float(candidate["worst_class_accuracy"]) > float(raw["worst_class_accuracy"])
    )


def _candidate_passes(
    rows: Mapping[str, Mapping[str, Mapping[str, int | float]]],
    name: str,
) -> bool:
    if not all(_per_seed_pass(row["raw_target_head"], row[name]) for row in rows.values()):
        return False
    class10_gain = sum(
        int(row[name]["class10_correct"]) - int(row["raw_target_head"]["class10_correct"])
        for row in rows.values()
    )
    class11_loss = sum(
        int(row["raw_target_head"]["class11_correct"]) - int(row[name]["class11_correct"])
        for row in rows.values()
    )
    old_loss = sum(
        int(row["raw_target_head"]["old_classes_correct"])
        - int(row[name]["old_classes_correct"])
        for row in rows.values()
    )
    return class10_gain >= 30 and class11_loss <= 4 and old_loss <= 8


def classify_head_reconstruction(
    per_seed: Mapping[str, Mapping[str, object]],
) -> str:
    """按预注册优先级给出三seed唯一总体状态。"""

    if not isinstance(per_seed, Mapping):
        return "invalid"
    rows = _normalized_rows(per_seed)
    if rows is None:
        return "invalid"
    if _candidate_passes(rows, "stored_source_ridge"):
        return "stored_feature_replay_supported"
    if _candidate_passes(rows, "oracle_target_ridge"):
        return "oracle_only"
    oracle_seed_passes = sum(
        _per_seed_pass(row["raw_target_head"], row["oracle_target_ridge"])
        for row in rows.values()
    )
    if oracle_seed_passes == 0:
        return "head_refit_not_supported"
    return "mixed_evidence"
