"""Exercise installed electronic/elastic APIs on saved native tasks; submit no jobs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    directory = args.report_dir.resolve()
    directory.mkdir(parents=True)
    bundle = args.bundle_root.resolve()
    env = dict(os.environ, PYTHONPATH=str(bundle / "src"))
    workspace = ROOT / "workspace"
    task_dirs = {
        "czo": workspace / "tasks/p4-czo-compatibility-scf-v001",
        "ni": workspace / "tasks/h1-ni-scf-v003",
    }
    historical = {path: path.read_text(encoding="utf-8")
                  for task in task_dirs.values() for path in (task / "task.json", task / "result.json")}
    commands = []

    def run(name, arguments, expected=0):
        output = directory / f"{name}.json"
        command = [sys.executable, "-m", "mlcc.cli", *map(str, arguments), "--output", str(output)]
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True, encoding="utf-8", capture_output=True)
        (directory / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (directory / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        commands.append({"command": command, "exit_code": completed.returncode, "expected_exit_code": expected})
        assert completed.returncode == expected, completed.stderr
        return json.loads(output.read_text(encoding="utf-8"))

    electronic, dos = {}, {}
    for name, task in task_dirs.items():
        electronic[name] = run(f"{name}-electronic", ["electronic", "--task", task])
        levels = [energy for spin in electronic[name]["band_energies_eV"] for kpoint in spin for energy in kpoint]
        dos[name] = run(f"{name}-dos", ["electronic-dos", "--task", task,
                       "--emin", min(levels) - 2.0, "--emax", max(levels) + 2.0,
                       "--points", 4001, "--sigma", 0.2])
    model = workspace / "models/cazro3-pnma-pristine/v001"
    plan = run("czo-elastic-plan", ["elastic-plan", "--model", model, "--amplitudes", 0.005])
    thresholds = {"fractional_tolerance": 1e-7, "strain_tolerance": 1e-8,
                  "reference_stress_GPa": 1.0, "linearity_residual_GPa": 1.0,
                  "condition_number_max": 100.0, "asymmetry_GPa": 1.0}
    threshold_path = directory / "elastic-thresholds.json"
    threshold_path.write_text(json.dumps(thresholds, indent=2) + "\n", encoding="utf-8")
    analysis = run("ni-elastic-blocked", ["elastic-analyze", "--reference-task", task_dirs["ni"],
                   "--strained-tasks", workspace / "tasks/h1-ni-strainminus-v004",
                   workspace / "tasks/h1-ni-strainplus-v004", "--calibration",
                   workspace / "reports/h1/strain-quick-v004/comparison.json", "--thresholds", threshold_path], 1)

    sys.path.insert(0, str(bundle / "src"))
    from mlcc.abacus_tasks import create_abacus_task
    from mlcc.modeling import read_model_artifacts
    from ase.io import read
    import numpy as np
    local = directory / "native-inputs"
    (local / "tasks").mkdir(parents=True)
    site = json.loads((workspace / "configs/site.v100.json").read_text(encoding="utf-8"))
    site["workspace"]["local"] = str(local)
    site_path = directory / "site-input-only.json"
    site_path.write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
    request_template = json.loads((workspace / "configs/czo-compatibility-request-v001.json").read_text(encoding="utf-8"))
    original = read_model_artifacts(model).atoms
    generated = []
    for entry in [plan["reference"], *plan["requests"]]:
        request = dict(request_template, task_id=f"elastic-input-{entry['request_id']}",
                       input_transformation=entry["input_transformation"])
        request_path = directory / f"{request['task_id']}.request.json"
        request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        task = create_abacus_task(study_path=workspace / "configs/cases/cazro3-firing-v003.json",
                                 model_path=model, method_path=workspace / "configs/cazro3-abacus-capability-v002.json",
                                 site_path=site_path, request_path=request_path)
        prepared_dir = local / "tasks" / task["task_id"]
        atoms = read(prepared_dir / "input.extxyz")
        assert np.allclose(atoms.cell.array, entry["record"]["derived_lattice_angstrom"], atol=1e-7, rtol=0)
        assert np.allclose(atoms.get_scaled_positions(wrap=False), original.get_scaled_positions(wrap=False), atol=1e-7, rtol=0)
        assert atoms.arrays["atom_id"].tolist() == original.arrays["atom_id"].tolist()
        assert task["scheduler_job_id"] is None and task["status"] == "defined"
        assert task["method_input_qualified"] is True
        generated.append(task["task_id"])

    checks = {
        "CZO_fixed_160_electrons": electronic["czo"]["occupations"] == "fixed" and abs(electronic["czo"]["electron_count_native"] - 160) < 1e-5,
        "CZO_sampled_mesh_gap_only": electronic["czo"]["sampled_mesh_KS_gap_eV"] > 0 and not electronic["czo"]["gap_qualification"]["is_fundamental_gap"],
        "Ni_spin2_72_electrons": electronic["ni"]["nspin"] == 2 and abs(electronic["ni"]["electron_count_native"] - 72) < 1e-5,
        "Ni_smearing_no_gap": electronic["ni"]["sampled_mesh_KS_gap_eV"] is None,
        "DOS_CZO_states": abs(dos["czo"]["weighted_state_count"] - 176) < 1e-8,
        "DOS_Ni_states": abs(dos["ni"]["weighted_state_count"] - 112) < 1e-8,
        "DOS_integrals": all(abs(value["finite_grid_integral_relative_error"]) < 1e-5 for value in dos.values()),
        "six_directions_plus_minus": plan["request_count"] == 13 and len(plan["requests"]) == 12,
        "all_native_inputs_written_unsubmitted": len(generated) == 13,
        "failed_calibration_blocks_Cij": analysis["status"] == "blocked" and analysis["Cij"] is None,
        "isotropic_rank_one": analysis["fit"]["rank"] == 1,
        "no_production_claim": not analysis["production_qualification"],
        "historical_tasks_unchanged": all(path.read_text(encoding="utf-8") == old for path, old in historical.items()),
    }
    report = {"passed": all(checks.values()), "checks": checks, "commands": commands,
              "bundle_root": str(bundle), "source_jobs": ["37", "38", "39", "40"],
              "generated_local_input_tasks": generated, "new_numerical_jobs": [],
              "temperature_matrix_calculated": False, "production_qualification": False,
              "elastic_constant_qualification": False, "design_assessment": "not_assessed"}
    (directory / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": checks, "report": str(directory / "acceptance.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
