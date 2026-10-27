"""Read-only task continuation decisions and provenance checks.

This module describes the next action for one saved task.  It never invokes a
runner, writes a task record, or submits a scheduler job.  Scientific parsing
and result production remain the responsibility of the domain caller.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .tasks import TaskRecord, load_task


_TERMINAL_STATES = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "BOOT_FAIL",
    "DEADLINE",
    "PREEMPTED",
    "REVOKED",
}
_FAILED_STATES = _TERMINAL_STATES - {"COMPLETED"}
_CONVERGED_STATUSES = {"converged", "converged_engineering_fixture"}
_LAMMPS_ENGINEERING_STATUSES = {
    "evaluated_engineering_fixture",
    "executed_engineering_fixture",
}
_LAMMPS_NATIVE_SOURCES = ("log.lammps", "dump.final")
_LAMMPS_NEB_TASK_SCHEMA = "mlcc.lammps-neb-task.v1"
_LAMMPS_NEB_RESULT_SCHEMA = "mlcc.lammps-neb-result.v1"
_LAMMPS_NEB_NATIVE_SOURCES = (
    "method.json",
    "atom-map.json",
    "in.lammps",
    "log.lammps",
    "image_atom_maps",
    "image_data",
    "image_logs",
    "image_dumps",
    "endpoint_dumps",
)
_LAMMPS_NEB_SCALAR_SOURCES = {"method.json", "atom-map.json", "in.lammps", "log.lammps"}
_LAMMPS_NEB_LIST_SOURCES = {
    "image_atom_maps",
    "image_data",
    "image_logs",
    "image_dumps",
}
_BERRY_RESULT_SCHEMA = "mlcc.abacus-polarization.v1"
_BERRY_SCIENTIFIC_STATUS = "evaluated_polarization_unqualified"
_BERRY_NATIVE_SOURCES = ("running_nscf.log", "INPUT", "KPT", "STRU")


def _is_berry_nscf_task(task: TaskRecord) -> bool:
    data = task.data
    berry = data.get("berry")
    return (
        data.get("engine") == "abacus"
        and data.get("stage") == "P5"
        and data.get("calculation") == "nscf"
        and isinstance(berry, Mapping)
        and berry.get("role") == "nscf"
    )


def _berry_reference_task_id(task: TaskRecord) -> Any:
    berry = task.data.get("berry")
    if not isinstance(berry, Mapping):
        return None
    return berry.get("source_reference_task_id")


def _is_berry_result_contract(result: Mapping[str, Any]) -> bool:
    return (
        result.get("schema") == _BERRY_RESULT_SCHEMA
        and result.get("engine") == "abacus"
        and result.get("stage") == "nscf"
        and result.get("scientific_status") == _BERRY_SCIENTIFIC_STATUS
        and result.get("branch_status") == "not_unwrapped"
        and result.get("scientific_qualification") is False
        and result.get("numerical_qualification") is False
        and result.get("production_qualification") is False
        and result.get("production_label") is False
    )


def _berry_source_paths(
    result: Mapping[str, Any],
    result_path: Path,
) -> tuple[list[Path], list[Path]]:
    source_files = result.get("source_files")
    if not isinstance(source_files, Mapping):
        expected = [result_path.parent / name for name in _BERRY_NATIVE_SOURCES]
        return expected, expected
    paths = _source_artifacts(result, result_path)
    missing = [
        result_path.parent / name
        for name in _BERRY_NATIVE_SOURCES
        if name not in source_files
    ]
    wrong_names: list[Path] = []
    for name in _BERRY_NATIVE_SOURCES:
        if name not in source_files:
            continue
        path = Path(source_files[name])
        if not path.is_absolute():
            path = result_path.parent / path
        if path.name != name:
            wrong_names.append(path)
    return paths, [*missing, *wrong_names]


def _lammps_native_sources(result: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the native files required by the result's explicit protocol."""

    protocol = result.get("protocol")
    if isinstance(protocol, Mapping) and protocol.get("kind") == "md":
        sources = (*_LAMMPS_NATIVE_SOURCES, "trajectory.lammpstrj")
        if protocol.get("purpose") in {"md_bulk_thermal", "bulk_thermal_transport"}:
            sources = (*sources, "in.lammps", "method.json", "atom-map.json", "model.data")
            if protocol.get("purpose") == "bulk_thermal_transport":
                sources = (*sources, "thermal-energy.dat", "thermal-profile.dat")
            potential = result.get("potential")
            files = potential.get("files") if isinstance(potential, Mapping) else None
            if isinstance(files, list):
                sources = (*sources, *tuple(
                    item["filename"] for item in files
                    if isinstance(item, Mapping)
                    and isinstance(item.get("filename"), str)
                    and item["filename"]
                ))
            return sources
        if protocol.get("purpose") == "md_native_sampling":
            # The native finite-temperature sampling route keeps the ordinary
            # MD outputs and adds its explicit sidecars.  The unwrapped dump
            # is conditional on the protocol switch, matching md_unwrapped's
            # writer contract.
            sources = (
                *sources,
                "in.lammps",
                "sampling.lammpstrj",
                "pressure-series.dat",
            )
            if protocol.get("unwrapped_trajectory") is True:
                sources = (*sources, "trajectory.unwrapped.lammpstrj")
        return sources
    return _LAMMPS_NATIVE_SOURCES


