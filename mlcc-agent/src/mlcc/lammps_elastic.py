"""Prepare one small fixed-strain LAMMPS elasticity demo.

The producer in this module materializes the already-defined elastic strain
plan into child model/Study inputs and delegates static input writing to the
existing LAMMPS task factory.  It never submits a scheduler job and it does
not fit or consume an elastic tensor.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .elastic import VOIGT_ORDER, plan_elastic_strains, voigt_strain_model
from .lammps_tasks import create_lammps_task
from .modeling import ModelArtifacts, read_model_artifacts, write_model_artifacts
from .site_runner import SiteConfig, SiteRunner
from .studies import load_study
from .tasks import load_task, save_task


_REQUEST_SCHEMA = "mlcc.lammps-elastic-prepare-request.v1"
_RESPONSE_SCHEMA = "mlcc.lammps-elastic-response-request.v1"
_MANIFEST_SCHEMA = "mlcc.lammps-elastic-prepare-manifest.v1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"elastic prepare {name} must be a non-empty string")
    return value.strip()


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"elastic prepare {name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        qualifier = "positive and finite" if positive else "finite"
        raise ValueError(f"elastic prepare {name} must be {qualifier}")
    return result


def _resolve_input_path(request_path: Path, value: Any, name: str) -> Path:
    raw = Path(_required_text(value, name))
    path = raw if raw.is_absolute() else request_path.parent / raw
    return path.resolve()


def _point_ids(plan_id: str, request_id: str) -> tuple[str, str, str, str]:
    point_id = request_id
    identity = f"{plan_id}-{point_id}"
    return point_id, f"{identity}-model", f"{identity}-study", f"{identity}-task"


def _parent_model_record(model: ModelArtifacts) -> dict[str, Any]:
    return {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(model.artifact_dir.resolve()),
        "atom_ids": model.atom_ids,
    }


def _parent_study_record(
    study: Mapping[str, Any], path: Path, *, model_path: Path | None = None
) -> dict[str, Any]:
    selected = study.get("model")
    model = dict(selected) if isinstance(selected, Mapping) else {}
    model_ref = {
        key: model[key]
        for key in ("model_id", "version")
        if key in model
    }
    if model_path is not None:
        model_ref.update(
            {
                "path": str(model_path.resolve()),
                "model_path": str(model_path.resolve()),
            }
        )
    return {
        "study_id": study.get("study_id"),
        "path": str(path.resolve()),
        "model": model_ref,
    }


def _lineage(parent: ModelArtifacts, child_atoms: Any) -> list[dict[str, Any]]:
    parent_frac = np.asarray(parent.atoms.get_scaled_positions(wrap=False), dtype=float)
    child_frac = np.asarray(child_atoms.get_scaled_positions(wrap=False), dtype=float)
    parent_cart = np.asarray(parent.atoms.get_positions(), dtype=float)
    child_cart = np.asarray(child_atoms.get_positions(), dtype=float)
    symbols = [str(value) for value in parent.atoms.get_chemical_symbols()]
    rows: list[dict[str, Any]] = []
    for index, atom_id in enumerate(parent.atom_ids):
        rows.append(
            {
                "child_atom_id": int(atom_id),
                "parent_atom_id": int(atom_id),
                "parent_frac_coords": parent_frac[index].tolist(),
                "child_frac_coords": child_frac[index].tolist(),
                "parent_cart_coords_angstrom": parent_cart[index].tolist(),
                "child_cart_coords_angstrom": child_cart[index].tolist(),
                "displacement_cartesian_A": (child_cart[index] - parent_cart[index]).tolist(),
                "element": symbols[index],
                "kind": "voigt_strain_fixed_fractional_atom",
            }
        )
    return rows


def _materialize_model(
    parent: ModelArtifacts,
    *,
    child_atoms: Any,
    strain_record: Mapping[str, Any],
    model_id: str,
    model_version: str,
    child_study_id: str,
    parent_study_id: str,
    parent_study_path: Path,
    output: Path,
) -> ModelArtifacts:
    lineage = _lineage(parent, child_atoms)
    parent_ref = _parent_model_record(parent)
    basis_transform = {
        "kind": "voigt_strain_fixed_fractional",
        "fractional_matrix": np.eye(3, dtype=int).tolist(),
        "fractional_translation": [0.0, 0.0, 0.0],
        "source_lattice_angstrom": np.asarray(parent.atoms.cell.array, dtype=float).tolist(),
        "target_lattice_angstrom": np.asarray(child_atoms.cell.array, dtype=float).tolist(),
        "strain_record": copy.deepcopy(dict(strain_record)),
        "parent_model": parent_ref,
    }
    derivation = {
        "kind": "voigt_strain_fixed_fractional",
        "strain_record": copy.deepcopy(dict(strain_record)),
        "parent_model": parent_ref,
        "parent_study_id": parent_study_id,
        "parent_study_file": str(parent_study_path.resolve()),
        "study_id": child_study_id,
        "production_qualified": False,
        "scientific_status": "derived_structure_not_relaxed",
    }
    child = write_model_artifacts(
        child_atoms,
        output,
        model_id=model_id,
        version=model_version,
        fixture=bool(parent.metadata.get("fixture", False)),
        fixture_purpose=parent.metadata.get("fixture_purpose"),
        phase_requested=str(parent.metadata.get("phase_requested", "user_selected_phase_pending")),
        source_path=str(parent.artifact_dir.resolve()),
        source_version=f"{parent.model_id}:{parent.version}",
        engineering_perturbation={
            "kind": "voigt_strain_fixed_fractional",
            "strain_voigt": copy.deepcopy(dict(strain_record))["strain_voigt"],
        },
        source_atoms=parent.atoms.copy(),
        material=parent.metadata.get("material"),
        source_format="voigt_strain_plan",
        source_reference=str(parent_study_path.resolve()),
        selection_status="explicit_derived_model",
        material_selection_confirmed=parent.metadata.get("material_selection_confirmed"),
        basis_transform=basis_transform,
        atom_lineage=lineage,
        scientific_status="derived_structure_not_relaxed",
    )
    metadata = dict(child.metadata)
    metadata.update(
        {
            "parent_models": [parent_ref],
            "parent_model": parent_ref,
            "parent_study_file": str(parent_study_path.resolve()),
            "source_structure_role": "generated_child_reference",
            "derivation_schema": "mlcc.model-derivation.v1",
            "derivation": derivation,
            "parent_study_id": parent_study_id,
            "study_id": child_study_id,
            "study_binding": child_study_id,
            "production_qualified": False,
            "scientific_status": "derived_structure_not_relaxed",
            "relaxation_status": "not_run",
        }
    )
    _write_json(output / "model.json", metadata)
    lineage_value = _read_json(output / "atom-lineage.json")
    lineage_value.update(
        {
            "parent_model": parent_ref,
            "parent_study_file": str(parent_study_path.resolve()),
            "derivation_schema": "mlcc.model-derivation.v1",
            "derivation": derivation,
        }
    )
    _write_json(output / "atom-lineage.json", lineage_value)
    child.metadata = metadata
    return child


def _child_study(
    root: Mapping[str, Any],
    *,
    root_model: ModelArtifacts,
    root_study_path: Path,
    child_model: ModelArtifacts,
    child_model_path: Path,
    child_study_id: str,
    strain_record: Mapping[str, Any],
    task_id: str,
) -> dict[str, Any]:
    value = copy.deepcopy(dict(root))
    selected = value.get("model")
    if not isinstance(selected, Mapping):
        raise ValueError("root Study model must be an object")
    selected_model = dict(selected)
    selected_model.update(
        {
            "model_id": child_model.model_id,
            "version": child_model.version,
            "source_structure": str((child_model_path / "model.extxyz").resolve()),
            "path": str(child_model_path.resolve()),
            "model_path": str(child_model_path.resolve()),
        }
    )
    root_study_id = _required_text(root.get("study_id"), "root study_id")
    value["model"] = selected_model
    value.update(
        {
            "study_id": child_study_id,
            "parent_study_id": root_study_id,
            "parent_study_file": str(root_study_path.resolve()),
            "derived_from": {
                "study_id": root_study_id,
                "model_id": root_model.model_id,
                "model_version": root_model.version,
                "parent_study_file": str(root_study_path.resolve()),
                "reason": "fixed_fractional_voigt_strain_child",
            },
            "elastic_strain": copy.deepcopy(dict(strain_record)),
            "selected_required_tasks": [task_id],
            "status": "elastic_strain_child_study_inputs_not_calculated",
        }
    )
    return value


def _protocol(
    *,
    timestep_ps: float,
    strain_record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "run0",
        "purpose": "potential_qualification",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "timestep_ps": timestep_ps,
        "static_tensor": True,
        "experiment_scope": "elastic_static_demo",
        "elastic_strain": copy.deepcopy(dict(strain_record)),
    }


def _task_lineage(
    *,
    root_model: ModelArtifacts,
    root_study: Mapping[str, Any],
    root_study_path: Path,
    child_study: Mapping[str, Any],
    child_study_path: Path,
    child_model: ModelArtifacts,
    child_model_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        {
            "model_id": root_model.model_id,
            "version": root_model.version,
            "path": str(root_model.artifact_dir.resolve()),
        },
        _parent_study_record(root_study, root_study_path, model_path=root_model.artifact_dir),
        _parent_study_record(child_study, child_study_path, model_path=child_model_path),
    )


def _potential_copy(
    source: Mapping[str, Any],
    *,
    root_model_id: str,
    root_potential_path: Path,
    child_model_ids: list[str],
    output_path: Path,
) -> dict[str, Any]:
    potential = copy.deepcopy(dict(source))
    model_ids = [str(value) for value in potential.get("model_ids", [])]
    if root_model_id not in model_ids:
        raise ValueError("elastic strain potential does not declare the root model")
    for model_id in child_model_ids:
        if model_id not in model_ids:
            model_ids.append(model_id)
    potential["model_ids"] = model_ids
    potential["applicability_derivation"] = {
        "kind": "fixed_fractional_voigt_strain_children",
        "root_model_id": root_model_id,
        "derived_model_ids": list(child_model_ids),
        "statement": "Applicability is extended only to fixed-strain children of the declared root model; potential identity and scientific qualification are unchanged.",
    }
    files = potential.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, Mapping) and isinstance(item.get("local_path"), str):
                local = Path(item["local_path"])
                if not local.is_absolute():
                    item["local_path"] = str((root_potential_path.parent / local).resolve())
    _write_json(output_path, potential)
    return potential


def prepare_lammps_elastic(request_path: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Materialize the 13-point static LAMMPS elasticity preparation.

    The returned manifest is preparation evidence only.  Native jobs remain
    unsubmitted and result files are intentionally absent until the caller
    runs the existing runner lifecycle.
    """

    request_file = Path(request_path).resolve()
    request = _read_json(request_file)
    if request.get("schema") != _REQUEST_SCHEMA:
        raise ValueError(f"elastic prepare request schema must be {_REQUEST_SCHEMA}")
    plan_id = _required_text(request.get("plan_id"), "plan_id")
    if any(char in plan_id for char in ("/", "\\")):
        raise ValueError("elastic prepare plan_id must not contain path separators")
    model_version = _required_text(request.get("model_version"), "model_version")
    strain_amplitude = _number(request.get("strain_amplitude"), "strain_amplitude", positive=True)
    timestep_ps = _number(request.get("timestep_ps"), "timestep_ps", positive=True)
    resources = request.get("resource_request")
    if not isinstance(resources, Mapping):
        raise ValueError("elastic prepare resource_request must be an object")

    root_study_path = _resolve_input_path(request_file, request.get("study_path"), "study_path")
    root_model_path = _resolve_input_path(request_file, request.get("model_path"), "model_path")
    root_potential_path = _resolve_input_path(request_file, request.get("potential_path"), "potential_path")
    root_site_path = _resolve_input_path(request_file, request.get("site_path"), "site_path")
    root_study = load_study(root_study_path)
    root_model = read_model_artifacts(root_model_path)
    root_potential = _read_json(root_potential_path)
    root_site = _read_json(root_site_path)
    selected = root_study.get("model")
    if not isinstance(selected, Mapping) or (
        str(selected.get("model_id")) != root_model.model_id
        or str(selected.get("version")) != root_model.version
    ):
        raise ValueError("root Study model does not select the requested root model")

    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan = plan_elastic_strains(root_model, strain_amplitude)
    points = [dict(plan["reference"]), *[dict(value) for value in plan["requests"]]]
    point_specs: list[dict[str, Any]] = []
    for point in points:
        point_id, child_model_id, child_study_id, task_id = _point_ids(
            plan_id, str(point["request_id"])
        )
        point_specs.append(
            {
                "point": point,
                "point_id": point_id,
                "child_model_id": child_model_id,
                "child_study_id": child_study_id,
                "task_id": task_id,
            }
        )

    potential_path = output / "potential.json"
    potential = _potential_copy(
        root_potential,
        root_model_id=root_model.model_id,
        root_potential_path=root_potential_path,
        child_model_ids=[str(spec["child_model_id"]) for spec in point_specs],
        output_path=potential_path,
    )
    runner = SiteRunner(SiteConfig.from_mapping(root_site))
    manifest_points: list[dict[str, Any]] = []
    for spec in point_specs:
        point = spec["point"]
        point_id = str(spec["point_id"])
        point_dir = output / point_id
        point_dir.mkdir(parents=True, exist_ok=False)
        model_dir = point_dir / "model"
        strain_record = point.get("record")
        if not isinstance(strain_record, Mapping):
            raise ValueError(f"elastic plan point {point_id} has no strain record")
        child_atoms, generated_record = voigt_strain_model(
            root_model.atoms,
            point["strain_voigt"],
            reference_model={"model_id": root_model.model_id, "version": root_model.version},
        )
        # Keep the plan's complete record while confirming the materialized
        # geometry record is the one used by the writer.
        strain_record = copy.deepcopy(dict(generated_record))
        strain_record.update(
            {
                "request_id": point["request_id"],
                "point_kind": point["kind"],
                "direction": point.get("direction"),
                "sign": point.get("sign"),
                "amplitude": point.get("amplitude", 0.0),
                "plan_id": plan_id,
            }
        )
        child_model = _materialize_model(
            root_model,
            child_atoms=child_atoms,
            strain_record=strain_record,
            model_id=str(spec["child_model_id"]),
            model_version=model_version,
            child_study_id=str(spec["child_study_id"]),
            parent_study_id=_required_text(root_study.get("study_id"), "root study_id"),
            parent_study_path=root_study_path,
            output=model_dir,
        )
        child_study = _child_study(
            root_study,
            root_model=root_model,
            root_study_path=root_study_path,
            child_model=child_model,
            child_model_path=model_dir,
            child_study_id=str(spec["child_study_id"]),
            strain_record=strain_record,
            task_id=str(spec["task_id"]),
        )
        child_study_path = point_dir / "study.json"
        _write_json(child_study_path, child_study)
        protocol = _protocol(timestep_ps=timestep_ps, strain_record=strain_record)
        protocol_path = point_dir / "protocol.json"
        _write_json(protocol_path, protocol)
        task_request = {
            "task_id": str(spec["task_id"]),
            "required_results": [],
            "resource_request": copy.deepcopy(dict(resources)),
            "elastic_strain": copy.deepcopy(strain_record),
            "root_model": _parent_model_record(root_model),
            "root_study": _parent_study_record(
                root_study, root_study_path, model_path=root_model.artifact_dir
            ),
        }
        request_point_path = point_dir / "request.json"
        _write_json(request_point_path, task_request)
        task_data = create_lammps_task(
            study_path=child_study_path,
            model_path=model_dir,
            potential_path=potential_path,
            protocol_path=protocol_path,
            site_path=root_site_path,
            request_path=request_point_path,
        )
        task_path = Path(task_data["local_workdir"]) / "task.json"
        task = load_task(task_path)
        root_model_ref, root_study_ref, child_study_ref = _task_lineage(
            root_model=root_model,
            root_study=root_study,
            root_study_path=root_study_path,
            child_study=child_study,
            child_study_path=child_study_path,
            child_model=child_model,
            child_model_path=model_dir,
        )
        task.set(
            study_file=str(child_study_path.resolve()),
            request_path=str(request_point_path.resolve()),
            elastic_strain=copy.deepcopy(strain_record),
            root_model=root_model_ref,
            root_study=root_study_ref,
            child_study=child_study_ref,
        )
        save_task(task)
        runner.prepare(task)
        result_path = task_path.parent / "result.json"
        manifest_points.append(
            {
                "point_id": point_id,
                "kind": point["kind"],
                "strain_voigt": list(strain_record["strain_voigt"]),
                "model_path": str(model_dir.resolve()),
                "study_path": str(child_study_path.resolve()),
                "task_path": str(task_path.resolve()),
                "result_path": str(result_path.resolve()),
                "protocol_path": str(protocol_path.resolve()),
                "request_path": str(request_point_path.resolve()),
                "status": task.data["status"],
            }
        )

    reference_point = manifest_points[0]
    response_request = {
        "schema": _RESPONSE_SCHEMA,
        "plan_id": plan_id,
        "voigt_order": list(VOIGT_ORDER),
        "strain_amplitude": strain_amplitude,
        "study_path": str(root_study_path.resolve()),
        "model_path": str(root_model_path.resolve()),
        "reference": {
            "task_path": reference_point["task_path"],
            "result_path": reference_point["result_path"],
            "strain_voigt": reference_point["strain_voigt"],
        },
        "samples": [
            {
                "task_path": point["task_path"],
                "result_path": point["result_path"],
                "strain_voigt": point["strain_voigt"],
            }
            for point in manifest_points[1:]
        ],
    }
    response_path = output / "response-request.json"
    _write_json(response_path, response_request)
    manifest = {
        "schema": _MANIFEST_SCHEMA,
        "plan_id": plan_id,
        "root_study": str(root_study_path.resolve()),
        "root_model": str(root_model_path.resolve()),
        "root_potential": str(root_potential_path.resolve()),
        "potential_path": str(potential_path.resolve()),
        "root_site": str(root_site_path.resolve()),
        "root_study_id": root_study["study_id"],
        "root_model_id": root_model.model_id,
        "root_model_version": root_model.version,
        "voigt_order": list(VOIGT_ORDER),
        "strain_amplitude": strain_amplitude,
        "model_version": model_version,
        "resource_request": copy.deepcopy(dict(resources)),
        "timestep_ps": timestep_ps,
        "points": manifest_points,
        "response_request_path": str(response_path.resolve()),
        "native_jobs_submitted": False,
        "production_qualification": False,
        "status": "prepared_not_submitted",
    }
    _write_json(output / "prepare-manifest.json", manifest)
    return manifest


__all__ = ["prepare_lammps_elastic"]
