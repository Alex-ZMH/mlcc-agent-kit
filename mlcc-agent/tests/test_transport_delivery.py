"""Same-Study transport delivery without repeating band interpolation."""
import json

import pytest

from mlcc.property_delivery import deliver_transport_properties


def _saved(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    task = {
        "study_id": "study-a", "task_id": "transport-fixture", "scheduler_job_id": "fixture-job",
        "model_id": "fixture-model", "model_version": "v001", "method_set": "fixture-method",
        "scheduler_state": "COMPLETED", "exit_code": "0:0", "scientific_status": "fixture",
        "calculation_conditions": {"calculation_kind": "static_dft_reference", "reference_temperature_K": 0},
    }
    (task_dir / "task.json").write_text(json.dumps(task))
    study_path = tmp_path / "study.json"
    study_path.write_text(json.dumps({
        "study_id": "study-a", "model": {"model_id": "fixture-model", "version": "v001"},
    }))
    product = {key: task[key] for key in ("task_id", "scheduler_job_id", "model_id", "model_version", "method_set")}
    product.update(
        schema="mlcc.transport.v001", task_path=str(task_dir), status="unresolved",
        missing=["magnetic_symmetry"], tensors=None,
        units={"seebeck": "V/K", "sigma_over_tau": "S/(m s)",
               "kappa_e_over_tau": "W/(m K s)", "power_factor_over_tau": "W/(m K^2 s)"},
        parameters={"temperatures_K": [330], "chemical_potentials_eV": [0], "energy_reference": "native_fermi"},
        source_files={"task.json": str(task_dir / "task.json")},
    )
    product_path = tmp_path / "transport.json"
    product_path.write_text(json.dumps(product))
    return study_path, product_path, product


def test_missing_transport_stays_missing_in_same_study(tmp_path):
    study, product_path, product = _saved(tmp_path)
    delivery = deliver_transport_properties(study, product_path)
    assert delivery["product"] == product
    assert delivery["missing"] == ["magnetic_symmetry"]
    assert all(item["value"] is None for item in delivery["observables"])
    assert delivery["conditions"]["temperatures_K"] == [330]
    assert delivery["conditions"]["native_source_conditions"]["reference_temperature_K"] == 0
    assert delivery["design_assessment"] == "not_assessed"


@pytest.mark.parametrize("field", ["scheduler_job_id", "units"])
def test_transport_delivery_rejects_wrong_source_or_units(tmp_path, field):
    study, product_path, product = _saved(tmp_path)
    if field == "units":
        product["units"]["sigma_over_tau"] = "S/m"
    else:
        product[field] = "another-job"
    product_path.write_text(json.dumps(product))
    with pytest.raises(ValueError, match=field):
        deliver_transport_properties(study, product_path)


def test_transport_delivery_rejects_other_study(tmp_path):
    study, product_path, _ = _saved(tmp_path)
    record = json.loads(study.read_text())
    record["study_id"] = "another-study"
    study.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="study_id"):
        deliver_transport_properties(study, product_path)


def test_missing_conditions_remain_null_in_delivery(tmp_path):
    study, product_path, product = _saved(tmp_path)
    product["parameters"] = {}
    product["missing"] = ["temperatures_K", "chemical_potentials_eV", "energy_reference"]
    product_path.write_text(json.dumps(product))
    delivery = deliver_transport_properties(study, product_path)
    assert delivery["missing"] == product["missing"]
    assert delivery["conditions"]["temperatures_K"] is None
    assert delivery["conditions"]["chemical_potentials_eV"] is None
    assert delivery["conditions"]["energy_reference"] is None
    assert all(item["value"] is None for item in delivery["observables"])
