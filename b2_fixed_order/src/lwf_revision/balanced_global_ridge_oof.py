from __future__ import annotations
from collections.abc import Sequence
import hashlib
import torch

def _integer_labels(labels: torch.Tensor | Sequence[int], *, expected_count: int, classes: int=12) -> list[int]:
    if isinstance(labels, torch.Tensor):
        if labels.ndim != 1 or labels.dtype == torch.bool or labels.is_floating_point():
            raise ValueError('labels必须为一维整数张量')
        values = [int(value) for value in labels.detach().cpu().tolist()]
    elif isinstance(labels, Sequence) and (not isinstance(labels, (str, bytes))):
        values = []
        for value in labels:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError('labels必须为整数序列')
            values.append(value)
    else:
        raise ValueError('labels必须为一维整数序列')
    if len(values) != expected_count:
        raise ValueError('labels数量与特征不一致')
    if any((value < 0 or value >= classes for value in values)):
        raise ValueError('labels超出类别范围')
    return values

def _identity_paths(paths: Sequence[str], *, expected_count: int) -> list[str]:
    if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence):
        raise ValueError('身份路径必须为字符串序列')
    values = list(paths)
    if len(values) != expected_count:
        raise ValueError('身份路径数量与特征不一致')
    if any((not isinstance(value, str) or not value or '\\' in value or value.startswith('/') for value in values)):
        raise ValueError('身份路径格式错误')
    if len(set(values)) != len(values):
        raise ValueError('身份路径重复')
    return values

def assign_balanced_folds(labels: torch.Tensor | Sequence[int], paths: Sequence[str], *, seed: int, n_folds: int=5, classes: int=12) -> list[int]:
    """按类别内稳定哈希排序后轮转分配折号。"""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError('seed必须为整数')
    if isinstance(n_folds, bool) or not isinstance(n_folds, int) or n_folds < 2:
        raise ValueError('n_folds必须为不小于2的整数')
    if isinstance(classes, bool) or not isinstance(classes, int) or classes < 2:
        raise ValueError('classes必须为不小于2的整数')
    path_values = _identity_paths(paths, expected_count=len(paths))
    label_values = _integer_labels(labels, expected_count=len(path_values), classes=classes)
    assignments = [-1] * len(path_values)
    for label in range(classes):
        indices = [index for index, value in enumerate(label_values) if value == label]
        if not indices or len(indices) % n_folds != 0:
            raise ValueError('每类样本数必须为正且能被折数整除')
        ordered = sorted(indices, key=lambda index: hashlib.sha256(f'{seed}\n{path_values[index]}'.encode('utf-8')).digest())
        for rank, index in enumerate(ordered):
            assignments[index] = rank % n_folds
    if any((value < 0 for value in assignments)):
        raise AssertionError('折分未覆盖全部身份')
    return assignments
