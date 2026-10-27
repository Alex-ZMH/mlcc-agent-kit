"""Read one explicit normal-displacement task into a saved response product."""

from pathlib import Path
from typing import Any

from .tasks import load_task
from .lammps_tasks import read_lammps_task
from .interface_normal import normal_response_from_points
from .lammps_interface_normal import validate_normal_protocol


def read_interface_normal_task(task_path: str | Path) -> dict[str, Any]:
    task_file = Path(task_path).resolve()
    task = load_task(task_file).data
    if task["engine"] != "lammps" or task["protocol"]["kind"] != "interface_normal":
        raise ValueError("interface-normal requires an explicit LAMMPS interface_normal task")
    validate_normal_protocol(task["protocol"])
    relaxed = task["protocol"]["normal_response"]["kinematics"] == (
        "fixed_cell_clamped_internal_relaxation"
    )
    result = {
        "schema": "mlcc.interface-normal-product.v1",
        "study_id": task["study_id"], "case_id": task["case_id"],
        "case_role": task["case_role"], "fixture": task["fixture"],
        "model_id": task["model_id"], "model_version": task["model_version"],
        "model_path": task["model_path"], "task_id": task["task_id"],
        "task_path": str(task_file), "protocol": task["protocol"],
        "interface_sources": task["interface_sources"],
        "source_task": {key: task.get(key) for key in (
            "scheduler_job_id", "scheduler_state", "exit_code", "status", "scientific_status",
        )},
        "status": "unresolved", "normal_response": None, "native_result": None,
        "missing_evidence": ["completed_native_interface_normal_response"],
        "production_qualified": False,
    }
    if relaxed:
        result["relaxation_status"] = "unresolved"
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        return result
    native = read_lammps_task(task_file)
    response = normal_response_from_points(task["protocol"], native["atom_ids"], native["points"])
    result.update(status="available", normal_response=response, native_result=native,
                  missing_evidence=[])
    if relaxed:
        result["relaxation_status"] = response["relaxation_status"]
    return result


__all__ = ["read_interface_normal_task"]
