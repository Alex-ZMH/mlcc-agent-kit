"""New NAO public entry checks; run only in the site's Slurm allocation."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mlcc.site_runner import SiteConfig, SiteRunner
from mlcc.tasks import load_task


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def inputs():
    return load(os.environ["MLCC_NAO_ENTRY_INPUTS"])


def public_command(directory, name, action, **paths):
    command = [sys.executable, "-m", "mlcc.cli", action]
    for key, path in paths.items():
        command.extend(["--" + key, str(path)])
    result = subprocess.run(command, capture_output=True, text=True)
    save(directory / (name + "-command.json"),
         {"command": command, "cwd": str(Path.cwd()), "returncode": result.returncode})
    (directory / (name + "-stdout.txt")).write_text(result.stdout, encoding="utf-8")
    (directory / (name + "-stderr.txt")).write_text(result.stderr, encoding="utf-8")
    return result


def test_public_nao_snapshot_to_task_prepare(inputs):
    directory = Path(inputs["root"]) / "public-nao-positive"
    directory.mkdir()
    config, site = load(inputs["method"]), load(inputs["site"])
    snapshot_path = Path(inputs["snapshot"])
    assert config["input_qualification"]["orbital_header_snapshot"] == str(snapshot_path)
    assert not snapshot_path.exists()
    result = public_command(directory, "inspect", "inspect-nao", method=inputs["method"],
                            site=inputs["site"], output=snapshot_path)
    assert result.returncode == 0, result.stderr
    snapshot = load(snapshot_path)
    library = config["numerical_orbital_library"]
    assert snapshot["schema"] == "mlcc.nao-header-snapshot.v1"
    assert snapshot["inspection"] == "explicit_native_files_read_on_configured_site"
    assert snapshot["ssh_alias"] == site["ssh"]["alias"]
    assert snapshot["method_set"] == config["method_set"]
    assert snapshot["library"] == library["name"]
    assert snapshot["library_version"] == library["version"]
    assert snapshot["pairing_source"] == library["pairing_source"]
    assert snapshot["pairing_native_excerpt"] == Path(library["pairing_source"]).read_text(encoding="utf-8")
    assert snapshot["pseudopotential_map_path"] == library["pseudopotential_map"]
    assert snapshot["pseudopotential_map_text"] == Path(library["pseudopotential_map"]).read_text(encoding="utf-8")
    library_map = json.loads(snapshot["pseudopotential_map_text"])
    assert set(snapshot["native_excerpts"]) == set(config["element_order"])
    for element in config["element_order"]:
        excerpt = snapshot["native_excerpts"][element]
        orbital_id = config["numerical_orbital_ids"][element]
        pseudo_id = config["pseudopotential_ids"][element]
        orbital = site["abacus"]["numerical_orbital_files"][orbital_id]
        pseudo = site["abacus"]["pseudopotential_files"][pseudo_id]
        assert excerpt["source_path"] == orbital
        assert excerpt["orbital_id"] == orbital_id
        assert excerpt["source_kind"] == "declared_library_pairing"
        assert excerpt["functional"] == "PBE"
        assert excerpt["paired_pseudopotential_id"] == pseudo_id
        assert excerpt["paired_pseudopotential_source"] == pseudo
        assert library_map[element] == Path(pseudo).name
        assert Path(orbital).read_text(encoding="utf-8").startswith(excerpt["native_excerpt"])
        assert excerpt["native_excerpt"].splitlines()[-1].split() == ["SUMMARY", "END"]
    assert snapshot["scientific_qualification"] is False
    assert snapshot["production_qualification"] is False
    result = public_command(directory, "qualify", "qualify-method", model=inputs["model"],
                            method=inputs["method"], site=inputs["site"],
                            output=directory / "qualification.json")
    assert result.returncode == 0, result.stderr
    assert load(directory / "qualification.json")["input_qualified"] is True
    result = public_command(directory, "create", "create-abacus",
                            **{key: inputs[key] for key in ("study", "model", "method", "site", "request")})
    assert result.returncode == 0, result.stderr
    task = json.loads(result.stdout)
    task_directory = Path(site["workspace"]["local"]) / "tasks" / task["task_id"]
    assert task["scheduler_job_id"] is None
    assert task["method_input_qualified"] is True
    assert load(task_directory / "method.json")["production_qualification"] is False
    for artifact in ("hamiltonian", "overlap", "position"):
        assert task["requested_artifacts"][artifact]["native_output_observed"] is False
    SiteRunner(SiteConfig.from_mapping(site)).prepare(load_task(task_directory / "task.json"))
    batch = (task_directory / "job.sbatch").read_text()
    assert "#SBATCH --time=0" in batch and "#SBATCH --no-requeue" in batch
    assert load(task_directory / "task.json")["scheduler_job_id"] is None
    save(directory / "prepare-evidence.json", {
        "operation": "SiteRunner.prepare", "task": str(task_directory / "task.json"),
        "batch": str(task_directory / "job.sbatch"), "scheduler_job_id": None,
        "source_task_reused_for_inputs": inputs["native_source_task"],
        "source_job_id": inputs["source_job_id"], "prior_public_creation_job": inputs["prior_public_creation_job"],
        "native_output_observed": False, "production_qualification": False,
    })


@pytest.mark.parametrize("fault,error", [
    ("missing_metadata", "numerical_orbital_library"),
    ("missing_resource", "No such file or directory"),
    ("wrong_element", "NAO header element"),
    ("wrong_upf_map", "does not match the selected UPF"),
    ("missing_map_element", "must contain every selected element"),
    ("wrong_functional", "must both declare PBE"),
    ("empty_pairing", "pairing source must contain"),
    ("existing_output", "File exists"),
])
def test_public_nao_rejects_invalid_input(inputs, fault, error):
    directory = Path(inputs["root"]) / ("public-nao-" + fault)
    directory.mkdir()
    config, site = load(inputs["method"]), load(inputs["site"])
    library = config["numerical_orbital_library"]
    element, other = config["element_order"][:2]
    output = directory / "snapshot.json"
    if fault == "missing_metadata":
        del config["numerical_orbital_library"]
    elif fault == "missing_resource":
        site["abacus"]["numerical_orbital_files"][config["numerical_orbital_ids"][element]] = str(directory / "absent.orb")
    elif fault == "wrong_element":
        native = Path(site["abacus"]["numerical_orbital_files"][config["numerical_orbital_ids"][other]])
        header = native.read_text(encoding="utf-8").split("SUMMARY END", 1)[0] + "SUMMARY END\n"
        wrong = directory / "wrong-element.orb"
        wrong.write_text(header, encoding="utf-8")
        site["abacus"]["numerical_orbital_files"][config["numerical_orbital_ids"][element]] = str(wrong)
    elif fault in ("wrong_upf_map", "missing_map_element"):
        mapping = load(library["pseudopotential_map"])
        if fault == "wrong_upf_map":
            mapping[element] = "unselected.upf"
        else:
            del mapping[element]
        save(directory / "element.json", mapping)
        library["pseudopotential_map"] = str(directory / "element.json")
    elif fault == "wrong_functional":
        library["functional"] = "LDA"
    elif fault == "empty_pairing":
        (directory / "empty-readme.txt").write_text("", encoding="utf-8")
        library["pairing_source"] = str(directory / "empty-readme.txt")
    elif fault == "existing_output":
        output.write_text("existing output must remain unchanged\n", encoding="utf-8")
    save(directory / "method.json", config)
    save(directory / "site.json", site)
    result = public_command(directory, "inspect", "inspect-nao", method=directory / "method.json",
                            site=directory / "site.json", output=output)
    assert result.returncode != 0
    assert error in result.stderr
    if fault == "existing_output":
        assert output.read_text(encoding="utf-8") == "existing output must remain unchanged\n"
    else:
        assert not output.exists()
