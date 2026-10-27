"""Fixed-cell atomic-displacement producers for Berry response calculations.

This module only materializes explicit structures, Studies, and ABACUS task
inputs.  It deliberately stops at the native-task boundary: an SCF task is
created for every requested point, while a Berry NSCF task is created only
after the referenced SCF task carries saved native completion evidence.  No
scheduler submission, path ordering, phase selection, relaxation, or
polarization algebra is performed here.

The response points are represented by sibling child Studies.  The manifest
therefore records their common parent Study/model for a later response
collector; it does not pretend that sibling Studies satisfy the sequential
path contract used by :mod:`mlcc.polarization`.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .berry_tasks import (
    _validate_model_study,
    create_berry_nscf_task,
    create_berry_reference_task,
)
from .model_derivatives import (
    _model_charge_state,
    _parent_record,
    _require_atom_id,
    _write_derived,
)
from .modeling import ModelArtifacts, read_model_artifacts
from .tasks import load_task, save_task


RESPONSE_REQUEST_SCHEMA = "mlcc.abacus-berry-displacement-response-request.v1"
POINT_REQUEST_SCHEMA = "mlcc.abacus-berry-displacement-point-request.v1"
RESPONSE_MANIFEST_SCHEMA = "mlcc.abacus-berry-displacement-response.v1"
RESPONSE_BINDING_SCHEMA = "mlcc.abacus-berry-response-binding.v1"

_GDIRS = (1, 2, 3)


def _json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_json(path: str | Path, value: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    result = value.strip()
    if result in {".", ".."} or "/" in result or "\\" in result:
        raise ValueError(f"{name} must be a single path-safe identifier")
    return result


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _zero_time(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value) == 0.0
    return isinstance(value, str) and value.strip() == "0"


def _resources(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result = dict(value)
    if "time" not in result or not _zero_time(result["time"]):
        raise ValueError(f"{name}.time must be explicitly 0 for a DFT task")
    return result


def _required_results(value: Any, name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must be a list of objects")
    return [dict(item) for item in value]


def _gdirs(value: Any, name: str) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise ValueError(f"{name} must be a non-empty list of Berry directions")
    result: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
            raise ValueError(f"{name}[{index}] must be an integer in 1, 2, or 3")
        direction = int(item)
        if direction not in _GDIRS:
            raise ValueError(f"{name}[{index}] must be an integer in 1, 2, or 3")
        if direction in result:
            raise ValueError(f"{name} must not repeat a direction")
        result.append(direction)
    return result


def _displacements(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(f"{name}[{index}] must be an object")
        atom_id = _require_atom_id(item.get("atom_id"), f"{name}[{index}].atom_id")
        if atom_id in seen:
            raise ValueError(f"{name} must not contain the same atom_id twice")
        seen.add(atom_id)
        delta = item.get("delta_cartesian_A")
        if not isinstance(delta, Sequence) or isinstance(delta, (str, bytes)) or len(delta) != 3:
            raise ValueError(f"{name}[{index}].delta_cartesian_A must have length 3")
        vector = [_finite_number(component, f"{name}[{index}].delta_cartesian_A") for component in delta]
        result.append({"atom_id": atom_id, "delta_cartesian_A": vector})
    return result


def _model_identity(parent: ModelArtifacts) -> dict[str, Any]:
    return {
        "model_id": parent.model_id,
        "version": parent.version,
        "path": str(parent.artifact_dir.resolve()),
        "charge_state": _model_charge_state(parent.metadata),
    }


def _parent_contract(parent: ModelArtifacts, study: Mapping[str, Any]) -> None:
    _validate_model_study(parent, study)
    if _model_charge_state(parent.metadata) != 0:
        raise ValueError("Berry displacement response requires a neutral parent model")
    if not bool(np.all(np.asarray(parent.atoms.pbc, dtype=bool))):
        raise ValueError("Berry displacement response requires a three-dimensional periodic parent")
    cell = np.asarray(parent.atoms.cell.array, dtype=float)
    if cell.shape != (3, 3) or not np.isfinite(cell).all() or abs(float(np.linalg.det(cell))) <= 1.0e-10:
        raise ValueError("Berry displacement response requires a finite non-zero parent cell")


def _point_records(request: Mapping[str, Any], parent: ModelArtifacts, parent_study: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_points = request.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError("response request requires a non-empty points list")
    parent_study_id = _text(parent_study.get("study_id"), "parent study_id")
    records: list[dict[str, Any]] = []
    seen_points: set[str] = set()
    seen_models: set[tuple[str, str]] = set()
    seen_studies: set[str] = set()
    seen_tasks: set[str] = set()
    parent_atom_ids = set(parent.atom_ids)
    for index, raw in enumerate(raw_points):
        if not isinstance(raw, Mapping):
            raise ValueError(f"points[{index}] must be an object")
        point_id = _text(raw.get("point_id"), f"points[{index}].point_id")
        child_model_id = _text(raw.get("child_model_id"), f"points[{index}].child_model_id")
        child_model_version = _text(raw.get("child_model_version"), f"points[{index}].child_model_version")
        child_study_id = _text(raw.get("child_study_id"), f"points[{index}].child_study_id")
        scf_task_id = _text(raw.get("scf_task_id"), f"points[{index}].scf_task_id")
        if point_id in seen_points:
            raise ValueError(f"response request repeats point_id {point_id!r}")
        if (child_model_id, child_model_version) in seen_models:
            raise ValueError("response request repeats a child model identity")
        if child_study_id in seen_studies or child_study_id == parent_study_id:
            raise ValueError("response child Studies require unique IDs distinct from the parent Study")
        if scf_task_id in seen_tasks:
            raise ValueError("response request repeats an SCF task_id")
        displacements = _displacements(raw.get("displacements", []), f"points[{index}].displacements")
        unknown_atoms = [item["atom_id"] for item in displacements if item["atom_id"] not in parent_atom_ids]
        if unknown_atoms:
            raise ValueError(f"points[{index}] names atom IDs absent from the parent model: {unknown_atoms}")
        resource_value = raw.get("scf_resource_request", raw.get("resource_request"))
        resources = _resources(resource_value, f"points[{index}].scf_resource_request")
        required_results = _required_results(raw.get("scf_required_results", raw.get("required_results")), f"points[{index}].scf_required_results")
        path_coordinate = _finite_number(raw.get("path_coordinate"), f"points[{index}].path_coordinate")
        gdirs = _gdirs(raw.get("gdirs"), f"points[{index}].gdirs")
        berry = raw.get("berry", {})
        if not isinstance(berry, Mapping):
            raise ValueError(f"points[{index}].berry must be an object")
        berry_record = dict(berry)
        berry_record.update({"role": "reference_scf", "out_chg": 1})
        records.append(
            {
                "point_id": point_id,
                "child_model_id": child_model_id,
                "child_model_version": child_model_version,
                "child_study_id": child_study_id,
                "scf_task_id": scf_task_id,
                "displacements": displacements,
                "path_coordinate": path_coordinate,
                "gdirs": gdirs,
                "scf_resource_request": resources,
                "scf_required_results": required_results,
                "berry": berry_record,
            }
        )
        seen_points.add(point_id)
        seen_models.add((child_model_id, child_model_version))
        seen_studies.add(child_study_id)
        seen_tasks.add(scf_task_id)
    return records


def _child_study(
    parent_study: Mapping[str, Any],
    parent: ModelArtifacts,
    *,
    response_id: str,
    point: Mapping[str, Any],
    child_model_path: Path,
    parent_study_path: Path,
) -> dict[str, Any]:
    value = copy.deepcopy(dict(parent_study))
    selected_model = value.get("model")
    if not isinstance(selected_model, Mapping):
        raise ValueError("parent Study model must be an object")
    selected_model = dict(selected_model)
    selected_model.update(
        {
            "model_id": point["child_model_id"],
            "version": point["child_model_version"],
            "source_structure": str((child_model_path / "model.extxyz").resolve()),
        }
    )
    value["model"] = selected_model
    parent_study_id = _text(parent_study.get("study_id"), "parent study_id")
    child_study_id = str(point["child_study_id"])
    value.update(
        {
            "study_id": child_study_id,
            "parent_study_id": parent_study_id,
            "derived_from": {
                "study_id": parent_study_id,
                "model_id": parent.model_id,
                "model_version": parent.version,
                "reason": "P5 fixed-cell Berry displacement response child Study",
                "parent_study_file": str(parent_study_path.resolve()),
            },
            "berry_response": {
                "schema": RESPONSE_BINDING_SCHEMA,
                "response_id": response_id,
                "point_id": point["point_id"],
                "path_coordinate": point["path_coordinate"],
                "parent_study_id": parent_study_id,
                "parent_model": _model_identity(parent),
                "cell_constraint": "fixed_cell",
                "charge_state": 0,
            },
            "status": "berry_displacement_child_study_inputs_not_calculated",
        }
    )
    return value


def _child_model(
    parent: ModelArtifacts,
    *,
    response_id: str,
    point: Mapping[str, Any],
    child_model_path: Path,
    parent_study_id: str,
    parent_study_path: Path,
    child_study_id: str,
) -> ModelArtifacts:
    child_atoms = parent.atoms.copy()
    parent_positions = np.asarray(parent.atoms.get_positions(), dtype=float).copy()
    parent_frac = np.asarray(parent.atoms.get_scaled_positions(wrap=False), dtype=float)
    id_to_index = {atom_id: index for index, atom_id in enumerate(parent.atom_ids)}
    applied: dict[int, np.ndarray] = {atom_id: np.zeros(3, dtype=float) for atom_id in parent.atom_ids}
    for item in point["displacements"]:
        atom_id = int(item["atom_id"])
        delta = np.asarray(item["delta_cartesian_A"], dtype=float)
        applied[atom_id] = delta
        child_atoms.positions[id_to_index[atom_id]] += delta
    child_frac = np.asarray(child_atoms.get_scaled_positions(wrap=False), dtype=float)
    symbols = [str(value) for value in parent.atoms.get_chemical_symbols()]
    lineage: list[dict[str, Any]] = []
    for index, atom_id in enumerate(parent.atom_ids):
        delta = applied[atom_id]
        lineage.append(
            {
                "child_atom_id": int(atom_id),
                "parent_atom_id": int(atom_id),
                "parent_image": [0, 0, 0],
                "parent_frac_coords": [float(value) for value in parent_frac[index]],
                "parent_frac_coords_unwrapped": [float(value) for value in parent_frac[index]],
                "child_frac_coords": [float(value) for value in child_frac[index]],
                "child_frac_coords_unwrapped": [float(value) for value in child_frac[index]],
                "parent_cart_coords_angstrom": [float(value) for value in parent_positions[index]],
                "child_cart_coords_angstrom": [float(value) for value in child_atoms.positions[index]],
                "displacement_cartesian_A": [float(value) for value in delta],
                "element": symbols[index],
                "kind": "cartesian_displacement" if np.any(delta != 0.0) else "retained_parent_atom",
            }
        )
    derivation = {
        "kind": "berry_fixed_cell_cartesian_displacement",
        "response_id": response_id,
        "point_id": point["point_id"],
        "path_coordinate": point["path_coordinate"],
        "displacements": copy.deepcopy(point["displacements"]),
        "parent_model": _parent_record(parent),
        "parent_study_id": parent_study_id,
        "parent_study_file": str(parent_study_path.resolve()),
        "charge_state": 0,
        "charge_convention": "neutral fixed-cell response point; no compensating charge",
        "relaxation_status": "not_run",
        "production_qualified": False,
        "study_id": child_study_id,
    }
    basis_transform = {
        "kind": "fixed_cell_cartesian_displacement",
        "fractional_matrix": np.eye(3, dtype=int).tolist(),
        "fractional_translation": [0.0, 0.0, 0.0],
        "source_lattice_angstrom": np.asarray(parent.atoms.cell.array, dtype=float).tolist(),
        "target_lattice_angstrom": np.asarray(child_atoms.cell.array, dtype=float).tolist(),
        "parent_model": _parent_record(parent),
    }
    child = _write_derived(
        parent,
        child_atoms,
        child_model_path,
        {
            "model_id": point["child_model_id"],
            "version": point["child_model_version"],
            "study_id": child_study_id,
        },
        derivation=derivation,
        atom_lineage=lineage,
        basis_transform=basis_transform,
        spatial_mode="fixed_cell_berry_displacement",
    )
    return child


def _task_path(site: Mapping[str, Any], task_id: str) -> Path:
    workspace = site.get("workspace")
    if not isinstance(workspace, Mapping) or not isinstance(workspace.get("local"), str):
        raise ValueError("site.workspace.local is required")
    return Path(str(workspace["local"])) / "tasks" / task_id


def _binding(
    *,
    manifest_path: Path,
    response_id: str,
    point: Mapping[str, Any],
    task: Mapping[str, Any],
    task_kind: str,
    gdir: int | None = None,
) -> dict[str, Any]:
    binding = {
        "schema": RESPONSE_BINDING_SCHEMA,
        "response_id": response_id,
        "point_id": point["point_id"],
        "path_coordinate": point["path_coordinate"],
        "task_kind": task_kind,
        "gdir": gdir,
        "manifest_path": str(manifest_path.resolve()),
        "parent_study_id": point["parent_study_id"],
        "parent_model": copy.deepcopy(point["parent_model"]),
        "child_study_id": point["child_study_id"],
        "child_model_id": point["child_model_id"],
        "child_model_version": point["child_model_version"],
        "source_scf_task_id": point["scf_task_id"],
        "source_scf_task_path": point["scf_task_path"],
        "task_id": task.get("task_id"),
        "task_path": task.get("task_path"),
    }
    return binding


def _bind_task(task_file: Path, binding: Mapping[str, Any], event: str) -> dict[str, Any]:
    task = load_task(task_file)
    task.set(berry_response=dict(binding))
    task.record_event(event, result="response_provenance_bound", response_id=binding["response_id"], point_id=binding["point_id"])
    save_task(task)
    return dict(task.data)


def create_berry_displacement_response(
    study_path: str | Path,
    model_path: str | Path,
    method_path: str | Path,
    site_path: str | Path,
    request_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Materialize all explicitly requested fixed-cell response SCF points.

    The caller supplies every point identity, displacement, path coordinate,
    Berry direction, and unlimited Slurm resource request.  The function
    writes a response manifest and invokes the existing Berry reference
    producer once per point.  It never submits those tasks.
    """

    request = _json(request_path)
    if request.get("schema") not in (None, RESPONSE_REQUEST_SCHEMA):
        raise ValueError(f"unsupported Berry response request schema: {request.get('schema')!r}")
    response_id = _text(request.get("response_id"), "response_id")
    if request.get("cell_constraint", "fixed_cell") != "fixed_cell":
        raise ValueError("Berry displacement response requires cell_constraint=fixed_cell")
    if "charge_state" not in request:
        raise ValueError("response request requires explicit charge_state=0")
    charge_state = request["charge_state"]
    if isinstance(charge_state, bool) or not isinstance(charge_state, (int, np.integer)) or int(charge_state) != 0:
        raise ValueError("Berry displacement response requires explicit charge_state=0")
    parent_study = _json(study_path)
    parent = read_model_artifacts(model_path)
    _parent_contract(parent, parent_study)
    parent_study_id = _text(parent_study.get("study_id"), "parent study_id")
    if request.get("parent_study_id") not in (None, parent_study_id):
        raise ValueError("response request parent_study_id differs from the supplied Study")
    if request.get("parent_model_id") not in (None, parent.model_id) or request.get("parent_model_version") not in (None, parent.version):
        raise ValueError("response request parent model identity differs from the supplied model")
    points = _point_records(request, parent, parent_study)
    output = Path(output_path).resolve()
    if output.exists():
        raise FileExistsError(f"Berry response output directory already exists: {output}")
    output.mkdir(parents=True)
    site = _json(site_path)
    parent_study_file = Path(study_path).resolve()
    parent_model_identity = _model_identity(parent)
    point_records: list[dict[str, Any]] = []
    for point in points:
        point_dir = output / "points" / str(point["point_id"])
        model_dir = point_dir / "model"
        child_study_path = point_dir / "study.json"
        scf_request_path = point_dir / "scf-request.json"
        child_model = _child_model(
            parent,
            response_id=response_id,
            point=point,
            child_model_path=model_dir,
            parent_study_id=parent_study_id,
            parent_study_path=parent_study_file,
            child_study_id=str(point["child_study_id"]),
        )
        # Keep the parent Study ID explicit in the model derivation without
        # modifying the shared private writer's generic contract.
        metadata = _json(model_dir / "model.json")
        derivation = dict(metadata.get("derivation", {}))
        derivation["parent_study_id"] = parent_study_id
        metadata["derivation"] = derivation
        metadata["parent_study_id"] = parent_study_id
        metadata["berry_response"] = {
            "schema": RESPONSE_BINDING_SCHEMA,
            "response_id": response_id,
            "point_id": point["point_id"],
            "path_coordinate": point["path_coordinate"],
            "parent_study_id": parent_study_id,
        }
        _write_json(model_dir / "model.json", metadata)
        lineage = _json(model_dir / "atom-lineage.json")
        lineage["parent_study_id"] = parent_study_id
        lineage["berry_response"] = {
            "response_id": response_id,
            "point_id": point["point_id"],
            "path_coordinate": point["path_coordinate"],
        }
        _write_json(model_dir / "atom-lineage.json", lineage)
        child_study = _child_study(
            parent_study,
            parent,
            response_id=response_id,
            point=point,
            child_model_path=model_dir,
            parent_study_path=parent_study_file,
        )
        _write_json(child_study_path, child_study)
        scf_request = {
            "schema": POINT_REQUEST_SCHEMA,
            "response_id": response_id,
            "point_id": point["point_id"],
            "child_model_id": point["child_model_id"],
            "child_model_version": point["child_model_version"],
            "child_study_id": point["child_study_id"],
            "scf_task_id": point["scf_task_id"],
            "displacements": copy.deepcopy(point["displacements"]),
            "path_coordinate": point["path_coordinate"],
            "gdirs": list(point["gdirs"]),
            "calculation": "scf",
            "task_id": point["scf_task_id"],
            "input_transformation": None,
            "berry": copy.deepcopy(point["berry"]),
            "resource_request": copy.deepcopy(point["scf_resource_request"]),
            "required_results": copy.deepcopy(point["scf_required_results"]),
            "response_parent": {
                "study_id": parent_study_id,
                "study_path": str(parent_study_file),
                "model": copy.deepcopy(parent_model_identity),
            },
        }
        _write_json(scf_request_path, scf_request)
        task_data = create_berry_reference_task(
            study_path=child_study_path,
            model_path=model_dir,
            method_path=method_path,
            site_path=site_path,
            request_path=scf_request_path,
        )
        task_dir = _task_path(site, str(point["scf_task_id"]))
        task_file = task_dir / "task.json"
        if not task_file.is_file():
            raise FileNotFoundError(f"Berry reference creator did not write task.json: {task_file}")
        point_binding = {
            "point_id": point["point_id"],
            "path_coordinate": point["path_coordinate"],
            "parent_study_id": parent_study_id,
            "parent_model": copy.deepcopy(parent_model_identity),
            "child_study_id": point["child_study_id"],
            "child_model_id": point["child_model_id"],
            "child_model_version": point["child_model_version"],
            "scf_task_id": point["scf_task_id"],
            "displacements": copy.deepcopy(point["displacements"]),
            "gdirs": list(point["gdirs"]),
            "scf_task_path": str(task_dir.resolve()),
        }
        task = load_task(task_file)
        binding = _binding(
            manifest_path=output / "response-manifest.json",
            response_id=response_id,
            point=point_binding,
            task={"task_id": task.task_id, "task_path": str(task_file.resolve())},
            task_kind="reference_scf",
        )
        task_data = _bind_task(task_file, binding, "berry_response_scf_bind")
        point_records.append(
            {
                **point_binding,
                "model_path": str(model_dir.resolve()),
                "study_path": str(child_study_path.resolve()),
                "scf_request_path": str(scf_request_path.resolve()),
                "scf_task_path": str(task_file.resolve()),
                "scf_task": {
                    "task_id": task_data.get("task_id"),
                    "scheduler_job_id": task_data.get("scheduler_job_id"),
                    "scheduler_state": task_data.get("scheduler_state"),
                    "exit_code": task_data.get("exit_code"),
                    "status": task_data.get("status"),
                    "resource_request": copy.deepcopy(task_data.get("resource_request")),
                },
                "nscf_tasks": [],
            }
        )
    manifest = {
        "schema": RESPONSE_MANIFEST_SCHEMA,
        "response_id": response_id,
        "request_schema": request.get("schema", RESPONSE_REQUEST_SCHEMA),
        "request_path": str(Path(request_path).resolve()),
        "manifest_path": str((output / "response-manifest.json").resolve()),
        "status": "scf_inputs_written_not_submitted",
        "scientific_status": "fixed_cell_response_inputs_only",
        "production_qualified": False,
        "scientific_qualification": False,
        "cell_constraint": "fixed_cell",
        "charge_state": 0,
        "parent_study": {
            "study_id": parent_study_id,
            "study_path": str(parent_study_file),
        },
        "parent_model": parent_model_identity,
        "method_path": str(Path(method_path).resolve()),
        "site_path": str(Path(site_path).resolve()),
        "points": point_records,
        "polarization_compatibility": {
            "status": "not_directly_consumable_as_sequential_path",
            "reason": "points use unique sibling child Studies; polarization.py requires one Study and sequential parent_point_id",
            "common_parent_study_id": parent_study_id,
            "common_parent_model": parent_model_identity,
            "collector_required": True,
        },
        "scope_note": "Producer creates fixed-cell SCF/NSCF inputs only; no Berry difference, Born charge, dielectric tensor, branch unwrapping, or material qualification is claimed.",
    }
    _write_json(output / "response-manifest.json", manifest)
    return manifest


