"""Contract checks for the native local-virial stress adapter.

The dump fixtures below are mathematical format fixtures only.  They do not
represent a completed LAMMPS task or a native scientific result.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from mlcc.lammps_local_stress import (
    local_stress_after_run_commands,
    local_stress_before_run_commands,
    read_local_stress_outputs,
    validate_local_stress_protocol,
)


def _protocol() -> dict[str, object]:
    return {
        "kind": "run0",
        "purpose": "interface_local_stress",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "static_tensor": True,
        "timestep_ps": 0.001,
        "experiment_scope": "Ni layered local virial fixture",
        "local_stress": {
            "schema": "mlcc.local-stress-protocol.v1",
            "contribution": "virial",
        },
    }


def _atom_map() -> dict[str, object]:
    return {
        "model_id": "ni-layered-fixture",
        "version": "v001",
        "source_atom_ids": [20, 5, 90],
        "source_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
        "lammps_prism": [4.0, 5.0, 6.0, 0.0, 0.0, 0.0],
        "atoms": [
            {"source_index": 0, "source_atom_id": 20, "lammps_id": 3, "type": 1},
            {"source_index": 1, "source_atom_id": 5, "lammps_id": 1, "type": 1},
            {"source_index": 2, "source_atom_id": 90, "lammps_id": 2, "type": 1},
        ],
    }


def _dump_text(rows: list[str], *, step: int = 0) -> str:
    return "\n".join(
        [
            "ITEM: TIMESTEP",
            str(step),
            "ITEM: NUMBER OF ATOMS",
            str(len(rows)),
            "ITEM: BOX BOUNDS xy xz yz pp pp pp",
            "0.0 4.0 0.0",
            "0.0 5.0 0.0",
            "0.0 6.0 0.0",
            "ITEM: ATOMS id type "
            "c_mlcc_local_stress[1] c_mlcc_local_stress[2] "
            "c_mlcc_local_stress[3] c_mlcc_local_stress[4] "
            "c_mlcc_local_stress[5] c_mlcc_local_stress[6]",
            *rows,
            "",
        ]
    )


def _write_dump(directory: Path, rows: list[str]) -> None:
    (directory / "local-stress.lammpstrj").write_text(
        _dump_text(rows), encoding="utf-8"
    )


def _rows() -> list[str]:
    return [
        "1 1 1.0 -2.0 3.0 4.0 5.0 6.0",
        "2 1 -7.0 8.0 -9.0 10.0 -11.0 12.0",
        "3 1 -13.0 14.0 -15.0 16.0 -17.0 18.0",
    ]


def test_commands_define_per_atom_virial_before_run0_and_clean_up():
    protocol = _protocol()
    validate_local_stress_protocol(protocol)
    commands = local_stress_before_run_commands(protocol)

    assert commands == [
        "compute mlcc_local_stress all stress/atom NULL virial",
        "dump mlcc_local_stress_dump all custom 1 local-stress.lammpstrj id type "
        "c_mlcc_local_stress[1] c_mlcc_local_stress[2] "
        "c_mlcc_local_stress[3] c_mlcc_local_stress[4] "
        "c_mlcc_local_stress[5] c_mlcc_local_stress[6]",
        "dump_modify mlcc_local_stress_dump sort id format float %.16g",
    ]
    assert "run 0" not in "\n".join(commands)
    assert local_stress_after_run_commands(protocol) == [
        "undump mlcc_local_stress_dump",
        "uncompute mlcc_local_stress",
    ]


def test_reader_preserves_native_sign_and_remaps_to_source_order(tmp_path: Path):
    _write_dump(tmp_path, _rows())

    result = read_local_stress_outputs(tmp_path, _protocol(), _atom_map())

    frame = result["frames"][0]
    assert frame["step"] == 0
    assert frame["physical_time_ps"] == 0.0
    assert frame["atom_ids"] == [20, 5, 90]
    assert frame["stress_volume_components_bar_A3"] == [
        [-13.0, 14.0, -15.0, 16.0, -17.0, 18.0],
        [1.0, -2.0, 3.0, 4.0, 5.0, 6.0],
        [-7.0, 8.0, -9.0, 10.0, -11.0, 12.0],
    ]
    assert result["component_order"] == ["xx", "yy", "zz", "xy", "xz", "yz"]
    assert result["stress_volume_unit"] == "bar*angstrom^3"
    assert result["tensor_basis"] == "native_prism"
    assert result["contribution"] == "virial"
    assert result["kinetic_included"] is False
    assert result["missing_evidence"] == []


def test_reader_reports_missing_dump_without_fabricating_frames(tmp_path: Path):
    result = read_local_stress_outputs(tmp_path, _protocol(), _atom_map())

    assert result["frames"] is None
    assert result["missing_evidence"] == ["local-stress.lammpstrj"]
    assert result["source_files"]["local-stress.lammpstrj"].endswith(
        "local-stress.lammpstrj"
    )


def test_reader_rejects_wrong_native_ids_and_types(tmp_path: Path):
    rows = _rows()
    wrong_id = rows.copy()
    wrong_id[0] = wrong_id[0].replace("1 1", "4 1", 1)
    _write_dump(tmp_path, wrong_id)
    with pytest.raises(ValueError, match="atom IDs differ"):
        read_local_stress_outputs(tmp_path, _protocol(), _atom_map())

    wrong_type = rows.copy()
    wrong_type[0] = wrong_type[0].replace("1 1", "1 2", 1)
    _write_dump(tmp_path, wrong_type)
    with pytest.raises(ValueError, match="atom type differs"):
        read_local_stress_outputs(tmp_path, _protocol(), _atom_map())


def test_reader_rejects_nonzero_step_or_mismatched_prism_box(tmp_path: Path):
    path = tmp_path / "local-stress.lammpstrj"
    path.write_text(_dump_text(_rows(), step=1), encoding="utf-8")
    with pytest.raises(ValueError, match="timestep must be zero"):
        read_local_stress_outputs(tmp_path, _protocol(), _atom_map())

    path.write_text(_dump_text(_rows()).replace("0.0 6.0 0.0", "0.0 7.0 0.0"), encoding="utf-8")
    with pytest.raises(ValueError, match="box differs"):
        read_local_stress_outputs(tmp_path, _protocol(), _atom_map())


def test_protocol_rejects_kinetic_or_temperature_fields():
    protocol = _protocol()
    protocol["temperature_K"] = 330.0
    with pytest.raises(ValueError, match="temperature_K or seed"):
        validate_local_stress_protocol(protocol)

    protocol = deepcopy(_protocol())
    protocol["local_stress"] = deepcopy(protocol["local_stress"])
    protocol["local_stress"]["contribution"] = "total"
    with pytest.raises(ValueError, match="contribution must be virial"):
        validate_local_stress_protocol(protocol)
