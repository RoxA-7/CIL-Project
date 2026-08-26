"""Pure B2 class-12 confirmation metrics, gates, and multiseed summaries."""

from __future__ import annotations

import math
from statistics import mean, stdev
from typing import Any, Mapping, Sequence

import torch

from .recursive_ridge_class12_sequence import summarize_class12_predictions


REGISTERED_METRICS = (
    "class10_accuracy",
    "class11_accuracy",
    "class12_accuracy",
    "old_macro_accuracy",
    "pair_harmonic_accuracy",
    "triple_harmonic_accuracy",
    "triple_worst_accuracy",
    "overall_accuracy",
)


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _integer_vector(values: Sequence[int], *, name: str) -> torch.Tensor:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be an integer sequence")
    normalized = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer sequence")
        normalized.append(value)
    return torch.tensor(normalized, dtype=torch.long)


def summarize_predictions(
    labels: Sequence[int], predictions: Sequence[int]
) -> dict[str, Any]:
    """Summarize a complete 13-class prediction vector."""

    return summarize_class12_predictions(
        _integer_vector(labels, name="labels"),
        _integer_vector(predictions, name="predictions"),
    )


def _summary_metric(summary: Mapping[str, Any], name: str) -> float:
    return _finite(summary.get(name), name=name)


def _fold_deltas(values: Sequence[float]) -> list[float]:
    if isinstance(values, (str, bytes)) or len(values) != 5:
        raise ValueError("exactly five outer-fold triple-H deltas are required")
    return [_finite(value, name="triple_h_fold_delta") for value in values]


def b2_confirmation_checks(
    *,
    b0: Mapping[str, Any],
    b2: Mapping[str, Any],
    triple_h_fold_deltas: Sequence[float],
    truth_passed: bool,
    equivalence_passed: bool,
    audit_passed: bool,
) -> dict[str, Any]:
    """Evaluate the preregistered original and balance gates for one seed."""

    if not all(type(value) is bool for value in (truth_passed, equivalence_passed, audit_passed)):
        raise ValueError("truth, equivalence, and audit flags must be booleans")
    deltas = _fold_deltas(triple_h_fold_deltas)
    b0_old = _summary_metric(b0, "old_macro_accuracy")
    b0_worst = _summary_metric(b0, "triple_worst_accuracy")
    b0_pair = _summary_metric(b0, "pair_harmonic_accuracy")
    b0_triple = _summary_metric(b0, "triple_harmonic_accuracy")
    b0_overall = _summary_metric(b0, "overall_accuracy")
    b2_old = _summary_metric(b2, "old_macro_accuracy")
    b2_c10 = _summary_metric(b2, "class10_accuracy")
    b2_c11 = _summary_metric(b2, "class11_accuracy")
    b2_c12 = _summary_metric(b2, "class12_accuracy")
    b2_worst = _summary_metric(b2, "triple_worst_accuracy")
    b2_pair = _summary_metric(b2, "pair_harmonic_accuracy")
    b2_triple = _summary_metric(b2, "triple_harmonic_accuracy")
    b2_overall = _summary_metric(b2, "overall_accuracy")
    original = {
        "class12_minimum": b2_c12 >= 0.50,
        "recent_classes_nonzero": min(b2_c10, b2_c11, b2_c12) > 0.0,
        "triple_worst_vs_b0": b2_worst >= b0_worst,
        "old_macro_budget": b2_old >= b0_old - 0.005,
        "batch_recursive_equivalence": equivalence_passed,
        "independent_audit": audit_passed,
    }
    balance = {
        "recent_triad_minimum": min(b2_c10, b2_c11, b2_c12) >= 0.50,
        "pair_harmonic_strict_gain": b2_pair > b0_pair,
        "triple_harmonic_strict_gain": b2_triple > b0_triple,
        "overall_no_drop": b2_overall >= b0_overall,
        "positive_fold_direction": sum(value > 0.0 for value in deltas) >= 4,
    }
    return {
        "truth_passed": truth_passed,
        "original_checks": original,
        "balance_checks": balance,
        "positive_fold_count": sum(value > 0.0 for value in deltas),
        "passed": truth_passed and all(original.values()) and all(balance.values()),
    }


def old_class_risk_flags(
    *, b0: Mapping[str, Any], b2: Mapping[str, Any]
) -> dict[str, Any]:
    """Report old-class drops over two percentage points without changing gates."""

    b0_values = b0.get("per_class_accuracy")
    b2_values = b2.get("per_class_accuracy")
    if (
        not isinstance(b0_values, Sequence)
        or isinstance(b0_values, (str, bytes))
        or not isinstance(b2_values, Sequence)
        or isinstance(b2_values, (str, bytes))
        or len(b0_values) != 13
        or len(b2_values) != 13
    ):
        raise ValueError("per_class_accuracy must contain exactly 13 values")
    drops = []
    flagged = []
    for label in range(10):
        drop = _finite(b0_values[label], name="b0 per-class accuracy") - _finite(
            b2_values[label], name="b2 per-class accuracy"
        )
        drops.append(drop)
        if drop > 0.02:
            flagged.append(label)
    return {
        "threshold": 0.02,
        "drops": drops,
        "classes": flagged,
        "flagged": bool(flagged),
        "changes_gate": False,
    }


def aggregate_multiseed_confirmation(
    seed_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Describe three fixed seeds without allowing means to mask failures."""

    if isinstance(seed_results, (str, bytes)) or len(seed_results) != 3:
        raise ValueError("exactly seeds 2026, 2027, and 2028 are required")
    by_seed: dict[int, Mapping[str, Any]] = {}
    for result in seed_results:
        seed = result.get("seed")
        if type(seed) is not int or seed in by_seed:
            raise ValueError("exactly seeds 2026, 2027, and 2028 are required")
        if type(result.get("passed")) is not bool:
            raise ValueError("seed passed flag must be boolean")
        if not isinstance(result.get("b2"), Mapping):
            raise ValueError("seed B2 summary is required")
        by_seed[seed] = result
    if set(by_seed) != {2026, 2027, 2028}:
        raise ValueError("exactly seeds 2026, 2027, and 2028 are required")
    descriptive = {}
    for metric in REGISTERED_METRICS:
        values = {
            seed: _summary_metric(by_seed[seed]["b2"], metric)
            for seed in (2026, 2027, 2028)
        }
        ordered = list(values.values())
        worst_seed = min(values, key=lambda seed: (values[seed], seed))
        descriptive[metric] = {
            "per_seed": {str(seed): values[seed] for seed in (2026, 2027, 2028)},
            "mean": mean(ordered),
            "sample_sd": stdev(ordered),
            "ddof": 1,
            "min": min(ordered),
            "max": max(ordered),
            "worst_seed": worst_seed,
        }
    failed = [seed for seed in (2026, 2027, 2028) if not by_seed[seed]["passed"]]
    all_passed = not failed
    if all_passed:
        classification = "three_seed_consistent"
    elif not by_seed[2027]["passed"] and not by_seed[2028]["passed"]:
        classification = "seed2026_local_only"
    else:
        classification = "seed_sensitive"
    return {
        "schema": "b2_class12_multiseed_summary_v1",
        "seed_order": [2026, 2027, 2028],
        "per_seed": {str(seed): dict(by_seed[seed]) for seed in (2026, 2027, 2028)},
        "descriptive": descriptive,
        "failed_seeds": failed,
        "all_seeds_passed": all_passed,
        "classification": classification,
    }