def _result_path(task: TaskRecord) -> Path | None:
    value = task.data.get("result_file")
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute() and task.path is not None:
        path = task.path.parent / path
    return path


def _source_artifacts(result: Mapping[str, Any], result_path: Path) -> list[Path]:
    paths: list[Path] = []
    source_files = result.get("source_files")
    if isinstance(source_files, dict):
        for value in source_files.values():
            path = Path(value)
            paths.append(path if path.is_absolute() else result_path.parent / path)
    source_artifact = result.get("source_artifact")
    if source_artifact is not None:
        path = Path(source_artifact)
        paths.append(path if path.is_absolute() else result_path.parent / path)
    return paths


def _lammps_potential_identity(value: Any) -> dict[str, Any] | None:
    """Normalize staged LAMMPS potential paths while preserving identity.

    ``create_lammps_task`` stages each potential file into the native task
    directory. Consequently the parsed result has a task-local
    ``files[*].local_path`` whereas the task record retains the selected
    source path. The file names and all other potential metadata remain the
    binding contract.
    """

    if not isinstance(value, Mapping) or not isinstance(value.get("files"), list):
        return None
    files: list[dict[str, Any]] = []
    for item in value["files"]:
        if not isinstance(item, Mapping):
            return None
        files.append({key: item_value for key, item_value in item.items() if key != "local_path"})
    identity = dict(value)
    identity["files"] = files
    return identity


def _bulk_thermal_series_shape_is_valid(value: Any) -> bool:
    """Check the saved bulk-series marker without re-parsing native output."""

    if not isinstance(value, Mapping) or value.get("schema") != "mlcc.md-bulk-thermal-source.v1":
        return False
    frames = value.get("frames")
    return isinstance(frames, list) and bool(frames)


def _is_parsed_result_json(path: Path) -> bool:
    """Identify a parsed result JSON that cannot serve as native evidence."""

    if path.name == "result.json":
        return True
    if path.suffix.lower() != ".json":
        return False
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    return isinstance(value, dict) and "task_id" in value and "scientific_status" in value


def source_evidence(
    result: Mapping[str, Any],
    result_path: Path,
    *,
    engine: str | None = None,
) -> tuple[list[Path], list[Path], str]:
    """Resolve native source links and apply the current engine source contract.

    The helper is shared by continuation and delivery.  It checks actual files,
    rejects result JSON as evidence, and requires an engine-native output for
    ABACUS or VASP.  ABACUS Berry NSCF is accepted only through its explicit
    polarization schema and four-file native source contract.  Other engines
    retain the generic existing-file check.
    """

    if engine == "lammps":
        required_sources = _lammps_native_sources(result)
        source_files = result.get("source_files")
        if not isinstance(source_files, Mapping):
            expected = [result_path.parent / name for name in required_sources]
            return expected, expected, "missing_lammps_native_outputs"
        missing = [name for name in required_sources if name not in source_files]
        if missing:
            missing_paths = [result_path.parent / name for name in missing]
            return _source_artifacts(result, result_path) + missing_paths, missing_paths, "missing_lammps_native_outputs"
        wrong_names: list[Path] = []
        for name in required_sources:
            path = Path(source_files[name])
            if path.name != name:
                wrong_names.append(path)
        if wrong_names:
            return _source_artifacts(result, result_path), wrong_names, "lammps_native_source_name_mismatch"

    if engine == "abacus" and result.get("stage") == "nscf":
        source_files = result.get("source_files")
        paths, contract_invalid = _berry_source_paths(result, result_path)
        if not _is_berry_result_contract(result):
            return paths, contract_invalid or paths, "unsupported_abacus_nscf_source"
        if contract_invalid:
            return paths, contract_invalid, "berry_native_source_contract"

    paths = _source_artifacts(result, result_path)
    if not paths:
        return [], [], "no_source_files"
    result_resolved = result_path.resolve()
    invalid: list[Path] = []
    native = False
    for path in paths:
        if not path.is_file() or path.resolve() == result_resolved or _is_parsed_result_json(path):
            invalid.append(path)
            continue
        if engine == "abacus" and path.name in {"running_scf.log", "running_relax.log"}:
            native = True
        if engine == "abacus" and _is_berry_result_contract(result) and path.name == "running_nscf.log":
            native = True
        if engine == "vasp" and path.name in {"OUTCAR", "vasprun.xml"}:
            native = True
    if invalid:
        if engine == "abacus" and result.get("stage") == "nscf":
            required_paths = {
                (
                    Path(source_files[name])
                    if Path(source_files[name]).is_absolute()
                    else result_path.parent / Path(source_files[name])
                ).resolve()
                for name in _BERRY_NATIVE_SOURCES
                if isinstance(source_files, Mapping) and name in source_files
            }
            if any(path.resolve() in required_paths for path in invalid):
                return paths, invalid, "missing_berry_native_outputs"
        if engine == "lammps":
            required_paths = {
                (Path(source_files[name]) if Path(source_files[name]).is_absolute() else result_path.parent / Path(source_files[name])).resolve()
                for name in _lammps_native_sources(result)
            }
            if any(path.resolve() in required_paths for path in invalid):
                return paths, invalid, "missing_lammps_native_outputs"
        if any(path.is_file() and path.suffix.lower() == ".json" for path in invalid):
            return paths, invalid, "parsed_result_json_source"
        return paths, invalid, "missing_source_files"
    if engine == "abacus" and not native:
        return paths, [], "no_native_scf_or_relax_log"
    if engine == "vasp" and not native:
        return paths, [], "no_native_outcar_or_vasprun"
    return paths, [], "complete"


