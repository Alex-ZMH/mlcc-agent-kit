from __future__ import annotations

import copy
import json
from pathlib import Path

from mlcc.tasks import TaskRecord, save_task
from mlcc.workflow import inspect_task, source_evidence


_STATUS = "executed_bulk_thermal_protocol"


def _protocol() -> dict[str, object]:
    return {
        "kind": "md",
        "purpose": "md_bulk_thermal",
        "ensemble": "npt",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "temperature_K": 400.0,
        "pressure_coupling": "iso",
        "pressure_target_bar": 0.0,
        "pdamp_ps": 0.1,
        "tdamp_ps": 0.01,
        "steps": 20,
        "thermo_every": 10,
        "bulk_thermal": {"equilibration_steps": 10, "production_steps": 10},
    }


def _potential() -> dict[str, object]:
    return {
        "potential_id": "deepmd-czo-neutral",
        "version": "v001",
        "fixture": True,
        "production_qualification": False,
        "files": [{"local_path": "training/frozen_model.pth", "filename": "frozen.pth"}],
    }


def _task_with_result(tmp_path: Path) -> tuple[TaskRecord, Path, dict[str, object]]:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    task_path = task_dir / "task.json"
    result_path = task_dir / "result.json"
    protocol = _protocol()
    potential = _potential()
    task_data: dict[str, object] = {
        "task_id": "czo-md-bulk-thermal-v001",
        "calculation": "md",
        "engine": "lammps",
        "engine_version": "LAMMPS test native",
        "scheduler_job_id": "7011",
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
    for name in (
        "in.lammps",
        "method.json",
        "atom-map.json",
        "model.data",
        "frozen.pth",
        "log.lammps",
        "dump.final",
        "trajectory.lammpstrj",
    ):
        source = task_dir / name
        source.write_text("{}\n" if source.suffix == ".json" else "native source\n", encoding="utf-8")
        source_files[name] = str(source)
    bulk_series = {
        "schema": "mlcc.md-bulk-thermal-source.v1",
        "frames": [
            {
                "step": 0,
                "physical_time_ps": 0.0,
                "temperature_K": 400.0,
                "pressure_bar": 0.0,
                "cell_angstrom": [[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]],
            },
            {
                "step": 20,
                "physical_time_ps": 0.002,
                "temperature_K": 401.0,
                "pressure_bar": 0.1,
                "cell_angstrom": [[5.01, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]],
            },
        ],
    }
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
        "scientific_status": _STATUS,
        "bulk_thermal_series": bulk_series,
        "source_files": source_files,
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return task, result_path, result


def test_bulk_thermal_result_completes_with_native_dynamic_cell_frames(tmp_path: Path) -> None:
    task, result_path, result = _task_with_result(tmp_path)

    paths, invalid, reason = source_evidence(result, result_path, engine="lammps")
    assert reason == "complete"
    assert invalid == []
    assert {path.name for path in paths} >= {"log.lammps", "dump.final", "trajectory.lammpstrj"}

    plan = inspect_task(task)

    assert plan["action"] == "completed"
    assert plan["scientific_status"] == _STATUS
    assert plan["scientific_qualification"] is False
    assert "bulk NPT thermal protocol" in plan["reason"]
    assert any(Path(path).name == "frozen.pth" for path in plan["source_artifacts"])


def test_bulk_thermal_result_rejects_missing_or_malformed_native_series(tmp_path: Path) -> None:
    task, result_path, result = _task_with_result(tmp_path)
    broken = copy.deepcopy(result)
    broken["bulk_thermal_series"] = {"schema": "mlcc.md-bulk-thermal-source.v1", "frames": []}
    result_path.write_text(json.dumps(broken, indent=2) + "\n", encoding="utf-8")

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"
    assert plan["scientific_status"] == _STATUS
    assert "bulk_thermal_series" in plan["reason"] or "complete evaluation identity" in plan["reason"]


def test_bulk_thermal_result_rejects_missing_static_or_potential_source(tmp_path: Path) -> None:
    task, result_path, result = _task_with_result(tmp_path)
    broken = copy.deepcopy(result)
    del broken["source_files"]["frozen.pth"]
    result_path.write_text(json.dumps(broken, indent=2) + "\n", encoding="utf-8")

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"
    assert plan["scientific_status"] == _STATUS
    assert "potential-files" in plan["reason"] or "native" in plan["reason"]
