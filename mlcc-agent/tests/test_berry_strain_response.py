from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import numpy as np
import pytest

import mlcc.berry_strain_response as response
from mlcc.modeling import read_model_artifacts
from test_polarization_strain import _write_relaxed_software_manifest


ROOT = Path(__file__).resolve().parents[2]
CZO_MODEL = Path(
    os.environ.get(
        "MLCC_BERRY_STRAIN_MODEL",
        str(ROOT / "workspace" / "models" / "cazro3-pnma-pristine" / "v001"),
    )
)
CZO_STUDY = Path(
    os.environ.get(
        "MLCC_BERRY_STRAIN_STUDY",
        str(ROOT / "workspace" / "configs" / "cases" / "cazro3-firing-v003.json"),
    )
)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def strain_request(tmp_path: Path, *, component: str = "yy", minus: float = -0.01, plus: float = 0.01) -> Path:
    request = {
        "schema": response.RESPONSE_REQUEST_SCHEMA,
        "response_id": "czo-berry-strain-response-test",
        "parent_study_id": "cazro3_firing_validation_v003",
        "parent_model_id": "cazro3-pnma-pristine",
        "parent_model_version": "v001",
        "charge_state": 0,
        "mechanical_boundary": "clamped_ion_fixed_fractional",
        "points": [
            {
                "point_id": "minus",
                "child_model_id": "czo-strain-minus",
                "child_model_version": "v001",
                "child_study_id": "czo-strain-minus-study",
                "scf_task_id": "p5-czo-strain-minus-scf",
                "voigt_component": component,
                "strain": minus,
                "gdirs": [1, 2, 3],
                "scf_resource_request": {
                    "nodes": 1,
                    "partition": "cpu",
                    "ntasks": 1,
                    "cpus_per_task": 1,
                    "mem_mib": 2048,
                    "time": 0,
                },
            },
            {
                "point_id": "plus",
                "child_model_id": "czo-strain-plus",
                "child_model_version": "v001",
                "child_study_id": "czo-strain-plus-study",
                "scf_task_id": "p5-czo-strain-plus-scf",
                "voigt_component": component,
                "strain": plus,
                "gdirs": [1, 2, 3],
                "scf_resource_request": {
                    "nodes": 1,
                    "partition": "cpu",
                    "ntasks": 1,
                    "cpus_per_task": 1,
                    "mem_mib": 2048,
                    "time": 0,
                },
            },
        ],
    }
    path = tmp_path / "strain-request.json"
    write_json(path, request)
    return path


def _fake_reference_task(*, study_path, model_path, method_path, site_path, request_path):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    study = json.loads(Path(study_path).read_text(encoding="utf-8"))
    model = read_model_artifacts(model_path)
    site = json.loads(Path(site_path).read_text(encoding="utf-8"))
    task_dir = Path(site["workspace"]["local"]) / "tasks" / request["task_id"]
    task_dir.mkdir(parents=True)
    task = {
        "task_id": request["task_id"],
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": study["case_role"],
        "model_id": model.model_id,
        "model_version": model.version,
        "model_path": str(Path(model_path).resolve()),
        "study_file": str(Path(study_path).resolve()),
        "resource_request": request["resource_request"],
        "scheduler_state": "DEFINED",
        "status": "defined",
        "scheduler_job_id": None,
        "exit_code": None,
    }
    write_json(task_dir / "task.json", task)
    return task


def _site(tmp_path: Path) -> Path:
    path = tmp_path / "site.json"
    write_json(path, {"workspace": {"local": str(tmp_path / "task-workspace")}})
    return path


def _fake_relaxed_reference_task(*, bridge_path, method_path, site_path, request_path):
    """Create only a software task record for the real saved-bridge path."""

    bridge_file = Path(bridge_path).resolve()
    bridge = json.loads(bridge_file.read_text(encoding="utf-8"))
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    task = _fake_reference_task(
        study_path=bridge["child_study"]["study_path"],
        model_path=bridge["child_model"]["path"],
        method_path=method_path,
        site_path=site_path,
        request_path=request_path,
    )
    task_path = Path(json.loads(Path(site_path).read_text(encoding="utf-8"))["workspace"]["local"])
    task_path = task_path / "tasks" / request["task_id"] / "task.json"
    source = bridge["relaxation_source"]
    dependency = {
        "task_id": source["task_id"],
        "task_file": source["task_file"],
        "result_file": source["result_file"],
        "scientific_status": source["scientific_status"],
    }
    task.update(
        {
            "engine": "abacus",
            "engine_version": "3.10.1",
            "calculation": "scf",
            "method_path": str(Path(method_path).resolve()),
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "evidence_kind": "software_contract_only",
            "required_results": [*request.get("required_results", []), dependency],
            "relaxation_source": copy.deepcopy(source),
            "relaxed_structure_bridge": str(bridge_file),
        }
    )
    write_json(task_path, task)
    return task


