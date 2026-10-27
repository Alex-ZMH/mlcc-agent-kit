"""Thin reader and input contract for native LAMMPS unwrapped MD tracks.

The existing MD trajectory remains the wrapped ``x y z`` dump.  This module
only handles the separately requested ``xu yu zu`` dump; it never reconstructs
unwrapped coordinates from wrapped positions or image-free data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from ase.calculators.lammps import Prism

from .lammps import _finite_row, _integer_token, _prism_from_lammps_bounds


_UNWRAPPED_FILENAME = "trajectory.unwrapped.lammpstrj"
_UNWRAPPED_COLUMNS = ["id", "type", "xu", "yu", "zu"]
_UNWRAPPED_SCHEMA = "mlcc.md-unwrapped-trajectory.v1"


def validate_unwrapped_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate the optional native unwrapped-output switch only."""

    if "unwrapped_trajectory" not in protocol:
        return
    value = protocol["unwrapped_trajectory"]
    if not isinstance(value, bool):
        raise ValueError("LAMMPS protocol unwrapped_trajectory must be boolean")
    if value and str(protocol["kind"]) != "md":
        raise ValueError("LAMMPS unwrapped_trajectory is supported only for md protocols")


def unwrapped_input_commands(protocol: Mapping[str, Any]) -> list[str]:
    """Return the native dump definition and its post-run cleanup command."""

    validate_unwrapped_protocol(protocol)
    if protocol.get("unwrapped_trajectory") is not True:
        return []
    dump_every = int(protocol["dump_every"])
    return [
        f"dump trajectory_unwrapped all custom {dump_every} {_UNWRAPPED_FILENAME} id type xu yu zu",
        "dump_modify trajectory_unwrapped sort id format float %.16g",
        "undump trajectory_unwrapped",
    ]


def unwrapped_output_files(protocol: Mapping[str, Any]) -> list[str]:
    """Return the requested native output names."""

    validate_unwrapped_protocol(protocol)
    return [_UNWRAPPED_FILENAME] if protocol.get("unwrapped_trajectory") is True else []


def _method_task_binding(
    directory: Path,
    task: Mapping[str, Any],
    method: Mapping[str, Any],
    atom_map: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], Path, Path]:
    protocol = method["protocol"]
    validate_unwrapped_protocol(protocol)
    if protocol.get("unwrapped_trajectory") is not True:
        raise ValueError("native unwrapped reader requires protocol unwrapped_trajectory=true")
    if task.get("engine") != "lammps" or task.get("calculation") != "md":
        raise ValueError("native unwrapped reader requires an LAMMPS md task")
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        raise ValueError("native unwrapped reader requires saved native COMPLETED/0:0")
    if task.get("runner") != "slurm" or not task.get("scheduler_job_id"):
        raise ValueError("native unwrapped reader requires a saved Slurm job identity")
    if method.get("engine") != "lammps" or method.get("units") != "metal" or method.get("atom_style") != "atomic":
        raise ValueError("native unwrapped reader requires LAMMPS metal atomic method")
    if task.get("protocol") != protocol:
        raise ValueError("native unwrapped task protocol differs from method")
    for identity in ("model_id", "model_version"):
        if task[identity] != method["model_id" if identity == "model_id" else "version"]:
            raise ValueError("native unwrapped task/model identity differs from method")
    model_record = task["model"]
    if (model_record["model_id"], model_record["version"]) != (method["model_id"], method["version"]):
        raise ValueError("native unwrapped task model record differs from method")
    if (atom_map["model_id"], atom_map["version"]) != (method["model_id"], method["version"]):
        raise ValueError("native unwrapped atom map identity differs from method")
    if "source_cell_angstrom" not in atom_map or "lammps_prism" not in atom_map:
        raise ValueError("native unwrapped atom map requires source cell and LAMMPS Prism")
    source_cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    if source_cell.shape != (3, 3) or not np.all(np.isfinite(source_cell)):
        raise ValueError("native unwrapped atom map source cell must be a finite 3x3 matrix")
    if abs(float(np.linalg.det(source_cell))) <= 1.0e-12:
        raise ValueError("native unwrapped atom map source cell must have non-zero volume")
    source_prism = Prism(source_cell, pbc=True, reduce_cell=False)
    if not np.allclose(
        np.asarray(source_prism.get_lammps_prism(), dtype=float),
        np.asarray(atom_map["lammps_prism"], dtype=float),
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("native unwrapped atom map Prism differs from source cell")
    entries = sorted(atom_map["atoms"], key=lambda entry: int(entry["source_index"]))
    if [int(entry["source_index"]) for entry in entries] != list(range(len(entries))):
        raise ValueError("native unwrapped atom map source indices are not stable source order")
    expected_source_ids = [int(entry["source_atom_id"]) for entry in entries]
    if [int(value) for value in atom_map["source_atom_ids"]] != expected_source_ids:
        raise ValueError("native unwrapped atom map source IDs are inconsistent")
    if len(expected_source_ids) != len(set(expected_source_ids)):
        raise ValueError("native unwrapped atom map contains duplicate source atom IDs")
    if "atom_ids" in model_record and [int(value) for value in model_record["atom_ids"]] != expected_source_ids:
        raise ValueError("native unwrapped task model atom IDs differ from atom map")
    native_ids = [int(entry["lammps_id"]) for entry in entries]
    if sorted(native_ids) != list(range(1, len(native_ids) + 1)):
        raise ValueError("native unwrapped atom map native IDs are not stable 1-based IDs")
    input_path = directory / "in.lammps"
    output_path = directory / _UNWRAPPED_FILENAME
    for filename in ("task.json", "method.json", "atom-map.json"):
        (directory / filename).stat()
    input_path.stat()
    output_path.stat()
    method_files = method["files"]
    recorded_file = method_files.get(_UNWRAPPED_FILENAME)
    if recorded_file is None or Path(str(recorded_file)).name != _UNWRAPPED_FILENAME:
        raise ValueError("native method does not record trajectory.unwrapped.lammpstrj")
    input_lines = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines()]
    expected_commands = unwrapped_input_commands(protocol)
    for command in expected_commands:
        if command not in input_lines:
            raise ValueError(f"native unwrapped input is missing command: {command}")
    return dict(protocol), entries, input_path, output_path


