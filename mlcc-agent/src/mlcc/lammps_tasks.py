"""Create and parse explicit LAMMPS Slurm tasks.

The task layer owns study/site/request identity and stages the caller-selected
potential files.  Native data/input generation and native output parsing stay
in :mod:`mlcc.lammps`; this module never submits a task.
"""

from __future__ import annotations

import json
from pathlib import Path
import posixpath
import shutil
from typing import Any, Mapping

from .lammps import (
    _is_mace_potential,
    parse_lammps_outputs,
    prepare_lammps,
    validate_lammps_model,
    validate_lammps_protocol,
)
from .lammps_local_stress import local_stress_enabled, validate_local_stress_model
from .modeling import read_model_artifacts
from .tasks import TaskRecord, load_task, save_task


_INPUT_FILES = ("model.data", "atom-map.json", "in.lammps", "method.json")
_RUN0_OUTPUT_FILES = ("stdout.log", "stderr.log", "log.lammps", "dump.final")
_MD_OUTPUT_FILES = (
    "stdout.log",
    "stderr.log",
    "log.lammps",
    "dump.final",
    "trajectory.lammpstrj",
)


def _json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON record must contain an object: {path}")
    return value


def _site_contract(site: Mapping[str, Any]) -> dict[str, Any]:
    ssh = site["ssh"]
    workspace = site["workspace"]
    runner = site["runner"]
    if runner["selected"] != "slurm":
        raise ValueError("LAMMPS tasks require runner.selected=slurm")
    lammps = site["lammps"]
    binary = str(lammps["binary"])
    version = str(lammps["version"])
    environment_script = lammps["environment_script"]
    launch_prefix = lammps["launch_prefix"]
    launch_arguments = lammps.get("launch_arguments", [])
    if not binary or not version:
        raise ValueError("LAMMPS site binary and version must be explicit")
    if not isinstance(launch_prefix, list) or any(not isinstance(item, str) for item in launch_prefix):
        raise ValueError("LAMMPS site launch_prefix must be a list of strings")
    if not isinstance(launch_arguments, list) or any(
        not isinstance(item, str) for item in launch_arguments
    ):
        raise ValueError("LAMMPS site launch_arguments must be a list of strings")
    return {
        "ssh_alias": str(ssh["alias"]),
        "local_workspace": str(workspace["local"]),
        "remote_root": str(workspace["remote_root"]),
        "runner": str(runner["selected"]),
        "binary": binary,
        "version": version,
        "environment_script": environment_script,
        "launch_prefix": list(launch_prefix),
        "launch_arguments": list(launch_arguments),
    }


_MACE_PAIR_STYLE = "mace no_domain_decomposition"
_MACE_LAUNCH_ARGUMENTS = ["-k", "on", "g", "1", "-sf", "kk"]


def _validate_mace_resources(resources: Mapping[str, Any]) -> None:
    """Require one explicitly allocated Slurm GPU for the native MACE route."""

    if "nodes" not in resources or int(resources["nodes"]) != 1:
        raise ValueError("native MACE requires resource_request.nodes=1")
    keys = ("gres", "gpus", "gpus_per_task")
    present = [key for key in keys if resources.get(key) not in (None, "")]
    if len(present) != 1:
        raise ValueError("native MACE requires one explicit GPU resource (gres, gpus, or gpus_per_task)")
    key = present[0]
    value = resources[key]
    if isinstance(value, bool):
        raise ValueError("native MACE GPU resource must request exactly one GPU")
    text = str(value).strip()
    if key == "gres":
        # Accept the native site_runner spelling, for example gpu:v100:1.
        parts = text.split(",")
        if len(parts) != 1 or not parts[0].startswith("gpu:"):
            raise ValueError("native MACE gres must explicitly name one gpu resource")
        count_text = parts[0].rsplit(":", 1)[-1]
    else:
        count_text = text.rsplit(":", 1)[-1]
    if not count_text.isdigit() or int(count_text) != 1:
        raise ValueError("native MACE GPU resource must request exactly one GPU")


