from __future__ import annotations

import json
from pathlib import Path

import pytest
from ase.units import Rydberg

from mlcc.results import make_dft_result
from mlcc.tasks import TaskRecord, save_task


def make_task(tmp_path: Path, *, fixture: bool = True, state: str = "COMPLETED", exit_code: str = "0:0"):
    task_dir = tmp_path / "tasks" / "task-001"
    task_dir.mkdir(parents=True)
    source = task_dir / "running_scf.log"
    source.write_text("native log\n", encoding="utf-8")
    (task_dir / "method.json").write_text(
        json.dumps(
            {
                "smearing_method": "gauss",
                "parameters": {"smearing_sigma_eV": 0.1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "INPUT").write_text(
        "smearing_method gauss\nsmearing_sigma 0.00734986449499\n",
        encoding="utf-8",
    )
    result_path = task_dir / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "task_id": "task-001",
                "energy_eV": -12.5,
                "energy_unit": "eV",
                "energy_kind": "finite_smearing_free_energy",
                "energy_definition": "ABACUS native E_KohnSham",
                "energy_default_definition": "ABACUS native finite-smearing free energy",
                "forces_eV_per_A": [[0.1, 0.0, 0.0], [0.0, -0.2, 0.0]],
                "max_force_eV_per_A": 0.2,
                "stress_GPa": [[0.3, 0.0, 0.0], [0.0, 0.3, 0.0], [0.0, 0.0, 0.3]],
                "stress_unit": "GPa",
                "stress_sign": "abacus_printed",
                "stress_sign_calibration": "pending_finite_strain_check",
                "stress_conversion": "0.1 * raw ABACUS kBar",
                "atom_ids": [4, 9],
                "total_magnetization_muB": 1.25,
                "magnetization_status": "parsed_native_output",
                "source_files": {"running_scf.log": str(source)},
                "final_atoms": {"symbols": ["Ni", "Ni"]},
                "stage": "scf",
                "scientific_status": "converged_engineering_fixture",
                "fixture": fixture,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    task = TaskRecord(
        {
            "task_id": "task-001",
            "stage": "P4",
            "engine": "abacus",
            "engine_version": "3.10.1",
            "model_id": "ni-fcc-engineering",
            "model_version": "v001",
            "method_set": "ni-oncv-pbe18-pw-engineering-v001",
            "fixture": fixture,
            "status": "COMPLETED" if state == "COMPLETED" else state,
            "scheduler_state": state,
            "exit_code": exit_code,
            "scheduler_job_id": "32",
            "result_file": str(result_path),
            "scientific_status": "converged_engineering_fixture",
        },
        task_dir / "task.json",
    )
    save_task(task)
    return task


def study() -> dict[str, object]:
    return {
        "study_id": "study-001",
        "case_id": "ni-fixture",
        "case_role": "engineering_fixture",
        "model": {"material": "Ni"},
    }


def static_conditions(*, smearing: float | None = 0.1) -> dict[str, object]:
    return {
        "calculation_kind": "static_dft_reference",
        "lattice_temperature_K": None,
        "reference_temperature_K": 0,
        "cell_constraint": "fixed_cell_3.52_angstrom",
        "applied_external_pressure_Pa": None,
        "electronic_smearing_eV": smearing,
        "role": "engineering_fixture",
        "production_temperature_applied": False,
    }


def static_conditions_ry(
    *, occupations: str = "smearing", smearing: float | None = 0.00734986449499
) -> dict[str, object]:
    return {
        "calculation_kind": "static_dft_reference",
        "lattice_temperature_K": None,
        "reference_temperature_K": 0,
        "applied_external_pressure_Pa": None,
        "cell_constraint": "fixed_cell",
        "occupations": occupations,
        "electronic_smearing_Ry": smearing,
    }


def test_make_dft_result_preserves_units_sources_and_native_conventions(tmp_path: Path):
    task = make_task(tmp_path)

    result = make_dft_result(task, study(), static_conditions())

    assert result["study"]["study_id"] == "study-001"
    assert result["engine"] == "abacus"
    assert result["engine_version"] == "3.10.1"
    assert result["method_set"] == "ni-oncv-pbe18-pw-engineering-v001"
    assert result["model_refs"] == {"model_id": "ni-fcc-engineering", "version": "v001"}
    assert result["scheduler"]["job_id"] == "32"
    assert result["scheduler"]["exit_code"] == "0:0"
    assert result["scientific_status"] == "converged_engineering_fixture"
    assert result["design_assessment"] == "not_assessed"
    assert result["validity_domain"] == "engineering_fixture_only"
    assert result["uncertainty"] is None
    assert result["source_tasks"] == ["task-001"]
    assert result["observables"]["energy"]["unit"] == "eV"
    assert result["observables"]["energy"]["value"] == -12.5
    assert result["observables"]["forces"]["unit"] == "eV/angstrom"
    assert result["observables"]["forces"]["atom_ids"] == [4, 9]
    assert result["observables"]["stress"]["unit"] == "GPa"
    assert result["observables"]["stress"]["convention"] == "abacus_printed"
    assert result["method"]["native"]["energy_definition"] == "ABACUS native E_KohnSham"
    assert result["observables"]["magnetic_moment"]["value"] == 1.25
    assert result["source_artifacts"]["source_files"]["running_scf.log"].endswith("running_scf.log")


def test_design_spec_is_insufficient_and_unqualified_method_is_explicit(tmp_path: Path):
    task = make_task(tmp_path, fixture=False)
    task.set(study_id=study()["study_id"])

    result = make_dft_result(
        task,
        {**study(), "design_requirements_ref": "targets.json"},
        static_conditions(),
    )

    assert result["design_assessment"] == "insufficient_evidence"
    assert result["validity_domain"] == "unqualified_method"


def test_missing_observables_are_null_and_never_zero_filled(tmp_path: Path):
    task = make_task(tmp_path)
    result_path = Path(task.data["result_file"])
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    for key in ("forces_eV_per_A", "max_force_eV_per_A", "stress_GPa", "stress_unit", "total_magnetization_muB"):
        raw.pop(key, None)
    result_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    result = make_dft_result(task, study(), static_conditions())

    assert result["observables"]["forces"]["value"] is None
    assert result["observables"]["stress"]["value"] is None
    assert "magnetic_moment" not in result["observables"]
    assert result["observables"]["forces"]["value"] != 0
    assert result["observables"]["stress"]["value"] != 0


def test_failed_scheduler_cannot_claim_scientific_validity(tmp_path: Path):
    task = make_task(tmp_path, state="FAILED", exit_code="1:0")

    result = make_dft_result(task, study(), static_conditions())

    assert result["scientific_status"] is None
    assert result["parsed_scientific_status"] == "converged_engineering_fixture"
    assert result["scheduler"]["state"] == "FAILED"
    assert result["design_assessment"] == "not_assessed"


def test_result_requires_abacus_task(tmp_path: Path):
    task = make_task(tmp_path)
    task.set(engine="vasp")

    with pytest.raises(ValueError, match="ABACUS"):
        make_dft_result(task, study(), static_conditions())


def test_result_requires_matching_parsed_task_id(tmp_path: Path):
    task = make_task(tmp_path)
    result_path = Path(task.data["result_file"])
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    raw["task_id"] = "other-task"
    result_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="belongs to task"):
        make_dft_result(task, study(), static_conditions())


def test_result_requires_matching_task_study(tmp_path: Path):
    task = make_task(tmp_path)
    task.set(study_id="ca-zro3-pnma")

    with pytest.raises(ValueError, match="study_id"):
        make_dft_result(task, study(), static_conditions())


def test_static_result_rejects_temperature_or_pressure_conditions(tmp_path: Path):
    task = make_task(tmp_path)

    with pytest.raises(ValueError, match="temperature_K"):
        make_dft_result(task, study(), {**static_conditions(), "temperature_K": 330})
    with pytest.raises(ValueError, match="mechanical_pressure_Pa"):
        make_dft_result(task, study(), {**static_conditions(), "mechanical_pressure_Pa": 101325})
    with pytest.raises(ValueError, match="reference_temperature_K"):
        make_dft_result(task, study(), {**static_conditions(), "reference_temperature_K": 330})


def test_static_result_requires_task_calculation_conditions_to_match(tmp_path: Path):
    task = make_task(tmp_path)
    task.set(calculation_conditions=static_conditions())

    make_dft_result(task, study(), static_conditions())
    with pytest.raises(ValueError, match="calculation_conditions"):
        make_dft_result(task, study(), {**static_conditions(), "cell_constraint": "fixed_cell"})


def test_static_result_requires_method_and_native_input_smearing_match(tmp_path: Path):
    task = make_task(tmp_path)

    with pytest.raises(ValueError, match="electronic_smearing_eV"):
        make_dft_result(task, study(), static_conditions(smearing=0.2))

    (task.path.parent / "INPUT").write_text(
        "smearing_method gauss\nsmearing_sigma 0.01469972898998\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="smearing_sigma"):
        make_dft_result(task, study(), static_conditions())


def test_static_result_validates_ry_occupations_and_saved_new_contract(tmp_path: Path):
    task = make_task(tmp_path)
    conditions = static_conditions_ry()
    task.set(calculation_conditions=conditions)

    result = make_dft_result(task, study(), conditions)

    assert result["conditions"] == conditions
    assert result["source_evidence_status"] == "complete"
    assert abs(conditions["electronic_smearing_Ry"] * Rydberg - 0.1) < 1e-9

    with pytest.raises(ValueError, match="electronic_smearing_Ry"):
        make_dft_result(task, study(), {**conditions, "electronic_smearing_Ry": 0.008})


def test_static_result_does_not_fallback_to_method_sigma_when_native_sigma_missing(tmp_path: Path):
    task = make_task(tmp_path)
    (task.path.parent / "INPUT").write_text(
        "smearing_method gauss\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="native INPUT smearing_sigma"):
        make_dft_result(task, study(), static_conditions())


def test_fixed_occupations_require_null_sigma_in_native_and_conditions(tmp_path: Path):
    task = make_task(tmp_path)
    (task.path.parent / "method.json").write_text(
        json.dumps(
            {
                "occupations": "fixed",
                "smearing_method": None,
                "parameters": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (task.path.parent / "INPUT").write_text("smearing_method fixed\n", encoding="utf-8")
    conditions = static_conditions_ry(occupations="fixed", smearing=None)
    task.set(calculation_conditions=conditions)

    result = make_dft_result(task, study(), conditions)
    assert result["conditions"]["electronic_smearing_Ry"] is None

    with pytest.raises(ValueError, match="fixed occupations"):
        make_dft_result(
            task,
            study(),
            {**conditions, "electronic_smearing_Ry": 0.001},
        )


def test_legacy_ni_fixture_requires_matching_study_identity(tmp_path: Path):
    task = make_task(tmp_path)

    with pytest.raises(ValueError, match="engineering_fixture"):
        make_dft_result(task, {**study(), "case_role": "scientific_validation"}, static_conditions())
    with pytest.raises(ValueError, match="material"):
        make_dft_result(task, {**study(), "model": {"material": "CaZrO3"}}, static_conditions())

    raw = json.loads(Path(task.data["result_file"]).read_text(encoding="utf-8"))
    raw["final_atoms"]["symbols"] = ["Ni", "O"]
    Path(task.data["result_file"]).write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="only Ni"):
        make_dft_result(task, study(), static_conditions())


def test_result_without_study_id_rejects_non_ni_nonfixture_identity(tmp_path: Path):
    task = make_task(tmp_path, fixture=False)
    task.set(model_id="other-material-model")

    with pytest.raises(ValueError, match="without task study_id"):
        make_dft_result(task, study(), static_conditions())


def test_incomplete_native_source_evidence_downgrades_scientific_status(tmp_path: Path):
    task = make_task(tmp_path)
    result_path = Path(task.data["result_file"])
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    raw["source_files"] = {
        "running_scf.log": str(task.path.parent / "missing.log"),
        "result.json": str(result_path),
    }
    result_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    result = make_dft_result(task, study(), static_conditions())

    assert result["parsed_scientific_status"] == "converged_engineering_fixture"
    assert result["scientific_status"] is None
    assert result["source_evidence_status"] == "incomplete"
    assert set(result["missing_source_files"]) == {
        str(task.path.parent / "missing.log"),
        str(result_path),
    }
    assert result["source_evidence_reason"] == "parsed_result_json_source"


def test_metadata_only_source_is_not_native_dft_evidence(tmp_path: Path):
    task = make_task(tmp_path)
    metadata = task.path.parent / "STRU.atom-map.json"
    metadata.write_text(json.dumps({"atom_ids": [4, 9]}) + "\n", encoding="utf-8")
    result_path = Path(task.data["result_file"])
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    raw["source_files"] = {"STRU.atom-map.json": str(metadata)}
    result_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    result = make_dft_result(task, study(), static_conditions())

    assert result["scientific_status"] is None
    assert result["source_evidence_status"] == "incomplete"
    assert result["source_evidence_reason"] == "no_native_scf_or_relax_log"
    assert result["missing_source_files"] == []
