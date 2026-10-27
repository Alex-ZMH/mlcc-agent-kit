from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import write

from mlcc.qualification import compare_cutoff_tasks


def _method(ecut: float, *, nspin: int = 2) -> dict:
    return {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "stage": "scf",
        "model_id": "fixture-model",
        "version": "v001",
        "suffix": "NiPW",
        "device": "gpu",
        "dft_functional": "PBE",
        "basis_type": "pw",
        "ks_solver": "cg",
        "nspin": nspin,
        "initial_magnetic_moment_muB_per_atom": 0.6,
        "smearing_method": "gauss",
        "element_order": ["Ni"],
        "kpoints": [9, 9, 9],
        "kpoint_rule": "ceil(30 Angstrom / each cell-vector length)",
        "parameters": {
            "ecutwfc_Ry": ecut,
            "scf_thr": 1e-8,
            "scf_nmax": 100,
            "nbands": 56,
            "smearing_sigma_Ry": 0.007349864494991328,
            "mixing_beta": 0.3,
            "force_thr_eV_per_A": 0.02,
            "relax_nmax": 40,
        },
        "pseudopotentials": {
            "Ni": {
                "source": "/home/v100/abacus-work/PPORBs/pseudopotentials/Ni_ONCV_PBE-1.2.upf",
                "filename": "Ni_ONCV_PBE-1.2.upf",
            }
        },
        "potential": {
            "remote_file": "/home/v100/abacus-work/PPORBs/pseudopotentials/Ni_ONCV_PBE-1.2.upf",
            "element": "Ni",
            "type": "ONCV_NC",
            "functional": "PBE",
            "valence_electrons_per_atom": 18,
            "relativity": "scalar",
            "has_spin_orbit": False,
            "qualification": "candidate_for_engineering_tests_only",
        },
        "stress_convention": {
            "input_output_unit": "raw ABACUS output kBar",
            "converted_unit": "GPa",
            "conversion": "0.1 * raw kBar",
            "sign": "abacus_printed",
            "sign_calibration": "pending_finite_strain_check",
        },
        "method_set": "ni-oncv-pbe18-pw-engineering-v001",
        "fixture": True,
        "case": "scf" if ecut == 100.0 else "cutoff120",
    }


