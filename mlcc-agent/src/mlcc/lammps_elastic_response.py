"""Consume saved LAMMPS static stress results into a Cij domain product."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .domain_parameters import domain_parameter_product
from .elastic import VOIGT_INDICES, VOIGT_ORDER, _fit_cij

REQUEST_SCHEMA = "mlcc.lammps-elastic-response-request.v1"
RESULT_SCHEMA = "mlcc.lammps-result.v1"
DOMAIN_KIND = "lammps_elastic_response"


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object and preserve ordinary file/JSON errors."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON record must be an object: {path}")
    return value


def _reference_path(value: Any, request_file: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = request_file.parent / path
    return path.resolve()


def _vector(value: Any, field: str) -> np.ndarray:
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise ValueError(f"{field} must contain six Voigt components")
    try:
        converted = np.asarray([float(item) for item in value], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain finite numeric components") from exc
    if not np.isfinite(converted).all():
        raise ValueError(f"{field} must contain finite numeric components")
    return converted


def _stress_voigt(result: Mapping[str, Any], role: str) -> tuple[np.ndarray, np.ndarray]:
    """Return raw source-Cartesian stress and the requested Voigt view."""

    if result.get("schema") != RESULT_SCHEMA:
        raise ValueError(f"{role} result schema must be {RESULT_SCHEMA}")
    for field in ("stress_GPa", "stress_unit", "stress_sign", "tensor_basis"):
        if field not in result:
            raise ValueError(f"{role} result is missing {field}")
    matrix = np.asarray(result["stress_GPa"], dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError(f"{role} result stress_GPa must be a finite 3x3 matrix")
    if result["stress_unit"] != "GPa":
        raise ValueError(f"{role} result stress_unit must be GPa")
    if result["stress_sign"] != "tension_positive":
        raise ValueError(f"{role} result stress_sign must be tension_positive")
    if result["tensor_basis"] != "source_cartesian":
        raise ValueError(f"{role} result tensor_basis must be source_cartesian")
    voigt = np.asarray([matrix[i, j] for i, j in VOIGT_INDICES], dtype=float)
    return matrix, voigt


def _result_source(
    result_ref: Mapping[str, Any],
    result_path: Path,
    result: Mapping[str, Any],
    *,
    role: str,
    root_model: Mapping[str, Any],
    root_study: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep native job/source identity without reopening native files."""

    if not isinstance(result_ref.get("task_path"), str) or not result_ref["task_path"].strip():
        raise ValueError(f"{role} request entry requires task_path")
    required = (
        "task_id", "scheduler_job_id", "scheduler_state", "exit_code",
        "model_id", "version", "study_id", "case_id",
    )
    for field in required:
        if field not in result:
            raise ValueError(f"{role} result is missing {field}")
    result_model = (result["model_id"], result["version"])
    root_model_identity = (root_model["model_id"], root_model["version"])
    parent_model = result.get("parent_model")
    if result_model != root_model_identity:
        parent_models = parent_model.get("parent_models") if isinstance(parent_model, Mapping) else None
        parent_bound = isinstance(parent_models, list) and any(
            isinstance(parent, Mapping)
            and (parent.get("model_id"), parent.get("version")) == root_model_identity
            for parent in parent_models
        )
        if not parent_bound:
            raise ValueError(f"{role} child result is not bound to root model")
    if result["case_id"] != root_study["case_id"]:
        raise ValueError(f"{role} result case identity differs from root Study")
    if result_model == root_model_identity and result["study_id"] != root_study["study_id"]:
        raise ValueError(f"{role} root-model result Study identity differs from root Study")
    return {
        "role": role,
        "task_path": str(result_ref["task_path"]),
        "result_path": str(result_path),
        "task_id": result["task_id"],
        "scheduler_job_id": result["scheduler_job_id"],
        "scheduler_state": result["scheduler_state"],
        "exit_code": result["exit_code"],
        "scientific_status": result.get("scientific_status"),
        "production_qualification": result.get("production_qualification"),
        "method_set": result.get("method_set"),
        "protocol": copy.deepcopy(result.get("protocol")),
        "model_id": result["model_id"],
        "model_version": result["version"],
        "study_id": result["study_id"],
        "case_id": result["case_id"],
        "parent_model": copy.deepcopy(parent_model),
        "root_model": copy.deepcopy(dict(root_model)),
        "root_study": copy.deepcopy(dict(root_study)),
        "source_files": copy.deepcopy(result.get("source_files")),
    }


