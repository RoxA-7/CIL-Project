"""Pure metrics and preregistered fixed-order B2 class-12 gates."""
from __future__ import annotations
import math
from typing import Any, Mapping, Sequence
import torch

def harmonic_nonzero(values: Sequence[float]) -> float:
    numbers = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('harmonic inputs must be finite numbers')
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError('harmonic inputs must be finite non-negative numbers')
        numbers.append(number)
    if not numbers or any((value == 0.0 for value in numbers)):
        return 0.0
    return len(numbers) / sum((1.0 / value for value in numbers))

def _integer_vector(value: torch.Tensor, *, name: str, classes: int) -> torch.Tensor:
    if not isinstance(value, torch.Tensor) or value.ndim != 1 or value.dtype == torch.bool or value.is_floating_point():
        raise ValueError(f'{name} must be an integer vector')
    result = value.detach().cpu().to(torch.long)
    if torch.any(result < 0) or torch.any(result >= classes):
        raise ValueError(f'{name} is outside the configured class range')
    return result.contiguous()

def summarize_class12_predictions(labels: torch.Tensor, predictions: torch.Tensor, *, classes: int=13) -> dict[str, Any]:
    if type(classes) is not int or classes != 13:
        raise ValueError('class12 sequence requires exactly 13 classes')
    truth = _integer_vector(labels, name='labels', classes=classes)
    guessed = _integer_vector(predictions, name='predictions', classes=classes)
    if truth.shape != guessed.shape or truth.shape[0] == 0:
        raise ValueError('labels and predictions must have matching non-empty rows')
    confusion = torch.zeros((classes, classes), dtype=torch.int64)
    for actual, predicted in zip(truth.tolist(), guessed.tolist(), strict=True):
        confusion[actual, predicted] += 1
    totals = confusion.sum(dim=1)
    if torch.any(totals == 0):
        raise ValueError('labels must contain every class')
    per_class = [int(confusion[label, label]) / int(totals[label]) for label in range(classes)]
    old_macro = sum(per_class[:10]) / 10.0
    pair_h = harmonic_nonzero((per_class[10], per_class[11]))
    triple = (per_class[10], per_class[11], per_class[12])
    return {'per_class_accuracy': per_class, 'old_macro_accuracy': old_macro, 'class10_accuracy': per_class[10], 'class11_accuracy': per_class[11], 'class12_accuracy': per_class[12], 'pair_harmonic_accuracy': pair_h, 'triple_harmonic_accuracy': harmonic_nonzero(triple), 'triple_macro_accuracy': sum(triple) / 3.0, 'triple_worst_accuracy': min(triple), 'overall_accuracy': int(confusion.diagonal().sum()) / int(confusion.sum()), 'total_count': int(confusion.sum()), 'total_correct': int(confusion.diagonal().sum()), 'flow_10_to_11': int(confusion[10, 11]), 'flow_11_to_10': int(confusion[11, 10]), 'flow_10_11_to_12': int(confusion[10, 12] + confusion[11, 12]), 'flow_12_to_10': int(confusion[12, 10]), 'flow_12_to_11': int(confusion[12, 11]), 'old_to_recent': int(confusion[:10, 10:13].sum()), 'recent_to_old': int(confusion[10:13, :10].sum()), 'confusion_matrix': confusion.tolist()}

def _metric(summary: Mapping[str, Any], key: str) -> float:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{key} must be a finite metric')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{key} must be a finite metric')
    return result

def b2_learnability_checks(*, b0: Mapping[str, Any], b2: Mapping[str, Any], equivalence_passed: bool, audit_passed: bool) -> dict[str, bool]:
    b0_worst = _metric(b0, 'triple_worst_accuracy')
    b0_old = _metric(b0, 'old_macro_accuracy')
    b2_c10 = _metric(b2, 'class10_accuracy')
    b2_c11 = _metric(b2, 'class11_accuracy')
    b2_c12 = _metric(b2, 'class12_accuracy')
    b2_worst = _metric(b2, 'triple_worst_accuracy')
    b2_old = _metric(b2, 'old_macro_accuracy')
    return {'class12_minimum': b2_c12 >= 0.5, 'recent_classes_nonzero': min(b2_c10, b2_c11, b2_c12) > 0.0, 'triple_worst_vs_b0': b2_worst >= b0_worst, 'old_macro_budget': b2_old >= b0_old - 0.005, 'batch_recursive_equivalence': equivalence_passed is True, 'independent_audit': audit_passed is True}
