"""P12 property delivery and explicit design-target comparison.

The comparison function consumes already qualified scientific observables.  It
does not qualify a method, convert units, interpolate conditions, or infer a
target.  The electronic delivery function re-reads the native ABACUS task and
keeps the resulting scalar values and provenance separate from the design
assessment.
"""

from __future__ import annotations

import json
import math
import copy
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .electronic import read_abacus_electronic_task
from .berry_results import read_berry_task
from .dielectric_response import _model_context


_ASSESSMENTS = {"met", "not_met", "insufficient_evidence", "not_assessed", "not_applicable"}


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {source}")
    return value


def _records(value: Any, field: str) -> list[Mapping[str, Any]]:
    """Read the explicit list contract; ``None`` means no records."""

    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of objects")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"each {field} entry must be an object")
        result.append(item)
    return result


def _observable_id(record: Mapping[str, Any]) -> Any:
    return record.get("observable_id")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _has_source_refs(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(reference, str) and bool(reference.strip()) for reference in value)


def _target_interval(requirement: Mapping[str, Any]) -> tuple[float | None, float | None, str | None, str | None]:
    """Return lower, upper, comparison name, and a missing/invalid reason."""

    comparison = requirement.get("comparison")
    if comparison not in {"upper_bound", "lower_bound", "interval", "target_with_tolerance"}:
        return None, None, None, "comparison is missing or unsupported"

    if comparison == "upper_bound":
        value = requirement.get("upper_bound")
        if value is None:
            return None, None, comparison, "upper_bound is not provided"
        if not _finite_number(value):
            return None, None, comparison, "upper_bound must be finite"
        return None, float(value), comparison, None

    if comparison == "lower_bound":
        value = requirement.get("lower_bound")
        if value is None:
            return None, None, comparison, "lower_bound is not provided"
        if not _finite_number(value):
            return None, None, comparison, "lower_bound must be finite"
        return float(value), None, comparison, None

    if comparison == "target_with_tolerance":
        target = requirement.get("target")
        tolerance = requirement.get("tolerance")
        if target is None or tolerance is None:
            if target is None and tolerance is None:
                return None, None, comparison, "target and tolerance are not provided"
            return None, None, comparison, "target and tolerance are both required"
        if not _finite_number(target) or not _finite_number(tolerance) or float(tolerance) < 0.0:
            return None, None, comparison, "target and tolerance must be finite with non-negative tolerance"
        target_value = float(target)
        tolerance_value = float(tolerance)
        return target_value - tolerance_value, target_value + tolerance_value, comparison, None

    lower = requirement.get("lower_bound")
    upper = requirement.get("upper_bound")
    if lower is None or upper is None:
        if lower is None and upper is None:
            return None, None, comparison, "interval bounds are not provided"
        return None, None, comparison, "interval requires lower_bound and upper_bound"
    if not _finite_number(lower) or not _finite_number(upper):
        return None, None, comparison, "interval bounds must be finite"
    lower_value = float(lower)
    upper_value = float(upper)
    if lower_value > upper_value:
        return None, None, comparison, "interval lower_bound exceeds upper_bound"
    return lower_value, upper_value, comparison, None


def _metadata_mismatch(
    requirement: Mapping[str, Any], observable: Mapping[str, Any]
) -> str | None:
    required_fields = ("definition", "object_level", "unit", "conditions")
    for field in required_fields:
        if field not in requirement:
            return f"requirement {field} is missing"
        if field not in observable:
            return f"observable {field} is missing"
        if field == "conditions":
            if not isinstance(requirement[field], Mapping) or not isinstance(observable[field], Mapping):
                return "conditions must be dictionaries"
        elif (
            not isinstance(requirement[field], str)
            or not requirement[field].strip()
            or not isinstance(observable[field], str)
            or not observable[field].strip()
        ):
            return f"{field} must be a non-empty string"
        if requirement[field] != observable[field]:
            return f"{field} does not exactly match"
    return None


def _validate_requirement(requirement: Mapping[str, Any]) -> None:
    observable_id = requirement.get("observable_id")
    if not isinstance(observable_id, str) or not observable_id.strip():
        raise ValueError("requirement observable_id must be a non-empty string")
    for field in ("definition", "object_level", "unit"):
        value = requirement.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"requirement {field} must be a non-empty string")
    if not isinstance(requirement.get("conditions"), Mapping):
        raise ValueError("requirement conditions must be a dictionary")
    if "required" not in requirement or not isinstance(requirement["required"], bool):
        raise ValueError("requirement required must be an explicit boolean")
    if "uncertainty_rule" not in requirement or requirement["uncertainty_rule"] not in {
        "nominal",
        "whole_interval",
    }:
        raise ValueError("requirement uncertainty_rule must be nominal or whole_interval")
    if requirement.get("comparison") not in {
        "upper_bound",
        "lower_bound",
        "interval",
        "target_with_tolerance",
    }:
        raise ValueError("requirement comparison must be explicit and supported")


def _find_observable(
    requirement: Mapping[str, Any], observables: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any] | None, str | None]:
    requested_id = _observable_id(requirement)
    if not isinstance(requested_id, str) or not requested_id.strip():
        return None, "requirement observable_id is missing"
    candidates = [item for item in observables if _observable_id(item) == requested_id]
    if not candidates:
        return None, f"observable {requested_id!r} is missing"
    matches = [candidate for candidate in candidates if _metadata_mismatch(requirement, candidate) is None]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, f"observable {requested_id!r} has ambiguous duplicate matches"
    return None, f"observable {requested_id!r} metadata or conditions do not exactly match"


def _assessment_item_base(
    requirement: Mapping[str, Any], observable: Mapping[str, Any] | None
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "requirement_id": requirement.get("requirement_id"),
        "observable_id": _observable_id(requirement),
        "required": requirement["required"],
        "comparison": requirement["comparison"],
        "uncertainty_rule": requirement["uncertainty_rule"],
        "design_assessment": "insufficient_evidence",
        "reason": None,
        "margin": None,
        "nominal_margin": None,
        "whole_interval_margin": None,
        "target_interval": None,
        "value": None,
        "uncertainty": None,
        "scientific_status": None,
        "source_refs": [],
    }
    if observable is not None:
        for field in ("value", "uncertainty", "unit", "conditions", "scientific_status", "source_refs"):
            item[field] = observable.get(field)
    return item


def _evaluate_interval(
    value: float,
    uncertainty: float | None,
    lower: float | None,
    upper: float | None,
    comparison: str,
    uncertainty_rule: str,
) -> tuple[str, str, Any, Any, Any]:
    nominal_lower = value
    nominal_upper = value
    if uncertainty_rule == "nominal":
        interval_lower = value
        interval_upper = value
    elif uncertainty_rule == "whole_interval":
        if uncertainty is None:
            return (
                "insufficient_evidence",
                "whole_interval requires a numeric uncertainty",
                None,
                None,
                None,
            )
        interval_lower = value - uncertainty
        interval_upper = value + uncertainty
    else:
        return "insufficient_evidence", "uncertainty_rule must be nominal or whole_interval", None, None, None

    nominal_margin: Any
    interval_margin: Any
    if comparison == "upper_bound":
        assert upper is not None
        nominal_margin = upper - nominal_upper
        interval_margin = upper - interval_upper
        if interval_upper <= upper:
            return "met", "value interval is within the upper bound", nominal_margin, interval_margin, [interval_lower, interval_upper]
        if interval_lower > upper:
            return "not_met", "value interval is above the upper bound", nominal_margin, interval_margin, [interval_lower, interval_upper]
        return "insufficient_evidence", "uncertainty interval crosses the upper bound", nominal_margin, interval_margin, [interval_lower, interval_upper]
    if comparison == "lower_bound":
        assert lower is not None
        nominal_margin = nominal_lower - lower
        interval_margin = interval_lower - lower
        if interval_lower >= lower:
            return "met", "value interval is within the lower bound", nominal_margin, interval_margin, [interval_lower, interval_upper]
        if interval_upper < lower:
            return "not_met", "value interval is below the lower bound", nominal_margin, interval_margin, [interval_lower, interval_upper]
        return "insufficient_evidence", "uncertainty interval crosses the lower bound", nominal_margin, interval_margin, [interval_lower, interval_upper]

    assert lower is not None and upper is not None
    nominal_margin = {"lower": value - lower, "upper": upper - value}
    interval_margin = {"lower": interval_lower - lower, "upper": upper - interval_upper}
    if interval_lower >= lower and interval_upper <= upper:
        return "met", "value interval is within the target interval", nominal_margin, interval_margin, [interval_lower, interval_upper]
    if interval_upper < lower or interval_lower > upper:
        return "not_met", "value interval is outside the target interval", nominal_margin, interval_margin, [interval_lower, interval_upper]
    return "insufficient_evidence", "uncertainty interval crosses a target boundary", nominal_margin, interval_margin, [interval_lower, interval_upper]


def _aggregate_assessment(items: Sequence[Mapping[str, Any]], has_targets: bool) -> tuple[str, str]:
    if not has_targets:
        return "not_assessed", "no design targets were provided"
    required = [item for item in items if item.get("required")]
    if not required:
        return "not_assessed", "no required design targets were provided"
    if any(item.get("design_assessment") == "not_met" for item in required):
        return "not_met", "at least one required observable is valid and outside its target"
    if any(item.get("design_assessment") == "insufficient_evidence" for item in required):
        return "insufficient_evidence", "at least one required observable lacks qualified evidence"
    if any(item.get("design_assessment") == "not_assessed" for item in required):
        return "not_assessed", "at least one required target has no usable threshold"
    if all(item.get("design_assessment") == "not_applicable" for item in required):
        return "not_applicable", "all required targets were explicitly marked not applicable"
    if all(item.get("design_assessment") == "met" for item in required):
        return "met", "all required observables are within their qualified targets"
    return "insufficient_evidence", "required target set is incomplete"


def assess_design(
    requirements: Any,
    observables: Any,
) -> dict[str, Any]:
    """Compare explicitly matched observables with per-study requirements.

    A ``qualified`` scientific status must already have been granted by an
    upstream method/physics qualification.  This function only compares
    numbers and records the resulting evidence state.
    """

    requirement_records = _records(requirements, "requirements")
    observable_records = _records(observables, "observables")
    has_targets = bool(requirement_records)
    assessments: list[dict[str, Any]] = []
    for requirement in requirement_records:
        _validate_requirement(requirement)
        item: dict[str, Any]
        explicit_not_applicable = requirement.get("not_applicable") is True or requirement.get("applicability") == "not_applicable"
        if explicit_not_applicable:
            item = _assessment_item_base(requirement, None)
            item.update(design_assessment="not_applicable", reason="requirement explicitly marked not applicable")
            assessments.append(item)
            continue

        observable, match_reason = _find_observable(requirement, observable_records)
        item = _assessment_item_base(requirement, observable)
        lower, upper, comparison, target_reason = _target_interval(requirement)
        item["comparison"] = comparison
        if target_reason is not None:
            if (
                target_reason.endswith("is not provided")
                or target_reason.endswith("are not provided")
                or target_reason == "comparison is missing or unsupported"
            ):
                item.update(design_assessment="not_assessed", reason=target_reason)
            else:
                item.update(design_assessment="insufficient_evidence", reason=target_reason)
            assessments.append(item)
            continue
        item["target_interval"] = [lower, upper]
        if match_reason is not None:
            item.update(design_assessment="insufficient_evidence", reason=match_reason)
            assessments.append(item)
            continue

        assert observable is not None
        if "value" not in observable or observable.get("value") is None or not _finite_number(observable.get("value")):
            item.update(design_assessment="insufficient_evidence", reason="observable value is missing or non-finite")
            assessments.append(item)
            continue
        if "uncertainty" not in observable:
            item.update(design_assessment="insufficient_evidence", reason="observable uncertainty must be numeric or explicit None")
            assessments.append(item)
            continue
        uncertainty_value = observable.get("uncertainty")
        if uncertainty_value is not None and (not _finite_number(uncertainty_value) or float(uncertainty_value) < 0.0):
            item.update(design_assessment="insufficient_evidence", reason="observable uncertainty must be non-negative")
            assessments.append(item)
            continue
        if not _has_source_refs(observable.get("source_refs")):
            item.update(design_assessment="insufficient_evidence", reason="observable source_refs are missing")
            assessments.append(item)
            continue
        scientific_status = observable.get("scientific_status")
        if scientific_status != "qualified":
            reason = "scientific result is not qualified"
            if scientific_status == "invalid":
                reason = "scientific result is invalid and cannot establish not_met"
            item.update(design_assessment="insufficient_evidence", reason=reason)
            assessments.append(item)
            continue

        item["uncertainty"] = None if uncertainty_value is None else float(uncertainty_value)
        assert comparison is not None
        uncertainty_rule = requirement["uncertainty_rule"]
        status, reason, nominal_margin, interval_margin, evidence_interval = _evaluate_interval(
            float(observable["value"]),
            None if uncertainty_value is None else float(uncertainty_value),
            lower,
            upper,
            comparison,
            uncertainty_rule,
        )
        item.update(
            design_assessment=status,
            reason=reason,
            value=float(observable["value"]),
            scientific_status=scientific_status,
            source_refs=observable.get("source_refs"),
            nominal_margin=nominal_margin,
            whole_interval_margin=interval_margin,
            margin=interval_margin if uncertainty_rule == "whole_interval" else nominal_margin,
            evidence_interval=evidence_interval,
        )
        assessments.append(item)

    overall, aggregate_reason = _aggregate_assessment(assessments, has_targets)
    summary = {status: sum(item["design_assessment"] == status for item in assessments) for status in _ASSESSMENTS}
    return {
        "schema": "mlcc.design-assessment.v001",
        "design_assessment": overall,
        "reason": aggregate_reason,
        "assessments": assessments,
        "required_assessments": [item for item in assessments if item["required"]],
        "summary": summary,
        "targets_provided": has_targets,
    }


def _task_records(task_paths: str | Path | Sequence[str | Path]) -> list[Path]:
    if isinstance(task_paths, (str, Path)):
        values: Sequence[str | Path] = [task_paths]
    else:
        values = task_paths
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise ValueError("task_paths must contain at least one ABACUS task path")
    return [Path(value).expanduser().resolve() for value in values]


def _legacy_ni_binding(task: Mapping[str, Any], study: Mapping[str, Any]) -> bool:
    model = study.get("model")
    return (
        task.get("study_id") is None
        and task.get("fixture") is True
        and study.get("case_role") == "engineering_fixture"
        and isinstance(model, Mapping)
        and model.get("material") == "Ni"
    )


def _bind_task(task: Mapping[str, Any], study: Mapping[str, Any], task_path: Path) -> None:
    study_id = study.get("study_id")
    if task.get("study_id") != study_id and not _legacy_ni_binding(task, study):
        raise ValueError(f"task study_id {task.get('study_id')!r} does not match study {study_id!r}: {task_path}")
    model = study.get("model")
    if not isinstance(model, Mapping):
        raise ValueError("study.model is required for electronic property delivery")
    for task_field, study_field in (("model_id", "model_id"), ("model_version", "version")):
        expected = model.get(study_field)
        if expected is not None and task.get(task_field) != expected:
            raise ValueError(
                f"task {task_field} {task.get(task_field)!r} does not match study model {expected!r}: {task_path}"
            )
    if study.get("case_id") is not None and task.get("case_id") not in (None, study.get("case_id")):
        raise ValueError(f"task case_id does not match study: {task_path}")


def _static_conditions(task: Mapping[str, Any], task_path: Path) -> dict[str, Any]:
    conditions = task.get("calculation_conditions")
    if not isinstance(conditions, Mapping):
        raise ValueError(f"task calculation_conditions are required: {task_path}")
    if conditions.get("calculation_kind") != "static_dft_reference":
        raise ValueError(f"electronic property delivery requires static_dft_reference: {task_path}")
    if conditions.get("reference_temperature_K") not in (0, 0.0):
        raise ValueError(f"electronic property delivery requires static 0 K reference conditions: {task_path}")
    for field in (
        "temperature_C",
        "temperature_K",
        "lattice_temperature_K",
        "applied_external_pressure_Pa",
        "mechanical_pressure_Pa",
        "mechanical_pressure_GPa",
        "pressure_Pa",
        "pressure_GPa",
    ):
        if conditions.get(field) is not None:
            raise ValueError(f"static_dft_reference does not accept {field}: {task_path}")
    return dict(conditions)


def _qualified_status(task: Mapping[str, Any], electronic: Mapping[str, Any]) -> str:
    task_status = task.get("scientific_status")
    qualification = electronic.get("qualification")
    precision = qualification.get("scientific_precision_qualified") if isinstance(qualification, Mapping) else None
    if task_status == "qualified" and precision is True:
        return "qualified"
    return "unqualified"


def _property_record(
    observable_id: str,
    definition: str,
    value: Any,
    *,
    conditions: Mapping[str, Any],
    scientific_status: str,
    task: Mapping[str, Any],
    electronic: Mapping[str, Any],
    task_path: Path,
) -> dict[str, Any]:
    source_files = electronic.get("source_files")
    if not isinstance(source_files, Mapping):
        raise ValueError(f"electronic source_files are required: {task_path}")
    source_refs = [
        f"task:{task['task_id']}",
        f"scheduler_job:{task['scheduler_job_id']}",
        f"method:{task['method_set']}",
        str(task_path / "task.json"),
        str(task_path / "method.json"),
        str(task_path / "result.json"),
    ]
    source_refs.extend(str(path) for path in source_files.values() if isinstance(path, str))
    return {
        "observable_id": observable_id,
        "definition": definition,
        "object_level": "bulk_model_cell",
        "unit": "eV",
        "conditions": dict(conditions),
        "value": value,
        "uncertainty": None,
        "scientific_status": scientific_status,
        "source_refs": source_refs,
        "source_task": task["task_id"],
        "scheduler_job_id": task["scheduler_job_id"],
        "method_set": task["method_set"],
        "model_refs": {"model_id": task.get("model_id"), "version": task.get("model_version")},
        "source_files": dict(source_files),
        "upstream_scientific_status": task.get("scientific_status"),
        "task_path": str(task_path),
    }


