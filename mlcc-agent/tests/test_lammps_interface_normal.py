"""Input-contract checks for the native LAMMPS normal-response path.

These checks cover protocol validation, source-to-native grouping, adjacent
point sequencing, and model lineage binding.  They do not construct a native
log or dump and therefore do not claim a LAMMPS result.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.lammps import validate_lammps_protocol
from mlcc.lammps_interface_normal import (
    normal_input_commands,
    normal_output_files,
    validate_normal_model,
    validate_normal_protocol,
)
from mlcc.modeling import ModelArtifacts


def _protocol() -> dict[str, object]:
    return {
        "kind": "interface_normal",
        "purpose": "interface_normal_response",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "none",
        "static_tensor": True,
        "experiment_scope": "Ni layered interface normal input contract",
        "timestep_ps": 0.001,
        "normal_response": {
            "schema": "mlcc.interface-normal-protocol.v1",
            "kinematics": "fixed_cell_rigid_side_translation",
            "normal_cartesian": [0.0, 0.0, 1.0],
            "area_angstrom2": 20.0,
            "interface_count": 2,
            "fixed_atom_ids": [20, 90],
            "moving_atom_ids": [5],
            "points": [
                {
                    "point_id": "reference",
                    "branch": "reference",
                    "displacement_angstrom": 0.0,
                },
                {
                    "point_id": "load",
                    "branch": "loading",
                    "displacement_angstrom": 0.01,
                },
                {
                    "point_id": "return",
                    "branch": "unloading",
                    "displacement_angstrom": 0.0,
                },
            ],
        },
    }


def _atom_map() -> dict[str, object]:
    return {
        "model_id": "ni-layered-fixture",
        "version": "v001",
        "source_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
        "atoms": [
            {"source_index": 0, "source_atom_id": 20, "lammps_id": 3, "type": 1},
            {"source_index": 1, "source_atom_id": 5, "lammps_id": 1, "type": 1},
            {"source_index": 2, "source_atom_id": 90, "lammps_id": 2, "type": 1},
        ],
    }


def _layered_model(tmp_path: Path) -> ModelArtifacts:
    cell = np.asarray([[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]])
    atoms = Atoms(
        ["Ni", "Ni", "Ni"],
        positions=[[0.2, 0.3, 0.4], [1.2, 1.3, 1.4], [2.2, 2.3, 2.4]],
        cell=cell,
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([20, 5, 90], dtype=int))
    metadata = {
        "spatial_mode": "layered_interface",
        "interface_geometry": {
            "normal_cartesian": [0.0, 0.0, 1.0],
            "area_angstrom2": 20.0,
            "interface_count": 2,
            "cell_angstrom": cell.tolist(),
        },
        "atom_lineage": [
            {"atom_id": 20, "side": "a"},
            {"atom_id": 5, "side": "b"},
            {"atom_id": 90, "side": "a"},
        ],
    }
    return ModelArtifacts("ni-layered-fixture", "v001", atoms, metadata, tmp_path / "model")


def test_protocol_and_native_input_preserve_groups_and_adjacent_q_sequence():
    protocol = _protocol()
    atom_map = _atom_map()

    validate_normal_protocol(protocol)
    validate_lammps_protocol(protocol)
    commands = normal_input_commands(protocol, atom_map)

    assert commands[0] == "group mlcc_normal_fixed id 3 2"
    assert commands[1] == "group mlcc_normal_moving id 1"
    assert commands[2] == "timestep 0.001"
    assert commands[3] == "thermo 1"
    moves = [command for command in commands if command.startswith("displace_atoms")]
    assert moves == [
        "displace_atoms mlcc_normal_moving move 0 0 0 units box",
        "displace_atoms mlcc_normal_moving move 0 0 0.01 units box",
        "displace_atoms mlcc_normal_moving move -0 -0 -0.01 units box",
    ]
    assert [command for command in commands if command == "run 0 pre yes"] == [
        "run 0 pre yes",
        "run 0 pre yes",
        "run 0 pre yes",
    ]
    assert normal_output_files(protocol) == [
        "dump.normal-0000",
        "dump.normal-0001",
        "dump.normal-0002",
    ]
    assert all(
        "xu yu zu fx fy fz" in command
        for command in commands
        if command.startswith("write_dump")
    )
    assert not any("fix setforce" in command or "storeforce" in command for command in commands)


def test_input_rejects_groups_that_do_not_cover_native_map():
    protocol = _protocol()
    protocol["normal_response"] = deepcopy(protocol["normal_response"])
    protocol["normal_response"]["fixed_atom_ids"] = [20, 999]

    with pytest.raises(ValueError, match="cover the atom map"):
        normal_input_commands(protocol, _atom_map())


def test_input_rejects_duplicate_native_mapping():
    atom_map = _atom_map()
    atom_map["atoms"] = deepcopy(atom_map["atoms"])
    atom_map["atoms"][1]["lammps_id"] = 3

    with pytest.raises(ValueError, match="duplicate source or native IDs"):
        normal_input_commands(_protocol(), atom_map)


def test_protocol_rejects_non_reference_first_point():
    protocol = _protocol()
    protocol["normal_response"] = deepcopy(protocol["normal_response"])
    protocol["normal_response"]["points"][0]["displacement_angstrom"] = 0.01

    with pytest.raises(ValueError, match="first point must be reference"):
        validate_normal_protocol(protocol)


def test_model_groups_and_saved_geometry_are_bound_to_lineage(tmp_path: Path):
    validate_normal_model(_layered_model(tmp_path), _protocol())

    protocol = _protocol()
    protocol["normal_response"] = deepcopy(protocol["normal_response"])
    protocol["normal_response"]["fixed_atom_ids"] = [20, 5]
    protocol["normal_response"]["moving_atom_ids"] = [90]
    with pytest.raises(ValueError, match="lineage side a"):
        validate_normal_model(_layered_model(tmp_path), protocol)
