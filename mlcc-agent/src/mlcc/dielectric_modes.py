"""Mode-resolved fixed-cell ionic dielectric response.

This module consumes already-saved Born, Gamma, and ionic response products.
It deliberately does not diagonalize a Hessian or solve the ionic response
again: the optical eigenpairs and the translation basis are taken from the
saved Gamma product in their recorded order.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from scipy.constants import elementary_charge, epsilon_0

from .dielectric_response import (
    EPSILON_UNIT,
    FORCE_CONSTANT_UNIT,
    GAMMA_HESSIAN_SCHEMA,
    IONIC_SCHEMA,
    _array,
    _born_matrix,
    _finite_number,
    _mapping,
    _validate_context_geometry,
    _validate_context_pair,
    p5_method_comparison,
)


SCHEMA = "mlcc.dielectric-mode-response.v1"
BORN_SCHEMA = "mlcc.born-charge-columns.v1"
EXPLICIT_GAMMA_SCHEMA = "mlcc.gamma-explicit-processing.v1"
GAUGE = "euclidean_translation_free"
ATOL = 1.0e-8
RTOL = 1.0e-8


def _source_reasons(record: Mapping[str, Any], name: str) -> list[str]:
    value = record.get("unresolved_reasons", [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name}.unresolved_reasons must be a list")
    for index, reason in enumerate(value):
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"{name}.unresolved_reasons[{index}] must be a non-empty string")
    return list(value)


def _source_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep source/job identity without copying large numeric products."""

    keys = (
        "provenance_kind",
        "source_mode",
        "source",
        "source_refs",
        "sources",
        "born_source",
        "gamma_source",
        "native_jobs",
        "native_tasks",
        "processing_execution",
        "import_execution",
        "postprocess_task",
        "raw_product",
        "status",
        "unresolved_reasons",
        "scientific_status",
        "scientific_qualification",
        "numerical_qualification",
        "production_qualified",
        "production_qualification",
        "qualification",
        "qualification_reasons",
        "raw_source_status",
        "raw_source_unresolved_reasons",
        "response_scope",
    )
    return {key: copy.deepcopy(record[key]) for key in keys if key in record}


def _context_from_gamma(gamma: Mapping[str, Any]) -> dict[str, Any]:
    parent = _mapping(gamma["parent"], "gamma.parent")
    context = {
        "parent": {
            "study_id": parent["study_id"],
            "model_id": parent["model_id"],
            "model_version": parent["model_version"],
            "model_path": parent["model_path"],
        },
        "atom_ids": copy.deepcopy(gamma["atom_ids"]),
        "cell_angstrom": copy.deepcopy(gamma["cell_angstrom"]),
        "volume_A3": gamma["volume_A3"],
        "common_method": copy.deepcopy(dict(_mapping(gamma["method_identity"], "gamma.method_identity"))),
    }
    _validate_context_geometry(context, "gamma.context")
    atom_ids = context["atom_ids"]
    if not isinstance(atom_ids, list) or not atom_ids or len(set(atom_ids)) != len(atom_ids):
        raise ValueError("gamma.atom_ids must be a non-empty unique list")
    return context


def _context_from_ionic(ionic: Mapping[str, Any]) -> dict[str, Any]:
    context = dict(_mapping(ionic["context"], "ionic.context"))
    _validate_context_geometry(context, "ionic.context")
    atom_ids = context["atom_ids"]
    if not isinstance(atom_ids, list) or not atom_ids or len(set(atom_ids)) != len(atom_ids):
        raise ValueError("ionic.context.atom_ids must be a non-empty unique list")
    return context


def _born_inputs(born: Mapping[str, Any]) -> tuple[dict[str, Any], np.ndarray | None, np.ndarray | None]:
    if born["schema"] != BORN_SCHEMA:
        raise ValueError("born schema is unsupported")
    context = _mapping(born["context"], "born.context")
    _validate_context_geometry(context, "born.context")
    atom_ids = context["atom_ids"]
    if not isinstance(atom_ids, list) or not atom_ids or len(set(atom_ids)) != len(atom_ids):
        raise ValueError("born.context.atom_ids must be a non-empty unique list")
    if born["unit"] != "e":
        raise ValueError("born.unit must be e")
    tensors = born["full_born_tensors_e"]
    if tensors is None:
        return dict(context), None, None
    born_context, matrix = _born_matrix(born)
    tensor_array = _array(tensors, (len(atom_ids), 3, 3), "born.full_born_tensors_e")
    return born_context, matrix, np.sum(tensor_array, axis=0)


