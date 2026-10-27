"""Materialize explicit clamped-ion Berry strain-response tasks.

The producer in this module owns only structure, Study, and native task
materialization.  It does not submit Slurm jobs or interpret Berry phases.
Each requested point is an explicit sibling child model whose fractional
coordinates and atom IDs are preserved while the cell is transformed by the
engineering-Voigt strain convention in :mod:`mlcc.elastic`.
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
from .elastic import VOIGT_ORDER, voigt_strain_model
from .model_derivatives import _model_charge_state, _parent_record, _write_derived
from .modeling import ModelArtifacts, read_model_artifacts
from .relaxed_structure_bridge import SCHEMA as RELAXED_BRIDGE_SCHEMA, _saved_source, create_relaxed_scf
from .tasks import load_task, save_task


RESPONSE_REQUEST_SCHEMA = "mlcc.abacus-berry-strain-response-request.v1"
POINT_REQUEST_SCHEMA = "mlcc.abacus-berry-strain-point-request.v1"
RESPONSE_MANIFEST_SCHEMA = "mlcc.abacus-berry-strain-response.v1"
RESPONSE_BINDING_SCHEMA = "mlcc.abacus-berry-strain-response-binding.v1"

_GDIRS = (1, 2, 3)
_COMPONENTS = frozenset(VOIGT_ORDER)
CLAMPED_BOUNDARY = "clamped_ion_fixed_fractional"
RELAXED_BOUNDARIES = {
    "relaxed_ion_fixed_cell": "all_internal_dofs",
    "constrained_ion_fixed_cell": "selected_internal_dofs",
}


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


def _absolute_path(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return str(path.resolve())


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


def _model_identity(model: ModelArtifacts) -> dict[str, Any]:
    return {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(model.artifact_dir.resolve()),
        "charge_state": _model_charge_state(model.metadata),
    }


def _parent_contract(parent: ModelArtifacts, study: Mapping[str, Any]) -> None:
    _validate_model_study(parent, study)
    if _model_charge_state(parent.metadata) != 0:
        raise ValueError("Berry strain response requires a neutral parent model")
    if not bool(np.all(np.asarray(parent.atoms.pbc, dtype=bool))):
        raise ValueError("Berry strain response requires a three-dimensional periodic parent")
    cell = np.asarray(parent.atoms.cell.array, dtype=float)
    if cell.shape != (3, 3) or not np.isfinite(cell).all() or abs(float(np.linalg.det(cell))) <= 1.0e-10:
        raise ValueError("Berry strain response requires a finite non-zero parent cell")


def _strain_vector(component: str, strain: float) -> list[float]:
    vector = np.zeros(6, dtype=float)
    vector[VOIGT_ORDER.index(component)] = float(strain)
    return [float(value) for value in vector]


def _point_records(
    request: Mapping[str, Any],
    parent: ModelArtifacts,
    parent_study: Mapping[str, Any],
    *,
    mechanical_boundary: str = CLAMPED_BOUNDARY,
) -> list[dict[str, Any]]:
    raw_points = request.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError("response request requires a non-empty points list")
    parent_study_id = _text(parent_study.get("study_id"), "parent study_id")
    records: list[dict[str, Any]] = []
    seen_points: set[str] = set()
    seen_models: set[tuple[str, str]] = set()
    seen_studies: set[str] = set()
    seen_tasks: set[str] = set()
    components: set[str] = set()
    parent_count = len(parent.atom_ids)
    for index, raw in enumerate(raw_points):
        if not isinstance(raw, Mapping):
            raise ValueError(f"points[{index}] must be an object")
        point_id = _text(raw.get("point_id"), f"points[{index}].point_id")
        child_model_id = _text(raw.get("child_model_id"), f"points[{index}].child_model_id")
        child_model_version = _text(raw.get("child_model_version"), f"points[{index}].child_model_version")
        child_study_id = _text(raw.get("child_study_id"), f"points[{index}].child_study_id")
        scf_task_id = _text(raw.get("scf_task_id"), f"points[{index}].scf_task_id")
        component = _text(raw.get("voigt_component"), f"points[{index}].voigt_component")
        if component not in _COMPONENTS:
            raise ValueError(f"points[{index}].voigt_component must be one of {list(VOIGT_ORDER)}")
        strain = _finite_number(raw.get("strain"), f"points[{index}].strain")
        if strain == 0.0:
            raise ValueError(f"points[{index}].strain must be non-zero")
        if point_id in seen_points:
            raise ValueError(f"response request repeats point_id {point_id!r}")
        if (child_model_id, child_model_version) in seen_models:
            raise ValueError("response request repeats a child model identity")
        if child_study_id in seen_studies or child_study_id == parent_study_id:
            raise ValueError("response child Studies require unique IDs distinct from the parent Study")
        if scf_task_id in seen_tasks:
            raise ValueError("response request repeats an SCF task_id")
        resource_value = raw.get("scf_resource_request")
        resources = _resources(resource_value, f"points[{index}].scf_resource_request")
        required_results = _required_results(raw.get("scf_required_results"), f"points[{index}].scf_required_results")
        gdirs = _gdirs(raw.get("gdirs"), f"points[{index}].gdirs")
        berry = raw.get("berry", {})
        if not isinstance(berry, Mapping):
            raise ValueError(f"points[{index}].berry must be an object")
        berry_record = dict(berry)
        berry_record.update({"role": "reference_scf", "out_chg": 1})
        strain_voigt = _strain_vector(component, strain)
        record = {
                "point_id": point_id,
                "child_model_id": child_model_id,
                "child_model_version": child_model_version,
                "child_study_id": child_study_id,
                "scf_task_id": scf_task_id,
                "voigt_component": component,
                "strain": strain,
                "strain_voigt": strain_voigt,
                "gdirs": gdirs,
                "scf_resource_request": resources,
                "scf_required_results": required_results,
                "berry": berry_record,
        }
        bridge_value = raw.get("relaxed_structure_bridge")
        if mechanical_boundary in RELAXED_BOUNDARIES:
            record["relaxed_structure_bridge"] = _absolute_path(
                bridge_value, f"points[{index}].relaxed_structure_bridge"
            )
        elif bridge_value is not None:
            raise ValueError("relaxed_structure_bridge is only valid for a relaxed fixed-cell boundary")
        records.append(record)
        seen_points.add(point_id)
        seen_models.add((child_model_id, child_model_version))
        seen_studies.add(child_study_id)
        seen_tasks.add(scf_task_id)
        components.add(component)
    if len(components) > 1:
        raise ValueError("strain response points must use one selected Voigt component")
    if len(records) == 2:
        left, right = records
        if left["voigt_component"] != right["voigt_component"] or not math.isclose(
            left["strain"], -right["strain"], rel_tol=0.0, abs_tol=0.0
        ):
            raise ValueError("a two-point central strain pair requires opposite equal non-zero strain in one component")
    if parent_count <= 0:
        raise ValueError("Berry strain response requires at least one parent atom")
    return records


def _child_model(
    parent: ModelArtifacts,
    *,
    response_id: str,
    point: Mapping[str, Any],
    child_model_path: Path,
    parent_study_id: str,
    parent_study_path: Path,
    child_study_id: str,
) -> tuple[ModelArtifacts, dict[str, Any]]:
    child_atoms, strain_record = voigt_strain_model(
        parent.atoms,
        point["strain_voigt"],
        reference_model={"model_id": parent.model_id, "version": parent.version},
    )
    parent_frac = np.asarray(parent.atoms.get_scaled_positions(wrap=False), dtype=float)
    child_frac = np.asarray(child_atoms.get_scaled_positions(wrap=False), dtype=float)
    parent_positions = np.asarray(parent.atoms.get_positions(), dtype=float)
    child_positions = np.asarray(child_atoms.get_positions(), dtype=float)
    symbols = [str(value) for value in parent.atoms.get_chemical_symbols()]
    lineage: list[dict[str, Any]] = []
    for index, atom_id in enumerate(parent.atom_ids):
        displacement = child_positions[index] - parent_positions[index]
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
                "child_cart_coords_angstrom": [float(value) for value in child_positions[index]],
                "displacement_cartesian_A": [float(value) for value in displacement],
                "element": symbols[index],
                "kind": "voigt_strain_fixed_fractional_atom",
            }
        )
    derivation = {
        "kind": "berry_clamped_ion_voigt_strain",
        "response_id": response_id,
        "point_id": point["point_id"],
        "voigt_component": point["voigt_component"],
        "strain": point["strain"],
        "strain_voigt": copy.deepcopy(point["strain_voigt"]),
        "strain_record": copy.deepcopy(strain_record),
        "parent_model": _parent_record(parent),
        "parent_study_id": parent_study_id,
        "parent_study_file": str(parent_study_path.resolve()),
        "charge_state": 0,
        "mechanical_boundary": "clamped_ion_fixed_fractional",
        "relaxation_status": "not_run",
        "production_qualified": False,
        "study_id": child_study_id,
    }
    basis_transform = {
        "kind": "voigt_strain_fixed_fractional",
        "fractional_matrix": np.eye(3, dtype=int).tolist(),
        "fractional_translation": [0.0, 0.0, 0.0],
        "source_lattice_angstrom": np.asarray(parent.atoms.cell.array, dtype=float).tolist(),
        "target_lattice_angstrom": np.asarray(child_atoms.cell.array, dtype=float).tolist(),
        "strain_record": copy.deepcopy(strain_record),
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
        spatial_mode="clamped_ion_fixed_fractional_voigt_strain",
    )
    return child, strain_record


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
            "path": str(child_model_path.resolve()),
            "model_path": str(child_model_path.resolve()),
        }
    )
    parent_study_id = _text(parent_study.get("study_id"), "parent study_id")
    value["model"] = selected_model
    value.update(
        {
            "study_id": point["child_study_id"],
            "parent_study_id": parent_study_id,
            "derived_from": {
                "study_id": parent_study_id,
                "model_id": parent.model_id,
                "model_version": parent.version,
                "reason": "P5 clamped-ion fixed-fractional Berry strain response child Study",
                "parent_study_file": str(parent_study_path.resolve()),
            },
            "berry_strain_response": {
                "schema": RESPONSE_BINDING_SCHEMA,
                "response_id": response_id,
                "point_id": point["point_id"],
                "voigt_component": point["voigt_component"],
                "strain": point["strain"],
                "strain_voigt": copy.deepcopy(point["strain_voigt"]),
                "parent_study_id": parent_study_id,
                "parent_model": _model_identity(parent),
                "mechanical_boundary": "clamped_ion_fixed_fractional",
                "charge_state": 0,
            },
            "status": "berry_strain_child_study_inputs_not_calculated",
        }
    )
    return value


def _task_path(site: Mapping[str, Any], task_id: str) -> Path:
    workspace = site.get("workspace")
    if not isinstance(workspace, Mapping) or not isinstance(workspace.get("local"), str):
        raise ValueError("site.workspace.local is required")
    return Path(str(workspace["local"])) / "tasks" / task_id


def _point_binding(
    *,
    manifest_path: Path,
    response_id: str,
    point: Mapping[str, Any],
    parent_model: Mapping[str, Any],
    parent_study_id: str,
    task: Mapping[str, Any],
    task_kind: str,
    gdir: int | None = None,
) -> dict[str, Any]:
    binding = {
        "schema": RESPONSE_BINDING_SCHEMA,
        "response_id": response_id,
        "point_id": point["point_id"],
        "task_kind": task_kind,
        "gdir": gdir,
        "manifest_path": str(manifest_path.resolve()),
        "parent_study_id": parent_study_id,
        "parent_model": copy.deepcopy(dict(parent_model)),
        "child_study_id": point["child_study_id"],
        "child_model_id": point["child_model_id"],
        "child_model_version": point["child_model_version"],
        "voigt_component": point["voigt_component"],
        "strain": point["strain"],
        "strain_voigt": copy.deepcopy(point["strain_voigt"]),
        "mechanical_boundary": point.get("mechanical_boundary", CLAMPED_BOUNDARY),
        "charge_state": 0,
        "source_scf_task_id": point["scf_task_id"],
        "source_scf_task_path": point.get("scf_task_path"),
        "task_id": task.get("task_id"),
        "task_path": task.get("task_path"),
    }
    if binding["mechanical_boundary"] in RELAXED_BOUNDARIES:
        for key in (
            "relaxation_scope",
            "pre_relax_model",
            "pre_relax_study",
            "relaxed_structure_bridge",
            "relaxation_source",
            "ionic_constraints",
        ):
            if key not in point:
                raise ValueError(f"relaxed Berry binding is missing {key}")
            binding[key] = copy.deepcopy(point[key])
    return binding


def _bind_task(task_file: Path, binding: Mapping[str, Any], event: str) -> dict[str, Any]:
    task = load_task(task_file)
    task.set(berry_strain_response=dict(binding))
    task.record_event(event, result="strain_response_provenance_bound", response_id=binding["response_id"], point_id=binding["point_id"])
    save_task(task)
    return dict(task.data)


def create_berry_strain_response(
    study_path: str | Path,
    model_path: str | Path,
    method_path: str | Path,
    site_path: str | Path,
    request_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Materialize explicit clamped or saved fixed-cell relaxed strain inputs."""

    request = _json(request_path)
    if request.get("schema") != RESPONSE_REQUEST_SCHEMA:
        raise ValueError(f"unsupported Berry strain response request schema: {request.get('schema')!r}")
    response_id = _text(request.get("response_id"), "response_id")
    mechanical_boundary = request.get("mechanical_boundary")
    if mechanical_boundary != CLAMPED_BOUNDARY and mechanical_boundary not in RELAXED_BOUNDARIES:
        raise ValueError(
            "Berry strain response mechanical_boundary must be clamped_ion_fixed_fractional, "
            "relaxed_ion_fixed_cell, or constrained_ion_fixed_cell"
        )
    if "charge_state" not in request:
        raise ValueError("response request requires explicit charge_state=0")
    charge_state = request["charge_state"]
    if isinstance(charge_state, bool) or not isinstance(charge_state, (int, np.integer)) or int(charge_state) != 0:
        raise ValueError("Berry strain response requires explicit charge_state=0")
    parent_study = _json(study_path)
    parent = read_model_artifacts(model_path)
    _parent_contract(parent, parent_study)
    parent_study_id = _text(parent_study.get("study_id"), "parent study_id")
    if request.get("parent_study_id") not in (None, parent_study_id):
        raise ValueError("response request parent_study_id differs from the supplied Study")
    if request.get("parent_model_id") not in (None, parent.model_id) or request.get("parent_model_version") not in (None, parent.version):
        raise ValueError("response request parent model identity differs from the supplied model")
    points = _point_records(request, parent, parent_study, mechanical_boundary=mechanical_boundary)
    if mechanical_boundary in RELAXED_BOUNDARIES and len(points) != 2:
        raise ValueError("relaxed fixed-cell strain response requires exactly two saved bridge points")
    output = Path(output_path).resolve()
    if output.exists():
        raise FileExistsError(f"Berry strain response output directory already exists: {output}")
    site = _json(site_path)
    parent_study_file = Path(study_path).resolve()
    parent_model_identity = _model_identity(parent)
    parent_cell = np.asarray(parent.atoms.cell.array, dtype=float)
    parent_volume = float(abs(np.linalg.det(parent_cell)))
    relaxed_info: dict[str, dict[str, Any]] = {}
    if mechanical_boundary in RELAXED_BOUNDARIES:
        base_manifest = {
            "response_id": response_id,
            "mechanical_boundary": mechanical_boundary,
            "parent_study": {"study_id": parent_study_id, "study_path": str(parent_study_file)},
            "parent_model": copy.deepcopy(parent_model_identity),
        }
        for point in points:
            relaxed_info[point["point_id"]] = _validate_relaxed_point(base_manifest, point)
            info = relaxed_info[point["point_id"]]
            bridge = info["bridge"]
            point.update(
                {
                    "mechanical_boundary": mechanical_boundary,
                    "relaxation_scope": info["relaxation_scope"],
                    "pre_relax_model": _bridge_model_identity(info["pre_relax_model"]),
                    "pre_relax_study": {
                        "study_id": bridge["parent_study"]["study_id"],
                        "study_path": str(Path(bridge["parent_study"]["study_path"]).resolve()),
                    },
                    "relaxation_source": copy.deepcopy(info["relaxation_source"]),
                    "ionic_constraints": copy.deepcopy(info["ionic_constraints"]),
                }
            )
        _validate_relaxed_pair(points, relaxed_info, berry_method_path=method_path)
    output.mkdir(parents=True)
    point_records: list[dict[str, Any]] = []
    for point in points:
        point_dir = output / "points" / point["point_id"]
        point_info = relaxed_info.get(point["point_id"])
        if mechanical_boundary in RELAXED_BOUNDARIES:
            if point_info is None:
                raise ValueError("relaxed strain point was not validated")
            child = point_info["model"]
            child_model_path = child.artifact_dir.resolve()
            child_study_path = Path(point_info["bridge"]["child_study"]["study_path"]).resolve()
            model_dir = child_model_path
            strain_record = copy.deepcopy(point_info["strain_record"])
        else:
            child_model_path = point_dir / "model"
            model_dir = child_model_path
            child_study_path = point_dir / "study.json"
            child, strain_record = _child_model(
                parent,
                response_id=response_id,
                point=point,
                child_model_path=model_dir,
                parent_study_id=parent_study_id,
                parent_study_path=parent_study_file,
                child_study_id=point["child_study_id"],
            )
        scf_request_path = point_dir / "scf-request.json"
        binding_base = {
            "schema": RESPONSE_BINDING_SCHEMA,
            "response_id": response_id,
            "point_id": point["point_id"],
            "voigt_component": point["voigt_component"],
            "strain": point["strain"],
            "strain_voigt": copy.deepcopy(point["strain_voigt"]),
            "parent_study_id": parent_study_id,
            "parent_model": copy.deepcopy(parent_model_identity),
            "child_study_id": point["child_study_id"],
            "child_model_id": point["child_model_id"],
            "child_model_version": point["child_model_version"],
            "mechanical_boundary": mechanical_boundary,
            "charge_state": 0,
        }
        if mechanical_boundary == CLAMPED_BOUNDARY:
            model_metadata = _json(model_dir / "model.json")
            model_metadata["berry_strain_response"] = copy.deepcopy(binding_base)
            _write_json(model_dir / "model.json", model_metadata)
            lineage = _json(model_dir / "atom-lineage.json")
            lineage["berry_strain_response"] = copy.deepcopy(binding_base)
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
            "voigt_component": point["voigt_component"],
            "strain": point["strain"],
            "strain_voigt": copy.deepcopy(point["strain_voigt"]),
            "strain_record": copy.deepcopy(strain_record),
            "mechanical_boundary": mechanical_boundary,
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
        if request.get("evidence_kind") is not None:
            scf_request["evidence_kind"] = request["evidence_kind"]
        if mechanical_boundary in RELAXED_BOUNDARIES:
            scf_request.update(
                {
                    "relaxation_scope": point["relaxation_scope"],
                    "pre_relax_model": copy.deepcopy(point["pre_relax_model"]),
                    "pre_relax_study": copy.deepcopy(point["pre_relax_study"]),
                    "relaxed_structure_bridge": point["relaxed_structure_bridge"],
                    "relaxation_source": copy.deepcopy(point["relaxation_source"]),
                }
            )
        _write_json(scf_request_path, scf_request)
        if mechanical_boundary in RELAXED_BOUNDARIES:
            task_data = create_relaxed_scf(
                bridge_path=point["relaxed_structure_bridge"],
                method_path=method_path,
                site_path=site_path,
                request_path=scf_request_path,
            )
        else:
            task_data = create_berry_reference_task(
                study_path=child_study_path,
                model_path=model_dir,
                method_path=method_path,
                site_path=site_path,
                request_path=scf_request_path,
            )
        task_dir = _task_path(site, point["scf_task_id"])
        task_file = task_dir / "task.json"
        if not task_file.is_file():
            raise FileNotFoundError(f"Berry reference creator did not write task.json: {task_file}")
        task = load_task(task_file)
        bound_point = {**point, "scf_task_path": str(task_file.resolve())}
        binding = _point_binding(
            manifest_path=output / "response-manifest.json",
            response_id=response_id,
            point=bound_point,
            parent_model=parent_model_identity,
            parent_study_id=parent_study_id,
            task={"task_id": task.task_id, "task_path": str(task_file.resolve())},
            task_kind="reference_scf",
        )
        task_data = _bind_task(task_file, binding, "berry_strain_response_scf_bind")
        point_records.append(
            {
                "point_id": point["point_id"],
                "child_model_id": point["child_model_id"],
                "child_model_version": point["child_model_version"],
                "child_study_id": point["child_study_id"],
                "scf_task_id": point["scf_task_id"],
                "voigt_component": point["voigt_component"],
                "strain": point["strain"],
                "strain_voigt": copy.deepcopy(point["strain_voigt"]),
                "strain_record": copy.deepcopy(strain_record),
                "mechanical_boundary": mechanical_boundary,
                "gdirs": list(point["gdirs"]),
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
        if mechanical_boundary in RELAXED_BOUNDARIES:
            point_records[-1].update(
                {
                    "relaxation_scope": point["relaxation_scope"],
                    "pre_relax_model": copy.deepcopy(point["pre_relax_model"]),
                    "pre_relax_study": copy.deepcopy(point["pre_relax_study"]),
                    "relaxed_structure_bridge": point["relaxed_structure_bridge"],
                    "relaxation_source": copy.deepcopy(point["relaxation_source"]),
                    "ionic_constraints": copy.deepcopy(point["ionic_constraints"]),
                }
            )
    manifest = {
        "schema": RESPONSE_MANIFEST_SCHEMA,
        "response_id": response_id,
        "request_schema": RESPONSE_REQUEST_SCHEMA,
        "request_path": str(Path(request_path).resolve()),
        "manifest_path": str((output / "response-manifest.json").resolve()),
        "method_path": str(Path(method_path).resolve()),
        "site_path": str(Path(site_path).resolve()),
        "status": "scf_inputs_written_not_submitted",
        "mechanical_boundary": mechanical_boundary,
        "scientific_status": (
            "fixed_fractional_strain_response_inputs_only"
            if mechanical_boundary == CLAMPED_BOUNDARY
            else "saved_relaxed_strain_response_inputs_only"
        ),
        "charge_state": 0,
        "qualification": False,
        "scientific_qualification": False,
        "production_qualified": False,
        "parent_study": {
            "study_id": parent_study_id,
            "study_path": str(parent_study_file),
        },
        "parent_model": parent_model_identity,
        "reference_lattice_angstrom": parent_cell.tolist(),
        "reference_volume_A3": parent_volume,
        "voigt_order": list(VOIGT_ORDER),
        "engineering_shear": True,
        "points": point_records,
    }
    if request.get("evidence_kind") is not None:
        manifest["evidence_kind"] = request["evidence_kind"]
    if mechanical_boundary in RELAXED_BOUNDARIES:
        manifest["relaxation_scope"] = point_records[0]["relaxation_scope"]
    _write_json(output / "response-manifest.json", manifest)
    return manifest


def _load_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = Path(path).resolve()
    manifest = _json(manifest_path)
    if manifest.get("schema") != RESPONSE_MANIFEST_SCHEMA:
        raise ValueError(f"unsupported Berry strain response manifest schema: {manifest.get('schema')!r}")
    _text(manifest.get("response_id"), "manifest.response_id")
    boundary = manifest.get("mechanical_boundary")
    if boundary != CLAMPED_BOUNDARY and boundary not in RELAXED_BOUNDARIES:
        raise ValueError("Berry strain response manifest has an unsupported mechanical_boundary")
    points = manifest.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("Berry strain response manifest requires points")
    if boundary in RELAXED_BOUNDARIES:
        if len(points) != 2:
            raise ValueError("relaxed fixed-cell strain response manifest requires exactly two points")
        for index, point in enumerate(points):
            if not isinstance(point, Mapping):
                raise ValueError(f"manifest.points[{index}] must be an object")
            _absolute_path(point.get("relaxed_structure_bridge"), f"manifest.points[{index}].relaxed_structure_bridge")
    return manifest_path, manifest


def _manifest_point(manifest: Mapping[str, Any], point_id: str) -> dict[str, Any]:
    for value in manifest["points"]:
        if isinstance(value, Mapping) and value.get("point_id") == point_id:
            return dict(value)
    raise KeyError(f"Berry strain response manifest has no point_id {point_id!r}")


def _path_matches(value: Any, expected: Any) -> bool:
    return isinstance(value, str) and Path(value).resolve() == Path(str(expected)).resolve()


def _array_matches(
    value: Any,
    expected: Any,
    *,
    shape: tuple[int, ...] | None = None,
    atol: float = 1.0e-12,
) -> bool:
    try:
        left = np.asarray(value, dtype=float)
        right = np.asarray(expected, dtype=float)
    except (TypeError, ValueError):
        return False
    if shape is not None and left.shape != shape:
        return False
    return left.shape == right.shape and np.allclose(left, right, rtol=0.0, atol=atol)


def _model_parent_matches(child: ModelArtifacts, parent: ModelArtifacts) -> bool:
    records = child.metadata.get("parent_models")
    if not isinstance(records, list):
        return False
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if (record.get("model_id"), record.get("version")) != (parent.model_id, parent.version):
            continue
        if _path_matches(record.get("path"), parent.artifact_dir):
            return True
    return False


def _method_relaxed_signature(method: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the two relax sources, including their declared stop controls."""
    signature = _method_physical_signature(method)
    parameters = method.get("parameters", {})
    science = method.get("science", {})
    signature.update({
        "relax_method": method.get("relax_method", science.get("relax_method")),
        "relax_nmax": parameters.get("relax_nmax"),
        "force_thr_eV_per_A": parameters.get("force_thr_eV_per_A"),
    })
    return signature


def _method_physical_signature(method: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the existing configuration and saved method representations.

    Configurations group science/execution; prepare_abacus also records them
    at top level, with abacus_version_target and an explicit-mesh marker.
    Model/task/output locations and ionic stop controls are not physical
    differences between the relax source and its fresh reference SCF.
    """
    values = {**method.get("science", {}), **method.get("execution", {}),
              **method.get("parameters", {}), **method}
    keys = (
        "engine", "basis_type", "dft_functional", "ks_solver", "nspin",
        "lspinorb", "noncolin", "initial_moments_muB_by_element", "occupations",
        "smearing_method", "smearing_sigma_Ry", "mixing_type", "mixing_beta",
        "symmetry", "ecutwfc_Ry", "nbands", "scf_thr", "scf_nmax", "net_charge",
        "element_order", "pseudopotential_ids", "pseudopotential_metadata",
        "pseudopotential_treatment", "kpoints",
    )
    signature = {key: copy.deepcopy(values.get(key)) for key in keys}
    signature["engine_version"] = values.get("engine_version", values.get("abacus_version_target"))
    # The existing PW writer accepts an explicit Gamma-centered mesh only.
    signature["kpoint_rule"] = values.get("kpoint_rule", "explicit_mesh")
    signature["kpoint_shift"] = values.get("kpoint_shift", [0, 0, 0])
    return signature

def _constraints_scope(constraints: Mapping[str, Any], atom_ids: Sequence[int]) -> str:
    if constraints.get("schema") != "mlcc.ionic-constraints.v1":
        raise ValueError("relaxation source ionic_constraints schema is unsupported")
    if constraints.get("coordinate_basis") != "cartesian":
        raise ValueError("relaxation source ionic_constraints must use Cartesian coordinates")
    if list(constraints.get("atom_ids", [])) != list(atom_ids):
        raise ValueError("relaxation source ionic_constraints atom IDs differ from the model")
    flags = np.asarray(constraints.get("move_flags"))
    if flags.shape != (len(atom_ids), 3) or flags.dtype.kind not in "iu" or not np.isin(flags, [0, 1]).all():
        raise ValueError("relaxation source ionic_constraints move_flags are invalid")
    if not flags.any():
        raise ValueError("relaxation source ionic_constraints has no movable degree of freedom")
    return "all_internal_dofs" if bool(np.all(flags == 1)) else "selected_internal_dofs"


def _constraints_pair_signature(constraints: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": constraints.get("schema"),
        "coordinate_basis": constraints.get("coordinate_basis"),
        "atom_ids": copy.deepcopy(constraints.get("atom_ids")),
        "move_flags": copy.deepcopy(constraints.get("move_flags")),
        "relax_new": constraints.get("relax_new"),
    }


def _validate_relaxed_point(manifest: Mapping[str, Any], point: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one saved fixed-cell relaxation bridge without running a task.

    The returned records are deliberately reusable by the Berry consumer.  All
    native convergence and geometry checks are delegated to the bridge's saved
    source gate; this helper only binds that proven source to this response
    point and checks the initial strain lineage.
    """

    boundary = manifest.get("mechanical_boundary")
    if boundary not in RELAXED_BOUNDARIES:
        raise ValueError("relaxed point validation requires a relaxed fixed-cell mechanical boundary")
    bridge_path = Path(_absolute_path(point.get("relaxed_structure_bridge"), "relaxed_structure_bridge"))
    if not bridge_path.is_file():
        raise FileNotFoundError(f"relaxed structure bridge is missing: {bridge_path}")
    bridge = _json(bridge_path)
    if bridge.get("schema") != RELAXED_BRIDGE_SCHEMA or not _path_matches(bridge.get("bridge_path"), bridge_path):
        raise ValueError("relaxed structure bridge schema/path differs from the point")
    parent_model_record = manifest.get("parent_model")
    parent_study_record = manifest.get("parent_study")
    if not isinstance(parent_model_record, Mapping) or not isinstance(parent_study_record, Mapping):
        raise ValueError("relaxed Berry response requires parent model and Study records")
    root_model = read_model_artifacts(parent_model_record["path"])
    root_study_path = Path(_absolute_path(parent_study_record.get("study_path"), "manifest.parent_study.study_path"))
    root_study = _json(root_study_path)
    _parent_contract(root_model, root_study)
    if (root_model.model_id, root_model.version) != (
        parent_model_record.get("model_id"),
        parent_model_record.get("version"),
    ):
        raise ValueError("relaxed Berry root model identity differs from manifest")
    if root_study.get("study_id") != parent_study_record.get("study_id"):
        raise ValueError("relaxed Berry root Study identity differs from manifest")

    pre_record = bridge.get("parent_model")
    pre_study_record = bridge.get("parent_study")
    child_record = bridge.get("child_model")
    child_study_record = bridge.get("child_study")
    source = bridge.get("relaxation_source")
    if not all(isinstance(value, Mapping) for value in (pre_record, pre_study_record, child_record, child_study_record, source)):
        raise ValueError("relaxed structure bridge is missing parent/child/source records")
    pre_model_path = _absolute_path(pre_record.get("path"), "bridge.parent_model.path")
    pre_study_path = _absolute_path(pre_study_record.get("study_path"), "bridge.parent_study.study_path")
    pre_model = read_model_artifacts(pre_model_path)
    pre_study = _json(pre_study_path)
    _validate_model_study(pre_model, pre_study)
    if (pre_model.model_id, pre_model.version) != (pre_record.get("model_id"), pre_record.get("version")):
        raise ValueError("relaxed structure bridge pre-relax model identity differs")
    if pre_study.get("study_id") != pre_study_record.get("study_id"):
        raise ValueError("relaxed structure bridge pre-relax Study identity differs")
    if pre_study.get("case_id") != root_study.get("case_id") or pre_study.get("case_role") != root_study.get("case_role"):
        raise ValueError("relaxed strain point pre-relax Study case identity differs from the root")
    if pre_study.get("parent_study_id") != root_study.get("study_id"):
        raise ValueError("relaxed strain point pre-relax Study parent differs from the root")
    pre_derived = pre_study.get("derived_from")
    if not isinstance(pre_derived, Mapping) or pre_derived.get("study_id") != root_study.get("study_id"):
        raise ValueError("relaxed strain point pre-relax Study derivation differs from the root")
    if not _path_matches(pre_derived.get("parent_study_file"), root_study_path):
        raise ValueError("relaxed strain point pre-relax Study source path differs from the root")
    if not _model_parent_matches(pre_model, root_model):
        raise ValueError("relaxed strain point must derive its pre-relax model from the common root")
    if _model_charge_state(pre_model.metadata) != 0:
        raise ValueError("relaxed Berry strain point pre-relax model must be neutral")
    if list(pre_model.atom_ids) != list(root_model.atom_ids) or pre_model.atoms.get_chemical_symbols() != root_model.atoms.get_chemical_symbols():
        raise ValueError("relaxed strain point pre-relax atom mapping differs from the root")
    if not np.array_equal(np.asarray(pre_model.atoms.pbc, dtype=bool), np.asarray(root_model.atoms.pbc, dtype=bool)):
        raise ValueError("relaxed strain point periodicity differs from the root")
    for key in ("material", "phase_requested", "fixture", "dopants"):
        if pre_model.metadata.get(key) != root_model.metadata.get(key):
            raise ValueError(f"relaxed strain point pre-relax {key} differs from the root")
    for key in ("material", "phase_requested"):
        if pre_study.get("model", {}).get(key) != root_study.get("model", {}).get(key):
            raise ValueError(f"relaxed strain point Study {key} differs from the root")

    saved_parent, saved_study, final_atoms, saved_source = _saved_source(
        source.get("task_file"), pre_model.artifact_dir, pre_study_path
    )
    if saved_parent.model_id != pre_model.model_id or saved_parent.version != pre_model.version or saved_study.get("study_id") != pre_study.get("study_id"):
        raise ValueError("relaxation source parent identity differs from bridge")
    if saved_source != dict(source):
        raise ValueError("relaxation source differs from the bridge's saved source gate")
    if bridge.get("parent_model") != _bridge_model_identity(pre_model) or bridge.get("parent_study") != {
        "study_id": pre_study["study_id"],
        "study_path": str(pre_study_path),
    }:
        raise ValueError("relaxed structure bridge parent binding differs from saved source")

    child_model_path = _absolute_path(child_record.get("path"), "bridge.child_model.path")
    child_study_path = _absolute_path(child_study_record.get("study_path"), "bridge.child_study.study_path")
    child_model = read_model_artifacts(child_model_path)
    child_study = _json(child_study_path)
    _validate_model_study(child_model, child_study)
    if (child_model.model_id, child_model.version) != (child_record.get("model_id"), child_record.get("version")):
        raise ValueError("relaxed structure bridge child model identity differs")
    if child_study.get("study_id") != child_study_record.get("study_id"):
        raise ValueError("relaxed structure bridge child Study identity differs")
    if _model_charge_state(child_model.metadata) != 0:
        raise ValueError("relaxed strain point final model must be neutral")
    for key in ("material", "phase_requested", "fixture", "dopants"):
        if child_model.metadata.get(key) != pre_model.metadata.get(key):
            raise ValueError(f"relaxed strain point child {key} differs from its pre-relax model")
    if child_study.get("case_id") != pre_study.get("case_id") or child_study.get("case_role") != pre_study.get("case_role"):
        raise ValueError("relaxed strain point child Study case identity differs from its pre-relax Study")
    if child_study.get("parent_study_id") != pre_study.get("study_id"):
        raise ValueError("relaxed strain point child Study parent differs from its pre-relax Study")
    child_derived = child_study.get("derived_from")
    if not isinstance(child_derived, Mapping) or child_derived.get("study_id") != pre_study.get("study_id"):
        raise ValueError("relaxed strain point child Study derivation differs from its pre-relax Study")
    if not _path_matches(child_derived.get("study_file"), pre_study_path):
        raise ValueError("relaxed strain point child Study source path differs from its pre-relax Study")
    expected_child_parent = _bridge_model_identity(pre_model)
    if child_model.metadata.get("parent_model") != expected_child_parent or not _model_parent_matches(child_model, pre_model):
        raise ValueError("relaxed strain point child model parent differs from its pre-relax model")
    if (child_model.model_id, child_model.version, child_study["study_id"]) != (
        point.get("child_model_id"), point.get("child_model_version"), point.get("child_study_id")
    ):
        raise ValueError("relaxed strain point child identity differs from its bridge")
    if child_model.metadata.get("relaxation_source") != source or child_study.get("relaxation_source") != source:
        raise ValueError("relaxed strain point child source provenance differs from its bridge")
    if child_model.atom_ids != pre_model.atom_ids or child_model.atoms.get_chemical_symbols() != pre_model.atoms.get_chemical_symbols():
        raise ValueError("relaxed strain point child atom mapping differs from its pre-relax source")
    if not np.allclose(child_model.atoms.cell.array, pre_model.atoms.cell.array, atol=1e-7, rtol=0):
        raise ValueError("relaxed strain point final cell differs from its pre-relax cell")
    if not np.allclose(child_model.atoms.positions, final_atoms.positions, atol=1e-7, rtol=0):
        raise ValueError("relaxed strain point final model differs from saved relaxed geometry")

    expected_vector = _strain_vector(str(point.get("voigt_component")), float(point.get("strain")))
    if not _array_matches(point.get("strain_voigt"), expected_vector, shape=(6,)):
        raise ValueError("relaxed strain point strain_voigt does not match component and strain")
    expected_atoms, expected_record = voigt_strain_model(
        root_model.atoms,
        expected_vector,
        reference_model={"model_id": root_model.model_id, "version": root_model.version},
    )
    if not _array_matches(pre_model.atoms.cell.array, expected_atoms.cell.array, shape=(3, 3)):
        raise ValueError("relaxed strain point pre-relax cell differs from its declared strain")
    if not _array_matches(
        pre_model.atoms.get_scaled_positions(wrap=False),
        expected_atoms.get_scaled_positions(wrap=False),
        shape=(len(root_model.atom_ids), 3),
        atol=1e-8,
    ):
        raise ValueError("relaxed strain point pre-relax fractional coordinates differ from its declared strain")
    declared_record = point.get("strain_record")
    if declared_record is None:
        declared_record = expected_record
    if not isinstance(declared_record, Mapping):
        raise ValueError("relaxed strain point strain_record must be an object")
    for key in (
        "strain_voigt",
        "epsilon_tensor",
        "F",
        "deformation_gradient",
        "reference_lattice_angstrom",
        "derived_lattice_angstrom",
    ):
        if not _array_matches(declared_record.get(key), expected_record.get(key)):
            raise ValueError(f"relaxed strain point strain_record field {key} differs from its pre-relax geometry")
    for key in ("engineering_shear", "fractional_coordinates_fixed", "atom_ids_preserved"):
        if declared_record.get(key) != expected_record.get(key):
            raise ValueError(f"relaxed strain point strain_record field {key} differs from its pre-relax geometry")

    expected_source_binding = {
        "point_id": point.get("point_id"),
        "parent_study_id": root_study.get("study_id"),
        "child_study_id": pre_study.get("study_id"),
        "child_model_id": pre_model.model_id,
        "child_model_version": pre_model.version,
        "voigt_component": point.get("voigt_component"),
        "strain": point.get("strain"),
        "strain_voigt": point.get("strain_voigt"),
        "charge_state": 0,
    }
    for owner, record in (
        ("pre-relax model", pre_model.metadata.get("berry_strain_response")),
        ("pre-relax Study", pre_study.get("berry_strain_response")),
    ):
        if not isinstance(record, Mapping):
            raise ValueError(f"relaxed strain point {owner} is missing its strain response binding")
        if record.get("schema") != RESPONSE_BINDING_SCHEMA or record.get("mechanical_boundary") != CLAMPED_BOUNDARY:
            raise ValueError(f"relaxed strain point {owner} source binding is not the clamped pre-relax strain")
        for key, expected in expected_source_binding.items():
            if key == "strain_voigt":
                if not _array_matches(record.get(key), expected, shape=(6,)):
                    raise ValueError(f"relaxed strain point {owner} {key} differs from its source binding")
            elif record.get(key) != expected:
                raise ValueError(f"relaxed strain point {owner} {key} differs from its source binding")
        bound_parent = record.get("parent_model")
        if not isinstance(bound_parent, Mapping) or bound_parent.get("model_id") != root_model.model_id or bound_parent.get("version") != root_model.version or not _path_matches(bound_parent.get("path"), root_model.artifact_dir):
            raise ValueError(f"relaxed strain point {owner} parent binding differs from the root")
    model_binding = pre_model.metadata.get("berry_strain_response")
    study_binding = pre_study.get("berry_strain_response")
    if model_binding.get("response_id") != study_binding.get("response_id"):
        raise ValueError("relaxed strain point pre-relax model and Study response IDs differ")

    relaxation = source.get("relaxation")
    if not isinstance(relaxation, Mapping):
        raise ValueError("relaxation_source.relaxation is required")
    constraints = relaxation.get("ionic_constraints")
    if not isinstance(constraints, Mapping):
        raise ValueError("relaxation_source.relaxation.ionic_constraints is required")
    scope = _constraints_scope(constraints, pre_model.atom_ids)
    if scope != RELAXED_BOUNDARIES[boundary]:
        raise ValueError("relaxed strain response boundary does not match its saved ionic constraints")
    if point.get("relaxation_scope", scope) != scope:
        raise ValueError("relaxed strain point relaxation_scope differs from its saved constraints")
    if point.get("ionic_constraints", constraints) != dict(constraints):
        raise ValueError("relaxed strain point ionic_constraints differ from its saved source")
    if point.get("relaxation_source", source) != dict(source):
        raise ValueError("relaxed strain point relaxation_source differs from its bridge")
    if point.get("pre_relax_model") is not None and point["pre_relax_model"] != _bridge_model_identity(pre_model):
        raise ValueError("relaxed strain point pre_relax_model differs from its bridge")
    expected_pre_study = {"study_id": pre_study["study_id"], "study_path": str(pre_study_path)}
    if point.get("pre_relax_study") is not None and point["pre_relax_study"] != expected_pre_study:
        raise ValueError("relaxed strain point pre_relax_study differs from its bridge")
    return {
        "model": child_model,
        "study": child_study,
        "pre_relax_model": pre_model,
        "pre_relax_study": pre_study,
        "relaxation_source": copy.deepcopy(dict(source)),
        "ionic_constraints": copy.deepcopy(dict(constraints)),
        "relaxation_scope": scope,
        "bridge": bridge,
        "strain_record": copy.deepcopy(dict(declared_record)),
    }


def _bridge_model_identity(model: ModelArtifacts) -> dict[str, Any]:
    return {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(model.artifact_dir.resolve()),
    }


def _validate_relaxed_pair(
    points: Sequence[Mapping[str, Any]],
    info: Mapping[str, Mapping[str, Any]],
    *,
    berry_method_path: str | Path,
) -> None:
    if len(points) != 2:
        raise ValueError("relaxed fixed-cell strain response requires exactly two paired points")
    scopes = {str(info[item["point_id"]]["relaxation_scope"]) for item in points}
    if len(scopes) != 1:
        raise ValueError("relaxed strain response points must use one relaxation scope")
    constraints = [info[item["point_id"]]["ionic_constraints"] for item in points]
    if _constraints_pair_signature(constraints[0]) != _constraints_pair_signature(constraints[1]):
        raise ValueError("relaxed strain response points must use the same ionic constraint selection")
    sources = [info[item["point_id"]]["relaxation_source"] for item in points]
    source_task_ids = {source.get("task_id") for source in sources}
    if len(source_task_ids) != 2:
        raise ValueError("relaxed strain response points require distinct saved relaxation tasks")
    method_signatures = []
    relaxation_signatures = []
    for source in sources:
        method_file = _absolute_path(source.get("method_file"), "relaxation_source.method_file")
        method = _json(method_file)
        method_signatures.append(_method_relaxed_signature(method))
        relaxation = source.get("relaxation")
        if not isinstance(relaxation, Mapping):
            raise ValueError("relaxation_source.relaxation is required")
        relaxation_signatures.append(
            {
                "relax_new": relaxation.get("relax_new"),
                "relax_nmax": relaxation.get("relax_nmax"),
                "force_metric": relaxation.get("force_metric"),
                "force_threshold_eV_per_A": relaxation.get("force_threshold_eV_per_A"),
                "ionic_constraints": _constraints_pair_signature(relaxation["ionic_constraints"]),
            }
        )
    if method_signatures[0] != method_signatures[1]:
        raise ValueError("relaxed strain response points must use the same physical method and pseudopotentials")
    if relaxation_signatures[0] != relaxation_signatures[1]:
        raise ValueError("relaxed strain response points must use the same relaxation controls")
    berry_method = _json(berry_method_path)
    if _method_physical_signature(berry_method) != _method_physical_signature(_json(sources[0]["method_file"])):
        raise ValueError("Berry reference method differs from the saved relaxation physical method")


def _validate_point_binding_and_geometry(manifest: Mapping[str, Any], point: Mapping[str, Any], task: Any) -> None:
    """Check the producer binding and declared geometry before NSCF creation.

    The existing native NSCF creator validates native SCF/charge evidence, but
    it cannot know which response manifest point the task was meant to serve.
    These checks keep that response identity and the explicit deformation
    record attached to the saved SCF task.
    """

    binding = task.data.get("berry_strain_response")
    if not isinstance(binding, Mapping):
        raise ValueError("Berry strain response SCF task is missing berry_strain_response binding")
    expected_parent = manifest.get("parent_model")
    if not isinstance(expected_parent, Mapping):
        raise ValueError("Berry strain response manifest parent_model is required")
    expected = {
        "schema": RESPONSE_BINDING_SCHEMA,
        "response_id": manifest.get("response_id"),
        "point_id": point.get("point_id"),
        "parent_study_id": manifest.get("parent_study", {}).get("study_id"),
        "child_study_id": point.get("child_study_id"),
        "child_model_id": point.get("child_model_id"),
        "child_model_version": point.get("child_model_version"),
        "voigt_component": point.get("voigt_component"),
        "mechanical_boundary": manifest.get("mechanical_boundary"),
        "charge_state": 0,
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            raise ValueError(f"Berry strain response SCF binding field {key} differs from manifest")
    bound_strain = _finite_number(binding.get("strain"), "berry_strain_response.strain")
    if not math.isclose(bound_strain, float(point["strain"]), rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("Berry strain response SCF binding strain differs from manifest")
    if not _array_matches(binding.get("strain_voigt"), point.get("strain_voigt"), shape=(6,)):
        raise ValueError("Berry strain response SCF binding strain_voigt differs from manifest")
    bound_parent = binding.get("parent_model")
    if not isinstance(bound_parent, Mapping):
        raise ValueError("Berry strain response SCF binding is missing parent_model")
    for key in ("model_id", "version", "charge_state"):
        if bound_parent.get(key) != expected_parent.get(key):
            raise ValueError(f"Berry strain response SCF binding parent model {key} differs from manifest")
    if not _path_matches(bound_parent.get("path"), expected_parent.get("path")):
        raise ValueError("Berry strain response SCF binding parent model path differs from manifest")
    if binding.get("source_scf_task_id") != point.get("scf_task_id"):
        raise ValueError("Berry strain response SCF binding source task differs from manifest")
    if not _path_matches(binding.get("source_scf_task_path"), point.get("scf_task_path")):
        raise ValueError("Berry strain response SCF binding source task path differs from manifest")

    if manifest.get("mechanical_boundary") in RELAXED_BOUNDARIES:
        relaxed = _validate_relaxed_point(manifest, point)
        for key in (
            "relaxation_scope",
            "pre_relax_model",
            "pre_relax_study",
            "relaxed_structure_bridge",
            "relaxation_source",
            "ionic_constraints",
        ):
            expected_value = point.get(key)
            bound_value = binding.get(key)
            if key == "relaxed_structure_bridge":
                if not _path_matches(bound_value, expected_value):
                    raise ValueError(f"Berry strain response SCF relaxed binding field {key} differs from manifest")
            elif bound_value != expected_value:
                raise ValueError(f"Berry strain response SCF relaxed binding field {key} differs from manifest")
        child = relaxed["model"]
        child_study = relaxed["study"]
        if (child.model_id, child.version) != (point.get("child_model_id"), point.get("child_model_version")):
            raise ValueError("Berry strain response relaxed child model identity differs from manifest")
        if child_study.get("study_id") != point.get("child_study_id"):
            raise ValueError("Berry strain response relaxed child Study identity differs from manifest")
        return

    parent_model_path = expected_parent.get("path")
    if not isinstance(parent_model_path, str):
        raise ValueError("Berry strain response manifest parent_model.path is required")
    parent = read_model_artifacts(parent_model_path)
    child = read_model_artifacts(point["model_path"])
    child_study = _json(point["study_path"])
    _validate_model_study(child, child_study)
    if (child.model_id, child.version) != (point["child_model_id"], point["child_model_version"]):
        raise ValueError("Berry strain response child model identity differs from manifest")
    expected_vector = _strain_vector(str(point["voigt_component"]), float(point["strain"]))
    if not _array_matches(point.get("strain_voigt"), expected_vector, shape=(6,)):
        raise ValueError("Berry strain response manifest strain_voigt does not match component and strain")
    expected_atoms, expected_record = voigt_strain_model(
        parent.atoms,
        expected_vector,
        reference_model={"model_id": parent.model_id, "version": parent.version},
    )
    if child.atom_ids != parent.atom_ids or child.atoms.get_chemical_symbols() != parent.atoms.get_chemical_symbols():
        raise ValueError("Berry strain response child atom mapping differs from the parent model")
    if not _array_matches(child.atoms.cell.array, expected_atoms.cell.array, shape=(3, 3)):
        raise ValueError("Berry strain response child cell differs from the declared strain")
    if not _array_matches(
        child.atoms.get_scaled_positions(wrap=False),
        expected_atoms.get_scaled_positions(wrap=False),
        shape=(len(parent.atom_ids), 3),
        atol=1.0e-8,
    ):
        raise ValueError("Berry strain response child fractional coordinates differ from the declared strain")
    declared_record = point.get("strain_record")
    if not isinstance(declared_record, Mapping):
        raise ValueError("Berry strain response point is missing strain_record")
    for key in (
        "strain_voigt",
        "epsilon_tensor",
        "F",
        "deformation_gradient",
        "reference_lattice_angstrom",
        "derived_lattice_angstrom",
    ):
        if not _array_matches(declared_record.get(key), expected_record.get(key)):
            raise ValueError(f"Berry strain response strain_record field {key} differs from child geometry")
    for key in ("engineering_shear", "fractional_coordinates_fixed", "atom_ids_preserved"):
        if declared_record.get(key) != expected_record.get(key):
            raise ValueError(f"Berry strain response strain_record field {key} differs from child geometry")


def _reference_preflight(task_path: Path, point: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    task_file = task_path.resolve()
    if task_file.is_dir():
        task_file = task_file / "task.json"
    if not task_file.is_file():
        raise FileNotFoundError(f"Berry strain response SCF task.json is missing: {task_file}")
    task = load_task(task_file)
    if task.task_id != point["scf_task_id"]:
        raise ValueError("Berry strain response SCF task identity differs from manifest")
    if task.data.get("study_id") != point["child_study_id"]:
        raise ValueError("Berry strain response SCF Study identity differs from manifest")
    if (task.data.get("model_id"), task.data.get("model_version")) != (
        point["child_model_id"],
        point["child_model_version"],
    ):
        raise ValueError("Berry strain response SCF model identity differs from manifest")
    model_path = task.data.get("model_path")
    if not isinstance(model_path, str) or Path(model_path).resolve() != Path(str(point["model_path"])).resolve():
        raise ValueError("Berry strain response SCF model path differs from manifest")
    study_path = task.data.get("study_file")
    if not isinstance(study_path, str) or Path(study_path).resolve() != Path(str(point["study_path"])).resolve():
        raise ValueError("Berry strain response SCF Study path differs from manifest")
    if task.data.get("scheduler_state") != "COMPLETED" or task.data.get("exit_code") != "0:0":
        raise ValueError("Berry strain response NSCF requires saved native SCF COMPLETED/0:0 evidence")
    if task.data.get("scheduler_job_id") in (None, ""):
        raise ValueError("Berry strain response NSCF requires a native SCF scheduler job ID")
    result_value = task.data.get("result_file", "result.json")
    result_path = Path(str(result_value))
    if not result_path.is_absolute():
        result_path = task_file.parent / result_path
    if not result_path.is_file():
        raise FileNotFoundError(f"Berry strain response SCF result.json is missing: {result_path}")
    result = _json(result_path)
    if result.get("task_id") != task.task_id or result.get("scheduler_job_id") != task.scheduler_job_id:
        raise ValueError("Berry strain response SCF result identity differs from task")
    if result.get("scientific_status") not in ("converged", "converged_engineering_fixture"):
        raise ValueError("Berry strain response NSCF requires a converged native SCF result")
    if result.get("electronic_converged") is not True:
        raise ValueError("Berry strain response NSCF requires native electronic convergence evidence")
    _validate_point_binding_and_geometry(manifest, point, task)
    preflight = {
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
    if manifest.get("mechanical_boundary") in RELAXED_BOUNDARIES:
        relaxed = _validate_relaxed_point(manifest, point)
        preflight.update(
            {
                "relaxed_structure_bridge": point["relaxed_structure_bridge"],
                "relaxation_scope": relaxed["relaxation_scope"],
                "relaxation_source": copy.deepcopy(relaxed["relaxation_source"]),
            }
        )
    return preflight


def create_berry_strain_nscf(
    manifest_path: str | Path,
    point_id: str,
    site_path: str | Path,
    method_path: str | Path,
    request_path: str | Path,
) -> dict[str, Any]:
    """Materialize one explicit Berry NSCF direction for a strain point."""

    manifest_file, manifest = _load_manifest(manifest_path)
    point_id = _text(point_id, "point_id")
    point = _manifest_point(manifest, point_id)
    if manifest.get("method_path") != str(Path(method_path).resolve()):
        raise ValueError("Berry strain response method_path differs from the manifest method binding")
    if manifest.get("site_path") != str(Path(site_path).resolve()):
        raise ValueError("Berry strain response site_path differs from the manifest site binding")
    request = _json(request_path)
    if request.get("calculation") != "nscf":
        raise ValueError("Berry strain response NSCF request calculation must be nscf")
    if request.get("input_transformation") not in (None,):
        raise ValueError("Berry strain response NSCF does not support a structure transformation")
    raw_berry = request.get("berry")
    if not isinstance(raw_berry, Mapping):
        raise ValueError("Berry strain response NSCF request requires a berry object")
    berry = dict(raw_berry)
    if berry.get("role") != "nscf":
        raise ValueError("Berry strain response NSCF request must declare berry.role=nscf")
    gdir = berry.get("gdir")
    if isinstance(gdir, bool) or not isinstance(gdir, (int, np.integer)) or int(gdir) not in _GDIRS:
        raise ValueError("Berry strain response NSCF request berry.gdir must be 1, 2, or 3")
    gdir = int(gdir)
    if gdir not in point.get("gdirs", []):
        raise ValueError(f"Berry strain response point {point_id!r} did not request gdir={gdir}")
    task_id = _text(request.get("task_id"), "request.task_id")
    resources = _resources(request.get("resource_request"), "request.resource_request")
    existing = point.get("nscf_tasks", [])
    if not isinstance(existing, list):
        raise ValueError("Berry strain response manifest nscf_tasks must be a list")
    if any(isinstance(item, Mapping) and item.get("task_id") == task_id for item in existing):
        raise ValueError(f"Berry strain response NSCF task_id already recorded: {task_id}")
    scf_file = Path(str(point["scf_task_path"])).resolve()
    preflight = _reference_preflight(scf_file, point, manifest)
    site = _json(site_path)
    derived_request = copy.deepcopy(request)
    derived_request.update(
        {
            "schema": POINT_REQUEST_SCHEMA,
            "response_id": manifest["response_id"],
            "point_id": point_id,
            "child_model_id": point["child_model_id"],
            "child_model_version": point["child_model_version"],
            "child_study_id": point["child_study_id"],
            "source_scf_task_id": point["scf_task_id"],
            "response_parent": {
                "study_id": manifest["parent_study"]["study_id"],
                "model": copy.deepcopy(manifest["parent_model"]),
                "manifest_path": str(manifest_file),
            },
            "strain_response": {
                "voigt_component": point["voigt_component"],
                "strain": point["strain"],
                "strain_voigt": copy.deepcopy(point["strain_voigt"]),
                "mechanical_boundary": manifest["mechanical_boundary"],
            },
        }
    )
    if manifest.get("evidence_kind") is not None:
        derived_request["evidence_kind"] = manifest["evidence_kind"]
    if manifest.get("mechanical_boundary") in RELAXED_BOUNDARIES:
        for key in (
            "relaxation_scope",
            "pre_relax_model",
            "pre_relax_study",
            "relaxed_structure_bridge",
            "relaxation_source",
            "ionic_constraints",
        ):
            derived_request[key] = copy.deepcopy(point[key])
    nscf_request_path = manifest_file.parent / "points" / point_id / "nscf" / f"{task_id}.request.json"
    _write_json(nscf_request_path, derived_request)
    task_data = create_berry_nscf_task(
        reference_task_path=scf_file,
        method_path=method_path,
        site_path=site_path,
        request_path=nscf_request_path,
    )
    task_dir = _task_path(site, task_id)
    task_file = task_dir / "task.json"
    if not task_file.is_file():
        raise FileNotFoundError(f"Berry NSCF creator did not write task.json: {task_file}")
    parent_model = manifest["parent_model"]
    binding = _point_binding(
        manifest_path=manifest_file,
        response_id=str(manifest["response_id"]),
        point=point,
        parent_model=parent_model,
        parent_study_id=str(manifest["parent_study"]["study_id"]),
        task={"task_id": task_id, "task_path": str(task_file.resolve())},
        task_kind="nscf",
        gdir=gdir,
    )
    task_data = _bind_task(task_file, binding, "berry_strain_response_nscf_bind")
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
    updated_point["nscf_tasks"] = [*existing, nscf_record]
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
            "path": str(Path(str(point["model_path"])).resolve()),
        },
        "source_study": {
            "study_id": point["child_study_id"],
            "path": str(Path(str(point["study_path"])).resolve()),
        },
        "scope_note": "NSCF inputs are materialized only; no Berry polarization, strain response, Born charge, dielectric tensor, or scientific qualification is claimed.",
    }


__all__ = ["create_berry_strain_response", "create_berry_strain_nscf", "_validate_relaxed_point"]