def _saved_bridge_producer_inputs(tmp_path: Path, boundary: str) -> dict[str, object]:
    """Build producer inputs from the existing saved software bridge fixture."""

    fixture_root = tmp_path / "saved-bridge-fixture"
    fixture_root.mkdir()
    source_manifest_path, fixture = _write_relaxed_software_manifest(fixture_root, boundary)
    source_manifest = fixture["manifest"]
    artifact_dir = tmp_path / "producer-integration"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    source_method_path = Path(fixture["points"]["minus"]["source"]["method_file"])
    flat_method = json.loads(source_method_path.read_text(encoding="utf-8"))
    flat_method["stage"] = "scf"
    flat_method["method_set"] = "software-relaxed-berry-reference-v001"
    flat_method["evidence_kind"] = "software_contract_only"
    flat_method.pop("relax_method", None)
    flat_method.pop("ionic_constraints", None)
    flat_method["parameters"] = dict(flat_method["parameters"])
    flat_method["parameters"].pop("relax_nmax", None)
    flat_method["parameters"].pop("force_thr_eV_per_A", None)
    method_path = artifact_dir / "berry-reference-method.json"
    flat_method["source_path"] = str(method_path.resolve())
    write_json(method_path, flat_method)

    site_path = artifact_dir / "site.json"
    write_json(
        site_path,
        {
            "workspace": {"local": str(artifact_dir / "task-workspace")},
            "evidence_kind": "software_contract_only",
        },
    )

    response_id = f"software-relaxed-producer-{boundary}"
    request_points = []
    for point_id in ("minus", "plus"):
        source_point = source_manifest["points"][[item["point_id"] for item in source_manifest["points"]].index(point_id)]
        request_points.append(
            {
                "point_id": point_id,
                "child_model_id": source_point["child_model_id"],
                "child_model_version": source_point["child_model_version"],
                "child_study_id": source_point["child_study_id"],
                "scf_task_id": f"{response_id}-scf-{point_id}",
                "voigt_component": source_point["voigt_component"],
                "strain": source_point["strain"],
                "gdirs": [1],
                "scf_resource_request": {
                    "nodes": 1,
                    "partition": "cpu",
                    "ntasks": 1,
                    "cpus_per_task": 1,
                    "mem_mib": 2048,
                    "time": 0,
                },
                "scf_required_results": [],
                "relaxed_structure_bridge": source_point["relaxed_structure_bridge"],
            }
        )
    request_path = artifact_dir / "response-request.json"
    write_json(
        request_path,
        {
            "schema": response.RESPONSE_REQUEST_SCHEMA,
            "response_id": response_id,
            "parent_study_id": source_manifest["parent_study"]["study_id"],
            "parent_model_id": source_manifest["parent_model"]["model_id"],
            "parent_model_version": source_manifest["parent_model"]["version"],
            "charge_state": 0,
            "mechanical_boundary": boundary,
            "evidence_kind": "software_contract_only",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "points": request_points,
        },
    )

    parent_model_path = Path(source_manifest["parent_model"]["path"])
    parent_study_path = Path(source_manifest["parent_study"]["study_path"])
    output_path = artifact_dir / "response"
    snapshots = {}
    for point_id in ("minus", "plus"):
        source_point = source_manifest["points"][[item["point_id"] for item in source_manifest["points"]].index(point_id)]
        for path in (
            Path(source_point["relaxed_structure_bridge"]),
            Path(source_point["pre_relax_model"]["path"]) / "model.json",
            Path(source_point["pre_relax_study"]["study_path"]),
            Path(source_point["model_path"]) / "model.json",
            Path(source_point["study_path"]),
        ):
            snapshots[str(path.resolve())] = path.read_bytes()
    return {
        "fixture": fixture,
        "source_manifest_path": source_manifest_path,
        "parent_model_path": parent_model_path,
        "parent_study_path": parent_study_path,
        "method_path": method_path,
        "site_path": site_path,
        "request_path": request_path,
        "output_path": output_path,
        "artifact_dir": artifact_dir,
        "snapshots": snapshots,
    }


