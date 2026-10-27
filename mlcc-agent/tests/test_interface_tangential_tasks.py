"""Public tangential-task and saved-product wiring contracts.

Every record in this file is an explicit software-contract fixture.  The
``fixture-only`` scheduler records do not represent a submitted LAMMPS job or
a material response; native reading and the domain reduction are mocked where
the task path reaches them.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _study() -> dict[str, object]:
    parents = [
        {"side": "a", "model_id": "ni", "version": "v001", "path": "ni"},
        {"side": "b", "model_id": "bto", "version": "v001", "path": "bto"},
    ]
    return {
        "schema": "mlcc.study.v1",
        "study_id": "interface-tangential-task-fixture",
        "case_id": "software-interface-tangential",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": "ni-bto-interface",
            "version": "v001",
            "spatial_mode": "layered_interface",
            "fixture": True,
        },
        "interface": {
            "schema": "mlcc.interface-study-binding.v1",
            "model_path": "interface-model",
            "parent_models": parents,
            "parent_study_refs": [],
            "request": {
                "schema": "mlcc.layered-interface-request.v1",
                "boundary": ["p", "p", "p"],
            },
        },
        "conditions": {"temperature_K": 330.0},
    }


def _protocol() -> dict[str, object]:
    return {
        "kind": "interface_tangential",
        "purpose": "interface_tangential_response",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "none",
        "static_tensor": True,
        "experiment_scope": "software_contract_only tangential fixture",
        "timestep_ps": 0.001,
        "source_kind": "software_contract_only",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "tangential_response": {
            "schema": "mlcc.interface-tangential-protocol.v1",
            "kinematics": "fixed_cell_clamped_internal_relaxation",
            "normal_cartesian": [0.0, 0.0, 1.0],
            "tangential_cartesian": [1.0, 0.0, 0.0],
            "area_angstrom2": 4.0,
            "interface_count": 2,
            "fixed_atom_ids": [11],
            "moving_atom_ids": [22],
            "free_atom_ids": [33],
            "minimization": {
                "min_style": "cg",
                "etol": 1.0e-10,
                "ftol_eV_per_A": 1.0e-8,
                "maxiter": 100,
                "maxeval": 200,
            },
            "points": [
                {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
                {"point_id": "loading", "branch": "loading", "displacement_angstrom": 0.01},
                {"point_id": "unloading", "branch": "unloading", "displacement_angstrom": 0.0},
            ],
        },
    }


def _task(
    study: dict[str, object],
    protocol: dict[str, object],
    *,
    scheduler_state: str,
    exit_code: str | None,
    scientific_status: str,
) -> dict[str, object]:
    interface_sources = {
        "schema": "mlcc.interface-sources.v1",
        "kind": "software_contract_only",
        "side_a": {"model_id": "ni", "version": "v001", "study_id": "ni-fixture"},
        "side_b": {"model_id": "bto", "version": "v001", "study_id": "bto-fixture"},
    }
    return {
        "schema": "mlcc.lammps-task.v1",
        "task_id": "interface-tangential-task-fixture",
        "kind": "interface_tangential",
        "calculation": "interface_tangential",
        "engine": "lammps",
        "protocol": deepcopy(protocol),
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": "engineering_fixture",
        "fixture": True,
        "model_id": study["model"]["model_id"],
        "model_version": study["model"]["version"],
        "model_path": "interface-model",
        "model": deepcopy(study["model"]),
        "interface_sources": interface_sources,
        "study": deepcopy(study),
        "command": ["lmp", "-in", "in.lammps"],
        "scheduler_job_id": "fixture-only",
        "scheduler_state": scheduler_state,
        "exit_code": exit_code,
        "status": "COMPLETED" if scheduler_state == "COMPLETED" else "defined",
        "scientific_status": scientific_status,
        "production_qualified": False,
    }


def _native_result() -> dict[str, object]:
    def point(point_id: str, displacement: float, *, converged: bool) -> dict[str, object]:
        return {
            "point_id": point_id,
            "energy_eV": -10.0 + displacement,
            "positions_angstrom": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
            "forces_eV_per_A": [[0.1, 0.0, 0.0], [-0.2, 0.0, 0.0], [0.1, 0.0, 0.0]],
            "native_step": 0,
            "force_source": "unconstrained_run0_at_minimized_geometry",
            "minimization": {
                "stopping_criterion": "force tolerance" if converged else "max iterations",
                "iterations": 12 if converged else 100,
                "force_evaluations": 17 if converged else 200,
                "converged": converged,
                "raw_summary": "software-contract fixture native stopping record",
            },
        }

    return {
        "schema": "mlcc.lammps-tangential-result.v1",
        "atom_ids": [11, 22, 33],
        "points": [
            point("reference", 0.0, converged=True),
            point("loading", 0.01, converged=False),
            point("unloading", 0.0, converged=True),
        ],
    }


def _response(native: dict[str, object]) -> dict[str, object]:
    # This is a saved response-shaped fixture; the stable domain fields are
    # named explicitly, but no response formula is tested in this file.
    points = []
    for native_point in native["points"]:
        points.append(
            {
                **deepcopy(native_point),
                "tangential_reaction_force_eV_per_A": 0.0,
                "cell_net_tangential_stress_GPa": 0.0,
            }
        )
    return {
        "schema": "mlcc.interface-tangential-response.v1",
        "status": "available",
        "relaxation_status": "unconverged",
        "production_qualified": False,
        "source": {"kind": "software_contract_only", "fixture": True},
        "points": points,
        "intervals": [
            {
                "from_point_id": "reference",
                "to_point_id": "loading",
                "tangential_stiffness_eV_per_A2": 0.0,
                "cell_net_tangential_stress_slope_GPa_per_A": 0.0,
            },
            {
                "from_point_id": "loading",
                "to_point_id": "unloading",
                "tangential_stiffness_eV_per_A2": 0.0,
                "cell_net_tangential_stress_slope_GPa_per_A": 0.0,
            },
        ],
    }


def _product(
    study: dict[str, object],
    task: dict[str, object],
    task_path: Path,
    native: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": "mlcc.interface-tangential-product.v1",
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": study["case_role"],
        "fixture": True,
        "model_id": task["model_id"],
        "model_version": task["model_version"],
        "model_path": task["model_path"],
        "task_id": task["task_id"],
        "task_path": str(task_path.resolve()),
        "protocol": deepcopy(task["protocol"]),
        "interface_sources": deepcopy(task["interface_sources"]),
        "source_task": {
            key: task.get(key)
            for key in ("scheduler_job_id", "scheduler_state", "exit_code", "status", "scientific_status")
        },
        "status": "available",
        "relaxation_status": "unconverged",
        "tangential_response": _response(native),
        "native_result": deepcopy(native),
        "missing_evidence": [],
        "production_qualified": False,
    }


def test_incomplete_fixture_stays_unresolved_through_public_delivery(tmp_path: Path) -> None:
    from mlcc.cli import main

    study = _study()
    task = _task(
        study,
        _protocol(),
        scheduler_state="PENDING",
        exit_code=None,
        scientific_status="not_calculated",
    )
    study_path = _write(tmp_path / "Study.json", study)
    task_path = _write(tmp_path / "task.json", task)
    product_path = tmp_path / "product.json"
    assert main(
        [
            "interface-tangential",
            "--task",
            str(task_path),
            "--output",
            str(product_path),
        ]
    ) == 0

    product = json.loads(product_path.read_text(encoding="utf-8"))
    assert product["schema"] == "mlcc.interface-tangential-product.v1"
    assert product["status"] == "unresolved"
    assert product["relaxation_status"] == "unresolved"
    assert product["tangential_response"] is None
    assert product["native_result"] is None
    assert product["missing_evidence"] == ["completed_native_interface_tangential_response"]
    assert product["source_task"]["scheduler_job_id"] == "fixture-only"

    delivery_path = tmp_path / "delivery.json"
    assert main(
        [
            "deliver-properties",
            "--study",
            str(study_path),
            "--interface-tangential",
            str(product_path),
            "--output",
            str(delivery_path),
        ]
    ) == 0
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    assert delivery["schema"] == "mlcc.interface-tangential-delivery.v1"
    assert delivery["status"] == "unresolved"
    assert delivery["response_status"] == "unresolved"
    assert delivery["relaxation_status"] == "unresolved"
    assert delivery["responses"]["constrained_tangential_response"] is None
    assert delivery["native_result"] is None
    assert delivery["missing_evidence"] == product["missing_evidence"]
    assert delivery["source_task"] == product["source_task"]
    assert delivery["interface_sources"] == task["interface_sources"]


def test_completed_fixture_preserves_max_iterations_and_existing_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mlcc.interface_tangential_tasks as tasks_module

    study = _study()
    task = _task(
        study,
        _protocol(),
        scheduler_state="COMPLETED",
        exit_code="0:0",
        scientific_status="unconverged",
    )
    task_path = _write(tmp_path / "task.json", task)
    native = _native_result()
    response = _response(native)
    captured: dict[str, object] = {}

    def fake_read(path: Path) -> dict[str, object]:
        captured["task_path"] = path
        return deepcopy(native)

    def fake_domain(
        protocol: dict[str, object],
        atom_ids: list[int],
        points: list[dict[str, object]],
    ) -> dict[str, object]:
        captured["protocol"] = deepcopy(protocol)
        captured["atom_ids"] = list(atom_ids)
        captured["points"] = deepcopy(points)
        return deepcopy(response)

    monkeypatch.setattr(tasks_module, "read_lammps_task", fake_read)
    monkeypatch.setattr(tasks_module, "tangential_response_from_points", fake_domain)
    product = tasks_module.read_interface_tangential_task(task_path)

    assert captured["task_path"] == task_path.resolve()
    assert captured["protocol"] == task["protocol"]
    assert captured["atom_ids"] == native["atom_ids"]
    assert captured["points"] == native["points"]
    assert product["status"] == "available"
    assert product["relaxation_status"] == "unconverged"
    assert product["source_task"]["scientific_status"] == "unconverged"
    assert product["tangential_response"] == response
    assert product["native_result"] == native
    assert product["native_result"]["points"][1]["minimization"]["stopping_criterion"] == "max iterations"
    assert product["native_result"]["points"][1]["minimization"]["converged"] is False
    assert product["missing_evidence"] == []


def test_saved_product_delivery_does_not_recompute_or_reread_native(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mlcc.interface_tangential as domain
    import mlcc.interface_tangential_tasks as tasks_module
    from mlcc.property_delivery import deliver_interface_tangential

    study = _study()
    task = _task(
        study,
        _protocol(),
        scheduler_state="COMPLETED",
        exit_code="0:0",
        scientific_status="unconverged",
    )
    task_path = _write(tmp_path / "task.json", task)
    study_path = _write(tmp_path / "Study.json", study)
    native = _native_result()
    product_path = _write(tmp_path / "product.json", _product(study, task, task_path, native))

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("saved tangential delivery must not recompute or reread native output")

    monkeypatch.setattr(domain, "tangential_response_from_points", forbidden)
    monkeypatch.setattr(tasks_module, "tangential_response_from_points", forbidden)
    monkeypatch.setattr(tasks_module, "read_lammps_task", forbidden)
    delivered = deliver_interface_tangential(study_path, product_path)

    product = json.loads(product_path.read_text(encoding="utf-8"))
    assert delivered["status"] == product["status"] == "available"
    assert delivered["response_status"] == "available"
    assert delivered["relaxation_status"] == "unconverged"
    assert delivered["responses"]["constrained_tangential_response"] == product["tangential_response"]
    assert delivered["native_result"] == product["native_result"]
    assert delivered["source_task"] == product["source_task"]
    assert delivered["interface_sources"] == product["interface_sources"]
    assert delivered["production_qualified"] is False


@pytest.mark.parametrize("mismatch", ["task", "model", "interface"])
def test_saved_product_rejects_task_model_or_interface_mismatch(
    tmp_path: Path, mismatch: str
) -> None:
    from mlcc.property_delivery import deliver_interface_tangential

    study = _study()
    task = _task(
        study,
        _protocol(),
        scheduler_state="COMPLETED",
        exit_code="0:0",
        scientific_status="unconverged",
    )
    task_path = _write(tmp_path / "task.json", task)
    study_path = _write(tmp_path / "Study.json", study)
    product = _product(study, task, task_path, _native_result())
    if mismatch == "task":
        product["task_id"] = "different-task"
    elif mismatch == "model":
        product["model_id"] = "different-model"
    else:
        product["interface_sources"] = {"kind": "different-interface"}
    product_path = _write(tmp_path / f"product-{mismatch}.json", product)

    with pytest.raises(ValueError, match=r"(?i)(task|model|interface|source|identity)"):
        deliver_interface_tangential(study_path, product_path)


__all__ = []
