from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import phonopy
import pytest
from ase import Atoms
from ase.io import read as ase_read

from mlcc.modeling import read_model_artifacts, write_model_artifacts
from mlcc.phonon_forces import _child_lineage_issues, _identity_mismatches, _phonon_entry_identity
from mlcc.phonon_tasks import create_phonon_task
from mlcc.phonons import generate_phonon_displacement_plan


ROOT = Path(__file__).resolve().parents[2]
METHOD = ROOT / "workspace" / "configs" / "h1-abacus-method-v003.json"
SITE_TEMPLATE = ROOT / "workspace" / "configs" / "site.v100.json"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parent(tmp_path: Path) -> Path:
    atoms = Atoms(
        symbols=["Ni", "Ni"],
        scaled_positions=[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        cell=np.eye(3) * 3.5,
        pbc=True,
    )
    atoms.set_masses([58.6934, 58.6934])
    atoms.new_array("initial_magmoms", np.asarray([0.6, 0.6]))
    atoms.new_array("atom_id", np.asarray([0, 1], dtype=np.int64))
    parent_path = tmp_path / "parent"
    write_model_artifacts(
        atoms,
        parent_path,
        model_id="ni-phonon-parent",
        version="v001",
        fixture=True,
        fixture_purpose="phonon-task-test",
        phase_requested="fcc_test",
        source_path="test-source",
        source_version="test-v001",
        material="Ni",
    )
    model = json.loads((parent_path / "model.json").read_text(encoding="utf-8"))
    model["dopants"] = [{"element": "Ni", "site": "fixture-site", "atom_id": 1, "fraction": 0.25}]
    (parent_path / "model.json").write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    dopants = json.loads((parent_path / "dopants.json").read_text(encoding="utf-8"))
    dopants["dopants"] = model["dopants"]
    (parent_path / "dopants.json").write_text(json.dumps(dopants, indent=2) + "\n", encoding="utf-8")
    return parent_path


def _study(parent: Path, path: Path, *, phase: str = "fcc_test") -> Path:
    value = {
        "study_id": "ni-phonon-parent-study",
        "case_id": "ni_phonon_case",
        "case_role": "engineering_fixture",
        "selected_purposes": ["normal"],
        "selected_scenarios": ["diagnostic"],
        "selected_required_tasks": ["parent-task"],
        "design_requirements_ref": None,
        "model": {
            "material": "Ni",
            "phase_requested": phase,
            "model_id": "ni-phonon-parent",
            "version": "v001",
            "dopants": [{"element": "Ni", "site": "fixture-site", "atom_id": 1, "fraction": 0.25}],
            "temperature_K": [400.0, 500.0],
            "temperature_range_C": [126.85, 226.85],
        },
        "scope": "phonon task contract test",
    }
    _write_json(path, value)
    return path


def _plan(parent: Path, path: Path) -> Path:
    generate_phonon_displacement_plan(
        parent,
        {
            "plan_id": "ni-phonon-plan",
            "version": "v001",
            "phonopy_version": str(phonopy.__version__),
            "repeat_matrix": [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
            "primitive_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "distance_angstrom": 0.01,
            "symprec": 1e-5,
            "is_symmetry": False,
            "hermitianize_dynamical_matrix": True,
        },
        path,
    )
    return path / "displacement-manifest.json"


def _site(tmp_path: Path) -> Path:
    site = json.loads(SITE_TEMPLATE.read_text(encoding="utf-8"))
    workspace = tmp_path / "site-workspace"
    (workspace / "tasks").mkdir(parents=True)
    site["workspace"]["local"] = str(workspace)
    path = tmp_path / "site.json"
    _write_json(path, site)
    return path


def _request(manifest_path: Path, output: Path, *, displacement_id: str | None = None) -> tuple[Path, dict, Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = displacement_id or manifest["displacements"][0]["entry_id"]
    request = {
        "displacement_id": selected,
        "child_model_id": "ni-phonon-child",
        "child_model_version": "v001",
        "child_study_id": "ni-phonon-child-study",
        "task_id": "ni-phonon-task-001",
        "resource_request": {
            "nodes": 1,
            "partition": "gpu",
            "ntasks": 1,
            "cpus_per_task": 1,
            "gpus_per_task": "v100:1",
            "hint": "nomultithread",
            "mem_mib": 8192,
            "time": "00:20:00",
        },
        "required_results": [],
    }
    path = output / "request.json"
    _write_json(path, request)
    return path, request, output


def _case(tmp_path: Path) -> tuple[dict[str, Path], dict]:
    parent = _parent(tmp_path)
    parent_study = _study(parent, tmp_path / "parent-study.json")
    manifest = _plan(parent, tmp_path / "plan")
    site = _site(tmp_path)
    request_path, request, output_root = _request(manifest, tmp_path / "request-root")
    return {
        "parent": parent,
        "study": parent_study,
        "manifest": manifest,
        "site": site,
        "request": request_path,
        "method": METHOD,
        "output": tmp_path / "task-output",
    }, request


def test_create_phonon_task_binds_exact_child_geometry_and_preserves_parent_context(tmp_path: Path):
    paths, request = _case(tmp_path)
    parent_study = json.loads(paths["study"].read_text(encoding="utf-8"))
    parent_study["parent_study_id"] = "earlier-study-in-model-lineage"
    _write_json(paths["study"], parent_study)
    data = create_phonon_task(
        plan_path=paths["manifest"],
        study_path=paths["study"],
        method_path=paths["method"],
        site_path=paths["site"],
        request_path=paths["request"],
        output_path=paths["output"],
    )

    assert data["stage"] == "P7"
    assert data["calculation"] == "scf"
    assert data["status"] == "defined"
    assert data["scheduler_job_id"] is None
    assert data["input_transformation"] is None
    assert data["calculation_conditions"]["reference_temperature_K"] == 0
    assert data["calculation_conditions"]["lattice_temperature_K"] is None
    assert data["phonon_displacement"]["displacement_id"] == request["displacement_id"]

    child = read_model_artifacts(data["child_model_path"])
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    selected = next(entry for entry in manifest["displacements"] if entry["entry_id"] == request["displacement_id"])
    planned = ase_read(str(paths["manifest"].parent / selected["structure_file"]), format="extxyz", index=0)
    assert child.atom_ids == selected["atom_ids"]
    assert np.allclose(child.atoms.positions, planned.positions, rtol=0.0, atol=1e-8)
    assert np.allclose(child.atoms.cell.array, planned.cell.array, rtol=0.0, atol=1e-8)
    assert child.atoms.get_masses().tolist() == pytest.approx(planned.get_masses().tolist())
    assert child.atoms.arrays["initial_magmoms"].tolist() == pytest.approx(planned.arrays["initial_magmoms"].tolist())
    assert child.metadata["parent_model"]["model_id"] == "ni-phonon-parent"
    assert child.metadata["parent_model"]["version"] == "v001"
    assert child.metadata["source_structure_role"] == "generated_child_reference"
    assert child.metadata["spatial_mode"] == "phonon_displacement_child"
    assert child.metadata["phonon_displacement"]["parent_study_file"] == str(paths["study"].resolve())
    assert child.metadata["relaxation_status"] == "not_run"
    assert child.metadata["production_qualified"] is False
    expected_dopants = [{"element": "Ni", "site": "fixture-site", "atom_id": 1, "fraction": 0.25}]
    assert child.metadata["dopants"] == expected_dopants
    assert child.metadata["parent_dopant_selection"] == expected_dopants
    assert child.metadata["dopants_source_role"] == "parent_dopant_selection"
    assert child.metadata["source_cif_role"] == "generated_child_reference"
    assert child.metadata["parent_source_ref"]["parent_artifact_dir"] == str(paths["parent"].resolve())
    assert child.metadata["source_original_file"] is None
    selected_target = selected["displaced_atom_id"]
    selected_vector = selected["displacement_angstrom"]
    lineage = json.loads((Path(data["child_model_path"]) / "atom-lineage.json").read_text(encoding="utf-8"))
    target_lineage = next(item for item in lineage["entries"] if item["child_atom_id"] == selected_target)
    assert target_lineage["phonon_displacement"]["applied_vector_angstrom"] == pytest.approx(selected_vector)
    dopant_map = child.metadata["dopant_lineage_mapping"][0]
    assert dopant_map["source_role"] == "parent_dopant_selection"
    assert dopant_map["parent_atom_ids"] == [1]
    assert dopant_map["child_atom_ids"] == [
        item["child_atom_id"]
        for item in lineage["entries"]
        if item["parent_atom_id"] == 1
    ]
    assert dopant_map["child_atom_ids"] != [1]

    child_study = json.loads(Path(data["child_study_path"]).read_text(encoding="utf-8"))
    assert child_study["study_id"] == request["child_study_id"]
    assert child_study["parent_study_id"] == "ni-phonon-parent-study"
    assert child_study["selected_required_tasks"] == [request["task_id"]]
    assert child_study["model"]["model_id"] == request["child_model_id"]
    assert child_study["model"]["temperature_K"] == [400.0, 500.0]
    assert child_study["model"]["dopants"] == expected_dopants

    abacus_request = json.loads(Path(data["abacus_request_path"]).read_text(encoding="utf-8"))
    assert abacus_request["calculation"] == "scf"
    assert abacus_request["input_transformation"] is None
    assert abacus_request["resource_request"] == request["resource_request"]
    assert json.loads(Path(data["task_path"]).read_text(encoding="utf-8"))["stage"] == "P7"


def test_create_reference_and_displacement_have_collector_identity_and_lineage_contract(tmp_path: Path):
    paths, _ = _case(tmp_path)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    parent_study = json.loads(paths["study"].read_text(encoding="utf-8"))
    parent_model = manifest["source_model"]
    records = []
    for index, entry in enumerate((manifest["reference"], manifest["displacements"][0])):
        request_path, request, _ = _request(
            paths["manifest"],
            tmp_path / f"request-{index}",
            displacement_id=entry["entry_id"],
        )
        request.update(
            {
                "child_model_id": f"ni-phonon-child-{index}",
                "child_study_id": f"ni-phonon-child-study-{index}",
                "task_id": f"ni-phonon-task-{index}",
            }
        )
        _write_json(request_path, request)
        records.append(
            (
                entry,
                create_phonon_task(
                    plan_path=paths["manifest"],
                    study_path=paths["study"],
                    method_path=paths["method"],
                    site_path=paths["site"],
                    request_path=request_path,
                    output_path=tmp_path / f"child-{index}",
                ),
            )
        )

    for entry, data in records:
        task = json.loads(Path(data["task_path"]).read_text(encoding="utf-8"))
        identity = task["phonon_displacement"]
        expected = _phonon_entry_identity(
            entry,
            plan_id=manifest["plan_id"],
            plan_version=manifest["version"],
            manifest_path=paths["manifest"].resolve(),
            parent_model=parent_model,
            parent_study_id=parent_study["study_id"],
            parent_study_file=paths["study"].resolve(),
        )
        assert _identity_mismatches(expected, identity, base_path=Path(data["task_path"]).parent) == []
        child = read_model_artifacts(data["child_model_path"])
        assert _identity_mismatches(expected, child.metadata["phonon_displacement"], base_path=child.artifact_dir) == []
        assert _identity_mismatches(expected, child.metadata["derivation"], base_path=child.artifact_dir) == []
        child_study = json.loads(Path(data["child_study_path"]).read_text(encoding="utf-8"))
        assert _identity_mismatches(expected, child_study["phonon_displacement"], base_path=Path(data["child_study_path"]).parent) == []
        assert _child_lineage_issues(
            data["child_model_path"],
            child.metadata,
            entry,
            expected,
            parent_model,
        ) == []
        if entry["entry_id"] == "reference":
            assert identity["displacement_unit"] is None
            assert identity["displacement_angstrom"] is None
            assert identity["displaced_atom_id"] is None
            assert identity["phonopy_atom_index"] is None
            assert identity["sign"] is None
        else:
            assert identity["displacement_unit"] == "angstrom"
            assert identity["displacement_angstrom"] == entry["displacement_angstrom"]
        lineage = json.loads((Path(data["child_model_path"]) / "atom-lineage.json").read_text(encoding="utf-8"))
        units = {item["phonon_displacement"]["displacement_unit"] for item in lineage["entries"]}
        assert units == {None if entry["entry_id"] == "reference" else "angstrom"}


def test_phonon_task_rejects_tampered_plan_geometry_and_wrong_displacement(tmp_path: Path):
    paths, request = _case(tmp_path)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    selected = manifest["displacements"][0]
    structure_path = paths["manifest"].parent / selected["structure_file"]
    atoms = ase_read(str(structure_path), format="extxyz", index=0)
    atoms.positions[0, 0] += 0.123
    from ase.io import write as ase_write

    ase_write(str(structure_path), atoms, format="extxyz")
    with pytest.raises(ValueError, match="positions differ|differs from Phonopy"):
        create_phonon_task(
            plan_path=paths["manifest"], study_path=paths["study"], method_path=paths["method"],
            site_path=paths["site"], request_path=paths["request"], output_path=paths["output"],
        )
    assert not paths["output"].exists()

    paths2, _ = _case(tmp_path / "wrong")
    wrong_request_path, _, _ = _request(paths2["manifest"], tmp_path / "wrong-request", displacement_id="does-not-exist")
    with pytest.raises(ValueError, match="not present"):
        create_phonon_task(
            plan_path=paths2["manifest"], study_path=paths2["study"], method_path=paths2["method"],
            site_path=paths2["site"], request_path=wrong_request_path, output_path=paths2["output"],
        )
    assert not paths2["output"].exists()


def test_phonon_task_rejects_parent_phase_mismatch_duplicate_output_and_same_identity(tmp_path: Path):
    paths, request = _case(tmp_path)
    bad_study = json.loads(paths["study"].read_text(encoding="utf-8"))
    bad_study["model"]["phase_requested"] = "wrong_phase"
    bad_study_path = tmp_path / "bad-study.json"
    _write_json(bad_study_path, bad_study)
    with pytest.raises(ValueError, match="phase_requested"):
        create_phonon_task(
            plan_path=paths["manifest"], study_path=bad_study_path, method_path=paths["method"],
            site_path=paths["site"], request_path=paths["request"], output_path=paths["output"],
        )
    assert not paths["output"].exists()

    data = create_phonon_task(
        plan_path=paths["manifest"], study_path=paths["study"], method_path=paths["method"],
        site_path=paths["site"], request_path=paths["request"], output_path=paths["output"],
    )
    with pytest.raises(FileExistsError, match="output directory already exists"):
        create_phonon_task(
            plan_path=paths["manifest"], study_path=paths["study"], method_path=paths["method"],
            site_path=paths["site"], request_path=paths["request"], output_path=paths["output"],
        )
    assert Path(data["child_model_path"]).is_dir()

    same_request = dict(request)
    same_request["child_model_id"] = "ni-phonon-parent"
    same_request["child_model_version"] = "v001"
    same_request_path = tmp_path / "same-request.json"
    _write_json(same_request_path, same_request)
    with pytest.raises(ValueError, match="new model_id and version"):
        create_phonon_task(
            plan_path=paths["manifest"], study_path=paths["study"], method_path=paths["method"],
            site_path=paths["site"], request_path=same_request_path, output_path=tmp_path / "same-output",
        )
