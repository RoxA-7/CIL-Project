from __future__ import annotations

import importlib.util
import json
import math
import os
import platform
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from torch import nn
from torch.utils.data import DataLoader, Subset, TensorDataset
from torchvision import datasets, transforms

from .losses import group_separated_loss, kd_shift_delta, old_class_kd
from .schema import write_raw_run


CLASS_NAMES = [
    "apple", "clock", "keyboard", "lamp", "mushroom", "orange", "pear",
    "sweet_pepper", "telephone", "television", "bus", "train", "wolf",
]


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def _load_legacy_model(legacy_root: Path, checkpoint: Path, device: torch.device) -> nn.Module:
    spec = importlib.util.spec_from_file_location("legacy_vgg_model", legacy_root / "model.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load legacy model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.vgg(model_name="vgg16", num_classes=11, init_weights=False)
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    state = {k.removeprefix("module."): v for k, v in state.items()}
    model.load_state_dict(state, strict=True)
    return model.to(device).eval()


@torch.inference_mode()
def _penultimate(model: nn.Module, images: torch.Tensor) -> torch.Tensor:
    x = model.features(images)
    x = torch.flatten(x, 1)
    return model.classifier[:6](x)


def _select_indices(dataset: datasets.ImageFolder, allowed: set[int], memory_per_class: int | None) -> list[int]:
    by_class: dict[int, list[int]] = {c: [] for c in allowed}
    for idx, (_, label) in enumerate(dataset.samples):
        if label in allowed:
            by_class[label].append(idx)
    selected: list[int] = []
    for label in sorted(allowed):
        ids = by_class[label]
        selected.extend(ids if memory_per_class is None else ids[:memory_per_class])
    return selected


@torch.inference_mode()
def _extract_subset(model: nn.Module, dataset: datasets.ImageFolder, indices: list[int], device: torch.device, batch_size: int) -> tuple[torch.Tensor, torch.Tensor]:
    loader = DataLoader(Subset(dataset, indices), batch_size=batch_size, shuffle=False, num_workers=0, pin_memory=device.type == "cuda")
    features, labels = [], []
    for images, y in loader:
        features.append(_penultimate(model, images.to(device, non_blocking=True)).cpu())
        labels.append(y.cpu())
    return torch.cat(features), torch.cat(labels)


def build_feature_cache(cfg: dict[str, Any], project_root: Path, force: bool = False) -> Path:
    cache_path = (project_root / cfg["feature_cache"]).resolve()
    if cache_path.exists() and not force:
        return cache_path
    seed_everything(int(cfg["seed"]))
    legacy_root = (project_root / cfg["legacy_root"]).resolve()
    checkpoint = (project_root / cfg["checkpoint"]).resolve()
    data_root = (project_root / cfg["data_root"]).resolve()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])
    train_ds = datasets.ImageFolder(data_root / "train", transform=transform)
    test_ds = datasets.ImageFolder(data_root / "test", transform=transform)
    if train_ds.classes[:13] != [f"{i + 1:02d}_{name}" for i, name in enumerate(CLASS_NAMES)]:
        raise ValueError(f"unexpected legacy class order: {train_ds.classes[:13]}")
    model = _load_legacy_model(legacy_root, checkpoint, device)
    new_idx = _select_indices(train_ds, {11}, None)
    replay_idx = _select_indices(train_ds, set(range(11)), int(cfg["memory_per_class"]))
    test_idx = _select_indices(test_ds, set(range(12)), None)
    started = time.perf_counter()
    new_x, new_y = _extract_subset(model, train_ds, new_idx, device, int(cfg["batch_size"]))
    replay_x, replay_y = _extract_subset(model, train_ds, replay_idx, device, int(cfg["batch_size"]))
    test_x, test_y = _extract_subset(model, test_ds, test_idx, device, int(cfg["batch_size"]))
    payload = {
        "new_x": new_x, "new_y": new_y,
        "replay_x": replay_x, "replay_y": replay_y,
        "test_x": test_x, "test_y": test_y,
        "old_weight": model.classifier[6].weight.detach().cpu(),
        "old_bias": model.classifier[6].bias.detach().cpu(),
        "class_names": CLASS_NAMES,
        "checkpoint": str(checkpoint),
        "feature_seconds": time.perf_counter() - started,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, cache_path)
    return cache_path


