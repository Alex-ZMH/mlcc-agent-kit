"""Exercise the MLCC MCP server over its real stdio JSON-RPC transport."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any


def _default_python(repo: Path) -> Path:
    return repo / "workspace" / ".venv" / "Scripts" / "python.exe"


def _read_response(process: subprocess.Popen[str], request_id: int) -> dict[str, Any]:
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout before the response")
        message = json.loads(line)
        if message.get("id") == request_id:
            return message


def _send(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    process.stdin.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="probe_mcp")
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--query-task", help="Query this recorded task through the real MCP and Slurm path.")
    parser.add_argument("--python", dest="python_executable", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    python_executable = args.python_executable or _default_python(repo)
    launcher = args.launcher or repo / "mlcc-agent" / "tools" / "mlcc_mcp.py"
    process = subprocess.Popen(
        [
            str(python_executable),
            str(launcher),
            "--site",
            str(args.site),
            "--workspace",
            str(args.workspace),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "mlcc-h0-probe", "version": "0.1.0"},
        },
    }
    _send(process, initialize)
    initialize_response = _read_response(process, 1)
    _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    _send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools_response = _read_response(process, 2)
    _send(
        process,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "mlcc_query_calculation" if args.query_task else "mlcc_list_tasks",
                "arguments": {"task_id": args.query_task} if args.query_task else {},
            },
        },
    )
    call_response = _read_response(process, 3)
    process.stdin.close()
    process.wait(timeout=10)
    stderr = process.stderr.read()
    if process.returncode != 0:
        raise RuntimeError(f"MCP server exited {process.returncode}: {stderr}")
    print(json.dumps({"initialize": initialize_response, "tools": tools_response, "call": call_response}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
