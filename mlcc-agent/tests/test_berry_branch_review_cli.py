"""Focused CLI pass-through tests for the Berry branch-review boundary.

These tests replace the two domain functions and check only JSON loading,
argument routing and output creation. They do not consume native Berry data or
authorize a branch.
"""

from __future__ import annotations

import json
from pathlib import Path

import mlcc.cli as cli


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def test_berry_branch_review_dispatches_response_policy_and_out(tmp_path: Path, monkeypatch) -> None:
    response = _write_json(tmp_path / "response.json", {"response_id": "response-1"})
    policy = _write_json(tmp_path / "policy.json", {"candidate_neighbor_radius": 1})
    output = tmp_path / "review" / "suggestions.json"
    calls: dict[str, object] = {}

    def fake_review(response_value, policy_value):
        calls.update(response=response_value, policy=policy_value)
        return {"schema": "dispatcher-test", "decision": "review_required"}

    monkeypatch.setattr(cli, "review_berry_response_branches", fake_review)

    assert cli.main(
        [
            "berry-branch-review",
            "--response",
            str(response),
            "--policy",
            str(policy),
            "--out",
            str(output),
        ]
    ) == 0
    assert calls == {"response": {"response_id": "response-1"}, "policy": {"candidate_neighbor_radius": 1}}
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "schema": "dispatcher-test",
        "decision": "review_required",
    }


def test_berry_branch_consume_dispatches_response_review_and_out_without_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    response = _write_json(tmp_path / "response.json", {"response_id": "response-2"})
    review = _write_json(tmp_path / "review.json", {"response_id": "response-2", "decision": "deferred"})
    output = tmp_path / "consumed.json"
    before = response.read_bytes()
    calls: dict[str, object] = {}

    def fake_consume(response_value, review_value):
        calls.update(response=response_value, review=review_value)
        return {"schema": "dispatcher-test", "decision": "deferred", "gdirs": []}

    monkeypatch.setattr(cli, "consume_berry_branch_review", fake_consume)

    assert cli.main(
        [
            "berry-branch-consume",
            "--response",
            str(response),
            "--review",
            str(review),
            "--out",
            str(output),
        ]
    ) == 0
    assert calls == {
        "response": {"response_id": "response-2"},
        "review": {"response_id": "response-2", "decision": "deferred"},
    }
    assert response.read_bytes() == before
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "schema": "dispatcher-test",
        "decision": "deferred",
        "gdirs": [],
    }
