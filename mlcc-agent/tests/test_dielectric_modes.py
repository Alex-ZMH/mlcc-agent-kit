from __future__ import annotations

import copy
import json

import numpy as np
import pytest
from scipy.constants import elementary_charge, epsilon_0

from mlcc.dielectric_modes import calculate_dielectric_modes


def _context() -> dict:
    return {
        "parent": {
            "study_id": "mode-study",
            "model_id": "mode-model",
            "model_version": "v001",
            "model_path": "/model",
        },
        "atom_ids": [10, 20],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
        "common_method": {"engine": "mathematical_fixture", "method_set": "mode_fixture"},
    }


def _born(*, tensors: list[list[list[float]]] | None = None) -> dict:
    if tensors is None:
        tensors = [
            [[1.0, 0.2, 0.0], [0.2, 0.7, 0.1], [0.3, 0.0, 0.5]],
            [[0.4, -0.1, 0.0], [0.5, 0.3, 0.2], [0.1, 0.0, 0.2]],
        ]
    return {
        "schema": "mlcc.born-charge-columns.v1",
        "context": _context(),
        "unit": "e",
        "full_born_tensors_e": tensors,
        "source": {"record": "born.json"},
        "source_refs": ["born.json"],
        "sources": [{"response_id": "fixture-born"}],
        "native_jobs": [{"scheduler_job_id": "born-job"}],
        "status": "complete",
        "unresolved_reasons": [],
        "production_qualified": False,
        "qualification": {"fixture": True},
        "response_scope": {"scope": "born"},
    }


def _gamma(
    eigenvalues: tuple[float, float, float] = (2.0, 3.0, 4.0),
    vectors: list[list[float]] | None = None,
    mode_indices: tuple[int, int, int] = (0, 1, 2),
) -> dict:
    translations = np.tile(np.eye(3), (2, 1)) / np.sqrt(2.0)
    if vectors is None:
        vectors = [
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        ]
    optical = [
        {
            "mode_index": mode_indices[index],
            "eigenvalue_eV_per_A2_per_amu": eigenvalues[index],
            "frequency_cm1": 100.0 + 10.0 * index,
            "signed_frequency_cm1": 100.0 + 10.0 * index,
            "frequency_magnitude_cm1": 100.0 + 10.0 * index,
            "translation_overlap": 0.0,
            "eigenvector": vectors[index],
        }
        for index in range(3)
    ]
    return {
        "schema": "mlcc.gamma-force-constants.v1",
        "parent": copy.deepcopy(_context()["parent"]),
        "atom_ids": [10, 20],
        "elements": ["A", "B"],
        "cell_angstrom": copy.deepcopy(_context()["cell_angstrom"]),
        "volume_A3": 64.0,
        "matrix_basis": "parent_atom_major_cartesian",
        "unit": "eV/angstrom^2",
        "nac": "not_applied",
        "method_identity": copy.deepcopy(_context()["common_method"]),
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "status": "complete",
        "unresolved_reasons": [],
        "source": {"record": "gamma.json"},
        "source_refs": ["gamma.json"],
        "native_jobs": [{"scheduler_job_id": "gamma-job"}],
        "import_execution": {"runner": "slurm", "scheduler_job_id": "gamma-import"},
        "production_qualified": False,
        "qualification": {"fixture": True},
        "response_scope": {"scope": "gamma"},
        "explicit_processing": {
            "schema": "mlcc.gamma-explicit-processing.v1",
            "operation": "saved_fixture_optical_modes",
            "unit": "eV/angstrom^2",
            "matrix_basis": "parent_atom_major_cartesian",
            "atom_count": 2,
            "masses_amu": [1.0, 4.0],
            "translation_basis": translations.tolist(),
            "spectra": {"optical": optical},
        },
        "mass_mapping": {
            "atom_ids": [10, 20],
            "elements": ["A", "B"],
            "masses_amu": [1.0, 4.0],
        },
    }


def _ionic(delta: list[list[float]] | None, *, status: str = "complete", reasons=None) -> dict:
    return {
        "schema": "mlcc.ionic-dielectric-response.v1",
        "context": _context(),
        "unit": "dimensionless",
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "delta_epsilon_ionic": delta,
        "status": status,
        "unresolved_reasons": [] if reasons is None else reasons,
        "source": {"record": "ionic.json"},
        "source_refs": ["ionic.json"],
        "native_jobs": [{"scheduler_job_id": "ionic-job"}],
        "response_scope": {"scope": "ionic"},
    }


def _unresolved_ionic() -> dict:
    return _ionic(None, status="unresolved", reasons=["gamma_force_constants_missing"])


