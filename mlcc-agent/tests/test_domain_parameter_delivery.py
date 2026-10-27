"""New saved domain-parameter delivery boundary; no native source reads."""

import json

import pytest

from mlcc.cli import main
from mlcc.domain_parameters import domain_parameter_product
from mlcc.property_delivery import deliver_domain_parameters


def _saved(tmp_path):
    study = {"study_id": "study", "case_id": "case", "model": {"model_id": "cell", "version": "v001"}}
    product = domain_parameter_product(
        kind="bulk_thermodynamics", model=study["model"],
        study={"study_id": "study", "case_id": "case"},
        properties=[{
            "name": "mass_density", "value": None, "unit": "kg/m^3", "shape": [],
            "definition": "whole cell mass divided by volume", "conditions": {},
            "coordinates": "not_applicable_to_scalar", "atom_mapping_ref": "saved-atom-map.json",
            "source_refs": ["saved-source.json"], "status": "unresolved", "reason": "mass_missing",
        }],
        execution={"analysis_job_id": "analysis", "source_jobs": [{"job_id": "native", "state": "FAILED", "exit_code": "1:0"}]},
    )
    study_path, product_path = tmp_path / "study.json", tmp_path / "product.json"
    study_path.write_text(json.dumps(study), encoding="utf-8")
    product_path.write_text(json.dumps(product), encoding="utf-8")
    return study_path, product_path, product


def test_cli_delivers_saved_values_and_original_states_without_opening_source_refs(tmp_path):
    study_path, product_path, product = _saved(tmp_path)
    output = tmp_path / "delivery.json"
    assert main(["deliver-properties", "--study", str(study_path),
                 "--domain-parameters", str(product_path), "--output", str(output)]) == 0
    delivery = json.loads(output.read_text(encoding="utf-8"))
    assert delivery["product"] == product
    assert delivery["properties"][0]["value"] is None
    assert delivery["properties"][0]["status"] == "unresolved"
    assert delivery["execution"]["source_jobs"][0]["state"] == "FAILED"


def test_domain_delivery_rejects_another_study(tmp_path):
    study_path, product_path, _ = _saved(tmp_path)
    study = json.loads(study_path.read_text(encoding="utf-8"))
    study["study_id"] = "other-study"
    study_path.write_text(json.dumps(study), encoding="utf-8")
    with pytest.raises(ValueError, match="study_id differs"):
        deliver_domain_parameters(study_path, product_path)
