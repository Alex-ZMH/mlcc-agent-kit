from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.io import write

from mlcc.strain import EV_PER_A3_TO_GPA, compare_strain_tasks, isotropic_strain_model


def _atoms() -> Atoms:
    atoms = Atoms(
        symbols=["Ni", "Ni", "Ni", "Ni"],
        positions=[[0.03, 0.0, 0.0], [0.0, 1.76, 1.76], [1.76, 0.0, 1.76], [1.76, 1.76, 0.0]],
        cell=np.diag([3.52, 3.52, 3.52]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.arange(4, dtype=int))
    return atoms


def _method(method_set: str, *, new_schema: bool = False, version: str | None = None) -> dict:
    method = {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "stage": "scf",
        "model_id": "ni-fcc-engineering",
        "version": version or ("v002" if new_schema else "v001"),
        "suffix": "NiPW",
        "device": "gpu",
        "dft_functional": "PBE",
        "basis_type": "pw",
        "ks_solver": "cg",
        "nspin": 2,
        "initial_magnetic_moment_muB_per_atom": 0.6,
        "smearing_method": "gauss",
        "element_order": ["Ni"],
        "kpoints": [2, 2, 2],
        "kpoint_rule": "explicit_mesh",
        "parameters": {
            "ecutwfc_Ry": 100,
            "scf_thr": 1e-8,
            "scf_nmax": 100,
            "nbands": 56,
            "smearing_sigma_Ry": 0.007349864494991328,
            "mixing_beta": 0.3,
            "force_thr_eV_per_A": 0.02,
            "relax_nmax": 40,
            "cal_force": True,
            "cal_stress": True,
        },
        "pseudopotentials": {"Ni": {"filename": "Ni_ONCV_PBE-1.2.upf"}},
        "potential": {"element": "Ni", "type": "ONCV_NC", "functional": "PBE", "valence_electrons_per_atom": 18},
        "stress_convention": {"input_output_unit": "raw ABACUS output kBar", "converted_unit": "GPa", "sign": "abacus_printed"},
        "method_set": method_set,
    }
    if new_schema:
        method["version"] = "v002"
        method.pop("initial_magnetic_moment_muB_per_atom")
        method["initial_moments_muB_by_element"] = {"Ni": 0.6}
        method["occupations"] = "smearing"
        method["mixing_type"] = "broyden"
        method["relax_method"] = "cg"
        method["symmetry"] = 0
        method["execution"] = {"device": "gpu", "ks_solver": "cg"}
        method["science"] = {"initial_moments_muB_by_element": {"Ni": 0.6}, "occupations": "smearing"}
        method.pop("potential")
    return method


def _result(task_id: str, method_set: str, energy: float, stress_trace: float, sigma0: float, job_id: str) -> dict:
    return {
        "task_id": task_id,
        "scheduler_job_id": job_id,
        "method_set": method_set,
        "stage": "scf",
        "energy_eV": energy,
        "energy_unit": "eV",
        "energy_default_definition": "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham finite-smearing free energy in eV",
        "energy_definition": "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham at the selected finite smearing",
        "energy_sigma0_eV": sigma0,
        "forces_eV_per_A": [[0.0, 0.0, 0.0]] * 4,
        "stress_GPa": np.eye(3).tolist() if stress_trace == 3.0 else (np.eye(3) * (stress_trace / 3.0)).tolist(),
        "stress_unit": "GPa",
        "stress_sign": "abacus_printed",
        "atom_ids": [0, 1, 2, 3],
        "electronic_converged": True,
    }


def _write_task(
    root: Path,
    name: str,
    epsilon: float,
    method_set: str,
    *,
    suffix: str,
    energy: float,
    stress_trace: float,
    sigma0: float,
    job_id: str,
    method_version: str | None = None,
) -> Path:
    path = root / name
    path.mkdir()
    atoms, _ = isotropic_strain_model(_atoms(), epsilon, reference_model="ni-fcc-engineering/v001")
    write(path / "input.extxyz", atoms, format="extxyz")
    method = _method(method_set, new_schema=epsilon != 0, version=method_version)
    method["suffix"] = suffix
    method["case"] = "scf" if epsilon == 0 else "strainminus" if epsilon < 0 else "strainplus"
    (path / "method.json").write_text(json.dumps(method) + "\n", encoding="utf-8")
    (path / "INPUT").write_text(
        "INPUT_PARAMETERS\n"
        f"suffix {suffix}\n"
        "device gpu\n"
        "dft_functional PBE\n"
        "basis_type pw\n"
        "ks_solver cg\n"
        "ecutwfc 100\n"
        "scf_thr 1e-08\n"
        "scf_nmax 100\n"
        "nbands 56\n"
        "nspin 2\n"
        "smearing_method gauss\n"
        "smearing_sigma 0.00734986449499\n"
        "mixing_type broyden\n"
        "mixing_beta 0.3\n"
        "symmetry 0\n"
        "cal_force 1\n"
        "cal_stress 1\n",
        encoding="utf-8",
    )
    (path / "KPT").write_text("K_POINTS\n0\nGamma\n2 2 2 0 0 0\n", encoding="utf-8")
    (path / "running_scf.log").write_text("ABACUS native source fixture\n", encoding="utf-8")
    task = {
        "task_id": name,
        "stage": "P4",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "model_id": "ni-fcc-engineering",
        "model_version": "v001",
        "method_set": method_set,
        "scheduler_job_id": job_id,
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
    }
    (path / "task.json").write_text(json.dumps(task) + "\n", encoding="utf-8")
    result = _result(name, method_set, energy, stress_trace, sigma0, job_id)
    result["source_files"] = {"running_scf.log": "running_scf.log"}
    (path / "result.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
    return path


def _write_method_config(
    root: Path,
    *,
    method_set: str = "ni-oncv-pbe18-pw-strain-v002",
    parent_method_set: str = "ni-oncv-pbe18-pw-engineering-v001",
    filename: str = "h1-abacus-method-v002.json",
) -> Path:
    path = root / filename
    path.write_text(
        json.dumps(
            {
                "method_set": method_set,
                "parent_method_set": parent_method_set,
                "engine": "abacus",
                "engine_version": "3.10.1",
                "kpoints": [2, 2, 2],
                "parameters": {"ecutwfc_Ry": 100},
                "predeclared_engineering_thresholds": {
                    "strain_step": 0.005,
                    "strain_derivative_stress_trace_GPa": 1.0,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_isotropic_strain_model_preserves_fractional_coordinates(tmp_path: Path):
    reference = _atoms()
    derived, record = isotropic_strain_model(reference, 0.005, reference_model="ni-fcc-engineering/v001")

    assert record["reference_model"] == "ni-fcc-engineering/v001"
    assert record["F"] == np.diag([1.005, 1.005, 1.005]).tolist()
    assert record["reference_volume_A3"] == reference.get_volume()
    np.testing.assert_allclose(derived.get_scaled_positions(wrap=False), reference.get_scaled_positions(wrap=False), rtol=0, atol=1e-12)
    np.testing.assert_allclose(derived.cell.array, reference.cell.array * 1.005, rtol=0, atol=1e-12)


def test_compare_strain_uses_finite_smearing_energy_and_allows_suffix_label(tmp_path: Path):
    config = _write_method_config(tmp_path)
    V0 = _atoms().get_volume()
    h = 0.005
    derivative = 2.0
    delta = derivative * 2 * h * V0 / EV_PER_A3_TO_GPA
    minus = _write_task(tmp_path, "minus", -h, "ni-oncv-pbe18-pw-strain-v002", suffix="NiPWStrain", energy=-10.0 - delta / 2, stress_trace=2.0, sigma0=-100.0, job_id="41")
    reference = _write_task(tmp_path, "reference", 0.0, "ni-oncv-pbe18-pw-engineering-v001", suffix="NiPW", energy=-10.0, stress_trace=2.0, sigma0=-100.0, job_id="32")
    plus = _write_task(tmp_path, "plus", h, "ni-oncv-pbe18-pw-strain-v002", suffix="NiPWStrain", energy=-10.0 + delta / 2, stress_trace=2.0, sigma0=100.0, job_id="42")

    report = compare_strain_tasks(minus, reference, plus, config)

    assert report["overall"] is True
    assert report["physics_comparable"] is True
    assert report["temperature_K"] is None
    assert report["energy_derivative_trace_GPa"] == pytest.approx(2.0, abs=1e-12)
    assert report["sign_candidates"]["printed_trace"]["passed"] is True
    assert report["sign_candidates"]["negative_printed_trace"]["passed"] is False
    assert report["passing_sign_candidates"] == ["printed_trace"]
    assert report["energy_definition"]["field"] == "energy_eV"
    assert report["suffix_labels"] == {"minus": "NiPWStrain", "reference": "NiPW", "plus": "NiPWStrain"}


def test_compare_strain_accepts_explicit_2x2x2_parent_child_versions(tmp_path: Path):
    config = _write_method_config(
        tmp_path,
        method_set="ni-oncv-pbe18-pw-capability-v004",
        parent_method_set="ni-oncv-pbe18-pw-capability-v003",
        filename="h1-abacus-method-v004.json",
    )
    V0 = _atoms().get_volume()
    h = 0.005
    derivative = 2.0
    delta = derivative * 2 * h * V0 / EV_PER_A3_TO_GPA
    minus = _write_task(
        tmp_path,
        "minus",
        -h,
        "ni-oncv-pbe18-pw-capability-v004",
        suffix="NiPWStrain",
        energy=-10.0 - delta / 2,
        stress_trace=2.0,
        sigma0=-100.0,
        job_id="51",
        method_version="v004",
    )
    reference = _write_task(
        tmp_path,
        "reference",
        0.0,
        "ni-oncv-pbe18-pw-capability-v003",
        suffix="NiPW",
        energy=-10.0,
        stress_trace=2.0,
        sigma0=-100.0,
        job_id="37",
        method_version="v003",
    )
    plus = _write_task(
        tmp_path,
        "plus",
        h,
        "ni-oncv-pbe18-pw-capability-v004",
        suffix="NiPWStrain",
        energy=-10.0 + delta / 2,
        stress_trace=2.0,
        sigma0=-100.0,
        job_id="52",
        method_version="v004",
    )

    report = compare_strain_tasks(minus, reference, plus, config)

    assert report["overall"] is True
    assert report["physics_comparable"] is True
    assert report["method_set"] == {
        "reference": "ni-oncv-pbe18-pw-capability-v003",
        "strain": "ni-oncv-pbe18-pw-capability-v004",
    }
    assert report["kpoints"]["native"]["reference"] == {"grid": [2, 2, 2], "offset": [0, 0, 0]}
    assert report["checks"]["same_native_kpoints"]["passed"] is True


def test_compare_strain_rejects_native_kpt_offset_mismatch(tmp_path: Path):
    config = _write_method_config(
        tmp_path,
        method_set="ni-oncv-pbe18-pw-capability-v004",
        parent_method_set="ni-oncv-pbe18-pw-capability-v003",
        filename="h1-abacus-method-v004.json",
    )
    V0 = _atoms().get_volume()
    h = 0.005
    delta = 2.0 * 2 * h * V0 / EV_PER_A3_TO_GPA
    minus = _write_task(
        tmp_path,
        "minus",
        -h,
        "ni-oncv-pbe18-pw-capability-v004",
        suffix="NiPWStrain",
        energy=-10.0 - delta / 2,
        stress_trace=2.0,
        sigma0=-10.0,
        job_id="51",
        method_version="v004",
    )
    reference = _write_task(
        tmp_path,
        "reference",
        0.0,
        "ni-oncv-pbe18-pw-capability-v003",
        suffix="NiPW",
        energy=-10.0,
        stress_trace=2.0,
        sigma0=-10.0,
        job_id="37",
        method_version="v003",
    )
    plus = _write_task(
        tmp_path,
        "plus",
        h,
        "ni-oncv-pbe18-pw-capability-v004",
        suffix="NiPWStrain",
        energy=-10.0 + delta / 2,
        stress_trace=2.0,
        sigma0=-10.0,
        job_id="52",
        method_version="v004",
    )
    (plus / "KPT").write_text("K_POINTS\n0\nGamma\n2 2 2 1 0 0\n", encoding="utf-8")

    report = compare_strain_tasks(minus, reference, plus, config)

    assert report["overall"] is False
    assert report["physics_comparable"] is False
    assert report["checks"]["same_native_kpoints"]["passed"] is False
    assert report["energy_derivative_trace_GPa"] is None


def test_compare_strain_requires_complete_native_source_evidence(tmp_path: Path):
    config = _write_method_config(tmp_path)
    V0 = _atoms().get_volume()
    h = 0.005
    delta = 2.0 * 2 * h * V0 / EV_PER_A3_TO_GPA
    minus = _write_task(
        tmp_path,
        "minus",
        -h,
        "ni-oncv-pbe18-pw-strain-v002",
        suffix="NiPWStrain",
        energy=-10.0 - delta / 2,
        stress_trace=2.0,
        sigma0=-10.0,
        job_id="41",
    )
    reference = _write_task(
        tmp_path,
        "reference",
        0.0,
        "ni-oncv-pbe18-pw-engineering-v001",
        suffix="NiPW",
        energy=-10.0,
        stress_trace=2.0,
        sigma0=-10.0,
        job_id="32",
    )
    plus = _write_task(
        tmp_path,
        "plus",
        h,
        "ni-oncv-pbe18-pw-strain-v002",
        suffix="NiPWStrain",
        energy=-10.0 + delta / 2,
        stress_trace=2.0,
        sigma0=-10.0,
        job_id="42",
    )
    (plus / "running_scf.log").unlink()

    report = compare_strain_tasks(minus, reference, plus, config)

    assert report["overall"] is False
    assert report["physics_comparable"] is False
    assert report["energy_derivative_trace_GPa"] is None
    assert report["checks"]["native_source_evidence"]["passed"] is False
    assert report["source_evidence"]["plus"]["reason"] == "missing_source_files"


def test_compare_strain_rejects_physical_native_input_mismatch(tmp_path: Path):
    config = _write_method_config(tmp_path)
    V0 = _atoms().get_volume()
    h = 0.005
    delta = 2.0 * 2 * h * V0 / EV_PER_A3_TO_GPA
    minus = _write_task(tmp_path, "minus", -h, "ni-oncv-pbe18-pw-strain-v002", suffix="NiPWStrain", energy=-10.0 - delta / 2, stress_trace=2.0, sigma0=-10.0, job_id="41")
    reference = _write_task(tmp_path, "reference", 0.0, "ni-oncv-pbe18-pw-engineering-v001", suffix="NiPW", energy=-10.0, stress_trace=2.0, sigma0=-10.0, job_id="32")
    plus = _write_task(tmp_path, "plus", h, "ni-oncv-pbe18-pw-strain-v002", suffix="NiPWStrain", energy=-10.0 + delta / 2, stress_trace=2.0, sigma0=-10.0, job_id="42")
    (plus / "INPUT").write_text((plus / "INPUT").read_text(encoding="utf-8").replace("smearing_sigma 0.00734986449499", "smearing_sigma 0.008"), encoding="utf-8")

    report = compare_strain_tasks(minus, reference, plus, config)

    assert report["overall"] is False
    assert report["physics_comparable"] is False
    assert report["checks"]["same_native_input_physics"]["passed"] is False
    assert report["energy_derivative_trace_GPa"] is None
    assert report["sign_candidates"]["printed_trace"]["passed"] is False


def test_compare_strain_rejects_method_physics_mismatch(tmp_path: Path):
    config = _write_method_config(tmp_path)
    V0 = _atoms().get_volume()
    h = 0.005
    delta = 2.0 * 2 * h * V0 / EV_PER_A3_TO_GPA
    minus = _write_task(tmp_path, "minus", -h, "ni-oncv-pbe18-pw-strain-v002", suffix="NiPWStrain", energy=-10.0 - delta / 2, stress_trace=2.0, sigma0=-10.0, job_id="41")
    reference = _write_task(tmp_path, "reference", 0.0, "ni-oncv-pbe18-pw-engineering-v001", suffix="NiPW", energy=-10.0, stress_trace=2.0, sigma0=-10.0, job_id="32")
    plus = _write_task(tmp_path, "plus", h, "ni-oncv-pbe18-pw-strain-v002", suffix="NiPWStrain", energy=-10.0 + delta / 2, stress_trace=2.0, sigma0=-10.0, job_id="42")
    method = json.loads((plus / "method.json").read_text(encoding="utf-8"))
    method["nspin"] = 1
    (plus / "method.json").write_text(json.dumps(method) + "\n", encoding="utf-8")

    report = compare_strain_tasks(minus, reference, plus, config)

    assert report["overall"] is False
    assert report["physics_comparable"] is False
    assert report["checks"]["same_method_physics"]["passed"] is False
    assert report["energy_derivative_trace_GPa"] is None


def test_compare_strain_requires_exactly_one_sign_candidate(tmp_path: Path):
    config = _write_method_config(tmp_path)
    V0 = _atoms().get_volume()
    h = 0.005
    minus = _write_task(tmp_path, "minus", -h, "ni-oncv-pbe18-pw-strain-v002", suffix="NiPWStrain", energy=-10.0, stress_trace=0.0, sigma0=-10.0, job_id="41")
    reference = _write_task(tmp_path, "reference", 0.0, "ni-oncv-pbe18-pw-engineering-v001", suffix="NiPW", energy=-10.0, stress_trace=0.0, sigma0=-10.0, job_id="32")
    plus = _write_task(tmp_path, "plus", h, "ni-oncv-pbe18-pw-strain-v002", suffix="NiPWStrain", energy=-10.0, stress_trace=0.0, sigma0=-10.0, job_id="42")

    report = compare_strain_tasks(minus, reference, plus, config)

    assert report["overall"] is False
    assert report["sign_determined"] is False
    assert len(report["passing_sign_candidates"]) == 2
