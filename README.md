# MLCC Agent

This is the **0.60.1 candidate**. It is published and visible/hireable in the
catalog, and its public control round passed without submitting compute. This
is not a claim of scientific execution or production qualification. The former
`0.60.0` catalog publication was cancelled while its enabled deployment and
historical pins remain unchanged.

Start with [DEPLOY.md](DEPLOY.md),
[SYSTEM_MANIFEST.json](SYSTEM_MANIFEST.json) and the
[public-chain audit](docs/public-chain-audit-20261029.md).

MLCC is a MatterAI-compatible agent and Python bundle for atomistic and
multiscale workflow contracts around CaZrO3/BaTiO3 ceramics. This repository
contains the MLCC-owned bundle, domain functions, 8 top-level Skills plus 7
nested module-method routes (15 total), CLI/MCP adapters, configuration
templates and design documentation.

## What was verified

- v100 user-level Node `22.23.2`, Codex `0.146.0`, Python `3.12.3` and MCP
  `2.3.0` were present; the Worker healthcheck returned `1`.
- The existing scientific environment already had `numpy`, `ase`, `scipy`,
  `phonopy`, `phonors`, `symfc`, `h5py` and `pymatgen`. It was not changed.
- The candidate Bundle exposes 13 MCP tools, 8 top-level Skill routes, 7
  nested module-method routes and 114 CLI catalog routes. The public catalog
  returned all 15 Skills; individual Skill filters passed in the v100 probe.
  Four generic operation-contract reads, four scale-contract reads, eight
  public `*-0601` tasks created and prepared, and six historical
  `mlcc_read_result` calls completed. Prepared task job IDs were all `null`.
- Five repaired public calls completed, and the same thread/provider session
  continued successfully across a Worker restart. No Slurm command or
  scientific computation was submitted. Seven Linux control tests passed.
- The Worker runtime has three small source patches: Node resolution through
  `process.execPath`; removal of the rejected native
  `model_supports_reasoning_summaries` override while retaining the catalog
  capability; and artifact-boundary handling for site config and task payloads
  at two entry points. The targeted config test passed, both artifact-boundary
  tests passed, and final Worker typecheck passed. The Node-path suite remains
  39 initial passes plus one targeted corrected pass, not a complete final
  40-case rerun.

These checks establish the candidate public control path and current Worker
deployment, not scientific execution or material qualification.

## Package

The installable bundle is in [`mlcc-agent/`](mlcc-agent/). It exposes the
`mlcc` CLI and MCP server declared in `mlcc-agent/bundle.json`.

```powershell
python -m pip install -e .\mlcc-agent
mlcc --help
```

The candidate requires these operator-provided environment variables:

- `MLCC_SITE_CONFIG`: absolute path to the private site configuration.
- `MLCC_WORKSPACE_ROOT`: the Worker's managed project-workspace root.

Do not place credentials, SSH keys, licensed pseudopotentials, runtime
binaries, scientific outputs or full private host configuration in this
repository.

## Cloud and v100 boundary

The intended public control plane is `https://agent.mattok.cn`. A v100-local
Worker uses `ssh.transport="local"` to control the existing Slurm site; it is
not a localhost dependency and it does not replace the public host. The
approved `target_mlcc_v100` exists, server pairing credentials are active,
`zeus.service` is active, the user-level `mlcc-worker.service` is running and
the database heartbeat is online.

The LF metadata fix was applied before publication. The same unpublished
deployment ID advanced from revision 2 to final revision 3 under the immutable
store rule. Five repaired public calls completed, including the same
thread/provider session continuing across a Worker restart. Because only one
same-name record may be published, an old conversation must start a new
conversation to select `0.60.1`; do not claim an old conversation continued on
the new revision.

The six historical results retain their domain status: DFT489 is
`raw_charged_scf_unqualified`, MD45 is `executed_engineering_fixture`, and the
four continuum results are `not_checked`. The four generic scientific inputs
remain `deferred_not_input_ready`; real submit/query/collect execution is
deferred this round, not undeveloped.

The initial continuum read used JSON-only copies and failed. Restoring the
original payload/schema/artifacts directories made all four reads succeed; the
original task/result records were unchanged and this did not reveal a source
portability bug.

See [`scripts/worker/README.md`](scripts/worker/README.md) for the current
Worker boundary and safe checks.

## Scientific data boundary

Numerical jobs and scientific postprocessing belong on the configured v100
Slurm site. Scientific run products, private site data, local Zeus state,
credentials, downloaded upstream trees and generated evidence remain outside
this source distribution. The four historical jobs 702–705 are engineering
records only; their scientific status remains `not_checked`.
