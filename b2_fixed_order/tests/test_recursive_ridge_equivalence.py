import pytest
import torch

from lwf_revision.recursive_ridge_equivalence import (
    RecursiveEquivalenceDataset,
    StageBlock,
    evaluate_recursive_equivalence,
)


def _case():
    generator = torch.Generator().manual_seed(20260825)
    centers = torch.tensor(
        [[-3.0, -3.0], [-3.0, 3.0], [3.0, -3.0], [3.0, 3.0]],
        dtype=torch.float64,
    )
    fit_x = torch.cat(
        [center + 0.1 * torch.randn(8, 2, generator=generator) for center in centers]
    ).to(torch.float64)
    fit_y = torch.arange(4).repeat_interleave(8)
    holdout_x = torch.cat(
        [center + 0.1 * torch.randn(3, 2, generator=generator) for center in centers]
    ).to(torch.float64)
    holdout_y = torch.arange(4).repeat_interleave(3)
    return RecursiveEquivalenceDataset(
        fit_x=fit_x,
        fit_y=fit_y,
        holdout_x=holdout_x,
        holdout_y=holdout_y,
        stage_blocks=(
            StageBlock(fit_x[fit_y < 2], fit_y[fit_y < 2], classes=2),
            StageBlock(fit_x[fit_y == 2], fit_y[fit_y == 2], classes=3),
            StageBlock(fit_x[fit_y == 3], fit_y[fit_y == 3], classes=4),
        ),
    )


def test_c0_c1_c2_c3_are_equivalent():
    result = evaluate_recursive_equivalence(_case(), classes=4, l2=1.0)
    assert result.all_pass is True
    assert result.predictions_exact is True
    assert result.confusions_exact is True
    assert result.metrics_exact is True
    assert result.weight_max_abs <= 1e-10
    assert result.bias_max_abs <= 1e-10
    assert result.logit_max_abs <= 1e-9
    assert set(result.head_sha256) == {"c0", "c1", "c2", "c3"}
    assert len(set(result.head_sha256.values())) >= 1


def test_equivalence_reports_all_four_paths_and_raw_predictions():
    result = evaluate_recursive_equivalence(_case(), classes=4, l2=1.0)
    assert set(result.predictions) == {"c0", "c1", "c2", "c3"}
    assert set(result.confusion_matrices) == {"c0", "c1", "c2", "c3"}
    assert set(result.metrics) == {"c0", "c1", "c2", "c3"}
    assert result.predictions["c0"] == result.predictions["c3"]
    assert result.metrics["c0"]["overall_accuracy"] == 1.0


def test_dataset_rejects_stage_order_or_coverage_pollution():
    case = _case()
    bad = RecursiveEquivalenceDataset(
        fit_x=case.fit_x,
        fit_y=case.fit_y,
        holdout_x=case.holdout_x,
        holdout_y=case.holdout_y,
        stage_blocks=(case.stage_blocks[0], case.stage_blocks[2]),
    )
    with pytest.raises(ValueError, match="stage.*coverage"):
        evaluate_recursive_equivalence(bad, classes=4, l2=1.0)


def test_dataset_rejects_non_monotonic_class_expansion():
    case = _case()
    bad = RecursiveEquivalenceDataset(
        fit_x=case.fit_x,
        fit_y=case.fit_y,
        holdout_x=case.holdout_x,
        holdout_y=case.holdout_y,
        stage_blocks=(
            StageBlock(case.stage_blocks[0].features, case.stage_blocks[0].labels, 2),
            StageBlock(case.stage_blocks[2].features, case.stage_blocks[2].labels, 4),
            StageBlock(case.stage_blocks[1].features, case.stage_blocks[1].labels, 3),
        ),
    )
    with pytest.raises(ValueError, match="monotonic"):
        evaluate_recursive_equivalence(bad, classes=4, l2=1.0)


def test_equivalence_rejects_missing_class_in_fit_data():
    case = _case()
    keep = case.fit_y != 3
    bad = RecursiveEquivalenceDataset(
        fit_x=case.fit_x[keep],
        fit_y=case.fit_y[keep],
        holdout_x=case.holdout_x,
        holdout_y=case.holdout_y,
        stage_blocks=case.stage_blocks[:2],
    )
    with pytest.raises(ValueError, match="every class"):
        evaluate_recursive_equivalence(bad, classes=4, l2=1.0)


def test_result_serialization_contains_registered_tolerances():
    payload = evaluate_recursive_equivalence(_case(), classes=4, l2=1.0).to_dict()
    assert payload["schema"] == "recursive_ridge_equivalence_v1"
    assert payload["tolerances"] == {
        "weight_bias_atol": 1e-10,
        "logit_atol": 1e-9,
    }
    assert payload["all_pass"] is True
