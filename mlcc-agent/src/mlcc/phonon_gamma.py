"""Source-bound Gamma fixed-cell Hessian adaptation for the P7 harmonic result.

This module consumes an already assembled, source-bound Phonopy harmonic result.
It does not fit force constants, create displacement structures, submit jobs, or
apply ASR/NAC corrections.  The result is a software integration artifact and
is never granted scientific or production qualification by this adapter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .modeling import read_model_artifacts
from .phonon_forces import _method_physics_without_model, load_native_force_task
from .phonons import (
    FORCE_CONSTANT_UNIT,
    HARMONIC_SCHEMA,
    _force_records,
    _rebuild_phonopy_from_plan,
    load_phonon_displacement_plan,
)
from .strain import _input_values, _kpt_values
from .polarization import _METHOD_KEYS
from .studies import load_study


GAMMA_HESSIAN_SCHEMA = "mlcc.gamma-force-constants.v1"
GEOMETRY_ATOL_ANGSTROM = 1e-7
MASS_ATOL_AMU = 1e-8


def read_native_gamma_method_source(
    task_path: str | Path, *, expected_method: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read a P7 displacement or P4 parent task's method and protocol.

    A defined task can be audited before execution.  This reader never makes
    it a completed force source; the existing force-collection gates do that.
    """
    from .dielectric_response import p5_method_identity, p5_method_comparison

    path = Path(task_path).resolve()
    directory = path if path.is_dir() else path.parent
    task_file = directory / "task.json"
    method_file = directory / "method.json"
    task = _load_json_object(task_file, "task")
    method = _load_json_object(method_file, "method")
    phonon_identity = task.get("phonon_displacement")
    is_parent_reference = phonon_identity is None
    if task["calculation"] != "scf" or (
        task["stage"] != "P7" and not (task["stage"] == "P4" and is_parent_reference)
    ):
        raise ValueError("Gamma native method source requires a P7 displacement or P4 parent-reference SCF task")
    if (task["model_id"], task["model_version"], task["method_set"]) != (
        method["model_id"], method["version"], method["method_set"]
    ):
        raise ValueError("Gamma source task/model/method identity differs")
    if method["engine"] != "abacus" or method["abacus_version_target"] != "3.10.1":
        raise ValueError("Gamma native method source requires ABACUS 3.10.1")
    if (task["engine"], task["engine_version"]) != (method["engine"], method["abacus_version_target"]):
        raise ValueError("Gamma source task engine differs from its method")
    method_record = {key: method[key] for key in (*_METHOD_KEYS, "method_set") if key in method}
    if method.get("basis_type") == "lcao":
        for key in ("numerical_orbital_ids", "numerical_orbitals", "orbital_header_snapshot"):
            if key in method:
                method_record[key] = method[key]
    missing_physical = [key for key in _METHOD_KEYS if key not in method and key != "kpoints"]
    if "smearing_sigma_Ry" not in method["parameters"]:
        missing_physical.append("parameters.smearing_sigma_Ry")
    input_file = directory / "INPUT"
    kpt_file = directory / "KPT"
    native_input_file = directory / f"OUT.{method['suffix']}" / "INPUT"
    result_file = directory / "result.json"
    requested = _input_values(input_file)
    kpt = _kpt_values(kpt_file) if kpt_file.is_file() else None
    effective = _input_values(native_input_file) if native_input_file.is_file() else None
    result = _load_json_object(result_file, "result") if result_file.is_file() else None
    if result is not None:
        for key in ("task_id", "method_set", "scheduler_job_id", "model_id", "model_version"):
            if result[key] != task[key]:
                raise ValueError(f"Gamma saved result {key} differs from task")
    if kpt is not None and kpt["grid"] != list(method["kpoints"]):
        raise ValueError("Gamma task KPT grid differs from its method")
    protocol: dict[str, Any] = {}
    for key in ("scf_thr", "scf_nmax", "mixing_beta", "pw_diag_thr", "nbands", "ecutwfc"):
        if effective is not None and key in effective:
            value, source, scope = float(effective[key]), native_input_file, "native_echo"
        elif key in requested:
            value, source, scope = float(requested[key]), input_file, "requested_input"
        else:
            value, source, scope = None, None, "unresolved_missing"
        protocol[key] = {
            "value": value, "source_file": None if source is None else str(source),
            "source_field": key, "scope": scope,
        }
    for name, field in (("kpoints", "grid"), ("kpoint_shift", "offset")):
        value = None if kpt is None else kpt[field]
        protocol[name] = {"value": value, "source_file": None if kpt is None else str(kpt_file), "source_field": field, "scope": "unresolved_missing" if kpt is None else "requested_input"}
        if value is not None:
            method_record[name] = value
    if protocol["pw_diag_thr"]["value"] is not None:
        method_record["pw_diag_thr"] = protocol["pw_diag_thr"]["value"]
    identity = None if missing_physical else p5_method_identity(method_record)
    comparison = None
    if expected_method is not None and identity is not None:
        comparison = p5_method_comparison(method_record, expected_method)
        if not comparison["same_physical_method"]:
            raise ValueError("Gamma requested physical method differs from the native source task")
    for name, value, file in (("method_set", method["method_set"], method_file), ("calculation", task["calculation"], task_file)):
        protocol[name] = {"value": value, "source_file": str(file), "source_field": name, "scope": "declared"}
    missing = [f"method.{key}" for key in missing_physical]
    missing.extend(name for name, item in protocol.items() if item["value"] is None)
    if effective is None:
        missing.append("native_INPUT")
    if result is None:
        missing.append("result.json")
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        missing.append("scheduler_completed_0")
    return {
        "schema": "mlcc.gamma-native-method-source.v1",
        "status": "unresolved_missing" if missing else "source_fields_present",
        "task_id": task["task_id"], "scheduler_job_id": task.get("scheduler_job_id"),
        "scheduler_state": task.get("scheduler_state"), "exit_code": task.get("exit_code"),
        "model_id": task["model_id"], "model_version": task["model_version"],
        "reference_kind": "parent_reference" if is_parent_reference else "displacement",
        "phonon_displacement": phonon_identity,
        "method_identity": identity,
        "method_record": method_record,
        "requested_method_comparison": comparison,
        "method_field_sources": {key: {"source_file": str(method_file), "source_field": key} for key in _METHOD_KEYS if key in method},
        "numerical_protocol": protocol, "missing_fields": missing,
        "raw_method": method, "requested_INPUT": requested, "native_INPUT": effective,
        "source_files": {
            "task": str(task_file), "method": str(method_file), "INPUT": str(input_file), "KPT": str(kpt_file) if kpt is not None else None,
            "native_INPUT": str(native_input_file) if effective is not None else None,
            "result": str(result_file) if result is not None else None,
        },
        "scientific_qualification": False, "production_qualification": False,
        "complete_force_set_established": False,
    }


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _absolute_existing_path(value: Any, name: str, *, directory: bool | None = None) -> Path:
    if isinstance(value, Path):
        path = value
    else:
        path = Path(_non_empty_string(value, name))
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"{name} does not exist: {resolved}")
    if directory is True and not resolved.is_dir():
        raise ValueError(f"{name} must be a directory: {resolved}")
    if directory is False and not resolved.is_file():
        raise ValueError(f"{name} must be a file: {resolved}")
    return resolved


