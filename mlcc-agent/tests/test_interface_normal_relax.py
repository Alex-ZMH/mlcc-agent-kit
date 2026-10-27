"""Mathematical response and mocked task contracts; no native execution claim."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from mlcc.interface_normal import normal_response_from_points
from mlcc.interface_normal_tasks import read_interface_normal_task


def _protocol() -> dict[str, object]:
    return {
        "kind": "interface_normal",
        "source_kind": "mathematical_fixture",
        "fixture": True,
        "fixture_purpose": "mathematical_fixture",
        "normal_response": {
            "schema": "mlcc.interface-normal-protocol.v1",
            "kinematics": "fixed_cell_clamped_internal_relaxation",
            "normal_cartesian": [0.0, 0.0, 1.0],
            "area_angstrom2": 4.0,
            "interface_count": 2,
            "fixed_atom_ids": [10],
            "moving_atom_ids": [20],
            "free_atom_ids": [30],
            "minimization": {
                "min_style": "cg",
                "etol": 1.0e-10,
                "ftol_eV_per_A": 1.0e-8,
                "maxiter": 100,
                "maxeval": 200,
            },
            "points": [
                {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
                {"point_id": "load", "branch": "loading", "displacement_angstrom": 0.5},
                {"point_id": "return", "branch": "unloading", "displacement_angstrom": 0.0},
            ],
        }
    }


def _point(point_id: str, energy: float, *, converged: bool = True) -> dict[str, object]:
    return {
        "point_id": point_id,
        "energy_eV": energy,
        "positions_angstrom": [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.2, 0.3, 0.4],
        ],
        "forces_eV_per_A": [
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -2.0],
            [0.3, -0.4, 0.0],
        ],
        "force_source": "unconstrained_run0_at_minimized_geometry",
        "native_step": 0,
        "minimization": {
            "stopping_criterion": "energy tolerance"
            if converged
            else "max iterations",
            "iterations": 12 if converged else 100,
            "force_evaluations": 17 if converged else 200,
            "converged": converged,
            "raw_summary": "Minimization stats: mathematical text fixture",
        },
    }


def test_relaxed_response_keeps_clamp_reactions_and_free_force_statistics():
    result = normal_response_from_points(
        _protocol(),
        [10, 20, 30],
        [_point("reference", -10.0), _point("load", -9.25), _point("return", -10.0)],
    )
    point = result["points"][0]
    assert result["status"] == "mathematical_fixture"
    assert result["relaxation_status"] == "converged"
    assert result["production_qualified"] is False
    assert point["force_source"] == "unconstrained_run0_at_minimized_geometry"
    assert point["fixed_constraint_reaction_vector_eV_per_A"] == pytest.approx([0.0, 0.0, -1.0])
    assert point["moving_constraint_reaction_vector_eV_per_A"] == pytest.approx([0.0, 0.0, 2.0])
    assert point["fixed_constraint_reaction_force_eV_per_A"] == pytest.approx(-1.0)
    assert point["moving_constraint_reaction_force_eV_per_A"] == pytest.approx(2.0)
    assert point["free_atom_ids"] == [30]
    assert point["free_forces_eV_per_A"][0] == pytest.approx([0.3, -0.4, 0.0])
    assert point["free_group_force_eV_per_A"] == pytest.approx([0.3, -0.4, 0.0])
    assert point["free_force_l2_eV_per_A"] == pytest.approx(0.5)
    assert point["free_force_max_abs_eV_per_A"] == pytest.approx(0.4)
    assert point["total_force_eV_per_A"] == pytest.approx([0.3, -0.4, -1.0])
    assert result["constraints"]["interface_opening_derivatives"] is None
    assert "not extracted" in result["constraints"]["interface_opening_derivatives_reason"]
    assert result["return_closure"]["status"] == "reported_coordinate_return"
    assert "free_internal_state_not_compared" in result["return_closure"]["interpretation"]


def test_relaxed_response_preserves_native_unconverged_state():
    protocol = _protocol()
    protocol["normal_response"]["minimization"]["etol"] = 0.0
    points = [_point("reference", -10.0), _point("load", -9.25, converged=False), _point("return", -10.0)]
    result = normal_response_from_points(protocol, [10, 20, 30], points)
    assert result["status"] == "mathematical_fixture"
    assert result["relaxation_status"] == "unconverged"
    assert result["points"][1]["minimization"]["converged"] is False
    assert result["points"][1]["minimization"]["stopping_criterion"] == "max iterations"
    assert result["points"][1]["minimization"]["raw_summary"]


def test_relaxed_response_requires_explicit_groups_settings_and_force_source():
    protocol = _protocol()
    protocol["normal_response"] = deepcopy(protocol["normal_response"])
    protocol["normal_response"]["free_atom_ids"] = [20]
    with pytest.raises(ValueError, match="must not overlap"):
        normal_response_from_points(protocol, [10, 20, 30], [_point("reference", -10.0)] * 3)

    protocol = _protocol()
    protocol["normal_response"] = deepcopy(protocol["normal_response"])
    protocol["normal_response"]["minimization"]["min_style"] = "fire"
    with pytest.raises(ValueError, match="min_style must be cg or sd"):
        normal_response_from_points(protocol, [10, 20, 30], [_point("reference", -10.0)] * 3)

    points = [_point("reference", -10.0), _point("load", -9.25), _point("return", -10.0)]
    points[0]["force_source"] = "native_final_dump"
    with pytest.raises(ValueError, match="force_source"):
        normal_response_from_points(_protocol(), [10, 20, 30], points)


def test_task_keeps_relaxation_status_separate_from_scheduler_status(monkeypatch, tmp_path: Path):
    import mlcc.interface_normal_tasks as tasks_module

    protocol = _protocol()
    task_data = {
        "engine": "lammps",
        "protocol": protocol,
        "study_id": "study",
        "case_id": "case",
        "case_role": "fixture",
        "fixture": True,
        "model_id": "model",
        "model_version": "v1",
        "model_path": "model",
        "task_id": "task",
        "interface_sources": {},
        "scheduler_job_id": "123",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "status": "completed",
        "scientific_status": "executed_interface_normal_response",
    }

    class Loaded:
        data = task_data

    monkeypatch.setattr(tasks_module, "load_task", lambda path: Loaded())
    monkeypatch.setattr(tasks_module, "validate_normal_protocol", lambda value: None)
    monkeypatch.setattr(
        tasks_module,
        "read_lammps_task",
        lambda path: {
            "atom_ids": [10, 20, 30],
            "points": [_point("reference", -10.0), _point("load", -9.25, converged=False), _point("return", -10.0)],
        },
    )
    result = read_interface_normal_task(tmp_path / "task.json")
    assert result["status"] == "available"
    assert result["relaxation_status"] == "unconverged"
    assert result["normal_response"]["relaxation_status"] == "unconverged"
