"""Software-contract tests prepared for v100 Slurm acceptance.

The tests exercise only protocol/input/task routing.  They do not launch
LAMMPS or parse a native log/dump; native completion remains planned for the
v100 Slurm acceptance job.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mlcc import lammps_interface_normal as native_tangential
from mlcc import lammps_tasks
from mlcc.lammps import _input_text, parse_lammps_outputs, validate_lammps_protocol


def _protocol() -> dict[str, object]:
    return {
        "kind": "interface_tangential",
        "purpose": "interface_tangential_response",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "none",
        "static_tensor": True,
        "experiment_scope": "Ni layered interface tangential routing fixture",
        "timestep_ps": 0.001,
        "tangential_response": {
            "schema": "mlcc.interface-tangential-protocol.v1",
            "kinematics": "fixed_cell_clamped_internal_relaxation",
            "normal_cartesian": [0.0, 0.0, 1.0],
            "tangential_cartesian": [1.0, 0.0, 0.0],
            "area_angstrom2": 12.3904,
            "interface_count": 2,
            "fixed_atom_ids": [0, 3],
            "moving_atom_ids": [4, 7],
            "free_atom_ids": [1, 2, 5, 6],
            "minimization": {
                "min_style": "cg",
                "etol": 0.0,
                "ftol_eV_per_A": 1.0e-6,
                "maxiter": 200,
                "maxeval": 2000,
            },
            "points": [
                {
                    "point_id": "reference",
                    "branch": "reference",
                    "displacement_angstrom": 0.0,
                },
                {
                    "point_id": "load",
                    "branch": "loading",
                    "displacement_angstrom": 0.01,
                },
                {
                    "point_id": "return",
                    "branch": "unloading",
                    "displacement_angstrom": 0.0,
                },
            ],
        },
    }


def _atom_map() -> dict[str, object]:
    return {
        "model_id": "ni-layered-fixture",
        "version": "v001",
        "source_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "atoms": [
            {"source_index": index, "source_atom_id": index, "lammps_id": index + 1, "type": 1}
            for index in range(8)
        ],
    }


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_tangential_protocol_and_public_input_route():
    protocol = _protocol()

    validate_lammps_protocol(protocol)
    text = _input_text(
        {
            "pair_style": "eam",
            "pair_coeff": ["* * Ni_u3.eam"],
        },
        protocol,
        {"1": 58.6934},
        _atom_map(),
    )

    assert "# MLCC LAMMPS interface tangential response" in text
    assert "group mlcc_tangential_fixed id 1 4" in text
    assert "group mlcc_tangential_moving id 5 8" in text
    assert "group mlcc_tangential_free id 2 3 6 7" in text
    assert "dump.tangential-0000" in text
    assert "dump.tangential-0002" in text

    invalid = deepcopy(protocol)
    invalid["ensemble"] = "nvt"
    with pytest.raises(ValueError, match="tangential protocol ensemble must be none"):
        validate_lammps_protocol(invalid)


def test_tangential_output_parser_is_selected_before_generic_parser(tmp_path: Path, monkeypatch):
    assert hasattr(native_tangential, "parse_tangential_outputs")
    called: dict[str, object] = {}

    def fake_parser(directory, method, atom_map):
        called.update(directory=directory, method=method, atom_map=atom_map)
        return {"schema": "mlcc.lammps-tangential-result.v1", "engine": "lammps"}

    monkeypatch.setattr(native_tangential, "parse_tangential_outputs", fake_parser)
    method = {
        "protocol": _protocol(),
        "potential": {},
    }
    atom_map = {"native": "tangential-routing-fixture"}
    _json(tmp_path / "method.json", method)
    _json(tmp_path / "atom-map.json", atom_map)

    result = parse_lammps_outputs(tmp_path)

    assert result["schema"] == "mlcc.lammps-tangential-result.v1"
    assert called["directory"] == tmp_path
    assert called["method"] == method
    assert called["atom_map"] == atom_map


def test_tangential_task_creation_collects_only_tangential_dumps(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    (workspace / "tasks").mkdir(parents=True)
    model_path = tmp_path / "model"
    potential_file = tmp_path / "Ni_u3.eam"
    potential_file.write_text("fixture potential\n", encoding="utf-8")

    study = {
        "study_id": "ni-tangential-fixture-v001",
        "case_id": "ni_tangential_fixture",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": "ni-fcc-engineering",
            "version": "v001",
            "fixture": True,
        },
    }
    potential = {
        "potential_id": "ni-u3",
        "version": "stable22Jul2025-update4",
        "source": "LAMMPS bundled Ni_u3.eam",
        "license": "GPL-2.0",
        "fixture": True,
        "production_qualification": False,
        "units": "metal",
        "atom_style": "atomic",
        "elements": ["Ni"],
        "element_order": ["Ni"],
        "model_ids": ["ni-fcc-engineering"],
        "pair_style": "eam",
        "pair_coeff": ["* * Ni_u3.eam"],
        "files": [{"local_path": str(potential_file), "filename": "Ni_u3.eam"}],
    }
    site = {
        "ssh": {"alias": "v100"},
        "workspace": {"local": str(workspace), "remote_root": "/home/v100/projects/mlcc"},
        "runner": {"selected": "slurm"},
        "lammps": {
            "binary": "/home/v100/projects/mlcc/.venv-lammps/bin/lmp",
            "version": "LAMMPS (22 Jul 2025 - Update 4)",
            "environment_script": "/home/v100/projects/mlcc/lammps-env.sh",
            "launch_prefix": [],
        },
    }
    request = {
        "task_id": "p11-ni-lammps-tangential-v001",
        "required_results": [],
        "resource_request": {
            "nodes": 1,
            "partition": "cpu",
            "ntasks": 1,
            "cpus_per_task": 1,
            "mem_mib": 1024,
            "time": "00:05:00",
        },
    }
    protocol = _protocol()
    paths = {
        "study": tmp_path / "study.json",
        "potential": tmp_path / "potential.json",
        "protocol": tmp_path / "protocol.json",
        "site": tmp_path / "site.json",
        "request": tmp_path / "request.json",
    }
    _json(paths["study"], study)
    _json(paths["potential"], potential)
    _json(paths["protocol"], protocol)
    _json(paths["site"], site)
    _json(paths["request"], request)

    model = SimpleNamespace(
        model_id="ni-fcc-engineering",
        version="v001",
        atom_ids=[0, 1, 2, 3, 4, 5, 6, 7],
        metadata={
            "fixture": True,
            "fixture_purpose": "software_contract_only",
            "source_path": "software-contract:model-fixture",
            "source_version": "test-model-v001",
        },
    )
    monkeypatch.setattr(
        lammps_tasks,
        "_study_model_contract",
        lambda study, selected_model_path, selected_protocol: model,
    )

    def fake_prepare(model, directory, *, potential, protocol):
        _json(
            Path(directory) / "method.json",
            {
                "schema": "mlcc.lammps-method.v1",
                "engine": "lammps",
                "model_id": model.model_id,
                "version": model.version,
                "units": "metal",
                "atom_style": "atomic",
                "element_order": ["Ni"],
                "potential": dict(potential),
                "protocol": dict(protocol),
            },
        )
        return {}

    monkeypatch.setattr(lammps_tasks, "prepare_lammps", fake_prepare)
    monkeypatch.setattr(native_tangential, "validate_tangential_model", lambda model, protocol: None)

    data = lammps_tasks.create_lammps_task(
        study_path=paths["study"],
        model_path=model_path,
        potential_path=paths["potential"],
        protocol_path=paths["protocol"],
        site_path=paths["site"],
        request_path=paths["request"],
    )

    assert data["calculation"] == "interface_tangential"
    assert data["scientific_status"] == "not_calculated"
    assert data["collect_paths"] == [
        "stdout.log",
        "stderr.log",
        "log.lammps",
        "dump.tangential-0000",
        "dump.tangential-0001",
        "dump.tangential-0002",
    ]
    assert data["production_qualification"] is False
