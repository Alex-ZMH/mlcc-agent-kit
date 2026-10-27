"""Three small checks for the saved MSD, replica and occupancy bridges."""

from __future__ import annotations

import json

import pytest

from mlcc.saved_domain_parameters import build_saved_domain_parameters


def _write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _study(tmp_path):
    return _write(
        tmp_path / "study.json",
        {
            "schema": "mlcc.study.v1",
            "study_id": "study",
            "case_id": "case",
            "model": {"model_id": "model", "version": "v001", "material": "fixture"},
        },
    )


def _request(tmp_path, kind, source_path, study_path):
    return _write(
        tmp_path / f"{kind}-request.json",
        {
            "schema": "mlcc.saved-domain-parameters-request.v1",
            "kind": kind,
            "study_path": study_path.name,
            "source_path": source_path.name,
        },
    )


def test_saved_msd_properties_keep_refs_fit_and_unresolved_diffusivity(tmp_path):
    study_path = _study(tmp_path)
    source_path = _write(
        tmp_path / "msd.json",
        {
            "schema": "mlcc.md-msd.v1",
            "model": {"model_id": "model", "version": "v001", "path": "model"},
            "status": "partial",
            "scientific_status": "unqualified",
            "production_qualification": False,
            "production_qualified": False,
            "sampling_equilibrium_qualified": False,
            "task_id": "md-task",
            "analysis_scheduler_job_id": "566",
            "native_job": {"scheduler_job_id": "561", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
            "collection_path": "collection.json",
            "source_files": {"atom-map.json": "atom-map.json"},
            "units": {"MSD_A2": "angstrom^2", "lag_ps": "ps", "D_A2_per_ps": "angstrom^2/ps", "D_m2_per_s": "m^2/s"},
            "coordinate_basis": "source_cartesian",
            "dimensions": 3,
            "com_policy": "none",
            "source_atom_ids": [8, 9],
            "observation": {
                "request": {"kind": "step_range", "start_step": 1000, "end_step": 6000},
                "step_range": [1000, 6000],
                "physical_time_ps_range": [0.1, 0.6],
            },
            "MSD_A2": [0.1, 0.2],
            "lag_ps": [0.01, 0.02],
            "fick": {
                "status": "partial",
                "window_ps": [0.01, 0.1],
                "fit": {
                    "status": "available",
                    "slope_A2_per_ps": 3.4,
                    "intercept_A2": -0.1,
                    "r_squared": 0.98,
                    "relative_slope_spread": 0.4,
                },
            },
            "D_m2_per_s": None,
            "D_m2_per_s_unresolved_reason": "diagnostic thresholds",
            "diffusivity": {"status": "unresolved", "reason": "diagnostic thresholds"},
        },
    )

    product = build_saved_domain_parameters(_request(tmp_path, "md_msd", source_path, study_path))

    assert [item["name"] for item in product["properties"]] == [
        "tracer_msd_curve", "msd_fit_slope", "tracer_diffusivity",
    ]
    assert product["properties"][0]["data_ref"]["json_pointer"] == "/MSD_A2"
    assert "value" not in product["properties"][0]
    assert product["properties"][0]["coordinates"]["lag_axis"]["data_ref"]["json_pointer"] == "/lag_ps"
    assert product["properties"][0]["coordinates"]["lag_axis"]["unit"] == "ps"
    assert product["properties"][1]["value"] == 3.4
    assert product["properties"][2]["value"] is None
    assert product["properties"][2]["status"] == "unresolved"
    assert product["properties"][1]["conditions"]["fit_ref"]["json_pointer"] == "/fick/fit"


def test_saved_replicas_keep_two_seed_statistics_and_null_intervals(tmp_path):
    study_path = _study(tmp_path)
    source = {
        "schema": "mlcc.md-replica-summary.v1",
        "status": "summarized_engineering_observation",
        "scientific_status": ["unqualified", "unqualified"],
        "production_qualification": False,
        "sampling_equilibrium_qualified": False,
        "analysis_scheduler_job_id": "566",
        "observable_id": "MD_temperature_sample_mean",
        "observable": {"definition": "mean temperature", "object_level": "whole_simulation_cell", "unit": "K"},
        "replica_count": 2,
        "observed_source_count": 2,
        "statistics_status": "available",
        "statistics": {
            "mean": 300.1, "standard_deviation": 4.1, "standard_error": None,
            "confidence_interval": None, "interval_basis": "descriptive",
        },
        "interval": {"mode": "descriptive"},
        "sources": [
            {
                "model": {"model_id": "model", "version": "v001", "path": "model"},
                "task_id": "replica-1",
                "replica": {"velocity_seed": 202610261},
                "native_job": {"scheduler_job_id": "561", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
                "source_files": {"atom-map.json": "map-1.json"},
            },
            {
                "model": {"model_id": "model", "version": "v001", "path": "model"},
                "task_id": "replica-2",
                "replica": {"velocity_seed": 202610262},
                "native_job": {"scheduler_job_id": "562", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
                "source_files": {"atom-map.json": "map-2.json"},
            },
        ],
    }
    source_path = _write(tmp_path / "replicas.json", source)

    properties = build_saved_domain_parameters(_request(tmp_path, "md_replicas", source_path, study_path))["properties"]

    assert [item["name"] for item in properties] == [
        "replica_observable_mean", "replica_observable_standard_deviation",
        "replica_observable_standard_error", "replica_observable_confidence_interval",
    ]
    assert [item["status"] for item in properties] == ["available", "available", "unresolved", "unresolved"]
    assert properties[2]["value"] is None
    assert properties[3]["value"] is None
    assert properties[3]["shape"] == [2]
    assert properties[0]["atom_mapping_ref"] is None
    assert properties[0]["conditions"]["velocity_seeds"] == [202610261, 202610262]
    assert properties[0]["conditions"]["atom_mapping_refs"] == ["map-1.json", "map-2.json"]
    assert properties[0]["conditions"]["source_records_ref"]["json_pointer"] == "/sources"


def test_saved_vacancy_occupancy_uses_neb_refs_without_time_or_rate(tmp_path):
    study_path = _study(tmp_path)
    source_path = _write(
        tmp_path / "vacancy.json",
        {
            "schema": "mlcc.vacancy-migration.v1",
            "study_id": "study",
            "case_id": "case",
            "model_ref": {"model_id": "model", "version": "v001"},
            "status": "unresolved",
            "mode": "neb_path",
            "assignment_radius_angstrom": 1.0,
            "ambiguity_tolerance_angstrom": 1e-6,
            "vacancy_position_definition": "fixed host cell representative; global winding is not inferred",
            "site_image_definition": "nearest current-frame site image only; not trajectory unwrapping",
            "analysis_scheduler_job_id": "549",
            "confirmation_frames": 1,
            "observation": {"request": {"kind": "whole_record"}, "source_frame_indices": [0, 1, 2, 3]},
            "frames": [{"frame_index": 0}, {"frame_index": 1}, {"frame_index": 2}, {"frame_index": 3}],
            "site_changes": [{"status": "resolved", "from_frame_index": 1, "to_frame_index": 2}],
            "unresolved_transitions": [{"from_frame_index": 0, "to_frame_index": 1, "status": "unresolved"}],
            "source_refs": ["native-result.json"],
            "source_record": {
                "native_job": {"scheduler_job_id": "546", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
                "source_files": {"neb_result": "native-result.json"},
                "native_result": {
                    "atom_map": "atom-map.json",
                    "task_id": "neb-task",
                    "scientific_status": "neb_native_unconverged",
                    "native_converged": False,
                    "regular_native_converged": False,
                    "climbing_native_converged": False,
                    "path_endpoint_converged": True,
                    "production_qualification": False,
                },
            },
            "source_parent_record": {"source_scheduler_job_id": "121"},
        },
    )

    request_path = _request(tmp_path, "vacancy_occupancy", source_path, study_path)
    properties = build_saved_domain_parameters(request_path)["properties"]

    assert [item["name"] for item in properties] == [
        "vacancy_site_occupancy", "migration_geometric_events",
    ]
    assert [item["shape"] for item in properties] == [[4], [1]]
    assert all("value" not in item and item["status"] == "unresolved" for item in properties)
    assert properties[0]["conditions"]["physical_time_available"] is False
    assert properties[0]["conditions"]["axis_kind"] == "NEB_image_and_reaction_coordinate"
    assert properties[0]["conditions"]["assignment_radius_angstrom"] == 1.0
    assert properties[0]["conditions"]["ambiguity_tolerance_angstrom"] == 1e-6
    assert properties[0]["conditions"]["vacancy_position_definition"].startswith("fixed host")
    assert properties[0]["conditions"]["site_image_definition"].startswith("nearest current-frame")
    assert properties[1]["data_ref"]["json_pointer"] == "/site_changes"

    bad_source = json.loads(source_path.read_text(encoding="utf-8"))
    bad_source["mode"] = "md"
    bad_source_path = _write(tmp_path / "vacancy-md.json", bad_source)
    bad_request_path = _write(
        tmp_path / "vacancy-md-request.json",
        {
            "schema": "mlcc.saved-domain-parameters-request.v1",
            "kind": "vacancy_occupancy",
            "study_path": study_path.name,
            "source_path": bad_source_path.name,
        },
    )
    with pytest.raises(ValueError, match="neb_path"):
        build_saved_domain_parameters(bad_request_path)
