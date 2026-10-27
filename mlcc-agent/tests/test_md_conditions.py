"""MD-01 conditions and post-processing window contract tests.

The positive input is the accepted collection produced from native job45.
Mutating temporary JSON copies exercises the contract without touching the
shared collection or starting another numerical task.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from mlcc.md_conditions import read_md_conditions


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COLLECTION = ROOT / "workspace" / "reports" / "md-series-v011-v001" / "collection.json"


def _collection_source() -> Path:
    return Path(os.environ.get("MLCC_MD_COLLECTION", str(DEFAULT_COLLECTION)))


def _copy_collection(tmp_path: Path, name: str) -> tuple[Path, dict[str, object]]:
    source = _collection_source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    target = tmp_path / f"{name}.json"
    shutil.copy2(source, target)
    return target, json.loads(target.read_text(encoding="utf-8"))


def _write_record(path: Path, record: dict[str, object]) -> None:
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _write_request(tmp_path: Path, record: dict[str, object], **overrides: object) -> Path:
    native_job = record["native_job"]
    request: dict[str, object] = {
        "schema": "mlcc.md-window-request.v1",
        "task_id": record["task_id"],
        "scheduler_job_id": native_job["scheduler_job_id"],
        "purpose": "engineering_postprocessing_selection",
        "equilibration_window": {"start_step": 0, "end_step": 40},
        "production_window": {"start_step": 50, "end_step": 100},
    }
    request.update(overrides)
    path = tmp_path / "engineering-windows.json"
    path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    return path


def test_read_md_conditions_selects_explicit_engineering_windows(tmp_path: Path) -> None:
    source = _collection_source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    source_before = source.read_text(encoding="utf-8")
    collection_path, record = _copy_collection(tmp_path, "accepted")
    request_path = _write_request(tmp_path, record)

    result = read_md_conditions(collection_path, request_path)
    assert source.read_text(encoding="utf-8") == source_before

    assert result["schema"] == "mlcc.md-conditions.v1"
    assert result["task_id"] == "p10-ni-lammps-nve100-v001"
    assert result["native_job"]["scheduler_job_id"] == "45"
    assert result["native_job"]["scheduler_state"] == "COMPLETED"
    assert result["native_job"]["exit_code"] == "0:0"
    assert result["model"]["model_id"] == "ni-abacus-engineering-relaxed"
    assert result["potential"]["potential_id"] == "Ni-u3-Foiles1986"

    conditions = result["conditions"]
    assert conditions["engine"] == "lammps"
    assert conditions["units"] == "metal"
    assert conditions["atom_style"] == "atomic"
    assert conditions["ensemble"] == "nve"
    assert conditions["timestep_ps"] == pytest.approx(0.001)
    assert conditions["timestep_fs"] == pytest.approx(1.0)
    assert conditions["temperature"]["initial_velocity_temperature_K"] == pytest.approx(300.0)
    assert conditions["temperature"]["target_temperature_K"] is None
    assert conditions["temperature"]["status"] == "initial_velocity_temperature_only"
    assert conditions["pressure"] == {"pressure_bar": None, "status": "not_declared"}

    samples = result["samples"]
    assert samples["steps"] == list(range(0, 101, 10))
    assert samples["thermo_count"] == 11
    assert samples["trajectory_count"] == 11

    windows = result["windows"]
    assert set(("equilibration_window", "production_window")) <= windows.keys()
    equilibration = windows["equilibration_window"]
    assert equilibration["status"] == "selected_for_engineering_postprocessing"
    assert equilibration["start_step"] == 0
    assert equilibration["end_step"] == 40
    assert equilibration["thermo_indices"] == [0, 1, 2, 3, 4]
    assert equilibration["trajectory_indices"] == [0, 1, 2, 3, 4]
    assert equilibration["steps"] == [0, 10, 20, 30, 40]
    assert equilibration["physical_time_ps"] == pytest.approx([0.0, 0.01, 0.02, 0.03, 0.04])
    assert equilibration["physical_time_fs"] == pytest.approx([0.0, 10.0, 20.0, 30.0, 40.0])
    assert equilibration["count"] == 5

    production = windows["production_window"]
    assert production["status"] == "selected_for_engineering_postprocessing"
    assert production["start_step"] == 50
    assert production["end_step"] == 100
    assert production["thermo_indices"] == [5, 6, 7, 8, 9, 10]
    assert production["trajectory_indices"] == [5, 6, 7, 8, 9, 10]
    assert production["steps"] == [50, 60, 70, 80, 90, 100]
    assert production["physical_time_ps"][-1] == pytest.approx(0.1)
    assert production["physical_time_fs"][-1] == pytest.approx(100.0)
    assert production["count"] == 6

    assert result["production_qualification"] is False
    assert result["sampling_equilibrium_qualified"] is False
    assert result["source"]["window_request"] == str(request_path)


def test_missing_windows_remain_unresolved(tmp_path: Path) -> None:
    collection_path, _ = _copy_collection(tmp_path, "accepted")

    result = read_md_conditions(collection_path)

    assert result["windows"]["equilibration_window"]["status"] == "unresolved_missing"
    assert result["windows"]["production_window"]["status"] == "unresolved_missing"
    assert result["windows"]["equilibration_window"]["selection"] is None
    assert result["windows"]["production_window"]["selection"] is None
    assert result["windows"]["equilibration_window"]["thermo_indices"] is None
    assert result["windows"]["production_window"]["trajectory_indices"] is None
    assert result["windows"]["equilibration_window"]["count"] is None


def test_selects_independent_thermo_and_trajectory_intervals(tmp_path: Path) -> None:
    collection_path, record = _copy_collection(tmp_path, "different-intervals")
    record["protocol"]["thermo_every"] = 20
    record["thermo"]["rows"] = record["thermo"]["rows"][::2]
    _write_record(collection_path, record)
    request_path = _write_request(
        tmp_path,
        record,
        equilibration_window={"start_step": 0, "end_step": 40},
        production_window={"start_step": 60, "end_step": 100},
    )

    result = read_md_conditions(collection_path, request_path)

    assert result["samples"]["thermo_steps"] == [0, 20, 40, 60, 80, 100]
    assert result["samples"]["trajectory_steps"] == list(range(0, 101, 10))
    equilibration = result["windows"]["equilibration_window"]
    assert equilibration["thermo_indices"] == [0, 1, 2]
    assert equilibration["trajectory_indices"] == [0, 1, 2, 3, 4]
    assert equilibration["steps"] == [0, 20, 40]


def test_rejects_collection_time_mismatch(tmp_path: Path) -> None:
    collection_path, record = _copy_collection(tmp_path, "bad-time")
    record["thermo"]["rows"][1]["physical_time_ps"] = 0.011
    _write_record(collection_path, record)

    with pytest.raises(ValueError, match="physical_time_ps"):
        read_md_conditions(collection_path)


def test_rejects_non_metal_collection_units(tmp_path: Path) -> None:
    collection_path, record = _copy_collection(tmp_path, "bad-units")
    record["units"] = "real"
    _write_record(collection_path, record)

    with pytest.raises(ValueError, match="metal/atomic"):
        read_md_conditions(collection_path)


def test_rejects_window_identity_mismatch(tmp_path: Path) -> None:
    collection_path, record = _copy_collection(tmp_path, "identity")
    request_path = _write_request(tmp_path, record, task_id="different-task")

    with pytest.raises(ValueError, match="task_id"):
        read_md_conditions(collection_path, request_path)


@pytest.mark.parametrize(
    ("equilibration", "production", "message"),
    [
        ({"start_step": -10, "end_step": 10}, {"start_step": 50, "end_step": 100}, "endpoints"),
        ({"start_step": 5, "end_step": 15}, {"start_step": 50, "end_step": 100}, "endpoints"),
        ({"start_step": 0, "end_step": 60}, {"start_step": 50, "end_step": 100}, "overlap"),
    ],
)
def test_rejects_invalid_windows(
    tmp_path: Path,
    equilibration: dict[str, int],
    production: dict[str, int],
    message: str,
) -> None:
    collection_path, record = _copy_collection(tmp_path, "bad-window")
    request_path = _write_request(
        tmp_path,
        record,
        equilibration_window=equilibration,
        production_window=production,
    )

    with pytest.raises(ValueError, match=message):
        read_md_conditions(collection_path, request_path)


def test_rejects_missing_request_window(tmp_path: Path) -> None:
    collection_path, record = _copy_collection(tmp_path, "missing-window")
    request_path = _write_request(tmp_path, record)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    del request["production_window"]
    request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="requires both"):
        read_md_conditions(collection_path, request_path)
