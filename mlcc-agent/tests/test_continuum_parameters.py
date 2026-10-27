"""Contract tests for the explicit continuum-parameter adapter.

These tests are intentionally source-only fixtures.  They exercise conversion
and provenance rules without invoking any native reader or solver.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mlcc.continuum_parameters import (
    PACKAGE_SCHEMA,
    REQUEST_SCHEMA,
    build_continuum_parameter_package,
    transform_elastic_stiffness,
    transform_piezoelectric_e,
    transform_tensor2,
)


def _write(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path.name


def _study() -> dict:
    return {
        "schema": "mlcc.study.v1",
        "study_id": "study-1",
        "model": {"model_id": "model-1", "model_version": "v1"},
        "study_scope": {"kind": "fixture"},
    }


def _coordinates(source_to_material=None, material_to_target=None) -> dict:
    return {
        "source_basis": "source_cartesian",
        "material_basis": "material_crystal_axes",
        "target_basis": "comsol_global_cartesian",
        "source_to_material": np.eye(3).tolist() if source_to_material is None else source_to_material,
        "material_to_target": np.eye(3).tolist() if material_to_target is None else material_to_target,
    }


def _request(tmp_path: Path, properties: list[dict], *, temperature=None, coordinates=None, comsol=None) -> Path:
    _write(tmp_path / "study.json", _study())
    request = {
        "schema": REQUEST_SCHEMA,
        "package_id": "package-1",
        "study_path": "study.json",
        "material_state": {
            "state_id": "state-1",
            "phase": "fixture-phase",
            "composition": {"A": 1, "B": 1},
            "temperature_K": temperature,
            "mechanical_boundary": "fixed_cell",
            "reference_state": {"kind": "declared"},
            "history": [{"step": "initial"}],
        },
        "coordinate_systems": coordinates or _coordinates(),
        "properties": properties,
    }
    if comsol is not None:
        request["comsol"] = comsol
    _write(tmp_path / "request.json", request)
    return tmp_path / "request.json"


def _typed(property_name: str, value, *, unit: str, shape: str, conditions=None, **extra) -> dict:
    source = {
        "schema": "mlcc.continuum-property-source.v1",
        "study_id": "study-1",
        "model_id": "model-1",
        "model_version": "v1",
        "property": property_name,
        "definition": property_name,
        "unit": unit,
        "value": value,
        "shape": shape,
        "basis": "source_cartesian",
        "conditions": {} if conditions is None else conditions,
        "source_refs": ["fixture-source"],
        "native_jobs": [{"job_id": "fixture-job"}],
        "status": "available",
        "qualification": {"scientific": False},
    }
    source.update(extra)
    return source


def _rotation_z_90() -> list[list[float]]:
    return [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]


def test_tensor2_rotation_preserves_complete_nonsymmetric_tensor() -> None:
    source = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    rotation = np.asarray(_rotation_z_90())
    expected = rotation @ np.asarray(source) @ rotation.T
    result = transform_tensor2(source, rotation, np.eye(3))
    np.testing.assert_allclose(result["material"], expected)
    assert not np.allclose(result["material"], np.asarray(result["material"]).T)


def test_isotropic_elastic_rotation_invariant_with_engineering_shear() -> None:
    lam, mu = 3.0, 5.0
    diagonal = lam + 2.0 * mu
    source = np.full((6, 6), lam)
    source[range(3), range(3)] = diagonal
    source[:3, 3:] = 0.0
    source[3:, :3] = 0.0
    source[3:, 3:] = np.eye(3) * mu
    half_sqrt = np.sqrt(0.5)
    rotation = np.asarray([[half_sqrt, -half_sqrt, 0.0], [half_sqrt, half_sqrt, 0.0], [0.0, 0.0, 1.0]])
    result = transform_elastic_stiffness(source, rotation, np.eye(3))
    np.testing.assert_allclose(result["target"], source, rtol=1e-12, atol=1e-12)


def test_elastic_stress_engineering_strain_covariance_is_independent() -> None:
    source = np.asarray([
        [18.0, 2.0, 1.0, 0.7, 0.8, 0.9],
        [2.0, 15.0, 1.5, 1.1, 0.6, 0.4],
        [1.0, 1.5, 12.0, 0.3, 0.5, 0.2],
        [0.7, 1.1, 0.3, 7.0, 0.9, 0.8],
        [0.8, 0.6, 0.5, 0.9, 8.0, 0.4],
        [0.9, 0.4, 0.2, 0.8, 0.4, 6.0],
    ])
    half_sqrt = np.sqrt(0.5)
    rotation = np.asarray([[half_sqrt, -half_sqrt, 0.0], [half_sqrt, half_sqrt, 0.0], [0.0, 0.0, 1.0]])
    source_strain = np.asarray([[0.12, 0.07, -0.03], [0.07, -0.08, 0.05], [-0.03, 0.05, 0.04]])
    source_engineering_strain = np.asarray([
        source_strain[0, 0], source_strain[1, 1], source_strain[2, 2],
        2.0 * source_strain[1, 2], 2.0 * source_strain[0, 2], 2.0 * source_strain[0, 1],
    ])
    source_stress_voigt = source @ source_engineering_strain
    source_stress = np.asarray([
        [source_stress_voigt[0], source_stress_voigt[5], source_stress_voigt[4]],
        [source_stress_voigt[5], source_stress_voigt[1], source_stress_voigt[3]],
        [source_stress_voigt[4], source_stress_voigt[3], source_stress_voigt[2]],
    ])
    target_strain = rotation @ source_strain @ rotation.T
    target_engineering_strain = np.asarray([
        target_strain[0, 0], target_strain[1, 1], target_strain[2, 2],
        2.0 * target_strain[1, 2], 2.0 * target_strain[0, 2], 2.0 * target_strain[0, 1],
    ])
    target_stress_expected = rotation @ source_stress @ rotation.T
    transformed = transform_elastic_stiffness(source, rotation, np.eye(3))
    target_stress_voigt = np.asarray(transformed["target"]) @ target_engineering_strain
    target_stress_from_transformed = np.asarray([
        [target_stress_voigt[0], target_stress_voigt[5], target_stress_voigt[4]],
        [target_stress_voigt[5], target_stress_voigt[1], target_stress_voigt[3]],
        [target_stress_voigt[4], target_stress_voigt[3], target_stress_voigt[2]],
    ])
    np.testing.assert_allclose(target_stress_from_transformed, target_stress_expected)


def test_piezoelectric_engineering_shear_rotation_preserves_polarization_covariance() -> None:
    source = np.asarray([[1.0, 2.0, 3.0, 7.0, 5.0, 11.0], [13.0, 17.0, 19.0, 23.0, 29.0, 31.0], [37.0, 41.0, 43.0, 47.0, 53.0, 59.0]])
    half_sqrt = np.sqrt(0.5)
    rotation = np.asarray([[half_sqrt, -half_sqrt, 0.0], [half_sqrt, half_sqrt, 0.0], [0.0, 0.0, 1.0]])
    source_strain = np.asarray([[0.08, 0.03, -0.02], [0.03, -0.04, 0.06], [-0.02, 0.06, 0.11]])
    source_engineering_strain = np.asarray([
        source_strain[0, 0], source_strain[1, 1], source_strain[2, 2],
        2.0 * source_strain[1, 2], 2.0 * source_strain[0, 2], 2.0 * source_strain[0, 1],
    ])
    source_polarization = source @ source_engineering_strain
    target_strain = rotation @ source_strain @ rotation.T
    target_engineering_strain = np.asarray([
        target_strain[0, 0], target_strain[1, 1], target_strain[2, 2],
        2.0 * target_strain[1, 2], 2.0 * target_strain[0, 2], 2.0 * target_strain[0, 1],
    ])
    result = transform_piezoelectric_e(source, rotation, np.eye(3))
    target_polarization = np.asarray(result["material"]) @ target_engineering_strain
    np.testing.assert_allclose(target_polarization, rotation @ source_polarization)


def test_typed_tensor2_converts_to_si_and_preserves_source_metadata(tmp_path: Path) -> None:
    source = _typed("thermal_conductivity", [[1, 2, 3], [4, 5, 6], [7, 8, 9]], unit="W/(m*K)", shape="tensor2")
    source_path = tmp_path / "conductivity.json"
    _write(source_path, source)
    request_path = _request(
        tmp_path,
        [{"name": "thermal_conductivity", "source_path": source_path.name, "shape": "tensor2"}],
        coordinates=_coordinates(_rotation_z_90(), np.eye(3).tolist()),
    )
    package = build_continuum_parameter_package(request_path)
    parameter = package["parameters"]["thermal_conductivity"]
    expected = np.asarray(_rotation_z_90()) @ np.asarray(source["value"]) @ np.asarray(_rotation_z_90()).T
    np.testing.assert_allclose(parameter["value_si"], expected)
    assert package["schema"] == PACKAGE_SCHEMA
    assert parameter["source"]["native_jobs"] == [{"job_id": "fixture-job"}]
    assert parameter["source"]["qualification"] == {"scientific": False}
    assert parameter["source"]["record"] == source
    assert parameter["conditions"] == {}


def test_saved_source_reference_state_wins_and_is_preserved(tmp_path: Path) -> None:
    source_reference_state = {
        "kind": "source_stress_free_state",
        "stress_free_temperature_K": 298.15,
        "history": [{"source": "native"}],
    }
    source = _typed("initial_stress", [[1, 0, 0], [0, 2, 0], [0, 0, 3]], unit="GPa", shape="tensor2", reference_state=source_reference_state)
    _write(tmp_path / "stress.json", source)
    request_path = _request(tmp_path, [{"name": "initial_stress", "source_path": "stress.json"}])
    parameter = build_continuum_parameter_package(request_path)["parameters"]["initial_stress"]
    assert parameter["reference_state"] == source_reference_state
    assert parameter["source"]["record"]["reference_state"] == source_reference_state

    conflict_request = _request(
        tmp_path,
        [{
            "name": "initial_stress",
            "source_path": "stress.json",
            "reference_state": {"kind": "request_override", "stress_free_temperature_K": 300.0},
        }],
    )
    with pytest.raises(ValueError, match="saved source reference_state"):
        build_continuum_parameter_package(conflict_request)


def test_typed_source_shape_controls_implicit_request_shape(tmp_path: Path) -> None:
    source = _typed("thermal_conductivity", 2.5, unit="W/(m*K)", shape="scalar")
    _write(tmp_path / "conductivity.json", source)
    request_path = _request(tmp_path, [{"name": "thermal_conductivity", "source_path": "conductivity.json"}])
    parameter = build_continuum_parameter_package(request_path)["parameters"]["thermal_conductivity"]
    assert parameter["shape"] == "scalar"
    assert parameter["value_si"] == 2.5


def test_declared_single_interface_conductance_is_not_treated_as_cell_net(tmp_path: Path) -> None:
    source = _typed(
        "heat_contact_conductance",
        120.0,
        unit="W/(m^2*K)",
        shape="scalar",
        definition="single_interface thermal conductance G",
    )
    _write(tmp_path / "conductance.json", source)
    request_path = _request(
        tmp_path,
        [{
            "name": "heat_contact_conductance",
            "source_path": "conductance.json",
            "selection": {"interface_pair": ["left", "right"]},
        }],
    )
    parameter = build_continuum_parameter_package(request_path)["parameters"]["heat_contact_conductance"]
    assert parameter["status"] == "available"
    assert parameter["value_si"] == 120.0
    assert parameter["selection"] == {"interface_pair": ["left", "right"]}


def test_explicit_request_shape_must_match_typed_source(tmp_path: Path) -> None:
    source = _typed("thermal_conductivity", 2.5, unit="W/(m*K)", shape="scalar")
    _write(tmp_path / "conductivity.json", source)
    request_path = _request(tmp_path, [{"name": "thermal_conductivity", "source_path": "conductivity.json", "shape": "tensor2"}])
    with pytest.raises(ValueError, match="property or shape"):
        build_continuum_parameter_package(request_path)


def test_typed_temperature_series_requires_value_per_temperature(tmp_path: Path) -> None:
    source = _typed(
        "density",
        [1.0, 2.0],
        unit="g/cm^3",
        shape="scalar",
        temperatures_K=[300, 400],
        temperature_policy={"interpolation": "linear", "extrapolation": "none"},
    )
    source_path = tmp_path / "density.json"
    _write(source_path, source)
    request_path = _request(tmp_path, [{"name": "density", "source_path": source_path.name}])
    parameter = build_continuum_parameter_package(request_path)["parameters"]["density"]
    assert parameter["temperatures_K"] == [300.0, 400.0]
    assert parameter["source_value_si"] == [1000.0, 2000.0]
    assert parameter["value_si"] == [1000.0, 2000.0]


def test_entry_temperatures_cannot_annotate_single_source(tmp_path: Path) -> None:
    source_path = tmp_path / "density.json"
    _write(source_path, _typed("density", 1.0, unit="g/cm^3", shape="scalar"))
    request_path = _request(
        tmp_path,
        [{
            "name": "density",
            "source_path": source_path.name,
            "temperatures_K": [300, 400],
            "temperature_policy": {"interpolation": "linear", "extrapolation": "none"},
        }],
    )
    with pytest.raises(ValueError, match="annotate a single source value"):
        build_continuum_parameter_package(request_path)


def test_p5_contains_both_permittivity_properties_and_comsol_choice_is_passthrough(tmp_path: Path) -> None:
    dielectric = {
        "schema": "mlcc.dielectric-response.v1",
        "context": {"parent": {"study_id": "study-1", "model_id": "model-1", "model_version": "v1"}},
        "unit": "dimensionless",
        "conditions": None,
        "epsilon_infinity": [[2, 0, 0], [0, 3, 0], [0, 0, 4]],
        "epsilon_static": None,
        "status": "unresolved",
        "unresolved_reasons": ["ionic contribution unavailable"],
    }
    source = {
        "schema": "mlcc.p5-property-delivery.v1",
        "study_id": "study-1",
        "model": {"model_id": "model-1", "model_version": "v1"},
        "products": {"dielectric": dielectric},
        "status": "partial",
        "contribution_provenance": {"electronic": {"job_id": "e-1"}},
    }
    source_path = tmp_path / "p5.json"
    _write(source_path, source)
    request_path = _request(
        tmp_path,
        [
            {"name": "relative_permittivity_electronic", "source_path": source_path.name},
            {"name": "relative_permittivity_static", "source_path": source_path.name},
        ],
        comsol={"permittivity_property": "relative_permittivity_static", "domain": "continuum"},
    )
    package = build_continuum_parameter_package(request_path)
    electronic = package["parameters"]["relative_permittivity_electronic"]
    static = package["parameters"]["relative_permittivity_static"]
    assert electronic["status"] == "available"
    np.testing.assert_allclose(electronic["value_si"], dielectric["epsilon_infinity"])
    assert static["status"] == "unresolved"
    assert static["value_si"] is None
    assert package["status"] == "partial"
    assert package["comsol"]["permittivity_property"] == "relative_permittivity_static"
    assert "permittivity_property" not in package
    assert electronic["source"]["selected_product"] == dielectric
    assert electronic["source"]["record"] == source
    assert electronic["source"]["record"]["products"]["dielectric"]["conditions"] is None
    assert electronic["source"]["native_jobs"] is None


def test_static_dielectric_source_rejects_request_temperature(tmp_path: Path) -> None:
    source = {
        "schema": "mlcc.dielectric-response.v1",
        "context": {"parent": {"study_id": "study-1", "model_id": "model-1", "model_version": "v1"}},
        "unit": "dimensionless",
        "conditions": None,
        "epsilon_infinity": [[2, 0, 0], [0, 2, 0], [0, 0, 2]],
        "epsilon_static": None,
    }
    source_path = tmp_path / "dielectric.json"
    _write(source_path, source)
    request_path = _request(tmp_path, [{"name": "relative_permittivity_electronic", "source_path": source_path.name}], temperature=300)
    with pytest.raises(ValueError, match="temperature_K=null"):
        build_continuum_parameter_package(request_path)


def test_elastic_null_and_saved_lammps_stress_are_preserved(tmp_path: Path) -> None:
    elastic = {
        "schema": "mlcc.elastic-analysis.v001",
        "study_id": "study-1",
        "model_id": "model-1",
        "model_version": "v1",
        "voigt_order": ["xx", "yy", "zz", "yz", "xz", "xy"],
        "engineering_shear": True,
        "Cij_GPa": None,
        "status": "unresolved",
        "issues": ["fit unavailable"],
    }
    stress = {
        "schema": "mlcc.lammps-result.v1",
        "study_id": "study-1",
        "model_id": "model-1",
        "model_version": "v1",
        "tensor_basis": "source_cartesian",
        "stress_unit": "GPa",
        "stress_GPa": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
        "stress_sign": "tension_positive",
    }
    _write(tmp_path / "elastic.json", elastic)
    _write(tmp_path / "stress.json", stress)
    request_path = _request(tmp_path, [
        {"name": "elastic_stiffness", "source_path": "elastic.json"},
        {"name": "initial_stress", "source_path": "stress.json"},
    ])
    package = build_continuum_parameter_package(request_path)
    assert package["parameters"]["elastic_stiffness"]["status"] == "unresolved"
    assert package["parameters"]["elastic_stiffness"]["value_si"] is None
    np.testing.assert_allclose(package["parameters"]["initial_stress"]["value_si"], np.asarray(stress["stress_GPa"]) * 1e9)
    assert package["parameters"]["initial_stress"]["source"]["sign_conversion"] == "none_saved_stress_tension_positive"


def test_lammps_voigt_order_is_reordered_to_target_without_changing_source_record(tmp_path: Path) -> None:
    source_matrix = np.arange(1.0, 37.0).reshape(6, 6).tolist()
    source = _typed(
        "elastic_stiffness",
        source_matrix,
        unit="GPa",
        shape="elasticity6",
        voigt_order=["xx", "yy", "zz", "xy", "xz", "yz"],
        engineering_shear=True,
    )
    _write(tmp_path / "elastic-lammps-order.json", source)
    request_path = _request(tmp_path, [{"name": "elastic_stiffness", "source_path": "elastic-lammps-order.json"}])
    parameter = build_continuum_parameter_package(request_path)["parameters"]["elastic_stiffness"]
    permutation = [0, 1, 2, 5, 4, 3]
    expected_target = np.asarray(source_matrix)[np.ix_(permutation, permutation)] * 1e9
    np.testing.assert_allclose(parameter["source_value"], source_matrix)
    np.testing.assert_allclose(parameter["source_value_si"], np.asarray(source_matrix) * 1e9)
    np.testing.assert_allclose(parameter["material_value_si"], expected_target)
    np.testing.assert_allclose(parameter["value_si"], expected_target)
    assert parameter["source"]["record"] == source
    assert parameter["source_voigt_order"] == ["xx", "yy", "zz", "xy", "xz", "yz"]
    assert parameter["material_voigt_order"] == ["xx", "yy", "zz", "yz", "xz", "xy"]
    assert parameter["target_voigt_order"] == ["xx", "yy", "zz", "yz", "xz", "xy"]


def test_pressure_tensor_flips_once(tmp_path: Path) -> None:
    source = {
        "schema": "mlcc.lammps-result.v1",
        "study_id": "study-1", "model_id": "model-1", "model_version": "v1",
        "tensor_basis": "source_cartesian", "stress_unit": "GPa", "pressure_tensor_GPa": [[-1, 0, 0], [0, -2, 0], [0, 0, -3]],
        "pressure_sign": "compression_positive",
    }
    _write(tmp_path / "pressure.json", source)
    request_path = _request(tmp_path, [{"name": "initial_stress", "source_path": "pressure.json", "source_field": "pressure_tensor_GPa"}])
    parameter = build_continuum_parameter_package(request_path)["parameters"]["initial_stress"]
    np.testing.assert_allclose(parameter["source_value_si"], np.asarray(source["pressure_tensor_GPa"]) * 1e9)
    np.testing.assert_allclose(parameter["value_si"], -np.asarray(source["pressure_tensor_GPa"]) * 1e9)


def test_source_conditions_cannot_be_overridden(tmp_path: Path) -> None:
    source = _typed("density", 1.0, unit="g/cm^3", shape="scalar", conditions={"temperature_K": 300})
    _write(tmp_path / "density.json", source)
    request_path = _request(tmp_path, [{"name": "density", "source_path": "density.json", "conditions": {"temperature_K": 301}}], temperature=300)
    with pytest.raises(ValueError, match="differs from source conditions"):
        build_continuum_parameter_package(request_path)


@pytest.mark.parametrize("definition", ["sigma/tau", "kappa/tau", "sigma_over_tau", "kappa_over_tau", "cell_net single interface stress"])
def test_ambiguous_tau_or_cell_net_source_is_rejected(tmp_path: Path, definition: str) -> None:
    source = _typed("thermal_conductivity", 1.0, unit="W/(m*K)", shape="scalar", definition=definition)
    _write(tmp_path / "property.json", source)
    request_path = _request(tmp_path, [{"name": "thermal_conductivity", "source_path": "property.json", "shape": "scalar"}])
    with pytest.raises(ValueError, match="tau-normalized|cell-net"):
        build_continuum_parameter_package(request_path)


def test_identity_and_arbitrary_json_path_are_rejected(tmp_path: Path) -> None:
    source = _typed("density", 1.0, unit="g/cm^3", shape="scalar")
    source["study_id"] = "other-study"
    _write(tmp_path / "density.json", source)
    request_path = _request(tmp_path, [{"name": "density", "source_path": "density.json", "json_path": "value"}])
    with pytest.raises(ValueError, match="JSONPath"):
        build_continuum_parameter_package(request_path)


def test_identity_mismatch_is_rejected_after_selection_validation(tmp_path: Path) -> None:
    source = _typed("density", 1.0, unit="g/cm^3", shape="scalar")
    source["study_id"] = "other-study"
    _write(tmp_path / "density.json", source)
    request_path = _request(tmp_path, [{"name": "density", "source_path": "density.json"}])
    with pytest.raises(ValueError, match="study_id"):
        build_continuum_parameter_package(request_path)

