"""Focused fixed-cell ionic-constraint and native-stop contract checks.

The native log fixtures are documented-format software fixtures.  They do not
claim constrained ABACUS dynamics; the saved Ni33 mirror is covered by the
v100 installed acceptance script.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.abacus import (
    AbacusExecution,
    AbacusMethod,
    AbacusParameters,
    parse_abacus_outputs,
    prepare_abacus,
)
from mlcc.modeling import build_nickel_fcc_fixture, write_model_artifacts


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "workspace" / "models" / "ni-fcc-engineering" / "v001"
METHOD = ROOT / "workspace" / "configs" / "h1-abacus-method-v002.json"
STUDY = ROOT / "workspace" / "configs" / "cases" / "ni-engineering-v001.json"


def _method(*, suffix: str = "NiRelax") -> AbacusMethod:
    return AbacusMethod(
        suffix=suffix,
        dft_functional="PBE",
        nspin=1,
        initial_moments_muB_by_element={"Ni": 0.0},
        occupations="fixed",
        smearing_method=None,
        mixing_type="broyden",
        relax_method="cg",
        symmetry=0,
    )


def _parameters() -> AbacusParameters:
    return AbacusParameters(
        ecutwfc_Ry=100.0,
        scf_thr=1e-8,
        scf_nmax=100,
        nbands=56,
        smearing_sigma_Ry=None,
        mixing_beta=0.4,
        force_thr_eV_per_A=0.2,
        relax_nmax=8,
    )


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _multi_model(tmp_path: Path):
    atoms = Atoms(
        ["O", "Ni", "Ca", "O"],
        positions=[[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3]],
        cell=np.diag([4.0, 5.0, 6.0]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([70, 10, 50, 20], dtype=int))
    return write_model_artifacts(
        atoms,
        tmp_path / "model",
        model_id="multi-engineering",
        version="v001",
        fixture=True,
        fixture_purpose="ionic_constraint_contract",
        phase_requested="engineering_fixture",
    )


def test_prepare_normalizes_source_ids_and_emits_grouped_native_flags(tmp_path: Path):
    model = _multi_model(tmp_path)
    constraints = {
        "coordinate_basis": "cartesian",
        "atom_ids": [20, 70, 50, 10],
        "move_flags": [[0, 0, 0], [1, 0, 1], [1, 1, 1], [0, 1, 0]],
    }
    prepare_abacus(
        model,
        tmp_path / "task",
        method=AbacusMethod(
            suffix="MultiRelax",
            dft_functional="PBE",
            nspin=1,
            initial_moments_muB_by_element={"Ca": 0.0, "O": 0.0, "Ni": 0.0},
            occupations="fixed",
            smearing_method=None,
            mixing_type="broyden",
            relax_method="cg",
            symmetry=0,
        ),
        execution=AbacusExecution(device="cpu", ks_solver="cg"),
        parameters=_parameters(),
        stage="relax",
        pseudopotentials={"Ca": "Ca.upf", "O": "O.upf", "Ni": "Ni.upf"},
        element_order=["Ca", "O", "Ni"],
        kpoints=(1, 1, 1),
        ionic_constraints=constraints,
    )
    task = tmp_path / "task"
    method = json.loads((task / "method.json").read_text(encoding="utf-8"))
    assert method["ionic_constraints"] == {
        "schema": "mlcc.ionic-constraints.v1",
        "coordinate_basis": "cartesian",
        "atom_ids": [70, 10, 50, 20],
        "move_flags": [[1, 0, 1], [0, 1, 0], [1, 1, 1], [0, 0, 0]],
        "relax_new": True,
        "origin": "explicit_request",
    }
    assert "relax_new           1" in (task / "INPUT").read_text(encoding="utf-8")
    rows = [line.split() for line in (task / "STRU").read_text(encoding="utf-8").splitlines() if " m " in line]
    assert [row[4:7] for row in rows] == [["1", "1", "1"], ["1", "0", "1"], ["0", "0", "0"], ["0", "1", "0"]]


def test_prepare_legacy_relax_is_all_free_and_records_origin(tmp_path: Path):
    model = build_nickel_fcc_fixture(tmp_path / "model")
    prepare_abacus(
        model,
        tmp_path / "task",
        method=_method(),
        execution=AbacusExecution(device="cpu", ks_solver="cg"),
        parameters=_parameters(),
        stage="relax",
        pseudopotentials={"Ni": "Ni.upf"},
        element_order=["Ni"],
        kpoints=(1, 1, 1),
    )
    constraints = json.loads((tmp_path / "task" / "method.json").read_text(encoding="utf-8"))["ionic_constraints"]
    assert constraints["origin"] == "legacy_all_free"
    assert constraints["move_flags"] == [[1, 1, 1]] * 4


def test_prepare_rejects_partial_flags_on_skew_cell_and_all_frozen(tmp_path: Path):
    atoms = Atoms(["Ni"], positions=[[0, 0, 0]], cell=[[3.0, 0.2, 0], [0, 3.0, 0], [0, 0, 3.0]], pbc=True)
    atoms.new_array("atom_id", np.asarray([0], dtype=int))
    model = write_model_artifacts(
        atoms,
        tmp_path / "skew-model",
        model_id="skew",
        version="v001",
        fixture=True,
        fixture_purpose="ionic_constraint_contract",
        phase_requested="engineering_fixture",
    )
    common = dict(
        method=_method(),
        execution=AbacusExecution(device="cpu", ks_solver="cg"),
        parameters=_parameters(),
        stage="relax",
        pseudopotentials={"Ni": "Ni.upf"},
        element_order=["Ni"],
        kpoints=(1, 1, 1),
    )
    with pytest.raises(ValueError, match="positive diagonal"):
        prepare_abacus(model, tmp_path / "partial", ionic_constraints={"coordinate_basis": "cartesian", "atom_ids": [0], "move_flags": [[1, 0, 1]]}, **common)
    with pytest.raises(ValueError, match="at least one movable"):
        prepare_abacus(model, tmp_path / "frozen", ionic_constraints={"coordinate_basis": "cartesian", "atom_ids": [0], "move_flags": [[0, 0, 0]]}, **common)


@pytest.mark.parametrize("bad_id", [0.1, True, "0"])
def test_prepare_rejects_non_integer_source_atom_ids(tmp_path: Path, bad_id):
    model = build_nickel_fcc_fixture(tmp_path / "model")
    constraints = {
        "coordinate_basis": "cartesian",
        "atom_ids": [bad_id, 1, 2, 3],
        "move_flags": [[1, 1, 1]] * 4,
    }
    with pytest.raises(ValueError, match="atom_ids must contain integers"):
        prepare_abacus(
            model,
            tmp_path / "task",
            method=_method(),
            execution=AbacusExecution(device="cpu", ks_solver="cg"),
            parameters=_parameters(),
            stage="relax",
            pseudopotentials={"Ni": "Ni.upf"},
            element_order=["Ni"],
            kpoints=(1, 1, 1),
            ionic_constraints=constraints,
        )


def test_prepare_rejects_ionic_constraints_for_scf(tmp_path: Path):
    model = build_nickel_fcc_fixture(tmp_path / "model")
    parameters = _parameters()
    parameters = AbacusParameters(100.0, 1e-8, 100, 56, None, 0.4)
    with pytest.raises(ValueError, match="only for fixed-cell relax"):
        prepare_abacus(
            model,
            tmp_path / "task",
            method=_method(),
            execution=AbacusExecution(device="cpu", ks_solver="cg"),
            parameters=parameters,
            stage="scf",
            pseudopotentials={"Ni": "Ni.upf"},
            element_order=["Ni"],
            kpoints=(1, 1, 1),
            ionic_constraints={"coordinate_basis": "cartesian", "atom_ids": [0, 1, 2, 3], "move_flags": [[1, 1, 1]] * 4},
        )


def _native_fixture(tmp_path: Path):
    model = build_nickel_fcc_fixture(tmp_path / "model")
    task = tmp_path / "task"
    constraints = {"coordinate_basis": "cartesian", "atom_ids": [0, 1, 2, 3], "move_flags": [[0, 0, 0], [1, 1, 1], [1, 1, 1], [1, 1, 1]]}
    prepare_abacus(
        model,
        task,
        method=_method(),
        execution=AbacusExecution(device="cpu", ks_solver="cg"),
        parameters=_parameters(),
        stage="relax",
        pseudopotentials={"Ni": "Ni.upf"},
        element_order=["Ni"],
        kpoints=(1, 1, 1),
        ionic_constraints=constraints,
    )
    output = task / "OUT.NiRelax"
    output.mkdir()
    # Treat the output INPUT as ABACUS's native echoed runtime controls.  The
    # task INPUT alone is only a request and must not establish promotion.
    (output / "INPUT").write_text((task / "INPUT").read_text(encoding="utf-8"), encoding="utf-8")
    force_rows = "\n".join(
        [
            "Ni1 100.0 0.0 0.0",
            "Ni2 0.1 0.0 0.0",
            "Ni3 0.0 0.0 0.0",
            "Ni4 0.0 0.0 0.0",
        ]
    )
    log = f"""PW ALGORITHM --------------- ION=   1  ELEC=   1--------------------------------
