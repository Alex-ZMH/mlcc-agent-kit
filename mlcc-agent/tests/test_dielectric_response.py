from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from ase import Atoms
from scipy.constants import elementary_charge, epsilon_0

import mlcc.dielectric_response as dielectric_module
from mlcc.dielectric_response import (
    aggregate_born_columns,
    bind_external_electronic_input,
    calculate_ionic_dielectric,
    combine_dielectric_contributions,
)
from mlcc.modeling import write_model_artifacts


def _context() -> dict:
    return {
        "parent": {
            "study_id": "study",
            "model_id": "model",
            "model_version": "v001",
            "model_path": "/model",
        },
        "atom_ids": [10, 20],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
        "common_method": {"engine": "mathematical_fixture", "method_set": "math_fixture"},
    }


def _born() -> dict:
    return {
        "schema": "mlcc.born-charge-columns.v1",
        "context": _context(),
        "unit": "e",
        "full_born_tensors_e": [
            [[1.0, 0.2, 0.0], [0.0, 1.0, 0.3], [0.4, 0.0, 1.0]],
            [[-1.0, -0.2, 0.0], [0.0, -1.0, -0.3], [-0.4, 0.0, -1.0]],
        ],
        "sources": [{"response_id": "fixture"}],
    }


def _gamma(*, k: float = 2.0, unstable: bool = False) -> dict:
    block = k * np.block([[np.eye(3), -np.eye(3)], [-np.eye(3), np.eye(3)]])
    if unstable:
        block = -block
    return {
        "schema": "mlcc.gamma-force-constants.v1",
        "parent": _context()["parent"],
        "atom_ids": [10, 20],
        "cell_angstrom": _context()["cell_angstrom"],
        "volume_A3": 64.0,
        "unit": "eV/angstrom^2",
        "matrix_basis": "parent_atom_major_cartesian",
        "matrix_eV_per_A2": block.tolist(),
        "method_identity": _context()["common_method"],
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "source": {"harmonic_result": "gamma.json", "plan_manifest": "plan.json", "force_bundle": "forces.json"},
        "qualification": {"scientific_qualification": False},
    }


def _thresholds() -> dict[str, float]:
    return {
        "symmetry_eV_per_A2": 1.0e-12,
        "translation_eV_per_A2": 1.0e-12,
        "born_sum_e": 1.0e-12,
        "minimum_optical_eigenvalue_eV_per_A2": 1.0e-8,
    }


def test_ionic_dielectric_projects_translations_and_preserves_offdiagonal_response():
    result = calculate_ionic_dielectric(_born(), _gamma(), thresholds=_thresholds())
    assert result["status"] == "complete"
    tensor = np.asarray(result["delta_epsilon_ionic"], dtype=float)
    scale = elementary_charge * 1.0e10 / (epsilon_0 * 64.0)
    expected = (scale / 2.0) * np.asarray(
        [[1.04, 0.2, 0.4], [0.2, 1.09, 0.3], [0.4, 0.3, 1.16]],
        dtype=float,
    )
    np.testing.assert_allclose(tensor, expected, rtol=1.0e-12, atol=1.0e-12)
    assert result["production_qualification"] is False


@pytest.mark.parametrize("missing_born", [False, True])
def test_ionic_dielectric_rejects_gamma_matrix_basis_mismatch(missing_born: bool):
    gamma = _gamma()
    gamma["matrix_basis"] = "displacement_major_cartesian"
    born = _born()
    if missing_born:
        born["full_born_tensors_e"] = None
    with pytest.raises(ValueError, match="matrix_basis"):
        calculate_ionic_dielectric(born, gamma, thresholds=_thresholds())


def test_ionic_dielectric_rejects_missing_gamma_matrix_basis():
    gamma = _gamma()
    del gamma["matrix_basis"]
    with pytest.raises(KeyError, match="matrix_basis"):
        calculate_ionic_dielectric(_born(), gamma, thresholds=_thresholds())


