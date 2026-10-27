"""Review and consume explicit Berry polarization branch declarations.

The Berry response consumer deliberately leaves branch integers unresolved when
the native output does not provide an auditable branch path.  This module is a
small, read-only review boundary around that result.  It computes numerical
relative-branch suggestions from the already parsed ``P`` and ``Q`` values,
but it never turns a suggestion into a physical branch decision.  An external
review record is required before explicit integers can be returned for a new
response request.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


_RESPONSE_SCHEMA = "mlcc.abacus-berry-displacement-response-results.v1"
_SUGGESTION_SCHEMA = "mlcc.abacus-berry-branch-review-suggestions.v1"
_REVIEW_SCHEMA = "mlcc.abacus-berry-branch-review.v1"
_CONSUMPTION_SCHEMA = "mlcc.abacus-berry-branch-review-consumption.v1"


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _number(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _integer(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _string_list(value: Any, *, name: str, require_nonempty: bool) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a list of text references")
    output = [_text(item, name=f"{name}[{index}]") for index, item in enumerate(value)]
    if require_nonempty and not output:
        raise ValueError(f"{name} must not be empty")
    return output


def _policy(value: Any) -> dict[str, Any]:
    policy = _mapping(value, name="explicit_policy")
    radius = _integer(policy.get("candidate_neighbor_radius"), name="explicit_policy.candidate_neighbor_radius")
    if radius < 1:
        raise ValueError("explicit_policy.candidate_neighbor_radius must be at least one")
    quantum_tolerance = _number(
        policy.get("quantum_consistency_tolerance_C_per_m2"),
        name="explicit_policy.quantum_consistency_tolerance_C_per_m2",
    )
    equidistant_tolerance = _number(
        policy.get("equidistant_half_quantum_tolerance_ratio"),
        name="explicit_policy.equidistant_half_quantum_tolerance_ratio",
    )
    near_tolerance = _number(
        policy.get("near_half_quantum_tolerance_ratio"),
        name="explicit_policy.near_half_quantum_tolerance_ratio",
    )
    if quantum_tolerance < 0.0 or equidistant_tolerance < 0.0 or near_tolerance < 0.0:
        raise ValueError("branch review tolerances must be non-negative")
    if near_tolerance < equidistant_tolerance:
        raise ValueError("near_half_quantum_tolerance_ratio must not be smaller than the equidistant tolerance")
    return {
        "candidate_neighbor_radius": radius,
        "quantum_consistency_tolerance_C_per_m2": quantum_tolerance,
        "equidistant_half_quantum_tolerance_ratio": equidistant_tolerance,
        "near_half_quantum_tolerance_ratio": near_tolerance,
    }


def _point_binding(point: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    point_id = _text(point.get("point_id"), name=f"{name}.point_id")
    task = _mapping(point.get("task"), name=f"{name}.task")
    native = _mapping(point.get("native_result"), name=f"{name}.native_result")
    source = _mapping(point.get("source"), name=f"{name}.source")
    task_id = _text(task.get("task_id"), name=f"{name}.task.task_id")
    native_task_id = _text(native.get("task_id"), name=f"{name}.native_result.task_id")
    if native_task_id != task_id:
        raise ValueError(f"{name} native task identity differs from the public task identity")
    scheduler_job_id = _text(task.get("scheduler_job_id"), name=f"{name}.task.scheduler_job_id")
    native_job_id = _text(native.get("scheduler_job_id"), name=f"{name}.native_result.scheduler_job_id")
    if native_job_id != scheduler_job_id:
        raise ValueError(f"{name} native scheduler job differs from the public task job")
    reference_validation = _mapping(
        native.get("reference_scf_validation"),
        name=f"{name}.native_result.reference_scf_validation",
    )
    return {
        "point_id": point_id,
        "task_id": task_id,
        "scheduler_job_id": scheduler_job_id,
        "reference_scf_task_id": _text(
            native.get("reference_scf_task_id"),
            name=f"{name}.native_result.reference_scf_task_id",
        ),
        "reference_scf_task_file": _text(
            reference_validation.get("task_file"),
            name=f"{name}.native_result.reference_scf_validation.task_file",
        ),
        "reference_scf_scheduler_job_id": (
            None
            if reference_validation.get("scheduler_job_id") is None
            else _text(
                reference_validation.get("scheduler_job_id"),
                name=f"{name}.native_result.reference_scf_validation.scheduler_job_id",
            )
        ),
        "P_C_per_m2": _number(
            point.get("representative_P_C_per_m2"),
            name=f"{name}.representative_P_C_per_m2",
        ),
        "Q_C_per_m2": _number(
            point.get("quantum_Q_C_per_m2"),
            name=f"{name}.quantum_Q_C_per_m2",
        ),
        "branch_status": _text(
            native.get("branch_status"),
            name=f"{name}.native_result.branch_status",
        ),
        "branch_unwrapped": native.get("branch_unwrapped"),
        "source_task_file": _text(source.get("task_file"), name=f"{name}.source.task_file"),
        "source_result_file": _text(source.get("result_file"), name=f"{name}.source.result_file"),
        "source_study_file": _text(source.get("study_file"), name=f"{name}.source.study_file"),
        "source_model_path": _text(source.get("model_path"), name=f"{name}.source.model_path"),
    }


def _response_binding(response_result: Mapping[str, Any]) -> dict[str, Any]:
    if response_result.get("schema") != _RESPONSE_SCHEMA:
        raise ValueError(f"response_result schema must be {_RESPONSE_SCHEMA}")
    response_id = _text(response_result.get("response_id"), name="response_result.response_id")
    parent = _mapping(response_result.get("parent"), name="response_result.parent")
    target = _mapping(response_result.get("target"), name="response_result.target")
    directions = response_result.get("directions")
    if isinstance(directions, (str, bytes)) or not isinstance(directions, Sequence) or not directions:
        raise ValueError("response_result.directions must be a non-empty list")
    parent_binding = {
        "study_id": _text(parent.get("study_id"), name="response_result.parent.study_id"),
        "study_file": _text(parent.get("study_file"), name="response_result.parent.study_file"),
        "model_id": _text(parent.get("model_id"), name="response_result.parent.model_id"),
        "model_version": _text(parent.get("model_version"), name="response_result.parent.model_version"),
        "model_path": _text(parent.get("model_path"), name="response_result.parent.model_path"),
    }
    target_binding = {
        "atom_id": _integer(target.get("atom_id"), name="response_result.target.atom_id"),
        "cartesian_axis": _integer(target.get("cartesian_axis"), name="response_result.target.cartesian_axis"),
        "axis_label": _text(target.get("axis_label"), name="response_result.target.axis_label"),
        "displacement_angstrom": _number(
            target.get("displacement_angstrom"),
            name="response_result.target.displacement_angstrom",
        ),
    }
    direction_bindings: list[dict[str, Any]] = []
    seen_gdirs: set[int] = set()
    for index, raw_direction in enumerate(directions):
        direction = _mapping(raw_direction, name=f"response_result.directions[{index}]")
        gdir = _integer(direction.get("gdir"), name=f"response_result.directions[{index}].gdir")
        if gdir in seen_gdirs:
            raise ValueError("response_result directions must not repeat a gdir")
        seen_gdirs.add(gdir)
        minus = _mapping(direction.get("minus"), name=f"response_result.directions[{index}].minus")
        plus = _mapping(direction.get("plus"), name=f"response_result.directions[{index}].plus")
        if _integer(minus.get("sign"), name=f"response_result.directions[{index}].minus.sign") != -1:
            raise ValueError(f"gdir {gdir} minus point must have sign=-1")
        if _integer(plus.get("sign"), name=f"response_result.directions[{index}].plus.sign") != 1:
            raise ValueError(f"gdir {gdir} plus point must have sign=1")
        direction_bindings.append(
            {
                "gdir": gdir,
                "minus": _point_binding(minus, name=f"response_result.directions[{index}].minus"),
                "plus": _point_binding(plus, name=f"response_result.directions[{index}].plus"),
            }
        )
    return {
        "response_id": response_id,
        "parent": parent_binding,
        "target": target_binding,
        "directions": direction_bindings,
    }


def _candidate_values(
    raw_delta: float,
    quantum: float,
    *,
    radius: int,
) -> tuple[list[dict[str, Any]], float, int, int]:
    scaled = -raw_delta / quantum
    lower = math.floor(scaled)
    upper = math.ceil(scaled)
    candidate_integers = sorted(
        {
            base + offset
            for base in (lower, upper)
            for offset in range(-radius, radius + 1)
        }
    )
    values = []
    for relative_integer in candidate_integers:
        corrected_delta = raw_delta + relative_integer * quantum
        values.append(
            {
                "relative_branch_integer": relative_integer,
                "corrected_delta_P_C_per_m2": corrected_delta,
                "corrected_delta_over_Q": corrected_delta / quantum,
                "absolute_residual_P_C_per_m2": abs(corrected_delta),
            }
        )
    return values, scaled, lower, upper


def review_berry_response_branches(
    response_result: Mapping[str, Any],
    explicit_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Return numerical branch suggestions without authorizing a branch.

    The relative integer is ``k = n_plus - n_minus`` and the corrected
    difference is ``(P_plus - P_minus) + k Q``.  A nearest-integer value is a
    numerical suggestion only; this function never returns an approved branch
    declaration or scientific qualification.
    """

    policy = _policy(explicit_policy)
    binding = _response_binding(response_result)
    direction_suggestions: list[dict[str, Any]] = []
    for direction in binding["directions"]:
        minus = direction["minus"]
        plus = direction["plus"]
        q_minus = minus["Q_C_per_m2"]
        q_plus = plus["Q_C_per_m2"]
        if q_minus <= 0.0 or q_plus <= 0.0:
            raise ValueError(f"gdir {direction['gdir']} polarization quantum must be positive")
        if abs(q_minus - q_plus) > policy["quantum_consistency_tolerance_C_per_m2"]:
            raise ValueError(f"gdir {direction['gdir']} plus/minus polarization quantum differs")
        raw_delta = plus["P_C_per_m2"] - minus["P_C_per_m2"]
        candidates, scaled, lower, upper = _candidate_values(
            raw_delta,
            q_minus,
            radius=policy["candidate_neighbor_radius"],
        )
        fractional = scaled - math.floor(scaled)
        distance_to_half = abs(fractional - 0.5)
        if distance_to_half <= policy["equidistant_half_quantum_tolerance_ratio"]:
            ambiguity_class = "equidistant_half_quantum"
        elif distance_to_half <= policy["near_half_quantum_tolerance_ratio"]:
            ambiguity_class = "near_half_quantum"
        else:
            ambiguity_class = "unique"
        nearest = min(candidates, key=lambda item: item["absolute_residual_P_C_per_m2"])
        if ambiguity_class == "equidistant_half_quantum":
            suggestion = None
            nearest_candidates = [lower, upper]
        else:
            suggestion = {
                "relative_branch_integer": nearest["relative_branch_integer"],
                "criterion": "minimum_absolute_corrected_delta",
                "authorized": False,
                "corrected_delta_P_C_per_m2": nearest["corrected_delta_P_C_per_m2"],
            }
            nearest_candidates = [nearest["relative_branch_integer"]]
        direction_suggestions.append(
            {
                "gdir": direction["gdir"],
                "minus": dict(minus),
                "plus": dict(plus),
                "raw_delta_P_C_per_m2": raw_delta,
                "raw_delta_over_Q": raw_delta / q_minus,
                "candidate_relative_branch_integers": candidates,
                "nearest_integer_suggestion": suggestion,
                "nearest_candidate_relative_branch_integers": nearest_candidates,
                "ambiguity": {
                    "class": ambiguity_class,
                    "distance_to_half_quantum": distance_to_half,
                },
            }
        )
    return {
        "schema": _SUGGESTION_SCHEMA,
        "response_id": binding["response_id"],
        "decision": "review_required",
        "binding": {
            "parent": binding["parent"],
            "target": binding["target"],
            "directions": direction_suggestions,
        },
        "policy": policy,
        "directions": direction_suggestions,
        "qualification": {
            "branch_authorized": False,
            "branch_continuity_qualified": False,
            "scientific_qualification": False,
            "production_qualification": False,
        },
    }


