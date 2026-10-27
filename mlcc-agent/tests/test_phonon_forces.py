from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import numpy as np
import pytest
from ase import Atoms

import mlcc.phonon_forces as phonon_forces
from mlcc.phonon_forces import (
    _force_drift,
    _identity_mismatches,
    _native_lcao_contract,
    _native_stru_contract,
    _phonon_entry_identity,
    collect_phonon_forces,
    load_native_force_task,
)
from mlcc.phonons import generate_phonon_displacement_plan


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JOB40 = PROJECT_ROOT / "workspace" / "tasks" / "p4-czo-compatibility-scf-v001"
CZO_MODEL = PROJECT_ROOT / "workspace" / "models" / "cazro3-pnma-pristine" / "v001"


def _thresholds() -> dict[str, float]:
    return {
        "force_match_tolerance_eV_per_A": 1.0e-10,
        "reference_force_tolerance_eV_per_A": 1.0e-3,
        "force_drift_tolerance_eV_per_A": 1.0e-3,
        "geometry_tolerance_A": 1.0e-8,
        "displacement_tolerance_A": 1.0e-8,
    }


def _plan(path: Path) -> Path:
    output = path.parent / "phonon-plan"
    generate_phonon_displacement_plan(
        CZO_MODEL,
        {
            "plan_id": "czo-p7-force-plan",
            "version": "v001",
            "phonopy_version": "4.8.3",
            "repeat_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "primitive_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "distance_angstrom": 0.01,
            "symprec": 1.0e-5,
            "is_symmetry": False,
            "hermitianize_dynamical_matrix": True,
        },
        output,
    )
    return output / "displacement-manifest.json"


