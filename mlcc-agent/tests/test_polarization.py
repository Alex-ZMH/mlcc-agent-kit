"""Focused checks for the declared-branch polarization path adapter.

Native-result checks use the existing v100 Berry58/SCF50 evidence through
``MLCC_POLARIZATION_REQUEST``.  No test creates a fake native result or runs a
solver; the pure branch test is algebra only.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

import mlcc.polarization as polarization
from mlcc.polarization import _branch_algebra, analyze_polarization_path


def _request_path() -> Path:
    path = Path(os.environ["MLCC_POLARIZATION_REQUEST"])
    assert path.is_file(), f"real v100 polarization request is required: {path}"
    return path


def _request_record() -> dict[str, object]:
    return json.loads(_request_path().read_text(encoding="utf-8"))


def _write_request(tmp_path: Path, record: dict[str, object]) -> Path:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def test_branch_algebra_declared_integer_values_and_delta():
    unwrapped, delta = _branch_algebra([0.4, -0.4], [1.0, 1.0], [0, 1], ["reference", "declared"])
    assert unwrapped == [0.4, 0.6]
    assert delta == pytest.approx(0.2)


def test_branch_algebra_missing_basis_or_integer_is_unresolved():
    assert _branch_algebra([0.4, -0.4], [1.0, 1.0], [0, None], ["reference", ""])[0] is None
    assert _branch_algebra([0.4, -0.4], [1.0, 1.0], [0, 1], ["reference", None]) == (None, None)


def test_branch_algebra_rejects_non_integer_branch():
    with pytest.raises(ValueError, match="branch_integer"):
        _branch_algebra([0.4], [1.0], [0.5], ["declared"])
    with pytest.raises(ValueError, match="branch_integer"):
        _branch_algebra([0.4], [1.0], [True], ["declared"])


def test_branch_algebra_common_branch_shift_preserves_delta():
    # Pure mathematical gauge identity, not a physical path or native result.
    unwrapped, delta = _branch_algebra([0.4, -0.4], [1.0, 1.0], [3, 4], ["declared", "declared"])
    assert unwrapped == pytest.approx([3.4, 3.6])
    assert delta == pytest.approx(0.2)


@pytest.mark.parametrize("quanta", [[0.0, 0.0], [-1.0, -1.0], [1.0, 2.0]])
def test_branch_algebra_rejects_invalid_fixed_cell_quantum_even_without_branches(quanta):
    with pytest.raises(ValueError, match="quantum"):
        _branch_algebra([0.4, -0.4], quanta, [None, None], [None, None])


@pytest.mark.parametrize("corruption, message", [
    ("unit", "units"), ("direction", "direction"),
    ("engine", "engine/version"), ("native_source", "source_files"),
])
def test_saved_result_corruption_is_rejected(monkeypatch, corruption, message):
    # Change only an in-memory copy of the real result for negative testing.
    # No fake native positive example or change to the evidence files.
    original_json = polarization._json

    def read_with_corrupted_result(path, label):
        record = original_json(path, label)
        if label == "result":
            if corruption == "unit":
                record["polarization_rows"]["c_per_m2"]["native_unit"] = "e/bohr^2"
            elif corruption == "direction":
                record["direction_lattice_vector_angstrom"] = [0.0, 1.0, 0.0]
            elif corruption == "engine":
                record["engine_version"] = "wrong-version"
            elif corruption == "native_source":
                record["source_files"]["native_INPUT"] = record["source_files"]["INPUT"]
        return record

    monkeypatch.setattr(polarization, "_json", read_with_corrupted_result)
    with pytest.raises(ValueError, match=message):
        analyze_polarization_path(_request_path())


def test_real_single_reference_preserves_unqualified_status_and_sources():
    result = analyze_polarization_path(_request_path())
    assert result["schema"] == "mlcc.polarization-path.v1"
    assert result["status"] == "unresolved_insufficient_path"
    assert result["delta_P_C_per_m2"] is None
    assert result["gdir"] == 1
    assert result["unit"] == "C/m^2"
    assert result["qualification"] == {
        "branch_continuity_qualified": False,
        "insulating_path_qualified": False,
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }
    assert len(result["points"]) == 1
    point = result["points"][0]
    assert point["native_job"]["scheduler_job_id"] == "58"
    assert point["scf_job"]["scheduler_job_id"] == "50"
    assert point["scf_job"]["task_id"] == "p5-czo-berry-scf-v001"
    assert point["polarization"]["representative_P_C_per_m2"] == pytest.approx(4.8e-6)
    assert point["polarization"]["quantum_Q_C_per_m2"] == pytest.approx(0.6943717)
    assert point["polarization"]["branch_integer"] is None
    assert point["polarization"]["unwrapped_P_C_per_m2"] is None
    assert point["qualification"]["native_completed"] is True
    assert point["qualification"]["reference_scf_converged"] is True
    assert point["qualification"]["scientific_qualification"] is False
    assert point["qualification"]["production_qualification"] is False
    for key in ("INPUT", "native_INPUT", "KPT", "STRU", "STRU.atom-map.json", "method.json", "running_nscf.log"):
        assert Path(point["source"]["source_files"][key]).is_file()


def test_real_request_rejects_study_mismatch(tmp_path: Path):
    record = _request_record()
    record["study_id"] = "wrong-study"
    with pytest.raises(ValueError, match="study"):
        analyze_polarization_path(_write_request(tmp_path, record))


def test_real_request_rejects_gdir_mismatch(tmp_path: Path):
    record = _request_record()
    record["gdir"] = 2
    with pytest.raises(ValueError, match="gdir"):
        analyze_polarization_path(_write_request(tmp_path, record))


def test_real_request_rejects_duplicate_path_point(tmp_path: Path):
    record = _request_record()
    first = copy.deepcopy(record["points"][0])
    first["point_id"] = "duplicate"
    first["path_coordinate"] = 1.0
    first["parent_point_id"] = record["points"][0]["point_id"]
    record["points"] = [record["points"][0], first]
    with pytest.raises(ValueError, match="result_file|task IDs|scheduler jobs"):
        analyze_polarization_path(_write_request(tmp_path, record))


def test_real_request_rejects_non_integer_branch(tmp_path: Path):
    record = _request_record()
    record["points"][0]["branch_integer"] = 0.5
    record["points"][0]["branch_basis"] = "test mutation"
    with pytest.raises(ValueError, match="branch_integer"):
        analyze_polarization_path(_write_request(tmp_path, record))


@pytest.mark.parametrize("field, value", [("branch_status", "unwrapped"), ("branch_unwrapped", True)])
def test_boundary_rejects_pre_unwrapped_native_branch(monkeypatch, field, value):
    original_json = polarization._json

    def read_with_corrupted_branch(path, label):
        record = original_json(path, label)
        if label == "result":
            record[field] = value
        return record

    monkeypatch.setattr(polarization, "_json", read_with_corrupted_branch)
    with pytest.raises(ValueError, match="branch"):
        analyze_polarization_path(_request_path())


@pytest.mark.parametrize("target", ["reference_task", "validation"])
def test_boundary_rejects_reference_model_path_mismatch(monkeypatch, target):
    original_json = polarization._json

    def read_with_corrupted_model_path(path, label):
        record = original_json(path, label)
        if target == "reference_task" and label == "reference SCF task":
            record["model_path"] = str(Path(record["model_path"]).parent)
        if target == "validation" and label == "result":
            validation = record["reference_scf_validation"]
            validation["model_path"] = str(Path(validation["model_path"]).parent)
        return record

    monkeypatch.setattr(polarization, "_json", read_with_corrupted_model_path)
    with pytest.raises(ValueError, match="model_path|model"):
        analyze_polarization_path(_request_path())


@pytest.mark.parametrize("field", ["case_id", "case_role", "fixture"])
def test_boundary_rejects_reference_scf_case_mismatch(monkeypatch, field):
    original_json = polarization._json

    def read_with_corrupted_reference_case(path, label):
        record = original_json(path, label)
        if label == "reference SCF task":
            record[field] = (not record[field]) if field == "fixture" else f"wrong-{field}"
        return record

    monkeypatch.setattr(polarization, "_json", read_with_corrupted_reference_case)
    with pytest.raises(ValueError, match="case"):
        analyze_polarization_path(_request_path())


def _task_case(task: dict[str, object]) -> dict[str, object]:
    return {field: task[field] for field in ("case_id", "case_role", "fixture")}


@pytest.mark.parametrize("field", ["case_id", "case_role", "fixture"])
def test_boundary_rejects_cross_point_case_mismatch(field):
    request = _request_record()
    point = request["points"][0]
    task = json.loads(Path(point["task_file"]).read_text(encoding="utf-8"))
    wrong_case = _task_case(task)
    wrong_case[field] = (not wrong_case[field]) if field == "fixture" else f"wrong-{field}"
    with pytest.raises(ValueError, match="case"):
        polarization._point_record(point, request=request, previous={"case": wrong_case})


def test_boundary_real_single_reference_exposes_case_path_and_branch_fields():
    request = _request_record()
    point_request = request["points"][0]
    task_path = Path(point_request["task_file"]).resolve()
    result_path = Path(point_request["result_file"]).resolve()
    task = json.loads(task_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    reference_task_path = Path(result["reference_scf_validation"]["task_file"]).resolve()
    reference_task = json.loads(reference_task_path.read_text(encoding="utf-8"))
    output = analyze_polarization_path(_request_path())
    point = output["points"][0]
    assert point["case"] == _task_case(task)
    assert point["source"]["task_file"] == str(task_path)
    assert point["source"]["result_file"] == str(result_path)
    assert point["polarization"]["branch_integer"] is None
    assert point["polarization"]["branch_basis"] is None
    assert point["polarization"]["unwrapped_P_C_per_m2"] is None
    assert point["scf_job"]["case_id"] == reference_task["case_id"]
    assert point["scf_job"]["case_role"] == reference_task["case_role"]
    assert point["scf_job"]["fixture"] == reference_task["fixture"]
    assert point["scf_job"]["model_path"] == str(Path(task["model_path"]).resolve())
    assert point["scf_job"]["model_path"] == str(Path(result["reference_scf_validation"]["model_path"]).resolve())
    assert point["polarization"]["source_branch_status"] == "not_unwrapped"
    assert point["polarization"]["source_branch_unwrapped"] is False
    assert output["status"] == "unresolved_insufficient_path"
    assert output["delta_P_C_per_m2"] is None
