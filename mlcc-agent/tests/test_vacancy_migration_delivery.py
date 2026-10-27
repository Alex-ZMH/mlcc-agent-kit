"""Saved vacancy products reach the same Study without frame re-analysis."""

import json

import pytest

from mlcc.property_delivery import deliver_vacancy_migration


@pytest.mark.parametrize("mode", ["md_time", "neb_path"])
def test_saved_vacancy_product_preserves_events_and_unresolved_source(tmp_path, mode):
    study = {
        "study_id": "vacancy-study", "case_id": "vacancy-case", "case_role": "engineering_fixture",
        "model": {"model_id": "vacancy19", "version": "v001"},
    }
    product = {
        "schema": "mlcc.vacancy-migration.v1", "mode": mode,
        "study_id": study["study_id"], "model_ref": dict(study["model"]),
        "status": "unresolved", "frames": [{"frame_index": 1, "status": "unresolved"}],
        "jump_events": [] if mode == "md_time" else None,
        "site_changes": [] if mode == "neb_path" else None,
        "unresolved_reasons": ["ambiguous site occupancy"],
        "source_refs": [str(tmp_path / "unavailable-original-source.json")],
        "source_record": {"native_job": {"scheduler_job_id": "155"}, "unwrap_evidence": "missing"},
    }
    study_path, product_path = tmp_path / "study.json", tmp_path / "product.json"
    study_path.write_text(json.dumps(study), encoding="utf-8")
    product_path.write_text(json.dumps(product), encoding="utf-8")
    result = deliver_vacancy_migration(study_path, product_path)
    assert result["responses"]["vacancy_migration"] == product
    assert result["status"] == "unresolved"
    assert result["model_refs"] == study["model"]
    study["model"]["model_id"] = "another-model"
    study_path.write_text(json.dumps(study), encoding="utf-8")
    with pytest.raises(ValueError, match="model differs from Study"):
        deliver_vacancy_migration(study_path, product_path)
