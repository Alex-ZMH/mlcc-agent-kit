"""Copy already-saved domain values into the common parameter envelope.

This module is deliberately a source bridge, not a scientific calculator.  It
reads one explicitly declared saved product, copies its native values and
statuses, and records JSON pointers for the larger source objects.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .domain_parameters import domain_parameter_product


REQUEST_SCHEMA = "mlcc.saved-domain-parameters-request.v1"
NEB_KIND = "neb_barriers"
NORMAL_KIND = "interface_normal"
TANGENTIAL_KIND = "interface_tangential"
LOCAL_STRESS_KIND = "local_stress"
MSD_KIND = "md_msd"
REPLICAS_KIND = "md_replicas"
VACANCY_OCCUPANCY_KIND = "vacancy_occupancy"
KINDS = {
    NEB_KIND,
    NORMAL_KIND,
    TANGENTIAL_KIND,
    LOCAL_STRESS_KIND,
    MSD_KIND,
    REPLICAS_KIND,
    VACANCY_OCCUPANCY_KIND,
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _declared_path(value: str | Path, owner: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = owner.parent / path
    return path.resolve()


def _unique_refs(*groups: Any) -> list[str]:
    refs: list[str] = []
    for group in groups:
        values = group if isinstance(group, list) else [group]
        for value in values:
            if isinstance(value, str) and value and value not in refs:
                refs.append(value)
    return refs


def _load_request(request_path: str | Path) -> tuple[
    dict[str, Any], Path, dict[str, Any], Path, dict[str, Any]
]:
    request_file = Path(request_path).expanduser().resolve()
    request = _read_json(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA}")
    kind = request["kind"]
    if kind not in KINDS:
        raise ValueError(f"unsupported saved domain-parameter kind: {kind}")
    study_path = _declared_path(request["study_path"], request_file)
    study = _read_json(study_path)
    source_path = _declared_path(request["source_path"], request_file)
    source = _read_json(source_path)
    return request, study_path, study, source_path, source


def _study_record(study: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    model = copy.deepcopy(study["model"])
    return (
        {"study_id": study["study_id"], "case_id": study["case_id"]},
        model,
    )


def _require_identity(
    *,
    source: dict[str, Any],
    study: dict[str, Any],
    source_model: dict[str, Any],
    label: str,
) -> None:
    if source["study_id"] != study["study_id"] or source["case_id"] != study["case_id"]:
        raise ValueError(f"{label} Study identity differs from saved Study")
    study_model = study["model"]
    if (
        source_model["model_id"] != study_model["model_id"]
        or source_model["version"] != study_model["version"]
    ):
        raise ValueError(f"{label} model identity differs from saved Study")


def _property(
    *,
    name: str,
    value: Any,
    unit: str,
    shape: list[int],
    definition: str,
    conditions: dict[str, Any],
    coordinates: Any,
    atom_mapping_ref: str | None,
    source_refs: list[str],
    status: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "value": copy.deepcopy(value),
        "unit": unit,
        "shape": copy.deepcopy(shape),
        "definition": definition,
        "conditions": copy.deepcopy(conditions),
        "coordinates": copy.deepcopy(coordinates),
        "atom_mapping_ref": atom_mapping_ref,
        "source_refs": _unique_refs(source_refs),
        "status": status,
    }


def _referenced_property(
    *,
    name: str,
    unit: str,
    shape: list[int],
    definition: str,
    conditions: dict[str, Any],
    coordinates: Any,
    atom_mapping_ref: str | None,
    source_refs: list[str],
    status: Any,
    source_path: Path,
    json_pointer: str,
) -> dict[str, Any]:
    property_record = _property(
        name=name,
        value=None,
        unit=unit,
        shape=shape,
        definition=definition,
        conditions=conditions,
        coordinates=coordinates,
        atom_mapping_ref=atom_mapping_ref,
        source_refs=source_refs,
        status=status,
    )
    del property_record["value"]
    property_record["data_ref"] = {
        "path": str(source_path),
        "json_pointer": json_pointer,
    }
    return property_record


def _require_model_identity(
    *,
    source_model: dict[str, Any],
    study: dict[str, Any],
    label: str,
) -> None:
    study_model = study["model"]
    if (
        source_model["model_id"] != study_model["model_id"]
        or source_model["version"] != study_model["version"]
    ):
        raise ValueError(f"{label} model identity differs from saved Study")


def _neb_properties(
    *,
    source: dict[str, Any],
    source_path: Path,
    study_path: Path,
    study: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source["schema"] != "mlcc.vacancy-migration.v1":
        raise ValueError("saved NEB source schema must be mlcc.vacancy-migration.v1")
    source_record = source["source_record"]
    native = source_record["native_result"]
    _require_identity(
        source=source,
        study=study,
        source_model=source_record["model"],
        label="saved NEB source",
    )

    protocol = native["protocol"]
    barrier = source_record["barrier"]
    regular = {
        "images": protocol["images"],
        "ranks_per_image": protocol["ranks_per_image"],
        "min_style": protocol["min_style"],
        "timestep_ps": protocol["timestep_ps"],
        "etol": protocol["etol"],
        "ftol_eV_per_angstrom": protocol["ftol_eV_per_angstrom"],
        "max_iterations": protocol["max_iterations"],
        "output_every": protocol["output_every"],
        "spring_eV_per_angstrom2": protocol["spring_eV_per_angstrom2"],
    }
    climbing = {
        "climb_iterations": protocol["climb_iterations"],
        "climbing_replica": barrier["climbing_replica"],
        "climbing_replica_zero_based": barrier["climbing_replica_zero_based"],
        "climbing_replica_energy_eV": barrier["climbing_replica_energy_eV"],
        "climbing_replica_is_endpoint": barrier["climbing_replica_is_endpoint"],
        "highest_image_is_climbing_replica": barrier["highest_image_is_climbing_replica"],
    }
    path_endpoint = {
        "endpoint_policy": protocol["endpoint_policy"],
        "endpoint_minimization": copy.deepcopy(protocol["endpoint_minimization"]),
        "highest_final_image": barrier["highest_final_image"],
        "highest_final_image_is_endpoint": barrier["highest_final_image_is_endpoint"],
    }
    conditions = {
        "source_status": source["status"],
        "source_record_ref": {
            "path": str(source_path),
            "json_pointer": "/source_record",
        },
        "native_result_ref": {
            "path": str(source_path),
            "json_pointer": "/source_record/native_result",
        },
        "regular": regular,
        "climbing": climbing,
        "path_endpoint": path_endpoint,
        "native_convergence": {
            "scientific_status": native["scientific_status"],
            "native_converged": native["native_converged"],
            "regular_native_converged": native["regular_native_converged"],
            "climbing_native_converged": native["climbing_native_converged"],
            "path_endpoint_converged": native["path_endpoint_converged"],
        },
        "analysis_scheduler_job_id": source["analysis_scheduler_job_id"],
        "native_job": copy.deepcopy(source_record["native_job"]),
    }
    atom_mapping_ref = native["source_files"]["atom-map.json"]
    refs = _unique_refs(
        source_path.as_posix(),
        study_path.as_posix(),
        source.get("source_refs", []),
        source_record["source_files"]["neb_result"],
    )
    properties = [
        _property(
            name="neb_forward_barrier_candidate",
            value=barrier["forward_eV"],
            unit="eV",
            shape=[],
            definition="saved forward NEB barrier candidate from source_record.barrier.forward_eV",
            conditions=conditions,
            coordinates="not_applicable_to_scalar",
            atom_mapping_ref=atom_mapping_ref,
            source_refs=refs,
            status=source["status"],
        ),
        _property(
            name="neb_backward_barrier_candidate",
            value=barrier["backward_eV"],
            unit="eV",
            shape=[],
            definition="saved backward NEB barrier candidate from source_record.barrier.backward_eV",
            conditions=conditions,
            coordinates="not_applicable_to_scalar",
            atom_mapping_ref=atom_mapping_ref,
            source_refs=refs,
            status=source["status"],
        ),
    ]
    job = copy.deepcopy(source_record["native_job"])
    task_id = native.get("task_id")
    if task_id is not None:
        job["task_id"] = task_id
    return properties, [job]


def _interface_property(
    *,
    source: dict[str, Any],
    source_path: Path,
    study_path: Path,
    study: dict[str, Any],
    response_key: str,
    response_ref_name: str,
    value_field: str,
    direction_field: str,
    property_name: str,
    definition: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    response = source[response_key]
    constraints = response["constraints"]
    points = response["points"]
    native = source["native_result"]
    _require_identity(
        source=source,
        study=study,
        source_model={"model_id": source["model_id"], "version": source["model_version"]},
        label=f"saved {response_ref_name} source",
    )
    coordinates = {
        "basis": "source_cartesian",
        direction_field: copy.deepcopy(constraints[direction_field]),
        "points": [
            {
                "point_id": point["point_id"],
                "branch": point["branch"],
                "displacement_angstrom": point["displacement_angstrom"],
            }
            for point in points
        ],
    }
    conditions = {
        "source_status": source["status"],
        "response_status": response["status"],
        "relaxation_status": response["relaxation_status"],
        "production_qualified": source["production_qualified"],
        "area_angstrom2": constraints["area_angstrom2"],
        "interface_count": constraints["interface_count"],
        "normalization": constraints["normalization"],
        "definitions": {
            key: copy.deepcopy(constraints[key])
            for key in constraints
            if key.endswith("definition") or key.endswith("scope")
        },
        "response_units": copy.deepcopy(response["units"]),
        "response_ref": {
            "path": str(source_path),
            "json_pointer": f"/{response_key}",
        },
        "native_result_ref": {
            "path": str(source_path),
            "json_pointer": "/native_result",
        },
        "source_task": copy.deepcopy(source["source_task"]),
        "native_scientific_status": native["scientific_status"],
    }
    interface_sources = source["interface_sources"]
    refs = _unique_refs(
        source_path.as_posix(),
        study_path.as_posix(),
        interface_sources["study_file"],
    )
    atom_mapping_ref = native["source_files"]["atom-map.json"]
    value = [point[value_field] for point in points]
    property_record = _property(
        name=property_name,
        value=value,
        unit="GPa",
        shape=[len(value)],
        definition=definition,
        conditions=conditions,
        coordinates=coordinates,
        atom_mapping_ref=atom_mapping_ref,
        source_refs=refs,
        status=source["status"],
    )
    job = copy.deepcopy(source["source_task"])
    job["task_id"] = source["task_id"]
    return [property_record], [job]


def _normal_properties(
    *,
    source: dict[str, Any],
    source_path: Path,
    study_path: Path,
    study: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source["schema"] != "mlcc.interface-normal-product.v1":
        raise ValueError("saved normal source schema must be mlcc.interface-normal-product.v1")
    return _interface_property(
        source=source,
        source_path=source_path,
        study_path=study_path,
        study=study,
        response_key="normal_response",
        response_ref_name="interface-normal",
        value_field="traction_GPa",
        direction_field="normal_cartesian",
        property_name="cell_net_normal_traction_curve",
        definition="saved periodic-cell net normal traction curve from normal_response.points[*].traction_GPa",
    )


def _tangential_properties(
    *,
    source: dict[str, Any],
    source_path: Path,
    study_path: Path,
    study: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source["schema"] != "mlcc.interface-tangential-product.v1":
        raise ValueError("saved tangential source schema must be mlcc.interface-tangential-product.v1")
    return _interface_property(
        source=source,
        source_path=source_path,
        study_path=study_path,
        study=study,
        response_key="tangential_response",
        response_ref_name="interface-tangential",
        value_field="cell_net_tangential_stress_GPa",
        direction_field="tangential_cartesian",
        property_name="cell_net_tangential_stress_curve",
        definition="saved periodic-cell net tangential stress curve, not a single-interface traction",
    )


def _local_stress_properties(
    *,
    source: dict[str, Any],
    source_path: Path,
    study_path: Path,
    study: dict[str, Any],
    region_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source["schema"] != "mlcc.local-stress-product.v1":
        raise ValueError("saved local-stress source schema must be mlcc.local-stress-product.v1")
    _require_identity(
        source=source,
        study=study,
        source_model={"model_id": source["model_id"], "version": source["model_version"]},
        label="saved local-stress source",
    )
    local_stress = source["local_stress"]
    regions = local_stress["regions"]
    region_index = next(index for index, region in enumerate(regions) if region["region_id"] == region_id)
    region = regions[region_index]
    native = source["native_local_stress"]
    coordinates = {
        "basis": region["tensor_basis"],
        "source_cell_angstrom": copy.deepcopy(native["source_cell_angstrom"]),
        "component_order": copy.deepcopy(local_stress["stress_volume_component_order"]),
    }
    conditions = {
        "region_id": region["region_id"],
        "atom_ids": copy.deepcopy(region["atom_ids"]),
        "volume_source": copy.deepcopy(region["volume_source"]),
        "stress_sign": region["stress_sign"],
        "tensor_basis": region["tensor_basis"],
        "region_status": region["status"],
        "conversion": copy.deepcopy(region["conversion"]),
        "contribution": local_stress["contribution"],
        "kinetic_included": local_stress["kinetic_included"],
        "stress_volume_basis": local_stress["stress_volume_basis"],
        "native_stress_volume_basis": native["tensor_basis"],
        "stress_volume_unit": native["stress_volume_unit"],
        "component_order": copy.deepcopy(local_stress["stress_volume_component_order"]),
        "window": copy.deepcopy(local_stress["observation_window"]),
        "source_status": source["status"],
        "scientific_status": native["scientific_status"],
        "sampling_equilibrium_qualified": native["sampling_equilibrium_qualified"],
        "production_qualified": source["production_qualified"],
        "analysis_scheduler_job_id": source["analysis_scheduler_job_id"],
        "source_task": copy.deepcopy(source["source_task"]),
        "response_ref": {
            "path": str(source_path),
            "json_pointer": f"/local_stress/regions/{region_index}",
        },
        "native_result_ref": {
            "path": str(source_path),
            "json_pointer": "/native_local_stress",
        },
    }
    refs = _unique_refs(
        source_path.as_posix(),
        study_path.as_posix(),
        source["request_path"],
    )
    atom_mapping_ref = source["source_files"]["atom-map"]
    property_record = _property(
        name="regional_virial_stress_tensor",
        value=region["stress_GPa"],
        unit="GPa",
        shape=[3, 3],
        definition="saved regional virial stress tensor; kinetic contribution is not included",
        conditions=conditions,
        coordinates=coordinates,
        atom_mapping_ref=atom_mapping_ref,
        source_refs=refs,
        status=region["status"],
    )
    job = copy.deepcopy(source["source_task"])
    job["task_id"] = source["task_id"]
    return [property_record], [job]


def _md_msd_properties(
    *,
    source: dict[str, Any],
    source_path: Path,
    study_path: Path,
    study: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source["schema"] != "mlcc.md-msd.v1":
        raise ValueError("saved MSD source schema must be mlcc.md-msd.v1")
    _require_model_identity(
        source_model=source["model"], study=study, label="saved MSD source",
    )
    units = source["units"]
    observation = source["observation"]
    observation_record = {
        "request": copy.deepcopy(observation["request"]),
        "step_range": copy.deepcopy(observation["step_range"]),
        "physical_time_ps_range": copy.deepcopy(observation["physical_time_ps_range"]),
    }
    native_job = copy.deepcopy(source["native_job"])
    native_job["task_id"] = source["task_id"]
    atom_mapping_ref = source["source_files"]["atom-map.json"]
    refs = _unique_refs(
        source_path.as_posix(), study_path.as_posix(), source["collection_path"], atom_mapping_ref,
    )
    common_conditions = {
        "source_status": source["status"],
        "scientific_status": source["scientific_status"],
        "production_qualification": source["production_qualification"],
        "production_qualified": source["production_qualified"],
        "sampling_equilibrium_qualified": source["sampling_equilibrium_qualified"],
        "analysis_scheduler_job_id": source["analysis_scheduler_job_id"],
        "native_job": copy.deepcopy(source["native_job"]),
        "observation": observation_record,
        "dimensions": source["dimensions"],
        "com_policy": source["com_policy"],
        "source_atom_ids": copy.deepcopy(source["source_atom_ids"]),
    }
    fit = source["fick"]["fit"]
    fit_conditions = {
        **common_conditions,
        "fick_status": source["fick"]["status"],
        "window_ps": copy.deepcopy(source["fick"]["window_ps"]),
        "intercept_A2": fit["intercept_A2"],
        "r_squared": fit["r_squared"],
        "relative_slope_spread": fit["relative_slope_spread"],
        "fit_status": fit["status"],
        "fit_ref": {"path": str(source_path), "json_pointer": "/fick/fit"},
    }
    diffusivity = source["diffusivity"]
    diffusivity_conditions = {
        **common_conditions,
        "diffusivity_ref": {"path": str(source_path), "json_pointer": "/diffusivity"},
        "diffusivity_reason": diffusivity["reason"],
        "unresolved_reason": source["D_m2_per_s_unresolved_reason"],
    }
    properties = [
        _referenced_property(
            name="tracer_msd_curve",
            unit=units["MSD_A2"],
            shape=[len(source["MSD_A2"])],
            definition="saved tracer mean-square-displacement curve",
            conditions={**common_conditions, "msd_ref": {"path": str(source_path), "json_pointer": "/MSD_A2"}},
            coordinates={
                "basis": source["coordinate_basis"],
                "lag_axis": {
                    "data_ref": {"path": str(source_path), "json_pointer": "/lag_ps"},
                    "unit": units["lag_ps"],
                },
            },
            atom_mapping_ref=atom_mapping_ref,
            source_refs=refs,
            status=source["status"],
            source_path=source_path,
            json_pointer="/MSD_A2",
        ),
        _property(
            name="msd_fit_slope",
            value=fit["slope_A2_per_ps"],
            unit=units["D_A2_per_ps"],
            shape=[],
            definition="saved Fick-window MSD fit slope",
            conditions=fit_conditions,
            coordinates="not_applicable_to_scalar",
            atom_mapping_ref=atom_mapping_ref,
            source_refs=refs,
            status=fit["status"],
        ),
        _property(
            name="tracer_diffusivity",
            value=source["D_m2_per_s"],
            unit=units["D_m2_per_s"],
            shape=[],
            definition="saved tracer diffusivity value; no value is inferred from an unresolved diagnostic",
            conditions=diffusivity_conditions,
            coordinates="not_applicable_to_scalar",
            atom_mapping_ref=atom_mapping_ref,
            source_refs=refs,
            status=diffusivity["status"],
        ),
    ]
    return properties, [native_job]


def _md_replica_properties(
    *,
    source: dict[str, Any],
    source_path: Path,
    study_path: Path,
    study: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source["schema"] != "mlcc.md-replica-summary.v1":
        raise ValueError("saved replica source schema must be mlcc.md-replica-summary.v1")
    sources = source["sources"]
    native_jobs: list[dict[str, Any]] = []
    atom_map_refs: list[str] = []
    replica_seeds: list[Any] = []
    refs = [source_path.as_posix(), study_path.as_posix()]
    for replica_source in sources:
        _require_model_identity(
            source_model=replica_source["model"], study=study, label="saved replica source",
        )
        job = copy.deepcopy(replica_source["native_job"])
        job["task_id"] = replica_source["task_id"]
        native_jobs.append(job)
        atom_map_ref = replica_source["source_files"]["atom-map.json"]
        atom_map_refs.append(atom_map_ref)
        replica_seeds.append(replica_source["replica"]["velocity_seed"])
        refs.extend([atom_map_ref, replica_source["model"]["path"]])
    statistics = source["statistics"]
    observable = source["observable"]
    conditions = {
        "observable_id": source["observable_id"],
        "definition": observable["definition"],
        "object_level": observable["object_level"],
        "replica_count": source["replica_count"],
        "observed_source_count": source["observed_source_count"],
        "statistics_status": source["statistics_status"],
        "source_status": source["status"],
        "scientific_status": copy.deepcopy(source["scientific_status"]),
        "production_qualification": source["production_qualification"],
        "sampling_equilibrium_qualified": source["sampling_equilibrium_qualified"],
        "statistics_interval_basis": statistics["interval_basis"],
        "interval": copy.deepcopy(source["interval"]),
        "velocity_seeds": replica_seeds,
        "atom_mapping_refs": atom_map_refs,
        "source_records_ref": {"path": str(source_path), "json_pointer": "/sources"},
        "native_jobs": copy.deepcopy(native_jobs),
        "analysis_scheduler_job_id": source["analysis_scheduler_job_id"],
    }
    unit = observable["unit"]
    scalar_coordinates = "not_applicable_to_whole_cell_scalar"
    mean_status = source["statistics_status"]
    optional_status = "unresolved" if statistics["standard_error"] is None else source["statistics_status"]
    ci_status = "unresolved" if statistics["confidence_interval"] is None else source["statistics_status"]
    properties = [
        _property(
            name="replica_observable_mean",
            value=statistics["mean"],
            unit=unit,
            shape=[],
            definition=observable["definition"],
            conditions=conditions,
            coordinates=scalar_coordinates,
            atom_mapping_ref=None,
            source_refs=refs,
            status=mean_status,
        ),
        _property(
            name="replica_observable_standard_deviation",
            value=statistics["standard_deviation"],
            unit=unit,
            shape=[],
            definition="saved descriptive standard deviation across replica observations",
            conditions=conditions,
            coordinates=scalar_coordinates,
            atom_mapping_ref=None,
            source_refs=refs,
            status=mean_status,
        ),
        _property(
            name="replica_observable_standard_error",
            value=statistics["standard_error"],
            unit=unit,
            shape=[],
            definition="saved replica standard error; null remains unresolved",
            conditions=conditions,
            coordinates=scalar_coordinates,
            atom_mapping_ref=None,
            source_refs=refs,
            status=optional_status,
        ),
        _property(
            name="replica_observable_confidence_interval",
            value=statistics["confidence_interval"],
            unit=unit,
            shape=[2],
            definition="saved replica confidence interval; null remains unresolved",
            conditions=conditions,
            coordinates=scalar_coordinates,
            atom_mapping_ref=None,
            source_refs=refs,
            status=ci_status,
        ),
    ]
    return properties, native_jobs


def _vacancy_occupancy_properties(
    *,
    source: dict[str, Any],
    source_path: Path,
    study_path: Path,
    study: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source["schema"] != "mlcc.vacancy-migration.v1":
        raise ValueError("saved vacancy-occupancy source schema must be mlcc.vacancy-migration.v1")
    if source["mode"] != "neb_path":
        raise ValueError("saved vacancy occupancy requires a neb_path source")
    _require_identity(
        source=source,
        study=study,
        source_model=source["model_ref"],
        label="saved vacancy-occupancy source",
    )
    source_record = source["source_record"]
    native = source_record["native_result"]
    atom_mapping_ref = native["atom_map"]
    native_job = copy.deepcopy(source_record["native_job"])
    native_job["task_id"] = native["task_id"]
    conditions = {
        "source_status": source["status"],
        "source_mode": source["mode"],
        "assignment_radius_angstrom": source["assignment_radius_angstrom"],
        "ambiguity_tolerance_angstrom": source["ambiguity_tolerance_angstrom"],
        "vacancy_position_definition": source["vacancy_position_definition"],
        "site_image_definition": source["site_image_definition"],
        "observation": copy.deepcopy(source["observation"]),
        "confirmation_frames": source["confirmation_frames"],
        "axis_kind": "NEB_image_and_reaction_coordinate",
        "physical_time_available": False,
        "field_units": {
            "image_index": "dimensionless",
            "reaction_coordinate": "dimensionless",
            "distance_angstrom": "angstrom",
            "vacancy_position_angstrom": "angstrom",
            "physical_time_ps": "ps",
        },
        "frames_ref": {"path": str(source_path), "json_pointer": "/frames"},
        "site_changes_ref": {"path": str(source_path), "json_pointer": "/site_changes"},
        "unresolved_transitions_ref": {
            "path": str(source_path), "json_pointer": "/unresolved_transitions",
        },
        "native_convergence": {
            "scientific_status": native["scientific_status"],
            "native_converged": native["native_converged"],
            "regular_native_converged": native["regular_native_converged"],
            "climbing_native_converged": native["climbing_native_converged"],
            "path_endpoint_converged": native["path_endpoint_converged"],
        },
        "production_qualification": native["production_qualification"],
        "analysis_scheduler_job_id": source["analysis_scheduler_job_id"],
        "native_job": copy.deepcopy(source_record["native_job"]),
        "source_parent_job": source["source_parent_record"]["source_scheduler_job_id"],
    }
    refs = _unique_refs(
        source_path.as_posix(),
        study_path.as_posix(),
        source.get("source_refs", []),
        source_record["source_files"]["neb_result"],
        atom_mapping_ref,
    )
    coordinates = {
        "basis": "source_cartesian",
        "axis_kind": "NEB_image_and_reaction_coordinate",
        "physical_time_axis": None,
    }
    properties = [
        _referenced_property(
            name="vacancy_site_occupancy",
            unit="dimensionless",
            shape=[len(source["frames"])],
            definition="saved per-NEB-image site occupancy and vacancy assignment records",
            conditions=conditions,
            coordinates=coordinates,
            atom_mapping_ref=atom_mapping_ref,
            source_refs=refs,
            status=source["status"],
            source_path=source_path,
            json_pointer="/frames",
        ),
        _referenced_property(
            name="migration_geometric_events",
            unit="dimensionless",
            shape=[len(source["site_changes"])],
            definition="saved geometric vacancy-site changes between adjacent resolved NEB images",
            conditions=conditions,
            coordinates=coordinates,
            atom_mapping_ref=atom_mapping_ref,
            source_refs=refs,
            status=source["status"],
            source_path=source_path,
            json_pointer="/site_changes",
        ),
    ]
    return properties, [native_job]


def build_saved_domain_parameters(request_path: str | Path) -> dict[str, Any]:
    """Build a domain envelope from one explicitly declared saved product."""

    request, study_path, study, source_path, source = _load_request(request_path)
    study_record, model = _study_record(study)
    kind = request["kind"]
    if kind == NEB_KIND:
        properties, native_jobs = _neb_properties(
            source=source, source_path=source_path, study_path=study_path, study=study,
        )
    elif kind == NORMAL_KIND:
        properties, native_jobs = _normal_properties(
            source=source, source_path=source_path, study_path=study_path, study=study,
        )
    elif kind == TANGENTIAL_KIND:
        properties, native_jobs = _tangential_properties(
            source=source, source_path=source_path, study_path=study_path, study=study,
        )
    elif kind == MSD_KIND:
        properties, native_jobs = _md_msd_properties(
            source=source, source_path=source_path, study_path=study_path, study=study,
        )
    elif kind == REPLICAS_KIND:
        properties, native_jobs = _md_replica_properties(
            source=source, source_path=source_path, study_path=study_path, study=study,
        )
    elif kind == VACANCY_OCCUPANCY_KIND:
        properties, native_jobs = _vacancy_occupancy_properties(
            source=source, source_path=source_path, study_path=study_path, study=study,
        )
    else:
        properties, native_jobs = _local_stress_properties(
            source=source,
            source_path=source_path,
            study_path=study_path,
            study=study,
            region_id=request["region_id"],
        )
    for property_record in properties:
        property_record["source_refs"] = _unique_refs(property_record["source_refs"], study_path.as_posix())
    execution = {
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "native_jobs": native_jobs,
    }
    return domain_parameter_product(
        kind=kind,
        model=model,
        study=study_record,
        properties=properties,
        execution=execution,
    )


__all__ = ["REQUEST_SCHEMA", "build_saved_domain_parameters"]
