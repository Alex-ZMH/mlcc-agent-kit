"""Explicit MD conditions and post-processing window selection.

The function in this module consumes an already accepted MD collection.  It
does not parse native files, submit jobs, infer a force field, or calculate
statistics.  A window selected here is an engineering post-processing
selection and carries no equilibrium or production qualification.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


_COLLECTION_SCHEMA = "mlcc.md-collection.v1"
_REQUEST_SCHEMA = "mlcc.md-window-request.v1"


def _window_value(
    value: Any,
    name: str,
    thermo_steps: list[int],
    trajectory_steps: list[int],
) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"MD {name} must be an object or null")
    if "start_step" not in value or "end_step" not in value:
        raise ValueError(f"MD {name} requires start_step and end_step")
    start = value["start_step"]
    end = value["end_step"]
    if type(start) is not int or type(end) is not int:
        raise ValueError(f"MD {name} start_step and end_step must be integers")
    if end <= start:
        raise ValueError(f"MD {name} end_step must be greater than start_step")
    if start not in thermo_steps or end not in thermo_steps or start not in trajectory_steps or end not in trajectory_steps:
        raise ValueError(f"MD {name} endpoints must be recorded thermo and trajectory steps")
    return {"start_step": start, "end_step": end}


def _window_selection(
    value: dict[str, int] | None,
    name: str,
    declaration: str,
    thermo_steps: list[int],
    trajectory_steps: list[int],
    thermo_times_ps: list[float],
    trajectory_times_ps: list[float],
    timestep_ps: float,
) -> dict[str, Any]:
    if value is None:
        return {
            "name": name,
            "status": "unresolved_missing",
            "declaration": declaration,
            "selection": None,
            "window": None,
            "start_step": None,
            "end_step": None,
            "inclusive": True,
            "thermo_indices": None,
            "trajectory_indices": None,
            "steps": None,
            "physical_time_ps": None,
            "physical_time_fs": None,
            "thermo_steps": None,
            "trajectory_steps": None,
            "thermo_physical_time_ps": None,
            "trajectory_physical_time_ps": None,
            "thermo_physical_time_fs": None,
            "trajectory_physical_time_fs": None,
            "count": None,
            "thermo_count": None,
            "trajectory_count": None,
        }
    thermo_indices = [index for index, step in enumerate(thermo_steps) if value["start_step"] <= step <= value["end_step"]]
    trajectory_indices = [index for index, step in enumerate(trajectory_steps) if value["start_step"] <= step <= value["end_step"]]
    selected_thermo_steps = [thermo_steps[index] for index in thermo_indices]
    selected_trajectory_steps = [trajectory_steps[index] for index in trajectory_indices]
    common_steps = sorted(set(selected_thermo_steps).intersection(selected_trajectory_steps))
    selection = dict(value)
    return {
        "name": name,
        "status": "selected_for_engineering_postprocessing",
        "declaration": declaration,
        "selection": selection,
        "window": selection,
        "start_step": value["start_step"],
        "end_step": value["end_step"],
        "inclusive": True,
        "thermo_indices": thermo_indices,
        "trajectory_indices": trajectory_indices,
        "steps": common_steps,
        "physical_time_ps": [step * timestep_ps for step in common_steps],
        "physical_time_fs": [step * timestep_ps * 1000.0 for step in common_steps],
        "thermo_steps": selected_thermo_steps,
        "trajectory_steps": selected_trajectory_steps,
        "thermo_physical_time_ps": [thermo_times_ps[index] for index in thermo_indices],
        "trajectory_physical_time_ps": [trajectory_times_ps[index] for index in trajectory_indices],
        "thermo_physical_time_fs": [thermo_times_ps[index] * 1000.0 for index in thermo_indices],
        "trajectory_physical_time_fs": [trajectory_times_ps[index] * 1000.0 for index in trajectory_indices],
        "count": len(common_steps),
        "thermo_count": len(thermo_indices),
        "trajectory_count": len(trajectory_indices),
    }


def _read_collection(collection_path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(collection_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["schema"] != _COLLECTION_SCHEMA:
        raise ValueError("MD collection schema must be mlcc.md-collection.v1")
    return path, record


def _validate_collection(
    record: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[int], list[int], float]:
    native_job = record["native_job"]
    if native_job["runner"] != "slurm" or native_job["scheduler_state"] != "COMPLETED" or native_job["exit_code"] != "0:0":
        raise ValueError("MD collection requires Slurm COMPLETED with exit code 0:0")
    if record["engine"] != "lammps" or record["units"] != "metal" or record["atom_style"] != "atomic":
        raise ValueError("MD collection requires the LAMMPS metal/atomic contract")
    protocol = record["protocol"]
    if protocol["kind"] != "md" or protocol["units"] != "metal":
        raise ValueError("MD collection protocol must be an explicit metal MD protocol")
    if protocol["ensemble"] not in {"nve", "nvt"}:
        raise ValueError("MD collection supports nve and nvt ensembles only")
    timestep_ps = float(protocol["timestep_ps"])
    if not math.isfinite(timestep_ps) or timestep_ps <= 0.0:
        raise ValueError("MD protocol timestep_ps must be a positive finite value")
    timestep_fs = timestep_ps * 1000.0
    collection_time = record["time"]
    if not math.isclose(float(collection_time["timestep_ps"]), timestep_ps, rel_tol=0.0, abs_tol=1.0e-15):
        raise ValueError("MD collection time timestep_ps differs from protocol")
    if not math.isclose(float(collection_time["timestep_fs"]), timestep_fs, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("MD collection time timestep_fs differs from protocol")
    if type(collection_time["initial_step"]) is not int or collection_time["initial_step"] != 0:
        raise ValueError("MD collection initial_step must be the native step 0")
    if (
        type(protocol["steps"]) is not int
        or type(protocol["thermo_every"]) is not int
        or type(protocol["dump_every"]) is not int
    ):
        raise ValueError("MD protocol steps and output intervals must be integers")
    steps_limit = protocol["steps"]
    thermo_every = protocol["thermo_every"]
    dump_every = protocol["dump_every"]
    if steps_limit <= 0 or thermo_every <= 0 or dump_every <= 0:
        raise ValueError("MD protocol steps and output intervals must be positive integers")
    rows = record["thermo"]["rows"]
    frames = record["trajectory"]["frames"]
    if not rows or not frames:
        raise ValueError("MD collection requires non-empty thermo and trajectory samples")
    thermo_steps = [row["step"] for row in rows]
    trajectory_steps = [frame["step"] for frame in frames]
    if any(type(step) is not int for step in thermo_steps + trajectory_steps):
        raise ValueError("MD thermo and trajectory steps must be integers")
    expected_thermo = list(range(0, steps_limit + 1, thermo_every))
    expected_dump = list(range(0, steps_limit + 1, dump_every))
    if expected_thermo[-1] != steps_limit:
        expected_thermo.append(steps_limit)
    if expected_dump[-1] != steps_limit:
        expected_dump.append(steps_limit)
    if thermo_steps != expected_thermo or trajectory_steps != expected_dump:
        raise ValueError("MD sample sequence does not match protocol thermo/dump intervals")
    for row in rows:
        step = row["step"]
        if not math.isclose(float(row["physical_time_ps"]), step * timestep_ps, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("MD thermo physical_time_ps differs from step and protocol timestep")
        if not math.isclose(float(row["physical_time_fs"]), step * timestep_fs, rel_tol=0.0, abs_tol=1.0e-9):
            raise ValueError("MD thermo physical_time_fs differs from step and protocol timestep")
    for frame in frames:
        step = frame["step"]
        if not math.isclose(float(frame["physical_time_ps"]), step * timestep_ps, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("MD trajectory physical_time_ps differs from step and protocol timestep")
        if not math.isclose(float(frame["physical_time_fs"]), step * timestep_fs, rel_tol=0.0, abs_tol=1.0e-9):
            raise ValueError("MD trajectory physical_time_fs differs from step and protocol timestep")
    if record["thermo"]["units"] != {"step": "native step", "temp": "K", "pe": "eV", "ke": "eV", "etotal": "eV", "press": "bar"}:
        raise ValueError("MD thermo units are not the declared metal units")
    if record["trajectory"]["coordinate_units"] != "angstrom" or record["trajectory"]["force_units"] != "eV/angstrom":
        raise ValueError("MD trajectory units are not the declared metal units")
    for name in ("task.json", "method.json", "atom-map.json", "in.lammps", "log.lammps", "trajectory.lammpstrj", "dump.final", "result.json"):
        if not isinstance(record["source_files"][name], str) or not record["source_files"][name]:
            raise ValueError(f"MD collection source_files.{name} is not bound")
    if record["production_qualification"] is not False or record["sampling_equilibrium_qualified"] is not False:
        raise ValueError("MD collection qualification flags must remain false")
    return protocol, rows, frames, thermo_steps, trajectory_steps, timestep_ps


def _window_declarations(
    record: dict[str, Any],
    request_path: Path | None,
    thermo_steps: list[int],
    trajectory_steps: list[int],
) -> tuple[dict[str, int] | None, dict[str, int] | None, dict[str, str], dict[str, Any] | None]:
    sampling = record["sampling_metadata"]
    declared_equilibration = sampling["equilibration_window"] if "equilibration_window" in sampling else None
    declared_production = sampling["production_window"] if "production_window" in sampling else None
    if request_path is None:
        equilibration = _window_value(declared_equilibration, "equilibration_window", thermo_steps, trajectory_steps)
        production = _window_value(declared_production, "production_window", thermo_steps, trajectory_steps)
        return (
            equilibration,
            production,
            {
                "equilibration_window": "collection.sampling_metadata.equilibration_window",
                "production_window": "collection.sampling_metadata.production_window",
            },
            None,
        )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request["schema"] != _REQUEST_SCHEMA:
        raise ValueError("MD window request schema must be mlcc.md-window-request.v1")
    if request["purpose"] != "engineering_postprocessing_selection":
        raise ValueError("MD window request purpose must be engineering_postprocessing_selection")
    if request["task_id"] != record["task_id"]:
        raise ValueError("MD window request task_id differs from collection")
    if request["scheduler_job_id"] != record["native_job"]["scheduler_job_id"]:
        raise ValueError("MD window request scheduler_job_id differs from collection")
    if "equilibration_window" not in request or "production_window" not in request:
        raise ValueError("MD window request requires both equilibration_window and production_window")
    equilibration = _window_value(request["equilibration_window"], "equilibration_window", thermo_steps, trajectory_steps)
    production = _window_value(request["production_window"], "production_window", thermo_steps, trajectory_steps)
    if declared_equilibration is not None and equilibration != _window_value(declared_equilibration, "equilibration_window", thermo_steps, trajectory_steps):
        raise ValueError("MD request equilibration_window conflicts with collection declaration")
    if declared_production is not None and production != _window_value(declared_production, "production_window", thermo_steps, trajectory_steps):
        raise ValueError("MD request production_window conflicts with collection declaration")
    return (
        equilibration,
        production,
        {
            "equilibration_window": "window_request.equilibration_window",
            "production_window": "window_request.production_window",
        },
        request,
    )


def read_md_conditions(collection_path: str | Path, window_request_path: str | Path | None = None) -> dict[str, Any]:
    """Validate explicit MD conditions and select declared sample windows."""

    collection_file, collection = _read_collection(collection_path)
    protocol, rows, frames, thermo_steps, trajectory_steps, timestep_ps = _validate_collection(collection)
    request_file = None if window_request_path is None else Path(window_request_path)
    equilibration, production, declarations, request = _window_declarations(collection, request_file, thermo_steps, trajectory_steps)
    if equilibration is not None and production is not None and equilibration["end_step"] >= production["start_step"]:
        raise ValueError("MD equilibration_window and production_window overlap or are reversed")
    initialization = collection["initialization"]
    if not math.isfinite(float(initialization["temperature_K"])):
        raise ValueError("MD initial velocity temperature must be finite")
    if not math.isclose(float(initialization["temperature_K"]), float(protocol["temperature_K"]), rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("MD initialization temperature differs from protocol")
    if (
        type(initialization["velocity_seed"]) is not int
        or type(protocol["seed"]) is not int
        or initialization["velocity_seed"] != protocol["seed"]
    ):
        raise ValueError("MD initialization velocity seed differs from protocol")
    ensemble = protocol["ensemble"]
    temperature = {
        "initial_velocity_temperature_K": float(initialization["temperature_K"]),
        "velocity_seed": initialization["velocity_seed"],
        "target_temperature_K": None if ensemble == "nve" else float(protocol["temperature_K"]),
        "status": "initial_velocity_temperature_only" if ensemble == "nve" else "nvt_target_temperature",
    }
    pressure_bar = protocol.get("pressure_bar")
    if pressure_bar is not None and not math.isfinite(float(pressure_bar)):
        raise ValueError("MD declared pressure_bar must be finite")
    pressure = {
        "pressure_bar": None if pressure_bar is None else float(pressure_bar),
        "status": "not_declared" if pressure_bar is None else "declared_in_protocol",
    }
    sampling = collection["sampling_metadata"]
    replica = {
        "replica_id": sampling["replica_id"] if "replica_id" in sampling else None,
        "packing_seed": sampling["packing_seed"] if "packing_seed" in sampling else None,
        "status": "declared" if sampling.get("replica_id") is not None or sampling.get("packing_seed") is not None else "not_declared",
    }
    source_files = dict(collection["source_files"])
    source = {
        "collection": str(collection_file),
        "collection_source_files": source_files,
        "window_request": None if request_file is None else str(request_file),
        "window_declarations": declarations,
    }
    return {
        "schema": "mlcc.md-conditions.v1",
        "task_id": collection["task_id"],
        "native_job": dict(collection["native_job"]),
        "lineage": dict(collection["lineage"]),
        "model": dict(collection["model"]),
        "potential": dict(collection["potential"]),
        "protocol": dict(protocol),
        "time": dict(collection["time"]),
        "conditions": {
            "engine": collection["engine"],
            "units": collection["units"],
            "atom_style": collection["atom_style"],
            "purpose": protocol.get("purpose"),
            "ensemble": ensemble,
            "temperature": temperature,
            "pressure": pressure,
            "timestep_ps": timestep_ps,
            "timestep_fs": timestep_ps * 1000.0,
            "steps": int(protocol["steps"]),
            "thermo_every_steps": int(protocol["thermo_every"]),
            "dump_every_steps": int(protocol["dump_every"]),
        },
        "samples": {
            "steps": thermo_steps if thermo_steps == trajectory_steps else None,
            "thermo_steps": thermo_steps,
            "trajectory_steps": trajectory_steps,
            "physical_time_ps": [step * timestep_ps for step in thermo_steps] if thermo_steps == trajectory_steps else None,
            "physical_time_fs": [step * timestep_ps * 1000.0 for step in thermo_steps] if thermo_steps == trajectory_steps else None,
            "thermo_physical_time_ps": [float(row["physical_time_ps"]) for row in rows],
            "trajectory_physical_time_ps": [float(frame["physical_time_ps"]) for frame in frames],
            "thermo_physical_time_fs": [float(row["physical_time_fs"]) for row in rows],
            "trajectory_physical_time_fs": [float(frame["physical_time_fs"]) for frame in frames],
            "thermo_count": len(rows),
            "trajectory_count": len(frames),
        },
        "replica": replica,
        "windows": {
            "purpose": "engineering_postprocessing_selection",
            "equilibration_window": _window_selection(
                equilibration,
                "equilibration_window",
                declarations["equilibration_window"],
                thermo_steps,
                trajectory_steps,
                [float(row["physical_time_ps"]) for row in rows],
                [float(frame["physical_time_ps"]) for frame in frames],
                timestep_ps,
            ),
            "production_window": _window_selection(
                production,
                "production_window",
                declarations["production_window"],
                thermo_steps,
                trajectory_steps,
                [float(row["physical_time_ps"]) for row in rows],
                [float(frame["physical_time_ps"]) for frame in frames],
                timestep_ps,
            ),
            "request": request,
            "qualification": {
                "equilibrium": False,
                "production": False,
                "reason": "window selection does not establish sampling or production qualification",
            },
        },
        "source": source,
        "production_qualification": False,
        "sampling_equilibrium_qualified": False,
    }


__all__ = ["read_md_conditions"]
