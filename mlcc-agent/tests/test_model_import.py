from __future__ import annotations

import json
from pathlib import Path
import re

import numpy as np
import pytest
from ase import Atoms
from ase.io import read as ase_read
from ase.io import write as ase_write

from mlcc.abacus import (
    AbacusExecution,
    AbacusMethod,
    AbacusParameters,
    prepare_abacus,
)
from mlcc.cli import main
from mlcc.modeling import import_model_artifacts, read_model_artifacts
from mlcc.vasp import VaspParameters, prepare_vasp, read_poscar_with_mapping


ROOT = Path(__file__).resolve().parents[2]
CZO_SOURCE = ROOT / "workspace" / "sources" / "cazro3" / "COD-1532747.cif"
NI_EXTXYZ = ROOT / "workspace" / "models" / "ni-fcc-engineering" / "v001" / "model.extxyz"
NI_POSCAR = ROOT / "workspace" / "tasks" / "h0-ni-single-v002" / "POSCAR"

CZO_TRANSFORM = {
    "kind": "right_handed_equivalent",
    "fractional_matrix": [[-1, 0, 0], [0, 0, -1], [0, -1, 0]],
    "fractional_translation": [0, 0, 0],
    "axis_reference": "cazro3-setting-audit-v001",
    "target_lattice_angstrom": [
        [5.58305, 0.0, 0.0],
        [0.0, 5.75904, 0.0],
        [0.0, 0.0, 8.00703],
    ],
}


def _czo_request(source: Path, *, model_id: str = "cazro3-pnma-test") -> dict:
    return {
        "source_path": str(source.resolve()),
        "source_format": "cif",
        "source_reference": "COD-1532747",
        "source_version": "COD-1532747",
        "material": "CaZrO3",
        "phase_requested": "orthorhombic_Pnma",
        "model_id": model_id,
        "version": "v001",
        "basis_transform": CZO_TRANSFORM,
    }


def _ni_request(source: Path, *, source_format: str, model_id: str) -> dict:
    return {
        "source_path": str(source.resolve()),
        "source_format": source_format,
        "source_reference": "local-ni-engineering-fixture",
        "source_version": "h0-v001",
        "material": "Ni",
        "phase_requested": "fcc_engineering_fixture",
        "model_id": model_id,
        "version": "v001",
        "fixture": True,
        "fixture_purpose": "connection_test",
    }


def test_import_czo_cif_applies_audited_equivalent_setting_and_retains_source(tmp_path):
    output = tmp_path / "cazro3-pnma"
    result = import_model_artifacts(_czo_request(CZO_SOURCE), output)

    assert result.metadata["material"] == "CaZrO3"
    assert result.metadata["phase_requested"] == "orthorhombic_Pnma"
    assert result.metadata["source_format"] == "cif"
    assert result.metadata["source_index_basis"] == "full_expanded_structure_order"
    assert result.metadata["source_asymmetric_site_mapping"] == "not_one_to_one_for_cif_asymmetric_sites"
    assert result.metadata["scientific_status"] == "source_reference_unrelaxed"
    assert result.metadata["production_qualified"] is False
    assert result.metadata["relaxation_status"] == "not_run"
    assert result.metadata["composition"] == {"Ca": 4, "Zr": 4, "O": 12}
    assert len(result.atoms) == 20
    assert np.linalg.det(result.atoms.cell.array) == pytest.approx(5.58305 * 5.75904 * 8.00703)
    assert result.atoms.cell.array == pytest.approx(np.diag([5.58305, 5.75904, 8.00703]))
    assert result.atom_ids == list(range(20))
    assert (output / "source.original.cif").read_bytes() == CZO_SOURCE.read_bytes()
    assert (output / "source.extxyz").is_file()
    lineage = json.loads((output / "atom-lineage.json").read_text(encoding="utf-8"))
    assert lineage["source_index_basis"] == "full_expanded_structure_order"
    assert len(lineage["entries"]) == 20
    loaded = read_model_artifacts(output)
    assert loaded.atom_ids == list(range(20))
    assert loaded.metadata["material"] == "CaZrO3"
    dopants = json.loads((output / "dopants.json").read_text(encoding="utf-8"))
    assert dopants["material"] == "CaZrO3"
    assert dopants["material_selection_confirmed"] == result.metadata["material_selection_confirmed"]


