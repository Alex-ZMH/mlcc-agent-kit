from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from mlcc.lammps_tasks import create_lammps_task, parse_lammps_task, read_lammps_task


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "workspace" / "models" / "ni-fcc-engineering" / "v001"
REAL_MODEL = ROOT / "workspace" / "models" / "ni-abacus-engineering-relaxed" / "v001"
REAL_MODEL_FILES = ("model.json", "model.extxyz")
REAL_LAMMPS_TASK = ROOT / "workspace" / "tasks" / "p9-ni-lammps-run0-v001"
REAL_LAMMPS_FILES = (
    "task.json",
    "method.json",
    "atom-map.json",
    "in.lammps",
    "log.lammps",
    "dump.final",
    "Ni_u3.eam",
)
REAL_LAMMPS_AVAILABLE = REAL_LAMMPS_TASK.is_dir() and all(
    (REAL_LAMMPS_TASK / name).is_file() for name in REAL_LAMMPS_FILES
) and REAL_MODEL.is_dir() and all((REAL_MODEL / name).is_file() for name in REAL_MODEL_FILES)


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _inputs(tmp_path: Path, *, kind: str = "run0") -> dict[str, Path | dict]:
    workspace = tmp_path / "workspace"
    (workspace / "tasks").mkdir(parents=True)
    model_path = tmp_path / "model"
    shutil.copytree(MODEL, model_path)
    potential_file = tmp_path / "Ni_u3.eam"
    potential_file.write_text("fixture potential\n", encoding="utf-8")
    study = {
        "study_id": "ni-lammps-fixture-v001",
        "case_id": "ni_lammps_fixture",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": "ni-fcc-engineering",
            "version": "v001",
            "fixture": True,
        },
    }
    potential = {
        "potential_id": "ni-u3",
        "version": "stable22Jul2025-update4",
        "source": "LAMMPS bundled Ni_u3.eam",
        "license": "GPL-2.0",
        "fixture": True,
        "production_qualification": False,
        "units": "metal",
        "atom_style": "atomic",
        "elements": ["Ni"],
        "element_order": ["Ni"],
        "model_ids": ["ni-fcc-engineering"],
        "pair_style": "eam",
        "pair_coeff": ["* * Ni_u3.eam"],
        "files": [{"local_path": str(potential_file), "filename": "Ni_u3.eam"}],
    }
    protocol = {
        "kind": kind,
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "none" if kind == "run0" else "nvt",
        "timestep_ps": 0.001,
    }
    if kind == "md":
        protocol.update(
            {
                "steps": 4,
                "timestep_ps": 0.001,
                "temperature_K": 300.0,
                "tdamp_ps": 0.1,
                "seed": 17,
                "thermo_every": 2,
                "dump_every": 4,
            }
        )
    site = {
        "ssh": {"alias": "v100"},
        "workspace": {"local": str(workspace), "remote_root": "/home/v100/projects/mlcc"},
        "runner": {"selected": "slurm"},
        "lammps": {
            "binary": "/home/v100/projects/mlcc/.venv-lammps/bin/lmp",
            "version": "LAMMPS (22 Jul 2025 - Update 4)",
            "environment_script": "/home/v100/projects/mlcc/lammps-env.sh",
            "launch_prefix": [],
        },
    }
    request = {
        "task_id": f"p9-ni-lammps-{kind}-v001",
        "required_results": [],
        "resource_request": {
            "nodes": 1,
            "partition": "cpu",
            "ntasks": 1,
            "cpus_per_task": 1,
            "mem_mib": 1024,
            "time": "00:05:00",
        },
    }
    paths = {
        "study": tmp_path / "study.json",
        "model": model_path,
        "potential": tmp_path / "potential.json",
        "protocol": tmp_path / "protocol.json",
        "site": tmp_path / "site.json",
        "request": tmp_path / "request.json",
    }
    _json(paths["study"], study)
    _json(paths["potential"], potential)
    _json(paths["protocol"], protocol)
    _json(paths["site"], site)
    _json(paths["request"], request)
    paths.update({"workspace": workspace, "request_record": request, "protocol_record": protocol})
    return paths


