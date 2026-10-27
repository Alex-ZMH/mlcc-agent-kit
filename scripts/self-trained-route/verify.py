"""Verify only the new explicit route, with accepted artifacts and no submission."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

import mlcc
import mlcc_deepmd


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("config", type=Path)
args = parser.parse_args()
config = read(args.config)
root = Path(config["remote_root"])
project = root / "project"
report = root / "reports"
workspace = root / "workspace"
report.mkdir(exist_ok=True)
workspace.mkdir(exist_ok=True)

package = tomllib.loads((project / "mlcc-agent/pyproject.toml").read_text())
assert package["project"]["optional-dependencies"]["ceramic"] == ["mlcc-deepmd-bridge==0.1.0"]
assert Path(mlcc.__file__).is_relative_to(project / "mlcc-agent/src")
assert Path(mlcc_deepmd.__file__).is_relative_to(project / "standalone/deepmd_bridge/src")

# Only the new control-route tests; previous ceramic/core/host checks are reused.
test_command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                str(project / "mlcc-agent/tests/test_ceramic_potential_route.py"),
                f"--junitxml={report / 'route-tests.xml'}"]
with (report / "route-tests.txt").open("w") as stdout:
    subprocess.run(test_command, check=True, stdout=stdout, stderr=subprocess.STDOUT)

common = {"potential_route": "abacus_deepmd", "workspace": str(workspace), "collection": config["collection"]}
training_request = {
    **common, "operation": "create_training", "task_id": "route-training-unsubmitted-v001",
    "input_file": config["input_file"], "interface_acceptance": config["interface_acceptance"],
    "account": "v100", "training_config": config["training_config"],
}
source_task = Path(config["source_md_task"])
protocol = read(source_task / "protocol.json")
site = read(config["site_file"])
site["workspace"] = {"local": str(workspace), "remote_root": str(workspace)}
md_request = {
    **common, "operation": "create_lammps", "task_id": "route-host20-unsubmitted-v001",
    "system_id": "host20", "model_card": config["model_card"], "protocol": protocol,
    "site": site, "resource_request": config["lammps_resources"],
}
tasks = {}
for label, request in (("training", training_request), ("lammps", md_request)):
    request_file = report / f"{label}-route-request.json"
    write(request_file, request)
    command = [sys.executable, "-m", "mlcc.ceramic_potential_route", "--request", str(request_file)]
    with (report / f"{label}.stdout.json").open("w") as stdout, (report / f"{label}.stderr.txt").open("w") as stderr:
        subprocess.run(command, check=True, stdout=stdout, stderr=stderr)
    task_file = workspace / "tasks" / request["task_id"] / "task.json"
    task = read(task_file)
    assert task == read(report / f"{label}.stdout.json")
    assert task["scheduler_job_id"] is None
    assert task["production_qualification"] is False
    assert task["potential_route"] == {
        "selected": "abacus_deepmd", "selection": "explicit", "operation": request["operation"],
        "request_file": str(request_file),
    }
    assert task["events"][-1]["action"] == "select_ceramic_potential_route"
    tasks[label] = task

train = tasks["training"]
assert train["status"] == "created" and train["scientific_status"] == "not_qualified"
assert [str(job) for job in train["source_scheduler_job_ids"]] == ["50", "121"]
assert train["resource_request"]["gres"] == "gpu:v100:4"
train_dir = Path(train["local_workdir"])
native_input = read(train_dir / "input.json")
assert native_input == read(config["input_file"])
manifest = read(train_dir / "training-manifest.json")
assert manifest["batch"]["world_size"] == 4
assert manifest["batch"]["global"] == 4 * manifest["batch"]["local_per_rank"]
assert manifest["dataset"]["training_system_frame_counts"] == [1, 1]
assert manifest["dataset"]["validation_systems"] == []
assert "--nproc-per-node=4" in (train_dir / "deepmd-train.sbatch").read_text()

md = tasks["lammps"]
assert md["status"] == "defined" and md["scientific_status"] == "not_calculated"
assert md["source_system_id"] == "host20" and str(md["source_scheduler_job_id"]) == "50"
assert str(md["training_job_id"]) == "146"
assert md["protocol"] == protocol
assert md["model_id"] == "cazro3-pnma-pristine" and md["model_version"] == "v001"
assert md["study_id"] == "cazro3_firing_validation_v003"
md_dir = Path(md["local_workdir"])
atom_map = read(md_dir / "atom-map.json")
assert atom_map == read(source_task / "atom-map.json")
assert atom_map["source_atom_ids"] == list(range(20))
assert atom_map["element_order"] == ["Ca", "Zr", "O"]
assert (md_dir / "model.data").read_text() == (source_task / "model.data").read_text()
method = read(md_dir / "method.json")
assert method["units"] == "metal" and method["atom_style"] == "atomic"
assert method["potential"]["model_card"] == config["model_card"]
assert method["potential"]["pair_coeff"] == ["* * Ca Zr O"]
assert method["protocol"] == protocol
assert (md_dir / "in.lammps").read_text().startswith(f'plugin load "{site["lammps"]["plugin"]}"')

suite = ET.parse(report / "route-tests.xml").getroot().find("testsuite")
result = {
    "schema": "mlcc.explicit-ceramic-potential-route-acceptance.v1", "status": "passed",
    "verification_job_id": os.environ["SLURM_JOB_ID"],
    "scope": "new explicit choice to existing creators; input generation only",
    "imports": {"python": sys.executable, "mlcc": mlcc.__file__, "bridge": mlcc_deepmd.__file__,
                "source_package_version": package["project"]["version"],
                "binding": "isolated source snapshot; no installed release activation"},
    "tests": dict(suite.attrib), "new_tasks": {
        name: {"task_id": task["task_id"], "status": task["status"], "scheduler_job_id": task["scheduler_job_id"],
               "task_file": str(Path(task["local_workdir"]) / "task.json"), "potential_route": task["potential_route"]}
        for name, task in tasks.items()
    },
    "reused_sources": {"abacus_jobs": ["50", "121"], "collection_job": "141", "training_job": "146",
                       "prior_public_acceptance": "166", "prior_installed_acceptance": "175"},
    "training_requested_gpus": 4, "training_executed": False, "lammps_executed": False,
    "dft_executed": False, "new_numerical_jobs_submitted": [],
    "validation_resources": {"cpus": 1, "memory_mib": 4096, "gpus": 0, "time": "00:05:00"},
    "production_qualification": False, "scientific_status": "engineering_input_route_only",
    "polarization_or_dielectric_capability": False,
}
write(report / "acceptance.json", result)
print(json.dumps(result, indent=2))
