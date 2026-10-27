"""Tests for the opt-in native rich MD sampling artifact."""

from __future__ import annotations

from pathlib import Path

import pytest

from mlcc.lammps_md_sampling import (
    md_sampling_after_run_commands,
    md_sampling_before_run_commands,
    md_sampling_enabled,
    md_sampling_output_files,
    read_md_sampling_outputs,
    validate_md_sampling_potential,
    validate_md_sampling_protocol,
)


COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz", "yx", "zx", "zy"]


def _protocol(*, purpose: str = "md_native_sampling") -> dict[str, object]:
    return {
        "kind": "md",
        "purpose": purpose,
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "nvt",
        "temperature_K": 400.0,
        "seed": 12345,
        "timestep_ps": 0.0001,
        "tdamp_ps": 0.1,
        "thermo_every": 10,
        "dump_every": 10,
        "steps": 30,
        "unwrapped_trajectory": True,
        "native_sampling": {
            "schema": "mlcc.lammps-md-sampling-protocol.v1",
            "equilibration_steps": 10,
            "production_steps": 20,
            "component_order": list(COMPONENT_ORDER),
        },
    }


def _potential() -> dict[str, object]:
    return {
        "pair_style": "deepmd frozen.pth",
        "plugin": "/opt/deepmd/libdeepmd_lmpplugin.so",
    }


def _atom_map() -> dict[str, object]:
    return {
        "source_atom_ids": [20, 5, 90],
        "source_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
        "lammps_prism": [4.0, 5.0, 6.0, 0.0, 0.0, 0.0],
        "atoms": [
            {"source_index": 0, "source_atom_id": 20, "lammps_id": 3, "type": 1},
            {"source_index": 1, "source_atom_id": 5, "lammps_id": 1, "type": 1},
            {"source_index": 2, "source_atom_id": 90, "lammps_id": 2, "type": 1},
        ],
    }


def _native_echo(protocol: dict[str, object]) -> str:
    commands = [
        "units metal",
        "atom_style atomic",
        "boundary p p p",
        "velocity all create 400 12345 mom yes rot no dist gaussian",
        "timestep 0.0001",
        "fix integrator all nvt temp 400 400 0.1",
        "dump trajectory_unwrapped all custom 10 trajectory.unwrapped.lammpstrj id type xu yu zu",
        "dump_modify trajectory_unwrapped sort id format float %.16g",
        *md_sampling_before_run_commands(protocol),
        "run 30",
    ]
    return "\n".join(commands) + "\n"


def _thermo_log(protocol: dict[str, object]) -> str:
    rows = [
        "0 300.0 -1.0 0.1 -0.9 2.0",
        "10 305.0 -1.1 0.2 -0.9 3.0",
        "20 400.0 -1.2 0.3 -0.9 4.0",
        "30 401.0 -1.3 0.4 -0.9 5.0",
    ]
    return _native_echo(protocol) + "Step Temp PotEng KinEng TotEng Press\n" + "\n".join(rows) + "\n"


def _pressure_series() -> str:
    return "\n".join(
        [
            "# Time-averaged data for fix mlcc_sampling_pressure_series",
            "# TimeStep c_mlcc_sampling_temp c_mlcc_sampling_pressure "
            "c_mlcc_sampling_pressure[1] c_mlcc_sampling_pressure[2] "
            "c_mlcc_sampling_pressure[3] c_mlcc_sampling_pressure[4] "
            "c_mlcc_sampling_pressure[5] c_mlcc_sampling_pressure[6]",
            "10 305.0 3.0 30.0 31.0 32.0 33.0 34.0 35.0",
            "20 400.0 4.0 40.0 41.0 42.0 43.0 44.0 45.0",
            "30 401.0 5.0 50.0 51.0 52.0 53.0 54.0 55.0",
            "",
        ]
    )


def _sampling_dump() -> str:
    header = "ITEM: ATOMS " + " ".join(
        [
            "id",
            "type",
            "xu",
            "yu",
            "zu",
            "ix",
            "iy",
            "iz",
            "vx",
            "vy",
            "vz",
            *[f"c_mlcc_sampling_virial[{index}]" for index in range(1, 10)],
        ]
    )
    blocks: list[str] = []
    for step in (0, 10, 20, 30):
        rows = [
            "1 1 1.0 2.0 3.0 0 0 0 0.1 0.2 0.3 1 2 3 4 5 6 7 8 9",
            "2 1 2.0 3.0 4.0 1 -1 0 0.4 0.5 0.6 10 11 12 13 14 15 16 17 18",
            "3 1 3.0 4.0 5.0 -1 0 1 0.7 0.8 0.9 19 20 21 22 23 24 25 26 27",
        ]
        blocks.extend(
            [
                "ITEM: TIMESTEP",
                str(step),
                "ITEM: NUMBER OF ATOMS",
                "3",
                "ITEM: BOX BOUNDS xy xz yz pp pp pp",
                "0.0 4.0 0.0",
                "0.0 5.0 0.0",
                "0.0 6.0 0.0",
                header,
                *rows,
            ]
        )
    return "\n".join(blocks) + "\n"


def _write_native(directory: Path, protocol: dict[str, object]) -> None:
    (directory / "in.lammps").write_text(_native_echo(protocol), encoding="utf-8")
    (directory / "log.lammps").write_text(_thermo_log(protocol), encoding="utf-8")
    (directory / "sampling.lammpstrj").write_text(_sampling_dump(), encoding="utf-8")
    (directory / "pressure-series.dat").write_text(_pressure_series(), encoding="utf-8")


