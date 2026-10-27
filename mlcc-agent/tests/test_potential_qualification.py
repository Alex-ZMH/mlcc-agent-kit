from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import json
import shutil

import numpy as np
import pytest
from ase import Atoms

import mlcc.potential_qualification as pq


def _atoms() -> Atoms:
    atoms = Atoms(
        symbols=["Ni", "Ni"],
        positions=[[0.0, 0.0, 0.0], [1.76, 1.76, 0.0]],
        cell=np.diag([3.52, 3.52, 3.52]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([0, 1], dtype=int))
    return atoms


def _method() -> dict:
    return {
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "stage": "scf",
        "dft_functional": "PBE",
        "basis_type": "pw",
        "ks_solver": "cg",
        "nspin": 1,
        "initial_moments_muB_by_element": {"Ni": 0.0},
        "occupations": "fixed",
        "smearing_method": None,
        "mixing_type": "broyden",
        "relax_method": "cg",
        "symmetry": 0,
        "element_order": ["Ni"],
        "kpoints": [2, 2, 2],
        "kpoint_rule": "explicit_mesh",
        "parameters": {"ecutwfc_Ry": 100, "scf_thr": 1e-4, "scf_nmax": 100, "nbands": 8, "smearing_sigma_Ry": None},
        "pseudopotentials": {"Ni": {"filename": "Ni.upf", "source": "/site/Ni.upf"}},
        "pseudopotential_ids": {"Ni": "Ni-test"},
        "pseudopotential_metadata": {"Ni": {"element": "Ni"}},
        "stress_convention": {"sign": "abacus_printed"},
        "execution": {"device": "gpu", "ks_solver": "cg"},
        "method_set": "abacus-test-v001",
    }


def _pair_data(pair_id: str, abacus_energy: float, lammps_energy: float) -> tuple[dict, dict]:
    atoms = _atoms()
    stress = np.diag([1.0, 2.0, 3.0])
    force = np.asarray([[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]])
    abacus = {
        "directory": pair_id + ":abacus",
        "task": {"task_id": pair_id + "-a", "scheduler_job_id": "unit-only"},
        "method": _method(),
        "parsed": SimpleNamespace(
            atom_ids=[0, 1],
            final_atoms=atoms,
            energy_eV=abacus_energy,
            forces_eV_per_A=force.tolist(),
            stress_GPa=stress.tolist(),
            electronic_converged=True,
            source_files={},
        ),
        "atoms": atoms,
    }
    potential = {
        "potential_id": "Ni-test",
        "version": "v001",
        "elements": ["Ni"],
        "element_order": ["Ni"],
        "units": "metal",
        "atom_style": "atomic",
        "pair_style": "eam",
        "pair_coeff": ["* * Ni.eam"],
        "files": [{"filename": "Ni.eam", "local_path": "/task/Ni.eam"}],
        "fixture": True,
        "production_qualification": False,
    }
    protocol = {"kind": "run0", "static_tensor": True}
    lammps = {
        "static_tensor_declared": True,
        "directory": pair_id + ":lammps",
        "task": {"task_id": pair_id + "-l", "method_set": "lammps-Ni-test-v001", "scheduler_job_id": "unit-only"},
        "method": {"potential": potential, "protocol": protocol},
        "parsed": {
            "source_files": {},
            "engine": "lammps",
            "model_id": "fixture",
            "version": "v001",
            "protocol": protocol,
            "energy_eV": lammps_energy,
            "forces_eV_per_A": force.tolist(),
            "atom_ids": [0, 1],
            "elements": ["Ni", "Ni"],
            "positions_angstrom": atoms.positions.tolist(),
            "cell_angstrom": atoms.cell.array.tolist(),
            "pressure_tensor_GPa": (-stress).tolist(),
            "stress_GPa": stress.tolist(),
            "stress_unit": "GPa",
            "stress_sign": "tension_positive",
            "tensor_basis": "source_cartesian",
        },
        "atom_ids": [0, 1],
        "elements": ["Ni", "Ni"],
        "positions": atoms.positions.copy(),
        "cell": atoms.cell.array.copy(),
    }
    abacus["native_binding"] = {"passed": True, "identity": {"physics": {"ecutwfc": "100"}, "kpt": {"grid": [2, 2, 2], "offset": [0, 0, 0]}, "pseudopotential_files": ["Ni.upf"]}}
    return abacus, lammps


def test_stress_mapping_requires_explicit_calibration_evidence(tmp_path):
    factor, target, missing = pq._stress_mapping(None)
    assert factor is None
    assert target is None
    assert "abacus_stress_sign_calibration_missing" in missing

    evidence = tmp_path / "calibration.txt"
    evidence.write_text("Unit input only: calibration not validated")
    factor, target, missing = pq._stress_mapping(
        {"factor_to_tension_positive": 1.0, "evidence_path": str(evidence)},
    )
    assert factor == 1.0
    assert target == "tension_positive"
    assert missing == ["abacus_stress_calibration_not_validated"]


def test_stress_matrix_does_not_fill_missing_lammps_tensor():
    matrix, missing = pq._stress_matrix(
        {"stress_GPa": np.eye(3).tolist(), "stress_unit": "GPa", "stress_sign": "tension_positive"},
        engine="lammps",
    )
    assert matrix is not None
    assert "lammps_pressure_tensor_GPa_missing" in missing
    assert "lammps_stress_frame_not_source_cartesian" in missing


def test_compare_uses_relative_per_atom_energies_and_keeps_production_false(monkeypatch, tmp_path):
    first_a, first_l = _pair_data("reference", -10.0, -2.0)
    second_a, second_l = _pair_data("strained", -9.5, -1.75)
    by_path = {"reference-a": first_a, "reference-l": first_l, "strained-a": second_a, "strained-l": second_l}
    monkeypatch.setattr(pq, "_read_abacus_task", lambda path: by_path[str(path) + "-a"])
    monkeypatch.setattr(pq, "_read_lammps_task", lambda path: by_path[str(path) + "-l"])

    evidence = tmp_path / "evidence.txt"
    evidence.write_text("Unit comparison input; not scientific evidence")
    report = pq.compare_potential_tasks(
        [
            {"pair_id": "reference", "abacus_task": "reference", "lammps_task": "reference"},
            {"pair_id": "strained", "abacus_task": "strained", "lammps_task": "strained"},
        ],
        "reference",
        {"energy_eV_per_atom": 1e-12, "force_component_eV_per_A": 1e-12, "stress_component_GPa": 1e-12, "geometry_A": 1e-12},
        abacus_stress_mapping={"factor_to_tension_positive": 1.0, "evidence_path": str(evidence)},
    )
    second = next(item for item in report["pairs"] if item["pair_id"] == "strained")
    assert second["relative_energy"]["abacus_eV_per_atom"] == pytest.approx(0.25)
    assert second["relative_energy"]["lammps_eV_per_atom"] == pytest.approx(0.125)
    assert second["relative_energy"]["abs_error_eV_per_atom"] == pytest.approx(0.125)
    assert report["production_qualification"] is False
    assert report["potential_qualification"] is False


def test_compare_rejects_missing_reference_or_threshold():
    with pytest.raises(ValueError, match="reference_pair_id"):
        pq.compare_potential_tasks(
            [{"pair_id": name, "abacus_task": "a", "lammps_task": "l"} for name in ("one", "two")],
            "missing",
            {"energy_eV_per_atom": 1, "force_component_eV_per_A": 1, "stress_component_GPa": 1, "geometry_A": 1},
        )
    with pytest.raises(ValueError, match="energy_eV_per_atom"):
        pq.compare_potential_tasks(
            [{"pair_id": "one", "abacus_task": "a", "lammps_task": "l"}],
            "one",
            {"force_component_eV_per_A": 1, "stress_component_GPa": 1},
        )


def _compare_units(monkeypatch, first, second):
    data = {"first": first, "second": second}
    monkeypatch.setattr(pq, "_read_abacus_task", lambda name: data[name][0])
    monkeypatch.setattr(pq, "_read_lammps_task", lambda name: data[name][1])
    return pq.compare_potential_tasks(
        [{"pair_id": name, "abacus_task": name, "lammps_task": name} for name in data],
        "first", {"energy_eV_per_atom": .01, "force_component_eV_per_A": .01,
                  "stress_component_GPa": .01, "geometry_A": 1e-8})


@pytest.mark.parametrize("change", ["geometry", "ids", "composition", "method", "potential"])
def test_incomparable_pairs_never_pass(monkeypatch, change):
    first = _pair_data("first", -1000, -2)
    second = _pair_data("second", -999.5, -1.5)
    if change == "geometry":
        second[1]["positions"][0, 0] += .1
    elif change == "ids":
        second[1]["atom_ids"] = [1, 0]
    elif change == "composition":
        second[0]["atoms"].set_chemical_symbols(["Ni", "O"])
        second[1]["elements"] = ["Ni", "O"]
    elif change == "method":
        second[0]["method"]["parameters"]["ecutwfc_Ry"] = 120
    else:
        second[1]["method"]["potential"]["version"] = "v002"
    report = _compare_units(monkeypatch, first, second)
    assert report["measured_comparison_pass"] is False
    assert report["pairs"][1]["relative_energy"]["abs_error_eV_per_atom"] is None
    if change in ("geometry", "ids"):
        assert report["pairs"][1]["force"]["delta_eV_per_A"] is None
        assert report["pairs"][1]["stress"]["delta_GPa"] is None


def test_real_abacus_reader_binds_stru_and_preserves_saved_evidence(tmp_path):
    root = Path(__file__).resolve().parents[2]
    original = root / "workspace/tasks/h1-ni-scf-v003"
    copied = tmp_path / "job37"
    shutil.copytree(original, copied)
    task_path = copied / "task.json"
    task = json.loads(task_path.read_text())
    task["model_path"] = str(root / "workspace/models/ni-fcc-engineering/v001")
    task_path.write_text(json.dumps(task))
    before = {str(path.relative_to(copied)): path.read_bytes() for path in copied.rglob("*") if path.is_file()}
    result = pq._read_abacus_task(copied)
    assert result["parsed"].energy_eV == pytest.approx(-16778.90745945708)
    assert result["native_binding"]["checks"]["stru_geometry"] is True
    assert result["native_binding"]["checks"]["neutral_charge"] is True
    assert result["native_binding"]["identity"]["charge_contract"]["model_charge_state"] == 0
    assert result["native_binding"]["checks"]["input_smearing_sigma"] is True
    after = {str(path.relative_to(copied)): path.read_bytes() for path in copied.rglob("*") if path.is_file()}
    assert before == after
    text = (copied / "STRU").read_text()
    # Perturb the actual lattice scale while leaving input.extxyz unchanged.
    lines = text.splitlines()
    index = lines.index("LATTICE_CONSTANT") + 1
    lines[index] = str(float(lines[index]) * 1.01)
    (copied / "STRU").write_text("\n".join(lines) + "\n")
    altered = pq._read_abacus_task(copied)
    assert altered["native_binding"]["checks"]["stru_geometry"] is False


@pytest.mark.parametrize(
    "source",
    ["task", "method", "task_nelec", "method_nelec_delta", "model_derivation", "model_top_level"],
)
def test_abacus_neutral_charge_contract_rejects_non_neutral_source(tmp_path, source):
    (tmp_path / "INPUT").write_text("INPUT_PARAMETERS\n", encoding="utf-8")
    task = {"net_charge": 1} if source == "task" else {}
    task.update({"nelec": 1} if source == "task_nelec" else {})
    method = {"net_charge": 1} if source == "method" else {}
    method.update({"nelec_delta": 1} if source == "method_nelec_delta" else {})
    metadata = {"derivation": {"charge_state": 1}} if source == "model_derivation" else {}
    metadata.update({"charge_state": 1} if source == "model_top_level" else {})

    with pytest.raises(ValueError, match="must be neutral"):
        pq._abacus_neutral_charge_contract(tmp_path, task, method, metadata)


@pytest.mark.parametrize("key", ["nelec", "nelec_delta", "gate_flag"])
def test_abacus_neutral_charge_contract_rejects_native_input_override(tmp_path, key):
    (tmp_path / "INPUT").write_text(f"INPUT_PARAMETERS\n{key} 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match=f"native INPUT {key} must be"):
        pq._abacus_neutral_charge_contract(tmp_path, {}, {}, {})


def test_abacus_neutral_charge_contract_accepts_false_gate_flag(tmp_path):
    (tmp_path / "INPUT").write_text("INPUT_PARAMETERS\ngate_flag false\n", encoding="utf-8")

    result = pq._abacus_neutral_charge_contract(tmp_path, {}, {}, {})

    assert result["native_gate_flag"] == "false"


def test_abacus_neutral_charge_reader_rejects_charged_task_with_neutral_native_log(tmp_path):
    root = Path(__file__).resolve().parents[2]
    copied = tmp_path / "charged-label-negative-only"
    shutil.copytree(root / "workspace/tasks/h1-ni-scf-v003", copied)
    task_path = copied / "task.json"
    task = json.loads(task_path.read_text())
    task["model_path"] = str(root / "workspace/models/ni-fcc-engineering/v001")
    task["net_charge"] = 2
    task_path.write_text(json.dumps(task))
    with pytest.raises(ValueError, match="task.net_charge must be neutral"):
        pq._read_abacus_task(copied)


def _patched_lammps_contract(protocol, *, fixture):
    task = {
        "engine": "lammps",
        "calculation": "run0",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "fixture": fixture,
        "production_label": False,
        "model_id": "Ni-model",
        "model_version": "v001",
        "protocol": protocol,
    }
    method = {
        "protocol": protocol,
        "potential": {"production_qualification": False},
    }
    parsed = {
        "engine": "lammps",
        "model_id": "Ni-model",
        "version": "v001",
        "protocol": protocol,
        "energy_eV": -1.0,
        "forces_eV_per_A": [[0.0, 0.0, 0.0]],
        "atom_ids": [0],
        "elements": ["Ni"],
        "cell_angstrom": np.eye(3).tolist(),
        "positions_angstrom": [[0.0, 0.0, 0.0]],
        "source_files": {},
    }
    return task, method, parsed


def test_qualification_purpose_accepts_nonfixture_readonly_contract(monkeypatch, tmp_path):
    protocol = {
        "kind": "run0",
        "static_tensor": True,
        "purpose": "potential_qualification",
        "experiment_scope": "Ni static potential pair",
    }
    task, method, parsed = _patched_lammps_contract(protocol, fixture=False)
    monkeypatch.setattr(pq, "_task_dir", lambda value: tmp_path)
    monkeypatch.setattr(pq, "_json", lambda path: task if Path(path).name == "task.json" else method)
    monkeypatch.setattr(pq, "read_lammps_task", lambda path: parsed)

    result = pq._read_lammps_task(tmp_path)

    assert result["static_tensor_declared"] is True
    assert result["task"]["fixture"] is False
    assert result["parsed"] is parsed


def test_qualification_purpose_rejects_ordinary_nonfixture(monkeypatch, tmp_path):
    protocol = {"kind": "run0", "static_tensor": True}
    task, method, _ = _patched_lammps_contract(protocol, fixture=False)
    monkeypatch.setattr(pq, "_task_dir", lambda value: tmp_path)
    monkeypatch.setattr(pq, "_json", lambda path: task if Path(path).name == "task.json" else method)

    with pytest.raises(ValueError, match="non-fixture LAMMPS comparison requires purpose=potential_qualification"):
        pq._read_lammps_task(tmp_path)


def test_qualification_purpose_preserves_legacy_fixture_missing_tensor(monkeypatch, tmp_path):
    task, method, parsed = _patched_lammps_contract({"kind": "run0"}, fixture=True)
    monkeypatch.setattr(pq, "_task_dir", lambda value: tmp_path)
    monkeypatch.setattr(pq, "_json", lambda path: task if Path(path).name == "task.json" else method)
    monkeypatch.setattr(pq, "read_lammps_task", lambda path: parsed)
    result = pq._read_lammps_task(tmp_path)
    assert result["static_tensor_declared"] is False
    assert "stress_GPa" not in result["parsed"]


def test_native_binding_gate_keeps_raw_observables_without_force_stress_delta(monkeypatch, tmp_path):
    first = _pair_data("first", -100.0, -10.0)
    second = _pair_data("second", -99.5, -9.75)
    first[0]["native_binding"]["passed"] = False
    second[0]["native_binding"]["passed"] = False
    data = {"first": first, "second": second}
    monkeypatch.setattr(pq, "_read_abacus_task", lambda name: data[name][0])
    monkeypatch.setattr(pq, "_read_lammps_task", lambda name: data[name][1])
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("Unit comparison input; not scientific evidence")

    report = pq.compare_potential_tasks(
        [{"pair_id": name, "abacus_task": name, "lammps_task": name} for name in data],
        "first",
        {
            "energy_eV_per_atom": 1.0,
            "force_component_eV_per_A": 1.0,
            "stress_component_GPa": 1.0,
            "geometry_A": 1e-8,
        },
        abacus_stress_mapping={"factor_to_tension_positive": 1.0, "evidence_path": str(evidence)},
    )

    for index, pair in enumerate(report["pairs"]):
        expected_abacus, expected_lammps = data[("first", "second")[index]]
        assert pair["force"]["raw_abacus_eV_per_A"] == expected_abacus["parsed"].forces_eV_per_A
        assert pair["force"]["raw_lammps_eV_per_A"] == expected_lammps["parsed"]["forces_eV_per_A"]
        assert pair["force"]["delta_eV_per_A"] is None
        assert pair["force"]["passed"] is False
        assert pair["stress"]["raw_abacus_stress_GPa"] == expected_abacus["parsed"].stress_GPa
        assert pair["stress"]["raw_lammps_stress_GPa"] == expected_lammps["parsed"]["stress_GPa"]
        assert pair["stress"]["delta_GPa"] is None
        assert pair["stress"]["passed"] is False