def deliver_electronic_properties(
    study_path: str | Path,
    task_paths: str | Path | Sequence[str | Path],
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Re-read completed ABACUS tasks and deliver scalar electronic properties."""

    study = _read_json(study_path)
    if not isinstance(study.get("study_id"), str) or not study["study_id"]:
        raise ValueError("study.study_id is required")
    design_ref = study.get("design_requirements_ref")
    has_design_ref = (
        bool(design_ref.strip())
        if isinstance(design_ref, str)
        else design_ref is not None
    )
    inline_requirements = study.get("design_requirements")
    has_inline_requirements = inline_requirements not in (None, "", [], {})
    if targets_path is None and (has_design_ref or has_inline_requirements):
        raise ValueError("study has design requirements; targets_path must be explicit")
    paths = _task_records(task_paths)
    observables: list[dict[str, Any]] = []
    task_refs: list[dict[str, Any]] = []
    static_conditions: list[dict[str, Any]] = []
    model_refs: dict[str, Any] | None = None
    for task_path in paths:
        electronic = read_abacus_electronic_task(task_path)
        task = _read_json(task_path / "task.json")
        _bind_task(task, study, task_path)
        conditions = _static_conditions(task, task_path)
        if model_refs is None:
            model_refs = {"model_id": task.get("model_id"), "version": task.get("model_version")}
        elif model_refs != {"model_id": task.get("model_id"), "version": task.get("model_version")}:
            raise ValueError("electronic property delivery cannot mix task model identities")
        scientific_status = _qualified_status(task, electronic)
        definitions = {
            "sampled_mesh_KS_gap": electronic.get("gap_qualification", {}).get("definition", "sampled uniform-mesh Kohn-Sham gap"),
            "fermi_level": "ABACUS final Fermi level on the static SCF reference",
            "vbm": "maximum occupied level on the native uniform SCF mesh",
            "cbm": "minimum unoccupied level on the native uniform SCF mesh",
        }
        values = {
            "sampled_mesh_KS_gap": electronic.get("sampled_mesh_KS_gap_eV"),
            "fermi_level": electronic.get("fermi_level_eV"),
            "vbm": electronic.get("vbm_eV"),
            "cbm": electronic.get("cbm_eV"),
        }
        for observable_id, value in values.items():
            observables.append(
                _property_record(
                    observable_id,
                    definitions[observable_id],
                    value,
                    conditions=conditions,
                    scientific_status=scientific_status,
                    task=task,
                    electronic=electronic,
                    task_path=task_path,
                )
            )
        static_conditions.append(conditions)
        task_refs.append(
            {
                "task_id": task["task_id"],
                "scheduler_job_id": task["scheduler_job_id"],
                "method_set": task["method_set"],
                "task_path": str(task_path),
                "scientific_status": task.get("scientific_status"),
                "scheduler_state": task.get("scheduler_state", task.get("status")),
                "exit_code": task.get("exit_code"),
            }
        )

    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets.get("study_id") != study["study_id"]:
            raise ValueError("targets study_id must exactly match study")
        requirements: Any = targets.get("requirements")
    else:
        requirements = None
    assessment = assess_design(requirements, observables)
    statuses = {item["scientific_status"] for item in observables}
    aggregate_scientific_status = "qualified" if statuses == {"qualified"} else "unqualified"
    return {
        "schema": "mlcc.electronic-property-delivery.v001",
        "study_id": study["study_id"],
        "case_id": study.get("case_id"),
        "model_refs": model_refs,
        "task_refs": task_refs,
        "observables": observables,
        "static_0K_conditions": static_conditions[0] if len(static_conditions) == 1 else static_conditions,
        "scientific_status": aggregate_scientific_status,
        "design_assessment": assessment["design_assessment"],
        "design_assessment_detail": assessment,
        "targets_path": None if targets_path is None else str(Path(targets_path).expanduser().resolve()),
    }


def deliver_magnetic_properties(
    study_path: str | Path,
    product_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Bind a saved native magnetic observation to its existing Study."""
    study_file = Path(study_path).expanduser().resolve()
    product_file = Path(product_path).expanduser().resolve()
    study = _read_json(study_file)
    product = _read_json(product_file)
    if product["schema"] != "mlcc.abacus-magnetic.v001":
        raise ValueError("unsupported magnetic product schema")
    task_path = Path(product["task_path"])
    task = _read_json(task_path / "task.json")
    _bind_task(task, study, task_path)
    for field in ("task_id", "scheduler_job_id", "method_set", "model_id", "model_version"):
        if product[field] != task[field]:
            raise ValueError(f"magnetic product {field} differs from source task")
    conditions = copy.deepcopy(task.get("calculation_conditions"))
    source_refs = [str(product_file), *product["source_files"].values()]
    definitions = (
        ("total_magnetization", "total_magnetization_muB", "muB", "bulk_model_cell",
         "last native ABACUS total magnetization; see native convergence status"),
        ("mean_magnetization_per_atom", "mean_magnetization_muB_per_atom", "muB/atom", "bulk_model_cell_average",
         "cell total divided by atom count; not a local atomic magnetic moment"),
    )
    observables = [
        {
            "observable_id": name, "definition": definition, "value": product[field],
            "unit": unit, "object_level": level, "conditions": conditions,
            "status": product["status"], "scientific_status": task.get("scientific_status"),
            "source_refs": source_refs, "source_task": task["task_id"],
            "scheduler_job_id": task["scheduler_job_id"], "method_set": task["method_set"],
            "model_refs": {"model_id": task["model_id"], "version": task["model_version"]},
        }
        for name, field, unit, level, definition in definitions
    ]
    targets = None if targets_path is None else _read_json(targets_path)
    if targets is not None and targets["study_id"] != study["study_id"]:
        raise ValueError("magnetic targets differ from delivery Study")
    assessment = assess_design(None if targets is None else targets["requirements"], observables)
    return {
        "schema": "mlcc.magnetic-property-delivery.v001",
        "study_id": study["study_id"], "study_path": str(study_file),
        "case_id": study.get("case_id"), "model_refs": observables[0]["model_refs"],
        "product_path": str(product_file), "product": product,
        "status": product["status"], "observables": observables,
        "task_refs": [{key: task.get(key) for key in (
            "task_id", "scheduler_job_id", "method_set", "scheduler_state", "exit_code",
        )}],
        "source_files": copy.deepcopy(product["source_files"]),
        "calculation_conditions": conditions,
        "scientific_status": task.get("scientific_status"),
        "design_assessment": assessment["design_assessment"],
        "design_assessment_detail": assessment,
    }


def deliver_transport_properties(
    study_path: str | Path,
    product_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Deliver existing tau-normalized tensors without recomputing transport."""
    study_file = Path(study_path).expanduser().resolve()
    product_file = Path(product_path).expanduser().resolve()
    study = _read_json(study_file)
    product = _read_json(product_file)
    if product["schema"] != "mlcc.transport.v001":
        raise ValueError("unsupported transport product schema")
    task_path = Path(product["task_path"])
    task = _read_json(task_path / "task.json")
    _bind_task(task, study, task_path)
    for field in ("task_id", "scheduler_job_id", "method_set", "model_id", "model_version"):
        if product[field] != task[field]:
            raise ValueError(f"transport product {field} differs from source task")
    units = {
        "seebeck": "V/K", "sigma_over_tau": "S/(m s)",
        "kappa_e_over_tau": "W/(m K s)", "power_factor_over_tau": "W/(m K^2 s)",
    }
    if product["units"] != units:
        raise ValueError("transport product units differ from the tau-normalized tensor contract")
    conditions = {
        "temperatures_K": product["parameters"].get("temperatures_K"),
        "chemical_potentials_eV": product["parameters"].get("chemical_potentials_eV"),
        "energy_reference": product["parameters"].get("energy_reference"),
        "native_source_conditions": copy.deepcopy(task.get("calculation_conditions")),
    }
    source_refs = [str(product_file), *product["source_files"].values()]
    observables = []
    for name, unit in units.items():
        observables.append({
            "observable_id": name, "unit": unit,
            "value": None if product["tensors"] is None else product["tensors"][name],
            "axes": ["temperature", "chemical_potential", "cartesian_row", "cartesian_column"],
            "conditions": conditions, "status": product["status"],
            "scientific_status": task.get("scientific_status"),
            "source_refs": source_refs, "source_task": task["task_id"],
            "scheduler_job_id": task["scheduler_job_id"], "method_set": task["method_set"],
        })
    targets = None if targets_path is None else _read_json(targets_path)
    if targets is not None and targets["study_id"] != study["study_id"]:
        raise ValueError("transport targets differ from delivery Study")
    assessment = assess_design(None if targets is None else targets["requirements"], observables)
    return {
        "schema": "mlcc.transport-property-delivery.v001",
        "study_id": study["study_id"], "study_path": str(study_file),
        "case_id": study.get("case_id"),
        "model_refs": {"model_id": task["model_id"], "version": task["model_version"]},
        "product_path": str(product_file), "product": product,
        "status": product["status"], "missing": product["missing"],
        "observables": observables, "conditions": conditions,
        "task_refs": [{key: task.get(key) for key in (
            "task_id", "scheduler_job_id", "method_set", "scheduler_state", "exit_code",
        )}],
        "source_files": copy.deepcopy(product["source_files"]),
        "scientific_status": task.get("scientific_status"),
        "design_assessment": assessment["design_assessment"],
        "design_assessment_detail": assessment,
    }


def deliver_continuum_package(study_path: str | Path, package_path: str | Path) -> dict[str, Any]:
    """Attach an already converted parameter package to its original Study."""
    study_file, package_file = Path(study_path).resolve(), Path(package_path).resolve()
    study, package = _read_json(study_file), _read_json(package_file)
    if package["schema"] != "mlcc.continuum-parameters.v1":
        raise ValueError("unsupported continuum parameter package")
    saved_study = package["study"]
    if saved_study["study_id"] != study["study_id"]:
        raise ValueError("continuum package belongs to a different Study")
    if (saved_study["model"]["model_id"], saved_study["model"]["version"]) != (
        study["model"]["model_id"], study["model"]["version"]
    ):
        raise ValueError("continuum package model differs from Study")
    return {
        "schema": "mlcc.continuum-delivery.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(saved_study["model"]),
        "status": package["status"],
        "responses": {"continuum_parameters": package},
        "source_files": {"study": str(study_file), "package": str(package_file)},
        "design_assessment": "not_assessed",
    }


def deliver_vacancy_migration(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach saved site occupancy and path events without reading or analyzing frames."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.vacancy-migration.v1":
        raise ValueError("unsupported vacancy migration product")
    if product["study_id"] != study["study_id"]:
        raise ValueError("vacancy migration product belongs to a different Study")
    model_ref = product["model_ref"]
    if (model_ref["model_id"], model_ref["version"]) != (
        study["model"]["model_id"], study["model"]["version"]
    ):
        raise ValueError("vacancy migration model differs from Study")
    return {
        "schema": "mlcc.vacancy-migration-delivery.v1",
        "study_id": study["study_id"], "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(model_ref), "status": product["status"],
        "responses": {"vacancy_migration": product},
        "source_refs": copy.deepcopy(product["source_refs"]),
        "source_files": {"study": str(study_file), "product": str(product_file)},
        "design_assessment": "not_assessed",
    }


def deliver_composition_product(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Deliver a saved composition build, collection or comparison without recomputing."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] in {"mlcc.composition-build.v1", "mlcc.composition-configurations.v1"}:
        model_ref = product["model_ref"]
    elif product["schema"] == "mlcc.composition-comparison.v1":
        model_ref = product["baseline"]["model_ref"]
    else:
        raise ValueError("unsupported composition product")
    if product["study_id"] != study["study_id"]:
        raise ValueError("composition product belongs to a different Study")
    if (model_ref["model_id"], model_ref["version"]) != (
        study["model"]["model_id"], study["model"]["version"]
    ):
        raise ValueError("composition product reference model differs from Study")
    return {
        "schema": "mlcc.composition-delivery.v1",
        "study_id": study["study_id"],
        "case_id": study["case_id"],
        "case_role": study["case_role"],
        "model_refs": copy.deepcopy(model_ref),
        "status": product["status"],
        "responses": {"composition": product},
        "source_refs": copy.deepcopy(product["source_refs"]),
        "source_files": {"study": str(study_file), "product": str(product_file)},
        "design_assessment": "not_assessed",
    }


def deliver_dielectric_modes(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach saved mode contributions and closure diagnostics without recomputing."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.dielectric-mode-response.v1":
        raise ValueError("unsupported dielectric mode response product")
    parent = product["context"]["parent"]
    _bind_task(parent, study, product_file)
    for field in ("study_id", "case_id", "case_role"):
        if product[field] != study[field]:
            raise ValueError(f"dielectric mode {field} differs from Study")
    if product["model_refs"] != study["model"]:
        raise ValueError("dielectric mode model differs from Study")
    return {
        "schema": "mlcc.dielectric-mode-delivery.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(product["model_refs"]),
        "status": product["status"],
        "responses": {"mode_resolved_ionic_response": product},
        "analysis_scheduler_job_id": product["analysis_scheduler_job_id"],
        "native_jobs": product["native_jobs"], "source_refs": product["source_refs"],
        "source_files": {"study": str(study_file), "product": str(product_file)},
        "original_source_files": product["source_files"],
        "design_assessment": "not_assessed",
    }


def deliver_interface_inputs(study_path: str | Path, request_path: str | Path) -> dict[str, Any]:
    """Deliver a layered model and existing MD input provenance, without a run."""
    from .modeling import read_model_artifacts
    from .interface_sources import _model_records, read_interface_task_sources

    study_file = Path(study_path).resolve()
    request_file = Path(request_path).resolve()
    study, request = _read_json(study_file), _read_json(request_file)
    if request["schema"] != "mlcc.interface-delivery-request.v1":
        raise ValueError("unsupported interface delivery request")
    model = read_model_artifacts(request["model_path"])
    record, lineage = _model_records(model)
    if (study["model"]["model_id"], study["model"]["version"]) != (model.model_id, model.version):
        raise ValueError("interface delivery Study model differs")
    if study["interface"]["parent_models"] != record["parent_models"] or study["interface"]["request"] != record["request"]:
        raise ValueError("interface delivery Study construction differs")
    task = None
    task_provenance = None
    if request.get("task_path") is not None:
        task_file = Path(request["task_path"]).resolve()
        task = _read_json(task_file)
        _bind_task(task, study, task_file.parent)
        if task["engine"] != "lammps":
            raise ValueError("interface input task must use the LAMMPS adapter")
        if (task["model_id"], task["model_version"]) != (model.model_id, model.version):
            raise ValueError("interface task model differs from delivery")
        task_provenance = read_interface_task_sources(
            task_file.parent, task["interface_sources"], study_id=study["study_id"],
            model_id=model.model_id, model_version=model.version, atom_ids=model.atom_ids,
        )
        if task_provenance["interface"] != record or task_provenance["atom_lineage"] != lineage:
            raise ValueError("interface task geometry or lineage differs from selected model")
        if task["study"]["interface"] != study["interface"]:
            raise ValueError("interface task Study source selection differs")
    return {
        "schema": "mlcc.interface-input-delivery.v1", "study_id": study["study_id"],
        "study_path": str(study_file), "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": {"model_id": model.model_id, "version": model.version,
                       "path": str(model.artifact_dir.resolve())},
        "parent_models": copy.deepcopy(record["parent_models"]),
        "parent_study_refs": copy.deepcopy(study["interface"]["parent_study_refs"]),
        "status": "input_sources_available", "interface": record, "atom_lineage": lineage,
        "task": task, "task_provenance": task_provenance,
        "conditions": copy.deepcopy(study.get("conditions")),
        "responses": {"traction_separation": None, "interface_thermal_response": None,
                      "local_thermal_stress": None},
        "response_status": "not_calculated", "missing_evidence": ["native_interface_response"],
        "source_files": {
            "request": str(request_file), "model": str(model.artifact_dir / "model.json"),
            "interface": str(model.artifact_dir / model.metadata["interface_file"]),
            "atom_lineage": str(model.artifact_dir / model.metadata["atom_lineage_file"]),
        },
        "design_assessment": "not_assessed",
    }


def deliver_interface_normal(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach an existing constrained normal response to its original Study."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.interface-normal-product.v1":
        raise ValueError("unsupported interface normal response product")
    task_file = Path(product["task_path"])
    task = _read_json(task_file)
    _bind_task(product, study, task_file.parent)
    _bind_task(task, study, task_file.parent)
    if task["task_id"] != product["task_id"] or task["protocol"] != product["protocol"]:
        raise ValueError("interface normal product differs from its source task")
    if task["study"]["interface"] != study["interface"]:
        raise ValueError("interface normal response Study source selection differs")
    delivery = {
        "schema": "mlcc.interface-normal-delivery.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(study["model"]),
        "parent_models": copy.deepcopy(study["interface"]["parent_models"]),
        "parent_study_refs": copy.deepcopy(study["interface"]["parent_study_refs"]),
        "status": product["status"], "response_status": product["status"],
        "responses": {"constrained_normal_response": product["normal_response"],
                      "traction_separation": None, "interface_thermal_response": None,
                      "local_thermal_stress": None},
        "missing_evidence": product["missing_evidence"],
        "source_task": product["source_task"], "native_result": product["native_result"],
        "protocol": product["protocol"], "conditions": copy.deepcopy(study.get("conditions")),
        "source_files": {"study": str(study_file), "product": str(product_file), "task": str(task_file)},
        "design_assessment": "not_assessed", "production_qualified": False,
    }
    if product["protocol"]["normal_response"]["kinematics"] == "fixed_cell_clamped_internal_relaxation":
        delivery["relaxation_status"] = product["relaxation_status"]
    return delivery


def deliver_interface_tangential(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach a saved tangential response and native stopping state to its Study."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.interface-tangential-product.v1":
        raise ValueError("unsupported interface tangential response product")
    task_file = Path(product["task_path"])
    task = _read_json(task_file)
    _bind_task(product, study, task_file.parent)
    _bind_task(task, study, task_file.parent)
    if task["protocol"]["kind"] != "interface_tangential":
        raise ValueError("interface tangential delivery requires an interface_tangential task")
    if task["task_id"] != product["task_id"] or task["protocol"] != product["protocol"]:
        raise ValueError("interface tangential product differs from its source task")
    if task["study"]["interface"] != study["interface"]:
        raise ValueError("interface tangential Study source selection differs")
    if product["interface_sources"] != task["interface_sources"]:
        raise ValueError("interface tangential product sources differ from task")
    return {
        "schema": "mlcc.interface-tangential-delivery.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(study["model"]),
        "parent_models": copy.deepcopy(study["interface"]["parent_models"]),
        "parent_study_refs": copy.deepcopy(study["interface"]["parent_study_refs"]),
        "status": product["status"], "response_status": product["status"],
        "relaxation_status": product["relaxation_status"],
        "responses": {"constrained_tangential_response": product["tangential_response"]},
        "missing_evidence": product["missing_evidence"],
        "source_task": product["source_task"], "native_result": product["native_result"],
        "interface_sources": product["interface_sources"],
        "protocol": product["protocol"], "conditions": copy.deepcopy(study.get("conditions")),
        "source_files": {"study": str(study_file), "product": str(product_file), "task": str(task_file)},
        "design_assessment": "not_assessed", "production_qualified": product["production_qualified"],
    }


def deliver_interface_thermal(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach saved thermal samples, quantities and explicit missing evidence."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.interface-thermal-product.v1":
        raise ValueError("unsupported interface thermal response product")
    task_file = Path(product["task_path"])
    task = _read_json(task_file)
    _bind_task(product, study, task_file.parent)
    _bind_task(task, study, task_file.parent)
    if task["task_id"] != product["task_id"] or task["protocol"] != product["protocol"]:
        raise ValueError("interface thermal product differs from its source task")
    if task["study"]["interface"] != study["interface"]:
        raise ValueError("interface thermal response Study source selection differs")
    return {
        "schema": "mlcc.interface-thermal-delivery.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(study["model"]),
        "parent_models": copy.deepcopy(study["interface"]["parent_models"]),
        "parent_study_refs": copy.deepcopy(study["interface"]["parent_study_refs"]),
        "status": product["status"], "response_status": product["status"],
        "responses": {"interface_thermal_response": product["thermal_response"],
                      "traction_separation": None, "local_thermal_stress": None},
        "missing_evidence": product["missing_evidence"],
        "source_task": product["source_task"], "native_result": product["native_result"],
        "native_thermal": product["native_thermal"], "protocol": product["protocol"],
        "analysis_request": product["analysis_request"],
        "conditions": copy.deepcopy(study.get("conditions")),
        "source_files": {"study": str(study_file), "product": str(product_file),
                         "task": str(task_file), "analysis_request": product["request_path"]},
        "design_assessment": "not_assessed", "production_qualified": False,
    }


def deliver_interface_electrical(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach a saved interface electrical response without reading native sources."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.interface-electrical-product.v1":
        raise ValueError("unsupported interface electrical response product")
    for field in ("study_id", "case_id", "case_role"):
        if product[field] != study[field]:
            raise ValueError(f"interface electrical {field} differs from Study")
    if (product["model_id"], product["model_version"]) != (study["model"]["model_id"], study["model"]["version"]):
        raise ValueError("interface electrical model differs from Study")
    if product["interface"] != study["interface"]:
        raise ValueError("interface electrical Study source selection differs")
    return {
        "schema": "mlcc.interface-electrical-delivery.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"],
        "analysis_scheduler_job_id": product["analysis_scheduler_job_id"],
        "model_refs": copy.deepcopy(study["model"]),
        "parent_models": copy.deepcopy(study["interface"]["parent_models"]),
        "parent_study_refs": copy.deepcopy(study["interface"]["parent_study_refs"]),
        "interface": product["interface"],
        "status": product["status"], "response_status": product["status"],
        "responses": {"interface_electrical_response": product["response"]},
        "selection": product["selection"], "method_set": product["method_set"],
        "source": product["source"], "reference": product["reference"],
        "missing_evidence": product["missing_evidence"],
        "conditions": copy.deepcopy(study.get("conditions")),
        "source_refs": product["source_refs"],
        "source_files": {"study": str(study_file), "product": str(product_file)},
        "potential_source_files": product["source_files"],
        "scientific_qualification": product["scientific_qualification"],
        "production_qualification": product["production_qualification"],
        "design_assessment": "not_assessed",
    }


def deliver_domain_parameters(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach saved domain values and their original states to the same Study."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.domain-parameters.v1":
        raise ValueError("unsupported domain parameter product")
    for key in ("study_id", "case_id"):
        if product["study"][key] != study[key]:
            raise ValueError(f"domain parameter {key} differs from Study")
    for key in ("model_id", "version"):
        if product["model"][key] != study["model"][key]:
            raise ValueError(f"domain parameter {key} differs from Study model")
    return {
        "schema": "mlcc.domain-parameter-delivery.v1",
        "status": "delivered",
        "study_id": study["study_id"], "case_id": study["case_id"],
        "study_path": str(study_file), "model": product["model"],
        "kind": product["kind"], "properties": product["properties"],
        "execution": product["execution"], "product": product,
        "source_files": {"study": str(study_file), "product": str(product_file)},
    }


def deliver_local_stress(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach explicit atom-group virial stress and its source definitions."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.local-stress-product.v1":
        raise ValueError("unsupported local stress product")
    task_file = Path(product["task_path"])
    task = _read_json(task_file)
    _bind_task(product, study, task_file.parent)
    _bind_task(task, study, task_file.parent)
    if task["task_id"] != product["task_id"] or task["protocol"] != product["protocol"]:
        raise ValueError("local stress product differs from its source task")
    for field in ("study_id", "case_id", "case_role"):
        if task[field] != study[field] or product[field] != study[field]:
            raise ValueError(f"local stress {field} differs from Study")
    if product["source_task"] != {key: task.get(key) for key in product["source_task"]}:
        raise ValueError("local stress native job differs from source task")
    purpose = task["protocol"]["purpose"]
    if purpose == "interface_local_stress":
        if product["interface_sources"] is None or product["interface_sources"] != task["interface_sources"]:
            raise ValueError("interface local stress requires matching interface sources")
        if task["study"]["interface"] != study["interface"]:
            raise ValueError("local stress Study source selection differs")
        parent_models = study["interface"]["parent_models"]
        parent_study_refs = study["interface"]["parent_study_refs"]
    elif purpose in {"potential_qualification", "md_native_sampling"}:
        if purpose == "potential_qualification":
            stress_protocol = task["protocol"]["local_stress"]
            if stress_protocol["compute_style"] != "centroid/stress/atom":
                raise ValueError("bulk local stress delivery requires explicit centroid/stress/atom")
        else:
            from .thermal_stress_sources import bind_thermal_source
            stress_protocol = task["protocol"]["native_sampling"]
            if product["native_local_stress"]["schema"] != "mlcc.md-native-stress-source.v1":
                raise ValueError("dynamic local stress requires the saved native MD stress source")
            bind_thermal_source(product_file, study)
        if product["local_stress"]["stress_volume_component_order"] != stress_protocol["component_order"]:
            raise ValueError("bulk local stress component order differs from source protocol")
        for field in ("parent_model", "method_set", "potential"):
            if product[field] != task[field]:
                raise ValueError(f"bulk local stress {field} differs from task")
        if product["interface_sources"] is not None or product["interface_provenance"] is not None or task.get("interface_sources") is not None:
            raise ValueError("bulk local stress does not declare interface sources")
        parent_models = None
        parent_study_refs = None
    else:
        raise ValueError(f"unsupported local stress delivery purpose: {purpose}")
    return {
        "schema": "mlcc.local-stress-delivery.v1", "study_id": study["study_id"],
        "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(study["model"]),
        "parent_models": copy.deepcopy(parent_models),
        "parent_study_refs": copy.deepcopy(parent_study_refs),
        "parent_model": copy.deepcopy(task.get("parent_model")),
        "method_set": task["method_set"], "potential": copy.deepcopy(task["potential"]),
        "status": product["status"], "response_status": product["status"],
        "responses": {"local_stress": product["local_stress"], "local_thermal_stress": None},
        "missing_evidence": product["missing_evidence"],
        "source_task": product["source_task"], "native_result": product["native_result"],
        "native_local_stress": product["native_local_stress"],
        "failure_evidence": product["failure_evidence"],
        "interface_provenance": product["interface_provenance"],
        "protocol": product["protocol"], "analysis_request": product["analysis_request"],
        "conditions": copy.deepcopy(study.get("conditions")),
        "source_files": {"study": str(study_file), "product": str(product_file),
                         "task": str(task_file), "analysis_request": product["request_path"]},
        "design_assessment": "not_assessed", "production_qualified": False,
    }


def deliver_md_replica_properties(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Attach a saved scalar replica summary without recalculating statistics."""
    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.md-replica-summary.v1":
        raise ValueError("unsupported MD replica summary schema")
    sources = product["sources"]
    if not sources or product["observed_source_count"] != len(sources):
        raise ValueError("MD replica summary source count differs from saved sources")
    if product["values"] != [source["value"] for source in sources]:
        raise ValueError("MD replica summary values differ from saved sources")
    artifacts = {"md-replicas": str(product_file), "study": str(study_file)}
    task_refs = []
    for index, source in enumerate(sources):
        delivery_file = Path(source["delivery_path"]).resolve()
        delivery = _read_json(delivery_file)
        task_file = Path(source["source_files"]["task.json"]).resolve()
        task = _read_json(task_file)
        _bind_task(task, study, task_file)
        for field in ("study_id", "case_id", "case_role"):
            if delivery[field] != study[field] or task[field] != study[field]:
                raise ValueError(f"MD replica source {field} differs from delivery Study")
        if delivery["schema"] != "mlcc.md-property-delivery.v1":
            raise ValueError("MD replica source must be a saved MD property delivery")
        if Path(delivery["task_path"]).resolve() != task_file:
            raise ValueError("MD replica source task path differs from saved delivery")
        if source["task_id"] != task["task_id"] or source["task_id"] != delivery["task_id"]:
            raise ValueError("MD replica source task identity differs from saved delivery")
        native_job = {key: task[key] for key in ("scheduler_job_id", "scheduler_state", "exit_code", "runner")}
        if source["native_job"] != native_job or delivery["native_job"] != native_job:
            raise ValueError("MD replica native job differs from saved delivery/task")
        if source["analysis_scheduler_job_id"] != delivery["analysis_scheduler_job_id"]:
            raise ValueError("MD replica source analysis job differs from saved delivery")
        if Path(source["collection_path"]).resolve() != Path(delivery["artifacts"]["collection"]).resolve():
            raise ValueError("MD replica source collection differs from saved delivery")
        if source["method_set"] != task["method_set"] or source["method_set"] != delivery["lineage"]["method_set"]:
            raise ValueError("MD replica source method_set differs from saved delivery/task")
        for key in ("model_id", "version"):
            if source["model"][key] != delivery["model"][key]:
                raise ValueError("MD replica source model differs from saved delivery")
        for key in ("potential_id", "version"):
            if source["potential"][key] != delivery["potential"][key]:
                raise ValueError("MD replica source potential differs from saved delivery")
        matches = [row for row in delivery["observables"] if row["observable_id"] == product["observable_id"]]
        if len(matches) != 1 or source["observable"] != matches[0] or source["value"] != matches[0]["value"]:
            raise ValueError("MD replica source observable differs from saved delivery")
        if product["observable"] != {key: matches[0][key] for key in ("definition", "object_level", "unit")}:
            raise ValueError("MD replica summary observable definition differs from saved delivery")
        artifacts[f"source-delivery-{index}"] = str(delivery_file)
        artifacts[f"source-collection-{index}"] = source["collection_path"]
        artifacts[f"source-task-{index}"] = str(task_file)
        task_refs.append({"task_id": task["task_id"], "task_path": str(task_file),
                          "native_job": native_job, "source_analysis_scheduler_job_id": source["analysis_scheduler_job_id"],
                          "method_set": task["method_set"]})
    return {
        "schema": "mlcc.md-replica-property-delivery.v1",
        "study_id": study["study_id"], "study_path": str(study_file),
        "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(study["model"]),
        "status": product["status"], "statistics_status": product["statistics_status"],
        "statistics_unresolved_reasons": copy.deepcopy(product["statistics_unresolved_reasons"]),
        "observable_id": product["observable_id"], "observable": copy.deepcopy(product["observable"]),
        "statistics": copy.deepcopy(product["statistics"]), "interval": copy.deepcopy(product["interval"]),
        "observed_source_count": product["observed_source_count"], "replica_count": product["replica_count"],
        "values": copy.deepcopy(product["values"]), "sources": copy.deepcopy(sources), "task_refs": task_refs,
        "product_path": str(product_file), "product": product, "artifacts": artifacts,
        "analysis_scheduler_job_id": product.get("analysis_scheduler_job_id"),
        "scientific_status": copy.deepcopy(product["scientific_status"]),
        "production_qualification": product["production_qualification"],
        "sampling_equilibrium_qualified": product["sampling_equilibrium_qualified"],
        "design_assessment": "not_assessed",
    }


def deliver_thermal_stress(study_path: str | Path, product_path: str | Path) -> dict[str, Any]:
    """Deliver saved stress differences and histories without evaluating them again."""
    from .thermal_stress_sources import bind_thermal_source

    study_file, product_file = Path(study_path).resolve(), Path(product_path).resolve()
    study, product = _read_json(study_file), _read_json(product_file)
    if product["schema"] != "mlcc.thermal-stress-product.v1":
        raise ValueError("unsupported thermal stress product")
    for field in ("study_id", "case_id", "case_role"):
        if product[field] != study[field]:
            raise ValueError(f"thermal stress {field} differs from delivery Study")
    artifacts = {"thermal-stress": str(product_file), "study": str(study_file),
                 "request": product["request_path"]}
    task_refs = []
    for index, source in enumerate(product["sources"]):
        bound = bind_thermal_source(source["product_path"], study)
        if bound != source:
            raise ValueError("thermal stress source differs from saved product/task")
        task_refs.append(source)
        artifacts[f"source-product-{index}"] = source["product_path"]
        artifacts[f"source-task-{index}"] = source["task_path"]
        for name, path in source["source_files"].items():
            artifacts[f"source-{index}:{name}"] = path
    request = product["analysis_request"]
    entries = request["states"] if request["reference"] is None else [request["reference"], *request["states"]]
    for index, entry in enumerate(entries):
        for name in ("temperature_history_path", "mechanical_history_path", "temperature_product_path"):
            if entry[name] is not None:
                artifacts[f"{name}-{index}"] = entry[name]
    return {
        "schema": "mlcc.thermal-stress-delivery.v1", "study_id": study["study_id"],
        "study_path": str(study_file), "case_id": study["case_id"], "case_role": study["case_role"],
        "model_refs": copy.deepcopy(study["model"]),
        "status": product["status"], "responses": {"local_thermal_stress": product["response"]},
        "missing_evidence": product["missing_evidence"], "task_refs": task_refs,
        "product_path": str(product_file), "product": product, "artifacts": artifacts,
        "analysis_scheduler_job_id": product["analysis_scheduler_job_id"],
        "conditions": copy.deepcopy(study.get("conditions")),
        "design_assessment": "not_assessed", "production_qualified": product["production_qualified"],
    }


def _berry_task_file(task_path: str | Path) -> Path:
    candidate = Path(task_path).expanduser().resolve()
    if candidate.is_dir():
        candidate = candidate / "task.json"
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _berry_native_job(task: Mapping[str, Any], task_path: Path, *, role: str, device: Any = None) -> dict[str, Any]:
    job = {
        "role": role,
        "task_id": task.get("task_id"),
        "scheduler_job_id": task.get("scheduler_job_id"),
        "scheduler_state": task.get("scheduler_state", task.get("status")),
        "exit_code": task.get("exit_code"),
        "runner": task.get("runner"),
        "task_path": str(task_path),
    }
    if device is not None:
        job["device"] = device
    if task.get("result_file") is not None:
        job["result_file"] = task.get("result_file")
    return job


def deliver_berry_polarization(
    study_path: str | Path,
    task_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Deliver one native single-direction Berry polarization observation.

    The native reader performs all ABACUS/SCF/charge/source validation.  This
    function only binds that read-only observation to the selected Study and
    exposes its scalar direction and provenance for ``assess_design``.  One
    ``gdir`` is intentionally never promoted to a three-dimensional,
    spontaneous-polarization, Born-charge, or dielectric result.
    """

    study = _read_json(study_path)
    study_id = study.get("study_id")
    case_id = study.get("case_id")
    case_role = study.get("case_role")
    if not isinstance(study_id, str) or not study_id:
        raise ValueError("study.study_id is required")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("study.case_id is required for Berry delivery")
    if not isinstance(case_role, str) or not case_role:
        raise ValueError("study.case_role is required for Berry delivery")
    study_model = study.get("model")
    if not isinstance(study_model, Mapping):
        raise ValueError("study.model is required for Berry delivery")

    task_file = _berry_task_file(task_path)
    task_directory = task_file.parent
    task = _read_json(task_file)
    # Keep native validation in one place.  In particular, this call validates
    # the reference SCF, charge source, native direction and parser protocol;
    # this delivery layer must not reimplement or weaken those checks.
    native = read_berry_task(task_directory)

    for key in ("study_id", "case_id", "case_role"):
        if task.get(key) != study.get(key):
            raise ValueError(f"Berry task {key} does not match Study")
    expected_fixture = case_role == "engineering_fixture"
    if "fixture" not in task or not isinstance(task.get("fixture"), bool) or task.get("fixture") != expected_fixture:
        raise ValueError("Berry task fixture role does not match Study case_role")
    study_fixture = study_model.get("fixture")
    if study_fixture is not None and bool(study_fixture) != expected_fixture:
        raise ValueError("Study model fixture role does not match Study case_role")
    for task_key, study_key in (("model_id", "model_id"), ("model_version", "version")):
        expected = study_model.get(study_key)
        if expected is None or task.get(task_key) != expected:
            raise ValueError(f"Berry task {task_key} does not match Study model")
    if native.get("model_id") != task.get("model_id") or native.get("model_version") != task.get("model_version"):
        raise ValueError("Berry native result model identity differs from task")
    if native.get("method_set") != task.get("method_set"):
        raise ValueError("Berry native result method_set differs from task")

    method_path = task_directory / "method.json"
    method = _read_json(method_path)
    if method.get("method_set") != task.get("method_set"):
        raise ValueError("Berry method_set differs from task")
    if method.get("engine") != "abacus" or method.get("abacus_version_target") != "3.10.1":
        raise ValueError("Berry delivery requires ABACUS 3.10.1")
    if method.get("model_id") not in (None, task.get("model_id")) or method.get("version") not in (
        None,
        task.get("model_version"),
    ):
        raise ValueError("Berry method model identity differs from task")
    protocol = method.get("berry")
    if not isinstance(protocol, Mapping) or protocol.get("role") != "nscf":
        raise ValueError("Berry method must declare an NSCF protocol")
    gdir = native.get("gdir")
    if isinstance(gdir, bool) or gdir not in (1, 2, 3) or protocol.get("gdir") != gdir:
        raise ValueError("Berry delivery requires one consistent gdir")

    reference_validation = native.get("reference_scf_validation")
    if not isinstance(reference_validation, Mapping):
        raise ValueError("Berry native result lacks validated SCF reference")
    reference_file = Path(str(protocol.get("source_reference_task_file", ""))).expanduser().resolve()
    if not reference_file.is_file():
        raise FileNotFoundError(reference_file)
    reference_task_file = _berry_task_file(reference_file)
    reference_task = _read_json(reference_task_file)
    if reference_task.get("task_id") != native.get("reference_task_id"):
        raise ValueError("Berry reference task identity differs from native result")
    for key in ("study_id", "case_id", "case_role", "model_id", "model_version", "fixture"):
        if reference_task.get(key) != task.get(key):
            raise ValueError(f"Berry reference {key} differs from NSCF task")
    reference_method_path = reference_task_file.parent / "method.json"
    reference_method = _read_json(reference_method_path)
    if reference_method.get("method_set") != reference_task.get("method_set"):
        raise ValueError("Berry reference method_set differs from reference task")
    if reference_task.get("method_set") != task.get("method_set"):
        raise ValueError("Berry reference and NSCF method_set differ")

    calculation_conditions = task.get("calculation_conditions")
    if not isinstance(calculation_conditions, Mapping):
        raise ValueError("Berry task calculation_conditions are required")
    conditions = dict(calculation_conditions)
    value = native.get("total_P_C_per_m2")
    quantum = native.get("modulo_quantum_C_per_m2")
    if not _finite_number(value) or not _finite_number(quantum):
        raise ValueError("Berry native representative and quantum must be finite")
    source_refs = [
        f"task:{task['task_id']}",
        f"scheduler_job:{task['scheduler_job_id']}",
        f"reference_task:{reference_task['task_id']}",
        f"reference_scheduler_job:{reference_task['scheduler_job_id']}",
        f"method:{task['method_set']}",
        str(task_file),
        str(method_path),
        str(reference_task_file),
        str(reference_method_path),
    ]
    source_files = native.get("source_files")
    if not isinstance(source_files, Mapping) or not source_files:
        raise ValueError("Berry native source_files are required")
    source_refs.extend(str(path) for path in source_files.values() if isinstance(path, str))
    reference_source_files = {
        key: reference_validation[key]
        for key in ("native_scf_source", "electronic_source", "charge_files")
        if reference_validation.get(key) is not None
    }
    source_refs.extend(
        str(path)
        for value in reference_source_files.values()
        for path in (value if isinstance(value, list) else value.values() if isinstance(value, Mapping) else [value])
        if isinstance(path, str)
    )
    scientific_status = (
        "qualified"
        if native.get("scientific_qualification") is True
        else "unqualified"
    )
    observable = {
        "observable_id": f"berry_polarization_gdir_{gdir}",
        "definition": "single-direction absolute Berry polarization representative on the native branch",
        "object_level": "bulk_model_cell",
        "unit": "C/m^2",
        "conditions": conditions,
        "value": float(value),
        "uncertainty": None,
        "scientific_status": scientific_status,
        "source_refs": source_refs,
        "source_task": task["task_id"],
        "scheduler_job_id": task["scheduler_job_id"],
        "reference_task": reference_task["task_id"],
        "reference_scheduler_job_id": reference_task["scheduler_job_id"],
        "method_set": task["method_set"],
        "model_refs": {"model_id": task.get("model_id"), "version": task.get("model_version")},
        "gdir": gdir,
        "direction_lattice_vector_angstrom": native.get("direction_lattice_vector_angstrom"),
        "direction_unit_vector_cartesian": native.get("direction_unit_vector_cartesian"),
        "polarization_quantum_C_per_m2": float(quantum),
        "branch_status": native.get("branch_status"),
        "branch_unwrapped": native.get("branch_unwrapped"),
        "upstream_scientific_status": native.get("scientific_status"),
    }

    if targets_path is None and (
        study.get("design_requirements_ref") not in (None, "")
        or study.get("design_requirements") not in (None, "", [], {})
    ):
        raise ValueError("study has design requirements; targets_path must be explicit")
    if targets_path is None:
        requirements = None
    else:
        targets = _read_json(targets_path)
        if targets.get("study_id") != study_id:
            raise ValueError("targets study_id must exactly match Study")
        requirements = targets.get("requirements")
    assessment = assess_design(requirements, [observable])

    reference_source = {
        "task_file": str(reference_task_file),
        "method_file": str(reference_method_path),
        **reference_source_files,
    }
    native_job = _berry_native_job(task, task_file, role="nscf", device=native.get("device"))
    reference_job = _berry_native_job(reference_task, reference_task_file, role="reference_scf")
    return {
        "schema": "mlcc.berry-polarization-delivery.v001",
        "study_id": study_id,
        "case_id": case_id,
        "case_role": case_role,
        "study_path": str(Path(study_path).expanduser().resolve()),
        "task_path": str(task_file),
        "fixture": expected_fixture,
        "model_refs": {"model_id": task.get("model_id"), "version": task.get("model_version")},
        "task_refs": [native_job, reference_job],
        "native_jobs": {"nscf": native_job, "reference_scf": reference_job},
        "method_set": task["method_set"],
        "method": method,
        "reference_method": reference_method,
        "conditions": conditions,
        "gdir": gdir,
        "direction_lattice_vector_angstrom": native.get("direction_lattice_vector_angstrom"),
        "direction_unit_vector_cartesian": native.get("direction_unit_vector_cartesian"),
        "unit": "C/m^2",
        "polarization": {
            "representative_P_C_per_m2": float(value),
            "quantum_Q_C_per_m2": float(quantum),
            "branch_status": native.get("branch_status"),
            "branch_unwrapped": native.get("branch_unwrapped"),
        },
        "observables": [observable],
        "source_files": dict(source_files),
        "reference_source_files": reference_source,
        "native_result": native,
        "native_compatibility_evidence": {
            "device": native.get("device"),
            "task_id": task.get("task_id"),
            "scheduler_job_id": task.get("scheduler_job_id"),
            "scheduler_state": task.get("scheduler_state"),
            "exit_code": task.get("exit_code"),
            "runner": task.get("runner"),
            "fixture": task.get("fixture"),
            "method_set": task.get("method_set"),
            "gdir": gdir,
            "scientific_status": native.get("scientific_status"),
            "production_label": native.get("production_label"),
            "source_task": str(task_file),
        },
        "upstream_scientific_status": native.get("scientific_status"),
        "qualification_status": task.get("qualification_status", protocol.get("qualification_status")),
        "scope": {
            "direction_count": 1,
            "single_gdir_scalar": True,
            "complete_3d_polarization": False,
            "spontaneous_polarization": False,
            "born_effective_charges": False,
            "dielectric_tensor": False,
            "branch_continuity": False,
        },
        "uncomputed": {
            "complete_3d_polarization_C_per_m2": None,
            "spontaneous_polarization_C_per_m2": None,
            "born_effective_charges": None,
            "dielectric_tensor": None,
        },
        "scientific_status": "qualified" if scientific_status == "qualified" else "unqualified",
        "production_qualification": False,
        "design_assessment": assessment["design_assessment"],
        "design_assessment_detail": assessment,
        "targets_path": None if targets_path is None else str(Path(targets_path).expanduser().resolve()),
    }


_P5_DELIVERY_SCHEMA = "mlcc.p5-property-delivery.v1"
_P5_REQUEST_SCHEMA = "mlcc.p5-property-delivery-request.v1"
_P5_SOURCE_MODES = {"native_source_bound", "software_math_only"}
_P5_REQUEST_FIELDS = {
    "schema", "study_id", "source_mode", "born", "gamma", "nac",
    "electronic", "ionic", "dielectric",
}


_DEFECT_REFERENCE_DELIVERY_SCHEMA = "mlcc.defect-reference-delivery.v1"
_DEFECT_REFERENCE_REQUEST_SCHEMA = "mlcc.defect-reference-delivery-request.v1"
_DEFECT_REFERENCE_REQUEST_FIELDS = {
    "schema", "host_electronic_path", "defect_electronic_path", "descriptor_path",
}


def _resolve_defect_reference_input(request_path: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"defect-reference request {field} must be a non-empty string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = request_path.parent / path
    return path.resolve()


def _defect_reference_model(reference: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    model = reference.get("model")
    if not isinstance(model, Mapping):
        raise ValueError(f"defect-reference {role} model is required")
    for field in ("model_id", "version", "path"):
        if not isinstance(model.get(field), str) or not model[field].strip():
            raise ValueError(f"defect-reference {role} model.{field} is required")
    return model


def _defect_reference_parent_binding(
    host: Mapping[str, Any], defect: Mapping[str, Any],
) -> None:
    host_model = _defect_reference_model(host, "host")
    defect_parent = defect.get("parent_model")
    if not isinstance(defect_parent, Mapping):
        raise ValueError("defect-reference descriptor parent_model is required")
    for field in ("model_id", "version", "path"):
        if not isinstance(defect_parent.get(field), str) or not defect_parent[field].strip():
            raise ValueError(f"defect-reference descriptor parent_model.{field} is required")
    if (defect_parent["model_id"], defect_parent["version"]) != (
        host_model["model_id"], host_model["version"],
    ):
        raise ValueError("defect descriptor parent model differs from host model")
    if Path(defect_parent["path"]).expanduser().resolve() != Path(host_model["path"]).expanduser().resolve():
        raise ValueError("defect descriptor parent model path differs from host model")


def deliver_polarization_energy(
    study_path: str | Path,
    energy_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Deliver an existing SCF energy curve without repeating its calculation."""
    study_file, result_file = Path(study_path).resolve(), Path(energy_path).resolve()
    study, result = _read_json(study_file), _read_json(result_file)
    if result["schema"] != "mlcc.polarization-energy-path.v1":
        raise ValueError("unsupported polarization-energy result schema")
    parent = result["parent"]
    if parent["study_id"] != study["study_id"] or (
        parent["model_id"], parent["model_version"]
    ) != (study["model"]["model_id"], study["model"]["version"]):
        raise ValueError("polarization-energy parent differs from delivery Study/model")
    if Path(parent["study_file"]).resolve() != study_file:
        raise ValueError("polarization-energy parent Study source differs from delivery Study")
    model_path = study["model"].get("model_path", study["model"].get("path"))
    if model_path is not None and Path(model_path).resolve() != Path(parent["model_path"]).resolve():
        raise ValueError("polarization-energy parent model path differs from delivery Study")
    requirements = None
    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets["study_id"] != study["study_id"]:
            raise ValueError("polarization-energy targets differ from Study")
        requirements = targets["requirements"]
    elif study.get("design_requirements_ref") or study.get("design_requirements"):
        raise ValueError("Study has design requirements; targets_path must be explicit")
    assessment = assess_design(requirements, [])
    return {
        "schema": "mlcc.polarization-energy-delivery.v1",
        "study_id": study["study_id"], "study_path": str(study_file), "study": study,
        "path_result_file": str(result_file), "path_result": copy.deepcopy(result),
        "path_id": result["path_id"], "parent": copy.deepcopy(parent),
        "status": result["status"], "evidence_kind": result["evidence_kind"],
        "points": copy.deepcopy(result["points"]),
        "mechanical_constraint": copy.deepcopy(result["mechanical_constraint"]),
        "reference_point_id": result["reference_point_id"],
        "endpoint_difference_eV_cell": result["endpoint_difference_eV_cell"],
        "sampled_maximum": copy.deepcopy(result["sampled_maximum"]),
        "native_jobs": copy.deepcopy(result["native_jobs"]), "missing": copy.deepcopy(result["missing"]),
        "neb_barrier_eV": None, "finite_temperature_free_energy_eV": None,
        "spontaneous_polarization": None, "double_well_qualified": False,
        "scientific_qualification": False, "production_qualification": False,
        "design_assessment": assessment["design_assessment"], "design_assessment_detail": assessment,
    }


def deliver_polarization_strain(
    study_path: str | Path,
    result_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Deliver saved strain responses without recomputing polarization algebra."""
    study_file, result_file = Path(study_path).resolve(), Path(result_path).resolve()
    study, result = _read_json(study_file), _read_json(result_file)
    if result["schema"] != "mlcc.polarization-strain.v1":
        raise ValueError("unsupported polarization-strain result schema")
    parent = result["parent"]
    if parent["study_id"] != study["study_id"] or (
        parent["model_id"], parent["model_version"]
    ) != (study["model"]["model_id"], study["model"]["version"]):
        raise ValueError("polarization-strain parent differs from delivery Study/model")
    if Path(parent["study_file"]).resolve() != study_file:
        raise ValueError("polarization-strain parent Study source differs from delivery Study")
    for key in ("model_path", "path"):
        model_path = study["model"].get(key)
        if model_path is not None and (study_file.parent / model_path).resolve() != Path(parent["model_path"]).resolve():
            raise ValueError("polarization-strain parent model path differs from delivery Study")
    requirements = None
    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets["study_id"] != study["study_id"]:
            raise ValueError("polarization-strain targets differ from Study")
        requirements = targets["requirements"]
    elif study.get("design_requirements_ref") or study.get("design_requirements"):
        raise ValueError("Study has design requirements; targets_path must be explicit")
    assessment = assess_design(requirements, [])
    return {
        **copy.deepcopy(result),
        "schema": "mlcc.polarization-strain-delivery.v1",
        "study_id": study["study_id"], "study_path": str(study_file), "study": study,
        "result_file": str(result_file), "result": copy.deepcopy(result),
        "scientific_qualification": False, "production_qualification": False,
        "full_tensor_qualified": False,
        "design_assessment": assessment["design_assessment"], "design_assessment_detail": assessment,
    }


def deliver_potential_alignment(
    study_path: str | Path,
    alignment_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Deliver a saved regional difference, without creating charge corrections."""
    study_file, alignment_file = Path(study_path).resolve(), Path(alignment_path).resolve()
    study, alignment = _read_json(study_file), _read_json(alignment_file)
    if alignment["schema"] != "mlcc.potential-alignment.v1":
        raise ValueError("unsupported potential-alignment result schema")
    host, defect = alignment["references"]["host"], alignment["references"]["defect"]
    if defect["study"]["study_id"] != study["study_id"] or (
        defect["model"]["model_id"], defect["model"]["version"]
    ) != (study["model"]["model_id"], study["model"]["version"]):
        raise ValueError("potential-alignment defect differs from delivery Study/model")
    explicit_model_path = study["model"].get("model_path", study["model"].get("path"))
    if explicit_model_path is not None and Path(explicit_model_path).resolve() != Path(defect["model"]["path"]).resolve():
        raise ValueError("potential-alignment Study model path differs from defect")
    requirements = None
    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets["study_id"] != study["study_id"]:
            raise ValueError("potential-alignment targets differ from Study")
        requirements = targets["requirements"]
    elif study.get("design_requirements_ref") or study.get("design_requirements"):
        raise ValueError("Study has design requirements; targets_path must be explicit")
    assessment = assess_design(requirements, [])
    return {
        "schema": "mlcc.potential-alignment-delivery.v1",
        "study_id": study["study_id"], "study_path": str(study_file), "study": study,
        "alignment_path": str(alignment_file), "alignment": copy.deepcopy(alignment),
        "source_paths": copy.deepcopy(alignment["source_paths"]),
        "host": copy.deepcopy(host), "defect": copy.deepcopy(defect),
        "missing": copy.deepcopy(alignment["missing"]),
        "difference": copy.deepcopy(alignment["difference"]),
        "candidate_host_vbm_on_defect_gauge_eV": alignment["candidate_host_vbm_on_defect_gauge_eV"],
        "aligned_host_vbm_eV": None, "potential_alignment_eV": None,
        "correction_terms": None, "FNV_eFNV_correction_eV": None,
        "charged_formation_energy_eV": None, "native_alignment_accepted": False,
        "scientific_qualification": False, "numerical_qualification": False,
        "production_qualification": False,
        "design_assessment": assessment["design_assessment"], "design_assessment_detail": assessment,
    }


def deliver_chemical_references(
    study_path: str | Path,
    collection_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Consume saved normalized references; reuse the existing region solver.

    No source energies or native levels are parsed again. Mathematical
    collections can exercise the algebra but cannot supply a native chemical
    point to a real defect task.
    """
    from .defect_thermodynamics import chemical_potential_region

    study_file, collection_file = Path(study_path).resolve(), Path(collection_path).resolve()
    study, collection = _read_json(study_file), _read_json(collection_file)
    if collection["schema"] != "mlcc.chemical-reference-set.v1":
        raise ValueError("unsupported chemical-reference collection schema")
    references = collection["references"]
    hosts = [record for record in references if record["reference_id"] == collection["host_reference_id"]]
    if len(hosts) != 1 or hosts[0]["role"] != "host":
        raise ValueError("chemical-reference collection needs its declared host")
    host, source = hosts[0], hosts[0]["source"]
    if source["study"]["study_id"] != study["study_id"] or (
        source["model"]["model_id"], source["model"]["version"]
    ) != (study["model"]["model_id"], study["model"]["version"]):
        raise ValueError("chemical-reference host differs from delivery Study/model")
    native = all(record["evidence_kind"] == "native_saved_source" for record in references)
    region_request = collection["region_request"]
    region = None if region_request is None else chemical_potential_region(region_request)
    point = None
    if region is not None and region["selected_point"] is not None and region["selected_point"]["feasible"]:
        point = {
            "mu_eV_per_atom": region["selected_point"]["mu_eV_per_atom"],
            "delta_mu_eV_per_atom": region["selected_point"]["delta_mu_eV_per_atom"],
            "engine": source["method"]["engine"],
            "engine_version": source["method"]["abacus_version_target"],
            "method_set": source["method"]["method_set"],
            "energy_definition": source["parent_total_energy_provenance"]["definition"],
            "source_reference": str(collection_file),
            "reference_set_id": collection["reference_set_id"],
            "evidence_kind": "native_saved_source" if native else "software_contract_only",
            "scientific_qualification": False, "production_qualification": False,
        }
    requirements = None
    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets["study_id"] != study["study_id"]:
            raise ValueError("chemical-reference targets differ from Study")
        requirements = targets["requirements"]
    elif study.get("design_requirements_ref") or study.get("design_requirements"):
        raise ValueError("Study has design requirements; targets_path must be explicit")
    assessment = assess_design(requirements, [])
    return {
        "schema": "mlcc.chemical-reference-delivery.v1",
        "study_id": study["study_id"], "study_path": str(study_file),
        "collection_path": str(collection_file), "study": study,
        "reference_set_id": collection["reference_set_id"],
        "references": copy.deepcopy(collection), "host": copy.deepcopy(host),
        "native_jobs": [copy.deepcopy(record["source"]["native_job"]) for record in references],
        "missing": copy.deepcopy(collection["missing"]), "region": region,
        "chemical_point": point if native else None,
        "mathematical_chemical_point": point if not native else None,
        "raw_formation_energy_eV": None, "charged_formation_energy_eV": None,
        "scientific_qualification": False, "production_qualification": False,
        "design_assessment": assessment["design_assessment"], "design_assessment_detail": assessment,
    }


def deliver_defect_references(
    study_path: str | Path,
    request_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Deliver an already built host/defect electronic reference pair.

    The paired builder is the only producer consumed here.  This layer binds
    its defect task to the requested Study and preserves the native sampled
    levels and source provenance without re-reading ``istate`` or deriving a
    potential alignment, correction, or formation energy.
    """
    study_file = Path(study_path).expanduser().resolve()
    request_file = Path(request_path).expanduser().resolve()
    study = _read_json(study_file)
    request = _read_json(request_file)
    if request.get("schema") != _DEFECT_REFERENCE_REQUEST_SCHEMA:
        raise ValueError("defect-reference request schema is unsupported")
    if set(request) - _DEFECT_REFERENCE_REQUEST_FIELDS:
        raise ValueError("defect-reference request contains unsupported fields")
    source_paths = {
        field: _resolve_defect_reference_input(request_file, request.get(field), field)
        for field in ("host_electronic_path", "defect_electronic_path", "descriptor_path")
    }

    study_id = study.get("study_id")
    study_model = study.get("model")
    if not isinstance(study_id, str) or not study_id.strip() or not isinstance(study_model, Mapping):
        raise ValueError("Study study_id and model are required")
    for field in ("model_id", "version"):
        if not isinstance(study_model.get(field), str) or not study_model[field].strip():
            raise ValueError(f"Study model.{field} is required")

    from .defect_references import build_defect_electronic_reference

    pair = build_defect_electronic_reference(
        source_paths["host_electronic_path"],
        source_paths["defect_electronic_path"],
        source_paths["descriptor_path"],
    )
    if not isinstance(pair, Mapping) or pair.get("schema") != "mlcc.defect-reference-pair.v1":
        raise ValueError("defect-reference builder returned an unsupported pair")
    host = pair.get("host")
    defect = pair.get("defect")
    if not isinstance(host, Mapping) or not isinstance(defect, Mapping):
        raise ValueError("defect-reference pair must contain host and defect records")
    host_model = _defect_reference_model(host, "host")
    defect_model = _defect_reference_model(defect, "defect")
    defect_study = defect.get("study")
    if not isinstance(defect_study, Mapping) or defect_study.get("study_id") != study_id:
        raise ValueError("provided Study must match defect reference Study")
    if (defect_model["model_id"], defect_model["version"]) != (
        study_model["model_id"], study_model["version"],
    ):
        raise ValueError("provided Study model differs from defect reference model")
    explicit_model_path = study_model.get("model_path", study_model.get("path"))
    if explicit_model_path is not None and Path(str(explicit_model_path)).expanduser().resolve() != Path(defect_model["path"]).expanduser().resolve():
        raise ValueError("provided Study model path differs from defect reference model")
    _defect_reference_parent_binding(host, defect)

    descriptor_path = pair.get("descriptor_path")
    if descriptor_path is not None and Path(str(descriptor_path)).expanduser().resolve() != source_paths["descriptor_path"]:
        raise ValueError("defect-reference descriptor path differs from request")
    for role, reference, field in (
        ("host", host, "host_electronic_path"),
        ("defect", defect, "defect_electronic_path"),
    ):
        source_file = reference.get("electronic_source_file")
        if source_file is not None and Path(str(source_file)).expanduser().resolve() != source_paths[field]:
            raise ValueError(f"defect-reference {role} source path differs from request")

    requirements = None
    has_design = study.get("design_requirements_ref") not in (None, "") or study.get("design_requirements") not in (None, "", [], {})
    if targets_path is None and has_design:
        raise ValueError("study has design requirements; targets_path must be explicit")
    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets.get("study_id") != study_id:
            raise ValueError("defect-reference targets study_id differs from Study")
        requirements = targets.get("requirements")
    # Independent sampled levels are deliberately not design observables.  A
    # supplied target therefore remains explicitly insufficient_evidence.
    assessment = assess_design(requirements, [])
    preserved = copy.deepcopy(dict(pair))
    qualification = {
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }
    return {
        "schema": _DEFECT_REFERENCE_DELIVERY_SCHEMA,
        "study_id": study_id,
        "study_path": str(study_file),
        "request_path": str(request_file),
        "targets_path": None if targets_path is None else str(Path(targets_path).expanduser().resolve()),
        "source_paths": {field: str(path) for field, path in source_paths.items()},
        "study": copy.deepcopy(study),
        "references": preserved,
        "host": copy.deepcopy(host),
        "defect": copy.deepcopy(defect),
        "aligned_host_vbm_eV": None,
        "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None,
        "charged_formation_energy_eV": None,
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
        "qualification": qualification,
        "design_assessment": assessment["design_assessment"],
        "design_assessment_detail": assessment,
    }


_CHARGE_DELIVERY_SCHEMA = "mlcc.charge-property-delivery.v1"
_CHARGE_PRODUCT_SCHEMAS = {
    "charge_correction": "mlcc.charge-correction.v1",
    "charged_formation": "mlcc.charged-formation.v1",
    "charge_transitions": "mlcc.charge-transition-collection.v1",
}


def deliver_charge_properties(
    study_path: str | Path,
    product_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    """Deliver a saved charge product after binding its selected Study/model.

    The product is copied as a complete source record.  This function does not
    recompute charge corrections, formation energies, envelopes, or any
    scientific qualification.
    """

    study_file = Path(study_path).expanduser().resolve()
    product_file = Path(product_path).expanduser().resolve()
    study = _read_json(study_file)
    product = _read_json(product_file)
    schema = product["schema"]
    if schema == _CHARGE_PRODUCT_SCHEMAS["charge_correction"]:
        kind = "charge_correction"
    elif schema == _CHARGE_PRODUCT_SCHEMAS["charged_formation"]:
        kind = "charged_formation"
    elif schema == _CHARGE_PRODUCT_SCHEMAS["charge_transitions"]:
        kind = "charge_transitions"
    else:
        raise ValueError("unsupported charge product schema")
    if not isinstance(study.get("study_id"), str) or not study["study_id"].strip():
        raise ValueError("Study study_id is required")
    study_model = study["model"]
    if kind in {"charge_correction", "charged_formation"}:
        references = product["references"]
        defect = references["defect"]
        if defect["study"]["study_id"] != study["study_id"]:
            raise ValueError(f"{kind} defect Study differs from delivery Study")
        if (defect["model"]["model_id"], defect["model"]["version"]) != (
            study_model["model_id"], study_model["version"],
        ):
            raise ValueError(f"{kind} defect model differs from delivery Study model")
        study_model_path = study_model.get("model_path", study_model.get("path"))
        if study_model_path is not None and Path(study_model_path).expanduser().resolve() != Path(defect["model"]["path"]).expanduser().resolve():
            raise ValueError(f"{kind} defect model path differs from delivery Study model")
        binding = {"kind": "defect_reference", "study": copy.deepcopy(defect["study"]), "model": copy.deepcopy(defect["model"])}
    else:
        host = product["host"]
        host_study = host["study"]
        if host_study["study_id"] != study["study_id"]:
            raise ValueError("charge_transitions host Study differs from delivery Study")
        if (host["model"]["model_id"], host["model"]["version"]) != (
            study_model["model_id"], study_model["version"],
        ):
            raise ValueError("charge_transitions host model differs from delivery Study model")
        study_model_path = study_model.get("model_path", study_model.get("path"))
        if study_model_path is not None and Path(study_model_path).expanduser().resolve() != Path(host["model"]["path"]).expanduser().resolve():
            raise ValueError("charge_transitions host model path differs from delivery Study model")
        binding = {"kind": "host_reference", "study": copy.deepcopy(host_study), "model": copy.deepcopy(host["model"])}
    targets = None
    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets.get("study_id") != study["study_id"]:
            raise ValueError("charge product targets differ from delivery Study")
    missing = product["missing"]
    if not isinstance(missing, list):
        raise ValueError("charge product missing must be a list")
    native_jobs = copy.deepcopy(product.get("native_jobs", []))
    if not native_jobs and kind in {"charge_correction", "charged_formation"}:
        native_jobs = []
        for role in ("host", "defect"):
            job = product["references"][role]["native_job"]
            if job not in native_jobs:
                native_jobs.append(copy.deepcopy(job))
    return {
        "schema": _CHARGE_DELIVERY_SCHEMA,
        "property_kind": kind,
        "study_id": study["study_id"],
        "study_path": str(study_file),
        "study": copy.deepcopy(study),
        "product_path": str(product_file),
        "product": copy.deepcopy(product),
        "source_paths": copy.deepcopy(product.get("source_paths", {})),
        "native_jobs": native_jobs,
        "status": product.get("status"),
        "missing": copy.deepcopy(missing),
        "reference_identity": copy.deepcopy(product.get("reference_identity")),
        "host": copy.deepcopy(product.get("host")),
        "references": copy.deepcopy(product.get("references")),
        "binding": binding,
        "targets_path": None if targets_path is None else str(Path(targets_path).expanduser().resolve()),
        "targets": targets,
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }


def _p5_context(product: Mapping[str, Any], label: str) -> dict[str, Any]:
    if label == "born":
        context = product.get("context")
    elif label in {"gamma", "nac"}:
        context = {
            "parent": product.get("parent"),
            "atom_ids": product.get("atom_ids"),
            "cell_angstrom": product.get("cell_angstrom"),
            "volume_A3": product.get("volume_A3"),
            "common_method": product.get("method_identity"),
        }
    elif label == "electronic":
        context = {
            "parent": product.get("parent"),
            "atom_ids": product.get("atom_ids"),
            "cell_angstrom": product.get("cell_angstrom"),
            "volume_A3": product.get("volume_A3"),
            "common_method": product.get("method_identity"),
        }
    else:
        context = product.get("context")
    if not isinstance(context, Mapping):
        raise ValueError(f"{label} context is required")
    parent = context.get("parent")
    if not isinstance(parent, Mapping):
        raise ValueError(f"{label}.parent is required")
    for field in ("study_id", "model_id", "model_version", "model_path"):
        if not isinstance(parent.get(field), str) or not parent[field].strip():
            raise ValueError(f"{label}.parent.{field} is required")
    atom_ids = context.get("atom_ids")
    if not isinstance(atom_ids, list) or not atom_ids or len(set(atom_ids)) != len(atom_ids):
        raise ValueError(f"{label}.atom_ids must be a non-empty unique list")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in atom_ids):
        raise ValueError(f"{label}.atom_ids must contain integers")
    method = context.get("common_method")
    if not isinstance(method, Mapping):
        raise ValueError(f"{label}.common_method is required")
    normalized = {
        "parent": {
            "study_id": parent["study_id"],
            "model_id": parent["model_id"],
            "model_version": parent["model_version"],
            "model_path": str(Path(parent["model_path"]).expanduser().resolve()),
        },
        "atom_ids": list(atom_ids),
        "cell_angstrom": copy.deepcopy(context.get("cell_angstrom")),
        "volume_A3": context.get("volume_A3"),
        "common_method": copy.deepcopy(dict(method)),
    }
    from .dielectric_response import _validate_context_geometry
    _validate_context_geometry(normalized, f"{label}.context")
    return normalized


def _p5_method_identity(method: Mapping[str, Any]) -> dict[str, Any]:
    from .dielectric_response import p5_method_identity
    return copy.deepcopy(p5_method_identity(method))


def _p5_method_comparison(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    from .dielectric_response import p5_method_comparison
    return copy.deepcopy(p5_method_comparison(left, right))


def _p5_context_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    from .dielectric_response import _context_equal
    return bool(_context_equal(left, right))


def _p5_validate_declared_method(product: Mapping[str, Any], label: str, context: Mapping[str, Any]) -> None:
    field = "common_method" if label == "born" else "method_identity"
    declared = product.get(field)
    if declared is None:
        return
    if not isinstance(declared, Mapping):
        raise ValueError(f"{label}.{field} must be an object")
    if _p5_method_comparison(context["common_method"], declared).get("same_physical_method") is not True:
        raise ValueError(f"{label} declared method differs from context method")


def _p5_declared_mode(product: Mapping[str, Any], label: str) -> str:
    method = product.get("common_method") or product.get("method_identity")
    if not isinstance(method, Mapping):
        method = _p5_context(product, label)["common_method"]
    engine = method.get("engine")
    engine_mode = (
        "software_math_only"
        if engine in {"math-fixture", "mathematical_fixture"}
        else "native_source_bound"
        if engine == "abacus"
        else None
    )
    declared: list[str] = []
    has_external_child = False
    if label == "born":
        if isinstance(product.get("source"), Mapping) and product["source"].get("native_born_family"):
            declared.append("native_source_bound")
        declared.extend(
            source.get("source_mode")
            for source in product.get("sources", [])
            if isinstance(source, Mapping) and source.get("source_mode") in _P5_SOURCE_MODES
        )
        # A response path is an explicit native producer reference.  Bind its
        # mode here instead of allowing an ABACUS method record by itself to
        # silently turn an otherwise source-less product into a native one.
        if not declared and (product.get("response_paths") or product.get("response_sources")):
            declared.append("native_source_bound")
        if not declared:
            raise ValueError("Born source_mode or response_paths is required")
    elif label == "gamma":
        source = product.get("source")
        if not isinstance(source, Mapping) or source.get("source_mode") not in _P5_SOURCE_MODES:
            raise ValueError("Gamma source.source_mode is required")
        declared.append(source["source_mode"])
    elif label == "nac":
        source = product.get("source")
        source_mode = product.get("source_mode")
        source_declared_mode = source.get("source_mode") if isinstance(source, Mapping) else None
        if source_mode not in _P5_SOURCE_MODES or source_declared_mode not in _P5_SOURCE_MODES:
            raise ValueError("NAC source_mode and source.source_mode are required")
        if source_mode != source_declared_mode:
            raise ValueError("NAC source contains conflicting source modes")
        declared.append(source_mode)
    elif label == "electronic":
        provenance_kind = product.get("provenance_kind")
        if provenance_kind == "native_derived":
            if product.get("source_mode") != "native_source_bound" or engine_mode != "native_source_bound":
                raise ValueError("native electronic source mode conflicts with method engine")
            declared.append("native_source_bound")
        elif provenance_kind is not None:
            if provenance_kind != "external_supplied":
                raise ValueError("electronic provenance_kind is unsupported")
            recorded_mode = product.get("source_mode")
            if recorded_mode is not None and recorded_mode != "software_math_only":
                raise ValueError("external electronic source_mode is unsupported")
            if recorded_mode == "software_math_only" and engine_mode != "software_math_only":
                raise ValueError("external electronic source_mode conflicts with method engine")
            # External electronic input is a contribution classification.  It
            # does not change the Born/Gamma Study source mode or the method
            # identity used below for context/method matching.
            return "external_supplied"
        if product.get("source_mode") in _P5_SOURCE_MODES:
            declared.append(product["source_mode"])
        elif engine_mode != "software_math_only":
            raise ValueError("electronic source_mode and explicit native source are required")
    elif label == "ionic":
        for source in (product.get("gamma_source"), product.get("born_source")):
            if isinstance(source, Mapping) and source.get("source_mode") in _P5_SOURCE_MODES:
                declared.append(source["source_mode"])
        if not declared:
            born_source = product.get("born_source")
            source_records = born_source.get("sources", []) if isinstance(born_source, Mapping) else []
            if any(isinstance(record, Mapping) and record.get("response_path") for record in source_records):
                declared.append("native_source_bound")
            elif any(isinstance(record, Mapping)
                     and record.get("source_mode") == "native_source_bound"
                     and record.get("native_born_family")
                     and "native_born_review" in record for record in source_records):
                declared.append("native_source_bound")
            gamma_source = product.get("gamma_source")
            if isinstance(gamma_source, Mapping) and gamma_source.get("native_refs"):
                declared.append("native_source_bound")
    elif label == "dielectric":
        for child in (product.get("electronic"), product.get("ionic")):
            if isinstance(child, Mapping):
                mode = _p5_declared_mode(child, "electronic" if child is product.get("electronic") else "ionic")
                # The external electronic contribution is allowed as the one
                # explicit exception to the global Born/Gamma source mode.
                # The composite mode comes from its non-external child (or
                # from the composite context when electronic is the only
                # child).
                if mode != "external_supplied":
                    declared.append(mode)
                else:
                    has_external_child = True
    if any(mode not in _P5_SOURCE_MODES for mode in declared):
        raise ValueError(f"{label} source_mode is unsupported")
    if len(set(declared)) > 1:
        raise ValueError(f"{label} contains conflicting source modes")
    if declared and engine_mode and declared[0] != engine_mode:
        raise ValueError(f"{label} declared source_mode conflicts with method engine")
    if declared:
        return declared[0]
    if label == "dielectric" and has_external_child and engine_mode in _P5_SOURCE_MODES:
        # An external-only composite has no non-external child from which to
        # inherit the global mode.  Its already validated context supplies the
        # mode for this narrow case; other products retain their existing
        # native-source gate.
        return engine_mode
    if engine_mode == "software_math_only":
        return engine_mode
    raise ValueError(f"{label} source_mode is missing")


def _p5_source_paths(product: Mapping[str, Any], label: str) -> list[str]:
    refs: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip() and value not in refs:
            refs.append(value)
        elif isinstance(value, list):
            for child in value:
                add(child)

    if label in {"born", "gamma"} and product.get("provenance_kind") == "native_derived":
        add(product.get("source_refs"))
    if label == "born":
        add(product.get("response_paths"))
        add(product.get("response_sources"))
        for source in product.get("sources", []):
            if isinstance(source, Mapping):
                add(source.get("response_path"))
                add(source.get("reference"))
    elif label == "gamma":
        source = product.get("source")
        if isinstance(source, Mapping):
            for key in ("harmonic_result", "plan_manifest", "force_bundle", "native_refs", "native_method_files", "collection"):
                add(source.get(key))
    elif label == "nac":
        # The NAC result is a saved directional product.  Keep the explicit
        # Born/epsilon inputs alongside the harmonic source so a delivered
        # result cannot become detached from the inputs that produced it.
        for key in ("born_input", "electronic_input"):
            input_record = product.get(key)
            if isinstance(input_record, Mapping):
                add(input_record.get("path"))
        source = product.get("source")
        if isinstance(source, Mapping):
            for key in (
                "harmonic_result", "plan_manifest", "force_bundle", "native_refs",
                "native_method_files", "native_task_records", "collection",
            ):
                add(source.get(key))
    elif label == "electronic":
        add(product.get("source_path"))
        add(product.get("source_refs"))
        add(product.get("native_tasks"))
        add(product.get("native_jobs"))
    elif label == "ionic":
        for source in (product.get("gamma_source"), product.get("born_source")):
            if isinstance(source, Mapping):
                for record in source.get("sources", []):
                    if isinstance(record, Mapping):
                        add(record.get("response_path"))
                        add(record.get("reference"))
                for key in ("harmonic_result", "plan_manifest", "force_bundle", "native_refs", "native_method_files", "collection"):
                    add(source.get(key))
    elif label == "dielectric":
        add(product.get("source_path"))
        add(product.get("source_refs"))
        contribution = product.get("contribution_provenance")
        if isinstance(contribution, Mapping):
            electronic = contribution.get("electronic")
            if isinstance(electronic, Mapping):
                add(electronic.get("source_path"))
                add(electronic.get("source_refs"))
            ionic = contribution.get("ionic")
            if isinstance(ionic, Mapping):
                for source in (ionic.get("born_source"), ionic.get("gamma_source")):
                    if isinstance(source, Mapping):
                        for record in source.get("sources", []):
                            if isinstance(record, Mapping):
                                add(record.get("response_path"))
                                add(record.get("reference"))
                        add(source.get("response_path"))
                        add(source.get("reference"))
                        add(source.get("harmonic_result"))
                        add(source.get("plan_manifest"))
                        add(source.get("force_bundle"))
                        add(source.get("native_refs"))
                        add(source.get("native_method_files"))
                        add(source.get("collection"))
    return refs


def _p5_job_from_task(task: Mapping[str, Any], role: str, source: str) -> dict[str, Any]:
    return {
        "role": role,
        "task_id": task.get("task_id"),
        "scheduler_job_id": task.get("scheduler_job_id"),
        "scheduler_state": task.get("scheduler_state", task.get("status")),
        "exit_code": task.get("exit_code"),
        "runner": task.get("runner"),
        "source": source,
    }


def _p5_read_task(path: str | Path, role: str, expected_id: Any = None) -> dict[str, Any]:
    task_path = Path(str(path)).expanduser().resolve()
    if task_path.is_dir():
        task_path = task_path / "task.json"
    if not task_path.is_file():
        raise FileNotFoundError(task_path)
    task = _read_json(task_path)
    if expected_id is not None and task.get("task_id") != expected_id:
        raise ValueError(f"{role} task_id differs from declared source")
    return _p5_job_from_task(task, role, str(task_path))


def _p5_native_born(born: Mapping[str, Any], born_context: Mapping[str, Any]) -> list[dict[str, Any]]:
    from . import dielectric_response
    source = born.get("source")
    if isinstance(source, Mapping) and source.get("native_born_family"):
        if "native_born_review" in source:
            from .born_affine import consume_native_born_review
            bound = consume_native_born_review(source["native_born_family"], source["native_born_review"])
        else:
            bound = dielectric_response.read_native_born_family(source["native_born_family"])
        if dict(born) != bound:
            raise ValueError("native Born family product differs from its saved source")
        return copy.deepcopy(bound["native_jobs"])
    validator = dielectric_response._validate_native_sources
    raw_paths = born.get("response_paths") or born.get("response_sources")
    if raw_paths is not None and not isinstance(raw_paths, list):
        raise ValueError("native Born response_paths must be a list")
    raw_paths = list(raw_paths or [])
    if not raw_paths:
        raw_paths = [
            source.get("response_path")
            for source in born.get("sources", [])
            if isinstance(source, Mapping) and source.get("response_path")
        ]
    if not raw_paths:
        raise ValueError("native Born response_paths are required")
    jobs: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, str]] = set()
    for raw_path in raw_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("native Born response_paths must contain file paths")
        response_path = Path(str(raw_path)).expanduser().resolve()
        response = _read_json(response_path)
        parent = response.get("parent")
        if not isinstance(parent, Mapping):
            raise ValueError("native Born response parent is required")
        response_context = {
            "parent": {
                "study_id": parent.get("study_id"),
                "model_id": parent.get("model_id"),
                "model_version": parent.get("model_version"),
                "model_path": str(Path(str(parent.get("model_path"))).expanduser().resolve()),
            },
            "atom_ids": born_context["atom_ids"],
            "cell_angstrom": born_context["cell_angstrom"],
            "volume_A3": born_context["volume_A3"],
            "common_method": response.get("common_method"),
        }
        if not _p5_context_equal(born_context, response_context):
            raise ValueError("native Born response parent/method differs from Born product")
        validator(response, response_path)
        for direction in response.get("directions", []):
            if not isinstance(direction, Mapping):
                continue
            for side in ("minus", "plus"):
                point = direction.get(side)
                if not isinstance(point, Mapping):
                    continue
                task_record = point.get("task")
                source = point.get("source")
                if not isinstance(task_record, Mapping) or not isinstance(source, Mapping):
                    raise ValueError("native Born response lacks declared NSCF source/task")
                task_file = source.get("task_file")
                jobs_to_add: list[tuple[str, Any, Any]] = [("nscf", task_file, task_record.get("task_id"))]
                native_result = point.get("native_result")
                reference = native_result.get("reference_scf_validation") if isinstance(native_result, Mapping) else None
                scf_record = point.get("scf_job")
                reference_file = reference.get("task_file") if isinstance(reference, Mapping) else None
                if reference_file is None and isinstance(scf_record, Mapping):
                    reference_file = scf_record.get("task_file")
                reference_id = (
                    reference.get("task_id")
                    if isinstance(reference, Mapping)
                    else scf_record.get("task_id")
                    if isinstance(scf_record, Mapping)
                    else None
                )
                jobs_to_add.append(("reference_scf", reference_file, reference_id))
                for role, task_path, expected_id in jobs_to_add:
                    if not isinstance(task_path, str) or not task_path.strip():
                        raise ValueError(f"native Born {role} task_file is required")
                    job = _p5_read_task(task_path, role, expected_id)
                    key = (job["task_id"], job["scheduler_job_id"], role)
                    if key not in seen:
                        seen.add(key)
                        jobs.append(job)
    return jobs


def _p5_native_gamma_jobs(gamma: Mapping[str, Any], gamma_context: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = gamma.get("source")
    if isinstance(source, Mapping) and source.get("native_saved_gamma_request"):
        from .gamma_processing import import_saved_gamma
        bound = import_saved_gamma(source["native_saved_gamma_request"])
        if dict(gamma) != bound:
            raise ValueError("saved Gamma product differs from its bound source and import request")
        return copy.deepcopy(bound["native_jobs"])
    if isinstance(source, Mapping) and source.get("native_gamma_processing_request"):
        from .gamma_processing import process_native_gamma
        bound = process_native_gamma(source["native_gamma_processing_request"])
        if dict(gamma) != bound:
            raise ValueError("explicitly processed Gamma differs from its saved raw source and request")
        return copy.deepcopy(bound["native_jobs"])
    if isinstance(source, Mapping) and source.get("native_raw_product"):
        from .dielectric_response import read_native_gamma_force
        bound = read_native_gamma_force(source["native_raw_product"])
        if dict(gamma) != bound:
            raise ValueError("native raw Gamma product differs from its saved source")
        return copy.deepcopy(bound["native_jobs"])
    records = source.get("native_task_records") if isinstance(source, Mapping) else None
    if not isinstance(records, list) or not records:
        raise ValueError("native Gamma source.native_task_records is required")
    jobs: list[dict[str, Any]] = []
    seen_task_ids: set[Any] = set()
    parent_fields = {
        "parent_study_id": "study_id",
        "parent_model_id": "model_id",
        "parent_model_version": "model_version",
    }
    for path in records:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("native Gamma task records must be task-file paths")
        task_path = Path(path).expanduser().resolve()
        if task_path.is_dir():
            task_path = task_path / "task.json"
        task = _read_json(task_path)
        if task.get("stage") != "P7" or task.get("calculation") != "scf":
            raise ValueError("native Gamma task must be a P7 SCF TaskRecord")
        if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
            raise ValueError("native Gamma task must be COMPLETED with exit_code 0:0")
        identity = task.get("phonon_displacement")
        if not isinstance(identity, Mapping):
            raise ValueError("native Gamma task lacks phonon_displacement binding")
        for identity_field, parent_field in parent_fields.items():
            if identity.get(identity_field) != gamma_context["parent"][parent_field]:
                raise ValueError(f"native Gamma task {identity_field} differs from Gamma parent")
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip() or task.get("scheduler_job_id") in (None, ""):
            raise ValueError("native Gamma task must preserve task_id and scheduler_job_id")
        if task_id in seen_task_ids:
            raise ValueError("native Gamma task records contain duplicate task_id")
        seen_task_ids.add(task_id)
        jobs.append(_p5_job_from_task(task, "gamma_native_task", str(task_path)))
    return jobs


def _p5_validate_born(born: Mapping[str, Any], context: Mapping[str, Any]) -> None:
    if born.get("schema") != "mlcc.born-charge-columns.v1" or born.get("unit") != "e":
        raise ValueError("Born schema or unit is unsupported")
    if list(born.get("atom_ids", context["atom_ids"])) != context["atom_ids"]:
        raise ValueError("Born atom_ids differ from context")
    tensor = born.get("full_born_tensors_e")
    if tensor is not None:
        try:
            array = np.asarray(tensor, dtype=float)
        except (TypeError, ValueError) as error:
            raise ValueError("Born full_born_tensors_e must be finite N x 3 x 3") from error
        if array.shape != (len(context["atom_ids"]), 3, 3) or not np.all(np.isfinite(array)):
            raise ValueError("Born full_born_tensors_e must be finite N x 3 x 3")
    elif not isinstance(born.get("missing_columns"), list) or not born.get("missing_columns"):
        raise ValueError("unresolved Born product must declare missing_columns")


def _p5_validate_gamma(gamma: Mapping[str, Any], context: Mapping[str, Any]) -> None:
    if gamma.get("schema") != "mlcc.gamma-force-constants.v1":
        raise ValueError("Gamma schema is unsupported")
    if gamma.get("unit") != "eV/angstrom^2" or gamma.get("matrix_basis") != "parent_atom_major_cartesian":
        raise ValueError("Gamma unit or matrix_basis is unsupported")
    if gamma.get("electrical_boundary") != "fixed_E_zero" or gamma.get("mechanical_boundary") != "fixed_cell" or gamma.get("nac") != "not_applied":
        raise ValueError("Gamma boundary contract is unsupported")
    try:
        matrix = np.asarray(gamma.get("matrix_eV_per_A2"), dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("Gamma matrix must be finite 3N x 3N") from error
    expected = (3 * len(context["atom_ids"]), 3 * len(context["atom_ids"]))
    if matrix.shape != expected or not np.all(np.isfinite(matrix)):
        raise ValueError("Gamma matrix must be finite 3N x 3N")


def _p5_validate_nac(
    nac: Mapping[str, Any],
    context: Mapping[str, Any],
    born: Mapping[str, Any],
    electronic: Mapping[str, Any] | None,
    *,
    born_path: Path,
    electronic_path: Path | None,
) -> None:
    """Validate one saved directional NAC product and its explicit inputs.

    NAC is an independent phonon observable.  This validator deliberately
    does not feed its corrected matrix into the Gamma Hessian or the ionic
    dielectric consumer; it only checks that the saved directional result is
    bound to the exact Born/epsilon files supplied to this delivery request.
    """

    if nac.get("schema") != "mlcc.phonon-gamma-nac.v1":
        raise ValueError("NAC schema is unsupported")
    if nac.get("hermitianize") is not False:
        raise ValueError("NAC hermitianize must be false")
    if nac.get("born_epsilon_symmetrized") is not False:
        raise ValueError("NAC born_epsilon_symmetrized must be false")
    if nac.get("nac_method") != "wang":
        raise ValueError("NAC method is unsupported")
    if nac.get("direction_basis") != "primitive_reciprocal_fractional":
        raise ValueError("NAC direction_basis is unsupported")
    direction = np.asarray(nac["nac_q_direction"], dtype=float)
    if direction.shape != (3,) or not np.all(np.isfinite(direction)) or float(np.linalg.norm(direction)) <= 0.0:
        raise ValueError("NAC nac_q_direction must be a finite non-zero three-vector")
    normalized_direction = np.asarray(nac["nac_q_direction_normalized"], dtype=float)
    if (
        normalized_direction.shape != (3,)
        or not np.all(np.isfinite(normalized_direction))
        or not np.allclose(
            normalized_direction,
            direction / float(np.linalg.norm(direction)),
            rtol=0.0,
            atol=1.0e-12,
        )
    ):
        raise ValueError("NAC nac_q_direction_normalized does not match nac_q_direction")
    q_point = np.asarray(nac["q_point"], dtype=float)
    if q_point.shape != (3,) or not np.allclose(q_point, 0.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("NAC q_point must be Gamma")
    unit = "eV/angstrom^2/amu"
    if nac.get("dynamical_matrix_unit") != unit:
        raise ValueError("NAC dynamical_matrix_unit is unsupported")

    expected = (3 * len(context["atom_ids"]),) * 2

    def matrix(record: Any, name: str) -> np.ndarray:
        if not isinstance(record, Mapping):
            raise ValueError(f"NAC {name} record is required")
        if record.get("dynamical_matrix_unit") != unit:
            raise ValueError(f"NAC {name} dynamical_matrix_unit is unsupported")
        value = np.asarray(record["dynamical_matrix"], dtype=float)
        if value.shape != expected or not np.all(np.isfinite(value)):
            raise ValueError(f"NAC {name} dynamical_matrix must be finite 3N x 3N")
        return value

    def frequencies(record: Any, name: str) -> np.ndarray:
        if not isinstance(record, Mapping):
            raise ValueError(f"NAC {name} record is required")
        value = np.asarray(record["frequencies_THz"], dtype=float)
        if value.shape != (expected[0],) or not np.all(np.isfinite(value)):
            raise ValueError(f"NAC {name} frequencies_THz must be finite 3N values")
        return value

    baseline_record = nac.get("baseline")
    corrected_record = nac.get("corrected")
    correction_record = nac.get("correction")
    if not isinstance(baseline_record, Mapping) or baseline_record.get("nac") != "not_applied":
        raise ValueError("NAC baseline must preserve nac=not_applied")
    if not isinstance(corrected_record, Mapping) or corrected_record.get("nac") != "wang":
        raise ValueError("NAC corrected product must preserve nac=wang")
    baseline = matrix(baseline_record, "baseline")
    corrected = matrix(corrected_record, "corrected")
    if not isinstance(correction_record, Mapping) or correction_record.get("formula") != "D_corrected - D_baseline":
        raise ValueError("NAC correction formula is unsupported")
    correction = matrix(correction_record, "correction")
    if not np.allclose(corrected - baseline, correction, rtol=0.0, atol=1.0e-12):
        raise ValueError("NAC correction differs from corrected minus baseline")
    frequencies(baseline_record, "baseline")
    frequencies(corrected_record, "corrected")
    if nac.get("asr") != "not_applied":
        raise ValueError("NAC asr must be not_applied")

    masses = np.asarray(nac["masses_amu"], dtype=float)
    if masses.shape != (len(context["atom_ids"]),) or not np.all(np.isfinite(masses)) or np.any(masses <= 0.0):
        raise ValueError("NAC masses_amu must be finite positive values for every atom")

    born_input = nac.get("born_input")
    if not isinstance(born_input, Mapping):
        raise ValueError("NAC born_input snapshot is required")
    required_born_fields = ("path", "schema", "unit", "atom_ids", "full_born_tensors_e", "sources")
    if any(field not in born_input for field in required_born_fields):
        raise ValueError("NAC born_input snapshot is incomplete")
    if not isinstance(born_input["path"], str) or not born_input["path"].strip():
        raise ValueError("NAC born_input.path is required")
    if Path(born_input["path"]).expanduser().resolve() != born_path.resolve():
        raise ValueError("NAC born_input.path differs from supplied Born product")
    if born_input.get("schema") != born.get("schema") or born_input.get("unit") != born.get("unit"):
        raise ValueError("NAC born_input differs from supplied Born product")
    if born_input["atom_ids"] != born.get("atom_ids", context["atom_ids"]):
        raise ValueError("NAC born_input atom_ids differ from supplied Born product")
    if born_input["sources"] != born.get("sources", []):
        raise ValueError("NAC born_input sources differ from supplied Born product")
    saved_born = np.asarray(born_input["full_born_tensors_e"], dtype=float)
    supplied_born = np.asarray(born["full_born_tensors_e"], dtype=float)
    if saved_born.shape != supplied_born.shape or not np.allclose(saved_born, supplied_born, rtol=0.0, atol=1.0e-12):
        raise ValueError("NAC saved Born tensor differs from supplied Born product")

    electronic_input = nac.get("electronic_input")
    if electronic is None or electronic_path is None:
        raise ValueError("NAC electronic input is required")
    if not isinstance(electronic_input, Mapping):
        raise ValueError("NAC electronic_input snapshot is required")
    required_electronic_fields = (
        "path", "kind", "unit", "atom_ids", "tensor", "source_refs", "provenance_kind",
        "electrical_boundary", "mechanical_boundary", "ions",
    )
    if any(field not in electronic_input for field in required_electronic_fields):
        raise ValueError("NAC electronic_input snapshot is incomplete")
    if not isinstance(electronic_input["path"], str) or not electronic_input["path"].strip():
        raise ValueError("NAC electronic_input.path is required")
    if Path(electronic_input["path"]).expanduser().resolve() != electronic_path.resolve():
        raise ValueError("NAC electronic_input.path differs from supplied electronic product")
    if electronic_input.get("kind") != electronic.get("kind") or electronic_input.get("unit") != electronic.get("unit"):
        raise ValueError("NAC electronic_input differs from supplied electronic product")
    if electronic_input["atom_ids"] != electronic.get("atom_ids", context["atom_ids"]):
        raise ValueError("NAC electronic_input atom_ids differ from supplied electronic product")
    if electronic_input["source_refs"] != electronic.get("source_refs", []):
        raise ValueError("NAC electronic_input source_refs differ from supplied electronic product")
    if electronic_input["provenance_kind"] != electronic.get("provenance_kind"):
        raise ValueError("NAC electronic_input provenance_kind differs from supplied electronic product")
    if (
        electronic_input["electrical_boundary"] != "fixed_E_zero"
        or electronic_input["mechanical_boundary"] != "fixed_cell"
        or electronic_input["ions"] != "clamped"
    ):
        raise ValueError("NAC electronic_input boundary snapshot is unsupported")
    if (
        electronic_input["electrical_boundary"] != electronic.get("electrical_boundary")
        or electronic_input["mechanical_boundary"] != electronic.get("mechanical_boundary")
        or electronic_input["ions"] != electronic.get("ions")
    ):
        raise ValueError("NAC electronic_input boundary snapshot differs from supplied electronic product")
    saved_electronic = np.asarray(electronic_input["tensor"], dtype=float)
    supplied_electronic = np.asarray(electronic["tensor"], dtype=float)
    if saved_electronic.shape != supplied_electronic.shape or not np.allclose(saved_electronic, supplied_electronic, rtol=0.0, atol=1.0e-12):
        raise ValueError("NAC saved electronic tensor differs from supplied electronic product")


def _p5_validate_ionic(ionic: Mapping[str, Any], born: Mapping[str, Any], gamma: Mapping[str, Any] | None) -> None:
    if ionic.get("schema") != "mlcc.ionic-dielectric-response.v1" or ionic.get("unit") != "dimensionless":
        raise ValueError("ionic schema or unit is unsupported")
    if ionic.get("electrical_boundary") != "fixed_E_zero" or ionic.get("mechanical_boundary") != "fixed_cell" or ionic.get("nac") != "not_applied":
        raise ValueError("ionic boundary contract is unsupported")
    if gamma is not None and "explicit_processing" in gamma:
        if ionic.get("response_scope") != gamma["response_scope"]:
            raise ValueError("ionic local-response scope differs from explicitly processed Gamma")
    born_source = ionic.get("born_source")
    expected_born_source = {"schema": born.get("schema"), "sources": born.get("sources")}
    if not isinstance(born_source, Mapping) or dict(born_source) != expected_born_source:
        raise ValueError("ionic born_source does not match supplied Born product")
    gamma_source = ionic.get("gamma_source")
    delta = ionic.get("delta_epsilon_ionic")
    # An unresolved ionic product may legitimately record that neither a
    # Gamma source nor its delta exists yet.  Once either a Gamma product or a
    # non-null delta is supplied, the source binding becomes mandatory.
    if gamma is None and delta is None:
        if gamma_source is not None and not isinstance(gamma_source, Mapping):
            raise ValueError("ionic gamma_source must be an object when supplied")
        return
    if not isinstance(gamma_source, Mapping):
        raise ValueError("ionic gamma_source is required for a supplied Gamma/delta")
    if delta is not None:
        if gamma is None:
            raise ValueError("non-null ionic delta requires supplied Gamma product")
        if dict(gamma_source) != dict(gamma.get("source", {})):
            raise ValueError("ionic gamma_source does not match supplied Gamma product")
        if born.get("full_born_tensors_e") is None:
            raise ValueError("non-null ionic delta requires complete Born tensors")
        try:
            array = np.asarray(delta, dtype=float)
        except (TypeError, ValueError) as error:
            raise ValueError("ionic delta_epsilon_ionic must be finite 3x3") from error
        if array.shape != (3, 3) or not np.all(np.isfinite(array)):
            raise ValueError("ionic delta_epsilon_ionic must be finite 3x3")
    elif gamma is not None and gamma_source != gamma.get("source"):
        raise ValueError("ionic gamma_source differs from supplied Gamma product")


def _p5_nested_product_for_compare(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    # ``combine_dielectric_contributions`` adds method_comparisons to the
    # product envelope.  Preserve every saved product field (including
    # status and unresolved reasons) when comparing nested products.
    result = copy.deepcopy(dict(value))
    result.pop("method_comparisons", None)
    return result


def _p5_validate_dielectric(saved: Mapping[str, Any], recombined: Mapping[str, Any], electronic: Mapping[str, Any] | None, ionic: Mapping[str, Any] | None) -> None:
    if saved.get("schema") != "mlcc.dielectric-response.v1" or saved.get("unit") != "dimensionless":
        raise ValueError("dielectric schema or unit is unsupported")
    if saved.get("response_scope") != recombined.get("response_scope"):
        raise ValueError("dielectric local-response scope differs from recombined contributions")
    for field in ("epsilon_infinity", "delta_epsilon_ionic", "epsilon_static"):
        left, right = saved.get(field), recombined.get(field)
        if left is None or right is None:
            if left is not None or right is not None:
                raise ValueError(f"saved dielectric.{field} differs from recombined contributions")
        else:
            try:
                left_array = np.asarray(left, dtype=float)
                right_array = np.asarray(right, dtype=float)
            except (TypeError, ValueError) as error:
                raise ValueError(f"saved dielectric.{field} must be finite 3x3") from error
            if (
                left_array.shape != (3, 3)
                or right_array.shape != (3, 3)
                or not np.all(np.isfinite(left_array))
                or not np.all(np.isfinite(right_array))
            ):
                raise ValueError(f"saved dielectric.{field} must be finite 3x3")
            if not np.allclose(left_array, right_array, rtol=0.0, atol=1.0e-12):
                raise ValueError(f"saved dielectric.{field} differs from recombined contributions")
    for label, supplied in (("electronic", electronic), ("ionic", ionic)):
        nested = saved.get(label)
        if supplied is None or not isinstance(nested, Mapping):
            if nested is not None or supplied is not None:
                raise ValueError(f"saved dielectric {label} must match explicit request product")
        elif _p5_nested_product_for_compare(nested) != _p5_nested_product_for_compare(supplied):
            raise ValueError(f"saved dielectric {label} differs from explicit request product")
    saved_provenance = saved.get("contribution_provenance")
    recombined_provenance = recombined.get("contribution_provenance")
    bound_electronic = (
        isinstance(recombined_provenance, Mapping)
        and isinstance(recombined_provenance.get("electronic"), Mapping)
        and recombined_provenance["electronic"].get("provenance_kind") in {"external_supplied", "native_derived"}
    )
    # Legacy mathematical saved products predate this envelope field.  Once
    # an external electronic contribution is present, however, a saved result
    # must carry the same source declaration and cannot override the request.
    if saved_provenance is not None or bound_electronic:
        if saved_provenance != recombined_provenance:
            raise ValueError("saved dielectric contribution_provenance differs from recombined contributions")


def _p5_tensor_observables(label: str, product: Mapping[str, Any], context: Mapping[str, Any], refs: list[str], include: bool) -> list[dict[str, Any]]:
    if not include:
        return []
    if label == "nac":
        return []
    field = {
        "born": ("full_born_tensors_e", "e", ("atom_id", "polarization_cartesian_axis", "displacement_cartesian_axis")),
        "gamma": ("matrix_eV_per_A2", "eV/angstrom^2", ("row_dof", "column_dof")),
        "electronic": ("tensor", "dimensionless", ("cartesian_row", "cartesian_column")),
        "ionic": ("delta_epsilon_ionic", "dimensionless", ("cartesian_row", "cartesian_column")),
        "dielectric": ("epsilon_static", "dimensionless", ("cartesian_row", "cartesian_column")),
    }[label]
    tensor = product.get(field[0])
    if tensor is None:
        return []
    array = np.asarray(tensor, dtype=float)
    if not np.all(np.isfinite(array)):
        return []
    result: list[dict[str, Any]] = []
    for index in np.ndindex(array.shape):
        if label == "born":
            identifier = f"born.atom_{context['atom_ids'][index[0]]}.polarization_{index[1]}.displacement_{index[2]}"
            definition = "Born effective-charge tensor component"
            object_level = "bulk_model_cell_atom"
        elif label == "gamma":
            identifier = f"gamma.row_dof_{index[0]}.column_dof_{index[1]}"
            definition = "Gamma fixed-cell force-constant matrix component"
            object_level = "bulk_model_cell"
        else:
            identifier = f"{label}.row_{index[0]}.column_{index[1]}"
            definition = f"{label} dielectric tensor component"
            object_level = "bulk_model_cell"
        result.append({
            "observable_id": identifier,
            "definition": definition,
            "object_level": object_level,
            "unit": field[1],
            "conditions": {
                "study_id": context["parent"]["study_id"],
                "model_id": context["parent"]["model_id"],
                "model_version": context["parent"]["model_version"],
                "product": label,
                "axes": list(field[2]),
                "indices": list(index),
                **({"response_scope": copy.deepcopy(product["response_scope"])}
                   if "response_scope" in product else {}),
            },
            "value": float(array[index]),
            "uncertainty": None,
            "scientific_status": "unqualified",
            "source_refs": list(refs) or [f"product:{label}"],
        })
    return result


def _p5_nac_observables(
    product: Mapping[str, Any],
    context: Mapping[str, Any],
    refs: list[str],
) -> list[dict[str, Any]]:
    """Expose saved NAC baseline/corrected frequencies as ordinary observables."""

    result: list[dict[str, Any]] = []
    direction = copy.deepcopy(product.get("nac_q_direction"))
    for branch in ("baseline", "corrected"):
        record = product[branch]
        values = np.asarray(record["frequencies_THz"], dtype=float)
        for mode, value in enumerate(values):
            result.append({
                "observable_id": f"nac.{branch}.frequency_mode_{mode}",
                "definition": f"Gamma {branch} phonon frequency with directional Wang NAC context",
                "object_level": "bulk_model_cell_mode",
                "unit": "THz",
                "conditions": {
                    "study_id": context["parent"]["study_id"],
                    "model_id": context["parent"]["model_id"],
                    "model_version": context["parent"]["model_version"],
                    "product": "nac",
                    "branch": branch,
                    "nac_method": product.get("nac_method"),
                    "direction_basis": product.get("direction_basis"),
                    "nac_q_direction": direction,
                    "mode_index": mode,
                },
                "value": float(value),
                "uncertainty": None,
                "scientific_status": "unqualified",
                "source_refs": list(refs) or ["product:nac"],
            })
    return result


def deliver_p5_properties(
    study_path: str | Path,
    request_path: str | Path,
    targets_path: str | Path | None = None,
) -> dict[str, Any]:
    study = _read_json(study_path)
    request = _read_json(request_path)
    if request.get("schema") != _P5_REQUEST_SCHEMA:
        raise ValueError("P5 request schema is unsupported")
    if set(request) - _P5_REQUEST_FIELDS:
        raise ValueError("P5 request contains unsupported fields")
    source_mode = request.get("source_mode")
    if source_mode not in _P5_SOURCE_MODES:
        raise ValueError("P5 request source_mode is unsupported")
    if request.get("study_id") is not None and request.get("study_id") != study.get("study_id"):
        raise ValueError("P5 request study_id differs from Study")
    product_paths = {}
    for label in ("born", "gamma", "nac", "electronic", "ionic", "dielectric"):
        value = request.get(label)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"P5 request {label} path must be a non-empty string")
            product_paths[label] = Path(value).expanduser().resolve()
    products = {label: _read_json(path) for label, path in product_paths.items()}
    if products.get("gamma", {}).get("schema") == "mlcc.czo-native-raw-gamma-force.v001":
        from .dielectric_response import read_native_gamma_force
        products["gamma"] = read_native_gamma_force(product_paths["gamma"])
    if products.get("born", {}).get("schema") == "mlcc.native-born-branch-family.v1":
        from .dielectric_response import read_native_born_family
        products["born"] = read_native_born_family(product_paths["born"])
    born = products.get("born")
    anchor_label = "born" if born is not None else "electronic"
    anchor_name = "Born" if born is not None else "electronic"
    if born is None:
        if (
            source_mode != "native_source_bound"
            or products.get("electronic", {}).get("provenance_kind") != "native_derived"
            or any(label in products for label in ("nac", "ionic"))
        ):
            raise ValueError("P5 without Born requires an independent native electronic contribution")
    anchor_context = _p5_context(products[anchor_label], anchor_label)
    study_id = study.get("study_id")
    model = study.get("model")
    if not isinstance(study_id, str) or not study_id.strip() or not isinstance(model, Mapping):
        raise ValueError("Study study_id and model are required")
    if anchor_context["parent"]["study_id"] != study_id:
        raise ValueError(f"{anchor_name} Study identity differs from Study")
    if (anchor_context["parent"]["model_id"], anchor_context["parent"]["model_version"]) != (model.get("model_id"), model.get("version")):
        raise ValueError(f"{anchor_name} model identity differs from Study model")
    explicit_model_path = model.get("model_path", model.get("path"))
    if explicit_model_path is not None and Path(str(explicit_model_path)).expanduser().resolve() != Path(anchor_context["parent"]["model_path"]):
        raise ValueError(f"{anchor_name} model_path differs from explicit Study model path")
    model_context = _model_context(anchor_context["parent"]["model_path"])
    if (model_context["model_id"], model_context["model_version"], model_context["atom_ids"]) != (
        anchor_context["parent"]["model_id"], anchor_context["parent"]["model_version"], anchor_context["atom_ids"]
    ) or not np.allclose(np.asarray(model_context["cell_angstrom"]), np.asarray(anchor_context["cell_angstrom"]), rtol=0.0, atol=1.0e-7):
        raise ValueError(f"{anchor_name} model artifacts differ from product context")
    _p5_validate_declared_method(products[anchor_label], anchor_label, anchor_context)
    if _p5_declared_mode(products[anchor_label], anchor_label) != source_mode:
        raise ValueError(f"{anchor_name} source_mode differs from request")
    contexts = {anchor_label: anchor_context}
    methods = {anchor_label: copy.deepcopy(anchor_context["common_method"])}
    native_jobs = []
    if born is not None:
        _p5_validate_born(born, anchor_context)
        if source_mode == "native_source_bound":
            native_jobs = _p5_native_born(born, anchor_context)
    for label in ("gamma", "nac", "electronic", "ionic", "dielectric"):
        product = products.get(label)
        if product is None:
            continue
        if label == "electronic" and "provenance_kind" in product:
            from .dielectric_response import bind_external_electronic_input, bind_native_electronic_input
            if product["provenance_kind"] == "native_derived":
                product = bind_native_electronic_input(product, product_paths[label])
            else:
                product = bind_external_electronic_input(product, product_paths[label])
            products[label] = product
        mode = _p5_declared_mode(product, label)
        if mode != source_mode and not (label == "electronic" and mode == "external_supplied"):
            raise ValueError(f"{label} source_mode differs from request")
        context = _p5_context(product, label)
        if not _p5_context_equal(anchor_context, context):
            raise ValueError(f"{label} context differs from {anchor_name} context")
        _p5_validate_declared_method(product, label, context)
        contexts[label] = context
        methods[label] = copy.deepcopy(context["common_method"])
        if label == "gamma":
            _p5_validate_gamma(product, context)
            if mode == "native_source_bound":
                native_jobs.extend(_p5_native_gamma_jobs(product, context))
        elif label == "nac":
            _p5_validate_nac(
                product,
                context,
                born,
                products.get("electronic"),
                born_path=product_paths["born"],
                electronic_path=product_paths.get("electronic"),
            )
            # Native NAC uses the existing Gamma task-record contract.  Let
            # the helper report a missing or malformed record directly rather
            # than silently accepting an unbound native result.
            if mode == "native_source_bound":
                native_jobs.extend(_p5_native_gamma_jobs(product, context))
        elif label == "ionic":
            _p5_validate_ionic(product, born, products.get("gamma"))
        elif label == "electronic" and mode == "native_source_bound":
            if product.get("provenance_kind") != "native_derived":
                raise ValueError("native electronic delivery requires native_derived source binding")
            native_jobs.extend(copy.deepcopy(product["native_jobs"]))
    for label, method in methods.items():
        comparison = _p5_method_comparison(methods[anchor_label], method)
        if comparison.get("same_physical_method") is not True:
            raise ValueError(f"{label} physical method differs from {anchor_name} method")
    from .dielectric_response import combine_dielectric_contributions
    electronic = products.get("electronic")
    ionic = products.get("ionic")
    recombined = combine_dielectric_contributions(
        born,
        electronic,
        ionic,
        electronic_path=product_paths.get("electronic"),
    )
    if recombined["epsilon_static"] is None:
        for label in ("born", "gamma"):
            contribution = products.get(label)
            if contribution is not None and contribution.get("provenance_kind") == "native_derived":
                for reason in contribution["unresolved_reasons"]:
                    qualified_reason = f"{label}:{reason}"
                    if qualified_reason not in recombined["unresolved_reasons"]:
                        recombined["unresolved_reasons"].append(qualified_reason)
    saved_dielectric = products.get("dielectric")
    if saved_dielectric is not None:
        saved_context = _p5_context(saved_dielectric, "dielectric")
        if not _p5_context_equal(anchor_context, saved_context):
            raise ValueError(f"dielectric context differs from {anchor_name} context")
        _p5_validate_dielectric(saved_dielectric, recombined, electronic, ionic)
    requirements = None
    has_design = study.get("design_requirements_ref") not in (None, "") or study.get("design_requirements") not in (None, "", [], {})
    if targets_path is None and has_design:
        raise ValueError("study has design requirements; targets_path must be explicit")
    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets.get("study_id") != study_id:
            raise ValueError("P5 targets study_id differs from Study")
        requirements = targets.get("requirements")
    contexts["dielectric"] = _p5_context(saved_dielectric or recombined, "dielectric")
    methods["dielectric"] = copy.deepcopy(contexts["dielectric"]["common_method"])
    method_comparison = _p5_method_comparison(methods[anchor_label], methods["dielectric"])
    if method_comparison.get("same_physical_method") is not True:
        raise ValueError("dielectric physical method differs from Born method")
    products_out: dict[str, Any] = {
        "born": born,
        "gamma": products.get("gamma"),
        "nac": products.get("nac"),
        "electronic": electronic,
        "ionic": ionic,
        "dielectric": saved_dielectric or recombined,
    }
    statuses: dict[str, Any] = {}
    for label, product in products_out.items():
        if product is None:
            statuses[label] = {"status": "missing", "source_mode": None, "source_paths": [], "unresolved_reasons": ["product_not_supplied"], "scientific_qualification": False, "numerical_qualification": False, "production_qualification": False}
            continue
        if label in {"born", "gamma"} and product.get("provenance_kind") == "native_derived":
            status = product["status"]
        elif label == "born":
            status = "complete" if product.get("full_born_tensors_e") is not None else "unresolved"
        elif label in {"ionic", "dielectric"} or (label == "electronic" and product.get("provenance_kind") == "native_derived"):
            status = product.get("status", "unresolved")
        else:
            status = "complete"
        unresolved_reasons = list(product.get("unresolved_reasons") or [])
        if label == "born" and product.get("full_born_tensors_e") is None:
            if "born_tensor_incomplete" not in unresolved_reasons:
                unresolved_reasons.insert(0, "born_tensor_incomplete")
            for column in product.get("missing_columns", []):
                if isinstance(column, Mapping):
                    for reason in column.get("reasons", []):
                        if isinstance(reason, str) and reason not in unresolved_reasons:
                            unresolved_reasons.append(reason)
        status_mode = (
            "external_supplied"
            if label == "electronic" and product.get("provenance_kind") == "external_supplied"
            else source_mode
        )
        statuses[label] = {"status": status, "source_mode": status_mode, "source_paths": _p5_source_paths(product, label), "unresolved_reasons": unresolved_reasons, "scientific_qualification": False, "numerical_qualification": False, "production_qualification": False}
        if label == "nac" or (label in {"born", "gamma", "electronic"} and product.get("provenance_kind") == "native_derived"):
            statuses[label]["source_paths"].insert(0, str(product_paths[label]))
    include_gamma = any(str(item.get("observable_id", "")).startswith("gamma.") for item in requirements or [])
    observables: list[dict[str, Any]] = []
    for label, product in products_out.items():
        if product is not None and label in contexts:
            observables.extend(_p5_tensor_observables(label, product, contexts[label], statuses[label]["source_paths"], include_gamma or label != "gamma"))
            if label == "nac":
                observables.extend(_p5_nac_observables(product, contexts[label], statuses[label]["source_paths"]))
    assessment = assess_design(requirements, observables)
    return {
        "schema": _P5_DELIVERY_SCHEMA,
        "product_paths": {label: str(path) for label, path in product_paths.items()},
        "study_id": study_id,
        "case_id": study.get("case_id"),
        "case_role": study.get("case_role"),
        "study_path": str(Path(study_path).expanduser().resolve()),
        "request_path": str(Path(request_path).expanduser().resolve()),
        "targets_path": None if targets_path is None else str(Path(targets_path).expanduser().resolve()),
        "source_mode": source_mode,
        "model": {**model_context, "study_model": copy.deepcopy(dict(model))},
        "contexts": {label: contexts.get(label) for label in products_out},
        "methods": {"original": methods, "physical_identity": _p5_method_identity(methods[anchor_label]), "reference_contribution": anchor_label, "comparisons_to_born": {} if born is None else {label: _p5_method_comparison(methods["born"], method) for label, method in methods.items()}, "comparisons_to_reference": {label: _p5_method_comparison(methods[anchor_label], method) for label, method in methods.items()}},
        "products": products_out,
        "product_status": statuses,
        "source_paths": {label: statuses[label]["source_paths"] for label in products_out},
        "native_jobs": native_jobs,
        "observables": observables,
        "design_assessment": assessment["design_assessment"],
        "design_assessment_detail": assessment,
        **({"response_scope": copy.deepcopy(products["gamma"]["response_scope"])}
           if products.get("gamma") is not None and "explicit_processing" in products["gamma"] else {}),
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
        "qualification": {"source_mode": source_mode, "scientific_qualification": False, "numerical_qualification": False, "production_qualification": False},
        "tensor_contract": {
            "born": {"unit": "e", "axes": ["atom_id", "polarization_cartesian_axis", "displacement_cartesian_axis"]},
            "gamma": {"unit": "eV/angstrom^2", "axes": ["row_dof", "column_dof"], "basis": "parent_atom_major_cartesian"},
            "nac": {"unit": "eV/angstrom^2/amu", "axes": ["row_dof", "column_dof"], "basis": "parent_atom_major_cartesian", "frequency_unit": "THz"},
            "electronic": {"unit": "dimensionless", "axes": ["cartesian_row", "cartesian_column"]},
            "ionic": {"unit": "dimensionless", "axes": ["cartesian_row", "cartesian_column"]},
            "dielectric": {"unit": "dimensionless", "axes": ["cartesian_row", "cartesian_column"]},
        },
    }


def deliver_md_properties(
    study_path: str | Path,
    task_path: str | Path,
    request_path: str | Path,
    output_directory: str | Path,
    *,
    window_request_path: str | Path | None = None,
    targets_path: str | Path | None = None,
    collection_path: str | Path | None = None,
) -> dict[str, Any]:
    """Deliver one existing MD task through the direct collection/analysis chain.

    Artifacts are written to a new directory. No native task, model, potential,
    scheduler record or scientific qualification is changed by this function.
    """
    import os

    from .md_conditions import read_md_conditions
    from .md_sources import select_md_sources
    from .md_thermo import analyze_md_thermo
    from .md_trajectory import read_md_collection
    from .tasks import load_task
    from .workflow import inspect_task, require_result_dependencies

    task_file = Path(task_path).resolve()
    if task_file.is_dir():
        task_file = task_file / "task.json"
    task = load_task(task_file)
    study = _read_json(study_path)
    request = _read_json(request_path)
    _bind_task(task.data, study, task_file)
    if task.data["study_id"] != study["study_id"]:
        raise ValueError("MD delivery requires the native task's explicit Study")
    if task.data["case_role"] != study["case_role"]:
        raise ValueError("MD delivery Study case_role differs from native task")
    if study["model"].get("fixture") != task.data["model"].get("fixture"):
        raise ValueError("MD delivery Study model fixture differs from native task")
    continuation = inspect_task(task)
    if continuation["action"] != "completed":
        raise ValueError(f"MD task is not ready for delivery: {continuation['action']}: {continuation['reason']}")
    if task.data["engine"] != "lammps" or task.data["calculation"] != "md":
        raise ValueError("MD delivery requires a native LAMMPS MD task")
    dependencies = require_result_dependencies(task, task_file.parent.parent.parent)
    if request["window"] not in {"whole_record", "equilibration_window", "production_window"}:
        raise ValueError("MD delivery window must be whole_record, equilibration_window or production_window")
    rdf_request = request.get("rdf")
    diagnostics_request = request.get("thermo_diagnostics")
    msd_request = request.get("msd")
    include_thermo = request.get("thermo_summary", True)
    if type(include_thermo) is not bool:
        raise ValueError("MD delivery thermo_summary must be a boolean")
    if not include_thermo and diagnostics_request is not None:
        raise ValueError("thermo_diagnostics requires thermo_summary=true")
    if rdf_request is not None:
        if not isinstance(rdf_request, Mapping) or set(rdf_request) != {"species_pair", "r_edges_angstrom"}:
            raise ValueError("MD delivery rdf must contain only species_pair and r_edges_angstrom")
    if targets_path is None and (study.get("design_requirements_ref") or study.get("design_requirements")):
        raise ValueError("study has design requirements; targets_path must be explicit")
    requirements = None
    if targets_path is not None:
        targets = _read_json(targets_path)
        if targets["study_id"] != study["study_id"]:
            raise ValueError("MD targets study_id differs from Study")
        requirements = targets["requirements"]

    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifacts: dict[str, str] = {}

    def write(name: str, value: Any) -> Path:
        path = output / f"{name}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        artifacts[name] = str(path)
        return path

    source_collection_path = None if collection_path is None else Path(collection_path).resolve()
    collection = (read_md_collection(task_file.parent) if source_collection_path is None
                  else _read_json(source_collection_path))
    if collection["schema"] != "mlcc.md-collection.v1":
        raise ValueError("MD delivery collection schema must be mlcc.md-collection.v1")
    if (collection["task_id"] != task.data["task_id"]
            or collection["native_job"]["scheduler_job_id"] != task.data["scheduler_job_id"]):
        raise ValueError("MD collection task/job identity differs from native task")
    for key in ("model_id", "version"):
        if collection["model"][key] != task.data["model"][key]:
            raise ValueError(f"MD collection model {key} differs from native task")
    method = _read_json(task_file.parent / "method.json")
    for key in ("potential_id", "version"):
        if collection["potential"][key] != method["potential"][key]:
            raise ValueError(f"MD collection potential {key} differs from native task")
    for field in ("study_id", "case_id", "case_role", "method_set"):
        if collection["lineage"][field] != task.data[field]:
            raise ValueError(f"MD collection {field} differs from native task")
    collection_path = write("collection", collection)
    conditions = read_md_conditions(collection_path, window_request_path)
    write("conditions", conditions)
    selection = select_md_sources([collection_path], **request["source"])
    write("source-selection", selection)
    all_elements = set(collection["legacy_final_result"]["elements"])
    if include_thermo and set(request["source"]["elements"]) != all_elements:
        raise ValueError("thermo delivery requires all system elements; element-resolved thermo is unavailable")
    if request["window"] == "whole_record":
        observation_window = {"kind": "whole_record"}
    else:
        selected_window = conditions["windows"][request["window"]]
        observation_window = None if selected_window["selection"] is None else {
            "kind": "step_range", **selected_window["selection"],
        }

    md_rdf = None
    if observation_window is not None and rdf_request is not None:
        from .md_rdf import analyze_md_rdf

        md_rdf = analyze_md_rdf(
            collection_path,
            species_pair=rdf_request["species_pair"],
            r_edges_angstrom=rdf_request["r_edges_angstrom"],
            observation_window=observation_window,
        )
        if md_rdf["source_selection"]["sources"] != selection["sources"]:
            raise ValueError("MD RDF source binding differs from selected source")
        write("md-rdf", md_rdf)

    md_msd = None
    if observation_window is not None and msd_request is not None:
        from .md_msd import analyze_md_msd

        md_msd = analyze_md_msd(
            collection_path, observation_window=observation_window, request=msd_request,
        )
        selected_atom_ids = {
            atom_id for element in selection["sources"][0]["mapping"]["elements"].values()
            for atom_id in element["source_atom_ids"]
        }
        if not set(msd_request["source_atom_ids"]).issubset(selected_atom_ids):
            raise ValueError("MSD atom IDs differ from the selected source elements")
        write("md-msd", md_msd)

    thermo = None
    observables: list[dict[str, Any]] = []
    missing = list(collection["missing_evidence"])
    status = "delivered_engineering_observations"
    if observation_window is None:
        status = "unresolved_missing_observation_window"
    elif include_thermo:
        thermo = analyze_md_thermo(
            collection_path, observation_window=observation_window,
            thermo_diagnostics=diagnostics_request,
        )
        # The analysis and public selection must refer to the same actual
        # source; this comparison never grants replica or scientific status.
        if thermo["source_selection"]["sources"] != selection["sources"]:
            raise ValueError("MD thermo source binding differs from selected source")
        thermo_path = write("thermo", thermo)
        if diagnostics_request is not None:
            write("thermo-diagnostics", thermo["thermo_diagnostics"])
        status = "delivered_engineering_observations"
        source_refs = [str(task_file), str(thermo_path), *collection["source_files"].values()]
        definitions = [
            ("MD_temperature_sample_mean", "arithmetic mean of recorded whole-system temperature samples", "K",
             thermo["quantities"]["temperature"]["sample_mean"]),
            ("MD_total_energy_final_minus_initial", "last minus first total energy in the explicit observation window", "eV",
             thermo["quantities"]["total_energy"]["final_minus_initial"]),
        ]
        for observable_id, definition, unit, value in definitions:
            observables.append({
                "observable_id": observable_id, "definition": definition,
                "object_level": "whole_simulation_cell", "unit": unit,
                "value": value, "uncertainty": None, "scientific_status": "unqualified",
                "conditions": {"ensemble": collection["protocol"]["ensemble"],
                               "observation_window": thermo["observation"]},
                "source_refs": source_refs, "source_task": task.data["task_id"],
                "scheduler_job_id": task.data["scheduler_job_id"],
                "method_set": collection["lineage"]["method_set"],
            })
    if md_msd is not None:
        missing.extend(item for item in md_msd["missing_evidence"] if item not in missing)
        if md_msd["D_m2_per_s"] is not None:
            observables.append({
                "observable_id": "MD_atomic_tracer_diffusivity",
                "definition": "single-trajectory three-dimensional MSD slope / 6 in the explicit Fick window",
                "object_level": "explicit_source_atom_ids", "unit": "m^2/s",
                "value": md_msd["D_m2_per_s"], "uncertainty": None,
                "scientific_status": "unqualified",
                "conditions": {"request": msd_request, "observation_window": observation_window},
                "source_refs": [str(task_file), artifacts["md-msd"], *collection["source_files"].values()],
                "source_task": task.data["task_id"], "scheduler_job_id": task.data["scheduler_job_id"],
                "method_set": collection["lineage"]["method_set"],
            })
        if not include_thermo and md_rdf is None and md_msd["MSD_A2"] is None:
            status = "unresolved"
    assessment = assess_design(requirements, observables)
    result = {
        "schema": "mlcc.md-property-delivery.v1", "status": status,
        "study_id": study["study_id"], "case_id": study["case_id"], "case_role": study["case_role"],
        "task_id": task.data["task_id"], "lineage": collection["lineage"],
        "study_path": str(Path(study_path).resolve()), "task_path": str(task_file),
        "request_path": str(Path(request_path).resolve()),
        "source_collection_path": None if source_collection_path is None else str(source_collection_path),
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "window_request_path": None if window_request_path is None else str(Path(window_request_path).resolve()),
        "native_job": collection["native_job"], "workflow": continuation, "dependencies": dependencies,
        "model": task.data["model"], "potential": method["potential"],
        "model_provenance": "native task model and parent-model references; no potential-training claim",
        "potential_training_from_this_DFT": "not_established",
        "protocol": collection["protocol"], "source_selection": selection,
        "replica_aggregation": selection["replica_aggregation"],
        "conditions": conditions, "windows": conditions["windows"], "md_thermo": thermo,
        "observables": observables, "source_files": collection["source_files"],
        "artifacts": artifacts,
        "missing_evidence": missing,
        "unresolved_qualification": ["material_potential", "sampling_equilibrium", "stationarity",
                                     "statistical_uncertainty", "time_step_convergence"],
        "scientific_status": "unqualified", "production_qualification": False,
        "sampling_equilibrium_qualified": False,
        "design_assessment": assessment["design_assessment"], "design_assessment_detail": assessment,
    }
    if rdf_request is not None:
        result["md_rdf"] = md_rdf
    if msd_request is not None:
        result["msd_request"] = msd_request
        result["md_msd"] = md_msd
        result["msd_status"] = "unresolved_missing_observation_window" if md_msd is None else md_msd["status"]
    result["thermo_summary_requested"] = include_thermo
    if diagnostics_request is not None:
        result["thermo_diagnostics_request"] = diagnostics_request
        result["thermo_diagnostics"] = None if thermo is None else thermo["thermo_diagnostics"]
        result["thermo_diagnostics_status"] = (
            "unresolved_missing_observation_window" if thermo is None else "described_explicit_request"
        )
    ceramic = task.data.get("schema") == "mlcc.ceramic-lammps-task.v1"
    if ceramic:
        card_path = task_file.parent / "model-card.json"
        card = _read_json(card_path)
        if (card.get("training_task_id") != task.data["training_task_id"]
                or str(card.get("job_id")) != task.data["training_job_id"]):
            raise ValueError("ceramic delivery model card training identity differs from native task")
        result["potential_training_from_this_DFT"] = "engineering_source_bound"
        result["model_provenance"] = "native model and explicit ceramic ABACUS training-source collection"
        result["training_provenance"] = {
            **{field: task.data[field] for field in (
                "training_task_id", "training_job_id", "source_system_id", "source_task_id",
                "source_scheduler_job_id", "collection_path", "model_card_path")},
            "saved_model_card": str(card_path),
            "dataset_manifest_path": card["dataset_manifest_path"],
            "source_task_ids": card["dataset_manifest"]["source_task_ids"],
            "source_scheduler_job_ids": card["dataset_manifest"]["source_scheduler_job_ids"],
            "scientific_qualification": False,
            "independent_validation": card["training_plan"]["dataset"]["validation_is_independent"],
        }
    artifacts["delivery"] = str(output / "delivery.json")
    artifacts["report"] = str(output / "report.md")
    write("delivery", result)
    lines = ["# MLCC MD 工程观测结果", "", f"Study: {study['study_id']}",
             f"原生任务: {task.data['task_id']} / Slurm {task.data['scheduler_job_id']}",
             f"状态: {status}", f"模型: {collection['model']['model_id']}",
             f"势: {collection['potential']['potential_id']} / {collection['potential']['version']}",
             f"观测窗口请求: {request['window']}", f"实际观测范围: {observation_window}",
             "", "| 观测量 | 数值 | 单位 |", "| --- | --- | --- |"]
    lines.extend(f"| {item['observable_id']} | {item['value']} | {item['unit']} |" for item in observables)
    if msd_request is not None:
        lines.extend(["", f"原子示踪MSD: {result['msd_status']}",
                      f"显式source atom IDs: {msd_request['source_atom_ids']}",
                      "MSD、显式Fick诊断、D和原生来源见md-msd.json。"
                      if md_msd is not None else "观察窗口缺失，MSD未计算。"])
    if diagnostics_request is not None:
        lines.extend(["", f"热力学诊断: {result['thermo_diagnostics_status']}",
                      f"后处理 Slurm: {result['analysis_scheduler_job_id']}",
                      "显式块统计、时间漂移、异常索引及请求参数见 thermo-diagnostics.json；原始样本保留。"
                      if thermo is not None else "窗口缺失，诊断值为 null。"])
    if rdf_request is None:
        lines.append("RDF: 未请求。")
    elif md_rdf is None:
        lines.append("RDF: unresolved_missing_observation_window；未计算，不隐式改用 whole_record。")
    else:
        rdf_grid = md_rdf["grid"]
        first_peak = md_rdf["first_peak"]
        lines.extend([
            "",
            f"RDF: {md_rdf['species_pair']}，r范围 [0, {rdf_grid['r_max_angstrom']}] Å；"
            f"first_peak={first_peak['status']}。",
            "RDF仅为显式窗口内的工程观察；不等同于完整配位数或材料科学资格。",
        ])
    lines.extend(["", "结果仅描述显式窗口内的全体系记录；没有平衡、势或生产资格。",
                  (f"陶瓷工程训练来源已绑定：训练作业{task.data['training_job_id']}；材料势仍未获得科学资格。"
                   if ceramic else "模型结构来源与势训练来源独立；本任务不证明 EAM/MACE 来自本项目 DFT 训练。"),
                  f"设计评估: {assessment['design_assessment']}；replica: {selection['replica_aggregation']['status']}。",
                  "", "各阶段JSON和原生来源见 delivery.json。缺失窗口不自动改用全记录。"])
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


__all__ = [
    "assess_design",
    "deliver_defect_references",
    "deliver_electronic_properties",
    "deliver_magnetic_properties",
    "deliver_transport_properties",
    "deliver_dielectric_modes",
    "deliver_composition_product",
    "deliver_vacancy_migration",
    "deliver_continuum_package",
    "deliver_interface_inputs",
    "deliver_interface_normal",
    "deliver_interface_tangential",
    "deliver_interface_thermal",
    "deliver_interface_electrical",
    "deliver_local_stress",
    "deliver_domain_parameters",
    "deliver_thermal_stress",
    "deliver_berry_polarization",
    "deliver_p5_properties",
    "deliver_md_properties",
    "deliver_charge_properties",
]
