from __future__ import annotations

import json
from pathlib import Path

import pytest

import mlcc.abacus_tasks as abacus_tasks
from mlcc.abacus import (
    AbacusExecution,
    AbacusMethod,
    AbacusParameters,
    prepare_abacus,
)
from mlcc.modeling import build_nickel_fcc_fixture


def _method(*, suffix: str = "NiPot", nspin: int = 1) -> AbacusMethod:
    return AbacusMethod(
        suffix=suffix,
        dft_functional="PBE",
        nspin=nspin,
        initial_moments_muB_by_element={"Ni": 0.0 if nspin == 1 else 0.6},
        occupations="fixed" if nspin == 1 else "smearing",
        smearing_method=None if nspin == 1 else "gauss",
        mixing_type="broyden",
        relax_method="cg",
        symmetry=0,
    )


def _parameters(*, relax: bool = False, nspin: int = 1) -> AbacusParameters:
    return AbacusParameters(
        ecutwfc_Ry=100.0,
        scf_thr=1.0e-8,
        scf_nmax=100,
        nbands=56,
        smearing_sigma_Ry=None if nspin == 1 else 0.007,
        mixing_beta=0.3,
        force_thr_eV_per_A=0.02 if relax else None,
        relax_nmax=40 if relax else None,
    )


def _nc_qualification(*, passed: bool = True) -> dict:
    return {
        "input_qualified": passed,
        "scientific_qualification": False,
        "production_qualification": False,
        "checks": {"norm_conserving": {"passed": passed}},
    }


def _prepare_kwargs(model, output_dir: Path, *, relax: bool = False, qualification=None) -> dict:
    return {
        "model": model,
        "output_dir": output_dir,
        "method": _method(nspin=1),
        "execution": AbacusExecution(device="cpu", ks_solver="cg"),
        "parameters": _parameters(relax=relax, nspin=1),
        "stage": "relax" if relax else "scf",
        "pseudopotentials": {"Ni": "Ni_ONCV_PBE-1.2.upf"},
        "element_order": ["Ni"],
        "kpoints": (2, 2, 2),
        "input_qualification": qualification,
    }


def test_prepare_electrostatic_output_writes_controls_and_artifact(tmp_path: Path) -> None:
    model = build_nickel_fcc_fixture(tmp_path / "model")
    prepare_abacus(
        **_prepare_kwargs(model, tmp_path / "task", qualification=_nc_qualification()),
        output_control={"out_pot": 2},
    )
    input_text = (tmp_path / "task" / "INPUT").read_text(encoding="utf-8")
    for line in (
        "out_pot              2",
        "out_interval         1",
        "efield_flag          0",
        "dip_cor_flag         0",
        "gate_flag            0",
        "imp_sol              0",
        "use_paw              0",
        "vl_in_h              1",
        "vion_in_h            1",
        "vh_in_h              1",
    ):
        assert line in input_text
    method = json.loads((tmp_path / "task" / "method.json").read_text(encoding="utf-8"))
    artifact = method["requested_artifacts"]["electrostatic_potential"]
    assert method["output_control"] == {"out_pot": 2}
    assert artifact == {
        "schema": "mlcc.abacus-electrostatic-output.v1",
        "relative_path": "OUT.NiPot/ElecStaticPot.cube",
        "kind": "local_ionic_plus_hartree",
        "value_unit": "Ry",
        "geometry_unit": "Bohr",
        "native_output_observed": False,
        "native_GPU_accepted": False,
    }


def test_prepare_without_output_request_keeps_input_and_method_unmodified(tmp_path: Path) -> None:
    model = build_nickel_fcc_fixture(tmp_path / "model")
    prepare_abacus(**_prepare_kwargs(model, tmp_path / "plain", qualification=None))
    input_text = (tmp_path / "plain" / "INPUT").read_text(encoding="utf-8")
    method = json.loads((tmp_path / "plain" / "method.json").read_text(encoding="utf-8"))
    assert "out_pot" not in input_text
    assert "output_control" not in method
    assert "requested_artifacts" not in method


@pytest.mark.parametrize("value", [True, 1, 3, "2"])
def test_prepare_rejects_unsupported_out_pot_values(tmp_path: Path, value) -> None:
    model = build_nickel_fcc_fixture(tmp_path / f"model-{str(value).replace('/', '_')}")
    with pytest.raises(ValueError, match="out_pot"):
        prepare_abacus(
            **_prepare_kwargs(model, tmp_path / "bad", qualification=_nc_qualification()),
            output_control={"out_pot": value},
        )


def test_prepare_rejects_relax_and_non_nc_requests(tmp_path: Path) -> None:
    model = build_nickel_fcc_fixture(tmp_path / "model")
    with pytest.raises(ValueError, match="fixed-cell SCF"):
        prepare_abacus(
            **_prepare_kwargs(model, tmp_path / "relax", relax=True, qualification=_nc_qualification()),
            output_control={"out_pot": 2},
        )
    with pytest.raises(ValueError, match="NC input qualification"):
        prepare_abacus(
            **_prepare_kwargs(model, tmp_path / "uspp", qualification=_nc_qualification(passed=False)),
            output_control={"out_pot": 2},
        )


