import json

import numpy as np
import pytest
from scipy.constants import atomic_mass, elementary_charge, speed_of_light

from mlcc.gamma_processing import SCHEMA, optical_response_sensitivity, process_gamma_matrix


def _asymmetric_fixture() -> tuple[np.ndarray, list[float]]:
    matrix = np.diag(np.arange(1.0, 7.0))
    matrix[0, 3] = 2.0
    matrix[3, 0] = -3.0
    matrix[1, 4] = 0.25
    return matrix, [1.0, 4.0]


def _translation_invariant_fixture(kx: float = -0.5) -> tuple[np.ndarray, list[float]]:
    matrix = np.zeros((6, 6), dtype=float)
    for axis, spring in enumerate((kx, 1.0, 2.0)):
        indices = [axis, 3 + axis]
        matrix[np.ix_(indices, indices)] = ((spring, -spring), (-spring, spring))
    return matrix, [1.0, 2.0]


def test_schema_is_json_safe_and_keeps_the_native_raw_matrix() -> None:
    matrix, masses = _asymmetric_fixture()
    original = matrix.copy()

    result = process_gamma_matrix(matrix, masses)

    assert result["schema"] == SCHEMA
    assert result["unit"] == "eV/angstrom^2"
    assert result["qualifications"] is False
    assert np.array_equal(np.asarray(result["matrices"]["raw"]), original)
    # No numpy complex objects may escape into the persisted product.
    json.dumps(result)


def test_raw_spectrum_uses_general_eig_and_preserves_complex_modes() -> None:
    matrix, masses = _asymmetric_fixture()

    result = process_gamma_matrix(matrix, masses)

    raw_modes = result["spectra"]["raw"]
    assert result["diagnostics"]["raw_spectrum_solver"] == "numpy.linalg.eig_general_complex"
    assert any(mode["eigenvalue_eV_per_A2_per_amu"]["imag"] != 0.0 for mode in raw_modes)
    complex_mode = next(
        mode for mode in raw_modes if mode["eigenvalue_eV_per_A2_per_amu"]["imag"] != 0.0
    )
    assert complex_mode["signed_frequency_cm1"] is None
    assert set(complex_mode["frequency_cm1"]) == {"real", "imag"}
    assert len(result["diagnostics"]["raw_acoustic_diagnostic_mode_indices"]) == 3


def test_mass_weighted_translation_basis_and_recorded_constants() -> None:
    matrix, masses = _asymmetric_fixture()

    result = process_gamma_matrix(matrix, masses)

    q_mass = np.asarray(result["translation_basis_mass_weighted"], dtype=float)
    assert np.allclose(q_mass.T @ q_mass, np.eye(3))
    assert result["operation"] == "reciprocity_average_then_exact_three_translation_projection"
    assert result["masses_amu"] == masses
    constants = result["constants"]
    assert constants["elementary_charge_C"] == elementary_charge
    assert constants["atomic_mass_kg"] == atomic_mass
    assert constants["speed_of_light_m_per_s"] == speed_of_light
    assert constants["angstrom_m"] == 1.0e-10
    assert constants["frequency_conversion_cm1_per_sqrt_eV_per_A2_per_amu"] > 0.0


def test_explicit_symmetrization_and_projection_report_each_correction() -> None:
    matrix, masses = _asymmetric_fixture()

    result = process_gamma_matrix(matrix, masses)
    matrices = {key: np.asarray(value) for key, value in result["matrices"].items()}
    corrections = result["diagnostics"]["corrections"]

    assert np.allclose(matrices["symmetric"], (matrix + matrix.T) / 2.0)
    assert np.allclose(matrices["projected"], matrices["projected"].T)
    assert corrections["raw_to_symmetric"]["max_abs_eV_per_A2"] == pytest.approx(2.5)
    assert corrections["raw_to_symmetric"]["frobenius_eV_per_A2"] > 0.0
    assert corrections["symmetric_to_projected"]["frobenius_eV_per_A2"] > 0.0
    reciprocity = result["diagnostics"]["reciprocity"]
    assert reciprocity["raw"]["absolute_max_eV_per_A2"] > 0.0
    assert reciprocity["symmetric"]["absolute_max_eV_per_A2"] == pytest.approx(0.0)


