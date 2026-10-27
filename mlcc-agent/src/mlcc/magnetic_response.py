"""Consume a saved native ABACUS collinear magnetic result."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from .abacus import _convergence_marker, _native_marker_text, _parse_total_magnetization
from .electronic import _parse_input


SCHEMA = "mlcc.abacus-magnetic.v001"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _equal(label: str, left: Any, right: Any) -> None:
    if left != right:
        raise ValueError(f"{label} mismatch: {left!r} != {right!r}")


def _finite(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _moment_map(value: Mapping[str, Any], label: str) -> dict[str, float]:
    return {str(key): _finite(item, f"{label}[{key!r}]") for key, item in value.items()}


def _initial_seed(method: Mapping[str, Any]) -> dict[str, Any] | None:
    seed: dict[str, Any] = {"source": "method.json", "unit": "muB"}
    if "initial_magnetic_moment_muB_per_atom" in method:
        seed["initial_magnetic_moment_muB_per_atom"] = _finite(
            method["initial_magnetic_moment_muB_per_atom"],
            "method.initial_magnetic_moment_muB_per_atom",
        )
    if "initial_moments_muB_by_element" in method:
        seed["initial_moments_muB_by_element"] = _moment_map(
            method["initial_moments_muB_by_element"], "method.initial_moments_muB_by_element"
        )
    if "initial_moments_muB_by_atom_id" in method:
        seed["initial_moments_muB_by_atom_id"] = _moment_map(
            method["initial_moments_muB_by_atom_id"], "method.initial_moments_muB_by_atom_id"
        )
    return seed if len(seed) > 2 else None


def _electronic_reference(path: Path, task: Mapping[str, Any], nspin: int) -> dict[str, Any]:
    electronic = _read_json(path)
    if electronic["schema"] != "mlcc.abacus-electronic.v001":
        raise ValueError("electronic product schema is unsupported")
    for field in ("task_id", "scheduler_job_id", "method_set", "model_id", "model_version"):
        _equal(f"electronic.{field}", electronic[field], task[field])
    _equal("electronic.nspin", electronic["nspin"], nspin)
    return {
        "path": str(path),
        "schema": electronic["schema"],
        "task_id": electronic["task_id"],
        "scheduler_job_id": electronic["scheduler_job_id"],
        "method_set": electronic["method_set"],
        "model_id": electronic["model_id"],
        "model_version": electronic["model_version"],
        "nspin": electronic["nspin"],
        "spin_channels": electronic.get("spin_channels"),
        "band_energies_eV": electronic.get("band_energies_eV"),
        "occupations": electronic.get("occupations"),
        "weighted_occupations": electronic.get("weighted_occupations"),
        "normalized_occupations": electronic.get("normalized_occupations"),
        "source_files": electronic.get("source_files"),
    }


def read_abacus_magnetic_task(
    task_path: str | Path, electronic_path: str | Path | None = None
) -> dict[str, Any]:
    """Read the saved native collinear magnetic observation for one task."""

    task_dir = Path(task_path).expanduser().resolve()
    task = _read_json(task_dir / "task.json")
    result = _read_json(task_dir / "result.json")
    method = _read_json(task_dir / "method.json")
    atom_map_path = task_dir / "STRU.atom-map.json"
    atom_map = _read_json(atom_map_path)
    input_parameters = _parse_input(task_dir / "INPUT")

    if task["engine"] != "abacus" or task["engine_version"] != "3.10.1":
        raise ValueError("magnetic task requires ABACUS 3.10.1")
    if method["engine"] != "abacus" or method["abacus_version_target"] != "3.10.1":
        raise ValueError("magnetic method requires ABACUS 3.10.1")
    _equal("result.task_id", result["task_id"], task["task_id"])
    _equal("result.method_set", result["method_set"], task["method_set"])
    _equal("result.scheduler_job_id", result["scheduler_job_id"], task["scheduler_job_id"])
    _equal("method.method_set", method["method_set"], task["method_set"])
    _equal("method.model_id", method["model_id"], task["model_id"])
    _equal("method.version", method["version"], task["model_version"])
    if "model_id" in result:
        _equal("result.model_id", result["model_id"], task["model_id"])
    if "model_version" in result:
        _equal("result.model_version", result["model_version"], task["model_version"])
    _equal("atom-map.model_id", atom_map["model_id"], task["model_id"])
    _equal("atom-map.version", atom_map["version"], task["model_version"])

    nspin = int(input_parameters["nspin"])
    if nspin not in (1, 2):
        raise ValueError("INPUT nspin must be 1 or 2")
    _equal("INPUT/method nspin", method["nspin"], nspin)
    if method.get("lspinorb") in (True, 1, "1") or method.get("noncolin") in (True, 1, "1"):
        raise ValueError("magnetic reader supports collinear non-SOC methods only")
    if input_parameters.get("lspinorb") == "1" or input_parameters.get("noncolin") == "1":
        raise ValueError("magnetic reader supports collinear non-SOC methods only")

    atom_ids = atom_map["source_atom_ids"]
    if not atom_ids or len(atom_ids) != len(set(atom_ids)):
        raise ValueError("STRU.atom-map.json source_atom_ids must be unique and non-empty")
    entries = sorted(atom_map["abacus_order"], key=lambda item: item["source_index"])
    _equal("atom-map source order", [entry["atom_id"] for entry in entries], atom_ids)
    if "atom_ids" in result:
        _equal("result.atom_ids", result["atom_ids"], atom_ids)

    stage = result["stage"].lower()
    if stage not in ("scf", "relax"):
        raise ValueError(f"unsupported ABACUS magnetic stage: {stage}")
    _equal("method.stage", method["stage"], stage)
    _equal("INPUT calculation", input_parameters["calculation"], stage)
    native_log = task_dir / f"OUT.{method['suffix']}" / f"running_{stage}.log"
    declared_log = Path(result["source_files"][f"running_{stage}.log"])
    if not declared_log.is_absolute():
        declared_log = task_dir / declared_log
    _equal("result.source_files native log", declared_log.resolve(), native_log.resolve())
    text = native_log.read_text(encoding="utf-8")

    native_electronic, native_ionic = _convergence_marker(text, stage=stage)
    native_completed = _native_marker_text(text)["finish"] is not None
    if result.get("electronic_converged") is not None:
        _equal("result.electronic_converged", result["electronic_converged"], native_electronic)
    if result.get("ionic_converged") is not None:
        _equal("result.ionic_converged", result["ionic_converged"], native_ionic)
    if result.get("native_completed") is not None:
        _equal("result.native_completed", result["native_completed"], native_completed)

    total = _parse_total_magnetization(text)
    if total is not None:
        total = _finite(total, "native total magnetization")
    if result.get("total_magnetization_muB") is not None:
        saved_total = _finite(result["total_magnetization_muB"], "result.total_magnetization_muB")
        if total is None:
            raise ValueError("result.total_magnetization_muB is missing from native log")
        if not math.isclose(total, saved_total, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("result.total_magnetization_muB differs from native log")
    mean = None if total is None else total / len(atom_ids)
    scheduler_complete = (
        task.get("status") == "COMPLETED"
        and task.get("scheduler_state") == "COMPLETED"
        and task.get("exit_code") == "0:0"
    )
    converged = (
        native_completed
        and native_electronic is True
        and (stage == "scf" or native_ionic is True)
    )
    status = "missing" if total is None else (
        "incomplete_task" if not scheduler_complete else (
            "available" if converged else "unconverged"
        )
    )

    source_files = {
        "task.json": str(task_dir / "task.json"),
        "result.json": str(task_dir / "result.json"),
        "method.json": str(task_dir / "method.json"),
        "INPUT": str(task_dir / "INPUT"),
        "STRU": str(task_dir / "STRU"),
        "STRU.atom-map.json": str(atom_map_path),
        f"running_{stage}.log": str(native_log),
    }
    resolved_electronic = None
    electronic = None
    if electronic_path is not None:
        resolved_electronic = Path(electronic_path).expanduser().resolve()
        electronic = _electronic_reference(resolved_electronic, task, nspin)

    return {
        "schema": SCHEMA,
        "task_id": task["task_id"],
        "model_id": task["model_id"],
        "model_version": task["model_version"],
        "method_set": task["method_set"],
        "scheduler_job_id": task["scheduler_job_id"],
        "task_path": str(task_dir),
        "electronic_path": None if resolved_electronic is None else str(resolved_electronic),
        "source_files": source_files,
        "scheduler_status": task.get("status"),
        "scheduler_state": task.get("scheduler_state"),
        "exit_code": task.get("exit_code"),
        "nspin": nspin,
        "atom_ids": atom_ids,
        "abacus_atom_order": atom_map["abacus_order"],
        "natoms": len(atom_ids),
        "native_electronic_converged": native_electronic,
        "native_ionic_converged": native_ionic,
        "native_completed": native_completed,
        "total_magnetization_muB": total,
        "mean_magnetization_muB_per_atom": mean,
        "magnetization_unit": "muB",
        "mean_magnetization_unit": "muB/atom",
        "status": status,
        "initial_seed": _initial_seed(method),
        "local_moments_muB": None,
        "magnetic_order": "unassessed",
        "electronic": electronic,
    }


__all__ = ["SCHEMA", "read_abacus_magnetic_task"]
