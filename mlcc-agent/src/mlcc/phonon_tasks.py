"""Create one explicit ABACUS SCF task from a verified Phonopy displacement.

The displacement plan is produced by :mod:`mlcc.phonons`.  This adapter binds
one selected plan entry to a new child model and child study, then delegates
native ABACUS input generation to :func:`mlcc.abacus_tasks.create_abacus_task`.
It never submits a task and never creates a scientific result.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from ase import Atoms
from ase.io import read as ase_read

from .abacus_tasks import create_abacus_task
from .modeling import ModelArtifacts, read_model_artifacts, write_model_artifacts
from .phonons import load_phonon_displacement_plan
from .tasks import load_task, save_task


TASK_STAGE = "P7"
DERIVATION_SCHEMA = "mlcc.model-derivation.v1"
CHILD_SOURCE_ROLE = "generated_child_reference"


def _json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _resolved(path: str | Path) -> Path:
    return Path(path).resolve()


def _under(base: Path, relative: str, name: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError(f"{name} must be a non-empty relative path")
    path = (base / relative).resolve()
    if path != base and base not in path.parents:
        raise ValueError(f"{name} escapes the phonon plan directory")
    return path


def _model_ref(model: ModelArtifacts) -> dict[str, str]:
    return {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(model.artifact_dir.resolve()),
    }


def _parent_dopants(parent: ModelArtifacts) -> tuple[dict[str, Any], Path]:
    file_name = parent.metadata.get("dopants_file", "dopants.json")
    if not isinstance(file_name, str) or not file_name:
        raise ValueError("parent model dopants_file must be a non-empty string")
    path = parent.artifact_dir / file_name
    document = _json(path)
    if document.get("model_id") != parent.model_id or document.get("version") != parent.version:
        raise ValueError("parent dopants.json identity differs from model.json")
    metadata_dopants = parent.metadata.get("dopants", [])
    if not isinstance(document.get("dopants"), list) or not isinstance(metadata_dopants, list):
        raise ValueError("parent dopants must be a JSON list")
    if document.get("dopants", []) != metadata_dopants:
        raise ValueError("parent dopants metadata differs from dopants.json")
    return document, path


def _study_model(study: Mapping[str, Any]) -> Mapping[str, Any]:
    value = study.get("model")
    if not isinstance(value, Mapping):
        raise ValueError("parent study requires a model object")
    return value


def _validate_parent_binding(parent: ModelArtifacts, study: Mapping[str, Any]) -> None:
    study_id = _text(study.get("study_id"), "parent study_id")
    selected = _study_model(study)
    if (_text(selected.get("model_id"), "parent study model_id"),
            _text(selected.get("version"), "parent study model version")) != (parent.model_id, parent.version):
        raise ValueError("parent study model identity differs from parent model")

    expected_fixture = study.get("case_role") == "engineering_fixture"
    if bool(parent.metadata.get("fixture", False)) != expected_fixture:
        raise ValueError("parent study case_role differs from parent model fixture")
    if "fixture" in study and bool(study["fixture"]) != bool(parent.metadata.get("fixture", False)):
        raise ValueError("parent study fixture differs from parent model fixture")

    for field in ("material", "phase_requested"):
        selected_value = selected.get(field)
        parent_value = parent.metadata.get(field)
        if selected_value is None or parent_value is None or str(selected_value) != str(parent_value):
            raise ValueError(f"parent study {field} differs from parent model")

    parent_binding = parent.metadata.get("study_binding")
    if parent_binding not in (None, study_id):
        raise ValueError("parent model study_binding differs from parent study")
    selected_dopants = selected.get("dopants")
    if selected_dopants is not None and selected_dopants != parent.metadata.get("dopants", []):
        raise ValueError("parent study dopants differ from parent model")


def _validate_plan_geometry(
    plan_file: Path,
    manifest: Mapping[str, Any],
    parent: ModelArtifacts,
    displacement_id: str,
) -> tuple[dict[str, Any], Atoms]:
    source_model = manifest.get("source_model")
    if not isinstance(source_model, Mapping):
        raise ValueError("phonon plan requires source_model")
    if (source_model.get("model_id"), source_model.get("version")) != (parent.model_id, parent.version):
        raise ValueError("phonon plan source_model identity differs from parent model")
    if "path" not in source_model or _resolved(source_model["path"]) != parent.artifact_dir.resolve():
        raise ValueError("phonon plan source_model path differs from parent model")
    for field in ("material", "phase_requested"):
        if source_model.get(field) != parent.metadata.get(field):
            raise ValueError(f"phonon plan source_model {field} differs from parent model")

    displacement_entries = manifest.get("displacements")
    reference = manifest.get("reference")
    if not isinstance(reference, Mapping) or not isinstance(displacement_entries, list):
        raise ValueError("phonon plan requires reference and displacement entries")
    entries = [reference, *displacement_entries]
    selected = next((entry for entry in entries if entry.get("entry_id") == displacement_id), None)
    if selected is None:
        raise ValueError(f"displacement_id {displacement_id!r} is not present in the verified phonon plan")
    if not isinstance(selected, dict):
        selected = dict(selected)
    if selected.get("atom_lineage") != reference.get("atom_lineage"):
        raise ValueError("phonon displacement entry lineage differs from the plan reference")
    plan_dir = plan_file.parent.resolve()
    structure_file = _under(plan_dir, selected.get("structure_file"), "selected structure_file")
    # load_phonon_displacement_plan has already reconstructed and verified the
    # reference plus every displacement.  Read the selected verified artifact
    # here so the child model is exactly the planner output, without a second
    # Phonopy implementation in this task adapter.
    return selected, ase_read(str(structure_file), format="extxyz", index=0)


def _lineage_with_displacement(
    lineage: list[dict[str, Any]], selected: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Annotate planner lineage with the selected displacement operation."""

    entry_id = _text(selected.get("entry_id"), "plan entry_id")
    is_reference = entry_id == "reference"
    record: dict[str, Any] = {
        "entry_id": entry_id,
        "kind": selected.get("kind"),
        "displacement_unit": None if is_reference else "angstrom",
        "displaced_atom_id": selected.get("displaced_atom_id"),
        "phonopy_atom_index": selected.get("phonopy_atom_index"),
        "vector_angstrom": copy.deepcopy(selected.get("displacement_angstrom")),
        "sign": selected.get("sign"),
    }
    target = selected.get("displaced_atom_id")
    if target is not None:
        target = int(target)
    annotated: list[dict[str, Any]] = []
    target_seen = target is None
    for item in lineage:
        child_atom_id = int(item["child_atom_id"])
        item_copy = copy.deepcopy(item)
        is_target = target is not None and child_atom_id == target
        item_copy["phonon_displacement"] = {
            **record,
            "target": is_target,
            "applied_vector_angstrom": (
                copy.deepcopy(selected.get("displacement_angstrom")) if is_target else [0.0, 0.0, 0.0]
            ),
        }
        if is_target:
            target_seen = True
        annotated.append(item_copy)
    if not target_seen:
        raise ValueError("selected phonon displacement target is absent from its atom lineage")
    return annotated


