"""Static-contract tests for the C1-to-COMSOL file exporter.

The tests exercise only temporary JSON/text files.  They do not require a
COMSOL installation and do not run a solver or a scientific post-processing
path.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from mlcc.comsol_export import export_comsol_material_package


def _source(field: str, status: str = "available") -> dict[str, object]:
    return {
        "path": "/workspace/native/source.json",
        "schema": "mlcc.native.v1",
        "field": field,
        "identity": {"study_id": "study-01", "method": "abacus"},
        "status": status,
        "qualification": "engineering_only",
        "native_jobs": ["job-01"],
        "source_files": ["result.json"],
    }


def _entry(
    name: str,
    shape: str,
    value: object,
    unit: str | None,
    *,
    status: str = "available",
    temperatures: list[float] | None = None,
    missing_reasons: list[str] | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": name,
        "definition": f"definition of {name}",
        "shape": shape,
        "value_si": value,
        "unit_si": unit,
        "source_value": value,
        "source_unit": unit,
        "source_value_si": value,
        "material_value_si": value,
        "temperatures_K": temperatures,
        "temperature_policy": {"interpolation": "linear", "extrapolation": "none"} if temperatures and len(temperatures) >= 2 else None,
        "conditions": {"temperature_K": 300.0},
        "reference_state": {"temperature_K": 300.0},
        "status": status,
        "missing_reasons": missing_reasons or [],
        "source": _source(name, status),
    }
    if status == "unresolved":
        entry["source"] = _source(name, "missing")
    return entry


def _package(*, explicit_permittivity: str | None = "relative_permittivity_electronic") -> dict[str, object]:
    parameters: dict[str, object] = {
        "density": _entry("density", "scalar", 7800.0, "kg/m^3"),
        "heat_capacity_cp": _entry(
            "heat_capacity_cp",
            "scalar",
            [500.0, 650.0],
            "J/(kg*K)",
            temperatures=[300.0, 600.0],
        ),
        "thermal_conductivity": _entry(
            "thermal_conductivity",
            "tensor2",
            [[10.0, 1.0, 2.0], [3.0, 20.0, 4.0], [5.0, 6.0, 30.0]],
            "W/(m*K)",
        ),
        "thermal_expansion": _entry("thermal_expansion", "tensor2", [[1.0e-5, 0.0, 0.0], [0.0, 2.0e-5, 0.0], [0.0, 0.0, 3.0e-5]], "1/K"),
        "elastic_stiffness": _entry(
            "elastic_stiffness",
            "elasticity6",
            [[100.0 + 10.0 * row + column for column in range(6)] for row in range(6)],
            "Pa",
        ),
        "relative_permittivity_static": _entry(
            "relative_permittivity_static",
            "tensor2",
            None,
            "dimensionless",
            status="unresolved",
            missing_reasons=["static dielectric source is absent"],
        ),
        "relative_permittivity_electronic": _entry(
            "relative_permittivity_electronic",
            "tensor2",
            [[100.0, 0.0, 0.0], [0.0, 110.0, 0.0], [0.0, 0.0, 120.0]],
            "dimensionless",
        ),
        "electric_conductivity": _entry(
            "electric_conductivity",
            "scalar",
            None,
            "S/m",
            status="unresolved",
            missing_reasons=["only sigma_over_tau is available"],
        ),
        "heat_contact_conductance": _entry(
            "heat_contact_conductance",
            "scalar",
            None,
            "W/(m^2*K)",
            status="unresolved",
            missing_reasons=["interface physics tag is not defined"],
        ),
    }
    parameters["thermal_expansion"]["conditions"] = {"thermal_expansion_form": "secant"}
    parameters["thermal_expansion"]["reference_state"] = {"stress_free_temperature_K": 300.0}
    package: dict[str, object] = {
        "schema": "mlcc.continuum-parameters.v1",
        "package_id": "package-with-\"quote\"",
        "study": {"study_id": "study-01", "material_id": "BTO-P4mm"},
        "material_state": {"phase": "P4mm", "temperature_K": 300.0},
        "coordinate_systems": {
            "source_basis": "native_material",
            "target_basis": "comsol_global_cartesian",
            "source_to_target": [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
        },
        "status": "partial",
        "parameters": parameters,
    }
    if explicit_permittivity is not None:
        package["comsol"] = {"permittivity_property": explicit_permittivity}
    return package


def _write_package(tmp_path: Path, package: dict[str, object]) -> Path:
    path = tmp_path / "parameters-si-input.json"
    path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    return path


def test_export_preserves_package_and_writes_java_functions_and_mapping(tmp_path: Path) -> None:
    package = _package()
    source = _write_package(tmp_path, package)
    output = tmp_path / "export"

    manifest = export_comsol_material_package(source, output)

    assert manifest["export_status"] == "export-template-passed"
    assert manifest["comsol_import_status"] == "not_run"
    assert manifest["mph_generated"] is False
    assert manifest["device_solve"] is False
    assert json.loads((output / "parameters-si.json").read_text(encoding="utf-8")) == package
    assert (output / "parameters-si.csv").is_file()
    assert (output / "PopulateMlccMaterial.java").is_file()
    assert (output / "comsol-mapping.md").is_file()
    assert (output / "export-manifest.json").is_file()
    assert (output / "functions" / "heat_capacity_cp__scalar.txt").is_file()

    java = (output / "PopulateMlccMaterial.java").read_text(encoding="utf-8")
    assert "selectionTag is required" in java
    assert "comsol_global_cartesian; no tensor rotation or sign flip" in java
    assert "source\", \"file\"" in java
    assert "struct\", \"spreadsheet\"" in java
    assert "funcnametable" in java
    assert "argunit\", \"K\"" in java
    assert "interp\", \"linear\"" in java
    assert "extrap\", \"none\"" in java
    assert 'String functionPrefix = "mlcc_" + componentTag + "_" + materialTag + "_";' in java
    assert 'model.func().create(functionPrefix + "mlcc_heat_capacity_cp_scalar_fn", "Interpolation");' in java
    assert 'set("funcnametable", new String[][]{{functionPrefix + "mlcc_heat_capacity_cp_scalar_fn", "1"}});' in java
    assert 'set("heatcapacity", functionPrefix + "mlcc_heat_capacity_cp_scalar_fn(T)")' in java
    assert '"1[W/(m*K)]"' in java
    assert '"3[W/(m*K)]"' in java
    assert '"thermalexpansioncoefficient"' in java
    assert 'set("strainreferencetemperature", "300[K]")' in java
    assert 'create("AnisotropicVoGrp", "Anisotropic, Voigt notation")' in java
    assert 'anisotropicVoigt.set("DVo"' in java
    assert '"101[Pa]"' in java
    assert '"110[Pa]"' in java
    assert ".solve(" not in java
    assert ".save(" not in java
    assert "package-with-\\\"quote\\\"" in java
    assert "electricconductivity" not in java

    with (output / "parameters-si.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    tensor_row = next(row for row in rows if row["property"] == "thermal_conductivity" and row["component"] == "xy")
    assert tensor_row["value_si"] == "1.0"
    elasticity_rows = [row for row in rows if row["property"] == "elastic_stiffness"]
    assert len(elasticity_rows) == 36
    assert manifest["mapping"]["elastic_stiffness"]["status"] == "mapped"
    assert manifest["mapping"]["electric_conductivity"]["status"] == "pending"


def test_both_available_permittivities_require_explicit_selection(tmp_path: Path) -> None:
    package = _package(explicit_permittivity=None)
    package["parameters"]["relative_permittivity_static"]["status"] = "available"
    package["parameters"]["relative_permittivity_static"]["value_si"] = [[90.0, 0.0, 0.0], [0.0, 95.0, 0.0], [0.0, 0.0, 100.0]]
    source = _write_package(tmp_path, package)

    with pytest.raises(ValueError, match="both permittivity properties.*explicit"):
        export_comsol_material_package(source, tmp_path / "reject")


def test_electronic_permittivity_cannot_replace_missing_static_implicitly(tmp_path: Path) -> None:
    package = _package(explicit_permittivity=None)
    source = _write_package(tmp_path, package)

    manifest = export_comsol_material_package(source, tmp_path / "unresolved")
    assert manifest["selected_permittivity"] is None
    assert manifest["mapping"]["relative_permittivity_electronic"]["status"] == "pending"
    assert "not selected" in manifest["mapping"]["relative_permittivity_electronic"]["reason"]

    package["comsol"] = {"permittivity_property": "relative_permittivity_electronic"}
    source.write_text(json.dumps(package), encoding="utf-8")
    manifest = export_comsol_material_package(source, tmp_path / "selected")
    assert manifest["selected_permittivity"] == "relative_permittivity_electronic"


def test_temperature_policy_and_null_temperature_series_rules(tmp_path: Path) -> None:
    package = _package()
    package["parameters"]["density"]["temperatures_K"] = None
    package["parameters"]["density"]["temperature_policy"] = None
    package["parameters"]["density"]["conditions"] = {"temperature_K": 300.0}
    package["parameters"]["density"]["value_si"] = 7800.0
    source = _write_package(tmp_path, package)
    output = tmp_path / "single"

    manifest = export_comsol_material_package(source, output)

    assert not any("density" in filename for filename in manifest["files"]["functions"])
    assert any("heat_capacity_cp" in filename for filename in manifest["files"]["functions"])
    with pytest.raises(FileExistsError):
        export_comsol_material_package(source, output)

    package["parameters"]["density"]["temperatures_K"] = [300.0]
    source.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(ValueError, match="at least two temperatures"):
        export_comsol_material_package(source, tmp_path / "single-invalid")


def test_dimensionless_temperature_function_uses_unit_one(tmp_path: Path) -> None:
    package = _package()
    epsilon = package["parameters"]["relative_permittivity_electronic"]
    epsilon["temperatures_K"] = [300.0, 600.0]
    epsilon["temperature_policy"] = {"interpolation": "linear", "extrapolation": "none"}
    epsilon["value_si"] = [
        [[100.0, 0.0, 0.0], [0.0, 110.0, 0.0], [0.0, 0.0, 120.0]],
        [[101.0, 0.0, 0.0], [0.0, 111.0, 0.0], [0.0, 0.0, 121.0]],
    ]
    source = _write_package(tmp_path, package)

    manifest = export_comsol_material_package(source, tmp_path / "dimensionless")

    assert any("relative_permittivity_electronic" in filename for filename in manifest["files"]["functions"])
    java = (tmp_path / "dimensionless" / "PopulateMlccMaterial.java").read_text(encoding="utf-8")
    assert 'set("fununit", "1")' in java
    assert 'set("fununit", "dimensionless")' not in java


def test_temperature_elasticity_emits_all_36_functions_and_group_input(tmp_path: Path) -> None:
    package = _package()
    package["parameters"]["heat_capacity_cp"]["temperatures_K"] = None
    package["parameters"]["heat_capacity_cp"]["temperature_policy"] = None
    package["parameters"]["heat_capacity_cp"]["value_si"] = 500.0
    elasticity = package["parameters"]["elastic_stiffness"]
    first = [[100.0 + 10.0 * row + column for column in range(6)] for row in range(6)]
    second = [[200.0 + 10.0 * row + column for column in range(6)] for row in range(6)]
    elasticity["temperatures_K"] = [300.0, 600.0]
    elasticity["temperature_policy"] = {"interpolation": "linear", "extrapolation": "none"}
    elasticity["value_si"] = [first, second]
    source = _write_package(tmp_path, package)

    manifest = export_comsol_material_package(source, tmp_path / "elastic-temperature")

    elastic_functions = [
        filename for filename in manifest["files"]["functions"] if filename.startswith("functions/elastic_stiffness__")
    ]
    assert len(elastic_functions) == 36
    java = (tmp_path / "elastic-temperature" / "PopulateMlccMaterial.java").read_text(encoding="utf-8")
    assert 'anisotropicVoigt.addInput("temperature")' in java
    assert 'propertyGroup("def").addInput("temperature")' not in java
    assert 'model.func().create(functionPrefix + "mlcc_elastic_stiffness_xx_xx_fn", "Interpolation");' in java
    assert 'functionPrefix + "mlcc_elastic_stiffness_xx_xx_fn(T)"' in java
    assert 'anisotropicVoigt.set("DVo", new String[][]' in java


def test_invalid_temperature_policy_and_missing_temperature_series_are_explicit(tmp_path: Path) -> None:
    package = _package()
    cp = package["parameters"]["heat_capacity_cp"]
    cp["value_si"] = 500.0
    cp["temperature_policy"] = {"interpolation": "nearest", "extrapolation": "none"}
    source = _write_package(tmp_path, package)
    with pytest.raises(ValueError, match="linear/none"):
        export_comsol_material_package(source, tmp_path / "bad-policy")

    cp["temperature_policy"] = {"interpolation": "linear", "extrapolation": "none"}
    source.write_text(json.dumps(package), encoding="utf-8")
    manifest = export_comsol_material_package(source, tmp_path / "missing-series")
    assert manifest["mapping"]["heat_capacity_cp"]["status"] == "pending"
    assert "temperature series values are missing" in manifest["mapping"]["heat_capacity_cp"]["reason"]
    assert not any("heat_capacity_cp" in filename for filename in manifest["files"]["functions"])


def test_tau_normalized_conductivity_is_rejected_as_electric_conductivity(tmp_path: Path) -> None:
    package = _package()
    conductivity = package["parameters"]["electric_conductivity"]
    conductivity["status"] = "available"
    conductivity["value_si"] = 1.0
    conductivity["unit_si"] = "S/(m*s)"
    source = _write_package(tmp_path, package)

    with pytest.raises(ValueError, match="electric_conductivity.unit_si"):
        export_comsol_material_package(source, tmp_path / "reject-tau")


def test_tangent_or_unreferenced_alpha_stays_mapping_pending(tmp_path: Path) -> None:
    package = _package()
    package["parameters"]["thermal_expansion"]["conditions"] = {"thermal_expansion_form": "tangent"}
    source = _write_package(tmp_path, package)

    manifest = export_comsol_material_package(source, tmp_path / "pending-alpha")

    assert manifest["mapping"]["thermal_expansion"]["status"] == "pending"
    assert "secant" in manifest["mapping"]["thermal_expansion"]["reason"]
    java = (tmp_path / "pending-alpha" / "PopulateMlccMaterial.java").read_text(encoding="utf-8")
    assert "thermalexpansioncoefficient" not in java

    package["parameters"]["thermal_expansion"]["conditions"] = {"thermal_expansion_form": "secant"}
    package["parameters"]["thermal_expansion"]["reference_state"] = {}
    source.write_text(json.dumps(package), encoding="utf-8")
    missing_reference = export_comsol_material_package(source, tmp_path / "pending-reference")
    assert "stress_free_temperature_K" in missing_reference["mapping"]["thermal_expansion"]["reason"]


def test_unresolved_elasticity_keeps_dv0_pending_without_java_defaults(tmp_path: Path) -> None:
    package = _package()
    elasticity = package["parameters"]["elastic_stiffness"]
    elasticity["status"] = "unresolved"
    elasticity["value_si"] = None
    elasticity["missing_reasons"] = ["no complete stiffness source"]
    source = _write_package(tmp_path, package)

    manifest = export_comsol_material_package(source, tmp_path / "pending-elasticity")

    assert manifest["mapping"]["elastic_stiffness"]["status"] == "pending"
    assert "no complete stiffness source" in manifest["mapping"]["elastic_stiffness"]["reason"]
    java = (tmp_path / "pending-elasticity" / "PopulateMlccMaterial.java").read_text(encoding="utf-8")
    assert "AnisotropicVoGrp" not in java
