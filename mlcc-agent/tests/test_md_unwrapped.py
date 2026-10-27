"""Focused MD-04 unwrapped-input/reader checks.

The dump text below is a mathematical format fixture only.  It is not a
LAMMPS result and does not claim a native completed task.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase.calculators.lammps import Prism

from mlcc.lammps import validate_lammps_protocol
from mlcc.md_unwrapped import (
    read_unwrapped_trajectory,
    unwrapped_input_commands,
    unwrapped_output_files,
    validate_unwrapped_protocol,
)


def _protocol() -> dict[str, object]:
    return {
        "kind": "md",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "nve",
        "temperature_K": 300.0,
        "seed": 12345,
        "timestep_ps": 0.5,
        "steps": 4,
        "dump_every": 2,
        "thermo_every": 2,
        "unwrapped_trajectory": True,
    }


def _atom_map() -> dict[str, object]:
    source_cell = np.asarray(
        [[4.0, 0.3, 0.2], [0.8, 3.6, 0.4], [0.4, 0.5, 5.2]], dtype=float
    )
    prism = Prism(source_cell, pbc=True, reduce_cell=False)
    return {
        "model_id": "ni-unwrapped-fixture",
        "version": "v001",
        "source_cell_angstrom": source_cell.tolist(),
        "lammps_prism": [float(value) for value in prism.get_lammps_prism()],
        "source_atom_ids": [20, 5],
        "atoms": [
            {"source_index": 0, "source_atom_id": 20, "lammps_id": 2, "type": 1},
            {"source_index": 1, "source_atom_id": 5, "lammps_id": 1, "type": 1},
        ],
    }


def _task_method(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    protocol = _protocol()
    task = {
        "engine": "lammps",
        "calculation": "md",
        "task_id": "md-unwrapped-fixture",
        "engine_version": "LAMMPS (22 Jul 2025 - Update 4)",
        "scheduler_job_id": "fixture-job",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "runner": "slurm",
        "model_id": "ni-unwrapped-fixture",
        "model_version": "v001",
        "model": {"model_id": "ni-unwrapped-fixture", "version": "v001"},
        "protocol": protocol,
    }
    method = {
        "engine": "lammps",
        "model_id": "ni-unwrapped-fixture",
        "version": "v001",
        "units": "metal",
        "atom_style": "atomic",
        "production_qualification": False,
        "protocol": protocol,
        "files": {
            "trajectory.unwrapped.lammpstrj": str(
                tmp_path / "trajectory.unwrapped.lammpstrj"
            )
        },
    }
    return task, method


def _dump(*, changed_box: bool = False, wrong_id: bool = False, wrong_columns: bool = False) -> str:
    atom_map = _atom_map()
    lx, ly, lz, xy, xz, yz = [float(value) for value in atom_map["lammps_prism"]]
    xlo_bound = min(0.0, xy, xz, xy + xz)
    xhi_bound = lx + max(0.0, xy, xz, xy + xz)
    ylo_bound = min(0.0, yz)
    yhi_bound = ly + max(0.0, yz)
    atom_header = "ITEM: ATOMS id type x y z" if wrong_columns else "ITEM: ATOMS id type xu yu zu"
    frames: list[str] = []
    for step, offset in ((0, 0.0), (2, 1.0), (4, 2.0)):
        frame_xhi_bound = xhi_bound + (0.1 if changed_box and step == 2 else 0.0)
        first_id = "9" if wrong_id and step == 2 else "1"
        frames.extend(
            [
                "ITEM: TIMESTEP",
                str(step),
                "ITEM: NUMBER OF ATOMS",
                "2",
                "ITEM: BOX BOUNDS xy xz yz pp pp pp",
                f"{xlo_bound:.16g} {frame_xhi_bound:.16g} {xy:.16g}",
                f"{ylo_bound:.16g} {yhi_bound:.16g} {xz:.16g}",
                f"0 {lz:.16g} {yz:.16g}",
                atom_header,
                f"{first_id} 1 {1.0 + offset:.16g} {2.0 + offset:.16g} {3.0 + offset:.16g}",
                f"2 1 {7.0 + offset:.16g} {8.0 + offset:.16g} {9.0 + offset:.16g}",
            ]
        )
    return "\n".join(frames) + "\n"


def _write_fixture(tmp_path: Path, **kwargs: object) -> tuple[dict[str, object], dict[str, object]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    task, method = _task_method(tmp_path)
    atom_map = _atom_map()
    for filename, record in (
        ("task.json", task),
        ("method.json", method),
        ("atom-map.json", atom_map),
    ):
        (tmp_path / filename).write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
    (tmp_path / "in.lammps").write_text(
        "\n".join(unwrapped_input_commands(_protocol())) + "\n", encoding="utf-8"
    )
    (tmp_path / "trajectory.unwrapped.lammpstrj").write_text(
        _dump(**kwargs), encoding="utf-8"
    )
    return task, method


def test_explicit_protocol_adds_independent_native_dump_and_preserves_columns() -> None:
    protocol = _protocol()
    validate_unwrapped_protocol(protocol)
    validate_lammps_protocol(protocol)
    assert unwrapped_input_commands(protocol) == [
        "dump trajectory_unwrapped all custom 2 trajectory.unwrapped.lammpstrj id type xu yu zu",
        "dump_modify trajectory_unwrapped sort id format float %.16g",
        "undump trajectory_unwrapped",
    ]
    assert unwrapped_output_files(protocol) == ["trajectory.unwrapped.lammpstrj"]


def test_unwrapped_switch_rejects_non_md_and_absence_keeps_old_path() -> None:
    protocol = _protocol()
    protocol["kind"] = "run0"
    with pytest.raises(ValueError, match="only for md"):
        validate_unwrapped_protocol(protocol)
    absent = _protocol()
    absent.pop("unwrapped_trajectory")
    validate_lammps_protocol(absent)
    assert unwrapped_input_commands(absent) == []
    assert unwrapped_output_files(absent) == []


def test_reader_returns_source_order_and_prism_unwrapped_positions(tmp_path: Path) -> None:
    task, method = _write_fixture(tmp_path)
    result = read_unwrapped_trajectory(tmp_path, task, method, _atom_map())

    assert result["schema"] == "mlcc.md-unwrapped-trajectory.v1"
    assert result["native_columns"] == ["id", "type", "xu", "yu", "zu"]
    assert result["task_id"] == "md-unwrapped-fixture"
    assert result["native_job"]["scheduler_job_id"] == "fixture-job"
    assert result["model"] == {"model_id": "ni-unwrapped-fixture", "version": "v001"}
    assert [frame["step"] for frame in result["frames"]] == [0, 2, 4]
    assert [frame["physical_time_ps"] for frame in result["frames"]] == [0.0, 1.0, 2.0]
    assert result["source_atom_ids"] == [20, 5]
    assert result["frames"][0]["source_atom_ids"] == [20, 5]
    prism = Prism(
        np.asarray(_atom_map()["source_cell_angstrom"], dtype=float),
        pbc=True,
        reduce_cell=False,
    )
    expected_positions = prism.vector_to_ase(
        np.asarray([[7.0, 8.0, 9.0], [1.0, 2.0, 3.0]], dtype=float),
        wrap=False,
    )
    np.testing.assert_allclose(
        result["frames"][0]["positions_angstrom"], expected_positions, rtol=0, atol=1e-12
    )
    assert result["frames"][0]["coordinate_basis"] == "source_cartesian"
    assert result["frames"][0]["native_coordinate_basis"] == "unwrapped_lammps_prism"
    assert result["fixed_cell"]["value"] is True
    assert result["expected_outputs"] == ["trajectory.unwrapped.lammpstrj"]
    assert result["source_files"]["trajectory.unwrapped.lammpstrj"].endswith(
        "trajectory.unwrapped.lammpstrj"
    )


def test_reader_requires_real_unwrapped_source_file(tmp_path: Path) -> None:
    task, method = _task_method(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    atom_map = _atom_map()
    for filename, record in (
        ("task.json", task),
        ("method.json", method),
        ("atom-map.json", atom_map),
    ):
        (tmp_path / filename).write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
    (tmp_path / "in.lammps").write_text(
        "\n".join(unwrapped_input_commands(_protocol())) + "\n", encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError):
        read_unwrapped_trajectory(tmp_path, task, method, _atom_map())


def test_reader_rejects_wrong_native_ids_and_non_unwrapped_columns(tmp_path: Path) -> None:
    task, method = _write_fixture(tmp_path, wrong_id=True)
    with pytest.raises(ValueError, match="atom IDs"):
        read_unwrapped_trajectory(tmp_path, task, method, _atom_map())

    task, method = _write_fixture(tmp_path / "columns", wrong_columns=True)
    with pytest.raises(ValueError, match="columns"):
        read_unwrapped_trajectory(tmp_path / "columns", task, method, _atom_map())


def test_reader_rejects_prism_change_between_frames(tmp_path: Path) -> None:
    task, method = _write_fixture(tmp_path, changed_box=True)
    with pytest.raises(ValueError, match="box"):
        read_unwrapped_trajectory(tmp_path, task, method, _atom_map())
