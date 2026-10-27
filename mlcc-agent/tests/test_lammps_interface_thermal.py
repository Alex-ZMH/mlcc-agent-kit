"""Contract checks for the explicit native LAMMPS thermal adapter.

These tests cover command rendering and fixed-format table mathematics only.
They do not construct a native LAMMPS task or claim an engine result.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.lammps_interface_thermal import (
    read_thermal_outputs,
    thermal_after_run_commands,
    thermal_before_run_commands,
    validate_thermal_model,
    validate_thermal_protocol,
)
from mlcc.modeling import ModelArtifacts
from mlcc.interface_thermal import thermal_response_from_samples


def _protocol() -> dict[str, object]:
    return {
        "kind": "md",
        "purpose": "interface_thermal_response",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "nve",
        "steps": 100,
        "timestep_ps": 0.001,
        "temperature_K": 330.0,
        "seed": 17,
        "thermo_every": 10,
        "dump_every": 10,
        "thermal": {
            "schema": "mlcc.interface-thermal-protocol.v1",
            "area_angstrom2": 20.0,
            "normal_cartesian": [0.0, 0.0, 1.0],
            "interface_count": 2,
            "hot": {
                "atom_ids": [10, 30],
                "temperature_K": 400.0,
                "damping_ps": 0.1,
                "seed": 101,
                "zero_random_force": True,
            },
            "cold": {
                "atom_ids": [20],
                "temperature_K": 330.0,
                "damping_ps": 0.2,
                "seed": 202,
                "zero_random_force": False,
            },
            "sample_every": 10,
            "bin_width_angstrom": 1.5,
            "temperature_definition": "kinetic_3N_no_bias",
        },
    }


def _atom_map() -> dict[str, object]:
    return {
        "source_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
        "atoms": [
            {"source_atom_id": 10, "lammps_id": 4},
            {"source_atom_id": 20, "lammps_id": 1},
            {"source_atom_id": 30, "lammps_id": 3},
            {"source_atom_id": 40, "lammps_id": 2},
        ]
    }


def _layered_model(tmp_path: Path) -> ModelArtifacts:
    cell = np.asarray([[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]])
    atoms = Atoms(
        ["Ni", "Ni", "Ni", "Ni"],
        positions=[
            [0.2, 0.3, 0.4],
            [1.2, 1.3, 1.4],
            [2.2, 2.3, 2.4],
            [3.2, 3.3, 3.4],
        ],
        cell=cell,
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([10, 20, 30, 40], dtype=int))
    metadata = {
        "spatial_mode": "layered_interface",
        "interface_geometry": {
            "normal_cartesian": [0.0, 0.0, 1.0],
            "area_angstrom2": 20.0,
            "interface_count": 2,
            "cell_angstrom": cell.tolist(),
        },
    }
    return ModelArtifacts("ni-layered-fixture", "v001", atoms, metadata, tmp_path / "model")


def _write_tables(directory: Path) -> None:
    (directory / "thermal-energy.dat").write_text(
        "\n".join(
            [
                "# Time-averaged data for fix mlcc_thermal_energy",
                "# TimeStep f_mlcc_hot f_mlcc_cold",
                "10 -2.500000000000 1.250000000000",
                "20 -4.000000000000 2.000000000000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "thermal-profile.dat").write_text(
        "\n".join(
            [
                "# Chunk-averaged data for fix mlcc_thermal_profile and group all",
                "# Timestep Number-of-chunks Total-count",
                "# Chunk Coord1 Ncount temp",
                "10 3 3.0",
                "1 0.125000 2.0 401.0",
                "2 0.375000 0.0 0.0",
                "3 0.625000 1e+00 329.0",
                "20 3 3e0",
                "1 0.125000 2.0 402.0",
                "2 0.375000 0.0 0.0",
                "3 0.625000 1.0 328.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_protocol_commands_and_reverse_cleanup_are_explicit():
    protocol = _protocol()
    validate_thermal_protocol(protocol)
    commands = thermal_before_run_commands(protocol, _atom_map())

    assert commands[:2] == [
        "group mlcc_thermal_hot id 4 3",
        "group mlcc_thermal_cold id 1",
    ]
    assert "fix mlcc_hot mlcc_thermal_hot langevin 400 400 0.1 101 zero yes tally yes" in commands
    assert "fix mlcc_cold mlcc_thermal_cold langevin 330 330 0.2 202 zero no tally yes" in commands
    assert (
        "fix mlcc_thermal_energy all ave/time 10 1 10 f_mlcc_hot f_mlcc_cold "
        "mode scalar ave one file thermal-energy.dat"
    ) in commands
    assert "compute mlcc_thermal_bins all chunk/atom bin/1d z lower 0.25 units reduced compress no" in commands
    assert (
        "fix mlcc_thermal_profile all ave/chunk 10 1 10 mlcc_thermal_bins temp "
        "norm sample ave one adof 3 cdof 0 file thermal-profile.dat"
    ) in commands
    assert thermal_after_run_commands(protocol) == [
        "unfix mlcc_thermal_profile",
        "uncompute mlcc_thermal_bins",
        "unfix mlcc_thermal_energy",
        "unfix mlcc_cold",
        "unfix mlcc_hot",
    ]


def test_protocol_rejects_overlap_or_wrong_temperature_definition():
    protocol = _protocol()
    protocol["thermal"] = deepcopy(protocol["thermal"])
    protocol["thermal"]["cold"] = deepcopy(protocol["thermal"]["cold"])
    protocol["thermal"]["cold"]["atom_ids"] = [30]
    with pytest.raises(ValueError, match="must not overlap"):
        validate_thermal_protocol(protocol)

    protocol = _protocol()
    protocol["thermal"] = deepcopy(protocol["thermal"])
    protocol["thermal"]["temperature_definition"] = "kinetic_3N_com_removed"
    with pytest.raises(ValueError, match="temperature_definition"):
        validate_thermal_protocol(protocol)


def test_model_geometry_and_reservoir_ids_bind_to_saved_layered_model(tmp_path: Path):
    validate_thermal_model(_layered_model(tmp_path), _protocol())

    protocol = _protocol()
    protocol["thermal"] = deepcopy(protocol["thermal"])
    protocol["thermal"]["area_angstrom2"] = 21.0
    with pytest.raises(ValueError, match="area differs"):
        validate_thermal_model(_layered_model(tmp_path), protocol)


def test_reader_preserves_energy_sign_and_empty_profile_bins(tmp_path: Path):
    _write_tables(tmp_path)
    result = read_thermal_outputs(tmp_path, _protocol(), _atom_map())

    assert result["energy_rows"][0] == {
        "step": 10,
        "physical_time_ps": 0.01,
        "hot_reservoir_eV": -2.5,
        "cold_reservoir_eV": 1.25,
    }
    assert result["profile_frames"][0]["bins"][1] == {
        "bin_id": 2,
        "coordinate_reduced": 0.375,
        "coordinate_angstrom": 2.25,
        "atom_count": 0.0,
        "temperature_K": 0.0,
    }
    assert result["profile_frames"][0]["total_count"] == 3.0
    assert result["missing_evidence"] == []
    assert result["production_qualification"] is False

    response = thermal_response_from_samples(
        {
            "schema": "mlcc.interface-thermal-analysis.v1",
            "source_kind": "mathematical_fixture",
            "fixture": True,
            "observation_window": {"kind": "step_range", "start_step": 10, "end_step": 20},
            "area_angstrom2": 20.0,
            "normal_cartesian": [0.0, 0.0, 1.0],
            "interface_count": 2,
            "temperature_pairs": [
                {"interface_id": "AB", "upstream_bin_ids": [1], "downstream_bin_ids": [3], "direction_sign": 1},
                {"interface_id": "BA", "upstream_bin_ids": [3], "downstream_bin_ids": [1], "direction_sign": -1},
            ],
            "heat_allocation": None,
        },
        result["energy_rows"],
        result["profile_frames"],
    )
    assert response["energy"]["power"]["hot_input_eV_per_ps"] == pytest.approx(150.0)
    assert response["energy"]["power"]["cold_extraction_eV_per_ps"] == pytest.approx(75.0)
    assert response["temperature"]["pairs"][0]["temperature_difference_K"] == pytest.approx(73.0)
    assert response["temperature"]["pairs"][0]["heat_flux_J_W_per_m2"] is None


def test_reader_reports_missing_tables_independently(tmp_path: Path):
    _write_tables(tmp_path)
    (tmp_path / "thermal-profile.dat").unlink()

    result = read_thermal_outputs(tmp_path, _protocol(), _atom_map())

    assert result["energy_rows"] is not None
    assert result["profile_frames"] is None
    assert result["missing_evidence"] == ["thermal-profile.dat"]


def test_reader_rejects_nonuniform_sample_spacing(tmp_path: Path):
    _write_tables(tmp_path)
    path = tmp_path / "thermal-energy.dat"
    path.write_text(path.read_text(encoding="utf-8").replace("20 -4.000", "25 -4.000"), encoding="utf-8")

    with pytest.raises(ValueError, match="sample_every"):
        read_thermal_outputs(tmp_path, _protocol(), _atom_map())
