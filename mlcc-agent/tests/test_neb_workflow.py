from __future__ import annotations

import json
from pathlib import Path

from mlcc.tasks import TaskRecord, load_task, save_task
from mlcc.workflow import inspect_task


def _write_neb_task(tmp_path: Path, *, with_result: bool = True, collect_status: str = "collected") -> tuple[TaskRecord, Path]:
    task_dir = tmp_path / "tasks" / "neb-001"
    task_dir.mkdir(parents=True)
    method_path = task_dir / "method.json"
    method_path.write_text("{}\n", encoding="utf-8")

    image_root = task_dir / "images"
    source_files: dict[str, object] = {
        "method.json": str(method_path),
        "atom-map.json": str(task_dir / "atom-map.json"),
        "in.lammps": str(task_dir / "in.lammps"),
        "log.lammps": str(task_dir / "log.lammps"),
        "image_atom_maps": [],
        "image_data": [],
        "image_logs": [],
        "image_dumps": [],
        "endpoint_dumps": [],
    }
    for name in ("atom-map.json", "in.lammps", "log.lammps"):
        (task_dir / name).write_text("{}\n" if name == "atom-map.json" else "native\n", encoding="utf-8")
    for image in range(2):
        image_dir = image_root / f"image-{image}"
        image_dir.mkdir(parents=True)
        files = {
            "image_atom_maps": image_dir / "atom-map.json",
            "image_data": image_dir / "model.data",
            "image_logs": task_dir / f"log.lammps.{image}",
            "image_dumps": image_dir / "final.lammpstrj",
        }
        for key, path in files.items():
            path.write_text("{}\n" if key == "image_atom_maps" else "native\n", encoding="utf-8")
            source_files[key].append(str(path))  # type: ignore[union-attr]
    for image in (0, 1):
        path = image_root / f"image-{image}" / "endpoint-final.lammpstrj"
        path.write_text("native\n", encoding="utf-8")
        source_files["endpoint_dumps"].append(str(path))  # type: ignore[union-attr]

    model = {
        "model_id": "host-model",
        "version": "v001",
        "path": str(tmp_path / "models" / "host-model" / "v001"),
    }
    final_model = {
        "model_id": "final-model",
        "version": "v001",
        "path": str(tmp_path / "models" / "final-model" / "v001"),
    }
    method = {
        "schema": "mlcc.lammps-method.v1",
        "engine": "lammps",
        "path": str(method_path),
        "method_set": "lammps-fixture-v001",
    }
    protocol = {
        "schema": "mlcc.lammps-neb-protocol.v1",
        "kind": "neb",
        "images": 2,
        "ranks_per_image": 1,
    }
    potential = {
        "potential_id": "fixture-potential",
        "version": "v001",
        "files": [],
    }
    result_path = task_dir / "result.json"
    task_data = {
        "schema": "mlcc.lammps-neb-task.v1",
        "task_id": "neb-001",
        "engine": "lammps",
        "engine_version": "LAMMPS fixture",
        "calculation": "neb",
        "status": "COMPLETED",
        "scheduler_job_id": "546",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "collect_status": collect_status,
        "study_id": "study-001",
        "case_id": "case-001",
        "model_id": model["model_id"],
        "model_version": model["version"],
        "model_path": model["path"],
        "model": model,
        "final_model": final_model,
        "final_model_path": final_model["path"],
        "method": method,
        "method_path": str(method_path),
        "method_set": method["method_set"],
        "protocol": protocol,
        "potential": potential,
        "result_file": str(result_path),
    }
    task = TaskRecord(task_data, task_dir / "task.json")
    save_task(task)

    if with_result:
        result = {
            "schema": "mlcc.lammps-neb-result.v1",
            "engine": "lammps",
            "engine_version": "LAMMPS fixture",
            "task_id": task.task_id,
            "scheduler_job_id": "546",
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "study_id": "study-001",
            "case_id": "case-001",
            "model_id": model["model_id"],
            "version": model["version"],
            "model_path": model["path"],
            "model": model,
            "final_model_id": final_model["model_id"],
            "final_version": final_model["version"],
            "final_model_path": final_model["path"],
            "final_model": final_model,
            "method": method,
            "method_path": str(method_path),
            "method_set": method["method_set"],
            "protocol": protocol,
            "potential": potential,
            "source_files": source_files,
            "scientific_status": "neb_native_unconverged",
            "regular_native_converged": False,
            "climbing_native_converged": False,
            "path_endpoint_converged": True,
            "native_converged": False,
            "stopping": {"phase_converged": {"endpoint": True, "regular": False, "climbing": False}},
            "production_qualification": False,
        }
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return task, result_path


def test_saved_nonconverged_neb_result_is_completed_without_scientific_upgrade(tmp_path: Path):
    task, _ = _write_neb_task(tmp_path)

    plan = inspect_task(task)

    assert plan["action"] == "completed"
    assert plan["scientific_status"] == "neb_native_unconverged"
    assert plan["native_converged"] is False
    assert plan["regular_native_converged"] is False
    assert plan["climbing_native_converged"] is False
    assert plan["path_endpoint_converged"] is True
    assert plan["phase_converged"] == {"endpoint": True, "regular": False, "climbing": False}
    assert any(Path(value).name == "final.lammpstrj" for value in plan["source_artifacts"])


def test_saved_neb_result_rejects_wrong_job_or_missing_native_source(tmp_path: Path):
    task, result_path = _write_neb_task(tmp_path)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["scheduler_job_id"] = "999"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    assert inspect_task(load_task(task.path))["action"] == "review_original_error"

    task, result_path = _write_neb_task(tmp_path / "missing")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["source_files"]["image_dumps"] = []
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    assert inspect_task(load_task(task.path))["action"] == "review_original_error"

    task, result_path = _write_neb_task(tmp_path / "missing-image")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["source_files"]["image_dumps"].pop()
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    assert inspect_task(load_task(task.path))["action"] == "review_original_error"


def test_neb_without_result_follows_collect_then_parse_state(tmp_path: Path):
    task, _ = _write_neb_task(tmp_path, with_result=False, collect_status="selected")
    assert inspect_task(task)["action"] == "collect"

    task.data["collect_status"] = "collected"
    save_task(task)
    assert inspect_task(load_task(task.path))["action"] == "parse"
