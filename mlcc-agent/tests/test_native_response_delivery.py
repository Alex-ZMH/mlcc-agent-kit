"""Only new delivery branches; mocked readers are software-contract evidence."""
import copy
import json

import pytest

from mlcc import dielectric_response, property_delivery
from test_pyatb_static_delivery import delivery_case


@pytest.fixture
def response_case(delivery_case, monkeypatch):
    study, request, _, electronic, _ = delivery_case
    root = request.parent
    born_path = root / "born-family.json"
    gamma_path = root / "raw-gamma.json"
    born_path.write_text(json.dumps({"schema": "mlcc.native-born-branch-family.v1"}))
    gamma_path.write_text(json.dumps({"schema": "mlcc.czo-native-raw-gamma-force.v001"}))
    context = {
        "parent": copy.deepcopy(electronic["parent"]), "atom_ids": electronic["atom_ids"],
        "cell_angstrom": electronic["cell_angstrom"], "volume_A3": electronic["volume_A3"],
        "common_method": electronic["method_identity"],
    }
    born = {
        "schema": "mlcc.born-charge-columns.v1", "provenance_kind": "native_derived",
        "context": context, "common_method": electronic["method_identity"], "unit": "e",
        "atom_ids": electronic["atom_ids"], "full_born_tensors_e": None,
        "missing_columns": [{"atom_id": 0, "cartesian_axis": 0, "reasons": ["physical_branch_unselected"]}],
        "sources": [], "source": {"native_born_family": str(born_path)},
        "source_refs": [str(born_path)], "native_jobs": [{"role": "born_aggregation", "scheduler_job_id": "contract-born"}],
        "status": "unresolved", "unresolved_reasons": ["physical_branch_unselected"],
        "raw_product": {"branch_family": {"selected_branch_shift": None}, "evidence_kind": "software_contract_only"},
        "scientific_qualification": False, "production_qualification": False,
    }
    matrix = [[0.0] * 6 for _ in range(6)]
    matrix[0][1] = 0.3
    gamma = {
        "schema": "mlcc.gamma-force-constants.v1", "provenance_kind": "native_derived",
        "parent": context["parent"], "atom_ids": context["atom_ids"],
        "cell_angstrom": context["cell_angstrom"], "volume_A3": context["volume_A3"],
        "method_identity": context["common_method"], "unit": "eV/angstrom^2",
        "matrix_eV_per_A2": matrix, "matrix_basis": "parent_atom_major_cartesian",
        "electrical_boundary": "fixed_E_zero", "mechanical_boundary": "fixed_cell", "nac": "not_applied",
        "source": {"source_mode": "native_source_bound", "native_raw_product": str(gamma_path)},
        "source_refs": [str(gamma_path)], "native_jobs": [{"role": "gamma_postprocess", "scheduler_job_id": "contract-gamma"}],
        "status": "unresolved", "unresolved_reasons": ["unresolved_raw_nonsymmetric"],
        "raw_product": {"evidence_kind": "software_contract_only", "assembly": {"hermitian_projection_applied": False}},
        "scientific_qualification": False, "production_qualification": False,
    }
    monkeypatch.setattr(dielectric_response, "read_native_born_family", lambda _path: copy.deepcopy(born))
    monkeypatch.setattr(dielectric_response, "read_native_gamma_force", lambda _path: copy.deepcopy(gamma))
    document = json.loads(request.read_text())
    document.update(born=str(born_path), gamma=str(gamma_path))
    request.write_text(json.dumps(document))
    return study, request, born, gamma


def test_native_family_raw_gamma_and_saved_electronic_deliver_unresolved(response_case):
    study, request, born, gamma = response_case
    delivered = property_delivery.deliver_p5_properties(study, request)
    assert delivered["products"]["born"]["full_born_tensors_e"] is None
    assert delivered["products"]["born"]["raw_product"] == born["raw_product"]
    assert delivered["products"]["gamma"]["matrix_eV_per_A2"] == gamma["matrix_eV_per_A2"]
    assert delivered["product_status"]["gamma"]["status"] == "unresolved"
    assert delivered["products"]["dielectric"]["epsilon_static"] is None
    assert "born:physical_branch_unselected" in delivered["products"]["dielectric"]["unresolved_reasons"]
    assert "gamma:unresolved_raw_nonsymmetric" in delivered["products"]["dielectric"]["unresolved_reasons"]
    assert {item["scheduler_job_id"] for item in delivered["native_jobs"]} >= {"contract-born", "contract-gamma"}
    assert delivered["scientific_qualification"] is False
    assert delivered["production_qualification"] is False


def test_native_raw_gamma_can_accompany_electronic_before_born_arrives(response_case):
    study, request, _, gamma = response_case
    document = json.loads(request.read_text())
    del document["born"]
    request.write_text(json.dumps(document))
    delivered = property_delivery.deliver_p5_properties(study, request)
    assert delivered["products"]["born"] is None
    assert delivered["products"]["gamma"]["matrix_eV_per_A2"] == gamma["matrix_eV_per_A2"]
    assert delivered["products"]["dielectric"]["epsilon_static"] is None


def test_native_gamma_wrapper_cannot_change_raw_source_matrix(response_case):
    study, request, _, gamma = response_case
    tampered = copy.deepcopy(gamma)
    tampered["matrix_eV_per_A2"][0][1] = 0.0
    path = request.parent / "tampered-gamma.json"
    path.write_text(json.dumps(tampered))
    document = json.loads(request.read_text())
    document["gamma"] = str(path)
    request.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="differs from its saved source"):
        property_delivery.deliver_p5_properties(study, request)