def _minimal_collection_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_specs: Sequence[str],
) -> dict[str, Any]:
    """Exercise collection provenance with software-only loaded TaskRecords.

    The collector is real; only native parsing, geometry and lineage reads are
    stubbed.  Every known record is explicitly an engineering fixture, so this
    helper cannot be mistaken for a native force or Gamma result.
    """

    root = tmp_path / "phonon-source-fixture"
    root.mkdir()
    manifest_path = (root / "displacement-manifest.json").resolve()
    parent_path = (root / "parent-model").resolve()
    parent_path.mkdir()
    parent_model = SimpleNamespace(
        model_id="phonon-parent",
        version="v001",
        metadata={"fixture": True},
        artifact_dir=parent_path,
    )
    entries = [
        {"entry_id": "reference", "kind": "reference", "atom_ids": [7]},
        {
            "entry_id": "u-plus",
            "kind": "displacement",
            "displaced_atom_id": 7,
            "phonopy_atom_index": 0,
            "displacement_angstrom": [0.01, 0.0, 0.0],
            "sign": "+",
            "atom_ids": [7],
        },
        {
            "entry_id": "u-minus",
            "kind": "displacement",
            "displaced_atom_id": 7,
            "phonopy_atom_index": 0,
            "displacement_angstrom": [-0.01, 0.0, 0.0],
            "sign": "-",
            "atom_ids": [7],
        },
    ]
    manifest = {
        "schema": "mlcc.phonon-displacement-plan.v1",
        "plan_id": "software-contract-plan",
        "version": "v001",
        "source_model": {
            "model_id": parent_model.model_id,
            "version": parent_model.version,
            "path": str(parent_path),
        },
        "reference": entries[0],
        "displacements": entries[1:],
    }
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    atoms_by_id: dict[str, Atoms] = {}
    for entry in entries:
        atoms = Atoms(symbols=["He"], positions=[[0.0, 0.0, 0.0]], cell=np.eye(3) * 3.0, pbc=True)
        atoms.new_array("atom_id", np.asarray([7], dtype=np.int64))
        atoms_by_id[str(entry["entry_id"])] = atoms

    def task_identity(entry: dict[str, Any]) -> dict[str, Any]:
        reference = entry["entry_id"] == "reference"
        return {
            "plan_id": manifest["plan_id"],
            "plan_version": manifest["version"],
            "manifest_path": str(manifest_path),
            "displacement_id": entry["entry_id"],
            "entry_kind": "reference" if reference else entry.get("kind"),
            "displaced_atom_id": None if reference else entry.get("displaced_atom_id"),
            "phonopy_atom_index": None if reference else entry.get("phonopy_atom_index"),
            "displacement_angstrom": None if reference else entry.get("displacement_angstrom"),
            "displacement_unit": None if reference else "angstrom",
            "sign": None if reference else entry.get("sign"),
            "parent_model_id": parent_model.model_id,
            "parent_model_version": parent_model.version,
            "parent_study_id": None,
            "parent_study_file": None,
        }

    def unknown_identity() -> dict[str, Any]:
        return {
            "plan_id": manifest["plan_id"],
            "plan_version": manifest["version"],
            "manifest_path": str(manifest_path),
            "displacement_id": "unknown",
            "entry_kind": None,
            "displaced_atom_id": None,
            "phonopy_atom_index": None,
            "displacement_angstrom": None,
            "displacement_unit": None,
            "sign": None,
            "parent_model_id": parent_model.model_id,
            "parent_model_version": parent_model.version,
            "parent_study_id": None,
            "parent_study_file": None,
        }

    records: dict[str, dict[str, Any]] = {}
    task_paths: list[Path] = []
    entry_by_id = {str(entry["entry_id"]): entry for entry in entries}
    for ordinal, spec in enumerate(task_specs, start=1):
        task_path = (root / f"task-{ordinal}-{spec}").resolve()
        task_path.mkdir()
        task_paths.append(task_path)
        task_id = f"software-task-{ordinal:03d}"
        if spec == "unbound":
            task = {"task_id": task_id}
            (task_path / "task.json").write_text(json.dumps(task) + "\n", encoding="utf-8")
            records[str(task_path)] = {"task_path": str(task_path), "task": task}
            continue

        if spec == "unknown":
            identity = unknown_identity()
            atoms = atoms_by_id["reference"].copy()
        else:
            identity = task_identity(entry_by_id[spec])
            atoms = atoms_by_id[spec].copy()
        study_path = task_path / "study.json"
        study_path.write_text("{}\n", encoding="utf-8")
        task = {
            "task_id": task_id,
            "stage": "P7",
            "calculation": "scf",
            "engine": "abacus",
            "engine_version": "3.10.1",
            "model_id": f"child-model-{ordinal:03d}",
            "model_version": "v001",
            "method_set": "software-contract-method-v001",
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "study_id": f"child-study-{ordinal:03d}",
            "study_file": str(study_path.resolve()),
            "case_id": "software-contract-case",
            "case_role": "engineering_fixture",
            "fixture": True,
            "input_transformation": None,
            "phonon_displacement": identity,
        }
        (task_path / "task.json").write_text(json.dumps(task) + "\n", encoding="utf-8")
        records[str(task_path)] = {
            "task_path": str(task_path),
            "task": task,
            "method": {},
            "source_model_path": str(task_path),
            "source_model_metadata": {"fixture": True},
            "source_model_atoms": atoms.copy(),
            "atoms": atoms,
            "native_stru": atoms.copy(),
            "final_atoms": atoms.copy(),
            "native_input": {"passed": False, "mismatches": [{"kind": "software_contract_only"}]},
            "native_electronic_converged": False,
            "method_physics": {},
            "native_physics": {},
            "native_result_consistent": False,
            "source_evidence": {
                "reason": "software_contract_only",
                "paths": [],
                "paths_belong_to_task": False,
                "fixture_purpose": "software_contract_only",
            },
            "native_forces_eV_per_A": [[0.0, 0.0, 0.0]],
            "result_forces_eV_per_A": [[0.0, 0.0, 0.0]],
        }

    monkeypatch.setattr(phonon_forces, "load_phonon_displacement_plan", lambda _path: manifest)
    monkeypatch.setattr(phonon_forces, "read_model_artifacts", lambda _path: parent_model)
    monkeypatch.setattr(
        phonon_forces,
        "_entry_atoms",
        lambda _path, entry: atoms_by_id[str(entry["entry_id"])].copy(),
    )
    monkeypatch.setattr(phonon_forces, "_geometry_check", lambda *_args: {"passed": True, "issues": []})
    monkeypatch.setattr(phonon_forces, "_structure_match", lambda *_args: {"passed": True, "issues": []})
    monkeypatch.setattr(phonon_forces, "_child_lineage_issues", lambda *_args: [])
    monkeypatch.setattr(
        phonon_forces,
        "load_native_force_task",
        lambda path: records[str(Path(path).resolve())],
    )
    return {
        "manifest_path": manifest_path,
        "task_paths": task_paths,
        "records_by_path": records,
        "manifest": manifest,
        "parent_model": parent_model,
    }


