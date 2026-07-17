import math

from cil_restart.metrics import average_incremental_accuracy, class_forgetting, mean_std


def test_aia_is_arithmetic_mean():
    assert average_incremental_accuracy([80.0, 70.0, 60.0]) == 70.0


def test_class_forgetting_excludes_final_new_classes():
    history = [
        [80.0, 70.0, math.nan, math.nan],
        [75.0, 65.0, 90.0, math.nan],
        [70.0, 60.0, 85.0, 95.0],
    ]
    assert class_forgetting(history) == (10.0 + 10.0 + 5.0) / 3.0


def test_mean_std_requires_three_seeds():
    try:
        mean_std([1.0, 2.0])
    except ValueError as exc:
        assert "at least 3" in str(exc)
    else:
        raise AssertionError("missing seeds must be rejected")
