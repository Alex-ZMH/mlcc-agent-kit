"""Accept the one completed CZO non-SOC compatibility job, not production accuracy."""
import argparse
import json
from pathlib import Path
import re
import sys

import numpy as np
from ase.io import read

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.bundle_root.resolve() / "src"))
    from mlcc.method_tasks import qualify_abacus_configuration
    from mlcc.workflow import source_evidence

    directory = ROOT / "workspace/tasks/p4-czo-compatibility-scf-v001"
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    task = load(directory / "task.json")
    result = load(directory / "result.json")
    method = load(directory / "method.json")
    qualification = qualify_abacus_configuration(
        ROOT / "workspace/models/cazro3-pnma-pristine/v001",
        ROOT / "workspace/configs/cazro3-abacus-capability-v002.json",
        ROOT / "workspace/configs/site.v100.json")
    native = directory / "OUT.CZOCompat"
    log = (native / "running_scf.log").read_text(encoding="utf-8")
    stdout = (directory / "stdout.log").read_text(encoding="utf-8")
    stderr = (directory / "stderr.log").read_text(encoding="utf-8")
    echo = dict(line.split()[:2] for line in (native / "INPUT").read_text().splitlines()
                if len(line.split()) >= 2 and not line.lstrip().startswith('#'))
    numbers = re.findall(r"AUTOSET number of electrons:\s*=\s*([\d.Ee+-]+)", log)
    source = read(directory / "input.extxyz")
    final = read(directory / "final.extxyz")
    evidence, invalid, reason = source_evidence(result, directory / "result.json", engine="abacus")
    checks = {
        "input_qualification": qualification["input_qualified"],
        "COMPLETED_0": task["scheduler_state"] == "COMPLETED" and task["exit_code"] == "0:0",
        "native_version": bool(re.search(r"ABACUS\s+v?3\.10\.1\b", stdout)),
        "identity": result["task_id"] == task["task_id"] and result["scheduler_job_id"] == task["scheduler_job_id"] and result["method_set"] == task["method_set"],
        "three_UPFs_loaded": all(f"Read in pseudopotential file is {name}" in log for name in ("Ca.upf", "Zr_ONCV_PBE-1.0.upf", "O.upf")),
        "three_NC_headers": len(re.findall(r"pseudopotential type\s*=\s*NC", log)) == 3,
        "nonlocal_setup": "Init Non-Local-Pseudopotential done." in log,
        "native_electrons_160": bool(numbers) and float(numbers[-1]) == 160,
        "native_non_SOC": echo["nspin"] == "1" and echo["lspinorb"].lower() in ("0", "false") and echo["noncolin"].lower() in ("0", "false"),
        "no_SOC_reader_error": all(token not in log + stdout + stderr for token in ("FR-USPP please use lspinorb", "no soc upf used for lspinorb calculation")),
        "electronic_converged": result["electronic_converged"] is True and "charge density convergence is achieved" in log,
        "finite_E_F_stress": all(np.isfinite(result[key]).all() for key in ("energy_eV", "forces_eV_per_A", "stress_GPa")),
        "atom_ids": source.arrays["atom_id"].tolist() == final.arrays["atom_id"].tolist() == result["atom_ids"],
        "fixed_SCF_geometry": source.get_chemical_symbols() == final.get_chemical_symbols() and np.allclose(source.cell, final.cell, rtol=0, atol=1e-8) and np.allclose(source.positions, final.positions, rtol=0, atol=1e-8),
        "source_evidence": reason == "complete" and not invalid,
        "original_Ca_retained": method["pseudopotential_treatment"]["Ca"] == "abacus_3.10.1_average_j" and qualification["pseudopotentials"]["Ca"]["has_so"] is True,
        "production_false": task["production_label"] is False and result["production_label"] is False,
    }
    report = {
        "passed": all(checks.values()), "checks": checks,
        "scope": "ABACUS_3.10.1_Ca_FR_NC_average_j_single_static_SCF_interface_compatibility",
        "task_id": task["task_id"], "job_id": task["scheduler_job_id"],
        "engine": "abacus", "engine_version": "3.10.1", "method_set": task["method_set"],
        "new_numerical_jobs": [], "source_job_ids": [task["scheduler_job_id"]], "read_only_verification": True,
        "source_files": [str(path) for path in evidence],
        "native_total_electrons": float(numbers[-1]) if numbers else None,
        "scf_iterations": result["scf_iterations"], "energy_eV": result["energy_eV"],
        "max_force_eV_per_A": result["max_force_eV_per_A"],
        "input_qualification": qualification,
        "average_j_evidence": "workspace/reports/method-qualification/ca-compatibility-investigation-v001.json",
        "source_note": "Versioned source establishes j-channel averaging; the native run proves this binary loads the selected files and reaches the requested SCF threshold. No dedicated average-completed log marker exists.",
        "production_qualification": False, "precision_qualification": False,
        "stress_qualification": False, "temperature_grid_calculated": False,
        "design_assessment": "not_assessed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({"passed": report["passed"], "job_id": task["scheduler_job_id"],
                      "failed_checks": [key for key, value in checks.items() if not value], "report": str(args.output)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
