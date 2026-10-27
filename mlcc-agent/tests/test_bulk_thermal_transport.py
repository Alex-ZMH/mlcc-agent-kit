"""Focused tests for saved single-direction NEMD transport conversion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scipy.constants import elementary_charge

from mlcc.bulk_thermal_transport import build_bulk_thermal_transport


def _dump(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _fixture(
    root: Path,
    *,
    empty_bin: int | None = None,
    zero_gradient: bool = False,
    missing_energy: bool = False,
    missing_window: bool = False,
) -> Path:
    identity = {
        "study_id": "study-1",
        "case_id": "case-1",
        "model_id": "model-1",
        "model_version": "v001",
        "method_set": "lammps-czo-nemd-v001",
        "task_id": "task-nemd-1",
        "scheduler_job_id": "615",
    }
    model_directory = root / "model"
    _dump(model_directory / "model.json", {"schema": "mlcc.model.v1", "model_id": "model-1", "version": "v001"})
    study_path = _dump(root / "study.json", {
        "study_id": "study-1",
        "case_id": "case-1",
        "model": {"model_id": "model-1", "version": "v001"},
    })
    task = {
        **identity,
        "status": "COMPLETED",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "potential": {"potential_id": "potential-1", "version": "v146"},
    }
    task_path = _dump(root / "task.json", task)
    result = {
        "schema": "mlcc.lammps-result.v1",
        **identity,
        "version": "v001",
        "status": "COMPLETED",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "source_files": {"native": "native-output"},
    }
    result_path = _dump(root / "result.json", result)

    source_atom_ids = list(range(80))
    source_dir = root / "source"
    source_path = source_dir / "bulk-heat-source.json"
    _dump(source_dir / "atom-map.json", {"source_atom_ids": source_atom_ids})
    cell = [[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 20.0]]
    steps = [1000, 2000, 3000]
    energy_rows = [
        {"step": step, "physical_time_ps": float(index + 1),
         "hot_reservoir_eV": float(index), "cold_reservoir_eV": float(-index)}
        for index, step in enumerate(steps)
    ]
    profile_frames = []
    for index, step in enumerate(steps):
        bins = []
        for bin_id in range(3, 9):
            temperature = 300.0 if zero_gradient else 300.0 + 2.0 * bin_id
            record = {
                "bin_id": bin_id,
                "coordinate_reduced": float(bin_id) / 16.0,
                "coordinate_angstrom": float(bin_id),
                "atom_count": 5,
                "temperature_K": temperature + 0.1 * index,
            }
            if empty_bin == bin_id and index == 1:
                record["atom_count"] = 0
            bins.append(record)
        profile_frames.append({"step": step, "physical_time_ps": float(index + 1), "total_count": 30, "bins": bins})
    source = {
        "schema": "mlcc.md-bulk-heat-source.v1",
        "units": "metal",
        "protocol": {"kind": "md", "purpose": "bulk_thermal_transport"},
        "energy_rows": [] if missing_energy else energy_rows,
        "profile_frames": profile_frames,
        "source_atom_ids": source_atom_ids,
        "atoms": [{"source_atom_id": atom_id, "native_atom_id": atom_id, "element": "O"} for atom_id in source_atom_ids],
        "cell_angstrom": cell,
        "atom_mapping_ref": "atom-map.json",
        "geometry": {"area_angstrom2": 25.0, "normal_cartesian": [0, 0, 1], "z_length_angstrom": 20.0},
        "source_files": {"atom-map.json": "atom-map.json"},
        "reservoir_tally_convention": {
            "quantity": "cumulative_reservoir_energy",
            "native_definition": "fix_langevin_tally_energy",
            "positive_direction": "native_lammps_tally",
            "sign_transform": {"hot": "negative_slope", "cold": "positive_slope"},
        },
        "missing_evidence": [],
    }
    _dump(source_path, source)
    observation_window = {"kind": "step_range", "start_step": 1000, "end_step": 3000}
    if missing_window:
        observation_window = {"kind": "step_range", "start_step": 1500, "end_step": 3000}
    request = {
        "schema": "mlcc.bulk-thermal-transport-request.v1",
        "study_path": str(study_path),
        "model_path": str(model_directory),
        "source_path": str(source_path),
        "task_path": str(task_path),
        "result_path": str(result_path),
        "transport": {
            "direction_cartesian": [0, 0, 1],
            "profile_bin_ids": [3, 4, 5, 6, 7, 8],
            "periodic_channel_count": 2,
            "heat_fraction": 0.5,
            "heat_fraction_basis": "declared_equal_split_not_measured",
        },
    }
    if not missing_window:
        request["observation_window"] = observation_window
    return _dump(root / "request.json", request)


def _by_name(result: dict) -> dict[str, dict]:
    return {record["name"]: record for record in result["properties"]}


def test_saved_nemd_uses_signed_ols_powers_and_directional_response(tmp_path: Path) -> None:
    result = build_bulk_thermal_transport(_fixture(tmp_path))
    properties = _by_name(result)
    conversion = elementary_charge * 1.0e12
    assert result["schema"] == "mlcc.domain-parameters.v1"
    assert result["kind"] == "bulk_thermal_transport"
    assert properties["hot_reservoir_input_power"]["value"] == pytest.approx(-conversion)
    assert properties["cold_reservoir_extraction_power"]["value"] == pytest.approx(-conversion)
    assert properties["reservoir_net_power"]["value"] == pytest.approx(0.0)
    expected_flux = -0.5 * conversion / (25.0 * 1.0e-20)
    assert properties["directional_heat_flux"]["value"] == pytest.approx(expected_flux)
    assert properties["directional_temperature_gradient"]["value"] == pytest.approx(2.0e10)
    assert properties["directional_temperature_gradient"]["conditions"]["gradient_K_per_angstrom"] == pytest.approx(2.0)
    assert properties["directional_thermal_conductivity"]["value"] == pytest.approx(-expected_flux / 2.0e10)
    assert properties["hot_reservoir_input_power"]["conditions"]["sign_definition"] == "P_hot=-slope(Q_hot)"
    assert properties["directional_heat_flux"]["conditions"]["heat_fraction_basis"] == "declared_equal_split_not_measured"
    assert properties["directional_heat_flux"]["coordinates"]["basis"] == "source_cartesian"
    assert properties["directional_heat_flux"]["coordinates"]["direction_cartesian"] == [0, 0, 1]
    assert properties["hot_reservoir_input_power"]["atom_mapping_ref"].endswith("atom-map.json")


def test_empty_profile_bin_keeps_bin_record_and_unresolves_gradient_only(tmp_path: Path) -> None:
    properties = _by_name(build_bulk_thermal_transport(_fixture(tmp_path, empty_bin=5)))
    assert properties["hot_reservoir_input_power"]["status"] == "available"
    assert properties["directional_heat_flux"]["status"] == "available"
    assert properties["directional_temperature_gradient"]["status"] == "unresolved"
    assert properties["directional_temperature_gradient"]["value"] is None
    profile = properties["directional_temperature_gradient"]["conditions"]["profile"]
    empty = next(record for record in profile["bins"] if record["bin_id"] == 5)
    assert empty["atom_count_by_frame"] == [5, 0, 5]
    assert properties["directional_thermal_conductivity"]["value"] is None


def test_zero_temperature_gradient_keeps_zero_gradient_and_unresolves_kappa(tmp_path: Path) -> None:
    properties = _by_name(build_bulk_thermal_transport(_fixture(tmp_path, zero_gradient=True)))
    assert properties["directional_temperature_gradient"]["status"] == "available"
    assert properties["directional_temperature_gradient"]["value"] == pytest.approx(0.0)
    assert properties["directional_thermal_conductivity"]["status"] == "unresolved"
    assert "zero" in properties["directional_thermal_conductivity"]["conditions"]["unresolved_reason"]


@pytest.mark.parametrize("missing", ["energy", "window"])
def test_missing_energy_or_window_unresolves_only_dependent_properties(tmp_path: Path, missing: str) -> None:
    request = _fixture(tmp_path, missing_energy=missing == "energy", missing_window=missing == "window")
    properties = _by_name(build_bulk_thermal_transport(request))
    assert properties["hot_reservoir_input_power"]["value"] is None
    assert properties["cold_reservoir_extraction_power"]["value"] is None
    assert properties["directional_heat_flux"]["value"] is None
    if missing == "energy":
        assert properties["directional_temperature_gradient"]["status"] == "available"
    else:
        assert properties["directional_temperature_gradient"]["value"] is None
