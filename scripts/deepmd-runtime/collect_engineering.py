"""Collect native scheduler evidence and engineering metrics inside Slurm."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from mlcc_deepmd.handoff import collect_training

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--site", type=Path, required=True)
parser.add_argument("--public-job-id")
args = parser.parse_args()
site = json.loads(args.site.read_text())
root = Path(site["remote_root"])
experiment = root / "engineering-v001"
report = root / "reports"
records = {}
jobs = {"runtime": "118", "data": "122", "train_1gpu": "124", "train_2gpu": "125", "interface": "126"}
if args.public_job_id:
    jobs["train_4gpu_public"] = args.public_job_id
for name, job_id in jobs.items():
    raw = subprocess.run(["scontrol", "show", "job", job_id, "-o"], check=True, text=True, capture_output=True).stdout
    (report / f"scheduler-{job_id}.txt").write_text(raw)
    fields = dict(re.findall(r"(\w+)=(\S+)", raw))
    records[name] = {"job_id": job_id, "state": fields["JobState"], "exit_code": fields["ExitCode"],
                     "workdir": fields["WorkDir"], "runtime": fields["RunTime"], "raw": raw}
training = []
for name in ("train_1gpu", "train_2gpu", "train_4gpu_public"):
    if name not in records:
        continue
    native = records[name]
    workdir = Path(native["workdir"])
    dataset = experiment / "dataset/dataset_manifest.json"
    card_path = collect_training(workdir, dataset, native)
    card = json.loads(card_path.read_text())
    stderr = (workdir / "stderr.log").read_text()
    stdout = (workdir / "stdout.log").read_text()
    ranks = sorted(set((int(a), int(b)) for a, b in re.findall(r"Rank:\s+(\d+)/(\d+)", stderr)))
    world = card["batch"]["world_size"]
    if ranks != [(rank, world) for rank in range(world)]:
        raise ValueError(f"missing native training ranks for {name}: {ranks}")
    seconds = float(re.search(r"average training time:\s+([\d.]+) s/batch", stderr)[1])
    item = {"name": name, "scheduler": native, "native_ranks": ranks, "world_size": world,
            "local_batch": card["batch"]["local_per_rank"], "global_batch": card["batch"]["global"],
            "seconds_per_step_excluding_first_10": seconds,
            "sample_exposures_per_second": card["batch"]["global"] / seconds,
            "model_card": str(card_path), "scientific_status": "not_qualified"}
    training.append(item)
    card["native_execution"] = {"rank_records": ranks,
                                "gpu_banner": [line for line in stderr.splitlines() if any(term in line for term in ("Computing Device:", "Device Name:", "Visible GPU Count:", "PT Ver:", "CUDA_VISIBLE_DEVICES:"))],
                                "nccl_device_evidence": [line for line in stdout.splitlines() if "cudaDev" in line]}
    card_path.write_text(json.dumps(card, indent=2) + "\n")
interface_dir = experiment / "interface-2gpu-model"
interface = json.loads((interface_dir / "interface-acceptance.json").read_text())
interface["scheduler"] = records["interface"]
interface["training_job_id"] = records["train_2gpu"]["job_id"]
interface["model_card"] = str(experiment / "train-2gpu/model-card.json")
interface["runtime"] = site
(interface_dir / "interface-acceptance.json").write_text(json.dumps(interface, indent=2) + "\n")
result = {"schema": "mlcc.deepmd-engineering-acceptance.v1", "scheduler_jobs": records,
          "dataset_frames": 2, "independent_validation": False,
          "training": training, "interface_status": interface["status"],
          "interface_errors": interface["max_absolute_errors"],
          "scaling_scope": "100 steps; local batch 1; 2 unique Ni frames; exposure throughput only, no production speed claim",
          "scientific_status": "not_qualified", "design_assessment": "not_assessed"}
(report / "acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"interface": interface["status"], "training": training}, indent=2))