def test_left_right_translation_residuals_keep_normalized_and_sum_rule_views() -> None:
    matrix, masses = _translation_invariant_fixture()

    result = process_gamma_matrix(matrix, masses)
    residuals = result["diagnostics"]["translation_residuals"]

    for name in ("raw", "symmetric", "projected"):
        assert set(residuals[name]) == {"normalized", "sum_rule"}
        assert residuals[name]["normalized"]["left"]["max_abs_eV_per_A2"] < 1.0e-14
        assert residuals[name]["normalized"]["right"]["max_abs_eV_per_A2"] < 1.0e-14
        assert residuals[name]["sum_rule"]["left"]["frobenius_eV_per_A2"] < 1.0e-13
        assert residuals[name]["sum_rule"]["right"]["frobenius_eV_per_A2"] < 1.0e-13


def test_optical_complement_removes_only_three_translations_and_keeps_negative_soft_modes() -> None:
    matrix, masses = _translation_invariant_fixture(kx=-0.5)

    result = process_gamma_matrix(matrix, masses)
    optical = result["spectra"]["optical"]
    projected = result["spectra"]["projected"]

    assert len(optical) == 3
    assert len(projected) == 6
    assert any(mode["signed_frequency_cm1"] < -5.0 for mode in optical)
    assert "projected_optical_negative_frequency_over_5_cm1" in result["warnings"]
    assert all(mode["translation_overlap"] < 1.0e-12 for mode in optical)


def test_near_zero_optical_mode_is_retained_without_clipping() -> None:
    matrix, masses = _translation_invariant_fixture(kx=1.0e-14)

    result = process_gamma_matrix(matrix, masses)

    optical_frequencies = [abs(mode["frequency_cm1"]) for mode in result["spectra"]["optical"]]
    assert len(optical_frequencies) == 3
    assert any(frequency < 1.0 for frequency in optical_frequencies)
    assert result["qualifications"] is False


def test_two_atom_spring_frequency_matches_mass_weighted_analytic_value() -> None:
    matrix, masses = _translation_invariant_fixture(kx=0.5)

    result = process_gamma_matrix(matrix, masses)
    factor = result["constants"]["frequency_conversion_cm1_per_sqrt_eV_per_A2_per_amu"]
    expected = factor * np.sqrt(0.75)  # k*(1/m1 + 1/m2) = .5*(1 + .5)

    assert any(
        mode["eigenvalue_eV_per_A2_per_amu"] == pytest.approx(0.75)
        and mode["frequency_cm1"] == pytest.approx(expected)
        for mode in result["spectra"]["optical"]
    )


def test_optical_response_sensitivity_compares_three_explicit_matrices() -> None:
    matrix, masses = _translation_invariant_fixture(kx=0.5)
    processing = process_gamma_matrix(matrix, masses)
    born = np.arange(18.0, dtype=float).reshape(3, 6) / 10.0

    result = optical_response_sensitivity(born, processing, volume_A3=120.0)

    assert result["schema"] == "mlcc.gamma-optical-response-sensitivity.v1"
    assert result["status"] == "complete"
    assert all(item["status"] == "complete" for item in result["responses"].values())
    assert result["comparisons"]["raw_vs_symmetric"] is not None
    assert result["comparisons"]["raw_vs_projected"] is not None
    assert all(value is not None for value in result["optical_block_condition_numbers"].values())
    json.dumps(result)


