"""New saved-product delivery paths; real sources supplied by Slurm acceptance."""

import json
import os
from pathlib import Path

import pytest

import mlcc.thermal_stress as domain
import mlcc.thermal_stress_sources as sources
import mlcc.local_stress_tasks as local_tasks
import mlcc.interface_thermal_tasks as thermal_tasks
from mlcc.property_delivery import deliver_thermal_stress


def _paths(case):
    return Path(os.environ[f"MLCC_THERMAL_{case}_STUDY"]), Path(os.environ[f"MLCC_THERMAL_{case}_PRODUCT"])


def _forbid(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("saved delivery must not recompute stress or parse native data")
    monkeypatch.setattr(domain, "thermal_stress_change", forbidden)
    monkeypatch.setattr(sources, "thermal_stress_change", forbidden)
    monkeypatch.setattr(local_tasks, "read_local_stress_task", forbidden)
    monkeypatch.setattr(thermal_tasks, "read_interface_thermal_task", forbidden)


@pytest.mark.parametrize("case", ["NI", "NI_BTO"])
def test_real_saved_product_keeps_missing_values_without_recomputation(case, monkeypatch):
    study_path, product_path = _paths(case)
    product = json.loads(product_path.read_text())
    _forbid(monkeypatch)
    result = deliver_thermal_stress(study_path, product_path)
    assert result["product"] == product
    assert result["responses"]["local_thermal_stress"] == product["response"]
    assert result["missing_evidence"] == product["missing_evidence"]
    assert result["artifacts"]["thermal-stress"] == str(product_path)
    assert result["status"] == "unresolved"


def test_saved_thermal_product_rejects_another_study(tmp_path, monkeypatch):
    study_path, product_path = _paths("NI")
    study = json.loads(study_path.read_text())
    study["study_id"] = "another-study"
    wrong = tmp_path / "wrong-study.json"
    wrong.write_text(json.dumps(study))
    _forbid(monkeypatch)
    with pytest.raises(ValueError, match="Study"):
        deliver_thermal_stress(wrong, product_path)


def test_saved_source_native_job_cannot_be_relabelled(tmp_path, monkeypatch):
    study_path, product_path = _paths("NI")
    product = json.loads(product_path.read_text())
    product["sources"][0]["native_job"]["scheduler_job_id"] = "another-native-job"
    wrong = tmp_path / "wrong-source.json"
    wrong.write_text(json.dumps(product))
    _forbid(monkeypatch)
    with pytest.raises(ValueError, match="source differs"):
        deliver_thermal_stress(study_path, wrong)
