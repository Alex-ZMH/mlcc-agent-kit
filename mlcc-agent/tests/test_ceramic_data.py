"""Only the new ceramic adapter boundaries; real sources are jobs50/121."""
import copy
import json
import os
from pathlib import Path

import pytest

import mlcc.ceramic_data as ceramic


def request():
    return json.loads(Path(os.environ["MLCC_CERAMIC_REQUEST"]).read_text())


def test_real_inspection_preserves_systems_charge_and_parent_lineage():
    inspected = ceramic.inspect_ceramic_sources(request())
    host, defect = inspected["systems"]
    assert [len(row["model"].atoms) for row in (host, defect)] == [20, 19]
    assert [row["task"]["scheduler_job_id"] for row in (host, defect)] == ["50", "121"]
    assert inspected["type_map"] == ["Ca", "Zr", "O"]
    assert host["charge"]["fields"]["result"] == {"present": False, "value": None}
    assert defect["charge"]["fields"]["result"] == {"present": True, "value": 0}
    assert host["input_electrons"]["nelec"] == {"present": False, "value": None}
    assert defect["parent"]["deleted_atom_ids"] == [8]
    assert len(defect["parent"]["entries"]) == 19
    assert host["task"]["study_id"] != defect["task"]["study_id"]
    assert all(row["task"]["production_label"] is False for row in (host, defect))


@pytest.mark.parametrize("corruption, message", [
    ("types", "type_map"), ("split", "crosses train/validation"),
    ("parent_group", "parent must share"), ("parent_missing", "parent_models"),
    ("charge_file", "charge_source.file"), ("output_name", "directory name"),
])
def test_request_boundary_rejects_mixed_sources(corruption, message):
    value = request()
    if corruption == "types":
        value["type_map"].reverse()
    elif corruption == "split":
        value["systems"][1]["split"] = "validation"
    elif corruption == "parent_group":
        value["systems"][1]["source_group"] = "pretended-independent-group"
    elif corruption == "parent_missing":
        value["systems"][1]["parent_system_id"] = None
    elif corruption == "charge_file":
        value["systems"][1]["charge_source"]["file"] = value["systems"][0]["charge_source"]["file"]
    elif corruption == "output_name":
        value["systems"][1]["system_id"] = "../outside"
    with pytest.raises(ValueError, match=message):
        ceramic.inspect_ceramic_sources(value)


@pytest.mark.parametrize("corruption, exception, message", [
    ("charge_plus2", ValueError, "non-neutral"),
    ("charge_missing", KeyError, "net_charge"),
    ("job", ValueError, "bound to task"),
    ("method", ValueError, "native INPUT"),
    ("lineage", ValueError, "atom_lineage"),
])
def test_saved_record_corruption_rejected(monkeypatch, corruption, exception, message):
    original = ceramic._json

    def changed(path, label):
        value = original(path, label)
        if label == "host20 method.json" and corruption == "charge_plus2":
            value["net_charge"] = 2
        if label == "host20 method.json" and corruption == "charge_missing":
            del value["net_charge"]
        if label == "host20 result.json" and corruption == "job":
            value["scheduler_job_id"] = "wrong-job"
        if label == "vacancy19 method.json" and corruption == "method":
            value["parameters"]["ecutwfc_Ry"] = 110
        if label == "atom-lineage.json" and corruption == "lineage":
            value["entries"][0]["parent_atom_id"] = 1
        return value

    monkeypatch.setattr(ceramic, "_json", changed)
    with pytest.raises(exception, match=message):
        ceramic.inspect_ceramic_sources(request())


def test_conversion_keeps_original_error_and_does_not_write_acceptance(monkeypatch, tmp_path):
    error = RuntimeError("native converter original failure")

    def fail(source, output):
        raise error

    monkeypatch.setattr(ceramic, "convert_to_deepmd", fail)
    with pytest.raises(RuntimeError) as caught:
        ceramic.convert_ceramic_systems(request(), tmp_path / "data")
    assert caught.value is error
    assert not (tmp_path / "data" / "collection.json").exists()
