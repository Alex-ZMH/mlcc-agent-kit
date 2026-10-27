"""Collect source-bound ABACUS forces for the verified Phonopy plan.

This adapter is deliberately limited to native SCF force collection.  It
does not submit jobs, modify task directories, subtract residual forces, or
apply an acoustic sum rule.  The displacement manifest is validated by
``mlcc.phonons.load_phonon_displacement_plan`` and each force is reparsed from
the native ABACUS log with ``parse_abacus_outputs``.

The only accepted plan is ``mlcc.phonon-displacement-plan.v1``.  Displacement
tasks bind through ``task.json.phonon_displacement`` with the manifest's
``entry_id`` as ``displacement_id``.  A caller may additionally bind one
explicit P4 parent task as ``reference_task_record``; that task deliberately
has no displacement identity or child lineage.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from ase import Atoms
from ase.io import read

from .abacus import parse_abacus_outputs
from .elastic import _atom_mapping_valid, _load_bundle, _native_input_compatibility
from .modeling import read_model_artifacts
from .phonons import PLAN_SCHEMA, load_phonon_displacement_plan
from .strain import _method_physics, _native_physics


COLLECTION_SCHEMA = "mlcc.phonon-force-collection.v001"
FORCE_UNIT = "eV/angstrom"
_THRESHOLD_NAMES = (
    "force_match_tolerance_eV_per_A",
    "reference_force_tolerance_eV_per_A",
    "force_drift_tolerance_eV_per_A",
    "geometry_tolerance_A",
    "displacement_tolerance_A",
)
_PHONON_IDENTITY_FIELDS = (
    "plan_id",
    "plan_version",
    "manifest_path",
    "displacement_id",
    "entry_kind",
    "displaced_atom_id",
    "phonopy_atom_index",
    "displacement_angstrom",
    "displacement_unit",
    "sign",
    "parent_model_id",
    "parent_model_version",
    "parent_study_id",
    "parent_study_file",
)


def _task_directory(task_path: str | Path) -> Path:
    path = Path(task_path)
    if path.is_dir():
        return path.resolve()
    if path.name == "task.json":
        return path.parent.resolve()
    raise ValueError(f"phonon task path must be a task directory or task.json: {path}")


def _as_array(value: Any, *, name: str, shape: tuple[int, ...] | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if shape is not None and array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite values")
    return array


def _thresholds(thresholds: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(thresholds, Mapping):
        raise TypeError("thresholds must be a mapping with explicit limits")
    missing = [name for name in _THRESHOLD_NAMES if name not in thresholds]
    if missing:
        raise ValueError("thresholds missing required fields: " + ", ".join(missing))
    result: dict[str, float] = {}
    for name in _THRESHOLD_NAMES:
        value = thresholds[name]
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise TypeError(f"threshold {name} must be a finite positive number")
        number = float(value)
        if not np.isfinite(number) or number <= 0.0:
            raise ValueError(f"threshold {name} must be finite and positive")
        result[name] = number
    return result


def _method_physics_without_model(method: Mapping[str, Any]) -> dict[str, Any]:
    value = _method_physics(dict(method))
    value.pop("model_id", None)
    value.pop("stress_convention", None)
    value.update(
        {
            "lspinorb": bool(method["lspinorb"]),
            "noncolin": bool(method["noncolin"]),
            "occupations": method["occupations"],
            "mixing_type": method["mixing_type"],
            "relax_method": method["relax_method"],
            "symmetry": method["symmetry"],
            "pseudopotential_ids": method.get("pseudopotential_ids"),
            "pseudopotential_treatment": method.get("pseudopotential_treatment"),
            "net_charge": method.get("net_charge"),
        }
    )
    # LCAO numerical orbitals are part of the common physical/input method
    # identity.  Keeping the formal records here makes a cross-point
    # comparison reject a displacement that silently uses a different NAO
    # library or header snapshot.  PW methods retain their historical
    # identity without these fields.
    if method.get("basis_type") == "lcao":
        value.update(
            {
                "basis_type": "lcao",
                "numerical_orbital_ids": copy.deepcopy(method.get("numerical_orbital_ids")),
                "numerical_orbitals": copy.deepcopy(method.get("numerical_orbitals")),
                "orbital_header_snapshot": method.get("orbital_header_snapshot"),
            }
        )
    return value


def _read_json_object(path: str | Path) -> dict[str, Any]:
    """Read one required JSON object without hiding malformed source errors."""

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON source must be an object: {path}")
    return value


def _absolute_path(value: Any) -> Path | None:
    """Return one explicitly absolute path, or ``None`` for an invalid value."""

    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        return None
    return path.resolve()


def _phonon_entry_identity(
    entry: Mapping[str, Any],
    *,
    plan_id: str,
    plan_version: str,
    manifest_path: Path,
    parent_model: Mapping[str, Any],
    parent_study_id: Any,
    parent_study_file: Path | None,
) -> dict[str, Any]:
    """Build the exact task identity expected for one verified manifest entry."""

    reference = str(entry.get("entry_id")) == "reference"
    return {
        "plan_id": plan_id,
        "plan_version": plan_version,
        "manifest_path": str(manifest_path),
        "displacement_id": entry.get("entry_id"),
        "entry_kind": "reference" if reference else entry.get("kind"),
        "displaced_atom_id": None if reference else entry.get("displaced_atom_id"),
        "phonopy_atom_index": None if reference else entry.get("phonopy_atom_index"),
        "displacement_angstrom": None if reference else entry.get("displacement_angstrom"),
        "displacement_unit": None if reference else "angstrom",
        "sign": None if reference else entry.get("sign"),
        "parent_model_id": parent_model.get("model_id"),
        "parent_model_version": parent_model.get("version"),
        "parent_study_id": parent_study_id,
        "parent_study_file": None if parent_study_file is None else str(parent_study_file),
    }


def _native_stru_contract(path: str | Path, method: Mapping[str, Any]) -> dict[str, Any]:
    """Read STRU species filenames and block initial moments for exact comparison."""

    lines = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    try:
        species_start = lines.index("ATOMIC_SPECIES") + 1
        lattice_start = lines.index("LATTICE_CONSTANT", species_start)
        numerical_orbital_start = (
            lines.index("NUMERICAL_ORBITAL", species_start)
            if "NUMERICAL_ORBITAL" in lines[species_start:lattice_start]
            else lattice_start
        )
        species_end = min(lattice_start, numerical_orbital_start)
        positions_start = lines.index("ATOMIC_POSITIONS")
    except ValueError as exc:
        raise ValueError(f"native STRU lacks required sections: {path}") from exc

    species: dict[str, str] = {}
    for line in lines[species_start:species_end]:
        fields = line.split()
        if len(fields) < 3:
            raise ValueError(f"native STRU ATOMIC_SPECIES line is malformed: {line!r}")
        element, filename = fields[0], fields[2]
        if element in species:
            raise ValueError(f"native STRU repeats ATOMIC_SPECIES element: {element}")
        species[element] = filename

    moments: dict[str, float] = {}
    position_index = positions_start + 1
    if position_index >= len(lines):
        raise ValueError(f"native STRU ATOMIC_POSITIONS section is empty: {path}")
    if lines[position_index] in {"Direct", "Cartesian"}:
        position_index += 1
    while position_index < len(lines):
        element = lines[position_index].split()[0]
        if position_index + 2 >= len(lines):
            raise ValueError(f"native STRU ATOMIC_POSITIONS block is incomplete: {path}")
        try:
            moment = float(lines[position_index + 1].split()[0])
            count = int(lines[position_index + 2].split()[0])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"native STRU ATOMIC_POSITIONS block is malformed: {path}") from exc
        if element in moments:
            raise ValueError(f"native STRU repeats ATOMIC_POSITIONS element: {element}")
        moments[element] = moment
        position_index += 3 + count
    expected_moments = method.get("initial_moments_muB_by_element")
    expected_pseudopotentials = method.get("pseudopotentials")
    mismatches: list[dict[str, Any]] = []
    if not isinstance(expected_pseudopotentials, Mapping):
        mismatches.append({"kind": "method_pseudopotentials_missing"})
    else:
        expected_files: dict[str, Any] = {}
        for element, record in expected_pseudopotentials.items():
            if isinstance(record, Mapping):
                expected_files[str(element)] = record.get("filename")
            else:
                expected_files[str(element)] = None
        if species != expected_files:
            mismatches.append({"kind": "pseudopotential_filename", "native": species, "method": expected_files})
    if not isinstance(expected_moments, Mapping):
        mismatches.append({"kind": "method_initial_moments_missing"})
    else:
        expected_values = {str(element): float(value) for element, value in expected_moments.items()}
        if set(moments) != set(expected_values) or any(
            not np.isclose(moments[element], expected_values[element], rtol=0.0, atol=1.0e-10)
            for element in expected_values
            if element in moments
        ):
            mismatches.append({"kind": "initial_moments", "native": moments, "method": expected_values})
    return {
        "passed": not mismatches,
        "pseudopotentials": species,
        "initial_moments_muB_by_element": moments,
        "mismatches": mismatches,
    }


def _native_lcao_contract(path: str | Path, method: Mapping[str, Any]) -> dict[str, Any]:
    """Check a native LCAO STRU against the formal NAO method contract.

    The loader deliberately verifies the saved task contract and the saved
    header snapshot.  It does not re-read the remote orbital library or infer
    aliases from legacy report fields.
    """

    file_path = Path(path)
    lines = [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines()]
    mismatches: list[dict[str, Any]] = []
    try:
        orbital_index = next(index for index, value in enumerate(lines) if value == "NUMERICAL_ORBITAL")
        lattice_index = next(
            index for index, value in enumerate(lines[orbital_index + 1 :], orbital_index + 1)
            if value == "LATTICE_CONSTANT"
        )
    except StopIteration:
        mismatches.append({"kind": "numerical_orbital_section_missing", "path": str(file_path)})
        native_orbitals: list[str] = []
    else:
        native_orbitals = [
            value
            for value in lines[orbital_index + 1 : lattice_index]
            if value and not value.startswith("#")
        ]

    element_order = method.get("element_order")
    if not isinstance(element_order, list) or not element_order or any(
        not isinstance(element, str) or not element for element in element_order
    ):
        mismatches.append({"kind": "method_element_order_missing"})
        elements: list[str] = []
    else:
        elements = [str(element) for element in element_order]

    numerical_ids = method.get("numerical_orbital_ids")
    if not isinstance(numerical_ids, Mapping) or set(numerical_ids) != set(elements):
        mismatches.append(
            {
                "kind": "method_numerical_orbital_ids",
                "method": numerical_ids,
                "expected_elements": elements,
            }
        )
        numerical_ids_by_element: dict[str, Any] = {}
    else:
        numerical_ids_by_element = {element: numerical_ids[element] for element in elements}
        if any(not isinstance(value, str) or not value.strip() for value in numerical_ids_by_element.values()):
            mismatches.append({"kind": "method_numerical_orbital_ids_empty"})

    numerical_orbitals = method.get("numerical_orbitals")
    if not isinstance(numerical_orbitals, Mapping) or set(numerical_orbitals) != set(elements):
        mismatches.append(
            {
                "kind": "method_numerical_orbitals",
                "method": numerical_orbitals,
                "expected_elements": elements,
            }
        )
        orbital_records: dict[str, Mapping[str, Any]] = {}
    else:
        orbital_records = {}
        for element in elements:
            record = numerical_orbitals[element]
            if not isinstance(record, Mapping):
                mismatches.append({"kind": "method_numerical_orbital_record", "element": element})
                continue
            source = record.get("source")
            filename = record.get("filename")
            if not isinstance(source, str) or not source.strip() or not isinstance(filename, str) or not filename.strip():
                mismatches.append({"kind": "method_numerical_orbital_record", "element": element, "record": dict(record)})
            orbital_records[element] = record

    expected_orbitals = [
        orbital_records[element].get("filename")
        for element in elements
        if element in orbital_records
    ]
    if native_orbitals != expected_orbitals:
        mismatches.append(
            {
                "kind": "native_numerical_orbitals",
                "native": native_orbitals,
                "method": expected_orbitals,
            }
        )

    snapshot_value = method.get("orbital_header_snapshot")
    snapshot_path = _absolute_path(snapshot_value)
    snapshot: dict[str, Any] | None = None
    if snapshot_path is None or not snapshot_path.is_file():
        mismatches.append(
            {
                "kind": "orbital_header_snapshot_missing",
                "path": snapshot_value,
            }
        )
    else:
        try:
            snapshot = _read_json_object(snapshot_path)
        except (OSError, ValueError) as exc:
            mismatches.append(
                {
                    "kind": "orbital_header_snapshot_invalid",
                    "path": str(snapshot_path),
                    "error": str(exc),
                }
            )
        if snapshot is not None:
            if snapshot.get("schema") != "mlcc.nao-header-snapshot.v1":
                mismatches.append({"kind": "orbital_header_snapshot_schema", "actual": snapshot.get("schema")})
            if snapshot.get("method_set") != method.get("method_set"):
                mismatches.append(
                    {
                        "kind": "orbital_header_snapshot_method_set",
                        "actual": snapshot.get("method_set"),
                        "method": method.get("method_set"),
                    }
                )
            excerpts = snapshot.get("native_excerpts")
            if not isinstance(excerpts, Mapping) or set(excerpts) != set(elements):
                mismatches.append(
                    {
                        "kind": "orbital_header_snapshot_elements",
                        "actual": sorted(excerpts) if isinstance(excerpts, Mapping) else excerpts,
                        "method": elements,
                    }
                )
            else:
                for element in elements:
                    excerpt = excerpts[element]
                    record = orbital_records.get(element)
                    if not isinstance(excerpt, Mapping) or record is None:
                        mismatches.append({"kind": "orbital_header_snapshot_excerpt", "element": element})
                        continue
                    if excerpt.get("source_path") != record.get("source"):
                        mismatches.append(
                            {
                                "kind": "orbital_header_snapshot_source",
                                "element": element,
                                "actual": excerpt.get("source_path"),
                                "method": record.get("source"),
                            }
                        )
                    if excerpt.get("orbital_id") != numerical_ids_by_element.get(element):
                        mismatches.append(
                            {
                                "kind": "orbital_header_snapshot_id",
                                "element": element,
                                "actual": excerpt.get("orbital_id"),
                                "method": numerical_ids_by_element.get(element),
                            }
                        )

    return {
        "passed": not mismatches,
        "native_numerical_orbitals": native_orbitals,
        "method_numerical_orbitals": copy.deepcopy(numerical_orbitals),
        "method_numerical_orbital_ids": copy.deepcopy(numerical_ids),
        "orbital_header_snapshot": None if snapshot_path is None else str(snapshot_path),
        "mismatches": mismatches,
    }


def _child_lineage_issues(
    model_path: str | Path,
    metadata: Mapping[str, Any],
    entry: Mapping[str, Any],
    identity: Mapping[str, Any],
    parent_model: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Check child lineage files against the verified plan entry and metadata."""

    model_directory = Path(model_path)
    issues: list[dict[str, Any]] = []
    lineage_file = metadata.get("atom_lineage_file")
    if not isinstance(lineage_file, str) or not lineage_file:
        return [{"code": "child_lineage_file_missing", "message": "model.json atom_lineage_file is required"}]
    lineage_document = _read_json_object(model_directory / lineage_file)
    if lineage_document.get("model_id") != metadata.get("model_id") or lineage_document.get("version") != metadata.get("version"):
        issues.append({"code": "child_lineage_identity_mismatch", "message": "atom-lineage.json identity differs from model.json"})
    if lineage_document.get("parent_study_id") != identity.get("parent_study_id"):
        issues.append({"code": "child_lineage_parent_study_mismatch", "message": "atom-lineage.json parent_study_id differs from verified parent study"})
    lineage_parent = lineage_document.get("parent_model")
    if (
        not isinstance(lineage_parent, Mapping)
        or {
            "model_id": lineage_parent.get("model_id") if isinstance(lineage_parent, Mapping) else None,
            "version": lineage_parent.get("version") if isinstance(lineage_parent, Mapping) else None,
        }
        != {"model_id": parent_model.get("model_id"), "version": parent_model.get("version")}
        or _absolute_path(lineage_parent.get("path")) != _absolute_path(parent_model.get("path"))
    ):
        issues.append({"code": "child_lineage_parent_model_mismatch", "message": "atom-lineage.json parent model differs from verified source model"})
    lineage_plan = lineage_document.get("phonon_displacement")
    if not isinstance(lineage_plan, Mapping):
        issues.append({"code": "child_lineage_identity_missing", "message": "atom-lineage.json phonon_displacement is required"})
    else:
        mismatches = _identity_mismatches(identity, lineage_plan, base_path=model_directory)
        if mismatches:
            issues.append({"code": "child_lineage_identity_mismatch", "message": "atom-lineage.json phonon identity differs from verified identity", "mismatches": mismatches})
    entries = lineage_document.get("entries")
    metadata_entries = metadata.get("atom_lineage")
    if not isinstance(entries, list) or not isinstance(metadata_entries, list):
        issues.append({"code": "child_lineage_entries_missing", "message": "model.json and atom-lineage.json require atom lineage lists"})
        return issues
    if entries != metadata_entries:
        issues.append({"code": "child_lineage_metadata_mismatch", "message": "model.json atom_lineage differs from atom-lineage.json entries"})
    manifest_entries = entry.get("atom_lineage")
    if not isinstance(manifest_entries, list) or len(entries) != len(manifest_entries):
        issues.append({"code": "child_lineage_plan_mismatch", "message": "child lineage length differs from verified plan entry"})
        return issues
    reference = str(entry.get("entry_id")) == "reference"
    target_atom = None if reference else entry.get("displaced_atom_id")
    for actual, manifest_lineage in zip(entries, manifest_entries):
        if not isinstance(actual, Mapping) or not isinstance(manifest_lineage, Mapping):
            issues.append({"code": "child_lineage_entry_malformed", "message": "lineage entries must be objects"})
            continue
        base_actual = {key: value for key, value in actual.items() if key != "phonon_displacement"}
        if base_actual != dict(manifest_lineage):
            issues.append({"code": "child_lineage_plan_entry_mismatch", "message": "child lineage ancestry differs from verified plan entry", "child_atom_id": actual.get("child_atom_id")})
        annotation = actual.get("phonon_displacement")
        if not isinstance(annotation, Mapping):
            issues.append({"code": "child_lineage_annotation_missing", "message": "each child lineage entry requires phonon_displacement", "child_atom_id": actual.get("child_atom_id")})
            continue
        child_atom_id = actual.get("child_atom_id")
        target = target_atom is not None and child_atom_id == target_atom
        expected_annotation = {
            "entry_id": entry.get("entry_id"),
            "kind": "reference" if reference else entry.get("kind"),
            "displaced_atom_id": None if reference else entry.get("displaced_atom_id"),
            "phonopy_atom_index": None if reference else entry.get("phonopy_atom_index"),
            "vector_angstrom": None if reference else entry.get("displacement_angstrom"),
            "sign": None if reference else entry.get("sign"),
            "target": target,
            "applied_vector_angstrom": (
                [0.0, 0.0, 0.0] if not target else entry.get("displacement_angstrom")
            ),
        }
        for key, expected_value in expected_annotation.items():
            if annotation.get(key) != expected_value:
                issues.append({"code": "child_lineage_annotation_mismatch", "message": f"lineage annotation {key} differs from verified plan entry", "child_atom_id": child_atom_id, "field": key, "actual": annotation.get(key), "expected": expected_value})
    return issues


