from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from mlcc.tasks import TaskRecord, load_task
from mlcc.workflow import require_result_dependencies


_ACCEPTED_STATUSES = {"converged", "converged_engineering_fixture"}


def _source50() -> tuple[Path, Path, str, object]:
    value = os.environ.get("MLCC_BERRY_REFERENCE_TASK")
    if not value:
        pytest.skip("MLCC_BERRY_REFERENCE_TASK must point to the read-only source50 task")
    task_path = Path(value).expanduser()
    if task_path.is_dir():
        task_path = task_path / "task.json"
    task_path = task_path.resolve()
    if not task_path.is_file():
        pytest.skip(f"source50 task.json is unavailable: {task_path}")
    task = load_task(task_path)
    result_value = task.data.get("result_file", "result.json")
    result_path = Path(result_value)
    if not result_path.is_absolute():
        result_path = task_path.parent / result_path
    result_path = result_path.resolve()
    if not result_path.is_file():
        pytest.skip(f"source50 result.json is unavailable: {result_path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    scientific_status = result.get("scientific_status")
    if scientific_status not in _ACCEPTED_STATUSES:
        pytest.skip(f"source50 result is not an accepted converged dependency: {scientific_status!r}")
    return task_path, result_path, scientific_status, task


def _consumer(requirement: dict) -> TaskRecord:
    return TaskRecord({"task_id": "external-dependency-consumer", "required_results": [requirement]})


def test_external_task_file_accepts_read_only_source50_lineage(tmp_path: Path):
    task_path, result_path, scientific_status, source_task = _source50()

    provenance = require_result_dependencies(
        _consumer(
            {
                "task_id": source_task.task_id,
                "task_file": str(task_path),
                "result_file": str(result_path),
                "scientific_status": scientific_status,
            }
        ),
        tmp_path,
    )

    assert provenance[0]["task_id"] == source_task.task_id
    assert provenance[0]["task_file"] == str(task_path)
    assert provenance[0]["result_file"] == str(result_path)


def test_external_task_file_rejects_wrong_declared_task_id(tmp_path: Path):
    task_path, result_path, scientific_status, source_task = _source50()

    with pytest.raises(ValueError, match="declared task_id"):
        require_result_dependencies(
            _consumer(
                {
                    "task_id": f"{source_task.task_id}-wrong",
                    "task_file": str(task_path),
                    "result_file": str(result_path),
                    "scientific_status": scientific_status,
                }
            ),
            tmp_path,
        )


def test_default_workspace_task_file_accepts_real_source50_minimal_copy(tmp_path: Path):
    task_path, result_path, scientific_status, source_task = _source50()
    copied_task_path = tmp_path / "tasks" / source_task.task_id / "task.json"
    copied_task_path.parent.mkdir(parents=True)
    shutil.copy2(task_path, copied_task_path)

    provenance = require_result_dependencies(
        _consumer(
            {
                "task_id": source_task.task_id,
                "result_file": str(result_path),
                "scientific_status": scientific_status,
            }
        ),
        tmp_path,
    )

    assert provenance[0]["task_file"] == str(copied_task_path)
    assert provenance[0]["result_file"] == str(result_path)
