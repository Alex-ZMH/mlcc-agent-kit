"""Direct cross-engine material-potential qualification.

This module compares explicitly paired, native ABACUS SCF and LAMMPS static
tasks.  It intentionally does not create a task, rewrite a saved result, or
grant production qualification.  Every pair keeps its own raw observables and
errors in the returned report; energies are compared only after subtracting
the selected reference structure in each engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from ase.io import read

from .abacus import _read_stru, parse_abacus_outputs
from .lammps_tasks import read_lammps_task
from .modeling import read_model_artifacts
from .strain import _input_values, _kpt_values, _native_physics


SCHEMA = "mlcc.potential-qualification.v001"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _task_dir(value: str | Path) -> Path:
    path = Path(value)
    if path.is_file():
        if path.name != "task.json":
            raise ValueError(f"task path must be a task directory or task.json: {path}")
        return path.parent.resolve()
    if path.is_dir():
        return path.resolve()
    raise FileNotFoundError(path)


def _completed(task: Mapping[str, Any], label: str) -> None:
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        raise ValueError(f"{label} requires saved native COMPLETED/0:0")


def _abacus_neutral_charge_contract(
    directory: Path,
    task: Mapping[str, Any],
    method: Mapping[str, Any],
    model_metadata: Mapping[str, Any],
) -> dict[str, float | str]:
    """Require the ABACUS SCF record and native INPUT to be neutral.

    The current ABACUS writer records ``net_charge`` and electron overrides in
    task and method records, with model charge in the derivation metadata.
    Older neutral jobs omit those fields and omit the native INPUT overrides;
    those omissions retain their native neutral meaning.  No charged LAMMPS
    comparison path is defined here.
    """

    science = method.get("science")
    derivation = model_metadata.get("derivation")
    sources: dict[str, Any] = {
        "task.net_charge": task.get("net_charge", 0),
        "task.nelec": task.get("nelec", 0),
        "task.nelec_delta": task.get("nelec_delta", 0),
        "method.net_charge": method.get("net_charge", 0),
        "method.nelec": method.get("nelec", 0),
        "method.nelec_delta": method.get("nelec_delta", 0),
        "method.science.net_charge": science.get("net_charge", 0) if isinstance(science, Mapping) else 0,
        "model.derivation.charge_state": derivation.get("charge_state", 0) if isinstance(derivation, Mapping) else 0,
        "model.charge_state": model_metadata.get("charge_state", 0),
    }
    for label, value in sources.items():
        numeric = float(value)
        if not np.isfinite(numeric) or numeric != 0.0:
            raise ValueError(f"{label} must be neutral (0) for atomic LAMMPS comparison")

    native = _input_values(directory / "INPUT")
    for key in ("nelec", "nelec_delta"):
        numeric = float(native.get(key, 0))
        if not np.isfinite(numeric) or numeric != 0.0:
            raise ValueError(f"native INPUT {key} must be zero for atomic LAMMPS comparison")
    gate_flag = str(native.get("gate_flag", "0")).strip().lower()
    if gate_flag not in ("0", "false"):
        raise ValueError("native INPUT gate_flag must be 0 or false for atomic LAMMPS comparison")
    return {
        "task_net_charge": float(sources["task.net_charge"]),
        "task_nelec": float(sources["task.nelec"]),
        "task_nelec_delta": float(sources["task.nelec_delta"]),
        "method_net_charge": float(sources["method.net_charge"]),
        "method_nelec": float(sources["method.nelec"]),
        "method_nelec_delta": float(sources["method.nelec_delta"]),
        "method_science_net_charge": float(sources["method.science.net_charge"]),
        "model_charge_state": float(sources["model.derivation.charge_state"]),
        "model_top_level_charge_state": float(sources["model.charge_state"]),
        "native_nelec": float(native.get("nelec", 0)),
        "native_nelec_delta": float(native.get("nelec_delta", 0)),
        "native_gate_flag": gate_flag,
    }


def _abacus_native_binding(directory: Path, method: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the saved method to the native INPUT, KPT and STRU headers."""
    values = _input_values(directory / "INPUT")
    kpt = _kpt_values(directory / "KPT")
    native_physics = _native_physics(values)
    atom_map = _json(directory / "STRU.atom-map.json")
    stru_atoms = _read_stru(directory / "STRU", atom_map)
    input_atoms = read(directory / "input.extxyz")
    raw_stru = (directory / "STRU").read_text(encoding="utf-8").splitlines()
    species_start = raw_stru.index("ATOMIC_SPECIES") + 1
    species_stop = raw_stru.index("LATTICE_CONSTANT")
    stru_species = {
        fields[0]: fields[2]
        for line in raw_stru[species_start:species_stop]
        if len(fields := line.split()) >= 3
    }
    parameters = method["parameters"]
    checks: dict[str, bool] = {
        "task_method_set": task.get("method_set") == method.get("method_set"),
        "native_kpoints": kpt["grid"] == [int(value) for value in method["kpoints"]] and kpt["offset"] == [0, 0, 0],
        "cal_force": values.get("cal_force") == "1",
        "cal_stress": values.get("cal_stress") == "1",
        "stru_atom_map": [int(value) for value in stru_atoms.arrays["atom_id"]] == [int(value) for value in atom_map["source_atom_ids"]],
        "stru_geometry": (stru_atoms.get_chemical_symbols() == input_atoms.get_chemical_symbols()
            and np.allclose(stru_atoms.cell.array, input_atoms.cell.array, rtol=0, atol=1e-8)
            and np.allclose(stru_atoms.positions, input_atoms.positions, rtol=0, atol=1e-8)),
    }
    for key, expected in {
        "ecutwfc": parameters["ecutwfc_Ry"],
        "scf_thr": parameters["scf_thr"],
        "scf_nmax": parameters["scf_nmax"],
        "nbands": parameters["nbands"],
        "mixing_beta": parameters["mixing_beta"],
        "nspin": method["nspin"],
        "symmetry": method["symmetry"],
    }.items():
        # Native inputs use 12 significant digits; allow only that serialization rounding.
        checks[f"input_{key}"] = bool(np.isclose(float(values[key]), float(expected), rtol=1e-11, atol=0))
    for key in ("dft_functional", "basis_type", "ks_solver", "mixing_type"):
        checks[f"input_{key}"] = values[key] == method[key]
    checks["input_calculation"] = values["calculation"] == "scf"
    checks["input_suffix"] = values["suffix"] == method["suffix"]
    expected_smearing = "fixed" if method["occupations"] == "fixed" else method["smearing_method"]
    checks["input_smearing_method"] = values.get("smearing_method") == str(expected_smearing)
    if method["occupations"] == "smearing":
        checks["input_smearing_sigma"] = bool(np.isclose(
            float(values["smearing_sigma"]), float(parameters["smearing_sigma_Ry"]), rtol=1e-11, atol=0))
    pseudo_files = [str(item["filename"]) for item in method["pseudopotentials"].values()]
    pseudo_sources = [str(item["source"]) for item in method["pseudopotentials"].values()]
    checks["pseudopotential_files_present"] = all(
        (directory / filename).is_file() or Path(source).is_file()
        for filename, source in zip(pseudo_files, pseudo_sources)
    )
    checks["stru_pseudopotential_names"] = all(
        stru_species.get(str(element)) == str(item["filename"])
        for element, item in method["pseudopotentials"].items()
    )
    native_identity = {"physics": native_physics, "kpt": kpt, "pseudopotential_files": pseudo_files, "stru_species": stru_species}
    return {"checks": checks, "passed": all(checks.values()), "identity": native_identity}


