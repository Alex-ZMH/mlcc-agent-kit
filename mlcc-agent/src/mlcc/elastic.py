"""Public, clamped-ion elastic-strain helpers.

This module owns the geometry and post-processing contract for the first
elasticity slice of the MLCC workflow.  It deliberately does not submit jobs
or create task directories.  The task layer may consume the in-memory records
returned by :func:`plan_elastic_strains` and persist them alongside an
ABACUS task.

The strain convention is engineering Voigt order ``xx, yy, zz, yz, xz, xy``.
The three shear entries are engineering shears (``gamma``), so the
off-diagonal entries of the small-strain tensor are ``gamma / 2``.  The
geometry produced here is a static, clamped-ion slice: fractional positions
and atom IDs are held fixed.  It is not a relaxed-ion elastic tensor and does
not carry a finite-temperature interpretation.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.io import read

from .abacus import _convergence_marker, _parse_energy, _parse_stress, _read_stru
from .modeling import ModelArtifacts
from .strain import _method_physics, _native_physics
from .workflow import source_evidence


SCHEMA = "mlcc.elastic-analysis.v001"
PLAN_SCHEMA = "mlcc.elastic-strain-plan.v001"
STRAIN_SCHEMA = "mlcc.elastic-strain.v001"
ABACUS_VERSION = "3.10.1"
EV_PER_A3_TO_GPA = 160.21766208
VOIGT_ORDER = ("xx", "yy", "zz", "yz", "xz", "xy")
VOIGT_INDICES = ((0, 0), (1, 1), (2, 2), (1, 2), (0, 2), (0, 1))


def _voigt_array(value: Sequence[float], *, name: str = "strain_voigt") -> np.ndarray:
    """Validate and convert one six-component engineering Voigt vector."""

    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be a sequence of six finite numbers")
    try:
        raw = list(value)
    except TypeError as exc:
        raise TypeError(f"{name} must be a sequence of six finite numbers") from exc
    if len(raw) != 6:
        raise ValueError(f"{name} must contain exactly six values")
    if any(isinstance(item, (bool, np.bool_)) for item in raw):
        raise TypeError(f"{name} values must be real numbers, not booleans")
    try:
        result = np.asarray(raw, dtype=float)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} values must be real numbers") from exc
    if not np.isfinite(result).all():
        raise ValueError(f"{name} values must be finite")
    return result


def _atom_ids(atoms: Atoms) -> list[int]:
    if "atom_id" not in atoms.arrays:
        raise ValueError("elastic geometry requires an integer atom_id array")
    values = np.asarray(atoms.arrays["atom_id"])
    if not np.issubdtype(values.dtype, np.integer):
        raise ValueError("elastic geometry requires integer atom_id values")
    ids = [int(value) for value in values]
    if len(ids) != len(atoms) or len(set(ids)) != len(ids):
        raise ValueError("elastic geometry requires unique atom_id values")
    return ids


def _reference_model_record(reference_model: Any) -> Any:
    """Keep the model identity without copying an entire ModelArtifacts object."""

    if isinstance(reference_model, ModelArtifacts):
        return {"model_id": reference_model.model_id, "version": reference_model.version}
    if isinstance(reference_model, Mapping):
        return copy.deepcopy(dict(reference_model))
    if reference_model is None or isinstance(reference_model, str):
        return copy.deepcopy(reference_model)
    raise TypeError("reference_model must be a ModelArtifacts, mapping, string, or None")


def voigt_strain_model(
    atoms: Atoms,
    strain_voigt: Sequence[float],
    reference_model: Any = None,
) -> tuple[Atoms, dict[str, Any]]:
    """Apply a symmetric engineering-Voigt strain while fixing fractional sites.

    ABACUS/ASE cells are stored as rows.  With ``F = I + epsilon`` this gives
    ``cell' = cell @ F.T``.  Atom arrays and fractional coordinates are copied
    unchanged, including the stable ``atom_id`` array.
    """

    if not isinstance(atoms, Atoms):
        raise TypeError("atoms must be an ASE Atoms object")
    vector = _voigt_array(strain_voigt)
    epsilon = np.zeros((3, 3), dtype=float)
    epsilon[0, 0], epsilon[1, 1], epsilon[2, 2] = vector[:3]
    epsilon[1, 2] = epsilon[2, 1] = vector[3] / 2.0
    epsilon[0, 2] = epsilon[2, 0] = vector[4] / 2.0
    epsilon[0, 1] = epsilon[1, 0] = vector[5] / 2.0
    F = np.eye(3, dtype=float) + epsilon

    eigenvalues = np.linalg.eigvalsh(F)
    if not np.isfinite(eigenvalues).all() or np.any(eigenvalues <= 0.0):
        raise ValueError("strain deformation gradient F must be positive definite")

    reference_cell = np.asarray(atoms.cell.array, dtype=float)
    if reference_cell.shape != (3, 3) or not np.isfinite(reference_cell).all():
        raise ValueError("reference lattice must be a finite 3x3 cell")
    reference_volume = float(abs(np.linalg.det(reference_cell)))
    if not np.isfinite(reference_volume) or reference_volume <= 0.0:
        raise ValueError("reference lattice must have positive volume")
    derived_cell = reference_cell @ F.T
    derived_volume = float(abs(np.linalg.det(derived_cell)))
    if not np.isfinite(derived_volume) or derived_volume <= 0.0:
        raise ValueError("strained lattice must have positive volume")

    fractional = atoms.get_scaled_positions(wrap=False).copy()
    ids = _atom_ids(atoms)
    derived = atoms.copy()
    derived.set_cell(derived_cell, scale_atoms=False)
    derived.set_scaled_positions(fractional)

    record = {
        "schema": STRAIN_SCHEMA,
        "kind": "voigt_strain",
        "strain_type": "voigt",
        "voigt_order": list(VOIGT_ORDER),
        "strain_voigt": [float(value) for value in vector],
        "engineering_shear": True,
        "epsilon_tensor": epsilon.tolist(),
        "F": F.tolist(),
        "deformation_gradient": F.tolist(),
        "cell_update": "row_cell @ F.T",
        "F_eigenvalues": [float(value) for value in eigenvalues],
        "reference_model": _reference_model_record(reference_model),
        "reference_lattice_angstrom": reference_cell.tolist(),
        "derived_lattice_angstrom": derived_cell.tolist(),
        "reference_volume_A3": reference_volume,
        "derived_volume_A3": derived_volume,
        "detF": float(np.linalg.det(F)),
        "fractional_coordinates_fixed": True,
        "atom_ids": ids,
        "atom_ids_preserved": ids == _atom_ids(derived),
        "scope": "clamped-ion_fixed-fractional_static",
        "ionic_relaxation": "not_performed",
        "temperature_K": None,
    }
    return derived, record


def _amplitudes(amplitudes: float | Sequence[float]) -> list[float]:
    if isinstance(amplitudes, (str, bytes)):
        raise TypeError("amplitudes must be a positive number or sequence")
    if np.isscalar(amplitudes):
        values = [amplitudes]
    else:
        values = list(amplitudes)
    if not values:
        raise ValueError("amplitudes must contain at least one positive value")
    converted: list[float] = []
    for value in values:
        if isinstance(value, (bool, np.bool_)):
            raise TypeError("amplitudes must be real numbers")
        number = float(value)
        if not np.isfinite(number) or number <= 0.0:
            raise ValueError("amplitudes must be finite and positive")
        if number in converted:
            raise ValueError("amplitudes must not contain duplicates")
        converted.append(number)
    return converted


def plan_elastic_strains(
    model: ModelArtifacts,
    amplitudes: float | Sequence[float],
) -> dict[str, Any]:
    """Build an in-memory reference plus six-direction ± strain plan.

    No task directory or scheduler request is created.  The returned plan is
    JSON serializable: each entry carries the transformation request and the
    complete geometry record, while the task layer regenerates the structure
    through :func:`voigt_strain_model` during normal task preparation.
    """

    if not isinstance(model, ModelArtifacts):
        raise TypeError("model must be a ModelArtifacts instance")
    values = _amplitudes(amplitudes)
    model_reference = {"model_id": model.model_id, "version": model.version}
    _, reference_record = voigt_strain_model(
        model.atoms,
        [0.0] * 6,
        reference_model=model_reference,
    )
    reference = {
        "request_id": "reference",
        "kind": "reference",
        "strain_voigt": [0.0] * 6,
        "input_transformation": None,
        "record": reference_record,
    }
    requests: list[dict[str, Any]] = []
    for amplitude_index, amplitude in enumerate(values):
        for direction_index, direction in enumerate(VOIGT_ORDER):
            for sign_name, sign in (("minus", -1.0), ("plus", 1.0)):
                vector = np.zeros(6, dtype=float)
                vector[direction_index] = sign * amplitude
                _, record = voigt_strain_model(
                    model.atoms,
                    vector,
                    reference_model=model_reference,
                )
                requests.append(
                    {
                        "request_id": f"{sign_name}-{direction}-a{amplitude_index}",
                        "kind": "strained",
                        "direction": direction,
                        "direction_index": direction_index,
                        "sign": sign_name,
                        "amplitude": amplitude,
                        "amplitude_index": amplitude_index,
                        "strain_voigt": [float(value) for value in vector],
                        "input_transformation": {
                            "kind": "voigt_strain",
                            "strain_voigt": [float(value) for value in vector],
                        },
                        "record": record,
                    }
                )
    return {
        "schema": PLAN_SCHEMA,
        "scope": "clamped-ion_fixed-fractional_static",
        "ionic_relaxation": "not_performed",
        "temperature_K": None,
        "voigt_order": list(VOIGT_ORDER),
        "engineering_shear": True,
        "model": model_reference,
        "amplitudes": values,
        "reference": reference,
        "requests": requests,
        "request_count": len(requests) + 1,
    }


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


def _native_flag_matches(raw: Any, expected: Any) -> bool:
    """Compare a method boolean with ABACUS's 0/1 input spelling."""

    if expected is None:
        return raw is None
    if isinstance(expected, (bool, np.bool_)):
        return str(raw).strip().lower() in ({"1", "true"} if bool(expected) else {"0", "false"})
    return raw == str(expected)


