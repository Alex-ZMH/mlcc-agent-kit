"""Minimal descriptive thermo observations for accepted MLCC MD collections.

The function consumes one accepted collection and returns observations from
its native thermo rows, with optional explicit block/drift/anomaly diagnostics.
It does not select windows, infer equilibrium, estimate sampling uncertainty,
or submit numerical work. Source lineage follows the MD-01/MD-02 contracts.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from .md_conditions import read_md_conditions
from .md_sources import select_md_sources
from .md_thermo_diagnostics import analyze_thermo_diagnostics


_COLLECTION_SCHEMA = "mlcc.md-collection.v1"
_SUMMARY_SCHEMA = "mlcc.md-thermo-summary.v1"


def _read_collection(path: Path) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["schema"] != _COLLECTION_SCHEMA:
        raise ValueError("MD thermo collection schema must be mlcc.md-collection.v1")
    return record


def _observation_rows(
    rows: list[dict[str, Any]], observation_window: dict[str, Any],
) -> tuple[list[int], list[dict[str, Any]]]:
    if not isinstance(observation_window, dict):
        raise ValueError("MD thermo observation_window must be an object")
    if "kind" not in observation_window:
        raise ValueError("MD thermo observation_window requires kind")

    kind = observation_window["kind"]
    steps = [row["step"] for row in rows]
    if kind == "whole_record":
        if set(observation_window) != {"kind"}:
            raise ValueError("MD thermo whole_record must not contain step bounds or other selectors")
        indices = list(range(len(rows)))
    elif kind == "step_range":
        if "start_step" not in observation_window or "end_step" not in observation_window:
            raise ValueError("MD thermo step_range requires start_step and end_step")
        start_step = observation_window["start_step"]
        end_step = observation_window["end_step"]
        if type(start_step) is not int or type(end_step) is not int:
            raise ValueError("MD thermo step_range endpoints must be integers")
        if end_step <= start_step:
            raise ValueError("MD thermo step_range end_step must be greater than start_step")
        if start_step not in steps or end_step not in steps:
            raise ValueError("MD thermo step_range endpoints must be recorded thermo steps")
        indices = [index for index, step in enumerate(steps) if start_step <= step <= end_step]
    else:
        raise ValueError(f"MD thermo observation_window kind is unsupported: {kind}")

    return indices, [rows[index] for index in indices]


def _finite_thermo_value(row: dict[str, Any], field: str) -> float:
    # Keep the direct field lookup so a missing native field remains the
    # original KeyError rather than being converted into synthetic data.
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"MD thermo {field} must be a finite numeric value")
    return float(value)


def _range(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [float(rows[0][field]), float(rows[-1][field])]


def analyze_md_thermo(
    collection_path: str | Path, *, observation_window: dict[str, Any],
    thermo_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe selected native thermo samples for one accepted MD collection.

    ``observation_window`` must be explicit.  ``whole_record`` reports all
    observed thermo rows; ``step_range`` reports an inclusive range whose two
    endpoints must be present in the native thermo record.  Both scopes remain
    engineering observations and never establish production or equilibrium
    qualification.
    """

    path = Path(collection_path)
    record = _read_collection(path)
    conditions = read_md_conditions(path)
    legacy = record["legacy_final_result"]
    elements = list(dict.fromkeys(legacy["elements"]))
    source_selection = select_md_sources(
        [path],
        model_id=record["model"]["model_id"],
        model_version=record["model"]["version"],
        potential_id=record["potential"]["potential_id"],
        potential_version=record["potential"]["version"],
        elements=elements,
    )

    thermo = record["thermo"]
    native_rows = thermo["rows"]
    indices, rows = _observation_rows(native_rows, observation_window)
    temperatures = [_finite_thermo_value(row, "temp") for row in rows]
    total_energies = [_finite_thermo_value(row, "etotal") for row in rows]
    selected_rows = [dict(row) for row in rows]
    first_row = rows[0]
    last_row = rows[-1]

    result = {
        "schema": _SUMMARY_SCHEMA,
        "status": "described_engineering_observation",
        "task_id": record["task_id"],
        "native_job": dict(record["native_job"]),
        "model": dict(record["model"]),
        "potential": dict(record["potential"]),
        "lineage": dict(record["lineage"]),
        "source_files": dict(record["source_files"]),
        "source_selection": source_selection,
        "conditions": conditions,
        "observation": {
            "request": dict(observation_window),
            "indices": indices,
            "sample_count": len(rows),
            "step_range": [first_row["step"], last_row["step"]],
            "physical_time_ps_range": _range(rows, "physical_time_ps"),
            "physical_time_fs_range": _range(rows, "physical_time_fs"),
            "scope": "engineering_observation_not_production",
        },
        "thermo": {
            "units": dict(thermo["units"]),
            "rows": selected_rows,
        },
        "quantities": {
            "temperature": {
                "source_field": "temp",
                "unit": "K",
                "normalization": "whole_simulation_cell",
                "sample_mean": math.fsum(temperatures) / len(temperatures),
                "minimum": min(temperatures),
                "maximum": max(temperatures),
            },
            "total_energy": {
                "source_field": "etotal",
                "unit": "eV",
                "initial": total_energies[0],
                "final": total_energies[-1],
                "final_minus_initial": total_energies[-1] - total_energies[0],
                "normalization": "whole_simulation_cell",
            },
        },
        "diagnostics": {
            "stationarity": {
                "status": "unresolved",
                "reason": "not_evaluated_by_descriptive_summary",
            },
            "uncertainty": {
                "status": "unresolved",
                "reason": "not_evaluated_by_descriptive_summary",
            },
            "time_step_convergence": {
                "status": "unresolved",
                "reason": "not_evaluated_by_descriptive_summary",
            },
        },
        "production_qualification": False,
        "sampling_equilibrium_qualified": False,
    }
    if thermo_diagnostics is not None:
        result["thermo_diagnostics"] = analyze_thermo_diagnostics(
            selected_rows, row_indices=indices, units=thermo["units"],
            request=thermo_diagnostics,
        )
        result["thermo_diagnostics"].update({
            **{key: result[key] for key in (
                "task_id", "native_job", "model", "potential", "lineage", "source_files", "observation",
            )},
            "collection_path": str(path.resolve()),
            "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        })
        result["diagnostics"]["stationarity"]["reason"] = "not_inferred_from_drift_and_anomaly_diagnostics"
        result["diagnostics"]["uncertainty"]["reason"] = "sampling_uncertainty_not_estimated_from_descriptive_blocks"
    return result


__all__ = ["analyze_md_thermo"]
