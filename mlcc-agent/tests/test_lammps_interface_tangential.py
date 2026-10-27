"""Static contract fixtures for the native tangential-response adapter.

The command and log snippets in this file are mathematical/text fixtures only;
they are not native LAMMPS results and do not establish a completed task.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from ase.calculators.lammps import Prism

from mlcc.lammps_interface_normal import (
    _TANGENTIAL_MARKER,
    _TANGENTIAL_MIN_BEGIN,
    _TANGENTIAL_MIN_END,
    _marker_rows_for,
    _minimization_rows_for,
    _source_rows,
    normal_input_commands,
    tangential_input_commands,
    tangential_output_files,
    validate_tangential_model,
    validate_tangential_protocol,
)


def _protocol() -> dict[str, object]:
    return {
        "kind": "interface_tangential",
        "purpose": "interface_tangential_response",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "none",
        "static_tensor": True,
        "experiment_scope": "mathematical fixture for clamped tangential response",
        "timestep_ps": 0.001,
        "tangential_response": {
            "schema": "mlcc.interface-tangential-protocol.v1",
            "kinematics": "fixed_cell_clamped_internal_relaxation",
            "normal_cartesian": [0.0, 0.0, 1.0],
            "tangential_cartesian": [1.0, 0.0, 0.0],
            "area_angstrom2": 12.3904,
            "interface_count": 2,
            "fixed_atom_ids": [0, 3],
            "moving_atom_ids": [4, 7],
            "free_atom_ids": [1, 2, 5, 6],
            "minimization": {
                "min_style": "cg",
                "etol": 0.0,
                "ftol_eV_per_A": 1.0e-6,
                "maxiter": 200,
                "maxeval": 2000,
            },
            "points": [
                {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
                {"point_id": "load", "branch": "loading", "displacement_angstrom": 0.01},
                {"point_id": "return", "branch": "unloading", "displacement_angstrom": 0.0},
            ],
        },
    }


def _atom_map() -> dict[str, object]:
    return {
        "model_id": "ni-layered-fixture",
        "version": "v001",
        "source_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
        "atoms": [
            {"source_index": index, "source_atom_id": index, "lammps_id": index + 1, "type": 1}
            for index in range(8)
        ],
    }


def _model() -> SimpleNamespace:
    cell = np.asarray([[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]])
    return SimpleNamespace(
        atom_ids=list(range(8)),
        atoms=SimpleNamespace(cell=SimpleNamespace(array=cell)),
        metadata={
            "spatial_mode": "layered_interface",
            "interface_geometry": {
                "normal_cartesian": [0.0, 0.0, 1.0],
                "area_angstrom2": 12.3904,
                "interface_count": 2,
                "cell_angstrom": cell.tolist(),
            },
            "atom_lineage": [
                {"atom_id": atom_id, "side": "a" if atom_id in {0, 3} else "b"}
                for atom_id in range(8)
            ],
        },
    )


def _normal_rigid_protocol() -> dict[str, object]:
    protocol = _protocol()
    return {
        "kind": "interface_normal",
        "purpose": "interface_normal_response",
        "units": protocol["units"],
        "boundary": protocol["boundary"],
        "ensemble": "none",
        "static_tensor": True,
        "experiment_scope": "legacy normal renderer compatibility fixture",
        "timestep_ps": protocol["timestep_ps"],
        "normal_response": {
            "schema": "mlcc.interface-normal-protocol.v1",
            "kinematics": "fixed_cell_rigid_side_translation",
            "normal_cartesian": [0.0, 0.0, 1.0],
            "area_angstrom2": 12.3904,
            "interface_count": 2,
            "fixed_atom_ids": [0, 3, 4, 7],
            "moving_atom_ids": [1, 2, 5, 6],
            "points": protocol["tangential_response"]["points"],
        },
    }


def _minimization_block(index: int, reason: str = "force tolerance") -> list[str]:
    return [
        f"MLCC_TANGENTIAL_MIN_BEGIN index={index}",
        "Minimization stats:",
        f"  Stopping criterion = {reason}",
        "  Energy initial, next-to-last, final = ",
        "    -10.0 -10.1 -10.1",
        "  Force two-norm initial, final = 2.0 1.0e-9",
        "  Force max component initial, final = 1.5 8.0e-10",
        "  Final line search alpha, max atom move = 1.0 0.01",
        "  Iterations, force evaluations = 7 9",
        f"MLCC_TANGENTIAL_MIN_END index={index}",
    ]


def test_tangential_protocol_checks_unit_orthogonal_directions_and_saved_normal():
    protocol = _protocol()
    validate_tangential_protocol(protocol)
    validate_tangential_model(_model(), protocol)

    alternate_tangent = deepcopy(protocol)
    alternate_tangent["tangential_response"]["tangential_cartesian"] = [0.0, 1.0, 0.0]
    validate_tangential_model(_model(), alternate_tangent)

    invalid = deepcopy(protocol)
    invalid["tangential_response"]["tangential_cartesian"] = [2.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="tangential_cartesian must be a unit vector"):
        validate_tangential_protocol(invalid)

    invalid = deepcopy(protocol)
    invalid["tangential_response"]["tangential_cartesian"] = [
        0.7071067811865476,
        0.0,
        0.7071067811865476,
    ]
    with pytest.raises(ValueError, match="orthogonal"):
        validate_tangential_protocol(invalid)

    invalid = deepcopy(protocol)
    invalid["tangential_response"]["normal_cartesian"] = [1.0, 0.0, 0.0]
    invalid["tangential_response"]["tangential_cartesian"] = [0.0, 1.0, 0.0]
    with pytest.raises(ValueError, match="normal differs"):
        validate_tangential_model(_model(), invalid)


def test_tangential_commands_use_incremental_t_move_and_restore_unclamped_forces():
    commands = tangential_input_commands(_protocol(), _atom_map())
    assert commands[:3] == [
        "group mlcc_tangential_fixed id 1 4",
        "group mlcc_tangential_moving id 5 8",
        "group mlcc_tangential_free id 2 3 6 7",
    ]
    assert [command for command in commands if command.startswith("displace_atoms")] == [
        "displace_atoms mlcc_tangential_moving move 0 0 0 units box",
        "displace_atoms mlcc_tangential_moving move 0.01 0 0 units box",
        "displace_atoms mlcc_tangential_moving move -0.01 -0 -0 units box",
    ]
    assert commands.count("fix mlcc_tangential_fixed_clamp mlcc_tangential_fixed setforce 0 0 0") == 3
    assert commands.count("fix mlcc_tangential_moving_clamp mlcc_tangential_moving setforce 0 0 0") == 3
    assert commands.count("min_style cg") == 3
    assert commands.count("minimize 0 1e-06 200 2000") == 3
    assert commands.count('print "MLCC_TANGENTIAL_MIN_BEGIN index=0"') == 1
    assert commands.count('print "MLCC_TANGENTIAL_MIN_END index=0"') == 1
    assert commands.count("unfix mlcc_tangential_fixed_clamp") == 3
    assert commands.count("unfix mlcc_tangential_moving_clamp") == 3
    assert commands.count("run 0 pre yes") == 3
    assert all("storeforce" not in command for command in commands)
    for index in range(3):
        begin = commands.index(f'print "MLCC_TANGENTIAL_MIN_BEGIN index={index}"')
        marker = commands.index(f'print "MLCC_TANGENTIAL index={index} pe=$(pe:%.16g)"')
        point_commands = commands[begin:marker + 1]
        ordered = [
            "fix mlcc_tangential_fixed_clamp mlcc_tangential_fixed setforce 0 0 0",
            "fix mlcc_tangential_moving_clamp mlcc_tangential_moving setforce 0 0 0",
            "minimize 0 1e-06 200 2000",
            f'print "MLCC_TANGENTIAL_MIN_END index={index}"',
            "unfix mlcc_tangential_fixed_clamp",
            "unfix mlcc_tangential_moving_clamp",
            "run 0 pre yes",
            f'print "MLCC_TANGENTIAL index={index} pe=$(pe:%.16g)"',
        ]
        offsets = [point_commands.index(command) for command in ordered]
        assert offsets == sorted(offsets)
    assert tangential_output_files(_protocol()) == [
        "dump.tangential-0000",
        "dump.tangential-0001",
        "dump.tangential-0002",
    ]


def test_normal_shared_renderer_keeps_legacy_marker_and_dump_path():
    commands = normal_input_commands(_normal_rigid_protocol(), _atom_map())
    assert commands[:4] == [
        "group mlcc_normal_fixed id 1 4 5 8",
        "group mlcc_normal_moving id 2 3 6 7",
        "timestep 0.001",
        "thermo 1",
    ]
    assert [command for command in commands if command.startswith('print "MLCC_NORMAL')] == [
        f'print "MLCC_NORMAL index={index} pe=$(pe:%.16g)"' for index in range(3)
    ]
    assert not any("MLCC_TANGENTIAL" in command for command in commands)
    assert [command for command in commands if command.startswith("write_dump")] == [
        "write_dump all custom dump.normal-0000 id type xu yu zu fx fy fz modify sort id format float %.16g",
        "write_dump all custom dump.normal-0001 id type xu yu zu fx fy fz modify sort id format float %.16g",
        "write_dump all custom dump.normal-0002 id type xu yu zu fx fy fz modify sort id format float %.16g",
    ]


def test_tangential_marker_and_minimization_fixtures_keep_native_stop_reason():
    lines: list[str] = []
    for index in range(3):
        lines.extend(_minimization_block(index, "max iterations" if index == 1 else "force tolerance"))
    log_text = "\n".join(lines)
    markers = _marker_rows_for(
        "\n".join(f"MLCC_TANGENTIAL index={index} pe=-10.{index}" for index in range(3)),
        [{}, {}, {}],
        _TANGENTIAL_MARKER,
        "tangential",
    )
    minimizations = _minimization_rows_for(
        log_text,
        [{}, {}, {}],
        _TANGENTIAL_MIN_BEGIN,
        _TANGENTIAL_MIN_END,
        "tangential",
    )
    assert [marker["index"] for marker in markers] == [0, 1, 2]
    assert minimizations[0]["converged"] is True
    assert minimizations[1]["converged"] is False
    assert minimizations[1]["stopping_criterion"] == "max iterations"
    assert minimizations[2]["raw_summary"].startswith("Minimization stats:")


def test_tangential_prism_rows_are_read_in_source_order_with_raw_force_vectors():
    atom_map = _atom_map()
    atom_map["source_cell_angstrom"] = [
        [4.0, 0.4, 0.2],
        [0.0, 5.0, 0.3],
        [0.0, 0.0, 6.0],
    ]
    source_positions = np.asarray(
        [[0.2, 0.3, 0.4], [1.1, 1.3, 1.5], [2.1, 2.2, 2.4], [3.0, 3.1, 3.3],
         [0.4, 1.1, 3.5], [1.4, 2.1, 4.5], [2.4, 3.1, 5.5], [3.4, 4.1, 0.5]],
        dtype=float,
    )
    source_forces = np.asarray(
        [[0.1, 0.2, 0.3], [0.2, 0.3, 0.4], [0.3, 0.4, 0.5], [0.4, 0.5, 0.6],
         [0.5, 0.6, 0.7], [0.6, 0.7, 0.8], [0.7, 0.8, 0.9], [0.8, 0.9, 1.0]],
        dtype=float,
    )
    prism = Prism(np.asarray(atom_map["source_cell_angstrom"], dtype=float), pbc=True, reduce_cell=False)
    move = [command for command in tangential_input_commands(_protocol(), atom_map)
            if command.startswith("displace_atoms")][1]
    assert [float(value) for value in move.split()[3:6]] == pytest.approx(
        prism.vector_to_lammps(np.asarray([0.01, 0.0, 0.0]))
    )
    rows = [
        (
            index + 1,
            1,
            prism.vector_to_lammps(source_positions[index]).tolist(),
            prism.vector_to_lammps(source_forces[index]).tolist(),
        )
        for index in range(8)
    ]
    atom_ids, positions, forces = _source_rows(
        rows,
        atom_map,
        coordinate_basis="unwrapped_lammps_prism",
    )
    assert atom_ids == list(range(8))
    assert np.asarray(positions) == pytest.approx(source_positions)
    assert np.asarray(forces) == pytest.approx(source_forces)