def _native_input_compatibility(bundle: Mapping[str, Any]) -> bool:
    """Check the saved ABACUS INPUT against the saved method contract."""

    native = bundle["input"]
    method = bundle["method"]
    method_parameters = method.get("parameters", {})
    method_parameters = method_parameters if isinstance(method_parameters, Mapping) else {}
    try:
        # Elastic, neutral-defect and phonon consumers share this contract.
        # Charged SCF extraction has a separate native-electron-count check;
        # making its input writable does not qualify these downstream uses.
        neutral_charge = (
            float(method.get("net_charge", 0)) == 0.0
            and float(method.get("nelec", 0)) == 0.0
            and float(method.get("nelec_delta", 0)) == 0.0
            and float(native.get("nelec", 0)) == 0.0
            and float(native.get("nelec_delta", 0)) == 0.0
            and str(native.get("gate_flag", "0")).lower() in ("0", "false")
        )
        scalar_precision = (
            np.isclose(float(native.get("ecutwfc")), float(method_parameters.get("ecutwfc_Ry")), rtol=1.0e-12, atol=1.0e-12)
            and np.isclose(float(native.get("scf_thr")), float(method_parameters.get("scf_thr")), rtol=1.0e-12, atol=1.0e-12)
            and int(native.get("scf_nmax")) == int(method_parameters.get("scf_nmax"))
            and int(native.get("nbands")) == int(method_parameters.get("nbands"))
            and np.isclose(float(native.get("mixing_beta")), float(method_parameters.get("mixing_beta")), rtol=1.0e-12, atol=1.0e-12)
        )
        if method.get("occupations") == "smearing":
            occupation_precision = (
                native.get("smearing_method") == method.get("smearing_method")
                and np.isclose(float(native.get("smearing_sigma")), float(method_parameters.get("smearing_sigma_Ry")), rtol=1.0e-10, atol=1.0e-12)
            )
        elif method.get("occupations") == "fixed":
            occupation_precision = (
                native.get("smearing_method") == "fixed"
                and native.get("smearing_sigma") is None
                and method_parameters.get("smearing_sigma_Ry") is None
            )
        else:
            occupation_precision = False
        native_precision = bool(scalar_precision and occupation_precision and neutral_charge)
    except (TypeError, ValueError):
        native_precision = False
    return bool(
        native.get("calculation") == "scf"
        and native.get("dft_functional") == method.get("dft_functional")
        and native.get("basis_type") == method.get("basis_type")
        and native.get("ks_solver") == method.get("ks_solver")
        and native.get("nspin") == str(method.get("nspin"))
        and native.get("mixing_type") == method.get("mixing_type")
        and native.get("symmetry") == str(method.get("symmetry"))
        and _native_flag_matches(native.get("lspinorb"), method.get("lspinorb"))
        and _native_flag_matches(native.get("noncolin"), method.get("noncolin"))
        and native_precision
        and native.get("cal_stress") == "1"
    )


def _kpt_values(path: Path) -> dict[str, list[int]]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 4 or lines[0] != "K_POINTS" or lines[1] != "0" or lines[2] != "Gamma":
        raise ValueError(f"{path} must use the current four-line Gamma KPT format")
    fields = lines[3].split()
    if len(fields) != 6:
        raise ValueError(f"{path} Gamma KPT line must contain grid and offset")
    return {"grid": [int(value) for value in fields[:3]], "offset": [int(value) for value in fields[3:]]}


def _directory(path: str | Path) -> Path:
    value = Path(path)
    if value.is_file():
        if value.name != "task.json":
            raise ValueError(f"elastic task path must be a task directory or task.json: {value}")
        value = value.parent
    return value


def _load_bundle(path: str | Path) -> dict[str, Any]:
    directory = _directory(path)
    task = _json(directory / "task.json")
    method = _json(directory / "method.json")
    result = _json(directory / "result.json")
    input_values = _input_values(directory / "INPUT")
    kpt = _kpt_values(directory / "KPT")
    atoms = read(directory / "input.extxyz")
    atom_map_path = directory / "STRU.atom-map.json"
    atom_map = _json(atom_map_path) if atom_map_path.is_file() else None
    native_stru = _read_stru(directory / "STRU", atom_map) if atom_map is not None else None
    final_path = directory / "final.extxyz"
    # A parsed final structure is part of the result contract.  Reusing the
    # input/native STRU object would turn a missing result artifact into a
    # false geometry pass, so leave the final structure absent and let the
    # structural gate block the analysis.
    final_atoms = read(final_path) if final_path.is_file() else None
    suffix = str(method["suffix"])
    stage = str(method["stage"])
    output_directories = sorted(directory.glob(f"OUT.{suffix}"))
    if len(output_directories) != 1 or not output_directories[0].is_dir():
        raise ValueError(f"{directory} must have one native OUT.{suffix} directory")
    native_output_directory = output_directories[0]
    native_log = native_output_directory / f"running_{stage}.log"
    native_text = native_log.read_text(encoding="utf-8")
    native_lines = native_text.splitlines()
    native_energy_eV = _parse_energy(native_text)
    _, native_stress_GPa = _parse_stress(native_lines)
    native_electronic, _ = _convergence_marker(native_text, stage=stage)
    source_files = result.get("source_files")
    source_log = source_files.get(f"running_{stage}.log") if isinstance(source_files, Mapping) else None
    source_log_matches_native = (
        isinstance(source_log, str)
        and Path(source_log).resolve() == native_log.resolve()
    )
    try:
        result_stress = np.asarray(result.get("stress_GPa"), dtype=float)
        native_result_stress_match = bool(
            result_stress.shape == (3, 3)
            and np.allclose(result_stress, np.asarray(native_stress_GPa, dtype=float), rtol=0.0, atol=1.0e-9)
        )
    except (TypeError, ValueError):
        native_result_stress_match = False
    try:
        native_result_energy_match = bool(
            np.isclose(
                float(result.get("energy_eV")),
                float(native_energy_eV),
                rtol=0.0,
                atol=1.0e-8,
            )
        )
    except (TypeError, ValueError):
        native_result_energy_match = False
    native_result_electronic_match = result.get("electronic_converged") is native_electronic
    native_result_consistent = bool(
        source_log_matches_native
        and native_result_stress_match
        and native_result_energy_match
        and native_result_electronic_match
    )
    source_paths, invalid_sources, source_reason = source_evidence(
        result,
        directory / "result.json",
        engine="abacus",
    )
    directory_resolved = directory.resolve()
    source_paths_belong_to_task = all(
        path.resolve().is_relative_to(directory_resolved) for path in source_paths
    )
    return {
        "directory": directory,
        "task": task,
        "method": method,
        "result": result,
        "input": input_values,
        "kpt": kpt,
        "atoms": atoms,
        "native_stru": native_stru,
        "final_atoms": final_atoms,
        "final_structure_source": str(final_path) if final_path.is_file() else None,
        "native_output_directory": native_output_directory,
        "native_log": native_log,
        "native_energy_eV": native_energy_eV,
        "native_stress_GPa": native_stress_GPa,
        "native_result_energy_match": native_result_energy_match,
        "native_electronic_converged": native_electronic,
        "native_result_stress_match": native_result_stress_match,
        "native_result_electronic_match": native_result_electronic_match,
        "native_result_consistent": native_result_consistent,
        "atom_map": atom_map,
        "source_evidence": {
            "paths": [str(value) for value in source_paths],
            "invalid": [str(value) for value in invalid_sources],
            "reason": source_reason,
            "paths_belong_to_task": source_paths_belong_to_task,
        },
    }


def _task_entries(strained_task_paths: Mapping[str, str | Path] | Sequence[str | Path]) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(strained_task_paths, Mapping):
        return [(str(key), _load_bundle(value)) for key, value in strained_task_paths.items()]
    if isinstance(strained_task_paths, (str, bytes)):
        raise TypeError("strained_task_paths must be a sequence of task paths")
    entries: list[tuple[str, dict[str, Any]]] = []
    for value in strained_task_paths:
        bundle = _load_bundle(value)
        entries.append((str(bundle["task"].get("task_id", bundle["directory"])), bundle))
    return entries


def _engineering_from_F(F: np.ndarray) -> np.ndarray:
    epsilon = (F + F.T) / 2.0 - np.eye(3)
    return np.asarray(
        [epsilon[0, 0], epsilon[1, 1], epsilon[2, 2], 2.0 * epsilon[1, 2], 2.0 * epsilon[0, 2], 2.0 * epsilon[0, 1]],
        dtype=float,
    )


def _F_from_voigt(vector: Sequence[float]) -> np.ndarray:
    values = _voigt_array(vector)
    epsilon = np.zeros((3, 3), dtype=float)
    epsilon[0, 0], epsilon[1, 1], epsilon[2, 2] = values[:3]
    epsilon[1, 2] = epsilon[2, 1] = values[3] / 2.0
    epsilon[0, 2] = epsilon[2, 0] = values[4] / 2.0
    epsilon[0, 1] = epsilon[1, 0] = values[5] / 2.0
    return np.eye(3, dtype=float) + epsilon


def _requested_strain(task: Mapping[str, Any]) -> tuple[np.ndarray | None, str | None]:
    transformation = task.get("input_transformation")
    if not isinstance(transformation, Mapping):
        return None, None
    kind = transformation.get("kind")
    if kind == "voigt_strain":
        return _voigt_array(transformation["strain_voigt"], name="task strain_voigt"), "voigt_strain"
    if kind == "isotropic_strain":
        value = float(transformation["epsilon"])
        return np.asarray([value, value, value, 0.0, 0.0, 0.0], dtype=float), "isotropic_epsilon"
    raise ValueError("elastic analysis supports only explicit voigt_strain or isotropic_strain transformations")


def _geometry_record(
    reference: Atoms,
    candidate: Atoms,
    requested: np.ndarray | None,
    fractional_tolerance: float | None,
    strain_tolerance: float | None,
) -> dict[str, Any]:
    reference_cell = np.asarray(reference.cell.array, dtype=float)
    candidate_cell = np.asarray(candidate.cell.array, dtype=float)
    F = np.linalg.solve(reference_cell, candidate_cell).T
    actual = _engineering_from_F(F)
    expected_F = None if requested is None else _F_from_voigt(requested)
    F_delta = None if expected_F is None else float(np.max(np.abs(F - expected_F)))
    reference_fractional = reference.get_scaled_positions(wrap=False)
    candidate_fractional = candidate.get_scaled_positions(wrap=False)
    fractional_delta = (
        float(np.max(np.abs(candidate_fractional - reference_fractional)))
        if candidate_fractional.shape == reference_fractional.shape
        else None
    )
    reference_ids = _atom_ids(reference)
    candidate_ids = _atom_ids(candidate)
    symbols_same = candidate.get_chemical_symbols() == reference.get_chemical_symbols()
    pbc_same = candidate.pbc.tolist() == reference.pbc.tolist()
    ids_same = candidate_ids == reference_ids
    fixed_fractional = (
        symbols_same
        and pbc_same
        and ids_same
        and fractional_delta is not None
        and fractional_tolerance is not None
        and fractional_delta <= fractional_tolerance
    )
    strain_delta = None if requested is None else float(np.max(np.abs(actual - requested)))
    expected_geometry = (
        requested is not None
        and F_delta is not None
        and strain_tolerance is not None
        and F_delta <= strain_tolerance
    )
    determinant = float(np.linalg.det(F))
    return {
        "passed": bool(fixed_fractional and expected_geometry and np.isfinite(determinant) and determinant > 0.0),
        "fixed_fractional_coordinates": fixed_fractional,
        "fractional_max_abs_delta": fractional_delta,
        "fractional_tolerance": fractional_tolerance,
        "symbols_same": symbols_same,
        "pbc_same": pbc_same,
        "atom_ids_same": ids_same,
        "atom_ids": {"reference": reference_ids, "candidate": candidate_ids},
        "F": F.tolist(),
        "expected_F": None if expected_F is None else expected_F.tolist(),
        "detF": determinant,
        "actual_strain_voigt": actual.tolist(),
        "requested_strain_voigt": None if requested is None else requested.tolist(),
        "strain_max_abs_delta": strain_delta,
        "F_max_abs_delta": F_delta,
        "strain_tolerance": strain_tolerance,
        "requested_strain_available": requested is not None,
    }


