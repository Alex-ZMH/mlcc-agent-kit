"""Native LAMMPS adapters for fixed-cell normal and tangential response paths.

The module only renders and reads the explicit interface response protocols. It
does not run LAMMPS or calculate a response from synthetic records. Domain
reduction of parsed points remains in the corresponding interface modules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from pathlib import Path
import re
from typing import Any

import numpy as np
from ase.calculators.lammps import Prism
from ase.data import atomic_numbers
from ase.io.lammpsdata import read_lammps_data


_PROTOCOL_SCHEMA = "mlcc.interface-normal-protocol.v1"
_RESULT_SCHEMA = "mlcc.lammps-normal-result.v1"
_NORMAL_KIND = "interface_normal"
_NORMAL_PURPOSE = "interface_normal_response"
_NORMAL_OUTPUT_PREFIX = "dump.normal-"
_NORMAL_DUMP_COORDINATES = ("xu", "yu", "zu")
_TANGENTIAL_PROTOCOL_SCHEMA = "mlcc.interface-tangential-protocol.v1"
_TANGENTIAL_RESULT_SCHEMA = "mlcc.lammps-tangential-result.v1"
_TANGENTIAL_KIND = "interface_tangential"
_TANGENTIAL_PURPOSE = "interface_tangential_response"
_TANGENTIAL_OUTPUT_PREFIX = "dump.tangential-"
_TANGENTIAL_DUMP_COORDINATES = ("xu", "yu", "zu")
_RIGID_KINEMATICS = "fixed_cell_rigid_side_translation"
_RELAX_KINEMATICS = "fixed_cell_clamped_internal_relaxation"
_RELAX_FORCE_SOURCE = "unconstrained_run0_at_minimized_geometry"
_NORMAL_MARKER = re.compile(
    r"^\s*MLCC_NORMAL\s+"
    r"index=(?P<index>\d+)\s+"
    r"pe=(?P<energy>[+\-0-9.eE]+)\s*$"
)
_NORMAL_MIN_BEGIN = re.compile(r"^\s*MLCC_NORMAL_MIN_BEGIN\s+index=(?P<index>\d+)\s*$")
_NORMAL_MIN_END = re.compile(r"^\s*MLCC_NORMAL_MIN_END\s+index=(?P<index>\d+)\s*$")
_TANGENTIAL_MARKER = re.compile(
    r"^\s*MLCC_TANGENTIAL\s+"
    r"index=(?P<index>\d+)\s+"
    r"pe=(?P<energy>[+\-0-9.eE]+)\s*$"
)
_TANGENTIAL_MIN_BEGIN = re.compile(
    r"^\s*MLCC_TANGENTIAL_MIN_BEGIN\s+index=(?P<index>\d+)\s*$"
)
_TANGENTIAL_MIN_END = re.compile(
    r"^\s*MLCC_TANGENTIAL_MIN_END\s+index=(?P<index>\d+)\s*$"
)


def _finite_vector(value: Any, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite length-3 vector")
    return result


def _positive_finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def _nonnegative_finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be non-negative and finite")
    return result


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _minimization_settings(
    response: Mapping[str, Any], response_name: str = "normal_response"
) -> dict[str, Any]:
    settings = response["minimization"]
    if not isinstance(settings, Mapping):
        raise ValueError(f"{response_name}.minimization must be an object")
    min_style = settings["min_style"]
    if min_style not in {"cg", "sd"}:
        raise ValueError(f"{response_name}.minimization.min_style must be cg or sd")
    etol = _nonnegative_finite(settings["etol"], f"{response_name}.minimization.etol")
    ftol = _nonnegative_finite(
        settings["ftol_eV_per_A"], f"{response_name}.minimization.ftol_eV_per_A"
    )
    if etol == 0.0 and ftol == 0.0:
        raise ValueError(
            f"{response_name}.minimization requires a positive etol or ftol_eV_per_A"
        )
    return {
        "min_style": min_style,
        "etol": etol,
        "ftol_eV_per_A": ftol,
        "maxiter": _positive_integer(
            settings["maxiter"], f"{response_name}.minimization.maxiter"
        ),
        "maxeval": _positive_integer(
            settings["maxeval"], f"{response_name}.minimization.maxeval"
        ),
    }


def _atom_id_list(value: Any, name: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
            raise ValueError(f"{name} must contain integer atom IDs")
        number = int(item)
        if number < 0:
            raise ValueError(f"{name} must contain non-negative atom IDs")
        result.append(number)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique atom IDs")
    return result


def _point_specs_for(
    protocol: Mapping[str, Any], response_key: str, response_name: str
) -> list[dict[str, Any]]:
    response = protocol[response_key]
    points = response["points"]
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError(f"{response_name}.points must contain at least two points")
    result: list[dict[str, Any]] = []
    point_ids: set[str] = set()
    for index, raw in enumerate(points):
        if not isinstance(raw, Mapping):
            raise ValueError(f"{response_name}.points[{index}] must be an object")
        point_id = raw["point_id"]
        if not isinstance(point_id, str) or not point_id or any(
            character.isspace() for character in point_id
        ) or any(character in point_id for character in ('"', "'")):
            raise ValueError(f"{response_name} point_id must be a non-empty token")
        if point_id in point_ids:
            raise ValueError(f"{response_name} point_id values must be unique")
        point_ids.add(point_id)
        branch = raw["branch"]
        if branch not in {"reference", "loading", "unloading"}:
            raise ValueError(f"{response_name} point branch is unsupported")
        displacement = float(raw["displacement_angstrom"])
        if not math.isfinite(displacement):
            raise ValueError(f"{response_name} point displacement must be finite")
        result.append(
            {
                "point_id": point_id,
                "branch": branch,
                "displacement_angstrom": displacement,
            }
        )
    if result[0]["branch"] != "reference" or result[0]["displacement_angstrom"] != 0.0:
        raise ValueError(f"{response_name} first point must be reference at zero displacement")
    return result


def _point_specs(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _point_specs_for(protocol, "normal_response", "normal_response")


def validate_normal_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate the explicit fixed-cell normal-response protocol."""

    if str(protocol["kind"]) != _NORMAL_KIND:
        raise ValueError("normal protocol kind must be interface_normal")
    if str(protocol["purpose"]) != _NORMAL_PURPOSE:
        raise ValueError("normal protocol purpose must be interface_normal_response")
    if str(protocol["units"]) != "metal":
        raise ValueError("normal protocol units must be metal")
    if [str(value) for value in protocol["boundary"]] != ["p", "p", "p"]:
        raise ValueError("normal protocol boundary must be p p p")
    if protocol.get("ensemble") != "none":
        raise ValueError("normal protocol ensemble must be none")
    if any(key in protocol for key in ("temperature_K", "seed", "steps", "tdamp_ps")):
        raise ValueError("normal static protocol does not accept MD temperature, seed, steps or thermostat settings")
    if protocol.get("static_tensor") is not True:
        raise ValueError("normal protocol requires static_tensor=true")
    if not isinstance(protocol["experiment_scope"], str) or not protocol["experiment_scope"].strip():
        raise ValueError("normal protocol requires a predeclared experiment_scope")
    _positive_finite(protocol["timestep_ps"], "timestep_ps")

    response = protocol["normal_response"]
    if not isinstance(response, Mapping):
        raise ValueError("normal_response must be an object")
    if response["schema"] != _PROTOCOL_SCHEMA:
        raise ValueError(f"normal_response schema must be {_PROTOCOL_SCHEMA}")
    if response["kinematics"] not in {_RIGID_KINEMATICS, _RELAX_KINEMATICS}:
        raise ValueError("normal_response kinematics is unsupported")
    normal = _finite_vector(response["normal_cartesian"], "normal_cartesian")
    if not math.isclose(float(np.linalg.norm(normal)), 1.0, rel_tol=0.0, abs_tol=1.0e-10):
        raise ValueError("normal_cartesian must be a unit vector")
    _positive_finite(response["area_angstrom2"], "area_angstrom2")
    if response["interface_count"] != 2:
        raise ValueError("interface_count must be exactly 2")
    fixed = _atom_id_list(response["fixed_atom_ids"], "fixed_atom_ids")
    moving = _atom_id_list(response["moving_atom_ids"], "moving_atom_ids")
    if set(fixed) & set(moving):
        raise ValueError("fixed_atom_ids and moving_atom_ids must not overlap")
    if response["kinematics"] == _RELAX_KINEMATICS:
        free = _atom_id_list(response["free_atom_ids"], "free_atom_ids")
        if set(fixed) & set(free) or set(moving) & set(free):
            raise ValueError("normal response clamped and free atom groups must not overlap")
        _minimization_settings(response)
    _point_specs(protocol)


