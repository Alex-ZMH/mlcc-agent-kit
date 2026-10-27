"""Explicit ABACUS 3.10.1 Berry-phase task materialization.

The module keeps the Berry workflow as two ordinary Slurm task records:
an SCF reference that writes the native charge-density cube files under
``OUT.<suffix>/`` and an NSCF task that copies those files into its work
directory and reads them with ``read_file_dir ./`` and ABACUS's native
``init_chg=file`` interface.  It does not submit a job or manufacture an
electronic result.
The reference validation deliberately consumes native electronic evidence;
``result.json`` alone is not a Berry prerequisite.
"""

from __future__ import annotations

from dataclasses import MISSING, fields
import json
import math
from pathlib import Path
import re
import shlex
import shutil
from typing import Any, Mapping, Sequence

import numpy as np

from .abacus import (
    ABACUS_BASIS_TYPE,
    ABACUS_VERSION,
    AbacusExecution,
    AbacusMethod,
    AbacusParameters,
    _read_stru,
    parse_abacus_outputs,
    prepare_abacus,
)
from .berry import BERRY_GPU_IMPLEMENTATION_ID, BERRY_GPU_SCOPE
from .electronic import read_abacus_electronic_task
from .method_tasks import check_method_configuration
from .modeling import ModelArtifacts, read_model_artifacts
from .tasks import TaskRecord, load_task, save_task


TASK_STAGE = "P5"
BERRY_SCHEMA = "mlcc.abacus-berry.v1"
CHARGE_FILES_BY_NSPIN = {
    1: ("SPIN1_CHG.cube",),
    2: ("SPIN1_CHG.cube", "SPIN2_CHG.cube"),
}


