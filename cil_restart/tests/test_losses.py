import torch

from cil_restart.losses import ce_gradient_signs, group_separated_loss, kd_shift_delta


def test_old_class_kd_is_invariant_to_common_shift():
    torch.manual_seed(7)
    s = torch.randn(8, 12)
    t = torch.randn(8, 11)
    assert kd_shift_delta(s, t, old_classes=11, shift=-100.0) < 1e-5


def test_new_class_ce_pushes_old_logits_down_during_gradient_descent():
    signs = ce_gradient_signs()
    assert signs["target"] < 0
    assert signs["old_mean"] > 0


def test_group_separated_loss_has_new_row_gradient_for_one_new_class():
    logits = torch.zeros(4, 12, requires_grad=True)
    labels = torch.tensor([0, 1, 11, 11])
    loss = group_separated_loss(logits, labels, old_classes=11)
    loss.backward()
    assert logits.grad[:, 11].abs().sum() > 0

