"""Thin ceramic model to DeePMD/LAMMPS task adapter.

The ceramic path keeps the ABACUS collection and source model identity visible
while using the existing LAMMPS native preparation/parser.  The source model
is a non-fixture artifact; the frozen DeePMD potential is an explicitly
unqualified engineering fixture.  This module only materializes and
finalizes task records.  SiteRunner remains responsible for Slurm lifecycle.
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
import json
from pathlib import Path
import posixpath
import shutil
from typing import Any

import numpy as np

from .lammps import (
    parse_lammps_outputs,
    prepare_lammps,
    validate_lammps_model,
    validate_lammps_protocol,
)
from .md_conditions import read_md_conditions
from .md_trajectory import read_md_collection
from .modeling import read_model_artifacts
from .tasks import TaskRecord, load_task, save_task


_COLLECTION_SCHEMA = "mlcc.ceramic-dataset-collection.v1"
_TASK_SCHEMA = "mlcc.ceramic-lammps-task.v1"

_RUN0_OUTPUT_FILES = (
    "stdout.log",
    "stderr.log",
    "log.lammps",
    "dump.final",
)
_MD_OUTPUT_FILES = (
    "stdout.log",
    "stderr.log",
    "log.lammps",
    "dump.final",
    "trajectory.lammpstrj",
)


def _json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON record must contain an object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _site_record(site: Mapping[str, Any]) -> dict[str, Any]:
    """Read the explicit Slurm/LAMMPS site contract.

    The plugin is intentionally a site property.  It is retained in the task
    record and environment metadata rather than inferred from the model card.
    """

    ssh = site["ssh"]
    workspace = site["workspace"]
    runner = site["runner"]
    lammps = site["lammps"]
    if runner["selected"] != "slurm":
        raise ValueError("ceramic LAMMPS tasks require runner.selected=slurm")
    binary = str(lammps["binary"])
    version = str(lammps["version"])
    environment_script = str(lammps["environment_script"])
    plugin = lammps["plugin"]
    if not binary or not version or not environment_script:
        raise ValueError("ceramic LAMMPS site binary, version, and environment_script must be explicit")
    if plugin in (None, ""):
        raise ValueError("ceramic LAMMPS site must declare the DeepMD plugin explicitly")
    plugin = str(plugin)
    launch_prefix = lammps.get("launch_prefix", [])
    launch_arguments = lammps.get("launch_arguments", [])
    if not isinstance(launch_prefix, list) or any(not isinstance(item, str) for item in launch_prefix):
        raise ValueError("ceramic LAMMPS site launch_prefix must be a list of strings")
    if not isinstance(launch_arguments, list) or any(not isinstance(item, str) for item in launch_arguments):
        raise ValueError("ceramic LAMMPS site launch_arguments must be a list of strings")
    return {
        "ssh_alias": str(ssh["alias"]),
        "local_workspace": str(workspace["local"]),
        "remote_root": str(workspace["remote_root"]),
        "runner": "slurm",
        "binary": binary,
        "version": version,
        "environment_script": environment_script,
        "plugin": plugin,
        "launch_prefix": list(launch_prefix),
        "launch_arguments": list(launch_arguments),
    }


def _embedded_collection(card: Mapping[str, Any]) -> Mapping[str, Any]:
    """Locate the complete collection embedded by the training handoff."""

    manifest = card["dataset_manifest"]
    collection = manifest["collection"]
    if not isinstance(collection, Mapping) or collection.get("schema") != _COLLECTION_SCHEMA:
        raise ValueError("DeepMD model card must embed the complete ceramic collection")
    return collection


def _validate_card(card: Mapping[str, Any], collection: Mapping[str, Any], system_id: str) -> Mapping[str, Any]:
    if card.get("status") != "engineering_handoff":
        raise ValueError("DeepMD model card status must be engineering_handoff")
    if card.get("scientific_status") != "not_qualified":
        raise ValueError("DeepMD model card must remain scientifically unqualified")
    if card.get("engine") != "deepmd":
        raise ValueError("ceramic LAMMPS requires a DeepMD model card")
    if card.get("type_map") != collection.get("type_map"):
        raise ValueError("DeepMD model card type_map differs from ceramic collection")
    embedded = _embedded_collection(card)
    if dict(embedded) != dict(collection):
        raise ValueError("embedded ceramic collection differs from selected collection")
    collection_systems = collection["systems"]
    if not isinstance(collection_systems, list):
        raise ValueError("ceramic collection systems must be a list")
    collection_by_id = {row["system_id"]: row for row in collection_systems}
    if system_id not in collection_by_id:
        raise ValueError(f"ceramic collection has no system {system_id!r}")
    selected_card_system = card.get("system_id")
    if selected_card_system not in (None, system_id):
        raise ValueError("DeepMD model card selected system differs from request")
    frozen = card.get("frozen_model")
    if not isinstance(frozen, str) or not frozen:
        raise ValueError("DeepMD model card requires frozen_model")
    return collection_by_id[system_id]


def _resolve_card_file(card_path: Path, value: str) -> Path:
    source = Path(value).expanduser()
    return source if source.is_absolute() else (card_path.parent / source).resolve()


def _validate_source_system(
    system: Mapping[str, Any],
    collection: Mapping[str, Any],
    system_id: str,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    if system.get("system_id") != system_id:
        raise ValueError("collection system identity differs from requested system_id")
    if system.get("fixture") is not False:
        raise ValueError("ceramic source model must remain fixture=false")
    model = read_model_artifacts(system["model_path"])
    if model.metadata.get("fixture") is not False:
        raise ValueError("ceramic source model artifact must declare fixture=false")
    if (model.model_id, model.version) != (system["model_id"], system["model_version"]):
        raise ValueError("ceramic source model identity differs from collection")
    dataset_systems = system.get("dataset_systems")
    if not isinstance(dataset_systems, list) or len(dataset_systems) != 1:
        raise ValueError("ceramic LAMMPS task requires one selected dataset system")
    dataset_system = dataset_systems[0]
    frames = dataset_system.get("frames")
    if not isinstance(frames, list) or len(frames) != 1:
        raise ValueError("ceramic LAMMPS task requires one selected dataset frame")
    frame = frames[0]
    if frame.get("model_id") != model.model_id or frame.get("model_version") != model.version:
        raise ValueError("ceramic dataset frame model identity differs from source model")
    if [int(value) for value in frame["atom_ids"]] != model.atom_ids:
        raise ValueError("ceramic dataset frame atom IDs differ from source model")
    if [str(value) for value in frame["symbols"]] != [str(value) for value in model.atoms.get_chemical_symbols()]:
        raise ValueError("ceramic dataset frame elements differ from source model")
    if not np.allclose(np.asarray(frame["positions_angstrom"], dtype=float), model.atoms.get_positions(), rtol=0.0, atol=1.0e-8):
        raise ValueError("ceramic dataset frame positions differ from source model")
    if not np.allclose(np.asarray(frame["cell_angstrom"], dtype=float), model.atoms.cell.array, rtol=0.0, atol=1.0e-8):
        raise ValueError("ceramic dataset frame cell differs from source model")
    if frame.get("type_map") != collection.get("type_map"):
        raise ValueError("ceramic dataset frame type_map differs from collection")
    parent_model = {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(Path(system["model_path"]).resolve()),
        "atom_ids": model.atom_ids,
        "atom_lineage_file": model.metadata.get("atom_lineage_file"),
        "atom_lineage": copy.deepcopy(model.metadata.get("atom_lineage")),
        "parent_models": copy.deepcopy(model.metadata.get("parent_models", [])),
        "collection_parent_system_id": system.get("parent_system_id"),
        "collection_parent_mapping": copy.deepcopy(system.get("parent_mapping")),
    }
    return model, frame, parent_model


def _validate_protocol(protocol: Mapping[str, Any]) -> str:
    validate_lammps_protocol(protocol)
    kind = str(protocol["kind"])
    if kind == "run0":
        if protocol.get("purpose") != "potential_qualification":
            raise ValueError("ceramic run0 requires purpose=potential_qualification")
        if protocol.get("static_tensor") is not True:
            raise ValueError("ceramic run0 requires static_tensor=true")
        return kind
    if kind != "md":
        raise ValueError("ceramic LAMMPS protocol kind must be run0 or md")
    if "purpose" in protocol:
        raise ValueError("ceramic MD protocol must not claim a qualification purpose")
    if not isinstance(protocol.get("engineering_scope"), str) or not protocol["engineering_scope"].strip():
        raise ValueError("ceramic MD requires an explicit engineering_scope")
    if protocol.get("ensemble") != "nve":
        raise ValueError("ceramic MD engineering scope requires ensemble=nve")
    return kind


def _potential(card: Mapping[str, Any], card_path: Path, collection: Mapping[str, Any], plugin: str) -> dict[str, Any]:
    training_job_id = card["job_id"]
    training_task_id = card["training_task_id"]
    if not isinstance(training_task_id, str) or not training_task_id:
        raise ValueError("DeepMD model card training_task_id must be non-empty")
    if training_job_id in (None, ""):
        raise ValueError("DeepMD model card job_id must be present")
    source = str(card_path.resolve())
    return {
        "potential_id": f"deepmd-{training_task_id}",
        "version": str(training_job_id),
        "source": source,
        "license": "project engineering model; not distributed",
        "fixture": True,
        "production_qualification": False,
        "elements": list(collection["type_map"]),
        "element_order": list(collection["type_map"]),
        "model_ids": [str(row["model_id"]) for row in collection["systems"]],
        "units": "metal",
        "atom_style": "atomic",
        "pair_style": "deepmd frozen.pth",
        "pair_coeff": ["* * " + " ".join(str(value) for value in collection["type_map"])],
        "training_task_id": training_task_id,
        "training_job_id": training_job_id,
        "model_card": source,
        "backend": card.get("backend"),
        "model_format": card.get("format"),
        "plugin": plugin,
        "files": [{"local_path": str(_resolve_card_file(card_path, card["frozen_model"])), "filename": "frozen.pth"}],
    }


def _frame_record(system: Mapping[str, Any], frame: Mapping[str, Any], collection_path: Path) -> dict[str, Any]:
    return {
        "schema": "mlcc.ceramic-lammps-frame.v1",
        "system_id": system["system_id"],
        "model_id": system["model_id"],
        "model_version": system["model_version"],
        "source_task_id": system["task_id"],
        "source_scheduler_job_id": system["scheduler_job_id"],
        "study_id": system["study_id"],
        "case_id": system["case_id"],
        "case_role": system["case_role"],
        "fixture": False,
        "type_map": list(frame["type_map"]),
        "elements": list(frame["symbols"]),
        "atom_ids": [int(value) for value in frame["atom_ids"]],
        "positions_angstrom": copy.deepcopy(frame["positions_angstrom"]),
        "cell_angstrom": copy.deepcopy(frame["cell_angstrom"]),
        "charge": copy.deepcopy(system.get("charge")),
        "parent_mapping": copy.deepcopy(system.get("parent_mapping")),
        "collection_path": str(collection_path.resolve()),
    }


def _prepend_plugin(directory: Path, plugin: str) -> None:
    """Make the native DeepMD plugin load part of the prepared input."""

    input_path = directory / "in.lammps"
    input_text = input_path.read_text(encoding="utf-8")
    input_path.write_text(f'plugin load "{plugin}"\n' + input_text, encoding="utf-8", newline="\n")


def create_ceramic_lammps_task(
    workspace: str | Path,
    task_id: str,
    collection_path: str | Path,
    system_id: str,
    model_card_path: str | Path,
    protocol: Mapping[str, Any],
    site: Mapping[str, Any],
    resources: Mapping[str, Any],
) -> TaskRecord:
    """Materialize one selected ceramic system for a Slurm LAMMPS task."""

    if not isinstance(task_id, str) or not task_id:
        raise ValueError("ceramic LAMMPS task_id must be non-empty")
    collection_file = Path(collection_path).expanduser().resolve()
    card_file = Path(model_card_path).expanduser().resolve()
    collection = _json(collection_file)
    if collection.get("schema") != _COLLECTION_SCHEMA:
        raise ValueError("ceramic collection schema must be mlcc.ceramic-dataset-collection.v1")
    if not isinstance(collection.get("type_map"), list) or not collection["type_map"]:
        raise ValueError("ceramic collection requires a non-empty type_map")
    systems = collection.get("systems")
    if not isinstance(systems, list) or not systems:
        raise ValueError("ceramic collection systems must be a non-empty list")
    system_rows = {row.get("system_id"): row for row in systems if isinstance(row, Mapping)}
    if system_id not in system_rows:
        raise ValueError(f"ceramic collection has no system {system_id!r}")
    card = _json(card_file)
    system = _validate_card(card, collection, system_id)
    model, frame, parent_model = _validate_source_system(system, collection, system_id)
    kind = _validate_protocol(protocol)
    site_record = _site_record(site)
    if not isinstance(resources, Mapping):
        raise ValueError("ceramic LAMMPS resources must be an object")
    resources_record = dict(resources)
    if resources_record.get("ntasks") != 1:
        raise ValueError("ceramic LAMMPS resource_request.ntasks must be 1")
    if resources_record.get("gres") in (None, "") and resources_record.get("gpus") in (None, "") and resources_record.get("gpus_per_task") in (None, ""):
        raise ValueError("ceramic LAMMPS resource_request must explicitly request a GPU")

    workspace_path = Path(workspace).expanduser().resolve()
    directory = workspace_path / "tasks" / task_id
    directory.mkdir(parents=True, exist_ok=False)
    frozen_source = _resolve_card_file(card_file, card["frozen_model"])
    frozen_destination = directory / "frozen.pth"
    shutil.copyfile(frozen_source, frozen_destination)
    potential = _potential(card, card_file, collection, site_record["plugin"])
    prepare_lammps(model, directory, potential=potential, protocol=dict(protocol))
    _prepend_plugin(directory, site_record["plugin"])

    _write_json(directory / "ceramic-collection.json", collection)
    _write_json(directory / "source-system.json", dict(system))
    _write_json(directory / "model-card.json", card)
    _write_json(directory / "protocol.json", dict(protocol))
    _write_json(directory / "frame.json", _frame_record(system, frame, collection_file))

    method_set = f"lammps-{potential['potential_id']}-{potential['version']}"
    command = [
        *site_record["launch_prefix"],
        site_record["binary"],
        *site_record["launch_arguments"],
        "-in",
        "in.lammps",
        "-log",
        "log.lammps",
    ]
    remote_workdir = posixpath.join(site_record["remote_root"], "tasks", task_id)
    model_record = {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(Path(system["model_path"]).resolve()),
        "fixture": False,
        "atom_ids": model.atom_ids,
        "parent_model": parent_model,
    }
    source_record = {
        "system_id": system_id,
        "task_id": system["task_id"],
        "scheduler_job_id": system["scheduler_job_id"],
        "study_id": system["study_id"],
        "case_id": system["case_id"],
        "case_role": system["case_role"],
        "fixture": False,
        "model_id": system["model_id"],
        "model_version": system["model_version"],
        "model_path": str(Path(system["model_path"]).resolve()),
        "charge": copy.deepcopy(system.get("charge")),
        "input_electrons": copy.deepcopy(system.get("input_electrons")),
        "method": copy.deepcopy(system.get("method")),
        "method_set": system.get("method", {}).get("method_set") if isinstance(system.get("method"), Mapping) else None,
        "parent_system_id": system.get("parent_system_id"),
        "parent_mapping": copy.deepcopy(system.get("parent_mapping")),
        "source": copy.deepcopy(system.get("source")),
    }
    transfer_paths = [
        "model.data",
        "atom-map.json",
        "in.lammps",
        "method.json",
        "frozen.pth",
        "frame.json",
        "ceramic-collection.json",
        "source-system.json",
        "model-card.json",
        "protocol.json",
    ]
    collect_paths = list(_RUN0_OUTPUT_FILES if kind == "run0" else _MD_OUTPUT_FILES)
    data: dict[str, Any] = {
        "schema": _TASK_SCHEMA,
        "task_id": task_id,
        "stage": "P9" if kind == "run0" else "P10",
        "calculation": kind,
        "engine": "lammps",
        "engine_version": site_record["version"],
        "site": {**site_record, "path": None},
        "study": {
            "study_id": system["study_id"],
            "case_id": system["case_id"],
            "case_role": system["case_role"],
            "model": {
                "model_id": model.model_id,
                "version": model.version,
                "fixture": False,
                "material": model.metadata.get("material"),
                "phase_requested": model.metadata.get("phase_requested"),
            },
        },
        "study_id": system["study_id"],
        "case_id": system["case_id"],
        "case_role": system["case_role"],
        "source_system_id": system_id,
        "source": source_record,
        "model": model_record,
        "model_id": model.model_id,
        "model_version": model.version,
        "model_path": str(Path(system["model_path"]).resolve()),
        "parent_model": parent_model,
        "method_set": method_set,
        "method_path": str((directory / "method.json").resolve()),
        "potential": potential,
        "potential_file": str(card_file),
        "staged_potential_files": ["frozen.pth"],
        "model_card_path": str(card_file),
        "training_task_id": potential.get("training_task_id"),
        "training_job_id": potential.get("training_job_id"),
        "protocol": dict(protocol),
        "protocol_path": str((directory / "protocol.json").resolve()),
        "frame_path": str((directory / "frame.json").resolve()),
        "collection_path": str(collection_file),
        "collection_dataset_id": collection.get("dataset_id"),
        "source_task_id": system["task_id"],
        "source_scheduler_job_id": system["scheduler_job_id"],
        "source_method": copy.deepcopy(system.get("method")),
        "source_method_set": system.get("method", {}).get("method_set") if isinstance(system.get("method"), Mapping) else None,
        "source_charge": copy.deepcopy(system.get("charge")),
        "source_parent_mapping": copy.deepcopy(system.get("parent_mapping")),
        "production_label": False,
        "production_qualification": False,
        "scientific_qualification": False,
        "fixture": False,
        "required_results": [],
        "depends_on": [],
        "resource_request": resources_record,
        "runner": "slurm",
        "environment_script": site_record["environment_script"],
        "environment": {"LAMMPS_PLUGIN": site_record["plugin"]},
        "scheduler_job_id": None,
        "command": command,
        "local_workdir": str(directory.resolve()),
        "remote_workdir": remote_workdir,
        "transfer_paths": transfer_paths,
        "collect_paths": collect_paths,
        "status": "defined",
        "scientific_status": "not_calculated",
    }
    task = TaskRecord(data, directory / "task.json")
    task.record_event(
        "create_ceramic_lammps",
        collection_path=str(collection_file),
        system_id=system_id,
        model_card_path=str(card_file),
        result="native_inputs_written_not_submitted",
    )
    save_task(task)
    return task


def _scheduler_contract(task: TaskRecord) -> None:
    if task.data.get("engine") != "lammps":
        raise ValueError("ceramic LAMMPS finalizer requires engine=lammps")
    if task.data.get("runner") != "slurm":
        raise ValueError("ceramic LAMMPS finalizer requires runner=slurm")
    job_id = task.scheduler_job_id
    if job_id is None:
        raise ValueError("ceramic LAMMPS finalizer requires a real scheduler_job_id")
    if task.data.get("scheduler_state") != "COMPLETED" or task.data.get("status") != "COMPLETED":
        raise ValueError("ceramic LAMMPS finalizer requires scheduler_state/status COMPLETED")
    if task.data.get("exit_code") != "0:0":
        raise ValueError("ceramic LAMMPS finalizer requires Slurm exit_code=0:0")
    fields = task.data.get("scheduler_fields")
    if not isinstance(fields, Mapping):
        raise ValueError("ceramic LAMMPS finalizer requires recorded scheduler_fields")
    if fields.get("JobId") != job_id or fields.get("JobState") != "COMPLETED" or fields.get("ExitCode") != "0:0":
        raise ValueError("ceramic LAMMPS scheduler_fields differ from completed task")


def _result_metadata(task: TaskRecord, parsed: Mapping[str, Any], model: Any) -> dict[str, Any]:
    result = dict(parsed)
    protocol = dict(task.data["protocol"])
    result.update(
        {
            "task_id": task.task_id,
            "scheduler_job_id": task.scheduler_job_id,
            "scheduler_state": task.data["scheduler_state"],
            "exit_code": task.data["exit_code"],
            "runner": "slurm",
            "study_id": task.data["study_id"],
            "case_id": task.data["case_id"],
            "case_role": task.data["case_role"],
            "source_system_id": task.data["source_system_id"],
            "source_task_id": task.data["source_task_id"],
            "source_scheduler_job_id": task.data["source_scheduler_job_id"],
            "source_method": copy.deepcopy(task.data.get("source_method")),
            "source_method_set": task.data.get("source_method_set"),
            "collection_path": task.data["collection_path"],
            "collection_dataset_id": task.data["collection_dataset_id"],
            "frame_path": task.data["frame_path"],
            "model_path": task.data["model_path"],
            "method_set": task.data["method_set"],
            "parent_model": copy.deepcopy(task.data["parent_model"]),
            "source": copy.deepcopy(task.data["source"]),
            "source_charge": copy.deepcopy(task.data["source_charge"]),
            "source_parent_mapping": copy.deepcopy(task.data["source_parent_mapping"]),
            "protocol": protocol,
            "potential": copy.deepcopy(parsed["potential"]),
            "production_label": False,
            "production_qualification": False,
            "scientific_qualification": False,
            "fixture": model.metadata["fixture"],
            "model_card_path": task.data["model_card_path"],
            "training_task_id": task.data["training_task_id"],
            "training_job_id": task.data.get("training_job_id"),
            "scientific_status": (
                "evaluated_ceramic_potential_candidate"
                if protocol["kind"] == "run0"
                else "executed_ceramic_engineering_md"
            ),
        }
    )
    if protocol["kind"] == "md":
        result["sampling_equilibrium_qualified"] = False
    return result


def finalize_ceramic_lammps_task(task_file: str | Path) -> dict[str, Any]:
    """Attach a native Slurm result and, for MD, the common collection views."""

    task = load_task(task_file)
    _scheduler_contract(task)
    directory = Path(task_file).resolve().parent
    snapshot_collection = _json(directory / "ceramic-collection.json")
    snapshot_card = _json(directory / "model-card.json")
    snapshot_system = _validate_card(snapshot_card, snapshot_collection, task.data["source_system_id"])
    if snapshot_system["model_id"] != task.data["model_id"] or snapshot_system["model_version"] != task.data["model_version"]:
        raise ValueError("ceramic task model identity differs from saved collection")
    if task.data["fixture"] is not False or task.data["model"]["fixture"] is not False:
        raise ValueError("ceramic task source model must remain fixture=false")
    model = read_model_artifacts(task.data["model_path"])
    if model.metadata.get("fixture") is not False:
        raise ValueError("ceramic finalizer source model must remain fixture=false")
    validate_lammps_model(model, directory)
    parsed = parse_lammps_outputs(directory)
    if parsed["engine_version"] != task.data["engine_version"]:
        raise ValueError("native LAMMPS engine version differs from site declaration")
    if (parsed["model_id"], parsed["version"]) != (task.data["model_id"], task.data["model_version"]):
        raise ValueError("native LAMMPS result model identity differs from ceramic task")
    if parsed["protocol"] != task.data["protocol"]:
        raise ValueError("native LAMMPS result protocol differs from ceramic task")
    if parsed["potential"] != task.data["potential"]:
        raise ValueError("native LAMMPS result potential differs from ceramic task")
    result = _result_metadata(task, parsed, model)
    result_path = directory / "result.json"
    _write_json(result_path, result)
    task.set(scientific_status=result["scientific_status"], result_file=str(result_path))
    collect_paths = list(task.data["collect_paths"])
    if "result.json" not in collect_paths:
        collect_paths.append("result.json")
    task.set(collect_paths=collect_paths)
    task.record_event("finalize_ceramic_lammps", result_file=str(result_path), scientific_status=result["scientific_status"])
    save_task(task)

    if task.data["protocol"]["kind"] == "md":
        collection = read_md_collection(directory)
        collection_path = directory / "md-collection.json"
        _write_json(collection_path, collection)
        conditions = read_md_conditions(collection_path)
        conditions_path = directory / "md-conditions.json"
        _write_json(conditions_path, conditions)
        result["md_collection_path"] = str(collection_path)
        result["md_conditions_path"] = str(conditions_path)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        collect_paths = list(task.data["collect_paths"])
        for name in ("md-collection.json", "md-conditions.json"):
            if name not in collect_paths:
                collect_paths.append(name)
        task.set(
            result_file=str(result_path),
            md_collection_file=str(collection_path),
            md_conditions_file=str(conditions_path),
            collect_paths=collect_paths,
        )
        task.record_event(
            "finalize_ceramic_md",
            md_collection_file=str(collection_path),
            md_conditions_file=str(conditions_path),
            sampling_equilibrium_qualified=False,
        )
        save_task(task)
    return result


__all__ = ["create_ceramic_lammps_task", "finalize_ceramic_lammps_task"]
