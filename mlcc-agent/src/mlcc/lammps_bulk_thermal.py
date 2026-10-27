"""Opt-in native NPT thermo source for bulk thermal experiments.

This module is intentionally smaller than the fixed-cell MD sampling route.
It does not add a dump or a sidecar file: the native LAMMPS thermo table is
the sole source for the complete NPT record.  The table keeps the raw
restricted-triclinic cell and the native ``Time`` column for every observed
thermo frame.  No thermal expansion, density, heat-capacity, averaging, or
qualification decision is made here.
"""

from __future__ import annotations

from pathlib import Path
import math
from typing import Any, Mapping

import numpy as np
from ase.calculators.lammps import Prism


_PURPOSE = "md_bulk_thermal"
_RESULT_SCHEMA = "mlcc.md-bulk-thermal-source.v1"
_THERMO_KEYWORDS = (
    "step",
    "temp",
    "pe",
    "ke",
    "etotal",
    "press",
    "vol",
    "lx",
    "ly",
    "lz",
    "xy",
    "xz",
    "yz",
    "pxx",
    "pyy",
    "pzz",
    "pxy",
    "pxz",
    "pyz",
    "time",
    "xlo",
    "ylo",
    "zlo",
)
_THERMO_FIELDS = (
    "Step",
    "Temp",
    "PotEng",
    "KinEng",
    "TotEng",
    "Press",
    "Volume",
    "Lx",
    "Ly",
    "Lz",
    "Xy",
    "Xz",
    "Yz",
    "Pxx",
    "Pyy",
    "Pzz",
    "Pxy",
    "Pxz",
    "Pyz",
    "Time",
    "Xlo",
    "Ylo",
    "Zlo",
)
_THERMO_COMMAND = " ".join(_THERMO_KEYWORDS)
_PRESSURE_COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz"]
_SOURCE_FILES = ("in.lammps", "log.lammps", "atom-map.json")


def bulk_thermal_enabled(protocol: Mapping[str, Any]) -> bool:
    """Return whether the explicit native bulk-thermal route is requested."""

    return isinstance(protocol, Mapping) and protocol.get("purpose") == _PURPOSE


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"bulk thermal {name} must be a positive integer")
    result = int(value)
    if result <= 0:
        raise ValueError(f"bulk thermal {name} must be a positive integer")
    return result


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"bulk thermal {name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"bulk thermal {name} must be a finite number")
    return result


def _bulk_record(protocol: Mapping[str, Any]) -> Mapping[str, Any]:
    record = protocol.get("bulk_thermal")
    if not isinstance(record, Mapping):
        raise ValueError("md_bulk_thermal requires a bulk_thermal object")
    equilibration_steps = _positive_int(
        record.get("equilibration_steps"), "bulk_thermal.equilibration_steps"
    )
    production_steps = _positive_int(
        record.get("production_steps"), "bulk_thermal.production_steps"
    )
    steps = _positive_int(protocol.get("steps"), "steps")
    if steps != equilibration_steps + production_steps:
        raise ValueError(
            "md_bulk_thermal steps must equal equilibration plus production steps"
        )
    cadence = _positive_int(protocol.get("thermo_every"), "thermo_every")
    if equilibration_steps % cadence or production_steps % cadence:
        raise ValueError("bulk thermal windows must lie on the native thermo grid")
    return record


