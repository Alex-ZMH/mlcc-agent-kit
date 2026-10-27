"""High-level MD-04 collection-consumer checks.

The local native files written here are an explicit mathematical format
fixture.  They exercise the reader/collection binding path only; they are not
claimed to be a completed LAMMPS calculation.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import numpy as np
import pytest
from ase.calculators.lammps import Prism

from mlcc.md_msd import analyze_md_msd
from mlcc.md_unwrapped import read_unwrapped_trajectory, unwrapped_input_commands


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
        "files": {"trajectory.unwrapped.lammpstrj": str(tmp_path / "trajectory.unwrapped.lammpstrj")},
    }
    return task, method


def _dump() -> str:
    atom_map = _atom_map()
    lx, ly, lz, xy, xz, yz = [float(value) for value in atom_map["lammps_prism"]]
    xlo_bound = min(0.0, xy, xz, xy + xz)
    xhi_bound = lx + max(0.0, xy, xz, xy + xz)
    ylo_bound = min(0.0, yz)
    yhi_bound = ly + max(0.0, yz)
    frames: list[str] = []
    for step, offset in ((0, 0.0), (2, 1.0), (4, 2.0)):
        frames.extend(
            [
                "ITEM: TIMESTEP",
                str(step),
                "ITEM: NUMBER OF ATOMS",
                "2",
                "ITEM: BOX BOUNDS xy xz yz pp pp pp",
                f"{xlo_bound:.16g} {xhi_bound:.16g} {xy:.16g}",
                f"{ylo_bound:.16g} {yhi_bound:.16g} {xz:.16g}",
                f"0 {lz:.16g} {yz:.16g}",
                "ITEM: ATOMS id type xu yu zu",
                f"1 1 {1.0 + offset:.16g} {2.0 + offset:.16g} {3.0 + offset:.16g}",
                f"2 1 {7.0 + offset:.16g} {8.0 + offset:.16g} {9.0 + offset:.16g}",
            ]
        )
    return "\n".join(frames) + "\n"


def _write_collection(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    native_path = tmp_path / "native"
    native_path.mkdir()
    task, method = _task_method(native_path)
    atom_map = _atom_map()
    for filename, record in (
        ("task.json", task),
        ("method.json", method),
        ("atom-map.json", atom_map),
    ):
        (native_path / filename).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (native_path / "in.lammps").write_text(
        "\n".join(unwrapped_input_commands(_protocol())) + "\n", encoding="utf-8"
    )
    (native_path / "trajectory.unwrapped.lammpstrj").write_text(_dump(), encoding="utf-8")
    unwrapped = read_unwrapped_trajectory(native_path, task, method, atom_map)
    assert all(Path(path).is_file() for path in unwrapped["source_files"].values())

    collection = {
        "schema": "mlcc.md-collection.v1",
        "task_id": unwrapped["task_id"],
        "native_job": copy.deepcopy(unwrapped["native_job"]),
        "model": copy.deepcopy(unwrapped["model"]),
        "potential": {"potential_id": "ni-fixture-potential", "version": "v001"},
        "lineage": {"source": "mathematical_unwrapped_fixture"},
        "protocol": copy.deepcopy(unwrapped["protocol"]),
        "legacy_final_result": {"elements": ["Ni", "Ni"], "atom_ids": [20, 5]},
        "trajectory": {"frames": copy.deepcopy(unwrapped["frames"])},
        "source_files": copy.deepcopy(unwrapped["source_files"]),
        "unwrapped_trajectory": copy.deepcopy(unwrapped),
    }
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    return collection_path, collection, unwrapped


def _request() -> dict[str, object]:
    return {
        "source_atom_ids": [20, 5],
        "dimensions": 3,
        "com_policy": "none",
        "fick_window": {"start_ps": 0.5, "end_ps": 2.0},
    }


def _fake_source_selection(*args: object, **kwargs: object) -> dict[str, object]:
    return {
        "schema": "mlcc.md-source-selection.v1",
        "sources": [{"fixture": "mathematical_unwrapped_collection"}],
        "source_selection": {"status": "selected_for_engineering_source_binding"},
        "replica_aggregation": {"status": "unresolved"},
        "production_qualification": False,
    }


def test_old_job105_collection_without_native_unwrapped_data_stays_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path(
        os.environ.get(
            "MLCC_MD_COLLECTION",
            Path(__file__).resolve().parents[2] / "workspace/reports/md-series-v011-v001/collection.json",
        )
    )
    assert source.is_file()
    record = json.loads(source.read_text(encoding="utf-8"))
    record["trajectory"]["wrapped_coordinates"] = False
    collection_path = tmp_path / "job105-wrapped-only.json"
    collection_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr("mlcc.md_sources.select_md_sources", _fake_source_selection)

    def forbidden_compute(*args: object, **kwargs: object) -> None:
        raise AssertionError("wrapped-only collection must not call compute_tracer_msd")

    monkeypatch.setattr("mlcc.md_msd.compute_tracer_msd", forbidden_compute)
    request = {
        "source_atom_ids": list(record["legacy_final_result"]["atom_ids"]),
        "dimensions": 3,
        "com_policy": "none",
        "fick_window": {"start_ps": 0.01, "end_ps": 0.02},
    }
    result = analyze_md_msd(
        collection_path,
        observation_window={"kind": "whole_record"},
        request=request,
    )

    assert result["status"] == "unresolved"
    assert result["MSD_A2"] is None
    assert result["D_A2_per_ps"] is None
    assert result["D_m2_per_s"] is None
    assert result["missing_evidence"] == ["native_unwrapped_trajectory"]


def test_math_unwrapped_reader_product_is_consumed_by_collection_msd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection_path, collection, unwrapped = _write_collection(tmp_path)
    monkeypatch.setattr("mlcc.md_sources.select_md_sources", _fake_source_selection)
    result = analyze_md_msd(
        collection_path,
        observation_window={"kind": "whole_record"},
        request=_request(),
    )

    assert result["status"] == "partial"
    assert result["MSD_A2"] is not None
    assert result["lag_ps"] == pytest.approx([1.0, 2.0])
    assert result["coordinate_basis"] == "source_cartesian"
    assert result["unwrapped_source"]["schema"] == "mlcc.md-unwrapped-trajectory.v1"
    assert result["unwrapped_source"]["source_files"] == unwrapped["source_files"]
    assert collection["source_files"] == unwrapped["source_files"]
    assert all(Path(path).is_file() for path in result["source_files"].values())


@pytest.mark.parametrize("mismatch", ["job", "commands"])
def test_collection_rejects_unwrapped_source_binding_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    collection_path, collection, _ = _write_collection(tmp_path)
    if mismatch == "job":
        collection["unwrapped_trajectory"]["native_job"]["scheduler_job_id"] = "different-job"
        message = "task/job"
    else:
        collection["unwrapped_trajectory"]["input_commands"][0] = "dump wrong all custom"
        message = "command definition"
    collection_path.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr("mlcc.md_sources.select_md_sources", _fake_source_selection)

    with pytest.raises(ValueError, match=message):
        analyze_md_msd(
            collection_path,
            observation_window={"kind": "whole_record"},
            request=_request(),
        )
