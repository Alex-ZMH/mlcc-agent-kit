"""Opt-in native finite-temperature LAMMPS sampling output.

The ordinary MLCC LAMMPS trajectory deliberately keeps its historic fixed
columns.  This module owns the separate, explicit sampling artifact used by
the native MD producer: unwrapped coordinates, image flags, velocities and
the asymmetric nine-component centroid virial are retained verbatim for
every native frame.  No averages or tensor symmetrisation are performed
here; downstream consumers decide which production frames to select.
"""

from __future__ import annotations

from pathlib import Path
import math
from typing import Any, Mapping, Sequence

import numpy as np


_PURPOSE = "md_native_sampling"
_PROTOCOL_SCHEMA = "mlcc.lammps-md-sampling-protocol.v1"
_RESULT_SCHEMA = "mlcc.md-native-stress-source.v1"
_SAMPLING_DUMP = "sampling.lammpstrj"
_PRESSURE_SERIES = "pressure-series.dat"
_OUTPUT_FILES = (_SAMPLING_DUMP, _PRESSURE_SERIES)
_LAMMPS_SEED_MAX = 900_000_000
_COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz", "yx", "zx", "zy"]
_PRESSURE_COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz"]
_DUMP_COLUMNS = [
    "id",
    "type",
    "xu",
    "yu",
    "zu",
    "ix",
    "iy",
    "iz",
    "vx",
    "vy",
    "vz",
    *[f"c_mlcc_sampling_virial[{index}]" for index in range(1, 10)],
]


def md_sampling_enabled(protocol: Mapping[str, Any]) -> bool:
    """Return whether the explicit native sampling route is requested."""

    return isinstance(protocol, Mapping) and protocol.get("purpose") == _PURPOSE


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"MD sampling {name} must be a positive integer")
    result = int(value)
    if result <= 0:
        raise ValueError(f"MD sampling {name} must be a positive integer")
    return result


def _positive_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"MD sampling {name} must be positive and finite")
    return result


def _protocol_record(protocol: Mapping[str, Any]) -> Mapping[str, Any]:
    record = protocol.get("native_sampling")
    if not isinstance(record, Mapping):
        raise ValueError("md_native_sampling requires a native_sampling object")
    if record.get("schema") != _PROTOCOL_SCHEMA:
        raise ValueError(f"native_sampling schema must be {_PROTOCOL_SCHEMA}")
    if record.get("component_order") != _COMPONENT_ORDER:
        raise ValueError(
            "native_sampling component_order must be the explicit asymmetric nine-component order"
        )
    return record


