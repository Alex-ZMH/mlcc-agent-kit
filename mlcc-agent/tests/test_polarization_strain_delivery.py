"""Focused Study/CLI checks for saved polarization--strain delivery.

The records in this file are explicit ``software_contract_only`` fixtures.
They exercise the saved-result binding and public routing only; they do not
stand in for native Berry/SCF evidence or a material qualification.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

import mlcc.cli as cli
from mlcc.cli import build_parser
from mlcc.property_delivery import deliver_polarization_strain


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _study(
    path: Path,
    *,
    study_id: str = "czo-parent-study",
    model_id: str = "czo-parent-model",
    model_path: Path | None = None,
) -> Path:
    model = model_path or path.parent / "parent-model"
    model.mkdir(parents=True, exist_ok=True)
    return _write_json(
        path,
        {
            "study_id": study_id,
            "model": {
                "model_id": model_id,
                "version": "v001",
                "path": str(model.resolve()),
            },
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )


def _strain_result(path: Path, study_path: Path) -> Path:
    study = json.loads(study_path.read_text(encoding="utf-8"))
    declared_model = Path(study["model"]["path"])
    parent_model = (
        declared_model
        if declared_model.is_absolute()
        else study_path.parent / declared_model
    ).resolve()
    source_root = path.parent / "saved-strain-sources"
    source_root.mkdir(parents=True, exist_ok=True)
    manifest_path = source_root / "response-manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")

    result = {
        "schema": "mlcc.polarization-strain.v1",
        "response_id": "software-czo-strain-v001",
        "manifest_path": str(manifest_path.resolve()),
        "request_path": str((source_root / "request.json").resolve()),
        "parent": {
            "study_id": study["study_id"],
            "study_file": str(study_path.resolve()),
            "model_id": study["model"]["model_id"],
            "model_version": study["model"]["version"],
            "model_path": str(parent_model.resolve()),
        },
        "mechanical_boundary": "clamped_ion_fixed_fractional",
        "voigt_order": ["xx", "yy", "zz", "yz", "xz", "xy"],
        "engineering_shear": True,
        "reference_lattice_angstrom": [
            [4.0, 0.0, 0.0],
            [0.0, 4.0, 0.0],
            [0.0, 0.0, 4.0],
        ],
        "reference_volume_A3": 64.0,
        "points": [
            {
                "point_id": "xx-minus",
                "voigt_component": "xx",
                "strain": -0.01,
                "strain_voigt": [-0.01, 0.0, 0.0, 0.0, 0.0, 0.0],
                "model_path": str((source_root / "xx-minus-model").resolve()),
                "study_path": str((source_root / "xx-minus-study.json").resolve()),
                "scf_task_path": str((source_root / "xx-minus-task.json").resolve()),
                "nscf_tasks": [],
            },
            {
                "point_id": "xx-plus",
                "voigt_component": "xx",
                "strain": 0.01,
                "strain_voigt": [0.01, 0.0, 0.0, 0.0, 0.0, 0.0],
                "model_path": str((source_root / "xx-plus-model").resolve()),
                "study_path": str((source_root / "xx-plus-study.json").resolve()),
                "scf_task_path": str((source_root / "xx-plus-task.json").resolve()),
                "nscf_tasks": [],
            },
            {
                "point_id": "yy-minus",
                "voigt_component": "yy",
                "strain": -0.01,
                "strain_voigt": [0.0, -0.01, 0.0, 0.0, 0.0, 0.0],
                "model_path": str((source_root / "yy-minus-model").resolve()),
                "study_path": str((source_root / "yy-minus-study.json").resolve()),
                "scf_task_path": str((source_root / "yy-minus-task.json").resolve()),
                "nscf_tasks": [],
            },
            {
                "point_id": "yy-plus",
                "voigt_component": "yy",
                "strain": 0.01,
                "strain_voigt": [0.0, 0.01, 0.0, 0.0, 0.0, 0.0],
                "model_path": str((source_root / "yy-plus-model").resolve()),
                "study_path": str((source_root / "yy-plus-study.json").resolve()),
                "scf_task_path": str((source_root / "yy-plus-task.json").resolve()),
                "nscf_tasks": [],
            },
        ],
        "pairs": [
            {
                "pair_id": "xx-h",
                "voigt_component": "xx",
                "minus_point_id": "xx-minus",
                "plus_point_id": "xx-plus",
                "amplitude": 0.01,
                "reduced_slopes_by_gdir": {"1": 0.1, "2": 0.2, "3": 0.3},
                "proper_e_C_per_m2": [0.11, 0.22, 0.33],
                "improper_dP_ds_C_per_m2": [0.44, 0.55, 0.66],
                "missing_directions": [],
                "missing_branches": [],
                "sources": [
                    {"point_id": "xx-minus", "gdir": 1, "result_file": "saved-minus.json"},
                    {"point_id": "xx-plus", "gdir": 1, "result_file": "saved-plus.json"},
                ],
                "units": {
                    "proper_e": "C/m^2",
                    "improper_dP_ds": "C/m^2",
                },
            },
            {
                "pair_id": "yy-h",
                "voigt_component": "yy",
                "minus_point_id": "yy-minus",
                "plus_point_id": "yy-plus",
                "amplitude": 0.01,
                "reduced_slopes_by_gdir": {"1": 0.1, "2": None, "3": None},
                "proper_e_C_per_m2": None,
                "improper_dP_ds_C_per_m2": None,
                "missing_directions": [2, 3],
                "missing_branches": ["yy-minus:gdir2"],
                "sources": [
                    {"point_id": "yy-minus", "gdir": 1, "result_file": "saved-minus.json"},
                    {"point_id": "yy-plus", "gdir": 1, "result_file": "saved-plus.json"},
                ],
                "units": {
                    "proper_e": "C/m^2",
                    "improper_dP_ds": "C/m^2",
                },
            }
        ],
        "native_jobs": [],
        "missing": ["yy:gdir2", "yy:gdir3", "yy:branch"],
        "status": "unresolved_missing_sources",
        "evidence_kind": "software_contract_only",
        "scientific_qualification": False,
        "production_qualification": False,
        "full_tensor_qualified": False,
        "relaxed_ion_response": None,
        "d_coefficient": None,
        "electrostriction": None,
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    return _write_json(path, result)


def _fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **functions: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    for function_name, function in functions.items():
        setattr(module, function_name, function)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_delivery_preserves_contract_values_nulls_and_saved_provenance(tmp_path: Path) -> None:
    study_path = _study(tmp_path / "study.json")
    result_path = _strain_result(tmp_path / "strain-response.json", study_path)
    saved = json.loads(result_path.read_text(encoding="utf-8"))

    delivered = deliver_polarization_strain(study_path, result_path)

    assert delivered["schema"] == "mlcc.polarization-strain-delivery.v1"
    assert delivered["result_file"] == str(result_path.resolve())
    assert delivered["result"] == saved
    for field in (
        "response_id",
        "parent",
        "mechanical_boundary",
        "voigt_order",
        "engineering_shear",
        "reference_lattice_angstrom",
        "reference_volume_A3",
        "points",
        "pairs",
        "native_jobs",
        "missing",
        "status",
        "evidence_kind",
    ):
        assert delivered[field] == saved[field]
    assert delivered["pairs"][0]["proper_e_C_per_m2"] == [0.11, 0.22, 0.33]
    assert delivered["pairs"][0]["improper_dP_ds_C_per_m2"] == [0.44, 0.55, 0.66]
    assert delivered["pairs"][1]["proper_e_C_per_m2"] is None
    assert delivered["pairs"][1]["improper_dP_ds_C_per_m2"] is None
    assert delivered["pairs"][1]["reduced_slopes_by_gdir"] == {"1": 0.1, "2": None, "3": None}
    assert delivered["native_jobs"] == []
    assert delivered["scientific_qualification"] is False
    assert delivered["production_qualification"] is False
    assert delivered["full_tensor_qualified"] is False


def test_delivery_without_targets_is_not_assessed(tmp_path: Path) -> None:
    study_path = _study(tmp_path / "study.json")
    result_path = _strain_result(tmp_path / "strain-response.json", study_path)

    delivered = deliver_polarization_strain(study_path, result_path)

    assert delivered["design_assessment"] == "not_assessed"
    assert delivered["design_assessment_detail"]["design_assessment"] == "not_assessed"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("study_id", "polarization-strain parent differs"),
        ("model_id", "polarization-strain parent differs"),
        ("model_path", "polarization-strain parent model path"),
    ],
)
def test_delivery_rejects_wrong_study_model_or_explicit_model_path(
    tmp_path: Path, mutation: str, match: str,
) -> None:
    study_path = _study(tmp_path / "study.json")
    result_path = _strain_result(tmp_path / "strain-response.json", study_path)
    mutated = json.loads(study_path.read_text(encoding="utf-8"))
    if mutation == "study_id":
        mutated["study_id"] = "other-study"
    elif mutation == "model_id":
        mutated["model"]["model_id"] = "other-model"
    else:
        other_model = tmp_path / "other-model-path"
        other_model.mkdir()
        mutated["model"]["path"] = str(other_model.resolve())
    wrong_study = _write_json(study_path, mutated)

    with pytest.raises(ValueError, match=match):
        deliver_polarization_strain(wrong_study, result_path)


def test_delivery_resolves_relative_study_model_path(tmp_path: Path) -> None:
    model_path = tmp_path / "relative-model"
    model_path.mkdir()
    study_path = _write_json(
        tmp_path / "study.json",
        {
            "study_id": "czo-parent-study",
            "model": {
                "model_id": "czo-parent-model",
                "version": "v001",
                "path": "relative-model",
            },
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )
    result_path = _strain_result(tmp_path / "strain-response.json", study_path)

    delivered = deliver_polarization_strain(study_path, result_path)

    assert delivered["parent"]["model_path"] == str(model_path.resolve())
    assert delivered["design_assessment"] == "not_assessed"


def test_delivery_rejects_saved_parent_study_path_mismatch(tmp_path: Path) -> None:
    study_path = _study(tmp_path / "study.json")
    result_path = _strain_result(tmp_path / "strain-response.json", study_path)
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    saved["parent"]["study_file"] = str((tmp_path / "unrelated-study.json").resolve())
    mismatched = _write_json(tmp_path / "mismatched.json", saved)

    with pytest.raises(ValueError):
        deliver_polarization_strain(study_path, mismatched)


def test_cli_parser_exposes_all_strain_routes() -> None:
    parser = build_parser()
    parsed = parser.parse_args([
        "create-berry-strain", "--study", "study", "--model", "model",
        "--method", "method", "--site", "site", "--request", "request",
        "--output", "out",
    ])
    assert parsed.action == "create-berry-strain"
    parsed = parser.parse_args([
        "create-berry-strain-nscf", "--manifest", "manifest", "--point-id", "yy-minus",
        "--site", "site", "--method", "method", "--request", "request",
    ])
    assert parsed.action == "create-berry-strain-nscf"
    parsed = parser.parse_args(["polarization-strain", "--request", "request", "--output", "out"])
    assert parsed.action == "polarization-strain"
    parsed = parser.parse_args([
        "deliver-properties", "--study", "study", "--polarization-strain", "result",
        "--output", "out",
    ])
    assert parsed.action == "deliver-properties"
    assert parsed.polarization_strain == Path("result")


def test_cli_routes_both_strain_producer_commands_without_running_an_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def fake_response(*args: Any) -> dict[str, Any]:
        calls.append(("response", args))
        return {"status": "scf_inputs_written_not_submitted", "evidence_kind": "software_contract_only"}

    def fake_nscf(*args: Any) -> dict[str, Any]:
        calls.append(("nscf", args))
        return {"status": "nscf_input_written_not_submitted", "evidence_kind": "software_contract_only"}

    _fake_module(
        monkeypatch,
        "mlcc.berry_strain_response",
        create_berry_strain_response=fake_response,
        create_berry_strain_nscf=fake_nscf,
    )
    response_args = [
        tmp_path / name for name in ("study.json", "model", "method.json", "site.json", "request.json", "manifest.json")
    ]
    assert cli.main([
        "create-berry-strain", "--study", str(response_args[0]), "--model", str(response_args[1]),
        "--method", str(response_args[2]), "--site", str(response_args[3]),
        "--request", str(response_args[4]), "--output", str(response_args[5]),
    ]) == 0
    assert cli.main([
        "create-berry-strain-nscf", "--manifest", str(response_args[5]), "--point-id", "yy-minus",
        "--site", str(response_args[3]), "--method", str(response_args[2]), "--request", str(response_args[4]),
    ]) == 0

    assert [name for name, _ in calls] == ["response", "nscf"]
    assert calls[0][1][-1] == response_args[5]
    assert calls[1][1][1] == "yy-minus"


def test_cli_routes_saved_strain_analysis_and_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _write_json(tmp_path / "request.json", {
        "schema": "mlcc.polarization-strain-request.v1",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    })
    analysis_output = tmp_path / "analysis.json"
    analysis_calls: list[Path] = []

    def fake_analysis(request_path: Path) -> dict[str, Any]:
        analysis_calls.append(Path(request_path))
        return {
            "schema": "mlcc.polarization-strain.v1",
            "status": "software_contract_only",
            "evidence_kind": "software_contract_only",
            "scientific_qualification": False,
            "production_qualification": False,
        }

    _fake_module(monkeypatch, "mlcc.polarization_strain", analyze_polarization_strain=fake_analysis)
    assert cli.main([
        "polarization-strain", "--request", str(request), "--output", str(analysis_output),
    ]) == 0
    assert analysis_calls == [request.resolve()]
    assert json.loads(analysis_output.read_text(encoding="utf-8"))["status"] == "software_contract_only"

    study_path = _study(tmp_path / "study.json")
    saved_result = _strain_result(tmp_path / "strain-response.json", study_path)
    delivery_output = tmp_path / "delivery.json"
    delivery_calls: list[tuple[Path, Path, Path | None]] = []

    def fake_delivery(study: Path, result: Path, targets: Path | None) -> dict[str, Any]:
        delivery_calls.append((Path(study), Path(result), targets))
        return {
            "schema": "mlcc.polarization-strain-delivery.v1",
            "status": "unresolved_missing_sources",
            "evidence_kind": "software_contract_only",
            "scientific_qualification": False,
            "production_qualification": False,
        }

    monkeypatch.setattr(cli, "deliver_polarization_strain", fake_delivery)
    assert cli.main([
        "deliver-properties", "--study", str(study_path),
        "--polarization-strain", str(saved_result), "--output", str(delivery_output),
    ]) == 0
    assert delivery_calls == [(study_path.resolve(), saved_result.resolve(), None)]
    assert json.loads(delivery_output.read_text(encoding="utf-8"))["schema"] == "mlcc.polarization-strain-delivery.v1"

