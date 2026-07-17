import pytest

from cil_restart.schema import validate_run


def test_schema_rejects_noncontiguous_tasks():
    run = {
        "schema_version": "1.0", "run_id": "x", "method": "D0", "seed": 1,
        "scenario": "diagnostic", "status": "complete", "protocol": {},
        "tasks": [{"task_id": 1, "learned_classes": 12, "overall_accuracy": 1, "old_accuracy": 1, "new_accuracy": 1}],
    }
    with pytest.raises(ValueError, match="contiguous"):
        validate_run(run)

