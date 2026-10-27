from __future__ import annotations

import json

import numpy as np
import pytest
from ase import Atoms

from mlcc.interfaces import build_layered_interface
from mlcc.modeling import read_model_artifacts, write_model_artifacts


def _parent(
    tmp_path,
    name: str,
    symbols: list[str],
    cell: list[list[float]],
    positions: list[list[float]],
    *,
    magnetic: list[float] | None = None,
    charges: list[float] | None = None,
):
    atoms = Atoms(symbols=symbols, positions=positions, cell=cell, pbc=True)
    atoms.new_array("atom_id", np.arange(len(atoms), dtype=np.int64))
    if magnetic is not None:
        atoms.new_array("initial_magmoms", np.asarray(magnetic, dtype=float))
    if charges is not None:
        atoms.new_array("initial_charges", np.asarray(charges, dtype=float))
    return write_model_artifacts(
        atoms,
        tmp_path / name,
        model_id=name,
        version="v001",
        fixture=True,
        fixture_purpose="interface_geometry_test",
        phase_requested="test_phase",
        source_path=f"{name}-source",
        source_atoms=atoms,
        material=name,
    )


def _request(model_id: str = "ni-bto-interface") -> dict[str, object]:
    target_a = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 3.52]]
    target_b = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.08]]
    return {
        "schema": "mlcc.layered-interface-request.v1",
        "model_id": model_id,
        "version": "v001",
        "fixture": True,
        "fixture_purpose": "interface_geometry_test",
        "charge_state": 0,
        "boundary": ["p", "p", "p"],
        "sides": {
            "a": {
                "repeat": [1, 1, 2],
                "target_cell_angstrom": target_a,
                "origin_shift_fractional": [0.125, 0.0, 0.0],
                "translation_inplane_angstrom": [0.0, 0.0],
            },
            "b": {
                "repeat": [1, 1, 2],
                "target_cell_angstrom": target_b,
                "origin_shift_fractional": [0.0, 0.0, 0.0],
                "translation_inplane_angstrom": [0.25, 0.25],
            },
        },
        "gap_ab_angstrom": 2.0,
        "gap_ba_angstrom": 2.0,
        "minimum_distance_angstrom": 1.0,
    }


def test_build_layered_interface_writes_two_sources_and_reconstructable_lineage(tmp_path):
    side_a = _parent(
        tmp_path,
        "side-a",
        ["Ni"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 3.52]],
        [[0.7, 0.8, 0.9]],
        magnetic=[0.6],
        charges=[0.0],
    )
    side_b = _parent(
        tmp_path,
        "side-b",
        ["O"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.08]],
        [[2.1, 2.2, 2.3]],
    )
    result = build_layered_interface(side_a.artifact_dir, side_b.artifact_dir, _request(), tmp_path / "interface")

    assert len(result.atoms) == 4
    assert result.atoms.arrays["atom_id"].tolist() == [0, 1, 2, 3]
    assert result.atoms.arrays["side_id"].tolist() == ["a", "a", "b", "b"]
    assert "initial_magmoms" not in result.atoms.arrays
    assert "initial_charges" not in result.atoms.arrays
    assert result.metadata["spatial_mode"] == "layered_interface"
    assert result.metadata["interface_file"] == "layered-interface.json"
    assert result.metadata["phase_requested"] == "layered_interface_no_single_space_group"
    assert result.metadata["material"] == "side-a+side-b"
    assert len(result.metadata["parent_models"]) == 2

    interface_record = json.loads(
        (result.artifact_dir / "layered-interface.json").read_text(encoding="utf-8")
    )
    assert interface_record["schema"] == "mlcc.layered-interface.v1"
    assert interface_record["geometry"]["interface_count"] == 2
    assert interface_record["geometry"]["interface_equivalence"] == "unresolved"
    assert interface_record["geometry"]["gaps_angstrom"] == {"ab": 2.0, "ba": 2.0}
    assert interface_record["checks"]["source_arrays"]["initial_magmoms"]["propagated_to_child"] is False
    assert interface_record["checks"]["source_arrays"]["initial_magmoms"]["raw_values"] == {
        "a": [0.6],
        "b": None,
    }

    lineage = interface_record["lineage"]
    assert len(lineage) == 4
    assert result.metadata["atom_lineage"] == lineage
    for entry in lineage:
        origin = np.asarray(entry["origin_shift_fractional"], dtype=float)
        fractional = np.asarray(entry["parent_fractional"], dtype=float)
        wrapped = np.mod(fractional - origin, 1.0)
        image = np.asarray(entry["repeat_image"], dtype=float)
        target = np.asarray(entry["target_cell_angstrom"], dtype=float)
        translation = np.asarray(entry["translation_inplane_angstrom"], dtype=float)
        expected = (wrapped + image) @ target + [translation[0], translation[1], 0.0]
        expected = expected + np.asarray(entry["layer_offset_angstrom"], dtype=float)
        expected = expected + np.asarray(entry["stack_offset_angstrom"], dtype=float)
        assert result.atoms.positions[entry["atom_id"]] == pytest.approx(expected)
        assert result.atoms.positions[entry["atom_id"]] == pytest.approx(
            entry["position_reconstruction_angstrom"]
        )
        assert entry["parent_model_id"] in {"side-a", "side-b"}
        assert len(entry["repeat_image"]) == 3

    loaded = read_model_artifacts(result.artifact_dir)
    assert loaded.metadata["parent_models"] == interface_record["parent_models"]
    with pytest.raises(FileExistsError):
        build_layered_interface(side_a.artifact_dir, side_b.artifact_dir, _request(), result.artifact_dir)


