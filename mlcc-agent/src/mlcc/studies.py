"""Direct temperature-condition helpers for active MLCC execution studies."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping


Study = Mapping[str, Any]
KELVIN_OFFSET = 273.15
STATIC_DFT_REFERENCE = "static_dft_reference"
ISOTHERMAL_MD = "isothermal_md"


def load_study(path: str | Path) -> dict[str, Any]:
    """Load one active execution-study JSON document without rewriting it."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def _temperature_plan(study: Study) -> tuple[list[float], dict[float, float], float, list[float]]:
    model = study["model"]
    protocol = study["temperature_protocol"]
    grid_C = [float(value) for value in protocol["grid_C"]]
    model_K = [float(value) for value in model["temperature_K"]]
    order_C = [float(value) for value in protocol["execution_order_C"]]
    if not grid_C or len(grid_C) != len(model_K) or len(set(grid_C)) != len(grid_C):
        raise ValueError("study temperature grid must contain unique C/K pairs")
    if any(not math.isfinite(value) for value in [*grid_C, *model_K, *order_C]):
        raise ValueError("study temperature values must be finite")
    if any(abs(celsius + KELVIN_OFFSET - kelvin) > 1e-9 for celsius, kelvin in zip(grid_C, model_K)):
        raise ValueError("study temperature_K must equal temperature_C + 273.15")
    range_C = model.get("temperature_range_C")
    if range_C is not None and any(value < float(range_C[0]) or value > float(range_C[1]) for value in grid_C):
        raise ValueError("study temperature grid lies outside its declared C range")
    if set(order_C) != set(grid_C) or len(order_C) != len(grid_C):
        raise ValueError("study execution_order_C must contain each grid point once")
    pilot_C = float(protocol["pilot_C"])
    if pilot_C not in grid_C:
        raise ValueError("study pilot_C must be one of its grid points")
    range_K = model.get("temperature_range_K")
    if range_K is not None and any(value < float(range_K[0]) or value > float(range_K[1]) for value in model_K):
        raise ValueError("study temperature grid lies outside its declared K range")
    return grid_C, dict(zip(grid_C, model_K)), pilot_C, order_C


def planned_temperature_points(study: Study) -> list[dict[str, Any]]:
    """Return the selected firing grid in its explicit pilot/endpoints order."""

    _, kelvin_by_C, pilot_C, order_C = _temperature_plan(study)
    endpoints = {min(kelvin_by_C), max(kelvin_by_C)}
    points: list[dict[str, Any]] = []
    for order, temperature_C in enumerate(order_C, start=1):
        role = "pilot" if temperature_C == pilot_C else "endpoint" if temperature_C in endpoints else "grid"
        points.append({"order": order, "temperature_C": temperature_C, "temperature_K": kelvin_by_C[temperature_C], "role": role})
    return points


def calculation_conditions(
    study: Study,
    calculation_kind: str,
    temperature_C: float | None = None,
) -> dict[str, Any]:
    """Build explicit conditions for the two currently supported calculations."""

    if calculation_kind not in {STATIC_DFT_REFERENCE, ISOTHERMAL_MD}:
        raise ValueError(f"unsupported calculation kind: {calculation_kind}")
    model = study["model"]
    protocol = study["temperature_protocol"]
    pressure_pa = model.get("pressure_Pa")
    pressure_gpa = model.get("pressure_GPa")
    if pressure_pa is not None and pressure_gpa is not None and not math.isclose(
        float(pressure_pa), float(pressure_gpa) * 1e9, rel_tol=1e-9, abs_tol=1e-3
    ):
        raise ValueError("study pressure_Pa and pressure_GPa do not match")
    if "thermal_history" in protocol:
        thermal_history = protocol["thermal_history"]
    else:
        thermal_history = study.get("thermal_history")
    conditions: dict[str, Any] = {
        "calculation_kind": calculation_kind,
        "mechanical_pressure_Pa": pressure_pa,
        "mechanical_pressure_GPa": pressure_gpa,
        "service_temperature_K": protocol.get("service_temperature_K"),
        "measurement_temperature_K": protocol.get("measurement_temperature_K"),
        "stress_free_reference_temperature_K": protocol.get("stress_free_reference_temperature_K"),
        "thermal_history": thermal_history,
        "design_assessment": "not_assessed" if study.get("design_requirements_ref") is None else "insufficient_evidence",
    }
    if calculation_kind == STATIC_DFT_REFERENCE:
        if temperature_C is not None:
            raise ValueError("static_dft_reference does not accept a firing temperature")
        conditions.update(
            temperature_C=None,
            temperature_K=None,
            lattice_temperature_K=None,
            reference_temperature_K=0.0,
            role="static_dft_reference",
            target_external_pressure_Pa=conditions.pop("mechanical_pressure_Pa"),
            target_external_pressure_GPa=conditions.pop("mechanical_pressure_GPa"),
            applied_external_pressure_Pa=None,
        )
        return conditions

    if temperature_C is None:
        raise ValueError("isothermal_md requires an explicit study grid temperature_C")
    selected_C = float(temperature_C)
    points = planned_temperature_points(study)
    selected = next((point for point in points if point["temperature_C"] == selected_C), None)
    if selected is None:
        raise ValueError("isothermal_md temperature_C must be one of the study grid points")
    conditions.update(
        temperature_C=selected["temperature_C"],
        temperature_K=selected["temperature_K"],
        lattice_temperature_K=selected["temperature_K"],
        reference_temperature_K=None,
        role="firing_process_material_response",
    )
    return conditions


def study_summary(study: Study) -> dict[str, Any]:
    """Return the explicit study identity and current temperature contract."""

    model = study.get("model", {})
    design_requirements_ref = study.get("design_requirements_ref")
    return {
        "study_id": study.get("study_id"),
        "case_id": study.get("case_id"),
        "case_role": study.get("case_role"),
        "selected_purposes": study.get("selected_purposes"),
        "selected_scenarios": study.get("selected_scenarios"),
        "selected_required_tasks": study.get("selected_required_tasks"),
        "design_requirements_ref": design_requirements_ref,
        "temperature_points": planned_temperature_points(study),
        "static_reference_conditions": calculation_conditions(study, STATIC_DFT_REFERENCE),
        "missing_scientific_inputs": [
            name
            for name, value in (
                ("phase_requested", model.get("phase_requested")),
                ("source_structure", model.get("source_structure")),
                ("pressure_Pa", model.get("pressure_Pa")),
            )
            if value is None
        ],
        "design_assessment": "insufficient_evidence" if design_requirements_ref is not None else "not_assessed",
    }
