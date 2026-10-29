# MLCC 0.60.1 candidate deployment boundary

This directory is the MLCC-owned integration delivery. It is not a copy of the
MatterAI host. Public control validation has passed; this document does not
claim that a scientific computation was submitted or that production science is
complete.

## Version state

| Layer | State | Meaning |
| --- | --- | --- |
| Bundle manifest | `0.60.1` | Candidate Bundle with 13 MCP tools and two required environment variables. |
| Published baseline | `0.60.0` | Catalog publication cancelled; `deployment.enabled=true` retained and historical pins unchanged. |
| Candidate label | `0.60.1-candidate` | Published and visible/hireable; public control validation passed with no compute submitted. |
| GitHub delivery baseline | `codex/cloud-delivery-20261029` / `5dbb0e4` | Source-distribution baseline; not the runtime integration branch. |
| Historical source | `0.57` | Retained for provenance; not the current candidate. |

The candidate must not be described as having completed scientific execution or
production qualification. The public control gates in
[`docs/public-chain-audit-20261029.md`](docs/public-chain-audit-20261029.md)
are closed. The existing `0.60.0` deployment and its pinned sessions are not
retargeted by this candidate. Because the catalog permits only one published
record for the same name, an old conversation must start a new conversation to
select `0.60.1`; do not claim that an old conversation continued on the new
revision.

## Repository boundary

- `mlcc-agent/`: MLCC Agent, eight top-level Skills, nested module methods,
  FEM, phase-field, RVE and SPICE modules, adapters and schemas.
- `configs/`: public templates only. SSH identity, host paths, environments,
  scheduler paths and credentials remain operator configuration.
- `scripts/`: source-side preparation helpers; no runtime binary or secret is
  distributed here.
- `SYSTEM_MANIFEST.json`: candidate state and sanitized evidence index.
- `docs/`: delivery, audit and operator-boundary documentation.

MatterAI host source, the workspace resolver, private Worker runtime, full v100
configuration, scientific data, runtime binaries and credentials are outside
this repository. Upstream reference trees remain read-only references.

## Current execution chain

```text
MatterAI host + workspace resolver (independent release)
        -> public control plane https://agent.mattok.cn
        -> candidate outbound Worker on v100 (systemd active; DB heartbeat online)
        -> MLCC MCP / CLI -> local Slurm control on v100
```

The candidate v100 route is a user-level Worker design using
`ssh.transport="local"`; it does not require localhost and does not create a
second cloud-to-LAN SSH hop. The approved `target_mlcc_v100` now exists, the
server pairing credentials are active, `zeus.service` is active, and the
v100-user `mlcc-worker.service` has started with an online database heartbeat.
Five repaired public calls completed. The same
`thread_a81202520ca34d75979c62e23f997575` / provider session
`01a187f1…` continued successfully across a Worker restart. The public control
round is therefore verified; this does not submit a scientific job.

The LF metadata fix was applied before publication. Under the immutable-store
rule, the same unpublished deployment ID advanced from revision 2 to revision 3;
revision 3 is the final published candidate revision. The old `0.60.0` catalog
publication was cancelled while its enabled deployment and historical pins were
retained.

## Control-only verification

The following facts are recorded from the 2026-10-29 v100 readiness run. They
are not a scientific run and did not call `sbatch`, `scontrol`, or a scheduler
query:

- User-level Node `22.23.2`, Codex `0.146.0`, Python `3.12.3` and MCP `2.3.0`
  were present. Worker healthcheck output was `1`.
- The existing scientific environment already contained `numpy`, `ase`,
  `scipy`, `phonopy`, `phonors`, `symfc`, `h5py` and `pymatgen`; it was not
  modified. MCP dependencies were read-only migrated from the verified Docker
  SDK; a PyPI install encountered an index timeout.
- The private Worker runtime changed one Node path from a fixed
  `/usr/local/bin/node` to `process.execPath`. Typecheck passed; 39 cases passed
  in the first run and the remaining case passed a targeted recheck after its
  hard-coded expectation was corrected. Other runtime
  adapters were unchanged.
- The candidate exposes 13 MCP tools, 8 top-level Skill routes, 7 nested
  module-method routes and 114 CLI catalog routes. The public catalog returned
  all 15 Skills; individual Skill filters passed in the v100 probe. Four
  generic operation-contract reads, four scale-contract reads, eight public
  `*-0601` tasks created and prepared, and the six historical result reads from
  the original rollout passed. All prepared task scheduler IDs were `null`; no
  Slurm or scientific computation was submitted.
- Seven Linux control tests passed, including the executor's rejection of a
  missing Slurm allocation without loading scientific code or writing a result.
- The approved target, active server pairing, active `zeus.service`, active
  `mlcc-worker.service` and online database heartbeat were observed after
  publication. The public control calls also continued successfully after the
  Worker restart.

## Public control result reads

