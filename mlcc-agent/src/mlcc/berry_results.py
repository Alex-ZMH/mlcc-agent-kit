"""Bind native Berry observations to their completed Slurm and SCF tasks."""
from __future__ import annotations

import json
from pathlib import Path

from .berry import parse_berry_outputs
from .berry_tasks import validate_berry_reference
from .modeling import read_model_artifacts
from .tasks import load_task, save_task


def read_berry_task(task_path):
    """Read and validate one native Berry task without changing it."""

    task_file = Path(task_path).expanduser().resolve()
    if task_file.is_dir():
        task_file = task_file / "task.json"
    task = load_task(task_file)
    directory = task_file.parent
    data = task.data
    if (data["engine"], data["engine_version"], data["stage"], data["calculation"]) != (
        "abacus", "3.10.1", "P5", "nscf"
    ):
        raise ValueError("Berry parser requires an ABACUS 3.10.1 P5 NSCF task")
    if not task.scheduler_job_id or data["scheduler_state"] != "COMPLETED" or data["exit_code"] != "0:0":
        raise ValueError("Berry parsing requires a saved native Slurm job and COMPLETED/0:0")
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    if data["berry"] != method["berry"] or method["berry"]["role"] != "nscf":
        raise ValueError("Berry task and native method protocol differ")
    for task_key, method_key in (("model_id", "model_id"), ("model_version", "version"), ("method_set", "method_set")):
        if data[task_key] != method[method_key]:
            raise ValueError(f"Berry task and method {task_key} differ")
    protocol = method["berry"]
    reference_path = Path(protocol["source_reference_task_file"])
    reference = validate_berry_reference(reference_path)
    if reference["task_id"] != protocol["source_reference_task_id"]:
        raise ValueError("Berry reference task identity differs from the NSCF protocol")
    reference_task = load_task(reference_path)
    for key in ("study_id", "case_id", "case_role", "model_id", "model_version"):
        if data[key] != reference_task.data[key]:
            raise ValueError(f"Berry NSCF and SCF reference {key} differ")
    if Path(data["model_path"]).resolve() != Path(reference["model_path"]).resolve():
        raise ValueError("Berry NSCF and SCF reference model paths differ")
    reference_method = json.loads((reference_path.parent / "method.json").read_text(encoding="utf-8"))
    for key in ("engine", "abacus_version_target", "basis_type", "dft_functional", "nspin",
                "lspinorb", "noncolin", "occupations", "element_order", "parameters",
                "initial_moments_muB_by_element", "pseudopotential_ids",
                "pseudopotential_metadata", "pseudopotential_treatment", "net_charge"):
        if method[key] != reference_method[key]:
            raise ValueError(f"Berry NSCF and SCF reference physical method {key} differ")
    charge = protocol["charge_density"]
    sources = [Path(value).resolve() for value in charge["source_paths"]]
    if sources != [Path(value).resolve() for value in reference["charge_files"]]:
        raise ValueError("Berry charge source paths differ from the validated SCF reference")
    if len(charge["files"]) != len(sources):
        raise ValueError("Berry staged and source charge file counts differ")
    staged_files = []
    for relative, source in zip(charge["files"], sources, strict=True):
        staged = directory / relative
        if staged.resolve() == source or directory not in staged.resolve().parents:
            raise ValueError("Berry charge must be an independent staged task input")
        if staged.read_bytes() != source.read_bytes():
            raise ValueError("Berry staged charge differs from its SCF source")
        staged_files.append(staged)
    model = read_model_artifacts(data["model_path"])
    expected = {**protocol, "reference_task_id": protocol["source_reference_task_id"]}
    result = parse_berry_outputs(directory, source_model=model, expected=expected)
    result.update(
        task_id=task.task_id, scheduler_job_id=task.scheduler_job_id,
        fixture=data["fixture"], production_label=False,
        reference_scf_converged=True, reference_scf_status="validated_native_reference",
        reference_scf_validation=reference,
        design_assessment="not_assessed", kpoint_qualification="smoke_only",
    )
    for index, path in enumerate(staged_files):
        result["source_files"][f"staged_charge_{index}"] = str(path)
    return result


def parse_berry_task(task_path):
    """Parse one NSCF observation, preserving unqualified branch semantics."""
    task_file = Path(task_path).expanduser().resolve()
    if task_file.is_dir():
        task_file = task_file / "task.json"
    task = load_task(task_file)
    directory = task_file.parent
    result = read_berry_task(task_path)
    result_path = directory / "result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    task.set(scientific_status=result["scientific_status"], result_file=str(result_path),
             scientific_qualification=False, numerical_qualification=False, production_qualification=False)
    task.record_event("parse_berry", result_file=str(result_path), scientific_status=result["scientific_status"])
    save_task(task)
    return result
