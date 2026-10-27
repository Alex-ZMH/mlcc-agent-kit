"""Focused ABACUS adapter tests.

The log and ``STRU_ION_D`` text below are documented-format samples, not real
ABACUS measurements.  Real validation remains the Slurm task and its retained
native output files.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.abacus import (
    ABACUS_BASIS_TYPE,
    ABACUS_VERSION,
    BOHR_PER_ANGSTROM,
    AbacusExecution,
    AbacusMethod,
    AbacusParameters,
    _convergence_marker,
    _parse_forces,
    _parse_total_magnetization,
    _scf_iterations,
    parse_abacus_outputs,
    prepare_abacus,
)
from mlcc.modeling import (
    ModelArtifacts,
    build_nickel_fcc_fixture,
    read_model_artifacts,
    write_model_artifacts,
)


def _ni_model(tmp_path) -> ModelArtifacts:
    return build_nickel_fcc_fixture(tmp_path / "model")


def _ni_method(
    *,
    suffix: str = "NiPW",
    occupations: str = "smearing",
    nspin: int = 2,
    moment: float = 0.6,
) -> AbacusMethod:
    return AbacusMethod(
        suffix=suffix,
        dft_functional="PBE",
        nspin=nspin,
        initial_moments_muB_by_element={"Ni": moment},
        occupations=occupations,
        smearing_method="gauss" if occupations == "smearing" else None,
        mixing_type="broyden",
        relax_method="cg",
        symmetry=0,
    )


def _execution(*, device: str = "gpu", ks_solver: str = "cg") -> AbacusExecution:
    return AbacusExecution(device=device, ks_solver=ks_solver)


def _parameters(*, relax: bool, occupations: str = "smearing") -> AbacusParameters:
    return AbacusParameters(
        ecutwfc_Ry=100.0,
        scf_thr=1e-8,
        scf_nmax=100,
        nbands=56,
        smearing_sigma_Ry=0.007349864 if occupations == "smearing" else None,
        mixing_beta=0.4,
        force_thr_eV_per_A=0.02 if relax else None,
        relax_nmax=40 if relax else None,
    )


def _sample_log(labels: list[str], *, energy: float = -123.456) -> str:
    force_rows = "\n".join(
        f"{label:<28s}{index + 0.1:.10f}        {index + 0.2:.10f}        {index + 0.3:.10f}"
        for index, label in enumerate(labels)
    )
    return f"""PW ALGORITHM --------------- ION=   3  ELEC=   1--------------------------------
          total magnetism (Bohr mag/cell) = 1.1000000000
PW ALGORITHM --------------- ION=   3  ELEC=   2--------------------------------
          total magnetism (Bohr mag/cell) = 1.2340000000
charge density convergence is achieved
Relaxation is converged!
 TOTAL-FORCE (eV/Angstrom)
------------------------------------------------------------------------------------------
{force_rows}
 TOTAL-STRESS (KBAR):
         2.0         3.0         4.0
         5.0         6.0         7.0
         8.0         9.0        10.0
 E_KS(sigma->0) -123.4000000000 -123.4000000000
 E_entropy(-TS)    -0.0560000000   -0.7616000000
 !FINAL_ETOT_IS {energy:.10f} eV
