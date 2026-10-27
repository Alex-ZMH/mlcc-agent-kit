"""Convert saved native NPT bulk-thermal frames to domain properties.

This module consumes the already-saved bulk-thermal source envelope.  It does
not parse a LAMMPS trajectory or recompute the native frame data.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from typing import Any

from scipy.constants import Avogadro, elementary_charge

from .domain_parameters import domain_parameter_product


REQUEST_SCHEMA = "mlcc.bulk-thermal-response-request.v1"
SOURCE_SCHEMA = "mlcc.md-bulk-thermal-source.v1"
DOMAIN_KIND = "bulk_thermal_response"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_path(value: str | Path, owner: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = owner.parent / path
    return path.resolve()


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite numeric value")
    return float(value)


def _mass_from_source(source: dict[str, Any]) -> tuple[float | None, dict[str, Any], str | None]:
    """Return total saved mass in kg and its minimal provenance."""

    masses = source.get("masses_by_type")
    atoms = source.get("atoms")
    source_ids = source.get("source_atom_ids")
    mass_units = source.get("mass_units")
    mass_source = source.get("mass_source")
    metadata = {"mass_source": mass_source, "mass_units": mass_units}
    if not isinstance(masses, dict) or not isinstance(atoms, list) or not atoms:
        return None, metadata, "saved source atom masses are missing"
    if not isinstance(source_ids, list):
        return None, metadata, "saved source_atom_ids are missing"
    atom_ids = [atom["source_atom_id"] for atom in atoms]
    if atom_ids != source_ids:
        raise ValueError("saved source atom order differs from source_atom_ids")
    if not isinstance(mass_source, str) or not mass_source:
        return None, metadata, "saved source mass source is missing"
    if mass_units is None:
        return None, metadata, "saved source mass units are missing"
    if mass_units != "g/mol":
        raise ValueError(f"unsupported saved source mass_units: {mass_units}")
    total_molar_mass = math.fsum(
        _finite(masses[str(atom["type"])], "saved source atom mass") for atom in atoms
    )
    total_mass_kg = total_molar_mass * 1.0e-3 / Avogadro
    if total_mass_kg <= 0:
        raise ValueError("saved total atom mass must be positive")
    metadata.update({
        "total_molar_mass": total_molar_mass,
        "total_molar_mass_unit": mass_units,
    })
    return total_mass_kg, metadata, None


def _unresolved_state(state_id: str, source_path: Path | None, reason: str) -> dict[str, Any]:
    return {
        "state_id": state_id,
        "source_path": source_path,
        "source": None,
        "source_refs": [str(source_path)] if source_path is not None else [],
        "atom_mapping_ref": None,
        "mass_kg": None,
        "mass_meta": {},
        "volume_mean_angstrom3": None,
        "temperature_mean_K": None,
        "internal_energy_mean_eV": None,
        "enthalpy_mean_J": None,
        "mean_pressure_bar": None,
        "target_temperature_K": None,
        "external_pressure_bar": None,
        "seed": None,
        "model_id": None,
        "model_version": None,
        "study_id": None,
        "method_set": None,
        "potential_id": None,
        "potential_version": None,
        "source_atom_ids": None,
        "source_cell_angstrom": None,
        "protocol": {},
        "mechanical_constraint": {},
        "native_job": None,
        "analysis_scheduler_job_id": None,
        "status": None,
        "scientific_status": None,
        "sampling_equilibrium_qualified": None,
        "production_qualification": None,
        "selected_step_range": None,
        "selected_sample_count": 0,
        "observation_window": None,
        "reasons": [reason],
    }


def _state_record(
    state_request: dict[str, Any],
    request_file: Path,
    observation_window: dict[str, Any],
    study: dict[str, Any],
) -> dict[str, Any]:
    state_id = state_request["state_id"]
    source_value = state_request.get("source_path")
    if not isinstance(source_value, str) or not source_value:
        return _unresolved_state(state_id, None, "bulk thermal source path is missing")
    source_path = _request_path(source_value, request_file)
    source = _read_json(source_path)
    if source.get("schema") != SOURCE_SCHEMA:
        raise ValueError(f"bulk thermal source schema must be {SOURCE_SCHEMA}")

    expected_study_id = study["study_id"]
    expected_model = study["model"]
    source_study_id = source.get("study_id")
    source_model_id = source.get("model_id")
    source_model_version = source.get("model_version")
    if source_study_id is not None and source_study_id != expected_study_id:
        raise ValueError("bulk thermal source Study identity differs from request Study")
    if source_model_id is not None and source_model_id != expected_model["model_id"]:
        raise ValueError("bulk thermal source model identity differs from request Study")
    if source_model_version is not None and source_model_version != expected_model["version"]:
        raise ValueError("bulk thermal source model version differs from request Study")

    protocol = source.get("protocol")
    mechanical = source.get("mechanical_constraint")
    reasons: list[str] = []
    if not isinstance(protocol, dict):
        protocol = {}
        reasons.append("bulk thermal source protocol is missing")
    if source.get("units") != "metal":
        if source.get("units") is None:
            reasons.append("bulk thermal source units are missing")
        else:
            raise ValueError("bulk thermal source units must be metal")

    if not isinstance(mechanical, dict):
        mechanical = {}
        reasons.append("bulk thermal source mechanical constraint is missing")

    external_pressure = source.get("external_pressure_bar")
    if external_pressure is None:
        reasons.append("bulk thermal source external pressure is missing")
    else:
        external_pressure = _finite(external_pressure, "external_pressure_bar")

    frames = source.get("frames")
    if not isinstance(frames, list) or not frames:
        reasons.append("bulk thermal source frames are missing")
        frames = []
    start_step = observation_window["start_step"]
    end_step = observation_window["end_step"]
    bad_step = any(
        "step" not in frame
        or not isinstance(frame.get("step"), (int, float))
        or isinstance(frame.get("step"), bool)
        for frame in frames
    )
    if bad_step:
        reasons.append("saved source frame step is missing")
    selected = [
        frame for frame in frames
        if isinstance(frame, dict)
        and isinstance(frame.get("step"), (int, float))
        and not isinstance(frame.get("step"), bool)
        and frame.get("step") >= start_step
        and frame.get("step") <= end_step
    ]
    window_valid = bool(selected)
    if bad_step:
        window_valid = False
    if not selected:
        reasons.append("observation window contains no saved source frames")
    elif selected[0].get("step") != start_step or selected[-1].get("step") != end_step:
        reasons.append("saved source frames do not cover the closed observation window")
        window_valid = False

    required_frame_fields = (
        "step", "temperature_K", "potential_energy_eV",
        "kinetic_energy_eV", "volume_angstrom3",
    )
    missing_frame_fields: set[str] = set()
    for field in required_frame_fields:
        if any(field not in frame for frame in selected):
            missing_frame_fields.add(field)
    if missing_frame_fields:
        reasons.append(
            "saved source frame fields are missing: "
            + ",".join(sorted(missing_frame_fields))
        )

    temperature_mean = None
    internal_energy_mean = None
    volume_mean = None
    mean_pressure = None
    if window_valid and "temperature_K" not in missing_frame_fields:
        temperatures = [_finite(frame["temperature_K"], "source frame temperature_K") for frame in selected]
        temperature_mean = math.fsum(temperatures) / len(temperatures)
    if window_valid and not ({"potential_energy_eV", "kinetic_energy_eV"} & missing_frame_fields):
        internal_energies = [
            _finite(frame["potential_energy_eV"], "source frame potential_energy_eV")
            + _finite(frame["kinetic_energy_eV"], "source frame kinetic_energy_eV")
            for frame in selected
        ]
        internal_energy_mean = math.fsum(internal_energies) / len(internal_energies)
    if window_valid and "volume_angstrom3" not in missing_frame_fields:
        volumes = [_finite(frame["volume_angstrom3"], "source frame volume_angstrom3") for frame in selected]
        if any(volume <= 0 for volume in volumes):
            raise ValueError("source frame volume_angstrom3 must be positive")
        volume_mean = math.fsum(volumes) / len(volumes)
    if window_valid and all("pressure_bar" in frame for frame in selected):
        pressure_values = [
            _finite(frame["pressure_bar"], "source frame pressure_bar")
            for frame in selected
        ]
        mean_pressure = math.fsum(pressure_values) / len(pressure_values)

    mass_kg, mass_meta, mass_reason = _mass_from_source(source)
    if mass_reason:
        reasons.append(mass_reason)
    target_temperature = source.get("target_temperature_K")
    if target_temperature is not None:
        target_temperature = _finite(target_temperature, "target_temperature_K")
    else:
        target_temperature = protocol.get("temperature_K")
        if target_temperature is None:
            reasons.append("bulk thermal source target temperature is missing")
        else:
            target_temperature = _finite(target_temperature, "protocol temperature_K")
    seed = protocol.get("seed")
    if seed is None:
        reasons.append("bulk thermal source seed is missing")
    source_ids = source.get("source_atom_ids")
    if not isinstance(source_ids, list):
        reasons.append("bulk thermal source source_atom_ids are missing")
    atom_mapping_ref = source.get("atom_mapping_ref")
    if not isinstance(atom_mapping_ref, str) or not atom_mapping_ref:
        reasons.append("bulk thermal source atom_mapping_ref is missing")
        atom_mapping_ref = None
    elif not Path(atom_mapping_ref).is_absolute():
        atom_mapping_ref = str((source_path.parent / atom_mapping_ref).resolve())
    for field, label in (
        ("task_id", "bulk thermal source task identity"),
        ("method_set", "bulk thermal source method_set"),
        ("potential_id", "bulk thermal source potential_id"),
        ("potential_version", "bulk thermal source potential_version"),
    ):
        if not source.get(field):
            reasons.append(f"{label} is missing")
    if source_study_id is None:
        reasons.append("bulk thermal source study_id is missing")
    if source_model_id is None or source_model_version is None:
        reasons.append("bulk thermal source model identity is missing")

    enthalpy_mean = None
    if internal_energy_mean is not None and volume_mean is not None and external_pressure is not None:
        enthalpy_mean = (
            internal_energy_mean * elementary_charge
            + external_pressure * 1.0e5 * volume_mean * 1.0e-30
        )
    source_refs = [str(source_path)]
    if atom_mapping_ref is not None:
        source_refs.append(atom_mapping_ref)
    return {
        "state_id": state_id,
        "source_path": source_path,
        "source": source,
        "source_refs": source_refs,
        "atom_mapping_ref": atom_mapping_ref,
        "mass_kg": mass_kg,
        "mass_meta": mass_meta,
        "volume_mean_angstrom3": volume_mean,
        "temperature_mean_K": temperature_mean,
        "internal_energy_mean_eV": internal_energy_mean,
        "enthalpy_mean_J": enthalpy_mean,
        "mean_pressure_bar": mean_pressure,
        "target_temperature_K": target_temperature,
        "external_pressure_bar": external_pressure,
        "seed": seed,
        "model_id": source_model_id,
        "model_version": source_model_version,
        "study_id": source_study_id,
        "method_set": source.get("method_set"),
        "potential_id": source.get("potential_id"),
        "potential_version": source.get("potential_version"),
        "source_atom_ids": copy.deepcopy(source_ids),
        "source_cell_angstrom": copy.deepcopy(source.get("source_cell_angstrom")),
        "protocol": copy.deepcopy(protocol),
        "mechanical_constraint": copy.deepcopy(mechanical),
        "native_job": copy.deepcopy(source.get("native_job")),
        "analysis_scheduler_job_id": source.get("analysis_scheduler_job_id"),
        "status": source.get("status"),
        "scientific_status": source.get("scientific_status"),
        "sampling_equilibrium_qualified": source.get("sampling_equilibrium_qualified"),
        "production_qualification": source.get("production_qualification"),
        "selected_step_range": [selected[0]["step"], selected[-1]["step"]] if selected else None,
        "selected_sample_count": len(selected),
        "observation_window": copy.deepcopy(observation_window),
        "reasons": list(dict.fromkeys(reasons)),
    }


def _state_conditions(state: dict[str, Any]) -> dict[str, Any]:
    source = state["source"]
    return {
        "state_id": state["state_id"],
        "task_id": source.get("task_id") if isinstance(source, dict) else None,
        "source_path": str(state["source_path"]) if state["source_path"] is not None else None,
        "target_temperature_K": state["target_temperature_K"],
        "actual_temperature_mean_K": state["temperature_mean_K"],
        "mean_internal_energy_eV": state["internal_energy_mean_eV"],
        "mean_volume_angstrom3": state["volume_mean_angstrom3"],
        "mean_enthalpy_J": state["enthalpy_mean_J"],
        "mean_pressure_bar": state["mean_pressure_bar"],
        "external_pressure_bar": state["external_pressure_bar"],
        "external_pressure_unit": "bar",
        "observation_window": copy.deepcopy(state["observation_window"]),
        "selected_step_range": copy.deepcopy(state["selected_step_range"]),
        "selected_sample_count": state["selected_sample_count"],
        "protocol": copy.deepcopy(state["protocol"]),
        "mechanical_constraint": copy.deepcopy(state["mechanical_constraint"]),
        "model_id": state["model_id"],
        "model_version": state["model_version"],
        "method_set": state["method_set"],
        "potential_id": state["potential_id"],
        "potential_version": state["potential_version"],
        "atom_mapping_ref": state["atom_mapping_ref"],
        "source_cell_angstrom": copy.deepcopy(state["source_cell_angstrom"]),
        "status": state["status"],
        "scientific_status": state["scientific_status"],
        "sampling_equilibrium_qualified": state["sampling_equilibrium_qualified"],
        "production_qualification": state["production_qualification"],
        "analysis_scheduler_job_id": state["analysis_scheduler_job_id"],
        "native_job": copy.deepcopy(state["native_job"]),
        "unresolved_reasons": list(state["reasons"]),
    }


def _property(
    *,
    name: str,
    value: Any,
    unit: str,
    shape: list[int],
    coordinates: Any,
    definition: str,
    conditions: dict[str, Any],
    atom_mapping_ref: str | None,
    source_refs: list[str],
    reason: str | None,
) -> dict[str, Any]:
    conditions = copy.deepcopy(conditions)
    if reason is not None:
        conditions["unresolved_reason"] = reason
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "shape": shape,
        "definition": definition,
        "conditions": conditions,
        "coordinates": coordinates,
        "atom_mapping_ref": atom_mapping_ref,
        "source_refs": list(dict.fromkeys(source_refs)),
        "status": "unresolved" if reason is not None else "available",
    }


def _density_property(state: dict[str, Any]) -> dict[str, Any]:
    reason = None
    value = None
    if state["mass_kg"] is None:
        reason = "saved source total mass is unresolved"
    elif state["volume_mean_angstrom3"] is None:
        reason = "saved source mean volume is unresolved"
    else:
        value = state["mass_kg"] / (state["volume_mean_angstrom3"] * 1.0e-30)
    return _property(
        name="mass_density",
        value=value,
        unit="kg/m^3",
        shape=[],
        coordinates="not_applicable_to_scalar",
        definition="saved total atom mass divided by the mean selected whole-cell volume",
        conditions=_state_conditions(state),
        atom_mapping_ref=state["atom_mapping_ref"],
        source_refs=state["source_refs"],
        reason=reason,
    )


def _interval_conditions(
    interval: dict[str, Any], reference: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any]:
    return {
        "interval_id": interval["interval_id"],
        "reference_state_id": reference["state_id"],
        "target_state_id": target["state_id"],
        "seed": reference["seed"],
        "reference_target_temperature_K": reference["target_temperature_K"],
        "target_target_temperature_K": target["target_temperature_K"],
        "reference_actual_temperature_mean_K": reference["temperature_mean_K"],
        "target_actual_temperature_mean_K": target["temperature_mean_K"],
        "external_pressure_bar": reference["external_pressure_bar"]
        if reference["external_pressure_bar"] == target["external_pressure_bar"]
        else None,
        "mean_internal_energy_eV": {
            "reference": reference["internal_energy_mean_eV"],
            "target": target["internal_energy_mean_eV"],
            "unit": "eV",
        },
        "mean_volume_angstrom3": {
            "reference": reference["volume_mean_angstrom3"],
            "target": target["volume_mean_angstrom3"],
            "unit": "angstrom^3",
        },
        "mean_enthalpy_J": {
            "reference": reference["enthalpy_mean_J"],
            "target": target["enthalpy_mean_J"],
            "unit": "J",
        },
        "reference": _state_conditions(reference),
        "target": _state_conditions(target),
        "actual_delta_temperature_K": (
            target["temperature_mean_K"] - reference["temperature_mean_K"]
            if reference["temperature_mean_K"] is not None and target["temperature_mean_K"] is not None
            else None
        ),
        "external_pressure_unit": "bar",
        "mechanical_scope": "isotropic fixed-shape interval; no anisotropic inference",
    }


def _interval_base_reasons(reference: dict[str, Any], target: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if reference["seed"] is None or target["seed"] is None:
        reasons.append("same-seed identity is unresolved")
    elif reference["seed"] != target["seed"]:
        raise ValueError("bulk thermal interval reference and target must use the same seed")
    for field, label in (
        ("model_id", "model identity"),
        ("model_version", "model version"),
        ("study_id", "Study identity"),
        ("method_set", "method_set"),
        ("potential_id", "potential identity"),
        ("potential_version", "potential version"),
    ):
        left = reference[field]
        right = target[field]
        if left is None or right is None:
            reasons.append(f"same {label} is unresolved")
        elif left != right:
            raise ValueError(f"bulk thermal interval reference and target {label} differ")
    if reference["external_pressure_bar"] is None or target["external_pressure_bar"] is None:
        reasons.append("same external pressure is unresolved")
    elif reference["external_pressure_bar"] != target["external_pressure_bar"]:
        raise ValueError("bulk thermal interval reference and target external pressure differ")
    if reference["source_atom_ids"] is None or target["source_atom_ids"] is None:
        reasons.append("source atom mapping is unresolved")
    elif reference["source_atom_ids"] != target["source_atom_ids"]:
        raise ValueError("bulk thermal interval source atom mappings differ")
    return list(dict.fromkeys(reasons))


def _interval_property(
    *,
    name: str,
    reference: dict[str, Any],
    target: dict[str, Any],
    interval: dict[str, Any],
    unit: str,
    shape: list[int],
    coordinates: Any,
    definition: str,
    value_function: Any,
    base_reasons: list[str],
    extra_reasons: list[str] = (),
) -> dict[str, Any]:
    reasons = list(base_reasons) + list(extra_reasons)
    value = None
    if not reasons:
        value = value_function(reference, target)
    reason = "; ".join(dict.fromkeys(reasons)) if reasons else None
    conditions = _interval_conditions(interval, reference, target)
    return _property(
        name=name,
        value=value,
        unit=unit,
        shape=shape,
        coordinates=coordinates,
        definition=definition,
        conditions=conditions,
        atom_mapping_ref=reference["atom_mapping_ref"],
        source_refs=reference["source_refs"] + target["source_refs"],
        reason=reason,
    )


def build_bulk_thermal_response(request_path: str | Path) -> dict[str, Any]:
    """Build a domain-parameter product from explicitly saved NPT sources."""

    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    study_path = _request_path(request["study_path"], request_file)
    study = _read_json(study_path)
    study_id = study["study_id"]
    case_id = study["case_id"]
    model_data = study["model"]
    model = {"model_id": model_data["model_id"], "version": model_data["version"]}
    observation_window = request["observation_window"]
    start_step = observation_window["start_step"]
    end_step = observation_window["end_step"]
    if not isinstance(start_step, int) or isinstance(start_step, bool):
        raise ValueError("observation_window.start_step must be an integer")
    if not isinstance(end_step, int) or isinstance(end_step, bool):
        raise ValueError("observation_window.end_step must be an integer")
    if end_step < start_step:
        raise ValueError("observation_window end_step must not precede start_step")
    observation_window = {"start_step": start_step, "end_step": end_step, "closed": True}

    states = [
        _state_record(entry, request_file, observation_window, study)
        for entry in request["states"]
    ]
    state_by_id = {state["state_id"]: state for state in states}
    properties = [_density_property(state) for state in states]

    interval = request["interval"]
    reference = state_by_id[interval["reference_state_id"]]
    target = state_by_id[interval["target_state_id"]]
    base_reasons = _interval_base_reasons(reference, target)
    delta_temperature = None
    if reference["temperature_mean_K"] is not None and target["temperature_mean_K"] is not None:
        delta_temperature = target["temperature_mean_K"] - reference["temperature_mean_K"]
    delta_reason = []
    if delta_temperature is None:
        delta_reason.append("actual mean temperature difference is unresolved")
    elif delta_temperature == 0:
        delta_reason.append("actual mean temperature difference is zero")

    def strain_value(ref: dict[str, Any], tgt: dict[str, Any]) -> float:
        return (tgt["volume_mean_angstrom3"] / ref["volume_mean_angstrom3"]) ** (1.0 / 3.0) - 1.0

    volume_reasons = list(base_reasons)
    if reference["volume_mean_angstrom3"] is None or target["volume_mean_angstrom3"] is None:
        volume_reasons.append("mean volume is unresolved")
    if not volume_reasons:
        if reference["volume_mean_angstrom3"] <= 0 or target["volume_mean_angstrom3"] <= 0:
            raise ValueError("bulk thermal mean volume must be positive")
    properties.append(_interval_property(
        name="mass_specific_heat_cp_interval",
        reference=reference, target=target, interval=interval,
        unit="J/(kg K)", shape=[], coordinates="not_applicable_to_scalar",
        definition="secant mass-specific heat from mean enthalpy between two same-seed NPT states",
        value_function=lambda ref, tgt: (
            (tgt["enthalpy_mean_J"] - ref["enthalpy_mean_J"])
            / (ref["mass_kg"] * delta_temperature)
        ),
        base_reasons=base_reasons,
        extra_reasons=(
            (["mean enthalpy is unresolved"] if reference["enthalpy_mean_J"] is None or target["enthalpy_mean_J"] is None else [])
            + (["total mass is unresolved"] if reference["mass_kg"] is None else [])
            + delta_reason
        ),
    ))
    properties.append(_interval_property(
        name="isotropic_thermal_linear_strain_interval",
        reference=reference, target=target, interval=interval,
        unit="dimensionless", shape=[], coordinates="not_applicable_to_scalar",
        definition="isotropic linear strain from the cube-root mean-volume ratio over the selected interval",
        value_function=strain_value,
        base_reasons=volume_reasons,
    ))
    properties.append(_interval_property(
        name="isotropic_thermal_strain_tensor_interval",
        reference=reference, target=target, interval=interval,
        unit="dimensionless", shape=[3, 3],
        coordinates={"basis": "source_cartesian", "mechanical_constraint": "isotropic_fixed_shape"},
        definition="isotropic strain tensor in the saved source Cartesian basis over the selected interval",
        value_function=lambda ref, tgt: (
            lambda strain: [[strain, 0.0, 0.0], [0.0, strain, 0.0], [0.0, 0.0, strain]]
        )(strain_value(ref, tgt)),
        base_reasons=volume_reasons,
    ))
    properties.append(_interval_property(
        name="isotropic_linear_thermal_expansion_interval",
        reference=reference, target=target, interval=interval,
        unit="1/K", shape=[], coordinates="not_applicable_to_scalar",
        definition="finite isotropic linear thermal expansion over the selected actual-temperature interval",
        value_function=lambda ref, tgt: strain_value(ref, tgt) / delta_temperature,
        base_reasons=volume_reasons,
        extra_reasons=delta_reason,
    ))
    properties.append(_interval_property(
        name="isotropic_volumetric_thermal_expansion_interval",
        reference=reference, target=target, interval=interval,
        unit="1/K", shape=[], coordinates="not_applicable_to_scalar",
        definition="finite isotropic volumetric thermal expansion from the mean-volume ratio over the selected actual-temperature interval",
        value_function=lambda ref, tgt: (
            (tgt["volume_mean_angstrom3"] / ref["volume_mean_angstrom3"] - 1.0) / delta_temperature
        ),
        base_reasons=volume_reasons,
        extra_reasons=delta_reason,
    ))

    for property_record in properties:
        if str(study_path) not in property_record["source_refs"]:
            property_record["source_refs"].append(str(study_path))

    native_jobs = []
    for state in states:
        native = copy.deepcopy(state["native_job"])
        if isinstance(native, dict):
            native_jobs.append({"task_id": state.get("source", {}).get("task_id"), **native})
    execution = {
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "native_jobs": native_jobs,
    }
    return domain_parameter_product(
        kind=DOMAIN_KIND,
        model=model,
        study={"study_id": study_id, "case_id": case_id},
        properties=properties,
        execution=execution,
    )


__all__ = ["REQUEST_SCHEMA", "SOURCE_SCHEMA", "build_bulk_thermal_response"]