def _mace_inputs(tmp_path: Path) -> dict[str, Path | dict]:
    paths = _inputs(tmp_path)
    model_file = tmp_path / "mace-candidate.model-lammps.pt"
    model_file.write_text("candidate TorchScript placeholder\n", encoding="utf-8")
    potential = json.loads(paths["potential"].read_text(encoding="utf-8"))
    potential.update(
        potential_id="mace-mp-0b3-candidate",
        version="mace-0.3.10-model-v001",
        source="ACEsuit MACE-MP-0b3 public candidate",
        license="MIT model release; candidate only",
        fixture=True,
        production_qualification=False,
        elements=["Ni"],
        element_order=["Ni"],
        pair_style="mace no_domain_decomposition",
        pair_coeff=["* * mace-candidate.model-lammps.pt Ni"],
        files=[{"local_path": str(model_file), "filename": "mace-candidate.model-lammps.pt"}],
    )
    protocol = json.loads(paths["protocol"].read_text(encoding="utf-8"))
    protocol.update(
        purpose="potential_qualification",
        static_tensor=True,
        experiment_scope="Unit MACE task input contract only",
    )
    site = json.loads(paths["site"].read_text(encoding="utf-8"))
    site["lammps"]["launch_arguments"] = ["-k", "on", "g", "1", "-sf", "kk"]
    request = json.loads(paths["request"].read_text(encoding="utf-8"))
    request["resource_request"].update(nodes=1, gres="gpu:v100:1")
    _json(paths["potential"], potential)
    _json(paths["protocol"], protocol)
    _json(paths["site"], site)
    _json(paths["request"], request)
    paths["protocol_record"] = protocol
    paths["request_record"] = request
    return paths


def test_create_lammps_task_stages_atomic_run0_and_direct_command(tmp_path: Path):
    paths = _inputs(tmp_path)

    data = create_lammps_task(
        study_path=paths["study"],
        model_path=paths["model"],
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )

    directory = paths["workspace"] / "tasks" / paths["request_record"]["task_id"]
    assert data["engine"] == "lammps"
    assert data["engine_version"] == "LAMMPS (22 Jul 2025 - Update 4)"
    assert data["fixture"] is True
    assert data["production_label"] is False
    assert "site_path" not in data
    assert "potential_path" not in data
    assert "protocol_path" not in data
    assert data["protocol"]["kind"] == "run0"
    assert data["stage"] == "P9"
    assert data["command"] == [
        "/home/v100/projects/mlcc/.venv-lammps/bin/lmp",
        "-in",
        "in.lammps",
        "-log",
        "log.lammps",
    ]
    assert data["transfer_paths"] == [
        "model.data",
        "atom-map.json",
        "in.lammps",
        "method.json",
        "Ni_u3.eam",
    ]
    assert (directory / "model.data").is_file()
    assert (directory / "atom-map.json").is_file()
    assert (directory / "in.lammps").is_file()
    assert (directory / "method.json").is_file()
    assert (directory / "Ni_u3.eam").read_text(encoding="utf-8") == "fixture potential\n"
    input_text = (directory / "in.lammps").read_text(encoding="utf-8")
    assert "run 0" in input_text
    assert "pair_coeff * * Ni_u3.eam\n" in input_text
    assert data["parent_model"]["path"] == str(paths["model"].resolve())
    assert data["parent_model"]["atom_ids"] == [0, 1, 2, 3]
    assert data["status"] == "defined"
    assert data["scheduler_job_id"] is None
    assert data["site"]["launch_arguments"] == []


def test_create_mace_candidate_requires_explicit_single_gpu_and_launch_arguments(tmp_path: Path):
    paths = _mace_inputs(tmp_path)
    data = create_lammps_task(
        **{f"{name}_path": paths[name] for name in ("study", "model", "potential", "protocol", "site", "request")}
    )
    directory = paths["workspace"] / "tasks" / paths["request_record"]["task_id"]
    assert data["production_label"] is False
    assert data["production_qualification"] is False
    assert data["command"] == [
        "/home/v100/projects/mlcc/.venv-lammps/bin/lmp",
        "-k",
        "on",
        "g",
        "1",
        "-sf",
        "kk",
        "-in",
        "in.lammps",
        "-log",
        "log.lammps",
    ]
    input_text = (directory / "in.lammps").read_text(encoding="utf-8")
    assert "package kokkos neigh half newton on" in input_text
    assert "atom_modify map yes" in input_text
    assert "atom_modify sort 0 0.0" in input_text

    missing_launch = _mace_inputs(tmp_path / "missing-launch")
    site = json.loads(missing_launch["site"].read_text(encoding="utf-8"))
    del site["lammps"]["launch_arguments"]
    _json(missing_launch["site"], site)
    with pytest.raises(ValueError, match="launch_arguments"):
        create_lammps_task(
            **{f"{name}_path": missing_launch[name] for name in ("study", "model", "potential", "protocol", "site", "request")}
        )
    assert not (missing_launch["workspace"] / "tasks" / missing_launch["request_record"]["task_id"]).exists()

    missing_gpu = _mace_inputs(tmp_path / "missing-gpu")
    request = json.loads(missing_gpu["request"].read_text(encoding="utf-8"))
    del request["resource_request"]["gres"]
    _json(missing_gpu["request"], request)
    with pytest.raises(ValueError, match="explicit GPU"):
        create_lammps_task(
            **{f"{name}_path": missing_gpu[name] for name in ("study", "model", "potential", "protocol", "site", "request")}
        )
    assert not (missing_gpu["workspace"] / "tasks" / missing_gpu["request_record"]["task_id"]).exists()


