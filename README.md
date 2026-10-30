# MLCC Agent

This is the **0.60.2 candidate** for the public service at
[agent.mattok.cn](https://agent.mattok.cn). Publication and acceptance status are
recorded in [SYSTEM_MANIFEST.json](SYSTEM_MANIFEST.json). The previous accepted
public version is 0.60.1.

ABACUS is the default production DFT engine. VASP is selected only when the
customer explicitly requests it. The resource library prefers
[AIS Square dataset 381](https://www.aissquare.com/datasets/detail?pageType=datasets&id=381):
its 83 PBE/NC pseudopotentials and 83 paired efficiency orbital files. Reliable
author sources supplement missing elements; a periodic-table record alone does
not establish resource availability or material qualification.

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