def _materialize_saved_bridge_response(tmp_path: Path, monkeypatch, boundary: str) -> dict[str, object]:
    inputs = _saved_bridge_producer_inputs(tmp_path, boundary)
    monkeypatch.setattr(response, "create_relaxed_scf", _fake_relaxed_reference_task)
    result = response.create_berry_strain_response(
        inputs["parent_study_path"],
        inputs["parent_model_path"],
        inputs["method_path"],
        inputs["site_path"],
        inputs["request_path"],
        inputs["output_path"],
    )
    inputs["result"] = result
    inputs["manifest_path"] = Path(inputs["output_path"]) / "response-manifest.json"
    inputs["manifest"] = json.loads(Path(inputs["manifest_path"]).read_text(encoding="utf-8"))
    return inputs


def _explicit_parent_study(tmp_path: Path) -> Path:
    study = json.loads(CZO_STUDY.read_text(encoding="utf-8"))
    study["model"]["path"] = str(CZO_MODEL.resolve())
    study["model"]["model_path"] = str(CZO_MODEL.resolve())
    path = tmp_path / "parent-study.json"
    write_json(path, study)
    return path


def test_materializes_explicit_voigt_points_and_preserves_fractional_lineage(tmp_path, monkeypatch):
    site_path = _site(tmp_path)
    parent_study_path = _explicit_parent_study(tmp_path)
    monkeypatch.setattr(response, "create_berry_reference_task", _fake_reference_task)
    manifest = response.create_berry_strain_response(
        parent_study_path,
        CZO_MODEL,
        tmp_path / "method.json",
        site_path,
        strain_request(tmp_path),
        tmp_path / "response",
    )

    parent = read_model_artifacts(CZO_MODEL)
    assert manifest["schema"] == response.RESPONSE_MANIFEST_SCHEMA
    assert manifest["status"] == "scf_inputs_written_not_submitted"
    assert manifest["mechanical_boundary"] == "clamped_ion_fixed_fractional"
    assert manifest["voigt_order"] == ["xx", "yy", "zz", "yz", "xz", "xy"]
    assert manifest["engineering_shear"] is True
    assert manifest["qualification"] is False
    assert len(manifest["points"]) == 2
    for point in manifest["points"]:
        child = read_model_artifacts(point["model_path"])
        child_study = json.loads(Path(point["study_path"]).read_text(encoding="utf-8"))
        assert child.atom_ids == parent.atom_ids
        assert child.atoms.get_chemical_symbols() == parent.atoms.get_chemical_symbols()
        assert child_study["model"]["path"] == str(Path(point["model_path"]).resolve())
        assert child_study["model"]["model_path"] == str(Path(point["model_path"]).resolve())
        assert np.allclose(child.atoms.get_scaled_positions(wrap=False), parent.atoms.get_scaled_positions(wrap=False))
        assert point["strain_record"]["fractional_coordinates_fixed"] is True
        assert point["strain_record"]["engineering_shear"] is True
        assert Path(point["scf_task_path"]).name == "task.json"
        task = json.loads(Path(point["scf_task_path"]).read_text(encoding="utf-8"))
        assert task["berry_strain_response"]["voigt_component"] == "yy"
        assert task["berry_strain_response"]["strain"] == point["strain"]
        request = json.loads(Path(point["scf_request_path"]).read_text(encoding="utf-8"))
        assert request["input_transformation"] is None
        assert request["resource_request"]["time"] == 0
        F = np.asarray(point["strain_record"]["F"], dtype=float)
        expected_cell = np.asarray(parent.atoms.cell.array) @ F.T
        assert np.allclose(child.atoms.cell.array, expected_cell)


