"""Direct thermal-response consumption for explicit layered-interface samples."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

import numpy as np

from .md_thermo import _observation_rows


REQUEST_SCHEMA = "mlcc.interface-thermal-analysis.v1"
RESPONSE_SCHEMA = "mlcc.interface-thermal-response.v1"
EV_PER_PS_TO_W = 1.602176634e-7
ANGSTROM2_TO_M2 = 1.0e-20


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _validate_request(request: Mapping[str, Any]) -> tuple[Mapping[str, Any], float, np.ndarray, list[dict[str, Any]], Any]:
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError(f"thermal analysis request schema must be {REQUEST_SCHEMA}")
    area = _finite(request["area_angstrom2"], "area_angstrom2")
    if area <= 0.0:
        raise ValueError("area_angstrom2 must be positive")
    normal = np.asarray(request["normal_cartesian"], dtype=float)
    if normal.shape != (3,) or not np.all(np.isfinite(normal)) or not np.allclose(
        normal, [0.0, 0.0, 1.0], rtol=0.0, atol=1.0e-12
    ):
        raise ValueError("normal_cartesian must be [0, 0, 1]")
    if request["interface_count"] != 2:
        raise ValueError("interface_count must be exactly 2")
    pairs = list(request["temperature_pairs"])
    if pairs and (len(pairs) != 2 or {pair["interface_id"] for pair in pairs} != {"AB", "BA"}):
        raise ValueError("temperature_pairs must contain exactly AB and BA when specified")
    for pair in pairs:
        if pair["direction_sign"] not in (-1, 1):
            raise ValueError("temperature pair direction_sign must be +1 or -1")
        upstream_ids = list(pair["upstream_bin_ids"])
        downstream_ids = list(pair["downstream_bin_ids"])
        if not upstream_ids or not downstream_ids:
            raise ValueError("temperature pair bin groups must be non-empty")
        if any(type(bin_id) is not int for bin_id in upstream_ids + downstream_ids):
            raise ValueError("temperature pair bin IDs must be integers")
        if len(set(upstream_ids)) != len(upstream_ids) or len(set(downstream_ids)) != len(downstream_ids):
            raise ValueError("temperature pair bin IDs must be unique within each side")
        if set(upstream_ids) & set(downstream_ids):
            raise ValueError("temperature pair upstream and downstream bins must not overlap")
    allocation = request.get("heat_allocation")
    if allocation is not None:
        if allocation["power_reference"] != "hot_input":
            raise ValueError("heat_allocation.power_reference must be hot_input")
        fractions = allocation["fractions"]
        values = {key: _finite(fractions[key], f"heat_allocation.fractions.{key}") for key in ("AB", "BA")}
        if any(value < 0.0 for value in values.values()) or not np.isclose(
            values["AB"] + values["BA"], 1.0, rtol=0.0, atol=1.0e-12
        ):
            raise ValueError("heat_allocation fractions must be non-negative and sum to 1")
        if not isinstance(allocation["source"], str) or not allocation["source"].strip():
            raise ValueError("heat_allocation.source must be non-empty")
    return request, area, normal, pairs, allocation


def _select_observation_rows(rows: list[dict[str, Any]], window: Any) -> tuple[list[int] | None, list[dict[str, Any]] | None, str | None]:
    if window is None:
        return None, None, "observation_window is unresolved"
    indices, selected = _observation_rows(rows, window)
    return indices, [dict(row) for row in selected], None


def _power(rows: list[dict[str, Any]] | None, area: float) -> dict[str, Any]:
    if rows is None:
        return {
            "status": "unresolved",
            "reason": "selected energy window is unresolved",
            "time_span_ps": None,
            "area_m2": area * ANGSTROM2_TO_M2,
            "hot_input_eV_per_ps": None,
            "cold_extraction_eV_per_ps": None,
            "net_power_eV_per_ps": None,
            "hot_input_W": None,
            "cold_extraction_W": None,
            "net_power_W": None,
            "total_source_power_per_area_W_per_m2": None,
        }
    if len(rows) < 2:
        return {
            "status": "unresolved",
            "reason": "selected energy window needs at least two samples",
            "time_span_ps": None,
            "area_m2": area * ANGSTROM2_TO_M2,
            "hot_input_eV_per_ps": None,
            "cold_extraction_eV_per_ps": None,
            "net_power_eV_per_ps": None,
            "hot_input_W": None,
            "cold_extraction_W": None,
            "net_power_W": None,
            "total_source_power_per_area_W_per_m2": None,
        }
    start, end = rows[0], rows[-1]
    dt = _finite(end["physical_time_ps"], "physical_time_ps") - _finite(start["physical_time_ps"], "physical_time_ps")
    if dt < 0.0:
        raise ValueError("selected energy window has negative physical time span")
    if dt == 0.0:
        return {
            "status": "unresolved",
            "reason": "selected energy window has zero physical time span",
            "time_span_ps": None,
            "area_m2": area * ANGSTROM2_TO_M2,
            "hot_input_eV_per_ps": None,
            "cold_extraction_eV_per_ps": None,
            "net_power_eV_per_ps": None,
            "hot_input_W": None,
            "cold_extraction_W": None,
            "net_power_W": None,
            "total_source_power_per_area_W_per_m2": None,
        }
    hot = -(
        _finite(end["hot_reservoir_eV"], "hot_reservoir_eV")
        - _finite(start["hot_reservoir_eV"], "hot_reservoir_eV")
    ) / dt
    cold = (
        _finite(end["cold_reservoir_eV"], "cold_reservoir_eV")
        - _finite(start["cold_reservoir_eV"], "cold_reservoir_eV")
    ) / dt
    net = hot - cold
    hot_w, cold_w, net_w = hot * EV_PER_PS_TO_W, cold * EV_PER_PS_TO_W, net * EV_PER_PS_TO_W
    area_m2 = area * ANGSTROM2_TO_M2
    return {
        "status": "available",
        "time_span_ps": dt,
        "area_m2": area_m2,
        "hot_input_eV_per_ps": hot,
        "cold_extraction_eV_per_ps": cold,
        "net_power_eV_per_ps": net,
        "hot_input_W": hot_w,
        "cold_extraction_W": cold_w,
        "net_power_W": net_w,
        "total_source_power_per_area_W_per_m2": hot_w / area_m2,
    }


def _temperature_pair(
    pair: Mapping[str, Any],
    frames: list[dict[str, Any]] | None,
    normal: np.ndarray,
    allocation: Mapping[str, Any] | None,
    power: dict[str, Any],
    area: float,
    profile_reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "interface_id": pair["interface_id"],
        "direction_sign": int(pair["direction_sign"]),
        "direction_vector": (int(pair["direction_sign"]) * normal).tolist(),
        "upstream_bin_ids": list(pair["upstream_bin_ids"]),
        "downstream_bin_ids": list(pair["downstream_bin_ids"]),
        "temperature_difference_kind": "slab_mean_difference_not_extrapolated_jump",
        "upstream_temperature_K": None,
        "downstream_temperature_K": None,
        "temperature_difference_K": None,
        "power_fraction": None,
        "heat_allocation_source": None,
        "heat_flux_basis": None,
        "heat_flux_J_W_per_m2": None,
        "conductance_G_W_per_m2_K": None,
        "resistance_R_m2_K_per_W": None,
    }

    if allocation is not None:
        fraction = _finite(allocation["fractions"][pair["interface_id"]], "heat allocation fraction")
        result["power_fraction"] = fraction
        result["heat_allocation_source"] = allocation["source"]
        result["heat_flux_basis"] = "declared_fraction_of_hot_input_not_independent_flux_measurement"
        if power["status"] == "available":
            result["heat_flux_J_W_per_m2"] = fraction * power["hot_input_W"] / (area * ANGSTROM2_TO_M2)

    if profile_reason is not None:
        result.update({"status": "unresolved", "reason": profile_reason})
        return result
    if frames is None or not frames:
        result.update({"status": "unresolved", "reason": "selected profile window is unresolved"})
        return result
    bin_means: dict[Any, float] = {}
    for label in ("upstream_bin_ids", "downstream_bin_ids"):
        for bin_id in pair[label]:
            samples: list[float] = []
            for frame in frames:
                frame_bin_ids = [entry["bin_id"] for entry in frame["bins"]]
                if any(type(value) is not int for value in frame_bin_ids):
                    raise ValueError("profile bin IDs must be integers")
                if len(set(frame_bin_ids)) != len(frame_bin_ids):
                    raise ValueError("profile bin IDs must be unique")
                bins = {entry["bin_id"]: entry for entry in frame["bins"]}
                if bin_id not in bins:
                    result.update({"status": "unresolved", "reason": f"selected profile frame lacks bin {bin_id}"})
                    return result
                entry = bins[bin_id]
                if int(entry["atom_count"]) <= 0:
                    result.update({"status": "unresolved", "reason": f"selected bin {bin_id} has atom_count=0"})
                    return result
                samples.append(_finite(entry["temperature_K"], "temperature_K"))
            bin_means[bin_id] = float(np.mean(samples))
    upstream = float(np.mean([bin_means[bin_id] for bin_id in pair["upstream_bin_ids"]]))
    downstream = float(np.mean([bin_means[bin_id] for bin_id in pair["downstream_bin_ids"]]))
    delta_t = upstream - downstream
    result.update(
        {
            "status": "available",
            "bin_temperature_means_K": {str(key): value for key, value in bin_means.items()},
            "upstream_temperature_K": upstream,
            "downstream_temperature_K": downstream,
            "temperature_difference_K": delta_t,
        }
    )
    if allocation is None:
        result.update({"status": "available_without_flux", "reason": "heat_allocation is unresolved"})
        return result
    if power["status"] != "available":
        result.update({"status": "unresolved", "reason": "hot input power is unresolved"})
        return result
    flux = result["heat_flux_J_W_per_m2"]
    if delta_t == 0.0:
        result["conductance_reason"] = "zero_temperature_difference"
    else:
        result["conductance_G_W_per_m2_K"] = flux / delta_t
    if flux == 0.0:
        result["resistance_reason"] = "zero_heat_flux"
    else:
        result["resistance_R_m2_K_per_W"] = delta_t / flux
    if delta_t == 0.0 or flux == 0.0:
        reasons = []
        if delta_t == 0.0:
            reasons.append("temperature difference is zero")
        if flux == 0.0:
            reasons.append("heat flux is zero")
        result.update({"status": "unresolved", "reason": " and ".join(reasons)})
    return result


def thermal_response_from_samples(
    request: Mapping[str, Any],
    energy_rows: Sequence[Mapping[str, Any]] | None,
    profile_frames: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Consume explicit LAMMPS thermal samples without selecting a steady window."""

    request, area, normal, pairs, allocation = _validate_request(request)
    raw_energy = None if energy_rows is None else [dict(row) for row in energy_rows]
    raw_frames = None if profile_frames is None else [dict(frame) for frame in profile_frames]
    window = request["observation_window"]
    if raw_energy is None:
        indices, selected_energy, selection_reason = None, None, "energy_rows is missing"
    elif not raw_energy:
        indices, selected_energy, selection_reason = None, None, "energy_rows is empty"
    else:
        indices, selected_energy, selection_reason = _select_observation_rows(raw_energy, window)
    selected_steps = None if selected_energy is None else [row["step"] for row in selected_energy]
    if raw_frames is None:
        profile_indices, selected_frames, profile_selection_reason = None, None, "profile_frames is missing"
    elif not raw_frames:
        profile_indices, selected_frames, profile_selection_reason = None, None, "profile_frames is empty"
    else:
        profile_indices, selected_frames, profile_selection_reason = _select_observation_rows(raw_frames, window)
    if selected_steps is not None and selected_frames is not None:
        selected_frame_steps = [frame["step"] for frame in selected_frames]
        if selected_frame_steps != selected_steps:
            profile_selection_reason = "selected energy and profile steps differ"
    power = _power(selected_energy, area)
    temperature_pairs = [
        _temperature_pair(pair, selected_frames, normal, allocation, power, area, profile_selection_reason)
        for pair in pairs
    ]
    pair_statuses = [pair["status"] for pair in temperature_pairs]
    if power["status"] != "available":
        response_status = "unresolved"
    elif not temperature_pairs:
        response_status = "partial"
    elif all(status == "available" for status in pair_statuses):
        response_status = "available"
    else:
        response_status = "partial"
    source_kind = request.get("source_kind")
    fixture_purpose = request.get("fixture_purpose")
    status = "mathematical_fixture" if response_status == "available" and (
        source_kind == "mathematical_fixture" or fixture_purpose == "mathematical_fixture"
    ) else response_status
    missing_evidence: list[str] = []
    if window is None:
        missing_evidence.append("observation_window")
    if raw_energy is None or not raw_energy:
        missing_evidence.append("energy_rows")
    if raw_frames is None or not raw_frames:
        missing_evidence.append("profile_frames")
    if not pairs:
        missing_evidence.append("temperature_pairs")
    if allocation is None and pairs:
        missing_evidence.append("heat_allocation")
    if profile_selection_reason == "selected energy and profile steps differ":
        missing_evidence.append("selected_profile_steps")
    for pair in temperature_pairs:
        if pair["status"] == "unresolved" and "bin" in pair.get("reason", ""):
            missing_evidence.append(f"temperature_bins_{pair['interface_id']}")
    result = {
        "schema": RESPONSE_SCHEMA,
        "status": status,
        "production_qualified": False,
        "source": {
            "kind": source_kind,
            "fixture": request.get("fixture"),
            "fixture_purpose": fixture_purpose,
        },
        "request": copy.deepcopy(dict(request)),
        "observation_window": copy.deepcopy(window),
        "heat_allocation": copy.deepcopy(allocation),
        "missing_evidence": list(dict.fromkeys(missing_evidence)),
        "energy": {
            "raw_rows": raw_energy,
            "selected_indices": indices,
            "selected_rows": selected_energy,
            "selection_status": "available" if selection_reason is None else "unresolved",
            "selection_reason": selection_reason,
            "power": power,
        },
        "temperature": {
            "raw_profile_frames": raw_frames,
            "selected_indices": profile_indices,
            "selection_status": "available" if profile_selection_reason is None else "unresolved",
            "selection_reason": profile_selection_reason,
            "selected_steps": selected_steps,
            "selected_profile_frames": selected_frames,
            "pairs": temperature_pairs,
        },
        "steady_state": {"status": "unresolved", "reason": "no automatic steady-state selection"},
        "units": {
            "energy": "eV",
            "time": "ps",
            "power_native": "eV/ps",
            "power": "W",
            "area": "angstrom^2",
            "area_SI": "m^2",
            "temperature": "K",
            "heat_flux": "W/m^2",
            "conductance": "W/(m^2 K)",
            "resistance": "m^2 K/W",
        },
    }
    return result


__all__ = ["thermal_response_from_samples"]
