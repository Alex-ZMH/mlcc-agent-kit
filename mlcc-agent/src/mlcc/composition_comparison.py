"""Compare saved properties across one composition family.

The comparison layer deliberately consumes saved JSON records only.  It does
not read native task outputs, compare bare total energies, infer method
compatibility, or fill missing values.  Method comparison is an explicit
input supplied by the caller (normally the shared method adapter).
"""

from __future__ import annotations

import copy
import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA = "mlcc.composition-comparison.v1"
REQUEST_SCHEMA = "mlcc.composition-comparison-request.v1"


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {source}")
    return value


def _path_value(record: Mapping[str, Any], path: str, name: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not part:
            raise ValueError(f"{name} must be a dotted field path")
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _finite_scalar(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite scalar or numeric tensor")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _numeric_value(value: Any, name: str) -> tuple[Any, tuple[int, ...]]:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain finite numeric values")
    return array.astype(float).tolist(), tuple(array.shape)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _map_numeric(value: Any, operation: Any) -> Any:
    result = operation(np.asarray(value, dtype=float))
    if np.ndim(result) == 0:
        return float(result)
    return np.asarray(result, dtype=float).tolist()


def _subtract(left: Any, right: Any) -> Any:
    result = np.asarray(left, dtype=float) - np.asarray(right, dtype=float)
    if np.ndim(result) == 0:
        return float(result)
    return result.tolist()


def _divide(left: Any, right: Any) -> Any:
    result = np.asarray(left, dtype=float) / np.asarray(right, dtype=float)
    if np.ndim(result) == 0:
        return float(result)
    return result.tolist()


def _contains_zero(value: Any) -> bool:
    return bool(np.any(np.asarray(value, dtype=float) == 0.0))


def _rotation_matrix(value: Any, name: str) -> list[list[float]]:
    numeric, shape = _numeric_value(value, name)
    if shape != (3, 3):
        raise ValueError(f"{name} must be a 3x3 rotation matrix")
    matrix = np.asarray(numeric, dtype=float)
    if not np.allclose(matrix.T @ matrix, np.eye(3), rtol=0.0, atol=1.0e-8):
        raise ValueError(f"{name} must be orthonormal")
    if not math.isclose(float(np.linalg.det(matrix)), 1.0, rel_tol=0.0, abs_tol=1.0e-8):
        raise ValueError(f"{name} must have positive unit determinant")
    return matrix.tolist()


def _rotate_second_order(value: Any, source_basis: Mapping[str, Any], target_basis: Mapping[str, Any], name: str) -> tuple[Any, str | None]:
    if source_basis == target_basis:
        return value, None
    transform = source_basis.get("rotation_to_common")
    if transform is None or source_basis.get("common_basis") != target_basis:
        return None, f"{name}.basis_rotation_unsupported"
    rotation = _rotation_matrix(transform, f"{name}.rotation_to_common")
    result = np.asarray(rotation, dtype=float) @ np.asarray(value, dtype=float) @ np.asarray(rotation, dtype=float).T
    return result.tolist(), None


def _composition(model: Mapping[str, Any], name: str) -> dict[str, float]:
    value = model.get("composition")
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name}.composition is required for explicit normalization")
    composition: dict[str, float] = {}
    for element, amount in value.items():
        symbol = _text(element, f"{name}.composition.element")
        number = _finite_scalar(amount, f"{name}.composition.{symbol}")
        if number <= 0.0:
            raise ValueError(f"{name}.composition.{symbol} must be positive")
        composition[symbol] = number
    return composition


