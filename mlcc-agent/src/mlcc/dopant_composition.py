"""Explicit integer composition plans for selected parent structures.

This module is a thin composition layer over the existing exact supercell and
explicit defect derivation functions.  It never chooses sites, rounds a
fractional concentration, creates an SQS, or invents a compensation state.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .model_derivatives import _integer_matrix, derive_defect_model, derive_supercell_model
from .modeling import read_model_artifacts


REQUEST_SCHEMA = "mlcc.dopant-composition-request.v1"
PLAN_SCHEMA = "mlcc.dopant-composition-plan.v1"
BUILD_SCHEMA = "mlcc.composition-build.v1"


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _integer(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _integer_vector(value: Any, name: str, length: int = 3) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != length:
        raise ValueError(f"{name} must contain {length} integers")
    return [_integer(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _matrix(value: Any) -> list[list[int]]:
    integer = _integer_matrix(value)
    return [[int(item) for item in row] for row in integer.tolist()]


def _matrix_determinant(matrix: Sequence[Sequence[int]]) -> int:
    """Return the exact determinant of the validated 3x3 repeat matrix."""

    a, b, c = (int(item) for item in matrix[0])
    d, e, f = (int(item) for item in matrix[1])
    g, h, i = (int(item) for item in matrix[2])
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _atom_ids(value: Any, name: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    result = [_integer(item, f"{name}[{index}]", minimum=0) for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique atom IDs")
    return result


def _element(value: Any, name: str) -> str:
    result = _text(value, name)
    if any(char.isspace() for char in result):
        raise ValueError(f"{name} must be one element symbol")
    return result


def _concentration(value: Any, name: str) -> dict[str, Any]:
    record = _mapping(value, name)
    numerator = _integer(record.get("numerator"), f"{name}.numerator", minimum=0)
    denominator = _integer(record.get("denominator"), f"{name}.denominator", minimum=1)
    basis = _text(record.get("basis"), f"{name}.basis")
    if basis not in {"sublattice", "all_atoms", "explicit_cation_set"}:
        raise ValueError(f"{name}.basis must be sublattice, all_atoms, or explicit_cation_set")
    result = {"numerator": numerator, "denominator": denominator, "basis": basis}
    if basis == "explicit_cation_set":
        result["atom_ids"] = _atom_ids(record.get("atom_ids"), f"{name}.atom_ids")
    elif "atom_ids" in record:
        raise ValueError(f"{name}.atom_ids is only valid for explicit_cation_set")
    return result


def _formal_valences(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()
    for index, item in enumerate(value):
        record = _mapping(item, f"{name}[{index}]")
        element = _element(record.get("element"), f"{name}[{index}].element")
        sublattice_value = record.get("sublattice")
        sublattice = None if sublattice_value is None else _text(sublattice_value, f"{name}[{index}].sublattice")
        key = (sublattice, element)
        if key in seen:
            raise ValueError(f"{name} contains duplicate valence entry for {sublattice or '*'}:{element}")
        seen.add(key)
        result.append(
            {
                "sublattice": sublattice,
                "element": element,
                "valence": _integer(record.get("valence"), f"{name}[{index}].valence"),
                "source": _text(record.get("source"), f"{name}[{index}].source"),
            }
        )
    return result


def _compensation(value: Any) -> dict[str, Any]:
    record = _mapping(value, "compensation")
    status = _text(record.get("status"), "compensation.status")
    if status not in {"specified", "none", "unresolved"}:
        raise ValueError("compensation.status must be specified, none, or unresolved")
    net_value = record.get("net_charge")
    net_charge = None if net_value is None else _integer(net_value, "compensation.net_charge")
    ionic_value = record.get("ionic_charge_delta")
    electronic_value = record.get("electronic_compensation_charge")
    ionic_charge_delta = None if ionic_value is None else _integer(ionic_value, "compensation.ionic_charge_delta")
    electronic_compensation_charge = (
        None
        if electronic_value is None
        else _integer(electronic_value, "compensation.electronic_compensation_charge")
    )
    source = _text(record.get("source"), "compensation.source")
    formal_value = record.get("formal_valences")
    if formal_value is None and status == "unresolved":
        formal_valences = []
    else:
        formal_valences = _formal_valences(formal_value, "compensation.formal_valences")
    operations = record.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("compensation.operations must be a list")
    if status == "unresolved" and operations:
        raise ValueError("unresolved compensation cannot include executable operations")
    if status != "unresolved":
        if net_charge is None or ionic_charge_delta is None or electronic_compensation_charge is None:
            raise ValueError(
                "specified compensation requires net_charge, ionic_charge_delta, and "
                "electronic_compensation_charge"
            )
        if ionic_charge_delta + electronic_compensation_charge != net_charge:
            raise ValueError(
                "compensation charge balance requires ionic_charge_delta + "
                "electronic_compensation_charge == net_charge"
            )
    return {
        "status": status,
        "net_charge": net_charge,
        "ionic_charge_delta": ionic_charge_delta,
        "electronic_compensation_charge": electronic_compensation_charge,
        "source": source,
        "formal_valences": formal_valences,
        "operations": copy.deepcopy(operations),
        "ionic_delta_convention": "new_formal_valence_minus_old; vacancy_is_negative_old; interstitial_is_positive_new",
    }


def _site_reference(value: Any, name: str) -> dict[str, Any]:
    record = _mapping(value, name)
    return {
        "sublattice": _text(record.get("sublattice"), f"{name}.sublattice"),
        "parent_atom_id": _integer(record.get("parent_atom_id"), f"{name}.parent_atom_id", minimum=0),
        "parent_image": _integer_vector(record.get("parent_image"), f"{name}.parent_image"),
    }


def _site_assignment(value: Any, name: str) -> dict[str, Any]:
    result = _site_reference(value, name)
    result["element"] = _element(value.get("element"), f"{name}.element")
    return result


def _capacity_for(
    component: Mapping[str, Any],
    sublattices: Mapping[str, Mapping[str, Any]],
    all_atom_ids: Sequence[int],
    repeat_count: int,
) -> int:
    concentration = component.get("concentration")
    if concentration is None:
        return 0
    basis = concentration["basis"]
    if basis == "sublattice":
        return len(sublattices[component["sublattice"]]["allowed_atom_ids"]) * repeat_count
    if basis == "all_atoms":
        return len(all_atom_ids) * repeat_count
    return len(concentration["atom_ids"]) * repeat_count


def _valence_for(
    formal_valences: Sequence[Mapping[str, Any]],
    sublattice: str | None,
    element: str,
) -> tuple[int | None, str | None]:
    """Resolve a site-specific valence, then an element-wide fallback."""

    fallback: Mapping[str, Any] | None = None
    for record in formal_valences:
        if record.get("element") != element:
            continue
        if record.get("sublattice") == sublattice and sublattice is not None:
            return int(record["valence"]), str(record["source"])
        if record.get("sublattice") is None:
            fallback = record
    if fallback is not None:
        return int(fallback["valence"]), str(fallback["source"])
    return None, None


def _derived_ionic_charge_delta(
    assignments: Sequence[Mapping[str, Any]],
    compensation_operations: Sequence[Mapping[str, Any]],
    *,
    parent_symbols: Mapping[int, str] | None,
    formal_valences: Sequence[Mapping[str, Any]],
) -> tuple[int | None, str | None]:
    """Calculate the ionic charge delta from actual selected operations."""

    if parent_symbols is None:
        return None, "parent element mapping is required for the formal-valence ledger"

    total = 0

    def parent_element(atom_id: int, name: str) -> str:
        if atom_id not in parent_symbols:
            raise ValueError(f"parent_symbols is missing atom {atom_id} for {name}")
        return str(parent_symbols[atom_id])

    def valence(sublattice: str | None, element: str, name: str) -> int | None:
        value, _source = _valence_for(formal_valences, sublattice, element)
        if value is None:
            raise LookupError(f"missing formal valence/source for {name}: {sublattice or '*'}:{element}")
        return value

    try:
        for assignment in assignments:
            old_element = parent_element(int(assignment["parent_atom_id"]), "site assignment")
            old_value = valence(assignment["sublattice"], old_element, "site assignment parent")
            new_value = valence(assignment["sublattice"], str(assignment["element"]), "site assignment child")
            total += int(new_value) - int(old_value)

        for operation in compensation_operations:
            kind = _text(operation.get("kind"), "compensation.operations.kind")
            if kind in {"vacancy", "substitution"}:
                site = _site_reference(operation, "compensation operation")
                old_element = parent_element(site["parent_atom_id"], "compensation operation")
                old_value = valence(site["sublattice"], old_element, "compensation operation parent")
                if kind == "vacancy":
                    total -= int(old_value)
                else:
                    new_element = operation.get("element")
                    if new_element is None:
                        new_element = operation.get("new_element")
                    new_element = _element(new_element, "compensation operation.element")
                    new_value = valence(site["sublattice"], new_element, "compensation operation child")
                    total += int(new_value) - int(old_value)
            elif kind == "interstitial":
                element = _element(operation.get("element"), "compensation interstitial.element")
                sublattice = operation.get("sublattice")
                if sublattice is not None:
                    sublattice = _text(sublattice, "compensation interstitial.sublattice")
                value = valence(sublattice, element, "compensation interstitial")
                total += int(value)
            else:
                raise ValueError(f"unsupported compensation operation kind: {kind}")
    except LookupError as error:
        return None, str(error)
    return total, None


def resolve_component_counts(
    component_values: Any,
    sublattices: Mapping[str, Mapping[str, Any]],
    parent_atom_ids: Sequence[int],
    repeat_count: int,
) -> list[dict[str, Any]]:
    """Resolve M1 integer counts using the declared concentration denominator."""
    all_ids = list(parent_atom_ids)
    if not isinstance(component_values, list) or not component_values:
        raise ValueError("components must be a non-empty list")
    components: list[dict[str, Any]] = []
    for index, value in enumerate(component_values):
        record = _mapping(value, f"components[{index}]")
        element = _element(record.get("element"), f"components[{index}].element")
        sub_id = _text(record.get("sublattice"), f"components[{index}].sublattice")
        if sub_id not in sublattices:
            raise ValueError(f"components[{index}].sublattice is not declared")
        count = record.get("count")
        concentration = None if record.get("concentration") is None else _concentration(record.get("concentration"), f"components[{index}].concentration")
        if count is None and concentration is None:
            raise ValueError(f"components[{index}] requires count or concentration")
        resolved_count = None if count is None else _integer(count, f"components[{index}].count", minimum=0)
        if concentration is not None:
            if concentration["basis"] == "explicit_cation_set":
                unknown = set(concentration["atom_ids"]) - set(all_ids)
                if unknown:
                    raise ValueError(
                        f"components[{index}].concentration.atom_ids contains IDs outside parent model: {sorted(unknown)}"
                    )
            capacity = _capacity_for(
                {"sublattice": sub_id, "concentration": concentration},
                sublattices,
                all_ids,
                repeat_count,
            )
            numerator = concentration["numerator"]
            denominator = concentration["denominator"]
            product = numerator * capacity
            if product % denominator:
                raise ValueError(f"components[{index}] concentration is not an exact integer for its declared capacity")
            concentration_count = product // denominator
            if resolved_count is not None and resolved_count != concentration_count:
                raise ValueError(f"components[{index}] count disagrees with concentration")
            resolved_count = concentration_count
        if resolved_count is None:
            raise ValueError(f"components[{index}] did not resolve to an integer count")
        if resolved_count > sublattices[sub_id]["supercell_capacity"]:
            raise ValueError(f"components[{index}] count exceeds sublattice capacity")
        components.append(
            {
                "element": element,
                "sublattice": sub_id,
                "count": resolved_count,
                "concentration": concentration,
                "capacity": sublattices[sub_id]["supercell_capacity"],
                "count_scope": "reference_supercell",
            }
        )
    counts_by_sublattice: Counter[str] = Counter()
    for component in components:
        counts_by_sublattice[component["sublattice"]] += component["count"]
    for sub_id, count in counts_by_sublattice.items():
        if count > sublattices[sub_id]["supercell_capacity"]:
            raise ValueError(f"component counts exceed sublattice {sub_id} capacity")
    return components


def resolve_dopant_composition(
    request: Mapping[str, Any],
    *,
    parent_atom_ids: Sequence[int] | None = None,
    parent_symbols: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """Resolve an explicit plan using atom IDs loaded from the parent model."""

    request = _mapping(request, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("unsupported dopant composition request")
    if request.get("random_seed") is not None:
        raise ValueError("random placement is not supported by the explicit composition planner")
    if request.get("sqs") not in (None, False):
        raise ValueError("SQS configuration is not supported by the explicit composition planner")
    requested_strategy = request.get("configuration_strategy")
    if requested_strategy not in (None, "explicit_deterministic", "explicit"):
        raise ValueError("only explicit deterministic composition is supported")
    study_id = _text(request.get("study_id"), "study_id")
    parent_model = _mapping(request.get("parent_model"), "parent_model")
    parent_model_id = _text(parent_model.get("model_id"), "parent_model.model_id")
    parent_version = _text(parent_model.get("version"), "parent_model.version")
    parent_path = _text(parent_model.get("path"), "parent_model.path")
    parent_study = _text(request.get("parent_study"), "parent_study")
    repeat_matrix = _matrix(request.get("repeat_matrix"))
    repeat_count = _matrix_determinant(repeat_matrix)
    if repeat_count <= 0:
        raise ValueError("repeat_matrix must have a positive integer capacity")
    max_atoms = _integer(request.get("max_atoms"), "max_atoms", minimum=1)
    if parent_atom_ids is None:
        raise ValueError("parent_atom_ids must be supplied from the loaded parent model")
    child_model = _mapping(request.get("child_model"), "child_model")
    child_model_id = _text(child_model.get("model_id"), "child_model.model_id")
    child_version = _text(child_model.get("version"), "child_model.version")
    reference_model = _mapping(request.get("reference_model"), "reference_model")
    reference_id = _text(reference_model.get("model_id"), "reference_model.model_id")
    reference_version = _text(reference_model.get("version"), "reference_model.version")
    if (reference_id, reference_version) == (parent_model_id, parent_version):
        raise ValueError("reference_model must use a new model identity")
    if (child_model_id, child_version) == (parent_model_id, parent_version):
        raise ValueError("child_model must use a new model identity")
    if (child_model_id, child_version) == (reference_id, reference_version):
        raise ValueError("child_model must differ from reference_model")
    sublattice_values = request.get("sublattices")
    if not isinstance(sublattice_values, list) or not sublattice_values:
        raise ValueError("sublattices must be a non-empty list")
    sublattices: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(sublattice_values):
        record = _mapping(value, f"sublattices[{index}]")
        sub_id = _text(record.get("id"), f"sublattices[{index}].id")
        if sub_id in sublattices:
            raise ValueError(f"duplicate sublattice id: {sub_id}")
        allowed_elements = record.get("allowed_parent_elements", [])
        if not isinstance(allowed_elements, list):
            raise ValueError(f"sublattices[{index}].allowed_parent_elements must be a list")
        allowed_ids_value = record.get("allowed_atom_ids", record.get("allowed_parent_atom_ids"))
        if "allowed_atom_ids" in record and "allowed_parent_atom_ids" in record and record["allowed_atom_ids"] != record["allowed_parent_atom_ids"]:
            raise ValueError(f"sublattices[{index}] has conflicting allowed atom ID fields")
        sublattices[sub_id] = {
            "id": sub_id,
            "allowed_atom_ids": _atom_ids(allowed_ids_value, f"sublattices[{index}].allowed_atom_ids"),
            "allowed_parent_elements": [
                _element(item, f"sublattices[{index}].allowed_parent_elements[{position}]")
                for position, item in enumerate(allowed_elements)
            ],
        }
    all_ids = list(parent_atom_ids)
    all_ids = _atom_ids(all_ids, "parent_atom_ids")
    reference_atom_count = len(all_ids) * repeat_count
    if reference_atom_count > max_atoms:
        raise ValueError(
            f"repeat_matrix creates {reference_atom_count} reference atoms above max_atoms={max_atoms}"
        )
    for sub_id, sublattice in sublattices.items():
        unknown = set(sublattice["allowed_atom_ids"]) - set(all_ids)
        if unknown:
            raise ValueError(f"sublattice {sub_id} contains atom IDs outside parent model: {sorted(unknown)}")
        if parent_symbols is not None and sublattice["allowed_parent_elements"]:
            for atom_id in sublattice["allowed_atom_ids"]:
                if atom_id not in parent_symbols:
                    raise ValueError(f"parent_symbols is missing atom {atom_id}")
                if parent_symbols[atom_id] not in sublattice["allowed_parent_elements"]:
                    raise ValueError(f"sublattice {sub_id} atom {atom_id} has an unallowed parent element")
        sublattice["parent_capacity"] = len(sublattice["allowed_atom_ids"])
        sublattice["supercell_capacity"] = len(sublattice["allowed_atom_ids"]) * repeat_count
    components = resolve_component_counts(request.get("components"), sublattices, all_ids, repeat_count)
    assignments_value = request.get("site_assignments")
    if not isinstance(assignments_value, list):
        raise ValueError("site_assignments must be a list of explicit sites")
    assignments = [_site_assignment(value, f"site_assignments[{index}]") for index, value in enumerate(assignments_value)]
    seen_sites: set[tuple[int, tuple[int, int, int]]] = set()
    for index, assignment in enumerate(assignments):
        sub_id = assignment["sublattice"]
        key = (assignment["parent_atom_id"], tuple(assignment["parent_image"]))
        if sub_id not in sublattices or assignment["parent_atom_id"] not in sublattices[sub_id]["allowed_atom_ids"]:
            raise ValueError(f"site_assignments[{index}] is outside its declared sublattice")
        if key in seen_sites:
            raise ValueError(f"site_assignments[{index}] repeats a final occupied site")
        seen_sites.add(key)
        if parent_symbols is not None and sublattices[sub_id]["allowed_parent_elements"]:
            if assignment["parent_atom_id"] not in parent_symbols:
                raise ValueError(f"parent_symbols is missing atom {assignment['parent_atom_id']}")
            if parent_symbols[assignment["parent_atom_id"]] not in sublattices[sub_id]["allowed_parent_elements"]:
                raise ValueError(f"site_assignments[{index}] parent element is not allowed")
        if len([item for item in assignments if item["sublattice"] == sub_id]) > sublattices[sub_id]["supercell_capacity"]:
            raise ValueError(f"site_assignments exceed sublattice {sub_id} capacity")
    expected: Counter[tuple[str, str]] = Counter()
    for component in components:
        expected[(component["sublattice"], component["element"])] += component["count"]
    actual = Counter((assignment["sublattice"], assignment["element"]) for assignment in assignments)
    if actual != expected:
        raise ValueError("site_assignments do not exactly match component counts")
    compensation = _compensation(request.get("compensation"))
    operation_sites = set(seen_sites)
    operation_atom_ids = set(all_ids)
    for index, operation_value in enumerate(compensation["operations"]):
        operation = _mapping(operation_value, f"compensation.operations[{index}]")
        kind = _text(operation.get("kind"), f"compensation.operations[{index}].kind")
        if kind in {"vacancy", "substitution"}:
            site = _site_reference(operation, f"compensation.operations[{index}]")
            if site["sublattice"] not in sublattices:
                raise ValueError(f"compensation.operations[{index}] sublattice is not declared")
            if site["parent_atom_id"] not in sublattices[site["sublattice"]]["allowed_atom_ids"]:
                raise ValueError(f"compensation.operations[{index}] is outside its declared sublattice")
            key = (site["parent_atom_id"], tuple(site["parent_image"]))
            if key in operation_sites:
                raise ValueError(f"compensation.operations[{index}] repeats a final occupied site")
            operation_sites.add(key)
            if kind == "substitution":
                new_element = operation.get("element")
                if new_element is None:
                    new_element = operation.get("new_element")
                _element(new_element, f"compensation.operations[{index}].element")
        elif kind == "interstitial":
            new_atom_id = _integer(operation.get("new_atom_id"), f"compensation.operations[{index}].new_atom_id", minimum=0)
            if new_atom_id in operation_atom_ids:
                raise ValueError(f"compensation.operations[{index}] new_atom_id is already used")
            operation_atom_ids.add(new_atom_id)
            _element(operation.get("element"), f"compensation.operations[{index}].element")
            if operation.get("sublattice") is not None:
                sub_id = _text(operation.get("sublattice"), f"compensation.operations[{index}].sublattice")
                if sub_id not in sublattices:
                    raise ValueError(f"compensation.operations[{index}] sublattice is not declared")
        else:
            raise ValueError(f"unsupported compensation operation kind: {kind}")
    if compensation["status"] != "unresolved":
        derived_ionic, unresolved_reason = _derived_ionic_charge_delta(
            assignments,
            compensation["operations"],
            parent_symbols=parent_symbols,
            formal_valences=compensation["formal_valences"],
        )
        if unresolved_reason is not None:
            compensation["requested_status"] = compensation["status"]
            compensation["status"] = "unresolved"
            compensation["unresolved_reason"] = unresolved_reason
            compensation["derived_ionic_charge_delta"] = None
            compensation["derived_electronic_compensation_charge"] = None
        else:
            if compensation["ionic_charge_delta"] != derived_ionic:
                raise ValueError(
                    "declared ionic_charge_delta differs from the selected operations and formal valences"
                )
            derived_electronic = compensation["net_charge"] - int(derived_ionic)
            if compensation["electronic_compensation_charge"] != derived_electronic:
                raise ValueError(
                    "declared electronic_compensation_charge differs from net_charge minus ionic_charge_delta"
                )
            compensation["derived_ionic_charge_delta"] = int(derived_ionic)
            compensation["derived_electronic_compensation_charge"] = int(derived_electronic)
    else:
        compensation["derived_ionic_charge_delta"] = None
        compensation["derived_electronic_compensation_charge"] = None
    recipe_value = request.get("recipe")
    if recipe_value is None:
        recipe = {"kind": "explicit_composition", "source": "request"}
    else:
        recipe = copy.deepcopy(dict(_mapping(recipe_value, "recipe")))
    return {
        "schema": PLAN_SCHEMA,
        "status": "unresolved" if compensation["status"] == "unresolved" else "resolved",
        "study_id": study_id,
        "parent_study": parent_study,
        "parent_model": {"model_id": parent_model_id, "version": parent_version, "path": parent_path},
        "reference_model": {"model_id": reference_id, "version": reference_version, **{key: value for key, value in reference_model.items() if key not in {"model_id", "version"}}},
        "child_model": {"model_id": child_model_id, "version": child_version, **{key: value for key, value in child_model.items() if key not in {"model_id", "version"}}},
        "recipe": recipe,
        "repeat_matrix": repeat_matrix,
        "max_atoms": max_atoms,
        "reference_atom_count": reference_atom_count,
        "parent_atom_ids": all_ids,
        "parent_atom_ids_source": "explicit_parent_model",
        "sublattices": list(sublattices.values()),
        "components": components,
        "site_assignments": assignments,
        "compensation": compensation,
        "selection": "explicit_sites_only",
        "configuration_strategy": "explicit_deterministic",
        "sqs": None,
    }


def _find_child_atom_id(lineage: Sequence[Mapping[str, Any]], assignment: Mapping[str, Any]) -> int:
    matches = [
        int(entry["child_atom_id"])
        for entry in lineage
        if entry.get("parent_atom_id") == assignment["parent_atom_id"]
        and list(entry.get("parent_image", [])) == list(assignment["parent_image"])
    ]
    if len(matches) != 1:
        raise ValueError(f"selected parent site does not map to exactly one supercell atom: {assignment}")
    return matches[0]


def _lineage_entry(lineage: Sequence[Mapping[str, Any]], assignment: Mapping[str, Any]) -> Mapping[str, Any]:
    matches = [
        entry
        for entry in lineage
        if entry.get("parent_atom_id") == assignment["parent_atom_id"]
        and list(entry.get("parent_image", [])) == list(assignment["parent_image"])
    ]
    if len(matches) != 1:
        raise ValueError(f"selected parent site does not map to exactly one supercell atom: {assignment}")
    return matches[0]


def compile_dopant_operations(plan: Mapping[str, Any], lineage: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compile explicit parent-image selections to existing child atom IDs."""

    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported dopant composition plan")
    compensation = _mapping(plan.get("compensation"), "compensation")
    if compensation.get("status") == "unresolved":
        raise ValueError("compensation plan is unresolved; no child model can be compiled")
    operations: list[dict[str, Any]] = []
    used_child_ids: set[int] = set()
    lineage_child_ids = {
        _integer(entry.get("child_atom_id"), "lineage.child_atom_id", minimum=0)
        for entry in lineage
    }
    for assignment in plan["site_assignments"]:
        entry = _lineage_entry(lineage, assignment)
        child_atom_id = _integer(entry.get("child_atom_id"), "lineage.child_atom_id", minimum=0)
        if entry.get("element") == assignment["element"]:
            raise ValueError(f"substitution at parent site is a no-op: {assignment}")
        if child_atom_id in used_child_ids:
            raise ValueError(f"multiple final composition operations target child atom {child_atom_id}")
        used_child_ids.add(child_atom_id)
        operations.append(
            {"kind": "substitution", "atom_id": child_atom_id, "new_element": assignment["element"]}
        )
    for operation in compensation.get("operations", []):
        record = _mapping(operation, "compensation.operations entry")
        kind = _text(record.get("kind"), "compensation.operations.kind")
        if kind in {"vacancy", "substitution"}:
            site = _site_reference(record, "compensation operation")
            child_atom_id = _find_child_atom_id(lineage, site)
            if child_atom_id in used_child_ids:
                raise ValueError(f"multiple final composition operations target child atom {child_atom_id}")
            used_child_ids.add(child_atom_id)
            compiled = {"kind": kind, "atom_id": child_atom_id}
            if kind == "substitution":
                new_element = record.get("element")
                if new_element is None:
                    new_element = record.get("new_element")
                compiled["new_element"] = _element(
                    new_element,
                    "compensation operation.element",
                )
                if _lineage_entry(lineage, site).get("element") == compiled["new_element"]:
                    raise ValueError(f"compensation substitution at a site is a no-op: {record}")
            operations.append(compiled)
        elif kind == "interstitial":
            new_atom_id = _integer(record.get("new_atom_id"), "compensation interstitial.new_atom_id", minimum=0)
            if new_atom_id in lineage_child_ids:
                raise ValueError(f"interstitial new_atom_id {new_atom_id} collides with a child atom")
            if new_atom_id in used_child_ids:
                raise ValueError(f"interstitial new_atom_id {new_atom_id} is repeated")
            raw_frac = record.get("frac_coords")
            if not isinstance(raw_frac, Sequence) or isinstance(raw_frac, (str, bytes)) or len(raw_frac) != 3:
                raise ValueError("compensation interstitial.frac_coords must contain three values")
            frac_coords = [float(item) for item in raw_frac]
            if not all(math.isfinite(item) for item in frac_coords):
                raise ValueError("compensation interstitial.frac_coords must contain finite values")
            compiled = {
                "kind": kind,
                "new_atom_id": new_atom_id,
                "element": _element(record.get("element"), "compensation interstitial.element"),
                "frac_coords": frac_coords,
            }
            used_child_ids.add(new_atom_id)
            operations.append(compiled)
        else:
            raise ValueError(f"unsupported compensation operation kind: {kind}")
    if not operations:
        raise ValueError("resolved composition plan has no executable operations")
    return operations