def _assert_binding_matches(expected: Mapping[str, Any], supplied: Mapping[str, Any]) -> None:
    supplied_parent = _mapping(supplied.get("parent"), name="review_record.binding.parent")
    supplied_target = _mapping(supplied.get("target"), name="review_record.binding.target")
    if dict(supplied_parent) != dict(expected["parent"]):
        raise ValueError("branch review parent Study/model binding differs from response result")
    if dict(supplied_target) != dict(expected["target"]):
        raise ValueError("branch review target binding differs from response result")
    supplied_directions = supplied.get("directions")
    if isinstance(supplied_directions, (str, bytes)) or not isinstance(supplied_directions, Sequence):
        raise ValueError("review_record.binding.directions must be a list")
    expected_by_gdir = {item["gdir"]: item for item in expected["directions"]}
    supplied_by_gdir: dict[int, Mapping[str, Any]] = {}
    for index, raw in enumerate(supplied_directions):
        direction = _mapping(raw, name=f"review_record.binding.directions[{index}]")
        gdir = _integer(direction.get("gdir"), name=f"review_record.binding.directions[{index}].gdir")
        if gdir in supplied_by_gdir:
            raise ValueError("review_record.binding directions must not repeat a gdir")
        supplied_by_gdir[gdir] = direction
    if set(supplied_by_gdir) != set(expected_by_gdir):
        raise ValueError("branch review binding gdirs differ from response result")
    for gdir, expected_direction in expected_by_gdir.items():
        supplied_direction = supplied_by_gdir[gdir]
        for side in ("minus", "plus"):
            supplied_point = _mapping(
                supplied_direction.get(side),
                name=f"review_record.binding.directions.gdir={gdir}.{side}",
            )
            if dict(supplied_point) != dict(expected_direction[side]):
                raise ValueError(f"branch review {side} point binding differs for gdir={gdir}")