def _result(energy: float, force: float = 0.0, stress: float = 0.0, *, task_id: str = "baseline") -> dict:
    return {
        "task_id": task_id,
        "method_set": "ni-oncv-pbe18-pw-engineering-v001",
        "energy_eV": energy,
        "energy_unit": "eV",
        "stress_unit": "GPa",
        "energy_definition": "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham at the selected finite smearing",
        "energy_default_definition": "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham finite-smearing free energy in eV",
        "forces_eV_per_A": [[force, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        "stress_GPa": [[stress, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        "stress_sign": "abacus_printed",
        "atom_ids": [0, 1, 2, 3],
        "electronic_converged": True,
        "stage": "scf",
    }


def _write_bundle(root: Path, name: str, ecut: float, *, nspin: int = 2) -> Path:
    directory = root / name
    directory.mkdir()
    atoms = Atoms(
        symbols=["Ni", "Ni", "Ni", "Ni"],
        positions=[[0.0, 0.0, 0.0], [0.0, 1.76, 1.76], [1.76, 0.0, 1.76], [1.76, 1.76, 0.0]],
        cell=np.diag([3.52, 3.52, 3.52]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.arange(4, dtype=int))
    write(directory / "input.extxyz", atoms, format="extxyz")
    (directory / "method.json").write_text(json.dumps(_method(ecut, nspin=nspin)) + "\n", encoding="utf-8")
    (directory / "INPUT").write_text(
        "INPUT_PARAMETERS\n"
        f"ecutwfc {int(ecut)}\n"
        "cal_force 1\n"
        "cal_stress 1\n"
        "device gpu\n",
        encoding="utf-8",
    )
    (directory / "task.json").write_text(
        json.dumps(
            {
                "task_id": name,
                "engine": "abacus",
                "engine_version": "3.10.1",
                "method_set": "ni-oncv-pbe18-pw-engineering-v001",
                "scheduler_state": "COMPLETED",
                "exit_code": "0:0",
                "scheduler_job_id": name,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "result.json").write_text(json.dumps(_result(-10.0, task_id=name)) + "\n", encoding="utf-8")
    return directory


def _write_method_config(root: Path) -> Path:
    path = root / "h1-method.json"
    path.write_text(
        json.dumps(
            {
                "method_set": "ni-oncv-pbe18-pw-engineering-v001",
                "engine": "abacus",
                "engine_version": "3.10.1",
                "parameters": {"ecutwfc_Ry": 100, "cutoff_comparison_Ry": 120},
                "predeclared_engineering_thresholds": {
                    "cutoff_energy_eV_per_atom": 0.01,
                    "cutoff_force_component_eV_per_A": 0.03,
                    "cutoff_stress_component_GPa": 0.5,
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_same_geometry_abacus_cutoff_passes(tmp_path: Path):
    baseline = _write_bundle(tmp_path, "baseline", 100.0)
    comparison = _write_bundle(tmp_path, "comparison", 120.0)
    config = _write_method_config(tmp_path)
    baseline_method = json.loads((baseline / "method.json").read_text(encoding="utf-8"))
    baseline_method["parameters"].update(cal_force=True, cal_stress=True)
    (baseline / "method.json").write_text(json.dumps(baseline_method) + "\n", encoding="utf-8")
    result = json.loads((comparison / "result.json").read_text(encoding="utf-8"))
    result["energy_eV"] = -9.98
    result["forces_eV_per_A"][0][0] = 0.01
    result["stress_GPa"][0][0] = 0.1
    (comparison / "result.json").write_text(json.dumps(result) + "\n", encoding="utf-8")

    report = compare_cutoff_tasks(baseline, comparison, config)

    assert report["overall"] is True
    assert report["cutoff_qualification"] is True
    assert report["h1_qualification"] is False
    assert report["production_qualification"] is False
    assert report["checks"]["only_ecutwfc_changed"]["passed"] is True
    assert report["checks"]["energy_per_atom"]["passed"] is True
    assert report["checks"]["force_component"]["passed"] is True
    assert report["checks"]["stress_component"]["passed"] is True
    assert report["checks"]["native_input_verified"]["passed"] is True


def test_parameter_mismatch_blocks_cutoff_qualification(tmp_path: Path):
    baseline = _write_bundle(tmp_path, "baseline", 100.0)
    comparison = _write_bundle(tmp_path, "comparison", 120.0, nspin=1)
    config = _write_method_config(tmp_path)

    report = compare_cutoff_tasks(baseline, comparison, config)

    assert report["overall"] is False
    assert report["checks"]["same_spin"]["passed"] is False
    assert report["checks"]["only_ecutwfc_changed"]["passed"] is False
    assert report["checks"]["energy_per_atom"]["value"]["status"] == "not_comparable"


def test_physical_threshold_failure_blocks_cutoff_qualification(tmp_path: Path):
    baseline = _write_bundle(tmp_path, "baseline", 100.0)
    comparison = _write_bundle(tmp_path, "comparison", 120.0)
    config = _write_method_config(tmp_path)
    result = _result(-9.8, force=0.04, stress=0.6, task_id="comparison")
    (comparison / "result.json").write_text(json.dumps(result) + "\n", encoding="utf-8")

    report = compare_cutoff_tasks(baseline, comparison, config)

    assert report["overall"] is False
    assert report["checks"]["energy_per_atom"]["passed"] is False
    assert report["checks"]["force_component"]["passed"] is False
    assert report["checks"]["stress_component"]["passed"] is False
    assert report["checks"]["stress_component"]["value"]["stress_sign"] == {
        "baseline": "abacus_printed",
        "comparison": "abacus_printed",
    }


def test_native_cal_force_mismatch_blocks_comparison(tmp_path: Path):
    baseline = _write_bundle(tmp_path, "baseline", 100.0)
    comparison = _write_bundle(tmp_path, "comparison", 120.0)
    config = _write_method_config(tmp_path)
    input_path = comparison / "INPUT"
    input_path.write_text(input_path.read_text(encoding="utf-8").replace("cal_force 1", "cal_force 0"), encoding="utf-8")

    report = compare_cutoff_tasks(baseline, comparison, config)

    assert report["overall"] is False
    assert report["native_input_verified"] is False
    assert report["checks"]["native_input_verified"]["passed"] is False
    assert report["checks"]["energy_per_atom"]["value"]["status"] == "not_comparable"


def test_real_job32_job35_native_inputs_regression():
    root = Path(__file__).resolve().parents[2]
    baseline = root / "workspace/tasks/h1-ni-scf-v001"
    comparison = root / "workspace/tasks/h1-ni-cutoff120-v001"
    config = root / "workspace/configs/h1-abacus-method-v001.json"
    if not all(path.is_dir() for path in (baseline, comparison)):
        import pytest

        pytest.skip("retained real job 32/35 task directories are unavailable")

    report = compare_cutoff_tasks(baseline, comparison, config)

    assert report["job_ids"] == {"baseline": "32", "comparison": "35"}
    assert report["native_input_verified"] is True
    assert report["checks"]["native_input_verified"]["passed"] is True
    assert report["overall"] is True

