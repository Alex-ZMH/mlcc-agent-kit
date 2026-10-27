from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mlcc.property_delivery import assess_design, deliver_electronic_properties


ROOT = Path(__file__).resolve().parents[2]
CZO_STUDY = ROOT / "workspace" / "configs" / "cases" / "cazro3-firing-v003.json"
CZO_TASK = ROOT / "workspace" / "tasks" / "p4-czo-compatibility-scf-v001"


def _observable(
    *,
    value: float = 4.0,
    uncertainty: float | None = 0.1,
    scientific_status: str = "qualified",
    conditions: dict | None = None,
    source_refs: list[str] | None = None,
) -> dict:
    return {
        "observable_id": "dielectric_test",
        "definition": "test scalar at the declared point",
        "object_level": "bulk_model_cell",
        "unit": "eV",
        "conditions": {"temperature_K": 0.0} if conditions is None else conditions,
        "value": value,
        "uncertainty": uncertainty,
        "scientific_status": scientific_status,
        "source_refs": ["task:test"] if source_refs is None else source_refs,
    }


def _requirement(**overrides: object) -> dict:
    requirement = {
        "requirement_id": "dielectric-limit",
        "observable_id": "dielectric_test",
        "definition": "test scalar at the declared point",
        "object_level": "bulk_model_cell",
        "unit": "eV",
        "conditions": {"temperature_K": 0.0},
        "comparison": "upper_bound",
        "upper_bound": 5.0,
        "required": True,
        "uncertainty_rule": "nominal",
    }
    requirement.update(overrides)
    return requirement


def _property(result: dict, observable_id: str) -> dict:
    return next(item for item in result["observables"] if item["observable_id"] == observable_id)


def test_no_targets_are_not_assessed() -> None:
    result = assess_design(None, [_observable()])
    assert result["design_assessment"] == "not_assessed"
    assert result["assessments"] == []


def test_upper_lower_interval_and_target_tolerance_comparisons() -> None:
    assert assess_design([_requirement()], [_observable(value=4.0, uncertainty=None)])[
        "design_assessment"
    ] == "met"
    assert assess_design(
        [_requirement(comparison="lower_bound", lower_bound=5.0, upper_bound=None)],
        [_observable(value=4.0, uncertainty=None)],
    )["design_assessment"] == "not_met"
    assert assess_design(
        [_requirement(comparison="interval", lower_bound=3.0, upper_bound=5.0)],
        [_observable(value=4.0, uncertainty=0.2)],
    )["design_assessment"] == "met"
    assert assess_design(
        [
            _requirement(
                comparison="target_with_tolerance",
                target=4.0,
                tolerance=0.5,
                upper_bound=None,
            )
        ],
        [_observable(value=4.4, uncertainty=None)],
    )["design_assessment"] == "met"


def test_whole_interval_crossing_boundary_is_insufficient_with_margin() -> None:
    result = assess_design(
        [_requirement(upper_bound=5.0, uncertainty_rule="whole_interval")],
        [_observable(value=4.95, uncertainty=0.1)],
    )
    item = result["assessments"][0]
    assert result["design_assessment"] == "insufficient_evidence"
    assert item["design_assessment"] == "insufficient_evidence"
    assert item["nominal_margin"] == pytest.approx(0.05)
    assert item["whole_interval_margin"] == pytest.approx(-0.05)
    assert "crosses" in item["reason"]


@pytest.mark.parametrize(
    "observable_update, requirement_update, reason",
    [
        ({"source_refs": []}, {}, "source_refs"),
        ({"scientific_status": "invalid", "value": 8.0, "uncertainty": None}, {}, "invalid"),
        ({"conditions": {"temperature_K": 300.0}}, {}, "conditions"),
        ({"value": None}, {}, "value"),
        ({"uncertainty": -0.1}, {}, "uncertainty"),
    ],
)
def test_missing_or_unqualified_evidence_cannot_prove_not_met(
    observable_update: dict, requirement_update: dict, reason: str
) -> None:
    observable = _observable()
    observable.update(observable_update)
    requirement = _requirement()
    requirement.update(requirement_update)
    result = assess_design([requirement], [observable])
    assert result["design_assessment"] == "insufficient_evidence"
    assert reason in result["assessments"][0]["reason"]


def test_metadata_and_conditions_are_exact_and_optional_targets_do_not_aggregate() -> None:
    required = _requirement(upper_bound=5.0)
    optional = _requirement(
        requirement_id="optional",
        upper_bound=2.0,
        required=False,
    )
    result = assess_design([required, optional], [_observable(value=4.0, uncertainty=None)])
    assert result["design_assessment"] == "met"
    assert result["summary"]["not_met"] == 1
    assert result["required_assessments"][0]["design_assessment"] == "met"

    mismatch = assess_design(
        [_requirement()],
        [_observable(conditions={"temperature_K": 350.0})],
    )
    assert mismatch["design_assessment"] == "insufficient_evidence"
    assert "metadata or conditions" in mismatch["assessments"][0]["reason"]


def test_missing_target_value_is_not_assessed() -> None:
    result = assess_design(
        [_requirement(comparison="interval", lower_bound=None, upper_bound=None)],
        [_observable()],
    )
    assert result["design_assessment"] == "not_assessed"
    assert result["assessments"][0]["design_assessment"] == "not_assessed"


