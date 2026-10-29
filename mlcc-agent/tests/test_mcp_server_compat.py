"""Protocol smoke test for the installed MLCC MCP entry point."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest


pytest.importorskip("mcp")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = PROJECT_ROOT / "tools" / "mlcc_mcp.py"


def _request(process: subprocess.Popen[str], message: dict[str, object]) -> dict[str, object]:
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    response = process.stdout.readline()
    assert response, process.stderr.read()
    return json.loads(response)


def test_mcp_stdio_initialize_tools_list_and_list_tasks() -> None:
    with TemporaryDirectory() as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        template_path = Path(temporary) / "site-template.json"
        template_path.write_text(
            json.dumps(
                {
                    "ssh": {"alias": "test-no-network"},
                    "workspace": {"local": "ignored", "remote_root": "/remote/mlcc"},
                    "runner": {"selected": "slurm", "slurm": {}},
                    "scales": {
                        "runtime_python": "/usr/bin/python3",
                        "modules": {
                            "fem": {
                                "adapter_python": "/usr/bin/python3",
                                "deployment": {
                                    "schema_version": "fea.deployment.native.v1",
                                    "transport": "native_linux",
                                    "python": "/usr/bin/python3",
                                    "timeout_seconds": 90,
                                    "threads": 1,
                                    "max_cells": 50000,
                                },
                            }
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        input_payload = json.loads(
            (PROJECT_ROOT / "modules" / "fem" / "examples" / "quantities-mm.json").read_text(
                encoding="utf-8"
            )
        )
        request_payload = {
            "schema": "mlcc.scale-task-request.v1",
            "task_id": "mcp-fem-create",
            "resource_request": {
                "nodes": 1,
                "ntasks": 1,
                "cpus_per_task": 1,
                "mem_mib": 512,
                "time": "00:05:00",
            },
        }
        environment = os.environ.copy()
        environment["MLCC_SITE_CONFIG"] = str(template_path)
        environment["MLCC_WORKSPACE_ROOT"] = temporary

        process = subprocess.Popen(
            [
                sys.executable,
                str(ENTRY_POINT),
                "--site",
                str(Path(temporary) / "untrusted-site.json"),
                "--workspace",
                "zeus://workspace/current",
            ],
            cwd=workspace,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            initialized = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "mlcc-compat-test", "version": "1"},
                    },
                },
            )
            assert initialized["result"]["serverInfo"]["name"] == "mlcc-agent"

            process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    }
                )
                + "\n"
            )
            process.stdin.flush()

            listed = _request(
                process,
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            tool_names = {tool["name"] for tool in listed["result"]["tools"]}
            assert tool_names == {
                "mlcc_list_tasks",
                "mlcc_describe_scales",
                "mlcc_create_scale_task",
                "mlcc_read_scale_result",
                "mlcc_prepare_calculation",
                "mlcc_transfer_calculation",
                "mlcc_submit_calculation",
                "mlcc_query_calculation",
                "mlcc_cancel_calculation",
                "mlcc_collect_calculation",
            }

            task_list = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "mlcc_list_tasks", "arguments": {}},
                },
            )
            assert task_list["result"]["isError"] is not True
            assert task_list["result"]["structuredContent"]["tasks"] == []

            description = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "mlcc_describe_scales",
                        "arguments": {
                            "module_id": "fem",
                            "operation": "electrostatics_2d_quantities",
                        },
                    },
                },
            )
            assert description["result"]["structuredContent"]["module_id"] == "fem"

            invalid_created = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "mlcc_create_scale_task",
                        "arguments": {
                            "module_id": "fem",
                            "operation": "electrostatics_2d_quantities",
                            "input": {},
                            "request": request_payload,
                        },
                    },
                },
            )
            assert invalid_created["result"]["isError"] is True

            created = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {
                        "name": "mlcc_create_scale_task",
                        "arguments": {
                            "module_id": "fem",
                            "operation": "electrostatics_2d_quantities",
                            "input": input_payload,
                            "request": request_payload,
                        },
                    },
                },
            )
            assert created["result"]["isError"] is not True
            assert created["result"]["structuredContent"]["task_id"] == "mcp-fem-create"
            assert created["result"]["structuredContent"]["scheduler_job_id"] is None
            assert (workspace / "configs" / "site.v100.json").is_file()
            generated_site = json.loads(
                (workspace / "configs" / "site.v100.json").read_text(encoding="utf-8")
            )
            assert generated_site["workspace"]["local"] == str(workspace.resolve())
            assert generated_site["workspace"]["remote_root"] == "/remote/mlcc/workspace"
            assert (workspace / "tasks" / "mcp-fem-create" / "task.json").is_file()

            read_result = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {
                        "name": "mlcc_read_scale_result",
                        "arguments": {"task_id": "mcp-fem-create"},
                    },
                },
            )
            assert read_result["result"]["isError"] is True
        finally:
            process.terminate()
            process.wait(timeout=5)
