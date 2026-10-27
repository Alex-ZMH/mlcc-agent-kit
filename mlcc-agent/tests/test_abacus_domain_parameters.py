from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc.abacus_domain_parameters import build_abacus_domain_parameters


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _case(tmp_path: Path, *, electronic_path: str | None = "electronic.json") -> Path:
    model = tmp_path / "model"
    _write(
        model / "model.json",
        {
            "schema": "mlcc.model.v1",
            "model_id": "batio3-j6-host",
            "version": "v001",
            "material": "BaTiO3",
            "element_order": ["Ba", "Ti", "O"],
            "atom_ids": [0, 1, 2],
        },
    )
    study = _write(
        tmp_path / "study.json",
        {
            "schema": "mlcc.study.v1",
            "study_id": "bto-j6-host-study",
            "case_id": "bto_j6_host_scf",
            "case_role": "scientific_validation",
            "model": {"model_id": "batio3-j6-host", "version": "v001"},
        },
    )
    task_dir = tmp_path / "task"
    task = _write(
        task_dir / "task.json",
        {
            "task_id": "bto-j6-host-scf-v001",
            "engine": "abacus",
            "engine_version": "3.10.1",
            "calculation": "scf",
            "model_id": "batio3-j6-host",
            "model_version": "v001",
            "study_id": "bto-j6-host-study",
            "case_id": "bto_j6_host_scf",
            "method_set": "bto-j6-scf11-v001",
            "scheduler_job_id": "j6-100",
            "scheduler_state": "COMPLETED",
            "status": "COMPLETED",
            "exit_code": "0:0",
            "basis_type": "lcao",
            "net_charge": 0,
            "nelec": 0,
            "nelec_delta": 0,
            "calculation_conditions": {"cell_constraint": "fixed_cell", "occupations": "fixed"},
        },
    )
    result = _write(
        task_dir / "result.json",
        {
            "task_id": "bto-j6-host-scf-v001",
            "scheduler_job_id": "j6-100",
            "model_id": "batio3-j6-host",
            "version": "v001",
            "method_set": "bto-j6-scf11-v001",
            "study_id": "bto-j6-host-study",
            "case_id": "bto_j6_host_scf",
            "energy_eV": -123.4,
            "energy_definition": "ABACUS native E_KohnSham",
            "forces_eV_per_A": [[0.1, 0.2, 0.3], [0.0, 0.0, 0.0], [-0.1, -0.2, -0.3]],
            "stress_GPa": [[1.0, 0.1, 0.0], [0.1, 2.0, 0.0], [0.0, 0.0, 3.0]],
            "stress_unit": "GPa",
            "stress_sign": "abacus_printed",
            "atom_ids": [0, 1, 2],
            "scientific_status": "not_converged",
            "electronic_converged": False,
            "ionic_converged": None,
            "native_completed": True,
            "production_qualification": False,
            "scientific_qualification": False,
            "source_files": {"STRU.atom-map.json": str(task_dir / "STRU.atom-map.json")},
        },
    )
    _write(task_dir / "STRU.atom-map.json", {"schema": "fixture-map"})
    if electronic_path is not None:
        _write(
            tmp_path / electronic_path,
            {
                "schema": "mlcc.abacus-electronic.v001",
                "task_id": "bto-j6-host-scf-v001",
                "scheduler_job_id": "j6-100",
                "method_set": "bto-j6-scf11-v001",
                "model_id": "batio3-j6-host",
                "model_version": "v001",
                "electron_count_native": 320.0,
                "sampled_mesh_KS_gap_eV": 1.7,
                "electronic_converged": True,
                "native_completed": True,
                "gap_status": "sampled_mesh_KS_gap",
                "source_files": {"istate.info": str(task_dir / "istate.info")},
            },
        )
    return _write(
        tmp_path / "request.json",
        {
            "schema": "mlcc.abacus-domain-parameters-request.v1",
            "model_path": str(model),
            "study_path": str(study),
            "task_path": str(task),
            "result_path": str(result),
            "electronic_path": None if electronic_path is None else str(tmp_path / electronic_path),
        },
    )


def test_saved_abacus_values_keep_source_order_and_unconverged_status(tmp_path: Path) -> None:
    product = build_abacus_domain_parameters(_case(tmp_path))

    assert product["schema"] == "mlcc.domain-parameters.v1"
    assert product["kind"] == "abacus_domain_parameters"
    properties = {item["name"]: item for item in product["properties"]}
    assert properties["total_energy"]["value"] == pytest.approx(-123.4)
    assert properties["source_order_forces"]["shape"] == [3, 3]
    assert properties["native_stress"]["value"][0][0] == pytest.approx(1.0)
    assert properties["native_stress"]["conditions"]["stress_sign"] == "abacus_printed"
    assert properties["native_electron_count"]["value"] == pytest.approx(320.0)
    assert properties["sampled_mesh_KS_gap"]["value"] == pytest.approx(1.7)
    assert properties["total_energy"]["conditions"]["native"]["scientific_status"] == "not_converged"


def test_missing_electronic_product_is_explicitly_unresolved(tmp_path: Path) -> None:
    product = build_abacus_domain_parameters(_case(tmp_path, electronic_path=None))
    properties = {item["name"]: item for item in product["properties"]}

    assert product["execution"]["electronic_path"] is None
    assert properties["native_electron_count"]["value"] is None
    assert properties["native_electron_count"]["status"] == "unresolved"
    assert properties["native_electron_count"]["conditions"]["unresolved_reason"] == "electronic_path_not_provided"
    assert properties["sampled_mesh_KS_gap"]["status"] == "unresolved"


def test_result_identity_or_shape_mismatch_is_rejected(tmp_path: Path) -> None:
    request = _case(tmp_path)
    result_path = tmp_path / "task" / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["forces_eV_per_A"] = [[0.0, 0.0, 0.0]]
    result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="forces_eV_per_A"):
        build_abacus_domain_parameters(request)