def validate_bulk_thermal_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate only the additional NPT bulk-thermal protocol contract.

    Common MD fields (temperature, seed, timestep, thermo cadence, and the
    ordinary positive-step checks) remain owned by the shared LAMMPS
    validator.  This function is a no-op for every other protocol purpose.
    """

    if not bulk_thermal_enabled(protocol):
        return
    if protocol.get("kind") != "md":
        raise ValueError("md_bulk_thermal requires protocol kind=md")
    if protocol.get("units") != "metal":
        raise ValueError("md_bulk_thermal requires units=metal")
    if [str(value) for value in protocol.get("boundary", [])] != ["p", "p", "p"]:
        raise ValueError("md_bulk_thermal requires periodic boundary p p p")
    if protocol.get("ensemble") != "npt":
        raise ValueError("md_bulk_thermal requires ensemble=npt")
    if protocol.get("static_tensor") is True:
        raise ValueError("md_bulk_thermal does not allow static_tensor=true")
    if protocol.get("pressure_coupling") != "iso":
        raise ValueError("md_bulk_thermal requires pressure_coupling=iso")
    _finite_number(
        protocol.get("pressure_target_bar"), "pressure_target_bar"
    )
    _finite_positive = _finite_number(protocol.get("pdamp_ps"), "pdamp_ps")
    if _finite_positive <= 0.0:
        raise ValueError("bulk thermal pdamp_ps must be positive and finite")
    _bulk_record(protocol)


def bulk_thermal_integrator_command(protocol: Mapping[str, Any]) -> str:
    """Return the one native isotropic NPT integrator command."""

    if not bulk_thermal_enabled(protocol):
        return ""
    validate_bulk_thermal_protocol(protocol)
    temperature = float(protocol["temperature_K"])
    target_pressure = float(protocol["pressure_target_bar"])
    pdamp = float(protocol["pdamp_ps"])
    tdamp = float(protocol["tdamp_ps"])
    return (
        f"fix integrator all npt temp {temperature:.12g} {temperature:.12g} "
        f"{tdamp:.12g} iso {target_pressure:.12g} {target_pressure:.12g} {pdamp:.12g}"
    )


def bulk_thermal_thermo_commands(protocol: Mapping[str, Any]) -> list[str]:
    """Return the exact native thermo table and high-precision formatting."""

    if not bulk_thermal_enabled(protocol):
        return []
    validate_bulk_thermal_protocol(protocol)
    return [
        f"thermo_style custom {_THERMO_COMMAND}",
        "thermo_modify format float %.16g",
    ]


def _ordered_atom_entries(atom_map: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries = atom_map.get("atoms")
    if not isinstance(entries, list) or not entries:
        raise ValueError("LAMMPS atom map contains no atoms")
    try:
        ordered = sorted(entries, key=lambda entry: int(entry["source_index"]))
        for entry in ordered:
            for key in ("source_index", "source_atom_id", "lammps_id", "type"):
                if key not in entry:
                    raise ValueError(f"LAMMPS atom map atom mapping is missing {key}")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("LAMMPS atom map source indices are invalid") from error
    return ordered


def _map_geometry(
    atom_map: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], np.ndarray, np.ndarray, np.ndarray]:
    entries = _ordered_atom_entries(atom_map)
    source_cell = np.asarray(atom_map.get("source_cell_angstrom"), dtype=float)
    if source_cell.shape != (3, 3) or not np.all(np.isfinite(source_cell)):
        raise ValueError("LAMMPS atom map source cell is invalid")
    if abs(float(np.linalg.det(source_cell))) <= 1.0e-12:
        raise ValueError("LAMMPS atom map source cell has zero volume")
    prism = Prism(source_cell, pbc=True, reduce_cell=False)
    raw_prism = np.asarray(atom_map.get("lammps_prism"), dtype=float)
    if raw_prism.shape != (6,) or not np.all(np.isfinite(raw_prism)):
        raise ValueError("LAMMPS atom map Prism parameters are invalid")
    rotation = np.asarray(
        atom_map.get("rotation_matrix_ase_to_lammps", prism.rot_mat), dtype=float
    )
    if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
        raise ValueError("LAMMPS atom map Prism rotation is invalid")
    return entries, source_cell, raw_prism, rotation


def _window_record(protocol: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    record = protocol["bulk_thermal"]
    equilibration_steps = int(record["equilibration_steps"])
    production_end = equilibration_steps + int(record["production_steps"])
    thermo_every = protocol.get("thermo_every")
    if (
        isinstance(thermo_every, (int, np.integer))
        and 0 < int(thermo_every) <= equilibration_steps
    ):
        equilibration_end = equilibration_steps - int(thermo_every)
    else:
        equilibration_end = equilibration_steps - 1
    return {
        "equilibration": {
            "name": "equilibration",
            "start_step": 0,
            "end_step": equilibration_end,
            "closed": True,
        },
        "production": {
            "name": "production",
            "start_step": equilibration_steps,
            "end_step": production_end,
            "closed": True,
        },
    }


def _read_thermo_rows(
    text: str, protocol: Mapping[str, Any]
) -> list[dict[str, Any]]:
    from .lammps import _finite_row, _integer_token, _validate_native_log

    _validate_native_log(text)
    lines = text.splitlines()
    headers = [index for index, line in enumerate(lines) if tuple(line.split()) == _THERMO_FIELDS]
    if len(headers) != 1:
        raise ValueError("LAMMPS bulk thermal log must contain the exact thermo header once")
    header = headers[0]
    rows: list[dict[str, Any]] = []
    loop_seen = False
    for line in lines[header + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Loop time"):
            loop_seen = True
            break
        tokens = stripped.split()
        if len(tokens) != len(_THERMO_FIELDS):
            raise ValueError("LAMMPS bulk thermal thermo row differs from the exact header")
        step = _integer_token(tokens[0], context="bulk thermal thermo step")
        values = _finite_row(tokens[1:], context="bulk thermal thermo")
        lx, ly, lz = values[6:9]
        if lx <= 0.0 or ly <= 0.0 or lz <= 0.0:
            raise ValueError("LAMMPS bulk thermal thermo cell lengths must be positive")
        volume = values[5]
        if volume <= 0.0:
            raise ValueError("LAMMPS bulk thermal thermo volume must be positive")
        physical_time = values[18]
        if rows and step <= int(rows[-1]["step"]):
            raise ValueError("LAMMPS bulk thermal thermo steps are not strictly increasing")
        if rows and physical_time <= float(rows[-1]["physical_time_ps"]):
            raise ValueError("LAMMPS bulk thermal native Time values are not strictly increasing")
        rows.append(
            {
                "step": step,
                "physical_time_ps": physical_time,
                "temperature_K": values[0],
                "potential_energy_eV": values[1],
                "kinetic_energy_eV": values[2],
                "total_energy_eV": values[3],
                "volume_angstrom3": volume,
                "pressure_bar": values[4],
                "pressure_components_bar": values[12:18],
                "lammps_prism": [lx, ly, lz, values[9], values[10], values[11]],
                "cell_lammps_angstrom": [
                    [lx, 0.0, 0.0],
                    [values[9], ly, 0.0],
                    [values[10], values[11], lz],
                ],
                "origin_lammps_angstrom": values[19:22],
            }
        )
    if not loop_seen:
        raise ValueError("LAMMPS bulk thermal log is missing the native Loop terminator")
    if not rows:
        raise ValueError("LAMMPS bulk thermal log contains no native thermo data")
    if int(rows[0]["step"]) != 0:
        raise ValueError("LAMMPS bulk thermal thermo sequence must begin at native step 0")
    final_step = int(protocol["steps"])
    if int(rows[-1]["step"]) != final_step:
        raise ValueError("LAMMPS bulk thermal thermo sequence final step differs from protocol")
    thermo_every = protocol.get("thermo_every")
    if isinstance(thermo_every, (int, np.integer)) and int(thermo_every) > 0:
        expected_steps = list(range(0, final_step + 1, int(thermo_every)))
        if expected_steps[-1] != final_step:
            expected_steps.append(final_step)
        if [int(row["step"]) for row in rows] != expected_steps:
            raise ValueError("LAMMPS bulk thermal thermo sequence has missing or conflicting native steps")
    return rows


def read_bulk_thermal_outputs(
    directory: str | Path,
    protocol: Mapping[str, Any],
    atom_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Read one completed native NPT thermo table into source-order metadata."""

    validate_bulk_thermal_protocol(protocol)
    if not bulk_thermal_enabled(protocol):
        raise ValueError("read_bulk_thermal_outputs requires purpose=md_bulk_thermal")
    entries, source_cell, initial_prism, rotation = _map_geometry(atom_map)
    output = Path(directory)
    input_path = output / "in.lammps"
    log_path = output / "log.lammps"
    atom_map_path = output / "atom-map.json"
    input_path.stat()
    atom_map_path.stat()
    log_text = log_path.read_text(encoding="utf-8")
    rows = _read_thermo_rows(log_text, protocol)
    windows = _window_record(protocol)
    source_atom_ids = [int(entry["source_atom_id"]) for entry in entries]
    native_atom_ids = [int(entry["lammps_id"]) for entry in entries]
    frames: list[dict[str, Any]] = []
    for row in rows:
        step = int(row["step"])
        window = (
            "equilibration"
            if step < int(protocol["bulk_thermal"]["equilibration_steps"])
            else "production"
        )
        cell_lammps = np.asarray(row["cell_lammps_angstrom"], dtype=float)
        cell_source = cell_lammps @ rotation.T
        frames.append(
            {
                **row,
                "frame_index": len(frames),
                "window": window,
                "window_interval": dict(windows[window]),
                "cell_angstrom": cell_source.tolist(),
            }
        )
    atom_mapping = [
        {
            "source_index": int(entry["source_index"]),
            "source_atom_id": int(entry["source_atom_id"]),
            "lammps_id": int(entry["lammps_id"]),
            "type": int(entry["type"]),
        }
        for entry in entries
    ]
    source_files = {name: str(output / name) for name in _SOURCE_FILES}
    pressure_target = float(protocol["pressure_target_bar"])
    target_temperature = float(protocol["temperature_K"])
    return {
        "schema": _RESULT_SCHEMA,
        "units": "metal",
        "protocol": dict(protocol),
        "target_temperature_K": target_temperature,
        "target_temperature": {"value": target_temperature, "unit": "K"},
        "pressure_target_bar": pressure_target,
        "external_pressure_bar": pressure_target,
        "external_pressure": {"value": pressure_target, "unit": "bar"},
        "mechanical_constraint": {
            "kind": "isotropic",
            "shape": "fixed_shape",
            "description": "isotropic fixed_shape",
            "pressure_coupling": "iso",
            "pressure_target_bar": pressure_target,
        },
        "pressure_unit": "bar",
        "pressure_component_order": list(_PRESSURE_COMPONENT_ORDER),
        "pressure_sign": "compression_positive",
        "kinetic_included": True,
        "cell_basis": "source_cartesian",
        "native_cell_basis": "lammps_restricted_triclinic",
        "source_cell_angstrom": source_cell.tolist(),
        "initial_lammps_prism": initial_prism.tolist(),
        "rotation_matrix_ase_to_lammps": rotation.tolist(),
        "atom_mapping_ref": "atom-map.json",
        "atom_ids": list(source_atom_ids),
        "source_atom_ids": list(source_atom_ids),
        "native_atom_ids": list(native_atom_ids),
        "atom_mapping": atom_mapping,
        "atoms": [dict(entry) for entry in atom_map["atoms"]],
        "masses_by_type": dict(atom_map.get("masses_by_type", {})),
        "mass_units": atom_map.get("mass_units"),
        "mass_source": atom_map.get("mass_source"),
        "sampling_windows": windows,
        "frames": frames,
        "source_files": source_files,
        "production_qualification": False,
    }


__all__ = [
    "bulk_thermal_enabled",
    "bulk_thermal_integrator_command",
    "bulk_thermal_thermo_commands",
    "read_bulk_thermal_outputs",
    "validate_bulk_thermal_protocol",
]
