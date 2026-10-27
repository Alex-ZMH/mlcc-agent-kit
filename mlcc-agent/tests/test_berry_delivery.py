"""Read-only public delivery checks for the real CZO Berry 58/50 evidence.

These tests deliberately use the native task and reference paths supplied by
the v100 run.  They never copy a charge-density cube and never call the
parser entry point that writes ``result.json``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import mlcc.property_delivery as property_delivery
from mlcc.property_delivery import deliver_berry_polarization


ROOT = Path(__file__).resolve().parents[2]
_LOCAL_NATIVE = ROOT / "workspace" / "reports" / "berry-v001" / "focused-65" / "entrypoints" / "parsed-native-nscf"


def _native_context() -> tuple[Path, Path, Path]:
    configured = os.environ.get("MLCC_BERRY_NATIVE_TASK")
    task_directory = Path(configured).expanduser() if configured else _LOCAL_NATIVE
    task_file = task_directory / "task.json"
    if not task_file.is_file():
        pytest.skip(f"real v100 Berry NSCF task is required: {task_directory}")
    task = json.loads(task_file.read_text(encoding="utf-8"))
    reference_file = Path(task["berry"]["source_reference_task_file"])
    if not reference_file.is_file():
        pytest.skip(f"real v100 Berry reference job50 is required: {reference_file}")
    study_file = Path(os.environ.get("MLCC_BERRY_STUDY", task["study_file"])).expanduser()
    if not study_file.is_file():
        pytest.skip(f"matching CZO Study is required: {study_file}")
    return task_directory, study_file, reference_file


def test_deliver_real_berry_58_with_reference_50_without_writing_native_task() -> None:
    task_directory, study_file, _reference_file = _native_context()
    task_json = task_directory / "task.json"
    result_json = task_directory / "result.json"
    before = task_json.read_bytes()
    before_result = result_json.read_bytes() if result_json.is_file() else None

    result = deliver_berry_polarization(study_file, task_directory)

    assert result["schema"] == "mlcc.berry-polarization-delivery.v001"
    assert result["study_id"] == "cazro3_firing_validation_v003"
    assert result["native_jobs"]["nscf"]["scheduler_job_id"] == "58"
    assert result["native_jobs"]["reference_scf"]["scheduler_job_id"] == "50"
    assert result["native_compatibility_evidence"]["device"] == "cpu"
    assert result["gdir"] == 1
    assert result["polarization"]["representative_P_C_per_m2"] == pytest.approx(4.8e-6)
    assert result["polarization"]["quantum_Q_C_per_m2"] == pytest.approx(0.6943717)
    assert result["polarization"]["branch_status"] == "not_unwrapped"
    assert result["scope"]["complete_3d_polarization"] is False
    assert result["uncomputed"]["dielectric_tensor"] is None
    assert result["design_assessment"] == "not_assessed"
    assert task_json.read_bytes() == before
    if before_result is not None:
        assert result_json.read_bytes() == before_result


def test_berry_delivery_rejects_wrong_study_without_copying_charge_density(tmp_path: Path) -> None:
    task_directory, study_file, _reference_file = _native_context()
    study = json.loads(study_file.read_text(encoding="utf-8"))
    study["study_id"] = "wrong-study"
    wrong_study = tmp_path / "wrong-study.json"
    wrong_study.write_text(json.dumps(study), encoding="utf-8")

    with pytest.raises(ValueError, match="Study|study_id"):
        deliver_berry_polarization(wrong_study, task_directory)


def test_berry_delivery_rejects_method_identity_in_shadow_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_directory, study_file, _reference_file = _native_context()
    task = json.loads((task_directory / "task.json").read_text(encoding="utf-8"))
    method = json.loads((task_directory / "method.json").read_text(encoding="utf-8"))
    method["method_set"] = "wrong-method"
    shadow = tmp_path / "shadow-berry"
    shadow.mkdir()
    (shadow / "task.json").write_text(json.dumps(task), encoding="utf-8")
    (shadow / "method.json").write_text(json.dumps(method), encoding="utf-8")
    native = {
        "model_id": task["model_id"],
        "model_version": task["model_version"],
        "method_set": task["method_set"],
        "gdir": 1,
        "reference_scf_validation": {"task_file": task["berry"]["source_reference_task_file"]},
    }
    monkeypatch.setattr(property_delivery, "read_berry_task", lambda _path: native)

    with pytest.raises(ValueError, match="method_set"):
        deliver_berry_polarization(study_file, shadow)


def test_real_berry_58_with_explicit_task_conditions_stays_insufficient_without_qualification(
    tmp_path: Path,
) -> None:
    task_directory, study_file, _reference_file = _native_context()
    task = json.loads((task_directory / "task.json").read_text(encoding="utf-8"))
    baseline = deliver_berry_polarization(study_file, task_directory)
    observable = baseline["observables"][0]
    targets = {
        "study_id": baseline["study_id"],
        "requirements": [
            {
                "requirement_id": "berry-single-direction-engineering-target",
                "observable_id": observable["observable_id"],
                "definition": observable["definition"],
                "object_level": observable["object_level"],
                "unit": observable["unit"],
                "conditions": dict(task["calculation_conditions"]),
                "comparison": "target_with_tolerance",
                "target": observable["value"],
                "tolerance": 1.0,
                "required": True,
                "uncertainty_rule": "nominal",
            }
        ],
    }
    target_path = tmp_path / "targets.json"
    target_path.write_text(json.dumps(targets), encoding="utf-8")

    result = deliver_berry_polarization(study_file, task_directory, target_path)

    assert result["observables"][0]["conditions"] == task["calculation_conditions"]
    assert result["design_assessment"] == "insufficient_evidence"
    assert result["design_assessment_detail"]["assessments"][0]["design_assessment"] == "insufficient_evidence"
    assert "not qualified" in result["design_assessment_detail"]["assessments"][0]["reason"]

