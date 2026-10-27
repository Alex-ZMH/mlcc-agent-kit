"""Focused tests for the joint ceramic DeePMD manifest boundary."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from mlcc.ceramic_training import bind_ceramic_training_dataset


TYPE_MAP = ["Ca", "Zr", "O"]
METHOD_SET = "cazro3-oncv-pbe-pw-berry-capability-v001"


def _child(system_id: str, task_id: str, atom_ids: list[int]) -> dict:
    path = "train/system-000"
    set_path = f"{path}/set.000"
    frame = {
        "task_id": task_id,
        "model_id": f"{system_id}-model",
        "model_version": "v001",
        "set": "set.000",
        "set_path": set_path,
        "frame_index": 0,
        "atom_ids": atom_ids,
        "type_map": TYPE_MAP,
        "source_group": "czo-pnma-parent-v001",
        "npy": {
            "box": f"{set_path}/box.npy",
            "coord": f"{set_path}/coord.npy",
            "energy": f"{set_path}/energy.npy",
            "force": f"{set_path}/force.npy",
            "virial": f"{set_path}/virial.npy",
            "row": 0,
        },
        "source": {"system": path, "set": set_path, "frame_index": 0},
    }
    return {
        "schema": "mlcc.deepmd-dataset-manifest.v1",
        "format": "deepmd/npy",
        "engine": "abacus",
        "method_set": METHOD_SET,
        "method": {
            "engine": "abacus",
            "method_set": METHOD_SET,
            "effective_signature": {"engine": "abacus", "method_set": METHOD_SET},
        },
        "type_map": TYPE_MAP,
        "splits": {"train": [path], "validation": []},
        "training_systems": [path],
        "validation_systems": [],
        "systems": [
            {
                "path": path,
                "split": "train",
                "type_raw": f"{path}/type.raw",
                "type_map_raw": f"{path}/type_map.raw",
                "type_map": TYPE_MAP,
                "atom_ids": atom_ids,
                "sets": [set_path],
                "frames": [frame],
            }
        ],
        "sets": [
            {
                "name": "set.000",
                "path": set_path,
                "system": path,
                "split": "train",
                "source_group": "czo-pnma-parent-v001",
                "frame_count": 1,
                "source_task_ids": [task_id],
            }
        ],
        "units": {"energy": "eV", "force": "eV/angstrom", "virial": "eV"},
        "virial": {"source": "result.stress_GPa"},
        "sources": [
            {
                "task_id": task_id,
                "label": system_id,
                "split": "train",
                "source_group": "czo-pnma-parent-v001",
                "engine": "abacus",
                "method_set": METHOD_SET,
                "model_id": f"{system_id}-model",
                "model_version": "v001",
                "system": path,
                "task_provenance": {
                    "task_id": task_id,
                    "scheduler_job_id": "50" if system_id == "host20" else "121",
                },
            }
        ],
    }


def _collection(root: Path) -> Path:
    host = _child("host20", "p5-czo-berry-scf-v001", list(range(20)))
    vacancy_ids = list(range(20))
    vacancy_ids.remove(8)
    vacancy = _child("vacancy19", "p4-czo-vo8-q0-energy-chain-v001", vacancy_ids)
    (root / "host20").mkdir(parents=True)
    (root / "vacancy19").mkdir(parents=True)
    (root / "host20" / "dataset_manifest.json").write_text(json.dumps(host), encoding="utf-8")
    (root / "vacancy19" / "dataset_manifest.json").write_text(json.dumps(vacancy), encoding="utf-8")
    collection = {
        "schema": "mlcc.ceramic-dataset-collection.v1",
        "dataset_id": "czo-host50-vacancy121-neutral-engineering-v001",
        "purpose": "ordinary_neutral_energy_force_virial",
        "format": "deepmd/npy",
        "type_map": TYPE_MAP,
        "method": {"engine": "abacus", "method_set": METHOD_SET},
        "systems": [
            {
                "system_id": "host20",
                "split": "train",
                "manifest_path": str(root / "host20" / "dataset_manifest.json"),
                "source_group": "czo-pnma-parent-v001",
                "dataset_systems": copy.deepcopy(host["systems"]),
                "task_id": "p5-czo-berry-scf-v001",
                "scheduler_job_id": "50",
                "study_id": "cazro3_firing_validation_v003",
                "case_id": "cazro3_pnma_undoped",
                "case_role": "scientific_validation",
                "fixture": False,
                "production_label": False,
                "charge": {"fields": {"method": {"present": True, "value": 0}, "task": {"present": False, "value": None}, "result": {"present": False, "value": None}}},
                "input_electrons": {"nelec": {"present": False, "value": None}},
                "parent_system_id": None,
                "parent_mapping": {"parent_system_id": None, "entries": [], "deleted_atom_ids": []},
                "method": {"engine": "abacus", "method_set": METHOD_SET},
                "source": {"task_id": "p5-czo-berry-scf-v001"},
            },
            {
                "system_id": "vacancy19",
                "split": "train",
                "manifest_path": str(root / "vacancy19" / "dataset_manifest.json"),
                "source_group": "czo-pnma-parent-v001",
                "dataset_systems": copy.deepcopy(vacancy["systems"]),
                "task_id": "p4-czo-vo8-q0-energy-chain-v001",
                "scheduler_job_id": "121",
                "study_id": "czo-vo8-q0-energy-chain-v001",
                "case_id": "czo_vo8_q0_system_energy_chain",
                "case_role": "scientific_validation",
                "fixture": False,
                "production_label": False,
                "charge": {"fields": {"method": {"present": True, "value": 0}, "task": {"present": True, "value": 0}, "result": {"present": True, "value": 0}}},
                "input_electrons": {"nelec": {"present": False, "value": None}},
                "parent_system_id": "host20",
                "parent_mapping": {"parent_system_id": "host20", "entries": [{"child_atom_id": 0, "parent_atom_id": 0}], "deleted_atom_ids": [8]},
                "method": {"engine": "abacus", "method_set": METHOD_SET},
                "source": {"task_id": "p4-czo-vo8-q0-energy-chain-v001"},
            },
        ],
        "production_qualification": False,
        "scientific_qualification": False,
        "unsupported": ["polarization", "fieldforce", "dielectric"],
        "units": {"energy": "eV", "force": "eV/angstrom", "stress": "GPa", "virial": "eV"},
        "virial": {"source": "result.stress_GPa"},
    }
    path = root / "collection.json"
    path.write_text(json.dumps(collection), encoding="utf-8")
    return path


def test_joint_manifest_rebases_paths_without_global_atom_ids(tmp_path: Path):
    collection_path = _collection(tmp_path)
    manifest = bind_ceramic_training_dataset(collection_path, tmp_path / "joint" / "dataset-manifest.json")

    assert manifest["schema"] == "mlcc.deepmd-dataset-manifest.v1"
    assert manifest["engine"] == "abacus"
    assert manifest["method_set"] == METHOD_SET
    assert manifest["training_systems"] == ["host20/train/system-000", "vacancy19/train/system-000"]
    assert manifest["validation_systems"] == []
    assert "atom_ids" not in manifest
    assert manifest["systems"][0]["path"] == "host20/train/system-000"
    assert manifest["systems"][0]["atom_ids"] == list(range(20))
    assert manifest["systems"][0]["frames"][0]["set_path"] == "host20/train/system-000/set.000"
    assert manifest["systems"][0]["frames"][0]["npy"]["force"] == "host20/train/system-000/set.000/force.npy"
    assert manifest["systems"][0]["frames"][0]["source"]["system"] == "host20/train/system-000"
    assert manifest["sets"][1]["system"] == "vacancy19/train/system-000"
    assert manifest["sources"][0]["task_id"] == "p5-czo-berry-scf-v001"
    assert manifest["source_scheduler_job_ids"] == ["50", "121"]
    assert manifest["collection"]["dataset_id"] == "czo-host50-vacancy121-neutral-engineering-v001"


def test_joint_manifest_preserves_charge_and_vacancy_lineage(tmp_path: Path):
    collection_path = _collection(tmp_path)
    manifest = bind_ceramic_training_dataset(collection_path, tmp_path / "joint.json")
    host_meta = manifest["systems"][0]["collection_metadata"]
    vacancy_meta = manifest["systems"][1]["collection_metadata"]
    assert host_meta["charge"]["fields"]["result"] == {"present": False, "value": None}
    assert vacancy_meta["charge"]["fields"]["result"] == {"present": True, "value": 0}
    assert vacancy_meta["parent_system_id"] == "host20"
    assert vacancy_meta["parent_mapping"]["deleted_atom_ids"] == [8]
    assert manifest["collection_systems"][0]["study_id"] != manifest["collection_systems"][1]["study_id"]


@pytest.mark.parametrize("field, value, message", [
    ("type_map", ["O", "Zr", "Ca"], "type_map"),
    ("method_set", "wrong-method", "method_set"),
])
def test_joint_manifest_rejects_child_method_mismatch(tmp_path: Path, field: str, value: object, message: str):
    collection_path = _collection(tmp_path)
    child_path = tmp_path / "vacancy19" / "dataset_manifest.json"
    child = json.loads(child_path.read_text(encoding="utf-8"))
    child[field] = value
    child_path.write_text(json.dumps(child), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        bind_ceramic_training_dataset(collection_path, tmp_path / "joint.json")


@pytest.mark.skipif(not os.environ.get("MLCC_CERAMIC_COLLECTION"), reason="v100 collection path is not configured")
def test_real_collection_preserves_job50_job121_charge_and_deleted_atom8(tmp_path: Path):
    collection_path = Path(os.environ["MLCC_CERAMIC_COLLECTION"])
    manifest = bind_ceramic_training_dataset(collection_path, tmp_path / "joint.json")
    assert manifest["training_systems"] == ["host20/train/system-000", "vacancy19/train/system-000"]
    assert [row["atom_ids"] for row in manifest["systems"]] == [list(range(20)), [*range(8), *range(9, 20)]]
    assert [source["task_id"] for source in manifest["sources"]] == [
        "p5-czo-berry-scf-v001", "p4-czo-vo8-q0-energy-chain-v001"
    ]
    assert manifest["source_scheduler_job_ids"] == ["50", "121"]
    assert manifest["systems"][0]["collection_metadata"]["charge"]["fields"]["result"] == {
        "present": False, "value": None
    }
    assert manifest["systems"][1]["collection_metadata"]["parent_mapping"]["deleted_atom_ids"] == [8]

