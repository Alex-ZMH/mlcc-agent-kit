import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

import mlcc.phonon_gamma as phonon_gamma
from mlcc.modeling import read_model_artifacts, write_model_artifacts
from mlcc.dielectric_response import p5_method_identity
from mlcc.phonon_gamma import (
    GAMMA_HESSIAN_SCHEMA,
    _select_native_task_records,
    _validate_source_binding,
    compute_gamma_fixed_cell_hessian,
    read_native_gamma_method_source,
)
from mlcc.phonons import FORCE_CONSTANT_UNIT, FORCE_UNIT, compute_harmonic_qpoints, generate_phonon_displacement_plan


def _request(plan_id: str = "gamma-plan") -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "version": "v001",
        "phonopy_version": "4.8.3",
        "repeat_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "primitive_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "distance_angstrom": 0.01,
        "symprec": 1e-5,
        "is_symmetry": False,
        "hermitianize_dynamical_matrix": False,
    }


def _write_parent(tmp_path: Path) -> Path:
    atoms = Atoms(
        symbols=["Na", "Cl"],
        scaled_positions=[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        cell=[[3.0, 0.0, 0.0], [0.2, 3.1, 0.0], [0.1, 0.2, 3.2]],
        pbc=True,
    )
    atoms.set_masses([10.0, 20.0])
    atoms.new_array("atom_id", np.asarray([101, 205], dtype=np.int64))
    model_dir = tmp_path / "parent"
    write_model_artifacts(
        atoms,
        model_dir,
        model_id="gamma-parent",
        version="v001",
        fixture=False,
        phase_requested="explicit_test_structure",
        source_path="test-structure",
        source_version="test-v001",
        material="test-material",
    )
    return model_dir


def _prepare_case(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    parent_path = _write_parent(tmp_path)
    plan_dir = tmp_path / "plan"
    manifest = generate_phonon_displacement_plan(parent_path, _request(), plan_dir)
    spring = 0.75
    records = []
    for entry in manifest["displacements"]:
        force = np.zeros((len(entry["atom_ids"]), 3), dtype=float)
        force[int(entry["phonopy_atom_index"])] = -spring * np.asarray(entry["displacement_angstrom"])
        records.append(
            {
                "entry_id": entry["entry_id"],
                "atom_ids": entry["atom_ids"],
                "forces": force.tolist(),
                "source_ref": f"math://{entry['entry_id']}",
            }
        )
    force_bundle = {"unit": FORCE_UNIT, "source": "math_harmonic_fixture", "records": records}
    force_bundle_path = tmp_path / "force-bundle.json"
    force_bundle_path.write_text(json.dumps(force_bundle) + "\n", encoding="utf-8")
    harmonic_path = tmp_path / "harmonic-result.json"
    harmonic = compute_harmonic_qpoints(
        plan_dir / "displacement-manifest.json",
        force_bundle,
        [[0.0, 0.0, 0.0]],
        output_path=harmonic_path,
    )
    study_path = tmp_path / "study.json"
    parent = read_model_artifacts(parent_path)
    study_path.write_text(
        json.dumps(
            {
                "study_id": "gamma-study",
                "model": {"model_id": parent.model_id, "version": parent.version},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    binding = {
        "parent": {
            "study_id": "gamma-study",
            "study_path": str(study_path.resolve()),
            "model_id": parent.model_id,
            "model_version": parent.version,
            "model_path": str(parent_path.resolve()),
        },
        "method_identity": {"engine": "math-fixture", "method": "explicit-spring"},
        "source_binding": {
            "source_mode": "software_math_only",
            "harmonic_result_path": str(harmonic_path.resolve()),
            "plan_manifest_path": str((plan_dir / "displacement-manifest.json").resolve()),
            "force_bundle_path": str(force_bundle_path.resolve()),
        },
    }
    return harmonic_path, plan_dir / "displacement-manifest.json", force_bundle_path, {
        **binding,
        "harmonic": harmonic,
    }


def test_native_source_binding_keeps_legacy_p7_reference_without_explicit_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The historical P7 reference branch must not read an unset parent path."""

    harmonic_path, plan_path, force_bundle_path, case = _prepare_case(tmp_path)
    manifest = json.loads(plan_path.read_text(encoding="utf-8"))
    force_bundle = json.loads(force_bundle_path.read_text(encoding="utf-8"))
    study_path = Path(str(case["parent"]["study_path"])).resolve()
    parent_model_path = Path(str(case["parent"]["model_path"])).resolve()
    expected_ids = ["reference", *[str(entry["entry_id"]) for entry in manifest["displacements"]]]
    task_root = tmp_path / "legacy-p7-native-tasks"
    task_root.mkdir()
    task_paths: list[Path] = []
    loaded_by_path: dict[str, dict[str, object]] = {}
    evidence_by_task: dict[str, dict[str, object]] = {}
    source_logs: dict[str, str] = {}
    native_method_set = "legacy-p7-native-method-v001"

    for ordinal, entry_id in enumerate(expected_ids, start=1):
        task_dir = task_root / f"task-{ordinal:03d}-{entry_id}"
        task_dir.mkdir()
        task_id = f"legacy-p7-task-{ordinal:03d}"
        task_file = task_dir / "task.json"
        method_file = task_dir / "method.json"
        native_log = task_dir / "OUT.LegacyP7" / "running_scf.log"
        native_log.parent.mkdir()
        native_log.write_text("legacy native source\n", encoding="utf-8")
        task = {
            "task_id": task_id,
            "stage": "P7",
            "calculation": "scf",
            "model_id": "gamma-parent",
            "model_version": "v001",
            "method_set": native_method_set,
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "study_id": "gamma-study",
            "study_file": str(study_path),
            "phonon_displacement": {
                "displacement_id": entry_id,
                "parent_model_id": "gamma-parent",
                "parent_model_version": "v001",
                "parent_study_id": "gamma-study",
                "parent_study_file": str(study_path),
                "manifest_path": str(plan_path.resolve()),
            },
        }
        method = {"method_set": native_method_set}
        task_file.write_text(json.dumps(task) + "\n", encoding="utf-8")
        method_file.write_text(json.dumps(method) + "\n", encoding="utf-8")
        task_paths.append(task_dir)
        source_logs[entry_id] = str(native_log.resolve())
        loaded_by_path[str(task_dir.resolve())] = {
            "task": task,
            "method": method,
            "native_log": str(native_log.resolve()),
            "source_model_path": str(parent_model_path),
            "source_evidence": {
                "reason": "complete",
                "paths_belong_to_task": True,
                "paths": [str(native_log.resolve())],
            },
        }
        evidence_by_task[task_id] = {
            "reason": "complete",
            "paths_belong_to_task": True,
            "paths": [str(native_log.resolve())],
        }

    for record in force_bundle["records"]:
        record["source_ref"] = source_logs[str(record["entry_id"])]
    force_bundle_path.write_text(json.dumps(force_bundle) + "\n", encoding="utf-8")
    harmonic = json.loads(harmonic_path.read_text(encoding="utf-8"))
    harmonic["force_input"]["source_refs"] = [
        source_logs[str(entry["entry_id"])] for entry in manifest["displacements"]
    ]
    harmonic_path.write_text(json.dumps(harmonic) + "\n", encoding="utf-8")

    checks = {
        name: {"passed": True}
        for name in (
            "scheduler_completed_0",
            "p7_stage",
            "electronic_converged",
            "source_identity",
            "parent_study_binding",
            "child_model_binding",
            "child_study_binding",
            "method_input_qualification",
            "same_method_physics",
            "same_native_input_physics",
            "native_input_contract",
            "native_result_force_match",
            "native_result_consistency",
        )
    }
    checks["native_source_evidence"] = {"passed": True, "tasks": evidence_by_task}
    collection = {
        "schema": "mlcc.phonon-force-collection.v001",
        "plan_path": str(plan_path.resolve()),
        "plan_id": manifest["plan_id"],
        "plan_version": manifest["version"],
        "parent_model_id": "gamma-parent",
        "parent_model_version": "v001",
        "parent_study_id": "gamma-study",
        "parent_study_file": str(study_path),
        "reference_binding_mode": "p7_reference_identity",
        "reference_task_record": None,
        "ready_for_harmonic": True,
        "expected_displacement_ids": expected_ids,
        "collected_displacement_ids": expected_ids,
        "checks": checks,
        "force_bundle": force_bundle,
        "native_task_records": [str((path / "task.json").resolve()) for path in task_paths],
    }
    collection_path = tmp_path / "legacy-p7-collection.json"
    collection_path.write_text(json.dumps(collection) + "\n", encoding="utf-8")
    source_binding = {
        "source_mode": "native_source_bound",
        "harmonic_result_path": str(harmonic_path.resolve()),
        "plan_manifest_path": str(plan_path.resolve()),
        "force_bundle_path": str(force_bundle_path.resolve()),
        "collection_path": str(collection_path.resolve()),
        "parent_model_id": "gamma-parent",
        "parent_model_version": "v001",
        "parent_study_id": "gamma-study",
        "parent_study_file": str(study_path),
        "native_task_records": [str((path / "task.json").resolve()) for path in task_paths],
    }

    monkeypatch.setattr(
        phonon_gamma,
        "load_native_force_task",
        lambda path: loaded_by_path[str(Path(path).resolve())],
    )
    monkeypatch.setattr(
        phonon_gamma,
        "_method_physics_without_model",
        lambda _method: {"method": "legacy-p7"},
    )
    monkeypatch.setattr(
        phonon_gamma,
        "read_native_gamma_method_source",
        lambda *_args, **_kwargs: {"method_identity": {"method": "legacy-p7"}},
    )

    bound, _ = _validate_source_binding(
        source_binding,
        harmonic_path=harmonic_path.resolve(),
        plan_path=plan_path.resolve(),
        manifest=manifest,
        harmonic=harmonic,
        method_identity={"method": "legacy-p7"},
        parent_binding=case["parent"],
    )

    assert bound["reference_task_record"] is None
    assert bound["native_task_records"] == [
        str((path / "task.json").resolve()) for path in task_paths
    ]
    assert len(bound["native_method_sources"]) == len(expected_ids)


def _write_task_record_paths(tmp_path: Path) -> tuple[Path, Path]:
    paths = []
    for name in ("reference", "displacement-001"):
        task_dir = tmp_path / name
        task_dir.mkdir()
        task_file = task_dir / "task.json"
        task_file.write_text("{}\n", encoding="utf-8")
        paths.append(task_file)
    return paths[0], paths[1]


def test_native_task_records_auto_selects_saved_reference_first_order(tmp_path):
    reference, displacement = _write_task_record_paths(tmp_path)
    selected, has_saved_order = _select_native_task_records(
        {"native_task_records": [str(reference), str(displacement)]},
        {},
    )

    assert selected == [reference.resolve(), displacement.resolve()]
    assert has_saved_order is True


def test_native_task_records_accepts_matching_explicit_file_and_directory_forms(tmp_path):
    reference, displacement = _write_task_record_paths(tmp_path)
    selected, has_saved_order = _select_native_task_records(
        {"native_task_records": [str(reference), str(displacement)]},
        {"native_task_records": [str(reference), str(displacement.parent)]},
    )

    assert selected == [reference.resolve(), displacement.resolve()]
    assert has_saved_order is True


def test_native_task_records_rejects_conflicting_explicit_order(tmp_path):
    reference, displacement = _write_task_record_paths(tmp_path)
    with pytest.raises(ValueError, match="differs from the saved collection"):
        _select_native_task_records(
            {"native_task_records": [str(reference), str(displacement)]},
            {"native_task_records": [str(displacement), str(reference)]},
        )


def test_native_task_records_legacy_collection_preserves_explicit_order(tmp_path):
    reference, displacement = _write_task_record_paths(tmp_path)
    selected, has_saved_order = _select_native_task_records(
        {},
        {"native_task_records": [str(displacement.parent), str(reference)]},
    )

    assert selected == [displacement.resolve(), reference.resolve()]
    assert has_saved_order is False


def test_native_task_records_requires_explicit_source_for_legacy_collection(tmp_path):
    _write_task_record_paths(tmp_path)
    with pytest.raises(ValueError, match="requires native_task_records"):
        _select_native_task_records({}, {})


def test_native_task_records_rejects_malformed_saved_field_instead_of_falling_back(tmp_path):
    reference, _displacement = _write_task_record_paths(tmp_path)
    with pytest.raises(ValueError, match="must be a non-empty list"):
        _select_native_task_records(
            {"native_task_records": None},
            {"native_task_records": [str(reference)]},
        )
    with pytest.raises(ValueError, match="must be a non-empty list"):
        _select_native_task_records(
            {"native_task_records": [str(reference)]},
            {"native_task_records": []},
        )


def test_native_task_records_rejects_invalid_and_duplicate_explicit_entries(tmp_path):
    reference, _displacement = _write_task_record_paths(tmp_path)
    with pytest.raises(ValueError, match="must be a non-empty string"):
        _select_native_task_records(
            {},
            {"native_task_records": [123]},
        )
    with pytest.raises(ValueError, match="contains duplicate task records"):
        _select_native_task_records(
            {},
            {"native_task_records": [str(reference), str(reference)]},
        )


def test_gamma_hessian_reuses_harmonic_result_and_scales_mass(tmp_path):
    harmonic_path, plan_path, _force_bundle_path, case = _prepare_case(tmp_path)
    result = compute_gamma_fixed_cell_hessian(
        harmonic_path,
        plan_path,
        parent=case["parent"],
        method_identity=case["method_identity"],
        source_binding=case["source_binding"],
        geometry_tolerance_angstrom=1e-7,
        volume_tolerance_A3=1e-7,
        mass_tolerance_amu=1e-8,
        dynamical_imag_tolerance=1e-12,
    )
    matrix = np.asarray(result["matrix_eV_per_A2"], dtype=float)
    force_constants = np.asarray(case["harmonic"]["force_constants"], dtype=float)
    assert result["schema"] == GAMMA_HESSIAN_SCHEMA
    assert result["atom_ids"] == [101, 205]
    assert result["unit"] == FORCE_CONSTANT_UNIT
    assert result["matrix_unit"] == FORCE_CONSTANT_UNIT
    assert result["electrical_boundary"] == "fixed_E_zero"
    assert result["mechanical_boundary"] == "fixed_cell"
    assert result["nac"] == "not_applied"
    assert result["scientific_qualification"] is False
    assert result["production_qualified"] is False
    assert matrix.shape == (6, 6)
    # The source FC is in eV/A^2; recovering it from D*sqrt(m_i*m_j)
    # catches the mass scaling because the two parent masses differ.
    assert matrix[0, 0] == pytest.approx(force_constants[0, 0, 0, 0], abs=1e-8)
    assert matrix[3, 3] == pytest.approx(force_constants[1, 1, 0, 0], abs=1e-8)
    assert result["qualification"]["source_mode"] == "software_math_only"


def test_gamma_hessian_requires_force_bundle_refs_matching_harmonic(tmp_path):
    harmonic_path, plan_path, force_bundle_path, case = _prepare_case(tmp_path)
    force_bundle = json.loads(force_bundle_path.read_text(encoding="utf-8"))
    force_bundle["records"][0]["source_ref"] = "math://tampered"
    force_bundle_path.write_text(json.dumps(force_bundle) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_refs differ"):
        compute_gamma_fixed_cell_hessian(
            harmonic_path,
            plan_path,
            parent=case["parent"],
            method_identity=case["method_identity"],
            source_binding=case["source_binding"],
            geometry_tolerance_angstrom=1e-7,
            volume_tolerance_A3=1e-7,
            mass_tolerance_amu=1e-8,
            dynamical_imag_tolerance=1e-12,
        )


def test_gamma_hessian_rejects_non_matching_parent_model_binding(tmp_path):
    harmonic_path, plan_path, _force_bundle_path, case = _prepare_case(tmp_path)
    wrong_parent = dict(case["parent"])
    wrong_parent["model_id"] = "different-parent"
    with pytest.raises(ValueError, match="parent model binding"):
        compute_gamma_fixed_cell_hessian(
            harmonic_path,
            plan_path,
            parent=wrong_parent,
            method_identity=case["method_identity"],
            source_binding=case["source_binding"],
            geometry_tolerance_angstrom=1e-7,
            volume_tolerance_A3=1e-7,
            mass_tolerance_amu=1e-8,
            dynamical_imag_tolerance=1e-12,
        )


def test_gamma_hessian_rejects_study_model_binding_and_implicit_hermitianization(tmp_path):
    harmonic_path, plan_path, _force_bundle_path, case = _prepare_case(tmp_path)
    study = json.loads(Path(case["parent"]["study_path"]).read_text(encoding="utf-8"))
    study["model"]["model_id"] = "different-parent"
    Path(case["parent"]["study_path"]).write_text(json.dumps(study) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Study model reference"):
        compute_gamma_fixed_cell_hessian(
            harmonic_path,
            plan_path,
            parent=case["parent"],
            method_identity=case["method_identity"],
            source_binding=case["source_binding"],
            geometry_tolerance_angstrom=1e-7,
            volume_tolerance_A3=1e-7,
            mass_tolerance_amu=1e-8,
            dynamical_imag_tolerance=1e-12,
        )

    harmonic_path, plan_path, _force_bundle_path, case = _prepare_case(tmp_path / "hermitian")
    manifest = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest["request"]["hermitianize_dynamical_matrix"] = True
    plan_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hermitianize_dynamical_matrix=false"):
        compute_gamma_fixed_cell_hessian(
            harmonic_path,
            plan_path,
            parent=case["parent"],
            method_identity=case["method_identity"],
            source_binding=case["source_binding"],
            geometry_tolerance_angstrom=1e-7,
            volume_tolerance_A3=1e-7,
            mass_tolerance_amu=1e-8,
            dynamical_imag_tolerance=1e-12,
        )


def test_gamma_hessian_requires_explicit_tolerance_and_source_mode(tmp_path):
    harmonic_path, plan_path, force_bundle_path, case = _prepare_case(tmp_path)
    bad_source = dict(case["source_binding"])
    bad_source.pop("source_mode")
    with pytest.raises(ValueError, match="source_binding.source_mode"):
        compute_gamma_fixed_cell_hessian(
            harmonic_path,
            plan_path,
            parent=case["parent"],
            method_identity=case["method_identity"],
            source_binding=bad_source,
            geometry_tolerance_angstrom=1e-7,
            volume_tolerance_A3=1e-7,
            mass_tolerance_amu=1e-8,
            dynamical_imag_tolerance=1e-12,
        )
    native_source = dict(case["source_binding"])
    native_source.update(
        {
            "source_mode": "native_source_bound",
            "parent_study_id": case["parent"]["study_id"],
            "parent_model_id": case["parent"]["model_id"],
            "parent_model_version": case["parent"]["model_version"],
            # An existing force bundle is deliberately not accepted as a
            # native phonon-force collection merely because it is readable.
            "collection_path": str(force_bundle_path.resolve()),
        }
    )
    with pytest.raises(ValueError, match="phonon force collection"):
        compute_gamma_fixed_cell_hessian(
            harmonic_path,
            plan_path,
            parent=case["parent"],
            method_identity=case["method_identity"],
            source_binding=native_source,
            geometry_tolerance_angstrom=1e-7,
            volume_tolerance_A3=1e-7,
            mass_tolerance_amu=1e-8,
            dynamical_imag_tolerance=1e-12,
        )
    with pytest.raises(ValueError, match="dynamical_imag_tolerance"):
        compute_gamma_fixed_cell_hessian(
            harmonic_path,
            plan_path,
            parent=case["parent"],
            method_identity=case["method_identity"],
            source_binding=case["source_binding"],
            geometry_tolerance_angstrom=1e-7,
            volume_tolerance_A3=1e-7,
            mass_tolerance_amu=1e-8,
            dynamical_imag_tolerance=-1.0,
        )


def _write_gamma_source_task(
    tmp_path: Path,
    *,
    kpt_offset: tuple[int, int, int] | None = (0, 0, 0),
    requested_pw_diag_thr: float | None = 1.0e-3,
    native_pw_diag_thr: float | None = 2.0e-3,
    result: bool = False,
    missing_method_keys: tuple[str, ...] = (),
) -> Path:
    """Write a software-only P7 source fixture with explicit input gaps."""
    task_dir = tmp_path / "p7-source"
    task_dir.mkdir()
    task = {
        "task_id": "p7-source-task-001",
        "stage": "P7",
        "calculation": "scf",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "model_id": "gamma-parent",
        "model_version": "v001",
        "method_set": "p7-source-method-v001",
        "scheduler_job_id": "p7-job-001" if result else None,
        "scheduler_state": "COMPLETED" if result else "DEFINED",
        "exit_code": "0:0" if result else None,
        "phonon_displacement": {
            "plan_id": "p7-source-plan-v001",
            "displacement_id": "reference",
        },
    }
    method = {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "stage": "scf",
        "model_id": "gamma-parent",
        "version": "v001",
        "method_set": "p7-source-method-v001",
        "suffix": "P7Source",
        "device": "gpu",
        "dft_functional": "PBE",
        "basis_type": "pw",
        "ks_solver": "cg",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "initial_moments_muB_by_element": {"Na": 0.0, "Cl": 0.0},
        "occupations": "fixed",
        "smearing_method": "fixed",
        "mixing_type": "broyden",
        "relax_method": "cg",
        "symmetry": 0,
        "element_order": ["Na", "Cl"],
        "kpoints": [2, 2, 2],
        "parameters": {
            "ecutwfc_Ry": 100,
            "scf_thr": 1.0e-4,
            "scf_nmax": 100,
            "nbands": 20,
            "smearing_sigma_Ry": None,
            "mixing_beta": 0.3,
            "force_thr_eV_per_A": None,
            "relax_nmax": None,
        },
        "pseudopotentials": {
            "Na": {"source": "/opt/Na.upf", "filename": "Na.upf"},
            "Cl": {"source": "/opt/Cl.upf", "filename": "Cl.upf"},
        },
        "pseudopotential_ids": {"Na": "Na-PBE-NC", "Cl": "Cl-PBE-NC"},
        "pseudopotential_metadata": {
            "Na": {
                "element": "Na",
                "functional": "PBE",
                "relativity": "scalar",
                "type": "ONCV_NC",
                "qualification": "input_compatibility_only",
            },
            "Cl": {
                "element": "Cl",
                "functional": "PBE",
                "relativity": "scalar",
                "type": "ONCV_NC",
                "qualification": "input_compatibility_only",
            },
        },
        "pseudopotential_treatment": {"Na": "scalar", "Cl": "scalar"},
        "net_charge": 0,
    }
    for key in missing_method_keys:
        method.pop(key)
    (task_dir / "task.json").write_text(json.dumps(task) + "\n", encoding="utf-8")
    (task_dir / "method.json").write_text(json.dumps(method) + "\n", encoding="utf-8")

    input_lines = [
        "INPUT_PARAMETERS",
        "device gpu",
        "calculation scf",
        "basis_type pw",
        "dft_functional PBE",
        "ecutwfc 100",
        "scf_thr 0.0001",
        "scf_nmax 100",
        "nbands 20",
    ]
    if requested_pw_diag_thr is not None:
        input_lines.append(f"pw_diag_thr {requested_pw_diag_thr}")
    (task_dir / "INPUT").write_text("\n".join(input_lines) + "\n", encoding="utf-8")
    if native_pw_diag_thr is not None:
        native_dir = task_dir / "OUT.P7Source"
        native_dir.mkdir()
        (native_dir / "INPUT").write_text(
            "INPUT_PARAMETERS\n"
            "calculation scf\n"
            f"pw_diag_thr {native_pw_diag_thr}\n",
            encoding="utf-8",
        )
    if kpt_offset is not None:
        (task_dir / "KPT").write_text(
            "K_POINTS\n0\nGamma\n2 2 2 "
            + " ".join(str(value) for value in kpt_offset)
            + "\n",
            encoding="utf-8",
        )
    if result:
        saved_result = {
            "task_id": task["task_id"],
            "method_set": task["method_set"],
            "scheduler_job_id": task["scheduler_job_id"],
            "model_id": task["model_id"],
            "model_version": task["model_version"],
        }
        (task_dir / "result.json").write_text(
            json.dumps(saved_result) + "\n", encoding="utf-8"
        )
    return task_dir


def test_native_gamma_method_source_uses_native_diag_and_task_kpt_offset(tmp_path):
    task_dir = _write_gamma_source_task(tmp_path, kpt_offset=(1, -1, 0))
    source = read_native_gamma_method_source(task_dir)

    assert source["schema"] == "mlcc.gamma-native-method-source.v1"
    assert source["method_identity"] == p5_method_identity(source["method_record"])
    assert source["method_record"]["kpoint_shift"] == [1, -1, 0]
    assert source["numerical_protocol"]["kpoint_shift"] == {
        "value": [1, -1, 0],
        "source_file": str((task_dir / "KPT").resolve()),
        "source_field": "offset",
        "scope": "requested_input",
    }
    assert source["numerical_protocol"]["pw_diag_thr"]["value"] == pytest.approx(2.0e-3)
    assert source["numerical_protocol"]["pw_diag_thr"]["scope"] == "native_echo"
    assert source["scientific_qualification"] is False
    assert source["complete_force_set_established"] is False


def test_native_gamma_method_source_accepts_explicit_p4_parent_reference(tmp_path):
    task_dir = _write_gamma_source_task(tmp_path)
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    task["stage"] = "P4"
    task.pop("phonon_displacement")
    (task_dir / "task.json").write_text(json.dumps(task) + "\n", encoding="utf-8")

    source = read_native_gamma_method_source(task_dir)

    assert source["reference_kind"] == "parent_reference"
    assert source["phonon_displacement"] is None


def test_native_gamma_method_source_records_requested_diag_and_missing_execution(tmp_path):
    task_dir = _write_gamma_source_task(
        tmp_path,
        requested_pw_diag_thr=None,
        native_pw_diag_thr=None,
        result=False,
    )
    source = read_native_gamma_method_source(task_dir)

    assert source["status"] == "unresolved_missing"
    assert source["method_identity"] is not None
    assert source["numerical_protocol"]["pw_diag_thr"]["value"] is None
    assert source["numerical_protocol"]["pw_diag_thr"]["scope"] == "unresolved_missing"
    assert "pw_diag_thr" in source["missing_fields"]
    assert "native_INPUT" in source["missing_fields"]
    assert "result.json" in source["missing_fields"]
    assert "scheduler_completed_0" in source["missing_fields"]


def test_native_gamma_method_source_uses_requested_diag_when_native_echo_absent(tmp_path):
    task_dir = _write_gamma_source_task(
        tmp_path,
        requested_pw_diag_thr=4.0e-3,
        native_pw_diag_thr=None,
    )
    source = read_native_gamma_method_source(task_dir)

    assert source["numerical_protocol"]["pw_diag_thr"]["value"] == pytest.approx(4.0e-3)
    assert source["numerical_protocol"]["pw_diag_thr"]["scope"] == "requested_input"


def test_native_gamma_method_source_compares_physical_identity_but_keeps_protocols(tmp_path):
    task_dir = _write_gamma_source_task(tmp_path)
    baseline = read_native_gamma_method_source(task_dir)
    expected_method = deepcopy(baseline["method_record"])
    expected_method["method_set"] = "cazro3-oncv-pbe-pw-berry-capability-v001"
    expected_method["pw_diag_thr"] = 1.0e-6
    expected_method["kpoints"] = [4, 4, 4]
    expected_method["kpoint_shift"] = [0, 0, 0]
    expected_method["parameters"]["scf_thr"] = 1.0e-6
    expected_method["parameters"]["scf_nmax"] = 200

    source = read_native_gamma_method_source(task_dir, expected_method=expected_method)
    comparison = source["requested_method_comparison"]
    assert comparison["same_physical_method"] is True
    assert comparison["numerical_protocols_equal"] is False
    assert comparison["original_methods"][1]["kpoints"] == [4, 4, 4]


def test_native_gamma_method_source_rejects_different_physical_xc(tmp_path):
    task_dir = _write_gamma_source_task(tmp_path)
    baseline = read_native_gamma_method_source(task_dir)
    expected_method = deepcopy(baseline["method_record"])
    expected_method["dft_functional"] = "PBEsol"

    with pytest.raises(ValueError, match="requested physical method differs"):
        read_native_gamma_method_source(task_dir, expected_method=expected_method)


def test_native_gamma_method_source_missing_physics_has_no_identity(tmp_path):
    task_dir = _write_gamma_source_task(
        tmp_path,
        missing_method_keys=("net_charge", "pseudopotential_treatment"),
    )
    source = read_native_gamma_method_source(task_dir)

    assert source["method_identity"] is None
    assert "method.net_charge" in source["missing_fields"]
    assert "method.pseudopotential_treatment" in source["missing_fields"]


def test_native_gamma_method_source_rejects_task_method_identity_mismatch(tmp_path):
    task_dir = _write_gamma_source_task(tmp_path)
    method = json.loads((task_dir / "method.json").read_text(encoding="utf-8"))
    method["model_id"] = "different-parent"
    (task_dir / "method.json").write_text(json.dumps(method) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="task/model/method identity"):
        read_native_gamma_method_source(task_dir)


def test_native_gamma_method_source_rejects_result_scheduler_identity_mismatch(tmp_path):
    task_dir = _write_gamma_source_task(tmp_path, result=True)
    result = json.loads((task_dir / "result.json").read_text(encoding="utf-8"))
    result["scheduler_job_id"] = "different-job"
    (task_dir / "result.json").write_text(json.dumps(result) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="saved result scheduler_job_id differs"):
        read_native_gamma_method_source(task_dir)


def test_native_gamma_method_source_missing_kpt_is_unresolved(tmp_path):
    task_dir = _write_gamma_source_task(tmp_path, kpt_offset=None)
    source = read_native_gamma_method_source(task_dir)

    assert source["status"] == "unresolved_missing"
    assert source["source_files"]["KPT"] is None
    assert source["numerical_protocol"]["kpoints"]["value"] is None
    assert source["numerical_protocol"]["kpoint_shift"]["value"] is None
    assert "kpoints" in source["missing_fields"]
    assert "kpoint_shift" in source["missing_fields"]
