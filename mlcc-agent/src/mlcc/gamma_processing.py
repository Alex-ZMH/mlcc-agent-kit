"""Explicit processing of a native Gamma force-constant matrix.

The native Gamma matrix is a real, un-mass-weighted Hessian in
``eV/angstrom**2``.  Pure matrix operations and a thin native adapter keep
the non-reciprocal diagnostic separate from the explicitly
symmetrized and translation-projected spectra used for response analysis.

The returned object is JSON-safe and has schema
``mlcc.gamma-explicit-processing.v1``.  Scientific qualification is always
false; the 30 cm^-1 acoustic and 5 cm^-1 negative-frequency values are
diagnostic warnings only.
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.constants import atomic_mass, elementary_charge, epsilon_0, speed_of_light


SCHEMA = "mlcc.gamma-explicit-processing.v1"
GAMMA_HESSIAN_SCHEMA = "mlcc.gamma-force-constants.v1"
SAVED_GAMMA_REQUEST_SCHEMA = "mlcc.saved-gamma-import-request.v1"
GAMMA_OPERATION = "reciprocity_average_then_exact_three_translation_projection"
_ANGSTROM_M = 1.0e-10
_TWO_PI = 2.0 * np.pi
_ACOUSTIC_WARNING_CM1 = 30.0
_INSTABILITY_WARNING_CM1 = 5.0


def _as_real_matrix(value: Any) -> np.ndarray:
    matrix = np.asarray(value)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("matrix_eV_per_A2 must be a square two-dimensional matrix")
    if not np.issubdtype(matrix.dtype, np.number):
        raise TypeError("matrix_eV_per_A2 must contain real numbers")
    if np.iscomplexobj(matrix):
        if np.any(np.imag(matrix) != 0.0):
            raise ValueError("matrix_eV_per_A2 must be real, not complex")
        matrix = np.real(matrix)
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape[0] == 0 or matrix.shape[0] % 3:
        raise ValueError("matrix_eV_per_A2 dimension must be a non-zero multiple of 3")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("matrix_eV_per_A2 must contain only finite values")
    return matrix.copy()


def _as_masses(value: Any, n_atoms: int) -> np.ndarray:
    masses = np.asarray(value)
    if masses.ndim != 1 or masses.shape[0] != n_atoms:
        raise ValueError("masses_amu must contain one mass per atom")
    if not np.issubdtype(masses.dtype, np.number):
        raise TypeError("masses_amu must contain real numbers")
    if np.iscomplexobj(masses):
        if np.any(np.imag(masses) != 0.0):
            raise ValueError("masses_amu must be real, not complex")
        masses = np.real(masses)
    masses = np.asarray(masses, dtype=float)
    if not np.all(np.isfinite(masses)) or np.any(masses <= 0.0):
        raise ValueError("masses_amu must contain finite positive values")
    return masses.copy()


def _max_abs(value: np.ndarray) -> float:
    return float(np.max(np.abs(value))) if value.size else 0.0


def _frobenius(value: np.ndarray) -> float:
    return float(np.linalg.norm(value, ord="fro"))


def _relative_residual(value: np.ndarray) -> float:
    denominator = _frobenius(value)
    numerator = _frobenius(value - value.T)
    return float(numerator / denominator) if denominator else 0.0


def _matrix_pair_metrics(left: np.ndarray, right: np.ndarray) -> dict[str, float]:
    delta = np.asarray(left) - np.asarray(right)
    return {
        "max_abs_eV_per_A2": _max_abs(delta),
        "frobenius_eV_per_A2": _frobenius(delta),
    }


def _translation_metric(value: np.ndarray, basis: np.ndarray) -> dict[str, Any]:
    left = basis.T @ value
    right = value @ basis
    return {
        "left": {
            "max_abs_eV_per_A2": _max_abs(left),
            "frobenius_eV_per_A2": _frobenius(left),
            "components_eV_per_A2": left.tolist(),
        },
        "right": {
            "max_abs_eV_per_A2": _max_abs(right),
            "frobenius_eV_per_A2": _frobenius(right),
            "components_eV_per_A2": right.tolist(),
        },
    }


def _complex_pair(value: complex) -> dict[str, float]:
    return {"real": float(np.real(value)), "imag": float(np.imag(value))}


def _frequency_scale_cm1() -> float:
    """Return cm^-1 per sqrt(eV/angstrom^2/amu)."""

    # lambda [eV/A^2/amu] -> lambda*e/(A^2*m_u) [s^-2].
    return float(
        np.sqrt(elementary_charge / (_ANGSTROM_M**2 * atomic_mass))
        / (_TWO_PI * speed_of_light * 100.0)
    )


def _complex_frequency_cm1(eigenvalue: complex) -> complex:
    return complex(np.sqrt(complex(eigenvalue) * _frequency_scale_cm1() ** 2))


def _signed_frequency_cm1(eigenvalue: float) -> float:
    if eigenvalue == 0.0:
        return 0.0
    return float(np.copysign(np.sqrt(abs(eigenvalue)) * _frequency_scale_cm1(), eigenvalue))


def _vector_json(vector: np.ndarray) -> list[dict[str, float]] | list[float]:
    if np.iscomplexobj(vector):
        return [_complex_pair(complex(item)) for item in vector]
    return np.asarray(vector, dtype=float).tolist()


def _raw_modes(
    eigenvalues: np.ndarray,
    eigenvectors: np.ndarray,
    q_mass: np.ndarray,
) -> list[dict[str, Any]]:
    modes: list[dict[str, Any]] = []
    for index, value in enumerate(eigenvalues):
        vector = np.asarray(eigenvectors[:, index], dtype=complex)
        norm = np.linalg.norm(vector)
        if norm:
            vector = vector / norm
        frequency = _complex_frequency_cm1(complex(value))
        imag_zero = float(np.imag(value)) == 0.0
        record: dict[str, Any] = {
            "mode_index": int(index),
            "eigenvalue_eV_per_A2_per_amu": _complex_pair(complex(value)),
            "frequency_cm1": _complex_pair(frequency),
            "frequency_magnitude_cm1": float(abs(frequency)),
            "translation_overlap": float(np.linalg.norm(q_mass.T.conj() @ vector) ** 2),
            "eigenvector": _vector_json(vector),
            "signed_frequency_cm1": (
                _signed_frequency_cm1(float(np.real(value))) if imag_zero else None
            ),
        }
        modes.append(record)
    return modes


def _real_modes(
    eigenvalues: np.ndarray,
    eigenvectors: np.ndarray,
    q_mass: np.ndarray,
) -> list[dict[str, Any]]:
    modes: list[dict[str, Any]] = []
    for index, value in enumerate(np.asarray(eigenvalues, dtype=float)):
        vector = np.asarray(eigenvectors[:, index], dtype=float)
        signed = _signed_frequency_cm1(float(value))
        modes.append(
            {
                "mode_index": int(index),
                "eigenvalue_eV_per_A2_per_amu": float(value),
                "frequency_cm1": signed,
                "signed_frequency_cm1": signed,
                "frequency_magnitude_cm1": abs(signed),
                "translation_overlap": float(np.linalg.norm(q_mass.T @ vector) ** 2),
                "eigenvector": vector.tolist(),
            }
        )
    return modes


def _mass_weighted_matrix(matrix: np.ndarray, masses: np.ndarray) -> np.ndarray:
    sqrt_masses = np.repeat(np.sqrt(masses), 3)
    return matrix / np.outer(sqrt_masses, sqrt_masses)


def _json_matrix(matrix: np.ndarray) -> list[list[float]]:
    return np.asarray(matrix, dtype=float).tolist()


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def process_gamma_matrix(matrix_eV_per_A2: Any, masses_amu: Any) -> dict[str, Any]:
    """Process one native, un-mass-weighted Gamma Hessian.

    ``matrix_eV_per_A2`` is never modified.  The raw nonsymmetric dynamical
    matrix is diagnosed with :func:`numpy.linalg.eig`; only the explicitly
    symmetric ``Ks`` and projected ``Kc`` matrices use Hermitian eigensolvers.
    """

    raw = _as_real_matrix(matrix_eV_per_A2)
    n_atoms = raw.shape[0] // 3
    masses = _as_masses(masses_amu, n_atoms)

    identity = np.eye(raw.shape[0], dtype=float)
    translation = np.tile(np.eye(3, dtype=float), (n_atoms, 1)) / np.sqrt(float(n_atoms))
    translation_unnormalized = translation * np.sqrt(float(n_atoms))
    projection = identity - translation @ translation.T
    symmetric = (raw + raw.T) / 2.0
    projected = projection @ symmetric @ projection

    sqrt_mass = np.repeat(np.sqrt(masses), 3)
    q_mass = sqrt_mass[:, None] * translation
    # The three Cartesian columns remain mutually orthogonal when each atom's
    # scalar mass is repeated across x/y/z.  Normalize each column explicitly;
    # this keeps the basis unit-normalized for any atom count and mass set.
    q_mass = q_mass / np.linalg.norm(q_mass, axis=0, keepdims=True)
    q_mass_full, _ = np.linalg.qr(q_mass, mode="complete")
    q_mass_optical = q_mass_full[:, 3:]

    q_unweighted_full, _ = np.linalg.qr(translation, mode="complete")
    q_unweighted_optical = q_unweighted_full[:, 3:]

    raw_dynamical = _mass_weighted_matrix(raw, masses)
    symmetric_dynamical = _mass_weighted_matrix(symmetric, masses)
    projected_dynamical = _mass_weighted_matrix(projected, masses)

    raw_values, raw_vectors = np.linalg.eig(raw_dynamical)
    symmetric_values, symmetric_vectors = np.linalg.eigh(symmetric_dynamical)
    projected_values, projected_vectors = np.linalg.eigh(projected_dynamical)
    optical_dynamical = q_mass_optical.T @ projected_dynamical @ q_mass_optical
    optical_values, optical_vectors_reduced = np.linalg.eigh(optical_dynamical)
    optical_vectors = q_mass_optical @ optical_vectors_reduced

    raw_modes = _raw_modes(raw_values, raw_vectors, q_mass)
    symmetric_modes = _real_modes(symmetric_values, symmetric_vectors, q_mass)
    projected_modes = _real_modes(projected_values, projected_vectors, q_mass)
    optical_modes = _real_modes(optical_values, optical_vectors, q_mass)

    raw_acoustic_indices = sorted(
        range(len(raw_modes)),
        key=lambda index: (-raw_modes[index]["translation_overlap"], index),
    )[:3]
    raw_acoustic_modes = [raw_modes[index] for index in raw_acoustic_indices]
    raw_acoustic_max = max(
        (mode["frequency_magnitude_cm1"] for mode in raw_acoustic_modes),
        default=0.0,
    )

    instability_modes = [
        mode["mode_index"]
        for mode in optical_modes
        if mode["signed_frequency_cm1"] < -_INSTABILITY_WARNING_CM1
    ]
    warnings: list[str] = []
    if raw_acoustic_max > _ACOUSTIC_WARNING_CM1:
        warnings.append("raw_acoustic_frequency_over_30_cm1")
    if instability_modes:
        warnings.append("projected_optical_negative_frequency_over_5_cm1")

    correction_metrics = {
        "raw_to_symmetric": _matrix_pair_metrics(symmetric, raw),
        "symmetric_to_projected": _matrix_pair_metrics(projected, symmetric),
        "raw_to_projected": _matrix_pair_metrics(projected, raw),
    }
    reciprocity = {
        "raw": {
            "absolute_max_eV_per_A2": _max_abs(raw - raw.T),
            "relative_frobenius": _relative_residual(raw),
        },
        "symmetric": {
            "absolute_max_eV_per_A2": _max_abs(symmetric - symmetric.T),
            "relative_frobenius": _relative_residual(symmetric),
        },
        "projected": {
            "absolute_max_eV_per_A2": _max_abs(projected - projected.T),
            "relative_frobenius": _relative_residual(projected),
        },
    }
    translation_residuals = {
        "raw": {
            "normalized": _translation_metric(raw, translation),
            "sum_rule": _translation_metric(raw, translation_unnormalized),
        },
        "symmetric": {
            "normalized": _translation_metric(symmetric, translation),
            "sum_rule": _translation_metric(symmetric, translation_unnormalized),
        },
        "projected": {
            "normalized": _translation_metric(projected, translation),
            "sum_rule": _translation_metric(projected, translation_unnormalized),
        },
    }

    return {
        "schema": SCHEMA,
        "operation": "reciprocity_average_then_exact_three_translation_projection",
        "unit": "eV/angstrom^2",
        "matrix_basis": "parent_atom_major_cartesian",
        "atom_count": n_atoms,
        "masses_amu": masses.tolist(),
        "matrices": {
            "raw": _json_matrix(raw),
            "symmetric": _json_matrix(symmetric),
            "projected": _json_matrix(projected),
        },
        "translation_basis": _json_matrix(translation),
        "translation_basis_unnormalized": _json_matrix(translation_unnormalized),
        "translation_basis_mass_weighted": _json_matrix(q_mass),
        "optical_basis": _json_matrix(q_unweighted_optical),
        "optical_basis_mass_weighted": _json_matrix(q_mass_optical),
        "diagnostics": {
            "reciprocity": reciprocity,
            "translation_residuals": translation_residuals,
            "corrections": correction_metrics,
            "raw_acoustic_diagnostic_mode_indices": raw_acoustic_indices,
            "raw_acoustic_diagnostic_frequency_max_cm1": raw_acoustic_max,
            "raw_acoustic_diagnostic_frequency_warning_cm1": _ACOUSTIC_WARNING_CM1,
            "projected_optical_instability_mode_indices": instability_modes,
            "projected_optical_instability_warning_cm1": _INSTABILITY_WARNING_CM1,
            "raw_spectrum_solver": "numpy.linalg.eig_general_complex",
            "symmetric_spectrum_solver": "numpy.linalg.eigh_explicitly_symmetric",
            "projected_spectrum_solver": "numpy.linalg.eigh_explicitly_symmetric",
            "optical_spectrum_solver": "numpy.linalg.eigh_mass_weighted_translation_complement",
        },
        "spectra": {
            "raw": raw_modes,
            "symmetric": symmetric_modes,
            "projected": projected_modes,
            "optical": optical_modes,
        },
        "optical_blocks": {
            "raw": _json_matrix(q_unweighted_optical.T @ raw @ q_unweighted_optical),
            "symmetric": _json_matrix(q_unweighted_optical.T @ symmetric @ q_unweighted_optical),
            "projected": _json_matrix(q_unweighted_optical.T @ projected @ q_unweighted_optical),
            "basis": "unmassweighted_translation_complement",
        },
        "constants": {
            "elementary_charge_C": float(elementary_charge),
            "atomic_mass_kg": float(atomic_mass),
            "speed_of_light_m_per_s": float(speed_of_light),
            "angstrom_m": _ANGSTROM_M,
            "frequency_conversion_cm1_per_sqrt_eV_per_A2_per_amu": _frequency_scale_cm1(),
            "formula": "sqrt(lambda_eV_per_A2_per_amu*e/(angstrom_m^2*atomic_mass))/(2*pi*c*100)",
        },
        "warnings": warnings,
        "qualifications": False,
        "scientific_qualification": False,
        "production_qualification": False,
        "qualification_reasons": [
            "explicit_gamma_processing_is_a_local_response_diagnostic",
            "raw_acoustic_and_optical_warnings_do_not_grant_scientific_qualification",
        ],
    }


def optical_response_sensitivity(
    born_matrix: Any,
    processing: Mapping[str, Any],
    volume_A3: float,
) -> dict[str, Any]:
    """Compare raw, reciprocal, and projected local optical responses.

    The optical basis is the un-mass-weighted complement of the three rigid
    translations returned by :func:`process_gamma_matrix`.  The comparison is
    intentionally separate from the existing ionic solver.  A non-positive
    reciprocal optical block leaves the result unresolved; an individual
    ``solve`` error is retained verbatim in that branch's result and is not
    replaced by another matrix or solver.
    """

    born = np.asarray(born_matrix)
    if born.ndim != 2 or born.shape[0] != 3:
        raise ValueError("born_matrix must have shape (3, 3N)")
    if np.iscomplexobj(born):
        if np.any(np.imag(born) != 0.0):
            raise ValueError("born_matrix must be real, not complex")
        born = np.real(born)
    born = np.asarray(born, dtype=float)
    if born.shape[1] == 0 or born.shape[1] % 3:
        raise ValueError("born_matrix must have three Cartesian columns per atom")
    if not np.all(np.isfinite(born)):
        raise ValueError("born_matrix must contain only finite values")
    volume = float(volume_A3)
    if not np.isfinite(volume) or volume <= 0.0:
        raise ValueError("volume_A3 must be finite and positive")

    matrices = processing["matrices"]
    optical_basis = np.asarray(processing["optical_basis"], dtype=float)
    if optical_basis.ndim != 2 or optical_basis.shape[0] != born.shape[1]:
        raise ValueError("processing optical_basis is incompatible with born_matrix")
    if optical_basis.shape[1] == 0:
        return {
            "schema": "mlcc.gamma-optical-response-sensitivity.v1",
            "status": "unresolved",
            "unresolved_reasons": ["empty_optical_space"],
            "born_matrix": born.tolist(),
            "volume_A3": volume,
            "responses": {"raw": None, "symmetric": None, "projected": None},
            "comparisons": {"raw_vs_symmetric": None, "raw_vs_projected": None},
            "optical_block_condition_numbers": {"raw": None, "symmetric": None, "projected": None},
            "qualifications": False,
        }

    blocks: dict[str, np.ndarray] = {}
    for name in ("raw", "symmetric", "projected"):
        matrix = np.asarray(matrices[name], dtype=float)
        if matrix.shape != (born.shape[1], born.shape[1]):
            raise ValueError(f"processing matrices.{name} has incompatible shape")
        blocks[name] = optical_basis.T @ matrix @ optical_basis

    condition_numbers = {
        name: _finite_or_none(float(np.linalg.cond(block))) for name, block in blocks.items()
    }
    symmetric_eigenvalues = np.linalg.eigvalsh((blocks["symmetric"] + blocks["symmetric"].T) / 2.0)
    if symmetric_eigenvalues.size == 0 or float(np.min(symmetric_eigenvalues)) <= 0.0:
        return {
            "schema": "mlcc.gamma-optical-response-sensitivity.v1",
            "status": "unresolved",
            "unresolved_reasons": ["symmetric_optical_block_not_positive_definite"],
            "born_matrix": born.tolist(),
            "volume_A3": volume,
            "scale": None,
            "symmetric_optical_eigenvalues_eV_per_A2": symmetric_eigenvalues.tolist(),
            "responses": {"raw": None, "symmetric": None, "projected": None},
            "comparisons": {"raw_vs_symmetric": None, "raw_vs_projected": None},
            "optical_block_condition_numbers": condition_numbers,
            "qualifications": False,
        }

    born_optical = born @ optical_basis
    scale = float(elementary_charge * 1.0e10 / (epsilon_0 * volume))
    responses: dict[str, dict[str, Any]] = {}
    for name, block in blocks.items():
        try:
            solved = np.linalg.solve(block, born_optical.T)
        except np.linalg.LinAlgError as error:
            # Preserve the native scientific error; do not substitute a
            # reciprocal or pseudo-inverse calculation for this branch.
            responses[name] = {
                "status": "error",
                "error_type": type(error).__name__,
                "error": str(error),
                "response": None,
            }
            continue
        response = scale * born_optical @ solved
        responses[name] = {
            "status": "complete",
            "response": response.tolist(),
        }

    def comparison(name: str) -> dict[str, float] | None:
        raw_response = responses["raw"].get("response")
        other_response = responses[name].get("response")
        if raw_response is None or other_response is None:
            return None
        delta = np.asarray(raw_response, dtype=float) - np.asarray(other_response, dtype=float)
        return {
            "max_abs": _max_abs(delta),
            "frobenius": _frobenius(delta),
        }

    all_complete = all(item.get("status") == "complete" for item in responses.values())
    status = "complete" if all_complete else "partial"
    unresolved_reasons = [] if all_complete else [
        f"{name}_optical_block_solve_failed:{item['error']}"
        for name, item in responses.items()
        if item.get("status") == "error"
    ]
    return {
        "schema": "mlcc.gamma-optical-response-sensitivity.v1",
        "status": status,
        "unresolved_reasons": unresolved_reasons,
        "born_matrix": born.tolist(),
        "volume_A3": volume,
        "scale": scale,
        "symmetric_optical_eigenvalues_eV_per_A2": symmetric_eigenvalues.tolist(),
        "responses": responses,
        "comparisons": {
            "raw_vs_symmetric": comparison("symmetric"),
            "raw_vs_projected": comparison("projected"),
        },
        "optical_block_condition_numbers": condition_numbers,
        "qualifications": False,
    }


def process_native_gamma(request_path: str | Path) -> dict[str, Any]:
    """Bind one native Hessian and apply the explicitly requested v001 treatment."""

    from .dielectric_response import read_native_gamma_force

    path = Path(request_path).expanduser().resolve()
    request = json.loads(path.read_text(encoding="utf-8"))
    if request["schema"] != "mlcc.gamma-processing-request.v1":
        raise ValueError("unsupported Gamma processing request schema")
    operation = "reciprocity_average_then_exact_three_translation_projection"
    if request["operation"] != operation:
        raise ValueError("Gamma request must explicitly select reciprocity and three translations")
    standard_path = Path(request["standard_file"]).resolve()
    standard = json.loads(standard_path.read_text(encoding="utf-8"))
    if standard["schema"] != "mlcc.born-gamma-provisional-standard.v1":
        raise ValueError("unsupported Born/Gamma provisional standard schema")
    if request["standard_id"] != standard["standard_id"]:
        raise ValueError("Gamma request standard_id differs from supplied standard")
    if standard["gamma"] != {
        "raw_retained": True, "NAC": False, "optical_soft_modes_retained": True,
        "raw_acoustic_warning_cm_1": 30, "negative_frequency_flag_cm_1": 5,
        "treatment": operation,
    }:
        raise ValueError("Gamma standard differs from the explicit v001 procedure")
    scope = copy.deepcopy(standard["scope"])
    if scope["response"] != "specified_geometry_local_fixed_cell_zero_macroscopic_electric_field":
        raise ValueError("Gamma procedure requires specified-geometry local response scope")
    if any(scope[key] is not False for key in (
        "equilibrium_reference", "production_qualification", "firing_temperature_response",
    )):
        raise ValueError("Gamma local response cannot claim equilibrium or production qualification")

    raw = read_native_gamma_force(request["native_raw_product"])
    if scope["material"] != raw["parent"]["model_id"] + "/" + raw["parent"]["model_version"]:
        raise ValueError("Gamma standard material differs from native model")
    native = raw["raw_product"]
    stru = Path(native["provenance"]["reference_task_root"]) / "STRU"
    lines = [line.split("#", 1)[0].split("//", 1)[0].strip()
             for line in stru.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in lines if line]
    start = lines.index("ATOMIC_SPECIES") + 1
    species = list(dict.fromkeys(raw["elements"]))
    rows = [line.split() for line in lines[start:start + len(species)]]
    if [row[0] for row in rows] != species:
        raise ValueError("Gamma reference STRU species differ from bound atom order")
    masses_by_element = {row[0]: float(row[1]) for row in rows}
    masses = [masses_by_element[element] for element in raw["elements"]]
    processing = process_gamma_matrix(raw["matrix_eV_per_A2"], masses)
    reference_forces = np.asarray(raw["reference"]["raw_reference_forces_eV_per_A"], dtype=float)
    if reference_forces.shape != (len(raw["atom_ids"]), 3) or not np.all(np.isfinite(reference_forces)):
        raise ValueError("Gamma reference force must be finite and follow bound atom order")
    reference_max_force = float(np.max(np.abs(reference_forces)))
    recorded_force = raw["diagnostics"]["reference_force_residual"]["max_abs_eV_per_A"]
    if not np.isclose(reference_max_force, recorded_force, rtol=0, atol=1e-12):
        raise ValueError("Gamma reference force diagnostic differs from saved reference forces")
    scope.update({
        "reference_max_abs_force_eV_per_A": reference_max_force,
        "reference_force_source": raw["reference"]["result_file"],
        "reference_scheduler_job_id": native["provenance"]["reference_scheduler_job_id"],
        "geometry_state": "unrelaxed_reference",
        "electrical_boundary": "fixed_E_zero", "mechanical_boundary": "fixed_cell",
        "NAC": False,
    })
    unresolved = [reason for reason in raw["unresolved_reasons"]
                  if reason != "raw_gamma_characteristic_status_unresolved_raw_nonsymmetric"]
    optical = processing["spectra"]["optical"]
    if not optical or min(mode["eigenvalue_eV_per_A2_per_amu"] for mode in optical) <= 0:
        unresolved.append("projected_optical_space_not_positive_definite")
    execution = copy.deepcopy(request["execution"])
    if execution["runner"] != "slurm" or not str(execution["scheduler_job_id"]).isdigit():
        raise ValueError("Gamma processing requires its actual Slurm job identity")
    source_refs = [*raw["source_refs"], str(path), str(standard_path), str(stru)]
    result = copy.deepcopy(raw)
    result.update({
        "matrix_eV_per_A2": copy.deepcopy(processing["matrices"]["projected"]),
        "explicit_processing": processing,
        "processing_request": request,
        "processing_execution": execution,
        "standard": standard,
        "response_scope": scope,
        "mass_mapping": {"atom_ids": raw["atom_ids"], "elements": raw["elements"],
                         "masses_amu": masses, "source": str(stru),
                         "source_section": "ATOMIC_SPECIES"},
        "raw_source_status": raw["status"],
        "raw_source_unresolved_reasons": copy.deepcopy(raw["unresolved_reasons"]),
        "raw_assembly": copy.deepcopy(raw["assembly"]),
        "assembly": {"reciprocity_projection_applied": True, "asr_applied": True,
                     "asr_method": "exact_three_rigid_translations_after_reciprocity_average",
                     "nac_applied": False, "optical_modes_clipped": False},
        "raw_gamma_analysis": copy.deepcopy(raw["gamma_analysis"]),
        "gamma_analysis": {"characteristic_status": "explicitly_processed_local_response",
                           "warnings": copy.deepcopy(processing["warnings"])},
        "status": "unresolved" if unresolved else "complete",
        "unresolved_reasons": unresolved,
        "scientific_status": "specified_geometry_local_response_unqualified",
        "qualification": {"source_mode": "native_source_bound", "scientific": False,
                          "production": False,
                          "reason": "Explicit numerical processing does not qualify equilibrium or production response"},
    })
    result["source"].update({"native_gamma_processing_request": str(path),
                             "standard_file": str(standard_path), "standard_id": standard["standard_id"],
                             "native_refs": source_refs})
    result["source_refs"] = source_refs
    result["native_jobs"].append({
        "role": "gamma_explicit_processing", "task_id": execution["task_id"],
        "scheduler_job_id": str(execution["scheduler_job_id"]), "runner": "slurm",
        "scheduler_state_at_generation": "RUNNING",
        "task_file": str(path), "engine": "numpy", "engine_version": np.__version__,
    })
    result["native_tasks"] = copy.deepcopy(result["native_jobs"])
    return result

def _saved_gamma_file(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _saved_gamma_object(path: Path, name: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _saved_gamma_source_ref(value: Any, name: str, refs: list[str]) -> Path:
    path = _saved_gamma_file(value, name)
    text = str(path)
    if text not in refs:
        refs.append(text)
    return path


def import_saved_gamma(request_path: str | Path) -> dict[str, Any]:
    """Bind a saved explicit Gamma processing product without recomputation."""

    from .dielectric_response import read_native_gamma_force

    request_file = Path(request_path).expanduser().resolve()
    request = _saved_gamma_object(request_file, "saved Gamma import request")
    if request.get("schema") != SAVED_GAMMA_REQUEST_SCHEMA:
        raise ValueError("unsupported saved Gamma import request schema")

    raw_path, processed_path, scheduler_path = (
        _saved_gamma_file(request[key], name)
        for key, name in (
            ("native_raw_product", "saved Gamma native_raw_product"),
            ("saved_processing_product", "saved Gamma saved_processing_product"),
            ("processing_scheduler", "saved Gamma processing_scheduler"),
        )
    )
    mass_source_path = _saved_gamma_file(request["mass_source"], "saved Gamma mass_source")
    standard_path = _saved_gamma_file(request["standard_file"], "saved Gamma standard_file")
    processing_schema = request["saved_processing_schema"]
    if not isinstance(processing_schema, str) or not processing_schema.strip():
        raise ValueError("saved Gamma saved_processing_schema must be a non-empty string")
    execution = request["execution"]
    if not isinstance(execution, Mapping) or execution.get("runner") != "slurm":
        raise ValueError("saved Gamma import execution must be a Slurm object")
    if not isinstance(execution.get("task_id"), str) or not execution["task_id"].strip():
        raise ValueError("saved Gamma import execution.task_id must be a non-empty string")
    if not str(execution.get("scheduler_job_id", "")).isdigit():
        raise ValueError("saved Gamma import execution.scheduler_job_id must be numeric")

    raw = read_native_gamma_force(raw_path)
    processed = _saved_gamma_object(processed_path, "saved Gamma processing product")
    standard = _saved_gamma_object(standard_path, "saved Gamma standard")
    if processed.get("schema") != processing_schema:
        raise ValueError("saved Gamma processing schema differs from request")
    processing = processed["gamma_processing"]
    if processing.get("schema") != SCHEMA:
        raise ValueError("saved Gamma inner processing schema is unsupported")
    if processed.get("operation") != GAMMA_OPERATION or processing.get("operation") != GAMMA_OPERATION:
        raise ValueError("saved Gamma operation differs from the explicit procedure")
    if processing.get("unit") != "eV/angstrom^2":
        raise ValueError("saved Gamma processing unit is unsupported")
    if processing.get("matrix_basis") != raw["matrix_basis"]:
        raise ValueError("saved Gamma processing matrix basis differs from native raw source")
    if processing["matrices"]["raw"] != raw["matrix_eV_per_A2"]:
        raise ValueError("saved raw/processed Gamma matrix mismatch")

    masses = request["masses_amu"]
    if processing["masses_amu"] != masses:
        raise ValueError("saved Gamma mass/plan binding differs from request masses")
    if len(masses) != len(raw["atom_ids"]):
        raise ValueError("saved Gamma request masses do not match native atom count")
    stru = Path(raw["raw_product"]["provenance"]["reference_task_root"]) / "STRU"
    lines = [line.split("#", 1)[0].split("//", 1)[0].strip()
             for line in stru.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in lines if line]
    start = lines.index("ATOMIC_SPECIES") + 1
    species = list(dict.fromkeys(raw["elements"]))
    rows = [line.split() for line in lines[start:start + len(species)]]
    if [row[0] for row in rows] != species:
        raise ValueError("saved Gamma reference STRU species differ from bound atom order")
    masses_by_element = {row[0]: float(row[1]) for row in rows}
    if masses != [masses_by_element[element] for element in raw["elements"]]:
        raise ValueError("saved Gamma masses differ from reference STRU ATOMIC_SPECIES")
    dimension = 3 * len(raw["atom_ids"])
    for name, count in (("raw", dimension), ("symmetric", dimension),
                        ("projected", dimension), ("optical", dimension - 3)):
        if len(processing["spectra"][name]) != count:
            raise ValueError(f"saved Gamma spectra.{name} does not retain all {count} modes")
    processing_matrix = np.asarray(processing["matrices"]["projected"], dtype=float)
    raw_matrix = np.asarray(raw["matrix_eV_per_A2"], dtype=float)
    if processing_matrix.shape != raw_matrix.shape or not np.all(np.isfinite(processing_matrix)):
        raise ValueError("saved Gamma projected matrix has an incompatible shape")

    saved_execution = processed["execution"]
    if not isinstance(saved_execution, Mapping) or saved_execution.get("runner") != "slurm":
        raise ValueError("saved Gamma processing execution must be Slurm")
    postprocess = raw["postprocess_task"]
    if (
        saved_execution.get("scheduler_job_id") != postprocess["scheduler_job_id"]
        or saved_execution.get("runner") != postprocess["runner"]
    ):
        raise ValueError("saved Gamma processing source binding differs from native postprocess job")
    if postprocess["scheduler_state"] != "COMPLETED" or postprocess["exit_code"] != "0:0":
        raise ValueError("native Gamma postprocess job is not COMPLETED/0:0")
    scheduler_text = scheduler_path.read_text(encoding="utf-8")
    scheduler_job_id = str(saved_execution["scheduler_job_id"])
    for marker in (f"JobId={scheduler_job_id}", "JobState=COMPLETED", "ExitCode=0:0"):
        if marker not in scheduler_text.split():
            raise ValueError(f"saved Gamma scheduler evidence lacks {marker}")

    postprocess = raw["postprocess_task"]
    postprocess_source = raw["raw_product"]["source"]
    postprocess_original = _saved_gamma_file(
        postprocess["original_result_file"], "native raw postprocess original_result_file"
    )
    if (
        postprocess_original != _saved_gamma_file(
            postprocess_source["original_result_file"], "native raw source original_result_file"
        )
        or postprocess["conversion_execution"] != postprocess_source["conversion_execution"]
        or postprocess["conversion_execution"] != dict(execution)
    ):
        raise ValueError("saved Gamma processing source binding differs from import execution")
    saved_raw_source = Path(processed["raw_product_source"])
    if not saved_raw_source.is_absolute():
        saved_raw_source = (processed_path.parent / saved_raw_source).resolve()
    if saved_raw_source != postprocess_original:
        raise ValueError("saved Gamma processing source binding differs from native postprocess job")
    if standard.get("schema") != "mlcc.born-gamma-provisional-standard.v1":
        raise ValueError("saved Gamma standard schema is unsupported")
    if standard["standard_id"] != request["standard_id"]:
        raise ValueError("saved Gamma standard_id differs from request")
    if standard["gamma"]["treatment"] != GAMMA_OPERATION:
        raise ValueError("saved Gamma standard treatment differs from operation")
    scope = standard["scope"]
    if scope["material"] != raw["parent"]["model_id"] + "/" + raw["parent"]["model_version"]:
        raise ValueError("saved Gamma standard material differs from native model")
    if scope["response"] != "specified_geometry_local_fixed_cell_zero_macroscopic_electric_field":
        raise ValueError("saved Gamma standard response scope is unsupported")
    if any(scope[key] is not False for key in (
        "equilibrium_reference", "production_qualification", "firing_temperature_response",
    )):
        raise ValueError("saved Gamma local response scope differs from its declared standard")

    raw_reasons = [
        reason for reason in raw["unresolved_reasons"]
        if reason != "raw_gamma_characteristic_status_unresolved_raw_nonsymmetric"
    ]
    optical = processing["spectra"]["optical"]
    nonpositive_optical = not optical or any(
        float(mode["eigenvalue_eV_per_A2_per_amu"]) <= 0.0 for mode in optical
    )
    saved_reasons = list(processed["unresolved_reasons"])
    for reason in raw_reasons:
        if reason not in saved_reasons:
            raise ValueError("saved Gamma processing dropped a native unresolved reason")
    optical_reason = "projected_optical_space_not_positive_definite"
    if nonpositive_optical and optical_reason not in saved_reasons:
        raise ValueError("saved Gamma processing dropped its non-positive optical status")
    if not nonpositive_optical and optical_reason in saved_reasons:
        raise ValueError("saved Gamma processing reports a non-positive optical status without saved evidence")
    if processed["status"] not in ("complete", "unresolved"):
        raise ValueError("saved Gamma processing status is unsupported")
    if saved_reasons and processed["status"] != "unresolved":
        raise ValueError("saved Gamma processing status does not retain unresolved reasons")
    if not saved_reasons and processed["status"] != "complete":
        raise ValueError("saved Gamma processing status is unresolved without a saved reason")

    refs = [str(path) for path in (
        request_file, raw_path, processed_path, scheduler_path, mass_source_path, standard_path, stru,
    )]
    _saved_gamma_source_ref(str(postprocess_original), "native raw original result", refs)
    for index, value in enumerate(raw["source_refs"]):
        _saved_gamma_source_ref(value, f"native raw source_refs[{index}]", refs)
    for index, value in enumerate(processed["source_refs"]):
        _saved_gamma_source_ref(value, f"saved processing source_refs[{index}]", refs)

    source = copy.deepcopy(raw["source"])
    source.update({
        "source_mode": "native_source_bound",
        "native_saved_gamma_request": str(request_file),
        "native_saved_gamma_product": str(processed_path),
        "native_saved_gamma_scheduler": str(scheduler_path),
        "native_saved_gamma_mass_source": str(mass_source_path),
        "native_saved_gamma_standard": str(standard_path),
        "native_refs": list(refs),
    })
    native_jobs = copy.deepcopy(raw["native_jobs"])
    native_jobs.append({"role": "gamma_saved_import", "task_id": execution["task_id"],
                        "scheduler_job_id": str(execution["scheduler_job_id"]), "runner": "slurm",
                        "task_file": str(request_file), "engine": "mlcc.gamma_processing",
                        "engine_version": None, "execution": copy.deepcopy(dict(execution))})
    result = copy.deepcopy(raw)
    response_scope = copy.deepcopy(standard["scope"])
    response_scope.update({
        "reference_max_abs_force_eV_per_A": raw["diagnostics"]["reference_force_residual"]["max_abs_eV_per_A"],
        "reference_force_source": raw["reference"]["result_file"],
        "reference_scheduler_job_id": raw["native_jobs"][0]["scheduler_job_id"],
        "geometry_state": "saved_reference",
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "NAC": False,
    })
    result.update({
        "schema": GAMMA_HESSIAN_SCHEMA,
        "source_mode": "native_source_bound",
        "scientific_status": "native_source_bound_unresolved" if processed["status"] == "unresolved" else "native_source_bound_unqualified",
        "matrix_eV_per_A2": copy.deepcopy(processing["matrices"]["projected"]),
        "explicit_processing": copy.deepcopy(processing),
        "processing_execution": copy.deepcopy(dict(saved_execution)),
        "saved_import_request": copy.deepcopy(request),
        "import_execution": copy.deepcopy(dict(execution)),
        "saved_processing_product": copy.deepcopy(processed),
        "standard": copy.deepcopy(standard),
        "response_scope": response_scope,
        "mass_mapping": {
            "atom_ids": copy.deepcopy(raw["atom_ids"]),
            "elements": copy.deepcopy(raw["elements"]),
            "masses_amu": copy.deepcopy(masses),
            "source": str(stru),
            "source_section": "ATOMIC_SPECIES",
            "declared_mass_source": str(mass_source_path),
        },
        "source": source,
        "source_refs": list(refs),
        "native_jobs": native_jobs,
        "native_tasks": copy.deepcopy(native_jobs),
        "raw_source_status": raw["status"],
        "raw_source_unresolved_reasons": copy.deepcopy(raw["unresolved_reasons"]),
        "raw_assembly": copy.deepcopy(raw["assembly"]),
        "assembly": {
            "reciprocity_projection_applied": True,
            "asr_applied": True,
            "asr_method": "exact_three_rigid_translations_after_reciprocity_average",
            "nac_applied": False,
            "optical_modes_clipped": False,
        },
        "raw_gamma_analysis": copy.deepcopy(raw["gamma_analysis"]),
        "gamma_analysis": {
            "characteristic_status": "explicitly_processed_local_response",
            "warnings": copy.deepcopy(processing["warnings"]),
        },
        "status": processed["status"],
        "unresolved_reasons": copy.deepcopy(saved_reasons),
    })
    return result


__all__ = [
    "SCHEMA",
    "GAMMA_HESSIAN_SCHEMA",
    "SAVED_GAMMA_REQUEST_SCHEMA",
    "optical_response_sensitivity",
    "process_gamma_matrix",
    "process_native_gamma",
    "import_saved_gamma",
]