def _read_abacus_task(value: str | Path) -> dict[str, Any]:
    """Read and validate one native completed ABACUS SCF task without writes."""

    directory = _task_dir(value)
    task = _json(directory / "task.json")
    _completed(task, "ABACUS task")
    if task.get("engine") != "abacus":
        raise ValueError("potential comparison requires an ABACUS task")
    if task.get("calculation") != "scf":
        raise ValueError("potential comparison requires ABACUS SCF tasks")
    method = _json(directory / "method.json")
    if method.get("engine") != "abacus" or method.get("abacus_version_target") != "3.10.1":
        raise ValueError("ABACUS task must target native ABACUS 3.10.1")
    if method.get("stage") != "scf":
        raise ValueError("ABACUS method stage must be scf")
    if task.get("engine_version") != "3.10.1":
        raise ValueError("ABACUS task engine_version differs from 3.10.1")
    native_binding = _abacus_native_binding(directory, method, task)
    model_path = task.get("model_path")
    if not model_path:
        raise ValueError("ABACUS task must record model_path for native parsing")
    model = read_model_artifacts(model_path)
    if (model.model_id, model.version) != (task.get("model_id"), task.get("model_version")):
        raise ValueError("ABACUS task model identity differs from model artifacts")
    charge_contract = _abacus_neutral_charge_contract(directory, task, method, model.metadata)
    native_binding["checks"]["neutral_charge"] = True
    native_binding["identity"]["charge_contract"] = charge_contract
    input_structure = directory / "input.extxyz"
    model.atoms = read(input_structure)
    parsed = parse_abacus_outputs(directory, source_model=model, stage="scf")
    if parsed.electronic_converged is not True:
        raise ValueError(f"ABACUS task {task.get('task_id')} is not electronically converged")
    forces = np.asarray(parsed.forces_eV_per_A, dtype=float)
    stress = np.asarray(parsed.stress_GPa, dtype=float)
    if not np.isfinite(float(parsed.energy_eV)) or not np.isfinite(forces).all() or not np.isfinite(stress).all():
        raise ValueError("ABACUS native result contains non-finite energy, forces, or stress")
    if forces.shape != (len(parsed.final_atoms), 3) or stress.shape != (3, 3):
        raise ValueError("ABACUS native result has incomplete force or stress shape")
    if [int(value) for value in parsed.atom_ids] != [int(value) for value in parsed.final_atoms.arrays["atom_id"]]:
        raise ValueError("ABACUS native result atom IDs are not in source order")
    return {
        "directory": directory,
        "task": task,
        "method": method,
        "parsed": parsed,
        "atoms": parsed.final_atoms,
        "native_binding": native_binding,
    }


