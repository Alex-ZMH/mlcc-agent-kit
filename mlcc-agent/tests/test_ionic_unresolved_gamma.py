from __future__ import annotations

import copy

import numpy as np

import mlcc.dielectric_response as dielectric_module
from mlcc.dielectric_response import calculate_ionic_dielectric, combine_dielectric_contributions


def _context() -> dict:
    return {
        "parent": {
            "study_id": "study",
            "model_id": "model",
            "model_version": "v001",
            "model_path": "/model",
        },
        "atom_ids": [10, 20],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
        "common_method": {"engine": "mathematical_fixture", "method_set": "math_fixture"},
    }


def _born(*, unresolved: bool = False) -> dict:
    return {
        "schema": "mlcc.born-charge-columns.v1",
        "context": _context(),
        "unit": "e",
        "full_born_tensors_e": None
        if unresolved
        else [
            [[1.0, 0.2, 0.0], [0.0, 1.0, 0.3], [0.4, 0.0, 1.0]],
            [[-1.0, -0.2, 0.0], [0.0, -1.0, -0.3], [-0.4, 0.0, -1.0]],
        ],
        "sources": [{"response_id": "fixture-born"}],
    }


def _gamma() -> dict:
    matrix = 2.0 * np.block([[np.eye(3), -np.eye(3)], [-np.eye(3), np.eye(3)]])
    return {
        "schema": "mlcc.gamma-force-constants.v1",
        "parent": _context()["parent"],
        "atom_ids": [10, 20],
        "cell_angstrom": _context()["cell_angstrom"],
        "volume_A3": 64.0,
        "unit": "eV/angstrom^2",
        "matrix_basis": "parent_atom_major_cartesian",
        "matrix_eV_per_A2": matrix.tolist(),
        "method_identity": _context()["common_method"],
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "source": {"harmonic_result": "gamma://raw", "plan_manifest": "gamma://plan"},
        "status": "unresolved",
        "unresolved_reasons": ["raw_gamma_characteristic_status_unresolved_raw_nonsymmetric"],
        "thresholds": {
            "symmetry_eV_per_A2": 1.0e-12,
            "translation_eV_per_A2": 1.0e-12,
            "born_sum_e": 1.0e-12,
            "minimum_optical_eigenvalue_eV_per_A2": 1.0e-8,
        },
    }


def _thresholds() -> dict[str, float]:
    return {
        "symmetry_eV_per_A2": 1.0e9,
        "translation_eV_per_A2": 1.0e9,
        "born_sum_e": 1.0e9,
        "minimum_optical_eigenvalue_eV_per_A2": 0.0,
    }


def _electronic() -> dict:
    context = _context()
    return {
        "kind": "epsilon_infinity_relative",
        "parent": context["parent"],
        "atom_ids": context["atom_ids"],
        "cell_angstrom": context["cell_angstrom"],
        "volume_A3": context["volume_A3"],
        "method_identity": context["common_method"],
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "ions": "clamped",
        "unit": "dimensionless",
        "tensor": np.eye(3).tolist(),
        "source_refs": ["epsilon://fixture"],
    }


def test_unresolved_gamma_never_enters_eigensolver_even_with_relaxed_tolerances(monkeypatch):
    born = _born()
    gamma = _gamma()
    matrix_before = copy.deepcopy(gamma["matrix_eV_per_A2"])

    def unexpected_solver(*args, **kwargs):
        raise AssertionError("unresolved Gamma must not enter eigensolver or solve")

    monkeypatch.setattr(dielectric_module.np.linalg, "eigvalsh", unexpected_solver)
    monkeypatch.setattr(dielectric_module.np.linalg, "solve", unexpected_solver)

    result = calculate_ionic_dielectric(born, gamma, thresholds=_thresholds())

    assert result["status"] == "unresolved"
    assert result["delta_epsilon_ionic"] is None
    assert result["unresolved_reasons"] == [
        "gamma_force_constants_unresolved",
        "raw_gamma_characteristic_status_unresolved_raw_nonsymmetric",
    ]
    assert result["gamma_source"] == gamma["source"]
    assert result["gamma_method_comparison"]["same_physical_method"] is True
    assert result["method_identity"] == born["context"]["common_method"]
    assert result["scientific_qualification"] is False
    assert result["numerical_qualification"] is False
    assert result["production_qualification"] is False
    assert result["qualification"]["scientific_qualification"] is False
    assert gamma["matrix_eV_per_A2"] == matrix_before


def test_unresolved_born_and_gamma_keep_reasons_and_leave_combined_static_null():
    born = _born(unresolved=True)
    gamma = _gamma()

    ionic = calculate_ionic_dielectric(born, gamma, thresholds=_thresholds())

    assert ionic["status"] == "unresolved"
    assert ionic["delta_epsilon_ionic"] is None
    assert ionic["unresolved_reasons"] == [
        "born_tensor_incomplete",
        "gamma_force_constants_unresolved",
        "raw_gamma_characteristic_status_unresolved_raw_nonsymmetric",
    ]
    assert ionic["born_source"]["sources"] == born["sources"]
    assert ionic["gamma_source"] == gamma["source"]

    combined = combine_dielectric_contributions(born, _electronic(), ionic)

    assert combined["epsilon_infinity"] == np.eye(3).tolist()
    assert combined["delta_epsilon_ionic"] is None
    assert combined["epsilon_static"] is None
    assert combined["status"] == "unresolved"
    assert combined["ionic"]["unresolved_reasons"] == ionic["unresolved_reasons"]