def _validate_mace_task_contract(
    potential: Mapping[str, Any],
    protocol: Mapping[str, Any],
    site: Mapping[str, Any],
    resources: Mapping[str, Any],
) -> None:
    if not _is_mace_potential(potential):
        return
    if potential["pair_style"] != _MACE_PAIR_STYLE:
        raise ValueError("MACE requires the supported pair_style 'mace no_domain_decomposition'")
    if (protocol.get("kind"), protocol.get("purpose")) not in {
        ("run0", "potential_qualification"), ("interface_normal", "interface_normal_response"),
        ("interface_tangential", "interface_tangential_response"),
        ("md", "interface_thermal_response"),
        ("run0", "interface_local_stress"),
    }:
        raise ValueError("native MACE requires an explicit static candidate or supported interface protocol")
    if protocol.get("purpose") == "interface_thermal_response":
        from .lammps_interface_thermal import validate_thermal_protocol
        validate_thermal_protocol(protocol)
    elif protocol.get("static_tensor") is not True:
        raise ValueError("native MACE requires static_tensor=true")
    if potential.get("production_qualification") is not False:
        raise ValueError("native MACE qualification must remain production_qualification=false")
    if site.get("launch_arguments") != _MACE_LAUNCH_ARGUMENTS:
        raise ValueError("native MACE site launch_arguments must explicitly provide -k on g 1 -sf kk")
    _validate_mace_resources(resources)


def _study_model_contract(study: Mapping[str, Any], model_path: str | Path, protocol: Mapping[str, Any]):
    model = read_model_artifacts(model_path)
    selected = study["model"]
    if (selected["model_id"], selected["version"]) != (model.model_id, model.version):
        raise ValueError("study must explicitly select this model ID and version")
    fixture = model.metadata["fixture"]
    if fixture is False and protocol.get("purpose") in {"potential_qualification", "interface_normal_response", "interface_tangential_response", "interface_thermal_response", "interface_local_stress", "md_native_sampling", "md_bulk_thermal", "bulk_thermal_transport"}:
        if study["case_role"] == "engineering_fixture":
            raise ValueError("LAMMPS scientific model cannot be labeled an engineering fixture")
        for field in ("material", "phase_requested"):
            if not selected[field] or selected[field] != model.metadata[field]:
                raise ValueError(f"LAMMPS study {field} differs from selected scientific model")
    elif study["case_role"] != "engineering_fixture" or fixture is not True:
        raise ValueError("LAMMPS ordinary tasks support engineering fixtures only")
    if "fixture" in selected and selected["fixture"] is not fixture:
        raise ValueError("LAMMPS study model fixture flag differs from model")
    return model


