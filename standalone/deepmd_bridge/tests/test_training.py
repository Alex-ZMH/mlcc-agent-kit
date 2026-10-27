from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from mlcc_deepmd.training import (  # noqa: E402
    DEEPMD_KIT_VERSION,
    DeepMDTrainingConfig,
    TrainingConfigError,
    build_freeze_command,
    build_sbatch_script,
    build_torchrun_command,
    count_training_frames,
    make_training_plan,
    prepare_training_input,
    record_native_result,
    write_sbatch_script,
    write_training_input,
)


def _system(root: Path, name: str, frames: int) -> Path:
    path = root / name / "set.000"
    path.mkdir(parents=True)
    np.save(path / "coord.npy", np.zeros((frames, 6), dtype=float))
    np.save(path / "energy.npy", np.zeros((frames,), dtype=float))
    return path.parent


def _input(root: Path, *, frames: int = 8, validation: list[str] | None = None) -> Path:
    train = _system(root, "train", frames)
    value = {
        "model": {"type_map": ["Ca", "Zr", "O"]},
        "training": {
            "training_data": {
                "systems": [train.name],
                "batch_size": 2,
            },
            "seed": 17,
            "numb_steps": 12,
            "disp_freq": 3,
            "save_freq": 12,
            "save_ckpt": "model.ckpt",
        },
    }
    if validation is not None:
        value["training"]["validation_data"] = {"systems": validation, "batch_size": 1}
    path = root / "input.json"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def test_from_input_json_records_frame_gate_batch_and_torchrun(tmp_path: Path):
    input_path = _input(tmp_path, frames=8)
    config = DeepMDTrainingConfig.from_input_json(
        input_path,
        workdir="/home/v100/tasks/deepmd",
        nproc_per_node=4,
    )

    assert config.training_frame_count == 8
    assert config.local_batch_size == 2
    assert config.global_batch_size == 8
    assert config.seed == 17
    assert config.stop_batch == 12
    assert config.deepmd_kit_version == DEEPMD_KIT_VERSION == "3.2.0"
    assert build_torchrun_command(config) == (
        "torchrun",
        "--standalone",
        "--nnodes=1",
        "--nproc-per-node=4",
        "--no-python",
        "dp",
        "--pt",
        "train",
        input_path.as_posix(),
    )


@pytest.mark.parametrize("workers", (1, 2, 4))
def test_supported_gpu_counts_emit_matching_gres_and_rank_count(tmp_path: Path, workers: int):
    input_path = _input(tmp_path, frames=workers)
    config = DeepMDTrainingConfig.from_input_json(
        input_path,
        workdir="/home/v100/tasks/deepmd",
        nproc_per_node=workers,
    )
    script = build_sbatch_script(config)
    assert f"#SBATCH --gres=gpu:v100:{workers}" in script
    assert f"--nproc-per-node={workers}" in script
    assert f"expected {workers} visible GPUs" in script
    assert f"global_batch={2 * workers}" in script
    assert "--pt train" in script
    assert "--pt freeze" in script
    assert "no CPU fallback is allowed" in script


def test_ddp_sampler_records_replicated_samples_for_fewer_frames(tmp_path: Path):
    input_path = _input(tmp_path, frames=1)
    config = DeepMDTrainingConfig.from_input_json(
        input_path,
        workdir="/home/v100/tasks/deepmd",
        nproc_per_node=4,
    )
    assert config.replicated_samples is True
    manifest = config.manifest()
    assert manifest["dataset"]["minimum_frames_required"] == 1
    assert manifest["ddp_sampling"] == {
        "sampler": "torch.utils.data.DistributedSampler",
        "drop_last": False,
        "padding": "repeat_indices_to_equalize_rank_lengths",
        "replicated_samples": True,
        "replication_is_engineering_only": True,
    }
    assert "replicated_samples=true" in build_sbatch_script(config)


def test_engineering_single_system_without_validation_is_allowed(tmp_path: Path):
    input_path = _input(tmp_path, frames=2)
    config = DeepMDTrainingConfig.from_input_json(input_path, workdir="/home/v100/tasks/deepmd", nproc_per_node=2)
    assert config.validation_systems == ()
    assert config.manifest()["dataset"]["validation_is_independent"] is False
    assert config.manifest()["scientific_status"] == "not_assessed"


