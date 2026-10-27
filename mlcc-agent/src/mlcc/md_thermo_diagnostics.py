"""Explicit finite-sample diagnostics for an already selected MD thermo window."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Sequence

import numpy as np


RESPONSE_SCHEMA = "mlcc.md-thermo-diagnostics.v1"
FIELD_NAMES = ("temp", "etotal", "press")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite numeric")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric")
    return float(value)


def _threshold(value: Any, name: str) -> float | None:
    if value is None:
        return None
    result = _finite(value, name)
    if result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _field_specs(request: Mapping[str, Any]) -> dict[str, dict[str, float | None]]:
    raw_fields = request["fields"]
    if not isinstance(raw_fields, Mapping) or not raw_fields:
        raise ValueError("fields must be a non-empty mapping")
    specs: dict[str, dict[str, float | None]] = {}
    for field, raw_spec in raw_fields.items():
        if field not in FIELD_NAMES:
            raise ValueError(f"unsupported thermo diagnostic field: {field}")
        if not isinstance(raw_spec, Mapping):
            raise ValueError(f"diagnostic specification for {field} must be an object")
        specs[field] = {
            "max_abs_slope_per_ps": _threshold(
                raw_spec.get("max_abs_slope_per_ps"),
                f"{field}.max_abs_slope_per_ps",
            ),
            "anomaly_z_threshold": _threshold(
                raw_spec.get("anomaly_z_threshold"),
                f"{field}.anomaly_z_threshold",
            ),
        }
    return specs


def _block_specs(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_blocks = request.get("blocks")
    if raw_blocks is None:
        return []
    if not isinstance(raw_blocks, list):
        raise ValueError("blocks must be a list when present")
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_block in raw_blocks:
        block_id = raw_block["block_id"]
        if not isinstance(block_id, str) or not block_id.strip() or block_id in seen:
            raise ValueError("block_id must be non-empty and unique")
        start = raw_block["start_step"]
        end = raw_block["end_step"]
        if type(start) is not int or type(end) is not int or end < start:
            raise ValueError(f"block {block_id} must have integer start_step <= end_step")
        seen.add(block_id)
        blocks.append({"block_id": block_id, "start_step": start, "end_step": end})
    for index, left in enumerate(blocks):
        for right in blocks[index + 1 :]:
            if left["start_step"] <= right["end_step"] and right["start_step"] <= left["end_step"]:
                raise ValueError(f"blocks {left['block_id']} and {right['block_id']} overlap")
    return blocks


def _variance(values: Sequence[float], *, reason_prefix: str) -> tuple[float | None, str | None]:
    if len(values) < 2:
        return None, f"{reason_prefix}: fewer_than_two_samples"
    if all(value == values[0] for value in values):
        return 0.0, None
    return float(np.var(np.asarray(values, dtype=float), ddof=1)), None


def _ols(times: Sequence[float], values: Sequence[float]) -> dict[str, Any]:
    if len(times) < 2:
        return {
            "status": "unresolved",
            "slope_per_ps": None,
            "intercept": None,
            "residuals": None,
            "r_squared": None,
            "r_squared_unresolved_reason": None,
            "duration_ps": None,
            "reason": "fewer_than_two_samples",
        }
    duration = float(times[-1] - times[0])
    if duration <= 0.0:
        return {
            "status": "unresolved",
            "slope_per_ps": None,
            "intercept": None,
            "residuals": None,
            "r_squared": None,
            "r_squared_unresolved_reason": None,
            "duration_ps": duration,
            "reason": "physical_time_ps has no positive span",
        }
    t = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float)
    is_constant = all(value == values[0] for value in values)
    centered_t = t - float(np.mean(t))
    centered_y = y - float(np.mean(y))
    denominator = float(np.dot(centered_t, centered_t))
    if denominator == 0.0:
        return {
            "status": "unresolved",
            "slope_per_ps": None,
            "intercept": None,
            "residuals": None,
            "r_squared": None,
            "r_squared_unresolved_reason": None,
            "duration_ps": duration,
            "reason": "physical_time_ps is degenerate",
        }
    slope = 0.0 if is_constant else float(np.dot(centered_t, centered_y) / denominator)
    intercept = float(values[0]) if is_constant else float(np.mean(y) - slope * np.mean(t))
    fitted = slope * t + intercept
    residuals = (y - fitted).tolist()
    residual_sum = float(np.dot(y - fitted, y - fitted))
    total_sum = 0.0 if is_constant else float(np.dot(centered_y, centered_y))
    if total_sum == 0.0:
        r_squared = None
        r2_reason = "constant_values_r_squared_undefined"
    else:
        r_squared = 1.0 - residual_sum / total_sum
        r2_reason = None
    return {
        "status": "available",
        "slope_per_ps": slope,
        "intercept": intercept,
        "residuals": residuals,
        "r_squared": r_squared,
        "r_squared_unresolved_reason": r2_reason,
        "duration_ps": duration,
        "reason": None,
    }


def _drift(ols: Mapping[str, Any], threshold: float | None) -> dict[str, Any]:
    slope = ols["slope_per_ps"]
    observed = None if slope is None else abs(float(slope))
    if threshold is None:
        return {
            "threshold_abs_slope_per_ps": None,
            "observed_abs_slope_per_ps": observed,
            "status": "unresolved",
            "reason": "max_abs_slope_per_ps was not provided",
        }
    if observed is None:
        return {
            "threshold_abs_slope_per_ps": threshold,
            "observed_abs_slope_per_ps": None,
            "status": "unresolved",
            "reason": "OLS slope is unresolved",
        }
    passed = observed <= threshold
    return {
        "threshold_abs_slope_per_ps": threshold,
        "observed_abs_slope_per_ps": observed,
        "status": "pass" if passed else "fail",
        "reason": None if passed else "absolute OLS slope exceeds explicit threshold",
    }


def _anomaly(
    values: Sequence[float],
    rows: Sequence[Mapping[str, Any]],
    row_indices: Sequence[int],
    threshold: float | None,
) -> dict[str, Any]:
    if not values:
        return {
            "population_std": None,
            "population_std_zero_reason": None,
            "z_scores": [],
            "threshold_z": threshold,
            "anomalies": [] if threshold is not None else None,
            "status": "unresolved",
            "reason": "no_samples",
        }
    is_constant = all(value == values[0] for value in values)
    mean = float(values[0]) if is_constant else float(np.mean(np.asarray(values, dtype=float)))
    population_std = 0.0 if is_constant else float(np.std(np.asarray(values, dtype=float), ddof=0))
    if is_constant or population_std == 0.0:
        z_scores = [0.0 for _ in values]
        zero_reason = "population standard deviation is zero; z_scores defined as zero"
    else:
        z_scores = [abs((float(value) - mean) / population_std) for value in values]
        zero_reason = None
    anomalies = None
    status = "unresolved"
    reason = "anomaly_z_threshold was not provided"
    if threshold is not None:
        anomalies = [
            {
                "row_index": int(row_index),
                "step": row["step"],
                "physical_time_ps": row["physical_time_ps"],
                "value": float(value),
                "absolute_z_score": float(z_score),
            }
            for row_index, row, value, z_score in zip(row_indices, rows, values, z_scores)
            if z_score > threshold
        ]
        status = "fail" if anomalies else "pass"
        reason = zero_reason
    return {
        "population_std": population_std,
        "population_std_zero_reason": zero_reason,
        "z_scores": z_scores,
        "threshold_z": threshold,
        "anomalies": anomalies,
        "status": status,
        "reason": reason,
    }


def _block_products(
    blocks: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    row_indices: Sequence[int],
    field_specs: Mapping[str, Mapping[str, float | None]],
    units: Mapping[str, Any],
) -> list[dict[str, Any]]:
    steps = [row["step"] for row in rows]
    products: list[dict[str, Any]] = []
    for block in blocks:
        start, end = block["start_step"], block["end_step"]
        if start not in steps or end not in steps:
            raise ValueError(f"block {block['block_id']} endpoints must be selected thermo steps")
        selected = [
            (index, row)
            for index, row in enumerate(rows)
            if start <= row["step"] <= end
        ]
        selected_indices = [int(row_indices[index]) for index, _ in selected]
        selected_steps = [row["step"] for _, row in selected]
        selected_times = [float(row["physical_time_ps"]) for _, row in selected]
        means: dict[str, float | None] = {}
        variances: dict[str, float | None] = {}
        variance_reasons: dict[str, str | None] = {}
        for field in field_specs:
            values = [_finite(row[field], f"{field} block {block['block_id']}") for _, row in selected]
            means[field] = None if not values else float(np.mean(np.asarray(values, dtype=float)))
            variance, variance_reason = _variance(values, reason_prefix=f"{field} block {block['block_id']}")
            variances[field] = variance
            variance_reasons[field] = variance_reason if variance_reason is not None else None
        products.append(
            {
                "block_id": block["block_id"],
                "start_step": start,
                "end_step": end,
                "row_indices": selected_indices,
                "steps": selected_steps,
                "physical_time_ps_range": None if not selected_times else [selected_times[0], selected_times[-1]],
                "count": len(selected),
                "mean": means,
                "sample_variance": variances,
                "sample_variance_unresolved_reason": variance_reasons,
                "units": {field: units[field] for field in field_specs},
            }
        )
    return products


def _block_mean_dispersion(
    blocks: Sequence[Mapping[str, Any]], field_specs: Mapping[str, Mapping[str, float | None]],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for field in field_specs:
        if not blocks:
            output[field] = {
                "count": 0,
                "mean": None,
                "sample_variance": None,
                "sample_variance_unresolved_reason": "blocks_not_requested",
            }
            continue
        values = [block["mean"][field] for block in blocks]
        if any(value is None for value in values):
            output[field] = {
                "count": len(values),
                "mean": None,
                "sample_variance": None,
                "sample_variance_unresolved_reason": "block_mean_unresolved",
            }
            continue
        numeric = [float(value) for value in values]
        variance, reason = _variance(numeric, reason_prefix=f"{field} block means")
        output[field] = {
            "count": len(numeric),
            "mean": float(np.mean(np.asarray(numeric, dtype=float))),
            "sample_variance": variance,
            "sample_variance_unresolved_reason": reason if reason is not None else None,
        }
    return output


def analyze_thermo_diagnostics(
    rows: Sequence[Mapping[str, Any]],
    *,
    row_indices: Sequence[int],
    units: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute explicit thermo statistics without selecting or moving a window."""

    field_specs = _field_specs(request)
    blocks = _block_specs(request)
    raw_rows = [dict(row) for row in rows]
    original_indices = list(row_indices)
    if len(original_indices) != len(raw_rows):
        raise ValueError("row_indices length must equal selected rows length")
    if any(type(index) is not int for index in original_indices):
        raise ValueError("row_indices must be integers")

    times = [_finite(row["physical_time_ps"], "physical_time_ps") for row in raw_rows]
    selected_steps = [row["step"] for row in raw_rows]
    field_products: dict[str, dict[str, Any]] = {}
    for field, thresholds in field_specs.items():
        values = [_finite(row[field], field) for row in raw_rows]
        mean = None if not values else float(np.mean(np.asarray(values, dtype=float)))
        variance, variance_reason = _variance(values, reason_prefix=field)
        ols = _ols(times, values)
        unit = units[field]
        ols["slope_unit"] = f"{unit}/ps"
        ols["intercept_unit"] = unit
        ols["residuals_unit"] = unit
        field_products[field] = {
            "unit": unit,
            "values": values,
            "mean": mean,
            "sample_variance": variance,
            "sample_variance_unit": f"{unit}^2",
            "sample_variance_unresolved_reason": variance_reason,
            "ols": ols,
            "drift": _drift(ols, thresholds["max_abs_slope_per_ps"]),
            "anomaly": _anomaly(values, raw_rows, original_indices, thresholds["anomaly_z_threshold"]),
        }

    block_products = _block_products(blocks, raw_rows, original_indices, field_specs, units)
    block_dispersion = _block_mean_dispersion(block_products, field_specs)
    unresolved = not raw_rows or any(
        product["sample_variance"] is None
        or product["ols"]["status"] == "unresolved"
        or product["drift"]["status"] == "unresolved"
        or product["anomaly"]["status"] == "unresolved"
        for product in field_products.values()
    )
    status = "unresolved" if not raw_rows else "partial" if unresolved else "available"
    return {
        "schema": RESPONSE_SCHEMA,
        "status": status,
        "production_qualified": False,
        "request": copy.deepcopy(dict(request)),
        "row_indices": original_indices,
        "steps": selected_steps,
        "physical_time_ps": times,
        "units": copy.deepcopy(dict(units)),
        "fields": field_products,
        "blocks": block_products,
        "block_mean_dispersion": block_dispersion,
        "block_mean_scope": "descriptive_block_mean_dispersion_not_replica_or_CI_SE",
    }


__all__ = ["analyze_thermo_diagnostics"]