def _identity_mismatches(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    base_path: Path,
) -> list[dict[str, Any]]:
    """Compare complete phonon identity; only manifest paths may be relative."""

    mismatches: list[dict[str, Any]] = []
    for field in _PHONON_IDENTITY_FIELDS:
        if field not in actual:
            mismatches.append({"field": field, "expected": expected.get(field), "actual": None})
            continue
        value = actual[field]
        if field in {"manifest_path", "parent_study_file"}:
            if not isinstance(value, str) or not value.strip() or expected.get(field) is None:
                match = False
            else:
                actual_path = Path(value)
                if not actual_path.is_absolute() and field == "manifest_path":
                    actual_path = base_path / actual_path
                match = actual_path.is_absolute() and actual_path.resolve() == Path(str(expected[field])).resolve()
        else:
            match = value == expected.get(field)
        if not match:
            mismatches.append({"field": field, "expected": expected.get(field), "actual": value})
    return mismatches


def load_native_force_task(task_path: str | Path) -> dict[str, Any]:
    """Read one completed native ABACUS SCF force result without writing files."""

    directory = _task_directory(task_path)
    bundle = _load_bundle(directory)
    task = bundle["task"]
    method = bundle["method"]
    result = bundle["result"]
    if task["engine"] != "abacus" or task["engine_version"] != "3.10.1":
        raise ValueError(f"{directory}: task is not ABACUS 3.10.1")
    if (
        task["calculation"] != "scf"
        or method["stage"] != "scf"
        or method["engine"] != "abacus"
        or method["abacus_version_target"] != "3.10.1"
        or method.get("basis_type") not in {"pw", "lcao"}
    ):
        raise ValueError(f"{directory}: phonon force collection requires SCF")
    if task["scheduler_state"] != "COMPLETED" or task["exit_code"] != "0:0":
        raise ValueError(f"{directory}: native scheduler evidence is not COMPLETED/0:0")
    if task["status"] != "COMPLETED":
        raise ValueError(f"{directory}: task status is not COMPLETED")
    if (task["model_id"], task["model_version"]) != (method["model_id"], method["version"]):
        raise ValueError(f"{directory}: task and method model identity differ")
    if result.get("task_id") != task["task_id"] or result.get("method_set") != task["method_set"]:
        raise ValueError(f"{directory}: saved result identity differs from task")
    if method.get("method_set") != task["method_set"]:
        raise ValueError(f"{directory}: method_set differs between method.json and task.json")
    if result.get("scheduler_job_id") != task.get("scheduler_job_id"):
        raise ValueError(f"{directory}: saved result scheduler job differs from task")
    source_model = read_model_artifacts(task["model_path"])
    if (source_model.model_id, source_model.version) != (task["model_id"], task["model_version"]):
        raise ValueError(f"{directory}: recorded model path identity differs from task")
    source_model_atoms = source_model.atoms.copy()
    source_model_metadata = copy.deepcopy(source_model.metadata)
    atoms = bundle["atoms"]
    if "atom_id" not in atoms.arrays:
        raise ValueError(f"{directory}: input.extxyz has no atom_id")
    native_stru = bundle["native_stru"]
    final_atoms = bundle["final_atoms"]
    if native_stru is None:
        raise ValueError(f"{directory}: native STRU was not parsed")
    if final_atoms is None:
        raise ValueError(f"{directory}: final.extxyz is missing")
    model_for_parse = copy.copy(source_model)
    model_for_parse.atoms = atoms
    atom_map = bundle["atom_map"]
    if not _atom_mapping_valid(bundle):
        raise ValueError(f"{directory}: native atom mapping gate failed")
    kpt_matches_method = (
        bundle["kpt"]["grid"] == [int(value) for value in method["kpoints"]]
        and bundle["kpt"]["offset"] == [0, 0, 0]
    )
    native_input_mismatches: list[dict[str, Any]] = []
    if not _native_input_compatibility(bundle):
        native_input_mismatches.append({"key": "INPUT", "message": "elastic native input compatibility gate failed"})
    if bundle["input"].get("cal_force") != "1":
        native_input_mismatches.append({"key": "cal_force", "native": bundle["input"].get("cal_force"), "required": "1"})
    if bundle["input"].get("device") != str(method["device"]):
        native_input_mismatches.append({"key": "device", "native": bundle["input"].get("device"), "method": method["device"]})
    if not kpt_matches_method:
        native_input_mismatches.append({"key": "kpoints", "native": bundle["kpt"], "method": method["kpoints"]})
    native_stru_contract = _native_stru_contract(directory / "STRU", method)
    if not native_stru_contract["passed"]:
        native_input_mismatches.extend(native_stru_contract["mismatches"])
    native_lcao_contract = None
    if method.get("basis_type") == "lcao":
        native_lcao_contract = _native_lcao_contract(directory / "STRU", method)
        if not native_lcao_contract["passed"]:
            native_input_mismatches.extend(native_lcao_contract["mismatches"])
    native_input = {
        "passed": not native_input_mismatches,
        "native": bundle["input"],
        "kpt": bundle["kpt"],
        "kpt_matches_method": kpt_matches_method,
        "native_stru_pseudopotentials": native_stru_contract["pseudopotentials"],
        "native_stru_initial_moments_muB_by_element": native_stru_contract["initial_moments_muB_by_element"],
        "native_lcao_orbital_contract": native_lcao_contract,
        "mismatches": native_input_mismatches,
    }
    parsed = parse_abacus_outputs(directory, source_model=model_for_parse, stage="scf")
    native_forces = _as_array(parsed.forces_eV_per_A, name="native forces", shape=(len(atoms), 3))
    saved_forces = _as_array(result["forces_eV_per_A"], name="result forces", shape=native_forces.shape)
    atom_ids = [int(value) for value in atoms.arrays["atom_id"]]
    if parsed.atom_ids != atom_ids or [int(value) for value in result["atom_ids"]] != atom_ids:
        raise ValueError(f"{directory}: saved/native atom IDs differ from input")
    if result.get("electronic_converged") is not parsed.electronic_converged:
        raise ValueError(f"{directory}: saved/native electronic convergence differs")
    native_log = bundle["native_log"]
    return {
        "task_path": str(directory),
        "task": task,
        "method": method,
        "result": result,
        "source_model_path": str(source_model.artifact_dir.resolve()),
        "source_model_atoms": source_model_atoms,
        "source_model_metadata": source_model_metadata,
        "atoms": atoms,
        "atom_map": atom_map,
        "native_stru": native_stru,
        "final_atoms": final_atoms,
        "native_result": parsed.as_dict(),
        "source_files": parsed.source_files,
        "native_forces_eV_per_A": native_forces.tolist(),
        "result_forces_eV_per_A": saved_forces.tolist(),
        "native_electronic_converged": parsed.electronic_converged,
        "native_input": native_input,
        "method_physics": _method_physics_without_model(method),
        "native_physics": {**_native_physics(native_input["native"]), "kpt": native_input["kpt"]},
        "native_result_consistent": bundle["native_result_consistent"],
        "source_evidence": bundle["source_evidence"],
        "native_log": str(native_log.resolve()),
    }


