"""Explicit scalar replica summaries for saved MD deliveries.

This module is deliberately a thin boundary around already saved MD products.
It reads one scalar observable from each requested delivery, binds the saved
collection through :func:`mlcc.md_sources.select_md_sources`, and applies an
explicit descriptive or Student-t summary to the values.  It never reads a
native trajectory or recomputes thermo samples.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

from .md_sources import select_md_sources


_REQUEST_SCHEMA = "mlcc.md-replica-request.v1"
_SUMMARY_SCHEMA = "mlcc.md-replica-summary.v1"
_OBSERVABLES = {
    "MD_temperature_sample_mean": {
        "unit": "K",
        "definition": "arithmetic mean of recorded whole-system temperature samples",
    },
    "MD_total_energy_final_minus_initial": {
        "unit": "eV",
        "definition": "last minus first total energy in the explicit observation window",
    },
}


def _finite_value(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"MD replica {name} must be a finite numeric value")
    return float(value)


def _sample_summary(values: list[float], *, interval: dict[str, Any]) -> dict[str, Any]:
    """Summarize explicit replica estimates for algorithm-only callers.

    The saved-source adapter below gates this helper on native replica
    identity and independence evidence.  This private function is also useful
    for mathematical tests, where the arrays are explicitly marked as
    algorithm-only and are not native MD evidence.
    """

    if not isinstance(values, list) or not values:
        raise ValueError("MD replica values must be a non-empty list")
    numeric = [_finite_value(value, "value") for value in values]
    if not isinstance(interval, dict):
        raise ValueError("MD replica interval must be an object")
    mode = interval.get("mode")
    if mode not in {"descriptive", "student_t"}:
        raise ValueError("MD replica interval.mode must be descriptive or student_t")

    mean = fmean(numeric)
    result: dict[str, Any] = {
        "mean": mean,
        "standard_deviation": None,
        "standard_error": None,
        "confidence_interval": None,
        "replica_count": len(numeric),
        "degrees_of_freedom": None,
        "t_critical": None,
        "interval_basis": (
            "descriptive replica estimates; no standard error or confidence interval"
            if mode == "descriptive"
            else "parametric Student-t interval under the declared iid replica-estimates assumption; "
            "not a normality, equilibrium, coverage, or production qualification"
        ),
    }
    if len(numeric) < 2:
        return result

    sd = stdev(numeric)
    result["standard_deviation"] = sd
    if mode == "descriptive":
        return result

    confidence = interval.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("MD replica student_t confidence must be numeric")
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("MD replica student_t confidence must satisfy 0 < confidence < 1")
    if interval.get("iid_replica_estimates") is not True:
        raise ValueError("MD replica student_t requires iid_replica_estimates=true")

    # SciPy is part of the declared transport/runtime environment.  Import it
    # only for this explicit mode so descriptive summaries have no extra
    # dependency path.
    from scipy.stats import t

    standard_error = sd / math.sqrt(len(numeric))
    degrees_of_freedom = len(numeric) - 1
    critical = float(t.isf((1.0 - confidence) / 2.0, degrees_of_freedom))
    result["standard_error"] = standard_error
    result["degrees_of_freedom"] = degrees_of_freedom
    result["t_critical"] = critical
    result["confidence_interval"] = [
        mean - critical * standard_error,
        mean + critical * standard_error,
    ]
    return result


def _read_json(path: Path, name: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"MD replica {name} must be a JSON object")
    return value


def _validate_request(request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, Any]]:
    if not isinstance(request, dict) or request.get("schema") != _REQUEST_SCHEMA:
        raise ValueError("MD replica request schema must be mlcc.md-replica-request.v1")

    source_selection = request.get("source_selection")
    if not isinstance(source_selection, dict):
        raise ValueError("MD replica request requires source_selection")
    required_source_fields = ("model_id", "model_version", "potential_id", "potential_version", "elements")
    if any(field not in source_selection for field in required_source_fields):
        raise ValueError("MD replica source_selection is incomplete")

    observable_id = request.get("observable_id")
    if observable_id not in _OBSERVABLES:
        raise ValueError("MD replica observable_id is not supported by the v001 contract")

    sources = request.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("MD replica request sources must be a non-empty list")
    checked_sources: list[dict[str, Any]] = []
    seen_delivery_paths: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or "delivery_path" not in source:
            raise ValueError("MD replica each source requires delivery_path")
        delivery_path = source["delivery_path"]
        if not isinstance(delivery_path, str) or not delivery_path:
            raise ValueError("MD replica delivery_path must be a non-empty string")
        delivery_key = str(Path(delivery_path).resolve())
        if delivery_key in seen_delivery_paths:
            raise ValueError("MD replica delivery path is repeated; the same native source cannot be counted twice")
        seen_delivery_paths.add(delivery_key)

        requested_replica_id = source.get("replica_id")
        if requested_replica_id is not None and (
            not isinstance(requested_replica_id, str) or not requested_replica_id.strip()
        ):
            raise ValueError("MD replica replica_id must be null or an existing non-empty string")
        independence = source.get("independence")
        if independence is not None:
            if not isinstance(independence, dict):
                raise ValueError("MD replica independence must be an object or null")
            if independence.get("basis") != "same_fixed_parent_distinct_velocity_seeds":
                raise ValueError("MD replica independence basis is unsupported")
            if not isinstance(independence.get("independently_executed"), bool):
                raise ValueError("MD replica independently_executed must be boolean")
        checked_sources.append(
            {
                "delivery_path": delivery_path,
                "replica_id": requested_replica_id,
                "independence": copy.deepcopy(independence),
            }
        )

    interval = request.get("interval")
    if not isinstance(interval, dict):
        raise ValueError("MD replica request requires interval")
    mode = interval.get("mode")
    if mode not in {"descriptive", "student_t"}:
        raise ValueError("MD replica interval.mode must be descriptive or student_t")
    checked_interval = copy.deepcopy(interval)
    if mode == "student_t":
        if "confidence" not in interval:
            raise ValueError("MD replica student_t confidence is required")
        confidence = interval["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("MD replica student_t confidence must be numeric")
        if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
            raise ValueError("MD replica student_t confidence must satisfy 0 < confidence < 1")
        # A missing iid declaration is an unresolved gate, not a reason to
        # invent an assumption.  _sample_summary is called only after the gate.
        if "iid_replica_estimates" in interval and not isinstance(interval["iid_replica_estimates"], bool):
            raise ValueError("MD replica iid_replica_estimates must be boolean")
    return source_selection, checked_sources, observable_id, checked_interval


def _protocol_comparison(protocol: dict[str, Any], *, ignore_velocity_seed: bool = False) -> dict[str, Any]:
    # A distinct native velocity seed is the one permitted variation across
    # replicas.  A replica_id is an identity label, not a physical protocol
    # field, so both are excluded only for the between-source comparison.
    # Within one saved delivery, the full protocol must bind exactly to the
    # collection/task/method source.
    return {
        key: copy.deepcopy(value)
        for key, value in protocol.items()
        if not (ignore_velocity_seed and key in {"seed", "replica_id"})
    }


def _geometry_signature(collection: dict[str, Any]) -> dict[str, Any]:
    frames = collection["trajectory"]["frames"]
    if not frames:
        raise ValueError("MD replica collection has no trajectory frames")
    first = frames[0]
    required = (
        "source_atom_ids",
        "lammps_atom_ids",
        "source_indices",
        "types",
        "coordinate_basis",
        "positions_angstrom",
        "box_bounds_angstrom",
        "lammps_prism_angstrom",
    )
    if any(field not in first for field in required):
        raise ValueError("MD replica collection lacks explicit atom-set or cell metadata")
    cells = []
    for frame in frames:
        if "box_bounds_angstrom" not in frame or "lammps_prism_angstrom" not in frame:
            raise ValueError("MD replica collection lacks explicit cell metadata on every frame")
        cells.append(
            {
                "box_bounds_angstrom": copy.deepcopy(frame["box_bounds_angstrom"]),
                "lammps_prism_angstrom": copy.deepcopy(frame["lammps_prism_angstrom"]),
            }
        )
    if any(cell != cells[0] for cell in cells[1:]):
        raise ValueError("MD replica collection cell differs between trajectory frames")
    return {
        "source_atom_ids": copy.deepcopy(first["source_atom_ids"]),
        "lammps_atom_ids": copy.deepcopy(first["lammps_atom_ids"]),
        "source_indices": copy.deepcopy(first["source_indices"]),
        "types": copy.deepcopy(first["types"]),
        "coordinate_basis": copy.deepcopy(first["coordinate_basis"]),
        "positions_angstrom": copy.deepcopy(first["positions_angstrom"]),
        "cells": cells,
    }


def _condition_signature(conditions: dict[str, Any], time: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = (
        "engine",
        "units",
        "atom_style",
        "ensemble",
        "timestep_ps",
        "timestep_fs",
        "steps",
        "thermo_every_steps",
        "dump_every_steps",
        "initial_velocity_temperature_K",
        "target_temperature_K",
        "pressure_bar",
        "initial_step",
        "time_origin",
    )
    if "temperature" in conditions:
        # md_conditions returns nested temperature/pressure fields while
        # md_sources returns the flattened source-selection signature.
        normalized = {
            "engine": conditions.get("engine"),
            "units": conditions.get("units"),
            "atom_style": conditions.get("atom_style"),
            "ensemble": conditions.get("ensemble"),
            "timestep_ps": conditions.get("timestep_ps"),
            "timestep_fs": conditions.get("timestep_fs"),
            "steps": conditions.get("steps"),
            "thermo_every_steps": conditions.get("thermo_every_steps"),
            "dump_every_steps": conditions.get("dump_every_steps"),
            "initial_velocity_temperature_K": conditions["temperature"].get("initial_velocity_temperature_K"),
            "target_temperature_K": conditions["temperature"].get("target_temperature_K"),
            "pressure_bar": conditions.get("pressure", {}).get("pressure_bar"),
            "initial_step": None if time is None else time.get("initial_step"),
            "time_origin": None if time is None else time.get("origin"),
        }
        optional = {"target_temperature_K", "pressure_bar"}
        if any(normalized[field] is None and field not in optional for field in fields):
            raise ValueError("MD replica saved conditions are incomplete")
        return normalized
    if any(field not in conditions for field in fields):
        raise ValueError("MD replica saved conditions are incomplete")
    return {field: copy.deepcopy(conditions[field]) for field in fields}


def _bind_native_metadata(collection: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind collection metadata to the original task and method JSON files."""

    source_files = collection.get("source_files")
    if not isinstance(source_files, dict):
        raise ValueError("MD replica collection source_files are required")
    task_path = Path(source_files["task.json"])
    method_path = Path(source_files["method.json"])
    task = _read_json(task_path, "native task")
    method = _read_json(method_path, "native method")

    if task["task_id"] != collection["task_id"]:
        raise ValueError("MD replica native task identity differs from collection")
    if task["scheduler_job_id"] != collection["native_job"]["scheduler_job_id"]:
        raise ValueError("MD replica native task job identity differs from collection")
    for field in ("scheduler_state", "exit_code", "runner"):
        if field in task and task[field] != collection["native_job"].get(field):
            raise ValueError(f"MD replica native task {field} differs from collection")
    if task["model"]["model_id"] != collection["model"]["model_id"] or task["model"]["version"] != collection["model"]["version"]:
        raise ValueError("MD replica native task model identity differs from collection")
    if task["method_set"] != collection["lineage"]["method_set"]:
        raise ValueError("MD replica native task method_set differs from collection")
    if task["protocol"] != collection["protocol"]:
        raise ValueError("MD replica native task protocol differs from collection")

    if method["model_id"] != collection["model"]["model_id"] or method["version"] != collection["model"]["version"]:
        raise ValueError("MD replica native method model identity differs from collection")
    if method["engine"] != collection["engine"]:
        raise ValueError("MD replica native method engine differs from collection")
    if method["units"] != collection["units"]:
        raise ValueError("MD replica native method units differ from collection")
    if method["atom_style"] != collection["atom_style"]:
        raise ValueError("MD replica native method atom_style differs from collection")
    if method["protocol"] != collection["protocol"]:
        raise ValueError("MD replica native method protocol differs from collection")
    for field in ("replica_id", "packing_seed"):
        if collection["sampling_metadata"].get(field) != method["protocol"].get(field):
            raise ValueError(f"MD replica native method {field} differs from collection")
    if collection["initialization"]["velocity_seed"] != method["protocol"]["seed"]:
        raise ValueError("MD replica native method velocity_seed differs from collection")
    for source_name, source_record in (("task", task), ("method", method)):
        source_potential = source_record["potential"]
        if source_potential["potential_id"] != collection["potential"]["potential_id"] or source_potential["version"] != collection["potential"]["version"]:
            raise ValueError(f"MD replica native {source_name} potential identity differs from collection")
    return task, method


