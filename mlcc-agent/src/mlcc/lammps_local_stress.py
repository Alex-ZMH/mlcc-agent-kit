"""Thin native LAMMPS adapter for explicit per-atom virial stress output.

The adapter renders fixed-cell, zero-velocity ``run 0`` paths for interface
stress or explicit DeePMD centroid qualification and reads one native dump. It does
not divide a cell pressure among atoms, assign an atomic volume, rotate the
raw tensor out of the native Prism basis, or grant scientific qualification.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from pathlib import Path
from typing import Any

import numpy as np


_PROTOCOL_SCHEMA = "mlcc.local-stress-protocol.v1"
_RESULT_SCHEMA = "mlcc.lammps-local-stress.v1"
_LOCAL_STRESS_KIND = "run0"
_LOCAL_STRESS_PURPOSE = "interface_local_stress"
_QUALIFICATION_PURPOSE = "potential_qualification"
_DUMP_FILE = "local-stress.lammpstrj"
_LEGACY_COMPONENT_ORDER = ("xx", "yy", "zz", "xy", "xz", "yz")
_CENTROID_COMPONENT_ORDER = (
    "xx",
    "yy",
    "zz",
    "xy",
    "xz",
    "yz",
    "yx",
    "zx",
    "zy",
)


def _positive_finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def local_stress_enabled(protocol: Mapping[str, Any]) -> bool:
    """Return whether *protocol* requests the optional native local dump."""

    purpose = str(protocol.get("purpose", ""))
    return purpose == _LOCAL_STRESS_PURPOSE or (
        purpose == _QUALIFICATION_PURPOSE
        and str(protocol.get("kind", "")) == _LOCAL_STRESS_KIND
        and "local_stress" in protocol
    )


def _local_stress_record(protocol: Mapping[str, Any]) -> Mapping[str, Any]:
    local_stress = protocol.get("local_stress")
    if not isinstance(local_stress, Mapping):
        raise ValueError("local_stress must be an object")
    if local_stress.get("schema") != _PROTOCOL_SCHEMA:
        raise ValueError(f"local_stress schema must be {_PROTOCOL_SCHEMA}")
    if local_stress.get("contribution") != "virial":
        raise ValueError("local_stress contribution must be virial")
    return local_stress


def validate_local_stress_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate an explicit zero-velocity native local-stress protocol.

    ``interface_local_stress`` retains the historical six-component
    ``stress/atom`` output.  The optional ``potential_qualification`` route is
    enabled only by an explicit nine-component ``centroid/stress/atom`` record.
    """

    if str(protocol["kind"]) != _LOCAL_STRESS_KIND:
        raise ValueError("local stress protocol kind must be run0")
    purpose = str(protocol.get("purpose", ""))
    if purpose not in {_LOCAL_STRESS_PURPOSE, _QUALIFICATION_PURPOSE}:
        raise ValueError(
            "local stress protocol purpose must be interface_local_stress or potential_qualification"
        )
    if str(protocol["units"]) != "metal":
        raise ValueError("local stress protocol units must be metal")
    if [str(value) for value in protocol["boundary"]] != ["p", "p", "p"]:
        raise ValueError("local stress protocol boundary must be p p p")
    if protocol.get("static_tensor") is not True:
        raise ValueError("local stress protocol requires static_tensor=true")
    if "temperature_K" in protocol or "seed" in protocol:
        raise ValueError("local stress protocol must not define temperature_K or seed")
    _positive_finite(protocol["timestep_ps"], "timestep_ps")

    local_stress = _local_stress_record(protocol)
    compute_style = local_stress.get("compute_style")
    component_order = local_stress.get("component_order")
    if purpose == _LOCAL_STRESS_PURPOSE:
        # Missing fields preserve the v1 six-component contract for existing
        # records.  Explicit legacy metadata is accepted and checked exactly.
        if compute_style not in (None, "stress/atom"):
            raise ValueError("interface local stress requires compute_style=stress/atom")
        if component_order is not None and component_order != list(_LEGACY_COMPONENT_ORDER):
            raise ValueError("interface local stress component_order must be the legacy six components")
    else:
        if compute_style != "centroid/stress/atom":
            raise ValueError(
                "potential_qualification local stress requires compute_style=centroid/stress/atom"
            )
        if component_order != list(_CENTROID_COMPONENT_ORDER):
            raise ValueError(
                "potential_qualification local stress component_order must be the explicit nine components"
            )