def test_sampling_protocol_commands_are_opt_in_and_explicit() -> None:
    protocol = _protocol()
    assert md_sampling_enabled(protocol)
    validate_md_sampling_protocol(protocol)
    validate_md_sampling_potential(protocol, _potential())

    commands = md_sampling_before_run_commands(protocol)
    assert commands[0] == "compute mlcc_sampling_virial all centroid/stress/atom NULL virial"
    assert "id type xu yu zu ix iy iz vx vy vz" in commands[1]
    assert "c_mlcc_sampling_virial[9]" in commands[1]
    assert commands[2] == "dump_modify mlcc_sampling_trajectory sort id format float %.16g"
    assert commands[3] == "compute mlcc_sampling_temp all temp"
    assert commands[4] == "compute mlcc_sampling_pressure all pressure mlcc_sampling_temp"
    assert "ave/time 10 1 10 c_mlcc_sampling_temp c_mlcc_sampling_pressure" in commands[5]
    assert commands[5].endswith('file pressure-series.dat format " %.16g"')
    assert md_sampling_after_run_commands(protocol) == [
        "unfix mlcc_sampling_pressure_series",
        "undump mlcc_sampling_trajectory",
        "uncompute mlcc_sampling_pressure",
        "uncompute mlcc_sampling_temp",
        "uncompute mlcc_sampling_virial",
    ]
    assert md_sampling_output_files(protocol) == ["sampling.lammpstrj", "pressure-series.dat"]


def test_sampling_rejects_non_nvt_or_out_of_range_seed() -> None:
    protocol = _protocol()
    protocol["ensemble"] = "nve"
    with pytest.raises(ValueError, match="ensemble=nvt"):
        validate_md_sampling_protocol(protocol)

    protocol = _protocol()
    protocol["seed"] = 900_000_001
    with pytest.raises(ValueError, match="between 1 and 900000000"):
        validate_md_sampling_protocol(protocol)

    with pytest.raises(ValueError, match="DeepMD pair_style"):
        validate_md_sampling_potential(_protocol(), {"pair_style": "eam", "plugin": "x"})


def test_sampling_reader_preserves_asymmetric_virial_mapping_and_pressure(tmp_path: Path) -> None:
    protocol = _protocol()
    _write_native(tmp_path, protocol)

    result = read_md_sampling_outputs(tmp_path, protocol, _atom_map())

    assert result["schema"] == "mlcc.md-native-stress-source.v1"
    assert result["component_order"] == COMPONENT_ORDER
    assert result["stress_volume_unit"] == "bar*angstrom^3"
    assert result["tensor_basis"] == "lammps_prism"
    assert result["kinetic_included"] is False
    assert result["pressure_series"]["unit"] == "bar"
    assert result["pressure_series"]["kinetic_included"] is True
    assert [row["step"] for row in result["pressure_series"]["records"]] == [10, 20, 30]
    assert [row["step"] for row in result["pressure_series"]["production_records"]] == [10, 20, 30]

    frames = result["frames"]
    assert [frame["step"] for frame in frames] == [0, 10, 20, 30]
    assert [frame["window"] for frame in frames] == [
        "equilibration",
        "production",
        "production",
        "production",
    ]
    assert result["sampling_windows"]["equilibration"] == {
        "name": "equilibration",
        "start_step": 0,
        "end_step": 0,
        "closed": True,
    }
    assert result["sampling_windows"]["production"] == {
        "name": "production",
        "start_step": 10,
        "end_step": 30,
        "closed": True,
    }
    assert frames[0]["temperature_K"] == pytest.approx(300.0)
    assert frames[0]["temperature_source"] == "log.lammps:thermo"
    assert frames[2]["temperature_K"] == pytest.approx(400.0)
    assert frames[2]["temperature_source"] == "pressure-series.dat"
    assert frames[0]["atom_ids"] == [20, 5, 90]
    assert frames[0]["native_atom_ids"] == [3, 1, 2]
    assert frames[0]["image_flags"] == [[-1, 0, 1], [0, 0, 0], [1, -1, 0]]
    assert frames[0]["velocities_angstrom_per_ps"] == [
        [0.7, 0.8, 0.9],
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]
    assert frames[0]["stress_volume_components_bar_A3"] == [
        [19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0],
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
        [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0],
    ]
    assert frames[0]["stress_volume_components_bar_A3"][0][6:] == [25.0, 26.0, 27.0]


def test_sampling_reader_rejects_missing_frame_and_native_mapping(tmp_path: Path) -> None:
    protocol = _protocol()
    _write_native(tmp_path, protocol)
    sampling_path = tmp_path / "sampling.lammpstrj"
    text = sampling_path.read_text(encoding="utf-8")
    start = text.index("ITEM: TIMESTEP\n20\n")
    end = text.find("ITEM: TIMESTEP\n", start + 1)
    sampling_path.write_text(text[:start] + text[end:], encoding="utf-8")
    with pytest.raises(ValueError, match="dump grid"):
        read_md_sampling_outputs(tmp_path, protocol, _atom_map())

    _write_native(tmp_path, protocol)
    sampling_path.write_text(
        sampling_path.read_text(encoding="utf-8").replace(
            "1 1 1.0 2.0 3.0 0 0 0 0.1", "9 1 1.0 2.0 3.0 0 0 0 0.1", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="atom IDs"):
        read_md_sampling_outputs(tmp_path, protocol, _atom_map())


def test_sampling_reader_rejects_box_change(tmp_path: Path) -> None:
    protocol = _protocol()
    _write_native(tmp_path, protocol)
    sampling_path = tmp_path / "sampling.lammpstrj"
    sampling_path.write_text(
        sampling_path.read_text(encoding="utf-8").replace(
            "0.0 4.0 0.0", "0.0 4.1 0.0", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="box"):
        read_md_sampling_outputs(tmp_path, protocol, _atom_map())
