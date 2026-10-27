"""Readable task records used by the MLCC site runner.

Task records are ordinary JSON.  They intentionally keep raw command output
and do not compute hashes, deduplicate content, or infer scientific status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    """A mutable JSON-backed task record.

    ``data`` follows the task contract in ``docs/harness-design.md``.  The
    runner adds execution evidence under explicit fields and an ``events``
    list; unknown fields are retained so a scientific task can carry its own
    method metadata.
    """

    data: dict[str, Any]
    path: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.path is not None:
            self.path = Path(self.path)

    @property
    def task_id(self) -> str:
        value = self.data["task_id"]
        if not isinstance(value, str) or not value:
            raise ValueError("task_id must be a non-empty string")
        return value

    @property
    def scheduler_job_id(self) -> str | None:
        value = self.data.get("scheduler_job_id")
        if value in (None, ""):
            return None
        return str(value)

    @property
    def command(self) -> list[str]:
        value = self.data["command"]
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item for item in value
        ):
            raise ValueError("command must be a non-empty list of strings")
        return value

    def set(self, **values: Any) -> None:
        self.data.update(values)

    def record_event(self, action: str, **values: Any) -> dict[str, Any]:
        event = {"action": action, "recorded_at": utc_now()}
        event.update(values)
        self.data.setdefault("events", []).append(event)
        return event


def load_task(path: str | Path) -> TaskRecord:
    """Load one JSON task file without changing it."""

    task_path = Path(path)
    with task_path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("task JSON must contain an object")
    task = TaskRecord(dict(value), task_path)
    task.task_id
    return task


def save_task(task: TaskRecord, path: str | Path | None = None) -> Path:
    """Write a task record as readable JSON and return its path."""

    target = Path(path) if path is not None else task.path
    if target is None:
        raise ValueError("task path is required")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(task.data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    task.path = target
    return target


def task_from_mapping(value: Mapping[str, Any], path: str | Path | None = None) -> TaskRecord:
    """Construct a task for callers that already parsed a mapping."""

    task = TaskRecord(dict(value), Path(path) if path is not None else None)
    task.task_id
    return task

