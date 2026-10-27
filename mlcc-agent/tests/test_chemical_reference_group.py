from __future__ import annotations

import copy

import pytest

from mlcc.defect_thermodynamics import chemical_potential_region


def _identity_fields(method_set: str = "test-abacus-pbe-v001") -> dict[str, str]:
    return {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "method_set": method_set,
        "energy_definition": "test native E_KohnSham in eV",
    }


def _chemical_request() -> dict:
    identity = _identity_fields()
    return {
        "schema": "mlcc.chemical-potential-request.v1",
        "elements": ["Ca", "Zr", "O"],
        "mu_ref": {
            "Ca": {"value_eV_per_atom": -1.0, "source": "test Ca reference", **identity},
            "Zr": {"value_eV_per_atom": -2.0, "source": "test Zr reference", **identity},
            "O": {"value_eV_per_atom": -3.0, "source": "test O reference", **identity},
        },
        "physics": {
            "temperature_model": "0K_DFT_formation_energy",
            "temperature_K": 0.0,
            "pressure_role": "not_applied",
            "oxygen_reservoir": None,
        },
        "host": {
            "phase_id": "CaZrO3",
            "stoichiometry": {"Ca": 1, "Zr": 1, "O": 3},
            "formation_energy_eV": -10.0,
            "source_tasks": ["test-host-reference"],
            **identity,
        },
        "competing_phases": [
            {
                "phase_id": "CaO",
                "stoichiometry": {"Ca": 1, "O": 1},
                "formation_energy_eV": -3.0,
                "source_tasks": ["test-CaO-reference"],
                **identity,
            },
            {
                "phase_id": "ZrO2",
                "stoichiometry": {"Zr": 1, "O": 2},
                "formation_energy_eV": -4.0,
                "source_tasks": ["test-ZrO2-reference"],
                **identity,
            },
        ],
        "selected_delta_mu": {"Ca": -3.0, "Zr": -4.0, "O": -1.0},
    }


def _grouped_request() -> dict:
    request = _chemical_request()
    group = "chemical-reference-set-v021"
    method_sets = {
        "Ca": "element-Ca-method",
        "Zr": "element-Zr-method",
        "O": "element-O-method",
    }
    for element, method_set in method_sets.items():
        request["mu_ref"][element]["method_set"] = method_set
        request["mu_ref"][element]["reference_method_id"] = group
    request["host"]["method_set"] = "host-method"
    request["host"]["reference_method_id"] = group
    for phase in request["competing_phases"]:
        phase["method_set"] = f"{phase['phase_id']}-method"
        phase["reference_method_id"] = group
    return request


def test_explicit_reference_group_preserves_each_method_label_and_host_identity():
    report = chemical_potential_region(_grouped_request())

    assert report["status"] == "feasible"
    assert report["reference"] == {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "method_set": "host-method",
        "energy_definition": "test native E_KohnSham in eV",
        "reference_method_id": "chemical-reference-set-v021",
    }
    assert report["mu_ref"]["Ca"]["method_set"] == "element-Ca-method"
    assert report["mu_ref"]["Ca"]["reference_method_id"] == "chemical-reference-set-v021"
    assert report["host"]["method_set"] == "host-method"
    assert report["host"]["reference_method_id"] == "chemical-reference-set-v021"
    assert report["competing_phases"][0]["method_set"] == "CaO-method"
    assert report["competing_phases"][0]["reference_method_id"] == "chemical-reference-set-v021"


def test_reference_group_mismatch_is_rejected():
    request = _grouped_request()
    request["competing_phases"][0]["reference_method_id"] = "other-reference-set"

    with pytest.raises(ValueError, match="reference_method_id"):
        chemical_potential_region(request)


def test_legacy_inputs_without_group_keep_legacy_method_identity_shape():
    report = chemical_potential_region(_chemical_request())

    assert report["reference"]["method_set"] == "test-abacus-pbe-v001"
    assert "reference_method_id" not in report["reference"]
    assert "reference_method_id" not in report["mu_ref"]["Ca"]
    assert "reference_method_id" not in report["host"]
    assert "reference_method_id" not in report["competing_phases"][0]


def test_mixed_group_declarations_are_rejected():
    request = _grouped_request()
    del request["host"]["reference_method_id"]

    with pytest.raises(ValueError, match="reference_method_id"):
        chemical_potential_region(copy.deepcopy(request))