@pytest.mark.parametrize(
    ("component", "minus", "plus", "message"),
    [
        ("yy", 0.01, 0.01, "central strain pair"),
        ("yy", -0.01, 0.02, "central strain pair"),
        ("xx", -0.01, 0.01, "one selected Voigt component"),
    ],
)
def test_rejects_noncentral_or_mixed_component_points(tmp_path, monkeypatch, component, minus, plus, message):
    site_path = _site(tmp_path)
    monkeypatch.setattr(response, "create_berry_reference_task", lambda **_: pytest.fail("creator must not run"))
    request_path = strain_request(tmp_path, component=component, minus=minus, plus=plus)
    if component == "xx":
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["points"][1]["voigt_component"] = "zz"
        write_json(request_path, request)
    with pytest.raises(ValueError, match=message):
        response.create_berry_strain_response(
            CZO_STUDY,
            CZO_MODEL,
            tmp_path / "method.json",
            site_path,
            request_path,
            tmp_path / "response",
        )


def test_requires_explicit_unlimited_dft_resources(tmp_path, monkeypatch):
    site_path = _site(tmp_path)
    monkeypatch.setattr(response, "create_berry_reference_task", lambda **_: pytest.fail("creator must not run"))
    request_path = strain_request(tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["points"][0]["scf_resource_request"]["time"] = "00:10:00"
    write_json(request_path, request)
    with pytest.raises(ValueError, match=r"time must be explicitly 0"):
        response.create_berry_strain_response(
            CZO_STUDY,
            CZO_MODEL,
            tmp_path / "method.json",
            site_path,
            request_path,
            tmp_path / "response",
        )


def _unrun_manifest(tmp_path: Path) -> tuple[Path, Path, Path]:
    site_path = _site(tmp_path)
    method_path = tmp_path / "method.json"
    method_path.write_text("{}\n", encoding="utf-8")
    scf_dir = tmp_path / "scf"
    scf_dir.mkdir()
    model_path = tmp_path / "model"
    study_path = tmp_path / "study.json"
    write_json(
        scf_dir / "task.json",
        {
            "task_id": "scf-minus",
            "study_id": "child-study",
            "model_id": "child-model",
            "model_version": "v001",
            "model_path": str(model_path.resolve()),
            "study_file": str(study_path.resolve()),
            "scheduler_state": "RUNNING",
            "status": "RUNNING",
            "scheduler_job_id": "501",
            "exit_code": None,
            "result_file": "result.json",
        },
    )
    manifest_path = tmp_path / "response-manifest.json"
    write_json(
        manifest_path,
        {
            "schema": response.RESPONSE_MANIFEST_SCHEMA,
            "response_id": "response",
            "method_path": str(method_path.resolve()),
            "site_path": str(site_path.resolve()),
            "mechanical_boundary": "clamped_ion_fixed_fractional",
            "parent_study": {"study_id": "parent"},
            "parent_model": {"model_id": "parent-model", "version": "v001", "path": str(model_path)},
            "points": [
                {
                    "point_id": "minus",
                    "child_study_id": "child-study",
                    "child_model_id": "child-model",
                    "child_model_version": "v001",
                    "scf_task_id": "scf-minus",
                    "scf_task_path": str(scf_dir / "task.json"),
                    "model_path": str(model_path),
                    "study_path": str(study_path),
                    "voigt_component": "yy",
                    "strain": -0.01,
                    "strain_voigt": [0, -0.01, 0, 0, 0, 0],
                    "gdirs": [1],
                    "nscf_tasks": [],
                }
            ],
        },
    )
    request_path = tmp_path / "nscf-request.json"
    write_json(
        request_path,
        {
            "calculation": "nscf",
            "input_transformation": None,
            "task_id": "nscf-minus-gdir1",
            "berry": {"role": "nscf", "gdir": 1},
            "resource_request": {"nodes": 1, "ntasks": 1, "time": 0},
        },
    )
    return manifest_path, method_path, request_path


def _completed_manifest(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path, Path]:
    site_path = _site(tmp_path)
    parent_study_path = _explicit_parent_study(tmp_path)
    monkeypatch.setattr(response, "create_berry_reference_task", _fake_reference_task)
    manifest = response.create_berry_strain_response(
        parent_study_path,
        CZO_MODEL,
        tmp_path / "method.json",
        site_path,
        strain_request(tmp_path),
        tmp_path / "response",
    )
    manifest_path = tmp_path / "response" / "response-manifest.json"
    for point in manifest["points"]:
        task_path = Path(point["scf_task_path"])
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task.update({"scheduler_state": "COMPLETED", "status": "COMPLETED", "scheduler_job_id": "601", "exit_code": "0:0"})
        task["result_file"] = "result.json"
        write_json(
            task_path.parent / "result.json",
            {
                "task_id": task["task_id"],
                "scheduler_job_id": "601",
                "scientific_status": "converged_engineering_fixture",
                "electronic_converged": True,
            },
        )
        write_json(task_path, task)
    return manifest_path, site_path, tmp_path / "method.json", tmp_path / "response"


def _fake_nscf_task(*, reference_task_path, method_path, site_path, request_path):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    reference = json.loads(Path(reference_task_path).read_text(encoding="utf-8"))
    site = json.loads(Path(site_path).read_text(encoding="utf-8"))
    task_dir = Path(site["workspace"]["local"]) / "tasks" / request["task_id"]
    task_dir.mkdir(parents=True)
    task = {
        "task_id": request["task_id"],
        "study_id": reference["study_id"],
        "model_id": reference["model_id"],
        "model_version": reference["model_version"],
        "model_path": reference["model_path"],
        "study_file": reference["study_file"],
        "resource_request": request["resource_request"],
        "scheduler_state": "DEFINED",
        "status": "defined",
        "scheduler_job_id": None,
        "exit_code": None,
    }
    write_json(task_dir / "task.json", task)
    return task


def test_nscf_accepts_matching_saved_binding_and_records_task(tmp_path, monkeypatch):
    manifest_path, site_path, method_path, _ = _completed_manifest(tmp_path, monkeypatch)
    monkeypatch.setattr(response, "create_berry_nscf_task", _fake_nscf_task)
    request_path = tmp_path / "nscf-request.json"
    write_json(
        request_path,
        {
            "calculation": "nscf",
            "input_transformation": None,
            "task_id": "nscf-minus-gdir1",
            "berry": {"role": "nscf", "gdir": 1},
            "resource_request": {"nodes": 1, "ntasks": 1, "time": 0},
        },
    )
    result = response.create_berry_strain_nscf(manifest_path, "minus", site_path, method_path, request_path)
    assert result["status"] == "nscf_inputs_written_not_submitted"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["points"][0]["nscf_tasks"][0]["gdir"] == 1
    assert manifest["points"][0]["nscf_tasks"][0]["request_path"].endswith("nscf-minus-gdir1.request.json")


def test_nscf_rejects_saved_binding_strain_mismatch(tmp_path, monkeypatch):
    manifest_path, site_path, method_path, _ = _completed_manifest(tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    task_path = Path(manifest["points"][0]["scf_task_path"])
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["berry_strain_response"]["strain"] = -0.02
    write_json(task_path, task)
    request_path = tmp_path / "nscf-request.json"
    write_json(
        request_path,
        {
            "calculation": "nscf",
            "input_transformation": None,
            "task_id": "nscf-minus-gdir1",
            "berry": {"role": "nscf", "gdir": 1},
            "resource_request": {"nodes": 1, "ntasks": 1, "time": 0},
        },
    )
    monkeypatch.setattr(response, "create_berry_nscf_task", lambda **_: pytest.fail("native creator must not run"))
    with pytest.raises(ValueError, match=r"binding strain differs"):
        response.create_berry_strain_nscf(manifest_path, "minus", site_path, method_path, request_path)


def test_nscf_rejects_saved_declared_strain_record_mismatch(tmp_path, monkeypatch):
    manifest_path, site_path, method_path, _ = _completed_manifest(tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    point = manifest["points"][0]
    point["strain_record"]["F"][0][0] += 0.001
    write_json(manifest_path, manifest)
    request_path = tmp_path / "nscf-request.json"
    write_json(
        request_path,
        {
            "calculation": "nscf",
            "input_transformation": None,
            "task_id": "nscf-minus-gdir1",
            "berry": {"role": "nscf", "gdir": 1},
            "resource_request": {"nodes": 1, "ntasks": 1, "time": 0},
        },
    )
    monkeypatch.setattr(response, "create_berry_nscf_task", lambda **_: pytest.fail("native creator must not run"))
    with pytest.raises(ValueError, match=r"strain_record field F differs"):
        response.create_berry_strain_nscf(manifest_path, "minus", site_path, method_path, request_path)


def test_nscf_rejects_unrun_reference_before_native_creator(tmp_path, monkeypatch):
    manifest_path, method_path, request_path = _unrun_manifest(tmp_path)
    monkeypatch.setattr(response, "create_berry_nscf_task", lambda **_: pytest.fail("NSCF creator must not run"))
    with pytest.raises(ValueError, match=r"COMPLETED/0:0"):
        response.create_berry_strain_nscf(
            manifest_path,
            "minus",
            tmp_path / "site.json",
            method_path,
            request_path,
        )


def test_relaxed_point_records_require_absolute_saved_bridge_paths(tmp_path):
    request_path = strain_request(tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["mechanical_boundary"] = "constrained_ion_fixed_cell"
    for point in request["points"]:
        point["relaxed_structure_bridge"] = str((tmp_path / (point["point_id"] + "-bridge.json")).resolve())
    records = response._point_records(
        request,
        type("Parent", (), {"atom_ids": [1]})(),
        {"study_id": "parent-study"},
        mechanical_boundary="constrained_ion_fixed_cell",
    )
    assert [item["relaxed_structure_bridge"] for item in records] == [
        str((tmp_path / "minus-bridge.json").resolve()),
        str((tmp_path / "plus-bridge.json").resolve()),
    ]
    request["points"][0]["relaxed_structure_bridge"] = "relative/bridge.json"
    with pytest.raises(ValueError, match=r"absolute path"):
        response._point_records(
            request,
            type("Parent", (), {"atom_ids": [1]})(),
            {"study_id": "parent-study"},
            mechanical_boundary="constrained_ion_fixed_cell",
        )


def test_relaxed_method_pair_signature_keeps_kpoints_but_ignores_stage_output_controls():
    first = {
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "basis_type": "pw",
        "stage": "relax",
        "kpoints": [2, 2, 2],
        "parameters": {"ecutwfc_Ry": 100, "relax_nmax": 10},
        "output": {"suffix": "relax"},
    }
    second = json.loads(json.dumps(first))
    second["stage"] = "scf"
    second["output"] = {"suffix": "berry-reference"}
    assert response._method_relaxed_signature(first) == response._method_relaxed_signature(second)
    second["kpoints"] = [3, 3, 3]
    assert response._method_relaxed_signature(first) != response._method_relaxed_signature(second)


def test_method_physical_signature_normalizes_config_and_native_records():
    config = {
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "basis_type": "pw",
        "science": {
            "dft_functional": "PBE",
            "nspin": 1,
            "lspinorb": False,
            "noncolin": False,
            "occupations": "fixed",
            "smearing_method": "fixed",
            "smearing_sigma_Ry": 0.0,
            "mixing_type": "plain",
            "mixing_beta": 0.7,
            "symmetry": 1,
            "net_charge": 0,
            "element_order": ["Ni"],
            "pseudopotential_ids": {"Ni": "Ni.upf"},
            "pseudopotential_metadata": {"Ni": {"filename": "Ni.upf"}},
            "pseudopotential_treatment": {"Ni": "scalar"},
        },
        "execution": {"ks_solver": "cg"},
        "parameters": {
            "ecutwfc_Ry": 100,
            "nbands": 4,
            "scf_thr": 1.0e-4,
            "scf_nmax": 100,
            "kpoints": [2, 2, 2],
        },
    }
    native = {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "basis_type": "pw",
        "dft_functional": "PBE",
        "ks_solver": "cg",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "smearing_method": "fixed",
        "smearing_sigma_Ry": 0.0,
        "mixing_type": "plain",
        "mixing_beta": 0.7,
        "symmetry": 1,
        "net_charge": 0,
        "element_order": ["Ni"],
        "pseudopotential_ids": {"Ni": "Ni.upf"},
        "pseudopotential_metadata": {"Ni": {"filename": "Ni.upf"}},
        "pseudopotential_treatment": {"Ni": "scalar"},
        "ecutwfc_Ry": 100,
        "nbands": 4,
        "scf_thr": 1.0e-4,
        "scf_nmax": 100,
        "kpoints": [2, 2, 2],
        "kpoint_rule": "explicit_mesh",
    }
    assert response._method_physical_signature(config) == response._method_physical_signature(native)


def test_relaxed_constraint_pair_signature_ignores_provenance_origin():
    first = {
        "schema": "mlcc.ionic-constraints.v1",
        "coordinate_basis": "cartesian",
        "atom_ids": [1, 2],
        "move_flags": [[1, 1, 1], [0, 1, 0]],
        "relax_new": True,
        "origin": "saved-minus",
    }
    second = dict(first, origin="saved-plus")
    assert response._constraints_pair_signature(first) == response._constraints_pair_signature(second)


@pytest.mark.parametrize(
    ("boundary", "scope"),
    [
        ("relaxed_ion_fixed_cell", "all_internal_dofs"),
        ("constrained_ion_fixed_cell", "selected_internal_dofs"),
    ],
)
def test_saved_bridge_producer_materializes_both_relaxed_boundaries_without_rewriting_sources(
    tmp_path, monkeypatch, boundary, scope,
):
    inputs = _materialize_saved_bridge_response(tmp_path, monkeypatch, boundary)
    manifest = inputs["manifest"]
    fixture = inputs["fixture"]

    assert manifest["schema"] == response.RESPONSE_MANIFEST_SCHEMA
    assert manifest["response_id"] == f"software-relaxed-producer-{boundary}"
    assert manifest["mechanical_boundary"] == boundary
    assert manifest["relaxation_scope"] == scope
    assert manifest["evidence_kind"] == "software_contract_only"
    assert manifest["scientific_qualification"] is False
    assert manifest["production_qualified"] is False
    assert manifest["status"] == "scf_inputs_written_not_submitted"
    assert Path(manifest["method_path"]).resolve() == Path(inputs["method_path"]).resolve()
    assert Path(manifest["site_path"]).resolve() == Path(inputs["site_path"]).resolve()

    fixture_points = {item["point_id"]: item for item in fixture["manifest"]["points"]}
    for point in manifest["points"]:
        source_point = fixture_points[point["point_id"]]
        task_path = Path(point["scf_task_path"])
        task = json.loads(task_path.read_text(encoding="utf-8"))
        binding = task["berry_strain_response"]
        bridge = json.loads(Path(point["relaxed_structure_bridge"]).read_text(encoding="utf-8"))

        assert point["relaxation_scope"] == scope
        assert point["model_path"] == bridge["child_model"]["path"]
        assert point["study_path"] == bridge["child_study"]["study_path"]
        assert point["pre_relax_model"]["path"] == bridge["parent_model"]["path"]
        assert point["pre_relax_study"]["study_path"] == bridge["parent_study"]["study_path"]
        assert point["relaxation_source"] == bridge["relaxation_source"]
        assert point["relaxed_structure_bridge"] == str(Path(source_point["relaxed_structure_bridge"]).resolve())
        assert point["relaxation_source"]["task_file"] != point["scf_task_path"]
        assert task["task_id"] == point["scf_task_id"]
        assert task["model_path"] == point["model_path"]
        assert task["study_file"] == point["study_path"]
        assert task["fixture_purpose"] == "software_contract_only"
        assert task["evidence_kind"] == "software_contract_only"
        assert task["relaxed_structure_bridge"] == point["relaxed_structure_bridge"]
        assert task["relaxation_source"] == point["relaxation_source"]
        assert task["required_results"][0]["task_id"] == point["relaxation_source"]["task_id"]
        assert binding["response_id"] == manifest["response_id"]
        assert binding["point_id"] == point["point_id"]
        assert binding["task_id"] == task["task_id"]
        assert binding["relaxed_structure_bridge"] == point["relaxed_structure_bridge"]
        assert binding["relaxation_source"] == point["relaxation_source"]
        assert binding["pre_relax_model"] == point["pre_relax_model"]
        assert binding["pre_relax_study"] == point["pre_relax_study"]

    for path_text, before in inputs["snapshots"].items():
        assert Path(path_text).read_bytes() == before

    if boundary == "constrained_ion_fixed_cell":
        integration_paths = {
            "schema": "mlcc.berry-strain-response-producer-integration.v1",
            "evidence_kind": "software_contract_only",
            "manifest_path": str(Path(inputs["manifest_path"]).resolve()),
            "request_path": str(Path(inputs["request_path"]).resolve()),
            "site_path": str(Path(inputs["site_path"]).resolve()),
            "method_path": str(Path(inputs["method_path"]).resolve()),
        }
        write_json(Path(inputs["artifact_dir"]) / "producer-integration-paths.json", integration_paths)
        assert Path(integration_paths["manifest_path"]).is_file()
        assert Path(integration_paths["request_path"]).is_file()
        assert Path(integration_paths["site_path"]).is_file()
        assert Path(integration_paths["method_path"]).is_file()


@pytest.mark.parametrize("mutation", ["kpoints", "pseudopotential"])
def test_saved_bridge_producer_rejects_new_scf_method_physical_mismatch(tmp_path, monkeypatch, mutation):
    inputs = _saved_bridge_producer_inputs(tmp_path, "constrained_ion_fixed_cell")
    method = json.loads(Path(inputs["method_path"]).read_text(encoding="utf-8"))
    if mutation == "kpoints":
        method["kpoints"] = [3, 2, 2]
    elif mutation == "pseudopotential":
        method["pseudopotential_ids"] = {"Ni": "different.upf"}
    else:
        raise AssertionError(mutation)
    write_json(Path(inputs["method_path"]), method)
    monkeypatch.setattr(response, "create_relaxed_scf", lambda **_: pytest.fail("relaxed SCF creator must not run"))

    with pytest.raises(ValueError, match="Berry reference method differs"):
        response.create_berry_strain_response(
            inputs["parent_study_path"],
            inputs["parent_model_path"],
            inputs["method_path"],
            inputs["site_path"],
            inputs["request_path"],
            inputs["output_path"],
        )
    assert not Path(inputs["output_path"]).exists()


def test_saved_bridge_nscf_preflight_rejects_changed_relaxed_binding(tmp_path, monkeypatch):
    inputs = _materialize_saved_bridge_response(tmp_path, monkeypatch, "constrained_ion_fixed_cell")
    manifest = inputs["manifest"]
    point = manifest["points"][0]
    other_point = manifest["points"][1]
    task_path = Path(point["scf_task_path"])
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task.update(
        {
            "scheduler_state": "COMPLETED",
            "status": "COMPLETED",
            "scheduler_job_id": "software-reference-job-minus",
            "exit_code": "0:0",
            "result_file": str((task_path.parent / "result.json").resolve()),
        }
    )
    task["berry_strain_response"]["relaxed_structure_bridge"] = other_point["relaxed_structure_bridge"]
    write_json(task_path, task)
    write_json(
        task_path.parent / "result.json",
        {
            "schema": "mlcc.abacus-result.v1",
            "task_id": task["task_id"],
            "scheduler_job_id": task["scheduler_job_id"],
            "scientific_status": "converged_engineering_fixture",
            "electronic_converged": True,
            "evidence_kind": "software_contract_only",
        },
    )
    request_path = Path(inputs["artifact_dir"]) / "nscf-request.json"
    write_json(
        request_path,
        {
            "calculation": "nscf",
            "input_transformation": None,
            "task_id": "software-relaxed-producer-nscf-minus-gdir1",
            "berry": {"role": "nscf", "gdir": 1},
            "resource_request": {"nodes": 1, "ntasks": 1, "time": 0},
        },
    )
    monkeypatch.setattr(response, "create_berry_nscf_task", lambda **_: pytest.fail("NSCF creator must not run"))

    with pytest.raises(ValueError, match="relaxed binding field relaxed_structure_bridge"):
        response.create_berry_strain_nscf(
            inputs["manifest_path"],
            "minus",
            inputs["site_path"],
            inputs["method_path"],
            request_path,
        )


def test_saved_bridge_pair_ignores_origin_in_both_control_comparisons(tmp_path):
    inputs = _saved_bridge_producer_inputs(tmp_path, "constrained_ion_fixed_cell")
    manifest = inputs["fixture"]["manifest"]
    info = {point["point_id"]: response._validate_relaxed_point(manifest, point)
            for point in manifest["points"]}
    # Each saved source was checked above. Pair comparison concerns physical
    # selections; the provenance origin may differ without changing the mask.
    info["plus"]["ionic_constraints"]["origin"] = "other_recorded_origin"
    info["plus"]["relaxation_source"]["relaxation"]["ionic_constraints"]["origin"] = "other_recorded_origin"
    response._validate_relaxed_pair(manifest["points"], info,
                                    berry_method_path=inputs["method_path"])