charge density convergence is achieved
PW ALGORITHM --------------- ION=   2  ELEC=   1--------------------------------
charge density convergence is achieved
Relaxation is converged!
 TOTAL-FORCE (eV/Angstrom)
{force_rows}
 TOTAL-STRESS (KBAR):
 0 0 0
 0 0 0
 0 0 0
 !FINAL_ETOT_IS -1.0 eV
Finish Time  : Thu Jan 01 00:00:00 1970
Total  Time  : 0 h 0 mins 1 secs
"""
    (output / "running_relax.log").write_text(log, encoding="utf-8")
    stru = (task / "STRU").read_text(encoding="utf-8")
    (output / "STRU_ION_D").write_text(stru, encoding="utf-8")
    (output / "STRU_ION2_D").write_text(stru, encoding="utf-8")
    return model, task


def test_parse_relaxation_uses_free_component_metric_and_binds_final_geometry(tmp_path: Path):
    model, task = _native_fixture(tmp_path)
    result = parse_abacus_outputs(task, source_model=model, stage="relax")
    relaxation = result.relaxation
    assert relaxation is not None
    assert relaxation["max_free_force_component_eV_per_A"] == pytest.approx(0.1)
    assert relaxation["max_all_force_component_eV_per_A"] == pytest.approx(100.0)
    assert relaxation["force_metric"] == "max_abs_movable_cartesian_component"
    assert relaxation["ionic_steps"] == 2
    assert relaxation["native_completed"] is True
    assert relaxation["final_geometry_matches_last_evaluation"] is True
    assert relaxation["geometry_promotable"] is True


def test_parse_relaxation_does_not_promote_unevaluated_final_geometry(tmp_path: Path):
    model, task = _native_fixture(tmp_path)
    log = task / "OUT.NiRelax" / "running_relax.log"
    log.write_text(log.read_text(encoding="utf-8").replace("Relaxation is converged!", "Relaxation is not converged yet (threshold is 0.2 eV/A)."), encoding="utf-8")
    result = parse_abacus_outputs(task, source_model=model, stage="relax")
    relaxation = result.relaxation
    assert relaxation is not None
    assert relaxation["ionic_converged"] is False
    assert relaxation["final_geometry_matches_last_evaluation"] is False
    assert relaxation["final_geometry_role"] == "unevaluated_proposed_next_geometry"
    assert relaxation["geometry_promotable"] is False


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("force_thr_ev        0.2", "force_thr_ev        0.3", "native force threshold"),
        ("relax_nmax          8", "relax_nmax          9", "native relax_nmax"),
    ],
)
def test_parse_rejects_native_relax_control_mismatch(
    tmp_path: Path, old: str, new: str, message: str
):
    model, task = _native_fixture(tmp_path)
    native_input = task / "OUT.NiRelax" / "INPUT"
    native_input.write_text(native_input.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        parse_abacus_outputs(task, source_model=model, stage="relax")


def test_parse_records_ionic_iteration_limit_without_promoting(tmp_path: Path):
    model, task = _native_fixture(tmp_path)
    log_path = task / "OUT.NiRelax" / "running_relax.log"
    log = log_path.read_text(encoding="utf-8")
    extra_steps = "\n".join(
        f"PW ALGORITHM --------------- ION=   {step}  ELEC=   1--------------------------------"
        for step in range(3, 9)
    )
    log = log.replace("Relaxation is converged!", extra_steps + "\nRelaxation is not converged yet (threshold is 0.2 eV/A).")
    log_path.write_text(log, encoding="utf-8")
    result = parse_abacus_outputs(task, source_model=model, stage="relax")
    assert result.relaxation is not None
    assert result.relaxation["ionic_steps"] == 8
    assert result.relaxation["native_stop_reason"] == "ionic_iteration_limit"
    assert result.relaxation["final_geometry_role"] == "unevaluated_proposed_next_geometry"
    assert result.relaxation["geometry_promotable"] is False


def test_parse_electronic_failure_blocks_ionic_promotion(tmp_path: Path):
    model, task = _native_fixture(tmp_path)
    log_path = task / "OUT.NiRelax" / "running_relax.log"
    log_path.write_text(
        log_path.read_text(encoding="utf-8").replace(
            "charge density convergence is achieved", "!! convergence has not been achieved @_@"
        ),
        encoding="utf-8",
    )
    result = parse_abacus_outputs(task, source_model=model, stage="relax")
    assert result.relaxation is not None
    assert result.relaxation["electronic_converged"] is False
    assert result.relaxation["ionic_converged"] is True
    assert result.relaxation["native_stop_reason"] == "electronic_not_converged"
    assert result.relaxation["geometry_promotable"] is False


def test_parse_without_native_echo_controls_cannot_promote(tmp_path: Path):
    model, task = _native_fixture(tmp_path)
    (task / "OUT.NiRelax" / "INPUT").unlink()
    result = parse_abacus_outputs(task, source_model=model, stage="relax")
    assert result.relaxation is not None
    assert result.relaxation["native_marker_text"]["native_controls_bound"] is False
    assert result.relaxation["relax_new"] is None
    assert result.relaxation["relax_nmax"] is None
    assert result.relaxation["native_force_threshold_eV_per_A"] is None
    assert result.relaxation["geometry_promotable"] is False


def test_parse_rejects_partial_skew_flags_without_saved_method_constraints(tmp_path: Path):
    atoms = Atoms(["Ni"], positions=[[0.0, 0.0, 0.0]], cell=[[3.0, 0.2, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]], pbc=True)
    atoms.new_array("atom_id", np.asarray([0], dtype=int))
    model = write_model_artifacts(
        atoms,
        tmp_path / "model",
        model_id="skew-parser",
        version="v001",
        fixture=True,
        fixture_purpose="ionic_constraint_contract",
        phase_requested="engineering_fixture",
    )
    task = tmp_path / "task"
    prepare_abacus(
        model,
        task,
        method=_method(),
        execution=AbacusExecution(device="cpu", ks_solver="cg"),
        parameters=_parameters(),
        stage="relax",
        pseudopotentials={"Ni": "Ni.upf"},
        element_order=["Ni"],
        kpoints=(1, 1, 1),
    )
    method = json.loads((task / "method.json").read_text(encoding="utf-8"))
    method.pop("ionic_constraints", None)
    _write_json(task / "method.json", method)
    stru = (task / "STRU").read_text(encoding="utf-8")
    stru = stru.replace("3 0.0 0.0", "3 0.2 0.0", 1).replace(" m 1 1 1", " m 1 0 1", 1)
    (task / "STRU").write_text(stru, encoding="utf-8")
    output = task / "OUT.NiRelax"
    output.mkdir()
    (output / "INPUT").write_text((task / "INPUT").read_text(encoding="utf-8"), encoding="utf-8")
    (output / "STRU_ION_D").write_text(stru, encoding="utf-8")
    (output / "STRU_ION1_D").write_text(stru, encoding="utf-8")
    (output / "running_relax.log").write_text(
        """PW ALGORITHM --------------- ION=   1  ELEC=   1--------------------------------
