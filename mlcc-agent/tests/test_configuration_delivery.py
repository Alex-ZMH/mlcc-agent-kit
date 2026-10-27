"""New finite-configuration collection delivery, without rebuilding models."""
import copy
import json

import pytest

from mlcc.property_delivery import deliver_composition_product


def test_configuration_collection_preserves_each_child_seed_and_missing_build(tmp_path):
    study = {"study_id": "parent-study", "case_id": "parent-case", "case_role": "engineering_fixture",
             "model": {"model_id": "parent", "version": "v001"}}
    product = {
        "schema": "mlcc.composition-configurations.v1", "study_id": study["study_id"],
        "model_ref": study["model"], "status": "unresolved", "source_refs": ["unavailable-original-request.json"],
        "configurations": [{"configuration_id": "seeded-001", "seed": 37, "status": "unresolved",
                            "model_ref": None, "unresolved_reason": "missing explicit compensation"}],
        "native_scheduler_job_id": None, "analysis_scheduler_job_id": "saved-configuration-job",
    }
    study_file, product_file = tmp_path / "study.json", tmp_path / "collection.json"
    study_file.write_text(json.dumps(study), encoding="utf-8")
    product_file.write_text(json.dumps(product), encoding="utf-8")
    result = deliver_composition_product(study_file, product_file)
    assert result["responses"]["composition"] == product
    assert result["status"] == "unresolved"
    assert result["model_refs"] == study["model"]

    other_study = copy.deepcopy(study)
    other_study["model"] = {"model_id": "child", "version": "v001"}
    study_file.write_text(json.dumps(other_study), encoding="utf-8")
    with pytest.raises(ValueError, match="reference model differs"):
        deliver_composition_product(study_file, product_file)
