# Public deployment status — 2026-10-29

Read [the deployment boundary](../DEPLOY.md) before operating this candidate.
The former `0.60.0` catalog publication was cancelled while its enabled
deployment and historical pins remain unchanged. `0.60.1` is published and
visible/hireable in the catalog; its public control round passed without
submitting compute.

The intended public control plane is `https://agent.mattok.cn`. The v100 site
remains the existing Slurm installation and retains its engine environments.
The candidate route is a user-level outbound Worker on v100, not a localhost
service and not a second cloud-to-LAN SSH hop.

## Observed v100 readiness

The 2026-10-29 readiness run was deliberately control-only:

- Node `22.23.2`, Codex `0.146.0`, Python `3.12.3` and MCP `2.3.0` were
  installed in the v100 user directory. The Worker healthcheck output was
  `1`.
- The existing scientific environment had `numpy`, `ase`, `scipy`, `phonopy`,
  `phonors`, `symfc`, `h5py` and `pymatgen`; it was preserved unchanged.
  Dependencies were read-only migrated from the verified Docker SDK. A PyPI
  installation attempt encountered an index timeout.
- The private Worker runtime changed one Node path from
  `/usr/local/bin/node` to `process.execPath`; typecheck passed, 39 cases passed
  initially, and the remaining case passed a targeted recheck after correcting
  its hard-coded expectation. A complete final 40-case rerun was not performed.
  No other runtime adapter changed.
- The candidate MCP surface has 13 tools. Its catalog has 8 top-level Skills,
  7 nested module-method routes and 114 CLI routes. The public catalog returned
  all 15 Skills; individual Skill filters passed in the v100 probe. Four
  generic operation-contract reads, four scale-contract reads, eight public
  `*-0601` tasks created and prepared, and six historical `mlcc_read_result`
  calls completed. All prepared task job IDs were `null`; no Slurm or
  scientific job was submitted.
- Seven Linux control tests passed, including the executor no-Slurm guard.

The approved target and deployment are now active: server pairing credentials
are effective, `zeus.service` is active, the v100 user-level
`mlcc-worker.service` is started, and the database heartbeat is online. Five
repaired public calls completed, and the same thread/provider session continued
successfully across a Worker restart. No scientific computation was submitted.

## Publication and validation state

User confirmation has been received and `target_mlcc_v100` was created. The LF
metadata fix was applied before publication. Under the immutable-store rule,
the same unpublished deployment ID advanced from revision 2 to final revision 3.
The current state is:

| Item | State |
| --- | --- |
| New target created | yes: `target_mlcc_v100` |
| Server pairing credentials | effective |
| `zeus.service` | active |
| v100 Worker daemon | `mlcc-worker.service` started |
| Database heartbeat | online |
| `0.60.1` candidate published | yes; catalog visible/hireable |
| Candidate deployment revision | final revision `3` |
| Public control round | five repaired calls completed |
| Same-thread cross-Worker continuation | succeeded; `public_second_turn_verified=true` |
| Existing `0.60.0` deployment and durable session pins | enabled/unchanged; catalog publication cancelled |

The six historical result reads completed with statuses `DFT489=`
`raw_charged_scf_unqualified`, `MD45=` `executed_engineering_fixture` and the
four continuum results=`not_checked`. The four generic scientific inputs remain
`deferred_not_input_ready`; real `submit`, `query` and `collect` execution is
deferred this round, not undeveloped. Because only one same-name record may be
published, an old conversation must start a new conversation to select
`0.60.1`; do not claim that an old conversation continued on the new revision.

The initial continuum read used JSON-only copies and failed. Restoring the
original payload/schema/artifacts directories made all four reads succeed; the
original task/result records were unchanged and this did not reveal a source
portability bug.

## Private site configuration

The candidate Bundle declares two operator environment variables:

- `MLCC_SITE_CONFIG`: absolute path to the private v100 site template.
- `MLCC_WORKSPACE_ROOT`: the Worker's managed project-workspace root.

For a Worker running on v100, the private site uses `ssh.transport="local"`
to invoke local Slurm control. Keep VASP, ABACUS, LAMMPS, FEniCSX and ngspice
paths, PP/NAO/model libraries, credentials and scheduler details outside Git.
Do not overwrite the existing full v100 configuration with a four-scale-only
template. The Worker configuration must be supplied through the host's
allowlisted environment keys and must not be copied into this repository.

The candidate contains no runtime binary, private host configuration or secret.
The candidate carries three small source patches:

1. `runtime-node-path.patch` resolves Node through `process.execPath`.
2. `codex-config-0146.patch` removes the rejected native
   `model_supports_reasoning_summaries` override while retaining the catalog
   `supports_reasoning_summaries` capability.
3. `mlcc-artifact-boundary.patch` makes two entry points skip
   `configs/site.v100.json` and `tasks/*/payload`, including an optional
   `project/` prefix.

The targeted Codex config test passed, two artifact-boundary targeted tests
passed and final Worker typecheck passed. The initial Node-path suite remains
39 passes plus one targeted corrected pass, not a complete final 40-case rerun.
The initial public error was the old native
`model_supports_reasoning_summaries` override being rejected by Codex 0.146;
the config patch removes only that native setting and retains the catalog
`supports_reasoning_summaries` capability.

## Four-scale records and evidence

FEM 702, phase-field 703, RVE 704 and SPICE 705 are historical completed jobs
whose saved results were read during the control probe. They are not new
submissions from this candidate. The v100 all-Skill control evidence is kept in
`workspace/reports/public-mlcc-eight-skill-20261029/`; second-turn control
material is in `workspace/reports/public-mlcc-second-turn-20261029/`.

The public control round and cross-Worker continuation are verified. Fresh real
scientific `submit/query/collect` execution remains deferred with no new job;
the release status is **public control passed; no compute submitted**.
