"""Focused contract checks for chemical-reference delivery.

The records in this file are deliberately labelled ``software_contract_only``.
They exercise the saved-record/Study/CLI wiring and the existing chemical
potential algebra; they are not native DFT evidence or a material
qualification claim.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from mlcc.abacus import _energy_definition
import mlcc.cli as cli
import mlcc.defect_thermodynamics as defect_thermodynamics
from mlcc.chemical_references import assemble_chemical_reference_set
from mlcc.cli import build_parser
from mlcc.property_delivery import deliver_chemical_references


ENERGY_DEFINITION = _energy_definition("fixed")


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _method(method_set: str, *, elements: tuple[str, ...] = ("Ca",)) -> dict[str, Any]:
    return {
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "basis_type": "pw",
        "dft_functional": "PBE",
        "method_set": method_set,
        "net_charge": 0,
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "pseudopotential_ids": {element: f"{element}.NC.PBE.v001" for element in elements},
        "pseudopotential_metadata": {
            element: {
                "type": "norm_conserving",
                "valence_electrons": 8,
                "relativistic": "scalar",
            }
            for element in elements
        },
        "pseudopotential_treatment": {
            element: "scalar_relativistic_norm_conserving" for element in elements
        },
        "initial_moments_muB_by_element": {element: 0.0 for element in elements},
        "smearing_method": "fixed",
        "ks_solver": "dav",
        "kpoints": [2, 2, 2],
        "kpoint_shift": [0, 0, 0],
        "kpoint_rule": "Gamma",
        "mixing_type": "plain",
        "symmetry": "none",
        "parameters": {"ecutwfc_Ry": 100.0, "scf_thr": 1.0e-4},
    }


def _source(
    reference_id: str,
    *,
    study_id: str = "study-czo",
    model_id: str = "model-czo",
    model_version: str = "v001",
    method_set: str = "method-host",
    task_path: str = "/software-contract/host-task",
    total_energy: float = -2.0,
    formula_units: int = 1,
) -> dict[str, Any]:
    """Return the saved source envelope consumed by property delivery."""

    return {
        "task_path": task_path,
        "task_id": f"software-contract-{reference_id}",
        "study": {"study_id": study_id, "source_file": "/software-contract/study.json"},
        "model": {
            "model_id": model_id,
            "version": model_version,
            "path": "/software-contract/model",
        },
        "method": _method(method_set),
        "engine": "abacus",
        "engine_version": "3.10.1",
        "method_set": method_set,
        "energy_definition": ENERGY_DEFINITION,
        "parent_total_energy_provenance": {
            "definition": ENERGY_DEFINITION,
            "is_potential_zero": False,
        },
        "native_job": {
            "scheduler_job_id": "software-contract-job",
            "state": "COMPLETED",
            "exit_code": "0:0",
        },
        "total_energy_eV_cell": total_energy,
        "energy_eV_per_formula_unit": total_energy / formula_units,
        "evidence_kind": "software_contract_only",
        "electronic_source": {
            "evidence_kind": "software_contract_only",
            "electronic_converged": True,
            "source_file": "/software-contract/electronic.json",
        },
        "source_files": {},
        "source_evidence": {"fixture": True, "purpose": "software_contract_only"},
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }


def _reference(
    reference_id: str,
    role: str,
    *,
    phase_id: str | None = None,
    stoichiometry: dict[str, int] | None = None,
    formula_units: int = 1,
    total_energy: float = -2.0,
    method_set: str = "method-host",
    task_path: str = "/software-contract/host-task",
    study_id: str = "study-czo",
    model_id: str = "model-czo",
) -> dict[str, Any]:
    stoichiometry = dict(stoichiometry or {"Ca": 1})
    composition = {element: count * formula_units for element, count in stoichiometry.items()}
    source = _source(
        reference_id,
        study_id=study_id,
        model_id=model_id,
        method_set=method_set,
        task_path=task_path,
        total_energy=total_energy,
        formula_units=formula_units,
    )
    source["method"] = _method(method_set, elements=tuple(composition))
    return {
        "schema": "mlcc.chemical-reference.v1",
        "reference_id": reference_id,
        "role": role,
        "phase_id": phase_id or f"phase-{reference_id}",
        "phase_selection_source": "software_contract_only explicit declaration",
        "formula_stoichiometry": stoichiometry,
        "cell_composition": composition,
        "formula_units": formula_units,
        "total_energy_eV_cell": total_energy,
        "energy_eV_per_formula_unit": total_energy / formula_units,
        "elemental_mu_eV_per_atom": (
            total_energy / sum(composition.values()) if role == "elemental" else None
        ),
        "source": source,
        "method_set": method_set,
        "evidence_kind": "software_contract_only",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "scientific_qualification": False,
        "production_qualification": False,
    }


def _study(path: Path, *, study_id: str = "study-czo", model_id: str = "model-czo") -> Path:
    return _write_json(
        path,
        {
            "study_id": study_id,
            "model": {"model_id": model_id, "version": "v001", "path": "/software-contract/model"},
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )


def _collection(
    path: Path,
    *,
    references: list[dict[str, Any]],
    region_request: dict[str, Any] | None = None,
    missing: list[str] | None = None,
    reference_set_id: str = "software-contract-reference-set",
) -> Path:
    return _write_json(
        path,
        {
            "schema": "mlcc.chemical-reference-set.v1",
            "reference_set_id": reference_set_id,
            "elements": ["Ca"],
            "host_reference_id": "host",
            "references": references,
            "per_reference_methods": {
                record["reference_id"]: {
                    "method_set": record["source"]["method"]["method_set"],
                    "reference_method_id": reference_set_id,
                }
                for record in references
            },
            "method_comparison": {
                "status": "recorded_physics_and_common_element_PP_match",
                "evidence_kind": "software_contract_only",
            },
            "missing": list(missing or []),
            "region_request": region_request,
            "selected_delta_mu": None,
            "scientific_qualification": False,
            "production_qualification": False,
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        },
    )


def _one_element_region_request() -> dict[str, Any]:
    group = "software-contract-reference-set"
    identity = {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "energy_definition": ENERGY_DEFINITION,
        "reference_method_id": group,
    }
    return {
        "schema": "mlcc.chemical-potential-request.v1",
        "elements": ["Ca"],
        "mu_ref": {
            "Ca": {
                "value_eV_per_atom": -1.0,
                "source": "software-contract Ca reference",
                "method_set": "method-element-Ca",
                **identity,
            }
        },
        "physics": {
            "temperature_model": "0K_DFT_formation_energy",
            "temperature_K": 0.0,
            "pressure_role": "not_applied",
            "oxygen_reservoir": None,
        },
        "host": {
            "phase_id": "Ca_host",
            "stoichiometry": {"Ca": 1},
            "formation_energy_eV": -1.0,
            "source_tasks": ["software-contract-host"],
            "method_set": "method-host",
            **identity,
        },
        "competing_phases": [],
        "selected_delta_mu": {"Ca": -1.0},
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }


def test_delivery_rejects_study_or_model_mismatch(tmp_path: Path) -> None:
    host = _reference("host", "host")
    collection = _collection(tmp_path / "collection.json", references=[host])

    with pytest.raises(ValueError, match="chemical-reference host differs"):
        deliver_chemical_references(_study(tmp_path / "wrong-study.json", study_id="other-study"), collection)
    with pytest.raises(ValueError, match="chemical-reference host differs"):
        deliver_chemical_references(_study(tmp_path / "wrong-model.json", model_id="other-model"), collection)


def test_incomplete_saved_set_preserves_host_energy_and_null_outputs(tmp_path: Path) -> None:
    host = _reference(
        "host", "host", formula_units=4, total_energy=-123.456, method_set="method-host",
    )
    missing = [
        "elemental_reference:Ca",
        "elemental_reference:Zr",
        "elemental_reference:O",
        "competing_phase_selection",
        "selected_delta_mu",
    ]
    collection = _collection(
        tmp_path / "collection.json",
        references=[host],
        missing=missing,
        region_request=None,
    )

    result = deliver_chemical_references(_study(tmp_path / "study.json"), collection)

    assert result["missing"] == missing
    assert result["region"] is None
    assert result["chemical_point"] is None
    assert result["mathematical_chemical_point"] is None
    assert result["host"]["total_energy_eV_cell"] == pytest.approx(-123.456)
    assert result["host"]["energy_eV_per_formula_unit"] == pytest.approx(-30.864)
    assert result["host"]["source"]["total_energy_eV_cell"] == pytest.approx(-123.456)
    assert result["host"]["source"]["energy_eV_per_formula_unit"] == pytest.approx(-30.864)
    assert result["host"]["evidence_kind"] == "software_contract_only"


def test_software_math_collection_calls_existing_region_solver_without_native_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _reference("host", "host", total_energy=-2.0, method_set="method-host")
    elemental = _reference(
        "ca", "elemental", phase_id="declared-Ca", total_energy=-1.0,
        method_set="method-element-Ca",
    )
    collection = _collection(
        tmp_path / "collection.json",
        references=[host, elemental],
        region_request=_one_element_region_request(),
    )
    calls: list[dict[str, Any]] = []
    original_solver = defect_thermodynamics.chemical_potential_region

    def spy(request: dict[str, Any]) -> dict[str, Any]:
        calls.append(copy.deepcopy(request))
        return original_solver(request)

    monkeypatch.setattr(defect_thermodynamics, "chemical_potential_region", spy)
    result = deliver_chemical_references(_study(tmp_path / "study.json"), collection)

    assert calls == [_one_element_region_request()]
    assert result["region"]["schema"] == "mlcc.chemical-potential-region.v1"
    assert result["region"]["selected_point"]["feasible"] is True
    assert result["chemical_point"] is None
    assert result["mathematical_chemical_point"] is not None
    assert result["mathematical_chemical_point"]["evidence_kind"] == "software_contract_only"
    assert result["mathematical_chemical_point"]["scientific_qualification"] is False
    assert all(record["evidence_kind"] == "software_contract_only" for record in result["references"]["references"])


def test_assembly_groups_different_method_sets_without_overwriting_labels() -> None:
    reference_set_id = "software-contract-reference-set"
    host = _reference("host", "host", method_set="method-host")
    elemental = _reference("ca", "elemental", method_set="method-element-Ca", total_energy=-1.0)
    request = {
        "schema": "mlcc.chemical-reference-request.v1",
        "reference_set_id": reference_set_id,
        "elements": ["Ca"],
        "host_reference_id": "host",
        "elemental_reference_ids": {"Ca": "ca"},
        "competing_reference_ids": [],
        "selected_delta_mu": None,
        "references": [
            {
                "reference_id": "host",
                "role": "host",
                "phase_id": host["phase_id"],
                "phase_selection_source": host["phase_selection_source"],
                "formula_stoichiometry": {"Ca": 1},
                "task_path": "/software-contract/host-task",
                "electronic_path": "/software-contract/host-electronic.json",
            },
            {
                "reference_id": "ca",
                "role": "elemental",
                "phase_id": elemental["phase_id"],
                "phase_selection_source": elemental["phase_selection_source"],
                "formula_stoichiometry": {"Ca": 1},
                "task_path": "/software-contract/ca-task",
                "electronic_path": "/software-contract/ca-electronic.json",
            },
        ],
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }

    result = assemble_chemical_reference_set(request, [host, elemental])

    by_id = {record["reference_id"]: record for record in result["references"]}
    assert by_id["host"]["method_set"] == "method-host"
    assert by_id["ca"]["method_set"] == "method-element-Ca"
    assert by_id["host"]["reference_method_id"] == reference_set_id
    assert by_id["ca"]["reference_method_id"] == reference_set_id
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False


def test_cli_chemical_reference_sources_are_mutually_exclusive() -> None:
    parser = build_parser()
    parsed = parser.parse_args([
        "deliver-properties", "--study", "study.json",
        "--chemical-references", "collection.json", "--output", "out.json",
    ])
    assert parsed.chemical_references == Path("collection.json")
    with pytest.raises(SystemExit):
        parser.parse_args([
            "deliver-properties", "--study", "study.json", "--tasks", "task",
            "--chemical-references", "collection.json", "--output", "out.json",
        ])
    with pytest.raises(SystemExit):
        parser.parse_args([
            "neutral-formation", "--host-task", "host", "--defect-task", "defect",
            "--descriptor", "descriptor.json", "--output", "out.json",
            "--chemical-point", "point.json", "--chemical-reference-delivery", "delivery.json",
        ])


def test_cli_neutral_formation_forwards_only_native_point_from_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_task = tmp_path / "host-task"
    defect_task = tmp_path / "defect-task"
    host_task.mkdir()
    defect_task.mkdir()
    descriptor = _write_json(tmp_path / "descriptor.json", {"fixture": True})
    delivery = _write_json(
        tmp_path / "delivery.json",
        {
            "schema": "mlcc.chemical-reference-delivery.v1",
            "host": {"source": {"task_path": str(host_task.resolve())}},
            "chemical_point": None,
            "mathematical_chemical_point": {
                "mu_eV_per_atom": {"Ca": -2.0},
                "evidence_kind": "software_contract_only",
            },
        },
    )
    captured: list[tuple[Path, Path, Any, Path]] = []

    def fake_neutral(host: Path, defect: Path, point: Any, descriptor_path: Path) -> dict[str, Any]:
        captured.append((host, defect, point, descriptor_path))
        return {"fixture": True, "chemical_point_received": point}

    monkeypatch.setattr(cli, "neutral_formation_from_tasks", fake_neutral)
    exit_code = cli.main([
        "neutral-formation", "--host-task", str(host_task), "--defect-task", str(defect_task),
        "--descriptor", str(descriptor), "--output", str(tmp_path / "out.json"),
        "--chemical-reference-delivery", str(delivery),
    ])

    assert exit_code == 0
    assert captured == [(host_task, defect_task, None, descriptor)]


def test_cli_rejects_delivery_bound_to_another_host_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_task = tmp_path / "host-task"
    other_host = tmp_path / "other-host"
    defect_task = tmp_path / "defect-task"
    for path in (host_task, other_host, defect_task):
        path.mkdir()
    descriptor = _write_json(tmp_path / "descriptor.json", {"fixture": True})
    delivery = _write_json(
        tmp_path / "delivery.json",
        {
            "schema": "mlcc.chemical-reference-delivery.v1",
            "host": {"source": {"task_path": str(other_host.resolve())}},
            "chemical_point": None,
            "mathematical_chemical_point": None,
        },
    )
    called = False

    def fake_neutral(*_: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(cli, "neutral_formation_from_tasks", fake_neutral)
    with pytest.raises(SystemExit) as error:
        cli.main([
            "neutral-formation", "--host-task", str(host_task), "--defect-task", str(defect_task),
            "--descriptor", str(descriptor), "--output", str(tmp_path / "out.json"),
            "--chemical-reference-delivery", str(delivery),
        ])

    assert error.value.code == 1
    assert called is False
