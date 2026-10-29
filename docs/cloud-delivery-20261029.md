# Cloud delivery

This repository is the source distribution for the MLCC bundle. Runtime
execution uses a remote Slurm site over SSH; the local Zeus web UI is not a
runtime dependency and no localhost endpoint is part of the cloud contract.

Before using the template, configure an SSH alias on the operator machine. The
private key and the actual host/user/port stay in `~/.ssh/config`:

```sshconfig
Host mlcc-cloud
    HostName <cloud-host>
    User <cloud-user>
    Port <cloud-ssh-port>
    IdentityFile <private-key>
```

Verify access before running a task:

```powershell
ssh mlcc-cloud 'hostname; id -un; command -v sbatch; scontrol version'
scp -q .\mlcc-agent\bundle.json mlcc-cloud:/tmp/mlcc-bundle.json
```

On the server, create the checkout and install the bundle into the selected
Python environment:

```bash
mkdir -p /home/v100/projects/mlcc
cd /home/v100/projects/mlcc
python -m pip install -e ./mlcc-agent
```

Use [`configs/site.cloud.example.json`](../configs/site.cloud.example.json) as
the site contract. Copy it to a private workspace configuration and keep the
remote root, environment script, pseudopotential/orbital paths, and scheduler
partition specific to that server. The bundle's runner submits with
`sbatch --parsable`, reads state with `scontrol`, and collects only the paths
listed by the task. It never starts a numerical process directly over SSH and
does not silently fall back to localhost or another scheduler.

The development endpoint `43.142.15.151:22022` accepted TCP connections during
the 2026-10-29 check, but the available local SSH identity was rejected. A
cloud deployment is therefore pending the operator's valid SSH identity; no
credentials are stored in this repository.

## Four-scale evidence

The 0.60 candidate was exercised through the remote `v100` Slurm alias with
four independent tasks: FEM job 702, phase-field job 703, RVE job 704, and
SPICE job 705. Each reached `COMPLETED` with `ExitCode=0:0`, was collected, and
passed the saved-result reader. The detailed local evidence remains under
`workspace/reports/four-scale-workbench-20261028/` and is intentionally not
committed with scientific output files.

The same Agent bundle declares eight Skills: `model-mlcc-structures`,
`run-mlcc-dft`, `run-mlcc-md`, `run-mlcc-phase-field`, `run-mlcc-rve`,
`run-mlcc-fem`, `run-mlcc-spice`, and `compute-mlcc-properties`. This round
added four new real Slurm lifecycles; existing modeling, DFT, MD, and property
consumer evidence was reused without repeating calculations.