def _review_gdirs(
    review_record: Mapping[str, Any],
    *,
    expected_gdirs: set[int],
    decision: str,
) -> list[dict[str, Any]]:
    raw_gdirs = review_record.get("gdirs")
    if raw_gdirs is None:
        raw_gdirs = []
    if isinstance(raw_gdirs, (str, bytes)) or not isinstance(raw_gdirs, Sequence):
        raise ValueError("review_record.gdirs must be a list")
    by_gdir: dict[int, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_gdirs):
        entry = _mapping(raw, name=f"review_record.gdirs[{index}]")
        gdir = _integer(entry.get("gdir"), name=f"review_record.gdirs[{index}].gdir")
        if gdir in by_gdir:
            raise ValueError("review_record.gdirs must not repeat a gdir")
        by_gdir[gdir] = entry
    if by_gdir and set(by_gdir) != expected_gdirs:
        raise ValueError("review_record.gdirs must cover the response gdirs")
    if decision != "approved":
        for gdir, entry in by_gdir.items():
            branches = _mapping(entry.get("branch_integer", {}), name=f"review_record.gdirs.gdir={gdir}.branch_integer")
            bases = _mapping(entry.get("branch_basis", {}), name=f"review_record.gdirs.gdir={gdir}.branch_basis")
            if branches.get("minus") is not None or branches.get("plus") is not None:
                raise ValueError(f"non-approved branch review cannot declare integers for gdir={gdir}")
            if bases.get("minus") is not None or bases.get("plus") is not None:
                raise ValueError(f"non-approved branch review cannot declare bases for gdir={gdir}")
    output: list[dict[str, Any]] = []
    for gdir in sorted(expected_gdirs):
        entry = by_gdir.get(gdir)
        if decision != "approved":
            output.append(
                {
                    "gdir": gdir,
                    "branch_integer": {"minus": None, "plus": None},
                    "branch_basis": {"minus": None, "plus": None},
                }
            )
            continue
        if entry is None:
            raise ValueError(f"approved branch review lacks explicit gdir={gdir} declaration")
        branches = _mapping(entry.get("branch_integer"), name=f"review_record.gdirs.gdir={gdir}.branch_integer")
        bases = _mapping(entry.get("branch_basis"), name=f"review_record.gdirs.gdir={gdir}.branch_basis")
        minus = _integer(branches.get("minus"), name=f"review_record.gdirs.gdir={gdir}.branch_integer.minus")
        plus = _integer(branches.get("plus"), name=f"review_record.gdirs.gdir={gdir}.branch_integer.plus")
        relative = _integer(
            entry.get("relative_branch_integer"),
            name=f"review_record.gdirs.gdir={gdir}.relative_branch_integer",
        )
        if relative != plus - minus:
            raise ValueError(f"approved branch review relative integer differs for gdir={gdir}")
        minus_basis = _text(bases.get("minus"), name=f"review_record.gdirs.gdir={gdir}.branch_basis.minus")
        plus_basis = _text(bases.get("plus"), name=f"review_record.gdirs.gdir={gdir}.branch_basis.plus")
        baseline_basis = _text(entry.get("baseline_basis"), name=f"review_record.gdirs.gdir={gdir}.baseline_basis")
        insulating_refs = _string_list(
            entry.get("insulating_path_refs"),
            name=f"review_record.gdirs.gdir={gdir}.insulating_path_refs",
            require_nonempty=True,
        )
        output.append(
            {
                "gdir": gdir,
                "branch_integer": {"minus": minus, "plus": plus},
                "branch_basis": {"minus": minus_basis, "plus": plus_basis},
                "relative_branch_integer": relative,
                "baseline_basis": baseline_basis,
                "insulating_path_refs": insulating_refs,
            }
        )
    return output