def test_load_native_force_task_reparses_job40_without_writing() -> None:
    loaded = load_native_force_task(JOB40)

    assert loaded["task"]["stage"] == "P4"
    assert loaded["task"]["scheduler_state"] == "COMPLETED"
    assert loaded["task"]["exit_code"] == "0:0"
    assert loaded["native_electronic_converged"] is True
    assert loaded["native_input"]["passed"] is True
    assert len(loaded["native_forces_eV_per_A"]) == 20
    assert loaded["native_forces_eV_per_A"] == loaded["native_result"]["forces_eV_per_A"]
    assert loaded["source_model_metadata"]["model_id"] == loaded["task"]["model_id"]
    assert loaded["source_model_metadata"]["version"] == loaded["task"]["model_version"]
    assert len(loaded["source_model_atoms"]) == len(loaded["atoms"])
    assert loaded["source_model_atoms"].get_chemical_symbols() == loaded["atoms"].get_chemical_symbols()
    assert Path(loaded["native_log"]).is_file()
    assert loaded["native_input"]["native_stru_pseudopotentials"] == {
        "Ca": "Ca.upf",
        "Zr": "Zr_ONCV_PBE-1.0.upf",
        "O": "O.upf",
    }
    assert loaded["native_input"]["native_stru_initial_moments_muB_by_element"] == {
        "Ca": 0.0,
        "Zr": 0.0,
        "O": 0.0,
    }


def test_native_stru_contract_rejects_pseudopotential_or_moment_drift() -> None:
    loaded = load_native_force_task(JOB40)
    method = json.loads(json.dumps(loaded["method"]))

    method["pseudopotentials"]["Ca"]["filename"] = "other-Ca.upf"
    method["initial_moments_muB_by_element"]["Zr"] = 1.0
    contract = _native_stru_contract(JOB40 / "STRU", method)

    assert contract["passed"] is False
    assert {item["kind"] for item in contract["mismatches"]} == {
        "pseudopotential_filename",
        "initial_moments",
    }


