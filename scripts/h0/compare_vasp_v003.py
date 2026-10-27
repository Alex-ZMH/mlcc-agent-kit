"""Evaluate fixed H0 VASP fixture records; never start a calculation."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
METHOD_PATH = WORKSPACE / "configs" / "h0-vasp-method-v003.json"
REPORT_ROOT = WORKSPACE / "reports" / "h0"
OUTPUTS = {
    "cutoff": REPORT_ROOT / "vasp-comparison-v003-cutoff.json",
    "stress": REPORT_ROOT / "vasp-comparison-v003-stress.json",
    "all": REPORT_ROOT / "vasp-comparison-v003.json",
}
ELECTRONIC = (1, 0.2, 2, "Normal", "Accurate", 1e-7)
def load_case(task_id, cutoff, job_id=None):
    directory = WORKSPACE / "tasks" / task_id
    task_path, method_path, result_path = (directory / name for name in ("task.json", "method.json", "result.json"))
    task = json.loads(task_path.read_text(encoding="utf-8"))
    method = json.loads(method_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert task["task_id"] == task_id
    assert task["status"] == task["scheduler_state"] == "COMPLETED"
    assert task["exit_code"] == "0:0"
    assert task["engine"] == method["engine"] == "vasp"
    assert result["task_id"] == task_id
    assert str(result["scheduler_job_id"]) == str(task["scheduler_job_id"])
    assert result["electronic_converged"] is True
    assert float(method["parameters"]["ENCUT"]) == cutoff
    assert method["kpoints"] == [9, 9, 9]
    parameters = method["parameters"]
    assert (parameters["ISMEAR"], parameters["SIGMA"], parameters["ISPIN"],
            parameters["ALGO"], parameters["PREC"], parameters["EDIFF"]) == ELECTRONIC
    if job_id is not None:
        assert str(task["scheduler_job_id"]) == job_id
    return {
        "task": task,
        "method": method,
        "result": result,
        "paths": {"task": str(task_path), "method": str(method_path), "result": str(result_path)},
    }
def max_difference(left, right):
    return float(np.abs(np.asarray(left) - np.asarray(right)).max())
def atom_count(*cases):
    counts = [len(case["result"]["final_atoms"]["symbols"]) for case in cases]
    assert counts and all(count == counts[0] for count in counts)
    return counts[0]
def parallel_400eV(method):
    single = load_case("h0-ni-single-v004", 400.0, "20")
    four = load_case("h0-ni-four-v004", 400.0, "21")
    n_atoms = atom_count(single, four)
    a, b = single["result"], four["result"]
    differences = {
        "energy_eV_per_atom": abs(float(b["e_fr_energy"]) - float(a["e_fr_energy"])) / n_atoms,
        "force_component_eV_per_A": max_difference(b["forces_eV_per_A"], a["forces_eV_per_A"]),
        "stress_component_GPa": max_difference(b["stress_tensile_positive_GPa"], a["stress_tensile_positive_GPa"]),
        "site_moment_muB": max(abs(float(x["tot"]) - float(y["tot"])) for x, y in zip(b["magnetization"], a["magnetization"])),
    }
    thresholds = method["predeclared_acceptance"]["single_vs_four"]
    return {
        "cutoff_eV": 400.0,
        "scope_note": "completed 400 eV single/four-GPU parallel consistency only",
        "source_tasks": [single["task"]["task_id"], four["task"]["task_id"]],
        "job_ids": [single["task"]["scheduler_job_id"], four["task"]["scheduler_job_id"]],
        "differences": differences,
        "thresholds": thresholds,
        "passed": all(differences[key] <= float(thresholds[key]) for key in differences),
    }
def cutoff_comparison(method):
    baseline = load_case("h0-ni-cutoff500-v004", 500.0, "24")
    current = load_case("h0-ni-cutoff600-v005", 600.0)
    n_atoms = atom_count(baseline, current)
    a, b = baseline["result"], current["result"]
    differences = {
        "energy_eV_per_atom": abs(float(b["e_fr_energy"]) - float(a["e_fr_energy"])) / n_atoms,
        "force_component_eV_per_A": max_difference(b["forces_eV_per_A"], a["forces_eV_per_A"]),
        "stress_component_GPa": max_difference(b["stress_tensile_positive_GPa"], a["stress_tensile_positive_GPa"]),
    }
    thresholds = method["predeclared_acceptance"]["cutoff_500_vs_600"]
    return {
        "baseline": {"task_id": baseline["task"]["task_id"], "job_id": baseline["task"]["scheduler_job_id"], "cutoff_eV": 500.0, "paths": baseline["paths"]},
        "comparison": {"task_id": current["task"]["task_id"], "job_id": current["task"]["scheduler_job_id"], "cutoff_eV": 600.0, "paths": current["paths"]},
        "differences": differences,
        "thresholds": thresholds,
        "passed": all(differences[key] <= float(thresholds[key]) for key in differences),
    }
def stress_comparison(method):
    baseline = load_case("h0-ni-cutoff500-v004", 500.0, "24")
    minus = load_case("h0-ni-strainminus-v005", 500.0)
    plus = load_case("h0-ni-strainplus-v005", 500.0)
    atom_count(baseline, minus, plus)
    strain = float(method["predeclared_acceptance"]["isotropic_strain"]["linear_strain"])
    baseline_result = baseline["result"]
    baseline_cell = np.asarray(baseline_result["final_atoms"]["cell_angstrom"])
    minus_cell = np.asarray(minus["result"]["final_atoms"]["cell_angstrom"])
    plus_cell = np.asarray(plus["result"]["final_atoms"]["cell_angstrom"])
    assert np.allclose(minus_cell, baseline_cell * (1.0 - strain), rtol=0.0, atol=1e-9)
    assert np.allclose(plus_cell, baseline_cell * (1.0 + strain), rtol=0.0, atol=1e-9)
    volume_A3 = abs(float(np.linalg.det(baseline_cell)))
    derivative_trace = (float(plus["result"]["e_fr_energy"]) - float(minus["result"]["e_fr_energy"])) / (2.0 * strain * volume_A3) * 160.21766208
    reported_trace = float(np.trace(np.asarray(baseline_result["stress_tensile_positive_GPa"])))
    trace_error = abs(derivative_trace - reported_trace)
    threshold = float(method["predeclared_acceptance"]["isotropic_strain"]["trace_stress_difference_GPa"])
    return {
        "baseline": {"task_id": baseline["task"]["task_id"], "job_id": baseline["task"]["scheduler_job_id"], "cutoff_eV": 500.0, "free_energy_eV": baseline_result["e_fr_energy"], "stress_trace_GPa": reported_trace, "cell_volume_A3": volume_A3, "paths": baseline["paths"]},
        "strainminus": {"task_id": minus["task"]["task_id"], "job_id": minus["task"]["scheduler_job_id"], "cutoff_eV": 500.0, "linear_strain": -strain, "free_energy_eV": minus["result"]["e_fr_energy"], "cell_scale": 1.0 - strain, "paths": minus["paths"]},
        "strainplus": {"task_id": plus["task"]["task_id"], "job_id": plus["task"]["scheduler_job_id"], "cutoff_eV": 500.0, "linear_strain": strain, "free_energy_eV": plus["result"]["e_fr_energy"], "cell_scale": 1.0 + strain, "paths": plus["paths"]},
        "energy_for_derivative": method["predeclared_acceptance"]["isotropic_strain"]["energy_for_derivative"],
        "energy_derivative_trace_GPa": derivative_trace,
        "reported_tensile_trace_GPa": reported_trace,
        "absolute_difference_GPa": trace_error,
        "threshold_GPa": threshold,
        "passed": trace_error <= threshold,
    }
def relax_comparison(method):
    relax = load_case("h0-ni-relax-v005", 500.0)
    post = load_case("h0-ni-post-relax-v005", 500.0)
    atom_count(relax, post)
    threshold = float(method["predeclared_acceptance"]["fixed_cell_relax_max_force_eV_per_A"])
    max_force = max(float(relax["result"]["max_force_eV_per_A"]), float(post["result"]["max_force_eV_per_A"]))
    return {
        "relax": {"task_id": relax["task"]["task_id"], "job_id": relax["task"]["scheduler_job_id"], "max_force_eV_per_A": relax["result"]["max_force_eV_per_A"], "ionic_converged": relax["result"]["ionic_converged"], "paths": relax["paths"]},
        "post_relax_scf": {"task_id": post["task"]["task_id"], "job_id": post["task"]["scheduler_job_id"], "max_force_eV_per_A": post["result"]["max_force_eV_per_A"], "paths": post["paths"]},
        "max_force_eV_per_A": max_force,
        "threshold_eV_per_A": threshold,
        "ionic_converged": relax["result"]["ionic_converged"],
        "passed": relax["result"]["ionic_converged"] is True and max_force <= threshold,
    }
def evaluate(scope):
    method = json.loads(METHOD_PATH.read_text(encoding="utf-8"))
    report = {"schema": "mlcc.vasp-comparison.v003", "scope": scope, "method_set": method["method_set"], "method_config": str(METHOD_PATH), "fixture": True, "production_qualification": False, "parallel_400eV": parallel_400eV(method), "comparisons": {}}
    if scope in ("cutoff", "all"):
        report["comparisons"]["cutoff_500_vs_600"] = cutoff_comparison(method)
    if scope in ("stress", "all"):
        report["comparisons"]["stress_sign_finite_strain_500"] = stress_comparison(method)
    if scope == "all":
        report["comparisons"]["relax_to_post_relax_scf_500"] = relax_comparison(method)
    report["passed"] = report["parallel_400eV"]["passed"] and all(item["passed"] for item in report["comparisons"].values())
    return report
def write_report(scope, report):
    output = OUTPUTS[scope]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return output
parser = argparse.ArgumentParser(prog="compare_vasp_v003")
parser.add_argument("--scope", choices=("cutoff", "stress", "all"), default="all")
args = parser.parse_args()
report = evaluate(args.scope)
output = write_report(args.scope, report)
print(json.dumps(report, indent=2, ensure_ascii=False))
print(f"report={output}", file=sys.stderr)
raise SystemExit(0 if report["passed"] else 1)
