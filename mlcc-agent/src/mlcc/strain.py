"""Direct ABACUS finite-strain stress-sign qualification helpers."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.io import read

from .workflow import source_evidence


SCHEMA = "mlcc.abacus-strain-qualification.v001"
ABACUS_VERSION = "3.10.1"
EV_PER_A3_TO_GPA = 160.21766208
GEOMETRY_TOLERANCE_A = 1.0e-10
FRACTIONAL_TOLERANCE = 1.0e-10


def isotropic_strain_model(
    reference_atoms: Atoms,
    epsilon: float,
    *,
    reference_model: str | dict[str, Any] | None = None,
) -> tuple[Atoms, dict[str, Any]]:
    """Derive an isotropically strained model while keeping fractional sites fixed."""

    value = float(epsilon)
    F = np.eye(3, dtype=float) * (1.0 + value)
    fractional = reference_atoms.get_scaled_positions(wrap=False)
    derived = reference_atoms.copy()
    derived.set_cell(np.asarray(reference_atoms.cell.array, dtype=float) @ F, scale_atoms=False)
    derived.set_scaled_positions(fractional)
    record = {
        "strain_type": "isotropic",
        "epsilon": value,
        "F": F.tolist(),
        "deformation_gradient": F.tolist(),
        "reference_model": copy.deepcopy(reference_model),
        "reference_volume_A3": float(reference_atoms.get_volume()),
        "derived_volume_A3": float(derived.get_volume()),
        "fractional_coordinates_fixed": True,
        "atom_ids": [int(v) for v in reference_atoms.arrays["atom_id"]],
    }
    return derived, record


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _input_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and not fields[0].startswith("#") and len(fields) >= 2:
            values[fields[0]] = fields[1]
    return values


def _kpt_values(path: Path) -> dict[str, list[int]]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 4 or lines[0] != "K_POINTS" or lines[1] != "0" or lines[2] != "Gamma":
        raise ValueError(f"{path} must use the current four-line Gamma KPT format")
    fields = lines[3].split()
    if len(fields) != 6:
        raise ValueError(f"{path} Gamma KPT line must contain grid and offset")
    return {
        "grid": [int(value) for value in fields[:3]],
        "offset": [int(value) for value in fields[3:]],
    }


def _bundle(directory: str | Path) -> dict[str, Any]:
    directory = Path(directory)
    return {
        "directory": directory,
        "task": _json(directory / "task.json"),
        "method": _json(directory / "method.json"),
        "result": _json(directory / "result.json"),
        "input": _input_values(directory / "INPUT"),
        "kpt": _kpt_values(directory / "KPT"),
        "atoms": read(directory / "input.extxyz"),
    }


def _check(value: Any, passed: bool) -> dict[str, Any]:
    return {"value": value, "passed": bool(passed)}


def _method_physics(method: dict[str, Any]) -> dict[str, Any]:
    parameters = copy.deepcopy(method["parameters"])
    parameters.pop("cal_force", None)
    parameters.pop("cal_stress", None)
    element_order = [str(value) for value in method["element_order"]]
    if "initial_moments_muB_by_element" in method:
        moments = {str(key): float(value) for key, value in method["initial_moments_muB_by_element"].items()}
    else:
        moment = float(method["initial_magnetic_moment_muB_per_atom"])
        moments = {element: moment for element in element_order}
    return {
        "engine": method["engine"],
        "abacus_version_target": method["abacus_version_target"],
        "stage": method["stage"],
        "model_id": method["model_id"],
        "device": method["device"],
        "dft_functional": method["dft_functional"],
        "basis_type": method["basis_type"],
        "ks_solver": method["ks_solver"],
        "nspin": method["nspin"],
        "initial_moments_muB_by_element": moments,
        "smearing_method": method["smearing_method"],
        "element_order": method["element_order"],
        "kpoints": method["kpoints"],
        "kpoint_rule": method["kpoint_rule"],
        "parameters": parameters,
        "pseudopotentials": {
            element: method["pseudopotentials"][element]["filename"]
            for element in element_order
        },
        "stress_convention": method["stress_convention"],
    }


def _native_physics(values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if key != "suffix"}


def _finite_smearing_energy(result: dict[str, Any]) -> tuple[float, bool, dict[str, Any]]:
    definition = result["energy_definition"]
    default_definition = result["energy_default_definition"]
    normalized = f"{definition} {default_definition}".lower().replace("-", " ")
    finite_smearing = "e_kohnsham" in normalized and "finite smearing" in normalized
    energy = float(result["energy_eV"])
    return energy, finite_smearing, {
        "field": "energy_eV",
        "unit": result["energy_unit"],
        "definition": definition,
        "default_definition": default_definition,
        "sigma0_field_ignored": "energy_sigma0_eV",
    }


def _geometry(reference: Atoms, candidate: Atoms) -> dict[str, Any]:
    reference_ids = [int(v) for v in reference.arrays["atom_id"]]
    candidate_ids = [int(v) for v in candidate.arrays["atom_id"]]
    reference_fractional = reference.get_scaled_positions(wrap=False)
    candidate_fractional = candidate.get_scaled_positions(wrap=False)
    fractional_delta = (
        float(np.max(np.abs(candidate_fractional - reference_fractional)))
        if candidate_fractional.shape == reference_fractional.shape
        else None
    )
    cell_delta = (
        float(np.max(np.abs(candidate.cell.array - reference.cell.array)))
        if candidate.cell.array.shape == reference.cell.array.shape
        else None
    )
    same = (
        candidate.get_chemical_symbols() == reference.get_chemical_symbols()
        and candidate_ids == reference_ids
        and candidate.pbc.tolist() == reference.pbc.tolist()
        and fractional_delta is not None
        and fractional_delta <= FRACTIONAL_TOLERANCE
    )
    return {
        "passed": same,
        "atom_ids": {"reference": reference_ids, "candidate": candidate_ids},
        "fractional_max_abs_delta": fractional_delta,
        "fractional_tolerance": FRACTIONAL_TOLERANCE,
        "cell_max_abs_delta_A": cell_delta,
        "symbols_same": candidate.get_chemical_symbols() == reference.get_chemical_symbols(),
        "pbc_same": candidate.pbc.tolist() == reference.pbc.tolist(),
    }


def _strain_geometry(reference: Atoms, candidate: Atoms, expected_epsilon: float) -> dict[str, Any]:
    F = np.linalg.solve(reference.cell.array, candidate.cell.array)
    expected_F = np.eye(3) * (1.0 + expected_epsilon)
    volume = float(abs(np.linalg.det(reference.cell.array)))
    expected_volume = volume * (1.0 + expected_epsilon) ** 3
    F_delta = float(np.max(np.abs(F - expected_F)))
    volume_delta = abs(float(candidate.get_volume()) - expected_volume)
    fixed = _geometry(reference, candidate)
    passed = fixed["passed"] and F_delta <= GEOMETRY_TOLERANCE_A and volume_delta <= GEOMETRY_TOLERANCE_A
    return {
        "passed": passed,
        "epsilon": float(expected_epsilon),
        "F": F.tolist(),
        "expected_F": expected_F.tolist(),
        "F_max_abs_delta": F_delta,
        "reference_volume_A3": volume,
        "candidate_volume_A3": float(candidate.get_volume()),
        "expected_volume_A3": expected_volume,
        "volume_abs_delta_A3": volume_delta,
        "fixed_fractional_coordinates": fixed,
    }


def compare_strain_tasks(
    minus_task: str | Path,
    reference_task: str | Path,
    plus_task: str | Path,
    method: str | Path,
) -> dict[str, Any]:
    """Compare finite-smearing ABACUS energies with the reference stress trace."""

    minus, reference, plus = (_bundle(path) for path in (minus_task, reference_task, plus_task))
    config = _json(Path(method))
    bundles = {"minus": minus, "reference": reference, "plus": plus}
    tasks = {name: bundle["task"] for name, bundle in bundles.items()}
    methods = {name: bundle["method"] for name, bundle in bundles.items()}
    results = {name: bundle["result"] for name, bundle in bundles.items()}
    inputs = {name: bundle["input"] for name, bundle in bundles.items()}
    atoms = {name: bundle["atoms"] for name, bundle in bundles.items()}
    thresholds = config["predeclared_engineering_thresholds"]
    threshold = float(thresholds["strain_derivative_stress_trace_GPa"])
    h = float(thresholds["strain_step"])

    scheduler = {
        name: {"scheduler_state": task["scheduler_state"], "exit_code": task["exit_code"]}
        for name, task in tasks.items()
    }
    scheduler_ok = all(value == {"scheduler_state": "COMPLETED", "exit_code": "0:0"} for value in scheduler.values())
    electronic = {name: result["electronic_converged"] for name, result in results.items()}
    electronic_ok = all(value is True for value in electronic.values())

    engines = [tasks[name]["engine"] for name in bundles] + [methods[name]["engine"] for name in bundles] + [config["engine"]]
    versions = [tasks[name]["engine_version"] for name in bundles] + [methods[name]["abacus_version_target"] for name in bundles] + [config["engine_version"]]
    same_engine = all(value == "abacus" for value in engines)
    same_version = all(value == ABACUS_VERSION for value in versions)

    parent_method_set = config["parent_method_set"]
    method_set = config["method_set"]
    method_set_check = {
        "expected": {"reference": parent_method_set, "minus": method_set, "plus": method_set},
        "task": {name: tasks[name]["method_set"] for name in bundles},
        "method": {name: methods[name]["method_set"] for name in bundles},
    }
    method_sets_ok = (
        tasks["reference"]["method_set"] == methods["reference"]["method_set"] == parent_method_set
        and tasks["minus"]["method_set"] == methods["minus"]["method_set"] == method_set
        and tasks["plus"]["method_set"] == methods["plus"]["method_set"] == method_set
    )

    method_physics = {name: _method_physics(methods[name]) for name in bundles}
    method_physics_ok = method_physics["minus"] == method_physics["reference"] == method_physics["plus"]
    native_physics = {name: _native_physics(inputs[name]) for name in bundles}
    native_physics_ok = native_physics["minus"] == native_physics["reference"] == native_physics["plus"]
    native_kpoints = {name: bundles[name]["kpt"] for name in bundles}
    native_kpoints_same = native_kpoints["minus"] == native_kpoints["reference"] == native_kpoints["plus"]
    method_kpoints_match = all(
        list(methods[name]["kpoints"]) == native_kpoints[name]["grid"]
        for name in bundles
    )
    config_kpoints_match = list(config["kpoints"]) == native_kpoints["reference"]["grid"]
    kpoints_ok = native_kpoints_same and method_kpoints_match and config_kpoints_match
    native_flags = {
        name: {key: inputs[name][key] for key in ("cal_force", "cal_stress")}
        for name in bundles
    }
    native_flags_ok = all(flags == {"cal_force": "1", "cal_stress": "1"} for flags in native_flags.values())
    suffixes = {name: inputs[name]["suffix"] for name in bundles}

    geometry = {
        "minus": _strain_geometry(atoms["reference"], atoms["minus"], -h),
        "reference": _geometry(atoms["reference"], atoms["reference"]),
        "plus": _strain_geometry(atoms["reference"], atoms["plus"], h),
    }
    geometry_ok = all(value["passed"] for value in geometry.values())
    input_ids_ok = all(results[name]["atom_ids"] == [int(v) for v in atoms[name].arrays["atom_id"]] for name in bundles)
    task_result_identity = all(
        results[name]["task_id"] == tasks[name]["task_id"]
        and results[name]["scheduler_job_id"] == tasks[name]["scheduler_job_id"]
        and results[name]["method_set"] == tasks[name]["method_set"]
        for name in bundles
    )
    stage_ok = all(methods[name]["stage"] == "scf" and results[name]["stage"] == "scf" for name in bundles)
    source_records: dict[str, dict[str, Any]] = {}
    for name, bundle in bundles.items():
        paths, invalid, reason = source_evidence(
            results[name],
            bundle["directory"] / "result.json",
            engine="abacus",
        )
        source_records[name] = {
            "paths": [str(path) for path in paths],
            "invalid": [str(path) for path in invalid],
            "reason": reason,
        }
    source_evidence_ok = all(record["reason"] == "complete" for record in source_records.values())

    energies: dict[str, float] = {}
    energy_records: dict[str, dict[str, Any]] = {}
    finite_energy = {}
    for name in bundles:
        energy, is_finite_smearing, record = _finite_smearing_energy(results[name])
        energies[name] = energy
        finite_energy[name] = is_finite_smearing and results[name]["energy_unit"] == "eV"
        energy_records[name] = record
    energy_definitions_ok = (
        all(finite_energy.values())
        and len({results[name]["energy_definition"] for name in bundles}) == 1
        and len({results[name]["energy_default_definition"] for name in bundles}) == 1
    )

    stress = {}
    stress_records = {}
    for name in bundles:
        matrix = np.asarray(results[name]["stress_GPa"], dtype=float)
        stress[name] = matrix
        stress_records[name] = {
            "unit": results[name]["stress_unit"],
            "sign": results[name]["stress_sign"],
            "trace_GPa": float(np.trace(matrix)),
        }
    stress_ok = (
        all(results[name]["stress_unit"] == "GPa" and results[name]["stress_sign"] == "abacus_printed" for name in bundles)
        and len({results[name]["stress_sign"] for name in bundles}) == 1
        and all(matrix.shape == (3, 3) and np.isfinite(matrix).all() for matrix in stress.values())
    )
    finite_results = all(
        np.isfinite(float(results[name]["energy_eV"]))
        and np.isfinite(np.asarray(results[name]["forces_eV_per_A"], dtype=float)).all()
        for name in bundles
    ) and stress_ok

    configured_ecut = config["parameters"]["ecutwfc_Ry"]
    configured_ecut_ok = all(methods[name]["parameters"]["ecutwfc_Ry"] == configured_ecut for name in bundles)
    comparable = all((scheduler_ok, electronic_ok, same_engine, same_version, method_sets_ok, method_physics_ok,
                      native_physics_ok, kpoints_ok, native_flags_ok, geometry_ok, input_ids_ok, task_result_identity,
                      stage_ok, source_evidence_ok, configured_ecut_ok, energy_definitions_ok, finite_results))
    V0 = float(abs(np.linalg.det(atoms["reference"].cell.array)))
    derivative = ((energies["plus"] - energies["minus"]) / (2.0 * h * V0) * EV_PER_A3_TO_GPA) if comparable else None
    printed_trace = stress_records["reference"]["trace_GPa"]
    candidates = {
        "printed_trace": {
            "candidate_GPa": printed_trace,
            "derivative_GPa": derivative,
            "absolute_error_GPa": abs(derivative - printed_trace) if derivative is not None else None,
            "threshold_GPa": threshold,
        },
        "negative_printed_trace": {
            "candidate_GPa": -printed_trace,
            "derivative_GPa": derivative,
            "absolute_error_GPa": abs(derivative + printed_trace) if derivative is not None else None,
            "threshold_GPa": threshold,
        },
    }
    for candidate in candidates.values():
        candidate["passed"] = candidate["absolute_error_GPa"] is not None and candidate["absolute_error_GPa"] <= threshold
    passing_candidates = [name for name, candidate in candidates.items() if candidate["passed"]]
    sign_determined = len(passing_candidates) == 1

    checks = {
        "scheduler_completed_0": _check(scheduler, scheduler_ok),
        "electronic_converged": _check(electronic, electronic_ok),
        "same_engine": _check(engines, same_engine),
        "same_engine_version": _check(versions, same_version),
        "method_set_lineage": _check(method_set_check, method_sets_ok),
        "same_method_physics": _check(method_physics, method_physics_ok),
        "same_native_input_physics": _check(native_physics, native_physics_ok),
        "same_native_kpoints": _check({"native": native_kpoints, "methods": {name: methods[name]["kpoints"] for name in bundles}, "config": config["kpoints"]}, kpoints_ok),
        "native_force_stress_flags": _check(native_flags, native_flags_ok),
        "same_atom_order": _check(input_ids_ok, input_ids_ok),
        "fixed_fractional_isotropic_geometry": _check(geometry, geometry_ok),
        "result_identity": _check(task_result_identity, task_result_identity),
        "same_scf_stage": _check(stage_ok, stage_ok),
        "native_source_evidence": _check(source_records, source_evidence_ok),
        "configured_ecutwfc": _check({"configured_Ry": configured_ecut, "tasks_Ry": {name: methods[name]["parameters"]["ecutwfc_Ry"] for name in bundles}}, configured_ecut_ok),
        "finite_smearing_energy": _check(energy_records, energy_definitions_ok),
        "finite_results": _check(finite_results, finite_results),
        "stress_units_and_printed_sign": _check(stress_records, stress_ok),
        "printed_sign_candidate": _check(candidates["printed_trace"], candidates["printed_trace"]["passed"]),
        "negative_printed_sign_candidate": _check(candidates["negative_printed_trace"], candidates["negative_printed_trace"]["passed"]),
        "exactly_one_sign_candidate": _check(passing_candidates, sign_determined),
    }
    overall = comparable and sign_determined
    return {
        "schema": SCHEMA,
        "scope": "ABACUS_isotropic_finite_strain_stress_trace_only",
        "overall": overall,
        "stress_sign_qualification": overall,
        "production_qualification": False,
        "tensor_qualification": False,
        "shear_qualification": False,
        "elastic_constant_qualification": False,
        "engine": "abacus",
        "engine_version": ABACUS_VERSION,
        "method_set": {"reference": parent_method_set, "strain": method_set},
        "parent_method_set": parent_method_set,
        "temperature_K": None,
        "reference_model": {
            "model_id": tasks["reference"]["model_id"],
            "version": tasks["reference"]["model_version"],
            "task_id": tasks["reference"]["task_id"],
        },
        "source_jobs": {name: tasks[name]["scheduler_job_id"] for name in bundles},
        "source_tasks": {name: str(bundles[name]["directory"]) for name in bundles},
        "source_evidence": source_records,
        "suffix_labels": suffixes,
        "kpoints": {"native": native_kpoints, "method": {name: methods[name]["kpoints"] for name in bundles}, "config": config["kpoints"]},
        "strain_step": h,
        "reference_volume_A3": V0,
        "energy_derivative_trace_GPa": derivative,
        "energy_definition": energy_records["reference"],
        "stress_trace_GPa": stress_records,
        "sign_candidates": candidates,
        "sign_determined": sign_determined,
        "passing_sign_candidates": passing_candidates,
        "units": {"energy": "eV", "volume": "angstrom^3", "strain": "dimensionless", "stress": "GPa", "derivative": "GPa"},
        "thresholds": {"strain_step": h, "strain_derivative_stress_trace_GPa": threshold},
        "checks": checks,
        "physics_comparable": comparable,
    }
