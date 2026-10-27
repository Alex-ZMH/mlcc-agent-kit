"""Explicit atom-tracer MSD and Fick-window diagnostics."""

from __future__ import annotations

import copy
import math
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


MSD_SCHEMA = "mlcc.md-msd.v1"


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite numeric value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite numeric value")
    return result


def _atom_ids(value: Any, name: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    result = []
    seen: set[int] = set()
    for atom_id in value:
        if type(atom_id) is not int:
            raise ValueError(f"{name} must contain integer atom IDs")
        if atom_id in seen:
            raise ValueError(f"{name} must not contain duplicate atom IDs")
        seen.add(atom_id)
        result.append(atom_id)
    return result


def _validate_request(request: Mapping[str, Any]) -> tuple[list[int], dict[str, float], dict[str, Any] | None]:
    source_atom_ids = _atom_ids(request["source_atom_ids"], "request.source_atom_ids")
    if request["dimensions"] != 3:
        raise ValueError("MSD tracer dimensions must be 3")
    if request["com_policy"] != "none":
        raise ValueError("MSD tracer com_policy must be none")
    window = request["fick_window"]
    if not isinstance(window, Mapping):
        raise ValueError("MSD fick_window must be an object")
    start_ps = _number(window["start_ps"], "fick_window.start_ps")
    end_ps = _number(window["end_ps"], "fick_window.end_ps")
    if start_ps <= 0.0 or end_ps <= start_ps:
        raise ValueError("fick_window requires 0 < start_ps < end_ps")
    raw_thresholds = request.get("thresholds")
    if raw_thresholds is None:
        thresholds = None
    else:
        if not isinstance(raw_thresholds, Mapping):
            raise ValueError("MSD thresholds must be an object")
        unknown = set(raw_thresholds) - {
            "minimum_r_squared",
            "maximum_relative_slope_spread",
            "log_msd_exponent_range",
            "minimum_msd_change_A2",
        }
        if unknown:
            raise ValueError(f"unsupported MSD threshold: {next(iter(unknown))}")
        thresholds = {}
        for name in ("minimum_r_squared", "maximum_relative_slope_spread", "minimum_msd_change_A2"):
            if name in raw_thresholds:
                value = _number(raw_thresholds[name], f"thresholds.{name}")
                if value < 0.0:
                    raise ValueError(f"thresholds.{name} must be non-negative")
                thresholds[name] = value
        if "log_msd_exponent_range" in raw_thresholds:
            exponent_range = raw_thresholds["log_msd_exponent_range"]
            if not isinstance(exponent_range, list) or len(exponent_range) != 2:
                raise ValueError("thresholds.log_msd_exponent_range must contain two values")
            lower = _number(exponent_range[0], "thresholds.log_msd_exponent_range[0]")
            upper = _number(exponent_range[1], "thresholds.log_msd_exponent_range[1]")
            if lower > upper:
                raise ValueError("log-MSD exponent range lower bound must not exceed upper bound")
            thresholds["log_msd_exponent_range"] = [lower, upper]
    return source_atom_ids, {"start_ps": start_ps, "end_ps": end_ps}, thresholds


def _validate_frames(
    frames: Sequence[Mapping[str, Any]], source_atom_ids: Sequence[int]
) -> tuple[list[dict[str, Any]], list[float], list[list[list[float]]]]:
    normalized: list[dict[str, Any]] = []
    times: list[float] = []
    selected_positions: list[list[list[float]]] = []
    for frame_index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise ValueError(f"MSD frame {frame_index} must be an object")
        step = frame["step"]
        if type(step) is not int:
            raise ValueError(f"MSD frame {frame_index} step must be an integer")
        time_ps = _number(frame["physical_time_ps"], f"frames[{frame_index}].physical_time_ps")
        frame_ids = _atom_ids(frame["source_atom_ids"], f"frames[{frame_index}].source_atom_ids")
        positions = frame["positions_angstrom"]
        if not isinstance(positions, list) or len(positions) != len(frame_ids):
            raise ValueError(f"MSD frame {frame_index} positions must match source_atom_ids")
        coordinates: list[list[float]] = []
        for atom_index, point in enumerate(positions):
            if not isinstance(point, list) or len(point) != 3:
                raise ValueError(f"MSD frame {frame_index} position {atom_index} must have three coordinates")
            coordinates.append([
                _number(value, f"frames[{frame_index}].positions_angstrom[{atom_index}]")
                for value in point
            ])
        mapping = {atom_id: index for index, atom_id in enumerate(frame_ids)}
        missing = [atom_id for atom_id in source_atom_ids if atom_id not in mapping]
        if missing:
            raise ValueError(f"MSD requested atom IDs absent from frame {frame_index}: {missing}")
        normalized.append({
            "step": step,
            "physical_time_ps": frame["physical_time_ps"],
            "source_atom_ids": copy.deepcopy(frame_ids),
            "positions_angstrom": copy.deepcopy(frame["positions_angstrom"]),
        })
        times.append(time_ps)
        selected_positions.append([coordinates[mapping[atom_id]] for atom_id in source_atom_ids])
    return normalized, times, selected_positions


def _time_status(times: Sequence[float]) -> tuple[bool, str | None, float | None]:
    if len(times) < 2:
        return False, "at least two frames are required", None
    if any(right <= left for left, right in zip(times, times[1:])):
        return False, "physical_time_ps must be strictly increasing", None
    interval = times[1] - times[0]
    if any(not math.isclose(right - left, interval, rel_tol=1.0e-8, abs_tol=1.0e-12)
           for left, right in zip(times, times[1:])):
        return False, "physical_time_ps sampling is nonuniform", None
    return True, None, interval


def _compute_lags(
    times: Sequence[float], selected_positions: Sequence[Sequence[Sequence[float]]]
) -> tuple[list[float], list[float], list[int], list[int]]:
    lag_ps: list[float] = []
    msd: list[float] = []
    origin_counts: list[int] = []
    pair_counts: list[int] = []
    atom_count = len(selected_positions[0])
    for lag_index in range(1, len(times)):
        origins = len(times) - lag_index
        squared: list[float] = []
        actual_lags: list[float] = []
        for origin in range(origins):
            actual_lags.append(float(times[origin + lag_index] - times[origin]))
            for atom_index in range(atom_count):
                first = selected_positions[origin][atom_index]
                last = selected_positions[origin + lag_index][atom_index]
                squared.append(sum((last[axis] - first[axis]) ** 2 for axis in range(3)))
        lag_ps.append(math.fsum(actual_lags) / len(actual_lags))
        msd.append(math.fsum(squared) / len(squared))
        origin_counts.append(origins)
        pair_counts.append(len(squared))
    return lag_ps, msd, origin_counts, pair_counts


def _linear_fit(x: Sequence[float], y: Sequence[float]) -> dict[str, Any]:
    if len(x) < 2:
        return {"status": "unresolved", "reason": "fewer_than_two_fit_points"}
    mean_x = math.fsum(x) / len(x)
    mean_y = math.fsum(y) / len(y)
    denominator = math.fsum((value - mean_x) ** 2 for value in x)
    if denominator <= 0.0:
        return {"status": "unresolved", "reason": "fit_axis_has_zero_extent"}
    is_constant = all(value == y[0] for value in y)
    slope = 0.0 if is_constant else math.fsum(
        (a - mean_x) * (b - mean_y) for a, b in zip(x, y)
    ) / denominator
    intercept = y[0] if is_constant else mean_y - slope * mean_x
    residuals = [float(b - (intercept + slope * a)) for a, b in zip(x, y)]
    rss = math.fsum(value * value for value in residuals)
    total = 0.0 if is_constant else math.fsum((value - mean_y) ** 2 for value in y)
    if total == 0.0:
        r_squared = None
        r2_reason = "constant_values_r_squared_undefined"
    else:
        r_squared = float(1.0 - rss / total)
        r2_reason = None
    return {
        "status": "available",
        "slope": float(slope),
        "intercept": float(intercept),
        "residuals": residuals,
        "r_squared": r_squared,
        "r_squared_unresolved_reason": r2_reason,
        "duration_ps": float(x[-1] - x[0]),
        "count": len(x),
        "reason": None,
    }


def _fit_report(x: Sequence[float], y: Sequence[float]) -> dict[str, Any]:
    fit = _linear_fit(x, y)
    if fit["status"] != "available":
        return fit
    return {
        "status": fit["status"],
        "lag_ps": [float(value) for value in x],
        "MSD_A2": [float(value) for value in y],
        "slope_A2_per_ps": fit["slope"],
        "intercept_A2": fit["intercept"],
        "residuals_A2": fit["residuals"],
        "r_squared": fit["r_squared"],
        "r_squared_unresolved_reason": fit["r_squared_unresolved_reason"],
        "duration_ps": fit["duration_ps"],
        "count": fit["count"],
        "reason": fit["reason"],
    }


def _empty_fick(window: Mapping[str, float], reason: str) -> dict[str, Any]:
    return {
        "status": "unresolved",
        "window_ps": [window["start_ps"], window["end_ps"]],
        "selected_lag_indices": [],
        "selected_lag_ps": [],
        "fit": None,
        "half_fits": {"first": None, "second": None},
        "subwindow_slopes_A2_per_ps": None,
        "relative_slope_spread": None,
        "relative_slope_spread_unresolved_reason": reason,
        "log_msd_exponent": None,
        "log_msd_exponent_unresolved_reason": reason,
        "diagnostics": None,
        "reason": reason,
    }


def _diagnostics(
    fit: Mapping[str, Any],
    first_half: Mapping[str, Any],
    second_half: Mapping[str, Any],
    log_fit: Mapping[str, Any] | None,
    fit_msd: Sequence[float],
    thresholds: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], float | None, list[str]]:
    checks: dict[str, Any] = {}

    def check(name: str, observed: float | None, threshold: Any, predicate: str) -> None:
        if threshold is None:
            checks[name] = {"status": "unresolved", "observed": observed,
                            "threshold": None, "reason": "threshold was not provided"}
        elif observed is None:
            checks[name] = {"status": "unresolved", "observed": None,
                            "threshold": threshold, "reason": "diagnostic quantity is unresolved"}
        else:
            passed = (
                observed >= threshold if predicate == "minimum" else
                observed <= threshold if predicate == "maximum" else
                threshold[0] <= observed <= threshold[1]
            )
            checks[name] = {"status": "pass" if passed else "fail", "observed": observed,
                            "threshold": threshold, "reason": None if passed else "threshold failed"}

    thresholds = {} if thresholds is None else thresholds
    check("minimum_r_squared", fit.get("r_squared"), thresholds.get("minimum_r_squared"), "minimum")
    relative_spread = fit.get("relative_slope_spread")
    check("maximum_relative_slope_spread", relative_spread,
          thresholds.get("maximum_relative_slope_spread"), "maximum")
    log_exponent = None if log_fit is None else log_fit.get("exponent")
    check("log_msd_exponent_range", log_exponent,
          thresholds.get("log_msd_exponent_range"), "range")
    change = None if len(fit_msd) < 2 else float(fit_msd[-1] - fit_msd[0])
    minimum_change = thresholds.get("minimum_msd_change_A2")
    if minimum_change is None:
        checks["minimum_msd_change_A2"] = {
            "status": "not_requested", "observed": change, "threshold": None, "reason": None,
        }
    else:
        check("minimum_msd_change_A2", change, minimum_change, "minimum")
    slope = fit.get("slope_A2_per_ps")
    if slope is None:
        checks["positive_slope"] = {"status": "unresolved", "observed": None,
                                     "threshold": 0.0, "reason": "MSD fit slope is unresolved"}
    else:
        checks["positive_slope"] = {"status": "pass" if slope > 0.0 else "fail",
                                     "observed": slope, "threshold": 0.0,
                                     "reason": None if slope > 0.0 else "MSD fit slope is not positive"}
    statuses = [item["status"] for item in checks.values() if item["status"] != "not_requested"]
    if any(status == "fail" for status in statuses):
        status = "fail"
    elif any(status == "unresolved" for status in statuses):
        status = "unresolved"
    else:
        status = "pass"
    reasons = [f"{name}: {item['reason']}" for name, item in checks.items() if item["reason"]]
    return {"status": status, "checks": checks}, change, reasons


