"""Saved-source adapter checks; fixtures are software-contract-only math data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mlcc.thermal_stress_sources as sources


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _base(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    study = {
        "study_id": "contract-study", "case_id": "contract-case", "case_role": "engineering_fixture",
        "fixture": True,
        "model": {"model_id": "contract-model", "version": "v001"},
    }
    study_file = _write(tmp_path / "study.json", study)
    task_dir = tmp_path / "task"
    task = {
        "task_id": "contract-stress", "study_id": study["study_id"], "case_id": study["case_id"],
        "case_role": study["case_role"], "model_id": "contract-model", "model_version": "v001",
        "method": {"schema": "contract-method"}, "method_set": "contract-method-v001",
        "potential": {"potential_id": "contract-potential", "version": "v001"},
        "protocol": {"kind": "run0", "purpose": "interface_local_stress"}, "runner": "slurm",
        "scheduler_job_id": "contract-stress", "scheduler_state": "COMPLETED", "exit_code": "0:0",
        "status": "COMPLETED", "scientific_status": "software_contract_only",
    }
    task_file = _write(task_dir / "task.json", task)
    _write(task_dir / "atom-map.json", {
        "schema": "mlcc.lammps-atom-map.v1", "model_id": "contract-model", "version": "v001",
        "source_atom_ids": [0, 1],
        "source_cell_angstrom": [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]],
    })
    product = {
        "schema": "mlcc.local-stress-product.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"], "fixture": True,
        "model_id": "contract-model", "model_version": "v001", "task_id": task["task_id"],
        "task_path": str(task_file), "status": "partial", "protocol": task["protocol"],
        "source_task": {"scheduler_job_id": task["scheduler_job_id"], "scheduler_state": task["scheduler_state"],
                        "exit_code": task["exit_code"], "status": task["status"],
                        "scientific_status": task["scientific_status"]},
        "local_stress": {
            "schema": "mlcc.local-stress-response.v1",
            "units": {"stress": "GPa", "time": "ps", "volume": "angstrom^3"},
            "stress_volume_basis": "lammps_prism", "contribution": "virial",
            "kinetic_included": False, "stress_volume_component_order": ["xx", "yy", "zz", "xy", "xz", "yz"],
            "source_cell_angstrom": [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]],
            "selected_frames": [{"step": 0, "physical_time_ps": 0.0}], "raw_frames": [], "missing_evidence": [],
            "regions": [{
                "region_id": "whole", "atom_ids": [0, 1],
                "volume_source": {"volume_angstrom3": 8.0, "volume_definition": "fixed cell"},
                "tensor_basis": "source_cartesian", "stress_sign": "tension_positive",
                "stress_GPa": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "missing_evidence": [],
            }],
        },
        "missing_evidence": [], "production_qualified": False,
    }
    product_file = _write(tmp_path / "local-product.json", product)
    request_file = _write(tmp_path / "request.json", {
        "schema": "mlcc.thermal-stress-request.v1", "reference": None,
        "states": [{"state_id": "s0", "region_id": "whole", "stress_product_path": str(product_file),
                     "temperature_history_path": None, "mechanical_history_path": None,
                     "temperature_product_path": None}],
    })
    return study, study_file, product_file, request_file


def test_build_binds_saved_local_product_once(tmp_path, monkeypatch):
    study, study_file, _, request_file = _base(tmp_path)
    calls = []

    def domain(reference, states):
        calls.append((reference, states))
        return {"schema": "mlcc.thermal-stress-response.v1", "status": "unresolved",
                "states": [], "missing_evidence": []}

    monkeypatch.setattr(sources, "thermal_stress_change", domain)
    product = sources.build_thermal_stress(study_file, request_file)
    assert len(calls) == 1
    assert product["sources"][0]["source_kind"] == "local_stress_product"
    assert calls[0][1][0]["stress_GPa"] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert calls[0][1][0]["frame_keys"] == [{"step": 0, "physical_time_ps": 0.0}]
    assert product["production_qualified"] is False


def test_temperature_product_is_context_and_not_region_history(tmp_path, monkeypatch):
    study, study_file, _, _ = _base(tmp_path)
    task_dir = tmp_path / "thermal-task"
    task = {
        "task_id": "contract-thermal", "study_id": study["study_id"], "case_id": study["case_id"],
        "case_role": study["case_role"], "model_id": "contract-model", "model_version": "v001",
        "method": {"schema": "contract-method"}, "method_set": "contract-thermal-v001",
        "potential": {"potential_id": "contract-potential", "version": "v001"},
        "protocol": {"kind": "md", "purpose": "interface_thermal_response"}, "runner": "slurm",
        "scheduler_job_id": "contract-thermal", "scheduler_state": "COMPLETED", "exit_code": "0:0",
        "status": "COMPLETED", "scientific_status": "software_contract_only",
    }
    task_file = _write(task_dir / "task.json", task)
    _write(task_dir / "atom-map.json", {
        "schema": "mlcc.lammps-atom-map.v1", "model_id": "contract-model", "version": "v001",
        "source_atom_ids": [0, 1], "source_cell_angstrom": [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]],
    })
    thermal_file = _write(tmp_path / "thermal.dat", "saved fixture\n")
    thermal = {
        "schema": "mlcc.interface-thermal-product.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"], "fixture": True,
        "model_id": "contract-model", "model_version": "v001", "task_id": task["task_id"],
        "task_path": str(task_file), "status": "partial", "protocol": task["protocol"],
        "analysis_request": {"kind": "software_contract_only"},
        "thermal_response": {"status": "unresolved", "source_kind": "mathematical_fixture"},
        "source_task": {"scheduler_job_id": "contract-thermal", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
        "native_thermal": {"schema": "mlcc.lammps-thermal-result.v1", "profile_frames": [
            {"step": 0, "physical_time_ps": 0.0, "total_count": 2.0, "bins": []}],
            "source_files": {"thermal-energy.dat": str(thermal_file)}},
        "missing_evidence": ["temperature_bins_AB"], "production_qualified": False,
    }
    thermal_product = _write(tmp_path / "thermal-product.json", thermal)
    request = _write(tmp_path / "thermal-request.json", {
        "schema": "mlcc.thermal-stress-request.v1", "reference": None,
        "states": [{"state_id": "temperature-only", "region_id": None, "stress_product_path": None,
                     "temperature_history_path": None, "mechanical_history_path": None,
                     "temperature_product_path": str(thermal_product)}],
    })
    seen = []

    def domain(reference, states):
        seen.extend(states)
        return {"schema": "mlcc.thermal-stress-response.v1", "status": "unresolved",
                "states": [], "missing_evidence": []}

    monkeypatch.setattr(sources, "thermal_stress_change", domain)
    product = sources.build_thermal_stress(study_file, request)
    assert seen[0]["temperature_history"] is None
    assert seen[0]["temperature_context"]["profile_frames"][0]["total_count"] == 2.0
    assert "temperature_bin_to_region_atom_mapping" in seen[0]["missing_evidence"]
    assert product["sources"][0]["source_kind"] == "interface_thermal_product"
    assert product["production_qualified"] is False


def test_saved_source_rebind_keeps_contract_record(tmp_path):
    study, study_file, product_file, _ = _base(tmp_path)
    study_value = json.loads(study_file.read_text())
    record = sources.bind_thermal_source(product_file, study_value)
    assert record["product_path"] == str(product_file.resolve())
    assert record["native_job"]["scheduler_job_id"] == "contract-stress"
    assert record["source_kind"] == "local_stress_product"


def test_saved_source_rejects_wrong_saved_job_and_units(tmp_path):
    study, study_file, product_file, _ = _base(tmp_path)
    product = json.loads(product_file.read_text())
    product["source_task"]["scheduler_job_id"] = "wrong-job"
    _write(product_file, product)
    with pytest.raises(ValueError, match="source_task.scheduler_job_id"):
        sources.bind_thermal_source(product_file, json.loads(study_file.read_text()))
    product["source_task"]["scheduler_job_id"] = "contract-stress"
    product["local_stress"]["units"]["stress"] = "bar"
    _write(product_file, product)
    with pytest.raises(ValueError, match="units.stress"):
        sources.bind_thermal_source(product_file, json.loads(study_file.read_text()))


def test_history_task_mismatch_is_an_original_binding_error(tmp_path, monkeypatch):
    study, study_file, product_file, _ = _base(tmp_path)
    history = _write(tmp_path / "temperature.json", {
        "schema": "mlcc.region-temperature-history.v1", "model_id": "contract-model", "model_version": "v001",
        "task_id": "wrong-task", "native_job_id": "wrong-job", "region_id": "whole", "atom_ids": [0, 1],
        "samples": [{"step": 0, "physical_time_ps": 0.0, "temperature_K": 300.0}],
        "source_files": {},
    })
    request = _write(tmp_path / "history-request.json", {
        "schema": "mlcc.thermal-stress-request.v1", "reference": None,
        "states": [{"state_id": "s0", "region_id": "whole", "stress_product_path": str(product_file),
                     "temperature_history_path": str(history), "mechanical_history_path": None,
                     "temperature_product_path": None}],
    })
    monkeypatch.setattr(sources, "thermal_stress_change", lambda *args: {})
    with pytest.raises(ValueError, match="task_id"):
        sources.build_thermal_stress(study_file, request)


def test_mechanical_history_protocol_is_bound_to_stress_protocol(tmp_path, monkeypatch):
    study, study_file, product_file, _ = _base(tmp_path)
    history = _write(tmp_path / "mechanical.json", {
        "schema": "mlcc.mechanical-history.v1", "model_id": "contract-model", "model_version": "v001",
        "task_id": "contract-stress", "native_job_id": "contract-stress", "region_id": "whole", "atom_ids": [0, 1],
        "protocol": {"kind": "different"},
        "samples": [{"step": 0, "physical_time_ps": 0.0, "constraint": {}}], "source_files": {},
    })
    request = _write(tmp_path / "mechanical-request.json", {
        "schema": "mlcc.thermal-stress-request.v1", "reference": None,
        "states": [{"state_id": "s0", "region_id": "whole", "stress_product_path": str(product_file),
                     "temperature_history_path": None, "mechanical_history_path": str(history),
                     "temperature_product_path": None}],
    })
    monkeypatch.setattr(sources, "thermal_stress_change", lambda *args: {})
    with pytest.raises(ValueError, match="mechanical-history.v1.protocol"):
        sources.build_thermal_stress(study_file, request)


def test_saved_reference_and_target_histories_reach_real_domain(tmp_path):
    study, study_file, reference_file, _ = _base(tmp_path)
    target = json.loads(reference_file.read_text())
    target["local_stress"]["regions"][0]["stress_GPa"] = [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]]
    target_file = _write(tmp_path / "target-product.json", target)
    protocol = {"kind": "run0", "purpose": "interface_local_stress"}
    cell = [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]]

    def history(path: Path, temperature: float) -> Path:
        return _write(path, {
            "schema": "mlcc.region-temperature-history.v1", "model_id": "contract-model", "model_version": "v001",
            "task_id": "contract-stress", "native_job_id": "contract-stress", "region_id": "whole", "atom_ids": [0, 1],
            "samples": [{"step": 0, "physical_time_ps": 0.0, "temperature_K": temperature}],
            "source_files": {"table": str(path)},
        })

    def mechanical(path: Path) -> Path:
        return _write(path, {
            "schema": "mlcc.mechanical-history.v1", "model_id": "contract-model", "model_version": "v001",
            "task_id": "contract-stress", "native_job_id": "contract-stress", "region_id": "whole", "atom_ids": [0, 1],
            "protocol": protocol, "samples": [{"step": 0, "physical_time_ps": 0.0, "constraint": {
                "cell_angstrom": cell, "boundary": ["p", "p", "p"], "fixed_atom_ids": [],
                "loading": {"kind": "none"}}}], "source_files": {"table": str(path)},
        })

    ref_temp = history(tmp_path / "ref-temperature.json", 300.0)
    ref_mechanical = mechanical(tmp_path / "ref-mechanical.json")
    target_temp = history(tmp_path / "target-temperature.json", 400.0)
    target_mechanical = mechanical(tmp_path / "target-mechanical.json")
    entry = lambda product, temp, mech, state_id: {
        "state_id": state_id, "region_id": "whole", "stress_product_path": str(product),
        "temperature_history_path": str(temp), "mechanical_history_path": str(mech),
        "temperature_product_path": None,
    }
    request = _write(tmp_path / "positive-request.json", {
        "schema": "mlcc.thermal-stress-request.v1",
        "reference": entry(reference_file, ref_temp, ref_mechanical, "reference"),
        "states": [entry(target_file, target_temp, target_mechanical, "target")],
    })
    product = sources.build_thermal_stress(study_file, request)
    result = product["response"]["states"][0]
    assert result["classification"] == "same_constraint_thermal_stress_change"
    assert result["thermal_stress_change_GPa"] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def test_missing_saved_product_preserves_file_error(tmp_path):
    study = {"study_id": "s", "case_id": "c", "case_role": "engineering_fixture",
             "model": {"model_id": "m", "version": "v001"}}
    with pytest.raises(FileNotFoundError):
        sources.bind_thermal_source(tmp_path / "missing.json", study)
