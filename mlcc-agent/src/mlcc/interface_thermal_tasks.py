"""Consume one explicitly declared interface thermal task and analysis window."""

import json
from pathlib import Path
from typing import Any

from .tasks import load_task
from .modeling import read_model_artifacts
from .lammps_tasks import read_lammps_task
from .lammps_interface_thermal import validate_thermal_model, read_thermal_outputs
from .interface_thermal import thermal_response_from_samples


def read_interface_thermal_task(task_path: str | Path, request_path: str | Path) -> dict[str, Any]:
    task_file, request_file = Path(task_path).resolve(), Path(request_path).resolve()
    task = load_task(task_file).data
    request = json.loads(request_file.read_text(encoding="utf-8"))
    protocol = task["protocol"]
    if task["engine"] != "lammps" or protocol.get("purpose") != "interface_thermal_response":
        raise ValueError("interface-thermal requires an explicit LAMMPS interface thermal task")
    validate_thermal_model(read_model_artifacts(task["model_path"]), protocol)
    for key in ("area_angstrom2", "normal_cartesian", "interface_count"):
        if request[key] != protocol["thermal"][key]:
            raise ValueError(f"thermal analysis {key} differs from task geometry")
    native = None
    samples = None
    energy_rows = None
    profile_frames = None
    missing = []
    if task.get("scheduler_state") == "COMPLETED" and task.get("exit_code") == "0:0":
        native = read_lammps_task(task_file)
        atom_map = json.loads((task_file.parent / "atom-map.json").read_text(encoding="utf-8"))
        samples = read_thermal_outputs(task_file.parent, protocol, atom_map)
        energy_rows = samples["energy_rows"]
        profile_frames = samples["profile_frames"]
        missing.extend(samples["missing_evidence"])
    else:
        missing.append("completed_native_interface_thermal_task")
    response = thermal_response_from_samples(request, energy_rows, profile_frames)
    missing.extend(response["missing_evidence"])
    return {
        "schema": "mlcc.interface-thermal-product.v1",
        "study_id": task["study_id"], "case_id": task["case_id"],
        "case_role": task["case_role"], "fixture": task["fixture"],
        "model_id": task["model_id"], "model_version": task["model_version"],
        "model_path": task["model_path"], "task_id": task["task_id"],
        "task_path": str(task_file), "request_path": str(request_file),
        "analysis_request": request, "protocol": protocol,
        "interface_sources": task["interface_sources"],
        "source_task": {key: task.get(key) for key in (
            "scheduler_job_id", "scheduler_state", "exit_code", "status", "scientific_status",
        )},
        "status": response["status"], "thermal_response": response,
        "native_result": native, "native_thermal": samples,
        "missing_evidence": list(dict.fromkeys(missing)),
        "production_qualified": False,
    }


__all__ = ["read_interface_thermal_task"]