def _composition_artifact_fields(
    plan: Mapping[str, Any],
    *,
    role: str,
    plan_file: str,
) -> dict[str, Any]:
    return {
        "composition_plan_schema": PLAN_SCHEMA,
        "composition_plan_file": plan_file,
        "composition_role": role,
        "composition_status": plan["status"],
        "composition_parent_study": plan["parent_study"],
        "composition_parent_model": copy.deepcopy(plan["parent_model"]),
        "composition_reference_model": copy.deepcopy(plan["reference_model"]),
        "composition_child_model": copy.deepcopy(plan["child_model"]),
        "composition_repeat_matrix": copy.deepcopy(plan["repeat_matrix"]),
        "composition_max_atoms": plan["max_atoms"],
        "composition_reference_atom_count": plan["reference_atom_count"],
        "composition_parent_atom_ids": copy.deepcopy(plan["parent_atom_ids"]),
        "composition_sublattices": copy.deepcopy(plan["sublattices"]),
        "composition_components": copy.deepcopy(plan["components"]),
        "composition_site_assignments": copy.deepcopy(plan["site_assignments"]),
        "composition_compensation": copy.deepcopy(plan["compensation"]),
        "composition_configuration_strategy": plan["configuration_strategy"],
    }


def _site_key(record: Mapping[str, Any]) -> tuple[int, tuple[int, int, int]]:
    return int(record["parent_atom_id"]), tuple(int(item) for item in record["parent_image"])


