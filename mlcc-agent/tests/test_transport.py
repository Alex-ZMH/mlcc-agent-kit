"""Direct tests for the saved-band transport source contract."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mlcc.transport import calculate_transport, read_transport_source
from mlcc.transport import _power_factor


def _request(electronic_path: Path, task_path: Path, *, magnetic: object = None, include_magnetic: bool = True) -> dict:
    request = {
        "schema": "mlcc.transport-request.v001",
        "electronic_path": str(electronic_path),
        "task_path": str(task_path),
        "kpoint_weight_field": "kpoint_weights",
        "temperatures_K": [330.0],
        "chemical_potentials_eV": [0.0],
        "energy_reference": "native_fermi",
        "dos_energy_window_eV": [-2.0, 2.0],
        "dos_bins": 64,
        "equivalence_count": 8,
    }
    if include_magnetic:
        request["magnetic_symmetry"] = magnetic
    return request


def _write_source(tmp_path: Path, *, nspin: int = 1, include_grid: bool = True, include_magnetic: bool = True, magnetic: object = None) -> tuple[dict, Path, Path]:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    identity = {
        "task_id": "transport-fixture",
        "scheduler_job_id": "job-fixture",
        "method_set": "fixture-abacus-scf",
        "model_id": "fixture-model",
        "model_version": "v001",
    }
    task = {**identity, "engine": "abacus", "engine_version": "3.10.1", "status": "COMPLETED", "scheduler_state": "COMPLETED", "exit_code": "0:0"}
    result = {
        "task_id": identity["task_id"],
        "scheduler_job_id": identity["scheduler_job_id"],
        "method_set": identity["method_set"],
        "stage": "scf",
        "electronic_converged": True,
        "atom_ids": [10, 20],
        "final_atoms": {
            "symbols": ["O", "Ni"],
            "positions_angstrom": [[0.0, 0.0, 0.0], [1.5, 1.5, 1.5]],
            "cell_angstrom": [[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]],
            "pbc": [True, True, True],
        },
    }
    method = {
        "method_set": identity["method_set"], "model_id": identity["model_id"], "version": identity["model_version"],
        "engine": "abacus", "abacus_version_target": "3.10.1",
        "nspin": nspin, "stage": "scf", "suffix": "Fixture",
    }
    # The ABACUS order is intentionally different from final_atoms source order.
    atom_map = {
        "model_id": identity["model_id"], "version": identity["model_version"], "source_atom_ids": [10, 20],
        "abacus_order": [
            {"abacus_index": 0, "source_index": 1, "atom_id": 20, "element": "Ni"},
            {"abacus_index": 1, "source_index": 0, "atom_id": 10, "element": "O"},
        ],
    }
    for name, value in (("task.json", task), ("result.json", result), ("method.json", method), ("STRU.atom-map.json", atom_map)):
        (task_dir / name).write_text(json.dumps(value), encoding="utf-8")
    (task_dir / "INPUT").write_text(f"INPUT_PARAMETERS\nnspin {nspin}\n", encoding="utf-8")

    coordinates = [[ix / 2, iy / 2, iz / 2] for iz in range(2) for iy in range(2) for ix in range(2)]
    electronic = {
        "schema": "mlcc.abacus-electronic.v001", **identity, "engine": "abacus", "engine_version": "3.10.1",
        "stage": "scf", "native_completed": True, "electronic_converged": True, "native_exit_code": "0:0",
        "nspin": nspin, "spin_degeneracy": 2 if nspin == 1 else 1,
        "occupation_capacity_per_spin_channel": 2.0 if nspin == 1 else 1.0,
        "array_order": "spin,kpoint,band", "kpoint_coordinate_system": "direct_reciprocal_lattice",
        "uniform_kmesh_verified": True, "kpoint_coordinates": coordinates,
        "kpoint_weights": [0.125] * 8, "kpoint_mesh": [2, 2, 2], "kpoint_mesh_shift": [0, 0, 0],
        "fermi_level_eV": 5.0,
        "band_energies_eV": [[[4.0 + index * 0.1, 5.0 + index * 0.1] for index in range(8)] for _ in range(nspin)],
    }
    if not include_grid:
        del electronic["kpoint_mesh"]
    electronic_path = tmp_path / "electronic.json"
    electronic_path.write_text(json.dumps(electronic), encoding="utf-8")
    request = _request(electronic_path, task_dir, magnetic=magnetic, include_magnetic=include_magnetic)
    return request, task_dir, electronic_path


def test_nspin1_source_uses_electron_weight_and_source_index_mapping(tmp_path):
    request, task_dir, electronic_path = _write_source(tmp_path)
    source = read_transport_source(request)

    assert source["status"] == "ready"
    assert source["dosweight"] == 2.0
    assert source["symbols"] == ["Ni", "O"]
    assert source["atom_ids"] == [20, 10]
    assert source["band_energies_relative_eV"][0, 0] == -1.0
    assert source["kpoint_weights"].tolist() == [0.125] * 8


def test_nspin2_without_explicit_magnetic_symmetry_stays_unresolved(tmp_path):
    request, _, _ = _write_source(tmp_path, nspin=2, include_magnetic=False)
    source = read_transport_source(request)

    assert source["status"] == "unresolved"
    assert "magnetic_symmetry" in source["missing"]
    assert source["magmom"] is None


def test_nspin2_explicit_magnetic_symmetry_concatenates_spin_bands(tmp_path):
    magnetic = {"moments_muB_by_atom_id": {"20": 1.0, "10": -1.0}, "source_refs": ["fixture/magnetic.json"]}
    request, _, _ = _write_source(tmp_path, nspin=2, magnetic=magnetic)
    source = read_transport_source(request)

    assert source["status"] == "ready"
    assert source["dosweight"] == 1.0
    assert source["band_energies_relative_eV"].shape == (8, 4)
    assert source["magmom"].tolist() == [1.0, -1.0]


def test_missing_grid_is_unresolved_without_indexing_missing_fields(tmp_path):
    request, _, _ = _write_source(tmp_path, include_grid=False)
    source = read_transport_source(request)
    product = calculate_transport(source, request)

    assert source["status"] == "unresolved"
    assert "electronic.kpoint_mesh" in source["missing"]
    assert product["status"] == "unresolved"
    assert product["tensors"] is None


def test_identity_conflict_is_original_value_error(tmp_path):
    request, _, electronic_path = _write_source(tmp_path)
    electronic = json.loads(electronic_path.read_text(encoding="utf-8"))
    electronic["task_id"] = "other-task"
    electronic_path.write_text(json.dumps(electronic), encoding="utf-8")

    with pytest.raises(ValueError, match="electronic/task.task_id"):
        read_transport_source(request)


@pytest.mark.parametrize("field,value", [("status", "FAILED"), ("scheduler_state", "FAILED"), ("exit_code", "1:0")])
def test_unsuccessful_scheduler_state_stays_unresolved(tmp_path, field, value):
    request, task_dir, _ = _write_source(tmp_path)
    task_path = task_dir / "task.json"
    task = json.loads(task_path.read_text())
    task[field] = value
    task_path.write_text(json.dumps(task))
    source = read_transport_source(request)
    product = calculate_transport(source, request)
    assert product["status"] == "unresolved"
    assert product["tensors"] is None
    assert "scheduler_completion" in product["missing"]
    assert source["native_exit_code"] == "0:0"
    assert source[{"status": "scheduler_status", "scheduler_state": "scheduler_state", "exit_code": "exit_code"}[field]] == value


def test_power_factor_is_matrix_product():
    seebeck = np.asarray([[[[2.0, 1.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 4.0]]]])
    sigma = np.asarray([[[[5.0, 1.0, 0.0], [1.0, 6.0, 0.0], [0.0, 0.0, 7.0]]]])

    expected = np.swapaxes(seebeck, -1, -2) @ sigma @ seebeck
    np.testing.assert_allclose(_power_factor(seebeck, sigma), expected)