def _validate_request_shape(
    request: Mapping[str, Any],
) -> tuple[np.ndarray, list[dict[str, Any]], float]:
    reference = request.get("reference")
    samples = request.get("samples")
    if not isinstance(reference, Mapping):
        raise ValueError("elastic response request requires reference")
    if not isinstance(samples, list) or len(samples) != 12:
        raise ValueError("elastic response request requires twelve sample points")
    reference_strain = _vector(reference.get("strain_voigt"), "reference.strain_voigt")
    if not np.allclose(reference_strain, np.zeros(6), rtol=0.0, atol=0.0):
        raise ValueError("reference.strain_voigt must be the zero vector")

    seen: set[tuple[int, int]] = set()
    normalized: list[dict[str, Any]] = []
    amplitude: float | None = None
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            raise ValueError(f"samples[{index}] must be an object")
        strain = _vector(sample.get("strain_voigt"), f"samples[{index}].strain_voigt")
        nonzero = np.flatnonzero(np.abs(strain) > 0.0)
        if len(nonzero) != 1:
            raise ValueError(f"samples[{index}] must contain one non-zero Voigt component")
        direction = int(nonzero[0])
        sample_amplitude = abs(float(strain[direction]))
        if amplitude is None:
            amplitude = sample_amplitude
        elif not np.isclose(sample_amplitude, amplitude, rtol=1.0e-12, atol=1.0e-15):
            raise ValueError("samples must use one shared non-zero strain amplitude")
        sign = 1 if strain[direction] > 0.0 else -1
        key = (direction, sign)
        if key in seen:
            raise ValueError(f"samples repeat {VOIGT_ORDER[direction]} sign {sign:+d}")
        seen.add(key)
        normalized.append({"entry": dict(sample), "strain": strain, "direction": direction, "sign": sign})
    expected = {(direction, sign) for direction in range(6) for sign in (-1, 1)}
    if seen != expected:
        raise ValueError("samples must contain one minus and one plus point for every Voigt direction")
    if amplitude is None or not np.isfinite(amplitude) or amplitude <= 0.0:
        raise ValueError("samples must contain one shared positive strain amplitude")
    return reference_strain, normalized, amplitude


def _source_refs(
    request_file: Path,
    study_path: Path,
    model_path: Path,
    sources: Sequence[Mapping[str, Any]],
) -> list[str]:
    values = [str(request_file), str(study_path), str(model_path)]
    for source in sources:
        values.extend([str(source["task_path"]), str(source["result_path"])])
        files = source.get("source_files")
        if isinstance(files, Mapping):
            atom_map = files.get("atom-map.json")
            if isinstance(atom_map, str) and atom_map:
                values.append(atom_map)
    return list(dict.fromkeys(values))


