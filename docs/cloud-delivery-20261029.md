# Public deployment status · 2026-10-29

Read [the deployment checklist](../DEPLOY.md) before installing this candidate.
The public baseline is 0.60.0. It is published, but its MCP process fails to
start in the current cloud Worker. Version 0.60.1 is a repair candidate, not a
publicly accepted release.

The compute site remains the existing **v100 + Slurm** installation. Public
users access `https://agent.mattok.cn`; their computers are not compute workers.
The cloud web server does not replace v100's scientific environments.

## Routes and runtime

The existing cloud Worker cannot reach the LAN-only v100 SSH alias. A proposed
route is a Worker running on v100 that connects outward to the public host.
That route is not deployed: v100 still needs the Worker Node/Codex runtime,
registration and private operator configuration. It is not a chain of two
Workers. The existing SSH transport remains the default for development.

For a Worker already running on v100, a private site may set
`ssh.transport="local"`. The runner then performs file copies and invokes
Slurm control commands locally. Numerical execution still belongs to Slurm;
this setting does not start scientific programs directly.

MLCC MCP requires Python >=3.12, `mcp==2.3.0` and `PyYAML==6.0.3`.
The production cloud image currently selects Python 3.11/MCP 1.28.1 and fails
at `from mcp.server import MCPServer`. The optional image extension in
`scripts/runtime/` was built and tested in isolation; it has not replaced the
production image. It depends on the operator's existing base image.

## Private site configuration

Preserve the original v100 configuration and its engine environments. Keep
VASP, ABACUS, LAMMPS, FEniCSX and ngspice paths and PP/NAO/model libraries
outside this Git repository. Do not overwrite the older full v100 config
with a four-scale-only template.

The candidate Bundle declares two required operator environment variables:

- `MLCC_SITE_CONFIG`: absolute path to the private site template.
- `MLCC_WORKSPACE_ROOT`: the Worker's managed project-workspace root.

MCP resolves `zeus://workspace/current` to its project cwd and creates a
project-local `configs/site.v100.json`. The remote root is isolated by the
project path relative to the managed workspace root. An existing different
project config is reported for explicit migration rather than overwritten.
These variables must be supplied through the host's MCP environment allowlist.

The checked-in cloud template contains only the runner skeleton; it is not a
complete scientific deployment. The operator must supply explicit engine and
module bindings. Credentials and licensed pseudopotentials are not distributed.

## Acceptance boundary

This round prohibits new jobs. Isolated checks cover protocol, creation,
batch-file preparation, local file transport and reading copies of saved
results. They do not establish new scheduler execution or a public browser
conversation. Actual submission and new scientific acceptance remain deferred.

Historical jobs FEM 702, phase-field 703, RVE 704 and SPICE 705 completed and
were read successfully. Their sanitized summary is in
[the chain audit](public-chain-audit-20261029.md). Binding eight Skills is not
proof that modeling, DFT, MD and properties also work through the public host.
