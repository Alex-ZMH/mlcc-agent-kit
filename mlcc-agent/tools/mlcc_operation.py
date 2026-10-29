"""Execute one staged MLCC CLI operation inside an allocated Slurm task."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any


def _package_root() -> Path:
    script = Path(__file__).resolve()
    return script.parent.parent if script.parent.name == "tools" else script.parent


PACKAGE_ROOT = _package_root()
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from mlcc import contracts  # noqa: E402


def execute(request_path: str | Path, response_path: str | Path) -> dict[str, Any]:
    request_file = Path(request_path).resolve()
    response_file = Path(response_path).resolve()
    request = contracts.read_json(request_file)
    if request.get("schema") != "mlcc.operation-request.v1":
        raise ValueError("Unsupported operation request")
    task_id = request.get("task_id")
    operation = request.get("operation")
    argv = request.get("argv")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("operation request task_id is required")
    if not isinstance(operation, str) or not operation:
        raise ValueError("operation request operation is required")
    if not isinstance(argv, list) or not all(isinstance(value, str) and value for value in argv):
        raise ValueError("operation request argv must be a non-empty string array")
    project_root = request.get("project_root")
    if not isinstance(project_root, str) or not project_root:
        raise ValueError("operation request project_root is required")
    project_directory = Path(project_root).resolve()
    if not project_directory.is_dir():
        raise FileNotFoundError(f"operation project_root does not exist: {project_directory}")
    scheduler_job_id = os.environ.get("SLURM_JOB_ID")
    if not scheduler_job_id:
        raise ValueError("operation executor requires an explicit Slurm allocation")

    output_file = request_file.parent / "operation-output.json"
    stdout = io.StringIO()
    stderr = io.StringIO()
    result: dict[str, Any] = {
        "schema": "mlcc.operation-result.v1",
        "task_id": task_id,
        "operation": operation,
        "scheduler_job_id": scheduler_job_id,
        "status": "failed",
        "scientific_status": "not_checked",
        "output": None,
        "error": None,
    }
    raised: Exception | None = None
    try:
        os.chdir(project_directory)
        from mlcc.cli import main

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        text = stdout.getvalue()
        try:
            output: Any = json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            output = {"stdout": text}
        result["status"] = "succeeded" if code == 0 else "failed"
        result["output"] = output
        if code != 0:
            result["error"] = {"type": "CLI_EXIT", "message": f"mlcc exited with {code}"}
    except Exception as exc:
        raised = exc
        result["output"] = {"stdout": stdout.getvalue(), "stderr": stderr.getvalue()}
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    result["stderr"] = stderr.getvalue()
    sys.stderr.write(stderr.getvalue())
    output_file.write_text(stdout.getvalue(), encoding="utf-8")
    response_file.write_text(contracts.dumps(result), encoding="utf-8")
    if raised is not None:
        raise raised
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args(argv)
    result = execute(args.request, args.response)
    print(contracts.dumps({"task_id": result["task_id"], "status": result["status"]}), end="")
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
