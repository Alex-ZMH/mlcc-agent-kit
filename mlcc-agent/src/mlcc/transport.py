"""Saved ABACUS bands to the fixed BoltzTraP2 transport contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import numpy as np


SCHEMA = "mlcc.transport.v001"
REQUEST_SCHEMA = "mlcc.transport-request.v001"
BACKEND_VERSION = "26.3.1"
UNITS = {
    "seebeck": "V/K",
    "sigma_over_tau": "S/(m s)",
    "kappa_e_over_tau": "W/(m K s)",
    "power_factor_over_tau": "W/(m K^2 s)",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _equal(label: str, left: Any, right: Any) -> None:
    if left != right:
        raise ValueError(f"{label} mismatch: {left!r} != {right!r}")


def _missing(mapping: Mapping[str, Any], field: str) -> bool:
    return field not in mapping or mapping[field] is None


def _identity(label: str, left: Mapping[str, Any], right: Mapping[str, Any], fields: tuple[str, ...], missing: list[str]) -> None:
    for field in fields:
        if _missing(left, field):
            missing.append(f"{label}.{field}.left")
        if _missing(right, field):
            missing.append(f"{label}.{field}.right")
        if field in left and field in right and left[field] is not None and right[field] is not None:
            _equal(f"{label}.{field}", left[field], right[field])


def _source_files(electronic_path: Path, task_dir: Path) -> dict[str, str]:
    return {name: str(task_dir / name) for name in ("task.json", "result.json", "method.json", "INPUT", "STRU.atom-map.json")} | {"electronic.json": str(electronic_path)}


def _source_missing(request: Mapping[str, Any], electronic: Mapping[str, Any], result: Mapping[str, Any], task: Mapping[str, Any], method: Mapping[str, Any], atom_map: Mapping[str, Any], inputs: Mapping[str, str]) -> list[str]:
    missing: list[str] = []
    for field in ("kpoint_weight_field", "temperatures_K", "chemical_potentials_eV", "energy_reference", "dos_energy_window_eV", "dos_bins", "equivalence_count"):
        if _missing(request, field):
            missing.append(field)
    for field in ("nspin", "array_order", "kpoint_coordinates", "kpoint_mesh", "kpoint_mesh_shift", "fermi_level_eV", "band_energies_eV", "kpoint_coordinate_system", "uniform_kmesh_verified", "spin_degeneracy", "occupation_capacity_per_spin_channel"):
        if _missing(electronic, field):
            missing.append(f"electronic.{field}")
    weight_field = request.get("kpoint_weight_field")
    if weight_field is not None and weight_field not in electronic:
        missing.append(f"electronic.{weight_field}")
    for field in ("final_atoms", "atom_ids", "stage", "electronic_converged"):
        if _missing(result, field):
            missing.append(f"result.{field}")
    atoms = result.get("final_atoms")
    if isinstance(atoms, Mapping):
        for field in ("symbols", "positions_angstrom", "cell_angstrom", "pbc"):
            if _missing(atoms, field):
                missing.append(f"result.final_atoms.{field}")
    for field in ("source_atom_ids", "abacus_order", "model_id", "version"):
        if _missing(atom_map, field):
            missing.append(f"STRU.atom-map.json.{field}")
    if "abacus_order" in atom_map:
        for index, item in enumerate(atom_map["abacus_order"]):
            for field in ("abacus_index", "source_index", "atom_id", "element"):
                if _missing(item, field):
                    missing.append(f"STRU.atom-map.json.abacus_order[{index}].{field}")
    for field in ("nspin", "stage"):
        if _missing(method, field):
            missing.append(f"method.{field}")
    if _missing(inputs, "nspin"):
        missing.append("INPUT.nspin")
    for field in ("status", "scheduler_state", "exit_code", "engine", "engine_version"):
        if _missing(task, field):
            missing.append(f"task.{field}")
    for field in ("engine", "engine_version"):
        if _missing(electronic, field):
            missing.append(f"electronic.{field}")
    for field in ("engine", "abacus_version_target"):
        if _missing(method, field):
            missing.append(f"method.{field}")
    return missing


def _validate_atoms(result: Mapping[str, Any], atom_map: Mapping[str, Any]) -> tuple[list[Any], list[str], np.ndarray, np.ndarray, list[bool]]:
    atoms = result["final_atoms"]
    source_ids = list(result["atom_ids"])
    _equal("result.atom_ids/source_atom_ids", source_ids, list(atom_map["source_atom_ids"]))
    if not source_ids or len(set(source_ids)) != len(source_ids):
        raise ValueError("atom-map source_atom_ids must be unique and non-empty")
    symbols = list(atoms["symbols"])
    positions = np.asarray(atoms["positions_angstrom"], dtype=float)
    cell = np.asarray(atoms["cell_angstrom"], dtype=float)
    pbc = list(atoms["pbc"])
    if len(symbols) != len(source_ids) or positions.shape != (len(source_ids), 3) or cell.shape != (3, 3) or len(pbc) != 3:
        raise ValueError("result.final_atoms and atom map dimensions differ")
    ordered_ids: list[Any] = []
    ordered_symbols: list[str] = []
    ordered_positions: list[np.ndarray] = []
    order = sorted(atom_map["abacus_order"], key=lambda value: int(value["abacus_index"]))
    if [int(item["abacus_index"]) for item in order] != list(range(len(source_ids))):
        raise ValueError("atom-map abacus_index is not a complete zero-based order")
    for item in order:
        source_index = int(item["source_index"])
        if source_index < 0 or source_index >= len(source_ids):
            raise ValueError("atom-map source_index is outside result.final_atoms")
        if item["atom_id"] != source_ids[source_index] or item["element"] != symbols[source_index]:
            raise ValueError("atom-map source_index does not identify result.final_atoms")
        ordered_ids.append(item["atom_id"])
        ordered_symbols.append(symbols[source_index])
        ordered_positions.append(positions[source_index])
    if len(ordered_ids) != len(source_ids) or len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("atom-map abacus_order is incomplete or duplicated")
    return ordered_ids, ordered_symbols, np.asarray(ordered_positions), cell, pbc


def _validate_kmesh(electronic: Mapping[str, Any], weight_field: str) -> tuple[np.ndarray, np.ndarray, list[int], list[int], float]:
    coordinates = np.asarray(electronic["kpoint_coordinates"], dtype=float)
    weights = np.asarray(electronic[weight_field], dtype=float)
    mesh = [int(value) for value in electronic["kpoint_mesh"]]
    shift = list(electronic["kpoint_mesh_shift"])
    if coordinates.ndim != 2 or coordinates.shape[1] != 3 or weights.shape != (len(coordinates),):
        raise ValueError("saved kpoint coordinates and selected weights have incompatible shapes")
    if len(mesh) != 3 or any(value <= 0 for value in mesh) or len(shift) != 3:
        raise ValueError("saved kpoint mesh is invalid")
    expected = np.asarray([[(ix + shift[0]) / mesh[0], (iy + shift[1]) / mesh[1], (iz + shift[2]) / mesh[2]] for iz in range(mesh[2]) for iy in range(mesh[1]) for ix in range(mesh[0])], dtype=float)
    if len(expected) != len(coordinates):
        raise ValueError("saved kpoint coordinates do not have the declared mesh size")
    used: set[int] = set()
    for row in coordinates:
        candidates = np.flatnonzero(np.all(np.isclose(expected, row, rtol=0.0, atol=1.0e-12), axis=1))
        if len(candidates) != 1 or int(candidates[0]) in used:
            raise ValueError("saved kpoint coordinates are not a complete uniform mesh")
        used.add(int(candidates[0]))
    reference = 1.0 / len(coordinates)
    if not np.allclose(weights, reference, rtol=0.0, atol=1.0e-12):
        raise ValueError("selected kpoint weights are not the complete uniform weights")
    return coordinates, weights, mesh, shift, float(np.max(np.abs(weights - reference)))


def _magnetic_input(request: Mapping[str, Any], nspin: int, atom_ids: list[Any]) -> tuple[np.ndarray | None, dict[str, Any] | None, list[str]]:
    if "magnetic_symmetry" not in request:
        return None, None, ["magnetic_symmetry"]
    magnetic = request["magnetic_symmetry"]
    if nspin == 1:
        if magnetic is not None:
            raise ValueError("nspin=1 transport requires magnetic_symmetry=null")
        return None, None, []
    if magnetic is None:
        return None, None, ["magnetic_symmetry"]
    missing = [f"magnetic_symmetry.{field}" for field in ("moments_muB_by_atom_id", "source_refs") if field not in magnetic]
    if missing:
        return None, magnetic, missing
    values = {str(key): float(value) for key, value in magnetic["moments_muB_by_atom_id"].items()}
    if set(values) != {str(value) for value in atom_ids}:
        raise ValueError("magnetic symmetry moments must cover the atom map exactly")
    if not magnetic["source_refs"]:
        return None, magnetic, ["magnetic_symmetry.source_refs"]
    return np.asarray([values[str(value)] for value in atom_ids], dtype=float), magnetic, []


def read_transport_source(request: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a saved electronic product to its original ABACUS task sources."""
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("unsupported transport request schema")
    if "electronic_path" not in request or "task_path" not in request:
        return {"schema": SCHEMA, "status": "unresolved", "missing": ["electronic_path", "task_path"]}
    electronic_path = Path(request["electronic_path"]).expanduser().resolve()
    task_dir = Path(request["task_path"]).expanduser().resolve()
    electronic = _read_json(electronic_path)
    task, result = _read_json(task_dir / "task.json"), _read_json(task_dir / "result.json")
    method, atom_map = _read_json(task_dir / "method.json"), _read_json(task_dir / "STRU.atom-map.json")
    from .electronic import _parse_input
    inputs = _parse_input(task_dir / "INPUT")
    if electronic.get("schema") != "mlcc.abacus-electronic.v001":
        raise ValueError("transport requires mlcc.abacus-electronic.v001")

    missing = _source_missing(request, electronic, result, task, method, atom_map, inputs)
    _identity("electronic/task", electronic, task, ("task_id", "scheduler_job_id", "method_set", "model_id", "model_version"), missing)
    _identity("result/task", result, task, ("task_id", "scheduler_job_id", "method_set"), missing)
    for field in ("model_id", "model_version"):
        if field in result and result[field] is not None and not _missing(task, field):
            _equal(f"result/task.{field}", result[field], task[field])
    _identity("method/task", method, task, ("method_set", "model_id"), missing)
    if _missing(method, "version"):
        missing.append("method.version")
    elif not _missing(task, "model_version"):
        _equal("method.version", method["version"], task["model_version"])
    _identity("atom-map/task", atom_map, task, ("model_id",), missing)
    if _missing(atom_map, "version"):
        missing.append("STRU.atom-map.json.version")
    elif not _missing(task, "model_version"):
        _equal("atom-map.version", atom_map["version"], task["model_version"])
    if "nspin" in electronic and "nspin" in method:
        _equal("electronic.nspin", electronic["nspin"], method["nspin"])
    if "nspin" in inputs and "nspin" in method:
        _equal("INPUT/method nspin", int(inputs["nspin"]), method["nspin"])
    if "stage" in electronic and "stage" in result and electronic["stage"] != result["stage"]:
        raise ValueError("electronic/result stage mismatch")
    for label, record, version_field in (
        ("task", task, "engine_version"),
        ("electronic", electronic, "engine_version"),
        ("method", method, "abacus_version_target"),
    ):
        if record.get("engine") not in (None, "abacus"):
            raise ValueError(f"{label}.engine must be abacus")
        if record.get(version_field) not in (None, "3.10.1"):
            raise ValueError(f"{label}.{version_field} must be 3.10.1")
    if method.get("stage") not in (None, "scf"):
        raise ValueError("transport source method stage must be scf")
    if electronic.get("stage") != "scf":
        missing.append("electronic.stage")
    if result.get("stage") != "scf":
        missing.append("result.stage")
    if result.get("electronic_converged") is not None and electronic.get("electronic_converged") is not None:
        _equal("result.electronic_converged", result["electronic_converged"], electronic["electronic_converged"])
    if result.get("native_completed") is not None and electronic.get("native_completed") is not None:
        _equal("result.native_completed", result["native_completed"], electronic["native_completed"])

    source: dict[str, Any] = {"schema": SCHEMA, "status": "unresolved", "missing": [],
        "task_id": task.get("task_id"), "model_id": task.get("model_id"), "model_version": task.get("model_version"),
        "method_set": task.get("method_set"), "scheduler_job_id": task.get("scheduler_job_id"),
        "task_path": str(task_dir), "electronic_path": str(electronic_path), "source_files": _source_files(electronic_path, task_dir),
        "electronic_source_files": electronic.get("source_files"), "method": dict(method),
        "scheduler_status": task.get("status"), "scheduler_state": task.get("scheduler_state"), "exit_code": task.get("exit_code"),
        "native_exit_code": electronic.get("native_exit_code"),
        "native_completed": electronic.get("native_completed"), "electronic_converged": electronic.get("electronic_converged"), "ionic_converged": result.get("ionic_converged"),
        "nspin": electronic.get("nspin"), "fermi_level_eV": electronic.get("fermi_level_eV"), "source_atom_ids": atom_map.get("source_atom_ids"), "abacus_order": atom_map.get("abacus_order")}
    if task.get("status") != "COMPLETED" or task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0" or result.get("status") not in (None, "COMPLETED"):
        missing.append("scheduler_completion")
    if electronic.get("native_completed") is not True:
        missing.append("electronic.native_completed")
    if electronic.get("electronic_converged") is not True:
        missing.append("electronic.electronic_converged")
    if electronic.get("array_order") != "spin,kpoint,band":
        missing.append("electronic.array_order")
    if electronic.get("kpoint_coordinate_system") != "direct_reciprocal_lattice":
        missing.append("electronic.kpoint_coordinate_system")
    if electronic.get("uniform_kmesh_verified") is not True:
        missing.append("electronic.uniform_kmesh_verified")
    if electronic.get("nspin") not in (1, 2):
        missing.append("electronic.nspin")
    if electronic.get("spin_degeneracy") != (2 if electronic.get("nspin") == 1 else 1):
        missing.append("electronic.spin_degeneracy")
    if electronic.get("occupation_capacity_per_spin_channel") != (2.0 if electronic.get("nspin") == 1 else 1.0):
        missing.append("electronic.occupation_capacity_per_spin_channel")
    if missing:
        source["missing"] = sorted(set(missing))
        return source

    atom_ids, symbols, positions, cell, pbc = _validate_atoms(result, atom_map)
    source.update({"atom_ids": atom_ids, "natoms": len(atom_ids), "symbols": symbols, "positions_angstrom": positions.tolist(), "cell_angstrom": cell.tolist(), "pbc": pbc})
    coordinates, weights, mesh, shift, weight_error = _validate_kmesh(electronic, request["kpoint_weight_field"])
    source.update({"kpoints": coordinates, "kpoint_weights": weights, "kpoint_mesh": mesh, "kpoint_mesh_shift": shift, "weight_reference": 1.0 / len(weights), "weight_max_abs_error": weight_error})
    magmom, magnetic, magnetic_missing = _magnetic_input(request, int(source["nspin"]), atom_ids)
    source.update({"magnetic_symmetry": magnetic, "magmom": magmom, "dosweight": 2.0 if source["nspin"] == 1 else 1.0})
    missing.extend(magnetic_missing)
    raw = np.asarray(electronic["band_energies_eV"], dtype=float)
    source["raw_band_energies_eV"] = raw
    source["band_energies_relative_eV"] = None
    if raw.ndim != 3 or raw.shape[0] != source["nspin"] or raw.shape[1] != len(coordinates):
        missing.append("electronic.band_energies_eV shape")
    elif source["nspin"] == 1:
        source["band_energies_relative_eV"] = raw[0] - float(source["fermi_level_eV"])
    else:
        relative = raw - float(source["fermi_level_eV"])
        source["band_energies_relative_eV"] = np.concatenate((relative[0], relative[1]), axis=1)
    source["missing"] = sorted(set(missing))
    source["status"] = "ready" if not source["missing"] else "unresolved"
    return source