def validate_md_sampling_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate the opt-in fixed-cell NVT sampling contract.

    The generic LAMMPS validator remains responsible for the common protocol
    fields.  This function only adds the stricter native sampling contract and
    is a no-op for protocols that do not opt into this purpose.
    """

    if not md_sampling_enabled(protocol):
        return
    if protocol.get("kind") != "md":
        raise ValueError("md_native_sampling requires protocol kind=md")
    if protocol.get("units") != "metal":
        raise ValueError("md_native_sampling requires units=metal")
    if [str(value) for value in protocol.get("boundary", [])] != ["p", "p", "p"]:
        raise ValueError("md_native_sampling requires fixed periodic boundary p p p")
    if protocol.get("ensemble") != "nvt":
        raise ValueError("md_native_sampling requires ensemble=nvt")
    if "static_tensor" in protocol and protocol["static_tensor"] is not False:
        raise ValueError("md_native_sampling does not allow static_tensor=true")
    if protocol.get("unwrapped_trajectory") is not True:
        raise ValueError("md_native_sampling requires unwrapped_trajectory=true")

    native_sampling = _protocol_record(protocol)
    equilibration_steps = _positive_int(
        native_sampling.get("equilibration_steps"), "native_sampling.equilibration_steps"
    )
    production_steps = _positive_int(
        native_sampling.get("production_steps"), "native_sampling.production_steps"
    )
    steps = _positive_int(protocol.get("steps"), "steps")
    if steps != equilibration_steps + production_steps:
        raise ValueError("md_native_sampling steps must equal equilibration plus production steps")

    dump_every = _positive_int(protocol.get("dump_every"), "dump_every")
    if equilibration_steps % dump_every != 0 or production_steps % dump_every != 0:
        raise ValueError("md_native_sampling sampling windows must lie on the dump grid")
    _positive_int(protocol.get("thermo_every"), "thermo_every")
    _positive_float(protocol.get("temperature_K"), "temperature_K")
    _positive_float(protocol.get("timestep_ps"), "timestep_ps")
    _positive_float(protocol.get("tdamp_ps"), "tdamp_ps")

    seed = _positive_int(protocol.get("seed"), "seed")
    if seed > _LAMMPS_SEED_MAX:
        raise ValueError(
            f"md_native_sampling seed must be between 1 and {_LAMMPS_SEED_MAX}"
        )


def validate_md_sampling_potential(
    protocol: Mapping[str, Any], potential: Mapping[str, Any]
) -> None:
    """Bind the native centroid virial route to an explicit DeepMD plugin."""

    if not md_sampling_enabled(protocol):
        return
    validate_md_sampling_protocol(protocol)
    pair_style = str(potential.get("pair_style", "")).strip().split(maxsplit=1)
    if not pair_style or pair_style[0] != "deepmd":
        raise ValueError("md_native_sampling requires a DeepMD pair_style")
    plugin = potential.get("plugin")
    if not isinstance(plugin, str) or not plugin.strip():
        raise ValueError("md_native_sampling requires an explicit DeepMD plugin")


def _sampling_dump_command(protocol: Mapping[str, Any]) -> str:
    dump_every = int(protocol["dump_every"])
    return (
        f"dump mlcc_sampling_trajectory all custom {dump_every} {_SAMPLING_DUMP} "
        + " ".join(_DUMP_COLUMNS)
    )


def _pressure_series_command(protocol: Mapping[str, Any]) -> str:
    dump_every = int(protocol["dump_every"])
    values = [
        "c_mlcc_sampling_temp",
        "c_mlcc_sampling_pressure",
        *[f"c_mlcc_sampling_pressure[{index}]" for index in range(1, 7)],
    ]
    return (
        f"fix mlcc_sampling_pressure_series all ave/time {dump_every} 1 {dump_every} "
        + " ".join(values)
        + f' file {_PRESSURE_SERIES} format " %.16g"'
    )


def _sampling_window(protocol: Mapping[str, Any], step: int) -> tuple[str, dict[str, Any]]:
    equilibration_steps = int(protocol["native_sampling"]["equilibration_steps"])
    dump_every = int(protocol["dump_every"])
    total_steps = int(protocol["steps"])
    if step < equilibration_steps:
        return (
            "equilibration",
            {
                "name": "equilibration",
                "start_step": 0,
                "end_step": equilibration_steps - dump_every,
                "closed": True,
            },
        )
    return (
        "production",
        {
            "name": "production",
            "start_step": equilibration_steps,
            "end_step": total_steps,
            "closed": True,
        },
    )


def md_sampling_before_run_commands(protocol: Mapping[str, Any]) -> list[str]:
    """Return native sampling definitions to insert after ``fix nvt``."""

    if not md_sampling_enabled(protocol):
        return []
    validate_md_sampling_protocol(protocol)
    return [
        "compute mlcc_sampling_virial all centroid/stress/atom NULL virial",
        _sampling_dump_command(protocol),
        "dump_modify mlcc_sampling_trajectory sort id format float %.16g",
        "compute mlcc_sampling_temp all temp",
        "compute mlcc_sampling_pressure all pressure mlcc_sampling_temp",
        _pressure_series_command(protocol),
    ]


def md_sampling_after_run_commands(protocol: Mapping[str, Any]) -> list[str]:
    """Return cleanup commands in reverse dependency order."""

    if not md_sampling_enabled(protocol):
        return []
    validate_md_sampling_protocol(protocol)
    return [
        "unfix mlcc_sampling_pressure_series",
        "undump mlcc_sampling_trajectory",
        "uncompute mlcc_sampling_pressure",
        "uncompute mlcc_sampling_temp",
        "uncompute mlcc_sampling_virial",
    ]


def md_sampling_output_files(protocol: Mapping[str, Any]) -> list[str]:
    """Return the additional native output files for this opt-in route."""

    if not md_sampling_enabled(protocol):
        return []
    validate_md_sampling_protocol(protocol)
    return list(_OUTPUT_FILES)


def _ordered_atom_entries(atom_map: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries = atom_map.get("atoms")
    if not isinstance(entries, list) or not entries:
        raise ValueError("LAMMPS atom map contains no atoms")
    ordered = sorted(entries, key=lambda entry: int(entry["source_index"]))
    source_indices = [int(entry["source_index"]) for entry in ordered]
    if source_indices != list(range(len(ordered))):
        raise ValueError("LAMMPS atom map source indices are not stable source order")
    source_ids = [int(entry["source_atom_id"]) for entry in ordered]
    native_ids = [int(entry["lammps_id"]) for entry in ordered]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("LAMMPS atom map contains duplicate source atom IDs")
    if len(set(native_ids)) != len(native_ids) or any(value < 1 for value in native_ids):
        raise ValueError("LAMMPS atom map contains duplicate or invalid native IDs")
    if [int(value) for value in atom_map.get("source_atom_ids", [])] != source_ids:
        raise ValueError("LAMMPS atom map source IDs are inconsistent")
    for entry in ordered:
        if int(entry["type"]) <= 0:
            raise ValueError("LAMMPS atom map atom types must be positive")
    return ordered


def _map_geometry(atom_map: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], np.ndarray, np.ndarray]:
    entries = _ordered_atom_entries(atom_map)
    source_cell = np.asarray(atom_map.get("source_cell_angstrom"), dtype=float)
    if source_cell.shape != (3, 3) or not np.all(np.isfinite(source_cell)):
        raise ValueError("LAMMPS atom map source cell is invalid")
    lammps_prism = np.asarray(atom_map.get("lammps_prism"), dtype=float)
    if lammps_prism.shape != (6,) or not np.all(np.isfinite(lammps_prism)):
        raise ValueError("LAMMPS atom map Prism parameters are invalid")
    return entries, source_cell, lammps_prism


def _command_echoed(text: str, command: str) -> bool:
    return any(line.strip() == command for line in text.splitlines())


def _required_native_commands(protocol: Mapping[str, Any]) -> list[str]:
    temperature = float(protocol["temperature_K"])
    seed = int(protocol["seed"])
    timestep = float(protocol["timestep_ps"])
    tdamp = float(protocol["tdamp_ps"])
    steps = int(protocol["steps"])
    dump_every = int(protocol["dump_every"])
    return [
        "units metal",
        "atom_style atomic",
        "boundary p p p",
        f"velocity all create {temperature:.12g} {seed} mom yes rot no dist gaussian",
        f"timestep {timestep:.12g}",
        f"fix integrator all nvt temp {temperature:.12g} {temperature:.12g} {tdamp:.12g}",
        f"dump trajectory_unwrapped all custom {dump_every} trajectory.unwrapped.lammpstrj id type xu yu zu",
        "dump_modify trajectory_unwrapped sort id format float %.16g",
        f"run {steps}",
    ]


def _validate_native_echoes(
    input_text: str, log_text: str, protocol: Mapping[str, Any]
) -> None:
    commands = [*_required_native_commands(protocol), *md_sampling_before_run_commands(protocol)]
    for name, text in (("in.lammps", input_text), ("log.lammps", log_text)):
        for command in commands:
            if not _command_echoed(text, command):
                raise ValueError(f"native {name} is missing echoed command: {command}")
        run_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("run ")]
        if run_lines != [f"run {int(protocol['steps'])}"]:
            raise ValueError(f"native {name} must contain exactly one sampling run")
        if any(line.strip().startswith("reset_timestep") for line in text.splitlines()):
            raise ValueError(f"native {name} contains reset_timestep")


def _read_thermo_series(
    log_text: str, protocol: Mapping[str, Any]
) -> list[dict[str, Any]]:
    # This is the established MD thermo-series parser; keep the ordinary
    # six-column thermo header and do not duplicate its row parsing here.
    from .md_trajectory import _parse_thermo_series

    return _parse_thermo_series(
        log_text,
        protocol,
        timestep_ps=float(protocol["timestep_ps"]),
        first_step=0,
    )


def _read_pressure_series(
    text: str, protocol: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split()
        if len(tokens) != 9:
            raise ValueError(
                f"pressure-series.dat row {line_number} must contain step, temperature, scalar pressure and six tensor values"
            )
        from .lammps import _finite_row, _integer_token

        step = _integer_token(tokens[0], context="sampling pressure step")
        values = _finite_row(tokens[1:], context="sampling pressure series")
        window, window_interval = _sampling_window(protocol, step)
        rows.append(
            {
                "step": step,
                "physical_time_ps": step * float(protocol["timestep_ps"]),
                "temperature_K": values[0],
                "pressure_bar": values[1],
                "pressure_components_bar": values[2:],
                "component_order": list(_PRESSURE_COMPONENT_ORDER),
                "window": window,
                "window_interval": window_interval,
            }
        )
    if not rows:
        raise ValueError("pressure-series.dat contains no native rows")
    steps = [int(row["step"]) for row in rows]
    if steps[0] < 0 or any(right <= left for left, right in zip(steps, steps[1:])):
        raise ValueError("pressure-series.dat steps are not strictly increasing")
    dump_every = int(protocol["dump_every"])
    total_steps = int(protocol["steps"])
    expected = list(range(dump_every, total_steps + 1, dump_every))
    if steps not in (expected, [0, *expected]):
        raise ValueError("pressure-series.dat steps differ from the native dump grid")
    return rows


def _parse_sampling_dump(
    text: str,
    protocol: Mapping[str, Any],
    atom_map: Mapping[str, Any],
    pressure_by_step: Mapping[int, Mapping[str, Any]],
    thermo_by_step: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    from .lammps import _finite_row, _integer_token, _prism_from_lammps_bounds

    entries, _source_cell, expected_prism = _map_geometry(atom_map)
    expected_native_ids_sorted = sorted(int(entry["lammps_id"]) for entry in entries)
    expected_by_native = {int(entry["lammps_id"]): entry for entry in entries}
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "ITEM: TIMESTEP"]
    if not starts:
        raise ValueError("sampling.lammpstrj contains no native timestep frame")
    expected_columns = tuple(_DUMP_COLUMNS)
    frames: list[dict[str, Any]] = []
    previous_step: int | None = None
    for frame_number, start in enumerate(starts):
        end = starts[frame_number + 1] if frame_number + 1 < len(starts) else len(lines)
        frame = lines[start:end]
        count_expected = len(entries)
        if len(frame) < 9 + count_expected:
            raise ValueError(f"sampling.lammpstrj frame {frame_number} is incomplete")
        step = _integer_token(frame[1].strip(), context="sampling dump timestep")
        if previous_step is not None and step <= previous_step:
            raise ValueError("sampling.lammpstrj steps are not strictly increasing")
        if frame[2].strip() != "ITEM: NUMBER OF ATOMS":
            raise ValueError("sampling.lammpstrj is missing the atom-count header")
        count = _integer_token(frame[3].strip(), context="sampling dump atom count")
        if count != count_expected:
            raise ValueError("sampling.lammpstrj atom count differs from atom map")
        if not frame[4].startswith("ITEM: BOX BOUNDS"):
            raise ValueError("sampling.lammpstrj is missing the box header")
        box_header = frame[4].split()
        if box_header[3:6] != ["xy", "xz", "yz"] or box_header[6:] != ["pp", "pp", "pp"]:
            raise ValueError("sampling.lammpstrj box header is not triclinic p p p")
        box_rows = np.asarray(
            [_finite_row(frame[index].split(), context="sampling dump box") for index in range(5, 8)],
            dtype=float,
        )
        if box_rows.shape != (3, 3):
            raise ValueError("sampling.lammpstrj box must contain three rows")
        if not frame[8].startswith("ITEM: ATOMS "):
            raise ValueError("sampling.lammpstrj is missing the atom header")
        if tuple(frame[8].split()[2:]) != expected_columns:
            raise ValueError("sampling.lammpstrj atom columns differ from the fixed sampling dump")
        data_end = 9 + count
        if len(frame) < data_end:
            raise ValueError("sampling.lammpstrj atom rows are incomplete")
        if any(line.strip() for line in frame[data_end:]):
            raise ValueError(f"sampling.lammpstrj frame {frame_number} has trailing data")

        rows: list[tuple[int, int, list[float], list[int], list[float], list[float]]] = []
        for line in frame[9:data_end]:
            tokens = line.split()
            if len(tokens) != len(expected_columns):
                raise ValueError("sampling.lammpstrj atom row has the wrong column count")
            atom_id = _integer_token(tokens[0], context="sampling dump atom id")
            atom_type = _integer_token(tokens[1], context="sampling dump atom type")
            coordinates = _finite_row(tokens[2:5], context="sampling dump xu/yu/zu")
            flags = [
                _integer_token(tokens[index], context="sampling dump image flag")
                for index in range(5, 8)
            ]
            velocities = _finite_row(tokens[8:11], context="sampling dump velocity")
            virial = _finite_row(tokens[11:20], context="sampling dump centroid virial")
            rows.append((atom_id, atom_type, coordinates, flags, velocities, virial))

        native_ids = [row[0] for row in rows]
        if native_ids != expected_native_ids_sorted:
            raise ValueError("sampling.lammpstrj atom IDs differ from sorted native atom-map order")
        if len(set(native_ids)) != len(native_ids):
            raise ValueError("sampling.lammpstrj contains duplicate atom IDs")
        for atom_id, atom_type, _coordinates, _flags, _velocities, _virial in rows:
            if atom_id not in expected_by_native:
                raise ValueError("sampling.lammpstrj atom IDs differ from atom map")
            if atom_type != int(expected_by_native[atom_id]["type"]):
                raise ValueError("sampling.lammpstrj atom types differ from atom map")
        observed_prism = np.asarray(_prism_from_lammps_bounds(box_rows), dtype=float)
        if not np.allclose(observed_prism, expected_prism, rtol=0.0, atol=1.0e-7):
            raise ValueError("sampling.lammpstrj box differs from atom-map Prism cell")

        rows_by_id = {row[0]: row for row in rows}
        source_atom_ids = [int(entry["source_atom_id"]) for entry in entries]
        source_native_ids = [int(entry["lammps_id"]) for entry in entries]
        source_types = [int(entry["type"]) for entry in entries]
        if step in pressure_by_step:
            temperature = float(pressure_by_step[step]["temperature_K"])
            temperature_source = "pressure-series.dat"
        elif step == 0 and step in thermo_by_step:
            temperature = float(thermo_by_step[step]["temp"])
            temperature_source = "log.lammps:thermo"
        else:
            raise ValueError(
                f"sampling frame step {step} has no aligned native temperature record"
            )
        window, window_interval = _sampling_window(protocol, step)
        frames.append(
            {
                "frame_index": frame_number,
                "step": step,
                "physical_time_ps": step * float(protocol["timestep_ps"]),
                "time_source": "native sampling timestep and protocol timestep_ps",
                "window": window,
                "window_interval": window_interval,
                "temperature_K": temperature,
                "temperature_source": temperature_source,
                "atom_ids": source_atom_ids,
                "native_atom_ids": source_native_ids,
                "types": source_types,
                "native_types": source_types,
                "positions_angstrom": [rows_by_id[native_id][2] for native_id in source_native_ids],
                "xu_yu_zu_angstrom": [rows_by_id[native_id][2] for native_id in source_native_ids],
                "image_flags": [rows_by_id[native_id][3] for native_id in source_native_ids],
                "velocities_angstrom_per_ps": [
                    rows_by_id[native_id][4] for native_id in source_native_ids
                ],
                "stress_volume_components_bar_A3": [
                    rows_by_id[native_id][5] for native_id in source_native_ids
                ],
                "component_order": list(_COMPONENT_ORDER),
                "coordinate_basis": "unwrapped_lammps_prism",
                "box_bounds_angstrom": box_rows.tolist(),
                "lammps_prism_angstrom": expected_prism.tolist(),
                "fixed_cell": True,
            }
        )
        previous_step = step

    dump_every = int(protocol["dump_every"])
    total_steps = int(protocol["steps"])
    expected_without_zero = list(range(dump_every, total_steps + 1, dump_every))
    expected_with_zero = [0, *expected_without_zero]
    actual_steps = [int(frame["step"]) for frame in frames]
    if actual_steps != expected_with_zero:
        raise ValueError("sampling.lammpstrj steps differ from the complete native dump grid")
    if set(pressure_by_step) - set(actual_steps):
        raise ValueError("pressure-series.dat contains steps absent from sampling.lammpstrj")
    return frames


def read_md_sampling_outputs(
    directory: str | Path,
    protocol: Mapping[str, Any],
    atom_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Read the native rich sampling dump and pressure sidecar verbatim."""

    validate_md_sampling_protocol(protocol)
    if not md_sampling_enabled(protocol):
        raise ValueError("read_md_sampling_outputs requires purpose=md_native_sampling")
    entries, source_cell, lammps_prism = _map_geometry(atom_map)
    output = Path(directory)
    input_path = output / "in.lammps"
    log_path = output / "log.lammps"
    sampling_path = output / _SAMPLING_DUMP
    pressure_path = output / _PRESSURE_SERIES
    input_text = input_path.read_text(encoding="utf-8")
    log_text = log_path.read_text(encoding="utf-8")
    _validate_native_echoes(input_text, log_text, protocol)

    thermo_rows = _read_thermo_series(log_text, protocol)
    thermo_by_step = {int(row["step"]): row for row in thermo_rows}
    pressure_rows = _read_pressure_series(pressure_path.read_text(encoding="utf-8"), protocol)
    pressure_by_step = {int(row["step"]): row for row in pressure_rows}
    frames = _parse_sampling_dump(
        sampling_path.read_text(encoding="utf-8"),
        protocol,
        atom_map,
        pressure_by_step,
        thermo_by_step,
    )

    source_files = {
        "in.lammps": str(input_path),
        "log.lammps": str(log_path),
        _SAMPLING_DUMP: str(sampling_path),
        _PRESSURE_SERIES: str(pressure_path),
    }
    atom_map_path = output / "atom-map.json"
    if atom_map_path.exists():
        source_files["atom-map.json"] = str(atom_map_path)
    equilibration_steps = int(protocol["native_sampling"]["equilibration_steps"])
    pressure_series = {
        "unit": "bar",
        "basis": "lammps_prism",
        "component_order": list(_PRESSURE_COMPONENT_ORDER),
        "compression_positive": True,
        "kinetic_included": True,
        "records": pressure_rows,
        "production_records": [
            row for row in pressure_rows if int(row["step"]) >= equilibration_steps
        ],
        "source": str(pressure_path),
    }
    return {
        "schema": _RESULT_SCHEMA,
        "units": "metal",
        "source_cell_angstrom": source_cell.tolist(),
        "component_order": list(_COMPONENT_ORDER),
        "stress_volume_unit": "bar*angstrom^3",
        "stress_sign": "tension_positive",
        "tensor_basis": "lammps_prism",
        "contribution": "virial",
        "kinetic_included": False,
        "protocol": dict(protocol),
        "native_columns": list(_DUMP_COLUMNS),
        "fixed_cell": {
            "value": True,
            "source": "atom-map.json:lammps_prism",
            "lammps_prism_angstrom": lammps_prism.tolist(),
        },
        "thermo_series": {
            "fields": ["step", "temp", "pe", "ke", "etotal", "press"],
            "rows": thermo_rows,
            "source": str(log_path),
            "frame_zero_temperature_source": "log.lammps:thermo",
        },
        "pressure_series": pressure_series,
        "frames": frames,
        "sampling_windows": {
            "equilibration": {
                "name": "equilibration",
                "start_step": 0,
                "end_step": equilibration_steps - int(protocol["dump_every"]),
                "closed": True,
            },
            "production": {
                "name": "production",
                "start_step": equilibration_steps,
                "end_step": int(protocol["steps"]),
                "closed": True,
            },
        },
        "source_files": source_files,
        "production_qualification": False,
    }


__all__ = [
    "md_sampling_after_run_commands",
    "md_sampling_before_run_commands",
    "md_sampling_enabled",
    "md_sampling_output_files",
    "read_md_sampling_outputs",
    "validate_md_sampling_potential",
    "validate_md_sampling_protocol",
]
