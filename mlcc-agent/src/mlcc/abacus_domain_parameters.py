"""Consume saved ABACUS SCF products as one domain-parameter product.

This is a saved-product adapter only. It does not reopen native logs, infer
convergence, or recompute any electronic quantity.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .domain_parameters import domain_parameter_product


REQUEST_SCHEMA = "mlcc.abacus-domain-parameters-request.v1"
ELECTRONIC_SCHEMA = "mlcc.abacus-electronic.v001"
DOMAIN_KIND = "abacus_domain_parameters"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON record must contain an object: {path}")
    return value


def _path(value: Any, request_file: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path")
    path = Path(value).expanduser()
    return (request_file.parent / path).resolve() if not path.is_absolute() else path.resolve()


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _same(label: str, left: Any, right: Any) -> None:
    if left != right:
        raise ValueError(f"{label} differs: {left!r} != {right!r}")


def _forces(value: Any, count: int) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError("result.forces_eV_per_A must be an N x 3 list matching atom_ids")
    rows: list[list[float]] = []
    for index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError(f"result.forces_eV_per_A[{index}] must contain three components")
        rows.append([_number(component, f"result.forces_eV_per_A[{index}]") for component in row])
    return rows


def _stress(value: Any) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("result.stress_GPa must be a 3 x 3 matrix")
    rows: list[list[float]] = []
    for index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError(f"result.stress_GPa[{index}] must contain three components")
        rows.append([_number(component, f"result.stress_GPa[{index}]") for component in row])
    return rows


def _refs(*records: Mapping[str, Any] | None, paths: list[Path]) -> list[str]:
    values = [str(path) for path in paths]
    for record in records:
        files = record.get("source_files") if isinstance(record, Mapping) else None
        if isinstance(files, Mapping):
            values.extend(str(value) for value in files.values() if isinstance(value, str) and value)
    return list(dict.fromkeys(values))


def _property(
    name: str,
    value: Any,
    unit: str,
    shape: list[int],
    definition: str,
    conditions: Mapping[str, Any],
    coordinates: Any,
    refs: list[str],
    atom_map: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    condition = copy.deepcopy(dict(conditions))
    if reason is not None:
        condition["unresolved_reason"] = reason
    return {
        "name": name,
        "value": copy.deepcopy(value),
        "unit": unit,
        "shape": list(shape),
        "definition": definition,
        "conditions": condition,
        "coordinates": copy.deepcopy(coordinates),
        "atom_mapping_ref": atom_map,
        "source_refs": list(refs),
        "status": "unresolved" if reason is not None else "available",
    }


def build_abacus_domain_parameters(request_path: str | Path) -> dict[str, Any]:
    """Build five domain properties from explicit saved JSON products."""

    request_file = Path(request_path).expanduser().resolve()
    request = _read(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    if "electronic_path" not in request:
        raise ValueError("request requires explicit electronic_path, including null")

    model_path = _path(request.get("model_path"), request_file, "model_path")
    study_path = _path(request.get("study_path"), request_file, "study_path")
    task_path = _path(request.get("task_path"), request_file, "task_path")
    result_path = _path(request.get("result_path"), request_file, "result_path")
    if task_path.name != "task.json":
        raise ValueError("task_path must point to an explicit task.json")
    model = _read(model_path / "model.json")
    study = _read(study_path)
    task = _read(task_path)
    result = _read(result_path)

    study_model = study.get("model")
    if not isinstance(study_model, Mapping):
        raise ValueError("Study model must be an object")
    for field in ("study_id", "case_id"):
        if not isinstance(study.get(field), str) or not study[field].strip():
            raise ValueError(f"Study requires {field}")
    identity = (study_model.get("model_id"), study_model.get("version"))
    if not all(isinstance(item, str) and item.strip() for item in identity):
        raise ValueError("Study model requires model_id and version")
    _same("model.json identity and Study model", (model.get("model_id"), model.get("version")), identity)
    _same("task model identity and Study model", (task.get("model_id"), task.get("model_version")), identity)
    _same("result model identity and task", (result.get("model_id"), result.get("version")), identity)
    _same("task Study identity and request Study", (task.get("study_id"), task.get("case_id")), (study["study_id"], study["case_id"]))
    _same("result task_id and task", result.get("task_id"), task.get("task_id"))
    _same("result scheduler_job_id and task", result.get("scheduler_job_id"), task.get("scheduler_job_id"))
    _same("result method_set and task", result.get("method_set"), task.get("method_set"))
    if "study_id" in result or "case_id" in result:
        _same("result Study identity and task", (result.get("study_id"), result.get("case_id")), (task.get("study_id"), task.get("case_id")))

    atom_ids = result.get("atom_ids")
    if not isinstance(atom_ids, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in atom_ids):
        raise ValueError("result.atom_ids must preserve integer source atom order")
    if isinstance(model.get("atom_ids"), list):
        _same("result.atom_ids and model atom order", atom_ids, model["atom_ids"])
    forces = _forces(result.get("forces_eV_per_A"), len(atom_ids))
    stress = _stress(result.get("stress_GPa"))
    if result.get("stress_unit") != "GPa" or result.get("stress_sign") != "abacus_printed":
        raise ValueError("result stress must retain ABACUS printed GPa convention")
    energy = _number(result.get("energy_eV"), "result.energy_eV")

    electronic_path: Path | None = None
    electronic: dict[str, Any] | None = None
    if request["electronic_path"] is not None:
        electronic_path = _path(request["electronic_path"], request_file, "electronic_path")
        electronic = _read(electronic_path)
        if electronic.get("schema") != ELECTRONIC_SCHEMA:
            raise ValueError(f"electronic product schema must be {ELECTRONIC_SCHEMA}")
        _same("electronic task_id and task", electronic.get("task_id"), task.get("task_id"))
        _same("electronic scheduler_job_id and task", electronic.get("scheduler_job_id"), task.get("scheduler_job_id"))
        _same("electronic method_set and task", electronic.get("method_set"), task.get("method_set"))
        _same("electronic model identity and task", (electronic.get("model_id"), electronic.get("model_version")), identity)

    refs = _refs(model, study, task, result, electronic, paths=[request_file, model_path, model_path / "model.json", study_path, task_path, result_path] + ([electronic_path] if electronic_path else []))
    atom_map = None
    files = result.get("source_files")
    if isinstance(files, Mapping):
        for key in ("STRU.atom-map.json", "atom-map.json", "atom_lineage.json"):
            if isinstance(files.get(key), str) and files[key]:
                atom_map = files[key]
                break

    method = {key: copy.deepcopy(task.get(key)) for key in ("engine", "engine_version", "basis_type", "calculation", "method_set", "calculation_conditions", "net_charge", "nelec", "nelec_delta")}
    native = {"task_id": task.get("task_id"), "scheduler_job_id": task.get("scheduler_job_id"), "scheduler_state": task.get("scheduler_state"), "exit_code": task.get("exit_code"), "task_status": task.get("status"), "scientific_status": result.get("scientific_status"), "electronic_converged": result.get("electronic_converged"), "ionic_converged": result.get("ionic_converged"), "native_completed": result.get("native_completed"), "scf_iterations": result.get("scf_iterations"), "method_conditions": method}
    common = {"native": native, "method": method, "source_order_atom_ids": list(atom_ids), "production_qualification": result.get("production_qualification"), "scientific_qualification": result.get("scientific_qualification")}
    properties = [
        _property("total_energy", energy, "eV", [], result.get("energy_definition") or "ABACUS native total energy", common, "not_applicable_to_scalar", refs, atom_map),
        _property("source_order_forces", forces, "eV/angstrom", [len(atom_ids), 3], "ABACUS native forces in saved source atom order", common, {"basis": "source_atom_order", "atom_ids": list(atom_ids)}, refs, atom_map),
        _property("native_stress", stress, "GPa", [3, 3], "ABACUS native printed stress; no sign conversion", {**common, "stress_sign": "abacus_printed", "stress_basis": "source_cartesian"}, {"basis": "source_cartesian"}, refs, atom_map),
    ]

    if electronic is None:
        electron, gap, electron_reason, gap_reason = None, None, "electronic_path_not_provided", "electronic_path_not_provided"
        econditions: dict[str, Any] = {"status": "missing_saved_electronic_product"}
    else:
        electron = electronic.get("electron_count_native")
        if electron is not None:
            electron = _number(electron, "electronic.electron_count_native")
        electron_reason = None if electron is not None else "native_electron_count_missing"
        gap = electronic.get("sampled_mesh_KS_gap_eV")
        if gap is not None:
            gap = _number(gap, "electronic.sampled_mesh_KS_gap_eV")
        gap_reason = None if gap is not None else str(electronic.get("gap_reason") or electronic.get("gap_status") or "sampled_mesh_gap_missing")
        econditions = {key: copy.deepcopy(electronic.get(key)) for key in ("schema", "task_id", "scheduler_job_id", "electronic_converged", "native_completed", "gap_status", "gap_reason", "gap_qualification")}
        econditions["source_electronic_product"] = str(electronic_path)
    properties.extend([
        _property("native_electron_count", electron, "electrons", [], "native ABACUS electron count saved by electronic parser", {**common, "electronic": econditions}, "not_applicable_to_scalar", refs, None, electron_reason),
        _property("sampled_mesh_KS_gap", gap, "eV", [], "sampled uniform-mesh Kohn-Sham gap; not fundamental or band-path", {**common, "electronic": econditions}, "not_applicable_to_scalar", refs, None, gap_reason),
    ])
    return domain_parameter_product(
        kind=DOMAIN_KIND,
        model={"model_id": identity[0], "version": identity[1], "path": str(model_path), "material": model.get("material"), "element_order": copy.deepcopy(model.get("element_order"))},
        study={"study_id": study["study_id"], "case_id": study["case_id"], "case_role": study.get("case_role"), "path": str(study_path)},
        properties=properties,
        execution={"analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"), "request_path": str(request_file), "task_path": str(task_path), "result_path": str(result_path), "electronic_path": None if electronic_path is None else str(electronic_path), "method_set": task.get("method_set"), "native_job": native, "scientific_status": result.get("scientific_status"), "production_qualification": result.get("production_qualification"), "source_refs": refs},
    )


__all__ = ["DOMAIN_KIND", "REQUEST_SCHEMA", "build_abacus_domain_parameters"]
