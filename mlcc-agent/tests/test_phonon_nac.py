"""Focused directional-NAC checks against the saved job197 fixture.

The fixture is an existing source-bound artifact. These tests do not create a
new displacement set or run DFT/MD. ``MLCC_NAC_FIXTURE`` may point at an
equivalent evidence directory on v100; absence is an error, not a skip.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from phonopy import Phonopy

import mlcc.phonon_nac as phonon_nac
from mlcc.phonon_nac import NAC_SCHEMA, compute_gamma_directional_nac


DEFAULT_FIXTURE_ROOT = Path(
    "/home/v100/projects/mlcc/reports/p5-v017-integration-v001/installed-197/software-math-positive"
)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"fixture file must contain an object: {path}")
    return value


def _request(case: dict[str, Any], direction: list[float] | None = None) -> dict[str, Any]:
    request = copy.deepcopy(case["request"])
    request.update(
        {
            "nac_method": "wang",
            "direction_basis": "primitive_reciprocal_fractional",
            "nac_q_direction": [1.0, 0.0, 0.0] if direction is None else direction,
            "dynamical_hermitian_tolerance": 1e-12,
        }
    )
    return request


def _compute(case: dict[str, Any], *, direction: list[float] | None = None) -> dict[str, Any]:
    root = case["root"]
    return compute_gamma_directional_nac(
        _request(case, direction),
        copy.deepcopy(case["born"]),
        copy.deepcopy(case["electronic"]),
        born_path=root / "born.json",
        electronic_path=root / "electronic.json",
    )


@pytest.fixture(scope="module")
def case() -> dict[str, Any]:
    root = Path(os.environ.get("MLCC_NAC_FIXTURE", str(DEFAULT_FIXTURE_ROOT)))
    if not root.is_dir():
        raise AssertionError(f"saved job197 fixture is unavailable: {root}")
    fixture = {
        "root": root,
        "request": _json(root / "phonon-gamma-request.json"),
        "born": _json(root / "born.json"),
        "electronic": _json(root / "electronic.json"),
        "gamma": _json(root / "gamma.json"),
    }
    low_level_calls: list[dict[str, Any]] = []
    run_qpoints_calls: list[dict[str, Any]] = []
    low_level = phonon_nac.get_dynamical_matrices_at_qpoints

    def spy(*args: Any, **kwargs: Any) -> Any:
        low_level_calls.append(dict(kwargs))
        return low_level(*args, **kwargs)

    def forbidden_run_qpoints(*args: Any, **kwargs: Any) -> Any:
        run_qpoints_calls.append(dict(kwargs))
        raise AssertionError("directional NAC must use the explicit low-level q-point API")

    with patch.object(phonon_nac, "get_dynamical_matrices_at_qpoints", side_effect=spy):
        with patch.object(Phonopy, "run_qpoints", side_effect=forbidden_run_qpoints):
            fixture["result"] = _compute(fixture)
            fixture["scaled"] = _compute(fixture, direction=[2.0, 0.0, 0.0])
    fixture["low_level_calls"] = low_level_calls
    fixture["run_qpoints_calls"] = run_qpoints_calls
    result_path = os.environ.get("MLCC_NAC_RESULT")
    if result_path:
        output = Path(result_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(fixture["result"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = fixture["result"]
        scaled = fixture["scaled"]
        cell = np.asarray(result["cell_angstrom"], dtype=float)
        volume = float(result["volume_A3"])
        direction = np.asarray(result["nac_q_direction_normalized"], dtype=float)
        q_cart = direction @ np.linalg.inv(cell).T
        born = np.asarray(fixture["born"]["full_born_tensors_e"], dtype=float)
        epsilon = np.asarray(fixture["electronic"]["tensor"], dtype=float)
        factor = float(result["nac_unit_conversion"]["nac_factor"])
        constant = factor * 4.0 * np.pi / volume / float(q_cart @ epsilon @ q_cart)
        charge_sum = np.einsum("k,ikj->ij", q_cart, born)
        correction_force = constant * np.einsum("ia,jb->iajb", charge_sum, charge_sum)
        masses = np.asarray(result["masses_amu"], dtype=float)
        mass_scale = np.sqrt(np.outer(np.repeat(masses, 3), np.repeat(masses, 3)))
        expected_correction = correction_force.reshape(6, 6) / mass_scale
        correction = np.asarray(result["correction"]["dynamical_matrix"], dtype=float)
        baseline = np.asarray(result["baseline"]["dynamical_matrix"], dtype=float)
        saved_gamma = np.asarray(fixture["gamma"]["matrix_eV_per_A2"], dtype=float)
        baseline_hessian = baseline * mass_scale
        correction_blocks = correction.reshape(2, 3, 2, 3)
        transverse = np.concatenate(
            (correction_blocks[:, 1:, :, :].ravel(), correction_blocks[:, :, :, 1:].ravel())
        )
        metrics = {
            "schema": "mlcc.phonon-gamma-nac.numeric-checks.v1",
            "analytic_correction_max_abs_diff": float(np.max(np.abs(correction - expected_correction))),
            "saved_gamma_baseline_max_abs_diff": float(np.max(np.abs(baseline_hessian - saved_gamma))),
            "transverse_max_abs": float(np.max(np.abs(transverse))),
            "nac_factor_eV_angstrom": factor,
            "correction_rank": int(np.linalg.matrix_rank(correction, tol=1e-10)),
            "direction_scaled_max_abs_diff": float(
                np.max(
                    np.abs(
                        np.asarray(result["corrected"]["dynamical_matrix"], dtype=float)
                        - np.asarray(scaled["corrected"]["dynamical_matrix"], dtype=float)
                    )
                )
            ),
        }
        output.with_name("numerical-checks.json").write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return fixture


def test_saved_197_uses_explicit_unhermitianized_low_level_path(case: dict[str, Any]):
    assert case["run_qpoints_calls"] == []
    calls = case["low_level_calls"]
    assert len(calls) == 4
    assert all(call["hermitianize"] is False for call in calls)
    assert all(call["lang"] == "Rust" for call in calls)
    assert calls[0]["nac_q_direction"] is None
    assert calls[1]["nac_q_direction"] == [1.0, 0.0, 0.0]
    assert calls[2]["nac_q_direction"] is None
    assert calls[3]["nac_q_direction"] == [1.0, 0.0, 0.0]


def test_saved_197_directional_nac_schema_and_unqualified_status(case: dict[str, Any]):
    result = case["result"]

    assert result["schema"] == NAC_SCHEMA
    assert result["source_mode"] == "software_math_only"
    assert result["nac_method"] == "wang"
    assert result["direction_basis"] == "primitive_reciprocal_fractional"
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False
    assert result["baseline"]["nac"] == "not_applied"
    assert result["corrected"]["nac"] == "wang"
    assert result["masses_amu"] == [11.0, 23.0]
    baseline = np.asarray(result["baseline"]["dynamical_matrix"], dtype=float)
    corrected = np.asarray(result["corrected"]["dynamical_matrix"], dtype=float)
    correction = np.asarray(result["correction"]["dynamical_matrix"], dtype=float)
    assert baseline.shape == corrected.shape == correction.shape == (6, 6)
    np.testing.assert_allclose(corrected - baseline, correction, rtol=0.0, atol=1e-12)
    assert result["dynamical_matrix_unit"] == "eV/angstrom^2/amu"
    assert result["imaginary_frequencies_preserved"] is True


def test_saved_197_baseline_matches_saved_gamma_hessian(case: dict[str, Any]):
    result = case["result"]
    gamma = case["gamma"]
    masses = np.asarray(result["masses_amu"], dtype=float)
    dynamical = np.asarray(result["baseline"]["dynamical_matrix"], dtype=float)
    hessian = dynamical * np.sqrt(np.outer(np.repeat(masses, 3), np.repeat(masses, 3)))
    np.testing.assert_allclose(hessian, np.asarray(gamma["matrix_eV_per_A2"], dtype=float), rtol=0.0, atol=1e-10)


def test_saved_197_wang_correction_is_longitudinal_rank_one(case: dict[str, Any]):
    correction = np.asarray(case["result"]["correction"]["dynamical_matrix"], dtype=float)

    assert np.linalg.matrix_rank(correction, tol=1e-10) <= 1
    blocks = correction.reshape(2, 3, 2, 3)
    np.testing.assert_allclose(blocks[:, 1:, :, :], 0.0, rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(blocks[:, :, :, 1:], 0.0, rtol=0.0, atol=1e-10)
    assert np.max(np.abs(blocks[:, 0, :, 0])) > 0.0


def test_saved_197_wang_correction_matches_unit_and_mass_scaled_rank_one_term(case: dict[str, Any]):
    result = case["result"]
    cell = np.asarray(result["cell_angstrom"], dtype=float)
    volume = float(result["volume_A3"])
    direction = np.asarray(result["nac_q_direction_normalized"], dtype=float)
    q_cart = direction @ np.linalg.inv(cell).T
    born = np.asarray(case["born"]["full_born_tensors_e"], dtype=float)
    epsilon = np.asarray(case["electronic"]["tensor"], dtype=float)
    factor = float(result["nac_unit_conversion"]["nac_factor"])
    constant = factor * 4.0 * np.pi / volume / float(q_cart @ epsilon @ q_cart)
    charge_sum = np.einsum("k,ikj->ij", q_cart, born)
    correction_force = constant * np.einsum("ia,jb->iajb", charge_sum, charge_sum)
    masses = np.asarray(result["masses_amu"], dtype=float)
    mass_scale = np.sqrt(np.outer(np.repeat(masses, 3), np.repeat(masses, 3)))
    expected = correction_force.reshape(6, 6) / mass_scale

    np.testing.assert_allclose(
        np.asarray(result["correction"]["dynamical_matrix"], dtype=float),
        expected,
        rtol=0.0,
        atol=1e-10,
    )
    assert factor == pytest.approx(14.399652, rel=0.0, abs=2e-5)
    assert result["nac_unit_conversion"]["nac_factor_unit"] == "eV*angstrom"


def test_saved_197_direction_scaling_leaves_wang_correction_unchanged(case: dict[str, Any]):
    scaled = case["scaled"]

    np.testing.assert_allclose(
        np.asarray(case["result"]["corrected"]["dynamical_matrix"], dtype=float),
        np.asarray(scaled["corrected"]["dynamical_matrix"], dtype=float),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        np.asarray(case["result"]["corrected"]["frequencies_THz"], dtype=float),
        np.asarray(scaled["corrected"]["frequencies_THz"], dtype=float),
        rtol=0.0,
        atol=1e-12,
    )
    assert scaled["nac_q_direction"] == [2.0, 0.0, 0.0]
    assert scaled["nac_q_direction_normalized"] == [1.0, 0.0, 0.0]


def test_direction_and_method_are_explicit(case: dict[str, Any]):
    zero = _request(case, [0.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="must be non-zero"):
        compute_gamma_directional_nac(
            zero,
            case["born"],
            case["electronic"],
            born_path=case["root"] / "born.json",
            electronic_path=case["root"] / "electronic.json",
        )
    wrong_method = _request(case)
    wrong_method["nac_method"] = "gonze"
    with pytest.raises(ValueError, match="exactly 'wang'"):
        compute_gamma_directional_nac(
            wrong_method,
            case["born"],
            case["electronic"],
            born_path=case["root"] / "born.json",
            electronic_path=case["root"] / "electronic.json",
        )


def test_input_mapping_and_born_atom_order_are_bound(case: dict[str, Any], tmp_path: Path):
    incomplete = copy.deepcopy(case["born"])
    incomplete["full_born_tensors_e"] = None
    incomplete["missing_columns"] = [{"atom_id": 101, "cartesian_axis": 0}]
    incomplete_path = tmp_path / "born-incomplete.json"
    incomplete_path.write_text(json.dumps(incomplete), encoding="utf-8")
    with pytest.raises(ValueError, match="full_born_tensors_e"):
        compute_gamma_directional_nac(
            _request(case),
            incomplete,
            case["electronic"],
            born_path=incomplete_path,
            electronic_path=case["root"] / "electronic.json",
        )

    wrong_order = copy.deepcopy(case["born"])
    wrong_order["atom_ids"] = [205, 101]
    wrong_order_path = tmp_path / "born-wrong-order.json"
    wrong_order_path.write_text(json.dumps(wrong_order), encoding="utf-8")
    with pytest.raises(ValueError, match="atom_ids"):
        compute_gamma_directional_nac(
            _request(case),
            wrong_order,
            case["electronic"],
            born_path=wrong_order_path,
            electronic_path=case["root"] / "electronic.json",
        )


def test_non_positive_epsilon_is_rejected_with_bound_file(case: dict[str, Any], tmp_path: Path):
    electronic = copy.deepcopy(case["electronic"])
    electronic["tensor"] = [[-2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]]
    electronic_path = tmp_path / "electronic.json"
    electronic_path.write_text(json.dumps(electronic), encoding="utf-8")
    with pytest.raises(ValueError, match="positive definite"):
        compute_gamma_directional_nac(
            _request(case),
            case["born"],
            electronic,
            born_path=case["root"] / "born.json",
            electronic_path=electronic_path,
        )