def _backend_modules() -> tuple[Any, Any, Any, Any, str]:
    from BoltzTraP2 import bandlib, fite, sphere, units
    from BoltzTraP2.version import PROGRAM_VERSION
    if PROGRAM_VERSION != BACKEND_VERSION:
        raise ValueError(f"BoltzTraP2 version {PROGRAM_VERSION!r} differs from required {BACKEND_VERSION!r}")
    return bandlib, fite, sphere, units, PROGRAM_VERSION


def _power_factor(seebeck: np.ndarray, sigma_over_tau: np.ndarray) -> np.ndarray:
    return np.swapaxes(seebeck, -1, -2) @ sigma_over_tau @ seebeck


def _calculate_ready(source: Mapping[str, Any], parameters: Mapping[str, Any]) -> dict[str, Any]:
    bandlib, fite, sphere, units, backend_version = _backend_modules()
    from ase import Atoms
    temperatures = np.asarray(parameters["temperatures_K"], dtype=float)
    chemical_potentials = np.asarray(parameters["chemical_potentials_eV"], dtype=float)
    window = np.asarray(parameters["dos_energy_window_eV"], dtype=float)
    atoms = Atoms(symbols=source["symbols"], positions=np.asarray(source["positions_angstrom"]), cell=np.asarray(source["cell_angstrom"]), pbc=source["pbc"])
    lattvec = atoms.get_cell().T * units.Angstrom
    data = SimpleNamespace(kpoints=np.asarray(source["kpoints"]), ebands=np.asarray(source["band_energies_relative_eV"]).T * units.eV, mommat=None)
    data.get_lattvec = lambda: lattvec
    equivalences = sphere.get_equivalences(atoms, source["magmom"], int(parameters["equivalence_count"]))
    coeffs = fite.fitde3D(data, equivalences)
    eband, vvband, _ = fite.getBTPbands(equivalences, coeffs, lattvec, curvature=False, nworkers=1)
    fitted_source, _ = fite.getBands(data.kpoints, equivalences, lattvec, coeffs, curvature=False)
    residual_eV = (fitted_source - data.ebands) / units.eV
    epsilon, dos, vvdos, _ = bandlib.BTPDOS(eband, vvband, erange=tuple(float(value) * units.eV for value in window), npts=int(parameters["dos_bins"]), scattering_model="uniform_tau")
    mur = chemical_potentials * units.eV
    _, L0, L1, L2, _ = bandlib.fermiintegrals(epsilon, dos, vvdos, mur=mur, Tr=temperatures, dosweight=source["dosweight"])
    sigma, seebeck, kappa, _ = bandlib.calc_Onsager_coefficients(L0, L1, L2, mur, temperatures, float(abs(np.linalg.det(lattvec))))
    pf = _power_factor(seebeck, sigma)
    dimensions = 2 * np.max(np.abs(np.vstack(equivalences)), axis=0) + 1
    return {"tensors": {"seebeck": seebeck.tolist(), "sigma_over_tau": sigma.tolist(), "kappa_e_over_tau": kappa.tolist(), "power_factor_over_tau": pf.tolist()},
        "backend": {"name": "BoltzTraP2", "version": backend_version, "scattering_model": "uniform_tau", "call_chain": ["sphere.get_equivalences", "fite.fitde3D", "fite.getBTPbands(curvature=False,nworkers=1)", "bandlib.BTPDOS(scattering_model=uniform_tau)", "bandlib.fermiintegrals", "bandlib.calc_Onsager_coefficients"]},
        "grids": {"source_kpoint_mesh": list(source["kpoint_mesh"]), "source_kpoint_count": len(source["kpoints"]), "selected_weight_field": parameters["kpoint_weight_field"], "selected_weight_reference": source["weight_reference"], "selected_weight_max_abs_error": source["weight_max_abs_error"], "requested_equivalence_count": int(parameters["equivalence_count"]), "actual_equivalence_count": len(equivalences), "fft_shape": [int(value) for value in dimensions], "dos_bins_requested": int(parameters["dos_bins"]), "dos_bins_actual": int(len(epsilon)), "dos_energy_window_eV": window.tolist()},
        "fit": {"residual_method": "fite.getBands(curvature=False)", "source_residual_max_abs_eV": float(np.max(np.abs(residual_eV))), "source_residual_rmse_eV": float(np.sqrt(np.mean(residual_eV**2))), "source_residual_count": int(residual_eV.size)},
        "energy_reference": "native_fermi", "fermi_level_eV": source["fermi_level_eV"], "dosweight": source["dosweight"]}


