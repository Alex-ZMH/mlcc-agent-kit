"""Contract-only checks for the native raw Gamma delivery reader.

The fixture is explicitly software_contract_only.  It exercises source
binding, raw matrix preservation and rejection of an altered native record;
it is not a CZO result or a scientific qualification test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.dielectric_response import read_native_gamma_force
from mlcc.modeling import write_model_artifacts


CONTRACT_EVIDENCE = "software_contract_only"
ABACUS_VERSION = "3.10.1"


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _method(model_id: str) -> dict:
    return {
        "engine": "abacus",
        "abacus_version_target": ABACUS_VERSION,
        "stage": "scf",
        "method_set": "czo-native-gamma-contract",
        "basis_type": "lcao",
        "dft_functional": "PBE",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "element_order": ["Ca", "Zr"],
        "initial_moments_muB_by_element": {"Ca": 0.0, "Zr": 0.0},
        "pseudopotential_ids": {"Ca": "Ca.contract.upf", "Zr": "Zr.contract.upf"},
        "pseudopotential_metadata": {
            "Ca": {"source": CONTRACT_EVIDENCE},
            "Zr": {"source": CONTRACT_EVIDENCE},
        },
        "pseudopotential_treatment": {"Ca": "contract", "Zr": "contract"},
        "net_charge": 0,
        "parameters": {"smearing_sigma_Ry": None},
        "kpoints": [1, 1, 1],
        "kpoint_shift": [0, 0, 0],
        "orbital_files": {"Ca": "Ca.contract.orb", "Zr": "Zr.contract.orb"},
        "orbital_metadata": {
            "Ca": {"source": CONTRACT_EVIDENCE},
            "Zr": {"source": CONTRACT_EVIDENCE},
        },
        "model_id": model_id,
        "version": "v001",
        "suffix": "CZO_CONTRACT",
    }


def _atom_map(model_id: str) -> dict:
    return {
        "schema": "mlcc.abacus-atom-map.v1",
        "abacus_version_target": ABACUS_VERSION,
        "model_id": model_id,
        "version": "v001",
        "source_atom_ids": [0, 1],
        "abacus_order": [
            {"abacus_index": 0, "source_index": 0, "atom_id": 0, "element": "Ca", "label": "Ca1"},
            {"abacus_index": 1, "source_index": 1, "atom_id": 1, "element": "Zr", "label": "Zr1"},
        ],
    }


def _native_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    model_id = "czo-native-gamma-contract-model"
    model_path = tmp_path / "model"
    atoms = Atoms(
        symbols=["Ca", "Zr"],
        positions=[[0.0, 0.0, 0.0], [2.0, 2.0, 2.0]],
        cell=np.diag([4.0, 4.0, 4.0]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([0, 1], dtype=int))
    write_model_artifacts(
        atoms,
        model_path,
        model_id=model_id,
        version="v001",
        fixture=True,
        fixture_purpose=CONTRACT_EVIDENCE,
        material="CaZrO3",
        source_path=CONTRACT_EVIDENCE,
    )

    parent_study = _write(tmp_path / "parent-study.json", {"study_id": "czo-contract-study"})
    task_root = tmp_path / "tasks"
    reference_root = task_root / "reference"
    displacement_root = task_root / "displacement-001"
    method = _method(model_id)
    reference_task = {
        "task_id": "czo-contract-reference",
        "stage": "P5",
        "calculation": "scf",
        "study_id": "czo-contract-study",
        "case_id": "czo-contract-case",
        "case_role": "software_contract_only",
        "engine": "abacus",
        "engine_version": ABACUS_VERSION,
        "basis_type": "lcao",
        "model_id": model_id,
        "model_version": "v001",
        "model_path": str(model_path.resolve()),
        "method_set": method["method_set"],
        "method_file": str((reference_root / "method.json").resolve()),
        "study_file": str(parent_study.resolve()),
        "runner": "slurm",
        "scheduler_job_id": "269-contract",
        "scheduler_state": "COMPLETED",
        "status": "COMPLETED",
        "exit_code": "0:0",
    }
    displacement_task = {
        "task_id": "czo-contract-displacement-001",
        "stage": "P5",
        "calculation": "scf",
        "study_id": "czo-contract-displacement-study",
        "case_id": reference_task["case_id"],
        "case_role": reference_task["case_role"],
        "engine": "abacus",
        "engine_version": ABACUS_VERSION,
        "basis_type": "lcao",
        "model_id": model_id,
        "model_version": "v001",
        "model_path": str(model_path.resolve()),
        "parent_model_id": model_id,
        "parent_model_version": "v001",
        "parent_study_id": reference_task["study_id"],
        "method_set": method["method_set"],
        "method_file": str((displacement_root / "method.json").resolve()),
        "study_file": str((displacement_root / "study.json").resolve()),
        "runner": "slurm",
        "scheduler_job_id": "284-contract",
        "scheduler_state": "COMPLETED",
        "status": "COMPLETED",
        "exit_code": "0:0",
    }
    for root, task in ((reference_root, reference_task), (displacement_root, displacement_task)):
        _write(root / "task.json", task)
        _write(root / "method.json", method)
        _write(root / "result.json", {"task_id": task["task_id"], "scheduler_job_id": task["scheduler_job_id"]})
        _write(root / "electronic.json", {"task_id": task["task_id"]})
        _write(root / "STRU.atom-map.json", _atom_map(model_id))
        (root / "STRU").write_text(f"{CONTRACT_EVIDENCE}\n", encoding="utf-8")
        (root / "KPT").write_text("K_POINTS\n0\nGamma\n1 1 1 0 0 0\n", encoding="utf-8")
        if root == displacement_root:
            _write(root / "study.json", {"study_id": displacement_task["study_id"]})

    raw_path = tmp_path / "raw-gamma-result.json"
    manifest = _write(tmp_path / "displacement-manifest.json", {"contract": CONTRACT_EVIDENCE})
    phonopy_yaml = tmp_path / "phonopy_disp.yaml"
    phonopy_yaml.write_text(f"{CONTRACT_EVIDENCE}\n", encoding="utf-8")
    postprocess_file = _write(
        tmp_path / "gamma-postprocess-task.json",
        {
            "schema": "mlcc.native-postprocess-task.v1",
            "task_id": "czo-contract-gamma-postprocess",
            "engine": "phonopy",
            "engine_version": "4.8.3-contract",
            "runner": "slurm",
            "scheduler_job_id": "345-contract",
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "study_id": reference_task["study_id"],
            "model_id": model_id,
            "model_version": "v001",
            "result_file": str(raw_path.resolve()),
            "version_observation": "post-run contract observation",
        },
    )
    raw_hessian = np.zeros((6, 6), dtype=float).tolist()
    raw_hessian[0][1] = 2.0
    raw_hessian[1][0] = 1.0
    entry = {
        "task_id": displacement_task["task_id"],
        "scheduler_job_id": displacement_task["scheduler_job_id"],
        "task_root": str(displacement_root.resolve()),
        "atom_index": 0,
        "source_atom_id": 0,
        "sign": "+",
    }
    raw = {
        "schema": "mlcc.czo-native-raw-gamma-force.v001",
        "status": "raw_force_chain_complete_unqualified",
        "scope": "Gamma force-only finite-displacement response",
        "units": {
            "displacement": "angstrom",
            "force": "eV/angstrom",
            "force_constants": "eV/angstrom^2",
            "hessian": "eV/angstrom^2",
        },
        "force_constants_convention": "Phonopy [displaced atom, force atom, displaced component, force component]",
        "hessian_convention": "H[(displaced_atom,displaced_component),(force_atom,force_component)]",
        "provenance": {
            "manifest": str(manifest.resolve()),
            "ensemble_root": str(task_root.resolve()),
            "phonopy_displacement_yaml": str(phonopy_yaml.resolve()),
            "reference_task_root": str(reference_root.resolve()),
            "reference_task_id": reference_task["task_id"],
            "reference_scheduler_job_id": reference_task["scheduler_job_id"],
            "method_set": method["method_set"],
            "engine": "abacus",
            "engine_version": ABACUS_VERSION,
            "reference_model": {
                "model_id": model_id,
                "version": "v001",
                "path": str(model_path.resolve()),
            },
            "parent_study": {
                "study_id": reference_task["study_id"],
                "case_id": reference_task["case_id"],
                "case_role": reference_task["case_role"],
                "path": str(parent_study.resolve()),
            },
            "method_physical_signature": {"source": CONTRACT_EVIDENCE},
            "atom_map": {
                "reference": str((reference_root / "STRU.atom-map.json").resolve()),
                "source_atom_ids": [0, 1],
                "source_symbols": ["Ca", "Zr"],
                "abacus_order": _atom_map(model_id)["abacus_order"],
            },
            "task_count": 1,
            "tasks": [entry],
            "postprocess_task_file": str(postprocess_file.resolve()),
        },
        "assembly": {
            "asr_applied": False,
            "reciprocity_projection_applied": False,
            "hermitian_projection_applied": False,
            "nac_applied": False,
            "born_or_dipole_constructed": False,
            "dipoles_constructed": False,
            "born_charges_constructed": False,
            "raw_measured_forces_retained": True,
            "reference_force_subtraction": True,
        },
        "qualification": {
            "scientific_qualification": False,
            "production_qualification": False,
        },
        "reference": {
            "task_id": reference_task["task_id"],
            "scheduler_job_id": reference_task["scheduler_job_id"],
            "result_file": str((reference_root / "result.json").resolve()),
            "electronic_file": str((reference_root / "electronic.json").resolve()),
            "method_file": str((reference_root / "method.json").resolve()),
            "reference_native_converged": True,
        },
        "displacements": [
            {
                **entry,
                "element": "Ca",
                "direction": 0,
                "vector_A": [0.01, 0.0, 0.0],
                "result_file": str((displacement_root / "result.json").resolve()),
                "electronic_file": str((displacement_root / "electronic.json").resolve()),
                "method_file": str((displacement_root / "method.json").resolve()),
                "study_file": str((displacement_root / "study.json").resolve()),
                "model_file": str((model_path / "model.json").resolve()),
            }
        ],
        "raw_force_constants_eV_A2": np.zeros((2, 2, 3, 3), dtype=float).tolist(),
        "raw_hessian_eV_A2": raw_hessian,
        "diagnostics": {"source": CONTRACT_EVIDENCE},
        "gamma_analysis": {
            "characteristic_status": "unresolved_raw_nonsymmetric",
            "symmetrization_applied": False,
        },
    }
    _write(raw_path, raw)
    return raw_path, displacement_root, postprocess_file


def test_native_gamma_reader_preserves_raw_nonsymmetric_matrix(tmp_path: Path):
    raw_path, _, _ = _native_fixture(tmp_path)
    product = read_native_gamma_force(raw_path)
    assert product["schema"] == "mlcc.gamma-force-constants.v1"
    assert product["provenance_kind"] == "native_derived"
    assert product["source"]["source_mode"] == "native_source_bound"
    np.testing.assert_array_equal(
        np.asarray(product["matrix_eV_per_A2"], dtype=float),
        np.asarray(product["raw_product"]["raw_hessian_eV_A2"], dtype=float),
    )
    assert product["matrix_eV_per_A2"][0][1] == 2.0
    assert product["matrix_eV_per_A2"][1][0] == 1.0
    assert product["status"] == "unresolved"
    assert "raw_gamma_characteristic_status_unresolved_raw_nonsymmetric" in product["unresolved_reasons"]
    assert [job["role"] for job in product["native_jobs"]] == [
        "reference_scf",
        "gamma_displacement",
        "gamma_postprocess",
    ]


def test_native_gamma_reader_rejects_projection_flag(tmp_path: Path):
    raw_path, _, _ = _native_fixture(tmp_path)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["assembly"]["asr_applied"] = True
    _write(raw_path, raw)
    with pytest.raises(ValueError, match="asr_applied"):
        read_native_gamma_force(raw_path)


def test_native_gamma_reader_rejects_displacement_job_mismatch(tmp_path: Path):
    raw_path, displacement_root, _ = _native_fixture(tmp_path)
    task = json.loads((displacement_root / "task.json").read_text(encoding="utf-8"))
    task["scheduler_job_id"] = "wrong-job"
    _write(displacement_root / "task.json", task)
    with pytest.raises(ValueError, match="scheduler_job_id"):
        read_native_gamma_force(raw_path)
