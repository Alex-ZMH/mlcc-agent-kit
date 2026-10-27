"""Contract checks for the opt-in native bulk NPT thermo source.

The fixtures below exercise only parser/writer contracts.  They are not
scientific results and do not establish a thermal property or qualification.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase.calculators.lammps import Prism

from mlcc.lammps_bulk_thermal import (
    bulk_thermal_enabled,
    bulk_thermal_integrator_command,
    bulk_thermal_thermo_commands,
    read_bulk_thermal_outputs,
    validate_bulk_thermal_protocol,
)


def _protocol(*, purpose: str = "md_bulk_thermal") -> dict[str, object]:
    return {
        "kind": "md",
        "purpose": purpose,
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "npt",
        "temperature_K": 400.0,
        "seed": 12345,
        "timestep_ps": 0.1,
        "tdamp_ps": 1.0,
        "pdamp_ps": 10.0,
        "pressure_coupling": "iso",
        "pressure_target_bar": 0.0,
        "thermo_every": 10,
        "dump_every": 10,
        "steps": 30,
        "bulk_thermal": {
            "equilibration_steps": 10,
            "production_steps": 20,
        },
    }


def _atom_map() -> dict[str, object]:
    source_cell = np.asarray(
        [[0.0, 4.0, 0.0], [-5.0, 0.0, 0.0], [0.0, 0.0, 6.0]], dtype=float
    )
    prism = Prism(source_cell, pbc=True, reduce_cell=False)
    return {
        "schema": "mlcc.lammps-atom-map.v1",
        "source_atom_ids": [20, 5],
        "source_cell_angstrom": source_cell.tolist(),
        "lammps_prism": prism.get_lammps_prism().tolist(),
        "rotation_matrix_ase_to_lammps": prism.rot_mat.tolist(),
        "masses_by_type": {"1": 58.6934},
        "mass_units": "g/mol",
        "mass_source": "fixture map",
        "atoms": [
            {"source_index": 0, "source_atom_id": 20, "lammps_id": 2, "type": 1},
            {"source_index": 1, "source_atom_id": 5, "lammps_id": 1, "type": 1},
        ],
    }


def _log_text(protocol: dict[str, object]) -> str:
    thermo = "thermo_style custom " + " ".join(
        [
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
        ]
    )
    rows = [
        "0 400 -10 1 -9 0 120 4 5 6 0 0 0 1 2 3 4 5 6 0 0 0 0",
        "10 401 -9.5 1.1 -8.4 0.2 121 4.1 5.0 6.0 0.1 0.2 0.3 1.2 2.2 3.2 4.2 5.2 6.2 1.25 0.2 0.3 0.4",
        "20 402 -9.0 1.2 -7.8 0.4 122 4.2 5.0 6.0 0.2 0.4 0.6 1.4 2.4 3.4 4.4 5.4 6.4 2.5 0.4 0.5 0.6",
        "30 403 -8.5 1.3 -7.2 0.6 123 4.3 5.0 6.0 0.3 0.6 0.9 1.6 2.6 3.6 4.6 5.6 6.6 3.75 0.6 0.7 0.8",
    ]
    return "\n".join(
        [
            "LAMMPS (fixture)",
            "units metal",
            "atom_style atomic",
            "boundary p p p",
            bulk_thermal_integrator_command(protocol),
            *bulk_thermal_thermo_commands(protocol),
            "run 30",
            "Step  Temp PotEng  KinEng TotEng Press Volume  Lx Ly Lz Xy Xz Yz Pxx Pyy Pzz Pxy Pxz Pyz Time Xlo Ylo Zlo",
            *rows,
            "Loop time of 1.0 on 1 procs for 30 steps with 2 atoms",
            "Total wall time: 0:00:01",
            thermo,
        ]
    ) + "\n"


def _write_native(directory: Path, protocol: dict[str, object]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "in.lammps").write_text("# bulk thermal fixture\n", encoding="utf-8")
    (directory / "log.lammps").write_text(_log_text(protocol), encoding="utf-8")
    (directory / "atom-map.json").write_text(
        json.dumps(_atom_map(), indent=2) + "\n", encoding="utf-8"
    )


def test_bulk_thermal_npt_commands_and_windows_are_explicit() -> None:
    protocol = _protocol()
    assert bulk_thermal_enabled(protocol)
    validate_bulk_thermal_protocol(protocol)
    assert bulk_thermal_integrator_command(protocol) == (
        "fix integrator all npt temp 400 400 1 iso 0 0 10"
    )
    assert bulk_thermal_thermo_commands(protocol) == [
        "thermo_style custom step temp pe ke etotal press vol lx ly lz xy xz yz pxx pyy pzz pxy pxz pyz time xlo ylo zlo",
        "thermo_modify format float %.16g",
    ]

    protocol["ensemble"] = "nvt"
    with pytest.raises(ValueError, match="ensemble=npt"):
        validate_bulk_thermal_protocol(protocol)

    protocol = _protocol()
    protocol["bulk_thermal"] = {"equilibration_steps": 11, "production_steps": 20}
    with pytest.raises(ValueError, match="equal equilibration"):
        validate_bulk_thermal_protocol(protocol)


def test_bulk_thermal_reader_preserves_native_time_dynamic_cell_and_mapping(
    tmp_path: Path,
) -> None:
    protocol = _protocol()
    _write_native(tmp_path, protocol)

    result = read_bulk_thermal_outputs(tmp_path, protocol, _atom_map())

    assert result["schema"] == "mlcc.md-bulk-thermal-source.v1"
    assert result["target_temperature"] == {"value": 400.0, "unit": "K"}
    assert result["external_pressure"] == {"value": 0.0, "unit": "bar"}
    assert result["pressure_target_bar"] == 0.0
    assert result["mechanical_constraint"]["description"] == "isotropic fixed_shape"
    assert result["cell_basis"] == "source_cartesian"
    assert result["native_cell_basis"] == "lammps_restricted_triclinic"
    assert result["pressure_sign"] == "compression_positive"
    assert result["kinetic_included"] is True
    assert result["atom_ids"] == [20, 5]
    assert result["native_atom_ids"] == [2, 1]
    assert result["atom_mapping_ref"] == "atom-map.json"
    assert result["mass_units"] == "g/mol"
    assert [frame["step"] for frame in result["frames"]] == [0, 10, 20, 30]
    assert [frame["window"] for frame in result["frames"]] == [
        "equilibration",
        "production",
        "production",
        "production",
    ]
    assert [frame["physical_time_ps"] for frame in result["frames"]] == [
        0.0,
        1.25,
        2.5,
        3.75,
    ]
    assert result["frames"][1]["lammps_prism"] == [4.1, 5.0, 6.0, 0.1, 0.2, 0.3]
    assert result["frames"][1]["cell_lammps_angstrom"] == [
        [4.1, 0.0, 0.0],
        [0.1, 5.0, 0.0],
        [0.2, 0.3, 6.0],
    ]
    np.testing.assert_allclose(
        result["frames"][1]["cell_angstrom"],
        [[0.0, 4.1, 0.0], [-5.0, 0.1, 0.0], [-0.3, 0.2, 6.0]],
        atol=1.0e-12,
    )
    assert not np.allclose(
        np.asarray(result["frames"][1]["cell_angstrom"]),
        np.asarray(result["frames"][1]["cell_lammps_angstrom"]),
    )
    assert result["frames"][1]["origin_lammps_angstrom"] == [0.2, 0.3, 0.4]
    assert result["frames"][1]["potential_energy_eV"] == -9.5
    assert result["frames"][1]["kinetic_energy_eV"] == 1.1
    assert result["frames"][1]["pressure_components_bar"] == [1.2, 2.2, 3.2, 4.2, 5.2, 6.2]
    assert "initial_source_cell_angstrom" not in result["frames"][1]
    assert "atom_mapping" not in result["frames"][1]
    assert set(result["source_files"]) == {"in.lammps", "log.lammps", "atom-map.json"}


def test_bulk_thermal_reader_preserves_native_error_line(tmp_path: Path) -> None:
    protocol = _protocol()
    _write_native(tmp_path, protocol)
    (tmp_path / "log.lammps").write_text(
        (tmp_path / "log.lammps").read_text(encoding="utf-8")
        + "ERROR: native NPT failed\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="ERROR: native NPT failed"):
        read_bulk_thermal_outputs(tmp_path, protocol, _atom_map())