def _read_lammps_task(value: str | Path) -> dict[str, Any]:
    """Read and validate one native completed LAMMPS static task without writes."""

    directory = _task_dir(value)
    task = _json(directory / "task.json")
    _completed(task, "LAMMPS task")
    if task.get("engine") != "lammps":
        raise ValueError("potential comparison requires a LAMMPS task")
    if task.get("calculation") != "run0":
        raise ValueError("potential comparison requires static LAMMPS run0 tasks")
    method = _json(directory / "method.json")
    protocol = method.get("protocol")
    if not isinstance(protocol, Mapping) or protocol.get("kind") != "run0":
        raise ValueError("LAMMPS native method must declare a run0 protocol")
    if task.get("production_label") is not False:
        raise ValueError("LAMMPS potential comparison requires production_label=false")
    purpose = protocol.get("purpose")
    if "purpose" in protocol and purpose != "potential_qualification":
        raise ValueError("LAMMPS potential comparison requires purpose=potential_qualification")
    if purpose == "potential_qualification":
        if protocol.get("static_tensor") is not True:
            raise ValueError("LAMMPS potential qualification requires static_tensor=true")
        experiment_scope = protocol.get("experiment_scope")
        if not isinstance(experiment_scope, str) or not experiment_scope.strip():
            raise ValueError("LAMMPS potential qualification requires non-empty experiment_scope")
    fixture = task.get("fixture") is True
    if not fixture:
        if purpose != "potential_qualification":
            raise ValueError("non-fixture LAMMPS comparison requires purpose=potential_qualification")
        potential = method.get("potential")
        if not isinstance(potential, Mapping) or potential.get("production_qualification") is not False:
            raise ValueError("non-fixture LAMMPS comparison requires production_qualification=false")
    static_tensor_declared = protocol.get("static_tensor") is True
    if task.get("protocol") != protocol:
        raise ValueError("LAMMPS task protocol differs from native method")
    if task.get("calculation") != protocol.get("kind"):
        raise ValueError("LAMMPS task calculation differs from native method")
    parsed = read_lammps_task(directory / "task.json")
    if parsed.get("engine") != "lammps":
        raise ValueError("LAMMPS native parser returned a different engine")
    if (parsed.get("model_id"), parsed.get("version")) != (
        task.get("model_id"),
        task.get("model_version"),
    ):
        raise ValueError("LAMMPS native result model identity differs from task")
    if parsed.get("protocol") != protocol:
        raise ValueError("LAMMPS native result protocol differs from task")
    forces = np.asarray(parsed.get("forces_eV_per_A"), dtype=float)
    if not np.isfinite(forces).all() or forces.ndim != 2 or forces.shape[1] != 3:
        raise ValueError("LAMMPS native result has incomplete force data")
    if not np.isfinite(float(parsed.get("energy_eV"))):
        raise ValueError("LAMMPS native result energy is not finite")
    atom_ids = [int(value) for value in parsed.get("atom_ids", [])]
    elements = [str(value) for value in parsed.get("elements", [])]
    if len(atom_ids) != len(elements) or forces.shape[0] != len(atom_ids):
        raise ValueError("LAMMPS native result atom data are inconsistent")
    cell = np.asarray(parsed.get("cell_angstrom"), dtype=float)
    positions = np.asarray(parsed.get("positions_angstrom"), dtype=float)
    if cell.shape != (3, 3) or positions.shape != (len(atom_ids), 3) or not np.isfinite(cell).all() or not np.isfinite(positions).all():
        raise ValueError("LAMMPS native result has incomplete geometry")
    return {
        "directory": directory,
        "task": task,
        "method": method,
        "parsed": parsed,
        "atom_ids": atom_ids,
        "elements": elements,
        "positions": positions,
        "cell": cell,
        "static_tensor_declared": static_tensor_declared,
    }


