"""Direct consumers for Born columns and fixed-cell dielectric response.

The Berry response producer remains responsible for native calculations.  This
module only aggregates saved response records and evaluates the explicit
fixed-cell linear-response formula supplied by the caller.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.constants import elementary_charge, epsilon_0

from .berry import _read_kpt, _validate_model_and_stru
from .electronic import read_abacus_electronic_task
from .modeling import read_model_artifacts
from .polarization import _METHOD_KEYS


AGGREGATE_SCHEMA = "mlcc.born-charge-columns.v1"
IONIC_SCHEMA = "mlcc.ionic-dielectric-response.v1"
COMBINED_SCHEMA = "mlcc.dielectric-response.v1"
RESPONSE_SCHEMA = "mlcc.abacus-berry-displacement-response-results.v1"
PYATB_REQUEST_SCHEMA = "mlcc.pyatb-static-electronic-request.v1"
PYATB_ELECTRONIC_SCHEMA = "mlcc.pyatb-static-electronic.v1"
NATIVE_RAW_GAMMA_SCHEMA = "mlcc.czo-native-raw-gamma-force.v001"
GAMMA_HESSIAN_SCHEMA = "mlcc.gamma-force-constants.v1"
BORN_UNIT = "e"
FORCE_CONSTANT_UNIT = "eV/angstrom^2"
EPSILON_UNIT = "dimensionless"
_CELL_TOL = 1.0e-7
_NATIVE_ABACUS_VERSION = "3.10.1"


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _array(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != shape or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite array with shape {shape}")
    return result


def _non_empty_text_list(value: Any, name: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    result = [_text(item, f"{name}[{index}]") for index, item in enumerate(value)]
    return result


def _model_context(model_path: str | Path) -> dict[str, Any]:
    model = read_model_artifacts(model_path)
    cell = np.asarray(model.atoms.cell.array, dtype=float)
    volume = abs(float(np.linalg.det(cell)))
    if not math.isfinite(volume) or volume <= 0.0:
        raise ValueError("model cell volume must be positive")
    return {
        "model_id": model.model_id,
        "model_version": model.version,
        "model_path": str(model.artifact_dir.resolve()),
        "atom_ids": list(model.atom_ids),
        "cell_angstrom": cell.tolist(),
        "volume_A3": volume,
    }


def _response_context(response: Mapping[str, Any], model_context: Mapping[str, Any]) -> dict[str, Any]:
    parent = _mapping(response["parent"], "response.parent")
    model_id = _text(parent["model_id"], "response.parent.model_id")
    model_version = _text(parent["model_version"], "response.parent.model_version")
    if (model_id, model_version) != (model_context["model_id"], model_context["model_version"]):
        raise ValueError("Berry response parent model identity differs from model_path")
    response_model_path = Path(_text(parent["model_path"], "response.parent.model_path")).resolve()
    if response_model_path != Path(model_context["model_path"]):
        raise ValueError("Berry response parent model_path differs from model_path")
    study_id = _text(parent["study_id"], "response.parent.study_id")
    common_method = _mapping(response["common_method"], "response.common_method")
    return {
        "parent": {
            "study_id": study_id,
            "model_id": model_id,
            "model_version": model_version,
            "model_path": str(response_model_path),
        },
        "atom_ids": list(model_context["atom_ids"]),
        "cell_angstrom": copy.deepcopy(model_context["cell_angstrom"]),
        "volume_A3": model_context["volume_A3"],
        "common_method": copy.deepcopy(dict(common_method)),
    }


_P5_NUMERICAL_PARAMETERS = (
    "ecutwfc_Ry", "scf_thr", "scf_nmax", "nbands", "mixing_beta",
    "force_thr_eV_per_A", "relax_nmax",
)
_P5_NUMERICAL_TOP_LEVEL = ("pw_diag_thr", "kpoints", "kpoint_shift")


def p5_method_identity(method: Mapping[str, Any]) -> dict[str, Any]:
    """Physical identity for combining force and Berry response sources.

    Solver controls and discretization remain in each original method record.
    Their equality is neither necessary across SCF/NSCF roles nor evidence of
    target-property convergence. Unknown explicit fields remain in the identity.
    """
    identity = copy.deepcopy(dict(method))
    if method["engine"] != "abacus":
        return identity
    for key in (
        "abacus_version_target", "basis_type", "dft_functional", "nspin",
        "lspinorb", "noncolin", "occupations", "element_order",
        "initial_moments_muB_by_element", "pseudopotential_ids",
        "pseudopotential_metadata", "pseudopotential_treatment", "net_charge",
    ):
        if key not in method:
            raise ValueError(f"P5 physical method field is missing: {key}")
    parameters = dict(_mapping(method["parameters"], "method.parameters"))
    if "smearing_sigma_Ry" not in parameters:
        raise ValueError("P5 physical method field is missing: smearing_sigma_Ry")
    for key in _P5_NUMERICAL_PARAMETERS:
        parameters.pop(key, None)
    identity["parameters"] = parameters
    for key in ("method_set", *_P5_NUMERICAL_TOP_LEVEL):
        identity.pop(key, None)
    # A qualification label is an assessment of a PP, not its physical identity.
    for metadata in identity["pseudopotential_metadata"].values():
        metadata.pop("qualification", None)
    return identity


def p5_method_comparison(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """Keep both protocols and missing fields; never infer a solver default."""
    left_identity = p5_method_identity(left)
    right_identity = p5_method_identity(right)
    numerical = []
    for method in (left, right):
        if method["engine"] != "abacus":
            numerical.append({"record": {}, "missing_fields": []})
            continue
        parameters = method["parameters"]
        record = {key: copy.deepcopy(method[key]) for key in _P5_NUMERICAL_TOP_LEVEL if key in method}
        record["parameters"] = {key: copy.deepcopy(parameters[key]) for key in _P5_NUMERICAL_PARAMETERS if key in parameters}
        missing = [key for key in _P5_NUMERICAL_TOP_LEVEL if key not in method]
        missing += [f"parameters.{key}" for key in _P5_NUMERICAL_PARAMETERS if key not in parameters]
        numerical.append({"record": record, "missing_fields": missing})
    return {
        "same_physical_method": left_identity == right_identity,
        "physical_identities": [left_identity, right_identity],
        "original_methods": [copy.deepcopy(dict(left)), copy.deepcopy(dict(right))],
        "numerical_protocols": numerical,
        "numerical_protocols_equal": numerical[0] == numerical[1],
        "scientific_precision_qualified": False,
    }


def _context_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    for key in ("parent", "atom_ids"):
        if left[key] != right[key]:
            return False
    if p5_method_identity(left["common_method"]) != p5_method_identity(right["common_method"]):
        return False
    if not np.allclose(
        np.asarray(left["cell_angstrom"], dtype=float),
        np.asarray(right["cell_angstrom"], dtype=float),
        rtol=0.0,
        atol=_CELL_TOL,
    ):
        return False
    return math.isclose(float(left["volume_A3"]), float(right["volume_A3"]), rel_tol=0.0, abs_tol=_CELL_TOL)


def _direction_check(
    response: Mapping[str, Any],
    model_context: Mapping[str, Any],
) -> tuple[dict[int, Mapping[str, Any]], list[int], list[str]]:
    raw = response["directions"]
    if isinstance(raw, (str, bytes)) or not isinstance(raw, list):
        raise ValueError("response.directions must be a list")
    cell = np.asarray(model_context["cell_angstrom"], dtype=float)
    by_gdir: dict[int, Mapping[str, Any]] = {}
    unresolved: list[str] = []
    for index, item in enumerate(raw):
        direction = _mapping(item, f"response.directions[{index}]")
        gdir = direction["gdir"]
        if isinstance(gdir, bool) or not isinstance(gdir, int) or gdir not in (1, 2, 3):
            raise ValueError(f"response.directions[{index}].gdir must be 1, 2 or 3")
        if gdir in by_gdir:
            raise ValueError(f"response.directions repeats gdir={gdir}")
        vector = _array(direction["direction_lattice_vector_angstrom"], (3,), f"response direction gdir={gdir} lattice vector")
        unit = _array(direction["direction_unit_vector_cartesian"], (3,), f"response direction gdir={gdir} unit vector")
        expected = cell[gdir - 1]
        expected_unit = expected / np.linalg.norm(expected)
        if not np.allclose(vector, expected, rtol=0.0, atol=_CELL_TOL):
            raise ValueError(f"response gdir={gdir} lattice direction differs from model cell")
        if not np.allclose(unit, expected_unit, rtol=0.0, atol=_CELL_TOL):
            raise ValueError(f"response gdir={gdir} Cartesian direction differs from model cell")
        if direction["unit"] != "C/m^2/angstrom":
            raise ValueError(f"response gdir={gdir} derivative unit is unsupported")
        branch_resolved = direction["branch_resolved"]
        if not isinstance(branch_resolved, bool):
            raise ValueError(f"response gdir={gdir}.branch_resolved must be boolean")
        if branch_resolved:
            for side in ("minus", "plus"):
                point = _mapping(direction[side], f"response gdir={gdir}.{side}")
                branch_integer = point["branch_integer"]
                branch_basis = point["branch_basis"]
                if isinstance(branch_integer, bool) or not isinstance(branch_integer, int):
                    raise ValueError(f"response gdir={gdir}.{side}.branch_integer must be an integer")
                if not isinstance(branch_basis, str) or not branch_basis.strip():
                    raise ValueError(f"response gdir={gdir}.{side}.branch_basis must be non-empty")
        by_gdir[gdir] = direction
        if not branch_resolved:
            unresolved.append(f"gdir={gdir}:branch_unresolved")
    missing_gdirs = [gdir for gdir in (1, 2, 3) if gdir not in by_gdir]
    unresolved.extend(f"gdir={gdir}:missing" for gdir in missing_gdirs)
    return by_gdir, missing_gdirs, unresolved


def _task_ids(response: Mapping[str, Any]) -> list[str]:
    task_ids: list[str] = []
    for direction in response["directions"]:
        for side in ("minus", "plus"):
            point = _mapping(direction[side], f"response direction {side}")
            for key in ("task", "native_result", "scf_job"):
                value = point.get(key)
                if isinstance(value, Mapping) and value.get("task_id") is not None:
                    task_id = _text(value["task_id"], f"response {side}.{key}.task_id")
                    if task_id not in task_ids:
                        task_ids.append(task_id)
    return task_ids


def _validate_native_sources(response: Mapping[str, Any], response_path: Path) -> None:
    """Check native task/result provenance before consuming a saved response."""

    common_method = _mapping(response["common_method"], "response.common_method")
    method_set = _text(common_method["method_set"], "response.common_method.method_set")
    for direction in response["directions"]:
        for side in ("minus", "plus"):
            point = _mapping(direction[side], f"response {side}")
            task = _mapping(point["task"], f"response {side}.task")
            native = _mapping(point["native_result"], f"response {side}.native_result")
            scf = _mapping(point["scf_job"], f"response {side}.scf_job")
            task_id = _text(task["task_id"], f"response {side}.task.task_id")
            if native["task_id"] != task_id:
                raise ValueError(f"{response_path}: native result task_id differs from task")
            if task["scheduler_job_id"] != native["scheduler_job_id"]:
                raise ValueError(f"{response_path}: native result scheduler job differs from task")
            if task["method_set"] != method_set:
                raise ValueError(f"{response_path}: task method_set differs from common method")
            for record_name, record in (("native_result", native), ("scf_job", scf)):
                if (record["model_id"], record["model_version"]) != (task["model_id"], task["model_version"]):
                    raise ValueError(f"{response_path}: {record_name} model identity differs from task")
                if record["method_set"] != method_set:
                    raise ValueError(f"{response_path}: {record_name} method_set differs from common method")
            if native["reference_scf_task_id"] != scf["task_id"] or native["reference_task_id"] != scf["task_id"]:
                raise ValueError(f"{response_path}: native result SCF task identity differs")
            source = _mapping(point["source"], f"response {side}.source")
            task_file = Path(_text(source["task_file"], f"response {side}.source.task_file")).resolve()
            result_file = Path(_text(source["result_file"], f"response {side}.source.result_file")).resolve()
            if not task_file.is_file() or not result_file.is_file():
                raise FileNotFoundError(f"{response_path}: native source task/result file is missing")
            saved_task = _mapping(json.loads(task_file.read_text(encoding="utf-8")), "native task file")
            saved_result = _mapping(json.loads(result_file.read_text(encoding="utf-8")), "native result file")
            if (
                saved_task["task_id"] != task_id
                or (saved_task["model_id"], saved_task["model_version"]) != (task["model_id"], task["model_version"])
                or saved_task["method_set"] != method_set
                or saved_task["scheduler_job_id"] != task["scheduler_job_id"]
            ):
                raise ValueError(f"{response_path}: saved task file identity differs")
            if (
                saved_result["task_id"] != task_id
                or (saved_result["model_id"], saved_result["model_version"]) != (task["model_id"], task["model_version"])
                or saved_result["scheduler_job_id"] != native["scheduler_job_id"]
            ):
                raise ValueError(f"{response_path}: saved result file identity differs")
            if saved_result["method_set"] != method_set:
                raise ValueError(f"{response_path}: saved result method_set differs")


def _column_from_response(
    response: Mapping[str, Any],
    *,
    complete_directions: bool,
    unresolved: list[str],
) -> tuple[tuple[int, int], dict[str, Any] | None, str | None]:
    target = _mapping(response["target"], "response.target")
    atom_id = target["atom_id"]
    axis = target["cartesian_axis"]
    if isinstance(atom_id, bool) or not isinstance(atom_id, int):
        raise ValueError("response.target.atom_id must be an integer")
    if isinstance(axis, bool) or not isinstance(axis, int) or axis not in (0, 1, 2):
        raise ValueError("response.target.cartesian_axis must be 0, 1 or 2")
    key = (atom_id, axis)
    raw_column = response.get("born_charge_column")
    if not complete_directions:
        return key, None, ";".join(unresolved) or "response_incomplete"
    if raw_column is None:
        return key, None, "born_charge_column_missing"
    column = _mapping(raw_column, "response.born_charge_column")
    if column["atom_id"] != atom_id or column["cartesian_axis"] != axis:
        raise ValueError("response born_charge_column target differs from response.target")
    if column["unit"] != BORN_UNIT:
        raise ValueError("response born_charge_column unit must be e")
    if column["complete"] is not True:
        return key, None, "born_charge_column_incomplete"
    values = _array(column["values_e"], (3,), "response born_charge_column.values_e")
    return key, {
        "atom_id": atom_id,
        "cartesian_axis": axis,
        "axis_label": ("x", "y", "z")[axis],
        "values_e": values.tolist(),
        "unit": BORN_UNIT,
        "complete": True,
    }, None


def aggregate_born_columns(model_path: str | Path, response_paths: Sequence[str | Path]) -> dict[str, Any]:
    """Aggregate explicit Cartesian Born columns from saved Berry responses."""

    model_context = _model_context(model_path)
    paths = [response_paths] if isinstance(response_paths, (str, Path)) else list(response_paths)
    if not paths:
        raise ValueError("response_paths must be non-empty")
    context: dict[str, Any] | None = None
    common_method: Mapping[str, Any] | None = None
    column_values: dict[tuple[int, int], dict[str, Any]] = {}
    column_sources: dict[tuple[int, int], dict[str, list[str]]] = {}
    missing_reasons: dict[tuple[int, int], list[str]] = {}
    sources: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        response = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(response, Mapping) or response["schema"] != RESPONSE_SCHEMA:
            raise ValueError(f"Berry response schema is unsupported: {path}")
        _validate_native_sources(response, path)
        response_context = _response_context(response, model_context)
        if context is None:
            context = response_context
            common_method = response_context["common_method"]
        elif (not _context_equal(context, response_context)
              or context["common_method"] != response_context["common_method"]):
            # One finite-displacement Born series retains its declared common
            # numerical protocol. Cross-role P7/NSCF matching is separate.
            raise ValueError("Berry response context differs across response_paths")
        if not math.isclose(float(response["volume_A3"]), float(model_context["volume_A3"]), rel_tol=0.0, abs_tol=_CELL_TOL):
            raise ValueError("Berry response volume differs from model cell")
        directions, missing_gdirs, unresolved = _direction_check(response, model_context)
        complete_directions = not missing_gdirs and not unresolved
        key, column, reason = _column_from_response(
            response,
            complete_directions=complete_directions,
            unresolved=unresolved,
        )
        if key[0] not in model_context["atom_ids"]:
            raise ValueError("Berry response target atom_id is absent from model")
        response_path = str(path)
        task_ids = _task_ids(response)
        source_record = {
            "response_path": response_path,
            "response_id": _text(response["response_id"], "response.response_id"),
            "source_request": response.get("source_request"),
            "response_manifest": response.get("response_manifest"),
            "target": copy.deepcopy(dict(response["target"])),
            "directions": copy.deepcopy(response["directions"]),
            "source": [
                copy.deepcopy(direction[side].get("source"))
                for direction in response["directions"]
                for side in ("minus", "plus")
                if isinstance(direction.get(side), Mapping)
            ],
            "task_ids": task_ids,
            "missing_gdirs": missing_gdirs,
            "branch_unresolved": bool(unresolved),
        }
        sources.append(source_record)
        if key in column_sources:
            raise ValueError(f"duplicate Born column atom_id={key[0]} axis={key[1]}")
        column_sources[key] = {"response_paths": [response_path], "task_ids": task_ids}
        if column is not None:
            column_values[key] = column
        else:
            missing_reasons[key] = [reason or "column_missing"]

    assert context is not None
    atom_ids = list(context["atom_ids"])
    columns: list[dict[str, Any]] = []
    missing_columns: list[dict[str, Any]] = []
    for atom_id in atom_ids:
        for axis in (0, 1, 2):
            key = (atom_id, axis)
            if key in column_values:
                column = copy.deepcopy(column_values[key])
                provenance = column_sources[key]
                column.update(provenance)
                columns.append(column)
            else:
                reasons = missing_reasons.get(key, ["column_missing"])
                provenance = column_sources.get(key, {"response_paths": [], "task_ids": []})
                column = {
                    "atom_id": atom_id,
                    "cartesian_axis": axis,
                    "axis_label": ("x", "y", "z")[axis],
                    "values_e": None,
                    "unit": BORN_UNIT,
                    "complete": False,
                    **provenance,
                    "missing_reasons": reasons,
                }
                columns.append(column)
                missing_columns.append({
                    "atom_id": atom_id,
                    "cartesian_axis": axis,
                    "axis_label": ("x", "y", "z")[axis],
                    "reasons": reasons,
                })
    tensor = None
    if not missing_columns:
        tensor_array = np.empty((len(atom_ids), 3, 3), dtype=float)
        for atom_index, atom_id in enumerate(atom_ids):
            for axis in (0, 1, 2):
                tensor_array[atom_index, :, axis] = column_values[(atom_id, axis)]["values_e"]
        tensor = tensor_array.tolist()
    context["common_method"] = copy.deepcopy(dict(common_method or {}))
    return {
        "schema": AGGREGATE_SCHEMA,
        "context": context,
        "common_method": copy.deepcopy(dict(common_method or {})),
        "atom_ids": atom_ids,
        "unit": BORN_UNIT,
        "columns": columns,
        "full_born_tensors_e": tensor,
        "missing_columns": missing_columns,
        "sources": sources,
        "response_paths": [str(Path(path).resolve()) for path in paths],
        "qualification": {
            "complete": not missing_columns,
            "scientific_qualification": False,
            "numerical_qualification": False,
            "production_qualification": False,
        },
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }


def _born_matrix(born: Mapping[str, Any]) -> tuple[dict[str, Any], np.ndarray]:
    context = _mapping(born["context"], "born.context")
    _validate_context_geometry(context, "born.context")
    atom_ids = context["atom_ids"]
    if not isinstance(atom_ids, list) or len(atom_ids) == 0 or len(set(atom_ids)) != len(atom_ids):
        raise ValueError("born.context.atom_ids must be a non-empty unique list")
    tensors = born["full_born_tensors_e"]
    if tensors is None:
        raise ValueError("born.full_born_tensors_e is unresolved")
    array = _array(tensors, (len(atom_ids), 3, 3), "born.full_born_tensors_e")
    if born["unit"] != BORN_UNIT:
        raise ValueError("born.unit must be e")
    matrix = np.empty((3, 3 * len(atom_ids)), dtype=float)
    for index in range(len(atom_ids)):
        for axis in (0, 1, 2):
            matrix[:, 3 * index + axis] = array[index, :, axis]
    return dict(context), matrix


def _validate_context_pair(left: Mapping[str, Any], right: Mapping[str, Any], name: str) -> None:
    if not _context_equal(left, right):
        raise ValueError(f"{name} context differs from Born context")


def _validate_context_geometry(context: Mapping[str, Any], name: str) -> None:
    cell = _array(context["cell_angstrom"], (3, 3), f"{name}.cell_angstrom")
    volume = _finite_number(context["volume_A3"], f"{name}.volume_A3")
    determinant_volume = abs(float(np.linalg.det(cell)))
    if volume <= 0.0 or determinant_volume <= 0.0:
        raise ValueError(f"{name} cell volume must be positive")
    if not math.isclose(volume, determinant_volume, rel_tol=0.0, abs_tol=_CELL_TOL):
        raise ValueError(f"{name}.volume_A3 differs from the cell determinant")


def _validate_thresholds(thresholds: Mapping[str, Any]) -> None:
    for key in (
        "symmetry_eV_per_A2",
        "translation_eV_per_A2",
        "born_sum_e",
        "minimum_optical_eigenvalue_eV_per_A2",
    ):
        value = _finite_number(thresholds[key], f"thresholds.{key}")
        if value < 0.0:
            raise ValueError(f"thresholds.{key} must be non-negative")


def _gamma_inputs(gamma: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[np.ndarray, dict[str, float]]:
    if gamma["schema"] != "mlcc.gamma-force-constants.v1":
        raise ValueError("gamma_force_constants schema is unsupported")
    parent = _mapping(gamma["parent"], "gamma_force_constants.parent")
    gamma_context = {
        "parent": {
            "study_id": parent["study_id"],
            "model_id": parent["model_id"],
            "model_version": parent["model_version"],
            "model_path": str(Path(parent["model_path"]).resolve()),
        },
        "atom_ids": list(gamma["atom_ids"]),
        "cell_angstrom": copy.deepcopy(gamma["cell_angstrom"]),
        "volume_A3": _finite_number(gamma["volume_A3"], "gamma_force_constants.volume_A3"),
        "common_method": copy.deepcopy(dict(gamma["method_identity"])),
    }
    _validate_context_pair(context, gamma_context, "gamma_force_constants")
    _validate_context_geometry(gamma_context, "gamma_force_constants")
    if gamma["unit"] != FORCE_CONSTANT_UNIT:
        raise ValueError(f"gamma_force_constants.unit must be {FORCE_CONSTANT_UNIT}")
    if gamma["matrix_basis"] != "parent_atom_major_cartesian":
        raise ValueError("gamma_force_constants.matrix_basis must be parent_atom_major_cartesian")
    if gamma["electrical_boundary"] != "fixed_E_zero":
        raise ValueError("gamma_force_constants.electrical_boundary must be fixed_E_zero")
    if gamma["mechanical_boundary"] != "fixed_cell":
        raise ValueError("gamma_force_constants.mechanical_boundary must be fixed_cell")
    if gamma["nac"] != "not_applied":
        raise ValueError("gamma_force_constants.nac must be not_applied")
    source = _mapping(gamma["source"], "gamma_force_constants.source")
    source_refs: list[str] = []
    for key in ("harmonic_result", "plan_manifest", "force_bundle", "native_refs"):
        if key not in source:
            continue
        value = source[key]
        if isinstance(value, list):
            source_refs.extend(_non_empty_text_list(value, f"gamma_force_constants.source.{key}"))
        else:
            source_refs.append(_text(value, f"gamma_force_constants.source.{key}"))
    if not source_refs:
        raise ValueError("gamma_force_constants.source must contain non-empty source references")
    n = len(context["atom_ids"])
    matrix = _array(gamma["matrix_eV_per_A2"], (3 * n, 3 * n), "gamma_force_constants.matrix_eV_per_A2")
    gamma_thresholds = _mapping(gamma["thresholds"], "gamma_force_constants.thresholds")
    _validate_thresholds(gamma_thresholds)
    return matrix, {
        key: float(gamma_thresholds[key])
        for key in (
            "symmetry_eV_per_A2",
            "translation_eV_per_A2",
            "born_sum_e",
            "minimum_optical_eigenvalue_eV_per_A2",
        )
    }


def _qualification() -> dict[str, bool]:
    return {
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }


def calculate_ionic_dielectric(
    born: Mapping[str, Any],
    gamma_force_constants: Mapping[str, Any] | None,
    *,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Consume Gamma, retaining explicit-processing scope and sensitivity."""

    result = _calculate_ionic_dielectric(born, gamma_force_constants, thresholds=thresholds)
    if gamma_force_constants is not None and "explicit_processing" in gamma_force_constants:
        gamma = gamma_force_constants
        result["response_scope"] = copy.deepcopy(gamma["response_scope"])
        result["gamma_processing"] = {
            "request": gamma["source"][
                "native_saved_gamma_request" if "native_saved_gamma_request" in gamma["source"]
                else "native_gamma_processing_request"
            ],
            "operation": gamma["explicit_processing"]["operation"],
            "warnings": copy.deepcopy(gamma["explicit_processing"]["warnings"]),
        }
        if born["full_born_tensors_e"] is None:
            result["processing_sensitivity"] = {
                "schema": "mlcc.gamma-optical-response-sensitivity.v1",
                "status": "unresolved", "unresolved_reasons": ["born_tensor_incomplete"],
                "responses": {"raw": None, "symmetric": None, "projected": None},
            }
        else:
            from .gamma_processing import optical_response_sensitivity
            context, born_matrix = _born_matrix(born)
            result["processing_sensitivity"] = optical_response_sensitivity(
                born_matrix, gamma["explicit_processing"], context["volume_A3"],
            )
    return result


