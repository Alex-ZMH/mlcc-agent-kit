from __future__ import annotations

import json

import ase
import pytest
import pymatgen

from mlcc.modeling import build_nickel_fcc_fixture, read_model_artifacts


def test_nickel_fixture_writes_and_reads_stable_model(tmp_path):
    result = build_nickel_fcc_fixture(tmp_path / "model")
    directory = result.artifact_dir
    assert {path.name for path in directory.iterdir()} == {
        "source.cif",
        "model.extxyz",
        "model.json",
        "dopants.json",
    }
    assert len(result.atoms) == 4
    assert result.atom_ids == [0, 1, 2, 3]
    metadata = json.loads((directory / "model.json").read_text(encoding="utf-8"))
    assert metadata["fixture"] is True
    assert metadata["scientific_status"] == "engineering_fixture_not_production"
    assert metadata["composition"] == {"Ni": 4}

    loaded = read_model_artifacts(directory)
    assert loaded.atom_ids == result.atom_ids
    assert loaded.atoms.get_chemical_symbols() == ["Ni"] * 4
    assert loaded.atoms.cell.array == pytest.approx(result.atoms.cell.array)
    assert loaded.atoms.get_positions() == pytest.approx(result.atoms.get_positions())


def test_displaced_fixture_keeps_source_cif_unperturbed(tmp_path):
    result = build_nickel_fcc_fixture(
        tmp_path / "model",
        displaced_atom_id=0,
        displacement_angstrom=0.03,
    )
    assert result.metadata["engineering_perturbation"]["atom_id"] == 0
    assert result.metadata["source_atoms"][0]["cart_coords_angstrom"] != result.metadata["atoms"][0]["cart_coords_angstrom"]
    source = ase.io.read(str(result.artifact_dir / "source.cif"), format="cif")
    model = ase.io.read(str(result.artifact_dir / "model.extxyz"), format="extxyz")
    assert source.get_positions() != pytest.approx(model.get_positions())


def test_model_reader_rejects_extxyz_atom_id_mismatch(tmp_path):
    result = build_nickel_fcc_fixture(tmp_path / "model")
    broken = ase.io.read(str(result.artifact_dir / "model.extxyz"), format="extxyz")
    broken.set_array("atom_id", broken.arrays["atom_id"] + 100)
    ase.io.write(str(result.artifact_dir / "model.extxyz"), broken, format="extxyz")
    with pytest.raises(ValueError, match="atom_id values differ"):
        read_model_artifacts(result.artifact_dir)

