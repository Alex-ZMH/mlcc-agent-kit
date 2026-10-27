"""Small source-copy checks for saved domain-parameter products."""

from __future__ import annotations

import json

import pytest

from mlcc.saved_domain_parameters import build_saved_domain_parameters


def _write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _study(tmp_path, *, case_id="case"):
    return _write(
        tmp_path / "study.json",
        {
            "schema": "mlcc.study.v1",
            "study_id": "study",
            "case_id": case_id,
            "model": {
                "model_id": "model",
                "version": "v001",
                "fixture": False,
                "material": "CaZrO3",
                "phase_requested": "orthorhombic_Pnma",
            },
        },
    )


def _request(tmp_path, kind, source_path, study_path, **extra):
    request = {
        "schema": "mlcc.saved-domain-parameters-request.v1",
        "kind": kind,
        "study_path": study_path.name,
        "source_path": source_path.name,
    }
    request.update(extra)
    return _write(tmp_path / f"{kind}-request.json", request)


def _neb_source(tmp_path):
    source = {
        "schema": "mlcc.vacancy-migration.v1",
        "study_id": "study",
        "case_id": "case",
        "status": "unresolved",
        "analysis_scheduler_job_id": "547",
        "source_refs": ["saved-neb-result.json"],
        "source_record": {
            "model": {"model_id": "model", "version": "v001"},
            "barrier": {"forward_eV": 2.2, "backward_eV": 2.4,
                         "climbing_replica": 2, "climbing_replica_zero_based": 1,
                         "climbing_replica_energy_eV": -10.0,
                         "climbing_replica_is_endpoint": False,
                         "highest_image_is_climbing_replica": True,
                         "highest_final_image": 2,
                         "highest_final_image_is_endpoint": False},
            "native_job": {"scheduler_job_id": "546", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
            "source_files": {"neb_result": "saved-neb-result.json"},
            "native_result": {
                "schema": "mlcc.lammps-neb-result.v1",
                "model_id": "model",
                "version": "v001",
                "scientific_status": "neb_native_unconverged",
                "native_converged": False,
                "regular_native_converged": False,
                "climbing_native_converged": False,
                "path_endpoint_converged": True,
                "task_id": "neb-task",
                "source_files": {"atom-map.json": "saved-atom-map.json"},
                "protocol": {
                    "images": 4,
                    "ranks_per_image": 1,
                    "min_style": "quickmin",
                    "timestep_ps": 0.001,
                    "etol": 0.0,
                    "ftol_eV_per_angstrom": 0.05,
                    "max_iterations": 200,
                    "output_every": 10,
                    "spring_eV_per_angstrom2": 1.0,
                    "climb_iterations": 200,
                    "endpoint_policy": "fixed",
                    "endpoint_minimization": {"min_style": "cg"},
                },
            },
        },
    }
    return _write(tmp_path / "neb.json", source)


def test_neb_values_keep_saved_unresolved_status_and_native_convergence(tmp_path):
    study_path = _study(tmp_path)
    source_path = _neb_source(tmp_path)
    request_path = _request(tmp_path, "neb_barriers", source_path, study_path)

    product = build_saved_domain_parameters(request_path)

    assert product["model"] == json.loads(study_path.read_text())["model"]
    assert [item["value"] for item in product["properties"]] == [2.2, 2.4]
    assert [item["status"] for item in product["properties"]] == ["unresolved", "unresolved"]
    assert product["properties"][0]["conditions"]["native_convergence"] == {
        "scientific_status": "neb_native_unconverged",
        "native_converged": False,
        "regular_native_converged": False,
        "climbing_native_converged": False,
        "path_endpoint_converged": True,
    }
    assert product["properties"][0]["conditions"]["analysis_scheduler_job_id"] == "547"
    assert product["properties"][0]["atom_mapping_ref"] == "saved-atom-map.json"
    assert product["execution"]["native_jobs"][0]["scheduler_job_id"] == "546"


def _interface_source(tmp_path, kind):
    normal = kind == "interface_normal"
    response_key = "normal_response" if normal else "tangential_response"
    schema = "mlcc.interface-normal-product.v1" if normal else "mlcc.interface-tangential-product.v1"
    point = {
        "point_id": "load",
        "branch": "loading",
        "displacement_angstrom": 0.01,
        "energy_eV": -1.0,
        "traction_GPa": 1.2,
        "cell_net_tangential_stress_GPa": 0.8,
    }
    constraints = {
        "area_angstrom2": 12.3,
        "interface_count": 2,
        "normalization": "area_once_no_division_by_interface_count",
        "normal_cartesian": [0.0, 0.0, 1.0],
        "reaction_definition": "reaction",
    }
    if normal:
        constraints["traction_definition"] = "traction"
        value_field = "traction_GPa"
    else:
        constraints.update({
            "tangential_cartesian": [1.0, 0.0, 0.0],
            "stress_scope": "cell_net_tangential_stress_not_single_interface_traction",
            "stiffness_scope": "adjacent_clamp_response_not_material_shear_modulus",
            "stress_definition": "stress",
        })
        value_field = "cell_net_tangential_stress_GPa"
    source = {
        "schema": schema,
        "study_id": "study",
        "case_id": "case",
        "model_id": "model",
        "model_version": "v001",
        "status": "available",
        "production_qualified": False,
        "task_id": f"{kind}-task",
        "source_task": {"scheduler_job_id": "530", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
        "interface_sources": {"study_file": "study.json"},
        "native_result": {
            "scientific_status": "evaluated_response",
            "source_files": {"atom-map.json": "saved-atom-map.json"},
        },
        response_key: {
            "status": "available",
            "relaxation_status": "converged",
            "constraints": constraints,
            "units": {"stress": "GPa"},
            "points": [point],
        },
    }
    return _write(tmp_path / f"{kind}.json", source), value_field


@pytest.mark.parametrize(
    ("kind", "property_name", "direction", "expected"),
    [
        ("interface_normal", "cell_net_normal_traction_curve", "normal_cartesian", [1.2]),
        ("interface_tangential", "cell_net_tangential_stress_curve", "tangential_cartesian", [0.8]),
    ],
)
def test_interface_curves_copy_values_coordinates_and_source_pointer(
    tmp_path, kind, property_name, direction, expected,
):
    study_path = _study(tmp_path)
    source_path, _ = _interface_source(tmp_path, kind)
    request_path = _request(tmp_path, kind, source_path, study_path)

    property_record = build_saved_domain_parameters(request_path)["properties"][0]

    assert property_record["name"] == property_name
    assert property_record["value"] == expected
    assert property_record["shape"] == [1]
    assert property_record["coordinates"][direction] == ([0.0, 0.0, 1.0] if direction == "normal_cartesian" else [1.0, 0.0, 0.0])
    assert property_record["coordinates"]["points"] == [{
        "point_id": "load", "branch": "loading", "displacement_angstrom": 0.01,
    }]
    assert property_record["conditions"]["response_ref"]["json_pointer"].endswith("response")
    assert property_record["atom_mapping_ref"] == "saved-atom-map.json"


def test_local_stress_copies_null_region_metadata_without_filling_value(tmp_path):
    study_path = _study(tmp_path)
    source = {
        "schema": "mlcc.local-stress-product.v1",
        "study_id": "study",
        "case_id": "case",
        "model_id": "model",
        "model_version": "v001",
        "status": "available",
        "production_qualified": False,
        "analysis_scheduler_job_id": "566",
        "task_id": "stress-task",
        "request_path": "saved-request.json",
        "source_task": {"scheduler_job_id": "561", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
        "source_files": {"atom-map": "saved-atom-map.json"},
        "local_stress": {
            "contribution": "virial",
            "kinetic_included": False,
            "stress_volume_basis": "lammps_prism",
            "stress_volume_component_order": ["xx", "yy", "zz"],
            "observation_window": {"start_step": 1000, "end_step": 6000},
            "regions": [{
                "region_id": "whole_cell",
                "atom_ids": [0, 1],
                "volume_source": None,
                "stress_GPa": None,
                "stress_sign": None,
                "tensor_basis": None,
                "status": "unresolved",
                "conversion": None,
            }],
        },
        "native_local_stress": {
            "tensor_basis": "lammps_prism",
            "source_cell_angstrom": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "stress_sign": "tension_positive",
            "stress_volume_unit": "bar*angstrom^3",
            "scientific_status": "engineering_sampling_not_equilibrium_qualification",
            "sampling_equilibrium_qualified": False,
        },
    }
    source_path = _write(tmp_path / "local-stress.json", source)
    request_path = _request(tmp_path, "local_stress", source_path, study_path, region_id="whole_cell")

    property_record = build_saved_domain_parameters(request_path)["properties"][0]

    assert property_record["value"] is None
    assert property_record["conditions"]["volume_source"] is None
    assert property_record["conditions"]["tensor_basis"] is None
    assert property_record["conditions"]["kinetic_included"] is False
    assert property_record["status"] == "unresolved"
    assert property_record["atom_mapping_ref"] == "saved-atom-map.json"


def test_saved_source_must_bind_to_requested_study(tmp_path):
    study_path = _study(tmp_path, case_id="other-case")
    source_path = _neb_source(tmp_path)
    request_path = _request(tmp_path, "neb_barriers", source_path, study_path)

    with pytest.raises(ValueError, match="Study identity"):
        build_saved_domain_parameters(request_path)