def build_lammps_elastic_response(request_path: str | Path) -> dict[str, Any]:
    """Build the J3 domain product from one saved 13-point result set."""

    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    study_path = _reference_path(request.get("study_path"), request_file, "study_path")
    model_path = _reference_path(request.get("model_path"), request_file, "model_path")
    study = _read_json(study_path)
    study_model = study.get("model")
    if not isinstance(study_model, Mapping):
        raise ValueError("root Study model must be an object")
    for field in ("study_id", "case_id"):
        if not isinstance(study.get(field), str) or not study[field].strip():
            raise ValueError(f"root Study requires {field}")
    for field in ("model_id", "version"):
        if not isinstance(study_model.get(field), str) or not study_model[field].strip():
            raise ValueError(f"root Study model requires {field}")

    model_file = model_path / "model.json"
    model_record = _read_json(model_file)
    root_model = {
        "model_id": str(study_model["model_id"]),
        "version": str(study_model["version"]),
        "path": str(model_path),
    }
    if (model_record.get("model_id"), model_record.get("version")) != (
        root_model["model_id"], root_model["version"],
    ):
        raise ValueError("root model.json identity differs from root Study")
    root_study = {
        "study_id": str(study["study_id"]),
        "case_id": str(study["case_id"]),
        "case_role": study.get("case_role"),
        "path": str(study_path),
    }

    reference_ref = request.get("reference")
    if not isinstance(reference_ref, Mapping):
        raise ValueError("elastic response request requires reference")
    _reference_strain, sample_records, strain_amplitude = _validate_request_shape(request)
    reference_result_path = _reference_path(reference_ref.get("result_path"), request_file, "reference.result_path")
    reference_result = _read_json(reference_result_path)
    reference_matrix, reference_stress = _stress_voigt(reference_result, "reference")
    reference_source = _result_source(
        reference_ref, reference_result_path, reference_result,
        role="reference", root_model=root_model, root_study=root_study,
    )

    strain_rows: list[list[float]] = []
    stress_rows: list[list[float]] = []
    sample_sources: list[dict[str, Any]] = []
    sample_by_key = {(entry["direction"], entry["sign"]): entry for entry in sample_records}
    for direction in range(6):
        for sign in (-1, 1):
            entry = sample_by_key[(direction, sign)]
            sample_ref = entry["entry"]
            result_path = _reference_path(
                sample_ref.get("result_path"), request_file,
                f"samples[{direction},{sign:+d}].result_path",
            )
            result = _read_json(result_path)
            _matrix, sample_stress = _stress_voigt(result, f"sample {VOIGT_ORDER[direction]} {sign:+d}")
            source = _result_source(
                sample_ref, result_path, result,
                role=f"sample:{VOIGT_ORDER[direction]}:{sign:+d}",
                root_model=root_model, root_study=root_study,
            )
            sample_sources.append(source)
            strain_rows.append(entry["strain"].tolist())
            stress_rows.append((sample_stress - reference_stress).tolist())

    cij, predicted, residual, condition_number = _fit_cij(strain_rows, stress_rows)
    sources = [reference_source, *sample_sources]
    source_refs = _source_refs(request_file, study_path, model_path, sources)
    atom_mapping_ref = None
    reference_files = reference_source.get("source_files")
    if isinstance(reference_files, Mapping):
        atom_mapping_ref = reference_files.get("atom-map.json")
    native_jobs = [
        {
            "role": source["role"], "task_id": source["task_id"],
            "scheduler_job_id": source["scheduler_job_id"],
            "scheduler_state": source["scheduler_state"],
            "exit_code": source["exit_code"],
            "scientific_status": source["scientific_status"],
        }
        for source in sources
    ]
    conditions = {
        "mechanical_constraint": "clamped-ion_fixed-fractional_static",
        "ionic_relaxation": "not_performed",
        "calculation": "static",
        "native_protocol_kind": "run0",
        "native_static_tensor": True,
        "time_integration": "none",
        "temperature_K": None,
        "strain_amplitude": strain_amplitude,
        "strain_amplitude_unit": "dimensionless",
        "engineering_shear": True,
        "voigt_order": list(VOIGT_ORDER),
        "stress_basis": "source_cartesian",
        "stress_unit": "GPa",
        "stress_sign": "tension_positive",
        "reference_stress_GPa": reference_matrix.tolist(),
        "sample_stress_delta_GPa": copy.deepcopy(stress_rows),
        "predicted_stress_delta_GPa": predicted.tolist(),
        "residual_GPa": residual.tolist(),
        "fit_condition_number": condition_number,
        "native_sources": copy.deepcopy(sources),
        "native_jobs": native_jobs,
        "scientific_status": "engineering_static_finite_difference_not_material_qualification",
        "production_qualification": False,
    }
    properties = [
        {
            "name": "elastic_stiffness_tensor",
            "value": cij.tolist(),
            "unit": "GPa",
            "shape": [6, 6],
            "definition": "raw finite-difference source-Cartesian stress response to one fixed-fractional clamped-ion engineering-Voigt strain amplitude",
            "conditions": conditions,
            "coordinates": {
                "basis": "source_cartesian",
                "voigt_order": list(VOIGT_ORDER),
                "shear_convention": "engineering",
            },
            "atom_mapping_ref": atom_mapping_ref,
            "source_refs": source_refs,
            "status": "available",
        },
        {
            "name": "reference_stress_tensor",
            "value": reference_matrix.tolist(),
            "unit": "GPa",
            "shape": [3, 3],
            "definition": "saved reference LAMMPS virial-only stress before subtracting the reference from each strained sample",
            "conditions": {
                "basis": "source_cartesian",
                "stress_sign": "tension_positive",
                "stress_unit": "GPa",
                "mechanical_constraint": "clamped-ion_fixed-fractional_static",
                "calculation": "static",
                "native_protocol_kind": "run0",
                "native_static_tensor": True,
                "time_integration": "none",
                "native_source": copy.deepcopy(reference_source),
                "production_qualification": False,
            },
            "coordinates": {"basis": "source_cartesian"},
            "atom_mapping_ref": atom_mapping_ref,
            "source_refs": source_refs,
            "status": "available",
        },
    ]
    return domain_parameter_product(
        kind=DOMAIN_KIND,
        model=root_model,
        study=root_study,
        properties=properties,
        execution={
            "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
            "native_jobs": native_jobs,
            "request_path": str(request_file),
            "source_result_count": len(sources),
        },
    )


__all__ = ["DOMAIN_KIND", "REQUEST_SCHEMA", "RESULT_SCHEMA", "build_lammps_elastic_response"]
