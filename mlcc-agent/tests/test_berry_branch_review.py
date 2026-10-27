from __future__ import annotations

"""Software-math-only tests; no test establishes Berry/material qualification."""

import copy

import pytest

from mlcc.berry_branch_review import (
    consume_berry_branch_review,
    review_berry_response_branches,
)


SOFTWARE_MATH_ONLY = True


def _policy() -> dict[str, object]:
    return {
        "candidate_neighbor_radius": 1,
        "quantum_consistency_tolerance_C_per_m2": 1.0e-9,
        "equidistant_half_quantum_tolerance_ratio": 1.0e-9,
        "near_half_quantum_tolerance_ratio": 1.0e-3,
    }


def _point(*, point_id: str, sign: int, p: float, job: str) -> dict[str, object]:
    task_id = f"task-{point_id}"
    task_file = f"/native/{task_id}/task.json"
    result_file = f"/native/{task_id}/result.json"
    study_file = f"/native/{point_id}/study.json"
    model_path = f"/native/{point_id}/model"
    return {
        "point_id": point_id,
        "sign": sign,
        "representative_P_C_per_m2": p,
        "quantum_Q_C_per_m2": 2.0,
        "task": {
            "task_id": task_id,
            "scheduler_job_id": job,
        },
        "native_result": {
            "task_id": task_id,
            "scheduler_job_id": job,
            "reference_scf_task_id": f"scf-{point_id}",
            "reference_scf_validation": {
                "task_file": f"/native/scf-{point_id}/task.json",
                "scheduler_job_id": f"scf-{point_id}",
            },
            "branch_status": "not_unwrapped",
            "branch_unwrapped": False,
        },
        "source": {
            "task_file": task_file,
            "result_file": result_file,
            "study_file": study_file,
            "model_path": model_path,
        },
    }


def _response(*, plus_p: float = 3.0, minus_p: float = 1.0) -> dict[str, object]:
    return {
        "schema": "mlcc.abacus-berry-displacement-response-results.v1",
        "response_id": "review-test-response",
        "parent": {
            "study_id": "parent-study",
            "study_file": "/native/parent/study.json",
            "model_id": "parent-model",
            "model_version": "v001",
            "model_path": "/native/parent/model",
        },
        "target": {
            "atom_id": 8,
            "cartesian_axis": 0,
            "axis_label": "x",
            "displacement_angstrom": 0.01,
        },
        "directions": [
            {
                "gdir": 1,
                "minus": _point(point_id="minus", sign=-1, p=minus_p, job="180"),
                "plus": _point(point_id="plus", sign=1, p=plus_p, job="181"),
            }
        ],
    }


def _review_record(suggestions: dict[str, object], *, decision: str = "deferred") -> dict[str, object]:
    return {
        "schema": "mlcc.abacus-berry-branch-review.v1",
        "response_id": suggestions["response_id"],
        "reviewer": "reviewer-test",
        "reviewed_at": "2026-10-22T00:00:00+08:00",
        "decision": decision,
        "decision_basis": "branch continuity is externally reviewed separately",
        "evidence_refs": ["review/evidence.json"],
        "binding": copy.deepcopy(suggestions["binding"]),
    }


def test_integer_math_suggestion_is_relative_and_never_authorized() -> None:
    response = _response()
    suggestions = review_berry_response_branches(response, _policy())

    direction = suggestions["directions"][0]
    assert direction["raw_delta_P_C_per_m2"] == pytest.approx(2.0)
    assert direction["raw_delta_over_Q"] == pytest.approx(1.0)
    assert direction["nearest_integer_suggestion"]["relative_branch_integer"] == -1
    assert direction["nearest_integer_suggestion"]["authorized"] is False
    assert direction["ambiguity"]["class"] == "unique"
    assert {item["relative_branch_integer"] for item in direction["candidate_relative_branch_integers"]} == {
        -2,
        -1,
        0,
    }
    assert suggestions["qualification"]["branch_authorized"] is False


def test_equally_distant_half_quantum_has_no_nearest_integer_suggestion() -> None:
    response = _response(plus_p=1.0, minus_p=0.0)
    suggestions = review_berry_response_branches(response, _policy())

    direction = suggestions["directions"][0]
    assert direction["ambiguity"]["class"] == "equidistant_half_quantum"
    assert direction["nearest_integer_suggestion"] is None
    assert direction["nearest_candidate_relative_branch_integers"] == [-1, 0]


def test_quantum_mismatch_over_explicit_tolerance_is_rejected() -> None:
    response = _response()
    response["directions"][0]["plus"]["quantum_Q_C_per_m2"] = 2.1

    with pytest.raises(ValueError, match="polarization quantum differs"):
        review_berry_response_branches(response, _policy())


def test_deferred_review_returns_null_request_branches() -> None:
    response = _response()
    suggestions = review_berry_response_branches(response, _policy())
    consumed = consume_berry_branch_review(response, _review_record(suggestions))

    assert consumed["decision"] == "deferred"
    assert consumed["gdirs"] == [
        {
            "gdir": 1,
            "branch_integer": {"minus": None, "plus": None},
            "branch_basis": {"minus": None, "plus": None},
        }
    ]
    assert consumed["qualification"]["branch_continuity_qualified"] is False
    assert consumed["qualification"]["scientific_qualification"] is False


def test_approved_review_requires_explicit_basis_and_insulating_path() -> None:
    response = _response()
    suggestions = review_berry_response_branches(response, _policy())
    record = _review_record(suggestions, decision="approved")
    record["gdirs"] = [
        {
            "gdir": 1,
            "branch_integer": {"minus": 4, "plus": 3},
            "branch_basis": {"minus": "external-minus", "plus": "external-plus"},
            "relative_branch_integer": -1,
            "baseline_basis": "same fixed-cell reference branch",
            "insulating_path_refs": ["review/insulating-path.json"],
        }
    ]
    consumed = consume_berry_branch_review(response, record)

    assert consumed["gdirs"][0]["branch_integer"] == {"minus": 4, "plus": 3}
    assert consumed["gdirs"][0]["relative_branch_integer"] == -1
    assert consumed["qualification"]["branch_continuity_qualified"] is False

    missing_evidence = copy.deepcopy(record)
    missing_evidence["gdirs"][0]["insulating_path_refs"] = []
    with pytest.raises(ValueError, match="insulating_path_refs"):
        consume_berry_branch_review(response, missing_evidence)


def test_review_rejects_response_identity_mixing() -> None:
    response = _response()
    suggestions = review_berry_response_branches(response, _policy())
    record = _review_record(suggestions)
    record["binding"]["directions"][0]["plus"]["task_id"] = "wrong-task"

    with pytest.raises(ValueError, match="point binding differs"):
        consume_berry_branch_review(response, record)