def test_unequal_masses_and_non_neutral_born_use_translation_free_gauge() -> None:
    result = calculate_dielectric_modes(
        _born(), _gamma(), _unresolved_ionic(), displacement_gauge="euclidean_translation_free"
    )
    mode = result["modes"][0]
    np.testing.assert_allclose(mode["u_raw_amu_minus_half"], [1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    np.testing.assert_allclose(
        mode["u_gauge_amu_minus_half"], [0.5, 0.0, 0.0, -0.5, 0.0, 0.0]
    )
    assert mode["raw_born_coupling_e_per_sqrt_amu"] != mode[
        "gauge_born_coupling_e_per_sqrt_amu"
    ]
    np.testing.assert_allclose(
        result["raw_born_sum_rule_residual_e"],
        np.asarray(_born()["full_born_tensors_e"]).sum(axis=0),
    )
    assert result["status"] == "unresolved"


def test_direction_sign_and_dielectric_scale_are_preserved() -> None:
    gamma = _gamma(eigenvalues=(2.0, 3.0, 4.0))
    provisional = calculate_dielectric_modes(
        _born(), gamma, _unresolved_ionic(), displacement_gauge="euclidean_translation_free"
    )
    expected = np.zeros((3, 3), dtype=float)
    scale = elementary_charge * 1.0e10 / (epsilon_0 * 64.0)
    for mode in provisional["modes"]:
        expected += scale * np.asarray(mode["strength_e2_per_amu"]) / mode[
            "eigenvalue_eV_per_A2_per_amu"
        ]
    result = calculate_dielectric_modes(
        _born(), gamma, _ionic(expected.tolist()), displacement_gauge="euclidean_translation_free"
    )
    assert result["status"] == "complete"
    assert result["closure"]["matches"] is True
    np.testing.assert_allclose(result["total_delta_epsilon_ionic"], expected)
    assert result["modes"][0]["strength_e2_per_amu"][0][1] < 0.0


def test_saved_lambda_not_reconstructed_from_frequency() -> None:
    gamma = _gamma()
    provisional = calculate_dielectric_modes(
        _born(), gamma, _unresolved_ionic(), displacement_gauge="euclidean_translation_free"
    )
    expected = np.zeros((3, 3), dtype=float)
    scale = elementary_charge * 1.0e10 / (epsilon_0 * 64.0)
    for mode in provisional["modes"]:
        expected += scale * np.asarray(mode["strength_e2_per_amu"]) / mode[
            "eigenvalue_eV_per_A2_per_amu"
        ]
    changed = copy.deepcopy(gamma)
    for index, mode in enumerate(changed["explicit_processing"]["spectra"]["optical"]):
        mode["frequency_cm1"] = -700.0 - index
        mode["signed_frequency_cm1"] = -700.0 - index
        mode["frequency_magnitude_cm1"] = 700.0 + index
    first = calculate_dielectric_modes(
        _born(), gamma, _ionic(expected.tolist()), displacement_gauge="euclidean_translation_free"
    )
    second = calculate_dielectric_modes(
        _born(), changed, _ionic(expected.tolist()), displacement_gauge="euclidean_translation_free"
    )
    np.testing.assert_allclose(first["total_delta_epsilon_ionic"], second["total_delta_epsilon_ionic"])
    for left, right in zip(first["modes"], second["modes"]):
        assert left["eigenvalue_eV_per_A2_per_amu"] == right["eigenvalue_eV_per_A2_per_amu"]
        assert left["frequency_cm1"] != right["frequency_cm1"]
        np.testing.assert_allclose(left["delta_epsilon_ionic"], right["delta_epsilon_ionic"])


def test_product_labels_and_original_source_fields_are_retained() -> None:
    result = calculate_dielectric_modes(
        _born(), _gamma(), _unresolved_ionic(), displacement_gauge="euclidean_translation_free"
    )
    assert result["field_units"]["eigenvalue"] == "eV/(angstrom^2*amu)"
    assert "frequency_cm1^2" not in result["field_units"]["eigenvalue"]
    assert "saved Gamma eigenvalue" in result["mode_semantics"]["eigenvalue"]
    assert "diagnostic_only" in result["mode_semantics"]["raw_born_coupling"]
    assert "degenerate basis" in result["mode_semantics"]["degenerate_modes"]
    assert result["modes"][0]["lambda_source"] == "eigenvalue_eV_per_A2_per_amu"
    assert "saved_mass_weighted_gamma_basis" in result["modes"][0]["mode_response_semantics"]
    assert result["sources"]["born"]["sources"] == [{"response_id": "fixture-born"}]
    assert result["sources"]["gamma"]["import_execution"]["scheduler_job_id"] == "gamma-import"
    assert result["sources"]["gamma"]["qualification"] == {"fixture": True}
    assert result["mass_mapping"]["elements"] == ["A", "B"]
    assert result["response_scope"] == {"scope": "gamma"}
    assert result["source_response_scopes"] == {
        "born": {"scope": "born"},
        "gamma": {"scope": "gamma"},
        "ionic": {"scope": "ionic"},
    }
    assert "qualification" not in result


def test_degenerate_saved_basis_is_not_rotated_or_reordered() -> None:
    base_vectors = _gamma()["explicit_processing"]["spectra"]["optical"]
    vectors = [item["eigenvector"] for item in base_vectors]
    rotated = copy.deepcopy(vectors)
    rotated[0] = ((np.asarray(vectors[0]) + np.asarray(vectors[1])) / np.sqrt(2.0)).tolist()
    rotated[1] = ((np.asarray(vectors[0]) - np.asarray(vectors[1])) / np.sqrt(2.0)).tolist()
    first = calculate_dielectric_modes(
        _born(),
        _gamma(eigenvalues=(2.0, 2.0, 4.0), mode_indices=(7, 3, 11)),
        _unresolved_ionic(),
        displacement_gauge="euclidean_translation_free",
    )
    second = calculate_dielectric_modes(
        _born(),
        _gamma(eigenvalues=(2.0, 2.0, 4.0), vectors=rotated, mode_indices=(9, 4, 12)),
        _unresolved_ionic(),
        displacement_gauge="euclidean_translation_free",
    )
    assert [mode["mode_index"] for mode in first["modes"]] == [7, 3, 11]
    assert [mode["mode_index"] for mode in second["modes"]] == [9, 4, 12]
    first_sum = sum(
        (
            np.asarray(mode["strength_e2_per_amu"])
            / mode["eigenvalue_eV_per_A2_per_amu"]
            for mode in first["modes"]
        ),
        np.zeros((3, 3)),
    )
    second_sum = sum(
        (
            np.asarray(mode["strength_e2_per_amu"])
            / mode["eigenvalue_eV_per_A2_per_amu"]
            for mode in second["modes"]
        ),
        np.zeros((3, 3)),
    )
    np.testing.assert_allclose(first_sum, second_sum)


def test_nonpositive_optical_mode_keeps_couplings_but_nulls_all_deltas() -> None:
    result = calculate_dielectric_modes(
        _born(),
        _gamma(eigenvalues=(0.0, 3.0, -1.0)),
        _ionic(np.eye(3).tolist()),
        displacement_gauge="euclidean_translation_free",
    )
    assert result["total_delta_epsilon_ionic"] is None
    assert "optical_space_not_positive_definite" in result["unresolved_reasons"]
    assert all(mode["delta_epsilon_ionic"] is None for mode in result["modes"])
    assert all(
        mode["gauge_born_coupling_e_per_sqrt_amu"] is not None for mode in result["modes"]
    )


def test_born_or_ionic_unresolved_is_not_bypassed() -> None:
    born = _born()
    born["full_born_tensors_e"] = None
    result = calculate_dielectric_modes(
        born, _gamma(), _unresolved_ionic(), displacement_gauge="euclidean_translation_free"
    )
    assert result["total_delta_epsilon_ionic"] is None
    assert "born_tensor_incomplete" in result["unresolved_reasons"]
    assert all(mode["strength_e2_per_amu"] is None for mode in result["modes"])
    born = _born()
    born["status"] = "unresolved"
    result = calculate_dielectric_modes(
        born, _gamma(), _ionic(np.eye(3).tolist()), displacement_gauge="euclidean_translation_free"
    )
    assert "born_tensor_unresolved" in result["unresolved_reasons"]
    assert result["total_delta_epsilon_ionic"] is None
    assert all(mode["delta_epsilon_ionic"] is None for mode in result["modes"])
    assert all(mode["strength_e2_per_amu"] is not None for mode in result["modes"])


def test_saved_eigenpairs_are_used_without_eigh_or_solve(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("mode response must not diagonalize or solve")

    monkeypatch.setattr(np.linalg, "eigh", forbidden)
    monkeypatch.setattr(np.linalg, "solve", forbidden)
    result = calculate_dielectric_modes(
        _born(), _gamma(), _unresolved_ionic(), displacement_gauge="euclidean_translation_free"
    )
    assert len(result["modes"]) == 3
    json.dumps(result)


def test_context_mismatch_is_rejected() -> None:
    ionic = _ionic(None, status="unresolved", reasons=["missing"])
    ionic["context"]["parent"]["study_id"] = "other-study"
    with pytest.raises(ValueError, match="context differs from Born context"):
        calculate_dielectric_modes(
            _born(), _gamma(), ionic, displacement_gauge="euclidean_translation_free"
        )
