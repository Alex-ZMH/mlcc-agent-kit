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

## v100 server layout

The supported development site is the existing SSH alias `v100`. A checkout can
be transferred to `/home/v100/projects/mlcc`; the site-specific executable and
pseudopotential/orbital paths are recorded in
[`configs/site.v100.example.json`](configs/site.v100.example.json). Slurm job
templates and runtime preparation scripts are under [`scripts/`](scripts/).

Typical setup on the server is:

```bash
mkdir -p /home/v100/projects/mlcc
cd /home/v100/projects/mlcc
python -m pip install -e ./mlcc-agent
sbatch scripts/admin/slurm-gpu-smoke.sbatch
```

The repository supplies paths and templates so another authorized v100 user can
reproduce the setup. Access to the server, pseudopotential libraries, model
files, and private scientific results remains governed by the site's existing
permissions; no credentials are stored here.

## Scope

The repository records engineering input/output contracts, provenance, units,
atom mappings, and explicit unresolved states. Numerical jobs and scientific
postprocessing run on the configured v100 Slurm site; this repository does not
contain the resulting private trajectories or model weights.
