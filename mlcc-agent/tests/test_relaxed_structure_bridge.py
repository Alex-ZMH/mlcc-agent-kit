"""Focused saved fixed-cell relaxation bridge checks.

The fixtures in this file are explicitly software-contract-only records.  They
exercise source binding, structure promotion, lineage and the thin downstream
SCF dispatch without claiming a new native relaxation or scientific
qualification.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.io import write as ase_write

import mlcc.relaxed_structure_bridge as bridge_module
from mlcc.modeling import write_model_artifacts
from mlcc.relaxed_structure_bridge import create_relaxed_scf, derive_relaxed_structure
from mlcc.tasks import load_task
from mlcc.workflow import require_result_dependencies


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parent_study(parent, path: Path) -> dict:
    return {
        "study_id": "software-parent-study",
        "case_id": "software_case",
        "case_role": "engineering_fixture",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "model": {
            "material": "NiCo",
            "phase_requested": "fcc_engineering_fixture",
            "model_id": parent.model_id,
            "version": parent.version,
            "source_structure": "model.extxyz",
        },
        "study_file": str(path.resolve()),
    }


def _constraints(atom_ids: list[int], *, all_free: bool = True) -> dict:
    return {
        "schema": "mlcc.ionic-constraints.v1",
        "coordinate_basis": "cartesian",
        "atom_ids": list(atom_ids),
        "move_flags": [[1, 1, 1] if all_free else [0, 0, 0] for _ in atom_ids],
        "relax_new": True,
        "origin": "explicit_request",
    }


def _method_record(parent, method_path: Path, constraints: dict) -> dict:
    method = {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "abacus_version_target": "3.10.1",
        "stage": "relax",
        "model_id": parent.model_id,
        "version": parent.version,
        "method_set": "software-relax-contract-v001",
        "fixture": True,
        "basis_type": "pw",
        "dft_functional": "PBE",
        "ks_solver": "cg",
        "relax_method": "cg",
        "relax_new": True,
        "nspin": 1,
        "occupations": "fixed",
        "element_order": list(dict.fromkeys(parent.atoms.get_chemical_symbols())),
        "kpoints": [2, 2, 2],
        "net_charge": 0,
        "ionic_constraints": copy.deepcopy(constraints),
        "parameters": {
            "ecutwfc_Ry": 100,
            "scf_thr": 1.0e-4,
            "relax_nmax": 10,
            "force_thr_eV_per_A": 0.02,
        },
        "pseudopotentials": {
            element: {"filename": f"{element}.upf"}
            for element in dict.fromkeys(parent.atoms.get_chemical_symbols())
        },
        "pseudopotential_ids": {
            element: f"{element}.upf"
            for element in dict.fromkeys(parent.atoms.get_chemical_symbols())
        },
        "pseudopotential_metadata": {
            element: {
                "element": element,
                "filename": f"{element}.upf",
                "valence_electrons_per_atom": 10,
            }
            for element in dict.fromkeys(parent.atoms.get_chemical_symbols())
        },
        "pseudopotential_treatment": {
            element: "scalar"
            for element in dict.fromkeys(parent.atoms.get_chemical_symbols())
        },
        "source_path": str(method_path.resolve()),
    }
    _write_json(method_path, method)
    return method


def _relaxation_record(
    constraints: dict,
    *,
    geometry_promotable: bool = True,
    electronic_converged: bool = True,
    ionic_converged: bool = True,
    fixed_cell_verified: bool = True,
    frozen_dofs_verified: bool = True,
    final_geometry_matches_last_evaluation: bool = True,
    final_geometry_role: str = "last_evaluated_ionic_step",
    native_stop_reason: str = "ionic_converged",
    ionic_steps: int = 3,
) -> dict:
    return {
        "schema": "mlcc.fixed-cell-relaxation-result.v1",
        "cell_constraint": "fixed_cell",
        "ionic_constraints": copy.deepcopy(constraints),
        "relax_new": True,
        "ionic_steps": ionic_steps,
        "relax_nmax": 10,
        "native_stop_reason": native_stop_reason,
        "native_marker_text": "Relaxation is converged!" if ionic_converged else "Relaxation is not converged yet!",
        "electronic_converged": electronic_converged,
        "ionic_converged": ionic_converged,
        "native_completed": True,
        "force_metric": "max_abs_movable_cartesian_component",
        "force_threshold_eV_per_A": 0.02,
        "max_free_force_component_eV_per_A": 0.001,
        "max_all_force_component_eV_per_A": 0.001,
        "fixed_cell_verified": fixed_cell_verified,
        "frozen_dofs_verified": frozen_dofs_verified,
        "final_geometry_matches_last_evaluation": final_geometry_matches_last_evaluation,
        "final_geometry_role": final_geometry_role,
        "geometry_promotable": geometry_promotable,
        "source_files": {},
    }


def _make_saved_relax_fixture(
    tmp_path: Path,
    *,
    task_study_file: bool = True,
    relaxation_overrides: dict | None = None,
) -> dict[str, Path | dict | list[int]]:
    cell = np.diag([3.52, 3.52, 3.52])
    parent_atoms = Atoms(
        symbols=["Ni", "Co", "Ni", "Co"],
        cell=cell,
        scaled_positions=[[0.0, 0.0, 0.0], [0.0, 0.5, 0.5], [0.5, 0.0, 0.5], [0.5, 0.5, 0.0]],
        pbc=True,
    )
    parent_atoms.new_array("atom_id", np.asarray([10, 20, 30, 40], dtype=int))
    parent_dir = tmp_path / "parent-model"
    parent = write_model_artifacts(
        parent_atoms,
        parent_dir,
        model_id="software-parent-model",
        version="v001",
        fixture=True,
        fixture_purpose="software_contract_only",
        phase_requested="fcc_engineering_fixture",
        source_path="software-parent-source",
        source_version="software-parent-v001",
        material="NiCo",
        selection_status="engineering_fixture",
        material_selection_confirmed=False,
        scientific_status="engineering_fixture_not_production",
    )
    fixture_dopants = [
        {
            "element": "Co",
            "site_index": 1,
            "role": "engineering_fixture_marker",
            "source": "software_contract_only",
        }
    ]
    parent.metadata["dopants"] = copy.deepcopy(fixture_dopants)
    _write_json(parent_dir / "model.json", parent.metadata)
    parent_dopants = _read_json(parent_dir / "dopants.json")
    parent_dopants["dopants"] = copy.deepcopy(fixture_dopants)
    _write_json(parent_dir / "dopants.json", parent_dopants)

    parent_study_path = tmp_path / "parent-study.json"
    parent_study = _parent_study(parent, parent_study_path)
    _write_json(parent_study_path, parent_study)

    method_path = tmp_path / "relax-task" / "method.json"
    constraints = _constraints(parent.atom_ids)
    method = _method_record(parent, method_path, constraints)

    final_order = parent.atom_ids
    final_symbols = parent_atoms.get_chemical_symbols()
    final_positions = parent_atoms.get_positions().copy()
    final_positions[0] += np.asarray([0.01, 0.0, 0.0])
    final_atoms = Atoms(final_symbols, positions=final_positions, cell=cell, pbc=True)
    final_atoms.new_array("atom_id", np.asarray(final_order, dtype=int))
    final_path = tmp_path / "relax-task" / "final.extxyz"
    ase_write(str(final_path), final_atoms, format="extxyz")

    result_path = tmp_path / "relax-task" / "result.json"
    task_path = tmp_path / "relax-task" / "task.json"
    task_dir = task_path.parent
    running_log = task_dir / "running_relax.log"
    stru_ion_d = task_dir / "STRU_ION_D"
    atom_map_path = task_dir / "STRU.atom-map.json"
    input_path = task_dir / "INPUT"
    running_log.write_text("software_contract_only relax log\n", encoding="utf-8")
    stru_ion_d.write_text("software_contract_only STRU_ION_D\n", encoding="utf-8")
    input_path.write_text("INPUT_PARAMETERS\ncalculation relax\n", encoding="utf-8")
    atom_map = {
        "schema": "mlcc.abacus-atom-map.v1",
        "abacus_version_target": "3.10.1",
        "model_id": parent.model_id,
        "version": parent.version,
        "source_atom_ids": parent.atom_ids,
        "element_order": method["element_order"],
        "abacus_order": [
            {
                "abacus_index": index,
                "source_index": index,
                "atom_id": atom_id,
                "element": parent_atoms[index].symbol,
                "label": f"{parent_atoms[index].symbol}{index + 1}",
            }
            for index, atom_id in enumerate(parent.atom_ids)
        ],
    }
    _write_json(atom_map_path, atom_map)
    source_files = {
        "running_relax.log": str(running_log.resolve()),
        "STRU_ION_D": str(stru_ion_d.resolve()),
        "STRU.atom-map.json": str(atom_map_path.resolve()),
        "method.json": str(method_path.resolve()),
        "INPUT": str(input_path.resolve()),
    }
    result = {
        "schema": "mlcc.abacus-result.v1",
        "task_id": "software-relax-task",
        "scheduler_job_id": "9001",
        "model_id": parent.model_id,
        "model_version": parent.version,
        "method_set": method["method_set"],
        "stage": "relax",
        "fixture": True,
        "production_label": False,
        "energy_eV": -100.0,
        "energy_unit": "eV",
        "forces_eV_per_A": [[0.001, 0.0, 0.0] for _ in parent_atoms],
        "stress_GPa": [[0.0, 0.0, 0.0] for _ in range(3)],
        "atom_ids": final_order,
        "final_structure_file": str(final_path.resolve()),
        "final_atoms": {
            "symbols": final_symbols,
            "positions_angstrom": final_positions.tolist(),
            "cell_angstrom": cell.tolist(),
            "pbc": [True, True, True],
        },
        "electronic_converged": True,
        "ionic_converged": True,
        "native_completed": True,
        "scientific_status": "converged_engineering_fixture",
        "source_files": source_files,
    }
    relaxation = _relaxation_record(constraints)
    if relaxation_overrides:
        relaxation.update(copy.deepcopy(relaxation_overrides))
    relaxation["source_files"] = {
        **source_files,
        "result.json": str(result_path.resolve()),
    }
    result["relaxation"] = relaxation
    _write_json(result_path, result)

    task = {
        "schema": "mlcc.task.v1",
        "task_id": "software-relax-task",
        "stage": "P4",
        "calculation": "relax",
        "input_transformation": None,
        "engine": "abacus",
        "engine_version": "3.10.1",
        "model_id": parent.model_id,
        "model_version": parent.version,
        "model_path": str(parent.artifact_dir.resolve()),
        "method_set": method["method_set"],
        "method_file": str(method_path.resolve()),
        "study_id": parent_study["study_id"],
        "fixture": True,
        "production_label": False,
        "runner": "slurm",
        "scheduler_job_id": "9001",
        "status": "COMPLETED",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "result_file": str(result_path.resolve()),
        "final_structure_file": str(final_path.resolve()),
        "ionic_constraints": copy.deepcopy(constraints),
        "relaxation": copy.deepcopy(relaxation),
        "source_files": {
            **source_files,
            "result.json": str(result_path.resolve()),
        },
    }
    if task_study_file:
        task["study_file"] = str(parent_study_path.resolve())
    else:
        task.pop("study_id")
    _write_json(task_path, task)

    request_path = tmp_path / "bridge-request.json"
    request = {
        "schema": "mlcc.relaxed-structure-bridge-request.v1",
        "model_id": "software-relaxed-model",
        "version": "v001",
        "study_id": "software-relaxed-study",
        "case_id": "software_case",
        "case_role": "engineering_fixture",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "evidence_kind": "software_contract_only",
    }
    _write_json(request_path, request)

    output_path = tmp_path / "bridge-output"
    return {
        "parent_model": parent_dir,
        "parent_study": parent_study_path,
        "method": method_path,
        "task": task_path,
        "result": result_path,
        "final": final_path,
        "request": request_path,
        "output": output_path,
        "task_record": task,
        "result_record": result,
        "parent_study_record": parent_study,
        "final_order": final_order,
        "constraints": constraints,
    }


def test_derive_promotes_noncontiguous_interleaved_saved_final_and_preserves_lineage(tmp_path):
    fixture = _make_saved_relax_fixture(tmp_path)
    parent_study = _read_json(fixture["parent_study"])
    parent_study.update(
        scientific_qualification=True,
        production_qualification=True,
        production_qualified=True,
    )
    _write_json(fixture["parent_study"], parent_study)
    bridge = derive_relaxed_structure(
        task_path=fixture["task"],
        parent_model_path=fixture["parent_model"],
        study_path=fixture["parent_study"],
        request_path=fixture["request"],
        output_path=fixture["output"],
    )

    assert bridge["schema"] == "mlcc.relaxed-structure-bridge.v1"
    assert bridge["status"] == "promoted_unqualified"
    assert bridge["scientific_qualification"] is False
    assert bridge["production_qualification"] is False
    assert bridge["parent_model"]["model_id"] == "software-parent-model"
    assert bridge["parent_study"]["study_id"] == "software-parent-study"
    assert bridge["child_model"]["model_id"] == "software-relaxed-model"
    assert bridge["child_model"]["version"] == "v001"
    assert Path(bridge["child_model"]["path"]).resolve() == (fixture["output"] / "model").resolve()
    assert bridge["child_study"]["study_id"] == "software-relaxed-study"

    child_model = _read_json(fixture["output"] / "model" / "model.json")
    assert child_model["atom_ids"] == fixture["final_order"]
    assert child_model["fixture"] is True
    assert child_model["material"] == "NiCo"
    parent_model = _read_json(fixture["parent_model"] / "model.json")
    assert parent_model["dopants"]
    assert child_model["dopants"] == parent_model["dopants"]
    assert child_model["phase_requested"] == "fcc_engineering_fixture"
    assert child_model["phase_relaxed"] is None
    assert child_model["production_qualified"] is False
    assert "berry_strain_response" not in child_model
    assert child_model["relaxation_source"]["task_file"] == str(fixture["task"].resolve())
    assert child_model["relaxation_source"]["scheduler_job_id"] == "9001"
    assert child_model["relaxation_source"]["relaxation"]["geometry_promotable"] is True
    assert child_model["relaxation_source"]["relaxation"]["ionic_constraints"] == fixture["constraints"]
    child_dopants = _read_json(fixture["output"] / "model" / "dopants.json")
    parent_dopants = _read_json(fixture["parent_model"] / "dopants.json")
    assert child_dopants["spatial_mode"] == parent_dopants["spatial_mode"] == "pristine"
    assert child_dopants["dopants"] == parent_dopants["dopants"]
    assert child_dopants["dopants"]
    assert child_dopants["compensation"] == parent_dopants["compensation"]
    assert child_dopants["compensation"] is None

    lineage = _read_json(fixture["output"] / "model" / "atom-lineage.json")
    assert [entry["child_atom_id"] for entry in lineage["entries"]] == fixture["final_order"]
    assert [entry["parent_atom_id"] for entry in lineage["entries"]] == fixture["final_order"]
    assert all("parent_atom_id" in entry and "child_atom_id" in entry for entry in lineage["entries"])

    child_study = _read_json(fixture["output"] / "study.json")
    assert child_study["study_id"] == "software-relaxed-study"
    assert child_study["parent_study_id"] == "software-parent-study"
    assert child_study["model"]["model_id"] == "software-relaxed-model"
    assert child_study["case_role"] == "engineering_fixture"
    assert child_study["scientific_qualification"] is False
    assert child_study["production_qualification"] is False
    assert child_study["production_qualified"] is False
    assert child_study["model"]["production_qualified"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"electronic_converged": False, "native_stop_reason": "electronic_not_converged"},
        {"ionic_converged": False, "native_stop_reason": "ionic_iteration_limit", "geometry_promotable": False},
        {"geometry_promotable": False},
        {"final_geometry_role": "proposed"},
        {"final_geometry_matches_last_evaluation": False, "final_geometry_role": "proposed", "geometry_promotable": False},
        {"fixed_cell_verified": False, "geometry_promotable": False},
        {"frozen_dofs_verified": False, "geometry_promotable": False},
    ],
)
def test_derive_rejects_nonpromotable_relaxation_records(tmp_path, overrides):
    fixture = _make_saved_relax_fixture(tmp_path, relaxation_overrides=overrides)
    with pytest.raises(ValueError):
        derive_relaxed_structure(
            task_path=fixture["task"],
            parent_model_path=fixture["parent_model"],
            study_path=fixture["parent_study"],
            request_path=fixture["request"],
            output_path=fixture["output"],
        )


@pytest.mark.parametrize("field", ["task_id", "method_model_id", "scheduler_job_id"])
def test_derive_rejects_source_identity_mismatch(tmp_path, field):
    fixture = _make_saved_relax_fixture(tmp_path)
    if field == "task_id":
        task = _read_json(fixture["task"])
        task["task_id"] = "different-source"
        _write_json(fixture["task"], task)
    elif field == "method_model_id":
        method = _read_json(fixture["method"])
        method["model_id"] = "different-source"
        _write_json(fixture["method"], method)
    else:
        task = _read_json(fixture["task"])
        task["scheduler_job_id"] = "different-source"
        _write_json(fixture["task"], task)
    with pytest.raises(ValueError):
        derive_relaxed_structure(
            task_path=fixture["task"],
            parent_model_path=fixture["parent_model"],
            study_path=fixture["parent_study"],
            request_path=fixture["request"],
            output_path=fixture["output"],
        )


def test_derive_rejects_atom_mapping_and_fixed_cell_mismatch(tmp_path):
    fixture = _make_saved_relax_fixture(tmp_path)
    result = _read_json(fixture["result"])
    result["atom_ids"] = [0, 1, 2, 99]
    _write_json(fixture["result"], result)
    with pytest.raises(ValueError):
        derive_relaxed_structure(
            task_path=fixture["task"],
            parent_model_path=fixture["parent_model"],
            study_path=fixture["parent_study"],
            request_path=fixture["request"],
            output_path=fixture["output"],
        )

    fixture = _make_saved_relax_fixture(tmp_path / "cell")
    result = _read_json(fixture["result"])
    result["final_atoms"]["cell_angstrom"][0][0] += 0.1
    _write_json(fixture["result"], result)
    with pytest.raises(ValueError):
        derive_relaxed_structure(
            task_path=fixture["task"],
            parent_model_path=fixture["parent_model"],
            study_path=fixture["parent_study"],
            request_path=fixture["request"],
            output_path=fixture["output"],
        )


def test_derive_rejects_saved_scf_task_as_relax_source(tmp_path):
    fixture = _make_saved_relax_fixture(tmp_path)
    task = _read_json(fixture["task"])
    task["calculation"] = "scf"
    _write_json(fixture["task"], task)
    with pytest.raises(ValueError):
        derive_relaxed_structure(
            task_path=fixture["task"],
            parent_model_path=fixture["parent_model"],
            study_path=fixture["parent_study"],
            request_path=fixture["request"],
            output_path=fixture["output"],
        )


@pytest.mark.parametrize("target", ["relaxation", "ionic_constraints"])
def test_derive_rejects_relax_new_false_in_saved_contract(tmp_path, target):
    fixture = _make_saved_relax_fixture(tmp_path)
    result = _read_json(fixture["result"])
    if target == "relaxation":
        result["relaxation"]["relax_new"] = False
    else:
        result["relaxation"]["ionic_constraints"]["relax_new"] = False
    _write_json(fixture["result"], result)
    with pytest.raises(ValueError):
        derive_relaxed_structure(
            task_path=fixture["task"],
            parent_model_path=fixture["parent_model"],
            study_path=fixture["parent_study"],
            request_path=fixture["request"],
            output_path=fixture["output"],
        )


def test_historical_task_without_study_file_records_explicit_caller_binding_origin(tmp_path):
    fixture = _make_saved_relax_fixture(tmp_path, task_study_file=False)
    bridge = derive_relaxed_structure(
        task_path=fixture["task"],
        parent_model_path=fixture["parent_model"],
        study_path=fixture["parent_study"],
        request_path=fixture["request"],
        output_path=fixture["output"],
    )
    assert bridge["study_binding_origin"] == "caller_supplied_parent_study_matching_source_model"
    assert bridge["parent_study"]["study_path"] == str(fixture["parent_study"].resolve())


def test_create_relaxed_scf_dispatches_existing_creator_with_bridge_dependency(tmp_path, monkeypatch):
    fixture = _make_saved_relax_fixture(tmp_path)
    dependency = {
        "task_id": "software-relax-task",
        "task_file": str(fixture["task"].resolve()),
        "result_file": str(fixture["result"].resolve()),
        "scientific_status": "converged_engineering_fixture",
    }
    derive_relaxed_structure(
        task_path=fixture["task"],
        parent_model_path=fixture["parent_model"],
        study_path=fixture["parent_study"],
        request_path=fixture["request"],
        output_path=fixture["output"],
    )
    method_path = tmp_path / "scf-method.json"
    site_path = tmp_path / "site.json"
    request_path = tmp_path / "scf-request.json"
    _write_json(method_path, {"engine": "abacus", "engine_version": "3.10.1", "basis_type": "pw"})
    _write_json(site_path, {"workspace": {"local": str(tmp_path / "workspace")}})
    _write_json(
        request_path,
        {
            "schema": "mlcc.abacus-task-request.v1",
            "task_id": "software-relaxed-scf",
            "calculation": "scf",
            "input_transformation": None,
            "ionic_constraints": None,
            "required_results": [
                dependency
            ],
            "resource_request": {"nodes": 1, "partition": "cpu", "ntasks": 1, "cpus_per_task": 1, "mem_mib": 2048, "time": "00:02:00"},
        },
    )
    calls = {}

    def fake_creator(**kwargs):
        calls.update(kwargs)
        request = _read_json(kwargs["request_path"])
        site = _read_json(kwargs["site_path"])
        task_id = request["task_id"]
        task_file = Path(site["workspace"]["local"]) / "tasks" / task_id / "task.json"
        _write_json(
            task_file,
            {
                "task_id": task_id,
                "scheduler_job_id": None,
                "calculation": request["calculation"],
                "input_transformation": request["input_transformation"],
                "depends_on": [item["task_id"] for item in request["required_results"]],
                "required_results": request["required_results"],
                "events": [],
            },
        )
        return {
            "task_id": task_id,
            "calculation": request["calculation"],
            "depends_on": [item["task_id"] for item in request["required_results"]],
            "input_transformation": request["input_transformation"],
        }

    monkeypatch.setattr(bridge_module, "create_abacus_task", fake_creator)
    created = create_relaxed_scf(
        bridge_path=fixture["output"] / "bridge.json",
        method_path=method_path,
        site_path=site_path,
        request_path=request_path,
    )
    assert Path(calls["model_path"]).resolve() == (fixture["output"] / "model").resolve()
    assert Path(calls["study_path"]).resolve() == (fixture["output"] / "study.json").resolve()
    effective_request = _read_json(Path(calls["request_path"]))
    assert effective_request["calculation"] == "scf"
    assert effective_request["input_transformation"] is None
    assert effective_request["ionic_constraints"] is None
    assert effective_request["required_results"] == [dependency]
    assert created["depends_on"] == ["software-relax-task"]
    assert created["relaxation_source"]["task_id"] == "software-relax-task"
    assert created["calculation"] == "scf"
    assert created["input_transformation"] is None
    saved_child = load_task(
        tmp_path / "workspace" / "tasks" / "software-relaxed-scf" / "task.json"
    )
    dependency_evidence = require_result_dependencies(saved_child, tmp_path)
    assert dependency_evidence[0]["task_id"] == "software-relax-task"
    assert any(Path(path).name == "running_relax.log" for path in dependency_evidence[0]["source_files"])


def test_create_relaxed_scf_dispatches_berry_reference_only_for_explicit_role(tmp_path, monkeypatch):
    fixture = _make_saved_relax_fixture(tmp_path)
    derive_relaxed_structure(
        task_path=fixture["task"],
        parent_model_path=fixture["parent_model"],
        study_path=fixture["parent_study"],
        request_path=fixture["request"],
        output_path=fixture["output"],
    )
    method_path = tmp_path / "berry-method.json"
    site_path = tmp_path / "site.json"
    request_path = tmp_path / "berry-request.json"
    _write_json(method_path, {})
    _write_json(site_path, {"workspace": {"local": str(tmp_path / "workspace")}})
    _write_json(
        request_path,
        {
            "schema": "mlcc.abacus-task-request.v1",
            "task_id": "software-relaxed-berry-reference",
            "calculation": "scf",
            "input_transformation": None,
            "berry": {"role": "reference_scf"},
            "required_results": [
                {
                    "task_id": "software-relax-task",
                    "task_file": str(fixture["task"].resolve()),
                    "result_file": str(fixture["result"].resolve()),
                    "scientific_status": "converged_engineering_fixture",
                }
            ],
        },
    )
    calls = []

    def fake_berry(**kwargs):
        calls.append(kwargs)
        site = _read_json(kwargs["site_path"])
        task_file = Path(site["workspace"]["local"]) / "tasks" / "software-relaxed-berry-reference" / "task.json"
        _write_json(
            task_file,
            {
                "task_id": "software-relaxed-berry-reference",
                "scheduler_job_id": None,
                "calculation": "scf",
                "input_transformation": None,
                "depends_on": ["software-relax-task"],
                "events": [],
            },
        )
        return {"task_id": "software-relaxed-berry-reference", "depends_on": ["software-relax-task"]}

    monkeypatch.setattr(bridge_module, "create_berry_reference_task", fake_berry)
    created = create_relaxed_scf(
        bridge_path=fixture["output"] / "bridge.json",
        method_path=method_path,
        site_path=site_path,
        request_path=request_path,
    )
    assert len(calls) == 1
    assert Path(calls[0]["model_path"]).resolve() == (fixture["output"] / "model").resolve()
    assert created["depends_on"] == ["software-relax-task"]

