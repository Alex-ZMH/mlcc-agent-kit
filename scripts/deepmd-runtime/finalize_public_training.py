"""Register existing model outputs on the public task without retraining."""
import json
from pathlib import Path
import re
import subprocess
import sys

from mlcc_deepmd.handoff import collect_training

root = Path(sys.argv[1])
report = root / "reports"
dataset = root / "engineering-v001/dataset/dataset_manifest.json"
records = {}
for job_id in ("124", "125", "129"):
    raw = subprocess.run(["scontrol", "show", "job", job_id, "-o"], check=True,
                         text=True, capture_output=True).stdout
    fields = dict(re.findall(r"(\w+)=(\S+)", raw))
    records[job_id] = {"job_id": job_id, "state": fields["JobState"], "exit_code": fields["ExitCode"],
                       "workdir": fields["WorkDir"], "raw": raw}
    (report / f"scheduler-{job_id}.txt").write_text(raw)
for job_id in ("124", "125"):
    collect_training(records[job_id]["workdir"], dataset, records[job_id])
task_dir = Path(records["129"]["workdir"])
(task_dir / "handoff-scheduler-record.json").write_text(json.dumps(records["129"], indent=2) + "\n")
# Use the public standalone command, preserving the normal TaskRecord file.
subprocess.run([sys.executable, "-m", "mlcc_deepmd", "finalize-task", str(task_dir / "task.json"),
                str(task_dir / "handoff-scheduler-record.json")], check=True,
               stdout=(report / "public-finalize-task.json").open("w"))
task = json.loads((task_dir / "task.json").read_text())
assert task["model_handoff"]["status"] == "engineering_handoff"
assert task["model_handoff"]["training_job_id"] == "129"
assert "model-card.json" in task["collect_paths"]
acceptance = json.loads((report / "acceptance.json").read_text())
acceptance["public_training_handoff"] = task["model_handoff"]
acceptance["handoff_binding_checks"] = "scheduler workdir, native input, dataset systems, checkpoint and frozen model"
(report / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n")
print(json.dumps(task["model_handoff"], indent=2))
