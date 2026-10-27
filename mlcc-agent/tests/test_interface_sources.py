"""P11 layered-interface Study/source binding contract checks.

These tests create a small explicit geometry fixture and exercise only source
provenance and input delivery.  No LAMMPS executable or native result is run;
the task hook is checked at the point where it writes the selected inputs.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.interfaces import build_layered_interface
from mlcc.interface_sources import bind_interface_study
from mlcc.lammps_tasks import create_lammps_task
from mlcc.modeling import write_model_artifacts
from mlcc.property_delivery import deliver_interface_inputs


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _parent(tmp_path: Path, name: str, element: str, c_length: float):
    atoms = Atoms(
        symbols=[element],
        positions=[[0.8, 0.8, 0.8]],
        cell=[[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, c_length]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([0], dtype=np.int64))
    return write_model_artifacts(
        atoms,
        tmp_path / name,
        model_id=name,
        version="v001",
        fixture=True,
        fixture_purpose="layered_interface_source_contract",
        phase_requested=f"{name}-phase",
        source_path=f"fixture://{name}",
        source_reference=f"source-record:{name}",
        source_atoms=atoms,
        material=name,
    )


def _interface_request() -> dict:
    return {
        "schema": "mlcc.layered-interface-request.v1",
        "model_id": "ni-o-layered-interface",
        "version": "v001",
        "fixture": True,
        "fixture_purpose": "layered_interface_source_contract",
        "charge_state": 0,
        "boundary": ["p", "p", "p"],
        "sides": {
            "a": {
                "repeat": [1, 1, 1],
                "target_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 3.52]],
                "origin_shift_fractional": [0.0, 0.0, 0.0],
                "translation_inplane_angstrom": [0.0, 0.0],
            },
            "b": {
                "repeat": [1, 1, 1],
                "target_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.08]],
                "origin_shift_fractional": [0.0, 0.0, 0.0],
                "translation_inplane_angstrom": [0.25, 0.25],
            },
        },
        "gap_ab_angstrom": 2.0,
        "gap_ba_angstrom": 2.0,
        "minimum_distance_angstrom": 1.0,
    }


def _make_case(tmp_path: Path) -> dict:
    side_a = _parent(tmp_path, "parent-ni", "Ni", 3.52)
    side_b = _parent(tmp_path, "parent-o", "O", 4.08)
    geometry_request = _interface_request()
    interface = build_layered_interface(
        side_a.artifact_dir,
        side_b.artifact_dir,
        geometry_request,
        tmp_path / "interface-model",
    )

    parent_a_study = _write(
        tmp_path / "parent-a-study.json",
        {
            "study_id": "parent-a-study",
            "model": {"model_id": side_a.model_id, "version": side_a.version},
        },
    )
    parent_b_study = _write(
        tmp_path / "parent-b-study.json",
        {
            "study_id": "parent-b-study",
            "model": {"model_id": side_b.model_id, "version": side_b.version},
        },
    )
    study_request = {
        "schema": "mlcc.interface-study-request.v1",
        "study_id": "interface-study-v001",
        "case_id": "ni-o-layered-interface-contract",
        "case_role": "engineering_fixture",
        "parent_study_refs": [
            {"side": "a", "study_id": "parent-a-study", "path": str(parent_a_study.resolve())},
            {"side": "b", "study_id": "parent-b-study", "path": str(parent_b_study.resolve())},
        ],
        "conditions": {"temperature_K": 330.0, "mechanical_pressure_Pa": 101325.0},
    }
    study_path = tmp_path / "interface-study.json"
    study = bind_interface_study(interface.artifact_dir, study_request, study_path)
    return {
        "side_a": side_a,
        "side_b": side_b,
        "interface": interface,
        "geometry_request": geometry_request,
        "study_request": study_request,
        "study_path": study_path,
        "study": study,
    }


def _lammps_inputs(tmp_path: Path, case: dict) -> dict[str, Path]:
    workspace = tmp_path / "lammps-workspace"
    (workspace / "tasks").mkdir(parents=True)
    potential_file = tmp_path / "interface.eam"
    potential_file.write_text("software contract fixture potential\n", encoding="utf-8")
    potential_path = _write(
        tmp_path / "potential.json",
        {
            "potential_id": "ni-o-contract",
            "version": "fixture-v001",
            "source": "software contract fixture; no native result",
            "license": "fixture",
            "fixture": True,
            "production_qualification": False,
            "units": "metal",
            "atom_style": "atomic",
            "elements": ["Ni", "O"],
            "element_order": ["Ni", "O"],
            "model_ids": [case["interface"].model_id],
            "pair_style": "eam",
            "pair_coeff": ["* * interface.eam Ni O"],
            "files": [{"local_path": str(potential_file), "filename": "interface.eam"}],
        },
    )
    protocol_path = _write(
        tmp_path / "protocol.json",
        {
            "kind": "run0",
            "units": "metal",
            "boundary": ["p", "p", "p"],
            "ensemble": "none",
            "timestep_ps": 0.001,
        },
    )
    site_path = _write(
        tmp_path / "site.json",
        {
            "ssh": {"alias": "v100"},
            "workspace": {"local": str(workspace), "remote_root": "/home/v100/projects/mlcc"},
            "runner": {"selected": "slurm"},
            "lammps": {
                "binary": "/site/lammps/bin/lmp",
                "version": "LAMMPS contract fixture",
                "environment_script": "/site/lammps/env.sh",
                "launch_prefix": [],
            },
        },
    )
    request_path = _write(
        tmp_path / "lammps-request.json",
        {
            "task_id": "p11-interface-input-v001",
            "required_results": [],
            "resource_request": {
                "nodes": 1,
                "partition": "cpu",
                "ntasks": 1,
                "cpus_per_task": 1,
                "mem_mib": 512,
                "time": "00:05:00",
            },
        },
    )
    return {
        "study": case["study_path"],
        "model": case["interface"].artifact_dir,
        "potential": potential_path,
        "protocol": protocol_path,
        "site": site_path,
        "request": request_path,
        "workspace": workspace,
    }


def test_interface_study_binding_preserves_two_parent_sources_and_request(tmp_path: Path):
    case = _make_case(tmp_path)

    assert case["study"]["model"]["spatial_mode"] == "layered_interface"
    assert case["study"]["model"]["fixture"] is True
    assert case["study"]["interface"]["request"] == case["geometry_request"]
    assert [item["side"] for item in case["study"]["interface"]["parent_models"]] == ["a", "b"]
    assert [item["model_id"] for item in case["study"]["interface"]["parent_models"]] == [
        case["side_a"].model_id,
        case["side_b"].model_id,
    ]
    assert case["study"]["interface"]["parent_study_refs"] == case["study_request"]["parent_study_refs"]
    assert case["study"]["conditions"] == case["study_request"]["conditions"]


def test_interface_binding_rejects_wrong_parent_study(tmp_path: Path):
    case = _make_case(tmp_path)
    wrong_request = copy.deepcopy(case["study_request"])
    wrong_request["parent_study_refs"][1] = {**wrong_request["parent_study_refs"][0], "side": "b"}

    with pytest.raises(ValueError, match="parent Study model differs"):
        bind_interface_study(case["interface"].artifact_dir, wrong_request, tmp_path / "wrong-study.json")


def test_interface_delivery_without_task_keeps_responses_unresolved(tmp_path: Path):
    case = _make_case(tmp_path)
    request_path = _write(
        tmp_path / "delivery-no-task.json",
        {
            "schema": "mlcc.interface-delivery-request.v1",
            "model_path": str(case["interface"].artifact_dir.resolve()),
        },
    )

    delivered = deliver_interface_inputs(case["study_path"], request_path)

    assert delivered["status"] == "input_sources_available"
    assert delivered["task"] is None
    assert delivered["task_provenance"] is None
    assert delivered["responses"] == {
        "traction_separation": None,
        "interface_thermal_response": None,
        "local_thermal_stress": None,
    }
    assert delivered["response_status"] == "not_calculated"
    assert delivered["missing_evidence"] == ["native_interface_response"]
    assert delivered["interface"]["request"] == case["geometry_request"]
    assert [item["model_id"] for item in delivered["parent_models"]] == [
        case["side_a"].model_id,
        case["side_b"].model_id,
    ]


def test_lammps_hook_stages_and_delivery_rereads_task_local_two_source_record(tmp_path: Path):
    case = _make_case(tmp_path)
    paths = _lammps_inputs(tmp_path, case)
    task = create_lammps_task(
        study_path=paths["study"],
        model_path=paths["model"],
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )
    task_path = paths["workspace"] / "tasks" / task["task_id"] / "task.json"
    task_directory = task_path.parent
    delivery_request = _write(
        tmp_path / "delivery-with-task.json",
        {
            "schema": "mlcc.interface-delivery-request.v1",
            "model_path": str(case["interface"].artifact_dir.resolve()),
            "task_path": str(task_path.resolve()),
        },
    )

    delivered = deliver_interface_inputs(case["study_path"], delivery_request)

    assert task["stage"] == "P11"
    assert task["runner"] == "slurm"
    assert task["scheduler_job_id"] is None
    assert task["interface_sources"]["parent_models"] == case["study"]["interface"]["parent_models"]
    assert task["interface_sources"]["transfer_paths"] == [
        "interface-sources/layered-interface.json",
        "interface-sources/atom-lineage.json",
        "interface-sources/parent-a-model.json",
        "interface-sources/parent-b-model.json",
    ]
    for relative in task["interface_sources"]["transfer_paths"]:
        assert (task_directory / relative).is_file()
    assert delivered["task"]["interface_sources"] == task["interface_sources"]
    assert delivered["task_provenance"]["interface"]["request"] == case["geometry_request"]
    assert [item["model_id"] for item in delivered["task_provenance"]["parent_models"]] == [
        case["side_a"].model_id,
        case["side_b"].model_id,
    ]
    assert delivered["responses"]["traction_separation"] is None
    assert delivered["response_status"] == "not_calculated"


def test_interface_delivery_rejects_task_bound_to_wrong_study(tmp_path: Path):
    case = _make_case(tmp_path)
    paths = _lammps_inputs(tmp_path, case)
    task = create_lammps_task(
        study_path=paths["study"],
        model_path=paths["model"],
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )
    task_path = paths["workspace"] / "tasks" / task["task_id"] / "task.json"
    wrong_study = json.loads(case["study_path"].read_text(encoding="utf-8"))
    wrong_study["study_id"] = "different-interface-study"
    wrong_study_path = _write(tmp_path / "wrong-interface-study.json", wrong_study)
    delivery_request = _write(
        tmp_path / "delivery-wrong-study.json",
        {
            "schema": "mlcc.interface-delivery-request.v1",
            "model_path": str(case["interface"].artifact_dir.resolve()),
            "task_path": str(task_path.resolve()),
        },
    )

    with pytest.raises(ValueError, match="task study_id"):
        deliver_interface_inputs(wrong_study_path, delivery_request)


def test_interface_delivery_rejects_wrong_parent_atom_id(tmp_path: Path):
    case = _make_case(tmp_path)
    paths = _lammps_inputs(tmp_path, case)
    task = create_lammps_task(
        study_path=paths["study"],
        model_path=paths["model"],
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )
    task_path = paths["workspace"] / "tasks" / task["task_id"] / "task.json"
    lineage_path = task_path.parent / "interface-sources" / "atom-lineage.json"
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage["entries"][0]["parent_atom_id"] = 999
    lineage_path.write_text(json.dumps(lineage, indent=2) + "\n", encoding="utf-8")
    delivery_request = _write(
        tmp_path / "delivery-wrong-parent-atom.json",
        {
            "schema": "mlcc.interface-delivery-request.v1",
            "model_path": str(case["interface"].artifact_dir.resolve()),
            "task_path": str(task_path.resolve()),
        },
    )

    with pytest.raises(ValueError, match="parent index/ID"):
        deliver_interface_inputs(case["study_path"], delivery_request)