def local_stress_compute_style(protocol: Mapping[str, Any]) -> str:
    """Return the validated native per-atom compute style."""

    validate_local_stress_protocol(protocol)
    local_stress = _local_stress_record(protocol)
    return str(local_stress.get("compute_style") or "stress/atom")


def local_stress_component_order(protocol: Mapping[str, Any]) -> list[str]:
    """Return the validated native component order for the local dump."""

    validate_local_stress_protocol(protocol)
    local_stress = _local_stress_record(protocol)
    component_order = local_stress.get("component_order")
    if component_order is None:
        return list(_LEGACY_COMPONENT_ORDER)
    return [str(value) for value in component_order]


def validate_local_stress_potential(
    protocol: Mapping[str, Any], potential: Mapping[str, Any]
) -> None:
    """Bind the centroid route to a DeepMD potential and configured plugin."""

    validate_local_stress_protocol(protocol)
    if local_stress_compute_style(protocol) != "centroid/stress/atom":
        return
    pair_style = str(potential.get("pair_style", "")).strip()
    if pair_style != "deepmd" and not pair_style.startswith("deepmd "):
        raise ValueError(
            "centroid/stress/atom local stress requires a DeepMD pair_style"
        )
    plugin = potential.get("plugin")
    if not isinstance(plugin, str) or not plugin.strip():
        raise ValueError(
            "centroid/stress/atom local stress requires an explicit DeepMD plugin"
        )


def validate_local_stress_model(model: Any, protocol: Mapping[str, Any]) -> None:
    """Bind the local-stress protocol to its persisted model."""

    validate_local_stress_protocol(protocol)
    if (
        str(protocol.get("purpose")) == _LOCAL_STRESS_PURPOSE
        and model.metadata.get("spatial_mode") != "layered_interface"
    ):
        raise ValueError("local stress requires spatial_mode=layered_interface")

    # Reuse the existing model/atom-ID and periodic-cell checks.  The local
    # stress path consumes source IDs from the same exported model and does not
    # introduce a second atom identity contract.
    from .lammps import _model_atoms

    _model_atoms(model)


def local_stress_before_run_commands(
    protocol: Mapping[str, Any], potential: Mapping[str, Any] | None = None
) -> list[str]:
    """Render the native compute and dump before the shared ``run 0``."""

    validate_local_stress_protocol(protocol)
    compute_style = local_stress_compute_style(protocol)
    if compute_style == "centroid/stress/atom":
        if potential is None:
            raise ValueError(
                "centroid/stress/atom local stress command rendering requires a potential"
            )
        validate_local_stress_potential(protocol, potential)
    component_order = local_stress_component_order(protocol)
    columns = " ".join(
        f"c_mlcc_local_stress[{index}]" for index in range(1, len(component_order) + 1)
    )
    return [
        f"compute mlcc_local_stress all {compute_style} NULL virial",
        f"dump mlcc_local_stress_dump all custom 1 {_DUMP_FILE} id type {columns}",
        "dump_modify mlcc_local_stress_dump sort id format float %.16g",
    ]


def local_stress_after_run_commands(protocol: Mapping[str, Any]) -> list[str]:
    """Render cleanup after the shared ``run 0`` and final dump."""

    validate_local_stress_protocol(protocol)
    return [
        "undump mlcc_local_stress_dump",
        "uncompute mlcc_local_stress",
    ]


