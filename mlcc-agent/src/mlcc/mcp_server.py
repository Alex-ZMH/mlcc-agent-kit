"""MCP wrappers for the explicit MLCC Slurm task lifecycle."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any, Sequence

from mcp.server import MCPServer

from . import contracts
from .abacus_library import describe_abacus_resources
from .public_operations import create_operation_task, describe_operations
from .scale_tasks import create_scale_task, describe_scales, read_scale_result
from .site_runner import SiteRunner, runner_for_task
from .tasks import TaskRecord, load_task
from .workflow import inspect_task
from .result_views import task_summary


_WORKSPACE_URI = "zeus://workspace/current"
_SITE_URI = f"{_WORKSPACE_URI}/configs/site.v100.json"


def _task_path(workspace: Path, task_id: str) -> Path:
    """Return one task path below the configured workspace."""

    if not task_id or "/" in task_id or "\\" in task_id or task_id in {".", ".."}:
        raise ValueError("task_id must be one directory name")
    return workspace / "tasks" / task_id / "task.json"


def _load_runner_task(site_path: Path, workspace: Path, task_id: str) -> tuple[SiteRunner, TaskRecord]:
    runner, task = runner_for_task(site_path, _task_path(workspace, task_id))
    return runner, task


def _require_prepared(task: TaskRecord) -> None:
    prepared = task.data.get("prepared_script")
    if not prepared:
        raise ValueError("task has not been prepared")
    if not Path(prepared).is_file():
        raise FileNotFoundError(f"prepared script does not exist: {prepared}")


def _resolve_workspace(value: str | Path) -> Path:
    if str(value) == _WORKSPACE_URI:
        return Path.cwd().resolve()
    return Path(value).expanduser().resolve()


def _materialize_site_config(template_value: str, workspace: Path) -> Path:
    template_path = Path(template_value).expanduser().resolve()
    workspace_root_value = os.environ.get("MLCC_WORKSPACE_ROOT")
    if not workspace_root_value:
        raise ValueError("MLCC_WORKSPACE_ROOT is required with MLCC_SITE_CONFIG")
    workspace_root = Path(workspace_root_value).expanduser().resolve()
    try:
        relative_workspace = workspace.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("workspace must be below MLCC_WORKSPACE_ROOT") from exc

    template = contracts.read_json(template_path)
    site_workspace = template.get("workspace") if isinstance(template, dict) else None
    if not isinstance(site_workspace, dict):
        raise ValueError("MLCC_SITE_CONFIG must contain a workspace object")
    remote_root = site_workspace.get("remote_root")
    if not isinstance(remote_root, str) or not remote_root.startswith("/"):
        raise ValueError("MLCC_SITE_CONFIG workspace.remote_root must be an absolute POSIX path")
    relative_posix = PurePosixPath(*relative_workspace.parts).as_posix()
    site_workspace["local"] = str(workspace)
    site_workspace["remote_root"] = (
        f"{remote_root.rstrip('/')}/{relative_posix}" if relative_posix != "." else remote_root
    )

    target = workspace / "configs" / "site.v100.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contracts.dumps(template), encoding="utf-8")
    return target


def _resolve_site(site_path: str | Path, workspace: Path) -> Path:
    template = os.environ.get("MLCC_SITE_CONFIG")
    if template:
        return _materialize_site_config(template, workspace)
    if str(site_path) == _SITE_URI:
        return workspace / "configs" / "site.v100.json"
    return Path(site_path).expanduser().resolve()


def _stage_scale_documents(
    workspace: Path,
    input_data: dict[str, Any],
    request: dict[str, Any],
) -> tuple[Path, Path]:
    task_id = request.get("task_id")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", task_id):
        raise ValueError("request.task_id must be a single readable directory name")
    task_path = workspace / "tasks" / task_id
    if task_path.exists():
        raise FileExistsError(f"MCP task already exists: {task_id}")
    input_path = workspace / "inputs" / f"{task_id}.json"
    request_path = workspace / "requests" / f"{task_id}.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(contracts.dumps(input_data), encoding="utf-8")
    request_path.write_text(contracts.dumps(request), encoding="utf-8")
    return input_path, request_path


def build_server(site_path: str | Path, workspace: str | Path) -> MCPServer:
    """Build the stdio server for one private site and workspace."""

    root = _resolve_workspace(workspace)
    site = _resolve_site(site_path, root)
    server = MCPServer(
        name="mlcc-agent",
        title="MLCC Slurm runner",
        description="Explicit Slurm task lifecycle for the MLCC project.",
        version="0.60.2",
    )

    @server.tool(
        name="mlcc_list_tasks",
        title="List MLCC tasks",
        description="List task IDs and recorded execution status from the configured workspace.",
        structured_output=True,
    )
    def list_tasks() -> dict[str, Any]:
        tasks: list[dict[str, Any]] = []
        for task_file in sorted((root / "tasks").glob("*/task.json")):
            task = load_task(task_file)
            tasks.append(
                {
                    "task_id": task.task_id,
                    "status": task.data.get("status"),
                    "scheduler_job_id": task.scheduler_job_id,
                    **task_summary(task),
                    "next_action": inspect_task(task)["action"],
                }
            )
        return {"tasks": tasks}

    @server.tool(
        name="mlcc_describe_dft_resources",
        title="Describe installed ABACUS resources",
        description="Read the installed periodic-table resource catalog and selected-element PP/NAO metadata; availability is not scientific qualification.",
        structured_output=True,
    )
    def describe_dft_resources_tool(elements: list[str] | None = None) -> dict[str, Any]:
        return describe_abacus_resources(site, elements)

    @server.tool(
        name="mlcc_describe_operations",
        title="Describe MLCC operations",
        description="Describe all registered Skills and CLI operations without importing scientific runtimes.",
        structured_output=True,
    )
    def describe_operations_tool(
        skill_id: str | None = None,
        operation: str | None = None,
    ) -> dict[str, Any]:
        return describe_operations(skill_id, operation)

    @server.tool(
        name="mlcc_create_operation_task",
        title="Create MLCC operation task",
        description="Stage one allowlisted MLCC operation for a v100-local Slurm task without executing it.",
        structured_output=True,
    )
    def create_operation_task_tool(
        operation: str,
        arguments: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return create_operation_task(
            operation=operation,
            arguments=arguments,
            request=request,
            site_path=site,
            workspace=root,
        )

    @server.tool(
        name="mlcc_read_result",
        title="Read MLCC result",
        description="Read one saved MLCC result envelope without parsing or starting a calculation.",
        structured_output=True,
    )
    def read_result_tool(task_id: str) -> dict[str, Any]:
        from .task_service import read_result

        return read_result(_task_path(root, task_id))

    @server.tool(
        name="mlcc_describe_scales",
        title="Describe MLCC scales",
        description="Describe the registered four-scale catalog or one operation contract.",
        structured_output=True,
    )
    def describe_scales_tool(
        module_id: str | None = None,
        operation: str | None = None,
    ) -> dict[str, Any]:
        return describe_scales(module_id, operation)

    @server.tool(
        name="mlcc_create_scale_task",
        title="Create MLCC scale task",
        description="Validate and stage one FEM, phase-field, RVE, or SPICE task without submitting it.",
        structured_output=True,
    )
    def create_scale_task_tool(
        module_id: str,
        operation: str,
        input: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        input_path, request_path = _stage_scale_documents(root, input, request)
        return create_scale_task(
            module_id=module_id,
            operation=operation,
            input_path=input_path,
            site_path=site,
            request_path=request_path,
        )

    @server.tool(
        name="mlcc_read_scale_result",
        title="Read MLCC scale result",
        description="Read the saved result for one existing FEM, phase-field, RVE, or SPICE task.",
        structured_output=True,
    )
    def read_scale_result_tool(task_id: str) -> dict[str, Any]:
        return read_scale_result(_task_path(root, task_id))

    @server.tool(
        name="mlcc_prepare_calculation",
        title="Prepare MLCC calculation",
        description="Write the Slurm batch script for one local task.",
        structured_output=True,
    )
    def prepare_calculation(task_id: str) -> dict[str, Any]:
        runner, task = _load_runner_task(site, root, task_id)
        return runner.prepare(task)

    @server.tool(
        name="mlcc_transfer_calculation",
        title="Transfer MLCC calculation",
        description="Copy a prepared task and its explicit inputs to the configured site.",
        structured_output=True,
    )
    def transfer_calculation(task_id: str) -> dict[str, Any]:
        runner, task = _load_runner_task(site, root, task_id)
        _require_prepared(task)
        return runner.transfer(task)

    @server.tool(
        name="mlcc_submit_calculation",
        title="Submit MLCC calculation",
        description="Submit a prepared task with sbatch through the configured site runner.",
        structured_output=True,
    )
    def submit_calculation(task_id: str) -> dict[str, Any]:
        runner, task = _load_runner_task(site, root, task_id)
        _require_prepared(task)
        return runner.submit(task)

    @server.tool(
        name="mlcc_query_calculation",
        title="Query MLCC calculation",
        description="Query the native Slurm state and retain the raw scontrol response.",
        structured_output=True,
    )
    def query_calculation(task_id: str) -> dict[str, Any]:
        runner, task = _load_runner_task(site, root, task_id)
        return runner.query(task)

    @server.tool(
        name="mlcc_cancel_calculation",
        title="Cancel MLCC calculation",
        description="Request cancellation of one task through scancel.",
        structured_output=True,
    )
    def cancel_calculation(task_id: str) -> dict[str, Any]:
        runner, task = _load_runner_task(site, root, task_id)
        return runner.cancel(task)

    @server.tool(
        name="mlcc_collect_calculation",
        title="Collect MLCC calculation",
        description="Copy the explicitly selected task artifacts from the configured site.",
        structured_output=True,
    )
    def collect_calculation(task_id: str) -> dict[str, Any]:
        runner, task = _load_runner_task(site, root, task_id)
        return runner.collect(task)

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mlcc-mcp")
    parser.add_argument("--site", required=True)
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    build_server(args.site, args.workspace).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