def _composition_material(composition: Mapping[str, Any], element_order: Sequence[str] | None = None) -> str:
    """Return a readable material label derived from actual atom counts."""

    if not composition:
        raise ValueError("child model composition must not be empty")
    order = list(element_order or composition.keys())
    order.extend(element for element in composition if element not in order)
    parts: list[str] = []
    for element in order:
        if element not in composition:
            continue
        count = _integer(composition[element], f"composition.{element}", minimum=1)
        parts.append(str(element) if count == 1 else f"{element}{count}")
    return "".join(parts)


def _parent_dopant_records(plan: Mapping[str, Any]) -> list[Any]:
    """Read and preserve the parent's canonical dopant records."""

    parent_dir = Path(str(plan["parent_model"]["path"])).expanduser().resolve()
    parent_model = json.loads((parent_dir / "model.json").read_text(encoding="utf-8"))
    model_records = parent_model.get("dopants", [])
    if not isinstance(model_records, list):
        raise ValueError("parent model dopants must be a list")
    dopants_path = parent_dir / "dopants.json"
    dopants_document = json.loads(dopants_path.read_text(encoding="utf-8"))
    document_records = dopants_document.get("dopants", [])
    if not isinstance(document_records, list):
        raise ValueError("parent dopants.json dopants must be a list")
    if model_records != document_records:
        raise ValueError("parent model.json and dopants.json dopant records differ")
    return copy.deepcopy(model_records)


