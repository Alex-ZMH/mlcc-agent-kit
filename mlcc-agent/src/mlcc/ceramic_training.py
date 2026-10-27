"""Bind converted ceramic systems to the existing DeePMD training contract.

The converter deliberately writes one DeePMD manifest per source system.  A
joint training run needs one manifest whose relative paths are rooted at the
collection directory.  This module performs that mechanical binding only: it
does not copy frames, infer labels, create a validation split, or qualify the
resulting model.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from mlcc_deepmd.training import DeepMDTrainingConfig


DATASET_SCHEMA = "mlcc.deepmd-dataset-manifest.v1"
COLLECTION_SCHEMA = "mlcc.ceramic-dataset-collection.v1"


def _read_object(path: str | Path, label: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return dict(value)


def _path_part(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a relative path inside the collection")
    return path.as_posix()


def _namespace(prefix: str, value: Any, label: str) -> str:
    return f"{prefix}/{_path_part(value, label)}"


def _child_manifest_path(collection_path: Path, entry: Mapping[str, Any]) -> Path:
    """Resolve the child manifest at its fixed collection-relative location."""

    system_id = entry.get("system_id")
    if not isinstance(system_id, str) or not system_id or Path(system_id).name != system_id:
        raise ValueError("collection system_id must be one directory name")
    return (collection_path.parent / system_id / "dataset_manifest.json").resolve()


def _same(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        raise ValueError(f"{label} differs from the ceramic collection")


def _rebase_system(system: Mapping[str, Any], prefix: str, label: str) -> dict[str, Any]:
    row = copy.deepcopy(dict(system))
    path = _namespace(prefix, row.get("path"), f"{label}.path")
    row["path"] = path
    for field in ("type_raw", "type_map_raw"):
        row[field] = _namespace(prefix, row.get(field), f"{label}.{field}")
    sets = row.get("sets")
    if not isinstance(sets, list):
        raise ValueError(f"{label}.sets must be a list")
    row["sets"] = [_namespace(prefix, item, f"{label}.sets") for item in sets]
    frames = row.get("frames")
    if not isinstance(frames, list):
        raise ValueError(f"{label}.frames must be a list")
    for frame_index, frame_value in enumerate(frames):
        if not isinstance(frame_value, Mapping):
            raise ValueError(f"{label}.frames[{frame_index}] must be an object")
        frame = frame_value
        frame["set_path"] = _namespace(prefix, frame.get("set_path"), f"{label}.frames[{frame_index}].set_path")
        npy = frame.get("npy")
        if not isinstance(npy, Mapping):
            raise ValueError(f"{label}.frames[{frame_index}].npy must be an object")
        rebased_npy = dict(npy)
        for key, value in list(rebased_npy.items()):
            if key != "row":
                rebased_npy[key] = _namespace(prefix, value, f"{label}.frames[{frame_index}].npy.{key}")
        frame["npy"] = rebased_npy
        source = frame.get("source")
        if isinstance(source, Mapping):
            source_copy = dict(source)
            if "system" in source_copy:
                source_copy["system"] = _namespace(prefix, source_copy["system"], f"{label}.frames[{frame_index}].source.system")
            if "set" in source_copy:
                source_copy["set"] = _namespace(prefix, source_copy["set"], f"{label}.frames[{frame_index}].source.set")
            frame["source"] = source_copy
        row["frames"][frame_index] = frame
    return row


def _rebase_set(value: Mapping[str, Any], prefix: str, label: str) -> dict[str, Any]:
    row = copy.deepcopy(dict(value))
    row["path"] = _namespace(prefix, row.get("path"), f"{label}.path")
    row["system"] = _namespace(prefix, row.get("system"), f"{label}.system")
    return row


def _source_records(child: Mapping[str, Any], prefix: str, system_id: str) -> list[dict[str, Any]]:
    sources = child.get("sources")
    if not isinstance(sources, list):
        raise ValueError(f"child manifest {system_id}.sources must be a list")
    result: list[dict[str, Any]] = []
    for index, source_value in enumerate(sources):
        if not isinstance(source_value, Mapping):
            raise ValueError(f"child manifest {system_id}.sources[{index}] must be an object")
        source = copy.deepcopy(dict(source_value))
        task_id = source.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"child manifest {system_id}.sources[{index}] requires task_id")
        provenance = source.get("task_provenance")
        if not isinstance(provenance, Mapping) or not str(provenance.get("scheduler_job_id", "")):
            raise ValueError(f"child manifest {system_id}.sources[{index}] requires scheduler_job_id")
        _same(source.get("engine"), "abacus", f"source {task_id}.engine")
        source["system"] = _namespace(prefix, source["system"], f"source {task_id}.system")
        source["collection_system_id"] = system_id
        result.append(source)
    return result


def _check_child_method(child: Mapping[str, Any], common: Mapping[str, Any], system_id: str) -> None:
    """Compare the common method fields with a child's effective signature.

    Child manifests wrap their source signature under ``effective_signature``
    and omit optional ``None`` controls that the collection's common method
    records explicitly.  Normalize only those documented optional fields; all
    present physical controls must match exactly.
    """

    child_method = child.get("method")
    if not isinstance(child_method, Mapping):
        raise ValueError(f"{system_id} child method must be an object")
    effective = child_method.get("effective_signature")
    if not isinstance(effective, Mapping):
        raise ValueError(f"{system_id} child method lacks effective_signature")
    for key, expected in common.items():
        if key == "native_method":
            continue
        if key == "parameters":
            actual_parameters = effective.get("parameters")
            if not isinstance(actual_parameters, Mapping):
                raise ValueError(f"{system_id} child method lacks parameters")
            normalized = dict(actual_parameters)
            for optional in ("force_thr_eV_per_A", "relax_nmax"):
                normalized.setdefault(optional, None)
            _same(normalized, expected, f"{system_id} child method.parameters")
            continue
        if key not in effective:
            raise ValueError(f"{system_id} child method lacks {key}")
        _same(effective[key], expected, f"{system_id} child method.{key}")


def bind_ceramic_training_dataset(
    collection_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Create a namespaced joint DeePMD manifest from an existing collection.

    ``output_path`` is a manifest file.  Existing converted ``.npy`` files are
    never copied or modified; training resolves every path relative to the
    collection directory.
    """

    collection_file = Path(collection_path).expanduser().resolve()
    collection = _read_object(collection_file, "ceramic collection")
    if collection.get("schema") != COLLECTION_SCHEMA:
        raise ValueError(f"unsupported ceramic collection schema: {collection.get('schema')!r}")
    if collection.get("format") != "deepmd/npy":
        raise ValueError("ceramic collection format must be deepmd/npy")
    if collection.get("type_map") is None or not isinstance(collection["type_map"], list):
        raise ValueError("ceramic collection requires type_map")
    type_map = list(collection["type_map"])
    method = collection.get("method")
    if not isinstance(method, Mapping):
        raise ValueError("ceramic collection requires a common method")
    _same(method.get("engine"), "abacus", "collection method.engine")
    method_set = method.get("method_set")
    if not isinstance(method_set, str) or not method_set:
        raise ValueError("ceramic collection requires a common method_set")

    entries = collection.get("systems")
    if not isinstance(entries, list) or not entries:
        raise ValueError("ceramic collection systems must be a non-empty list")
    training_systems: list[str] = []
    validation_systems: list[str] = []
    systems: list[dict[str, Any]] = []
    sets: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    collection_systems: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_tasks: set[str] = set()
    source_group_splits: dict[str, str] = {}
    child_units: dict[str, Any] | None = None
    child_virial: dict[str, Any] | None = None

    for entry_value in entries:
        if not isinstance(entry_value, Mapping):
            raise ValueError("collection systems must contain objects")
        entry = dict(entry_value)
        system_id = entry.get("system_id")
        if not isinstance(system_id, str) or not system_id or Path(system_id).name != system_id:
            raise ValueError("collection system_id must be one directory name")
        if system_id in seen_ids:
            raise ValueError(f"duplicate collection system_id: {system_id}")
        seen_ids.add(system_id)
        split = entry.get("split")
        if split not in {"train", "validation"}:
            raise ValueError(f"collection system {system_id} requires train or validation split")
        child_path = _child_manifest_path(collection_file, entry)
        child = _read_object(child_path, f"{system_id} dataset manifest")
        if child.get("schema") != DATASET_SCHEMA:
            raise ValueError(f"{system_id} child manifest schema differs")
        _same(child.get("engine"), "abacus", f"{system_id} engine")
        _same(child.get("method_set"), method_set, f"{system_id} method_set")
        _same(child.get("type_map"), type_map, f"{system_id} type_map")
        _check_child_method(child, method, system_id)
        if child_units is None:
            if not isinstance(child.get("units"), Mapping):
                raise ValueError(f"{system_id} child units must be an object")
            child_units = copy.deepcopy(dict(child["units"]))
        else:
            _same(child.get("units"), child_units, f"{system_id} child units")
        if child_virial is None:
            if not isinstance(child.get("virial"), Mapping):
                raise ValueError(f"{system_id} child virial must be an object")
            child_virial = copy.deepcopy(dict(child["virial"]))
        else:
            _same(child.get("virial"), child_virial, f"{system_id} child virial")
        if child.get("systems") != entry.get("dataset_systems"):
            raise ValueError(f"{system_id} child systems differ from collection dataset_systems")
        child_train = child["training_systems"]
        child_validation = child["validation_systems"]
        if not isinstance(child_train, list) or not isinstance(child_validation, list):
            raise ValueError(f"{system_id} child split paths must be lists")
        if not child_train and not child_validation:
            raise ValueError(f"{system_id} child split paths must not be empty")
        child_system_rows = child.get("systems")
        if not isinstance(child_system_rows, list):
            raise ValueError(f"{system_id} child systems must be a list")
        child_by_path = {row.get("path"): row for row in child_system_rows if isinstance(row, Mapping)}
        if len(child_by_path) != len(child_system_rows):
            raise ValueError(f"{system_id} child systems have invalid paths")
        prefix = system_id

        def add_system(child_system_path_value: Any, declared_split: str) -> None:
            child_system_path = _path_part(child_system_path_value, f"{system_id}.training_systems")
            if child_system_path not in child_by_path:
                raise ValueError(f"{system_id} training path has no systems entry: {child_system_path}")
            child_row = child_by_path[child_system_path]
            _same(child_row.get("split"), declared_split, f"{system_id} system {child_system_path}.split")
            _same(split, declared_split, f"{system_id} collection split")
            source_group = entry["source_group"]
            if not isinstance(source_group, str) or not source_group:
                raise ValueError(f"{system_id}.source_group is required")
            frames = child_row["frames"]
            if not isinstance(frames, list) or not frames:
                raise ValueError(f"{system_id} system {child_system_path}.frames must be non-empty")
            for frame_index, frame in enumerate(frames):
                if not isinstance(frame, Mapping):
                    raise ValueError(f"{system_id} system {child_system_path}.frames[{frame_index}] must be an object")
                _same(frame["source_group"], source_group,
                      f"{system_id} system {child_system_path}.frames[{frame_index}].source_group")
            prior_split = source_group_splits.setdefault(source_group, declared_split)
            _same(prior_split, declared_split, f"source_group {source_group} crosses train/validation")
            namespaced = f"{prefix}/{child_system_path}"
            (training_systems if declared_split == "train" else validation_systems).append(namespaced)
            row = _rebase_system(child_row, prefix, f"{system_id}.systems[{child_system_path}]")
            row["collection_system_id"] = system_id
            row["collection_split"] = split
            row["collection_metadata"] = {
                "task_id": entry.get("task_id"),
                "scheduler_job_id": entry.get("scheduler_job_id"),
                "study_id": entry.get("study_id"),
                "case_id": entry.get("case_id"),
                "case_role": entry.get("case_role"),
                "fixture": entry.get("fixture"),
                "production_label": entry.get("production_label"),
                "charge": copy.deepcopy(entry.get("charge")),
                "input_electrons": copy.deepcopy(entry.get("input_electrons")),
                "parent_system_id": entry.get("parent_system_id"),
                "parent_mapping": copy.deepcopy(entry.get("parent_mapping")),
                "production_qualification": entry.get("production_qualification", False),
                "scientific_qualification": entry.get("scientific_qualification", False),
                "source": copy.deepcopy(entry.get("source")),
                "method": copy.deepcopy(entry.get("method")),
            }
            systems.append(row)

        for child_system_path_value in child_train:
            add_system(child_system_path_value, "train")
        for child_system_path_value in child_validation:
            add_system(child_system_path_value, "validation")
        child_sets = child.get("sets")
        if not isinstance(child_sets, list):
            raise ValueError(f"{system_id} child sets must be a list")
        for set_index, set_value in enumerate(child_sets):
            if not isinstance(set_value, Mapping):
                raise ValueError(f"{system_id}.sets[{set_index}] must be an object")
            sets.append(_rebase_set(set_value, prefix, f"{system_id}.sets[{set_index}]"))
        child_sources = _source_records(child, prefix, system_id)
        for source in child_sources:
            task_id = source["task_id"]
            if task_id in seen_tasks:
                raise ValueError(f"duplicate source task_id: {task_id}")
            seen_tasks.add(task_id)
            _same(source.get("method_set"), method_set, f"source {task_id}.method_set")
            _same(source.get("task_id"), entry.get("task_id"), f"source {task_id}.task_id")
            _same(str(source["task_provenance"]["scheduler_job_id"]), str(entry.get("scheduler_job_id")),
                  f"source {task_id}.scheduler_job_id")
            source_group = source.get("source_group")
            _same(source.get("split"), split, f"source {task_id}.split")
            if not isinstance(source_group, str) or not source_group:
                raise ValueError(f"source {task_id}.source_group is required")
            _same(source_group, entry.get("source_group"), f"source {task_id}.source_group")
            prior_split = source_group_splits.setdefault(source_group, split)
            _same(prior_split, split, f"source_group {source_group} crosses train/validation")
            sources.append(source)
        collection_systems.append(entry)

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema": DATASET_SCHEMA,
        "format": "deepmd/npy",
        "engine": "abacus",
        "method_set": method_set,
        "method": copy.deepcopy(dict(method)),
        "type_map": type_map,
        "splits": {"train": list(training_systems), "validation": list(validation_systems)},
        "training_systems": training_systems,
        "validation_systems": validation_systems,
        "systems": systems,
        "sets": sets,
        "units": copy.deepcopy(collection.get("units", {})),
        "virial": copy.deepcopy(collection.get("virial", {})),
        "sources": sources,
        "source_task_ids": [source["task_id"] for source in sources],
        "source_scheduler_job_ids": [source["task_provenance"]["scheduler_job_id"] for source in sources],
        "collection_path": str(collection_file),
        "collection_dataset_id": collection.get("dataset_id"),
        "collection": copy.deepcopy(collection),
        "collection_systems": collection_systems,
        "production_qualification": False,
        "scientific_qualification": False,
        "scientific_status": "not_qualified",
        "engineering_only": True,
        "unsupported": copy.deepcopy(collection.get("unsupported", [])),
    }
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def create_ceramic_training_task(
    workspace: str | Path,
    task_id: str,
    config: "DeepMDTrainingConfig",
    input_file: str | Path,
    collection_path: str | Path,
    interface_acceptance: str | Path,
    *,
    account: str,
) -> Any:
    """Bind a collection, then create its existing DeePMD ``TaskRecord``.

    The standalone bridge remains responsible for staging the input, writing
    the sbatch script, and preserving scheduler lifecycle fields.  This thin
    wrapper only supplies the joint manifest and records that its source is a
    non-fixture ceramic collection.
    """

    from mlcc_deepmd.integration import create_training_task

    workspace_path = Path(workspace).expanduser().resolve()
    collection_file = Path(collection_path).expanduser().resolve()
    dataset_path = workspace_path / "datasets" / f"{task_id}.dataset-manifest.json"
    manifest = bind_ceramic_training_dataset(collection_file, dataset_path)
    dataset_root = str(collection_file.parent)
    task = create_training_task(
        workspace_path,
        task_id,
        config,
        input_file,
        dataset_path,
        interface_acceptance,
        account=account,
        dataset_remote_root=dataset_root,
    )
    task.set(
        fixture=False,
        source_fixture=False,
        engineering_only=True,
        production_qualification=False,
        scientific_status="not_qualified",
        design_assessment="not_assessed",
        dataset_location={
            **task.data["dataset_location"],
            "collection_path": str(collection_file),
            "collection_dataset_id": manifest.get("collection_dataset_id"),
            "systems": list(manifest["training_systems"]),
            "validation_systems": list(manifest["validation_systems"]),
        },
        integration_scope="engineering joint ceramic training through existing MLCC Slurm lifecycle",
    )
    task.record_event(
        "bind_ceramic_training_dataset",
        collection_path=str(collection_file),
        dataset_manifest=str(dataset_path),
        source_task_ids=list(manifest["source_task_ids"]),
    )
    from mlcc.tasks import save_task

    save_task(task)
    return task


