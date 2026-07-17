from __future__ import annotations

import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

from .schema import write_raw_run


METHODS = {
    "finetune": ("FineTune", "finetune.yaml", "AccMatrix.csv"),
    "lwf": ("LwF", "lwf.yaml", "AccMatrix.csv"),
    "replay": ("Replay", "replay.yaml", "AccMatrix.csv"),
    "podnet": ("PODNet", "podnet.yaml", "AccMatrix_NME.csv"),
    "mtd_podnet": ("MTD-PODNet", "mtd_podnet.yaml", "AccMatrix_ENS.csv"),
    "ssil": ("SS-IL", "ssil.yaml", "AccMatrix.csv"),
    "mtd_ssil": ("MTD-SSIL", "mtd_ssil.yaml", "AccMatrix_ENS.csv"),
}


def dependency_report() -> dict[str, Any]:
    modules = {}
    for name in ["torch", "torchvision", "continuum", "yaml", "tensorboard", "scipy", "sklearn"]:
        try:
            mod = __import__(name)
            modules[name] = {"ok": True, "version": getattr(mod, "__version__", "unknown")}
        except Exception as exc:
            modules[name] = {"ok": False, "error": repr(exc)}
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "cuda_available": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "modules": modules,
    }


def _weighted_task_metrics(matrix: np.ndarray, increments: list[int]) -> list[dict[str, Any]]:
    tasks = []
    for i in range(matrix.shape[0]):
        accs = matrix[i, : i + 1] * 100.0
        weights = np.asarray(increments[: i + 1], dtype=float)
        overall = float(np.average(accs, weights=weights))
        if i == 0:
            old_acc, new_acc = math.nan, float(accs[0])
        else:
            old_acc = float(np.average(accs[:-1], weights=weights[:-1]))
            new_acc = float(accs[-1])
        tasks.append({
            "task_id": i,
            "learned_classes": int(weights.sum()),
            "overall_accuracy": overall,
            "old_accuracy": old_acc,
            "new_accuracy": new_acc,
            "task_accuracy": accs.tolist(),
            "per_class_accuracy": [],
            "confusion_matrix": [],
        })
    return tasks


def import_acc_matrix(project_root: Path, method_key: str, seed: int, matrix_path: Path, elapsed: float, peak_mb: float, stdout_path: Path) -> Path:
    method, _, _ = METHODS[method_key]
    matrix = np.atleast_2d(np.loadtxt(matrix_path, delimiter=None))
    tasks = _weighted_task_metrics(matrix, [50, 10, 10, 10, 10, 10])
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    run = {
        "schema_version": "1.0",
        "run_id": f"official_{method_key}_seed{seed}_{timestamp}",
        "method": method,
        "seed": seed,
        "scenario": "cifar100_b50_5s",
        "status": "partial",
        "protocol": {
            "dataset": "CIFAR100", "class_order": 0, "increments": [50, 10, 10, 10, 10, 10],
            "memory_per_class": 20 if method_key not in {"finetune", "lwf"} else 0,
            "checkpoint_selection": "fixed_last_epoch", "test_usage": "evaluation_after_fixed_training",
            "official_commit": "ce0789a40bda9e566a1e0432d3ac320937ca48f0",
        },
        "tasks": tasks,
        "diagnostics": {
            "instrumentation_level": "task_accuracy_matrix",
            "missing_for_complete_status": ["per_class_accuracy", "confusion_matrix", "logit_statistics", "classifier_statistics"],
            "official_stdout": str(stdout_path),
        },
        "runtime": {"training_seconds": elapsed, "peak_gpu_memory_mb": peak_mb},
        "environment": dependency_report(),
    }
    return write_raw_run(run, project_root / "results" / "raw")


def run_official(project_root: Path, method_key: str, seed: int, epochs: int | None = None, tasks: int | None = None) -> Path:
    if method_key not in METHODS:
        raise ValueError(f"unknown method {method_key}")
    report = dependency_report()
    if not report["modules"]["continuum"]["ok"]:
        raise RuntimeError("continuum is unavailable; run scripts/check_official.py for the compatibility report")
    method, cfg_name, matrix_name = METHODS[method_key]
    cfg_path = project_root / "configs" / "official" / cfg_name
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["seed"] = seed
    if epochs is not None:
        cfg["epochs"] = epochs
        if "finetuning_config" in cfg:
            cfg["finetuning_config"]["epochs"] = min(cfg["finetuning_config"]["epochs"], epochs)
        if "finetune" in cfg:
            cfg["finetune"]["epochs"] = min(cfg["finetune"]["epochs"], epochs)
    if tasks is not None:
        cfg["tasks"] = tasks
    run_name = f"runs/{method_key}/seed{seed}"
    cfg["name"] = run_name
    run_dir = project_root / "outputs" / "official" / method_key / f"seed{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    generated_cfg = run_dir / "config.yaml"
    generated_cfg.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    stdout_path = run_dir / "stdout.log"
    official = project_root / "third_party" / "CLearning"
    log_root = project_root / "outputs" / "clearning_logs"
    cmd = [sys.executable, "main.py", "--cfg", str(generated_cfg), "--seed", str(seed), "--logdir", str(log_root) + os.sep, "--opt", "time_memory"]
    started = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    with stdout_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, cwd=official, stdout=log, stderr=subprocess.STDOUT, text=True)
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        raise RuntimeError(f"official run failed; inspect {stdout_path}")
    matrix_path = log_root / run_name / matrix_name
    if not matrix_path.exists():
        alternatives = list((log_root / run_name).glob("AccMatrix*.csv"))
        raise FileNotFoundError(f"expected {matrix_path}; found {alternatives}")
    peak_mb = float(torch.cuda.max_memory_allocated() / 2**20) if torch.cuda.is_available() else 0.0
    return import_acc_matrix(project_root, method_key, seed, matrix_path, elapsed, peak_mb, stdout_path)

