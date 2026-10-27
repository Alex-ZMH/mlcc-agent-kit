"""Saved-source adapter tests for interface electrostatic response.

These tests are prepared for the v100 Slurm acceptance slice.  The fixtures
are explicitly mathematical/software-contract records; they never establish a
native interface calculation or a material qualification.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mlcc.interface_electrical_sources as sources
from mlcc.electrostatic_potential import BOHR_TO_ANGSTROM, RY_TO_EV


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _selection(axis: int = 2, boundary: list[str] | None = None) -> dict:
    return {
        "grid_axis": axis,
        "orientation": 1,
        "boundary": list(boundary or ["p", "p", "p"]),
        "derivative": "adjacent_planes_no_wrap",
        "regions": {
            "from": {"region_id": "a", "index_range": [0, 1], "reason": "explicit side-a window"},
            "to": {"region_id": "b", "index_range": [1, 2], "reason": "explicit side-b window"},
        },
        "source": "saved interface potential contract fixture",
    }


def _study(root: Path) -> dict:
    model_dir = root / "interface-model"
    parents = [
        {"side": "a", "model_id": "ni", "version": "v001", "path": str(root / "ni")},
        {"side": "b", "model_id": "bto", "version": "v001", "path": str(root / "bto")},
    ]
    interface_request = {"schema": "mlcc.layered-interface-request.v1", "boundary": ["p", "p", "p"]}
    model = {
        "schema": "mlcc.model.v1",
        "model_id": "ni-bto-interface",
        "version": "v001",
        "spatial_mode": "layered_interface",
        "boundary": ["p", "p", "p"],
        "pbc": [True, True, True],
        "parent_models": parents,
        "interface_file": "layered-interface.json",
        "interface_geometry": {"normal_cartesian": [0.0, 0.0, 1.0]},
        "lattice_angstrom": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "atom_ids": [0, 1],
        "atoms": [
            {"atom_id": 0, "element": "Ni", "cart_coords_angstrom": [0.0, 0.0, 0.0]},
            {"atom_id": 1, "element": "Ba", "cart_coords_angstrom": [0.5, 0.5, 0.5]},
        ],
    }
    record = {
        "schema": "mlcc.layered-interface.v1",
        "model_id": model["model_id"],
        "version": model["version"],
        "request": interface_request,
        "parent_models": parents,
        "geometry": {"normal_cartesian": [0.0, 0.0, 1.0]},
    }
    _write(model_dir / "model.json", model)
    _write(model_dir / "layered-interface.json", record)
    return {
        "schema": "mlcc.study.v1",
        "study_id": "ni-bto-interface-study",
        "case_id": "interface-electrical-fixture",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": model["model_id"],
            "version": model["version"],
            "spatial_mode": "layered_interface",
        },
        "interface": {
            "schema": "mlcc.interface-study-binding.v1",
            "model_path": str(model_dir),
            "parent_models": parents,
            "request": interface_request,
        },
    }


def _potential(root: Path, *, model_id: str = "ni-bto-interface", model_version: str = "v001") -> Path:
    model_path = root / "interface-model" / "model.json"
    source_model_path = root.parent / "interface-model" / "model.json"
    if source_model_path.is_file() and source_model_path != model_path:
        model = json.loads(source_model_path.read_text(encoding="utf-8"))
    else:
        model = {
            "schema": "mlcc.model.v1",
            "model_id": model_id,
            "version": model_version,
            "spatial_mode": "layered_interface",
            "boundary": ["p", "p", "p"],
            "interface_file": "layered-interface.json",
            "interface_geometry": {"normal_cartesian": [0.0, 0.0, 1.0]},
            "lattice_angstrom": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "atom_ids": [0, 1],
            "atoms": [
                {"atom_id": 0, "element": "Ni", "cart_coords_angstrom": [0.0, 0.0, 0.0]},
                {"atom_id": 1, "element": "Ba", "cart_coords_angstrom": [0.5, 0.5, 0.5]},
            ],
        }
    model["model_id"], model["version"] = model_id, model_version
    _write(model_path, model)
    record_path = model_path.parent / "layered-interface.json"
    source_record = source_model_path.parent / "layered-interface.json"
    if source_record.is_file() and source_record != record_path:
        record_path.write_text(source_record.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        _write(
            record_path,
            {
                "schema": "mlcc.layered-interface.v1",
                "model_id": model_id,
                "version": model_version,
                "request": {"schema": "mlcc.layered-interface-request.v1", "boundary": ["p", "p", "p"]},
                "parent_models": [
                    {"side": "a", "model_id": "ni", "version": "v001", "path": str(root / "ni")},
                    {"side": "b", "model_id": "bto", "version": "v001", "path": str(root / "bto")},
                ],
                "geometry": {"normal_cartesian": [0.0, 0.0, 1.0]},
            },
        )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    model["parent_models"] = record["parent_models"]
    model["pbc"] = [True, True, True]
    _write(model_path, model)
    method = {
        "method_set": "abacus-interface-fixture", "engine": "abacus", "abacus_version_target": "3.10.1",
        "stage": "scf", "model_id": model_id, "version": model_version, "dft_functional": "PBE", "basis_type": "pw",
        "nspin": 1, "lspinorb": False, "noncolin": False, "initial_moments_muB_by_element": {"Ni": 0, "Ba": 0},
        "occupations": "fixed", "smearing_method": None, "symmetry": -1, "net_charge": 0,
        "nelec": 0, "nelec_delta": 0, "charge_convention": "positive q removes q electrons", "element_order": ["Ba", "Ni"],
        "kpoints": [1, 1, 1], "kpoint_rule": "explicit_mesh", "parameters": {"ecutwfc_Ry": 100, "scf_thr": 1e-11},
        "pseudopotential_ids": {"Ni": "Ni-mathematical", "Ba": "Ba-mathematical"},
        "pseudopotential_metadata": {element: {"element": element, "functional": "PBE", "valence_electrons_per_atom": 2,
                                             "relativity": "scalar", "has_spin_orbit": False, "type": "NC"}
                                     for element in ("Ba", "Ni")},
        "pseudopotential_treatment": {"Ni": "scalar", "Ba": "scalar"}, "suffix": root.name,
    }
    source_ids = list(model["atom_ids"])
    cell = model["lattice_angstrom"]
    atom_map = {
        "schema": "mlcc.abacus-atom-map.v1",
        "abacus_version_target": "3.10.1",
        "model_id": model_id,
        "version": model_version,
        "source_atom_ids": source_ids,
        "element_order": ["Ba", "Ni"],
        "coordinate_unit": "Direct",
        "lattice_constant_bohr": 1.0 / BOHR_TO_ANGSTROM,
        "abacus_order": [
            {"abacus_index": 0, "source_index": 1, "atom_id": 1, "element": "Ba"},
            {"abacus_index": 1, "source_index": 0, "atom_id": 0, "element": "Ni"},
        ],
    }
    mapped_atoms = [
        {"abacus_index": 0, "atom_id": 1, "source_index": 1, "element": "Ba", "position_angstrom": [0.5, 0.5, 1.5]},
        {"abacus_index": 1, "atom_id": 0, "source_index": 0, "element": "Ni", "position_angstrom": [1.0, 0.0, 0.0]},
    ]
    final_atoms = {
        "symbols": ["Ni", "Ba"],
        "positions_angstrom": [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        "cell_angstrom": cell,
        "pbc": [True, True, True],
    }
    task = {
        "task_id": "fixture-task", "scheduler_job_id": "fixture-job", "method_set": method["method_set"],
        "study_id": "ni-bto-interface-study", "model_id": model_id, "model_version": model_version,
        "runner": "slurm", "status": "COMPLETED", "scheduler_state": "COMPLETED", "exit_code": "0:0",
        "engine": "abacus", "engine_version": "3.10.1", "calculation": "scf",
        "calculation_conditions": {"cell_constraint": "fixed_cell", "net_charge": 0},
    }
    result = {
        "task_id": task["task_id"], "scheduler_job_id": task["scheduler_job_id"],
        "method_set": task["method_set"], "electronic_converged": True,
        "stage": "scf",
        "atom_ids": source_ids, "final_atoms": final_atoms,
    }
    saved_study = {
        "schema": "mlcc.study.v1", "study_id": task["study_id"],
        "model": {"model_id": model_id, "version": model_version, "spatial_mode": "layered_interface"},
        "interface": {"schema": "mlcc.interface-study-binding.v1",
                      "model_path": str(source_model_path.parent if source_model_path.is_file() else model_path.parent),
                      "parent_models": record["parent_models"], "request": record["request"]},
    }
    potential = {
        "schema": "mlcc.abacus-electrostatic-potential.v1",
        "status": "software_contract_only",
        "task_id": "fixture-task",
        "scheduler_job_id": "fixture-job",
        "study_id": "ni-bto-interface-study",
        "model_id": model_id,
        "model_version": model_version,
        "method_set": "abacus-interface-fixture",
        "method": method,
        "native_job": {"scheduler_fields": {"JobId": "fixture-job", "JobState": "COMPLETED", "ExitCode": "0:0"}},
        "native_output_observed": False,
        "electronic_converged": False,
        "energy_zero": {
            "Hartree_G0": "zero", "local_ionic_G0": "retained_pseudopotential_convention",
            "total_mean_subtracted": False, "fermi_subtracted": False, "vacuum_subtracted": False,
        },
        "kind": "local_ionic_plus_hartree",
        "value_unit": "Ry",
        "geometry_unit": "Bohr",
        "sign_convention": "electron_potential_energy",
        "includes_XC": False,
        "includes_nonlocal_pseudopotential": False,
        "evidence_kind": "software_contract_only",
        "atom_map": atom_map,
        "mapped_atoms": mapped_atoms,
        "conditions": {"cell_constraint": "fixed_cell", "net_charge": 0},
        "input_parameters": {section: {"efield_flag": "0", "dip_cor_flag": "0", "gate_flag": "0", "imp_sol": "0"}
                             for section in ("INPUT", "OUT.INPUT")},
        "cube": {
            "schema": "mlcc.abacus-electrostatic-cube.v1",
            "evidence_kind": "software_contract_only",
            "shape": [2, 2, 2],
            "origin_angstrom": [0.0, 0.0, 0.0],
            "step_vectors_angstrom": [[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 0.5]],
            "cell_angstrom": cell,
            "origin_bohr": [0.0, 0.0, 0.0],
            "step_vectors_bohr": [[0.5 / BOHR_TO_ANGSTROM, 0.0, 0.0], [0.0, 0.5 / BOHR_TO_ANGSTROM, 0.0], [0.0, 0.0, 0.5 / BOHR_TO_ANGSTROM]],
            "cell_bohr": [[value / BOHR_TO_ANGSTROM for value in row] for row in cell],
            "axis_order": "x_outer_y_middle_z_inner", "flat_index": "(ix*ny+iy)*nz+iz",
            "values_Ry": [0.0] * 8, "values_eV": [0.0] * 8,
            "print_precision": {"geometry_half_quantum_bohr": 5.0e-7},
            "unit_conversion": {"Ry_to_eV": RY_TO_EV, "Bohr_to_angstrom": BOHR_TO_ANGSTROM},
        },
        "source_files": {
            "task.json": str(root / "task.json"), "result.json": str(root / "result.json"),
            "method.json": str(root / "method.json"), "model.json": str(model_path),
            "Study": str(root / "Study"), "STRU.atom-map.json": str(root / "STRU.atom-map.json"),
            "fixture": "software-contract-only",
        },
    }
    _write(root / "task.json", task)
    _write(root / "result.json", result)
    _write(root / "method.json", method)
    _write(root / "Study", saved_study)
    _write(root / "STRU.atom-map.json", atom_map)
    return _write(root / "potential.json", potential)


def _request(potential: Path | None, *, reference: Path | None = None) -> dict:
    return {
        "schema": "mlcc.interface-electrical-request.v1",
        "study_id": "ni-bto-interface-study",
        "potential_path": None if potential is None else str(potential),
        "reference_potential_path": None if reference is None else str(reference),
        "reference_description": "same-model reference state" if reference is not None else None,
        "selection": _selection(),
    }


def test_missing_interface_potential_is_explicitly_unresolved(tmp_path: Path) -> None:
    study = _study(tmp_path)
    request = _request(None)
    request["selection"] = None
    result = sources.build_interface_electrical_product(
        study,
        {
            **request,
            "missing_source_reason": "no saved native interface electrostatic potential",
        },
    )
    assert result["schema"] == "mlcc.interface-electrical-product.v1"
    assert result["status"] == "unresolved"
    assert result["response"] is None
    assert result["missing_evidence"] == ["no saved native interface electrostatic potential"]
    assert result["source"] is None
    assert result["selection"] is None


def test_saved_interface_source_preserves_provenance_and_reordered_periodic_atoms(tmp_path: Path) -> None:
    study = _study(tmp_path)
    potential_path = _potential(tmp_path)
    result = sources.build_interface_electrical_product(study, _request(potential_path))
    assert result["source"]["method_set"] == "abacus-interface-fixture"
    assert result["response"]["target"]["regional_response"]["delta_phi_V"] == 0.0
    assert result["response"]["evidence_kind"] == "software_contract_only"
    assert result["status"] == "computed_software_contract_only"
    assert result["source"]["energy_zero"]["Hartree_G0"] == "zero"
    assert result["source"]["native_job"]["scheduler_fields"]["ExitCode"] == "0:0"
    assert result["source_files"]["fixture"] == "software-contract-only"
    assert result["interface"]["parent_models"] == study["interface"]["parent_models"]
    assert result["source_files"]["model.json"].endswith("interface-model\\model.json") or result["source_files"]["model.json"].endswith("interface-model/model.json")
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False


def test_declared_missing_source_path_keeps_file_error(tmp_path: Path) -> None:
    study = _study(tmp_path)
    request = _request(tmp_path / "does-not-exist.json")
    with pytest.raises(FileNotFoundError):
        sources.build_interface_electrical_product(study, request)


def test_bulk_or_czo_source_is_rejected_before_domain_call(tmp_path: Path) -> None:
    study = _study(tmp_path)
    potential_path = _potential(tmp_path, model_id="cazro3-pnma-pristine")
    with pytest.raises(ValueError, match="potential.model_id"):
        sources.build_interface_electrical_product(study, _request(potential_path))


def test_reference_identity_mismatch_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    study = _study(tmp_path)
    target = _potential(tmp_path / "target")
    reference = _potential(tmp_path / "reference", model_id="wrong-interface")
    monkeypatch.setattr(
        sources,
        "calculate_interface_electrical",
        lambda *args, **kwargs: {"schema": "mlcc.interface-electrical-response.v1", "missing_evidence": []},
    )
    with pytest.raises(ValueError, match="potential.model_id"):
        sources.build_interface_electrical_product(study, _request(target, reference=reference))


def test_reference_description_is_required_when_reference_is_present(tmp_path: Path) -> None:
    study = _study(tmp_path)
    target = _potential(tmp_path / "target")
    reference = _potential(tmp_path / "reference")
    request = _request(target, reference=reference)
    request["reference_description"] = None
    with pytest.raises(ValueError, match="reference_description"):
        sources.build_interface_electrical_product(study, request)


def test_selection_boundary_and_axis_are_bound_to_saved_interface(tmp_path: Path) -> None:
    study = _study(tmp_path)
    potential = _potential(tmp_path)
    request = _request(potential)
    request["selection"] = _selection(axis=1)
    with pytest.raises(ValueError, match="grid_axis"):
        sources.build_interface_electrical_product(study, request)
    request["selection"] = _selection(boundary=["p", "p", "f"])
    with pytest.raises(ValueError, match="boundary"):
        sources.build_interface_electrical_product(study, request)


def test_saved_reference_uses_same_physics_with_task_specific_paths(tmp_path: Path) -> None:
    study = _study(tmp_path)
    target, reference = _potential(tmp_path / "target"), _potential(tmp_path / "reference")
    result = sources.build_interface_electrical_product(study, _request(target, reference=reference))
    assert result["response"]["reference_comparison"]["delta_delta_phi_V"] == 0.0
    assert result["source"]["path"] != result["reference"]["path"]
    assert result["source"]["method"]["suffix"] != result["reference"]["method"]["suffix"]


def test_duplicate_source_index_is_rejected(tmp_path: Path) -> None:
    study = _study(tmp_path)
    path = _potential(tmp_path)
    potential = json.loads(path.read_text(encoding="utf-8"))
    potential["mapped_atoms"][1]["source_index"] = 1
    _write(path, potential)
    with pytest.raises(ValueError, match="permutation"):
        sources.build_interface_electrical_product(study, _request(path))


def test_declared_nonperiodic_axis_does_not_wrap_coordinates(tmp_path: Path) -> None:
    study = _study(tmp_path)
    path = _potential(tmp_path)
    boundary = ["f", "p", "p"]
    study["interface"]["request"]["boundary"] = boundary
    for file in (tmp_path / "Study", tmp_path / "interface-model" / "model.json", tmp_path / "interface-model" / "layered-interface.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        if file.name == "Study":
            data["interface"] = study["interface"]
        elif file.name == "model.json":
            data["boundary"], data["pbc"] = boundary, [False, True, True]
        else:
            data["request"]["boundary"] = boundary
        _write(file, data)
    result_path = tmp_path / "result.json"
    saved_result = json.loads(result_path.read_text(encoding="utf-8"))
    saved_result["final_atoms"]["pbc"] = [False, True, True]
    _write(result_path, saved_result)
    request = _request(path)
    request["selection"]["boundary"] = boundary
    with pytest.raises(ValueError, match="coordinates"):
        sources.build_interface_electrical_product(study, request)


def test_missing_declared_json_does_not_fall_back_to_study_model(tmp_path: Path) -> None:
    study = _study(tmp_path)
    path = _potential(tmp_path)
    potential = json.loads(path.read_text(encoding="utf-8"))
    potential["source_files"]["model.json"] = str(tmp_path / "missing-model.json")
    _write(path, potential)
    with pytest.raises(FileNotFoundError):
        sources.build_interface_electrical_product(study, _request(path))


__all__ = []
