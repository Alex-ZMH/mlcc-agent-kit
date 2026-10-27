from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.io import read, write

from mlcc.modeling import ModelArtifacts
from mlcc.elastic import (
    EV_PER_A3_TO_GPA,
    VOIGT_ORDER,
    _H_from_direction,
    _amplitude_slope_consistency,
    _derivative_comparison,
    _fit_cij,
    _load_bundle,
    _native_input_compatibility,
    _tensor_calibration_from_bundles,
    _work_conjugate_stress,
    analyze_elastic_tasks,
    calibrate_tensor_stress,
    plan_elastic_strains,
    voigt_strain_model,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _atoms() -> Atoms:
    atoms = Atoms(
        symbols=["Ca", "Zr", "O"],
        scaled_positions=[[0.0, 0.0, 0.0], [0.25, 0.5, 0.75], [0.5, 0.25, 0.25]],
        cell=[[5.1, 0.2, 0.1], [0.0, 5.4, 0.3], [0.0, 0.0, 5.7]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([11, 17, 23], dtype=int))
    return atoms


def _model() -> ModelArtifacts:
    return ModelArtifacts(
        model_id="cazro3-test",
        version="v001",
        atoms=_atoms(),
        metadata={"material": "CaZrO3"},
        artifact_dir=PROJECT_ROOT / "tmp" / "elastic-test-model",
    )


def _synthetic_tensor_bundles(*, nonlinear: bool = False):
    """Construct in-memory analytic data for the calibration math only."""

    reference_atoms = _atoms()
    volume = abs(float(np.linalg.det(reference_atoms.cell.array)))
    k_values = np.asarray([10.0, 12.0, 14.0, 16.0, 18.0, 20.0])
    method = {
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "stage": "scf",
        "model_id": "analytic",
        "device": "cpu",
        "dft_functional": "PBE",
        "basis_type": "pw",
        "ks_solver": "cg",
        "nspin": 1,
        "initial_moments_muB_by_element": {"Ca": 0.0, "Zr": 0.0, "O": 0.0},
        "smearing_method": "fixed",
        "element_order": ["Ca", "Zr", "O"],
        "kpoints": [1, 1, 1],
        "kpoint_rule": "explicit_mesh",
        "parameters": {
            "ecutwfc_Ry": 100,
            "scf_thr": 1.0e-8,
            "scf_nmax": 100,
            "nbands": 8,
            "mixing_beta": 0.3,
            "smearing_sigma_Ry": None,
        },
        "pseudopotentials": {element: {"filename": element + ".upf"} for element in ("Ca", "Zr", "O")},
        "stress_convention": {"sign": "abacus_printed"},
    }
    native_input = {"calculation": "scf", "nspin": "1", "suffix": "analytic"}
    bundles = []
    requested = {"reference": np.zeros(6, dtype=float)}

    def make_bundle(name, atoms, eta, stress, energy):
        return (
            name,
            {
                "directory": Path("analytic") / name,
                "task": {"task_id": name, "model_id": "analytic", "model_version": "v001"},
                "method": {**method, "version": "v001", "method_set": "analytic"},
                "input": dict(native_input),
                "result": {
                    "task_id": name,
                    "energy_eV": float(energy),
                    "energy_unit": "eV",
                    "energy_definition": "analytic total energy",
                    "energy_default_definition": "analytic total energy",
                    "occupations": "fixed",
                    "stress_GPa": np.asarray(stress).tolist(),
                    "stress_unit": "GPa",
                    "stress_sign": "abacus_printed",
                },
                "atoms": atoms,
                "native_result_consistent": True,
                "native_result_energy_match": True,
                "source_evidence": {"reason": "complete", "paths": [str(Path("analytic") / name / "OUT.log")]},
            },
        )

    zero_stress = np.zeros((3, 3), dtype=float)
    bundles.append(make_bundle("reference", reference_atoms, np.zeros(6), zero_stress, 0.0))
    for amplitude in (0.01, 0.02):
        for index, direction_name in enumerate(VOIGT_ORDER):
            for sign_name, sign in (("minus", -1.0), ("plus", 1.0)):
                eta = np.zeros(6, dtype=float)
                eta[index] = sign * amplitude
                atoms, record = voigt_strain_model(reference_atoms, eta, reference_model="analytic/v001")
                H = _H_from_direction(index)
                stiffness = k_values[index]
                if nonlinear and amplitude == 0.02:
                    stiffness = stiffness * 1.5
                P = stiffness * eta[index] * H / float(np.sum(H * H))
                F = np.asarray(record["F"], dtype=float)
                stress = P @ F.T / float(np.linalg.det(F))
                energy = 0.5 * volume * stiffness * eta[index] ** 2 / EV_PER_A3_TO_GPA
                name = f"{sign_name}-{direction_name}-a{amplitude}"
                bundles.append(make_bundle(name, atoms, eta, stress, energy))
                requested[name] = eta
    return bundles, requested


def _real_thresholds() -> dict[str, float]:
    return {
        "fractional_tolerance": 1.0e-10,
        "strain_tolerance": 1.0e-10,
        "reference_stress_GPa": 1.0,
        "linearity_residual_GPa": 1.0,
        "condition_number_max": 1.0e8,
        "asymmetry_GPa": 1.0,
        "calibration_abs_error_GPa": 1.0,
        "calibration_relative_error": 0.1,
        "calibration_signal_min_GPa": 0.01,
        "calibration_fd_consistency_GPa": 1.0,
        "amplitude_slope_difference_GPa": 1.0,
        "native_stress_asymmetry_GPa": 1.0e-8,
    }


def _tensor_thresholds() -> dict[str, float]:
    return {
        "fractional_tolerance": 1.0e-10,
        "strain_tolerance": 1.0e-10,
        "reference_stress_GPa": 1.0,
        "linearity_residual_GPa": 1.0,
        "condition_number_max": 1.0e8,
        "asymmetry_GPa": 1.0e-8,
        "calibration_abs_error_GPa": 1.0e-8,
        "calibration_relative_error": 1.0e-8,
        "calibration_signal_min_GPa": 1.0e-4,
        "calibration_fd_consistency_GPa": 1.0e-8,
        "amplitude_slope_difference_GPa": 1.0e-8,
        "native_stress_asymmetry_GPa": 1.0e-8,
    }


def _copy_real_elastic_tasks(tmp_path: Path) -> tuple[Path, Path]:
    source_tasks = PROJECT_ROOT / "workspace" / "tasks"
    target_tasks = tmp_path / "tasks"
    target_tasks.mkdir()
    for name in ("h1-ni-scf-v003", "h1-ni-strainminus-v004", "h1-ni-strainplus-v004"):
        source = source_tasks / name
        target = target_tasks / name
        shutil.copytree(source, target)
        result_path = target / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        source_files = result["source_files"]
        source_root = source.resolve()
        for key, raw_path in list(source_files.items()):
            raw = Path(raw_path)
            relative = raw.resolve().relative_to(source_root)
            source_files[key] = str((target / relative).resolve())
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return target_tasks / "h1-ni-scf-v003", target_tasks


def _analyze_real_copies(reference: Path, task_root: Path) -> dict:
    reports = PROJECT_ROOT / "workspace" / "reports" / "h1" / "strain-quick-v004"
    return analyze_elastic_tasks(
        reference,
        [task_root / "h1-ni-strainminus-v004", task_root / "h1-ni-strainplus-v004"],
        reports / "comparison.json",
        _real_thresholds(),
    )


def test_voigt_strain_uses_engineering_shear_and_preserves_lineage():
    reference = _atoms()
    strain = np.asarray([0.01, -0.02, 0.03, 0.04, -0.06, 0.08])

    derived, record = voigt_strain_model(reference, strain, reference_model={"model_id": "czo", "version": "v001"})

    epsilon = np.asarray(
        [
            [0.01, 0.08 / 2.0, -0.06 / 2.0],
            [0.08 / 2.0, -0.02, 0.04 / 2.0],
            [-0.06 / 2.0, 0.04 / 2.0, 0.03],
        ]
    )
    expected_F = np.eye(3) + epsilon
    np.testing.assert_allclose(derived.cell.array, reference.cell.array @ expected_F.T, rtol=0, atol=1e-12)
    np.testing.assert_allclose(derived.get_scaled_positions(wrap=False), reference.get_scaled_positions(wrap=False), rtol=0, atol=1e-14)
    assert derived.arrays["atom_id"].tolist() == reference.arrays["atom_id"].tolist()
    assert record["voigt_order"] == ["xx", "yy", "zz", "yz", "xz", "xy"]
    np.testing.assert_allclose(record["epsilon_tensor"], epsilon, rtol=0, atol=1e-14)
    assert record["fractional_coordinates_fixed"] is True
    assert record["atom_ids_preserved"] is True
    assert record["scope"] == "clamped-ion_fixed-fractional_static"


def test_voigt_zero_strain_is_the_identity_geometry():
    reference = _atoms()
    derived, record = voigt_strain_model(reference, [0.0] * 6, reference_model="czo/v001")

    np.testing.assert_allclose(derived.cell.array, reference.cell.array, rtol=0, atol=1e-14)
    np.testing.assert_allclose(derived.positions, reference.positions, rtol=0, atol=1e-14)
    assert record["detF"] == pytest.approx(1.0)
    assert record["reference_volume_A3"] == pytest.approx(record["derived_volume_A3"])


def test_voigt_strain_rejects_non_positive_definite_deformation_gradient():
    with pytest.raises(ValueError, match="positive definite"):
        voigt_strain_model(_atoms(), [-2.0, 0.0, 0.0, 0.0, 0.0, 0.0], reference_model="czo/v001")


def test_plan_contains_reference_and_six_plus_minus_requests_without_writing_tasks():
    plan = plan_elastic_strains(_model(), [0.005, 0.01])

    assert plan["scope"] == "clamped-ion_fixed-fractional_static"
    assert plan["ionic_relaxation"] == "not_performed"
    assert plan["request_count"] == 25
    assert len(plan["requests"]) == 24
    assert {entry["direction"] for entry in plan["requests"]} == {"xx", "yy", "zz", "yz", "xz", "xy"}
    assert {entry["sign"] for entry in plan["requests"]} == {"minus", "plus"}
    assert {entry["amplitude"] for entry in plan["requests"]} == {0.005, 0.01}
    assert plan["reference"]["record"]["strain_voigt"] == [0.0] * 6
    assert plan["requests"][0]["input_transformation"]["kind"] == "voigt_strain"
    json.dumps(plan)


def test_real_three_point_fixture_is_blocked_before_any_cij_fit():
    tasks = PROJECT_ROOT / "workspace" / "tasks"
    reports = PROJECT_ROOT / "workspace" / "reports" / "h1" / "strain-quick-v004"
    thresholds = {
        "fractional_tolerance": 1.0e-10,
        "strain_tolerance": 1.0e-10,
        "reference_stress_GPa": 1.0,
        "linearity_residual_GPa": 1.0,
        "condition_number_max": 1.0e8,
        "asymmetry_GPa": 1.0,
        "calibration_abs_error_GPa": 1.0,
        "calibration_relative_error": 0.1,
        "calibration_signal_min_GPa": 0.01,
        "calibration_fd_consistency_GPa": 1.0,
        "amplitude_slope_difference_GPa": 1.0,
        "native_stress_asymmetry_GPa": 1.0e-8,
    }

    report = analyze_elastic_tasks(
        tasks / "h1-ni-scf-v003",
        [tasks / "h1-ni-strainminus-v004", tasks / "h1-ni-strainplus-v004"],
        reports / "comparison.json",
        thresholds,
    )

    assert report["status"] == "blocked"
    assert report["Cij"] is None
    assert report["Cij_GPa"] is None
    assert report["production_qualification"] is False
    assert report["calibration"]["stress_sign_qualification"] is False
    assert report["fit"]["rank"] == 1
    assert report["checks"]["rank6"] is False
    assert report["checks"]["complete_plus_minus_pairs"] is True
    assert report["tensor_qualification"] is False
    assert report["shear_qualification"] is False
    assert "full_tensor_calibration_evidence_missing" in report["issues"]


def test_public_tensor_calibrator_blocks_real_three_point_fixture():
    tasks = PROJECT_ROOT / "workspace" / "tasks"
    report = calibrate_tensor_stress(
        tasks / "h1-ni-scf-v003",
        [tasks / "h1-ni-strainminus-v004", tasks / "h1-ni-strainplus-v004"],
        _real_thresholds(),
    )

    assert report["status"] == "blocked"
    assert report["full_tensor_stress_calibration"] is False
    assert report["sign_status"] == "blocked"
    assert report["checks"]["five_point_grid"]["passed"] is False


def test_real_copy_result_stress_must_match_native_log(tmp_path):
    reference, task_root = _copy_real_elastic_tasks(tmp_path)
    result_path = task_root / "h1-ni-strainplus-v004" / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["stress_GPa"][0][0] += 0.25
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    report = _analyze_real_copies(reference, task_root)

    assert report["status"] == "blocked"
    assert report["checks"]["native_result_consistency"] is False
    assert report["checks"]["native_result_consistency_by_task"]["h1-ni-strainplus-v004"] is False


def test_real_copy_method_model_version_must_match_task(tmp_path):
    reference, task_root = _copy_real_elastic_tasks(tmp_path)
    method_path = task_root / "h1-ni-strainminus-v004" / "method.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method["version"] = "v999"
    method_path.write_text(json.dumps(method, indent=2) + "\n", encoding="utf-8")

    report = _analyze_real_copies(reference, task_root)

    assert report["status"] == "blocked"
    assert report["checks"]["identity_by_task"]["h1-ni-strainminus-v004"] is False
    assert report["checks"]["identity"] is False


def test_real_copy_native_input_precision_must_match_method(tmp_path):
    reference, task_root = _copy_real_elastic_tasks(tmp_path)
    input_path = task_root / "h1-ni-strainminus-v004" / "INPUT"
    text = input_path.read_text(encoding="utf-8")
    input_path.write_text(text.replace("ecutwfc              100", "ecutwfc              101", 1), encoding="utf-8")

    report = _analyze_real_copies(reference, task_root)

    assert report["status"] == "blocked"
    assert report["checks"]["native_input_compatibility"] is False
    assert report["checks"]["native_input_compatibility_by_task"]["h1-ni-strainminus-v004"] is False


def test_real_copy_full_deformation_gradient_rejects_antisymmetric_rotation(tmp_path):
    reference, task_root = _copy_real_elastic_tasks(tmp_path)
    input_path = task_root / "h1-ni-strainminus-v004" / "input.extxyz"
    atoms = read(input_path)
    fractional = atoms.get_scaled_positions(wrap=False)
    rotation = np.eye(3)
    rotation[0, 1] = 0.01
    rotation[1, 0] = -0.01
    atoms.set_cell(atoms.cell.array @ rotation.T, scale_atoms=False)
    atoms.set_scaled_positions(fractional)
    write(input_path, atoms, format="extxyz")

    report = _analyze_real_copies(reference, task_root)
    geometry = report["checks"]["geometry"]["h1-ni-strainminus-v004"]

    assert report["status"] == "blocked"
    assert geometry["passed"] is False
    assert geometry["F_max_abs_delta"] > 1.0e-3


def test_czo_fixed_occupation_native_input_compatibility_is_true_but_analysis_stays_blocked():
    root = PROJECT_ROOT / "workspace"
    task = root / "tasks" / "p4-czo-compatibility-scf-v001"
    report = analyze_elastic_tasks(
        task,
        [],
        root / "reports" / "method-qualification" / "czo-native-acceptance-v001.json",
        _real_thresholds(),
    )

    assert report["status"] == "blocked"
    assert report["checks"]["native_input_compatibility"] is True
    assert report["checks"]["native_input_compatibility_by_task"]["reference"] is True


@pytest.mark.parametrize("location,key,value", [
    ("method", "net_charge", 2),
    ("method", "nelec_delta", -2),
    ("input", "nelec_delta", "-2"),
    ("input", "nelec", "158"),
    ("input", "gate_flag", "1"),
])
def test_neutral_native_consumers_reject_charge_overrides(location, key, value):
    # Negative contract checks against a copy of real neutral evidence;
    # these mutations are not charged calculation results.
    bundle = _load_bundle(PROJECT_ROOT / "workspace" / "tasks" / "p4-czo-compatibility-scf-v001")
    assert _native_input_compatibility(bundle) is True
    bundle[location][key] = value
    assert _native_input_compatibility(bundle) is False


def test_tensor_calibration_uses_work_conjugacy_and_allows_zero_reference_signal():
    bundles, requested = _synthetic_tensor_bundles()
    report = _tensor_calibration_from_bundles(
        bundles,
        requested,
        _tensor_thresholds(),
        geometry_strain_tolerance=1.0e-10,
    )

    assert report["status"] == "passed"
    assert report["full_tensor_stress_calibration"] is True
    assert report["passing_sign_candidates"] == ["printed_trace"]
    assert report["sign_status"] == "determined"
    assert report["directions"]["xx"]["points"]["zero"]["signal_identifiable"] is False
    assert report["directions"]["xx"]["passed"] is True
    assert report["checks"]["finite_difference_consistency"]["passed"] is True


def test_tensor_calibration_identifies_global_negative_printed_stress_sign():
    bundles, requested = _synthetic_tensor_bundles()
    for _name, bundle in bundles:
        bundle["result"]["stress_GPa"] = (-np.asarray(bundle["result"]["stress_GPa"])).tolist()
    report = _tensor_calibration_from_bundles(
        bundles,
        requested,
        _tensor_thresholds(),
        geometry_strain_tolerance=1.0e-10,
    )

    assert report["status"] == "passed"
    assert report["passing_sign_candidates"] == ["negative_printed_trace"]
    assert report["stress_sign_qualification"] is True


def test_tensor_calibration_rejects_engineering_shear_factor_error():
    bundles, requested = _synthetic_tensor_bundles()
    for name, bundle in bundles:
        if any(f"-{direction}-" in name for direction in ("yz", "xz", "xy")):
            bundle["result"]["stress_GPa"] = (2.0 * np.asarray(bundle["result"]["stress_GPa"])).tolist()
    report = _tensor_calibration_from_bundles(
        bundles,
        requested,
        _tensor_thresholds(),
        geometry_strain_tolerance=1.0e-10,
    )

    assert report["status"] == "blocked"
    assert report["full_tensor_stress_calibration"] is False
    assert report["directions"]["yz"]["passed"] is False


def test_tensor_calibration_rejects_wrong_stress_unit_magnitude():
    bundles, requested = _synthetic_tensor_bundles()
    for _name, bundle in bundles:
        bundle["result"]["stress_GPa"] = (0.1 * np.asarray(bundle["result"]["stress_GPa"])).tolist()
    report = _tensor_calibration_from_bundles(
        bundles,
        requested,
        _tensor_thresholds(),
        geometry_strain_tolerance=1.0e-10,
    )

    assert report["status"] == "blocked"
    assert report["passing_sign_candidates"] == []


def test_tensor_calibration_rejects_amplitude_dependent_response():
    bundles, requested = _synthetic_tensor_bundles(nonlinear=True)
    report = _tensor_calibration_from_bundles(
        bundles,
        requested,
        _tensor_thresholds(),
        geometry_strain_tolerance=1.0e-10,
    )

    assert report["status"] == "blocked"
    assert report["full_tensor_stress_calibration"] is False
    assert report["checks"]["candidate_signs"]["passed"] is False


def test_amplitude_slope_consistency_is_explicit_and_does_not_silently_average():
    pair_groups = {}
    stress_vectors = {}
    for index, direction in enumerate(VOIGT_ORDER):
        unit = np.zeros(6)
        unit[index] = 1.0
        for amplitude in (0.01, 0.02):
            key = f"{direction}-{amplitude}"
            minus = f"{key}-minus"
            plus = f"{key}-plus"
            slope = 10.0 * unit if amplitude == 0.01 else 14.0 * unit
            stress_vectors[minus] = -amplitude * slope
            stress_vectors[plus] = amplitude * slope
            pair_groups[key] = {
                "direction": unit.tolist(),
                "amplitude": amplitude,
                "minus": [minus],
                "plus": [plus],
            }

    report = _amplitude_slope_consistency(pair_groups, stress_vectors, 1.0, 1.0)

    assert report["enough_amplitudes"] is True
    assert report["maximum_difference_GPa"] == pytest.approx(4.0)
    assert report["passed"] is False


def test_zero_signal_is_indeterminate_when_both_global_signs_pass():
    comparison = _derivative_comparison(0.0, 0.0, 0.01, 1.0e-8, 1.0e-8, 1.0)

    assert comparison["error_passed"] is True
    assert comparison["passed"] is False
    assert comparison["signal_identifiable"] is False


def test_tensor_calibration_reports_dual_zero_sign_candidates_as_indeterminate():
    bundles, requested = _synthetic_tensor_bundles()
    for _name, bundle in bundles:
        bundle["result"]["energy_eV"] = 0.0
        bundle["result"]["stress_GPa"] = np.zeros((3, 3)).tolist()
    thresholds = _tensor_thresholds()
    thresholds["calibration_signal_min_GPa"] = 0.0
    report = _tensor_calibration_from_bundles(
        bundles,
        requested,
        thresholds,
        geometry_strain_tolerance=1.0e-10,
    )

    assert report["passing_sign_candidates"] == ["printed_trace", "negative_printed_trace"]
    assert report["sign_status"] == "indeterminate"
    assert report["full_tensor_stress_calibration"] is False


def test_work_conjugate_stress_uses_current_configuration_cauchy_measure():
    reference = _atoms()
    strained, record = voigt_strain_model(reference, [0.02, 0, 0, 0, 0, 0])
    sigma = np.diag([3.0, 4.0, 5.0])
    F, P, determinant = _work_conjugate_stress(
        reference,
        strained,
        {"stress_GPa": sigma.tolist(), "stress_unit": "GPa", "stress_sign": "abacus_printed"},
    )

    np.testing.assert_allclose(F, np.asarray(record["F"]), rtol=0, atol=1.0e-12)
    np.testing.assert_allclose(np.diag(P), [3.0, 4.08, 5.1], rtol=0, atol=1.0e-12)
    np.testing.assert_allclose(P - np.diag(np.diag(P)), np.zeros((3, 3)), rtol=0, atol=1.0e-12)


def test_fit_cij_preserves_non_diagonal_matrix_orientation():
    Cij = np.asarray(
        [
            [110.0, 7.0, 3.0, 0.0, 1.0, 2.0],
            [5.0, 120.0, 4.0, 1.0, 0.0, 3.0],
            [2.0, 6.0, 130.0, 2.0, 1.0, 0.0],
            [0.5, 1.5, 2.5, 40.0, 3.0, 4.0],
            [1.0, 0.5, 2.0, 2.5, 45.0, 5.0],
            [2.0, 1.0, 0.5, 3.5, 4.5, 50.0],
        ]
    )
    strains = np.vstack([np.eye(6), np.asarray([[0.2, -0.1, 0.3, 0.05, 0.1, -0.2]])])
    stresses = strains @ Cij.T

    fitted, predicted, residual, condition = _fit_cij(strains, stresses)

    np.testing.assert_allclose(fitted, Cij, rtol=0, atol=1.0e-10)
    np.testing.assert_allclose(predicted, stresses, rtol=0, atol=1.0e-10)
    np.testing.assert_allclose(residual, np.zeros_like(stresses), rtol=0, atol=1.0e-10)
    assert np.isfinite(condition)

