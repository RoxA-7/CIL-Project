from __future__ import annotations

import torch
import torch.nn.functional as F


def old_class_kd(student_logits: torch.Tensor, teacher_logits: torch.Tensor, old_classes: int, temperature: float = 2.0) -> torch.Tensor:
    s = F.log_softmax(student_logits[:, :old_classes] / temperature, dim=1)
    t = F.softmax(teacher_logits[:, :old_classes] / temperature, dim=1)
    return F.kl_div(s, t, reduction="batchmean") * temperature**2


def group_separated_loss(logits: torch.Tensor, labels: torch.Tensor, old_classes: int) -> torch.Tensor:
    """Separated old-class classification plus calibrated old/new group CE.

    For a one-new-class diagnostic, softmax over the new-class block alone is
    degenerate. The two group logits [logsumexp(old), logsumexp(new)] keep the
    old/new decision trainable, while old replay samples retain old-class CE.
    This is a diagnostic analogue, not a replacement for official SS-IL.
    """
    if not 0 < old_classes < logits.shape[1]:
        raise ValueError("old_classes must split the classifier into two non-empty blocks")
    is_new = labels >= old_classes
    group_logits = torch.stack(
        [torch.logsumexp(logits[:, :old_classes], dim=1), torch.logsumexp(logits[:, old_classes:], dim=1)],
        dim=1,
    )
    loss = F.cross_entropy(group_logits, is_new.long())
    if (~is_new).any():
        loss = loss + F.cross_entropy(logits[~is_new, :old_classes], labels[~is_new])
    if is_new.any() and logits.shape[1] - old_classes > 1:
        loss = loss + F.cross_entropy(logits[is_new, old_classes:], labels[is_new] - old_classes)
    return loss


def kd_shift_delta(student_logits: torch.Tensor, teacher_logits: torch.Tensor, old_classes: int, shift: float = -10.0) -> float:
    base = old_class_kd(student_logits, teacher_logits, old_classes)
    shifted = student_logits.clone()
    shifted[:, :old_classes] += shift
    return float((old_class_kd(shifted, teacher_logits, old_classes) - base).abs().item())


def ce_gradient_signs(num_classes: int = 12, target: int = 11) -> dict[str, float]:
    logits = torch.zeros(1, num_classes, requires_grad=True)
    F.cross_entropy(logits, torch.tensor([target])).backward()
    g = logits.grad.detach()[0]
    return {"target": float(g[target]), "old_mean": float(g[:target].mean()), "old_min": float(g[:target].min())}

