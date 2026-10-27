"""Consume explicit Berry finite-difference displacement responses.

The response adapter is deliberately a small consumer of saved native Berry
tasks.  It does not create a displacement, infer a polarization branch, or
run a solver.  Every point is read through :func:`read_berry_task`, so the
native ABACUS/Slurm/SCF/source checks remain owned by the existing Berry
parser.  This module adds the response-specific binding between a public
parent Study/model, two explicit child states, and the requested atom
displacement.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .berry_results import read_berry_task
from .modeling import ModelArtifacts, read_model_artifacts
from .polarization import _branch_algebra, _method_signature
from .tasks import load_task


_SCHEMA = "mlcc.abacus-berry-displacement-response-results-request.v1"
_MANIFEST_SCHEMA = "mlcc.abacus-berry-displacement-response.v1"
_OUTPUT_SCHEMA = "mlcc.abacus-berry-displacement-response-results.v1"
_ABACUS_VERSION = "3.10.1"
_CELL_TOL = 1.0e-8
_POSITION_TOL = 1.0e-7
_VALUE_TOL = 1.0e-7
_ELEMENTARY_CHARGE_C = 1.602176634e-19


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Berry response is missing {label}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Berry response {label} must contain a JSON object")
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
    return Path(_text(value, name=name)).expanduser().resolve()


def _task_file_path(value: Any, *, name: str) -> Path:
    """Resolve a producer nscf task_path to its task.json file."""

    path = _absolute_path(value, name=name)
    if path.name == "task.json" or path.suffix == ".json":
        return path
    return path / "task.json"


def _axis(value: Any, *, name: str) -> int:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"x", "y", "z"}:
            return {"x": 0, "y": 1, "z": 2}[normalized]
    if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1, 2):
        raise ValueError(f"{name} must be Cartesian axis 0/1/2 or x/y/z")
    return int(value)


def _axis_label(axis: int) -> str:
    return ("x", "y", "z")[axis]


def _vector(value: Any, *, name: str) -> list[float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise ValueError(f"{name} must contain three numeric values")
    return [_number(item, name=f"{name}[{index}]") for index, item in enumerate(value)]


def _model_snapshot(model: ModelArtifacts) -> dict[str, Any]:
    atoms = model.atoms
    if "atom_id" not in atoms.arrays:
        raise ValueError(f"Berry response model lacks atom_id values: {model.artifact_dir}")
    rows: list[tuple[int, str, list[float]]] = []
    frac = atoms.get_scaled_positions(wrap=False)
    for index, raw_id in enumerate(atoms.arrays["atom_id"]):
        atom_id = int(raw_id)
        rows.append((atom_id, str(atoms.get_chemical_symbols()[index]), [float(item) for item in frac[index]]))
    rows.sort(key=lambda row: row[0])
    ids = [row[0] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Berry response model atom_id values are not unique: {model.artifact_dir}")
    return {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(model.artifact_dir.resolve()),
        "atom_ids": ids,
        "atom_id_to_element": {str(row[0]): row[1] for row in rows},
        "fractional_positions_by_atom_id": {str(row[0]): row[2] for row in rows},
        "cell_angstrom": np.asarray(atoms.cell.array, dtype=float).tolist(),
    }


def _model_reference(value: Any, *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return {
        "model_id": _text(value.get("model_id"), name=f"{name}.model_id"),
        "version": _text(value.get("version"), name=f"{name}.version"),
        "path": str(_absolute_path(value.get("path", value.get("model_path")), name=f"{name}.path")),
    }


def _study_model_reference(study: Mapping[str, Any], *, name: str) -> tuple[str, str]:
    selected = study.get("model")
    if not isinstance(selected, Mapping):
        raise ValueError(f"{name}.model must be an object")
    return (
        _text(selected.get("model_id"), name=f"{name}.model.model_id"),
        _text(selected.get("version"), name=f"{name}.model.version"),
    )


def _load_parent_context(manifest: Mapping[str, Any]) -> dict[str, Any]:
    parent_binding = manifest.get("parent_study")
    if not isinstance(parent_binding, Mapping):
        raise ValueError("manifest.parent_study must be an object")
    parent_study_path = _absolute_path(parent_binding.get("study_path"), name="manifest.parent_study.study_path")
    parent_study = _json(parent_study_path, "parent study")
    parent_study_id = _text(parent_binding.get("study_id"), name="manifest.parent_study.study_id")
    if parent_study.get("study_id") != parent_study_id:
        raise ValueError("response manifest parent study identity differs from its study file")
    parent_ref = _model_reference(manifest.get("parent_model"), name="manifest.parent_model")
    parent_model = read_model_artifacts(parent_ref["path"])
    if (parent_model.model_id, parent_model.version) != (parent_ref["model_id"], parent_ref["version"]):
        raise ValueError("response manifest parent model identity differs from its model files")
    if _study_model_reference(parent_study, name="parent study") != (parent_model.model_id, parent_model.version):
        raise ValueError("parent Study model identity differs from the public parent model")
    return {
        "study_file": parent_study_path,
        "study_id": parent_study_id,
        "study": parent_study,
        "model": parent_model,
        "model_reference": parent_ref,
        "snapshot": _model_snapshot(parent_model),
    }


def _manifest_points(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = manifest.get("points")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, list) or not raw:
        raise ValueError("response manifest points must be a non-empty list")
    points: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(raw):
        if not isinstance(value, Mapping):
            raise ValueError(f"response manifest points[{index}] must be an object")
        point_id = _text(value.get("point_id"), name=f"manifest.points[{index}].point_id")
        if point_id in points:
            raise ValueError("response manifest point_id values must be unique")
        child_study_id = _text(value.get("child_study_id"), name=f"manifest point {point_id}.child_study_id")
        model_id = _text(value.get("child_model_id"), name=f"manifest point {point_id}.child_model_id")
        model_version = _text(value.get("child_model_version"), name=f"manifest point {point_id}.child_model_version")
        study_path = _absolute_path(value.get("study_path"), name=f"manifest point {point_id}.study_path")
        model_path = _absolute_path(value.get("model_path"), name=f"manifest point {point_id}.model_path")
        scf_task_path = _task_file_path(value.get("scf_task_path"), name=f"manifest point {point_id}.scf_task_path")
        raw_displacements = value.get("displacements")
        if isinstance(raw_displacements, (str, bytes)) or not isinstance(raw_displacements, list) or not raw_displacements:
            raise ValueError(f"manifest point {point_id}.displacements must be a non-empty list")
        raw_gdirs = value.get("gdirs")
        if isinstance(raw_gdirs, (str, bytes)) or not isinstance(raw_gdirs, list) or not raw_gdirs:
            raise ValueError(f"manifest point {point_id}.gdirs must be a non-empty list")
        gdirs: list[int] = []
        for gdir_index, raw_gdir in enumerate(raw_gdirs):
            if isinstance(raw_gdir, bool) or not isinstance(raw_gdir, int) or raw_gdir not in (1, 2, 3):
                raise ValueError(f"manifest point {point_id}.gdirs[{gdir_index}] must be 1, 2 or 3")
            if raw_gdir in gdirs:
                raise ValueError(f"manifest point {point_id}.gdirs must not repeat a direction")
            gdirs.append(int(raw_gdir))
        nscf_tasks = value.get("nscf_tasks")
        if not isinstance(nscf_tasks, list):
            raise ValueError(f"manifest point {point_id}.nscf_tasks must be a list")
        by_gdir: dict[int, dict[str, Any]] = {}
        for task_index, raw_task in enumerate(nscf_tasks):
            if not isinstance(raw_task, Mapping):
                raise ValueError(f"manifest point {point_id}.nscf_tasks[{task_index}] must be an object")
            raw_gdir = raw_task.get("gdir")
            if isinstance(raw_gdir, bool) or not isinstance(raw_gdir, int) or raw_gdir not in (1, 2, 3):
                raise ValueError(f"manifest point {point_id}.nscf_tasks[{task_index}].gdir must be 1, 2 or 3")
            if raw_gdir in by_gdir:
                raise ValueError(f"manifest point {point_id} repeats nscf gdir={raw_gdir}")
            task_id = _text(raw_task.get("task_id"), name=f"manifest point {point_id}.nscf_tasks[{task_index}].task_id")
            task_path = _task_file_path(raw_task.get("task_path"), name=f"manifest point {point_id}.nscf_tasks[{task_index}].task_path")
            task_record = dict(raw_task)
            if raw_task.get("result_file") is not None:
                task_record["result_file"] = _absolute_path(
                    raw_task.get("result_file"),
                    name=f"manifest point {point_id}.nscf_tasks[{task_index}].result_file",
                )
            by_gdir[int(raw_gdir)] = {"task_id": task_id, "task_path": task_path, "record": task_record}
        if any(gdir not in gdirs for gdir in by_gdir):
            raise ValueError(f"manifest point {point_id}.nscf_tasks contains an undeclared gdir")
        points[point_id] = {
            "point_id": point_id,
            "parent_study_id": _text(value.get("parent_study_id"), name=f"manifest point {point_id}.parent_study_id"),
            "parent_model": _model_reference(value.get("parent_model"), name=f"manifest point {point_id}.parent_model"),
            "study_id": child_study_id,
            "study_file": study_path,
            "model_path": model_path,
            "model_id": model_id,
            "model_version": model_version,
            "scf_task_path": scf_task_path,
            "scf_task_id": _text(value.get("scf_task_id"), name=f"manifest point {point_id}.scf_task_id"),
            "displacements": [dict(item) if isinstance(item, Mapping) else item for item in raw_displacements],
            "gdirs": gdirs,
            "nscf_tasks": by_gdir,
            "manifest_record": dict(value),
        }
    return points


def _point_descriptor(
    point_id_value: Any,
    *,
    label: str,
    points: Mapping[str, Mapping[str, Any]],
    gdir: int,
    sign: int,
    branch_integer: Any,
    branch_basis: Any,
) -> dict[str, Any]:
    point_id = _text(point_id_value, name=f"{label}.point_id")
    if point_id not in points:
        raise ValueError(f"{label}.point_id is absent from response_manifest")
    manifest_point = points[point_id]
    if gdir not in manifest_point["gdirs"]:
        raise ValueError(f"{label}.point_id does not declare gdir={gdir}")
    nscf = manifest_point["nscf_tasks"].get(gdir)
    if nscf is None:
        raise ValueError(f"{label}.point_id has no manifest nscf task for gdir={gdir}")
    branch = _integer_or_none(branch_integer, name=f"{label}.branch_integer")
    if branch_basis is not None and (not isinstance(branch_basis, str) or not branch_basis.strip()):
        raise ValueError(f"{label}.branch_basis must be non-empty text or null")
    descriptor = {
        "point_id": point_id,
        "task_file": nscf["task_path"],
        "result_file": nscf["record"].get("result_file"),
        "study_file": manifest_point["study_file"],
        "study_id": manifest_point["study_id"],
        "model_path": manifest_point["model_path"],
        "model_id": manifest_point["model_id"],
        "model_version": manifest_point["model_version"],
        "scf_task_path": manifest_point["scf_task_path"],
        "scf_task_id": manifest_point["scf_task_id"],
        "sign": int(sign),
        "branch_integer": branch,
        "branch_basis": branch_basis,
        "execution_variant": nscf["record"].get("execution_variant"),
        "manifest_nscf": dict(nscf["record"]),
    }
    return descriptor


def _validate_child_binding(
    *,
    point: Mapping[str, Any],
    task: Mapping[str, Any],
    child_study: Mapping[str, Any],
    child_model: ModelArtifacts,
    parent: Mapping[str, Any],
) -> None:
    point_id = point["point_id"]
    child_study_id = _text(child_study.get("study_id"), name=f"point {point_id} child study_id")
    if child_study_id != point["study_id"] or task.get("study_id") != child_study_id:
        raise ValueError(f"point {point_id} task and child Study are not bound to the declared child study")
    if (child_model.model_id, child_model.version) != (point["model_id"], point["model_version"]):
        raise ValueError(f"point {point_id} child model identity differs from response manifest")
    if task.get("model_id") != child_model.model_id or task.get("model_version") != child_model.version:
        raise ValueError(f"point {point_id} task model identity differs from child model")
    if _absolute_path(task.get("model_path"), name=f"point {point_id} task.model_path") != child_model.artifact_dir.resolve():
        raise ValueError(f"point {point_id} task model_path differs from child model")
    task_study_file = task.get("study_file")
    if task_study_file is None or _absolute_path(task_study_file, name=f"point {point_id} task.study_file") != point["study_file"].resolve():
        raise ValueError(f"point {point_id} task study_file differs from child Study")
    parent_study_id = parent["study_id"]
    if child_study.get("parent_study_id") != parent_study_id:
        raise ValueError(f"point {point_id} child Study parent_study_id differs from the public parent Study")
    derived = child_study.get("derived_from")
    if not isinstance(derived, Mapping):
        raise ValueError(f"point {point_id} child Study derived_from is required")
    if (
        derived.get("study_id") != parent_study_id
        or derived.get("model_id") != parent["model"].model_id
        or derived.get("model_version") != parent["model"].version
    ):
        raise ValueError(f"point {point_id} child Study is not derived from the public parent model/Study")
    metadata = child_model.metadata
    if metadata.get("parent_study_id") != parent_study_id or metadata.get("study_binding") != child_study_id:
        raise ValueError(f"point {point_id} child model Study binding is incomplete")
    parent_models = metadata.get("parent_models")
    if not isinstance(parent_models, list):
        raise ValueError(f"point {point_id} child model parent_models is required")
    parent_path = parent["model"].artifact_dir.resolve()
    matching_parent = False
    for record in parent_models:
        if not isinstance(record, Mapping):
            continue
        if (
            record.get("model_id") == parent["model"].model_id
            and record.get("version") == parent["model"].version
            and _absolute_path(record.get("path"), name=f"point {point_id} parent_models.path") == parent_path
        ):
            matching_parent = True
            break
    if not matching_parent:
        raise ValueError(f"point {point_id} child model does not name the public parent model")
    derivation = metadata.get("derivation")
    if not isinstance(derivation, Mapping) or derivation.get("parent_study_id") != parent_study_id:
        raise ValueError(f"point {point_id} child model derivation is not bound to the public parent Study")


def _minimum_image_cartesian_delta(parent: ModelArtifacts, child: ModelArtifacts) -> dict[int, np.ndarray]:
    cell = np.asarray(parent.atoms.cell.array, dtype=float)
    parent_frac = parent.atoms.get_scaled_positions(wrap=False)
    child_frac = child.atoms.get_scaled_positions(wrap=False)
    parent_ids = [int(value) for value in parent.atoms.arrays["atom_id"]]
    child_ids = [int(value) for value in child.atoms.arrays["atom_id"]]
    if len(parent_ids) != len(set(parent_ids)) or len(child_ids) != len(set(child_ids)):
        raise ValueError("response parent and child atom_id arrays must be unique")
    child_index_by_id = {atom_id: index for index, atom_id in enumerate(child_ids)}
    if set(parent_ids) != set(child_ids):
        raise ValueError("response parent and child atom_id sets differ")
    delta_frac = np.asarray(
        [child_frac[child_index_by_id[atom_id]] - parent_frac[index] for index, atom_id in enumerate(parent_ids)],
        dtype=float,
    )
    delta_frac -= np.rint(delta_frac)
    delta_cartesian = delta_frac @ cell
    return {atom_id: delta_cartesian[index] for index, atom_id in enumerate(parent_ids)}


def _validate_displacement(
    *,
    parent: ModelArtifacts,
    child: ModelArtifacts,
    point: Mapping[str, Any],
    target_atom_id: int,
    cartesian_axis: int,
    displacement_angstrom: float,
) -> dict[str, Any]:
    parent_snapshot = _model_snapshot(parent)
    child_snapshot = _model_snapshot(child)
    if parent_snapshot["atom_ids"] != child_snapshot["atom_ids"]:
        raise ValueError(f"point {point['point_id']} changes atom IDs relative to the parent model")
    if parent_snapshot["atom_id_to_element"] != child_snapshot["atom_id_to_element"]:
        raise ValueError(f"point {point['point_id']} changes atom elements relative to the parent model")
    if not np.allclose(
        np.asarray(parent_snapshot["cell_angstrom"], dtype=float),
        np.asarray(child_snapshot["cell_angstrom"], dtype=float),
        rtol=0.0,
        atol=_CELL_TOL,
    ):
        raise ValueError(f"point {point['point_id']} changes the fixed response cell")
    if target_atom_id not in parent_snapshot["atom_ids"]:
        raise ValueError("response target atom_id is absent from the parent model")
    delta_by_atom_id = _minimum_image_cartesian_delta(parent, child)
    expected_by_atom_id = {
        atom_id: np.zeros(3, dtype=float) for atom_id in parent_snapshot["atom_ids"]
    }
    expected_by_atom_id[target_atom_id][cartesian_axis] = int(point["sign"]) * displacement_angstrom
    if any(
        not np.allclose(delta_by_atom_id[atom_id], expected_by_atom_id[atom_id], rtol=0.0, atol=_POSITION_TOL)
        for atom_id in parent_snapshot["atom_ids"]
    ):
        raise ValueError(
            f"point {point['point_id']} displacement does not equal the declared Cartesian "
            f"{point['sign']:+d} delta on atom {target_atom_id}"
        )
    return {
        "sign": int(point["sign"]),
        "atom_id": target_atom_id,
        "cartesian_axis": cartesian_axis,
        "axis_label": _axis_label(cartesian_axis),
        "displacement_angstrom": displacement_angstrom,
        "actual_delta_cartesian_angstrom": delta_by_atom_id[target_atom_id].tolist(),
    }


def _validate_point(
    *,
    point: Mapping[str, Any],
    parent: Mapping[str, Any],
    gdir: int,
) -> dict[str, Any]:
    task_path = point["task_file"]
    task_record = load_task(task_path)
    task = dict(task_record.data)
    manifest_nscf = point.get("manifest_nscf")
    if not isinstance(manifest_nscf, Mapping) or manifest_nscf.get("task_id") != task.get("task_id"):
        raise ValueError(f"point {point['point_id']} manifest NSCF task identity differs from task file")
    task_result_value = task.get("result_file", "result.json")
    result_path = Path(str(task_result_value))
    if not result_path.is_absolute():
        result_path = task_path.parent / result_path
    result_path = result_path.resolve()
    manifest_result = point.get("result_file")
    if manifest_result is not None and Path(manifest_result).resolve() != result_path:
        raise ValueError(f"point {point['point_id']} manifest result_file differs from task result_file")
    native = read_berry_task(task_path)
    if not result_path.is_file():
        raise ValueError(f"point {point['point_id']} result_file is missing: {result_path}")
    saved_result = _json(result_path, f"point {point['point_id']} saved result")
    if saved_result.get("task_id") != task.get("task_id") or native.get("task_id") != task.get("task_id"):
        raise ValueError(f"point {point['point_id']} task/result/native task IDs differ")
    if str(saved_result.get("scheduler_job_id")) != str(task.get("scheduler_job_id")):
        raise ValueError(f"point {point['point_id']} saved result scheduler job differs from task")
    if str(native.get("scheduler_job_id")) != str(task.get("scheduler_job_id")):
        raise ValueError(f"point {point['point_id']} native result scheduler job differs from task")
    method_path = task_path.parent / "method.json"
    method = _json(method_path, f"point {point['point_id']} method")
    model_path = _absolute_path(task.get("model_path"), name=f"point {point['point_id']} task.model_path")
    child_model = read_model_artifacts(model_path)
    child_study = _json(point["study_file"], f"point {point['point_id']} child Study")
    _validate_child_binding(point=point, task=task, child_study=child_study, child_model=child_model, parent=parent)
    if task.get("engine") != "abacus" or task.get("engine_version") != _ABACUS_VERSION:
        raise ValueError(f"point {point['point_id']} must use ABACUS 3.10.1")
    if task.get("stage") != "P5" or task.get("calculation") != "nscf" or task.get("runner") != "slurm":
        raise ValueError(f"point {point['point_id']} must be a native P5 NSCF Slurm task")
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        raise ValueError(f"point {point['point_id']} requires native COMPLETED/0:0 evidence")
    if native.get("gdir") != gdir or native.get("engine_version") != _ABACUS_VERSION:
        raise ValueError(f"point {point['point_id']} native gdir/ABACUS version differs from request")
    if (
        native.get("method_set") != method.get("method_set")
        or native.get("model_id") != child_model.model_id
        or native.get("model_version") != child_model.version
    ):
        raise ValueError(f"point {point['point_id']} native method/model identity differs from task")
    if native.get("reference_scf_converged") is not True:
        raise ValueError(f"point {point['point_id']} lacks a converged native SCF reference")
    if native.get("reference_scf_task_id") != point["scf_task_id"] or not isinstance(native.get("reference_scf_validation"), Mapping):
        raise ValueError(f"point {point['point_id']} lacks its native SCF source record")
    reference_validation = native["reference_scf_validation"]
    if reference_validation.get("task_id") != point["scf_task_id"]:
        raise ValueError(f"point {point['point_id']} native SCF source task differs from manifest")
    reference_task_file = reference_validation.get("task_file")
    if (
        reference_task_file is None
        or _absolute_path(reference_task_file, name=f"point {point['point_id']} reference_scf_validation.task_file")
        != point["scf_task_path"].resolve()
    ):
        raise ValueError(f"point {point['point_id']} native SCF source task path differs from manifest")
    method_signature = _method_signature(method, native)
    p = _number(native.get("total_P_C_per_m2"), name=f"point {point['point_id']} total_P_C_per_m2")
    q = _number(native.get("modulo_quantum_C_per_m2"), name=f"point {point['point_id']} modulo_quantum_C_per_m2")
    if q <= 0.0:
        raise ValueError(f"point {point['point_id']} polarization quantum must be positive")
    direction = np.asarray(_vector(native.get("direction_lattice_vector_angstrom"), name=f"point {point['point_id']} direction_lattice_vector_angstrom"), dtype=float)
    unit = np.asarray(_vector(native.get("direction_unit_vector_cartesian"), name=f"point {point['point_id']} direction_unit_vector_cartesian"), dtype=float)
    if not math.isclose(float(np.linalg.norm(unit)), 1.0, rel_tol=0.0, abs_tol=_VALUE_TOL):
        raise ValueError(f"point {point['point_id']} Berry direction unit vector is not normalized")
    cell_direction = np.asarray(child_model.atoms.cell.array, dtype=float)[gdir - 1]
    expected_unit = cell_direction / np.linalg.norm(cell_direction)
    if not np.allclose(direction, cell_direction, rtol=0.0, atol=_CELL_TOL) or not np.allclose(unit, expected_unit, rtol=0.0, atol=_CELL_TOL):
        raise ValueError(f"point {point['point_id']} native direction is not bound to its model lattice vector")
    reprojection = np.asarray(_vector(native.get("cartesian_reprojection"), name=f"point {point['point_id']} cartesian_reprojection"), dtype=float)
    if not np.allclose(reprojection, p * unit, rtol=0.0, atol=_VALUE_TOL):
        raise ValueError(f"point {point['point_id']} native Cartesian reprojection differs from P and gdir")
    return {
        "point": dict(point),
        "task": task,
        "native_result": native,
        "saved_result": saved_result,
        "result_path": result_path,
        "method": method,
        "method_signature": method_signature,
        "model": child_model,
        "study": child_study,
        "p": p,
        "q": q,
        "direction_lattice_vector_angstrom": direction.tolist(),
        "direction_unit_vector_cartesian": unit.tolist(),
        "cartesian_reprojection": reprojection.tolist(),
    }


def _public_point(point: Mapping[str, Any], *, displacement: Mapping[str, Any], record: Mapping[str, Any], unwrapped: float | None) -> dict[str, Any]:
    native = record["native_result"]
    task = record["task"]
    return {
        "point_id": point["point_id"],
        "sign": point["sign"],
        "branch_integer": point["branch_integer"],
        "branch_basis": point["branch_basis"],
        "unwrapped_P_C_per_m2": unwrapped,
        "representative_P_C_per_m2": record["p"],
        "quantum_Q_C_per_m2": record["q"],
        "displacement": dict(displacement),
        "task": dict(task),
        "native_result": dict(native),
        "scf_job": dict(native["reference_scf_validation"]),
        "execution_variant": point.get("execution_variant"),
        "source": {
            "task_file": str(point["task_file"]),
            "result_file": str(record["result_path"]),
            "method_file": str((point["task_file"].parent / "method.json").resolve()),
            "study_file": str(point["study_file"]),
            "model_path": str(record["model"].artifact_dir.resolve()),
            "native_source_files": native.get("source_files"),
            "saved_result_source": str(record["result_path"]),
        },
    }


def _manifest_displacement(
    point: Mapping[str, Any],
    *,
    target_atom_id: int,
    cartesian_axis: int,
    sign: int,
) -> float:
    raw = point.get("displacements")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, list) or len(raw) != 1:
        raise ValueError(
            f"point {point['point_id']} must declare exactly one displacement for a response point"
        )
    item = raw[0]
    if not isinstance(item, Mapping) or item.get("atom_id") != target_atom_id:
        raise ValueError(f"point {point['point_id']} displacement atom differs from response target")
    vector = np.asarray(
        _vector(item.get("delta_cartesian_A"), name=f"point {point['point_id']} delta_cartesian_A"),
        dtype=float,
    )
    magnitude = abs(float(vector[cartesian_axis]))
    if magnitude <= 0.0:
        raise ValueError(f"point {point['point_id']} target displacement must be non-zero")
    expected = np.zeros(3, dtype=float)
    expected[cartesian_axis] = int(sign) * magnitude
    if not np.allclose(vector, expected, rtol=0.0, atol=_POSITION_TOL):
        raise ValueError(
            f"point {point['point_id']} manifest displacement is not {sign:+d} along the target Cartesian axis"
        )
    return magnitude


def analyze_berry_displacement_response(request_path: str | Path) -> dict[str, Any]:
    """Analyze declared ±Cartesian displacement Berry differences.

    ``request_path`` is a read-only selector for one producer manifest.  The
    selected minus/plus point IDs and per-gdir branch declarations are the only
    response-specific inputs; task and result paths are read from the producer
    manifest.  The function returns scalar directional derivatives and, only
    when all three gdirs are present and branch-resolved, their Cartesian
    reprojection sum and one Born-charge column.  It never fills a missing
    branch or direction with zero.
    """

    request_file = Path(request_path).expanduser().resolve()
    request = _json(request_file, "response request")
    if request.get("schema") != _SCHEMA:
        raise ValueError(f"Berry response request schema must be {_SCHEMA}")
    manifest_path = _absolute_path(request.get("response_manifest"), name="response_manifest")
    manifest = _json(manifest_path, "response manifest")
    if manifest.get("schema") != _MANIFEST_SCHEMA:
        raise ValueError(f"response manifest schema must be {_MANIFEST_SCHEMA}")
    response_id = _text(request.get("response_id"), name="response_id")
    if response_id != _text(manifest.get("response_id"), name="manifest.response_id"):
        raise ValueError("response request response_id differs from the producer manifest")
    parent = _load_parent_context(manifest)
    points = _manifest_points(manifest)
    for point in points.values():
        if point["parent_study_id"] != parent["study_id"]:
            raise ValueError(f"manifest point {point['point_id']} parent Study differs from producer parent Study")
        point_parent = point["parent_model"]
        if (
            point_parent["model_id"],
            point_parent["version"],
            Path(point_parent["path"]).resolve(),
        ) != (
            parent["model"].model_id,
            parent["model"].version,
            parent["model"].artifact_dir.resolve(),
        ):
            raise ValueError(f"manifest point {point['point_id']} parent model differs from producer parent model")
    target = request.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("response request requires a target object")
    target_atom_id = target.get("atom_id")
    if isinstance(target_atom_id, bool) or not isinstance(target_atom_id, int):
        raise ValueError("response target atom_id must be an integer")
    cartesian_axis = _axis(target.get("cartesian_axis", target.get("axis")), name="response target cartesian_axis")
    if target_atom_id not in parent["snapshot"]["atom_ids"]:
        raise ValueError("response target atom_id is absent from the public parent model")

    minus_point_id = _text(request.get("minus_point_id"), name="minus_point_id")
    plus_point_id = _text(request.get("plus_point_id"), name="plus_point_id")
    if minus_point_id == plus_point_id:
        raise ValueError("minus_point_id and plus_point_id must be different")
    if minus_point_id not in points or plus_point_id not in points:
        raise ValueError("response minus/plus point ID is absent from the producer manifest")
    displacement_minus = _manifest_displacement(
        points[minus_point_id], target_atom_id=target_atom_id, cartesian_axis=cartesian_axis, sign=-1
    )
    displacement_plus = _manifest_displacement(
        points[plus_point_id], target_atom_id=target_atom_id, cartesian_axis=cartesian_axis, sign=1
    )
    if not math.isclose(displacement_minus, displacement_plus, rel_tol=0.0, abs_tol=_POSITION_TOL):
        raise ValueError("producer minus/plus points use different displacement magnitudes")
    displacement_angstrom = displacement_minus

    raw_gdirs = request.get("gdirs")
    if isinstance(raw_gdirs, (str, bytes)) or not isinstance(raw_gdirs, list) or not raw_gdirs:
        raise ValueError("response request gdirs must be a non-empty list")
    seen_gdirs: set[int] = set()
    seen_task_paths: set[str] = set()
    seen_task_ids: set[str] = set()
    common_method: dict[str, Any] | None = None
    direction_records: list[dict[str, Any]] = []
    for index, raw_gdir in enumerate(raw_gdirs):
        if not isinstance(raw_gdir, Mapping):
            raise ValueError(f"gdirs[{index}] must be an object")
        gdir = raw_gdir.get("gdir")
        if isinstance(gdir, bool) or not isinstance(gdir, int) or gdir not in (1, 2, 3):
            raise ValueError(f"gdirs[{index}].gdir must be 1, 2 or 3")
        if gdir in seen_gdirs:
            raise ValueError("response gdir values must be unique")
        seen_gdirs.add(gdir)
        branch_integers = raw_gdir.get("branch_integer")
        branch_bases = raw_gdir.get("branch_basis")
        if not isinstance(branch_integers, Mapping) or not isinstance(branch_bases, Mapping):
            raise ValueError(f"gdirs[{index}] requires branch_integer and branch_basis minus/plus objects")
        minus = _point_descriptor(
            minus_point_id,
            label=f"gdirs[{index}].minus",
            points=points,
            gdir=gdir,
            sign=-1,
            branch_integer=branch_integers.get("minus"),
            branch_basis=branch_bases.get("minus"),
        )
        plus = _point_descriptor(
            plus_point_id,
            label=f"gdirs[{index}].plus",
            points=points,
            gdir=gdir,
            sign=1,
            branch_integer=branch_integers.get("plus"),
            branch_basis=branch_bases.get("plus"),
        )
        for point in (minus, plus):
            task_key = str(point["task_file"])
            if task_key in seen_task_paths:
                raise ValueError("a response task source cannot represent multiple gdirs")
            seen_task_paths.add(task_key)
        minus_record = _validate_point(point=minus, parent=parent, gdir=gdir)
        plus_record = _validate_point(point=plus, parent=parent, gdir=gdir)
        if common_method is None:
            common_method = minus_record["method_signature"]
        if minus_record["method_signature"] != plus_record["method_signature"]:
            raise ValueError(f"gdir {gdir} ± points do not share one physical method signature")
        if common_method != minus_record["method_signature"]:
            raise ValueError("all Berry response points must share one physical method signature")
        for record in (minus_record, plus_record):
            task_id = str(record["task"]["task_id"])
            if task_id in seen_task_ids:
                raise ValueError("a response task ID cannot represent multiple points")
            seen_task_ids.add(task_id)
        minus_displacement = _validate_displacement(
            parent=parent["model"],
            child=minus_record["model"],
            point=minus,
            target_atom_id=target_atom_id,
            cartesian_axis=cartesian_axis,
            displacement_angstrom=displacement_angstrom,
        )
        plus_displacement = _validate_displacement(
            parent=parent["model"],
            child=plus_record["model"],
            point=plus,
            target_atom_id=target_atom_id,
            cartesian_axis=cartesian_axis,
            displacement_angstrom=displacement_angstrom,
        )
        unwrapped, delta = _branch_algebra(
            [minus_record["p"], plus_record["p"]],
            [minus_record["q"], plus_record["q"]],
            [minus["branch_integer"], plus["branch_integer"]],
            [minus["branch_basis"], plus["branch_basis"]],
        )
        branch_resolved = unwrapped is not None and delta is not None
        derivative = None if not branch_resolved else float(delta) / (2.0 * displacement_angstrom)
        unit = np.asarray(plus_record["direction_unit_vector_cartesian"], dtype=float)
        contribution = None if derivative is None else (derivative * unit).tolist()
        direction_records.append(
            {
                "gdir": gdir,
                "direction_lattice_vector_angstrom": plus_record["direction_lattice_vector_angstrom"],
                "direction_unit_vector_cartesian": plus_record["direction_unit_vector_cartesian"],
                "minus": _public_point(minus, displacement=minus_displacement, record=minus_record, unwrapped=None if unwrapped is None else unwrapped[0]),
                "plus": _public_point(plus, displacement=plus_displacement, record=plus_record, unwrapped=None if unwrapped is None else unwrapped[1]),
                "branch_resolved": branch_resolved,
                "delta_P_gdir_C_per_m2": None if delta is None else float(delta),
                "dP_gdir_du_C_per_m2_per_angstrom": derivative,
                "cartesian_contribution_dP_du_C_per_m2_per_angstrom": contribution,
                "unit": "C/m^2/angstrom",
                "qualification": {
                    "branch_resolved": branch_resolved,
                    "scientific_qualification": False,
                    "production_qualification": False,
                },
            }
        )
    complete_gdirs = set(seen_gdirs) == {1, 2, 3}
    all_branch_resolved = all(item["branch_resolved"] for item in direction_records)
    if complete_gdirs and all_branch_resolved:
        cartesian_derivative = np.sum(
            np.asarray(
                [item["cartesian_contribution_dP_du_C_per_m2_per_angstrom"] for item in direction_records],
                dtype=float,
            ),
            axis=0,
        )
    else:
        cartesian_derivative = None
    volume_A3 = float(abs(np.linalg.det(np.asarray(parent["snapshot"]["cell_angstrom"], dtype=float))))
    if cartesian_derivative is not None:
        scale = volume_A3 * 1.0e-20 / _ELEMENTARY_CHARGE_C
        born_column = (scale * cartesian_derivative).tolist()
    else:
        born_column = None
    unresolved: list[str] = []
    if not complete_gdirs:
        unresolved.append("incomplete_cartesian_response")
    if not all_branch_resolved:
        unresolved.append("ambiguous_missing_branch_declaration")
    if complete_gdirs and all_branch_resolved:
        status = "evaluated_cartesian_response_unqualified"
    else:
        status = "unresolved_missing_branch" if complete_gdirs else "incomplete_cartesian_response"
    return {
        "schema": _OUTPUT_SCHEMA,
        "response_id": _text(request.get("response_id"), name="response_id"),
        "status": status,
        "response_manifest": str(manifest_path),
        "source_request": str(request_file),
        "parent": {
            "study_id": parent["study_id"],
            "study_file": str(parent["study_file"]),
            "model_id": parent["model"].model_id,
            "model_version": parent["model"].version,
            "model_path": str(parent["model"].artifact_dir.resolve()),
        },
        "target": {
            "atom_id": target_atom_id,
            "cartesian_axis": cartesian_axis,
            "axis_label": _axis_label(cartesian_axis),
            "displacement_angstrom": displacement_angstrom,
        },
        "common_method": common_method,
        "directions": direction_records,
        "cartesian_response": {
            "complete_gdirs": complete_gdirs,
            "gdirs": sorted(seen_gdirs),
            "dP_cartesian_du_C_per_m2_per_angstrom": None if cartesian_derivative is None else cartesian_derivative.tolist(),
            "unit": "C/m^2/angstrom",
        },
        "born_charge_column": None
        if born_column is None
        else {
            "atom_id": target_atom_id,
            "cartesian_axis": cartesian_axis,
            "values_e": born_column,
            "unit": "e",
            "complete": True,
        },
        "epsilon_infinity": None,
        "ionic_dielectric": None,
        "static_dielectric": None,
        "volume_A3": volume_A3,
        "unresolved_reasons": unresolved,
        "qualification": {
            "native_tasks_completed": True,
            "scf_references_converged": True,
            "complete_cartesian_response": bool(complete_gdirs and all_branch_resolved),
            "branch_continuity_qualified": False,
            "scientific_qualification": False,
            "numerical_qualification": False,
            "production_qualification": False,
        },
    }


__all__ = ["analyze_berry_displacement_response"]