def test_import_rejects_fractional_cif_occupancy(tmp_path):
    source = tmp_path / "fractional.cif"
    source.write_text(CZO_SOURCE.read_text(encoding="utf-8").replace(" 1 0.0", " 0.5 0.0", 1), encoding="utf-8")
    request = _czo_request(source, model_id="fractional-czo")
    with pytest.raises(ValueError, match="fractional occupancy"):
        import_model_artifacts(request, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_import_rejects_ambiguous_multiblock_cif_without_index(tmp_path):
    original = CZO_SOURCE.read_text(encoding="utf-8")
    second = original.replace("data_1532747", "data_second", 1)
    source = tmp_path / "blocks.cif"
    source.write_text(original + "\n" + second, encoding="utf-8")
    request = _czo_request(source, model_id="czo-blocks")
    with pytest.raises(ValueError, match="multiple structure blocks"):
        import_model_artifacts(request, tmp_path / "output")
    request["source_index"] = 1
    result = import_model_artifacts(request, tmp_path / "selected")
    assert result.metadata["source_index"] == 1
    assert result.metadata["source_block"] == "cif_block_1"
    assert result.atom_ids == list(range(20))


def test_import_requires_explicit_phase_selection(tmp_path):
    request = _czo_request(CZO_SOURCE)
    request.pop("phase_requested")
    with pytest.raises(ValueError, match="phase_requested"):
        import_model_artifacts(request, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_invalid_cif_block_cannot_shift_the_selected_source_index(tmp_path):
    original = CZO_SOURCE.read_text(encoding="utf-8")
    invalid = original.replace("data_1532747", "data_invalid", 1)
    invalid = re.sub(r"(?m)^(_cell_length_a\s+).+$", r"\g<1>invalid_length", invalid)
    third = original.replace("data_1532747", "data_third", 1)
    source = tmp_path / "invalid-middle-block.cif"
    source.write_text("\n".join([original, invalid, third]), encoding="utf-8")
    request = _czo_request(source)
    request["source_index"] = 1
    with pytest.raises(ValueError, match="No structure parsed for section 2"):
        import_model_artifacts(request, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_cif_block_returning_none_cannot_shift_the_selected_source_index(tmp_path):
    original = CZO_SOURCE.read_text(encoding="utf-8")
    invalid = """data_invalid
_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
loop_
_symmetry_equiv_pos_as_xyz
  'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
  bad1 ? 0 0 0 1
"""
    third = original.replace("data_1532747", "data_third", 1)
    source = tmp_path / "none-middle-block.cif"
    source.write_text("\n".join([original, invalid, third]), encoding="utf-8")
    request = _czo_request(source)
    request["source_index"] = 1
    with pytest.raises(ValueError, match="structure block count"):
        import_model_artifacts(request, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_import_rejects_ambiguous_multiframe_extxyz_without_index(tmp_path):
    source_atoms = ase_read(str(NI_EXTXYZ), format="extxyz", index=0)
    source = tmp_path / "frames.extxyz"
    ase_write(str(source), [source_atoms, source_atoms.copy()], format="extxyz")
    request = _ni_request(source, source_format="extxyz", model_id="ni-frames")
    with pytest.raises(ValueError, match="multiple frames"):
        import_model_artifacts(request, tmp_path / "output")
    request["source_index"] = 1
    result = import_model_artifacts(request, tmp_path / "selected")
    assert result.metadata["source_index"] == 1
    assert result.atom_ids == [0, 1, 2, 3]


def test_import_extxyz_preserves_ids_magnetic_moments_and_pbc(tmp_path):
    result = import_model_artifacts(_ni_request(NI_EXTXYZ, source_format="extxyz", model_id="ni-extxyz"), tmp_path / "model")
    assert result.metadata["source_format"] == "extxyz"
    assert result.metadata["source_atom_id_origin"] == "source_extxyz"
    assert result.atom_ids == [0, 1, 2, 3]
    assert result.metadata["initial_magnetic_moments_muB"] == pytest.approx([0.6] * 4)
    assert result.atoms.pbc.tolist() == [True, True, True]
    source = ase_read(str(result.artifact_dir / "source.extxyz"), format="extxyz", index=0)
    assert source.arrays["atom_id"].tolist() == [0, 1, 2, 3]
    assert source.get_initial_magnetic_moments().tolist() == pytest.approx([0.6] * 4)


def test_import_extxyz_assigns_ids_only_when_absent(tmp_path):
    atoms = Atoms(
        "Ni4",
        scaled_positions=[[0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0]],
        cell=np.diag([3.52, 3.52, 3.52]),
        pbc=True,
    )
    atoms.set_initial_magnetic_moments([0.25] * 4)
    source = tmp_path / "no-ids.extxyz"
    ase_write(str(source), atoms, format="extxyz")
    result = import_model_artifacts(_ni_request(source, source_format="extxyz", model_id="ni-assigned"), tmp_path / "model")
    assert result.atom_ids == [0, 1, 2, 3]
    assert result.metadata["source_atom_id_origin"] == "assigned_source_order"
    assert result.metadata["source_initial_magnetic_moments_muB"] == pytest.approx([0.25] * 4)


@pytest.mark.parametrize(
    "ids, match",
    [([0.5, 1.0], "must be integers"), ([0, 0], "unique non-negative integers")],
)
def test_import_extxyz_rejects_decimal_or_duplicate_ids(tmp_path, ids, match):
    atoms = Atoms("Ni2", cell=np.diag([3.52, 3.52, 3.52]), pbc=True)
    atoms.new_array("atom_id", np.asarray(ids))
    source = tmp_path / "bad-ids.extxyz"
    ase_write(str(source), atoms, format="extxyz")
    with pytest.raises(ValueError, match=match):
        import_model_artifacts(_ni_request(source, source_format="extxyz", model_id="ni-bad-ids"), tmp_path / "model")


@pytest.mark.parametrize(
    "matrix, match",
    [
        (
            [[2**-0.5, -(2**-0.5), 0], [2**-0.5, 2**-0.5, 0], [0, 0, 1]],
            "integer unimodular",
        ),
        ([[2, 0, 0], [0, 1, 0], [0, 0, 1]], "integer unimodular"),
    ],
)
def test_import_rejects_noninteger_or_nonunimodular_basis_matrix(tmp_path, matrix, match):
    request = _ni_request(NI_EXTXYZ, source_format="extxyz", model_id="ni-bad-transform")
    request["basis_transform"] = {
        "kind": "equivalent_setting",
        "fractional_matrix": matrix,
        "fractional_translation": [0, 0, 0],
        "axis_reference": "test-transform",
        "target_lattice_angstrom": np.diag([3.52, 3.52, 3.52]).tolist(),
    }
    with pytest.raises(ValueError, match=match):
        import_model_artifacts(request, tmp_path / "model")


def test_import_rejects_untransformed_cartesian_vector_arrays(tmp_path):
    atoms = Atoms("Ni", cell=np.diag([3.52, 3.52, 3.52]), pbc=True)
    atoms.set_initial_magnetic_moments([[1.0, 0.0, 0.0]])
    source = tmp_path / "vector.extxyz"
    ase_write(str(source), atoms, format="extxyz")
    request = _ni_request(source, source_format="extxyz", model_id="ni-vector")
    request["basis_transform"] = {
        "kind": "equivalent_setting",
        "fractional_matrix": [[0, 1, 0], [1, 0, 0], [0, 0, -1]],
        "fractional_translation": [0, 0, 0],
        "axis_reference": "test-vector-transform",
        "target_lattice_angstrom": np.diag([3.52, 3.52, 3.52]).tolist(),
    }
    with pytest.raises(ValueError, match="vector arrays"):
        import_model_artifacts(request, tmp_path / "model")


def test_import_poscar_reads_full_periodic_structure(tmp_path):
    result = import_model_artifacts(_ni_request(NI_POSCAR, source_format="poscar", model_id="ni-poscar"), tmp_path / "model")
    assert result.metadata["source_format"] == "poscar"
    assert result.atom_ids == [0, 1, 2, 3]
    assert result.atoms.pbc.tolist() == [True, True, True]
    assert (result.artifact_dir / "source.original").exists() is False
    assert (result.artifact_dir / "source.original.poscar").is_file()


def test_import_cli_writes_json_result(tmp_path, capsys):
    relative_source = tmp_path / "source.cif"
    relative_source.write_bytes(CZO_SOURCE.read_bytes())
    request_data = _czo_request(relative_source)
    request_data["source_path"] = "source.cif"
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request_data), encoding="utf-8")
    output = tmp_path / "cli-model"
    assert main(["import-model", "--request", str(request_path), "--output", str(output)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["model_id"] == "cazro3-pnma-test"
    assert printed["metadata"]["material"] == "CaZrO3"
    assert Path(printed["artifact_dir"]) == output


def test_vasp_and_abacus_grouping_maps_are_reversible_for_imported_model(tmp_path):
    model = import_model_artifacts(_czo_request(CZO_SOURCE), tmp_path / "model")
    vasp = prepare_vasp(
        model,
        tmp_path / "vasp",
        parameters=VaspParameters(
            encut_eV=400.0,
            kpoints=(2, 2, 2),
            ismear=0,
            sigma_eV=0.05,
            ediff_eV=1e-6,
            ediffg_eV_per_A=-0.02,
            ispin=1,
            initial_magnetic_moments=(0.0,) * 20,
            nbands=32,
            lwave=False,
            lcharg=False,
            lreal=False,
            istart=0,
            icharg=2,
            isym=0,
            lorbit=11,
            nsw=0,
            ibrion=-1,
            isif=2,
            prec="Accurate",
            algo="Normal",
            nelm=80,
        ),
        stage="scf",
        element_order=["Ca", "Zr", "O"],
    )
    assert read_poscar_with_mapping(vasp.files["POSCAR"]).arrays["atom_id"].tolist() == model.atom_ids
    vasp_map = json.loads((tmp_path / "vasp" / "POSCAR.atom-map.json").read_text(encoding="utf-8"))
    assert vasp_map["source_atom_ids"] == model.atom_ids
    assert {entry["atom_id"] for entry in vasp_map["poscar_order"]} == set(model.atom_ids)

    abacus = prepare_abacus(
        model,
        tmp_path / "abacus",
        method=AbacusMethod(
            suffix="CZOImport",
            dft_functional="PBE",
            nspin=1,
            initial_moments_muB_by_element={"Ca": 0.0, "Zr": 0.0, "O": 0.0},
            occupations="fixed",
            smearing_method=None,
            mixing_type="broyden",
            relax_method="cg",
            symmetry=0,
        ),
        execution=AbacusExecution(device="cpu", ks_solver="cg"),
        parameters=AbacusParameters(
            ecutwfc_Ry=100.0,
            scf_thr=1e-8,
            scf_nmax=100,
            nbands=32,
            smearing_sigma_Ry=None,
            mixing_beta=0.4,
        ),
        stage="scf",
        pseudopotentials={"Ca": "Ca.upf", "Zr": "Zr.upf", "O": "O.upf"},
        element_order=["Ca", "Zr", "O"],
        kpoints=(2, 2, 2),
    )
    abacus_map = json.loads((tmp_path / "abacus" / "STRU.atom-map.json").read_text(encoding="utf-8"))
    assert abacus_map["source_atom_ids"] == model.atom_ids
    assert {entry["atom_id"] for entry in abacus_map["abacus_order"]} == set(model.atom_ids)
    assert [entry["element"] for entry in abacus_map["abacus_order"][:4]] == ["Ca"] * 4
    assert [entry["element"] for entry in abacus_map["abacus_order"][4:8]] == ["Zr"] * 4
    assert all(entry["element"] == "O" for entry in abacus_map["abacus_order"][8:])

