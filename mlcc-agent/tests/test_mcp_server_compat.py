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
    assert response, "MCP exited without a response; see mcp-stderr.log in the test workspace"
    return json.loads(response)


def _error_text(response: dict[str, object]) -> str:
    result = response["result"]
    assert isinstance(result, dict)
    content = result.get("content")
    if isinstance(content, list):
        text_items = [
            item["text"] for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if text_items:
            return "\n".join(text_items)
    return json.dumps(content if content is not None else result, ensure_ascii=False)


def _assert_tool_error(response: dict[str, object], *terms: str) -> None:
    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is True
    detail = _error_text(response)
    assert detail.strip()
    assert detail.strip() not in {
        "Error executing tool mlcc_create_scale_task",
        "Error executing tool mlcc_describe_scales",
        "Error executing tool mlcc_create_operation_task",
        "Error executing tool mlcc_describe_operations",
    }
    assert all(term.lower() in detail.lower() for term in terms), detail


def _resolve_schema(schema: dict[str, object], root: dict[str, object]) -> dict[str, object]:
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        definitions = root.get("$defs")
        assert isinstance(definitions, dict)
        resolved = definitions.get(reference.removeprefix("#/$defs/"))
        assert isinstance(resolved, dict)
        return resolved
    return schema


def _assert_no_staged_documents(workspace: Path, task_id: str) -> None:
    assert not (workspace / "tasks" / task_id / "task.json").exists()
    assert not (workspace / "inputs" / f"{task_id}.json").exists()
    assert not (workspace / "requests" / f"{task_id}.json").exists()


def test_mcp_stdio_initialize_tools_list_and_list_tasks() -> None:
    with TemporaryDirectory() as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        from mlcc.abacus_library import PERIODIC_TABLE

        catalog_path = Path(temporary) / "abacus-library.json"
        catalog_path.write_text(json.dumps({
            "schema": "mlcc.abacus-library.v1",
            "version": "test-v1",
            "elements": [{
                "symbol": symbol, "atomic_number": number, "status": "missing",
                "pseudopotentials": [], "orbitals": [], "issues": [],
            } for number, symbol in enumerate(PERIODIC_TABLE, 1)],
        }), encoding="utf-8")
        template_path = Path(temporary) / "site-template.json"
        template_path.write_text(
            json.dumps(
                {
                    "ssh": {"alias": "test-no-network", "transport": "local"},
                    "workspace": {"local": "ignored", "remote_root": "/remote/mlcc"},
                    "python": {"remote_executable": "/usr/bin/python3"},
                    "runner": {"selected": "slurm", "slurm": {}},
                    "abacus": {"resource_catalog": str(catalog_path)},
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

        stderr_log = (Path(temporary) / "mcp-stderr.log").open("w", encoding="utf-8")
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
            stderr=stderr_log,
            text=True,
            encoding="utf-8",
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
            assert initialized["result"]["serverInfo"]["version"] == "0.60.6"

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
                "mlcc_describe_dft_resources",
                "mlcc_describe_operations",
                "mlcc_create_operation_task",
                "mlcc_read_result",
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
            create_tool = next(
                tool for tool in listed["result"]["tools"]
                if tool["name"] == "mlcc_create_scale_task"
            )
            create_schema = create_tool["inputSchema"]
            assert isinstance(create_schema, dict)
            request_schema = _resolve_schema(
                create_schema["properties"]["request"], create_schema
            )
            assert isinstance(request_schema, dict)
            request_properties = request_schema["properties"]
            assert isinstance(request_properties, dict)
            assert {"schema", "task_id", "resource_request"} <= set(
                request_schema["required"]
            )
            schema_field = request_properties["schema"]
            assert isinstance(schema_field, dict)
            assert schema_field.get("const") == "mlcc.scale-task-request.v1" or schema_field.get(
                "enum"
            ) == ["mlcc.scale-task-request.v1"]
            assert "study_ref" in request_properties
            assert "platform_task_id" not in request_properties
            assert "mlcc.scale-execution-request.v1" not in json.dumps(request_schema)
            operation_tool = next(
                tool for tool in listed["result"]["tools"]
                if tool["name"] == "mlcc_create_operation_task"
            )
            operation_schema = operation_tool["inputSchema"]
            assert isinstance(operation_schema, dict)
            operation_request_schema = _resolve_schema(
                operation_schema["properties"]["request"], operation_schema
            )
            assert {"task_id", "resource_request"} <= set(operation_request_schema["required"])
            assert operation_request_schema["properties"]["schema"]["const"] == (
                "mlcc.operation-task-request.v1"
            )

            missing_operation_task_id = _request(process, {
                "jsonrpc": "2.0", "id": 13, "method": "tools/call",
                "params": {
                    "name": "mlcc_create_operation_task",
                    "arguments": {
                        "operation": "import-model",
                        "arguments": {
                            "request": "inputs/model.json",
                            "output": "models/imported",
                        },
                        "request": {
                            "schema": "mlcc.operation-task-request.v1",
                            "resource_request": {
                                "cpus_per_task": 1,
                                "mem_mib": 512,
                                "time": "00:05:00",
                            },
                        },
                    },
                },
            })
            _assert_tool_error(missing_operation_task_id, "request", "task_id")
            _assert_no_staged_documents(workspace, "missing-operation-task-id")

            invalid_operation_argument = _request(process, {
                "jsonrpc": "2.0", "id": 14, "method": "tools/call",
                "params": {
                    "name": "mlcc_create_operation_task",
                    "arguments": {
                        "operation": "electronic-dos",
                        "arguments": {
                            "task": "inputs/task.json",
                            "emin": "not-a-number",
                            "emax": "1",
                            "sigma": "0.1",
                            "points": "10",
                            "output": "results/dos.json",
                        },
                        "request": {
                            "schema": "mlcc.operation-task-request.v1",
                            "task_id": "invalid-operation-argument",
                            "resource_request": {
                                "cpus_per_task": 1,
                                "mem_mib": 512,
                                "time": "00:05:00",
                            },
                        },
                    },
                },
            })
            _assert_tool_error(invalid_operation_argument, "invalid float", "emin")
            _assert_no_staged_documents(workspace, "invalid-operation-argument")

            invalid_operation_schema = _request(process, {
                "jsonrpc": "2.0", "id": 15, "method": "tools/call",
                "params": {
                    "name": "mlcc_create_operation_task",
                    "arguments": {
                        "operation": "import-model",
                        "arguments": {
                            "request": "inputs/model.json",
                            "output": "models/imported",
                        },
                        "request": {
                            "schema": "mlcc.operation-execution-request.v1",
                            "task_id": "invalid-operation-schema",
                            "resource_request": {
                                "cpus_per_task": 1,
                                "mem_mib": 512,
                                "time": "00:05:00",
                            },
                        },
                    },
                },
            })
            _assert_tool_error(
                invalid_operation_schema, "schema", "mlcc.operation-task-request.v1"
            )
            _assert_no_staged_documents(workspace, "invalid-operation-schema")

            traversal_operation_argument = _request(process, {
                "jsonrpc": "2.0", "id": 16, "method": "tools/call",
                "params": {
                    "name": "mlcc_create_operation_task",
                    "arguments": {
                        "operation": "import-model",
                        "arguments": {
                            "request": "../inputs/model.json",
                            "output": "models/imported",
                        },
                        "request": {
                            "schema": "mlcc.operation-task-request.v1",
                            "task_id": "traversal-operation-argument",
                            "resource_request": {
                                "cpus_per_task": 1,
                                "mem_mib": 512,
                                "time": "00:05:00",
                            },
                        },
                    },
                },
            })
            _assert_tool_error(traversal_operation_argument, "request", "UNSAFE_PATH")
            _assert_no_staged_documents(workspace, "traversal-operation-argument")

            resources = _request(process, {
                "jsonrpc": "2.0", "id": 8, "method": "tools/call",
                "params": {"name": "mlcc_describe_dft_resources", "arguments": {"elements": ["Tm", "Og"]}},
            })
            resource_result = resources["result"]["structuredContent"]
            assert len(resource_result["elements"]) == 118
            assert [item["symbol"] for item in resource_result["selected"]] == ["Tm", "Og"]
            assert resource_result["selected"][1]["status"] == "missing"

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

            rve_description = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {
                        "name": "mlcc_describe_scales",
                        "arguments": {"module_id": "rve"},
                    },
                },
            )
            _assert_tool_error(rve_description, "Select one supported operation")

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
            _assert_tool_error(invalid_created, "input", "schema_version")
            _assert_no_staged_documents(workspace, "mcp-fem-create")

            missing_task_id_request = dict(request_payload)
            del missing_task_id_request["task_id"]
            missing_task_id = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "tools/call",
                    "params": {
                        "name": "mlcc_create_scale_task",
                        "arguments": {
                            "module_id": "fem",
                            "operation": "electrostatics_2d_quantities",
                            "input": input_payload,
                            "request": missing_task_id_request,
                        },
                    },
                },
            )
            _assert_tool_error(missing_task_id, "request", "task_id")
            assert not list((workspace / "tasks").glob("*/task.json"))
            assert not list((workspace / "inputs").glob("*.json"))
            assert not list((workspace / "requests").glob("*.json"))

            wrong_schema_request = dict(request_payload)
            wrong_schema_request["task_id"] = "mcp-wrong-schema"
            wrong_schema_request["schema"] = "mlcc.scale-execution-request.v1"
            wrong_schema = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {
                        "name": "mlcc_create_scale_task",
                        "arguments": {
                            "module_id": "fem",
                            "operation": "electrostatics_2d_quantities",
                            "input": input_payload,
                            "request": wrong_schema_request,
                        },
                    },
                },
            )
            _assert_tool_error(wrong_schema, "schema", "mlcc.scale-task-request.v1")
            _assert_no_staged_documents(workspace, "mcp-wrong-schema")

            extra_field_request = dict(request_payload)
            extra_field_request["task_id"] = "mcp-extra-field"
            extra_field_request["platform_task_id"] = "unexpected"
            extra_field = _request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "tools/call",
                    "params": {
                        "name": "mlcc_create_scale_task",
                        "arguments": {
                            "module_id": "fem",
                            "operation": "electrostatics_2d_quantities",
                            "input": input_payload,
                            "request": extra_field_request,
                        },
                    },
                },
            )
            _assert_tool_error(extra_field, "request", "platform_task_id")
            _assert_no_staged_documents(workspace, "mcp-extra-field")

            operation_created = _request(process, {
                "jsonrpc": "2.0", "id": 17, "method": "tools/call",
                "params": {
                    "name": "mlcc_create_operation_task",
                    "arguments": {
                        "operation": "import-model",
                        "arguments": {
                            "request": "inputs/model.json",
                            "output": "models/imported",
                        },
                        "request": {
                            "schema": "mlcc.operation-task-request.v1",
                            "task_id": "mcp-operation-create",
                            "resource_request": {
                                "cpus_per_task": 1,
                                "mem_mib": 512,
                                "time": "00:05:00",
                            },
                        },
                    },
                },
            })
            assert operation_created["result"]["isError"] is not True
            operation_data = operation_created["result"]["structuredContent"]
            assert operation_data["task_id"] == "mcp-operation-create"
            assert operation_data["status"] == "defined"
            assert operation_data["scheduler_job_id"] is None
            assert not (
                workspace / "tasks" / "mcp-operation-create" / "operation-result.json"
            ).exists()

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
            stderr_log.close()


def test_operator_template_refreshes_existing_project_site(tmp_path, monkeypatch):
    from mlcc.mcp_server import _materialize_site_config

    workspace = tmp_path / "project" / "thread"
    (workspace / "configs").mkdir(parents=True)
    target = workspace / "configs" / "site.v100.json"
    target.write_text(json.dumps({"abacus": {"pseudopotential_files": {"O-old": "/old/O.upf"}}}))
    template = tmp_path / "operator-site.json"
    template.write_text(json.dumps({
        "workspace": {"local": "ignored", "remote_root": "/remote/mlcc"},
        "abacus": {"resource_catalog": "/private/library-v2.json"},
    }))
    monkeypatch.setenv("MLCC_WORKSPACE_ROOT", str(tmp_path))

    assert _materialize_site_config(str(template), workspace) == target
    updated = json.loads(target.read_text())
    assert updated["abacus"]["resource_catalog"] == "/private/library-v2.json"
    assert updated["workspace"]["local"] == str(workspace)
    assert updated["workspace"]["remote_root"] == "/remote/mlcc/project/thread"
