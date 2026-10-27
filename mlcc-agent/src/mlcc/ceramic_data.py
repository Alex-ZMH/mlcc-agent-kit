"""Direct ceramic E/F/virial source inspection and per-system conversion.

The adapter keeps source systems separate because the existing DeePMD
converter compares model identity as part of its effective method.  It does
not discover sources, infer charge, or qualify a material for production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from ase.io import read as ase_read

from mlcc.modeling import read_model_artifacts
from mlcc.electronic import _parse_input, _parse_input_kmesh
from mlcc_deepmd.dataset import convert_to_deepmd


SCHEMA = "mlcc.ceramic-data-request.v1"
COLLECTION_SCHEMA = "mlcc.ceramic-dataset-collection.v1"
SOURCE_SCHEMA = "mlcc.deepmd-source-manifest.v1"
PURPOSE = "ordinary_neutral_energy_force_virial"
METHOD_FIELDS = (
    "engine", "abacus_version_target", "method_set", "basis_type",
    "dft_functional", "nspin", "lspinorb", "noncolin", "occupations",
    "initial_moments_muB_by_element", "parameters", "pseudopotential_ids",
    "pseudopotential_metadata", "pseudopotential_treatment", "kpoints",
    "element_order", "net_charge",
)
UNSUPPORTED = ["polarization", "fieldforce", "dielectric"]
NEUTRAL_NOTE = (
    "ABACUS 3.10.1 neutral UPF electron-count convention: absent nelec and "
    "nelec_delta use the neutral valence count from the UPF files; an explicit "
    "nelec=0 is a neutral adjustment and does not mean zero electrons."
)


def _json(path: str | Path, label: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return dict(value)


def _absolute(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be an absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path: {value}")
    return path.resolve()


def _integer_zero(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be integer zero")
    integer = value
    if integer != 0:
        raise ValueError(f"{label} must be zero for ordinary neutral data")
    return integer


def _input_electrons(path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2 and fields[0] in {"nelec", "nelec_delta"}:
            numeric = float(fields[1])
            if numeric != 0.0:
                raise ValueError(f"INPUT {fields[0]} must be zero for ordinary neutral data")
            values[fields[0]] = {"present": True, "value": numeric}
    for name in ("nelec", "nelec_delta"):
        values.setdefault(name, {"present": False, "value": None})
    values["interpretation"] = NEUTRAL_NOTE
    return values


def _native_method(method: Mapping[str, Any], task_dir: Path) -> dict[str, Any]:
    native = _parse_input(task_dir / "INPUT")
    parameters = method["parameters"]
    numeric = {"ecutwfc": parameters["ecutwfc_Ry"], "scf_thr": parameters["scf_thr"],
               "scf_nmax": parameters["scf_nmax"], "nbands": parameters["nbands"],
               "mixing_beta": parameters["mixing_beta"], "nspin": method["nspin"],
               "lspinorb": int(method["lspinorb"]), "noncolin": int(method["noncolin"]),
               "symmetry": method["symmetry"]}
    for key, value in numeric.items():
        if float(native[key]) != value:
            raise ValueError(f"native INPUT {key} differs from method")
    text = {key: method[key] for key in ("dft_functional", "basis_type", "mixing_type")}
    text["smearing_method"] = "fixed" if method["occupations"] == "fixed" else method["smearing_method"]
    for key, value in text.items():
        if native[key] != value:
            raise ValueError(f"native INPUT {key} differs from method")
    mesh, shift = _parse_input_kmesh(task_dir / "KPT")
    if mesh != method["kpoints"]:
        raise ValueError("native KPT differs from method kpoints")
    return {**numeric, **text, "kpoints": mesh, "kpoint_shift": shift}


def _charge(method: Mapping[str, Any], task: Mapping[str, Any], result: Mapping[str, Any], spec: Mapping[str, Any], task_dir: Path) -> dict[str, Any]:
    source = spec.get("charge_source")
    if not isinstance(source, Mapping) or source.get("field") != "net_charge":
        raise ValueError("charge_source must name method.json field net_charge")
    charge_file = _absolute(source.get("file"), "charge_source.file")
    if charge_file != (task_dir / "method.json").resolve():
        raise ValueError("charge_source.file must be this task's method.json")
    value = method.get("net_charge")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("method.json net_charge must be an explicit integer")
    if value != 0:
        raise ValueError("q+2 or non-neutral charge is not valid for ordinary neutral data")
    fields: dict[str, Any] = {"method": {"present": True, "value": value}}
    for label, record in (("task", task), ("result", result)):
        if "net_charge" not in record:
            fields[label] = {"present": False, "value": None}
        else:
            fields[label] = {"present": True, "value": _integer_zero(record["net_charge"], f"{label}.net_charge")}
    return {"source_file": str(charge_file), "source_field": "net_charge", "fields": fields}


def _parent_mapping(model: Any, parent: Any | None) -> dict[str, Any]:
    metadata = model.metadata
    raw_lineage = metadata.get("atom_lineage")
    lineage_file = metadata.get("atom_lineage_file")
    lineage_parent: Mapping[str, Any] | None = None
    if lineage_file:
        lineage_document = _json(model.artifact_dir / str(lineage_file), "atom-lineage.json")
        file_entries = lineage_document.get("entries")
        if isinstance(lineage_document.get("parent_model"), Mapping):
            lineage_parent = lineage_document["parent_model"]
        if raw_lineage is not None and file_entries != raw_lineage:
            raise ValueError("model atom_lineage differs from atom-lineage.json")
        raw_lineage = file_entries
    if parent is None:
        if metadata.get("parent_models"):
            raise ValueError("root model unexpectedly has parent_models")
        return {"parent_system_id": None, "entries": raw_lineage or [], "deleted_atom_ids": []}
    parent_refs = metadata.get("parent_models")
    if not isinstance(parent_refs, list) or len(parent_refs) != 1:
        raise ValueError("derived model must record exactly one parent_models entry")
    parent_ref = parent_refs[0]
    if (
        not isinstance(parent_ref, Mapping)
        or parent_ref.get("model_id") != parent.model_id
        or parent_ref.get("version") != parent.version
        or Path(parent_ref.get("path", "")).expanduser().resolve() != Path(parent.artifact_dir).resolve()
    ):
        raise ValueError("metadata.parent_models does not bind the requested parent model")
    if (
        not isinstance(lineage_parent, Mapping)
        or lineage_parent.get("model_id") != parent.model_id
        or lineage_parent.get("version") != parent.version
        or Path(lineage_parent.get("path", "")).expanduser().resolve() != Path(parent.artifact_dir).resolve()
    ):
        raise ValueError("atom-lineage.json does not bind the requested parent model")
    if not isinstance(raw_lineage, list):
        raise ValueError("derived model requires atom-lineage entries")
    parent_ids = set(parent.atom_ids)
    child_ids = set(model.atom_ids)
    if not np.allclose(model.atoms.cell.array, parent.atoms.cell.array, rtol=0.0, atol=1e-8):
        raise ValueError("only same-cell parent-child atom deletion is supported")
    if len(model.atoms) >= len(parent.atoms) or not child_ids < parent_ids:
        raise ValueError("parent-child mapping must be a same-cell atom deletion")
    seen_child: set[int] = set()
    seen_parent: set[int] = set()
    for entry in raw_lineage:
        child_id = int(entry["child_atom_id"])
        parent_id = int(entry["parent_atom_id"])
        if child_id != parent_id:
            raise ValueError("retained parent atom IDs must not be reassigned")
        if child_id in seen_child or parent_id in seen_parent:
            raise ValueError("atom-lineage contains duplicate atom IDs")
        if child_id not in child_ids or parent_id not in parent_ids:
            raise ValueError("atom-lineage contains an atom outside parent/child models")
        if entry.get("element") != model.atoms[model.atom_ids.index(child_id)].symbol:
            raise ValueError("atom-lineage child element disagrees with model")
        if entry["element"] != parent.atoms[parent.atom_ids.index(parent_id)].symbol:
            raise ValueError("atom-lineage parent element disagrees with model")
        if entry.get("parent_image") != [0, 0, 0] or entry.get("kind") != "retained_parent_atom":
            raise ValueError("only retained same-cell parent atoms are supported")
        seen_child.add(child_id)
        seen_parent.add(parent_id)
    if seen_child != child_ids or seen_parent != child_ids:
        raise ValueError("atom-lineage does not cover every child atom exactly once")
    return {
        "parent_system_id": None,
        "entries": raw_lineage,
        "deleted_atom_ids": sorted(parent_ids - seen_parent),
        "parent_model": {"model_id": parent.model_id, "version": parent.version, "path": str(Path(parent.artifact_dir).resolve())},
    }


def _validate_request(request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    if request.get("schema") != SCHEMA:
        raise ValueError(f"unsupported ceramic request schema: {request.get('schema')!r}")
    if request.get("purpose") != PURPOSE:
        raise ValueError(f"unsupported ceramic data purpose: {request.get('purpose')!r}")
    if not isinstance(request.get("dataset_id"), str) or not request["dataset_id"].strip():
        raise ValueError("dataset_id is required")
    type_map = request.get("type_map")
    if not isinstance(type_map, list) or not type_map or any(not isinstance(v, str) or not v for v in type_map) or len(set(type_map)) != len(type_map):
        raise ValueError("type_map must be an explicit unique element list")
    systems = request.get("systems")
    if not isinstance(systems, list) or not systems:
        raise ValueError("systems must be a non-empty list")
    seen: set[str] = set()
    groups: dict[str, str] = {}
    for index, spec in enumerate(systems):
        if not isinstance(spec, Mapping):
            raise ValueError("each system must be an object")
        system_id = spec.get("system_id")
        if not isinstance(system_id, str) or not system_id.strip() or system_id in seen:
            raise ValueError(f"system_id is missing or duplicated at index {index}")
        if Path(system_id).name != system_id or system_id in {".", ".."}:
            raise ValueError("system_id must be a single directory name")
        if spec.get("split") not in {"train", "validation"}:
            raise ValueError(f"system {system_id} requires split train or validation")
        source_group = spec.get("source_group")
        if not isinstance(source_group, str) or not source_group.strip():
            raise ValueError(f"system {system_id} requires source_group")
        if source_group in groups and groups[source_group] != spec["split"]:
            raise ValueError(f"source_group {source_group!r} crosses train/validation splits")
        parent = spec.get("parent_system_id")
        if parent is not None and (index == 0 or parent != systems[index - 1].get("system_id")):
            raise ValueError(f"system {system_id} parent_system_id must be the previous system")
        seen.add(system_id)
        groups[source_group] = spec["split"]
    return [dict(spec) for spec in systems], [str(v) for v in type_map]


def inspect_ceramic_sources(request: Mapping[str, Any]) -> dict[str, Any]:
    """Read and validate all sources before any output conversion is written."""
    systems, type_map = _validate_request(request)
    records: list[dict[str, Any]] = []
    common_method: dict[str, Any] | None = None
    models: dict[str, Any] = {}
    for spec in systems:
        system_id = str(spec["system_id"])
        task_dir = _absolute(spec.get("task_dir"), f"system {system_id} task_dir")
        task = _json(task_dir / "task.json", f"{system_id} task.json")
        result = _json(task_dir / "result.json", f"{system_id} result.json")
        method = _json(task_dir / "method.json", f"{system_id} method.json")
        input_path = task_dir / "INPUT"
        for path in (input_path, task_dir / "KPT", task_dir / "input.extxyz", task_dir / "final.extxyz", task_dir / "STRU.atom-map.json"):
            if not path.is_file():
                raise FileNotFoundError(path)
        if method.get("engine") != "abacus" or method.get("abacus_version_target") != "3.10.1":
            raise ValueError(f"system {system_id} requires ABACUS 3.10.1")
        if task.get("engine") != "abacus" or task.get("engine_version") != "3.10.1":
            raise ValueError(f"system {system_id} task is not bound to ABACUS 3.10.1")
        if task.get("runner") != "slurm" or task.get("status") != "COMPLETED" or task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0" or not str(task.get("scheduler_job_id", "")).strip():
            raise ValueError(f"system {system_id} lacks Slurm COMPLETED/0:0 evidence")
        if task.get("method_set") != method.get("method_set"):
            raise ValueError(f"system {system_id} task method_set disagrees with method")
        if result.get("task_id") != task.get("task_id") or result.get("scheduler_job_id") != task.get("scheduler_job_id") or result.get("method_set") != method.get("method_set") or result.get("electronic_converged") is not True:
            raise ValueError(f"system {system_id} result is not bound to task and method")
        for flag in ("fixture", "production_label"):
            if task.get(flag) is not None and result.get(flag) is not None and task.get(flag) != result.get(flag):
                raise ValueError(f"system {system_id} {flag} disagrees between task and result")
        if (result.get("scientific_status") or task.get("scientific_status")) not in {"converged", "converged_engineering_fixture"}:
            raise ValueError(f"system {system_id} is not electronically converged")
        model_path = _absolute(task.get("model_path"), f"system {system_id} model_path")
        model = read_model_artifacts(model_path)
        models[system_id] = model
        if Path(model.artifact_dir).resolve() != model_path or model.model_id != task.get("model_id") or model.version != task.get("model_version"):
            raise ValueError(f"system {system_id} task/model identity is not bound")
        if model.metadata.get("fixture") is not None and task.get("fixture") is not None and model.metadata.get("fixture") != task.get("fixture"):
            raise ValueError(f"system {system_id} fixture flag disagrees with persisted model")
        for identity in (method, result):
            if identity.get("model_id") is not None and identity.get("model_id") != model.model_id:
                raise ValueError(f"system {system_id} model_id disagrees with source")
            if identity.get("version") is not None and identity.get("version") != model.version:
                raise ValueError(f"system {system_id} model version disagrees with source")
        source_atoms = ase_read(str(task_dir / "input.extxyz"), format="extxyz", index=0)
        if "atom_id" not in source_atoms.arrays:
            raise ValueError(f"system {system_id} input.extxyz lacks atom_id")
        source_ids = [int(value) for value in source_atoms.arrays["atom_id"]]
        if (not len(model.atoms) or source_ids != model.atom_ids
                or source_atoms.get_chemical_symbols() != model.atoms.get_chemical_symbols()
                or not np.allclose(source_atoms.cell.array, model.atoms.cell.array, rtol=0.0, atol=1e-8)
                or list(source_atoms.pbc) != list(model.atoms.pbc)
                or not np.allclose(source_atoms.positions, model.atoms.positions, rtol=0.0, atol=1e-8)):
            raise ValueError(f"system {system_id} input.extxyz disagrees with persisted model")
        if set(model.atoms.get_chemical_symbols()) != set(type_map) or method.get("element_order") != type_map:
            raise ValueError(f"system {system_id} model elements disagree with explicit type_map")
        if [int(v) for v in result.get("atom_ids", [])] != model.atom_ids:
            raise ValueError(f"system {system_id} result atom IDs disagree with model")
        signature = {field: method[field] for field in METHOD_FIELDS}
        signature["native_method"] = _native_method(method, task_dir)
        if common_method is None:
            common_method = signature
        elif signature != common_method:
            raise ValueError(f"system {system_id} physical method differs from the collection")
        charges = _charge(method, task, result, spec, task_dir)
        input_electrons = _input_electrons(input_path)
        for label, source in (("task", task), ("result", result)):
            for key in ("nelec", "nelec_delta"):
                if source.get(key) is not None:
                    _integer_zero(source[key], f"{label}.{key}")
        if model.metadata.get("charge_state") not in (None, 0):
            raise ValueError(f"system {system_id} q+2 model cannot serve ordinary neutral data")
        parent_id = spec.get("parent_system_id")
        parent = models.get(parent_id) if parent_id is not None else None
        if parent_id is not None:
            parent_spec = next(item for item in systems if item.get("system_id") == parent_id)
            if parent_spec.get("source_group") != spec.get("source_group") or parent_spec.get("split") != spec.get("split"):
                raise ValueError(f"system {system_id} parent must share source_group and split")
        parent_mapping = _parent_mapping(model, parent)
        parent_mapping["parent_system_id"] = parent_id
        source_manifest = {
            "schema": SOURCE_SCHEMA, "engine": "abacus", "method_set": method["method_set"], "type_map": type_map,
            "virial": {"source": "result.stress_GPa", "sign": "source_stress_times_volume", "input_unit": "GPa", "output_unit": "eV"},
            "sources": [{"task_id": task["task_id"], "split": spec["split"], "source_group": spec["source_group"], "label": system_id,
                         "task_dir": str(task_dir), "task": "task.json", "result": "result.json", "method": "method.json",
                         "input": "INPUT", "kpoints": "KPT", "input_structure": "input.extxyz", "structure": "final.extxyz",
                         "atom_map": "STRU.atom-map.json"}],
        }
        records.append({"system_id": system_id, "spec": spec, "task": task, "result": result, "method": method, "model": model,
                        "task_dir": task_dir, "charge": charges, "input_electrons": input_electrons, "parent": parent_mapping,
                        "source_manifest": source_manifest})
    return {"dataset_id": request["dataset_id"], "purpose": request["purpose"], "type_map": type_map, "systems": records, "common_method": common_method}


def convert_ceramic_systems(request_path: str | Path | Mapping[str, Any], output_directory: str | Path) -> dict[str, Any]:
    """Convert each explicitly listed ceramic frame and write one final collection manifest."""
    request = dict(request_path) if isinstance(request_path, Mapping) else _json(request_path, "ceramic request")
    inspected = inspect_ceramic_sources(request)
    output = Path(output_directory).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    systems: list[dict[str, Any]] = []
    for record in inspected["systems"]:
        system_output = output / record["system_id"]
        manifest = convert_to_deepmd(record["source_manifest"], system_output)
        npy_paths = [str(system_output / path) for frame in manifest["systems"] for item in frame["frames"] for path in item["npy"].values() if isinstance(path, str)]
        task, result, method, model = record["task"], record["result"], record["method"], record["model"]
        source_record = {**record["source_manifest"]["sources"][0],
                         "task": str((record["task_dir"] / "task.json").resolve()),
                         "result": str((record["task_dir"] / "result.json").resolve()),
                         "method": str((record["task_dir"] / "method.json").resolve()),
                         "input": str((record["task_dir"] / "INPUT").resolve()),
                         "kpoints": str((record["task_dir"] / "KPT").resolve()),
                         "input_structure": str((record["task_dir"] / "input.extxyz").resolve()),
                         "structure": str((record["task_dir"] / "final.extxyz").resolve()),
                         "atom_map": str((record["task_dir"] / "STRU.atom-map.json").resolve())}
        systems.append({"system_id": record["system_id"], "split": record["spec"]["split"], "source_group": record["spec"]["source_group"],
                        "parent_system_id": record["spec"].get("parent_system_id"), "manifest_path": str((system_output / "dataset_manifest.json").resolve()),
                        "dataset_systems": manifest["systems"], "npy_paths": npy_paths, "source": source_record,
                        "task_id": task["task_id"], "scheduler_job_id": task["scheduler_job_id"], "study_id": task.get("study_id"),
                        "case_id": task.get("case_id"), "case_role": task.get("case_role"), "fixture": task.get("fixture"),
                        "production_label": task.get("production_label"), "model_id": model.model_id, "model_version": model.version,
                        "model_path": str(Path(model.artifact_dir).resolve()), "method": record["method"], "charge": record["charge"],
                        "input_electrons": record["input_electrons"], "parent_mapping": record["parent"], "production_qualification": False,
                        "scientific_qualification": False,
                        "unsupported": list(UNSUPPORTED)})
    collection = {"schema": COLLECTION_SCHEMA, "dataset_id": inspected["dataset_id"], "purpose": inspected["purpose"], "format": "deepmd/npy",
                  "type_map": inspected["type_map"], "method": inspected["common_method"], "systems": systems,
                  "production_qualification": False, "scientific_qualification": False, "training_collector_interface": "not_claimed",
                  "unsupported": list(UNSUPPORTED), "units": {"energy": "eV", "force": "eV/angstrom", "stress": "GPa", "virial": "eV"},
                  "virial": {"formula": "stress_GPa * cell_volume_A3 / 160.21766208", "source": "ABACUS abacus_printed"}}
    (output / "collection.json").write_text(json.dumps(collection, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return collection


__all__ = ["convert_ceramic_systems", "inspect_ceramic_sources"]
