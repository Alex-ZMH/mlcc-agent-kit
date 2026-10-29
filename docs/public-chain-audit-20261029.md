# MLCC public-chain audit — 2026-10-29

## Scope and conclusion

This audit covers the MLCC GitHub integration delivery and its control-only
v100 readiness evidence. The repository is not the MatterAI host source and
does not replace the independently released host runtime, workspace resolver
or outbound Worker.

The `0.60.1` candidate Bundle contains 13 MCP tools. The public catalog returned
all 15 Skills; individual Skill filters passed in the v100 probe. Four generic
operation-contract reads, four scale-contract reads, eight public `*-0601` tasks
created and prepared, and six historical `mlcc_read_result` calls completed.
User approval is complete:
`target_mlcc_v100` was created, the server pairing is active, `zeus.service` is
active, the v100 `mlcc-worker.service` is started with an online database
heartbeat, and the candidate is published. The LF metadata fix produced final
deployment revision 3 from the same unpublished deployment ID's revision 2.
Five repaired public calls completed, and the same thread/provider session
continued successfully across a Worker restart. Current status is **public
control passed; no compute submitted**. This is not a claim of scientific
execution or production qualification.

## Control-only evidence

The 2026-10-29 v100 check used the user-level runtime and preserved the
existing scientific environment:

| Check | Result |
| --- | --- |
| Node / Codex | `22.23.2` / `0.146.0` |
| Python / MCP | `3.12.3` / `2.3.0` |
| Worker healthcheck | output `1` |
| Scientific environment | `numpy`, `ase`, `scipy`, `phonopy`, `phonors`, `symfc`, `h5py`, `pymatgen` present; unchanged |
| Worker runtime | one Node path changed to `process.execPath`; typecheck passed |
| Worker cases | 39 initial passes + one targeted pass after correcting the Node-path expectation; no complete final 40-case rerun; other runtimes unchanged |
| Candidate MCP | 13 tools |
| Skill routes | 8 top-level + 7 nested = 15; all v100 control routes passed |
| CLI catalog | 114 routes |
| Task controls | 8 create/prepare checks passed |
| Historical reads | six `mlcc_read_result` calls completed: DFT489 `raw_charged_scf_unqualified`, MD45 `executed_engineering_fixture`, four continuum results `not_checked` |
| New scheduler IDs | all `null` |
| Slurm/scientific submission | none |
| Linux control tests | 7 passed, including the no-Slurm executor guard |
| Public control calls | 5 repaired calls completed; same thread/provider session survived Worker restart |
| Deployment target | `target_mlcc_v100` created; server pairing active |
| Services | `zeus.service` active; `mlcc-worker.service` started; DB heartbeat online |
| Candidate publication | `0.60.1` visible/hireable; final deployment revision `3` |
| Public model validation | Control round completed; no real scientific execution |

MCP dependencies were read-only migrated from the verified Docker SDK. A PyPI
installation attempt encountered an index timeout. No scientific environment
was changed. The evidence files are retained locally under
`workspace/reports/public-mlcc-eight-skill-20261029/` and
`workspace/reports/public-mlcc-second-turn-20261029/`; private runtime files,
credentials and raw host configuration are not copied into GitHub.

## Historical result records

The following records were read without submitting a new job:

| Task | Module | Operation | Scheduler job | State | Exit | Result view | Scientific status |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `fem-20261029` | `fem` | `electrostatics_2d_quantities` | 702 | `COMPLETED` | `0:0` | `mlcc.task-result-view.v1` | `not_checked` |
| `p29` | `phase_field` | `vector_evolve_si` | 703 | `COMPLETED` | `0:0` | `mlcc.task-result-view.v1` | `not_checked` |
| `r29` | `rve` | `homogenize_electrostatics_2d` | 704 | `COMPLETED` | `0:0` | `mlcc.task-result-view.v1` | `not_checked` |
| `spice-20261029` | `spice` | `ac_impedance` | 705 | `COMPLETED` | `0:0` | `mlcc.task-result-view.v1` | `not_checked` |

These are engineering records, not public acceptance or material qualification.

The initial continuum read used JSON-only copies and failed. Restoring the
original payload/schema/artifacts directories made all four reads succeed; the
original task/result records were unchanged and this did not reveal a source
portability bug.

