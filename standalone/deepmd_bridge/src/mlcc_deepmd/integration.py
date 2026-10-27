"""Thin TaskRecord producer for the existing MLCC Slurm lifecycle.

Call only after standalone interface acceptance. This adapter adds no
scheduler and does not enable or replace a released MLCC bundle.
"""
from dataclasses import replace
import json
from pathlib import Path
import shutil

from mlcc.tasks import TaskRecord, load_task, save_task

from .training import DeepMDTrainingConfig, write_sbatch_script


def create_training_task(workspace: str | Path, task_id: str, config: DeepMDTrainingConfig,
                         input_file: str | Path, dataset_manifest: str | Path,
                         interface_acceptance: str | Path, *, account: str,
                         dataset_remote_root: str) -> TaskRecord:
    """Stage an explicit training task, ready for SiteRunner prepare/submit."""
    accepted = json.loads(Path(interface_acceptance).read_text(encoding="utf-8"))
    if accepted["status"] != "passed":
        raise ValueError("standalone DeePMD/LAMMPS interface must pass before system integration")
    data = json.loads(Path(dataset_manifest).read_text(encoding="utf-8"))
    input_data = json.loads(Path(input_file).read_text(encoding="utf-8"))
    if data["engine"] != "abacus" or data["type_map"] != input_data["model"]["type_map"]:
        raise ValueError("training input and ABACUS dataset type maps differ")
    expected_systems = [dataset_remote_root.rstrip("/") + "/" + p for p in data["training_systems"]]
    if input_data["training"]["training_data"]["systems"] != expected_systems:
        raise ValueError("training input is not bound to the declared remote ABACUS dataset")
    expected_validation = [dataset_remote_root.rstrip("/") + "/" + p for p in data["validation_systems"]]
    if (list(config.training_systems) != expected_systems
            or list(config.validation_systems) != expected_validation
            or input_data["training"].get("validation_data", {}).get("systems", []) != expected_validation):
        raise ValueError("training plan and native data split paths differ")
    if (input_data["training"]["seed"] != config.seed
            or input_data["training"]["numb_steps"] != config.stop_batch
            or input_data["training"]["training_data"]["batch_size"] != config.local_batch_size):
        raise ValueError("training configuration differs from the native input")
    # Keep the first system adapter's on-disk contract explicit.
    if (str(config.frozen_model) != "frozen_model.pth" or str(config.status_file) != "training-status.json"
            or str(config.manifest_file) != "training-manifest.json"
            or str(config.stdout_log) != "stdout.log" or str(config.stderr_log) != "stderr.log"):
        raise ValueError("system adapter requires the declared standard output filenames")
    local_dir = Path(workspace) / "tasks" / task_id
    local_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(input_file, local_dir / "input.json")
    shutil.copyfile(dataset_manifest, local_dir / "dataset-manifest.json")
    shutil.copyfile(interface_acceptance, local_dir / "standalone-interface-acceptance.json")
    config = replace(config, input_json="input.json")
    write_sbatch_script(config, local_dir / "deepmd-train.sbatch")
    task = TaskRecord({
        "task_id": task_id, "stage": "P9", "engine": "deepmd",
        "engine_version": config.deepmd_kit_version, "method_set": data["method_set"],
        "fixture": True, "production_qualification": False,
        "scientific_status": "not_qualified", "design_assessment": "not_assessed",
        "runner": "slurm", "status": "created", "scheduler_job_id": None,
        "command": ["bash", "deepmd-train.sbatch"],
        "local_workdir": str(local_dir.resolve()), "remote_workdir": str(config.workdir),
        "resource_request": {**config.resource_request(), "account": account},
        "transfer_paths": ["input.json", "dataset-manifest.json", "standalone-interface-acceptance.json",
                           "deepmd-train.sbatch", "training-manifest.json"],
        "collect_paths": ["input.json", "out.json", "lcurve.out", "stdout.log", "stderr.log",
                          "training-status.json", "training-manifest.json", "frozen_model.pth"],
        "dataset_manifest": "dataset-manifest.json",
        "model_handoff": {"status": "pending", "model_card": "model-card.json",
                          "frozen_model": "frozen_model.pth"},
        "dataset_location": {"mode": "existing_remote_dataset", "root": dataset_remote_root},
        "source_engine": "abacus", "source_method_set": data["method_set"],
        "source_task_ids": [source["task_id"] for source in data["sources"]],
        "depends_on": [source["task_id"] for source in data["sources"]],
        "source_models": [{"model_id": source["model_id"], "version": source["model_version"]} for source in data["sources"]],
        "source_scheduler_job_ids":
            [source["task_provenance"]["scheduler_job_id"] for source in data["sources"]],
        "integration_scope": "engineering training producer through existing MLCC Slurm lifecycle",
    }, local_dir / "task.json")
    task.record_event("create_deepmd_training", standalone_acceptance=str(interface_acceptance))
    save_task(task)
    return task


def finalize_training_task(task_file: str | Path, scheduler_record: dict) -> TaskRecord:
    """Collect a remote run and register its model card on its existing task.

    Run this domain collection step in Slurm after querying the native training
    job. SiteRunner's file collection can then retrieve the declared model card.
    """
    from .handoff import collect_training

    task = load_task(task_file)
    directory = Path(task_file).resolve().parent
    if task.data["engine"] != "deepmd" or task.scheduler_job_id != str(scheduler_record["job_id"]):
        raise ValueError("training task and native scheduler identity differ")
    if Path(task.data["remote_workdir"]).resolve() != directory:
        raise ValueError("model handoff must run in the task's declared remote directory")
    card_path = collect_training(directory, directory / task.data["dataset_manifest"], scheduler_record,
                                 dataset_root=task.data["dataset_location"]["root"])
    card = json.loads(card_path.read_text(encoding="utf-8"))
    task.set(
        status=scheduler_record["state"], scheduler_state=scheduler_record["state"],
        exit_code=scheduler_record["exit_code"],
        model_handoff={"status": "engineering_handoff", "model_card": card_path.name,
                       "frozen_model": Path(card["frozen_model"]).name, "training_job_id": card["job_id"]},
        scientific_status="not_qualified", production_qualification=False,
        design_assessment="not_assessed",
    )
    if card_path.name not in task.data["collect_paths"]:
        task.data["collect_paths"].append(card_path.name)
    task.record_event("collect_deepmd_model", model_card=card_path.name, scheduler_job_id=card["job_id"])
    save_task(task)
    return task