def compute_tracer_msd(frames: Sequence[Mapping[str, Any]], *, request: Mapping[str, Any]) -> dict[str, Any]:
    """Compute three-dimensional atom-tracer MSD from unwrapped fixed-cell frames."""

    source_atom_ids, window, thresholds = _validate_request(request)
    frame_list = list(frames)
    raw_frames = copy.deepcopy(frame_list)
    normalized, times, selected_positions = _validate_frames(frame_list, source_atom_ids)
    base = {
        "schema": MSD_SCHEMA,
        "status": "unresolved",
        "production_qualified": False,
        "request": copy.deepcopy(dict(request)),
        "dimensions": 3,
        "com_policy": "none",
        "source_atom_ids": source_atom_ids,
        "frames": raw_frames,
        "frame_steps": [frame["step"] for frame in normalized],
        "physical_time_ps": [frame["physical_time_ps"] for frame in normalized],
        "lag_ps": None,
        "MSD_A2": None,
        "MSD_A2_unresolved_reason": None,
        "origin_count": None,
        "atom_origin_pair_count": None,
        "D_A2_per_ps": None,
        "D_A2_per_ps_unresolved_reason": "MSD is unresolved",
        "D_m2_per_s": None,
        "D_m2_per_s_unresolved_reason": "MSD is unresolved",
        "units": {
            "physical_time_ps": "ps",
            "lag_ps": "ps",
            "MSD_A2": "angstrom^2",
            "D_A2_per_ps": "angstrom^2/ps",
            "D_m2_per_s": "m^2/s",
        },
        "time": {"status": "unresolved", "interval_ps": None, "reason": None},
        "fick": _empty_fick(window, "time sampling has not been validated"),
        "diffusivity": {"status": "unresolved", "reason": "MSD is unresolved"},
        "unresolved_reasons": [],
    }
    time_valid, time_reason, interval_ps = _time_status(times)
    if not time_valid:
        base["time"] = {"status": "unresolved", "interval_ps": interval_ps, "reason": time_reason}
        base["MSD_A2_unresolved_reason"] = time_reason
        base["D_A2_per_ps_unresolved_reason"] = time_reason
        base["D_m2_per_s_unresolved_reason"] = time_reason
        base["unresolved_reasons"] = [time_reason]
        return base
    base["time"] = {"status": "available", "interval_ps": interval_ps, "reason": None}
    lag_ps, msd, origin_counts, pair_counts = _compute_lags(times, selected_positions)
    base["lag_ps"] = lag_ps
    base["MSD_A2"] = msd
    base["origin_count"] = origin_counts
    base["atom_origin_pair_count"] = pair_counts
    selected = [index for index, lag in enumerate(lag_ps) if window["start_ps"] <= lag <= window["end_ps"]]
    selected_frame_lags = [index + 1 for index in selected]
    fit_msd = [msd[index] for index in selected]
    fit_lags = [lag_ps[index] for index in selected]
    if len(selected) < 4:
        base["fick"] = _empty_fick(window, "fick_window requires at least four positive lag points")
        base["fick"]["selected_lag_indices"] = selected_frame_lags
        base["fick"]["selected_lag_ps"] = fit_lags
        base["unresolved_reasons"] = [base["fick"]["reason"]]
        base["diffusivity"]["reason"] = base["fick"]["reason"]
        base["D_A2_per_ps_unresolved_reason"] = base["fick"]["reason"]
        base["D_m2_per_s_unresolved_reason"] = base["fick"]["reason"]
        base["status"] = "partial"
        return base
    if min(origin_counts[index] for index in selected) < 2:
        reason = "fick_window endpoint requires at least two time origins"
        base["fick"] = _empty_fick(window, reason)
        base["fick"]["selected_lag_indices"] = selected_frame_lags
        base["fick"]["selected_lag_ps"] = fit_lags
        base["unresolved_reasons"] = [reason]
        base["diffusivity"]["reason"] = reason
        base["D_A2_per_ps_unresolved_reason"] = reason
        base["D_m2_per_s_unresolved_reason"] = reason
        base["status"] = "partial"
        return base
    split = len(selected) // 2
    if split < 2 or len(selected) - split < 2:
        reason = "each Fick half-window requires at least two lag points"
        base["fick"] = _empty_fick(window, reason)
        base["fick"]["selected_lag_indices"] = selected_frame_lags
        base["fick"]["selected_lag_ps"] = fit_lags
        base["unresolved_reasons"] = [reason]
        base["diffusivity"]["reason"] = reason
        base["D_A2_per_ps_unresolved_reason"] = reason
        base["D_m2_per_s_unresolved_reason"] = reason
        base["status"] = "partial"
        return base
    fit = _fit_report(fit_lags, fit_msd)
    first_fit = _fit_report(fit_lags[:split], fit_msd[:split])
    second_fit = _fit_report(fit_lags[split:], fit_msd[split:])
    if fit["status"] != "available" or first_fit["status"] != "available" or second_fit["status"] != "available":
        reason = "Fick OLS fit is unresolved"
        base["fick"] = _empty_fick(window, reason)
        base["fick"]["selected_lag_indices"] = selected_frame_lags
        base["fick"]["selected_lag_ps"] = fit_lags
        base["fick"]["fit"] = fit
        base["fick"]["half_fits"] = {"first": first_fit, "second": second_fit}
        base["unresolved_reasons"] = [reason]
        base["diffusivity"]["reason"] = reason
        base["D_A2_per_ps_unresolved_reason"] = reason
        base["D_m2_per_s_unresolved_reason"] = reason
        base["status"] = "partial"
        return base
    slope = fit["slope_A2_per_ps"]
    if slope == 0.0:
        relative_spread = None
        spread_reason = "overall MSD slope is zero"
    else:
        relative_spread = abs(first_fit["slope_A2_per_ps"] - second_fit["slope_A2_per_ps"]) / abs(slope)
        spread_reason = None
    fit["relative_slope_spread"] = relative_spread
    fit["relative_slope_spread_unresolved_reason"] = spread_reason
    if min(fit_msd) <= 0.0:
        log_fit = None
        log_reason = "log-MSD exponent requires strictly positive MSD values"
    else:
        log_lags = [math.log(value) for value in fit_lags]
        log_values = [math.log(value) for value in fit_msd]
        raw_log_fit = _linear_fit(log_lags, log_values)
        log_fit = {
            "status": raw_log_fit["status"],
            "log_lag_relative_to_1ps": log_lags,
            "log_msd_relative_to_1A2": log_values,
            "exponent": raw_log_fit.get("slope"),
            "intercept": raw_log_fit.get("intercept"),
            "residuals": raw_log_fit.get("residuals"),
            "r_squared": raw_log_fit.get("r_squared"),
            "r_squared_unresolved_reason": raw_log_fit.get("r_squared_unresolved_reason"),
            "count": raw_log_fit.get("count"),
            "reason": raw_log_fit.get("reason"),
        }
        log_reason = None
    diagnostics, change, diagnostic_reasons = _diagnostics(
        fit, first_fit, second_fit, log_fit, fit_msd, thresholds
    )
    if relative_spread is None:
        diagnostics["checks"]["maximum_relative_slope_spread"] = {
            "status": "unresolved", "observed": None,
            "threshold": None if thresholds is None else thresholds.get("maximum_relative_slope_spread"),
            "reason": spread_reason,
        }
        diagnostics["status"] = "unresolved" if diagnostics["status"] == "pass" else diagnostics["status"]
    if log_reason is not None:
        diagnostics["checks"]["log_msd_exponent_range"] = {
            "status": "unresolved", "observed": None,
            "threshold": None if thresholds is None else thresholds.get("log_msd_exponent_range"),
            "reason": log_reason,
        }
        diagnostics["status"] = "unresolved" if diagnostics["status"] == "pass" else diagnostics["status"]
        diagnostic_reasons.append(log_reason)
    fick_status = "available" if diagnostics["status"] == "pass" else "partial"
    base["fick"] = {
        "status": fick_status,
        "window_ps": [window["start_ps"], window["end_ps"]],
        "selected_lag_indices": selected_frame_lags,
        "selected_lag_ps": fit_lags,
        "fit": fit,
        "half_fits": {"first": first_fit, "second": second_fit},
        "subwindow_slopes_A2_per_ps": [first_fit["slope_A2_per_ps"], second_fit["slope_A2_per_ps"]],
        "relative_slope_spread": relative_spread,
        "relative_slope_spread_unresolved_reason": spread_reason,
        "log_fit": log_fit,
        "log_msd_exponent": None if log_fit is None else log_fit.get("exponent"),
        "log_msd_exponent_unresolved_reason": log_reason,
        "diagnostics": diagnostics,
        "msd_change_A2": change,
        "reason": None if diagnostics["status"] == "pass" else "Fick diagnostic thresholds are not all passed",
    }
    if diagnostics["status"] == "pass" and slope > 0.0:
        base["D_A2_per_ps"] = slope / 6.0
        base["D_m2_per_s"] = base["D_A2_per_ps"] * 1.0e-8
        base["diffusivity"] = {
            "status": "available",
            "D_A2_per_ps": base["D_A2_per_ps"],
            "D_m2_per_s": base["D_m2_per_s"],
            "reason": None,
            "formula": "slope_A2_per_ps / 6 for three-dimensional tracer diffusion",
        }
        base["D_A2_per_ps_unresolved_reason"] = None
        base["D_m2_per_s_unresolved_reason"] = None
        base["status"] = "available"
    else:
        base["diffusivity"] = {
            "status": "unresolved" if diagnostics["status"] == "unresolved" else "failed",
            "D_A2_per_ps": None,
            "D_m2_per_s": None,
            "reason": "Fick diagnostic thresholds are not all passed" if diagnostics["status"] != "pass" else "MSD slope is not positive",
        }
        base["D_A2_per_ps_unresolved_reason"] = base["diffusivity"]["reason"]
        base["D_m2_per_s_unresolved_reason"] = base["diffusivity"]["reason"]
        base["status"] = "partial"
    base["unresolved_reasons"] = diagnostic_reasons
    return base