## Why the public chain is still open

The former `0.60.0` catalog publication was cancelled while its deployment
remains enabled and historical pins remain unchanged. The candidate's 13-tool
surface and active v100 route have now been published, and the public control
round completed across the Worker restart. Real `submit`, `query` and `collect`
execution was not performed in this round; it is deferred, not undeveloped.

The v100 route is designed as an outbound user-level Worker. A private site
configuration can use `ssh.transport="local"` to control Slurm locally on v100;
this is not a localhost requirement and does not start a computation by itself.
The existing full v100 engine environments remain the source of truth.

## Version and ownership boundary

| Item | Current fact | Release implication |
| --- | --- | --- |
| Candidate Bundle | `0.60.1`, 13 MCP tools | Published; multi-turn validation incomplete |
| Candidate status | `public_control_passed_no_compute` | Published; control validation passed with no compute |
| Published baseline | `0.60.0` | Catalog unpublished; deployment enabled; historical pins unchanged |
| GitHub delivery baseline | `codex/cloud-delivery-20261029` / `5dbb0e4` | Source-distribution baseline |
| MatterAI host | Independent private runtime | Workspace-resolver release remains separate |
| Public Worker | Candidate `0.60.1` deployed | Five public control calls completed |
| v100 outbound route | Target created; Worker started; heartbeat online | Cross-Worker continuation passed |
| localhost | Not required by target contract | Public control accepted; compute deferred |

The repository intentionally excludes MatterAI host source, upstream reference
trees, credentials, SSH keys, private site configuration, runtime binaries and
raw scientific/runtime output. The existing `0.60.0` target and durable
session pins are not retargeted.

## Skill boundary

The candidate catalog binds the same eight top-level Skills: modeling, DFT, MD,
phase field, RVE, FEM, SPICE and properties. It also exposes seven nested
module-method routes, for 15 Skill routes total, and 114 CLI catalog entries.
All 15 passed on the v100 and public control paths. This does not qualify a
scientific computation or material result.

| Skill group | Control-path status | Public closed loop |
| --- | --- | --- |
| modeling, DFT, MD, properties | public/v100 control calls passed | scientific execution deferred |
| phase field, RVE, FEM, SPICE | public/v100 control calls passed | scientific execution deferred |

## Complete deployment gap list

- [x] Review candidate source and Bundle manifest; synchronize the 13-tool
      candidate MCP surface and required environment variables.
- [x] Verify v100 user-level runtimes, Worker healthcheck and typecheck without
      starting the daemon.
- [x] Confirm the public catalog returned all 15 Skills; individual Skill
      filters passed in the v100 probe. Four generic operation-contract reads,
      four scale-contract reads, eight public `*-0601` tasks created and
      prepared, and six historical result reads passed; all prepared scheduler
      IDs remained null.
- [x] Run seven Linux control tests, including the no-Slurm executor guard.
- [x] Obtain the required user confirmation and create `target_mlcc_v100`.
- [x] Activate server pairing, `zeus.service`, `mlcc-worker.service` and the
      database heartbeat. Existing `0.60.0` pins remain unchanged.
- [ ] Release the independent MatterAI workspace-resolver fix and verify
      replacement-thread MCP loading on the public host.
- [x] Apply the LF metadata fix and publish candidate deployment revision 3;
      ordinary users can see/hire the candidate.
- [x] Complete five repaired public calls and verify same-thread continuation
      across the Worker restart.
- [ ] Submit/query/collect a real computation; deferred in this round with no
      new Slurm/scientific job, not an undeveloped API.
- [ ] Provide four generic scientific inputs when they become ready; current
      status is `deferred_not_input_ready`.

The three runtime patches are `runtime-node-path.patch`,
`codex-config-0146.patch` and `mlcc-artifact-boundary.patch`; targeted config
and artifact tests passed, final Worker typecheck passed, and the Node-path
suite remains 39 initial passes plus one targeted corrected pass. An old
conversation must be recreated to select `0.60.1` because only one same-name
record can be published.

The initial public error was the old native
`model_supports_reasoning_summaries` override being rejected by Codex 0.146;
the config patch removes only that native setting and retains the catalog
`supports_reasoning_summaries` capability.

Release status is **public control passed; no compute submitted**.
