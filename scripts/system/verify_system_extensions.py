"""Exercise the installed extension entry points using real saved models/tasks.

Only derived structures, native inputs and read-only reports are written. No
scientific output is fabricated and no numerical job is submitted.
"""
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
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True)
    bundle = args.bundle_root.resolve()
    env = dict(os.environ, PYTHONPATH=str(bundle / "src"))
    sys.path.insert(0, str(bundle / "src"))
    import numpy as np
    import mlcc.model_derivatives as derivation_module
    from mlcc.modeling import read_model_artifacts
    from ase.io import read

    workspace = ROOT / "workspace"
    czo_model = workspace / "models/cazro3-pnma-pristine/v001"
    ni_model = workspace / "models/ni-fcc-engineering/v001"
    czo_task = workspace / "tasks/p4-czo-compatibility-scf-v001"
    ni_task = workspace / "tasks/h1-ni-scf-v003"
    historical_paths = [czo_model / "model.json", ni_model / "model.json",
                        czo_task / "task.json", czo_task / "result.json",
                        ni_task / "task.json", ni_task / "result.json"]
    historical = {path: path.read_text(encoding="utf-8") for path in historical_paths}
    commands = []

    def write(name, value):
        path = report_dir / name
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        return path

    def run(name, arguments, expected=0):
        command = [sys.executable, "-m", "mlcc.cli", *map(str, arguments)]
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, encoding="utf-8", capture_output=True)
        (report_dir / f"{name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (report_dir / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        commands.append({"command": command, "exit_code": result.returncode, "expected": expected})
        assert result.returncode == expected, result.stderr
        return result

    super_request = write("supercell-request.json", {
        "model_id": "czo-supercell-input-acceptance", "version": "v001",
        "repeat_matrix": [[2, 1, 0], [0, 1, 0], [0, 0, 1]],
    })
    super_output = report_dir / "czo-supercell-model"
    run("supercell", ["derive-supercell", "--parent", czo_model, "--request", super_request,
                       "--output", super_output])
    child = read_model_artifacts(super_output)
    parent = read_model_artifacts(czo_model)
    lineage = json.loads((super_output / "atom-lineage.json").read_text(encoding="utf-8"))["entries"]
    max_position_error = 0.0
    for i, entry in enumerate(lineage):
        parent_index = parent.atom_ids.index(entry["parent_atom_id"])
        expected = (parent.atoms.get_scaled_positions(wrap=False)[parent_index]
                    + np.asarray(entry["parent_image"])) @ parent.atoms.cell.array
        max_position_error = max(max_position_error, float(np.max(np.abs(expected - child.atoms.positions[i]))))

    # The Ni vacancy is an explicitly named engineering input test, not a
    # selected CaZrO3/BaTiO3 material defect or a calculated defect result.
    study_id = "ni-derived-input-acceptance-v001"
    defect_request = write("ni-vacancy-request.json", {
        "model_id": "ni-vacancy-input-acceptance", "version": "v001", "study_id": study_id,
        "charge_state": 0, "operations": [{"kind": "vacancy", "atom_id": 0}],
    })
    defect_output = report_dir / "ni-vacancy-model"
    run("defect", ["derive-defect", "--parent", ni_model, "--request", defect_request,
                    "--output", defect_output])
    defect = read_model_artifacts(defect_output)
    study = json.loads((workspace / "configs/cases/ni-engineering-v001.json").read_text(encoding="utf-8"))
    study["study_id"] = study_id
    study["model"].update(model_id=defect.model_id, version=defect.version,
                           composition=defect.metadata["composition"])
    study_path = write("ni-derived-study.json", study)
    local_inputs = report_dir / "native-inputs"
    (local_inputs / "tasks").mkdir(parents=True)
    site = json.loads((workspace / "configs/site.v100.json").read_text(encoding="utf-8"))
    site["workspace"]["local"] = str(local_inputs)
    site_path = write("input-only-site.json", site)
    request = json.loads((workspace / "configs/czo-compatibility-request-v001.json").read_text(encoding="utf-8"))
    request.update(task_id="ni-vacancy-native-input-only", input_transformation=None, required_results=[])
    request_path = write("ni-native-request.json", request)
    native = run("defect-native", ["create-abacus", "--study", study_path, "--model", defect_output,
                  "--method", workspace / "configs/h1-abacus-method-v003.json",
                  "--site", site_path, "--request", request_path])
    task = json.loads(native.stdout)
    native_atoms = read(local_inputs / "tasks" / request["task_id"] / "input.extxyz")

    charged_request = json.loads(defect_request.read_text(encoding="utf-8"))
    charged_request.update(model_id="ni-charged-input-rejection", charge_state=1)
    charged_path = write("ni-charged-request.json", charged_request)
    charged_output = report_dir / "ni-charged-model"
    run("charged-model", ["derive-defect", "--parent", ni_model, "--request", charged_path,
                          "--output", charged_output])
    rejected = run("charged-native-rejected", ["create-abacus", "--study", study_path,
                   "--model", charged_output, "--method", workspace / "configs/h1-abacus-method-v003.json",
                   "--site", site_path, "--request", request_path], expected=1)

    thresholds = write("elastic-thresholds.json", {
        "fractional_tolerance": 1e-7, "strain_tolerance": 1e-8,
        "reference_stress_GPa": 1.0, "linearity_residual_GPa": 0.1,
        "condition_number_max": 100.0, "asymmetry_GPa": 1.0,
        "calibration_abs_error_GPa": 0.1, "calibration_relative_error": 0.05,
        "calibration_signal_min_GPa": 0.2, "calibration_fd_consistency_GPa": 0.1,
        "native_stress_asymmetry_GPa": 1e-6, "amplitude_slope_difference_GPa": 5.0,
    })
    calibration_path = report_dir / "ni-tensor-blocked.json"
    run("tensor-calibration", ["elastic-calibrate", "--reference-task", ni_task,
        "--strained-tasks", workspace / "tasks/h1-ni-strainminus-v004",
        workspace / "tasks/h1-ni-strainplus-v004", "--thresholds", thresholds,
        "--output", calibration_path], expected=1)
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    plan_path = report_dir / "czo-25-point-plan.json"
    run("tensor-plan", ["elastic-plan", "--model", czo_model, "--amplitudes", "0.005", "0.01",
                        "--output", plan_path])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    delivery_path = report_dir / "czo-property-delivery.json"
    run("property-delivery", ["deliver-properties", "--study",
        workspace / "configs/cases/cazro3-firing-v003.json", "--tasks", czo_task,
        "--output", delivery_path])
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    checks = {
        "installed_source_loaded": Path(derivation_module.__file__).resolve().is_relative_to(bundle),
        "exact_40_atom_supercell": len(child.atoms) == 40,
        "exact_determinant_volume": abs(child.atoms.get_volume() / parent.atoms.get_volume() - 2) < 1e-10,
        "parent_image_mapping": max_position_error < 1e-7,
        "supercell_unqualified": child.metadata["production_qualified"] is False,
        "explicit_vacancy_delta": defect.metadata["derivation"]["composition_delta"] == {"Ni": -1},
        "survivor_ids": defect.atom_ids == [1, 2, 3],
        "derived_model_native_input": native_atoms.arrays["atom_id"].tolist() == defect.atom_ids,
        "native_task_not_submitted": task["scheduler_job_id"] is None and task["scientific_status"] == "not_calculated",
        "charged_model_not_neutralized": "charged defect models" in rejected.stderr,
        "tensor_plan_25_points": len(plan["requests"]) + 1 == 25,
        "incomplete_tensor_native_evidence_blocked": calibration["status"] == "blocked" and not calibration["full_tensor_stress_calibration"],
        "calibration_not_production": calibration["production_qualification"] is False,
        "no_spec_not_assessed": delivery["design_assessment"] == "not_assessed",
        "native_properties_not_precision_qualified": delivery["scientific_status"] == "unqualified",
        "native_gap_delivered": any(item["observable_id"] == "sampled_mesh_KS_gap" and item["value"] is not None
                                    for item in delivery["observables"]),
        "historical_evidence_unchanged": all(path.read_text(encoding="utf-8") == value for path, value in historical.items()),
        "all_cli_exit_codes_expected": all(item["exit_code"] == item["expected"] for item in commands),
    }
    checks = {name: bool(value) for name, value in checks.items()}
    report = {
        "schema": "mlcc.system-extensions-acceptance.v001", "bundle_root": str(bundle),
        "passed": all(checks.values()), "checks": checks, "commands": commands,
        "max_supercell_position_error_angstrom": max_position_error,
        "property_delivery_file": str(delivery_path),
        "new_numerical_jobs": [], "temperature_matrix_started": False,
        "scientific_qualification": {"full_tensor_native_dataset": False, "neutral_defect_native_pair": False,
                                     "production_engine_switch": False, "H1_complete": False},
    }
    write("acceptance.json", report)
    print(json.dumps({"passed": report["passed"], "checks": len(checks), "report": str(report_dir / "acceptance.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