def _parse_frame(
    frame: Sequence[str],
    atom_map: Mapping[str, Any],
    *,
    frame_number: int,
) -> tuple[int, list[tuple[int, int, list[float]]]]:
    if len(frame) < 9:
        raise ValueError(f"native unwrapped frame {frame_number} is incomplete")
    if frame[0].strip() != "ITEM: TIMESTEP":
        raise ValueError("native unwrapped dump is missing the timestep header")
    step = _integer_token(frame[1].strip(), context="unwrapped dump timestep")
    if frame[2].strip() != "ITEM: NUMBER OF ATOMS":
        raise ValueError("native unwrapped dump is missing the atom-count header")
    count = _integer_token(frame[3].strip(), context="unwrapped dump atom count")
    if count < 1:
        raise ValueError("native unwrapped dump atom count must be positive")
    if frame[4].strip() != "ITEM: BOX BOUNDS xy xz yz pp pp pp":
        raise ValueError("native unwrapped dump box header is not triclinic p p p")
    box_rows = [_finite_row(frame[index].split(), context="unwrapped dump box") for index in range(5, 8)]
    if not np.allclose(
        np.asarray(_prism_from_lammps_bounds(box_rows), dtype=float),
        np.asarray(atom_map["lammps_prism"], dtype=float),
        rtol=0.0,
        atol=1.0e-7,
    ):
        raise ValueError("native unwrapped dump box differs from atom-map Prism cell")
    if frame[8].strip() != "ITEM: ATOMS id type xu yu zu":
        raise ValueError("native unwrapped dump columns must be id type xu yu zu")
    if len(frame) < 9 + count:
        raise ValueError(f"native unwrapped frame {frame_number} is incomplete")
    rows: list[tuple[int, int, list[float]]] = []
    for line in frame[9 : 9 + count]:
        tokens = line.split()
        if len(tokens) != 5:
            raise ValueError("native unwrapped atom row has the wrong column count")
        atom_id = _integer_token(tokens[0], context="unwrapped dump atom id")
        atom_type = _integer_token(tokens[1], context="unwrapped dump atom type")
        rows.append((atom_id, atom_type, _finite_row(tokens[2:], context="unwrapped dump atom")))
    if any(line.strip() for line in frame[9 + count :]):
        raise ValueError(f"native unwrapped frame {frame_number} has unexpected trailing data")
    return step, rows