def _load_json_object(path: Path, name: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value


def _canonical_task_record(value: Any, name: str, *, allow_directory: bool) -> Path:
    path = _absolute_existing_path(value, name)
    if path.is_dir():
        if not allow_directory:
            raise ValueError(f"{name} must be an absolute task.json file")
        path = path / "task.json"
    elif path.name != "task.json":
        raise ValueError(f"{name} must resolve to task.json")
    if not path.is_file():
        raise ValueError(f"{name} must resolve to an existing task.json")
    return path.resolve()


def _select_native_task_records(
    collection: Mapping[str, Any], source_binding: Mapping[str, Any]
) -> tuple[list[Path], bool]:
    """Choose saved collection records, retaining legacy explicit ordering.

    The boolean marks a new collection carrying its canonical manifest-order
    list.  Legacy collections have no such field and retain the caller's
    historical explicit order.
    """
    collection_has_records = "native_task_records" in collection
    if collection_has_records:
        raw_saved = collection.get("native_task_records")
        if not isinstance(raw_saved, list) or not raw_saved:
            raise ValueError("native force collection native_task_records must be a non-empty list")
        saved = [
            _canonical_task_record(
                value,
                "collection.native_task_records entry",
                allow_directory=False,
            )
            for value in raw_saved
        ]
        if len(set(saved)) != len(saved):
            raise ValueError("collection.native_task_records contains duplicate task records")
        if "native_task_records" in source_binding:
            raw_explicit = source_binding.get("native_task_records")
            if not isinstance(raw_explicit, list) or not raw_explicit:
                raise ValueError("source_binding.native_task_records must be a non-empty list")
            explicit = [
                _canonical_task_record(
                    value,
                    "source_binding.native_task_records entry",
                    allow_directory=True,
                )
                for value in raw_explicit
            ]
            if len(set(explicit)) != len(explicit):
                raise ValueError("source_binding.native_task_records contains duplicate task records")
            if explicit != saved:
                raise ValueError(
                    "source_binding.native_task_records differs from the saved collection records"
                )
        return saved, True

    if "native_task_records" not in source_binding:
        raise ValueError("native_source_bound requires native_task_records")
    raw_explicit = source_binding.get("native_task_records")
    if not isinstance(raw_explicit, list) or not raw_explicit:
        raise ValueError("source_binding.native_task_records must be a non-empty list")
    explicit = [
        _canonical_task_record(
            value,
            "source_binding.native_task_records entry",
            allow_directory=True,
        )
        for value in raw_explicit
    ]
    if len(set(explicit)) != len(explicit):
        raise ValueError("source_binding.native_task_records contains duplicate task records")
    return explicit, False


def _positive_or_zero(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not np.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _required_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a non-empty object")
    return value


def _validate_parent_binding(
    parent: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], Any]:
    required = ("study_id", "study_path", "model_id", "model_version", "model_path")
    for field in required:
        _non_empty_string(parent.get(field), f"parent.{field}")
    study_path = _absolute_existing_path(parent["study_path"], "parent.study_path")
    model_path = _absolute_existing_path(parent["model_path"], "parent.model_path", directory=True)
    source_model = manifest.get("source_model")
    if not isinstance(source_model, Mapping):
        raise ValueError("phonon plan source_model is required")
    source_model_path = _absolute_existing_path(source_model.get("path"), "plan.source_model.path", directory=True)
    if (
        parent["model_id"] != source_model.get("model_id")
        or parent["model_version"] != source_model.get("version")
        or model_path != source_model_path
    ):
        raise ValueError("parent model binding differs from the phonon plan source_model")
    source_model_artifacts = read_model_artifacts(model_path)
    if (source_model_artifacts.model_id, source_model_artifacts.version) != (
        parent["model_id"],
        parent["model_version"],
    ):
        raise ValueError("parent model binding differs from the persisted model artifact")
    study_document = load_study(study_path)
    if not isinstance(study_document, Mapping):
        raise ValueError("parent.study_path must contain a Study object")
    if study_document.get("study_id") != parent["study_id"]:
        raise ValueError("parent Study study_id differs from the explicit parent binding")
    study_model = study_document.get("model")
    if not isinstance(study_model, Mapping):
        raise ValueError("parent Study must contain a model reference")
    if (
        study_model.get("model_id") != parent["model_id"]
        or study_model.get("version") != parent["model_version"]
    ):
        raise ValueError("parent Study model reference differs from the parent model binding")
    declared_study_model_path = study_model.get("path", study_model.get("model_path"))
    if declared_study_model_path is not None:
        if _absolute_existing_path(declared_study_model_path, "parent Study model path", directory=True) != model_path:
            raise ValueError("parent Study model path differs from the parent model binding")
    bound_parent = {
        "study_id": str(parent["study_id"]),
        "study_path": str(study_path),
        "model_id": str(parent["model_id"]),
        "model_version": str(parent["model_version"]),
        "model_path": str(model_path),
    }
    return bound_parent, source_model_artifacts


def _validate_harmonic_result(
    harmonic_path: Path,
    plan_path: Path,
    harmonic: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> np.ndarray:
    if harmonic.get("schema") != HARMONIC_SCHEMA:
        raise ValueError(f"unsupported harmonic result schema: {harmonic.get('schema')!r}")
    plan_record = harmonic.get("plan")
    if not isinstance(plan_record, Mapping):
        raise ValueError("harmonic result requires plan")
    declared_plan = _absolute_existing_path(plan_record.get("manifest_path"), "harmonic.plan.manifest_path", directory=False)
    if declared_plan != plan_path:
        raise ValueError("harmonic result plan manifest differs from the requested plan")
    if plan_record.get("plan_id") != manifest.get("plan_id") or plan_record.get("version") != manifest.get("version"):
        raise ValueError("harmonic result plan identity differs from the requested plan")
    if harmonic.get("force_constants_unit") != FORCE_CONSTANT_UNIT:
        raise ValueError(f"harmonic.force_constants_unit must be exactly {FORCE_CONSTANT_UNIT!r}")
    if harmonic.get("force_constants_basis") != "phonopy_supercell_atom_order":
        raise ValueError("harmonic force_constants_basis must be phonopy_supercell_atom_order")
    force_constants = np.asarray(harmonic.get("force_constants"), dtype=float)
    if not np.all(np.isfinite(force_constants)):
        raise ValueError("harmonic force_constants must contain finite values")
    force_input = harmonic.get("force_input")
    if not isinstance(force_input, Mapping):
        raise ValueError("harmonic result requires force_input")
    expected_entry_ids = [str(entry["entry_id"]) for entry in manifest["displacements"]]
    if force_input.get("entry_ids") != expected_entry_ids:
        raise ValueError("harmonic force_input entry_ids differ from the plan")
    source_refs = force_input.get("source_refs")
    if not isinstance(source_refs, list) or len(source_refs) != len(expected_entry_ids):
        raise ValueError("harmonic force_input source_refs must cover every displacement")
    if any(not isinstance(value, str) or not value.strip() for value in source_refs):
        raise ValueError("harmonic force_input source_refs must be non-empty")
    if not isinstance(force_input.get("source"), str) or not force_input["source"].strip():
        raise ValueError("harmonic force_input source must be non-empty")
    return force_constants


def _validate_source_binding(
    source_binding: Mapping[str, Any],
    *,
    harmonic_path: Path,
    plan_path: Path,
    manifest: Mapping[str, Any],
    harmonic: Mapping[str, Any],
    method_identity: Mapping[str, Any],
    parent_binding: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_mode = _non_empty_string(source_binding.get("source_mode"), "source_binding.source_mode")
    if source_mode not in {"native_source_bound", "software_math_only"}:
        raise ValueError("source_binding.source_mode must be native_source_bound or software_math_only")
    declared_harmonic = _absolute_existing_path(
        source_binding.get("harmonic_result_path"),
        "source_binding.harmonic_result_path",
        directory=False,
    )
    declared_plan = _absolute_existing_path(
        source_binding.get("plan_manifest_path"),
        "source_binding.plan_manifest_path",
        directory=False,
    )
    if declared_harmonic != harmonic_path or declared_plan != plan_path:
        raise ValueError("source binding does not identify the requested harmonic result and plan")
    force_bundle_path = _absolute_existing_path(
        source_binding.get("force_bundle_path"),
        "source_binding.force_bundle_path",
        directory=False,
    )
    force_bundle = _load_json_object(force_bundle_path, "source_binding.force_bundle_path")
    _force_records(manifest, force_bundle)
    force_input = harmonic["force_input"]
    expected_entry_ids = [str(entry["entry_id"]) for entry in manifest["displacements"]]
    records = force_bundle.get("records")
    if not isinstance(records, list):
        raise ValueError("force bundle records must be a list")
    by_id = {str(record["entry_id"]): record for record in records}
    actual_refs = [str(by_id[entry_id]["source_ref"]) for entry_id in expected_entry_ids]
    if force_input.get("source") != force_bundle.get("source"):
        raise ValueError("force bundle source differs from harmonic force_input source")
    if force_input.get("source_refs") != actual_refs:
        raise ValueError("force bundle source_refs differ from harmonic force_input")
    task_records: list[str] = []
    native_refs: list[str] = []
    native_method_files: list[str] = []
    method_sources: list[dict[str, Any]] = []
    # Legacy P7 collections have no explicit parent reference.  Keep this
    # sentinel defined for the later parent-vs-child identity branch.
    reference_task_path: Path | None = None
    if source_mode == "native_source_bound":
        bound_model_id = _non_empty_string(source_binding.get("parent_model_id"), "source_binding.parent_model_id")
        bound_model_version = _non_empty_string(
            source_binding.get("parent_model_version"), "source_binding.parent_model_version"
        )
        bound_study_id = _non_empty_string(source_binding.get("parent_study_id"), "source_binding.parent_study_id")
        if (
            bound_model_id != parent_binding.get("model_id")
            or bound_model_version != parent_binding.get("model_version")
            or bound_study_id != parent_binding.get("study_id")
        ):
            raise ValueError("native source binding differs from the validated parent Study/model")
        collection_path = _absolute_existing_path(
            source_binding.get("collection_path"),
            "source_binding.collection_path",
            directory=False,
        )
        collection = _load_json_object(collection_path, "source_binding.collection_path")
        if collection.get("schema") != "mlcc.phonon-force-collection.v001":
            raise ValueError("native source binding requires a phonon force collection")
        collection_plan = _absolute_existing_path(collection.get("plan_path"), "collection.plan_path", directory=False)
        if (
            collection_plan != plan_path
            or collection.get("plan_id") != manifest.get("plan_id")
            or collection.get("plan_version") != manifest.get("version")
        ):
            raise ValueError("native force collection is not bound to the requested plan")
        collection_study = collection.get("parent_study_file")
        declared_study = source_binding.get("parent_study_file")
        if not isinstance(collection_study, str) or not isinstance(declared_study, str):
            raise ValueError("native source binding requires parent study file paths")
        collection_study_path = _absolute_existing_path(collection_study, "collection.parent_study_file", directory=False)
        declared_study_path = _absolute_existing_path(declared_study, "source_binding.parent_study_file", directory=False)
        if collection_study_path != declared_study_path:
            raise ValueError("native force collection parent study file differs from the explicit binding")
        if declared_study_path != Path(str(parent_binding["study_path"])).resolve():
            raise ValueError("native source binding study file differs from the validated parent Study")
        if (
            collection.get("parent_model_id") != bound_model_id
            or collection.get("parent_model_version") != bound_model_version
            or collection.get("parent_study_id") != bound_study_id
        ):
            raise ValueError("native force collection parent identity is not explicitly bound")
        if collection.get("ready_for_harmonic") is not True or collection.get("force_bundle") is None:
            raise ValueError("native force collection is not ready_for_harmonic")
        expected_all_ids = ["reference", *expected_entry_ids]
        if collection.get("expected_displacement_ids") != expected_all_ids:
            raise ValueError("native force collection expected_displacement_ids differ from the plan")
        collected_ids = collection.get("collected_displacement_ids")
        if (
            not isinstance(collected_ids, list)
            or len(collected_ids) != len(expected_all_ids)
            or set(str(value) for value in collected_ids) != set(expected_all_ids)
        ):
            raise ValueError("native force collection does not contain the complete reference/displacement set")
        collection_checks = collection.get("checks")
        required_checks = (
            "scheduler_completed_0",
            "p7_stage",
            "electronic_converged",
            "source_identity",
            "parent_study_binding",
            "child_model_binding",
            "child_study_binding",
            "method_input_qualification",
            "same_method_physics",
            "same_native_input_physics",
            "native_input_contract",
            "native_result_force_match",
            "native_result_consistency",
            "native_source_evidence",
        )
        explicit_reference_record = collection.get("reference_task_record")
        explicit_reference_mode = (
            collection.get("reference_binding_mode") == "explicit_parent_reference"
            or explicit_reference_record is not None
        )
        if explicit_reference_mode:
            required_checks = (*required_checks, "reference_binding")
        if not isinstance(collection_checks, Mapping) or any(
            not isinstance(collection_checks.get(name), Mapping)
            or collection_checks[name].get("passed") is not True
            for name in required_checks
        ):
            raise ValueError("native force collection lacks the required passed source/method checks")
        collection_force_bundle = collection.get("force_bundle")
        if not isinstance(collection_force_bundle, Mapping):
            raise ValueError("native force collection requires force_bundle")
        _force_records(manifest, collection_force_bundle)

        def record_map(bundle: Mapping[str, Any], name: str) -> dict[str, Mapping[str, Any]]:
            raw_records = bundle.get("records")
            if not isinstance(raw_records, list):
                raise ValueError(f"{name}.records must be a list")
            mapped: dict[str, Mapping[str, Any]] = {}
            for record in raw_records:
                if not isinstance(record, Mapping):
                    raise ValueError(f"{name}.records entries must be objects")
                entry_id = _non_empty_string(record.get("entry_id"), f"{name}.records.entry_id")
                if entry_id in mapped:
                    raise ValueError(f"{name}.records contains duplicate entry_id {entry_id!r}")
                mapped[entry_id] = record
            return mapped

        collection_record_map = record_map(collection_force_bundle, "native collection force_bundle")
        force_record_map = record_map(force_bundle, "source force_bundle")
        expected_force_ids = set(expected_entry_ids)
        if set(collection_record_map) != expected_force_ids or set(force_record_map) != expected_force_ids:
            raise ValueError("native force bundles must contain every non-reference displacement exactly once")
        if collection_force_bundle.get("source") != force_bundle.get("source"):
            raise ValueError("native collection force_bundle source differs from the requested force bundle")
        for entry_id in expected_entry_ids:
            collection_record = collection_record_map[entry_id]
            force_record = force_record_map[entry_id]
            if str(collection_record.get("source_ref")) != str(force_record.get("source_ref")):
                raise ValueError(f"native force source_ref differs for displacement {entry_id}")
            if collection_record.get("atom_ids") != force_record.get("atom_ids"):
                raise ValueError(f"native force atom_ids differ for displacement {entry_id}")
            collection_forces = np.asarray(collection_record.get("forces"), dtype=float)
            force_forces = np.asarray(force_record.get("forces"), dtype=float)
            if collection_forces.shape != force_forces.shape or not np.array_equal(collection_forces, force_forces):
                raise ValueError(f"native force arrays differ for displacement {entry_id}")
        collection_refs = [str(collection_record_map[entry_id]["source_ref"]) for entry_id in expected_entry_ids]
        if collection_refs != actual_refs:
            raise ValueError("native collection source_refs differ from the requested force bundle")
        if any(not Path(reference).is_absolute() or not Path(reference).is_file() for reference in collection_refs):
            raise ValueError("native collection source_refs must resolve to existing native source files")

        selected_task_records, has_saved_collection_order = _select_native_task_records(
            collection, source_binding
        )
        if explicit_reference_mode:
            if explicit_reference_record is None:
                raise ValueError("explicit parent reference collection requires reference_task_record")
            reference_task_path = _canonical_task_record(
                explicit_reference_record,
                "collection.reference_task_record",
                allow_directory=True,
            )
            if not selected_task_records or selected_task_records[0] != reference_task_path:
                raise ValueError(
                    "explicit parent reference must be the first saved native_task_records entry"
                )
            if source_binding.get("reference_task_record") is not None:
                declared_reference = _canonical_task_record(
                    source_binding["reference_task_record"],
                    "source_binding.reference_task_record",
                    allow_directory=True,
                )
                if declared_reference != reference_task_path:
                    raise ValueError(
                        "source_binding.reference_task_record differs from the saved parent reference"
                    )
        task_method_sets: set[str] = set()
        task_method_physics: list[dict[str, Any]] = []
        displacement_ids: set[str] = set()
        task_ids: set[str] = set()
        ordered_displacement_ids: list[str] = []
        native_log_by_displacement: dict[str, Path] = {}
        collection_source_tasks = collection_checks["native_source_evidence"].get("tasks")
        if not isinstance(collection_source_tasks, Mapping):
            raise ValueError("native force collection source evidence must contain task records")
        for task_record in selected_task_records:
            task_path = task_record
            task_directory = task_path if task_path.is_dir() else task_path.parent
            task_file = task_directory / "task.json"
            if not task_file.is_file():
                raise ValueError("native task record path must resolve to a task directory or task.json")
            loaded = load_native_force_task(task_directory)
            task_data = loaded["task"]
            task_id = _non_empty_string(task_data.get("task_id"), "native task task_id")
            if task_id in task_ids:
                raise ValueError(f"native task records contain duplicate task_id {task_id!r}")
            task_ids.add(task_id)
            is_parent_reference = reference_task_path is not None and task_file.resolve() == reference_task_path
            if is_parent_reference:
                if task_data.get("stage") != "P4":
                    raise ValueError("explicit parent reference native task must be a P4 task")
                if task_data.get("phonon_displacement") is not None:
                    raise ValueError("explicit parent reference must not carry phonon_displacement")
                if (
                    task_data.get("model_id") != bound_model_id
                    or task_data.get("model_version") != bound_model_version
                ):
                    raise ValueError("explicit parent reference model differs from the validated parent model")
                task_study_path = _absolute_existing_path(
                    task_data.get("study_file"), "native parent reference study_file", directory=False
                )
                if (
                    task_data.get("study_id") != bound_study_id
                    or task_study_path != declared_study_path
                ):
                    raise ValueError("explicit parent reference Study differs from the validated parent Study")
                if Path(str(loaded["source_model_path"])).resolve() != Path(
                    str(parent_binding["model_path"])
                ).resolve():
                    raise ValueError("explicit parent reference source model differs from the validated parent model")
                displacement_ids.add("reference")
                ordered_displacement_ids.append("reference")
                task_method_set = _non_empty_string(task_data.get("method_set"), "native parent reference method_set")
                task_method_sets.add(task_method_set)
                task_method_file = task_directory / "method.json"
                if not task_method_file.is_file():
                    raise ValueError("native parent reference method.json is missing")
                native_method_files.append(str(task_method_file.resolve()))
                task_method_physics.append(_method_physics_without_model(loaded["method"]))
                method_source = read_native_gamma_method_source(task_file, expected_method=method_identity)
                if method_source["method_identity"] is None:
                    raise ValueError(
                        f"P4 parent reference physical method source is incomplete: {method_source['missing_fields']}"
                    )
                method_sources.append(method_source)
                source_evidence = loaded.get("source_evidence")
                if (
                    not isinstance(source_evidence, Mapping)
                    or source_evidence.get("reason") != "complete"
                    or source_evidence.get("paths_belong_to_task") is not True
                ):
                    raise ValueError("native parent reference source evidence is incomplete")
                native_log = Path(str(loaded["native_log"])).resolve()
                evidence_paths = source_evidence.get("paths")
                if not isinstance(evidence_paths, list) or native_log not in {
                    Path(str(path)).resolve() for path in evidence_paths
                }:
                    raise ValueError("native parent reference source evidence does not contain its native log")
                collection_evidence = collection_source_tasks.get(task_id)
                if not isinstance(collection_evidence, Mapping):
                    raise ValueError("native collection source evidence lacks the parent reference TaskRecord")
                if collection_evidence.get("reason") != "complete" or collection_evidence.get("paths_belong_to_task") is not True:
                    raise ValueError("native collection source evidence is incomplete for the parent reference")
                collection_evidence_paths = collection_evidence.get("paths")
                if not isinstance(collection_evidence_paths, list) or native_log not in {
                    Path(str(path)).resolve() for path in collection_evidence_paths
                }:
                    raise ValueError("native collection source evidence does not bind the parent reference native log")
                task_records.append(str(task_file.resolve()))
                continue
            if (
                task_data.get("stage") != "P7"
                or task_data.get("scheduler_state") != "COMPLETED"
                or task_data.get("exit_code") != "0:0"
            ):
                raise ValueError("native task record is not a completed P7 task")
            _non_empty_string(task_data.get("model_id"), "native child model_id")
            _non_empty_string(task_data.get("model_version"), "native child model_version")
            _non_empty_string(task_data.get("study_id"), "native child study_id")
            _absolute_existing_path(task_data.get("study_file"), "native child study_file", directory=False)
            identity = task_data.get("phonon_displacement")
            if not isinstance(identity, Mapping):
                raise ValueError("native task record lacks phonon_displacement identity")
            if (
                identity.get("parent_model_id") != bound_model_id
                or identity.get("parent_model_version") != bound_model_version
                or identity.get("parent_study_id") != bound_study_id
            ):
                raise ValueError("native task parent identity differs from the validated parent")
            identity_parent_study = _absolute_existing_path(identity.get("parent_study_file"), "native parent_study_file", directory=False)
            if identity_parent_study != declared_study_path:
                raise ValueError("native task parent_study_file differs from the validated parent Study")
            task_manifest = _absolute_existing_path(identity.get("manifest_path"), "native task manifest_path", directory=False)
            if task_manifest != plan_path:
                raise ValueError("native task record manifest differs from the requested plan")
            displacement_id = _non_empty_string(identity.get("displacement_id"), "native task displacement_id")
            if displacement_id not in set(expected_all_ids):
                raise ValueError("native task record displacement is not in the requested plan")
            if displacement_id in displacement_ids:
                raise ValueError(f"native task records contain duplicate displacement_id {displacement_id!r}")
            displacement_ids.add(displacement_id)
            ordered_displacement_ids.append(displacement_id)
            task_method_set = _non_empty_string(task_data.get("method_set"), "native task method_set")
            task_method_sets.add(task_method_set)
            task_method_files = task_directory / "method.json"
            if not task_method_files.is_file():
                raise ValueError("native task method.json is missing")
            native_method_files.append(str(task_method_files.resolve()))
            task_method_physics.append(_method_physics_without_model(loaded["method"]))
            method_source = read_native_gamma_method_source(task_file, expected_method=method_identity)
            if method_source["method_identity"] is None:
                raise ValueError(f"P7 physical method source is incomplete: {method_source['missing_fields']}")
            method_sources.append(method_source)
            source_evidence = loaded.get("source_evidence")
            if (
                not isinstance(source_evidence, Mapping)
                or source_evidence.get("reason") != "complete"
                or source_evidence.get("paths_belong_to_task") is not True
            ):
                raise ValueError("native task source evidence is incomplete")
            native_log = Path(str(loaded["native_log"])).resolve()
            evidence_paths = source_evidence.get("paths")
            if not isinstance(evidence_paths, list) or native_log not in {
                Path(str(path)).resolve() for path in evidence_paths
            }:
                raise ValueError("native task source evidence does not contain its native log")
            collection_evidence = collection_source_tasks.get(task_id)
            if not isinstance(collection_evidence, Mapping):
                raise ValueError("native collection source evidence lacks a submitted TaskRecord")
            if collection_evidence.get("reason") != "complete" or collection_evidence.get("paths_belong_to_task") is not True:
                raise ValueError("native collection source evidence is incomplete for a TaskRecord")
            collection_evidence_paths = collection_evidence.get("paths")
            if not isinstance(collection_evidence_paths, list) or native_log not in {
                Path(str(path)).resolve() for path in collection_evidence_paths
            }:
                raise ValueError("native collection source evidence does not bind the TaskRecord native log")
            native_log_by_displacement[displacement_id] = native_log
            task_records.append(str(task_file.resolve()))
        if set(str(value) for value in collection_source_tasks) != task_ids:
            raise ValueError("native collection source evidence contains a different TaskRecord set")
        if (
            displacement_ids != set(expected_all_ids)
            or len(task_method_sets) != 1
            or (has_saved_collection_order and ordered_displacement_ids != expected_all_ids)
        ):
            if has_saved_collection_order and ordered_displacement_ids != expected_all_ids:
                raise ValueError(
                    "native collection native_task_records must follow reference-first manifest order"
                )
            raise ValueError("native task records do not cover one common method-bound reference/displacement set")
        if len(task_method_physics) != len(selected_task_records) or any(
            physics != task_method_physics[0] for physics in task_method_physics[1:]
        ):
            raise ValueError("native task method physics differ across the force collection")
        for entry_id in expected_entry_ids:
            native_log = native_log_by_displacement[entry_id]
            collection_ref = Path(str(collection_record_map[entry_id]["source_ref"])).resolve()
            force_ref = Path(str(force_record_map[entry_id]["source_ref"])).resolve()
            if native_log != collection_ref or native_log != force_ref:
                raise ValueError(f"native source log is not bound to force entry {entry_id}")
        native_refs = [str(native_log_by_displacement[entry_id]) for entry_id in expected_entry_ids]
        collection_path_value = str(collection_path)
    elif source_binding.get("native_task_records") not in (None, []):
        raise ValueError("software_math_only cannot carry native_task_records")
    else:
        collection_path_value = None
    bound_source = {
        "source_mode": source_mode,
        "harmonic_result": str(harmonic_path),
        "plan_manifest": str(plan_path),
        "force_bundle": str(force_bundle_path),
        "native_task_records": task_records,
        "reference_task_record": (
            str(reference_task_path) if reference_task_path is not None else None
        ),
        "collection": collection_path_value,
    }
    if native_refs:
        bound_source["native_refs"] = native_refs
        bound_source["native_method_files"] = native_method_files
        bound_source["native_method_sources"] = method_sources
    return bound_source, force_bundle


def _validate_primitive_parent(
    phonon: Any,
    source_parent: Any,
    *,
    geometry_tolerance_angstrom: float,
    volume_tolerance_A3: float,
    mass_tolerance_amu: float,
) -> tuple[list[int], np.ndarray, float]:
    parent_atoms = source_parent.atoms
    primitive = phonon.primitive
    primitive_cell = np.asarray(primitive.cell, dtype=float)
    parent_cell = np.asarray(parent_atoms.cell.array, dtype=float)
    if primitive_cell.shape != (3, 3) or not np.allclose(
        primitive_cell, parent_cell, rtol=0.0, atol=geometry_tolerance_angstrom
    ):
        raise ValueError("Phonopy primitive cell differs from the parent cell")
    if len(primitive) != len(parent_atoms):
        raise ValueError("Phonopy primitive atom count differs from the parent atom set")
    primitive_symbols = [str(value) for value in primitive.symbols]
    parent_symbols = [str(value) for value in parent_atoms.get_chemical_symbols()]
    if primitive_symbols != parent_symbols:
        raise ValueError("Phonopy primitive element order differs from the parent atom order")
    if not np.allclose(
        np.asarray(primitive.positions, dtype=float),
        np.asarray(parent_atoms.positions, dtype=float),
        rtol=0.0,
        atol=geometry_tolerance_angstrom,
    ):
        raise ValueError("Phonopy primitive positions differ from the parent atom positions")
    if not np.allclose(
        np.asarray(primitive.masses, dtype=float),
        np.asarray(parent_atoms.get_masses(), dtype=float),
        rtol=0.0,
        atol=mass_tolerance_amu,
    ):
        raise ValueError("Phonopy primitive masses differ from the parent atom masses")
    volume = abs(float(np.linalg.det(parent_cell)))
    primitive_volume = abs(float(np.linalg.det(primitive_cell)))
    if not np.isclose(primitive_volume, volume, rtol=0.0, atol=volume_tolerance_A3):
        raise ValueError("Phonopy primitive volume differs from the parent cell volume")
    return source_parent.atom_ids, np.asarray(primitive.masses, dtype=float), volume


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def compute_gamma_fixed_cell_hessian(
    harmonic_result_path: str | Path,
    plan_path: str | Path,
    *,
    parent: Mapping[str, Any],
    method_identity: Mapping[str, Any],
    source_binding: Mapping[str, Any],
    geometry_tolerance_angstrom: float,
    volume_tolerance_A3: float,
    mass_tolerance_amu: float,
    dynamical_imag_tolerance: float,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Convert an existing harmonic Phonopy result to a parent-order Gamma Hessian.

    The force constants are read from ``harmonic_result_path`` and assigned to a
    Phonopy object rebuilt from ``plan_path``.  Only the Gamma dynamical matrix is
    evaluated.  No force-constant fitting, ASR correction, NAC, displacement
    generation, or native-task submission occurs here.
    """

    harmonic_file = _absolute_existing_path(harmonic_result_path, "harmonic_result_path", directory=False)
    plan_file = _absolute_existing_path(plan_path, "plan_path", directory=False)
    geometry_tolerance_angstrom = _positive_or_zero(
        geometry_tolerance_angstrom, "geometry_tolerance_angstrom"
    )
    volume_tolerance_A3 = _positive_or_zero(volume_tolerance_A3, "volume_tolerance_A3")
    mass_tolerance_amu = _positive_or_zero(mass_tolerance_amu, "mass_tolerance_amu")
    dynamical_imag_tolerance = _positive_or_zero(
        dynamical_imag_tolerance, "dynamical_imag_tolerance"
    )
    method = dict(_required_mapping(method_identity, "method_identity"))
    manifest = load_phonon_displacement_plan(plan_file)
    harmonic = _load_json_object(harmonic_file, "harmonic_result_path")
    force_constants = _validate_harmonic_result(harmonic_file, plan_file, harmonic, manifest)
    bound_parent, source_parent = _validate_parent_binding(parent, manifest)
    bound_source, _force_bundle = _validate_source_binding(
        _required_mapping(source_binding, "source_binding"),
        harmonic_path=harmonic_file,
        plan_path=plan_file,
        manifest=manifest,
        harmonic=harmonic,
        method_identity=method,
        parent_binding=bound_parent,
    )
    if bound_source["source_mode"] == "native_source_bound":
        method = bound_source["native_method_sources"][0]["method_record"]
    if manifest["request"].get("hermitianize_dynamical_matrix") is not False:
        raise ValueError("Gamma Hessian adaptation requires hermitianize_dynamical_matrix=false")
    phonon = _rebuild_phonopy_from_plan(plan_file, manifest)
    parent_atom_ids, primitive_masses, volume = _validate_primitive_parent(
        phonon,
        source_parent,
        geometry_tolerance_angstrom=geometry_tolerance_angstrom,
        volume_tolerance_A3=volume_tolerance_A3,
        mass_tolerance_amu=mass_tolerance_amu,
    )
    expected_supercell_atoms = len(phonon.supercell)
    if force_constants.shape != (expected_supercell_atoms, expected_supercell_atoms, 3, 3):
        raise ValueError(
            "harmonic force_constants shape does not match the reconstructed Phonopy supercell"
        )
    phonon.force_constants = force_constants
    qpoints = phonon.run_qpoints(
        [[0.0, 0.0, 0.0]],
        with_eigenvectors=False,
        with_dynamical_matrices=True,
        nac_q_direction=None,
    )
    dynamical = np.asarray(qpoints.dynamical_matrices[0])
    expected_hessian_size = 3 * len(parent_atom_ids)
    if dynamical.shape != (expected_hessian_size, expected_hessian_size):
        raise ValueError("Gamma dynamical matrix shape does not match the parent atom set")
    if not np.all(np.isfinite(dynamical.real)) or not np.all(np.isfinite(dynamical.imag)):
        raise ValueError("Gamma dynamical matrix must contain finite values")
    max_imaginary = float(np.max(np.abs(dynamical.imag)))
    if max_imaginary > dynamical_imag_tolerance:
        raise ValueError(
            "Gamma dynamical matrix imaginary residual exceeds the explicit tolerance: "
            f"{max_imaginary} > {dynamical_imag_tolerance}"
        )
    masses_dof = np.repeat(primitive_masses, 3)
    mass_scale = np.sqrt(np.outer(masses_dof, masses_dof))
    hessian = np.asarray(dynamical.real * mass_scale, dtype=float)
    if not np.all(np.isfinite(hessian)):
        raise ValueError("Gamma Hessian must contain finite values")
    scientific_qualification = False
    production_qualification = False
    output: dict[str, Any] = {
        "schema": GAMMA_HESSIAN_SCHEMA,
        "scientific_status": "native_source_bound_unqualified" if bound_source["source_mode"] == "native_source_bound" else "software_math_only_unqualified",
        "scientific_qualification": scientific_qualification,
        "production_qualified": production_qualification,
        "parent": bound_parent,
        "atom_ids": [int(value) for value in parent_atom_ids],
        "elements": [str(value) for value in source_parent.atoms.get_chemical_symbols()],
        "cell_angstrom": np.asarray(source_parent.atoms.cell.array, dtype=float).tolist(),
        "volume_A3": volume,
        "matrix_basis": "parent_atom_major_cartesian",
        "unit": FORCE_CONSTANT_UNIT,
        "matrix_unit": FORCE_CONSTANT_UNIT,
        "matrix_eV_per_A2": hessian.tolist(),
        "method_identity": method,
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "q_point": [0.0, 0.0, 0.0],
        "dynamical_matrix_unit": "eV/angstrom^2/amu",
        "mass_mapping": {
            "basis": "parent_atom_order",
            "masses_amu": primitive_masses.tolist(),
            "formula": "K[(kappa,beta),(lambda,gamma)] = D * sqrt(m_kappa*m_lambda)",
        },
        "source": {
            **bound_source,
            "harmonic_schema": HARMONIC_SCHEMA,
            "harmonic_force_constants_basis": harmonic["force_constants_basis"],
            "harmonic_force_constants_unit": harmonic["force_constants_unit"],
            "harmonic_scientific_status": harmonic.get("scientific_status"),
            "harmonic_scientific_qualification": harmonic.get("scientific_qualification"),
            "harmonic_production_qualified": harmonic.get("production_qualified"),
        },
        "tolerances": {
            "geometry_angstrom": geometry_tolerance_angstrom,
            "volume_A3": volume_tolerance_A3,
            "mass_amu": mass_tolerance_amu,
            "dynamical_imaginary": dynamical_imag_tolerance,
            "observed_dynamical_imaginary": max_imaginary,
        },
        "qualification": {
            "source_mode": bound_source["source_mode"],
            "scientific": scientific_qualification,
            "production": production_qualification,
            "reason": "Gamma Hessian adaptation is software-only until independent native and scientific contracts pass",
        },
    }
    if output_path is not None:
        _write_json(Path(output_path), output)
    return output


__all__ = ["GAMMA_HESSIAN_SCHEMA", "compute_gamma_fixed_cell_hessian", "read_native_gamma_method_source"]