def _abacus_method_identity(method: Mapping[str, Any]) -> dict[str, Any]:
    """Keep scientific ABACUS identity while dropping task-local paths/labels."""

    keys = (
        "engine",
        "abacus_version_target",
        "stage",
        "dft_functional",
        "basis_type",
        "ks_solver",
        "nspin",
        "lspinorb",
        "noncolin",
        "initial_moments_muB_by_element",
        "occupations",
        "smearing_method",
        "mixing_type",
        "relax_method",
        "symmetry",
        "element_order",
        "kpoints",
        "kpoint_rule",
        "parameters",
        "pseudopotential_ids",
        "pseudopotential_metadata",
        "stress_convention",
        "execution",
    )
    identity = {key: method.get(key) for key in keys if key in method}
    pseudo = method.get("pseudopotentials")
    if isinstance(pseudo, Mapping):
        identity["pseudopotentials"] = {
            str(element): {
                key: item[key]
                for key in ("filename",)
                if isinstance(item, Mapping) and key in item
            }
            for element, item in pseudo.items()
        }
    return identity


def _lammps_potential_identity(method: Mapping[str, Any]) -> dict[str, Any]:
    potential = method.get("potential")
    if not isinstance(potential, Mapping):
        raise ValueError("LAMMPS native method is missing potential identity")
    identity: dict[str, Any] = {}
    for key, value in potential.items():
        if key in ("model_ids",):
            continue
        if key == "files" and isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            identity[key] = [
                {str(k): v for k, v in item.items() if str(k) != "local_path"}
                for item in value
                if isinstance(item, Mapping)
            ]
        else:
            identity[str(key)] = value
    return identity


def _check(value: Any, passed: bool) -> dict[str, Any]:
    return {"value": value, "passed": bool(passed)}