"""


def test_prepare_abacus_pw_uses_explicit_method_execution_and_mesh(tmp_path):
    prepared = prepare_abacus(
        _ni_model(tmp_path),
        tmp_path,
        method=_ni_method(),
        execution=_execution(),
        parameters=_parameters(relax=True),
        stage="relax",
        pseudopotentials={"Ni": "/home/v100/abacus-work/PPORBs/pseudopotentials/Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(9, 9, 9),
    )

    assert prepared.kpoints == (9, 9, 9)
    assert prepared.abacus_atom_ids == [0, 1, 2, 3]
    assert all(b"\r" not in (tmp_path / filename).read_bytes() for filename in ("INPUT", "STRU", "KPT"))

    input_text = (tmp_path / "INPUT").read_text(encoding="utf-8")
    assert "device               gpu" in input_text
    assert "dft_functional      PBE" in input_text
    assert "basis_type           pw" in input_text
    assert "ks_solver            cg" in input_text
    assert "ecutwfc              100" in input_text
    assert "nspin                2" in input_text
    assert "lspinorb             0" in input_text
    assert "noncolin             0" in input_text
    assert "occupations" not in input_text
    assert "smearing_method      gauss" in input_text
    assert "smearing_sigma       0.007349864" in input_text
    assert "force_thr_ev        0.02" in input_text
    assert "relax_nmax          40" in input_text
    assert "NUMERICAL_ORBITAL" not in (tmp_path / "STRU").read_text(encoding="utf-8")

    stru = (tmp_path / "STRU").read_text(encoding="utf-8")
    assert "Ni 58.6934 Ni_ONCV_PBE-1.2.upf upf201" in stru
    assert f"{BOHR_PER_ANGSTROM:.16g}" in stru
    assert "\nNi\n0.6\n4\n" in stru
    assert "m 1 1 1" in stru
    assert (tmp_path / "KPT").read_text(encoding="utf-8").splitlines() == [
        "K_POINTS",
        "0",
        "Gamma",
        "9 9 9 0 0 0",
    ]
    mapping = json.loads((tmp_path / "STRU.atom-map.json").read_text(encoding="utf-8"))
    assert mapping["source_atom_ids"] == [0, 1, 2, 3]
    assert [entry["atom_id"] for entry in mapping["abacus_order"]] == [0, 1, 2, 3]
    method = json.loads((tmp_path / "method.json").read_text(encoding="utf-8"))
    assert method["engine"] == "abacus"
    assert method["abacus_version_target"] == ABACUS_VERSION
    assert method["suffix"] == "NiPW"
    assert method["basis_type"] == ABACUS_BASIS_TYPE
    assert method["kpoint_rule"] == "explicit_mesh"
    assert method["kpoints"] == [9, 9, 9]
    assert method["science"]["occupations"] == "smearing"
    assert method["science"]["lspinorb"] is False
    assert method["science"]["noncolin"] is False
    assert method["execution"] == {"device": "gpu", "ks_solver": "cg"}


def test_prepare_abacus_explicit_two_cubed_mesh_is_written_and_recorded(tmp_path):
    prepared = prepare_abacus(
        _ni_model(tmp_path),
        tmp_path,
        method=_ni_method(),
        execution=_execution(),
        parameters=AbacusParameters(100.0, 1e-4, 100, 56, 0.007349864, 0.4),
        stage="scf",
        pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(2, 2, 2),
    )

    assert prepared.kpoints == (2, 2, 2)
    assert (tmp_path / "KPT").read_text(encoding="utf-8").splitlines()[-1] == "2 2 2 0 0 0"
    method = json.loads((tmp_path / "method.json").read_text(encoding="utf-8"))
    assert method["kpoints"] == [2, 2, 2]
    assert method["kpoint_rule"] == "explicit_mesh"
    assert method["parameters"]["scf_thr"] == pytest.approx(1e-4)


@pytest.mark.parametrize("kpoints", ((2, 2), (2, 0, 2), (2, True, 2)))
def test_prepare_abacus_rejects_nonpositive_or_nonthree_kpoints(tmp_path, kpoints):
    with pytest.raises(ValueError, match="three positive integers"):
        prepare_abacus(
            _ni_model(tmp_path),
            tmp_path / "invalid",
            method=_ni_method(),
            execution=_execution(),
            parameters=_parameters(relax=False),
            stage="scf",
            pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
            element_order=["Ni"],
            kpoints=kpoints,
        )


def test_prepare_abacus_scf_has_no_relax_controls(tmp_path):
    prepare_abacus(
        _ni_model(tmp_path),
        tmp_path,
        method=_ni_method(),
        execution=_execution(),
        parameters=_parameters(relax=False),
        stage="scf",
        pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(9, 9, 9),
    )
    input_text = (tmp_path / "INPUT").read_text(encoding="utf-8")
    assert "calculation           scf" in input_text
    assert "relax_nmax" not in input_text
    assert "force_thr_ev" not in input_text
    assert "out_stru" not in input_text


def test_fixed_occupations_use_native_fixed_smearing_without_sigma(tmp_path):
    model = _ni_model(tmp_path)
    prepare_abacus(
        model,
        tmp_path,
        method=_ni_method(suffix="FixedPW", occupations="fixed", nspin=1, moment=0.0),
        execution=_execution(device="cpu"),
        parameters=_parameters(relax=False, occupations="fixed"),
        stage="scf",
        pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(9, 9, 9),
    )
    input_text = (tmp_path / "INPUT").read_text(encoding="utf-8")
    assert "smearing_method      fixed" in input_text
    assert "smearing_sigma" not in input_text
    assert "occupations" not in input_text
    assert "\nNi\n0\n4\n" in (tmp_path / "STRU").read_text(encoding="utf-8")

    output_dir = tmp_path / "OUT.FixedPW"
    output_dir.mkdir()
    (output_dir / "running_scf.log").write_text(_sample_log(["Ni1", "Ni2", "Ni3", "Ni4"]), encoding="utf-8")
    result = parse_abacus_outputs(tmp_path, source_model=model, stage="scf")
    assert result.occupations == "fixed"
    assert "fixed occupations" in result.as_dict()["energy_definition"]
    assert "finite-smearing" not in result.as_dict()["energy_definition"]


@pytest.mark.parametrize("charge,delta,target", [(2, -2, 70.0), (-2, 2, 74.0)])
def test_prepare_charged_scf_writes_mlcc_native_charge_contract(tmp_path, charge, delta, target):
    method = _ni_method(suffix="NiCharged", occupations="fixed", nspin=1, moment=0.0)
    method = AbacusMethod(**{**method.__dict__, "net_charge": charge})
    qualification = {
        "input_qualified": True,
        "scientific_qualification": False,
        "production_qualification": False,
        "electron_count": {
            "neutral_valence_electrons": 72.0,
            "target_electrons": target,
            "net_charge": charge,
            "nelec": 0,
            "nelec_delta": delta,
            "nbands": 56,
        },
    }
    prepare_abacus(
        _ni_model(tmp_path),
        tmp_path / "charged",
        method=method,
        execution=_execution(device="cpu"),
        parameters=_parameters(relax=False, occupations="fixed"),
        stage="scf",
        pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(2, 2, 2),
        input_qualification=qualification,
    )
    input_text = (tmp_path / "charged" / "INPUT").read_text(encoding="utf-8")
    assert "nelec                0" in input_text
    assert f"nelec_delta          {delta}" in input_text
    method_record = json.loads((tmp_path / "charged" / "method.json").read_text(encoding="utf-8"))
    assert method_record["net_charge"] == charge
    assert method_record["nelec"] == 0
    assert method_record["nelec_delta"] == delta
    assert method_record["charge_convention"] == "positive q removes q electrons"
    assert method_record["scientific_qualification"] is False
    assert method_record["production_qualification"] is False


def test_prepare_charged_writer_rejects_relax_and_berry_stages(tmp_path):
    method = _ni_method(suffix="NiCharged", occupations="fixed", nspin=1, moment=0.0)
    method = AbacusMethod(**{**method.__dict__, "net_charge": 2})
    qualification = {
        "input_qualified": True,
        "scientific_qualification": False,
        "production_qualification": False,
        "electron_count": {
            "neutral_valence_electrons": 72.0,
            "target_electrons": 70.0,
            "net_charge": 2,
            "nelec": 0,
            "nelec_delta": -2,
            "nbands": 56,
        },
    }
    with pytest.raises(ValueError, match="fixed-cell SCF only"):
        prepare_abacus(
            _ni_model(tmp_path), tmp_path / "relax",
            method=method, execution=_execution(device="cpu"),
            parameters=_parameters(relax=True, occupations="fixed"), stage="relax",
            pseudopotentials={"Ni": "Ni.upf"}, element_order=["Ni"], kpoints=(2, 2, 2),
            input_qualification=qualification,
        )
    with pytest.raises(ValueError, match="unsupported for Berry"):
        prepare_abacus(
            _ni_model(tmp_path), tmp_path / "berry",
            method=method, execution=_execution(device="cpu"),
            parameters=_parameters(relax=False, occupations="fixed"), stage="scf",
            pseudopotentials={"Ni": "Ni.upf"}, element_order=["Ni"], kpoints=(2, 2, 2),
            berry={"role": "reference_scf", "out_chg": 1},
            input_qualification=qualification,
        )


def test_parse_abacus_sample_log_and_relaxed_stru_restores_source_order(tmp_path):
    model = _ni_model(tmp_path)
    prepare_abacus(
        model,
        tmp_path,
        method=_ni_method(),
        execution=_execution(),
        parameters=_parameters(relax=True),
        stage="relax",
        pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(9, 9, 9),
    )
    output_dir = tmp_path / "OUT.NiPW"
    output_dir.mkdir()
    (output_dir / "running_relax.log").write_text(
        _sample_log(["Ni1", "Ni2", "Ni3", "Ni4"]), encoding="utf-8"
    )
    (output_dir / "STRU_ION_D").write_text((tmp_path / "STRU").read_text(encoding="utf-8"), encoding="utf-8")

    result = parse_abacus_outputs(tmp_path, source_model=model, stage="relax")

    assert result.energy_eV == pytest.approx(-123.456)
    assert result.energy_sigma0_eV == pytest.approx(-123.4)
    assert result.entropy_minus_TS_eV == pytest.approx(-0.7616)
    assert result.atom_ids == [0, 1, 2, 3]
    assert np.asarray(result.forces_eV_per_A) == pytest.approx(
        np.asarray(
            [
                [0.1, 0.2, 0.3],
                [1.1, 1.2, 1.3],
                [2.1, 2.2, 2.3],
                [3.1, 3.2, 3.3],
            ]
        )
    )
    assert np.asarray(result.stress_kbar) == pytest.approx(
        np.asarray([[2.0, 3.0, 4.0], [5.0, 6.0, 7.0], [8.0, 9.0, 10.0]])
    )
    assert np.asarray(result.stress_GPa) == pytest.approx(
        np.asarray([[0.2, 0.3, 0.4], [0.5, 0.6, 0.7], [0.8, 0.9, 1.0]])
    )
    assert result.electronic_converged is True
    assert result.ionic_converged is True
    assert result.scf_iterations == 2
    assert result.total_magnetization_muB == pytest.approx(1.234)
    assert result.as_dict()["magnetization_status"] == "parsed_native_output"
    assert result.final_atoms.arrays["atom_id"].tolist() == [0, 1, 2, 3]
    assert result.final_atoms.cell.lengths() == pytest.approx([3.52, 3.52, 3.52])
    assert result.as_dict()["stress_sign"] == "abacus_printed"
    assert result.as_dict()["energy_definition"] == (
        "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham at the selected finite smearing"
    )
    assert "finite-smearing" in result.as_dict()["energy_default_definition"]


def test_custom_suffix_and_method_stage_drive_parser_paths(tmp_path):
    model = _ni_model(tmp_path)
    prepare_abacus(
        model,
        tmp_path,
        method=_ni_method(suffix="NiPWStrain"),
        execution=_execution(),
        parameters=_parameters(relax=False),
        stage="scf",
        pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(9, 9, 9),
    )
    output_dir = tmp_path / "OUT.NiPWStrain"
    output_dir.mkdir()
    (output_dir / "running_scf.log").write_text(
        _sample_log(["Ni1", "Ni2", "Ni3", "Ni4"]), encoding="utf-8"
    )
    result = parse_abacus_outputs(tmp_path, source_model=model, stage="scf")
    assert Path(result.source_files["running_scf.log"]).parts[-2:] == (
        "OUT.NiPWStrain",
        "running_scf.log",
    )
    with pytest.raises(ValueError, match="differs from method.json stage"):
        parse_abacus_outputs(tmp_path, source_model=model, stage="relax")


def test_old_method_without_contract_occupations_uses_native_smearing_method(tmp_path):
    model = _ni_model(tmp_path)
    prepare_abacus(
        model,
        tmp_path,
        method=_ni_method(),
        execution=_execution(),
        parameters=_parameters(relax=False),
        stage="scf",
        pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(9, 9, 9),
    )
    method_path = tmp_path / "method.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method.pop("occupations")
    method.pop("science")
    method_path.write_text(json.dumps(method), encoding="utf-8")
    output_dir = tmp_path / "OUT.NiPW"
    output_dir.mkdir()
    (output_dir / "running_scf.log").write_text(
        _sample_log(["Ni1", "Ni2", "Ni3", "Ni4"]), encoding="utf-8"
    )
    result = parse_abacus_outputs(tmp_path, source_model=model, stage="scf")
    assert result.occupations == "smearing"


@pytest.mark.parametrize(
    ("missing_field", "error_text"),
    (("smearing_method", "required smearing_method"), ("smearing_sigma", "missing smearing_sigma")),
)
def test_native_smearing_method_and_sigma_are_required(tmp_path, missing_field, error_text):
    model = _ni_model(tmp_path)
    prepare_abacus(
        model,
        tmp_path,
        method=_ni_method(),
        execution=_execution(),
        parameters=_parameters(relax=False),
        stage="scf",
        pseudopotentials={"Ni": "Ni_ONCV_PBE-1.2.upf"},
        element_order=["Ni"],
        kpoints=(9, 9, 9),
    )
    input_path = tmp_path / "INPUT"
    input_path.write_text(
        "\n".join(
            line for line in input_path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith(missing_field)
        ) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "OUT.NiPW"
    output_dir.mkdir()
    (output_dir / "running_scf.log").write_text(
        _sample_log(["Ni1", "Ni2", "Ni3", "Ni4"]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=error_text):
        parse_abacus_outputs(tmp_path, source_model=model, stage="scf")


def test_multielement_fixture_preserves_explicit_element_and_atom_order(tmp_path):
    atoms = Atoms(
        ["O", "Ni", "Ca", "O"],
        positions=[[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3]],
        cell=np.diag([4.0, 5.0, 6.0]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([70, 10, 50, 20], dtype=int))
    write_model_artifacts(
        atoms,
        tmp_path / "multi-model",
        model_id="multi-engineering",
        version="v001",
        fixture=True,
        fixture_purpose="abacus_order_test",
        phase_requested="engineering_fixture",
    )
    model = read_model_artifacts(tmp_path / "multi-model")
    method = AbacusMethod(
        suffix="MultiFixed",
        dft_functional="PBE",
        nspin=1,
        initial_moments_muB_by_element={"Ca": 0.0, "O": 0.0, "Ni": 0.0},
        occupations="fixed",
        smearing_method=None,
        mixing_type="broyden",
        relax_method="cg",
        symmetry=0,
    )
    prepared = prepare_abacus(
        model,
        tmp_path / "multi-task",
        method=method,
        execution=_execution(device="cpu"),
        parameters=_parameters(relax=False, occupations="fixed"),
        stage="scf",
        pseudopotentials={"Ca": "Ca.upf", "O": "O.upf", "Ni": "Ni.upf"},
        element_order=["Ca", "O", "Ni"],
        kpoints=(8, 6, 5),
    )
    task_dir = tmp_path / "multi-task"
    assert prepared.abacus_atom_ids == [50, 70, 20, 10]
    assert prepared.kpoints == (8, 6, 5)
    mapping = json.loads((task_dir / "STRU.atom-map.json").read_text(encoding="utf-8"))
    assert [entry["atom_id"] for entry in mapping["abacus_order"]] == [50, 70, 20, 10]
    assert [entry["element"] for entry in mapping["abacus_order"]] == ["Ca", "O", "O", "Ni"]
    stru = (task_dir / "STRU").read_text(encoding="utf-8")
    assert stru.index("\nCa\n") < stru.index("\nO\n") < stru.index("\nNi\n")
    assert "\nCa\n0\n1\n" in stru
    assert "\nO\n0\n2\n" in stru
    assert "\nNi\n0\n1\n" in stru


def test_method_requires_explicit_moments_and_occupation_sigma_pair(tmp_path):
    model = _ni_model(tmp_path)
    with pytest.raises(ValueError, match="nspin=1"):
        prepare_abacus(
            model,
            tmp_path / "nonzero-spin1",
            method=_ni_method(nspin=1, moment=0.6),
            execution=_execution(),
            parameters=_parameters(relax=False),
            stage="scf",
            pseudopotentials={"Ni": "Ni.upf"},
            element_order=["Ni"],
            kpoints=(9, 9, 9),
        )
    with pytest.raises(ValueError, match="require smearing_sigma_Ry"):
        prepare_abacus(
            model,
            tmp_path / "missing-sigma",
            method=_ni_method(),
            execution=_execution(),
            parameters=AbacusParameters(100.0, 1e-8, 100, 56, None, 0.4),
            stage="scf",
            pseudopotentials={"Ni": "Ni.upf"},
            element_order=["Ni"],
            kpoints=(9, 9, 9),
        )


def test_force_labels_require_complete_atom_map_labels():
    atom_map = {
        "source_atom_ids": [20, 70, 50, 10],
        "abacus_order": [
            {"abacus_index": 0, "atom_id": 50, "element": "Ca", "label": "Ca1"},
            {"abacus_index": 1, "atom_id": 70, "element": "O", "label": "O1"},
            {"abacus_index": 2, "atom_id": 20, "element": "O", "label": "O2"},
            {"abacus_index": 3, "atom_id": 10, "element": "Ni", "label": "Ni1"},
        ],
    }
    lines = [
        "TOTAL-FORCE (eV/Angstrom)",
        "Ca1 1 0 0",
        "O1 2 0 0",
        "O2 3 0 0",
        "Ni1 4 0 0",
        "TOTAL-STRESS (KBAR)",
    ]
    assert _parse_forces(lines, atom_map) == [[3.0, 0.0, 0.0], [2.0, 0.0, 0.0], [1.0, 0.0, 0.0], [4.0, 0.0, 0.0]]


@pytest.mark.parametrize("labels", (["Ni2", "Ni1"], ["N1", "Ni2"]))
def test_force_label_swap_or_element_prefix_is_mapping_error(labels):
    atom_map = {
        "source_atom_ids": [1, 2],
        "abacus_order": [
            {"abacus_index": 0, "atom_id": 1, "element": "Ni", "label": "Ni1"},
            {"abacus_index": 1, "atom_id": 2, "element": "Ni", "label": "Ni2"},
        ],
    }
    lines = ["TOTAL-FORCE (eV/Angstrom)", *(f"{label} 0 0 0" for label in labels), "TOTAL-STRESS (KBAR)"]
    with pytest.raises(ValueError, match="label differs from STRU atom map"):
        _parse_forces(lines, atom_map)


def test_native_iteration_and_magnetization_use_last_ionic_step():
    text = """PW ALGORITHM --------------- ION=   1  ELEC=   1--------------------------------
