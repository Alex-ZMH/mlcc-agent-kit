"""Public interface-electrical CLI and saved-product delivery contracts.

All records here are explicit mathematical/software-contract fixtures.  They
do not stand in for a native interface potential or a material result.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import mlcc.interface_electrical as domain
import mlcc.interface_electrical_sources as sources
from mlcc.property_delivery import deliver_interface_electrical


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _study() -> dict[str, object]:
    parents = [
        {"side": "a", "model_id": "ni", "version": "v001", "path": "ni"},
        {"side": "b", "model_id": "bto", "version": "v001", "path": "bto"},
    ]
    interface_request = {
        "schema": "mlcc.layered-interface-request.v1",
        "boundary": ["p", "p", "p"],
    }
    return {
        "schema": "mlcc.study.v1",
        "study_id": "interface-electrical-delivery-fixture",
        "case_id": "math-interface-electrical",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": "ni-bto-interface",
            "version": "v001",
            "spatial_mode": "layered_interface",
        },
        "interface": {
            "schema": "mlcc.interface-study-binding.v1",
            "model_path": "interface-model",
            "parent_models": parents,
            "parent_study_refs": [],
            "request": interface_request,
        },
        "conditions": {"temperature_K": 330.0},
    }


def _selection() -> dict[str, object]:
    return {
        "grid_axis": 2,
        "orientation": 1,
        "boundary": ["p", "p", "p"],
        "derivative": "adjacent_planes_no_wrap",
        "regions": {
            "from": {"region_id": "from", "index_range": [0, 1], "reason": "explicit from window"},
            "to": {"region_id": "to", "index_range": [1, 2], "reason": "explicit to window"},
        },
        "source": "mathematical interface fixture",
    }


def _request(*, potential_path: str | None, selection: dict[str, object] | None) -> dict[str, object]:
    request: dict[str, object] = {
        "schema": "mlcc.interface-electrical-request.v1",
        "study_id": _study()["study_id"],
        "potential_path": potential_path,
        "reference_potential_path": None,
        "reference_description": None,
        "selection": selection,
    }
    if potential_path is None:
        request["missing_source_reason"] = "no saved native interface electrostatic potential"
    return request


def _response() -> dict[str, object]:
    return {
        "schema": "mlcc.interface-electrical-response.v1",
        "status": "mathematical_fixture",
        "evidence_kind": "software_contract_only",
        "target": {"regional_response": {"delta_phi_V": 0.25}},
    }


def _product(study: dict[str, object], *, response: dict[str, object] | None) -> dict[str, object]:
    source_files = {
        "potential": "math-potential.json",
        "task.json": "math-task.json",
        "result.json": "math-result.json",
    }
    return {
        "schema": "mlcc.interface-electrical-product.v1",
        "analysis_scheduler_job_id": "contract-fixture-only",
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": study["case_role"],
        "model_id": study["model"]["model_id"],
        "model_version": study["model"]["version"],
        "interface": deepcopy(study["interface"]),
        "selection": _selection() if response is not None else None,
        "method_set": "interface-electrical-math-v001" if response is not None else None,
        "source": (
            {
                "path": "math-potential.json",
                "method_set": "interface-electrical-math-v001",
                "evidence_kind": "software_contract_only",
            }
            if response is not None
            else None
        ),
        "reference": None,
        "source_files": source_files if response is not None else {},
        "source_refs": ["math-potential.json"] if response is not None else [],
        "response": response,
        "status": "computed_software_contract_only" if response is not None else "unresolved",
        "missing_evidence": [] if response is not None else ["no saved native interface electrostatic potential"],
        "scientific_qualification": False,
        "production_qualification": False,
    }


def test_cli_missing_source_stays_null_through_public_delivery(tmp_path: Path) -> None:
    from mlcc.cli import main

    study = _study()
    study_path = _write(tmp_path / "Study.json", study)
    request_path = _write(
        tmp_path / "request.json",
        _request(potential_path=None, selection=None),
    )
    product_path = tmp_path / "product.json"
    assert main(
        [
            "interface-electrical",
            "--study",
            str(study_path),
            "--request",
            str(request_path),
            "--output",
            str(product_path),
        ]
    ) == 0
    product = json.loads(product_path.read_text(encoding="utf-8"))
    assert product["schema"] == "mlcc.interface-electrical-product.v1"
    assert product["status"] == "unresolved"
    assert product["response"] is None
    assert product["selection"] is None

    delivery_path = tmp_path / "delivery.json"
    assert main(
        [
            "deliver-properties",
            "--study",
            str(study_path),
            "--interface-electrical",
            str(product_path),
            "--output",
            str(delivery_path),
        ]
    ) == 0
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    assert delivery["schema"] == "mlcc.interface-electrical-delivery.v1"
    assert delivery["status"] == "unresolved"
    assert delivery["responses"]["interface_electrical_response"] is None
    assert delivery["missing_evidence"] == product["missing_evidence"]
    assert delivery["analysis_scheduler_job_id"] == product["analysis_scheduler_job_id"]


def test_saved_nonnull_math_response_is_delivered_without_recomputation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    study = _study()
    response = _response()
    product = _product(study, response=response)
    study_path = _write(tmp_path / "Study.json", study)
    product_path = _write(tmp_path / "product.json", product)

    def forbidden(*args, **kwargs):
        raise AssertionError("saved interface-electrical delivery must not recompute")

    monkeypatch.setattr(domain, "calculate_interface_electrical", forbidden)
    monkeypatch.setattr(sources, "build_interface_electrical_product", forbidden)
    result = deliver_interface_electrical(study_path, product_path)
    assert result["interface"] == product["interface"]
    assert result["model_refs"] == study["model"]
    assert result["parent_models"] == study["interface"]["parent_models"]
    assert result["responses"]["interface_electrical_response"] == response
    assert result["potential_source_files"] == product["source_files"]
    assert result["analysis_scheduler_job_id"] == product["analysis_scheduler_job_id"]
    assert result["source"] == product["source"]
    assert result["reference"] is None
    assert result["status"] == product["status"]
    assert result["source_refs"] == product["source_refs"]
    assert result["source_files"]["study"] == str(study_path.resolve())
    assert result["source_files"]["product"] == str(product_path.resolve())
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False


@pytest.mark.parametrize("mismatch", ["study_id", "model", "interface"])
def test_saved_product_rejects_study_model_or_interface_mismatch(
    tmp_path: Path, mismatch: str
) -> None:
    study = _study()
    product = _product(study, response=_response())
    if mismatch == "study_id":
        product["study_id"] = "different-study"
    elif mismatch == "model":
        product["model_id"] = "different-model"
    else:
        product["interface"] = deepcopy(study["interface"])
        product["interface"]["request"]["boundary"] = ["p", "f", "p"]
    with pytest.raises(ValueError, match="(?i)(study|model|interface|identity)"):
        deliver_interface_electrical(
            _write(tmp_path / "Study.json", study),
            _write(tmp_path / f"product-{mismatch}.json", product),
        )


def test_cli_interface_electrical_delivery_rejects_targets(tmp_path: Path) -> None:
    from mlcc.cli import main

    study = _study()
    product = _product(study, response=_response())
    study_path = _write(tmp_path / "Study.json", study)
    product_path = _write(tmp_path / "product.json", product)
    targets_path = _write(tmp_path / "targets.json", {"targets": []})
    with pytest.raises(SystemExit) as error:
        main(
            [
                "deliver-properties",
                "--study",
                str(study_path),
                "--interface-electrical",
                str(product_path),
                "--targets",
                str(targets_path),
                "--output",
                str(tmp_path / "delivery.json"),
            ]
        )
    assert error.value.code == 1


def test_cli_resolves_relative_sources_and_preserves_request_study_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mlcc.cli as cli

    inputs = tmp_path / "inputs"
    run_dir = tmp_path / "different-cwd"
    output_dir = tmp_path / "outputs"
    inputs.mkdir()
    run_dir.mkdir()
    output_dir.mkdir()
    study = _study()
    study_path = _write(inputs / "Study.json", study)
    request_path = _write(
        inputs / "request.json",
        {
            **_request(
                potential_path="../saved/target.json",
                selection=_selection(),
            ),
            "reference_potential_path": "../saved/reference.json",
            "reference_description": "explicit mathematical reference",
        },
    )
    captured: dict[str, object] = {}

    def fake_builder(study_value, request_value):
        captured["study"] = study_value
        captured["request"] = request_value
        return _product(study_value, response=_response())

    monkeypatch.setattr(sources, "build_interface_electrical_product", fake_builder)
    monkeypatch.chdir(run_dir)
    relative_study = str(Path("..") / "inputs" / "Study.json")
    relative_request = str(Path("..") / "inputs" / "request.json")
    relative_output = str(Path("..") / "outputs" / "product.json")
    assert cli.main(
        [
            "interface-electrical",
            "--study",
            relative_study,
            "--request",
            relative_request,
            "--output",
            relative_output,
        ]
    ) == 0

    expected_target = (inputs / "../saved/target.json").resolve()
    expected_reference = (inputs / "../saved/reference.json").resolve()
    request_seen = captured["request"]
    assert request_seen["potential_path"] == str(expected_target)
    assert request_seen["reference_potential_path"] == str(expected_reference)
    assert captured["study"] == study

    product_path = output_dir / "product.json"
    product = json.loads(product_path.read_text(encoding="utf-8"))
    assert product["request_path"] == str(request_path.resolve())
    assert product["study_path"] == str(study_path.resolve())
    assert product["source_refs"][0] == "math-potential.json"
    assert str(request_path.resolve()) in product["source_refs"]
    assert str(study_path.resolve()) in product["source_refs"]

    delivered = deliver_interface_electrical(study_path, product_path)
    assert delivered["source_refs"] == product["source_refs"]
