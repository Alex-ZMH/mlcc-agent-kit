# MLCC Agent

This is the **0.60.2** source and deployment record for the public service at
[agent.mattok.cn](https://agent.mattok.cn). Publication and acceptance status are
recorded in [SYSTEM_MANIFEST.json](SYSTEM_MANIFEST.json). Deployment
`deployment_mlcc_v100_0_60_2` revision 4 is published and its v100 Worker is
active. The previous 0.60.1 catalog is unpublished but remains enabled as the
rollback version.
Two consecutive ordinary-user read-only turns passed in the same thread and
Codex provider session on deployment revision 4. A third turn confirmed the Bh
metadata correction after the Worker resource update. All three runs completed;
their four tool calls used only `mlcc_describe_dft_resources` and created zero
`task.json` files.

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
precondition because the v100 node was occupied. Job 776 remains `PENDING`; it
was not cancelled or bypassed, and its pending record is not a pass result.

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
preserved. [0.60.1 verification history](docs/evidence/public-0601-verification-history.md)
records the earlier control tests separately from this release.

Source folder: `versions/0.60.2-candidate` in the local MLCC workspace.
