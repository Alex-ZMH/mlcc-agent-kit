"""Read-only acceptance of one real Ni LAMMPS run-0 fixture against declared criteria."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mlcc-agent/src"))

from mlcc.lammps import parse_lammps_outputs
from mlcc.modeling import read_model_artifacts
from mlcc.tasks import load_task


def verify_lammps_run0(task_path: Path, criteria_path: Path) -> dict:
    task = load_task(task_path)
    criteria = json.loads(criteria_path.read_text(encoding="utf-8"))
    result = parse_lammps_outputs(task_path.resolve().parent)
    model = read_model_artifacts(task.data["model_path"])
    forces = np.asarray(result["forces_eV_per_A"])
    positions = np.asarray(result["positions_angstrom"])
    cell = np.asarray(result["cell_angstrom"])
    fractional_delta = (positions - model.atoms.positions) @ np.linalg.inv(cell)
    fractional_delta -= np.round(fractional_delta)
    max_position_delta = float(np.linalg.norm(fractional_delta @ cell, axis=1).max())
    energy_per_atom = result["energy_eV"] / len(model.atoms)
    energy_error = abs(energy_per_atom - criteria["expected_energy_near_eV_per_atom"])
    net_force = float(np.linalg.norm(forces.sum(axis=0)))
    symbols = model.atoms.get_chemical_symbols()
    composition = {element: symbols.count(element) for element in set(symbols)}
    checks = {
        "task_identity": task.task_id == criteria["task"],
        "scheduler_completed": task.data["scheduler_state"] == "COMPLETED" and task.data["exit_code"] == "0:0",
        "native_version": result["engine_version"] == task.data["engine_version"],
        "run_zero": result["protocol"]["kind"] == "run0" and result["step"] == criteria["run_steps"] == 0,
        "explicit_method_units": result["units"] == "metal" and result["atom_style"] == "atomic",
        "atom_ids": result["atom_ids"] == model.atom_ids,
        "composition": composition == criteria["composition"] and len(model.atoms) == criteria["atom_count"],
        "source_cell": bool(np.allclose(cell, model.atoms.cell.array, rtol=0, atol=1e-10)),
        "run0_fixed_geometry": max_position_delta <= criteria["run0_geometry_MIC_tolerance_A"],
        "finite_energy_forces": bool(np.isfinite(result["energy_eV"]) and np.isfinite(forces).all()),
        "force_balance": net_force <= criteria["net_force_norm_tolerance_eV_per_A"],
        "loose_energy_reference": energy_error <= criteria["energy_tolerance_eV_per_atom"],
        "native_sources_exist": all(Path(value).is_file() for value in result["source_files"].values()),
        "fixture_scope": task.data["fixture"] is True and task.data["production_label"] is False and result["production_qualification"] is False,
    }
    return {
        "scope": "Ni_static_LAMMPS_engineering_wiring_only",
        "passed": all(checks.values()),
        "checks": checks,
        "task_id": task.task_id,
        "scheduler_job_id": task.scheduler_job_id,
        "scheduler_state": task.data["scheduler_state"],
        "exit_code": task.data["exit_code"],
        "engine_version": result["engine_version"],
        "energy_eV": result["energy_eV"],
        "energy_eV_per_atom": energy_per_atom,
        "reference_energy_error_eV_per_atom": energy_error,
        "net_force_norm_eV_per_A": net_force,
        "max_force_eV_per_A": float(np.linalg.norm(forces, axis=1).max()),
        "max_position_MIC_delta_A": max_position_delta,
        "pressure_GPa": result["pressure_GPa"],
        "criteria_file": str(criteria_path.resolve()),
        "criteria": criteria,
        "source_files": result["source_files"],
        "potential": result["potential"],
        "production_qualification": False,
        "MD_sampling_qualification": False,
        "not_validated": ["MD_dynamics", "thermal_equilibration", "ceramics", "ferroelectricity", "interfaces", "polymer_branches"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--criteria", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = verify_lammps_run0(args.task, args.criteria)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "job_id": report["scheduler_job_id"], "report": str(args.report)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
