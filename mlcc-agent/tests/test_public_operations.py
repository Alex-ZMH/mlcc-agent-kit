from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from mlcc.public_operations import create_operation_task, describe_operations
from mlcc.site_runner import SiteConfig, SiteRunner
from mlcc.task_service import read_result
from mlcc.tasks import load_task, save_task


def _site(path: Path, workspace: Path) -> Path:
    value = {
        "ssh": {"alias": "v100", "transport": "local"},
        "workspace": {"local": str(workspace), "remote_root": "/v100/projects/mlcc"},
        "runner": {"selected": "slurm", "slurm": {"default_partition": "cpu"}},
        "python": {"remote_executable": "/opt/mlcc/bin/python"},
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_catalog_is_dynamic_and_does_not_import_scientific_runtimes() -> None:
    catalog = describe_operations()

    assert catalog["schema"] == "mlcc.operation-catalog.v1"
    assert len(catalog["skills"]) == 15
    assert len(catalog["operations"]) == 114
    assert {row["id"] for row in catalog["skills"]} >= {
        "model-mlcc-structures", "run-mlcc-dft", "run-mlcc-md", "compute-mlcc-properties",
    }
    assert {row["route"] for row in catalog["operations"]} >= {"slurm_control", "existing_mcp_lifecycle"}
    routes = {row["name"]: row for row in catalog["operations"]}
    assert routes["resume-plan"]["route"] == "slurm_control"
    assert routes["study-plan"]["route"] == "slurm_control"
    assert routes["read-result"]["mcp_tool"] == "mlcc_read_result"
    assert routes["create-task"]["mcp_tool"] == "mlcc_create_scale_task"
    nested = [skill for skill in catalog["skills"] if skill["scope"] == "nested"]
    assert all(skill["operations"] and skill["module_operation_routes"] for skill in nested)
    assert all("arguments" not in row for row in catalog["operations"])
    assert "operation=<name>" in catalog["operation_arguments_note"]
    assert "MCP tool's input schema" in catalog["arguments_contract"]
    detail = describe_operations(operation="create-abacus")
    assert detail["operations"][0]["arguments"]
    assert "numpy" not in sys.modules
    assert "ase" not in sys.modules


def test_read_result_only_reads_a_saved_control_envelope(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    site_path = _site(workspace / "site.json", workspace)
    data = create_operation_task(
        operation="import-model",
        arguments={"request": "inputs/model.json", "output": "models/imported"},
        request={
            "task_id": "saved-control",
            "resource_request": {"cpus_per_task": 1, "mem_mib": 512, "time": "00:05:00"},
        },
        site_path=site_path,
        workspace=workspace,
    )
    task_path = workspace / "tasks" / "saved-control" / "task.json"
    task = load_task(task_path)
    task.set(scheduler_job_id="unit-fixture-job", unit_fixture=True)
    save_task(task)
    result_path = task_path.parent / "operation-result.json"
    result_path.write_text(
        json.dumps({
            "schema": "mlcc.operation-result.v1",
            "task_id": "saved-control",
            "operation": "import-model",
            "scheduler_job_id": "unit-fixture-job",
            "unit_fixture": True,
            "scientific_status": "not_checked",
            "status": "failed",
            "output": None,
            "error": {"type": "fixture", "message": "saved evidence"},
        }),
        encoding="utf-8",
    )
    view = read_result(task_path)
    assert view["schema"] == "mlcc.task-result-view.v1"
    assert view["result"]["error"]["type"] == "fixture"
    assert view["result"]["unit_fixture"] is True
    assert data["scheduler_job_id"] is None
    saved_result = json.loads(result_path.read_text(encoding="utf-8"))
    saved_result["operation"] = "create-abacus"
    result_path.write_text(json.dumps(saved_result), encoding="utf-8")
    with pytest.raises(ValueError, match="operation differs"):
        read_result(task_path)


def test_executor_requires_slurm_without_loading_scientific_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor_path = Path(__file__).resolve().parents[1] / "tools" / "mlcc_operation.py"
    spec = importlib.util.spec_from_file_location("mlcc_operation_guard", executor_path)
    assert spec is not None and spec.loader is not None
    executor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(executor)

    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    request_path = tmp_path / "operation-request.json"
    response_path = tmp_path / "operation-result.json"
    request_path.write_text(
        json.dumps({
            "schema": "mlcc.operation-request.v1",
            "task_id": "executor-guard",
            "operation": "list-capabilities",
            "argv": ["list-capabilities"],
            "project_root": str(tmp_path),
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit Slurm allocation"):
        executor.execute(request_path, response_path)

    assert not response_path.exists()
    assert not (tmp_path / "operation-output.json").exists()
    assert "numpy" not in sys.modules
    assert "ase" not in sys.modules


def test_remaining_skill_operations_create_and_prepare_without_execution(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    site_path = _site(workspace / "site.json", workspace)
    cases = {
        "public-model": (
            "import-model",
            {"request": "inputs/model.json", "output": "models/imported"},
            {"cpus_per_task": 1, "mem_mib": 512, "time": "00:05:00"},
        ),
        "public-dft": (
            "create-abacus",
            {
                "study": "inputs/study.json",
                "model": "inputs/model",
                "method": "inputs/method.json",
                "request": "inputs/dft-request.json",
            },
            {"cpus_per_task": 1, "mem_mib": 1024, "time": 0},
        ),
        "public-md": (
            "create-lammps",
            {
                "study": "inputs/study.json",
                "model": "inputs/model",
                "potential": "inputs/potential.json",
                "protocol": "inputs/protocol.json",
                "request": "inputs/md-request.json",
            },
            {"cpus_per_task": 1, "mem_mib": 1024, "time": "00:05:00"},
        ),
        "public-properties": (
            "deliver-properties",
            {
                "study": "inputs/study.json",
                "continuum": "inputs/continuum.json",
                "output": "results/properties.json",
            },
            {"cpus_per_task": 1, "mem_mib": 512, "time": "00:05:00"},
        ),
    }

    for task_id, (operation, arguments, resources) in cases.items():
        data = create_operation_task(
            operation=operation,
            arguments=arguments,
            request={
                "schema": "mlcc.operation-task-request.v1",
                "task_id": task_id,
                "resource_request": resources,
            },
            site_path=site_path,
            workspace=workspace,
        )
        task_path = workspace / "tasks" / task_id / "task.json"
        assert data["scheduler_job_id"] is None
        assert data["status"] == "defined"
        assert not (task_path.parent / "operation-result.json").exists()
        assert not (task_path.parent / "operation-output.json").exists()
        assert (task_path.parent / "payload" / "execute.py").is_file()

        task = load_task(task_path)
        runner = SiteRunner(SiteConfig.from_file(site_path))
        prepared = runner.prepare(task)
        assert prepared["status"] == "prepared"
        assert prepared["scheduler_job_id"] is None
        script = (task_path.parent / "job.sbatch").read_text(encoding="utf-8")
        assert "/opt/mlcc/bin/python -I payload/execute.py" in script
        assert not (task_path.parent / "operation-result.json").exists()

    assert "numpy" not in sys.modules
    assert "ase" not in sys.modules
