import math

import pytest
import torch

from lwf_revision.frozen_head_reconstruction import fit_centered_ridge
from lwf_revision.recursive_centered_ridge import RidgeSufficientStatistics


def test_recursive_statistics_match_batch_centered_ridge():
    x = torch.tensor(
        [[1.0, 2.0], [2.0, 1.0], [4.0, 3.0], [3.0, 4.0]],
        dtype=torch.float64,
    )
    y = torch.tensor([0, 0, 1, 1], dtype=torch.long)
    batch_w, batch_b = fit_centered_ridge(x, y, classes=2, l2=1.0)
    left = RidgeSufficientStatistics.from_samples(x[:2], y[:2], classes=2)
    right = RidgeSufficientStatistics.from_samples(x[2:], y[2:], classes=2)
    recursive_w, recursive_b = left.merge(right).solve(l2=1.0)
    torch.testing.assert_close(recursive_w, batch_w, atol=1e-10, rtol=0)
    torch.testing.assert_close(recursive_b, batch_b, atol=1e-10, rtol=0)


def test_centered_intercept_formula_is_exact():
    x = torch.tensor([[1.0], [2.0], [7.0], [8.0]], dtype=torch.float64)
    y = torch.tensor([0, 0, 1, 1], dtype=torch.long)
    stats = RidgeSufficientStatistics.from_samples(x, y, classes=2)
    weight, bias = stats.solve(l2=1.0)
    expected = stats.sum_y / stats.n - (stats.sum_x / stats.n) @ weight
    torch.testing.assert_close(bias, expected, atol=0, rtol=0)


def test_class_expansion_pads_only_target_statistics():
    stats = RidgeSufficientStatistics.from_samples(
        torch.eye(2, dtype=torch.float64), torch.tensor([0, 1]), classes=2
    )
    expanded = stats.expand_classes(3)
    assert expanded.n == stats.n
    assert torch.equal(expanded.sum_x, stats.sum_x)
    assert torch.equal(expanded.sum_xx, stats.sum_xx)
    assert torch.equal(expanded.sum_y[:2], stats.sum_y)
    assert torch.equal(expanded.sum_xy[:, :2], stats.sum_xy)
    assert torch.count_nonzero(expanded.sum_y[2:]) == 0
    assert torch.count_nonzero(expanded.sum_xy[:, 2:]) == 0


def test_merge_order_is_numerically_equivalent():
    generator = torch.Generator().manual_seed(77)
    x = torch.randn(18, 5, generator=generator, dtype=torch.float64)
    y = torch.arange(3).repeat_interleave(6)
    blocks = [
        RidgeSufficientStatistics.from_samples(x[y == label], y[y == label], classes=3)
        for label in range(3)
    ]
    forward = blocks[0].merge(blocks[1]).merge(blocks[2])
    reverse = blocks[2].merge(blocks[1]).merge(blocks[0])
    for left, right in zip(forward.solve(l2=1.0), reverse.solve(l2=1.0)):
        torch.testing.assert_close(left, right, atol=1e-12, rtol=0)


@pytest.mark.parametrize(
    ("x", "y", "classes", "match"),
    [
        (torch.ones(2), torch.tensor([0, 1]), 2, "matrix"),
        (torch.ones(2, 2), torch.tensor([[0], [1]]), 2, "labels"),
        (torch.ones(2, 2), torch.tensor([0.0, 1.0]), 2, "integer"),
        (torch.ones(2, 2), torch.tensor([0, 2]), 2, "range"),
        (torch.ones(2, 2), torch.tensor([0, 1]), 1, "classes"),
        (torch.empty(0, 2), torch.empty(0, dtype=torch.long), 2, "empty"),
    ],
)
def test_from_samples_rejects_invalid_inputs(x, y, classes, match):
    with pytest.raises(ValueError, match=match):
        RidgeSufficientStatistics.from_samples(x, y, classes=classes)


def test_from_samples_rejects_non_finite_features():
    x = torch.tensor([[1.0, math.nan], [2.0, 3.0]])
    with pytest.raises(ValueError, match="finite"):
        RidgeSufficientStatistics.from_samples(x, torch.tensor([0, 1]), classes=2)


@pytest.mark.parametrize("l2", [0, -1, math.nan, math.inf, True, "1"])
def test_solve_rejects_invalid_regularization(l2):
    stats = RidgeSufficientStatistics.from_samples(
        torch.eye(2, dtype=torch.float64), torch.tensor([0, 1]), classes=2
    )
    with pytest.raises(ValueError, match="l2"):
        stats.solve(l2=l2)


def test_merge_rejects_feature_and_class_dimension_mismatch():
    two_features = RidgeSufficientStatistics.from_samples(
        torch.eye(2, dtype=torch.float64), torch.tensor([0, 1]), classes=2
    )
    three_features = RidgeSufficientStatistics.from_samples(
        torch.eye(3, dtype=torch.float64), torch.tensor([0, 1, 2]), classes=3
    )
    with pytest.raises(ValueError, match="dimension"):
        two_features.merge(three_features)

    two_features_three_classes = two_features.expand_classes(3)
    with pytest.raises(ValueError, match="classes"):
        two_features.merge(two_features_three_classes)


def test_constructor_rejects_polluted_or_inconsistent_statistics():
    with pytest.raises(ValueError, match="n"):
        RidgeSufficientStatistics(
            n=0,
            sum_x=torch.zeros(2, dtype=torch.float64),
            sum_y=torch.zeros(2, dtype=torch.float64),
            sum_xx=torch.zeros(2, 2, dtype=torch.float64),
            sum_xy=torch.zeros(2, 2, dtype=torch.float64),
        )

    with pytest.raises(ValueError, match="sum_y"):
        RidgeSufficientStatistics(
            n=2,
            sum_x=torch.zeros(2, dtype=torch.float64),
            sum_y=torch.tensor([1.0, math.nan], dtype=torch.float64),
            sum_xx=torch.zeros(2, 2, dtype=torch.float64),
            sum_xy=torch.zeros(2, 2, dtype=torch.float64),
        )


def test_to_dict_round_trip_uses_exact_aggregate_fields():
    stats = RidgeSufficientStatistics.from_samples(
        torch.eye(2, dtype=torch.float64), torch.tensor([0, 1]), classes=2
    )
    payload = stats.to_dict()
    assert set(payload) == {"n", "sum_x", "sum_y", "sum_xx", "sum_xy"}
    restored = RidgeSufficientStatistics.from_dict(payload)
    assert restored.n == stats.n
    for name in ("sum_x", "sum_y", "sum_xx", "sum_xy"):
        assert torch.equal(getattr(restored, name), getattr(stats, name))


@pytest.mark.parametrize("missing", ["n", "sum_x", "sum_y", "sum_xx", "sum_xy"])
def test_from_dict_rejects_missing_statistics(missing):
    stats = RidgeSufficientStatistics.from_samples(
        torch.eye(2, dtype=torch.float64), torch.tensor([0, 1]), classes=2
    ).to_dict()
    del stats[missing]
    with pytest.raises(ValueError, match="fields"):
        RidgeSufficientStatistics.from_dict(stats)


def test_from_dict_rejects_extra_statistics():
    stats = RidgeSufficientStatistics.from_samples(
        torch.eye(2, dtype=torch.float64), torch.tensor([0, 1]), classes=2
    ).to_dict()
    stats["features"] = torch.eye(2)
    with pytest.raises(ValueError, match="fields"):
        RidgeSufficientStatistics.from_dict(stats)
