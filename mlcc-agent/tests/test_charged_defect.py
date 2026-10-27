"""Software-contract checks for the saved charged-formation consumer."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from mlcc.charged_defect import build_charged_formation


def _write(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _method(method_set: str) -> dict[str, Any]:
    return {
        "engine": "abacus", "abacus_version_target": "3.10.1", "basis_type": "pw",
        "dft_functional": "PBE", "method_set": method_set, "nspin": 1,
        "lspinorb": False, "noncolin": False, "occupations": "fixed",
        "smearing_method": "fixed", "mixing_type": "plain", "symmetry": "none",
        "ks_solver": "dav", "kpoints": [2, 2, 2], "kpoint_rule": "Gamma",
        "parameters": {"ecutwfc_Ry": 100.0, "scf_thr": 1.0e-4},
        "pseudopotential_ids": {e: f"{e}.NC.PBE.fixture" for e in ("Ca", "Zr", "O")},
        "pseudopotential_metadata": {
            e: {"type": "norm_conserving", "valence_electrons": 8} for e in ("Ca", "Zr", "O")
        },
        "pseudopotential_treatment": {
            e: "scalar_relativistic_norm_conserving" for e in ("Ca", "Zr", "O")
        },
    }


def _reference(
    role: str,
    *,
    method_set: str,
    total_energy: float,
    model: dict[str, str],
    parent_model: dict[str, str] | None,
    q: int,
    vbm: float | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema": "mlcc.defect-electronic-reference.v1",
        "role": role,
        "task_id": f"fixture-{role}-task",
        "task_path": f"/software-contract/{role}-task",
        "study": {"study_id": "fixture-study", "source_file": "/software-contract/study.json"},
        "model": deepcopy(model),
        "method": _method(method_set),
        "charge": {"q": q, "convention": "q_positive_removes_electrons"},
        "levels": {"unit": "eV", "vbm_eV": vbm, "vbm_reference": "fixture-levels"},
        "parent_total_energy_provenance": {
            "value_eV": total_energy, "definition": "ABACUS fixture total energy in eV",
            "original_field": "energy_eV", "is_potential_zero": False,
        },
        "electronic_source_file": f"/software-contract/{role}-electronic.json",
        "source_files": {"task.json": f"/software-contract/{role}-task/task.json"},
        "electronic_source": {"evidence_kind": "software_contract_only"},
    }
    if role == "defect":
        record["parent_model"] = deepcopy(parent_model)
        record["defect_descriptor"] = {"composition_delta": {"O": -1}}
    return record


def _pair() -> dict[str, Any]:
    host_model = {"model_id": "fixture-czo-host", "version": "v001", "path": "/software-contract/czo-host"}
    host = _reference(
        "host", method_set="host-method", total_energy=-10.0, model=host_model,
        parent_model=None, q=0, vbm=1.5,
    )
    defect = _reference(
        "defect", method_set="defect-method", total_energy=-9.0,
        model={"model_id": "fixture-czo-defect", "version": "v001", "path": "/software-contract/czo-defect"},
        parent_model=host_model, q=1, vbm=None,
    )
    return {
        "schema": "mlcc.defect-reference-pair.v1", "status": "matching_recorded_fields_unaligned",
        "host": host, "defect": defect, "descriptor_path": "/software-contract/czo-defect/model.json",
        "method_comparison": {
            "same_recorded_comparison_fields": True,
            "same_method_label": False,
            "compared_physical_fields": ["engine", "pseudopotential_ids"],
            "compared_numerical_fields": ["kpoints", "parameters"],
        },
    }


def _correction(status: str = "computed") -> dict[str, Any]:
    terms = {
        "potential_alignment_eV": 0.25, "image_charge_eV": 0.75, "total_eV": 1.0,
        "method": "FNV_scalar", "qualification": "software_contract_only",
    }
    return {
        "schema": "mlcc.charge-correction.v1", "correction_id": "fixture-correction",
        "status": status, "references": _pair(),
        "lineage": {
            "parent_model": {"model_id": "fixture-czo-host", "version": "v001", "path": "/software-contract/czo-host"},
            "composition_delta": {"O": -1}, "defect_charge_q": 1,
            "charge_convention": "q_positive_removes_electrons",
        },
        "source_paths": {"host_potential_path": "/software-contract/host.cube"},
        "missing": [] if status == "computed" else ["defect_potential"],
        "calculation": None if status == "missing" else {
            "schema": "mlcc.scalar-fnv.v1", "parameters": {"q": 1},
            "image_charge_eV": 0.75, "potential_alignment_eV": 0.25,
            "alignment_charge_multiplier": 1, "total_eV": 1.0,
            "correction_terms": deepcopy(terms),
        },
        "correction_terms": None if status == "missing" else terms,
        "evidence_kind": "software_contract_only",
    }


def _chemical_delivery(path: Path, pair: dict[str, Any], *, method_set: str = "host-method") -> Path:
    return _write(
        path,
        {
            "schema": "mlcc.chemical-reference-delivery.v1",
            "study_id": "fixture-study", "reference_set_id": "fixture-chemical-set",
            "collection_path": "/software-contract/chemical-set.json",
            "host": {"role": "host", "source": deepcopy(pair["host"])},
            "references": {
                "schema": "mlcc.chemical-reference-set.v1", "evidence_kind": "software_contract_only",
                "references": [{"evidence_kind": "software_contract_only"}],
            },
            "chemical_point": None,
            "mathematical_chemical_point": {
                "mu_eV_per_atom": {"O": -2.0}, "engine": "abacus", "engine_version": "3.10.1",
                "method_set": method_set, "energy_definition": "ABACUS fixture total energy in eV",
                "source_reference": "/software-contract/chemical-set.json",
                "reference_set_id": "fixture-chemical-set", "evidence_kind": "software_contract_only",
            },
            "missing": [], "scientific_qualification": False, "production_qualification": False,
        },
    )


def _request(path: Path, correction: Path, chemical: Path | None, ef_grid: list[float] | None) -> Path:
    return _write(path, {
        "schema": "mlcc.charged-formation-request.v1", "formation_id": "fixture-vo-q1",
        "correction_path": str(correction),
        "chemical_delivery_path": None if chemical is None else str(chemical),
        "ef_grid_eV": ef_grid,
    })


def test_saved_correction_alignment_is_counted_once(tmp_path: Path) -> None:
    correction_value = _correction()
    correction = _write(tmp_path / "correction.json", correction_value)
    chemical = _chemical_delivery(tmp_path / "chemical.json", correction_value["references"])
    request = _request(tmp_path / "request.json", correction, chemical, [0.0, 0.5])

    result = build_charged_formation(request)

    assert result["status"] == "computed"
    assert result["evidence_kind"] == "software_contract_only"
    assert result["formation"]["correction"]["alignment_count"] == 1
    assert result["formation"]["curve"][0]["formation_energy_eV"] == pytest.approx(1.5)
    assert result["formation"]["vbm_eV"] == pytest.approx(1.5)
    assert result["reference_identity"]["method_comparison"]["same_method_label"] is False
    assert result["reference_identity"]["host_vbm"]["source"] == "references.host.levels.vbm_eV"


def test_different_chemical_method_is_rejected(tmp_path: Path) -> None:
    correction_value = _correction()
    correction = _write(tmp_path / "correction.json", correction_value)
    chemical = _chemical_delivery(tmp_path / "chemical.json", correction_value["references"], method_set="different-method")
    request = _request(tmp_path / "request.json", correction, chemical, [0.0])

    with pytest.raises(ValueError, match="chemical point engine, method, or energy definition"):
        build_charged_formation(request)


def test_missing_correction_and_inputs_remain_unresolved(tmp_path: Path) -> None:
    correction = _write(tmp_path / "correction.json", _correction(status="missing"))
    request = _request(tmp_path / "request.json", correction, None, None)

    result = build_charged_formation(request)

    assert result["status"] == "missing"
    assert result["formation"] is None
    assert "defect_potential" in result["missing"]
    assert "correction" in result["missing"]
    assert "chemical_reference" in result["missing"]
    assert "ef_grid_eV" in result["missing"]
    assert result["correction"]["calculation"] is None
