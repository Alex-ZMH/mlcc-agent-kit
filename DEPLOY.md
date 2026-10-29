# MLCC 0.60.1 candidate deployment boundary

This directory is the MLCC-owned integration delivery. It is not a copy of the
MatterAI host and it is not a public-compute availability claim.

## Version state

| Layer | State | Meaning |
| --- | --- | --- |
| Bundle manifest | `0.60.1` | Candidate manifest; its 10 MCP tools and two required environment variables are synchronized in the working tree. |
| Published baseline | `0.60.0` | Installed/published, but the public MCP path failed. |
| Candidate label | `0.60.1-candidate` | Control-only checks passed; not deployed or publicly accepted. |
| GitHub delivery baseline | `codex/cloud-delivery-20261029` / `5dbb0e4` | Source-distribution baseline; this is not the runtime integration branch. |
| Historical source | `0.57` | Historical enabled source only; it is not the current candidate. |

Do not describe this candidate as deployed or as publicly usable until the gates
in [`docs/public-chain-audit-20261029.md`](docs/public-chain-audit-20261029.md)
are closed.

## What is in this repository

- `mlcc-agent/`: the MLCC Agent, eight Skills, independent FEM, phase-field,
  RVE and SPICE modules, CLI/MCP adapters, schemas and examples.
- `configs/`: site templates. Actual SSH identity, host, environment and
  scheduler paths remain operator configuration.
- `scripts/`: site and Slurm preparation helpers.
- `SYSTEM_MANIFEST.json`: the current candidate boundary and evidence index.
- `docs/public-chain-audit-20261029.md`: the public-chain audit and missing
  deployment gates.

The independent MatterAI host, its workspace resolver, catalog/runtime code and
the outbound Worker are not included here. The GitHub delivery depends on those
components being released separately. Upstream reference trees remain outside
the MLCC repository.

## Current execution chain

```text
MatterAI host + workspace resolver
        -> cloud Worker (deployed; current MLCC MCP startup fails)

Proposed compute route, not deployed:
MatterAI host <-> outbound Worker on v100
        -> MLCC MCP / CLI -> local Slurm commands on v100
```

The public Worker already exists. The proposed v100 Worker connects outward to
the public host; it is not a second hop through the cloud Worker. It needs a
Node/Codex runtime, worker registration and a private site template on v100.
These are not provisioned. The v100 site was used for engineering
acceptance. That does not make the public endpoint available for computation.
The target contract does not require localhost, but that target property is not
currently verified on the public chain.

## Skill coverage boundary

The new four-scale MCP surface covers only FEM, phase field, RVE and SPICE.
The other four Skills remain CLI create/consume paths and have not completed a
public conversational loop:

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

## Historical four-scale acceptance

The local acceptance archive records these four existing jobs. They are
historical evidence, not new submissions from this candidate:

| Module | Operation | Slurm job | Final state | Result read |
| --- | --- | ---: | --- | --- |
| FEM | `electrostatics_2d_quantities` | 702 | `COMPLETED`, `0:0` | `mlcc.task-result-view.v1`, passed |
| phase field | `vector_evolve_si` | 703 | `COMPLETED`, `0:0` | `mlcc.task-result-view.v1`, passed |
| RVE | `homogenize_electrostatics_2d` | 704 | `COMPLETED`, `0:0` | `mlcc.task-result-view.v1`, passed |
| SPICE | `ac_impedance` | 705 | `COMPLETED`, `0:0` | `mlcc.task-result-view.v1`, passed |

The raw files are retained locally under
`versions/0.60.0/evidence/four-scale-workbench-20261028/` and are not
committed because they contain site-specific paths and runtime material.
Their `scientific_status` is `not_checked`; the table is an engineering
execution record, not a material qualification or a public deployment proof.

## Deployment prerequisites

Before an operator attempts a public release, all of the following must be
completed and recorded. This round is control-only and does not submit a real
calculation:

- [x] Review the 0.60.1 source changes; Git identifies the delivery revision.
- [x] Synchronize `bundle.json` with the candidate MCP tools and required
      environment variables in the working tree.
- [x] Verify the real candidate MCP in an isolated container: protocol, ten
      tools, four creates, prepares, local file transfers and four saved reads.
- [ ] Release the independent MatterAI host workspace-resolver fix and verify
      replacement-thread MCP loading on the target host.
- [ ] Configure and verify the missing v100 outbound-worker route; the public
      Worker itself is already deployed.
- [ ] Preserve the existing v100 engine environments and inject the private
      site contract into the selected Worker. A v100-local Worker uses
      `ssh.transport="local"`; the default SSH transport remains supported.
- [ ] After separate user authorization, run a fresh end-to-end job. This is
      deferred in the current round; do not submit a job now and do not reuse
      jobs 702–705 as a new submission.
- [ ] Publish the catalog candidate only after the isolated test, host fix and
      route checks pass; production cut is deferred in this round.
- [x] Include the sanitized [control-check evidence](docs/evidence/no-submit-audit-20261029.json).

Until these checks pass, the correct status is **candidate / not publicly
available**.
