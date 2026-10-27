"""Explicit H0 Ni task preparation, lifecycle actions and actual result parsing."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from ase.io import write

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "mlcc-agent/src"))
from mlcc.modeling import build_nickel_fcc_fixture, read_model_artifacts
from mlcc.site_runner import runner_for_task
from mlcc.tasks import load_task, save_task
from mlcc.vasp import VaspParameters, prepare_vasp, parse_vasp_outputs, minimum_product_kmesh

workspace = root / "workspace"
site_path = workspace / "configs/site.v100.json"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=["model", "create", "prepare", "transfer", "submit", "query", "collect", "parse"])
parser.add_argument("case", nargs="?", choices=["single", "four", "relax", "post-relax", "cutoff500", "cutoff600", "strainminus", "strainplus"])
parser.add_argument("--task-version", default="v004")
parser.add_argument("--method", type=Path, default=workspace / "configs/h0-vasp-method-v002.json")
args = parser.parse_args()
method_path = args.method
model_dir = workspace / "models/ni-fcc-engineering/v001"

if args.action == "model":
    model_dir.mkdir(parents=True)
    model = build_nickel_fcc_fixture(model_dir, displaced_atom_id=0, displacement_angstrom=0.03)
    print(json.dumps({"model_id": model.model_id, "atom_ids": model.atom_ids, "fixture": True}))
    raise SystemExit(0)

case = args.case
task_id = f"h0-ni-{case}-{args.task_version}"
task_dir = workspace / "tasks" / task_id
task_path = task_dir / "task.json"

if args.action == "create":
    task_dir.mkdir()
    method = json.loads(method_path.read_text(encoding="utf-8"))
    model = read_model_artifacts(model_dir)
    parameters = method["parameters"].copy()
    ranks = 1 if case == "single" else 4
    parameters["kpar"] = ranks
    stage = "relax" if case == "relax" else "scf"
    depends_on = ["h0-mpi-one-v001", "h0-mpi-four-v001", "h0-runner-echo-v001"]
    if case == "relax":
        parameters.update(nsw=40, ibrion=2)
    if case == "post-relax":
        parent = workspace / f"tasks/h0-ni-relax-{args.task_version}"
        parent_task = load_task(parent / "task.json")
        assert parent_task.data["scheduler_state"] == "COMPLETED"
        assert parent_task.data["exit_code"] == "0:0"
        relaxed = parse_vasp_outputs(parent, stage="relax")
        assert relaxed.electronic_converged and relaxed.ionic_converged
        assert np.linalg.norm(relaxed.forces_eV_per_A, axis=1).max() < 0.02
        model.atoms = relaxed.final_atoms
        depends_on = [f"h0-ni-relax-{args.task_version}"]
    if case == "cutoff500":
        parameters["encut_eV"] = 500.0
    if case == "cutoff600":
        parameters["encut_eV"] = 600.0
    if case in ("strainminus", "strainplus"):
        strain = -0.005 if case == "strainminus" else 0.005
        model.atoms.set_cell(model.atoms.cell * (1 + strain), scale_atoms=True)
    parameters["kpoints"] = minimum_product_kmesh(model.atoms)
    prepared = prepare_vasp(
        model, task_dir, parameters=VaspParameters(**parameters),
        stage=stage, element_order=["Ni"],
    )
    task_method = json.loads((task_dir / "method.json").read_text())
    task_method.update(method_set=method["method_set"], fixture=True, potential=method["potential"],
                       acceptance_record=str(method_path), case=case)
    (task_dir / "method.json").write_text(json.dumps(task_method, indent=2) + "\n")
    # Licensed POTCAR is assembled only on the authorized server, inside this task.
    run_script = """#!/bin/bash
set -e
cp /home/v100/projects/mlcc/resources/vasp/PAW_PBE_52/Ni/POTCAR POTCAR
date --iso-8601=seconds
printf 'Slurm job=%s ranks=%s visible_gpus=%s\\n' "$SLURM_JOB_ID" "$SLURM_NTASKS" "$CUDA_VISIBLE_DEVICES"
nvidia-smi --query-gpu=index,uuid,pci.bus_id,name --format=csv > gpu-inventory.csv
mpirun --map-by slot --bind-to core --report-bindings /opt/vasp/vasp_std
"""
    (task_dir / "run-vasp.sh").write_text(run_script, encoding="utf-8", newline="\n")
    task = {
        "task_id": task_id, "stage": "P3", "engine": "vasp",
        "model_id": model.model_id, "model_version": model.version,
        "method_set": method["method_set"], "fixture": True,
        "depends_on": depends_on, "runner": "slurm", "scheduler_job_id": None,
        "command": ["/bin/bash", "run-vasp.sh"],
        "resource_request": {
            "nodes": 1, "partition": "gpu", "ntasks": ranks,
            "cpus_per_task": 1, "gpus_per_task": "v100:1", "hint": "nomultithread",
            "mem_mib": 8192, "time": "00:20:00" if case == "relax" else "00:10:00",
        },
        "transfer_paths": [*prepared.files, "run-vasp.sh"],
        "collect_paths": ["stdout.log", "stderr.log", "OUTCAR", "OSZICAR", "vasprun.xml", "CONTCAR", "gpu-inventory.csv"],
        "status": "defined", "scientific_status": "not_calculated",
    }
    if case == "post-relax":
        task["structure_source"] = f"workspace/tasks/h0-ni-relax-{args.task_version}/CONTCAR"
    task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    print(task_path)
elif args.action == "parse":
    task = load_task(task_path)
    assert task.data["scheduler_state"] == "COMPLETED"
    assert task.data["exit_code"] == "0:0"
    stage = "relax" if case == "relax" else "scf"
    result = parse_vasp_outputs(task_dir, stage=stage)
    data = result.as_dict()
    force_max = float(np.linalg.norm(result.forces_eV_per_A, axis=1).max())
    scientific_complete = result.electronic_converged and (
        stage == "scf" or (result.ionic_converged and force_max < 0.02)
    )
    data.update(task_id=task_id, scheduler_job_id=task.scheduler_job_id,
                method_set=task.data["method_set"], fixture=True,
                max_force_eV_per_A=force_max,
                scientific_status="converged_engineering_fixture" if scientific_complete else "not_converged")
    assert np.isfinite(np.asarray(result.forces_eV_per_A)).all()
    assert np.isfinite(np.asarray(result.stress_tensile_positive_GPa)).all()
    assert np.isfinite(result.e_fr_energy)
    (task_dir / "result.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write(task_dir / "final.extxyz", result.final_atoms)
    task.set(scientific_status=data["scientific_status"], result_file=str(task_dir / "result.json"))
    save_task(task)
    print(json.dumps({key: data[key] for key in ["task_id", "scheduler_job_id", "scientific_status",
                      "e_fr_energy", "e_0_energy", "max_force_eV_per_A", "electronic_converged", "ionic_converged"]}))
else:
    runner, task = runner_for_task(site_path, task_path)
    getattr(runner, args.action)(task)
    print(json.dumps({key: task.data[key] for key in ["task_id", "status", "scheduler_job_id"]}))
