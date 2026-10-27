"""Collect one completed DeePMD engineering run for the system handoff.

The collector only consumes the files written by the selected training run.
It does not discover another run, invoke DeePMD, import torch, or judge the
scientific quality of the resulting potential.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _resolve_path(value: str | Path, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _require_inside(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} is outside the current run directory: {path}") from error


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a list of non-empty paths")
    return list(value)


def _resolved_systems(value: Any, base: Path, label: str) -> list[str]:
    return [str(_resolve_path(item, base)) for item in _string_list(value, label)]


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _input_validation_systems(training: Mapping[str, Any]) -> list[str]:
    validation = training.get("validation_data")
    if validation is None:
        return []
    if not isinstance(validation, Mapping):
        raise ValueError("input.json training.validation_data must be an object or null")
    return _string_list(validation.get("systems", []), "input.json validation systems")


def _lcurve(path: Path, target_step: int) -> tuple[int, int]:
    rows: list[tuple[int, list[float]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        fields = text.split()
        try:
            step_value = float(fields[0])
            step = int(step_value)
        except (IndexError, OverflowError, ValueError) as error:
            raise ValueError(f"invalid lcurve row: {path}") from error
        if not math.isfinite(step_value) or step_value != step:
            raise ValueError(f"lcurve step must be a finite integer: {path}")
        try:
            losses = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise ValueError(f"invalid lcurve loss: {path}") from error
        if not losses or not all(math.isfinite(value) for value in losses):
            raise ValueError(f"lcurve contains a nonfinite loss: {path}")
        rows.append((step, losses))
    if not rows:
        raise ValueError(f"lcurve has no data rows: {path}")
    last_step = rows[-1][0]
    if last_step < target_step:
        raise ValueError(f"lcurve stops at step {last_step}, before numb_steps {target_step}")
    return len(rows), last_step


def _frozen_path(workdir: Path, manifest: Mapping[str, Any]) -> Path:
    freeze = manifest.get("freeze")
    if not isinstance(freeze, Mapping) or freeze.get("enabled") is not True:
        raise ValueError("training manifest does not enable freezing")
    output = freeze.get("output")
    if not isinstance(output, str) or not output:
        raise ValueError("training manifest has no freeze output")
    frozen = _resolve_path(output, workdir)
    if frozen.suffix.lower() != ".pth":
        raise ValueError(f"freeze output is not a .pth file: {output}")
    _require_inside(frozen, workdir, "freeze output")
    if not frozen.is_file():
        raise FileNotFoundError(frozen)
    return frozen


def _scheduler(
    scheduler_record: Mapping[str, Any], status: Mapping[str, Any], run_dir: Path
) -> dict[str, Any]:
    job_id = scheduler_record["job_id"]
    state = scheduler_record["state"]
    exit_code = scheduler_record["exit_code"]
    workdir = scheduler_record["workdir"]
    status_job_id = status["scheduler_job_id"]
    if job_id in (None, "") or status_job_id in (None, ""):
        raise ValueError("training and scheduler records require a job id")
    if str(job_id) != str(status_job_id):
        raise ValueError("scheduler job id does not match training status")
    if state != "COMPLETED":
        raise ValueError(f"scheduler job is not COMPLETED: {state}")
    if exit_code not in (0, "0", "0:0"):
        raise ValueError(f"scheduler job did not exit successfully: {exit_code}")
    if not isinstance(workdir, str) or not workdir:
        raise ValueError("scheduler record requires workdir")
    if Path(workdir).expanduser().resolve() != run_dir:
        raise ValueError("scheduler workdir does not match the current run directory")
    record = dict(scheduler_record)
    record["job_id"] = str(job_id)
    return record


def _checkpoint_path(
    run_dir: Path, input_path: Path, training: Mapping[str, Any], manifest: Mapping[str, Any]
) -> tuple[str, Path]:
    checkpoint = manifest["checkpoint"]
    if not isinstance(checkpoint, Mapping):
        raise ValueError("training manifest checkpoint must be an object")
    checkpoint_ref = checkpoint["path_or_prefix"]
    if not isinstance(checkpoint_ref, str) or not checkpoint_ref:
        raise ValueError("training manifest has no checkpoint")
    save_ckpt = training["save_ckpt"]
    if not isinstance(save_ckpt, str) or not save_ckpt:
        raise ValueError("input.json training.save_ckpt must be a non-empty path prefix")
    expected_ref = save_ckpt if save_ckpt.lower().endswith(".pt") else save_ckpt + ".pt"
    checkpoint_path = _resolve_path(checkpoint_ref, run_dir)
    expected_path = _resolve_path(expected_ref, input_path.parent)
    if checkpoint_path != expected_path:
        raise ValueError("training manifest checkpoint is not the native PT save_ckpt path")
    _require_inside(checkpoint_path, run_dir, "checkpoint")
    if not checkpoint_path.is_file():
        raise FileNotFoundError(checkpoint_path)
    return checkpoint_ref, checkpoint_path


def _runtime_evidence(
    run_dir: Path, manifest: Mapping[str, Any]
) -> tuple[Path, list[str], list[str]]:
    logs = manifest["logs"]
    if not isinstance(logs, Mapping):
        raise ValueError("training manifest logs must be an object")
    stderr_ref = logs["stderr"]
    if not isinstance(stderr_ref, str) or not stderr_ref:
        raise ValueError("training manifest has no stderr log")
    stderr_path = _resolve_path(stderr_ref, run_dir)
    _require_inside(stderr_path, run_dir, "stderr log")
    raw_lines = stderr_path.read_text(encoding="utf-8").splitlines()
    terms = (
        "DeePMD version:",
        "Installed to:",
        "Source:",
        "Source Commit:",
        "Build Variant:",
        "Backend:",
        "PT Ver:",
        "Built with PT",
        "Computing Device:",
        "Visible GPU Count:",
        "CUDA",
    )
    evidence = [line for line in raw_lines if "DEEPMD INFO" in line and any(term in line for term in terms)]
    if not evidence:
        raise ValueError(f"stderr has no DeePMD/PT/CUDA runtime evidence: {stderr_path}")
    rank_gpu_terms = (
        "Rank:",
        "Computing Device:",
        "Device Name:",
        "Visible GPU Count:",
        "CUDA_VISIBLE_DEVICES:",
        "PT Ver:",
    )
    rank_gpu_evidence = [line for line in raw_lines if any(term in line for term in rank_gpu_terms)]
    return stderr_path, evidence, rank_gpu_evidence


def _bind_input_and_dataset(
    input_path: Path,
    input_value: Mapping[str, Any],
    manifest: Mapping[str, Any],
    dataset: Mapping[str, Any],
    dataset_root: Path,
) -> None:
    manifest_input = manifest["input_json"]
    if not isinstance(manifest_input, str) or not manifest_input:
        raise ValueError("training manifest has no input_json")
    if _resolve_path(manifest_input, input_path.parent) != input_path:
        raise ValueError("training manifest input_json does not match the current input.json")

    training = input_value["training"]
    if not isinstance(training, Mapping):
        raise ValueError("input.json training must be an object")
    training_data = training["training_data"]
    if not isinstance(training_data, Mapping):
        raise ValueError("input.json training.training_data must be an object")
    plan_dataset = manifest["dataset"]
    if not isinstance(plan_dataset, Mapping):
        raise ValueError("training manifest dataset must be an object")

    input_train = _resolved_systems(
        training_data["systems"], input_path.parent, "input.json training systems"
    )
    input_validation = _resolved_systems(
        _input_validation_systems(training), input_path.parent, "input.json validation systems"
    )
    plan_train = _resolved_systems(
        plan_dataset["training_systems"], input_path.parent, "training manifest training systems"
    )
    plan_validation = _resolved_systems(
        plan_dataset["validation_systems"], input_path.parent, "training manifest validation systems"
    )
    dataset_train = _resolved_systems(
        dataset["training_systems"], dataset_root, "dataset manifest training systems"
    )
    dataset_validation = _resolved_systems(
        dataset["validation_systems"], dataset_root, "dataset manifest validation systems"
    )
    if input_train != plan_train or input_validation != plan_validation:
        raise ValueError("training input and manifest data split paths differ")
    if input_train != dataset_train or input_validation != dataset_validation:
        raise ValueError("training input is not bound to the declared dataset manifest")

    manifest_seed = manifest["seed"]
    if isinstance(manifest_seed, bool) or not isinstance(manifest_seed, int):
        raise ValueError("training manifest seed must be an integer")
    _positive_int(manifest["stop_batch"], "training manifest stop_batch")
    if manifest_seed != training["seed"]:
        raise ValueError("training manifest seed does not match input.json")
    if manifest["stop_batch"] != training["numb_steps"]:
        raise ValueError("training manifest stop_batch does not match input.json numb_steps")


def collect_training(
    workdir: str | Path,
    dataset_manifest: str | Path,
    scheduler_record: Mapping[str, Any],
    *,
    dataset_root: str | Path | None = None,
) -> Path:
    """Write the model card for one explicitly identified completed run."""

    run_dir = Path(workdir).expanduser().resolve()
    if not isinstance(scheduler_record, Mapping):
        raise TypeError("scheduler_record must be a mapping")

    status_path = run_dir / "training-status.json"
    input_path = run_dir / "input.json"
    manifest_path = run_dir / "training-manifest.json"
    lcurve_path = run_dir / "lcurve.out"
    status = _json_file(status_path)
    input_value = _json_file(input_path)
    manifest = _json_file(manifest_path)
    dataset_path = Path(dataset_manifest).expanduser().resolve()
    dataset = _json_file(dataset_path)
    data_root = (
        Path(dataset_root).expanduser().resolve()
        if dataset_root is not None
        else dataset_path.parent
    )

    if status.get("status") != "completed" or status.get("phase") != "freeze":
        raise ValueError("training status is not completed freeze")
    if status.get("returncode") != 0:
        raise ValueError(f"training freeze returncode is not zero: {status.get('returncode')}")

    training = input_value["training"]
    if not isinstance(training, Mapping):
        raise ValueError("input.json training must be an object")
    target_step = _positive_int(training["numb_steps"], "input.json training.numb_steps")
    seed = training["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("input.json training.seed must be an integer")
    model = input_value["model"]
    if not isinstance(model, Mapping) or not isinstance(model.get("type_map"), list):
        raise ValueError("input.json model.type_map must be a list")
    type_map = model["type_map"]
    if not type_map or not all(isinstance(item, str) and item for item in type_map):
        raise ValueError("input.json model.type_map must contain non-empty strings")
    if dataset.get("type_map") is not None and dataset["type_map"] != type_map:
        raise ValueError("dataset type_map disagrees with input type_map")

    _bind_input_and_dataset(input_path, input_value, manifest, dataset, data_root)

    training_data = training["training_data"]
    if not isinstance(training_data, Mapping):
        raise ValueError("input.json training.training_data must be an object")
    input_batch = _positive_int(training_data["batch_size"], "input.json local batch")
    batch = manifest["batch"]
    if not isinstance(batch, Mapping):
        raise ValueError("training manifest batch must be an object")
    local_batch = _positive_int(batch["local_per_rank"], "training manifest local batch")
    global_batch = _positive_int(batch["global"], "training manifest global batch")
    world_size = _positive_int(batch["world_size"], "training manifest world size")
    if local_batch != input_batch:
        raise ValueError("training manifest local batch does not match input.json")
    if global_batch != local_batch * world_size:
        raise ValueError("training manifest global batch does not match local batch and world size")
    torchrun = manifest["torchrun"]
    if not isinstance(torchrun, Mapping) or torchrun["nproc_per_node"] != world_size:
        raise ValueError("training manifest world size does not match torchrun nproc_per_node")

    runtime_version = manifest["deepmd_kit_version"]
    backend = manifest["backend"]
    if not isinstance(runtime_version, str) or not runtime_version:
        raise ValueError("training manifest has no DeePMD runtime version")
    if backend != "pt":
        raise ValueError(f"unsupported DeePMD backend: {backend}")
    checkpoint, checkpoint_path = _checkpoint_path(run_dir, input_path, training, manifest)

    controls = manifest["training_controls"]
    if not isinstance(controls, Mapping):
        raise ValueError("training manifest training_controls must be an object")
    disp_file = controls["disp_file"]
    if not isinstance(disp_file, str) or _resolve_path(disp_file, run_dir) != lcurve_path:
        raise ValueError("training manifest disp_file does not match lcurve.out")
    logs = manifest["logs"]
    if not isinstance(logs, Mapping):
        raise ValueError("training manifest logs must be an object")
    status_ref = logs["status"]
    if not isinstance(status_ref, str) or _resolve_path(status_ref, run_dir) != status_path:
        raise ValueError("training manifest status log does not match training-status.json")

    frozen = _frozen_path(run_dir, manifest)
    stderr_path, stderr_evidence, rank_gpu_evidence = _runtime_evidence(run_dir, manifest)
    rows, last_step = _lcurve(lcurve_path, target_step)
    scheduler = _scheduler(scheduler_record, status, run_dir)

    card = {
        "schema_version": "mlcc.deepmd.model-card.v1",
        "status": "engineering_handoff",
        "scientific_status": "not_qualified",
        "design_assessment": "not_assessed",
        "engine": "deepmd",
        "backend": backend,
        "format": "pth",
        "runtime": {
            "deepmd_kit_version": runtime_version,
            "stderr_path": str(stderr_path),
            "stderr_evidence": stderr_evidence,
            "rank_gpu_evidence": rank_gpu_evidence,
        },
        "type_map": list(type_map),
        "input_path": str(input_path),
        "input": input_value,
        "dataset_manifest_path": str(dataset_path),
        "dataset_root": str(data_root),
        "dataset_manifest": dataset,
        "dataset_source_paths": dataset.get("sources"),
        "checkpoint": checkpoint,
        "checkpoint_path": str(checkpoint_path),
        "frozen_model": str(frozen),
        "resources": manifest.get("resources"),
        "scheduler": scheduler,
        "job_id": scheduler["job_id"],
        "batch": {
            "local_per_rank": local_batch,
            "global": global_batch,
            "world_size": world_size,
        },
        "training": {
            "seed": training["seed"],
            "numb_steps": target_step,
            "lcurve_path": str(lcurve_path),
            "lcurve_rows": rows,
            "last_step": last_step,
        },
        "training_plan": manifest,
        "execution_status": status,
    }
    output = run_dir / "model-card.json"
    output.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
