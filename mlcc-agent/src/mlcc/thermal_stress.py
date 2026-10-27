"""Direct comparison of saved local-stress states and explicit histories."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

import numpy as np


RESPONSE_SCHEMA = "mlcc.thermal-stress-response.v1"
STRESS_IDENTITY_FIELDS = (
    "study_id",
    "model_id",
    "model_version",
    "potential_id",
    "potential_version",
    "method_set",
    "source_atom_ids",
    "source_cell_angstrom",
    "contribution",
    "kinetic_included",
    "native_component_order",
)
REGION_FIELDS = ("region_id", "atom_ids", "volume_angstrom3", "volume_definition")
UNITS = {
    "stress": "GPa",
    "temperature": "K",
    "time": "ps",
    "volume": "angstrom^3",
}


def _matrix(value: Any, label: str) -> np.ndarray | None:
    if value is None:
        return None
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError(f"{label} must be a finite 3x3 stress_GPa tensor")
    return matrix


def _frame_keys(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    keys = state["frame_keys"]
    if keys is None:
        return []
    if not isinstance(keys, list):
        raise ValueError(f"state {state['state_id']} frame_keys must be a list")
    normalized: list[dict[str, Any]] = []
    for key in keys:
        if not isinstance(key, dict):
            raise ValueError(f"state {state['state_id']} frame_keys must contain objects")
        step = key["step"]
        time = float(key["physical_time_ps"])
        if type(step) is not int or not np.isfinite(time):
            raise ValueError(f"state {state['state_id']} frame_keys contain invalid step/time")
        normalized.append({"step": step, "physical_time_ps": time})
    if len({(item["step"], item["physical_time_ps"]) for item in normalized}) != len(normalized):
        raise ValueError(f"state {state['state_id']} frame_keys must be unique")
    return normalized


def _state_stress(state: Mapping[str, Any], label: str) -> np.ndarray | None:
    return _matrix(state.get("stress_GPa"), f"{label}.stress_GPa")


def _validate_region(region: Mapping[str, Any], label: str) -> None:
    volume = region.get("volume_angstrom3")
    if volume is None:
        return
    volume = float(volume)
    if not np.isfinite(volume) or volume <= 0.0:
        raise ValueError(f"{label} volume_angstrom3 must be positive and finite")


def _pair_missing(reference: Mapping[str, Any], state: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in STRESS_IDENTITY_FIELDS:
        if reference["identity"].get(key) is None:
            missing.append(f"reference:identity:{key}")
        if state["identity"].get(key) is None:
            missing.append(f"state:{state['state_id']}:identity:{key}")
    for key in REGION_FIELDS:
        if reference["region"].get(key) is None:
            missing.append(f"reference:region:{key}")
        if state["region"].get(key) is None:
            missing.append(f"state:{state['state_id']}:region:{key}")
    return missing


def _compare_identity(reference: Mapping[str, Any], state: Mapping[str, Any]) -> None:
    for key in STRESS_IDENTITY_FIELDS:
        left = reference["identity"][key]
        right = state["identity"][key]
        if left != right:
            raise ValueError(f"thermal stress identity {key} differs")
    for key in REGION_FIELDS:
        left = reference["region"][key]
        right = state["region"][key]
        if left != right:
            raise ValueError(f"thermal stress region {key} differs")


def _history_samples(
    state: Mapping[str, Any], history: Mapping[str, Any] | None, kind: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if history is None:
        return None, f"{kind}_history"
    samples = history["samples"]
    if samples is None:
        return None, f"{kind}_history.samples"
    if not isinstance(samples, list):
        raise ValueError(f"{kind} history samples must be a list")
    if not samples:
        return None, f"{kind}_history.samples"
    keys = _frame_keys(state)
    sample_keys: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError(f"{kind} history samples must contain objects")
        step = sample["step"]
        time = float(sample["physical_time_ps"])
        if type(step) is not int or not np.isfinite(time):
            raise ValueError(f"{kind} history sample has invalid step/time")
        sample_keys.append({"step": step, "physical_time_ps": time})
    if sample_keys != keys:
        raise ValueError(f"{kind} history frame keys differ from state frame_keys")
    source_files = history.get("source_files")
    if not isinstance(source_files, (dict, list)) or not source_files:
        return None, f"{kind}_history.source_files"

    region = state["region"]
    if history.get("region_id") is not None and region.get("region_id") is not None:
        if history["region_id"] != region["region_id"]:
            raise ValueError(f"{kind} history region_id differs from state")
    if history.get("atom_ids") is not None and region.get("atom_ids") is not None:
        if history["atom_ids"] != region["atom_ids"]:
            raise ValueError(f"{kind} history atom_ids differ from state")
    identity = state["identity"]
    for history_key, identity_key in (
        ("model_id", "model_id"),
        ("model_version", "model_version"),
    ):
        if history.get(history_key) is not None and identity.get(identity_key) is not None:
            if history[history_key] != identity[identity_key]:
                raise ValueError(f"{kind} history {history_key} differs from state")

    for sample in samples:
        if kind == "temperature":
            value = float(sample["temperature_K"])
            if not np.isfinite(value) or value < 0.0:
                raise ValueError("temperature history temperature_K must be finite and non-negative")
        else:
            constraint = sample["constraint"]
            if not isinstance(constraint, dict):
                raise ValueError("mechanical history constraint must be an object")
            cell = np.asarray(constraint["cell_angstrom"], dtype=float)
            if cell.shape != (3, 3) or not np.isfinite(cell).all():
                raise ValueError("mechanical history constraint cell_angstrom must be a finite 3x3 cell")
            source_cell = state["identity"].get("source_cell_angstrom")
            if source_cell is not None and not np.allclose(cell, np.asarray(source_cell, dtype=float), rtol=0.0, atol=1.0e-12):
                raise ValueError("mechanical history constraint cell differs from state source cell")
            constraint["boundary"]
            constraint["fixed_atom_ids"]
            loading = constraint["loading"]
            if not isinstance(loading, dict) or loading.get("kind") not in {"none", "declared"}:
                raise ValueError("mechanical history loading kind must be none or declared")
            if loading["kind"] == "declared":
                if not isinstance(loading.get("definition"), str) or not loading["definition"].strip():
                    raise ValueError("declared mechanical loading requires a definition")
                if not loading.get("parameters"):
                    raise ValueError("declared mechanical loading requires parameters")
    return copy.deepcopy(samples), None


def _same_constraints(
    reference_samples: list[dict[str, Any]], state_samples: list[dict[str, Any]],
) -> bool:
    constraints = [sample["constraint"] for sample in reference_samples + state_samples]
    return bool(constraints) and all(constraint == constraints[0] for constraint in constraints[1:])


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _raw_state(state: Mapping[str, Any]) -> dict[str, Any]:
    # Validate the mandatory normalized envelope before preserving it verbatim.
    state["state_id"]
    identity = state["identity"]
    region = state["region"]
    if not isinstance(identity, dict) or not isinstance(region, dict):
        raise ValueError("thermal stress state identity and region must be objects")
    _validate_region(region, f"state {state['state_id']}")
    _frame_keys(state)
    _state_stress(state, f"state {state['state_id']}")
    return copy.deepcopy(dict(state))


def thermal_stress_change(
    reference: Mapping[str, Any] | None,
    states: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare saved local-stress tensors against one explicit reference.

    ``reference`` and each state are already bound by the source adapter.  This
    function performs no file reads, temperature fitting, tensor rotation, or
    mechanical correction.
    """

    raw_reference = None if reference is None else _raw_state(reference)
    raw_states = [_raw_state(state) for state in states]
    missing: list[str] = []
    if raw_reference is None:
        missing.append("reference_state")
    else:
        missing.extend(list(raw_reference.get("missing_evidence", []) or []))
    if not raw_states:
        missing.append("states")

    reference_stress = None if reference is None else _state_stress(reference, "reference")
    if reference is not None:
        _validate_region(reference["region"], "reference")
        reference_temperature, reference_temperature_reason = _history_samples(
            reference, reference.get("temperature_history"), "temperature"
        )
        reference_mechanical, reference_mechanical_reason = _history_samples(
            reference, reference.get("mechanical_history"), "mechanical"
        )
    else:
        reference_temperature = None
        reference_temperature_reason = None
        reference_mechanical = None
        reference_mechanical_reason = None
    results: list[dict[str, Any]] = []
    ordinary_available = 0
    thermal_available = 0

    for state in states:
        state_id = state["state_id"]
        state_stress = _state_stress(state, f"state {state_id}")
        state_missing = list(state.get("missing_evidence", []) or [])
        if reference is not None:
            state_missing.extend(list(reference.get("missing_evidence", []) or []))
        stress_change: list[list[float]] | None = None
        thermal_change: list[list[float]] | None = None
        classification = "unresolved"
        reasons: list[str] = []
        state_temperature, state_temperature_reason = _history_samples(
            state, state.get("temperature_history"), "temperature"
        )
        state_mechanical, state_mechanical_reason = _history_samples(
            state, state.get("mechanical_history"), "mechanical"
        )
        if reference_temperature_reason is not None:
            reasons.append(f"reference {reference_temperature_reason}")
        if reference_mechanical_reason is not None:
            reasons.append(f"reference {reference_mechanical_reason}")
        if state_temperature_reason is not None:
            reasons.append(f"state {state_temperature_reason}")
        if state_mechanical_reason is not None:
            reasons.append(f"state {state_mechanical_reason}")

        if reference is None:
            reasons.append("reference state is missing")
        elif reference_stress is None:
            reasons.append("reference stress_GPa is missing")
        elif state_stress is None:
            reasons.append("state stress_GPa is missing")
        else:
            pair_missing = _pair_missing(reference, state)
            if pair_missing:
                reasons.extend(pair_missing)
            else:
                _compare_identity(reference, state)
                stress_change = (state_stress - reference_stress).tolist()
                ordinary_available += 1
                classification = "stress_change_without_history"

            if stress_change is not None:
                if reference_mechanical is not None and state_mechanical is not None:
                    if _same_constraints(reference_mechanical, state_mechanical):
                        if reference_temperature is not None and state_temperature is not None:
                            thermal_change = copy.deepcopy(stress_change)
                            classification = "same_constraint_thermal_stress_change"
                            thermal_available += 1
                        else:
                            classification = "stress_change_without_history"
                    else:
                        classification = "mixed_thermal_mechanical_change"
                        reasons.append("mechanical constraint or loading history differs")
                else:
                    classification = "stress_change_without_history"

        if state_stress is None:
            state_missing.append(f"state:{state_id}:stress_GPa")
        if reference is not None and reference_stress is None:
            state_missing.append("reference:stress_GPa")
        if reference is not None and reference["region"].get("volume_angstrom3") is None:
            state_missing.append("reference:volume_angstrom3")
        if state["region"].get("volume_angstrom3") is None:
            state_missing.append(f"state:{state_id}:volume_angstrom3")
        state_missing.extend(reasons)
        state_result = {
            "state_id": state_id,
            "state": copy.deepcopy(dict(state)),
            "reference_state_id": None if reference is None else reference["state_id"],
            "reference": None if reference is None else copy.deepcopy(dict(reference)),
            "identity": copy.deepcopy(state["identity"]),
            "region": copy.deepcopy(state["region"]),
            "frame_keys": copy.deepcopy(state["frame_keys"]),
            "temperature_history": copy.deepcopy(state.get("temperature_history")),
            "mechanical_history": copy.deepcopy(state.get("mechanical_history")),
            "stress_change_GPa": stress_change,
            "thermal_stress_change_GPa": thermal_change,
            "classification": classification,
            "missing_evidence": _unique(state_missing),
            "source_refs": copy.deepcopy(state.get("source_refs")),
        }
        results.append(state_result)
        missing.extend(state_result["missing_evidence"])

    if ordinary_available == 0:
        status = "unresolved"
    elif ordinary_available < len(states) or thermal_available < ordinary_available:
        status = "partial"
    else:
        status = "available"

    limitations = [
        "same_constraint_thermal_stress_change is an observed difference under the recorded thermal history, not proof of temperature-only causation",
        "thermal_stress_change_GPa is not an equilibrium thermal-stress coefficient",
        "no interpolation, tensor symmetrization, component compression, or mechanical correction is performed",
    ]
    return {
        "schema": RESPONSE_SCHEMA,
        "status": status,
        "production_qualified": False,
        "reference": raw_reference,
        "states": results,
        "missing_evidence": _unique(missing),
        "definition": "explicit saved source-Cartesian tension-positive stress difference against a bound reference",
        "limitations": limitations,
        "units": dict(UNITS),
    }


__all__ = ["thermal_stress_change"]
