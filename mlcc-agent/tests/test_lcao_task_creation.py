"""New public LCAO path checks against saved native CZO inputs on v100."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from ase.io import read

from mlcc.abacus_tasks import create_abacus_task
from mlcc.site_runner import SiteConfig, SiteRunner
from mlcc.tasks import load_task


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture
def native_cases():
    return load(os.environ["MLCC_LCAO_NATIVE_CASES"])


def parameters(path):
    result = {}
    for line in Path(path).read_text().splitlines()[1:]:
        tokens = line.split()
        if len(tokens) >= 2:
            result[tokens[0]] = tokens[1:]
    return result


@pytest.mark.parametrize("case", ["reference", "displacement"])
def test_public_lcao_creation_reuses_native_inputs(native_cases, case):
    selected = native_cases[case]
    command = [sys.executable, "-m", "mlcc.cli", "create-abacus"]
    for name in ("study", "model", "method", "site", "request"):
        command.extend(["--" + name, selected[name]])
    result = subprocess.run(command, capture_output=True, text=True)
    save(Path(selected["request"]).with_name("public-command.json"),
         {"command": command, "returncode": result.returncode,
          "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode == 0, result.stderr
    task = json.loads(result.stdout)
    directory = Path(load(selected["site"])["workspace"]["local"]) / "tasks" / task["task_id"]
    origin = Path(selected["native_task"])
    actual, original = parameters(directory / "INPUT"), parameters(origin / "INPUT")
    for key in ("basis_type", "ks_solver", "device", "ecutwfc", "scf_thr", "scf_nmax", "nbands",
                "nspin", "lspinorb", "noncolin", "mixing_type", "mixing_beta", "symmetry",
                "out_chg", "out_bandgap", "out_mat_hs2", "out_mat_r", "cal_force", "cal_stress"):
        assert actual[key] == original[key], key
    assert (directory / "KPT").read_text().split() == (origin / "KPT").read_text().split()
    actual_atoms, native_atoms = read(directory / "input.extxyz"), read(origin / "input.extxyz")
    assert actual_atoms.get_chemical_symbols() == native_atoms.get_chemical_symbols()
    np.testing.assert_allclose(actual_atoms.positions, native_atoms.positions, atol=1e-12, rtol=0)
    np.testing.assert_allclose(actual_atoms.cell.array, native_atoms.cell.array, atol=1e-12, rtol=0)
    mapping, native_mapping = load(directory / "STRU.atom-map.json"), load(origin / "STRU.atom-map.json")
    assert mapping["source_atom_ids"] == native_mapping["source_atom_ids"]
    assert mapping["abacus_order"] == native_mapping["abacus_order"]
    method = load(directory / "method.json")
    site = load(selected["site"])
    config = load(selected["method"])
    ordered_orbs = [Path(site["abacus"]["numerical_orbital_files"][config["numerical_orbital_ids"][e]]).name
                    for e in config["element_order"]]
    section = (directory / "STRU").read_text().split("NUMERICAL_ORBITAL", 1)[1].split("LATTICE_CONSTANT", 1)[0]
    assert section.split() == ordered_orbs
    assert method["basis_type"] == task["basis_type"] == "lcao"
    assert method["input_qualification"]["electron_count"]["target_electrons"] == 160
    assert task["method_input_qualified"] is True
    assert method["production_qualification"] is False
    assert task["scheduler_job_id"] is None
    assert not (directory / "job.sbatch").exists()
    for element in config["element_order"]:
        path = site["abacus"]["numerical_orbital_files"][config["numerical_orbital_ids"][element]]
        assert path in (directory / "run-abacus.sh").read_text()
        assert method["numerical_orbitals"][element]["source"] == path
    for artifact in ("hamiltonian", "overlap", "position"):
        assert task["requested_artifacts"][artifact]["native_output_observed"] is False
    runner = SiteRunner(SiteConfig.from_mapping(site))
    runner.prepare(load_task(directory / "task.json"))
    batch = (directory / "job.sbatch").read_text()
    assert "#SBATCH --time=0" in batch and "#SBATCH --no-requeue" in batch
    assert "#SBATCH --gpus-per-task=v100:1" in batch
    assert load(directory / "task.json")["scheduler_job_id"] is None


@pytest.mark.parametrize("fault,match", [
    ("missing_orbital", "orbital"), ("wrong_element", "element"),
    ("wrong_xc", "functional|PBE"), ("missing_pairing", "pairing"),
    ("collision", "colliding|basename"), ("pw_with_orbitals", "PW"),
    ("solver", "cusolver|execution"), ("relax", "SCF"), ("charge", "charge|neutral"),
    ("override", "method configuration"),
])
def test_public_lcao_rejects_invalid_contract(native_cases, tmp_path, fault, match):
    selected = native_cases["reference"]
    config, site, request = map(load, (selected["method"], selected["site"], selected["request"]))
    snapshot = load(config["input_qualification"]["orbital_header_snapshot"])
    snapshot = copy.deepcopy(snapshot)
    request["task_id"] = "invalid-" + fault
    site["workspace"]["local"] = str(tmp_path)
    (tmp_path / "tasks").mkdir()
    if fault == "missing_orbital":
        config["numerical_orbital_ids"].pop("Ca")
    elif fault == "wrong_element":
        snapshot["native_excerpts"]["Ca"]["native_excerpt"] = snapshot["native_excerpts"]["Ca"]["native_excerpt"].replace("Ca", "Ba")
    elif fault == "wrong_xc":
        snapshot["native_excerpts"]["Ca"]["functional"] = "LDA"
    elif fault == "missing_pairing":
        snapshot.pop("pairing_source")
    elif fault == "collision":
        site["abacus"]["numerical_orbital_files"][config["numerical_orbital_ids"]["Ca"]] = "/other/O.upf"
    elif fault == "pw_with_orbitals":
        config["basis_type"] = "pw"
    elif fault == "solver":
        config["execution"]["ks_solver"] = "cg"
    elif fault == "relax":
        request["calculation"] = "relax"
    elif fault == "charge":
        config["net_charge"] = 2
    elif fault == "override":
        request["basis_type"] = "pw"
    save(tmp_path / "orbital-snapshot.json", snapshot)
    config["input_qualification"]["orbital_header_snapshot"] = str(tmp_path / "orbital-snapshot.json")
    for name, value in (("method", config), ("site", site), ("request", request)):
        save(tmp_path / (name + ".json"), value)
    with pytest.raises((ValueError, KeyError), match=match):
        create_abacus_task(study_path=selected["study"], model_path=selected["model"],
                           method_path=tmp_path / "method.json", site_path=tmp_path / "site.json",
                           request_path=tmp_path / "request.json")
