"""Glue checks for the saved Born/Gamma mode-response public path.

The records in this file are mathematical fixtures only.  They exercise the
request-path resolution and saved-product binding; they are not material
evidence and do not call a native engine.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from test_dielectric_modes import _born as _mode_born
from test_dielectric_modes import _context as _mode_context
from test_dielectric_modes import _gamma as _mode_gamma
from test_dielectric_modes import _ionic as _mode_ionic


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _study() -> dict:
    return {
        "schema": "mlcc.study.v1",
        "study_id": "mode-study",
        "case_id": "mode-case",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": "mode-model",
            "version": "v001",
            "path": "/model",
            "fixture": True,
        },
    }


def _source_records() -> tuple[dict, dict, dict]:
    """Return valid P5-shaped math records with explicit source bindings."""
    born = _mode_born()
    gamma = _mode_gamma()
    ionic = _mode_ionic(None, status="unresolved", reasons=["ionic_fixture_unresolved"])

    born["source_mode"] = "software_math_only"
    born["sources"] = [{"source_mode": "software_math_only", "reference": "born.json"}]
    born["source"] = {
        "source_mode": "software_math_only",
        "record": "born.json",
    }

    gamma["matrix_eV_per_A2"] = [[0.0] * 6 for _ in range(6)]
    gamma["source"] = {
        "source_mode": "software_math_only",
        "harmonic_result": "gamma.json",
    }
    gamma["source_mode"] = "software_math_only"
    gamma["response_scope"] = "full_cell_fixed_cell"

    ionic["source_mode"] = "software_math_only"
    ionic["response_scope"] = "full_cell_fixed_cell"
    ionic["born_source"] = {
        "schema": born["schema"],
        "sources": copy.deepcopy(born["sources"]),
    }
    ionic["gamma_source"] = copy.deepcopy(gamma["source"])
    return born, gamma, ionic


def _inputs(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "relative-inputs"
    study_path = _write(root / "study.json", _study())
    born, gamma, ionic = _source_records()
    born_path = _write(root / "born.json", born)
    gamma_path = _write(root / "gamma.json", gamma)
    ionic_path = _write(root / "ionic.json", ionic)

    # Source records point to the actual saved fixture files, while the
    # request deliberately contains only relative names.
    born["source"]["record"] = str(born_path.resolve())
    born["sources"][0]["reference"] = str(born_path.resolve())
    gamma["source"]["harmonic_result"] = str(gamma_path.resolve())
    ionic["born_source"] = {
        "schema": born["schema"],
        "sources": copy.deepcopy(born["sources"]),
    }
    ionic["gamma_source"] = copy.deepcopy(gamma["source"])
    _write(born_path, born)
    _write(gamma_path, gamma)
    _write(ionic_path, ionic)
    request_path = _write(
        root / "request.json",
        {
            "schema": "mlcc.dielectric-modes-request.v1",
            "study": "study.json",
            "born": "born.json",
            "gamma": "gamma.json",
            "ionic": "ionic.json",
            "displacement_gauge": "euclidean_translation_free",
        },
    )
    return {
        "root": root,
        "study": study_path,
        "born": born_path,
        "gamma": gamma_path,
        "ionic": ionic_path,
        "request": request_path,
    }


def _saved_product(paths: dict[str, Path]) -> dict:
    context = _mode_context()
    study = json.loads(paths["study"].read_text(encoding="utf-8"))
    return {
        "schema": "mlcc.dielectric-mode-response.v1",
        "operation": "saved_gamma_mode_resolved_ionic_dielectric_response",
        "status": "unresolved",
        "unresolved_reasons": ["ionic_fixture_unresolved"],
        "context": context,
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": study["case_role"],
        "model_refs": copy.deepcopy(study["model"]),
        "displacement_gauge": "euclidean_translation_free",
        "analysis_scheduler_job_id": None,
        "native_jobs": {"born": [], "gamma": []},
        "source_refs": [str(paths[name].resolve()) for name in ("born", "gamma", "ionic")],
        "source_files": {
            "request": str(paths["request"].resolve()),
            "study": str(paths["study"].resolve()),
            "born": str(paths["born"].resolve()),
            "gamma": str(paths["gamma"].resolve()),
            "ionic": str(paths["ionic"].resolve()),
        },
    }


def test_cli_resolves_relative_sources_and_delivers_saved_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mlcc.cli import main
    import mlcc.born_affine as born_affine
    import mlcc.cli as cli
    import mlcc.dielectric_response as dielectric_response
    import mlcc.gamma_processing as gamma_processing
    import numpy as np

    def forbidden(*args, **kwargs):
        raise AssertionError("saved-mode analysis must not use an old native/calculation entry point")

    # The new request consumes saved Born/Gamma/ionic records and the saved
    # mode basis.  These guards make a regression to the old P5 recombination,
    # native readers, or a fresh eigensolve fail at the public CLI boundary.
    for module, name in (
        (cli, "calculate_ionic_dielectric"),
        (dielectric_response, "calculate_ionic_dielectric"),
        (dielectric_response, "_calculate_ionic_dielectric"),
        (dielectric_response, "read_native_born_family"),
        (dielectric_response, "read_native_gamma_force"),
        (born_affine, "consume_native_born_review"),
        (gamma_processing, "process_native_gamma"),
        (gamma_processing, "import_saved_gamma"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(np.linalg, "eigh", forbidden)
    monkeypatch.setattr(np.linalg, "solve", forbidden)

    paths = _inputs(tmp_path)
    product_path = tmp_path / "outputs" / "product.json"
    assert main(
        [
            "dielectric-modes",
            "--request",
            str(paths["request"]),
            "--output",
            str(product_path),
        ]
    ) == 0
    product = json.loads(product_path.read_text(encoding="utf-8"))
    assert product["schema"] == "mlcc.dielectric-mode-response.v1"
    assert product["study_id"] == "mode-study"
    assert product["case_id"] == "mode-case"
    assert product["model_refs"] == _study()["model"]
    assert product["displacement_gauge"] == "euclidean_translation_free"
    for name in ("request", "study", "born", "gamma", "ionic"):
        assert Path(product["source_files"][name]).resolve() == paths[name].resolve()
    assert set(product["native_jobs"]) == {"born", "gamma"}

    delivery_path = tmp_path / "outputs" / "delivery.json"
    assert main(
        [
            "deliver-properties",
            "--study",
            str(paths["study"]),
            "--dielectric-modes",
            str(product_path),
            "--output",
            str(delivery_path),
        ]
    ) == 0
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    assert delivery["schema"] == "mlcc.dielectric-mode-delivery.v1"
    assert delivery["responses"]["mode_resolved_ionic_response"] == product
    assert delivery["original_source_files"] == product["source_files"]
    assert delivery["source_refs"] == product["source_refs"]
    assert delivery["analysis_scheduler_job_id"] == product["analysis_scheduler_job_id"]


@pytest.mark.parametrize("mismatch", ["context", "ionic_source", "study"])
def test_request_rejects_context_source_or_study_mismatch(
    tmp_path: Path, mismatch: str
) -> None:
    from mlcc.dielectric_modes import analyze_dielectric_modes_request

    paths = _inputs(tmp_path)
    if mismatch == "context":
        gamma = json.loads(paths["gamma"].read_text(encoding="utf-8"))
        gamma["volume_A3"] = 65.0
        _write(paths["gamma"], gamma)
    elif mismatch == "ionic_source":
        ionic = json.loads(paths["ionic"].read_text(encoding="utf-8"))
        ionic["born_source"]["sources"][0]["reference"] = str(tmp_path / "wrong-born.json")
        _write(paths["ionic"], ionic)
    else:
        study = json.loads(paths["study"].read_text(encoding="utf-8"))
        study["study_id"] = "different-study"
        _write(paths["study"], study)

    with pytest.raises(ValueError):
        analyze_dielectric_modes_request(paths["request"])


def test_saved_delivery_does_not_recompute_or_read_native_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path)
    product_path = _write(tmp_path / "saved-product.json", _saved_product(paths))

    def forbidden(*args, **kwargs):
        raise AssertionError("saved dielectric-mode delivery must not recompute or read native sources")

    import mlcc.dielectric_modes as dielectric_modes
    import mlcc.dielectric_response as dielectric_response
    import mlcc.gamma_processing as gamma_processing
    import mlcc.property_delivery as property_delivery

    monkeypatch.setattr(dielectric_modes, "calculate_dielectric_modes", forbidden)
    monkeypatch.setattr(dielectric_response, "read_native_born_family", forbidden)
    monkeypatch.setattr(dielectric_response, "read_native_gamma_force", forbidden)
    monkeypatch.setattr(gamma_processing, "process_native_gamma", forbidden)
    monkeypatch.setattr(gamma_processing, "import_saved_gamma", forbidden)
    monkeypatch.setattr(property_delivery, "_p5_native_born", forbidden)
    monkeypatch.setattr(property_delivery, "_p5_native_gamma_jobs", forbidden)

    # Delivery is a saved-product consumer.  The original input records are
    # intentionally absent at this point; only Study and product may be read.
    for name in ("born", "gamma", "ionic"):
        paths[name].unlink()

    from mlcc.property_delivery import deliver_dielectric_modes

    delivery = deliver_dielectric_modes(paths["study"], product_path)
    saved = json.loads(product_path.read_text(encoding="utf-8"))
    assert delivery["responses"]["mode_resolved_ionic_response"] == saved
    assert delivery["status"] == saved["status"]
    assert delivery["native_jobs"] == saved["native_jobs"]
    assert delivery["original_source_files"] == saved["source_files"]

