"""Thin native LAMMPS adapter for the explicit interface thermal contract.

This module only validates the declared thermal protocol, renders the thermal
commands that are inserted into an existing MLCC MD input, and reads the two
fixed-format ``fix ave`` tables.  It does not submit LAMMPS, infer a thermal
window, divide a periodic two-interface flux, or turn an engineering fixture
into a production result.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from pathlib import Path
from typing import Any

import numpy as np


_PROTOCOL_SCHEMA = "mlcc.interface-thermal-protocol.v1"
_RESULT_SCHEMA = "mlcc.lammps-thermal-result.v1"
_THERMAL_KIND = "md"
_THERMAL_PURPOSE = "interface_thermal_response"
_ENERGY_FILE = "thermal-energy.dat"
_PROFILE_FILE = "thermal-profile.dat"


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be a positive integer")
    result = int(value)
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be positive and finite")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _atom_ids(value: Any, name: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
            raise ValueError(f"{name} must contain integer atom IDs")
        atom_id = int(item)
        if atom_id < 0:
            raise ValueError(f"{name} must contain non-negative atom IDs")
        result.append(atom_id)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique atom IDs")
    return result


def _normal(value: Any, name: str = "normal_cartesian") -> list[float]:
    values = np.asarray(value, dtype=float)
    if values.shape != (3,) or not np.all(np.isfinite(values)):
        raise ValueError(f"{name} must be a finite length-3 vector")
    if not math.isclose(float(np.linalg.norm(values)), 1.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError(f"{name} must be a unit vector")
    if not np.allclose(values, [0.0, 0.0, 1.0], rtol=0.0, atol=1.0e-12):
        raise ValueError(f"{name} must be [0, 0, 1]")
    return [float(item) for item in values]


def _reservoir(protocol: Mapping[str, Any], name: str) -> dict[str, Any]:
    thermal = protocol["thermal"]
    record = thermal[name]
    if not isinstance(record, Mapping):
        raise ValueError(f"thermal.{name} must be an object")
    return {
        "atom_ids": _atom_ids(record["atom_ids"], f"thermal.{name}.atom_ids"),
        "temperature_K": _positive_float(
            record["temperature_K"], f"thermal.{name}.temperature_K"
        ),
        "damping_ps": _positive_float(
            record["damping_ps"], f"thermal.{name}.damping_ps"
        ),
        "seed": _positive_int(record["seed"], f"thermal.{name}.seed"),
        "zero_random_force": record["zero_random_force"],
    }


def validate_thermal_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate the complete explicit ``interface_thermal_response`` input."""

    if protocol["kind"] != _THERMAL_KIND:
        raise ValueError("thermal protocol kind must be md")
    if protocol["purpose"] != _THERMAL_PURPOSE:
        raise ValueError("thermal protocol purpose must be interface_thermal_response")
    if protocol["units"] != "metal":
        raise ValueError("thermal protocol units must be metal")
    if [str(value) for value in protocol["boundary"]] != ["p", "p", "p"]:
        raise ValueError("thermal protocol boundary must be p p p")
    if protocol["ensemble"] != "nve":
        raise ValueError("thermal protocol ensemble must be nve")
    if "static_tensor" in protocol and protocol["static_tensor"] is not False:
        raise ValueError("thermal protocol static_tensor must be false when present")

    steps = _positive_int(protocol["steps"], "steps")
    timestep_ps = _positive_float(protocol["timestep_ps"], "timestep_ps")
    _positive_float(protocol["temperature_K"], "temperature_K")
    _positive_int(protocol["seed"], "seed")
    _positive_int(protocol["thermo_every"], "thermo_every")
    dump_every = _positive_int(protocol["dump_every"], "dump_every")
    if steps % dump_every != 0:
        raise ValueError("thermal protocol dump_every must divide steps")
    if not math.isfinite(steps * timestep_ps):
        raise ValueError("thermal protocol physical run time must be finite")

    thermal = protocol["thermal"]
    if not isinstance(thermal, Mapping):
        raise ValueError("thermal must be an object")
    if thermal["schema"] != _PROTOCOL_SCHEMA:
        raise ValueError(f"thermal schema must be {_PROTOCOL_SCHEMA}")
    _positive_float(thermal["area_angstrom2"], "thermal.area_angstrom2")
    _normal(thermal["normal_cartesian"], "thermal.normal_cartesian")
    if thermal["interface_count"] != 2:
        raise ValueError("thermal.interface_count must be exactly 2")
    hot = _reservoir(protocol, "hot")
    cold = _reservoir(protocol, "cold")
    if type(hot["zero_random_force"]) is not bool:
        raise ValueError("thermal.hot.zero_random_force must be boolean")
    if type(cold["zero_random_force"]) is not bool:
        raise ValueError("thermal.cold.zero_random_force must be boolean")
    if set(hot["atom_ids"]) & set(cold["atom_ids"]):
        raise ValueError("thermal hot and cold atom IDs must not overlap")
    if hot["seed"] == cold["seed"]:
        raise ValueError("thermal hot and cold seeds must be independent")
    _positive_int(thermal["sample_every"], "thermal.sample_every")
    _positive_float(thermal["bin_width_angstrom"], "thermal.bin_width_angstrom")
    if thermal["temperature_definition"] != "kinetic_3N_no_bias":
        raise ValueError(
            "thermal.temperature_definition must be kinetic_3N_no_bias"
        )
    # The values above are intentionally checked as direct request fields;
    # no default or inferred value is introduced.


