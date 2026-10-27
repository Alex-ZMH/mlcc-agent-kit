"""Saved composition delivery keeps family records without reconstructing them."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mlcc.property_delivery import deliver_composition_product, deliver_continuum_package


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _study() -> dict:
    return {
        "study_id": "composition-fixture-study",
        "case_id": "composition-input-check",
        "case_role": "engineering_fixture",
        "model": {"model_id": "composition-fixture-baseline", "version": "v001"},
    }


@pytest.mark.parametrize("kind", ["build", "comparison"])
def test_saved_composition_delivery_preserves_missing_and_variant_records(tmp_path: Path, kind: str) -> None:
    study = _study()
    model_ref = {**study["model"], "path": str(tmp_path / "absent-model")}
    product = {
        "schema": "mlcc.composition-build.v1" if kind == "build" else "mlcc.composition-comparison.v1",
        "study_id": study["study_id"],
        "status": "unresolved",
        "unresolved_reasons": ["saved_variant_property_missing"],
        "source_refs": [str(tmp_path / "absent-source.json")],
        "model_ref": model_ref,
        "baseline": {"model_ref": model_ref},
        "variants": [{"id": "v", "model_ref": {"model_id": "composition-fixture-variant", "version": "v001"}}],
        "comparisons": [{"property_id": "epsilon", "difference": None, "reason": "saved_variant_property_missing"}],
        "analysis_scheduler_job_id": "saved-job",
    }
    study_file = _write(tmp_path / "study.json", study)
    product_file = _write(tmp_path / "product.json", product)
    result = deliver_composition_product(study_file, product_file)
    assert result["responses"]["composition"] == product
    assert result["status"] == "unresolved"
    assert result["model_refs"] == model_ref
    assert result["source_refs"] == product["source_refs"]


@pytest.mark.parametrize("mismatch", ["study", "model"])
def test_composition_delivery_rejects_different_study_or_reference_model(tmp_path: Path, mismatch: str) -> None:
    study = _study()
    product = {
        "schema": "mlcc.composition-comparison.v1",
        "study_id": study["study_id"],
        "status": "complete",
        "baseline": {"model_ref": copy.deepcopy(study["model"])},
        "source_refs": [],
    }
    if mismatch == "study":
        product["study_id"] = "different-study"
    else:
        product["baseline"]["model_ref"]["model_id"] = "different-model"
    with pytest.raises(ValueError):
        deliver_composition_product(
            _write(tmp_path / "study.json", study), _write(tmp_path / "product.json", product)
        )


def test_saved_continuum_delivery_preserves_null_parameter_and_source_paths(tmp_path: Path) -> None:
    study = _study()
    package = {
        "schema": "mlcc.continuum-parameters.v1",
        "study": study,
        "status": "unresolved",
        "parameters": {
            "epsilon_static": {
                "value": None,
                "reason": "saved_static_response_missing",
                "source_path": str(tmp_path / "absent-source.json"),
            }
        },
    }
    result = deliver_continuum_package(
        _write(tmp_path / "study.json", study), _write(tmp_path / "package.json", package)
    )
    assert result["responses"]["continuum_parameters"] == package
    assert result["status"] == "unresolved"
    assert result["model_refs"] == study["model"]


def test_continuum_delivery_rejects_different_saved_model(tmp_path: Path) -> None:
    study = _study()
    package = {"schema": "mlcc.continuum-parameters.v1", "study": copy.deepcopy(study)}
    package["study"]["model"]["model_id"] = "different-model"
    with pytest.raises(ValueError):
        deliver_continuum_package(
            _write(tmp_path / "study.json", study), _write(tmp_path / "package.json", package)
        )