def _init_head(cache: dict[str, Any], mode: str, seed: int) -> nn.Linear:
    torch.manual_seed(seed)
    head = nn.Linear(cache["new_x"].shape[1], 12)
    nn.init.xavier_uniform_(head.weight)
    nn.init.zeros_(head.bias)
    if mode == "copy":
        with torch.no_grad():
            head.weight[:11].copy_(cache["old_weight"])
            head.bias[:11].copy_(cache["old_bias"])
    elif mode != "reset":
        raise ValueError(f"unknown head_init: {mode}")
    return head


def _loss_parts(head: nn.Linear, x: torch.Tensor, y: torch.Tensor, teacher_logits: torch.Tensor, spec: dict[str, Any], cfg: dict[str, Any]) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    logits = head(x)
    if spec["loss"] == "ce_kd":
        primary = F.cross_entropy(logits, y)
    elif spec["loss"] == "group_separated":
        primary = group_separated_loss(logits, y, old_classes=11)
    else:
        raise ValueError(spec["loss"])
    kd = old_class_kd(logits, teacher_logits, old_classes=11, temperature=float(cfg["temperature"]))
    total = float(cfg["lambda_ce"]) * primary + (1.0 - float(cfg["lambda_ce"])) * kd
    return total, primary, kd


def _gradient_audit(head: nn.Linear, x: torch.Tensor, y: torch.Tensor, teacher_logits: torch.Tensor, spec: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    audits: dict[str, Any] = {}
    _, primary, kd = _loss_parts(head, x, y, teacher_logits, spec, cfg)
    for name, loss in (("ce_or_group", primary), ("kd", kd)):
        head.zero_grad(set_to_none=True)
        loss.backward(retain_graph=True)
        grad = head.weight.grad.detach()
        audits[name] = {
            "old_row_norm_mean": float(grad[:11].norm(dim=1).mean()),
            "new_row_norm": float(grad[11].norm()),
            "old_row_signed_mean": float(grad[:11].mean()),
            "new_row_signed_mean": float(grad[11].mean()),
        }
    head.zero_grad(set_to_none=True)
    return audits


@torch.inference_mode()
def _evaluate(head: nn.Linear, x: torch.Tensor, y: torch.Tensor) -> dict[str, Any]:
    logits = head(x)
    pred = logits.argmax(1)
    per_class: list[float] = []
    confusion = torch.zeros(12, 12, dtype=torch.int64)
    for target, guess in zip(y.cpu(), pred.cpu()):
        confusion[target, guess] += 1
    for c in range(12):
        mask = y == c
        per_class.append(float((pred[mask] == c).float().mean().item() * 100.0))
    old_acc = float(np.mean(per_class[:11]))
    new_acc = per_class[11]
    overall = float((pred == y).float().mean().item() * 100.0)
    old_logit = float(logits[:, :11].mean().item())
    new_logit = float(logits[:, 11:].mean().item())
    bus_row = confusion[10]
    bus_errors = {CLASS_NAMES[i]: int(bus_row[i]) for i in range(12) if i != 10 and bus_row[i] > 0}
    return {
        "overall_accuracy": overall,
        "old_accuracy": old_acc,
        "new_accuracy": new_acc,
        "per_class_accuracy": per_class,
        "confusion_matrix": confusion.tolist(),
        "mean_old_logits": old_logit,
        "mean_new_logits": new_logit,
        "logit_gap": new_logit - old_logit,
        "bus_accuracy": per_class[10],
        "train_accuracy": per_class[11],
        "bus_misclassified_as": bus_errors,
        "classifier_weight_norms": head.weight.norm(dim=1).cpu().tolist(),
        "classifier_bias": head.bias.cpu().tolist(),
    }


def run_variant(cfg: dict[str, Any], project_root: Path, variant: str, force_cache: bool = False) -> Path:
    spec = cfg["variants"][variant]
    seed = int(cfg["seed"])
    seed_everything(seed)
    cache_path = build_feature_cache(cfg, project_root, force=force_cache)
    cache = torch.load(cache_path, map_location="cpu", weights_only=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    head = _init_head(cache, spec["head_init"], seed).to(device)
    old_teacher = nn.Linear(cache["old_weight"].shape[1], 11).to(device)
    with torch.no_grad():
        old_teacher.weight.copy_(cache["old_weight"].to(device))
        old_teacher.bias.copy_(cache["old_bias"].to(device))
    old_teacher.requires_grad_(False).eval()

    if spec["replay"]:
        x = torch.cat([cache["new_x"], cache["replay_x"]])
        y = torch.cat([cache["new_y"], cache["replay_y"]])
    else:
        x, y = cache["new_x"], cache["new_y"]
    train_ds = TensorDataset(x, y)
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(train_ds, batch_size=int(cfg["batch_size"]), shuffle=True, generator=generator)
    test_x, test_y = cache["test_x"].to(device), cache["test_y"].to(device)
    optimizer = torch.optim.Adam(head.parameters(), lr=float(cfg["learning_rate"]))
    tasks = []
    started = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    for epoch in range(int(cfg["epochs"])):
        head.train()
        grad_audit = None
        loss_totals = Counter()
        batches = 0
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            teacher_logits = old_teacher(xb)
            if grad_audit is None:
                grad_audit = _gradient_audit(head, xb, yb, teacher_logits, spec, cfg)
            optimizer.zero_grad(set_to_none=True)
            total, primary, kd = _loss_parts(head, xb, yb, teacher_logits, spec, cfg)
            total.backward()
            if not spec["update_old_rows"]:
                head.weight.grad[:11].zero_()
                head.bias.grad[:11].zero_()
            optimizer.step()
            loss_totals.update(total=float(total.detach()), primary=float(primary.detach()), kd=float(kd.detach()))
            batches += 1
        head.eval()
        record = _evaluate(head, test_x, test_y)
        record.update({
            "task_id": epoch,
            "epoch": epoch + 1,
            "learned_classes": 12,
            "loss_total": loss_totals["total"] / batches,
            "loss_primary": loss_totals["primary"] / batches,
            "loss_kd": loss_totals["kd"] / batches,
            "gradient_audit": grad_audit,
        })
        tasks.append(record)

    probe_s = torch.randn(32, 12)
    probe_t = torch.randn(32, 11)
    elapsed = time.perf_counter() - started
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    run = {
        "schema_version": "1.0",
        "run_id": f"diag_{variant}_seed{seed}_{timestamp}",
        "method": variant,
        "seed": seed,
        "scenario": "legacy_head_diagnostic",
        "status": "complete",
        "protocol": {
            "dataset": "legacy_CIFAR100_JPEG_subset",
            "transition": "11_to_12",
            "old_classes": 11,
            "new_classes": 1,
            "memory_per_class": int(cfg["memory_per_class"]) if spec["replay"] else 0,
            "epochs": int(cfg["epochs"]),
            "checkpoint_selection": "fixed_last_epoch",
            "test_usage": "evaluation_after_each_diagnostic_epoch_not_checkpoint_selection",
            "variant": spec,
        },
        "tasks": tasks,
        "diagnostics": {
            "kd_common_shift_delta": kd_shift_delta(probe_s, probe_t, 11, -100.0),
            "class_names": CLASS_NAMES[:12],
            "feature_cache": str(cache_path),
            "determinism": {"cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"), "torch_deterministic": True},
        },
        "runtime": {
            "training_seconds": elapsed,
            "peak_gpu_memory_mb": float(torch.cuda.max_memory_allocated(device) / 2**20) if device.type == "cuda" else 0.0,
            "trainable_parameters": sum(p.numel() for p in head.parameters() if p.requires_grad),
        },
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu",
            "platform": platform.platform(),
        },
    }
    return write_raw_run(run, project_root / "results" / "raw")


def load_config(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