def test_create_lammps_task_preserves_md_protocol_without_sampling_claim(tmp_path: Path):
    paths = _inputs(tmp_path, kind="md")

    data = create_lammps_task(
        study_path=paths["study"],
        model_path=paths["model"],
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )

    assert data["stage"] == "P10"
    assert data["protocol"] == paths["protocol_record"]
    assert data["command"][0:1] == ["/home/v100/projects/mlcc/.venv-lammps/bin/lmp"]
    assert "temperature_K" in data["protocol"]
    assert data["protocol"]["ensemble"] == "nvt"
    assert data["protocol"]["tdamp_ps"] == 0.1
    assert data["resource_request"]["ntasks"] == 1
    assert "dump.final" in data["collect_paths"]
    assert "trajectory.lammpstrj" in data["collect_paths"]
    assert data["scientific_status"] == "not_calculated"


def test_create_lammps_task_rejects_potential_for_other_element(tmp_path: Path):
    paths = _inputs(tmp_path)
    potential = json.loads(paths["potential"].read_text(encoding="utf-8"))
    potential["model_ids"] = ["other-model"]
    _json(paths["potential"], potential)

    with pytest.raises(ValueError, match="potential.*applicable"):
        create_lammps_task(
            study_path=paths["study"],
            model_path=paths["model"],
            potential_path=paths["potential"],
            protocol_path=paths["protocol"],
            site_path=paths["site"],
            request_path=paths["request"],
        )


@pytest.mark.parametrize(
    ("steps", "dump_every"),
    [(0, 4), (4, 0), (21, 10)],
)
def test_create_lammps_task_rejects_invalid_md_protocol_before_task_dir(
    tmp_path: Path, steps: int, dump_every: int
):
    paths = _inputs(tmp_path, kind="md")
    protocol = json.loads(paths["protocol"].read_text(encoding="utf-8"))
    protocol["steps"] = steps
    protocol["dump_every"] = dump_every
    _json(paths["protocol"], protocol)

    task_directory = paths["workspace"] / "tasks" / paths["request_record"]["task_id"]
    with pytest.raises(ValueError):
        create_lammps_task(
            study_path=paths["study"],
            model_path=paths["model"],
            potential_path=paths["potential"],
            protocol_path=paths["protocol"],
            site_path=paths["site"],
            request_path=paths["request"],
        )
    assert not task_directory.exists()


def test_parse_lammps_task_requires_saved_slurm_terminal_state(tmp_path: Path):
    paths = _inputs(tmp_path)
    data = create_lammps_task(
        study_path=paths["study"],
        model_path=paths["model"],
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )
    task_path = paths["workspace"] / "tasks" / paths["request_record"]["task_id"] / "task.json"
    data.update(scheduler_state="RUNNING", exit_code="0:0")
    _json(task_path, data)

    with pytest.raises(ValueError, match="COMPLETED/0:0"):
        parse_lammps_task(task_path)


def test_create_static_tensor_task_preserves_explicit_protocol(tmp_path):
    paths = _inputs(tmp_path)
    protocol = {**paths["protocol_record"], "static_tensor": True}
    _json(paths["protocol"], protocol)
    result = create_lammps_task(**{f"{name}_path": paths[name] for name in ("study", "model", "potential", "protocol", "site", "request")})
    assert result["protocol"] == protocol
    directory = paths["workspace"] / "tasks" / paths["request_record"]["task_id"]
    assert "pxx pyy pzz pxy pxz pyz" in (directory / "in.lammps").read_text()
    assert result["production_label"] is False


