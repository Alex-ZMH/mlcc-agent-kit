"""Stage and read immutable grain-boundary source records for a task.

The geometry model and Study are authoritative inputs.  This adapter binds
their already-produced source JSON records into a task-local directory and
does not create an engine task or consult a scheduler.
"""

from __future__ import annotations

import copy
import json
from numbers import Integral
from pathlib import Path
import shutil
from typing import Any, Mapping

from .modeling import ModelArtifacts


_SCHEMA = "mlcc.grain-task-sources.v1"
_GRAIN_TASK_FILES = {
    "grain_boundary": "grain-sources/grain-boundary.json",
    "atom_lineage": "grain-sources/atom-lineage.json",
}


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _zero(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise ValueError(f"{name} must be the explicit integer 0")


def _reference(value: Any, name: str) -> dict[str, Any]:
    reference = _mapping(value, name)
    _text(reference["model_id"], f"{name}.model_id")
    _text(reference["version"], f"{name}.version")
    reference["path"]
    reference["fixture"]
    return copy.deepcopy(dict(reference))


def _same_identity(left: Mapping[str, Any], right: Mapping[str, Any], name: str) -> None:
    if (left["model_id"], left["version"]) != (right["model_id"], right["version"]):
        raise ValueError(f"{name} model identity differs")
    if "fixture" in left and "fixture" in right and left["fixture"] != right["fixture"]:
        raise ValueError(f"{name} fixture identity differs")


def _zero_charge_contract(value: Any, name: str) -> None:
    contract = _mapping(value, name)
    _zero(contract["parent_charge_state"], f"{name}.parent_charge_state")
    _zero(contract["charge_state"], f"{name}.charge_state")


def _resolved_source_path(value: Any, name: str) -> Path:
    return Path(_text(value, name)).resolve()


def _validate_study_file_identity(study: Mapping[str, Any], study_file: str | Path) -> None:
    source_path = Path(study_file)
    source_study = _mapping(
        json.loads(source_path.read_text(encoding="utf-8")),
        "Study source file",
    )
    for key in ("study_id", "case_id", "case_role", "parent_study_id"):
        if source_study[key] != study[key]:
            raise ValueError(f"Study source {key} differs from supplied Study")
    source_model = _mapping(source_study["model"], "Study source model")
    supplied_model = _mapping(study["model"], "Study model")
    for key in (
        "model_id",
        "version",
        "fixture",
        "material",
        "phase_requested",
        "spatial_mode",
        "dopants",
    ):
        if source_model[key] != supplied_model[key]:
            raise ValueError(f"Study source model {key} differs from supplied Study")


def _model_grain_ids(model: ModelArtifacts) -> list[int]:
    if "grain_id" not in model.atoms.arrays:
        raise ValueError("grain-boundary model must carry grain_id values")
    values = model.atoms.arrays["grain_id"]
    if len(values) != len(model.atoms):
        raise ValueError("grain-boundary model grain_id count differs from atom count")
    if values.dtype.kind not in {"i", "u"}:
        raise ValueError("grain-boundary model grain_id values must be integers")
    return [int(value) for value in values]


def _validate_lineage(
    model: ModelArtifacts,
    lineage_document: Mapping[str, Any],
) -> tuple[list[int], list[int]]:
    if lineage_document["schema"] != "mlcc.atom-lineage.v1":
        raise ValueError("grain-boundary atom lineage schema is unsupported")
    if (lineage_document["model_id"], lineage_document["version"]) != (
        model.model_id,
        model.version,
    ):
        raise ValueError("grain-boundary atom lineage model identity differs from model")
    entries = lineage_document["entries"]
    if not isinstance(entries, list):
        raise ValueError("grain-boundary atom lineage entries must be a list")
    metadata_lineage = model.metadata["atom_lineage"]
    if entries != metadata_lineage:
        raise ValueError("grain-boundary atom lineage differs from model metadata")
    atom_ids = model.atom_ids
    grain_ids = _model_grain_ids(model)
    if len(entries) != len(atom_ids):
        raise ValueError("grain-boundary atom lineage count differs from model atoms")
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ValueError(f"grain-boundary atom lineage entry {index} must be an object")
        if entry["atom_id"] != atom_ids[index]:
            raise ValueError(f"grain-boundary atom lineage atom_id differs at model index {index}")
        if entry["grain_id"] != grain_ids[index]:
            raise ValueError(f"grain-boundary atom lineage grain_id differs at model index {index}")
    return atom_ids, grain_ids


def _validate_model_and_study(
    study: Mapping[str, Any],
    model: ModelArtifacts,
    study_file: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path, Mapping[str, Any], Mapping[str, Any]]:
    _validate_study_file_identity(study, study_file)
    study_id = _text(study["study_id"], "study.study_id")
    case_id = _text(study["case_id"], "study.case_id")
    case_role = _text(study["case_role"], "study.case_role")
    parent_study_id = _text(study["parent_study_id"], "study.parent_study_id")
    study_model = _mapping(study["model"], "study.model")
    study_model_id = _text(study_model["model_id"], "study.model.model_id")
    study_model_version = _text(study_model["version"], "study.model.version")
    if (study_model_id, study_model_version) != (model.model_id, model.version):
        raise ValueError("Study model identity differs from ModelArtifacts")
    if study_model["fixture"] != model.metadata["fixture"]:
        raise ValueError("Study model fixture differs from ModelArtifacts")
    if bool(model.metadata["fixture"]) != (case_role == "engineering_fixture"):
        raise ValueError("Study case_role differs from ModelArtifacts fixture identity")
    if study_model["material"] != model.metadata["material"]:
        raise ValueError("Study model material differs from ModelArtifacts")
    if study_model["spatial_mode"] != "grain_boundary" or model.metadata["spatial_mode"] != "grain_boundary":
        raise ValueError("grain task source binding requires spatial_mode=grain_boundary")
    if study_model["dopants"] != model.metadata["dopants"]:
        raise ValueError("Study model dopants differ from ModelArtifacts")

    study_grain_boundary = _mapping(study["grain_boundary"], "study.grain_boundary")
    if study_grain_boundary["schema"] != "mlcc.grain-boundary.v1":
        raise ValueError("Study grain_boundary schema is unsupported")
    if study_grain_boundary["parent_study_id"] != parent_study_id:
        raise ValueError("Study grain_boundary parent_study_id differs from Study")

    model_parent = _reference(model.metadata["parent_model"], "model.parent_model")
    parent_models = model.metadata["parent_models"]
    if not isinstance(parent_models, list) or len(parent_models) != 1:
        raise ValueError("grain-boundary model must record exactly one parent_models entry")
    recorded_parent = _reference(parent_models[0], "model.parent_models[0]")
    _same_identity(model_parent, recorded_parent, "model parent")
    study_parent = _reference(study_grain_boundary["parent_model"], "Study grain_boundary.parent_model")
    _same_identity(model_parent, study_parent, "Study grain_boundary parent")
    if study_grain_boundary["request"]["model_id"] != model.model_id:
        raise ValueError("Study grain_boundary request model identity differs from model")
    if study_grain_boundary["request"]["version"] != model.version:
        raise ValueError("Study grain_boundary request version differs from model")

    model_phase = _text(model.metadata["phase_requested"], "model phase_requested")
    study_phase = _text(study_model["phase_requested"], "Study model phase_requested")
    phase_contract = _mapping(study_grain_boundary["phase_contract"], "Study grain_boundary.phase_contract")
    if phase_contract["parent_study_phase_requested"] != study_phase:
        raise ValueError("Study grain_boundary parent phase contract differs from Study model")
    if phase_contract["generated_model_phase_requested"] != model_phase:
        raise ValueError("Study grain_boundary generated phase contract differs from model")
    if phase_contract["match"] != (study_phase == model_phase):
        raise ValueError("Study grain_boundary phase contract match differs from phase values")
    if model.metadata["fixture"]:
        if phase_contract["status"] not in {"exact", "fixture_phase_label_difference_recorded"}:
            raise ValueError("fixture grain-boundary phase contract is unsupported")
    elif study_phase != model_phase or phase_contract["status"] != "exact":
        raise ValueError("scientific grain-boundary phase contract is not exact")

    request = _mapping(model.metadata["grain_boundary_request"], "model grain_boundary_request")
    _zero(request["parent_charge_state"], "model grain_boundary_request.parent_charge_state")
    _zero(request["charge_state"], "model grain_boundary_request.charge_state")
    _zero(model.metadata["charge_state"], "model charge_state")
    _zero_charge_contract(model.metadata["charge_contract"], "model charge_contract")
    _zero_charge_contract(study_grain_boundary["charge_contract"], "Study grain_boundary.charge_contract")
    if study_grain_boundary["charge_contract"] != model.metadata["charge_contract"]:
        raise ValueError("Study grain_boundary charge contract differs from model metadata")

    model_directory = Path(model.artifact_dir).resolve()
    structure_path = model_directory / model.metadata["structure_file"]
    study_structure_path = _resolved_source_path(study_model["source_structure"], "Study model source_structure")
    if study_structure_path != structure_path.resolve():
        raise ValueError("Study model source_structure does not match the ModelArtifacts file")
    grain_path = model_directory / "grain-boundary.json"
    lineage_path = model_directory / model.metadata["atom_lineage_file"]
    study_grain_path = _resolved_source_path(study_grain_boundary["source_file"], "Study grain_boundary.source_file")
    study_lineage_path = _resolved_source_path(
        study_grain_boundary["atom_lineage_file"], "Study grain_boundary.atom_lineage_file"
    )
    if study_grain_path != grain_path.resolve():
        raise ValueError("Study grain_boundary source_file does not match the model artifact")
    if study_lineage_path != lineage_path.resolve():
        raise ValueError("Study grain_boundary atom_lineage_file does not match the model artifact")

    grain_bytes = grain_path.read_bytes()
    lineage_bytes = lineage_path.read_bytes()
    grain_record = _mapping(json.loads(grain_bytes), "grain-boundary source record")
    lineage_document = _mapping(json.loads(lineage_bytes), "grain-boundary atom lineage")
    if grain_record["schema"] != "mlcc.grain-boundary.v1":
        raise ValueError("grain-boundary source record schema is unsupported")
    if (grain_record["model_id"], grain_record["version"]) != (model.model_id, model.version):
        raise ValueError("grain-boundary source record model identity differs from model")
    source_parent = _reference(grain_record["parent_model"], "grain-boundary source parent_model")
    _same_identity(model_parent, source_parent, "grain-boundary source parent")
    _zero_charge_contract(grain_record["charge"], "grain-boundary source charge")
    if grain_record["charge"] != model.metadata["charge_contract"]:
        raise ValueError("grain-boundary source charge differs from model metadata")
    if grain_record["request"] != model.metadata["grain_boundary_request"]:
        raise ValueError("grain-boundary source request differs from model metadata")
    if grain_record["request_original"] != model.metadata["grain_boundary_request_original"]:
        raise ValueError("grain-boundary original request differs from model metadata")
    atom_ids, grain_ids = _validate_lineage(model, lineage_document)
    grain_counts = [grain_ids.count(grain_id) for grain_id in (0, 1)]
    source_counts = grain_record["checks"]["composition_grain_atom_counts"]
    if source_counts != grain_counts:
        raise ValueError("grain-boundary source grain counts differ from model grain IDs")
    if grain_record["checks"]["composition_total_atom_count"] != len(atom_ids):
        raise ValueError("grain-boundary source atom count differs from model atoms")
    source_study_grain_boundary = _mapping(study_grain_boundary, "Study grain_boundary")
    if source_study_grain_boundary["request"] != grain_record["request"]:
        raise ValueError("Study grain_boundary request differs from source record")
    if source_study_grain_boundary["request_normalized"] != grain_record["request"]:
        raise ValueError("Study grain_boundary normalized request differs from source record")
    return (
        {
            "study_id": study_id,
            "case_id": case_id,
            "case_role": case_role,
            "parent_study_id": parent_study_id,
        },
        {
            "model_id": model.model_id,
            "version": model.version,
            "fixture": model.metadata["fixture"],
        },
        grain_path,
        lineage_path,
        model_parent,
        study_grain_boundary,
    )


def stage_grain_task_sources(
    study: Mapping[str, Any],
    model: ModelArtifacts,
    task_directory: str | Path,
    *,
    study_file: str | Path,
) -> dict[str, Any]:
    """Validate and copy the two immutable grain-boundary source records."""

    study_binding, model_binding, grain_path, lineage_path, parent_model, study_grain_boundary = (
        _validate_model_and_study(study, model, study_file)
    )
    model_atom_ids = model.atom_ids
    model_grain_ids = _model_grain_ids(model)
    task_root = Path(task_directory).resolve()
    destination_root = task_root / "grain-sources"
    destination_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(grain_path, task_root / _GRAIN_TASK_FILES["grain_boundary"])
    shutil.copyfile(lineage_path, task_root / _GRAIN_TASK_FILES["atom_lineage"])
    return {
        "schema": _SCHEMA,
        "study": study_binding,
        "model": model_binding,
        "parent_model": copy.deepcopy(parent_model),
        "atom_ids": list(model_atom_ids),
        "grain_ids": list(model_grain_ids),
        "original_sources": {
            "study_file": str(Path(study_file).resolve()),
            "model_directory": str(Path(model.artifact_dir).resolve()),
            "grain_boundary": str(grain_path.resolve()),
            "atom_lineage": str(lineage_path.resolve()),
        },
        "study_grain_boundary": copy.deepcopy(dict(study_grain_boundary)),
        "task_files": copy.deepcopy(_GRAIN_TASK_FILES),
        "transfer_paths": list(_GRAIN_TASK_FILES.values()),
    }


def _validate_read_binding(
    binding: Mapping[str, Any],
    *,
    study_id: str,
    model_id: str,
    model_version: str,
    atom_ids: list[int],
) -> tuple[dict[str, Any], dict[str, Any], list[int], list[int]]:
    if binding["schema"] != _SCHEMA:
        raise ValueError("grain task source binding schema is unsupported")
    study_binding = _mapping(binding["study"], "grain task source binding.study")
    model_binding = _mapping(binding["model"], "grain task source binding.model")
    if study_binding["study_id"] != study_id:
        raise ValueError("grain task source binding study_id differs from task")
    if (model_binding["model_id"], model_binding["version"]) != (model_id, model_version):
        raise ValueError("grain task source binding model identity differs from task")
    if any(isinstance(value, bool) or not isinstance(value, Integral) for value in atom_ids):
        raise ValueError("task atom_ids must be integers")
    binding_atom_ids = binding["atom_ids"]
    if not isinstance(binding_atom_ids, list):
        raise ValueError("grain task source binding atom_ids must be a list")
    if any(isinstance(value, bool) or not isinstance(value, Integral) for value in binding_atom_ids):
        raise ValueError("grain task source binding atom_ids must be integers")
    if binding_atom_ids != atom_ids:
        raise ValueError("grain task source binding atom_ids differ from task")
    binding_grain_ids = binding["grain_ids"]
    if not isinstance(binding_grain_ids, list):
        raise ValueError("grain task source binding grain_ids must be a list")
    if any(isinstance(value, bool) or not isinstance(value, Integral) for value in binding_grain_ids):
        raise ValueError("grain task source binding grain_ids must be integers")
    grain_ids = list(binding_grain_ids)
    if len(grain_ids) != len(atom_ids):
        raise ValueError("grain task source binding grain_ids count differs from atom_ids")
    if binding["task_files"] != _GRAIN_TASK_FILES:
        raise ValueError("grain task source binding task_files are unsupported")
    if binding["transfer_paths"] != list(_GRAIN_TASK_FILES.values()):
        raise ValueError("grain task source binding transfer_paths are unsupported")
    return dict(study_binding), dict(model_binding), atom_ids, grain_ids


def read_grain_task_sources(
    task_directory: str | Path,
    binding: Mapping[str, Any],
    *,
    study_id: str,
    model_id: str,
    model_version: str,
    atom_ids: list[int],
) -> dict[str, Any]:
    """Read only task-local grain source copies and validate their binding."""

    expected_atom_ids_input = list(atom_ids)

    study_binding, model_binding, expected_atom_ids, expected_grain_ids = _validate_read_binding(
        binding,
        study_id=study_id,
        model_id=model_id,
        model_version=model_version,
        atom_ids=expected_atom_ids_input,
    )
    task_root = Path(task_directory).resolve()
    grain_path = task_root / _GRAIN_TASK_FILES["grain_boundary"]
    lineage_path = task_root / _GRAIN_TASK_FILES["atom_lineage"]
    grain_boundary = json.loads(grain_path.read_text(encoding="utf-8"))
    atom_lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    grain_record = _mapping(grain_boundary, "task grain-boundary source record")
    lineage_document = _mapping(atom_lineage, "task grain-boundary atom lineage")
    if grain_record["schema"] != "mlcc.grain-boundary.v1":
        raise ValueError("task grain-boundary source record schema is unsupported")
    if (grain_record["model_id"], grain_record["version"]) != (
        model_binding["model_id"],
        model_binding["version"],
    ):
        raise ValueError("task grain-boundary source model identity differs from binding")
    parent_model = _reference(binding["parent_model"], "grain task source binding.parent_model")
    source_parent = _reference(grain_record["parent_model"], "task grain-boundary parent_model")
    _same_identity(parent_model, source_parent, "task grain-boundary parent")
    study_grain_boundary = _mapping(binding["study_grain_boundary"], "grain task source binding.study_grain_boundary")
    if study_grain_boundary["request"] != grain_record["request"]:
        raise ValueError("task Study grain_boundary request differs from source record")
    if study_grain_boundary["request_normalized"] != grain_record["request"]:
        raise ValueError("task Study grain_boundary normalized request differs from source record")
    if study_grain_boundary["parent_study_id"] != study_binding["parent_study_id"]:
        raise ValueError("task Study grain_boundary parent_study_id differs from binding")
    study_parent = _reference(study_grain_boundary["parent_model"], "task Study grain_boundary.parent_model")
    if (
        study_parent["model_id"],
        study_parent["version"],
        study_parent.get("fixture"),
    ) != (
        source_parent["model_id"],
        source_parent["version"],
        source_parent.get("fixture"),
    ):
        raise ValueError("task Study grain_boundary parent identity differs from source record")
    if study_grain_boundary["charge_contract"] != grain_record["charge"]:
        raise ValueError("task Study grain_boundary charge contract differs from source record")
    if lineage_document["schema"] != "mlcc.atom-lineage.v1":
        raise ValueError("task grain-boundary atom lineage schema is unsupported")
    if (lineage_document["model_id"], lineage_document["version"]) != (
        model_binding["model_id"],
        model_binding["version"],
    ):
        raise ValueError("task grain-boundary atom lineage model identity differs from binding")
    entries = lineage_document["entries"]
    if len(entries) != len(expected_atom_ids):
        raise ValueError("task grain-boundary atom lineage count differs from binding")
    for index, entry in enumerate(entries):
        if entry["atom_id"] != expected_atom_ids[index]:
            raise ValueError(f"task grain-boundary atom_id differs at model index {index}")
        if entry["grain_id"] != expected_grain_ids[index]:
            raise ValueError(f"task grain-boundary grain_id differs at model index {index}")
    counts = [expected_grain_ids.count(grain_id) for grain_id in (0, 1)]
    if grain_record["checks"]["composition_grain_atom_counts"] != counts:
        raise ValueError("task grain-boundary source grain counts differ from binding")
    if grain_record["checks"]["composition_total_atom_count"] != len(expected_atom_ids):
        raise ValueError("task grain-boundary source atom count differs from binding")
    return {
        "binding": copy.deepcopy(dict(binding)),
        "grain_boundary": grain_boundary,
        "atom_lineage": atom_lineage,
        "source_files": {
            "grain_boundary": str(grain_path.resolve()),
            "atom_lineage": str(lineage_path.resolve()),
        },
    }


__all__ = ["stage_grain_task_sources", "read_grain_task_sources"]
