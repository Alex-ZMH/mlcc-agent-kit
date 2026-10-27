"""Focused Study/CLI delivery checks for the P4 potential-alignment contract.

The complete difference fixture is explicitly ``software_contract_only``.
It checks preservation of an already produced diagnostic and does not claim a
native alignment, a charge correction, or a qualified formation energy.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

import mlcc.cli as cli
from mlcc.cli import build_parser
from mlcc.property_delivery import deliver_potential_alignment


def _write(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _study(
    path: Path,
    *,
    study_id: str = "defect-study",
    model_id: str = "defect-model",
    model_path: Path | None = None,
) -> Path:
    return _write(
        path,
        {
            "study_id": study_id,
            "model": {
                "model_id": model_id,
                "version": "v001",
                "path": str(model_path or (path.parent / "defect-model")),
            },
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )


def _reference(
    root: Path,
    role: str,
    *,
    job_id: str,
    study_id: str,
    model_id: str,
    model_path: Path,
    electronic_path: Path,
    parent_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_dir = root / f"{role}-task"
    task_dir.mkdir(parents=True, exist_ok=True)
    model_path.mkdir(parents=True, exist_ok=True)
    model_file = _write(
        model_path / "model.json",
        {
            "model_id": model_id,
            "version": "v001",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )
    return {
        "schema": "mlcc.defect-electronic-reference.v1",
        "role": role,
        "status": "software_contract_only_reference",
        "task_id": f"software-{role}-task",
        "task_path": str(task_dir),
        "native_job": {
            "scheduler_job_id": job_id,
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "runner": "slurm",
        },
        "study": {
            "study_id": study_id,
            "source_file": str(root / f"{role}-source-study.json"),
        },
        "model": {
            "model_id": model_id,
            "version": "v001",
            "path": str(model_path),
            "metadata_file": str(model_file),
        },
        "parent_model": parent_model,
        "defect_descriptor": (
            {"kind": "explicit_defect_sequence", "fixture_purpose": "software_contract_only"}
            if role == "defect" else None
        ),
        "electronic_source_file": str(electronic_path),
        "source_files": {
            "task.json": str(task_dir / "task.json"),
            "result.json": str(task_dir / "result.json"),
            "method.json": str(task_dir / "method.json"),
        },
        "method": {
            "engine": "abacus",
            "engine_version": "3.10.1",
            "basis_type": "pw",
            "method_set": f"software-{role}-method",
            "fixture_purpose": "software_contract_only",
        },
        "conditions": {"net_charge": 0 if role == "host" else 1},
        "aligned_host_vbm_eV": None,
        "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None,
        "charged_formation_energy_eV": None,
        "scientific_qualification": False,
        "production_qualification": False,
        "evidence_kind": "software_contract_only",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }


def _pair(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    root = tmp_path / "saved"
    host_model = root / "host-model"
    defect_model = root / "defect-model"
    host_electronic = _write(root / "host-electronic.json", {"fixture": True})
    defect_electronic = _write(root / "defect-electronic.json", {"fixture": True})
    descriptor = _write(root / "defect-model.json", {"fixture": True})
    host = _reference(
        root, "host", job_id="software-host-job", study_id="host-study",
        model_id="host-model", model_path=host_model, electronic_path=host_electronic,
    )
    defect = _reference(
        root, "defect", job_id="software-defect-job", study_id="defect-study",
        model_id="defect-model", model_path=defect_model, electronic_path=defect_electronic,
        parent_model={
            "model_id": "host-model", "version": "v001", "path": str(host_model),
        },
    )
    pair = {
        "schema": "mlcc.defect-reference-pair.v1",
        "status": "software_contract_only_pair",
        "host": host,
        "defect": defect,
        "descriptor_path": str(descriptor),
        "method_comparison": {
            "same_recorded_comparison_fields": True,
            "scope": "software_contract_only",
        },
        "aligned_host_vbm_eV": None,
        "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None,
        "charged_formation_energy_eV": None,
        "scientific_qualification": False,
        "production_qualification": False,
    }
    return pair, {
        "host_electronic_path": host_electronic,
        "defect_electronic_path": defect_electronic,
        "descriptor_path": descriptor,
        "host_model_path": host_model,
        "defect_model_path": defect_model,
    }


def _potential_summary(
    *,
    role: str,
    source: dict[str, Any],
    path: Path | None,
    native: bool,
) -> dict[str, Any]:
    return {
        "schema": "mlcc.abacus-electrostatic-potential.v1",
        "role": role,
        "task_id": source["task_id"],
        "native_job": source["native_job"],
        "artifact_path": None if path is None else str(path),
        "kind": "local_ionic_plus_hartree",
        "value_unit": "Ry",
        "geometry_unit": "Bohr",
        "native_output_observed": native,
        "evidence_kind": "software_contract_only" if not native else "native_saved_source",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }


def _alignment(
    tmp_path: Path,
    *,
    complete: bool,
) -> tuple[Path, Path, dict[str, Any]]:
    pair, paths = _pair(tmp_path)
    host_potential = _write(tmp_path / "saved" / "host-potential.json", {"fixture": True})
    defect_potential = (
        _write(tmp_path / "saved" / "defect-potential.json", {"fixture": True})
        if complete else None
    )
    if complete:
        selection: dict[str, Any] | None = {
            "kind": "index_boxes",
            "boxes": [{"lower": [0, 0, 0], "upper": [2, 2, 1]}],
            "reason": "software_contract_only explicit region",
            "source": "software_contract_only fixture",
        }
        missing: list[str] = []
        difference: dict[str, Any] | None = {
            "delta_v_defect_minus_host_eV": 0.125,
            "sample_count": 4,
            "host_region_mean_eV": -1.25,
            "defect_region_mean_eV": -1.125,
            "difference_min_eV": 0.125,
            "difference_max_eV": 0.125,
            "difference_population_std_eV": 0.0,
            "difference_peak_to_peak_eV": 0.0,
            "evidence_kind": "software_contract_only",
        }
        candidate_vbm: float | None = 3.325
        status = "computed_regional_difference_unqualified"
    else:
        selection = None
        missing = ["defect_potential", "selection"]
        difference = None
        candidate_vbm = None
        status = "missing_inputs"

    defect_source = pair["defect"]
    host_source = pair["host"]
    alignment = {
        "schema": "mlcc.potential-alignment.v1",
        "alignment_id": "software-contract-alignment-v001",
        "request_path": str(tmp_path / "request.json"),
        "status": status,
        "references": pair,
        "source_paths": {
            "host_electronic_path": str(paths["host_electronic_path"]),
            "defect_electronic_path": str(paths["defect_electronic_path"]),
            "descriptor_path": str(paths["descriptor_path"]),
            "host_potential_path": str(host_potential),
            "defect_potential_path": None if defect_potential is None else str(defect_potential),
        },
        "potentials": {
            "host": _potential_summary(
                role="host", source=host_source, path=host_potential, native=False,
            ),
            "defect": (
                _potential_summary(
                    role="defect", source=defect_source, path=defect_potential, native=False,
                )
                if complete else None
            ),
        },
        "selection": selection,
        "missing": missing,
        "difference": difference,
        "candidate_host_vbm_on_defect_gauge_eV": candidate_vbm,
        "evidence_kind": "software_contract_only",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "native_alignment_accepted": False,
        "scientific_qualification": False,
        "production_qualification": False,
    }
    alignment_path = _write(tmp_path / "alignment.json", alignment)
    return alignment_path, _study(
        tmp_path / "study.json", model_path=paths["defect_model_path"],
    ), alignment


def test_delivery_preserves_software_difference_and_keeps_corrections_unresolved(
    tmp_path: Path,
) -> None:
    alignment_path, study_path, alignment = _alignment(tmp_path, complete=True)

    result = deliver_potential_alignment(study_path, alignment_path)

    assert result["schema"] == "mlcc.potential-alignment-delivery.v1"
    assert result["alignment"] == alignment
    assert result["source_paths"] == alignment["source_paths"]
    assert result["host"] == alignment["references"]["host"]
    assert result["defect"] == alignment["references"]["defect"]
    assert result["alignment"]["difference"]["delta_v_defect_minus_host_eV"] == pytest.approx(0.125)
    assert result["alignment"]["candidate_host_vbm_on_defect_gauge_eV"] == pytest.approx(3.325)
    assert result["potential_alignment_eV"] is None
    assert result["aligned_host_vbm_eV"] is None
    assert result["correction_terms"] is None
    assert result["FNV_eFNV_correction_eV"] is None
    assert result["charged_formation_energy_eV"] is None
    assert result["native_alignment_accepted"] is False
    assert result["scientific_qualification"] is False
    assert result["numerical_qualification"] is False
    assert result["production_qualification"] is False
    assert result["design_assessment"] == "not_assessed"


def test_delivery_preserves_job_fields_and_missing_potential_inputs(
    tmp_path: Path,
) -> None:
    alignment_path, study_path, alignment = _alignment(tmp_path, complete=False)

    result = deliver_potential_alignment(study_path, alignment_path)

    assert result["alignment"] == alignment
    assert result["missing"] == ["defect_potential", "selection"]
    assert result["alignment"]["difference"] is None
    assert result["alignment"]["potentials"]["defect"] is None
    assert result["host"]["native_job"]["scheduler_job_id"] == "software-host-job"
    assert result["defect"]["native_job"]["scheduler_job_id"] == "software-defect-job"
    assert result["source_paths"]["defect_potential_path"] is None
    assert result["potential_alignment_eV"] is None
    assert result["aligned_host_vbm_eV"] is None
    assert result["FNV_eFNV_correction_eV"] is None
    assert result["charged_formation_energy_eV"] is None
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False


@pytest.mark.parametrize(
    ("study_id", "model_id"),
    [("other-study", "defect-model"), ("defect-study", "other-model")],
)
def test_delivery_rejects_study_or_model_mismatch(
    tmp_path: Path, study_id: str, model_id: str,
) -> None:
    alignment_path, _, _ = _alignment(tmp_path, complete=True)
    study_path = _study(
        tmp_path / "mismatch-study.json",
        study_id=study_id,
        model_id=model_id,
        model_path=alignment_path.parent / "saved" / "defect-model",
    )

    with pytest.raises(ValueError):
        deliver_potential_alignment(study_path, alignment_path)


def test_cli_potential_alignment_source_is_mutually_exclusive() -> None:
    parser = build_parser()
    parsed = parser.parse_args([
        "deliver-properties", "--study", "study.json",
        "--potential-alignment", "alignment.json", "--output", "out.json",
    ])
    assert parsed.potential_alignment == Path("alignment.json")
    with pytest.raises(SystemExit):
        parser.parse_args([
            "deliver-properties", "--study", "study.json", "--tasks", "task",
            "--potential-alignment", "alignment.json", "--output", "out.json",
        ])


def test_cli_potential_alignment_routes_to_new_builder_without_old_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _write(
        tmp_path / "request.json",
        {
            "schema": "mlcc.potential-alignment-request.v1",
            "alignment_id": "software-contract-alignment-v001",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )
    output = tmp_path / "output.json"
    calls: list[Path] = []
    builder_module = importlib.import_module("mlcc.potential_alignment")
    electrostatic_module = importlib.import_module("mlcc.electrostatic_potential")

    def fake_builder(request_path: Path) -> dict[str, Any]:
        calls.append(Path(request_path))
        return {
            "schema": "mlcc.potential-alignment.v1",
            "alignment_id": "software-contract-alignment-v001",
            "evidence_kind": "software_contract_only",
            "difference": None,
            "scientific_qualification": False,
            "production_qualification": False,
        }

    monkeypatch.setattr(builder_module, "build_potential_alignment", fake_builder)

    def fail_if_old_parser_called(*_: Any, **__: Any) -> None:
        raise AssertionError("potential-alignment CLI must not call the old electrostatic parser")

    monkeypatch.setattr(
        electrostatic_module, "read_abacus_electrostatic_task", fail_if_old_parser_called,
    )

    exit_code = cli.main([
        "potential-alignment", "--request", str(request), "--output", str(output),
    ])

    assert exit_code == 0
    assert calls == [request.resolve()]
