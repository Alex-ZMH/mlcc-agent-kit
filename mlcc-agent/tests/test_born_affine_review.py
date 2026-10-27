"""Software/math-only checks for reviewed native Born affine branches."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.constants import elementary_charge, epsilon_0

import mlcc.born_affine as born_affine
from mlcc.born_affine import consume_native_born_review, evaluate_born_affine, resolve_born_affine_family
from mlcc.dielectric_response import calculate_ionic_dielectric, combine_dielectric_contributions
from mlcc.property_delivery import _p5_declared_mode, _p5_native_born


def test_reviewed_affine_born_to_ionic_and_total_matches_analytic_math_case(tmp_path):
    family, born, review_path, review, _ = _review_case(tmp_path)
    method = {"engine": "mathematical_fixture", "method_set": "affine-spring-math"}
    born["common_method"] = method
    born["context"]["common_method"] = method
    affine = born["raw_product"]["affine_family"]
    affine["base_tensor_e"][1] = (-np.asarray(affine["base_tensor_e"][0])).tolist()
    for coefficient in affine["coefficient_tensors_e"]:
        coefficient[1] = (-np.asarray(coefficient[0])).tolist()
    _write(family, born["raw_product"])
    review["context"] = copy.deepcopy(born["context"])
    _write(review_path, review)
    reviewed = resolve_born_affine_family(born, review, review_path=review_path)
    context = reviewed["context"]
    gamma = {
        "schema": "mlcc.gamma-force-constants.v1", "parent": context["parent"],
        "atom_ids": context["atom_ids"], "cell_angstrom": context["cell_angstrom"],
        "volume_A3": context["volume_A3"], "method_identity": method,
        "unit": "eV/angstrom^2", "matrix_basis": "parent_atom_major_cartesian",
        "matrix_eV_per_A2": (2.0 * np.block([[np.eye(3), -np.eye(3)], [-np.eye(3), np.eye(3)]])).tolist(),
        "electrical_boundary": "fixed_E_zero", "mechanical_boundary": "fixed_cell",
        "nac": "not_applied", "source": {"harmonic_result": "software_math_only:two_atom_spring"},
    }
    thresholds = {"symmetry_eV_per_A2": 1e-12, "translation_eV_per_A2": 1e-12,
                  "born_sum_e": 1e-12, "minimum_optical_eigenvalue_eV_per_A2": 1e-8}
    electronic = {
        "kind": "epsilon_infinity_relative", "parent": context["parent"],
        "atom_ids": context["atom_ids"], "cell_angstrom": context["cell_angstrom"],
        "volume_A3": context["volume_A3"], "method_identity": method,
        "electrical_boundary": "fixed_E_zero", "mechanical_boundary": "fixed_cell",
        "ions": "clamped", "unit": "dimensionless", "tensor": (2.0 * np.eye(3)).tolist(),
        "source_refs": ["software_math_only:epsilon_infinity_2"],
    }
    ionic = calculate_ionic_dielectric(reviewed, gamma, thresholds=thresholds)
    total = combine_dielectric_contributions(reviewed, electronic, ionic)
    expected_delta = elementary_charge * 1e10 / (epsilon_0 * 64.0) * (1.7 ** 2 / 2.0) * np.eye(3)
    np.testing.assert_allclose(ionic["delta_epsilon_ionic"], expected_delta, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(total["epsilon_static"], 2.0 * np.eye(3) + expected_delta, rtol=1e-12, atol=1e-12)
    assert total["status"] == "complete"
    assert total["scientific_qualification"] is False and total["production_qualification"] is False
    assert ionic["born_source"]["sources"] == reviewed["sources"]


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _math_case(tmp_path: Path) -> tuple[Path, dict, dict]:
    family_path = (tmp_path / "software-math-born-family.json").resolve()
    method = {
        "engine": "software_math_only",
        "engine_version": "contract",
        "method_set": "born-affine-software-math-only",
        "basis_type": "Cartesian",
    }
    context = {
        "parent": {
            "study_id": "software-math-study",
            "model_id": "software-math-model",
            "model_version": "v001",
            "model_path": str((tmp_path / "model").resolve()),
        },
        "common_method": copy.deepcopy(method),
        "atom_ids": [0, 1],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
    }
    affine = {
        "definition": "base_tensor_e + sum(n_i * coefficient_tensor_i_e)",
        "n_domain": "Z^3",
        "base_tensor_e": [
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]],
        ],
        "coefficient_tensors_e": [
            [
                [[0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.0, 0.1]],
                [[0.2, 0.0, 0.0], [0.0, 0.2, 0.0], [0.0, 0.0, 0.2]],
            ],
            [
                [[0.3, 0.0, 0.0], [0.0, 0.3, 0.0], [0.0, 0.0, 0.3]],
                [[0.4, 0.0, 0.0], [0.0, 0.4, 0.0], [0.0, 0.0, 0.4]],
            ],
            [
                [[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 0.5]],
                [[0.6, 0.0, 0.0], [0.0, 0.6, 0.0], [0.0, 0.0, 0.6]],
            ],
        ],
        "integer_labels": [
            {
                "label_index": 0,
                "atom_id": 0,
                "atom_index": 0,
                "direction": "x",
                "direction_index": 0,
                "polarization_lattice_axis": "a",
                "polarization_lattice_axis_index": 0,
            },
            {
                "label_index": 1,
                "atom_id": 0,
                "atom_index": 0,
                "direction": "x",
                "direction_index": 0,
                "polarization_lattice_axis": "b",
                "polarization_lattice_axis_index": 1,
            },
            {
                "label_index": 2, "atom_id": 0, "atom_index": 0,
                "direction": "x", "direction_index": 0,
                "polarization_lattice_axis": "c", "polarization_lattice_axis_index": 2,
            },
        ],
        "physical_branch_selected": False,
        "physical_born_tensor": None,
        "selection_policy": {
            "selected_branch_shift": None,
            "nearest_quantum_applied": False,
            "asr_projected": False,
        },
        "atom_ids_in_tensor_order": [0, 1],
        "atom_elements_in_tensor_order": ["Ca", "Zr"],
        "axes": {
            "tensor": ["atom", "polarization", "displacement"],
            "polarization": ["x", "y", "z"],
            "displacement": ["x", "y", "z"],
            "basis": "Cartesian",
        },
    }
    raw = {
        "schema": "mlcc.native-born-branch-family.v1",
        "status": "unresolved_physical_branch",
        "provenance_kind": "software_math_only",
        "unit": "e",
        "affine_family": affine,
        "atom_ids": [0],
        "source": {"family_path": str(family_path)},
    }
    _write(family_path, raw)
    born = {
        "schema": "mlcc.born-charge-columns.v1",
        "unit": "e",
        "context": context,
        "atom_ids": [0, 1],
        "common_method": copy.deepcopy(method),
        "provenance_kind": "software_math_only",
        "source_mode": "software_math_only",
        "source": {"native_born_family": str(family_path)},
        "source_refs": [str(family_path)],
        "native_jobs": [],
        "full_born_tensors_e": None,
        "columns": [],
        "sources": [],
        "missing_columns": [
            {"atom_id": atom_id, "cartesian_axis": axis, "reasons": ["unresolved"]}
            for atom_id in [0, 1] for axis in range(3)
        ],
        "raw_product": copy.deepcopy(raw),
        "status": "unresolved",
        "unresolved_reasons": ["software math fixture requires explicit review"],
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }
    return family_path, born, raw


def _review_case(
    tmp_path: Path,
    *,
    decision: str = "accepted",
    with_evidence: bool = True,
) -> tuple[Path, dict, Path, dict, Path | None]:
    family_path, born, raw = _math_case(tmp_path)
    evidence_path: Path | None = None
    evidence: list[dict] = []
    if with_evidence:
        evidence_path = (tmp_path / "continuous-path-review.txt").resolve()
        evidence_path.write_text("software_math_only continuity evidence\n", encoding="utf-8")
        evidence = [{
            "atom_id": 0,
            "direction_index": 0,
            "kind": "continuous_polarization_path",
            "source_refs": [str(evidence_path)],
            "rationale": "explicit software contract path",
        }]
    review = {
        "schema": "mlcc.native-born-affine-review.v1",
        "family_path": str(family_path),
        "context": copy.deepcopy(born["context"]),
        "integer_labels": copy.deepcopy(raw["affine_family"]["integer_labels"]),
        "decision": decision,
        "reviewer": "software-contract-reviewer",
        "reviewed_at": "2026-10-23T00:00:00Z",
        "rationale": "software math contract only",
        "integer_shifts": [1, 2, 0] if decision == "accepted" else None,
        "continuous_branch_evidence": evidence,
    }
    review_path = _write(tmp_path / "born-affine-review.json", review)
    return family_path, born, review_path, review, evidence_path


def test_evaluate_affine_preserves_cartesian_matrix_and_multiple_coefficients(tmp_path: Path):
    _, born, raw = _math_case(tmp_path)
    raw["affine_family"]["base_tensor_e"][0][0][1] = 4.0
    raw["affine_family"]["base_tensor_e"][0][1][0] = 7.0
    tensor = evaluate_born_affine(raw["affine_family"], [2, -3, 0])
    np.testing.assert_allclose(tensor[0][0][1], 4.0)
    np.testing.assert_allclose(tensor[0][1][0], 7.0)
    np.testing.assert_allclose(tensor[0][0][0], 1.0 + 2 * 0.1 - 3 * 0.3)
    np.testing.assert_allclose(tensor[1][0][0], 2.0 + 2 * 0.2 - 3 * 0.4)
    assert born["source_mode"] == "software_math_only"


def test_evaluate_affine_requires_explicit_integer_shifts(tmp_path: Path):
    _, _, raw = _math_case(tmp_path)
    for shifts in ([True, 0, 0], [1.0, 0, 0], [0]):
        with pytest.raises(ValueError, match="integer"):
            evaluate_born_affine(raw["affine_family"], shifts)


def test_consume_without_review_is_unresolved_and_does_not_mutate_family(tmp_path: Path, monkeypatch):
    family_path, born, raw = _math_case(tmp_path)
    original = family_path.read_text(encoding="utf-8")
    monkeypatch.setattr(born_affine, "read_native_born_family", lambda path: copy.deepcopy(born))
    product = consume_native_born_review(family_path)
    assert product["status"] == "unresolved"
    assert product["full_born_tensors_e"] is None
    assert "born_affine_review_missing" in product["unresolved_reasons"]
    assert product["source"]["native_born_review"] is None
    assert product["sources"] == [{
        "source_mode": "software_math_only",
        "native_born_family": str(family_path),
        "native_born_review": None,
    }]
    assert product["raw_product"] == raw
    assert family_path.read_text(encoding="utf-8") == original


def test_deferred_and_rejected_reviews_remain_unresolved(tmp_path: Path):
    for decision, reason in (("deferred", "born_affine_review_deferred"), ("rejected", "born_affine_review_rejected")):
        case = tmp_path / decision
        family_path, born, review_path, _, _ = _review_case(case, decision=decision, with_evidence=False)
        product = resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)
        assert product["status"] == "unresolved"
        assert product["full_born_tensors_e"] is None
        assert reason in product["unresolved_reasons"]
        assert product["source"]["native_born_review"] == str(review_path)
        assert family_path.exists()


def test_accepted_review_evaluates_tensor_columns_and_retains_source_text(tmp_path: Path, monkeypatch):
    family_path, born, review_path, _, evidence_path = _review_case(tmp_path)
    monkeypatch.setattr(born_affine, "read_native_born_family", lambda path: copy.deepcopy(born))
    product = consume_native_born_review(family_path, review_path)
    assert product["status"] == "reviewed_branch_tensor"
    assert product["scientific_qualification"] is False
    assert product["production_qualification"] is False
    np.testing.assert_allclose(product["full_born_tensors_e"], [
        [[1.7, 0.0, 0.0], [0.0, 1.7, 0.0], [0.0, 0.0, 1.7]],
        [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
    ])
    assert len(product["columns"]) == 6
    np.testing.assert_allclose(product["columns"][0]["values_e"], [1.7, 0.0, 0.0])
    assert str(review_path) in product["source_refs"]
    assert str(evidence_path) in product["source_refs"]
    assert product["review_source_text"] == review_path.read_text(encoding="utf-8")
    assert product["review_evidence"][0]["source_texts"][0]["text"] == evidence_path.read_text(encoding="utf-8")
    assert product["raw_product"] == born["raw_product"]
    assert product["source"]["native_born_family"] == str(family_path)


def test_accepted_review_without_complete_continuity_evidence_is_unresolved(tmp_path: Path):
    _, born, review_path, review, _ = _review_case(tmp_path, with_evidence=False)
    for missing in (False, True):
        if missing:
            del review["continuous_branch_evidence"]
        _write(review_path, review)
        product = resolve_born_affine_family(born, review, review_path=review_path)
        assert product["status"] == "unresolved"
        assert product["full_born_tensors_e"] is None
        assert "continuous_branch_evidence_missing" in product["unresolved_reasons"]
        assert product["missing_continuous_branch_groups"] == [[0, 0]]


def test_review_rejects_family_context_and_label_identity_mismatches(tmp_path: Path):
    for field, value, message in (
        ("family_path", str((tmp_path / "other-family.json").resolve()), "family_path differs"),
        ("context", {"parent": {}}, "context differs"),
        ("integer_labels", [{"label_index": 99}], "integer_labels differ"),
    ):
        case = tmp_path / field
        family_path, born, review_path, review, _ = _review_case(case)
        review[field] = value
        _write(review_path, review)
        with pytest.raises(ValueError, match=message):
            resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)
        assert family_path.exists()
    for field, value in (("label_index", 5), ("direction", "z"), ("atom_index", 1),
                         ("polarization_lattice_axis", "c")):
        _, born, review_path, review, _ = _review_case(tmp_path / ("semantic-" + field))
        born["raw_product"]["affine_family"]["integer_labels"][0][field] = value
        review["integer_labels"] = copy.deepcopy(born["raw_product"]["affine_family"]["integer_labels"])
        _write(review_path, review)
        with pytest.raises(ValueError, match="Born affine"):
            resolve_born_affine_family(born, review, review_path=review_path)


def test_review_rejects_non_integer_or_incomplete_branch_shift_list(tmp_path: Path):
    for shifts in ([True, 2, 0], [1.0, 2, 0], [1]):
        case = tmp_path / str(len(str(shifts)))
        _, born, review_path, review, _ = _review_case(case)
        review["integer_shifts"] = shifts
        _write(review_path, review)
        with pytest.raises(ValueError, match="integer"):
            resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)


def test_missing_or_noncontinuous_evidence_stays_unresolved_but_missing_file_is_error(tmp_path: Path):
    case = tmp_path / "empty"
    _, born, review_path, review, _ = _review_case(case)
    review["continuous_branch_evidence"][0]["source_refs"] = []
    _write(review_path, review)
    product = resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)
    assert product["status"] == "unresolved"
    assert "continuous_branch_evidence_missing" in product["unresolved_reasons"]

    case = tmp_path / "kind"
    _, born, review_path, review, _ = _review_case(case)
    review["continuous_branch_evidence"][0]["kind"] = "endpoint_only"
    _write(review_path, review)
    product = resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)
    assert product["status"] == "unresolved"

    case = tmp_path / "missing-file"
    _, born, review_path, review, _ = _review_case(case)
    review["continuous_branch_evidence"][0]["source_refs"] = [str((case / "missing.txt").resolve())]
    _write(review_path, review)
    with pytest.raises(FileNotFoundError):
        resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)

    case = tmp_path / "duplicate"
    _, born, review_path, review, _ = _review_case(case)
    review["continuous_branch_evidence"].append(copy.deepcopy(review["continuous_branch_evidence"][0]))
    _write(review_path, review)
    with pytest.raises(ValueError, match="duplicate"):
        resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)
    review["continuous_branch_evidence"][0]["kind"] = "endpoint_only"
    _write(review_path, review)
    with pytest.raises(ValueError, match="duplicate"):
        resolve_born_affine_family(born, review, review_path=review_path)


def test_reviewed_math_born_keeps_ionic_and_static_outputs_unresolved(tmp_path: Path):
    _, born, review_path, _, _ = _review_case(tmp_path)
    reviewed = resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)
    thresholds = {
        "symmetry_eV_per_A2": 1.0,
        "translation_eV_per_A2": 1.0,
        "born_sum_e": 1.0,
        "minimum_optical_eigenvalue_eV_per_A2": 1.0,
    }
    ionic = calculate_ionic_dielectric(reviewed, None, thresholds=thresholds)
    combined = combine_dielectric_contributions(reviewed, None, ionic)
    assert ionic["delta_epsilon_ionic"] is None
    assert combined["epsilon_static"] is None
    assert combined["scientific_qualification"] is False
    assert combined["production_qualification"] is False
    assert combined["ionic"]["born_source"]["sources"] == reviewed["sources"]

    native_stub = copy.deepcopy(reviewed)
    native_stub["source_mode"] = "native_source_bound"
    native_stub["common_method"]["engine"] = "abacus"
    native_stub["context"]["common_method"]["engine"] = "abacus"
    native_stub["sources"][0]["source_mode"] = "native_source_bound"
    native_ionic = calculate_ionic_dielectric(native_stub, None, thresholds=thresholds)
    assert _p5_declared_mode(native_ionic, "ionic") == "native_source_bound"


def test_p5_native_born_rebuilds_review_product_and_rejects_edited_tensor(tmp_path: Path, monkeypatch):
    family_path, born, review_path, _, _ = _review_case(tmp_path)
    product = resolve_born_affine_family(born, json.loads(review_path.read_text()), review_path=review_path)
    calls: list[tuple[str, str | None]] = []

    def rebuild(family: str | Path, review: str | Path | None = None) -> dict:
        calls.append((str(family), None if review is None else str(review)))
        return copy.deepcopy(product)

    monkeypatch.setattr(born_affine, "consume_native_born_review", rebuild)
    jobs = _p5_native_born(product, product["context"])
    assert jobs == product["native_jobs"]
    assert calls == [(str(family_path), str(review_path))]

    edited = copy.deepcopy(product)
    edited["full_born_tensors_e"][0][0][0] += 1.0
    with pytest.raises(ValueError, match="differs from its saved source"):
        _p5_native_born(edited, edited["context"])