def _calculate_ionic_dielectric(
    born: Mapping[str, Any],
    gamma_force_constants: Mapping[str, Any] | None,
    *,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Calculate the fixed-cell Gamma ionic dielectric increment."""

    if born["schema"] != AGGREGATE_SCHEMA:
        raise ValueError("born schema is unsupported")
    if born["unit"] != BORN_UNIT:
        raise ValueError("born.unit must be e")
    context = dict(_mapping(born["context"], "born.context"))
    _validate_context_geometry(context, "born.context")
    threshold_mapping = _mapping(thresholds, "thresholds")
    _validate_thresholds(threshold_mapping)
    gamma_source = None
    gamma_method_comparison = None
    gamma_unresolved = False
    gamma_unresolved_reasons: list[str] = []
    if gamma_force_constants is not None:
        gamma = _mapping(gamma_force_constants, "gamma_force_constants")
        gamma_for_validation = dict(gamma)
        gamma_for_validation["thresholds"] = threshold_mapping
        force_matrix, tolerances = _gamma_inputs(gamma_for_validation, context)
        gamma_source = copy.deepcopy(dict(gamma["source"]))
        gamma_method_comparison = p5_method_comparison(context["common_method"], gamma["method_identity"])
        if gamma.get("status") == "unresolved":
            gamma_unresolved = True
            gamma_unresolved_reasons = copy.deepcopy(gamma["unresolved_reasons"])
    if born["full_born_tensors_e"] is None:
        unresolved_reasons = ["born_tensor_incomplete"]
        if gamma_force_constants is None:
            unresolved_reasons.append("gamma_force_constants_missing")
        elif gamma_unresolved:
            unresolved_reasons.extend(["gamma_force_constants_unresolved", *gamma_unresolved_reasons])
        return {
            "schema": IONIC_SCHEMA,
            "context": copy.deepcopy(context),
            "unit": EPSILON_UNIT,
            "electrical_boundary": "fixed_E_zero",
            "mechanical_boundary": "fixed_cell",
            "nac": "not_applied",
            "delta_epsilon_ionic": None,
            "status": "unresolved",
            "unresolved_reasons": unresolved_reasons,
            "thresholds": copy.deepcopy(dict(threshold_mapping)),
            "gamma_source": gamma_source,
            "gamma_method_comparison": gamma_method_comparison,
            "method_identity": copy.deepcopy(dict(context["common_method"])),
            "born_source": {
                "schema": born.get("schema"),
                "sources": copy.deepcopy(born.get("sources", [])),
            },
            **_qualification(),
            "qualification": _qualification(),
        }
    context, born_matrix = _born_matrix(born)
    if len(context["atom_ids"]) == 1:
        raise ValueError("one-atom ionic dielectric is outside the current optical-space scope")
    if gamma_force_constants is None:
        return {
            "schema": IONIC_SCHEMA,
            "context": copy.deepcopy(context),
            "unit": EPSILON_UNIT,
            "electrical_boundary": "fixed_E_zero",
            "mechanical_boundary": "fixed_cell",
            "nac": "not_applied",
            "delta_epsilon_ionic": None,
            "status": "unresolved",
            "unresolved_reasons": ["gamma_force_constants_missing"],
            "thresholds": copy.deepcopy(dict(threshold_mapping)),
            "gamma_source": None,
            "gamma_method_comparison": None,
            "method_identity": copy.deepcopy(dict(context["common_method"])),
            "born_source": {
                "schema": born.get("schema"),
                "sources": copy.deepcopy(born.get("sources", [])),
            },
            **_qualification(),
            "qualification": _qualification(),
        }
    if gamma_unresolved:
        return {
            "schema": IONIC_SCHEMA,
            "context": copy.deepcopy(context),
            "unit": EPSILON_UNIT,
            "electrical_boundary": "fixed_E_zero",
            "mechanical_boundary": "fixed_cell",
            "nac": "not_applied",
            "delta_epsilon_ionic": None,
            "status": "unresolved",
            "unresolved_reasons": ["gamma_force_constants_unresolved", *gamma_unresolved_reasons],
            "thresholds": copy.deepcopy(dict(threshold_mapping)),
            "gamma_source": copy.deepcopy(dict(gamma["source"])),
            "gamma_method_comparison": gamma_method_comparison,
            "method_identity": copy.deepcopy(dict(context["common_method"])),
            "born_source": {
                "schema": born.get("schema"),
                "sources": copy.deepcopy(born.get("sources", [])),
            },
            **_qualification(),
            "qualification": _qualification(),
        }
    atom_count = len(context["atom_ids"])
    translation = np.tile(np.eye(3), (atom_count, 1)) / math.sqrt(atom_count)
    symmetry_residual = float(np.max(np.abs(force_matrix - force_matrix.T)))
    translation_residual = float(np.max(np.abs(force_matrix @ translation)))
    born_sum = float(
        max(
            np.max(np.abs(np.sum(born_matrix[:, axis::3], axis=1)))
            for axis in (0, 1, 2)
        )
    )
    reasons: list[str] = []
    if symmetry_residual > tolerances["symmetry_eV_per_A2"]:
        reasons.append("matrix_symmetry_residual_exceeds_tolerance")
    if translation_residual > tolerances["translation_eV_per_A2"]:
        reasons.append("translation_residual_exceeds_tolerance")
    if born_sum > tolerances["born_sum_e"]:
        reasons.append("born_acoustic_sum_exceeds_tolerance")
    optical_minimum: float | None = None
    optical_eigenvalues: list[float] = []
    delta: list[list[float]] | None = None
    if not reasons:
        q_full, _ = np.linalg.qr(translation, mode="complete")
        optical = q_full[:, 3:]
        optical_hessian = optical.T @ force_matrix @ optical
        eigenvalues = np.linalg.eigvalsh(optical_hessian)
        optical_eigenvalues = eigenvalues.tolist()
        optical_minimum = float(np.min(eigenvalues))
        if optical_minimum <= tolerances["minimum_optical_eigenvalue_eV_per_A2"]:
            reasons.append("negative_or_near_zero_optical_mode")
        else:
            solved = np.linalg.solve(optical_hessian, optical.T @ born_matrix.T)
            scale = float(elementary_charge * 1.0e10 / (epsilon_0 * float(context["volume_A3"])))
            delta = (scale * born_matrix @ optical @ solved).tolist()
    checks = {
        "matrix_symmetry_residual_eV_per_A2": symmetry_residual,
        "translation_residual_eV_per_A2": translation_residual,
        "born_sum_residual_e": born_sum,
        "optical_eigenvalues_eV_per_A2": optical_eigenvalues,
        "minimum_optical_eigenvalue_eV_per_A2": optical_minimum,
        "thresholds": tolerances,
    }
    return {
        "schema": IONIC_SCHEMA,
        "context": copy.deepcopy(context),
        "unit": EPSILON_UNIT,
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "delta_epsilon_ionic": delta,
        "status": "complete" if delta is not None else "unresolved",
        "unresolved_reasons": reasons,
        "checks": checks,
        "constants": {
            "elementary_charge_C": float(elementary_charge),
            "epsilon_0_F_per_m": float(epsilon_0),
            "angstrom_to_m": 1.0e-10,
            "eV_to_J": float(elementary_charge),
            "source": "scipy.constants (CODATA exact elementary charge and epsilon_0)",
        },
        "gamma_source": copy.deepcopy(dict(gamma["source"])),
        "gamma_method_comparison": gamma_method_comparison,
        "thresholds": copy.deepcopy(dict(threshold_mapping)),
        "method_identity": copy.deepcopy(dict(context["common_method"])),
        "born_source": {
            "schema": born.get("schema"),
            "sources": copy.deepcopy(born.get("sources", [])),
        },
        **_qualification(),
        "qualification": _qualification(),
    }


def _read_json_object(path: Path, name: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _resolve_within(path_value: Any, directory: Path, name: str) -> Path:
    raw = Path(_text(path_value, name)).expanduser()
    path = raw.resolve() if raw.is_absolute() else (directory / raw).resolve()
    try:
        path.relative_to(directory.resolve())
    except ValueError as error:
        raise ValueError(f"{name} must be within {directory}") from error
    return path


def _native_job(
    *,
    role: str,
    task: Mapping[str, Any],
    task_file: Path,
    engine: str,
    engine_version: str,
) -> dict[str, Any]:
    return {
        "role": role,
        "task_id": _text(task["task_id"], f"{role}.task_id"),
        "scheduler_job_id": _text(task["scheduler_job_id"], f"{role}.scheduler_job_id"),
        "scheduler_state": _text(task["scheduler_state"], f"{role}.scheduler_state"),
        "exit_code": _text(task["exit_code"], f"{role}.exit_code"),
        "engine": engine,
        "engine_version": engine_version,
        "task_file": str(task_file.resolve()),
    }


def _native_method_identity(method: Mapping[str, Any], task_root: Path) -> dict[str, Any]:
    """Normalize saved LCAO method layouts using the task's actual KPT.

    Historical records declare orbital_files/orbital_metadata directly; the
    public creator declares numerical_orbitals and native header evidence.
    Both map to the existing consumer identity without rewriting either
    source. Numerical controls, including mixing_beta, stay in parameters.
    """

    identity = {}
    for key in _METHOD_KEYS:
        if key not in method:
            raise KeyError(key)
        identity[key] = copy.deepcopy(method[key])
    identity["method_set"] = method["method_set"]
    mesh, shift = _read_kpt(task_root / "KPT")
    if list(mesh) != method["kpoints"]:
        raise ValueError("native KPT mesh differs from the LCAO method")
    if "kpoint_shift" in method and list(shift) != list(method["kpoint_shift"]):
        raise ValueError("native KPT shift differs from the declared LCAO method")
    identity["kpoint_shift"] = list(shift)
    if "orbital_files" in method:
        identity["orbital_files"] = copy.deepcopy(method["orbital_files"])
        identity["orbital_metadata"] = copy.deepcopy(method["orbital_metadata"])
    else:
        identity["orbital_files"] = {
            element: record["source"] for element, record in method["numerical_orbitals"].items()
        }
        identity["orbital_metadata"] = copy.deepcopy(method["orbital_input_qualification"]["orbital_headers"])
    return identity


def _native_gamma_absolute_path(value: Any, name: str) -> Path:
    path = value.expanduser() if isinstance(value, Path) else Path(_text(value, name)).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    return path.resolve()


def _native_gamma_task_file(value: Any, name: str) -> Path:
    path = _native_gamma_absolute_path(value, name)
    if path.is_dir():
        path = (path / "task.json").resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _native_gamma_completed(task: Mapping[str, Any], role: str) -> None:
    if task.get("runner") != "slurm":
        raise ValueError(f"{role} runner must be slurm")
    if str(task.get("scheduler_state", "")).upper() != "COMPLETED":
        raise ValueError(f"{role} scheduler state is not COMPLETED")
    if task.get("exit_code") != "0:0":
        raise ValueError(f"{role} exit code is not 0:0")
    if task.get("status") is not None and str(task["status"]).upper() != "COMPLETED":
        raise ValueError(f"{role} status is not COMPLETED")
    _text(task.get("task_id"), f"{role}.task_id")
    _text(task.get("scheduler_job_id"), f"{role}.scheduler_job_id")


def _native_gamma_model_context(
    task: Mapping[str, Any], role: str,
) -> tuple[dict[str, Any], Any, Path]:
    model_path = _native_gamma_absolute_path(task.get("model_path"), f"{role}.model_path")
    model = read_model_artifacts(model_path)
    cell = np.asarray(model.atoms.cell.array, dtype=float)
    volume = abs(float(np.linalg.det(cell)))
    if not math.isfinite(volume) or volume <= 0.0:
        raise ValueError(f"{role} model cell volume must be positive")
    context = {
        "model_id": model.model_id,
        "model_version": model.version,
        "model_path": str(model.artifact_dir.resolve()),
        "atom_ids": list(model.atom_ids),
        "cell_angstrom": cell.tolist(),
        "volume_A3": volume,
    }
    if (task.get("model_id"), task.get("model_version")) != (
        context["model_id"], context["model_version"]
    ):
        raise ValueError(f"{role} model identity differs from model_path")
    return context, model, model_path


def _native_gamma_atom_map(
    task_root: Path, model_context: Mapping[str, Any], model: Any, role: str,
) -> tuple[Path, dict[str, Any]]:
    map_file = (task_root / "STRU.atom-map.json").resolve()
    atom_map = _read_json_object(map_file, f"{role} STRU.atom-map")
    if atom_map.get("schema") != "mlcc.abacus-atom-map.v1":
        raise ValueError(f"{role} atom map schema is unsupported")
    if atom_map.get("abacus_version_target") != _NATIVE_ABACUS_VERSION:
        raise ValueError(f"{role} atom map must target ABACUS {_NATIVE_ABACUS_VERSION}")
    if (atom_map.get("model_id"), atom_map.get("version")) != (
        model_context["model_id"], model_context["model_version"]
    ):
        raise ValueError(f"{role} atom map model identity differs from model_path")
    source_ids = [int(value) for value in atom_map.get("source_atom_ids", [])]
    if source_ids != [int(value) for value in model_context["atom_ids"]]:
        raise ValueError(f"{role} atom map source IDs differ from model")
    entries = atom_map.get("abacus_order")
    if not isinstance(entries, list) or len(entries) != len(source_ids):
        raise ValueError(f"{role} atom map must contain one abacus_order entry per atom")
    symbols = [str(value) for value in model.atoms.get_chemical_symbols()]
    seen: set[int] = set()
    for abacus_index, entry in enumerate(sorted(entries, key=lambda item: int(item.get("abacus_index", -1)))):
        if not isinstance(entry, Mapping) or int(entry.get("abacus_index", -1)) != abacus_index:
            raise ValueError(f"{role} atom map abacus indices are not contiguous")
        source_index = int(entry.get("source_index", -1))
        if source_index < 0 or source_index >= len(source_ids) or source_index in seen:
            raise ValueError(f"{role} atom map source index is invalid or repeated")
        seen.add(source_index)
        if int(entry.get("atom_id", -1)) != source_ids[source_index]:
            raise ValueError(f"{role} atom map atom ID differs from model")
        if str(entry.get("element")) != symbols[source_index]:
            raise ValueError(f"{role} atom map element differs from model")
    if seen != set(range(len(source_ids))):
        raise ValueError(f"{role} atom map does not cover model atoms")
    return map_file, atom_map


def _native_gamma_method(
    task: Mapping[str, Any], task_root: Path, role: str,
) -> tuple[dict[str, Any], Path]:
    declared = task.get("method_file")
    method_file = (
        _native_gamma_absolute_path(declared, f"{role}.method_file")
        if declared is not None
        else (task_root / "method.json").resolve()
    )
    expected_file = (task_root / "method.json").resolve()
    if method_file != expected_file:
        raise ValueError(f"{role} method_file is not its task method.json")
    method = _read_json_object(method_file, f"{role} method")
    if method.get("engine") != "abacus" or method.get("basis_type") != "lcao":
        raise ValueError(f"{role} method must be native ABACUS LCAO")
    if method.get("abacus_version_target") != _NATIVE_ABACUS_VERSION:
        raise ValueError(f"{role} method must target ABACUS {_NATIVE_ABACUS_VERSION}")
    if method.get("method_set") != task.get("method_set"):
        raise ValueError(f"{role} task/method method_set differs")
    if (method.get("model_id"), method.get("version")) != (
        task.get("model_id"), task.get("model_version")
    ):
        raise ValueError(f"{role} task/method model identity differs")
    return method, method_file


def _native_gamma_p7_child_binding(
    task: Mapping[str, Any],
    *,
    role: str,
    expected_parent: Mapping[str, Any],
    expected_case: Mapping[str, Any],
) -> None:
    """Validate the nested lineage used by a P7 phonon displacement task.

    P7 task records deliberately keep their parent fields inside the saved
    phonon/study/model lineage.  Do not copy those values to the task's
    historical top-level fields: the P4/P5 contract still owns those fields.
    """

    displacement = task.get("phonon_displacement")
    if not isinstance(displacement, Mapping):
        raise ValueError(f"{role}.phonon_displacement must be an object")
    required = (
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
    for field in required:
        if field not in displacement:
            raise ValueError(f"{role}.phonon_displacement lacks {field}")
    for field in (
        "plan_id",
        "plan_version",
        "displacement_id",
        "parent_model_id",
        "parent_model_version",
        "parent_study_id",
    ):
        _text(displacement[field], f"{role}.phonon_displacement.{field}")
    if displacement["entry_kind"] != "displacement":
        raise ValueError(f"{role}.phonon_displacement.entry_kind must be displacement")
    if displacement["displacement_unit"] != "angstrom":
        raise ValueError(f"{role}.phonon_displacement.displacement_unit must be angstrom")
    if displacement["sign"] not in ("plus", "minus"):
        raise ValueError(f"{role}.phonon_displacement.sign is invalid")
    for field in ("displaced_atom_id", "phonopy_atom_index"):
        value = displacement[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{role}.phonon_displacement.{field} must be a non-negative integer")
    vector = displacement["displacement_angstrom"]
    if isinstance(vector, (str, bytes)) or not isinstance(vector, Sequence) or len(vector) != 3:
        raise ValueError(f"{role}.phonon_displacement.displacement_angstrom must have three values")
    for index, value in enumerate(vector):
        _finite_number(value, f"{role}.phonon_displacement.displacement_angstrom[{index}]")

    if str(displacement["parent_study_id"]) != str(expected_parent["study_id"]):
        raise ValueError(f"{role}.phonon_displacement.parent_study_id differs from reference parent")
    if str(displacement["parent_model_id"]) != str(expected_parent["model_id"]):
        raise ValueError(f"{role}.phonon_displacement.parent_model_id differs from reference parent")
    if str(displacement["parent_model_version"]) != str(expected_parent["model_version"]):
        raise ValueError(f"{role}.phonon_displacement.parent_model_version differs from reference parent")

    manifest_path = _native_gamma_absolute_path(
        displacement["manifest_path"], f"{role}.phonon_displacement.manifest_path"
    )
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = _read_json_object(manifest_path, f"{role} phonon displacement manifest")
    if manifest.get("schema") != "mlcc.phonon-displacement-plan.v1":
        raise ValueError(f"{role} phonon displacement manifest schema is unsupported")
    if (
        manifest.get("plan_id") != displacement["plan_id"]
        or manifest.get("version") != displacement["plan_version"]
    ):
        raise ValueError(f"{role} phonon displacement plan identity differs from task")
    source_model = _mapping(manifest.get("source_model"), f"{role} phonon manifest.source_model")
    expected_model_path_value = expected_parent.get("model_path")
    if expected_model_path_value is None:
        raise ValueError(f"{role} requires reference parent model_path for P7 binding")
    expected_model_path = _native_gamma_absolute_path(
        expected_model_path_value, "reference parent model_path"
    )
    if (
        source_model.get("model_id") != expected_parent["model_id"]
        or source_model.get("version") != expected_parent["model_version"]
        or _native_gamma_absolute_path(
            source_model.get("path"), f"{role} phonon manifest.source_model.path"
        )
        != expected_model_path
    ):
        raise ValueError(f"{role} phonon manifest source_model differs from reference parent")
    manifest_request = _mapping(manifest.get("request"), f"{role} phonon manifest.request")
    if manifest_request.get("distance_unit") != displacement["displacement_unit"]:
        raise ValueError(f"{role} phonon manifest displacement unit differs from task")
    manifest_entries = manifest.get("displacements")
    if isinstance(manifest_entries, (str, bytes)) or not isinstance(manifest_entries, list):
        raise ValueError(f"{role} phonon manifest.displacements must be a list")
    matching_entries = [
        item
        for item in manifest_entries
        if isinstance(item, Mapping) and item.get("entry_id") == displacement["displacement_id"]
    ]
    if len(matching_entries) != 1:
        raise ValueError(f"{role} phonon manifest must contain one matching displacement entry")
    manifest_entry = _mapping(matching_entries[0], f"{role} phonon manifest displacement entry")
    if manifest_entry.get("kind") != displacement["entry_kind"]:
        raise ValueError(f"{role} phonon manifest displacement kind differs from task")
    for field in ("displaced_atom_id", "phonopy_atom_index", "sign"):
        if manifest_entry.get(field) != displacement[field]:
            raise ValueError(f"{role} phonon manifest {field} differs from task")
    manifest_vector = _array(
        manifest_entry.get("displacement_angstrom"),
        (3,),
        f"{role} phonon manifest displacement_angstrom",
    )
    if not np.allclose(
        manifest_vector,
        np.asarray(vector, dtype=float),
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise ValueError(f"{role} phonon manifest displacement vector differs from task")
    if "displacement_unit" in manifest_entry and manifest_entry["displacement_unit"] != displacement["displacement_unit"]:
        raise ValueError(f"{role} phonon manifest displacement_unit differs from task")

    def _check_displacement_metadata(container: Mapping[str, Any], name: str) -> None:
        metadata = _mapping(container.get("phonon_displacement"), f"{name}.phonon_displacement")
        for field in required:
            if field not in metadata:
                raise ValueError(f"{name}.phonon_displacement lacks {field}")
            if field in ("manifest_path", "parent_study_file"):
                actual_path = _native_gamma_absolute_path(metadata[field], f"{name}.phonon_displacement.{field}")
                expected_path = _native_gamma_absolute_path(displacement[field], f"{role}.phonon_displacement.{field}")
                if actual_path != expected_path:
                    raise ValueError(f"{name}.phonon_displacement.{field} differs from task")
            elif field == "displacement_angstrom":
                actual_vector = _array(
                    metadata[field], (3,), f"{name}.phonon_displacement.displacement_angstrom"
                )
                if not np.allclose(actual_vector, np.asarray(vector, dtype=float), rtol=0.0, atol=1.0e-12):
                    raise ValueError(f"{name}.phonon_displacement.displacement_angstrom differs from task")
            elif metadata[field] != displacement[field]:
                raise ValueError(f"{name}.phonon_displacement.{field} differs from task")

    parent_study_path = _native_gamma_absolute_path(
        displacement["parent_study_file"], f"{role}.phonon_displacement.parent_study_file"
    )
    parent_study = _read_json_object(parent_study_path, f"{role} phonon parent Study")
    if parent_study.get("study_id") != expected_parent["study_id"]:
        raise ValueError(f"{role} phonon parent Study differs from reference parent")
    if (
        parent_study.get("case_id") != expected_case["case_id"]
        or parent_study.get("case_role") != expected_case["case_role"]
    ):
        raise ValueError(f"{role} phonon parent Study case binding differs from reference")
    parent_model = _mapping(parent_study.get("model"), f"{role} phonon parent Study.model")
    if (
        parent_model.get("model_id") != expected_parent["model_id"]
        or parent_model.get("version") != expected_parent["model_version"]
    ):
        raise ValueError(f"{role} phonon parent Study model differs from reference parent")
    parent_study_model_path = parent_study.get("model_path")
    if parent_study_model_path is None:
        raise ValueError(f"{role} phonon parent Study lacks model_path")
    parent_model_path = _native_gamma_absolute_path(
        parent_study_model_path, f"{role} phonon parent Study.model_path"
    )
    if parent_model_path != expected_model_path:
        raise ValueError(f"{role} phonon parent Study model path differs from reference parent")

    child_study_path = _native_gamma_absolute_path(task.get("study_file"), f"{role}.study_file")
    child_study = _read_json_object(child_study_path, f"{role} child Study")
    if child_study.get("study_id") != task.get("study_id"):
        raise ValueError(f"{role} child Study ID differs from task")
    if (
        child_study.get("case_id") != expected_case["case_id"]
        or child_study.get("case_role") != expected_case["case_role"]
    ):
        raise ValueError(f"{role} child Study case binding differs from reference")
    if child_study.get("parent_study_id") != expected_parent["study_id"]:
        raise ValueError(f"{role} child Study parent_study_id differs from reference parent")
    derived_from = _mapping(child_study.get("derived_from"), f"{role} child Study.derived_from")
    for field, expected in (
        ("study_id", expected_parent["study_id"]),
        ("model_id", expected_parent["model_id"]),
        ("model_version", expected_parent["model_version"]),
    ):
        if derived_from.get(field) != expected:
            raise ValueError(f"{role} child Study.derived_from.{field} differs from reference parent")
    child_study_model = _mapping(child_study.get("model"), f"{role} child Study.model")
    if (
        child_study_model.get("model_id") != task.get("model_id")
        or child_study_model.get("version") != task.get("model_version")
    ):
        raise ValueError(f"{role} child Study model differs from task")
    _check_displacement_metadata(child_study, f"{role} child Study")

    model_path = _native_gamma_absolute_path(task.get("model_path"), f"{role}.model_path")
    model_record = _read_json_object(model_path / "model.json", f"{role} child Model")
    _check_displacement_metadata(model_record, f"{role} child Model")
    parent_models = model_record.get("parent_models")
    if not isinstance(parent_models, list) or not parent_models:
        raise ValueError(f"{role} child Model lacks parent_models lineage")
    if not any(
        isinstance(item, Mapping)
        and item.get("model_id") == expected_parent["model_id"]
        and item.get("version") == expected_parent["model_version"]
        and _native_gamma_absolute_path(item.get("path"), f"{role} child Model.parent_models.path")
        == expected_model_path
        for item in parent_models
    ):
        raise ValueError(f"{role} child Model parent_models lineage differs from reference parent")
    if model_record.get("spatial_mode") != "phonon_displacement_child":
        raise ValueError(f"{role} child Model spatial_mode is not phonon_displacement_child")


def _native_gamma_task_binding(
    task_file: Path,
    *,
    role: str,
    expected_method_set: str,
    expected_parent: Mapping[str, Any] | None,
    expected_case: Mapping[str, Any],
    expected_method_identity: Mapping[str, Any] | None,
    expected_model_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    task = _read_json_object(task_file, f"{role} task")
    _native_gamma_completed(task, role)
    if task.get("engine") != "abacus" or task.get("engine_version") != _NATIVE_ABACUS_VERSION:
        raise ValueError(f"{role} task must be ABACUS {_NATIVE_ABACUS_VERSION}")
    # The public ABACUS creator records P4 SCFs; earlier P5 producers recorded
    # P5 SCFs. P7 is accepted only for a displacement child with a complete
    # nested lineage and an explicit expected parent.
    stage = task.get("stage")
    if stage not in ("P4", "P5", "P7") or task.get("calculation") != "scf":
        raise ValueError(f"{role} task must be a P4/P5 SCF or a bound P7 SCF task")
    if task.get("basis_type") != "lcao":
        raise ValueError(f"{role} task must be an LCAO task")
    if task.get("method_set") != expected_method_set:
        raise ValueError(f"{role} method_set differs from Gamma provenance")
    if task.get("case_id") != expected_case["case_id"] or task.get("case_role") != expected_case["case_role"]:
        raise ValueError(f"{role} case binding differs from Gamma provenance")
    if stage == "P7":
        if expected_parent is None:
            raise ValueError(f"{role} P7 task requires an expected parent")
        _native_gamma_p7_child_binding(
            task,
            role=role,
            expected_parent=expected_parent,
            expected_case=expected_case,
        )
    elif expected_parent is not None:
        for field, expected in (
            ("parent_study_id", expected_parent["study_id"]),
            ("parent_model_id", expected_parent["model_id"]),
            ("parent_model_version", expected_parent["model_version"]),
        ):
            if task.get(field) != expected:
                raise ValueError(f"{role} {field} differs from reference parent")
    method, method_file = _native_gamma_method(task, task_file.parent, role)
    model_context, model, model_path = _native_gamma_model_context(task, role)
    map_file, atom_map = _native_gamma_atom_map(task_file.parent, model_context, model, role)
    method_identity = _native_method_identity(method, task_file.parent)
    if expected_method_identity is not None and method_identity != dict(expected_method_identity):
        raise ValueError(f"{role} physical method differs from reference method")
    if expected_model_context is not None:
        if model_context["atom_ids"] != expected_model_context["atom_ids"]:
            raise ValueError(f"{role} atom IDs differ from reference model")
        if not np.allclose(
            np.asarray(model_context["cell_angstrom"], dtype=float),
            np.asarray(expected_model_context["cell_angstrom"], dtype=float),
            rtol=0.0,
            atol=_CELL_TOL,
        ):
            raise ValueError(f"{role} cell differs from reference model")
    return {
        "task": task,
        "task_file": task_file,
        "method": method,
        "method_file": method_file,
        "method_identity": method_identity,
        "model_context": model_context,
        "model": model,
        "model_path": model_path,
        "atom_map": atom_map,
        "atom_map_file": map_file,
    }


def _native_gamma_source_ref(value: Any, name: str, refs: list[str]) -> None:
    path = _native_gamma_absolute_path(value, name)
    if not path.is_file():
        raise FileNotFoundError(path)
    text = str(path)
    if text not in refs:
        refs.append(text)


def _native_gamma_add_task_files(
    binding: Mapping[str, Any], refs: list[str], *, include_study: bool,
) -> None:
    root = Path(binding["task_file"]).parent.resolve()
    for name in ("task.json", "method.json", "result.json", "electronic.json", "KPT", "STRU", "STRU.atom-map.json"):
        _native_gamma_source_ref(root / name, f"{root.name}.{name}", refs)
    if include_study:
        task = _mapping(binding["task"], f"{root.name}.task")
        if task.get("stage") == "P7":
            # P7 child studies are deliberately stored at task.study_file;
            # their parent Study is the nested phonon displacement source.
            child_study = _native_gamma_absolute_path(
                task.get("study_file"), f"{root.name}.study_file"
            )
            _native_gamma_source_ref(child_study, f"{root.name}.study_file", refs)
            displacement = _mapping(
                task.get("phonon_displacement"), f"{root.name}.phonon_displacement"
            )
            parent_study = _native_gamma_absolute_path(
                displacement.get("parent_study_file"),
                f"{root.name}.phonon_displacement.parent_study_file",
            )
            _native_gamma_source_ref(parent_study, f"{root.name}.parent_study_file", refs)
        else:
            _native_gamma_source_ref(root / "study.json", f"{root.name}.study.json", refs)
    model_path = Path(binding["model_path"]).resolve()
    _native_gamma_source_ref(model_path / "model.json", f"{root.name}.model.json", refs)
    structure_file = _read_json_object(model_path / "model.json", f"{root.name} model")
    _native_gamma_source_ref(
        model_path / _text(structure_file["structure_file"], f"{root.name}.structure_file"),
        f"{root.name}.model_structure",
        refs,
    )


def _native_gamma_postprocess_job(post: Mapping[str, Any], post_file: Path) -> dict[str, Any]:
    _native_gamma_completed(post, "Gamma postprocess")
    job = {
        "role": "gamma_postprocess",
        "task_id": _text(post["task_id"], "Gamma postprocess.task_id"),
        "scheduler_job_id": _text(post["scheduler_job_id"], "Gamma postprocess.scheduler_job_id"),
        "scheduler_state": _text(post["scheduler_state"], "Gamma postprocess.scheduler_state"),
        "exit_code": _text(post["exit_code"], "Gamma postprocess.exit_code"),
        "engine": copy.deepcopy(post.get("engine")),
        "engine_version": copy.deepcopy(post.get("engine_version")),
        "task_file": str(post_file.resolve()),
    }
    return job


def read_native_gamma_force(path: str | Path) -> dict[str, Any]:
    """Bind a saved ABACUS finite-displacement Gamma raw product.

    The producer owns force fitting and diagnostics.  This reader only binds
    its saved raw Hessian to the P5 reference/displacement TaskRecords and
    maps it to the existing Gamma envelope.  The raw matrix is returned byte
    for byte as JSON values: no ASR, reciprocity, Hermitian or NAC operation
    is performed here.
    """

    raw_path = Path(path).expanduser().resolve()
    raw = _read_json_object(raw_path, "native raw Gamma product")
    if raw.get("schema") not in (NATIVE_RAW_GAMMA_SCHEMA, "mlcc.native-raw-gamma-force.v1"):
        raise ValueError("native raw Gamma schema is unsupported")
    units = _mapping(raw.get("units"), "native raw Gamma units")
    for key, expected in (
        ("displacement", "angstrom"),
        ("force", "eV/angstrom"),
        ("force_constants", FORCE_CONSTANT_UNIT),
        ("hessian", FORCE_CONSTANT_UNIT),
    ):
        if units.get(key) != expected:
            raise ValueError(f"native raw Gamma units.{key} must be {expected}")
    if raw.get("force_constants_convention") != "Phonopy [displaced atom, force atom, displaced component, force component]":
        raise ValueError("native raw Gamma force-constant convention is unsupported")
    if raw.get("hessian_convention") != "H[(displaced_atom,displaced_component),(force_atom,force_component)]":
        raise ValueError("native raw Gamma Hessian convention is unsupported")

    provenance = _mapping(raw.get("provenance"), "native raw Gamma provenance")
    expected_method_set = _text(provenance.get("method_set"), "native raw Gamma provenance.method_set")
    if provenance.get("engine") != "abacus" or provenance.get("engine_version") != _NATIVE_ABACUS_VERSION:
        raise ValueError("native raw Gamma provenance must be ABACUS 3.10.1")
    reference_root = _native_gamma_absolute_path(
        provenance.get("reference_task_root"), "native raw Gamma provenance.reference_task_root"
    )
    reference_file = _native_gamma_task_file(reference_root, "native raw Gamma reference_task_root")
    parent_study = _mapping(provenance.get("parent_study"), "native raw Gamma provenance.parent_study")
    parent_study_id = _text(parent_study.get("study_id"), "native raw Gamma parent_study.study_id")
    case_id = _text(parent_study.get("case_id"), "native raw Gamma parent_study.case_id")
    case_role = _text(parent_study.get("case_role"), "native raw Gamma parent_study.case_role")
    expected_case = {"case_id": case_id, "case_role": case_role}

    reference = _native_gamma_task_binding(
        reference_file,
        role="Gamma reference SCF",
        expected_method_set=expected_method_set,
        expected_parent=None,
        expected_case=expected_case,
        expected_method_identity=None,
        expected_model_context=None,
    )
    reference_task = reference["task"]
    if reference_task.get("study_id") != parent_study_id:
        raise ValueError("Gamma reference SCF study_id differs from parent study")
    if reference_task.get("case_id") != case_id or reference_task.get("case_role") != case_role:
        raise ValueError("Gamma reference SCF case binding differs from parent study")
    if provenance.get("reference_task_id") != reference_task["task_id"]:
        raise ValueError("Gamma provenance reference_task_id differs from reference SCF")
    if provenance.get("reference_scheduler_job_id") != reference_task["scheduler_job_id"]:
        raise ValueError("Gamma provenance reference_scheduler_job_id differs from reference SCF")

    reference_model = _mapping(provenance.get("reference_model"), "native raw Gamma provenance.reference_model")
    if (
        reference_model.get("model_id"),
        reference_model.get("version"),
        _native_gamma_absolute_path(reference_model.get("path"), "native raw Gamma reference_model.path"),
    ) != (
        reference["model_context"]["model_id"],
        reference["model_context"]["model_version"],
        Path(reference["model_context"]["model_path"]).resolve(),
    ):
        raise ValueError("Gamma reference model differs from reference SCF")
    if reference_task.get("study_file") is not None and parent_study.get("path") is not None:
        if _native_gamma_absolute_path(parent_study["path"], "native raw Gamma parent_study.path") != _native_gamma_absolute_path(reference_task["study_file"], "Gamma reference study_file"):
            raise ValueError("Gamma parent study file differs from reference SCF")

    method_identity = reference["method_identity"]
    atom_ids = list(reference["model_context"]["atom_ids"])
    n_atoms = len(atom_ids)
    raw_hessian = _array(
        raw.get("raw_hessian_eV_A2"),
        (3 * n_atoms, 3 * n_atoms),
        "native raw Gamma raw_hessian_eV_A2",
    )
    if "raw_force_constants_eV_A2" in raw:
        _array(
            raw["raw_force_constants_eV_A2"],
            (n_atoms, n_atoms, 3, 3),
            "native raw Gamma raw_force_constants_eV_A2",
        )
    assembly = _mapping(raw.get("assembly"), "native raw Gamma assembly")
    for flag in (
        "asr_applied",
        "reciprocity_projection_applied",
        "hermitian_projection_applied",
        "nac_applied",
        "born_or_dipole_constructed",
        "dipoles_constructed",
        "born_charges_constructed",
    ):
        if flag not in assembly:
            raise KeyError(f"native raw Gamma assembly.{flag}")
        if assembly[flag] is not False:
            raise ValueError(f"native raw Gamma assembly.{flag} must be false")

    reference_map_file = reference["atom_map_file"]
    atom_map = _mapping(provenance.get("atom_map"), "native raw Gamma provenance.atom_map")
    if _native_gamma_absolute_path(atom_map.get("reference"), "native raw Gamma atom_map.reference") != reference_map_file:
        raise ValueError("Gamma atom_map.reference differs from reference SCF atom map")
    source_atom_ids = [int(value) for value in atom_map.get("source_atom_ids", [])]
    if source_atom_ids != atom_ids:
        raise ValueError("Gamma atom_map source_atom_ids differ from reference model")
    source_symbols = [str(value) for value in atom_map.get("source_symbols", [])]
    reference_symbols = [str(value) for value in reference["model"].atoms.get_chemical_symbols()]
    if source_symbols != reference_symbols:
        raise ValueError("Gamma atom_map source_symbols differ from reference model")
    if atom_map.get("abacus_order") != reference["atom_map"].get("abacus_order"):
        raise ValueError("Gamma atom_map abacus_order differs from reference SCF atom map")

    task_entries = provenance.get("tasks")
    if not isinstance(task_entries, list) or not task_entries:
        raise ValueError("native raw Gamma provenance.tasks must be a non-empty list")
    task_count = provenance.get("task_count")
    if isinstance(task_count, bool) or not isinstance(task_count, int) or task_count != len(task_entries):
        raise ValueError("Gamma provenance.task_count differs from provenance.tasks")
    child_bindings: list[dict[str, Any]] = []
    seen_task_ids: set[str] = {reference_task["task_id"]}
    for index, entry_value in enumerate(task_entries):
        entry = _mapping(entry_value, f"native raw Gamma provenance.tasks[{index}]")
        task_file = _native_gamma_task_file(entry.get("task_root"), f"Gamma displacement[{index}].task_root")
        binding = _native_gamma_task_binding(
            task_file,
            role=f"Gamma displacement[{index}]",
            expected_method_set=expected_method_set,
            expected_parent={
                "study_id": reference_task["study_id"],
                "model_id": reference["model_context"]["model_id"],
                "model_version": reference["model_context"]["model_version"],
                "model_path": reference["model_context"]["model_path"],
            },
            expected_case=expected_case,
            expected_method_identity=method_identity,
            expected_model_context=reference["model_context"],
        )
        task = binding["task"]
        if task["task_id"] in seen_task_ids:
            raise ValueError("Gamma provenance.tasks contain duplicate task_id")
        seen_task_ids.add(task["task_id"])
        if entry.get("task_id") != task["task_id"]:
            raise ValueError(f"Gamma displacement[{index}] task_id differs from task.json")
        if entry.get("scheduler_job_id") != task["scheduler_job_id"]:
            raise ValueError(f"Gamma displacement[{index}] scheduler_job_id differs from task.json")
        atom_index = entry.get("atom_index")
        source_atom_id = entry.get("source_atom_id")
        if isinstance(atom_index, bool) or not isinstance(atom_index, int) or atom_index < 0 or atom_index >= n_atoms:
            raise ValueError(f"Gamma displacement[{index}] atom_index is invalid")
        if int(source_atom_id) != atom_ids[atom_index]:
            raise ValueError(f"Gamma displacement[{index}] source_atom_id differs from atom map")
        if entry.get("sign") not in ("+", "-"):
            raise ValueError(f"Gamma displacement[{index}] sign is invalid")
        child_bindings.append(binding)

    displacement_records = raw.get("displacements")
    if displacement_records is not None:
        if not isinstance(displacement_records, list) or len(displacement_records) != len(task_entries):
            raise ValueError("Gamma displacements do not match provenance.tasks")
        for index, displacement_value in enumerate(displacement_records):
            displacement = _mapping(displacement_value, f"native raw Gamma displacements[{index}]")
            for key in ("task_id", "scheduler_job_id", "task_root"):
                if displacement.get(key) != task_entries[index].get(key):
                    raise ValueError(f"Gamma displacements[{index}].{key} differs from provenance.tasks")

    postprocess_file_value = provenance.get("postprocess_task_file")
    postprocess_file = _native_gamma_task_file(
        postprocess_file_value, "native raw Gamma provenance.postprocess_task_file"
    )
    postprocess = _read_json_object(postprocess_file, "Gamma postprocess task")
    postprocess_job = _native_gamma_postprocess_job(postprocess, postprocess_file)
    for field, expected in (
        ("study_id", parent_study_id),
        ("model_id", reference["model_context"]["model_id"]),
        ("model_version", reference["model_context"]["model_version"]),
    ):
        if field in postprocess and postprocess[field] != expected:
            raise ValueError(f"Gamma postprocess {field} differs from parent")
    if postprocess.get("result_file") is not None:
        if _native_gamma_absolute_path(postprocess["result_file"], "Gamma postprocess.result_file") != raw_path:
            raise ValueError("Gamma postprocess result_file differs from raw product")

    source_refs: list[str] = []
    _native_gamma_source_ref(raw_path, "native raw Gamma product", source_refs)
    _native_gamma_source_ref(provenance.get("manifest"), "native raw Gamma provenance.manifest", source_refs)
    if raw["schema"] == NATIVE_RAW_GAMMA_SCHEMA or provenance.get("phonopy_displacement_yaml") is not None:
        _native_gamma_source_ref(
            provenance.get("phonopy_displacement_yaml"),
            "native raw Gamma provenance.phonopy_displacement_yaml", source_refs,
        )
    if parent_study.get("path") is not None:
        _native_gamma_source_ref(parent_study["path"], "native raw Gamma parent_study.path", source_refs)
    _native_gamma_add_task_files(reference, source_refs, include_study=False)
    for binding in child_bindings:
        _native_gamma_add_task_files(binding, source_refs, include_study=True)
    for value, name in (
        (postprocess_file, "Gamma postprocess task"),
        (reference.get("task_file"), "Gamma reference task"),
        (reference.get("method_file"), "Gamma reference method"),
        (atom_map.get("reference"), "Gamma reference atom map"),
    ):
        _native_gamma_source_ref(value, name, source_refs)
    for index, entry_value in enumerate(task_entries):
        entry = _mapping(entry_value, f"native raw Gamma provenance.tasks[{index}]")
        _native_gamma_source_ref(entry["task_root"] + "/task.json", f"Gamma displacement[{index}] task", source_refs)
    reference_record = _mapping(raw.get("reference"), "native raw Gamma reference")
    for key in ("result_file", "electronic_file", "method_file"):
        if reference_record.get(key) is not None:
            _native_gamma_source_ref(reference_record[key], f"native raw Gamma reference.{key}", source_refs)
    for index, displacement_value in enumerate(displacement_records or []):
        displacement = _mapping(displacement_value, f"native raw Gamma displacements[{index}]")
        for key in ("result_file", "electronic_file", "method_file", "study_file", "model_file"):
            if displacement.get(key) is not None:
                _native_gamma_source_ref(displacement[key], f"native raw Gamma displacements[{index}].{key}", source_refs)
    for key in ("result_file", "output_file", "stdout_file", "stderr_file", "source_manifest"):
        if postprocess.get(key) is not None:
            _native_gamma_source_ref(postprocess[key], f"Gamma postprocess.{key}", source_refs)

    gamma_analysis = _mapping(raw.get("gamma_analysis"), "native raw Gamma gamma_analysis")
    unresolved_reasons: list[str] = []
    status = "complete"
    raw_status = _text(raw.get("status"), "native raw Gamma status")
    if raw_status != "raw_force_chain_complete_unqualified":
        status = "unresolved"
        unresolved_reasons.append(f"raw_gamma_status_{raw_status}")
    if gamma_analysis.get("characteristic_status") == "unresolved_raw_nonsymmetric":
        status = "unresolved"
        unresolved_reasons.append("raw_gamma_characteristic_status_unresolved_raw_nonsymmetric")
    parent = {
        "study_id": parent_study_id,
        "model_id": reference["model_context"]["model_id"],
        "model_version": reference["model_context"]["model_version"],
        "model_path": reference["model_context"]["model_path"],
    }
    native_jobs = [
        _native_job(
            role="reference_scf",
            task=reference_task,
            task_file=reference["task_file"],
            engine="abacus",
            engine_version=_NATIVE_ABACUS_VERSION,
        )
    ]
    native_jobs.extend(
        _native_job(
            role="gamma_displacement",
            task=binding["task"],
            task_file=binding["task_file"],
            engine="abacus",
            engine_version=_NATIVE_ABACUS_VERSION,
        )
        for binding in child_bindings
    )
    native_jobs.append(postprocess_job)
    source = {
        "source_mode": "native_source_bound",
        "native_raw_product": str(raw_path),
        "native_refs": list(source_refs),
        "native_task_records": [str(reference["task_file"].resolve())]
        + [str(binding["task_file"].resolve()) for binding in child_bindings],
        "postprocess_task_file": str(postprocess_file),
    }
    qualification = {
        "source_mode": "native_source_bound",
        "scientific": False,
        "production": False,
        "reason": "Native Gamma raw force chain is source-bound but remains scientifically and production unqualified",
    }
    return {
        "schema": GAMMA_HESSIAN_SCHEMA,
        "provenance_kind": "native_derived",
        "source_mode": "native_source_bound",
        "scientific_status": "native_source_bound_unqualified" if status == "complete" else "native_source_bound_unresolved",
        "scientific_qualification": False,
        "production_qualified": False,
        "production_qualification": False,
        "parent": parent,
        "atom_ids": copy.deepcopy(atom_ids),
        "elements": reference_symbols,
        "cell_angstrom": copy.deepcopy(reference["model_context"]["cell_angstrom"]),
        "volume_A3": reference["model_context"]["volume_A3"],
        "matrix_basis": "parent_atom_major_cartesian",
        "unit": FORCE_CONSTANT_UNIT,
        "matrix_unit": FORCE_CONSTANT_UNIT,
        "matrix_eV_per_A2": copy.deepcopy(raw["raw_hessian_eV_A2"]),
        "method_identity": copy.deepcopy(method_identity),
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "q_point": [0.0, 0.0, 0.0],
        "source": source,
        "source_refs": list(source_refs),
        "native_jobs": native_jobs,
        "native_tasks": copy.deepcopy(native_jobs),
        "raw_product": copy.deepcopy(raw),
        "assembly": copy.deepcopy(dict(assembly)),
        "diagnostics": copy.deepcopy(raw.get("diagnostics")),
        "gamma_analysis": copy.deepcopy(dict(gamma_analysis)),
        "reference": copy.deepcopy(dict(reference_record)),
        "displacements": copy.deepcopy(raw.get("displacements", [])),
        "raw_force_constants_eV_A2": copy.deepcopy(raw.get("raw_force_constants_eV_A2")),
        "raw_hessian_eV_A2": copy.deepcopy(raw["raw_hessian_eV_A2"]),
        "postprocess_task": {**copy.deepcopy(postprocess), "task_file": str(postprocess_file)},
        "status": status,
        "unresolved_reasons": unresolved_reasons,
        "qualification": qualification,
    }


def _native_born_polarization(
    point: Mapping[str, Any], scf: Mapping[str, Any], refs: list[str],
) -> dict[str, Any]:
    """Bind a saved PYATB polarization point, retaining its unselected branch."""
    source = point["pyatb"]
    task_file = Path(source["task_path"]) / "task.json"
    task = _read_json_object(task_file, "Born PYATB task")
    _native_gamma_completed(task, "Born PYATB")
    if task["engine"] != "pyatb" or task["engine_version"] != "1.1.2.dev0":
        raise ValueError("Born source requires the observed PYATB 1.1.2.dev0 interface")
    if (task["task_id"], task["scheduler_job_id"]) != (source["task_id"], source["job_id"]):
        raise ValueError("Born polarization task/job differs from saved point")
    scf_id_field = "reference_scf_task_id" if task["schema"] == "mlcc.pyatb-postprocess-task.v1" else "source_scf_task_id"
    if (task[scf_id_field], task["reference_scf_job_id"]) != (
        scf["task_id"], scf["scheduler_job_id"],
    ):
        raise ValueError("Born polarization SCF binding differs from native task")
    branch = point["branch"]
    if branch["physical_branch_selected"] is not False or branch["integer_shift"] is not None or branch["nearest_quantum_applied"] is not False:
        raise ValueError("Born family requires an explicitly unselected polarization branch")
    output_file = Path(source["polarization_output"])
    if output_file.read_text(encoding="utf-8") != source["raw_output_text"]:
        raise ValueError("Born polarization raw text differs from native output")
    for value in (task_file, output_file, source["input"], source["out_input_json"]):
        _native_gamma_source_ref(value, "Born polarization source", refs)
    if "record_file" in source:
        record_file = Path(source["record_file"])
        record = _read_json_object(record_file, "saved polarization record")
        for field in ("ionic_phase", "electronic_phase"):
            if point[field]["unit"] != record["phase_unit"]:
                raise ValueError(f"Born point {field} unit differs from saved polarization record")
            if any(point[field][key] != record[field][key] for key in ("values", "raw_tokens")):
                raise ValueError(f"Born point {field} differs from saved polarization record")
        if point["polarization"] != record["polarization"]:
            raise ValueError("Born point polarization differs from saved polarization record")
        if record["raw_output_text"] != source["raw_output_text"]:
            raise ValueError("Born point raw text differs from saved polarization record")
        _native_gamma_source_ref(record_file, "Born polarization record", refs)
        _native_gamma_source_ref(source["raw_output_file"], "Born raw copy", refs)
    return _native_job(role="pyatb_polarization", task=task, task_file=task_file,
                       engine=task["engine"], engine_version=task["engine_version"])


def read_native_born_family(path: str | Path) -> dict[str, Any]:
    """Expose saved affine coefficients without choosing a physical Born tensor."""
    raw_path = Path(path).expanduser().resolve()
    raw = _read_json_object(raw_path, "native Born family")
    if raw["schema"] != "mlcc.native-born-branch-family.v1" or raw["unit"] != "e":
        raise ValueError("native Born family schema or unit is unsupported")
    if raw["born_effective_charge_tensor"] is not None or raw["selected_branch_shift"] is not None:
        raise ValueError("native Born family cannot claim a selected physical tensor")
    parent = raw["parent"]
    reference = raw["reference"]
    reference_file = Path(reference["native_scf_task_path"]) / "task.json"
    reference_task = _read_json_object(reference_file, "Born reference SCF")
    expected_case = {key: reference_task[key] for key in ("case_id", "case_role")}
    binding = _native_gamma_task_binding(
        reference_file, role="Born reference SCF", expected_parent=None,
        expected_case=expected_case, expected_method_set=raw["common_method"]["method_set"],
        expected_method_identity=None, expected_model_context=None,
    )
    method = binding["method_identity"]
    if _native_method_identity(raw["common_method"], reference_file.parent) != method:
        raise ValueError("Born family common method differs from reference SCF")
    for key in ("study_id", "model_id", "model_version", "model_path"):
        if parent[key] != reference_task[key]:
            raise ValueError(f"Born parent {key} differs from reference SCF")
    # Top-level atom_ids identifies the independently displaced sites; the
    # affine tensor explicitly declares the full expanded parent atom order.
    context = {"parent": copy.deepcopy(parent), "common_method": method,
               "atom_ids": copy.deepcopy(raw["affine_family"]["atom_ids_in_tensor_order"]),
               **{key: copy.deepcopy(raw[key]) for key in ("cell_angstrom", "volume_A3")}}
    _validate_context_geometry(context, "native Born family")
    for key in ("atom_ids", "cell_angstrom"):
        if context[key] != binding["model_context"][key]:
            raise ValueError(f"Born {key} differs from reference model")
    affine = raw["affine_family"]
    if affine["physical_branch_selected"] is not False or affine["physical_born_tensor"] is not None:
        raise ValueError("Born affine coefficients cannot be selected physical tensors")
    policy = affine["selection_policy"]
    if policy["selected_branch_shift"] is not None or policy["nearest_quantum_applied"] is not False or policy["asr_projected"] is not False:
        raise ValueError("Born affine family must retain unselected, unprojected branches")
    if affine["axes"] != {"tensor": ["atom", "polarization", "displacement"],
                          "polarization": ["x", "y", "z"], "displacement": ["x", "y", "z"],
                          "basis": "Cartesian"}:
        raise ValueError("Born affine coefficients must declare Cartesian axes")
    n_atoms = len(context["atom_ids"])
    _array(affine["base_tensor_e"], (n_atoms, 3, 3), "Born affine base")
    _array(affine["coefficient_tensors_e"], (len(affine["integer_labels"]), n_atoms, 3, 3), "Born affine coefficients")
    if affine["atom_ids_in_tensor_order"] != context["atom_ids"]:
        raise ValueError("Born affine atom order differs from parent")
    source = raw["source"]
    collection_file = Path(source["collection_file"])
    collection = _read_json_object(collection_file, "ordered polarization collection")
    if collection["schema"] != "mlcc.native-ordered-polarization-collection.v1" or collection["parent"] != parent:
        raise ValueError("Born ordered collection schema or parent differs")
    points = [pair[sign] for pair in raw["pairs"] for sign in ("plus", "minus")]
    if points != collection["ordered_points"] or len(points) != collection["ordered_point_count"]:
        raise ValueError("Born pairs differ from saved ordered polarization collection")
    refs = [str(raw_path), str(collection_file)]
    _native_gamma_add_task_files(binding, refs, include_study=False)
    jobs = [_native_job(role="reference_scf", task=reference_task, task_file=reference_file,
                        engine="abacus", engine_version=_NATIVE_ABACUS_VERSION)]
    ref_point = {"pyatb": reference, **{field: reference[field] for field in (
        "branch", "ionic_phase", "electronic_phase", "polarization")}}
    jobs.append(_native_born_polarization(ref_point, reference_task, refs))
    reference_electronic = reference_file.parent / "electronic.json"
    insulation = [{"task_id": reference_task["task_id"], "source_path": str(reference_electronic),
                   "saved_electronic": _read_json_object(reference_electronic, "saved reference electronic evidence")}]
    for point in points:
        scf_source = point["source_scf"]
        scf_file = Path(scf_source["task_path"]) / "task.json"
        child = _native_gamma_task_binding(
            scf_file, role="Born displacement SCF", expected_parent=parent,
            expected_case=expected_case, expected_method_set=method["method_set"],
            expected_method_identity=method, expected_model_context=binding["model_context"],
        )
        scf = child["task"]
        if (scf["task_id"], scf["scheduler_job_id"]) != (scf_source["task_id"], scf_source["job_id"]):
            raise ValueError("Born displacement task/job differs from native SCF")
        manifest = point["manifest"]
        if manifest["atom_id"] != context["atom_ids"][manifest["atom_index"]]:
            raise ValueError("Born displacement atom mapping differs from parent")
        _native_gamma_add_task_files(child, refs, include_study=True)
        electronic_file = scf_file.parent / "electronic.json"
        insulation.append({"task_id": scf["task_id"], "source_path": str(electronic_file),
                           "saved_electronic": _read_json_object(electronic_file, "saved electronic evidence")})
        jobs.append(_native_job(role="born_displacement_scf", task=scf, task_file=scf_file,
                                engine="abacus", engine_version=_NATIVE_ABACUS_VERSION))
        jobs.append(_native_born_polarization(point, scf, refs))
    for value in source["postprocess_task_files"]:
        task_file = Path(value)
        task = _read_json_object(task_file, "Born aggregation task")
        _native_gamma_completed(task, "Born aggregation")
        if task["study_id"] != parent["study_id"]:
            raise ValueError("Born aggregation Study differs from family")
        _native_gamma_source_ref(task_file, "Born aggregation task", refs)
        jobs.append(_native_job(role="born_family_postprocess", task=task, task_file=task_file,
                                engine=task["engine"], engine_version=task["engine_version"]))
    reasons = _non_empty_text_list(raw["unresolved_reasons"], "Born family unresolved reasons")
    return {
        "schema": AGGREGATE_SCHEMA, "unit": "e", "context": context,
        "atom_ids": copy.deepcopy(context["atom_ids"]), "common_method": copy.deepcopy(method),
        "provenance_kind": "native_derived", "source_mode": "native_source_bound",
        "source": {"native_born_family": str(raw_path)}, "source_refs": refs, "native_jobs": jobs,
        "full_born_tensors_e": None, "columns": [], "sources": [],
        "missing_columns": [{"atom_id": atom_id, "cartesian_axis": axis, "reasons": list(reasons)}
                            for atom_id in context["atom_ids"] for axis in range(3)],
        "raw_product": copy.deepcopy(raw), "insulation_evidence": insulation,
        "status": "unresolved", "unresolved_reasons": list(reasons),
        "scientific_qualification": False, "production_qualification": False,
    }


def _parse_pyatb_static_output(path: Path) -> list[list[float]]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_header = ["#", "xx", "xy", "xz", "yx", "yy", "yz", "zx", "zy", "zz"]
    if len(lines) != 2 or lines[0].split() != expected_header:
        raise ValueError("PYATB static dielectric output must contain the nine-column header and one data row")
    values = lines[1].split()
    if len(values) != 9:
        raise ValueError("PYATB static dielectric output data row must contain nine values")
    tensor = [float(value) for value in values]
    if not all(math.isfinite(value) for value in tensor):
        raise ValueError("PYATB static dielectric output contains a non-finite value")
    # PYATB has already included the identity on the diagonal.  Preserve its
    # row-major values exactly; do not symmetrize or add another identity.
    return np.asarray(tensor, dtype=float).reshape(3, 3).tolist()


def _pyatb_gap_evidence(
    electronic: Mapping[str, Any],
    input_parameters: Mapping[str, Any],
    optical_parameters: Mapping[str, Any],
    minimum_gap_eV: float,
) -> tuple[dict[str, Any], list[str]]:
    nspin = electronic["nspin"]
    if nspin != 1 or electronic["occupations"] != "fixed":
        raise ValueError("PYATB static electronic binding requires nspin=1 fixed occupations")
    electron_count = electronic["electron_count_neutral"]
    gap = electronic.get("sampled_mesh_KS_gap_eV")
    if gap is not None:
        gap = _finite_number(gap, "SCF sampled_mesh_KS_gap_eV")
    occ_band = optical_parameters["occ_band"]
    if isinstance(occ_band, bool) or not isinstance(occ_band, int) or occ_band <= 0:
        raise ValueError("PYATB OPTICAL_CONDUCTIVITY.occ_band must be a positive integer")
    if input_parameters.get("nspin") != 1:
        raise ValueError("PYATB INPUT_PARAMETERS.nspin must be 1")
    if optical_parameters.get("static_dielectric_only") != 1:
        raise ValueError("PYATB OPTICAL_CONDUCTIVITY.static_dielectric_only must be 1")
    expected_occ = float(electron_count) / 2.0
    integer_electron_count = math.isclose(
        expected_occ, round(expected_occ), rel_tol=0.0, abs_tol=1.0e-10
    )
    normalized = np.asarray(electronic["normalized_occupations"], dtype=float)
    if integer_electron_count and normalized.ndim == 3 and normalized.shape[0] == 1:
        expected_band = int(round(expected_occ))
        occupancy_passed = (
            occ_band == expected_band
            and occ_band <= normalized.shape[2]
            and np.allclose(normalized[:, :, :occ_band], 2.0, rtol=0.0, atol=1.0e-6)
            and np.allclose(normalized[:, :, occ_band:], 0.0, rtol=0.0, atol=1.0e-6)
        )
    else:
        occupancy_passed = False
    reasons: list[str] = []
    if not occupancy_passed:
        reasons.append("occupation_contract_unmet")
    if gap is None:
        reasons.append("sampled_mesh_gap_missing")
    elif gap <= minimum_gap_eV:
        reasons.append("sampled_mesh_gap_below_minimum")
    return {
        "minimum_gap_eV": minimum_gap_eV,
        "sampled_mesh_KS_gap_eV": gap,
        "gap_status": electronic.get("gap_status"),
        "gap_reason": electronic.get("gap_reason"),
        "gap_qualification": electronic.get("gap_qualification"),
        "occ_band": occ_band,
        "electron_count_neutral": electron_count,
        "occupancy_passed": occupancy_passed,
        "gap_passed": gap is not None and gap > minimum_gap_eV,
        "passed": not reasons,
    }, reasons


def read_pyatb_static_electronic(request_path: str | Path) -> dict[str, Any]:
    """Read and bind one completed native ABACUS/PYATB static tensor.

    This is a source-bound parser.  It never launches PYATB or copies matrix
    files, and it returns an unresolved product when the declared sampled-gap
    or occupation gate is not met.
    """

    request_file = Path(request_path).expanduser().resolve()
    request = _read_json_object(request_file, "PYATB request")
    if request["schema"] != PYATB_REQUEST_SCHEMA:
        raise ValueError("PYATB request schema is unsupported")
    scf_dir = Path(_text(request["scf_task_path"], "request.scf_task_path")).expanduser().resolve()
    if not scf_dir.is_dir():
        raise FileNotFoundError(scf_dir)
    post_file = Path(_text(request["postprocess_task_path"], "request.postprocess_task_path")).expanduser()
    if not post_file.is_absolute():
        raise ValueError("request.postprocess_task_path must be absolute")
    post_file = post_file.resolve()
    post = _read_json_object(post_file, "PYATB postprocess task")
    if post["runner"] != "slurm":
        raise ValueError("PYATB postprocess runner must be slurm")
    if str(post["scheduler_state"]).upper() != "COMPLETED":
        raise ValueError(f"PYATB postprocess scheduler state is not COMPLETED: {post['scheduler_state']!r}")
    if post["exit_code"] != "0:0":
        raise ValueError(f"PYATB postprocess exit code is not 0:0: {post['exit_code']!r}")
    if post["engine"] != "pyatb":
        raise ValueError(f"PYATB postprocess engine is unsupported: {post['engine']!r}")
    pyatb_version = _text(post["engine_version"], "postprocess.engine_version")
    if post["mode"] != "direct_static":
        raise ValueError("PYATB postprocess mode must be direct_static")
    workdir = Path(_text(post["working_directory"], "postprocess.working_directory")).expanduser()
    if not workdir.is_absolute():
        raise ValueError("postprocess.working_directory must be absolute")
    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise FileNotFoundError(workdir)
    runtime_version_file = _resolve_within(post["runtime_version_file"], workdir, "postprocess.runtime_version_file")
    if not runtime_version_file.is_file():
        raise FileNotFoundError(runtime_version_file)
    runtime_version = runtime_version_file.read_text(encoding="utf-8").strip()
    if runtime_version != pyatb_version:
        raise ValueError("PYATB runtime version differs from postprocess.engine_version")
    input_file = _resolve_within(post["input_json"], workdir, "postprocess.input_json")
    output_file = _resolve_within(post["output_file"], workdir, "postprocess.output_file")
    if not input_file.is_file():
        raise FileNotFoundError(input_file)
    if not output_file.is_file():
        raise FileNotFoundError(output_file)
    pyatb_input = _read_json_object(input_file, "PYATB input.json")
    input_parameters = _mapping(pyatb_input["INPUT_PARAMETERS"], "PYATB INPUT_PARAMETERS")
    lattice = _mapping(pyatb_input["LATTICE"], "PYATB LATTICE")
    optical_parameters = _mapping(
        pyatb_input["OPTICAL_CONDUCTIVITY"], "PYATB OPTICAL_CONDUCTIVITY"
    )
    if input_parameters["package"] != "ABACUS":
        raise ValueError("PYATB INPUT_PARAMETERS.package must be ABACUS")

    scf_task = _read_json_object(scf_dir / "task.json", "ABACUS task")
    scf_result = _read_json_object(scf_dir / "result.json", "ABACUS result")
    if scf_task["runner"] != "slurm":
        raise ValueError("ABACUS SCF runner must be slurm")
    if str(scf_task["scheduler_state"]).upper() != "COMPLETED":
        raise ValueError(f"ABACUS SCF scheduler state is not COMPLETED: {scf_task['scheduler_state']!r}")
    if scf_task["exit_code"] != "0:0":
        raise ValueError(f"ABACUS SCF exit code is not 0:0: {scf_task['exit_code']!r}")
    method = _read_json_object(scf_dir / "method.json", "ABACUS method")
    electronic = read_abacus_electronic_task(scf_dir)
    if method["basis_type"] != "lcao":
        raise ValueError("PYATB static electronic binding requires an LCAO ABACUS method")
    if method["nspin"] != 1 or method["occupations"] != "fixed":
        raise ValueError("PYATB static electronic binding requires nspin=1 fixed occupations")
    if method["net_charge"] != 0:
        raise ValueError("PYATB static electronic binding requires a neutral ABACUS SCF")
    method_identity = _native_method_identity(method, scf_dir)
    for key in ("orbital_files", "orbital_metadata"):
        value = method_identity[key]
        if not isinstance(value, (Mapping, list)) or not value:
            raise ValueError(f"ABACUS method.{key} must be a non-empty producer-provided record")
    model_context = _model_context(_text(scf_task["model_path"], "ABACUS task.model_path"))
    canonical_model = read_model_artifacts(model_context["model_path"])
    if (scf_task["model_id"], scf_task["model_version"]) != (
        model_context["model_id"], model_context["model_version"]
    ):
        raise ValueError("ABACUS task model identity differs from model_path")
    if electronic["model_id"] != model_context["model_id"] or electronic["model_version"] != model_context["model_version"]:
        raise ValueError("ABACUS electronic model identity differs from model_path")
    suffix = _text(method["suffix"], "ABACUS method.suffix")
    native_dir = (scf_dir / f"OUT.{suffix}").resolve()
    matrix_units = {"HR": "Ry", "SR": "dimensionless", "rR": "Bohr"}
    matrix_names = {
        "HR": "data-HR-sparse_SPIN0.csr",
        "SR": "data-SR-sparse_SPIN0.csr",
        "rR": "data-rR-sparse.csr",
    }
    matrices = _mapping(request["matrices"], "request.matrices")
    matrix_sources: dict[str, dict[str, Any]] = {}
    for name in ("HR", "SR", "rR"):
        spec = _mapping(matrices[name], f"request.matrices.{name}")
        source_path = Path(_text(spec["path"], f"request.matrices.{name}.path")).expanduser()
        if not source_path.is_absolute():
            raise ValueError(f"request.matrices.{name}.path must be absolute")
        source_path = source_path.resolve()
        expected = (native_dir / matrix_names[name]).resolve()
        if source_path != expected:
            raise ValueError(f"request.matrices.{name}.path is not the reference SCF native matrix")
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if source_path.stat().st_size == 0:
            raise ValueError(f"reference SCF native matrix {name} is empty")
        if spec["unit"] != matrix_units[name]:
            raise ValueError(f"request.matrices.{name}.unit must be {matrix_units[name]}")
        matrix_sources[name] = {"path": str(source_path), "unit": matrix_units[name]}
    routes = {
        "HR": input_parameters["HR_route"],
        "SR": input_parameters["SR_route"],
        "rR": input_parameters["rR_route"],
    }
    for name, route in routes.items():
        route_value = Path(_text(route, f"PYATB INPUT_PARAMETERS.{name}_route")).expanduser()
        route_path = (workdir / route_value).resolve() if not route_value.is_absolute() else route_value.resolve()
        if route_path != Path(matrix_sources[name]["path"]).resolve():
            raise ValueError(f"PYATB {name}_route is not bound to the reference SCF matrix")
    if input_parameters["nspin"] != 1:
        raise ValueError("PYATB INPUT_PARAMETERS.nspin must be 1")
    if input_parameters["HR_unit"] != "Ry":
        raise ValueError("PYATB INPUT_PARAMETERS.HR_unit must be Ry")
    if input_parameters["rR_unit"] != "Bohr":
        raise ValueError("PYATB INPUT_PARAMETERS.rR_unit must be Bohr")
    sparse_format = input_parameters["sparse_format"]
    if isinstance(sparse_format, bool) or not isinstance(sparse_format, int) or sparse_format not in (0, 1):
        raise ValueError("PYATB INPUT_PARAMETERS.sparse_format must be integer 0 or 1")
    lattice_vector = _array(lattice["lattice_vector"], (3, 3), "PYATB LATTICE.lattice_vector")
    lattice_constant = _finite_number(lattice["lattice_constant"], "PYATB LATTICE.lattice_constant")
    if lattice_constant <= 0.0:
        raise ValueError("PYATB LATTICE.lattice_constant must be positive")
    if lattice.get("lattice_constant_unit") != "Angstrom":
        raise ValueError("PYATB LATTICE.lattice_constant_unit must be Angstrom")
    lattice_cell = lattice_constant * lattice_vector
    if not np.allclose(lattice_cell, np.asarray(model_context["cell_angstrom"]), rtol=0.0, atol=_CELL_TOL):
        raise ValueError("PYATB LATTICE differs from the reference model cell")
    for parameters, label in ((input_parameters, "INPUT_PARAMETERS"), (optical_parameters, "OPTICAL_CONDUCTIVITY")):
        if "use_fermi" in parameters and parameters["use_fermi"] not in (False, 0):
            raise ValueError(f"PYATB {label}.use_fermi must be false")
    if optical_parameters["method"] != 1:
        raise ValueError("PYATB OPTICAL_CONDUCTIVITY.method must be 1")
    fermi_energy = input_parameters["fermi_energy"]
    _finite_number(fermi_energy, "PYATB INPUT_PARAMETERS.fermi_energy")
    if input_parameters["fermi_energy_unit"] != "eV":
        raise ValueError("PYATB INPUT_PARAMETERS.fermi_energy_unit must be eV")
    grid = _array(optical_parameters["grid"], (3,), "PYATB OPTICAL_CONDUCTIVITY.grid")
    if not np.all(np.equal(grid, np.floor(grid))) or np.any(grid <= 0.0):
        raise ValueError("PYATB OPTICAL_CONDUCTIVITY.grid must contain positive integers")
    minimum_gap_eV = _finite_number(request["minimum_gap_eV"], "request.minimum_gap_eV")
    if minimum_gap_eV < 0.0:
        raise ValueError("request.minimum_gap_eV must be non-negative")
    gap_evidence, unresolved_reasons = _pyatb_gap_evidence(
        electronic, input_parameters, optical_parameters, minimum_gap_eV
    )
    raw_tensor = _parse_pyatb_static_output(output_file)
    tensor = raw_tensor
    if unresolved_reasons:
        tensor = None
    parent = {
        "study_id": _text(scf_task["study_id"], "ABACUS task.study_id"),
        "model_id": model_context["model_id"],
        "model_version": model_context["model_version"],
        "model_path": model_context["model_path"],
    }
    parent_model_path = Path(parent["model_path"]).resolve()
    post_model_path = Path(_text(post.get("model_path"), "postprocess.model_path")).expanduser()
    if not post_model_path.is_absolute():
        raise ValueError("postprocess.model_path must be absolute")
    post_model_path = post_model_path.resolve()
    source_model_path: Path | None = None
    if post.get("source_model_path") is not None:
        source_model_path = Path(
            _text(post["source_model_path"], "postprocess.source_model_path")
        ).expanduser()
        if not source_model_path.is_absolute():
            raise ValueError("postprocess.source_model_path must be absolute")
        source_model_path = source_model_path.resolve()

    if post_model_path == parent_model_path:
        if source_model_path is not None and source_model_path != parent_model_path:
            raise ValueError("PYATB postprocess source_model_path differs from reference SCF")
        bound_model = canonical_model
    else:
        if source_model_path is None:
            raise ValueError(
                "PYATB postprocess copied model requires an explicit source_model_path"
            )
        if source_model_path != parent_model_path:
            raise ValueError("PYATB postprocess source_model_path differs from reference SCF")
        try:
            post_model_path.relative_to(workdir)
        except ValueError as error:
            raise ValueError("PYATB postprocess copied model must be within its workdir") from error
        copied_model = read_model_artifacts(post_model_path)
        if (copied_model.model_id, copied_model.version) != (
            canonical_model.model_id,
            canonical_model.version,
        ):
            raise ValueError("PYATB postprocess copied model identity differs from reference SCF")
        if copied_model.atom_ids != canonical_model.atom_ids:
            raise ValueError("PYATB postprocess copied model atom IDs differ from reference SCF")
        if copied_model.atoms.get_chemical_symbols() != canonical_model.atoms.get_chemical_symbols():
            raise ValueError("PYATB postprocess copied model element order differs from reference SCF")
        if list(copied_model.atoms.pbc) != list(canonical_model.atoms.pbc):
            raise ValueError("PYATB postprocess copied model periodicity differs from reference SCF")
        if not np.allclose(
            copied_model.atoms.cell.array,
            canonical_model.atoms.cell.array,
            rtol=0.0,
            atol=1.0e-8,
        ):
            raise ValueError("PYATB postprocess copied model cell differs from reference SCF")
        if not np.allclose(
            copied_model.atoms.get_positions(),
            canonical_model.atoms.get_positions(),
            rtol=0.0,
            atol=1.0e-8,
        ):
            raise ValueError("PYATB postprocess copied model structure differs from reference SCF")
        bound_model = copied_model
    _validate_model_and_stru(scf_dir, bound_model, method)
    for field in ("study_id", "model_id", "model_version"):
        if post[field] != parent[field]:
            raise ValueError(f"PYATB postprocess {field} differs from reference SCF")
    if post["reference_scf_task_id"] != scf_task["task_id"]:
        raise ValueError("PYATB postprocess reference_scf_task_id differs from SCF")
    if post["reference_scf_job_id"] != scf_task["scheduler_job_id"]:
        raise ValueError("PYATB postprocess reference_scf_job_id differs from SCF")
    scf_job = _native_job(
        role="reference_scf",
        task=scf_task,
        task_file=scf_dir / "task.json",
        engine="abacus",
        engine_version=electronic["engine_version"],
    )
    pyatb_job = _native_job(
        role="pyatb_static",
        task=post,
        task_file=post_file,
        engine="pyatb",
        engine_version=pyatb_version,
    )
    source_files = []
    for source in electronic["source_files"].values():
        source_path = Path(_text(source, "ABACUS electronic source file"))
        if not source_path.is_absolute():
            raise ValueError("ABACUS electronic source refs must be absolute")
        source_files.append(str(source_path.resolve()))
    source_files.extend(
        [
            str((scf_dir / "STRU").resolve()),
            str((scf_dir / "KPT").resolve()),
            str((scf_dir / "STRU.atom-map.json").resolve()),
            str(post_file),
            str(input_file),
            str(output_file),
            str(runtime_version_file),
            *(record["path"] for record in matrix_sources.values()),
            str(request_file),
        ]
    )
    if post_model_path != parent_model_path:
        model_sources: list[tuple[Any, Path]] = [
            (canonical_model, parent_model_path),
            (bound_model, post_model_path),
        ]
        seen_model_paths: set[Path] = set()
        for model, model_path in model_sources:
            if model_path in seen_model_paths:
                continue
            seen_model_paths.add(model_path)
            metadata = getattr(model, "metadata", {})
            structure_file = "model.extxyz"
            if isinstance(metadata, Mapping) and metadata.get("structure_file") is not None:
                structure_file = _text(metadata["structure_file"], "model.structure_file")
            for filename in ("model.json", structure_file):
                model_ref = str((model_path / filename).resolve())
                if model_ref not in source_files:
                    source_files.append(model_ref)
    postprocess_record = {
        "task_file": str(post_file),
        "task_id": pyatb_job["task_id"],
        "runner": post["runner"],
        "scheduler_job_id": pyatb_job["scheduler_job_id"],
        "scheduler_state": pyatb_job["scheduler_state"],
        "exit_code": pyatb_job["exit_code"],
        "engine": post["engine"],
        "engine_version": pyatb_version,
        "working_directory": str(workdir),
        "mode": post["mode"],
        "input_json": str(input_file),
        "output_file": str(output_file),
        "runtime_version_file": str(runtime_version_file),
    }
    if post_model_path != parent_model_path:
        postprocess_record.update(
            {
                "model_path": str(post_model_path),
                "source_model_path": str(source_model_path),
            }
        )
    return {
        "schema": PYATB_ELECTRONIC_SCHEMA,
        "provenance_kind": "native_derived",
        "source_mode": "native_source_bound",
        "kind": "epsilon_infinity_relative",
        "unit": EPSILON_UNIT,
        "parent": parent,
        "atom_ids": copy.deepcopy(model_context["atom_ids"]),
        "cell_angstrom": copy.deepcopy(model_context["cell_angstrom"]),
        "volume_A3": model_context["volume_A3"],
        "method_identity": method_identity,
        "tensor": tensor,
        "raw_tensor": raw_tensor,
        "tensor_order": ["xx", "xy", "xz", "yx", "yy", "yz", "zx", "zy", "zz"],
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "ions": "clamped",
        "frequency_definition": "direct_static_omega_zero",
        "identity_included": True,
        "minimum_gap_eV": minimum_gap_eV,
        "sampled_mesh_KS_gap_eV": gap_evidence["sampled_mesh_KS_gap_eV"],
        "gap_evidence": gap_evidence,
        "input_json": str(input_file),
        "input_json_content": copy.deepcopy(dict(pyatb_input)),
        "pyatb_input": copy.deepcopy(dict(pyatb_input)),
        "matrices": copy.deepcopy(matrix_sources),
        "matrix_sources": copy.deepcopy(matrix_sources),
        "native_jobs": [scf_job, pyatb_job],
        "native_tasks": [copy.deepcopy(scf_job), copy.deepcopy(pyatb_job)],
        "source_refs": source_files,
        "request_path": str(request_file),
        "scf_electronic": copy.deepcopy(electronic),
        "postprocess_task": postprocess_record,
        "status": "complete" if tensor is not None else "unresolved",
        "unresolved_reasons": unresolved_reasons,
        **_qualification(),
        "qualification": _qualification(),
    }


def bind_native_electronic_input(
    product: Mapping[str, Any], input_path: str | Path | None = None,
) -> dict[str, Any]:
    """Re-read the native request and sources before downstream consumption."""

    if product.get("schema") != PYATB_ELECTRONIC_SCHEMA:
        raise ValueError("native electronic schema is unsupported")
    if product.get("provenance_kind") != "native_derived":
        raise ValueError("native electronic provenance_kind must be native_derived")
    if product.get("source_mode") != "native_source_bound":
        raise ValueError("native electronic source_mode must be native_source_bound")
    declared = product["request_path"]
    declared_file = Path(_text(declared, "electronic.request_path")).expanduser()
    if not declared_file.is_absolute():
        raise ValueError("electronic.request_path must be absolute")
    declared_file = declared_file.resolve()
    if not declared_file.is_file():
        raise FileNotFoundError(f"native electronic request does not exist: {declared_file}")

    declared_source = product.get("source_path")
    if declared_source is not None:
        declared_source_path = Path(_text(declared_source, "electronic.source_path")).expanduser()
        if not declared_source_path.is_absolute():
            raise ValueError("electronic.source_path must be absolute")
        declared_source_path = declared_source_path.resolve()
    else:
        declared_source_path = None

    source_file: Path | None = None
    if input_path is not None:
        candidate = Path(input_path).expanduser().resolve()
        if candidate == declared_file:
            raise ValueError("input_path must point to a saved native electronic product")
        if declared_source_path is not None and declared_source_path != candidate:
            raise ValueError("electronic.source_path differs from the supplied input_path")
        source_file = candidate
    elif declared_source_path is not None:
        if declared_source_path == declared_file:
            raise ValueError("electronic.source_path must point to a saved native electronic product")
        source_file = declared_source_path

    product_fields = {key: value for key, value in product.items() if key != "source_path"}
    if source_file is not None:
        saved_product = _read_json_object(source_file, "native electronic product")
        if saved_product.get("schema") != PYATB_ELECTRONIC_SCHEMA:
            raise ValueError("native electronic product differs from the supplied input_path")
        saved_request = Path(
            _text(saved_product.get("request_path"), "native electronic product.request_path")
        ).expanduser()
        if not saved_request.is_absolute() or saved_request.resolve() != declared_file:
            raise ValueError("native electronic product differs from the supplied input_path")
        saved_source = saved_product.get("source_path")
        if saved_source is not None:
            saved_source_path = Path(_text(saved_source, "native electronic product.source_path")).expanduser()
            if not saved_source_path.is_absolute() or saved_source_path.resolve() != source_file:
                raise ValueError("native electronic product source_path differs from the supplied input_path")
        saved_fields = {key: value for key, value in saved_product.items() if key != "source_path"}
        if saved_fields != product_fields:
            raise ValueError("native electronic product differs from the supplied input_path")

    rebound = read_pyatb_static_electronic(declared_file)
    rebound_fields = {key: value for key, value in rebound.items() if key != "source_path"}
    if set(product_fields) != set(rebound_fields):
        raise ValueError("native electronic product fields differ from source-bound product")
    for field in sorted(rebound_fields):
        if product_fields[field] != rebound_fields[field]:
            raise ValueError(f"native electronic product differs from source-bound {field}")
    rebound["request_path"] = str(declared_file)
    if source_file is not None:
        rebound["source_path"] = str(source_file)
    return rebound


def bind_external_electronic_input(
    electronic: Mapping[str, Any], input_path: str | Path | None = None,
) -> dict[str, Any]:
    """Bind a supplied electronic tensor file without reading or qualifying it."""
    if electronic.get("provenance_kind") != "external_supplied":
        raise ValueError("electronic.provenance_kind must be external_supplied")
    mode = electronic.get("source_mode")
    if mode is not None and not (
        mode == "software_math_only"
        and electronic["method_identity"]["engine"] in {"math-fixture", "mathematical_fixture"}
    ):
        raise ValueError("external electronic source_mode cannot claim native production")
    for field in ("native_tasks", "native_jobs"):
        if electronic.get(field):
            raise ValueError(f"external electronic input cannot carry nonempty {field}")
    _non_empty_text_list(electronic["source_refs"], "electronic.source_refs")
    if input_path is None:
        path = Path(_text(electronic["source_path"], "electronic.source_path"))
        if not path.is_absolute():
            raise ValueError("electronic.source_path must be absolute without input_path")
        path = path.resolve()
    else:
        path = Path(input_path).expanduser().resolve()
        if "source_path" in electronic:
            declared = Path(_text(electronic["source_path"], "electronic.source_path")).expanduser().resolve()
            if declared != path:
                raise ValueError("electronic.source_path differs from the supplied input_path")
    if not path.is_file():
        raise FileNotFoundError(f"external electronic input file does not exist: {path}")
    bound = copy.deepcopy(dict(electronic))
    bound["source_path"] = str(path)
    return bound


def _electronic_context(electronic: Mapping[str, Any]) -> dict[str, Any]:
    parent = _mapping(electronic["parent"], "electronic.parent")
    return {
        "parent": {
            "study_id": parent["study_id"],
            "model_id": parent["model_id"],
            "model_version": parent["model_version"],
            "model_path": str(Path(parent["model_path"]).resolve()),
        },
        "atom_ids": list(electronic["atom_ids"]),
        "cell_angstrom": copy.deepcopy(electronic["cell_angstrom"]),
        "volume_A3": _finite_number(electronic["volume_A3"], "electronic.volume_A3"),
        "common_method": copy.deepcopy(dict(electronic["method_identity"])),
    }


def _electronic_tensor(electronic: Mapping[str, Any], context: Mapping[str, Any]) -> np.ndarray | None:
    electronic_context = _electronic_context(electronic)
    _validate_context_pair(context, electronic_context, "electronic")
    if electronic["kind"] != "epsilon_infinity_relative":
        raise ValueError("electronic.kind must be epsilon_infinity_relative")
    if electronic["unit"] != EPSILON_UNIT:
        raise ValueError("electronic.unit must be dimensionless")
    if electronic["electrical_boundary"] != "fixed_E_zero":
        raise ValueError("electronic.electrical_boundary must be fixed_E_zero")
    if electronic["mechanical_boundary"] != "fixed_cell":
        raise ValueError("electronic.mechanical_boundary must be fixed_cell")
    if electronic["ions"] != "clamped":
        raise ValueError("electronic.ions must be clamped")
    _non_empty_text_list(electronic["source_refs"], "electronic.source_refs")
    if electronic.get("tensor") is None:
        if electronic.get("provenance_kind") == "native_derived" and electronic.get("status") == "unresolved":
            return None
        raise ValueError("electronic.tensor is required for a complete contribution")
    return _array(electronic["tensor"], (3, 3), "electronic.tensor")


def combine_dielectric_contributions(
    born: Mapping[str, Any] | None,
    electronic: Mapping[str, Any] | None = None,
    ionic: Mapping[str, Any] | None = None,
    *,
    electronic_path: str | Path | None = None,
) -> dict[str, Any]:
    """Combine epsilon-infinity and the fixed-cell ionic increment."""

    if electronic is not None and "provenance_kind" in electronic:
        if electronic["provenance_kind"] == "native_derived":
            electronic = bind_native_electronic_input(electronic, electronic_path)
        else:
            electronic = bind_external_electronic_input(electronic, electronic_path)
    if born is None:
        if electronic is None or electronic.get("provenance_kind") != "native_derived":
            raise ValueError("Born is required unless an independent native electronic contribution is supplied")
        context = _electronic_context(electronic)
    else:
        context = _mapping(born["context"], "born.context")
    _validate_context_geometry(context, "electronic.context" if born is None else "born.context")
    electronic_provenance = None
    if electronic is not None:
        if "provenance_kind" in electronic:
            kind = "native_derived" if electronic["provenance_kind"] == "native_derived" else "external_supplied"
        else:
            if electronic["method_identity"]["engine"] not in {"math-fixture", "mathematical_fixture"}:
                raise ValueError("non-mathematical electronic input requires provenance_kind=external_supplied")
            kind = "software_math_only"
        electronic_provenance = {
            "provenance_kind": kind,
            "source_path": electronic.get("source_path"),
            "source_refs": copy.deepcopy(electronic["source_refs"]),
        }
    electronic_tensor = None if electronic is None else _electronic_tensor(electronic, context)
    epsilon_infinity = None if electronic_tensor is None else electronic_tensor.tolist()
    delta = None
    ionic_context = None
    if ionic is not None:
        if born is None:
            raise ValueError("ionic contribution requires a Born context")
        if ionic["schema"] != IONIC_SCHEMA:
            raise ValueError("ionic schema is unsupported")
        if ionic["unit"] != EPSILON_UNIT:
            raise ValueError("ionic.unit must be dimensionless")
        if ionic["electrical_boundary"] != "fixed_E_zero":
            raise ValueError("ionic.electrical_boundary must be fixed_E_zero")
        if ionic["mechanical_boundary"] != "fixed_cell":
            raise ValueError("ionic.mechanical_boundary must be fixed_cell")
        if ionic["nac"] != "not_applied":
            raise ValueError("ionic.nac must be not_applied")
        ionic_context = _mapping(ionic["context"], "ionic.context")
        _validate_context_pair(context, ionic_context, "ionic")
        raw_delta = ionic["delta_epsilon_ionic"]
        if raw_delta is not None:
            delta = _array(raw_delta, (3, 3), "ionic.delta_epsilon_ionic").tolist()
    static = None
    if epsilon_infinity is not None and delta is not None:
        static = (np.asarray(epsilon_infinity, dtype=float) + np.asarray(delta, dtype=float)).tolist()
    unresolved_reasons: list[str] = []
    if static is None:
        is_native = electronic is not None and electronic.get("provenance_kind") == "native_derived"
        if is_native:
            if epsilon_infinity is None:
                unresolved_reasons.extend(electronic.get("unresolved_reasons") or ["electronic_contribution_unresolved"])
            if delta is None:
                unresolved_reasons.append("ionic_contribution_missing")
        else:
            unresolved_reasons.append("electronic_or_ionic_contribution_missing")
    return {
        "schema": COMBINED_SCHEMA,
        "context": copy.deepcopy(dict(context)),
        "unit": EPSILON_UNIT,
        "epsilon_infinity": epsilon_infinity,
        "delta_epsilon_ionic": delta,
        "epsilon_static": static,
        "electronic": None if electronic is None else copy.deepcopy(dict(electronic)),
        "ionic": None if ionic is None else copy.deepcopy(dict(ionic)),
        "contribution_provenance": {
            "electronic": electronic_provenance,
            "ionic": None if ionic is None else {
                "provenance_kind": "derived_from_born_gamma",
                "born_source": copy.deepcopy(ionic.get("born_source")),
                "gamma_source": copy.deepcopy(ionic.get("gamma_source")),
            },
        },
        "method_comparisons": {
            "electronic": None if electronic is None or born is None else p5_method_comparison(context["common_method"], electronic["method_identity"]),
            "ionic": None if ionic_context is None else p5_method_comparison(context["common_method"], ionic_context["common_method"]),
        },
        "status": "complete" if static is not None else "unresolved",
        "unresolved_reasons": [] if static is not None else unresolved_reasons,
        **({"response_scope": copy.deepcopy(ionic["response_scope"])}
           if ionic is not None and "response_scope" in ionic else {}),
        **_qualification(),
        "qualification": _qualification(),
    }


__all__ = [
    "read_native_born_family",
    "read_native_gamma_force",
    "read_pyatb_static_electronic",
    "bind_native_electronic_input",
    "bind_external_electronic_input",
    "p5_method_identity",
    "p5_method_comparison",
    "aggregate_born_columns",
    "calculate_ionic_dielectric",
    "combine_dielectric_contributions",
]