total magnetism (Bohr mag/cell) = 8.0
PW ALGORITHM --------------- ION=   1  ELEC=   8--------------------------------
total magnetism (Bohr mag/cell) = 7.0
PW ALGORITHM --------------- ION=   2  ELEC=   1--------------------------------
total magnetism (Bohr mag/cell) = 3.0
PW ALGORITHM --------------- ION=   2  ELEC=   3--------------------------------
total magnetism (Bohr mag/cell) = 2.5
"""

    assert _scf_iterations(text) == 3
    assert _parse_total_magnetization(text) == pytest.approx(2.5)


def test_parse_abacus_native_failure_markers():
    assert _convergence_marker(
        "!! convergence has not been achieved @_@", stage="scf"
    ) == (False, None)
    assert _convergence_marker(
        "Ion relaxation is not converged yet (threshold is 0.02 eV/A).", stage="relax"
    ) == (None, False)


def test_convergence_markers_use_last_native_state():
    assert _convergence_marker(
        "charge density convergence is achieved\n!! convergence has not been achieved @_@",
        stage="scf",
    ) == (False, None)
    assert _convergence_marker(
        "Ion relaxation is not converged yet (threshold is 0.02 eV/A).\nRelaxation is converged!",
        stage="relax",
    ) == (None, True)
    assert _convergence_marker("no convergence marker", stage="relax") == (None, None)
