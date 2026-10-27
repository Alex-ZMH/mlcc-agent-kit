"""Bind two explicit interface parents to a Study and task-local sources."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from .modeling import ModelArtifacts, read_model_artifacts


_FILES = {
    "interface": "interface-sources/layered-interface.json",
    "atom_lineage": "interface-sources/atom-lineage.json",
    "parent_a": "interface-sources/parent-a-model.json",
    "parent_b": "interface-sources/parent-b-model.json",
}


def _read(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _model_records(model: ModelArtifacts) -> tuple[dict, dict]:
    if model.metadata["spatial_mode"] != "layered_interface":
        raise ValueError("interface sources require spatial_mode=layered_interface")
    record = _read(model.artifact_dir / model.metadata["interface_file"])
    lineage = _read(model.artifact_dir / model.metadata["atom_lineage_file"])
    if record["schema"] != "mlcc.layered-interface.v1":
        raise ValueError("unsupported layered interface schema")
    for item in (record, lineage):
        if (item["model_id"], item["version"]) != (model.model_id, model.version):
            raise ValueError("interface source model identity differs")
    if record["parent_models"] != model.metadata["parent_models"]:
        raise ValueError("interface parents differ from model metadata")
    if [item["side"] for item in record["parent_models"]] != ["a", "b"]:
        raise ValueError("interface requires ordered parent sides a and b")
    if lineage["entries"] != model.metadata["atom_lineage"]:
        raise ValueError("interface atom lineage differs from model metadata")
    if record["lineage"] != lineage["entries"]:
        raise ValueError("interface record atom lineage differs from lineage file")
    if [item["atom_id"] for item in lineage["entries"]] != model.atom_ids:
        raise ValueError("interface lineage atom IDs differ from model order")
    return record, lineage


def bind_interface_study(
    model_path: str | Path, request: Mapping[str, Any], output_path: str | Path,
) -> dict[str, Any]:
    """Bind an explicitly named child Study; do not select materials or a method."""
    if request["schema"] != "mlcc.interface-study-request.v1":
        raise ValueError("unsupported interface Study request")
    model = read_model_artifacts(model_path)
    record, _ = _model_records(model)
    if model.metadata["fixture"] != (request["case_role"] == "engineering_fixture"):
        raise ValueError("interface Study fixture role differs from model")
    parents = record["parent_models"]
    refs = request["parent_study_refs"]
    if [item["side"] for item in refs] != ["a", "b"]:
        raise ValueError("parent_study_refs must explicitly identify sides a and b")
    for reference, parent in zip(refs, parents):
        study = _read(reference["path"])
        if study["study_id"] != reference["study_id"]:
            raise ValueError("parent Study identity differs from source file")
        if (study["model"]["model_id"], study["model"]["version"]) != (parent["model_id"], parent["version"]):
            raise ValueError("parent Study model differs from interface parent")
    result = {
        "schema": "mlcc.study.v1", "study_id": request["study_id"],
        "case_id": request["case_id"], "case_role": request["case_role"],
        "model": {key: copy.deepcopy(model.metadata[key]) for key in (
            "model_id", "version", "fixture", "material", "phase_requested", "spatial_mode", "dopants",
        )},
        "interface": {
            "schema": "mlcc.interface-study-binding.v1",
            "model_path": str(Path(model_path).resolve()),
            "parent_models": copy.deepcopy(parents),
            "parent_study_refs": copy.deepcopy(refs),
            "request": copy.deepcopy(record["request"]),
        },
        "conditions": copy.deepcopy(request.get("conditions")),
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    return result


def stage_interface_task_sources(
    study: Mapping[str, Any], model: ModelArtifacts, task_directory: str | Path,
    *, study_file: str | Path,
) -> dict[str, Any]:
    """Copy the geometry, atom lineage, and two original model metadata records."""
    record, lineage = _model_records(model)
    if (study["model"]["model_id"], study["model"]["version"]) != (model.model_id, model.version):
        raise ValueError("interface Study model differs from task model")
    if study["interface"]["parent_models"] != record["parent_models"] or study["interface"]["request"] != record["request"]:
        raise ValueError("interface Study construction differs from model")
    source_paths = {
        "interface": model.artifact_dir / model.metadata["interface_file"],
        "atom_lineage": model.artifact_dir / model.metadata["atom_lineage_file"],
        "parent_a": Path(record["parent_models"][0]["path"]) / "model.json",
        "parent_b": Path(record["parent_models"][1]["path"]) / "model.json",
    }
    parent_metadata = [_read(source_paths["parent_a"]), _read(source_paths["parent_b"])]
    _bind_parent_atoms(record, lineage, parent_metadata)
    directory = Path(task_directory)
    (directory / "interface-sources").mkdir()
    for name, path in source_paths.items():
        shutil.copyfile(path, directory / _FILES[name])
    return {
        "schema": "mlcc.interface-task-sources.v1",
        "study_id": study["study_id"], "model_id": model.model_id, "model_version": model.version,
        "atom_ids": model.atom_ids, "parent_models": copy.deepcopy(record["parent_models"]),
        "study_interface": copy.deepcopy(study["interface"]),
        "study_file": str(Path(study_file).resolve()),
        "original_sources": {name: str(path.resolve()) for name, path in source_paths.items()},
        "task_files": dict(_FILES), "transfer_paths": list(_FILES.values()),
    }


def _bind_parent_atoms(record: Mapping[str, Any], lineage: Mapping[str, Any], parents: list[dict]) -> None:
    by_side = {}
    for reference, parent in zip(record["parent_models"], parents):
        for field in ("model_id", "version", "fixture", "material", "phase_requested"):
            if reference[field] != parent[field]:
                raise ValueError(f"interface parent {reference['side']} {field} differs from source")
        by_side[reference["side"]] = parent
    for atom in lineage["entries"]:
        parent = by_side[atom["side"]]
        if (atom["parent_model_id"], atom["parent_model_version"]) != (parent["model_id"], parent["version"]):
            raise ValueError("interface atom parent identity differs")
        if parent["atom_ids"][atom["parent_index"]] != atom["parent_atom_id"]:
            raise ValueError("interface atom parent index/ID differs")


def read_interface_task_sources(
    task_directory: str | Path, binding: Mapping[str, Any], *, study_id: str,
    model_id: str, model_version: str, atom_ids: list[int],
) -> dict[str, Any]:
    """Consume saved task-local sources without looking for alternative parents."""
    if binding["schema"] != "mlcc.interface-task-sources.v1":
        raise ValueError("unsupported interface task sources schema")
    if (binding["study_id"], binding["model_id"], binding["model_version"], binding["atom_ids"]) != (study_id, model_id, model_version, atom_ids):
        raise ValueError("interface source binding differs from task")
    directory = Path(task_directory)
    files = {name: directory / filename for name, filename in binding["task_files"].items()}
    record, lineage = _read(files["interface"]), _read(files["atom_lineage"])
    parents = [_read(files["parent_a"]), _read(files["parent_b"])]
    for item in (record, lineage):
        if (item["model_id"], item["version"]) != (model_id, model_version):
            raise ValueError("task-local interface model identity differs")
    if record["parent_models"] != binding["parent_models"]:
        raise ValueError("task-local interface parents differ from binding")
    if record["request"] != binding["study_interface"]["request"]:
        raise ValueError("task-local interface request differs from binding")
    if [item["atom_id"] for item in lineage["entries"]] != atom_ids:
        raise ValueError("task-local interface atom order differs")
    _bind_parent_atoms(record, lineage, parents)
    if record["lineage"] != lineage["entries"]:
        raise ValueError("task-local interface atom lineage differs between source files")
    return {
        "schema": "mlcc.interface-task-provenance.v1", "study_id": study_id,
        "model_id": model_id, "model_version": model_version,
        "interface": record, "atom_lineage": lineage, "parent_models": parents,
        "source_files": {name: str(path.resolve()) for name, path in files.items()},
    }


__all__ = ["bind_interface_study", "stage_interface_task_sources", "read_interface_task_sources"]