@pytest.mark.parametrize("field", ["schema", "unit"])
def test_ionic_dielectric_rejects_invalid_born_identity_before_missing_tensor(field: str):
    born = _born()
    born["full_born_tensors_e"] = None
    born[field] = "invalid"
    with pytest.raises(ValueError):
        calculate_ionic_dielectric(born, None, thresholds=_thresholds())


def test_ionic_dielectric_keeps_unstable_optical_modes_unresolved():
    result = calculate_ionic_dielectric(_born(), _gamma(unstable=True), thresholds=_thresholds())
    assert result["delta_epsilon_ionic"] is None
    assert "negative_or_near_zero_optical_mode" in result["unresolved_reasons"]


def test_ionic_missing_gamma_is_explicitly_unresolved():
    result = calculate_ionic_dielectric(_born(), None, thresholds=_thresholds())
    assert result["delta_epsilon_ionic"] is None
    assert result["unresolved_reasons"] == ["gamma_force_constants_missing"]


def test_ionic_missing_born_and_gamma_preserves_both_reasons_and_sources():
    born = _born()
    born["full_born_tensors_e"] = None
    result = calculate_ionic_dielectric(born, None, thresholds=_thresholds())
    assert result["unresolved_reasons"] == ["born_tensor_incomplete", "gamma_force_constants_missing"]
    assert result["thresholds"] == _thresholds()
    assert result["born_source"]["sources"] == born["sources"]


def test_combine_does_not_add_identity_twice():
    ionic = calculate_ionic_dielectric(_born(), _gamma(), thresholds=_thresholds())
    electronic = {
        "kind": "epsilon_infinity_relative",
        "parent": _context()["parent"],
        "atom_ids": [10, 20],
        "cell_angstrom": _context()["cell_angstrom"],
        "volume_A3": 64.0,
        "method_identity": _context()["common_method"],
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "ions": "clamped",
        "unit": "dimensionless",
        "tensor": [[2.0, 0.1, 0.0], [0.1, 3.0, 0.0], [0.0, 0.0, 4.0]],
        "source_refs": ["epsilon.json"],
    }
    result = combine_dielectric_contributions(_born(), electronic, ionic)
    np.testing.assert_allclose(
        result["epsilon_static"],
        np.asarray(electronic["tensor"]) + np.asarray(ionic["delta_epsilon_ionic"]),
    )
    assert result["epsilon_static"][0][0] != pytest.approx(3.0)


def test_combine_rejects_incompatible_context():
    electronic = {
        "kind": "epsilon_infinity_relative",
        "parent": {**_context()["parent"], "study_id": "other"},
        "atom_ids": [10, 20],
        "cell_angstrom": _context()["cell_angstrom"],
        "volume_A3": 64.0,
        "method_identity": _context()["common_method"],
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "ions": "clamped",
        "unit": "dimensionless",
        "tensor": np.eye(3).tolist(),
        "source_refs": ["epsilon.json"],
    }
    with pytest.raises(ValueError, match="context"):
        combine_dielectric_contributions(_born(), electronic)


def _write_response(path: Path, model_path: Path, *, atom_id: int, axis: int, value: list[float]):
    cell = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]
    directions = []
    for gdir in (1, 2, 3):
        unit = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]][gdir - 1]
        directions.append(
            {
                "gdir": gdir,
                "direction_lattice_vector_angstrom": cell[gdir - 1],
                "direction_unit_vector_cartesian": unit,
                "unit": "C/m^2/angstrom",
                "branch_resolved": True,
                "minus": {
                    "branch_integer": 0,
                    "branch_basis": "mathematical_fixture",
                    "task": {"task_id": f"minus-{atom_id}-{axis}-{gdir}"},
                    "source": {"task": "m"},
                },
                "plus": {
                    "branch_integer": 0,
                    "branch_basis": "mathematical_fixture",
                    "task": {"task_id": f"plus-{atom_id}-{axis}-{gdir}"},
                    "source": {"task": "p"},
                },
            }
        )
    record = {
        "schema": "mlcc.abacus-berry-displacement-response-results.v1",
        "response_id": f"r-{atom_id}-{axis}",
        "parent": {"study_id": "study", "model_id": "model", "model_version": "v001", "model_path": str(model_path.resolve())},
        "target": {"atom_id": atom_id, "cartesian_axis": axis},
        "common_method": {"engine": "mathematical_fixture", "method_set": "math_fixture"},
        "directions": directions,
        "volume_A3": 64.0,
        "born_charge_column": {"atom_id": atom_id, "cartesian_axis": axis, "values_e": value, "unit": "e", "complete": True},
        "source_request": "request.json",
        "response_manifest": "manifest.json",
    }
    path.write_text(json.dumps(record), encoding="utf-8")