def _create_case(tmp_path: Path) -> dict[str, Path]:
    model = build_nickel_fcc_fixture(tmp_path / "model")
    workspace = tmp_path / "workspace"
    (workspace / "tasks").mkdir(parents=True)
    method = {
        "method_set": "ni-output-v001",
        "parent_method_set": "ni-output-parent-v001",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "basis_type": "pw",
        "science": {
            "suffix": "NiPot",
            "dft_functional": "PBE",
            "nspin": 1,
            "initial_moments_muB_by_element": {"Ni": 0.0},
            "occupations": "fixed",
            "smearing_method": None,
            "mixing_type": "broyden",
            "relax_method": "cg",
            "symmetry": 0,
            "lspinorb": False,
            "noncolin": False,
        },
        "execution": {"device": "cpu", "ks_solver": "cg"},
        "parameters": {
            "ecutwfc_Ry": 100.0,
            "scf_thr": 1.0e-8,
            "scf_nmax": 100,
            "nbands": 56,
            "smearing_sigma_Ry": None,
            "mixing_beta": 0.3,
            "force_thr_eV_per_A": None,
            "relax_nmax": None,
        },
        "element_order": ["Ni"],
        "pseudopotential_ids": {"Ni": "Ni_NC"},
        "pseudopotential_metadata": {"Ni": {"element": "Ni", "type": "ONCV_NC"}},
        "pseudopotential_treatment": {"Ni": "scalar"},
        "kpoints": [2, 2, 2],
        "net_charge": 0,
        "input_qualification": {"header_snapshot": "unused.json"},
        "output_control": {"out_pot": 2},
    }
    study = {
        "study_id": "ni-output-study",
        "case_id": "ni-output-case",
        "case_role": "engineering_fixture",
        "model": {"model_id": model.model_id, "version": model.version},
    }
    site = {
        "workspace": {"local": str(workspace)},
        "abacus": {
            "binary": "/opt/abacus",
            "mpi_launcher": "/opt/mpiexec",
            "environment_script": "/tmp/abacus-env.sh",
            "pseudopotential_files": {"Ni_NC": "/authorized/Ni.upf"},
        },
    }
    request = {
        "task_id": "ni-output-task",
        "calculation": "scf",
        "input_transformation": None,
        "required_results": [],
        "resource_request": {"nodes": 1, "partition": "cpu", "ntasks": 1, "cpus_per_task": 1, "mem_mib": 1024},
    }
    paths = {name: tmp_path / f"{name}.json" for name in ("method", "study", "site", "request")}
    for name, value in (("method", method), ("study", study), ("site", site), ("request", request)):
        paths[name].write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    paths["model"] = model.artifact_dir
    paths["task"] = workspace / "tasks" / request["task_id"]
    return paths


def test_create_transfers_expected_artifact_to_method_and_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _create_case(tmp_path)
    monkeypatch.setattr(
        abacus_tasks,
        "check_method_configuration",
        lambda *args: _nc_qualification(),
    )
    task = abacus_tasks.create_abacus_task(
        study_path=paths["study"], model_path=paths["model"], method_path=paths["method"],
        site_path=paths["site"], request_path=paths["request"],
    )
    expected = {
        "schema": "mlcc.abacus-electrostatic-output.v1",
        "relative_path": "OUT.NiPot/ElecStaticPot.cube",
        "kind": "local_ionic_plus_hartree",
        "value_unit": "Ry",
        "geometry_unit": "Bohr",
        "native_output_observed": False,
        "native_GPU_accepted": False,
    }
    method = json.loads((paths["task"] / "method.json").read_text(encoding="utf-8"))
    assert method["requested_artifacts"]["electrostatic_potential"] == expected
    assert task["requested_artifacts"]["electrostatic_potential"] == expected


@pytest.mark.parametrize("location", ["parameters", "top_level", "request"])
def test_create_rejects_misplaced_output_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str) -> None:
    paths = _create_case(tmp_path)
    method = json.loads(paths["method"].read_text(encoding="utf-8"))
    request = json.loads(paths["request"].read_text(encoding="utf-8"))
    if location == "parameters":
        method["parameters"]["out_pot"] = 2
    elif location == "top_level":
        method["out_pot"] = 2
    else:
        request["output_control"] = {"out_pot": 2}
    paths["method"].write_text(json.dumps(method) + "\n", encoding="utf-8")
    paths["request"].write_text(json.dumps(request) + "\n", encoding="utf-8")
    monkeypatch.setattr(abacus_tasks, "check_method_configuration", lambda *args: _nc_qualification())
    with pytest.raises(ValueError, match="output-control|output_control|out_pot"):
        abacus_tasks.create_abacus_task(
            study_path=paths["study"], model_path=paths["model"], method_path=paths["method"],
            site_path=paths["site"], request_path=paths["request"],
        )
