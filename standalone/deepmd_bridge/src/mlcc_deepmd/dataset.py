"""Direct ABACUS result-list to DeePMD ``deepmd/npy`` conversion.

The source list is explicit.  Every frame is re-read by
``mlcc.abacus.parse_abacus_outputs``; ``result.json`` is only checked against
the native labels.  No source discovery, fallback, retry, cache, or stress
sign calibration is performed here.
"""

from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from ase.io import read as ase_read

SCHEMA = "mlcc.deepmd-source-manifest.v1"
DATASET_SCHEMA = "mlcc.deepmd-dataset-manifest.v1"
FORMAT = "deepmd/npy"
ABACUS_ENGINE = "abacus"
CONVERGED_STATUSES = {"converged", "converged_engineering_fixture"}
GPA_PER_EV_PER_A3 = 160.21766208


class DatasetError(ValueError):
    """A source-list or scientific-contract rejection."""


def load_source_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise DatasetError("source manifest must be a JSON object")
    result = dict(payload)
    result["_base_dir"] = str(manifest_path.parent)
    return result


def convert_to_deepmd(
    source_manifest: str | Path | Mapping[str, Any], output_dir: str | Path
) -> dict[str, Any]:
    """Convert explicitly listed, converged ABACUS frames to ``deepmd/npy``."""

    manifest, base_dir = _manifest(source_manifest)
    policy = _virial_policy(manifest)
    sources = _sources(manifest, base_dir)
    frames = [_frame(source, manifest, policy) for source in sources]
    _validate_collection(frames, manifest)

    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise DatasetError(f"output directory must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    type_map = frames[0]["type_map"]
    type_indices = np.asarray(
        [type_map.index(symbol) for symbol in frames[0]["symbols"]], dtype=np.int32
    )
    records = [frame["record"] for frame in frames]
    grouped: OrderedDict[str, OrderedDict[str, list[dict[str, Any]]]] = OrderedDict()
    for frame in frames:
        grouped.setdefault(frame["split"], OrderedDict()).setdefault(
            frame["source_group"], []
        ).append(frame)

    systems: list[dict[str, Any]] = []
    sets: list[dict[str, Any]] = []
    for split, source_groups in grouped.items():
        system_rel = f"{split}/system-000"
        system_dir = output / split / "system-000"
        system_dir.mkdir(parents=True)
        np.savetxt(system_dir / "type.raw", type_indices, fmt="%d")
        (system_dir / "type_map.raw").write_text(
            "".join(f"{item}\n" for item in type_map), encoding="utf-8"
        )
        system = {
            "path": system_rel,
            "split": split,
            "type_raw": f"{system_rel}/type.raw",
            "type_map_raw": f"{system_rel}/type_map.raw",
            "type_map": list(type_map),
            "atom_ids": list(frames[0]["atom_ids"]),
            "sets": [],
            "frames": [],
        }
        for set_index, (source_group, group_frames) in enumerate(source_groups.items()):
            set_name = f"set.{set_index:03d}"
            set_rel = f"{system_rel}/{set_name}"
            set_dir = system_dir / set_name
            set_dir.mkdir()
            arrays = {
                "box": [item["cell"].reshape(-1) for item in group_frames],
                "coord": [item["positions"].reshape(-1) for item in group_frames],
                "energy": [item["energy"] for item in group_frames],
                "force": [item["forces"].reshape(-1) for item in group_frames],
                "virial": [item["virial"].reshape(-1) for item in group_frames],
            }
            for name, values in arrays.items():
                np.save(set_dir / f"{name}.npy", np.asarray(values, dtype=np.float64))
            sets.append(
                {
                    "name": set_name,
                    "path": set_rel,
                    "system": system_rel,
                    "split": split,
                    "source_group": source_group,
                    "frame_count": len(group_frames),
                    "source_task_ids": [item["task_id"] for item in group_frames],
                }
            )
            system["sets"].append(set_rel)
            for row, item in enumerate(group_frames):
                record = item["record"]
                record.update({"system": system_rel, "set": set_name, "frame_index": row})
                system["frames"].append(
                    {
                        "task_id": item["task_id"],
                        "model_id": item["model_id"],
                        "model_version": item["model_version"],
                        "set": set_name,
                        "set_path": set_rel,
                        "frame_index": row,
                        "atom_ids": list(item["atom_ids"]),
                        "type_map": list(type_map),
                        "symbols": list(item["symbols"]),
                        "cell_angstrom": item["cell"].tolist(),
                        "positions_angstrom": item["positions"].tolist(),
                        "source_group": source_group,
                        "npy": {
                            **{name: f"{set_rel}/{name}.npy" for name in arrays},
                            "row": row,
                        },
                        "source": record["paths"],
                    }
                )
        systems.append(system)

    first = frames[0]
    output_manifest = {
        "schema": DATASET_SCHEMA,
        "format": FORMAT,
        "engine": first["engine"],
        "method_set": first["method_set"],
        "method": {
            "engine": first["engine"],
            "method_set": first["method_set"],
            "effective_signature": first["effective_method"],
            "method_paths": [record["method_path"] for record in records],
        },
        "type_map": list(type_map),
        "atom_ids": list(first["atom_ids"]),
        "splits": OrderedDict(
            (system["split"], [system["path"]]) for system in systems
        ),
        "training_systems": [
            system["path"] for system in systems if system["split"] == "train"
        ],
        "validation_systems": [
            system["path"] for system in systems if system["split"] == "validation"
        ],
        "systems": systems,
        "sets": sets,
        "units": {
            "coordinates": "angstrom",
            "cell": "angstrom",
            "energy": "eV",
            "force": "eV/angstrom",
            "stress_input": "GPa",
            "virial": "eV",
        },
        "virial": {
            "source": policy["source"],
            "sign": policy["sign"],
            "source_stress_sign": first["stress_sign"],
            "conversion": "stress_GPa * cell_volume / 160.21766208",
            "gpa_per_eV_per_A3": GPA_PER_EV_PER_A3,
        },
        "sources": records,
    }
    (output / "dataset_manifest.json").write_text(
        json.dumps(output_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return output_manifest


def _manifest(value: str | Path | Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    if isinstance(value, (str, Path)):
        manifest = load_source_manifest(value)
        base_dir = Path(manifest.pop("_base_dir"))
    elif isinstance(value, Mapping):
        manifest = dict(value)
        base_dir = Path(manifest.pop("_base_dir", manifest.pop("base_dir", Path.cwd())))
    else:
        raise TypeError("source_manifest must be a path or mapping")
    if manifest.get("schema") not in (None, SCHEMA):
        raise DatasetError(f"unsupported source manifest schema: {manifest.get('schema')!r}")
    return manifest, base_dir.expanduser().resolve()


def _sources(manifest: Mapping[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)) or not raw_sources:
        raise DatasetError("source manifest requires a non-empty sources list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise DatasetError("each source must be an object")
        task_id = str(raw.get("task_id", "")).strip()
        if not task_id or task_id in seen:
            raise DatasetError(f"source task_id is missing or duplicated: {task_id!r}")
        seen.add(task_id)
        split = str(raw.get("split", "")).strip()
        source_group = str(raw.get("source_group", "")).strip()
        if not split or not source_group:
            raise DatasetError(f"source {task_id} requires split and source_group")
        task_dir = _path(base_dir, raw.get("task_dir", raw.get("path")))
        paths = {
            "task_dir": task_dir,
            "result_path": _path(task_dir, raw.get("result", "result.json")),
            "method_path": _path(task_dir, raw.get("method", "method.json")),
            "input_path": _path(task_dir, raw.get("input", "INPUT")),
            "kpoints_path": _path(task_dir, raw.get("kpoints", "KPT")),
            "input_structure_path": _path(
                task_dir, raw.get("input_structure", "input.extxyz")
            ),
            "structure_path": _path(task_dir, raw.get("structure", "final.extxyz")),
            "atom_map_path": _path(
                task_dir, raw.get("atom_map", "STRU.atom-map.json")
            ),
        }
        task_value = raw.get("task", "task.json")
        paths["task_path"] = _path(task_dir, task_value) if task_value else None
        required = (
            "result_path",
            "method_path",
            "input_path",
            "kpoints_path",
            "input_structure_path",
            "structure_path",
            "atom_map_path",
            "task_path",
        )
        for label in required:
            if paths[label] is None or not paths[label].is_file():
                raise DatasetError(f"source {task_id} {label} does not exist: {paths[label]}")
        result.append(
            {
                "task_id": task_id,
                "split": split,
                "source_group": source_group,
                "label": raw.get("label", task_id),
                **paths,
            }
        )
    return result


def _path(base: Path, value: Any) -> Path:
    if not isinstance(value, (str, Path)):
        raise DatasetError(f"source path must be a string: {value!r}")
    value = Path(value).expanduser()
    return (value if value.is_absolute() else base / value).resolve()


def _virial_policy(manifest: Mapping[str, Any]) -> dict[str, str]:
    raw = manifest.get("virial")
    if (
        not isinstance(raw, Mapping)
        or raw.get("source") != "result.stress_GPa"
        or raw.get("sign") != "source_stress_times_volume"
    ):
        raise DatasetError(
            "virial must use result.stress_GPa with source_stress_times_volume"
        )
    if raw.get("input_unit", "GPa") != "GPa" or raw.get("output_unit", "eV") != "eV":
        raise DatasetError("virial units must be GPa input and eV output")
    return {"source": "result.stress_GPa", "sign": "source_stress_times_volume"}


def _frame(
    source: Mapping[str, Any], manifest: Mapping[str, Any], policy: Mapping[str, str]
) -> dict[str, Any]:
    task_id = source["task_id"]
    result = json.loads(source["result_path"].read_text(encoding="utf-8"))
    method = json.loads(source["method_path"].read_text(encoding="utf-8"))
    task = json.loads(source["task_path"].read_text(encoding="utf-8"))
    atom_map = json.loads(source["atom_map_path"].read_text(encoding="utf-8"))
    if method.get("engine") != ABACUS_ENGINE:
        raise DatasetError(f"source {task_id} engine must be abacus")
    method_set = str(method.get("method_set", "")).strip()
    if not method_set or manifest.get("method_set") not in (None, method_set):
        raise DatasetError(f"source {task_id} method_set disagrees with manifest")
    for label, record in (("result", result), ("task", task)):
        if record.get("engine") not in (None, ABACUS_ENGINE):
            raise DatasetError(f"source {task_id} {label}.engine disagrees with abacus")
        if record.get("method_set") not in (None, method_set):
            raise DatasetError(f"source {task_id} {label}.method_set disagrees with method.json")
    if task.get("task_id") != task_id or result.get("task_id") not in (None, task_id):
        raise DatasetError(f"source {task_id} task/result task_id is not bound to the manifest")
    status = result.get("scientific_status") or task.get("scientific_status")
    if status not in CONVERGED_STATUSES or result.get("electronic_converged") is not True:
        raise DatasetError(f"source {task_id} is not accepted as converged")
    stage = str(result.get("stage") or method.get("stage") or "").strip()
    if stage not in {"scf", "relax"} or (
        stage == "relax" and result.get("ionic_converged") is not True
    ):
        raise DatasetError(f"source {task_id} native convergence/stage is not accepted")

    source_ids = [int(value) for value in atom_map["source_atom_ids"]]
    map_records = atom_map.get("abacus_order")
    if (
        not isinstance(map_records, Sequence)
        or len(map_records) != len(source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise DatasetError(f"source {task_id} atom map lacks a complete source order")
    abacus_indices = [int(item["abacus_index"]) for item in map_records]
    source_indices = [int(item["source_index"]) for item in map_records]
    if sorted(abacus_indices) != list(range(len(source_ids))) or sorted(source_indices) != list(range(len(source_ids))):
        raise DatasetError(f"source {task_id} atom map indices are not permutations")
    if any(source_ids[int(item["source_index"])] != int(item["atom_id"]) for item in map_records):
        raise DatasetError(f"source {task_id} atom map source_index/atom_id is inconsistent")

    model_atoms = ase_read(str(source["input_structure_path"]), index=0)
    final_atoms = ase_read(str(source["structure_path"]), index=0)
    if "atom_id" not in model_atoms.arrays or "atom_id" not in final_atoms.arrays:
        raise DatasetError(f"source {task_id} input/final structure lacks atom_id")
    model_ids = [int(value) for value in model_atoms.arrays["atom_id"]]
    final_ids = [int(value) for value in final_atoms.arrays["atom_id"]]
    if model_ids != source_ids or set(final_ids) != set(source_ids) or len(final_ids) != len(source_ids):
        raise DatasetError(f"source {task_id} atom IDs do not match STRU.atom-map.json")
    final_atoms = final_atoms[[final_ids.index(atom_id) for atom_id in source_ids]]

    from mlcc.abacus import parse_abacus_outputs
    from mlcc.modeling import ModelArtifacts

    native = parse_abacus_outputs(
        source["task_dir"],
        source_model=ModelArtifacts(
            model_id=str(method.get("model_id", task_id)),
            version=str(method.get("version", "unknown")),
            atoms=model_atoms,
            metadata={},
            artifact_dir=source["task_dir"],
        ),
        stage=stage,
        mapping_path=source["atom_map_path"],
    )
    if [int(value) for value in native.atom_ids] != source_ids:
        raise DatasetError(f"source {task_id} native atom IDs do not match source map")
    if (
        native.final_atoms.get_chemical_symbols() != final_atoms.get_chemical_symbols()
        or not np.allclose(native.final_atoms.cell.array, final_atoms.cell.array, rtol=0, atol=1e-8)
        or not np.allclose(native.final_atoms.positions, final_atoms.positions, rtol=0, atol=1e-8)
    ):
        raise DatasetError(f"source {task_id} native geometry differs from final.extxyz")
    if native.electronic_converged is not True or (
        stage == "relax" and native.ionic_converged is not True
    ):
        raise DatasetError(f"source {task_id} native convergence is not accepted")
    if (
        result.get("stress_unit") not in (None, "GPa")
        or result.get("stress_sign") != "abacus_printed"
        or [int(value) for value in result["atom_ids"]] != source_ids
    ):
        raise DatasetError(f"source {task_id} requires native ABACUS stress sign and atom IDs")
    stress = np.asarray(result["stress_GPa"], dtype=float)
    forces = np.asarray(result["forces_eV_per_A"], dtype=float)
    if (
        stress.shape != (3, 3)
        or forces.shape != (len(source_ids), 3)
        or not np.allclose(float(result["energy_eV"]), native.energy_eV, rtol=0, atol=1e-10)
        or not np.allclose(forces, native.forces_eV_per_A, rtol=0, atol=1e-10)
        or not np.allclose(stress, native.stress_GPa, rtol=0, atol=1e-10)
    ):
        raise DatasetError(f"source {task_id} result labels disagree with native ABACUS output")

    cell = np.asarray(final_atoms.cell.array, dtype=float)
    volume = abs(float(np.linalg.det(cell)))
    type_map = method.get("element_order")
    symbols = final_atoms.get_chemical_symbols()
    if (
        not isinstance(type_map, Sequence)
        or isinstance(type_map, (str, bytes))
        or set(type_map) != set(symbols)
        or len(set(type_map)) != len(type_map)
    ):
        raise DatasetError(f"source {task_id} method element_order does not match structure")
    effective = _method_signature(method, source["input_path"], source["kpoints_path"])
    model_id = str(method.get("model_id", task_id))
    model_version = str(method.get("version", "unknown"))
    paths = {
        "task_dir": str(source["task_dir"]),
        **{
            key: str(value)
            for key, value in source.items()
            if key.endswith("_path") and value is not None
        },
    }
    record = {
        "task_id": task_id,
        "label": source["label"],
        "split": source["split"],
        "source_group": source["source_group"],
        "engine": ABACUS_ENGINE,
        "method_set": method_set,
        "model_id": model_id,
        "model_version": model_version,
        "effective_method": effective,
        "type_map": [str(value) for value in type_map],
        "atom_ids": source_ids,
        "symbols": symbols,
        "cell_angstrom": cell.tolist(),
        "positions_angstrom": final_atoms.positions.tolist(),
        "stage": stage,
        "scientific_status": status,
        "energy_unit": "eV",
        "force_unit": "eV/angstrom",
        "stress_unit": "GPa",
        "stress_sign": "abacus_printed",
        "virial_source": policy["source"],
        "virial_sign": policy["sign"],
        "virial_unit": "eV",
        "task_provenance": {
            "task_id": task["task_id"],
            "scheduler_job_id": task.get("scheduler_job_id"),
            "status": task.get("status"),
            "runner": task.get("runner"),
        },
        "paths": paths,
        **paths,
    }
    return {
        "record": record,
        "task_id": task_id,
        "split": source["split"],
        "source_group": source["source_group"],
        "engine": ABACUS_ENGINE,
        "method_set": method_set,
        "model_id": model_id,
        "model_version": model_version,
        "effective_method": effective,
        "type_map": record["type_map"],
        "atom_ids": source_ids,
        "symbols": symbols,
        "cell": cell,
        "positions": final_atoms.positions,
        "energy": float(native.energy_eV),
        "forces": np.asarray(native.forces_eV_per_A, dtype=float),
        "virial": stress * volume / GPA_PER_EV_PER_A3,
        "stress_sign": "abacus_printed",
    }


def _method_signature(
    method: Mapping[str, Any], input_path: Path, kpoints_path: Path
) -> dict[str, Any]:
    excluded = {
        "stage",
        "case",
        "acceptance_record",
        "source_configuration",
        "fixture",
        "parent_method_set",
    }
    signature = {key: method[key] for key in method if key not in excluded}
    parameters = signature.get("parameters")
    if isinstance(parameters, Mapping):
        signature["parameters"] = {
            key: value
            for key, value in parameters.items()
            if key not in {"force_thr_eV_per_A", "relax_nmax", "cal_force", "cal_stress"}
        }
    signature["native_input"] = _native_input(input_path)
    signature["native_kpt"] = [
        line.strip() for line in kpoints_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return signature


def _native_input(path: Path) -> dict[str, str]:
    ignored = {
        "calculation",
        "relax_method",
        "relax_nmax",
        "force_thr_ev",
        "out_stru",
        "cal_force",
        "cal_stress",
    }
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("#", 1)[0].strip().split(None, 1)
        if len(fields) == 2 and fields[0] not in ignored and fields[0] != "INPUT_PARAMETERS":
            values[fields[0]] = fields[1].strip()
    return values


def _validate_collection(frames: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> None:
    first = frames[0]
    groups: dict[str, str] = {}
    for frame in frames:
        prior_split = groups.setdefault(frame["source_group"], frame["split"])
        if prior_split != frame["split"]:
            raise DatasetError(f"source_group {frame['source_group']!r} crosses train/validation splits")
        for field in (
            "engine",
            "method_set",
            "effective_method",
            "type_map",
            "atom_ids",
            "symbols",
            "stress_sign",
        ):
            if frame[field] != first[field]:
                raise DatasetError(f"mixed {field} values are not allowed")
    if manifest.get("engine") not in (None, ABACUS_ENGINE):
        raise DatasetError("source manifest engine disagrees with native data")
    if manifest.get("type_map") is not None and [str(value) for value in manifest["type_map"]] != first["type_map"]:
        raise DatasetError("source manifest type_map disagrees with native data")