def validate_normal_model(model: Any, protocol: Mapping[str, Any]) -> None:
    """Bind normal groups and geometry to a persisted layered model."""

    validate_normal_protocol(protocol)
    metadata = model.metadata
    if metadata.get("spatial_mode") != "layered_interface":
        raise ValueError("normal response requires spatial_mode=layered_interface")
    geometry = metadata["interface_geometry"]
    response = protocol["normal_response"]
    if not np.allclose(
        _finite_vector(response["normal_cartesian"], "normal_cartesian"),
        _finite_vector(geometry["normal_cartesian"], "saved normal_cartesian"),
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("normal response normal differs from saved interface geometry")
    if not math.isclose(
        float(response["area_angstrom2"]),
        float(geometry["area_angstrom2"]),
        rel_tol=0.0,
        abs_tol=1.0e-10,
    ):
        raise ValueError("normal response area differs from saved interface geometry")
    if response["interface_count"] != geometry["interface_count"]:
        raise ValueError("normal response interface_count differs from saved interface geometry")

    lineage = metadata["atom_lineage"]
    if not isinstance(lineage, list):
        raise ValueError("layered model atom_lineage must be a list")
    model_atom_ids = {int(value) for value in model.atom_ids}
    lineage_atom_ids = {int(entry["atom_id"]) for entry in lineage}
    if len(lineage) != len(model_atom_ids) or len(lineage_atom_ids) != len(lineage):
        raise ValueError("layered model atom_lineage must contain one entry per model atom")
    if lineage_atom_ids != model_atom_ids:
        raise ValueError("layered model atom_lineage atom IDs differ from model")
    side_a = {int(entry["atom_id"]) for entry in lineage if entry["side"] == "a"}
    side_b = {int(entry["atom_id"]) for entry in lineage if entry["side"] == "b"}
    if side_a | side_b != model_atom_ids or side_a & side_b:
        raise ValueError("layered model atom_lineage sides do not cover the model")
    fixed = {int(value) for value in response["fixed_atom_ids"]}
    moving = {int(value) for value in response["moving_atom_ids"]}
    if response["kinematics"] == _RIGID_KINEMATICS:
        if fixed != side_a:
            raise ValueError("fixed_atom_ids must exactly match lineage side a")
        if moving != side_b:
            raise ValueError("moving_atom_ids must exactly match lineage side b")
    else:
        free = {int(value) for value in response["free_atom_ids"]}
        if not fixed <= side_a:
            raise ValueError("fixed_atom_ids must be a subset of lineage side a")
        if not moving <= side_b:
            raise ValueError("moving_atom_ids must be a subset of lineage side b")
        if fixed & moving or fixed & free or moving & free:
            raise ValueError("normal response clamped and free atom groups must not overlap")
        if fixed | moving | free != model_atom_ids:
            raise ValueError("normal response clamped and free atom groups must cover the model")

    cell = np.asarray(geometry["cell_angstrom"], dtype=float)
    model_cell = np.asarray(model.atoms.cell.array, dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("saved interface geometry cell is invalid")
    if not np.allclose(model_cell, cell, rtol=0.0, atol=1.0e-10):
        raise ValueError("saved interface geometry cell differs from model")


def validate_tangential_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate the explicit fixed-cell tangential-response protocol."""

    if str(protocol["kind"]) != _TANGENTIAL_KIND:
        raise ValueError("tangential protocol kind must be interface_tangential")
    if str(protocol["purpose"]) != _TANGENTIAL_PURPOSE:
        raise ValueError(
            "tangential protocol purpose must be interface_tangential_response"
        )
    if str(protocol["units"]) != "metal":
        raise ValueError("tangential protocol units must be metal")
    if [str(value) for value in protocol["boundary"]] != ["p", "p", "p"]:
        raise ValueError("tangential protocol boundary must be p p p")
    if protocol.get("ensemble") != "none":
        raise ValueError("tangential protocol ensemble must be none")
    if any(key in protocol for key in ("temperature_K", "seed", "steps", "tdamp_ps")):
        raise ValueError(
            "tangential static protocol does not accept MD temperature, seed, steps or thermostat settings"
        )
    if protocol.get("static_tensor") is not True:
        raise ValueError("tangential protocol requires static_tensor=true")
    if not isinstance(protocol["experiment_scope"], str) or not protocol["experiment_scope"].strip():
        raise ValueError("tangential protocol requires a predeclared experiment_scope")
    _positive_finite(protocol["timestep_ps"], "timestep_ps")

    response = protocol["tangential_response"]
    if not isinstance(response, Mapping):
        raise ValueError("tangential_response must be an object")
    if response["schema"] != _TANGENTIAL_PROTOCOL_SCHEMA:
        raise ValueError(f"tangential_response schema must be {_TANGENTIAL_PROTOCOL_SCHEMA}")
    if response["kinematics"] != _RELAX_KINEMATICS:
        raise ValueError(
            "tangential_response kinematics must be fixed_cell_clamped_internal_relaxation"
        )
    normal = _finite_vector(response["normal_cartesian"], "normal_cartesian")
    tangent = _finite_vector(response["tangential_cartesian"], "tangential_cartesian")
    if not math.isclose(float(np.linalg.norm(normal)), 1.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("normal_cartesian must be a unit vector")
    if not math.isclose(float(np.linalg.norm(tangent)), 1.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("tangential_cartesian must be a unit vector")
    if not math.isclose(float(np.dot(normal, tangent)), 0.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("tangential_cartesian must be orthogonal to normal_cartesian")
    _positive_finite(response["area_angstrom2"], "area_angstrom2")
    if response["interface_count"] != 2:
        raise ValueError("interface_count must be exactly 2")
    fixed = _atom_id_list(response["fixed_atom_ids"], "fixed_atom_ids")
    moving = _atom_id_list(response["moving_atom_ids"], "moving_atom_ids")
    free = _atom_id_list(response["free_atom_ids"], "free_atom_ids")
    if set(fixed) & set(moving) or set(fixed) & set(free) or set(moving) & set(free):
        raise ValueError("tangential response clamped and free atom groups must not overlap")
    _minimization_settings(response, "tangential_response")
    _point_specs_for(protocol, "tangential_response", "tangential_response")


def validate_tangential_model(model: Any, protocol: Mapping[str, Any]) -> None:
    """Bind tangential groups and the normal direction to a layered model."""

    validate_tangential_protocol(protocol)
    metadata = model.metadata
    if metadata.get("spatial_mode") != "layered_interface":
        raise ValueError("tangential response requires spatial_mode=layered_interface")
    geometry = metadata["interface_geometry"]
    response = protocol["tangential_response"]
    if not np.allclose(
        _finite_vector(response["normal_cartesian"], "normal_cartesian"),
        _finite_vector(geometry["normal_cartesian"], "saved normal_cartesian"),
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("tangential response normal differs from saved interface geometry")
    if not math.isclose(
        float(response["area_angstrom2"]),
        float(geometry["area_angstrom2"]),
        rel_tol=0.0,
        abs_tol=1.0e-10,
    ):
        raise ValueError("tangential response area differs from saved interface geometry")
    if response["interface_count"] != geometry["interface_count"]:
        raise ValueError("tangential response interface_count differs from saved interface geometry")

    lineage = metadata["atom_lineage"]
    if not isinstance(lineage, list):
        raise ValueError("layered model atom_lineage must be a list")
    model_atom_ids = {int(value) for value in model.atom_ids}
    lineage_atom_ids = {int(entry["atom_id"]) for entry in lineage}
    if len(lineage) != len(model_atom_ids) or len(lineage_atom_ids) != len(lineage):
        raise ValueError("layered model atom_lineage must contain one entry per model atom")
    if lineage_atom_ids != model_atom_ids:
        raise ValueError("layered model atom_lineage atom IDs differ from model")
    side_a = {int(entry["atom_id"]) for entry in lineage if entry["side"] == "a"}
    side_b = {int(entry["atom_id"]) for entry in lineage if entry["side"] == "b"}
    if side_a | side_b != model_atom_ids or side_a & side_b:
        raise ValueError("layered model atom_lineage sides do not cover the model")
    fixed = {int(value) for value in response["fixed_atom_ids"]}
    moving = {int(value) for value in response["moving_atom_ids"]}
    free = {int(value) for value in response["free_atom_ids"]}
    if not fixed <= side_a:
        raise ValueError("fixed_atom_ids must be a subset of lineage side a")
    if not moving <= side_b:
        raise ValueError("moving_atom_ids must be a subset of lineage side b")
    if fixed & moving or fixed & free or moving & free:
        raise ValueError("tangential response clamped and free atom groups must not overlap")
    if fixed | moving | free != model_atom_ids:
        raise ValueError("tangential response clamped and free atom groups must cover the model")

    cell = np.asarray(geometry["cell_angstrom"], dtype=float)
    model_cell = np.asarray(model.atoms.cell.array, dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("saved interface geometry cell is invalid")
    if not np.allclose(model_cell, cell, rtol=0.0, atol=1.0e-10):
        raise ValueError("saved interface geometry cell differs from model")


def _atom_map_ids(atom_map: Mapping[str, Any]) -> dict[int, int]:
    entries = atom_map["atoms"]
    mapping: dict[int, int] = {}
    native_ids: set[int] = set()
    for entry in entries:
        source_id = int(entry["source_atom_id"])
        native_id = int(entry["lammps_id"])
        if source_id in mapping or native_id in native_ids:
            raise ValueError("LAMMPS atom map contains duplicate source or native IDs")
        mapping[source_id] = native_id
        native_ids.add(native_id)
    if not mapping:
        raise ValueError("LAMMPS atom map contains no atoms")
    return mapping


def _response_lammps_vector(
    protocol: Mapping[str, Any],
    atom_map: Mapping[str, Any],
    response_key: str,
    direction_key: str,
) -> np.ndarray:
    cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("LAMMPS atom map source cell is invalid")
    direction = _finite_vector(
        protocol[response_key][direction_key], direction_key
    )
    return np.asarray(
        Prism(cell, pbc=True, reduce_cell=False).vector_to_lammps(direction),
        dtype=float,
    )


def _normal_lammps_vector(protocol: Mapping[str, Any], atom_map: Mapping[str, Any]) -> np.ndarray:
    return _response_lammps_vector(protocol, atom_map, "normal_response", "normal_cartesian")


def _clamped_input_commands(
    protocol: Mapping[str, Any],
    atom_map: Mapping[str, Any],
    *,
    response_key: str,
    response_name: str,
    direction_key: str,
    group_prefix: str,
    marker_prefix: str,
    min_begin_prefix: str,
    min_end_prefix: str,
    output_prefix: str,
) -> list[str]:
    source_to_native = _atom_map_ids(atom_map)
    response = protocol[response_key]
    fixed = [int(value) for value in response["fixed_atom_ids"]]
    moving = [int(value) for value in response["moving_atom_ids"]]
    relaxation = response["kinematics"] == _RELAX_KINEMATICS
    free = [int(value) for value in response["free_atom_ids"]] if relaxation else []
    groups = [set(fixed), set(moving), set(free)] if relaxation else [set(fixed), set(moving)]
    if any(left & right for index, left in enumerate(groups) for right in groups[index + 1:]):
        raise ValueError(f"{response_name} atom groups must not overlap")
    if set().union(*groups) != set(source_to_native):
        raise ValueError(f"{response_name} atom groups must cover the atom map")
    fixed_native = [source_to_native[value] for value in fixed]
    moving_native = [source_to_native[value] for value in moving]
    free_native = [source_to_native[value] for value in free]
    direction_lammps = _response_lammps_vector(
        protocol, atom_map, response_key, direction_key
    )
    points = _point_specs_for(protocol, response_key, response_name)
    commands = [
        f"group {group_prefix}_fixed id " + " ".join(str(value) for value in fixed_native),
        f"group {group_prefix}_moving id " + " ".join(str(value) for value in moving_native),
    ]
    if relaxation:
        commands.append(
            f"group {group_prefix}_free id " + " ".join(str(value) for value in free_native)
        )
    commands.extend([f"timestep {float(protocol['timestep_ps']):.12g}", "thermo 1"])
    if relaxation:
        commands.extend(
            [
                "thermo_modify norm no",
                "neigh_modify every 1 delay 0 check yes",
            ]
        )
    minimization = _minimization_settings(response, response_name) if relaxation else None
    previous_q = 0.0
    for index, point in enumerate(points):
        displacement = float(point["displacement_angstrom"]) - previous_q
        move = direction_lammps * displacement
        commands.append(
            f"displace_atoms {group_prefix}_moving move "
            + " ".join(f"{float(value):.16g}" for value in move)
            + " units box"
        )
        if relaxation:
            commands.extend(
                [
                    f'print "{min_begin_prefix} index={index}"',
                    f"fix {group_prefix}_fixed_clamp {group_prefix}_fixed setforce 0 0 0",
                    f"fix {group_prefix}_moving_clamp {group_prefix}_moving setforce 0 0 0",
                    f"min_style {minimization['min_style']}",
                    "minimize "
                    f"{minimization['etol']:.16g} "
                    f"{minimization['ftol_eV_per_A']:.16g} "
                    f"{minimization['maxiter']} {minimization['maxeval']}",
                    f'print "{min_end_prefix} index={index}"',
                    f"unfix {group_prefix}_fixed_clamp",
                    f"unfix {group_prefix}_moving_clamp",
                    "run 0 pre yes",
                ]
            )
        else:
            commands.append("run 0 pre yes")
        commands.append(f'print "{marker_prefix} index={index} pe=$(pe:%.16g)"')
        commands.append(
            f"write_dump all custom {output_prefix}{index:04d} "
            "id type xu yu zu fx fy fz modify sort id format float %.16g"
        )
        previous_q = float(point["displacement_angstrom"])
    return commands


def normal_input_commands(protocol: Mapping[str, Any], atom_map: Mapping[str, Any]) -> list[str]:
    """Render the point sequence after the shared LAMMPS setup commands."""

    validate_normal_protocol(protocol)
    return _clamped_input_commands(
        protocol,
        atom_map,
        response_key="normal_response",
        response_name="normal_response",
        direction_key="normal_cartesian",
        group_prefix="mlcc_normal",
        marker_prefix="MLCC_NORMAL",
        min_begin_prefix="MLCC_NORMAL_MIN_BEGIN",
        min_end_prefix="MLCC_NORMAL_MIN_END",
        output_prefix=_NORMAL_OUTPUT_PREFIX,
    )


def tangential_input_commands(
    protocol: Mapping[str, Any], atom_map: Mapping[str, Any]
) -> list[str]:
    """Render the fixed-cell clamped tangential-response point sequence."""

    validate_tangential_protocol(protocol)
    return _clamped_input_commands(
        protocol,
        atom_map,
        response_key="tangential_response",
        response_name="tangential_response",
        direction_key="tangential_cartesian",
        group_prefix="mlcc_tangential",
        marker_prefix="MLCC_TANGENTIAL",
        min_begin_prefix="MLCC_TANGENTIAL_MIN_BEGIN",
        min_end_prefix="MLCC_TANGENTIAL_MIN_END",
        output_prefix=_TANGENTIAL_OUTPUT_PREFIX,
    )


def normal_output_files(protocol: Mapping[str, Any]) -> list[str]:
    """Return the deterministic native dump names for all response points."""

    validate_normal_protocol(protocol)
    return [f"{_NORMAL_OUTPUT_PREFIX}{index:04d}" for index, _ in enumerate(_point_specs(protocol))]


def tangential_output_files(protocol: Mapping[str, Any]) -> list[str]:
    """Return the deterministic native tangential dump names."""

    validate_tangential_protocol(protocol)
    return [
        f"{_TANGENTIAL_OUTPUT_PREFIX}{index:04d}"
        for index, _ in enumerate(
            _point_specs_for(protocol, "tangential_response", "tangential_response")
        )
    ]


def _source_rows(
    rows: Sequence[tuple[int, int, list[float], list[float]]],
    atom_map: Mapping[str, Any],
    *,
    coordinate_basis: str,
    response_name: str = "normal",
) -> tuple[list[int], list[list[float]], list[list[float]]]:
    entries = sorted(atom_map["atoms"], key=lambda entry: int(entry["source_index"]))
    rows_by_id = {int(row[0]): row for row in rows}
    expected_ids = {int(entry["lammps_id"]) for entry in entries}
    if set(rows_by_id) != expected_ids:
        raise ValueError(f"{response_name} dump atom IDs differ from atom map")
    for entry in entries:
        row = rows_by_id[int(entry["lammps_id"])]
        if int(row[1]) != int(entry["type"]):
            raise ValueError(f"{response_name} dump atom types differ from atom map")
    source_cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    prism = Prism(source_cell, pbc=True, reduce_cell=False)
    lammps_positions = np.asarray(
        [rows_by_id[int(entry["lammps_id"])][2] for entry in entries], dtype=float
    )
    lammps_forces = np.asarray(
        [rows_by_id[int(entry["lammps_id"])][3] for entry in entries], dtype=float
    )
    if coordinate_basis != "unwrapped_lammps_prism":
        raise ValueError(f"{response_name} parser requires unwrapped LAMMPS dump coordinates")
    positions = prism.vector_to_ase(lammps_positions, wrap=False)
    forces = prism.vector_to_ase(lammps_forces, wrap=False)
    return (
        [int(entry["source_atom_id"]) for entry in entries],
        np.asarray(positions, dtype=float).tolist(),
        np.asarray(forces, dtype=float).tolist(),
    )


def _reference_source_positions(
    model_data_path: Path,
    atom_map: Mapping[str, Any],
    response_name: str = "normal",
) -> tuple[list[int], np.ndarray]:
    """Read the exported unwrapped reference positions in source coordinates."""

    entries = sorted(atom_map["atoms"], key=lambda entry: int(entry["source_index"]))
    z_of_type = {
        int(type_id): atomic_numbers[str(element)]
        for type_id, element in enumerate(atom_map["element_order"], start=1)
    }
    data_atoms = read_lammps_data(
        str(model_data_path),
        Z_of_type=z_of_type,
        sort_by_id=True,
        units="metal",
        atom_style="atomic",
    )
    expected_ids = list(range(1, len(entries) + 1))
    if data_atoms.arrays["id"].tolist() != expected_ids:
        raise ValueError(
            f"LAMMPS {response_name} reference data atom IDs are not stable 1-based IDs"
        )
    expected_types = [int(entry["type"]) for entry in entries]
    if data_atoms.arrays["type"].tolist() != expected_types:
        raise ValueError(
            f"LAMMPS {response_name} reference data atom types differ from atom map"
        )
    source_cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    prism = Prism(source_cell, pbc=True, reduce_cell=False)
    source_positions = prism.vector_to_ase(
        np.asarray(data_atoms.positions, dtype=float), wrap=False
    )
    return [int(entry["source_atom_id"]) for entry in entries], np.asarray(
        source_positions, dtype=float
    )


def _marker_rows_for(
    log_text: str,
    points: Sequence[Mapping[str, Any]],
    marker_pattern: re.Pattern[str],
    response_name: str,
) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        match = marker_pattern.match(line)
        if match is None:
            continue
        markers.append(
            {
                "index": int(match.group("index")),
                "energy_eV": float(match.group("energy")),
            }
        )
    if len(markers) != len(points):
        raise ValueError(f"LAMMPS {response_name} log marker count differs from protocol points")
    for index, marker in enumerate(markers):
        if marker["index"] != index:
            raise ValueError(
                f"LAMMPS {response_name} log marker sequence differs from protocol points"
            )
        if not math.isfinite(marker["energy_eV"]):
            raise ValueError(f"LAMMPS {response_name} log marker energy is non-finite")
    return markers


def _marker_rows(log_text: str, points: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _marker_rows_for(log_text, points, _NORMAL_MARKER, "normal")


def _minimization_line(
    lines: Sequence[str], prefix: str, name: str, response_name: str = "normal"
) -> str:
    matches = [line.strip() for line in lines if line.strip().startswith(prefix)]
    if len(matches) != 1:
        raise ValueError(
            f"LAMMPS {response_name} minimization summary requires one {name} line"
        )
    return matches[0]


def _minimization_values(
    lines: Sequence[str], prefix: str, count: int, name: str, response_name: str = "normal",
) -> list[float]:
    matching = [
        (index, line.strip())
        for index, line in enumerate(lines)
        if line.strip().startswith(prefix)
    ]
    if len(matching) != 1:
        raise ValueError(
            f"LAMMPS {response_name} minimization summary requires one {name} line"
        )
    line_index, line = matching[0]
    if "=" not in line:
        raise ValueError(f"LAMMPS {response_name} minimization {name} line has no values")
    value_text = line.split("=", 1)[1].strip()
    if not value_text:
        if line_index + 1 >= len(lines):
            raise ValueError(f"LAMMPS {response_name} minimization {name} line has no values")
        value_text = lines[line_index + 1].strip()
    values = [float(value) for value in value_text.split()]
    if len(values) != count or not all(math.isfinite(value) for value in values):
        raise ValueError(f"LAMMPS {response_name} minimization {name} values are invalid")
    return values


def _minimization_integers(
    lines: Sequence[str], prefix: str, count: int, name: str, response_name: str = "normal",
) -> list[int]:
    values = _minimization_values(lines, prefix, count, name, response_name)
    integers = [int(value) for value in values]
    if any(value != raw for value, raw in zip(integers, values)):
        raise ValueError(
            f"LAMMPS {response_name} minimization {name} values are not integers"
        )
    return integers


def _minimization_rows_for(
    log_text: str,
    points: Sequence[Mapping[str, Any]],
    begin_pattern: re.Pattern[str],
    end_pattern: re.Pattern[str],
    response_name: str,
) -> list[dict[str, Any]]:
    lines = log_text.splitlines()
    blocks: list[tuple[int, list[str]]] = []
    begin: tuple[int, int] | None = None
    for line_index, line in enumerate(lines):
        begin_match = begin_pattern.match(line)
        end_match = end_pattern.match(line)
        if begin_match is not None:
            if begin is not None:
                raise ValueError(
                    f"LAMMPS {response_name} minimization begin markers are not paired"
                )
            index = int(begin_match.group("index"))
            if index != len(blocks):
                raise ValueError(
                    f"LAMMPS {response_name} minimization begin marker sequence differs from protocol points"
                )
            begin = (line_index, index)
        elif end_match is not None:
            if begin is None:
                raise ValueError(
                    f"LAMMPS {response_name} minimization end marker has no begin marker"
                )
            index = int(end_match.group("index"))
            if index != begin[1]:
                raise ValueError(
                    f"LAMMPS {response_name} minimization end marker sequence differs from begin marker"
                )
            blocks.append((index, lines[begin[0] + 1 : line_index]))
            begin = None
    if begin is not None:
        raise ValueError(f"LAMMPS {response_name} minimization begin marker has no end marker")
    if len(blocks) != len(points):
        raise ValueError(
            f"LAMMPS {response_name} minimization summary count differs from protocol points"
        )

    parsed: list[dict[str, Any]] = []
    for index, block in blocks:
        try:
            stats_index = next(
                offset for offset, line in enumerate(block)
                if line.strip() == "Minimization stats:"
            )
        except StopIteration as error:
            raise ValueError(
                f"LAMMPS {response_name} minimization point {index} has no native Minimization stats block"
            ) from error
        summary_lines = block[stats_index:]
        criterion_line = _minimization_line(
            summary_lines, "Stopping criterion", "stopping criterion", response_name
        )
        criterion = criterion_line.split("=", 1)[1].strip()
        energies = _minimization_values(
            summary_lines,
            "Energy initial, next-to-last, final",
            3,
            "energy",
            response_name,
        )
        force_two_norm = _minimization_values(
            summary_lines,
            "Force two-norm initial, final",
            2,
            "force two-norm",
            response_name,
        )
        force_max_component = _minimization_values(
            summary_lines,
            "Force max component initial, final",
            2,
            "force max component",
            response_name,
        )
        iterations, force_evaluations = _minimization_integers(
            summary_lines,
            "Iterations, force evaluations",
            2,
            "iterations",
            response_name,
        )
        parsed.append(
            {
                "stopping_criterion": criterion,
                "iterations": iterations,
                "force_evaluations": force_evaluations,
                "force_two_norm_initial": force_two_norm[0],
                "force_two_norm_final": force_two_norm[1],
                "force_max_component_initial": force_max_component[0],
                "force_max_component_final": force_max_component[1],
                "energy_initial": energies[0],
                "energy_penultimate": energies[1],
                "energy_final": energies[2],
                "raw_summary": "\n".join(summary_lines).strip(),
                "converged": criterion.lower() in {"energy tolerance", "force tolerance"},
            }
        )
    return parsed


def _minimization_rows(
    log_text: str, points: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return _minimization_rows_for(
        log_text,
        points,
        _NORMAL_MIN_BEGIN,
        _NORMAL_MIN_END,
        "normal",
    )


def _parse_response_outputs(
    directory: str | Path,
    method: Mapping[str, Any],
    atom_map: Mapping[str, Any],
    *,
    response_key: str,
    response_name: str,
    direction_key: str,
    output_prefix: str,
    dump_coordinates: tuple[str, str, str],
    marker_pattern: re.Pattern[str],
    min_begin_pattern: re.Pattern[str],
    min_end_pattern: re.Pattern[str],
    result_schema: str,
) -> dict[str, Any]:
    from .lammps import (
        _parse_dump,
        _validate_native_input_echo,
        _validate_native_log,
        _validate_potential,
        _validate_units_style,
        validate_lammps_protocol,
    )

    output = Path(directory)
    protocol = method["protocol"]
    validate_lammps_protocol(protocol)
    if method.get("engine") != "lammps":
        raise ValueError(f"{response_name} parser requires a LAMMPS method")
    units = str(method["units"])
    atom_style = str(method["atom_style"])
    _validate_units_style(units, atom_style)
    if method["production_qualification"] is not False:
        raise ValueError(f"{response_name} result production_qualification must remain false")
    if atom_map["model_id"] != method["model_id"] or atom_map["version"] != method["version"]:
        raise ValueError(f"{response_name} atom map identity differs from method.json")
    if atom_map["units"] != units or atom_map["atom_style"] != atom_style:
        raise ValueError(f"{response_name} atom map units or atom_style differs from method.json")
    if atom_map.get("coordinate_units") != "angstrom" or atom_map.get("mass_units") != "g/mol":
        raise ValueError(f"{response_name} atom map coordinate or mass units are invalid")
    if atom_map.get("lammps_origin_angstrom") != [0, 0, 0]:
        raise ValueError(f"{response_name} atom map origin must be [0, 0, 0] angstrom")
    entries = sorted(atom_map["atoms"], key=lambda entry: int(entry["source_index"]))
    map_elements = [str(value) for value in atom_map["element_order"]]
    if [int(entry["source_index"]) for entry in entries] != list(range(len(entries))):
        raise ValueError(f"{response_name} atom map source indices are not stable source order")
    if [int(value) for value in atom_map["source_atom_ids"]] != [
        int(entry["source_atom_id"]) for entry in entries
    ]:
        raise ValueError(f"{response_name} atom map source IDs are inconsistent")
    if [str(value) for value in method["element_order"]] != map_elements:
        raise ValueError(f"{response_name} method and atom map element_order differ")
    _validate_potential(
        method["potential"],
        model_id=str(method["model_id"]),
        model_elements=[str(entry["element"]) for entry in entries],
        element_order=map_elements,
        units=units,
        atom_style=atom_style,
        protocol=protocol,
    )
    for item in method["potential"]["files"]:
        filename = Path(str(item["filename"]))
        if filename.is_absolute() or ".." in filename.parts:
            raise ValueError("LAMMPS staged potential filename must stay inside the task directory")
        (output / filename).stat()

    log_path = output / "log.lammps"
    input_path = output / "in.lammps"
    model_data_path = output / "model.data"
    map_path = output / "atom-map.json"
    log_text = log_path.read_text(encoding="utf-8")
    input_text = input_path.read_text(encoding="utf-8")
    model_data_path.stat()
    reference_source_ids, reference_positions = _reference_source_positions(
        model_data_path, atom_map, response_name
    )
    engine_version = _validate_native_log(log_text)
    _validate_native_input_echo(
        log_text,
        input_text,
        method["potential"],
        protocol,
        atom_map["masses_by_type"],
        atom_map=atom_map,
    )
    points = _point_specs_for(protocol, response_key, f"{response_name}_response")
    markers = _marker_rows_for(log_text, points, marker_pattern, response_name)
    response = protocol[response_key]
    relaxation = response["kinematics"] == _RELAX_KINEMATICS
    minimizations = (
        _minimization_rows_for(
            log_text,
            points,
            min_begin_pattern,
            min_end_pattern,
            response_name,
        )
        if relaxation
        else []
    )
    direction = _finite_vector(response[direction_key], direction_key)
    fixed_ids = {int(value) for value in response["fixed_atom_ids"]}
    moving_ids = {int(value) for value in response["moving_atom_ids"]}
    source_ids = reference_source_ids
    parsed_points: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        dump_name = f"{output_prefix}{index:04d}"
        dump_path = output / dump_name
        dump_text = dump_path.read_text(encoding="utf-8")
        step, rows = _parse_dump(
            dump_text,
            atom_map,
            coordinate_columns=dump_coordinates,
        )
        if not relaxation and step != 0:
            raise ValueError(f"{response_name} response dump must record native step 0")
        point_source_ids, positions, forces = _source_rows(
            rows,
            atom_map,
            coordinate_basis="unwrapped_lammps_prism",
            response_name=response_name,
        )
        if point_source_ids != source_ids:
            raise ValueError(f"{response_name} response point atom order differs")
        observed_positions = np.asarray(positions, dtype=float)
        expected_positions = reference_positions.copy()
        for row_index, source_id in enumerate(source_ids):
            if source_id in moving_ids:
                expected_positions[row_index] += (
                    float(point["displacement_angstrom"]) * direction
                )
        if relaxation:
            constrained_indices = [
                row_index
                for row_index, source_id in enumerate(source_ids)
                if source_id in fixed_ids or source_id in moving_ids
            ]
            if not np.allclose(
                observed_positions[constrained_indices],
                expected_positions[constrained_indices],
                rtol=0.0,
                atol=1.0e-10,
            ):
                raise ValueError(
                    f"{response_name} response clamped/moving dump positions do not follow the explicit path"
                )
        elif not np.allclose(
            observed_positions,
            expected_positions,
            rtol=0.0,
            atol=1.0e-10,
        ):
            raise ValueError(
                f"{response_name} response dump positions do not follow the explicit unwrapped path"
            )
        point_result = {
            "point_id": point["point_id"],
            "branch": point["branch"],
            "displacement_angstrom": float(point["displacement_angstrom"]),
            "energy_eV": markers[index]["energy_eV"],
            "positions_angstrom": positions,
            "forces_eV_per_A": forces,
        }
        if relaxation:
            point_result.update(
                minimization=minimizations[index],
                native_step=step,
                force_source=_RELAX_FORCE_SOURCE,
            )
        parsed_points.append(point_result)

    source_files: dict[str, str] = {
        "method.json": str(output / "method.json"),
        "atom-map.json": str(map_path),
        "model.data": str(model_data_path),
        "in.lammps": str(input_path),
        "log.lammps": str(log_path),
    }
    map_path.stat()
    for index, _ in enumerate(points):
        source_files[f"{output_prefix}{index:04d}"] = str(output / f"{output_prefix}{index:04d}")
    for item in method["potential"]["files"]:
        filename = Path(str(item["filename"])).as_posix()
        source_files[filename] = str(output / filename)
    return {
        "schema": result_schema,
        "engine": "lammps",
        "engine_version": engine_version,
        "model_id": method["model_id"],
        "version": method["version"],
        "units": units,
        "atom_style": atom_style,
        "potential": method["potential"],
        "protocol": protocol,
        "atom_ids": source_ids,
        "points": parsed_points,
        "source_files": source_files,
        "production_qualification": False,
    }


def parse_normal_outputs(
    directory: str | Path,
    method: Mapping[str, Any],
    atom_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Parse one completed native normal-response output directory."""

    protocol = method["protocol"]
    validate_normal_protocol(protocol)
    return _parse_response_outputs(
        directory,
        method,
        atom_map,
        response_key="normal_response",
        response_name="normal",
        direction_key="normal_cartesian",
        output_prefix=_NORMAL_OUTPUT_PREFIX,
        dump_coordinates=_NORMAL_DUMP_COORDINATES,
        marker_pattern=_NORMAL_MARKER,
        min_begin_pattern=_NORMAL_MIN_BEGIN,
        min_end_pattern=_NORMAL_MIN_END,
        result_schema=_RESULT_SCHEMA,
    )


def parse_tangential_outputs(
    directory: str | Path,
    method: Mapping[str, Any],
    atom_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Parse one completed native tangential-response output directory."""

    protocol = method["protocol"]
    validate_tangential_protocol(protocol)
    return _parse_response_outputs(
        directory,
        method,
        atom_map,
        response_key="tangential_response",
        response_name="tangential",
        direction_key="tangential_cartesian",
        output_prefix=_TANGENTIAL_OUTPUT_PREFIX,
        dump_coordinates=_TANGENTIAL_DUMP_COORDINATES,
        marker_pattern=_TANGENTIAL_MARKER,
        min_begin_pattern=_TANGENTIAL_MIN_BEGIN,
        min_end_pattern=_TANGENTIAL_MIN_END,
        result_schema=_TANGENTIAL_RESULT_SCHEMA,
    )


__all__ = [
    "normal_input_commands",
    "normal_output_files",
    "parse_normal_outputs",
    "parse_tangential_outputs",
    "tangential_input_commands",
    "tangential_output_files",
    "validate_tangential_model",
    "validate_tangential_protocol",
    "validate_normal_model",
    "validate_normal_protocol",
]