def _stage_potential(
    potential: Mapping[str, Any],
    potential_path: str | Path,
    directory: Path,
) -> tuple[dict[str, Any], list[str]]:
    files = potential["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("LAMMPS potential files must be a non-empty list")
    staged: list[dict[str, Any]] = []
    names: list[str] = []
    source_root = Path(potential_path).resolve().parent
    for item in files:
        filename = Path(str(item["filename"]))
        if filename.is_absolute() or ".." in filename.parts:
            raise ValueError("LAMMPS potential filename must stay inside the task directory")
        source = Path(str(item["local_path"]))
        if not source.is_absolute():
            source = source_root / source
        destination = directory / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        staged.append({**dict(item), "local_path": str(destination), "filename": filename.as_posix()})
        names.append(filename.as_posix())
    selected = dict(potential)
    selected["files"] = staged
    return selected, names


def _method_record(directory: Path, potential: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    method_path = directory / "method.json"
    method = _json(method_path)
    method_set = f"lammps-{potential['potential_id']}-{potential['version']}"
    return {
        "schema": method["schema"],
        "path": str(method_path.resolve()),
        "method_set": method_set,
        "engine": method["engine"],
        "units": method["units"],
        "atom_style": method["atom_style"],
    }, method_set


def create_lammps_task(
    *,
    study_path,
    model_path,
    potential_path,
    protocol_path,
    site_path,
    request_path,
):
    """Materialize one LAMMPS task without transfer or scheduler submission."""

    study = _json(study_path)
    potential = _json(potential_path)
    protocol = _json(protocol_path)
    site = _json(site_path)
    request = _json(request_path)
    validate_lammps_protocol(protocol)
    qualification = protocol.get("purpose") in {"potential_qualification", "interface_normal_response", "interface_tangential_response", "interface_thermal_response", "interface_local_stress", "md_native_sampling", "md_bulk_thermal", "bulk_thermal_transport"}
    model = _study_model_contract(study, model_path, protocol)
    if protocol["kind"] == "interface_normal":
        from .lammps_interface_normal import validate_normal_model
        validate_normal_model(model, protocol)
    if protocol["kind"] == "interface_tangential":
        from .lammps_interface_normal import validate_tangential_model
        validate_tangential_model(model, protocol)
    if protocol.get("purpose") == "interface_thermal_response":
        from .lammps_interface_thermal import validate_thermal_model
        validate_thermal_model(model, protocol)
    if protocol.get("purpose") == "bulk_thermal_transport":
        from .lammps_bulk_heat import validate_bulk_heat_model

        validate_bulk_heat_model(model, protocol)
    if local_stress_enabled(protocol):
        validate_local_stress_model(model, protocol)
    site_record = _site_contract(site)

    if qualification and potential["production_qualification"] is not False:
        raise ValueError("LAMMPS qualification candidate must remain production_qualification=false")
    if not qualification and (potential["fixture"] is not True or potential.get("production_qualification") is True):
        raise ValueError("LAMMPS task potential must remain an engineering fixture")
    if model.model_id not in [str(value) for value in potential["model_ids"]]:
        raise ValueError("LAMMPS potential is not applicable to this model_id")
    validate_lammps_protocol(protocol)
    kind = str(protocol["kind"])
    task_id = str(request["task_id"])
    if not task_id:
        raise ValueError("LAMMPS request task_id must be non-empty")
    required_results = request["required_results"]
    resources = request["resource_request"]
    if not isinstance(required_results, list) or not isinstance(resources, dict):
        raise ValueError("LAMMPS request requires required_results and resource_request")
    if int(resources["ntasks"]) != 1:
        raise ValueError("LAMMPS task resource_request.ntasks must be 1")
    _validate_mace_task_contract(potential, protocol, site_record, resources)

    local_workspace = Path(site_record["local_workspace"])
    directory = local_workspace / "tasks" / task_id
    directory.mkdir(parents=True)
    grain_binding = None
    if model.metadata.get("spatial_mode") == "grain_boundary" or study.get("grain_boundary") is not None:
        # The helper validates the child Study against the original Model and
        # stages only static provenance; it does not alter the LAMMPS inputs.
        from .grain_task_sources import stage_grain_task_sources

        grain_binding = stage_grain_task_sources(
            study,
            model,
            directory,
            study_file=str(Path(study_path).resolve()),
        )
    interface_binding = None
    if model.metadata.get("spatial_mode") == "layered_interface" or study.get("interface") is not None:
        from .interface_sources import stage_interface_task_sources

        interface_binding = stage_interface_task_sources(
            study, model, directory, study_file=study_path,
        )
    staged_potential, potential_files = _stage_potential(potential, potential_path, directory)
    prepare_lammps(model, directory, potential=staged_potential, protocol=protocol)
    method, method_set = _method_record(directory, potential)

    command = [
        *site_record["launch_prefix"],
        site_record["binary"],
        *site_record["launch_arguments"],
        "-in",
        "in.lammps",
        "-log",
        "log.lammps",
    ]
    stage = "P11" if interface_binding is not None else ("P9" if kind == "run0" else "P10")
    remote_workdir = posixpath.join(site_record["remote_root"], "tasks", task_id)
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
        "atom_lineage": model.metadata.get("atom_lineage"),
        "parent_models": model.metadata.get("parent_models", []),
    }
    if qualification:
        parent_model.update(source_path=model.metadata["source_path"], source_version=model.metadata["source_version"])
    model_record = {
        "model_id": model.model_id,
        "version": model.version,
        "path": str(Path(model_path).resolve()),
        "fixture": model.metadata["fixture"],
        "atom_ids": model.atom_ids,
        "parent_model": parent_model,
    }
    study_snapshot = {
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": study["case_role"],
        "model": dict(study["model"]),
    }
    transfer_paths = [*_INPUT_FILES, *potential_files]
    if grain_binding is not None:
        study_snapshot.update(
            parent_study_id=study.get("parent_study_id"),
            grain_boundary=study["grain_boundary"],
        )
        transfer_paths.extend(grain_binding["transfer_paths"])
    if interface_binding is not None:
        study_snapshot["interface"] = study["interface"]
        transfer_paths.extend(interface_binding["transfer_paths"])
    collect_paths = list(_RUN0_OUTPUT_FILES if kind == "run0" else _MD_OUTPUT_FILES)
    if kind == "md":
        from .md_unwrapped import unwrapped_output_files

        collect_paths.extend(unwrapped_output_files(protocol))
        from .lammps_md_sampling import md_sampling_output_files

        collect_paths.extend(md_sampling_output_files(protocol))
    if protocol.get("purpose") == "interface_thermal_response":
        collect_paths.extend(["thermal-energy.dat", "thermal-profile.dat"])
    if protocol.get("purpose") == "bulk_thermal_transport":
        from .lammps_bulk_heat import bulk_heat_output_files

        collect_paths.extend(bulk_heat_output_files(protocol))
    if local_stress_enabled(protocol):
        collect_paths.append("local-stress.lammpstrj")
    if kind == "interface_normal":
        from .lammps_interface_normal import normal_output_files
        collect_paths = ["stdout.log", "stderr.log", "log.lammps", *normal_output_files(protocol)]
    if kind == "interface_tangential":
        from .lammps_interface_normal import tangential_output_files
        collect_paths = ["stdout.log", "stderr.log", "log.lammps", *tangential_output_files(protocol)]
    data = {
        "task_id": task_id,
        "stage": stage,
        "calculation": kind,
        "engine": "lammps",
        "engine_version": site_record["version"],
        "site": {**site_record, "path": str(Path(site_path).resolve())},
        "site_file": str(Path(site_path).resolve()),
        "study": study_snapshot,
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": study["case_role"],
        "model": model_record,
        "model_id": model.model_id,
        "model_version": model.version,
        "model_path": str(Path(model_path).resolve()),
        "parent_model": parent_model,
        "method": method,
        "method_set": method_set,
        "method_path": method["path"],
        "potential": dict(potential),
        "potential_file": str(Path(potential_path).resolve()),
        "staged_potential_files": potential_files,
        "protocol": dict(protocol),
        "protocol_file": str(Path(protocol_path).resolve()),
        "production_label": False,
        "fixture": model.metadata["fixture"],
        "required_results": required_results,
        "depends_on": [item["task_id"] for item in required_results],
        "resource_request": resources,
        "runner": "slurm",
        "environment_script": site_record["environment_script"],
        "scheduler_job_id": None,
        "command": command,
        "local_workdir": str(directory.resolve()),
        "remote_workdir": remote_workdir,
        "transfer_paths": transfer_paths,
        "collect_paths": collect_paths,
        "status": "defined",
        "scientific_status": "not_calculated",
    }
    if grain_binding is not None:
        data["study_file"] = str(Path(study_path).resolve())
        data["grain_boundary_sources"] = grain_binding
    if interface_binding is not None:
        data["study_file"] = str(Path(study_path).resolve())
        data["interface_sources"] = interface_binding
    if qualification:
        data["production_qualification"] = False
    task = TaskRecord(data, directory / "task.json")
    task.record_event(
        "create",
        study_file=str(Path(study_path).resolve()),
        model_path=str(Path(model_path).resolve()),
        potential_file=str(Path(potential_path).resolve()),
        protocol_file=str(Path(protocol_path).resolve()),
        request_file=str(Path(request_path).resolve()),
        result="native_inputs_written_not_submitted",
    )
    save_task(task)
    return task.data


def _potential_identity(potential: Mapping[str, Any]) -> dict[str, Any]:
    """Return the native identity fields that bind a potential to a task.

    The task and ``method.json`` records intentionally have different
    ``local_path`` values after staging.  The filename and all scientific
    identity fields still have to match exactly before the parsed native
    record is attached to the task.
    """

    return {
        **dict(potential),
        "files": [
            {key: value for key, value in item.items() if key != "local_path"}
            for item in potential["files"]
        ],
    }


def read_lammps_task(task_path):
    """Read one completed task and native output without changing its evidence."""

    task = load_task(task_path)
    if task.data["engine"] != "lammps":
        raise ValueError("parsing scientific results requires a LAMMPS task")
    if task.data.get("scheduler_state") != "COMPLETED" or task.data.get("exit_code") != "0:0":
        raise ValueError("parsing scientific results requires saved native COMPLETED/0:0")
    if task.data.get("production_label") is not False:
        raise ValueError("LAMMPS parser requires production_label=false")
    directory = Path(task_path).resolve().parent
    method = _json(directory / "method.json")
    protocol = method["protocol"]
    validate_lammps_protocol(protocol)
    if protocol != task.data["protocol"]:
        raise ValueError("LAMMPS task protocol differs from native method")
    qualification = protocol.get("purpose") in {"potential_qualification", "interface_normal_response", "interface_tangential_response", "interface_thermal_response", "interface_local_stress", "md_native_sampling", "md_bulk_thermal", "bulk_thermal_transport"}
    if qualification and task.data["production_qualification"] is not False:
        raise ValueError("LAMMPS qualification task must remain production_qualification=false")
    if qualification and any(task.data[key] != task.data["study"][key] for key in ("study_id", "case_id", "case_role")):
        raise ValueError("LAMMPS qualification study identity differs from task")
    model = _study_model_contract(task.data["study"], task.data["model_path"], protocol)
    if protocol["kind"] == "interface_normal":
        from .lammps_interface_normal import validate_normal_model
        validate_normal_model(model, protocol)
    if protocol["kind"] == "interface_tangential":
        from .lammps_interface_normal import validate_tangential_model
        validate_tangential_model(model, protocol)
    if protocol.get("purpose") == "interface_thermal_response":
        from .lammps_interface_thermal import validate_thermal_model
        validate_thermal_model(model, protocol)
    if protocol.get("purpose") == "bulk_thermal_transport":
        from .lammps_bulk_heat import validate_bulk_heat_model

        validate_bulk_heat_model(model, protocol)
    if local_stress_enabled(protocol):
        validate_local_stress_model(model, protocol)
    if (model.model_id, model.version) != (
        task.data["model_id"],
        task.data["model_version"],
    ):
        raise ValueError("LAMMPS task model identity differs from model artifacts")
    if (task.data["model"]["model_id"], task.data["model"]["version"]) != (
        model.model_id,
        model.version,
    ):
        raise ValueError("LAMMPS task model record differs from model artifacts")
    if task.data["fixture"] is not model.metadata["fixture"] or task.data["model"]["fixture"] is not model.metadata["fixture"]:
        raise ValueError("LAMMPS fixture role differs from parent model")
    if (task.data["parent_model"]["model_id"], task.data["parent_model"]["version"]) != (
        model.model_id,
        model.version,
    ):
        raise ValueError("LAMMPS parent model identity differs from model artifacts")
    grain_binding = task.data.get("grain_boundary_sources")
    grain_provenance = None
    if grain_binding is not None:
        from .grain_task_sources import read_grain_task_sources

        grain_provenance = read_grain_task_sources(
            directory,
            grain_binding,
            study_id=task.data["study_id"],
            model_id=task.data["model_id"],
            model_version=task.data["model_version"],
            atom_ids=model.atom_ids,
        )
        snapshot = task.data.get("study")
        if not isinstance(snapshot, dict) or snapshot.get("grain_boundary") != grain_binding.get("study_grain_boundary"):
            raise ValueError("saved LAMMPS Study grain-boundary snapshot differs from its source binding")
    interface_binding = task.data.get("interface_sources")
    interface_provenance = None
    if interface_binding is not None:
        from .interface_sources import read_interface_task_sources

        interface_provenance = read_interface_task_sources(
            directory, interface_binding, study_id=task.data["study_id"],
            model_id=model.model_id, model_version=model.version, atom_ids=model.atom_ids,
        )
        if task.data["study"]["interface"] != interface_binding["study_interface"]:
            raise ValueError("LAMMPS interface Study differs from task source binding")
    validate_lammps_model(model, directory)
    if qualification:
        expected_lineage = {"atom_ids": model.atom_ids, "parent_models": model.metadata.get("parent_models", []),
                            "source_path": model.metadata["source_path"], "source_version": model.metadata["source_version"]}
        if any(task.data["parent_model"][key] != value for key, value in expected_lineage.items()):
            raise ValueError("LAMMPS qualification model lineage differs from parent model")
    if task.data["calculation"] != protocol["kind"]:
        raise ValueError("LAMMPS task calculation differs from method protocol")
    expected_stage = "P11" if interface_binding is not None else ("P9" if protocol["kind"] == "run0" else "P10")
    if task.data["stage"] != expected_stage:
        raise ValueError("LAMMPS task stage differs from method protocol")
    native_method_set = f"lammps-{method['potential']['potential_id']}-{method['potential']['version']}"
    if task.data["method_set"] != native_method_set:
        raise ValueError("LAMMPS task method_set differs from native potential")
    if task.data["method"]["method_set"] != native_method_set:
        raise ValueError("LAMMPS task method record differs from native potential")
    parsed = parse_lammps_outputs(directory)
    if parsed["engine"] != "lammps":
        raise ValueError("LAMMPS parser returned a different engine")
    if (parsed["model_id"], parsed["version"]) != (
        task.data["model_id"],
        task.data["model_version"],
    ):
        raise ValueError("LAMMPS result model identity differs from task")
    site_version = task.data["site"]["version"]
    if task.data["engine_version"] != site_version:
        raise ValueError("LAMMPS task engine version differs from site declaration")
    if parsed["engine_version"] != site_version:
        raise ValueError("LAMMPS native engine version differs from site declaration")
    if _potential_identity(parsed["potential"]) != _potential_identity(task.data["potential"]):
        raise ValueError("LAMMPS native potential identity differs from task")
    if protocol != task.data["protocol"]:
        raise ValueError("LAMMPS result protocol differs from task")
    kind = protocol["kind"]
    status = ("executed_bulk_heat_protocol" if protocol.get("purpose") == "bulk_thermal_transport" else
              "executed_bulk_thermal_protocol" if protocol.get("purpose") == "md_bulk_thermal" else
              "engineering_sampling_not_equilibrium_qualification" if protocol.get("purpose") == "md_native_sampling" else
              "evaluated_local_virial_stress" if local_stress_enabled(protocol) else
              "executed_interface_thermal_protocol" if protocol.get("purpose") == "interface_thermal_response" else
              "evaluated_interface_normal_response" if kind == "interface_normal" else
              "evaluated_interface_tangential_response" if kind == "interface_tangential" else
              "evaluated_candidate_potential" if qualification else
              "evaluated_engineering_fixture" if kind == "run0" else "executed_engineering_fixture")
    data = dict(parsed)
    data.update(
        task_id=task.task_id,
        scheduler_job_id=task.scheduler_job_id,
        scheduler_state=task.data["scheduler_state"],
        exit_code=task.data["exit_code"],
        study_id=task.data["study_id"],
        case_id=task.data["case_id"],
        case_role=task.data["case_role"],
        model_path=task.data["model_path"],
        method_set=task.data["method_set"],
        protocol=protocol,
        production_label=False,
        fixture=model.metadata["fixture"],
        parent_model=task.data["parent_model"],
        scientific_status=status,
    )
    if kind == "md":
        data["sampling_equilibrium_qualified"] = False
    if grain_binding is not None:
        data.update(
            study_file=task.data["study_file"],
            study=task.data["study"],
            grain_boundary_sources=grain_binding,
            grain_boundary_provenance=grain_provenance,
        )
    if interface_binding is not None:
        data.update(
            study_file=task.data["study_file"], study=task.data["study"],
            interface_sources=interface_binding, interface_provenance=interface_provenance,
        )
    return data


def parse_lammps_task(task_path):
    """Persist the validated native result and its task parse event."""
    data = read_lammps_task(task_path)
    task = load_task(task_path)
    directory = Path(task_path).resolve().parent
    status = data["scientific_status"]
    result_path = directory / "result.json"
    result_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if "bulk_heat_source" in data:
        (directory / "bulk-heat-source.json").write_text(
            json.dumps(data["bulk_heat_source"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    task.set(scientific_status=status, result_file=str(result_path))
    task.record_event("parse", scientific_status=status, result_file=str(result_path))
    save_task(task)
    return data
