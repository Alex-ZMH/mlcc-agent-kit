from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

import mlcc.berry_response as response
from mlcc.modeling import read_model_artifacts


ROOT = Path(__file__).resolve().parents[2]
CZO_MODEL = Path(os.environ.get("MLCC_BERRY_MODEL", str(ROOT / "workspace" / "models" / "cazro3-pnma-pristine" / "v001")))
CZO_STUDY = Path(os.environ.get("MLCC_BERRY_STUDY", str(ROOT / "workspace" / "configs" / "cases" / "cazro3-firing-v003.json")))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def response_request(tmp_path: Path, *, time: int | str = 0) -> Path:
    request = {
        "schema": response.RESPONSE_REQUEST_SCHEMA,
        "response_id": "czo-berry-displacement-response-test",
        "parent_study_id": "cazro3_firing_validation_v003",
        "parent_model_id": "cazro3-pnma-pristine",
        "parent_model_version": "v001",
        "cell_constraint": "fixed_cell",
        "charge_state": 0,
        "points": [
            {
                "point_id": "minus-x",
                "child_model_id": "cazro3-berry-minus-x",
                "child_model_version": "v001",
                "child_study_id": "cazro3-berry-minus-x-study",
                "scf_task_id": "p5-czo-response-minus-x-scf",
                "displacements": [{"atom_id": 8, "delta_cartesian_A": [-0.01, 0.0, 0.0]}],
                "path_coordinate": -1.0,
                "gdirs": [1, 2, 3],
                "scf_resource_request": {
                    "nodes": 1,
                    "partition": "gpu",
                    "ntasks": 1,
                    "cpus_per_task": 1,
                    "gpus_per_task": "v100:1",
                    "mem_mib": 8192,
                    "time": time,
                },
            },
            {
                "point_id": "plus-x",
                "child_model_id": "cazro3-berry-plus-x",
                "child_model_version": "v001",
                "child_study_id": "cazro3-berry-plus-x-study",
                "scf_task_id": "p5-czo-response-plus-x-scf",
                "displacements": [{"atom_id": 8, "delta_cartesian_A": [0.01, 0.0, 0.0]}],
                "path_coordinate": 1.0,
                "gdirs": [1, 2, 3],
                "scf_resource_request": {
                    "nodes": 1,
                    "partition": "gpu",
                    "ntasks": 1,
                    "cpus_per_task": 1,
                    "gpus_per_task": "v100:1",
                    "mem_mib": 8192,
                    "time": time,
                },
            },
        ],
    }
    path = tmp_path / "response-request.json"
    write_json(path, request)
    return path


def test_response_materializes_sibling_child_models_and_explicit_scf_requests(tmp_path, monkeypatch):
    site_path = tmp_path / "site.json"
    site = {"workspace": {"local": str(tmp_path / "task-workspace")}}
    write_json(site_path, site)

    def fake_reference_task(*, study_path, model_path, method_path, site_path, request_path):
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        study = json.loads(Path(study_path).read_text(encoding="utf-8"))
        model = read_model_artifacts(model_path)
        task_dir = Path(json.loads(Path(site_path).read_text(encoding="utf-8"))["workspace"]["local"]) / "tasks" / request["task_id"]
        task_dir.mkdir(parents=True)
        task = {
            "task_id": request["task_id"],
            "study_id": study["study_id"],
            "model_id": model.model_id,
            "model_version": model.version,
            "model_path": str(Path(model_path).resolve()),
            "resource_request": request["resource_request"],
            "scheduler_state": "DEFINED",
            "status": "defined",
            "scheduler_job_id": None,
            "exit_code": None,
        }
        write_json(task_dir / "task.json", task)
        return task

    monkeypatch.setattr(response, "create_berry_reference_task", fake_reference_task)
    request_path = response_request(tmp_path)
    manifest = response.create_berry_displacement_response(
        CZO_STUDY,
        CZO_MODEL,
        tmp_path / "method.json",
        site_path,
        request_path,
        tmp_path / "response",
    )

    parent = read_model_artifacts(CZO_MODEL)
    assert manifest["status"] == "scf_inputs_written_not_submitted"
    assert manifest["parent_model"]["model_id"] == parent.model_id
    assert manifest["polarization_compatibility"]["collector_required"] is True
    assert len(manifest["points"]) == 2
    child_models = [read_model_artifacts(item["model_path"]) for item in manifest["points"]]
    assert [child.model_id for child in child_models] == ["cazro3-berry-minus-x", "cazro3-berry-plus-x"]
    for child in child_models:
        assert child.atom_ids == parent.atom_ids
        assert child.atoms.get_chemical_symbols() == parent.atoms.get_chemical_symbols()
        assert np.array_equal(child.atoms.cell.array, parent.atoms.cell.array)
        assert child.metadata["charge_state"] == 0
        assert child.metadata["spatial_mode"] == "fixed_cell_berry_displacement"
        assert child.metadata["production_qualified"] is False
    assert manifest["points"][0]["gdirs"] == [1, 2, 3]
    assert manifest["points"][0]["scf_task"]["resource_request"]["time"] == 0
    point_request = json.loads(Path(manifest["points"][0]["scf_request_path"]).read_text(encoding="utf-8"))
    assert point_request["point_id"] == "minus-x"
    assert point_request["child_study_id"] == "cazro3-berry-minus-x-study"
    assert point_request["gdirs"] == [1, 2, 3]
    assert point_request["resource_request"]["time"] == 0