charge density convergence is achieved
Relaxation is converged!
 TOTAL-FORCE (eV/Angstrom)
Ni1 0.0 0.0 0.0
 TOTAL-STRESS (KBAR):
 0 0 0
 0 0 0
 0 0 0
 !FINAL_ETOT_IS -1.0 eV
Finish Time  : Thu Jan 01 00:00:00 1970
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="positive diagonal"):
        parse_abacus_outputs(task, source_model=model, stage="relax")


def test_public_relax_requires_explicit_constraints_and_scf_rejects_them(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / "tasks").mkdir(parents=True)
    method = json.loads(METHOD.read_text(encoding="utf-8"))
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    site = {
        "workspace": {"local": str(workspace)},
        "abacus": {
            "binary": "/opt/abacus",
            "mpi_launcher": "/opt/mpiexec.hydra",
            "environment_script": "/tmp/abacus-env.sh",
            "pseudopotential_files": {"Ni_ONCV_PBE_1.2_18e": "/authorized/Ni.upf"},
        },
    }
    request = {
        "task_id": "relax-contract",
        "calculation": "relax",
        "input_transformation": None,
        "required_results": [],
        "resource_request": {"nodes": 1, "partition": "cpu", "ntasks": 1, "cpus_per_task": 1, "mem_mib": 2048, "time": 0},
    }
    paths = {name: tmp_path / f"{name}.json" for name in ("method", "study", "site", "request")}
    _write_json(paths["method"], method)
    _write_json(paths["study"], study)
    _write_json(paths["site"], site)
    _write_json(paths["request"], request)
    from mlcc.abacus_tasks import create_abacus_task

    with pytest.raises(ValueError, match="explicit ionic_constraints"):
        create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"], site_path=paths["site"], request_path=paths["request"])
    request["ionic_constraints"] = {"coordinate_basis": "cartesian", "atom_ids": [0, 1, 2, 3], "move_flags": [[1, 1, 1]] * 4}
    _write_json(paths["request"], request)
    data = create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"], site_path=paths["site"], request_path=paths["request"])
    assert data["ionic_constraints"]["origin"] == "explicit_request"
    assert data["calculation"] == "relax"
    request["task_id"] = "scf-with-constraints"
    request["calculation"] = "scf"
    _write_json(paths["request"], request)
    with pytest.raises(ValueError, match="SCF requests must not define ionic_constraints"):
        create_abacus_task(model_path=MODEL, method_path=paths["method"], study_path=paths["study"], site_path=paths["site"], request_path=paths["request"])
