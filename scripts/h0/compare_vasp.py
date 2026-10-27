"""Evaluate predeclared H0 tolerances using real parsed VASP results."""
import json
from pathlib import Path

import numpy as np

root = Path(__file__).resolve().parents[2]
workspace = root / "workspace"
method = json.loads((workspace / "configs/h0-vasp-method-v002.json").read_text())
limits = method["predeclared_acceptance"]


def result(case):
    path = workspace / f"tasks/h0-ni-{case}-v004/result.json"
    value = json.loads(path.read_text())
    assert value["electronic_converged"]
    return value


base = result("single")
comparisons = {}
for case, threshold in (
    ("four", limits["single_vs_four"]),
    ("cutoff500", limits["cutoff_400_vs_500"]),
):
    current = result(case)
    differences = {
        "energy_eV_per_atom": abs(current["e_fr_energy"] - base["e_fr_energy"]) / 4,
        "force_component_eV_per_A": float(np.abs(np.array(current["forces_eV_per_A"]) -
                                                          base["forces_eV_per_A"]).max()),
        "stress_component_GPa": float(np.abs(np.array(current["stress_tensile_positive_GPa"]) -
                                                      base["stress_tensile_positive_GPa"]).max()),
    }
    if case == "four":
        differences["site_moment_muB"] = max(
            abs(a["tot"] - b["tot"])
            for a, b in zip(current["magnetization"], base["magnetization"])
        )
    comparisons[case] = {
        "differences": differences,
        "thresholds": threshold,
        "passed": all(value <= threshold[key] for key, value in differences.items()),
        "source_tasks": [base["task_id"], current["task_id"]],
        "job_ids": [base["scheduler_job_id"], current["scheduler_job_id"]],
    }

minus = result("strainminus")
plus = result("strainplus")
cell = np.asarray(base["final_atoms"]["cell_angstrom"])
volume = abs(float(np.linalg.det(cell)))
strain = limits["isotropic_strain"]["linear_strain"]
derivative_trace = (plus["e_fr_energy"] - minus["e_fr_energy"]) / (2 * strain * volume) * 160.21766208
reported_trace = float(np.trace(base["stress_tensile_positive_GPa"]))
trace_error = abs(derivative_trace - reported_trace)
comparisons["stress_sign_finite_strain"] = {
    "energy_derivative_trace_GPa": derivative_trace,
    "reported_tensile_trace_GPa": reported_trace,
    "absolute_difference_GPa": trace_error,
    "threshold_GPa": limits["isotropic_strain"]["trace_stress_difference_GPa"],
    "passed": trace_error <= limits["isotropic_strain"]["trace_stress_difference_GPa"],
    "source_tasks": [minus["task_id"], base["task_id"], plus["task_id"]],
    "job_ids": [minus["scheduler_job_id"], base["scheduler_job_id"], plus["scheduler_job_id"]],
}
relax = result("relax")
post = result("post-relax")
comparisons["relax_to_scf"] = {
    "ionic_converged": relax["ionic_converged"],
    "relax_max_force_eV_per_A": relax["max_force_eV_per_A"],
    "scf_max_force_eV_per_A": post["max_force_eV_per_A"],
    "passed": relax["ionic_converged"] and
              max(relax["max_force_eV_per_A"], post["max_force_eV_per_A"]) <
              limits["fixed_cell_relax_max_force_eV_per_A"],
    "source_tasks": [relax["task_id"], post["task_id"]],
    "job_ids": [relax["scheduler_job_id"], post["scheduler_job_id"]],
}
report = {
    "method_set": method["method_set"], "fixture": True,
    "production_qualification": False, "comparisons": comparisons,
    "all_predeclared_checks_passed": all(value["passed"] for value in comparisons.values()),
}
output = workspace / "reports/h0/vasp-comparison.json"
output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
print(json.dumps(report, indent=2))