def _read_result(task: TaskRecord) -> tuple[Path, dict[str, Any]] | None:
    path = _result_path(task)
    if path is None or not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError(f"result file must contain an object: {path}")
    return path, result


def _converged_result(task: TaskRecord) -> tuple[Path, dict[str, Any], list[Path]] | None:
    if task.data.get("engine") == "abacus" and task.data.get("net_charge", 0) != 0:
        return None
    loaded = _read_result(task)
    if loaded is None:
        return None
    path, result = loaded
    if result.get("task_id") != task.task_id:
        return None
    status = result.get("scientific_status")
    if status not in _CONVERGED_STATUSES:
        return None
    sources, _invalid, reason = source_evidence(
        result,
        path,
        engine=task.data.get("engine"),
    )
    if reason != "complete":
        return None
    return path, result, sources


def _lammps_engineering_result(
    task: TaskRecord,
) -> tuple[Path, dict[str, Any], list[Path], str] | None:
    """Validate a completed engineering or candidate-potential evaluation."""

    loaded = _read_result(task)
    if loaded is None:
        return None
    path, result = loaded
    if task.data.get("engine") != "lammps" or result.get("engine") != "lammps":
        return None
    if task.scheduler_job_id is None:
        return None
    if result.get("task_id") != task.task_id:
        return None
    if result.get("scheduler_job_id") != task.scheduler_job_id:
        return None
    if result.get("scheduler_state") != "COMPLETED" or result.get("exit_code") != "0:0":
        return None
    if (
        not isinstance(task.data.get("engine_version"), str)
        or not task.data.get("engine_version")
        or result.get("engine_version") != task.data.get("engine_version")
    ):
        return None
    if (result.get("model_id"), result.get("version")) != (
        task.data.get("model_id"),
        task.data.get("model_version"),
    ):
        return None
    if task.data.get("production_label") is not False or result.get("production_label") is not False:
        return None
    if result.get("production_qualification") is not False:
        return None
    if (
        result.get("study_id") != task.data.get("study_id")
        or result.get("case_id") != task.data.get("case_id")
        or result.get("method_set") != task.data.get("method_set")
    ):
        return None
    protocol = task.data.get("protocol")
    if not isinstance(protocol, Mapping) or result.get("protocol") != protocol:
        return None
    kind = protocol.get("kind")
    if kind != task.data.get("calculation"):
        return None
    ceramic = task.data.get("schema") == "mlcc.ceramic-lammps-task.v1"
    if ceramic:
        potential = task.data.get("potential")
        if (task.data.get("fixture") is not False or result.get("fixture") is not False
                or task.data.get("engineering_only") is not True
                or task.data.get("scientific_qualification") is not False
                or result.get("scientific_qualification") is not False
                or task.data.get("production_qualification") is not False
                or not isinstance(potential, Mapping) or result.get("potential") != potential
                or potential.get("fixture") is not True
                or potential.get("production_qualification") is not False
                or result.get("case_role") != task.data.get("case_role")
                or result.get("parent_model") != task.data.get("parent_model")):
            return None
        for field in ("source_system_id", "source_task_id", "source_scheduler_job_id",
                      "training_task_id", "training_job_id", "collection_path", "model_card_path"):
            if not task.data.get(field) or result.get(field) != task.data[field]:
                return None
        for field in ("training_task_id", "training_job_id"):
            if potential.get(field) != task.data[field]:
                return None
        for field in ("source_method", "source_charge", "source_parent_mapping"):
            if result.get(field) != task.data.get(field):
                return None
    if protocol.get("purpose") == "potential_qualification":
        if (kind != "run0" or protocol.get("static_tensor") is not True
                or not isinstance(protocol.get("experiment_scope"), str)
                or not protocol["experiment_scope"].strip()
                or task.data.get("production_qualification") is not False
                or result.get("fixture") is not task.data.get("fixture")
                or result.get("case_role") != task.data.get("case_role")
                or result.get("parent_model") != task.data.get("parent_model")
                or result.get("tensor_contribution") != "virial_only_zero_velocity"
                or result.get("tensor_basis") != "source_cartesian"
                or result.get("stress_sign") != "tension_positive"
                or result.get("stress_unit") != "GPa"
                or "pressure_tensor_GPa" not in result or "stress_GPa" not in result):
            return None
        expected_status = "evaluated_ceramic_potential_candidate" if ceramic else "evaluated_candidate_potential"
    elif protocol.get("purpose") == "md_bulk_thermal":
        # This remains an ordinary create_lammps_task result. The explicit
        # bulk series is the saved native NPT thermo/cell record; it is not a
        # legacy md_collection and is not parsed here.
        task_potential = task.data.get("potential")
        result_potential = result.get("potential")
        potential_identity_matches = (
            isinstance(task_potential, Mapping)
            and isinstance(result_potential, Mapping)
            and isinstance(task_potential.get("potential_id"), str)
            and bool(task_potential.get("potential_id"))
            and isinstance(task_potential.get("version"), str)
            and bool(task_potential.get("version"))
            and result_potential.get("potential_id") == task_potential.get("potential_id")
            and result_potential.get("version") == task_potential.get("version")
        )
        result_potential_files = result_potential.get("files") if isinstance(result_potential, Mapping) else None
        potential_filenames_valid = (
            isinstance(result_potential_files, list)
            and bool(result_potential_files)
            and all(
                isinstance(item, Mapping)
                and isinstance(item.get("filename"), str)
                and bool(item["filename"])
                for item in result_potential_files
            )
        )
        if (
            kind != "md"
            or protocol.get("ensemble") != "npt"
            or task.data.get("fixture") is not False
            or result.get("fixture") is not False
            or result.get("schema") != "mlcc.lammps-result.v1"
            or result.get("case_role") != task.data.get("case_role")
            or not potential_identity_matches
            or not potential_filenames_valid
            or not isinstance(task_potential, Mapping)
            or not isinstance(task_potential.get("files"), list)
            or not task_potential.get("files")
            or not _bulk_thermal_series_shape_is_valid(result.get("bulk_thermal_series"))
        ):
            return None
        expected_status = "executed_bulk_thermal_protocol"
    elif protocol.get("purpose") == "bulk_thermal_transport":
        # Finite NEMD execution is complete when its raw tables are saved.
        # Steady state, gradient and conductivity are separate consumer results.
        source = result.get("bulk_heat_source")
        task_potential = task.data.get("potential")
        result_potential = result.get("potential")
        if (
            kind != "md"
            or protocol.get("ensemble") != "nve"
            or result.get("schema") != "mlcc.lammps-result.v1"
            or not isinstance(task_potential, Mapping)
            or not isinstance(result_potential, Mapping)
            or result_potential.get("potential_id") != task_potential.get("potential_id")
            or result_potential.get("version") != task_potential.get("version")
            or not isinstance(source, Mapping)
            or source.get("schema") != "mlcc.md-bulk-heat-source.v1"
            or not source.get("energy_rows")
            or not source.get("profile_frames")
            or source.get("missing_evidence")
        ):
            return None
        expected_status = "executed_bulk_heat_protocol"
    elif protocol.get("purpose") == "md_native_sampling":
        # This is an ordinary create_lammps_task result, not the older
        # ceramic-task schema.  Keep the non-fixture model and the finite
        # sampling status explicit; this route must not be promoted to an
        # equilibrium or scientific-convergence result.
        task_potential = task.data.get("potential")
        result_potential = result.get("potential")
        potential_identity_matches = (
            _lammps_potential_identity(task_potential) is not None
            and _lammps_potential_identity(result_potential)
            == _lammps_potential_identity(task_potential)
        )
        if (
            kind != "md"
            or protocol.get("ensemble") != "nvt"
            or task.data.get("fixture") is not False
            or result.get("fixture") is not False
            or result.get("schema") != "mlcc.lammps-result.v1"
            or result.get("case_role") != task.data.get("case_role")
            or not potential_identity_matches
            or not isinstance(task_potential, Mapping)
            or task_potential.get("fixture") is not True
            or task_potential.get("production_qualification") is not False
            or result.get("sampling_equilibrium_qualified") is not False
            or result.get("production_qualification") is not False
        ):
            return None
        expected_status = "engineering_sampling_not_equilibrium_qualification"
    elif ceramic:
        if (kind != "md" or protocol.get("ensemble") != "nve"
                or not isinstance(protocol.get("engineering_scope"), str)
                or not protocol["engineering_scope"].strip()
                or result.get("sampling_equilibrium_qualified") is not False):
            return None
        expected_status = "executed_ceramic_engineering_md"
    else:
        if (task.data.get("fixture") is not True
                or task.data.get("case_role") != "engineering_fixture"
                or result.get("case_role") != "engineering_fixture"):
            return None
        expected_status = {
            "run0": "evaluated_engineering_fixture",
            "md": "executed_engineering_fixture",
        }.get(kind)
        if expected_status not in _LAMMPS_ENGINEERING_STATUSES:
            return None
    if result.get("scientific_status") != expected_status:
        return None
    sources, invalid, reason = source_evidence(result, path, engine="lammps")
    if reason != "complete" or invalid:
        return None
    return path, result, sources, expected_status


