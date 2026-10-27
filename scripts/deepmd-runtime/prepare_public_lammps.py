"""Consume the public four-GPU model card through MLCC's LAMMPS creator."""
import json
from pathlib import Path
import sys

from mlcc.lammps_tasks import create_lammps_task

root = Path(sys.argv[1])
project = root / "project"
training_dir = root / "system/tasks/p9-deepmd-public-4gpu-v001"
card_path = training_dir / "model-card.json"
card = json.loads(card_path.read_text())
if card["status"] != "engineering_handoff" or card["scientific_status"] != "not_qualified":
    raise ValueError("expected explicitly unqualified engineering model card")
model_id = "ni-fcc-engineering"
configuration = root / "system/configs"
configuration.mkdir(exist_ok=True)
def save(name, value):
    path = configuration / name
    path.write_text(json.dumps(value, indent=2) + "\n")
    return path
study = save("study.json", {"study_id": "deepmd-system-engineering-v001", "case_id": "ni-fixture",
    "case_role": "engineering_fixture", "model": {"model_id": model_id, "version": "v001", "fixture": True}})
potential = save("potential.json", {"potential_id": "deepmd-public-4gpu", "version": "0.1.0",
    "source": str(card_path), "license": "project engineering model; not distributed",
    "fixture": True, "production_qualification": False, "elements": card["type_map"],
    "element_order": card["type_map"], "model_ids": [model_id], "units": "metal", "atom_style": "atomic",
    "pair_style": "deepmd frozen.pth", "pair_coeff": ["* * " + " ".join(card["type_map"])],
    "training_task_id": "p9-deepmd-public-4gpu-v001", "training_job_id": card["job_id"],
    "model_card": str(card_path), "backend": card["backend"], "model_format": card["format"],
    "files": [{"local_path": card["frozen_model"], "filename": "frozen.pth"}]})
protocol = save("protocol.json", {"kind": "run0", "static_tensor": True, "units": "metal",
    "boundary": ["p", "p", "p"], "timestep_ps": 0.001, "purpose": "potential_qualification",
    "experiment_scope": "public four-GPU engineering model; frozen Python versus LAMMPS interface only"})
site = save("site.json", {"ssh": {"alias": "v100"}, "workspace": {"local": str(root / "system"), "remote_root": str(root / "system")},
    "runner": {"selected": "slurm", "slurm": {"default_partition": "gpu"}},
    "lammps": {"binary": "/home/v100/dpa4/releases/3.2.0/bin/lmp", "version": "LAMMPS (22 Jul 2025 - Update 2)",
               "environment_script": str(project / "workspace/configs/deepmd-lammps-env-v001.sh"),
               "launch_prefix": [], "launch_arguments": []}})
request = save("request.json", {"task_id": "p9-deepmd-lammps-public-v001", "required_results": [],
    "resource_request": {"nodes": 1, "ntasks": 1, "partition": "gpu", "account": "v100", "cpus_per_task": 2,
                         "gres": "gpu:v100:1", "mem_mib": 8192, "time": "00:10:00"}})
task = create_lammps_task(study_path=study, model_path=project / "workspace/models/ni-fcc-engineering/v001",
                         potential_path=potential, protocol_path=protocol, site_path=site, request_path=request)
print(json.dumps(task, indent=2))
