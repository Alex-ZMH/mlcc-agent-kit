from __future__ import annotations

import pytest

from mlcc.interface_normal import normal_response_from_points


def _protocol(*, return_point: bool = True, zero_interval: bool = False) -> dict[str, object]:
    points = [
        {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
        {"point_id": "load", "branch": "loading", "displacement_angstrom": 0.5},
    ]
    if zero_interval:
        points[1]["displacement_angstrom"] = 0.0
    if return_point:
        points.append({"point_id": "return", "branch": "unloading", "displacement_angstrom": 0.0})
    return {
        "source_kind": "mathematical_fixture",
        "fixture": True,
        "fixture_purpose": "mathematical_fixture",
        "normal_response": {
            "schema": "mlcc.interface-normal-protocol.v1",
            "kinematics": "fixed_cell_rigid_side_translation",
            "normal_cartesian": [0.0, 0.0, 1.0],
            "area_angstrom2": 4.0,
            "interface_count": 2,
            "fixed_atom_ids": [10],
            "moving_atom_ids": [20],
            "points": points,
        },
    }


def _points(*, return_point: bool = True, zero_interval: bool = False) -> list[dict[str, object]]:
    values = [
        {"point_id": "reference", "energy_eV": -10.0, "force": 1.0},
        {"point_id": "load", "energy_eV": -9.25, "force": 2.0},
    ]
    if return_point:
        values.append({"point_id": "return", "energy_eV": -10.0, "force": 1.0})
    return [
        {
            "point_id": value["point_id"],
            "energy_eV": value["energy_eV"],
            "positions_angstrom": [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
            "forces_eV_per_A": [[0.0, 0.0, value["force"]], [0.0, 0.0, -value["force"]]],
        }
        for value in values
    ]


def test_formula_preserves_group_forces_total_and_two_interface_signs():
    result = normal_response_from_points(_protocol(), [10, 20], _points())
    expected_traction = 160.21766208 / 4.0
    assert result["status"] == "mathematical_fixture"
    assert result["production_qualified"] is False
    assert result["constraints"]["normal_cartesian"] == pytest.approx([0.0, 0.0, 1.0])
    assert result["constraints"]["interface_opening_derivatives"] == {"AB": 1.0, "BA": -1.0}
    assert result["points"][0]["fixed_group_force_eV_per_A"] == pytest.approx([0.0, 0.0, 1.0])
    assert result["points"][0]["moving_group_force_eV_per_A"] == pytest.approx([0.0, 0.0, -1.0])
    assert result["points"][0]["total_force_eV_per_A"] == pytest.approx([0.0, 0.0, 0.0])
    assert result["points"][0]["constraint_reaction_force_eV_per_A"] == pytest.approx(1.0)
    assert result["points"][0]["traction_GPa"] == pytest.approx(expected_traction)


def test_adjacent_interval_reports_traction_slope_and_energy_derivative():
    result = normal_response_from_points(_protocol(return_point=False), [10, 20], _points(return_point=False))
    interval = result["intervals"][0]
    expected_slope = (2.0 - 1.0) / 0.5 / 4.0 * 160.21766208
    expected_energy_derivative = (0.75 / (4.0 * 0.5)) * 160.21766208
    assert interval["traction_slope_GPa_per_A"] == pytest.approx(expected_slope)
    assert interval["energy_derivative_GPa"] == pytest.approx(expected_energy_derivative)
    assert interval["status"] == "available"


def test_zero_displacement_interval_is_null_and_named():
    result = normal_response_from_points(
        _protocol(return_point=False, zero_interval=True),
        [10, 20],
        _points(return_point=False),
    )
    interval = result["intervals"][0]
    assert interval["traction_slope_GPa_per_A"] is None
    assert interval["energy_derivative_GPa"] is None
    assert interval["status"] == "undefined_zero_displacement_interval"


def test_return_to_reference_reports_coordinate_closure_only():
    result = normal_response_from_points(_protocol(), [10, 20], _points())
    closure = result["return_closure"]
    assert closure["status"] == "reported_coordinate_return"
    assert closure["energy_residual_eV"] == pytest.approx(0.0)
    assert closure["reaction_force_residual_eV_per_A"] == pytest.approx(0.0)
    assert "not_physical_unloading_recovery" in closure["interpretation"]


def test_missing_unloading_return_is_unresolved():
    result = normal_response_from_points(
        _protocol(return_point=False),
        [10, 20],
        _points(return_point=False),
    )
    assert result["return_closure"]["status"] == "unresolved"


def test_groups_and_point_identity_are_explicit():
    with pytest.raises(ValueError, match="cover all atom_ids"):
        normal_response_from_points(_protocol(), [10, 20, 30], _points())
    points = _points()
    points[1]["point_id"] = "wrong"
    with pytest.raises(ValueError, match="point order or point_id"):
        normal_response_from_points(_protocol(), [10, 20], points)
