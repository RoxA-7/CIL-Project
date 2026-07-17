from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_RUN_FIELDS = {"schema_version", "run_id", "method", "seed", "scenario", "status", "protocol", "tasks"}
REQUIRED_TASK_FIELDS = {"task_id", "learned_classes", "overall_accuracy", "old_accuracy", "new_accuracy"}


def validate_run(run: dict[str, Any], require_complete: bool = False) -> None:
    missing = REQUIRED_RUN_FIELDS - run.keys()
    if missing:
        raise ValueError(f"run missing fields: {sorted(missing)}")
    if require_complete and run["status"] != "complete":
        raise ValueError(f"run {run['run_id']} is not complete")
    if not isinstance(run["seed"], int):
        raise ValueError("seed must be an integer")
    if not run["tasks"]:
        raise ValueError("tasks must be non-empty")
    expected_ids = list(range(len(run["tasks"])))
    actual_ids = [t.get("task_id") for t in run["tasks"]]
    if actual_ids != expected_ids:
        raise ValueError(f"task ids must be contiguous from 0, got {actual_ids}")
    for task in run["tasks"]:
        miss = REQUIRED_TASK_FIELDS - task.keys()
        if miss:
            raise ValueError(f"task {task.get('task_id')} missing fields: {sorted(miss)}")


def write_raw_run(run: dict[str, Any], raw_dir: str | Path) -> Path:
    validate_run(run)
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    run.setdefault("written_at_utc", datetime.now(timezone.utc).isoformat())
    path = raw / f"{run['run_id']}.json"
    if path.exists():
        raise FileExistsError(f"raw result is immutable and already exists: {path}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_runs(raw_dir: str | Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in sorted(Path(raw_dir).glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        validate_run(run)
        run["_source"] = str(path.resolve())
        runs.append(run)
    return runs

