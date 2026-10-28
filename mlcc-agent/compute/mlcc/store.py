"""Atomic local records. Reads neither load modules nor invoke adapters."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import uuid

from .contracts import FrameworkError, confined, dumps, read_json


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(dumps(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Store:
    def __init__(self, project):
        self.project = Path(project).resolve()

    def task_dir(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r'task-[a-f0-9]{32}', task_id):
            raise FrameworkError('INVALID_TASK_ID', 'Expected a saved task handle')
        return confined(self.project, f'outputs/tasks/{task_id}', must_exist=False)

    def create(self, record):
        path = self.task_dir(record['result']['task_id'])
        path.mkdir(parents=True, exist_ok=False)
        self.save(record)

    def save(self, record):
        path = confined(self.task_dir(record['result']['task_id']), 'record.json', must_exist=False)
        atomic_json(path, record)

    def read(self, task_id):
        return read_json(confined(self.task_dir(task_id), 'record.json'))

    def claim(self, task_id):
        path = confined(self.task_dir(task_id), 'worker.lock', must_exist=False)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, str(os.getpid()).encode('ascii'))
            os.close(fd)
        except FileExistsError as exc:
            raise FrameworkError('TASK_BUSY', 'Task is claimed. Query the record; do not resubmit or remove the lock without reconciliation.') from exc
        return path


def transition(result, status):
    stamp = now()
    result['execution']['status'] = status
    result['execution']['updated_at'] = stamp
    result['execution']['events'].append({'status': status, 'at': stamp})
