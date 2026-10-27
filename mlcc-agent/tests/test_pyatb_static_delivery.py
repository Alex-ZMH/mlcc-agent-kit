"""New delivery contract checks; reader/model stubs are not native CZO evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mlcc import dielectric_response, property_delivery
from test_p5_property_delivery import _native_method


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def delivery_case(tmp_path, monkeypatch):
    method = _native_method()
    method.update(basis_type="lcao", orbital_files={"Na": "contract.orb", "Cl": "contract.orb"},
                  orbital_metadata={"scope": "software_contract_only"})
    parent = {"study_id": "contract-study", "model_id": "contract-model", "model_version": "v001",
              "model_path": str(tmp_path / "model")}
    electronic = {
        "schema": "mlcc.pyatb-static-electronic.v1", "provenance_kind": "native_derived",
        "source_mode": "native_source_bound", "evidence_kind": "software_contract_only",
        "parent": parent, "atom_ids": [0, 1],
        "cell_angstrom": [[4, 0, 0], [0, 4, 0], [0, 0, 4]], "volume_A3": 64,
        "method_identity": method, "kind": "epsilon_infinity_relative", "unit": "dimensionless",
        "tensor": [[3, 0.2, 0], [0.2, 4, 0.1], [0, 0.1, 5]],
        "status": "complete", "unresolved_reasons": [],
        "electrical_boundary": "fixed_E_zero", "mechanical_boundary": "fixed_cell", "ions": "clamped",
        "frequency_definition": "direct_static_omega_zero", "identity_included": True,
        "source_refs": [str(tmp_path / "static_dielectric_function.dat")],
        "native_jobs": [{"role": role, "task_id": f"contract-{role}",
                         "scheduler_job_id": f"stub-{role}", "scheduler_state": "COMPLETED", "exit_code": "0:0"}
                        for role in ("reference_scf", "pyatb_static")],
        "scientific_qualification": False, "production_qualification": False,
    }
    calls = []

    def bound(product, input_path=None):
        calls.append(str(input_path))
        value = copy.deepcopy(product)
        value["source_path"] = str(Path(input_path).resolve())
        return value

    monkeypatch.setattr(dielectric_response, "bind_native_electronic_input", bound)
    monkeypatch.setattr(property_delivery, "_model_context", lambda _path: {
        "model_id": parent["model_id"], "model_version": parent["model_version"],
        "model_path": parent["model_path"], "atom_ids": electronic["atom_ids"],
        "cell_angstrom": electronic["cell_angstrom"], "volume_A3": electronic["volume_A3"],
    })
    study = _write(tmp_path / "study.json", {
        "study_id": parent["study_id"],
        "model": {"model_id": parent["model_id"], "version": parent["model_version"], "path": parent["model_path"]},
    })
    path = _write(tmp_path / "electronic.json", electronic)
    request = _write(tmp_path / "delivery.json", {
        "schema": "mlcc.p5-property-delivery-request.v1", "source_mode": "native_source_bound",
        "study_id": parent["study_id"], "electronic": str(path),
    })
    return study, request, path, electronic, calls


def test_native_electronic_only_delivery_preserves_jobs_and_missing_ionic(delivery_case):
    study, request, path, electronic, calls = delivery_case
    result = property_delivery.deliver_p5_properties(study, request)
    assert result["products"]["born"] is None
    assert result["products"]["dielectric"]["epsilon_infinity"] == electronic["tensor"]
    assert result["products"]["dielectric"]["epsilon_static"] is None
    assert result["product_status"]["electronic"]["status"] == "complete"
    assert result["product_status"]["dielectric"]["status"] == "unresolved"
    assert result["native_jobs"] == electronic["native_jobs"]
    assert str(path) in result["source_paths"]["electronic"]
    assert result["methods"]["reference_contribution"] == "electronic"
    assert result["methods"]["comparisons_to_born"] == {}
    assert len(result["observables"]) == 9
    assert str(path) in calls
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False


def test_native_electronic_unresolved_retains_null_and_reason(delivery_case):
    study, request, path, electronic, _ = delivery_case
    electronic.update(tensor=None, status="unresolved", unresolved_reasons=["scf_mesh_gap_not_above_threshold"])
    _write(path, electronic)
    result = property_delivery.deliver_p5_properties(study, request)
    assert result["product_status"]["electronic"]["status"] == "unresolved"
    assert result["product_status"]["electronic"]["unresolved_reasons"] == electronic["unresolved_reasons"]
    assert result["products"]["dielectric"]["epsilon_infinity"] is None
    assert result["products"]["dielectric"]["epsilon_static"] is None
    assert result["observables"] == []


def test_native_electronic_only_delivery_rejects_wrong_study(delivery_case):
    study, request, _, _, _ = delivery_case
    document = json.loads(study.read_text())
    document["study_id"] = "different-study"
    _write(study, document)
    with pytest.raises(ValueError, match="Study"):
        property_delivery.deliver_p5_properties(study, request)


def test_electronic_without_born_cannot_claim_external_input_is_native(delivery_case):
    study, request, path, electronic, _ = delivery_case
    electronic["provenance_kind"] = "external_supplied"
    _write(path, electronic)
    with pytest.raises(ValueError, match="independent native"):
        property_delivery.deliver_p5_properties(study, request)


def test_native_electronic_delivery_rejects_saved_total_without_ionic(delivery_case):
    study, request, _, _, _ = delivery_case
    result = property_delivery.deliver_p5_properties(study, request)
    saved = result["products"]["dielectric"]
    saved["epsilon_static"] = [[7, 0, 0], [0, 7, 0], [0, 0, 7]]
    saved_path = _write(request.parent / "false-total.json", saved)
    document = json.loads(request.read_text())
    document["dielectric"] = str(saved_path)
    _write(request, document)
    with pytest.raises(ValueError, match="epsilon_static"):
        property_delivery.deliver_p5_properties(study, request)


def test_native_electronic_reader_error_is_not_downgraded(delivery_case, monkeypatch):
    study, request, _, _, _ = delivery_case

    def missing_source(*_args, **_kwargs):
        raise FileNotFoundError("missing native HR matrix")

    monkeypatch.setattr(dielectric_response, "bind_native_electronic_input", missing_source)
    with pytest.raises(FileNotFoundError, match="missing native HR matrix"):
        property_delivery.deliver_p5_properties(study, request)