def _lammps_neb_source_artifacts(
    result: Mapping[str, Any], result_path: Path
) -> tuple[list[Path], list[Path]] | None:
    """Resolve the saved native artifacts of a parsed LAMMPS NEB result.

    NEB results intentionally use lists for per-image maps, data files, logs,
    and dumps.  This is kept separate from the run0/MD source contract above;
    the continuation planner must not route a saved NEB result through the
    single-dump LAMMPS parser contract.
    """

    source_files = result.get("source_files")
    if not isinstance(source_files, Mapping):
        return None
    protocol = result.get("protocol")
    if not isinstance(protocol, Mapping):
        return None
    images = protocol.get("images")
    if isinstance(images, bool) or not isinstance(images, int) or images < 1:
        return None
    paths: list[Path] = []
    invalid: list[Path] = []
    for name in _LAMMPS_NEB_NATIVE_SOURCES:
        if name not in source_files:
            invalid.append(result_path.parent / name)
            continue
        raw = source_files[name]
        if name in _LAMMPS_NEB_LIST_SOURCES:
            if not isinstance(raw, list) or len(raw) != images:
                invalid.append(result_path.parent / name)
                continue
            values = raw
        elif name == "endpoint_dumps":
            if not isinstance(raw, list) or len(raw) != 2:
                invalid.append(result_path.parent / name)
                continue
            values = raw
        else:
            if not isinstance(raw, str) or not raw.strip():
                invalid.append(result_path.parent / name)
                continue
            values = [raw]
        if not values:
            invalid.append(result_path.parent / name)
            continue
        for value in values:
            if not isinstance(value, str) or not value.strip():
                invalid.append(result_path.parent / name)
                continue
            path = Path(value)
            if not path.is_absolute():
                path = result_path.parent / path
            paths.append(path)
            if name in _LAMMPS_NEB_SCALAR_SOURCES and path.name != name:
                invalid.append(path)
                continue
            if not path.is_file() or path.resolve() == result_path.resolve():
                invalid.append(path)
                continue
            if path.suffix.lower() == ".json":
                if _is_parsed_result_json(path):
                    invalid.append(path)
    return paths, invalid


