from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc.grain_studies import bind_grain_boundary_study


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "workspace" / "reports" / "grain-boundary-v001" / "outputs-174" / "model"
PARENT_STUDY = ROOT / "workspace" / "configs" / "cases" / "ni-engineering-v001.json"
REQUEST = ROOT / "workspace" / "reports" / "grain-boundary-v001" / "request.json"


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_create_grain_boundary_cli_only_forwards_explicit_inputs(tmp_path, monkeypatch, capsys):
    from mlcc import cli
    import mlcc.grain_boundaries as grain_boundaries

    request = _write(tmp_path / "request.json", {"model_id": "child", "version": "v001"})
    captured = {}

    class DummyModel:
        model_id = "child"
        version = "v001"
        artifact_dir = tmp_path / "model"
        metadata = {"spatial_mode": "grain_boundary"}

    def fake_builder(parent, request_value, output):
        captured.update(parent=parent, request=request_value, output=output)
        return DummyModel()

    monkeypatch.setattr(grain_boundaries, "build_grain_boundary", fake_builder)
    assert cli.main(
        [
            "create-grain-boundary",
            "--parent",
            str(tmp_path / "parent"),
            "--request",
            str(request),
            "--output",
            str(tmp_path / "output"),
        ]
    ) == 0
    capsys.readouterr()
    assert captured == {
        "parent": tmp_path / "parent",
        "request": {"model_id": "child", "version": "v001"},
        "output": tmp_path / "output",
    }


def test_bind_grain_boundary_cli_only_forwards_explicit_inputs(tmp_path, monkeypatch, capsys):
    from mlcc import cli
    import mlcc.grain_studies as grain_studies

    captured = {}

    def fake_binder(parent_study, model, study_id, output):
        captured.update(
            parent_study=parent_study, model=model, study_id=study_id, output=output
        )
        return {"study_id": study_id, "status": "written"}

    monkeypatch.setattr(grain_studies, "bind_grain_boundary_study", fake_binder)
    assert cli.main(
        [
            "bind-grain-boundary-study",
            "--parent-study",
            str(tmp_path / "parent-study.json"),
            "--model",
            str(tmp_path / "model"),
            "--study-id",
            "child-study-v001",
            "--output",
            str(tmp_path / "child-study.json"),
        ]
    ) == 0
    capsys.readouterr()
    assert captured == {
        "parent_study": tmp_path / "parent-study.json",
        "model": tmp_path / "model",
        "study_id": "child-study-v001",
        "output": tmp_path / "child-study.json",
    }


def test_bind_job174_model_records_study_and_source_provenance(tmp_path):
    model_before = (MODEL / "model.json").read_bytes()
    output = tmp_path / "child-study.json"
    result = bind_grain_boundary_study(PARENT_STUDY, MODEL, "ni-gb-study-v001", output)
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert result["study_id"] == "ni-gb-study-v001"
    assert result["parent_study_id"] == "ni-engineering-qualification-v001"
    assert result["model"]["model_id"] == "ni-two-grain-engineering"
    assert result["model"]["version"] == "v001"
    assert result["model"]["fixture"] is True
    assert result["model"]["material"] == "Ni"
    assert result["grain_boundary"]["source_file"].endswith("grain-boundary.json")
    assert result["grain_boundary"]["atom_lineage_file"].endswith("atom-lineage.json")
    assert result["grain_boundary"]["charge_contract"]["charge_state"] == 0
    assert result["grain_boundary"]["phase_contract"]["status"] == "fixture_phase_label_difference_recorded"
    assert result["selected_required_tasks"] == []
    assert result["production_qualified"] is False
    assert (MODEL / "model.json").read_bytes() == model_before


def test_bind_rejects_parent_identity_mismatch(tmp_path):
    parent = json.loads(PARENT_STUDY.read_text(encoding="utf-8"))
    parent["model"]["model_id"] = "wrong-parent"
    parent_path = _write(tmp_path / "wrong-parent-study.json", parent)
    with pytest.raises(ValueError, match="parent Study model identity"):
        bind_grain_boundary_study(parent_path, MODEL, "ni-gb-study-v001", tmp_path / "child.json")
    assert not (tmp_path / "child.json").exists()
