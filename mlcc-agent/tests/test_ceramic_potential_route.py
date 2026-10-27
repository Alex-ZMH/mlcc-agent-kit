"""Focused checks for the explicit ceramic potential route boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc.ceramic_potential_route import create_selected_ceramic_task
from mlcc.tasks import TaskRecord


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _task(
    workspace: str | Path,
    task_id: str,
    *,
    status: str = "created",
    scientific_status: str = "not_qualified",
) -> TaskRecord:
    task_path = Path(workspace) / "tasks" / task_id / "task.json"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    return TaskRecord(
        {
            "task_id": task_id,
            "status": status,
            "scheduler_job_id": None,
            "scientific_status": scientific_status,
            "production_qualification": False,
        },
        task_path,
    )


def test_missing_or_unknown_selection_fails_before_any_creator(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_training(*args, **kwargs):
        calls.append("training")
        raise AssertionError("training creator must not run")

    def fake_lammps(*args, **kwargs):
        calls.append("lammps")
        raise AssertionError("LAMMPS creator must not run")

    monkeypatch.setattr("mlcc.ceramic_training.create_ceramic_training_task", fake_training)
    monkeypatch.setattr("mlcc.ceramic_md.create_ceramic_lammps_task", fake_lammps)

    for index, (request_data, message) in enumerate((
        ({"operation": "create_training"}, "potential_route"),
        ({"potential_route": "mace", "operation": "create_training"}, "potential_route"),
        ({"potential_route": "abacus_deepmd"}, "operation"),
        ({"potential_route": "abacus_deepmd", "operation": "discover"}, "operation"),
        ({"potential_route": "abacus_deepmd", "operation": []}, "operation"),
    )):
        request = _write_json(tmp_path / f"bad-{index}.json", request_data)
        with pytest.raises(ValueError, match=message):
            create_selected_ceramic_task(request)

    assert calls == []


def test_training_route_reuses_existing_creator_and_records_explicit_selection(tmp_path, monkeypatch):
    request = tmp_path / "create-training.json"
    workspace = tmp_path / "workspace"
    request_data = {
        "potential_route": "abacus_deepmd",
        "operation": "create_training",
        "workspace": str(workspace),
        "task_id": "ceramic-training-v001",
        "input_file": str(tmp_path / "input.json"),
        "collection": str(tmp_path / "collection.json"),
        "interface_acceptance": str(tmp_path / "interface-acceptance.json"),
        "account": "v100",
        "training_config": {
            "nproc_per_node": 2,
            "checkpoint": "model.ckpt.pt",
            "seed": 20261022,
            "partition": "gpu",
        },
    }
    _write_json(request, request_data)
    config_calls = {}
    create_calls = {}

    import mlcc_deepmd.training as training

    def fake_from_input_json(input_json, **kwargs):
        config_calls.update(input_json=input_json, kwargs=kwargs)
        return "training-config"

    def fake_create(workspace_path, task_id, config, input_file, collection, interface_acceptance, *, account):
        create_calls.update(
            workspace=workspace_path,
            task_id=task_id,
            config=config,
            input_file=input_file,
            collection=collection,
            interface_acceptance=interface_acceptance,
            account=account,
        )
        return _task(workspace_path, task_id)

    monkeypatch.setattr(training.DeepMDTrainingConfig, "from_input_json", staticmethod(fake_from_input_json))
    monkeypatch.setattr("mlcc.ceramic_training.create_ceramic_training_task", fake_create)

    task = create_selected_ceramic_task(request)

    assert config_calls == {
        "input_json": request_data["input_file"],
        "kwargs": {
            "workdir": workspace / "tasks" / request_data["task_id"],
            **request_data["training_config"],
        },
    }
    assert create_calls == {
        "workspace": workspace,
        "task_id": request_data["task_id"],
        "config": "training-config",
        "input_file": request_data["input_file"],
        "collection": request_data["collection"],
        "interface_acceptance": request_data["interface_acceptance"],
        "account": request_data["account"],
    }
    expected_route = {
        "selected": "abacus_deepmd",
        "selection": "explicit",
        "operation": "create_training",
        "request_file": str(request.resolve()),
    }
    assert task.data["potential_route"] == expected_route
    assert task.data["status"] == "created"
    assert task.data["scheduler_job_id"] is None
    assert task.data["scientific_status"] == "not_qualified"
    assert task.data["production_qualification"] is False
    assert task.data["events"][-1]["action"] == "select_ceramic_potential_route"
    assert task.data["events"][-1]["potential_route"] == expected_route
    assert task.data["events"][-1]["request_file"] == str(request.resolve())
    assert json.loads(task.path.read_text(encoding="utf-8"))["potential_route"] == expected_route


def test_lammps_route_passes_one_selected_system_without_fanout(tmp_path, monkeypatch):
    request = tmp_path / "create-lammps.json"
    request_data = {
        "potential_route": "abacus_deepmd",
        "operation": "create_lammps",
        "workspace": str(tmp_path / "workspace"),
        "task_id": "ceramic-lammps-v001",
        "collection": str(tmp_path / "collection.json"),
        "system_id": "host20",
        "model_card": str(tmp_path / "model-card.json"),
        "protocol": {"kind": "run0", "steps": 5, "engineering_scope": "route test"},
        "site": {"runner": {"selected": "slurm"}},
        "resource_request": {"ntasks": 1, "gres": "gpu:v100:1"},
    }
    _write_json(request, request_data)
    calls = {}

    def fake_create(*args):
        calls["args"] = args
        return _task(args[0], args[1], status="defined", scientific_status="not_calculated")

    monkeypatch.setattr("mlcc.ceramic_md.create_ceramic_lammps_task", fake_create)

    task = create_selected_ceramic_task(request)

    assert calls["args"] == (
        request_data["workspace"],
        request_data["task_id"],
        request_data["collection"],
        request_data["system_id"],
        request_data["model_card"],
        request_data["protocol"],
        request_data["site"],
        request_data["resource_request"],
    )
    assert task.data["potential_route"]["operation"] == "create_lammps"
    assert task.data["status"] == "defined"
    assert task.data["scheduler_job_id"] is None
    assert task.data["scientific_status"] == "not_calculated"


def test_creator_error_is_returned_without_fallback(tmp_path, monkeypatch):
    request = _write_json(
        tmp_path / "creator-error.json",
        {
            "potential_route": "abacus_deepmd",
            "operation": "create_lammps",
            "workspace": str(tmp_path / "workspace"),
            "task_id": "creator-error",
            "collection": "collection.json",
            "system_id": "host20",
            "model_card": "model-card.json",
            "protocol": {},
            "site": {},
            "resource_request": {},
        },
    )

    def fail(*args):
        raise RuntimeError("native ceramic creator failure")

    monkeypatch.setattr("mlcc.ceramic_md.create_ceramic_lammps_task", fail)

    with pytest.raises(RuntimeError, match="native ceramic creator failure"):
        create_selected_ceramic_task(request)
