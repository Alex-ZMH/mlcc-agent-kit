"""Focused Study/CLI wiring checks for the P5 SCF-energy path.

All records in this file are explicit ``software_contract_only`` fixtures.
They exercise saved-result delivery and CLI routing; they are not native DFT
evidence, a Berry branch decision, a NEB calculation, or a material
qualification claim.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest

import mlcc.cli as cli
from mlcc.cli import build_parser
from mlcc.property_delivery import deliver_polarization_energy


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
    parent_model_path = model_path or path.parent / "parent-model"
    parent_model_path.mkdir(parents=True, exist_ok=True)
    return _write_json(
        path,
        {
            "study_id": study_id,
            "model": {
                "model_id": model_id,
                "version": "v001",
                "path": str(parent_model_path.resolve()),
            },
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )


def _point(
    root: Path,
    *,
    point_id: str,
    coordinate: float,
    energy_eV_cell: float,
    scheduler_job_id: str,
    child_study_id: str,
    child_model_id: str,
    berry_result_file: str | None,
    relative_energy_eV_cell: float,
) -> dict[str, Any]:
    task_file = root / f"{point_id}.task.json"
    result_file = root / f"{point_id}.result.json"
    child_model_path = root / f"{point_id}.model"
    child_model_path.mkdir(parents=True, exist_ok=True)
    _write_json(
        task_file,
        {
            "task_id": f"software-{point_id}-task",
            "study_id": child_study_id,
            "model_id": child_model_id,
            "model_version": "v002",
            "calculation": "scf",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )
    _write_json(
        result_file,
        {
            "energy_eV": energy_eV_cell,
            "energy_unit": "eV",
            "electronic_converged": True,
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )
    return {
        "point_id": point_id,
        "coordinate": coordinate,
        "energy_eV_cell": energy_eV_cell,
        "relative_energy_eV_cell": relative_energy_eV_cell,
        "scf_task_file": str(task_file.resolve()),
        "scf_result_file": str(result_file.resolve()),
        "berry_result_file": berry_result_file,
        "child": {
            "study_id": child_study_id,
            "model": {
                "model_id": child_model_id,
                "version": "v002",
                "path": str(child_model_path.resolve()),
            },
        },
        "native_job": {
            "task_id": f"software-{point_id}-task",
            "scheduler_job_id": scheduler_job_id,
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "runner": "slurm",
        },
        "source": {
            "task_file": str(task_file.resolve()),
            "result_file": str(result_file.resolve()),
            "method_file": str((root / f"{point_id}.method.json").resolve()),
            "study_file": str((root / f"{point_id}.study.json").resolve()),
            "model_path": str(child_model_path.resolve()),
        },
        "polarization_coordinate": None,
        "delta_polarization": None,
        "branch_status": "not_unwrapped" if berry_result_file else None,
        "scientific_qualification": False,
        "production_qualification": False,
        "evidence_kind": "software_contract_only",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }


def _energy_result(tmp_path: Path, study_path: Path, *, berry: bool = False) -> Path:
    root = tmp_path / "saved-sources"
    root.mkdir(parents=True, exist_ok=True)
    parent_model_path = Path(json.loads(study_path.read_text(encoding="utf-8"))["model"]["path"])
    points = [
        _point(
            root,
            point_id="atom8-minus-x",
            coordinate=-0.01,
            energy_eV_cell=-10.0,
            relative_energy_eV_cell=0.0,
            scheduler_job_id="177",
            child_study_id="czo-minus-study",
            child_model_id="czo-minus-model",
            berry_result_file=(str((root / "minus.berry.json").resolve()) if berry else None),
        ),
        _point(
            root,
            point_id="atom8-plus-x",
            coordinate=0.01,
            energy_eV_cell=-9.75,
            relative_energy_eV_cell=0.25,
            scheduler_job_id="178",
            child_study_id="czo-plus-study",
            child_model_id="czo-plus-model",
            berry_result_file=(str((root / "plus.berry.json").resolve()) if berry else None),
        ),
    ]
    if berry:
        _write_json(root / "minus.berry.json", {"fixture": True, "branch_status": "not_unwrapped"})
        _write_json(root / "plus.berry.json", {"fixture": True, "branch_status": "not_unwrapped"})
    result = {
        "schema": "mlcc.polarization-energy-path.v1",
        "path_id": "software-czo-atom8-x-energy-v001",
        "path_basis": "explicit software fixture for saved fixed-cell SCF points",
        "parent": {
            "study_id": "czo-parent-study",
            "study_file": str(study_path.resolve()),
            "model_id": "czo-parent-model",
            "model_version": "v001",
            "model_path": str(parent_model_path.resolve()),
        },
        "path_coordinate": {"name": "atom8_cartesian_x", "unit": "angstrom"},
        "mechanical_constraint": {
            "kind": "fixed_cell",
            "description": "software fixture fixed-cell single-point samples",
        },
        "reference_point_id": "atom8-minus-x",
        "points": points,
        "endpoint_difference_eV_cell": 0.25,
        "sampled_maximum": {
            "energy_eV_cell": -9.75,
            "relative_energy_eV_cell": 0.25,
            "point_ids": ["atom8-plus-x"],
            "coordinates": [0.01],
            "sources": [{"task_id": "software-atom8-plus-x-task", "scheduler_job_id": "178"}],
        },
        "native_jobs": [
            {"task_id": "software-atom8-minus-x-task", "scheduler_job_id": "177", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
            {"task_id": "software-atom8-plus-x-task", "scheduler_job_id": "178", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
        ],
        "missing": (["branch_selection"] if berry else ["berry_result_file", "branch_selection"]),
        "status": "evaluated_energy_path_unqualified",
        "evidence_kind": "software_contract_only",
        "energy_definition": "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham at fixed occupations in eV",
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
        "neb_barrier_eV": None,
        "finite_temperature_free_energy_eV": None,
        "spontaneous_polarization": None,
        "double_well_qualified": False,
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    return _write_json(tmp_path / "energy-path.json", result)


def test_delivery_preserves_curve_sources_and_distinct_child_lineage(tmp_path: Path) -> None:
    study_path = _study(tmp_path / "study.json")
    energy_path = _energy_result(tmp_path, study_path)
    saved = json.loads(energy_path.read_text(encoding="utf-8"))

    result = deliver_polarization_energy(study_path, energy_path)

    assert result["schema"] == "mlcc.polarization-energy-delivery.v1"
    assert result["path_result"] == saved
    assert result["points"] == saved["points"]
    assert result["native_jobs"] == saved["native_jobs"]
    assert result["parent"] == saved["parent"]
    assert result["points"][0]["child"]["study_id"] != result["points"][1]["child"]["study_id"]
    assert result["points"][0]["child"]["model"]["model_id"] != result["points"][1]["child"]["model"]["model_id"]
    assert result["endpoint_difference_eV_cell"] == pytest.approx(0.25)
    assert result["evidence_kind"] == "software_contract_only"
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False


@pytest.mark.parametrize("berry", [False, True])
def test_delivery_allows_missing_berry_and_unresolved_branch(tmp_path: Path, berry: bool) -> None:
    study_path = _study(tmp_path / "study.json")
    energy_path = _energy_result(tmp_path, study_path, berry=berry)

    result = deliver_polarization_energy(study_path, energy_path)

    assert ("berry_result_file" in result["missing"]) is (not berry)
    assert "branch_selection" in result["missing"]
    assert all((point["berry_result_file"] is not None) is berry for point in result["points"])
    assert all(point["polarization_coordinate"] is None for point in result["points"])
    assert all(point["delta_polarization"] is None for point in result["points"])
    assert result["double_well_qualified"] is False
    assert result["neb_barrier_eV"] is None


def test_delivery_keeps_software_math_curve_unqualified_and_does_not_call_it_neb(
    tmp_path: Path,
) -> None:
    study_path = _study(tmp_path / "study.json")
    energy_path = _energy_result(tmp_path, study_path)

    result = deliver_polarization_energy(study_path, energy_path)

    assert result["status"] == "evaluated_energy_path_unqualified"
    assert result["evidence_kind"] == "software_contract_only"
    assert result["sampled_maximum"]["point_ids"] == ["atom8-plus-x"]
    assert result["sampled_maximum"]["relative_energy_eV_cell"] == pytest.approx(0.25)
    assert result["neb_barrier_eV"] is None
    assert result["finite_temperature_free_energy_eV"] is None
    assert result["spontaneous_polarization"] is None
    assert result["double_well_qualified"] is False
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False


@pytest.mark.parametrize(
    "mutate_study",
    [
        lambda path: _study(path, study_id="other-study"),
        lambda path: _study(path, model_id="other-model"),
        lambda path: _study(path, model_path=path.parent / "other-parent-model"),
    ],
)
def test_delivery_rejects_wrong_parent_study_model_or_path(
    tmp_path: Path, mutate_study: Callable[[Path], Path],
) -> None:
    good_study_path = _study(tmp_path / "good-study.json")
    energy_path = _energy_result(tmp_path, good_study_path)
    wrong_study_path = mutate_study(good_study_path)

    with pytest.raises(ValueError):
        deliver_polarization_energy(wrong_study_path, energy_path)


def test_cli_polarization_energy_dispatches_producer_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _write_json(
        tmp_path / "request.json",
        {
            "schema": "mlcc.polarization-energy-request.v1",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )
    output = tmp_path / "producer-result.json"
    polarization_energy = importlib.import_module("mlcc.polarization_energy")
    calls: list[Path] = []

    def fake_producer(request_path: Path) -> dict[str, Any]:
        calls.append(Path(request_path))
        return {
            "schema": "mlcc.polarization-energy-path.v1",
            "status": "software_contract_only",
            "evidence_kind": "software_contract_only",
            "scientific_qualification": False,
            "production_qualification": False,
        }

    monkeypatch.setattr(polarization_energy, "analyze_polarization_energy_path", fake_producer)

    exit_code = cli.main([
        "polarization-energy", "--request", str(request), "--output", str(output),
    ])

    assert exit_code == 0
    assert calls == [request.resolve()]
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "software_contract_only"


def test_cli_saved_delivery_does_not_call_polarization_energy_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_path = _study(tmp_path / "study.json")
    energy_path = _energy_result(tmp_path, study_path)
    output = tmp_path / "delivery.json"
    polarization_energy = importlib.import_module("mlcc.polarization_energy")

    def fail_if_recomputed(*_: Any, **__: Any) -> None:
        raise AssertionError("saved delivery must not rerun polarization-energy producer")

    monkeypatch.setattr(polarization_energy, "analyze_polarization_energy_path", fail_if_recomputed)

    exit_code = cli.main([
        "deliver-properties", "--study", str(study_path),
        "--polarization-energy", str(energy_path), "--output", str(output),
    ])

    assert exit_code == 0
    delivered = json.loads(output.read_text(encoding="utf-8"))
    assert delivered["schema"] == "mlcc.polarization-energy-delivery.v1"
    assert delivered["path_result_file"] == str(energy_path.resolve())
    assert delivered["points"] == json.loads(energy_path.read_text(encoding="utf-8"))["points"]


def test_cli_polarization_energy_delivery_source_is_mutually_exclusive() -> None:
    parser = build_parser()
    parsed = parser.parse_args([
        "deliver-properties", "--study", "study.json",
        "--polarization-energy", "energy.json", "--output", "out.json",
    ])
    assert parsed.polarization_energy == Path("energy.json")

    with pytest.raises(SystemExit):
        parser.parse_args([
            "deliver-properties", "--study", "study.json", "--tasks", "task",
            "--polarization-energy", "energy.json", "--output", "out.json",
        ])