def _product_base(source: Mapping[str, Any], parameters: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": SCHEMA, "task_id": source.get("task_id"), "model_id": source.get("model_id"), "model_version": source.get("model_version"), "method_set": source.get("method_set"), "method": source.get("method"), "scheduler_job_id": source.get("scheduler_job_id"), "task_path": source.get("task_path"), "electronic_path": source.get("electronic_path"), "source_files": source.get("source_files", {}), "electronic_source_files": source.get("electronic_source_files"), "status": "unresolved", "missing": [], "parameters": dict(parameters), "tensors": None, "units": dict(UNITS), "assumptions": {"band_model": "rigid_band", "relaxation_time": "constant_scalar_tau", "tau_value": None, "source": "saved ABACUS bands with BoltzTraP2 uniform_tau"}, "source_scheduler_status": source.get("scheduler_status"), "source_scheduler_state": source.get("scheduler_state"), "source_exit_code": source.get("exit_code"), "native_completed": source.get("native_completed"), "electronic_converged": source.get("electronic_converged"), "ionic_converged": source.get("ionic_converged"), "nspin": source.get("nspin")}


def calculate_transport(source: Mapping[str, Any], parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate tau-normalized transport tensors from one bound source."""
    product = _product_base(source, parameters)
    product["native_exit_code"] = source.get("native_exit_code")
    missing = list(source.get("missing", []))
    for field in ("temperatures_K", "chemical_potentials_eV", "dos_energy_window_eV", "dos_bins", "equivalence_count", "kpoint_weight_field"):
        if _missing(parameters, field):
            missing.append(field)
    if parameters.get("energy_reference") != "native_fermi":
        if "energy_reference" not in parameters:
            missing.append("energy_reference")
        else:
            raise ValueError("transport energy_reference must be native_fermi")
    if not missing:
        temperatures = [float(value) for value in parameters["temperatures_K"]]
        chemical_potentials = [float(value) for value in parameters["chemical_potentials_eV"]]
        window = [float(value) for value in parameters["dos_energy_window_eV"]]
        if not temperatures or any(value <= 0.0 or not math.isfinite(value) for value in temperatures):
            raise ValueError("temperatures_K must contain positive finite values")
        if not chemical_potentials or any(not math.isfinite(value) for value in chemical_potentials):
            raise ValueError("chemical_potentials_eV must contain finite values")
        if len(window) != 2 or not all(math.isfinite(value) for value in window) or window[0] >= window[1]:
            raise ValueError("dos_energy_window_eV must be an increasing pair")
        if any(value < window[0] or value > window[1] for value in chemical_potentials):
            raise ValueError("chemical potentials must lie inside dos_energy_window_eV")
        if int(parameters["dos_bins"]) < 2 or int(parameters["equivalence_count"]) < 1:
            raise ValueError("dos_bins and equivalence_count must be positive")
        if source.get("status") != "ready" or source.get("band_energies_relative_eV") is None:
            missing.append("source")
    if missing:
        product["missing"] = sorted(set(missing))
        return product
    product.update(_calculate_ready(source, parameters))
    product["status"], product["missing"] = "available", []
    return product


def build_transport(request_path: str | Path) -> dict[str, Any]:
    """Read a request file, bind its sources, and calculate the product."""
    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("unsupported transport request schema")
    request = dict(request)
    for field in ("electronic_path", "task_path"):
        path = Path(request[field])
        if not path.is_absolute():
            request[field] = str((request_file.parent / path).resolve())
    product = calculate_transport(read_transport_source(request), request)
    product["request_path"] = str(request_file)
    return product


__all__ = ["SCHEMA", "REQUEST_SCHEMA", "read_transport_source", "calculate_transport", "build_transport"]