def _structure_match(reference: Atoms, candidate: Atoms, fractional_tolerance: float | None, cell_tolerance: float | None) -> dict[str, Any]:
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
    symbols_same = candidate.get_chemical_symbols() == reference.get_chemical_symbols()
    pbc_same = candidate.pbc.tolist() == reference.pbc.tolist()
    ids_same = _atom_ids(candidate) == _atom_ids(reference)
    passed = bool(
        symbols_same
        and pbc_same
        and ids_same
        and fractional_delta is not None
        and fractional_tolerance is not None
        and fractional_delta <= fractional_tolerance
        and cell_delta is not None
        and cell_tolerance is not None
        and cell_delta <= cell_tolerance
    )
    return {
        "passed": passed,
        "symbols_same": symbols_same,
        "pbc_same": pbc_same,
        "atom_ids_same": ids_same,
        "fractional_max_abs_delta": fractional_delta,
        "fractional_tolerance": fractional_tolerance,
        "cell_max_abs_delta_A": cell_delta,
        "cell_tolerance_A": cell_tolerance,
        "atom_ids": {"reference": _atom_ids(reference), "candidate": _atom_ids(candidate)},
    }


def _stress_matrix(result: Mapping[str, Any]) -> np.ndarray:
    matrix = np.asarray(result["stress_GPa"], dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("result stress_GPa must be a finite 3x3 matrix")
    if result.get("stress_unit") != "GPa":
        raise ValueError("elastic analysis requires stress_GPa results")
    if result.get("stress_sign") != "abacus_printed":
        raise ValueError("elastic analysis requires the native ABACUS printed stress sign")
    return matrix


def _stress_voigt(result: Mapping[str, Any]) -> np.ndarray:
    matrix = _stress_matrix(result)
    return np.asarray([matrix[i, j] for i, j in VOIGT_INDICES], dtype=float)


def _atom_mapping_valid(bundle: Mapping[str, Any]) -> bool:
    atoms = bundle["atoms"]
    ids = _atom_ids(atoms)
    result_ids = bundle["result"].get("atom_ids")
    atom_map = bundle.get("atom_map")
    mapping_entries = atom_map.get("abacus_order") if isinstance(atom_map, Mapping) else None
    source_ids = atom_map.get("source_atom_ids") if isinstance(atom_map, Mapping) else None
    symbols = atoms.get_chemical_symbols()
    mapping_valid = (
        isinstance(atom_map, Mapping)
        and isinstance(source_ids, list)
        and source_ids == ids
        and isinstance(mapping_entries, list)
        and len(mapping_entries) == len(ids)
    )
    if mapping_valid:
        abacus_indices = [item.get("abacus_index") for item in mapping_entries if isinstance(item, Mapping)]
        source_indices = [item.get("source_index") for item in mapping_entries if isinstance(item, Mapping)]
        mapped_ids = [item.get("atom_id") for item in mapping_entries if isinstance(item, Mapping)]
        mapping_valid = (
            len(abacus_indices) == len(ids)
            and sorted(abacus_indices) == list(range(len(ids)))
            and len(source_indices) == len(ids)
            and sorted(source_indices) == list(range(len(ids)))
            and len(mapped_ids) == len(ids)
            and len(set(mapped_ids)) == len(ids)
            and set(mapped_ids) == set(ids)
            and all(
                item.get("atom_id") == ids[item.get("source_index")]
                and item.get("element") == symbols[item.get("source_index")]
                for item in mapping_entries
            )
        )
    return bool(result_ids == ids and mapping_valid)


def _H_from_direction(index: int) -> np.ndarray:
    if index < 0 or index >= len(VOIGT_INDICES):
        raise ValueError(f"invalid Voigt direction index: {index}")
    H = np.zeros((3, 3), dtype=float)
    i, j = VOIGT_INDICES[index]
    H[i, j] = 1.0
    if i != j:
        H[j, i] = 1.0
        H[i, j] = H[j, i] = 0.5
    return H


def _direction_key(vector: np.ndarray, tolerance: float | None) -> tuple[tuple[float, ...], float, int] | None:
    amplitude = float(np.max(np.abs(vector)))
    if not np.isfinite(amplitude) or (amplitude <= tolerance if tolerance is not None else amplitude == 0.0):
        return None
    first = int(np.flatnonzero(np.abs(vector) > (tolerance if tolerance is not None else 0.0))[0])
    sign = 1 if vector[first] > 0 else -1
    canonical = vector / (sign * amplitude)
    canonical[np.abs(canonical) < 1.0e-14] = 0.0
    return tuple(float(value) for value in np.round(canonical, 12)), amplitude, sign


def _threshold_value(thresholds: Mapping[str, Any], name: str) -> tuple[float | None, str | None]:
    if name not in thresholds:
        return None, f"missing threshold {name}"
    raw = thresholds[name]
    if isinstance(raw, (bool, np.bool_)):
        return None, f"threshold {name} must be a finite non-negative number"
    value = float(raw)
    if not np.isfinite(value) or value < 0.0:
        return None, f"threshold {name} must be a finite non-negative number"
    return value, None


def _path_is_traceable(raw: Any, context: Path) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    path = Path(raw)
    if path.is_absolute() and path.exists():
        return True
    for base in (Path.cwd(), context.parent, *context.resolve().parents):
        if (base / path).exists():
            return True
    return False


def _elastic_pair_groups(
    bundles: Sequence[tuple[str, Mapping[str, Any]]],
    requested_by_name: Mapping[str, np.ndarray | None],
    tolerance: float | None,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for name, _bundle in bundles:
        if name == "reference":
            continue
        requested = requested_by_name.get(name)
        if requested is None:
            continue
        direction = _direction_key(requested, tolerance)
        if direction is None:
            continue
        direction_vector, amplitude, sign = direction
        nonzero = np.flatnonzero(np.abs(np.asarray(direction_vector, dtype=float)) > 1.0e-10)
        if len(nonzero) != 1 or not np.isclose(direction_vector[int(nonzero[0])], 1.0, rtol=0.0, atol=1.0e-10):
            continue
        direction_index = int(nonzero[0])
        group_key = json.dumps([direction_vector, round(amplitude, 12)], separators=(",", ":"))
        group = groups.setdefault(
            group_key,
            {
                "direction": list(direction_vector),
                "direction_index": direction_index,
                "amplitude": amplitude,
                "minus": [],
                "plus": [],
            },
        )
        group["minus" if sign < 0 else "plus"].append(name)
    return groups


def _amplitude_slope_consistency(
    pair_groups: Mapping[str, Mapping[str, Any]],
    stress_vectors: Mapping[str, np.ndarray],
    calibration_multiplier: float | None,
    threshold_GPa: float | None,
) -> dict[str, Any]:
    """Compare Cauchy stress-difference slopes at every requested amplitude."""

    by_direction: dict[int, dict[float, Mapping[str, Any]]] = {index: {} for index in range(6)}
    for group in pair_groups.values():
        direction = np.asarray(group["direction"], dtype=float)
        matches = [index for index in range(6) if np.allclose(direction, np.eye(6)[index], rtol=0.0, atol=1.0e-10)]
        if len(matches) != 1:
            continue
        by_direction[matches[0]][float(group["amplitude"])] = group
    amplitudes = sorted({amplitude for groups in by_direction.values() for amplitude in groups})
    enough_amplitudes = len(amplitudes) >= 2
    direction_reports: dict[str, dict[str, Any]] = {}
    maximum_difference = 0.0
    complete = enough_amplitudes and calibration_multiplier is not None
    all_directions_complete = complete
    for index, direction_name in enumerate(VOIGT_ORDER):
        groups = by_direction[index]
        slopes: dict[str, list[float]] = {}
        direction_complete = complete and set(groups) >= set(amplitudes)
        for amplitude in amplitudes:
            group = groups.get(amplitude)
            if group is None or len(group.get("minus", [])) != 1 or len(group.get("plus", [])) != 1:
                direction_complete = False
                continue
            minus_name = group["minus"][0]
            plus_name = group["plus"][0]
            if minus_name not in stress_vectors or plus_name not in stress_vectors:
                direction_complete = False
                continue
            slope = calibration_multiplier * (
                np.asarray(stress_vectors[plus_name], dtype=float)
                - np.asarray(stress_vectors[minus_name], dtype=float)
            ) / (2.0 * amplitude)
            slopes[str(amplitude)] = [float(value) for value in slope]
        values = [np.asarray(value, dtype=float) for value in slopes.values()]
        if values:
            differences = [float(np.max(np.abs(value - values[0]))) for value in values[1:]]
            direction_difference = max(differences, default=0.0)
        else:
            direction_difference = None
        if direction_difference is None:
            direction_passed = False
        else:
            maximum_difference = max(maximum_difference, direction_difference)
            direction_passed = bool(
                direction_complete
                and threshold_GPa is not None
                and direction_difference <= float(threshold_GPa)
            )
        all_directions_complete = all_directions_complete and direction_complete
        direction_reports[direction_name] = {
            "slopes_GPa": slopes,
            "difference_max_GPa": direction_difference,
            "passed": direction_passed,
        }
    passed = bool(
        enough_amplitudes
        and calibration_multiplier is not None
        and threshold_GPa is not None
        and all_directions_complete
        and all(report["passed"] for report in direction_reports.values())
    )
    return {
        "amplitudes": amplitudes,
        "enough_amplitudes": enough_amplitudes,
        "maximum_difference_GPa": float(maximum_difference),
        "threshold_GPa": threshold_GPa,
        "directions": direction_reports,
        "passed": passed,
    }


def _fit_cij(strain_rows: Sequence[Sequence[float]], stress_rows: Sequence[Sequence[float]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Fit ``stress = Cij @ engineering_strain`` without symmetrizing Cij."""

    X = np.asarray(strain_rows, dtype=float)
    Y = np.asarray(stress_rows, dtype=float)
    if X.ndim != 2 or X.shape[1] != 6 or Y.shape != (X.shape[0], 6):
        raise ValueError("Cij fit requires strain and stress arrays with shape (n, 6)")
    coefficient, _, _, _ = np.linalg.lstsq(X, Y, rcond=None)
    Cij = coefficient.T
    predicted = X @ coefficient
    residual = Y - predicted
    return Cij, predicted, residual, float(np.linalg.cond(X))


def _energy_contract(bundles: Sequence[tuple[str, Mapping[str, Any]]]) -> tuple[bool, dict[str, Any]]:
    results = {name: bundle["result"] for name, bundle in bundles}
    units = {name: result.get("energy_unit") for name, result in results.items()}
    definitions = {name: result.get("energy_definition") for name, result in results.items()}
    defaults = {name: result.get("energy_default_definition") for name, result in results.items()}
    occupations = {name: result.get("occupations") for name, result in results.items()}
    passed = bool(
        all(value == "eV" for value in units.values())
        and len(set(definitions.values())) == 1
        and None not in definitions.values()
        and len(set(defaults.values())) == 1
        and None not in defaults.values()
        and len(set(occupations.values())) == 1
        and None not in occupations.values()
        and all(bundle.get("native_result_energy_match") is True for _, bundle in bundles)
    )
    return passed, {
        "units": units,
        "definitions": definitions,
        "defaults": defaults,
        "occupations": occupations,
        "native_result_energy_match": {
            name: bundle.get("native_result_energy_match") for name, bundle in bundles
        },
    }


def _actual_F(reference: Atoms, candidate: Atoms) -> np.ndarray:
    return np.linalg.solve(np.asarray(reference.cell.array, dtype=float), np.asarray(candidate.cell.array, dtype=float)).T


def _work_conjugate_stress(
    reference: Atoms,
    candidate: Atoms,
    result: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, float]:
    F = _actual_F(reference, candidate)
    determinant = float(np.linalg.det(F))
    if not np.isfinite(determinant) or determinant <= 0.0:
        raise ValueError("finite-strain calibration requires positive det(F)")
    sigma = _stress_matrix(result)
    P = determinant * sigma @ np.linalg.inv(F).T
    return F, P, determinant


def _derivative_comparison(
    derivative_GPa: float,
    predicted_GPa: float,
    signal_min_GPa: float,
    abs_error_GPa: float,
    relative_error: float,
    multiplier: float,
) -> dict[str, Any]:
    signed_prediction = multiplier * predicted_GPa
    error = abs(float(derivative_GPa) - signed_prediction)
    scale = max(abs(float(derivative_GPa)), abs(float(signed_prediction)))
    tolerance = float(abs_error_GPa) + float(relative_error) * scale
    signal = max(abs(float(derivative_GPa)), abs(float(predicted_GPa)))
    signal_identifiable = signal >= float(signal_min_GPa)
    return {
        "derivative_GPa": float(derivative_GPa),
        "predicted_work_conjugate_GPa": float(predicted_GPa),
        "signed_prediction_GPa": float(signed_prediction),
        "absolute_error_GPa": float(error),
        "relative_scale_GPa": float(scale),
        "allowed_error_GPa": float(tolerance),
        "signal_GPa": float(signal),
        "signal_identifiable": bool(signal_identifiable),
        "error_passed": bool(error <= tolerance),
        "passed": bool(signal_identifiable and error <= tolerance),
    }


def _tensor_calibration_from_bundles(
    bundles: Sequence[tuple[str, Mapping[str, Any]]],
    requested_by_name: Mapping[str, np.ndarray | None],
    threshold_values: Mapping[str, float | None],
    *,
    geometry_strain_tolerance: float | None,
) -> dict[str, Any]:
    """Recompute five-point tensor stress calibration from native task data."""

    reference_name, reference = bundles[0]
    groups = _elastic_pair_groups(bundles, requested_by_name, geometry_strain_tolerance)
    grouped_by_direction: dict[int, dict[float, dict[str, Any]]] = {index: {} for index in range(6)}
    for group in groups.values():
        grouped_by_direction[int(group["direction_index"])][float(group["amplitude"])] = group
    amplitudes = sorted({float(group["amplitude"]) for group in groups.values()})
    five_point_grid = bool(
        len(amplitudes) == 2
        and amplitudes[0] > 0.0
        and np.isclose(amplitudes[1], 2.0 * amplitudes[0], rtol=1.0e-8, atol=1.0e-12)
        and all(
            set(grouped_by_direction[index]) == set(amplitudes)
            and all(
                len(grouped_by_direction[index][amplitude]["minus"]) == 1
                and len(grouped_by_direction[index][amplitude]["plus"]) == 1
                for amplitude in amplitudes
            )
            for index in range(6)
        )
    )
    energy_ok, energy_detail = _energy_contract(bundles)
    stress_asymmetry: dict[str, float] = {}
    stress_ok = True
    native_result_ok = True
    for name, bundle in bundles:
        try:
            matrix = _stress_matrix(bundle["result"])
            asymmetry = float(np.max(np.abs(matrix - matrix.T)))
            stress_asymmetry[name] = asymmetry
            native_result_ok = native_result_ok and bundle.get("native_result_consistent") is True
            stress_ok = stress_ok and asymmetry <= float(threshold_values["native_stress_asymmetry_GPa"])
        except (KeyError, TypeError, ValueError):
            stress_ok = False
    method_physics = {name: _method_physics(bundle["method"]) for name, bundle in bundles}
    native_physics = {name: _native_physics(bundle["input"]) for name, bundle in bundles}
    physics_ok = bool(
        all(value == method_physics[reference_name] for value in method_physics.values())
        and all(value == native_physics[reference_name] for value in native_physics.values())
    )
    reference_atoms = reference["atoms"]
    reference_volume_A3 = float(abs(np.linalg.det(np.asarray(reference_atoms.cell.array, dtype=float))))
    if not np.isfinite(reference_volume_A3) or reference_volume_A3 <= 0.0:
        raise ValueError("tensor stress calibration requires positive reference volume")
    h = amplitudes[0] if amplitudes else None
    point_records: dict[str, dict[str, Any]] = {}
    candidate_results: dict[str, dict[str, Any]] = {
        "printed_trace": {"multiplier": 1.0, "directions": {}, "passed": False},
        "negative_printed_trace": {"multiplier": -1.0, "directions": {}, "passed": False},
    }
    all_directions_identifiable = True
    fd_consistency_ok = True
    calibration_abs = threshold_values["calibration_abs_error_GPa"]
    calibration_rel = threshold_values["calibration_relative_error"]
    signal_min = threshold_values["calibration_signal_min_GPa"]
    fd_consistency = threshold_values["calibration_fd_consistency_GPa"]
    if None in (calibration_abs, calibration_rel, signal_min, fd_consistency):
        calibration_thresholds_ok = False
    else:
        calibration_thresholds_ok = True
    for direction_index, direction_name in enumerate(VOIGT_ORDER):
        direction_report: dict[str, Any] = {
            "direction": direction_name,
            "direction_index": direction_index,
            "H": _H_from_direction(direction_index).tolist(),
            "amplitude_values": amplitudes,
            "passed": False,
            "candidate_comparisons": {},
        }
        if not five_point_grid or not stress_ok or not energy_ok:
            direction_report["status"] = (
                "missing_five_point_grid"
                if not five_point_grid
                else "native_stress_or_energy_contract_failed"
            )
            for candidate_name in candidate_results:
                candidate_results[candidate_name]["directions"][direction_name] = {"passed": False}
            point_records[direction_name] = direction_report
            all_directions_identifiable = False
            continue
        low_group = grouped_by_direction[direction_index][amplitudes[0]]
        high_group = grouped_by_direction[direction_index][amplitudes[1]]
        minus_h_name = low_group["minus"][0]
        plus_h_name = low_group["plus"][0]
        minus_2h_name = high_group["minus"][0]
        plus_2h_name = high_group["plus"][0]
        task_names = {
            "minus_2h": minus_2h_name,
            "minus_h": minus_h_name,
            "reference": reference_name,
            "plus_h": plus_h_name,
            "plus_2h": plus_2h_name,
        }
        energies = {
            key: float((dict(bundles)[name])["result"]["energy_eV"])
            for key, name in task_names.items()
        }
        derivative_values = {
            "minus_h": (energies["reference"] - energies["minus_2h"]) / (2.0 * amplitudes[0] * reference_volume_A3) * EV_PER_A3_TO_GPA,
            "zero": (energies["plus_h"] - energies["minus_h"]) / (2.0 * amplitudes[0] * reference_volume_A3) * EV_PER_A3_TO_GPA,
            "plus_h": (energies["plus_2h"] - energies["reference"]) / (2.0 * amplitudes[0] * reference_volume_A3) * EV_PER_A3_TO_GPA,
        }
        point_to_task = {"minus_h": minus_h_name, "zero": reference_name, "plus_h": plus_h_name}
        point_reports: dict[str, Any] = {}
        H = _H_from_direction(direction_index)
        predicted_values: dict[str, float] = {}
        for point_name, task_name in point_to_task.items():
            bundle = dict(bundles)[task_name]
            F, P, determinant = _work_conjugate_stress(reference_atoms, bundle["atoms"], bundle["result"])
            predicted = float(np.sum(P * H))
            predicted_values[point_name] = predicted
            point_reports[point_name] = {
                "task_id": bundle["task"].get("task_id"),
                "eta": 0.0 if point_name == "zero" else (amplitudes[0] if point_name == "plus_h" else -amplitudes[0]),
                "energy_eV": energies["reference"] if point_name == "zero" else energies[point_name],
                "F": F.tolist(),
                "detF": float(determinant),
                "stress_GPa": _stress_matrix(bundle["result"]).tolist(),
                "P_GPa": P.tolist(),
                "H_contract_GPa": predicted,
                "energy_derivative_GPa": float(derivative_values[point_name]),
            }
        derivative_two_h = (
            (energies["plus_2h"] - energies["minus_2h"])
            / (4.0 * amplitudes[0] * reference_volume_A3)
            * EV_PER_A3_TO_GPA
        )
        fd_error = abs(derivative_values["zero"] - derivative_two_h)
        fd_consistency_ok = fd_consistency_ok and bool(
            fd_consistency is not None and fd_error <= float(fd_consistency)
        )
        direction_report.update(
            {
                "tasks": task_names,
                "points": point_reports,
                "energy_derivative_GPa": derivative_values,
                "work_conjugate_GPa": predicted_values,
                "finite_difference_two_h_derivative_GPa": float(derivative_two_h),
                "finite_difference_consistency_error_GPa": float(fd_error),
                "finite_difference_consistency_passed": bool(
                    fd_consistency is not None and fd_error <= float(fd_consistency)
                ),
            }
        )
        for candidate_name, candidate in candidate_results.items():
            comparisons = {
                point_name: _derivative_comparison(
                    derivative_values[point_name],
                    predicted_values[point_name],
                    float(signal_min) if signal_min is not None else float("inf"),
                    float(calibration_abs) if calibration_abs is not None else float("inf"),
                    float(calibration_rel) if calibration_rel is not None else float("inf"),
                    float(candidate["multiplier"]),
                )
                for point_name in ("minus_h", "zero", "plus_h")
            }
            candidate_passed = bool(
                calibration_thresholds_ok
                and all(item["error_passed"] for item in comparisons.values())
                and any(item["signal_identifiable"] for item in comparisons.values())
            )
            candidate["directions"][direction_name] = {
                "passed": candidate_passed,
                "comparisons": comparisons,
            }
            direction_report["candidate_comparisons"][candidate_name] = {
                "passed": candidate_passed,
                "comparisons": comparisons,
            }
        for point_name, comparison in direction_report["candidate_comparisons"]["printed_trace"]["comparisons"].items():
            direction_report["points"][point_name]["signal_identifiable"] = comparison["signal_identifiable"]
            direction_report["points"][point_name]["error_passed"] = comparison["error_passed"]
        direction_passed = bool(
            calibration_thresholds_ok
            and fd_consistency is not None
            and fd_error <= float(fd_consistency)
            and any(candidate_results[name]["directions"][direction_name]["passed"] for name in candidate_results)
        )
        direction_report["passed"] = direction_passed
        direction_report["status"] = "passed" if direction_passed else "failed"
        signal_values = [
            comparison["signal_GPa"]
            for comparison in direction_report["candidate_comparisons"]["printed_trace"]["comparisons"].values()
        ]
        signal_ok = bool(signal_values) and signal_min is not None and max(signal_values) >= float(signal_min)
        direction_report["signal_identifiable"] = signal_ok
        all_directions_identifiable = all_directions_identifiable and signal_ok
        point_records[direction_name] = direction_report
    for candidate in candidate_results.values():
        candidate["passed"] = bool(
            calibration_thresholds_ok
            and five_point_grid
            and energy_ok
            and stress_ok
            and native_result_ok
            and physics_ok
            and all(direction.get("passed") for direction in candidate["directions"].values())
        )
    passing_sign_candidates = [name for name, candidate in candidate_results.items() if candidate["passed"]]
    sign_determined = len(passing_sign_candidates) == 1 and all_directions_identifiable
    if not five_point_grid or not native_result_ok or not energy_ok or not stress_ok:
        sign_status = "blocked"
    elif len(passing_sign_candidates) == 2 or not all_directions_identifiable:
        sign_status = "indeterminate"
    else:
        sign_status = "determined" if sign_determined else "indeterminate"
    full_tensor = bool(
        sign_determined
        and five_point_grid
        and energy_ok
        and stress_ok
        and native_result_ok
        and physics_ok
        and fd_consistency_ok
    )
    checks = {
        "five_point_grid": {"value": {"amplitudes": amplitudes, "expected": [h, None if h is None else 2.0 * h]}, "passed": five_point_grid},
        "energy_contract": {"value": energy_detail, "passed": energy_ok},
        "native_stress_symmetry": {"value": stress_asymmetry, "passed": stress_ok},
        "native_result_consistency": {"value": {name: bundle.get("native_result_consistent") for name, bundle in bundles}, "passed": native_result_ok},
        "same_method_physics": {"value": method_physics, "passed": all(value == method_physics[reference_name] for value in method_physics.values())},
        "same_native_input_physics": {"value": native_physics, "passed": all(value == native_physics[reference_name] for value in native_physics.values())},
        "finite_difference_consistency": {
            "value": {name: record.get("finite_difference_consistency_error_GPa") for name, record in point_records.items()},
            "passed": fd_consistency_ok,
        },
        "signal_identifiable": {"value": {name: record.get("signal_identifiable", False) for name, record in point_records.items()}, "passed": all_directions_identifiable},
        "candidate_signs": {"value": candidate_results, "passed": sign_determined},
    }
    return {
        "schema": "mlcc.elastic-stress-calibration.v002",
        "kind": "tensor_energy_derivative",
        "scope": "clamped-ion_fixed-fractional_static",
        "stress_measure": "cauchy",
        "stress_work_conjugate": "P=det(F) sigma F^-T",
        "voigt_order": list(VOIGT_ORDER),
        "engineering_shear": True,
        "energy_to_GPa": EV_PER_A3_TO_GPA,
        "reference_task": str(reference["directory"]),
        "source_tasks": {name: str(bundle["directory"]) for name, bundle in bundles},
        "source_evidence": {name: bundle["source_evidence"] for name, bundle in bundles},
        "reference_model": {
            "model_id": reference["task"].get("model_id"),
            "version": reference["task"].get("model_version"),
            "task_id": reference["task"].get("task_id"),
        },
        "engine": "abacus",
        "engine_version": ABACUS_VERSION,
        "method_physics": method_physics,
        "native_physics": native_physics,
        "reference_volume_A3": reference_volume_A3,
        "amplitudes": amplitudes,
        "directions": point_records,
        "candidate_signs": candidate_results,
        "passing_sign_candidates": passing_sign_candidates,
        "sign_determined": sign_determined,
        "sign_status": sign_status,
        "stress_sign_qualification": sign_determined,
        "full_tensor_stress_calibration": full_tensor,
        "tensor_qualification": full_tensor,
        "shear_qualification": bool(full_tensor and all(point_records.get(name, {}).get("passed") for name in VOIGT_ORDER[3:])),
        "production_qualification": False,
        "checks": checks,
        "thresholds": dict(threshold_values),
        "physics_comparable": physics_ok,
        "status": "passed" if full_tensor else "blocked",
        "issues": [] if full_tensor else [name + " failed" for name, item in checks.items() if item.get("passed") is not True],
    }


def _tensor_task_preflight(
    bundles: Sequence[tuple[str, Mapping[str, Any]]],
    requested_by_name: Mapping[str, np.ndarray | None],
    threshold_values: Mapping[str, float | None],
) -> dict[str, Any]:
    """Run the task/native gates required before tensor calibration.

    This is deliberately the same evidence boundary used by the analyzer:
    task metadata, native INPUT/STRU/output, and the saved result all have to
    describe one completed ABACUS SCF.  The tensor math itself is kept in
    ``_tensor_calibration_from_bundles`` so that a calibration report cannot
    turn a mutated or incomplete task set into a qualified result.
    """

    reference_name, reference = bundles[0]
    method_physics = {name: _method_physics(bundle["method"]) for name, bundle in bundles}
    native_physics = {name: _native_physics(bundle["input"]) for name, bundle in bundles}
    kpoints = {name: bundle["kpt"] for name, bundle in bundles}
    scheduler: dict[str, bool] = {}
    source: dict[str, bool] = {}
    electronic: dict[str, bool] = {}
    native_input: dict[str, bool] = {}
    stress: dict[str, bool] = {}
    atom_mapping: dict[str, bool] = {}
    result_consistency: dict[str, bool] = {}
    identity: dict[str, bool] = {}
    for name, bundle in bundles:
        task = bundle["task"]
        method = bundle["method"]
        result = bundle["result"]
        scheduler[name] = task.get("scheduler_state") == "COMPLETED" and task.get("exit_code") == "0:0"
        source[name] = (
            bundle["source_evidence"].get("reason") == "complete"
            and bundle["source_evidence"].get("paths_belong_to_task") is True
        )
        electronic[name] = result.get("electronic_converged") is True
        native_input[name] = _native_input_compatibility(bundle)
        result_consistency[name] = bundle.get("native_result_consistent") is True
        atom_mapping[name] = _atom_mapping_valid(bundle)
        try:
            _stress_matrix(result)
            stress[name] = True
        except (KeyError, TypeError, ValueError):
            stress[name] = False
        identity[name] = bool(
            task.get("task_id") == result.get("task_id")
            and task.get("scheduler_job_id") == result.get("scheduler_job_id")
            and task.get("model_id") == method.get("model_id")
            and task.get("model_version") == method.get("version")
            and task.get("method_set") == method.get("method_set") == result.get("method_set")
        )
    identity[reference_name] = bool(
        identity[reference_name]
        and reference["task"].get("model_id") == reference["method"].get("model_id")
        and reference["task"].get("model_version") == reference["method"].get("version")
    )
    for name, bundle in bundles[1:]:
        identity[name] = bool(
            identity[name]
            and bundle["task"].get("model_id") == reference["task"].get("model_id")
            and bundle["task"].get("model_version") == reference["task"].get("model_version")
            and bundle["method"].get("model_id") == reference["method"].get("model_id")
            and bundle["method"].get("version") == reference["method"].get("version")
        )

    static_scf_stage = all(
        bundle["task"].get("calculation") == "scf"
        and bundle["method"].get("stage") == "scf"
        and bundle["result"].get("stage") == "scf"
        for _, bundle in bundles
    )
    same_engine = all(
        bundle["task"].get("engine") == "abacus"
        and bundle["method"].get("engine") == "abacus"
        and bundle["task"].get("engine_version") == ABACUS_VERSION
        and bundle["method"].get("abacus_version_target") == ABACUS_VERSION
        for _, bundle in bundles
    )
    same_method_physics = all(value == method_physics[reference_name] for value in method_physics.values())
    same_native_physics = all(value == native_physics[reference_name] for value in native_physics.values())
    same_kpoints = all(value == kpoints[reference_name] for value in kpoints.values())
    method_kpoints = all(
        list(bundle["method"].get("kpoints", [])) == bundle["kpt"].get("grid")
        for _, bundle in bundles
    )
    reference_method_set = reference["method"].get("method_set")
    strained_method_sets = {bundle["method"].get("method_set") for _, bundle in bundles[1:]}
    method_set_lineage = (
        len(strained_method_sets) <= 1
        and (
            not strained_method_sets
            or reference_method_set in strained_method_sets
            or all(bundle["method"].get("parent_method_set") == reference_method_set for _, bundle in bundles[1:])
        )
    )

    geometry: dict[str, dict[str, Any]] = {}
    requested_reference = requested_by_name.get(reference_name, np.zeros(6, dtype=float))
    geometry[reference_name] = _geometry_record(
        reference["atoms"],
        reference["atoms"],
        requested_reference,
        threshold_values["fractional_tolerance"],
        threshold_values["strain_tolerance"],
    )
    for name, bundle in bundles[1:]:
        geometry[name] = _geometry_record(
            reference["atoms"],
            bundle["atoms"],
            requested_by_name.get(name),
            threshold_values["fractional_tolerance"],
            threshold_values["strain_tolerance"],
        )
    geometry_ok = all(item["passed"] for item in geometry.values())

    native_geometry: dict[str, dict[str, Any]] = {}
    for name, bundle in bundles:
        cell_tolerance = None
        if threshold_values["strain_tolerance"] is not None:
            cell_tolerance = threshold_values["strain_tolerance"] * float(np.max(np.abs(bundle["atoms"].cell.array)))
        native_stru = bundle["native_stru"]
        final_atoms = bundle["final_atoms"]
        native_stru_check = (
            _structure_match(bundle["atoms"], native_stru, threshold_values["fractional_tolerance"], cell_tolerance)
            if native_stru is not None
            else {"passed": False, "reason": "missing_native_STRU"}
        )
        final_check = (
            _structure_match(bundle["atoms"], final_atoms, threshold_values["fractional_tolerance"], cell_tolerance)
            if final_atoms is not None
            else {"passed": False, "reason": "missing_final_static_structure"}
        )
        native_geometry[name] = {
            "native_STRU": native_stru_check,
            "final_static_structure": final_check,
            "passed": bool(native_stru_check["passed"] and final_check["passed"]),
        }
    native_geometry_ok = all(item["passed"] for item in native_geometry.values())
    threshold_names = (
        "fractional_tolerance",
        "strain_tolerance",
        "reference_stress_GPa",
        "linearity_residual_GPa",
        "condition_number_max",
        "asymmetry_GPa",
        "calibration_abs_error_GPa",
        "calibration_relative_error",
        "calibration_signal_min_GPa",
        "calibration_fd_consistency_GPa",
        "amplitude_slope_difference_GPa",
        "native_stress_asymmetry_GPa",
    )
    thresholds_explicit = all(threshold_values.get(name) is not None for name in threshold_names)
    checks = {
        "native_scheduler_completed_0": all(scheduler.values()),
        "native_source_evidence": all(source.values()),
        "electronic_converged": all(electronic.values()),
        "identity": all(identity.values()),
        "same_engine_version": same_engine,
        "static_scf_stage": static_scf_stage,
        "same_method_physics": same_method_physics,
        "same_native_input_physics": same_native_physics,
        "same_kpoints": same_kpoints and method_kpoints,
        "method_set_lineage": method_set_lineage,
        "atom_mapping": all(atom_mapping.values()),
        "fixed_fractional_geometry": geometry_ok,
        "native_stru_and_final_geometry": native_geometry_ok,
        "native_input_compatibility": all(native_input.values()),
        "native_result_consistency": all(result_consistency.values()),
        "stress_units_and_native_sign": all(stress.values()),
        "thresholds_explicit": thresholds_explicit,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "scheduler_by_task": scheduler,
        "source_evidence_by_task": source,
        "electronic_converged_by_task": electronic,
        "identity_by_task": identity,
        "native_input_compatibility_by_task": native_input,
        "native_result_consistency_by_task": result_consistency,
        "atom_mapping_by_task": atom_mapping,
        "geometry": geometry,
        "native_geometry": native_geometry,
        "method_physics": method_physics,
        "native_physics": native_physics,
        "kpoints": kpoints,
    }


def _same_task_paths(left: Any, right: Mapping[str, str], context: Path | None = None) -> bool:
    if not isinstance(left, Mapping) or set(left) != set(right):
        return False
    bases = [Path.cwd()]
    if context is not None:
        bases = [context.parent, *context.resolve().parents, *bases]

    def resolve(raw: Any) -> Path:
        path = Path(str(raw))
        if path.is_absolute():
            return path.resolve()
        for base in bases:
            candidate = (base / path).resolve()
            if candidate.exists():
                return candidate
        return path.resolve()

    return all(resolve(left[name]) == resolve(path) for name, path in right.items())


def _calibration_binding(
    calibration: Mapping[str, Any],
    reference: dict[str, Any],
    calibration_path: Path,
    *,
    bundles: Sequence[tuple[str, Mapping[str, Any]]] | None = None,
    requested_by_name: Mapping[str, np.ndarray | None] | None = None,
    threshold_values: Mapping[str, float | None] | None = None,
    geometry_strain_tolerance: float | None = None,
    preflight_passed: bool = False,
) -> dict[str, Any]:
    checks = calibration.get("checks")
    checks = checks if isinstance(checks, Mapping) else {}
    source_tasks = calibration.get("source_tasks")
    source_tasks_ok = isinstance(source_tasks, Mapping) and bool(source_tasks) and all(
        _path_is_traceable(value, calibration_path) for value in source_tasks.values()
    )
    source_evidence = calibration.get("source_evidence")
    source_evidence_ok = isinstance(source_evidence, Mapping) and bool(source_evidence) and all(
        isinstance(value, Mapping) and value.get("reason") == "complete" and bool(value.get("paths"))
        for value in source_evidence.values()
    )
    method_check = checks.get("same_method_physics")
    method_values = method_check.get("value") if isinstance(method_check, Mapping) else None
    method_values = method_values if isinstance(method_values, Mapping) else {}
    method_physics_ok = bool(method_values) and all(value == reference["method_physics"] for value in method_values.values())
    native_check = checks.get("same_native_input_physics")
    native_values = native_check.get("value") if isinstance(native_check, Mapping) else None
    native_values = native_values if isinstance(native_values, Mapping) else {}
    native_physics_ok = bool(native_values) and all(value == reference["native_physics"] for value in native_values.values())
    check_passed = lambda name: isinstance(checks.get(name), Mapping) and checks[name].get("passed") is True
    calibration_sign = (
        calibration.get("stress_sign_qualification") is True
        and calibration.get("sign_determined") is True
        and isinstance(calibration.get("passing_sign_candidates"), list)
        and len(calibration["passing_sign_candidates"]) == 1
        and calibration["passing_sign_candidates"][0] in {"printed_trace", "negative_printed_trace"}
    )
    engine_ok = calibration.get("engine") == "abacus" and calibration.get("engine_version") == ABACUS_VERSION
    physics_ok = calibration.get("physics_comparable") is True and method_physics_ok and native_physics_ok
    recomputed: dict[str, Any] | None = None
    calibration_kind = calibration.get("kind")
    tensor_schema_ok = calibration.get("schema") == "mlcc.elastic-stress-calibration.v002"
    native_source_evidence = source_evidence_ok and check_passed("native_source_evidence")
    same_method_physics = method_physics_ok and check_passed("same_method_physics")
    same_native_input_physics = native_physics_ok and check_passed("same_native_input_physics")
    if (
        tensor_schema_ok
        and calibration_kind == "tensor_energy_derivative"
        and bundles is not None
        and requested_by_name is not None
        and threshold_values is not None
    ):
        recomputed = _tensor_calibration_from_bundles(
            bundles,
            requested_by_name,
            threshold_values,
            geometry_strain_tolerance=geometry_strain_tolerance,
        )
        current_source_tasks = {name: str(bundle["directory"]) for name, bundle in bundles}
        source_tasks_ok = source_tasks_ok and _same_task_paths(source_tasks, current_source_tasks, calibration_path)
        report_reference = calibration.get("reference_task")
        source_tasks_ok = source_tasks_ok and (
            isinstance(report_reference, str)
            and Path(report_reference).resolve() == Path(current_source_tasks["reference"]).resolve()
        )
        current_source_evidence_ok = all(
            bundle["source_evidence"].get("reason") == "complete"
            and bundle["source_evidence"].get("paths_belong_to_task") is True
            for _, bundle in bundles
        )
        source_evidence_ok = bool(
            source_evidence_ok
            and current_source_evidence_ok
            and set(source_evidence or {}) == set(current_source_tasks)
        )
        current_engine_ok = all(
            bundle["task"].get("engine") == "abacus"
            and bundle["method"].get("engine") == "abacus"
            and bundle["task"].get("engine_version") == ABACUS_VERSION
            and bundle["method"].get("abacus_version_target") == ABACUS_VERSION
            for _, bundle in bundles
        )
        engine_ok = bool(engine_ok and current_engine_ok)
        method_physics_ok = recomputed["checks"]["same_method_physics"]["passed"] is True
        native_physics_ok = recomputed["checks"]["same_native_input_physics"]["passed"] is True
        physics_ok = recomputed["physics_comparable"] is True and method_physics_ok and native_physics_ok
        native_source_evidence = bool(source_evidence_ok and preflight_passed)
        same_method_physics = bool(method_physics_ok and preflight_passed)
        same_native_input_physics = bool(native_physics_ok and preflight_passed)
        calibration_sign = bool(recomputed["sign_determined"] is True and preflight_passed)
        calibration_tensor_qualification = bool(recomputed["tensor_qualification"] is True and preflight_passed)
        calibration_shear_qualification = bool(recomputed["shear_qualification"] is True and preflight_passed)
        full_tensor_stress_calibration = bool(recomputed["full_tensor_stress_calibration"] and preflight_passed)
        stress_multiplier = (
            -1.0 if calibration_sign and recomputed["passing_sign_candidates"][0] == "negative_printed_trace"
            else 1.0 if calibration_sign else None
        )
        valid = bool(source_tasks_ok and source_evidence_ok and engine_ok and physics_ok and calibration_sign and preflight_passed)
        evidence_missing = False
    else:
        calibration_tensor_qualification = calibration.get("tensor_qualification") is True
        calibration_shear_qualification = calibration.get("shear_qualification") is True
        # The historical isotropic trace report can never qualify a full
        # tensor or shear response.  It remains useful as a blocked audit
        # record and as a source of no stress multiplier when it fails.
        full_tensor_stress_calibration = False
        stress_multiplier = (
            -1.0 if calibration_sign and calibration["passing_sign_candidates"][0] == "negative_printed_trace"
            else 1.0 if calibration_sign else None
        )
        valid = bool(source_tasks_ok and source_evidence_ok and engine_ok and physics_ok and calibration_sign)
        evidence_missing = True
    return {
        "source_tasks": source_tasks,
        "source_tasks_traceable": source_tasks_ok,
        "source_evidence": source_evidence,
        "native_source_evidence": native_source_evidence,
        "engine": calibration.get("engine"),
        "engine_version": calibration.get("engine_version"),
        "engine_match": engine_ok,
        "same_method_physics": same_method_physics,
        "same_native_input_physics": same_native_input_physics,
        "physics_comparable": physics_ok,
        "stress_sign_qualification": bool(calibration_sign),
        "sign_determined": bool(calibration_sign),
        "sign_status": (
            "blocked"
            if recomputed is not None and not preflight_passed
            else recomputed.get("sign_status") if recomputed is not None else calibration.get("sign_status")
        ),
        "passing_sign_candidates": (
            recomputed.get("passing_sign_candidates")
            if recomputed is not None
            else calibration.get("passing_sign_candidates")
        ),
        "tensor_qualification": calibration_tensor_qualification,
        "shear_qualification": calibration_shear_qualification,
        "full_tensor_stress_calibration": full_tensor_stress_calibration,
        "full_tensor_calibration_evidence_missing": evidence_missing,
        "recomputed": recomputed,
        "valid": valid,
        "stress_multiplier": stress_multiplier,
    }


def calibrate_tensor_stress(
    reference_task: str | Path,
    strained_task_paths: Mapping[str, str | Path] | Sequence[str | Path],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the v002 full-tensor stress calibration from native tasks.

    The protocol consumes one reference and six-direction ``±h``/``±2h``
    tasks (25 tasks total including the reference).  It reads native output
    and the saved structures again, so a cached report's ``passed`` fields
    cannot qualify a changed task directory.  This function performs no
    scheduler or filesystem mutation.
    """

    if not isinstance(thresholds, Mapping):
        raise TypeError("thresholds must be a mapping with explicit numeric limits")
    threshold_specs = (
        "fractional_tolerance",
        "strain_tolerance",
        "reference_stress_GPa",
        "linearity_residual_GPa",
        "condition_number_max",
        "asymmetry_GPa",
        "calibration_abs_error_GPa",
        "calibration_relative_error",
        "calibration_signal_min_GPa",
        "calibration_fd_consistency_GPa",
        "amplitude_slope_difference_GPa",
        "native_stress_asymmetry_GPa",
    )
    threshold_values: dict[str, float | None] = {}
    threshold_issues: list[str] = []
    for name in threshold_specs:
        value, issue = _threshold_value(thresholds, name)
        threshold_values[name] = value
        if issue is not None:
            threshold_issues.append(issue)
    reference = _load_bundle(reference_task)
    entries = _task_entries(strained_task_paths)
    bundles = [("reference", reference), *entries]
    requested_by_name: dict[str, np.ndarray | None] = {"reference": np.zeros(6, dtype=float)}
    for name, bundle in entries:
        requested_by_name[name], _ = _requested_strain(bundle["task"])
    preflight = _tensor_task_preflight(bundles, requested_by_name, threshold_values)
    report = _tensor_calibration_from_bundles(
        bundles,
        requested_by_name,
        threshold_values,
        geometry_strain_tolerance=threshold_values["strain_tolerance"],
    )
    preflight_passed = bool(preflight["passed"] and not threshold_issues)
    report["preflight"] = preflight
    report["threshold_issues"] = threshold_issues
    if not preflight_passed:
        report["sign_status"] = "blocked"
    report["stress_sign_qualification"] = bool(report["stress_sign_qualification"] and preflight_passed)
    report["full_tensor_stress_calibration"] = bool(
        report["full_tensor_stress_calibration"] and preflight_passed
    )
    report["tensor_qualification"] = report["full_tensor_stress_calibration"]
    report["shear_qualification"] = report["full_tensor_stress_calibration"]
    report["status"] = "passed" if report["full_tensor_stress_calibration"] else "blocked"
    report["production_qualification"] = False
    issues = list(report["issues"])
    issues.extend(threshold_issues)
    issues.extend(name + " failed" for name, passed in preflight["checks"].items() if not passed)
    report["issues"] = list(dict.fromkeys(issues))
    return report


def analyze_elastic_tasks(
    reference_task: str | Path,
    strained_task_paths: Mapping[str, str | Path] | Sequence[str | Path],
    calibration_path: str | Path,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate native strain tasks and fit Cij when all gates are qualified.

    The function is intentionally conservative.  A missing native source,
    identity/physics mismatch, incomplete ± set, rank below six, or invalid
    stress-sign calibration returns ``status='blocked'`` and ``Cij=None``.
    """

    if not isinstance(thresholds, Mapping):
        raise TypeError("thresholds must be a mapping with explicit numeric limits")
    threshold_specs = (
        "fractional_tolerance",
        "strain_tolerance",
        "reference_stress_GPa",
        "linearity_residual_GPa",
        "condition_number_max",
        "asymmetry_GPa",
        "calibration_abs_error_GPa",
        "calibration_relative_error",
        "calibration_signal_min_GPa",
        "calibration_fd_consistency_GPa",
        "amplitude_slope_difference_GPa",
        "native_stress_asymmetry_GPa",
    )
    threshold_values: dict[str, float | None] = {}
    threshold_issues: list[str] = []
    for name in threshold_specs:
        value, issue = _threshold_value(thresholds, name)
        threshold_values[name] = value
        if issue is not None:
            threshold_issues.append(issue)
    geometry_fractional_tolerance = threshold_values["fractional_tolerance"]
    geometry_strain_tolerance = threshold_values["strain_tolerance"]

    reference = _load_bundle(reference_task)
    entries = _task_entries(strained_task_paths)
    bundles = [("reference", reference), *entries]
    labels = [name for name, _ in bundles]
    method_physics = {name: _method_physics(bundle["method"]) for name, bundle in bundles}
    native_physics = {name: _native_physics(bundle["input"]) for name, bundle in bundles}
    kpoints = {name: bundle["kpt"] for name, bundle in bundles}

    task_identity: dict[str, dict[str, Any]] = {}
    scheduler_checks: dict[str, bool] = {}
    source_checks: dict[str, bool] = {}
    native_checks: dict[str, bool] = {}
    stress_checks: dict[str, bool] = {}
    electronic_checks: dict[str, bool] = {}
    for name, bundle in bundles:
        task = bundle["task"]
        method = bundle["method"]
        result = bundle["result"]
        task_identity[name] = {
            "task_id": task.get("task_id"),
            "result_task_id": result.get("task_id"),
            "scheduler_job_id": task.get("scheduler_job_id"),
            "result_scheduler_job_id": result.get("scheduler_job_id"),
            "task_model_id": task.get("model_id"),
            "task_model_version": task.get("model_version"),
            "method_model_id": method.get("model_id"),
            "method_model_version": method.get("version"),
            "task_method_set": task.get("method_set"),
            "method_method_set": method.get("method_set"),
            "result_method_set": result.get("method_set"),
        }
        scheduler_checks[name] = task.get("scheduler_state") == "COMPLETED" and task.get("exit_code") == "0:0"
        source_checks[name] = (
            bundle["source_evidence"]["reason"] == "complete"
            and bundle["source_evidence"]["paths_belong_to_task"] is True
        )
        electronic_checks[name] = result.get("electronic_converged") is True
        native_checks[name] = _native_input_compatibility(bundle)
        try:
            _stress_voigt(result)
            stress_checks[name] = True
        except (KeyError, TypeError, ValueError):
            stress_checks[name] = False

    identity_checks = {
        name: (
            values["task_id"] == values["result_task_id"]
            and values["scheduler_job_id"] == values["result_scheduler_job_id"]
            and values["task_model_id"] == values["method_model_id"]
            and values["task_model_version"] == values["method_model_version"]
            and values["task_method_set"] == values["method_method_set"] == values["result_method_set"]
            and reference["task"].get("model_id") == bundle["task"].get("model_id")
            and reference["task"].get("model_version") == bundle["task"].get("model_version")
            and bundle["method"].get("model_id") == reference["method"].get("model_id")
            and bundle["method"].get("version") == reference["method"].get("version")
        )
        for name, bundle in entries
        for values in [task_identity[name]]
    }
    identity_checks["reference"] = (
        task_identity["reference"]["task_id"] == task_identity["reference"]["result_task_id"]
        and task_identity["reference"]["scheduler_job_id"] == task_identity["reference"]["result_scheduler_job_id"]
        and task_identity["reference"]["task_model_id"] == task_identity["reference"]["method_model_id"]
        and task_identity["reference"]["task_model_version"] == task_identity["reference"]["method_model_version"]
        and task_identity["reference"]["task_method_set"] == task_identity["reference"]["method_method_set"] == task_identity["reference"]["result_method_set"]
        and reference["task"].get("model_id") == reference["method"].get("model_id")
        and reference["task"].get("model_version") == reference["method"].get("version")
    )
    static_scf_stage = all(
        bundle["task"].get("calculation") == "scf"
        and bundle["method"].get("stage") == "scf"
        and bundle["result"].get("stage") == "scf"
        for _, bundle in bundles
    )
    same_engine = all(
        bundle["task"].get("engine") == "abacus"
        and bundle["method"].get("engine") == "abacus"
        and bundle["task"].get("engine_version") == ABACUS_VERSION
        and bundle["method"].get("abacus_version_target") == ABACUS_VERSION
        for _, bundle in bundles
    )
    same_method_physics = all(value == method_physics["reference"] for value in method_physics.values())
    same_native_physics = all(value == native_physics["reference"] for value in native_physics.values())
    same_kpoints = all(value == kpoints["reference"] for value in kpoints.values())
    method_kpoints = all(
        list(bundle["method"].get("kpoints", [])) == bundle["kpt"].get("grid")
        for _, bundle in bundles
    )
    method_set_values = [bundle["method"].get("method_set") for _, bundle in bundles]
    strained_method_sets = {bundle["method"].get("method_set") for _, bundle in entries}
    reference_method_set = reference["method"].get("method_set")
    method_set_lineage = (
        len(strained_method_sets) == 1
        and (not entries or reference_method_set in strained_method_sets or all(
            bundle["method"].get("parent_method_set") == reference_method_set for _, bundle in entries
        ))
    )
    atom_mapping_checks: dict[str, bool] = {}
    for name, bundle in bundles:
        atom_mapping_checks[name] = _atom_mapping_valid(bundle)

    geometry: dict[str, dict[str, Any]] = {}
    reference_geometry = _geometry_record(
        reference["atoms"],
        reference["atoms"],
        np.zeros(6, dtype=float),
        geometry_fractional_tolerance,
        geometry_strain_tolerance,
    )
    geometry["reference"] = reference_geometry
    requested_by_name: dict[str, np.ndarray | None] = {"reference": np.zeros(6, dtype=float)}
    extraction_sources: dict[str, str | None] = {"reference": "reference"}
    for name, bundle in entries:
        requested, source = _requested_strain(bundle["task"])
        requested_by_name[name] = requested
        extraction_sources[name] = source
        geometry[name] = _geometry_record(
            reference["atoms"],
            bundle["atoms"],
            requested,
            geometry_fractional_tolerance,
            geometry_strain_tolerance,
        )
        geometry[name]["task_transformation_source"] = source
    geometry_ok = all(value["passed"] for value in geometry.values())
    native_geometry: dict[str, dict[str, Any]] = {}
    for name, bundle in bundles:
        cell_tolerance = None
        if geometry_strain_tolerance is not None:
            cell_tolerance = geometry_strain_tolerance * float(np.max(np.abs(bundle["atoms"].cell.array)))
        native_stru = bundle["native_stru"]
        final_atoms = bundle["final_atoms"]
        native_stru_check = (
            _structure_match(bundle["atoms"], native_stru, geometry_fractional_tolerance, cell_tolerance)
            if native_stru is not None
            else {"passed": False, "reason": "missing_native_STRU"}
        )
        final_check = (
            _structure_match(bundle["atoms"], final_atoms, geometry_fractional_tolerance, cell_tolerance)
            if final_atoms is not None
            else {"passed": False, "reason": "missing_final_static_structure"}
        )
        native_geometry[name] = {
            "native_STRU": native_stru_check,
            "final_static_structure": final_check,
            "final_structure_source": bundle["final_structure_source"],
            "passed": bool(native_stru_check["passed"] and final_check["passed"]),
        }
    native_geometry_ok = all(value["passed"] for value in native_geometry.values())

    stress_vectors: dict[str, np.ndarray] = {}
    stress_data_ok = all(stress_checks.values())
    if stress_data_ok:
        stress_vectors = {name: _stress_voigt(bundle["result"]) for name, bundle in bundles}

    calibration = _json(Path(calibration_path))
    calibration_reference = {
        "method_physics": method_physics["reference"],
        "native_physics": native_physics["reference"],
    }
    calibration_preflight_passed = bool(
        not threshold_issues
        and all(scheduler_checks.values())
        and all(source_checks.values())
        and all(electronic_checks.values())
        and all(identity_checks.values())
        and same_engine
        and static_scf_stage
        and same_method_physics
        and same_native_physics
        and same_kpoints
        and method_kpoints
        and method_set_lineage
        and all(atom_mapping_checks.values())
        and geometry_ok
        and native_geometry_ok
        and all(native_checks.values())
        and all(bundle["native_result_consistent"] for _, bundle in bundles)
        and stress_data_ok
    )
    calibration_binding = _calibration_binding(
        calibration,
        calibration_reference,
        Path(calibration_path),
        bundles=bundles,
        requested_by_name=requested_by_name,
        threshold_values=threshold_values,
        geometry_strain_tolerance=geometry_strain_tolerance,
        preflight_passed=calibration_preflight_passed,
    )
    calibration_multiplier = calibration_binding["stress_multiplier"]

    pair_groups: dict[str, dict[str, Any]] = {}
    strain_rows: list[np.ndarray] = []
    stress_rows: list[np.ndarray] = []
    pair_tolerance = geometry_strain_tolerance
    if stress_data_ok and "reference" in stress_vectors:
        reference_stress = stress_vectors["reference"]
    else:
        reference_stress = None
    for name, bundle in entries:
        requested = requested_by_name[name]
        if requested is None:
            continue
        direction = _direction_key(requested, pair_tolerance)
        if direction is None:
            continue
        direction_vector, amplitude, sign = direction
        group_key = json.dumps([direction_vector, round(amplitude, 12)], separators=(",", ":"))
        group = pair_groups.setdefault(group_key, {"direction": list(direction_vector), "amplitude": amplitude, "minus": [], "plus": []})
        group["minus" if sign < 0 else "plus"].append(name)
        strain_rows.append(np.asarray(geometry[name]["actual_strain_voigt"], dtype=float))
        if reference_stress is not None and calibration_multiplier is not None:
            stress_rows.append(calibration_multiplier * stress_vectors[name] - calibration_multiplier * reference_stress)
    complete_pairs = bool(pair_groups) and all(bool(value["minus"]) and bool(value["plus"]) for value in pair_groups.values())
    covered_voigt_directions: set[int] = set()
    for value in pair_groups.values():
        direction = np.asarray(value["direction"], dtype=float)
        for index in range(6):
            unit = np.zeros(6, dtype=float)
            unit[index] = 1.0
            if np.allclose(direction, unit, rtol=0.0, atol=1.0e-10):
                covered_voigt_directions.add(index)
    tensor_direction_coverage = len(covered_voigt_directions) == 6
    shear_direction_coverage = {3, 4, 5}.issubset(covered_voigt_directions) and complete_pairs
    tensor_qualification = bool(calibration_binding["full_tensor_stress_calibration"] and tensor_direction_coverage)
    shear_qualification = bool(calibration_binding["full_tensor_stress_calibration"] and shear_direction_coverage)
    tensor_calibration_report = calibration_binding.get("recomputed")
    tensor_calibration_checks = (
        tensor_calibration_report.get("checks", {})
        if isinstance(tensor_calibration_report, Mapping)
        else {}
    )
    amplitude_slope_report = _amplitude_slope_consistency(
        pair_groups,
        stress_vectors,
        calibration_multiplier,
        threshold_values["amplitude_slope_difference_GPa"],
    )
    at_least_two_amplitudes = bool(
        calibration.get("kind") == "tensor_energy_derivative"
        and amplitude_slope_report["enough_amplitudes"]
    )
    amplitude_consistency = bool(
        calibration.get("kind") == "tensor_energy_derivative"
        and amplitude_slope_report["passed"]
    )
    rank = int(np.linalg.matrix_rank(np.asarray(strain_rows, dtype=float))) if strain_rows else 0
    rank6 = rank == 6

    fit: dict[str, Any] = {
        "Cij_GPa": None,
        "rank": rank,
        "condition_number": None,
        "residual_rms_GPa": None,
        "residual_max_abs_GPa": None,
        "asymmetry_max_abs_GPa": None,
        "reference_stress_voigt_GPa": None if reference_stress is None or calibration_multiplier is None else (calibration_multiplier * reference_stress).tolist(),
        "Cij_definition": "Cauchy-stress_increment/engineering-strain_tangent_clamped-ion_fixed-fractional_static",
        "stress_calibration": "tensor_energy_derivative_v002",
        "amplitude_slope_consistency": amplitude_slope_report,
    }
    fit_checks = {
        "rank6": rank6,
        "complete_plus_minus_pairs": complete_pairs,
        "at_least_two_amplitudes": at_least_two_amplitudes,
        "amplitude_consistency": amplitude_consistency,
        "reference_residual_stress": False,
        "linearity_residual": False,
        "condition_number": False,
        "tensor_symmetry": False,
    }
    if reference_stress is not None and calibration_multiplier is not None and threshold_values["reference_stress_GPa"] is not None:
        reference_norm = float(np.linalg.norm(calibration_multiplier * reference_stress))
        fit["reference_stress_norm_GPa"] = reference_norm
        fit_checks["reference_residual_stress"] = reference_norm <= threshold_values["reference_stress_GPa"]
    else:
        fit["reference_stress_norm_GPa"] = None
    if rank == 6 and tensor_direction_coverage and shear_direction_coverage and stress_rows and calibration_multiplier is not None:
        X = np.asarray(strain_rows, dtype=float)
        Y = np.asarray(stress_rows, dtype=float)
        Cij, predicted, residual, condition = _fit_cij(X, Y)
        residual_rms = float(np.sqrt(np.mean(residual**2)))
        residual_max = float(np.max(np.abs(residual)))
        asymmetry = float(np.max(np.abs(Cij - Cij.T))) if Cij.shape == (6, 6) else None
        fit.update({
            "least_squares_Cij_GPa": Cij.tolist(),
            "condition_number": condition,
            "residual_rms_GPa": residual_rms,
            "residual_max_abs_GPa": residual_max,
            "asymmetry_max_abs_GPa": asymmetry,
        })
        if threshold_values["linearity_residual_GPa"] is not None:
            fit_checks["linearity_residual"] = residual_max <= threshold_values["linearity_residual_GPa"]
        if threshold_values["condition_number_max"] is not None:
            fit_checks["condition_number"] = np.isfinite(condition) and condition <= threshold_values["condition_number_max"]
        if threshold_values["asymmetry_GPa"] is not None and asymmetry is not None:
            fit_checks["tensor_symmetry"] = asymmetry <= threshold_values["asymmetry_GPa"]

    structural_checks = {
        "native_scheduler_completed_0": all(scheduler_checks.values()),
        "native_source_evidence": all(source_checks.values()),
        "electronic_converged": all(electronic_checks.values()),
        "identity": all(identity_checks.values()),
        "same_engine_version": same_engine,
        "static_scf_stage": static_scf_stage,
        "same_method_physics": same_method_physics,
        "same_native_input_physics": same_native_physics,
        "same_kpoints": same_kpoints and method_kpoints,
        "method_set_lineage": method_set_lineage,
        "atom_mapping": all(atom_mapping_checks.values()),
        "fixed_fractional_geometry": geometry_ok,
        "native_stru_and_final_geometry": native_geometry_ok,
        "native_input_compatibility": all(native_checks.values()),
        "native_result_consistency": all(bundle["native_result_consistent"] for _, bundle in bundles),
        "native_result_energy_match": all(bundle["native_result_energy_match"] for _, bundle in bundles),
        "stress_units_and_native_sign": stress_data_ok,
        "calibration_binding": calibration_binding["valid"],
        "thresholds_explicit": not threshold_issues,
        "rank6": rank6,
        "complete_plus_minus_pairs": complete_pairs,
        "tensor_direction_coverage": tensor_direction_coverage,
        "shear_direction_coverage": shear_direction_coverage,
        "full_tensor_stress_calibration": calibration_binding["full_tensor_stress_calibration"],
        "tensor_qualification": tensor_qualification,
        "shear_qualification": shear_qualification,
    }
    all_fit_checks = all(fit_checks.values())
    fit_allowed = all(structural_checks.values()) and all_fit_checks
    if fit_allowed:
        fit["Cij_GPa"] = fit.get("least_squares_Cij_GPa")
    issues = list(threshold_issues)
    for name, passed in structural_checks.items():
        if not passed:
            issues.append(f"{name} failed")
    for name, passed in fit_checks.items():
        if not passed:
            issues.append(f"{name} failed")
    if calibration_binding["full_tensor_calibration_evidence_missing"]:
        issues.append("full_tensor_calibration_evidence_missing")
    return {
        "schema": SCHEMA,
        "scope": "clamped-ion_fixed-fractional_static",
        "status": "passed" if fit_allowed else "blocked",
        "production_qualification": False,
        "elastic_constant_qualification": bool(fit_allowed),
        "stress_sign_qualification": bool(calibration_binding["stress_sign_qualification"]),
        "physics_comparable": bool(same_method_physics and same_native_physics and same_kpoints and method_kpoints),
        "tensor_direction_coverage": bool(tensor_direction_coverage),
        "shear_direction_coverage": bool(shear_direction_coverage),
        "tensor_qualification": bool(tensor_qualification),
        "shear_qualification": bool(shear_qualification),
        "Cij": fit["Cij_GPa"],
        "Cij_GPa": fit["Cij_GPa"],
        "rank": fit["rank"],
        "condition_number": fit["condition_number"],
        "residual_rms_GPa": fit["residual_rms_GPa"],
        "residual_max_abs_GPa": fit["residual_max_abs_GPa"],
        "asymmetry_max_abs_GPa": fit["asymmetry_max_abs_GPa"],
        "voigt_order": list(VOIGT_ORDER),
        "engineering_shear": True,
        "reference_task": str(reference["directory"]),
        "strained_tasks": {name: str(bundle["directory"]) for name, bundle in entries},
        "calibration_path": str(Path(calibration_path)),
        "calibration": calibration_binding,
        "thresholds": dict(threshold_values),
        "issues": issues,
        "checks": {
            **structural_checks,
            "fit": fit_checks,
            "scheduler_by_task": scheduler_checks,
            "source_evidence_by_task": source_checks,
            "electronic_converged_by_task": electronic_checks,
            "native_input_compatibility_by_task": native_checks,
            "native_result_consistency_by_task": {
                name: bundle["native_result_consistent"] for name, bundle in bundles
            },
            "native_result_energy_match_by_task": {
                name: bundle["native_result_energy_match"] for name, bundle in bundles
            },
            "identity_by_task": identity_checks,
            "atom_mapping_by_task": atom_mapping_checks,
            "geometry": geometry,
            "native_geometry": native_geometry,
            "requested_strain_source": extraction_sources,
            "method_physics": method_physics,
            "native_physics": native_physics,
            "kpoints": kpoints,
            "method_sets": method_set_values,
            "pair_groups": pair_groups,
            "covered_voigt_directions": sorted(covered_voigt_directions),
        },
        "fit": fit,
        "source_evidence": {name: bundle["source_evidence"] for name, bundle in bundles},
    }


__all__ = [
    "analyze_elastic_tasks",
    "calibrate_tensor_stress",
    "plan_elastic_strains",
    "voigt_strain_model",
]
