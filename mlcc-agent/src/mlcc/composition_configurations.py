"""Explicit seeded-random composition configurations.

This module samples finite, explicitly requested site assignments.  It is a
small adapter around the deterministic composition builder: it does not
search for an optimum, deduplicate configurations, or generate SQS output.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


REQUEST_SCHEMA = "mlcc.composition-configurations-request.v1"
OUTPUT_SCHEMA = "mlcc.composition-configurations.v1"
RANDOM_ALGORITHM = "numpy.random.Generator(PCG64)"


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


def _element(value: Any, name: str) -> str:
    result = _text(value, name)
    if any(character.isspace() for character in result):
        raise ValueError(f"{name} must be one element symbol")
    return result


def _parent_ids(parent_atom_ids: Sequence[int]) -> list[int]:
    if isinstance(parent_atom_ids, (str, bytes)) or not isinstance(parent_atom_ids, Sequence):
        raise ValueError("parent_atom_ids must be a sequence")
    result = [_integer(value, f"parent_atom_ids[{index}]", minimum=0) for index, value in enumerate(parent_atom_ids)]
    if not result or len(set(result)) != len(result):
        raise ValueError("parent_atom_ids must be non-empty and unique")
    return sorted(result)


def _sublattices(composition: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = composition.get("sublattices")
    if not isinstance(values, list) or not values:
        raise ValueError("composition.sublattices must be a non-empty list")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(values):
        item = _mapping(value, f"composition.sublattices[{index}]")
        identifier = _text(item.get("id"), f"composition.sublattices[{index}].id")
        if identifier in result:
            raise ValueError(f"duplicate sublattice id: {identifier}")
        if "allowed_atom_ids" in item and "allowed_parent_atom_ids" in item and item["allowed_atom_ids"] != item["allowed_parent_atom_ids"]:
            raise ValueError(f"composition.sublattices[{index}] has conflicting allowed atom ID fields")
        atom_ids = item.get("allowed_atom_ids", item.get("allowed_parent_atom_ids"))
        if isinstance(atom_ids, (str, bytes)) or not isinstance(atom_ids, Sequence):
            raise ValueError(f"{identifier}.allowed_atom_ids must be a sequence")
        raw_atom_ids = [_integer(atom_id, f"{identifier}.allowed_atom_ids", minimum=0) for atom_id in atom_ids]
        if not raw_atom_ids or len(set(raw_atom_ids)) != len(raw_atom_ids):
            raise ValueError(f"{identifier}.allowed_atom_ids must be non-empty and unique")
        allowed_elements = item.get("allowed_parent_elements", [])
        if not isinstance(allowed_elements, list):
            raise ValueError(f"{identifier}.allowed_parent_elements must be a list")
        result[identifier] = {
            "id": identifier,
            "allowed_atom_ids": sorted(raw_atom_ids),
            "allowed_atom_ids_raw": raw_atom_ids,
            "allowed_parent_elements": [_element(element, f"{identifier}.allowed_parent_elements") for element in allowed_elements],
            "supercell_capacity": None,
        }
    return result


def _component_counts(
    components: Sequence[Mapping[str, Any]],
    sublattices: Mapping[str, Mapping[str, Any]],
    parent_atom_ids: Sequence[int],
    repeat_count: int,
) -> list[dict[str, Any]]:
    """Resolve exact integer counts for the random sampler."""
    capacities = {name: len(item["allowed_atom_ids"]) * repeat_count for name, item in sublattices.items()}
    for name, capacity in capacities.items():
        sublattices[name]["supercell_capacity"] = capacity
    from .dopant_composition import resolve_component_counts

    return [dict(item) for item in resolve_component_counts(components, sublattices, parent_atom_ids, repeat_count)]


def _sampling_state(
    composition: Mapping[str, Any],
    parent_ids: Sequence[int],
    parent_symbols: Mapping[int, str],
    parent_images: Sequence[Sequence[int]],
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[int, tuple[int, int, int]]]], dict[str, list[tuple[int, tuple[int, int, int]]]]]:
    images = parent_images.tolist() if isinstance(parent_images, np.ndarray) else parent_images
    if isinstance(images, (str, bytes)) or not isinstance(images, Sequence):
        raise ValueError("parent_images must be a sequence")
    image_values: list[tuple[int, int, int]] = []
    for index, image in enumerate(images):
        if isinstance(image, (str, bytes)) or not isinstance(image, Sequence) or len(image) != 3:
            raise ValueError(f"parent_images[{index}] must contain three integers")
        image_values.append(tuple(_integer(value, f"parent_images[{index}]") for value in image))
    images = image_values
    if len(set(images)) != len(images):
        raise ValueError("parent_images must be unique")
    if "site_assignments" in composition:
        raise ValueError("composition_request must not include site_assignments")
    values = composition.get("components")
    if not isinstance(values, list) or not values:
        raise ValueError("composition.components must be a non-empty list")
    components: list[dict[str, Any]] = []
    seen_components: set[tuple[str, str]] = set()
    for index, value in enumerate(values):
        item = _mapping(value, f"composition.components[{index}]")
        element = _element(item.get("element"), f"composition.components[{index}].element")
        sublattice = _text(item.get("sublattice"), f"composition.components[{index}].sublattice")
        if (sublattice, element) in seen_components:
            raise ValueError(f"duplicate component: {sublattice}:{element}")
        seen_components.add((sublattice, element))
        component = dict(item)
        component.update(element=element, sublattice=sublattice)
        components.append(component)
    sublattices = _sublattices(composition)
    parent_id_set = set(parent_ids)
    for name, sublattice in sublattices.items():
        unknown = set(sublattice["allowed_atom_ids"]) - parent_id_set
        if unknown:
            raise ValueError(f"sublattice {name} contains parent atom IDs outside the model: {sorted(unknown)}")
        if sublattice["allowed_parent_elements"]:
            for atom_id in sublattice["allowed_atom_ids"]:
                if parent_symbols[atom_id] not in sublattice["allowed_parent_elements"]:
                    raise ValueError(f"sublattice {name} atom {atom_id} has an unallowed parent element")
    repeat_count = len(images)
    counts = _component_counts(components, sublattices, parent_ids, repeat_count)
    for left_name, left in sublattices.items():
        left_ids = set(left["allowed_atom_ids"])
        for right_name, right in sublattices.items():
            if left_name < right_name and left_ids & set(right["allowed_atom_ids"]):
                raise ValueError(f"random sublattice pools overlap: {left_name} and {right_name}")
    reserved: set[tuple[int, tuple[int, int, int]]] = set()
    compensation = composition.get("compensation")
    if compensation is not None:
        operations = _mapping(compensation, "composition.compensation").get("operations", [])
        if not isinstance(operations, list):
            raise ValueError("composition.compensation.operations must be a list")
        image_set = set(images)
        for index, value in enumerate(operations):
            item = _mapping(value, f"compensation.operations[{index}]")
            kind = _text(item.get("kind"), f"compensation.operations[{index}].kind")
            if kind == "interstitial":
                continue
            if kind not in {"vacancy", "substitution"}:
                raise ValueError(f"unsupported compensation operation kind: {kind}")
            sublattice = _text(item.get("sublattice"), f"compensation.operations[{index}].sublattice")
            atom_id = _integer(item.get("parent_atom_id"), f"compensation.operations[{index}].parent_atom_id", minimum=0)
            image = tuple(_integer(part, f"compensation.operations[{index}].parent_image") for part in item.get("parent_image", []))
            if sublattice not in sublattices or atom_id not in sublattices[sublattice]["allowed_atom_ids"]:
                raise ValueError("compensation operation is outside its sublattice")
            if len(image) != 3 or image not in image_set:
                raise ValueError("compensation operation image is outside the requested supercell")
            if (atom_id, image) in reserved:
                raise ValueError("compensation operations repeat a site")
            reserved.add((atom_id, image))
    raw = {
        name: [(atom_id, image) for atom_id in sublattice["allowed_atom_ids_raw"] for image in images
               if (atom_id, image) not in reserved]
        for name, sublattice in sublattices.items()
    }
    ordered = {name: sorted(pool) for name, pool in raw.items()}
    for component in counts:
        allowed_elements = [str(parent_symbols[atom_id]) for atom_id in sublattices[component["sublattice"]]["allowed_atom_ids"]]
        if int(component["count"]) > 0 and component["element"] in allowed_elements:
            raise ValueError(f"component {component['element']} would create a same-element/no-op site")
    return counts, raw, ordered


def _sample_from_state(
    counts: Sequence[Mapping[str, Any]],
    pools: Mapping[str, Sequence[tuple[int, tuple[int, int, int]]]],
    seed: int,
) -> list[dict[str, Any]]:
    generator = np.random.Generator(np.random.PCG64(seed))
    remaining = {name: list(pool) for name, pool in pools.items()}
    assignments: list[dict[str, Any]] = []
    for component in sorted(counts, key=lambda item: (item["sublattice"], item["element"])):
        sublattice = component["sublattice"]
        pool = remaining[sublattice]
        count = int(component["count"])
        if count > len(pool):
            raise ValueError(f"component {component['element']} exceeds available unreserved sites")
        selected_indices = generator.choice(len(pool), size=count, replace=False) if count else np.asarray([], dtype=int)
        selected = sorted(pool[int(index)] for index in selected_indices)
        selected_set = set(selected)
        for atom_id, image in selected:
            assignments.append({
                "sublattice": sublattice,
                "parent_atom_id": atom_id,
                "parent_image": list(image),
                "element": component["element"],
                "selection_source": "seeded_random",
                "seed": seed,
                "algorithm": RANDOM_ALGORITHM,
                "numpy_version": np.__version__,
            })
        remaining[sublattice] = [site for site in pool if site not in selected_set]
    return sorted(assignments, key=lambda item: (item["sublattice"], item["element"], item["parent_atom_id"], item["parent_image"]))


def sample_composition_assignments(
    composition: Mapping[str, Any],
    *,
    parent_atom_ids: Sequence[int],
    parent_symbols: Mapping[int, str],
    parent_images: Sequence[Sequence[int]],
    seed: int,
) -> list[dict[str, Any]]:
    """Sample explicit site assignments with a reproducible PCG64 generator."""
    seed = _integer(seed, "seed", minimum=0)
    parent_ids = _parent_ids(parent_atom_ids)
    if set(parent_symbols) != set(parent_ids):
        raise ValueError("parent_symbols must cover exactly the parent atom IDs")
    counts, _raw, ordered = _sampling_state(composition, parent_ids, parent_symbols, parent_images)
    return _sample_from_state(counts, ordered, seed)


def _identity(record: Mapping[str, Any], name: str) -> tuple[str, str]:
    return _text(record.get("model_id"), f"{name}.model_id"), _text(record.get("version"), f"{name}.version")


def _configuration_id(value: Any, name: str) -> str:
    result = _text(value, name)
    if result in {".", ".."} or "/" in result or "\\" in result or result[1:2] == ":":
        raise ValueError(f"{name} must be a single path segment")
    return result


def _validate_configurations(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise ValueError("configurations must be a non-empty explicit list")
    result: list[dict[str, Any]] = []
    seen_configurations: set[str] = set()
    seen_studies: set[str] = set()
    seen_models: set[tuple[str, str]] = set()
    for index, value in enumerate(values):
        item = _mapping(value, f"configurations[{index}]")
        configuration_id = _configuration_id(item.get("configuration_id"), f"configurations[{index}].configuration_id")
        if configuration_id in seen_configurations:
            raise ValueError(f"duplicate configuration_id: {configuration_id}")
        seed = _integer(item.get("seed"), f"configurations[{index}].seed", minimum=0)
        study_id = _text(item.get("study_id"), f"configurations[{index}].study_id")
        if study_id in seen_studies:
            raise ValueError(f"duplicate configuration Study identity: {study_id}")
        reference = dict(_mapping(item.get("reference_model"), f"configurations[{index}].reference_model"))
        child = dict(_mapping(item.get("child_model"), f"configurations[{index}].child_model"))
        reference_identity = _identity(reference, f"configurations[{index}].reference_model")
        child_identity = _identity(child, f"configurations[{index}].child_model")
        if reference_identity == child_identity or reference_identity in seen_models or child_identity in seen_models:
            raise ValueError(f"duplicate configuration model identity at {configuration_id}")
        seen_configurations.add(configuration_id)
        seen_studies.add(study_id)
        seen_models.update((reference_identity, child_identity))
        result.append({"configuration_id": configuration_id, "seed": seed, "study_id": study_id,
                       "reference_model": reference, "child_model": child})
    return result


def _serialize_pools(
    pools: Mapping[str, Sequence[tuple[int, tuple[int, int, int]]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        name: [
            {"parent_atom_id": int(atom_id), "parent_image": [int(value) for value in image]}
            for atom_id, image in pool
        ]
        for name, pool in pools.items()
    }


def _annotate(path: Path, fields: Mapping[str, Any]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(copy.deepcopy(dict(fields)))
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def build_composition_configurations(request_path: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Build each explicitly requested seeded configuration through M1."""
    request_file = Path(request_path).expanduser().resolve()
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    configuration_set_id = _text(request.get("configuration_set_id"), "configuration_set_id")
    composition = dict(_mapping(request.get("composition_request"), "composition_request"))
    if "site_assignments" in composition:
        raise ValueError("composition_request must not include site_assignments")
    max_configurations = _integer(request.get("max_configurations"), "max_configurations", minimum=1)
    configurations = _validate_configurations(request.get("configurations"))
    if len(configurations) > max_configurations:
        raise ValueError("configurations exceeds max_configurations")
    from .dopant_composition import REQUEST_SCHEMA as M1_REQUEST_SCHEMA

    if composition.get("schema") != M1_REQUEST_SCHEMA:
        raise ValueError(f"composition_request schema must be {M1_REQUEST_SCHEMA}")
    parent_model_ref = dict(_mapping(composition.get("parent_model"), "composition_request.parent_model"))
    parent_study_value = _text(composition.get("parent_study"), "composition_request.parent_study")
    parent_model_path = Path(_text(parent_model_ref.get("path"), "composition_request.parent_model.path"))
    parent_model_path = parent_model_path if parent_model_path.is_absolute() else request_file.parent / parent_model_path
    parent_model_path = parent_model_path.resolve()
    parent_study_path = Path(parent_study_value)
    parent_study_path = parent_study_path if parent_study_path.is_absolute() else request_file.parent / parent_study_path
    parent_study_path = parent_study_path.resolve()
    from .dopant_composition import _matrix, _matrix_determinant
    from .model_derivatives import supercell_parent_images
    from .modeling import read_model_artifacts

    parent_artifacts = read_model_artifacts(parent_model_path)
    parent_study = json.loads(parent_study_path.read_text(encoding="utf-8"))
    parent_study_id = _text(parent_study.get("study_id"), "parent Study.study_id")
    parent_identity = (parent_artifacts.model_id, parent_artifacts.version)
    if parent_identity != _identity(parent_model_ref, "composition_request.parent_model"):
        raise ValueError("composition parent_model differs from loaded model")
    if _identity(parent_study.get("model"), "parent Study model") != parent_identity:
        raise ValueError("parent Study model differs from parent model")
    if any(item["study_id"] == parent_study_id for item in configurations):
        raise ValueError("configuration Study identity collides with parent Study")
    parent_atom_ids = _parent_ids(parent_artifacts.atom_ids)
    parent_symbols = {
        int(atom_id): _element(symbol, "parent atom element")
        for atom_id, symbol in zip(parent_artifacts.atom_ids, parent_artifacts.atoms.get_chemical_symbols())
    }
    repeat_matrix = _matrix(composition.get("repeat_matrix"))
    composition["repeat_matrix"] = repeat_matrix
    determinant = _matrix_determinant(repeat_matrix)
    max_atoms = _integer(composition.get("max_atoms"), "composition.max_atoms", minimum=1)
    reference_atom_count = len(parent_atom_ids) * determinant
    if reference_atom_count > max_atoms:
        raise ValueError(f"requested supercell has {reference_atom_count} atoms above max_atoms={max_atoms}")
    for configuration in configurations:
        if _identity(configuration["reference_model"], "reference_model") == parent_identity:
            raise ValueError("configuration reference_model identity collides with parent model")
        if _identity(configuration["child_model"], "child_model") == parent_identity:
            raise ValueError("configuration child_model identity collides with parent model")
    parent_images = supercell_parent_images(composition["repeat_matrix"])
    counts, raw_pools, sorted_pools = _sampling_state(
        composition, parent_atom_ids, parent_symbols, parent_images,
    )
    output = Path(output_directory).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"configuration output directory already exists: {output}")
    output.mkdir(parents=True)
    parent_ref = {
        "model_id": parent_identity[0],
        "version": parent_identity[1],
        "path": str(parent_artifacts.artifact_dir.resolve()),
    }
    records: list[dict[str, Any]] = []
    for configuration in configurations:
        seed = configuration["seed"]
        assignments = _sample_from_state(counts, sorted_pools, seed)
        serialized_raw_pools = _serialize_pools(raw_pools)
        serialized_sorted_pools = _serialize_pools(sorted_pools)
        config_dir = output / "configurations" / configuration["configuration_id"]
        request_dir = config_dir / "request"
        model_dir = config_dir / "models"
        request_dir.mkdir(parents=True)
        subrequest = copy.deepcopy(dict(composition))
        subrequest.update({
            "schema": M1_REQUEST_SCHEMA,
            "study_id": configuration["study_id"],
            "parent_study": str(parent_study_path),
            "parent_model": parent_ref,
            "reference_model": copy.deepcopy(configuration["reference_model"]),
            "child_model": copy.deepcopy(configuration["child_model"]),
            "site_assignments": assignments,
            "configuration_strategy": "explicit_deterministic",
            "selection_source": "seeded_random",
            "seed": seed,
            "algorithm": RANDOM_ALGORITHM,
        })
        subrequest_path = request_dir / "composition-request.json"
        subrequest_path.write_text(json.dumps(subrequest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        from .dopant_composition import build_composition_model

        build = build_composition_model(subrequest_path, model_dir)
        provenance = {
            "configuration_set_id": configuration_set_id,
            "configuration_id": configuration["configuration_id"],
            "seed": seed,
            "random_seed": seed,
            "selection_strategy": "seeded_random",
            "selection_source": "composition_configurations",
            "random_algorithm": RANDOM_ALGORITHM,
            "numpy_version": np.__version__,
            "candidate_pools_raw": serialized_raw_pools,
            "candidate_pools_sorted": serialized_sorted_pools,
            "site_assignments": copy.deepcopy(assignments),
            "uniqueness_guarantee": False,
        }
        build_path = model_dir / "composition-build.json"
        _annotate(build_path, provenance)
        build.update(provenance)
        reference_path = Path(build["reference_model_path"])
        _annotate(reference_path / "model.json", provenance)
        _annotate(reference_path / "dopants.json", provenance)
        _annotate(reference_path / "atom-lineage.json", provenance)
        if build.get("model_path"):
            child_path = Path(build["model_path"])
            _annotate(child_path / "model.json", provenance)
            _annotate(child_path / "dopants.json", provenance)
            _annotate(child_path / "atom-lineage.json", provenance)
        if build.get("study_path") and Path(build["study_path"]).resolve() != parent_study_path:
            _annotate(Path(build["study_path"]), provenance)
        records.append({**copy.deepcopy(configuration), "status": build["status"], "random_seed": seed,
                        "random_algorithm": RANDOM_ALGORITHM, "numpy_version": np.__version__,
                        "request_path": str(subrequest_path.resolve()),
                        "build_path": str(build_path.resolve()), "build": build,
                        "assignments": assignments, "candidate_pools_raw": serialized_raw_pools,
                        "candidate_pools_sorted": serialized_sorted_pools,
                        "reference_model_path": build.get("reference_model_path"),
                        "reference_model_ref": build.get("reference_model_ref"),
                        "model_ref": build.get("model_ref"),
                        "model_path": build.get("model_path"), "study_path": build.get("study_path")})
    result = {
        "schema": OUTPUT_SCHEMA,
        "configuration_set_id": configuration_set_id,
        "status": "complete" if all(item["status"] == "resolved" for item in records) else "unresolved",
        "study_id": parent_study_id,
        "model_ref": parent_ref,
        "parent_study_path": str(parent_study_path),
        "parent_model_ref": parent_ref,
        "configurations": records,
        "configuration_count": len(records),
        "max_configurations": max_configurations,
        "random_algorithm": RANDOM_ALGORITHM,
        "numpy_version": np.__version__,
        "uniqueness_guarantee": False,
        "native_scheduler_job_id": None,
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "source_refs": [str(request_file), str(parent_study_path), str(parent_model_path)],
    }
    (output / "composition-configurations.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


__all__ = ["OUTPUT_SCHEMA", "RANDOM_ALGORITHM", "REQUEST_SCHEMA", "build_composition_configurations", "sample_composition_assignments"]
