"""MCP wrappers for the explicit MLCC Slurm task lifecycle."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

from mcp.server import MCPServer

from .site_runner import SiteRunner, runner_for_task
from .tasks import TaskRecord, load_task
from .workflow import inspect_task


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


def build_server(site_path: str | Path, workspace: str | Path) -> MCPServer:
    """Build the stdio server for one private site and workspace."""

    site = Path(site_path)
    root = Path(workspace)
    server = MCPServer(
        name="mlcc-agent",
        title="MLCC Slurm runner",
        description="Explicit Slurm task lifecycle for the MLCC project.",
        version="0.15.0",
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
                    "scientific_status": task.data.get("scientific_status"),
                    "next_action": inspect_task(task)["action"],
                }
            )
        return {"tasks": tasks}

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
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    build_server(args.site, args.workspace).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
