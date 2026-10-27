"""Direct fixed-cell, one-direction Berry polarization path algebra.

This module consumes already parsed native Berry result records.  It never
parses an ABACUS log, runs a solver, chooses a polarization branch, or grants
scientific qualification.  The path request is the only place where an
integer branch and its supporting declaration may be supplied.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .berry import _validate_model_and_stru
from .modeling import read_model_artifacts


_SCHEMA = "mlcc.polarization-path-request.v1"
_OUTPUT_SCHEMA = "mlcc.polarization-path.v1"
_RESULT_SCHEMA = "mlcc.abacus-polarization.v1"
_ABACUS_VERSION = "3.10.1"
_CELL_TOL = 1.0e-8
_FRAC_TOL = 5.0e-8
_METHOD_KEYS = (
    "engine",
    "abacus_version_target",
    "basis_type",
    "dft_functional",
    "nspin",
    "lspinorb",
    "noncolin",
    "occupations",
    "element_order",
    "parameters",
    "initial_moments_muB_by_element",
    "pseudopotential_ids",
    "pseudopotential_metadata",
    "pseudopotential_treatment",
    "net_charge",
    "kpoints",
)
_REQUIRED_SOURCE_KEYS = (
    "INPUT",
    "native_INPUT",
    "KPT",
    "STRU",
    "STRU.atom-map.json",
    "method.json",
    "running_nscf.log",
)


def _json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"polarization {label} must contain a JSON object")
    return value


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _number(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _integer_or_none(value: Any, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer or null")
    return int(value)


def _absolute_path(value: Any, *, name: str) -> Path:
    text = _text(value, name=name)
    path = Path(text)
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path


def _periodic_close(first: Sequence[float], second: Sequence[float], *, atol: float = _FRAC_TOL) -> bool:
    delta = np.asarray(first, dtype=float) - np.asarray(second, dtype=float)
    delta -= np.rint(delta)
    return bool(np.all(np.abs(delta) <= atol))


def _case_identity(task: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(task["fixture"], bool):
        raise ValueError("Berry case fixture must be an explicit boolean")
    return {
        "case_id": _text(task["case_id"], name="case_id"),
        "case_role": _text(task["case_role"], name="case_role"),
        "fixture": task["fixture"],
    }


def _source_files(result: Mapping[str, Any], directory: Path, suffix: str) -> dict[str, str]:
    raw = result.get("source_files")
    if not isinstance(raw, Mapping):
        raise ValueError("Berry result source_files must be an object")
    sources = {str(key): _text(value, name=f"result.source_files[{key!r}]") for key, value in raw.items()}
    for key in _REQUIRED_SOURCE_KEYS:
        if key not in sources:
            raise ValueError(f"Berry result source_files is missing {key!r}")
        if not Path(sources[key]).is_file():
            raise ValueError(f"Berry result source file is missing: {sources[key]}")
    expected = {
        "INPUT": directory / "INPUT",
        "KPT": directory / "KPT",
        "STRU": directory / "STRU",
        "STRU.atom-map.json": directory / "STRU.atom-map.json",
        "method.json": directory / "method.json",
        "native_INPUT": directory / f"OUT.{suffix}" / "INPUT",
        "running_nscf.log": directory / f"OUT.{suffix}" / "running_nscf.log",
    }
    for key, path in expected.items():
        if Path(sources[key]).resolve() != path.resolve():
            raise ValueError(f"Berry result source_files[{key!r}] does not point to the task file")
    return sources


def _method_signature(method: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    signature: dict[str, Any] = {}
    for key in _METHOD_KEYS:
        if key not in method:
            raise ValueError(f"Berry method is missing common physical key {key!r}")
        signature[key] = method[key]
    if "method_set" not in method:
        raise ValueError("Berry method is missing method_set")
    signature["method_set"] = method["method_set"]
    if "pw_diag_thr" not in result or "kpoint_shift" not in result:
        raise ValueError("Berry result must declare pw_diag_thr and kpoint_shift")
    signature["pw_diag_thr"] = _number(result["pw_diag_thr"], name="result.pw_diag_thr")
    shift = result["kpoint_shift"]
    if isinstance(shift, (str, bytes)) or not isinstance(shift, Sequence) or len(shift) != 3:
        raise ValueError("result.kpoint_shift must contain three values")
    signature["kpoint_shift"] = [_number(item, name="result.kpoint_shift item") for item in shift]
    return signature


def _model_geometry(model: Any) -> tuple[list[int], dict[str, str], dict[str, int], dict[str, list[float]], list[list[float]]]:
    atoms = model.atoms
    if "atom_id" not in atoms.arrays:
        raise ValueError("Berry model requires atom_id values")
    records = []
    frac = atoms.get_scaled_positions(wrap=False)
    symbols = atoms.get_chemical_symbols()
    for index, atom_id in enumerate(atoms.arrays["atom_id"]):
        records.append((int(atom_id), str(symbols[index]), [float(value) for value in frac[index]]))
    records.sort(key=lambda item: item[0])
    ids = [item[0] for item in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Berry model atom_id values must be unique")
    mapping = {str(item[0]): item[1] for item in records}
    composition: dict[str, int] = {}
    positions: dict[str, list[float]] = {}
    for atom_id, element, coordinates in records:
        composition[element] = composition.get(element, 0) + 1
        positions[str(atom_id)] = coordinates
    cell = [[float(value) for value in row] for row in np.asarray(atoms.cell.array, dtype=float)]
    return ids, mapping, composition, positions, cell


def _parent_identity_records(metadata: Mapping[str, Any]) -> list[tuple[str, str]]:
    raw = metadata.get("parent_models", [])
    if not isinstance(raw, list):
        raise ValueError("Berry model parent_models must be a list")
    identities: list[tuple[str, str]] = []
    for index, record in enumerate(raw):
        if not isinstance(record, Mapping):
            raise ValueError(f"Berry model parent_models[{index}] must be an object")
        model_id = _text(record.get("model_id"), name=f"parent_models[{index}].model_id")
        version = _text(record.get("version"), name=f"parent_models[{index}].version")
        identities.append((model_id, version))
    return identities


def _branch_algebra(
    representative_values: Sequence[Any],
    quantum_values: Sequence[Any],
    branch_integers: Sequence[Any],
    branch_bases: Sequence[Any],
) -> tuple[list[float] | None, float | None]:
    """Apply only caller-declared ``P + nQ`` values.

    A missing integer or supporting declaration leaves both results unresolved;
    no branch is inferred from neighboring values.
    """

    if not (len(representative_values) == len(quantum_values) == len(branch_integers) == len(branch_bases)):
        raise ValueError("branch algebra inputs must have equal lengths")
    output: list[float] = []
    missing_branch = False
    for index, (value, quantum, branch, basis) in enumerate(
        zip(representative_values, quantum_values, branch_integers, branch_bases)
    ):
        p = _number(value, name=f"representative_P[{index}]")
        q = _number(quantum, name=f"quantum_Q[{index}]")
        if q <= 0:
            raise ValueError("polarization quantum must be positive")
        if not math.isclose(q, float(quantum_values[0]), rel_tol=0.0, abs_tol=1e-7):
            raise ValueError("fixed-cell path must share one polarization quantum")
        if branch is not None and (isinstance(branch, bool) or not isinstance(branch, int)):
            raise ValueError(f"branch_integer[{index}] must be an integer or null")
        if branch is None or basis is None or not isinstance(basis, str) or not basis.strip():
            missing_branch = True
            continue
        output.append(p + int(branch) * q)
    if missing_branch:
        return None, None
    if len(output) < 2:
        return output, None
    return output, output[-1] - output[0]


def _validate_reference(
    result: Mapping[str, Any],
    task: Mapping[str, Any],
    method: Mapping[str, Any],
    *,
    study_id: str,
    model_id: str,
    model_version: str,
) -> dict[str, Any]:
    if result.get("reference_scf_converged") is not True:
        raise ValueError("Berry result reference_scf_converged must be true")
    validation = result.get("reference_scf_validation")
    if not isinstance(validation, Mapping):
        raise ValueError("Berry result reference_scf_validation is required")
    reference_path = _absolute_path(validation.get("task_file"), name="reference_scf_validation.task_file")
    reference = _json(reference_path, "reference SCF task")
    reference_method_path = reference_path.parent / "method.json"
    reference_method = _json(reference_method_path, "reference SCF method")
    reference_result_path = _absolute_path(reference["result_file"], name="reference.result_file")
    reference_result = _json(reference_result_path, "reference SCF result")
    if reference.get("task_id") != validation.get("task_id") or reference.get("task_id") != result.get("reference_scf_task_id"):
        raise ValueError("Berry reference SCF task identity differs from saved result")
    if reference.get("study_id") != study_id:
        raise ValueError("Berry reference SCF study differs from the path study")
    if _case_identity(reference) != _case_identity(task):
        raise ValueError("Berry reference SCF case differs from the NSCF point")
    model_path = _absolute_path(task["model_path"], name="task.model_path").resolve()
    if _absolute_path(reference["model_path"], name="reference.model_path").resolve() != model_path:
        raise ValueError("Berry reference SCF model_path differs from the NSCF point")
    if _absolute_path(validation["model_path"], name="reference_scf_validation.model_path").resolve() != model_path:
        raise ValueError("Berry saved reference validation model_path differs from the NSCF point")
    if reference["runner"] != "slurm" or reference["calculation"] != "scf":
        raise ValueError("Berry reference must be a Slurm SCF task")
    if reference_result["task_id"] != reference["task_id"] or str(reference_result["scheduler_job_id"]) != str(reference["scheduler_job_id"]):
        raise ValueError("Berry reference result task/job identity differs")
    if reference_result["electronic_converged"] is not True:
        raise ValueError("Berry reference result is not electronically converged")
    if reference_result["method_set"] != reference["method_set"]:
        raise ValueError("Berry reference result method_set differs")
    if task["berry"]["source_reference_task_id"] != reference["task_id"] or Path(task["berry"]["source_reference_task_file"]).resolve() != reference_path.resolve():
        raise ValueError("Berry declared SCF reference differs from saved validation")
    if reference.get("model_id") != model_id or reference.get("model_version") != model_version:
        raise ValueError("Berry reference SCF model identity differs from the NSCF point")
    if reference.get("method_set") != method.get("method_set") or reference_method.get("method_set") != method.get("method_set"):
        raise ValueError("Berry reference SCF method_set differs from the NSCF point")
    if reference.get("scheduler_state") != "COMPLETED" or reference.get("exit_code") != "0:0":
        raise ValueError("Berry reference SCF requires COMPLETED/0:0 native evidence")
    if not reference.get("scheduler_job_id"):
        raise ValueError("Berry reference SCF scheduler_job_id is required")
    if reference_method.get("engine") != "abacus" or reference_method.get("abacus_version_target") != _ABACUS_VERSION:
        raise ValueError("Berry reference SCF method engine/version differs from ABACUS 3.10.1")
    reference_signature = {
        key: reference_method.get(key)
        for key in _METHOD_KEYS
    }
    point_signature = {
        key: method.get(key)
        for key in _METHOD_KEYS
    }
    if reference_signature != point_signature:
        raise ValueError("Berry reference SCF physical method differs from the NSCF point")
    return {
        "task_id": reference["task_id"],
        "task_file": str(reference_path),
        "result_file": str(reference_result_path),
        "scheduler_job_id": str(reference["scheduler_job_id"]),
        "scheduler_state": reference.get("scheduler_state"),
        "exit_code": reference.get("exit_code"),
        "model_id": reference.get("model_id"),
        "model_version": reference.get("model_version"),
        "model_path": str(model_path),
        **_case_identity(reference),
        "method_set": reference.get("method_set"),
        "study_id": reference.get("study_id"),
        "scientific_qualification": reference.get("scientific_qualification"),
        "production_qualification": reference.get("production_qualification"),
    }


def _point_record(
    point: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    task_path = _absolute_path(point.get("task_file"), name="point.task_file")
    result_path = _absolute_path(point.get("result_file"), name="point.result_file")
    task = _json(task_path, "task")
    result = _json(result_path, "result")
    case = _case_identity(task)
    if previous is not None and case != previous["case"]:
        raise ValueError("Berry path point case differs from the previous point")
    if result_path.resolve() != _absolute_path(task["result_file"], name="task.result_file").resolve():
        raise ValueError("point result_file differs from task.result_file")
    method_path = task_path.parent / "method.json"
    method = _json(method_path, "method")
    if result.get("schema") != _RESULT_SCHEMA:
        raise ValueError("Berry point result schema must be mlcc.abacus-polarization.v1")
    if result["branch_status"] != "not_unwrapped" or result["branch_unwrapped"] is not False:
        raise ValueError("Berry input must retain branch_status=not_unwrapped and branch_unwrapped=false")
    if task.get("task_id") != result.get("task_id"):
        raise ValueError("Berry task and result task_id differ")
    if task.get("scheduler_job_id") is None or str(task.get("scheduler_job_id")) != str(result.get("scheduler_job_id")):
        raise ValueError("Berry task and result scheduler_job_id differ")
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        raise ValueError("Berry point requires COMPLETED/0:0 native evidence")
    if task.get("runner") != "slurm":
        raise ValueError("Berry point must retain Slurm runner provenance")
    if task.get("stage") != "P5" or task.get("calculation") != "nscf":
        raise ValueError("Berry point must be a P5 NSCF task")
    if task.get("study_id") != request.get("study_id"):
        raise ValueError("Berry point study differs from the path study")
    if task.get("engine") != "abacus" or task.get("engine_version") != _ABACUS_VERSION:
        raise ValueError("Berry point must use ABACUS 3.10.1")
    if result["engine"] != task["engine"] or result["engine_version"] != task["engine_version"]:
        raise ValueError("Berry result engine/version differs from task")
    if task["berry"] != method["berry"]:
        raise ValueError("Berry task and method protocols differ")
    if result["kpoints"] != method["kpoints"] or result["pw_diag_thr"] != method["berry"]["pw_diag_thr"]:
        raise ValueError("Berry result mesh/diagonalization threshold differs from method")
    model_id = _text(task.get("model_id"), name="task.model_id")
    model_version = _text(task.get("model_version"), name="task.model_version")
    if result.get("model_id") != model_id or result.get("model_version") != model_version:
        raise ValueError("Berry result model identity differs from task")
    if method.get("model_id") != model_id or method.get("version") != model_version:
        raise ValueError("Berry method model identity differs from task")
    if result.get("method_set") != task.get("method_set") or method.get("method_set") != task.get("method_set"):
        raise ValueError("Berry method_set differs across task, method and result")
    if result.get("gdir") != request.get("gdir") or method.get("berry", {}).get("gdir") != request.get("gdir"):
        raise ValueError("Berry point gdir differs from the explicit path gdir")
    if result.get("stage") != "nscf" or result.get("native_completed") is not True or result.get("nscf_completed") is not True:
        raise ValueError("Berry result does not prove native NSCF completion")
    source_files = _source_files(result, task_path.parent, method["suffix"])
    model_path = _absolute_path(task.get("model_path"), name="task.model_path")
    model = read_model_artifacts(model_path)
    atom_map, native_atoms, _stru_path, _stru_contract = _validate_model_and_stru(task_path.parent, model, method)
    ids, atom_elements, composition, positions, cell = _model_geometry(model)
    direction = np.asarray(cell[int(request["gdir"]) - 1])
    if not np.allclose(result["direction_lattice_vector_angstrom"], direction, atol=_CELL_TOL, rtol=0.0):
        raise ValueError("Berry direction differs from the model lattice vector")
    if not np.allclose(result["direction_unit_vector_cartesian"], direction / np.linalg.norm(direction), atol=_CELL_TOL, rtol=0.0):
        raise ValueError("Berry direction unit vector differs from the model")
    reference = _validate_reference(
        result,
        task,
        method,
        study_id=str(request["study_id"]),
        model_id=model_id,
        model_version=model_version,
    )
    method_signature = _method_signature(method, result)
    representative = result.get("total_P_C_per_m2")
    quantum = result.get("modulo_quantum_C_per_m2")
    p = _number(representative, name="result.total_P_C_per_m2")
    q = _number(quantum, name="result.modulo_quantum_C_per_m2")
    if q <= 0:
        raise ValueError("polarization quantum must be positive")
    rows = result.get("polarization_rows")
    if not isinstance(rows, Mapping) or not isinstance(rows.get("c_per_m2"), Mapping):
        raise ValueError("Berry result polarization_rows.c_per_m2 is required")
    printed = rows["c_per_m2"]
    if printed["unit"] != "c_per_m2" or printed["native_unit"] != "C/m^2":
        raise ValueError("Berry polarization row must declare C/m^2 units")
    if not math.isclose(p, _number(printed.get("value"), name="polarization_rows.c_per_m2.value"), rel_tol=0.0, abs_tol=1e-7):
        raise ValueError("Berry result total_P_C_per_m2 differs from polarization_rows.c_per_m2.value")
    if not math.isclose(q, _number(printed.get("modulo"), name="polarization_rows.c_per_m2.modulo"), rel_tol=0.0, abs_tol=1e-7):
        raise ValueError("Berry result modulo quantum differs from polarization_rows.c_per_m2.modulo")
    check = result.get("quantum_check")
    if not isinstance(check, Mapping) or not math.isclose(q, _number(check.get("quantum_C_per_m2"), name="quantum_check.quantum_C_per_m2"), rel_tol=0.0, abs_tol=1e-7):
        raise ValueError("Berry result quantum_check differs from the printed C/m2 quantum")
    branch = _integer_or_none(point.get("branch_integer"), name="point.branch_integer")
    basis = point.get("branch_basis")
    if basis is not None and (not isinstance(basis, str) or not basis.strip()):
        raise ValueError("point.branch_basis must be non-empty text or null")
    if branch is None or basis is None:
        unresolved = "ambiguous_missing_branch_declaration"
    else:
        unresolved = None
    structural_change = None
    if previous is not None:
        if not np.allclose(np.asarray(cell), np.asarray(previous["geometry"]["cell_angstrom"]), atol=_CELL_TOL, rtol=0.0):
            raise ValueError("Berry path cell differs beyond fixed-cell tolerance")
        if ids != previous["geometry"]["atom_ids"] or atom_elements != previous["geometry"]["atom_id_to_element"] or composition != previous["geometry"]["composition"]:
            raise ValueError("Berry path atom mapping or composition differs")
        structural_change = any(
            not _periodic_close(positions[str(atom_id)], previous["geometry"]["fractional_positions_by_atom_id"][str(atom_id)])
            for atom_id in ids
        )
        previous_identity = (previous["model"]["model_id"], previous["model"]["version"])
        current_identity = (model_id, model_version)
        if current_identity != previous_identity:
            parents = _parent_identity_records(model.metadata)
            first_identity = (previous["path_first_model_id"], previous["path_first_model_version"])
            if previous_identity not in parents and first_identity not in parents:
                raise ValueError("Berry derived model must declare the previous or first model in parent_models")
    return {
        "point_id": _text(point.get("point_id"), name="point.point_id"),
        "path_coordinate": _number(point.get("path_coordinate"), name="point.path_coordinate"),
        "parent_point_id": point.get("parent_point_id"),
        "task_id": task["task_id"],
        "case": case,
        "source": {
            "task_file": str(task_path),
            "result_file": str(result_path),
            "method_file": str(method_path.resolve()),
            "source_files": source_files,
        },
        "native_job": {
            "task_id": task["task_id"],
            "scheduler_job_id": str(task["scheduler_job_id"]),
            "scheduler_state": task.get("scheduler_state"),
            "exit_code": task.get("exit_code"),
            "runner": task.get("runner"),
        },
        "scf_job": reference,
        "model": {
            "model_id": model_id,
            "version": model_version,
            "path": str(model_path),
            "parent_models": model.metadata.get("parent_models", []),
        },
        "geometry": {
            "fixed_cell": True,
            "cell_angstrom": cell,
            "atom_ids": ids,
            "atom_id_to_element": atom_elements,
            "composition": composition,
            "fractional_positions_by_atom_id": positions,
            "structural_change_from_previous": structural_change,
        },
        "mapping": {
            "status": "stable_atom_id_element_mapping",
            "source_atom_ids": [int(value) for value in atom_map.get("source_atom_ids", [])],
            "abacus_order": atom_map.get("abacus_order"),
            "native_element_order": native_atoms.get_chemical_symbols(),
        },
        "common_method": method_signature,
        "gdir": int(request["gdir"]),
        "unit": "C/m^2",
        "polarization": {
            "representative_P_C_per_m2": p,
            "quantum_Q_C_per_m2": q,
            "source_branch_status": result["branch_status"],
            "source_branch_unwrapped": result["branch_unwrapped"],
            "branch_integer": branch,
            "branch_basis": basis,
            "unwrapped_P_C_per_m2": None,
        },
        "qualification": {
            "native_completed": bool(result.get("native_completed")),
            "nscf_completed": bool(result.get("nscf_completed")),
            "reference_scf_converged": bool(result.get("reference_scf_converged")),
            "scientific_qualification": result.get("scientific_qualification"),
            "numerical_qualification": result.get("numerical_qualification"),
            "production_qualification": result.get("production_qualification"),
            "insulating_path_qualified": False,
            "branch_continuity_qualified": False,
        },
        "original_qualification_flags": {
            "production_label": result.get("production_label"),
            "task_production_label": task.get("production_label"),
            "scientific_qualification": result.get("scientific_qualification"),
            "numerical_qualification": result.get("numerical_qualification"),
            "production_qualification": result.get("production_qualification"),
        },
        "_method_signature": method_signature,
        "_representative": p,
        "_quantum": q,
        "_branch": branch,
        "_branch_basis": basis,
        "_branch_unresolved": unresolved,
        "path_first_model_id": model_id if previous is None else previous["path_first_model_id"],
        "path_first_model_version": model_version if previous is None else previous["path_first_model_version"],
    }


def analyze_polarization_path(request_path: str | Path) -> dict[str, Any]:
    """Consume a declared fixed-cell Berry path from saved native results."""

    request_file = Path(request_path)
    request = _json(request_file, "path request")
    if request.get("schema") != _SCHEMA:
        raise ValueError("polarization path request schema must be mlcc.polarization-path-request.v1")
    path_id = _text(request.get("path_id"), name="path_id")
    study_id = _text(request.get("study_id"), name="study_id")
    gdir = _integer_or_none(request.get("gdir"), name="gdir")
    if gdir not in (1, 2, 3):
        raise ValueError("gdir must be 1, 2 or 3")
    path_basis = _text(request.get("path_basis"), name="path_basis")
    raw_points = request.get("points")
    if isinstance(raw_points, (str, bytes)) or not isinstance(raw_points, list) or not raw_points:
        raise ValueError("polarization path points must be a non-empty list")
    points: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_tasks: set[str] = set()
    seen_jobs: set[str] = set()
    seen_results: set[str] = set()
    previous_point: dict[str, Any] | None = None
    unresolved_reasons: list[str] = []
    common_method: dict[str, Any] | None = None
    for index, raw_point in enumerate(raw_points):
        if not isinstance(raw_point, Mapping):
            raise ValueError(f"points[{index}] must be an object")
        point_id = _text(raw_point.get("point_id"), name=f"points[{index}].point_id")
        if point_id in seen_ids:
            raise ValueError("polarization path point_id values must be unique")
        seen_ids.add(point_id)
        parent = raw_point.get("parent_point_id")
        if index == 0:
            if parent is not None:
                raise ValueError("first polarization path point parent_point_id must be null")
        elif parent != points[-1]["point_id"]:
            raise ValueError("polarization path parent_point_id must name the previous point")
        coordinate = _number(raw_point.get("path_coordinate"), name=f"points[{index}].path_coordinate")
        if points and coordinate <= points[-1]["path_coordinate"]:
            raise ValueError("polarization path coordinates must be strictly increasing")
        task_path = _absolute_path(raw_point.get("task_file"), name=f"points[{index}].task_file")
        result_path = _absolute_path(raw_point.get("result_file"), name=f"points[{index}].result_file")
        if str(result_path.resolve()) in seen_results:
            raise ValueError("polarization path result_file values must be unique")
        seen_results.add(str(result_path.resolve()))
        point = _point_record(raw_point, request=request, previous=previous_point)
        if point["task_id"] in seen_tasks:
            raise ValueError("polarization path task IDs must be unique")
        seen_tasks.add(point["task_id"])
        job_id = point["native_job"]["scheduler_job_id"]
        if job_id in seen_jobs:
            raise ValueError("polarization path native scheduler jobs must be unique")
        seen_jobs.add(job_id)
        if common_method is None:
            common_method = point["_method_signature"]
        elif point["_method_signature"] != common_method:
            raise ValueError("polarization path points must share one physical method signature")
        if point["_branch_unresolved"]:
            unresolved_reasons.append(point["_branch_unresolved"])
        previous_point = point
        points.append(point)
    representative = [point["_representative"] for point in points]
    quantum = [point["_quantum"] for point in points]
    branches = [point["_branch"] for point in points]
    bases = [point["_branch_basis"] for point in points]
    unwrapped, delta = _branch_algebra(representative, quantum, branches, bases)
    if unwrapped is not None:
        for point, value in zip(points, unwrapped):
            point["polarization"]["unwrapped_P_C_per_m2"] = value
    if len(points) == 1:
        status = "unresolved_insufficient_path"
        unresolved_reasons.append("unresolved_insufficient_path")
        delta = None
    elif not any(point["geometry"]["structural_change_from_previous"] is True for point in points[1:]):
        status = "unresolved_no_structural_change"
        unresolved_reasons.append("unresolved_no_structural_change")
        delta = None
    elif unwrapped is None:
        status = "ambiguous_missing_branch_declaration"
        if "ambiguous_missing_branch_declaration" not in unresolved_reasons:
            unresolved_reasons.append("ambiguous_missing_branch_declaration")
        delta = None
    else:
        status = "evaluated_declared_branch_unqualified"
    for point in points:
        for key in ("_method_signature", "_representative", "_quantum", "_branch", "_branch_basis", "_branch_unresolved", "path_first_model_id", "path_first_model_version"):
            point.pop(key, None)
    return {
        "schema": _OUTPUT_SCHEMA,
        "path_id": path_id,
        "study_id": study_id,
        "gdir": gdir,
        "unit": "C/m^2",
        "path_basis": path_basis,
        "status": status,
        "points": points,
        "common_method": common_method,
        "delta_P_C_per_m2": delta,
        "unresolved_reasons": list(dict.fromkeys(unresolved_reasons)),
        "qualification": {
            "branch_continuity_qualified": False,
            "insulating_path_qualified": False,
            "scientific_qualification": False,
            "numerical_qualification": False,
            "production_qualification": False,
        },
        "source_request": str(request_file.resolve()),
    }


__all__ = ["analyze_polarization_path"]