def _observable_from_delivery(delivery: dict[str, Any], observable_id: str) -> dict[str, Any]:
    observables = delivery.get("observables")
    if not isinstance(observables, list):
        raise ValueError("MD replica delivery has no saved observables")
    matches = [row for row in observables if isinstance(row, dict) and row.get("observable_id") == observable_id]
    if len(matches) != 1:
        raise ValueError(f"MD replica delivery does not contain exactly one {observable_id} observable")
    observable = copy.deepcopy(matches[0])
    expected = _OBSERVABLES[observable_id]
    if observable.get("definition") != expected["definition"] or observable.get("unit") != expected["unit"]:
        raise ValueError(f"MD replica {observable_id} definition or unit differs from the contract")
    if observable.get("object_level") != "whole_simulation_cell":
        raise ValueError(f"MD replica {observable_id} object level differs from whole_simulation_cell")
    observable["value"] = _finite_value(observable.get("value"), f"{observable_id}.value")
    conditions = observable.get("conditions")
    if not isinstance(conditions, dict) or not isinstance(conditions.get("observation_window"), dict):
        raise ValueError(f"MD replica {observable_id} lacks an explicit observation window")
    return observable


def _bind_saved_thermo_artifact(
    delivery: dict[str, Any],
    collection: dict[str, Any],
    selected: dict[str, Any],
    observable: dict[str, Any],
    observable_id: str,
) -> dict[str, Any]:
    artifacts = delivery.get("artifacts")
    artifact_path = artifacts.get("thermo") if isinstance(artifacts, dict) else None
    if not isinstance(artifact_path, str) or not artifact_path:
        raise ValueError("MD replica delivery.artifacts.thermo is required")
    thermo = _read_json(Path(artifact_path), "thermo artifact")
    if thermo.get("schema") != "mlcc.md-thermo-summary.v1":
        raise ValueError("MD replica thermo artifact schema is not mlcc.md-thermo-summary.v1")
    if thermo.get("task_id") != selected["task_id"] or thermo.get("native_job") != selected["native_job"]:
        raise ValueError("MD replica thermo artifact task/job differs from selected collection")
    for name, expected in (("model", selected["model"]), ("potential", selected["potential"])):
        actual = thermo.get(name)
        identifier = "model_id" if name == "model" else "potential_id"
        if not isinstance(actual, dict) or actual.get(identifier) != expected.get(identifier) or actual.get("version") != expected.get("version"):
            raise ValueError(f"MD replica thermo artifact {name} identity differs from selected collection")
    lineage = thermo.get("lineage")
    if not isinstance(lineage, dict) or lineage.get("method_set") != collection["lineage"]["method_set"]:
        raise ValueError("MD replica thermo artifact method_set differs from selected collection")
    if thermo.get("source_files") != collection.get("source_files"):
        raise ValueError("MD replica thermo artifact source files differ from selected collection")
    if thermo.get("observation") != observable["conditions"]["observation_window"]:
        raise ValueError("MD replica thermo artifact observation window differs from selected observable")
    quantities = thermo.get("quantities")
    if not isinstance(quantities, dict):
        raise ValueError("MD replica thermo artifact quantities are missing")
    if observable_id == "MD_temperature_sample_mean":
        saved_value = quantities.get("temperature", {}).get("sample_mean") if isinstance(quantities.get("temperature"), dict) else None
    else:
        saved_value = quantities.get("total_energy", {}).get("final_minus_initial") if isinstance(quantities.get("total_energy"), dict) else None
    if _finite_value(saved_value, f"{observable_id} saved thermo value") != observable["value"]:
        raise ValueError("MD replica thermo artifact value differs from selected observable")
    return thermo


