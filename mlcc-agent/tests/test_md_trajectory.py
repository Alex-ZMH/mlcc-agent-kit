"""MD-00 complete sequence regression against the real Slurm job45 output."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Callable

import pytest

from mlcc.md_trajectory import read_md_collection


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "workspace" / "tasks" / "p10-ni-lammps-nve100-v001"


def _real_source() -> Path:
    return Path(os.environ.get("MLCC_MD_SOURCE_TASK", str(DEFAULT_SOURCE)))


def _copy_job45(tmp_path: Path, name: str) -> Path:
    source = _real_source()
    assert source.is_dir(), f"real Slurm job45 artifact unavailable: {source}"
    target = tmp_path / name
    shutil.copytree(source, target)
    return target


def _rewrite_frame(task: Path, step: int, mutate: Callable[[list[str]], None]) -> None:
    path = task / "trajectory.lammpstrj"
    text = path.read_text(encoding="utf-8")
    marker = f"ITEM: TIMESTEP\n{step}\n"
    start = text.index(marker)
    next_start = text.find("ITEM: TIMESTEP\n", start + len(marker))
    end = len(text) if next_start < 0 else next_start
    block = text[start:end].splitlines()
    mutate(block)
    path.write_text(text[:start] + "\n".join(block) + "\n" + text[end:], encoding="utf-8")


def _remove_frame(task: Path, step: int) -> None:
    path = task / "trajectory.lammpstrj"
    text = path.read_text(encoding="utf-8")
    marker = f"ITEM: TIMESTEP\n{step}\n"
    start = text.index(marker)
    next_start = text.find("ITEM: TIMESTEP\n", start + len(marker))
    end = len(text) if next_start < 0 else next_start
    path.write_text(text[:start] + text[end:], encoding="utf-8")


def _change_frame_atom_id(block: list[str]) -> None:
    fields = block[9].split()
    fields[0] = "9"
    block[9] = " ".join(fields)


def _change_frame_atom_type(block: list[str]) -> None:
    fields = block[9].split()
    fields[1] = "2"
    block[9] = " ".join(fields)


def test_read_md_collection_real_job45() -> None:
    source = _real_source()
    assert source.is_dir(), f"real Slurm job45 artifact unavailable: {source}"
    result_path = source / "result.json"
    before = result_path.read_text(encoding="utf-8")
    collection = read_md_collection(source)
    after = result_path.read_text(encoding="utf-8")

    assert collection["schema"] == "mlcc.md-collection.v1"
    assert str(collection["native_job"]["scheduler_job_id"]) == "45"
    assert collection["native_job"]["scheduler_state"] == "COMPLETED"
    assert collection["native_job"]["exit_code"] == "0:0"
    assert collection["model"]["model_id"] == "ni-abacus-engineering-relaxed"
    assert collection["potential"]["potential_id"] == "Ni-u3-Foiles1986"
    assert [row["step"] for row in collection["thermo"]["rows"]] == list(range(0, 101, 10))
    assert [frame["step"] for frame in collection["trajectory"]["frames"]] == list(range(0, 101, 10))
    assert collection["trajectory"]["frames"][-1]["physical_time_ps"] == pytest.approx(0.1)
    assert collection["legacy_final_result"]["step"] == 100
    assert collection["trajectory"]["image_flags"] == "missing"
    assert collection["trajectory"]["velocities"] == "missing"
    assert collection["initialization"]["velocity_seed"] == 20261022
    assert "velocity_seed" not in collection["missing_evidence"]
    assert collection["production_qualification"] is False
    assert collection["sampling_equilibrium_qualified"] is False
    assert "msd" not in collection
    assert "diffusion" not in collection
    assert before == after


def test_rejects_missing_intermediate_trajectory_frame(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "missing-frame")
    _remove_frame(task, 50)
    with pytest.raises(ValueError, match="trajectory sequence"):
        read_md_collection(task)


def test_rejects_duplicate_trajectory_step(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "duplicate-step")
    _rewrite_frame(task, 20, lambda block: block.__setitem__(1, "10"))
    with pytest.raises(ValueError, match="trajectory steps"):
        read_md_collection(task)


def test_rejects_trajectory_atom_identity_corruption(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "bad-atom-id")
    _rewrite_frame(task, 20, _change_frame_atom_id)
    with pytest.raises(ValueError, match="atom IDs"):
        read_md_collection(task)


def test_rejects_trajectory_atom_type_corruption(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "bad-atom-type")
    _rewrite_frame(task, 20, _change_frame_atom_type)
    with pytest.raises(ValueError, match="atom type"):
        read_md_collection(task)


def test_rejects_trajectory_box_change(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "bad-box")
    _rewrite_frame(
        task,
        20,
        lambda block: block.__setitem__(5, block[5].replace("3.5200000000785536", "3.6200000000785536", 1)),
    )
    with pytest.raises(ValueError, match="box"):
        read_md_collection(task)


def test_rejects_deleted_initial_trajectory_frame(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "deleted-initial-frame")
    _remove_frame(task, 0)
    with pytest.raises(ValueError, match="initial step"):
        read_md_collection(task)


def test_rejects_missing_intermediate_thermo_row(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "missing-thermo")
    path = task / "log.lammps"
    lines = path.read_text(encoding="utf-8").splitlines()
    removed = False
    kept: list[str] = []
    for line in lines:
        fields = line.split()
        if not removed and len(fields) == 6 and fields[0] == "20":
            removed = True
            continue
        kept.append(line)
    assert removed
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="thermo sequence"):
        read_md_collection(task)


def test_rejects_extra_timestep_command(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "extra-timestep")
    path = task / "in.lammps"
    path.write_text(path.read_text(encoding="utf-8") + "timestep 0.002\n", encoding="utf-8")
    with pytest.raises(ValueError, match="timestep"):
        read_md_collection(task)


def test_rejects_reset_timestep_command(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "reset-timestep")
    path = task / "in.lammps"
    path.write_text(path.read_text(encoding="utf-8") + "reset_timestep 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reset_timestep"):
        read_md_collection(task)


def test_rejects_velocity_seed_conflict(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "bad-velocity-seed")
    path = task / "in.lammps"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("20261022", "20261023", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="velocity seed"):
        read_md_collection(task)


def test_rejects_task_result_job_mismatch(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "job-mismatch")
    path = task / "result.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["scheduler_job_id"] = "999"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="job IDs"):
        read_md_collection(task)


def test_rejects_failed_scheduler_records_even_when_consistent(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path, "failed-status")
    task_path = task / "task.json"
    task_record = json.loads(task_path.read_text(encoding="utf-8"))
    task_record["status"] = "FAILED"
    task_record["scheduler_state"] = "FAILED"
    task_record["exit_code"] = "1:0"
    task_path.write_text(json.dumps(task_record, indent=2) + "\n", encoding="utf-8")
    result_path = task / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["scheduler_state"] = "FAILED"
    result["exit_code"] = "1:0"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_md_collection(task)
