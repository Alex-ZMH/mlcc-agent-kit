from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.abacus import AbacusExecution, AbacusMethod, AbacusParameters, _input_text
from mlcc.berry_tasks import create_berry_nscf_task, create_berry_reference_task, validate_berry_reference
from mlcc.modeling import write_model_artifacts


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


_V100_WORKSPACE = Path("/home/v100/projects/mlcc/development/0.10.0/project/workspace")
_DEFAULT_BERRY_REFERENCE_TASK = _V100_WORKSPACE / "tasks/p5-czo-berry-scf-v001"
_DEFAULT_BERRY_METHOD = _V100_WORKSPACE / "configs/cazro3-berry-capability-v001.json"
_DEFAULT_BERRY_SITE = _V100_WORKSPACE / "configs/site.v100-berry-dev-v001.json"
_DEFAULT_BERRY_NSCF_REQUEST = _V100_WORKSPACE / "configs/berry-gdir1-request-v001.json"


def _configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


def _real_berry_reference_context(method_path: Path) -> tuple[Path, Path, Path, dict, Path, Path]:
    reference_task = _configured_path("MLCC_BERRY_REFERENCE_TASK", _DEFAULT_BERRY_REFERENCE_TASK)
    site_path = _configured_path("MLCC_BERRY_SITE", _DEFAULT_BERRY_SITE)
    request_path = _configured_path("MLCC_BERRY_NSCF_REQUEST", _DEFAULT_BERRY_NSCF_REQUEST)
    required_paths = [
        reference_task / "task.json",
        reference_task / "method.json",
        reference_task / "result.json",
        reference_task / "OUT.CZOBerry" / "SPIN1_CHG.cube",
        method_path,
        site_path,
        request_path,
    ]
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        pytest.skip("real v100 Berry SCF evidence/configuration is required: " + ", ".join(missing))
    reference_record = json.loads((reference_task / "task.json").read_text(encoding="utf-8"))
    model_path = Path(reference_record["model_path"])
    study_path = Path(reference_record["study_file"])
    if not model_path.is_dir() or not study_path.is_file():
        pytest.skip(f"real v100 Berry reference model/study is required: {model_path}, {study_path}")
    return reference_task, site_path, request_path, reference_record, model_path, study_path


def _isolated_nscf_inputs(tmp_path: Path, site_path: Path, request_path: Path) -> tuple[Path, Path, dict]:
    site = json.loads(site_path.read_text(encoding="utf-8"))
    site["workspace"] = dict(site["workspace"])
    site["workspace"]["local"] = str(tmp_path / "workspace")
    isolated_site = tmp_path / "site.json"
    _write_json(isolated_site, site)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["task_id"] = f"{request['task_id']}-construction-{tmp_path.name}"
    isolated_request = tmp_path / "request.json"
    _write_json(isolated_request, request)
    return isolated_site, isolated_request, request


