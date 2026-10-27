"""Turn the saved real MPI outputs into a small, readable acceptance record."""
import json
from pathlib import Path
import re

workspace = Path(__file__).resolve().parents[2] / "workspace"
for size, name, job_id, snapshot in (
    (1, "one", "12", "mpi-one-terminal.txt"),
    (4, "four", "13", "mpi-four-check.txt"),
):
    task_id = f"h0-mpi-{name}-v001"
    task_dir = workspace / "tasks" / task_id
    scheduler_raw = (workspace / "reports/h0" / snapshot).read_text(encoding="utf-8-sig")
    scheduler = dict(re.findall(r"([A-Za-z][A-Za-z0-9_]*)=([^\s]+)", scheduler_raw))
    stdout = (task_dir / "stdout.log").read_text()
    ranks = [
        dict(re.findall(r"(\w+)=([^\s]+)", line))
        for line in stdout.splitlines() if line.startswith("rank=")
    ]
    expected = size * (size + 1) // 2
    assert scheduler["JobId"] == job_id
    assert scheduler["JobState"] == "COMPLETED"
    assert scheduler["ExitCode"] == "0:0"
    assert len(ranks) == size
    assert sorted(int(row["rank"]) for row in ranks) == list(range(size))
    assert len({row["pci"] for row in ranks}) == size
    assert all(int(row["size"]) == size for row in ranks)
    assert all(int(row["host_sum"]) == expected for row in ranks)
    assert all(int(row["device_sum"]) == expected for row in ranks)
    task = {
        "task_id": task_id,
        "stage": "P1",
        "purpose": "MPI_CPU_and_CUDA_device_buffer_reduction",
        "runner": "slurm",
        "scheduler_job_id": job_id,
        "scheduler_state": scheduler["JobState"],
        "status": scheduler["JobState"],
        "exit_code": scheduler["ExitCode"],
        "scheduler_snapshot": f"workspace/reports/h0/{snapshot}",
        "command": [
            "/opt/nvidia/hpc_sdk/Linux_x86_64/24.1/comm_libs/12.3/hpcx/hpcx-2.17.1/ompi/bin/mpirun",
            "--map-by", "slot", "--bind-to", "core", "--report-bindings",
            "/home/v100/projects/mlcc/bin/mpi_cuda_reduction",
        ],
        "environment_script": "/home/v100/projects/mlcc/configs/vasp-nvhpc-env.sh",
        "remote_workdir": f"/home/v100/projects/mlcc/tasks/{task_id}",
        "resource_request": {
            "partition": "gpu", "nodes": 1, "ntasks": size,
            "cpus_per_task": 1, "gpus_per_task": "v100:1",
            "mem_mib": 4096, "time": "00:03:00",
        },
        "depends_on": [] if size == 1 else ["h0-mpi-one-v001"],
        "scientific_status": "not_a_material_calculation",
        "engineering_acceptance": "passed",
        "rank_observations": ranks,
        "note": "Submitted before runner implementation; manual sbatch integration evidence.",
    }
    (task_dir / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    print(f"{task_id}: job {job_id}, {size} unique ranks/GPUs, reductions {expected}, passed")