def test_parse_lammps_task_binds_native_potential_and_engine_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = _inputs(tmp_path)
    task_data = create_lammps_task(
        study_path=paths["study"],
        model_path=paths["model"],
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )
    task_path = paths["workspace"] / "tasks" / paths["request_record"]["task_id"] / "task.json"
    directory = task_path.parent
    task_data.update(scheduler_state="COMPLETED", exit_code="0:0")
    _json(task_path, task_data)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    parsed = {
        "engine": "lammps",
        "engine_version": task_data["engine_version"],
        "model_id": task_data["model_id"],
        "version": task_data["model_version"],
        "units": "metal",
        "potential": method["potential"],
        "protocol": method["protocol"],
        "source_files": {"method.json": str(directory / "method.json")},
        "step": 0,
        "thermo": {},
    }
    monkeypatch.setattr("mlcc.lammps_tasks.parse_lammps_outputs", lambda _: parsed)

    result = parse_lammps_task(task_path)
    assert result["potential"]["files"][0]["local_path"] == method["potential"]["files"][0][
        "local_path"
    ]
    assert result["scientific_status"] == "evaluated_engineering_fixture"

    bad_potential = dict(parsed)
    bad_potential["potential"] = dict(method["potential"], version="other-version")
    monkeypatch.setattr("mlcc.lammps_tasks.parse_lammps_outputs", lambda _: bad_potential)
    with pytest.raises(ValueError, match="potential identity"):
        parse_lammps_task(task_path)

    bad_version = dict(parsed, engine_version="other-lammps-version")
    monkeypatch.setattr("mlcc.lammps_tasks.parse_lammps_outputs", lambda _: bad_version)
    with pytest.raises(ValueError, match="engine version"):
        parse_lammps_task(task_path)


def _copy_real_lammps_task(tmp_path: Path) -> Path:
    copied = tmp_path / REAL_LAMMPS_TASK.name
    shutil.copytree(REAL_LAMMPS_TASK, copied)
    task_path = copied / "task.json"
    task_data = json.loads(task_path.read_text(encoding="utf-8"))
    model_path = str(REAL_MODEL.resolve())
    task_data["model_path"] = model_path
    task_data["model"]["path"] = model_path
    task_data["model"]["parent_model"]["path"] = model_path
    task_data["parent_model"]["path"] = model_path
    _json(task_path, task_data)
    return copied


