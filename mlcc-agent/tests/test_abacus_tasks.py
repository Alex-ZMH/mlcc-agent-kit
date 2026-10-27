from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase.io import read

from mlcc.abacus_tasks import create_abacus_task, parse_abacus_task
from mlcc.modeling import read_model_artifacts


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "workspace" / "models" / "ni-fcc-engineering" / "v001"
METHOD = ROOT / "workspace" / "configs" / "h1-abacus-method-v002.json"
STUDY = ROOT / "workspace" / "configs" / "cases" / "ni-engineering-v001.json"


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _inputs(tmp_path: Path, epsilon: float, *, bad_model: bool = False) -> tuple[dict, dict, dict, dict]:
    workspace = tmp_path / "workspace"
    (workspace / "tasks").mkdir(parents=True)
    method = json.loads(METHOD.read_text(encoding="utf-8"))
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    if bad_model:
        study["model"]["model_id"] = "unselected-model"
    site = {
        "workspace": {"local": str(workspace)},
        "abacus": {
            "binary": "/opt/abacus",
            "mpi_launcher": "/opt/mpiexec.hydra",
            "environment_script": "/tmp/abacus-env.sh",
            "pseudopotential_files": {"Ni_ONCV_PBE_1.2_18e": "/authorized/Ni.upf"},
        },
    }
    request = {
        "task_id": "h1-ni-strainminus-v002" if epsilon < 0 else "h1-ni-strainplus-v002",
        "calculation": "scf",
        "input_transformation": {
            "kind": "isotropic_strain", "epsilon": epsilon, "reference_task": "h1-ni-scf-v001"
        },
        "required_results": [
            {"task_id": "h1-ni-scf-v001", "result_file": "result.json", "scientific_status": "converged_engineering_fixture"},
            {"task_id": "h1-ni-cutoff120-v001", "result_file": "result.json", "scientific_status": "converged_engineering_fixture"},
        ],
        "resource_request": {"nodes": 1, "partition": "gpu", "ntasks": 1, "cpus_per_task": 1, "gpus_per_task": "v100:1", "hint": "nomultithread", "mem_mib": 8192, "time": "00:20:00"},
    }
    paths = {"method": tmp_path / "method.json", "study": tmp_path / "study.json", "site": tmp_path / "site.json", "request": tmp_path / "request.json"}
    _json(paths["method"], method); _json(paths["study"], study); _json(paths["site"], site); _json(paths["request"], request)
    return paths, site, request, study


@pytest.mark.parametrize("epsilon", (-0.005, 0.005))
def test_create_abacus_task_materializes_strained_native_inputs(tmp_path: Path, epsilon: float):
    model = read_model_artifacts(MODEL)
    paths, site, request, study = _inputs(tmp_path, epsilon)
    data = create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"], site_path=paths["site"], request_path=paths["request"])
    task_dir = Path(site["workspace"]["local"]) / "tasks" / request["task_id"]
    strained = read(task_dir / "input.extxyz")
    assert (data["study_id"], data["case_id"], data["case_role"]) == (study["study_id"], study["case_id"], study["case_role"])
    assert data["depends_on"] == [item["task_id"] for item in request["required_results"]]
    assert data["resource_request"] == request["resource_request"]
    assert data["collect_paths"] == ["stdout.log", "stderr.log", "OUT.NiPWStrain", "gpu-inventory.csv"]
    assert "suffix                NiPWStrain" in (task_dir / "INPUT").read_text(encoding="utf-8")
    assert "-launcher slurm" in (task_dir / "run-abacus.sh").read_text(encoding="utf-8")
    assert strained.arrays["atom_id"].tolist() == model.atom_ids
    assert np.allclose(strained.cell.array, model.atoms.cell.array * (1.0 + epsilon))
    assert np.allclose(strained.get_scaled_positions(wrap=False), model.atoms.get_scaled_positions(wrap=False))
    assert data["input_transformation"]["fractional_coordinates_fixed"] is True
    assert data["input_transformation"]["atom_ids"] == model.atom_ids
    method = json.loads((task_dir / "method.json").read_text(encoding="utf-8"))
    assert method["method_set"] == "ni-oncv-pbe18-pw-engineering-v002"
    assert method["pseudopotential_ids"]["Ni"] == "Ni_ONCV_PBE_1.2_18e"


def test_create_abacus_task_rejects_study_without_selected_model(tmp_path: Path):
    paths, site, request, _ = _inputs(tmp_path, 0.005, bad_model=True)
    with pytest.raises(ValueError, match="must explicitly select this model ID and version"):
        create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"], site_path=paths["site"], request_path=paths["request"])


@pytest.mark.parametrize("metadata,error", [
    ({"derivation": {"charge_state": 1}}, "charge_state must equal method net_charge"),
    ({"study_binding": "a-different-study"}, "study_binding"),
])
def test_derivation_identity_cannot_be_silently_reinterpreted(tmp_path, monkeypatch, metadata, error):
    paths, site, request, _ = _inputs(tmp_path, 0.005)
    model = read_model_artifacts(MODEL)
    model.metadata.update(metadata)
    monkeypatch.setattr("mlcc.abacus_tasks.read_model_artifacts", lambda path: model)
    with pytest.raises(ValueError, match=error):
        create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"],
                           site_path=paths["site"], request_path=paths["request"])
    assert not (Path(site["workspace"]["local"]) / "tasks" / request["task_id"]).exists()


