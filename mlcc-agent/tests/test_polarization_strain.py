"""Focused P5.07 polarization/strain consumer checks.

The pure-helper cases are mathematical inputs.  The public wrapper case uses
an explicitly software-contract-only manifest with no native jobs; it checks
that absent saved sources remain missing rather than being fabricated.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.io import read as ase_read
from ase.io import write as ase_write

import mlcc.polarization_strain as polarization_strain
from mlcc.abacus import BOHR_PER_ANGSTROM
from mlcc.berry import _E_PER_BOHR2_TO_C_PER_M2
from mlcc.elastic import voigt_strain_model
from mlcc.model_derivatives import _write_derived
from mlcc.modeling import read_model_artifacts, write_model_artifacts
from mlcc.polarization_strain import (
    _pair_response,
    _reduced_charge,
    analyze_polarization_strain,
)


_E_CHARGE_SCALE = 1.602176634e-19 * 1.0e20
_VOIGT_INDEX = {
    "xx": (0, 0),
    "yy": (1, 1),
    "zz": (2, 2),
    "yz": (1, 2),
    "xz": (0, 2),
    "xy": (0, 1),
}


def _cell_volume(cell: list[list[float]]) -> float:
    return float(abs(np.linalg.det(np.asarray(cell, dtype=float))))


def _strained_cell(reference_cell: list[list[float]], component: str, strain: float) -> list[list[float]]:
    F = np.eye(3)
    i, j = _VOIGT_INDEX[component]
    if i == j:
        F[i, j] += strain
    else:
        F[i, j] += strain / 2.0
        F[j, i] += strain / 2.0
    return (np.asarray(reference_cell, dtype=float) @ F.T).tolist()


def _direction(
    reduced_charge: float,
    *,
    quantum: float = 1.0,
    quantum_factor: int = 1,
    branch_integer: int | None = 0,
    branch_basis: str | None = "software-contract-basis",
) -> dict[str, object]:
    representative = quantum * (reduced_charge / quantum_factor - (branch_integer or 0))
    return {
        "reduced_charge": reduced_charge,
        "representative_P_C_per_m2": representative,
        "quantum_Q_C_per_m2": quantum,
        "quantum_factor": quantum_factor,
        "branch_integer": branch_integer,
        "branch_basis": branch_basis,
    }


def _point(
    point_id: str,
    strain: float,
    component: str,
    cell: list[list[float]],
    reduced_by_gdir: dict[str, float],
    *,
    directions: tuple[int, ...] = (1, 2, 3),
    branch_integer: int | None = 0,
    branch_basis: str | None = "software-contract-basis",
) -> dict[str, object]:
    return {
        "point_id": point_id,
        "voigt_component": component,
        "strain": strain,
        "cell_angstrom": cell,
        "volume_A3": _cell_volume(cell),
        "directions": {
            str(gdir): _direction(
                reduced_by_gdir[str(gdir)],
                branch_integer=branch_integer,
                branch_basis=branch_basis,
            )
            for gdir in directions
        },
    }


def _pair(component: str, minus_id: str = "minus", plus_id: str = "plus") -> dict[str, object]:
    return {
        "pair_id": f"{component}-pair",
        "voigt_component": component,
        "minus_point_id": minus_id,
        "plus_point_id": plus_id,
    }


def _assert_vector_close(actual: object, expected: np.ndarray) -> None:
    assert actual is not None
    np.testing.assert_allclose(np.asarray(actual, dtype=float), expected, rtol=0.0, atol=1e-12)


def test_reduced_charge_requires_declared_branch_and_applies_quantum_factor():
    assert _reduced_charge(0.25, 0.5, 2, 1, "branch-1") == pytest.approx(3.0)
    assert _reduced_charge(0.25, 0.5, 2, None, None) is None
    assert _reduced_charge(0.25, 0.5, 2, 1, None) is None


def test_pair_response_constant_reduced_charge_has_geometric_improper_response():
    reference_cell = [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]
    reference_volume = _cell_volume(reference_cell)
    h = 0.02
    minus_cell = _strained_cell(reference_cell, "xy", -h)
    plus_cell = _strained_cell(reference_cell, "xy", h)
    reduced = {"1": 0.25, "2": -0.5, "3": 0.75}
    minus = _point("minus", -h, "xy", minus_cell, reduced)
    plus = _point("plus", h, "xy", plus_cell, reduced)

    result = _pair_response(_pair("xy"), minus, plus, reference_cell, reference_volume)

    assert result["amplitude"] == pytest.approx(h)
    assert result["missing"] == []
    assert result["reduced_slopes_by_gdir"] == {"1": pytest.approx(0.0), "2": pytest.approx(0.0), "3": pytest.approx(0.0)}
    _assert_vector_close(result["proper_e_C_per_m2"], np.zeros(3))

    p_row = np.asarray([reduced["1"], reduced["2"], reduced["3"]], dtype=float)
    expected_improper = (
        _E_CHARGE_SCALE
        * (
            p_row @ np.asarray(plus_cell, dtype=float) / _cell_volume(plus_cell)
            - p_row @ np.asarray(minus_cell, dtype=float) / _cell_volume(minus_cell)
        )
        / (2.0 * h)
    )
    _assert_vector_close(result["improper_dP_ds_C_per_m2"], expected_improper)
    assert not np.allclose(np.asarray(result["improper_dP_ds_C_per_m2"]), np.zeros(3))


def test_pair_response_complete_nonorthogonal_shear_returns_proper_and_improper_vectors():
    reference_cell = [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]
    reference_volume = _cell_volume(reference_cell)
    h = 0.02
    minus_cell = _strained_cell(reference_cell, "xy", -h)
    plus_cell = _strained_cell(reference_cell, "xy", h)
    minus_reduced = {"1": 0.2, "2": -0.4, "3": 0.8}
    slopes = np.asarray([1.1, -0.7, 0.35], dtype=float)
    plus_reduced = {key: value + 2.0 * h * slopes[index] for index, (key, value) in enumerate(minus_reduced.items())}
    minus = _point("minus", -h, "xy", minus_cell, minus_reduced)
    plus = _point("plus", h, "xy", plus_cell, plus_reduced)

    result = _pair_response(_pair("xy"), minus, plus, reference_cell, reference_volume)

    assert result["amplitude"] == pytest.approx(h)
    assert result["missing"] == []
    for index, gdir in enumerate(("1", "2", "3")):
        assert result["reduced_slopes_by_gdir"][gdir] == pytest.approx(slopes[index])
    expected_proper = (_E_CHARGE_SCALE / reference_volume) * (slopes @ np.asarray(reference_cell, dtype=float))
    _assert_vector_close(result["proper_e_C_per_m2"], expected_proper)

    p_minus = np.asarray([minus_reduced["1"], minus_reduced["2"], minus_reduced["3"]])
    p_plus = np.asarray([plus_reduced["1"], plus_reduced["2"], plus_reduced["3"]])
    expected_improper = _E_CHARGE_SCALE * (
        p_plus @ np.asarray(plus_cell, dtype=float) / _cell_volume(plus_cell)
        - p_minus @ np.asarray(minus_cell, dtype=float) / _cell_volume(minus_cell)
    ) / (2.0 * h)
    _assert_vector_close(result["improper_dP_ds_C_per_m2"], expected_improper)


def test_pair_response_common_branch_shift_leaves_slopes_invariant():
    reference_cell = [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]
    reference_volume = _cell_volume(reference_cell)
    h = 0.01
    minus_reduced = {"1": 0.2, "2": -0.4, "3": 0.8}
    plus_reduced = {"1": 0.24, "2": -0.34, "3": 0.83}
    minus = _point("minus", -h, "xx", _strained_cell(reference_cell, "xx", -h), minus_reduced)
    plus = _point("plus", h, "xx", _strained_cell(reference_cell, "xx", h), plus_reduced)
    shifted_minus = copy.deepcopy(minus)
    shifted_plus = copy.deepcopy(plus)
    for point in (shifted_minus, shifted_plus):
        for direction in point["directions"].values():
            direction["branch_integer"] = 3
            direction["reduced_charge"] += 3

    base = _pair_response(_pair("xx"), minus, plus, reference_cell, reference_volume)
    shifted = _pair_response(_pair("xx"), shifted_minus, shifted_plus, reference_cell, reference_volume)

    for gdir in ("1", "2", "3"):
        assert shifted["reduced_slopes_by_gdir"][gdir] == pytest.approx(
            base["reduced_slopes_by_gdir"][gdir]
        )
    _assert_vector_close(shifted["proper_e_C_per_m2"], np.asarray(base["proper_e_C_per_m2"]))


def test_pair_response_reports_missing_direction_without_zero_filling():
    reference_cell = [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]
    h = 0.01
    minus = _point("minus", -h, "zz", _strained_cell(reference_cell, "zz", -h), {"1": 0.1, "2": 0.2}, directions=(1, 2))
    plus = _point("plus", h, "zz", _strained_cell(reference_cell, "zz", h), {"1": 0.2, "2": 0.3}, directions=(1, 2))

    result = _pair_response(_pair("zz"), minus, plus, reference_cell, _cell_volume(reference_cell))

    assert result["reduced_slopes_by_gdir"]["1"] == pytest.approx(5.0)
    assert result["reduced_slopes_by_gdir"]["2"] == pytest.approx(5.0)
    assert result["reduced_slopes_by_gdir"]["3"] is None
    assert any("3" in str(item) for item in result["missing"])
    assert result["proper_e_C_per_m2"] is None
    assert result["improper_dP_ds_C_per_m2"] is None


def test_pair_response_missing_branch_suppresses_only_dependent_outputs():
    reference_cell = [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]
    h = 0.01
    minus = _point("minus", -h, "yy", _strained_cell(reference_cell, "yy", -h), {"1": 0.1, "2": 0.2, "3": 0.3})
    plus = _point("plus", h, "yy", _strained_cell(reference_cell, "yy", h), {"1": 0.2, "2": 0.3, "3": 0.4})
    plus["directions"]["2"]["branch_integer"] = None
    plus["directions"]["2"]["branch_basis"] = None
    plus["directions"]["2"]["reduced_charge"] = None

    result = _pair_response(_pair("yy"), minus, plus, reference_cell, _cell_volume(reference_cell))

    assert result["reduced_slopes_by_gdir"]["1"] == pytest.approx(5.0)
    assert result["reduced_slopes_by_gdir"]["3"] == pytest.approx(5.0)
    assert result["reduced_slopes_by_gdir"]["2"] is None
    assert any("branch" in str(item) and "2" in str(item) for item in result["missing"])
    assert result["proper_e_C_per_m2"] is None
    assert result["improper_dP_ds_C_per_m2"] is None


def test_pair_response_requires_equal_opposite_nonzero_strain_amplitudes():
    reference_cell = [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]
    minus = _point("minus", -0.01, "xx", _strained_cell(reference_cell, "xx", -0.01), {"1": 0.1, "2": 0.2, "3": 0.3})
    plus = _point("plus", 0.02, "xx", _strained_cell(reference_cell, "xx", 0.02), {"1": 0.2, "2": 0.3, "3": 0.4})

    with pytest.raises(ValueError, match="opposite|amplitude|strain"):
        _pair_response(_pair("xx"), minus, plus, reference_cell, _cell_volume(reference_cell))


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _write_software_manifest(tmp_path: Path) -> Path:
    """Build real model/Study artifacts while keeping every source software-only."""

    marker = tmp_path / "software-contract-only.marker"
    marker.write_text("software_contract_only\n", encoding="utf-8")
    cell = [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]
    atoms = Atoms(
        symbols=["Ni", "Ni"],
        cell=cell,
        scaled_positions=[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([0, 1], dtype=int))
    parent = write_model_artifacts(
        atoms,
        tmp_path / "parent-model",
        model_id="software-parent-model",
        version="v001",
        fixture=True,
        fixture_purpose="software_contract_only",
        phase_requested="software_contract_fixture",
        source_path="software-contract-only",
        source_version="software-contract-only",
        material="Ni",
        selection_status="engineering_fixture",
        material_selection_confirmed=False,
        scientific_status="engineering_fixture_not_production",
    )
    parent_study_path = tmp_path / "parent-study.json"
    manifest_path = tmp_path / "response-manifest.json"
    _write_json(
        parent_study_path,
        {
            "study_id": "software-parent-study",
            "case_id": "software_case",
            "case_role": "engineering_fixture",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "model": {
                "model_id": parent.model_id,
                "version": parent.version,
                "source_structure": "model.extxyz",
            },
        },
    )
    parent_identity = {
        "model_id": parent.model_id,
        "version": parent.version,
        "path": str(parent.artifact_dir.resolve()),
        "charge_state": 0,
    }
    response_id = "software-strain-response"
    points = []
    for point_id, strain in (("minus", -0.01), ("plus", 0.01)):
        component = "xx"
        vector = [strain, 0.0, 0.0, 0.0, 0.0, 0.0]
        child_atoms, strain_record = voigt_strain_model(
            parent.atoms,
            vector,
            reference_model={"model_id": parent.model_id, "version": parent.version},
        )
        # A model ID with different explicit versions is a valid pair identity.
        child_model_id = "software-child"
        child_model_version = "v001" if point_id == "minus" else "v002"
        child_study_id = f"software-study-{point_id}"
        child_model_path = tmp_path / "models" / point_id
        parent_frac = parent.atoms.get_scaled_positions(wrap=False)
        child_frac = child_atoms.get_scaled_positions(wrap=False)
        parent_pos = parent.atoms.get_positions()
        child_pos = child_atoms.get_positions()
        lineage = [
            {
                "child_atom_id": int(atom_id),
                "parent_atom_id": int(atom_id),
                "parent_image": [0, 0, 0],
                "parent_frac_coords": [float(value) for value in parent_frac[index]],
                "parent_frac_coords_unwrapped": [float(value) for value in parent_frac[index]],
                "child_frac_coords": [float(value) for value in child_frac[index]],
                "child_frac_coords_unwrapped": [float(value) for value in child_frac[index]],
                "parent_cart_coords_angstrom": [float(value) for value in parent_pos[index]],
                "child_cart_coords_angstrom": [float(value) for value in child_pos[index]],
                "displacement_cartesian_A": [float(value) for value in child_pos[index] - parent_pos[index]],
                "element": str(parent.atoms.get_chemical_symbols()[index]),
                "kind": "voigt_strain_fixed_fractional_atom",
            }
            for index, atom_id in enumerate(parent.atom_ids)
        ]
        derivation = {
            "kind": "berry_fixed_cell_voigt_strain",
            "response_id": response_id,
            "point_id": point_id,
            "voigt_component": component,
            "strain": strain,
            "strain_voigt": vector,
            "strain_record": copy.deepcopy(strain_record),
            "parent_model": copy.deepcopy(parent_identity),
            "parent_study_id": "software-parent-study",
            "parent_study_file": str(parent_study_path.resolve()),
            "charge_state": 0,
            "mechanical_boundary": "clamped_ion_fixed_fractional",
            "relaxation_status": "not_run",
            "production_qualified": False,
            "study_id": child_study_id,
        }
        child = _write_derived(
            parent,
            child_atoms,
            child_model_path,
            {"model_id": child_model_id, "version": child_model_version, "study_id": child_study_id},
            derivation=derivation,
            atom_lineage=lineage,
            basis_transform={
                "kind": "voigt_strain_fixed_fractional",
                "fractional_matrix": np.eye(3, dtype=int).tolist(),
                "fractional_translation": [0.0, 0.0, 0.0],
                "source_lattice_angstrom": np.asarray(parent.atoms.cell.array).tolist(),
                "target_lattice_angstrom": np.asarray(child_atoms.cell.array).tolist(),
                "strain_record": copy.deepcopy(strain_record),
                "parent_model": copy.deepcopy(parent_identity),
            },
            spatial_mode="clamped_ion_fixed_fractional_voigt_strain",
        )
        binding = {
            "schema": "mlcc.abacus-berry-strain-response-binding.v1",
            "response_id": response_id,
            "point_id": point_id,
            "voigt_component": component,
            "strain": strain,
            "strain_voigt": vector,
            "parent_study_id": "software-parent-study",
            "parent_model": copy.deepcopy(parent_identity),
            "child_study_id": child_study_id,
            "child_model_id": child_model_id,
            "child_model_version": child_model_version,
            "mechanical_boundary": "clamped_ion_fixed_fractional",
            "charge_state": 0,
        }
        model_json = json.loads((child.artifact_dir / "model.json").read_text(encoding="utf-8"))
        model_json["berry_strain_response"] = copy.deepcopy(binding)
        _write_json(child.artifact_dir / "model.json", model_json)
        child_study_path = tmp_path / "studies" / f"{point_id}.json"
        _write_json(
            child_study_path,
            {
                "study_id": child_study_id,
                "case_id": "software_case",
                "case_role": "engineering_fixture",
                "fixture": True,
                "fixture_purpose": "software_contract_only",
                "model": {
                    "model_id": child_model_id,
                    "version": child_model_version,
                    "source_structure": str((child.artifact_dir / "model.extxyz").resolve()),
                },
                "parent_study_id": "software-parent-study",
                "derived_from": {
                    "study_id": "software-parent-study",
                    "model_id": parent.model_id,
                    "model_version": parent.version,
                    "reason": "software contract fixture",
                    "parent_study_file": str(parent_study_path.resolve()),
                },
                "berry_strain_response": copy.deepcopy(binding),
            },
        )
        scf_task_path = tmp_path / "tasks" / point_id / "task.json"
        scf_binding = copy.deepcopy(binding)
        scf_binding.update(
            {
                "task_kind": "reference_scf",
                "gdir": None,
                "task_id": f"software-scf-{point_id}",
                "task_path": str(scf_task_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "source_scf_task_id": f"software-scf-{point_id}",
                "source_scf_task_path": str(scf_task_path.resolve()),
            }
        )
        _write_json(
            scf_task_path,
            {
                "task_id": f"software-scf-{point_id}",
                "model_path": str(child.artifact_dir.resolve()),
                "study_file": str(child_study_path.resolve()),
                "fixture": True,
                "fixture_purpose": "software_contract_only",
                "berry_strain_response": scf_binding,
            },
        )
        points.append(
            {
                "point_id": point_id,
                "child_model_id": child_model_id,
                "child_model_version": child_model_version,
                "child_study_id": child_study_id,
                "scf_task_id": f"software-scf-{point_id}",
                "voigt_component": component,
                "strain": strain,
                "strain_voigt": vector,
                "strain_record": copy.deepcopy(strain_record),
                "gdirs": [1, 2, 3],
                "model_path": str(child.artifact_dir.resolve()),
                "study_path": str(child_study_path.resolve()),
                "scf_request_path": str(marker.resolve()),
                "scf_task_path": str(scf_task_path.resolve()),
                "scf_task": {
                    "task_id": f"software-scf-{point_id}",
                    "fixture": True,
                    "fixture_purpose": "software_contract_only",
                },
                "nscf_tasks": [],
            }
        )
    _write_json(
        manifest_path,
        {
            "schema": "mlcc.abacus-berry-strain-response.v1",
            "response_id": response_id,
            "manifest_path": str(manifest_path.resolve()),
            "request_path": str((tmp_path / "software-input.json").resolve()),
            "method_path": str(marker.resolve()),
            "site_path": str(marker.resolve()),
            "status": "scf_inputs_written_not_submitted",
            "mechanical_boundary": "clamped_ion_fixed_fractional",
            "charge_state": 0,
            "qualification": False,
            "evidence_kind": "software_contract_only",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "parent_study": {
                "study_id": "software-parent-study",
                "study_path": str(parent_study_path.resolve()),
            },
            "parent_model": parent_identity,
            "reference_lattice_angstrom": cell,
            "reference_volume_A3": _cell_volume(cell),
            "voigt_order": ["xx", "yy", "zz", "yz", "xz", "xy"],
            "engineering_shear": True,
            "points": points,
        },
    )
    return manifest_path


def test_public_consumer_keeps_missing_sources_explicit_for_software_contract_manifest(tmp_path):
    manifest_path = _write_software_manifest(tmp_path)
    request_path = tmp_path / "software-input.json"
    _write_json(
        request_path,
        {
            "schema": "mlcc.polarization-strain-request.v1",
            "response_id": "software-strain-response",
            "manifest_path": str(manifest_path),
            "pairs": [{"pair_id": "xx-h", "voigt_component": "xx", "minus_point_id": "minus", "plus_point_id": "plus"}],
            "sources": [],
            "evidence_kind": "software_contract_only",
        },
    )

    result = analyze_polarization_strain(request_path)

    assert result["schema"] == "mlcc.polarization-strain.v1"
    assert result["evidence_kind"] == "software_contract_only"
    assert result["native_jobs"] == []
    assert result["missing"]
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False
    _write_json(tmp_path / "unresolved-result.json", result)

    # This is a software-only result: retain the real generated model/Study
    # paths and distinguish the complete helper arithmetic from absent native
    # sources.  The file is the single handoff artifact copied by acceptance.
    minus = _point("minus", -0.01, "xx", _strained_cell(
        [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]], "xx", -0.01
    ), {"1": 0.1, "2": 0.2, "3": 0.3})
    plus = _point("plus", 0.01, "xx", _strained_cell(
        [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]], "xx", 0.01
    ), {"1": 0.2, "2": 0.3, "3": 0.4})
    software_math_pair = _pair_response(
        _pair("xx"), minus, plus,
        [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]],
        _cell_volume([[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]),
    )
    saved = copy.deepcopy(result)
    saved["pairs"] = [software_math_pair]
    saved["missing"] = []
    saved["status"] = "calculated_unqualified"
    saved["source_validation"] = "not_native_software_math_only"
    saved["native_jobs"] = []
    saved["parent_model_path"] = result["parent"]["model_path"]
    saved["software_math_points"] = [minus, plus]
    saved["points"] = [{**point, "directions": math_point["directions"]}
                       for point, math_point in zip(result["points"], (minus, plus))]
    handoff_request = json.loads(request_path.read_text(encoding="utf-8"))
    _write_json(tmp_path / "public-missing-request.json", handoff_request)
    handoff_request["schema"] = "mlcc.polarization-strain-software-math-input.v1"
    handoff_request["source_validation"] = "not_native_software_math_only"
    handoff_request["reference_cell_angstrom"] = [[4.0, 0.5, 0.2], [0.0, 3.0, 0.4], [0.0, 0.0, 5.0]]
    handoff_request["reference_volume_A3"] = _cell_volume(handoff_request["reference_cell_angstrom"])
    handoff_request["software_math_points"] = [minus, plus]
    _write_json(request_path, handoff_request)
    saved["input_path"] = str(request_path.resolve())
    software_result_path = tmp_path / "software-result.json"
    _write_json(software_result_path, saved)
    assert software_result_path.is_file()


def _consumer_request(
    tmp_path: Path,
    manifest_path: Path,
    *,
    sources: list[dict[str, object]] | None = None,
    pairs: list[dict[str, object]] | None = None,
) -> Path:
    request_path = tmp_path / "software-input.json"
    _write_json(
        request_path,
        {
            "schema": "mlcc.polarization-strain-request.v1",
            "response_id": "software-strain-response",
            "manifest_path": str(manifest_path.resolve()),
            "pairs": pairs or [_pair("xx")],
            "sources": [] if sources is None else sources,
            "evidence_kind": "software_contract_only",
        },
    )
    return request_path


@pytest.mark.parametrize("mutation", ["parent", "fraction", "cell", "charge"])
def test_public_rejects_parent_fraction_cell_and_charge_mismatch(tmp_path, mutation):
    manifest_path = _write_software_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    point = manifest["points"][0]
    if mutation == "parent":
        child_model_json_path = Path(point["model_path"]) / "model.json"
        child_model = json.loads(child_model_json_path.read_text(encoding="utf-8"))
        child_model["parent_models"][0]["model_id"] = "different-parent"
        _write_json(child_model_json_path, child_model)
    elif mutation == "fraction":
        child_model_path = Path(point["model_path"])
        child_atoms = ase_read(str(child_model_path / "model.extxyz"), format="extxyz", index=0)
        fractions = child_atoms.get_scaled_positions(wrap=False)
        fractions[0, 0] += 0.1
        child_atoms.set_scaled_positions(fractions)
        ase_write(str(child_model_path / "model.extxyz"), child_atoms, format="extxyz")
        child_model_json_path = child_model_path / "model.json"
        child_model = json.loads(child_model_json_path.read_text(encoding="utf-8"))
        child_model["atoms"][0]["frac_coords"] = [float(value) for value in fractions[0]]
        child_model["atoms"][0]["cart_coords_angstrom"] = [float(value) for value in child_atoms.get_positions()[0]]
        _write_json(child_model_json_path, child_model)
    elif mutation == "cell":
        manifest["points"][0]["strain_record"]["derived_lattice_angstrom"][0][0] += 0.1
        _write_json(manifest_path, manifest)
    elif mutation == "charge":
        manifest["parent_model"]["charge_state"] = 1
        _write_json(manifest_path, manifest)
    else:
        raise AssertionError(mutation)
    request_path = _consumer_request(tmp_path, manifest_path)
    with pytest.raises(ValueError):
        analyze_polarization_strain(request_path)


def test_public_rejects_unregistered_saved_direction(tmp_path):
    manifest_path = _write_software_manifest(tmp_path)
    source = {
        "point_id": "minus",
        "gdir": 1,
        "task_file": str((tmp_path / "not-registered-task.json").resolve()),
        "result_file": str((tmp_path / "not-registered-result.json").resolve()),
        "branch_integer": 0,
        "branch_basis": "software-contract-basis",
    }
    request_path = _consumer_request(tmp_path, manifest_path, sources=[source])
    with pytest.raises(ValueError, match="registered"):
        analyze_polarization_strain(request_path)


def test_public_rejects_duplicate_pair_id(tmp_path):
    manifest_path = _write_software_manifest(tmp_path)
    duplicate_pairs = [_pair("xx"), _pair("xx")]
    request_path = _consumer_request(tmp_path, manifest_path, pairs=duplicate_pairs)
    with pytest.raises(ValueError, match="duplicate pair_id"):
        analyze_polarization_strain(request_path)


def test_public_rejects_duplicate_source_before_second_source_read(tmp_path, monkeypatch):
    manifest_path = _write_software_manifest(tmp_path)
    source = {
        "point_id": "minus",
        "gdir": 1,
        "task_file": str((tmp_path / "software-nscf-task.json").resolve()),
        "result_file": str((tmp_path / "software-nscf-result.json").resolve()),
        "branch_integer": 0,
        "branch_basis": "software-contract-basis",
    }

    def software_stub(_source, _point, _manifest, _geometry):
        return (
            {"reduced_charge": 0.0, "source_record": {"native_job": None, "scf_job": None}},
            {"method_set": "software-contract-only"},
        )

    monkeypatch.setattr(polarization_strain, "_saved_direction", software_stub)
    request_path = _consumer_request(tmp_path, manifest_path, sources=[source, copy.deepcopy(source)])
    with pytest.raises(ValueError, match="unknown/duplicate"):
        analyze_polarization_strain(request_path)


def _saved_direction_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object], Path, Path]:
    manifest_path = _write_software_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    point = manifest["points"][0]
    child_model = json.loads((Path(point["model_path"]) / "model.json").read_text(encoding="utf-8"))
    binding = copy.deepcopy(child_model["berry_strain_response"])
    task_path = tmp_path / "nscf" / "task.json"
    task_binding = copy.deepcopy(binding)
    task_binding.update(
        {
            "gdir": 1,
            "task_kind": "nscf",
            "task_id": "software-nscf-minus-gdir1",
            "task_path": str(task_path.resolve()),
            "manifest_path": manifest["manifest_path"],
            "source_scf_task_id": point["scf_task_id"],
            "source_scf_task_path": point["scf_task_path"],
        }
    )
    _write_json(
        task_path,
        {
            "task_id": "software-nscf-minus-gdir1",
            "model_path": point["model_path"],
            "study_file": point["study_path"],
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "berry_strain_response": task_binding,
        },
    )
    point["nscf_tasks"] = [{"gdir": 1, "task_id": "software-nscf-minus-gdir1", "task_path": str(task_path.resolve())}]

    method_path = tmp_path / "nscf" / "method.json"
    method = {
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "evidence_kind": "software_contract_only",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "abacus_version_target": "3.10.1",
        "basis_type": "pw",
        "dft_functional": "PBE",
        "nspin": 1,
        "occupations": "fixed",
        "lspinorb": False,
        "noncolin": False,
        "net_charge": 0,
        "nelec_delta": 0,
        "nelec": 0,
        "element_order": ["Ni"],
        "kpoints": [2, 2, 2],
        "pseudopotentials": {"Ni": {"filename": "Ni.upf"}},
        "pseudopotential_ids": {"Ni": "Ni.upf"},
        "pseudopotential_metadata": {"Ni": {"element": "Ni", "filename": "Ni.upf", "valence_electrons_per_atom": 1}},
        "pseudopotential_treatment": {"Ni": "scalar"},
        "method_set": "software-contract-only",
        "parameters": {"ecutwfc_Ry": 100, "scf_thr": 1.0e-4},
        "science": {
            "dft_functional": "PBE",
            "nspin": 1,
            "lspinorb": False,
            "noncolin": False,
            "occupations": "fixed",
            "net_charge": 0,
            "pseudopotential_treatment": {"Ni": "scalar"},
            "suffix": "OUT",
        },
    }
    _write_json(method_path, method)
    configured_method_path = tmp_path / "nscf" / "configured-method.json"
    _write_json(configured_method_path, method)
    manifest["method_path"] = str(configured_method_path.resolve())
    input_text = "\n".join(
        [
            "INPUT_PARAMETERS",
            "efield_flag 0",
            "dip_cor_flag 0",
            "gate_flag 0",
            "nelec 0",
            "nelec_delta 0",
        ]
    ) + "\n"
    input_path = tmp_path / "nscf" / "INPUT"
    native_input_path = tmp_path / "nscf" / "OUT" / "INPUT"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(input_text, encoding="utf-8")
    native_input_path.parent.mkdir(parents=True, exist_ok=True)
    native_input_path.write_text(input_text, encoding="utf-8")

    direction = np.asarray(point["strain_record"]["derived_lattice_angstrom"], dtype=float)[0]
    volume = float(point["strain_record"]["derived_volume_A3"])
    expected_q = (
        np.linalg.norm(direction) * BOHR_PER_ANGSTROM / (volume * BOHR_PER_ANGSTROM**3)
        * _E_PER_BOHR2_TO_C_PER_M2
    )
    result_path = tmp_path / "nscf" / "result.json"
    _write_json(
        result_path,
        {
            "evidence_kind": "software_contract_only",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "native_pp_valence_electrons": {"Ni.upf": 1.0},
            "quantum_check": {
                "quantum_factor": 1,
                "rmod_bohr": np.linalg.norm(direction) * BOHR_PER_ANGSTROM,
                "cell_volume_bohr3": volume * BOHR_PER_ANGSTROM**3,
                "quantum_C_per_m2": expected_q,
            },
        },
    )
    representative = 0.05
    stub_record = {
        "case": {"case_id": "software_case", "case_role": "engineering_fixture", "fixture": True},
        "model": {"model_id": point["child_model_id"], "version": point["child_model_version"]},
        "scf_job": {"task_file": point["scf_task_path"]},
        "source": {
            "method_file": str(method_path.resolve()),
            "source_files": {
                "INPUT": str(input_path.resolve()),
                "native_INPUT": str(native_input_path.resolve()),
            },
        },
        "polarization": {
            "representative_P_C_per_m2": representative,
            "quantum_Q_C_per_m2": round(expected_q, 7),
        },
        "geometry": {
            "composition": {"Ni": 2},
            "fixed_cell": True,
            "cell_constraint": "fixed_cell",
            "case": {
                "case_id": "software_case",
                "case_role": "engineering_fixture",
                "fixture": True,
            },
        },
        "common_method": copy.deepcopy(method),
    }
    source = {
        "point_id": point["point_id"],
        "gdir": 1,
        "task_file": str(task_path.resolve()),
        "result_file": str(result_path.resolve()),
        "branch_integer": 0,
        "branch_basis": "software-contract-basis",
    }
    geometry = {
        "cell_angstrom": point["strain_record"]["derived_lattice_angstrom"],
        "volume_A3": point["strain_record"]["derived_volume_A3"],
        "case": {
            "case_id": "software_case",
            "case_role": "engineering_fixture",
            "fixture": True,
        },
    }
    return source, point, manifest, geometry, stub_record, method_path


def test_saved_direction_validates_software_method_and_historical_quantum_units(tmp_path, monkeypatch):
    source, point, manifest, geometry, stub_record, _method_path = _saved_direction_fixture(tmp_path)
    monkeypatch.setattr(polarization_strain, "_point_record", lambda *_args, **_kwargs: copy.deepcopy(stub_record))
    direction, method = polarization_strain._saved_direction(source, point, manifest, geometry)

    assert direction["quantum_factor"] == 1
    assert direction["reduced_charge"] == pytest.approx(
        stub_record["polarization"]["representative_P_C_per_m2"]
        / stub_record["polarization"]["quantum_Q_C_per_m2"]
    )
    assert method == stub_record["common_method"]
    assert "native_job" not in direction["source_record"]


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("nscf", "study_file"),
        ("nscf", "manifest_path"),
        ("nscf", "task_kind"),
        ("scf", "schema"),
        ("nscf", "child_model_id"),
    ],
)
def test_saved_direction_rejects_task_binding_identity_mismatches(tmp_path, monkeypatch, target, field):
    source, point, manifest, geometry, stub_record, _method_path = _saved_direction_fixture(tmp_path)
    if target == "scf":
        task_path = Path(point["scf_task_path"])
    else:
        task_path = Path(source["task_file"])
    task = json.loads(task_path.read_text(encoding="utf-8"))
    if field == "study_file":
        task["study_file"] = str((tmp_path / "wrong-study.json").resolve())
    elif field == "manifest_path":
        task["berry_strain_response"][field] = str((tmp_path / "wrong-manifest.json").resolve())
    elif field == "task_kind":
        task["berry_strain_response"][field] = "reference_scf"
    elif field == "schema":
        task["berry_strain_response"][field] = "wrong-schema"
    elif field == "child_model_id":
        task["berry_strain_response"][field] = "wrong-child-model"
    else:
        raise AssertionError(field)
    _write_json(task_path, task)
    monkeypatch.setattr(polarization_strain, "_point_record", lambda *_args, **_kwargs: copy.deepcopy(stub_record))
    with pytest.raises(ValueError):
        polarization_strain._saved_direction(source, point, manifest, geometry)


@pytest.mark.parametrize("failure", ["method", "quantum", "pseudopotential"])
def test_saved_direction_rejects_method_quantum_or_pp_mismatch(tmp_path, monkeypatch, failure):
    source, point, manifest, geometry, stub_record, method_path = _saved_direction_fixture(tmp_path)
    if failure == "method":
        method = json.loads(method_path.read_text(encoding="utf-8"))
        method["nspin"] = 2
        _write_json(method_path, method)
    elif failure == "quantum":
        result_path = Path(source["result_file"])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["quantum_check"]["quantum_factor"] = 2
        _write_json(result_path, result)
    elif failure == "pseudopotential":
        result_path = Path(source["result_file"])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["native_pp_valence_electrons"] = {"different.upf": 1.0}
        _write_json(result_path, result)
    else:
        raise AssertionError(failure)
    monkeypatch.setattr(polarization_strain, "_point_record", lambda *_args, **_kwargs: copy.deepcopy(stub_record))
    with pytest.raises(ValueError):
        polarization_strain._saved_direction(source, point, manifest, geometry)


def _relaxed_constraints(scope: str) -> dict[str, object]:
    if scope == "all_internal_dofs":
        flags = [[1, 1, 1], [1, 1, 1]]
    elif scope == "selected_internal_dofs":
        # The first atom is the selected internal subspace.  Keeping each
        # atom's Cartesian mask whole makes the fixture valid for the
        # producer's partial-mask rule on the oblique software cell.
        flags = [[1, 1, 1], [0, 0, 0]]
    else:
        raise AssertionError(scope)
    return {
        "schema": "mlcc.ionic-constraints.v1",
        "coordinate_basis": "cartesian",
        "atom_ids": [0, 1],
        "move_flags": flags,
        "relax_new": True,
        "origin": "explicit_request",
    }


def _relaxed_method(pre_model, method_path: Path, constraints: dict[str, object]) -> dict[str, object]:
    method = {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "abacus_version_target": "3.10.1",
        "stage": "relax",
        "model_id": pre_model.model_id,
        "version": pre_model.version,
        "method_set": "software-relaxed-strain-v001",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "basis_type": "pw",
        "dft_functional": "PBE",
        "ks_solver": "cg",
        "relax_method": "cg",
        "mixing_type": "plain",
        "mixing_beta": 0.7,
        "symmetry": 1,
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "smearing_method": "fixed",
        "smearing_sigma_Ry": 0.0,
        "element_order": ["Ni"],
        "kpoints": [2, 2, 2],
        "net_charge": 0,
        "initial_moments_muB_by_element": {"Ni": 0.0},
        "pseudopotentials": {"Ni": {"filename": "Ni.upf"}},
        "pseudopotential_ids": {"Ni": "Ni.upf"},
        "pseudopotential_metadata": {
            "Ni": {
                "element": "Ni",
                "filename": "Ni.upf",
                "valence_electrons_per_atom": 1,
            }
        },
        "pseudopotential_treatment": {"Ni": "scalar"},
        "parameters": {
            "ecutwfc_Ry": 100,
            "scf_thr": 1.0e-4,
            "scf_nmax": 100,
            "relax_nmax": 8,
            "force_thr_eV_per_A": 0.02,
        },
        "ionic_constraints": copy.deepcopy(constraints),
        "source_path": str(method_path.resolve()),
    }
    _write_json(method_path, method)
    return method


def _relaxed_source_fixture(
    tmp_path: Path,
    point: dict[str, object],
    *,
    scope: str,
    manifest_path: Path,
) -> dict[str, object]:
    """Create explicit software-only bridge source files for one endpoint.

    The pre-relax model and strain record come from the existing software
    strain fixture.  The saved relax/task/result files follow the 0.25 bridge
    contract, then the real ``derive_relaxed_structure`` entry creates the
    final model, Study, and bridge consumed by the producer helper.
    """
    from mlcc.relaxed_structure_bridge import derive_relaxed_structure

    constraints = _relaxed_constraints(scope)
    pre_model = read_model_artifacts(point["model_path"])
    pre_study_path = Path(point["study_path"])
    pre_study = json.loads(pre_study_path.read_text(encoding="utf-8"))
    pre_study["model"].update(
        material=pre_model.metadata["material"],
        phase_requested=pre_model.metadata["phase_requested"],
        path=str(pre_model.artifact_dir.resolve()),
        model_path=str(pre_model.artifact_dir.resolve()),
    )
    _write_json(pre_study_path, pre_study)

    endpoint = str(point["point_id"])
    source_dir = tmp_path / "relax-sources" / endpoint
    source_dir.mkdir(parents=True, exist_ok=True)
    method_path = source_dir / "method.json"
    method = _relaxed_method(pre_model, method_path, constraints)

    final_atoms = pre_model.atoms.copy()
    sign = -1.0 if endpoint == "minus" else 1.0
    for atom_index, flags in enumerate(constraints["move_flags"]):
        for axis, movable in enumerate(flags):
            if movable:
                final_atoms.positions[atom_index, axis] += sign * 0.004 * (atom_index + 1)
    final_path = source_dir / "final.extxyz"
    if "atom_id" in final_atoms.arrays:
        final_atoms.set_array("atom_id", np.asarray(pre_model.atom_ids, dtype=int))
    else:
        final_atoms.new_array("atom_id", np.asarray(pre_model.atom_ids, dtype=int))
    ase_write(str(final_path), final_atoms, format="extxyz")

    running_log = source_dir / "running_relax.log"
    stru_ion_d = source_dir / "STRU_ION_D"
    atom_map_path = source_dir / "STRU.atom-map.json"
    input_path = source_dir / "INPUT"
    running_log.write_text("software_contract_only relax log\n", encoding="utf-8")
    stru_ion_d.write_text("software_contract_only STRU_ION_D\n", encoding="utf-8")
    input_path.write_text("INPUT_PARAMETERS\ncalculation relax\n", encoding="utf-8")
    atom_map = {
        "schema": "mlcc.abacus-atom-map.v1",
        "abacus_version_target": "3.10.1",
        "model_id": pre_model.model_id,
        "version": pre_model.version,
        "source_atom_ids": pre_model.atom_ids,
        "element_order": ["Ni"],
        "abacus_order": [
            {
                "abacus_index": index,
                "source_index": index,
                "atom_id": atom_id,
                "element": pre_model.atoms[index].symbol,
                "label": f"Ni{index + 1}",
            }
            for index, atom_id in enumerate(pre_model.atom_ids)
        ],
    }
    _write_json(atom_map_path, atom_map)
    source_files = {
        "running_relax.log": str(running_log.resolve()),
        "STRU_ION_D": str(stru_ion_d.resolve()),
        "STRU.atom-map.json": str(atom_map_path.resolve()),
        "method.json": str(method_path.resolve()),
        "INPUT": str(input_path.resolve()),
    }
    task_id = f"software-relax-{endpoint}"
    job_id = f"software-relax-job-{endpoint}"
    result_path = source_dir / "result.json"
    task_path = source_dir / "task.json"
    relaxation = {
        "schema": "mlcc.fixed-cell-relaxation-result.v1",
        "cell_constraint": "fixed_cell",
        "ionic_constraints": copy.deepcopy(constraints),
        "relax_new": True,
        "ionic_steps": 3,
        "relax_nmax": 8,
        "native_stop_reason": "ionic_converged",
        "native_marker_text": "Relaxation is converged!",
        "electronic_converged": True,
        "ionic_converged": True,
        "native_completed": True,
        "force_metric": "max_abs_movable_cartesian_component",
        "force_threshold_eV_per_A": 0.02,
        "max_free_force_component_eV_per_A": 0.001,
        "max_all_force_component_eV_per_A": 0.001,
        "fixed_cell_verified": True,
        "frozen_dofs_verified": True,
        "final_geometry_matches_last_evaluation": True,
        "final_geometry_role": "last_evaluated_ionic_step",
        "geometry_promotable": True,
        "source_files": {**source_files, "result.json": str(result_path.resolve())},
    }
    result = {
        "schema": "mlcc.abacus-result.v1",
        "task_id": task_id,
        "scheduler_job_id": job_id,
        "method_set": method["method_set"],
        "stage": "relax",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "energy_eV": -100.0,
        "forces_eV_per_A": [[0.001, 0.0, 0.0] for _ in pre_model.atoms],
        "stress_GPa": [[0.0, 0.0, 0.0] for _ in range(3)],
        "atom_ids": pre_model.atom_ids,
        "final_structure_file": str(final_path.resolve()),
        "final_atoms": {
            "symbols": final_atoms.get_chemical_symbols(),
            "positions_angstrom": final_atoms.positions.tolist(),
            "cell_angstrom": final_atoms.cell.array.tolist(),
            "pbc": [True, True, True],
        },
        "electronic_converged": True,
        "ionic_converged": True,
        "native_completed": True,
        "scientific_status": "converged_engineering_fixture",
        "source_files": source_files,
        "relaxation": relaxation,
    }
    _write_json(result_path, result)
    task = {
        "schema": "mlcc.task.v1",
        "task_id": task_id,
        "stage": "P4",
        "calculation": "relax",
        "input_transformation": None,
        "engine": "abacus",
        "engine_version": "3.10.1",
        "model_id": pre_model.model_id,
        "model_version": pre_model.version,
        "model_path": str(pre_model.artifact_dir.resolve()),
        "method_set": method["method_set"],
        "method_file": str(method_path.resolve()),
        "study_id": pre_study["study_id"],
        "study_file": str(pre_study_path.resolve()),
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "production_label": False,
        "runner": "slurm",
        "scheduler_job_id": job_id,
        "status": "COMPLETED",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "result_file": str(result_path.resolve()),
        "final_structure_file": str(final_path.resolve()),
        "ionic_constraints": copy.deepcopy(constraints),
        "relaxation": copy.deepcopy(relaxation),
        "source_files": {**source_files, "result.json": str(result_path.resolve())},
    }
    _write_json(task_path, task)

    request_path = source_dir / "bridge-request.json"
    child_model_id = f"software-relaxed-{endpoint}"
    child_study_id = f"software-relaxed-study-{endpoint}"
    _write_json(
        request_path,
        {
            "schema": "mlcc.relaxed-structure-bridge-request.v1",
            "model_id": child_model_id,
            "version": "v001",
            "study_id": child_study_id,
            "case_id": "software_case",
            "case_role": "engineering_fixture",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "evidence_kind": "software_contract_only",
        },
    )
    bridge_dir = tmp_path / "relaxed-bridges" / endpoint
    bridge = derive_relaxed_structure(
        task_path=task_path,
        parent_model_path=pre_model.artifact_dir,
        study_path=pre_study_path,
        request_path=request_path,
        output_path=bridge_dir,
    )
    final_model = read_model_artifacts(bridge_dir / "model")
    final_study_path = bridge_dir / "study.json"
    final_study = json.loads(final_study_path.read_text(encoding="utf-8"))
    scf_task_id = f"software-relaxed-scf-{endpoint}"
    scf_task_path = source_dir / "scf-task.json"
    _write_json(
        scf_task_path,
        {
            "task_id": scf_task_id,
            "model_id": final_model.model_id,
            "model_version": final_model.version,
            "model_path": str(final_model.artifact_dir.resolve()),
            "study_id": final_study["study_id"],
            "study_file": str(final_study_path.resolve()),
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "berry_strain_response": {
                "source": "software_contract_only",
                "relaxed_structure_bridge": str((bridge_dir / "bridge.json").resolve()),
            },
        },
    )
    return {
        "constraints": constraints,
        "scope": scope,
        "pre_model": pre_model,
        "pre_study": pre_study,
        "pre_study_path": pre_study_path,
        "final_model": final_model,
        "final_study": final_study,
        "final_study_path": final_study_path,
        "bridge": bridge,
        "bridge_path": bridge_dir / "bridge.json",
        "source": bridge["relaxation_source"],
        "scf_task_id": scf_task_id,
        "scf_task_path": scf_task_path,
    }


def _write_relaxed_software_manifest(tmp_path: Path, boundary: str) -> tuple[Path, dict[str, object]]:
    if boundary not in ("relaxed_ion_fixed_cell", "constrained_ion_fixed_cell"):
        raise AssertionError(boundary)
    scope = "all_internal_dofs" if boundary == "relaxed_ion_fixed_cell" else "selected_internal_dofs"
    manifest_path = _write_software_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parent_study_path = Path(manifest["parent_study"]["study_path"])
    parent_study = json.loads(parent_study_path.read_text(encoding="utf-8"))
    parent_model = read_model_artifacts(manifest["parent_model"]["path"])
    parent_study["model"].update(
        material=parent_model.metadata["material"],
        phase_requested=parent_model.metadata["phase_requested"],
        path=str(parent_model.artifact_dir.resolve()),
        model_path=str(parent_model.artifact_dir.resolve()),
    )
    _write_json(parent_study_path, parent_study)
    infos = {}
    for point in manifest["points"]:
        info = _relaxed_source_fixture(
            tmp_path,
            point,
            scope=scope,
            manifest_path=manifest_path,
        )
        info["point_id"] = point["point_id"]
        point.update(
            {
                "child_model_id": info["final_model"].model_id,
                "child_model_version": info["final_model"].version,
                "child_study_id": info["final_study"]["study_id"],
                "model_path": str(info["final_model"].artifact_dir.resolve()),
                "study_path": str(info["final_study_path"].resolve()),
                "mechanical_boundary": boundary,
                "scf_task_id": info["scf_task_id"],
                "scf_task_path": str(info["scf_task_path"].resolve()),
                "relaxed_structure_bridge": str(info["bridge_path"].resolve()),
                "relaxation_source": copy.deepcopy(info["source"]),
                "ionic_constraints": copy.deepcopy(info["constraints"]),
                "relaxation_scope": info["scope"],
                "pre_relax_model": {
                    "model_id": info["pre_model"].model_id,
                    "version": info["pre_model"].version,
                    "path": str(info["pre_model"].artifact_dir.resolve()),
                },
                "pre_relax_study": {
                    "study_id": info["pre_study"]["study_id"],
                    "study_path": str(info["pre_study_path"].resolve()),
                },
                "nscf_tasks": [],
            }
        )
        infos[point["point_id"]] = info
    # Relaxed pair validation compares this configured physical method with
    # the explicit method JSON recorded by each bridge source.
    manifest["method_path"] = str(infos["minus"]["source"]["method_file"])
    manifest.update(
        {
            "mechanical_boundary": boundary,
            "relaxation_scope": scope,
            "evidence_kind": "software_contract_only",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "points": manifest["points"],
        }
    )
    _write_json(manifest_path, manifest)
    return manifest_path, {"manifest": manifest, "points": infos, "scope": scope, "boundary": boundary}


@pytest.mark.parametrize(
    ("boundary", "scope", "response_type"),
    [
        ("relaxed_ion_fixed_cell", "all_internal_dofs", "relaxed_ion_stress_form_piezoelectric_e"),
        ("constrained_ion_fixed_cell", "selected_internal_dofs", "constrained_ion_stress_form_piezoelectric_e"),
    ],
)
def test_relaxed_boundaries_preserve_root_pre_final_chain_and_labels(
    tmp_path, boundary, scope, response_type,
):
    manifest_path, fixture = _write_relaxed_software_manifest(tmp_path, boundary)
    request_path = _consumer_request(tmp_path, manifest_path)

    result = analyze_polarization_strain(request_path)

    assert result["mechanical_boundary"] == boundary
    assert result["relaxation_scope"] == scope
    assert result["response_type"] == response_type
    assert result["ionic_constraints"] == fixture["points"]["minus"]["constraints"]
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False
    assert result["native_jobs"]
    assert {job["role"] for job in result["native_jobs"]} == {"relax"}
    if boundary == "relaxed_ion_fixed_cell":
        assert result["relaxed_ion_response"] is not None
        assert result["constrained_ion_response"] is None
    else:
        assert result["relaxed_ion_response"] is None
        assert result["constrained_ion_response"] is not None
        assert "full_relaxed_ion" in result["out_of_scope"]
    for point in result["points"]:
        info = fixture["points"][point["point_id"]]
        assert point["mechanical_boundary"] == boundary
        assert point["relaxation_scope"] == scope
        assert point["ionic_constraints"] == info["constraints"]
        assert point["relaxed_structure_bridge"] == str(info["bridge_path"].resolve())
        assert point["pre_relax_model"] == {
            "model_id": info["pre_model"].model_id,
            "version": info["pre_model"].version,
            "path": str(info["pre_model"].artifact_dir.resolve()),
        }
        assert point["pre_relax_study"]["study_id"] == info["pre_study"]["study_id"]
        assert point["relaxation_source"] == info["source"]
        assert point["model_id"] == info["final_model"].model_id
        assert point["study_id"] == info["final_study"]["study_id"]
        assert np.allclose(info["pre_model"].atoms.cell.array, info["final_model"].atoms.cell.array)
        displacement = info["final_model"].atoms.positions - info["pre_model"].atoms.positions
        move_flags = np.asarray(info["constraints"]["move_flags"], dtype=bool)
        assert np.allclose(displacement[~move_flags], 0.0, atol=1e-12, rtol=0)
        assert not np.allclose(displacement[move_flags], 0.0, atol=1e-12, rtol=0)
        assert (info["pre_model"].model_id, info["pre_model"].version) in [
            (record["model_id"], record["version"]) for record in info["final_model"].metadata["parent_models"]
        ]
        assert (fixture["manifest"]["parent_model"]["model_id"], fixture["manifest"]["parent_model"]["version"]) in [
            (record["model_id"], record["version"]) for record in info["pre_model"].metadata["parent_models"]
        ]
    pair = result["pairs"][0]
    assert pair["reduced_slopes_by_gdir"] == {"1": None, "2": None, "3": None}
    assert pair["proper_e_C_per_m2"] is None
    assert pair["improper_dP_ds_C_per_m2"] is None
    assert result["missing"]


@pytest.mark.parametrize("mutation", ["relax_source", "bridge", "mask"])
def test_relaxed_consumer_rejects_borrowed_relax_source_bridge_or_mask(tmp_path, mutation):
    manifest_path, fixture = _write_relaxed_software_manifest(tmp_path, "relaxed_ion_fixed_cell")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    point = manifest["points"][0]
    if mutation == "relax_source":
        point["relaxation_source"] = copy.deepcopy(
            fixture["points"]["plus"]["source"]
        )
    elif mutation == "bridge":
        point["relaxed_structure_bridge"] = str(
            fixture["points"]["plus"]["bridge_path"].resolve()
        )
    elif mutation == "mask":
        point["ionic_constraints"]["move_flags"] = [[0, 0, 0], [1, 1, 1]]
    else:
        raise AssertionError(mutation)
    _write_json(manifest_path, manifest)
    request_path = _consumer_request(tmp_path, manifest_path)
    with pytest.raises((ValueError, FileNotFoundError)):
        analyze_polarization_strain(request_path)


def test_relaxed_consumer_rejects_borrowed_reference_scf_task(tmp_path, monkeypatch):
    source, point, manifest, geometry, stub_record, _method_path = _saved_direction_fixture(tmp_path)
    manifest["mechanical_boundary"] = "relaxed_ion_fixed_cell"
    manifest["relaxation_scope"] = "all_internal_dofs"
    relaxed_fields = {
        "mechanical_boundary": "relaxed_ion_fixed_cell",
        "relaxation_scope": "all_internal_dofs",
        "pre_relax_model": {
            "model_id": "software-pre-relax-model",
            "version": "v001",
            "path": str((tmp_path / "pre-relax-model").resolve()),
        },
        "pre_relax_study": {
            "study_id": "software-pre-relax-study",
            "study_path": str((tmp_path / "pre-relax-study.json").resolve()),
        },
        "relaxed_structure_bridge": str((tmp_path / "relaxed-bridge.json").resolve()),
        "relaxation_source": {"task_id": "software-relax-minus", "scheduler_job_id": "software-job"},
        "ionic_constraints": _relaxed_constraints("all_internal_dofs"),
    }
    point.update(relaxed_fields)
    nscf_task_path = Path(source["task_file"])
    nscf_task = json.loads(nscf_task_path.read_text(encoding="utf-8"))
    nscf_task["berry_strain_response"].update(copy.deepcopy(relaxed_fields))
    _write_json(nscf_task_path, nscf_task)
    scf_task_path = Path(point["scf_task_path"])
    scf_task = json.loads(scf_task_path.read_text(encoding="utf-8"))
    scf_task["berry_strain_response"].update(copy.deepcopy(relaxed_fields))
    _write_json(scf_task_path, scf_task)

    monkeypatch.setattr(polarization_strain, "_point_record", lambda *_args, **_kwargs: copy.deepcopy(stub_record))
    point["scf_task_id"] = "borrowed-reference-scf"
    nscf_task["berry_strain_response"]["source_scf_task_id"] = point["scf_task_id"]
    _write_json(nscf_task_path, nscf_task)
    with pytest.raises(ValueError, match="binding|SCF|source"):
        polarization_strain._saved_direction(source, point, manifest, geometry)


def test_relaxed_consumer_keeps_missing_directions_null_and_no_fake_jobs(tmp_path):
    manifest_path, fixture = _write_relaxed_software_manifest(tmp_path, "constrained_ion_fixed_cell")
    request_path = _consumer_request(tmp_path, manifest_path)
    result = analyze_polarization_strain(request_path)

    assert result["evidence_kind"] == "software_contract_only"
    assert result["native_jobs"]
    assert all(job["role"] == "relax" for job in result["native_jobs"])
    assert result["relaxed_ion_response"] is None
    assert result["constrained_ion_response"]["status"] == "unresolved"
    assert result["constrained_ion_response"]["relaxation_scope"] == "selected_internal_dofs"
    _write_json(tmp_path / "partial-request.json", json.loads(request_path.read_text(encoding="utf-8")))
    _write_json(tmp_path / "partial-result.json", result)
    for point in result["points"]:
        assert point["directions"] == {}
    assert result["pairs"][0]["reduced_slopes_by_gdir"] == {"1": None, "2": None, "3": None}
    assert result["pairs"][0]["missing"]


def _relaxed_software_math_sources(tmp_path: Path, fixture: dict[str, object], *, missing_branch: tuple[str, int] | None = None):
    """Return explicit software math sources and a common method record.

    The task/result marker files are provenance for this test-only path.  The
    consumer reader is replaced with the declared mathematical stub below;
    no native Berry output is represented by these files.
    """
    method = {
        "schema": "mlcc.software-math-method.v1",
        "engine": "abacus",
        "basis_type": "pw",
        "method_set": "software-relaxed-berry-math-v001",
        "evidence_kind": "software_contract_only",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    sources = []
    for point_id in ("minus", "plus"):
        for gdir in (1, 2, 3):
            task_path = tmp_path / "math-sources" / f"{point_id}-gdir{gdir}-task.json"
            result_path = tmp_path / "math-sources" / f"{point_id}-gdir{gdir}-result.json"
            marker = {
                "schema": "mlcc.software-math-source.v1",
                "task_id": f"software-math-{point_id}-gdir{gdir}",
                "evidence_kind": "software_contract_only",
                "fixture": True,
                "fixture_purpose": "software_contract_only",
            }
            _write_json(task_path, marker)
            _write_json(result_path, {**marker, "source_task_id": marker["task_id"]})
            sources.append(
                {
                    "point_id": point_id,
                    "gdir": gdir,
                    "task_file": str(task_path.resolve()),
                    "result_file": str(result_path.resolve()),
                    "branch_integer": 0,
                    "branch_basis": "software-math-branch-basis",
                }
            )

    def software_math_saved_direction(source, point, _manifest, _geometry):
        gdir = source["gdir"]
        point_id = point["point_id"]
        reduced = (0.1 if point_id == "minus" else 0.3) * gdir
        branch_integer = 0
        branch_basis = "software-math-branch-basis"
        if missing_branch == (point_id, gdir):
            reduced = None
            branch_integer = None
            branch_basis = None
        nscf_job = {
            "task_id": f"software-math-nscf-{point_id}-gdir{gdir}",
            "scheduler_job_id": None,
            "evidence_kind": "software_contract_only",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        }
        scf_job = {
            "task_id": f"software-math-scf-{point_id}",
            "scheduler_job_id": None,
            "evidence_kind": "software_contract_only",
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        }
        direction = {
            "representative_P_C_per_m2": reduced,
            "quantum_Q_C_per_m2": 1.0,
            "quantum_factor": 1,
            "reduced_charge": reduced,
            "branch_integer": branch_integer,
            "branch_basis": branch_basis,
            "direction_lattice_vector_angstrom": _geometry["cell_angstrom"][gdir - 1],
            "source_record": {"native_job": nscf_job, "scf_job": scf_job},
            "evidence_kind": "software_contract_only",
        }
        return direction, method

    return sources, software_math_saved_direction


@pytest.mark.parametrize(
    ("boundary", "missing_branch"),
    [
        ("relaxed_ion_fixed_cell", None),
        ("constrained_ion_fixed_cell", ("plus", 2)),
    ],
)
def test_relaxed_consumer_accepts_software_math_sources_and_preserves_missing_branch(
    tmp_path, monkeypatch, boundary, missing_branch,
):
    manifest_path, fixture = _write_relaxed_software_manifest(tmp_path, boundary)
    sources, software_math_saved_direction = _relaxed_software_math_sources(
        tmp_path, fixture, missing_branch=missing_branch,
    )
    monkeypatch.setattr(polarization_strain, "_saved_direction", software_math_saved_direction)
    request_path = _consumer_request(tmp_path, manifest_path, sources=sources)
    result = analyze_polarization_strain(request_path)

    assert result["evidence_kind"] == "software_contract_only"
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False
    assert {job["role"] for job in result["native_jobs"]} == {"relax", "nscf", "reference_scf"}
    pair = result["pairs"][0]
    if missing_branch is None:
        assert pair["status"] == "calculated_unqualified"
        assert pair["missing"] == []
        assert pair["reduced_slopes_by_gdir"] == {"1": pytest.approx(10.0), "2": pytest.approx(20.0), "3": pytest.approx(30.0)}
        assert pair["proper_e_C_per_m2"] is not None
        assert pair["improper_dP_ds_C_per_m2"] is not None
        assert result["relaxed_ion_response"]["status"] == "calculated_unqualified"
    else:
        assert pair["status"] == "unresolved"
        assert pair["reduced_slopes_by_gdir"]["1"] == pytest.approx(10.0)
        assert pair["reduced_slopes_by_gdir"]["2"] is None
        assert pair["reduced_slopes_by_gdir"]["3"] == pytest.approx(30.0)
        assert any(item["point_id"] == "plus" and item["gdir"] == 2 for item in pair["missing"])
        assert pair["proper_e_C_per_m2"] is None
        assert pair["improper_dP_ds_C_per_m2"] is None
        assert result["relaxed_ion_response"] is None
        assert result["constrained_ion_response"]["status"] == "unresolved"

    saved = copy.deepcopy(result)
    saved["source_validation"] = "not_native_software_math_only"
    saved["math_fixture"] = True
    saved["fixture_purpose"] = "software_contract_only"
    saved["software_math_jobs"] = copy.deepcopy(saved["native_jobs"])
    saved["native_jobs"] = []
    _write_json(tmp_path / f"{boundary}-software-math-result.json", saved)


@pytest.mark.parametrize("mutation", ["amplitude", "kpoints", "mask"])
def test_relaxed_pair_contract_rejects_mismatched_pair_inputs(tmp_path, mutation):
    boundary = "constrained_ion_fixed_cell" if mutation == "mask" else "relaxed_ion_fixed_cell"
    manifest_path, fixture = _write_relaxed_software_manifest(tmp_path, boundary)
    manifest = copy.deepcopy(fixture["manifest"])
    points = copy.deepcopy(manifest["points"])
    if mutation == "amplitude":
        points[1]["strain"] = 0.02
    elif mutation == "kpoints":
        method_path = Path(points[1]["relaxation_source"]["method_file"])
        method = json.loads(method_path.read_text(encoding="utf-8"))
        method["kpoints"] = [3, 2, 2]
        _write_json(method_path, method)
    elif mutation == "mask":
        points[1]["ionic_constraints"]["move_flags"] = [[0, 0, 0], [1, 1, 1]]
    else:
        raise AssertionError(mutation)
    with pytest.raises(ValueError):
        polarization_strain._relaxed_pair_contract(points, manifest)


def test_relaxed_pair_contract_allows_recorded_origin_difference(tmp_path):
    _manifest_path, fixture = _write_relaxed_software_manifest(tmp_path, "relaxed_ion_fixed_cell")
    manifest = copy.deepcopy(fixture["manifest"])
    points = copy.deepcopy(manifest["points"])
    source = copy.deepcopy(points[1]["relaxation_source"])
    source["relaxation"]["ionic_constraints"]["origin"] = "legacy_all_free"
    points[1]["ionic_constraints"]["origin"] = "legacy_all_free"
    points[1]["relaxation_source"] = source
    polarization_strain._relaxed_pair_contract(points, manifest)

