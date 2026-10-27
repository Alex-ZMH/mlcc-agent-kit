"""Focused source-contract checks for the saved BTO P7 lineage."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mlcc.dielectric_response import (
    _native_gamma_add_task_files,
    _native_gamma_task_binding,
)
from test_native_gamma_delivery_source import _native_fixture


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _p7_fixture(tmp_path: Path) -> tuple[Path, dict, dict, Path]:
    _, displacement_root, _ = _native_fixture(tmp_path)
    reference_root = displacement_root.parent / "reference"
    reference_task = json.loads((reference_root / "task.json").read_text(encoding="utf-8"))
    method = json.loads((displacement_root / "method.json").read_text(encoding="utf-8"))
    model_path = Path(reference_task["model_path"])
    model_file = model_path / "model.json"
    model = json.loads(model_file.read_text(encoding="utf-8"))
    model.update(
        {
            "spatial_mode": "phonon_displacement_child",
            "parent_models": [
                {
                    "model_id": reference_task["model_id"],
                    "version": reference_task["model_version"],
                    "path": str(model_path.resolve()),
                }
            ],
        }
    )
    _write(model_file, model)

    parent_study_path = Path(reference_task["study_file"])
    _write(
        parent_study_path,
        {
            "study_id": reference_task["study_id"],
            "case_id": reference_task["case_id"],
            "case_role": reference_task["case_role"],
            "model_id": reference_task["model_id"],
            "model_version": reference_task["model_version"],
            "model_path": str(model_path.resolve()),
            "model": {
                "model_id": reference_task["model_id"],
                "version": reference_task["model_version"],
            },
        },
    )
    child_study_path = displacement_root / "p7-child-study.json"
    child_study_id = "czo-contract-displacement-study"
    _write(
        child_study_path,
        {
            "study_id": child_study_id,
            "case_id": reference_task["case_id"],
            "case_role": reference_task["case_role"],
            "parent_study_id": reference_task["study_id"],
            "derived_from": {
                "study_id": reference_task["study_id"],
                "model_id": reference_task["model_id"],
                "model_version": reference_task["model_version"],
            },
            "model": {
                "model_id": reference_task["model_id"],
                "version": reference_task["model_version"],
            },
        },
    )
    plan_path = tmp_path / "bto-displacement-plan.json"
    _write(
        plan_path,
        {
            "schema": "mlcc.phonon-displacement-plan.v1",
            "plan_id": "bto-contract-plan-v001",
            "version": "v001",
            "source_model": {
                "model_id": reference_task["model_id"],
                "version": reference_task["model_version"],
                "path": str(model_path.resolve()),
            },
            "request": {"distance_unit": "angstrom"},
            "displacements": [
                {
                    "entry_id": "disp-000001",
                    "kind": "displacement",
                    "displaced_atom_id": 0,
                    "phonopy_atom_index": 0,
                    "displacement_angstrom": [0.01, 0.0, 0.0],
                    "sign": "plus",
                }
            ],
        },
    )
    task_path = displacement_root / "task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task.update(
        {
            "stage": "P7",
            "study_id": child_study_id,
            "study_file": str(child_study_path.resolve()),
            "parent_study_id": None,
            "parent_model_id": None,
            "parent_model_version": None,
        }
    )
    task["phonon_displacement"] = {
        "plan_id": "bto-contract-plan-v001",
        "plan_version": "v001",
        "manifest_path": str(plan_path.resolve()),
        "displacement_id": "disp-000001",
        "entry_kind": "displacement",
        "displaced_atom_id": 0,
        "phonopy_atom_index": 0,
        "displacement_angstrom": [0.01, 0.0, 0.0],
        "displacement_unit": "angstrom",
        "sign": "plus",
        "parent_model_id": reference_task["model_id"],
        "parent_model_version": reference_task["model_version"],
        "parent_study_id": reference_task["study_id"],
        "parent_study_file": str(parent_study_path.resolve()),
    }
    child_study = json.loads(child_study_path.read_text(encoding="utf-8"))
    child_study["phonon_displacement"] = task["phonon_displacement"]
    _write(child_study_path, child_study)
    model = json.loads(model_file.read_text(encoding="utf-8"))
    model["phonon_displacement"] = task["phonon_displacement"]
    _write(model_file, model)
    _write(task_path, task)
    parent = {
        "study_id": reference_task["study_id"],
        "model_id": reference_task["model_id"],
        "model_version": reference_task["model_version"],
        "model_path": reference_task["model_path"],
    }
    case = {
        "case_id": reference_task["case_id"],
        "case_role": reference_task["case_role"],
    }
    return task_path, parent, case, parent_study_path


def test_p7_binding_uses_nested_study_and_parent_files(tmp_path: Path):
    task_path, parent, case, parent_study_path = _p7_fixture(tmp_path)
    binding = _native_gamma_task_binding(
        task_path,
        role="BTO P7 displacement",
        expected_method_set="czo-native-gamma-contract",
        expected_parent=parent,
        expected_case=case,
        expected_method_identity=None,
        expected_model_context=None,
    )

    refs: list[str] = []
    _native_gamma_add_task_files(binding, refs, include_study=True)
    assert str(task_path.parent / "p7-child-study.json") in refs
    assert str(parent_study_path) in refs
    assert str(task_path.parent / "study.json") not in refs


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_displacement",
        "wrong_parent",
        "wrong_manifest_entry",
        "false_child_study",
        "false_child_case",
    ],
)
def test_p7_binding_rejects_incomplete_or_false_lineage(tmp_path: Path, mutation: str):
    task_path, parent, case, _ = _p7_fixture(tmp_path)
    task = json.loads(task_path.read_text(encoding="utf-8"))
    if mutation == "missing_displacement":
        task.pop("phonon_displacement")
    elif mutation == "wrong_parent":
        task["phonon_displacement"]["parent_model_id"] = "wrong-parent-model"
    elif mutation == "wrong_manifest_entry":
        manifest_path = Path(task["phonon_displacement"]["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["displacements"][0]["sign"] = "minus"
        _write(manifest_path, manifest)
    elif mutation == "false_child_study":
        child_study = json.loads(Path(task["study_file"]).read_text(encoding="utf-8"))
        child_study["parent_study_id"] = "false-parent-study"
        _write(Path(task["study_file"]), child_study)
    else:
        child_study = json.loads(Path(task["study_file"]).read_text(encoding="utf-8"))
        child_study["case_role"] = "false_case_role"
        _write(Path(task["study_file"]), child_study)
    _write(task_path, task)

    with pytest.raises(ValueError):
        _native_gamma_task_binding(
            task_path,
            role="BTO P7 displacement",
            expected_method_set="czo-native-gamma-contract",
            expected_parent=parent,
            expected_case=case,
            expected_method_identity=None,
            expected_model_context=None,
        )


def test_p7_binding_requires_explicit_parent_model_path(tmp_path: Path):
    task_path, parent, case, _ = _p7_fixture(tmp_path)
    parent.pop("model_path")
    with pytest.raises(ValueError, match="requires reference parent model_path"):
        _native_gamma_task_binding(
            task_path,
            role="BTO P7 displacement",
            expected_method_set="czo-native-gamma-contract",
            expected_parent=parent,
            expected_case=case,
            expected_method_identity=None,
            expected_model_context=None,
        )


def test_p7_reference_binding_requires_an_expected_parent(tmp_path: Path):
    task_path, _, case, _ = _p7_fixture(tmp_path)
    with pytest.raises(ValueError, match="requires an expected parent"):
        _native_gamma_task_binding(
            task_path,
            role="BTO P7 reference",
            expected_method_set="czo-native-gamma-contract",
            expected_parent=None,
            expected_case=case,
            expected_method_identity=None,
            expected_model_context=None,
        )


@pytest.mark.skipif(
    not Path(
        os.environ.get(
            "MLCC_BTO_P7_TASK",
            "/home/v100/projects/mlcc/workspace/tasks/bto-native-lcao-disp-000001-v001/task.json",
        )
    ).is_file(),
    reason="saved BTO P7 task is available on v100 only",
)
def test_saved_bto_p7_task_binds_from_real_lineage():
    task_path = Path(
        os.environ.get(
            "MLCC_BTO_P7_TASK",
            "/home/v100/projects/mlcc/workspace/tasks/bto-native-lcao-disp-000001-v001/task.json",
        )
    )
    reference_path = Path(
        os.environ.get(
            "MLCC_BTO_P7_REFERENCE_TASK",
            "/home/v100/projects/mlcc/workspace/tasks/bto-native-lcao-ref-v001/task.json",
        )
    )
    task = json.loads(task_path.read_text(encoding="utf-8"))
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    parent = {
        "study_id": reference["study_id"],
        "model_id": reference["model_id"],
        "model_version": reference["model_version"],
        "model_path": reference["model_path"],
    }
    case = {"case_id": reference["case_id"], "case_role": reference["case_role"]}
    binding = _native_gamma_task_binding(
        task_path,
        role="saved BTO P7 displacement",
        expected_method_set=reference["method_set"],
        expected_parent=parent,
        expected_case=case,
        expected_method_identity=None,
        expected_model_context=None,
    )
    refs: list[str] = []
    _native_gamma_add_task_files(binding, refs, include_study=True)
    assert task["phonon_displacement"]["parent_study_file"] in refs
