"""Direct source and element selection for accepted MLCC MD collections.

This module binds already accepted collection files to one explicit model,
potential, time protocol and element selection.  It does not parse native
LAMMPS files, create snapshots, run simulations or calculate statistics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .md_conditions import read_md_conditions


_COLLECTION_SCHEMA = "mlcc.md-collection.v1"


def _read_collection(path: Path) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["schema"] != _COLLECTION_SCHEMA:
        raise ValueError("MD source collection schema must be mlcc.md-collection.v1")
    return record


def _validate_request(
    model_id: str,
    model_version: str,
    potential_id: str,
    potential_version: str,
    elements: list[str],
) -> None:
    if any(not isinstance(value, str) or not value for value in (model_id, model_version, potential_id, potential_version)):
        raise ValueError("MD source model and potential identities must be non-empty strings")
    if not isinstance(elements, list) or not elements or any(type(value) is not str or not value for value in elements):
        raise ValueError("MD source elements must be a non-empty list of element names")
    if len(set(elements)) != len(elements):
        raise ValueError("MD source elements must be unique")


def _protocol_signature(conditions: dict[str, Any], time: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": conditions["engine"],
        "units": conditions["units"],
        "atom_style": conditions["atom_style"],
        "purpose": conditions.get("purpose"),
        "ensemble": conditions["ensemble"],
        "timestep_ps": conditions["timestep_ps"],
        "timestep_fs": conditions["timestep_fs"],
        "steps": conditions["steps"],
        "thermo_every_steps": conditions["thermo_every_steps"],
        "dump_every_steps": conditions["dump_every_steps"],
        "initial_velocity_temperature_K": conditions["temperature"]["initial_velocity_temperature_K"],
        "target_temperature_K": conditions["temperature"]["target_temperature_K"],
        "pressure_bar": conditions["pressure"]["pressure_bar"],
        "initial_step": time["initial_step"],
        "time_origin": time["origin"],
    }


def _bind_legacy_source(record: dict[str, Any]) -> None:
    """Bind selection metadata to the accepted original final-result identity."""
    legacy = record["legacy_final_result"]
    pairs = [
        (record["task_id"], legacy["task_id"], "task"),
        (record["native_job"]["scheduler_job_id"], legacy["scheduler_job_id"], "native job"),
        (record["native_job"]["scheduler_state"], legacy["scheduler_state"], "scheduler state"),
        (record["native_job"]["exit_code"], legacy["exit_code"], "exit code"),
        (record["model"]["model_id"], legacy["model_id"], "model"),
        (record["model"]["version"], legacy["version"], "model version"),
        (record["potential"]["potential_id"], legacy["potential"]["potential_id"], "potential"),
        (record["potential"]["version"], legacy["potential"]["version"], "potential version"),
        (record["lineage"]["method_set"], legacy["method_set"], "method set"),
        (record["protocol"], legacy["protocol"], "protocol"),
        (record["engine_version"], legacy["engine_version"], "engine version"),
    ]
    for selected, original, name in pairs:
        if selected != original:
            raise ValueError(f"MD collection {name} identity differs from legacy result")
    for name, source_path in legacy["source_files"].items():
        if record["source_files"][name] != source_path:
            raise ValueError(f"MD collection source file {name} differs from legacy result")


def _validate_element_mapping(record: dict[str, Any], requested: list[str]) -> dict[str, Any]:
    frames = record["trajectory"]["frames"]
    first = frames[0]
    legacy = record["legacy_final_result"]
    source_atom_ids = first["source_atom_ids"]
    lammps_atom_ids = first["lammps_atom_ids"]
    source_indices = first["source_indices"]
    frame_types = first["types"]
    positions = first["positions_angstrom"]
    legacy_atom_ids = legacy["atom_ids"]
    legacy_types = legacy["types"]
    legacy_elements = legacy["elements"]
    lengths = {
        len(source_atom_ids),
        len(lammps_atom_ids),
        len(source_indices),
        len(frame_types),
        len(positions),
        len(legacy_atom_ids),
        len(legacy_types),
        len(legacy_elements),
    }
    if len(lengths) != 1:
        raise ValueError("MD source atom mapping lengths differ between first frame and legacy result")
    if len(set(source_atom_ids)) != len(source_atom_ids) or len(set(lammps_atom_ids)) != len(lammps_atom_ids):
        raise ValueError("MD source atom mapping contains duplicate source or native IDs")
    if len(set(source_indices)) != len(source_indices):
        raise ValueError("MD source atom mapping contains duplicate frame source indices")
    if any(type(value) is not int for value in source_atom_ids + lammps_atom_ids + source_indices + frame_types + legacy_atom_ids + legacy_types):
        raise ValueError("MD source atom mapping IDs and types must be integers")
    if any(type(value) is not str or not value for value in legacy_elements):
        raise ValueError("MD legacy result element mapping is invalid")

    legacy_by_source_id = {
        atom_id: {"type": atom_type, "element": element, "legacy_index": index}
        for index, (atom_id, atom_type, element) in enumerate(zip(legacy_atom_ids, legacy_types, legacy_elements))
    }
    if set(source_atom_ids) != set(legacy_by_source_id):
        raise ValueError("MD first-frame source atom IDs differ from legacy result atom IDs")
    frame_by_source_id = {}
    for position_index, source_atom_id in enumerate(source_atom_ids):
        legacy_entry = legacy_by_source_id[source_atom_id]
        if frame_types[position_index] != legacy_entry["type"]:
            raise ValueError("MD first-frame atom types differ from legacy result source-ID mapping")
        if source_indices[position_index] != legacy_entry["legacy_index"]:
            raise ValueError("MD first-frame source index differs from legacy source order")
        frame_by_source_id[source_atom_id] = {
            "position_index": position_index,
            "source_index": source_indices[position_index],
            "lammps_id": lammps_atom_ids[position_index],
            "type": frame_types[position_index],
            "legacy_index": legacy_entry["legacy_index"],
            "element": legacy_entry["element"],
        }

    for frame in frames[1:]:
        if (
            frame["source_atom_ids"] != source_atom_ids
            or frame["lammps_atom_ids"] != lammps_atom_ids
            or frame["source_indices"] != source_indices
            or frame["types"] != frame_types
            or frame["coordinate_basis"] != first["coordinate_basis"]
        ):
            raise ValueError("MD trajectory frame atom mapping differs from the first frame")
    coordinate_bases = [frame["coordinate_basis"] for frame in frames]
    if any(basis != coordinate_bases[0] for basis in coordinate_bases[1:]):
        raise ValueError("MD trajectory coordinate basis differs between frames")

    selected: dict[str, Any] = {}
    for element in requested:
        entries = [
            entry
            for source_atom_id, entry in frame_by_source_id.items()
            if entry["element"] == element
        ]
        if not entries:
            raise ValueError(f"MD source element {element} is absent from the native element mapping")
        selected[element] = {
            "source_atom_ids": [source_atom_id for source_atom_id, entry in frame_by_source_id.items() if entry["element"] == element],
            "lammps_atom_ids": [entry["lammps_id"] for entry in entries],
            "native_atom_ids": [entry["lammps_id"] for entry in entries],
            "source_indices": [entry["source_index"] for entry in entries],
            "frame_position_indices": [entry["position_index"] for entry in entries],
            "type_ids": [entry["type"] for entry in entries],
            "first_frame": {
                "frame_index": first["frame_index"],
                "step": first["step"],
                "coordinate_basis": first["coordinate_basis"],
                "position_indices": [entry["position_index"] for entry in entries],
                "mapping_source": "trajectory.frames[0] source_atom_ids/lammps_atom_ids/source_indices/types plus legacy_final_result atom_ids/types/elements",
            },
        }
    return {
        "elements": selected,
        "atom_mapping": {
            "source": "trajectory.frames[0] and legacy_final_result",
            "coordinate_basis": first["coordinate_basis"],
            "legacy_coordinate_basis": record["legacy_final_result_coordinate_basis"],
            "coordinate_basis_relation": "trajectory and legacy result bases are retained separately",
            "coordinate_bases": coordinate_bases,
            "frame_count": len(frames),
            "frame_indices": [frame["frame_index"] for frame in frames],
        },
    }


def _replica_binding(record: dict[str, Any], conditions: dict[str, Any]) -> dict[str, Any]:
    sampling = record["sampling_metadata"]
    replica_id = sampling.get("replica_id")
    packing_seed = sampling.get("packing_seed")
    velocity_seed = conditions["temperature"]["velocity_seed"]
    return {
        "replica_id": replica_id,
        "packing_seed": packing_seed,
        "velocity_seed": velocity_seed,
        "status": "declared" if replica_id is not None else "unresolved_missing_replica_id",
    }


def select_md_sources(
    collection_paths: list[str | Path],
    *,
    model_id: str,
    model_version: str,
    potential_id: str,
    potential_version: str,
    elements: list[str],
) -> dict[str, Any]:
    """Select explicit accepted collection sources and native element indices."""

    _validate_request(model_id, model_version, potential_id, potential_version, elements)
    if not isinstance(collection_paths, list) or not collection_paths:
        raise ValueError("MD source collection_paths must be a non-empty list")

    records: list[dict[str, Any]] = []
    seen_collection_paths: set[str] = set()
    seen_source_paths: dict[str, str] = {}
    seen_tasks: dict[str, str] = {}
    seen_jobs: dict[str, str] = {}
    protocol_signature: dict[str, Any] | None = None

    for raw_path in collection_paths:
        path = Path(raw_path)
        collection_key = str(path.resolve())
        if collection_key in seen_collection_paths:
            raise ValueError(f"MD source collection path is repeated: {path}")
        seen_collection_paths.add(collection_key)
        record = _read_collection(path)
        conditions_result = read_md_conditions(path)
        _bind_legacy_source(record)
        conditions = conditions_result["conditions"]
        time = record["time"]
        if conditions["units"] != "metal" or conditions["engine"] != "lammps":
            raise ValueError("MD source selection requires LAMMPS metal collections")
        if record["model"]["model_id"] != model_id or record["model"]["version"] != model_version:
            raise ValueError("MD source model identity differs from requested model")
        if record["potential"]["potential_id"] != potential_id or record["potential"]["version"] != potential_version:
            raise ValueError("MD source potential identity differs from requested potential")
        signature = _protocol_signature(conditions, time)
        if protocol_signature is None:
            protocol_signature = signature
        elif signature != protocol_signature:
            raise ValueError("MD source time or condition protocol differs between collections")
        task_id = record["task_id"]
        scheduler_job_id = record["native_job"]["scheduler_job_id"]
        if task_id in seen_tasks:
            raise ValueError(f"MD source task_id is repeated: {task_id}")
        if scheduler_job_id in seen_jobs:
            raise ValueError(f"MD source scheduler_job_id is repeated: {scheduler_job_id}")
        seen_tasks[task_id] = str(path)
        seen_jobs[scheduler_job_id] = str(path)
        # Model/force-field files may legitimately be shared. Native trajectory,
        # log and task results must not be counted twice as independent data.
        for source_name in ("trajectory.lammpstrj", "log.lammps", "task.json", "result.json"):
            source_path = record["source_files"][source_name]
            if source_path in seen_source_paths:
                raise ValueError(f"MD source file path is repeated: {source_path}")
            seen_source_paths[source_path] = str(path)
        mapping = _validate_element_mapping(record, elements)
        replica = _replica_binding(record, conditions)
        records.append(
            {
                "collection_path": str(path),
                "source_files": dict(record["source_files"]),
                "task_id": task_id,
                "native_job": dict(record["native_job"]),
                "model": dict(record["model"]),
                "potential": dict(record["potential"]),
                "protocol": dict(record["protocol"]),
                "time": dict(record["time"]),
                "conditions": signature,
                "replica": replica,
                "mapping": mapping,
                "selection_status": "selected_for_engineering_source_binding",
            }
        )

    replica_ids = [row["replica"]["replica_id"] for row in records]
    velocity_seeds = [row["replica"]["velocity_seed"] for row in records]
    duplicate_replica_ids = len([value for value in replica_ids if value is not None]) != len(set(value for value in replica_ids if value is not None))
    duplicate_velocity_seeds = len(velocity_seeds) != len(set(velocity_seeds))
    if duplicate_replica_ids or duplicate_velocity_seeds:
        aggregation = {
            "status": "rejected_replica_aggregation",
            "qualified": False,
            "replica_ids_unique": not duplicate_replica_ids,
            "velocity_seeds_unique": not duplicate_velocity_seeds,
            "reason": "repeated replica_id or velocity_seed does not establish independent sampling; aggregation withheld",
        }
    elif any(value is None for value in replica_ids):
        aggregation = {
            "status": "unresolved",
            "qualified": False,
            "replica_ids_unique": None,
            "velocity_seeds_unique": True,
            "reason": "replica_id is not declared; no replica aggregation is published",
        }
    elif len(records) < 2:
        aggregation = {
            "status": "unresolved",
            "qualified": False,
            "replica_ids_unique": True,
            "velocity_seeds_unique": True,
            "reason": "one source is selected; independent replica aggregation is unresolved",
        }
    else:
        aggregation = {
            "status": "bound_for_replica_analysis",
            "qualified": False,
            "replica_ids_unique": True,
            "velocity_seeds_unique": True,
            "reason": "sources are bound but no replica statistic is calculated here",
        }

    return {
        "schema": "mlcc.md-source-selection.v1",
        "request": {
            "model_id": model_id,
            "model_version": model_version,
            "potential_id": potential_id,
            "potential_version": potential_version,
            "elements": list(elements),
        },
        "sources": records,
        "source_selection": {
            "status": "selected_for_engineering_source_binding",
            "source_count": len(records),
            "scientific_qualification": False,
        },
        "replica_aggregation": aggregation,
        "production_qualification": False,
    }


__all__ = ["select_md_sources"]