def _ordered_atom_entries(atom_map: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries = atom_map["atoms"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("LAMMPS atom map contains no atoms")
    ordered = sorted(entries, key=lambda entry: int(entry["source_index"]))
    if [int(entry["source_index"]) for entry in ordered] != list(range(len(ordered))):
        raise ValueError("LAMMPS atom map source indices are not stable source order")

    source_ids = [int(entry["source_atom_id"]) for entry in ordered]
    native_ids = [int(entry["lammps_id"]) for entry in ordered]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("LAMMPS atom map contains duplicate source atom IDs")
    if len(set(native_ids)) != len(native_ids) or any(value < 1 for value in native_ids):
        raise ValueError("LAMMPS atom map contains duplicate or invalid native IDs")
    if [int(value) for value in atom_map["source_atom_ids"]] != source_ids:
        raise ValueError("LAMMPS atom map source IDs are inconsistent")
    return ordered


def _source_cell(atom_map: Mapping[str, Any]) -> np.ndarray:
    cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("LAMMPS atom map source cell is invalid")
    return cell


def _native_prism(atom_map: Mapping[str, Any]) -> np.ndarray:
    prism = np.asarray(atom_map["lammps_prism"], dtype=float)
    if prism.shape != (6,) or not np.all(np.isfinite(prism)):
        raise ValueError("LAMMPS atom map Prism parameters are invalid")
    return prism


def _result(
    protocol: Mapping[str, Any],
    source_cell: np.ndarray,
    source_path: Path,
    frames: list[dict[str, Any]] | None,
    missing_evidence: list[str],
    component_order: list[str],
    compute_style: str,
) -> dict[str, Any]:
    return {
        "schema": _RESULT_SCHEMA,
        "units": "metal",
        "stress_volume_unit": "bar*angstrom^3",
        "component_order": list(component_order),
        "compute_style": compute_style,
        "contribution": "virial",
        "kinetic_included": False,
        "tensor_basis": "native_prism",
        "stress_sign": "tension_positive",
        "protocol": dict(protocol),
        "source_cell_angstrom": source_cell.tolist(),
        "frames": frames,
        "source_files": {_DUMP_FILE: str(source_path)},
        "missing_evidence": list(missing_evidence),
        "production_qualification": False,
    }


def _parse_single_dump(
    text: str,
    atom_map: Mapping[str, Any],
    component_order: list[str],
) -> tuple[list[int], list[list[float]]]:
    from .lammps import _finite_row, _integer_token, _prism_from_lammps_bounds

    lines = text.splitlines()
    frame_starts = [
        index for index, line in enumerate(lines) if line.strip() == "ITEM: TIMESTEP"
    ]
    if len(frame_starts) != 1:
        raise ValueError("LAMMPS local-stress dump must contain exactly one native frame")
    frame = lines[frame_starts[0] :]
    if len(frame) < 9:
        raise ValueError("LAMMPS local-stress dump is missing the native frame")

    step = _integer_token(frame[1].strip(), context="local-stress dump timestep")
    if step != 0:
        raise ValueError("LAMMPS local-stress dump timestep must be zero")
    if frame[2].strip() != "ITEM: NUMBER OF ATOMS":
        raise ValueError("LAMMPS local-stress dump is missing the atom-count header")
    count = _integer_token(frame[3].strip(), context="local-stress dump atom count")
    if count < 1:
        raise ValueError("LAMMPS local-stress dump atom count must be positive")
    if not frame[4].startswith("ITEM: BOX BOUNDS"):
        raise ValueError("LAMMPS local-stress dump is missing the box header")
    box_header = frame[4].split()
    if box_header[3:6] != ["xy", "xz", "yz"] or box_header[6:] != ["pp", "pp", "pp"]:
        raise ValueError("LAMMPS local-stress dump box header is not triclinic p p p")
    box_rows = np.asarray(
        [_finite_row(frame[index].split(), context="local-stress dump box") for index in range(5, 8)],
        dtype=float,
    )
    if box_rows.shape != (3, 3):
        raise ValueError("LAMMPS local-stress dump box must contain three rows")
    if not frame[8].startswith("ITEM: ATOMS "):
        raise ValueError("LAMMPS local-stress dump is missing the atom header")
    expected_columns = ("id", "type") + tuple(
        f"c_mlcc_local_stress[{index}]" for index in range(1, len(component_order) + 1)
    )
    if tuple(frame[8].split()[2:]) != expected_columns:
        raise ValueError("LAMMPS local-stress dump atom columns differ from the fixed compute dump")
    data_end = 9 + count
    if len(frame) < data_end:
        raise ValueError("LAMMPS local-stress dump atom rows are incomplete")
    if any(line.strip() for line in frame[data_end:]):
        raise ValueError("LAMMPS local-stress dump contains data beyond the fixed single frame")

    rows: list[tuple[int, int, list[float]]] = []
    for line in frame[9:data_end]:
        tokens = line.split()
        if len(tokens) != len(expected_columns):
            raise ValueError("LAMMPS local-stress dump atom row has the wrong column count")
        atom_id = _integer_token(tokens[0], context="local-stress dump atom id")
        atom_type = _integer_token(tokens[1], context="local-stress dump atom type")
        components = _finite_row(tokens[2:], context="local-stress dump atom")
        rows.append((atom_id, atom_type, components))

    row_ids = [row[0] for row in rows]
    if len(set(row_ids)) != len(row_ids):
        raise ValueError("LAMMPS local-stress dump contains duplicate atom IDs")
    entries = _ordered_atom_entries(atom_map)
    if count != len(entries):
        raise ValueError("LAMMPS local-stress dump atom count differs from atom map")
    expected_by_id = {int(entry["lammps_id"]): entry for entry in entries}
    if set(row_ids) != set(expected_by_id):
        raise ValueError("LAMMPS local-stress dump atom IDs differ from atom map")
    rows_by_id = {row[0]: row for row in rows}
    for atom_id, atom_type, _components in rows:
        if atom_type != int(expected_by_id[atom_id]["type"]):
            raise ValueError("LAMMPS local-stress dump atom type differs from atom map")

    observed_prism = _prism_from_lammps_bounds(box_rows)
    expected_prism = _native_prism(atom_map)
    if not np.allclose(observed_prism, expected_prism, rtol=0.0, atol=1.0e-7):
        raise ValueError("LAMMPS local-stress dump box differs from atom-map Prism cell")

    source_ids = [int(entry["source_atom_id"]) for entry in entries]
    components = [rows_by_id[int(entry["lammps_id"])][2] for entry in entries]
    return source_ids, components


def read_local_stress_outputs(
    directory: str | Path,
    protocol: Mapping[str, Any],
    atom_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Read the one native local-stress dump without deriving atomic stress."""

    validate_local_stress_protocol(protocol)
    component_order = local_stress_component_order(protocol)
    compute_style = local_stress_compute_style(protocol)
    _ordered_atom_entries(atom_map)
    source_cell = _source_cell(atom_map)
    output = Path(directory)
    source_path = output / _DUMP_FILE
    if not source_path.exists():
        return _result(
            protocol,
            source_cell,
            source_path,
            None,
            [_DUMP_FILE],
            component_order,
            compute_style,
        )

    source_ids, components = _parse_single_dump(
        source_path.read_text(encoding="utf-8"), atom_map, component_order
    )
    return _result(
        protocol,
        source_cell,
        source_path,
        [
            {
                "step": 0,
                "physical_time_ps": 0.0,
                "atom_ids": source_ids,
                "stress_volume_components_bar_A3": components,
                "component_order": list(component_order),
            }
        ],
        [],
        component_order,
        compute_style,
    )


__all__ = [
    "local_stress_after_run_commands",
    "local_stress_before_run_commands",
    "local_stress_component_order",
    "local_stress_compute_style",
    "local_stress_enabled",
    "read_local_stress_outputs",
    "validate_local_stress_model",
    "validate_local_stress_potential",
    "validate_local_stress_protocol",
]
