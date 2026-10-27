"""Contract checks for the fixed-cell native bulk heat source adapter.

These fixtures only exercise command and source-record contracts.  They are
not native LAMMPS calculations and do not establish a thermal property or
production qualification.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.lammps import _native_input_commands, prepare_lammps
from mlcc.lammps_bulk_heat import (
    bulk_heat_after_run_commands,
    bulk_heat_before_run_commands,
    bulk_heat_output_files,
    read_bulk_heat_outputs,
    validate_bulk_heat_protocol,
)
from mlcc.modeling import ModelArtifacts


def _protocol(*, purpose: str = "bulk_thermal_transport") -> dict[str, object]:
    return {
        "kind": "md",
        "purpose": purpose,
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "nve",
        "temperature_K": 300.0,
        "seed": 202610261,
        "timestep_ps": 0.0001,
        "thermo_every": 10,
        "dump_every": 10,
        "steps": 20,
        "thermal": {
            "schema": "mlcc.bulk-heat-protocol.v1",
            "area_angstrom2": 20.0,
            "normal_cartesian": [0.0, 0.0, 1.0],
            "hot": {
                "atom_ids": [10],
                "temperature_K": 310.0,
                "damping_ps": 0.01,
                "seed": 202610262,
                "zero_random_force": True,
            },
            "cold": {
                "atom_ids": [20],
                "temperature_K": 290.0,
                "damping_ps": 0.01,
                "seed": 202610263,
                "zero_random_force": True,
            },
            "sample_every": 10,
            "bin_count": 16,
            "temperature_definition": "kinetic_3N_no_bias",
            "transport": {
                "periodic_channel_count": 2,
                "heat_fraction": 0.5,
                "heat_fraction_basis": "declared_equal_split_not_measured",
            },
        },
    }


def _atom_map() -> dict[str, object]:
    return {
        "source_atom_ids": [10, 20, 30],
        "source_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
        "atoms": [
            {"source_index": 0, "source_atom_id": 10, "lammps_id": 3, "type": 1, "element": "Ni"},
            {"source_index": 1, "source_atom_id": 20, "lammps_id": 1, "type": 1, "element": "Ni"},
            {"source_index": 2, "source_atom_id": 30, "lammps_id": 2, "type": 2, "element": "O"},
        ],
    }


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
                "10 16 3.0",
                *[
                    f"{index} {(index - 0.5) / 16:.8f} "
                    f"{2.0 if index == 1 else 1.0 if index == 2 else 0.0} "
                    f"{301.0 if index == 1 else 299.0 if index == 2 else 0.0}"
                    for index in range(1, 17)
                ],
                "20 16 3.0",
                *[
                    f"{index} {(index - 0.5) / 16:.8f} "
                    f"{2.0 if index == 1 else 1.0 if index == 2 else 0.0} "
                    f"{302.0 if index == 1 else 298.0 if index == 2 else 0.0}"
                    for index in range(1, 17)
                ],
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _prepare_model(tmp_path: Path) -> ModelArtifacts:
    atoms = Atoms(
        ["Ni", "O"],
        positions=[[0.2, 0.3, 0.4], [1.2, 1.3, 2.4]],
        cell=[[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([10, 20], dtype=int))
    return ModelArtifacts("bulk-heat-input-fixture", "v001", atoms, {}, tmp_path / "model")


def _prepare_potential(model_id: str) -> dict[str, object]:
    return {
        "potential_id": "NiO-eam-fixture",
        "version": "stable_22Jul2025_update2",
        "source": "fixture",
        "license": "fixture",
        "elements": ["Ni", "O"],
        "element_order": ["Ni", "O"],
        "model_ids": [model_id],
        "units": "metal",
        "atom_style": "atomic",
        "pair_style": "eam",
        "pair_coeff": ["* * NiO.eam.alloy"],
        "files": [{"local_path": "/potentials/NiO.eam.alloy", "filename": "NiO.eam.alloy"}],
        "fixture": True,
        "production_qualification": False,
    }


def test_bulk_heat_protocol_commands_and_output_contract_are_explicit() -> None:
    protocol = _protocol()
    validate_bulk_heat_protocol(protocol)
    assert bulk_heat_output_files(protocol) == ["thermal-energy.dat", "thermal-profile.dat"]
    commands = bulk_heat_before_run_commands(protocol, _atom_map())
    assert commands[:2] == [
        "group mlcc_thermal_hot id 3",
        "group mlcc_thermal_cold id 1",
    ]
    assert "fix mlcc_hot mlcc_thermal_hot langevin 310 310 0.01 202610262 zero yes tally yes" in commands
    assert "fix mlcc_cold mlcc_thermal_cold langevin 290 290 0.01 202610263 zero yes tally yes" in commands
    assert (
        "fix mlcc_thermal_energy all ave/time 10 1 10 f_mlcc_hot f_mlcc_cold "
        "mode scalar ave one file thermal-energy.dat"
    ) in commands
    assert (
        "compute mlcc_thermal_bins all chunk/atom bin/1d z lower 0.0625 "
        "units reduced compress no"
    ) in commands
    assert (
        "fix mlcc_thermal_profile all ave/chunk 10 1 10 mlcc_thermal_bins temp "
        "norm sample ave one adof 3 cdof 0 file thermal-profile.dat"
    ) in commands
    assert bulk_heat_after_run_commands(protocol) == [
        "unfix mlcc_thermal_profile",
        "uncompute mlcc_thermal_bins",
        "unfix mlcc_thermal_energy",
        "unfix mlcc_cold",
        "unfix mlcc_hot",
    ]


def test_bulk_heat_prepare_input_hook_and_raw_outputs_are_bound(tmp_path: Path) -> None:
    model = _prepare_model(tmp_path)
    protocol = _protocol()
    protocol["experiment_scope"] = "bulk heat input contract fixture"
    potential = _prepare_potential(model.model_id)

    prepared = prepare_lammps(
        model,
        tmp_path / "prepared",
        potential=potential,
        protocol=protocol,
    )
    input_lines = (tmp_path / "prepared" / "in.lammps").read_text(encoding="utf-8").splitlines()
    commands = _native_input_commands(
        potential,
        protocol,
        prepared["atom_map"]["masses_by_type"],
        prepared["atom_map"],
    )
    assert all(command in input_lines for command in commands)
    assert "fix mlcc_hot mlcc_thermal_hot langevin 310 310 0.01 202610262 zero yes tally yes" in input_lines
    method = json.loads((tmp_path / "prepared" / "method.json").read_text(encoding="utf-8"))
    assert method["files"]["thermal-energy.dat"].endswith("thermal-energy.dat")
    assert method["files"]["thermal-profile.dat"].endswith("thermal-profile.dat")


def test_bulk_heat_protocol_rejects_non_nve_or_missing_transport_contract() -> None:
    protocol = _protocol()
    protocol["ensemble"] = "nvt"
    with pytest.raises(ValueError, match="ensemble=nve"):
        validate_bulk_heat_protocol(protocol)

    protocol = _protocol()
    protocol["pdamp_ps"] = 1.0
    with pytest.raises(ValueError, match="pdamp_ps"):
        validate_bulk_heat_protocol(protocol)

    protocol = _protocol()
    protocol["thermal"] = dict(protocol["thermal"])
    protocol["thermal"]["bin_count"] = 1
    with pytest.raises(ValueError, match="at least 2"):
        validate_bulk_heat_protocol(protocol)

    protocol = _protocol()
    protocol["thermal"] = dict(protocol["thermal"])
    protocol["thermal"]["transport"] = dict(protocol["thermal"]["transport"])
    del protocol["thermal"]["transport"]["heat_fraction_basis"]
    with pytest.raises(ValueError, match="heat_fraction_basis"):
        validate_bulk_heat_protocol(protocol)

    protocol = _protocol()
    protocol["thermal"] = dict(protocol["thermal"])
    protocol["thermal"]["transport"] = {
        "periodic_channel_count": 3,
        "heat_fraction": 0.25,
        "heat_fraction_basis": "measured",
    }
    validate_bulk_heat_protocol(protocol)


def test_bulk_heat_reader_preserves_native_rows_mapping_geometry_and_tally_sign(tmp_path: Path) -> None:
    protocol = _protocol()
    _write_tables(tmp_path)
    result = read_bulk_heat_outputs(tmp_path, protocol, _atom_map())

    assert result["schema"] == "mlcc.md-bulk-heat-source.v1"
    assert result["units"] == "metal"
    assert result["source_atom_ids"] == [10, 20, 30]
    assert result["atoms"][0]["lammps_id"] == 3
    assert result["atom_mapping_ref"] == "atom-map.json"
    assert result["cell_angstrom"] == [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]]
    assert result["geometry"] == {
        "area_angstrom2": 20.0,
        "normal_cartesian": [0.0, 0.0, 1.0],
        "z_length_angstrom": 6.0,
    }
    assert [row["step"] for row in result["energy_rows"]] == [10, 20]
    assert result["energy_rows"][0]["hot_reservoir_eV"] == -2.5
    assert [frame["step"] for frame in result["profile_frames"]] == [10, 20]
    assert result["profile_frames"][0]["bins"][0]["temperature_K"] == 301.0
    assert result["reservoir_tally_convention"] == {
        "quantity": "fix_langevin_scalar_reservoir_energy",
        "native_definition": "-energy_all",
        "raw_fields": ["f_mlcc_hot", "f_mlcc_cold"],
        "positive_direction": "energy_removed_from_system",
        "sign_transform": "none",
    }
    assert result["missing_evidence"] == []
    assert result["production_qualification"] is False


def test_bulk_heat_reader_reports_missing_profile_without_fabricating_rows(tmp_path: Path) -> None:
    protocol = _protocol()
    _write_tables(tmp_path)
    (tmp_path / "thermal-profile.dat").unlink()

    result = read_bulk_heat_outputs(tmp_path, protocol, _atom_map())

    assert result["energy_rows"] is not None
    assert result["profile_frames"] is None
    assert result["missing_evidence"] == ["thermal-profile.dat"]