def mathematical_fixture_no_native_evidence(response: dict, response_path: Path) -> None:
    return None


def test_aggregate_builds_stable_atom_axis_tensor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dielectric_module, "_validate_native_sources", mathematical_fixture_no_native_evidence)
    atoms = Atoms(symbols=["Na", "Cl"], cell=np.eye(3) * 4.0, scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5]], pbc=True)
    atoms.new_array("atom_id", np.asarray([10, 20], dtype=int))
    model = write_model_artifacts(atoms, tmp_path / "model", model_id="model", version="v001", fixture=True, fixture_purpose="dielectric_math", material="NaCl", phase_requested="fixture")
    paths = []
    for atom_id in (10, 20):
        for axis in (0, 1, 2):
            path = tmp_path / f"response-{atom_id}-{axis}.json"
            _write_response(path, model.artifact_dir, atom_id=atom_id, axis=axis, value=[float(axis + 1), 0.0, 0.0])
            paths.append(path)
    result = aggregate_born_columns(model.artifact_dir, paths)
    assert len(result["columns"]) == 6
    assert result["missing_columns"] == []
    assert np.asarray(result["full_born_tensors_e"]).shape == (2, 3, 3)


def _load_saved_197_math_chain() -> dict[str, dict[str, Any]]:
    root = Path(os.environ["MLCC_SAVED_197_MATH_ROOT"])
    return {
        name: json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("born", "electronic", "ionic", "dielectric")
    }


def _saved_197_external_fixture(tmp_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any], Path]:
    chain = _load_saved_197_math_chain()
    external = copy.deepcopy(chain["electronic"])
    external["provenance_kind"] = "external_supplied"
    external["source_mode"] = "software_math_only"
    external["qualification"] = {
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }
    source_path = tmp_path / "external.json"
    external["source_path"] = str(source_path.resolve())
    source_path.write_text(json.dumps(external, indent=2, sort_keys=True), encoding="utf-8")
    return chain, external, source_path


