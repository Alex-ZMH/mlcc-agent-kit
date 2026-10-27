"""Direct constrained normal-response calculations for a layered interface."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


RESPONSE_SCHEMA = "mlcc.interface-normal-response.v1"
TRACTION_CONVERSION_EV_PER_A3_TO_GPA = 160.21766208


def _finite_vector(value: Any, name: str, size: int) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (size,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite length-{size} vector")
    return result


def _atom_groups(response: Mapping[str, Any], atom_ids: Sequence[int]) -> tuple[list[int], list[int], dict[int, int]]:
    model_ids = [int(value) for value in atom_ids]
    if len(set(model_ids)) != len(model_ids):
        raise ValueError("atom_ids must be unique")
    positions = {atom_id: index for index, atom_id in enumerate(model_ids)}
    fixed = [int(value) for value in response["fixed_atom_ids"]]
    moving = [int(value) for value in response["moving_atom_ids"]]
    if len(set(fixed)) != len(fixed) or len(set(moving)) != len(moving):
        raise ValueError("fixed_atom_ids and moving_atom_ids must be unique")
    if set(fixed) & set(moving):
        raise ValueError("fixed_atom_ids and moving_atom_ids must not overlap")
    if set(fixed) | set(moving) != set(model_ids):
        raise ValueError("fixed_atom_ids and moving_atom_ids must cover all atom_ids")
    if not fixed or not moving:
        raise ValueError("fixed_atom_ids and moving_atom_ids must both be non-empty")
    return fixed, moving, positions


def _point_arrays(point: Mapping[str, Any], count: int) -> tuple[np.ndarray, np.ndarray]:
    positions = np.asarray(point["positions_angstrom"], dtype=float)
    forces = np.asarray(point["forces_eV_per_A"], dtype=float)
    if positions.shape != (count, 3):
        raise ValueError("point positions_angstrom count does not match atom_ids")
    if forces.shape != (count, 3):
        raise ValueError("point forces_eV_per_A count does not match atom_ids")
    if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(forces)):
        raise ValueError("point positions and forces must be finite")
    return positions, forces


_RELAXED_KINEMATICS = "fixed_cell_clamped_internal_relaxation"
_RELAXED_FORCE_SOURCE = "unconstrained_run0_at_minimized_geometry"


def _relaxed_atom_groups(
    response: Mapping[str, Any], atom_ids: Sequence[int]
) -> tuple[list[int], list[int], list[int], dict[int, int]]:
    model_ids = [int(value) for value in atom_ids]
    if len(set(model_ids)) != len(model_ids):
        raise ValueError("atom_ids must be unique")
    positions = {atom_id: index for index, atom_id in enumerate(model_ids)}
    fixed = [int(value) for value in response["fixed_atom_ids"]]
    moving = [int(value) for value in response["moving_atom_ids"]]
    free = [int(value) for value in response["free_atom_ids"]]
    groups = (fixed, moving, free)
    if any(not group for group in groups):
        raise ValueError("fixed_atom_ids, moving_atom_ids and free_atom_ids must be non-empty")
    if any(len(set(group)) != len(group) for group in groups):
        raise ValueError("fixed_atom_ids, moving_atom_ids and free_atom_ids must be unique")
    if set(fixed) & set(moving) or set(fixed) & set(free) or set(moving) & set(free):
        raise ValueError("fixed_atom_ids, moving_atom_ids and free_atom_ids must not overlap")
    if set(fixed) | set(moving) | set(free) != set(model_ids):
        raise ValueError("fixed_atom_ids, moving_atom_ids and free_atom_ids must cover all atom_ids")
    return fixed, moving, free, positions


def _relaxed_minimization_settings(response: Mapping[str, Any]) -> dict[str, Any]:
    settings = response["minimization"]
    if not isinstance(settings, Mapping):
        raise ValueError("normal_response minimization must be an object")
    min_style = settings["min_style"]
    if min_style not in {"cg", "sd"}:
        raise ValueError("normal_response minimization min_style must be cg or sd")
    etol = float(settings["etol"])
    ftol = float(settings["ftol_eV_per_A"])
    if not np.isfinite(etol) or etol < 0.0:
        raise ValueError("normal_response minimization etol must be non-negative and finite")
    if not np.isfinite(ftol) or ftol < 0.0:
        raise ValueError("normal_response minimization ftol_eV_per_A must be non-negative and finite")
    if etol == 0.0 and ftol == 0.0:
        raise ValueError("normal_response minimization requires at least one positive tolerance")
    maxiter = settings["maxiter"]
    maxeval = settings["maxeval"]
    if isinstance(maxiter, bool) or not isinstance(maxiter, (int, np.integer)) or maxiter <= 0:
        raise ValueError("normal_response minimization maxiter must be a positive integer")
    if isinstance(maxeval, bool) or not isinstance(maxeval, (int, np.integer)) or maxeval <= 0:
        raise ValueError("normal_response minimization maxeval must be a positive integer")
    return {
        "min_style": str(min_style),
        "etol": etol,
        "ftol_eV_per_A": ftol,
        "maxiter": int(maxiter),
        "maxeval": int(maxeval),
    }


def _relaxed_point_minimization(point: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    summary = point["minimization"]
    if not isinstance(summary, Mapping):
        raise ValueError("relaxed normal point minimization must be an object")
    criterion = summary["stopping_criterion"]
    if not isinstance(criterion, str) or not criterion:
        raise ValueError("relaxed normal point stopping_criterion must be a non-empty string")
    iterations = summary["iterations"]
    force_evaluations = summary["force_evaluations"]
    if (
        isinstance(iterations, bool)
        or not isinstance(iterations, (int, np.integer))
        or iterations < 0
    ):
        raise ValueError("relaxed normal point iterations must be a non-negative integer")
    if (
        isinstance(force_evaluations, bool)
        or not isinstance(force_evaluations, (int, np.integer))
        or force_evaluations < 0
    ):
        raise ValueError("relaxed normal point force_evaluations must be a non-negative integer")
    converged = summary["converged"]
    if not isinstance(converged, bool):
        raise ValueError("relaxed normal point converged must be boolean")
    raw_summary = summary["raw_summary"]
    if not isinstance(raw_summary, str) or not raw_summary:
        raise ValueError("relaxed normal point raw_summary must be a non-empty string")
    native_step = point["native_step"]
    if isinstance(native_step, bool) or not isinstance(native_step, (int, np.integer)):
        raise ValueError("relaxed normal point native_step must be an integer")
    if point["force_source"] != _RELAXED_FORCE_SOURCE:
        raise ValueError(f"relaxed normal point force_source must be {_RELAXED_FORCE_SOURCE!r}")
    preserved = dict(summary)
    preserved["iterations"] = int(iterations)
    preserved["force_evaluations"] = int(force_evaluations)
    preserved["converged"] = converged
    return preserved, int(native_step)


def normal_response_from_points(
    protocol: Mapping[str, Any],
    atom_ids: Sequence[int],
    points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Calculate the explicit fixed-cell normal response selected by kinematics."""

    response = protocol["normal_response"]
    relaxed = response["kinematics"] == _RELAXED_KINEMATICS
    normal_input = _finite_vector(response["normal_cartesian"], "normal_cartesian", 3)
    normal_length = float(np.linalg.norm(normal_input))
    if not np.isclose(normal_length, 1.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("normal_cartesian must be a unit vector")
    normal = normal_input
    area = float(response["area_angstrom2"])
    if not np.isfinite(area) or area <= 0.0:
        raise ValueError("area_angstrom2 must be positive and finite")
    if response["interface_count"] != 2:
        raise ValueError("interface_count must be exactly 2")
    if relaxed:
        fixed_ids, moving_ids, free_ids, atom_positions = _relaxed_atom_groups(response, atom_ids)
        minimization_settings = _relaxed_minimization_settings(response)
    else:
        fixed_ids, moving_ids, atom_positions = _atom_groups(response, atom_ids)
        free_ids = []
        minimization_settings = None

    specifications = list(response["points"])
    observations = list(points)
    if len(specifications) < 2:
        raise ValueError("normal_response.points must contain at least two points")
    if len(observations) != len(specifications):
        raise ValueError("point count differs from protocol.normal_response.points")
    protocol_ids = [specification["point_id"] for specification in specifications]
    observed_ids = [observation["point_id"] for observation in observations]
    if observed_ids != protocol_ids:
        raise ValueError("point order or point_id differs from protocol.normal_response.points")
    if specifications[0]["branch"] != "reference":
        raise ValueError("the first normal-response point must be the reference branch")

    fixed_indices = [atom_positions[atom_id] for atom_id in fixed_ids]
    moving_indices = [atom_positions[atom_id] for atom_id in moving_ids]
    free_indices = [atom_positions[atom_id] for atom_id in free_ids]
    point_products: list[dict[str, Any]] = []
    q_values: list[float] = []
    energies: list[float] = []
    reactions: list[float] = []
    tractions: list[float] = []
    relaxation_converged: list[bool] = []
    for specification, observation in zip(specifications, observations):
        q = float(specification["displacement_angstrom"])
        energy = float(observation["energy_eV"])
        if not np.isfinite(q) or not np.isfinite(energy):
            raise ValueError("point displacement and energy must be finite")
        positions, forces = _point_arrays(observation, len(atom_positions))
        fixed_force = np.sum(forces[fixed_indices], axis=0)
        moving_force = np.sum(forces[moving_indices], axis=0)
        if relaxed:
            minimization, native_step = _relaxed_point_minimization(observation)
            free_force = np.sum(forces[free_indices], axis=0)
            total_force = fixed_force + moving_force + free_force
            fixed_reaction_vector = -fixed_force
            moving_reaction_vector = -moving_force
            fixed_reaction = -float(np.dot(fixed_force, normal))
            relaxation_converged.append(minimization["converged"])
        else:
            minimization = None
            native_step = None
            free_force = None
            total_force = fixed_force + moving_force
            fixed_reaction_vector = None
            moving_reaction_vector = None
            fixed_reaction = None
        reaction = -float(np.dot(moving_force, normal))
        traction = reaction / area * TRACTION_CONVERSION_EV_PER_A3_TO_GPA
        q_values.append(q)
        energies.append(energy)
        reactions.append(reaction)
        tractions.append(traction)
        point_product = {
            "point_id": observation["point_id"],
            "branch": specification["branch"],
            "displacement_angstrom": q,
            "energy_eV": energy,
            "positions_angstrom": positions.tolist(),
            "forces_eV_per_A": forces.tolist(),
            "fixed_atom_ids": fixed_ids,
            "moving_atom_ids": moving_ids,
            "fixed_group_force_eV_per_A": fixed_force.tolist(),
            "moving_group_force_eV_per_A": moving_force.tolist(),
            "total_force_eV_per_A": total_force.tolist(),
            "constraint_reaction_force_eV_per_A": reaction,
            "traction_GPa": traction,
        }
        if relaxed:
            point_product.update(
                {
                    "force_source": _RELAXED_FORCE_SOURCE,
                    "native_step": native_step,
                    "minimization": minimization,
                    "free_atom_ids": free_ids,
                    "free_group_force_eV_per_A": free_force.tolist(),
                    "free_forces_eV_per_A": forces[free_indices].tolist(),
                    "free_force_l2_eV_per_A": float(np.linalg.norm(forces[free_indices])),
                    "free_force_max_abs_eV_per_A": float(np.max(np.abs(forces[free_indices]))),
                    "fixed_constraint_reaction_vector_eV_per_A": fixed_reaction_vector.tolist(),
                    "moving_constraint_reaction_vector_eV_per_A": moving_reaction_vector.tolist(),
                    "fixed_constraint_reaction_force_eV_per_A": fixed_reaction,
                    "moving_constraint_reaction_force_eV_per_A": reaction,
                }
            )
        point_products.append(point_product)

    if q_values[0] != 0.0:
        raise ValueError("the first normal-response point must have displacement_angstrom=0")

    intervals: list[dict[str, Any]] = []
    for index in range(len(point_products) - 1):
        dq = q_values[index + 1] - q_values[index]
        interval = {
            "from_point_id": point_products[index]["point_id"],
            "to_point_id": point_products[index + 1]["point_id"],
            "displacement_delta_angstrom": dq,
            "traction_change_GPa": tractions[index + 1] - tractions[index],
            "energy_change_eV": energies[index + 1] - energies[index],
        }
        if dq == 0.0:
            interval.update(
                {
                    "traction_slope_GPa_per_A": None,
                    "energy_derivative_GPa": None,
                    "status": "undefined_zero_displacement_interval",
                    "reason": "adjacent points have identical displacement",
                }
            )
        else:
            interval.update(
                {
                    "traction_slope_GPa_per_A": (tractions[index + 1] - tractions[index]) / dq,
                    "energy_derivative_GPa": (
                        (energies[index + 1] - energies[index]) / (area * dq)
                        * TRACTION_CONVERSION_EV_PER_A3_TO_GPA
                    ),
                    "status": "available",
                }
            )
        intervals.append(interval)

    if point_products[-1]["branch"] == "unloading" and q_values[-1] == q_values[0]:
        return_closure = {
            "status": "reported_coordinate_return",
            "reference_point_id": point_products[0]["point_id"],
            "return_point_id": point_products[-1]["point_id"],
            "energy_residual_eV": energies[-1] - energies[0],
            "reaction_force_residual_eV_per_A": reactions[-1] - reactions[0],
            "traction_residual_GPa": tractions[-1] - tractions[0],
            "interpretation": (
                "coordinate_return_only_free_internal_state_not_compared"
                if relaxed
                else "coordinate_return_only_not_physical_unloading_recovery"
            ),
        }
    else:
        return_closure = {
            "status": "unresolved",
            "reason": "no unloading point returns to the reference displacement",
        }

    source_kind = protocol.get("source_kind")
    fixture_purpose = protocol.get("fixture_purpose")
    status = (
        "mathematical_fixture"
        if source_kind == "mathematical_fixture" or fixture_purpose == "mathematical_fixture"
        else "available"
    )
    if relaxed:
        constraints = {
            "kinematics": _RELAXED_KINEMATICS,
            "fixed_atom_ids": fixed_ids,
            "moving_atom_ids": moving_ids,
            "free_atom_ids": free_ids,
            "normal_cartesian": normal.tolist(),
            "area_angstrom2": area,
            "interface_count": 2,
            "minimization": minimization_settings,
            "force_source": _RELAXED_FORCE_SOURCE,
            "reaction_definition": "R=-sum(F_moving_clamp) dot n",
            "constraint_reaction_vector_definition": "reaction_vector=-F_group",
            "traction_definition": "T_q=R/A*160.21766208",
            "normalization": "area_once_no_division_by_interface_count",
            "interface_opening_derivatives": None,
            "interface_opening_derivatives_reason": (
                "individual AB/BA openings are not extracted; q is the explicit clamp displacement coordinate"
            ),
        }
    else:
        constraints = {
            "kinematics": "fixed_cell_rigid_side_translation",
            "fixed_atom_ids": fixed_ids,
            "moving_atom_ids": moving_ids,
            "normal_cartesian": normal.tolist(),
            "area_angstrom2": area,
            "interface_count": 2,
            "reaction_definition": "R=-sum(F_moving) dot n",
            "traction_definition": "T_q=R/A*160.21766208",
            "normalization": "area_once_no_division_by_interface_count",
            "interface_opening_derivatives": {"AB": 1.0, "BA": -1.0},
        }
    result = {
        "schema": RESPONSE_SCHEMA,
        "status": status,
        "production_qualified": False,
        "source": {
            "kind": source_kind,
            "fixture": protocol.get("fixture"),
            "fixture_purpose": fixture_purpose,
        },
        "constraints": constraints,
        "points": point_products,
        "intervals": intervals,
        "return_closure": return_closure,
        "units": {
            "energy": "eV",
            "position": "angstrom",
            "force": "eV/angstrom",
            "displacement": "angstrom",
            "area": "angstrom^2",
            "reaction_force": "eV/angstrom",
            "traction": "GPa",
            "traction_slope": "GPa/angstrom",
            "energy_derivative": "GPa",
        },
    }
    if relaxed:
        result["relaxation_status"] = (
            "converged" if all(relaxation_converged) else "unconverged"
        )
    return result


__all__ = ["normal_response_from_points"]
