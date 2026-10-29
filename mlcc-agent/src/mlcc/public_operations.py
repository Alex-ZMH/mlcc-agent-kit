"""Bounded public operation catalog and Slurm control-task staging.

This module only validates arguments, copies the portable payload, and writes
an ordinary TaskRecord.  The operation executor is intentionally separate and
is invoked by the selected Slurm allocation, never by the public MCP process.
"""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Mapping

from . import contracts
from .capabilities import describe as describe_modules
from .cli import build_parser
from .tasks import TaskRecord, save_task, utc_now


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_POSIX_PATH = re.compile(r"/[A-Za-z0-9_./:-]+\Z")
_SAFE_RESOURCE_VALUE = re.compile(r"[A-Za-z0-9_:.%/@+,-]+\Z")

_LIFECYCLE_ACTIONS = frozenset({
    "prepare", "transfer", "submit", "status", "query", "cancel", "collect",
})
_MCP_OPERATION_TOOLS = {
    "list-capabilities": "mlcc_describe_operations",
    "list-scales": "mlcc_describe_scales",
    "describe-scale": "mlcc_describe_scales",
    "read-result": "mlcc_read_result",
    "parse-scale": "mlcc_read_scale_result",
    "create-task": "mlcc_create_scale_task",
    "create-scale": "mlcc_create_scale_task",
}
_INJECTED_PATH_DESTS = frozenset({"site", "site_path"})
_RESOURCE_KEYS = frozenset({
    "partition", "account", "ntasks", "nodes", "cpus_per_task", "mem_mib", "time",
    "gres", "gpus", "gpus_per_task", "constraint", "hint", "job_name", "stdout_log",
    "stderr_log",
})


def _frontmatter(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            if values:
                break
            continue
        match = re.match(r"^(name|description):\s*(.+?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"')
    return values


def _skill_catalog(
    action_names: set[str],
    module_operations: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    bundle_path = PACKAGE_ROOT / "bundle.json"
    bundle = contracts.read_json(bundle_path)
    top_names = list(bundle["agent"]["skills"])
    skill_root = PACKAGE_ROOT / "skills"
    records: list[dict[str, Any]] = []
    paths = sorted(PACKAGE_ROOT.rglob("SKILL.md"))
    top_paths = {path.parent.name: path for path in paths if path.parent.parent == skill_root}
    for name in top_names:
        path = top_paths.get(name)
        if path is None:
            raise ValueError(f"Bundle skill is missing: {name}")
        frontmatter = _frontmatter(path)
        records.append({
            "id": name,
            "scope": "top_level",
            "description": frontmatter.get("description", ""),
            "path": path.relative_to(PACKAGE_ROOT).as_posix(),
            "operations": sorted(
                action for action in action_names
                if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(action)}(?![A-Za-z0-9_-])",
                             path.read_text(encoding="utf-8"))
            ),
        })
    for path in paths:
        if path.parent.parent == skill_root:
            continue
        relative = path.relative_to(PACKAGE_ROOT).parts
        if len(relative) < 4 or relative[0] != "modules":
            continue
        frontmatter = _frontmatter(path)
        text = path.read_text(encoding="utf-8")
        operations = sorted(
            action for action in action_names
            if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(action)}(?![A-Za-z0-9_-])", text)
        )
        if not operations and module_operations.get(relative[1]):
            operations = ["create-task"]
        records.append({
            "id": frontmatter.get("name", path.parent.name),
            "scope": "nested",
            "module_id": relative[1],
            "description": frontmatter.get("description", ""),
            "path": path.relative_to(PACKAGE_ROOT).as_posix(),
            "operations": operations,
            "module_operation_routes": [
                {
                    "operation": operation,
                    "route": "existing_mcp",
                    "mcp_tool": "mlcc_create_scale_task",
                }
                for operation in sorted(module_operations.get(relative[1], ()))
            ],
        })
    return records


def _type_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "__name__", str(value))


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(item for item in parser._subparsers._group_actions if item.choices is not None)
    return dict(action.choices)


def _argument_metadata(action: argparse.Action) -> dict[str, Any]:
    row: dict[str, Any] = {
        "dest": action.dest,
        "option_strings": list(action.option_strings),
        "required": bool(action.required),
        "nargs": action.nargs,
        "type": _type_name(action.type),
    }
    if action.choices is not None:
        row["choices"] = list(action.choices)
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        row["boolean"] = True
    return row