def _lammps_neb_result(
    task: TaskRecord,
) -> tuple[Path, dict[str, Any], list[Path]] | None:
    """Validate only the saved identity/native-file contract of one NEB result.

    This deliberately does not call the NEB parser or recompute any native
    quantity.  It is a continuation check for results already parsed by the
    domain task module.
    """

    data = task.data
    if (
        data.get("schema") != _LAMMPS_NEB_TASK_SCHEMA
        or data.get("engine") != "lammps"
        or data.get("calculation") != "neb"
    ):
        return None
    loaded = _read_result(task)
    if loaded is None:
        return None
    result_path, result = loaded
    if (
        result.get("schema") != _LAMMPS_NEB_RESULT_SCHEMA
        or result.get("engine") != "lammps"
        or result.get("task_id") != task.task_id
        or task.scheduler_job_id is None
        or result.get("scheduler_job_id") != task.scheduler_job_id
        or result.get("scheduler_state") != "COMPLETED"
        or result.get("exit_code") != "0:0"
    ):
        return None
    for field in ("engine_version", "study_id"):
        task_value = data.get(field)
        if not isinstance(task_value, str) or not task_value.strip() or result.get(field) != task_value:
            return None
    if result.get("case_id") != data.get("case_id"):
        return None

    if (
        result.get("model_id"),
        result.get("version"),
        result.get("model_path"),
    ) != (
        data.get("model_id"),
        data.get("model_version"),
        data.get("model_path"),
    ):
        return None
    model = data.get("model")
    result_model = result.get("model")
    if not isinstance(model, Mapping) or not isinstance(result_model, Mapping):
        return None
    if any(result_model.get(key) != model.get(key) for key in ("model_id", "version", "path")):
        return None
    final_model = data.get("final_model")
    if not isinstance(final_model, Mapping):
        return None
    if (
        result.get("final_model_id"),
        result.get("final_version"),
        result.get("final_model_path"),
    ) != (
        final_model.get("model_id"),
        final_model.get("version"),
        data.get("final_model_path"),
    ):
        return None
    result_final_model = result.get("final_model")
    if not isinstance(result_final_model, Mapping):
        return None
    if any(
        result_final_model.get(key) != final_model.get(key)
        for key in ("model_id", "version", "path")
    ):
        return None

    method = data.get("method")
    protocol = data.get("protocol")
    potential = data.get("potential")
    if (
        not isinstance(method, Mapping)
        or not isinstance(protocol, Mapping)
        or not isinstance(potential, Mapping)
        or result.get("method") != method
        or result.get("method_path") != data.get("method_path")
        or result.get("method_set") != data.get("method_set")
        or result.get("protocol") != protocol
        or result.get("potential") != potential
    ):
        return None

    scientific_status = result.get("scientific_status")
    if not isinstance(scientific_status, str) or not scientific_status.strip():
        return None
    if result.get("production_qualification") is not False:
        return None
    convergence_fields = (
        "regular_native_converged",
        "climbing_native_converged",
        "path_endpoint_converged",
        "native_converged",
    )
    if any(not isinstance(result.get(field), bool) for field in convergence_fields):
        return None
    stopping = result.get("stopping")
    if not isinstance(stopping, Mapping) or not isinstance(stopping.get("phase_converged"), Mapping):
        return None

    artifacts = _lammps_neb_source_artifacts(result, result_path)
    if artifacts is None:
        return None
    sources, invalid = artifacts
    if invalid:
        return None
    return result_path, result, sources


