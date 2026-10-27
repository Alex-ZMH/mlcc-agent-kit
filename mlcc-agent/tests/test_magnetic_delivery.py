"""New magnetic Study binding and missing-observation propagation."""
import json

import pytest

from mlcc.property_delivery import deliver_magnetic_properties


def _saved(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    task = {
        "study_id": "study-a", "task_id": "saved-task", "scheduler_job_id": "fixture-job",
        "method_set": "fixture-method", "model_id": "model-a", "model_version": "v001",
        "scheduler_state": "FAILED", "exit_code": "1:0", "scientific_status": "unconverged",
        "calculation_conditions": {"calculation_kind": "static_dft_reference"},
    }
    (task_dir / "task.json").write_text(json.dumps(task))
    study = {"study_id": "study-a", "model": {"model_id": "model-a", "version": "v001"}}
    study_path = tmp_path / "study.json"
    study_path.write_text(json.dumps(study))
    product = {key: task[key] for key in ("task_id", "scheduler_job_id", "method_set", "model_id", "model_version")}
    product.update(
        schema="mlcc.abacus-magnetic.v001", task_path=str(task_dir), status="missing",
        total_magnetization_muB=None, mean_magnetization_muB_per_atom=None,
        source_files={"task.json": str(task_dir / "task.json")},
        initial_seed={"initial_magnetic_moment_muB_per_atom": 0.6},
        electronic_converged=False, magnetic_order="unassessed",
    )
    product_path = tmp_path / "product.json"
    product_path.write_text(json.dumps(product))
    return study_path, product_path, study, product


def test_delivery_preserves_missing_outputs_and_failed_source(tmp_path):
    study_path, product_path, _, product = _saved(tmp_path)
    result = deliver_magnetic_properties(study_path, product_path)
    assert result["product"] == product
    assert [item["value"] for item in result["observables"]] == [None, None]
    assert [item["unit"] for item in result["observables"]] == ["muB", "muB/atom"]
    assert result["scientific_status"] == "unconverged"
    assert result["task_refs"][0]["exit_code"] == "1:0"
    assert result["design_assessment"] == "not_assessed"


@pytest.mark.parametrize("change", ["study", "source_job"])
def test_delivery_rejects_cross_study_or_cross_job_product(tmp_path, change):
    study_path, product_path, study, product = _saved(tmp_path)
    if change == "study":
        study["study_id"] = "another-study"
        study_path.write_text(json.dumps(study))
        expected = "study_id"
    else:
        product["scheduler_job_id"] = "another-job"
        product_path.write_text(json.dumps(product))
        expected = "scheduler_job_id"
    with pytest.raises(ValueError, match=expected):
        deliver_magnetic_properties(study_path, product_path)
