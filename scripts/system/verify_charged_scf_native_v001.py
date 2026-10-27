"""Accept the declared real charged-SCF experiment; run only in v100 Slurm.

Consumes the three native tasks, executes the selected bundle's public parse
and electronic entry points, and checks the predeclared E/F refinements.
It neither starts DFT nor changes any physical parameter or qualification.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=WORKSPACE / "configs/charged-scf-native-protocol-v001.json")
    args = parser.parse_args()
    bundle = args.bundle_root.resolve()
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = args.protocol.resolve()
    protocol = read(protocol_path)
    site = WORKSPACE / "configs/charged-scf-native-v001/site.v100-charged-native-v001.json"
    env = {**os.environ, "PYTHONPATH": str(bundle / "src")}
    report = {
        "schema": "mlcc.charged-scf-native-acceptance.v001",
        "verification_job_id": os.environ["SLURM_JOB_ID"],
        "bundle_root": str(bundle), "bundle_version": read(bundle / "bundle.json")["version"],
        "protocol": str(protocol_path), "passed": False,
        "checks": [], "tasks": [], "comparisons": [],
        "material_scientific_qualification": False, "production_qualification": False,
        "scope": protocol["acceptance"]["scope"],
        "excluded_qualifications": protocol["excluded_qualifications"],
    }

    def check(label, passed):
        report["checks"].append({"criterion": label, "passed": bool(passed)})
        if not passed:
            raise ValueError(f"charged SCF acceptance failed: {label}")

    def cli(name, *arguments):
        command = [sys.executable, "-m", "mlcc", *map(str, arguments)]
        result = subprocess.run(command, env=env, cwd=ROOT, capture_output=True, text=True)
        (report_dir / f"{name}.stdout").write_text(result.stdout, encoding="utf-8")
        (report_dir / f"{name}.stderr").write_text(result.stderr, encoding="utf-8")
        check(f"{name}: CLI exit zero", result.returncode == 0)
        return result

    results = {}
    try:
        import mlcc
        report["import_file"] = str(Path(mlcc.__file__).resolve())
        check("import uses requested bundle", Path(mlcc.__file__).resolve().is_relative_to(bundle / "src"))
        for point in protocol["planned_points"]:
            task_id = point["task_id"]
            directory = WORKSPACE / "tasks" / task_id
            task_path = directory / "task.json"
            task, method = read(task_path), read(directory / "method.json")
            # Refresh and retain the actual native scheduler state without a
            # new submission or a guessed completion flag.
            raw = subprocess.run(["scontrol", "show", "job", str(task["scheduler_job_id"])],
                                 capture_output=True, text=True, check=True).stdout
            (report_dir / f"{task_id}-scheduler.txt").write_text(raw, encoding="utf-8")
            check(f"{task_id}: native scheduler completed", "JobState=COMPLETED" in raw and "ExitCode=0:0" in raw)
            check(f"{task_id}: unlimited GPU allocation", "TimeLimit=UNLIMITED" in raw and "Partition=gpu" in raw)
            check(f"{task_id}: saved scheduler evidence", task["scheduler_state"] == "COMPLETED" and task["exit_code"] == "0:0")
            check(f"{task_id}: declared numerical point", method["parameters"]["ecutwfc_Ry"] == point["ecutwfc_Ry"] and method["kpoints"] == point["kpoints"])
            check(f"{task_id}: unchanged SCF controls", method["parameters"]["scf_thr"] == protocol["method"]["scf_thr"] and method["parameters"]["scf_nmax"] == protocol["method"]["scf_nmax"])
            stdout = (directory / "stdout.log").read_text(encoding="utf-8")
            native_dir = directory / f"OUT.{method['suffix']}"
            log = (native_dir / "running_scf.log").read_text(encoding="utf-8")
            check(f"{task_id}: actual GPU", "RUNNING WITH DEVICE  : GPU" in stdout)
            density = [float(value.replace("D", "E")) for value in re.findall(rf"Density error is\s+({FLOAT})", log)]
            iterations = [int(value) for value in re.findall(r"PW ALGORITHM.*ION=\s*1\s+ELEC=\s*(\d+)", log)]
            check(f"{task_id}: native convergence", "charge density convergence is achieved" in log and "convergence has not been achieved" not in log)
            check(f"{task_id}: final density residual", bool(density) and density[-1] <= protocol["method"]["scf_thr"])
            check(f"{task_id}: iterations not exhausted", bool(iterations) and iterations[-1] < protocol["method"]["scf_nmax"])
            # The expanded INPUT is evidence of what the engine actually used.
            echo = dict(line.split()[:2] for line in (native_dir / "INPUT").read_text().splitlines()
                        if len(line.split()) >= 2 and not line.lstrip().startswith("#"))
            check(f"{task_id}: native charge echo", float(echo["nelec_delta"]) == -2 and float(echo["nspin"]) == 1)
            check(f"{task_id}: native method echo", echo["smearing_method"] == "fixed" and float(echo["scf_thr"]) == 1e-8 and float(echo["ecutwfc"]) == point["ecutwfc_Ry"])
            cli(f"{task_id}-parse", "parse-abacus", "--task", task_path, "--site", site)
            result = read(directory / "result.json")
            evidence = result["electron_count_evidence"]
            check(f"{task_id}: raw charged status", result["scientific_status"] == "raw_charged_scf_unqualified" and result["net_charge"] == 2 and result["nelec_delta"] == -2)
            check(f"{task_id}: no material qualification", result["scientific_qualification"] is False and result["production_qualification"] is False)
            tol = protocol["acceptance"]["electron_count_absolute_tolerance"]
            check(f"{task_id}: neutral electron count", evidence["electron_count_native_log_neutral"] == 154)
            check(f"{task_id}: target/occupation electron counts", evidence["electron_count_native_log_target"] == 152 and abs(evidence["electron_count_native"] - 152) <= tol)
            electronic_path = report_dir / f"{task_id}-electronic.json"
            cli(f"{task_id}-electronic", "electronic", "--task", directory, "--output", electronic_path)
            electronic = read(electronic_path)
            check(f"{task_id}: public electron evidence", electronic["electron_count_match"] is True and electronic["electron_count_net_charge"] == 2)
            check(f"{task_id}: finite energy/forces", np.isfinite(result["energy_eV"]) and np.isfinite(result["forces_eV_per_A"]).all())
            check(f"{task_id}: actual composition", result["final_atoms"]["symbols"].count("O") == 11 and len(result["final_atoms"]["symbols"]) == 19)
            write(report_dir / f"{task_id}-result.json", result)
            report["tasks"].append({"task_id": task_id, "job_id": task["scheduler_job_id"],
                "state": "COMPLETED", "exit_code": "0:0", "iterations": iterations[-1],
                "final_density_error": density[-1], "energy_eV": result["energy_eV"],
                "electron_count_evidence": evidence})
            results[task_id] = result

        # A copied, deliberately corrupted file is solely a rejection check;
        # it never becomes a scientific positive or changes original evidence.
        from mlcc.electronic import validate_charged_scf_electrons
        source = WORKSPACE / "tasks" / "p4-czo-vo8-q2-ecut120-k333-v001"
        negative = report_dir / "rejection-only-rounded-weight"
        shutil.copytree(source, negative)
        negative_method = read(negative / "method.json")
        negative_result = read(negative / "result.json")
        negative_result["source_files"] = {
            key: value.replace(str(source), str(negative))
            for key, value in negative_result["source_files"].items()
        }
        negative_kpoints = negative / f"OUT.{negative_method['suffix']}" / "kpoints"
        negative_text = negative_kpoints.read_text()
        check("negative probe uses actual 333 printed weights", "0.0370" in negative_text)
        negative_kpoints.write_text(negative_text.replace("0.0370", "0.0372", 1))
        rejected = False
        try:
            validate_charged_scf_electrons(negative, negative_method, negative_result)
        except ValueError as error:
            report["rounded_weight_rejection"] = str(error)
            rejected = "weight" in str(error)
        check("weight outside native print interval is rejected", rejected)

        for name in ("cutoff_pair", "kpoint_pair"):
            first, second = protocol["acceptance"][name]
            a, b = results[first], results[second]
            check(f"{name}: same atoms and energy definition", a["final_atoms"] == b["final_atoms"] and a["energy_definition"] == b["energy_definition"])
            natom = len(a["final_atoms"]["symbols"])
            delta_e = abs(a["energy_eV"] - b["energy_eV"]) / natom
            delta_f = float(np.linalg.norm(np.asarray(a["forces_eV_per_A"]) - np.asarray(b["forces_eV_per_A"]), axis=1).max())
            report["comparisons"].append({"name": name, "tasks": [first, second], "energy_change_eV_per_atom": delta_e, "max_atomic_force_change_eV_per_A": delta_f})
            check(f"{name}: energy refinement criterion", delta_e <= protocol["acceptance"]["energy_change_eV_per_atom_max"])
            check(f"{name}: force refinement criterion", delta_f <= protocol["acceptance"]["max_atomic_force_vector_change_eV_per_A"])
        report["passed"] = True
    finally:
        write(report_dir / "acceptance.json", report)
    print(json.dumps({"passed": report["passed"], "tasks": len(report["tasks"]), "report": str(report_dir / "acceptance.json")}))


if __name__ == "__main__":
    main()