def _inherited_dopant_records(
    parent_records: Sequence[Mapping[str, Any]],
    reference_lineage: Sequence[Mapping[str, Any]],
    operations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Expand explicit parent dopant sites and remove sites changed in the child."""
    replaced = {operation["atom_id"] for operation in operations if "atom_id" in operation}
    records = []
    for parent in parent_records:
        images = [entry for entry in reference_lineage if entry["parent_atom_id"] == parent["atom_id"]]
        if not images:
            raise ValueError("parent dopant atom_id is absent from the supercell lineage")
        for entry in images:
            if entry["child_atom_id"] not in replaced:
                records.append({
                    "element": parent["element"], "sublattice": parent["sublattice"],
                    "atom_id": entry["child_atom_id"], "parent_atom_id": parent["atom_id"],
                    "parent_image": copy.deepcopy(entry["parent_image"]), "count": 1,
                    "operation": "inherited_exact_supercell_site", "source": "parent_dopants",
                    "parent_record": copy.deepcopy(dict(parent)),
                })
    return records


def _composition_dopant_records(
    plan: Mapping[str, Any],
    reference_lineage: Sequence[Mapping[str, Any]],
    operations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build actual child dopant records from selected sites and operations."""

    components = {
        (component["sublattice"], component["element"]): component
        for component in plan["components"]
    }
    records: list[dict[str, Any]] = []
    assignment_count = len(plan["site_assignments"])
    for assignment in plan["site_assignments"]:
        reference_entry = _lineage_entry(reference_lineage, assignment)
        component = components[(assignment["sublattice"], assignment["element"])]
        records.append(
            {
                "element": assignment["element"],
                "site": assignment["sublattice"],
                "sublattice": assignment["sublattice"],
                "atom_id": int(reference_entry["child_atom_id"]),
                "reference_atom_id": int(reference_entry["child_atom_id"]),
                "parent_atom_id": int(assignment["parent_atom_id"]),
                "parent_image": copy.deepcopy(assignment["parent_image"]),
                "operation": "substitution",
                "source": "composition_plan",
                "count": 1,
                "component_count": int(component["count"]),
                "capacity": int(component["capacity"]),
                "fraction": float(component["count"]) / float(component["capacity"]),
                "concentration": copy.deepcopy(component["concentration"]),
            }
        )

    compensation_operations = plan["compensation"]["operations"]
    compiled_compensation = operations[assignment_count:]
    if len(compensation_operations) != len(compiled_compensation):
        raise ValueError("compiled compensation operation count differs from the composition plan")
    for raw_operation, compiled in zip(compensation_operations, compiled_compensation):
        kind = _text(raw_operation.get("kind"), "compensation.operations.kind")
        if kind == "vacancy":
            continue
        if kind == "substitution":
            site = _site_reference(raw_operation, "compensation operation")
            new_element = raw_operation.get("element")
            if new_element is None:
                new_element = raw_operation.get("new_element")
            records.append(
                {
                    "element": _element(new_element, "compensation operation.element"),
                    "site": site["sublattice"],
                    "sublattice": site["sublattice"],
                    "atom_id": int(compiled["atom_id"]),
                    "reference_atom_id": int(compiled["atom_id"]),
                    "parent_atom_id": int(site["parent_atom_id"]),
                    "parent_image": copy.deepcopy(site["parent_image"]),
                    "operation": "compensation_substitution",
                    "source": "composition_compensation",
                    "fraction": None,
                }
            )
            continue
        if kind == "interstitial":
            records.append(
                {
                    "element": _element(raw_operation.get("element"), "compensation interstitial.element"),
                    "site": raw_operation.get("sublattice"),
                    "sublattice": raw_operation.get("sublattice"),
                    "atom_id": int(compiled["new_atom_id"]),
                    "reference_atom_id": None,
                    "parent_atom_id": None,
                    "parent_image": None,
                    "operation": "interstitial",
                    "source": "composition_compensation",
                    "fraction": None,
                }
            )
            continue
        raise ValueError(f"unsupported compensation operation kind: {kind}")
    return records


def _annotate_composition_artifacts(
    artifact_dir: str | Path,
    plan: Mapping[str, Any],
    *,
    role: str,
    reference_lineage: Sequence[Mapping[str, Any]],
    operations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Attach composition semantics without changing derived structure data.

    ``model_derivatives`` remains the owner of structure generation and the
    original derivation records.  This helper only adds the composition
    contract to the three artifacts consumed by downstream MLCC paths and
    returns the metadata written to ``model.json``.
    """

    directory = Path(artifact_dir)
    plan_file = "../composition-plan.json"
    fields = _composition_artifact_fields(plan, role=role, plan_file=plan_file)

    model_path = directory / "model.json"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    parent_dopants = _parent_dopant_records(plan)
    composition_dopants = (
        _composition_dopant_records(plan, reference_lineage, operations)
        if role == "child"
        else []
    )
    inherited_dopants = _inherited_dopant_records(parent_dopants, reference_lineage, operations)
    actual_dopants = inherited_dopants + copy.deepcopy(composition_dopants)
    model.update(copy.deepcopy(fields))
    model["composition_parent_dopants"] = copy.deepcopy(parent_dopants)
    model["composition_dopants"] = copy.deepcopy(composition_dopants)
    model["dopants"] = copy.deepcopy(actual_dopants)
    if role == "child":
        model["material"] = _composition_material(model["composition"], model.get("element_order"))
    model["phase_requested_source"] = model.get("phase_requested")
    model["phase_structure_relation"] = "inherited_request_only"
    model_path.write_text(json.dumps(model, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

    dopants_path = directory / "dopants.json"
    dopants = json.loads(dopants_path.read_text(encoding="utf-8"))
    dopants.update(copy.deepcopy(fields))
    dopants["composition_parent_dopants"] = copy.deepcopy(parent_dopants)
    dopants["composition_dopants"] = copy.deepcopy(composition_dopants)
    dopants["dopants"] = copy.deepcopy(actual_dopants)
    if role == "child":
        dopants["material"] = model["material"]
    dopants["compensation"] = copy.deepcopy(plan["compensation"])
    dopants["composition_operations"] = copy.deepcopy(list(operations))
    dopants_path.write_text(json.dumps(dopants, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

    lineage_path = directory / "atom-lineage.json"
    lineage_record = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage_record.update(copy.deepcopy(fields))
    entries = [copy.deepcopy(entry) for entry in lineage_record.get("entries", [])]

    reference_by_id = {
        int(entry["child_atom_id"]): entry
        for entry in reference_lineage
        if entry.get("child_atom_id") is not None
    }
    selected_by_site = {
        _site_key(assignment): assignment
        for assignment in plan["site_assignments"]
    }
    selected_by_reference_id: dict[int, Mapping[str, Any]] = {}
    for entry in reference_lineage:
        if entry.get("parent_atom_id") is None or entry.get("parent_image") is None:
            continue
        assignment = selected_by_site.get(_site_key(entry))
        if assignment is not None:
            selected_by_reference_id[int(entry["child_atom_id"])] = assignment

    operation_by_atom = {
        int(operation["atom_id"]): operation
        for operation in operations
        if operation.get("atom_id") is not None
    }
    interstitial_by_atom = {
        int(operation["new_atom_id"]): operation
        for operation in operations
        if operation.get("kind") == "interstitial"
    }

    for entry in entries:
        if role == "reference":
            assignment = selected_by_site.get(_site_key(entry)) if entry.get("parent_image") is not None else None
            if assignment is None:
                entry["composition_role"] = "unchanged_reference"
            else:
                entry["composition_role"] = "selected_substitution"
                entry["composition_sublattice"] = assignment["sublattice"]
                entry["composition_requested_element"] = assignment["element"]
                entry["composition_final_atom_id"] = int(entry["child_atom_id"])
        else:
            reference_id = entry.get("parent_atom_id")
            if reference_id is None:
                operation = interstitial_by_atom.get(int(entry["child_atom_id"]))
                entry["composition_role"] = "compensation_interstitial" if operation is not None else "unmapped_child_atom"
                if operation is not None:
                    entry["composition_operation"] = copy.deepcopy(operation)
                continue
            reference_id = int(reference_id)
            reference_entry = reference_by_id.get(reference_id)
            entry["composition_reference_atom_id"] = reference_id
            if reference_entry is not None:
                entry["composition_parent_atom_id"] = reference_entry.get("parent_atom_id")
                entry["composition_parent_image"] = copy.deepcopy(reference_entry.get("parent_image"))
            assignment = selected_by_reference_id.get(reference_id)
            if assignment is not None:
                entry["composition_role"] = "selected_substitution"
                entry["composition_sublattice"] = assignment["sublattice"]
                entry["composition_requested_element"] = assignment["element"]
            elif reference_id in operation_by_atom:
                entry["composition_role"] = "compensation_operation"
                entry["composition_operation"] = copy.deepcopy(operation_by_atom[reference_id])
            else:
                entry["composition_role"] = "unchanged_reference"

    lineage_record["entries"] = entries
    lineage_path.write_text(
        json.dumps(lineage_record, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return model


def _write_composition_study(
    parent_study: Mapping[str, Any],
    parent_study_path: Path,
    output_path: Path,
    plan: Mapping[str, Any],
    *,
    model_ref: Mapping[str, Any] | None,
    baseline_ref: Mapping[str, Any],
    child_model_metadata: Mapping[str, Any] | None = None,
    unresolved: bool = False,
) -> Path:
    """Write the child Study binding for a resolved composition build."""

    child_study = copy.deepcopy(dict(parent_study))
    child_study["study_id"] = plan["study_id"]
    child_study["parent_study_id"] = parent_study.get("study_id")
    child_study["parent_study_path"] = str(parent_study_path.resolve())
    child_study["composition_plan_file"] = "composition-plan.json"
    child_study["composition_build_file"] = "composition-build.json"
    child_study["composition_status"] = plan["status"]
    child_study["composition_recipe"] = copy.deepcopy(plan.get("recipe"))
    child_study["reference_model"] = copy.deepcopy(dict(baseline_ref))
    child_study["reference_model_ref"] = copy.deepcopy(dict(baseline_ref))
    child_study["baseline_ref"] = copy.deepcopy(dict(baseline_ref))
    child_study["model_ref"] = None if model_ref is None else copy.deepcopy(dict(model_ref))
    child_study["composition_parent_model"] = copy.deepcopy(plan["parent_model"])
    child_study["composition_components"] = copy.deepcopy(plan["components"])
    child_study["composition_sublattices"] = copy.deepcopy(plan["sublattices"])
    child_study["composition_compensation"] = copy.deepcopy(plan["compensation"])
    if unresolved:
        child_study["composition_unresolved_reason"] = plan["compensation"].get(
            "unresolved_reason", "compensation plan unresolved; reference supercell only"
        )
        child_study["study_binding"] = "parent_study_unresolved_composition"
        return parent_study_path

    child_study["study_binding"] = "composition_child"
    child_study["model"] = copy.deepcopy(dict(parent_study.get("model", {})))
    if child_model_metadata is None:
        raise ValueError("resolved composition Study requires child model metadata")
    actual_composition = _mapping(child_model_metadata.get("composition"), "child model composition")
    actual_element_order = child_model_metadata.get("element_order")
    if actual_element_order is not None and not isinstance(actual_element_order, list):
        raise ValueError("child model element_order must be a list")
    if actual_element_order is None:
        actual_element_order = [str(element) for element in actual_composition]
    child_study["model"].update(
        {
            "model_id": model_ref["model_id"],
            "version": model_ref["version"],
            "path": model_ref["path"],
            "material": _composition_material(actual_composition, actual_element_order),
            "composition": copy.deepcopy(dict(actual_composition)),
            "element_order": copy.deepcopy(actual_element_order),
            "dopants": copy.deepcopy(child_model_metadata.get("dopants", [])),
            "phase_requested": parent_study.get("model", {}).get("phase_requested"),
            "phase_structure_relation": "inherited_request_only",
        }
    )
    child_study["selected_required_tasks_source"] = "parent_study"
    child_study["parent_selected_required_tasks"] = copy.deepcopy(parent_study.get("selected_required_tasks", []))
    child_study["selected_required_tasks"] = []
    child_study_path = output_path / "study.json"
    child_study_path.write_text(
        json.dumps(child_study, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return child_study_path


def build_composition_model(request_path: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Resolve a request and materialize its exact reference/child models."""

    request_file = Path(request_path).expanduser().resolve()
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("composition request must be a JSON object")
    requested_parent_model = _mapping(request["parent_model"], "parent_model")
    requested_parent_model_id = _text(requested_parent_model.get("model_id"), "parent_model.model_id")
    requested_parent_model_version = _text(requested_parent_model.get("version"), "parent_model.version")
    parent_model_path = (request_file.parent / Path(_text(requested_parent_model.get("path"), "parent_model.path")).expanduser()).resolve()
    parent_study_path = (request_file.parent / Path(_text(request["parent_study"], "parent_study")).expanduser()).resolve()
    parent = read_model_artifacts(parent_model_path)
    if (requested_parent_model_id, requested_parent_model_version) != (parent.model_id, parent.version):
        raise ValueError("request parent_model identity differs from the loaded parent model")
    study = json.loads(parent_study_path.read_text(encoding="utf-8"))
    parent_study_id = _text(study.get("study_id"), "parent study.study_id")
    if request.get("parent_study_id") is not None and _text(request.get("parent_study_id"), "parent_study_id") != parent_study_id:
        raise ValueError("parent_study_id differs from the supplied parent Study")
    if (study.get("model", {}).get("model_id"), study.get("model", {}).get("version")) != (parent.model_id, parent.version):
        raise ValueError("parent Study model differs from supplied parent model")
    parent_symbols = {int(atom_id): str(symbol) for atom_id, symbol in zip(parent.atom_ids, parent.atoms.get_chemical_symbols())}
    plan_request = copy.deepcopy(request)
    plan_request["parent_study"] = str(parent_study_path)
    plan_request["parent_model"] = copy.deepcopy(dict(requested_parent_model))
    plan_request["parent_model"]["path"] = str(parent_model_path)
    plan = resolve_dopant_composition(plan_request, parent_atom_ids=parent.atom_ids, parent_symbols=parent_symbols)
    plan["parent_study_id"] = parent_study_id
    if plan["status"] == "unresolved":
        plan["requested_study_id"] = plan["study_id"]
        plan["study_id"] = parent_study_id
        plan["study_binding"] = "parent_study_unresolved_composition"
    else:
        if plan["study_id"] == parent_study_id:
            raise ValueError("resolved composition requires a child Study identity distinct from parent_study")
        plan["study_binding"] = "composition_child"
    output = Path(output_directory).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"composition output directory already exists: {output}")
    output.mkdir(parents=True)
    plan_path = output / "composition-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    reference_model_path = output / "reference-model"
    reference_request = {
        "model_id": plan["reference_model"]["model_id"],
        "version": plan["reference_model"]["version"],
        "study_id": plan["study_id"],
        "repeat_matrix": plan["repeat_matrix"],
    }
    reference = derive_supercell_model(parent_model_path, reference_request, reference_model_path)
    reference_lineage = json.loads((reference.artifact_dir / "atom-lineage.json").read_text(encoding="utf-8"))["entries"]
    _annotate_composition_artifacts(
        reference.artifact_dir,
        plan,
        role="reference",
        reference_lineage=reference_lineage,
    )
    baseline_ref = {
        "model_id": reference.model_id,
        "version": reference.version,
        "path": str(reference.artifact_dir.resolve()),
    }
    parent_ref = {
        "model_id": parent.model_id,
        "version": parent.version,
        "path": str(parent.artifact_dir.resolve()),
    }
    build: dict[str, Any] = {
        "schema": BUILD_SCHEMA,
        "status": plan["status"],
        "study_id": plan["study_id"],
        "model_path": None,
        "study_path": str(parent_study_path) if plan["status"] == "unresolved" else None,
        "reference_model_path": str(reference.artifact_dir.resolve()),
        "reference_lineage_path": str((reference.artifact_dir / "atom-lineage.json").resolve()),
        "model_ref": parent_ref if plan["status"] == "unresolved" else None,
        "reference_model_ref": baseline_ref,
        "baseline_ref": baseline_ref,
        "parent_study_id": parent_study_id,
        "study_binding": plan["study_binding"],
        "composition_plan_path": str(plan_path.resolve()),
        "plan": plan,
        "source_refs": [str(request_file), str(parent_study_path), str(parent_model_path), str(plan_path)],
    }
    if plan["status"] == "unresolved":
        build["unresolved_reason"] = plan["compensation"].get(
            "unresolved_reason", "compensation plan unresolved; reference supercell only"
        )
        _write_composition_study(
            study,
            parent_study_path,
            output,
            plan,
            model_ref=parent_ref,
            baseline_ref=baseline_ref,
            unresolved=True,
        )
        (output / "composition-build.json").write_text(json.dumps(build, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        return build
    operations = compile_dopant_operations(plan, reference_lineage)
    expected_child_atom_count = plan["reference_atom_count"]
    expected_child_atom_count -= sum(1 for operation in operations if operation["kind"] == "vacancy")
    expected_child_atom_count += sum(1 for operation in operations if operation["kind"] == "interstitial")
    if expected_child_atom_count > plan["max_atoms"]:
        raise ValueError(
            f"composition operations create {expected_child_atom_count} child atoms above max_atoms={plan['max_atoms']}"
        )
    child_model_path = output / "child-model"
    defect_request = {
        "model_id": plan["child_model"]["model_id"],
        "version": plan["child_model"]["version"],
        "study_id": plan["study_id"],
        "charge_state": plan["compensation"]["net_charge"],
        "operations": operations,
    }
    child = derive_defect_model(reference.artifact_dir, defect_request, child_model_path)
    child_metadata = _annotate_composition_artifacts(
        child.artifact_dir,
        plan,
        role="child",
        reference_lineage=reference_lineage,
        operations=operations,
    )
    child.metadata.update(copy.deepcopy(child_metadata))
    build["model_path"] = str(child.artifact_dir.resolve())
    build["model_ref"] = {
        "model_id": child.model_id,
        "version": child.version,
        "path": str(child.artifact_dir.resolve()),
    }
    build["lineage_path"] = str((child.artifact_dir / "atom-lineage.json").resolve())
    build["actual_composition"] = copy.deepcopy(child_metadata.get("composition"))
    build["operations"] = operations
    study_path = _write_composition_study(
        study,
        parent_study_path,
        output,
        plan,
        model_ref=build["model_ref"],
        baseline_ref=baseline_ref,
        child_model_metadata=child_metadata,
    )
    build["study_path"] = str(study_path.resolve())
    (output / "composition-build.json").write_text(json.dumps(build, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return build


__all__ = [
    "BUILD_SCHEMA",
    "PLAN_SCHEMA",
    "REQUEST_SCHEMA",
    "build_composition_model",
    "compile_dopant_operations",
    "resolve_dopant_composition",
    "resolve_component_counts",
]
