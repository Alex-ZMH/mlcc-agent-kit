"""Focused tests for the ceramic LAMMPS task boundary.

These tests exercise task identity and staging with native execution patched at
this boundary; no LAMMPS process or numerical calculation is started here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc import ceramic_md
from mlcc.modeling import ModelArtifacts
from mlcc.tasks import save_task


TYPE_MAP = ["Ca", "Zr", "O"]


def _model(path: Path, model_id: str, atom_ids: list[int]) -> ModelArtifacts:
    atoms = Atoms(
        symbols=["Ca", "Zr", "O"],
        positions=[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
        cell=np.diag([5.0, 5.0, 5.0]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray(atom_ids, dtype=int))
    metadata = {
        "schema": "mlcc.model.v1",
        "model_id": model_id,
        "version": "v001",
        "fixture": False,
        "material": "CaZrO3",
        "phase_requested": "Pnma",
        "atom_ids": atom_ids,
        "parent_models": [],
    }
    return ModelArtifacts(model_id, "v001", atoms, metadata, path)


def _collection(root: Path, system_id: str, model_id: str, atom_ids: list[int]) -> dict:
    frame = {
        "task_id": f"abacus-{system_id}",
        "model_id": model_id,
        "model_version": "v001",
        "set": "set.000",
        "set_path": "train/system-000/set.000",
        "frame_index": 0,
        "atom_ids": atom_ids,
        "type_map": TYPE_MAP,
        "symbols": ["Ca", "Zr", "O"],
        "cell_angstrom": np.diag([5.0, 5.0, 5.0]).tolist(),
        "positions_angstrom": [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
        "source_group": "czo-pnma-parent-v001",
        "npy": {"box": "box.npy", "coord": "coord.npy", "energy": "energy.npy", "force": "force.npy", "virial": "virial.npy", "row": 0},
        "source": {"task_dir": str(root / "source"), "task_id": f"abacus-{system_id}"},
    }
    dataset_system = {"path": "train/system-000", "split": "train", "type_map": TYPE_MAP, "atom_ids": atom_ids, "sets": ["train/system-000/set.000"], "frames": [frame]}
    return {
        "system_id": system_id,
        "split": "train",
        "source_group": "czo-pnma-parent-v001",
        "parent_system_id": None if system_id == "host20" else "host20",
        "manifest_path": str(root / system_id / "dataset_manifest.json"),
        "dataset_systems": [dataset_system],
        "task_id": f"abacus-{system_id}",
        "scheduler_job_id": "50" if system_id == "host20" else "121",
        "study_id": "cazro3_firing_validation_v003",
        "case_id": f"cazro3_pnma_{system_id}",
        "case_role": "scientific_validation",
        "fixture": False,
        "production_label": False,
        "model_id": model_id,
        "model_version": "v001",
        "model_path": str(root / "models" / model_id / "v001"),
        "method": {"engine": "abacus", "method_set": "czo-method-v001"},
        "charge": {"fields": {"method": {"present": True, "value": 0}}},
        "input_electrons": {"nelec": {"present": False, "value": None}},
        "parent_mapping": {"parent_system_id": None, "entries": [], "deleted_atom_ids": []},
        "source": {"task_id": f"abacus-{system_id}"},
    }


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system_id: str):
    model_id = f"czo-{system_id}"
    model_path = tmp_path / "models" / model_id / "v001"
    model_path.mkdir(parents=True)
    model = _model(model_path, model_id, [0, 1, 2])
    monkeypatch.setattr(ceramic_md, "read_model_artifacts", lambda path: model)
    collection = {
        "schema": "mlcc.ceramic-dataset-collection.v1",
        "dataset_id": "czo-engineering-v001",
        "purpose": "ordinary_neutral_energy_force_virial",
        "format": "deepmd/npy",
        "type_map": TYPE_MAP,
        "method": {"engine": "abacus", "method_set": "czo-method-v001"},
        "systems": [_collection(tmp_path, system_id, model_id, [0, 1, 2])],
        "production_qualification": False,
        "scientific_qualification": False,
    }
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(json.dumps(collection), encoding="utf-8")
    frozen = tmp_path / "frozen.pth"
    frozen.write_bytes(b"exact-frozen-model")
    card = {
        "schema_version": "mlcc.deepmd.model-card.v1",
        "status": "engineering_handoff",
        "scientific_status": "not_qualified",
        "engine": "deepmd",
        "backend": "pt",
        "format": "pth",
        "type_map": TYPE_MAP,
        "frozen_model": str(frozen),
        "training_task_id": "czo-deepmd-training-v001",
        "job_id": "training-141",
        "dataset_manifest": {"collection": collection},
    }
    card_path = tmp_path / "model-card.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    site = {
        "ssh": {"alias": "v100"},
        "workspace": {"local": str(tmp_path), "remote_root": "/remote/mlcc"},
        "runner": {"selected": "slurm"},
        "lammps": {
            "binary": "/opt/lmp",
            "version": "LAMMPS test",
            "environment_script": "/opt/deepmd-env.sh",
            "plugin": "/opt/deepmd/libdeepmd_lmpplugin.so",
            "launch_prefix": [],
            "launch_arguments": [],
        },
    }
    return collection_path, card_path, site, model


def _fake_prepare(model, directory, *, potential, protocol):
    method = {
        "schema": "mlcc.lammps-method.v1",
        "engine": "lammps",
        "model_id": model.model_id,
        "version": model.version,
        "units": "metal",
        "atom_style": "atomic",
        "element_order": list(potential["element_order"]),
        "potential": dict(potential),
        "protocol": dict(protocol),
        "production_qualification": False,
    }
    (Path(directory) / "method.json").write_text(json.dumps(method), encoding="utf-8")
    for name in ("model.data", "atom-map.json", "in.lammps"):
        (Path(directory) / name).write_text(name, encoding="utf-8")
    return method


def _run0_protocol():
    return {
        "kind": "run0",
        "static_tensor": True,
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "timestep_ps": 0.001,
        "purpose": "potential_qualification",
        "experiment_scope": "CZO frozen model interface only",
    }


def _md_protocol():
    return {
        "kind": "md",
        "ensemble": "nve",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "steps": 5,
        "timestep_ps": 0.0001,
        "temperature_K": 10.0,
        "seed": 20261022,
        "thermo_every": 1,
        "dump_every": 1,
        "engineering_scope": "CZO five-step engineering smoke test",
    }


@pytest.mark.parametrize("system_id", ["host20", "vacancy19"])
def test_create_preserves_ceramic_identity_and_stages_frozen(tmp_path, monkeypatch, system_id):
    collection_path, card_path, site, model = _setup(tmp_path, monkeypatch, system_id)
    monkeypatch.setattr(ceramic_md, "prepare_lammps", _fake_prepare)
    task = ceramic_md.create_ceramic_lammps_task(
        tmp_path,
        f"ceramic-{system_id}",
        collection_path,
        system_id,
        card_path,
        _run0_protocol(),
        site,
        {"nodes": 1, "ntasks": 1, "partition": "gpu", "gres": "gpu:v100:1", "time": "00:05:00"},
    )
    assert task.data["model"]["fixture"] is False
    assert task.data["fixture"] is False
    assert task.data["potential"]["fixture"] is True
    assert task.data["potential"]["production_qualification"] is False
    assert task.data["potential"]["potential_id"] == "deepmd-czo-deepmd-training-v001"
    assert task.data["potential"]["version"] == "training-141"
    assert task.data["potential"]["model_ids"] == [model.model_id]
    assert task.data["potential"]["pair_coeff"] == ["* * Ca Zr O"]
    assert task.data["site"]["plugin"].endswith("libdeepmd_lmpplugin.so")
    assert (Path(task.data["local_workdir"]) / "frozen.pth").read_bytes() == b"exact-frozen-model"
    assert task.data["source"]["task_id"] == f"abacus-{system_id}"
    assert task.data["source"]["scheduler_job_id"] in {"50", "121"}
    assert task.data["source"]["charge"]["fields"]["method"]["value"] == 0
    frame = json.loads((Path(task.data["local_workdir"]) / "frame.json").read_text())
    assert frame["elements"] == ["Ca", "Zr", "O"]
    assert frame["source_task_id"] == f"abacus-{system_id}"


def test_create_md_requires_explicit_engineering_protocol(tmp_path, monkeypatch):
    collection_path, card_path, site, _ = _setup(tmp_path, monkeypatch, "host20")
    monkeypatch.setattr(ceramic_md, "prepare_lammps", _fake_prepare)
    task = ceramic_md.create_ceramic_lammps_task(
        tmp_path,
        "ceramic-md-host20",
        collection_path,
        "host20",
        card_path,
        _md_protocol(),
        site,
        {"nodes": 1, "ntasks": 1, "partition": "gpu", "gpus_per_task": 1},
    )
    assert "purpose" not in task.data["protocol"]
    assert task.data["protocol"]["engineering_scope"]
    assert task.data["protocol"]["temperature_K"] == 10.0
    assert task.data["protocol"]["steps"] == 5
    assert task.data["production_qualification"] is False
    assert task.data["scientific_qualification"] is False


def test_finalize_binds_real_scheduler_fields_without_qualification_override(tmp_path, monkeypatch):
    collection_path, card_path, site, model = _setup(tmp_path, monkeypatch, "host20")
    monkeypatch.setattr(ceramic_md, "prepare_lammps", _fake_prepare)
    task = ceramic_md.create_ceramic_lammps_task(
        tmp_path,
        "ceramic-finalize-host20",
        collection_path,
        "host20",
        card_path,
        _run0_protocol(),
        site,
        {"nodes": 1, "ntasks": 1, "partition": "gpu", "gres": "gpu:v100:1"},
    )
    task.set(scheduler_job_id="177", scheduler_state="COMPLETED", status="COMPLETED", exit_code="0:0", scheduler_fields={"JobId": "177", "JobState": "COMPLETED", "ExitCode": "0:0"})
    save_task(task)
    parsed = {
        "schema": "mlcc.lammps-result.v1",
        "engine": "lammps",
        "engine_version": "LAMMPS test",
        "model_id": model.model_id,
        "version": model.version,
        "protocol": _run0_protocol(),
        "potential": task.data["potential"],
    }
    monkeypatch.setattr(ceramic_md, "validate_lammps_model", lambda model, directory: None)
    monkeypatch.setattr(ceramic_md, "parse_lammps_outputs", lambda directory: parsed)
    result = ceramic_md.finalize_ceramic_lammps_task(Path(task.data["local_workdir"]) / "task.json")
    assert result["scheduler_job_id"] == "177"
    assert result["fixture"] is False
    assert result["production_qualification"] is False
    assert result["scientific_qualification"] is False
    assert result["source_task_id"] == "abacus-host20"
    assert (Path(task.data["local_workdir"]) / "result.json").is_file()


@pytest.mark.parametrize("mutation", ["card_type_map", "collection_binding"])
def test_create_rejects_unbound_training_card(tmp_path, monkeypatch, mutation):
    collection_path, card_path, site, _ = _setup(tmp_path, monkeypatch, "host20")
    if mutation == "card_type_map":
        card = json.loads(card_path.read_text())
        card["type_map"] = ["O", "Zr", "Ca"]
        card_path.write_text(json.dumps(card), encoding="utf-8")
    else:
        collection = json.loads(collection_path.read_text())
        collection["dataset_id"] = "unbound-collection"
        collection_path.write_text(json.dumps(collection), encoding="utf-8")
    with pytest.raises(ValueError):
        ceramic_md.create_ceramic_lammps_task(
            tmp_path,
            f"bad-card-{mutation}",
            collection_path,
            "host20",
            card_path,
            _run0_protocol(),
            site,
            {"nodes": 1, "ntasks": 1, "partition": "gpu", "gres": "gpu:v100:1"},
        )


def test_finalize_rejects_nonzero_slurm_exit(tmp_path, monkeypatch):
    collection_path, card_path, site, _ = _setup(tmp_path, monkeypatch, "host20")
    monkeypatch.setattr(ceramic_md, "prepare_lammps", _fake_prepare)
    task = ceramic_md.create_ceramic_lammps_task(
        tmp_path,
        "ceramic-failed-job",
        collection_path,
        "host20",
        card_path,
        _run0_protocol(),
        site,
        {"nodes": 1, "ntasks": 1, "partition": "gpu", "gres": "gpu:v100:1"},
    )
    task.set(
        scheduler_job_id="178",
        scheduler_state="COMPLETED",
        status="COMPLETED",
        exit_code="1:0",
        scheduler_fields={"JobId": "178", "JobState": "COMPLETED", "ExitCode": "1:0"},
    )
    save_task(task)
    with pytest.raises(ValueError, match="0:0"):
        ceramic_md.finalize_ceramic_lammps_task(Path(task.data["local_workdir"]) / "task.json")