def _normalization_factor(
    normalization: Mapping[str, Any], name: str, model: Mapping[str, Any] | None = None
) -> tuple[float, str]:
    kind = _text(normalization.get("kind"), f"{name}.kind")
    if kind == "none":
        return 1.0, "none"
    if kind == "divide":
        denominator = _finite_scalar(normalization.get("denominator"), f"{name}.denominator")
        if denominator <= 0.0:
            raise ValueError(f"{name}.denominator must be positive")
        return denominator, "divide"
    if kind == "per_atom":
        if model is None:
            raise ValueError(f"{name} requires a model for per_atom normalization")
        composition = _composition(model, name)
        return sum(composition.values()), "per_atom"
    if kind == "per_formula_unit":
        if model is None:
            raise ValueError(f"{name} requires a model for per_formula_unit normalization")
        formula = normalization.get("formula")
        if not isinstance(formula, Mapping) or not formula:
            raise ValueError(f"{name}.formula must be an explicit stoichiometric object")
        composition = _composition(model, name)
        ratios: list[float] = []
        for element, amount in formula.items():
            symbol = _text(element, f"{name}.formula.element")
            stoich = _finite_scalar(amount, f"{name}.formula.{symbol}")
            if stoich <= 0.0 or symbol not in composition:
                raise ValueError(f"{name}.formula.{symbol} must match model composition")
            ratios.append(composition[symbol] / stoich)
        if set(composition) != {_text(element, f"{name}.formula.element") for element in formula}:
            raise ValueError(f"{name}.formula must cover the complete model composition")
        if not ratios or any(not math.isclose(value, ratios[0], rel_tol=1e-9, abs_tol=1e-9) for value in ratios[1:]):
            raise ValueError(f"{name}.formula is inconsistent with model composition")
        return ratios[0], "per_formula_unit"
    raise ValueError(f"{name}.kind is unsupported: {kind!r}")


def _validate_normalization_spec(normalization: Mapping[str, Any], name: str) -> None:
    kind = _text(normalization.get("kind"), f"{name}.kind")
    if kind == "none":
        return
    if kind == "divide":
        denominator = _finite_scalar(normalization.get("denominator"), f"{name}.denominator")
        if denominator <= 0.0:
            raise ValueError(f"{name}.denominator must be positive")
        return
    if kind == "per_atom":
        return
    if kind == "per_formula_unit":
        if not isinstance(normalization.get("formula"), Mapping) or not normalization["formula"]:
            raise ValueError(f"{name}.formula must be an explicit stoichiometric object")
        return
    raise ValueError(f"{name}.kind is unsupported: {kind!r}")


def _model_identity(model: Mapping[str, Any], name: str) -> str:
    return f"{_text(model.get('model_id'), f'{name}.model_id')}:{_text(model.get('version'), f'{name}.version')}"


def _explicit_family_id(record: Mapping[str, Any], model: Mapping[str, Any], name: str) -> str | None:
    for owner, value in (
        ("record", record.get("family_id")),
        ("record", record.get("composition_family")),
        ("model", model.get("family_id")),
        ("model", model.get("composition_family")),
    ):
        if value is not None:
            return _text(value, f"{name}.{owner}.family_id")
    return None


def _parent_identities(model: Mapping[str, Any], name: str) -> set[str]:
    parents: list[Any] = []
    if model.get("parent_model") is not None:
        parents.append(model.get("parent_model"))
    if model.get("parent_models") is not None:
        value = model.get("parent_models")
        if not isinstance(value, list):
            raise ValueError(f"{name}.parent_models must be a list")
        parents.extend(value)
    identities: set[str] = set()
    for index, parent in enumerate(parents):
        item = _mapping(parent, f"{name}.parent[{index}]")
        identities.add(
            f"{_text(item.get('model_id'), f'{name}.parent[{index}].model_id')}:{_text(item.get('version'), f'{name}.parent[{index}].version')}"
        )
    return identities


def _reference_identities(model: Mapping[str, Any], name: str) -> set[str]:
    references: list[Any] = []
    for owner, value in (
        ("model", model.get("reference_model")),
        ("model", model.get("composition_reference_model")),
    ):
        if value is not None:
            references.append((owner, value))
    identities: set[str] = set()
    for owner, value in references:
        item = _mapping(value, f"{name}.{owner}.reference_model")
        identities.add(
            f"{_text(item.get('model_id'), f'{name}.{owner}.reference_model.model_id')}:{_text(item.get('version'), f'{name}.{owner}.reference_model.version')}"
        )
    return identities


