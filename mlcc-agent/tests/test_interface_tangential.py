"""Contract tests for the explicit fixed-cell tangential interface response.

The points below are mathematical/software-contract fixtures.  They exercise
the domain reduction only; no native LAMMPS output, material qualification, or
local numerical execution is implied.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from mlcc.interface_tangential import tangential_response_from_points


ATOM_IDS = [41, 7, 88, 12]
NORMAL = [0.6, 0.8, 0.0]
TANGENT = [-0.8, 0.6, 0.0]


def _protocol(
    *,
    points: list[dict[str, object]] | None = None,
    normal: list[float] | None = None,
    tangent: list[float] | None = None,
    fixture: bool = True,
) -> dict[str, object]:
    point_specs = points or [
        {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
        {"point_id": "load", "branch": "loading", "displacement_angstrom": 0.5},
        {"point_id": "return", "branch": "unloading", "displacement_angstrom": 0.0},
    ]
    return {
        "kind": "interface_tangential",
        "purpose": "interface_tangential_response",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "none",
        "static_tensor": True,
        "experiment_scope": "software contract fixture",
        "timestep_ps": 0.001,
        "source_kind": "mathematical_fixture" if fixture else "software_contract_fixture",
        "fixture": fixture,
        "fixture_purpose": "mathematical_fixture" if fixture else None,
        "tangential_response": {
            "schema": "mlcc.interface-tangential-protocol.v1",
            "kinematics": "fixed_cell_clamped_internal_relaxation",
            "normal_cartesian": list(normal or NORMAL),
            "tangential_cartesian": list(tangent or TANGENT),
            "area_angstrom2": 4.0,
            "interface_count": 2,
            "fixed_atom_ids": [88],
            "moving_atom_ids": [7],
            "free_atom_ids": [41, 12],
            "minimization": {
                "min_style": "cg",
                "etol": 1.0e-10,
                "ftol_eV_per_A": 1.0e-8,
                "maxiter": 100,
                "maxeval": 200,
            },
            "points": point_specs,
        },
    }


def _point(
    point_id: str,
    energy: float,
    *,
    moving_force: tuple[float, float, float] = (1.0, 2.0, 0.0),
    fixed_force: tuple[float, float, float] = (1.0, -1.0, 0.0),
    converged: bool = True,
    stopping_criterion: str | None = None,
    native_step: int = 0,
) -> dict[str, object]:
    return {
        "point_id": point_id,
        "energy_eV": energy,
        "positions_angstrom": [
            [0.1, 0.2, 0.3],
            [1.0, 2.0, 3.0],
            [-1.0, 0.5, 2.0],
            [0.4, 0.5, 0.6],
        ],
        "forces_eV_per_A": [
            [0.3, -0.4, 0.0],
            list(moving_force),
            list(fixed_force),
            [-0.3, 0.4, 0.0],
        ],
        "native_step": native_step,
        "force_source": "unconstrained_run0_at_minimized_geometry",
        "minimization": {
            "stopping_criterion": stopping_criterion or ("energy tolerance" if converged else "max iterations"),
            "iterations": 12 if converged else 100,
            "force_evaluations": 17 if converged else 200,
            "converged": converged,
            "raw_summary": "Minimization stats: mathematical tangential fixture",
        },
    }


def _points(*, reverse: bool = False) -> list[dict[str, object]]:
    if reverse:
        specs = [
            ("reference", -10.0, (1.0, 2.0, 0.0)),
            ("reverse", -9.5, (1.0, 5.0 / 3.0, 0.0)),
            ("zero", -9.25, (1.0, 2.0, 0.0)),
            ("return", -9.0, (1.0, 2.1, 0.0)),
        ]
    else:
        specs = [
            ("reference", -10.0, (1.0, 2.0, 0.0)),
            ("load", -9.25, (1.0, 5.0 / 3.0, 0.0)),
            ("return", -9.0, (1.0, 2.1, 0.0)),
        ]
    return [
        _point(point_id, energy, moving_force=moving_force)
        for point_id, energy, moving_force in specs
    ]


def test_non_axis_aligned_mapping_sign_units_and_raw_geometry_are_preserved() -> None:
    result = tangential_response_from_points(_protocol(), ATOM_IDS, _points())
    point = result["points"][0]

    assert result["schema"] == "mlcc.interface-tangential-response.v1"
    assert result["status"] == "mathematical_fixture"
    assert result["relaxation_status"] == "converged"
    assert result["production_qualified"] is False
    assert result["atom_ids"] == ATOM_IDS
    assert point["positions_angstrom"] == _point("reference", -10.0)["positions_angstrom"]
    assert point["forces_eV_per_A"] == _point("reference", -10.0)["forces_eV_per_A"]

    # t=(-0.8,0.6,0): F_moving·t=0.4, so R_t=-0.4.
    assert point["tangential_reaction_force_eV_per_A"] == pytest.approx(-0.4)
    assert point["fixed_tangential_reaction_force_eV_per_A"] == pytest.approx(1.4)
    assert point["cell_net_tangential_stress_GPa"] == pytest.approx(-16.021766208)
    assert point["moving_group_force_eV_per_A"] == pytest.approx([1.0, 2.0, 0.0])
    assert point["fixed_group_force_eV_per_A"] == pytest.approx([1.0, -1.0, 0.0])
    assert point["moving_constraint_reaction_vector_eV_per_A"] == pytest.approx([-1.0, -2.0, 0.0])
    assert point["fixed_constraint_reaction_vector_eV_per_A"] == pytest.approx([-1.0, 1.0, 0.0])
    assert point["free_forces_eV_per_A"][0] == pytest.approx([0.3, -0.4, 0.0])
    assert point["free_forces_eV_per_A"][1] == pytest.approx([-0.3, 0.4, 0.0])
    assert point["free_force_l2_eV_per_A"] == pytest.approx(0.7071067811865476)
    assert point["free_force_max_abs_eV_per_A"] == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("tangent", "expected_reaction"),
    [([0.8, -0.6, 0.0], 0.4), ([-0.8, 0.6, 0.0], -0.4)],
)
def test_flipping_tangent_flips_reaction_sign(
    tangent: list[float], expected_reaction: float,
) -> None:
    result = tangential_response_from_points(
        _protocol(tangent=tangent), ATOM_IDS, _points()
    )
    assert result["points"][0]["tangential_reaction_force_eV_per_A"] == pytest.approx(expected_reaction)


def test_negative_displacement_delta_and_zero_interval_keep_branch_order() -> None:
    protocol = _protocol(
        points=[
            {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
            {"point_id": "reverse", "branch": "loading", "displacement_angstrom": -0.5},
            {"point_id": "zero", "branch": "loading", "displacement_angstrom": -0.5},
            {"point_id": "return", "branch": "unloading", "displacement_angstrom": 0.0},
        ]
    )
    result = tangential_response_from_points(protocol, ATOM_IDS, _points(reverse=True))

    assert [point["point_id"] for point in result["points"]] == ["reference", "reverse", "zero", "return"]
    first, second = result["intervals"][:2]
    assert first["from_point_id"] == "reference"
    assert first["from_branch"] == "reference"
    assert first["to_point_id"] == "reverse"
    assert first["to_branch"] == "loading"
    assert first["displacement_delta_angstrom"] == pytest.approx(-0.5)
    assert first["tangential_stiffness_eV_per_A2"] == pytest.approx(-0.4)
    assert first["cell_net_tangential_stress_slope_GPa_per_A"] == pytest.approx(-16.021766208)
    assert second["displacement_delta_angstrom"] == pytest.approx(0.0)
    assert second["tangential_stiffness_eV_per_A2"] is None
    assert second["cell_net_tangential_stress_slope_GPa_per_A"] is None
    assert second["status"] == "undefined_zero_displacement_interval"
    assert "identical displacement" in second["reason"]


def test_stop_reason_and_relaxation_status_are_preserved_independently() -> None:
    points = _points()
    points[1] = _point(
        "load", -9.25, moving_force=(1.0, 5.0 / 3.0, 0.0), converged=False
    )
    result = tangential_response_from_points(_protocol(fixture=False), ATOM_IDS, points)

    assert result["status"] == "available"
    assert result["relaxation_status"] == "unconverged"
    assert result["points"][1]["minimization"]["converged"] is False
    assert result["points"][1]["minimization"]["stopping_criterion"] == "max iterations"
    assert result["points"][1]["minimization"]["raw_summary"]


def test_contradictory_converged_max_iterations_is_rejected() -> None:
    points = _points()
    points[1] = _point(
        "load",
        -9.25,
        converged=True,
        stopping_criterion="max iterations",
    )
    with pytest.raises(ValueError, match="converged|max iterations|stopping"):
        tangential_response_from_points(_protocol(), ATOM_IDS, points)


def test_coordinate_return_reports_nonzero_residual_without_recovery_claim() -> None:
    result = tangential_response_from_points(_protocol(), ATOM_IDS, _points())
    closure = result["return_closure"]

    assert closure["status"] == "reported_coordinate_return"
    assert closure["energy_residual_eV"] == pytest.approx(1.0)
    assert closure["tangential_reaction_residual_eV_per_A"] == pytest.approx(-0.06)
    assert closure["cell_net_tangential_stress_residual_GPa"] == pytest.approx(-2.4032649312)
    assert closure["interpretation"] == (
        "clamp_coordinate_return_only_free_internal_state_not_compared_not_physical_recovery"
    )


def test_without_unloading_return_closure_is_unresolved() -> None:
    protocol = _protocol(
        points=[
            {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
            {"point_id": "load", "branch": "loading", "displacement_angstrom": 0.5},
        ]
    )
    result = tangential_response_from_points(
        protocol, ATOM_IDS, _points()[:2]
    )
    assert result["return_closure"]["status"] == "unresolved"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("normal_cartesian", [1.0, 1.0, 0.0], "unit"),
        ("tangential_cartesian", [0.6, 0.8, 0.0], "orthogonal"),
        ("tangential_cartesian", [0.6, 0.6, 0.0], "unit"),
        ("area_angstrom2", 0.0, "area"),
        ("interface_count", 1, "interface_count"),
    ],
)
def test_invalid_vectors_and_interface_geometry_are_rejected(
    field: str, value: object, message: str,
) -> None:
    protocol = _protocol()
    protocol["tangential_response"] = deepcopy(protocol["tangential_response"])
    protocol["tangential_response"][field] = value
    with pytest.raises(ValueError, match=message):
        tangential_response_from_points(protocol, ATOM_IDS, _points())


def test_groups_minimization_order_and_force_source_are_explicit() -> None:
    protocol = _protocol()
    response = deepcopy(protocol["tangential_response"])
    response["moving_atom_ids"] = [88]
    response["fixed_atom_ids"] = [88]
    protocol["tangential_response"] = response
    with pytest.raises(ValueError, match="overlap|cover"):
        tangential_response_from_points(protocol, ATOM_IDS, _points())

    protocol = _protocol()
    protocol["tangential_response"] = deepcopy(protocol["tangential_response"])
    protocol["tangential_response"]["minimization"]["min_style"] = "fire"
    with pytest.raises(ValueError, match="min_style|cg|sd"):
        tangential_response_from_points(protocol, ATOM_IDS, _points())

    points = _points()
    points[0]["force_source"] = "native_final_dump"
    with pytest.raises(ValueError, match="force_source"):
        tangential_response_from_points(_protocol(), ATOM_IDS, points)


def test_atom_and_point_order_cannot_be_silently_rearranged() -> None:
    alternate_ids = [7, 41, 88, 12]
    alternate_points = _points()
    for point in alternate_points:
        point["positions_angstrom"] = [
            point["positions_angstrom"][1],
            point["positions_angstrom"][0],
            point["positions_angstrom"][2],
            point["positions_angstrom"][3],
        ]
        point["forces_eV_per_A"] = [
            point["forces_eV_per_A"][1],
            point["forces_eV_per_A"][0],
            point["forces_eV_per_A"][2],
            point["forces_eV_per_A"][3],
        ]
    result = tangential_response_from_points(_protocol(), alternate_ids, alternate_points)
    assert result["atom_ids"] == alternate_ids
    assert result["points"][0]["positions_angstrom"] == alternate_points[0]["positions_angstrom"]
    assert result["points"][0]["tangential_reaction_force_eV_per_A"] == pytest.approx(-0.4)
    assert result["points"][0]["cell_net_tangential_stress_GPa"] == pytest.approx(-16.021766208)

    points = _points()
    points[1]["point_id"] = "wrong"
    with pytest.raises(ValueError, match="point order|point_id"):
        tangential_response_from_points(_protocol(), ATOM_IDS, points)