def _load_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = Path(path).resolve()
    manifest = _json(manifest_path)
    if manifest.get("schema") != RESPONSE_MANIFEST_SCHEMA:
        raise ValueError(f"unsupported Berry response manifest schema: {manifest.get('schema')!r}")
    _text(manifest.get("response_id"), "manifest.response_id")
    points = manifest.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("Berry response manifest requires points")
    return manifest_path, manifest


def _manifest_point(manifest: Mapping[str, Any], point_id: str) -> dict[str, Any]:
    for value in manifest["points"]:
        if isinstance(value, Mapping) and value.get("point_id") == point_id:
            return dict(value)
    raise KeyError(f"Berry response manifest has no point_id {point_id!r}")


def _reference_preflight(task_path: Path, point: Mapping[str, Any]) -> dict[str, Any]:
    """Check saved scheduler/result identity before the old native validator.

    Native ABACUS output parsing remains owned by ``create_berry_nscf_task``'s
    existing ``validate_berry_reference`` call.  These checks are deliberately
    limited to the cheap saved evidence required before that call is reached.
    """

    task_path = task_path.resolve()
    task_file = task_path / "task.json" if task_path.is_dir() else task_path
    if not task_file.is_file():
        raise FileNotFoundError(f"Berry reference task.json is missing: {task_file}")
    task = load_task(task_file)
    if task.task_id != point["scf_task_id"]:
        raise ValueError("Berry response SCF task identity differs from manifest")
    if task.data.get("study_id") != point["child_study_id"]:
        raise ValueError("Berry response SCF study identity differs from manifest")
    if (task.data.get("model_id"), task.data.get("model_version")) != (
        point["child_model_id"],
        point["child_model_version"],
    ):
        raise ValueError("Berry response SCF model identity differs from manifest")
    recorded_model_path = task.data.get("model_path")
    if not isinstance(recorded_model_path, str) or Path(recorded_model_path).resolve() != Path(str(point["model_path"])).resolve():
        raise ValueError("Berry response SCF model path differs from manifest")
    recorded_study_path = task.data.get("study_file")
    if not isinstance(recorded_study_path, str) or Path(recorded_study_path).resolve() != Path(str(point["study_path"])).resolve():
        raise ValueError("Berry response SCF Study path differs from manifest")
    if task.data.get("scheduler_state") != "COMPLETED" or task.data.get("exit_code") != "0:0":
        raise ValueError("Berry response NSCF requires saved native SCF COMPLETED/0:0 evidence")
    if task.data.get("scheduler_job_id") in (None, ""):
        raise ValueError("Berry response NSCF requires a native SCF scheduler job ID")
    result_value = task.data.get("result_file", "result.json")
    result_path = Path(str(result_value))
    if not result_path.is_absolute():
        result_path = task_file.parent / result_path
    if not result_path.is_file():
        raise FileNotFoundError(f"Berry response SCF result.json is missing: {result_path}")
    result = _json(result_path)
    if result.get("task_id") != task.task_id or result.get("scheduler_job_id") != task.scheduler_job_id:
        raise ValueError("Berry response SCF result identity differs from task")
    if result.get("scientific_status") not in ("converged", "converged_engineering_fixture"):
        raise ValueError("Berry response NSCF requires a converged native SCF result")
    if result.get("electronic_converged") is not True:
        raise ValueError("Berry response NSCF requires native electronic convergence evidence")
    return {
        "task_id": task.task_id,
        "task_path": str(task_file.resolve()),
        "scheduler_job_id": str(task.scheduler_job_id),
        "scheduler_state": task.data.get("scheduler_state"),
        "exit_code": task.data.get("exit_code"),
        "result_path": str(result_path.resolve()),
        "scientific_status": result.get("scientific_status"),
        "electronic_converged": result.get("electronic_converged"),
        "native_parser": "delegated_to_create_berry_nscf_task.validate_berry_reference",
    }


