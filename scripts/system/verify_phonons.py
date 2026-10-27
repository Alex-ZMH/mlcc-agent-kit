"""Verify phonon software against saved models and native forces, without jobs."""
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
    report = args.report_dir.resolve()
    report.mkdir(parents=True)
    bundle = args.bundle_root.resolve()
    env = dict(os.environ, PYTHONPATH=str(bundle / "src"))
    sys.path.insert(0, str(bundle / "src"))
    import numpy as np
    from ase.io import read
    from mlcc.phonon_forces import load_native_force_task
    from mlcc.phonons import load_phonon_displacement_plan
    from mlcc.modeling import read_model_artifacts

    workspace = ROOT / "workspace"
    czo_model = workspace / "models/cazro3-pnma-pristine/v001"
    ni_model = workspace / "models/ni-fcc-engineering/v001"
    native_task = workspace / "tasks/p4-czo-compatibility-scf-v001"
    source_paths = [czo_model / "model.json", ni_model / "model.json",
                    native_task / "task.json", native_task / "result.json"]
    originals = {p: p.read_text(encoding="utf-8") for p in source_paths}
    commands = []

    def write(name, value):
        path = report / name
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        return path

    def run(name, arguments, expected=0):
        command = [sys.executable, "-m", "mlcc.cli", *map(str, arguments)]
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                   encoding="utf-8", capture_output=True)
        (report / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (report / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        commands.append({"command": command, "exit_code": completed.returncode, "expected": expected})
        assert completed.returncode == expected, completed.stderr

    request = {
        "plan_id": "czo-phonon-input-acceptance", "version": "v001",
        "phonopy_version": "4.8.3", "repeat_matrix": np.eye(3, dtype=int).tolist(),
        "primitive_matrix": np.eye(3).tolist(), "distance_angstrom": 0.01,
        "symprec": 1e-5, "is_symmetry": True, "hermitianize_dynamical_matrix": False,
    }
    czo_request = write("czo-plan-request.json", request)
    run("czo-plan", ["phonon-plan", "--model", czo_model, "--request", czo_request,
                     "--output", report / "czo-plan"])
    czo_plan_path = report / "czo-plan/displacement-manifest.json"
    czo_plan = load_phonon_displacement_plan(czo_plan_path)
    ni_request = write("ni-plan-request.json", {**request, "plan_id": "ni-phonon-input-acceptance"})
    run("ni-plan", ["phonon-plan", "--model", ni_model, "--request", ni_request,
                    "--output", report / "ni-plan"])
    plan_path = report / "ni-plan/displacement-manifest.json"
    plan = load_phonon_displacement_plan(plan_path)

    # All geometries are input-only engineering fixtures. No scheduler call.
    input_workspace = report / "input-workspace"
    (input_workspace / "tasks").mkdir(parents=True)
    site = json.loads((workspace / "configs/site.v100.json").read_text(encoding="utf-8"))
    site["workspace"]["local"] = str(input_workspace)
    site_path = write("site-input-only.json", site)
    ni_parent = read_model_artifacts(ni_model)
    parent_study = json.loads((workspace / "configs/cases/ni-engineering-v001.json").read_text(encoding="utf-8"))
    parent_study["study_id"] = "ni-phonon-input-acceptance-study-v001"
    parent_study["model"]["phase_requested"] = ni_parent.metadata["phase_requested"]
    parent_study["model"]["dopants"] = ni_parent.metadata.get("dopants", [])
    parent_study["derived_from"] = {"study_id": "ni-engineering-qualification-v001",
                                   "reason": "bind actual engineering model phase label for input acceptance"}
    parent_study_path = write("parent-engineering-study.json", parent_study)
    resources = json.loads((workspace / "configs/czo-compatibility-request-v001.json").read_text(encoding="utf-8"))["resource_request"]
    input_records = []
    for index, entry in enumerate([plan["reference"], plan["displacements"][0]]):
        task_id = f"ni-phonon-input-only-{index}"
        task_request = write(f"task-request-{index}.json", {
            "displacement_id": entry["entry_id"],
            "child_model_id": f"ni-phonon-input-model-{index}", "child_model_version": "v001",
            "child_study_id": f"ni-phonon-input-study-{index}", "task_id": task_id,
            "resource_request": resources, "required_results": [],
        })
        run(f"create-{index}", ["create-phonon", "--plan", plan_path,
            "--study", parent_study_path,
            "--method", workspace / "configs/h1-abacus-method-v003.json",
            "--site", site_path, "--request", task_request, "--output", report / f"child-{index}"])
        directory = input_workspace / "tasks" / task_id
        record = json.loads((directory / "task.json").read_text(encoding="utf-8"))
        actual = read(directory / "input.extxyz")
        expected = read(plan_path.parent / entry["structure_file"])
        input_records.append((record, actual, expected, directory))

    thresholds = write("thresholds.json", {
        "force_match_tolerance_eV_per_A": 1e-9,
        "reference_force_tolerance_eV_per_A": 0.01,
        "force_drift_tolerance_eV_per_A": 0.01,
        "geometry_tolerance_A": 1e-7,
        "displacement_tolerance_A": 1e-7,
    })
    run("missing-forces", ["phonon-forces", "--plan", plan_path, "--tasks",
        "--thresholds", thresholds, "--output", report / "missing-forces.json"], expected=1)
    qpoints = write("qpoints.json", [[0, 0, 0]])
    run("blocked-qpoints", ["phonon-qpoints", "--plan", plan_path, "--tasks",
        "--thresholds", thresholds, "--qpoints", qpoints,
        "--output", report / "blocked-qpoints.json"], expected=1)
    run("existing-plan", ["phonon-plan", "--model", ni_model, "--request", ni_request,
                          "--output", report / "ni-plan"], expected=1)
    blocked = json.loads((report / "blocked-qpoints.json").read_text(encoding="utf-8"))
    native = load_native_force_task(native_task)
    native_array = np.asarray(native["native_forces_eV_per_A"])
    saved_array = np.asarray(native["result_forces_eV_per_A"])
    czo_parent = read_model_artifacts(czo_model)
    checks = {
        "czo_phase_and_parent_retained": czo_plan["source_model"]["model_id"] == czo_parent.model_id
            and czo_plan["source_model"]["phase_requested"] == czo_parent.metadata["phase_requested"],
        "explicit_plus_minus": plan["request"]["is_plusminus"] is True,
        "length_units_angstrom": plan["request"]["distance_unit"] == "angstrom",
        "new_child_model_identities": all(t[0]["model_id"] != "ni-fcc-engineering" for t in input_records),
        "parent_study_provenance": all(t[0]["phonon_displacement"]["parent_study_id"] == parent_study["study_id"] for t in input_records),
        "native_input_geometry": all(np.allclose(t[1].positions, t[2].positions, rtol=0, atol=1e-8)
            and np.allclose(t[1].cell, t[2].cell, rtol=0, atol=1e-8) for t in input_records),
        "stable_atom_ids": all(t[1].arrays["atom_id"].tolist() == t[2].arrays["atom_id"].tolist() for t in input_records),
        "fixed_scf_inputs": all(t[0]["calculation"] == "scf" and t[0]["stage"] == "P7" for t in input_records),
        "no_job_submitted": all(t[0]["scheduler_job_id"] is None for t in input_records),
        "static_reference_not_firing_temperature": all(t[0]["calculation_conditions"]["lattice_temperature_K"] is None for t in input_records),
        "missing_forces_block_harmonic": blocked["ready_for_harmonic"] is False and blocked["force_bundle"] is None,
        "no_fake_frequencies": "frequencies_THz" not in blocked,
        "native_Ca_force_parser_regression": native_array.shape == (20, 3) and np.allclose(native_array, saved_array, rtol=0, atol=1e-12),
        "original_evidence_preserved": all(p.read_text(encoding="utf-8") == text for p, text in originals.items()),
    }
    checks = {key: bool(value) for key, value in checks.items()}
    acceptance = {"passed": all(checks.values()), "checks": checks, "commands": commands,
        "new_numerical_jobs": [], "native_source_job": "40",
        "complete_native_phonon_force_set": False, "phonon_scientific_qualification": False,
        "temperature_matrix_started": False}
    write("acceptance.json", acceptance)
    print(json.dumps({"passed": acceptance["passed"], "checks": len(checks), "report": str(report)}))
    return 0 if acceptance["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