def test_validation_system_must_be_a_separate_path(tmp_path: Path):
    train = _system(tmp_path, "train", 4)
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            {
                "training": {
                    "training_data": {"systems": [train.name], "batch_size": 1},
                    "validation_data": {"systems": [train.name], "batch_size": 1},
                    "seed": 1,
                    "numb_steps": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TrainingConfigError, match="separate paths"):
        DeepMDTrainingConfig.from_input_json(path, workdir="/home/v100/tasks/deepmd", nproc_per_node=2)


def test_invalid_seed_batch_and_worker_values_are_rejected(tmp_path: Path):
    input_path = _input(tmp_path, frames=4)
    value = json.loads(input_path.read_text(encoding="utf-8"))
    value["training"]["seed"] = True
    input_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(TrainingConfigError, match="training.seed"):
        DeepMDTrainingConfig.from_input_json(input_path, workdir="/home/v100/tasks/deepmd", nproc_per_node=2)
    with pytest.raises(TrainingConfigError, match="nproc_per_node"):
        DeepMDTrainingConfig(
            input_json=input_path,
            workdir="/home/v100/tasks/deepmd",
            nproc_per_node=3,
            local_batch_size=1,
            seed=1,
        )


def test_sbatch_keeps_native_errors_and_freezes_after_training(tmp_path: Path):
    input_path = _input(tmp_path, frames=2)
    config = DeepMDTrainingConfig.from_input_json(
        input_path,
        workdir="/home/v100/tasks/deepmd",
        nproc_per_node=2,
        environment_script="/home/v100/env/deepmd-3.2.0.sh",
        environment={"DP_TEST_FLAG": "engineering"},
    )
    script = build_sbatch_script(config)
    assert "set -euo pipefail" in script
    assert "source /home/v100/env/deepmd-3.2.0.sh" in script
    assert "export DP_TEST_FLAG=engineering" in script
    assert "write_status failed training \"$rc\"" in script
    assert "write_status failed freeze \"$rc\"" in script
    assert script.index("--pt train") < script.index("--pt freeze")
    assert "retry" not in script.lower()


def test_manifest_resource_request_and_native_failure_record(tmp_path: Path):
    input_path = _input(tmp_path, frames=4)
    config = DeepMDTrainingConfig.from_input_json(
        input_path,
        workdir=tmp_path,
        nproc_per_node=2,
        mem_mib=8192,
        time="00:10:00",
    )
    plan = make_training_plan(config)
    assert plan["resource_request"] == {
        "nodes": 1,
        "partition": "gpu",
        "ntasks": 1,
        "cpus_per_task": 8,
        "gres": "gpu:v100:2",
        "time": "00:10:00",
        "job_name": "mlcc-deepmd-train",
        "stdout_log": "stdout.log",
        "stderr_log": "stderr.log",
        "mem_mib": 8192,
    }
    assert plan["batch"] == {"local_per_rank": 2, "global": 4}
    assert build_freeze_command(config) == ("dp", "--pt", "freeze", "-c", "model.ckpt.pt", "-o", "frozen_model")

    script_path = write_sbatch_script(config)
    assert script_path == tmp_path / "deepmd-train.sbatch"
    manifest_path = tmp_path / "training-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "planned"
    assert manifest["batch"] == {"local_per_rank": 2, "global": 4, "world_size": 2}
    failed = record_native_result(
        manifest_path,
        phase="training",
        command=build_torchrun_command(config),
        returncode=7,
        stdout="native stdout",
        stderr="native training error",
    )
    assert failed["status"] == "failed"
    assert failed["native_error"]["returncode"] == 7
    assert failed["native_error"]["stderr"] == "native training error"
    assert failed["scientific_status"] == "not_assessed"


def test_mapping_is_explicit_and_site_runner_compatible(tmp_path: Path):
    input_path = _input(tmp_path, frames=4)
    config = DeepMDTrainingConfig.from_mapping(
        {
            "input_json": input_path.as_posix(),
            "workdir": "/home/v100/tasks/deepmd",
            "nproc_per_node": 4,
            "local_batch_size": 1,
            "seed": 99,
            "training_frame_count": 4,
            "resource_request": {
                "partition": "gpu",
                "gres": "gpu:v100:4",
                "cpus_per_task": 16,
                "mem_mib": 12288,
                "time": "00:20:00",
            },
        }
    )
    assert config.global_batch_size == 4
    assert config.resource_request()["gres"] == "gpu:v100:4"
    assert config.resource_request()["partition"] == "gpu"


def test_prepare_and_write_input_use_canonical_v32_schema(tmp_path: Path):
    value = prepare_training_input(systems=("scf", "relax"))
    assert value["model"]["type_map"] == ["Ni"]
    assert value["model"]["descriptor"] == {
        "type": "se_e2_a",
        "sel": [128],
        "rcut": 4.0,
        "rcut_smth": 3.5,
        "neuron": [8, 16, 32],
        "axis_neuron": 4,
        "precision": "float64",
    }
    assert value["model"]["fitting_net"] == {
        "neuron": [32, 32],
        "precision": "float64",
    }
    assert value["training"] == {
        "training_data": {"systems": ["scf", "relax"], "batch_size": 1},
        "numb_steps": 100,
        "seed": 20261022,
        "disp_file": "lcurve.out",
        "disp_freq": 10,
        "save_freq": 100,
        "save_ckpt": "model.ckpt",
    }
    assert value["loss"]["start_pref_v"] > 0
    train = _system(tmp_path, "train", 2)
    input_path = write_training_input(tmp_path / "input.json", systems=(train.name,))
    assert json.loads(input_path.read_text(encoding="utf-8")) == prepare_training_input(systems=(train.name,))
    config = DeepMDTrainingConfig.from_input_json(
        input_path,
        workdir=tmp_path,
        nproc_per_node=2,
    )
    assert config.local_batch_size == 1
    assert config.stop_batch == 100
    assert config.disp_freq == 10
    assert config.save_freq == 100