def _operation_catalog() -> tuple[dict[str, Any], dict[str, argparse.ArgumentParser]]:
    parser = build_parser()
    subparsers = _subparsers(parser)
    names = set(subparsers)
    modules = describe_modules()["modules"]
    module_operations = {
        module["id"]: set(module.get("operations", {}))
        for module in modules
    }
    skills = _skill_catalog(names, module_operations)
    operations: list[dict[str, Any]] = []
    for name in sorted(subparsers):
        subparser = subparsers[name]
        if name in _LIFECYCLE_ACTIONS:
            route = "existing_mcp_lifecycle"
        elif name in _MCP_OPERATION_TOOLS:
            route = "existing_mcp"
        else:
            route = "slurm_control"
        skill_ids = [skill["id"] for skill in skills if name in skill["operations"]]
        row: dict[str, Any] = {
            "name": name,
            "route": route,
            "skill_ids": skill_ids,
            "arguments": [
                _argument_metadata(action)
                for action in subparser._actions
                if action.dest != "help"
            ],
        }
        if route == "existing_mcp_lifecycle":
            row["mcp_tool"] = {
                "prepare": "mlcc_prepare_calculation",
                "transfer": "mlcc_transfer_calculation",
                "submit": "mlcc_submit_calculation",
                "status": "mlcc_query_calculation",
                "query": "mlcc_query_calculation",
                "cancel": "mlcc_cancel_calculation",
                "collect": "mlcc_collect_calculation",
            }[name]
        elif route == "existing_mcp":
            row["mcp_tool"] = _MCP_OPERATION_TOOLS[name]
        else:
            row["mcp_tool"] = "mlcc_create_operation_task"
        operations.append(row)
    return {
        "schema": "mlcc.operation-catalog.v1",
        "skills": skills,
        "modules": modules,
        "operations": operations,
        "arguments_contract": "arguments describe CLI options; for existing_mcp routes use the named MCP tool's input schema",
        "lifecycle_note": "Use the existing lifecycle MCP tools for prepare/transfer/submit/status/query/cancel/collect.",
    }, subparsers


def describe_operations(skill_id: str | None = None, operation: str | None = None) -> dict[str, Any]:
    """Return the generated catalog without importing scientific modules."""

    catalog, _ = _operation_catalog()
    known_skills = {skill["id"] for skill in catalog["skills"]}
    if skill_id is not None and skill_id not in known_skills:
        raise ValueError(f"Unknown Skill: {skill_id}")
    known_operations = {item["name"] for item in catalog["operations"]}
    if operation is not None and operation not in known_operations:
        raise ValueError(f"Unknown operation: {operation}")
    if skill_id is not None:
        catalog["skills"] = [skill for skill in catalog["skills"] if skill["id"] == skill_id]
        catalog["operations"] = [
            item for item in catalog["operations"] if skill_id in item["skill_ids"]
        ]
    if operation is not None:
        catalog["operations"] = [item for item in catalog["operations"] if item["name"] == operation]
    else:
        catalog["modules"] = [
            {"id": item["id"], "operations": sorted(item.get("operations", {}))}
            for item in catalog["modules"]
        ]
        catalog["operations"] = [
            {key: value for key, value in item.items() if key != "arguments"}
            for item in catalog["operations"]
        ]
        catalog["operation_arguments_note"] = (
            "Call mlcc_describe_operations with operation=<name> to retrieve its argparse arguments."
        )
    return catalog


