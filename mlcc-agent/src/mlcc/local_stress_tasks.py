"""Consume explicit local virial output from one saved LAMMPS task."""

import json
from pathlib import Path
from typing import Any

from .tasks import load_task
from .modeling import read_model_artifacts
from .lammps_tasks import read_lammps_task
from .lammps_local_stress import (
    local_stress_component_order,
    local_stress_enabled,
    validate_local_stress_model,
    read_local_stress_outputs,
)
from .local_stress import local_stress_from_frames
from .interface_sources import read_interface_task_sources


def read_local_stress_task(task_path: str | Path, request_path: str | Path) -> dict[str, Any]:
    task_file, request_file = Path(task_path).resolve(), Path(request_path).resolve()
    task = load_task(task_file).data
    request = json.loads(request_file.read_text(encoding="utf-8"))
    protocol = task["protocol"]
    if task["engine"] != "lammps" or not local_stress_enabled(protocol):
        raise ValueError("local-stress requires an explicit supported LAMMPS local_stress task")
    model = read_model_artifacts(task["model_path"])
    validate_local_stress_model(model, protocol)
    component_order = local_stress_component_order(protocol)
    interface_sources = (
        task["interface_sources"] if protocol.get("purpose") == "interface_local_stress"
        else task.get("interface_sources")
    )
    provenance = None
    if interface_sources is not None:
        provenance = read_interface_task_sources(
            task_file.parent, interface_sources, study_id=task["study_id"],
            model_id=model.model_id, model_version=model.version, atom_ids=model.atom_ids,
        )
    native = None
    samples = None
    frames = None
    missing = []
    failure_evidence = {}
    if task.get("scheduler_state") == "COMPLETED" and task.get("exit_code") == "0:0":
        native = read_lammps_task(task_file)
        atom_map = json.loads((task_file.parent / "atom-map.json").read_text(encoding="utf-8"))
        samples = read_local_stress_outputs(task_file.parent, protocol, atom_map)
        frames = samples["frames"]
        missing.extend(samples["missing_evidence"])
    else:
        missing.append("completed_native_local_stress_task")
        for filename in ("log.lammps", "stdout.log", "stderr.log"):
            path = task_file.parent / filename
            if path.is_file():
                failure_evidence[filename] = {"path": str(path), "text": path.read_text(encoding="utf-8")}
    response = local_stress_from_frames(
        request, frames, model.atoms.cell.array.tolist(), component_order=component_order,
    )
    missing.extend(response["missing_evidence"])
    return {
        "schema": "mlcc.local-stress-product.v1",
        "study_id": task["study_id"], "case_id": task["case_id"],
        "case_role": task["case_role"], "fixture": task["fixture"],
        "model_id": task["model_id"], "model_version": task["model_version"],
        "model_path": task["model_path"], "task_id": task["task_id"],
        "task_path": str(task_file), "request_path": str(request_file),
        "analysis_request": request, "protocol": protocol,
        "interface_sources": interface_sources, "interface_provenance": provenance,
        "parent_model": task.get("parent_model"), "method_set": task.get("method_set"),
        "potential": task.get("potential"),
        "source_task": {key: task.get(key) for key in (
            "scheduler_job_id", "scheduler_state", "exit_code", "native_exit_code", "status", "scientific_status",
        )},
        "status": response["status"], "local_stress": response,
        "native_result": native, "native_local_stress": samples,
        "failure_evidence": failure_evidence,
        "missing_evidence": list(dict.fromkeys(missing)),
        "production_qualified": False,
    }


__all__ = ["read_local_stress_task"]
