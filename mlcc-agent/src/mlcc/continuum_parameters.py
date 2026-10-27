"""Saved-product to SI continuum parameter conversion.

The adapter reads explicit JSON products only.  It never reruns a native
reader, fills a missing value, or grants a scientific qualification.
"""

from __future__ import annotations

import copy
import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


REQUEST_SCHEMA = "mlcc.continuum-parameter-request.v1"
PACKAGE_SCHEMA = "mlcc.continuum-parameters.v1"
TYPED_SOURCE_SCHEMA = "mlcc.continuum-property-source.v1"
P5_SCHEMA = "mlcc.p5-property-delivery.v1"
DIELECTRIC_SCHEMA = "mlcc.dielectric-response.v1"
ELASTIC_SCHEMA = "mlcc.elastic-analysis.v001"
LAMMPS_SCHEMA = "mlcc.lammps-result.v1"

VOIGT_ORDER = ("xx", "yy", "zz", "yz", "xz", "xy")
LAMMPS_VOIGT_ORDER = ("xx", "yy", "zz", "xy", "xz", "yz")
VOIGT_INDICES = ((0, 0), (1, 1), (2, 2), (1, 2), (0, 2), (0, 1))

PROPERTY_UNITS = {
    "density": "kg/m^3",
    "heat_capacity_cp": "J/(kg*K)",
    "thermal_conductivity": "W/(m*K)",
    "thermal_expansion": "1/K",
    "thermal_strain": "dimensionless",
    "elastic_stiffness": "Pa",
    "initial_stress": "Pa",
    "relative_permittivity_static": "dimensionless",
    "relative_permittivity_electronic": "dimensionless",
    "electric_conductivity": "S/m",
    "seebeck": "V/K",
    "heat_contact_conductance": "W/(m^2*K)",
    "heat_contact_resistance": "m^2*K/W",
    "interface_normal_stiffness": "Pa/m",
    "interface_tangential_stiffness": "Pa/m",
    "piezoelectric_e": "C/m^2",
}
PROPERTY_SHAPES = {
    "density": {"scalar"},
    "heat_capacity_cp": {"scalar"},
    "thermal_conductivity": {"scalar", "tensor2"},
    "thermal_expansion": {"scalar", "tensor2"},
    "thermal_strain": {"scalar", "tensor2"},
    "elastic_stiffness": {"elasticity6"},
    "initial_stress": {"tensor2"},
    "relative_permittivity_static": {"scalar", "tensor2"},
    "relative_permittivity_electronic": {"scalar", "tensor2"},
    "electric_conductivity": {"scalar", "tensor2"},
    "seebeck": {"scalar", "tensor2"},
    "heat_contact_conductance": {"scalar"},
    "heat_contact_resistance": {"scalar"},
    "interface_normal_stiffness": {"scalar"},
    "interface_tangential_stiffness": {"scalar"},
    "piezoelectric_e": {"piezoelectric3x6"},
}
DEFAULT_SHAPES = {
    "density": "scalar", "heat_capacity_cp": "scalar", "thermal_conductivity": "tensor2",
    "thermal_expansion": "tensor2", "thermal_strain": "tensor2", "elastic_stiffness": "elasticity6",
    "initial_stress": "tensor2", "relative_permittivity_static": "tensor2",
    "relative_permittivity_electronic": "tensor2", "electric_conductivity": "tensor2",
    "seebeck": "scalar", "heat_contact_conductance": "scalar", "heat_contact_resistance": "scalar",
    "interface_normal_stiffness": "scalar", "interface_tangential_stiffness": "scalar",
    "piezoelectric_e": "piezoelectric3x6",
}
PROPERTY_DEFINITIONS = {
    "density": "mass density",
    "heat_capacity_cp": "specific heat capacity at constant pressure",
    "thermal_conductivity": "thermal conductivity",
    "thermal_expansion": "thermal expansion coefficient",
    "thermal_strain": "declared thermal strain",
    "elastic_stiffness": "elastic stiffness in engineering Voigt notation",
    "initial_stress": "declared initial mechanical stress",
    "relative_permittivity_static": "static relative permittivity",
    "relative_permittivity_electronic": "electronic relative permittivity epsilon infinity",
    "electric_conductivity": "electric conductivity",
    "seebeck": "Seebeck coefficient",
    "heat_contact_conductance": "interfacial thermal conductance",
    "heat_contact_resistance": "interfacial thermal resistance",
    "interface_normal_stiffness": "normal interface stress-displacement slope",
    "interface_tangential_stiffness": "tangential interface stress-displacement slope",
    "piezoelectric_e": "stress-charge piezoelectric e tensor",
}
PROPERTY_NAMES = frozenset(PROPERTY_UNITS)
UNIT_FACTORS = {
    "density": {"kg/m^3": 1.0, "g/cm^3": 1000.0},
    "heat_capacity_cp": {"J/(kg*K)": 1.0, "J/kg/K": 1.0, "kJ/(kg*K)": 1000.0},
    "thermal_conductivity": {"W/(m*K)": 1.0, "W/m/K": 1.0},
    "thermal_expansion": {"1/K": 1.0, "K^-1": 1.0},
    "thermal_strain": {"dimensionless": 1.0},
    "elastic_stiffness": {"Pa": 1.0, "MPa": 1e6, "GPa": 1e9, "bar": 1e5, "kbar": 1e8},
    "initial_stress": {"Pa": 1.0, "MPa": 1e6, "GPa": 1e9, "bar": 1e5, "kbar": 1e8,
                       "eV/angstrom^3": 1.602176634e11},
    "relative_permittivity_static": {"dimensionless": 1.0},
    "relative_permittivity_electronic": {"dimensionless": 1.0},
    "electric_conductivity": {"S/m": 1.0},
    "seebeck": {"V/K": 1.0, "uV/K": 1e-6, "microV/K": 1e-6},
    "heat_contact_conductance": {"W/(m^2*K)": 1.0, "W/m^2/K": 1.0},
    "heat_contact_resistance": {"m^2*K/W": 1.0, "m^2 K/W": 1.0},
    "interface_normal_stiffness": {"Pa/m": 1.0, "GPa/angstrom": 1e19},
    "interface_tangential_stiffness": {"Pa/m": 1.0, "GPa/angstrom": 1e19},
    "piezoelectric_e": {"C/m^2": 1.0},
}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _array(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite array with shape {shape}") from exc
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite array with shape {shape}")
    return result


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _path(value: Any, base: Path, name: str) -> Path:
    candidate = Path(_text(value, name)).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _unique_strings(values: Sequence[Any], name: str) -> list[str]:
    result: list[str] = []
    for index, value in enumerate(values):
        item = _text(value, f"{name}[{index}]")
        if item not in result:
            result.append(item)
    return result


def _identity_from_study(study: Mapping[str, Any]) -> dict[str, Any]:
    model = study.get("model")
    if not isinstance(model, Mapping):
        model = study.get("model_refs") if isinstance(study.get("model_refs"), Mapping) else {}
    return {
        "study_id": study.get("study_id"),
        "model_id": model.get("model_id", study.get("model_id")),
        "model_version": model.get("model_version", model.get("version", study.get("model_version"))),
    }


def _check_identity(identity: Mapping[str, Any], study: Mapping[str, Any], name: str, *, required: bool = False) -> None:
    expected = _identity_from_study(study)
    if required:
        for field in ("study_id", "model_id", "model_version"):
            _text(identity.get(field), f"{name}.{field}")
            _text(expected.get(field), f"selected Study.{field}")
    for field in ("study_id", "model_id", "model_version"):
        if identity.get(field) is not None and expected.get(field) is not None and identity[field] != expected[field]:
            raise ValueError(f"{name}.{field} differs from the selected Study")


def _validate_coordinate_systems(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "coordinate_systems")
    if raw.get("source_basis") != "source_cartesian":
        raise ValueError("coordinate_systems.source_basis must be source_cartesian")
    if raw.get("target_basis") != "comsol_global_cartesian":
        raise ValueError("coordinate_systems.target_basis must be comsol_global_cartesian")
    source_to_material = _array(raw.get("source_to_material"), (3, 3), "coordinate_systems.source_to_material")
    material_to_target = _array(raw.get("material_to_target"), (3, 3), "coordinate_systems.material_to_target")
    for matrix, name in ((source_to_material, "source_to_material"), (material_to_target, "material_to_target")):
        if not np.allclose(matrix.T @ matrix, np.eye(3), rtol=0.0, atol=1e-10):
            raise ValueError(f"coordinate_systems.{name} must be an orthogonal rotation")
        if not math.isclose(float(np.linalg.det(matrix)), 1.0, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError(f"coordinate_systems.{name} must have determinant +1")
    result = copy.deepcopy(dict(raw))
    result["material_basis"] = _text(raw.get("material_basis"), "coordinate_systems.material_basis")
    result["source_to_material"] = source_to_material.tolist()
    result["material_to_target"] = material_to_target.tolist()
    result["source_to_target"] = (material_to_target @ source_to_material).tolist()
    return result


def _validate_temperatures(temperatures: Any, policy: Any, name: str) -> tuple[list[float] | None, dict[str, Any] | None]:
    if temperatures is None:
        if policy is not None:
            raise ValueError(f"{name}.temperature_policy requires temperatures_K")
        return None, None
    if isinstance(temperatures, (str, bytes)) or not isinstance(temperatures, list) or len(temperatures) < 2:
        raise ValueError(f"{name}.temperatures_K must contain at least two temperatures")
    result = [_finite(item, f"{name}.temperatures_K[{index}]") for index, item in enumerate(temperatures)]
    if any(left >= right for left, right in zip(result, result[1:])):
        raise ValueError(f"{name}.temperatures_K must be strictly ascending")
    if not isinstance(policy, Mapping) or dict(policy) != {"interpolation": "linear", "extrapolation": "none"}:
        raise ValueError(f"{name}.temperature_policy must be linear with no extrapolation")
    return result, copy.deepcopy(dict(policy))


def _shape_value(value: Any, shape: str, name: str) -> Any:
    if value is None:
        return None
    if shape == "scalar":
        return _finite(value, name)
    sizes = {"tensor2": (3, 3), "elasticity6": (6, 6), "piezoelectric3x6": (3, 6)}
    if shape not in sizes:
        raise ValueError(f"unsupported property shape: {shape}")
    return _array(value, sizes[shape], name).tolist()


def _shape_typed_value(value: Any, shape: str, temperatures: Sequence[float] | None, name: str) -> Any:
    """Validate one value or a strict ``[N] + shape`` temperature series."""
    if temperatures is None:
        return _shape_value(value, shape, name)
    if value is None or isinstance(value, (str, bytes)) or not isinstance(value, list) or len(value) != len(temperatures):
        raise ValueError(f"{name} must have one {shape} value for each temperatures_K entry")
    return [_shape_value(item, shape, f"{name}[{index}]") for index, item in enumerate(value)]


def _scale_value(value: Any, shape: str, factor: float) -> Any:
    if value is None:
        return None
    if shape == "scalar":
        return float(value) * factor
    return (np.asarray(value, dtype=float) * factor).tolist()


def _voigt_order(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise ValueError(f"{name} must be a six-name list")
    result = tuple(_text(item, f"{name}[{index}]") for index, item in enumerate(value))
    if result not in (VOIGT_ORDER, LAMMPS_VOIGT_ORDER):
        raise ValueError(f"{name} uses an unsupported Voigt order")
    return result


def _canonical_elastic(value: Any, order: Sequence[str], name: str) -> np.ndarray:
    matrix = _array(value, (6, 6), name)
    indices = [order.index(component) for component in VOIGT_ORDER]
    return matrix[np.ix_(indices, indices)]


def _elastic_to_tensor(value: np.ndarray) -> np.ndarray:
    tensor = np.zeros((3, 3, 3, 3), dtype=float)
    for row, (i, j) in enumerate(VOIGT_INDICES):
        for column, (k, l) in enumerate(VOIGT_INDICES):
            coefficient = value[row, column]
            for ii, jj in {(i, j), (j, i)}:
                for kk, ll in {(k, l), (l, k)}:
                    tensor[ii, jj, kk, ll] = coefficient
    return tensor


def _tensor_to_elastic(tensor: np.ndarray) -> list[list[float]]:
    result = np.zeros((6, 6), dtype=float)
    for row, (i, j) in enumerate(VOIGT_INDICES):
        for column, (k, l) in enumerate(VOIGT_INDICES):
            result[row, column] = tensor[i, j, k, l]
    return result.tolist()


def transform_tensor2(value: Sequence[Sequence[float]], source_to_material: Sequence[Sequence[float]], material_to_target: Sequence[Sequence[float]]) -> dict[str, list[list[float]]]:
    """Rotate a complete 3x3 tensor without symmetrizing it."""
    source = _array(value, (3, 3), "tensor2")
    source_to_material_array = _array(source_to_material, (3, 3), "source_to_material")
    material_to_target_array = _array(material_to_target, (3, 3), "material_to_target")
    material = source_to_material_array @ source @ source_to_material_array.T
    target = material_to_target_array @ material @ material_to_target_array.T
    return {"source": source.tolist(), "material": material.tolist(), "target": target.tolist()}


def transform_elastic_stiffness(value: Sequence[Sequence[float]], source_to_material: Sequence[Sequence[float]], material_to_target: Sequence[Sequence[float]], *, voigt_order: Sequence[str] = VOIGT_ORDER, engineering_shear: bool = True) -> dict[str, list[list[float]]]:
    """Rotate engineering-shear C through a fourth-order tensor."""
    if engineering_shear is not True:
        raise ValueError("elastic stiffness requires engineering_shear=true")
    order = _voigt_order(list(voigt_order), "voigt_order")
    source_matrix = _canonical_elastic(value, order, "elastic_stiffness")
    source_to_material_array = _array(source_to_material, (3, 3), "source_to_material")
    material_to_target_array = _array(material_to_target, (3, 3), "material_to_target")
    source_tensor = _elastic_to_tensor(source_matrix)
    material_tensor = np.einsum("ia,jb,kc,ld,abcd->ijkl", source_to_material_array, source_to_material_array, source_to_material_array, source_to_material_array, source_tensor)
    target_tensor = np.einsum("ia,jb,kc,ld,abcd->ijkl", material_to_target_array, material_to_target_array, material_to_target_array, material_to_target_array, material_tensor)
    return {"source": _array(value, (6, 6), "elastic_stiffness").tolist(), "material": _tensor_to_elastic(material_tensor), "target": _tensor_to_elastic(target_tensor)}


def transform_piezoelectric_e(value: Sequence[Sequence[float]], source_to_material: Sequence[Sequence[float]], material_to_target: Sequence[Sequence[float]], *, voigt_order: Sequence[str] = VOIGT_ORDER, engineering_shear: bool = True) -> dict[str, list[list[float]]]:
    """Rotate a 3x6 stress-charge piezoelectric tensor with engineering shear."""
    if engineering_shear is not True:
        raise ValueError("piezoelectric_e requires engineering_shear=true")
    order = _voigt_order(list(voigt_order), "voigt_order")
    source = _array(value, (3, 6), "piezoelectric_e")
    indices = [order.index(component) for component in VOIGT_ORDER]
    canonical = source[:, indices]
    source_tensor = np.zeros((3, 3, 3), dtype=float)
    for column, (j, k) in enumerate(VOIGT_INDICES):
        component = canonical[:, column]
        source_tensor[:, j, k] = component
        source_tensor[:, k, j] = component
    source_to_material_array = _array(source_to_material, (3, 3), "source_to_material")
    material_to_target_array = _array(material_to_target, (3, 3), "material_to_target")
    material_tensor = np.einsum("ia,jb,kc,abc->ijk", source_to_material_array, source_to_material_array, source_to_material_array, source_tensor)
    target_tensor = np.einsum("ia,jb,kc,abc->ijk", material_to_target_array, material_to_target_array, material_to_target_array, material_tensor)

    def reduce_tensor(tensor: np.ndarray) -> list[list[float]]:
        result = np.zeros((3, 6), dtype=float)
        for column, (j, k) in enumerate(VOIGT_INDICES):
            result[:, column] = tensor[:, j, k]
        return result.tolist()

    return {"source": source.tolist(), "material": reduce_tensor(material_tensor), "target": reduce_tensor(target_tensor)}


def _source_identity(source: Mapping[str, Any], schema: str) -> dict[str, Any]:
    if schema == DIELECTRIC_SCHEMA:
        parent = _mapping(_mapping(source.get("context"), "source.context").get("parent"), "source.context.parent")
        return {"study_id": parent.get("study_id"), "model_id": parent.get("model_id"), "model_version": parent.get("model_version")}
    if schema == P5_SCHEMA:
        model = source.get("model") if isinstance(source.get("model"), Mapping) else {}
        return {
            "study_id": source.get("study_id"),
            "model_id": model.get("model_id", source.get("model_id")),
            "model_version": model.get("model_version", model.get("version", source.get("model_version"))),
        }
    if schema == TYPED_SOURCE_SCHEMA:
        return {"study_id": source.get("study_id"), "model_id": source.get("model_id"), "model_version": source.get("model_version")}
    model = source.get("reference_model") if isinstance(source.get("reference_model"), Mapping) else source
    return {"study_id": source.get("study_id"), "model_id": model.get("model_id", source.get("model_id")), "model_version": model.get("model_version", model.get("version", source.get("model_version")))}


def _source_metadata(source: Mapping[str, Any], path: Path, schema: str, field: str, identity: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(source))
    metadata = copy.deepcopy(record)
    metadata["record"] = record
    qualification = source.get("qualification")
    if qualification is None:
        qualification = {key: source[key] for key in ("scientific_qualification", "numerical_qualification", "production_qualified", "production_qualification") if key in source}
        if not qualification:
            qualification = None
    native_jobs = None
    for key in ("native_jobs", "source_jobs", "native_job", "source_task"):
        if key in source:
            native_jobs = source[key]
            break
    metadata.update({
        "path": str(path),
        "schema": schema,
        "field": field,
        "identity": copy.deepcopy(dict(identity)),
        "status": source.get("status", source.get("response_status")),
        "qualification": copy.deepcopy(qualification),
        "native_jobs": copy.deepcopy(native_jobs),
        "source_files": copy.deepcopy(source.get("source_files")),
    })
    return metadata


def _reasons(source: Mapping[str, Any], name: str) -> list[str]:
    result: list[str] = []
    for key in ("missing_evidence", "unresolved_reasons", "issues", "missing_reasons"):
        value = source.get(key, [])
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValueError(f"{name}.{key} must be a list")
        result.extend(_unique_strings(value, f"{name}.{key}"))
    return result


def _field_name(entry: Mapping[str, Any]) -> str | None:
    source_field = entry.get("source_field")
    field = entry.get("field")
    if source_field is not None and field is not None and source_field != field:
        raise ValueError("property source_field and field differ")
    if source_field is None and field is None:
        return None
    return _text(source_field if source_field is not None else field, "property.source_field")


def _selection_fields(entry: Mapping[str, Any]) -> None:
    if "json_path" in entry or "jsonpath" in entry:
        raise ValueError("arbitrary JSONPath selection is not supported")
    if "selection" in entry and not isinstance(entry["selection"], Mapping):
        raise ValueError("property.selection must be an object")
    if "point_selection" in entry and not isinstance(entry["point_selection"], Mapping):
        raise ValueError("property.point_selection must be an object")


def _reject_ambiguous_field_labels(*values: Any) -> None:
    markers = ("sigma/tau", "kappa/tau", "sigma_over_tau", "kappa_over_tau", "cell_net")
    for value in values:
        if isinstance(value, str):
            label = value.lower().replace(" ", "_")
            compact = label.replace("_/_", "/")
            slash_compact = label.replace("_", "")
            if any(marker in label or marker in compact for marker in markers) or "sigma/tau" in slash_compact or "kappa/tau" in slash_compact:
                raise ValueError("continuum parameters cannot consume tau-normalized or cell-net single-interface values")


def _request_conditions(entry: Mapping[str, Any], source_conditions: Mapping[str, Any]) -> dict[str, Any]:
    declared = entry.get("conditions")
    if declared is None:
        return {}
    declared = _mapping(declared, "property.conditions")
    extras: dict[str, Any] = {}
    for key, value in declared.items():
        if key in source_conditions and source_conditions[key] != value:
            raise ValueError(f"property.conditions.{key} differs from source conditions")
        if key not in source_conditions:
            extras[key] = copy.deepcopy(value)
    return extras


def _expected_shape(name: str, entry: Mapping[str, Any], source_shape: Any = None) -> str:
    declared = entry.get("shape")
    if declared is None and source_shape is not None:
        declared = source_shape
    shape = _text(declared if declared is not None else DEFAULT_SHAPES[name], "property.shape")
    if shape not in PROPERTY_SHAPES[name]:
        raise ValueError(f"property {name} does not support shape {shape}")
    return shape


def _convert_value(value: Any, unit: str, name: str, shape: str) -> Any:
    unit = _text(unit, "source unit")
    factor = UNIT_FACTORS[name].get(unit)
    if factor is None:
        raise ValueError(f"unit {unit!r} is not valid for {name}")
    return _scale_value(_shape_value(value, shape, f"{name}.value"), shape, factor)


def _canonical_source_value(value: Any, extracted: Mapping[str, Any]) -> Any:
    shape = extracted["shape"]
    if value is None or shape not in {"elasticity6", "piezoelectric3x6"}:
        return value
    order = _voigt_order(list(extracted.get("voigt_order") or VOIGT_ORDER), "source voigt_order")
    if extracted.get("engineering_shear") is not True:
        raise ValueError(f"{shape} source requires engineering_shear=true")
    if shape == "elasticity6":
        return _canonical_elastic(value, order, "source elasticity6").tolist()
    values = _array(value, (3, 6), "source piezoelectric3x6")
    indices = [order.index(component) for component in VOIGT_ORDER]
    return values[:, indices].tolist()


def _transform_value(extracted: Mapping[str, Any], value: Any, source_to_material: np.ndarray, material_to_target: np.ndarray) -> dict[str, Any]:
    if value is None:
        return {"source": None, "material": None, "target": None}
    shape = extracted["shape"]
    if shape == "scalar":
        scalar = _finite(value, "scalar parameter")
        return {"source": scalar, "material": scalar, "target": scalar}
    if shape == "tensor2":
        return transform_tensor2(value, source_to_material, material_to_target)
    canonical = _canonical_source_value(value, extracted)
    if shape == "elasticity6":
        return transform_elastic_stiffness(canonical, source_to_material, material_to_target)
    if shape == "piezoelectric3x6":
        return transform_piezoelectric_e(canonical, source_to_material, material_to_target)
    raise ValueError(f"unsupported parameter shape: {shape}")


def _extract_typed(source: Mapping[str, Any], path: Path, entry: Mapping[str, Any], name: str, study: Mapping[str, Any], shape: str) -> dict[str, Any]:
    required = ("study_id", "model_id", "model_version", "property", "definition", "unit", "shape", "basis", "conditions", "source_refs", "native_jobs", "status", "qualification")
    for field in required:
        if field not in source:
            raise ValueError(f"typed source is missing {field}")
    identity = _source_identity(source, TYPED_SOURCE_SCHEMA)
    _check_identity(identity, study, "typed source", required=True)
    if source["property"] != name or source["shape"] != shape:
        raise ValueError("typed source property or shape differs from request")
    if source["basis"] != "source_cartesian":
        raise ValueError("typed source basis must be source_cartesian")
    entry_field = _field_name(entry)
    if entry_field not in (None, "value"):
        raise ValueError("typed source field must be value")
    if entry.get("source_unit") is not None and entry["source_unit"] != source["unit"]:
        raise ValueError("request source_unit differs from typed source unit")
    _reject_ambiguous_field_labels(source.get("definition"), entry.get("definition"), entry.get("source_field"), entry.get("field"))
    temperatures, policy = _validate_temperatures(source.get("temperatures_K"), source.get("temperature_policy"), "typed source")
    conditions = _mapping(source["conditions"], "typed source.conditions")
    if temperatures is not None and conditions.get("temperature_K") is not None:
        raise ValueError("temperature series cannot be represented by one conditions.temperature_K")
    voigt_order = None
    engineering_shear = None
    if shape in {"elasticity6", "piezoelectric3x6"}:
        voigt_order = _voigt_order(source.get("voigt_order"), "typed source.voigt_order")
        if source.get("engineering_shear") is not True:
            raise ValueError(f"typed {shape} source requires engineering_shear=true")
        engineering_shear = True
    value = _shape_typed_value(source.get("value"), shape, temperatures, "typed source.value")
    return {
        "value": value,
        "transform_value": source.get("value"),
        "unit": _text(source["unit"], "typed source.unit"), "shape": shape,
        "basis": "source_cartesian", "field": "value",
        "definition": _text(source["definition"], "typed source.definition"),
        "conditions": copy.deepcopy(dict(conditions)), "temperatures": temperatures, "temperature_policy": policy,
        "reference_state": copy.deepcopy(source.get("reference_state")),
        "identity": identity, "status": source["status"], "missing": _reasons(source, "typed source"),
        "source": _source_metadata(source, path, TYPED_SOURCE_SCHEMA, "value", identity),
        "voigt_order": voigt_order, "engineering_shear": engineering_shear,
    }


def _dielectric_field(name: str, entry: Mapping[str, Any]) -> str:
    if name == "relative_permittivity_static":
        default = "epsilon_static"
    elif name == "relative_permittivity_electronic":
        default = "epsilon_infinity"
    else:
        raise ValueError("dielectric sources support only relative permittivity")
    field = _field_name(entry) or default
    if field not in {default, f"dielectric.{default}", f"products.dielectric.{default}"}:
        raise ValueError(f"unsupported dielectric source field: {field}")
    return default


def _extract_dielectric(source: Mapping[str, Any], path: Path, entry: Mapping[str, Any], name: str, study: Mapping[str, Any], shape: str) -> dict[str, Any]:
    field = _dielectric_field(name, entry)
    schema = source.get("schema")
    product = source
    identity: dict[str, Any]
    reasons = _reasons(source, "dielectric source")
    if schema == P5_SCHEMA:
        products = _mapping(source.get("products"), "P5 products")
        product = _mapping(products.get("dielectric"), "P5 products.dielectric")
        identity = _source_identity(source, P5_SCHEMA)
        _check_identity(identity, study, "P5 delivery", required=True)
        _check_identity(_source_identity(product, DIELECTRIC_SCHEMA), study, "P5 dielectric context", required=True)
        source_field = f"products.dielectric.{field}"
        metadata_source = copy.deepcopy(dict(source))
        reasons.extend(_reasons(product, "P5 dielectric"))
    elif schema == DIELECTRIC_SCHEMA:
        identity = _source_identity(source, DIELECTRIC_SCHEMA)
        _check_identity(identity, study, "dielectric source", required=True)
        source_field, metadata_source = field, source
    else:
        raise ValueError(f"unsupported dielectric source schema: {schema}")
    if product.get("unit") != "dimensionless":
        raise ValueError("dielectric source unit must be dimensionless")
    temperatures, policy = _validate_temperatures(product.get("temperatures_K"), product.get("temperature_policy"), "dielectric source")
    raw_conditions = product.get("conditions", source.get("conditions", {}))
    if raw_conditions is None:
        raw_conditions = {}
    conditions = _mapping(raw_conditions, "dielectric conditions")
    if temperatures is not None or conditions.get("temperature_K") is not None:
        raise ValueError("static dielectric sources cannot carry a temperature series or temperature condition")
    reference_state = product.get("reference_state")
    if reference_state is None:
        reference_state = source.get("reference_state")
    metadata = _source_metadata(metadata_source, path, str(schema), source_field, identity)
    if schema == P5_SCHEMA:
        metadata["selected_product"] = copy.deepcopy(dict(product))
    return {
        "value": _shape_value(product.get(field), shape, source_field), "transform_value": product.get(field),
        "unit": "dimensionless", "shape": shape, "basis": "source_cartesian", "field": source_field,
        "definition": PROPERTY_DEFINITIONS[name],
        "conditions": copy.deepcopy(dict(conditions)),
        "reference_state": copy.deepcopy(reference_state),
        "temperatures": temperatures, "temperature_policy": policy, "identity": identity,
        "status": product.get("status", source.get("status")), "missing": reasons,
        "source": metadata,
        "voigt_order": None, "engineering_shear": None,
    }


def _reference_task_identity(source: Mapping[str, Any], path: Path) -> dict[str, Any]:
    identity = _source_identity(source, ELASTIC_SCHEMA)
    reference_task = source.get("reference_task")
    if reference_task is None:
        return identity
    candidate = Path(str(reference_task)).expanduser()
    if not candidate.is_absolute():
        candidate = path.parent / candidate
    if candidate.is_dir():
        candidate /= "task.json"
    if not candidate.is_file():
        return identity
    task = _json(candidate.resolve())
    model = task.get("model") if isinstance(task.get("model"), Mapping) else {}
    for field, value in (("study_id", task.get("study_id")), ("model_id", task.get("model_id", model.get("model_id"))), ("model_version", task.get("model_version", model.get("model_version", model.get("version"))))):
        if value is not None:
            identity[field] = value
    return identity


def _extract_elastic(source: Mapping[str, Any], path: Path, entry: Mapping[str, Any], name: str, study: Mapping[str, Any], shape: str) -> dict[str, Any]:
    if name != "elastic_stiffness":
        raise ValueError("elastic source supports only elastic_stiffness")
    field = _field_name(entry) or "Cij_GPa"
    if field != "Cij_GPa":
        raise ValueError("elastic source field must be Cij_GPa")
    identity = _reference_task_identity(source, path)
    _check_identity(identity, study, "elastic source", required=True)
    order = _voigt_order(source.get("voigt_order", list(VOIGT_ORDER)), "elastic source.voigt_order")
    if source.get("engineering_shear") is not True:
        raise ValueError("elastic source requires engineering_shear=true")
    fit = source.get("fit") if isinstance(source.get("fit"), Mapping) else {}
    raw_conditions = source.get("conditions", {})
    conditions = _mapping(raw_conditions, "elastic source.conditions")
    return {
        "value": _shape_value(source.get("Cij_GPa"), shape, "elastic source.Cij_GPa"),
        "transform_value": source.get("Cij_GPa"), "unit": "GPa", "shape": shape,
        "basis": "source_cartesian", "field": field,
        "definition": fit.get("Cij_definition", PROPERTY_DEFINITIONS[name]),
        "conditions": copy.deepcopy(dict(conditions)), "temperatures": None, "temperature_policy": None,
        "reference_state": copy.deepcopy(source.get("reference_state")),
        "identity": identity, "status": source.get("status"), "missing": _reasons(source, "elastic source"),
        "source": _source_metadata(source, path, ELASTIC_SCHEMA, field, identity),
        "voigt_order": order, "engineering_shear": True,
    }


def _extract_lammps(source: Mapping[str, Any], path: Path, entry: Mapping[str, Any], name: str, study: Mapping[str, Any], shape: str) -> dict[str, Any]:
    if name != "initial_stress":
        raise ValueError("LAMMPS stress source supports only initial_stress")
    field = _field_name(entry) or "stress_GPa"
    if field not in {"stress_GPa", "pressure_tensor_GPa"}:
        raise ValueError(f"unsupported LAMMPS stress source field: {field}")
    identity = _source_identity(source, LAMMPS_SCHEMA)
    _check_identity(identity, study, "LAMMPS source", required=True)
    if source.get("tensor_basis", "source_cartesian") != "source_cartesian":
        raise ValueError("LAMMPS stress source must be source_cartesian")
    if source.get("stress_unit") != "GPa":
        raise ValueError("LAMMPS stress source requires stress_unit=GPa")
    raw = _shape_value(source.get(field), shape, f"LAMMPS source.{field}")
    transformed = raw
    if field == "stress_GPa":
        if source.get("stress_sign") != "tension_positive":
            raise ValueError("saved LAMMPS stress_GPa must be tension_positive")
    else:
        if source.get("pressure_sign") != "compression_positive":
            raise ValueError("pressure_tensor_GPa requires compression_positive metadata")
        transformed = (-np.asarray(raw, dtype=float)).tolist() if raw is not None else None
    raw_conditions = source.get("conditions", {})
    conditions = _mapping(raw_conditions, "LAMMPS source.conditions")
    metadata = _source_metadata(source, path, LAMMPS_SCHEMA, field, identity)
    metadata["sign_conversion"] = "pressure_to_tension_negative" if field == "pressure_tensor_GPa" else "none_saved_stress_tension_positive"
    return {
        "value": raw, "transform_value": transformed, "unit": "GPa", "shape": shape,
        "basis": "source_cartesian", "field": field, "definition": "declared initial mechanical stress",
        "conditions": copy.deepcopy(dict(conditions)), "temperatures": None, "temperature_policy": None,
        "reference_state": copy.deepcopy(source.get("reference_state")),
        "identity": identity, "status": source.get("status"), "missing": _reasons(source, "LAMMPS source"),
        "source": metadata, "voigt_order": None, "engineering_shear": None,
    }


def _extract_source(source: Mapping[str, Any], path: Path, entry: Mapping[str, Any], name: str, study: Mapping[str, Any], shape: str) -> dict[str, Any]:
    schema = _text(source.get("schema"), "source.schema")
    if schema == TYPED_SOURCE_SCHEMA:
        return _extract_typed(source, path, entry, name, study, shape)
    if schema in {P5_SCHEMA, DIELECTRIC_SCHEMA}:
        return _extract_dielectric(source, path, entry, name, study, shape)
    if schema == ELASTIC_SCHEMA:
        return _extract_elastic(source, path, entry, name, study, shape)
    if schema == LAMMPS_SCHEMA:
        return _extract_lammps(source, path, entry, name, study, shape)
    raise ValueError(f"unsupported continuum property source schema: {schema}")


def _missing_parameter(entry: Mapping[str, Any], name: str, shape: str, material_state: Mapping[str, Any]) -> dict[str, Any]:
    reason = _text(entry.get("missing_reason"), f"property {name}.missing_reason")
    parameter = {
        "name": name, "definition": entry.get("definition", PROPERTY_DEFINITIONS[name]), "shape": shape,
        "value_si": None, "unit_si": PROPERTY_UNITS[name], "source_value": None,
        "source_unit": entry.get("source_unit"), "source_value_si": None, "material_value_si": None,
        "temperatures_K": copy.deepcopy(entry.get("temperatures_K")),
        "temperature_policy": copy.deepcopy(entry.get("temperature_policy")),
        "conditions": copy.deepcopy(entry.get("conditions", {})),
        "reference_state": copy.deepcopy(entry.get("reference_state", material_state.get("reference_state"))), "status": "unresolved",
        "missing_reasons": [reason],
        "source": {"record": None, "path": None, "schema": None, "field": None, "identity": None, "status": "unresolved", "qualification": None, "native_jobs": None, "source_files": None},
        "coordinate_transform": None,
    }
    for key in ("selection", "point_selection"):
        if key in entry:
            parameter[key] = copy.deepcopy(entry[key])
    return parameter


def _parameter_from_entry(entry: Mapping[str, Any], request_file: Path, study: Mapping[str, Any], material_state: Mapping[str, Any], coordinates: Mapping[str, Any]) -> dict[str, Any]:
    name = _text(entry.get("name"), "property.name")
    if name not in PROPERTY_NAMES:
        raise ValueError(f"unsupported continuum property name: {name}")
    _selection_fields(entry)
    if entry.get("source_path") is None:
        shape = _expected_shape(name, entry)
        return _missing_parameter(entry, name, shape, material_state)
    source_path = _path(entry.get("source_path"), request_file.parent, f"property {name}.source_path")
    source = _json(source_path)
    source_shape = source.get("shape") if source.get("schema") == TYPED_SOURCE_SCHEMA else None
    shape = _expected_shape(name, entry, source_shape)
    _reject_ambiguous_field_labels(entry.get("definition"), entry.get("source_field"), entry.get("field"), source.get("definition"), source.get("field"))
    extracted = _extract_source(source, source_path, entry, name, study, shape)
    if source.get("schema") in {P5_SCHEMA, DIELECTRIC_SCHEMA} and material_state.get("temperature_K") is not None:
        raise ValueError("static dielectric sources require material_state.temperature_K=null")
    if entry.get("basis") is not None and entry["basis"] != extracted["basis"]:
        raise ValueError(f"property {name}.basis differs from source")
    if extracted["basis"] != coordinates["source_basis"]:
        raise ValueError(f"property {name} source basis is not source_cartesian")
    if entry.get("source_unit") is not None and entry["source_unit"] != extracted["unit"]:
        raise ValueError(f"property {name}.source_unit differs from source")
    if entry.get("definition") is not None and entry["definition"] != extracted["definition"]:
        raise ValueError(f"property {name}.definition differs from source")
    source_temperature = extracted.get("conditions", {}).get("temperature_K")
    request_temperature = material_state.get("temperature_K")
    if source_temperature is not None and request_temperature is not None and source_temperature != request_temperature:
        raise ValueError(f"property {name} source temperature differs from material_state.temperature_K")
    source_value = extracted["value"]
    transform_value = extracted.get("transform_value", source_value)
    source_to_material = _array(coordinates["source_to_material"], (3, 3), "source_to_material")
    material_to_target = _array(coordinates["material_to_target"], (3, 3), "material_to_target")
    temperatures = extracted.get("temperatures")
    if temperatures is None:
        source_value_si = _convert_value(source_value, extracted["unit"], name, shape)
        transform_value_si = _convert_value(transform_value, extracted["unit"], name, shape)
        transformed = _transform_value(extracted, transform_value_si, source_to_material, material_to_target)
    else:
        source_value_si = [_convert_value(item, extracted["unit"], name, shape) for item in source_value]
        transform_value_si = [_convert_value(item, extracted["unit"], name, shape) for item in transform_value]
        transformed = {
            "source": source_value_si,
            "material": [_transform_value(extracted, item, source_to_material, material_to_target)["material"] for item in transform_value_si],
            "target": [_transform_value(extracted, item, source_to_material, material_to_target)["target"] for item in transform_value_si],
        }
    temperatures, policy = _validate_temperatures(extracted.get("temperatures"), extracted.get("temperature_policy"), f"property {name}")
    if entry.get("temperatures_K") is not None:
        requested_temperatures, requested_policy = _validate_temperatures(entry.get("temperatures_K"), entry.get("temperature_policy"), f"property {name} request")
        if temperatures is None:
            raise ValueError(f"property {name} request temperatures cannot annotate a single source value")
        if requested_temperatures != temperatures:
            raise ValueError(f"property {name} temperatures differ from source")
        temperatures, policy = requested_temperatures, requested_policy
    reasons = list(dict.fromkeys(_unique_strings(extracted.get("missing", []), f"property {name}.missing_reasons")))
    if transformed["target"] is None and not reasons:
        reasons = ["selected source value is null"]
    if entry.get("missing_reason") is not None:
        reasons.extend(_unique_strings([entry["missing_reason"]], f"property {name}.missing_reason"))
    status = "available" if transformed["target"] is not None else "unresolved"
    source_reference_state = extracted.get("reference_state")
    entry_reference_state = entry.get("reference_state")
    if source_reference_state is not None:
        if entry_reference_state is not None and entry_reference_state != source_reference_state:
            raise ValueError(f"property {name}.reference_state differs from saved source reference_state")
        reference_state = copy.deepcopy(source_reference_state)
    else:
        reference_state = copy.deepcopy(entry_reference_state if entry_reference_state is not None else material_state.get("reference_state"))
    parameter = {
        "name": name, "definition": extracted["definition"], "shape": shape,
        "value_si": transformed["target"], "unit_si": PROPERTY_UNITS[name],
        "source_value": copy.deepcopy(source_value), "source_unit": extracted["unit"],
        "source_value_si": source_value_si, "material_value_si": transformed["material"],
        "temperatures_K": temperatures, "temperature_policy": policy,
        "conditions": copy.deepcopy(dict(extracted.get("conditions", {}))),
        "reference_state": reference_state,
        "status": status, "missing_reasons": list(dict.fromkeys(reasons)),
        "source": copy.deepcopy(extracted["source"]),
        "coordinate_transform": {
            "source_basis": coordinates["source_basis"], "material_basis": coordinates["material_basis"], "target_basis": coordinates["target_basis"],
            "source_to_material": copy.deepcopy(coordinates["source_to_material"]), "material_to_target": copy.deepcopy(coordinates["material_to_target"]),
            "source_to_target": copy.deepcopy(coordinates["source_to_target"]),
            "rule": "full tensor rotation before engineering-Voigt reduction",
        },
    }
    for key in ("selection", "point_selection"):
        if key in entry:
            parameter[key] = copy.deepcopy(entry[key])
    request_conditions = _request_conditions(entry, extracted.get("conditions", {}))
    if request_conditions:
        parameter["request_conditions"] = request_conditions
    if shape in {"elasticity6", "piezoelectric3x6"}:
        parameter.update({"source_voigt_order": list(extracted.get("voigt_order") or VOIGT_ORDER), "material_voigt_order": list(VOIGT_ORDER), "target_voigt_order": list(VOIGT_ORDER), "engineering_shear": True})
    return parameter


def build_continuum_parameter_package(request_path: str | Path) -> dict[str, Any]:
    """Read explicit sources into SI; temperature series are ``value_si=[N]+shape``."""
    request_file = Path(request_path).expanduser().resolve()
    request = _json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    package_id = _text(request.get("package_id"), "package_id")
    study_file = _path(request.get("study_path"), request_file.parent, "study_path")
    study = _json(study_file)
    _check_identity(_identity_from_study(study), study, "selected Study", required=True)
    material_state = _mapping(request.get("material_state"), "material_state")
    for field in ("state_id", "phase", "composition", "temperature_K", "mechanical_boundary", "reference_state", "history"):
        if field not in material_state:
            raise ValueError(f"material_state is missing {field}")
    _text(material_state["state_id"], "material_state.state_id")
    _text(material_state["phase"], "material_state.phase")
    if not isinstance(material_state["composition"], Mapping):
        raise ValueError("material_state.composition must be an object")
    if material_state["temperature_K"] is not None:
        _finite(material_state["temperature_K"], "material_state.temperature_K")
    coordinates = _validate_coordinate_systems(request.get("coordinate_systems"))
    properties = request.get("properties")
    if isinstance(properties, (str, bytes)) or not isinstance(properties, list) or not properties:
        raise ValueError("properties must be a non-empty list")
    if "permittivity_property" in request:
        raise ValueError("top-level permittivity_property is unsupported; use comsol.permittivity_property")
    names: list[str] = []
    for entry in properties:
        item = _mapping(entry, "property")
        name = _text(item.get("name"), "property.name")
        if name in names:
            raise ValueError(f"duplicate property name: {name}")
        names.append(name)
    comsol = request.get("comsol")
    if comsol is not None and not isinstance(comsol, Mapping):
        raise ValueError("comsol must be an object when provided")
    if isinstance(comsol, Mapping) and "permittivity_property" in comsol:
        if comsol["permittivity_property"] not in {"relative_permittivity_static", "relative_permittivity_electronic"}:
            raise ValueError("comsol.permittivity_property must name a relative_permittivity property")
    parameters: dict[str, Any] = {}
    for entry in properties:
        item = _mapping(entry, "property")
        parameter = _parameter_from_entry(item, request_file, study, material_state, coordinates)
        parameters[parameter["name"]] = parameter
    available = sum(parameter["status"] == "available" for parameter in parameters.values())
    status = "complete" if available == len(parameters) else "unresolved" if available == 0 else "partial"
    return {
        "schema": PACKAGE_SCHEMA, "package_id": package_id, "request_path": str(request_file), "study_path": str(study_file),
        "study": copy.deepcopy(study), "material_state": copy.deepcopy(dict(material_state)), "coordinate_systems": coordinates,
        "comsol": None if comsol is None else copy.deepcopy(dict(comsol)),
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "status": status, "parameters": parameters,
    }


__all__ = ["DIELECTRIC_SCHEMA", "ELASTIC_SCHEMA", "LAMMPS_SCHEMA", "PACKAGE_SCHEMA", "P5_SCHEMA", "REQUEST_SCHEMA", "TYPED_SOURCE_SCHEMA", "build_continuum_parameter_package", "transform_elastic_stiffness", "transform_piezoelectric_e", "transform_tensor2"]
