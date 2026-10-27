"""Saved directional-NAC consumer checks for the shared P5 Study delivery.

The producer result is generated once by the focused NAC module checks and is
passed through ``MLCC_NAC_RESULT``.  These tests only consume that saved JSON
and the job197 Born/epsilon inputs; all negative cases mutate copies and never
invoke the NAC solver.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest

from mlcc.property_delivery import deliver_p5_properties


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def nac_case(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    raw_result = os.environ["MLCC_NAC_RESULT"]
    result_path = Path(raw_result).expanduser().resolve()
    assert result_path.is_file(), result_path
    result = _read(result_path)
    parent = result["parent"]
    born_input = result["born_input"]
    electronic_input = result["electronic_input"]
    assert isinstance(parent, dict)
    assert isinstance(born_input, dict)
    assert isinstance(electronic_input, dict)
    study_path = Path(parent["study_path"]).expanduser().resolve()
    born_path = Path(born_input["path"]).expanduser().resolve()
    electronic_path = Path(electronic_input["path"]).expanduser().resolve()
    assert study_path.is_file(), study_path
    assert born_path.is_file(), born_path
    assert electronic_path.is_file(), electronic_path
    study = _read(study_path)
    assert study["study_id"] == parent["study_id"]
    request_dir = tmp_path_factory.mktemp("nac-delivery-request")

    def request_for(nac_path: Path, *, electronic: Path = electronic_path) -> Path:
        request = {
            "schema": "mlcc.p5-property-delivery-request.v1",
            "study_id": study["study_id"],
            "source_mode": result["source_mode"],
            "born": str(born_path),
            "electronic": str(electronic),
            "nac": str(nac_path),
        }
        path = request_dir / f"request-{len(list(request_dir.glob('request-*.json')))}.json"
        path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        return path

    return {
        "result_path": result_path,
        "result": result,
        "study_path": study_path,
        "born_path": born_path,
        "electronic_path": electronic_path,
        "request_for": request_for,
        "request_dir": request_dir,
    }


def _deliver(case: dict[str, Any], request_path: Path) -> dict[str, Any]:
    return deliver_p5_properties(case["study_path"], request_path)


def test_saved_nac_keeps_same_study_and_unqualified_status(nac_case: dict[str, Any]):
    result = nac_case["result"]
    delivery = _deliver(nac_case, nac_case["request_for"](nac_case["result_path"]))

    assert delivery["study_id"] == result["parent"]["study_id"]
    assert delivery["products"]["nac"] == result
    assert result["hermitianize"] is False
    assert result["born_epsilon_symmetrized"] is False
    assert result["electronic_input"]["electrical_boundary"] == "fixed_E_zero"
    assert result["electronic_input"]["mechanical_boundary"] == "fixed_cell"
    assert result["electronic_input"]["ions"] == "clamped"
    assert delivery["product_status"]["nac"]["status"] == "complete"
    assert delivery["product_status"]["nac"]["source_mode"] == "software_math_only"
    assert delivery["product_status"]["nac"]["scientific_qualification"] is False
    assert delivery["product_status"]["nac"]["numerical_qualification"] is False
    assert delivery["product_status"]["nac"]["production_qualification"] is False
    assert delivery["qualification"]["production_qualification"] is False
    assert delivery["methods"]["comparisons_to_born"]["nac"]["same_physical_method"] is True
    assert str(nac_case["born_path"]) in delivery["source_paths"]["nac"]
    assert str(nac_case["electronic_path"]) in delivery["source_paths"]["nac"]
    nac_context = dict(delivery["contexts"]["nac"])
    born_context = dict(delivery["contexts"]["born"])
    assert nac_context.pop("volume_A3") == pytest.approx(born_context.pop("volume_A3"), rel=0.0, abs=1e-12)
    assert nac_context == born_context


def test_nac_does_not_substitute_gamma_or_ionic_hessian(nac_case: dict[str, Any]):
    delivery = _deliver(nac_case, nac_case["request_for"](nac_case["result_path"]))

    assert delivery["products"]["gamma"] is None
    assert delivery["product_status"]["gamma"]["status"] == "missing"
    assert delivery["products"]["ionic"] is None
    # The recombined dielectric remains a separate unresolved product and never
    # consumes the directional NAC matrix as an ionic Hessian.
    assert delivery["products"]["dielectric"].get("delta_epsilon_ionic") is None


def test_saved_nac_parent_method_mutation_is_rejected(nac_case: dict[str, Any]):
    mutated = copy.deepcopy(nac_case["result"])
    mutated["method_identity"] = {**mutated["method_identity"], "method": "different-method"}
    path = nac_case["request_dir"] / "mutated-method-nac.json"
    path.write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="context differs from Born context"):
        _deliver(nac_case, nac_case["request_for"](path))


def test_saved_nac_study_mutation_is_rejected(nac_case: dict[str, Any]):
    mutated = copy.deepcopy(nac_case["result"])
    mutated["parent"] = {**mutated["parent"], "study_id": "different-study"}
    path = nac_case["request_dir"] / "mutated-study-nac.json"
    path.write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="context differs from Born context"):
        _deliver(nac_case, nac_case["request_for"](path))


def test_saved_nac_input_path_conflict_is_rejected(nac_case: dict[str, Any]):
    mutated = copy.deepcopy(nac_case["result"])
    mutated["born_input"] = {
        **mutated["born_input"],
        "path": str(nac_case["electronic_path"]),
    }
    path = nac_case["request_dir"] / "mutated-input-path-nac.json"
    path.write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="born_input.path differs"):
        _deliver(nac_case, nac_case["request_for"](path))


def test_saved_nac_born_tensor_snapshot_conflict_is_rejected(nac_case: dict[str, Any]):
    mutated = copy.deepcopy(nac_case["result"])
    tensor = mutated["born_input"]["full_born_tensors_e"]
    tensor[0][0][0] = float(tensor[0][0][0]) + 1.0
    path = nac_case["request_dir"] / "mutated-born-tensor-nac.json"
    path.write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="saved Born tensor differs"):
        _deliver(nac_case, nac_case["request_for"](path))