def test_charged_fixture_requires_explicit_input_qualification(tmp_path, monkeypatch):
    paths, site, request, _ = _inputs(tmp_path, 0.005)
    method = json.loads(paths["method"].read_text(encoding="utf-8"))
    method["net_charge"] = 2
    method["science"].update(nspin=1, occupations="fixed", smearing_method=None,
                              initial_moments_muB_by_element={"Ni": 0.0})
    _json(paths["method"], method)
    request["input_transformation"] = None
    _json(paths["request"], request)
    model = read_model_artifacts(MODEL)
    model.metadata["derivation"] = {"charge_state": 2}
    monkeypatch.setattr("mlcc.abacus_tasks.read_model_artifacts", lambda path: model)
    with pytest.raises(ValueError, match="explicit method input qualification"):
        create_abacus_task(model_path=MODEL, method_path=paths["method"],
                           study_path=paths["study"], site_path=paths["site"],
                           request_path=paths["request"])
    assert not (Path(site["workspace"]["local"]) / "tasks" / request["task_id"]).exists()


def test_charged_task_requires_model_and_method_charge_identity(tmp_path):
    paths, site, request, _ = _inputs(tmp_path, 0.005)
    method = json.loads(paths["method"].read_text(encoding="utf-8"))
    method["net_charge"] = 2
    _json(paths["method"], method)
    with pytest.raises(ValueError, match="charge_state must equal method net_charge"):
        create_abacus_task(model_path=MODEL, method_path=paths["method"],
                           study_path=paths["study"], site_path=paths["site"],
                           request_path=paths["request"])


def test_shear_task_preserves_fractional_sites_and_engineering_strain(tmp_path: Path):
    paths, site, request, _ = _inputs(tmp_path, 0.005)
    request["input_transformation"] = {
        "kind": "voigt_strain", "strain_voigt": [0, 0, 0, 0.01, 0, 0],
        "reference_task": "h1-ni-scf-v001",
    }
    _json(paths["request"], request)
    data = create_abacus_task(model_path=MODEL, method_path=paths["method"],
                             study_path=paths["study"], site_path=paths["site"],
                             request_path=paths["request"])
    parent = read_model_artifacts(MODEL).atoms
    directory = Path(site["workspace"]["local"]) / "tasks" / request["task_id"]
    strained = read(directory / "input.extxyz")
    deformation = np.eye(3)
    deformation[1, 2] = deformation[2, 1] = 0.005
    assert np.allclose(strained.cell.array, parent.cell.array @ deformation.T)
    assert np.allclose(strained.get_scaled_positions(), parent.get_scaled_positions())
    assert strained.arrays["atom_id"].tolist() == parent.arrays["atom_id"].tolist()
    assert data["input_transformation"]["strain_voigt"] == [0, 0, 0, 0.01, 0, 0]
    assert data["scheduler_job_id"] is None


def test_strain_transform_rejects_relaxed_ion_request(tmp_path: Path):
    paths, _, request, _ = _inputs(tmp_path, 0.005)
    request["calculation"] = "relax"
    _json(paths["request"], request)
    with pytest.raises(ValueError, match="fixed-fractional-coordinate SCF"):
        create_abacus_task(model_path=MODEL, method_path=paths["method"],
                           study_path=paths["study"], site_path=paths["site"],
                           request_path=paths["request"])


def test_capability_task_uses_requested_grid_and_threshold(tmp_path: Path):
    paths, site, request, _ = _inputs(tmp_path, 0.005)
    config = json.loads(paths["method"].read_text(encoding="utf-8"))
    config["kpoints"] = [2, 2, 2]
    config["parameters"]["scf_thr"] = 1e-4
    _json(paths["method"], config)
    request["input_transformation"] = None
    _json(paths["request"], request)
    create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"], site_path=paths["site"], request_path=paths["request"])
    directory = Path(site["workspace"]["local"]) / "tasks" / request["task_id"]
    assert (directory / "KPT").read_text().splitlines()[-1] == "2 2 2 0 0 0"
    native = dict(line.split()[:2] for line in (directory / "INPUT").read_text().splitlines()[1:] if line.strip())
    assert float(native["scf_thr"]) == 1e-4
    assert np.allclose(read(directory / "input.extxyz").cell, read_model_artifacts(MODEL).atoms.cell)


@pytest.mark.parametrize("field,wrong_value", [("material", "Co"), ("phase_requested", "bcc")])
def test_scientific_task_rejects_material_or_phase_mismatch(tmp_path: Path, monkeypatch, field, wrong_value):
    paths, _, _, study = _inputs(tmp_path, 0.005)
    model = read_model_artifacts(MODEL)
    model.metadata["fixture"] = False
    study["case_role"] = "scientific_validation"
    study["model"].update(material=model.metadata["material"], phase_requested=model.metadata["phase_requested"])
    study["model"][field] = wrong_value
    _json(paths["study"], study)
    monkeypatch.setattr("mlcc.abacus_tasks.read_model_artifacts", lambda path: model)
    with pytest.raises(ValueError, match=f"study {field} must match"):
        create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"],
                           site_path=paths["site"], request_path=paths["request"])


def test_parse_uses_explicit_model_path_instead_of_site_convention(tmp_path: Path, monkeypatch):
    """A model accepted outside site.workspace/models must also be readable at parse time."""
    paths, site, request, _ = _inputs(tmp_path, 0.005)
    data = create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"],
                              site_path=paths["site"], request_path=paths["request"])
    task_path = Path(site["workspace"]["local"]) / "tasks" / request["task_id"] / "task.json"
    data.update(scheduler_state="COMPLETED", exit_code="0:0")
    _json(task_path, data)
    observed = []

    class StopBeforeParsing(Exception):
        pass

    def capture_model(path):
        observed.append(Path(path))
        raise StopBeforeParsing

    monkeypatch.setattr("mlcc.abacus_tasks.read_model_artifacts", capture_model)
    with pytest.raises(StopBeforeParsing):
        parse_abacus_task(task_path, paths["site"])
    assert observed == [MODEL.resolve()]