def _berry_engineering_result(
    task: TaskRecord,
) -> tuple[Path, dict[str, Any], list[Path]] | None:
    """Validate one completed Berry NSCF engineering result without qualifying it."""

    if not _is_berry_nscf_task(task):
        return None
    loaded = _read_result(task)
    if loaded is None:
        return None
    path, result = loaded
    if task.scheduler_job_id is None or not _is_berry_result_contract(result):
        return None
    if result.get("task_id") != task.task_id:
        return None
    if result.get("scheduler_job_id") != task.scheduler_job_id:
        return None
    for field in ("model_id", "model_version", "method_set"):
        task_value = task.data.get(field)
        if task_value in (None, "") or result.get(field) != task_value:
            return None
    berry = task.data["berry"]
    task_gdir = berry.get("gdir")
    result_gdir = result.get("gdir")
    if (
        isinstance(task_gdir, bool)
        or isinstance(result_gdir, bool)
        or task_gdir not in (1, 2, 3)
        or result_gdir != task_gdir
    ):
        return None
    reference_values = [
        berry.get("source_reference_task_id"),
        berry.get("reference_task_id"),
        task.data.get("reference_task_id"),
        task.data.get("source_reference_task_id"),
    ]
    reference_values = [value for value in reference_values if value not in (None, "")]
    if reference_values and any(value != reference_values[0] for value in reference_values[1:]):
        return None
    reference_task_id = _berry_reference_task_id(task)
    if not isinstance(reference_task_id, str) or not reference_task_id:
        return None
    if result.get("reference_task_id") != reference_task_id:
        return None
    if result.get("reference_scf_task_id", reference_task_id) != reference_task_id:
        return None
    task_reference = task.data.get("reference_task_id")
    if task_reference not in (None, reference_task_id):
        return None
    sources, invalid, reason = source_evidence(result, path, engine="abacus")
    if reason != "complete" or invalid:
        return None
    return path, result, sources


def _decision(task: TaskRecord, action: str, reason: str, **evidence: Any) -> dict[str, Any]:
    result = {
        "task_id": task.task_id,
        "action": action,
        "reason": reason,
        "scheduler_job_id": task.scheduler_job_id,
        "scheduler_state": task.data.get("scheduler_state"),
        "exit_code": task.data.get("exit_code"),
    }
    result.update(evidence)
    return result


