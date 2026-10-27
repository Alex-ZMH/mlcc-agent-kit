"""Focused wrapper checks for charge products and Study delivery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc import cli
import mlcc.charge_transition_adapter as transition_adapter
from mlcc.charge_transition_adapter import build_charge_transitions
from mlcc.property_delivery import deliver_charge_properties


def _product(*, q: int, status: str = "computed", chemical: float = -5.0, operations=None):
    method = {
        "engine": "abacus", "abacus_version_target": "3.10.1", "basis_type": "pw",
        "dft_functional": "PBE", "method_set": "pw-v1",
        "pseudopotential_ids": {"O": "O.fixture"},
        "pseudopotential_metadata": {"O": {"valence_electrons": 6}},
        "pseudopotential_treatment": {"O": "norm_conserving"},
    }
    host_model = {"model_id": "model-1", "version": "v1", "path": "/models/model-1"}
    defect_model = {"model_id": f"defect-{q}", "version": "v1", "path": f"/models/defect-{q}"}
    descriptor = {
        "operations": [{"kind": "remove", "element": "O", "index": 0}]
        if operations is None else operations,
        "composition_delta": {"O": -1},
    }
    host = {
        "schema": "mlcc.defect-electronic-reference.v1", "task_id": "host-task",
        "task_path": "/tasks/host-task",
        "study": {"study_id": "study-1", "source_file": "/studies/study.json"},
        "model": host_model, "method": method,
        "charge": {"q": 0, "convention": "q_positive_removes_electrons"},
        "levels": {"vbm_eV": 1.0, "vbm_reference": "levels.vbm"},
        "parent_total_energy_provenance": {"value_eV": -10.0, "definition": "native total energy"},
        "electronic_source_file": "/tasks/host-task/electronic.json",
        "source_files": {"task.json": "/tasks/host-task/task.json"},
        "native_job": {"scheduler_job_id": "host-job", "task_id": "host-task"},
    }
    defect = {
        "schema": "mlcc.defect-electronic-reference.v1", "task_id": f"defect-task-{q}",
        "task_path": f"/tasks/defect-task-{q}",
        "study": {"study_id": f"defect-study-{q}", "source_file": f"/studies/defect-{q}.json"},
        "model": defect_model, "parent_model": host_model, "method": method,
        "charge": {"q": q, "convention": "q_positive_removes_electrons"},
        "levels": {"vbm_eV": None, "vbm_reference": "levels.vbm"},
        "parent_total_energy_provenance": {"value_eV": -9.0 + q, "definition": "native total energy"},
        "defect_descriptor": descriptor,
        "native_job": {"scheduler_job_id": f"defect-job-{q}", "task_id": f"defect-task-{q}"},
    }
    chemical_reference = {
        "schema": "mlcc.chemical-reference-delivery.v1", "study_id": "study-1",
        "chemical_point": None,
        "mathematical_chemical_point": {
            "mu_eV_per_atom": {"O": chemical}, "engine": "abacus",
            "engine_version": "3.10.1", "method_set": "pw-v1",
            "energy_definition": "native total energy", "source_reference": "mu.json",
            "reference_set_id": "mu-1", "evidence_kind": "software_contract_only",
        },
    }
    host_task = {"task_id": host["task_id"], "task_path": host["task_path"], "study": host["study"]}
    physical_method = {
        "engine": "abacus", "engine_version": "3.10.1", "basis_type": "pw",
        "dft_functional": "PBE", "method_set": "pw-v1",
        "pseudopotential_ids": {"O": "O.fixture"},
        "pseudopotential_metadata": {"O": {"valence_electrons": 6}},
        "pseudopotential_treatment": {"O": "norm_conserving"},
    }
    host_vbm = {
        "value_eV": 1.0, "reference": "levels.vbm",
        "source": "references.host.levels.vbm_eV",
        "electronic_source_file": host["electronic_source_file"],
    }
    identity = {
        "host_task": host_task, "host_model": host_model,
        "physical_method": physical_method, "energy_definition": "native total energy",
        "charge": defect["charge"],
        "chemical_source": {
            "source_reference": "mu.json", "reference_set_id": "mu-1",
            "evidence_kind": "software_contract_only",
        },
        "chemical_potential_eV_per_atom": {"O": chemical}, "host_vbm": host_vbm,
        "host_source": {
            "task_id": host["task_id"], "task_path": host["task_path"], "study": host["study"],
            "model": host_model, "method": method,
            "parent_total_energy_provenance": host["parent_total_energy_provenance"],
            "levels": host["levels"], "electronic_source_file": host["electronic_source_file"],
            "source_files": host["source_files"],
        },
        "method_comparison": {"same_recorded_comparison_fields": True},
        "chemical_study_id": "study-1",
        "defect_task": {
            "task_id": defect["task_id"], "task_path": defect["task_path"], "study": defect["study"],
        },
    }
    formation = None
    if status != "missing":
        formation = {
            "schema": "mlcc.formation-energy.v1", "q": q,
            "charge_convention": "q_positive_removes_electrons",
            "Edef_eV": -9.0 + q, "Ehost_eV": -10.0,
            "deltaN": {"O": -1}, "mu_eV_per_atom": {"O": chemical},
            "energy_difference_eV": 1.0 + q, "chemical_potential_term_eV": chemical,
            "correction": {"total_eV": 0.0}, "vbm_eV": 1.0,
        }
    return {
        "schema": "mlcc.charged-formation.v1", "formation_id": f"state-{q}",
        "status": status, "missing": [] if status != "missing" else ["correction"],
        "formation": formation, "chemical_reference": chemical_reference,
        "reference_identity": identity,
        "references": {
            "schema": "mlcc.defect-reference-pair.v1", "host": host, "defect": defect,
            "method_comparison": {"same_recorded_comparison_fields": True},
        },
        "source_paths": {"correction_path": "/sources/correction.json"},
    }


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_transition_adapter_keeps_missing_formation_and_does_not_envelope(tmp_path):
    first = _write(tmp_path / "q0.json", _product(q=0))
    second = _write(tmp_path / "q1.json", _product(q=1, status="missing"))
    request = _write(tmp_path / "request.json", {
        "schema": "mlcc.charge-transition-request.v1", "transition_id": "transition-1",
        "formation_paths": {"q0": first.name, "q1": second.name}, "ef_interval_eV": [-1.0, 2.0],
    })
    result = build_charge_transitions(request)
    assert result["schema"] == "mlcc.charge-transition-collection.v1"
    assert result["status"] == "missing"
    assert result["envelope"] is None
    assert "q1:correction" in result["missing"]
    assert result["products"]["q0"]["formation"]["q"] == 0
    assert result["source_paths"]["q0"] == str(first.resolve())


def test_transition_adapter_success_passes_formations_and_source_refs(tmp_path, monkeypatch):
    first = _write(tmp_path / "q0.json", _product(q=0))
    second = _write(tmp_path / "q1.json", _product(q=1))
    request = _write(tmp_path / "request.json", {
        "schema": "mlcc.charge-transition-request.v1", "transition_id": "transition-1",
        "formation_paths": {"q0": first.name, "q1": second.name}, "ef_interval_eV": [-1.0, 2.0],
    })
    captured = {}

    def fake_envelope(records, interval, *, source_refs):
        captured.update(records=records, interval=interval, source_refs=source_refs)
        return {"schema": "mlcc.charge-transitions.v1", "source_refs": source_refs}

    monkeypatch.setattr(transition_adapter, "charge_transition_envelope", fake_envelope)
    result = build_charge_transitions(request)
    assert result["status"] == "computed"
    assert result["envelope"]["schema"] == "mlcc.charge-transitions.v1"
    assert captured["records"]["q0"] == _product(q=0)["formation"]
    assert captured["interval"] == [-1.0, 2.0]
    assert captured["source_refs"]["q0"] == f"{first.resolve()}#/formation"


def test_transition_adapter_rejects_different_common_chemical_point(tmp_path):
    first = _write(tmp_path / "q0.json", _product(q=0))
    second = _write(tmp_path / "q1.json", _product(q=1, chemical=-4.0))
    request = _write(tmp_path / "request.json", {
        "schema": "mlcc.charge-transition-request.v1", "transition_id": "transition-1",
        "formation_paths": {"q0": first.name, "q1": second.name}, "ef_interval_eV": [-1.0, 2.0],
    })
    with pytest.raises(ValueError, match="common host/reference identity"):
        build_charge_transitions(request)


def test_charge_delivery_preserves_product_status_and_source(tmp_path):
    model_path = tmp_path / "model"
    study = _write(tmp_path / "study.json", {
        "study_id": "study-1", "model": {"model_id": "model-1", "version": "v1", "path": str(model_path)},
    })
    product = _product(q=1, status="missing")
    product["references"]["defect"]["study"] = {"study_id": "study-1"}
    product["references"]["defect"]["model"] = {
        "model_id": "model-1", "version": "v1", "path": str(model_path),
    }
    product_path = _write(tmp_path / "formation.json", product)
    result = deliver_charge_properties(study, product_path)
    assert result["status"] == "missing"
    assert result["missing"] == product["missing"]
    assert result["native_jobs"] == [product["references"]["host"]["native_job"], product["references"]["defect"]["native_job"]]
    assert result["product"] == product


def test_cli_forwards_charge_delivery_source(monkeypatch, tmp_path):
    calls = {}

    def fake_delivery(study, product, targets):
        calls.update(study=study, product=product, targets=targets)
        return {"status": "missing"}

    monkeypatch.setattr(cli, "deliver_charge_properties", fake_delivery)
    output = tmp_path / "delivery.json"
    rc = cli.main([
        "deliver-properties", "--study", str(tmp_path / "study.json"),
        "--charged-formation", str(tmp_path / "formation.json"),
        "--targets", str(tmp_path / "targets.json"), "--output", str(output),
    ])
    assert rc == 0
    assert calls == {
        "study": tmp_path / "study.json", "product": tmp_path / "formation.json",
        "targets": tmp_path / "targets.json",
    }
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "missing"