def validate_thermal_model(model: Any, protocol: Mapping[str, Any]) -> None:
    """Bind thermal area/normal/count and reservoir IDs to a layered model."""

    validate_thermal_protocol(protocol)
    metadata = model.metadata
    if metadata.get("spatial_mode") != "layered_interface":
        raise ValueError("thermal response requires spatial_mode=layered_interface")
    geometry = metadata["interface_geometry"]
    thermal = protocol["thermal"]
    if not np.allclose(
        np.asarray(_normal(thermal["normal_cartesian"]), dtype=float),
        np.asarray(_normal(geometry["normal_cartesian"], "saved normal_cartesian"), dtype=float),
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise ValueError("thermal response normal differs from saved interface geometry")
    if not math.isclose(
        float(thermal["area_angstrom2"]),
        float(geometry["area_angstrom2"]),
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise ValueError("thermal response area differs from saved interface geometry")
    if thermal["interface_count"] != geometry["interface_count"]:
        raise ValueError("thermal response interface_count differs from saved interface geometry")

    model_ids = {int(value) for value in model.atom_ids}
    if not model_ids:
        raise ValueError("thermal response model must contain atom IDs")
    for name in ("hot", "cold"):
        reservoir_ids = set(_reservoir(protocol, name)["atom_ids"])
        if not reservoir_ids <= model_ids:
            raise ValueError(f"thermal {name} atom IDs differ from the model")

    saved_cell = np.asarray(geometry["cell_angstrom"], dtype=float)
    model_cell = np.asarray(model.atoms.cell.array, dtype=float)
    if saved_cell.shape != (3, 3) or not np.all(np.isfinite(saved_cell)):
        raise ValueError("saved interface geometry cell is invalid")
    if model_cell.shape != (3, 3) or not np.all(np.isfinite(model_cell)):
        raise ValueError("thermal response model cell is invalid")
    if not np.allclose(model_cell, saved_cell, rtol=0.0, atol=1.0e-10):
        raise ValueError("saved interface geometry cell differs from model")
    if (
        abs(float(model_cell[0, 2])) > 1.0e-10
        or abs(float(model_cell[1, 2])) > 1.0e-10
        or abs(float(model_cell[2, 0])) > 1.0e-10
        or abs(float(model_cell[2, 1])) > 1.0e-10
        or float(model_cell[2, 2]) <= 0.0
    ):
        raise ValueError("thermal model cell must be aligned with the +z binning normal")
    cross_xy = np.cross(model_cell[0], model_cell[1])
    if float(cross_xy[2]) <= 0.0 or abs(float(cross_xy[0])) > 1.0e-10 or abs(float(cross_xy[1])) > 1.0e-10:
        raise ValueError("thermal model first two cell vectors must span the +z-normal xy plane")
    model_area = float(np.linalg.norm(cross_xy))
    if not math.isclose(
        model_area,
        float(geometry["area_angstrom2"]),
        rel_tol=0.0,
        abs_tol=1.0e-10,
    ):
        raise ValueError("saved interface geometry area differs from model xy area")


def _atom_map_ids(atom_map: Mapping[str, Any]) -> dict[int, int]:
    entries = atom_map["atoms"]
    mapping: dict[int, int] = {}
    native_ids: set[int] = set()
    for entry in entries:
        source_id = int(entry["source_atom_id"])
        native_id = int(entry["lammps_id"])
        if source_id in mapping or native_id in native_ids:
            raise ValueError("LAMMPS atom map contains duplicate source or native IDs")
        if native_id <= 0:
            raise ValueError("LAMMPS atom map native IDs must be positive")
        mapping[source_id] = native_id
        native_ids.add(native_id)
    if not mapping:
        raise ValueError("LAMMPS atom map contains no atoms")
    return mapping


def _source_z_length(atom_map: Mapping[str, Any]) -> float:
    """Return the source cell z length used by LAMMPS reduced coordinates."""

    cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("LAMMPS atom map source cell is invalid")
    if (
        abs(float(cell[0, 2])) > 1.0e-10
        or abs(float(cell[1, 2])) > 1.0e-10
        or abs(float(cell[2, 0])) > 1.0e-10
        or abs(float(cell[2, 1])) > 1.0e-10
        or float(cell[2, 2]) <= 0.0
    ):
        raise ValueError("LAMMPS atom map source cell must be aligned with the +z thermal normal")
    return float(cell[2][2])


def thermal_before_run_commands(
    protocol: Mapping[str, Any], atom_map: Mapping[str, Any]
) -> list[str]:
    """Render only the thermal commands inserted before the existing MD run."""

    validate_thermal_protocol(protocol)
    source_to_native = _atom_map_ids(atom_map)
    hot = _reservoir(protocol, "hot")
    cold = _reservoir(protocol, "cold")
    available_source_ids = set(source_to_native)
    for name, reservoir in (("hot", hot), ("cold", cold)):
        if not set(reservoir["atom_ids"]) <= available_source_ids:
            raise ValueError(f"thermal {name} atom IDs must be present in the atom map")
    commands = [
        "group mlcc_thermal_hot id "
        + " ".join(str(source_to_native[atom_id]) for atom_id in hot["atom_ids"]),
        "group mlcc_thermal_cold id "
        + " ".join(str(source_to_native[atom_id]) for atom_id in cold["atom_ids"]),
        (
            "fix mlcc_hot mlcc_thermal_hot langevin "
            f"{hot['temperature_K']:.12g} {hot['temperature_K']:.12g} "
            f"{hot['damping_ps']:.12g} {hot['seed']} "
            f"zero {'yes' if hot['zero_random_force'] else 'no'} tally yes"
        ),
        (
            "fix mlcc_cold mlcc_thermal_cold langevin "
            f"{cold['temperature_K']:.12g} {cold['temperature_K']:.12g} "
            f"{cold['damping_ps']:.12g} {cold['seed']} "
            f"zero {'yes' if cold['zero_random_force'] else 'no'} tally yes"
        ),
    ]
    sample_every = _positive_int(protocol["thermal"]["sample_every"], "thermal.sample_every")
    width = _positive_float(protocol["thermal"]["bin_width_angstrom"], "thermal.bin_width_angstrom")
    z_length = _source_z_length(atom_map)
    delta_reduced = width / z_length
    commands.extend(
        [
            (
                "fix mlcc_thermal_energy all ave/time "
                f"{sample_every} 1 {sample_every} f_mlcc_hot f_mlcc_cold "
                "mode scalar ave one file thermal-energy.dat"
            ),
            (
                "compute mlcc_thermal_bins all chunk/atom bin/1d z lower "
                f"{delta_reduced:.12g} units reduced compress no"
            ),
            (
                "fix mlcc_thermal_profile all ave/chunk "
                f"{sample_every} 1 {sample_every} mlcc_thermal_bins temp "
                "norm sample ave one adof 3 cdof 0 file thermal-profile.dat"
            ),
        ]
    )
    return commands


def thermal_after_run_commands(protocol: Mapping[str, Any]) -> list[str]:
    """Render thermal cleanup in reverse fix/compute dependency order."""

    validate_thermal_protocol(protocol)
    return [
        "unfix mlcc_thermal_profile",
        "uncompute mlcc_thermal_bins",
        "unfix mlcc_thermal_energy",
        "unfix mlcc_cold",
        "unfix mlcc_hot",
    ]


def _table_lines(path: Path) -> tuple[list[str], list[str]]:
    raw_lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()]
    comments = [line.lstrip()[1:].strip() for line in raw_lines if line.lstrip().startswith("#")]
    data = [line.strip() for line in raw_lines if line.strip() and not line.lstrip().startswith("#")]
    return comments, data


def _parse_energy_rows(path: Path, protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    comments, lines = _table_lines(path)
    if not any(comment == "Time-averaged data for fix mlcc_thermal_energy" for comment in comments):
        raise ValueError("thermal-energy.dat is missing the native fix header")
    if not any(comment.lower() == "timestep f_mlcc_hot f_mlcc_cold" for comment in comments):
        raise ValueError("thermal-energy.dat columns differ from f_mlcc_hot/f_mlcc_cold")
    if not lines:
        raise ValueError("thermal-energy.dat contains no native rows")
    timestep_ps = _positive_float(protocol["timestep_ps"], "timestep_ps")
    sample_every = _positive_int(protocol["thermal"]["sample_every"], "thermal.sample_every")
    rows: list[dict[str, Any]] = []
    for row_index, line in enumerate(lines):
        tokens = line.split()
        if len(tokens) != 3:
            raise ValueError(f"thermal-energy.dat row {row_index} must contain step and two energies")
        try:
            step = int(tokens[0])
        except ValueError as error:
            raise ValueError(f"thermal-energy.dat row {row_index} has a non-integer step") from error
        if step < 0:
            raise ValueError("thermal-energy.dat steps must be non-negative")
        hot = _finite_float(tokens[1], f"thermal-energy.dat row {row_index} hot_reservoir_eV")
        cold = _finite_float(tokens[2], f"thermal-energy.dat row {row_index} cold_reservoir_eV")
        rows.append(
            {
                "step": step,
                "physical_time_ps": float(step) * timestep_ps,
                "hot_reservoir_eV": hot,
                "cold_reservoir_eV": cold,
            }
        )
    steps = [int(row["step"]) for row in rows]
    if any(right <= left for left, right in zip(steps, steps[1:])):
        raise ValueError("thermal-energy.dat steps must be strictly increasing")
    if any(right - left != sample_every for left, right in zip(steps, steps[1:])):
        raise ValueError("thermal-energy.dat steps do not match sample_every")
    return rows


def _parse_profile_frames(
    path: Path, protocol: Mapping[str, Any], z_length: float
) -> list[dict[str, Any]]:
    comments, lines = _table_lines(path)
    if not any(comment.startswith("Chunk-averaged data for fix mlcc_thermal_profile") for comment in comments):
        raise ValueError("thermal-profile.dat is missing the native fix header")
    if not any(comment.lower() == "timestep number-of-chunks total-count" for comment in comments):
        raise ValueError("thermal-profile.dat is missing the native frame header")
    if not any(comment.lower() == "chunk coord1 ncount temp" for comment in comments):
        raise ValueError("thermal-profile.dat columns differ from chunk/temp contract")
    if not lines:
        raise ValueError("thermal-profile.dat contains no native frames")
    timestep_ps = _positive_float(protocol["timestep_ps"], "timestep_ps")
    sample_every = _positive_int(protocol["thermal"]["sample_every"], "thermal.sample_every")
    frames: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(lines):
        header = lines[cursor].split()
        if len(header) != 3:
            raise ValueError(
                "thermal-profile.dat frame header must contain timestep, chunk count and total count"
            )
        try:
            step = int(header[0])
            chunk_count = int(header[1])
        except ValueError as error:
            raise ValueError("thermal-profile.dat frame header must contain integer values") from error
        total_count = _finite_float(header[2], "thermal-profile.dat total count")
        if step < 0:
            raise ValueError("thermal-profile.dat steps must be non-negative")
        if chunk_count <= 0:
            raise ValueError("thermal-profile.dat frame must contain a positive chunk count")
        if total_count < 0.0 or not math.isclose(total_count, round(total_count), rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("thermal-profile.dat total count must be a non-negative integer value")
        cursor += 1
        if cursor + chunk_count > len(lines):
            raise ValueError("thermal-profile.dat frame is missing chunk rows")
        bins: list[dict[str, Any]] = []
        for row_index in range(chunk_count):
            tokens = lines[cursor + row_index].split()
            if len(tokens) != 4:
                raise ValueError("thermal-profile.dat chunk row must contain four values")
            try:
                bin_id = int(tokens[0])
            except ValueError as error:
                raise ValueError("thermal-profile.dat chunk IDs must be integers") from error
            atom_count = _finite_float(
                tokens[2], f"thermal-profile.dat bin {bin_id} atom_count"
            )
            if bin_id < 1:
                raise ValueError("thermal-profile.dat chunk IDs must be positive")
            if atom_count < 0.0 or not math.isclose(
                atom_count, round(atom_count), rel_tol=0.0, abs_tol=1.0e-12
            ):
                raise ValueError("thermal-profile.dat atom counts must be non-negative integer values")
            coordinate_reduced = _finite_float(
                tokens[1], f"thermal-profile.dat bin {bin_id} coordinate_reduced"
            )
            temperature = _finite_float(
                tokens[3], f"thermal-profile.dat bin {bin_id} temperature_K"
            )
            bins.append(
                {
                    "bin_id": bin_id,
                    "coordinate_reduced": coordinate_reduced,
                    "coordinate_angstrom": coordinate_reduced * z_length,
                    "atom_count": atom_count,
                    "temperature_K": temperature,
                }
            )
        cursor += chunk_count
        if [item["bin_id"] for item in bins] != list(range(1, chunk_count + 1)):
            raise ValueError("thermal-profile.dat chunk IDs must cover 1..Number-of-chunks")
        coordinates = [float(item["coordinate_reduced"]) for item in bins]
        if any(right <= left for left, right in zip(coordinates, coordinates[1:])):
            raise ValueError("thermal-profile.dat bin coordinates must be increasing")
        if not math.isclose(
            math.fsum(float(item["atom_count"]) for item in bins),
            total_count,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError("thermal-profile.dat total count differs from bin atom counts")
        frames.append(
            {
                "step": step,
                "physical_time_ps": float(step) * timestep_ps,
                "total_count": total_count,
                "bins": bins,
            }
        )
    steps = [int(frame["step"]) for frame in frames]
    if any(right <= left for left, right in zip(steps, steps[1:])):
        raise ValueError("thermal-profile.dat steps must be strictly increasing")
    if any(right - left != sample_every for left, right in zip(steps, steps[1:])):
        raise ValueError("thermal-profile.dat steps do not match sample_every")
    return frames


def read_thermal_outputs(
    directory: str | Path, protocol: Mapping[str, Any], atom_map: Mapping[str, Any]
) -> dict[str, Any]:
    """Read the two native thermal tables without calculating a response."""

    validate_thermal_protocol(protocol)
    z_length = _source_z_length(atom_map)
    output = Path(directory)
    energy_path = output / _ENERGY_FILE
    profile_path = output / _PROFILE_FILE
    missing_evidence: list[str] = []
    energy_rows = None if not energy_path.exists() else _parse_energy_rows(energy_path, protocol)
    profile_frames = (
        None
        if not profile_path.exists()
        else _parse_profile_frames(profile_path, protocol, z_length)
    )
    if energy_rows is None:
        missing_evidence.append(_ENERGY_FILE)
    if profile_frames is None:
        missing_evidence.append(_PROFILE_FILE)
    if energy_rows is not None and profile_frames is not None and [
        row["step"] for row in energy_rows
    ] != [frame["step"] for frame in profile_frames]:
        raise ValueError("thermal energy and profile steps differ")
    return {
        "schema": _RESULT_SCHEMA,
        "units": "metal",
        "protocol": dict(protocol),
        "energy_rows": energy_rows,
        "profile_frames": profile_frames,
        "missing_evidence": missing_evidence,
        "source_files": {
            _ENERGY_FILE: str(energy_path),
            _PROFILE_FILE: str(profile_path),
        },
        "production_qualification": False,
    }


__all__ = [
    "read_thermal_outputs",
    "thermal_after_run_commands",
    "thermal_before_run_commands",
    "validate_thermal_model",
    "validate_thermal_protocol",
]