def _dopant_lineage_mapping(
    dopants: list[Any], lineage: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Map parent dopant atom IDs to child supercell IDs without relabeling them."""

    parent_to_child: dict[int, list[int]] = {}
    parent_to_lineage: dict[int, list[dict[str, Any]]] = {}
    for item in lineage:
        parent_id = item.get("parent_atom_id")
        child_id = item.get("child_atom_id")
        if isinstance(parent_id, bool) or not isinstance(parent_id, int):
            continue
        if isinstance(child_id, bool) or not isinstance(child_id, int):
            continue
        parent_to_child.setdefault(int(parent_id), []).append(int(child_id))
        parent_to_lineage.setdefault(int(parent_id), []).append(copy.deepcopy(item))

    result: list[dict[str, Any]] = []
    for dopant_index, dopant in enumerate(dopants):
        parent_ids: list[int] = []
        if isinstance(dopant, Mapping):
            raw_ids = dopant.get("atom_ids")
            if raw_ids is None:
                raw_ids = dopant.get("atom_id")
            if isinstance(raw_ids, list):
                parent_ids = [
                    int(value)
                    for value in raw_ids
                    if not isinstance(value, bool) and isinstance(value, int)
                ]
            elif not isinstance(raw_ids, bool) and isinstance(raw_ids, int):
                parent_ids = [int(raw_ids)]
        child_ids: list[int] = []
        lineage_entries: list[dict[str, Any]] = []
        for parent_id in parent_ids:
            child_ids.extend(parent_to_child.get(parent_id, []))
            lineage_entries.extend(parent_to_lineage.get(parent_id, []))
        result.append(
            {
                "dopant_index": dopant_index,
                "source_role": "parent_dopant_selection",
                "atom_id_basis": "parent_model_atom_id",
                "parent_atom_ids": parent_ids,
                "child_atom_ids": child_ids,
                "lineage_entries": lineage_entries,
            }
        )
    return result


def _child_study(
    parent_study: Mapping[str, Any],
    *,
    child_study_id: str,
    task_id: str,
    child_model_id: str,
    child_model_version: str,
    child_model_path: Path,
    parent_study_id: str,
    parent_model: ModelArtifacts,
    plan_identity: Mapping[str, Any],
    parent_dopant_selection: list[Any],
    dopant_lineage_mapping: list[dict[str, Any]],
) -> dict[str, Any]:
    value = copy.deepcopy(dict(parent_study))
    selected_model = _study_model(value)
    selected_model["model_id"] = child_model_id
    selected_model["version"] = child_model_version
    selected_model["source_structure"] = str((child_model_path / "model.extxyz").resolve())
    selected_model["dopants"] = copy.deepcopy(parent_model.metadata.get("dopants", []))
    selected_model["parent_dopant_selection"] = copy.deepcopy(parent_dopant_selection)
    selected_model["dopant_lineage_mapping"] = copy.deepcopy(dopant_lineage_mapping)
    selected_model["dopants_source_role"] = "parent_dopant_selection"
    value["study_id"] = child_study_id
    value["parent_study_id"] = parent_study_id
    value["selected_required_tasks"] = [task_id]
    value["derived_from"] = {
        "study_id": parent_study_id,
        "model_id": parent_model.model_id,
        "model_version": parent_model.version,
        "reason": "P7 phonon displacement child study",
    }
    value["phonon_displacement"] = dict(plan_identity)
    value["status"] = "phonon_displacement_child_study_not_calculated"
    return value


def _child_metadata(
    child_model: ModelArtifacts,
    parent: ModelArtifacts,
    *,
    child_study_id: str,
    parent_study_id: str,
    plan_identity: Mapping[str, Any],
    lineage: Any,
    parent_dopant_selection: list[Any],
    dopant_lineage_mapping: list[dict[str, Any]],
) -> dict[str, Any]:
    parent_ref = _model_ref(parent)
    source_original_file = parent.metadata.get("source_original_file")
    source_original_path = None
    if isinstance(source_original_file, str) and source_original_file.strip():
        original = Path(source_original_file)
        source_original_path = str(
            (original if original.is_absolute() else parent.artifact_dir / original).resolve()
        )
    parent_source_ref = {
        "model_id": parent.model_id,
        "version": parent.version,
        "artifact_dir": str(parent.artifact_dir.resolve()),
        "parent_artifact_dir": str(parent.artifact_dir.resolve()),
        "source_path": parent.metadata.get("source_path"),
        "source_structure_file": parent.metadata.get("source_structure_file"),
        "source_original_file": source_original_file,
        "source_original_path": source_original_path,
    }
    derivation = {
        "kind": "phonon_displacement",
        "plan_id": plan_identity["plan_id"],
        "plan_version": plan_identity["plan_version"],
        "manifest_path": plan_identity["manifest_path"],
        "displacement_id": plan_identity["displacement_id"],
        "entry_kind": plan_identity.get("entry_kind"),
        "parent_model_id": parent.model_id,
        "parent_model_version": parent.version,
        "parent_study_id": parent_study_id,
        "parent_study_file": plan_identity["parent_study_file"],
        "displaced_atom_id": plan_identity.get("displaced_atom_id"),
        "phonopy_atom_index": plan_identity.get("phonopy_atom_index"),
        "displacement_angstrom": copy.deepcopy(plan_identity.get("displacement_angstrom")),
        "displacement_unit": plan_identity.get("displacement_unit"),
        "sign": plan_identity.get("sign"),
        "relaxation_status": "not_run",
        "production_qualified": False,
    }
    metadata = dict(child_model.metadata)
    metadata.update(
        {
            "parent_models": [parent_ref],
            "parent_model": parent_ref,
            "parent_source_ref": parent_source_ref,
            "source_structure_role": CHILD_SOURCE_ROLE,
            "source_cif_role": "generated_child_reference",
            "spatial_mode": "phonon_displacement_child",
            "derivation_schema": DERIVATION_SCHEMA,
            "derivation": derivation,
            "phonon_displacement": dict(plan_identity),
            "study_id": child_study_id,
            "study_binding": child_study_id,
            "parent_study_id": parent_study_id,
            "relaxation_status": "not_run",
            "phase_relaxed": None,
            "production_qualified": False,
            "dopants": copy.deepcopy(parent.metadata.get("dopants", [])),
            "parent_dopant_selection": copy.deepcopy(parent_dopant_selection),
            "dopants_source_role": "parent_dopant_selection",
            "dopant_atom_id_basis": "parent_model_atom_id",
            "dopant_lineage_mapping": copy.deepcopy(dopant_lineage_mapping),
            "parent_dopants_source": str((parent.artifact_dir / parent.metadata.get("dopants_file", "dopants.json")).resolve()),
            "atom_lineage_file": "atom-lineage.json",
            "atom_lineage": copy.deepcopy(lineage),
        }
    )
    return metadata


def create_phonon_task(
    *,
    plan_path: str | Path,
    study_path: str | Path,
    method_path: str | Path,
    site_path: str | Path,
    request_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Create one local fixed-cell SCF task for one verified displacement.

    The parent study and parent model are read-only inputs.  ``output_path``
    must be new; it receives ``model/``, ``study.json`` and
    ``abacus-request.json``.  The native task is written by
    :func:`create_abacus_task` under the configured local workspace and is
    left in ``defined``/unsubmitted state.
    """

    request = _json(request_path)
    required = (
        "displacement_id",
        "child_model_id",
        "child_model_version",
        "child_study_id",
        "task_id",
        "resource_request",
        "required_results",
    )
    for field in required:
        if field not in request:
            raise ValueError(f"phonon task request requires {field}")
    displacement_id = _text(request["displacement_id"], "displacement_id")
    child_model_id = _text(request["child_model_id"], "child_model_id")
    child_model_version = _text(request["child_model_version"], "child_model_version")
    child_study_id = _text(request["child_study_id"], "child_study_id")
    task_id = _text(request["task_id"], "task_id")
    if not isinstance(request["resource_request"], Mapping):
        raise ValueError("resource_request must be a JSON object")
    if not isinstance(request["required_results"], list):
        raise ValueError("required_results must be a JSON list")
    if request.get("calculation") not in (None, "scf"):
        raise ValueError("phonon displacement tasks require fixed-cell SCF")
    if request.get("input_transformation") not in (None,):
        raise ValueError("phonon displacement geometry is already materialized; input_transformation must be null")

    parent_study = _json(study_path)
    parent_study_id = _text(parent_study.get("study_id"), "parent study_id")

    # The parent study contract records model identity; the caller's plan
    # source_model path is the authoritative artifact path for this adapter.
    manifest_file = _resolved(plan_path)
    manifest = load_phonon_displacement_plan(manifest_file)
    source_model = manifest["source_model"]
    parent_model_path = source_model.get("path")
    if not isinstance(parent_model_path, str) or not parent_model_path:
        raise ValueError("phonon plan source_model.path is required")
    parent = read_model_artifacts(parent_model_path)
    _validate_parent_binding(parent, parent_study)
    if (child_model_id, child_model_version) == (parent.model_id, parent.version):
        raise ValueError("phonon child model must use a new model_id and version")
    if child_study_id == parent_study_id:
        raise ValueError("phonon child study must use a new study_id")
    selected, child_atoms = _validate_plan_geometry(manifest_file, manifest, parent, displacement_id)
    parent_dopants, parent_dopants_path = _parent_dopants(parent)
    child_lineage = _lineage_with_displacement(selected["atom_lineage"], selected)
    parent_dopant_selection = copy.deepcopy(parent_dopants["dopants"])
    dopant_lineage_mapping = _dopant_lineage_mapping(parent_dopant_selection, child_lineage)

    plan_identity = {
        "plan_id": _text(manifest.get("plan_id"), "plan_id"),
        "plan_version": _text(manifest.get("version"), "plan_version"),
        "manifest_path": str(manifest_file),
        "displacement_id": displacement_id,
        "entry_kind": selected.get("kind"),
        "displaced_atom_id": selected.get("displaced_atom_id"),
        "phonopy_atom_index": selected.get("phonopy_atom_index"),
        "displacement_angstrom": copy.deepcopy(selected.get("displacement_angstrom")),
        "displacement_unit": None if displacement_id == "reference" else "angstrom",
        "sign": selected.get("sign"),
        "parent_model_id": parent.model_id,
        "parent_model_version": parent.version,
        "parent_study_id": parent_study_id,
        "parent_study_file": str(Path(study_path).resolve()),
    }
    output = _resolved(output_path)
    if output.exists():
        raise FileExistsError(f"phonon task output directory already exists: {output}")
    site = _json(site_path)
    local_workspace = Path(site["workspace"]["local"])
    task_directory = local_workspace / "tasks" / task_id
    if task_directory.exists():
        raise FileExistsError(f"ABACUS task output directory already exists: {task_directory}")

    child_model_path = output / "model"
    child_study_path = output / "study.json"
    abacus_request_path = output / "abacus-request.json"
    child_model = write_model_artifacts(
        child_atoms,
        child_model_path,
        model_id=child_model_id,
        version=child_model_version,
        fixture=bool(parent.metadata.get("fixture", False)),
        fixture_purpose=parent.metadata.get("fixture_purpose"),
        phase_requested=str(parent.metadata["phase_requested"]),
        source_path=str(manifest_file),
        source_version=plan_identity["plan_version"],
        engineering_perturbation=copy.deepcopy(parent.metadata.get("engineering_perturbation")),
        source_atoms=child_atoms.copy(),
        material=parent.metadata.get("material"),
        source_format="phonon_displacement_plan",
        source_reference=f"{plan_identity['plan_id']}:{displacement_id}",
        selection_status="explicit_phonon_displacement_child",
        material_selection_confirmed=parent.metadata.get("material_selection_confirmed"),
        atom_lineage=child_lineage,
        scientific_status="phonon_displacement_child_not_relaxed",
    )
    child_metadata = _child_metadata(
        child_model,
        parent,
        child_study_id=child_study_id,
        parent_study_id=parent_study_id,
        plan_identity=plan_identity,
        lineage=child_lineage,
        parent_dopant_selection=parent_dopant_selection,
        dopant_lineage_mapping=dopant_lineage_mapping,
    )
    (child_model_path / "model.json").write_text(
        json.dumps(child_metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lineage_document = _json(child_model_path / "atom-lineage.json")
    lineage_document.update(
        {
            "model_id": child_model_id,
            "version": child_model_version,
            "parent_model": _model_ref(parent),
            "parent_study_id": parent_study_id,
            "source_plan": dict(plan_identity),
            "source_structure_role": CHILD_SOURCE_ROLE,
            "derivation_schema": DERIVATION_SCHEMA,
            "derivation": child_metadata["derivation"],
            "phonon_displacement": dict(plan_identity),
            "parent_dopant_selection": copy.deepcopy(parent_dopant_selection),
            "dopant_lineage_mapping": copy.deepcopy(dopant_lineage_mapping),
            "dopants_source_role": "parent_dopant_selection",
        }
    )
    (child_model_path / "atom-lineage.json").write_text(
        json.dumps(lineage_document, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    child_dopants = copy.deepcopy(parent_dopants)
    child_dopants.update(
        {
            "model_id": child_model_id,
            "version": child_model_version,
            "parent_model": _model_ref(parent),
            "parent_study_id": parent_study_id,
            "source_plan": dict(plan_identity),
            "source_dopants_file": str(parent_dopants_path.resolve()),
            "source_role": "parent_dopant_selection",
            "parent_dopant_selection": copy.deepcopy(parent_dopant_selection),
            "dopant_atom_id_basis": "parent_model_atom_id",
            "dopant_lineage_mapping": copy.deepcopy(dopant_lineage_mapping),
            "spatial_mode": "phonon_displacement_child",
        }
    )
    (child_model_path / "dopants.json").write_text(
        json.dumps(child_dopants, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    child_study = _child_study(
        parent_study,
        child_study_id=child_study_id,
        task_id=task_id,
        child_model_id=child_model_id,
        child_model_version=child_model_version,
        child_model_path=child_model_path,
        parent_study_id=parent_study_id,
        parent_model=parent,
        plan_identity=plan_identity,
        parent_dopant_selection=parent_dopant_selection,
        dopant_lineage_mapping=dopant_lineage_mapping,
    )
    child_study_path.write_text(
        json.dumps(child_study, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    abacus_request = {
        "task_id": task_id,
        "calculation": "scf",
        "input_transformation": None,
        "resource_request": copy.deepcopy(request["resource_request"]),
        "required_results": copy.deepcopy(request["required_results"]),
        "phonon_displacement": dict(plan_identity),
    }
    abacus_request_path.write_text(
        json.dumps(abacus_request, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    task_data = create_abacus_task(
        study_path=child_study_path,
        model_path=child_model_path,
        method_path=method_path,
        site_path=site_path,
        request_path=abacus_request_path,
    )
    task_file = task_directory / "task.json"
    task = load_task(task_file)
    task.set(
        stage=TASK_STAGE,
        input_transformation=None,
        phonon_displacement=dict(plan_identity),
        phonon_plan_path=str(manifest_file),
        child_model_path=str(child_model_path.resolve()),
        child_study_path=str(child_study_path.resolve()),
        abacus_request_path=str(abacus_request_path.resolve()),
    )
    task.record_event(
        "phonon_displacement_bind",
        plan_id=plan_identity["plan_id"],
        plan_version=plan_identity["plan_version"],
        displacement_id=displacement_id,
        result="fixed_cell_scf_inputs_written_not_submitted",
    )
    save_task(task)
    task_data = dict(task.data)
    task_data.update(
        output_path=str(output),
        child_model_path=str(child_model_path.resolve()),
        child_study_path=str(child_study_path.resolve()),
        abacus_request_path=str(abacus_request_path.resolve()),
        task_path=str(task_file.resolve()),
    )
    return task_data


__all__ = ["create_phonon_task"]
