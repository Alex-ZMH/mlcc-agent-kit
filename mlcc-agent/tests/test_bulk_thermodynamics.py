"""Focused tests for saved NVT bulk-property conversion.

These tests use tiny saved-delivery fixtures only; they do not launch LAMMPS
or recompute a native trajectory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scipy.constants import Avogadro, elementary_charge

from mlcc.bulk_thermodynamics import build_bulk_thermodynamics


def _dump(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _state(
    root: Path,
    *,
    state_id: str,
    target_temperature: float,
    actual_temperature: float,
    seed: int = 7,
    energy_offset: float = 0.0,
    volume: float | None = 100.0,
    cell: list[list[float]] | None = None,
    mass_source: bool = True,
    window: bool = True,
) -> tuple[Path, Path]:
    task_id = f"task-{state_id}"
    state_dir = root / state_id
    delivery_dir = state_dir / "md-delivery"
    atom_map_path = state_dir / "atom-map.json"
    thermo_path = delivery_dir / "thermo.json"
    volume_path = state_dir / "md-thermal-sources-request.json"
    delivery_path = delivery_dir / "delivery.json"
    if cell is None:
        cell = [[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 4.0]]
    atom_map = {
        "schema": "mlcc.lammps-atom-map.v1",
        "model_id": "model-1",
        "version": "v001",
        "source_atom_ids": [0, 1],
        "source_cell_angstrom": cell,
        "mass_units": "g/mol",
        "mass_source": "ModelAtoms masses",
        "masses_by_type": {"1": 10.0},
        "atoms": [
            {"source_atom_id": 0, "type": 1},
            {"source_atom_id": 1, "type": 1},
        ],
    }
    if not mass_source:
        atom_map.pop("masses_by_type")
    _dump(atom_map_path, atom_map)
    delivery = {
        "schema": "mlcc.md-property-delivery.v1",
        "status": "delivered_engineering_observations",
        "scientific_status": "engineering_sampling_not_equilibrium_qualification",
        "sampling_equilibrium_qualified": False,
        "production_qualification": False,
        "study_id": "study-1",
        "case_id": "case-1",
        "task_id": task_id,
        "native_job": {
            "scheduler_job_id": str(seed),
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "runner": "slurm",
        },
        "analysis_scheduler_job_id": "566",
        "artifacts": {"thermo": str(thermo_path)},
        "model": {"model_id": "model-1", "version": "v001"},
        "lineage": {"method_set": "method-1"},
        "protocol": {
            "kind": "md",
            "purpose": "md_native_sampling",
            "ensemble": "nvt",
            "units": "metal",
            "temperature_K": target_temperature,
            "seed": seed,
        },
    }
    rows = [
        {"step": 1000, "pe": 1.0 + energy_offset, "ke": 0.5},
        {"step": 6000, "pe": 3.0 + energy_offset, "ke": 0.5},
    ]
    thermo = {
        "schema": "mlcc.md-thermo-summary.v1",
        "task_id": task_id,
        "native_job": delivery["native_job"],
        "source_files": {"atom-map.json": str(atom_map_path)},
        "observation": {
            "request": {"kind": "step_range", "start_step": 1000, "end_step": 6000},
            "sample_count": len(rows),
            "step_range": [1000, 6000],
            "scope": "engineering_observation_not_production",
        },
        "thermo": {"units": {"pe": "eV", "ke": "eV"}, "rows": rows},
        "quantities": {"temperature": {"unit": "K", "sample_mean": actual_temperature}},
    }
    if not window:
        thermo.pop("observation")
    _dump(delivery_path, delivery)
    _dump(thermo_path, thermo)
    task_path = _dump(state_dir / "task.json", {"task_id": task_id})
    volume_source = {
        "schema": "mlcc.md-thermal-sources-request.v1",
        "task_path": str(task_path),
        "analysis": {
            "regions": [{"region_id": "whole_cell", "atom_ids": [0, 1], "volume_angstrom3": volume}]
        },
        "mechanical_constraint": {
            "cell_angstrom": cell,
            "boundary": ["p", "p", "p"],
            "fixed_atom_ids": [],
            "loading": {"kind": "none"},
        },
    }
    _dump(volume_path, volume_source)
    return delivery_path, volume_path


def _request(root: Path, states: list[tuple[str, Path, Path]], intervals: list[dict]) -> Path:
    study_path = _dump(root / "study.json", {
        "study_id": "study-1", "case_id": "case-1",
        "model": {"model_id": "model-1", "version": "v001"},
    })
    return _dump(root / "request.json", {
        "schema": "mlcc.bulk-thermodynamics-request.v1",
        "study_path": str(study_path),
        "states": [
            {"state_id": state_id, "md_delivery_path": str(delivery), "volume_source_path": str(volume)}
            for state_id, delivery, volume in states
        ],
        "cv_intervals": intervals,
    })


def test_saved_nvt_density_and_cv_use_declared_units_and_mean_pe_plus_ke(tmp_path: Path) -> None:
    ref = _state(tmp_path, state_id="ref", target_temperature=300.0, actual_temperature=302.0)
    target = _state(tmp_path, state_id="target", target_temperature=400.0, actual_temperature=402.0, energy_offset=4.0)
    request = _request(tmp_path, [("ref", *ref), ("target", *target)], [{
        "interval_id": "cv-1", "reference_state_id": "ref", "target_state_id": "target",
    }])

    result = build_bulk_thermodynamics(request)
    assert result["schema"] == "mlcc.domain-parameters.v1"
    assert result["kind"] == "bulk_thermodynamics"
    density = result["properties"][0]
    cv = result["properties"][2]
    expected_mass = 20.0e-3 / Avogadro
    assert density["name"] == "mass_density"
    assert density["unit"] == "kg/m^3"
    assert density["shape"] == []
    assert density["coordinates"] == "not_applicable_to_scalar"
    assert density["value"] == pytest.approx(expected_mass / (100.0e-30))
    assert density["conditions"]["status"] == "delivered_engineering_observations"
    assert density["conditions"]["scientific_status"] == "engineering_sampling_not_equilibrium_qualification"
    assert density["conditions"]["sampling_equilibrium_qualified"] is False
    assert density["conditions"]["production_qualification"] is False
    assert density["conditions"]["analysis_scheduler_job_id"] == "566"
    assert density["conditions"]["native_job"]["scheduler_state"] == "COMPLETED"
    assert cv["name"] == "mass_specific_heat_cv_interval"
    assert cv["unit"] == "J/(kg K)"
    assert cv["value"] == pytest.approx((4.0 * elementary_charge) / (100.0 * expected_mass))
    assert cv["conditions"]["mean_pe_plus_ke"] == {
        "reference": 2.5, "target": 6.5, "unit": "eV", "source_fields": ["pe", "ke"]
    }
    assert cv["conditions"]["reference_delivery"]["native_job"]["exit_code"] == "0:0"
    assert cv["conditions"]["target_delivery"]["sampling_equilibrium_qualified"] is False
    assert result["execution"]["native_jobs"][0]["scheduler_job_id"] == "7"


@pytest.mark.parametrize("missing", ["volume", "mass", "window"])
def test_missing_saved_input_is_unresolved_without_zero_fill(tmp_path: Path, missing: str) -> None:
    ref = _state(
        tmp_path, state_id="ref", target_temperature=300.0, actual_temperature=302.0,
        volume=None if missing == "volume" else 100.0,
        mass_source=missing != "mass", window=missing != "window",
    )
    target = _state(tmp_path, state_id="target", target_temperature=400.0, actual_temperature=402.0)
    request = _request(tmp_path, [("ref", *ref), ("target", *target)], [{
        "interval_id": "cv-1", "reference_state_id": "ref", "target_state_id": "target",
    }])

    result = build_bulk_thermodynamics(request)
    density, _, cv = result["properties"]
    selected = density if missing in {"volume", "mass"} else cv
    assert selected["status"] == "unresolved"
    assert selected["value"] is None
    assert selected["value"] != 0
    assert selected["conditions"]["unresolved_reason"]


def test_cv_interval_requires_same_seed_and_same_fixed_cell(tmp_path: Path) -> None:
    ref = _state(tmp_path, state_id="ref", target_temperature=300.0, actual_temperature=302.0, seed=7)
    target = _state(tmp_path, state_id="target", target_temperature=400.0, actual_temperature=402.0, seed=8)
    request = _request(tmp_path, [("ref", *ref), ("target", *target)], [{
        "interval_id": "cv-1", "reference_state_id": "ref", "target_state_id": "target",
    }])
    with pytest.raises(ValueError, match="same seed"):
        build_bulk_thermodynamics(request)

    ref = _state(tmp_path, state_id="ref2", target_temperature=300.0, actual_temperature=302.0)
    target = _state(
        tmp_path, state_id="target2", target_temperature=400.0, actual_temperature=402.0,
        cell=[[5.1, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 4.0]],
    )
    request = _request(tmp_path, [("ref2", *ref), ("target2", *target)], [{
        "interval_id": "cv-2", "reference_state_id": "ref2", "target_state_id": "target2",
    }])
    with pytest.raises(ValueError, match="cells differ"):
        build_bulk_thermodynamics(request)


def test_zero_actual_temperature_interval_is_unresolved(tmp_path: Path) -> None:
    ref = _state(tmp_path, state_id="ref", target_temperature=300.0, actual_temperature=302.0)
    target = _state(tmp_path, state_id="target", target_temperature=400.0, actual_temperature=302.0, energy_offset=4.0)
    request = _request(tmp_path, [("ref", *ref), ("target", *target)], [{
        "interval_id": "cv-1", "reference_state_id": "ref", "target_state_id": "target",
    }])

    cv = build_bulk_thermodynamics(request)["properties"][2]
    assert cv["status"] == "unresolved"
    assert cv["value"] is None
    assert "zero" in cv["conditions"]["unresolved_reason"]
