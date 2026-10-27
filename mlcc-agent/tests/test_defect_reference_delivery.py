from __future__ import annotations

import json
from pathlib import Path

import pytest

import mlcc.defect_references as defect_references
from mlcc.cli import build_parser
from mlcc.property_delivery import deliver_defect_references


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _pair(tmp_path: Path, *, defect_study: str = "defect-study") -> tuple[dict, Path, Path, Path]:
    host_model = tmp_path / "host-model"
    defect_model = tmp_path / "defect-model"
    host_source = tmp_path / "request" / "host-electronic.json"
    defect_source = tmp_path / "request" / "defect-electronic.json"
    descriptor = tmp_path / "request" / "defect-model.json"
    for path in (host_source, defect_source, descriptor):
        _write(path, {"fixture": True})
    host = {
        "schema": "mlcc.defect-electronic-reference.v1",
        "role": "host",
        "study": {"study_id": "host-study", "source_file": str(tmp_path / "host-study.json")},
        "model": {"model_id": "host-model", "version": "v001", "path": str(host_model)},
        "electronic_source_file": str(host_source),
        "scientific_qualification": False,
        "production_qualification": False,
    }
    defect = {
        "schema": "mlcc.defect-electronic-reference.v1",
        "role": "defect",
        "study": {"study_id": defect_study, "source_file": str(tmp_path / "defect-study.json")},
        "model": {"model_id": "defect-model", "version": "v001", "path": str(defect_model)},
        "parent_model": {"model_id": "host-model", "version": "v001", "path": str(host_model)},
        "defect_descriptor": {"kind": "explicit_defect_sequence"},
        "electronic_source_file": str(defect_source),
        "aligned_host_vbm_eV": None,
        "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None,
        "charged_formation_energy_eV": None,
        "scientific_qualification": False,
        "production_qualification": False,
    }
    pair = {
        "schema": "mlcc.defect-reference-pair.v1",
        "status": "different_or_incomplete_method_sources_unaligned",
        "host": host,
        "defect": defect,
        "descriptor_path": str(descriptor),
        "aligned_host_vbm_eV": None,
        "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None,
        "charged_formation_energy_eV": None,
        "scientific_qualification": False,
        "production_qualification": False,
    }
    return pair, host_source, defect_source, descriptor


def _request(request_dir: Path) -> Path:
    return _write(
        request_dir / "request.json",
        {
            "schema": "mlcc.defect-reference-delivery-request.v1",
            "host_electronic_path": "host-electronic.json",
            "defect_electronic_path": "defect-electronic.json",
            "descriptor_path": "defect-model.json",
        },
    )


def _study(tmp_path: Path, *, study_id: str = "defect-study", model_id: str = "defect-model") -> Path:
    return _write(
        tmp_path / "study.json",
        {
            "study_id": study_id,
            "model": {
                "model_id": model_id,
                "version": "v001",
                "path": str(tmp_path / "defect-model"),
            },
        },
    )


def test_deliver_defect_references_binds_defect_study_and_preserves_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair, host_path, defect_path, descriptor_path = _pair(tmp_path)
    request = _request(tmp_path / "request")
    calls: list[tuple[Path, Path, Path]] = []

    def fake_builder(host: Path, defect: Path, descriptor: Path) -> dict:
        calls.append((host, defect, descriptor))
        return pair

    monkeypatch.setattr(defect_references, "build_defect_electronic_reference", fake_builder)
    result = deliver_defect_references(_study(tmp_path), request)

    assert calls == [(host_path.resolve(), defect_path.resolve(), descriptor_path.resolve())]
    assert result["schema"] == "mlcc.defect-reference-delivery.v1"
    assert result["study_id"] == "defect-study"
    assert result["references"] == pair
    assert result["host"] == pair["host"]
    assert result["defect"] == pair["defect"]
    assert result["aligned_host_vbm_eV"] is None
    assert result["potential_alignment_eV"] is None
    assert result["FNV_eFNV_correction_eV"] is None
    assert result["charged_formation_energy_eV"] is None
    assert result["qualification"]["scientific_qualification"] is False
    assert result["design_assessment"] == "not_assessed"


def test_deliver_defect_references_rejects_wrong_study_or_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair, _, _, _ = _pair(tmp_path)
    request = _request(tmp_path / "request")
    monkeypatch.setattr(defect_references, "build_defect_electronic_reference", lambda *_: pair)

    with pytest.raises(ValueError, match="provided Study"):
        deliver_defect_references(_study(tmp_path, study_id="other-study"), request)
    with pytest.raises(ValueError, match="provided Study model"):
        deliver_defect_references(_study(tmp_path, model_id="other-model"), request)


def test_deliver_defect_references_rejects_crossed_source_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair, _, _, _ = _pair(tmp_path)
    pair["host"]["electronic_source_file"] = str(tmp_path / "other-host.json")
    request = _request(tmp_path / "request")
    monkeypatch.setattr(defect_references, "build_defect_electronic_reference", lambda *_: pair)

    with pytest.raises(ValueError, match="host source path"):
        deliver_defect_references(_study(tmp_path), request)


def test_targets_keep_independent_levels_insufficient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair, _, _, _ = _pair(tmp_path)
    request = _request(tmp_path / "request")
    monkeypatch.setattr(defect_references, "build_defect_electronic_reference", lambda *_: pair)
    targets = _write(
        tmp_path / "targets.json",
        {
            "study_id": "defect-study",
            "requirements": [{
                "requirement_id": "epsilon",
                "observable_id": "epsilon_static",
                "definition": "static dielectric tensor component",
                "object_level": "bulk_model_cell",
                "unit": "dimensionless",
                "conditions": {},
                "required": True,
                "uncertainty_rule": "nominal",
                "comparison": "upper_bound",
                "upper_bound": 100.0,
            }],
        },
    )

    result = deliver_defect_references(_study(tmp_path), request, targets)
    assert result["design_assessment"] == "insufficient_evidence"


def test_cli_defect_reference_source_is_mutually_exclusive() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "deliver-properties", "--study", "study.json",
        "--defect-references", "request.json", "--output", "out.json",
    ])
    assert args.defect_references == Path("request.json")
    with pytest.raises(SystemExit):
        parser.parse_args([
            "deliver-properties", "--study", "study.json", "--tasks", "task",
            "--defect-references", "request.json", "--output", "out.json",
        ])
