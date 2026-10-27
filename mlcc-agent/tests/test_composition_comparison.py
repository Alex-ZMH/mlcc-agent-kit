"""Math fixtures for saved composition-property comparison.

These tests exercise only saved JSON-shaped records.  They do not invoke a
native engine, run a calculation, or claim a material qualification.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc.composition_comparison import (
    REQUEST_SCHEMA,
    SCHEMA,
    analyze_composition_comparison_request,
    compare_composition_properties,
)


_BASIS_6 = {
    "coordinate_system": "cartesian",
    "voigt_order": ["xx", "yy", "zz", "yz", "xz", "xy"],
    "shear_convention": "engineering",
}


def _model(model_id: str, *, family_id: str = "math-composition-family") -> dict[str, object]:
    return {
        "model_id": model_id,
        "version": "v001",
        "family_id": family_id,
        "role": "engineering_fixture",
        "composition": {"A": 1, "B": 1, "C": 1, "D": 1},
    }


def _product(*, gap: float | None, elastic: list[list[float]] | None, source: str) -> dict[str, object]:
    product: dict[str, object] = {
        "schema": "mlcc.saved-property-product.v1",
        "status": "engineering_fixture",
        "production_qualified": False,
        "source_refs": [source],
        "model_ref": {"model_id": "fixture-model", "version": "v001"},
        "study_id": "study-composition-math",
        "source_declarations": {
            "band_gap": {"source": f"{source}#band_gap", "origin": "saved_product_fixture"},
            "elastic": {"source": f"{source}#elastic", "origin": "saved_product_fixture"},
        },
        "property_metadata": {
            "band_gap": {
                "definition": "single-particle band gap at the saved geometry",
                "unit": "eV",
                "object_level": "cell",
                "conditions": {"temperature_K": 330.0, "pressure_Pa": 101325.0},
                "basis": None,
            },
            "elastic": {
                "definition": "elastic stiffness in the saved Cartesian frame",
                "unit": "GPa",
                "object_level": "cell",
                "conditions": {"temperature_K": 330.0, "pressure_Pa": 101325.0},
                "basis": _BASIS_6,
            },
        },
    }
    if gap is not None:
        product["band_gap_eV"] = gap
    if elastic is not None:
        product["elastic_C_GPa"] = elastic
    return product


def _record(
    record_id: str,
    *,
    gap: float | None = 2.0,
    elastic: list[list[float]] | None = None,
    model_id: str = "fixture-model",
    family_id: str = "math-composition-family",
) -> dict[str, object]:
    if elastic is None:
        elastic = [[100.0 if row == column else 0.0 for column in range(6)] for row in range(6)]
    model = _model(model_id, family_id=family_id)
    product = _product(gap=gap, elastic=elastic, source=f"saved://{record_id}")
    product["model_ref"]["model_id"] = model_id
    return {
        "id": record_id,
        "study_id": "study-composition-math",
        "model": model,
        "product": product,
    }


def _selected_properties(*, relative_gap: bool = True) -> list[dict[str, object]]:
    return [
        {
            "property_id": "band_gap",
            "field": "band_gap_eV",
            "definition": "single-particle band gap at the saved geometry",
            "unit": "eV",
            "object_level": "cell",
            "conditions": {"temperature_K": 330.0, "pressure_Pa": 101325.0},
            "normalization": {"kind": "none"},
            "basis": None,
            "relative": relative_gap,
        },
        {
            "property_id": "elastic",
            "field": "elastic_C_GPa",
            "definition": "elastic stiffness in the saved Cartesian frame",
            "unit": "GPa",
            "object_level": "cell",
            "conditions": {"temperature_K": 330.0, "pressure_Pa": 101325.0},
            "normalization": {"kind": "none"},
            "basis": _BASIS_6,
        },
    ]


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _method_fixture() -> dict[str, object]:
    elements = ["A", "B", "C", "D"]
    return {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "basis_type": "pw",
        "science": {
            "dft_functional": "PBE",
            "nspin": 1,
            "lspinorb": False,
            "noncolin": False,
            "initial_moments_muB_by_element": {element: 0.0 for element in elements},
            "occupations": "fixed",
            "smearing_method": "none",
            "mixing_type": "plain",
            "relax_method": "none",
            "symmetry": "none",
        },
        "execution": {"ks_solver": "dav"},
        "net_charge": 0,
        "charge_convention": "electrons",
        "element_order": elements,
        "kpoints": [2, 2, 2],
        "kpoint_rule": "explicit",
        "stage": "scf",
        "parameters": {
            "ecutwfc_Ry": 80.0,
            "scf_thr": 1.0e-4,
            "scf_nmax": 100,
            "nbands": 40,
            "smearing_sigma_Ry": 0.0,
            "mixing_beta": 0.4,
            "force_thr_eV_per_A": 0.01,
            "relax_nmax": 0,
        },
        "method_set": "fixture-method",
        "pseudopotential_ids": {element: f"{element}-fixture" for element in elements},
        "pseudopotential_treatment": {element: "NC" for element in elements},
        "pseudopotential_metadata": {element: {} for element in elements},
    }


def test_compare_scalar_normalization_and_voigt_tensor() -> None:
    baseline = _record("baseline", gap=2.0)
    variant = _record("variant", gap=2.5)
    variant_elastic = variant["product"]["elastic_C_GPa"]
    assert isinstance(variant_elastic, list)
    variant_elastic[0][0] = 102.0
    result = compare_composition_properties(
        baseline,
        [variant],
        _selected_properties(),
        method_comparison={"status": "explicit", "common_method": "fixture-method"},
        analysis_scheduler_job_id="job-composition-fixture",
    )
    assert result["schema"] == SCHEMA
    assert result["status"] == "complete"
    assert result["production_qualified"] is False
    assert result["analysis_scheduler_job_id"] == "job-composition-fixture"
    assert result["method_comparison"]["status"] == "explicit"
    gap_comparison = result["comparisons"][0]
    assert gap_comparison["difference"] == pytest.approx(0.5)
    assert gap_comparison["relative_difference"] == pytest.approx(0.25)
    elastic_comparison = result["comparisons"][1]
    assert elastic_comparison["difference"][0][0] == pytest.approx(2.0)
    assert elastic_comparison["variant"]["basis"]["shear_convention"] == "engineering"
    assert "saved://baseline" in result["source_refs"]
    assert "saved://variant" in result["source_refs"]


def test_per_atom_normalization_and_zero_baseline_relative_is_unresolved() -> None:
    baseline = _record("baseline", gap=0.0)
    variant = _record("variant", gap=4.0)
    selected = [{
        "property_id": "formation_energy",
        "field": "band_gap_eV",
        "definition": "formation product value",
        "unit": "eV",
        "object_level": "cell",
        "conditions": {},
        "normalization": {"kind": "per_atom"},
        "basis": None,
        "energy_kind": "formation_energy",
        "relative": True,
    }]
    baseline["product"]["property_metadata"]["formation_energy"] = {
        "definition": "formation product value",
        "unit": "eV",
        "object_level": "cell",
        "conditions": {},
        "basis": None,
    }
    baseline["product"]["source_declarations"]["formation_energy"] = {
        "source": "saved://baseline#formation_energy",
        "origin": "saved_product_fixture",
    }
    variant["product"]["property_metadata"]["formation_energy"] = baseline["product"]["property_metadata"]["formation_energy"]
    variant["product"]["source_declarations"]["formation_energy"] = {
        "source": "saved://variant#formation_energy",
        "origin": "saved_product_fixture",
    }
    result = compare_composition_properties(baseline, [variant], selected)
    comparison = result["comparisons"][0]
    assert comparison["baseline"]["value"] == pytest.approx(0.0)
    assert comparison["variant"]["value"] == pytest.approx(1.0)
    assert comparison["difference"] == pytest.approx(1.0)
    assert comparison["relative_difference"] is None
    assert comparison["status"] == "unresolved"
    assert comparison["reason"] == "baseline_value_zero_relative_undefined"
    assert result["status"] == "unresolved"


def test_per_formula_unit_uses_each_saved_model_composition() -> None:
    baseline = _record("baseline", gap=8.0)
    variant = _record("variant", gap=16.0)
    baseline["model"]["composition"] = {"A": 2, "B": 2, "C": 2, "D": 2}
    variant["model"]["composition"] = {"A": 3, "B": 3, "C": 3, "D": 3}
    selected = [{
        "property_id": "band_gap",
        "field": "band_gap_eV",
        "definition": "single-particle band gap at the saved geometry",
        "unit": "eV",
        "object_level": "cell",
        "conditions": {"temperature_K": 330.0, "pressure_Pa": 101325.0},
        "normalization": {"kind": "per_formula_unit", "formula": {"A": 1, "B": 1, "C": 1, "D": 1}},
        "basis": None,
    }]
    result = compare_composition_properties(baseline, [variant], selected)
    comparison = result["comparisons"][0]
    assert comparison["baseline"]["normalization_factor"] == pytest.approx(2.0)
    assert comparison["variant"]["normalization_factor"] == pytest.approx(3.0)
    assert comparison["baseline"]["value"] == pytest.approx(4.0)
    assert comparison["variant"]["value"] == pytest.approx(16.0 / 3.0)
    assert comparison["difference"] == pytest.approx(4.0 / 3.0)


def test_missing_saved_value_preserves_reason_and_raw_value() -> None:
    baseline = _record("baseline", gap=2.0)
    variant = _record("variant", gap=None)
    result = compare_composition_properties(baseline, [variant], [_selected_properties()[0]])
    comparison = result["comparisons"][0]
    assert comparison["status"] == "unresolved"
    assert comparison["reason"] == "variant:property_value_missing"
    assert comparison["variant"]["raw_value"] is None
    assert comparison["difference"] is None


def test_missing_source_declaration_keeps_raw_value_unresolved() -> None:
    baseline = _record("baseline", gap=2.0)
    variant = _record("variant", gap=2.5)
    del variant["product"]["source_declarations"]["band_gap"]
    result = compare_composition_properties(baseline, [variant], [_selected_properties()[0]])
    comparison = result["comparisons"][0]
    assert comparison["status"] == "unresolved"
    assert comparison["reason"] == "variant:source_declaration_missing"
    assert comparison["variant"]["raw_value"] == pytest.approx(2.5)
    assert comparison["difference"] is None


def test_definition_mismatch_is_incomparable_but_keeps_raw_values() -> None:
    baseline = _record("baseline", gap=2.0)
    variant = _record("variant", gap=2.5)
    variant["product"]["property_metadata"]["band_gap"]["conditions"] = {"temperature_K": 400.0}
    result = compare_composition_properties(baseline, [variant], [_selected_properties()[0]])
    comparison = result["comparisons"][0]
    assert comparison["status"] == "incomparable"
    assert comparison["reason"] == "variant:variants[0].conditions_differs_from_selected_definition"
    assert comparison["variant"]["raw_value"] == pytest.approx(2.5)
    assert comparison["difference"] is None


def test_request_loader_binds_saved_model_product_and_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _record("baseline", gap=2.0)
    variant = _record("variant", gap=2.5)
    baseline["product"]["study_id"] = "study-from-saved-json"
    baseline_model = _write_json(tmp_path / "baseline-model.json", baseline["model"])
    baseline_product = _write_json(tmp_path / "baseline-product.json", baseline["product"])
    variant_model = _write_json(tmp_path / "variant-model.json", variant["model"])
    variant_product = _write_json(tmp_path / "variant-product.json", variant["product"])
    study = _write_json(tmp_path / "study.json", {"study_id": "study-from-saved-json"})
    method_comparison = _write_json(
        tmp_path / "baseline-method.json",
        _method_fixture(),
    )
    variant_method = _write_json(tmp_path / "variant-method.json", _method_fixture())
    request = {
        "schema": REQUEST_SCHEMA,
        "study_id": "study-from-saved-json",
        "record_kind": "configuration",
        "baseline": {
            "id": "baseline",
            "model_ref": {"model_id": "fixture-model", "version": "v001", "path": baseline_model.name},
            "product_path": baseline_product.name,
            "study_path": study.name,
            "method_path": method_comparison.name,
        },
        "variants": [{
            "id": "variant",
            "model_ref": {"model_id": "fixture-model", "version": "v001", "path": variant_model.name},
            "product_path": variant_product.name,
            "method_path": variant_method.name,
        }],
        "selected_properties": [_selected_properties()[0]],
    }
    request_path = _write_json(tmp_path / "comparison-request.json", request)
    monkeypatch.setenv("SLURM_JOB_ID", "job-request-loader-fixture")
    result = analyze_composition_comparison_request(request_path)
    assert result["study_id"] == "study-from-saved-json"
    assert result["analysis_scheduler_job_id"] == "job-request-loader-fixture"
    assert result["comparisons"][0]["difference"] == pytest.approx(0.5)
    assert result["method_comparison"]["record_kind"] == "configuration"
    assert result["method_comparison"]["variants"][0]["result"]["status"] == "comparable"
    assert str(request_path.resolve()) in result["source_refs"]
    assert str(baseline_model.resolve()) in result["source_refs"]
    assert str(method_comparison.resolve()) in result["source_refs"]
    assert result["baseline"]["model_ref"]["path"] == str(baseline_model.resolve())
    assert result["variants"][0]["model_ref"]["path"] == str(variant_model.resolve())

    request["record_kind"] = "native"
    wrong_model_method = {**_method_fixture(), "model_id": "another-model", "version": "v001"}
    _write_json(method_comparison, wrong_model_method)
    _write_json(request_path, request)
    with pytest.raises(ValueError, match="native method identity differs"):
        analyze_composition_comparison_request(request_path)


def test_bare_total_energy_is_rejected_and_different_families_are_rejected() -> None:
    energy = {
        "property_id": "energy",
        "field": "total_energy_eV",
        "definition": "bare total energy",
        "unit": "eV",
        "object_level": "cell",
        "conditions": {},
        "normalization": {"kind": "none"},
        "basis": None,
    }
    with pytest.raises(ValueError, match="bare total energy"):
        compare_composition_properties(_record("baseline"), [_record("variant")], [energy])
    other_family = _record("other", family_id="different-family", model_id="other-model")
    with pytest.raises(ValueError, match="one composition family"):
        compare_composition_properties(_record("baseline"), [other_family], [_selected_properties()[0]])
    same_label_unrelated_model = _record("unrelated", family_id="math-composition-family", model_id="other-model")
    with pytest.raises(ValueError, match="one composition family"):
        compare_composition_properties(_record("baseline"), [same_label_unrelated_model], [_selected_properties()[0]])


def test_request_reference_cannot_replace_saved_model_lineage() -> None:
    unrelated = _record("unrelated", model_id="other-model")
    unrelated["reference_model"] = {"model_id": "fixture-model", "version": "v001"}
    with pytest.raises(ValueError, match="one composition family"):
        compare_composition_properties(_record("baseline"), [unrelated], [_selected_properties()[0]])


@pytest.mark.parametrize("mismatch", ["model", "study"])
def test_variant_product_must_belong_to_its_selected_model_and_study(mismatch: str) -> None:
    variant = _record("variant")
    if mismatch == "model":
        variant["product"]["model_ref"]["model_id"] = "different-model"
    else:
        variant["product"]["study_id"] = "different-study"
    with pytest.raises(ValueError):
        compare_composition_properties(_record("baseline"), [variant], [_selected_properties()[0]])


def test_second_order_tensor_uses_explicit_nontrivial_rotation() -> None:
    target_basis = {"coordinate_system": "common", "axes": ["x", "y", "z"]}
    source_basis = {
        "coordinate_system": "local",
        "rotation_to_common": [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
        "common_basis": target_basis,
    }
    baseline = _record("baseline")
    variant = _record("variant")
    baseline["product"]["tensor_3x3"] = [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]]
    variant["product"]["tensor_3x3"] = [[3.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 2.0]]
    for record, basis in ((baseline, target_basis), (variant, source_basis)):
        record["product"]["property_metadata"]["tensor"] = {
            "definition": "second-order Cartesian tensor",
            "unit": "GPa",
            "object_level": "cell",
            "conditions": {},
            "basis": basis,
        }
        record["product"]["source_declarations"]["tensor"] = {
            "source": f"saved://{record['id']}#tensor",
            "origin": "saved_product_fixture",
        }
    selected = [{
        "property_id": "tensor",
        "field": "tensor_3x3",
        "definition": "second-order Cartesian tensor",
        "unit": "GPa",
        "object_level": "cell",
        "conditions": {},
        "normalization": {"kind": "none"},
        "basis": target_basis,
    }]
    result = compare_composition_properties(baseline, [variant], selected)
    comparison = result["comparisons"][0]
    assert comparison["status"] == "complete"
    assert comparison["variant"]["value"] == [[1.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 2.0]]
    assert comparison["difference"] == [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]]


def test_voigt_basis_mismatch_is_explicitly_incomparable() -> None:
    baseline = _record("baseline")
    variant = _record("variant")
    variant["product"]["property_metadata"]["elastic"]["basis"] = {
        **_BASIS_6,
        "voigt_order": ["xx", "yy", "zz", "xy", "xz", "yz"],
    }
    result = compare_composition_properties(baseline, [variant], [_selected_properties()[1]])
    comparison = result["comparisons"][0]
    assert comparison["status"] == "incomparable"
    assert comparison["reason"] == "variant:voigt_basis_rotation_unsupported"
    assert comparison["variant"]["raw_value"] is not None
    assert comparison["difference"] is None
