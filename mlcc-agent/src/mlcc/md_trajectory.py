"""Direct collection of a fixed-format MLCC LAMMPS MD trajectory.

This module only extends the existing native output contract to a complete
sequence.  It deliberately does not calculate MSD, diffusion, equilibrium or
production statistics.  The current MLCC engineering input writes wrapped
``x y z`` coordinates and forces; the missing image flags and velocities are
reported explicitly rather than inferred.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np

from .lammps import (
    _DUMP_FIELDS,
    _THERMO_FIELDS,
    _finite_row,
    _integer_token,
    _parse_dump,
    _parse_thermo,
    _validate_native_log,
    parse_lammps_outputs,
    validate_lammps_protocol,
)


_TRAJECTORY_SCHEMA = "mlcc.md-collection.v1"


def _command_values(text: str, command: str) -> list[str]:
    pattern = re.compile(rf"^\s*{re.escape(command)}\s+([^\s#]+)")
    return [match.group(1) for line in text.splitlines() if (match := pattern.match(line))]


def _velocity_command(text: str, name: str) -> tuple[float, int]:
    pattern = re.compile(
        r"^\s*velocity\s+all\s+create\s+([^\s#]+)\s+([^\s#]+)\s+mom\s+yes\s+rot\s+no\s+dist\s+gaussian"
    )
    matches = [match.groups() for line in text.splitlines() if (match := pattern.match(line))]
    if len(matches) != 1:
        raise ValueError(f"MLCC MD {name} must contain exactly one native velocity seed command")
    temperature, seed = matches[0]
    return float(temperature), _integer_token(seed, context=f"{name} velocity seed")


def _validate_time_commands(input_text: str, log_text: str, protocol: Mapping[str, Any]) -> None:
    """Bind the native time source to the one fixed MLCC input run.

    A reset or a second run makes ``step * dt`` ambiguous, so this fixed-format
    collection rejects it and preserves the native error instead of guessing.
    """

    for name, text in (("input", input_text), ("log", log_text)):
        if _command_values(text, "units") != ["metal"]:
            raise ValueError(f"MLCC MD {name} units must be a single metal declaration")
        if _command_values(text, "atom_style") != ["atomic"]:
            raise ValueError(f"MLCC MD {name} atom_style must be a single atomic declaration")
        if re.search(r"^\s*reset_timestep\b", text, flags=re.MULTILINE):
            raise ValueError(f"MLCC MD {name} contains reset_timestep; physical time is ambiguous")
        timestep_values = _command_values(text, "timestep")
        if len(timestep_values) != 1:
            raise ValueError(f"MLCC MD {name} must contain exactly one timestep command")
        if not math.isclose(
            float(timestep_values[0]), float(protocol["timestep_ps"]), rel_tol=0.0, abs_tol=1.0e-15
        ):
            raise ValueError(f"MLCC MD {name} timestep differs from protocol timestep_ps")
        run_values = _command_values(text, "run")
        if len(run_values) != 1:
            raise ValueError(f"MLCC MD {name} must contain exactly one run command")
        if _integer_token(run_values[0], context=f"{name} run") != int(protocol["steps"]):
            raise ValueError(f"MLCC MD {name} run step count differs from protocol")
        velocity_temperature, velocity_seed = _velocity_command(text, name)
        if not math.isclose(velocity_temperature, float(protocol["temperature_K"]), rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError(f"MLCC MD {name} velocity temperature differs from protocol")
        if velocity_seed != int(protocol["seed"]):
            raise ValueError(f"MLCC MD {name} velocity seed differs from protocol")


def _parse_thermo_series(
    text: str, protocol: Mapping[str, Any], *, timestep_ps: float, first_step: int
) -> list[dict[str, Any]]:
    """Read every fixed thermo row from all native blocks."""

    # Reuse the established final-row parser for native header/final checks.
    final = _parse_thermo(text, protocol)
    fields = tuple(_THERMO_FIELDS)
    lines = text.splitlines()
    headers = [index for index, line in enumerate(lines) if tuple(line.split()) == fields]
    if not headers:
        raise ValueError("MLCC MD log.lammps is missing the requested thermo header")
    rows: list[dict[str, Any]] = []
    for header_index, header in enumerate(headers):
        block_end = headers[header_index + 1] if header_index + 1 < len(headers) else len(lines)
        for line in lines[header + 1 : block_end]:
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] == "Loop":
                break
            if len(tokens) != len(fields):
                raise ValueError("MLCC MD thermo row differs from the fixed thermo header")
            step = _integer_token(tokens[0], context="thermo step")
            values = _finite_row(tokens[1:], context="thermo")
            rows.append(
                {
                    "step": step,
                    "physical_time_ps": (step - first_step) * timestep_ps,
                    "physical_time_fs": (step - first_step) * timestep_ps * 1000.0,
                    "temp": values[0],
                    "pe": values[1],
                    "ke": values[2],
                    "etotal": values[3],
                    "press": values[4],
                }
            )
    if not rows:
        raise ValueError("MLCC MD log.lammps contains no thermo data")
    steps = [int(row["step"]) for row in rows]
    if steps[0] != first_step or any(right <= left for left, right in zip(steps, steps[1:])):
        raise ValueError("MLCC MD thermo steps are not strictly increasing from the native start")
    if int(rows[-1]["step"]) != int(final["step"]):
        raise ValueError("MLCC MD thermo sequence final step differs from native final parser")
    expected_steps = list(range(first_step, int(protocol["steps"]) + 1, int(protocol["thermo_every"])))
    if expected_steps[-1] != int(protocol["steps"]):
        expected_steps.append(int(protocol["steps"]))
    if steps != expected_steps:
        raise ValueError("MLCC MD thermo sequence has missing or conflicting native steps")
    return rows


def _parse_trajectory_frames(
    text: str,
    atom_map: Mapping[str, Any],
    *,
    timestep_ps: float,
    first_step: int,
) -> list[dict[str, Any]]:
    """Parse all frames using the established native single-frame parser."""

    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "ITEM: TIMESTEP"]
    if not starts:
        raise ValueError("MLCC MD trajectory is missing the native timestep header")
    expected_entries = sorted(atom_map["atoms"], key=lambda entry: int(entry["lammps_id"]))
    expected_ids = [int(entry["lammps_id"]) for entry in expected_entries]
    expected_types = [int(entry["type"]) for entry in expected_entries]
    expected_prism = [float(value) for value in atom_map["lammps_prism"]]
    frames: list[dict[str, Any]] = []
    previous_step: int | None = None
    for frame_number, start in enumerate(starts):
        end = starts[frame_number + 1] if frame_number + 1 < len(starts) else len(lines)
        frame = lines[start:end]
        if len(frame) < 9 + len(expected_entries):
            raise ValueError(f"MLCC MD trajectory frame {frame_number} is incomplete")
        frame_text = "\n".join(frame) + "\n"
        step, rows = _parse_dump(frame_text, atom_map)
        if previous_step is not None and step <= previous_step:
            raise ValueError("MLCC MD trajectory steps are not strictly increasing")
        data_end = 9 + len(expected_entries)
        if any(line.strip() for line in frame[data_end:]):
            raise ValueError(f"MLCC MD trajectory frame {frame_number} has unexpected trailing data")
        native_ids = [int(row[0]) for row in rows]
        native_types = [int(row[1]) for row in rows]
        if native_ids != expected_ids:
            raise ValueError("MLCC MD trajectory atom ID order differs from atom-map")
        if native_types != expected_types:
            raise ValueError("MLCC MD trajectory atom types differ from atom-map")
        box_rows = [_finite_row(frame[index].split(), context="trajectory box") for index in range(5, 8)]
        positions = [list(row[2]) for row in rows]
        forces = [list(row[3]) for row in rows]
        frames.append(
            {
                "frame_index": frame_number,
                "step": step,
                "physical_time_ps": (step - first_step) * timestep_ps,
                "physical_time_fs": (step - first_step) * timestep_ps * 1000.0,
                "time_source": "native trajectory STEP relative to first observed step; protocol timestep_ps",
                "coordinate_basis": "lammps_prism_cartesian",
                "lammps_atom_ids": native_ids,
                "source_indices": [int(entry["source_index"]) for entry in expected_entries],
                "source_atom_ids": [int(entry["source_atom_id"]) for entry in expected_entries],
                "types": native_types,
                "positions_angstrom": positions,
                "forces_eV_per_A": forces,
                "box_bounds_angstrom": box_rows,
                "lammps_prism_angstrom": expected_prism,
            }
        )
        previous_step = step
    if frames[0]["step"] != first_step:
        raise ValueError("MLCC MD trajectory does not start at the native initial step")
    return frames


def _trajectory_first_step(text: str) -> int:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "ITEM: TIMESTEP":
            if index + 1 >= len(lines):
                raise ValueError("MLCC MD trajectory has no first native timestep value")
            return _integer_token(lines[index + 1].strip(), context="trajectory initial step")
    raise ValueError("MLCC MD trajectory is missing the native timestep header")


def _compare_saved_final(saved: Mapping[str, Any], parsed: Mapping[str, Any]) -> None:
    """Ensure the old result remains the same native final record."""

    for field in ("schema", "engine", "model_id", "version", "units", "atom_style", "step"):
        if saved.get(field) != parsed.get(field):
            raise ValueError(f"MLCC MD saved result differs from native final field: {field}")
    for field in ("atom_ids", "types", "elements"):
        if saved.get(field) != parsed.get(field):
            raise ValueError(f"MLCC MD saved result differs from native final field: {field}")
    for field in ("thermo", "protocol"):
        if saved[field] != parsed[field]:
            raise ValueError(f"MLCC MD saved result differs from native final field: {field}")
    for field in ("potential_id", "version"):
        if saved["potential"][field] != parsed["potential"][field]:
            raise ValueError(f"MLCC MD saved result potential {field} differs from method")
    for field in ("energy_eV", "temperature_K", "pressure_bar"):
        if not math.isclose(float(saved[field]), float(parsed[field]), rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError(f"MLCC MD saved result differs from native final field: {field}")
    for field in ("positions_angstrom", "forces_eV_per_A", "cell_angstrom"):
        if not np.allclose(np.asarray(saved[field], dtype=float), np.asarray(parsed[field], dtype=float), rtol=0.0, atol=1.0e-12):
            raise ValueError(f"MLCC MD saved result differs from native final field: {field}")


def read_md_collection(directory: str | Path) -> dict[str, Any]:
    """Read the complete native MD collection without writing or analysing it.

    The returned ``legacy_final_result`` is loaded verbatim from ``result.json``;
    the file is never overwritten.  This function supports only the current
    ``units metal``/``atom_style atomic`` custom dump and fixed one-run input.
    """

    output = Path(directory)
    task_path = output / "task.json"
    method_path = output / "method.json"
    map_path = output / "atom-map.json"
    input_path = output / "in.lammps"
    log_path = output / "log.lammps"
    trajectory_path = output / "trajectory.lammpstrj"
    dump_path = output / "dump.final"
    result_path = output / "result.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    method = json.loads(method_path.read_text(encoding="utf-8"))
    atom_map = json.loads(map_path.read_text(encoding="utf-8"))
    saved_result = json.loads(result_path.read_text(encoding="utf-8"))
    protocol = method["protocol"]
    validate_lammps_protocol(protocol)
    if protocol.get("kind") != "md":
        raise ValueError("MLCC MD collection requires protocol kind md")
    if method.get("units") != "metal" or method.get("atom_style") != "atomic":
        raise ValueError("MLCC MD collection requires units metal and atom_style atomic")
    if method.get("production_qualification") is not False or saved_result.get("production_qualification") is not False:
        raise ValueError("MLCC MD collection production_qualification must remain false")
    if task["task_id"] != saved_result["task_id"]:
        raise ValueError("MLCC MD task and result task IDs differ")
    if task["engine"] != method["engine"] or saved_result["engine"] != method["engine"]:
        raise ValueError("MLCC MD task, method and result engines differ")
    if task["model_id"] != method["model_id"] or task["model_version"] != method["version"]:
        raise ValueError("MLCC MD task and method model identities differ")
    if saved_result["model_id"] != method["model_id"] or saved_result["version"] != method["version"]:
        raise ValueError("MLCC MD method and result model identities differ")
    if task["potential"]["potential_id"] != method["potential"]["potential_id"]:
        raise ValueError("MLCC MD task and method potential identities differ")
    if task["potential"]["version"] != method["potential"]["version"]:
        raise ValueError("MLCC MD task and method potential versions differ")
    if task["method_set"] != saved_result["method_set"]:
        raise ValueError("MLCC MD task and result method sets differ")
    if task["protocol"] != protocol:
        raise ValueError("MLCC MD task and method protocols differ")
    if task["status"] != saved_result["scheduler_state"] or task["exit_code"] != saved_result["exit_code"]:
        raise ValueError("MLCC MD task and result scheduler status differ")
    if task["runner"] != "slurm" or task["scheduler_state"] != "COMPLETED" or task["status"] != "COMPLETED" or task["exit_code"] != "0:0":
        raise ValueError("MLCC MD collection requires a completed Slurm task with exit code 0:0")
    log_text = log_path.read_text(encoding="utf-8")
    input_text = input_path.read_text(encoding="utf-8")
    engine_version = _validate_native_log(log_text)
    if task["engine_version"] != engine_version or saved_result["engine_version"] != engine_version:
        raise ValueError("MLCC MD task, result and native log engine versions differ")
    if method["potential"]["production_qualification"] is not False or task["potential"]["production_qualification"] is not False:
        raise ValueError("MLCC MD potential production_qualification must remain false")
    _validate_time_commands(input_text, log_text, protocol)
    velocity_temperature, velocity_seed = _velocity_command(input_text, "input")
    timestep_ps = float(protocol["timestep_ps"])
    trajectory_text = trajectory_path.read_text(encoding="utf-8")
    first_step = _trajectory_first_step(trajectory_text)
    if first_step != 0:
        raise ValueError("MLCC MD fixed read_data/run contract requires native initial step 0")
    thermo_rows = _parse_thermo_series(log_text, protocol, timestep_ps=timestep_ps, first_step=first_step)
    frames = _parse_trajectory_frames(
        trajectory_text,
        atom_map,
        timestep_ps=timestep_ps,
        first_step=first_step,
    )
    expected_trajectory_steps = list(range(first_step, int(protocol["steps"]) + 1, int(protocol["dump_every"])))
    if expected_trajectory_steps[-1] != int(protocol["steps"]):
        expected_trajectory_steps.append(int(protocol["steps"]))
    if [int(frame["step"]) for frame in frames] != expected_trajectory_steps:
        raise ValueError("MLCC MD trajectory sequence has missing or conflicting native steps")
    if frames[-1]["step"] != thermo_rows[-1]["step"]:
        raise ValueError("MLCC MD trajectory and thermo final steps differ")
    parsed_final = parse_lammps_outputs(output)
    _compare_saved_final(saved_result, parsed_final)
    unwrapped_trajectory = None
    if protocol.get("unwrapped_trajectory") is True:
        from .md_unwrapped import read_unwrapped_trajectory

        unwrapped_trajectory = read_unwrapped_trajectory(
            output, task, method, atom_map
        )
    if task["model"]["atom_ids"] != parsed_final["atom_ids"]:
        raise ValueError("MLCC MD task source atom IDs differ from native atom mapping")
    scheduler_job_id = saved_result["scheduler_job_id"]
    if task["scheduler_job_id"] != scheduler_job_id:
        raise ValueError("MLCC MD task and result scheduler job IDs differ")
    recorded_scheduler = task["scheduler_fields"]
    if recorded_scheduler["JobId"] != scheduler_job_id or recorded_scheduler["JobState"] != "COMPLETED" or recorded_scheduler["ExitCode"] != "0:0":
        raise ValueError("MLCC MD recorded native scheduler fields differ from completed task")
    source_files = {
        **parsed_final["source_files"],
        "task.json": str(task_path),
        "method.json": str(method_path),
        "atom-map.json": str(map_path),
        "in.lammps": str(input_path),
        "log.lammps": str(log_path),
        "trajectory.lammpstrj": str(trajectory_path),
        "dump.final": str(dump_path),
        "result.json": str(result_path),
    }
    sampling_metadata = {
        "equilibration_window": protocol.get("equilibration_window"),
        "production_window": protocol.get("production_window"),
        "replica_id": protocol.get("replica_id"),
        "packing_seed": protocol.get("packing_seed"),
    }
    missing_evidence = [
        "image_flags",
        "velocities",
    ]
    if unwrapped_trajectory is None:
        missing_evidence.append("unwrap_evidence")
    missing_evidence.extend(name for name, value in sampling_metadata.items() if value is None)
    result = {
        "schema": _TRAJECTORY_SCHEMA,
        "engine": "lammps",
        "engine_version": engine_version,
        "units": "metal",
        "atom_style": "atomic",
        "task_id": task["task_id"],
        "lineage": {
            "study_id": task["study_id"],
            "case_id": task["case_id"],
            "case_role": task["case_role"],
            "method_set": task["method_set"],
        },
        "native_job": {
            "scheduler_job_id": scheduler_job_id,
            "scheduler_state": saved_result["scheduler_state"],
            "exit_code": saved_result["exit_code"],
            "runner": task["runner"],
        },
        "model": {
            "model_id": method["model_id"],
            "version": method["version"],
            "path": task["model_path"],
        },
        "potential": {
            "potential_id": method["potential"]["potential_id"],
            "version": method["potential"]["version"],
            "source": method["potential"]["source"],
            "path_files": [str(item["filename"]) for item in method["potential"]["files"]],
        },
        "protocol": dict(protocol),
        "sampling_metadata": {
            **sampling_metadata,
            "source": "method.json protocol; null means not declared, never zero",
            "validation_status": "sampling windows and replica statistics not evaluated by MD-00",
        },
        "time": {
            "timestep_ps": timestep_ps,
            "timestep_fs": timestep_ps * 1000.0,
            "initial_step": first_step,
            "origin": "relative elapsed time since first native step",
            "source": "native trajectory/log STEP plus method.protocol.timestep_ps",
        },
        "initialization": {
            "temperature_K": velocity_temperature,
            "velocity_seed": velocity_seed,
            "source": "native velocity all create command in in.lammps and log.lammps",
        },
        "thermo": {
            "fields": list(_THERMO_FIELDS),
            "units": {"step": "native step", "temp": "K", "pe": "eV", "ke": "eV", "etotal": "eV", "press": "bar"},
            "rows": thermo_rows,
            "source": str(log_path),
        },
        "trajectory": {
            "fields": list(_DUMP_FIELDS),
            "coordinate_units": "angstrom",
            "force_units": "eV/angstrom",
            "frames": frames,
            "source": str(trajectory_path),
            "wrapped_coordinates": True,
            "image_flags": "missing",
            "velocities": "missing",
        },
        "legacy_final_result": saved_result,
        "legacy_final_result_source": str(result_path),
        "legacy_final_result_coordinate_basis": "source_cartesian",
        "source_files": source_files,
        "missing_evidence": missing_evidence,
        "unresolved": {
            "msd": (
                "image_flags are missing; native unwrapped tracks are available"
                if unwrapped_trajectory is not None
                else "image_flags and unwrapped tracks are missing"
            ),
            "diffusion": "MSD and declared sampling window are unresolved",
            "equilibrium": "sampling-window validation and equilibrium diagnostics are not implemented by MD-00",
            "replica_statistics": "replica sampling protocol is not evaluated by MD-00",
        },
        "production_qualification": False,
        "sampling_equilibrium_qualified": False,
    }
    if unwrapped_trajectory is not None:
        result["unwrapped_trajectory"] = unwrapped_trajectory
        result["source_files"]["trajectory.unwrapped.lammpstrj"] = str(
            output / "trajectory.unwrapped.lammpstrj"
        )
    return result


__all__ = ["read_md_collection"]