def test_native_lcao_contract_binds_formal_orbitals_and_header_snapshot(tmp_path: Path) -> None:
    stru = tmp_path / "STRU"
    stru.write_text(
        "ATOMIC_SPECIES\n"
        "Ba 137.33 Ba.upf upf201\n"
        "Ti 47.867 Ti.upf upf201\n"
        "O 16.0 O.upf upf201\n"
        "\n"
        "NUMERICAL_ORBITAL\n"
        "Ba.orb\n"
        "Ti.orb\n"
        "O.orb\n"
        "\n"
        "LATTICE_CONSTANT\n"
        "1.0\n"
        "LATTICE_VECTORS\n"
        "1 0 0\n"
        "0 1 0\n"
        "0 0 1\n"
        "ATOMIC_POSITIONS\n"
        "Cartesian\n"
        "Ba\n0.0\n1\n0 0 0 0 0\n"
        "Ti\n0.0\n1\n0.5 0.5 0.5 0 0\n"
        "O\n0.0\n1\n0.5 0.0 0.0 0 0\n",
        encoding="utf-8",
    )
    snapshot = tmp_path / "nao-snapshot.json"
    method = {
        "method_set": "bto-lcao-v001",
        "element_order": ["Ba", "Ti", "O"],
        "numerical_orbital_ids": {
            "Ba": "Ba.orb",
            "Ti": "Ti.orb",
            "O": "O.orb",
        },
        "numerical_orbitals": {
            element: {"source": str(tmp_path / f"{element}.orb"), "filename": f"{element}.orb"}
            for element in ("Ba", "Ti", "O")
        },
        "orbital_header_snapshot": str(snapshot),
    }
    snapshot.write_text(
        json.dumps(
            {
                "schema": "mlcc.nao-header-snapshot.v1",
                "method_set": method["method_set"],
                "native_excerpts": {
                    element: {
                        "source_path": method["numerical_orbitals"][element]["source"],
                        "orbital_id": method["numerical_orbital_ids"][element],
                    }
                    for element in ("Ba", "Ti", "O")
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    contract = _native_lcao_contract(stru, method)

    assert contract["passed"] is True
    assert contract["native_numerical_orbitals"] == ["Ba.orb", "Ti.orb", "O.orb"]
    method["numerical_orbital_ids"]["Ti"] = "other.orb"
    rejected = _native_lcao_contract(stru, method)
    assert rejected["passed"] is False
    assert {item["kind"] for item in rejected["mismatches"]} >= {
        "orbital_header_snapshot_id",
    }


def test_phonon_identity_requires_explicit_displacement_fields(tmp_path: Path) -> None:
    entry = {"entry_id": "reference", "kind": "reference"}
    expected = _phonon_entry_identity(
        entry,
        plan_id="plan",
        plan_version="v001",
        manifest_path=tmp_path / "plan/displacement-manifest.json",
        parent_model={"model_id": "parent", "version": "v001"},
        parent_study_id="study",
        parent_study_file=tmp_path / "study.json",
    )
    assert expected["entry_kind"] == "reference"
    assert expected["displaced_atom_id"] is None
    assert expected["phonopy_atom_index"] is None
    assert expected["displacement_angstrom"] is None
    assert expected["displacement_unit"] is None
    assert expected["sign"] is None

    actual = dict(expected)
    actual["displaced_atom_id"] = 0
    mismatches = _identity_mismatches(expected, actual, base_path=PROJECT_ROOT)
    assert [item["field"] for item in mismatches] == ["displaced_atom_id"]


def test_job40_is_a_real_single_task_regression_and_cannot_form_a_set(tmp_path: Path) -> None:
    plan_path = _plan(tmp_path / "phonon-plan.json")
    report = collect_phonon_forces(plan_path, [JOB40], _thresholds())

    assert report["force_set"] == "incomplete"
    assert report["status"] == "blocked_force_collection"
    assert report["ready_for_harmonic"] is False
    assert report["scientific_qualification"] is False
    assert report["collected_displacement_ids"] == []
    expected = report["checks"]["expected_displacement_set"]
    assert expected["missing"][0] == "reference"
    assert len(expected["missing"]) == len(report["expected_displacement_ids"])
    assert any(issue["code"] == "missing_displacement_identity" for issue in report["issues"])
    assert any(issue["code"] == "missing_reference_force" for issue in report["issues"])
    assert report["force_bundle"] is None


def test_raw_force_drift_is_reported_without_correction() -> None:
    raw = [[1.0, -2.0, 0.5], [-0.25, 0.5, 1.5]]
    original = json.loads(json.dumps(raw))

    drift = _force_drift(raw)

    assert raw == original
    assert drift["vector_eV_per_A"] == [0.75, -1.5, 2.0]
    assert drift["norm_eV_per_A"] == pytest.approx(np.sqrt(0.75**2 + 1.5**2 + 2.0**2))
    assert drift["max_component_abs_eV_per_A"] == 2.0


def test_collection_requires_every_explicit_threshold(tmp_path: Path) -> None:
    plan_path = _plan(tmp_path / "phonon-plan.json")
    values = _thresholds()
    values.pop("force_drift_tolerance_eV_per_A")

    with pytest.raises(ValueError, match="force_drift_tolerance_eV_per_A"):
        collect_phonon_forces(plan_path, [JOB40], values)


def test_collection_native_task_records_follow_manifest_order_and_keep_known_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _minimal_collection_fixture(
        tmp_path,
        monkeypatch,
        ["u-plus", "reference", "u-plus", "u-minus"],
    )
    manifest_path = fixture["manifest_path"]
    task_paths = fixture["task_paths"]
    records = fixture["records_by_path"]

    report = collect_phonon_forces(manifest_path, task_paths, _thresholds())

    expected_records = [
        str((task_paths[1] / "task.json").resolve()),
        str((task_paths[0] / "task.json").resolve()),
        str((task_paths[2] / "task.json").resolve()),
        str((task_paths[3] / "task.json").resolve()),
    ]
    assert report["native_task_records"] == expected_records
    assert all(Path(path).is_absolute() and Path(path).name == "task.json" for path in report["native_task_records"])
    assert report["checks"]["expected_displacement_set"]["duplicates"] == ["u-plus"]
    assert report["status"] == "blocked_force_collection"
    assert report["scientific_qualification"] is False
    assert all(item["task"].get("fixture") is True for item in records.values())


def test_collection_native_task_records_complete_known_input_keeps_blocking_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _minimal_collection_fixture(tmp_path, monkeypatch, ["u-minus", "u-plus", "reference"])
    manifest_path = fixture["manifest_path"]
    task_paths = fixture["task_paths"]

    report = collect_phonon_forces(manifest_path, task_paths, _thresholds())
    collection_path = manifest_path.parent / "collection.json"
    collection_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (manifest_path.parent / "fixture.json").write_text(json.dumps({
        "evidence_kind": "software_contract_only",
        "collection_path": str(collection_path),
        "manifest_path": str(manifest_path),
        "parent_model": fixture["manifest"]["source_model"],
        "task_paths": [str(path) for path in task_paths],
        "native_parser_executed": False,
        "native_source_bound_positive": False,
    }, indent=2) + "\n", encoding="utf-8")

    assert report["native_task_records"] == [
        str((task_paths[2] / "task.json").resolve()),
        str((task_paths[1] / "task.json").resolve()),
        str((task_paths[0] / "task.json").resolve()),
    ]
    assert report["checks"]["expected_displacement_set"]["missing"] == []
    assert report["checks"]["expected_displacement_set"]["duplicates"] == []
    assert report["status"] == "blocked_force_collection"
    assert report["ready_for_harmonic"] is False
    assert report["force_bundle"] is None
    assert report["scientific_qualification"] is False
    assert report["production_qualification"] is False
    assert report["native_task_records"]
    assert collection_path.is_file()


def test_collection_binds_explicit_p4_parent_reference_without_p7_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _minimal_collection_fixture(tmp_path, monkeypatch, ["reference", "u-minus", "u-plus"])
    reference_path = fixture["task_paths"][0]
    reference_record = fixture["records_by_path"][str(reference_path.resolve())]
    parent_model = fixture["parent_model"]
    study_path = parent_model.artifact_dir / "parent-study.json"
    study_path.write_text(
        json.dumps(
            {
                "study_id": "software-parent-study",
                "model": {
                    "model_id": parent_model.model_id,
                    "version": parent_model.version,
                    "material": None,
                    "phase_requested": None,
                    "dopants": [],
                },
                "case_id": "software-contract-case",
                "case_role": "engineering_fixture",
                "fixture": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reference_task = reference_record["task"]
    reference_task["stage"] = "P4"
    reference_task.pop("phonon_displacement", None)
    reference_task.update(
        {
            "model_id": parent_model.model_id,
            "model_version": parent_model.version,
            "study_id": "software-parent-study",
            "study_file": str(study_path.resolve()),
        }
    )
    reference_record["source_model_path"] = str(parent_model.artifact_dir.resolve())
    reference_record["source_model_metadata"] = parent_model.metadata

    report = collect_phonon_forces(
        fixture["manifest_path"],
        fixture["task_paths"][1:],
        _thresholds(),
        reference_task_record=reference_path,
    )

    assert report["reference_binding_mode"] == "explicit_parent_reference"
    assert report["reference_task_record"] == str((reference_path / "task.json").resolve())
    assert report["native_task_records"][0] == report["reference_task_record"]
    assert report["checks"]["reference_binding"]["task"]["stage"] == "P4"
    assert set(report["checks"]["p7_stage"]["tasks"]) == {
        str(fixture["records_by_path"][str(path.resolve())]["task"]["task_id"])
        for path in fixture["task_paths"][1:]
    }
    assert not any(issue["code"] == "missing_displacement_identity" for issue in report["issues"])


def test_collection_derives_omitted_study_fixture_and_rejects_explicit_contradiction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _minimal_collection_fixture(tmp_path, monkeypatch, ["reference", "u-minus", "u-plus"])
    reference_path = fixture["task_paths"][0]
    reference_record = fixture["records_by_path"][str(reference_path.resolve())]
    parent_model = fixture["parent_model"]
    study_path = parent_model.artifact_dir / "derived-fixture-study.json"

    reference_task = reference_record["task"]
    reference_task["stage"] = "P4"
    reference_task.pop("phonon_displacement", None)
    reference_task.update(
        {
            "model_id": parent_model.model_id,
            "model_version": parent_model.version,
            "study_id": "derived-fixture-study",
            "study_file": str(study_path.resolve()),
        }
    )
    reference_record["source_model_path"] = str(parent_model.artifact_dir.resolve())
    reference_record["source_model_metadata"] = parent_model.metadata

    study = {
        "study_id": "derived-fixture-study",
        "model": {
            "model_id": parent_model.model_id,
            "version": parent_model.version,
            "material": None,
            "phase_requested": None,
            "dopants": [],
        },
        "case_id": "software-contract-case",
        "case_role": "engineering_fixture",
    }
    study_path.write_text(json.dumps(study) + "\n", encoding="utf-8")

    for child_path in fixture["task_paths"][1:]:
        child_record = fixture["records_by_path"][str(child_path.resolve())]
        child_task = child_record["task"]
        child_identity = child_task["phonon_displacement"]
        child_identity["parent_study_id"] = "derived-fixture-study"
        child_identity["parent_study_file"] = str(study_path.resolve())
        child_study = {
            "study_id": child_task["study_id"],
            "model": {
                "model_id": child_task["model_id"],
                "version": child_task["model_version"],
                "material": None,
                "phase_requested": None,
                "dopants": [],
                "source_structure": str((child_path / "model.extxyz").resolve()),
            },
            "case_id": child_task["case_id"],
            "case_role": child_task["case_role"],
            "parent_study_id": "derived-fixture-study",
            "derived_from": {
                "study_id": "derived-fixture-study",
                "model_id": parent_model.model_id,
                "model_version": parent_model.version,
            },
            "phonon_displacement": child_identity,
            "selected_required_tasks": [child_task["task_id"]],
        }
        Path(child_task["study_file"]).write_text(json.dumps(child_study) + "\n", encoding="utf-8")

    report = collect_phonon_forces(
        fixture["manifest_path"],
        fixture["task_paths"][1:],
        _thresholds(),
        reference_task_record=reference_path,
    )

    assert report["checks"]["reference_binding"]["passed"] is True
    assert not any(
        detail["code"] == "reference_case_binding"
        for issue in report["issues"]
        if issue["code"] == "reference_binding_mismatch"
        for detail in issue.get("details", [])
    )
    assert all(
        not any(
            detail.get("field") == "fixture"
            for detail in check["issues"]
        )
        for check in report["checks"]["child_study_binding"]["tasks"].values()
    )

    study["fixture"] = False
    study_path.write_text(json.dumps(study) + "\n", encoding="utf-8")
    contradictory = collect_phonon_forces(
        fixture["manifest_path"],
        fixture["task_paths"][1:],
        _thresholds(),
        reference_task_record=reference_path,
    )

    assert contradictory["checks"]["reference_binding"]["passed"] is False
    assert any(
        detail["code"] == "reference_case_binding"
        for issue in contradictory["issues"]
        if issue["code"] == "reference_binding_mismatch"
        for detail in issue.get("details", [])
    )


def test_collection_rejects_explicit_p4_reference_bound_to_wrong_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _minimal_collection_fixture(tmp_path, monkeypatch, ["reference", "u-minus", "u-plus"])
    reference_path = fixture["task_paths"][0]
    reference_record = fixture["records_by_path"][str(reference_path.resolve())]
    parent_model = fixture["parent_model"]
    study_path = parent_model.artifact_dir / "wrong-parent-study.json"
    study_path.write_text(
        json.dumps(
            {
                "study_id": "wrong-parent-study",
                "model": {
                    "model_id": parent_model.model_id,
                    "version": parent_model.version,
                    "material": None,
                    "phase_requested": None,
                    "dopants": [],
                },
                "case_id": "software-contract-case",
                "case_role": "engineering_fixture",
                "fixture": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reference_task = reference_record["task"]
    reference_task["stage"] = "P4"
    reference_task.pop("phonon_displacement", None)
    reference_task.update(
        {
            "model_id": "wrong-parent-model",
            "model_version": parent_model.version,
            "study_id": "wrong-parent-study",
            "study_file": str(study_path.resolve()),
        }
    )
    reference_record["source_model_path"] = str(parent_model.artifact_dir.resolve())
    reference_record["source_model_metadata"] = parent_model.metadata

    report = collect_phonon_forces(
        fixture["manifest_path"],
        fixture["task_paths"][1:],
        _thresholds(),
        reference_task_record=reference_path,
    )

    assert report["checks"]["reference_binding"]["passed"] is False
    assert any(
        issue["code"] == "reference_binding_mismatch"
        and any(detail["code"] == "reference_model_identity" for detail in issue["details"])
        for issue in report["issues"]
        if issue["code"] == "reference_binding_mismatch"
    )


def test_collection_rejects_child_with_wrong_parent_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _minimal_collection_fixture(tmp_path, monkeypatch, ["reference", "u-minus", "u-plus"])
    reference_path = fixture["task_paths"][0]
    reference_record = fixture["records_by_path"][str(reference_path.resolve())]
    parent_model = fixture["parent_model"]
    study_path = parent_model.artifact_dir / "child-parent-study.json"
    study_path.write_text(
        json.dumps(
            {
                "study_id": "child-parent-study",
                "model": {
                    "model_id": parent_model.model_id,
                    "version": parent_model.version,
                    "material": None,
                    "phase_requested": None,
                    "dopants": [],
                },
                "case_id": "software-contract-case",
                "case_role": "engineering_fixture",
                "fixture": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reference_task = reference_record["task"]
    reference_task["stage"] = "P4"
    reference_task.pop("phonon_displacement", None)
    reference_task.update(
        {
            "model_id": parent_model.model_id,
            "model_version": parent_model.version,
            "study_id": "child-parent-study",
            "study_file": str(study_path.resolve()),
        }
    )
    reference_record["source_model_path"] = str(parent_model.artifact_dir.resolve())
    reference_record["source_model_metadata"] = parent_model.metadata

    child_path = fixture["task_paths"][1]
    child_record = fixture["records_by_path"][str(child_path.resolve())]
    child_record["task"]["phonon_displacement"]["parent_model_id"] = "wrong-parent-model"

    report = collect_phonon_forces(
        fixture["manifest_path"],
        fixture["task_paths"][1:],
        _thresholds(),
        reference_task_record=reference_path,
    )

    child_id = child_record["task"]["task_id"]
    assert report["checks"]["source_identity"]["passed"] is False
    assert any(
        issue["code"] == "source_identity_mismatch" and issue["task_id"] == child_id
        for issue in report["issues"]
    )


def test_collection_native_task_records_keeps_partial_known_and_excludes_unknown_or_unbound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _minimal_collection_fixture(
        tmp_path,
        monkeypatch,
        ["unknown", "u-plus", "unbound", "reference"],
    )
    manifest_path = fixture["manifest_path"]
    task_paths = fixture["task_paths"]

    report = collect_phonon_forces(manifest_path, task_paths, _thresholds())

    assert report["native_task_records"] == [
        str((task_paths[3] / "task.json").resolve()),
        str((task_paths[1] / "task.json").resolve()),
    ]
    expected = report["checks"]["expected_displacement_set"]
    assert expected["missing"] == ["u-minus"]
    assert expected["unknown"] == ["unknown"]
    assert report["status"] == "blocked_force_collection"
    assert report["ready_for_harmonic"] is False
    assert any(issue["code"] == "unknown_displacement" for issue in report["issues"])
    assert any(issue["code"] == "missing_displacement" for issue in report["issues"])
    assert any(issue["code"] == "missing_displacement_identity" for issue in report["issues"])


def test_collection_native_task_records_empty_input_stays_empty_and_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _minimal_collection_fixture(tmp_path, monkeypatch, [])
    manifest_path = fixture["manifest_path"]

    report = collect_phonon_forces(manifest_path, [], _thresholds())

    assert report["native_task_records"] == []
    assert report["status"] == "blocked_force_collection"
    assert report["ready_for_harmonic"] is False
    assert report["checks"]["expected_displacement_set"]["missing"] == [
        "reference",
        "u-plus",
        "u-minus",
    ]


def test_collection_preserves_original_loader_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _minimal_collection_fixture(tmp_path, monkeypatch, [])
    manifest_path = fixture["manifest_path"]
    failed_task = tmp_path / "failed-native-task"
    failed_task.mkdir()

    def raise_original_error(_path: Path) -> dict[str, Any]:
        raise RuntimeError("native loader original failure")

    monkeypatch.setattr(phonon_forces, "load_native_force_task", raise_original_error)

    with pytest.raises(RuntimeError, match="native loader original failure"):
        collect_phonon_forces(manifest_path, [failed_task], _thresholds())