def _force_drift(forces: Sequence[Sequence[float]]) -> dict[str, Any]:
    """Return raw total force drift; this function never changes ``forces``."""

    values = _as_array(forces, name="forces_eV_per_A")
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("forces_eV_per_A must be an N x 3 array")
    vector = values.sum(axis=0)
    return {
        "vector_eV_per_A": vector.tolist(),
        "norm_eV_per_A": float(np.linalg.norm(vector)),
        "max_component_abs_eV_per_A": float(np.max(np.abs(vector))),
    }


def _issue(code: str, message: str, *, task_id: str | None = None, **details: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    if task_id is not None:
        value["task_id"] = task_id
    value.update(details)
    return value


def _entry_atoms(manifest_path: Path, entry: Mapping[str, Any]) -> Atoms:
    return read(manifest_path.parent / str(entry["structure_file"]), index=0)


def _structure_match(expected: Atoms, candidate: Atoms, tolerance: float) -> dict[str, Any]:
    expected_ids = [int(value) for value in expected.arrays["atom_id"]]
    candidate_ids = [int(value) for value in candidate.arrays["atom_id"]]
    issues: list[dict[str, Any]] = []
    if expected_ids != candidate_ids:
        issues.append({"kind": "atom_ids", "expected": expected_ids, "actual": candidate_ids})
    if expected.get_chemical_symbols() != candidate.get_chemical_symbols():
        issues.append({"kind": "elements", "expected": expected.get_chemical_symbols(), "actual": candidate.get_chemical_symbols()})
    if expected.pbc.tolist() != candidate.pbc.tolist():
        issues.append({"kind": "pbc", "expected": expected.pbc.tolist(), "actual": candidate.pbc.tolist()})
    cell_delta = float(np.max(np.abs(expected.cell.array - candidate.cell.array)))
    if cell_delta > tolerance:
        issues.append({"kind": "cell", "max_delta_A": cell_delta, "tolerance_A": tolerance})
    if expected.get_positions().shape != candidate.get_positions().shape:
        issues.append({"kind": "positions", "expected_shape": expected.get_positions().shape, "actual_shape": candidate.get_positions().shape})
    else:
        position_delta = float(np.max(np.abs(expected.get_positions() - candidate.get_positions())))
        if position_delta > tolerance:
            issues.append({"kind": "positions", "max_delta_A": position_delta, "tolerance_A": tolerance})
    return {"passed": not issues, "issues": issues, "cell_max_abs_delta_A": cell_delta}


def _geometry_check(
    expected: Atoms,
    actual: Atoms,
    entry: Mapping[str, Any],
    reference: Atoms,
    geometry_tolerance: float,
    displacement_tolerance: float,
) -> dict[str, Any]:
    expected_ids = [int(value) for value in expected.arrays["atom_id"]]
    actual_ids = [int(value) for value in actual.arrays["atom_id"]]
    expected_symbols = expected.get_chemical_symbols()
    actual_symbols = actual.get_chemical_symbols()
    issues: list[dict[str, Any]] = []
    if expected_ids != actual_ids:
        issues.append({"kind": "atom_ids", "expected": expected_ids, "actual": actual_ids})
    if expected_symbols != actual_symbols:
        issues.append({"kind": "elements", "expected": expected_symbols, "actual": actual_symbols})
    cell_delta = float(np.max(np.abs(expected.cell.array - actual.cell.array)))
    if cell_delta > geometry_tolerance:
        issues.append({"kind": "cell", "max_delta_A": cell_delta, "tolerance_A": geometry_tolerance})
    position_delta = np.max(np.abs(expected.get_positions() - actual.get_positions()), axis=1)
    if float(np.max(position_delta)) > geometry_tolerance:
        issues.append({"kind": "positions", "max_delta_A": float(np.max(position_delta)), "tolerance_A": geometry_tolerance})
    reference_ids = [int(value) for value in reference.arrays["atom_id"]]
    if expected_ids != reference_ids or expected_symbols != reference.get_chemical_symbols():
        issues.append({"kind": "reference_mapping", "message": "manifest structures do not share reference atom IDs/elements"})
    if list(entry["atom_ids"]) != expected_ids:
        issues.append({"kind": "manifest_atom_ids", "manifest": entry["atom_ids"], "structure": expected_ids})
    if entry["entry_id"] != "reference":
        vector = _as_array(entry["displacement_angstrom"], name="manifest displacement_angstrom", shape=(3,))
        atom_id = int(entry["displaced_atom_id"])
        target_index = expected_ids.index(atom_id)
        expected_delta = expected.get_positions()[target_index] - reference.get_positions()[target_index]
        if float(np.max(np.abs(expected_delta - vector))) > displacement_tolerance:
            issues.append({"kind": "manifest_displacement", "expected_delta_A": expected_delta.tolist(), "manifest_delta_A": vector.tolist(), "tolerance_A": displacement_tolerance})
    return {"passed": not issues, "issues": issues, "cell_max_abs_delta_A": cell_delta}


def collect_phonon_forces(
    plan_path: str | Path,
    task_paths: Sequence[str | Path],
    thresholds: Mapping[str, Any],
    *,
    reference_task_record: str | Path | None = None,
) -> dict[str, Any]:
    """Collect one raw force record for every entry in a verified plan."""

    limits = _thresholds(thresholds)
    manifest_path = Path(plan_path).resolve()
    manifest = load_phonon_displacement_plan(manifest_path)
    if manifest.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"unsupported phonon displacement plan schema: {manifest.get('schema')!r}")
    reference_entry = manifest["reference"]
    entries = [reference_entry, *manifest["displacements"]]
    expected_ids = [str(entry["entry_id"]) for entry in entries]
    if len(set(expected_ids)) != len(expected_ids) or expected_ids[0] != "reference":
        raise ValueError("verified phonon plan entry IDs are not unique or reference-first")
    expected_structures = {str(entry["entry_id"]): _entry_atoms(manifest_path, entry) for entry in entries}
    parent_model = manifest["source_model"]
    parent_model_artifacts = read_model_artifacts(parent_model["path"])
    entries_by_id = {str(entry["entry_id"]): entry for entry in entries}
    issues: list[dict[str, Any]] = []
    loaded: list[dict[str, Any]] = []
    explicit_reference = reference_task_record is not None
    reference_item: dict[str, Any] | None = None
    if explicit_reference:
        # The explicit parent is loaded separately.  It is intentionally not
        # inserted into the displacement input list: P4 has no child
        # phonon_displacement identity and must never be made to look like a
        # P7 child.
        reference_item = load_native_force_task(reference_task_record)
    for task_path in task_paths:
        loaded.append(load_native_force_task(task_path))

    checks: dict[str, Any] = {
        "scheduler_completed_0": {"passed": True, "tasks": {}},
        "p7_stage": {"passed": True, "tasks": {}},
        "electronic_converged": {"passed": True, "tasks": {}},
        "expected_displacement_set": {"passed": True, "missing": [], "duplicates": [], "unknown": []},
        "atom_mapping": {"passed": True, "tasks": {}},
        "geometry": {"passed": True, "tasks": {}},
        "source_identity": {"passed": True, "tasks": {}},
        "child_model_binding": {"passed": True, "tasks": {}},
        "child_study_binding": {"passed": True, "tasks": {}},
        "parent_study_binding": {"passed": True, "tasks": {}},
        "case_binding": {"passed": True, "tasks": {}},
        "method_input_qualification": {"passed": True, "tasks": {}},
        "neutral_charge": {"passed": True, "tasks": {}},
        "same_method_physics": {"passed": True, "tasks": {}},
        "same_native_input_physics": {"passed": True, "tasks": {}},
        "native_input_contract": {"passed": True, "tasks": {}},
        "native_result_force_match": {"passed": True, "tasks": {}},
        "native_result_consistency": {"passed": True, "tasks": {}},
        "native_source_evidence": {"passed": True, "tasks": {}},
        "reference_binding": {"passed": True, "task": None},
    }
    by_id: dict[str, list[dict[str, Any]]] = {}
    raw_forces: dict[str, list[list[float]]] = {}
    force_drift: dict[str, dict[str, Any]] = {}
    reference_force: dict[str, Any] | None = None
    common_method: dict[str, Any] | None = None
    common_method_set: str | None = None
    common_native: dict[str, Any] | None = None
    common_parent_study: str | None = None
    common_parent_study_file: str | None = None
    common_case: dict[str, Any] | None = None
    reference_atoms = expected_structures["reference"]

    if explicit_reference and reference_item is not None:
        task = reference_item["task"]
        task_id = str(task["task_id"])
        reference_check: dict[str, Any] = {
            "passed": True,
            "issues": [],
            "task_path": str(Path(reference_item["task_path"]).resolve()),
            "stage": task.get("stage"),
        }

        def reference_issue(code: str, message: str, **details: Any) -> None:
            reference_check["passed"] = False
            reference_check["issues"].append({"code": code, "message": message, **details})

        if task.get("stage") != "P4":
            reference_issue("reference_stage", "explicit parent reference must be a P4 task", stage=task.get("stage"))
        if task.get("phonon_displacement") is not None:
            reference_issue(
                "reference_has_displacement_identity",
                "explicit parent reference must not carry phonon_displacement",
            )
        if task.get("model_id") != parent_model["model_id"] or task.get("model_version") != parent_model["version"]:
            reference_issue(
                "reference_model_identity",
                "explicit parent reference model differs from the plan source model",
                task_model={"model_id": task.get("model_id"), "version": task.get("model_version")},
                expected_model={"model_id": parent_model["model_id"], "version": parent_model["version"]},
            )
        if Path(str(reference_item["source_model_path"])).resolve() != Path(
            str(parent_model_artifacts.artifact_dir)
        ).resolve():
            reference_issue(
                "reference_source_model",
                "explicit parent reference source model path differs from the plan parent model",
                actual=reference_item["source_model_path"],
                expected=str(parent_model_artifacts.artifact_dir.resolve()),
            )

        reference_study_path = _absolute_path(task.get("study_file"))
        reference_study: dict[str, Any] | None = None
        if reference_study_path is None or not reference_study_path.is_file():
            reference_issue("reference_study_file", "explicit parent reference requires an existing study_file")
        else:
            reference_study = _read_json_object(reference_study_path)
            study_id = reference_study.get("study_id")
            if study_id != task.get("study_id"):
                reference_issue(
                    "reference_study_id",
                    "reference Study study_id differs from task",
                    study=study_id,
                    task=task.get("study_id"),
                )
            study_model = reference_study.get("model")
            if not isinstance(study_model, Mapping):
                reference_issue("reference_study_model", "reference Study requires a model object")
            else:
                expected_reference_model = {
                    "model_id": parent_model_artifacts.model_id,
                    "version": parent_model_artifacts.version,
                    "material": parent_model_artifacts.metadata.get("material"),
                    "phase_requested": parent_model_artifacts.metadata.get("phase_requested"),
                    "dopants": parent_model_artifacts.metadata.get("dopants", []),
                }
                for field, expected_value in expected_reference_model.items():
                    if study_model.get(field) != expected_value:
                        reference_issue(
                            "reference_study_model_mismatch",
                            f"reference Study model {field} differs from the plan parent model",
                            field=field,
                            study=study_model.get(field),
                            expected=expected_value,
                        )
                declared_model_path = _absolute_path(study_model.get("path", study_model.get("model_path")))
                if declared_model_path is not None and declared_model_path != Path(
                    str(parent_model_artifacts.artifact_dir)
                ).resolve():
                    reference_issue(
                        "reference_study_model_path",
                        "reference Study model path differs from the plan parent model",
                        study=str(declared_model_path),
                        expected=str(parent_model_artifacts.artifact_dir.resolve()),
                    )
            for field in ("case_id", "case_role"):
                if field not in task or field not in reference_study or task.get(field) != reference_study.get(field):
                    reference_issue(
                        "reference_case_binding",
                        f"reference Study and task must agree on {field}",
                        field=field,
                        task=task.get(field),
                        study=reference_study.get(field),
                    )
            task_fixture = task.get("fixture")
            if not isinstance(task_fixture, bool):
                reference_issue(
                    "reference_task_fixture_missing",
                    "explicit parent reference task.fixture must be an explicit boolean",
                    task=task_fixture,
                )
            elif "fixture" in reference_study:
                if not isinstance(reference_study.get("fixture"), bool) or reference_study.get("fixture") != task_fixture:
                    reference_issue(
                        "reference_case_binding",
                        "reference Study explicit fixture differs from task.fixture",
                        field="fixture",
                        task=task_fixture,
                        study=reference_study.get("fixture"),
                    )
            elif (reference_study.get("case_role") == "engineering_fixture") != task_fixture:
                reference_issue(
                    "reference_case_fixture_derived_mismatch",
                    "reference Study fixture omitted but case_role-derived fixture differs from task.fixture",
                    task=task_fixture,
                    case_role=reference_study.get("case_role"),
                )
            model_fixture = parent_model_artifacts.metadata.get("fixture")
            if not isinstance(model_fixture, bool):
                reference_issue(
                    "reference_model_fixture_missing",
                    "verified parent model fixture must be an explicit boolean",
                )
            elif isinstance(task_fixture, bool) and task_fixture != model_fixture:
                reference_issue(
                    "reference_task_model_fixture_mismatch",
                    "explicit parent reference task.fixture differs from the verified parent model",
                    task=task_fixture,
                    expected=model_fixture,
                )

        identity = task.get("phonon_displacement")
        checks["source_identity"]["tasks"][task_id] = {
            "passed": identity is None,
            "reference": True,
        }
        if identity is not None:
            checks["source_identity"]["passed"] = False
        if not isinstance(task.get("study_id"), str) or not task.get("study_id"):
            reference_issue("reference_study_id", "explicit parent reference requires a non-empty study_id")
        else:
            common_parent_study = str(task["study_id"])
        if reference_study_path is not None:
            common_parent_study_file = str(reference_study_path)

        reference_case_values = {
            field: task.get(field) for field in ("case_id", "case_role", "fixture")
        }
        common_case = copy.deepcopy(reference_case_values)
        checks["case_binding"]["tasks"][task_id] = {
            "passed": reference_check["passed"],
            "values": reference_case_values,
            "reference": True,
        }
        if not reference_check["passed"]:
            checks["case_binding"]["passed"] = False
            checks["parent_study_binding"]["passed"] = False
            issues.append(
                _issue(
                    "reference_binding_mismatch",
                    "explicit parent reference is not bound to the plan parent Model/Study",
                    task_id=task_id,
                    details=reference_check["issues"],
                )
            )
        # Keep parent identity/geometry binding separate from the ordinary
        # native/input and residual-force gates below.  In particular, an
        # unrelaxed reference may fail the declared residual threshold while
        # remaining the correctly bound P4 parent source.
        reference_binding_passed = bool(reference_check["passed"])
        checks["parent_study_binding"]["tasks"][task_id] = {
            "passed": reference_check["passed"],
            "reference": True,
            "study_file": None if reference_study_path is None else str(reference_study_path),
        }

        reference_method_qualification = reference_item["method"].get("input_qualification")
        fixture_value = task.get("fixture")
        if fixture_value is True:
            qualification_ok = True
            qualification_reason = "historical_engineering_fixture_input_qualification_not_required"
        elif fixture_value is False:
            qualification_ok = (
                task.get("method_input_qualified") is True
                and isinstance(reference_method_qualification, Mapping)
                and reference_method_qualification.get("input_qualified") is True
            )
            qualification_reason = "non_fixture_requires_task_and_method_input_qualification"
        else:
            qualification_ok = False
            qualification_reason = "task.fixture must be explicit"
        checks["method_input_qualification"]["tasks"][task_id] = {
            "passed": qualification_ok,
            "fixture": fixture_value,
            "reason": qualification_reason,
            "reference": True,
        }
        if not qualification_ok:
            checks["method_input_qualification"]["passed"] = False
            reference_issue("reference_method_input_not_qualified", "reference method input is not qualified")

        net_charge = reference_item["method"].get("net_charge")
        neutral_ok = (
            isinstance(net_charge, (int, float, np.integer, np.floating))
            and not isinstance(net_charge, bool)
            and float(net_charge) == 0.0
        )
        checks["neutral_charge"]["tasks"][task_id] = {
            "passed": neutral_ok,
            "net_charge": net_charge,
            "reference": True,
        }
        if not neutral_ok:
            checks["neutral_charge"]["passed"] = False
            reference_issue("reference_non_neutral", "phonon parent reference requires explicit net_charge == 0")

        scheduler_ok = task.get("scheduler_state") == "COMPLETED" and task.get("exit_code") == "0:0"
        electronic_ok = reference_item["native_electronic_converged"] is True
        checks["scheduler_completed_0"]["tasks"][task_id] = scheduler_ok
        checks["electronic_converged"]["tasks"][task_id] = electronic_ok
        if not scheduler_ok:
            checks["scheduler_completed_0"]["passed"] = False
            reference_issue("reference_scheduler_not_completed", "parent reference is not COMPLETED/0:0")
        if not electronic_ok:
            checks["electronic_converged"]["passed"] = False
            reference_issue("reference_electronic_not_converged", "parent reference SCF convergence marker is not true")

        reference_method = reference_item["method_physics"]
        reference_native = reference_item["native_physics"]
        checks["same_method_physics"]["tasks"][task_id] = reference_method
        checks["same_native_input_physics"]["tasks"][task_id] = reference_native
        common_method = copy.deepcopy(reference_method)
        common_method_set = str(task["method_set"])
        common_native = copy.deepcopy(reference_native)
        checks["native_input_contract"]["tasks"][task_id] = {
            "passed": bool(reference_item["native_input"]["passed"]),
            "mismatches": reference_item["native_input"]["mismatches"],
            "reference": True,
        }
        if not reference_item["native_input"]["passed"]:
            checks["native_input_contract"]["passed"] = False
            checks["same_native_input_physics"]["passed"] = False
            reference_issue("reference_native_input_contract", "parent reference native INPUT/KPT/STRU contract failed")
        checks["native_result_consistency"]["tasks"][task_id] = bool(reference_item["native_result_consistent"])
        if not reference_item["native_result_consistent"]:
            checks["native_result_consistency"]["passed"] = False
            reference_issue("reference_native_result_inconsistent", "parent reference native result is inconsistent")
        checks["native_source_evidence"]["tasks"][task_id] = reference_item["source_evidence"]
        if reference_item["source_evidence"].get("reason") != "complete":
            checks["native_source_evidence"]["passed"] = False
            reference_issue("reference_source_evidence", "parent reference source evidence is incomplete")

        reference_geometry = _geometry_check(
            reference_atoms,
            reference_item["atoms"],
            reference_entry,
            reference_atoms,
            limits["geometry_tolerance_A"],
            limits["displacement_tolerance_A"],
        )
        reference_geometry["parent_model"] = _structure_match(
            reference_atoms,
            reference_item["source_model_atoms"],
            limits["geometry_tolerance_A"],
        )
        reference_geometry["native_STRU"] = _structure_match(
            reference_atoms,
            reference_item["native_stru"],
            limits["geometry_tolerance_A"],
        )
        reference_geometry["final_extxyz"] = _structure_match(
            reference_atoms,
            reference_item["final_atoms"],
            limits["geometry_tolerance_A"],
        )
        reference_geometry["passed"] = bool(
            reference_geometry["passed"]
            and reference_geometry["parent_model"]["passed"]
            and reference_geometry["native_STRU"]["passed"]
            and reference_geometry["final_extxyz"]["passed"]
        )
        checks["geometry"]["tasks"][task_id] = reference_geometry
        if not reference_geometry["passed"]:
            checks["geometry"]["passed"] = False
            reference_issue("reference_geometry", "parent reference geometry differs from the plan reference")
        atom_ids = [int(value) for value in reference_item["atoms"].arrays["atom_id"]]
        atom_mapping_ok = atom_ids == [int(value) for value in reference_atoms.arrays["atom_id"]] and reference_item["atoms"].get_chemical_symbols() == reference_atoms.get_chemical_symbols()
        checks["atom_mapping"]["tasks"][task_id] = {
            "passed": atom_mapping_ok,
            "atom_ids": atom_ids,
            "elements": reference_item["atoms"].get_chemical_symbols(),
            "reference": True,
        }
        if not atom_mapping_ok:
            checks["atom_mapping"]["passed"] = False
            reference_issue("reference_atom_mapping", "parent reference atom IDs/elements differ from the plan")

        native_forces = _as_array(reference_item["native_forces_eV_per_A"], name=f"{task_id} native forces")
        saved_forces = _as_array(
            reference_item["result_forces_eV_per_A"],
            name=f"{task_id} result forces",
            shape=native_forces.shape,
        )
        delta = float(np.max(np.abs(native_forces - saved_forces)))
        force_match_ok = delta <= limits["force_match_tolerance_eV_per_A"]
        checks["native_result_force_match"]["tasks"][task_id] = {
            "passed": force_match_ok,
            "max_abs_delta_eV_per_A": delta,
            "reference": True,
        }
        if not force_match_ok:
            checks["native_result_force_match"]["passed"] = False
            reference_issue("reference_native_result_force_mismatch", "parent reference saved forces differ from native parser")
        by_id["reference"] = [reference_item]
        raw_forces["reference"] = reference_item["native_forces_eV_per_A"]
        force_drift["reference"] = _force_drift(reference_item["native_forces_eV_per_A"])
        max_atom_norm = float(np.max(np.linalg.norm(native_forces, axis=1)))
        reference_force = {
            "forces_eV_per_A": reference_item["native_forces_eV_per_A"],
            "max_atom_norm_eV_per_A": max_atom_norm,
            "passed": max_atom_norm <= limits["reference_force_tolerance_eV_per_A"],
        }
        if not reference_force["passed"]:
            reference_issue("reference_force_exceeds_threshold", "raw parent reference force exceeds threshold")
        reference_check["passed"] = bool(reference_check["passed"] and not reference_check["issues"])
        reference_check["binding_passed"] = reference_binding_passed
        checks["reference_binding"]["task"] = reference_check
        checks["reference_binding"]["passed"] = reference_binding_passed
        if not reference_binding_passed:
            issues.append(
                _issue(
                    "reference_binding_mismatch",
                    "explicit parent reference binding failed",
                    task_id=task_id,
                    details=reference_check["issues"],
                )
            )

    for item in loaded:
        task = item["task"]
        task_id = str(task["task_id"])
        identity = task.get("phonon_displacement")
        if not isinstance(identity, Mapping):
            checks["source_identity"]["passed"] = False
            issues.append(_issue("missing_displacement_identity", "task.phonon_displacement is required", task_id=task_id))
            continue
        displacement_value = identity.get("displacement_id")
        if not isinstance(displacement_value, str) or not displacement_value:
            checks["source_identity"]["passed"] = False
            issues.append(_issue("missing_displacement_identity", "task.phonon_displacement.displacement_id is required", task_id=task_id))
            continue
        displacement_id = displacement_value
        by_id.setdefault(displacement_id, []).append(item)
        entry = entries_by_id.get(displacement_id)
        parent_study_file = _absolute_path(identity.get("parent_study_file"))
        parent_study_document: dict[str, Any] | None = None
        parent_study_id_actual: Any = None
        parent_study_check: dict[str, Any] = {"passed": True, "issues": []}

        def parent_study_issue(code: str, message: str, **details: Any) -> None:
            parent_study_check["passed"] = False
            parent_study_check["issues"].append({"code": code, "message": message, **details})

        if parent_study_file is None:
            parent_study_issue("parent_study_file_invalid", "task identity requires an absolute parent_study_file")
            checks["source_identity"]["passed"] = False
            issues.append(_issue("missing_parent_study_file", "task phonon identity requires an absolute parent_study_file", task_id=task_id))
        else:
            parent_study_document = _read_json_object(parent_study_file)
            parent_study_id_actual = parent_study_document.get("study_id")
            if not isinstance(parent_study_id_actual, str) or not parent_study_id_actual:
                parent_study_issue("parent_study_id_missing", "parent study requires a non-empty study_id")
            if parent_study_document.get("study_id") != identity.get("parent_study_id"):
                parent_study_issue(
                    "parent_study_id_mismatch",
                    "parent study study_id differs from task identity",
                    study=parent_study_document.get("study_id"),
                    task=identity.get("parent_study_id"),
                )
            parent_study_model = parent_study_document.get("model")
            if not isinstance(parent_study_model, Mapping):
                parent_study_issue("parent_study_model_missing", "parent study requires a model object")
            else:
                expected_parent_fields = {
                    "model_id": parent_model_artifacts.model_id,
                    "version": parent_model_artifacts.version,
                    "material": parent_model_artifacts.metadata.get("material"),
                    "phase_requested": parent_model_artifacts.metadata.get("phase_requested"),
                    "dopants": parent_model_artifacts.metadata.get("dopants", []),
                }
                for field, expected_value in expected_parent_fields.items():
                    if parent_study_model.get(field) != expected_value:
                        parent_study_issue(
                            "parent_study_model_mismatch",
                            f"parent study model {field} differs from verified parent model",
                            field=field,
                            study=parent_study_model.get(field),
                            expected=expected_value,
                        )
            for field in ("case_id", "case_role"):
                value = parent_study_document.get(field)
                if not isinstance(value, str) or not value:
                    parent_study_issue("parent_study_case_field_missing", f"parent study requires {field}")
            model_fixture = parent_model_artifacts.metadata.get("fixture")
            if not isinstance(model_fixture, bool):
                parent_study_issue(
                    "parent_model_fixture_missing",
                    "verified parent model fixture must be an explicit boolean",
                )
                expected_fixture = False
            else:
                expected_fixture = model_fixture
            if (parent_study_document.get("case_role") == "engineering_fixture") != expected_fixture:
                parent_study_issue(
                    "parent_study_case_role_mismatch",
                    "parent study case_role differs from verified parent model fixture",
                    study=parent_study_document.get("case_role"),
                    expected_fixture=expected_fixture,
                )
            if "fixture" in parent_study_document and (
                not isinstance(parent_study_document.get("fixture"), bool)
                or parent_study_document.get("fixture") != expected_fixture
            ):
                parent_study_issue(
                    "parent_study_fixture_mismatch",
                    "parent study explicit fixture must be a boolean matching the verified parent model fixture",
                    study=parent_study_document.get("fixture"),
                    expected=expected_fixture,
                )
        checks["parent_study_binding"]["tasks"][task_id] = parent_study_check
        if not parent_study_check["passed"]:
            checks["parent_study_binding"]["passed"] = False
            issues.append(
                _issue(
                    "parent_study_binding_mismatch",
                    "parent study is not the verified source of the child study",
                    task_id=task_id,
                    details=parent_study_check["issues"],
                )
            )

        expected_identity = _phonon_entry_identity(
            entry if entry is not None else {"entry_id": displacement_id},
            plan_id=str(manifest["plan_id"]),
            plan_version=str(manifest["version"]),
            manifest_path=manifest_path,
            parent_model=parent_model,
            parent_study_id=parent_study_id_actual,
            parent_study_file=parent_study_file,
        )
        task_identity_mismatches = _identity_mismatches(
            expected_identity,
            identity,
            base_path=Path(item["task_path"]),
        )
        if task_identity_mismatches:
            checks["source_identity"]["passed"] = False
            issues.append(_issue("source_identity_mismatch", "task phonon identity differs from the verified plan", task_id=task_id, mismatches=task_identity_mismatches))
        parent_study_value = parent_study_id_actual
        if not isinstance(parent_study_value, str) or not parent_study_value:
            checks["source_identity"]["passed"] = False
            issues.append(_issue("missing_parent_study_identity", "verified parent study requires a non-empty study_id", task_id=task_id))
        parent_study = str(parent_study_value)
        if isinstance(parent_study_value, str) and common_parent_study is None:
            common_parent_study = parent_study
        elif isinstance(parent_study_value, str) and common_parent_study != parent_study:
            checks["source_identity"]["passed"] = False
            issues.append(_issue("parent_study_mismatch", "tasks do not share parent_study_id", task_id=task_id))
        parent_study_file_value = None if parent_study_file is None else str(parent_study_file)
        if parent_study_file_value is not None and common_parent_study_file is None:
            common_parent_study_file = parent_study_file_value
        elif parent_study_file_value is not None and common_parent_study_file != parent_study_file_value:
            checks["source_identity"]["passed"] = False
            issues.append(_issue("parent_study_file_mismatch", "tasks do not share parent_study_file", task_id=task_id))
        if task.get("input_transformation") is not None:
            checks["source_identity"]["passed"] = False
            issues.append(_issue("unexpected_input_transformation", "phonon tasks must use the manifest child structure", task_id=task_id))
        if displacement_id not in expected_structures:
            checks["expected_displacement_set"]["unknown"].append(displacement_id)
            issues.append(_issue("unknown_displacement", f"{displacement_id!r} is absent from the verified plan", task_id=task_id))
            continue
        expected_child_identity = dict(expected_identity)
        source_metadata = item["source_model_metadata"]
        child_model_check: dict[str, Any] = {"passed": True, "issues": []}

        def model_issue(code: str, message: str, **details: Any) -> None:
            child_model_check["passed"] = False
            child_model_check["issues"].append({"code": code, "message": message, **details})

        if source_metadata.get("model_id") != task.get("model_id"):
            model_issue("child_model_id_mismatch", "model.json model_id differs from task.json", model=source_metadata.get("model_id"), task=task.get("model_id"))
        if source_metadata.get("version") != task.get("model_version"):
            model_issue("child_model_version_mismatch", "model.json version differs from task.json", model=source_metadata.get("version"), task=task.get("model_version"))
        model_fixture = source_metadata.get("fixture")
        task_fixture = task.get("fixture")
        if not isinstance(model_fixture, bool):
            model_issue("child_model_fixture_missing", "model.json fixture must be an explicit boolean")
        elif not isinstance(task_fixture, bool) or model_fixture != task_fixture:
            model_issue(
                "child_model_fixture_mismatch",
                "model.json fixture differs from task.fixture",
                model=model_fixture,
                task=task_fixture,
            )
        for section in ("phonon_displacement", "derivation"):
            value = source_metadata.get(section)
            if not isinstance(value, Mapping):
                model_issue("child_model_identity_missing", f"model.json.{section} is required")
                continue
            mismatches = _identity_mismatches(
                expected_child_identity,
                value,
                base_path=Path(item["source_model_path"]),
            )
            if mismatches:
                model_issue("child_model_identity_mismatch", f"model.json.{section} differs from task identity", section=section, mismatches=mismatches)
        if source_metadata.get("study_id") != task.get("study_id"):
            model_issue("child_model_study_mismatch", "model.json study_id differs from task study_id", model=source_metadata.get("study_id"), task=task.get("study_id"))
        if source_metadata.get("study_binding") != task.get("study_id"):
            model_issue("child_model_study_binding_mismatch", "model.json study_binding differs from task study_id", model=source_metadata.get("study_binding"), task=task.get("study_id"))
        if source_metadata.get("parent_study_id") != identity.get("parent_study_id"):
            model_issue("child_model_parent_study_mismatch", "model.json parent_study_id differs from task identity", model=source_metadata.get("parent_study_id"), task=identity.get("parent_study_id"))
        expected_child_fields = {
            "material": parent_model_artifacts.metadata.get("material"),
            "phase_requested": parent_model_artifacts.metadata.get("phase_requested"),
            "spatial_mode": "phonon_displacement_child",
            "source_structure_role": "generated_child_reference",
            "dopants": parent_model_artifacts.metadata.get("dopants", []),
        }
        for field, expected_value in expected_child_fields.items():
            if source_metadata.get(field) != expected_value:
                model_issue(
                    "child_model_field_mismatch",
                    f"model.json {field} differs from the verified child contract",
                    field=field,
                    model=source_metadata.get(field),
                    expected=expected_value,
                )
        expected_parent = {
            "model_id": parent_model_artifacts.model_id,
            "version": parent_model_artifacts.version,
            "path": str(parent_model_artifacts.artifact_dir.resolve()),
        }
        parent_ref = source_metadata.get("parent_model")
        if not isinstance(parent_ref, Mapping):
            model_issue("child_model_parent_missing", "model.json parent_model reference is required")
        elif (
            {"model_id": parent_ref.get("model_id"), "version": parent_ref.get("version")}
            != {"model_id": expected_parent["model_id"], "version": expected_parent["version"]}
            or _absolute_path(parent_ref.get("path")) != Path(expected_parent["path"])
        ):
            model_issue("child_model_parent_mismatch", "model.json parent_model differs from verified source model", model=parent_ref, expected=expected_parent)
        parent_refs = source_metadata.get("parent_models")
        if not isinstance(parent_refs, list) or not parent_refs:
            model_issue("child_model_parent_list_missing", "model.json parent_models must contain the verified parent model")
        elif (
            not isinstance(parent_refs[0], Mapping)
            or {"model_id": parent_refs[0].get("model_id"), "version": parent_refs[0].get("version")}
            != {"model_id": expected_parent["model_id"], "version": expected_parent["version"]}
            or _absolute_path(parent_refs[0].get("path")) != Path(expected_parent["path"])
        ):
            model_issue("child_model_parent_list_mismatch", "model.json parent_models differs from verified source model", model=parent_refs, expected=expected_parent)
        lineage_issues = _child_lineage_issues(
            item["source_model_path"],
            source_metadata,
            entry,
            expected_child_identity,
            parent_model,
        )
        for lineage_issue in lineage_issues:
            child_model_check["passed"] = False
            child_model_check["issues"].append(lineage_issue)
        dopants_file = source_metadata.get("dopants_file")
        if not isinstance(dopants_file, str) or not dopants_file:
            model_issue("child_dopants_file_missing", "model.json dopants_file is required")
        else:
            dopants_document = _read_json_object(Path(item["source_model_path"]) / dopants_file)
            if dopants_document.get("model_id") != task.get("model_id") or dopants_document.get("version") != task.get("model_version"):
                model_issue("child_dopants_identity_mismatch", "dopants.json identity differs from task", dopants=dopants_document)
            if dopants_document.get("spatial_mode") != "phonon_displacement_child":
                model_issue("child_dopants_spatial_mode_mismatch", "dopants.json spatial_mode is not phonon_displacement_child", spatial_mode=dopants_document.get("spatial_mode"))
            if dopants_document.get("dopants") != parent_model_artifacts.metadata.get("dopants", []):
                model_issue("child_dopants_mismatch", "dopants.json differs from verified parent dopant selection", dopants=dopants_document.get("dopants"), expected=parent_model_artifacts.metadata.get("dopants", []))
            if dopants_document.get("parent_study_id") != expected_child_identity.get("parent_study_id"):
                model_issue("child_dopants_parent_study_mismatch", "dopants.json parent_study_id differs from verified parent study", parent_study_id=dopants_document.get("parent_study_id"), expected=expected_child_identity.get("parent_study_id"))
        checks["child_model_binding"]["tasks"][task_id] = child_model_check
        if not child_model_check["passed"]:
            checks["child_model_binding"]["passed"] = False
            issues.append(_issue("child_model_binding_mismatch", "child model metadata is not bound to task and verified parent", task_id=task_id, details=child_model_check["issues"]))

        study_path = Path(task["study_file"])
        study = _read_json_object(study_path)
        child_study_check: dict[str, Any] = {"passed": True, "issues": []}

        def study_issue(code: str, message: str, **details: Any) -> None:
            child_study_check["passed"] = False
            child_study_check["issues"].append({"code": code, "message": message, **details})

        if study.get("study_id") != task.get("study_id"):
            study_issue("child_study_id_mismatch", "study.json study_id differs from task study_id", study=study.get("study_id"), task=task.get("study_id"))
        study_model = study.get("model")
        if not isinstance(study_model, Mapping):
            study_issue("child_study_model_missing", "study.json model reference is required")
        else:
            if study_model.get("model_id") != task.get("model_id"):
                study_issue("child_study_model_id_mismatch", "study.json model_id differs from task", study=study_model.get("model_id"), task=task.get("model_id"))
            if study_model.get("version") != task.get("model_version"):
                study_issue("child_study_model_version_mismatch", "study.json model version differs from task", study=study_model.get("version"), task=task.get("model_version"))
            if parent_study_document is not None:
                parent_study_model = parent_study_document.get("model")
                for field in ("material", "phase_requested", "dopants"):
                    expected_value = parent_study_model.get(field) if isinstance(parent_study_model, Mapping) else None
                    if study_model.get(field) != expected_value:
                        study_issue(
                            "child_study_model_field_mismatch",
                            f"child study model {field} differs from verified parent study",
                            field=field,
                            study=study_model.get(field),
                            expected=expected_value,
                        )
                child_structure = _absolute_path(study_model.get("source_structure"))
                expected_structure = (Path(item["source_model_path"]) / "model.extxyz").resolve()
                if child_structure is None or child_structure != expected_structure:
                    study_issue(
                        "child_study_structure_mismatch",
                        "child study source_structure does not identify the task child model",
                        study=study_model.get("source_structure"),
                        expected=str(expected_structure),
                    )
                for field in ("case_id", "case_role"):
                    if field in parent_study_document and study.get(field) != parent_study_document.get(field):
                        study_issue(
                            "child_study_case_mismatch",
                            f"child study {field} differs from verified parent study",
                            field=field,
                            study=study.get(field),
                            expected=parent_study_document.get(field),
                        )
                if "fixture" in parent_study_document and "fixture" in study:
                    if not isinstance(study.get("fixture"), bool) or study.get("fixture") != parent_study_document.get("fixture"):
                        study_issue(
                            "child_study_case_mismatch",
                            "child study explicit fixture differs from the parent Study",
                            field="fixture",
                            study=study.get("fixture"),
                            expected=parent_study_document.get("fixture"),
                        )
            selected_required_tasks = study.get("selected_required_tasks")
            if not isinstance(selected_required_tasks, list) or task_id not in selected_required_tasks:
                study_issue(
                    "child_study_task_selection_missing",
                    "child study selected_required_tasks must contain this task",
                    task_id=task_id,
                    selected_required_tasks=selected_required_tasks,
                )
        if study.get("parent_study_id") != expected_child_identity.get("parent_study_id"):
            study_issue("child_study_parent_mismatch", "study.json parent_study_id differs from verified parent study", study=study.get("parent_study_id"), task=expected_child_identity.get("parent_study_id"))
        derived_from = study.get("derived_from")
        if not isinstance(derived_from, Mapping):
            study_issue("child_study_derivation_missing", "study.json derived_from reference is required")
        else:
            if derived_from.get("study_id") != expected_child_identity.get("parent_study_id"):
                study_issue("child_study_derived_parent_study_mismatch", "study.json derived_from.study_id differs from verified parent_study_id", study=derived_from.get("study_id"), task=expected_child_identity.get("parent_study_id"))
            if derived_from.get("model_id") != parent_model_artifacts.model_id or derived_from.get("model_version") != parent_model_artifacts.version:
                study_issue("child_study_derived_parent_model_mismatch", "study.json derived_from parent model differs from verified source model", study=derived_from, expected=expected_parent)
        study_identity = study.get("phonon_displacement")
        if not isinstance(study_identity, Mapping):
            study_issue("child_study_identity_missing", "study.json phonon_displacement is required")
        else:
            mismatches = _identity_mismatches(
                expected_child_identity,
                study_identity,
                base_path=study_path.parent,
            )
            if mismatches:
                study_issue("child_study_identity_mismatch", "study.json phonon identity differs from task identity", mismatches=mismatches)
        checks["child_study_binding"]["tasks"][task_id] = child_study_check
        if not child_study_check["passed"]:
            checks["child_study_binding"]["passed"] = False
            issues.append(_issue("child_study_binding_mismatch", "child study metadata is not bound to task and verified parent", task_id=task_id, details=child_study_check["issues"]))

        case_check: dict[str, Any] = {"passed": True, "values": {}, "issues": []}
        for field in ("case_id", "case_role"):
            if field not in task:
                case_check["passed"] = False
                case_check["issues"].append({"code": "task_case_field_missing", "field": field})
                continue
            value = task[field]
            case_check["values"][field] = value
            if field not in study:
                case_check["passed"] = False
                case_check["issues"].append({"code": "study_case_field_missing", "field": field})
            elif study[field] != value:
                case_check["passed"] = False
                case_check["issues"].append({"code": "study_case_field_mismatch", "field": field, "task": value, "study": study[field]})
        if "fixture" not in task or not isinstance(task.get("fixture"), bool):
            case_check["passed"] = False
            case_check["issues"].append({"code": "task_case_fixture_missing", "field": "fixture"})
        else:
            task_fixture = task["fixture"]
            case_check["values"]["fixture"] = task_fixture
            if "fixture" in study:
                if not isinstance(study.get("fixture"), bool) or study.get("fixture") != task_fixture:
                    case_check["passed"] = False
                    case_check["issues"].append({"code": "study_case_field_mismatch", "field": "fixture", "task": task_fixture, "study": study.get("fixture")})
            elif (study.get("case_role") == "engineering_fixture") != task_fixture:
                case_check["passed"] = False
                case_check["issues"].append({"code": "study_case_fixture_derived_mismatch", "field": "fixture", "task": task_fixture, "case_role": study.get("case_role")})
        if common_case is None and case_check["passed"]:
            common_case = copy.deepcopy(case_check["values"])
        elif common_case is not None and case_check["values"] != common_case:
            case_check["passed"] = False
            case_check["issues"].append({"code": "case_identity_mismatch", "expected": common_case, "actual": case_check["values"]})
        checks["case_binding"]["tasks"][task_id] = case_check
        if not case_check["passed"]:
            checks["case_binding"]["passed"] = False
            issues.append(_issue("case_binding_mismatch", "phonon child tasks do not share case identity", task_id=task_id, details=case_check["issues"]))

        stage_ok = task.get("stage") == "P7"
        checks["p7_stage"]["tasks"][task_id] = stage_ok
        if not stage_ok:
            checks["p7_stage"]["passed"] = False
            issues.append(_issue("wrong_task_stage", "phonon force collection requires task stage P7", task_id=task_id, stage=task.get("stage")))
        fixture_value = task.get("fixture")
        method_qualification = item["method"].get("input_qualification")
        if fixture_value is True:
            qualification_ok = True
            qualification_reason = "historical_engineering_fixture_input_qualification_not_required"
        elif fixture_value is False:
            qualification_ok = (
                task.get("method_input_qualified") is True
                and isinstance(method_qualification, Mapping)
                and method_qualification.get("input_qualified") is True
            )
            qualification_reason = "non_fixture_requires_task_and_method_input_qualification"
        else:
            qualification_ok = False
            qualification_reason = "task.fixture must be explicit"
        checks["method_input_qualification"]["tasks"][task_id] = {
            "passed": qualification_ok,
            "fixture": fixture_value,
            "reason": qualification_reason,
        }
        if not qualification_ok:
            checks["method_input_qualification"]["passed"] = False
            issues.append(_issue("method_input_not_qualified", "task/method input qualification is not sufficient for a non-fixture phonon task", task_id=task_id))
        net_charge = item["method"].get("net_charge")
        neutral_ok = isinstance(net_charge, (int, float, np.integer, np.floating)) and not isinstance(net_charge, bool) and float(net_charge) == 0.0
        checks["neutral_charge"]["tasks"][task_id] = {"passed": neutral_ok, "net_charge": net_charge}
        if not neutral_ok:
            checks["neutral_charge"]["passed"] = False
            issues.append(_issue("non_neutral_task", "phonon force collection requires explicit net_charge == 0", task_id=task_id, net_charge=net_charge))
        native_input_ok = bool(item["native_input"]["passed"])
        checks["native_input_contract"]["tasks"][task_id] = {
            "passed": native_input_ok,
            "mismatches": item["native_input"]["mismatches"],
        }
        if not native_input_ok:
            checks["native_input_contract"]["passed"] = False
            issues.append(_issue("native_input_contract_mismatch", "native INPUT/KPT/STRU differs from method.json", task_id=task_id, mismatches=item["native_input"]["mismatches"]))

        scheduler_ok = task["scheduler_state"] == "COMPLETED" and task["exit_code"] == "0:0"
        electronic_ok = item["native_electronic_converged"] is True
        checks["scheduler_completed_0"]["tasks"][task_id] = scheduler_ok
        checks["electronic_converged"]["tasks"][task_id] = electronic_ok
        if not scheduler_ok:
            checks["scheduler_completed_0"]["passed"] = False
            issues.append(_issue("scheduler_not_completed", "native task is not COMPLETED/0:0", task_id=task_id))
        if not electronic_ok:
            checks["electronic_converged"]["passed"] = False
            issues.append(_issue("electronic_not_converged", "native SCF convergence marker is not true", task_id=task_id))
        method_physics = item["method_physics"]
        native_physics = item["native_physics"]
        checks["same_method_physics"]["tasks"][task_id] = method_physics
        checks["same_native_input_physics"]["tasks"][task_id] = native_physics
        if common_method is None:
            common_method = copy.deepcopy(method_physics)
        elif method_physics != common_method:
            checks["same_method_physics"]["passed"] = False
            issues.append(_issue("method_physics_mismatch", "tasks do not share method physics", task_id=task_id))
        if common_method_set is None:
            common_method_set = str(task["method_set"])
        elif common_method_set != str(task["method_set"]):
            checks["source_identity"]["passed"] = False
            issues.append(_issue("method_set_mismatch", "tasks do not share method_set", task_id=task_id))
        if common_native is None:
            common_native = copy.deepcopy(native_physics)
        elif native_physics != common_native:
            checks["same_native_input_physics"]["passed"] = False
            issues.append(_issue("native_input_physics_mismatch", "tasks do not share native INPUT/KPT physics", task_id=task_id))
        if not item["native_input"]["passed"]:
            checks["same_native_input_physics"]["passed"] = False
            issues.append(_issue("native_input_mismatch", "native INPUT/KPT disagrees with method.json", task_id=task_id, mismatches=item["native_input"]["mismatches"]))
        checks["native_source_evidence"]["tasks"][task_id] = item["source_evidence"]
        if item["source_evidence"]["reason"] != "complete":
            checks["native_source_evidence"]["passed"] = False
        checks["native_result_consistency"]["tasks"][task_id] = bool(item["native_result_consistent"])
        if not item["native_result_consistent"]:
            checks["native_result_consistency"]["passed"] = False
            issues.append(_issue("native_result_inconsistent", "native energy/stress/electronic/result source evidence is inconsistent", task_id=task_id))
        expected_atoms = expected_structures[displacement_id]
        actual_atoms = item["atoms"]
        entry = next(entry for entry in entries if str(entry["entry_id"]) == displacement_id)
        geometry = _geometry_check(
            expected_atoms,
            actual_atoms,
            entry,
            reference_atoms,
            limits["geometry_tolerance_A"],
            limits["displacement_tolerance_A"],
        )
        geometry["child_model"] = _structure_match(
            expected_atoms,
            item["source_model_atoms"],
            limits["geometry_tolerance_A"],
        )
        geometry["native_STRU"] = _structure_match(expected_atoms, item["native_stru"], limits["geometry_tolerance_A"])
        geometry["final_extxyz"] = _structure_match(expected_atoms, item["final_atoms"], limits["geometry_tolerance_A"])
        geometry["passed"] = bool(
            geometry["passed"]
            and geometry["child_model"]["passed"]
            and geometry["native_STRU"]["passed"]
            and geometry["final_extxyz"]["passed"]
        )
        checks["geometry"]["tasks"][task_id] = geometry
        if not geometry["passed"]:
            checks["geometry"]["passed"] = False
            issues.append(_issue("geometry_mismatch", "task input structure differs from verified manifest structure", task_id=task_id, details=geometry["issues"]))
        atom_ids = [int(value) for value in actual_atoms.arrays["atom_id"]]
        atom_mapping_ok = atom_ids == [int(value) for value in expected_atoms.arrays["atom_id"]] and actual_atoms.get_chemical_symbols() == expected_atoms.get_chemical_symbols()
        checks["atom_mapping"]["tasks"][task_id] = {"passed": atom_mapping_ok, "atom_ids": atom_ids, "elements": actual_atoms.get_chemical_symbols()}
        if not atom_mapping_ok:
            checks["atom_mapping"]["passed"] = False
            issues.append(_issue("atom_mapping_mismatch", "task atom IDs/elements differ from manifest", task_id=task_id))
        native_forces = _as_array(item["native_forces_eV_per_A"], name=f"{task_id} native forces")
        saved_forces = _as_array(item["result_forces_eV_per_A"], name=f"{task_id} result forces", shape=native_forces.shape)
        delta = float(np.max(np.abs(native_forces - saved_forces)))
        force_match_ok = delta <= limits["force_match_tolerance_eV_per_A"]
        checks["native_result_force_match"]["tasks"][task_id] = {"passed": force_match_ok, "max_abs_delta_eV_per_A": delta}
        if not force_match_ok:
            checks["native_result_force_match"]["passed"] = False
            issues.append(_issue("native_result_force_mismatch", "saved result forces differ from native parser", task_id=task_id, max_abs_delta_eV_per_A=delta))
        if displacement_id not in raw_forces:
            raw_forces[displacement_id] = item["native_forces_eV_per_A"]
            force_drift[displacement_id] = _force_drift(item["native_forces_eV_per_A"])
            if displacement_id == "reference":
                max_atom_norm = float(np.max(np.linalg.norm(native_forces, axis=1)))
                reference_force = {
                    "forces_eV_per_A": item["native_forces_eV_per_A"],
                    "max_atom_norm_eV_per_A": max_atom_norm,
                    "passed": max_atom_norm <= limits["reference_force_tolerance_eV_per_A"],
                }

    missing = [identifier for identifier in expected_ids if identifier not in by_id]
    duplicates = [identifier for identifier in by_id if len(by_id[identifier]) > 1]
    checks["expected_displacement_set"]["missing"] = missing
    checks["expected_displacement_set"]["duplicates"] = duplicates
    if missing or duplicates or checks["expected_displacement_set"]["unknown"]:
        checks["expected_displacement_set"]["passed"] = False
        for identifier in missing:
            issues.append(_issue("missing_displacement", f"expected displacement {identifier!r} was not collected"))
        for identifier in duplicates:
            issues.append(_issue("duplicate_displacement", f"displacement {identifier!r} was collected more than once"))
    for identifier, drift in force_drift.items():
        drift["passed"] = drift["norm_eV_per_A"] <= limits["force_drift_tolerance_eV_per_A"]
        if not drift["passed"]:
            issues.append(_issue("force_drift_exceeds_threshold", f"raw total force drift exceeds threshold for {identifier!r}", displacement_id=identifier, drift=drift))
    if reference_force is None:
        issues.append(_issue("missing_reference_force", "the reference force task was not collected"))
    elif not reference_force["passed"]:
        issues.append(_issue("reference_force_exceeds_threshold", "raw reference residual force exceeds threshold", value=reference_force["max_atom_norm_eV_per_A"], threshold=limits["reference_force_tolerance_eV_per_A"]))
    checks["reference_force"] = reference_force or {"passed": False, "missing": True}
    checks["force_drift"] = {"passed": bool(force_drift) and all(value["passed"] for value in force_drift.values()), "tasks": force_drift}
    checks["native_source_evidence"]["passed"] = bool(
        checks["native_source_evidence"]["passed"]
        and all(value.get("paths_belong_to_task", False) for value in checks["native_source_evidence"]["tasks"].values())
    )
    assembled = not missing and not duplicates and not checks["expected_displacement_set"]["unknown"] and len(raw_forces) == len(expected_ids)
    ready = bool(
        assembled
        and checks["p7_stage"]["passed"]
        and checks["scheduler_completed_0"]["passed"]
        and checks["electronic_converged"]["passed"]
        and checks["atom_mapping"]["passed"]
        and checks["geometry"]["passed"]
        and checks["source_identity"]["passed"]
        and checks["child_model_binding"]["passed"]
        and checks["child_study_binding"]["passed"]
        and checks["parent_study_binding"]["passed"]
        and checks["case_binding"]["passed"]
        and checks["method_input_qualification"]["passed"]
        and checks["neutral_charge"]["passed"]
        and checks["same_method_physics"]["passed"]
        and checks["same_native_input_physics"]["passed"]
        and checks["native_input_contract"]["passed"]
        and checks["native_result_force_match"]["passed"]
        and checks["native_result_consistency"]["passed"]
        and checks["native_source_evidence"]["passed"]
        and checks["reference_binding"]["passed"]
        and checks["reference_force"]["passed"]
        and checks["force_drift"]["passed"]
    )
    force_bundle: dict[str, Any] | None = None
    if ready:
        force_bundle = {
            "unit": FORCE_UNIT,
            "source": "native_abacus_phonon_force_collection",
            "records": [
                {
                    "entry_id": identifier,
                    "source_ref": by_id[identifier][0]["native_log"],
                    "atom_ids": [int(value) for value in by_id[identifier][0]["atoms"].arrays["atom_id"]],
                    "forces": raw_forces[identifier],
                }
                for identifier in expected_ids[1:]
            ],
        }
    return {
        "schema": COLLECTION_SCHEMA,
        "plan_schema": PLAN_SCHEMA,
        "plan_path": str(manifest_path),
        "plan_id": manifest["plan_id"],
        "plan_version": manifest["version"],
        "parent_model_id": parent_model["model_id"],
        "parent_model_version": parent_model["version"],
        "parent_study_id": common_parent_study,
        "parent_study_file": common_parent_study_file,
        "reference_binding_mode": (
            "explicit_parent_reference" if explicit_reference else "p7_reference_identity"
        ),
        "reference_task_record": (
            str(Path(reference_item["task_path"]).resolve() / "task.json")
            if explicit_reference and reference_item is not None
            else None
        ),
        "force_unit": FORCE_UNIT,
        "force_set": "assembled_unqualified" if assembled else "incomplete",
        "status": "assembled_unqualified" if ready else "blocked_force_collection",
        "ready_for_harmonic": ready,
        "scientific_qualification": False,
        "production_qualification": False,
        "thresholds": limits,
        "expected_displacement_ids": expected_ids,
        "collected_displacement_ids": sorted(raw_forces),
        "native_task_records": [
            str(Path(item["task_path"]) / "task.json")
            for identifier in expected_ids
            for item in by_id.get(identifier, [])
        ],
        "raw_forces_eV_per_A": raw_forces,
        "reference_force": reference_force,
        "force_drift": force_drift,
        "force_bundle": force_bundle,
        "checks": checks,
        "issues": issues,
    }


__all__ = [
    "COLLECTION_SCHEMA",
    "FORCE_UNIT",
    "collect_phonon_forces",
    "load_native_force_task",
]
