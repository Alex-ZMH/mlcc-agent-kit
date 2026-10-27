# H0 runner contract

`mlcc-agent/src/mlcc/site_runner.py` is the smallest MLCC site adapter. It
uses the existing `v100` LAN alias and `scp`; a numerical executable is only
present in a generated batch script and is started by Slurm after `sbatch`.
SSH is used for `mkdir`, `sbatch --parsable`, `scontrol show job`, and
`scancel`. No direct SSH process launch, queue fallback, automatic retry, or
requeue is implemented.

## Site configuration

The private site file is JSON and stays in `workspace/configs/`. The portable
Bundle contains no host paths, credentials, VASP binaries, or POTCAR files.
The runner reads this contract:

```json
{
  "ssh": {"alias": "v100"},
  "workspace": {
    "local": "D:/project/mlcc/workspace",
    "remote_root": "/home/v100/projects/mlcc"
  },
  "runner": {
    "selected": "slurm",
    "slurm": {
      "default_partition": "cpu",
      "environment_script": "/home/v100/projects/mlcc/configs/site-env.sh"
    }
  }
}
```

The private execution file must use the approved `workspace.remote_root`.
`ssh_program` and
`scp_program` may be set when the local environment requires an explicit
executable; their defaults are `ssh` and `scp`.

## Task record

The task is a JSON object with at least `task_id` and a non-empty `command`
list. It carries the scientific fields from the harness contract and a
`resource_request` object. Supported Slurm resource keys are `partition`,
`ntasks`, `cpus_per_task`, `mem_mib`, `time`, `gres`, `gpus_per_task`,
`gpus`, `constraint`, `hint`, `nodes`, `job_name`, `stdout_log`, and
`stderr_log`. The runner
always emits `#SBATCH --no-requeue`.

As of the 2026-10-22 user direction, the 0.10 candidate runner treats
`engine=abacus` and `engine=vasp` as DFT: missing/null/empty `time` is persisted
as `0`, finite requests are rejected, and submission explicitly uses
`sbatch --parsable --time=0`. Non-DFT budgets are unchanged. A partition must
permit unlimited time; v100 cpu/gpu MaxTime=UNLIMITED was verified after user administrator authentication on 2026-10-22. The frozen installed 0.9 package is unchanged: future requests
there must explicitly supply `time: 0`. See
[DFT convergence policy](dft-convergence-policy-20261022.md).

`transfer_paths` names additional local files or directories copied into the
remote task directory; the generated `job.sbatch` is always copied as well.
`runner.slurm.environment_script` (or the task-level `environment_script`)
is sourced inside the batch script, so site-specific MPI/DFT paths stay in
the private configuration and are never embedded in the Bundle.
`collect_paths` names explicitly selected remote files; each item
is either a string or `{ "remote": ..., "local": ... }`. The runner records
the native job ID, raw submit/query output, parsed Slurm fields, exit code,
resource fields, every command event, and raw failures in the same task JSON.
`COMPLETED` with `ExitCode=0:0` remains a scheduler result; scientific
convergence and physical validity are separate fields owned by the engine
adapter.

## CLI

Run from the package environment (or with `PYTHONPATH=mlcc-agent/src`):

```text
mlcc prepare  --site workspace/configs/site.v100.json --task workspace/tasks/t1/task.json
mlcc transfer --site workspace/configs/site.v100.json --task workspace/tasks/t1/task.json
mlcc submit   --site workspace/configs/site.v100.json --task workspace/tasks/t1/task.json
mlcc status   --site workspace/configs/site.v100.json --task workspace/tasks/t1/task.json
mlcc cancel   --site workspace/configs/site.v100.json --task workspace/tasks/t1/task.json
mlcc collect  --site workspace/configs/site.v100.json --task workspace/tasks/t1/task.json
```

`status` calls `scontrol` and saves its raw response. Because this Slurm setup
does not provide `sacct`, a task must be queried and persisted while the
controller still retains the job; an unavailable historical job is retained
as a query error rather than inferred to be successful.

The included unit tests stub `subprocess.run` and therefore are not evidence
of a real calculation. The root execution agent owns the subsequent LAN
submission and real H0 evidence.

