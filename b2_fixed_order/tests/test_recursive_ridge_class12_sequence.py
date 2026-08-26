import math
import pytest
import torch
from lwf_revision.recursive_ridge_class12_sequence import b2_learnability_checks, harmonic_nonzero, summarize_class12_predictions

def _metrics(**changes):
    base = {'class10_accuracy': 0.6, 'class11_accuracy': 0.7, 'class12_accuracy': 0.55, 'old_macro_accuracy': 0.8, 'overall_accuracy': 0.76, 'pair_harmonic_accuracy': harmonic_nonzero((0.6, 0.7)), 'triple_harmonic_accuracy': harmonic_nonzero((0.6, 0.7, 0.55)), 'triple_macro_accuracy': (0.6 + 0.7 + 0.55) / 3, 'triple_worst_accuracy': 0.55}
    base.update(changes)
    return base

def test_summary_reports_all_registered_metrics_and_flows():
    labels = torch.arange(13).repeat_interleave(2)
    predictions = labels.clone()
    predictions[20] = 11
    predictions[22] = 10
    predictions[24] = 11
    summary = summarize_class12_predictions(labels, predictions, classes=13)
    assert len(summary['per_class_accuracy']) == 13
    assert summary['class10_accuracy'] == 0.5
    assert summary['class11_accuracy'] == 0.5
    assert summary['class12_accuracy'] == 0.5
    assert summary['flow_10_to_11'] == 1
    assert summary['flow_11_to_10'] == 1
    assert summary['flow_12_to_11'] == 1
    assert summary['flow_12_to_10'] == 0
    assert summary['old_to_recent'] == 0

def test_b2_gate_accepts_exact_approved_boundaries():
    b0 = _metrics(class12_accuracy=0.5, triple_worst_accuracy=0.5, old_macro_accuracy=0.805)
    b2 = _metrics(class12_accuracy=0.5, triple_worst_accuracy=0.5, old_macro_accuracy=0.8)
    checks = b2_learnability_checks(b0=b0, b2=b2, equivalence_passed=True, audit_passed=True)
    assert all(checks.values())

@pytest.mark.parametrize(('change', 'key'), [({'class12_accuracy': 0.499999}, 'class12_minimum'), ({'class10_accuracy': 0.0}, 'recent_classes_nonzero'), ({'triple_worst_accuracy': 0.499999}, 'triple_worst_vs_b0'), ({'old_macro_accuracy': 0.799999}, 'old_macro_budget')])
def test_b2_gate_rejects_just_outside_boundaries(change, key):
    b0 = _metrics(class12_accuracy=0.5, triple_worst_accuracy=0.5, old_macro_accuracy=0.805)
    values = {'class12_accuracy': 0.5, 'triple_worst_accuracy': 0.5, 'old_macro_accuracy': 0.8}
    values.update(change)
    b2 = _metrics(**values)
    checks = b2_learnability_checks(b0=b0, b2=b2, equivalence_passed=True, audit_passed=True)
    assert checks[key] is False

@pytest.mark.parametrize('values', [(0.0, 0.5), (0.5, 0.0), ()])
def test_harmonic_nonzero_returns_zero_when_any_component_is_zero(values):
    assert harmonic_nonzero(values) == 0.0
