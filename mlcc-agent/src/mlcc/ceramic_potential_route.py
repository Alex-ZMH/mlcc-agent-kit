"""Explicit user entry for the selected ceramic self-trained potential.

This module only selects the already implemented ABACUS -> DeePMD -> LAMMPS
route and delegates task construction to the existing ceramic adapters.  It
does not discover a potential, fan out systems, submit a job, or qualify a
model.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .tasks import TaskRecord, save_task


_POTENTIAL_ROUTE = "abacus_deepmd"
_OPERATIONS = {"create_training", "create_lammps"}


def _read_request(request_path: Path) -> dict[str, Any]:
    value = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("ceramic potential request must be a JSON object")
    return dict(value)


def _select_operation(request: Mapping[str, Any]) -> str:
    if request.get("potential_route") != _POTENTIAL_ROUTE:
        raise ValueError("potential_route must explicitly be 'abacus_deepmd'")
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        raise ValueError("operation must explicitly be 'create_training' or 'create_lammps'")
    return operation


def _create_training(request: Mapping[str, Any]) -> TaskRecord:
    from .ceramic_training import create_ceramic_training_task
    from mlcc_deepmd.training import DeepMDTrainingConfig

    workspace = Path(request["workspace"])
    task_id = request["task_id"]
    config = DeepMDTrainingConfig.from_input_json(
        request["input_file"],
        workdir=workspace / "tasks" / task_id,
        **request["training_config"],
    )
    return create_ceramic_training_task(
        workspace,
        task_id,
        config,
        request["input_file"],
        request["collection"],
        request["interface_acceptance"],
        account=request["account"],
    )


def _create_lammps(request: Mapping[str, Any]) -> TaskRecord:
    from .ceramic_md import create_ceramic_lammps_task

    return create_ceramic_lammps_task(
        request["workspace"],
        request["task_id"],
        request["collection"],
        request["system_id"],
        request["model_card"],
        request["protocol"],
        request["site"],
        request["resource_request"],
    )


def create_selected_ceramic_task(request_path: str | Path) -> TaskRecord:
    """Create one task through the explicitly selected ceramic potential route."""

    request_file = Path(request_path).expanduser().resolve()
    request = _read_request(request_file)
    operation = _select_operation(request)
    task = _create_training(request) if operation == "create_training" else _create_lammps(request)
    potential_route = {
        "selected": _POTENTIAL_ROUTE,
        "selection": "explicit",
        "operation": operation,
        "request_file": str(request_file),
    }
    # The existing creator owns execution and scientific states.
    task.set(potential_route=potential_route)
    task.record_event(
        "select_ceramic_potential_route",
        potential_route=dict(potential_route),
        selected=_POTENTIAL_ROUTE,
        operation=operation,
        request_file=str(request_file),
    )
    save_task(task)
    return task


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mlcc.ceramic_potential_route")
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args(argv)
    task = create_selected_ceramic_task(args.request)
    print(json.dumps(task.data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["create_selected_ceramic_task", "main"]
