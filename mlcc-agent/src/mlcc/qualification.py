"""Direct same-geometry ABACUS 3.10.1 cutoff qualification."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
from ase.io import read

SCHEMA = "mlcc.abacus-cutoff-qualification.v001"
GEOMETRY_TOLERANCE_A = 1.0e-10


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _bundle(directory: str | Path) -> dict[str, Any]:
    directory = Path(directory)
    return {
        "directory": directory,
        "task": _json(directory / "task.json"),
        "method": _json(directory / "method.json"),
        "result": _json(directory / "result.json"),
        "input": _input_values(directory / "INPUT"),
        "atoms": read(directory / "input.extxyz"),
    }


def _input_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and not fields[0].startswith("#") and len(fields) >= 2:
            values[fields[0]] = fields[1]
    return values


def _check(value: Any, passed: bool) -> dict[str, Any]:
    return {"value": value, "passed": bool(passed)}


def _method_context(method: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(method)
    value.pop("case", None)
    value["parameters"].pop("ecutwfc_Ry", None)
    value["parameters"].pop("cal_force", None)
    value["parameters"].pop("cal_stress", None)
    return value


def _method_flags_valid(method: dict[str, Any]) -> bool:
    parameters = method["parameters"]
    return all(parameters[key] is True for key in ("cal_force", "cal_stress") if key in parameters)


def _finite(result: dict[str, Any]) -> bool:
    values = [result["energy_eV"], result["forces_eV_per_A"], result["stress_GPa"]]
    return all(bool(np.isfinite(np.asarray(value, dtype=float)).all()) for value in values)


def compare_cutoff_tasks(
    baseline_task: str | Path,
    comparison_task: str | Path,
    method: str | Path,
) -> dict[str, Any]:
    """Compare the fixed 100 Ry and 120 Ry ABACUS Ni SCF task records."""
    baseline, comparison = _bundle(baseline_task), _bundle(comparison_task)
    config = _json(Path(method))
    bt, ct = baseline["task"], comparison["task"]
    bm, cm = baseline["method"], comparison["method"]
    br, cr = baseline["result"], comparison["result"]
    ba, ca = baseline["atoms"], comparison["atoms"]
    bi, ci = baseline["input"], comparison["input"]
    thresholds = config["predeclared_engineering_thresholds"]

    native = {
        "baseline": {"scheduler_state": bt["scheduler_state"], "exit_code": bt["exit_code"]},
        "comparison": {"scheduler_state": ct["scheduler_state"], "exit_code": ct["exit_code"]},
    }
    native_ok = all(v["scheduler_state"] == "COMPLETED" and v["exit_code"] == "0:0" for v in native.values())
    electronic = {"baseline": br["electronic_converged"], "comparison": cr["electronic_converged"]}
    electronic_ok = all(v is True for v in electronic.values())

    engines = [bt["engine"], ct["engine"], bm["engine"], cm["engine"], config["engine"]]
    versions = [bt["engine_version"], ct["engine_version"], bm["abacus_version_target"], cm["abacus_version_target"], config["engine_version"]]
    same_engine = all(value == "abacus" for value in engines)
    same_version = all(value == "3.10.1" for value in versions)
    method_sets = [bt["method_set"], ct["method_set"], bm["method_set"], cm["method_set"], config["method_set"]]
    same_method_set = len(set(method_sets)) == 1

    same_pseudo = bm["pseudopotentials"] == cm["pseudopotentials"] and bm["potential"] == cm["potential"]
    same_spin = (bm["nspin"], bm["initial_magnetic_moment_muB_per_atom"]) == (cm["nspin"], cm["initial_magnetic_moment_muB_per_atom"])
    same_kmesh = (bm["kpoints"], bm["kpoint_rule"]) == (cm["kpoints"], cm["kpoint_rule"])
    same_smearing = (bm["smearing_method"], bm["parameters"]["smearing_sigma_Ry"]) == (cm["smearing_method"], cm["parameters"]["smearing_sigma_Ry"])
    same_nbands = bm["parameters"]["nbands"] == cm["parameters"]["nbands"]
    context_equal = _method_context(bm) == _method_context(cm)
    method_flags_valid = _method_flags_valid(bm) and _method_flags_valid(cm)
    native_context_equal = {k: v for k, v in bi.items() if k != "ecutwfc"} == {k: v for k, v in ci.items() if k != "ecutwfc"}

    ecut = {"baseline_Ry": bm["parameters"]["ecutwfc_Ry"], "comparison_Ry": cm["parameters"]["ecutwfc_Ry"]}
    configured_cutoff = (
        config["parameters"]["ecutwfc_Ry"] == ecut["baseline_Ry"]
        and config["parameters"]["cutoff_comparison_Ry"] == ecut["comparison_Ry"]
        and ecut == {"baseline_Ry": 100, "comparison_Ry": 120}
    )
    native_ecut = {"baseline_Ry": float(bi["ecutwfc"]), "comparison_Ry": float(ci["ecutwfc"])}
    native_flags = all(values[key] == "1" for values in (bi, ci) for key in ("cal_force", "cal_stress"))
    native_ecut_matches_method = native_ecut == {"baseline_Ry": float(ecut["baseline_Ry"]), "comparison_Ry": float(ecut["comparison_Ry"])}
    native_input_verified = native_context_equal and native_flags and native_ecut_matches_method

    base_ids, comp_ids = [int(x) for x in ba.arrays["atom_id"]], [int(x) for x in ca.arrays["atom_id"]]
    result_ids = {"baseline": [int(x) for x in br["atom_ids"]], "comparison": [int(x) for x in cr["atom_ids"]]}
    same_ids = base_ids == comp_ids == result_ids["baseline"] == result_ids["comparison"]
    same_symbols = ba.get_chemical_symbols() == ca.get_chemical_symbols()
    same_pbc = ba.pbc.tolist() == ca.pbc.tolist()
    cell_delta = float(np.max(np.abs(ba.cell.array - ca.cell.array))) if ba.cell.array.shape == ca.cell.array.shape else None
    position_delta = float(np.max(np.abs(ba.positions - ca.positions))) if ba.positions.shape == ca.positions.shape else None
    same_geometry = (same_symbols and same_pbc and cell_delta is not None and position_delta is not None and cell_delta <= GEOMETRY_TOLERANCE_A and position_delta <= GEOMETRY_TOLERANCE_A)

    result_identity = br["task_id"] == bt["task_id"] and cr["task_id"] == ct["task_id"]
    result_method_set = br["method_set"] == bt["method_set"] and cr["method_set"] == ct["method_set"]
    scf_stage = (bm["stage"], cm["stage"], br["stage"], cr["stage"]) == ("scf",) * 4
    energy_definition = br["energy_definition"] == cr["energy_definition"] and br["energy_default_definition"] == cr["energy_default_definition"]
    stress_sign = br["stress_sign"] == cr["stress_sign"]
    units = br["energy_unit"] == cr["energy_unit"] == "eV" and br["stress_unit"] == cr["stress_unit"] == "GPa"
    finite = _finite(br) and _finite(cr)
    bf, cf = np.asarray(br["forces_eV_per_A"], dtype=float), np.asarray(cr["forces_eV_per_A"], dtype=float)
    bs, cs = np.asarray(br["stress_GPa"], dtype=float), np.asarray(cr["stress_GPa"], dtype=float)
    shapes = bf.shape == cf.shape == (len(ba), 3) and bs.shape == cs.shape == (3, 3)

    comparable = all((native_ok, electronic_ok, same_engine, same_version, same_method_set, same_pseudo, same_spin, same_kmesh, same_smearing, same_nbands, context_equal, method_flags_valid, configured_cutoff, native_input_verified, same_ids, same_geometry, result_identity, result_method_set, scf_stage, energy_definition, stress_sign, units, finite, shapes))
    status = "computed" if comparable else "not_comparable"
    if comparable:
        energy_delta = abs(float(cr["energy_eV"]) - float(br["energy_eV"]))
        energy_per_atom = energy_delta / len(ba)
        force_delta = float(np.max(np.abs(cf - bf)))
        stress_delta = float(np.max(np.abs(cs - bs)))
    else:
        energy_delta = energy_per_atom = force_delta = stress_delta = None
    energy_ok = comparable and energy_per_atom <= thresholds["cutoff_energy_eV_per_atom"]
    force_ok = comparable and force_delta <= thresholds["cutoff_force_component_eV_per_A"]
    stress_ok = comparable and stress_delta <= thresholds["cutoff_stress_component_GPa"]

    checks = {
        "native_completed_0": _check(native, native_ok),
        "electronic_converged": _check(electronic, electronic_ok),
        "same_engine": _check(engines, same_engine),
        "same_engine_version": _check(versions, same_version),
        "same_method_set": _check(method_sets, same_method_set),
        "same_pseudopotential": _check({"baseline": bm["pseudopotentials"], "comparison": cm["pseudopotentials"]}, same_pseudo),
        "same_spin": _check({"baseline": [bm["nspin"], bm["initial_magnetic_moment_muB_per_atom"]], "comparison": [cm["nspin"], cm["initial_magnetic_moment_muB_per_atom"]]}, same_spin),
        "same_kmesh": _check({"baseline": bm["kpoints"], "comparison": cm["kpoints"]}, same_kmesh),
        "same_smearing": _check({"baseline": [bm["smearing_method"], bm["parameters"]["smearing_sigma_Ry"]], "comparison": [cm["smearing_method"], cm["parameters"]["smearing_sigma_Ry"]]}, same_smearing),
        "same_nbands": _check({"baseline": bm["parameters"]["nbands"], "comparison": cm["parameters"]["nbands"]}, same_nbands),
        "only_ecutwfc_changed": _check({"case_is_metadata": True, "method_context_equal": context_equal, "native_input_verified": native_input_verified}, context_equal and native_input_verified),
        "method_flags_valid": _check({"baseline": bm["parameters"].get("cal_force"), "comparison": cm["parameters"].get("cal_force"), "required": True}, method_flags_valid),
        "native_input_verified": _check({"baseline": bi, "comparison": ci, "ecut_matches_method": native_ecut_matches_method, "cal_force_cal_stress_are_1": native_flags, "non_ecut_context_equal": native_context_equal}, native_input_verified),
        "ecutwfc_100_to_120": _check({"method": ecut, "native_input": native_ecut}, configured_cutoff and native_input_verified),
        "same_atom_ids": _check({"input_baseline": base_ids, "input_comparison": comp_ids, "result": result_ids}, same_ids),
        "same_geometry": _check({"cell_delta_A": cell_delta, "position_delta_A": position_delta, "tolerance_A": GEOMETRY_TOLERANCE_A}, same_geometry),
        "result_identity": _check({"task_id_match": result_identity, "method_set_match": result_method_set}, result_identity and result_method_set),
        "same_stage": _check({"all_scf": scf_stage}, scf_stage),
        "units": _check({"energy": [br["energy_unit"], cr["energy_unit"]], "stress": [br["stress_unit"], cr["stress_unit"]]}, units),
        "finite_results": _check(finite, finite),
        "same_energy_definition": _check([br["energy_definition"], cr["energy_definition"]], energy_definition),
        "same_stress_sign": _check([br["stress_sign"], cr["stress_sign"]], stress_sign),
        "energy_per_atom": _check({"status": status, "delta_eV": energy_delta, "delta_eV_per_atom": energy_per_atom, "threshold_eV_per_atom": thresholds["cutoff_energy_eV_per_atom"], "definition": br["energy_definition"] if comparable else None}, energy_ok),
        "force_component": _check({"status": status, "max_abs_difference_eV_per_A": force_delta, "threshold_eV_per_A": thresholds["cutoff_force_component_eV_per_A"]}, force_ok),
        "stress_component": _check({"status": status, "max_abs_difference_GPa": stress_delta, "threshold_GPa": thresholds["cutoff_stress_component_GPa"], "stress_sign": {"baseline": br["stress_sign"], "comparison": cr["stress_sign"]}}, stress_ok),
    }
    overall = comparable and energy_ok and force_ok and stress_ok
    return {"schema": SCHEMA, "scope": "ABACUS_same_geometry_cutoff_only", "overall": overall, "cutoff_qualification": overall, "h1_qualification": False, "production_qualification": False, "scope_note": "A pass qualifies only this same-geometry ABACUS cutoff comparison; it does not qualify H1 or production.", "cross_engine_energy_comparison": False, "native_input_verified": native_input_verified, "method_config": str(Path(method)), "baseline_task": str(baseline["directory"]), "comparison_task": str(comparison["directory"]), "job_ids": {"baseline": bt.get("scheduler_job_id"), "comparison": ct.get("scheduler_job_id")}, "ecutwfc_Ry": ecut, "thresholds": {key: thresholds[key] for key in ("cutoff_energy_eV_per_atom", "cutoff_force_component_eV_per_A", "cutoff_stress_component_GPa")}, "checks": checks, "physics_comparable": comparable}

