"""Preparation-only checks for the fixed-strain LAMMPS elasticity demo."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import read as ase_read

from mlcc.lammps_elastic import prepare_lammps_elastic
from mlcc.modeling import read_model_artifacts, write_model_artifacts


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    model_path = tmp_path / "root-model"
    atoms = Atoms(
        ["Ni", "Ni"],
        positions=[[0.0, 0.0, 0.0], [1.8, 1.8, 1.8]],
        cell=[[3.6, 0.1, 0.0], [0.0, 3.7, 0.2], [0.1, 0.0, 3.8]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([20, 5], dtype=int))
    root = write_model_artifacts(
        atoms,
        model_path,
        model_id="ni-elastic-root",
        version="v001",
        fixture=True,
        fixture_purpose="elastic_static_demo",
        material="Ni",
        phase_requested="fixture",
    )
    study_path = tmp_path / "root-study.json"
    study = {
        "study_id": "ni-elastic-study",
        "case_id": "ni-elastic-case",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": root.model_id,
            "version": root.version,
            "fixture": True,
        },
    }
    _write(study_path, study)
    potential_file = tmp_path / "Ni_u3.eam"
    potential_file.write_text("fixture potential\n", encoding="utf-8")
    potential_path = tmp_path / "root-potential.json"
    _write(
        potential_path,
        {
            "potential_id": "ni-u3",
            "version": "stable22Jul2025-update4",
            "source": "LAMMPS fixture",
            "license": "GPL-2.0",
            "fixture": True,
            "production_qualification": False,
            "units": "metal",
            "atom_style": "atomic",
            "elements": ["Ni"],
            "element_order": ["Ni"],
            "model_ids": [root.model_id],
            "pair_style": "eam",
            "pair_coeff": ["* * Ni_u3.eam"],
            "files": [{"local_path": str(potential_file), "filename": "Ni_u3.eam"}],
        },
    )
    workspace = tmp_path / "workspace"
    site_path = tmp_path / "site.json"
    _write(
        site_path,
        {
            "ssh": {"alias": "v100"},
            "workspace": {"local": str(workspace), "remote_root": "/tmp/mlcc"},
            "runner": {"selected": "slurm"},
            "lammps": {
                "binary": "/opt/lmp",
                "version": "LAMMPS (22 Jul 2025 - Update 4)",
                "environment_script": "/opt/lammps-env.sh",
                "launch_prefix": [],
            },
        },
    )
    request_path = tmp_path / "request" / "request.json"
    _write(
        request_path,
        {
            "schema": "mlcc.lammps-elastic-prepare-request.v1",
            "study_path": "../root-study.json",
            "model_path": "../root-model",
            "potential_path": "../root-potential.json",
            "site_path": "../site.json",
            "plan_id": "ni-j3-demo",
            "model_version": "elastic-v001",
            "strain_amplitude": 0.001,
            "resource_request": {
                "nodes": 1,
                "partition": "gpu",
                "gres": "gpu:v100:1",
                "ntasks": 1,
                "cpus_per_task": 2,
                "mem_mib": 6144,
                "time": "00:10:00",
            },
            "timestep_ps": 0.001,
        },
    )
    return request_path, study_path, model_path, potential_path, site_path


def test_prepare_materializes_thirteen_static_points_and_response_request(tmp_path: Path) -> None:
    request_path, study_path, model_path, potential_path, _site_path = _inputs(tmp_path)
    root_study_before = study_path.read_bytes()
    root_model_before = (model_path / "model.json").read_bytes()

    manifest = prepare_lammps_elastic(request_path, tmp_path / "elastic-output")

    assert manifest["status"] == "prepared_not_submitted"
    assert manifest["native_jobs_submitted"] is False
    assert manifest["voigt_order"] == ["xx", "yy", "zz", "yz", "xz", "xy"]
    assert manifest["model_version"] == "elastic-v001"
    assert len(manifest["points"]) == 13
    assert manifest["points"][0]["point_id"] == "reference"
    assert manifest["root_potential"] == str(potential_path.resolve())
    assert manifest["potential_path"] == str((tmp_path / "elastic-output" / "potential.json").resolve())
    assert manifest["response_request_path"] == str(
        (tmp_path / "elastic-output" / "response-request.json").resolve()
    )
    assert study_path.read_bytes() == root_study_before
    assert (model_path / "model.json").read_bytes() == root_model_before
    assert json.loads(potential_path.read_text(encoding="utf-8"))["model_ids"] == [
        "ni-elastic-root"
    ]

    response = json.loads(
        Path(manifest["response_request_path"]).read_text(encoding="utf-8")
    )
    assert response["schema"] == "mlcc.lammps-elastic-response-request.v1"
    assert len(response["samples"]) == 12
    assert set(response["reference"]) == {"task_path", "result_path", "strain_voigt"}
    assert all(set(sample) == set(response["reference"]) for sample in response["samples"])
    assert len(json.loads((tmp_path / "elastic-output" / "prepare-manifest.json").read_text(encoding="utf-8"))["points"]) == 13

    child = next(point for point in manifest["points"] if point["point_id"] == "minus-yz-a0")
    child_model = read_model_artifacts(child["model_path"])
    assert child_model.atom_ids == [20, 5]
    assert child_model.version == "elastic-v001"
    assert child_model.metadata["source_structure_role"] == "generated_child_reference"
    assert child_model.metadata["parent_model"]["model_id"] == "ni-elastic-root"
    assert child_model.metadata["derivation"]["kind"] == "voigt_strain_fixed_fractional"
    assert child_model.metadata["derivation"]["strain_record"]["kind"] == "voigt_strain"
    root_model = read_model_artifacts(model_path)
    assert np.allclose(
        child_model.atoms.get_scaled_positions(wrap=False),
        root_model.atoms.get_scaled_positions(wrap=False),
    )
    assert not np.allclose(child_model.atoms.cell.array, root_model.atoms.cell.array)
    source_atoms = ase_read(str(Path(child["model_path"]) / "source.cif"), format="cif")
    # CIF stores cell lengths/angles; the reader may choose another Cartesian
    # orientation.  The source metric must still describe the unstrained root.
    np.testing.assert_allclose(source_atoms.cell.cellpar(), root_model.atoms.cell.cellpar(), atol=1e-6)
    child_study = json.loads(Path(child["study_path"]).read_text(encoding="utf-8"))
    assert child_study["parent_study_id"] == "ni-elastic-study"
    assert child_study["model"]["model_id"] == child_model.model_id
    task_path = Path(child["task_path"])
    task = json.loads(task_path.read_text(encoding="utf-8"))
    assert task["elastic_strain"]["plan_id"] == "ni-j3-demo"
    assert task["elastic_strain"]["kind"] == "voigt_strain"
    assert task["elastic_strain"]["point_kind"] == "strained"
    assert task["root_study"]["study_id"] == "ni-elastic-study"
    assert task["root_study"]["path"] == str(study_path.resolve())
    assert task["child_study"]["study_id"] == child_study["study_id"]
    assert task["child_study"]["model"]["model_id"] == child_model.model_id
    assert task["request_path"] == str((Path(child["study_path"]).parent / "request.json").resolve())
    assert task["status"] == "prepared"
    input_text = (task_path.parent / "in.lammps").read_text(encoding="utf-8")
    assert "static_tensor" not in input_text
    assert "compute mlcc_static_pressure all pressure NULL virial" in input_text
    assert "run 0" in input_text

    child_model_ids = {
        read_model_artifacts(point["model_path"]).model_id for point in manifest["points"]
    }
    potential = json.loads(
        (tmp_path / "elastic-output" / "potential.json").read_text(encoding="utf-8")
    )
    assert len(child_model_ids) == 13
    assert set(potential["model_ids"]) == {"ni-elastic-root", *child_model_ids}