@pytest.mark.skipif(not REAL_LAMMPS_AVAILABLE, reason="real job41 evidence unavailable")
def test_read_real_job41_does_not_mutate_evidence(tmp_path):
    copied = _copy_real_lammps_task(tmp_path)
    before = {path.name: path.read_bytes() for path in copied.iterdir() if path.is_file()}
    result = read_lammps_task(copied / "task.json")
    after = {path.name: path.read_bytes() for path in copied.iterdir() if path.is_file()}
    assert before == after
    assert result["production_label"] is False
    assert "stress_GPa" not in result


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 task or bound model artifacts are not available",
)
def test_parse_real_job41_run0_is_engineering_fixture_only(tmp_path: Path):
    copied = _copy_real_lammps_task(tmp_path)

    result = parse_lammps_task(copied / "task.json")

    assert result["task_id"] == "p9-ni-lammps-run0-v001"
    assert result["scheduler_job_id"] == "41"
    assert result["scheduler_state"] == "COMPLETED"
    assert result["exit_code"] == "0:0"
    assert result["scientific_status"] == "evaluated_engineering_fixture"
    assert result["production_label"] is False
    assert result["production_qualification"] is False
    assert result["engine_version"] == "LAMMPS (22 Jul 2025 - Update 4)"
    assert result["source_files"]["log.lammps"] == str(copied / "log.lammps")
    assert result["source_files"]["dump.final"] == str(copied / "dump.final")
    assert (copied / "result.json").is_file()


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 task or bound model artifacts are not available",
)
def test_parse_real_job41_refuses_native_version_mismatch(tmp_path: Path):
    copied = _copy_real_lammps_task(tmp_path)
    log_path = copied / "log.lammps"
    log_text = log_path.read_text(encoding="utf-8")
    log_path.write_text(
        log_text.replace(
            "LAMMPS (22 Jul 2025 - Update 4)",
            "LAMMPS (unapproved version)",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="engine version"):
        parse_lammps_task(copied / "task.json")


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 task or bound model artifacts are not available",
)
def test_parse_real_job41_refuses_nonterminal_scheduler_state(tmp_path: Path):
    copied = _copy_real_lammps_task(tmp_path)
    task_path = copied / "task.json"
    task_data = json.loads(task_path.read_text(encoding="utf-8"))
    task_data["scheduler_state"] = "FAILED"
    task_data["exit_code"] = "1:0"
    _json(task_path, task_data)

    with pytest.raises(ValueError, match="COMPLETED/0:0"):
        parse_lammps_task(task_path)


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 task or bound model artifacts are not available",
)
@pytest.mark.parametrize("remapped_start", [100, 101, 102, 103])
def test_parse_real_job41_refuses_atom_id_remap(tmp_path: Path, remapped_start: int):
    copied = _copy_real_lammps_task(tmp_path)
    atom_map_path = copied / "atom-map.json"
    atom_map = json.loads(atom_map_path.read_text(encoding="utf-8"))
    remapped_ids = [remapped_start + index for index in range(4)]
    atom_map["source_atom_ids"] = remapped_ids
    for entry, source_atom_id in zip(atom_map["atoms"], remapped_ids):
        entry["source_atom_id"] = source_atom_id
    _json(atom_map_path, atom_map)

    with pytest.raises(ValueError):
        parse_lammps_task(copied / "task.json")


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 task or bound model artifacts are not available",
)
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("calculation", "md"),
        ("stage", "P10"),
        ("method_set", "lammps-wrong-version"),
    ],
)
def test_parse_real_job41_refuses_task_calculation_stage_or_method_set(
    tmp_path: Path, field: str, value: str
):
    copied = _copy_real_lammps_task(tmp_path)
    task_path = copied / "task.json"
    task_data = json.loads(task_path.read_text(encoding="utf-8"))
    task_data[field] = value
    _json(task_path, task_data)

    with pytest.raises(ValueError):
        parse_lammps_task(task_path)


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 task or bound model artifacts are not available",
)
def test_parse_real_job41_refuses_nested_method_set_mismatch(tmp_path: Path):
    copied = _copy_real_lammps_task(tmp_path)
    task_path = copied / "task.json"
    task_data = json.loads(task_path.read_text(encoding="utf-8"))
    task_data["method"]["method_set"] = "lammps-wrong-version"
    _json(task_path, task_data)

    with pytest.raises(ValueError):
        parse_lammps_task(task_path)


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 task or bound model artifacts are not available",
)
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("license", "unapproved license"),
        ("scope", "unapproved scope"),
        ("model_ids", ["ni-abacus-engineering-relaxed", "other-model"]),
    ],
)
def test_parse_real_job41_refuses_native_potential_declaration_mutation(
    tmp_path: Path, field: str, value: object
):
    copied = _copy_real_lammps_task(tmp_path)
    method_path = copied / "method.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method["potential"][field] = value
    _json(method_path, method)

    with pytest.raises(ValueError):
        parse_lammps_task(copied / "task.json")


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 task or bound model artifacts are not available",
)
def test_parse_real_job41_requires_parent_model_binding(tmp_path: Path):
    copied = _copy_real_lammps_task(tmp_path)
    task_path = copied / "task.json"
    task_data = json.loads(task_path.read_text(encoding="utf-8"))
    task_data["parent_model"]["model_id"] = "unbound-parent"
    _json(task_path, task_data)

    with pytest.raises(ValueError):
        parse_lammps_task(task_path)


