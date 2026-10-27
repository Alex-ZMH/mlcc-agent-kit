from __future__ import annotations

import copy
import json
from pathlib import Path

from mlcc.tasks import TaskRecord, save_task
from mlcc.workflow import inspect_task, source_evidence


_STATUS = "engineering_sampling_not_equilibrium_qualification"


def _protocol() -> dict[str, object]:
    return {
        "kind": "md",
        "purpose": "md_native_sampling",
        "ensemble": "nvt",
        "unwrapped_trajectory": True,
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "experiment_scope": "finite native sampling workflow",
    }


def _potential() -> dict[str, object]:
    return {
        "potential_id": "deepmd-czo-neutral",
        "version": "v001",
        "fixture": True,
        "production_qualification": False,
        "files": [{"local_path": "training/frozen_model.pth", "filename": "frozen.pth"}],
    }


def _source_names() -> tuple[str, ...]:
    return (
        "log.lammps",
        "dump.final",
        "trajectory.lammpstrj",
        "in.lammps",
        "sampling.lammpstrj",
        "pressure-series.dat",
        "trajectory.unwrapped.lammpstrj",
    )


def _task_with_result(tmp_path: Path) -> tuple[TaskRecord, Path, dict[str, object]]:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    task_path = task_dir / "task.json"
    result_path = task_dir / "result.json"
    protocol = _protocol()
    potential = _potential()
    task_data: dict[str, object] = {
        "task_id": "czo-md-native-sampling-v001",
        "calculation": "md",
        "engine": "lammps",
        "engine_version": "LAMMPS test native",
        "scheduler_job_id": "7001",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "status": "COMPLETED",
        "collect_status": "collected",
        "result_file": str(result_path),
        "model_id": "cazro3-pnma-pristine",
        "model_version": "v001",
        "fixture": False,
        "production_label": False,
        "production_qualification": False,
        "study_id": "cazro3-firing-validation-v003",
        "case_id": "cazro3-pnma-undoped",
        "case_role": "material_validation",
        "method_set": "lammps-deepmd-czo-neutral-joint-training-v001-146",
        "protocol": protocol,
        "potential": potential,
    }
    task = TaskRecord(task_data, task_path)
    save_task(task)

    source_files: dict[str, str] = {}
    for name in _source_names():
        source = task_dir / name
        source.write_text("native source\n", encoding="utf-8")
        source_files[name] = str(source)
    result: dict[str, object] = {
        "schema": "mlcc.lammps-result.v1",
        "engine": "lammps",
        "engine_version": task_data["engine_version"],
        "task_id": task_data["task_id"],
        "scheduler_job_id": task_data["scheduler_job_id"],
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "model_id": task_data["model_id"],
        "version": task_data["model_version"],
        "study_id": task_data["study_id"],
        "case_id": task_data["case_id"],
        "case_role": task_data["case_role"],
        "method_set": task_data["method_set"],
        "protocol": copy.deepcopy(protocol),
        "fixture": False,
        "potential": copy.deepcopy(potential),
        "production_label": False,
        "production_qualification": False,
        "sampling_equilibrium_qualified": False,
        "scientific_status": _STATUS,
        "source_files": source_files,
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return task, result_path, result


def test_native_sampling_result_completes_without_scientific_promotion(tmp_path: Path) -> None:
    task, result_path, result = _task_with_result(tmp_path)

    paths, invalid, reason = source_evidence(result, result_path, engine="lammps")
    assert reason == "complete"
    assert invalid == []
    assert {path.name for path in paths} >= set(_source_names())

    plan = inspect_task(task)

    assert plan["action"] == "completed"
    assert plan["scientific_status"] == _STATUS
    assert plan["scientific_status"] not in {"converged", "converged_engineering_fixture"}
    assert plan["scientific_qualification"] is False
    assert "finite native sampling, not equilibrium qualification" in plan["reason"]
    assert any(Path(path).name == "sampling.lammpstrj" for path in plan["source_artifacts"])


def test_native_sampling_result_rejects_missing_sampling_source(tmp_path: Path) -> None:
    task, result_path, result = _task_with_result(tmp_path)
    result["source_files"] = dict(result["source_files"])
    del result["source_files"]["pressure-series.dat"]
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    _, invalid, reason = source_evidence(result, result_path, engine="lammps")
    assert reason == "missing_lammps_native_outputs"
    assert any(path.name == "pressure-series.dat" for path in invalid)

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"
    assert plan["scientific_status"] == _STATUS
    assert "pressure-series.dat" in plan["reason"]


def test_native_sampling_result_accepts_staged_potential_path(tmp_path: Path) -> None:
    task, result_path, result = _task_with_result(tmp_path)
    staged = tmp_path / "task" / "frozen.pth"
    staged.write_text("staged native potential\n", encoding="utf-8")
    result["potential"] = copy.deepcopy(result["potential"])
    result["potential"]["files"] = [{
        "local_path": str(staged),
        "filename": "frozen.pth",
    }]
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    plan = inspect_task(task)

    assert plan["action"] == "completed"
    assert plan["scientific_status"] == _STATUS


def test_native_sampling_result_rejects_potential_identity_mismatch(tmp_path: Path) -> None:
    task, result_path, result = _task_with_result(tmp_path)
    result["potential"] = copy.deepcopy(result["potential"])
    result["potential"]["version"] = "v002"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"
    assert plan["scientific_status"] == _STATUS