def test_saved_197_external_electronic_combines_without_mutation(tmp_path: Path):
    chain, external, source_path = _saved_197_external_fixture(tmp_path)
    chain_before = copy.deepcopy(chain)
    external_before = copy.deepcopy(external)
    source_before = source_path.read_bytes()

    bound = bind_external_electronic_input(external, source_path)
    assert bound is not external
    assert bound["source_path"] == str(source_path.resolve())
    assert bound["method_identity"] == chain["electronic"]["method_identity"]
    assert bound["source_mode"] == "software_math_only"
    assert bound["qualification"] == external["qualification"]
    with_declared_path = copy.deepcopy(external)
    with_declared_path["source_path"] = str(source_path.resolve())
    assert bind_external_electronic_input(with_declared_path)["source_path"] == str(source_path.resolve())

    result = combine_dielectric_contributions(
        chain["born"], external, chain["ionic"], electronic_path=source_path
    )
    expected = chain["dielectric"]
    np.testing.assert_allclose(result["epsilon_infinity"], expected["epsilon_infinity"])
    np.testing.assert_allclose(result["delta_epsilon_ionic"], expected["delta_epsilon_ionic"])
    np.testing.assert_allclose(result["epsilon_static"], expected["epsilon_static"])
    assert result["contribution_provenance"]["electronic"] == {
        "provenance_kind": "external_supplied",
        "source_path": str(source_path.resolve()),
        "source_refs": chain["electronic"]["source_refs"],
    }
    assert result["contribution_provenance"]["ionic"] == {
        "provenance_kind": "derived_from_born_gamma",
        "born_source": chain["ionic"]["born_source"],
        "gamma_source": chain["ionic"]["gamma_source"],
    }
    assert result["production_qualification"] is False
    assert "native_jobs" not in result

    (tmp_path / "bound-electronic.json").write_text(json.dumps(bound, indent=2, sort_keys=True), encoding="utf-8")
    (tmp_path / "combined.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    (tmp_path / "fixture-metadata.json").write_text(
        json.dumps(
            {
                "fixture": "saved-197-math-with-external-electronic",
                "evidence_kind": "software_contract_only",
                "source_root_env": "MLCC_SAVED_197_MATH_ROOT",
                "source_root": os.environ["MLCC_SAVED_197_MATH_ROOT"],
                "external_input": str(source_path.resolve()),
                "combined_output": str((tmp_path / "combined.json").resolve()),
                "native_electronic_producer": False,
                "main_source_mode": "software_math_only",
                "electronic_provenance_kind": "external_supplied",
                "method_identity": chain["electronic"]["method_identity"],
                "qualification": False,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    assert chain == chain_before
    assert external == external_before
    assert source_path.read_bytes() == source_before


def test_external_binding_rejects_missing_source_path_without_input(tmp_path: Path):
    _, external, _ = _saved_197_external_fixture(tmp_path)
    external.pop("source_path")
    with pytest.raises(KeyError, match="source_path"):
        bind_external_electronic_input(external)


def test_external_binding_rejects_conflicting_source_path(tmp_path: Path):
    _, external, source_path = _saved_197_external_fixture(tmp_path)
    candidate = copy.deepcopy(external)
    candidate["source_path"] = str((tmp_path / "other.json").resolve())
    with pytest.raises(ValueError, match="differs"):
        bind_external_electronic_input(candidate, source_path)


def test_external_binding_rejects_missing_input_file(tmp_path: Path):
    _, external, _ = _saved_197_external_fixture(tmp_path)
    external.pop("source_path")
    with pytest.raises(FileNotFoundError, match="does not exist"):
        bind_external_electronic_input(external, tmp_path / "does-not-exist.json")


def test_external_binding_rejects_relative_source_path_without_input(tmp_path: Path):
    _, external, _ = _saved_197_external_fixture(tmp_path)
    candidate = copy.deepcopy(external)
    candidate["source_path"] = "external.json"
    with pytest.raises(ValueError, match="absolute"):
        bind_external_electronic_input(candidate)


def test_external_binding_rejects_empty_source_refs(tmp_path: Path):
    _, external, source_path = _saved_197_external_fixture(tmp_path)
    candidate = copy.deepcopy(external)
    candidate["source_refs"] = []
    with pytest.raises(ValueError, match="source_refs"):
        bind_external_electronic_input(candidate, source_path)


def test_external_binding_rejects_unknown_provenance_kind(tmp_path: Path):
    _, external, source_path = _saved_197_external_fixture(tmp_path)
    candidate = copy.deepcopy(external)
    candidate["provenance_kind"] = "unknown"
    with pytest.raises(ValueError, match="provenance_kind"):
        bind_external_electronic_input(candidate, source_path)


def test_external_binding_rejects_pseudo_native_declarations(tmp_path: Path):
    _, external, source_path = _saved_197_external_fixture(tmp_path)
    for field, value in (
        ("source_mode", "native_source_bound"),
        ("native_tasks", ["native-task"]),
        ("native_jobs", ["247"]),
    ):
        candidate = copy.deepcopy(external)
        candidate[field] = value
        with pytest.raises(ValueError, match="native|source_mode"):
            bind_external_electronic_input(candidate, source_path)


def test_external_binding_rejects_software_math_mode_for_nonmath_engine(tmp_path: Path):
    _, external, source_path = _saved_197_external_fixture(tmp_path)
    candidate = copy.deepcopy(external)
    candidate["source_mode"] = "software_math_only"
    candidate["method_identity"]["engine"] = "abacus"
    with pytest.raises(ValueError, match="source_mode"):
        bind_external_electronic_input(candidate, source_path)


def test_combine_rejects_unmarked_nonmath_electronic(tmp_path: Path):
    chain, external, source_path = _saved_197_external_fixture(tmp_path)
    candidate = copy.deepcopy(external)
    candidate.pop("provenance_kind")
    candidate["method_identity"]["engine"] = "abacus"
    with pytest.raises(ValueError, match="provenance_kind"):
        combine_dielectric_contributions(
            chain["born"], candidate, chain["ionic"], electronic_path=source_path
        )


def test_legacy_math_electronic_provenance_needs_no_external_path():
    chain = _load_saved_197_math_chain()
    result = combine_dielectric_contributions(chain["born"], chain["electronic"])
    np.testing.assert_allclose(result["epsilon_infinity"], chain["dielectric"]["epsilon_infinity"])
    assert result["delta_epsilon_ionic"] is None
    assert result["epsilon_static"] is None
    assert result["contribution_provenance"] == {
        "electronic": {
            "provenance_kind": "software_math_only",
            "source_path": None,
            "source_refs": chain["electronic"]["source_refs"],
        },
        "ionic": None,
    }


def test_combine_rejects_saved_197_context_or_method_conflicts(tmp_path: Path):
    chain, external, source_path = _saved_197_external_fixture(tmp_path)
    for field, value in (("study_id", "other-study"), ("method", "other-method")):
        candidate = copy.deepcopy(external)
        if field == "study_id":
            candidate["parent"][field] = value
        else:
            candidate["method_identity"][field] = value
        with pytest.raises(ValueError, match="context"):
            combine_dielectric_contributions(
                chain["born"], candidate, chain["ionic"], electronic_path=source_path
            )


def test_combine_rejects_saved_197_unit_and_boundary_conflicts(tmp_path: Path):
    chain, external, source_path = _saved_197_external_fixture(tmp_path)
    for field, value in (
        ("unit", "eV"),
        ("electrical_boundary", "fixed_D"),
        ("mechanical_boundary", "relaxed_cell"),
        ("ions", "relaxed"),
    ):
        candidate = copy.deepcopy(external)
        candidate[field] = value
        with pytest.raises(ValueError, match=field.split("_")[0] if field != "unit" else "unit"):
            combine_dielectric_contributions(
                chain["born"], candidate, chain["ionic"], electronic_path=source_path
            )


def test_saved_197_missing_ionic_total_remains_null(tmp_path: Path):
    chain, external, source_path = _saved_197_external_fixture(tmp_path)

    no_ionic = combine_dielectric_contributions(
        chain["born"], external, None, electronic_path=source_path
    )
    np.testing.assert_allclose(no_ionic["epsilon_infinity"], chain["dielectric"]["epsilon_infinity"])
    assert no_ionic["delta_epsilon_ionic"] is None
    assert no_ionic["epsilon_static"] is None
    assert no_ionic["status"] == "unresolved"
    assert no_ionic["contribution_provenance"]["ionic"] is None

    ionic = copy.deepcopy(chain["ionic"])
    ionic["delta_epsilon_ionic"] = None
    result = combine_dielectric_contributions(
        chain["born"], external, ionic, electronic_path=source_path
    )
    np.testing.assert_allclose(result["epsilon_infinity"], chain["dielectric"]["epsilon_infinity"])
    assert result["delta_epsilon_ionic"] is None
    assert result["epsilon_static"] is None
    assert result["status"] == "unresolved"
    assert result["unresolved_reasons"] == ["electronic_or_ionic_contribution_missing"]
    assert result["contribution_provenance"]["ionic"]["provenance_kind"] == "derived_from_born_gamma"
    (tmp_path / "missing-ionic-none.json").write_text(
        json.dumps(no_ionic, indent=2, sort_keys=True), encoding="utf-8"
    )
    (tmp_path / "missing-ionic-total-null.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
