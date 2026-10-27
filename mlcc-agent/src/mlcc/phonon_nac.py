"""Directional Gamma non-analytic correction for a saved phonon result.

The adapter consumes the source-bound force constants already used by the
Gamma Hessian path. It evaluates one explicit Gamma direction with the
installed Phonopy Wang implementation and returns the uncorrected and
corrected dynamical matrices. It never fits forces, creates displacements,
applies ASR, or changes the fixed-cell ionic-dielectric Hessian.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from phonopy.harmonic.dynamical_matrix import get_dynamical_matrices_at_qpoints
from phonopy.physical_units import get_physical_units

from .dielectric_response import (
    _born_matrix,
    _electronic_tensor,
    _validate_context_pair,
    bind_external_electronic_input,
)
from .phonon_gamma import (
    _absolute_existing_path,
    _load_json_object,
    _positive_or_zero,
    _required_mapping,
    _validate_harmonic_result,
    _validate_parent_binding,
    _validate_primitive_parent,
    _validate_source_binding,
)
from .phonons import (
    FORCE_CONSTANT_UNIT,
    HARMONIC_SCHEMA,
    _rebuild_phonopy_from_plan,
    load_phonon_displacement_plan,
)


NAC_SCHEMA = "mlcc.phonon-gamma-nac.v1"
NAC_METHOD = "wang"
NAC_DIRECTION_BASIS = "primitive_reciprocal_fractional"
DYNAMICAL_MATRIX_UNIT = "eV/angstrom^2/amu"


def _field(request: Mapping[str, Any], name: str) -> Any:
    if name not in request:
        raise ValueError(f"request.{name} must be explicit")
    return request[name]


def _direction(value: Any, name: str) -> np.ndarray:
    vector = np.asarray(value, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must be a finite three-vector")
    norm = float(np.linalg.norm(vector))
    if norm <= 0.0:
        raise ValueError(f"{name} must be non-zero")
    return vector


def _matrix(
    value: Any,
    *,
    name: str,
    imaginary_tolerance: float,
) -> tuple[np.ndarray, float, float]:
    matrix = np.asarray(value)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError(f"{name} must be a square dynamical matrix")
    if not np.all(np.isfinite(matrix.real)) or not np.all(np.isfinite(matrix.imag)):
        raise ValueError(f"{name} must contain finite values")
    observed = float(np.max(np.abs(matrix.imag)))
    if observed > imaginary_tolerance:
        raise ValueError(
            f"{name} imaginary residual exceeds the explicit tolerance: {observed} > {imaginary_tolerance}"
        )
    hermitian_residual = float(np.max(np.abs(matrix - matrix.conj().T)))
    return np.asarray(matrix.real, dtype=float), observed, hermitian_residual


def _frequencies(value: np.ndarray, *, name: str, factor: float) -> np.ndarray:
    eigenvalues = np.linalg.eigvalsh(value)
    if eigenvalues.ndim != 1 or not np.all(np.isfinite(eigenvalues)):
        raise ValueError(f"{name} eigenvalues must be one finite Gamma row")
    # Preserve imaginary-mode signs from the raw eigenvalues. This adapter does
    # not clip negative values or symmetrize the low-level matrix first.
    return np.ascontiguousarray(
        np.sqrt(np.abs(eigenvalues)) * np.sign(eigenvalues) * factor,
        dtype="double",
    )


def _gamma_context(
    parent: Mapping[str, Any],
    atom_ids: list[int],
    cell: np.ndarray,
    volume: float,
    method: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "parent": {
            "study_id": parent["study_id"],
            "model_id": parent["model_id"],
            "model_version": parent["model_version"],
            "model_path": str(Path(parent["model_path"]).resolve()),
        },
        "atom_ids": list(atom_ids),
        "cell_angstrom": cell.tolist(),
        "volume_A3": float(volume),
        "common_method": copy.deepcopy(dict(method)),
    }


def _source_mode_gates(
    born: Mapping[str, Any],
    electronic: Mapping[str, Any],
    bound_source: Mapping[str, Any],
    *,
    electronic_path: Path,
) -> tuple[dict[str, Any], str]:
    """Apply the existing P5 source gates without duplicating their rules."""

    # Runtime imports avoid a top-level property_delivery/phonon_nac cycle.
    from .property_delivery import (
        _p5_context,
        _p5_declared_mode,
        _p5_native_born,
        _p5_validate_born,
    )

    born_context = _p5_context(born, "born")
    source_mode = str(bound_source["source_mode"])
    if _p5_declared_mode(born, "born") != source_mode:
        raise ValueError("Born source_mode differs from the bound phonon source")
    _p5_validate_born(born, born_context)
    if source_mode == "native_source_bound":
        _p5_native_born(born, born_context)

    if "provenance_kind" in electronic:
        bound_electronic = bind_external_electronic_input(electronic, electronic_path)
        electronic_mode = _p5_declared_mode(bound_electronic, "electronic")
        if electronic_mode != "external_supplied":
            raise ValueError("external electronic provenance is inconsistent")
    else:
        bound_electronic = dict(electronic)
        electronic_mode = _p5_declared_mode(bound_electronic, "electronic")
        if electronic_mode == "native_source_bound":
            raise NotImplementedError("native electronic P5 input has no producer contract in this slice")
        if electronic_mode != source_mode:
            raise ValueError("electronic source_mode differs from the bound Born source")
    return bound_electronic, source_mode


def compute_gamma_directional_nac(
    request: Mapping[str, Any],
    born: Mapping[str, Any],
    electronic: Mapping[str, Any],
    *,
    born_path: str | Path,
    electronic_path: str | Path,
) -> dict[str, Any]:
    """Evaluate one explicit Gamma-direction Wang NAC.

    ``request`` is the persisted Gamma request with explicit ``nac_method``,
    ``direction_basis`` and ``nac_q_direction`` fields. All source, parent,
    geometry, method, unit and atom-order checks precede the Phonopy call.
    """

    if not isinstance(request, Mapping) or not request:
        raise ValueError("request must be a non-empty object")
    if _field(request, "nac_method") != NAC_METHOD:
        raise ValueError("request.nac_method must be exactly 'wang'")
    if _field(request, "direction_basis") != NAC_DIRECTION_BASIS:
        raise ValueError(
            "request.direction_basis must be exactly 'primitive_reciprocal_fractional'"
        )
    raw_direction = _direction(_field(request, "nac_q_direction"), "request.nac_q_direction")
    normalized_direction = raw_direction / float(np.linalg.norm(raw_direction))

    harmonic_file = _absolute_existing_path(
        _field(request, "harmonic_result_path"),
        "request.harmonic_result_path",
        directory=False,
    )
    plan_file = _absolute_existing_path(_field(request, "plan_path"), "request.plan_path", directory=False)
    parent = _required_mapping(_field(request, "parent"), "request.parent")
    method = dict(_required_mapping(_field(request, "method_identity"), "request.method_identity"))
    source_binding = _required_mapping(_field(request, "source_binding"), "request.source_binding")
    geometry_tolerance = _positive_or_zero(
        _field(request, "geometry_tolerance_angstrom"), "request.geometry_tolerance_angstrom"
    )
    volume_tolerance = _positive_or_zero(_field(request, "volume_tolerance_A3"), "request.volume_tolerance_A3")
    mass_tolerance = _positive_or_zero(_field(request, "mass_tolerance_amu"), "request.mass_tolerance_amu")
    imaginary_tolerance = _positive_or_zero(
        _field(request, "dynamical_imag_tolerance"), "request.dynamical_imag_tolerance"
    )
    hermitian_tolerance = _positive_or_zero(
        _field(request, "dynamical_hermitian_tolerance"),
        "request.dynamical_hermitian_tolerance",
    )
    born_file = _absolute_existing_path(born_path, "born_path", directory=False)
    electronic_file = _absolute_existing_path(electronic_path, "electronic_path", directory=False)
    if not isinstance(born, Mapping) or not born:
        raise ValueError("born must be a non-empty object")
    if not isinstance(electronic, Mapping) or not electronic:
        raise ValueError("electronic must be a non-empty object")

    # Input paths are bound to the exact JSON-shaped mappings supplied by the
    # caller. No hash or content-addressed cache is introduced.
    saved_born = _load_json_object(born_file, "born_path")
    if saved_born != dict(born):
        raise ValueError("born input mapping differs from born_path")
    saved_electronic = _load_json_object(electronic_file, "electronic_path")
    if saved_electronic != dict(electronic):
        raise ValueError("electronic input mapping differs from electronic_path")

    manifest = load_phonon_displacement_plan(plan_file)
    harmonic = _load_json_object(harmonic_file, "harmonic_result_path")
    force_constants = _validate_harmonic_result(harmonic_file, plan_file, harmonic, manifest)
    bound_parent, source_parent = _validate_parent_binding(parent, manifest)
    bound_source, _force_bundle = _validate_source_binding(
        source_binding,
        harmonic_path=harmonic_file,
        plan_path=plan_file,
        manifest=manifest,
        harmonic=harmonic,
        method_identity=method,
        parent_binding=bound_parent,
    )
    if bound_source["source_mode"] == "native_source_bound":
        method = dict(bound_source["native_method_sources"][0]["method_record"])
    if manifest["request"].get("hermitianize_dynamical_matrix") is not False:
        raise ValueError("Gamma NAC requires hermitianize_dynamical_matrix=false")
    if manifest["request"].get("is_symmetry") is not False:
        raise ValueError("Gamma NAC requires is_symmetry=false")

    bound_electronic, source_mode = _source_mode_gates(
        born, electronic, bound_source, electronic_path=electronic_file
    )
    phonon = _rebuild_phonopy_from_plan(plan_file, manifest)
    parent_atom_ids, primitive_masses, volume = _validate_primitive_parent(
        phonon,
        source_parent,
        geometry_tolerance_angstrom=geometry_tolerance,
        volume_tolerance_A3=volume_tolerance,
        mass_tolerance_amu=mass_tolerance,
    )
    atom_ids = [int(value) for value in parent_atom_ids]
    cell = np.asarray(source_parent.atoms.cell.array, dtype=float)
    if force_constants.shape != (len(phonon.supercell), len(phonon.supercell), 3, 3):
        raise ValueError("harmonic force_constants shape does not match the reconstructed Phonopy supercell")

    gamma_context = _gamma_context(bound_parent, atom_ids, cell, volume, method)
    born_context, born_matrix = _born_matrix(born)
    if born.get("missing_columns") != []:
        raise ValueError("Born product contains missing columns")
    _validate_context_pair(born_context, gamma_context, "born")
    # _born_matrix exposes columns as displacement axes. Phonopy consumes
    # born[atom, polarization, displacement], so transpose the final axes.
    born_values = born_matrix.T.reshape(len(atom_ids), 3, 3).transpose(0, 2, 1)
    electronic_values = _electronic_tensor(bound_electronic, gamma_context)
    if not np.allclose(electronic_values, electronic_values.T, rtol=0.0, atol=1e-12):
        raise ValueError("electronic.tensor must be symmetric")
    if float(np.min(np.linalg.eigvalsh(electronic_values))) <= 0.0:
        raise ValueError("electronic.tensor must be positive definite")

    phonon.force_constants = force_constants
    qpoints = np.asarray([[0.0, 0.0, 0.0]], dtype="double")
    units = get_physical_units()
    baseline_raw = get_dynamical_matrices_at_qpoints(
        phonon.dynamical_matrix,
        qpoints,
        nac_q_direction=None,
        hermitianize=False,
        lang="Rust",
    )
    baseline_dynamical, baseline_imaginary, baseline_hermitian = _matrix(
        np.asarray(baseline_raw)[0],
        name="baseline Gamma dynamical matrix",
        imaginary_tolerance=imaginary_tolerance,
    )
    if baseline_hermitian > hermitian_tolerance:
        raise ValueError(
            "baseline Gamma dynamical matrix Hermitian residual exceeds the explicit tolerance: "
            f"{baseline_hermitian} > {hermitian_tolerance}"
        )
    baseline_frequencies = _frequencies(
        baseline_dynamical,
        name="baseline Gamma",
        factor=float(units.DefaultToTHz),
    )

    nac_factor = float(units.Hartree * units.Bohr)
    if not np.isfinite(nac_factor) or nac_factor <= 0.0:
        raise ValueError("installed Phonopy NAC unit factor must be finite and positive")
    phonon.nac_params = {
        "born": born_values,
        "dielectric": electronic_values,
        "factor": nac_factor,
        "method": NAC_METHOD,
    }
    corrected_raw = get_dynamical_matrices_at_qpoints(
        phonon.dynamical_matrix,
        qpoints,
        nac_q_direction=normalized_direction.tolist(),
        hermitianize=False,
        lang="Rust",
    )
    corrected_dynamical, corrected_imaginary, corrected_hermitian = _matrix(
        np.asarray(corrected_raw)[0],
        name="corrected Gamma dynamical matrix",
        imaginary_tolerance=imaginary_tolerance,
    )
    if corrected_hermitian > hermitian_tolerance:
        raise ValueError(
            "corrected Gamma dynamical matrix Hermitian residual exceeds the explicit tolerance: "
            f"{corrected_hermitian} > {hermitian_tolerance}"
        )
    corrected_frequencies = _frequencies(
        corrected_dynamical,
        name="corrected Gamma",
        factor=float(units.DefaultToTHz),
    )
    correction = corrected_dynamical - baseline_dynamical

    return {
        "schema": NAC_SCHEMA,
        "scientific_status": (
            "native_source_bound_unqualified" if source_mode == "native_source_bound" else "software_math_only_unqualified"
        ),
        "scientific_qualification": False,
        "production_qualification": False,
        "parent": bound_parent,
        "atom_ids": atom_ids,
        "elements": [str(value) for value in source_parent.atoms.get_chemical_symbols()],
        "cell_angstrom": cell.tolist(),
        "volume_A3": float(volume),
        "masses_amu": primitive_masses.tolist(),
        "method_identity": method,
        "source": {
            **bound_source,
            "harmonic_schema": HARMONIC_SCHEMA,
            "harmonic_force_constants_basis": harmonic["force_constants_basis"],
            "harmonic_force_constants_unit": harmonic["force_constants_unit"],
            "harmonic_scientific_status": harmonic.get("scientific_status"),
            "harmonic_scientific_qualification": harmonic.get("scientific_qualification"),
            "harmonic_production_qualified": harmonic.get("production_qualified"),
        },
        "source_mode": source_mode,
        "born_input": {
            "path": str(born_file),
            "schema": born["schema"],
            "unit": born["unit"],
            "atom_ids": atom_ids,
            "full_born_tensors_e": copy.deepcopy(born["full_born_tensors_e"]),
            "sources": copy.deepcopy(born.get("sources", [])),
        },
        "electronic_input": {
            "path": str(electronic_file),
            "kind": bound_electronic["kind"],
            "unit": bound_electronic["unit"],
            "atom_ids": atom_ids,
            "tensor": copy.deepcopy(bound_electronic["tensor"]),
            "source_refs": copy.deepcopy(bound_electronic.get("source_refs", [])),
            "provenance_kind": bound_electronic.get("provenance_kind"),
            "electrical_boundary": bound_electronic["electrical_boundary"],
            "mechanical_boundary": bound_electronic["mechanical_boundary"],
            "ions": bound_electronic["ions"],
        },
        "nac_method": NAC_METHOD,
        "direction_basis": NAC_DIRECTION_BASIS,
        "nac_q_direction": raw_direction.tolist(),
        "nac_q_direction_normalized": normalized_direction.tolist(),
        "q_point": [0.0, 0.0, 0.0],
        "dynamical_matrix_unit": DYNAMICAL_MATRIX_UNIT,
        "nac_unit_conversion": {
            "force_constants_input_unit": FORCE_CONSTANT_UNIT,
            "born_input_unit": "e",
            "electronic_input_unit": "dimensionless",
            "nac_factor": nac_factor,
            "nac_factor_unit": "eV*angstrom",
            "nac_factor_definition": "installed_phonopy.Hartree * installed_phonopy.Bohr",
            "frequency_conversion_to_THz": float(units.DefaultToTHz),
        },
        "baseline": {
            "nac": "not_applied",
            "frequencies_THz": baseline_frequencies.tolist(),
            "dynamical_matrix": baseline_dynamical.tolist(),
            "dynamical_matrix_unit": DYNAMICAL_MATRIX_UNIT,
        },
        "corrected": {
            "nac": NAC_METHOD,
            "frequencies_THz": corrected_frequencies.tolist(),
            "dynamical_matrix": corrected_dynamical.tolist(),
            "dynamical_matrix_unit": DYNAMICAL_MATRIX_UNIT,
        },
        "correction": {
            "dynamical_matrix": correction.tolist(),
            "dynamical_matrix_unit": DYNAMICAL_MATRIX_UNIT,
            "formula": "D_corrected - D_baseline",
        },
        "imaginary_frequencies_preserved": True,
        "asr": "not_applied",
        "hermitianize": False,
        "born_epsilon_symmetrized": False,
        "tolerances": {
            "geometry_angstrom": geometry_tolerance,
            "volume_A3": volume_tolerance,
            "mass_amu": mass_tolerance,
            "dynamical_imaginary": imaginary_tolerance,
            "dynamical_hermitian": hermitian_tolerance,
            "baseline_observed_dynamical_imaginary": baseline_imaginary,
            "corrected_observed_dynamical_imaginary": corrected_imaginary,
            "baseline_observed_dynamical_hermitian_residual": baseline_hermitian,
            "corrected_observed_dynamical_hermitian_residual": corrected_hermitian,
        },
        "qualification": {
            "source_mode": source_mode,
            "scientific": False,
            "production": False,
            "reason": "Directional NAC calculation does not establish material scientific qualification",
        },
    }


__all__ = ["NAC_SCHEMA", "compute_gamma_directional_nac"]