def _qualification_inputs(tmp_path):
    """Real selected geometry; dummy candidate declaration for input contracts only."""
    paths = _inputs(tmp_path)
    paths["model"] = tmp_path / "scientific-model"
    shutil.copytree(ROOT / "workspace/models/cazro3-pnma-pristine/v001", paths["model"])
    metadata = json.loads((paths["model"] / "model.json").read_text())
    assert metadata["fixture"] is False
    study = {"study_id": "unit-qualification", "case_id": "unit-czo", "case_role": "scientific_validation",
             "model": {"model_id": metadata["model_id"], "version": metadata["version"], "fixture": False,
                       "material": metadata["material"], "phase_requested": metadata["phase_requested"]}}
    potential = json.loads(paths["potential"].read_text())
    potential.update(potential_id="unit-candidate-declaration", fixture=False, production_qualification=False,
                     elements=metadata["element_order"], element_order=metadata["element_order"],
                     model_ids=[metadata["model_id"]], pair_style="unit-test-only", pair_coeff=["* * candidate.test"],
                     source="unit input contract; not a selected scientific potential")
    protocol = {**paths["protocol_record"], "purpose": "potential_qualification", "static_tensor": True,
                "experiment_scope": "Unit input contract only; no engine execution or scientific qualification"}
    potential["files"][0]["filename"] = "candidate.test"
    _json(paths["study"], study)
    _json(paths["potential"], potential)
    _json(paths["protocol"], protocol)
    return paths


def _create_from_paths(paths):
    return create_lammps_task(**{f"{name}_path": paths[name] for name in ("study", "model", "potential", "protocol", "site", "request")})


def test_qualification_purpose_preserves_real_scientific_model_and_candidate(tmp_path):
    paths = _qualification_inputs(tmp_path)
    before = (paths["model"] / "model.json").read_bytes()
    result = _create_from_paths(paths)
    assert result["fixture"] is False
    assert result["model"]["fixture"] is False
    assert result["potential"]["fixture"] is False
    assert result["production_qualification"] is result["production_label"] is False
    assert result["protocol"]["experiment_scope"].startswith("Unit input")
    model = json.loads(before)
    for key in ("source_path", "source_version"):
        assert result["parent_model"][key] == model[key]
    assert result["parent_model"]["atom_ids"] == model["atom_ids"]
    assert before == (paths["model"] / "model.json").read_bytes()
    assert result["scheduler_job_id"] is None


@pytest.mark.parametrize("change", ["md", "tensor", "scope", "ordinary", "production", "phase"])
def test_qualification_purpose_rejects_invalid_scope_before_writing_task(tmp_path, change):
    paths = _qualification_inputs(tmp_path)
    protocol = json.loads(paths["protocol"].read_text())
    if change == "md":
        protocol["kind"] = "md"
    elif change == "tensor":
        protocol["static_tensor"] = False
    elif change == "scope":
        protocol["experiment_scope"] = " "
    elif change == "ordinary":
        del protocol["purpose"]
    elif change == "production":
        potential = json.loads(paths["potential"].read_text())
        potential["production_qualification"] = True
        _json(paths["potential"], potential)
    else:
        study = json.loads(paths["study"].read_text())
        study["model"]["phase_requested"] = "unselected-phase"
        _json(paths["study"], study)
    _json(paths["protocol"], protocol)
    with pytest.raises(ValueError):
        _create_from_paths(paths)
    assert not (paths["workspace"] / "tasks" / paths["request_record"]["task_id"]).exists()


def test_qualification_purpose_read_gate_and_lineage_without_fabricated_native_log(tmp_path, monkeypatch):
    # Mock only the native parser boundary; this is not real scientific execution.
    paths = _qualification_inputs(tmp_path)
    task = _create_from_paths(paths)
    directory = paths["workspace"] / "tasks" / task["task_id"]
    task.update(scheduler_state="COMPLETED", exit_code="0:0", scheduler_job_id="unit-contract-only")
    _json(directory / "task.json", task)
    method = json.loads((directory / "method.json").read_text())
    monkeypatch.setattr("mlcc.lammps_tasks.parse_lammps_outputs", lambda _: {
        "engine": "lammps", "engine_version": task["engine_version"], "model_id": task["model_id"],
        "version": task["model_version"], "potential": method["potential"], "protocol": method["protocol"],
        "production_qualification": False})
    result = read_lammps_task(directory / "task.json")
    assert result["scientific_status"] == "evaluated_candidate_potential"
    assert result["fixture"] is False
    assert result["production_label"] is result["production_qualification"] is False
    task["parent_model"]["source_version"] = "wrong-version"
    _json(directory / "task.json", task)
    with pytest.raises(ValueError, match="lineage"):
        read_lammps_task(directory / "task.json")


def test_qualification_purpose_does_not_change_ordinary_fixture_input(tmp_path):
    paths = _inputs(tmp_path)
    result = _create_from_paths(paths)
    assert result["fixture"] is True
    assert result["potential"]["fixture"] is True
    assert "purpose" not in result["protocol"]
    assert result["production_label"] is False

