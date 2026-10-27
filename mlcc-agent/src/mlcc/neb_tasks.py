"""Create and parse explicit multi-replica LAMMPS NEB tasks.

This module owns the task-record boundary for vacancy-migration NEB.  Native
input generation and native output parsing live in :mod:`mlcc.lammps_neb`;
the existing :class:`~mlcc.site_runner.SiteRunner` remains responsible for
Slurm preparation, transfer, submission, querying, and collection.

The task creator deliberately does not choose an MPI launcher, a partition,
an image count, a potential, or a GPU fallback.  Those values are explicit in
the request, site, and protocol records and are retained in ``task.json``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import posixpath
from typing import Any, Mapping, Sequence

import numpy as np

from .lammps import validate_lammps_model
from .lammps_neb import parse_lammps_neb_outputs, prepare_lammps_neb, validate_neb_protocol
from .lammps_tasks import _site_contract, _stage_potential
from .modeling import read_model_artifacts
from .tasks import TaskRecord, load_task, save_task


_TASK_SCHEMA = "mlcc.lammps-neb-task.v1"
_RESULT_SCHEMA = "mlcc.lammps-neb-result.v1"
_NEB_KIND = "neb"
_CONFLICTING_LAMMPS_ARGUMENTS = ("-partition", "-in", "-log")


def _json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON record must contain an object: {path}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _json_object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _safe_relative_name(value: Any, name: str) -> str:
    text = _text(value, name)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} must be a relative task-local path")
    if any(character in text for character in ("*", "?", "[", "]")):
        raise ValueError(f"{name} must name one file; glob patterns are unsupported")
    return path.as_posix()


def _native_names(value: Any, name: str) -> list[str]:
    """Normalize the native module's explicit task-local file list."""

    if not isinstance(value, list) or not value:
        raise ValueError(f"native NEB {name} must be a non-empty list")
    names: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"native NEB {name}[{index}] must be a string path")
        filename = _safe_relative_name(item, f"native NEB {name}[{index}]")
        if filename not in names:
            names.append(filename)
    return names


def _model_record(model: Any, model_path: str | Path) -> dict[str, Any]:
    atom_lineage_file = model.metadata.get("atom_lineage_file")
    atom_lineage_path = None
    if atom_lineage_file is not None:
        lineage_path = Path(str(atom_lineage_file))
        atom_lineage_path = str(
            (lineage_path if lineage_path.is_absolute() else Path(model_path) / lineage_path).resolve()
        )
    parent_model = {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(Path(model_path).resolve()),
        "atom_ids": model.atom_ids,
        "atom_lineage_file": atom_lineage_file,
        "atom_lineage_path": atom_lineage_path,
        "atom_lineage": copy.deepcopy(model.metadata.get("atom_lineage")),
        "parent_models": copy.deepcopy(model.metadata.get("parent_models", [])),
    }
    return {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(Path(model_path).resolve()),
        "fixture": model.metadata.get("fixture"),
        "atom_ids": model.atom_ids,
        "parent_model": parent_model,
    }


