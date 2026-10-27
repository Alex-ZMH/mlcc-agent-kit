"""Create the three small, non-scientific Slurm integration tasks."""
import json
from pathlib import Path


workspace = Path(__file__).resolve().parents[2] / "workspace"
commands = {
    "h0-runner-echo-v001": [
        "/usr/bin/python3",
        "-c",
        "import json,os; from pathlib import Path; "
        "result={'task':'h0-runner-echo-v001','job_id':os.environ['SLURM_JOB_ID'],"
        "'message':'MLCC LAN Slurm roundtrip'}; "
        "Path('receipt.json').write_text(json.dumps(result)); print(json.dumps(result))",
    ],
    "h0-runner-failure-v001": [
        "/usr/bin/python3",
        "-c",
        "import sys; print('MLCC controlled failure: requested exit 7',file=sys.stderr); sys.exit(7)",
    ],
    "h0-runner-cancel-v001": [
        "/usr/bin/python3",
        "-u",
        "-c",
        "import time; print('MLCC cancellation fixture started',flush=True); time.sleep(120)",
    ],
}
for task_id, command in commands.items():
    directory = workspace / "tasks" / task_id
    directory.mkdir()
    task = {
        "task_id": task_id,
        "stage": "P1",
        "purpose": "non_scientific_runner_acceptance",
        "engine": None,
        "method_set": None,
        "model_id": None,
        "depends_on": [],
        "runner": "slurm",
        "scheduler_job_id": None,
        "command": command,
        "resource_request": {
            "nodes": 1,
            "partition": "cpu",
            "ntasks": 1,
            "cpus_per_task": 1,
            "hint": "nomultithread",
            "mem_mib": 256,
            "time": "00:03:00",
        },
        "transfer_paths": [],
        "collect_paths": ["stdout.log", "stderr.log"],
        "scientific_status": "not_applicable",
        "status": "defined",
    }
    if task_id == "h0-runner-echo-v001":
        task["collect_paths"].append("receipt.json")
    (directory / "task.json").write_text(
        json.dumps(task, indent=2) + "\n", encoding="utf-8"
    )
    print(directory / "task.json")
