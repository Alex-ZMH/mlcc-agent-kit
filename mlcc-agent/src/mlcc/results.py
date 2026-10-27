"""Build a small delivery envelope from one saved DFT result.

The function in this module consumes the parser's JSON result.  It does not
parse native logs, write task history, compare engines, or turn a scheduler
failure into a scientific result.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from ase.units import Rydberg

from .tasks import TaskRecord
from .workflow import source_evidence

_STATIC_DFT_REFERENCE = "static_dft_reference"
_CONVERGED_STATUSES = {"converged", "converged_engineering_fixture"}


def _result_path(task: TaskRecord) -> Path:
    path = Path(task.data["result_file"])
    if not path.is_absolute() and task.path is not None:
        path = task.path.parent / path
    return path


def _design_assessment(study: Mapping[str, Any]) -> str:
    has_spec = (
        ("design_requirements_ref" in study and study["design_requirements_ref"] is not None)
        or ("design_requirements" in study and study["design_requirements"] is not None)
    )
    return "insufficient_evidence" if has_spec else "not_assessed"


def _validate_static_conditions(
    task: TaskRecord,
    conditions: Mapping[str, Any],
) -> None:
    if conditions.get("calculation_kind") != _STATIC_DFT_REFERENCE:
        raise ValueError("make_dft_result requires static_dft_reference conditions")

    for key in ("temperature_C", "temperature_K", "lattice_temperature_K"):
        if conditions.get(key) is not None:
            raise ValueError(f"static_dft_reference does not accept {key}")
    reference_temperature = conditions.get("reference_temperature_K")
    if reference_temperature is not None and float(reference_temperature) != 0.0:
        raise ValueError("static_dft_reference reference_temperature_K must be 0")

    for key in (
        "applied_external_pressure_Pa",
        "mechanical_pressure_Pa",
        "mechanical_pressure_GPa",
        "pressure_Pa",
        "pressure_GPa",
    ):
        if conditions.get(key) is not None:
            raise ValueError(f"static_dft_reference does not accept {key}")

def _validate_legacy_ni_identity(
    task: TaskRecord,
    study: Mapping[str, Any],
    parsed: Mapping[str, Any],
) -> None:
    if task.data.get("study_id") is not None:
        return
    if not task.data.get("fixture") or not str(task.data.get("model_id", "")).startswith("ni-"):
        raise ValueError(
            "result without task study_id requires an explicit Ni engineering fixture identity"
        )
    if study.get("case_role") != "engineering_fixture":
        raise ValueError("legacy Ni fixture requires an engineering_fixture study")
    model = study.get("model")
    if not isinstance(model, Mapping) or model.get("material") != "Ni":
        raise ValueError("legacy Ni fixture study model material must be Ni")
    final_atoms = parsed.get("final_atoms")
    symbols = final_atoms.get("symbols") if isinstance(final_atoms, Mapping) else None
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("legacy Ni fixture result must include final_atoms symbols")
    counts: dict[str, int] = {}
    for symbol in symbols:
        counts[str(symbol)] = counts.get(str(symbol), 0) + 1
    if set(counts) != {"Ni"}:
        raise ValueError("legacy Ni fixture final_atoms must contain only Ni")
    composition = model.get("composition")
    if composition is not None and dict(composition) != counts:
        raise ValueError("legacy Ni fixture model composition differs from final_atoms")


def _native_smearing(task: TaskRecord, result_path: Path) -> tuple[str, float | None]:
    task_dir = task.path.parent if task.path is not None else result_path.parent
    method_path = task_dir / "method.json"
    input_path = task_dir / "INPUT"
    with method_path.open("r", encoding="utf-8") as stream:
        method = json.load(stream)
    method_parameters = method["parameters"]
    method_occupations = method.get("occupations")
    method_smearing_method = method.get("smearing_method")
    if method_occupations == "fixed":
        if method_smearing_method is not None:
            raise ValueError("fixed occupations require method.json smearing_method to be null")
        method_name = "fixed"
    else:
        if method_smearing_method is None:
            raise ValueError("smearing occupations require method.json smearing_method")
        method_name = str(method_smearing_method).lower()
    method_sigma_eV = method_parameters.get("smearing_sigma_eV")
    method_sigma_Ry = method_parameters.get("smearing_sigma_Ry")
    if method_sigma_eV is not None and method_sigma_Ry is not None and not math.isclose(
        float(method_sigma_eV), float(method_sigma_Ry) * Rydberg, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise ValueError("method.json smearing_sigma_eV and smearing_sigma_Ry differ")
    input_text = input_path.read_text(encoding="utf-8")
    method_match = re.search(r"^\s*smearing_method\s+(?P<value>[^\s#]+)", input_text, re.MULTILINE)
    sigma_match = re.search(r"^\s*smearing_sigma\s+(?P<value>[^\s#]+)", input_text, re.MULTILINE)
    input_name = method_match.group("value").lower() if method_match else None
    input_sigma_Ry = float(sigma_match.group("value")) if sigma_match else None
    if input_name != method_name:
        raise ValueError("method.json and native INPUT smearing_method differ")

    if method_name == "fixed":
        if method_sigma_eV is not None or method_sigma_Ry is not None or input_sigma_Ry is not None:
            raise ValueError("fixed occupations require null smearing sigma")
        return method_name, None

    if input_sigma_Ry is None:
        raise ValueError("native INPUT smearing_sigma is required for non-fixed occupations")
    if method_sigma_eV is None and method_sigma_Ry is None:
        raise ValueError("method.json smearing sigma is required for non-fixed occupations")
    native_sigma_eV = input_sigma_Ry * Rydberg
    if method_sigma_eV is not None and not math.isclose(
        float(method_sigma_eV), native_sigma_eV, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise ValueError("method.json and native INPUT smearing_sigma differ")
    if method_sigma_Ry is not None and not math.isclose(
        float(method_sigma_Ry), input_sigma_Ry, rel_tol=1e-9, abs_tol=1e-12
    ):
        raise ValueError("method.json and native INPUT smearing_sigma differ")
    return method_name, native_sigma_eV


def _source_evidence(
    result_path: Path,
    parsed: Mapping[str, Any],
    *,
    engine: str,
) -> tuple[str, list[str], str]:
    _sources, invalid, reason = source_evidence(parsed, result_path, engine=engine)
    if reason == "no_source_files":
        return "missing", [], reason
    if reason == "complete":
        return "complete", [], reason
    return "incomplete", [str(source) for source in invalid], reason


def _observable(
    value: Any,
    unit: str | None,
    result_path: Path,
    **metadata: Any,
) -> dict[str, Any]:
    observable = {
        "value": value,
        "unit": unit,
        "data_file": str(result_path),
    }
    observable.update(metadata)
    return observable


def make_dft_result(
    task: TaskRecord,
    study: Mapping[str, Any],
    conditions: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a delivery envelope for one already parsed ABACUS DFT result."""

    result_path = _result_path(task)
    with result_path.open("r", encoding="utf-8") as stream:
        parsed = json.load(stream)

    if task.data["engine"] != "abacus":
        raise ValueError("make_dft_result requires an ABACUS task")
    if parsed["task_id"] != task.task_id:
        raise ValueError(
            f"parsed result belongs to task {parsed['task_id']!r}, expected {task.task_id!r}"
        )
    task_study_id = task.data.get("study_id")
    if task_study_id is not None and study.get("study_id") != task_study_id:
        raise ValueError(
            f"task study_id {task_study_id!r} does not match study {study.get('study_id')!r}"
        )
    _validate_static_conditions(task, conditions)
    _validate_legacy_ni_identity(task, study, parsed)

    electronic_smearing_eV = conditions.get("electronic_smearing_eV")
    electronic_smearing_Ry = conditions.get("electronic_smearing_Ry")
    occupations = conditions.get("occupations")
    native_smearing_method = None
    native_smearing_eV = None
    if occupations is not None or electronic_smearing_eV is not None or electronic_smearing_Ry is not None:
        native_smearing_method, native_smearing_eV = _native_smearing(task, result_path)
        if occupations is not None:
            if occupations not in {"smearing", "fixed"}:
                raise ValueError("occupations must be smearing or fixed")
            if (occupations == "fixed") != (native_smearing_method == "fixed"):
                raise ValueError("task occupations do not match native INPUT smearing_method")
        if native_smearing_method == "fixed":
            if electronic_smearing_eV is not None or electronic_smearing_Ry is not None:
                raise ValueError("fixed occupations require null electronic smearing")
        else:
            if native_smearing_eV is None:
                raise ValueError("non-fixed occupations require a native smearing sigma")
            if electronic_smearing_eV is not None and not math.isclose(
                float(electronic_smearing_eV), native_smearing_eV, rel_tol=1e-9, abs_tol=1e-9
            ):
                raise ValueError("electronic_smearing_eV does not match method.json and native INPUT")
            if electronic_smearing_Ry is not None and not math.isclose(
                float(electronic_smearing_Ry), native_smearing_eV / Rydberg, rel_tol=1e-9, abs_tol=1e-12
            ):
                raise ValueError("electronic_smearing_Ry does not match method.json and native INPUT")

    saved_conditions = task.data.get("calculation_conditions")
    if saved_conditions is not None and dict(saved_conditions) != dict(conditions):
        raise ValueError("task calculation_conditions do not match result conditions")

    native_success = (
        task.data.get("scheduler_state") == "COMPLETED"
        and task.data.get("exit_code") == "0:0"
    )
    parsed_scientific_status = parsed.get("scientific_status", task.data.get("scientific_status"))
    source_files = dict(parsed.get("source_files", {}))
    source_evidence_status, missing_source_files, source_evidence_reason = _source_evidence(
        result_path,
        parsed,
        engine=task.data["engine"],
    )
    study_identity = {
        key: study.get(key)
        for key in ("study_id", "case_id", "case_role")
        if key in study
    }
    if "model" in study:
        study_identity.update(
            {
                "material": study["model"].get("material"),
                "phase_requested": study["model"].get("phase_requested"),
            }
        )
    model_refs = {
        "model_id": task.data.get("model_id"),
        "version": task.data.get("model_version"),
    }
    method_info = {
        "engine": task.data.get("engine"),
        "engine_version": task.data.get("engine_version"),
        "method_set": task.data.get("method_set"),
        "model_refs": model_refs,
        "native": {
            "energy_kind": parsed.get("energy_kind"),
            "energy_default_definition": parsed.get("energy_default_definition"),
            "energy_definition": parsed.get("energy_definition"),
            "energy_definitions": parsed.get("energy_definitions"),
            "energy_sigma0_eV": parsed.get("energy_sigma0_eV"),
            "entropy_minus_TS_eV": parsed.get("entropy_minus_TS_eV"),
            "stress_unit": parsed.get("stress_unit"),
            "stress_sign": parsed.get("stress_sign"),
            "stress_sign_calibration": parsed.get("stress_sign_calibration"),
            "stress_conversion": parsed.get("stress_conversion"),
            "stress_tensor_convention": parsed.get("stress_tensor_convention"),
            "stress_voigt_order": parsed.get("stress_voigt_order"),
            "atom_ids": parsed.get("atom_ids"),
            "stage": parsed.get("stage"),
        },
    }
    observables = {
        "energy": _observable(
            parsed.get("energy_eV"),
            parsed.get("energy_unit"),
            result_path,
            energy_kind=parsed.get("energy_kind"),
            definition=parsed.get("energy_definition"),
            default_definition=parsed.get("energy_default_definition"),
        ),
        "forces": _observable(
            parsed.get("forces_eV_per_A"),
            "eV/angstrom" if "forces_eV_per_A" in parsed else None,
            result_path,
            atom_ids=parsed.get("atom_ids"),
            max_force_eV_per_A=parsed.get("max_force_eV_per_A"),
        ),
        "stress": _observable(
            parsed.get("stress_GPa"),
            parsed.get("stress_unit"),
            result_path,
            convention=parsed.get("stress_sign"),
            sign_calibration=parsed.get("stress_sign_calibration"),
            conversion=parsed.get("stress_conversion"),
        ),
    }
    magnetization = parsed.get("total_magnetization_muB")
    if magnetization is not None:
        observables["magnetic_moment"] = _observable(
            magnetization,
            "mu_B",
            result_path,
            status=parsed.get("magnetization_status"),
        )

    return {
        "result_id": task.task_id,
        "study": study_identity,
        "conditions": dict(conditions),
        "task_id": task.task_id,
        "stage": parsed.get("stage", task.data.get("stage")),
        "engine": task.data.get("engine"),
        "engine_version": task.data.get("engine_version"),
        "method_set": task.data.get("method_set"),
        "model_refs": model_refs,
        "method": method_info,
        "scheduler": {
            "job_id": task.scheduler_job_id,
            "status": task.data.get("status"),
            "state": task.data.get("scheduler_state"),
            "exit_code": task.data.get("exit_code"),
        },
        "scientific_status": (
            parsed_scientific_status
            if native_success
            and (
                parsed_scientific_status not in _CONVERGED_STATUSES
                or source_evidence_status == "complete"
            )
            else None
        ),
        "parsed_scientific_status": parsed_scientific_status,
        "source_evidence_status": source_evidence_status,
        "source_evidence_reason": source_evidence_reason,
        "missing_source_files": missing_source_files,
        "design_assessment": _design_assessment(study),
        "validity_domain": (
            "engineering_fixture_only"
            if task.data.get("fixture") or parsed.get("fixture")
            else "unqualified_method"
        ),
        "uncertainty": None,
        "source_tasks": [task.task_id],
        "source_artifacts": {
            "result_file": str(result_path),
            "source_files": source_files,
        },
        "observables": observables,
    }