def test_common_arrays_are_propagated_only_when_present_on_both_sides(tmp_path):
    side_a = _parent(
        tmp_path,
        "side-a",
        ["Ni"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 3.52]],
        [[0.7, 0.8, 0.9]],
        magnetic=[0.6],
        charges=[0.0],
    )
    side_b = _parent(
        tmp_path,
        "side-b",
        ["O"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.08]],
        [[2.1, 2.2, 2.3]],
        magnetic=[-0.2],
        charges=[0.0],
    )
    result = build_layered_interface(side_a.artifact_dir, side_b.artifact_dir, _request(), tmp_path / "interface")
    assert result.atoms.arrays["initial_magmoms"].tolist() == pytest.approx([0.6, 0.6, -0.2, -0.2])
    assert result.atoms.arrays["initial_charges"].tolist() == pytest.approx([0.0, 0.0, 0.0, 0.0])


def test_inplane_mismatch_is_rejected_without_output(tmp_path):
    side_a = _parent(
        tmp_path,
        "side-a",
        ["Ni"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 3.52]],
        [[0.7, 0.8, 0.9]],
    )
    side_b = _parent(
        tmp_path,
        "side-b",
        ["O"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.08]],
        [[2.1, 2.2, 2.3]],
    )
    request = _request()
    request["sides"]["b"]["target_cell_angstrom"][0][0] = 4.1
    with pytest.raises(ValueError, match="in-plane cells do not match"):
        build_layered_interface(side_a.artifact_dir, side_b.artifact_dir, request, tmp_path / "interface")
    assert not (tmp_path / "interface").exists()


def test_nonzero_parent_initial_charges_are_rejected(tmp_path):
    side_a = _parent(
        tmp_path,
        "side-a",
        ["Ni"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 3.52]],
        [[0.7, 0.8, 0.9]],
        charges=[0.1],
    )
    side_b = _parent(
        tmp_path,
        "side-b",
        ["O"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.08]],
        [[2.1, 2.2, 2.3]],
    )
    with pytest.raises(ValueError, match="initial_charges must be zero"):
        build_layered_interface(side_a.artifact_dir, side_b.artifact_dir, _request(), tmp_path / "interface")


def test_explicit_overlap_is_rejected(tmp_path):
    side_a = _parent(
        tmp_path,
        "side-a",
        ["Ni"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 3.52]],
        [[0.7, 0.8, 0.9]],
    )
    side_b = _parent(
        tmp_path,
        "side-b",
        ["O"],
        [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.08]],
        [[0.7, 0.8, 0.9]],
    )
    request = _request()
    request["gap_ab_angstrom"] = 0.0
    request["gap_ba_angstrom"] = 0.0
    with pytest.raises(ValueError, match="overlap rejected"):
        build_layered_interface(side_a.artifact_dir, side_b.artifact_dir, request, tmp_path / "interface")