def _absolute_posix(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _POSIX_PATH.fullmatch(value) or "\\" in value:
        raise ValueError(f"{field} must be an absolute POSIX path")
    path = PurePosixPath(value)
    if path.as_posix() != value or ".." in path.parts or value == "/":
        raise ValueError(f"{field} must be a canonical non-root POSIX path")
    return value


def _site_settings(site_path: Path) -> tuple[dict[str, Any], str]:
    site = contracts.read_json(site_path)
    ssh = site.get("ssh")
    workspace = site.get("workspace")
    python = site.get("python")
    if not isinstance(ssh, dict) or ssh.get("transport") != "local":
        raise ValueError("operation control tasks require a v100-local site transport")
    if not isinstance(workspace, dict):
        raise ValueError("site.workspace is required")
    remote_root = _absolute_posix(workspace.get("remote_root"), "site.workspace.remote_root")
    if not isinstance(python, dict):
        raise ValueError("site.python.remote_executable is required")
    executable = _absolute_posix(python.get("remote_executable"), "site.python.remote_executable")
    return site, executable


def _validate_resource_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError("request.resource_request must be a non-empty object")
    unknown = set(value) - _RESOURCE_KEYS
    if unknown:
        raise ValueError(f"Unsupported resource fields: {sorted(unknown)}")
    for key in ("cpus_per_task", "mem_mib"):
        if type(value.get(key)) is not int or value[key] <= 0:
            raise ValueError(f"resource_request.{key} must be a positive integer")
    if "nodes" in value and (type(value["nodes"]) is not int or value["nodes"] != 1):
        raise ValueError("resource_request.nodes must be 1")
    if "ntasks" in value and (type(value["ntasks"]) is not int or value["ntasks"] != 1):
        raise ValueError("resource_request.ntasks must be 1")
    time = value.get("time")
    if not ((type(time) is int and time == 0) or
            (isinstance(time, str) and _SAFE_RESOURCE_VALUE.fullmatch(time))):
        raise ValueError("resource_request.time must be 0 or a simple Slurm time value")
    for key in ("partition", "account", "gres", "gpus", "gpus_per_task", "constraint",
                "hint", "job_name", "stdout_log", "stderr_log"):
        if key in value and value[key] not in (None, ""):
            if not isinstance(value[key], (str, int)) or not _SAFE_RESOURCE_VALUE.fullmatch(str(value[key])):
                raise ValueError(f"resource_request.{key} contains unsupported characters")
            if key in {"stdout_log", "stderr_log"}:
                path = str(value[key])
                if path.startswith(("/", "\\")) or ".." in PurePosixPath(path).parts:
                    raise ValueError(f"resource_request.{key} must stay below the task directory")
    return dict(value)


def _confined_argument(root: Path, value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")) or ":" in value:
        raise ValueError(f"arguments.{field} must be a relative workspace path")
    return str(contracts.confined(root, value, must_exist=False))


def _is_path_action(action: argparse.Action) -> bool:
    return action.type is Path or _type_name(action.type) == "Path"


def _values_for_action(action: argparse.Action, value: Any, root: Path) -> list[str] | None:
    if isinstance(action, argparse._StoreTrueAction):
        if type(value) is not bool:
            raise ValueError(f"arguments.{action.dest} must be boolean")
        return [action.option_strings[0]] if value else None
    if isinstance(action, argparse._StoreFalseAction):
        if type(value) is not bool:
            raise ValueError(f"arguments.{action.dest} must be boolean")
        return [action.option_strings[0]] if not value else None
    values = value if isinstance(value, list) and action.nargs in ("+", "*", 1) else [value]
    if action.nargs in ("+", "*") and not isinstance(value, list):
        raise ValueError(f"arguments.{action.dest} must be an array")
    if action.nargs not in (None, "?", "+", "*") and isinstance(action.nargs, int):
        if not isinstance(value, list) or len(value) != action.nargs:
            raise ValueError(f"arguments.{action.dest} must contain {action.nargs} values")
        values = value
    if action.nargs == "?" and isinstance(value, list):
        raise ValueError(f"arguments.{action.dest} must be a scalar")
    rendered: list[str] = []
    for item in values:
        rendered.append(_confined_argument(root, item, action.dest) if _is_path_action(action) else str(item))
    return [action.option_strings[0], *rendered]


def _build_argv(
    operation: str,
    arguments: Mapping[str, Any],
    parser: argparse.ArgumentParser,
    subparser: argparse.ArgumentParser,
    root: Path,
    site_path: Path,
) -> list[str]:
    if not isinstance(arguments, Mapping):
        raise ValueError("arguments must be an object keyed by argparse dest")
    actions = [action for action in subparser._actions if action.dest != "help"]
    known = {action.dest for action in actions}
    unknown = set(arguments) - known
    if unknown:
        raise ValueError(f"Unknown arguments for {operation}: {sorted(unknown)}")
    supplied_operator_paths = set(arguments) & _INJECTED_PATH_DESTS
    if supplied_operator_paths:
        raise ValueError("site arguments are operator-controlled")
    argv = [operation]
    for action in actions:
        if action.dest in _INJECTED_PATH_DESTS:
            value = str(site_path)
            rendered = [action.option_strings[0], value]
        elif action.dest not in arguments:
            if action.required:
                raise ValueError(f"Missing required argument: {action.dest}")
            continue
        else:
            rendered = _values_for_action(action, arguments[action.dest], root)
            if rendered is None:
                continue
        argv.extend(rendered)
    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        raise ValueError(f"Invalid arguments for {operation} (argparse exit {exc.code})") from exc
    return argv


def _copy_payload(task_dir: Path) -> Path:
    payload = task_dir / "payload"
    payload.mkdir()
    for name in ("src", "schemas", "modules", "scientific_core"):
        shutil.copytree(
            PACKAGE_ROOT / name,
            payload / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copy2(PACKAGE_ROOT / "tools" / "mlcc_operation.py", payload / "execute.py")
    return payload


def create_operation_task(
    *,
    operation: str,
    arguments: Mapping[str, Any],
    request: Mapping[str, Any],
    site_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    """Stage one allowlisted CLI operation for a future v100 Slurm run."""

    catalog, subparsers = _operation_catalog()
    operation_rows = {item["name"]: item for item in catalog["operations"]}
    if operation not in operation_rows:
        raise ValueError(f"Unknown operation: {operation}")
    row = operation_rows[operation]
    if row["route"] != "slurm_control":
        raise ValueError(f"Use the existing route for operation {operation}: {row['route']}")
    if not isinstance(request, Mapping):
        raise ValueError("request must be an object")
    allowed_request = {"schema", "task_id", "resource_request", "study_ref", "required_results"}
    unknown_request = set(request) - allowed_request
    if unknown_request:
        raise ValueError(f"Unsupported request fields: {sorted(unknown_request)}")
    if request.get("schema") not in (None, "mlcc.operation-task-request.v1"):
        raise ValueError("Unsupported operation task request schema")
    task_id = request.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise ValueError("request.task_id must be a single readable directory name")
    resources = _validate_resource_request(request.get("resource_request"))
    root = Path(workspace).expanduser().resolve()
    site = Path(site_path).expanduser().resolve()
    if not site.is_file():
        raise FileNotFoundError(f"site config does not exist: {site}")
    site_mapping, remote_python = _site_settings(site)
    task_dir = root / "tasks" / task_id
    if task_dir.exists():
        raise FileExistsError(f"operation task already exists: {task_id}")
    site_arg = site
    argv = _build_argv(operation, arguments, build_parser(), subparsers[operation], root, site_arg)
    task_dir.mkdir(parents=True)
    payload = _copy_payload(task_dir)
    request_path = task_dir / "operation-request.json"
    output_path = task_dir / "operation-output.json"
    result_path = task_dir / "operation-result.json"
    operation_request = {
        "schema": "mlcc.operation-request.v1",
        "task_id": task_id,
        "operation": operation,
        "skill_ids": row["skill_ids"],
        "argv": argv,
        "project_root": str(root),
    }
    request_path.write_text(contracts.dumps(operation_request), encoding="utf-8")
    workspace_record = site_mapping["workspace"]
    remote_root = workspace_record["remote_root"].rstrip("/")
    remote_workdir = str(PurePosixPath(remote_root) / "tasks" / task_id)
    command = [
        remote_python,
        "-I",
        "payload/execute.py",
        "--request",
        "operation-request.json",
        "--response",
        "operation-result.json",
    ]
    data: dict[str, Any] = {
        "schema": "mlcc.operation-task.v1",
        "task_id": task_id,
        "skill_ids": row["skill_ids"],
        "operation": operation,
        "execution_protocol": "mlcc.operation.v1",
        "engine": "operation_control",
        "stage": "operation_control",
        "runner": "slurm",
        "scheduler_job_id": None,
        "resource_request": resources,
        "study_ref": request.get("study_ref"),
        "required_results": request.get("required_results", []),
        "command": command,
        "local_workdir": str(task_dir),
        "remote_workdir": remote_workdir,
        "transfer_paths": ["payload", "operation-request.json"],
        "collect_paths": ["stdout.log", "stderr.log", "operation-output.json", "operation-result.json"],
        "result_file": str(result_path),
        "operation_request": str(request_path),
        "operation_output": str(output_path),
        "payload_root": str(payload),
        "status": "defined",
        "scientific_status": "not_calculated",
        "created_at": utc_now(),
    }
    task = TaskRecord(data, task_dir / "task.json")
    task.record_event("create", result="operation_inputs_staged_not_submitted")
    save_task(task)
    return task.data