def _validate_endpoint_models(initial: Any, final: Any) -> None:
    if set(initial.atom_ids) != set(final.atom_ids):
        raise ValueError("NEB initial and final models must preserve the same atom IDs")
    initial_species = dict(zip(initial.atom_ids, initial.atoms.get_chemical_symbols()))
    final_species = dict(zip(final.atom_ids, final.atoms.get_chemical_symbols()))
    if initial_species != final_species:
        raise ValueError("NEB initial and final models must preserve the same species")
    if initial.atoms.pbc.tolist() != final.atoms.pbc.tolist():
        raise ValueError("NEB initial and final models must preserve the same PBC")
    if not np.allclose(
        np.asarray(initial.atoms.cell.array, dtype=float),
        np.asarray(final.atoms.cell.array, dtype=float),
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("NEB initial and final models must preserve the same cell")


def _validate_protocol(protocol: Mapping[str, Any], atom_ids: Sequence[int]) -> dict[str, Any]:
    validate_neb_protocol(protocol)
    if "path" in protocol:
        raise ValueError("protocol must use path_provenance instead of path")
    images = int(protocol["images"])
    ranks = int(protocol["ranks_per_image"])
    atom_id_set = {int(value) for value in atom_ids}
    moving_ids = [int(value) for value in protocol["neb_atom_ids"]]
    if not set(moving_ids).issubset(atom_id_set):
        raise ValueError("protocol.neb_atom_ids contains an unknown atom ID")
    shift_ids = [int(item["atom_id"]) for item in protocol["final_image_shifts"]]
    if set(shift_ids) != atom_id_set:
        raise ValueError("protocol.final_image_shifts must cover every endpoint atom ID")
    return {"images": images, "ranks_per_image": ranks}


def _potential_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    identity = copy.deepcopy(dict(value))
    files = identity.get("files")
    if isinstance(files, list):
        identity["files"] = [
            {key: item[key] for key in item if key != "local_path"}
            if isinstance(item, Mapping) else item
            for item in files
        ]
    return identity


def _validate_saved_contract(task: TaskRecord) -> tuple[Any, Any, dict[str, Any]]:
    data = task.data
    if data.get("schema") != _TASK_SCHEMA or data.get("engine") != "lammps" or data.get("calculation") != _NEB_KIND:
        raise ValueError("task is not an MLCC LAMMPS NEB task")
    model = read_model_artifacts(data["model_path"])
    final_model = read_model_artifacts(data["final_model_path"])
    if (model.model_id, model.version) != (data["model_id"], data["model_version"]):
        raise ValueError("saved NEB task model identity differs from model artifacts")
    if (final_model.model_id, final_model.version) != (
        data["final_model"]["model_id"],
        data["final_model"]["version"],
    ):
        raise ValueError("saved NEB task final model identity differs from model artifacts")
    _validate_endpoint_models(model, final_model)
    validate_lammps_model(model, Path(task.path).resolve().parent / "images" / "image-0")
    study = _json(data["study_file"])
    selected = _json_object(study.get("model"), "study.model")
    if (selected.get("model_id"), selected.get("version")) != (model.model_id, model.version):
        raise ValueError("saved NEB Study must select the initial model identity")
    if selected.get("path") is not None:
        selected_path = Path(str(selected["path"]))
        if not selected_path.is_absolute():
            selected_path = Path(data["study_file"]).resolve().parent / selected_path
        if selected_path.resolve() != Path(data["model_path"]).resolve():
            raise ValueError("saved NEB Study.model.path differs from the initial model path")
    if study.get("study_id") != data["study_id"]:
        raise ValueError("saved NEB Study identity differs from task")
    expected_study = {
        "study_id": study["study_id"],
        "case_id": study.get("case_id"),
        "case_role": study.get("case_role"),
        "model": copy.deepcopy(dict(selected)),
    }
    if data.get("study") != expected_study:
        raise ValueError("saved NEB Study snapshot differs from source Study")
    protocol = _json(data["protocol_file"])
    if protocol != data["protocol"]:
        raise ValueError("saved NEB protocol differs from protocol file")
    if data.get("path_provenance") != protocol.get("path_provenance"):
        raise ValueError("saved NEB task path_provenance differs from protocol")
    _validate_protocol(protocol, model.atom_ids)
    method_path = Path(data["method_path"])
    method = _json(method_path)
    if method.get("engine") != "lammps":
        raise ValueError("saved NEB method engine differs from LAMMPS task")
    if not isinstance(method.get("protocol"), Mapping):
        raise ValueError("saved NEB method is missing its protocol record")
    if method["protocol"] != protocol:
        raise ValueError("saved NEB method protocol differs from task protocol")
    if not isinstance(method.get("potential"), Mapping):
        raise ValueError("saved NEB method is missing its potential record")
    if _potential_identity(method["potential"]) != _potential_identity(data["potential"]):
        raise ValueError("saved NEB method potential differs from task potential")
    if (method.get("model_id"), method.get("version")) != (
        data["model_id"],
        data["model_version"],
    ):
        raise ValueError("saved NEB method model_id differs from task")
    if (method.get("final_model_id"), method.get("final_version")) != (
        data["final_model"]["model_id"],
        data["final_model"]["version"],
    ):
        raise ValueError("saved NEB method final_model_id differs from task")
    if not isinstance(data.get("method"), Mapping):
        raise ValueError("saved NEB task method record is missing")
    expected_method_set = f"lammps-{data['potential']['potential_id']}-{data['potential']['version']}"
    if data.get("method_set") != expected_method_set:
        raise ValueError("saved NEB task method_set differs from potential")
    if data.get("method", {}).get("method_set") != expected_method_set:
        raise ValueError("saved NEB task method record differs from potential")
    if data.get("method", {}).get("path") != str(method_path.resolve()):
        raise ValueError("saved NEB task method path differs from method.json")
    return model, final_model, method


def create_lammps_neb_task(
    *,
    study_path,
    model_path,
    final_model_path,
    potential_path,
    protocol_path,
    site_path,
    request_path,
) -> dict[str, Any]:
    """Materialize one explicit LAMMPS multi-partition NEB task."""

    study = _json(study_path)
    potential = _json(potential_path)
    protocol = _json(protocol_path)
    site = _json(site_path)
    request = _json(request_path)
    initial_model = read_model_artifacts(model_path)
    final_model = read_model_artifacts(final_model_path)
    _validate_endpoint_models(initial_model, final_model)
    _validate_protocol(protocol, initial_model.atom_ids)
    images = int(protocol["images"])
    ranks_per_image = int(protocol["ranks_per_image"])

    selected = _json_object(study.get("model"), "study.model")
    if (selected.get("model_id"), selected.get("version")) != (initial_model.model_id, initial_model.version):
        raise ValueError("study.model must select the initial NEB model identity")
    if selected.get("path") is not None:
        selected_path = Path(str(selected["path"]))
        if not selected_path.is_absolute():
            selected_path = Path(study_path).resolve().parent / selected_path
        if selected_path.resolve() != Path(model_path).resolve():
            raise ValueError("study.model.path must select the initial NEB model path")
    if protocol.get("purpose") == "potential_qualification":
        raise ValueError("NEB task must not use potential_qualification purpose")

    model_ids = potential.get("model_ids")
    if not isinstance(model_ids, list) or initial_model.model_id not in [str(value) for value in model_ids]:
        raise ValueError("LAMMPS potential is not applicable to the initial NEB model")
    if potential.get("production_qualification") is True:
        raise ValueError("NEB potential cannot be production-qualified")

    site_record = _site_contract(site)
    if not site_record.get("environment_script"):
        raise ValueError("NEB site must declare an explicit LAMMPS environment_script")
    launch_prefix = site_record.get("launch_prefix")
    if not isinstance(launch_prefix, list) or not launch_prefix or any(not str(item) for item in launch_prefix):
        raise ValueError("NEB site lammps.launch_prefix must be an explicit non-empty list")
    launch_arguments = list(site_record.get("launch_arguments", []))
    for argument in launch_arguments:
        token = str(argument)
        if token in _CONFLICTING_LAMMPS_ARGUMENTS or any(
            token.startswith(f"{flag}=") for flag in _CONFLICTING_LAMMPS_ARGUMENTS
        ):
            raise ValueError("NEB site launch_arguments must not predefine -partition, -in, or -log")

    resources = _json_object(request.get("resource_request"), "request.resource_request")
    requested_ntasks = _positive_int(resources.get("ntasks"), "request.resource_request.ntasks")
    expected_ntasks = images * ranks_per_image
    if requested_ntasks != expected_ntasks:
        raise ValueError(
            f"request.resource_request.ntasks must equal images*ranks_per_image={expected_ntasks}"
        )
    task_id = _text(request.get("task_id"), "request.task_id")
    if Path(task_id).name != task_id:
        raise ValueError("request.task_id must be a plain directory name")
    required_results = request.get("required_results", [])
    if not isinstance(required_results, list):
        raise ValueError("request.required_results must be a list")

    local_workspace = Path(site_record["local_workspace"]).expanduser().resolve()
    directory = local_workspace / "tasks" / task_id
    directory.mkdir(parents=True, exist_ok=False)
    staged_potential, potential_files = _stage_potential(potential, potential_path, directory)
    prepared = prepare_lammps_neb(
        initial_model,
        final_model,
        directory,
        potential=staged_potential,
        protocol=protocol,
    )
    if not isinstance(prepared, Mapping):
        raise ValueError("native NEB preparation must return a mapping")
    native_files = _native_names(prepared.get("files"), "files")
    collect_paths = _native_names(prepared.get("collect_paths"), "collect_paths")
    if "in.lammps" not in native_files or "method.json" not in native_files:
        raise ValueError("native NEB preparation must return in.lammps and method.json")
    method_path = directory / "method.json"
    method = _json(method_path)
    if method.get("engine") != "lammps":
        raise ValueError("native NEB method engine must be lammps")
    if method.get("protocol") != protocol:
        raise ValueError("native NEB method protocol differs from task protocol")
    if not isinstance(method.get("potential"), Mapping):
        raise ValueError("native NEB method is missing its potential record")
    if _potential_identity(method["potential"]) != _potential_identity(staged_potential):
        raise ValueError("native NEB method potential differs from task potential")
    if (method.get("model_id"), method.get("version")) != (
        initial_model.model_id,
        initial_model.version,
    ):
        raise ValueError("native NEB method model_id differs from initial model")
    if (method.get("final_model_id"), method.get("final_version")) != (
        final_model.model_id,
        final_model.version,
    ):
        raise ValueError("native NEB method final_model_id differs from final model")
    method_set = f"lammps-{potential['potential_id']}-{potential['version']}"
    if method.get("method_set") not in (None, method_set):
        raise ValueError("native NEB method_set differs from task potential")
    command = [
        *[str(item) for item in launch_prefix],
        site_record["binary"],
        *launch_arguments,
        "-partition",
        f"{images}x{ranks_per_image}",
        "-in",
        "in.lammps",
        "-log",
        "log.lammps",
    ]
    transfer_paths: list[str] = []
    for filename in [*native_files, *potential_files]:
        if filename not in transfer_paths:
            transfer_paths.append(filename)
    model_record = _model_record(initial_model, model_path)
    final_record = _model_record(final_model, final_model_path)
    study_snapshot = {
        "study_id": study["study_id"],
        "case_id": study.get("case_id"),
        "case_role": study.get("case_role"),
        "model": copy.deepcopy(dict(selected)),
    }
    data: dict[str, Any] = {
        "schema": _TASK_SCHEMA,
        "task_id": task_id,
        "stage": "P4",
        "calculation": _NEB_KIND,
        "engine": "lammps",
        "engine_version": site_record["version"],
        "site": {**site_record, "path": str(Path(site_path).resolve())},
        "site_file": str(Path(site_path).resolve()),
        "study": study_snapshot,
        "study_file": str(Path(study_path).resolve()),
        "study_id": study["study_id"],
        "case_id": study.get("case_id"),
        "case_role": study.get("case_role"),
        "model": model_record,
        "reference_model": copy.deepcopy(model_record),
        "final_model": final_record,
        "model_id": initial_model.model_id,
        "model_version": initial_model.version,
        "model_path": str(Path(model_path).resolve()),
        "final_model_path": str(Path(final_model_path).resolve()),
        "path_provenance": copy.deepcopy(protocol["path_provenance"]),
        "parent_model": copy.deepcopy(model_record["parent_model"]),
        "method": {
            "schema": method.get("schema"),
            "path": str(method_path.resolve()),
            "method_set": method_set,
            "engine": method.get("engine", "lammps"),
            "protocol": copy.deepcopy(protocol),
        },
        "method_set": method_set,
        "method_path": str(method_path.resolve()),
        "potential": copy.deepcopy(dict(potential)),
        "potential_file": str(Path(potential_path).resolve()),
        "staged_potential_files": potential_files,
        "protocol": copy.deepcopy(dict(protocol)),
        "protocol_file": str(Path(protocol_path).resolve()),
        "production_label": False,
        "production_qualification": False,
        "fixture": initial_model.metadata.get("fixture"),
        "required_results": copy.deepcopy(required_results),
        "depends_on": [item["task_id"] for item in required_results if isinstance(item, Mapping) and "task_id" in item],
        "resource_request": copy.deepcopy(dict(resources)),
        "runner": "slurm",
        "environment_script": site_record["environment_script"],
        "scheduler_job_id": None,
        "command": command,
        "local_workdir": str(directory.resolve()),
        "remote_workdir": posixpath.join(site_record["remote_root"], "tasks", task_id),
        "transfer_paths": transfer_paths,
        "collect_paths": collect_paths,
        "native_files": native_files,
        "native_collect_paths": collect_paths,
        "status": "defined",
        "scientific_status": "not_calculated",
        "request_file": str(Path(request_path).resolve()),
    }
    task = TaskRecord(data, directory / "task.json")
    task.record_event(
        "create",
        study_file=str(Path(study_path).resolve()),
        model_path=str(Path(model_path).resolve()),
        final_model_path=str(Path(final_model_path).resolve()),
        potential_file=str(Path(potential_path).resolve()),
        protocol_file=str(Path(protocol_path).resolve()),
        request_file=str(Path(request_path).resolve()),
        result="native_inputs_written_not_submitted",
    )
    save_task(task)
    return task.data


def read_lammps_neb_task(task_path: str | Path) -> dict[str, Any]:
    """Read one completed NEB task and parse its native multi-image output."""

    task = load_task(task_path)
    if task.scheduler_job_id is None:
        raise ValueError("parsing NEB results requires a real scheduler_job_id")
    if task.data.get("scheduler_state") != "COMPLETED" or task.data.get("exit_code") != "0:0":
        raise ValueError("parsing NEB results requires saved native COMPLETED/0:0")
    _validate_saved_contract(task)
    directory = Path(task_path).resolve().parent
    parsed = parse_lammps_neb_outputs(directory)
    if not isinstance(parsed, Mapping):
        raise ValueError("native NEB parser must return a mapping")
    data = dict(parsed)
    if data.get("schema") != _RESULT_SCHEMA:
        raise ValueError("native NEB parser returned an unexpected schema")
    if data.get("engine") != "lammps":
        raise ValueError("native NEB result engine differs from task")
    site = task.data.get("site")
    if not isinstance(site, Mapping) or site.get("version") != task.data.get("engine_version"):
        raise ValueError("NEB task engine version differs from site declaration")
    if data.get("engine_version") != task.data.get("engine_version"):
        raise ValueError("native NEB engine version differs from task/site declaration")
    if (data.get("model_id"), data.get("version")) != (
        task.data["model_id"],
        task.data["model_version"],
    ):
        raise ValueError("native NEB result model identity differs from task")
    if (data.get("final_model_id"), data.get("final_version")) != (
        task.data["final_model"]["model_id"],
        task.data["final_model"]["version"],
    ):
        raise ValueError("native NEB result final model identity differs from task")
    if data.get("protocol") != task.data["protocol"]:
        raise ValueError("native NEB result protocol differs from task")
    if not isinstance(data.get("potential"), Mapping):
        raise ValueError("native NEB result is missing its potential record")
    if _potential_identity(data["potential"]) != _potential_identity(task.data["potential"]):
        raise ValueError("native NEB result potential differs from task")
    scientific_status = data.get("scientific_status")
    if not isinstance(scientific_status, str) or not scientific_status.strip():
        raise ValueError("native NEB result is missing scientific_status")
    data.update(
        {
            "schema": _RESULT_SCHEMA,
            "engine": "lammps",
            "task_id": task.task_id,
            "scheduler_job_id": task.scheduler_job_id,
            "scheduler_state": task.data["scheduler_state"],
            "exit_code": task.data["exit_code"],
            "study_id": task.data["study_id"],
            "case_id": task.data.get("case_id"),
            "case_role": task.data.get("case_role"),
            "study": copy.deepcopy(task.data["study"]),
            "study_file": task.data["study_file"],
            "model": copy.deepcopy(task.data["model"]),
            "reference_model": copy.deepcopy(task.data["reference_model"]),
            "model_id": task.data["model_id"],
            "model_version": task.data["model_version"],
            "model_path": task.data["model_path"],
            "final_model": copy.deepcopy(task.data["final_model"]),
            "final_model_path": task.data["final_model_path"],
            "parent_model": copy.deepcopy(task.data["parent_model"]),
            "path_provenance": copy.deepcopy(task.data["path_provenance"]),
            "fixture": task.data["fixture"],
            "potential": copy.deepcopy(task.data["potential"]),
            "potential_file": task.data["potential_file"],
            "protocol": copy.deepcopy(task.data["protocol"]),
            "protocol_file": task.data["protocol_file"],
            "method": copy.deepcopy(task.data["method"]),
            "method_path": task.data["method_path"],
            "method_set": task.data["method_set"],
            "production_label": False,
            "production_qualification": False,
            "source_task": str(Path(task_path).resolve()),
        }
    )
    return data


def parse_lammps_neb_task(task_path: str | Path) -> dict[str, Any]:
    """Persist a validated native NEB result and its parse event."""

    data = read_lammps_neb_task(task_path)
    task = load_task(task_path)
    directory = Path(task_path).resolve().parent
    result_path = directory / "result.json"
    result_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    task.set(scientific_status=data["scientific_status"], result_file=str(result_path))
    task.record_event("parse", scientific_status=data["scientific_status"], result_file=str(result_path))
    save_task(task)
    return data


__all__ = [
    "create_lammps_neb_task",
    "read_lammps_neb_task",
    "parse_lammps_neb_task",
]
