# H0 MCP runner

`mlcc-agent/src/mlcc/mcp_server.py` is a thin MCP stdio adapter over the
existing Slurm runner. It receives the private site JSON and workspace as
required command-line arguments; it does not read an environment override and
does not expose an arbitrary shell command.

The portable launcher is `mlcc-agent/tools/mlcc_mcp.py`. It adds the installed
Bundle's sibling `src` directory to `sys.path` and starts the server with the
configured Python interpreter. The project MCP registration supplies
`--site` and `--workspace`; host paths remain in the private workspace/site
configuration rather than in the Bundle source.

The server exposes these fixed tools:

- `mlcc_list_tasks()` lists task IDs, recorded status, and native scheduler ID
  without changing task records.
- `mlcc_prepare_calculation(task_id)` writes the local Slurm script.
- `mlcc_transfer_calculation(task_id)` copies the prepared script and explicit
  input paths with `scp`.
- `mlcc_submit_calculation(task_id)` submits only a locally prepared task with
  `sbatch --parsable`.
- `mlcc_query_calculation(task_id)` queries `scontrol` and saves its raw
  response and parsed fields.
- `mlcc_cancel_calculation(task_id)` sends `scancel` for the recorded native
  job ID.
- `mlcc_collect_calculation(task_id)` copies only the task's explicit result
  paths.

The runner keeps native IDs, raw command output, exit status, scheduler state,
resource fields, and failures in each task JSON. It does not retry, requeue,
fallback to another engine/scheduler, or start numerical programs directly
over SSH. The list tool is the read-only stdio probe call; lifecycle tools
retain the runner's normal task-record side effects.

## Local stdio probe

After the Bundle source and the local environment are available, run:

```text
workspace/.venv/Scripts/python.exe scripts/h0/probe_mcp.py \
  --site workspace/configs/site.v100.json \
  --workspace workspace
```

The probe performs a real `initialize`, `notifications/initialized`,
`tools/list`, and `tools/call` for `mlcc_list_tasks`, then prints all three
responses. It starts no Slurm job and does not call SSH/scp.

The source launcher above is the default. To exercise the launcher copied into
an installed Bundle, pass it explicitly while keeping the same private site
and workspace arguments:

```text
workspace/.venv/Scripts/python.exe scripts/h0/probe_mcp.py \
  --launcher workspace/.zeus/bundles/mlcc-agent/0.1.0/tools/mlcc_mcp.py \
  --site workspace/configs/site.v100.json \
  --workspace workspace
```

The probe defaults to `workspace/.venv/Scripts/python.exe`; `--python` is an
explicit interpreter override. There is no system-Python fallback.

## Collect command investigation

The current runner's `collect` implementation intentionally issues one
`scp -r` command per `collect_paths` item and records one event per copied
artifact. This is needed because a collect item may map a remote name to a
different local path, including a nested local path. A single multi-source scp
would only be equivalent when every item uses the destination directory and
remote basenames; it would also collapse per-artifact raw stdout/stderr and
failure status. The H0 records already contain only a few explicit artifacts,
so batching is not worthwhile under the current contract. No runner change
was made from this investigation.
