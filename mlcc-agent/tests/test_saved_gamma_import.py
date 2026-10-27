"""Three broken-binding checks over the saved job518 Gamma products.

The actual positive import is exercised once by the same-Study consumer.
All input preparation and checks run in its v100 Slurm allocation.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

import mlcc.gamma_processing as gamma_processing


REPORT = Path(os.environ.get(
    "MLCC_BTO_GAMMA_REPORT",
    "/home/v100/projects/mlcc/workspace/reports/bto-native-dielectric-v001/gamma-consumer",
))


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _request(tmp_path: Path) -> dict:
    spec = importlib.util.spec_from_file_location(
        "bto_saved_gamma_normalizer", REPORT / "normalize-saved-gamma.py",
    )
    normalizer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(normalizer)
    return normalizer.normalize_saved_gamma(
        REPORT / "saved-gamma-import-template-v001.json", tmp_path,
        {"runner": "slurm", "task_id": "saved-gamma-import-negative-check",
         "scheduler_job_id": os.environ["SLURM_JOB_ID"]},
    )


def _forbid_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("saved Gamma import must not recompute Gamma processing")

    monkeypatch.setattr(gamma_processing, "process_gamma_matrix", forbidden)
    monkeypatch.setattr(gamma_processing, "process_native_gamma", forbidden)
    for name in ("eig", "eigh", "eigvals", "eigvalsh"):
        monkeypatch.setattr(gamma_processing.np.linalg, name, forbidden)


def test_saved_import_rejects_raw_matrix_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(tmp_path)
    raw_path = Path(request["native_raw_product"])
    raw = _read(raw_path)
    raw["raw_hessian_eV_A2"][0][0] += 1.0
    _write(raw_path, raw)
    request_path = _write(tmp_path / "raw-mismatch-request.json", request)
    _forbid_processing(monkeypatch)

    with pytest.raises(ValueError, match=r"(?i)(raw.*matrix|matrix.*raw)"):
        gamma_processing.import_saved_gamma(request_path)


def test_saved_import_rejects_mass_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(tmp_path)
    request["masses_amu"][0] += 1.0
    request_path = _write(tmp_path / "mass-mismatch-request.json", request)
    _forbid_processing(monkeypatch)

    with pytest.raises(ValueError, match=r"(?i)mass"):
        gamma_processing.import_saved_gamma(request_path)


def test_saved_import_rejects_processing_source_binding_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    # Mutate a temporary scheduler snapshot, never the original job518 record.
    scheduler_path = Path(request["processing_scheduler"])
    scheduler = scheduler_path.read_text(encoding="utf-8")
    bad_scheduler = tmp_path / "wrong-processing-job.txt"
    bad_scheduler.write_text(scheduler.replace("JobId=518 ", "JobId=519 ", 1), encoding="utf-8")
    request["processing_scheduler"] = str(bad_scheduler)
    request_path = _write(tmp_path / "source-mismatch-request.json", request)
    _forbid_processing(monkeypatch)

    with pytest.raises(ValueError, match=r"(?i)(processing.*source|scheduler.*JobId)"):
        gamma_processing.import_saved_gamma(request_path)
