"""Export a C1 continuum-parameter package as a COMSOL material template.

This module is deliberately a file-only adapter.  The C1 package is the source
of truth: ``value_si`` is already expressed in the requested global Cartesian
frame, so this exporter does not rotate tensors, change signs, or derive any
material property.  A generated Java file is an import template only; it does
not create a study, solve a model, or save an MPH file.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


PACKAGE_SCHEMA = "mlcc.continuum-parameters.v1"
MANIFEST_SCHEMA = "mlcc.comsol-export-manifest.v1"

PROPERTY_NAMES = (
    "density",
    "heat_capacity_cp",
    "thermal_conductivity",
    "thermal_expansion",
    "thermal_strain",
    "elastic_stiffness",
    "initial_stress",
    "relative_permittivity_static",
    "relative_permittivity_electronic",
    "electric_conductivity",
    "seebeck",
    "heat_contact_conductance",
    "heat_contact_resistance",
    "interface_normal_stiffness",
    "interface_tangential_stiffness",
    "piezoelectric_e",
)

_SHAPES = {"scalar", "tensor2", "elasticity6", "piezoelectric3x6"}
_VOIGT_LABELS = ("xx", "yy", "zz", "yz", "xz", "xy")
_CARTESIAN_LABELS = ("x", "y", "z")
_BASIC_COMSOL_PROPERTIES = {
    "density": "density",
    "heat_capacity_cp": "heatcapacity",
    "thermal_conductivity": "thermalconductivity",
    "thermal_expansion": "thermalexpansioncoefficient",
    "relative_permittivity_static": "relpermittivity",
    "relative_permittivity_electronic": "relpermittivity",
    "electric_conductivity": "electricconductivity",
    "seebeck": "seebeckcoefficient",
}
_ELASTIC_GROUP_TAG = "AnisotropicVoGrp"
_ELASTIC_GROUP_DESCRIPTION = "Anisotropic, Voigt notation"
_ELASTIC_PROPERTY_TAG = "DVo"
_EXPECTED_UNITS = {
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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _shape_matches(value: Any, shape: str) -> bool:
    if shape == "scalar":
        return _is_number(value)
    if shape == "tensor2":
        return (
            isinstance(value, Sequence)
            and len(value) == 3
            and all(isinstance(row, Sequence) and len(row) == 3 for row in value)
            and all(_is_number(item) for row in value for item in row)
        )
    if shape == "elasticity6":
        return (
            isinstance(value, Sequence)
            and len(value) == 6
            and all(isinstance(row, Sequence) and len(row) == 6 for row in value)
            and all(_is_number(item) for row in value for item in row)
        )
    if shape == "piezoelectric3x6":
        return (
            isinstance(value, Sequence)
            and len(value) == 3
            and all(isinstance(row, Sequence) and len(row) == 6 for row in value)
            and all(_is_number(item) for row in value for item in row)
        )
    return False


def _temperature_values(entry: Mapping[str, Any], shape: str, temperatures: Sequence[float] | None) -> list[Any] | None:
    """Return a C1 ``[N]+shape`` temperature series, if present."""

    if temperatures is None or len(temperatures) < 2:
        return None
    candidate = entry.get("value_si")
    if (
        isinstance(candidate, Sequence)
        and not isinstance(candidate, (str, bytes, bytearray))
        and len(candidate) == len(temperatures)
        and all(_shape_matches(item, shape) for item in candidate)
    ):
        return list(candidate)
    return None


def _component_values(shape: str, value: Any) -> list[tuple[str, Any]]:
    if value is None:
        return [("unresolved", None)]
    if shape == "scalar":
        return [("scalar", value)]
    if shape == "tensor2":
        labels = ("xx", "xy", "xz", "yx", "yy", "yz", "zx", "zy", "zz")
        return [(label, value[row][column]) for label, (row, column) in zip(labels, ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)))]
    if shape == "elasticity6":
        return [
            (f"{row_label},{column_label}", value[row][column])
            for row, row_label in enumerate(_VOIGT_LABELS)
            for column, column_label in enumerate(_VOIGT_LABELS)
        ]
    if shape == "piezoelectric3x6":
        return [
            (f"{row_label},{column_label}", value[row][column])
            for row, row_label in enumerate(_CARTESIAN_LABELS)
            for column, column_label in enumerate(_VOIGT_LABELS)
        ]
    return [("unresolved", None)]


def _extract_rotation(coordinate_systems: Mapping[str, Any]) -> Any:
    return coordinate_systems.get("source_to_target")


def _validate_temperatures(entry_name: str, entry: Mapping[str, Any]) -> list[float] | None:
    temperatures = entry.get("temperatures_K")
    if temperatures is None:
        if entry.get("temperature_policy") is not None:
            raise ValueError(f"{entry_name}.temperature_policy requires temperatures_K")
        return None
    if not isinstance(temperatures, list) or len(temperatures) < 2:
        raise ValueError(f"{entry_name}.temperatures_K must contain at least two temperatures or be null")
    values = [float(value) if _is_number(value) else None for value in temperatures]
    if any(value is None for value in values):
        raise ValueError(f"{entry_name}.temperatures_K must contain finite numbers")
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ValueError(f"{entry_name}.temperatures_K must be strictly ascending")
    policy = entry.get("temperature_policy")
    if len(values) >= 2:
        if not isinstance(policy, Mapping) or dict(policy) != {"interpolation": "linear", "extrapolation": "none"}:
            raise ValueError(f"{entry_name}.temperature_policy must be linear/none for a series")
    return values


def _validate_package(package: Mapping[str, Any]) -> dict[str, Any]:
    if package.get("schema") != PACKAGE_SCHEMA:
        raise ValueError(f"package schema must be {PACKAGE_SCHEMA}")
    for key in ("package_id", "study", "material_state", "coordinate_systems", "status", "parameters"):
        if key not in package:
            raise ValueError(f"package is missing required field {key}")
    if not isinstance(package["study"], Mapping) or not package["study"]:
        raise ValueError("study must be a complete non-empty object")
    if not isinstance(package["material_state"], Mapping):
        raise ValueError("material_state must be an object")
    coordinates = package["coordinate_systems"]
    if not isinstance(coordinates, Mapping) or coordinates.get("target_basis") != "comsol_global_cartesian":
        raise ValueError("coordinate_systems.target_basis must be comsol_global_cartesian")
    rotation = _extract_rotation(coordinates)
    if not _shape_matches(rotation, "tensor2"):
        raise ValueError("coordinate_systems must retain a complete 3x3 Q matrix")
    if package["status"] not in {"complete", "partial", "unresolved"}:
        raise ValueError("package status must be complete, partial, or unresolved")
    parameters = package["parameters"]
    if not isinstance(parameters, Mapping):
        raise ValueError("parameters must be an object keyed by property name")
    for name, entry in parameters.items():
        if not isinstance(name, str) or not isinstance(entry, Mapping):
            raise ValueError("each parameter must be an object keyed by name")
        if entry.get("name", name) != name:
            raise ValueError(f"parameter {name} has a mismatched name")
        shape = entry.get("shape")
        if shape not in _SHAPES:
            raise ValueError(f"{name}.shape must be one of {sorted(_SHAPES)}")
        status = entry.get("status")
        if status not in {"available", "unresolved"}:
            raise ValueError(f"{name}.status must be available or unresolved")
        if "missing_reasons" in entry and not isinstance(entry["missing_reasons"], list):
            raise ValueError(f"{name}.missing_reasons must be a list")
        temperatures = _validate_temperatures(name, entry)
        series = _temperature_values(entry, shape, temperatures)
        value = entry.get("value_si")
        if value is not None and series is None and not _shape_matches(value, shape):
            raise ValueError(f"{name}.value_si does not match {shape}")
        if series is not None:
            for index, item in enumerate(series):
                if not _shape_matches(item, shape):
                    raise ValueError(f"{name} temperature value {index} does not match {shape}")
        if status == "available" and value is None and series is None:
            raise ValueError(f"available parameter {name} has no value_si or temperature series")
        if name in _EXPECTED_UNITS and entry.get("unit_si") not in {None, _EXPECTED_UNITS[name]}:
            raise ValueError(f"{name}.unit_si must be {_EXPECTED_UNITS[name]}")
        source = entry.get("source", {})
        if source is not None and not isinstance(source, Mapping):
            raise ValueError(f"{name}.source must be an object")
    return dict(package)


def _selected_permittivity(package: Mapping[str, Any], parameters: Mapping[str, Any]) -> str | None:
    static_present = "relative_permittivity_static" in parameters
    electronic_present = "relative_permittivity_electronic" in parameters
    static = parameters.get("relative_permittivity_static")
    electronic = parameters.get("relative_permittivity_electronic")
    static_available = bool(static and static.get("status") == "available" and (static.get("value_si") is not None or _temperature_values(static, static.get("shape"), static.get("temperatures_K"))))
    electronic_available = bool(electronic and electronic.get("status") == "available" and (electronic.get("value_si") is not None or _temperature_values(electronic, electronic.get("shape"), electronic.get("temperatures_K"))))
    requested = None
    comsol = package.get("comsol")
    if comsol is not None:
        if not isinstance(comsol, Mapping):
            raise ValueError("comsol must be an object when provided")
        requested = comsol.get("permittivity_property")
        if requested is not None and requested not in {"relative_permittivity_static", "relative_permittivity_electronic"}:
            raise ValueError("comsol.permittivity_property is not a supported full property name")
    if requested is not None:
        if requested not in parameters:
            raise ValueError(f"selected permittivity property {requested} is not present")
        return requested
    if static_present and electronic_present:
        if static_available and electronic_available:
            raise ValueError("both permittivity properties are available; set comsol.permittivity_property explicitly")
        if electronic_available and not static_available:
            # Keep both fields visible and leave the choice unresolved.  A
            # partial package must not silently promote epsilon-infinity to a
            # static dielectric value; callers may opt in explicitly through
            # comsol.permittivity_property.
            return None
        if static_available:
            return "relative_permittivity_static"
        return None
    if static_present and static_available:
        return "relative_permittivity_static"
    if electronic_present and electronic_available:
        return "relative_permittivity_electronic"
    return None


def _is_available(entry: Mapping[str, Any]) -> bool:
    if entry.get("status") != "available":
        return False
    temperatures = entry.get("temperatures_K")
    return entry.get("value_si") is not None or _temperature_values(entry, entry.get("shape"), temperatures) is not None


def _thermal_expansion_reference(entry: Mapping[str, Any]) -> tuple[float | None, str | None]:
    conditions = entry.get("conditions")
    if not isinstance(conditions, Mapping) or conditions.get("thermal_expansion_form") != "secant":
        return None, "thermal_expansion requires conditions.thermal_expansion_form=secant"
    reference_state = entry.get("reference_state")
    if not isinstance(reference_state, Mapping) or not _is_number(reference_state.get("stress_free_temperature_K")):
        return None, "thermal_expansion requires finite reference_state.stress_free_temperature_K"
    return float(reference_state["stress_free_temperature_K"]), None


def _mapping_for(name: str, entry: Mapping[str, Any], selected_permittivity: str | None) -> dict[str, Any]:
    target = _BASIC_COMSOL_PROPERTIES.get(name)
    if name == "elastic_stiffness":
        target = _ELASTIC_PROPERTY_TAG
    result: dict[str, Any] = {"status": "pending", "target": target, "reason": "", "java": False}
    if name in {"relative_permittivity_static", "relative_permittivity_electronic"} and selected_permittivity != name:
        if _is_available(entry):
            result["reason"] = "not selected as the explicit COMSOL permittivity property"
        else:
            reasons = entry.get("missing_reasons") or ["parameter is unresolved"]
            result["reason"] = "unresolved: " + "; ".join(str(reason) for reason in reasons)
        return result
    if not _is_available(entry):
        reasons = entry.get("missing_reasons") or ["parameter is unresolved"]
        result["reason"] = "unresolved: " + "; ".join(str(reason) for reason in reasons)
        return result
    if name == "thermal_expansion":
        reference_temperature, reason = _thermal_expansion_reference(entry)
        if reason is not None:
            result["reason"] = reason
            return result
        result["reference_temperature_K"] = reference_temperature
    if name == "elastic_stiffness":
        if entry["shape"] != "elasticity6":
            result["reason"] = "elastic_stiffness must use the complete elasticity6 shape"
            return result
        temperatures = entry.get("temperatures_K")
        series = _temperature_values(entry, entry["shape"], temperatures)
        if temperatures is not None and len(temperatures) >= 2 and series is None:
            result["reason"] = "temperature series values are missing; no representative value is extrapolated"
            return result
        if entry.get("unit_si") in {None, ""}:
            result["reason"] = "unit_si is missing"
            return result
        result.update(
            {
                "status": "mapped",
                "java": True,
                "series": series,
                "group": _ELASTIC_GROUP_TAG,
                "group_description": _ELASTIC_GROUP_DESCRIPTION,
                "reason": "mapped to AnisotropicVoGrp.DVo",
            }
        )
        return result
    if target is None:
        result["reason"] = "COMSOL property-group/tag is intentionally pending for this field"
        return result
    shape = entry["shape"]
    if shape not in {"scalar", "tensor2"}:
        result["reason"] = f"shape {shape} is not emitted through the basic COMSOL property group"
        return result
    temperatures = entry.get("temperatures_K")
    series = _temperature_values(entry, shape, temperatures)
    if temperatures is not None and len(temperatures) >= 2 and series is None:
        result["reason"] = "temperature series values are missing; no representative value is extrapolated"
        return result
    if entry.get("unit_si") in {None, ""}:
        result["reason"] = "unit_si is missing"
        return result
    result["status"] = "mapped"
    result["java"] = True
    result["series"] = series
    return result


def _safe_stem(text: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._") or "field"
    if stem[0].isdigit():
        stem = "field_" + stem
    return stem


def _java_quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def _number_text(value: Any) -> str:
    if not _is_number(value):
        raise ValueError(f"expected a finite numeric value, got {value!r}")
    return format(float(value), ".17g")


def _unit_expression(value: Any, unit: Any) -> str:
    number = _number_text(value)
    if unit in {None, "", "1", "dimensionless"}:
        return number
    return number + "[" + str(unit) + "]"


def _write_functions(output_directory: Path, parameters: Mapping[str, Any], mappings: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    function_directory = output_directory / "functions"
    function_directory.mkdir()
    specs: list[dict[str, Any]] = []
    for name, entry in parameters.items():
        mapping = mappings[name]
        if mapping.get("status") != "mapped" or mapping.get("series") is None:
            continue
        temperatures = [float(value) for value in entry["temperatures_K"]]
        series = mapping["series"]
        component_series: dict[str, list[Any]] = {}
        for item in series:
            for component, value in _component_values(entry["shape"], item):
                component_series.setdefault(component, []).append(value)
        for component, values in component_series.items():
            if any(value is None for value in values):
                continue
            stem = _safe_stem(name + "__" + component)
            filename = stem + ".txt"
            path = function_directory / filename
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for temperature, value in zip(temperatures, values):
                    handle.write(f"{temperature:.17g}\t{_number_text(value)}\n")
            function_name = "mlcc_" + _safe_stem(name + "_" + component) + "_fn"
            specs.append(
                {
                    "property": name,
                    "component": component,
                    "filename": "functions/" + filename,
                    "function_name": function_name,
                    "unit": "1" if entry["unit_si"] == "dimensionless" else str(entry["unit_si"]),
                }
            )
    return specs


def _function_lookup(function_specs: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {(str(spec["property"]), str(spec["component"])): spec for spec in function_specs}


def _matrix_expression(matrix: Sequence[Sequence[Any]], unit: Any) -> str:
    rows = []
    for row in matrix:
        rows.append("{" + ", ".join(_java_quote(_unit_expression(value, unit)) for value in row) + "}")
    return "new String[][]{" + ", ".join(rows) + "}"


def _java_template(
    package: Mapping[str, Any],
    output_directory: Path,
    parameters: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    function_specs: Sequence[Mapping[str, Any]],
) -> str:
    package_label = "MLCC continuum package " + str(package["package_id"])
    lines = [
        "import com.comsol.model.Model;",
        "import com.comsol.model.MaterialModel;",
        "",
        "/**",
        " * COMSOL Multiphysics 6.3 material-population template generated from a C1 SI package.",
        " * value_si is already in comsol_global_cartesian; no tensor rotation or sign flip is done here.",
        " * This class creates material/function objects only. It does not solve or save an MPH model.",
        " */",
        "public final class PopulateMlccMaterial {",
        "    private PopulateMlccMaterial() {}",
        "",
        "    public static void populate(Model model, String componentTag, String materialTag,",
        "                                String selectionTag, String dataDirectory) {",
        "        if (model == null) throw new IllegalArgumentException(\"model is required\");",
        "        if (componentTag == null || componentTag.isEmpty()) throw new IllegalArgumentException(\"componentTag is required\");",
        "        if (materialTag == null || materialTag.isEmpty()) throw new IllegalArgumentException(\"materialTag is required\");",
        "        if (selectionTag == null || selectionTag.isEmpty()) throw new IllegalArgumentException(\"selectionTag is required\");",
        "        if (dataDirectory == null || dataDirectory.isEmpty()) throw new IllegalArgumentException(\"dataDirectory is required\");",
        "",
        "        // The caller owns the component and named selection; this template never selects the whole model.",
        "        model.component(componentTag).material().create(materialTag, \"Common\");",
        f"        model.component(componentTag).material(materialTag).label({_java_quote(package_label)} + \" (\" + materialTag + \")\");",
        "        model.component(componentTag).material(materialTag).selection().named(selectionTag);",
        "",
    ]
    if function_specs:
        lines.append('        String functionPrefix = "mlcc_" + componentTag + "_" + materialTag + "_";')
        if any(spec["property"] != "elastic_stiffness" for spec in function_specs):
            lines.append('        model.component(componentTag).material(materialTag).propertyGroup("def").addInput("temperature");')
        lines.append("")
        for spec in function_specs:
            tag = str(spec["function_name"])
            function_ref = "functionPrefix + " + _java_quote(tag)
            lines.extend(
                [
                    f'        model.func().create({function_ref}, "Interpolation");',
                    f'        model.func({function_ref}).set("source", "file");',
                    f'        model.func({function_ref}).set("filename", dataDirectory + "/" + {_java_quote(str(spec["filename"]))});',
                    f'        model.func({function_ref}).set("struct", "spreadsheet");',
                    f'        model.func({function_ref}).set("funcnametable", new String[][]{{{{{function_ref}, "1"}}}});',
                    f'        model.func({function_ref}).set("argunit", "K");',
                    f'        model.func({function_ref}).set("fununit", {_java_quote(str(spec["unit"]))});',
                    f'        model.func({function_ref}).set("interp", "linear");',
                    f'        model.func({function_ref}).set("extrap", "none");',
                    f'        model.func({function_ref}).importData();',
                    "",
                ]
            )
    lines.extend(
        [
            '        // Basic scalar/tensor properties are populated only when their C1 source is available.',
        ]
    )
    if mappings.get("elastic_stiffness", {}).get("status") == "mapped":
        lines.extend(
            [
                f'        MaterialModel anisotropicVoigt = model.component(componentTag).material(materialTag).propertyGroup().create({_java_quote(_ELASTIC_GROUP_TAG)}, {_java_quote(_ELASTIC_GROUP_DESCRIPTION)});',
                "",
            ]
        )
        if mappings["elastic_stiffness"].get("series") is not None:
            lines.append('        anisotropicVoigt.addInput("temperature");')
            lines.append("")
    lines.append('        // Initial stress, contact/interface fields, and piezoelectric fields remain mapping-pending.')
    lookup = _function_lookup(function_specs)
    for name, entry in parameters.items():
        mapping = mappings[name]
        if mapping.get("status") != "mapped":
            continue
        target = str(mapping["target"])
        shape = str(entry["shape"])
        unit = entry.get("unit_si")
        series = mapping.get("series")
        if series is not None:
            component_functions = {
                component: lookup[(name, component)]["function_name"]
                for component, _ in _component_values(shape, series[0])
                if (name, component) in lookup
            }
            if shape == "scalar" and "scalar" in component_functions:
                expression = "functionPrefix + " + _java_quote(str(component_functions["scalar"]) + "(T)")
            elif shape == "tensor2":
                matrix = [["functionPrefix + " + _java_quote(component_functions[f"{row}{column}"] + "(T)") for column in ("x", "y", "z")] for row in ("x", "y", "z")]
                expression = "new String[][]{" + ", ".join("{" + ", ".join(item for item in row) + "}" for row in matrix) + "}"
            elif shape == "elasticity6":
                matrix = [
                    ["functionPrefix + " + _java_quote(component_functions[f"{row},{column}"] + "(T)") for column in _VOIGT_LABELS]
                    for row in _VOIGT_LABELS
                ]
                expression = "new String[][]{" + ", ".join("{" + ", ".join(item for item in row) + "}" for row in matrix) + "}"
            else:
                continue
        else:
            value = entry.get("value_si")
            if shape == "scalar":
                expression = _java_quote(_unit_expression(value, unit))
            elif shape == "tensor2":
                expression = _matrix_expression(value, unit)
            elif shape == "elasticity6":
                expression = _matrix_expression(value, unit)
            else:
                continue
        if name == "elastic_stiffness":
            lines.append(f'        anisotropicVoigt.set({_java_quote(_ELASTIC_PROPERTY_TAG)}, {expression});')
        else:
            lines.append(f'        model.component(componentTag).material(materialTag).propertyGroup("def").set({_java_quote(target)}, {expression});')
        if name == "thermal_expansion":
            reference_temperature = mappings[name]["reference_temperature_K"]
            reference_expression = _java_quote(_unit_expression(reference_temperature, "K"))
            lines.append(
                f'        model.component(componentTag).material(materialTag).propertyGroup("def").set("strainreferencetemperature", {reference_expression});'
            )
    lines.extend(
        [
            "    }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (list, dict)) else str(value)


def _write_csv(output_directory: Path, package: Mapping[str, Any]) -> None:
    fields = [
        "package_id",
        "property",
        "definition",
        "component",
        "shape",
        "value_si",
        "unit_si",
        "source_value",
        "source_unit",
        "source_value_si",
        "material_value_si",
        "temperature_K",
        "temperature_policy",
        "conditions",
        "reference_state",
        "status",
        "missing_reasons",
        "source",
        "source_path",
        "source_schema",
        "source_field",
        "source_identity",
        "source_status",
        "source_qualification",
    ]
    with (output_directory / "parameters-si.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for name, entry in package["parameters"].items():
            temperatures = entry.get("temperatures_K")
            series = _temperature_values(entry, entry["shape"], temperatures)
            if series is not None:
                rows = [(temperature, value) for temperature, value in zip(temperatures, series)]
            else:
                rows = [(entry.get("conditions", {}).get("temperature_K"), entry.get("value_si"))]
            source = entry.get("source") or {}
            for temperature, value in rows:
                for component, component_value in _component_values(entry["shape"], value):
                    row = {
                        "package_id": package["package_id"],
                        "property": name,
                        "definition": _csv_value(entry.get("definition")),
                        "component": component,
                        "shape": entry["shape"],
                        "value_si": _csv_value(component_value),
                        "unit_si": _csv_value(entry.get("unit_si")),
                        "source_value": _csv_value(entry.get("source_value")),
                        "source_unit": _csv_value(entry.get("source_unit")),
                        "source_value_si": _csv_value(entry.get("source_value_si")),
                        "material_value_si": _csv_value(entry.get("material_value_si")),
                        "temperature_K": _csv_value(temperature),
                        "temperature_policy": _csv_value(entry.get("temperature_policy")),
                        "conditions": _csv_value(entry.get("conditions")),
                        "reference_state": _csv_value(entry.get("reference_state")),
                        "status": entry.get("status"),
                        "missing_reasons": _csv_value(entry.get("missing_reasons") or []),
                        "source": _csv_value(source),
                        "source_path": _csv_value(source.get("path")),
                        "source_schema": _csv_value(source.get("schema")),
                        "source_field": _csv_value(source.get("field")),
                        "source_identity": _csv_value(source.get("identity")),
                        "source_status": _csv_value(source.get("status")),
                        "source_qualification": _csv_value(source.get("qualification")),
                    }
                    writer.writerow(row)


def _write_mapping(output_directory: Path, package: Mapping[str, Any], mappings: Mapping[str, Mapping[str, Any]], selected_permittivity: str | None) -> None:
    lines = [
        "# COMSOL material mapping (template only)",
        "",
        f"Package: `{package['package_id']}`; schema: `{package['schema']}`.",
        "",
        "`value_si` is consumed as already rotated target Cartesian data. No rotation, pressure flip, or sign conversion is performed.",
        "The target basis is `comsol_global_cartesian`; the complete Q matrix remains in `parameters-si.json`.",
        "",
        f"Selected permittivity property: `{selected_permittivity or 'none'}`.",
        "An available electronic permittivity is never substituted for an unresolved static value without an explicit `comsol.permittivity_property` choice.",
        "COMSOL import status is not established by this file export.",
        "",
        "| Property | Status | COMSOL target | Reason/source |",
        "|---|---|---|---|",
    ]
    for name, entry in package["parameters"].items():
        mapping = mappings[name]
        source = entry.get("source") or {}
        source_text = f"{source.get('path', 'unknown')} :: {source.get('field', 'unknown')}"
        reason = mapping.get("reason") or "available SI field"
        lines.append(f"| `{name}` | `{mapping['status']}` | `{mapping.get('target') or 'pending'}` | {reason}; source `{source_text}` |")
    lines.extend(
        [
            "",
            "## Deliberately pending mappings",
            "",
            "Available elasticity uses the COMSOL 6.3 `AnisotropicVoGrp` group and `DVo` property with the complete engineering-Voigt order `(xx,yy,zz,yz,xz,xy)` and all 36 components. If the source is unresolved, its SI table remains pending rather than being filled. Initial stress, thermal/contact interface physics, and piezoelectric groups are not guessed here; their complete SI values and provenance remain in the table.",
            "",
            "Official API target: COMSOL Multiphysics 6.3 material/propertyGroup and interpolation-function APIs ([material](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_api_general.47.40.html), [functions](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_api_general.47.34.html)). No LiveLink, MPH generation, import readback, or device solve is implied.",
        ]
    )
    (output_directory / "comsol-mapping.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_comsol_material_package(package_path: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Export a C1 SI package without recomputing or transforming its fields.

    The output directory must not already exist.  The returned dictionary is
    the written manifest and intentionally reports ``comsol_import_status`` as
    ``not_run`` and ``mph_generated``/``device_solve`` as false.
    """

    package_file = Path(package_path)
    with package_file.open("r", encoding="utf-8") as handle:
        package_data = json.load(handle)
    if not isinstance(package_data, Mapping):
        raise ValueError("continuum package JSON must contain an object")
    package = _validate_package(package_data)
    parameters = package["parameters"]
    selected_permittivity = _selected_permittivity(package, parameters)
    mappings = {name: _mapping_for(name, entry, selected_permittivity) for name, entry in parameters.items()}

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=False)
    (output / "parameters-si.json").write_text(json.dumps(package_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_csv(output, package)
    function_specs = _write_functions(output, parameters, mappings)
    java_source = _java_template(package, output, parameters, mappings, function_specs)
    (output / "PopulateMlccMaterial.java").write_text(java_source, encoding="utf-8")
    _write_mapping(output, package, mappings, selected_permittivity)

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "package_schema": package["schema"],
        "package_id": package["package_id"],
        "source_package": str(package_file.resolve()),
        "output_directory": str(output.resolve()),
        "files": {
            "parameters_si": "parameters-si.json",
            "parameters_csv": "parameters-si.csv",
            "java_template": "PopulateMlccMaterial.java",
            "mapping": "comsol-mapping.md",
            "functions": [spec["filename"] for spec in function_specs],
        },
        "parameter_count": len(parameters),
        "mapping": mappings,
        "selected_permittivity": selected_permittivity,
        "export_status": "export-template-passed",
        "comsol_import_status": "not_run",
        "mph_generated": False,
        "device_solve": False,
        "environment": {
            "comsol_version": "unknown",
            "live_link": "unknown",
            "reason": "file-only template export; no COMSOL runtime evidence was supplied",
        },
    }
    (output / "export-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


__all__ = ["export_comsol_material_package"]
