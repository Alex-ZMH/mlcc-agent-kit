"""Thin native LAMMPS source adapter for fixed-cell bulk heat transport.

The bulk heat route deliberately reuses the two native ``fix ave`` table
formats already emitted by :mod:`mlcc.lammps_interface_thermal`.  It owns the
bulk protocol boundary, source metadata, and the Langevin command contract;
it does not run an interface validator, infer a response, or calculate a
thermal conductivity.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from pathlib import Path
from typing import Any

import numpy as np

from .lammps_interface_thermal import (
    _atom_map_ids,
    _finite_float,
    _normal,
    _parse_energy_rows,
    _parse_profile_frames,
    _positive_float,
    _positive_int,
    _reservoir,
    _source_z_length,
)


_PURPOSE = "bulk_thermal_transport"
_PROTOCOL_SCHEMA = "mlcc.bulk-heat-protocol.v1"
_RESULT_SCHEMA = "mlcc.md-bulk-heat-source.v1"
_ENERGY_FILE = "thermal-energy.dat"
_PROFILE_FILE = "thermal-profile.dat"
_OUTPUT_FILES = (_ENERGY_FILE, _PROFILE_FILE)
_LAMMPS_SEED_MAX = 900_000_000
_NORMAL = [0.0, 0.0, 1.0]


def bulk_heat_enabled(protocol: Mapping[str, Any]) -> bool:
    """Return whether the explicit fixed-cell bulk heat route is requested."""

    return isinstance(protocol, Mapping) and protocol.get("purpose") == _PURPOSE


def _seed(value: Any, name: str) -> int:
    result = _positive_int(value, name)
    if result > _LAMMPS_SEED_MAX:
        raise ValueError(
            f"bulk heat {name} must be between 1 and {_LAMMPS_SEED_MAX}"
        )
    return result


def _thermal_record(protocol: Mapping[str, Any]) -> Mapping[str, Any]:
    record = protocol.get("thermal")
    if not isinstance(record, Mapping):
        raise ValueError("bulk_thermal_transport requires a thermal object")
    if record.get("schema") != _PROTOCOL_SCHEMA:
        raise ValueError(f"bulk heat thermal schema must be {_PROTOCOL_SCHEMA}")
    _positive_float(record.get("area_angstrom2"), "thermal.area_angstrom2")
    _normal(record.get("normal_cartesian"))
    _positive_int(record.get("sample_every"), "thermal.sample_every")
    bin_count = _positive_int(record.get("bin_count"), "thermal.bin_count")
    if bin_count < 2:
        raise ValueError("bulk heat thermal.bin_count must be at least 2")
    if record.get("temperature_definition") != "kinetic_3N_no_bias":
        raise ValueError(
            "bulk heat thermal.temperature_definition must be kinetic_3N_no_bias"
        )
    hot = _reservoir(protocol, "hot")
    cold = _reservoir(protocol, "cold")
    for name, reservoir in (("hot", hot), ("cold", cold)):
        _seed(reservoir["seed"], f"thermal.{name}.seed")
    if type(hot["zero_random_force"]) is not bool:
        raise ValueError("bulk heat thermal.hot.zero_random_force must be boolean")
    if type(cold["zero_random_force"]) is not bool:
        raise ValueError("bulk heat thermal.cold.zero_random_force must be boolean")
    if set(hot["atom_ids"]) & set(cold["atom_ids"]):
        raise ValueError("bulk heat hot and cold atom IDs must not overlap")
    if hot["seed"] == cold["seed"]:
        raise ValueError("bulk heat hot and cold seeds must be independent")
    transport = record.get("transport")
    if not isinstance(transport, Mapping):
        raise ValueError("bulk heat thermal.transport must be an object")
    _positive_int(
        transport.get("periodic_channel_count"),
        "thermal.transport.periodic_channel_count",
    )
    heat_fraction = _finite_float(
        transport.get("heat_fraction"), "thermal.transport.heat_fraction"
    )
    if not 0.0 <= heat_fraction <= 1.0:
        raise ValueError("bulk heat thermal.transport.heat_fraction must be between 0 and 1")
    if not isinstance(transport.get("heat_fraction_basis"), str) or not transport[
        "heat_fraction_basis"
    ].strip():
        raise ValueError("bulk heat thermal.transport.heat_fraction_basis must be explicit")
    return record


def validate_bulk_heat_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate only the additional fixed-cell bulk heat protocol contract."""

    if not bulk_heat_enabled(protocol):
        return
    if protocol.get("kind") != "md":
        raise ValueError("bulk_thermal_transport requires protocol kind=md")
    if protocol.get("units") != "metal":
        raise ValueError("bulk_thermal_transport requires units=metal")
    if [str(value) for value in protocol.get("boundary", [])] != ["p", "p", "p"]:
        raise ValueError("bulk_thermal_transport requires periodic boundary p p p")
    if protocol.get("ensemble") != "nve":
        raise ValueError("bulk_thermal_transport requires ensemble=nve")
    if protocol.get("static_tensor") is True:
        raise ValueError("bulk_thermal_transport does not allow static_tensor=true")
    for name in ("pressure_coupling", "pressure_target_bar", "pdamp_ps"):
        if name in protocol:
            raise ValueError(f"bulk_thermal_transport does not allow {name}")

    thermal = _thermal_record(protocol)
    sample_every = int(thermal["sample_every"])
    for name in ("temperature_K", "timestep_ps"):
        if name in protocol:
            _positive_float(protocol[name], name)
    if "seed" in protocol:
        _seed(protocol["seed"], "seed")
    steps = None
    if "steps" in protocol:
        steps = _positive_int(protocol["steps"], "steps")
        if steps % sample_every:
            raise ValueError("bulk heat steps must lie on the thermal sample grid")
    for name in ("thermo_every", "dump_every"):
        if name in protocol:
            cadence = _positive_int(protocol[name], name)
            if cadence != sample_every:
                raise ValueError(
                    f"bulk heat {name} must equal thermal.sample_every"
                )
            if steps is not None and steps % cadence:
                raise ValueError(f"bulk heat {name} must divide steps")