def _thresholds(tolerances: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(tolerances, Mapping):
        raise TypeError("tolerances must be a mapping of predeclared finite values")
    result: dict[str, float] = {}
    for name in ("energy_eV_per_atom", "force_component_eV_per_A", "stress_component_GPa", "geometry_A"):
        if name not in tolerances:
            raise ValueError(f"tolerances must provide {name}")
        selected = tolerances[name]
        if isinstance(selected, bool) or not np.isfinite(float(selected)) or float(selected) < 0.0:
            raise ValueError(f"tolerances must provide finite non-negative {name}")
        result[name] = float(selected)
    return result


def _stress_mapping(
    abacus_stress_mapping: Mapping[str, Any] | None,
) -> tuple[float | None, str | None, list[str]]:
    """Resolve the one explicit ABACUS-to-tension mapping contract."""

    if abacus_stress_mapping is None:
        return None, None, ["abacus_stress_sign_calibration_missing"]
    if not isinstance(abacus_stress_mapping, Mapping):
        raise TypeError("abacus_stress_mapping must be a mapping")
    missing: list[str] = []
    factor = abacus_stress_mapping.get("factor_to_tension_positive")
    if isinstance(factor, bool) or factor is None or not np.isfinite(float(factor)) or float(factor) not in (-1.0, 1.0):
        missing.append("abacus_stress_conversion_factor_invalid")
        factor_value: float | None = None
    else:
        factor_value = float(factor)
    evidence = abacus_stress_mapping.get("evidence_path")
    if not isinstance(evidence, str) or not evidence.strip():
        missing.append("abacus_stress_sign_calibration_evidence_missing")
    else:
        Path(evidence).read_text(encoding="utf-8")
    # A caller-supplied factor permits a conditional comparison, not calibration.
    missing.append("abacus_stress_calibration_not_validated")
    return factor_value, "tension_positive", missing


def _geometry_checks(abacus: Mapping[str, Any], lammps: Mapping[str, Any], tolerance: float) -> dict[str, Any]:
    atoms = abacus["atoms"]
    abacus_ids = [int(value) for value in abacus["parsed"].atom_ids]
    abacus_elements = [str(value) for value in atoms.get_chemical_symbols()]
    lammps_ids = [int(value) for value in lammps["atom_ids"]]
    lammps_elements = [str(value) for value in lammps["elements"]]
    cell_delta = float(np.max(np.abs(np.asarray(atoms.cell.array, dtype=float) - lammps["cell"]))) if atoms.cell.array.shape == lammps["cell"].shape else None
    position_delta = float(np.max(np.abs(np.asarray(atoms.positions, dtype=float) - lammps["positions"]))) if atoms.positions.shape == lammps["positions"].shape else None
    ids_ok = abacus_ids == lammps_ids
    elements_ok = abacus_elements == lammps_elements
    geometry_ok = ids_ok and elements_ok and cell_delta is not None and position_delta is not None and cell_delta <= tolerance and position_delta <= tolerance
    return {
        "atom_ids": _check({"abacus": abacus_ids, "lammps": lammps_ids}, ids_ok),
        "elements": _check({"abacus": abacus_elements, "lammps": lammps_elements}, elements_ok),
        "cell_delta_A": cell_delta,
        "position_delta_A": position_delta,
        "same_geometry": _check({"cell_delta_A": cell_delta, "position_delta_A": position_delta, "tolerance_A": tolerance}, geometry_ok),
    }


def _stress_matrix(parsed: Mapping[str, Any], *, engine: str) -> tuple[np.ndarray | None, list[str]]:
    missing: list[str] = []
    if engine == "abacus":
        value = parsed.get("stress_GPa")
        if "stress_unit" in parsed and parsed.get("stress_unit") != "GPa":
            missing.append("abacus_stress_unit_not_GPa")
    else:
        if "pressure_tensor_GPa" not in parsed:
            missing.append("lammps_pressure_tensor_GPa_missing")
        value = parsed.get("stress_GPa")
        if "stress_GPa" not in parsed:
            missing.append("lammps_stress_GPa_missing")
        unit = parsed.get("stress_unit")
        if unit != "GPa":
            missing.append("lammps_stress_unit_not_GPa")
        if parsed.get("stress_sign") != "tension_positive":
            missing.append("lammps_stress_sign_not_tension_positive")
        frame = parsed.get("tensor_basis")
        if frame != "source_cartesian":
            missing.append("lammps_stress_frame_not_source_cartesian")
        pressure = parsed.get("pressure_tensor_GPa")
        if pressure is not None and value is not None:
            p = np.asarray(pressure, dtype=float)
            s = np.asarray(value, dtype=float)
            if p.shape != (3, 3) or s.shape != (3, 3):
                missing.append("lammps_stress_tensor_not_3x3")
            elif not np.allclose(s, -p, rtol=0.0, atol=1.0e-12):
                missing.append("lammps_pressure_to_stress_sign_mismatch")
    if value is None:
        missing.append(f"{engine}_stress_GPa_missing")
        return None, missing
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != (3, 3):
        missing.append(f"{engine}_stress_GPa_not_3x3")
        return None, missing
    if not np.isfinite(matrix).all():
        missing.append(f"{engine}_stress_GPa_nonfinite")
        return None, missing
    return matrix, missing


def compare_potential_tasks(
    pairs: Sequence[Mapping[str, Any]],
    reference_pair_id: str,
    tolerances: Mapping[str, Any],
    *,
    abacus_stress_mapping: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare explicitly paired native ABACUS SCF and LAMMPS static tasks.

    ``pairs`` contains mappings with ``pair_id``, ``abacus_task`` and
    ``lammps_task`` paths.  ``reference_pair_id`` is subtracted independently
    within each engine before the per-atom energy error is evaluated.  The
    returned report is read-only evidence: ``production_qualification`` is
    always ``False`` and no task/result files are rewritten.

    Tolerances require energy_eV_per_atom, force_component_eV_per_A,
    stress_component_GPa and geometry_A. Optional abacus_stress_mapping
    requires factor_to_tension_positive (+1 or -1) and evidence_path. This
    slice reads that evidence but does not certify its calibration: stress
    differences remain conditional and qualification remains false.
    """

    thresholds = _thresholds(tolerances)
    if not isinstance(pairs, Sequence) or isinstance(pairs, (str, bytes)) or len(pairs) < 2:
        raise ValueError("pairs must contain at least two explicit pairs")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in pairs:
        if not isinstance(entry, Mapping):
            raise TypeError("each potential pair must be a mapping")
        pair_id = str(entry.get("pair_id", ""))
        if not pair_id or pair_id in seen:
            raise ValueError("pair_id values must be non-empty and unique")
        if "abacus_task" not in entry or "lammps_task" not in entry:
            raise ValueError("each potential pair requires abacus_task and lammps_task")
        seen.add(pair_id)
        normalized.append({"pair_id": pair_id, "abacus_task": entry["abacus_task"], "lammps_task": entry["lammps_task"]})
    if reference_pair_id not in seen:
        raise ValueError("reference_pair_id must identify one explicit pair")

    sign_factor, sign_target, sign_missing = _stress_mapping(abacus_stress_mapping)
    loaded: list[dict[str, Any]] = []
    pair_reports: list[dict[str, Any]] = []
    for entry in normalized:
        abacus = _read_abacus_task(entry["abacus_task"])
        lammps = _read_lammps_task(entry["lammps_task"])
        geometry = _geometry_checks(abacus, lammps, thresholds["geometry_A"])
        af = np.asarray(abacus["parsed"].forces_eV_per_A, dtype=float)
        lf = np.asarray(lammps["parsed"]["forces_eV_per_A"], dtype=float)
        geometry_ok = geometry["same_geometry"]["passed"]
        native_binding_ok = abacus["native_binding"]["passed"] is True
        comparison_ok = geometry_ok and native_binding_ok
        force_shape = af.shape == lf.shape
        force_delta = np.asarray(lf - af, dtype=float) if comparison_ok and force_shape else None
        force_max = float(np.max(np.abs(force_delta))) if force_delta is not None else None
        force_rms = float(np.sqrt(np.mean(force_delta**2))) if force_delta is not None else None
        astress, astress_missing = _stress_matrix({"stress_GPa": abacus["parsed"].stress_GPa}, engine="abacus")
        lstress, lstress_missing = _stress_matrix(lammps["parsed"], engine="lammps")
        if not lammps["static_tensor_declared"]:
            lstress_missing.append("lammps_static_tensor_not_declared")
        if astress is not None and sign_factor is not None:
            mapped_abacus_stress = sign_factor * astress
        else:
            mapped_abacus_stress = None
        stress_delta = np.asarray(lstress - mapped_abacus_stress, dtype=float) if comparison_ok and lstress is not None and mapped_abacus_stress is not None else None
        stress_max = float(np.max(np.abs(stress_delta))) if stress_delta is not None else None
        stress_fro = float(np.linalg.norm(stress_delta)) if stress_delta is not None else None
        loaded.append({"entry": entry, "abacus": abacus, "lammps": lammps, "force_max": force_max, "force_rms": force_rms, "stress_max": stress_max, "stress_fro": stress_fro, "mapped_abacus_stress": mapped_abacus_stress, "astress_missing": astress_missing, "lstress_missing": lstress_missing, "force_shape": force_shape})
        pair_reports.append({
            "pair_id": entry["pair_id"],
            "abacus_task": str(abacus["directory"]),
            "lammps_task": str(lammps["directory"]),
            "source_jobs": {"abacus": abacus["task"]["scheduler_job_id"], "lammps": lammps["task"]["scheduler_job_id"]},
            "source_files": {"abacus": abacus["parsed"].source_files, "lammps": lammps["parsed"]["source_files"]},
            "geometry": geometry,
            "energy_raw": {
                "abacus_eV": float(abacus["parsed"].energy_eV),
                "lammps_eV": float(lammps["parsed"]["energy_eV"]),
            },
            "stress_missing_qualifications": [*sign_missing, *astress_missing, *lstress_missing],
            "force": {"raw_abacus_eV_per_A": af.tolist(), "raw_lammps_eV_per_A": lf.tolist(), "shape_match": force_shape, "delta_eV_per_A": None if force_delta is None else force_delta.tolist(), "max_component_eV_per_A": force_max, "rms_eV_per_A": force_rms, "threshold_eV_per_A": thresholds["force_component_eV_per_A"], "passed": comparison_ok and force_shape and force_max is not None and force_max <= thresholds["force_component_eV_per_A"]},
            "stress": {"raw_abacus_stress_GPa": astress.tolist() if astress is not None else None, "raw_lammps_stress_GPa": lstress.tolist() if lstress is not None else None, "mapped_abacus_stress_GPa": None if mapped_abacus_stress is None else mapped_abacus_stress.tolist(), "lammps_stress_GPa": None if lstress is None else lstress.tolist(), "delta_GPa": None if stress_delta is None else stress_delta.tolist(), "max_component_GPa": stress_max, "frobenius_GPa": stress_fro, "threshold_GPa": thresholds["stress_component_GPa"], "passed": comparison_ok and not sign_missing and not astress_missing and not lstress_missing and stress_max is not None and stress_max <= thresholds["stress_component_GPa"]},
        })

    reference_index = next(index for index, item in enumerate(loaded) if item["entry"]["pair_id"] == reference_pair_id)
    reference = loaded[reference_index]
    reference_abacus_energy = float(reference["abacus"]["parsed"].energy_eV)
    reference_lammps_energy = float(reference["lammps"]["parsed"]["energy_eV"])
    reference_elements = sorted(str(value) for value in reference["abacus"]["atoms"].get_chemical_symbols())
    reference_count = len(reference_elements)
    method_identities = [_abacus_method_identity(item["abacus"]["method"]) for item in loaded]
    native_bindings = [item["abacus"]["native_binding"] for item in loaded]
    native_binding_pass = all(item["passed"] for item in native_bindings)
    native_binding_identities = [item["identity"] for item in native_bindings]
    same_native_binding = all(item == native_binding_identities[0] for item in native_binding_identities)
    potential_identities = [_lammps_potential_identity(item["lammps"]["method"]) for item in loaded]
    method_sets = [item["abacus"]["method"].get("method_set") for item in loaded]
    potential_sets = [item["lammps"]["task"].get("method_set") for item in loaded]
    same_method = all(identity == method_identities[0] for identity in method_identities)
    same_method_set = len(set(method_sets)) == 1
    same_potential = all(identity == potential_identities[0] for identity in potential_identities)
    same_potential_set = len(set(potential_sets)) == 1

    for pair_index, (item, report) in enumerate(zip(loaded, pair_reports)):
        n_abacus = len(item["abacus"]["parsed"].atom_ids)
        n_lammps = len(item["lammps"]["parsed"]["atom_ids"])
        pair_elements = sorted(str(value) for value in item["abacus"]["atoms"].get_chemical_symbols())
        same_count = n_abacus == n_lammps == reference_count and n_abacus > 0
        same_composition = pair_elements == reference_elements and sorted(item["lammps"]["elements"]) == reference_elements
        relative_allowed = (report["geometry"]["same_geometry"]["passed"]
            and pair_reports[reference_index]["geometry"]["same_geometry"]["passed"]
            and same_count and same_composition and same_method and same_method_set
            and same_native_binding and native_binding_pass and same_potential and same_potential_set)
        abacus_relative = (float(item["abacus"]["parsed"].energy_eV) - reference_abacus_energy) / n_abacus if relative_allowed else None
        lammps_relative = (float(item["lammps"]["parsed"]["energy_eV"]) - reference_lammps_energy) / n_lammps if relative_allowed else None
        error = abs(abacus_relative - lammps_relative) if abacus_relative is not None and lammps_relative is not None else None
        passed = error is not None and error <= thresholds["energy_eV_per_atom"]
        report["relative_energy"] = {
            "abacus_eV_per_atom": abacus_relative,
            "lammps_eV_per_atom": lammps_relative,
            "abs_error_eV_per_atom": error,
            "threshold_eV_per_atom": thresholds["energy_eV_per_atom"],
            "same_atom_count": same_count,
            "same_composition": same_composition,
            "passed": passed,
        }
        report["method_set"] = method_sets[pair_index]
        report["potential_method_set"] = potential_sets[pair_index]

    missing: list[str] = list(sign_missing)
    if not native_binding_pass:
        missing.append("abacus_native_input_binding_failed")
    if not same_native_binding:
        missing.append("abacus_native_input_binding_mismatch")
    if not same_method:
        missing.append("abacus_method_native_physics_mismatch")
    if not same_method_set:
        missing.append("abacus_method_set_mismatch")
    if not same_potential:
        missing.append("lammps_potential_identity_mismatch")
    if not same_potential_set:
        missing.append("lammps_potential_method_set_mismatch")
    for report in pair_reports:
        missing.extend(report["stress_missing_qualifications"])
        if not report["geometry"]["same_geometry"]["passed"]:
            missing.append(f"geometry_mismatch:{report['pair_id']}")
        if not report["relative_energy"]["same_atom_count"]:
            missing.append(f"atom_count_mismatch:{report['pair_id']}")
        if not report["relative_energy"]["same_composition"]:
            missing.append(f"composition_mismatch:{report['pair_id']}")
    missing = list(dict.fromkeys(missing))
    pair_pass = all(
        report["geometry"]["same_geometry"]["passed"]
        and report["relative_energy"]["passed"]
        and report["force"]["passed"]
        and report["stress"]["passed"]
        for report in pair_reports
    )
    overall = pair_pass and native_binding_pass and same_native_binding and same_method and same_method_set and same_potential and same_potential_set and not missing
    checks = {
        "same_abacus_method_native_physics": _check(method_identities, same_method),
        "abacus_native_input_binding": _check(native_bindings, native_binding_pass and same_native_binding),
        "same_abacus_method_set": _check(method_sets, same_method_set),
        "same_lammps_potential_identity": _check(potential_identities, same_potential),
        "same_lammps_potential_method_set": _check(potential_sets, same_potential_set),
        "abacus_stress_sign_mapping": _check({"target_sign": sign_target, "factor": sign_factor, "missing": sign_missing}, not sign_missing),
        "pair_results": _check(pair_reports, pair_pass),
    }
    return {
        "schema": SCHEMA,
        "scope": "paired_ABACUS_SCF_vs_LAMMPS_static_relative_observables",
        "reference_pair_id": reference_pair_id,
        "thresholds": thresholds,
        "pairs": pair_reports,
        "checks": checks,
        "missing_qualifications": missing,
        "unassessed_qualifications": ["reference_DFT_precision", "material_applicability_domain",
            "stability_and_sampling", "polarization_and_field", "defects_cross_phase_and_interfaces"],
        "abacus_stress_mapping": None if abacus_stress_mapping is None else dict(abacus_stress_mapping),
        "physics_comparable": bool(overall),
        "measured_comparison_pass": bool(overall),
        "potential_qualification": False,
        "production_qualification": False,
        "production_label": False,
        "status": "comparison_passed_potential_unqualified" if overall else "not_qualified",
        "scope_note": "A pass is limited to the explicitly paired structures and selected native methods; it never grants production material or sampling qualification.",
    }

