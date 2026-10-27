# MLCC Agent

MLCC is a MatterAI-compatible agent and Python bundle for atomistic and multiscale
workflow contracts around CaZrO3/BaTiO3 ceramics. The published repository contains
the MLCC-owned bundle, domain functions, skills, CLI/MCP adapters, configuration
templates, and design documentation.

Scientific run products, v100 site data, local Zeus state, credentials, downloaded
upstream trees, and generated evidence remain outside this repository. They are
referenced by paths or Study records when needed and are not part of the source
distribution.

## Package

The installable bundle is in [`mlcc-agent/`](mlcc-agent/). It exposes the `mlcc`
CLI and the `mlcc` MCP server declared in `mlcc-agent/bundle.json`.

```powershell
python -m pip install -e .\mlcc-agent
mlcc --help
```

Site paths and Slurm settings belong in local configuration templates under
[`configs/`](configs/); do not put credentials in those files.

## Scope

The repository records engineering input/output contracts, provenance, units,
atom mappings, and explicit unresolved states. Numerical jobs and scientific
postprocessing run on the configured v100 Slurm site; this repository does not
contain the resulting private trajectories or model weights.