def analyze_md_msd(
    collection_path: str | Path, *, observation_window: dict[str, Any], request: Mapping[str, Any],
) -> dict[str, Any]:
    """Consume a saved collection's native unwrapped record or report its absence."""
    from .md_rdf import _observation_frames
    from .md_sources import select_md_sources
    from .md_unwrapped import unwrapped_input_commands

    path = Path(collection_path).resolve()
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["schema"] != "mlcc.md-collection.v1":
        raise ValueError("MSD requires mlcc.md-collection.v1")
    atom_ids, _, _ = _validate_request(request)
    elements = list(dict.fromkeys(record["legacy_final_result"]["elements"]))
    selection = select_md_sources(
        [path], model_id=record["model"]["model_id"], model_version=record["model"]["version"],
        potential_id=record["potential"]["potential_id"], potential_version=record["potential"]["version"],
        elements=elements,
    )
    if not set(atom_ids).issubset(record["legacy_final_result"]["atom_ids"]):
        raise ValueError("MSD requested source atom IDs are absent from collection")
    indices, observed = _observation_frames(record["trajectory"]["frames"], observation_window)
    provenance = {
        "task_id": record["task_id"], "native_job": record["native_job"],
        "model": record["model"], "potential": record["potential"], "lineage": record["lineage"],
        "source_files": record["source_files"], "source_selection": selection,
        "collection_path": str(path), "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "observation": {"request": dict(observation_window), "frame_indices": indices,
                        "step_range": [observed[0]["step"], observed[-1]["step"]],
                        "physical_time_ps_range": [observed[0]["physical_time_ps"], observed[-1]["physical_time_ps"]]},
        "production_qualification": False, "sampling_equilibrium_qualified": False,
        "scientific_status": "unqualified",
    }
    unwrapped = record.get("unwrapped_trajectory")
    if unwrapped is None:
        reason = "native xu/yu/zu trajectory and its command/source evidence are missing"
        return {
            "schema": MSD_SCHEMA, "status": "unresolved", **provenance,
            "request": copy.deepcopy(dict(request)), "source_atom_ids": atom_ids,
            "dimensions": 3, "com_policy": "none", "coordinate_basis": None,
            "lag_ps": None, "MSD_A2": None, "origin_count": None, "atom_origin_pair_count": None,
            "D_A2_per_ps": None, "D_m2_per_s": None, "fick": None,
            "MSD_A2_unresolved_reason": reason, "D_A2_per_ps_unresolved_reason": reason,
            "D_m2_per_s_unresolved_reason": reason,
            "missing_evidence": ["native_unwrapped_trajectory"], "unresolved_reasons": [reason],
            "units": {"lag_ps": "ps", "MSD_A2": "angstrom^2", "D_A2_per_ps": "angstrom^2/ps", "D_m2_per_s": "m^2/s"},
        }
    if record["protocol"].get("unwrapped_trajectory") is not True:
        raise ValueError("MSD unwrapped record lacks the explicit native protocol declaration")
    if unwrapped["schema"] != "mlcc.md-unwrapped-trajectory.v1" or unwrapped["native_columns"] != ["id", "type", "xu", "yu", "zu"]:
        raise ValueError("MSD requires the native xu/yu/zu reader product")
    if unwrapped["task_id"] != record["task_id"] or unwrapped["native_job"] != record["native_job"]:
        raise ValueError("MSD unwrapped task/job differs from collection")
    if any(unwrapped["model"][key] != record["model"][key] for key in ("model_id", "version")):
        raise ValueError("MSD unwrapped model differs from collection")
    if unwrapped["protocol"] != record["protocol"]:
        raise ValueError("MSD unwrapped protocol differs from collection")
    commands = unwrapped_input_commands(record["protocol"])
    if unwrapped["input_commands"] != commands:
        raise ValueError("MSD unwrapped command definition differs from protocol")
    for name, source_path in unwrapped["source_files"].items():
        if source_path != record["source_files"][name]:
            raise ValueError(f"MSD unwrapped source differs from collection: {name}")
        Path(source_path).stat()
    input_lines = Path(unwrapped["source_files"]["in.lammps"]).read_text(encoding="utf-8").splitlines()
    if any(command not in [line.strip() for line in input_lines] for command in commands):
        raise ValueError("MSD native input lacks the declared unwrapped commands")
    Path(unwrapped["source_files"]["trajectory.unwrapped.lammpstrj"]).stat()
    if unwrapped["fixed_cell"]["value"] is not True:
        raise ValueError("MSD currently requires a fixed cell")
    frames = unwrapped["frames"]
    if ([frame["step"] for frame in frames] != [frame["step"] for frame in record["trajectory"]["frames"]]
            or [frame["physical_time_ps"] for frame in frames] != [frame["physical_time_ps"] for frame in record["trajectory"]["frames"]]):
        raise ValueError("MSD unwrapped steps/time differ from collection")
    if any(frame["source_atom_ids"] != record["legacy_final_result"]["atom_ids"] for frame in frames):
        raise ValueError("MSD unwrapped atom mapping differs from collection")
    if any(frame["coordinate_basis"] != "source_cartesian" for frame in frames):
        raise ValueError("MSD requires the native reader's source Cartesian basis")
    _, selected_frames = _observation_frames(frames, observation_window)
    result = compute_tracer_msd(selected_frames, request=request)
    result.update(provenance)
    result.update({"missing_evidence": [], "coordinate_basis": "source_cartesian",
                   "unwrapped_source": {key: unwrapped[key] for key in ("schema", "native_columns", "source_files", "input_commands", "fixed_cell")}})
    return result


__all__ = ["compute_tracer_msd", "analyze_md_msd"]