def _record_model(record: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    model = record.get("model")
    if model is None:
        model = record.get("model_record")
    if model is None:
        raise ValueError(f"{name}.model is required")
    return _mapping(model, f"{name}.model")


def _record_model_ref(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Return the saved model reference without replacing the model record."""
    reference = record.get("model_ref")
    if reference is not None:
        value = dict(_mapping(reference, f"{name}.model_ref"))
    else:
        model = _record_model(record, name)
        value = {
            "model_id": model.get("model_id"),
            "version": model.get("version"),
        }
        if record.get("model_path") is not None:
            value["path"] = record["model_path"]
    return value


def _record_product(record: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    product = record.get("product")
    if product is None:
        product = record.get("product_record")
    if product is None:
        raise ValueError(f"{name}.product is required")
    return _mapping(product, f"{name}.product")


def _reference_identity(reference: Any, name: str) -> str:
    item = _mapping(reference, name)
    return f"{_text(item.get('model_id'), f'{name}.model_id')}:{_text(item.get('version'), f'{name}.version')}"


def _product_model_references(product: Mapping[str, Any], name: str) -> list[str]:
    references: list[Any] = []
    for field in ("model_ref", "parent_model"):
        if product.get(field) is not None:
            references.append((field, product[field]))
    model_refs = product.get("model_refs")
    if model_refs is not None:
        if isinstance(model_refs, Mapping):
            references.append(("model_refs", model_refs))
        elif isinstance(model_refs, list):
            references.extend((f"model_refs[{index}]", value) for index, value in enumerate(model_refs))
        else:
            raise ValueError(f"{name}.product.model_refs must be an object or list")
    context = product.get("context")
    if isinstance(context, Mapping) and context.get("parent") is not None:
        parent = context["parent"]
        references.append(("context.parent", {
            "model_id": parent["model_id"],
            "version": parent["model_version"],
        }))
    return [_reference_identity(value, f"{name}.product.{field}") for field, value in references]


def _validate_record_bindings(record: Mapping[str, Any], name: str, *, expected_study_id: str | None = None) -> None:
    model = _record_model(record, name)
    product = _record_product(record, name)
    identity = _model_identity(model, name)
    record_ref = record.get("model_ref")
    if record_ref is not None and _reference_identity(record_ref, f"{name}.model_ref") != identity:
        raise ValueError(f"{name}.model_ref does not match saved model")
    product_refs = _product_model_references(product, name)
    if not product_refs:
        raise ValueError(f"{name}.product requires model_ref, model_refs, or context.parent")
    if identity not in product_refs:
        raise ValueError(f"{name}.product model reference does not match saved model")
    study_ids = [value for value in (record.get("study_id"), model.get("study_id"), product.get("study_id")) if value is not None]
    context = product.get("context")
    if isinstance(context, Mapping) and isinstance(context.get("parent"), Mapping):
        context_study = context["parent"].get("study_id")
        if context_study is not None:
            study_ids.append(context_study)
    study = record.get("study")
    if isinstance(study, Mapping):
        if study.get("study_id") is not None:
            study_ids.append(study.get("study_id"))
        for field in ("model", "model_ref", "parent_model"):
            study_model = study.get(field)
            if isinstance(study_model, Mapping) and (study_model.get("model_id") is not None or study_model.get("version") is not None):
                if _reference_identity(study_model, f"{name}.study.{field}") != identity:
                    raise ValueError(f"{name}.study model reference does not match saved model")
    if len(set(study_ids)) > 1:
        raise ValueError(f"{name} saved model, product and Study identities differ")
    if expected_study_id is not None and any(value != expected_study_id for value in study_ids):
        raise ValueError(f"{name} is not bound to baseline study")


def _source_declaration(product: Mapping[str, Any], property_id: str, name: str) -> Mapping[str, Any] | None:
    declarations = product.get("source_declarations")
    if not isinstance(declarations, Mapping):
        return None
    declaration = declarations.get(property_id)
    if declaration is None:
        return None
    value = _mapping(declaration, f"{name}.product.source_declarations.{property_id}")
    source = value.get("source", value.get("source_ref"))
    _text(source, f"{name}.product.source_declarations.{property_id}.source")
    return value


def _source_status(product: Mapping[str, Any]) -> dict[str, Any]:
    reasons = product.get("unresolved_reasons", [])
    if reasons is None:
        reasons = []
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise ValueError("product.unresolved_reasons must be a list of strings")
    return {
        "status": product.get("status", product.get("scientific_status")),
        "unresolved_reasons": copy.deepcopy(reasons),
        "production_qualified": product.get("production_qualified"),
        "source_refs": copy.deepcopy(product.get("source_refs", [])),
    }


def _property_metadata(product: Mapping[str, Any], property_id: str) -> Mapping[str, Any] | None:
    for container_name in ("property_metadata", "properties"):
        container = product.get(container_name)
        if isinstance(container, Mapping) and isinstance(container.get(property_id), Mapping):
            return container[property_id]
    return None


def _validate_property_definition(spec: Mapping[str, Any], name: str) -> dict[str, Any]:
    property_id = _text(spec.get("property_id"), f"{name}.property_id")
    field = _text(spec.get("field"), f"{name}.field")
    definition = _text(spec.get("definition"), f"{name}.definition")
    unit = _text(spec.get("unit"), f"{name}.unit")
    object_level = _text(spec.get("object_level"), f"{name}.object_level")
    conditions = spec.get("conditions")
    if not isinstance(conditions, Mapping):
        raise ValueError(f"{name}.conditions must be an object")
    normalization = spec.get("normalization")
    if not isinstance(normalization, Mapping):
        raise ValueError(f"{name}.normalization must be an object")
    _validate_normalization_spec(normalization, f"{name}.normalization")
    basis = spec.get("basis")
    if basis is not None and not isinstance(basis, Mapping):
        raise ValueError(f"{name}.basis must be an object when supplied")
    if basis is not None and not basis:
        raise ValueError(f"{name}.basis must not be empty when supplied")
    energy_kind = spec.get("energy_kind")
    field_lower = field.lower()
    if "total_energy" in field_lower:
        raise ValueError("bare total energy cannot be compared across compositions")
    if field_lower in {"energy", "energy_ev"} and energy_kind not in {
        "formation_energy",
        "binding_energy",
    }:
        raise ValueError("bare total energy cannot be compared across compositions")
    return {
        "property_id": property_id,
        "field": field,
        "definition": definition,
        "unit": unit,
        "object_level": object_level,
        "conditions": copy.deepcopy(dict(conditions)),
        "normalization": copy.deepcopy(dict(normalization)),
        "basis": None if basis is None else copy.deepcopy(dict(basis)),
        "energy_kind": energy_kind,
        "relative": bool(spec.get("relative", False)),
    }


def _metadata_compatible(
    spec: Mapping[str, Any],
    metadata: Mapping[str, Any] | None,
    name: str,
    *,
    include_basis: bool = True,
) -> tuple[bool, str | None]:
    if metadata is None:
        return True, None
    fields = ["definition", "unit", "object_level", "conditions"]
    if include_basis:
        fields.append("basis")
    for field in fields:
        if field in metadata and metadata[field] != spec.get(field):
            return False, f"{name}.{field}_differs_from_selected_definition"
    return True, None


def _source_refs(record: Mapping[str, Any], product: Mapping[str, Any], record_name: str) -> list[str]:
    refs: list[str] = []
    for value in (record.get("source_refs", []), product.get("source_refs", [])):
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and item and item not in refs:
                refs.append(item)
    declarations = product.get("source_declarations")
    if isinstance(declarations, Mapping):
        for property_source in declarations.values():
            if isinstance(property_source, Mapping):
                source = property_source.get("source", property_source.get("source_ref"))
                if isinstance(source, str) and source and source not in refs:
                    refs.append(source)
    return refs


def _observation(record: Mapping[str, Any], spec: Mapping[str, Any], name: str) -> dict[str, Any]:
    product = _record_product(record, name)
    raw = _path_value(product, str(spec["field"]), f"{name}.{spec['property_id']}.field")
    source = _source_status(product)
    metadata = _property_metadata(product, str(spec["property_id"]))
    declaration = _source_declaration(product, str(spec["property_id"]), name)
    observation: dict[str, Any] = {
        "record_id": _text(record.get("id"), f"{name}.id"),
        "field": spec["field"],
        "definition": spec["definition"],
        "unit": spec["unit"],
        "object_level": spec["object_level"],
        "conditions": copy.deepcopy(spec["conditions"]),
        "normalization": copy.deepcopy(spec["normalization"]),
        "basis": copy.deepcopy(spec["basis"]),
        "source_basis": None if metadata is None else copy.deepcopy(metadata.get("basis")),
        "source_metadata": None if metadata is None else copy.deepcopy(dict(metadata)),
        "raw_value": copy.deepcopy(raw),
        "value": None,
        "shape": None,
        "normalization_factor": None,
        "normalization_basis": None,
        "source": source,
        "source_declaration": None if declaration is None else copy.deepcopy(dict(declaration)),
        "status": "complete",
        "reason": None,
    }
    compatible, reason = _metadata_compatible(spec, metadata, name, include_basis=False)
    if not compatible:
        observation["status"], observation["reason"] = "incomparable", reason
        return observation
    if metadata is None:
        observation["status"], observation["reason"] = "unresolved", "property_metadata_missing"
        return observation
    if any(field not in metadata for field in ("definition", "unit", "object_level", "conditions")):
        observation["status"], observation["reason"] = "unresolved", "property_metadata_incomplete"
        return observation
    if declaration is None:
        observation["status"], observation["reason"] = "unresolved", "source_declaration_missing"
        return observation
    if raw is None:
        observation["status"], observation["reason"] = "unresolved", "property_value_missing"
        return observation
    numeric, shape = _numeric_value(raw, f"{name}.{spec['property_id']}")
    if shape not in {(), (3, 3), (6, 6)}:
        raise ValueError(
            f"{name}.{spec['property_id']} must be a scalar, 3x3 tensor, or 6x6 Voigt tensor"
        )
    if shape != () and spec["basis"] is None:
        raise ValueError(f"{name}.{spec['property_id']} tensor requires an explicit basis")
    if shape == (6, 6):
        voigt_order = spec["basis"].get("voigt_order")
        if not _is_sequence(voigt_order) or len(voigt_order) != 6 or any(not isinstance(item, str) or not item for item in voigt_order):
            raise ValueError(f"{name}.{spec['property_id']} requires an explicit six-entry voigt_order")
        if spec["basis"].get("shear_convention") != "engineering":
            raise ValueError(f"{name}.{spec['property_id']} requires engineering shear convention")
    if shape != ():
        if metadata is None or not isinstance(metadata.get("basis"), Mapping):
            observation["status"], observation["reason"] = "incomparable", "source_basis_missing"
            return observation
        if shape == (6, 6) and metadata["basis"] != spec["basis"]:
            observation["status"], observation["reason"] = "incomparable", "voigt_basis_rotation_unsupported"
            return observation
        if shape == (3, 3):
            numeric, alignment_reason = _rotate_second_order(
                numeric,
                metadata["basis"],
                spec["basis"],
                f"{name}.{spec['property_id']}",
            )
            if alignment_reason is not None:
                observation["status"], observation["reason"] = "incomparable", alignment_reason
                return observation
    model = _record_model(record, name)
    denominator, normalization_kind = _normalization_factor(
        spec["normalization"], f"{name}.{spec['property_id']}.normalization", model
    )
    observation["value"] = _map_numeric(numeric, lambda item: item / denominator)
    observation["shape"] = list(shape)
    observation["normalization_factor"] = denominator
    observation["normalization_basis"] = normalization_kind
    return observation


def _family(record: Mapping[str, Any], name: str) -> tuple[str, str]:
    model = _record_model(record, name)
    explicit = _explicit_family_id(record, model, name)
    if explicit is not None:
        return "family_id", explicit
    return "model", _model_identity(model, name)


def _same_composition_family(
    baseline_record: Mapping[str, Any],
    variant_record: Mapping[str, Any],
    baseline_name: str,
    variant_name: str,
) -> bool:
    baseline_model = _record_model(baseline_record, baseline_name)
    variant_model = _record_model(variant_record, variant_name)
    baseline_explicit = _explicit_family_id(baseline_record, baseline_model, baseline_name)
    variant_explicit = _explicit_family_id(variant_record, variant_model, variant_name)
    baseline_identity = _model_identity(baseline_model, baseline_name)
    variant_parents = _parent_identities(variant_model, variant_name)
    variant_references = _reference_identities(variant_model, variant_name)
    direct_lineage = baseline_identity in variant_parents or baseline_identity in variant_references
    if baseline_explicit is not None or variant_explicit is not None:
        if baseline_explicit is not None and variant_explicit is not None:
            return baseline_explicit == variant_explicit and (
                baseline_identity == _model_identity(variant_model, variant_name) or direct_lineage
            )
        return direct_lineage
    return (
        baseline_identity == _model_identity(variant_model, variant_name)
        or direct_lineage
    )


def compare_composition_properties(
    baseline: Mapping[str, Any],
    variants: Sequence[Mapping[str, Any]],
    selected_properties: Sequence[Mapping[str, Any]],
    *,
    method_comparison: Mapping[str, Any] | None = None,
    analysis_scheduler_job_id: str | None = None,
) -> dict[str, Any]:
    """Compare saved scalar/tensor fields for one explicit model family."""
    baseline_record = _mapping(baseline, "baseline")
    if not _is_sequence(variants) or not variants:
        raise ValueError("variants must be a non-empty list")
    variant_records = [_mapping(item, f"variants[{index}]") for index, item in enumerate(variants)]
    if not _is_sequence(selected_properties):
        raise ValueError("selected_properties must be a non-empty list")
    specs = [
        _validate_property_definition(
            _mapping(item, f"selected_properties[{index}]"),
            f"selected_properties[{index}]",
        )
        for index, item in enumerate(selected_properties)
    ]
    if not specs:
        raise ValueError("selected_properties must not be empty")
    if method_comparison is not None and not isinstance(method_comparison, Mapping):
        raise ValueError("method_comparison must be an explicit object when supplied")
    baseline_study_id = baseline_record.get("study_id")
    if baseline_study_id is not None:
        baseline_study_id = _text(baseline_study_id, "baseline.study_id")
    _validate_record_bindings(baseline_record, "baseline", expected_study_id=baseline_study_id)
    for index, item in enumerate(variant_records):
        _validate_record_bindings(item, f"variants[{index}]")
    baseline_family = _family(baseline_record, "baseline")
    if any(
        not _same_composition_family(baseline_record, item, "baseline", f"variants[{index}]")
        for index, item in enumerate(variant_records)
    ):
        raise ValueError("baseline and variants must belong to one composition family")
    baseline_model = _record_model(baseline_record, "baseline")
    baseline_product = _record_product(baseline_record, "baseline")
    comparisons: list[dict[str, Any]] = []
    unresolved_reasons: list[str] = []
    for spec in specs:
        base_observation = _observation(baseline_record, spec, "baseline")
        for index, variant in enumerate(variant_records):
            variant_observation = _observation(variant, spec, f"variants[{index}]")
            entry: dict[str, Any] = {
                "property_id": spec["property_id"],
                "variant_id": variant_observation["record_id"],
                "baseline": base_observation,
                "variant": variant_observation,
                "difference": None,
                "relative_difference": None,
                "status": "complete",
                "reason": None,
            }
            if base_observation["status"] != "complete":
                entry["status"], entry["reason"] = base_observation["status"], f"baseline:{base_observation['reason']}"
            elif variant_observation["status"] != "complete":
                entry["status"], entry["reason"] = variant_observation["status"], f"variant:{variant_observation['reason']}"
            elif base_observation["shape"] != variant_observation["shape"]:
                entry["status"], entry["reason"] = "incomparable", "value_shapes_differ"
            else:
                entry["difference"] = _subtract(variant_observation["value"], base_observation["value"])
                if spec["relative"]:
                    if _contains_zero(base_observation["value"]):
                        entry["status"], entry["reason"] = "unresolved", "baseline_value_zero_relative_undefined"
                    else:
                        entry["relative_difference"] = _divide(entry["difference"], base_observation["value"])
            if entry["status"] != "complete" and entry["reason"] not in unresolved_reasons:
                unresolved_reasons.append(str(entry["reason"]))
            comparisons.append(entry)
    source_refs = []
    for record, name in [(baseline_record, "baseline"), *[(item, f"variant:{index}") for index, item in enumerate(variant_records)]]:
        source_refs.extend(value for value in _source_refs(record, _record_product(record, name), name) if value not in source_refs)
    return {
        "schema": SCHEMA,
        "operation": "saved_composition_property_comparison",
        "status": "complete" if not unresolved_reasons else "unresolved",
        "unresolved_reasons": unresolved_reasons,
        "study_id": baseline_record.get("study_id"),
        "family": {"kind": baseline_family[0], "id": baseline_family[1]},
        "selected_properties": copy.deepcopy(specs),
        "baseline": {
            "id": _text(baseline_record.get("id"), "baseline.id"),
            "study_id": baseline_record.get("study_id"),
            "model_ref": _record_model_ref(baseline_record, "baseline"),
            "method_path": baseline_record.get("method_path"),
            "model": copy.deepcopy(dict(baseline_model)),
            "product_status": _source_status(baseline_product),
        },
        "variants": [
            {
                "id": _text(item.get("id"), f"variants[{index}].id"),
                "study_id": item.get("study_id"),
                "model_ref": _record_model_ref(item, f"variants[{index}]"),
                "method_path": item.get("method_path"),
                "model": copy.deepcopy(dict(_record_model(item, f"variants[{index}]"))),
                "product_status": _source_status(_record_product(item, f"variants[{index}]")),
            }
            for index, item in enumerate(variant_records)
        ],
        "comparisons": comparisons,
        "method_comparison": None if method_comparison is None else copy.deepcopy(dict(method_comparison)),
        "source_refs": source_refs,
        "analysis_scheduler_job_id": analysis_scheduler_job_id,
        "production_qualified": False,
    }


def analyze_composition_comparison_request(request_path: str | Path) -> dict[str, Any]:
    """Load a saved comparison request and delegate to the pure comparator."""
    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("unsupported composition comparison request")
    record_kind = _text(request.get("record_kind"), "record_kind")
    if record_kind not in {"native", "configuration"}:
        raise ValueError("record_kind must be 'native' or 'configuration'")

    def load_record(value: Any, name: str) -> dict[str, Any]:
        item = _mapping(value, name)
        record = dict(item)
        model_ref = item.get("model_ref")
        if model_ref is None:
            raise ValueError(f"{name}.model_ref is required")
        ref = dict(_mapping(model_ref, f"{name}.model_ref"))
        model_source_value = ref.get("path")
        if model_source_value is None:
            raise ValueError(f"{name}.model_ref.path is required")
        model_source = Path(_text(model_source_value, f"{name}.model_ref.path"))
        model_source = model_source if model_source.is_absolute() else request_file.parent / model_source
        record["model_ref"] = ref
        record["model_ref"]["path"] = str(model_source.expanduser().resolve())
        record["model_path"] = record["model_ref"]["path"]
        for field in ("model_path", "product_path", "study_path"):
            if field in item and item[field] is not None:
                source = Path(_text(item[field], f"{name}.{field}"))
                source = source if source.is_absolute() else request_file.parent / source
                record[field] = str(source.expanduser().resolve())
        if "model_path" not in record or "product_path" not in record:
            raise ValueError(f"{name} requires model_path and product_path")
        record["model"] = _read_json(record["model_path"])
        if record.get("model_ref") is not None:
            model = record["model"]
            for field in ("model_id", "version"):
                expected = record["model_ref"].get(field)
                if expected is not None and model.get(field) != expected:
                    raise ValueError(f"{name}.model_ref.{field} differs from saved model")
        record["product"] = _read_json(record["product_path"])
        if record.get("study_id") is None and record["product"].get("study_id") is not None:
            record["study_id"] = record["product"].get("study_id")
        method_path_value = item.get("method_path")
        if method_path_value is None:
            raise ValueError(f"{name}.method_path is required")
        method_source = Path(_text(method_path_value, f"{name}.method_path"))
        method_source = method_source if method_source.is_absolute() else request_file.parent / method_source
        record["method_path"] = str(method_source.expanduser().resolve())
        record["method"] = _read_json(record["method_path"])
        if record_kind == "native":
            if _model_identity(record["method"], f"{name}.method") != _model_identity(record["model"], f"{name}.model"):
                raise ValueError(f"{name}.native method identity differs from saved model")
            if record["product"].get("method_set") is not None and record["product"]["method_set"] != record["method"]["method_set"]:
                raise ValueError(f"{name}.native method_set differs from saved product")
        if "study_path" in record:
            record["study"] = _read_json(record["study_path"])
            if record.get("study_id") is None:
                record["study_id"] = record["study"].get("study_id")
        record.setdefault("source_refs", []).extend([record["model_path"], record["product_path"], record["method_path"]])
        if record.get("study_path"):
            record["source_refs"].append(record["study_path"])
        return record

    baseline = load_record(request.get("baseline"), "baseline")
    variants_value = request.get("variants")
    if not isinstance(variants_value, list):
        raise ValueError("variants must be a list")
    variants = [load_record(item, f"variants[{index}]") for index, item in enumerate(variants_value)]
    if request.get("study_id") is not None:
        requested_study_id = _text(request.get("study_id"), "study_id")
        if baseline.get("study_id") is not None and baseline["study_id"] != requested_study_id:
            raise ValueError("study_id differs from baseline study")
        baseline["study_id"] = requested_study_id
    from .defect_thermodynamics import compare_variant_method_records

    host_elements = _composition(_record_model(baseline, "baseline"), "baseline.model")
    method_comparison_variants: list[dict[str, Any]] = []
    for index, variant in enumerate(variants):
        defect_elements = _composition(_record_model(variant, f"variants[{index}]"), f"variants[{index}].model")
        method_result = compare_variant_method_records(
            baseline["method"],
            variant["method"],
            host_elements=host_elements,
            defect_elements=defect_elements,
            record_kind=record_kind,
        )
        method_comparison_variants.append({
            "variant_id": _text(variant.get("id"), f"variants[{index}].id"),
            "host_method_path": baseline["method_path"],
            "variant_method_path": variant["method_path"],
            "defect_elements": defect_elements,
            "result": copy.deepcopy(dict(method_result)),
        })
    method_comparison = {
        "record_kind": record_kind,
        "host_method_path": baseline["method_path"],
        "host_elements": host_elements,
        "variants": method_comparison_variants,
    }
    result = compare_composition_properties(
        baseline,
        variants,
        request.get("selected_properties"),
        method_comparison=method_comparison,
        analysis_scheduler_job_id=os.environ.get("SLURM_JOB_ID"),
    )
    result["method_confounded"] = any(not item["result"]["passed"] for item in method_comparison_variants)
    result["source_refs"] = [str(request_file), *[ref for ref in result["source_refs"] if ref != str(request_file)]]
    return result


__all__ = ["REQUEST_SCHEMA", "SCHEMA", "analyze_composition_comparison_request", "compare_composition_properties"]