def inspect_task(task: TaskRecord) -> dict[str, Any]:
    """Return exactly one read-only continuation action for ``task``.

    The action is a recommendation only.  In particular, ``submit`` is never
    performed here and an ambiguous submission is sent to manual resolution.
    """

    data = task.data
    job_id = task.scheduler_job_id
    status = str(data.get("status", "")).upper()
    scheduler_state = data.get("scheduler_state")
    if scheduler_state is not None:
        scheduler_state = str(scheduler_state).upper()
    submission_started = data.get("submission_attempt_started_at")
    submission_state = str(data.get("submission_state", "")).lower()

    if job_id is None and (
        data.get("submitted_unknown")
        or submission_started is not None
        or submission_state in {"attempting", "unknown"}
        or status in {"SUBMITTING", "SUBMITTED_UNKNOWN"}
    ):
        return _decision(
            task,
            "resolve_submission_unknown",
            "a submission attempt is recorded without a native Slurm job ID; resolve the original submission before any submit",
        )

    if job_id is not None and scheduler_state not in _TERMINAL_STATES:
        return _decision(
            task,
            "query",
            "a scheduler job exists without a saved terminal state; query the native scheduler",
        )

    if scheduler_state in _FAILED_STATES or status in {
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "OUT_OF_MEMORY",
        "NODE_FAIL",
        "BOOT_FAIL",
        "DEADLINE",
        "PREEMPTED",
        "REVOKED",
    }:
        return _decision(
            task,
            "review_original_error",
            "the saved scheduler/task state is failed, cancelled, or timed out; preserve and review the original error",
        )

    if scheduler_state == "COMPLETED":
        if data.get("exit_code") != "0:0":
            return _decision(
                task,
                "review_original_error",
                "the scheduler reached COMPLETED without the required native exit code 0:0",
            )
        if data.get("engine") == "lammps":
            if data.get("schema") == _LAMMPS_NEB_TASK_SCHEMA:
                engineering = _lammps_neb_result(task)
                if engineering is not None:
                    path, parsed, sources = engineering
                    return _decision(
                        task,
                        "completed",
                        "the saved native LAMMPS NEB result completed with exit 0 and its task, model, method, "
                        "protocol, potential, and per-image native artifacts are bound; scientific status and "
                        "phase convergence are returned without being upgraded",
                        result_file=str(path),
                        scientific_status=parsed["scientific_status"],
                        regular_native_converged=parsed["regular_native_converged"],
                        climbing_native_converged=parsed["climbing_native_converged"],
                        path_endpoint_converged=parsed["path_endpoint_converged"],
                        native_converged=parsed["native_converged"],
                        phase_converged=parsed["stopping"]["phase_converged"],
                        production_qualification=parsed["production_qualification"],
                        source_artifacts=[str(source) for source in sources],
                    )
                loaded = _read_result(task)
                if loaded is not None:
                    return _decision(
                        task,
                        "review_original_error",
                        "the saved LAMMPS NEB result exists but its task/job/model/final-model/method/protocol/"
                        "potential binding or required per-image native artifacts are incomplete",
                        result_file=str(loaded[0]),
                        scientific_status=loaded[1].get("scientific_status"),
                    )
                if data.get("collect_status") != "collected":
                    return _decision(
                        task,
                        "collect",
                        "the native LAMMPS NEB job completed with exit 0 but its selected outputs are not recorded as collected",
                    )
                return _decision(
                    task,
                    "parse",
                    "LAMMPS NEB outputs are collected but result.json is absent; invoke the NEB parser",
                )
            engineering = _lammps_engineering_result(task)
            if engineering is not None:
                path, parsed, sources, scientific_status = engineering
                if scientific_status in {"evaluated_candidate_potential", "evaluated_ceramic_potential_candidate"}:
                    reason = (
                        "the native static candidate-potential evaluation completed with exit 0; "
                        "tensor/source identity is recorded, but material-potential and production "
                        "qualification remain false"
                    )
                elif scientific_status == "evaluated_engineering_fixture":
                    reason = (
                        "the native LAMMPS run0 completed with exit 0 as an engineering evaluation; "
                        "log.lammps and dump.final are present, with scientific qualification false"
                    )
                elif scientific_status == "engineering_sampling_not_equilibrium_qualification":
                    reason = (
                        "the native LAMMPS finite sampling completed with exit 0; this is finite native "
                        "sampling, not equilibrium qualification, and log.lammps, dump.final, "
                        "trajectory.lammpstrj, sampling.lammpstrj, pressure-series.dat, and the "
                        "protocol-requested unwrapped trajectory are present"
                    )
                elif scientific_status == "executed_bulk_thermal_protocol":
                    reason = (
                        "the native LAMMPS bulk NPT thermal protocol completed with exit 0; the saved "
                        "bulk_thermal_series contains native thermo frames with dynamic cells, while "
                        "thermal properties and material qualification remain outside this continuation check"
                    )
                elif scientific_status == "executed_bulk_heat_protocol":
                    reason = (
                        "the finite native bulk NEMD protocol completed with exit 0 and its saved "
                        "heat-reservoir and spatial-temperature tables are present; steady state "
                        "and conductivity are not inferred by continuation"
                    )
                else:
                    reason = (
                        "the native LAMMPS MD completed with exit 0 as an engineering execution; "
                        "log.lammps, dump.final, and trajectory.lammpstrj are present, with scientific qualification false"
                    )
                return _decision(
                    task,
                    "completed",
                    reason,
                    result_file=str(path),
                    scientific_status=scientific_status,
                    scientific_qualification=False,
                    source_artifacts=[str(source) for source in sources],
                )
            loaded = _read_result(task)
            if loaded is not None:
                required_outputs = "log.lammps/dump.final"
                protocol = loaded[1].get("protocol")
                if isinstance(protocol, Mapping) and protocol.get("kind") == "md":
                    required_outputs += "/trajectory.lammpstrj"
                    if protocol.get("purpose") == "md_native_sampling":
                        required_outputs += "/in.lammps/sampling.lammpstrj/pressure-series.dat"
                        if protocol.get("unwrapped_trajectory") is True:
                            required_outputs += "/trajectory.unwrapped.lammpstrj"
                    elif protocol.get("purpose") == "md_bulk_thermal":
                        required_outputs += "/in.lammps/method.json/atom-map.json/model.data/potential-files/bulk_thermal_series"
                    elif protocol.get("purpose") == "bulk_thermal_transport":
                        required_outputs += "/thermal-energy.dat/thermal-profile.dat/bulk_heat_source"
                return _decision(
                    task,
                    "review_original_error",
                    "the LAMMPS result exists but lacks complete evaluation identity, protocol, or required native "
                    f"{required_outputs} evidence",
                    result_file=str(loaded[0]),
                    scientific_status=loaded[1].get("scientific_status"),
                )
            if data.get("collect_status") != "collected":
                return _decision(
                    task,
                    "collect",
                    "the native LAMMPS job completed with exit 0 but its selected outputs are not recorded as collected",
                )
            return _decision(
                task,
                "parse",
                "LAMMPS outputs are collected but result.json is absent; invoke the LAMMPS parser",
            )
        if _is_berry_nscf_task(task):
            engineering = _berry_engineering_result(task)
            if engineering is not None:
                path, parsed, sources = engineering
                return _decision(
                    task,
                    "completed",
                    "the native ABACUS Berry NSCF completed with exit 0 as an engineering polarization evaluation; "
                    "the branch is not unwrapped and scientific, numerical, and production qualification remain false",
                    result_file=str(path),
                    scientific_status=parsed["scientific_status"],
                    branch_status=parsed["branch_status"],
                    scientific_qualification=False,
                    numerical_qualification=False,
                    production_qualification=False,
                    production_label=False,
                    source_artifacts=[str(source) for source in sources],
                )
            loaded = _read_result(task)
            if loaded is not None:
                return _decision(
                    task,
                    "review_original_error",
                    "the ABACUS Berry NSCF result exists but its schema, task/job/model/method/direction/reference identity, "
                    "or required native INPUT/KPT/STRU/running_nscf.log evidence is incomplete",
                    result_file=str(loaded[0]),
                    scientific_status=loaded[1].get("scientific_status"),
                )
            if data.get("collect_status") != "collected":
                return _decision(
                    task,
                    "collect",
                    "the native ABACUS Berry NSCF job completed with exit 0 but its selected outputs are not recorded as collected",
                )
            return _decision(
                task,
                "parse",
                "ABACUS Berry NSCF outputs are collected but result.json is absent; invoke the Berry parser",
            )
        result = _converged_result(task)
        if result is not None:
            path, parsed, sources = result
            return _decision(
                task,
                "completed",
                "the native job completed with exit 0 and the converged result references an existing source artifact",
                result_file=str(path),
                scientific_status=parsed["scientific_status"],
                source_artifacts=[str(source) for source in sources],
            )
        loaded = _read_result(task)
        if loaded is not None:
            return _decision(
                task,
                "review_original_error",
                "the result exists but its scientific_status is not converged with an existing source artifact",
                result_file=str(loaded[0]),
                scientific_status=loaded[1].get("scientific_status"),
            )
        if data.get("collect_status") != "collected":
            return _decision(
                task,
                "collect",
                "the native job completed with exit 0 but its explicitly selected outputs are not recorded as collected",
            )
        return _decision(
            task,
            "parse",
            "outputs are collected but result.json is absent; invoke the domain parser",
        )

    if job_id is None and status == "DEFINED":
        return _decision(task, "prepare", "the task is defined and can be prepared; this command does not prepare it")
    if job_id is None and status == "PREPARED":
        return _decision(task, "transfer", "the task is prepared and can be transferred; this command does not transfer it")
    if job_id is None and status == "TRANSFERRED":
        return _decision(task, "submit", "the task is transferred and can be submitted; this command does not submit it")
    return _decision(
        task,
        "review_original_error",
        "the saved task state does not identify a safe continuation action",
    )


