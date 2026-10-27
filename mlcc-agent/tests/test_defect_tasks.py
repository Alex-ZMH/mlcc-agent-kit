from __future__ import annotations

import json
from pathlib import Path

import pytest

import mlcc.defect_tasks as defect_tasks
from mlcc.abacus import _energy_definition
from mlcc.model_derivatives import derive_defect_model


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
HOST_MODEL = WORKSPACE / "models" / "cazro3-pnma-pristine" / "v001"
METHOD = WORKSPACE / "configs" / "cazro3-abacus-capability-v002.json"
SITE = WORKSPACE / "configs" / "site.v100.json"


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _pair_inputs(tmp_path: Path):
    defect_request = _write(
        tmp_path / "derive-defect.json",
        {
            "model_id": "czo-neutral-vacancy-input",
            "version": "v001",
            "study_id": "czo-neutral-pair-v001",
            "charge_state": 0,
            "operations": [{"kind": "vacancy", "atom_id": 0}],
        },
    )
    defect_model_path = tmp_path / "models" / "czo-neutral-vacancy-input" / "v001"
    derive_defect_model(HOST_MODEL, json.loads(defect_request.read_text()), defect_model_path)

    base_study = json.loads((WORKSPACE / "configs" / "cases" / "cazro3-firing-v003.json").read_text())
    base_study.update(study_id="czo-neutral-pair-v001", case_id="czo_neutral_pair")
    host_study = dict(base_study)
    host_study["model"] = dict(base_study["model"])
    host_study["model"].update(model_id="cazro3-pnma-pristine", version="v001")
    defect_study = dict(base_study)
    defect_study["model"] = dict(base_study["model"])
    defect_study["model"].update(
        model_id="czo-neutral-vacancy-input",
        version="v001",
        composition=json.loads((defect_model_path / "model.json").read_text())["composition"],
    )
    host_study_path = _write(tmp_path / "host-study.json", host_study)
    defect_study_path = _write(tmp_path / "defect-study.json", defect_study)

    host_request_path = _write(
        tmp_path / "host-request.json",
        {
            "task_id": "czo-neutral-host-input",
            "calculation": "scf",
            "input_transformation": None,
            "required_results": [],
            "resource_request": {
                "nodes": 1,
                "partition": "gpu",
                "ntasks": 1,
                "cpus_per_task": 1,
                "mem_mib": 8192,
                "time": "00:05:00",
                "gpus_per_task": "v100:1",
            },
        },
    )
    defect_request_path = _write(
        tmp_path / "defect-request.json",
        {
            "task_id": "czo-neutral-defect-input",
            "calculation": "scf",
            "input_transformation": None,
            "required_results": [],
            "resource_request": {
                "nodes": 1,
                "partition": "gpu",
                "ntasks": 1,
                "cpus_per_task": 1,
                "mem_mib": 8192,
                "time": "00:05:00",
                "gpus_per_task": "v100:1",
            },
        },
    )
    chemical_reference = _write(
        tmp_path / "chemical-reference.json",
        {
            "mu_eV_per_atom": {"Ca": -5.0},
            "engine": "abacus",
            "engine_version": "3.10.1",
            "method_set": "cazro3-oncv-pbe-pw-nonsoc-capability-v002",
            "energy_definition": _energy_definition("fixed"),
            "source_reference": "test chemical-potential source",
        },
    )
    site = json.loads(SITE.read_text())
    site["workspace"] = dict(site["workspace"])
    site["workspace"]["local"] = str(tmp_path / "workspace")
    (tmp_path / "workspace" / "tasks").mkdir(parents=True)
    site_path = _write(tmp_path / "site.json", site)
    return {
        "host_model_path": HOST_MODEL,
        "defect_model_path": defect_model_path,
        "host_study_path": host_study_path,
        "defect_study_path": defect_study_path,
        "method_path": METHOD,
        "site_path": site_path,
        "host_request_path": host_request_path,
        "defect_request_path": defect_request_path,
        "chemical_reference_path": chemical_reference,
    }


def test_neutral_pair_uses_real_creator_for_native_inputs(tmp_path):
    from mlcc.cli import main

    inputs = _pair_inputs(tmp_path)
    manifest = tmp_path / "pair.json"
    arguments = ["create-neutral-defect-pair"]
    for key, value in inputs.items():
        arguments.extend(["--" + key.removesuffix("_path").replace("_", "-"), str(value)])
    arguments.extend(["--output", str(manifest)])
    assert main(arguments) == 0
    result = json.loads(manifest.read_text())

    assert result["schema"] == "mlcc.neutral-defect-task-pair.v1"
    assert result["status"] == "tasks_defined_not_submitted"
    assert result["production_qualification"] is False
    assert Path(result["host_task"]).is_file()
    assert Path(result["defect_task"]).is_file()
    for task_path in (Path(result["host_task"]), Path(result["defect_task"])):
        task_directory = task_path.parent
        assert (task_directory / "INPUT").is_file()
        assert (task_directory / "STRU").is_file()
        task = json.loads(task_path.read_text())
        assert task["scheduler_job_id"] is None
        assert task["scientific_status"] == "not_calculated"
    assert result["postprocessing"]["adapter"].endswith("neutral_formation_from_tasks")
    assert result["postprocessing"]["formation_energy_written"] is False
    assert json.loads(manifest.read_text())["descriptor_path"] == result["descriptor_path"]


def test_neutral_pair_rejects_invalid_defect_request_before_materialization(tmp_path):
    inputs = _pair_inputs(tmp_path)
    invalid = json.loads(Path(inputs["defect_request_path"]).read_text())
    invalid["calculation"] = "relax"
    _write(Path(inputs["defect_request_path"]), invalid)
    with pytest.raises(ValueError, match="defect request must request calculation=scf"):
        defect_tasks.create_neutral_defect_task_pair(**inputs)
    tasks = Path(json.loads(Path(inputs["site_path"]).read_text())["workspace"]["local"]) / "tasks"
    assert list(tasks.iterdir()) == []


def test_neutral_pair_rejects_nonzero_derived_charge_before_materialization(tmp_path):
    inputs = _pair_inputs(tmp_path)
    descriptor = json.loads((Path(inputs["defect_model_path"]) / "model.json").read_text())
    descriptor["derivation"]["charge_state"] = 1
    (Path(inputs["defect_model_path"]) / "model.json").write_text(json.dumps(descriptor) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requires charge_state=0"):
        defect_tasks.create_neutral_defect_task_pair(**inputs)


def test_neutral_pair_rejects_incompatible_chemical_energy_reference(tmp_path):
    inputs = _pair_inputs(tmp_path)
    point = json.loads(Path(inputs["chemical_reference_path"]).read_text())
    point["energy_definition"] = "different energy reference"
    _write(Path(inputs["chemical_reference_path"]), point)
    with pytest.raises(ValueError, match="energy definition differs"):
        defect_tasks.create_neutral_defect_task_pair(**inputs)
