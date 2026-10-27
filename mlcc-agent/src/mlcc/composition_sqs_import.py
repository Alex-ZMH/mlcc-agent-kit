"""Import one explicitly mapped external extxyz composition candidate.

The importer is deliberately a consumer, not an SQS generator.  It reads one
external frame through the existing modeling reader, validates the explicit
parent-site mapping and fixed-lattice geometry, lets the M1 composition builder
compile the deterministic request, and then replaces only the generated child
geometry with the external coordinates.  External provenance and correlation
text remain separate from M1's composition and charge records.
"""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from ase.geometry import find_mic

from .dopant_composition import (
    BUILD_SCHEMA,
    REQUEST_SCHEMA as COMPOSITION_REQUEST_SCHEMA,
    _matrix as _m1_matrix,
    _matrix_determinant,
    build_composition_model,
    resolve_component_counts,
)
from .model_derivatives import supercell_parent_images
from .modeling import (
    _read_import_source,
    _validate_periodic_crystal,
    read_model_artifacts,
    write_model_artifacts,
)


REQUEST_SCHEMA = "mlcc.sqs-import-request.v1"
CORRELATION_STATUS = "not_evaluated"
GEOMETRY_SCOPE = "full_occupancy_substitution_fixed_parent_lattice"


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


def _integer_vector(value: Any, name: str) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{name} must contain three integers")
    return [_integer(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def _request_path(request_file: Path, value: Any, name: str) -> Path:
    path_value = _text(value, name)
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = request_file.parent / path
    return path.resolve()


def _source_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_external_atoms(path: str | Path, frame_index: int) -> tuple[Any, str]:
    source_path = _source_path(path)
    atoms, source_block = _read_import_source(source_path, "extxyz", frame_index)
    _validate_periodic_crystal(atoms)
    return atoms, source_block


def _source_contract(request_file: Path, value: Any) -> tuple[dict[str, Any], Path, int]:
    source = _mapping(value, "external_structure")
    if source.get("format") != "extxyz":
        raise ValueError("external_structure.format must be extxyz")
    if source.get("length_unit") != "angstrom":
        raise ValueError("external_structure.length_unit must be angstrom")
    frame_index = _integer(source.get("frame_index"), "external_structure.frame_index", minimum=0)
    if frame_index != 0:
        raise ValueError("only extxyz frame_index=0 is supported")
    source_path = _request_path(request_file, source.get("path"), "external_structure.path")
    provenance = _mapping(source.get("provenance"), "external_structure.provenance")
    kind = _text(provenance.get("kind"), "external_structure.provenance.kind")
    if kind not in {"engineering_fixture", "external_candidate"}:
        raise ValueError("external_structure.provenance.kind is unsupported")
    description = _text(
        provenance.get("description"),
        "external_structure.provenance.description",
    )
    normalized_provenance: dict[str, Any] = {
        "kind": kind,
        "description": description,
    }
    for field in ("tool_name", "tool_version", "job_id", "stopping_status"):
        field_value = provenance.get(field)
        if field_value is not None:
            field_value = _text(field_value, f"external_structure.provenance.{field}")
        normalized_provenance[field] = field_value
    normalized_source = copy.deepcopy(dict(source))
    normalized_source["path"] = str(source_path)
    normalized_source["format"] = "extxyz"
    normalized_source["frame_index"] = frame_index
    normalized_source["length_unit"] = "angstrom"
    normalized_source["provenance"] = normalized_provenance
    return normalized_source, source_path, frame_index


def _validate_correlation_request(request_file: Path, value: Any) -> Path | None:
    if value is None:
        return None
    return _source_path(_request_path(request_file, value, "correlation_file"))


def _sublattices(composition: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = composition.get("sublattices")
    if not isinstance(values, list) or not values:
        raise ValueError("composition_request.sublattices must be a non-empty list")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(values):
        record = _mapping(value, f"composition_request.sublattices[{index}]")
        sub_id = _text(record.get("id"), f"composition_request.sublattices[{index}].id")
        if sub_id in result:
            raise ValueError(f"duplicate composition sublattice: {sub_id}")
        allowed = record.get("allowed_atom_ids", record.get("allowed_parent_atom_ids"))
        if not isinstance(allowed, list) or not allowed:
            raise ValueError(
                f"composition_request.sublattices[{index}].allowed_atom_ids must be a non-empty list"
            )
        allowed_ids = [
            _integer(item, f"{sub_id}.allowed_atom_ids[{pos}]", minimum=0)
            for pos, item in enumerate(allowed)
        ]
        if len(set(allowed_ids)) != len(allowed_ids):
            raise ValueError(f"composition sublattice {sub_id} repeats an atom ID")
        result[sub_id] = {"id": sub_id, "allowed_atom_ids": allowed_ids}
    return result


def _component_pairs(composition: Mapping[str, Any]) -> set[tuple[str, str]]:
    values = composition.get("components")
    if not isinstance(values, list) or not values:
        raise ValueError("composition_request.components must be a non-empty list")
    result: set[tuple[str, str]] = set()
    for index, value in enumerate(values):
        record = _mapping(value, f"composition_request.components[{index}]")
        result.add(
            (
                _text(record.get("element"), f"composition_request.components[{index}].element"),
                _text(record.get("sublattice"), f"composition_request.components[{index}].sublattice"),
            )
        )
    return result


def _compensation_substitutions(
    composition: Mapping[str, Any],
) -> dict[tuple[int, tuple[int, int, int]], dict[str, Any]]:
    compensation = _mapping(composition.get("compensation"), "composition_request.compensation")
    status = _text(compensation.get("status"), "composition_request.compensation.status")
    if status == "unresolved":
        raise ValueError("unresolved compensation cannot be imported as a child model")
    operations = compensation.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("composition_request.compensation.operations must be a list")
    substitutions: dict[tuple[int, tuple[int, int, int]], dict[str, Any]] = {}
    for index, value in enumerate(operations):
        operation = _mapping(value, f"composition_request.compensation.operations[{index}]")
        kind = _text(operation.get("kind"), f"compensation.operations[{index}].kind")
        if kind != "substitution":
            raise ValueError(
                "SQS import supports compensation substitutions only; vacancy/interstitial are unsupported"
            )
        atom_id = _integer(
            operation.get("parent_atom_id"),
            f"compensation.operations[{index}].parent_atom_id",
            minimum=0,
        )
        image = tuple(
            _integer_vector(
                operation.get("parent_image"),
                f"compensation.operations[{index}].parent_image",
            )
        )
        sublattice = _text(
            operation.get("sublattice"),
            f"compensation.operations[{index}].sublattice",
        )
        new_element = operation.get("element")
        if new_element is None:
            new_element = operation.get("new_element")
        new_element = _text(new_element, f"compensation.operations[{index}].element")
        key = (atom_id, image)
        if key in substitutions:
            raise ValueError("compensation substitution operations repeat a physical site")
        substitutions[key] = {
            "sublattice": sublattice,
            "element": new_element,
            "operation_index": index,
        }
    return substitutions


def _validate_mapping_and_assignments(
    composition: Mapping[str, Any],
    parent: Any,
    source_atoms: Any,
    mapping_value: Any,
    repeat_matrix: Any,
    tolerance: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(mapping_value, list) or len(mapping_value) != len(source_atoms):
        raise ValueError("atom_mapping must contain one entry for each external atom")
    parent_ids = [int(value) for value in parent.atom_ids]
    parent_index = {atom_id: index for index, atom_id in enumerate(parent_ids)}
    parent_cell = np.asarray(parent.atoms.cell.array, dtype=float)
    parent_frac = np.asarray(parent.atoms.get_scaled_positions(wrap=False), dtype=float)
    repeat_matrix = _m1_matrix(repeat_matrix)
    repeat_count = _matrix_determinant(repeat_matrix)
    max_atoms = _integer(composition.get("max_atoms"), "composition_request.max_atoms", minimum=1)
    if len(parent_ids) * repeat_count > max_atoms:
        raise ValueError("repeat_matrix creates more atoms than composition_request.max_atoms")
    repeat_images = supercell_parent_images(repeat_matrix)
    expected_cell = np.asarray(repeat_matrix, dtype=float) @ parent_cell
    if not np.allclose(source_atoms.cell.array, expected_cell, atol=tolerance, rtol=0.0):
        raise ValueError(
            "external cell differs from repeat_matrix @ parent cell beyond mapping_tolerance_angstrom"
        )
    expected_sites = {
        (atom_id, tuple(int(value) for value in image))
        for image in repeat_images
        for atom_id in parent_ids
    }
    sublattices = _sublattices(composition)
    repeat_count = len(repeat_images)
    for record in sublattices.values():
        record["supercell_capacity"] = len(record["allowed_atom_ids"]) * repeat_count
    resolved_components = resolve_component_counts(
        composition.get("components"),
        sublattices,
        parent_ids,
        repeat_count,
    )
    components = _component_pairs(composition)
    compensation = _compensation_substitutions(composition)
    if any(site not in expected_sites for site in compensation):
        raise ValueError("compensation substitution site is outside the requested supercell")
    for (atom_id, _image), operation in compensation.items():
        if operation["sublattice"] not in sublattices:
            raise ValueError("compensation substitution uses an undeclared sublattice")
        if atom_id not in sublattices[operation["sublattice"]]["allowed_atom_ids"]:
            raise ValueError("compensation substitution is outside its declared sublattice")
    source_to_site: dict[int, tuple[int, tuple[int, int, int]]] = {}
    site_to_source: dict[tuple[int, tuple[int, int, int]], int] = {}
    source_symbols = [str(value) for value in source_atoms.get_chemical_symbols()]
    parent_symbols = {
        atom_id: str(symbol)
        for atom_id, symbol in zip(parent_ids, parent.atoms.get_chemical_symbols())
    }
    mapping: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for entry_index, value in enumerate(mapping_value):
        entry = _mapping(value, f"atom_mapping[{entry_index}]")
        source_index = _integer(
            entry.get("source_index"),
            f"atom_mapping[{entry_index}].source_index",
            minimum=0,
        )
        if source_index >= len(source_atoms) or source_index in source_to_site:
            raise ValueError("atom_mapping source_index values must be unique and within source order")
        parent_atom_id = _integer(
            entry.get("parent_atom_id"),
            f"atom_mapping[{entry_index}].parent_atom_id",
            minimum=0,
        )
        if parent_atom_id not in parent_index:
            raise ValueError(f"atom_mapping[{entry_index}] refers to an unknown parent_atom_id")
        parent_image = tuple(
            _integer_vector(entry.get("parent_image"), f"atom_mapping[{entry_index}].parent_image")
        )
        site = (parent_atom_id, parent_image)
        if site not in expected_sites or site in site_to_source:
            raise ValueError("atom_mapping must cover each canonical parent atom/image exactly once")
        sublattice_value = entry.get("sublattice")
        sublattice = (
            None
            if sublattice_value is None
            else _text(sublattice_value, f"atom_mapping[{entry_index}].sublattice")
        )
        if sublattice is not None:
            if sublattice not in sublattices:
                raise ValueError(f"atom_mapping[{entry_index}] uses an undeclared sublattice")
            if parent_atom_id not in sublattices[sublattice]["allowed_atom_ids"]:
                raise ValueError(f"atom_mapping[{entry_index}] is outside its sublattice")
        parent_position = parent_frac[parent_index[parent_atom_id]] @ parent_cell
        expected_position = parent_position + np.asarray(parent_image, dtype=float) @ parent_cell
        delta = np.asarray(source_atoms.positions[source_index], dtype=float) - expected_position
        _mic_vector, mic_length = find_mic(
            delta.reshape(1, 3), cell=source_atoms.cell.array, pbc=source_atoms.pbc
        )
        if float(np.asarray(mic_length, dtype=float).reshape(-1)[0]) > tolerance:
            raise ValueError(
                f"external position for source_index {source_index} differs from mapped parent site beyond tolerance"
            )
        source_element = source_symbols[source_index]
        parent_element = parent_symbols[parent_atom_id]
        if source_element.lower() in {"vac", "vacancy", "va", "x"}:
            raise ValueError("vacancy symbols are unsupported by the full-occupancy SQS importer")
        if source_element != parent_element and sublattice is None:
            raise ValueError("changed external site requires an explicit sublattice")
        operation = compensation.get(site)
        if operation is not None:
            if source_element != operation["element"]:
                raise ValueError("external element disagrees with compensation substitution")
            if sublattice is not None and sublattice != operation["sublattice"]:
                raise ValueError("external mapping sublattice disagrees with compensation substitution")
        elif source_element != parent_element:
            resolved_sublattice = sublattice
            if (source_element, resolved_sublattice) not in components:
                raise ValueError("external substitution is absent from composition_request.components")
            assignments.append(
                {
                    "sublattice": resolved_sublattice,
                    "parent_atom_id": parent_atom_id,
                    "parent_image": list(parent_image),
                    "element": source_element,
                }
            )
        mapping_entry = copy.deepcopy(dict(entry))
        mapping_entry["source_index"] = source_index
        mapping_entry["parent_atom_id"] = parent_atom_id
        mapping_entry["parent_image"] = list(parent_image)
        mapping_entry["sublattice"] = sublattice
        mapping_entry["element"] = source_element
        mapping.append(mapping_entry)
        source_to_site[source_index] = site
        site_to_source[site] = source_index
    if set(source_to_site) != set(range(len(source_atoms))):
        raise ValueError("atom_mapping must cover every source atom index exactly once")
    if set(site_to_source) != expected_sites:
        raise ValueError("atom_mapping must cover every canonical parent atom/image exactly once")
    expected_counts = Counter(
        (str(component["element"]), str(component["sublattice"]))
        for component in resolved_components
        for _ in range(int(component["count"]))
    )
    actual_counts = Counter(
        (str(assignment["element"]), str(assignment["sublattice"]))
        for assignment in assignments
    )
    if actual_counts != expected_counts:
        raise ValueError("external substitutions do not match composition_request component counts")
    return mapping, assignments


def _resolved_composition_request(
    request_file: Path,
    composition_value: Any,
    parent: Any,
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    composition = _mapping(composition_value, "composition_request")
    if composition.get("schema") != COMPOSITION_REQUEST_SCHEMA:
        raise ValueError("composition_request must use the M1 dopant-composition request schema")
    if "site_assignments" in composition:
        existing = composition.get("site_assignments")
        if not isinstance(existing, list) or existing:
            raise ValueError("composition_request.site_assignments must be omitted or empty for SQS import")
    resolved = copy.deepcopy(dict(composition))
    parent_model = _mapping(resolved.get("parent_model"), "composition_request.parent_model")
    parent_path = _request_path(request_file, parent_model.get("path"), "parent_model.path")
    if parent_model.get("model_id") != parent.model_id or parent_model.get("version") != parent.version:
        raise ValueError("composition_request parent_model identity differs from the loaded parent model")
    resolved_parent_model = copy.deepcopy(dict(parent_model))
    resolved_parent_model["path"] = str(parent_path)
    resolved["parent_model"] = resolved_parent_model
    resolved["parent_study"] = str(
        _request_path(request_file, resolved.get("parent_study"), "parent_study")
    )
    resolved["site_assignments"] = copy.deepcopy(assignments)
    return resolved


def _save_correlation(
    correlation_path: Path | None,
    output: Path,
) -> tuple[str | None, str | None]:
    if correlation_path is None:
        return None, None
    correlation_text = correlation_path.read_bytes().decode("utf-8")
    destination = output / "source.correlation.txt"
    destination.write_bytes(correlation_text.encode("utf-8"))
    return str(correlation_path), correlation_text


def _import_child_geometry(
    child_directory: Path,
    source_atoms: Any,
    source_path: Path,
    source_mapping: list[dict[str, Any]],
    reference_lineage: Sequence[Mapping[str, Any]],
    imported_configuration: Mapping[str, Any],
    source_kind: str,
    source_description: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    old_model = _read_json(child_directory / "model.json")
    old_dopants = _read_json(child_directory / "dopants.json")
    old_lineage = _read_json(child_directory / "atom-lineage.json")
    reference_by_site = {
        (
            int(entry["parent_atom_id"]),
            tuple(int(value) for value in entry["parent_image"]),
        ): int(entry["child_atom_id"])
        for entry in reference_lineage
        if entry.get("parent_atom_id") is not None and entry.get("parent_image") is not None
    }
    child_entries = {
        int(entry["child_atom_id"]): entry for entry in old_lineage.get("entries", [])
    }
    source_order_mapping = sorted(source_mapping, key=lambda entry: int(entry["source_index"]))
    child_ids: list[int] = []
    imported_entries: list[dict[str, Any]] = []
    for entry in source_order_mapping:
        site = (
            int(entry["parent_atom_id"]),
            tuple(int(value) for value in entry["parent_image"]),
        )
        child_id = reference_by_site.get(site)
        if child_id is None or child_id not in child_entries:
            raise ValueError("M1 lineage does not contain the mapped full-occupancy site")
        child_ids.append(child_id)
        lineage_entry = copy.deepcopy(dict(child_entries[child_id]))
        lineage_entry["source_index"] = int(entry["source_index"])
        lineage_entry["source_atom_id"] = int(
            source_atoms.arrays["atom_id"][int(entry["source_index"])]
        )
        lineage_entry["source_element"] = str(entry["element"])
        lineage_entry["external_element"] = str(entry["element"])
        imported_entries.append(lineage_entry)
        entry["child_atom_id"] = child_id
        entry["source_atom_id"] = lineage_entry["source_atom_id"]
    if len(set(child_ids)) != len(child_ids):
        raise ValueError("mapped external atoms do not have unique child atom IDs")
    old_child = read_model_artifacts(child_directory)
    child_symbols = {
        int(atom_id): str(symbol)
        for atom_id, symbol in zip(old_child.atom_ids, old_child.atoms.get_chemical_symbols())
    }
    for entry, child_id in zip(source_order_mapping, child_ids):
        if str(entry["element"]) != child_symbols[child_id]:
            raise ValueError("external composition differs from the compiled M1 child composition")
    imported_atoms = source_atoms.copy()
    imported_atoms.set_array("atom_id", np.asarray(child_ids, dtype=np.int64))
    imported_atoms.info["mlcc_atom_id_origin"] = "explicit_external_parent_mapping"
    source_atoms_for_writer = imported_atoms.copy()
    if isinstance(imported_configuration, dict):
        imported_configuration["atom_mapping"] = copy.deepcopy(source_mapping)
        imported_configuration["reference_basis_transform"] = copy.deepcopy(
            old_model.get("basis_transform")
        )
    fixture = bool(old_model.get("fixture", False)) or source_kind == "engineering_fixture"
    fixture_purpose = old_model.get("fixture_purpose")
    selection_status = old_model.get("selection_status")
    material_selection_confirmed = old_model.get("material_selection_confirmed")
    scientific_status = old_model.get("scientific_status")
    if source_kind == "engineering_fixture":
        fixture_purpose = source_description
        selection_status = "engineering_fixture"
        material_selection_confirmed = False
        scientific_status = "engineering_fixture_not_production"
    elif source_kind == "external_candidate":
        selection_status = "external_candidate"
        material_selection_confirmed = False
    elif fixture:
        material_selection_confirmed = False
        if not selection_status:
            selection_status = "engineering_fixture"
        if not scientific_status:
            scientific_status = "engineering_fixture_not_production"
    provenance = _mapping(
        imported_configuration["external_structure"].get("provenance"),
        "external_structure.provenance",
    )
    source_version = provenance.get("tool_version") or "unknown"
    write_model_artifacts(
        imported_atoms,
        child_directory,
        model_id=str(old_model["model_id"]),
        version=str(old_model["version"]),
        fixture=fixture,
        fixture_purpose=fixture_purpose,
        phase_requested=str(old_model.get("phase_requested", "user_selected_phase_pending")),
        source_path=str(source_path),
        source_version=str(source_version),
        source_atoms=source_atoms_for_writer,
        material=old_model.get("material"),
        source_format="extxyz",
        source_reference=str(source_path),
        selection_status=selection_status,
        material_selection_confirmed=material_selection_confirmed,
        basis_transform=None,
        atom_lineage=imported_entries,
        source_original_file="source.external.extxyz",
        scientific_status=scientific_status,
        source_index_basis="source_atom_order",
    )
    shutil.copyfile(source_path, child_directory / "source.external.extxyz")
    fresh_model = _read_json(child_directory / "model.json")
    if fresh_model.get("composition") != old_model.get("composition"):
        raise ValueError("external composition differs from the M1 child composition")
    geometry_fields = {
        "atoms",
        "source_atoms",
        "atom_ids",
        "atom_id_origin",
        "source_atom_id_origin",
        "lattice_angstrom",
        "source_lattice_angstrom",
        "pbc",
        "source_pbc",
        "initial_magnetic_moments_muB",
        "source_initial_magnetic_moments_muB",
        "composition",
        "element_order",
        "vasp_element_order",
        "structure_file",
        "source_structure_file",
        "source_original_file",
        "source_path",
        "source_format",
        "source_reference",
        "source_version",
        "source_index_basis",
        "source_asymmetric_site_mapping",
        "basis_transform",
        "tool_versions",
        "atom_lineage_file",
    }
    merged_model = copy.deepcopy(old_model)
    for field in geometry_fields:
        if field in fresh_model:
            merged_model[field] = copy.deepcopy(fresh_model[field])
    merged_model["fixture"] = fixture
    merged_model["fixture_purpose"] = fixture_purpose
    merged_model["selection_status"] = selection_status
    merged_model["material_selection_confirmed"] = material_selection_confirmed
    merged_model["scientific_status"] = scientific_status
    merged_model["production_qualified"] = None if fixture else old_model.get("production_qualified")
    merged_model["atom_lineage"] = copy.deepcopy(imported_entries)
    merged_model["source_structure_role"] = "external_sqs_import"
    merged_model["spatial_mode"] = "external_sqs_import"
    merged_model["imported_configuration"] = copy.deepcopy(dict(imported_configuration))
    _write_json(child_directory / "model.json", merged_model)
    merged_dopants = copy.deepcopy(old_dopants)
    merged_dopants["fixture"] = fixture
    merged_dopants["fixture_purpose"] = fixture_purpose
    merged_dopants["material_selection_confirmed"] = material_selection_confirmed
    merged_dopants["spatial_mode"] = "external_sqs_import"
    merged_dopants["imported_configuration"] = copy.deepcopy(dict(imported_configuration))
    _write_json(child_directory / "dopants.json", merged_dopants)
    lineage_record = copy.deepcopy(old_lineage)
    lineage_record["entries"] = copy.deepcopy(imported_entries)
    lineage_record["source_structure_role"] = "external_sqs_import"
    lineage_record["imported_configuration"] = copy.deepcopy(dict(imported_configuration))
    _write_json(child_directory / "atom-lineage.json", lineage_record)
    return merged_model, imported_entries


def import_sqs_configuration(
    request_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Import one explicitly mapped external extxyz into an M1 build."""

    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    composition = _mapping(request.get("composition_request"), "composition_request")
    external, source_path, frame_index = _source_contract(
        request_file, request.get("external_structure")
    )
    correlation_path = _validate_correlation_request(
        request_file, request.get("correlation_file")
    )
    tolerance = _positive_float(
        request.get("mapping_tolerance_angstrom"),
        "mapping_tolerance_angstrom",
    )
    parent_model = _mapping(composition.get("parent_model"), "composition_request.parent_model")
    parent_path = _request_path(request_file, parent_model.get("path"), "parent_model.path")
    parent = read_model_artifacts(parent_path)
    source_atoms, source_block = _read_external_atoms(source_path, frame_index)
    mapping, assignments = _validate_mapping_and_assignments(
        composition,
        parent,
        source_atoms,
        request.get("atom_mapping"),
        composition.get("repeat_matrix"),
        tolerance,
    )
    mapping.sort(key=lambda entry: int(entry["source_index"]))
    external.update(
        {
            "source_block": source_block,
            "source_atom_ids": [int(value) for value in source_atoms.arrays["atom_id"]],
            "elements": [str(value) for value in source_atoms.get_chemical_symbols()],
            "positions_angstrom": [
                [float(value) for value in row] for row in source_atoms.get_positions()
            ],
            "cell_angstrom": [
                [float(value) for value in row] for row in source_atoms.cell.array
            ],
            "pbc": [bool(value) for value in source_atoms.pbc],
            "atom_order": "source_file_order",
        }
    )
    resolved_composition = _resolved_composition_request(
        request_file,
        composition,
        parent,
        assignments,
    )
    output = Path(output_directory).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"SQS import output directory already exists: {output}")
    output.mkdir(parents=True)
    resolved_request_path = output / "resolved-composition-request.json"
    _write_json(resolved_request_path, resolved_composition)
    build = build_composition_model(resolved_request_path, output / "build")
    if build.get("schema") != BUILD_SCHEMA:
        raise ValueError("M1 composition builder returned an unexpected build schema")
    if build.get("status") != "resolved" or not build.get("model_path"):
        raise ValueError("unresolved compensation cannot produce an imported child model")
    if any(operation.get("kind") != "substitution" for operation in build.get("operations", [])):
        raise ValueError("SQS import child contains unsupported vacancy/interstitial operations")
    reference_lineage = _read_json(Path(build["reference_lineage_path"]))["entries"]
    child_directory = Path(build["model_path"])
    imported_configuration: dict[str, Any] = {
        "external_structure": copy.deepcopy(external),
        "atom_mapping": copy.deepcopy(mapping),
        "mapping_tolerance_angstrom": tolerance,
        "geometry_scope": GEOMETRY_SCOPE,
        "geometry_preserved": True,
        "correlation_file": None if correlation_path is None else str(correlation_path),
        "correlation_text": None,
        "correlation_assessment": CORRELATION_STATUS,
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
    }
    if imported_configuration["analysis_scheduler_job_id"] is not None:
        imported_configuration["analysis_scheduler_job_id"] = _text(
            imported_configuration["analysis_scheduler_job_id"],
            "analysis_scheduler_job_id",
        )
    for entry in mapping:
        entry["source_atom_id"] = int(source_atoms.arrays["atom_id"][int(entry["source_index"])])
    correlation_file, correlation_text = _save_correlation(
        correlation_path,
        output,
    )
    imported_configuration["correlation_file"] = correlation_file
    imported_configuration["correlation_text"] = correlation_text
    imported_configuration["atom_mapping"] = copy.deepcopy(mapping)
    imported_configuration["native_job"] = None
    imported_configuration["source_request_path"] = str(request_file)
    imported_configuration["resolved_composition_request"] = str(resolved_request_path)
    imported_configuration["source_copy"] = str(child_directory / "source.external.extxyz")
    imported_configuration["external_structure"]["saved_source_file"] = str(
        child_directory / "source.external.extxyz"
    )
    merged_model, _imported_entries = _import_child_geometry(
        child_directory,
        source_atoms,
        source_path,
        mapping,
        reference_lineage,
        imported_configuration,
        external["provenance"]["kind"],
        external["provenance"]["description"],
    )
    study_path = Path(build["study_path"])
    study = _read_json(study_path)
    study_model_ref = copy.deepcopy(study.get("model"))
    if not isinstance(study.get("model"), dict):
        raise ValueError("M1 child Study is missing its model reference")
    for field in (
        "fixture",
        "fixture_purpose",
        "material_selection_confirmed",
        "selection_status",
        "production_qualified",
        "material",
        "composition",
        "element_order",
        "dopants",
        "phase_requested",
        "phase_structure_relation",
        "spatial_mode",
    ):
        if field in merged_model:
            study["model"][field] = copy.deepcopy(merged_model[field])
    for field in ("model_id", "version", "path"):
        if study_model_ref.get(field) != study["model"].get(field):
            raise ValueError("external import must not alter the M1 Study model reference")
    if merged_model.get("fixture"):
        study["case_role"] = "engineering_fixture"
    study["imported_configuration"] = copy.deepcopy(imported_configuration)
    _write_json(study_path, study)
    build["imported_configuration"] = copy.deepcopy(imported_configuration)
    build["source_refs"] = list(build.get("source_refs", [])) + [str(request_file), str(source_path)]
    if correlation_file is not None:
        build["source_refs"].append(str(correlation_file))
    _write_json(output / "build" / "composition-build.json", build)
    _write_json(output / "composition-build.json", build)
    return build


__all__ = [
    "BUILD_SCHEMA",
    "CORRELATION_STATUS",
    "GEOMETRY_SCOPE",
    "REQUEST_SCHEMA",
    "import_sqs_configuration",
]
