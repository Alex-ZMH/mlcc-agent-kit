"""Record an explicitly submitted development job from native scontrol data.

This is administrative control only: it neither submits nor parses a solver.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--task", type=Path, required=True)
parser.add_argument("--job-id", required=True)
args = parser.parse_args()
task = json.loads(args.task.read_text(encoding="utf-8"))
if task.get("scheduler_job_id") not in (None, args.job_id):
    raise ValueError("task already belongs to a different scheduler job")
command = ["scontrol", "show", "job", args.job_id, "-o"]
raw = subprocess.run(command, capture_output=True, text=True, check=True).stdout
fields = dict(re.findall(r"(\w+)=(\S+)", raw))
if fields["JobId"] != args.job_id or Path(fields["WorkDir"]).resolve() != args.task.parent.resolve():
    raise ValueError("native scheduler job/work directory does not identify this task")
task.update(scheduler_job_id=args.job_id, scheduler_state=fields["JobState"],
            status=fields["JobState"], exit_code=fields["ExitCode"], runner="slurm")
if fields["JobState"] == "COMPLETED" and fields["ExitCode"] == "0:0":
    for value in task["collect_paths"]:
        if not (args.task.parent / value).exists():
            raise FileNotFoundError(args.task.parent / value)
    task.update(collect_status="collected", collection_mode="native_outputs_already_in_v100_workspace")
task.setdefault("events", []).append({"action": "record_native_development_job", "command": command,
                                      "recorded_at": datetime.now(timezone.utc).isoformat(), "stdout": raw})
args.task.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
(args.task.parent / "scheduler-latest.txt").write_text(raw, encoding="utf-8")
print(json.dumps({"job_id": args.job_id, "state": fields["JobState"], "exit_code": fields["ExitCode"]}))