def _gamma_inputs(
    gamma: Mapping[str, Any],
) -> tuple[dict[str, Any], np.ndarray, np.ndarray, list[Mapping[str, Any]]]:
    if gamma["schema"] != GAMMA_HESSIAN_SCHEMA:
        raise ValueError("gamma schema is unsupported")
    if gamma["unit"] != FORCE_CONSTANT_UNIT:
        raise ValueError("gamma.unit must be eV/angstrom^2")
    if gamma["matrix_basis"] != "parent_atom_major_cartesian":
        raise ValueError("gamma.matrix_basis must be parent_atom_major_cartesian")
    if gamma["electrical_boundary"] != "fixed_E_zero":
        raise ValueError("gamma electrical boundary must be fixed_E_zero")
    if gamma["mechanical_boundary"] != "fixed_cell":
        raise ValueError("gamma mechanical boundary must be fixed_cell")
    if gamma["nac"] != "not_applied":
        raise ValueError("gamma.nac must be not_applied")

    context = _context_from_gamma(gamma)
    n_atoms = len(context["atom_ids"])
    explicit = _mapping(gamma["explicit_processing"], "gamma.explicit_processing")
    if explicit["schema"] != EXPLICIT_GAMMA_SCHEMA:
        raise ValueError("gamma.explicit_processing schema is unsupported")
    if explicit["unit"] != FORCE_CONSTANT_UNIT:
        raise ValueError("gamma.explicit_processing.unit must be eV/angstrom^2")
    if explicit["matrix_basis"] != "parent_atom_major_cartesian":
        raise ValueError("gamma.explicit_processing.matrix_basis must be parent_atom_major_cartesian")
    if explicit["atom_count"] != n_atoms:
        raise ValueError("gamma.explicit_processing.atom_count differs from gamma.atom_ids")
    if not isinstance(explicit["operation"], str) or not explicit["operation"]:
        raise ValueError("gamma.explicit_processing.operation must be a non-empty string")

    masses = _array(explicit["masses_amu"], (n_atoms,), "gamma.explicit_processing.masses_amu")
    if np.any(masses <= 0.0):
        raise ValueError("gamma.explicit_processing.masses_amu must be positive")
    mass_mapping = _mapping(gamma["mass_mapping"], "gamma.mass_mapping")
    if mass_mapping["atom_ids"] != context["atom_ids"]:
        raise ValueError("gamma.mass_mapping.atom_ids differs from gamma.atom_ids")
    mapped_masses = _array(
        mass_mapping["masses_amu"], (n_atoms,), "gamma.mass_mapping.masses_amu"
    )
    if not np.allclose(mapped_masses, masses, rtol=0.0, atol=0.0):
        raise ValueError("gamma.mass_mapping.masses_amu differs from gamma.explicit_processing.masses_amu")
    if "elements" in gamma and "elements" in mass_mapping:
        if gamma["elements"] != mass_mapping["elements"]:
            raise ValueError("gamma.mass_mapping.elements differs from gamma.elements")
    translations = _array(
        explicit["translation_basis"],
        (3 * n_atoms, 3),
        "gamma.explicit_processing.translation_basis",
    )
    if not np.allclose(translations.T @ translations, np.eye(3), rtol=0.0, atol=1.0e-10):
        raise ValueError("gamma.explicit_processing.translation_basis must be orthonormal")
    rigid_translations = np.tile(np.eye(3), (n_atoms, 1)) / np.sqrt(float(n_atoms))
    if not np.allclose(
        translations @ translations.T,
        rigid_translations @ rigid_translations.T,
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("gamma.explicit_processing.translation_basis must span rigid translations")
    spectra = _mapping(explicit["spectra"], "gamma.explicit_processing.spectra")
    optical = spectra["optical"]
    if not isinstance(optical, list) or len(optical) != 3 * n_atoms - 3:
        raise ValueError("gamma.explicit_processing.spectra.optical must contain 3N-3 modes")
    for position, mode in enumerate(optical):
        mode = _mapping(mode, f"gamma.explicit_processing.spectra.optical[{position}]")
        _finite_number(
            mode["eigenvalue_eV_per_A2_per_amu"],
            f"gamma optical mode {position} eigenvalue",
        )
        _finite_number(mode["frequency_cm1"], f"gamma optical mode {position} frequency")
        _array(mode["eigenvector"], (3 * n_atoms,), f"gamma optical mode {position} eigenvector")
    return context, masses, translations, optical


def _ionic_inputs(ionic: Mapping[str, Any]) -> tuple[dict[str, Any], np.ndarray | None]:
    if ionic["schema"] != IONIC_SCHEMA:
        raise ValueError("ionic schema is unsupported")
    if ionic["unit"] != EPSILON_UNIT:
        raise ValueError("ionic.unit must be dimensionless")
    if ionic["electrical_boundary"] != "fixed_E_zero":
        raise ValueError("ionic electrical boundary must be fixed_E_zero")
    if ionic["mechanical_boundary"] != "fixed_cell":
        raise ValueError("ionic mechanical boundary must be fixed_cell")
    if ionic["nac"] != "not_applied":
        raise ValueError("ionic.nac must be not_applied")
    context = _context_from_ionic(ionic)
    value = ionic["delta_epsilon_ionic"]
    delta = None if value is None else _array(value, (3, 3), "ionic.delta_epsilon_ionic")
    return context, delta


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _mode_result(
    source_mode: Mapping[str, Any],
    position: int,
    masses: np.ndarray,
    translations: np.ndarray,
    born_matrix: np.ndarray | None,
    scale: float,
    delta_ready: bool,
) -> dict[str, Any]:
    eigenvalue = _finite_number(
        source_mode["eigenvalue_eV_per_A2_per_amu"],
        f"gamma optical mode {position} eigenvalue",
    )
    eigenvector = _array(
        source_mode["eigenvector"],
        (len(masses) * 3,),
        f"gamma optical mode {position} eigenvector",
    )
    mass_coordinates = np.repeat(masses, 3)
    u_raw = eigenvector / np.sqrt(mass_coordinates)
    u_gauge = u_raw - translations @ (translations.T @ u_raw)
    projection_change = u_gauge - u_raw
    raw_coupling = None if born_matrix is None else born_matrix @ u_raw
    gauge_coupling = None if born_matrix is None else born_matrix @ u_gauge
    strength = None if gauge_coupling is None else np.outer(gauge_coupling, gauge_coupling)
    delta = None
    if delta_ready and eigenvalue > 0.0:
        delta = scale * strength / eigenvalue

    result = copy.deepcopy(dict(source_mode))
    result.update(
        {
            "mode_position": position,
            "mode_response_semantics": (
                "saved_mass_weighted_gamma_basis_after_euclidean_translation_projection"
            ),
            "lambda_source": "eigenvalue_eV_per_A2_per_amu",
            "raw_born_coupling_semantics": "gauge_sensitive_diagnostic_only",
            "u_raw_amu_minus_half": u_raw.tolist(),
            "u_gauge_amu_minus_half": u_gauge.tolist(),
            "projection_change_amu_minus_half": projection_change.tolist(),
            "raw_born_coupling_e_per_sqrt_amu": (
                None if raw_coupling is None else raw_coupling.tolist()
            ),
            "gauge_born_coupling_e_per_sqrt_amu": (
                None if gauge_coupling is None else gauge_coupling.tolist()
            ),
            "strength_e2_per_amu": None if strength is None else strength.tolist(),
            "delta_epsilon_ionic": None if delta is None else delta.tolist(),
        }
    )
    return result


def calculate_dielectric_modes(
    born: Mapping[str, Any],
    gamma: Mapping[str, Any],
    ionic: Mapping[str, Any],
    *,
    displacement_gauge: str,
) -> dict[str, Any]:
    """Calculate the saved-Gamma mode decomposition of the ionic response."""

    if displacement_gauge != GAUGE:
        raise ValueError(f"unsupported displacement_gauge: {displacement_gauge}")
    born_context, born_matrix, born_sum_residual = _born_inputs(born)
    gamma_context, masses, translations, optical = _gamma_inputs(gamma)
    ionic_context, saved_ionic_delta = _ionic_inputs(ionic)

    _validate_context_pair(gamma_context, born_context, "Gamma")
    _validate_context_pair(ionic_context, born_context, "ionic")
    method_comparison = {
        "born_gamma": p5_method_comparison(
            born_context["common_method"], gamma_context["common_method"]
        ),
        "born_ionic": p5_method_comparison(
            born_context["common_method"], ionic_context["common_method"]
        ),
        "gamma_ionic": p5_method_comparison(
            gamma_context["common_method"], ionic_context["common_method"]
        ),
    }

    reasons: list[str] = []
    born_reasons = _source_reasons(born, "born")
    gamma_reasons = _source_reasons(gamma, "gamma")
    ionic_reasons = _source_reasons(ionic, "ionic")
    for reason in (*born_reasons, *gamma_reasons, *ionic_reasons):
        _add_reason(reasons, reason)
    if born_matrix is None:
        _add_reason(reasons, "born_tensor_incomplete")
    if born["status"] == "unresolved":
        _add_reason(reasons, "born_tensor_unresolved")
    if gamma["status"] != "complete":
        _add_reason(reasons, "gamma_force_constants_unresolved")
    if ionic["status"] != "complete":
        _add_reason(reasons, "ionic_contribution_unresolved")
    elif saved_ionic_delta is None:
        _add_reason(reasons, "ionic_contribution_missing")
    nonpositive_modes = [
        position
        for position, mode in enumerate(optical)
        if _finite_number(
            mode["eigenvalue_eV_per_A2_per_amu"],
            f"gamma optical mode {position} eigenvalue",
        )
        <= 0.0
    ]
    if nonpositive_modes:
        _add_reason(reasons, "optical_space_not_positive_definite")

    delta_ready = (
        born_matrix is not None
        and gamma["status"] == "complete"
        and ionic["status"] == "complete"
        and saved_ionic_delta is not None
        and not nonpositive_modes
        and not reasons
    )
    scale = elementary_charge * 1.0e10 / (epsilon_0 * float(born_context["volume_A3"]))
    modes = [
        _mode_result(
            source_mode=mode,
            position=position,
            masses=masses,
            translations=translations,
            born_matrix=born_matrix,
            scale=scale,
            delta_ready=delta_ready,
        )
        for position, mode in enumerate(optical)
    ]

    total = None
    closure_computed = None
    closure_difference = None
    closure_max_abs = None
    closure_matches = None
    if delta_ready:
        total_array = sum(
            (np.asarray(mode["delta_epsilon_ionic"], dtype=float) for mode in modes),
            np.zeros((3, 3), dtype=float),
        )
        total = total_array.tolist()
        closure_computed = total_array.tolist()
        closure_difference_array = total_array - saved_ionic_delta
        closure_difference = closure_difference_array.tolist()
        closure_max_abs = float(np.max(np.abs(closure_difference_array)))
        closure_matches = bool(
            np.allclose(total_array, saved_ionic_delta, rtol=RTOL, atol=ATOL)
        )

    return {
        "schema": SCHEMA,
        "operation": "saved_gamma_mode_resolved_ionic_dielectric_response",
        "status": "complete" if not reasons else "unresolved",
        "unresolved_reasons": reasons,
        "displacement_gauge": displacement_gauge,
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "unit": EPSILON_UNIT,
        "field_units": {
            "eigenvalue": "eV/(angstrom^2*amu)",
            "frequency": "cm^-1",
            "displacement": "1/sqrt(amu)",
            "born_coupling": "e/sqrt(amu)",
            "strength": "e^2/amu",
            "delta_epsilon_ionic": EPSILON_UNIT,
        },
        "mode_semantics": {
            "eigenvalue": (
                "lambda is the saved Gamma eigenvalue in eV/(angstrom^2*amu); "
                "it is not reconstructed from frequency_cm1 or frequency_cm1^2"
            ),
            "eigenvector": "saved mass_weighted_gamma_eigenvector_in_recorded_order",
            "displacement": "u=M^(-1/2)e",
            "gauge": (
                "u_gauge=(I-T@T.T)u; T is the saved Euclidean rigid-translation basis; "
                "no independent constrained eigensolve, renormalization, rotation, or reorder"
            ),
            "raw_born_coupling": "diagnostic_only_gauge_sensitive_not_static_response",
            "mode_response": "gauge_born_coupling_outer_product_divided_by_saved_lambda",
            "degenerate_modes": (
                "individual contributions depend on the saved degenerate basis; "
                "only the complete degenerate subspace sum has basis-invariant meaning"
            ),
        },
        "context": copy.deepcopy(born_context),
        "method_identity": copy.deepcopy(born_context["common_method"]),
        "source_methods": {
            "born": copy.deepcopy(born_context["common_method"]),
            "gamma": copy.deepcopy(gamma["method_identity"]),
            "ionic": copy.deepcopy(ionic_context["common_method"]),
        },
        "method_comparison": method_comparison,
        "masses_amu": masses.tolist(),
        "mass_mapping": copy.deepcopy(gamma["mass_mapping"]),
        "response_scope": copy.deepcopy(gamma.get("response_scope")),
        "source_response_scopes": {
            "born": copy.deepcopy(born.get("response_scope")),
            "gamma": copy.deepcopy(gamma.get("response_scope")),
            "ionic": copy.deepcopy(ionic.get("response_scope")),
        },
        "translation_basis": translations.tolist(),
        "translation_projection": "I - T @ T.T",
        "born_matrix_e": None if born_matrix is None else born_matrix.tolist(),
        "raw_born_sum_rule_residual_e": (
            None if born_sum_residual is None else born_sum_residual.tolist()
        ),
        "volume_A3": float(born_context["volume_A3"]),
        "scale_elementary_charge_1e10_over_epsilon0_volume": float(scale),
        "modes": modes,
        "total_delta_epsilon_ionic": total,
        "saved_ionic_delta_epsilon": (
            None if saved_ionic_delta is None else saved_ionic_delta.tolist()
        ),
        "closure": {
            "status": "evaluated" if delta_ready else "unresolved",
            "atol": ATOL,
            "rtol": RTOL,
            "computed_total": closure_computed,
            "saved_ionic_delta": (
                None if saved_ionic_delta is None else saved_ionic_delta.tolist()
            ),
            "difference_computed_minus_saved": closure_difference,
            "max_abs_difference": closure_max_abs,
            "matches": closure_matches,
        },
        "sources": {
            "born": _source_record(born),
            "gamma": _source_record(gamma),
            "ionic": _source_record(ionic),
        },
        "source_status": {
            "born": {"status": born.get("status"), "unresolved_reasons": born_reasons},
            "gamma": {"status": gamma.get("status"), "unresolved_reasons": gamma_reasons},
            "ionic": {"status": ionic.get("status"), "unresolved_reasons": ionic_reasons},
        },
    }


def analyze_dielectric_modes_request(request_path: str | Path) -> dict[str, Any]:
    """Bind four saved JSON inputs and analyze their recorded optical basis."""
    from .property_delivery import (
        _bind_task,
        _p5_context,
        _p5_context_equal,
        _p5_declared_mode,
        _p5_source_paths,
        _p5_validate_born,
        _p5_validate_declared_method,
        _p5_validate_gamma,
        _p5_validate_ionic,
        _read_json,
    )

    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request["schema"] != "mlcc.dielectric-modes-request.v1":
        raise ValueError("unsupported dielectric modes request")
    paths = {
        label: (request_file.parent / Path(request[label]).expanduser()).resolve()
        for label in ("study", "born", "gamma", "ionic")
    }
    study = _read_json(paths["study"])
    products = {label: _read_json(paths[label]) for label in ("born", "gamma", "ionic")}
    contexts = {label: _p5_context(product, label) for label, product in products.items()}
    anchor = contexts["born"]
    _bind_task(anchor["parent"], study, paths["born"])
    declared_model_path = study["model"].get("model_path", study["model"].get("path"))
    if declared_model_path is not None:
        study_model_path = (paths["study"].parent / Path(declared_model_path).expanduser()).resolve()
        if study_model_path != Path(anchor["parent"]["model_path"]):
            raise ValueError("Born model path differs from explicit Study model path")
    modes = {}
    for label, product in products.items():
        if not _p5_context_equal(anchor, contexts[label]):
            raise ValueError(f"{label} context differs from Born context")
        _p5_validate_declared_method(product, label, contexts[label])
        modes[label] = _p5_declared_mode(product, label)
    if len(set(modes.values())) != 1:
        raise ValueError("dielectric mode inputs contain different source modes")
    _p5_validate_born(products["born"], contexts["born"])
    _p5_validate_gamma(products["gamma"], contexts["gamma"])
    _p5_validate_ionic(products["ionic"], products["born"], products["gamma"])

    result = calculate_dielectric_modes(
        products["born"], products["gamma"], products["ionic"],
        displacement_gauge=request["displacement_gauge"],
    )
    source_files = {"request": str(request_file), **{label: str(path) for label, path in paths.items()}}
    source_refs = list(source_files.values())
    for label, product in products.items():
        source_refs.extend(_p5_source_paths(product, label))
    result.update({
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": study["case_role"],
        "model_refs": copy.deepcopy(study["model"]),
        "source_mode": modes["born"],
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "native_jobs": {
            label: copy.deepcopy(products[label]["native_jobs"])
            for label in ("born", "gamma")
        },
        "source_files": source_files,
        "source_refs": source_refs,
    })
    return result


__all__ = ["ATOL", "RTOL", "SCHEMA", "calculate_dielectric_modes", "analyze_dielectric_modes_request"]
