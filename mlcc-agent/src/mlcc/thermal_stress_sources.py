"""Bind saved thermal-stress source products.

This is a saved-product adapter.  The native LAMMPS sampling envelope and
collection are saved inputs; the MD path reuses the established local-stress
conversion for its declared virial frames and preserves the native provenance.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from typing import Any

from .local_stress import local_stress_from_frames
from .thermal_stress import thermal_stress_change


REQUEST_SCHEMA = "mlcc.thermal-stress-request.v1"
PRODUCT_SCHEMA = "mlcc.thermal-stress-product.v1"
LOCAL_SCHEMA = "mlcc.local-stress-product.v1"
THERMAL_SCHEMA = "mlcc.interface-thermal-product.v1"
TEMPERATURE_SCHEMA = "mlcc.region-temperature-history.v1"
MECHANICAL_SCHEMA = "mlcc.mechanical-history.v1"
ATOM_MAP_SCHEMA = "mlcc.lammps-atom-map.v1"
MD_THERMAL_REQUEST_SCHEMA = "mlcc.md-thermal-sources-request.v1"
MD_THERMAL_MANIFEST_SCHEMA = "mlcc.md-thermal-sources.v1"
MD_NATIVE_STRESS_SCHEMA = "mlcc.md-native-stress-source.v1"
MD_COLLECTION_SCHEMA = "mlcc.md-collection.v1"
MD_COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz", "yx", "zx", "zy"]


def _json(path: str | Path) -> tuple[dict[str, Any], Path]:
    file = Path(path).expanduser().resolve()
    value = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {file}")
    return value, file


def _existing(value: str | Path, label: str, base: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _check(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} differs: {actual!r} != {expected!r}")


def _write_json(path: str | Path, value: dict[str, Any]) -> Path:
    file = Path(path).expanduser().resolve()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return file


def _study_identity(study: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any]:
    model = study["model"]
    return (study["study_id"], study["case_id"], study["case_role"],
            model["model_id"], model["version"])


def _check_study(value: dict[str, Any], study: dict[str, Any], label: str) -> None:
    sid, cid, role, model_id, version = _study_identity(study)
    _check(value["study_id"], sid, f"{label}.study_id")
    _check(value["case_id"], cid, f"{label}.case_id")
    _check(value["case_role"], role, f"{label}.case_role")
    _check(value["model_id"], model_id, f"{label}.model_id")
    _check(value["model_version"], version, f"{label}.model_version")


def _atom_map(task_file: Path, model_id: str, version: str) -> tuple[dict[str, Any], Path]:
    file = _existing(task_file.parent / "atom-map.json", "atom-map")
    mapping, _ = _json(file)
    _check(mapping["schema"], ATOM_MAP_SCHEMA, "atom-map.schema")
    _check(mapping["model_id"], model_id, "atom-map.model_id")
    _check(mapping["version"], version, "atom-map.version")
    mapping["source_atom_ids"]
    mapping["source_cell_angstrom"]
    return mapping, file


def _source_files(
    product: dict[str, Any], product_file: Path, task: dict[str, Any], task_file: Path,
    atom_map_file: Path,
) -> dict[str, str]:
    files = {"product": str(product_file), "task": str(task_file), "atom-map": str(atom_map_file)}
    for owner, values in (("task", task), ("product", product)):
        for field in ("model_path", "method_path", "potential_file", "protocol_file",
                      "study_file", "site_file", "environment_script", "request_path"):
            value = values.get(field)
            if value is not None:
                base = task_file.parent if owner == "task" else product_file.parent
                files[f"{owner}:{field}"] = str(_existing(value, f"{owner}.{field}", base))
    for owner in ("native_result", "native_local_stress", "native_thermal"):
        value = product.get(owner)
        if value is None:
            continue
        for name, source in value["source_files"].items():
            files[f"{owner}:{name}"] = str(_existing(source, f"{owner}.source_files.{name}", task_file.parent))
    potential = task.get("potential")
    if potential is not None:
        for index, item in enumerate(potential.get("files", [])):
            files[f"potential:{index}"] = str(_existing(item["local_path"], f"potential.files[{index}]", task_file.parent))
    for owner in (product.get("interface_sources"), task.get("interface_sources")):
        if owner is None:
            continue
        for name, source in owner.get("original_sources", {}).items():
            if source is not None:
                files[f"interface:original:{name}"] = str(_existing(source, f"interface.original_sources.{name}", task_file.parent))
    return files


def _identity(
    product: dict[str, Any], task: dict[str, Any], mapping: dict[str, Any],
    local: dict[str, Any] | None, native: dict[str, Any] | None,
) -> dict[str, Any]:
    potential = task["potential"]
    potential_id, potential_version = potential["potential_id"], potential["version"]
    if native is not None and native.get("potential") is not None:
        _check(native["potential"]["potential_id"], potential_id, "native potential_id")
        _check(native["potential"]["version"], potential_version, "native potential.version")
    method_set = task["method_set"]
    if product.get("method_set") is not None:
        _check(product["method_set"], method_set, "product.method_set")
    if native is not None and native.get("method_set") is not None:
        _check(native["method_set"], method_set, "native method_set")
    atom_ids, cell = mapping["source_atom_ids"], mapping["source_cell_angstrom"]
    if native is not None:
        if native.get("atom_ids") is not None:
            _check(native["atom_ids"], atom_ids, "native atom_ids")
        if native.get("cell_angstrom") is not None:
            _check(native["cell_angstrom"], cell, "native cell_angstrom")
    if local is not None and local.get("source_cell_angstrom") is not None:
        _check(local["source_cell_angstrom"], cell, "local source_cell_angstrom")
    if local is not None:
        contribution = local["contribution"]
        kinetic = local["kinetic_included"]
        components = local["stress_volume_component_order"]
    else:
        contribution, kinetic, components = None, None, None
    return {
        "study_id": product["study_id"], "case_id": product["case_id"],
        "case_role": product["case_role"], "model_id": product["model_id"],
        "model_version": product["model_version"], "potential_id": potential_id,
        "potential_version": potential_version, "method_set": method_set,
        "source_atom_ids": copy.deepcopy(atom_ids), "source_cell_angstrom": copy.deepcopy(cell),
        "contribution": contribution, "kinetic_included": kinetic,
        "native_component_order": copy.deepcopy(components),
    }


def _native_job(task: dict[str, Any]) -> dict[str, Any]:
    return {key: task.get(key) for key in (
        "scheduler_job_id", "scheduler_state", "exit_code", "native_exit_code",
        "status", "scientific_status", "runner",
    )}


def _check_saved_job(product: dict[str, Any], task: dict[str, Any], label: str) -> None:
    saved = product["source_task"]
    for field in ("scheduler_job_id", "scheduler_state", "exit_code"):
        _check(saved[field], task[field], f"{label}.source_task.{field}")
    for field in ("native_exit_code", "status", "scientific_status"):
        if field in saved:
            _check(saved[field], task.get(field), f"{label}.source_task.{field}")


def _check_native_job(native: dict[str, Any], task: dict[str, Any], label: str) -> None:
    for field in ("task_id", "scheduler_job_id", "scheduler_state", "exit_code"):
        _check(native[field], task[field], f"{label}.{field}")


def _source_record(
    kind: str, product: dict[str, Any], product_file: Path, task: dict[str, Any], task_file: Path,
    files: dict[str, str], identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_kind": kind, "product_path": str(product_file), "task_path": str(task_file),
        "request_path": product.get("request_path"), "task_id": task["task_id"],
        "native_job": _native_job(task),
        "model": {"model_id": product["model_id"], "version": product["model_version"],
                  "path": product.get("model_path")},
        "potential": copy.deepcopy(task["potential"]), "method": copy.deepcopy(task["method"]),
        "method_set": task["method_set"], "protocol": copy.deepcopy(product["protocol"]),
        "identity": identity, "source_files": files, "source_refs": list(files.values()),
        "status": product["status"],
        "missing_evidence": copy.deepcopy(product.get("missing_evidence", [])),
    }


def _bind_local(path: str | Path, study: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    product, product_file = _json(path)
    _check(product["schema"], LOCAL_SCHEMA, "local stress schema")
    _check_study(product, study, "local stress product")
    task_file = _existing(product["task_path"], "local stress task_path", product_file.parent)
    task, _ = _json(task_file)
    _check_study(task, study, "local stress task")
    _check(product["task_id"], task["task_id"], "local stress task_id")
    _check(product["protocol"], task["protocol"], "local stress protocol")
    _check(task["runner"], "slurm", "local stress task.runner")
    _check_saved_job(product, task, "local stress")
    mapping, mapping_file = _atom_map(task_file, product["model_id"], product["model_version"])
    local = product["local_stress"]
    _check(local["schema"], "mlcc.local-stress-response.v1", "local stress response schema")
    _check(local["units"]["stress"], "GPa", "local stress units.stress")
    _check(local["units"]["time"], "ps", "local stress units.time")
    _check(local["units"]["volume"], "angstrom^3", "local stress units.volume")
    _check(local["stress_volume_basis"], "lammps_prism", "local stress basis")
    native = product.get("native_result")
    if native is not None and not isinstance(native, dict):
        raise ValueError("local stress native_result must be an object or null")
    if native is not None:
        _check_native_job(native, task, "local stress native_result")
    native_local = product.get("native_local_stress")
    if native_local is not None and not isinstance(native_local, dict):
        raise ValueError("local stress native_local_stress must be an object or null")
    identity = _identity(product, task, mapping, local, native)
    if native_local is not None:
        _check(native_local["source_cell_angstrom"], mapping["source_cell_angstrom"], "native local source cell")
        _check(native_local["component_order"], local["stress_volume_component_order"],
               "native local component_order")
        for frame in native_local["frames"]:
            _check(frame["atom_ids"], mapping["source_atom_ids"], "native local frame atom_ids")
    files = _source_files(product, product_file, task, task_file, mapping_file)
    return (_source_record("local_stress_product", product, product_file, task, task_file, files, identity),
            product, task, mapping)


def _bind_interface(path: str | Path, study: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    product, product_file = _json(path)
    _check(product["schema"], THERMAL_SCHEMA, "interface thermal schema")
    _check_study(product, study, "interface thermal product")
    task_file = _existing(product["task_path"], "interface thermal task_path", product_file.parent)
    task, _ = _json(task_file)
    _check_study(task, study, "interface thermal task")
    _check(product["task_id"], task["task_id"], "interface thermal task_id")
    _check(product["protocol"], task["protocol"], "interface thermal protocol")
    _check(task["runner"], "slurm", "interface thermal task.runner")
    _check_saved_job(product, task, "interface thermal")
    mapping, mapping_file = _atom_map(task_file, product["model_id"], product["model_version"])
    native = product.get("native_result")
    if native is not None and not isinstance(native, dict):
        raise ValueError("interface thermal native_result must be an object or null")
    if native is not None:
        _check_native_job(native, task, "interface thermal native_result")
    identity = _identity(product, task, mapping, None, native)
    native_thermal = product["native_thermal"]
    _check(native_thermal["schema"], "mlcc.lammps-thermal-result.v1", "native thermal schema")
    if not isinstance(native_thermal["profile_frames"], list):
        raise ValueError("native thermal profile_frames must be a list")
    files = _source_files(product, product_file, task, task_file, mapping_file)
    return (_source_record("interface_thermal_product", product, product_file, task, task_file, files, identity),
            product, task, mapping)


def bind_thermal_source(product_path: str | Path, study: dict[str, Any]) -> dict[str, Any]:
    """Rebind one saved local-stress or interface-thermal product."""
    product, _ = _json(product_path)
    if product["schema"] == LOCAL_SCHEMA:
        return _bind_local(product_path, study)[0]
    if product["schema"] == THERMAL_SCHEMA:
        return _bind_interface(product_path, study)[0]
    raise ValueError(f"unsupported thermal source schema: {product['schema']!r}")


def _frame_keys(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"step": frame["step"], "physical_time_ps": frame["physical_time_ps"]} for frame in frames]


def _local_state(entry: dict[str, Any], bound: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    record, product, _, _ = bound
    local = product["local_stress"]
    region_id = entry["region_id"]
    regions = [region for region in local["regions"] if region["region_id"] == region_id]
    if len(regions) != 1:
        raise ValueError(f"saved local stress region {region_id!r} is not unique")
    region = regions[0]
    volume = region["volume_source"]
    frames = local["selected_frames"] or []
    if region["stress_GPa"] is not None:
        _check(region["tensor_basis"], "source_cartesian", f"region {region_id}.tensor_basis")
        _check(region["stress_sign"], "tension_positive", f"region {region_id}.stress_sign")
    missing = list(product.get("missing_evidence", []))
    missing.extend(local.get("missing_evidence", []))
    missing.extend(region.get("missing_evidence", []))
    return {
        "state_id": entry["state_id"], "identity": copy.deepcopy(record["identity"]),
        "region": {"region_id": region_id, "atom_ids": copy.deepcopy(region["atom_ids"]),
                    "volume_angstrom3": volume["volume_angstrom3"],
                    "volume_definition": volume["volume_definition"]},
        "stress_GPa": copy.deepcopy(region["stress_GPa"]),
        "frame_keys": _frame_keys(frames), "temperature_history": None,
        "temperature_context": None, "mechanical_history": None,
        "missing_evidence": list(dict.fromkeys(missing)),
        "source_refs": copy.deepcopy(record["source_refs"]),
    }


def _history(path: str | Path, schema: str, study: dict[str, Any], state: dict[str, Any],
             stress_record: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    history, history_file = _json(path)
    _check(history["schema"], schema, f"{schema} schema")
    if history.get("study_id") is not None:
        _check(history["study_id"], study["study_id"], f"{schema}.study_id")
    if history.get("case_id") is not None:
        _check(history["case_id"], study["case_id"], f"{schema}.case_id")
    if history.get("case_role") is not None:
        _check(history["case_role"], study["case_role"], f"{schema}.case_role")
    _check(history["model_id"], study["model"]["model_id"], f"{schema}.model_id")
    _check(history["model_version"], study["model"]["version"], f"{schema}.model_version")
    history_task = None
    if history.get("task_path") is not None:
        history_task_file = _existing(history["task_path"], f"{schema}.task_path", history_file.parent)
        history_task, _ = _json(history_task_file)
        _check(history_task["task_id"], history["task_id"], f"{schema} task_id")
        _check(history_task["runner"], "slurm", f"{schema} task.runner")
    if stress_record is not None:
        _check(history["task_id"], stress_record["task_id"], f"{schema}.task_id")
        _check(str(history["native_job_id"]), str(stress_record["native_job"]["scheduler_job_id"]),
               f"{schema}.native_job_id")
        for field in ("potential_id", "potential_version", "method_set"):
            if history.get(field) is not None:
                _check(history[field], stress_record["identity"][field], f"{schema}.{field}")
    _check(history["region_id"], state["region"]["region_id"], f"{schema}.region_id")
    _check(history["atom_ids"], state["region"]["atom_ids"], f"{schema}.atom_ids")
    if schema == MECHANICAL_SCHEMA and stress_record is not None:
        _check(history["protocol"], stress_record["protocol"], f"{schema}.protocol")
    samples = history["samples"]
    _check(_frame_keys(samples), state["frame_keys"], f"{schema}.samples frame_keys")
    source_files = {"history": str(history_file)}
    if history_task is not None:
        source_files["task"] = str(history_task_file)
    for name, source in history["source_files"].items():
        source_files[name] = str(_existing(source, f"{schema}.source_files.{name}", history_file.parent))
    refs = history.get("source_refs", list(source_files.values()))
    return copy.deepcopy(history), copy.deepcopy(refs)


def _thermal_context(
    bound: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], state: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    record, product, _, _ = bound
    native = product["native_thermal"]
    context = {
        "schema": THERMAL_SCHEMA, "task_id": product["task_id"],
        "native_job_id": product["source_task"]["scheduler_job_id"],
        "model_id": product["model_id"], "model_version": product["model_version"],
        "region_id": state["region"]["region_id"], "atom_ids": None, "samples": None,
        "profile_frames": copy.deepcopy(native["profile_frames"]),
        "analysis_request": copy.deepcopy(product["analysis_request"]),
        "thermal_response": copy.deepcopy(product["thermal_response"]),
        "native_thermal": copy.deepcopy(native), "protocol": copy.deepcopy(product["protocol"]),
        "source_task": copy.deepcopy(product["source_task"]),
        "missing_evidence": copy.deepcopy(product.get("missing_evidence", [])),
        "source_files": copy.deepcopy(native["source_files"]),
    }
    return context, copy.deepcopy(record)


def _add_source(sources: list[dict[str, Any]], record: dict[str, Any]) -> None:
    if not any(item["product_path"] == record["product_path"] for item in sources):
        sources.append(copy.deepcopy(record))


def _state(entry: dict[str, Any], study: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    for field in ("state_id", "region_id", "stress_product_path", "temperature_history_path",
                  "mechanical_history_path", "temperature_product_path"):
        if field not in entry:
            raise ValueError(f"state {entry.get('state_id')!r} must explicitly provide {field}")
    if not isinstance(entry["state_id"], str) or not entry["state_id"]:
        raise ValueError("state_id must be a non-empty string")
    state = {
        "state_id": entry["state_id"],
        "identity": {"study_id": study["study_id"], "model_id": study["model"]["model_id"],
                      "model_version": study["model"]["version"], "potential_id": None,
                      "potential_version": None, "method_set": None, "source_atom_ids": None,
                      "source_cell_angstrom": None, "contribution": None, "kinetic_included": None,
                      "native_component_order": None},
        "region": {"region_id": entry["region_id"], "atom_ids": None,
                    "volume_angstrom3": None, "volume_definition": None},
        "stress_GPa": None, "frame_keys": [], "temperature_history": None,
        "temperature_context": None, "mechanical_history": None,
        "missing_evidence": [], "source_refs": [],
    }
    stress_record = None
    if entry["stress_product_path"] is None:
        state["missing_evidence"].append("stress_product_path")
    else:
        bound = _bind_local(entry["stress_product_path"], study)
        stress_record = bound[0]
        _add_source(sources, stress_record)
        local_state = _local_state(entry, bound)
        state.update({key: local_state[key] for key in ("identity", "region", "stress_GPa", "frame_keys",
                                                        "missing_evidence", "source_refs")})
    if entry["temperature_history_path"] is not None:
        history, refs = _history(entry["temperature_history_path"], TEMPERATURE_SCHEMA, study, state, stress_record)
        state["temperature_history"] = history
        state["source_refs"].extend(refs)
    elif entry["temperature_product_path"] is None:
        state["missing_evidence"].append("temperature_history_path_or_temperature_product_path")
    if entry["temperature_product_path"] is not None:
        bound = _bind_interface(entry["temperature_product_path"], study)
        if stress_record is not None:
            for key in ("study_id", "model_id", "model_version", "potential_id", "potential_version",
                        "method_set", "source_atom_ids", "source_cell_angstrom"):
                _check(stress_record["identity"][key], bound[0]["identity"][key], f"temperature source identity.{key}")
        context, source = _thermal_context(bound, state)
        if stress_record is None:
            state["identity"] = copy.deepcopy(source["identity"])
            state["identity"]["contribution"] = None
            state["identity"]["kinetic_included"] = None
            state["identity"]["native_component_order"] = None
        state["temperature_context"] = context
        state["missing_evidence"].extend(context["missing_evidence"])
        state["missing_evidence"].append("temperature_bin_to_region_atom_mapping")
        state["source_refs"].extend(source["source_refs"])
        _add_source(sources, source)
    if entry["mechanical_history_path"] is not None:
        history, refs = _history(entry["mechanical_history_path"], MECHANICAL_SCHEMA, study, state, stress_record)
        state["mechanical_history"] = history
        state["source_refs"].extend(refs)
    else:
        state["missing_evidence"].append("mechanical_history_path")
    state["missing_evidence"] = list(dict.fromkeys(state["missing_evidence"]))
    return state


def build_thermal_stress(study_path: str | Path, request_path: str | Path) -> dict[str, Any]:
    """Bind saved products and call the pure stress-difference function once."""
    study, _ = _json(study_path)
    request, request_file = _json(request_path)
    _check(request["schema"], REQUEST_SCHEMA, "thermal stress request schema")
    if request.get("study_id") is not None:
        _check(request["study_id"], study["study_id"], "request.study_id")
    if request.get("case_id") is not None:
        _check(request["case_id"], study["case_id"], "request.case_id")
    if "reference" not in request or "states" not in request:
        raise ValueError("thermal stress request must explicitly provide reference and states")
    reference_entry, states_entries = request["reference"], request["states"]
    if reference_entry is not None and not isinstance(reference_entry, dict):
        raise ValueError("request.reference must be an object or null")
    if not isinstance(states_entries, list):
        raise ValueError("request.states must be a list")
    ids = [entry["state_id"] for entry in states_entries]
    if len(ids) != len(set(ids)):
        raise ValueError("thermal stress state_id values must be unique")
    sources: list[dict[str, Any]] = []
    reference = _state(reference_entry, study, sources) if reference_entry is not None else None
    states = [_state(entry, study, sources) for entry in states_entries]
    response = thermal_stress_change(reference, states)
    missing: list[str] = []
    for state in ([reference] if reference is not None else []) + states:
        missing.extend(state["missing_evidence"])
    missing.extend(response["missing_evidence"])
    return {
        "schema": PRODUCT_SCHEMA, "study_id": study["study_id"], "case_id": study["case_id"],
        "case_role": study["case_role"],
        "fixture": bool(study["model"].get("fixture", False)) or study["case_role"] == "engineering_fixture",
        "request_path": str(request_file), "analysis_request": copy.deepcopy(request),
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "status": response["status"], "response": copy.deepcopy(response),
        "sources": sources, "missing_evidence": list(dict.fromkeys(missing)),
        "production_qualified": False,
    }


def _md_history_source_files(
    request_file: Path,
    task_file: Path,
    sampling_file: Path,
    collection_file: Path,
    atom_map_file: Path,
) -> dict[str, str]:
    return {
        "request": str(request_file),
        "task": str(task_file),
        "sampling": str(sampling_file),
        "collection": str(collection_file),
        "atom-map": str(atom_map_file),
    }


def _md_validate_identity(
    task: dict[str, Any],
    collection: dict[str, Any],
    sampling: dict[str, Any],
    mapping: dict[str, Any],
) -> None:
    """Bind the three saved envelopes before any stress averaging."""

    _check(task["runner"], "slurm", "MD source task.runner")
    _check(task["scheduler_state"], "COMPLETED", "MD source task.scheduler_state")
    _check(task["exit_code"], "0:0", "MD source task.exit_code")
    _check(task["protocol"]["kind"], "md", "MD source protocol.kind")
    _check(task["protocol"]["purpose"], "md_native_sampling", "MD source protocol.purpose")
    _check(task["protocol"]["ensemble"], "nvt", "MD source protocol.ensemble")
    _check(sampling["schema"], MD_NATIVE_STRESS_SCHEMA, "MD sampling schema")
    _check(collection["schema"], MD_COLLECTION_SCHEMA, "MD collection schema")
    for field in (
        "task_id",
        "study_id",
        "case_id",
        "case_role",
        "model_id",
        "model_version",
        "method_set",
        "scheduler_job_id",
        "scheduler_state",
        "exit_code",
    ):
        _check(sampling[field], task[field], f"MD sampling {field}")
    _check(sampling["protocol"], task["protocol"], "MD sampling protocol")
    _check(collection["task_id"], task["task_id"], "MD collection task_id")
    _check(collection["protocol"], task["protocol"], "MD collection protocol")
    _check(collection["native_job"]["scheduler_job_id"], task["scheduler_job_id"],
           "MD collection native_job.scheduler_job_id")
    _check(collection["native_job"]["scheduler_state"], task["scheduler_state"],
           "MD collection native_job.scheduler_state")
    _check(collection["native_job"]["exit_code"], task["exit_code"],
           "MD collection native_job.exit_code")
    _check(collection["lineage"]["study_id"], task["study_id"], "MD collection lineage.study_id")
    _check(collection["lineage"]["case_id"], task["case_id"], "MD collection lineage.case_id")
    _check(collection["lineage"]["case_role"], task["case_role"], "MD collection lineage.case_role")
    _check(collection["lineage"]["method_set"], task["method_set"], "MD collection lineage.method_set")
    _check(collection["model"]["model_id"], task["model_id"], "MD collection model.model_id")
    _check(collection["model"]["version"], task["model_version"], "MD collection model.version")
    _check(collection["potential"]["potential_id"], task["potential"]["potential_id"],
           "MD collection potential.potential_id")
    _check(collection["potential"]["version"], task["potential"]["version"],
           "MD collection potential.version")
    _check(sampling["model"]["model_id"], task["model_id"], "MD sampling model.model_id")
    _check(sampling["model"]["version"], task["model_version"], "MD sampling model.version")
    _check(sampling["potential"]["potential_id"], task["potential"]["potential_id"],
           "MD sampling potential.potential_id")
    _check(sampling["potential"]["version"], task["potential"]["version"],
           "MD sampling potential.version")
    _check(sampling["source_cell_angstrom"], mapping["source_cell_angstrom"],
           "MD sampling source_cell_angstrom")
    _check(sampling["component_order"], MD_COMPONENT_ORDER, "MD sampling component_order")
    _check(
        sampling["protocol"]["native_sampling"]["component_order"],
        MD_COMPONENT_ORDER,
        "MD sampling protocol.native_sampling.component_order",
    )
    _check(sampling["stress_volume_unit"], "bar*angstrom^3", "MD sampling stress_volume_unit")
    _check(sampling["tensor_basis"], "lammps_prism", "MD sampling tensor_basis")
    _check(sampling["contribution"], "virial", "MD sampling contribution")
    _check(sampling["kinetic_included"], False, "MD sampling kinetic_included")
    source_atom_ids = list(mapping["source_atom_ids"])
    for frame in sampling["frames"]:
        _check(frame["atom_ids"], source_atom_ids, "MD sampling frame atom_ids")
        _check(frame["component_order"], MD_COMPONENT_ORDER, "MD sampling frame component_order")


def _md_mechanical_constraint(
    request: dict[str, Any], sampling: dict[str, Any], task: dict[str, Any], mapping: dict[str, Any]
) -> dict[str, Any]:
    constraint = request["mechanical_constraint"]
    if not isinstance(constraint, dict):
        raise ValueError("md thermal sources mechanical_constraint must be an object")
    _check(sampling["mechanical_constraint"], constraint, "MD sampling mechanical_constraint")
    _check(constraint["cell_angstrom"], mapping["source_cell_angstrom"],
           "MD mechanical_constraint.cell_angstrom")
    _check(constraint["boundary"], task["protocol"]["boundary"],
           "MD mechanical_constraint.boundary")
    _check(constraint["fixed_atom_ids"], [], "MD mechanical_constraint.fixed_atom_ids")
    _check(constraint["loading"]["kind"], "none", "MD mechanical_constraint.loading.kind")
    return copy.deepcopy(constraint)


def _cell_volume(cell: list[list[float]]) -> float:
    a, b, c = cell
    return abs(
        float(a[0]) * (float(b[1]) * float(c[2]) - float(b[2]) * float(c[1]))
        - float(a[1]) * (float(b[0]) * float(c[2]) - float(b[2]) * float(c[0]))
        + float(a[2]) * (float(b[0]) * float(c[1]) - float(b[1]) * float(c[0]))
    )


def _md_temperature_samples(
    selected_frames: list[dict[str, Any]], collection: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = collection["thermo"]["rows"]
    rows_by_step = {int(row["step"]): row for row in rows}
    samples: list[dict[str, Any]] = []
    for frame in selected_frames:
        row = rows_by_step[int(frame["step"])]
        _check(row["physical_time_ps"], frame["physical_time_ps"],
               f"MD thermo frame step {frame['step']} physical_time_ps")
        samples.append(
            {
                "step": frame["step"],
                "physical_time_ps": frame["physical_time_ps"],
                "temperature_K": float(row["temp"]),
            }
        )
    return samples


def _md_history(
    schema: str,
    task: dict[str, Any],
    task_file: Path,
    analysis: dict[str, Any],
    region: dict[str, Any],
    samples: list[dict[str, Any]],
    source_files: dict[str, str],
    *,
    mechanical_constraint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history: dict[str, Any] = {
        "schema": schema,
        "study_id": task["study_id"],
        "case_id": task["case_id"],
        "case_role": task["case_role"],
        "task_id": task["task_id"],
        "task_path": str(task_file),
        "native_job_id": task["scheduler_job_id"],
        "model_id": task["model_id"],
        "model_version": task["model_version"],
        "potential_id": task["potential"]["potential_id"],
        "potential_version": task["potential"]["version"],
        "method_set": task["method_set"],
        "region_id": region["region_id"],
        "atom_ids": copy.deepcopy(region["atom_ids"]),
        "observation_window": copy.deepcopy(analysis["observation_window"]),
        "samples": samples,
        "source_files": source_files,
        "source_refs": list(source_files.values()),
    }
    if schema == MECHANICAL_SCHEMA:
        history["protocol"] = copy.deepcopy(task["protocol"])
        history["samples"] = [
            {
                "step": sample["step"],
                "physical_time_ps": sample["physical_time_ps"],
                "constraint": copy.deepcopy(mechanical_constraint),
            }
            for sample in samples
        ]
    return history


def build_md_thermal_sources(
    request_path: str | Path, output_directory: str | Path
) -> dict[str, Any]:
    """Bind one saved native MD sampling envelope to the thermal-stress path.

    The native sampling and MD collection have already been produced and
    validated by their respective readers.  This adapter only binds their
    saved identity, averages the declared virial-only nine-component frames
    through :func:`local_stress_from_frames`, and saves the three products
    consumed by :func:`build_thermal_stress`.
    """

    request, request_file = _json(request_path)
    _check(request["schema"], MD_THERMAL_REQUEST_SCHEMA, "MD thermal sources request schema")
    for field in ("task_path", "sampling_path", "collection_path", "analysis", "mechanical_constraint"):
        if field not in request:
            raise ValueError(f"MD thermal sources request must explicitly provide {field}")
    task_file = _existing(request["task_path"], "MD thermal sources task_path", request_file.parent)
    sampling_file = _existing(request["sampling_path"], "MD thermal sources sampling_path", request_file.parent)
    collection_file = _existing(request["collection_path"], "MD thermal sources collection_path", request_file.parent)
    task, _ = _json(task_file)
    sampling, _ = _json(sampling_file)
    collection, _ = _json(collection_file)
    mapping, mapping_file = _atom_map(task_file, task["model_id"], task["model_version"])
    _md_validate_identity(task, collection, sampling, mapping)
    analysis = request["analysis"]
    if not isinstance(analysis, dict):
        raise ValueError("MD thermal sources analysis must be an object")
    _check(analysis["schema"], "mlcc.local-stress-analysis.v1", "MD thermal sources analysis schema")
    regions = analysis["regions"]
    if len(regions) != 1 or regions[0]["region_id"] != "whole_cell":
        raise ValueError("MD thermal sources analysis must contain exactly one whole_cell region")
    region = regions[0]
    _check(region["atom_ids"], mapping["source_atom_ids"], "MD whole_cell atom_ids")
    if region["volume_angstrom3"] is not None:
        expected_volume = _cell_volume(mapping["source_cell_angstrom"])
        if not math.isclose(
            float(region["volume_angstrom3"]), expected_volume, rel_tol=0.0, abs_tol=1.0e-12
        ):
            raise ValueError(
                "MD whole_cell volume_angstrom3 differs from the source cell determinant"
            )
    mechanical_constraint = _md_mechanical_constraint(request, sampling, task, mapping)

    local_stress = local_stress_from_frames(
        analysis,
        sampling["frames"],
        sampling["source_cell_angstrom"],
        component_order=sampling["component_order"],
    )
    local_stress = copy.deepcopy(local_stress)
    for local_region in local_stress["regions"]:
        conversion = local_region.get("conversion")
        if conversion is not None and conversion.get("tensor_contribution") == "virial_only_zero_velocity":
            conversion["tensor_contribution"] = "virial_only"
    selected_frames = local_stress["selected_frames"] or []
    source_files = _md_history_source_files(
        request_file, task_file, sampling_file, collection_file, mapping_file
    )
    temperature_history = _md_history(
        TEMPERATURE_SCHEMA,
        task,
        task_file,
        analysis,
        region,
        _md_temperature_samples(selected_frames, collection),
        source_files,
    )
    mechanical_history = _md_history(
        MECHANICAL_SCHEMA,
        task,
        task_file,
        analysis,
        region,
        _frame_keys(selected_frames),
        source_files,
        mechanical_constraint=mechanical_constraint,
    )

    native_local_stress = copy.deepcopy(sampling)
    native_local_stress["source_files"] = dict(sampling["source_files"])
    native_local_stress["source_files"].update(
        {
            "request.json": str(request_file),
            "task.json": str(task_file),
            "collection.json": str(collection_file),
            "analysis.json": str(request_file),
            "atom-map.json": str(mapping_file),
        }
    )
    local_product: dict[str, Any] = {
        "schema": LOCAL_SCHEMA,
        "study_id": task["study_id"],
        "case_id": task["case_id"],
        "case_role": task["case_role"],
        "fixture": bool(task.get("fixture", False)),
        "model_id": task["model_id"],
        "model_version": task["model_version"],
        "model_path": task.get("model_path"),
        "parent_model": copy.deepcopy(task.get("parent_model")),
        "method_set": task["method_set"],
        "potential": copy.deepcopy(task["potential"]),
        "task_id": task["task_id"],
        "task_path": str(task_file),
        "request_path": str(request_file),
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "analysis_request": copy.deepcopy(analysis),
        "protocol": copy.deepcopy(task["protocol"]),
        "source_task": _native_job(task),
        "status": local_stress["status"],
        "local_stress": local_stress,
        "native_local_stress": native_local_stress,
        "native_result": None,
        "interface_sources": None,
        "interface_provenance": None,
        "source_files": {
            "request": str(request_file),
            "task": str(task_file),
            "sampling": str(sampling_file),
            "collection": str(collection_file),
            "atom-map": str(mapping_file),
            **{f"sampling:{name}": value for name, value in sampling["source_files"].items()},
            **{f"collection:{name}": value for name, value in collection["source_files"].items()},
        },
        "missing_evidence": copy.deepcopy(local_stress["missing_evidence"]),
        "failure_evidence": {},
        "production_qualified": False,
    }

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    local_path = _write_json(output / "local-stress-product.json", local_product)
    temperature_path = _write_json(output / "temperature-history.json", temperature_history)
    mechanical_path = _write_json(output / "mechanical-history.json", mechanical_history)
    manifest = {
        "schema": MD_THERMAL_MANIFEST_SCHEMA,
        "status": "saved" if local_stress["status"] in {"available", "mathematical_fixture"} else local_stress["status"],
        "request_path": str(request_file),
        "task_path": str(task_file),
        "sampling_path": str(sampling_file),
        "collection_path": str(collection_file),
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "task_id": task["task_id"],
        "study_id": task["study_id"],
        "case_id": task["case_id"],
        "case_role": task["case_role"],
        "native_job": _native_job(task),
        "analysis_request": copy.deepcopy(analysis),
        "mechanical_constraint": copy.deepcopy(mechanical_constraint),
        "sampling_windows": copy.deepcopy(sampling.get("sampling_windows")),
        "selected_frame_count": len(selected_frames),
        "source": {
            "schema": sampling["schema"],
            "component_order": copy.deepcopy(sampling["component_order"]),
            "contribution": sampling["contribution"],
            "kinetic_included": sampling["kinetic_included"],
            "tensor_basis": sampling["tensor_basis"],
        },
        "artifacts": {
            "local_stress": str(local_path),
            "temperature_history": str(temperature_path),
            "mechanical_history": str(mechanical_path),
            "manifest": str(output / "manifest.json"),
        },
        "source_refs": list(source_files.values()),
        "missing_evidence": list(dict.fromkeys(local_stress["missing_evidence"])),
        "production_qualification": False,
    }
    _write_json(output / "manifest.json", manifest)
    return manifest


__all__ = ["bind_thermal_source", "build_thermal_stress", "build_md_thermal_sources"]