def test_design_contract_requires_explicit_lists_and_fields() -> None:
    with pytest.raises(ValueError, match="requirements must be a list"):
        assess_design(_requirement(), [_observable()])
    with pytest.raises(ValueError, match="observables must be a list"):
        assess_design([_requirement()], _observable())
    missing_required = _requirement()
    del missing_required["required"]
    with pytest.raises(ValueError, match="required must be an explicit boolean"):
        assess_design([missing_required], [_observable()])
    missing_rule = _requirement()
    del missing_rule["uncertainty_rule"]
    with pytest.raises(ValueError, match="uncertainty_rule"):
        assess_design([missing_rule], [_observable()])
    inferred_comparison = _requirement()
    del inferred_comparison["comparison"]
    with pytest.raises(ValueError, match="comparison must be explicit"):
        assess_design([inferred_comparison], [_observable()])


def test_design_contract_rejects_aliases_invalid_metadata_and_ambiguous_matches() -> None:
    alias = _requirement()
    alias["observable"] = alias.pop("observable_id")
    with pytest.raises(ValueError, match="observable_id"):
        assess_design([alias], [_observable()])

    bad_definition = _requirement(definition="")
    with pytest.raises(ValueError, match="definition"):
        assess_design([bad_definition], [_observable()])

    duplicate = [_observable(value=4.0), _observable(value=4.1)]
    result = assess_design([_requirement()], duplicate)
    assert result["design_assessment"] == "insufficient_evidence"
    assert "ambiguous" in result["assessments"][0]["reason"]

    bad_source = _observable(source_refs=["", "task:other"])
    result = assess_design([_requirement()], [bad_source])
    assert result["design_assessment"] == "insufficient_evidence"
    assert "source_refs" in result["assessments"][0]["reason"]


@pytest.mark.parametrize(
    "field",
    [
        "lattice_temperature_K",
        "temperature_C",
        "temperature_K",
        "applied_external_pressure_Pa",
    ],
)
def test_static_delivery_rejects_nonzero_temperature_or_pressure(
    tmp_path: Path, field: str
) -> None:
    copied = tmp_path / CZO_TASK.name
    shutil.copytree(CZO_TASK, copied)
    result_path = copied / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["source_files"]["running_scf.log"] = str(copied / "OUT.CZOCompat" / "running_scf.log")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    task_path = copied / "task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["calculation_conditions"][field] = 700.0
    task_path.write_text(json.dumps(task), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        deliver_electronic_properties(CZO_STUDY, [copied])


def test_targets_require_explicit_matching_study_id_and_study_reference_requires_path(tmp_path: Path) -> None:
    study = json.loads(CZO_STUDY.read_text(encoding="utf-8"))
    study["design_requirements_ref"] = "targets.json"
    study_path = tmp_path / "study.json"
    study_path.write_text(json.dumps(study), encoding="utf-8")
    with pytest.raises(ValueError, match="targets_path"):
        deliver_electronic_properties(study_path, [CZO_TASK])

    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"requirements": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="study_id"):
        deliver_electronic_properties(CZO_STUDY, [CZO_TASK], targets_path)


def test_delivery_exposes_only_observable_list() -> None:
    result = deliver_electronic_properties(CZO_STUDY, [CZO_TASK])
    assert "observables" in result
    assert "properties" not in result


def test_native_czo_electronic_delivery_reads_job40_without_targets() -> None:
    result = deliver_electronic_properties(CZO_STUDY, [CZO_TASK])

    assert result["study_id"] == "cazro3_firing_validation_v003"
    assert result["scientific_status"] == "unqualified"
    assert result["design_assessment"] == "not_assessed"
    assert result["task_refs"][0]["scheduler_job_id"] == "40"
    assert result["task_refs"][0]["method_set"] == "cazro3-oncv-pbe-pw-nonsoc-capability-v002"
    assert result["static_0K_conditions"]["reference_temperature_K"] == 0

    gap = _property(result, "sampled_mesh_KS_gap")
    assert gap["value"] == pytest.approx(4.036775419048563)
    assert gap["unit"] == "eV"
    assert gap["uncertainty"] is None
    assert gap["scientific_status"] == "unqualified"
    assert f"scheduler_job:40" in gap["source_refs"]
    assert Path(gap["source_files"]["istate.info"]).parts[-2:] == ("OUT.CZOCompat", "istate.info")


def test_native_czo_target_in_range_stays_insufficient_without_precision_qualification(tmp_path: Path) -> None:
    baseline = deliver_electronic_properties(CZO_STUDY, [CZO_TASK])
    gap = _property(baseline, "sampled_mesh_KS_gap")
    targets = {
        "study_id": baseline["study_id"],
        "requirements": [
            {
                "requirement_id": "gap-target",
                "observable_id": gap["observable_id"],
                "definition": gap["definition"],
                "object_level": gap["object_level"],
                "unit": gap["unit"],
                "conditions": gap["conditions"],
                "comparison": "interval",
                "lower_bound": 4.0,
                "upper_bound": 4.1,
                "required": True,
                "uncertainty_rule": "nominal",
            }
        ],
    }
    target_path = tmp_path / "targets.json"
    target_path.write_text(json.dumps(targets), encoding="utf-8")

    result = deliver_electronic_properties(CZO_STUDY, [CZO_TASK], target_path)
    assert result["design_assessment"] == "insufficient_evidence"
    item = result["design_assessment_detail"]["assessments"][0]
    assert item["design_assessment"] == "insufficient_evidence"
    assert "not qualified" in item["reason"]


def test_delivery_binds_task_study_and_model(tmp_path: Path) -> None:
    copied = tmp_path / CZO_TASK.name
    shutil.copytree(CZO_TASK, copied)
    task_path = copied / "task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["study_id"] = "wrong-study"
    task_path.write_text(json.dumps(task), encoding="utf-8")
    result_path = copied / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["source_files"]["running_scf.log"] = str(copied / "OUT.CZOCompat" / "running_scf.log")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="study_id"):
        deliver_electronic_properties(CZO_STUDY, [copied])