def _bind_delivery(
    delivery: dict[str, Any],
    delivery_path: Path,
    collection: dict[str, Any],
    selected: dict[str, Any],
    observable: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    """Check saved delivery metadata against the freshly selected collection."""

    _bind_native_metadata(collection)
    _bind_saved_thermo_artifact(delivery, collection, selected, observable, observable["observable_id"])
    if delivery.get("schema") != "mlcc.md-property-delivery.v1":
        raise ValueError("MD replica delivery schema must be mlcc.md-property-delivery.v1")
    if delivery.get("task_id") != selected["task_id"]:
        raise ValueError("MD replica delivery task identity differs from selected collection")
    if delivery.get("native_job") != selected["native_job"]:
        raise ValueError("MD replica delivery native job identity differs from selected collection")
    lineage = delivery.get("lineage")
    if not isinstance(lineage, dict) or lineage.get("method_set") != collection["lineage"]["method_set"]:
        raise ValueError("MD replica delivery method_set differs from selected collection")
    for name, requested, identity_fields in (
        ("model", selected["model"], ("model_id", "version")),
        ("potential", selected["potential"], ("potential_id", "version")),
    ):
        actual = delivery.get(name)
        if not isinstance(actual, dict) or any(actual.get(key) != requested.get(key) for key in identity_fields):
            raise ValueError(f"MD replica delivery {name} identity differs from selected collection")

    protocol = delivery.get("protocol")
    if not isinstance(protocol, dict) or _protocol_comparison(protocol) != _protocol_comparison(collection["protocol"]):
        raise ValueError("MD replica delivery protocol or boundary differs from selected collection")
    selected_conditions = _condition_signature(selected["conditions"])
    delivery_conditions = delivery.get("conditions")
    if not isinstance(delivery_conditions, dict) or not isinstance(delivery_conditions.get("conditions"), dict):
        raise ValueError("MD replica delivery lacks saved conditions")
    if _condition_signature(delivery_conditions["conditions"], delivery_conditions.get("time")) != selected_conditions:
        raise ValueError("MD replica delivery engine, units, atom_style, or protocol conditions differ")

    selected_source = delivery.get("source_selection")
    if not isinstance(selected_source, dict):
        raise ValueError("MD replica delivery lacks source_selection")
    embedded_request = selected_source.get("request")
    if isinstance(embedded_request, dict):
        expected_request = {
            "model_id": selected["model"]["model_id"],
            "model_version": selected["model"]["version"],
            "potential_id": selected["potential"]["potential_id"],
            "potential_version": selected["potential"]["version"],
            "elements": list(selected["mapping"]["elements"]),
        }
        if embedded_request != expected_request:
            raise ValueError("MD replica delivery source-selection request differs from selected collection")
    embedded_sources = selected_source.get("sources")
    if not isinstance(embedded_sources, list) or len(embedded_sources) != 1:
        raise ValueError("MD replica delivery source_selection must bind one native source")
    embedded = embedded_sources[0]
    if embedded.get("task_id") != selected["task_id"] or embedded.get("native_job") != selected["native_job"]:
        raise ValueError("MD replica delivery source selection task/job differs from collection")
    if embedded.get("source_files") is not None and embedded.get("source_files") != selected["source_files"]:
        raise ValueError("MD replica delivery source selection files differ from collection")
    if embedded.get("collection_path") is not None:
        if str(Path(embedded["collection_path"]).resolve()) != str(Path(selected["collection_path"]).resolve()):
            raise ValueError("MD replica delivery source selection collection differs from artifacts.collection")
    if embedded.get("protocol") is not None and _protocol_comparison(embedded["protocol"]) != _protocol_comparison(collection["protocol"]):
        raise ValueError("MD replica delivery source selection protocol differs from collection")
    saved_replica = embedded.get("replica")
    actual_replica = selected["replica"]
    replica_id = actual_replica["replica_id"]
    if replica_id is not None and (not isinstance(replica_id, str) or not replica_id.strip()):
        raise ValueError("MD replica saved replica_id must be null or a non-empty string")
    if isinstance(saved_replica, dict):
        for field in ("replica_id", "packing_seed", "velocity_seed"):
            if field in saved_replica and saved_replica.get(field) != actual_replica.get(field):
                raise ValueError(f"MD replica saved {field} differs from selected collection")

    source_task = observable.get("source_task")
    source_job = observable.get("scheduler_job_id")
    source_method_set = observable.get("method_set")
    if source_task != selected["task_id"] or source_job != selected["native_job"]["scheduler_job_id"]:
        raise ValueError("MD replica observable source task/job differs from selected collection")
    if source_method_set != collection["lineage"]["method_set"]:
        raise ValueError("MD replica observable method_set differs from selected collection")
    if observable["conditions"].get("ensemble") != selected["conditions"]["ensemble"]:
        raise ValueError("MD replica observable ensemble differs from selected collection")

    # The delivery includes the saved MD-06 observation.  Compare the explicit
    # window when available, without opening thermo or trajectory files.
    saved_observations: list[dict[str, Any]] = []
    saved_thermo = delivery.get("md_thermo")
    if isinstance(saved_thermo, dict) and isinstance(saved_thermo.get("observation"), dict):
        saved_observations.append(saved_thermo["observation"])
    for saved_observation in saved_observations:
        if saved_observation != observable["conditions"]["observation_window"]:
            raise ValueError("MD replica observable observation window differs from saved source observation")

    requested_replica_id = source.get("replica_id")
    if requested_replica_id is not None and requested_replica_id != actual_replica.get("replica_id"):
        raise ValueError("MD replica request cannot replace the saved replica_id")

    return {
        "delivery_path": str(delivery_path),
        "collection_path": selected["collection_path"],
        "value": observable["value"],
        "observable": observable,
        "replica": {
            "requested_id": requested_replica_id,
            "replica_id": actual_replica.get("replica_id"),
            "packing_seed": actual_replica.get("packing_seed"),
            "velocity_seed": actual_replica.get("velocity_seed"),
            "independence": copy.deepcopy(source.get("independence")),
        },
        "task_id": selected["task_id"],
        "native_job": copy.deepcopy(selected["native_job"]),
        "analysis_scheduler_job_id": delivery.get("analysis_scheduler_job_id"),
        "model": copy.deepcopy(selected["model"]),
        "potential": copy.deepcopy(selected["potential"]),
        "method_set": collection["lineage"]["method_set"],
        "source_files": copy.deepcopy(collection["source_files"]),
        "protocol": copy.deepcopy(collection["protocol"]),
        "conditions": copy.deepcopy(selected["conditions"]),
        "observation_window": copy.deepcopy(observable["conditions"]["observation_window"]),
        "scientific_status": delivery.get("scientific_status"),
        "missing_evidence": copy.deepcopy(delivery.get("missing_evidence", [])),
        "unresolved_qualification": copy.deepcopy(delivery.get("unresolved_qualification", {})),
        "collection_missing_evidence": copy.deepcopy(collection.get("missing_evidence", [])),
        "collection_unresolved": copy.deepcopy(collection.get("unresolved", {})),
        "production_qualification": delivery.get("production_qualification"),
        "sampling_equilibrium_qualified": delivery.get("sampling_equilibrium_qualified"),
    }


def _gate_reasons(records: list[dict[str, Any]], interval: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if len(records) < 2:
        reasons.append("fewer than two observed sources are available")
    replica_ids = [record["replica"]["replica_id"] for record in records]
    if any(replica_id is None for replica_id in replica_ids):
        reasons.append("one or more native sources lacks a saved replica_id")
    elif len(set(replica_ids)) != len(replica_ids):
        reasons.append("replica_id values are repeated")
    independence = [record["replica"]["independence"] for record in records]
    if any(value is None for value in independence):
        reasons.append("independence basis is not declared for every source")
    if any(value is not None and value.get("independently_executed") is not True for value in independence):
        reasons.append("independent native execution is not declared for every source")
    velocity_seeds = [record["replica"]["velocity_seed"] for record in records]
    if len(set(velocity_seeds)) != len(velocity_seeds):
        reasons.append("velocity_seed values are repeated")
    packing_seeds = [record["replica"]["packing_seed"] for record in records]
    if len(set(map(repr, packing_seeds))) > 1:
        reasons.append("packing_seed metadata differs; packing variation is outside this contract")
    if interval.get("mode") == "student_t" and interval.get("iid_replica_estimates") is not True:
        reasons.append("student_t requires an explicit iid_replica_estimates=true declaration")
    return reasons


def summarize_md_replicas(request: dict[str, Any]) -> dict[str, Any]:
    """Summarize one explicitly selected scalar across saved MD deliveries."""

    source_selection, sources, observable_id, interval = _validate_request(request)
    loaded: list[tuple[dict[str, Any], Path, Path, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for source in sources:
        delivery_path = Path(source["delivery_path"])
        delivery = _read_json(delivery_path, "delivery")
        artifacts = delivery.get("artifacts")
        if not isinstance(artifacts, dict) or not isinstance(artifacts.get("collection"), str) or not artifacts["collection"]:
            raise ValueError("MD replica delivery.artifacts.collection is required")
        collection_path = Path(artifacts["collection"])
        collection = _read_json(collection_path, "collection")
        observable = _observable_from_delivery(delivery, observable_id)
        loaded.append((delivery, delivery_path, collection_path, collection, observable, source))

    # Bind every native collection in one call.  This preserves md_sources'
    # duplicate task/job/source-path rejection across the complete request;
    # calling it once per source would let copies of one native run pass.
    selected_result = select_md_sources(
        [entry[2] for entry in loaded],
        model_id=source_selection["model_id"],
        model_version=source_selection["model_version"],
        potential_id=source_selection["potential_id"],
        potential_version=source_selection["potential_version"],
        elements=source_selection["elements"],
    )
    selected_sources = selected_result["sources"]
    if len(selected_sources) != len(loaded):
        raise ValueError("MD replica source binding count differs from request")
    bound_records: list[tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any]]] = []
    for (delivery, delivery_path, _, collection, observable, source), selected in zip(loaded, selected_sources):
        bound_records.append(
            (
                delivery,
                delivery_path,
                collection,
                _bind_delivery(delivery, delivery_path, collection, selected, observable, source),
            )
        )

    # The fixed-parent and physical-condition comparisons apply across every
    # selected source.  A metadata mismatch is a hard boundary error, rather
    # than a silently withheld statistical result.
    first = bound_records[0][3]
    first_collection = bound_records[0][2]
    first_geometry = _geometry_signature(first_collection)
    first_protocol = _protocol_comparison(first_collection["protocol"], ignore_velocity_seed=True)
    first_conditions = _condition_signature(first["conditions"])
    first_window = first["observation_window"]
    first_identity = (
        first["model"]["model_id"],
        first["model"]["version"],
        first["potential"]["potential_id"],
        first["potential"]["version"],
        first["method_set"],
    )
    for _, _, collection, record in bound_records[1:]:
        identity = (
            record["model"]["model_id"],
            record["model"]["version"],
            record["potential"]["potential_id"],
            record["potential"]["version"],
            record["method_set"],
        )
        if identity != first_identity:
            raise ValueError("MD replica model, potential, or method_set differs between sources")
        if _protocol_comparison(collection["protocol"], ignore_velocity_seed=True) != first_protocol:
            raise ValueError("MD replica physical protocol or boundary differs between sources")
        if _condition_signature(record["conditions"]) != first_conditions:
            raise ValueError("MD replica engine, units, atom_style, or condition protocol differs between sources")
        if _geometry_signature(collection) != first_geometry:
            raise ValueError("MD replica atom set or cell differs between sources")
        if record["observation_window"] != first_window:
            raise ValueError("MD replica explicit observation window differs between sources")

    records = [entry[3] for entry in bound_records]
    values = [record["value"] for record in records]
    reasons = _gate_reasons(records, interval)
    eligible = not reasons
    if eligible:
        statistics = _sample_summary(values, interval=interval)
    else:
        statistics = {
            "mean": fmean(values),
            "standard_deviation": None,
            "standard_error": None,
            "confidence_interval": None,
            "replica_count": len({record["replica"]["replica_id"] for record in records if record["replica"]["replica_id"] is not None}),
            "degrees_of_freedom": None,
            "t_critical": None,
            "interval_basis": (
                "descriptive replica estimates; no standard error or confidence interval"
                if interval["mode"] == "descriptive"
                else "parametric Student-t interval withheld until iid replica-estimates evidence is declared"
            ),
        }

    return {
        "schema": _SUMMARY_SCHEMA,
        "status": "summarized_engineering_observation",
        "request": copy.deepcopy(request),
        "observable_id": observable_id,
        "observable": {
            "definition": records[0]["observable"]["definition"],
            "object_level": records[0]["observable"]["object_level"],
            "unit": records[0]["observable"]["unit"],
        },
        "observed_source_count": len(records),
        "replica_count": statistics["replica_count"],
        "values": values,
        "statistics": statistics,
        "interval": copy.deepcopy(interval),
        "statistics_status": "available" if eligible else "unresolved",
        "statistics_unresolved_reasons": reasons,
        "sources": records,
        "production_qualification": False,
        "sampling_equilibrium_qualified": False,
        "scientific_status": [record["scientific_status"] for record in records],
    }


__all__ = ["summarize_md_replicas"]
