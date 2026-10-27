"""Unit-only VASP mapping/stress tests using a stubbed pymatgen parser.

The repository has no authorized VASP/POTCAR output fixture. These tests do
not claim that real VASP XML/OUTCAR has been parsed; P3 still needs the remote
Slurm run and its original artifacts.
"""

from __future__ import annotations

import json
import shutil

import numpy as np
import pymatgen
import pytest

from ase import Atoms

from mlcc import vasp as vasp_module
from mlcc.vasp import VaspParameters, parse_vasp_outputs, prepare_vasp, read_poscar_with_mapping


def test_user_kmesh_rule_is_minimal_for_actual_cell_lengths():
    from mlcc.vasp import minimum_product_kmesh
    atoms = Atoms("Ni", cell=[3.52, 8.0, 15.0], pbc=True)
    mesh = minimum_product_kmesh(atoms)
    assert mesh == (9, 4, 2)
    lengths = atoms.cell.lengths()
    assert np.all(lengths * mesh >= 30)
    assert np.all(lengths * (np.asarray(mesh) - 1) < 30)


def _parameters(*, relax: bool = False) -> VaspParameters:
    return VaspParameters(
        encut_eV=400.0,
        kpoints=(4, 4, 4),
        ismear=1,
        sigma_eV=0.2,
        ediff_eV=1e-6,
        ediffg_eV_per_A=-0.02,
        ispin=2,
        initial_magnetic_moments=(1.0, 0.0),
        nbands=32,
        lwave=False,
        lcharg=False,
        lreal=False,
        istart=0,
        icharg=2,
        isym=0,
        lorbit=11,
        nsw=5 if relax else 0,
        ibrion=2,
        isif=2,
        prec="Accurate",
        algo="Normal",
        nelm=120,
    )


def _two_element_model() -> Atoms:
    atoms = Atoms(
        symbols=["O", "Ni"],
        scaled_positions=[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        cell=np.diag([3.0, 3.0, 3.0]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.array([41, 7], dtype=int))
    return atoms


def test_prepare_vasp_groups_elements_and_roundtrips_atom_map(tmp_path):
    atoms = _two_element_model()
    prepared = prepare_vasp(
        atoms,
        tmp_path,
        parameters=_parameters(),
        stage="scf",
        element_order=["Ni", "O"],
    )
    assert prepared.poscar_atom_ids == [7, 41]
    for filename in ("POSCAR", "INCAR", "KPOINTS"):
        assert b"\r" not in (tmp_path / filename).read_bytes()
    assert "POTCAR" not in {path.name for path in tmp_path.iterdir()}
    incar = (tmp_path / "INCAR").read_text(encoding="utf-8")
    assert "ENCUT = 400.0" in incar
    assert "ISPIN = 2" in incar
    assert "MAGMOM = 1*0.0 1*1.0" in incar
    assert "NBANDS = 32" in incar
    assert "LWAVE = False" in incar
    assert "LCHARG = False" in incar
    assert "LREAL = False" in incar
    assert "ISTART = 0" in incar
    assert "ICHARG = 2" in incar
    assert "ISYM = 0" in incar
    assert "LORBIT = 11" in incar
    assert (tmp_path / "KPOINTS").read_text(encoding="utf-8").splitlines()[3] == "4 4 4"
    loaded = read_poscar_with_mapping(tmp_path / "POSCAR")
    assert loaded.arrays["atom_id"].tolist() == [7, 41]
    mapping = json.loads((tmp_path / "POSCAR.atom-map.json").read_text(encoding="utf-8"))
    assert mapping["source_atom_ids"] == [41, 7]


def test_parse_vasp_outputs_converts_stress_and_restores_source_order(tmp_path, monkeypatch):
    atoms = _two_element_model()
    prepare_vasp(
        atoms,
        tmp_path,
        parameters=_parameters(relax=True),
        stage="relax",
        element_order=["Ni", "O"],
    )
    shutil.copyfile(tmp_path / "POSCAR", tmp_path / "CONTCAR")
    for name in ("vasprun.xml", "OUTCAR"):
        (tmp_path / name).write_text("fixture parser input\n", encoding="utf-8")
    from pymatgen.io.vasp.inputs import Poscar

    xml_structure = Poscar.from_file(str(tmp_path / "POSCAR"), check_for_potcar=False).structure

    class FakeVasprun:
        final_structure = xml_structure
        final_energy = -12.5
        ionic_steps = [
            {
                # VASP/POSCAR order is Ni(atom 7), O(atom 41).
                "forces": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
                "stress": [[10.0, 1.0, 2.0], [1.0, 20.0, 3.0], [2.0, 3.0, 30.0]],
                "e_fr_energy": -12.4,
                "e_0_energy": -12.5,
                "e_wo_entrp": -12.45,
            }
        ]
        converged_electronic = True
        converged_ionic = False
        init_kwargs = None

        def __init__(self, *args, **kwargs):
            type(self).init_kwargs = kwargs

    class FakeOutcar:
        magnetization = [{"tot": 0.2}, {"tot": 1.2}]

        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(vasp_module, "Vasprun", FakeVasprun)
    monkeypatch.setattr(vasp_module, "Outcar", FakeOutcar)
    result = parse_vasp_outputs(tmp_path, stage="relax")
    assert result.atom_ids == [41, 7]
    assert result.e_fr_energy == pytest.approx(-12.4)
    assert result.e_0_energy == pytest.approx(-12.5)
    assert result.e_wo_entrp == pytest.approx(-12.45)
    assert result.forces_eV_per_A == [[4.0, 5.0, 6.0], [1.0, 2.0, 3.0]]
    assert result.stress_voigt_vasp_compression_positive_GPa == pytest.approx(
        [1.0, 2.0, 3.0, 0.3, 0.2, 0.1]
    )
    assert result.stress_voigt_tensile_positive_GPa == pytest.approx(
        [-1.0, -2.0, -3.0, -0.3, -0.2, -0.1]
    )
    assert result.electronic_converged is True
    assert result.ionic_converged is False
    assert result.magnetization == [{"tot": 1.2}, {"tot": 0.2}]
    assert FakeVasprun.init_kwargs["parse_potcar_file"] is False

