"""Bind the existing native public LAMMPS output to its training handoff."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from mlcc.lammps_tasks import parse_lammps_task
from mlcc_deepmd.inference import compare_interface

parser = argparse.ArgumentParser()
parser.add_argument("root", type=Path)
parser.add_argument("job_id")
args = parser.parse_args()
root = args.root
directory = root / "system/tasks/p9-deepmd-lammps-public-v001"
raw = subprocess.run(["scontrol", "show", "job", args.job_id, "-o"], check=True, text=True, capture_output=True).stdout
fields = dict(re.findall(r"(\w+)=(\S+)", raw))
task_file = directory / "task.json"
task = json.loads(task_file.read_text())
if fields["WorkDir"] != str(directory) or fields["JobId"] != task["scheduler_job_id"]:
    raise ValueError("native LAMMPS scheduler identity differs from task")
if fields["JobState"] != "COMPLETED" or fields["ExitCode"] != "0:0":
    raise ValueError("native public LAMMPS job did not complete")
task.update(scheduler_state=fields["JobState"], status=fields["JobState"], exit_code=fields["ExitCode"])
task_file.write_text(json.dumps(task, indent=2) + "\n")
native = parse_lammps_task(task_file)
comparison = compare_interface(directory)
card_path = root / "system/tasks/p9-deepmd-public-4gpu-v001/model-card.json"
card = json.loads(card_path.read_text())
if task["potential"]["training_job_id"] != card["job_id"]:
    raise ValueError("downstream potential has a different training job")
report = root / "reports"
(report / f"scheduler-{args.job_id}.txt").write_text(raw)
acceptance = json.loads((report / "acceptance.json").read_text())
acceptance["public_lammps"] = {"task_id": task["task_id"], "scheduler_job_id": args.job_id,
    "state": fields["JobState"], "exit_code": fields["ExitCode"], "raw_scheduler": raw,
    "training_task_id": "p9-deepmd-public-4gpu-v001", "training_job_id": card["job_id"],
    "model_card": str(card_path), "interface_status": comparison["status"],
    "errors": comparison["max_absolute_errors"], "parser_scientific_status": native["scientific_status"]}
acceptance["engineering_status"] = "passed"
acceptance["integration_scope"] = "source adapter plus existing MLCC TaskRecord/SiteRunner and LAMMPS creator/parser; no Bundle release activation"
acceptance["production_qualification"] = False
(report / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n")
print(json.dumps(acceptance["public_lammps"], indent=2))
