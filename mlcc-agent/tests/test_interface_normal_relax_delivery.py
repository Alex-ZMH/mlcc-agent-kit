"""Saved-product contract fixture for relaxed normal-response delivery."""

import json

from mlcc.property_delivery import deliver_interface_normal


def test_delivery_preserves_unconverged_clamped_response(tmp_path):
    interface = {"parent_models": [], "parent_study_refs": []}
    study = {
        "study_id": "normal-relax-delivery-fixture", "case_id": "math-fixture",
        "case_role": "engineering_fixture", "model": {"model_id": "fixture", "version": "v001"},
        "interface": interface,
    }
    protocol = {"normal_response": {"kinematics": "fixed_cell_clamped_internal_relaxation"}}
    task = {
        "task_id": "defined-fixture", "study_id": study["study_id"], "case_id": study["case_id"],
        "model_id": "fixture", "model_version": "v001", "protocol": protocol,
        "study": study,
    }
    task_path = tmp_path / "task.json"
    response = {
        "status": "mathematical_fixture", "relaxation_status": "unconverged",
        "points": [{"minimization": {"stopping_criterion": "max iterations", "converged": False}}],
    }
    product = {
        **task, "schema": "mlcc.interface-normal-product.v1", "task_path": str(task_path),
        "status": "available", "normal_response": response, "relaxation_status": "unconverged",
        "source_task": {"scheduler_job_id": None}, "native_result": None, "missing_evidence": [],
    }
    study_path, product_path = tmp_path / "study.json", tmp_path / "product.json"
    for path, data in ((study_path, study), (task_path, task), (product_path, product)):
        path.write_text(json.dumps(data), encoding="utf-8")
    delivery = deliver_interface_normal(study_path, product_path)
    assert delivery["relaxation_status"] == "unconverged"
    assert delivery["responses"]["constrained_normal_response"] == response
    assert delivery["source_task"]["scheduler_job_id"] is None
    assert delivery["native_result"] is None