def _source_geometry(atom_map: Mapping[str, Any]) -> tuple[np.ndarray, float, float]:
    z_length = _source_z_length(atom_map)
    cell = np.asarray(atom_map.get("source_cell_angstrom"), dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("bulk heat atom map source cell is invalid")
    area = float(np.linalg.norm(np.cross(cell[0], cell[1])))
    if not math.isfinite(area) or area <= 0.0:
        raise ValueError("bulk heat source cell xy area must be positive and finite")
    if float(np.cross(cell[0], cell[1])[2]) <= 0.0:
        raise ValueError("bulk heat source cell xy normal must point along positive z")
    return cell, z_length, area


def _ordered_atom_entries(atom_map: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries = atom_map.get("atoms")
    if not isinstance(entries, list) or not entries:
        raise ValueError("bulk heat atom map contains no atoms")
    try:
        ordered = sorted((dict(entry) for entry in entries), key=lambda entry: int(entry["source_index"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("bulk heat atom map source indices are invalid") from error
    if [int(entry["source_index"]) for entry in ordered] != list(range(len(ordered))):
        raise ValueError("bulk heat atom map source indices are not stable source order")
    source_ids = [int(entry["source_atom_id"]) for entry in ordered]
    native_ids = [int(entry["lammps_id"]) for entry in ordered]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("bulk heat atom map source atom IDs are not unique")
    if len(set(native_ids)) != len(native_ids) or any(value <= 0 for value in native_ids):
        raise ValueError("bulk heat atom map native IDs are invalid")
    if [int(value) for value in atom_map.get("source_atom_ids", [])] != source_ids:
        raise ValueError("bulk heat atom map source IDs are inconsistent")
    if any(not isinstance(entry.get("element"), str) or not entry["element"] for entry in ordered):
        raise ValueError("bulk heat atom map elements are required")
    return ordered


def validate_bulk_heat_model(model: Any, protocol: Mapping[str, Any]) -> None:
    """Bind bulk heat geometry and reservoir IDs to a saved model when needed."""

    if not bulk_heat_enabled(protocol):
        return
    validate_bulk_heat_protocol(protocol)
    atoms = getattr(model, "atoms", None)
    if atoms is None:
        raise ValueError("bulk heat model must expose atoms")
    cell = np.asarray(atoms.cell.array, dtype=float)
    model_map = {"source_cell_angstrom": cell.tolist()}
    _, _, area = _source_geometry(model_map)
    requested_area = float(protocol["thermal"]["area_angstrom2"])
    if not math.isclose(area, requested_area, rel_tol=0.0, abs_tol=1.0e-10):
        raise ValueError("bulk heat thermal area differs from model xy area")
    model_ids = {int(value) for value in getattr(model, "atom_ids", [])}
    if not model_ids:
        raise ValueError("bulk heat model must contain atom IDs")
    for name in ("hot", "cold"):
        if not set(_reservoir(protocol, name)["atom_ids"]) <= model_ids:
            raise ValueError(f"bulk heat {name} atom IDs differ from the model")


def bulk_heat_output_files(protocol: Mapping[str, Any]) -> list[str]:
    """Return raw native sidecars; the saved JSON source is written by finalize."""

    if not bulk_heat_enabled(protocol):
        return []
    validate_bulk_heat_protocol(protocol)
    return list(_OUTPUT_FILES)


def bulk_heat_before_run_commands(
    protocol: Mapping[str, Any], atom_map: Mapping[str, Any]
) -> list[str]:
    """Render Langevin reservoirs and the existing native thermal tables."""

    if not bulk_heat_enabled(protocol):
        return []
    validate_bulk_heat_protocol(protocol)
    _source_geometry(atom_map)
    source_to_native = _atom_map_ids(atom_map)
    hot = _reservoir(protocol, "hot")
    cold = _reservoir(protocol, "cold")
    for name, reservoir in (("hot", hot), ("cold", cold)):
        if not set(reservoir["atom_ids"]) <= set(source_to_native):
            raise ValueError(f"bulk heat {name} atom IDs must be present in atom map")
    sample_every = int(protocol["thermal"]["sample_every"])
    bin_count = int(protocol["thermal"]["bin_count"])
    return [
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
        (
            "fix mlcc_thermal_energy all ave/time "
            f"{sample_every} 1 {sample_every} f_mlcc_hot f_mlcc_cold "
            "mode scalar ave one file thermal-energy.dat"
        ),
        (
            "compute mlcc_thermal_bins all chunk/atom bin/1d z lower "
            f"{1.0 / bin_count:.12g} units reduced compress no"
        ),
        (
            "fix mlcc_thermal_profile all ave/chunk "
            f"{sample_every} 1 {sample_every} mlcc_thermal_bins temp "
            "norm sample ave one adof 3 cdof 0 file thermal-profile.dat"
        ),
    ]


def bulk_heat_after_run_commands(protocol: Mapping[str, Any]) -> list[str]:
    """Render cleanup in reverse fix/compute dependency order."""

    if not bulk_heat_enabled(protocol):
        return []
    validate_bulk_heat_protocol(protocol)
    return [
        "unfix mlcc_thermal_profile",
        "uncompute mlcc_thermal_bins",
        "unfix mlcc_thermal_energy",
        "unfix mlcc_cold",
        "unfix mlcc_hot",
    ]


def read_bulk_heat_outputs(
    directory: str | Path,
    protocol: Mapping[str, Any],
    atom_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Read the raw native thermal tables into a source-order bulk record."""

    if not bulk_heat_enabled(protocol):
        raise ValueError("read_bulk_heat_outputs requires purpose=bulk_thermal_transport")
    validate_bulk_heat_protocol(protocol)
    entries = _ordered_atom_entries(atom_map)
    source_cell, z_length, area = _source_geometry(atom_map)
    requested_area = float(protocol["thermal"]["area_angstrom2"])
    if not math.isclose(area, requested_area, rel_tol=0.0, abs_tol=1.0e-10):
        raise ValueError("bulk heat thermal area differs from atom-map source cell")
    output = Path(directory)
    log_path = output / "log.lammps"

    energy_path = output / _ENERGY_FILE
    profile_path = output / _PROFILE_FILE
    energy_rows = None if not energy_path.exists() else _parse_energy_rows(energy_path, protocol)
    profile_frames = (
        None
        if not profile_path.exists()
        else _parse_profile_frames(profile_path, protocol, z_length)
    )
    if profile_frames is not None:
        bin_count = int(protocol["thermal"]["bin_count"])
        if any(len(frame["bins"]) != bin_count for frame in profile_frames):
            raise ValueError("bulk heat profile frame bin count differs from protocol")
    missing_evidence: list[str] = []
    if energy_rows is None:
        missing_evidence.append(_ENERGY_FILE)
    if profile_frames is None:
        missing_evidence.append(_PROFILE_FILE)
    if energy_rows is not None and profile_frames is not None:
        energy_steps = [int(row["step"]) for row in energy_rows]
        profile_steps = [int(frame["step"]) for frame in profile_frames]
        if energy_steps != profile_steps:
            raise ValueError("bulk heat energy and profile steps differ")

    source_files = {
        "in.lammps": str(output / "in.lammps"),
        "log.lammps": str(log_path),
        "atom-map.json": str(output / "atom-map.json"),
        _ENERGY_FILE: str(energy_path),
        _PROFILE_FILE: str(profile_path),
    }
    source_atom_ids = [int(entry["source_atom_id"]) for entry in entries]
    return {
        "schema": _RESULT_SCHEMA,
        "units": "metal",
        "protocol": dict(protocol),
        "energy_rows": energy_rows,
        "profile_frames": profile_frames,
        "source_atom_ids": source_atom_ids,
        "atoms": [dict(entry) for entry in entries],
        "cell_angstrom": source_cell.tolist(),
        "atom_mapping_ref": "atom-map.json",
        "geometry": {
            "area_angstrom2": area,
            "normal_cartesian": list(_NORMAL),
            "z_length_angstrom": z_length,
        },
        "reservoir_tally_convention": {
            "quantity": "fix_langevin_scalar_reservoir_energy",
            "native_definition": "-energy_all",
            "raw_fields": ["f_mlcc_hot", "f_mlcc_cold"],
            "positive_direction": "energy_removed_from_system",
            "sign_transform": "none",
        },
        "source_files": source_files,
        "missing_evidence": missing_evidence,
        "production_qualification": False,
    }


__all__ = [
    "bulk_heat_after_run_commands",
    "bulk_heat_before_run_commands",
    "bulk_heat_enabled",
    "bulk_heat_output_files",
    "read_bulk_heat_outputs",
    "validate_bulk_heat_model",
    "validate_bulk_heat_protocol",
]
