"""Saved 466/468 product delivery only; centroid algorithms are already accepted."""

import json
import os
from pathlib import Path

import pytest

import mlcc.local_stress as domain
import mlcc.local_stress_tasks as tasks
import mlcc.lammps_local_stress as native
from mlcc.cli import build_parser
from mlcc.property_delivery import deliver_local_stress


def test_saved_bulk_centroid_reaches_study_without_reparsing(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("saved centroid delivery must not reread native data or convert tensors")
    monkeypatch.setattr(domain, "local_stress_from_frames", forbidden)
    monkeypatch.setattr(tasks, "read_local_stress_task", forbidden)
    monkeypatch.setattr(native, "read_local_stress_outputs", forbidden)
    product_path = Path(os.environ["MLCC_CENTROID_PRODUCT"])
    study_path = Path(os.environ["MLCC_CENTROID_STUDY"])
    product = json.loads(product_path.read_text())
    result = deliver_local_stress(study_path, product_path)
    assert result["responses"]["local_stress"] == product["local_stress"]
    assert result["native_local_stress"] == product["native_local_stress"]
    assert result["source_task"]["scheduler_job_id"] == "466"
    assert result["parent_models"] is None and result["parent_study_refs"] is None
    assert result["parent_model"] == product["parent_model"]
    assert result["method_set"] == product["method_set"]
    assert result["potential"] == product["potential"]
    assert result["missing_evidence"] == product["missing_evidence"]
    args = build_parser().parse_args(["local-stress", "--task", product["task_path"],
                                     "--request", product["request_path"], "--output", "not-executed.json"])
    assert args.task == Path(product["task_path"])


def test_bulk_support_does_not_allow_interface_source_omission(tmp_path):
    product = json.loads(Path(os.environ["MLCC_INTERFACE_STRESS_PRODUCT"]).read_text())
    task = json.loads(Path(product["task_path"]).read_text())
    task["interface_sources"] = None
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps(task))
    product["task_path"] = str(task_path)
    product["interface_sources"] = None
    product_path = tmp_path / "missing-interface.json"
    product_path.write_text(json.dumps(product))
    with pytest.raises(ValueError, match="interface sources"):
        deliver_local_stress(os.environ["MLCC_THERMAL_NI_STUDY"], product_path)