def test_optical_response_sensitivity_keeps_unstable_reciprocal_block_unresolved() -> None:
    matrix, masses = _translation_invariant_fixture(kx=-0.5)
    processing = process_gamma_matrix(matrix, masses)
    born = np.ones((3, 6), dtype=float)

    result = optical_response_sensitivity(born, processing, volume_A3=120.0)

    assert result["status"] == "unresolved"
    assert result["responses"] == {"raw": None, "symmetric": None, "projected": None}
    assert result["unresolved_reasons"] == ["symmetric_optical_block_not_positive_definite"]
    assert result["qualifications"] is False


def test_invalid_shapes_and_nonpositive_masses_are_rejected() -> None:
    with pytest.raises(ValueError, match="square"):
        process_gamma_matrix(np.zeros((3, 2)), [1.0])
    with pytest.raises(ValueError, match="multiple of 3"):
        process_gamma_matrix(np.zeros((4, 4)), [1.0])
    with pytest.raises(ValueError, match="positive"):
        process_gamma_matrix(np.zeros((3, 3)), [0.0])
    with pytest.raises(ValueError, match="finite"):
        process_gamma_matrix(np.full((3, 3), np.nan), [1.0])


def test_derived_local_scope_and_sensitivity_reach_ionic_and_total():
    from test_ionic_unresolved_gamma import _born, _gamma, _thresholds, _electronic
    from mlcc.dielectric_response import calculate_ionic_dielectric, combine_dielectric_contributions
    from mlcc.property_delivery import _p5_validate_ionic, _p5_validate_dielectric, _p5_tensor_observables

    born, gamma = _born(), _gamma()
    processing = process_gamma_matrix(gamma["matrix_eV_per_A2"], [1.0, 2.0])
    gamma.update(status="complete", unresolved_reasons=[], explicit_processing=processing,
                 matrix_eV_per_A2=processing["matrices"]["projected"],
                 response_scope={"response": "specified_geometry_local_fixed_cell_zero_macroscopic_electric_field",
                                 "equilibrium_reference": False,
                                 "reference_max_abs_force_eV_per_A": 0.1179010327})
    gamma["source"]["native_gamma_processing_request"] = "math://explicit-processing"
    ionic = calculate_ionic_dielectric(born, gamma, thresholds=_thresholds())
    total = combine_dielectric_contributions(born, _electronic(), ionic)
    assert ionic["delta_epsilon_ionic"] is not None
    assert ionic["processing_sensitivity"]["status"] == "complete"
    assert total["response_scope"] == gamma["response_scope"]
    assert total["production_qualification"] is False
    observables = _p5_tensor_observables("ionic", ionic, born["context"], ["math://explicit"], True)
    assert all(item["conditions"]["response_scope"] == gamma["response_scope"] for item in observables)
    _p5_validate_ionic(ionic, born, gamma)
    changed = dict(ionic, response_scope={"equilibrium_reference": True})
    with pytest.raises(ValueError, match="scope"):
        _p5_validate_ionic(changed, born, gamma)
    changed_total = dict(total, response_scope={"equilibrium_reference": True})
    with pytest.raises(ValueError, match="scope"):
        _p5_validate_dielectric(changed_total, total, _electronic(), ionic)


def test_new_derived_path_keeps_missing_born_null_without_sensitivity_solver(monkeypatch):
    from test_ionic_unresolved_gamma import _born, _gamma, _thresholds
    from mlcc.dielectric_response import calculate_ionic_dielectric
    import mlcc.gamma_processing as domain

    gamma = _gamma()
    gamma.update(explicit_processing={"operation": "explicit", "warnings": []},
                 response_scope={"equilibrium_reference": False})
    gamma["source"]["native_gamma_processing_request"] = "math://unresolved"
    def forbidden(*args, **kwargs):
        raise AssertionError("missing Born cannot produce response sensitivity")
    monkeypatch.setattr(domain, "optical_response_sensitivity", forbidden)
    result = calculate_ionic_dielectric(_born(unresolved=True), gamma, thresholds=_thresholds())
    assert result["delta_epsilon_ionic"] is None
    assert result["processing_sensitivity"]["status"] == "unresolved"
    assert result["response_scope"]["equilibrium_reference"] is False