def require_result_dependencies(task: TaskRecord, workspace: str | Path) -> list[dict[str, Any]]:
    """Validate explicit result dependencies and return their provenance.

    ``required_results`` is deliberately required from the caller; absence is
    a contract error rather than an empty dependency set.  This function only
    reads parent records and result files.
    """

    requirements = task.data["required_results"]
    workspace = Path(workspace)
    provenance: list[dict[str, Any]] = []
    for requirement in requirements:
        parent_id = requirement["task_id"]
        expected_status = requirement["scientific_status"]
        if expected_status not in _CONVERGED_STATUSES:
            raise ValueError(
                f"required result {parent_id} scientific_status {expected_status!r} is not an accepted converged dependency"
            )
        explicit_parent_path = requirement.get("task_file")
        if explicit_parent_path is None:
            parent_path = workspace / "tasks" / parent_id / "task.json"
        else:
            if not isinstance(explicit_parent_path, str) or not explicit_parent_path.strip():
                raise ValueError(f"required result {parent_id} task_file must be a non-empty absolute path")
            parent_path = Path(explicit_parent_path)
            if not parent_path.is_absolute():
                raise ValueError(f"required result {parent_id} task_file must be an absolute path")
            parent_path = parent_path.resolve()
        parent = load_task(parent_path)
        if parent.task_id != parent_id:
            raise ValueError(
                f"required result declared task_id {parent_id!r} differs from loaded task {parent.task_id!r}"
            )
        if parent.data.get("engine") == "abacus" and parent.data.get("net_charge", 0) != 0:
            raise ValueError(f"required result {parent_id} is a raw charged SCF task, not a qualified scientific dependency")
        if parent.data.get("scheduler_state") != "COMPLETED" or parent.data.get("exit_code") != "0:0":
            raise ValueError(
                f"required result {parent_id} lacks saved native COMPLETED/0:0 evidence"
            )
        result_value = requirement["result_file"]
        result_path = Path(result_value)
        if not result_path.is_absolute():
            result_path = parent_path.parent / result_path
        if not result_path.is_file():
            raise ValueError(f"required result file does not exist: {result_path}")
        with result_path.open("r", encoding="utf-8") as stream:
            result = json.load(stream)
        if result["task_id"] != parent.task_id:
            raise ValueError(
                f"required result {parent_id} belongs to task {result['task_id']!r}"
            )
        if result["scientific_status"] != expected_status:
            raise ValueError(
                f"required result {parent_id} scientific_status is "
                f"{result['scientific_status']!r}, expected {expected_status!r}"
            )
        sources, invalid, reason = source_evidence(
            result,
            result_path,
            engine=parent.data.get("engine"),
        )
        if reason != "complete":
            missing = [str(source) for source in invalid]
            raise ValueError(
                f"required result {parent_id} source artifacts are incomplete: {missing}; reason={reason}"
            )
        provenance.append(
            {
                "task_id": parent.task_id,
                "task_file": str(parent_path),
                "scheduler_job_id": parent.scheduler_job_id,
                "scheduler_state": parent.data["scheduler_state"],
                "exit_code": parent.data["exit_code"],
                "result_file": str(result_path),
                "scientific_status": result["scientific_status"],
                "source_files": [str(source) for source in sources],
            }
        )
    return provenance


def task_chain_snapshot(task_paths: Sequence[str | Path]) -> list[dict[str, Any]]:
    """Return task/model/method/job/result links and read-only plan actions."""

    snapshot: list[dict[str, Any]] = []
    for task_path_value in task_paths:
        task_path = Path(task_path_value)
        task = load_task(task_path)
        workspace = task_path.parent.parent.parent
        model_path = workspace / "models" / task.data["model_id"] / task.data["model_version"]
        method_path = task_path.parent / "method.json"
        result_path = _result_path(task)
        decision = inspect_task(task)
        snapshot.append(
            {
                "task_id": task.task_id,
                "task_path": str(task_path),
                "model_id": task.data["model_id"],
                "model_version": task.data["model_version"],
                "method_set": task.data["method_set"],
                "model_path": str(model_path),
                "method_path": str(method_path),
                "model_exists": model_path.is_dir(),
                "method_exists": method_path.is_file(),
                "job_id": task.scheduler_job_id,
                "scheduler_state": task.data.get("scheduler_state"),
                "exit_code": task.data.get("exit_code"),
                "result_path": str(result_path) if result_path is not None else None,
                "result_exists": result_path.is_file() if result_path is not None else False,
                "depends_on": task.data.get("depends_on", []),
                "suggested_action": decision["action"],
                "suggested_reason": decision["reason"],
            }
        )
    return snapshot
