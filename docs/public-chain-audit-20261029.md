# MLCC public-chain audit — 2026-10-29

## Scope and conclusion

This audit covers the MLCC GitHub integration delivery only. The repository is
not the MatterAI host source, and it does not replace the independently released
host runtime, workspace resolver or outbound Worker.

The checked-in candidate Bundle is `0.60.1`. The GitHub delivery baseline is
branch `codex/cloud-delivery-20261029` at `5dbb0e4`; the runtime
`integration/four-scale-compute-20261028` branch is only a development reference.
The candidate manifest now contains ten MCP tools and the required
`MLCC_SITE_CONFIG` and `MLCC_WORKSPACE_ROOT` variables, but it is not deployed
and its isolated control-only test passed. The `0.60.0` baseline was
installed/published, while its public MCP path failed. Therefore the current
public-compute status is **not available**.

The v100 records below prove an earlier engineering lifecycle. They do not prove
that a public user can currently create or submit a new computation.

## Evidence verification

The query-final and read-result records in the local acceptance archive were
checked for task identity, operation, scheduler state, exit code and result-view
schema:

| Task | Module | Operation | Scheduler job | State | Exit | Result view | Scientific status |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `fem-20261029` | `fem` | `electrostatics_2d_quantities` | 702 | `COMPLETED` | `0:0` | `mlcc.task-result-view.v1` | `not_checked` |
| `p29` | `phase_field` | `vector_evolve_si` | 703 | `COMPLETED` | `0:0` | `mlcc.task-result-view.v1` | `not_checked` |
| `r29` | `rve` | `homogenize_electrostatics_2d` | 704 | `COMPLETED` | `0:0` | `mlcc.task-result-view.v1` | `not_checked` |
| `spice-20261029` | `spice` | `ac_impedance` | 705 | `COMPLETED` | `0:0` | `mlcc.task-result-view.v1` | `not_checked` |

These are historical acceptance artifacts, not new submissions by the 0.60.1
candidate. The raw archive is local under
`versions/0.60.0/evidence/four-scale-workbench-20261028/` and is deliberately
not part of this Git repository. It contains site-specific paths, runtime
details and host-side material. A future public release may publish only a
sanitized summary.

## Why the public MCP path is not accepted

The published `0.60.0` Bundle manifest allowed seven lifecycle tools only:

`mlcc_list_tasks`, `mlcc_prepare_calculation`, `mlcc_transfer_calculation`,
`mlcc_submit_calculation`, `mlcc_query_calculation`,
`mlcc_cancel_calculation`, and `mlcc_collect_calculation`.

The published MCP server also treated the `zeus://workspace/current` arguments
as ordinary paths and did not expose the four-scale create/read/describe tools.
The candidate source and Bundle manifest now contain the ten-tool surface and
two required environment variables, but the candidate is not deployed and the
isolated control-only test passed. It must not be described as a deployed public
fix yet. The cloud image's Python 3.11/MCP 1.28.1 cannot import `MCPServer`;
an isolated Python 3.12.13/MCP 2.3.0 image passed the protocol check. That image
has not replaced the production Worker.

The four-scale probe called describe/create/prepare/transfer/read for each
module. It copied files within an isolated container with networking disabled
and read copies of the original 702–705 result directories. New task job IDs
remained null. No submit, query, cancel or collect tool was invoked by that
probe. See [sanitized evidence](evidence/no-submit-audit-20261029.json).

## Version and ownership boundary

| Item | Current fact | Release implication |
| --- | --- | --- |
| `bundle.json` / `pyproject.toml` | `0.60.1` | Manifest and isolated controls verified; public deployment remains. |
| Published baseline | `0.60.0` | Installed/published baseline whose public MCP path failed. |
| GitHub delivery baseline | `codex/cloud-delivery-20261029` / `5dbb0e4` | Source-distribution baseline, not the runtime integration branch. |
| Candidate label | `0.60.1-candidate` | Not deployed and not cut to production. |
| Historical enabled source | `0.57` | Retained for provenance; not the candidate or public target. |
| MatterAI host | Independent private runtime | Must carry the workspace-resolver and replacement-thread MCP fixes separately. |
| Public Worker | Deployed | The missing piece is the outbound-worker route on v100. |
| v100 outbound-worker route | Missing | No public user path is available yet. |
| v100 | Existing SSH/Slurm engineering site | Its historical jobs do not establish public compute availability. |
| localhost | Not required by target contract | Current public-chain verification is not passed. |

This GitHub repository contains MLCC-owned agent integration: modules, Skills,
schemas, CLI and adapters. It intentionally excludes MatterAI host source,
upstream reference trees, credentials, SSH keys, private site configuration and
raw scientific/runtime output.

The Skill boundary is asymmetric. The new MCP surface covers only the four
scales below; modeling, DFT, MD and properties still require CLI creation or
consumption and have not completed a public conversational loop:

| Skill | Current invocation surface | Public closed loop |
| --- | --- | --- |
| modeling | CLI create/consume | not verified |
| DFT | CLI create/consume | not verified |
| MD | CLI create/consume | not verified |
| properties | CLI create/consume | not verified |
| phase field | candidate MCP create/read/describe | not deployed |
| RVE | candidate MCP create/read/describe | not deployed |
| FEM | candidate MCP create/read/describe | not deployed |
| SPICE | candidate MCP create/read/describe | not deployed |

## Complete deployment gap list

- [x] Review the candidate source changes; resolve the revision through Git.
- [x] Synchronize `mlcc-agent/bundle.json` with ten candidate MCP tools and the
      two required environment variables in the working tree.
- [x] Run the real MCP entry in an isolated fixture workspace, including
      initialize/list, four describe/create/prepare/transfer/read sequences.
      This is not a host Bundle-install or public-browser acceptance.
- [ ] Release the independent MatterAI host workspace-resolver fix and test
      replacement-thread MCP capability loading on the public host.
- [ ] Configure and verify the missing outbound-worker route on v100; the
      public Worker is already deployed.
- [ ] Configure Worker registration, private v100/site paths and existing
      engine environments outside Git. The local Worker route does not need
      a new cloud-to-LAN SSH identity.
- [ ] Obtain separate user authorization before any real end-to-end job. That
      acceptance is deferred; do not submit a job in this round or relabel jobs
      702–705 as a new public run.
- [ ] Publish the catalog candidate only after the isolated test, host fix and
      v100 route checks pass; the public production cut is deferred this round.
- [x] Include a sanitized evidence summary and retain raw evidence locally.
- [x] Mark older 0.57/0.56 operational documents as historical so they cannot
      be mistaken for the 0.60.1 target state.

Until every applicable gate is closed, release status remains **not publicly
available**.
