"""Consumer contracts for the ordinary ``md_native_sampling`` LAMMPS path.

These tests use JSON-only collection records.  They do not submit or parse a
native task; the native producer and its sidecar reader are tested separately.
The important consumer boundary here is that the protocol purpose is retained,
old ordinary MD is not mixed with the explicit sampling purpose, and missing
windows stay unresolved until an explicit window request is supplied.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc.md_conditions import read_md_conditions
from mlcc.md_sources import select_md_sources


def _collection(tmp_path: Path, *, purpose: str | None, name: str) -> Path:
    task_id = f"native-{name}"
    job_id = f"job-{name}"
    protocol = {
        "kind": "md",
        "purpose": purpose,
        "ensemble": "nvt",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "steps": 10,
        "timestep_ps": 0.1,
        "temperature_K": 400.0,
        "seed": 12345,
        "tdamp_ps": 0.01,
        "thermo_every": 10,
        "dump_every": 10,
        "experiment_scope": "explicit consumer contract fixture",
        "unwrapped_trajectory": True,
    }
    source_files = {
        filename: str(tmp_path / name / filename)
        for filename in (
            "task.json",
            "method.json",
            "atom-map.json",
            "in.lammps",
            "log.lammps",
            "trajectory.lammpstrj",
            "dump.final",
            "result.json",
        )
    }
    model = {"model_id": "czo-model", "version": "v001"}
    potential = {"potential_id": "deepmd-czo", "version": "146"}
    lineage = {
        "study_id": "cazro3_firing_validation_v003",
        "case_id": "cazro3_pnma_undoped",
        "case_role": "scientific_validation",
        "method_set": "lammps-deepmd-czo-146",
    }
    frame = {
        "frame_index": 0,
        "step": 0,
        "physical_time_ps": 0.0,
        "physical_time_fs": 0.0,
        "coordinate_basis": "lammps_prism_cartesian",
        "lammps_atom_ids": [1],
        "source_indices": [0],
        "source_atom_ids": [1],
        "types": [1],
        "positions_angstrom": [[0.0, 0.0, 0.0]],
        "box_bounds_angstrom": [[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]],
        "lammps_prism_angstrom": [1.0, 1.0, 1.0],
    }
    final_frame = {**frame, "frame_index": 1, "step": 10, "physical_time_ps": 1.0, "physical_time_fs": 1000.0}
    thermo_rows = [
        {"step": 0, "physical_time_ps": 0.0, "physical_time_fs": 0.0, "temp": 400.0, "pe": -1.0, "ke": 0.0, "etotal": -1.0, "press": 0.0},
        {"step": 10, "physical_time_ps": 1.0, "physical_time_fs": 1000.0, "temp": 400.0, "pe": -1.0, "ke": 0.0, "etotal": -1.0, "press": 0.0},
    ]
    legacy = {
        "task_id": task_id,
        "scheduler_job_id": job_id,
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "model_id": model["model_id"],
        "version": model["version"],
        "potential": dict(potential),
        "method_set": lineage["method_set"],
        "protocol": protocol,
        "engine_version": "LAMMPS consumer fixture",
        "source_files": source_files,
        "atom_ids": [1],
        "types": [1],
        "elements": ["O"],
    }
    record = {
        "schema": "mlcc.md-collection.v1",
        "engine": "lammps",
        "engine_version": "LAMMPS consumer fixture",
        "units": "metal",
        "atom_style": "atomic",
        "task_id": task_id,
        "lineage": lineage,
        "native_job": {"scheduler_job_id": job_id, "scheduler_state": "COMPLETED", "exit_code": "0:0", "runner": "slurm"},
        "model": {**model, "path": str(tmp_path / name / "model")},
        "potential": {**potential, "source": "fixture", "path_files": []},
        "protocol": protocol,
        "sampling_metadata": {
            "equilibration_window": None,
            "production_window": None,
            "replica_id": None,
            "packing_seed": None,
        },
        "time": {"timestep_ps": 0.1, "timestep_fs": 100.0, "initial_step": 0, "origin": "relative elapsed time since first native step"},
        "initialization": {"temperature_K": 400.0, "velocity_seed": 12345},
        "thermo": {
            "units": {"step": "native step", "temp": "K", "pe": "eV", "ke": "eV", "etotal": "eV", "press": "bar"},
            "rows": thermo_rows,
        },
        "trajectory": {
            "coordinate_units": "angstrom",
            "force_units": "eV/angstrom",
            "frames": [frame, final_frame],
        },
        "legacy_final_result": legacy,
        "legacy_final_result_coordinate_basis": "source_cartesian",
        "source_files": source_files,
        "missing_evidence": [],
        "unresolved": {},
        "production_qualification": False,
        "sampling_equilibrium_qualified": False,
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def test_native_sampling_purpose_is_preserved_and_missing_windows_stay_unresolved(tmp_path: Path) -> None:
    path = _collection(tmp_path, purpose="md_native_sampling", name="sampling")

    result = read_md_conditions(path)

    assert result["conditions"]["purpose"] == "md_native_sampling"
    assert result["windows"]["equilibration_window"]["status"] == "unresolved_missing"
    assert result["windows"]["production_window"]["status"] == "unresolved_missing"
    assert result["production_qualification"] is False
    assert result["sampling_equilibrium_qualified"] is False

    selected = select_md_sources(
        [path],
        model_id="czo-model",
        model_version="v001",
        potential_id="deepmd-czo",
        potential_version="146",
        elements=["O"],
    )
    assert selected["sources"][0]["conditions"]["purpose"] == "md_native_sampling"


def test_source_selection_does_not_mix_sampling_and_ordinary_md_purposes(tmp_path: Path) -> None:
    sampling = _collection(tmp_path, purpose="md_native_sampling", name="sampling")
    ordinary = _collection(tmp_path, purpose=None, name="ordinary")

    with pytest.raises(ValueError, match="protocol"):
        select_md_sources(
            [sampling, ordinary],
            model_id="czo-model",
            model_version="v001",
            potential_id="deepmd-czo",
            potential_version="146",
            elements=["O"],
        )

