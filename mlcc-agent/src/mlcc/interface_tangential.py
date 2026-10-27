"""Direct fixed-cell tangential response reduction for layered interfaces."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from .interface_normal import (
    _finite_vector,
    _point_arrays,
    _relaxed_atom_groups,
    _relaxed_minimization_settings,
    _relaxed_point_minimization,
)


RESPONSE_SCHEMA = "mlcc.interface-tangential-response.v1"
TANGENTIAL_CONVERSION_EV_PER_A3_TO_GPA = 160.21766208
_KINEMATICS = "fixed_cell_clamped_internal_relaxation"
_FORCE_SOURCE = "unconstrained_run0_at_minimized_geometry"
_STOPPING_CRITERIA = {"energy tolerance", "force tolerance"}


def tangential_response_from_points(
    protocol: Mapping[str, Any],
    atom_ids: Sequence[int],
    points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Calculate the explicit fixed-cell tangential clamp response."""

    if protocol["kind"] != "interface_tangential":
        raise ValueError("tangential protocol kind must be interface_tangential")
    if protocol["purpose"] != "interface_tangential_response":
        raise ValueError("tangential protocol purpose must be interface_tangential_response")
    response = protocol["tangential_response"]
    if response["schema"] != "mlcc.interface-tangential-protocol.v1":
        raise ValueError("tangential_response schema is unsupported")
    if response["kinematics"] != _KINEMATICS:
        raise ValueError("tangential response requires fixed_cell_clamped_internal_relaxation")

    normal = _finite_vector(response["normal_cartesian"], "normal_cartesian", 3)
    tangent = _finite_vector(response["tangential_cartesian"], "tangential_cartesian", 3)
    if not np.isclose(np.linalg.norm(normal), 1.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("normal_cartesian must be a unit vector")
    if not np.isclose(np.linalg.norm(tangent), 1.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("tangential_cartesian must be a unit vector")
    if not np.isclose(np.dot(normal, tangent), 0.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("tangential_cartesian must be orthogonal to normal_cartesian")
    area = float(response["area_angstrom2"])
    if not np.isfinite(area) or area <= 0.0:
        raise ValueError("area_angstrom2 must be positive and finite")
    if response["interface_count"] != 2:
        raise ValueError("interface_count must be exactly 2")

    model_atom_ids = [int(value) for value in atom_ids]
    fixed_ids, moving_ids, free_ids, atom_positions = _relaxed_atom_groups(response, model_atom_ids)
    minimization_settings = _relaxed_minimization_settings(response)
    specifications = list(response["points"])
    observations = list(points)
    if len(specifications) < 2:
        raise ValueError("tangential_response.points must contain at least two points")
    if len(observations) != len(specifications):
        raise ValueError("point count differs from protocol.tangential_response.points")

    protocol_ids: list[str] = []
    q_values: list[float] = []
    branches: list[str] = []
    for specification in specifications:
        point_id = specification["point_id"]
        branch = specification["branch"]
        q = float(specification["displacement_angstrom"])
        if point_id in protocol_ids:
            raise ValueError("tangential response point_id values must be unique")
        if branch not in {"reference", "loading", "unloading"}:
            raise ValueError("tangential response point branch is unsupported")
        if not np.isfinite(q):
            raise ValueError("tangential response displacement must be finite")
        protocol_ids.append(point_id)
        branches.append(branch)
        q_values.append(q)
    if branches[0] != "reference" or q_values[0] != 0.0:
        raise ValueError("first tangential response point must be reference at zero displacement")
    observed_ids = [observation["point_id"] for observation in observations]
    if observed_ids != protocol_ids:
        raise ValueError("point order or point_id differs from protocol.tangential_response.points")

    fixed_indices = [atom_positions[atom_id] for atom_id in fixed_ids]
    moving_indices = [atom_positions[atom_id] for atom_id in moving_ids]
    free_indices = [atom_positions[atom_id] for atom_id in free_ids]
    point_products: list[dict[str, Any]] = []
    energies: list[float] = []
    reactions: list[float] = []
    stresses: list[float] = []
    converged: list[bool] = []
    for observation, q, branch in zip(observations, q_values, branches):
        energy = float(observation["energy_eV"])
        if not np.isfinite(energy):
            raise ValueError("point energy must be finite")
        positions, forces = _point_arrays(observation, len(model_atom_ids))
        fixed_force = np.sum(forces[fixed_indices], axis=0)
        moving_force = np.sum(forces[moving_indices], axis=0)
        free_force = np.sum(forces[free_indices], axis=0)
        total_force = fixed_force + moving_force + free_force
        fixed_reaction_vector = -fixed_force
        moving_reaction_vector = -moving_force
        minimization, native_step = _relaxed_point_minimization(observation)
        criterion = minimization["stopping_criterion"].lower()
        if minimization["converged"] and criterion not in _STOPPING_CRITERIA:
            raise ValueError(
                "converged tangential point has unsupported stopping criterion"
            )
        tangential_reaction = -float(np.dot(moving_force, tangent))
        fixed_reaction = -float(np.dot(fixed_force, tangent))
        stress = tangential_reaction / area * TANGENTIAL_CONVERSION_EV_PER_A3_TO_GPA
        energies.append(energy)
        reactions.append(tangential_reaction)
        stresses.append(stress)
        converged.append(minimization["converged"])
        point_products.append(
            {
                "point_id": observation["point_id"],
                "branch": branch,
                "displacement_angstrom": q,
                "energy_eV": energy,
                "positions_angstrom": positions.tolist(),
                "forces_eV_per_A": forces.tolist(),
                "fixed_atom_ids": fixed_ids,
                "moving_atom_ids": moving_ids,
                "free_atom_ids": free_ids,
                "fixed_group_force_eV_per_A": fixed_force.tolist(),
                "moving_group_force_eV_per_A": moving_force.tolist(),
                "free_group_force_eV_per_A": free_force.tolist(),
                "total_force_eV_per_A": total_force.tolist(),
                "free_forces_eV_per_A": forces[free_indices].tolist(),
                "free_force_l2_eV_per_A": float(np.linalg.norm(forces[free_indices])),
                "free_force_max_abs_eV_per_A": float(np.max(np.abs(forces[free_indices]))),
                "fixed_constraint_reaction_vector_eV_per_A": fixed_reaction_vector.tolist(),
                "moving_constraint_reaction_vector_eV_per_A": moving_reaction_vector.tolist(),
                "fixed_tangential_reaction_force_eV_per_A": fixed_reaction,
                "tangential_reaction_force_eV_per_A": tangential_reaction,
                "cell_net_tangential_stress_GPa": stress,
                "native_step": native_step,
                "minimization": minimization,
                "force_source": observation["force_source"],
            }
        )

    intervals: list[dict[str, Any]] = []
    for index in range(len(point_products) - 1):
        dq = q_values[index + 1] - q_values[index]
        reaction_change = reactions[index + 1] - reactions[index]
        stress_change = stresses[index + 1] - stresses[index]
        interval = {
            "from_point_id": point_products[index]["point_id"],
            "to_point_id": point_products[index + 1]["point_id"],
            "from_branch": branches[index],
            "to_branch": branches[index + 1],
            "displacement_delta_angstrom": dq,
            "energy_change_eV": energies[index + 1] - energies[index],
            "tangential_reaction_change_eV_per_A": reaction_change,
            "cell_net_tangential_stress_change_GPa": stress_change,
        }
        if dq == 0.0:
            interval.update(
                {
                    "tangential_stiffness_eV_per_A2": None,
                    "cell_net_tangential_stress_slope_GPa_per_A": None,
                    "status": "undefined_zero_displacement_interval",
                    "reason": "adjacent points have identical displacement",
                }
            )
        else:
            interval.update(
                {
                    "tangential_stiffness_eV_per_A2": reaction_change / dq,
                    "cell_net_tangential_stress_slope_GPa_per_A": stress_change / dq,
                    "status": "available",
                }
            )
        intervals.append(interval)

    if branches[-1] == "unloading" and q_values[-1] == q_values[0]:
        return_closure = {
            "status": "reported_coordinate_return",
            "reference_point_id": point_products[0]["point_id"],
            "return_point_id": point_products[-1]["point_id"],
            "energy_residual_eV": energies[-1] - energies[0],
            "tangential_reaction_residual_eV_per_A": reactions[-1] - reactions[0],
            "cell_net_tangential_stress_residual_GPa": stresses[-1] - stresses[0],
            "interpretation": "clamp_coordinate_return_only_free_internal_state_not_compared_not_physical_recovery",
        }
    else:
        return_closure = {
            "status": "unresolved",
            "reason": "the final point is not an unloading return to the reference displacement",
        }

    source_kind = protocol.get("source_kind")
    fixture_purpose = protocol.get("fixture_purpose")
    status = (
        "mathematical_fixture"
        if source_kind == "mathematical_fixture" or fixture_purpose == "mathematical_fixture"
        else "available"
    )
    return {
        "schema": RESPONSE_SCHEMA,
        "status": status,
        "relaxation_status": "converged" if all(converged) else "unconverged",
        "production_qualified": False,
        "atom_ids": model_atom_ids,
        "source": {
            "kind": source_kind,
            "fixture": protocol.get("fixture"),
            "fixture_purpose": fixture_purpose,
        },
        "constraints": {
            "kinematics": _KINEMATICS,
            "fixed_atom_ids": fixed_ids,
            "moving_atom_ids": moving_ids,
            "free_atom_ids": free_ids,
            "normal_cartesian": normal.tolist(),
            "tangential_cartesian": tangent.tolist(),
            "area_angstrom2": area,
            "interface_count": 2,
            "minimization": minimization_settings,
            "force_source": _FORCE_SOURCE,
            "reaction_definition": "R_t=-sum(F_moving_clamp) dot t",
            "fixed_reaction_definition": "R_t_fixed=-sum(F_fixed_clamp) dot t",
            "constraint_reaction_vector_definition": "reaction_vector=-F_group",
            "stress_definition": "tau_t=R_t/A*160.21766208",
            "normalization": "area_once_no_division_by_interface_count",
            "stress_scope": "cell_net_tangential_stress_not_single_interface_traction",
            "stiffness_scope": "adjacent_clamp_response_not_material_shear_modulus",
        },
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
            "stress": "GPa",
            "stiffness": "eV/angstrom^2",
            "stress_slope": "GPa/angstrom",
        },
    }


__all__ = ["tangential_response_from_points"]