def test_response_requires_unlimited_dft_resource_request(tmp_path, monkeypatch):
    site_path = tmp_path / "site.json"
    write_json(site_path, {"workspace": {"local": str(tmp_path / "task-workspace")}})
    monkeypatch.setattr(response, "create_berry_reference_task", lambda **kwargs: pytest.fail("creator must not be called"))
    request_path = response_request(tmp_path, time="00:10:00")
    with pytest.raises(ValueError, match=r"time must be explicitly 0"):
        response.create_berry_displacement_response(
            CZO_STUDY,
            CZO_MODEL,
            tmp_path / "method.json",
            site_path,
            request_path,
            tmp_path / "response",
        )


def test_response_requires_explicit_neutral_charge_state(tmp_path, monkeypatch):
    site_path = tmp_path / "site.json"
    write_json(site_path, {"workspace": {"local": str(tmp_path / "task-workspace")}})
    request_path = response_request(tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request.pop("charge_state")
    write_json(request_path, request)
    monkeypatch.setattr(response, "create_berry_reference_task", lambda **kwargs: pytest.fail("creator must not be called"))
    with pytest.raises(ValueError, match=r"explicit charge_state=0"):
        response.create_berry_displacement_response(
            CZO_STUDY,
            CZO_MODEL,
            tmp_path / "method.json",
            site_path,
            request_path,
            tmp_path / "response",
        )


def test_nscf_refuses_before_saved_native_scf_completion(tmp_path, monkeypatch):
    manifest_path = tmp_path / "response-manifest.json"
    scf_task_dir = tmp_path / "scf-task"
    scf_task_dir.mkdir()
    write_json(
        scf_task_dir / "task.json",
        {
            "task_id": "p5-czo-response-minus-x-scf",
            "study_id": "cazro3-berry-minus-x-study",
            "model_id": "cazro3-berry-minus-x",
            "model_version": "v001",
            "model_path": str(tmp_path / "model"),
            "study_file": str(tmp_path / "study.json"),
            "scheduler_state": "RUNNING",
            "status": "RUNNING",
            "scheduler_job_id": "999",
            "exit_code": None,
            "result_file": "result.json",
        },
    )
    write_json(
        manifest_path,
        {
            "schema": response.RESPONSE_MANIFEST_SCHEMA,
            "response_id": "czo-response-test",
            "method_path": str((tmp_path / "method.json").resolve()),
            "site_path": str((tmp_path / "site.json").resolve()),
            "parent_study": {"study_id": "cazro3_firing_validation_v003"},
            "parent_model": {"model_id": "cazro3-pnma-pristine", "version": "v001"},
            "points": [
                {
                    "point_id": "minus-x",
                    "path_coordinate": -1.0,
                    "gdirs": [1, 2, 3],
                    "child_study_id": "cazro3-berry-minus-x-study",
                    "child_model_id": "cazro3-berry-minus-x",
                    "child_model_version": "v001",
                    "scf_task_id": "p5-czo-response-minus-x-scf",
                    "scf_task_path": str(scf_task_dir),
                    "model_path": str(tmp_path / "model"),
                    "study_path": str(tmp_path / "study.json"),
                    "nscf_tasks": [],
                }
            ],
        },
    )
    nscf_request = tmp_path / "nscf-request.json"
    write_json(
        nscf_request,
        {
            "calculation": "nscf",
            "task_id": "p5-czo-response-minus-x-gdir1",
            "berry": {"role": "nscf", "gdir": 1},
            "resource_request": {"nodes": 1, "ntasks": 1, "time": 0},
        },
    )
    monkeypatch.setattr(response, "create_berry_nscf_task", lambda **kwargs: pytest.fail("NSCF creator must not be called"))
    with pytest.raises(ValueError, match=r"COMPLETED/0:0"):
        response.create_berry_response_nscf(
            manifest_path,
            "minus-x",
            tmp_path / "site.json",
            tmp_path / "method.json",
            nscf_request,
        )
