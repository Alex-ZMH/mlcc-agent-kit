"""Focused tests for the active v002 study temperature contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from mlcc.studies import (
    ISOTHERMAL_MD,
    STATIC_DFT_REFERENCE,
    calculation_conditions,
    load_study,
    planned_temperature_points,
    study_summary,
)


ROOT = Path(__file__).resolve().parents[2]
STUDY_PATH = ROOT / "workspace/configs/cases/cazro3-firing-v002.json"


def _study() -> dict:
    return load_study(STUDY_PATH)


def test_planned_points_use_explicit_pilot_endpoints_and_kelvin_mapping():
    points = planned_temperature_points(_study())

    assert [point["temperature_C"] for point in points] == [500.0, 400.0, 580.0, 450.0, 550.0]
    assert [point["temperature_K"] for point in points] == [773.15, 673.15, 853.15, 723.15, 823.15]
    assert [point["role"] for point in points] == ["pilot", "endpoint", "endpoint", "grid", "grid"]
    assert [point["order"] for point in points] == [1, 2, 3, 4, 5]
    assert all(point["temperature_K"] == pytest.approx(point["temperature_C"] + 273.15) for point in points)


def test_planned_points_preserve_configured_endpoint_and_pilot_order():
    study = deepcopy(_study())
    study["temperature_protocol"]["execution_order_C"] = [500, 450, 400, 580, 550]

    points = planned_temperature_points(study)
    assert [point["temperature_C"] for point in points] == [500.0, 450.0, 400.0, 580.0, 550.0]
    assert [point["role"] for point in points] == ["pilot", "grid", "endpoint", "endpoint", "grid"]


def test_static_reference_is_zero_kelvin_reference_without_firing_temperature():
    conditions = calculation_conditions(_study(), STATIC_DFT_REFERENCE)

    assert conditions["calculation_kind"] == STATIC_DFT_REFERENCE
    assert conditions["temperature_C"] is None
    assert conditions["temperature_K"] is None
    assert conditions["lattice_temperature_K"] is None
    assert conditions["reference_temperature_K"] == 0.0
    assert conditions["target_external_pressure_Pa"] == 101325
    assert conditions["applied_external_pressure_Pa"] is None
    assert "mechanical_pressure_Pa" not in conditions
    assert conditions["role"] == STATIC_DFT_REFERENCE
    assert conditions["design_assessment"] == "not_assessed"
    assert conditions["thermal_history"] is None
    assert "smearing_temperature_K" not in conditions
    with pytest.raises(ValueError, match="does not accept"):
        calculation_conditions(_study(), STATIC_DFT_REFERENCE, temperature_C=500)


def test_md_requires_selected_grid_point_and_reports_pressure_and_units():
    conditions = calculation_conditions(_study(), ISOTHERMAL_MD, temperature_C=500)

    assert conditions["calculation_kind"] == ISOTHERMAL_MD
    assert conditions["temperature_C"] == 500.0
    assert conditions["temperature_K"] == pytest.approx(773.15)
    assert conditions["lattice_temperature_K"] == pytest.approx(773.15)
    assert conditions["mechanical_pressure_Pa"] == 101325
    assert conditions["mechanical_pressure_GPa"] == pytest.approx(0.000101325)
    assert conditions["role"] == "firing_process_material_response"
    assert conditions["service_temperature_K"] is None
    assert conditions["measurement_temperature_K"] is None
    assert conditions["thermal_history"] is None
    assert conditions["design_assessment"] == "not_assessed"

    with pytest.raises(ValueError, match="requires an explicit"):
        calculation_conditions(_study(), ISOTHERMAL_MD)
    with pytest.raises(ValueError, match="grid points"):
        calculation_conditions(_study(), ISOTHERMAL_MD, temperature_C=401)


def test_unknown_pressure_remains_null_and_planning_example_is_not_execution_input():
    study = deepcopy(_study())
    study["model"].pop("pressure_Pa")
    study["model"].pop("pressure_GPa")
    conditions = calculation_conditions(study, ISOTHERMAL_MD, temperature_C=400)
    assert conditions["mechanical_pressure_Pa"] is None
    assert conditions["mechanical_pressure_GPa"] is None

    planning_example = load_study(ROOT / "configs/cases/cazro3.validation-plan.v002.json")
    with pytest.raises(KeyError):
        planned_temperature_points(planning_example)


def test_pressure_conversion_and_explicit_thermal_history_are_checked_and_retained():
    study = deepcopy(_study())
    study["temperature_protocol"]["thermal_history"] = {"source": "user", "steps": []}
    assert calculation_conditions(study, ISOTHERMAL_MD, temperature_C=400)["thermal_history"] == {
        "source": "user",
        "steps": [],
    }

    study["model"]["pressure_GPa"] = 0.0002
    with pytest.raises(ValueError, match="pressure"):
        calculation_conditions(study, ISOTHERMAL_MD, temperature_C=400)


def test_study_summary_keeps_identity_and_reports_missing_inputs_without_assessing_design():
    summary = study_summary(_study())

    assert summary["study_id"] == "cazro3_firing_validation_v002"
    assert summary["case_id"] == "cazro3_pnma_undoped"
    assert summary["case_role"] == "scientific_validation"
    assert summary["selected_purposes"] == ["normal"]
    assert summary["selected_scenarios"] == ["nominal"]
    assert summary["selected_required_tasks"] == ["CZO-P4-RELAX-001", "CZO-P4-BASE-002"]
    assert summary["design_requirements_ref"] is None
    assert summary["missing_scientific_inputs"] == ["source_structure"]
    assert summary["design_assessment"] == "not_assessed"
    assert len(summary["temperature_points"]) == 5
    assert summary["static_reference_conditions"]["reference_temperature_K"] == 0.0

    with_spec = deepcopy(_study())
    with_spec["design_requirements_ref"] = "configs/design-targets.example.json"
    assert study_summary(with_spec)["design_assessment"] == "insufficient_evidence"
