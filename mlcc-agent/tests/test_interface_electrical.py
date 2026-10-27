"""Static-contract tests for the saved interface electrostatic response.

These fixtures are mathematical ``software_contract_only`` products.  They
exercise units, signs, explicit windows and source identity only; they are not
native ABACUS output and do not establish material qualification.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

from mlcc.electrostatic_potential import BOHR_TO_ANGSTROM, RY_TO_EV
from mlcc.interface_electrical import calculate_interface_electrical


def _selection(
    *,
    axis: int = 0,
    orientation: int = 1,
    from_range: tuple[int, int] = (0, 1),
    to_range: tuple[int, int] = (2, 3),
    boundary: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "grid_axis": axis,
        "orientation": orientation,
        "boundary": list(boundary or ["p", "f", "f"]),
        "derivative": "adjacent_planes_no_wrap",
        "regions": {
            "from": {
                "region_id": "left-window",
                "index_range": list(from_range),
                "reason": "explicit left interface window",
            },
            "to": {
                "region_id": "right-window",
                "index_range": list(to_range),
                "reason": "explicit right interface window",
            },
        },
        "source": "test declaration",
    }


def _potential(
    values_ry: list[float],
    *,
    shape: tuple[int, int, int] = (3, 2, 2),
    steps_bohr: list[list[float]] | None = None,
    task_id: str = "software-potential-task",
    model_id: str = "interface-model",
    method_set: str = "abacus-contract-scf",
) -> dict[str, Any]:
    steps = copy.deepcopy(steps_bohr or [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    steps_array = np.asarray(steps, dtype=float)
    shape_array = np.asarray(shape, dtype=float)
    cell = steps_array * shape_array[:, None]
    origin_bohr = [0.0, 0.0, 0.0]
    cube = {
        "schema": "mlcc.abacus-electrostatic-cube.v1",
        "source_file": f"software-contract-only/{task_id}/ElecStaticPot.cube",
        "step": 0,
        "nspin": 1,
        "shape": list(shape),
        "origin_bohr": origin_bohr,
        "step_vectors_bohr": steps,
        "cell_bohr": cell.tolist(),
        "origin_angstrom": [0.0, 0.0, 0.0],
        "step_vectors_angstrom": (steps_array * BOHR_TO_ANGSTROM).tolist(),
        "cell_angstrom": (cell * BOHR_TO_ANGSTROM).tolist(),
        "values_Ry": list(values_ry),
        "values_eV": [value * RY_TO_EV for value in values_ry],
        "axis_order": "x_outer_y_middle_z_inner",
        "flat_index": "(ix*ny+iy)*nz+iz",
        "unit_conversion": {
            "Ry_to_eV": RY_TO_EV,
            "Bohr_to_angstrom": BOHR_TO_ANGSTROM,
        },
        "evidence_kind": "software_contract_only",
    }
    return {
        "schema": "mlcc.abacus-electrostatic-potential.v1",
        "status": "software_contract_fixture_unaligned",
        "task_id": task_id,
        "scheduler_job_id": f"software-job-{task_id}",
        "study_id": "software-study",
        "model_id": model_id,
        "model_version": "v001",
        "method_set": method_set,
        "method": {
            "engine": "abacus",
            "abacus_version_target": "3.10.1",
            "stage": "scf",
            "model_id": model_id,
            "version": "v001",
            "dft_functional": "PBE",
            "basis_type": "pw",
            "nspin": 1,
            "lspinorb": False,
            "noncolin": False,
            "initial_moments_muB_by_element": {"X": 0.0},
            "occupations": "fixed",
            "smearing_method": None,
            "symmetry": -1,
            "net_charge": 0,
            "nelec": 0,
            "nelec_delta": 0,
            "charge_convention": "q_positive_removes_electrons",
            "element_order": ["X"],
            "kpoints": [1, 1, 1],
            "kpoint_rule": "Gamma",
            "parameters": {"ecutwfc_Ry": 100, "scf_thr": 1e-11},
            "pseudopotential_ids": {"X": "X-NC"},
            "pseudopotential_metadata": {
                "X": {
                    "element": "X",
                    "functional": "PBE",
                    "valence_electrons_per_atom": 1,
                    "relativity": "scalar",
                    "has_spin_orbit": False,
                    "type": "NC",
                    "qualification": "input_compatibility_only",
                },
            },
            "pseudopotential_treatment": {"X": "scalar"},
            "suffix": f"ContractSCF-{task_id}",
            "requested_artifacts": {
                "electrostatic_potential": {"relative_path": f"OUT.{task_id}/ElecStaticPot.cube"},
            },
            "source_configuration": f"/source/{task_id}/method.json",
            "pseudopotentials": {"X": {"source": f"/source/{task_id}/X.upf", "filename": "X.upf"}},
        },
        "atom_map": {
            "schema": "mlcc.abacus-atom-map.v1",
            "model_id": model_id,
            "version": "v001",
            "source_atom_ids": ["a0"],
            "element_order": ["X"],
            "abacus_order": [{"abacus_index": 0, "source_index": 0, "atom_id": "a0", "element": "X", "label": "X1"}],
        },
        "kind": "local_ionic_plus_hartree",
        "value_unit": "Ry",
        "geometry_unit": "Bohr",
        "sign_convention": "electron_potential_energy",
        "includes_XC": False,
        "includes_nonlocal_pseudopotential": False,
        "energy_zero": {
            "Hartree_G0": "zero",
            "local_ionic_G0": "retained_pseudopotential_convention",
            "total_mean_subtracted": False,
            "fermi_subtracted": False,
            "vacuum_subtracted": False,
        },
        "cube": cube,
        "source_files": {"potential": cube["source_file"]},
        "conditions": {"cell_constraint": "fixed_cell", "net_charge": 0},
        "input_parameters": {
            "INPUT": {"efield_flag": "0", "dip_cor_flag": "0", "gate_flag": "0", "imp_sol": "0"},
            "OUT.INPUT": {"efield_flag": "0", "dip_cor_flag": "0", "gate_flag": "0", "imp_sol": "0",
                          "efield_dir": "2", "efield_pos_max": "-1", "efield_pos_dec": "-1",
                          "efield_amp": "0", "zgate": "0.5"},
        },
        "native_output_observed": False,
        "native_GPU_accepted": False,
        "evidence_kind": "software_contract_only",
        "scientific_qualification": False,
        "production_qualification": False,
    }


def _three_plane_potential(**kwargs: Any) -> dict[str, Any]:
    values = [0.0] * 4 + [1.0 / RY_TO_EV] * 4 + [2.0 / RY_TO_EV] * 4
    return _potential(values, **kwargs)


def test_electron_energy_sign_and_explicit_regional_response() -> None:
    result = calculate_interface_electrical(_three_plane_potential(), _selection())

    assert result["schema"] == "mlcc.interface-electrical-response.v1"
    assert result["target"]["plane_profile"][1]["mean_electron_potential_energy_eV"] == pytest.approx(1.0)
    assert result["target"]["plane_profile"][1]["potential_V"] == pytest.approx(-1.0)
    regional = result["target"]["regional_response"]
    assert regional["delta_Ue_eV"] == pytest.approx(2.0)
    assert regional["delta_phi_V"] == pytest.approx(-2.0)
    assert regional["secant_field_V_per_angstrom"] == pytest.approx(1.0 / BOHR_TO_ANGSTROM)
    assert result["evidence_kind"] == "software_contract_only"
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False


def test_triclinic_normal_uses_true_transverse_cross_product_spacing() -> None:
    # Transverse planes are yz; the selected step is tilted by one Bohr in y.
    # Its true normal spacing is 2 Bohr, whereas its length is sqrt(5) Bohr.
    steps = [[2.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    result = calculate_interface_electrical(
        _three_plane_potential(steps_bohr=steps),
        _selection(),
    )
    assert result["normal_cartesian"] == pytest.approx([1.0, 0.0, 0.0])
    assert result["normal_spacing_magnitude_angstrom"] == pytest.approx(2.0 * BOHR_TO_ANGSTROM)
    assert result["target"]["regional_response"]["delta_s_angstrom"] == pytest.approx(4.0 * BOHR_TO_ANGSTROM)
    assert result["target"]["regional_response"]["secant_field_V_per_angstrom"] == pytest.approx(0.5 / BOHR_TO_ANGSTROM)


def test_orientation_reversal_flips_field_but_not_regional_delta_phi() -> None:
    positive = calculate_interface_electrical(_three_plane_potential(), _selection(orientation=1))
    negative = calculate_interface_electrical(_three_plane_potential(), _selection(orientation=-1))
    positive_regional = positive["target"]["regional_response"]
    negative_regional = negative["target"]["regional_response"]
    assert negative_regional["delta_phi_V"] == pytest.approx(positive_regional["delta_phi_V"])
    assert negative_regional["delta_Ue_eV"] == pytest.approx(positive_regional["delta_Ue_eV"])
    assert negative_regional["secant_field_V_per_angstrom"] == pytest.approx(
        -positive_regional["secant_field_V_per_angstrom"]
    )


@pytest.mark.parametrize(
    "selection",
    [
        _selection(from_range=(0, 0)),
        _selection(from_range=(0, 2), to_range=(1, 3)),
        _selection(to_range=(2, 4)),
    ],
    ids=["empty-window", "overlap", "out-of-range"],
)
def test_rejects_empty_overlapping_or_out_of_range_windows(selection: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        calculate_interface_electrical(_three_plane_potential(), selection)


def test_periodic_boundary_is_preserved_without_wrap_secant() -> None:
    result = calculate_interface_electrical(_three_plane_potential(), _selection(boundary=["p", "p", "p"]))
    secants = result["target"]["adjacent_plane_secants"]
    assert result["boundary"] == ["p", "p", "p"]
    assert [(item["left_plane_index"], item["right_plane_index"]) for item in secants] == [(0, 1), (1, 2)]
    assert not any(item["left_plane_index"] == 2 for item in secants)


def test_reference_comparison_is_gauge_invariant_and_preserves_profiles() -> None:
    target = _three_plane_potential(task_id="target")
    reference = _three_plane_potential(task_id="reference")
    reference["cube"]["values_Ry"] = [value + 10.0 / RY_TO_EV for value in reference["cube"]["values_Ry"]]
    reference["cube"]["values_eV"] = [value * RY_TO_EV for value in reference["cube"]["values_Ry"]]
    result = calculate_interface_electrical(
        target,
        _selection(),
        reference,
        reference_description="same model, constant source-gauge shift",
    )
    comparison = result["reference_comparison"]
    assert comparison["delta_delta_phi_V"] == pytest.approx(0.0)
    assert comparison["delta_delta_Ue_eV"] == pytest.approx(0.0)
    assert comparison["delta_secant_field_V_per_angstrom"] == pytest.approx(0.0)
    assert comparison["absolute_profile_difference"] is None
    assert result["reference"]["plane_profile"][0]["potential_V"] == pytest.approx(-10.0)
    assert result["target"]["identity"]["task_id"] == "target"
    assert result["reference"]["identity"]["task_id"] == "reference"


def test_reference_allows_runtime_suffix_and_output_path_differences() -> None:
    target = _three_plane_potential(task_id="target")
    reference = _three_plane_potential(task_id="reference")
    reference["method"]["suffix"] = "different-runtime-suffix"
    reference["method"]["requested_artifacts"]["electrostatic_potential"]["relative_path"] = "other-output/ElecStaticPot.cube"
    reference["method"]["source_configuration"] = "/other/source/method.json"
    reference["method"]["pseudopotentials"]["X"]["source"] = "/other/source/X.upf"
    reference["source_files"]["potential"] = "other-output/ElecStaticPot.cube"
    result = calculate_interface_electrical(
        target,
        _selection(),
        reference,
        reference_description="same physics, different runtime paths",
    )
    assert result["reference_comparison"]["delta_delta_phi_V"] == pytest.approx(0.0)


@pytest.mark.parametrize("section", ["INPUT", "OUT.INPUT"])
def test_reference_rejects_changed_external_field_control(section: str) -> None:
    target = _three_plane_potential(task_id="target")
    reference = _three_plane_potential(task_id="reference")
    reference["input_parameters"][section]["efield_flag"] = "1"
    with pytest.raises(ValueError):
        calculate_interface_electrical(
            target,
            _selection(),
            reference,
            reference_description="external-field control mismatch",
        )


@pytest.mark.parametrize("changed_key", ["model_id", "method_set", "atom_map"])
def test_reference_requires_strict_source_identity(changed_key: str) -> None:
    target = _three_plane_potential(task_id="target")
    reference = _three_plane_potential(task_id="reference")
    if changed_key == "atom_map":
        reference[changed_key]["source_atom_ids"] = ["different"]
    elif changed_key == "method_set":
        reference[changed_key] = "different-method"
    else:
        reference[changed_key] = "different-model"
    with pytest.raises(ValueError):
        calculate_interface_electrical(
            target,
            _selection(),
            reference,
            reference_description="identity mismatch",
        )


def test_reference_reports_nonzero_region_and_field_change() -> None:
    target = _three_plane_potential(task_id="target")
    reference = _potential([0.0] * 4 + [0.5 / RY_TO_EV] * 4 + [1.0 / RY_TO_EV] * 4, task_id="reference")
    result = calculate_interface_electrical(target, _selection(), reference, reference_description="explicit saved-state change")
    change = result["reference_comparison"]
    assert change["delta_delta_phi_V"] == pytest.approx(-1.0)
    assert change["delta_secant_field_V_per_angstrom"] == pytest.approx(0.5 / BOHR_TO_ANGSTROM)
    assert change["adjacent_field_differences_V_per_angstrom"] == pytest.approx([0.5 / BOHR_TO_ANGSTROM] * 2)


def test_missing_field_control_is_not_equivalent_to_explicit_off() -> None:
    target = _three_plane_potential(task_id="target")
    reference = _three_plane_potential(task_id="reference")
    del reference["input_parameters"]["INPUT"]["efield_flag"]
    with pytest.raises(ValueError, match="controls differ"):
        calculate_interface_electrical(target, _selection(), reference, reference_description="missing control")


def test_changed_physical_cutoff_is_not_a_runtime_path_change() -> None:
    target = _three_plane_potential(task_id="target")
    reference = _three_plane_potential(task_id="reference")
    reference["method"]["parameters"]["ecutwfc_Ry"] = 80
    with pytest.raises(ValueError, match="physical method"):
        calculate_interface_electrical(target, _selection(), reference, reference_description="different cutoff")


@pytest.mark.parametrize("key,value", [
    ("kpoint_shift", [0.0, 0.0, 0.0]), ("gamma_only", False),
    ("numerical_orbital_ids", {"X": "X-new-nao"}),
    ("numerical_orbitals", {"X": {"source": "/declared/X-new.orb", "filename": "X-new.orb"}}),
])
def test_optional_physical_method_fields_preserve_presence(key: str, value: Any) -> None:
    target = _three_plane_potential(task_id="target")
    reference = _three_plane_potential(task_id="reference")
    reference["method"][key] = value
    with pytest.raises(ValueError, match="physical method"):
        calculate_interface_electrical(target, _selection(), reference, reference_description="optional method mismatch")

