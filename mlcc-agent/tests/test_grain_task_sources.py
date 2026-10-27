from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil

import pytest

from mlcc.grain_task_sources import (
    read_grain_task_sources,
    stage_grain_task_sources,
)
from mlcc.modeling import read_model_artifacts


def _fixture(tmp_path: Path):
    model_source = os.environ["MLCC_GRAIN_MODEL"]
    study_source = os.environ["MLCC_GRAIN_STUDY"]
    real_model = Path(model_source)
    real_study = Path(study_source)
    model_directory = tmp_path / "model"
    shutil.copytree(real_model, model_directory)
    model = read_model_artifacts(model_directory)
    study = json.loads(real_study.read_text(encoding="utf-8"))
    study["model"]["source_structure"] = str(model_directory / model.metadata["structure_file"])
    study["grain_boundary"]["source_file"] = str(model_directory / "grain-boundary.json")
    study["grain_boundary"]["atom_lineage_file"] = str(
        model_directory / model.metadata["atom_lineage_file"]
    )
    study_file = tmp_path / "study.json"
    study_file.write_text(json.dumps(study, indent=2) + "\n", encoding="utf-8")
    return model, study, study_file


def test_stage_copies_bytes_and_read_survives_task_relocation(tmp_path: Path):
    model, study, study_file = _fixture(tmp_path)
    task_directory = tmp_path / "task"
    binding = stage_grain_task_sources(study, model, task_directory, study_file=study_file)

    assert binding["schema"] == "mlcc.grain-task-sources.v1"
    assert binding["atom_ids"] == model.atom_ids
    assert len(binding["grain_ids"]) == len(model.atoms)
    assert binding["transfer_paths"] == [
        "grain-sources/grain-boundary.json",
        "grain-sources/atom-lineage.json",
    ]
    assert (task_directory / binding["task_files"]["grain_boundary"]).read_bytes() == (
        model.artifact_dir / "grain-boundary.json"
    ).read_bytes()
    assert (task_directory / binding["task_files"]["atom_lineage"]).read_bytes() == (
        model.artifact_dir / model.metadata["atom_lineage_file"]
    ).read_bytes()
    json.dumps(binding)

    relocated = tmp_path / "relocated-task"
    shutil.move(str(task_directory), relocated)
    result = read_grain_task_sources(
        relocated,
        binding,
        study_id=study["study_id"],
        model_id=model.model_id,
        model_version=model.version,
        atom_ids=model.atom_ids,
    )
    assert result["grain_boundary"]["model_id"] == model.model_id
    assert len(result["atom_lineage"]["entries"]) == len(model.atoms)
    assert result["source_files"]["grain_boundary"] == str(
        (relocated / "grain-sources/grain-boundary.json").resolve()
    )
    assert result["source_files"]["atom_lineage"] == str(
        (relocated / "grain-sources/atom-lineage.json").resolve()
    )


def test_stage_rejects_wrong_study_identity(tmp_path: Path):
    model, study, study_file = _fixture(tmp_path)
    wrong = copy.deepcopy(study)
    wrong["study_id"] = "wrong-study"
    with pytest.raises(ValueError, match="study_id"):
        stage_grain_task_sources(wrong, model, tmp_path / "task", study_file=study_file)


def test_stage_rejects_wrong_parent_identity(tmp_path: Path):
    model, study, study_file = _fixture(tmp_path)
    wrong = copy.deepcopy(study)
    wrong["grain_boundary"]["parent_model"] = copy.deepcopy(wrong["grain_boundary"]["parent_model"])
    wrong["grain_boundary"]["parent_model"]["model_id"] = "wrong-parent"
    with pytest.raises(ValueError, match="parent"):
        stage_grain_task_sources(wrong, model, tmp_path / "task", study_file=study_file)


def test_read_rejects_wrong_atom_and_grain_binding(tmp_path: Path):
    model, study, study_file = _fixture(tmp_path)
    task_directory = tmp_path / "task"
    binding = stage_grain_task_sources(study, model, task_directory, study_file=study_file)

    wrong_atoms = copy.deepcopy(binding)
    wrong_atoms["atom_ids"][0] = 900
    with pytest.raises(ValueError, match="atom_ids"):
        read_grain_task_sources(
            task_directory,
            wrong_atoms,
            study_id=study["study_id"],
            model_id=model.model_id,
            model_version=model.version,
            atom_ids=model.atom_ids,
        )

    wrong_grains = copy.deepcopy(binding)
    wrong_grains["grain_ids"][0] = 1 - wrong_grains["grain_ids"][0]
    with pytest.raises(ValueError, match="grain_id"):
        read_grain_task_sources(
            task_directory,
            wrong_grains,
            study_id=study["study_id"],
            model_id=model.model_id,
            model_version=model.version,
            atom_ids=model.atom_ids,
        )


def test_stage_preserves_missing_source_error(tmp_path: Path):
    model, study, study_file = _fixture(tmp_path)
    (model.artifact_dir / "grain-boundary.json").unlink()
    with pytest.raises(FileNotFoundError):
        stage_grain_task_sources(study, model, tmp_path / "task", study_file=study_file)