def _json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _task_file(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if candidate.is_dir():
        candidate = candidate / "task.json"
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _task_dir(path: str | Path) -> Path:
    return _task_file(path).parent


def _parameter_values(config: Mapping[str, Any]) -> AbacusParameters:
    raw = config.get("parameters")
    if not isinstance(raw, Mapping):
        raise ValueError("ABACUS method parameters must be an object")
    values: dict[str, Any] = {}
    for field in fields(AbacusParameters):
        if field.name in raw:
            values[field.name] = raw[field.name]
        elif field.default is not MISSING:
            values[field.name] = field.default
        elif field.default_factory is not MISSING:  # type: ignore[comparison-overlap]
            values[field.name] = field.default_factory()  # type: ignore[misc]
        else:
            raise ValueError(f"ABACUS method parameters missing {field.name}")
    return AbacusParameters(**values)


def _pseudopotentials(config: Mapping[str, Any], site: Mapping[str, Any]) -> dict[str, str]:
    element_order = config.get("element_order")
    pseudo_ids = config.get("pseudopotential_ids")
    if not isinstance(element_order, Sequence) or isinstance(element_order, (str, bytes)):
        raise ValueError("ABACUS method element_order must be a sequence")
    if not isinstance(pseudo_ids, Mapping):
        raise ValueError("ABACUS method pseudopotential_ids must be an object")
    abacus_site = site.get("abacus")
    if not isinstance(abacus_site, Mapping) or not isinstance(abacus_site.get("pseudopotential_files"), Mapping):
        raise ValueError("site.abacus.pseudopotential_files is required")
    available = abacus_site["pseudopotential_files"]
    result: dict[str, str] = {}
    for element_value in element_order:
        element = str(element_value)
        pseudo_id = pseudo_ids.get(element)
        if pseudo_id not in available:
            raise KeyError(f"selected pseudopotential ID is absent from site configuration: {pseudo_id!r}")
        result[element] = str(available[pseudo_id])
    return result


def _validate_model_study(model: ModelArtifacts, study: Mapping[str, Any]) -> None:
    study_id = _text(study.get("study_id"), "study_id")
    selected = study.get("model")
    if not isinstance(selected, Mapping):
        raise ValueError("study.model must be an object")
    if (selected.get("model_id"), selected.get("version")) != (model.model_id, model.version):
        raise ValueError("study must explicitly select this model ID and version")
    if model.metadata.get("study_binding") not in (None, study_id):
        raise ValueError("derived model study_binding differs from the requested study")
    expected_fixture = study.get("case_role") == "engineering_fixture"
    if bool(model.metadata.get("fixture", False)) != expected_fixture:
        raise ValueError("study and model fixture roles differ")
    if not expected_fixture:
        for field in ("material", "phase_requested"):
            selected_value = selected.get(field)
            model_value = model.metadata.get(field)
            if not selected_value or selected_value != model_value:
                raise ValueError(f"study {field} must match the explicitly selected model")


def _load_method_inputs(
    *, model: ModelArtifacts, config: Mapping[str, Any], site: Mapping[str, Any], method_path: str | Path
) -> tuple[AbacusMethod, AbacusExecution, AbacusParameters, dict[str, str], dict[str, Any] | None]:
    if config.get("engine") != "abacus" or config.get("engine_version") != ABACUS_VERSION or config.get("basis_type") != ABACUS_BASIS_TYPE:
        raise ValueError("Berry adapter requires ABACUS 3.10.1 PW")
    science = config.get("science")
    execution = config.get("execution")
    if not isinstance(science, Mapping) or not isinstance(execution, Mapping):
        raise ValueError("ABACUS method science and execution objects are required")
    method = AbacusMethod(**dict(science))
    element_order = config.get("element_order")
    if not isinstance(element_order, Sequence) or isinstance(element_order, (str, bytes)):
        raise ValueError("ABACUS method element_order must be a sequence")
    method.validate([str(value) for value in element_order])
    if method.occupations != "fixed":
        raise ValueError("Berry phase requires fixed occupations for an insulating reference")
    if method.nspin != 1:
        raise ValueError(
            "unsupported_spin_resolved_occupations: ABACUS 3.10.1 uses one occupied-band count for both spin channels"
        )
    if method.lspinorb or method.noncolin:
        raise ValueError("Berry adapter supports only nspin=1 non-SOC collinear methods")
    if method.symmetry != -1:
        raise ValueError("Berry method configuration must set symmetry=-1 explicitly")
    if config.get("net_charge") != 0:
        raise ValueError("Berry tasks require explicit neutral net_charge=0")
    model_charge = model.metadata.get("derivation", {}).get("charge_state", 0)
    if model_charge != 0:
        raise ValueError("Berry tasks require a neutral model")
    input_qualification = None
    if "input_qualification" in config:
        input_qualification = check_method_configuration(model, config, site, method_path)
        if not input_qualification["input_qualified"]:
            raise ValueError(
                "ABACUS method input qualification failed: "
                + json.dumps(input_qualification["issues"], ensure_ascii=False)
            )
    elif not bool(model.metadata.get("fixture", False)):
        raise ValueError("non-fixture Berry tasks require explicit method input qualification")
    return method, AbacusExecution(**dict(execution)), _parameter_values(config), _pseudopotentials(config, site), input_qualification


def _berry_config(config: Mapping[str, Any], request: Mapping[str, Any], role: str, nspin: int) -> dict[str, Any]:
    if nspin != 1:
        raise ValueError(
            "unsupported_spin_resolved_occupations: ABACUS 3.10.1 uses one occupied-band count for both spin channels"
        )
    configured = config.get("berry", {})
    requested = request.get("berry", {})
    if configured is None:
        configured = {}
    if requested is None:
        requested = {}
    if not isinstance(configured, Mapping) or not isinstance(requested, Mapping):
        raise ValueError("method.berry and request.berry must be objects when supplied")
    merged = {str(key): value for key, value in configured.items()}
    merged.update({str(key): value for key, value in requested.items()})
    science = config.get("science")
    suffix = science.get("suffix") if isinstance(science, Mapping) else config.get("suffix")
    suffix = _text(suffix, "method.science.suffix")
    if role == "reference_scf":
        if "role" in merged and merged["role"] not in (None, role):
            raise ValueError("Berry reference request has a mismatched berry role")
        if "out_chg" in merged and int(merged["out_chg"]) != 1:
            raise ValueError("Berry reference_scf requires out_chg=1")
        if "berry_phase" in merged and int(merged["berry_phase"]) != 0:
            raise ValueError("Berry reference_scf requires berry_phase=0")
        if "symmetry" in merged and int(merged["symmetry"]) != -1:
            raise ValueError("Berry reference_scf requires symmetry=-1")
        if "init_chg" in merged and merged["init_chg"] not in (None, ""):
            raise ValueError("Berry reference_scf must not request init_chg")
        return {
            "schema": BERRY_SCHEMA,
            "role": role,
            "berry_phase": 0,
            "gdir": None,
            "symmetry": -1,
            "pw_diag_thr": None,
            "out_chg": 1,
            "init_chg": None,
            "charge_density": {"files": list(CHARGE_FILES_BY_NSPIN[nspin]), "directory": f"OUT.{suffix}"},
            "read_file_dir": None,
            "nspin": nspin,
            "lspinorb": False,
            "noncolin": False,
            "occupations": "fixed",
            "numerical_qualification": False,
            "qualification_status": "awaiting_native_scf_and_berry_qualification",
        }
    if "role" in merged and merged["role"] not in (None, role):
        raise ValueError("Berry NSCF request has a mismatched berry role")
    if "gdir" not in merged or isinstance(merged["gdir"], bool) or not isinstance(merged["gdir"], int) or merged["gdir"] not in (1, 2, 3):
        raise ValueError("Berry NSCF requires explicit gdir 1, 2, or 3")
    if "pw_diag_thr" not in merged:
        raise ValueError("Berry NSCF requires explicit pw_diag_thr")
    pw_diag_thr = float(merged["pw_diag_thr"])
    if not math.isfinite(pw_diag_thr) or pw_diag_thr <= 0.0 or pw_diag_thr > 1.0e-3:
        raise ValueError("Berry PW NSCF pw_diag_thr must be finite, positive, and <= 1e-3")
    if "symmetry" in merged and int(merged["symmetry"]) != -1:
        raise ValueError("Berry NSCF requires symmetry=-1")
    if "init_chg" in merged and str(merged["init_chg"]).lower() != "file":
        raise ValueError("Berry NSCF requires init_chg=file")
    if "berry_phase" in merged and int(merged["berry_phase"]) != 1:
        raise ValueError("Berry NSCF requires berry_phase=1")
    if "read_file_dir" in merged and str(merged["read_file_dir"]) not in (".", "./"):
        raise ValueError("Berry NSCF requires read_file_dir=./ for copied charge files")
    return {
        "schema": BERRY_SCHEMA,
        "role": role,
        "berry_phase": 1,
        "gdir": int(merged["gdir"]),
        "symmetry": -1,
        "pw_diag_thr": pw_diag_thr,
        "out_chg": 0,
        "init_chg": "file",
        "charge_density": {"files": list(CHARGE_FILES_BY_NSPIN[nspin]), "directory": "task_root"},
        "read_file_dir": "./",
        "nspin": nspin,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "numerical_qualification": False,
        "qualification_status": "awaiting_native_scf_and_berry_qualification",
    }


def _resource_request(request: Mapping[str, Any]) -> dict[str, Any]:
    value = request.get("resource_request")
    if not isinstance(value, Mapping):
        raise ValueError("request.resource_request must be an object")
    return dict(value)


def _registered_gpu_build(site: Mapping[str, Any]) -> dict[str, str]:
    """Read the site-registered isolated GPU Berry candidate.

    The site record is the authority for a candidate binary.  A method may
    select the candidate by ID, but it cannot invent a binary path or scope.
    This keeps the candidate on the ordinary SiteRunner/TaskRecord path while
    leaving the unpatched ABACUS GPU implementation unavailable.
    """

    abacus_site = site.get("abacus")
    if not isinstance(abacus_site, Mapping):
        raise ValueError("site.abacus is required for Berry execution")
    build = abacus_site.get("berry_gpu_build")
    if not isinstance(build, Mapping):
        raise ValueError("GPU Berry requires a site.abacus.berry_gpu_build registration")
    implementation_id = build.get("implementation_id")
    binary = build.get("binary")
    scope = build.get("scope")
    configured_binary = abacus_site.get("binary")
    if not isinstance(implementation_id, str) or not implementation_id.strip():
        raise ValueError("site.abacus.berry_gpu_build.implementation_id is required")
    if implementation_id.strip() != BERRY_GPU_IMPLEMENTATION_ID:
        raise ValueError(
            "site.abacus.berry_gpu_build.implementation_id is not the supported "
            f"candidate {BERRY_GPU_IMPLEMENTATION_ID!r}"
        )
    if not isinstance(binary, str) or not binary.strip():
        raise ValueError("site.abacus.berry_gpu_build.binary is required")
    if not isinstance(configured_binary, str) or not configured_binary.strip():
        raise ValueError("site.abacus.binary is required for Berry execution")
    if str(binary) != str(configured_binary):
        raise ValueError("site.abacus.berry_gpu_build.binary must equal site.abacus.binary")
    if scope != BERRY_GPU_SCOPE:
        raise ValueError(f"site.abacus.berry_gpu_build.scope must be {BERRY_GPU_SCOPE!r}")
    return {
        "implementation_id": implementation_id.strip(),
        "binary": str(binary),
        "scope": BERRY_GPU_SCOPE,
    }


def _gpu_count(resources: Mapping[str, Any]) -> int | None:
    """Return the explicit one-GPU count represented by a resource key."""

    selected: list[int] = []
    if "gpus_per_task" in resources and resources["gpus_per_task"] not in (None, ""):
        value = str(resources["gpus_per_task"]).strip()
        match = re.fullmatch(r"(?:[A-Za-z0-9_.-]+:)?([0-9]+)", value)
        if match is None:
            raise ValueError("GPU Berry gpus_per_task must name exactly one GPU")
        selected.append(int(match.group(1)))
    if "gres" in resources and resources["gres"] not in (None, ""):
        value = str(resources["gres"]).strip()
        match = re.fullmatch(r"gpu(?::[A-Za-z0-9_.-]+)?:(\d+)", value)
        if match is None:
            raise ValueError("GPU Berry gres must name exactly one GPU")
        selected.append(int(match.group(1)))
    if "gpus" in resources and resources["gpus"] not in (None, ""):
        try:
            selected.append(int(resources["gpus"]))
        except (TypeError, ValueError) as error:
            raise ValueError("GPU Berry gpus must be an integer") from error
    if not selected:
        return None
    if len(selected) != 1:
        raise ValueError("GPU Berry must use one explicit GPU resource key")
    return selected[0]


def _bind_execution_contract(
    *,
    config: Mapping[str, Any],
    site: Mapping[str, Any],
    execution: AbacusExecution,
    berry: dict[str, Any],
    resources: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the selected Berry execution and candidate when required.

    Historical GPU SCF references are allowed to retain the official binary
    path.  Candidate registration is mandatory for GPU NSCF, and optional for
    GPU SCF only when the method explicitly selects a candidate.
    """

    binary = site.get("abacus", {}).get("binary") if isinstance(site.get("abacus"), Mapping) else None
    if not isinstance(binary, str) or not binary.strip():
        raise ValueError("site.abacus.binary is required for Berry execution")
    if execution.device == "cpu":
        return berry

    configured = config.get("berry")
    selected = configured.get("implementation_id") if isinstance(configured, Mapping) else None
    is_nscf = berry.get("role") == "nscf"
    if not is_nscf and selected in (None, ""):
        # Preserve the historical official GPU SCF path (for example job50).
        berry["device"] = execution.device
        berry["binary_source"] = str(binary)
        return berry

    if not isinstance(configured, Mapping):
        raise ValueError("GPU Berry NSCF requires method.berry.implementation_id")
    build = _registered_gpu_build(site)
    implementation_id = configured.get("implementation_id")
    if implementation_id != build["implementation_id"]:
        raise ValueError("method.berry.implementation_id does not match the registered GPU Berry build")
    if resources.get("nodes", 1) != 1 or resources.get("ntasks") != 1:
        raise ValueError("GPU Berry requires nodes=1 and ntasks=1")
    if _gpu_count(resources) != 1:
        raise ValueError("GPU Berry requires one explicit GPU resource")
    berry["device"] = execution.device
    berry["kpar"] = 1
    berry["binary_source"] = str(binary)
    berry["implementation_id"] = build["implementation_id"]
    berry["gpu_build"] = dict(build)
    berry["scope"] = BERRY_GPU_SCOPE
    return berry


def _required_results(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = request.get("required_results", [])
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError("request.required_results must be a list of objects")
    return [dict(item) for item in value]


def _method_record_update(
    generated: dict[str, Any],
    *,
    config: Mapping[str, Any],
    method_path: str | Path,
    fixture: bool,
    pseudo_files: Mapping[str, str],
    input_qualification: Mapping[str, Any] | None,
    berry: Mapping[str, Any],
) -> None:
    generated.update(
        method_set=config["method_set"],
        parent_method_set=config.get("parent_method_set"),
        source_configuration=str(Path(method_path).resolve()),
        fixture=fixture,
        pseudopotential_ids=dict(config["pseudopotential_ids"]),
        pseudopotential_metadata=dict(config.get("pseudopotential_metadata", {})),
        net_charge=config.get("net_charge"),
        berry=dict(berry),
    )
    if berry.get("binary_source"):
        generated["binary_source"] = berry["binary_source"]
    if input_qualification is not None:
        generated.update(
            input_qualification=dict(input_qualification),
            pseudopotential_treatment=config.get("pseudopotential_treatment"),
            compatibility_reference=config.get("compatibility_reference"),
        )


def _run_script(
    *,
    site: Mapping[str, Any],
    pseudo_files: Mapping[str, str],
    execution: AbacusExecution,
    resources: Mapping[str, Any],
    task_id: str,
) -> str:
    launcher = site["abacus"]["mpi_launcher"]
    binary = site["abacus"]["binary"]
    cp_commands = [f"cp {shlex.quote(source)} {shlex.quote(Path(source).name)}" for source in pseudo_files.values()]
    launch = [launcher, "-launcher", "slurm", "-rmk", "slurm", "-n", str(resources["ntasks"]), "-bind-to", "core", binary]
    lines = [
        "#!/bin/bash",
        "set -e",
        *cp_commands,
        "date --iso-8601=seconds",
        "printf 'Slurm job=%s ranks=%s visible_gpus=%s\\n' \"$SLURM_JOB_ID\" \"$SLURM_NTASKS\" \"$CUDA_VISIBLE_DEVICES\"",
    ]
    if execution.device == "gpu":
        lines.append("nvidia-smi --query-gpu=index,uuid,pci.bus_id,name --format=csv > gpu-inventory.csv")
    lines.extend([shlex.join(launch), ""])
    return "\n".join(lines)


def _task_data(
    *,
    request: Mapping[str, Any],
    study: Mapping[str, Any],
    model: ModelArtifacts,
    config: Mapping[str, Any],
    method: AbacusMethod,
    method_path: str | Path,
    study_path: str | Path,
    model_path: str | Path,
    directory: Path,
    resources: Mapping[str, Any],
    berry: Mapping[str, Any],
    required_results: Sequence[Mapping[str, Any]],
    transfer_paths: Sequence[str],
    collect_paths: Sequence[str],
    calculation: str,
    input_qualification: Mapping[str, Any] | None,
) -> TaskRecord:
    task_id = _text(request.get("task_id"), "request.task_id")
    fixture = study.get("case_role") == "engineering_fixture"
    conditions = {
        "calculation_kind": "berry_polarization_reference" if calculation == "scf" else "berry_polarization_nscf",
        "lattice_temperature_K": None,
        "reference_temperature_K": 0,
        "applied_external_pressure_Pa": None,
        "cell_constraint": "fixed_cell",
        "occupations": "fixed",
        "electronic_smearing_Ry": None,
    }
    task = TaskRecord(
        {
            "task_id": task_id,
            "stage": TASK_STAGE,
            "calculation": calculation,
            "study_id": study["study_id"],
            "case_id": study["case_id"],
            "case_role": study["case_role"],
            "engine": "abacus",
            "engine_version": ABACUS_VERSION,
            "basis_type": ABACUS_BASIS_TYPE,
            "model_id": model.model_id,
            "model_version": model.version,
            "model_path": str(Path(model_path).resolve()),
            "method_set": config["method_set"],
            "fixture": fixture,
            "production_label": False,
            "production_qualification": False,
            "method_input_qualified": input_qualification is not None and input_qualification.get("input_qualified") is True,
            "study_file": str(Path(study_path).resolve()),
            "calculation_conditions": conditions,
            "required_results": [dict(item) for item in required_results],
            "depends_on": [str(item["task_id"]) for item in required_results],
            "berry": dict(berry),
            "resource_request": dict(resources),
            "runner": "slurm",
            "scheduler_job_id": None,
            "command": ["/bin/bash", "run-abacus.sh"],
            "environment_script": None,
            "transfer_paths": list(transfer_paths),
            "collect_paths": list(collect_paths),
            "status": "defined",
            "scientific_status": "not_calculated",
            "numerical_qualification": False,
            "scientific_qualification": False,
            "qualification_status": "awaiting_native_scf_and_berry_qualification",
            "structure_source": str(directory / "input.extxyz"),
        },
        directory / "task.json",
    )
    if berry.get("binary_source"):
        task.data["binary_source"] = berry["binary_source"]
    return task


def _set_environment(task: TaskRecord, site: Mapping[str, Any]) -> None:
    task.data["environment_script"] = site["abacus"]["environment_script"]


def _write_task(task: TaskRecord, *, request: Mapping[str, Any], kind: str) -> dict[str, Any]:
    task.record_event(
        "create",
        request_file=str(Path(request.get("_source_path", "")).resolve()) if request.get("_source_path") else None,
        result="native_inputs_written_not_submitted",
        berry_role=task.data["berry"]["role"],
        calculation=kind,
    )
    save_task(task)
    return task.data


def _reference_method_identity(method: Mapping[str, Any]) -> dict[str, Any]:
    parameters = method.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("reference method.json parameters are required")
    pseudopotentials = method.get("pseudopotential_ids")
    return {
        "engine": method.get("engine"),
        "engine_version": method.get("abacus_version_target", method.get("engine_version")),
        "basis_type": method.get("basis_type"),
        "dft_functional": method.get("dft_functional"),
        "ks_solver": method.get("ks_solver"),
        "nspin": method.get("nspin"),
        "lspinorb": method.get("lspinorb"),
        "noncolin": method.get("noncolin"),
        "initial_moments_muB_by_element": dict(method.get("initial_moments_muB_by_element", {})),
        "occupations": method.get("occupations"),
        "smearing_method": method.get("smearing_method"),
        "mixing_type": method.get("mixing_type"),
        "relax_method": method.get("relax_method"),
        "symmetry": method.get("symmetry"),
        "element_order": list(method.get("element_order", [])),
        "kpoints": list(method.get("kpoints", [])),
        "pseudopotential_ids": dict(pseudopotentials) if isinstance(pseudopotentials, Mapping) else pseudopotentials,
        "ecutwfc_Ry": parameters.get("ecutwfc_Ry"),
        "nbands": parameters.get("nbands"),
        "scf_nmax": parameters.get("scf_nmax"),
        "smearing_sigma_Ry": parameters.get("smearing_sigma_Ry"),
        "mixing_beta": parameters.get("mixing_beta"),
        "net_charge": method.get("net_charge"),
    }


def _candidate_method_record(config: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a method configuration into the identity fields used in task binding."""

    science = config.get("science")
    execution = config.get("execution")
    if not isinstance(science, Mapping) or not isinstance(execution, Mapping):
        raise ValueError("method science and execution objects are required")
    return {
        "engine": config.get("engine"),
        "abacus_version_target": config.get("engine_version"),
        "basis_type": config.get("basis_type"),
        "dft_functional": science.get("dft_functional"),
        "ks_solver": execution.get("ks_solver"),
        "nspin": science.get("nspin"),
        "lspinorb": science.get("lspinorb", False),
        "noncolin": science.get("noncolin", False),
        "initial_moments_muB_by_element": science.get("initial_moments_muB_by_element", {}),
        "occupations": science.get("occupations"),
        "smearing_method": science.get("smearing_method"),
        "mixing_type": science.get("mixing_type"),
        "relax_method": science.get("relax_method"),
        "symmetry": science.get("symmetry"),
        "element_order": list(config.get("element_order", [])),
        "kpoints": list(config.get("kpoints", [])),
        "pseudopotential_ids": config.get("pseudopotential_ids"),
        "parameters": config.get("parameters"),
        "net_charge": config.get("net_charge"),
    }


def _validate_native_stru_identity(directory: Path, model: ModelArtifacts, method: Mapping[str, Any]) -> None:
    map_path = directory / "STRU.atom-map.json"
    stru_path = directory / "STRU"
    if not map_path.is_file() or not stru_path.is_file():
        raise ValueError("Berry reference requires native STRU and STRU.atom-map.json")
    atom_map = _json(map_path)
    native_atoms = _read_stru(stru_path, atom_map)
    if native_atoms.arrays["atom_id"].tolist() != model.atoms.arrays["atom_id"].tolist():
        raise ValueError("native STRU atom IDs differ from the selected model")
    if native_atoms.get_chemical_symbols() != model.atoms.get_chemical_symbols():
        raise ValueError("native STRU element order differs from the selected model")
    if not np.allclose(native_atoms.cell.array, model.atoms.cell.array, rtol=0.0, atol=1.0e-10):
        raise ValueError("native STRU cell differs from the selected model")
    if not np.allclose(native_atoms.get_positions(), model.atoms.get_positions(), rtol=0.0, atol=1.0e-10):
        raise ValueError("native STRU geometry differs from the selected model")
    species_start = next((index for index, line in enumerate(stru_path.read_text(encoding="utf-8").splitlines()) if line.strip() == "ATOMIC_SPECIES"), None)
    if species_start is None:
        raise ValueError("native STRU is missing ATOMIC_SPECIES")
    raw_lines = stru_path.read_text(encoding="utf-8").splitlines()
    try:
        species_end = next(index for index in range(species_start + 1, len(raw_lines)) if raw_lines[index].strip() == "LATTICE_CONSTANT")
    except StopIteration as error:
        raise ValueError("native STRU is missing LATTICE_CONSTANT") from error
    actual_names = {}
    for line in raw_lines[species_start + 1 : species_end]:
        tokens = line.split()
        if len(tokens) >= 3:
            actual_names[str(tokens[0])] = str(tokens[2])
    expected_pseudos = method.get("pseudopotentials")
    if not isinstance(expected_pseudos, Mapping):
        raise ValueError("reference method.json pseudopotentials are required")
    for element, record in expected_pseudos.items():
        if not isinstance(record, Mapping) or not record.get("filename"):
            raise ValueError(f"reference method.json pseudopotential record is incomplete for {element}")
        if actual_names.get(str(element)) != str(record["filename"]):
            raise ValueError(f"native STRU pseudopotential filename differs for {element}")


def _validate_reference_method_config(
    method: Mapping[str, Any], method_path: str | Path | None, method_config: Mapping[str, Any] | None
) -> None:
    if method_config is None and method_path is not None:
        method_config = _json(method_path)
    if method_config is None:
        return
    candidate = _reference_method_identity(_candidate_method_record(method_config))
    observed = _reference_method_identity(method)
    for field in (
        "engine",
        "engine_version",
        "basis_type",
        "dft_functional",
        "ks_solver",
        "nspin",
        "lspinorb",
        "noncolin",
        "initial_moments_muB_by_element",
        "occupations",
        "smearing_method",
        "mixing_type",
        "relax_method",
        "symmetry",
        "element_order",
        "kpoints",
        "pseudopotential_ids",
        "ecutwfc_Ry",
        "nbands",
        "smearing_sigma_Ry",
        "mixing_beta",
        "net_charge",
    ):
        if candidate.get(field) != observed.get(field):
            raise ValueError(f"Berry reference method field {field} differs from method configuration")


def validate_berry_reference(
    reference_task_path: str | Path,
    method_path: str | Path | None = None,
    *,
    site_path: str | Path | None = None,
    method_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a completed Berry SCF reference and its native charge files.

    The function is intentionally strict: the reference must be a saved native
    Slurm ``COMPLETED``/``0:0`` task with a fixed-occupation sampled gap and
    native electronic evidence.  A claimed ``passed`` field in ``result.json``
    is never used as a substitute for the native parser.
    """

    task_file = _task_file(reference_task_path)
    directory = task_file.parent
    task = load_task(task_file)
    method = _json(directory / "method.json")
    if task.data.get("stage") != TASK_STAGE or task.data.get("calculation") != "scf":
        raise ValueError("Berry reference must be a P5 SCF task")
    if method.get("method_set") != task.data.get("method_set"):
        raise ValueError("Berry reference method identity differs from task")
    if task.data.get("engine") != "abacus" or task.data.get("engine_version") != ABACUS_VERSION:
        raise ValueError("Berry reference must target ABACUS 3.10.1")
    if task.data.get("scheduler_state") != "COMPLETED" or task.data.get("exit_code") != "0:0":
        raise ValueError("Berry reference requires saved native COMPLETED/0:0 evidence")
    berry = method.get("berry")
    if not isinstance(berry, Mapping) or berry.get("role") != "reference_scf":
        raise ValueError("reference method.json must declare berry.role=reference_scf")
    if method.get("occupations") != "fixed":
        raise ValueError("Berry reference must use fixed occupations")
    if method.get("nspin") != 1:
        raise ValueError(
            "unsupported_spin_resolved_occupations: ABACUS 3.10.1 uses one occupied-band count for both spin channels"
        )
    if method.get("lspinorb") is not False or method.get("noncolin") is not False:
        raise ValueError("Berry reference must be non-SOC collinear")
    if method.get("net_charge") != 0 or task.data.get("production_label") is not False:
        raise ValueError("Berry reference must be explicitly neutral and non-production-labeled")
    if berry.get("nspin") != 1 or berry.get("occupations") != "fixed" or berry.get("lspinorb") is not False or berry.get("noncolin") is not False:
        raise ValueError("Berry reference berry metadata differs from the fixed nspin=1 non-SOC method")
    model_path = task.data.get("model_path")
    if not model_path:
        raise ValueError("Berry reference task is missing model_path")
    model = read_model_artifacts(model_path)
    if task.data.get("model_id") != model.model_id or task.data.get("model_version") != model.version:
        raise ValueError("Berry reference task model identity differs from model_path")
    _validate_reference_method_config(method, method_path, method_config)
    if site_path is not None and method_config is None and method_path is not None:
        method_config = _json(method_path)
    if site_path is not None and method_config is not None:
        configured_pseudos = _pseudopotentials(method_config, _json(site_path))
        native_pseudos = method.get("pseudopotentials")
        if not isinstance(native_pseudos, Mapping):
            raise ValueError("reference method.json pseudopotentials are required")
        for element, filename in configured_pseudos.items():
            record = native_pseudos.get(element)
            if not isinstance(record, Mapping) or record.get("filename") != Path(filename).name:
                raise ValueError(f"Berry reference pseudopotential differs from site configuration for {element}")
    charge = berry.get("charge_density")
    if not isinstance(charge, Mapping) or not isinstance(charge.get("files"), list):
        raise ValueError("reference method.json must declare charge_density.files")
    expected_charge_files = list(CHARGE_FILES_BY_NSPIN[1])
    suffix = _text(method.get("suffix"), "reference method suffix")
    expected_charge_directory = f"OUT.{suffix}"
    if charge.get("files") != expected_charge_files or charge.get("directory") != expected_charge_directory:
        raise ValueError("Berry reference charge_density must use native OUT.<suffix>/SPIN1_CHG.cube")
    if berry.get("out_chg") != 1 or berry.get("berry_phase") != 0 or berry.get("read_file_dir") not in (None, ""):
        raise ValueError("Berry reference must declare out_chg=1 and berry_phase=0")
    _validate_native_stru_identity(directory, model, method)
    charge_paths = [directory / str(charge["directory"]) / str(name) for name in charge["files"]]
    missing_charge = [str(path) for path in charge_paths if not path.is_file()]
    if missing_charge:
        raise ValueError("Berry reference native charge files are missing: " + ", ".join(missing_charge))
    if any(path.stat().st_size <= 0 for path in charge_paths):
        raise ValueError("Berry reference native charge files must be non-empty")
    result_path = directory / "result.json"
    if not result_path.is_file():
        raise ValueError("Berry reference result.json is required alongside native evidence")
    result = _json(result_path)
    if result.get("task_id") != task.task_id or result.get("scheduler_job_id") != task.scheduler_job_id:
        raise ValueError("Berry reference result identity differs from task")
    if result.get("method_set") != task.data.get("method_set") or result.get("stage") != "scf":
        raise ValueError("Berry reference result method/stage identity differs from task")
    if result.get("scientific_status") not in ("converged", "converged_engineering_fixture"):
        raise ValueError("Berry reference result scientific_status is not an accepted converged status")
    if result.get("occupations") != "fixed" or result.get("electronic_converged") is not True:
        raise ValueError("Berry reference result must record fixed electronic convergence")
    # This parser validates the native SCF log, energy, forces, stress, atom
    # map, and method/INPUT stage.  It is deliberately independent of the
    # historical result/electronic records below.
    native = parse_abacus_outputs(directory, source_model=model, stage="scf")
    if native.electronic_converged is not True:
        raise ValueError("native Berry reference SCF did not converge electronically")
    # This reads the native OUT log, istate.info and kpoints rather than trusting
    # a hand-written result/electronic JSON record.
    electronic = read_abacus_electronic_task(directory)
    if electronic.get("occupations") != "fixed" or electronic.get("fractional_occupations_present") is not False:
        raise ValueError("native Berry reference occupations are not fixed integer occupations")
    gap = electronic.get("sampled_mesh_KS_gap_eV")
    if gap is None or not math.isfinite(float(gap)) or float(gap) <= 0.0:
        raise ValueError("native Berry reference requires a positive sampled mesh gap")
    expected_nspin = int(method["nspin"])
    if electronic.get("nspin") != expected_nspin:
        raise ValueError("native Berry reference nspin differs from method.json")
    return {
        "schema": "mlcc.abacus-berry-reference-validation.v1",
        "task_id": task.task_id,
        "task_file": str(task_file),
        "task_dir": str(directory),
        "model_id": model.model_id,
        "model_version": model.version,
        "model_path": str(Path(model_path).resolve()),
        "method_set": task.data.get("method_set"),
        "nspin": expected_nspin,
        "occupations": "fixed",
        "sampled_mesh_KS_gap_eV": float(gap),
        "electronic_source": electronic.get("source_files", {}),
        "native_scf_source": native.source_files,
        "charge_files": [str(path) for path in charge_paths],
        "native_completed": True,
        "numerical_qualification": False,
        "scientific_qualification": False,
        "qualification_status": "awaiting_native_berry_kpoint_and_branch_qualification",
    }


def create_berry_reference_task(*, study_path, model_path, method_path, site_path, request_path):
    """Materialize the neutral fixed-occupation SCF charge reference."""

    study = _json(study_path)
    config = _json(method_path)
    site = _json(site_path)
    request = _json(request_path)
    request["_source_path"] = str(Path(request_path).resolve())
    if request.get("calculation") != "scf":
        raise ValueError("Berry reference request calculation must be scf")
    if request.get("input_transformation") is not None:
        raise ValueError("Berry reference does not support a structure transformation")
    model = read_model_artifacts(model_path)
    _validate_model_study(model, study)
    method, execution, parameters, pseudo_files, input_qualification = _load_method_inputs(
        model=model, config=config, site=site, method_path=method_path
    )
    berry = _berry_config(config, request, "reference_scf", method.nspin)
    resources = _resource_request(request)
    _bind_execution_contract(
        config=config,
        site=site,
        execution=execution,
        berry=berry,
        resources=resources,
    )
    task_id = _text(request.get("task_id"), "request.task_id")
    directory = Path(site["workspace"]["local"]) / "tasks" / task_id
    directory.mkdir(parents=True, exist_ok=False)
    prepared = prepare_abacus(
        model,
        directory,
        parameters=parameters,
        method=method,
        execution=execution,
        stage="scf",
        pseudopotentials=pseudo_files,
        element_order=config["element_order"],
        kpoints=config["kpoints"],
        berry=berry,
    )
    from ase.io import write

    write(directory / "input.extxyz", model.atoms)
    generated = _json(directory / "method.json")
    _method_record_update(
        generated,
        config=config,
        method_path=method_path,
        fixture=bool(study.get("case_role") == "engineering_fixture"),
        pseudo_files=pseudo_files,
        input_qualification=input_qualification,
        berry=berry,
    )
    (directory / "method.json").write_text(json.dumps(generated, indent=2) + "\n", encoding="utf-8")
    run_script = _run_script(site=site, pseudo_files=pseudo_files, execution=execution, resources=resources, task_id=task_id)
    (directory / "run-abacus.sh").write_text(run_script, encoding="utf-8", newline="\n")
    transfer = [*prepared.files.keys(), "input.extxyz", "run-abacus.sh"]
    collect = [
        "stdout.log",
        "stderr.log",
        f"OUT.{method.suffix}",
        *[f"OUT.{method.suffix}/{name}" for name in berry["charge_density"]["files"]],
    ]
    required = _required_results(request)
    task = _task_data(
        request=request,
        study=study,
        model=model,
        config=config,
        method=method,
        method_path=method_path,
        study_path=study_path,
        model_path=model_path,
        directory=directory,
        resources=resources,
        berry=berry,
        required_results=required,
        transfer_paths=transfer,
        collect_paths=collect,
        calculation="scf",
        input_qualification=input_qualification,
    )
    _set_environment(task, site)
    return _write_task(task, request=request, kind="scf")


def create_berry_nscf_task(*, reference_task_path, method_path, site_path, request_path):
    """Materialize one Berry NSCF direction bound to a native SCF reference."""

    site = _json(site_path)
    config = _json(method_path)
    request = _json(request_path)
    request["_source_path"] = str(Path(request_path).resolve())
    if request.get("calculation") != "nscf":
        raise ValueError("Berry NSCF request calculation must be nscf")
    if request.get("input_transformation") is not None:
        raise ValueError("Berry NSCF does not support a structure transformation")
    reference = validate_berry_reference(reference_task_path, method_path, site_path=site_path)
    ref_file = Path(reference["task_file"])
    ref_task = load_task(ref_file)
    ref_method = _json(ref_file.parent / "method.json")
    study_path = ref_task.data.get("study_file")
    if not study_path:
        raise ValueError("Berry reference task is missing study_file")
    study = _json(study_path)
    model_path = ref_task.data.get("model_path")
    if not model_path:
        raise ValueError("Berry reference task is missing model_path")
    model = read_model_artifacts(model_path)
    _validate_model_study(model, study)
    method, execution, parameters, pseudo_files, input_qualification = _load_method_inputs(
        model=model, config=config, site=site, method_path=method_path
    )
    ref_identity = _reference_method_identity(ref_method)
    candidate_identity = _reference_method_identity(_candidate_method_record(config))
    # The NSCF may select a different suffix, Berry direction, and PW
    # diagonalization threshold, but its material/method/PP identity stays
    # tied to the SCF (including the explicit k mesh).
    for field in (
        "engine",
        "engine_version",
        "basis_type",
        "dft_functional",
        "ks_solver",
        "nspin",
        "lspinorb",
        "noncolin",
        "initial_moments_muB_by_element",
        "occupations",
        "smearing_method",
        "mixing_type",
        "relax_method",
        "symmetry",
        "element_order",
        "kpoints",
        "pseudopotential_ids",
        "ecutwfc_Ry",
        "nbands",
        "smearing_sigma_Ry",
        "mixing_beta",
        "net_charge",
    ):
        if candidate_identity.get(field) != ref_identity.get(field):
            raise ValueError(f"Berry NSCF method field {field} differs from the SCF reference")
    berry = _berry_config(config, request, "nscf", method.nspin)
    berry["source_reference_task_id"] = ref_task.task_id
    berry["source_reference_task_file"] = str(ref_file)
    charge_files = [Path(item).name for item in reference["charge_files"]]
    berry["charge_density"] = {
        "files": charge_files,
        "directory": "task_root",
        "read_file_dir": "./",
        "source_task_id": ref_task.task_id,
        "source_paths": list(reference["charge_files"]),
    }
    resources = _resource_request(request)
    _bind_execution_contract(
        config=config,
        site=site,
        execution=execution,
        berry=berry,
        resources=resources,
    )
    task_id = _text(request.get("task_id"), "request.task_id")
    directory = Path(site["workspace"]["local"]) / "tasks" / task_id
    directory.mkdir(parents=True, exist_ok=False)
    for source_name in reference["charge_files"]:
        source = Path(source_name)
        if not source.is_absolute():
            source = ref_file.parent / source
        shutil.copy2(source, directory / source.name)
    prepared = prepare_abacus(
        model,
        directory,
        parameters=parameters,
        method=method,
        execution=execution,
        stage="nscf",
        pseudopotentials=pseudo_files,
        element_order=config["element_order"],
        kpoints=config["kpoints"],
        berry=berry,
    )
    from ase.io import write

    write(directory / "input.extxyz", model.atoms)
    generated = _json(directory / "method.json")
    _method_record_update(
        generated,
        config=config,
        method_path=method_path,
        fixture=bool(study.get("case_role") == "engineering_fixture"),
        pseudo_files=pseudo_files,
        input_qualification=input_qualification,
        berry=berry,
    )
    (directory / "method.json").write_text(json.dumps(generated, indent=2) + "\n", encoding="utf-8")
    run_script = _run_script(site=site, pseudo_files=pseudo_files, execution=execution, resources=resources, task_id=task_id)
    (directory / "run-abacus.sh").write_text(run_script, encoding="utf-8", newline="\n")
    transfer = [*prepared.files.keys(), "input.extxyz", "run-abacus.sh", *charge_files]
    collect = ["stdout.log", "stderr.log", f"OUT.{method.suffix}"]
    required = _required_results(request)
    ref_requirement = {
        "task_id": ref_task.task_id,
        "task_file": str(ref_file),
        "result_file": ref_task.data.get("result_file", "result.json"),
        "scientific_status": _json(ref_file.parent / "result.json").get("scientific_status"),
    }
    if ref_requirement["scientific_status"] not in ("converged", "converged_engineering_fixture"):
        raise ValueError("Berry reference result scientific_status is not an accepted converged status")
    if not any(item.get("task_id") == ref_task.task_id for item in required):
        required.insert(0, ref_requirement)
    task = _task_data(
        request=request,
        study=study,
        model=model,
        config=config,
        method=method,
        method_path=method_path,
        study_path=study_path,
        model_path=model_path,
        directory=directory,
        resources=resources,
        berry=berry,
        required_results=required,
        transfer_paths=transfer,
        collect_paths=collect,
        calculation="nscf",
        input_qualification=input_qualification,
    )
    _set_environment(task, site)
    return _write_task(task, request=request, kind="nscf")