def create_berry_response_nscf(
    manifest_path: str | Path,
    point_id: str,
    site_path: str | Path,
    method_path: str | Path,
    request_path: str | Path,
) -> dict[str, Any]:
    """Create one explicit Berry NSCF direction after native SCF completion.

    The old NSCF creator performs the strict native SCF/charge/STRU/parser
    validation.  This wrapper performs the manifest and saved completion
    preflight first, then records response provenance on the newly materialized
    task and manifest.  No numerical result is produced here.
    """

    manifest_file, manifest = _load_manifest(manifest_path)
    point_id = _text(point_id, "point_id")
    point = _manifest_point(manifest, point_id)
    if manifest.get("method_path") != str(Path(method_path).resolve()):
        raise ValueError("Berry response method_path differs from the manifest method binding")
    if manifest.get("site_path") != str(Path(site_path).resolve()):
        raise ValueError("Berry response site_path differs from the manifest site binding")
    request = _json(request_path)
    if request.get("calculation") != "nscf":
        raise ValueError("Berry response NSCF request calculation must be nscf")
    if request.get("input_transformation") not in (None,):
        raise ValueError("Berry response NSCF does not support a structure transformation")
    raw_berry = request.get("berry")
    if not isinstance(raw_berry, Mapping):
        raise ValueError("Berry response NSCF request requires a berry object")
    berry = dict(raw_berry)
    if berry.get("role") != "nscf":
        raise ValueError("Berry response NSCF request must declare berry.role=nscf")
    gdir = berry.get("gdir")
    if isinstance(gdir, bool) or not isinstance(gdir, (int, np.integer)) or int(gdir) not in _GDIRS:
        raise ValueError("Berry response NSCF request berry.gdir must be 1, 2, or 3")
    gdir = int(gdir)
    if gdir not in point.get("gdirs", []):
        raise ValueError(f"Berry response point {point_id!r} did not request gdir={gdir}")
    task_id = _text(request.get("task_id"), "request.task_id")
    resources = _resources(request.get("resource_request"), "request.resource_request")
    request["resource_request"] = resources
    existing = point.get("nscf_tasks", [])
    if not isinstance(existing, list):
        raise ValueError("Berry response manifest nscf_tasks must be a list")
    if any(isinstance(item, Mapping) and item.get("task_id") == task_id for item in existing):
        raise ValueError(f"Berry response NSCF task_id already recorded: {task_id}")
    scf_path = Path(str(point["scf_task_path"])).resolve()
    preflight = _reference_preflight(scf_path, point)
    site = _json(site_path)
    child_model_path = Path(str(point["model_path"])).resolve()
    child_study_path = Path(str(point["study_path"])).resolve()
    derived_request = copy.deepcopy(request)
    derived_request["schema"] = POINT_REQUEST_SCHEMA
    derived_request["response_id"] = manifest["response_id"]
    derived_request["point_id"] = point_id
    derived_request["child_model_id"] = point["child_model_id"]
    derived_request["child_model_version"] = point["child_model_version"]
    derived_request["child_study_id"] = point["child_study_id"]
    derived_request["source_scf_task_id"] = point["scf_task_id"]
    derived_request["response_parent"] = {
        "study_id": manifest["parent_study"]["study_id"],
        "model": copy.deepcopy(manifest["parent_model"]),
        "manifest_path": str(manifest_file),
    }
    nscf_request_path = manifest_file.parent / "points" / point_id / "nscf" / f"{task_id}.request.json"
    _write_json(nscf_request_path, derived_request)
    task_data = create_berry_nscf_task(
        reference_task_path=scf_path,
        method_path=method_path,
        site_path=site_path,
        request_path=nscf_request_path,
    )
    task_dir = _task_path(site, task_id)
    task_file = task_dir / "task.json"
    if not task_file.is_file():
        raise FileNotFoundError(f"Berry NSCF creator did not write task.json: {task_file}")
    point_binding = {
        "point_id": point_id,
        "path_coordinate": point["path_coordinate"],
        "parent_study_id": manifest["parent_study"]["study_id"],
        "parent_model": copy.deepcopy(manifest["parent_model"]),
        "child_study_id": point["child_study_id"],
        "child_model_id": point["child_model_id"],
        "child_model_version": point["child_model_version"],
        "scf_task_id": point["scf_task_id"],
        "scf_task_path": str(scf_path),
    }
    binding = _binding(
        manifest_path=manifest_file,
        response_id=str(manifest["response_id"]),
        point=point_binding,
        task={"task_id": task_id, "task_path": str(task_file.resolve())},
        task_kind="nscf",
        gdir=gdir,
    )
    task_data = _bind_task(task_file, binding, "berry_response_nscf_bind")
    nscf_record = {
        "task_id": task_id,
        "task_path": str(task_file.resolve()),
        "request_path": str(nscf_request_path.resolve()),
        "gdir": gdir,
        "resource_request": copy.deepcopy(task_data.get("resource_request")),
        "scheduler_job_id": task_data.get("scheduler_job_id"),
        "scheduler_state": task_data.get("scheduler_state"),
        "exit_code": task_data.get("exit_code"),
        "status": task_data.get("status"),
        "source_scf": preflight,
    }
    updated = copy.deepcopy(manifest)
    updated_point = _manifest_point(updated, point_id)
    updated_point.setdefault("nscf_tasks", []).append(nscf_record)
    for index, candidate in enumerate(updated["points"]):
        if candidate.get("point_id") == point_id:
            updated["points"][index] = updated_point
            break
    updated["status"] = "scf_and_nscf_inputs_written_not_submitted"
    updated["manifest_path"] = str(manifest_file)
    _write_json(manifest_file, updated)
    return {
        "schema": RESPONSE_MANIFEST_SCHEMA,
        "response_id": manifest["response_id"],
        "point_id": point_id,
        "gdir": gdir,
        "status": "nscf_inputs_written_not_submitted",
        "scientific_status": "awaiting_native_berry_nscf",
        "production_qualified": False,
        "scientific_qualification": False,
        "native_scf_preflight": preflight,
        "task": task_data,
        "task_path": str(task_file.resolve()),
        "request_path": str(nscf_request_path.resolve()),
        "manifest_path": str(manifest_file),
        "source_model": {
            "model_id": point["child_model_id"],
            "version": point["child_model_version"],
            "path": str(child_model_path),
        },
        "source_study": {
            "study_id": point["child_study_id"],
            "path": str(child_study_path),
        },
        "scope_note": "NSCF inputs are materialized only; no Berry polarization, response difference, Born charge, dielectric tensor, or scientific qualification is claimed.",
    }


__all__ = ["create_berry_displacement_response", "create_berry_response_nscf"]
