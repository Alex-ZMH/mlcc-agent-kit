"""Bind one generated grain-boundary model to an explicit child Study.

The geometry producer owns model construction.  This small adapter only reads
the generated model and its provenance records, copies a caller-supplied
parent Study, and writes a new child Study.  It does not create an engine
task, alter the model, or submit work.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from .modeling import read_model_artifacts


def _json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _zero(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise ValueError(f"{name} must be the explicit integer 0")


def _model_reference(value: Any, name: str) -> dict[str, Any]:
    reference = _mapping(value, name)
    return {
        "model_id": _text(reference.get("model_id"), f"{name}.model_id"),
        "version": _text(reference.get("version"), f"{name}.version"),
        "path": reference.get("path"),
        "fixture": reference.get("fixture"),
    }


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def bind_grain_boundary_study(
    parent_study_path: str | Path,
    model_path: str | Path,
    study_id: str,
    output_path: str | Path,
) -> dict[str, Any]:
    """Write a child Study for an already generated grain-boundary model.

    ``model_path`` must point to the model directory produced by
    :func:`mlcc.grain_boundaries.build_grain_boundary`.  The parent Study and
    model are read-only inputs.  The existing fixture convention permits the
    historical engineering phase label in the parent Study to differ from the
    generated model's internal fixture phase label; both values are retained
    in ``grain_boundary.phase_contract``.  Scientific (non-fixture) Studies
    require an exact phase match.
    """

    parent_study_file = Path(parent_study_path).resolve()
    model_directory = Path(model_path).resolve()
    output_file = Path(output_path).resolve()
    parent_study = _mapping(_json(parent_study_file), "parent Study")
    parent_study_id = _text(parent_study.get("study_id"), "parent Study study_id")
    child_study_id = _text(study_id, "child study_id")
    if child_study_id == parent_study_id:
        raise ValueError("child study_id must differ from parent Study study_id")

    model = read_model_artifacts(model_directory)
    metadata = model.metadata
    if metadata.get("spatial_mode") != "grain_boundary":
        raise ValueError("model must have spatial_mode=grain_boundary")

    parent_reference = _model_reference(metadata.get("parent_model"), "model parent_model")
    parent_models = metadata.get("parent_models")
    if not isinstance(parent_models, list) or len(parent_models) != 1:
        raise ValueError("grain-boundary model must record exactly one parent_models entry")
    recorded_parent = _model_reference(parent_models[0], "model parent_models[0]")
    if (recorded_parent["model_id"], recorded_parent["version"]) != (
        parent_reference["model_id"],
        parent_reference["version"],
    ):
        raise ValueError("model parent_model and parent_models identities differ")

    selected_parent_model = _mapping(parent_study.get("model"), "parent Study model")
    parent_model_id = _text(selected_parent_model.get("model_id"), "parent Study model_id")
    parent_model_version = _text(selected_parent_model.get("version"), "parent Study model version")
    if (parent_model_id, parent_model_version) != (
        parent_reference["model_id"],
        parent_reference["version"],
    ):
        raise ValueError("model parent_model identity differs from parent Study model identity")

    case_role = _text(parent_study.get("case_role"), "parent Study case_role")
    model_fixture = metadata.get("fixture")
    if not isinstance(model_fixture, bool):
        raise ValueError("grain-boundary model fixture must be explicit")
    if model_fixture != (case_role == "engineering_fixture"):
        raise ValueError("grain-boundary model fixture differs from parent Study case_role")
    if "fixture" in selected_parent_model and bool(selected_parent_model["fixture"]) != model_fixture:
        raise ValueError("parent Study model fixture differs from grain-boundary model")

    parent_material = _text(selected_parent_model.get("material"), "parent Study model material")
    model_material = _text(metadata.get("material"), "grain-boundary model material")
    if parent_material != model_material:
        raise ValueError("grain-boundary model material differs from parent Study")
    parent_phase = _text(selected_parent_model.get("phase_requested"), "parent Study model phase_requested")
    model_phase = _text(metadata.get("phase_requested"), "grain-boundary model phase_requested")
    if not model_fixture and parent_phase != model_phase:
        raise ValueError("scientific grain-boundary model phase differs from parent Study")

    request = _mapping(metadata.get("grain_boundary_request"), "model grain_boundary_request")
    _zero(request.get("parent_charge_state"), "grain_boundary_request.parent_charge_state")
    _zero(request.get("charge_state"), "grain_boundary_request.charge_state")
    _zero(metadata.get("charge_state"), "model charge_state")
    charge_contract = _mapping(metadata.get("charge_contract"), "model charge_contract")
    _zero(charge_contract.get("parent_charge_state"), "charge_contract.parent_charge_state")
    _zero(charge_contract.get("charge_state"), "charge_contract.charge_state")

    structure_file = _text(metadata.get("structure_file", "model.extxyz"), "model structure_file")
    structure_path = (model_directory / structure_file).resolve()
    if not structure_path.is_file():
        raise ValueError(f"grain-boundary model structure is missing: {structure_path}")
    lineage_file = _text(metadata.get("atom_lineage_file"), "model atom_lineage_file")
    lineage_path = (model_directory / lineage_file).resolve()
    if not lineage_path.is_file():
        raise ValueError(f"grain-boundary atom lineage is missing: {lineage_path}")
    grain_path = model_directory / "grain-boundary.json"
    if not grain_path.is_file():
        raise ValueError(f"grain-boundary source record is missing: {grain_path}")
    grain_record = _mapping(_json(grain_path), "grain-boundary source record")
    if grain_record.get("schema") != "mlcc.grain-boundary.v1":
        raise ValueError("grain-boundary source record schema is unsupported")
    if (grain_record.get("model_id"), grain_record.get("version")) != (model.model_id, model.version):
        raise ValueError("grain-boundary source record model identity differs from model")
    grain_parent = _model_reference(grain_record.get("parent_model"), "grain-boundary parent_model")
    if (grain_parent["model_id"], grain_parent["version"]) != (
        parent_reference["model_id"],
        parent_reference["version"],
    ):
        raise ValueError("grain-boundary source parent identity differs from model parent_model")
    grain_charge = _mapping(grain_record.get("charge"), "grain-boundary charge")
    _zero(grain_charge.get("parent_charge_state"), "grain-boundary charge.parent_charge_state")
    _zero(grain_charge.get("charge_state"), "grain-boundary charge.charge_state")

    child_study = copy.deepcopy(dict(parent_study))
    child_study["study_id"] = child_study_id
    child_study["parent_study_id"] = parent_study_id
    child_study["derived_from"] = {
        "study_id": parent_study_id,
        "model_id": parent_reference["model_id"],
        "model_version": parent_reference["version"],
        "parent_study_file": str(parent_study_file),
        "reason": "grain-boundary geometry child Study",
    }
    child_model = copy.deepcopy(dict(selected_parent_model))
    child_model.update(
        {
            "model_id": model.model_id,
            "version": model.version,
            "source_structure": str(structure_path),
            "fixture": model_fixture,
            "material": model_material,
            "dopants": copy.deepcopy(metadata.get("dopants", [])),
            "spatial_mode": "grain_boundary",
        }
    )
    # Preserve the parent Study's fixture phase label while recording the
    # generated model's internal fixture phase in phase_contract below.
    child_study["model"] = child_model
    child_study["selected_required_tasks"] = []
    child_study["grain_boundary"] = {
        "schema": "mlcc.grain-boundary.v1",
        "source_file": str(grain_path.resolve()),
        "atom_lineage_file": str(lineage_path),
        "parent_study_id": parent_study_id,
        "parent_model": copy.deepcopy(parent_reference),
        "request": copy.deepcopy(grain_record.get("request", request)),
        "request_normalized": copy.deepcopy(grain_record.get("request_normalized", request)),
        "charge_contract": copy.deepcopy(charge_contract),
        "phase_contract": {
            "parent_study_phase_requested": parent_phase,
            "generated_model_phase_requested": model_phase,
            "match": parent_phase == model_phase,
            "status": (
                "exact"
                if parent_phase == model_phase
                else "fixture_phase_label_difference_recorded"
            ),
        },
        "status": "engineering_geometry_only",
        "scientific_status": metadata.get(
            "scientific_status", "engineering_grain_boundary_unrelaxed_not_qualified"
        ),
        "relaxation_status": "not_run",
        "production_qualified": False,
    }
    child_study["status"] = "grain_boundary_geometry_not_calculated"
    child_study["scientific_status"] = metadata.get(
        "scientific_status", "engineering_grain_boundary_unrelaxed_not_qualified"
    )
    child_study["relaxation_status"] = "not_run"
    child_study["production_qualified"] = False

    _write_new_json(output_file, child_study)
    return child_study


__all__ = ["bind_grain_boundary_study"]