def read_unwrapped_trajectory(
    directory: str | Path,
    task: Mapping[str, Any],
    method: Mapping[str, Any],
    atom_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Read one native ``xu yu zu`` trajectory in stable source order."""

    output = Path(directory)
    protocol, entries, input_path, trajectory_path = _method_task_binding(
        output, task, method, atom_map
    )
    text = trajectory_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "ITEM: TIMESTEP"]
    if not starts:
        raise ValueError("native unwrapped trajectory has no timestep frame")
    expected_native_ids = [int(entry["lammps_id"]) for entry in sorted(entries, key=lambda item: int(item["lammps_id"]))]
    expected_native_types = {int(entry["lammps_id"]): int(entry["type"]) for entry in entries}
    source_cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    prism = Prism(source_cell, pbc=True, reduce_cell=False)
    expected_steps = list(range(0, int(protocol["steps"]) + 1, int(protocol["dump_every"])))
    if expected_steps[-1] != int(protocol["steps"]):
        expected_steps.append(int(protocol["steps"]))
    frames: list[dict[str, Any]] = []
    previous_step: int | None = None
    for frame_number, start in enumerate(starts):
        end = starts[frame_number + 1] if frame_number + 1 < len(starts) else len(lines)
        step, rows = _parse_frame(lines[start:end], atom_map, frame_number=frame_number)
        ids = [int(row[0]) for row in rows]
        if ids != expected_native_ids:
            raise ValueError("native unwrapped dump atom IDs differ from stable native order")
        if len(set(ids)) != len(ids):
            raise ValueError("native unwrapped dump contains duplicate atom IDs")
        for atom_id, atom_type, _ in rows:
            if int(atom_type) != expected_native_types[int(atom_id)]:
                raise ValueError("native unwrapped dump atom types differ from atom map")
        if previous_step is not None and step <= previous_step:
            raise ValueError("native unwrapped trajectory steps are not strictly increasing")
        rows_by_id = {int(row[0]): row for row in rows}
        lammps_positions = np.asarray(
            [rows_by_id[int(entry["lammps_id"])][2] for entry in entries], dtype=float
        )
        source_positions = np.asarray(prism.vector_to_ase(lammps_positions, wrap=False), dtype=float)
        frames.append(
            {
                "frame_index": frame_number,
                "step": step,
                "physical_time_ps": (step * float(protocol["timestep_ps"])),
                "source_atom_ids": [int(entry["source_atom_id"]) for entry in entries],
                "positions_angstrom": source_positions.tolist(),
                "coordinate_basis": "source_cartesian",
                "native_coordinate_basis": "unwrapped_lammps_prism",
                "fixed_cell": True,
            }
        )
        previous_step = step
    if [int(frame["step"]) for frame in frames] != expected_steps:
        raise ValueError("native unwrapped trajectory steps differ from protocol dump sequence")
    if frames[0]["step"] != 0:
        raise ValueError("native unwrapped trajectory must start at native step 0")
    source_files = {
        "in.lammps": str(input_path),
        _UNWRAPPED_FILENAME: str(trajectory_path),
    }
    for filename in ("task.json", "method.json", "atom-map.json"):
        source_files[filename] = str(output / filename)
    return {
        "schema": _UNWRAPPED_SCHEMA,
        "engine": "lammps",
        "engine_version": task["engine_version"],
        "task_id": task["task_id"],
        "native_job": {
            "scheduler_job_id": task["scheduler_job_id"],
            "scheduler_state": task["scheduler_state"],
            "exit_code": task["exit_code"],
            "runner": task["runner"],
        },
        "model": {
            "model_id": method["model_id"],
            "version": method["version"],
        },
        "protocol": dict(protocol),
        "native_columns": list(_UNWRAPPED_COLUMNS),
        "frames": frames,
        "source_atom_ids": [int(entry["source_atom_id"]) for entry in entries],
        "fixed_cell": {
            "value": True,
            "source": "atom-map.json:source_cell_angstrom",
            "cell_angstrom": source_cell.tolist(),
            "lammps_prism_angstrom": [float(value) for value in atom_map["lammps_prism"]],
        },
        "input_commands": unwrapped_input_commands(protocol),
        "expected_outputs": [_UNWRAPPED_FILENAME],
        "source_files": source_files,
        "production_qualification": False,
    }


__all__ = [
    "read_unwrapped_trajectory",
    "unwrapped_input_commands",
    "unwrapped_output_files",
    "validate_unwrapped_protocol",
]
