"""Format and command fixtures for the explicit DeepMD centroid route."""

from __future__ import annotations

from pathlib import Path

import pytest

from mlcc.lammps import _native_input_commands
from mlcc.lammps_local_stress import (
    local_stress_before_run_commands,
    read_local_stress_outputs,
    validate_local_stress_potential,
    validate_local_stress_protocol,
)


COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz", "yx", "zx", "zy"]


def _protocol() -> dict[str, object]:
    return {
        "kind": "run0",
        "purpose": "potential_qualification",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "static_tensor": True,
        "timestep_ps": 0.0001,
        "experiment_scope": "DeepMD centroid local virial input fixture",
        "local_stress": {
            "schema": "mlcc.local-stress-protocol.v1",
            "contribution": "virial",
            "compute_style": "centroid/stress/atom",
            "component_order": COMPONENT_ORDER,
        },
    }


def _potential() -> dict[str, object]:
    return {
        "pair_style": "deepmd frozen.pth",
        "plugin": "/home/v100/dpa4/releases/3.2.0/lib/python3.12/site-packages/deepmd/lib/libdeepmd_lmpplugin.so",
        "pair_coeff": ["* * Ca Zr O"],
    }


def _atom_map() -> dict[str, object]:
    return {
        "model_id": "cazro3-pnma-pristine",
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


def _dump_text(rows: list[str]) -> str:
    columns = " ".join(
        f"c_mlcc_local_stress[{index}]" for index in range(1, len(COMPONENT_ORDER) + 1)
    )
    return "\n".join(
        [
            "ITEM: TIMESTEP",
            "0",
            "ITEM: NUMBER OF ATOMS",
            str(len(rows)),
            "ITEM: BOX BOUNDS xy xz yz pp pp pp",
            "0.0 4.0 0.0",
            "0.0 5.0 0.0",
            "0.0 6.0 0.0",
            f"ITEM: ATOMS id type {columns}",
            *rows,
            "",
        ]
    )


def _rows() -> list[str]:
    return [
        "1 1 1.0 -2.0 3.0 4.0 5.0 6.0 7.0 8.0 9.0",
        "2 1 -10.0 11.0 -12.0 13.0 -14.0 15.0 -16.0 17.0 -18.0",
        "3 1 -19.0 20.0 -21.0 22.0 -23.0 24.0 -25.0 26.0 -27.0",
    ]


def test_centroid_commands_are_explicit_and_include_plugin_in_canonical_setup() -> None:
    protocol = _protocol()
    potential = _potential()
    validate_local_stress_protocol(protocol)
    validate_local_stress_potential(protocol, potential)

    commands = local_stress_before_run_commands(protocol, potential)
    assert commands == [
        "compute mlcc_local_stress all centroid/stress/atom NULL virial",
        "dump mlcc_local_stress_dump all custom 1 local-stress.lammpstrj id type "
        "c_mlcc_local_stress[1] c_mlcc_local_stress[2] "
        "c_mlcc_local_stress[3] c_mlcc_local_stress[4] "
        "c_mlcc_local_stress[5] c_mlcc_local_stress[6] "
        "c_mlcc_local_stress[7] c_mlcc_local_stress[8] "
        "c_mlcc_local_stress[9]",
        "dump_modify mlcc_local_stress_dump sort id format float %.16g",
    ]

    canonical = _native_input_commands(
        potential,
        protocol,
        {"1": 40.0, "2": 91.0, "3": 16.0},
    )
    assert canonical[0] == f'plugin load "{potential["plugin"]}"'
    assert commands[0] in canonical
    assert commands[1] in canonical


def test_centroid_reader_preserves_nine_components_and_source_mapping(tmp_path: Path) -> None:
    (tmp_path / "local-stress.lammpstrj").write_text(
        _dump_text(_rows()), encoding="utf-8"
    )

    result = read_local_stress_outputs(tmp_path, _protocol(), _atom_map())

    assert result["compute_style"] == "centroid/stress/atom"
    assert result["component_order"] == COMPONENT_ORDER
    frame = result["frames"][0]
    assert frame["component_order"] == COMPONENT_ORDER
    assert frame["atom_ids"] == [20, 5, 90]
    assert frame["stress_volume_components_bar_A3"] == [
        [-19.0, 20.0, -21.0, 22.0, -23.0, 24.0, -25.0, 26.0, -27.0],
        [1.0, -2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
        [-10.0, 11.0, -12.0, 13.0, -14.0, 15.0, -16.0, 17.0, -18.0],
    ]


@pytest.mark.parametrize(
    ("potential_update", "message"),
    [
        ({"pair_style": "eam"}, "DeepMD pair_style"),
        ({"plugin": ""}, "explicit DeepMD plugin"),
    ],
)
def test_centroid_route_rejects_unbound_potential(
    potential_update: dict[str, str], message: str
) -> None:
    potential = _potential()
    potential.update(potential_update)
    with pytest.raises(ValueError, match=message):
        validate_local_stress_potential(_protocol(), potential)


def test_legacy_interface_protocol_keeps_six_component_defaults() -> None:
    protocol = _protocol()
    protocol["purpose"] = "interface_local_stress"
    del protocol["local_stress"]["compute_style"]
    del protocol["local_stress"]["component_order"]

    commands = local_stress_before_run_commands(protocol)

    assert commands[0] == "compute mlcc_local_stress all stress/atom NULL virial"
    assert commands[1].endswith(
        "c_mlcc_local_stress[1] c_mlcc_local_stress[2] "
        "c_mlcc_local_stress[3] c_mlcc_local_stress[4] "
        "c_mlcc_local_stress[5] c_mlcc_local_stress[6]"
    )
