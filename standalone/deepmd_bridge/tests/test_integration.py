"""Task registration checks; model values are validated by the handoff tests."""
import json

import pytest

from mlcc_deepmd.integration import finalize_training_task


def test_finalize_registers_model_for_existing_runner_collection(tmp_path, monkeypatch):
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({
        "task_id": "training", "engine": "deepmd", "scheduler_job_id": "129",
        "remote_workdir": str(tmp_path), "dataset_manifest": "dataset-manifest.json",
        "dataset_location": {"root": "/remote/dataset"}, "collect_paths": ["frozen_model.pth"],
    }))
    card_file = tmp_path / "model-card.json"
    card_file.write_text(json.dumps({"frozen_model": str(tmp_path / "frozen_model.pth"), "job_id": "129"}))
    scheduler = {"job_id": "129", "state": "COMPLETED", "exit_code": "0:0", "workdir": str(tmp_path)}

    def collect(directory, manifest, record, *, dataset_root):
        assert directory == tmp_path
        assert manifest == tmp_path / "dataset-manifest.json"
        assert record == scheduler
        assert dataset_root == "/remote/dataset"
        return card_file

    monkeypatch.setattr("mlcc_deepmd.handoff.collect_training", collect)
    task = finalize_training_task(task_file, scheduler)
    assert task.data["model_handoff"]["training_job_id"] == "129"
    assert task.data["model_handoff"]["model_card"] == "model-card.json"
    assert "model-card.json" in task.data["collect_paths"]
    assert task.data["scientific_status"] == "not_qualified"
    assert task.data["production_qualification"] is False
    assert json.loads(task_file.read_text())["events"][-1]["action"] == "collect_deepmd_model"


def test_finalize_rejects_a_different_job_before_collection(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"task_id": "training", "engine": "deepmd", "scheduler_job_id": "129"}))
    with pytest.raises(ValueError, match="scheduler identity"):
        finalize_training_task(task_file, {"job_id": "125"})