The six historical `mlcc_read_result` calls completed without changing their
source task/result records:

| Result | Read status |
| --- | --- |
| DFT489 | `raw_charged_scf_unqualified` |
| MD45 | `executed_engineering_fixture` |
| FEM / phase-field / RVE / SPICE historical results | `not_checked` |

The initial continuum read used JSON-only copies and failed. Restoring the
original payload/schema/artifacts directories made all four reads succeed; the
original task/result records were unchanged and this did not reveal a source
portability bug.

The four generic scientific inputs remain `deferred_not_input_ready`. Real
`submit`, `query` and `collect` execution is deferred in this round, not an
undeveloped API; no new scheduler or scientific job was created.

## Source patches and software checks

The private runtime carries three small patches:

1. `runtime-node-path.patch`: resolve Node through `process.execPath`.
2. `codex-config-0146.patch`: remove the rejected native
   `model_supports_reasoning_summaries` override while retaining the catalog
   `supports_reasoning_summaries` capability.
3. `mlcc-artifact-boundary.patch`: at two entry points, skip
   `configs/site.v100.json` and `tasks/*/payload`, including a `project/`
   prefix, when classifying artifacts.

The initial public error was the old native
`model_supports_reasoning_summaries` override being rejected by Codex 0.146;
the second patch removes only that native setting and retains the catalog
`supports_reasoning_summaries` capability.

The targeted existing test for the Codex config passed; the two artifact-boundary
targeted tests passed; final Worker typecheck passed. The initial Node-path
suite remains accurately recorded as 39 passes plus one targeted corrected pass,
not a complete final 40-case rerun. Private report packages are outside GitHub:
`worker-runtime-final.tar.gz` and `mcp-sdk.tar.gz`; the runtime base was rebuilt
from six source/test files.

## MCP and Skill boundary

The candidate MCP surface is:

`mlcc_list_tasks`, `mlcc_describe_operations`, `mlcc_create_operation_task`,
`mlcc_read_result`, `mlcc_describe_scales`, `mlcc_create_scale_task`,
`mlcc_read_scale_result`, `mlcc_prepare_calculation`,
`mlcc_transfer_calculation`, `mlcc_submit_calculation`,
`mlcc_query_calculation`, `mlcc_cancel_calculation`, and
`mlcc_collect_calculation`.

The eight top-level Skills are modeling, DFT, MD, phase field, RVE, FEM,
SPICE and properties. The 8 + 7 route inventory and the 114 CLI entries passed
on the v100 and public control paths; this does not claim scientific execution.

## Historical four-scale acceptance

These are existing records, not submissions from this candidate:

| Module | Operation | Slurm job | Final state | Result read |
| --- | --- | ---: | --- | --- |
| FEM | `electrostatics_2d_quantities` | 702 | `COMPLETED`, `0:0` | `mlcc.task-result-view.v1`, passed |
| phase field | `vector_evolve_si` | 703 | `COMPLETED`, `0:0` | `mlcc.task-result-view.v1`, passed |
| RVE | `homogenize_electrostatics_2d` | 704 | `COMPLETED`, `0:0` | `mlcc.task-result-view.v1`, passed |
| SPICE | `ac_impedance` | 705 | `COMPLETED`, `0:0` | `mlcc.task-result-view.v1`, passed |

Their raw files remain local under
`versions/0.60.0/evidence/four-scale-workbench-20261028/`; they are not a
public deployment proof or material qualification.

## Release gates

- [x] Candidate source and Bundle manifest reviewed; 13-tool surface is
      synchronized.
- [x] v100 user-level runtime healthcheck and typecheck completed before the
      Worker daemon was started.
- [x] The public catalog returned all 15 Skills; individual Skill filters
      passed in the v100 probe. Four generic operation-contract reads, four
      scale-contract reads, eight public `*-0601` tasks created and prepared,
      and six `mlcc_read_result` calls passed; all prepared job IDs were null.
- [x] Seven Linux control tests passed, including the no-Slurm executor guard.
- [x] Obtain the required user confirmation and create `target_mlcc_v100`.
- [x] Activate the server pairing, keep the existing `0.60.0` deployment
      enabled with catalog publication cancelled, and retain historical pins.
- [x] Start the user-level v100 Worker, confirm `zeus.service` is active and
      confirm the database heartbeat.
- [x] Apply the LF metadata fix and publish candidate revision 3. The catalog
      now exposes `0.60.1` to ordinary users.
- [x] Complete five repaired public control calls, including the full 15-Skill
      catalog response, four generic operation-contract reads and continuation
      across the Worker restart on the same thread/provider session.
- [x] Verify the public control round with `public_second_turn_verified=true`.
- [ ] Submit/query/collect a real computation; this remains explicitly
      deferred in this round and no compute was submitted.
- [ ] Obtain separate authorization before any real end-to-end job; no job is
      submitted in this round.

The current status is **public control passed; no compute submitted**.