def enrich_ceramic_training_model_card(task_file: str | Path) -> Any:
    """Attach ceramic provenance to an already collected DeePMD model card.

    This path is intentionally separate from scheduler collection so an
    existing completed handoff can be enriched without re-running its native
    collector or training job.
    """

    from mlcc.tasks import load_task, save_task

    task = load_task(task_file)
    handoff = task.data.get("model_handoff")
    if not isinstance(handoff, Mapping) or handoff.get("status") != "engineering_handoff":
        raise ValueError("ceramic model-card enrichment requires an engineering handoff")
    card_name = handoff.get("model_card")
    if not isinstance(card_name, str) or not card_name:
        raise ValueError("ceramic model-card enrichment requires model-card path")
    card_path = Path(task_file).expanduser().resolve().parent / card_name
    card = _read_object(card_path, "model-card")
    dataset_name = task.data.get("dataset_manifest")
    if not isinstance(dataset_name, str) or not dataset_name:
        raise ValueError("ceramic training task requires dataset manifest")
    dataset_path = Path(task_file).expanduser().resolve().parent / dataset_name
    dataset = _read_object(dataset_path, "ceramic training dataset manifest")
    unsupported = dataset.get("unsupported", [])
    if not isinstance(unsupported, list):
        raise ValueError("ceramic training dataset unsupported field must be a list")
    card.update(
        training_task_id=task.task_id,
        production_qualification=False,
        scientific_status="not_qualified",
        source_fixture=False,
        engineering_only=True,
        unsupported=copy.deepcopy(unsupported),
    )
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task.set(
        fixture=False,
        source_fixture=False,
        engineering_only=True,
        production_qualification=False,
        scientific_status="not_qualified",
    )
    task.record_event("enrich_ceramic_training_model_card", model_card=card_path.name)
    save_task(task)
    return task


def finalize_ceramic_training_task(task_file: str | Path, scheduler_record: Mapping[str, Any]) -> Any:
    """Collect a completed native training task and enrich its ceramic card."""

    from mlcc_deepmd.integration import finalize_training_task

    task = finalize_training_task(task_file, dict(scheduler_record))
    return enrich_ceramic_training_model_card(task_file)


__all__ = [
    "bind_ceramic_training_dataset",
    "create_ceramic_training_task",
    "enrich_ceramic_training_model_card",
    "finalize_ceramic_training_task",
]
