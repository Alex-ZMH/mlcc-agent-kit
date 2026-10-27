"""Convert a saved single-direction NEMD source to transport properties."""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from typing import Any

from scipy.constants import elementary_charge

from .domain_parameters import domain_parameter_product
from .md_msd import _linear_fit
from .md_thermo import _observation_rows


REQUEST_SCHEMA = "mlcc.bulk-thermal-transport-request.v1"
SOURCE_SCHEMA = "mlcc.md-bulk-heat-source.v1"
DOMAIN_KIND = "bulk_thermal_transport"


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


def _property(
    *,
    name: str,
    value: float | None,
    unit: str,
    definition: str,
    conditions: dict[str, Any],
    coordinates: Any,
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
        "shape": [],
        "definition": definition,
        "conditions": conditions,
        "coordinates": coordinates,
        "atom_mapping_ref": atom_mapping_ref,
        "source_refs": list(dict.fromkeys(source_refs)),
        "status": "unresolved" if reason is not None else "available",
    }


def _select_rows(
    rows: Any, observation_window: dict[str, Any] | None, label: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(rows, list) or not rows:
        return None, f"saved {label} rows are missing"
    if observation_window is None:
        return None, f"saved {label} observation window is missing"
    _, selected = _observation_rows(rows, observation_window)
    if not selected:
        return None, f"saved {label} observation window is empty"
    return selected, None


def _fit_report(
    times_ps: list[float], values: list[float], *, value_unit: str, source_field: str,
) -> dict[str, Any]:
    fit = _linear_fit(times_ps, values)
    if fit["status"] != "available":
        return {"status": fit["status"], "reason": fit.get("reason"), "source_field": source_field}
    return {
        "status": "available",
        "source_field": source_field,
        "time_unit": "ps",
        "value_unit": value_unit,
        "slope": fit["slope"],
        "slope_eV_per_ps": fit["slope"] if value_unit == "eV" else None,
        "intercept": fit["intercept"],
        "intercept_eV": fit["intercept"] if value_unit == "eV" else None,
        "residuals": fit["residuals"],
        "residuals_eV": fit["residuals"] if value_unit == "eV" else None,
        "r_squared": fit["r_squared"],
        "r_squared_unresolved_reason": fit["r_squared_unresolved_reason"],
        "count": fit["count"],
        "time_range_ps": [times_ps[0], times_ps[-1]],
    }


def _energy_fit(
    rows: list[dict[str, Any]] | None, field: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if rows is None:
        return None, "selected native energy rows are unresolved"
    if any("physical_time_ps" not in row for row in rows):
        return None, "saved native energy physical_time_ps is missing"
    if any(field not in row for row in rows):
        return None, f"saved native energy field is missing: {field}"
    times = [_finite(row["physical_time_ps"], f"energy row {field} physical_time_ps") for row in rows]
    values = [_finite(row[field], f"energy row {field}") for row in rows]
    fit = _fit_report(times, values, value_unit="eV", source_field=field)
    if fit["status"] != "available":
        return fit, f"{field} energy fit is unresolved: {fit.get('reason')}"
    return fit, None


def _power_from_fit(
    fit: dict[str, Any] | None, reason: str | None, *, sign: float,
) -> tuple[float | None, str | None]:
    if fit is None:
        return None, reason
    if fit["status"] != "available":
        return None, reason or "energy fit is unresolved"
    return sign * fit["slope"] * elementary_charge * 1.0e12, None


def _profile_summary(
    frames: list[dict[str, Any]] | None, bin_ids: list[Any], observation_window: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    selected, reason = _select_rows(frames, observation_window, "profile")
    if selected is None:
        return None, reason
    bins: list[dict[str, Any]] = []
    fit_x: list[float] = []
    fit_y: list[float] = []
    empty_bins: list[Any] = []
    for bin_id in bin_ids:
        temperatures: list[float] = []
        coordinates: list[float] = []
        coordinates_reduced: list[float] = []
        counts: list[Any] = []
        empty_steps: list[Any] = []
        for frame in selected:
            frame_bin = next((item for item in frame["bins"] if item["bin_id"] == bin_id), None)
            if frame_bin is None:
                counts.append(None)
                empty_steps.append(frame["step"])
                continue
            count = frame_bin.get("atom_count")
            counts.append(count)
            if count is None or count <= 0 or frame_bin.get("temperature_K") is None:
                empty_steps.append(frame["step"])
                continue
            if frame_bin.get("coordinate_angstrom") is None:
                empty_steps.append(frame["step"])
                continue
            temperatures.append(_finite(frame_bin["temperature_K"], f"profile bin {bin_id} temperature_K"))
            coordinates.append(_finite(frame_bin["coordinate_angstrom"], f"profile bin {bin_id} coordinate_angstrom"))
            if frame_bin.get("coordinate_reduced") is not None:
                coordinates_reduced.append(_finite(frame_bin["coordinate_reduced"], f"profile bin {bin_id} coordinate_reduced"))
        coordinate = coordinates[0] if coordinates else None
        mean_temperature = math.fsum(temperatures) / len(temperatures) if temperatures else None
        record = {
            "bin_id": bin_id,
            "coordinate_angstrom": coordinate,
            "coordinate_reduced": coordinates_reduced[0] if coordinates_reduced else None,
            "mean_temperature_K": mean_temperature,
            "selected_frame_count": len(temperatures),
            "selected_sample_count": len(selected),
            "atom_count_by_frame": counts,
            "empty_frame_steps": empty_steps,
        }
        bins.append(record)
        if empty_steps or mean_temperature is None or coordinate is None:
            empty_bins.append(bin_id)
        else:
            fit_x.append(coordinate)
            fit_y.append(mean_temperature)
    report = {
        "status": "unresolved" if empty_bins else "available",
        "selected_step_range": [selected[0]["step"], selected[-1]["step"]],
        "selected_sample_count": len(selected),
        "bins": bins,
        "fit_bin_ids": list(bin_ids) if not empty_bins else [],
    }
    if empty_bins:
        return report, f"specified profile bins have empty or missing frames: {empty_bins}"
    fit = _linear_fit(fit_x, fit_y)
    if fit["status"] != "available":
        report.update({"fit": {"status": fit["status"], "reason": fit.get("reason")}})
        return report, f"profile temperature fit is unresolved: {fit.get('reason')}"
    report["fit"] = {
        "status": "available",
        "coordinate_unit": "angstrom",
        "temperature_unit": "K",
        "slope_K_per_angstrom": fit["slope"],
        "slope_K_per_m": fit["slope"] * 1.0e10,
        "intercept_K": fit["intercept"],
        "residuals_K": fit["residuals"],
        "r_squared": fit["r_squared"],
        "r_squared_unresolved_reason": fit["r_squared_unresolved_reason"],
        "count": fit["count"],
        "coordinate_range_angstrom": [fit_x[0], fit_x[-1]],
    }
    return report, None


def _identity_error(label: str, left: Any, right: Any) -> None:
    if left is not None and right is not None and left != right:
        raise ValueError(f"{label} differs: {left!r} != {right!r}")


def _source_references(
    paths: list[Path], source: dict[str, Any], task: dict[str, Any], result: dict[str, Any],
) -> list[str]:
    references = [str(path) for path in paths]
    for record in (source, task, result):
        source_files = record.get("source_files")
        if isinstance(source_files, dict):
            references.extend(str(value) for value in source_files.values() if isinstance(value, str))
    return list(dict.fromkeys(references))


def _load_request(request_path: str | Path) -> tuple[
    Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[str]
]:
    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    study_path = _request_path(request["study_path"], request_file)
    model_directory = _request_path(request["model_path"], request_file)
    model_path = model_directory / "model.json"
    source_path = _request_path(request["source_path"], request_file)
    task_path = _request_path(request["task_path"], request_file)
    result_path = _request_path(request["result_path"], request_file)
    study = _read_json(study_path)
    model = _read_json(model_path)
    source = _read_json(source_path)
    task = _read_json(task_path)
    result = _read_json(result_path)
    if source.get("schema") != SOURCE_SCHEMA:
        raise ValueError(f"bulk heat source schema must be {SOURCE_SCHEMA}")
    if source.get("units") != "metal":
        if source.get("units") is None:
            raise ValueError("bulk heat source units are missing")
        raise ValueError("bulk heat source units must be metal")
    study_id = study["study_id"]
    model_id = model["model_id"]
    model_version = model["version"]
    study_model = study["model"]
    _identity_error("study.model.model_id/model.model_id", study_model["model_id"], model_id)
    _identity_error("study.model.version/model.version", study_model["version"], model_version)
    _identity_error("task.study_id", task.get("study_id"), study_id)
    _identity_error("task.model_id", task.get("model_id"), model_id)
    _identity_error("task.model_version", task.get("model_version"), model_version)
    for field in ("task_id", "scheduler_job_id", "study_id", "model_id", "model_version", "method_set"):
        _identity_error(f"result.{field}/task.{field}", result.get(field), task.get(field))
    if result.get("version") != task.get("model_version"):
        raise ValueError("result.version differs from task.model_version")
    paths = [study_path, model_path, source_path, task_path, result_path]
    return request_file, request, study, model, source, task, result, _source_references(paths, source, task, result)


def _transport_contract(request: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    transport = request["transport"]
    direction = transport["direction_cartesian"]
    if direction != [0, 0, 1]:
        raise ValueError("bulk thermal transport direction must be +z [0, 0, 1]")
    geometry = source.get("geometry")
    if not isinstance(geometry, dict):
        return transport, ["saved bulk heat geometry is missing"]
    normal = geometry.get("normal_cartesian")
    if normal is not None and normal != [0, 0, 1]:
        raise ValueError("saved bulk heat source normal must be +z [0, 0, 1]")
    reasons: list[str] = []
    for field in ("profile_bin_ids", "periodic_channel_count", "heat_fraction", "heat_fraction_basis"):
        if field not in transport:
            reasons.append(f"transport.{field} is missing")
    channel_count = transport.get("periodic_channel_count")
    if channel_count is not None and (type(channel_count) is not int or channel_count <= 0):
        raise ValueError("bulk thermal transport periodic_channel_count must be a positive integer")
    if transport.get("heat_fraction") is not None:
        fraction = _finite(transport["heat_fraction"], "transport.heat_fraction")
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("bulk thermal transport heat_fraction must be between 0 and 1")
    basis = transport.get("heat_fraction_basis")
    if basis is not None and (not isinstance(basis, str) or not basis.strip()):
        raise ValueError("bulk thermal transport heat_fraction_basis must be a non-empty declaration")
    return transport, reasons


def _base_conditions(
    source: dict[str, Any], task: dict[str, Any], result: dict[str, Any],
    observation_window: dict[str, Any] | None, transport: dict[str, Any], source_refs: list[str],
) -> dict[str, Any]:
    return {
        "observation_window": copy.deepcopy(observation_window),
        "direction_cartesian": copy.deepcopy(transport.get("direction_cartesian")),
        "profile_bin_ids": copy.deepcopy(transport.get("profile_bin_ids")),
        "periodic_channel_count": transport.get("periodic_channel_count"),
        "heat_fraction": transport.get("heat_fraction"),
        "heat_fraction_basis": transport.get("heat_fraction_basis"),
        "source_schema": source.get("schema"),
        "source_units": source.get("units"),
        "protocol": copy.deepcopy(source.get("protocol")),
        "source_files": copy.deepcopy(source.get("source_files")),
        "source_refs": list(source_refs),
        "task_id": task.get("task_id"),
        "study_id": task.get("study_id"),
        "case_id": task.get("case_id"),
        "model_id": task.get("model_id"),
        "model_version": task.get("model_version"),
        "method_set": task.get("method_set"),
        "potential": copy.deepcopy(task.get("potential")),
        "task_protocol": copy.deepcopy(task.get("protocol")),
        "task_status": task.get("status"),
        "task_scientific_status": task.get("scientific_status"),
        "task_production_qualification": task.get("production_qualification"),
        "task_sampling_equilibrium_qualified": task.get("sampling_equilibrium_qualified"),
        "task_scheduler_state": task.get("scheduler_state"),
        "task_exit_code": task.get("exit_code"),
        "result_status": result.get("status"),
        "result_scientific_status": result.get("scientific_status"),
        "result_production_qualification": result.get("production_qualification"),
        "result_sampling_equilibrium_qualified": result.get("sampling_equilibrium_qualified"),
        "result_scheduler_state": result.get("scheduler_state"),
        "result_exit_code": result.get("exit_code"),
        "result_potential": copy.deepcopy(result.get("potential")),
        "reservoir_tally_convention": copy.deepcopy(source.get("reservoir_tally_convention")),
        "native_job": {
            "scheduler_job_id": task.get("scheduler_job_id"),
            "scheduler_state": task.get("scheduler_state"),
            "exit_code": task.get("exit_code"),
            "result_scheduler_state": result.get("scheduler_state"),
            "result_exit_code": result.get("exit_code"),
        },
        "missing_evidence": copy.deepcopy(source.get("missing_evidence")),
        "steady_state": {"status": "unresolved", "reason": "not_evaluated_by_bulk_transport_conversion"},
        "finite_sampling": "selected native observation window only",
    }


def _coordinate_conditions(transport: dict[str, Any]) -> dict[str, Any]:
    return {
        "basis": "source_cartesian",
        "direction": copy.deepcopy(transport.get("direction_cartesian")),
        "direction_cartesian": copy.deepcopy(transport.get("direction_cartesian")),
    }


def _join_reasons(*reasons: str | None) -> str | None:
    values = [reason for reason in reasons if reason]
    return "; ".join(dict.fromkeys(values)) if values else None


def build_bulk_thermal_transport(request_path: str | Path) -> dict[str, Any]:
    """Build a domain-parameter product from explicitly saved NEMD sources."""

    request_file, request, study, model, source, task, result, source_refs = _load_request(request_path)
    observation_window = request.get("observation_window")
    transport, contract_reasons = _transport_contract(request, source)
    energy_rows, energy_window_reason = _select_rows(
        source.get("energy_rows"), observation_window, "bulk heat energy"
    )
    hot_fit, hot_fit_reason = _energy_fit(energy_rows, "hot_reservoir_eV")
    cold_fit, cold_fit_reason = _energy_fit(energy_rows, "cold_reservoir_eV")
    hot_power, hot_power_reason = _power_from_fit(hot_fit, hot_fit_reason, sign=-1.0)
    cold_power, cold_power_reason = _power_from_fit(cold_fit, cold_fit_reason, sign=1.0)
    hot_power_reason = _join_reasons(energy_window_reason, hot_power_reason)
    cold_power_reason = _join_reasons(energy_window_reason, cold_power_reason)

    bin_ids = transport.get("profile_bin_ids")
    if not isinstance(bin_ids, list):
        bin_ids = []
    profile_report, profile_reason = _profile_summary(
        source.get("profile_frames"), bin_ids, observation_window
    )
    if "transport.profile_bin_ids is missing" in contract_reasons:
        profile_reason = _join_reasons(profile_reason, "transport.profile_bin_ids is missing")

    geometry = source.get("geometry")
    geometry_reason = None
    if not isinstance(geometry, dict):
        geometry = {}
        geometry_reason = "saved bulk heat geometry is missing"
    area = geometry.get("area_angstrom2")
    if area is None:
        geometry_reason = _join_reasons(geometry_reason, "saved bulk heat area is missing")
    else:
        area = _finite(area, "geometry.area_angstrom2")
        if area <= 0.0:
            raise ValueError("geometry.area_angstrom2 must be positive")
    if geometry.get("normal_cartesian") is None:
        geometry_reason = _join_reasons(geometry_reason, "saved bulk heat normal is missing")

    atom_mapping_ref = source.get("atom_mapping_ref")
    if isinstance(atom_mapping_ref, str) and atom_mapping_ref:
        if not Path(atom_mapping_ref).is_absolute():
            atom_mapping_ref = str((_request_path(request["source_path"], request_file).parent / atom_mapping_ref).resolve())
    else:
        atom_mapping_ref = None
    if atom_mapping_ref is not None:
        source_refs = list(dict.fromkeys(source_refs + [atom_mapping_ref]))

    base_conditions = _base_conditions(
        source, task, result, observation_window, transport, source_refs
    )
    base_conditions.update({
        "request_path": str(request_file),
        "study_path": str(_request_path(request["study_path"], request_file)),
        "model_path": str(_request_path(request["model_path"], request_file) / "model.json"),
        "task_path": str(_request_path(request["task_path"], request_file)),
        "result_path": str(_request_path(request["result_path"], request_file)),
        "source_path": str(_request_path(request["source_path"], request_file)),
        "source_atom_ids": copy.deepcopy(source.get("source_atom_ids")),
        "source_cell_angstrom": copy.deepcopy(source.get("cell_angstrom")),
        "geometry": copy.deepcopy(geometry),
    })

    energy_conditions = {
        **base_conditions,
        "energy_observation": {
            "selected_step_range": [energy_rows[0]["step"], energy_rows[-1]["step"]]
            if energy_rows else None,
            "selected_sample_count": len(energy_rows) if energy_rows else 0,
            "time_unit": "ps",
            "reservoir_energy_unit": "eV",
            "hot_fit": copy.deepcopy(hot_fit),
            "cold_fit": copy.deepcopy(cold_fit),
        },
        "power_conversion": "eV/ps to W using elementary_charge*1e12",
    }
    hot_conditions = {
        **energy_conditions,
        "reservoir": "hot",
        "sign_definition": "P_hot=-slope(Q_hot)",
    }
    cold_conditions = {
        **energy_conditions,
        "reservoir": "cold",
        "sign_definition": "P_cold=+slope(Q_cold)",
    }
    properties = [
        _property(
            name="hot_reservoir_input_power",
            value=hot_power,
            unit="W",
            definition="negative ordinary-fit slope of the saved hot reservoir cumulative energy",
            conditions=hot_conditions,
            coordinates="not_applicable_to_scalar",
            atom_mapping_ref=atom_mapping_ref,
            source_refs=source_refs,
            reason=hot_power_reason,
        ),
        _property(
            name="cold_reservoir_extraction_power",
            value=cold_power,
            unit="W",
            definition="positive ordinary-fit slope of the saved cold reservoir cumulative energy",
            conditions=cold_conditions,
            coordinates="not_applicable_to_scalar",
            atom_mapping_ref=atom_mapping_ref,
            source_refs=source_refs,
            reason=cold_power_reason,
        ),
    ]
    net_power = None
    net_reason = _join_reasons(hot_power_reason, cold_power_reason)
    if net_reason is None:
        net_power = hot_power - cold_power
    net_conditions = {
        **energy_conditions,
        "heat_balance": {
            "hot_input_W": hot_power,
            "cold_extraction_W": cold_power,
            "net_definition": "hot-cold",
            "net_W": net_power,
            "residual_W": net_power,
        },
    }
    properties.append(_property(
        name="reservoir_net_power",
        value=net_power,
        unit="W",
        definition="hot reservoir input power minus cold reservoir extraction power",
        conditions=net_conditions,
        coordinates="not_applicable_to_scalar",
        atom_mapping_ref=atom_mapping_ref,
        source_refs=source_refs,
        reason=net_reason,
    ))

    flux_reasons = [reason for reason in contract_reasons if "profile_bin_ids" not in reason]
    if geometry_reason is not None:
        flux_reasons.append(geometry_reason)
    if hot_power is None:
        flux_reasons.append(hot_power_reason or "hot reservoir input power is unresolved")
    flux_value = None
    if not flux_reasons:
        flux_value = transport["heat_fraction"] * hot_power / (area * 1.0e-20)
    flux_reason = _join_reasons(*flux_reasons)
    flux_conditions = {
        **base_conditions,
        "area_angstrom2": area,
        "area_unit": "angstrom^2",
        "normal_cartesian": copy.deepcopy(geometry.get("normal_cartesian")),
        "hot_input_power_W": hot_power,
        "heat_fraction_basis": transport.get("heat_fraction_basis"),
        "heat_flux_definition": "heat_fraction*hot_input_power/area along +z",
    }
    properties.append(_property(
        name="directional_heat_flux",
        value=flux_value,
        unit="W/m^2",
        definition="declared fraction of hot reservoir input power divided by the fixed xy area along +z",
        conditions=flux_conditions,
        coordinates=_coordinate_conditions(transport),
        atom_mapping_ref=atom_mapping_ref,
        source_refs=source_refs,
        reason=flux_reason,
    ))

    gradient_value = None
    gradient_reason = profile_reason
    profile_fit = profile_report.get("fit") if isinstance(profile_report, dict) else None
    if gradient_reason is None and (not isinstance(profile_fit, dict) or profile_fit.get("status") != "available"):
        gradient_reason = "profile temperature fit is unresolved"
    if gradient_reason is None:
        gradient_value = profile_fit["slope_K_per_m"]
    gradient_conditions = {
        **base_conditions,
        "profile": copy.deepcopy(profile_report),
        "gradient_K_per_angstrom": profile_fit.get("slope_K_per_angstrom") if isinstance(profile_fit, dict) else None,
        "gradient_unit_K_per_angstrom": "K/angstrom",
        "gradient_unit": "K/m",
        "profile_fit_residuals_K": profile_fit.get("residuals_K") if isinstance(profile_fit, dict) else None,
    }
    properties.append(_property(
        name="directional_temperature_gradient",
        value=gradient_value,
        unit="K/m",
        definition="ordinary least-squares fit of selected-bin mean temperatures versus saved z coordinates",
        conditions=gradient_conditions,
        coordinates=_coordinate_conditions(transport),
        atom_mapping_ref=atom_mapping_ref,
        source_refs=source_refs,
        reason=gradient_reason,
    ))

    kappa_reasons = _join_reasons(flux_reason, gradient_reason)
    if kappa_reasons is None and gradient_value == 0.0:
        kappa_reasons = "directional temperature gradient is zero"
    kappa_value = None if kappa_reasons is not None else -flux_value / gradient_value
    kappa_conditions = {
        **base_conditions,
        "heat_flux_W_per_m2": flux_value,
        "temperature_gradient_K_per_m": gradient_value,
        "temperature_gradient_K_per_angstrom": profile_fit.get("slope_K_per_angstrom") if isinstance(profile_fit, dict) else None,
        "profile": copy.deepcopy(profile_report),
        "thermal_conductivity_definition": "-directional_heat_flux/directional_temperature_gradient",
    }
    properties.append(_property(
        name="directional_thermal_conductivity",
        value=kappa_value,
        unit="W/(m K)",
        definition="directional thermal conductivity from the declared +z heat flux and fitted temperature gradient",
        conditions=kappa_conditions,
        coordinates=_coordinate_conditions(transport),
        atom_mapping_ref=atom_mapping_ref,
        source_refs=source_refs,
        reason=kappa_reasons,
    ))

    native_job = {
        "task_id": task.get("task_id"),
        "scheduler_job_id": task.get("scheduler_job_id"),
        "scheduler_state": task.get("scheduler_state"),
        "exit_code": task.get("exit_code"),
        "result_scheduler_state": result.get("scheduler_state"),
        "result_exit_code": result.get("exit_code"),
    }
    execution = {
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "native_jobs": [native_job],
    }
    return domain_parameter_product(
        kind=DOMAIN_KIND,
        model={"model_id": model["model_id"], "version": model["version"]},
        study={"study_id": study["study_id"], "case_id": study["case_id"]},
        properties=properties,
        execution=execution,
    )


__all__ = ["REQUEST_SCHEMA", "SOURCE_SCHEMA", "build_bulk_thermal_transport"]


