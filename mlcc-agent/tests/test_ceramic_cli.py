"""Focused dispatcher checks for the public ceramic CLI branches.

These tests check only argument/configuration pass-through.  Domain functions
are replaced with small call recorders, so the tests do not manufacture a
scientific result or stand in for the v100 engineering acceptance job.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import mlcc.cli as cli


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_ceramic_data_dispatches_request_and_output(tmp_path, monkeypatch):
    request = tmp_path / "request.json"
    output = tmp_path / "collection.json"
    _write_json(request, {"systems": []})
    calls = {}

    def fake_convert(request_path, output_path):
        calls.update(request=request_path, output=output_path)
        return {"status": "dispatcher_mock"}

    monkeypatch.setattr("mlcc.ceramic_data.convert_ceramic_systems", fake_convert)

    assert cli.main(["ceramic-data", "--request", str(request), "--output", str(output)]) == 0
    assert calls == {"request": request, "output": output}


def test_ceramic_training_bind_dispatches_collection_and_output(tmp_path, monkeypatch):
    collection = tmp_path / "collection.json"
    output = tmp_path / "dataset-manifest.json"
    _write_json(collection, {"schema": "dispatcher-only"})
    calls = {}

    def fake_bind(collection_path, output_path):
        calls.update(collection=collection_path, output=output_path)
        return {"status": "dispatcher_mock"}

    monkeypatch.setattr("mlcc.ceramic_training.bind_ceramic_training_dataset", fake_bind)

    assert cli.main(["ceramic-training-bind", "--collection", str(collection), "--output", str(output)]) == 0
    assert calls == {"collection": collection, "output": output}


def test_create_ceramic_training_builds_config_and_passes_request(tmp_path, monkeypatch):
    request = tmp_path / "create-training.json"
    workspace = tmp_path / "workspace"
    input_file = tmp_path / "input.json"
    collection = tmp_path / "collection.json"
    interface = tmp_path / "interface-acceptance.json"
    for path in (input_file, collection, interface):
        _write_json(path, {"dispatcher": "placeholder"})
    request_data = {
        "workspace": str(workspace),
        "task_id": "dispatcher-training-v001",
        "input_file": str(input_file),
        "collection": str(collection),
        "interface_acceptance": str(interface),
        "account": "v100",
        "training_config": {
            "nproc_per_node": 1,
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
        return "dispatcher-config"

    def fake_create(workspace_path, task_id, config, input_path, collection_path, interface_path, *, account):
        create_calls.update(
            workspace=workspace_path,
            task_id=task_id,
            config=config,
            input_file=input_path,
            collection=collection_path,
            interface_acceptance=interface_path,
            account=account,
        )
        return SimpleNamespace(data={"status": "dispatcher_mock"})

    monkeypatch.setattr(training.DeepMDTrainingConfig, "from_input_json", staticmethod(fake_from_input_json))
    monkeypatch.setattr("mlcc.ceramic_training.create_ceramic_training_task", fake_create)

    assert cli.main(["create-ceramic-training", "--request", str(request)]) == 0
    assert config_calls == {
        "input_json": str(input_file),
        "kwargs": {
            "workdir": workspace / "tasks" / "dispatcher-training-v001",
            **request_data["training_config"],
        },
    }
    assert create_calls == {
        "workspace": workspace,
        "task_id": "dispatcher-training-v001",
        "config": "dispatcher-config",
        "input_file": str(input_file),
        "collection": str(collection),
        "interface_acceptance": str(interface),
        "account": "v100",
    }


def test_finalize_ceramic_training_passes_scheduler_record(tmp_path, monkeypatch):
    task = tmp_path / "task.json"
    scheduler_record = tmp_path / "scheduler-record.json"
    _write_json(task, {"dispatcher": "task"})
    record = {"job_id": "146", "state": "COMPLETED", "exit_code": "0:0"}
    _write_json(scheduler_record, record)
    calls = {}

    def fake_finalize(task_path, scheduler):
        calls.update(task=task_path, scheduler=scheduler)
        return SimpleNamespace(data={"status": "dispatcher_mock"})

    monkeypatch.setattr("mlcc.ceramic_training.finalize_ceramic_training_task", fake_finalize)

    assert cli.main(
        [
            "finalize-ceramic-training",
            "--task",
            str(task),
            "--scheduler-record",
            str(scheduler_record),
        ]
    ) == 0
    assert calls == {"task": task, "scheduler": record}


def test_create_ceramic_lammps_passes_all_request_fields(tmp_path, monkeypatch):
    request = tmp_path / "create-lammps.json"
    request_data = {
        "workspace": str(tmp_path / "workspace"),
        "task_id": "dispatcher-lammps-v001",
        "collection": str(tmp_path / "collection.json"),
        "system_id": "host20",
        "model_card": str(tmp_path / "model-card.json"),
        "protocol": {"kind": "md", "units": "metal", "engineering_scope": "dispatcher"},
        "site": {"runner": {"selected": "slurm"}},
        "resource_request": {"ntasks": 1, "gres": "gpu:v100:1"},
    }
    _write_json(request, request_data)
    calls = {}

    def fake_create(*args):
        calls["args"] = args
        return SimpleNamespace(data={"status": "dispatcher_mock"})

    monkeypatch.setattr("mlcc.ceramic_md.create_ceramic_lammps_task", fake_create)

    assert cli.main(["create-ceramic-lammps", "--request", str(request)]) == 0
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


def test_parse_ceramic_lammps_dispatches_task(tmp_path, monkeypatch):
    task = tmp_path / "completed-task"
    task.mkdir()
    calls = {}

    def fake_parse(task_path):
        calls["task"] = task_path
        return {"status": "dispatcher_mock"}

    monkeypatch.setattr("mlcc.ceramic_md.finalize_ceramic_lammps_task", fake_parse)

    assert cli.main(["parse-ceramic-lammps", "--task", str(task)]) == 0
    assert calls == {"task": task}
