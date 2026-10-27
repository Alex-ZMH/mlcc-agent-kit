from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from mlcc_deepmd.handoff import collect_training  # noqa: E402


def _run(tmp_path: Path, *, last_step: int = 100, loss: str = "1.0") -> Path:
    run = tmp_path / "train-2gpu"
    run.mkdir()
    dataset_root = tmp_path / "dataset"
    system = dataset_root / "train" / "system-000"
    system.mkdir(parents=True)
    dataset = dataset_root / "dataset_manifest.json"
    dataset.write_text(
        json.dumps(
            {
                "schema": "mlcc.deepmd-dataset-manifest.v1",
                "format": "deepmd/npy",
                "engine": "abacus",
                "type_map": ["Ni"],
                "training_systems": ["train/system-000"],
                "validation_systems": [],
                "sources": [{"task_id": "ni-scf", "paths": {"task_dir": "/v100/ni-scf"}}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    input_value = {
        "model": {"type_map": ["Ni"]},
        "training": {
            "training_data": {"systems": [str(system.resolve())], "batch_size": 1},
            "numb_steps": 100,
            "seed": 20261022,
            "save_ckpt": "model.ckpt",
        },
    }
    (run / "input.json").write_text(json.dumps(input_value) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "mlcc.deepmd.training.v1",
        "status": "planned",
        "deepmd_kit_version": "3.2.0",
        "backend": "pt",
        "input_json": "input.json",
        "seed": 20261022,
        "stop_batch": 100,
        "batch": {"local_per_rank": 1, "global": 2, "world_size": 2},
        "torchrun": {"nnodes": 1, "nproc_per_node": 2},
        "dataset": {
            "training_systems": [str(system.resolve())],
            "validation_systems": [],
        },
        "training_controls": {"disp_file": "lcurve.out"},
        "logs": {"stdout": "stdout.log", "stderr": "stderr.log", "status": "training-status.json"},
        "checkpoint": {"path_or_prefix": "model.ckpt.pt"},
        "freeze": {
            "enabled": True,
            "output": "frozen_model.pth",
            "lammps_pair_style": "deepmd",
        },
    }
    (run / "training-manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    (run / "training-status.json").write_text(
        json.dumps(
            {
                "schema_version": "mlcc.deepmd.training.v1",
                "status": "completed",
                "phase": "freeze",
                "returncode": 0,
                "scheduler_job_id": "124",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "lcurve.out").write_text(
        "# step rmse\n0 2.0\n" + f"{last_step} {loss}\n", encoding="utf-8"
    )
    (run / "model.ckpt.pt").write_bytes(b"engineering checkpoint")
    (run / "frozen_model.pth").write_bytes(b"engineering fixture")
    (run / "stderr.log").write_text(
        "[DEEPMD INFO] DeePMD version: 3.2.0\n"
        "[DEEPMD INFO] Backend: PyTorch\n"
        "[DEEPMD INFO] PT Ver: v2.11.0+cu126\n"
        "[DEEPMD INFO] Build Variant: CUDA\n"
        "[DEEPMD INFO] Rank: 0/2\n"
        "[DEEPMD INFO] Computing Device: CUDA:0\n",
        encoding="utf-8",
    )
    (run / "stdout.log").write_text("", encoding="utf-8")
    return dataset


def _scheduler(run: Path) -> dict[str, object]:
    return {
        "job_id": "124",
        "state": "COMPLETED",
        "exit_code": "0:0",
        "workdir": str(run.resolve()),
    }


def _manifest(run: Path) -> dict[str, object]:
    path = run / "training-manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _input(run: Path) -> dict[str, object]:
    path = run / "input.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_collect_training_writes_complete_engineering_card(tmp_path: Path):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"

    output = collect_training(run, dataset, _scheduler(run))

    card = json.loads(output.read_text(encoding="utf-8"))
    assert output == run / "model-card.json"
    assert card["scientific_status"] == "not_qualified"
    assert card["design_assessment"] == "not_assessed"
    assert card["runtime"]["deepmd_kit_version"] == "3.2.0"
    assert "[DEEPMD INFO] Backend: PyTorch" in card["runtime"]["stderr_evidence"]
    assert "[DEEPMD INFO] Rank: 0/2" in card["runtime"]["rank_gpu_evidence"]
    assert card["backend"] == "pt"
    assert card["format"] == "pth"
    assert card["type_map"] == ["Ni"]
    assert card["checkpoint"] == "model.ckpt.pt"
    assert card["job_id"] == "124"
    assert card["batch"]["local_per_rank"] == 1
    assert card["batch"]["global"] == 2
    assert card["training"]["last_step"] == 100
    assert card["dataset_manifest"]["sources"][0]["paths"]["task_dir"] == "/v100/ni-scf"
    assert card["training_plan"]["status"] == "planned"
    assert card["execution_status"]["phase"] == "freeze"


def test_collect_training_resolves_copied_manifest_against_dataset_root(tmp_path: Path):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"
    copied_manifest = tmp_path / "task" / "dataset-manifest.json"
    copied_manifest.parent.mkdir()
    copied_manifest.write_text(dataset.read_text(encoding="utf-8"), encoding="utf-8")

    output = collect_training(
        run,
        copied_manifest,
        _scheduler(run),
        dataset_root=dataset.parent,
    )

    card = json.loads(output.read_text(encoding="utf-8"))
    assert card["dataset_manifest_path"] == str(copied_manifest.resolve())
    assert card["dataset_root"] == str(dataset.parent.resolve())


@pytest.mark.parametrize(
    ("status_change", "scheduler_change"),
    [
        ({"phase": "training"}, {}),
        ({"status": "failed"}, {}),
        ({}, {"job_id": "125"}),
        ({}, {"state": "FAILED"}),
        ({}, {"exit_code": "1:0"}),
    ],
)
def test_collect_training_rejects_nonterminal_or_mismatched_scheduler(
    tmp_path: Path, status_change: dict[str, object], scheduler_change: dict[str, object]
):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"
    status_path = run / "training-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update(status_change)
    status_path.write_text(json.dumps(status), encoding="utf-8")
    scheduler = _scheduler(run)
    scheduler.update(scheduler_change)

    with pytest.raises(ValueError):
        collect_training(run, dataset, scheduler)
    assert not (run / "model-card.json").exists()


def test_collect_training_rejects_scheduler_workdir_binding(tmp_path: Path):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"
    scheduler = _scheduler(run)
    scheduler["workdir"] = str(tmp_path / "another-run")

    with pytest.raises(ValueError, match="workdir"):
        collect_training(run, dataset, scheduler)
    assert not (run / "model-card.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda manifest, _: manifest.update({"input_json": "other-input.json"}),
        lambda manifest, _: manifest.update({"seed": 7}),
        lambda manifest, _: manifest.update({"stop_batch": 99}),
        lambda manifest, _: manifest["dataset"].update({"training_systems": ["other-system"]}),
        lambda manifest, _: manifest["dataset"].update({"validation_systems": ["validation-system"]}),
        lambda manifest, _: manifest["batch"].update({"global": 1}),
        lambda manifest, _: manifest["batch"].update({"world_size": 1}),
        lambda manifest, _: manifest["torchrun"].update({"nproc_per_node": 4}),
        lambda manifest, _: manifest["checkpoint"].update({"path_or_prefix": "other.ckpt.pt"}),
    ],
)
def test_collect_training_rejects_plan_binding_mismatch(tmp_path: Path, change):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"
    manifest = _manifest(run)
    change(manifest, run)
    _write_json(run / "training-manifest.json", manifest)

    with pytest.raises((ValueError, FileNotFoundError)):
        collect_training(run, dataset, _scheduler(run))
    assert not (run / "model-card.json").exists()


def test_collect_training_rejects_input_dataset_path_mismatch(tmp_path: Path):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"
    input_value = _input(run)
    input_value["training"]["training_data"]["systems"] = ["other-system"]
    _write_json(run / "input.json", input_value)

    with pytest.raises(ValueError, match="data split paths"):
        collect_training(run, dataset, _scheduler(run))
    assert not (run / "model-card.json").exists()


def test_collect_training_rejects_external_frozen_model(tmp_path: Path):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"
    external = tmp_path / "external-frozen.pth"
    external.write_bytes(b"not this run")
    manifest = _manifest(run)
    manifest["freeze"]["output"] = str(external)
    _write_json(run / "training-manifest.json", manifest)

    with pytest.raises(ValueError, match="outside"):
        collect_training(run, dataset, _scheduler(run))
    assert not (run / "model-card.json").exists()


def test_collect_training_rejects_missing_native_checkpoint(tmp_path: Path):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"
    (run / "model.ckpt.pt").unlink()

    with pytest.raises(FileNotFoundError):
        collect_training(run, dataset, _scheduler(run))
    assert not (run / "model-card.json").exists()


@pytest.mark.parametrize(
    ("last_step", "loss", "message"),
    [(99, "1.0", "before numb_steps"), (100, "nan", "nonfinite")],
)
def test_collect_training_rejects_incomplete_or_nonfinite_lcurve(
    tmp_path: Path, last_step: int, loss: str, message: str
):
    dataset = _run(tmp_path, last_step=last_step, loss=loss)
    run = tmp_path / "train-2gpu"
    with pytest.raises(ValueError, match=message):
        collect_training(run, dataset, _scheduler(run))


def test_collect_training_requires_the_declared_frozen_pth(tmp_path: Path):
    dataset = _run(tmp_path)
    run = tmp_path / "train-2gpu"
    (run / "frozen_model.pth").unlink()

    with pytest.raises(FileNotFoundError):
        collect_training(run, dataset, _scheduler(run))