def consume_berry_branch_review(
    response_result: Mapping[str, Any],
    review_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Consume an external branch review and return request ``gdirs``.

    ``approved`` still means only that an external reviewer declared explicit
    integers with supporting references.  This function does not authenticate
    the references and always leaves physical branch continuity and scientific
    qualification false.
    """

    expected = _response_binding(response_result)
    review = _mapping(review_record, name="review_record")
    if review.get("schema") != _REVIEW_SCHEMA:
        raise ValueError(f"review_record schema must be {_REVIEW_SCHEMA}")
    if _text(review.get("response_id"), name="review_record.response_id") != expected["response_id"]:
        raise ValueError("branch review response_id differs from response result")
    reviewer = _text(review.get("reviewer"), name="review_record.reviewer")
    reviewed_at = _text(review.get("reviewed_at"), name="review_record.reviewed_at")
    decision_basis = _text(review.get("decision_basis"), name="review_record.decision_basis")
    evidence_refs = _string_list(review.get("evidence_refs"), name="review_record.evidence_refs", require_nonempty=True)
    decision = _text(review.get("decision"), name="review_record.decision")
    if decision not in {"deferred", "rejected", "approved"}:
        raise ValueError("review_record.decision must be deferred, rejected or approved")
    supplied_binding = _mapping(review.get("binding"), name="review_record.binding")
    _assert_binding_matches(expected, supplied_binding)
    request_gdirs = _review_gdirs(
        review,
        expected_gdirs={direction["gdir"] for direction in expected["directions"]},
        decision=decision,
    )
    return {
        "schema": _CONSUMPTION_SCHEMA,
        "response_id": expected["response_id"],
        "decision": decision,
        "review": {
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "decision_basis": decision_basis,
            "evidence_refs": evidence_refs,
        },
        "binding": expected,
        "gdirs": request_gdirs,
        "qualification": {
            "review_declared": True,
            "branch_continuity_qualified": False,
            "scientific_qualification": False,
            "production_qualification": False,
        },
    }


__all__ = ["consume_berry_branch_review", "review_berry_response_branches"]