def _fixtures(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict]:
    workspace = tmp_path / "workspace"
    model_dir = workspace / "models" / "cazro3-test" / "v001"
    atoms = Atoms(
        ["Ca", "Zr", "O", "O", "O"],
        positions=[[0, 0, 0], [2.1, 2.1, 2.1], [1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]],
        cell=np.diag([4.2, 4.2, 4.2]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.arange(len(atoms), dtype=int))
    write_model_artifacts(
        atoms,
        model_dir,
        model_id="cazro3-test",
        version="v001",
        fixture=True,
        material="CaZrO3",
        phase_requested="orthorhombic_Pnma",
        fixture_purpose="berry_input_contract",
    )
    model_path = model_dir
    method = {
        "method_set": "czo-berry-reference-v001",
        "parent_method_set": "czo-capability-v002",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "basis_type": "pw",
        "science": {
            "suffix": "CZOBerry",
            "dft_functional": "PBE",
            "nspin": 1,
            "initial_moments_muB_by_element": {"Ca": 0.0, "Zr": 0.0, "O": 0.0},
            "occupations": "fixed",
            "smearing_method": None,
            "mixing_type": "broyden",
            "relax_method": "cg",
            "symmetry": -1,
        },
        "execution": {"device": "cpu", "ks_solver": "cg"},
        "parameters": {
            "ecutwfc_Ry": 100,
            "scf_thr": 1e-4,
            "scf_nmax": 100,
            "nbands": 24,
            "smearing_sigma_Ry": None,
            "mixing_beta": 0.3,
            "force_thr_eV_per_A": None,
            "relax_nmax": None,
        },
        "element_order": ["Ca", "Zr", "O"],
        "kpoints": [2, 2, 2],
        "pseudopotential_ids": {"Ca": "ca", "Zr": "zr", "O": "o"},
        "pseudopotential_metadata": {},
        "net_charge": 0,
        "berry": {"role": "reference_scf"},
    }
    method_path = tmp_path / "method.json"
    _write_json(method_path, method)
    site = {
        "workspace": {"local": str(workspace)},
        "abacus": {
            "binary": "/opt/abacus",
            "mpi_launcher": "/opt/mpiexec.hydra",
            "environment_script": "/tmp/abacus-env.sh",
            "pseudopotential_files": {"ca": "/authorized/Ca.upf", "zr": "/authorized/Zr.upf", "o": "/authorized/O.upf"},
        },
    }
    site_path = tmp_path / "site.json"
    _write_json(site_path, site)
    study = {
        "study_id": "berry-test-study",
        "case_id": "berry-test-case",
        "case_role": "engineering_fixture",
        "model": {"model_id": "cazro3-test", "version": "v001"},
    }
    study_path = tmp_path / "study.json"
    _write_json(study_path, study)
    request = {
        "task_id": "p5-czo-berry-reference-v001",
        "calculation": "scf",
        "required_results": [],
        "resource_request": {"nodes": 1, "partition": "cpu", "ntasks": 1, "cpus_per_task": 1, "mem_mib": 1024, "time": "00:10:00"},
    }
    request_path = tmp_path / "request.json"
    _write_json(request_path, request)
    return model_path, method_path, site_path, study_path, request_path


def test_reference_materializes_native_charge_input(tmp_path: Path):
    model, method, site, study, request = _fixtures(tmp_path)
    data = create_berry_reference_task(
        study_path=study,
        model_path=model,
        method_path=method,
        site_path=site,
        request_path=request,
    )
    task_dir = Path(data["structure_source"]).parent
    native = (task_dir / "INPUT").read_text(encoding="utf-8")
    assert "calculation           scf" in native
    assert "out_chg              1" in native
    assert "berry_phase" not in native
    assert data["stage"] == "P5"
    assert data["berry"]["role"] == "reference_scf"
    assert data["berry"]["charge_density"]["files"] == ["SPIN1_CHG.cube"]
    assert data["berry"]["charge_density"]["directory"] == "OUT.CZOBerry"
    assert data["production_label"] is False
    assert data["scientific_status"] == "not_calculated"


def test_reference_rejects_non_fixed_or_non_neutral_method(tmp_path: Path):
    model, method, site, study, request = _fixtures(tmp_path)
    config = json.loads(method.read_text(encoding="utf-8"))
    config["net_charge"] = 1
    _write_json(method, config)
    with pytest.raises(ValueError, match="neutral net_charge"):
        create_berry_reference_task(
            study_path=study,
            model_path=model,
            method_path=method,
            site_path=site,
            request_path=request,
        )


def test_reference_rejects_spin_resolved_occupations(tmp_path: Path):
    model, method, site, study, request = _fixtures(tmp_path)
    config = json.loads(method.read_text(encoding="utf-8"))
    config["science"]["nspin"] = 2
    _write_json(method, config)
    with pytest.raises(ValueError, match="unsupported_spin_resolved_occupations"):
        create_berry_reference_task(
            study_path=study,
            model_path=model,
            method_path=method,
            site_path=site,
            request_path=request,
        )


def test_nscf_input_reads_copied_native_charge(tmp_path: Path):
    _model, method_path, _site, _study, _request = _fixtures(tmp_path)
    config = json.loads(method_path.read_text(encoding="utf-8"))
    method = AbacusMethod(**config["science"])
    execution = AbacusExecution(**config["execution"])
    parameters = AbacusParameters(**config["parameters"])
    native = _input_text(
        parameters,
        method=method,
        execution=execution,
        stage="nscf",
        berry={"role": "nscf", "init_chg": "file", "berry_phase": 1, "gdir": 1, "symmetry": -1, "pw_diag_thr": 1e-6},
    )
    assert "calculation           nscf" in native
    assert "init_chg            file" in native
    assert any(line.split() == ["read_file_dir", "./"] for line in native.splitlines())
    assert "berry_phase        1" in native
    assert "gdir                1" in native
    assert any(line.split() == ["symmetry", "-1"] for line in native.splitlines())
    assert any(line.split() == ["pw_diag_thr", "1e-06"] for line in native.splitlines())


def test_reference_validation_does_not_accept_result_without_native_charge(tmp_path: Path):
    model, method, site, study, request = _fixtures(tmp_path)
    data = create_berry_reference_task(
        study_path=study,
        model_path=model,
        method_path=method,
        site_path=site,
        request_path=request,
    )
    task_dir = Path(data["structure_source"]).parent
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    task.update(scheduler_state="COMPLETED", exit_code="0:0")
    (task_dir / "task.json").write_text(json.dumps(task) + "\n", encoding="utf-8")
    result = {
        "task_id": task["task_id"],
        "scheduler_job_id": None,
        "method_set": task["method_set"],
        "stage": "scf",
        "occupations": "fixed",
        "electronic_converged": True,
        "passed": True,
    }
    _write_json(task_dir / "result.json", result)
    with pytest.raises(ValueError, match="charge files"):
        validate_berry_reference(task_dir)


def test_gpu_candidate_materializes_on_single_rank_and_records_binary(tmp_path: Path):
    model, method_path, site_path, study, request_path = _fixtures(tmp_path)
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method["execution"]["device"] = "gpu"
    method["berry"] = {"implementation_id": "mlcc-abacus-3.10.1-berry-gpu-v001"}
    _write_json(method_path, method)
    site = json.loads(site_path.read_text(encoding="utf-8"))
    site["abacus"]["berry_gpu_build"] = {
        "implementation_id": "mlcc-abacus-3.10.1-berry-gpu-v001",
        "binary": site["abacus"]["binary"],
        "scope": "single_mpi_non_soc_nspin1",
    }
    _write_json(site_path, site)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["resource_request"] = {
        "nodes": 1,
        "partition": "gpu",
        "ntasks": 1,
        "cpus_per_task": 1,
        "gpus_per_task": "v100:1",
        "mem_mib": 1024,
        "time": "0",
    }
    _write_json(request_path, request)

    data = create_berry_reference_task(
        study_path=study,
        model_path=model,
        method_path=method_path,
        site_path=site_path,
        request_path=request_path,
    )
    task_dir = Path(data["structure_source"]).parent
    task_method = json.loads((task_dir / "method.json").read_text(encoding="utf-8"))
    assert data["resource_request"]["ntasks"] == 1
    assert data["resource_request"]["gpus_per_task"] == "v100:1"
    assert data["berry"]["device"] == "gpu"
    assert data["berry"]["implementation_id"] == "mlcc-abacus-3.10.1-berry-gpu-v001"
    assert data["berry"]["gpu_build"]["scope"] == "single_mpi_non_soc_nspin1"
    assert data["berry"]["binary_source"] == "/opt/abacus"
    assert task_method["berry"] == data["berry"]
    assert task_method["binary_source"] == "/opt/abacus"
    assert "/opt/abacus" in (task_dir / "run-abacus.sh").read_text(encoding="utf-8")


def test_official_gpu_scf_reference_remains_materializable_without_candidate(tmp_path: Path):
    model, method_path, site_path, study, request_path = _fixtures(tmp_path)
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method["execution"]["device"] = "gpu"
    _write_json(method_path, method)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["resource_request"].update(partition="gpu", ntasks=1, gpus_per_task="v100:1", time="0")
    _write_json(request_path, request)

    data = create_berry_reference_task(
        study_path=study,
        model_path=model,
        method_path=method_path,
        site_path=site_path,
        request_path=request_path,
    )
    assert data["berry"]["device"] == "gpu"
    assert data["berry"]["binary_source"] == "/opt/abacus"
    assert "implementation_id" not in data["berry"]
    assert "gpu_build" not in data["berry"]


def test_gpu_berry_candidate_rejects_unknown_id_or_wrong_resource(tmp_path: Path):
    model, method_path, site_path, study, request_path = _fixtures(tmp_path)
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method["execution"]["device"] = "gpu"
    method["berry"] = {"implementation_id": "unregistered-berry-build"}
    _write_json(method_path, method)
    site = json.loads(site_path.read_text(encoding="utf-8"))
    site["abacus"]["berry_gpu_build"] = {
        "implementation_id": "mlcc-abacus-3.10.1-berry-gpu-v001",
        "binary": site["abacus"]["binary"],
        "scope": "single_mpi_non_soc_nspin1",
    }
    _write_json(site_path, site)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["resource_request"].update(partition="gpu", ntasks=2, gpus_per_task="v100:1", time="0")
    _write_json(request_path, request)
    with pytest.raises(ValueError, match="implementation_id"):
        create_berry_reference_task(
            study_path=study,
            model_path=model,
            method_path=method_path,
            site_path=site_path,
            request_path=request_path,
        )

    method["berry"]["implementation_id"] = "mlcc-abacus-3.10.1-berry-gpu-v001"
    _write_json(method_path, method)
    with pytest.raises(ValueError, match="ntasks=1"):
        create_berry_reference_task(
            study_path=study,
            model_path=model,
            method_path=method_path,
            site_path=site_path,
            request_path=request_path,
        )


def test_real_v100_reference_rejects_gpu_berry_nscf(tmp_path: Path):
    """Reject a GPU Berry NSCF before materializing a task directory."""

    method_path = _configured_path("MLCC_BERRY_GPU_METHOD", _DEFAULT_BERRY_METHOD)
    if not method_path.is_file():
        pytest.skip(f"real v100 GPU Berry method configuration is required: {method_path}")
    method_config = json.loads(method_path.read_text(encoding="utf-8"))
    if method_config.get("execution", {}).get("device") != "gpu":
        pytest.skip(f"GPU Berry rejection fixture must declare execution.device=gpu: {method_path}")
    reference_task, site_path, request_path, _reference_record, _model_path, _study_path = _real_berry_reference_context(
        method_path
    )
    isolated_site, isolated_request, request = _isolated_nscf_inputs(tmp_path, site_path, request_path)

    with pytest.raises(ValueError, match=r"site\.abacus\.berry_gpu_build|implementation_id"):
        create_berry_nscf_task(
            reference_task_path=reference_task,
            method_path=method_path,
            site_path=isolated_site,
            request_path=isolated_request,
        )
    assert not (tmp_path / "workspace" / "tasks" / request["task_id"]).exists()


def test_nscf_materializes_from_real_v100_scf_reference(tmp_path: Path):
    """Bind an NSCF input to the retained native v100 SCF evidence.

    This is intentionally an integration fixture check.  The positive path is
    skipped until the real Slurm SCF task, its result, and its native
    ``OUT.<suffix>/SPIN1_CHG.cube`` have been collected; no synthetic evidence
    is created here.
    """

    method_env = os.environ.get("MLCC_BERRY_METHOD")
    if not method_env:
        pytest.skip("set MLCC_BERRY_METHOD to an explicit CPU Berry method configuration")
    method_path = Path(method_env)
    method_config = json.loads(method_path.read_text(encoding="utf-8")) if method_path.is_file() else {}
    if method_config.get("execution", {}).get("device") != "cpu":
        pytest.fail("MLCC_BERRY_METHOD must point to an explicit CPU Berry method configuration")
    reference_task, site_path, request_path, reference_record, _model_path, _study_path = _real_berry_reference_context(
        method_path
    )
    # Keep the real method/PP snapshot and native reference untouched while
    # materializing the NSCF task in pytest's isolated workspace.
    isolated_site, isolated_request, _request = _isolated_nscf_inputs(tmp_path, site_path, request_path)

    data = create_berry_nscf_task(
        reference_task_path=reference_task,
        method_path=method_path,
        site_path=isolated_site,
        request_path=isolated_request,
    )
    task_dir = Path(data["structure_source"]).parent
    task_method = json.loads((task_dir / "method.json").read_text(encoding="utf-8"))
    task_input = (task_dir / "INPUT").read_text(encoding="utf-8")
    reference_method = json.loads((reference_task / "method.json").read_text(encoding="utf-8"))
    reference_charge = (reference_task / "OUT.CZOBerry" / "SPIN1_CHG.cube").resolve()
    charge_file = task_dir / "SPIN1_CHG.cube"

    assert data["stage"] == "P5"
    assert data["calculation"] == "nscf"
    assert data["berry"]["source_reference_task_id"] == reference_record["task_id"]
    assert data["berry"]["charge_density"] == {
        "files": ["SPIN1_CHG.cube"],
        "directory": "task_root",
        "read_file_dir": "./",
        "source_task_id": reference_record["task_id"],
        "source_paths": [str(reference_charge)],
    }
    assert charge_file.is_file() and charge_file.stat().st_size == reference_charge.stat().st_size
    assert task_method["ks_solver"] == reference_method["ks_solver"]
    assert "calculation           nscf" in task_input
    assert any(line.split() == ["init_chg", "file"] for line in task_input.splitlines())
    assert any(line.split() == ["read_file_dir", "./"] for line in task_input.splitlines())

