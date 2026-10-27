from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.constraints import FixAtoms
from ase.io import read as ase_read

from mlcc.modeling import read_model_artifacts, write_model_artifacts
from mlcc.phonons import (
    FORCE_CONSTANT_UNIT,
    FORCE_UNIT,
    compute_harmonic_qpoints,
    generate_phonon_displacement_plan,
    load_phonon_displacement_plan,
)


def _request(
    *,
    plan_id: str = "math-phonon-plan",
    repeat_matrix: list[list[int]] | None = None,
    primitive_matrix: list[list[float]] | None = None,
    is_symmetry: bool = False,
) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "version": "v001",
        "phonopy_version": "4.8.3",
        "repeat_matrix": repeat_matrix or [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "primitive_matrix": primitive_matrix
        or [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "distance_angstrom": 0.01,
        "symprec": 1e-5,
        "is_symmetry": is_symmetry,
        "hermitianize_dynamical_matrix": True,
    }


def _write_parent(tmp_path: Path, *, one_atom: bool = False) -> Path:
    if one_atom:
        atoms = Atoms(
            symbols=["Na"],
            scaled_positions=[[0.0, 0.0, 0.0]],
            cell=np.eye(3) * 3.0,
            pbc=True,
        )
        atoms.set_masses([10.0])
    else:
        atoms = Atoms(
            symbols=["Na", "Cl"],
            scaled_positions=[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
            cell=[[3.0, 0.0, 0.0], [0.2, 3.1, 0.0], [0.1, 0.2, 3.2]],
            pbc=True,
        )
        atoms.set_masses([10.0, 20.0])
        atoms.new_array("initial_magmoms", np.asarray([1.0, -1.0]))
    atoms.new_array("atom_id", np.arange(len(atoms), dtype=np.int64))
    model_dir = tmp_path / ("one-atom" if one_atom else "two-atom")
    write_model_artifacts(
        atoms,
        model_dir,
        model_id="math-parent",
        version="v001",
        fixture=False,
        phase_requested="explicit_test_structure",
        source_path="test-structure",
        source_version="test-v001",
        material="test-material",
    )
    return model_dir


def test_plan_records_explicit_pairs_lineage_and_row_cell_convention(tmp_path):
    parent_path = _write_parent(tmp_path)
    repeat = [[2, 1, 0], [0, 1, 0], [0, 0, 1]]
    output = tmp_path / "plan"
    manifest = generate_phonon_displacement_plan(
        parent_path,
        _request(repeat_matrix=repeat),
        output,
    )
    loaded = load_phonon_displacement_plan(output / "displacement-manifest.json")
    assert loaded == manifest
    assert manifest["reference"]["entry_id"] == "reference"
    assert manifest["request"]["repeat_matrix"] == repeat
    assert manifest["request"]["supercell_matrix"] == np.asarray(repeat, dtype=int).T.tolist()
    assert manifest["coordinate_convention"]["cell_storage"] == "row_vectors_angstrom"
    assert manifest["request"]["is_plusminus"] is True

    parent = read_model_artifacts(parent_path)
    reference = ase_read(
        str(output / manifest["reference"]["structure_file"]),
        format="extxyz",
        index=0,
    )
    assert np.allclose(
        reference.cell.array,
        np.asarray(repeat, dtype=float) @ parent.atoms.cell.array,
        rtol=0.0,
        atol=1e-12,
    )
    assert reference.arrays["atom_id"].tolist() == list(range(len(reference)))
    assert reference.get_masses().tolist() == pytest.approx([10.0, 10.0, 20.0, 20.0])
    assert reference.arrays["initial_magmoms"].tolist() == pytest.approx([1.0, 1.0, -1.0, -1.0])

    parent_cell = parent.atoms.cell.array
    parent_frac = parent.atoms.get_scaled_positions(wrap=False)
    parent_ids = parent.atom_ids
    for index, record in enumerate(manifest["reference"]["atom_lineage"]):
        parent_index = parent_ids.index(record["parent_atom_id"])
        image = np.asarray(record["parent_image"], dtype=int)
        expected = (parent_frac[parent_index] + image) @ parent_cell
        assert reference.positions[index] == pytest.approx(expected, abs=1e-10)

    displacement_keys = {
        (
            int(entry["phonopy_atom_index"]),
            tuple(float(value) for value in np.round(entry["displacement_angstrom"], 12)),
        )
        for entry in manifest["displacements"]
    }
    assert displacement_keys
    for entry in manifest["displacements"]:
        vector = np.asarray(entry["displacement_angstrom"], dtype=float)
        opposite = (int(entry["phonopy_atom_index"]), tuple(float(value) for value in np.round(-vector, 12)))
        assert opposite in displacement_keys
        structure = ase_read(str(output / entry["structure_file"]), format="extxyz", index=0)
        expected_positions = reference.positions.copy()
        expected_positions[int(entry["phonopy_atom_index"])] += vector
        assert np.allclose(structure.positions, expected_positions, rtol=0.0, atol=1e-7)
        assert structure.arrays["atom_id"].tolist() == manifest["reference"]["atom_ids"]
        assert len(entry["atom_lineage"]) == len(structure)


def test_plan_rejects_implicit_parameters_charged_and_constrained_models(tmp_path, monkeypatch):
    parent_path = _write_parent(tmp_path)
    missing_primitive = _request()
    missing_primitive.pop("primitive_matrix")
    with pytest.raises(ValueError, match="primitive_matrix"):
        generate_phonon_displacement_plan(parent_path, missing_primitive, tmp_path / "missing-primitive")

    missing_symmetry = _request()
    missing_symmetry.pop("is_symmetry")
    with pytest.raises(ValueError, match="is_symmetry"):
        generate_phonon_displacement_plan(parent_path, missing_symmetry, tmp_path / "missing-symmetry")

    parent_metadata_path = parent_path / "model.json"
    metadata = json.loads(parent_metadata_path.read_text(encoding="utf-8"))
    metadata["charge_state"] = 1
    parent_metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="charged models"):
        generate_phonon_displacement_plan(parent_path, _request(), tmp_path / "charged")

    unconstrained = read_model_artifacts(_write_parent(tmp_path / "constraint-source"))
    unconstrained.atoms.set_constraint(FixAtoms(indices=[0]))
    monkeypatch.setattr("mlcc.phonons.read_model_artifacts", lambda _: unconstrained)
    with pytest.raises(ValueError, match="constrained models"):
        generate_phonon_displacement_plan(
            tmp_path / "does-not-matter",
            _request(plan_id="constrained-plan"),
            tmp_path / "constrained",
        )


def test_saved_plan_is_immutable_and_loader_verifies_parent_snapshot(tmp_path):
    parent_path = _write_parent(tmp_path)
    output = tmp_path / "plan"
    generate_phonon_displacement_plan(parent_path, _request(), output)
    with pytest.raises(FileExistsError, match="already exists"):
        generate_phonon_displacement_plan(parent_path, _request(plan_id="second-plan"), output)

    parent_snapshot_path = output / "structures" / "parent-unitcell.extxyz"
    parent_snapshot = ase_read(str(parent_snapshot_path), format="extxyz", index=0)
    parent_snapshot.positions[0, 0] += 0.2
    from ase.io import write as ase_write

    ase_write(str(parent_snapshot_path), parent_snapshot, format="extxyz")
    with pytest.raises(ValueError, match="parent snapshot geometry"):
        load_phonon_displacement_plan(output / "displacement-manifest.json")

    output2 = tmp_path / "plan-request-tamper"
    generate_phonon_displacement_plan(parent_path, _request(plan_id="request-tamper"), output2)
    manifest_path = output2 / "displacement-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["request"]["is_plusminus"] = False
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fixed to True"):
        load_phonon_displacement_plan(manifest_path)

    output3 = tmp_path / "plan-null-charge"
    metadata_path = parent_path / "model.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["charge_state"] = None
    metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be null"):
        generate_phonon_displacement_plan(parent_path, _request(plan_id="null-charge"), output3)


def test_harmonic_qpoints_rebuild_plan_and_preserve_math_only_status(tmp_path):
    parent_path = _write_parent(tmp_path, one_atom=True)
    output = tmp_path / "one-atom-plan"
    manifest = generate_phonon_displacement_plan(
        parent_path,
        _request(plan_id="one-atom-harmonic"),
        output,
    )
    spring = 0.75
    records = []
    for entry in manifest["displacements"]:
        force = np.zeros((len(entry["atom_ids"]), 3), dtype=float)
        force[int(entry["phonopy_atom_index"])] = -spring * np.asarray(entry["displacement_angstrom"])
        records.append(
            {
                "entry_id": entry["entry_id"],
                "atom_ids": entry["atom_ids"],
                "forces": force.tolist(),
                "source_ref": f"math://{entry['entry_id']}",
            }
        )
    force_bundle = {
        "unit": FORCE_UNIT,
        "source": "analytic_harmonic_fixture",
        "records": records,
    }
    result_path = tmp_path / "harmonic-result.json"
    result = compute_harmonic_qpoints(
        output / "displacement-manifest.json",
        force_bundle,
        [[0.0, 0.0, 0.0], [0.25, 0.0, 0.0]],
        output_path=result_path,
    )
    force_constants = np.asarray(result["force_constants"], dtype=float)
    frequencies = np.asarray(result["frequencies_THz"], dtype=float)
    assert result["scientific_status"] == "software_math_only_unqualified"
    assert result["force_constants_unit"] == FORCE_CONSTANT_UNIT
    assert result["q_point_coordinate_basis"] == "primitive_reciprocal_fractional"
    assert result["production_qualified"] is False
    assert result["scientific_qualification"] is False
    assert force_constants.shape == (1, 1, 3, 3)
    assert force_constants[0, 0] == pytest.approx(np.eye(3) * spring, abs=1e-10)
    assert frequencies.shape == (2, 3)
    assert frequencies == pytest.approx(np.full((2, 3), 4.28135616), abs=1e-7)
    assert result["nac"] == "not_requested"
    assert result["asr"] == "not_applied"
    assert json.loads(result_path.read_text(encoding="utf-8"))["plan"]["plan_id"] == "one-atom-harmonic"
    with pytest.raises(FileExistsError):
        compute_harmonic_qpoints(
            output / "displacement-manifest.json",
            force_bundle,
            [[0.0, 0.0, 0.0]],
            output_path=result_path,
        )

    # A negative spring is an analytic unstable Hessian, not a material result.
    unstable_bundle = {
        **force_bundle,
        "records": [{**record, "forces": (-np.asarray(record["forces"])).tolist()}
                    for record in records],
    }
    unstable = compute_harmonic_qpoints(output / "displacement-manifest.json",
                                       unstable_bundle, [[0, 0, 0]])
    assert np.asarray(unstable["frequencies_THz"]) == pytest.approx(-frequencies[:1], abs=1e-7)
    assert unstable["imaginary_frequencies_preserved"] is True


def test_harmonic_qpoints_require_source_bound_force_records(tmp_path):
    parent_path = _write_parent(tmp_path, one_atom=True)
    output = tmp_path / "plan"
    manifest = generate_phonon_displacement_plan(parent_path, _request(), output)
    records = [
        {
            "entry_id": entry["entry_id"],
            "atom_ids": entry["atom_ids"],
            "forces": [[0.0, 0.0, 0.0]],
            "source_ref": f"math://{entry['entry_id']}",
        }
        for entry in manifest["displacements"]
    ]
    with pytest.raises(ValueError, match="exactly 'eV/angstrom'"):
        compute_harmonic_qpoints(
            output / "displacement-manifest.json",
            {"unit": "eV/A", "source": "fixture", "records": records},
            [[0.0, 0.0, 0.0]],
        )
    records[0] = {**records[0], "source_ref": ""}
    with pytest.raises(ValueError, match="source_ref"):
        compute_harmonic_qpoints(
            output / "displacement-manifest.json",
            {"unit": FORCE_UNIT, "source": "fixture", "records": records},
            [[0.0, 0.0, 0.0]],
        )
