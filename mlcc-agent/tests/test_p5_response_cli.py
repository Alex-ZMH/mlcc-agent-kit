"""Focused dispatcher checks for the P5 response/phonon CLI branches."""

from __future__ import annotations

import json
from pathlib import Path

import mlcc.cli as cli


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def test_born_charges_dispatches_model_and_response_paths(tmp_path: Path, monkeypatch) -> None:
    model = tmp_path / "model"
    responses = [tmp_path / "response-a.json", tmp_path / "response-b.json"]
    output = tmp_path / "born.json"
    for path in responses:
        _write_json(path, {"dispatcher": "response"})
    calls: dict[str, object] = {}

    def fake_aggregate(model_path, response_paths):
        calls.update(model=model_path, responses=response_paths)
        return {"schema": "dispatcher-born", "status": "written"}

    monkeypatch.setattr(cli, "aggregate_born_columns", fake_aggregate)

    assert cli.main(
        [
            "born-charges",
            "--model",
            str(model),
            "--responses",
            *(str(path) for path in responses),
            "--output",
            str(output),
        ]
    ) == 0
    assert calls == {"model": model, "responses": responses}
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == "dispatcher-born"


def test_ionic_dielectric_passes_missing_gamma_as_none(tmp_path: Path, monkeypatch) -> None:
    born = _write_json(tmp_path / "born.json", {"schema": "born"})
    thresholds = _write_json(tmp_path / "thresholds.json", {"threshold": 1.0})
    output = tmp_path / "ionic.json"
    calls: dict[str, object] = {}

    def fake_ionic(born_value, gamma_value, *, thresholds):
        calls.update(born=born_value, gamma=gamma_value, thresholds=thresholds)
        return {"schema": "dispatcher-ionic", "status": "unresolved"}

    monkeypatch.setattr(cli, "calculate_ionic_dielectric", fake_ionic)

    assert cli.main(
        [
            "ionic-dielectric",
            "--born",
            str(born),
            "--thresholds",
            str(thresholds),
            "--output",
            str(output),
        ]
    ) == 0
    assert calls == {
        "born": {"schema": "born"},
        "gamma": None,
        "thresholds": {"threshold": 1.0},
    }


def test_dielectric_passes_optional_electronic_and_ionic_as_none(tmp_path: Path, monkeypatch) -> None:
    born = _write_json(tmp_path / "born.json", {"schema": "born"})
    output = tmp_path / "dielectric.json"
    calls: dict[str, object] = {}

    def fake_combine(born_value, electronic_value, ionic_value):
        calls.update(born=born_value, electronic=electronic_value, ionic=ionic_value)
        return {"schema": "dispatcher-dielectric", "status": "unresolved"}

    monkeypatch.setattr(cli, "combine_dielectric_contributions", fake_combine)

    assert cli.main(
        [
            "dielectric",
            "--born",
            str(born),
            "--output",
            str(output),
        ]
    ) == 0
    assert calls == {"born": {"schema": "born"}, "electronic": None, "ionic": None}


def test_phonon_gamma_passes_named_request_contract(tmp_path: Path, monkeypatch) -> None:
    request = _write_json(
        tmp_path / "gamma-request.json",
        {
            "harmonic_result_path": "harmonic.json",
            "plan_path": "plan.json",
            "parent": {"study_id": "study"},
            "method_identity": {"method_set": "method"},
            "source_binding": {"source_mode": "native"},
            "geometry_tolerance_angstrom": 1.0e-8,
            "mass_tolerance_amu": 1.0e-8,
            "volume_tolerance_A3": 1.0e-7,
            "dynamical_imag_tolerance": 1.0e-10,
        },
    )
    output = tmp_path / "gamma.json"
    calls: dict[str, object] = {}

    def fake_gamma(harmonic_path, plan_path, **kwargs):
        calls.update(harmonic=harmonic_path, plan=plan_path, kwargs=kwargs)
        return {"schema": "dispatcher-gamma", "status": "written"}

    monkeypatch.setattr(cli, "compute_gamma_fixed_cell_hessian", fake_gamma)

    assert cli.main(
        ["phonon-gamma", "--request", str(request), "--output", str(output)]
    ) == 0
    assert calls == {
        "harmonic": "harmonic.json",
        "plan": "plan.json",
        "kwargs": {
            "parent": {"study_id": "study"},
            "method_identity": {"method_set": "method"},
            "source_binding": {"source_mode": "native"},
            "geometry_tolerance_angstrom": 1.0e-8,
            "mass_tolerance_amu": 1.0e-8,
            "volume_tolerance_A3": 1.0e-7,
            "dynamical_imag_tolerance": 1.0e-10,
            "output_path": None,
        },
    }
