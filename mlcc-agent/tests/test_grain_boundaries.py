from __future__ import annotations

import json

import numpy as np
import pytest
from ase import Atoms

from mlcc.grain_boundaries import build_grain_boundary
from mlcc.modeling import read_model_artifacts, write_model_artifacts


def _request(
    *,
    model_id: str = "ni-gb-engineering",
    rotation_one: list[list[float]] | None = None,
    threshold: float = 0.2,
    termination_one: float = 0.0,
    in_plane_translation_one: list[float] | None = None,
) -> dict[str, object]:
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    rotation_one = identity if rotation_one is None else rotation_one
    in_plane_translation_one = (
        [0.0, 0.0] if in_plane_translation_one is None else in_plane_translation_one
    )
    return {
        "model_id": model_id,
        "version": "v001",
        "purpose": "engineering_geometry",
        "parent_charge_state": 0,
        "charge_state": 0,
        "charge_basis": "explicit_parent_neutral_geometry",
        "selection_status": "engineering_gb_not_user_selected",
        "grains": [
            {
                "grain_id": 0,
                "integer_transform": [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
                "rotation_cartesian": identity,
                "termination_fraction": 0.0,
                "in_plane_translation_fractional": [0.0, 0.0],
            },
            {
                "grain_id": 1,
                "integer_transform": [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
                "rotation_cartesian": rotation_one,
                "termination_fraction": termination_one,
                "in_plane_translation_fractional": in_plane_translation_one,
            },
        ],
        "boundary_plane": {"normal_cartesian": [0.0, 0.0, 1.0]},
        "periodic_cell_angstrom": [[8.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 8.0]],
        "overlap_policy": {
            "action": "reject",
            "minimum_distance_angstrom": threshold,
        },
    }


def _parent(
    tmp_path,
    *,
    charge_state: int | None = None,
    duplicate: bool = False,
    single: bool = False,
    cell_z: float = 4.0,
):
    positions = [[0.7, 0.8, 0.9], [2.1, 2.2, 2.3]]
    if single:
        positions = positions[:1]
    if duplicate:
        positions[1] = positions[0]
    count = len(positions)
    atoms = Atoms(
        symbols=["Ni"] * count,
        positions=positions,
        cell=np.diag([4.0, 4.0, cell_z]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.arange(count, dtype=np.int64))
    atoms.new_array("initial_magmoms", np.asarray([0.6, -0.2][:count], dtype=float))
    atoms.new_array("initial_charges", np.asarray([0.1, -0.1][:count], dtype=float))
    atoms.set_masses(np.asarray([58.1, 59.2][:count], dtype=float))
    metadata = {}
    if charge_state is not None:
        metadata["charge_state"] = charge_state
    model = write_model_artifacts(
        atoms,
        tmp_path / "parent",
        model_id="parent-ni",
        version="v001",
        fixture=True,
        fixture_purpose="connection_test",
        phase_requested="fcc_engineering_fixture",
        source_path="test-parent",
        source_atoms=atoms,
        material="Ni",
    )
    if metadata:
        model.metadata.update(metadata)
        (model.artifact_dir / "model.json").write_text(
            json.dumps(model.metadata, indent=2) + "\n", encoding="utf-8"
        )
    return model


def test_build_reconstructs_supercells_lineage_and_explicit_arrays(tmp_path):
    parent = _parent(tmp_path)
    result = build_grain_boundary(parent.artifact_dir, _request(), tmp_path / "child")

    assert len(result.atoms) == 8
    assert result.atoms.arrays["atom_id"].tolist() == list(range(8))
    assert result.atoms.arrays["grain_id"].tolist() == [0, 0, 0, 0, 1, 1, 1, 1]
    assert result.atoms.get_initial_magnetic_moments().tolist() == pytest.approx(
        [0.6, -0.2, 0.6, -0.2, 0.6, -0.2, 0.6, -0.2]
    )
    assert result.atoms.arrays["initial_charges"].tolist() == pytest.approx(
        [0.1, -0.1, 0.1, -0.1, 0.1, -0.1, 0.1, -0.1]
    )
    assert result.atoms.get_masses().tolist() == pytest.approx(
        [58.1, 59.2, 58.1, 59.2, 58.1, 59.2, 58.1, 59.2]
    )
    assert result.metadata["spatial_mode"] == "grain_boundary"
    assert result.metadata["selection_status"] == "engineering_gb_not_user_selected"
    assert result.metadata["material_selection_confirmed"] is False
    assert result.metadata["production_qualified"] is False
    assert result.metadata["charge_contract"]["parent_metadata"]["metadata.charge_state"]["present"] is False

    lineage = json.loads((result.artifact_dir / "atom-lineage.json").read_text(encoding="utf-8"))["entries"]
    assert len(lineage) == 8
    for entry in lineage:
        parent_position = parent.atoms.positions[entry["parent_index"]]
        rotation = np.asarray(entry["rotation_cartesian"], dtype=float)
        effective_image = np.asarray(entry["effective_parent_image"], dtype=float)
        translation = np.asarray(entry["translations"]["cartesian_angstrom"], dtype=float)
        stack_offset = np.asarray(entry["stack_offset_angstrom"], dtype=float)
        expected = (parent_position + effective_image @ parent.atoms.cell.array) @ rotation.T
        expected = expected + translation + stack_offset
        assert result.atoms.positions[entry["atom_id"]] == pytest.approx(expected)

    loaded = read_model_artifacts(result.artifact_dir)
    assert loaded.atoms.arrays["grain_id"].tolist() == result.atoms.arrays["grain_id"].tolist()
    geometry = json.loads((result.artifact_dir / "grain-boundary.json").read_text(encoding="utf-8"))
    assert geometry["checks"]["periodic_interfaces"] == 2
    assert geometry["checks"]["composition_determinant_sum"] == 4


def test_rotation_mismatch_fails_before_output(tmp_path):
    parent = _parent(tmp_path)
    quarter_turn = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    output = tmp_path / "mismatch"
    with pytest.raises(ValueError, match="in-plane cell vectors"):
        build_grain_boundary(parent.artifact_dir, _request(rotation_one=quarter_turn), output)
    assert not output.exists()


def test_nonzero_termination_and_translation_are_in_lineage_reconstruction(tmp_path):
    parent = _parent(tmp_path)
    request = _request(
        termination_one=0.25,
        in_plane_translation_one=[0.125, 0.25],
        threshold=0.2,
    )
    result = build_grain_boundary(parent.artifact_dir, request, tmp_path / "shifted")

    lineage = json.loads((result.artifact_dir / "atom-lineage.json").read_text(encoding="utf-8"))["entries"]
    grain_one = [entry for entry in lineage if entry["grain_id"] == 1]
    assert grain_one
    assert all(entry["translation_fractional"] == pytest.approx([0.125, 0.25, 0.25]) for entry in grain_one)
    assert all(entry["stack_offset_angstrom"] == pytest.approx([0.0, 0.0, 4.0]) for entry in grain_one)
    for entry in grain_one:
        parent_position = parent.atoms.positions[entry["parent_index"]]
        rotation = np.asarray(entry["rotation_cartesian"], dtype=float)
        effective_image = np.asarray(entry["effective_parent_image"], dtype=float)
        translation = np.asarray(entry["translations"]["cartesian_angstrom"], dtype=float)
        stack_offset = np.asarray(entry["stack_offset_angstrom"], dtype=float)
        expected = (parent_position + effective_image @ parent.atoms.cell.array) @ rotation.T
        expected = expected + translation + stack_offset
        assert result.atoms.positions[entry["atom_id"]] == pytest.approx(expected)
    record = json.loads((result.artifact_dir / "grain-boundary.json").read_text(encoding="utf-8"))
    assert record["request_original"]["charge_basis"] == "explicit_parent_neutral_geometry"
    assert record["request_original"]["selection_status"] == "engineering_gb_not_user_selected"


def test_periodic_self_image_overlap_is_rejected(tmp_path):
    parent = _parent(tmp_path, single=True, cell_z=10.0)
    request = _request(threshold=4.1)
    request["grains"][0]["integer_transform"] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    request["grains"][1]["integer_transform"] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    request["periodic_cell_angstrom"] = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 20.0]]
    with pytest.raises(ValueError, match=r"child_atom_ids=.*image_shift=.*distance_angstrom"):
        build_grain_boundary(parent.artifact_dir, request, tmp_path / "self-overlap")


def test_improper_rotation_is_rejected(tmp_path):
    parent = _parent(tmp_path)
    reflection = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]]
    with pytest.raises(ValueError, match="proper Cartesian rotation"):
        build_grain_boundary(parent.artifact_dir, _request(rotation_one=reflection), tmp_path / "reflection")


def test_overlap_policy_reports_child_ids_and_periodic_image(tmp_path):
    parent = _parent(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match=r"child_atom_ids=.*grains=.*distance_angstrom"):
        build_grain_boundary(parent.artifact_dir, _request(threshold=0.5), tmp_path / "overlap")


def test_parent_charge_is_checked_and_nonzero_charge_is_rejected(tmp_path):
    parent = _parent(tmp_path, charge_state=1)
    with pytest.raises(ValueError, match="parent metadata charge_state must be neutral"):
        build_grain_boundary(parent.artifact_dir, _request(), tmp_path / "charged")
