import pytest

from lwf_revision.b2_class12_multiseed import aggregate_multiseed_confirmation


def _seed(seed, passed, value):
    return {
        "seed": seed,
        "passed": passed,
        "b2": {
            "class10_accuracy": value,
            "class11_accuracy": value + 0.01,
            "class12_accuracy": value + 0.02,
            "old_macro_accuracy": value + 0.03,
            "pair_harmonic_accuracy": value + 0.04,
            "triple_harmonic_accuracy": value + 0.05,
            "triple_worst_accuracy": value,
            "overall_accuracy": value + 0.06,
        },
        "old_class_risk": {"flagged": False, "classes": []},
    }


def test_mean_cannot_mask_single_seed_failure():
    status = aggregate_multiseed_confirmation(
        [_seed(2026, True, 0.60), _seed(2027, False, 0.90), _seed(2028, True, 0.80)]
    )
    assert status["descriptive"]["triple_harmonic_accuracy"]["ddof"] == 1
    assert status["descriptive"]["triple_harmonic_accuracy"]["mean"] == pytest.approx(0.8166666667)
    assert status["all_seeds_passed"] is False
    assert status["classification"] == "seed_sensitive"
    assert status["failed_seeds"] == [2027]


def test_three_passes_are_consistent_and_report_worst_seed():
    status = aggregate_multiseed_confirmation(
        [_seed(2026, True, 0.60), _seed(2027, True, 0.70), _seed(2028, True, 0.80)]
    )
    assert status["all_seeds_passed"] is True
    assert status["classification"] == "three_seed_consistent"
    assert status["descriptive"]["class10_accuracy"]["min"] == 0.60
    assert status["descriptive"]["class10_accuracy"]["max"] == 0.80
    assert status["descriptive"]["class10_accuracy"]["worst_seed"] == 2026
    assert status["descriptive"]["class10_accuracy"]["sample_sd"] == pytest.approx(0.1)


def test_both_new_fail_classifies_seed2026_as_local_only():
    status = aggregate_multiseed_confirmation(
        [_seed(2026, True, 0.60), _seed(2027, False, 0.70), _seed(2028, False, 0.80)]
    )
    assert status["classification"] == "seed2026_local_only"
    assert status["failed_seeds"] == [2027, 2028]


def test_requires_exactly_the_registered_three_seeds():
    with pytest.raises(ValueError, match="exactly seeds 2026, 2027, and 2028"):
        aggregate_multiseed_confirmation([_seed(2026, True, 0.6)])
