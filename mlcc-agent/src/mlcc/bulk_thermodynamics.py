"""Saved NVT to bulk thermodynamic domain properties."""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from typing import Any

from scipy.constants import Avogadro, elementary_charge

from .domain_parameters import domain_parameter_product


REQUEST_SCHEMA = "mlcc.bulk-thermodynamics-request.v1"
DELIVERY_SCHEMA = "mlcc.md-property-delivery.v1"
THERMO_SCHEMA = "mlcc.md-thermo-summary.v1"
VOLUME_SCHEMA = "mlcc.md-thermal-sources-request.v1"
DOMAIN_KIND = "bulk_thermodynamics"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_path(value: str | Path, request_file: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = request_file.parent / path
    return path.resolve()


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite numeric value")
    return float(value)


def _declared_path(value: str, owner: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = owner.parent / path
    return path


def _native_job(delivery: dict[str, Any]) -> dict[str, Any]:
    native = delivery.get("native_job")
    if not isinstance(native, dict):
        raise ValueError("MD delivery native_job must be an object")
    return {
        "task_id": delivery["task_id"],
        **{key: native.get(key) for key in ("scheduler_job_id", "scheduler_state", "exit_code", "runner")},
    }


def _production_window(thermo: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if thermo is None:
        return None, "saved thermo artifact declaration is missing"
    observation = thermo.get("observation")
    if not isinstance(observation, dict):
        return None, "saved thermo observation window is missing"
    request = observation.get("request")
    step_range = observation.get("step_range")
    sample_count = observation.get("sample_count")
    if not isinstance(request, dict) or not isinstance(step_range, list) or len(step_range) != 2:
        return None, "saved thermo production window is incomplete"
    if not isinstance(sample_count, int) or sample_count <= 0:
        return None, "saved thermo production sample count is missing"
    thermo_record = thermo.get("thermo")
    rows = thermo_record.get("rows") if isinstance(thermo_record, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, "saved selected thermo rows are missing"
    if len(rows) != sample_count:
        raise ValueError("saved selected thermo row count differs from production sample_count")
    if [rows[0]["step"], rows[-1]["step"]] != step_range:
        raise ValueError("saved selected thermo row endpoints differ from production step_range")
    return {
        "request": copy.deepcopy(request),
        "step_range": copy.deepcopy(step_range),
        "sample_count": sample_count,
        "physical_time_ps_range": copy.deepcopy(observation.get("physical_time_ps_range")),
        "scope": observation.get("scope"),
    }, None


def _mean_pe_plus_ke(thermo: dict[str, Any] | None, window: dict[str, Any] | None) -> tuple[float | None, str | None]:
    if window is None:
        return None, "saved thermo production window is unresolved"
    if thermo is None:
        return None, "saved thermo artifact declaration is missing"
    thermo_record = thermo.get("thermo")
    if not isinstance(thermo_record, dict):
        raise KeyError("thermo")
    units = thermo_record["units"]
    if units["pe"] != "eV" or units["ke"] != "eV":
        raise ValueError("saved PE and KE units must be eV")
    rows = thermo_record.get("rows")
    if not isinstance(rows, list) or not rows:
        return None, "saved thermo production rows are missing"
    values = [_finite(row["pe"], "thermo row pe") + _finite(row["ke"], "thermo row ke") for row in rows]
    return math.fsum(values) / len(values), None


def _temperature_mean(thermo: dict[str, Any] | None, window: dict[str, Any] | None) -> tuple[float | None, str | None]:
    if window is None:
        return None, "saved thermo production window is unresolved"
    if thermo is None:
        return None, "saved thermo artifact declaration is missing"
    quantities = thermo.get("quantities")
    if not isinstance(quantities, dict) or not isinstance(quantities.get("temperature"), dict):
        return None, "saved thermo temperature quantity is missing"
    temperature = quantities["temperature"]
    if temperature["unit"] != "K":
        raise ValueError("saved thermo temperature unit must be K")
    value = temperature.get("sample_mean")
    if value is None:
        return None, "saved thermo actual mean temperature is missing"
    return _finite(value, "saved thermo temperature sample_mean"), None


def _mass_from_atom_map(
    atom_map: dict[str, Any] | None,
    delivery_model: dict[str, Any],
) -> tuple[float | None, dict[str, Any], str | None]:
    if atom_map is None:
        return None, {}, "saved atom-map mass source is unavailable"
    masses = atom_map.get("masses_by_type")
    atoms = atom_map.get("atoms")
    source_ids = atom_map.get("source_atom_ids")
    mass_units = atom_map.get("mass_units")
    mass_source = atom_map.get("mass_source")
    if not isinstance(masses, dict) or not isinstance(atoms, list) or not atoms:
        return None, {"mass_source": mass_source, "mass_units": mass_units}, "saved atom-map masses are missing"
    if not isinstance(source_ids, list):
        return None, {"mass_source": mass_source, "mass_units": mass_units}, "saved atom-map source_atom_ids are missing"
    atom_ids = [atom["source_atom_id"] for atom in atoms]
    if atom_ids != source_ids:
        raise ValueError("saved atom-map source_atom_id order differs from source_atom_ids")
    if atom_map.get("model_id") != delivery_model.get("model_id") or atom_map.get("version") != delivery_model.get("version"):
        raise ValueError("saved atom-map model identity differs from MD delivery")
    if not isinstance(mass_source, str) or not mass_source:
        return None, {"mass_source": mass_source, "mass_units": mass_units}, "saved atom-map mass source is missing"
    if mass_units is None:
        return None, {"mass_source": mass_source, "mass_units": mass_units}, "saved atom-map mass units are missing"
    if mass_units == "g/mol":
        factor = 1.0e-3 / Avogadro
    else:
        raise ValueError(f"unsupported saved atom-map mass_units: {mass_units}")
    total_molar_mass = math.fsum(
        _finite(masses[str(atom["type"])], "atom-map mass") for atom in atoms
    )
    total_mass_kg = total_molar_mass * factor
    if total_mass_kg <= 0:
        raise ValueError("saved total atom mass must be positive")
    return total_mass_kg, {
        "mass_source": mass_source,
        "mass_units": mass_units,
        "total_molar_mass": total_molar_mass,
        "total_molar_mass_unit": mass_units,
    }, None


def _volume_source(
    volume_path: Path,
    task_id: str,
    atom_map: dict[str, Any] | None,
) -> tuple[float | None, list[Any] | None, str | None]:
    source = _read_json(volume_path)
    if source.get("schema") != VOLUME_SCHEMA:
        raise ValueError(f"volume source schema must be {VOLUME_SCHEMA}")
    task_path = _declared_path(source["task_path"], volume_path)
    if _read_json(task_path)["task_id"] != task_id:
        raise ValueError("volume source task identity differs from MD delivery")
    analysis = source.get("analysis")
    regions = analysis.get("regions") if isinstance(analysis, dict) else None
    region = None
    if isinstance(regions, list):
        region = next((item for item in regions if isinstance(item, dict) and item.get("region_id") == "whole_cell"), None)
    if region is None:
        return None, None, "whole_cell volume source is missing"
    volume = region.get("volume_angstrom3")
    if volume is None:
        return None, None, "whole_cell volume is missing"
    volume = _finite(volume, "whole_cell volume_angstrom3")
    if volume <= 0:
        raise ValueError("whole_cell volume_angstrom3 must be positive")
    source_ids = atom_map.get("source_atom_ids") if isinstance(atom_map, dict) else None
    region_ids = region.get("atom_ids")
    if source_ids is not None and region_ids != source_ids:
        raise ValueError("whole_cell atom mapping differs from saved atom-map")
    mechanical = source.get("mechanical_constraint")
    if not isinstance(mechanical, dict):
        return volume, None, "fixed-cell mechanical constraint is missing"
    loading = mechanical.get("loading")
    if not isinstance(loading, dict) or loading.get("kind") != "none":
        raise ValueError("bulk thermodynamics requires a fixed-cell mechanical constraint")
    cell = mechanical.get("cell_angstrom")
    if cell is None:
        return volume, None, "fixed-cell matrix is missing"
    source_cell = atom_map.get("source_cell_angstrom") if isinstance(atom_map, dict) else None
    if source_cell is None:
        return volume, None, "saved atom-map source cell is missing"
    if source_cell != cell:
        raise ValueError("saved atom-map source cell differs from fixed-cell constraint")
    return volume, copy.deepcopy(cell), None


def _state_record(state_request: dict[str, Any], request_file: Path) -> dict[str, Any]:
    state_id = state_request["state_id"]
    delivery_path = _request_path(state_request["md_delivery_path"], request_file)
    if delivery_path.is_dir():
        delivery_path = delivery_path / "delivery.json"
    delivery = _read_json(delivery_path)
    if delivery.get("schema") != DELIVERY_SCHEMA:
        raise ValueError(f"MD delivery schema must be {DELIVERY_SCHEMA}")
    task_id = delivery["task_id"]
    protocol = delivery["protocol"]
    if protocol.get("kind") != "md" or protocol.get("ensemble") != "nvt":
        raise ValueError("bulk thermodynamics requires a fixed-cell MD NVT source")
    delivery_model = delivery["model"]
    artifacts = delivery.get("artifacts")
    thermo_ref = artifacts.get("thermo") if isinstance(artifacts, dict) else None
    thermo_path = _declared_path(thermo_ref, delivery_path) if isinstance(thermo_ref, str) and thermo_ref else None
    thermo = _read_json(thermo_path) if thermo_path is not None else None
    if thermo is not None:
        if thermo.get("schema") != THERMO_SCHEMA:
            raise ValueError(f"thermo artifact schema must be {THERMO_SCHEMA}")
        if thermo.get("task_id") != task_id:
            raise ValueError("thermo artifact task identity differs from MD delivery")
        if thermo.get("native_job", {}).get("scheduler_job_id") != delivery.get("native_job", {}).get("scheduler_job_id"):
            raise ValueError("thermo artifact native job identity differs from MD delivery")

    volume_path_value = state_request.get("volume_source_path")
    volume_path = _request_path(volume_path_value, request_file) if volume_path_value is not None else None
    atom_map_path = None
    atom_map_ref = None
    atom_map = None
    if thermo is not None:
        source_files = thermo.get("source_files")
        atom_map_ref = source_files.get("atom-map.json") if isinstance(source_files, dict) else None
        if isinstance(atom_map_ref, str) and atom_map_ref:
            atom_map_path = _declared_path(atom_map_ref, thermo_path)
            atom_map = _read_json(atom_map_path)
    if volume_path is None:
        volume = None
        cell = None
        volume_reason = "volume source path is missing"
    else:
        volume, cell, volume_reason = _volume_source(volume_path, task_id, atom_map)
    window, window_reason = _production_window(thermo)
    temperature_mean, temperature_reason = _temperature_mean(thermo, window)
    energy_mean, energy_reason = _mean_pe_plus_ke(thermo, window)
    mass_kg, mass_meta, mass_reason = _mass_from_atom_map(atom_map, delivery_model)
    if atom_map is None and atom_map_ref is None:
        mass_reason = "saved atom-map source reference is missing"
    source_refs = [str(delivery_path)]
    if thermo_path is not None:
        source_refs.append(str(thermo_path))
    if volume_path is not None:
        source_refs.append(str(volume_path))
    if atom_map_ref is not None:
        source_refs.append(atom_map_ref)
    reasons = [reason for reason in (volume_reason, window_reason, temperature_reason, energy_reason, mass_reason) if reason]
    return {
        "state_id": state_id,
        "delivery_path": delivery_path,
        "delivery": delivery,
        "thermo_path": thermo_path,
        "thermo": thermo,
        "task_id": task_id,
        "atom_map_path": atom_map_path,
        "atom_map_ref": atom_map_ref,
        "atom_map": atom_map,
        "mass_kg": mass_kg,
        "mass_meta": mass_meta,
        "volume_path": volume_path,
        "volume_angstrom3": volume,
        "cell_angstrom": cell,
        "window": window,
        "temperature_mean_K": temperature_mean,
        "energy_mean_eV": energy_mean,
        "target_temperature_K": protocol.get("temperature_K"),
        "seed": protocol.get("seed"),
        "protocol": protocol,
        "source_refs": source_refs,
        "reasons": reasons,
    }


def _state_conditions(state: dict[str, Any]) -> dict[str, Any]:
    delivery = state["delivery"]
    conditions = {
        "state_id": state["state_id"],
        "target_temperature_K": state["target_temperature_K"],
        "actual_temperature_mean_K": state["temperature_mean_K"],
        "seed": state["seed"],
        "ensemble": state["protocol"].get("ensemble"),
        "mechanical_constraint": "fixed_cell" if state["cell_angstrom"] is not None else None,
        "cell_angstrom": copy.deepcopy(state["cell_angstrom"]),
        "volume_angstrom3": state["volume_angstrom3"],
        "production_window": copy.deepcopy(state["window"]),
        "total_mass": {
            "value": state["mass_kg"],
            "unit": "kg",
            "source": copy.deepcopy(state["mass_meta"]),
        },
    }
    conditions.update({
        "status": delivery.get("status"),
        "scientific_status": delivery.get("scientific_status"),
        "sampling_equilibrium_qualified": delivery.get("sampling_equilibrium_qualified"),
        "production_qualification": delivery.get("production_qualification"),
        "analysis_scheduler_job_id": delivery.get("analysis_scheduler_job_id"),
        "native_job": copy.deepcopy(delivery.get("native_job")),
    })
    return conditions


def _delivery_status_conditions(delivery: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": delivery.get("status"),
        "scientific_status": delivery.get("scientific_status"),
        "sampling_equilibrium_qualified": delivery.get("sampling_equilibrium_qualified"),
        "production_qualification": delivery.get("production_qualification"),
        "analysis_scheduler_job_id": delivery.get("analysis_scheduler_job_id"),
        "native_job": copy.deepcopy(delivery.get("native_job")),
    }


def _property(
    *, name: str, value: float | None, definition: str, conditions: dict[str, Any],
    atom_mapping_ref: str | None, source_refs: list[str], reason: str | None,
) -> dict[str, Any]:
    if reason is not None:
        conditions = {**conditions, "unresolved_reason": reason}
    return {
        "name": name,
        "value": value,
        "unit": "kg/m^3" if name == "mass_density" else "J/(kg K)",
        "shape": [],
        "definition": definition,
        "conditions": conditions,
        "coordinates": "not_applicable_to_scalar",
        "atom_mapping_ref": atom_mapping_ref,
        "source_refs": list(dict.fromkeys(source_refs)),
        "status": "unresolved" if reason is not None else "available",
    }


def _density_property(state: dict[str, Any]) -> dict[str, Any]:
    conditions = _state_conditions(state)
    reason = None
    value = None
    if state["mass_kg"] is None:
        reason = "saved atom-map mass is unresolved"
    elif state["volume_angstrom3"] is None:
        reason = "saved fixed-cell volume is unresolved"
    else:
        value = state["mass_kg"] / (state["volume_angstrom3"] * 1.0e-30)
    return _property(
        name="mass_density", value=value,
        definition="total saved atom mass divided by the fixed whole-cell volume",
        conditions=conditions, atom_mapping_ref=state["atom_map_ref"],
        source_refs=state["source_refs"], reason=reason,
    )


def _interval_property(
    interval: dict[str, Any], reference: dict[str, Any], target: dict[str, Any],
) -> dict[str, Any]:
    conditions = {
        "interval_id": interval["interval_id"],
        "reference_state_id": reference["state_id"],
        "target_state_id": target["state_id"],
        "seed": reference["seed"],
        "reference_target_temperature_K": reference["target_temperature_K"],
        "target_target_temperature_K": target["target_temperature_K"],
        "reference_actual_temperature_mean_K": reference["temperature_mean_K"],
        "target_actual_temperature_mean_K": target["temperature_mean_K"],
        "actual_temperature_unit": "K",
        "mean_pe_plus_ke": {
            "reference": reference["energy_mean_eV"],
            "target": target["energy_mean_eV"],
            "unit": "eV",
            "source_fields": ["pe", "ke"],
        },
        "mass": {
            "value": reference["mass_kg"],
            "unit": "kg",
            "source": copy.deepcopy(reference["mass_meta"]),
        },
        "reference_production_window": copy.deepcopy(reference["window"]),
        "target_production_window": copy.deepcopy(target["window"]),
        "reference_cell_angstrom": copy.deepcopy(reference["cell_angstrom"]),
        "target_cell_angstrom": copy.deepcopy(target["cell_angstrom"]),
        "reference_volume_angstrom3": reference["volume_angstrom3"],
        "target_volume_angstrom3": target["volume_angstrom3"],
        "mechanical_constraint": "same_fixed_cell"
        if reference["cell_angstrom"] is not None and target["cell_angstrom"] is not None else None,
        "reference_delivery": _delivery_status_conditions(reference["delivery"]),
        "target_delivery": _delivery_status_conditions(target["delivery"]),
    }
    reasons = list(reference["reasons"]) + list(target["reasons"])
    if reference["seed"] is None or target["seed"] is None:
        reasons.append("same-seed identity is unresolved")
    elif reference["seed"] != target["seed"]:
        raise ValueError("cv interval reference and target must use the same seed")
    if reference["cell_angstrom"] is None or target["cell_angstrom"] is None:
        reasons.append("same fixed-cell matrix is unresolved")
    elif reference["cell_angstrom"] != target["cell_angstrom"]:
        raise ValueError("cv interval reference and target cells differ")
    if reference["volume_angstrom3"] is not None and target["volume_angstrom3"] is not None and reference["volume_angstrom3"] != target["volume_angstrom3"]:
        raise ValueError("cv interval reference and target volumes differ")
    if reference["mass_kg"] is not None and target["mass_kg"] is not None and reference["mass_kg"] != target["mass_kg"]:
        raise ValueError("cv interval reference and target masses differ")
    if reference["energy_mean_eV"] is None or target["energy_mean_eV"] is None:
        reasons.append("mean PE+KE is unresolved")
    if reference["temperature_mean_K"] is None or target["temperature_mean_K"] is None:
        reasons.append("actual mean temperature is unresolved")
    if reference["mass_kg"] is None:
        reasons.append("total mass is unresolved")
    value = None
    if not reasons:
        delta_temperature = target["temperature_mean_K"] - reference["temperature_mean_K"]
        conditions["actual_delta_temperature_K"] = delta_temperature
        if delta_temperature == 0:
            reasons.append("actual mean temperature difference is zero")
        else:
            value = (
                (target["energy_mean_eV"] - reference["energy_mean_eV"]) * elementary_charge
                / delta_temperature / reference["mass_kg"]
            )
    reason = "; ".join(dict.fromkeys(reasons)) if reasons else None
    return _property(
        name="mass_specific_heat_cv_interval", value=value,
        definition="secant fixed-volume mass-specific heat from mean (PE+KE) between two same-seed NVT states",
        conditions=conditions, atom_mapping_ref=reference["atom_map_ref"],
        source_refs=reference["source_refs"] + target["source_refs"],
        reason=reason,
    )


def build_bulk_thermodynamics(request_path: str | Path) -> dict[str, Any]:
    """Build a neutral domain-parameter product from saved NVT deliveries."""

    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    study_path = _request_path(request["study_path"], request_file)
    study = _read_json(study_path)
    study_id = study["study_id"]
    case_id = study["case_id"]
    study_model = study["model"]
    model = {"model_id": study_model["model_id"], "version": study_model["version"]}

    state_requests = request["states"]
    states = [_state_record(entry, request_file) for entry in state_requests]
    state_by_id = {state["state_id"]: state for state in states}
    for state in states:
        delivery = state["delivery"]
        if delivery.get("study_id") != study_id or delivery.get("case_id") != case_id:
            raise ValueError("MD delivery Study identity differs from request Study")
        delivery_model = delivery["model"]
        if delivery_model.get("model_id") != model["model_id"] or delivery_model.get("version") != model["version"]:
            raise ValueError("MD delivery model identity differs from request Study")

    properties = [_density_property(state) for state in states]
    for interval in request.get("cv_intervals", []):
        reference = state_by_id[interval["reference_state_id"]]
        target = state_by_id[interval["target_state_id"]]
        if reference["delivery"].get("lineage", {}).get("method_set") != target["delivery"].get("lineage", {}).get("method_set"):
            raise ValueError("cv interval reference and target method_set differ")
        properties.append(_interval_property(interval, reference, target))
    for property_record in properties:
        if str(study_path) not in property_record["source_refs"]:
            property_record["source_refs"].append(str(study_path))

    native_jobs = [_native_job(state["delivery"]) for state in states]
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


__all__ = ["REQUEST_SCHEMA", "build_bulk_thermodynamics"]
