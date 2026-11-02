# MLCC Agent

0.60.3 revision 5 is published at https://agent.mattok.cn. The Worker is active
and its native readiness check returns 1. Ordinary-user verification returned
a concrete missing-task_id error, then created one synthetic validation task
and read it in the next turn: defined, scheduler_job_id=null. 0.60.2 is kept
for rollback. See [acceptance evidence](docs/evidence/task-create-repair-20261102.json).

One earlier acceptance turn was stopped after 17m16s of model reasoning with
zero tool calls; it is retained as cancelled, not counted as passed. Model
settings were not changed. The subsequent create/read turns both completed.

This release fixes the four-scale task-creation failure that previously showed
only a generic MCP error. `mlcc_create_scale_task` now advertises and validates
the request object at the tool boundary. `module_id`, `operation`, and
scientific `input` are separate tool arguments; `request` is a
`mlcc.scale-task-request.v1` object with the following required shape:

```json
{
  "schema": "mlcc.scale-task-request.v1",
  "task_id": "rve-control-20261102-01",
  "resource_request": {
    "nodes": 1,
    "ntasks": 1,
    "cpus_per_task": 1,
    "mem_mib": 2048,
    "time": "00:05:00",
    "partition": "cpu"
  }
}
```

`study_ref` is optional. Missing `task_id`, a wrong request schema, or an
unsupported module/operation is reported as a visible `ToolError` with the
validation reason. `mlcc_describe_scales` also reports the supported operations
when a module is selected without a valid operation. A valid create call only
stages `task.json` with `status=defined` and `scheduler_job_id=null`; it does
not prepare, submit, or run a calculation.

21 pure-software checks passed locally and the same 21 passed in the actual
public MCP2.3.0 interpreter. No material calculation was submitted. The host
allows only one enabled `mlcc-agent` version at a time, so 0.60.3 is
the single active version; 0.60.2/rev4 remains installed as
the rollback version, not a simultaneously enabled version. Existing
conversation pins are not automatically migrated, and their continued online
tool use after the switch is not promised. Users must start a new conversation
to obtain the repaired version. The existing task/job 842, its binding, task
record, scheduler state, Slurm processes, and scientific files are not changed.

ABACUS is the default production DFT engine. VASP is selected only when the
customer explicitly requests it. The resource library prefers
[AIS Square dataset 381](https://www.aissquare.com/datasets/detail?pageType=datasets&id=381):
its 83 PBE/NC pseudopotentials and 83 paired efficiency orbital files. Reliable
author sources supplement missing elements; a periodic-table record alone does
not establish resource availability or material qualification. The required
private registration currently reports 117 available UPF elements, 83 paired
NAO resources and Og missing. This is resource metadata registration only and
has submitted no material calculation.

The latest private catalog metadata correction records Bh as Z=107, `nc=10`,
`nv=8`, with 4f core and 5f valence; Tm remains Z=69, `nc=10`, `nv=4`, with
4f core. The metadata-only correction was applied in generator commit
`ef490a8`; it did not run a solver or add a test job. Resource boundaries and limitations are detailed in
[`docs/abacus-library-20261030.md`](docs/abacus-library-20261030.md).

The separate Slurm 776 resource check was explicitly exempted as a release
precondition because the v100 node was occupied. Job 776 was recorded as `PENDING` on 2026-10-30; it
was not rechecked, cancelled or bypassed by this repair, and is not a pass result.

The repository contains the MLCC bundle, eight top-level Skills and seven
nested method routes, 114 CLI operation routes, and 14 MCP tools. The added
`mlcc_describe_dft_resources` tool returns resource metadata and registered IDs
without exposing private resource paths. Existing project site configurations
refresh from the operator-owned template at MCP startup.

## Install and operate

```powershell
python -m pip install -e .\mlcc-agent
mlcc --help
```

Read [DEPLOY.md](DEPLOY.md) for the public Worker boundary and
[ABACUS resource deployment](docs/abacus-library-20261030.md) for the resource
catalog. Operator-provided `MLCC_SITE_CONFIG` and `MLCC_WORKSPACE_ROOT` bind the
private compute site and per-project workspaces. Scientific calculations and
postprocessing run through the existing v100 Slurm runner. The public service
has no dependency on the developer's localhost.

Credentials, licensed VASP data, private site configuration, resource binaries,
and scientific outputs remain outside this source repository. The MatterAI host
and Worker are independent releases; their retained patch sources are in
[scripts/worker](scripts/worker/README.md). Existing scientific environments are
preserved. The 0.60.2 content and its public two-turn evidence are historical
for this candidate. The 0.60.3 plan keeps the existing
`registered-public-v002` site configuration and the AIS381-first ABACUS resource
catalog unchanged; it needs no MatterAI host code change, credential update, or
new framework. The rollback target is 0.60.2/rev4.

Source folder: `versions/0.60.3-candidate` in the local MLCC workspace.
