"""Read one explicit tangential-displacement task into a saved response product."""

from pathlib import Path
from typing import Any

from .tasks import load_task
from .lammps_tasks import read_lammps_task
from .interface_tangential import tangential_response_from_points
from .lammps_interface_normal import validate_tangential_protocol


def read_interface_tangential_task(task_path: str | Path) -> dict[str, Any]:
    task_file = Path(task_path).resolve()
    task = load_task(task_file).data
    if task["engine"] != "lammps" or task["protocol"]["kind"] != "interface_tangential":
        raise ValueError("interface-tangential requires an explicit LAMMPS interface_tangential task")
    validate_tangential_protocol(task["protocol"])
    result = {
        "schema": "mlcc.interface-tangential-product.v1",
        "study_id": task["study_id"], "case_id": task["case_id"],
        "case_role": task["case_role"], "fixture": task["fixture"],
        "model_id": task["model_id"], "model_version": task["model_version"],
        "model_path": task["model_path"], "task_id": task["task_id"],
        "task_path": str(task_file), "protocol": task["protocol"],
        "interface_sources": task["interface_sources"],
        "source_task": {key: task.get(key) for key in (
            "scheduler_job_id", "scheduler_state", "exit_code", "status", "scientific_status",
        )},
        "status": "unresolved", "relaxation_status": "unresolved",
        "tangential_response": None, "native_result": None,
        "missing_evidence": ["completed_native_interface_tangential_response"],
        "production_qualified": False,
    }
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        return result
    native = read_lammps_task(task_file)
    response = tangential_response_from_points(task["protocol"], native["atom_ids"], native["points"])
    result.update(status="available", tangential_response=response, native_result=native,
                  relaxation_status=response["relaxation_status"], missing_evidence=[])
    return result


__all__ = ["read_interface_tangential_task"]
