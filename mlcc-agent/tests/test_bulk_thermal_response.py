"""Focused tests for saved native NPT bulk-thermal response conversion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scipy.constants import Avogadro, elementary_charge

from mlcc.bulk_thermal_response import build_bulk_thermal_response


def _dump(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _source(
    root: Path,
    *,
    state_id: str,
    target_temperature: float,
    actual_temperatures: list[float] | None = None,
    volumes: list[float] | None = None,
    potential_energies: list[float] | None = None,
    seed: int = 7,
    external_pressure_bar: float = 2.0,
    omit_volume: bool = False,
) -> Path:
    state_dir = root / state_id
    source_path = state_dir / "bulk-thermal-source.json"
    steps = [1000, 3000, 6000]
    actual_temperatures = actual_temperatures or [target_temperature] * len(steps)
    volumes = volumes or [100.0] * len(steps)
    potential_energies = potential_energies or [1.0, 2.0, 3.0]
    cell = [[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 4.0]]
    frames = []
    for index, step in enumerate(steps):
        frame = {
            "step": step,
            "temperature_K": actual_temperatures[index],
            "potential_energy_eV": potential_energies[index],
            "kinetic_energy_eV": 0.5,
            "volume_angstrom3": volumes[index],
        }
        if omit_volume:
            frame.pop("volume_angstrom3")
        frames.append(frame)
    source = {
        "schema": "mlcc.md-bulk-thermal-source.v1",
        "units": "metal",
        "protocol": {
            "kind": "md",
            "purpose": "md_bulk_thermal",
            "ensemble": "npt",
            "units": "metal",
            "temperature_K": target_temperature,
            "seed": seed,
            "pressure_coupling": "iso",
        },
        "target_temperature_K": target_temperature,
        "external_pressure_bar": external_pressure_bar,
        "mechanical_constraint": {
            "kind": "isotropic",
            "shape": "fixed_shape",
            "pressure_coupling": "iso",
        },
        "atom_mapping_ref": "atom-map.json",
        "source_atom_ids": [0, 1],
        "atoms": [
            {"source_atom_id": 0, "type": 1},
            {"source_atom_id": 1, "type": 1},
        ],
        "masses_by_type": {"1": 10.0},
        "mass_units": "g/mol",
        "mass_source": "fixture masses",
        "source_cell_angstrom": cell,
        "frames": frames,
        "task_id": f"task-{state_id}",
        "study_id": "study-1",
        "model_id": "model-1",
        "model_version": "v001",
        "method_set": "method-1",
        "potential_id": "potential-1",
        "potential_version": "v001",
        "native_job": {
            "scheduler_job_id": str(seed),
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
        },
        "scientific_status": "executed_bulk_thermal_protocol",
        "production_qualification": False,
    }
    _dump(state_dir / "atom-map.json", {"source_atom_ids": [0, 1]})
    return _dump(source_path, source)


def _request(
    root: Path,
    states: list[tuple[str, Path | None]],
    *,
    reference_state_id: str = "ref",
    target_state_id: str = "target",
) -> Path:
    study_path = _dump(root / "study.json", {
        "study_id": "study-1",
        "case_id": "case-1",
        "model": {"model_id": "model-1", "version": "v001"},
    })
    state_records = []
    for state_id, source_path in states:
        record = {"state_id": state_id}
        if source_path is not None:
            record["source_path"] = str(source_path)
        state_records.append(record)
    return _dump(root / "request.json", {
        "schema": "mlcc.bulk-thermal-response-request.v1",
        "study_path": str(study_path),
        "states": state_records,
        "interval": {
            "interval_id": "thermal-1",
            "reference_state_id": reference_state_id,
            "target_state_id": target_state_id,
        },
        "observation_window": {"start_step": 1000, "end_step": 6000},
    })


def _properties(result: dict) -> dict[str, object]:
    records: dict[str, dict | list[dict]] = {}
    for property_record in result["properties"]:
        name = property_record["name"]
        if name not in records:
            records[name] = property_record
        elif isinstance(records[name], list):
            records[name].append(property_record)
        else:
            records[name] = [records[name], property_record]
    return records


def test_saved_npt_source_uses_external_pressure_and_selected_window(tmp_path: Path) -> None:
    reference = _source(
        tmp_path, state_id="ref", target_temperature=300.0,
        actual_temperatures=[300.0, 300.0, 300.0],
        volumes=[100.0, 100.0, 100.0],
        potential_energies=[1.0, 2.0, 3.0],
    )
    target = _source(
        tmp_path, state_id="target", target_temperature=400.0,
        actual_temperatures=[400.0, 400.0, 400.0],
        volumes=[110.0, 110.0, 110.0],
        potential_energies=[5.0, 6.0, 7.0],
    )
    request = _request(tmp_path, [("ref", reference), ("target", target)])

    result = build_bulk_thermal_response(request)
    properties = _properties(result)
    mass = 20.0e-3 / Avogadro
    expected_enthalpy_delta = (
        (6.5 - 2.5) * elementary_charge
        + 2.0e5 * (110.0 - 100.0) * 1.0e-30
    )
    expected_strain = (110.0 / 100.0) ** (1.0 / 3.0) - 1.0
    assert result["schema"] == "mlcc.domain-parameters.v1"
    assert result["kind"] == "bulk_thermal_response"
    assert len(result["properties"]) == 7
    densities = properties["mass_density"]
    assert isinstance(densities, list)
    assert [record["value"] for record in densities] == pytest.approx(
        [mass / 100.0e-30, mass / 110.0e-30]
    )
    assert densities[0]["unit"] == "kg/m^3"
    assert densities[0]["shape"] == []
    assert densities[0]["coordinates"] == "not_applicable_to_scalar"
    assert densities[0]["conditions"]["mean_pressure_bar"] is None
    assert properties["mass_specific_heat_cp_interval"]["value"] == pytest.approx(
        expected_enthalpy_delta / (mass * 100.0)
    )
    assert properties["isotropic_thermal_linear_strain_interval"]["value"] == pytest.approx(expected_strain)
    assert properties["isotropic_thermal_strain_tensor_interval"]["shape"] == [3, 3]
    assert properties["isotropic_thermal_strain_tensor_interval"]["coordinates"]["basis"] == "source_cartesian"
    assert properties["isotropic_thermal_strain_tensor_interval"]["value"][0][0] == pytest.approx(expected_strain)
    assert properties["isotropic_linear_thermal_expansion_interval"]["value"] == pytest.approx(expected_strain / 100.0)
    assert properties["isotropic_volumetric_thermal_expansion_interval"]["value"] == pytest.approx(0.1 / 100.0)
    assert densities[0]["conditions"]["selected_sample_count"] == 3
    assert properties["mass_specific_heat_cp_interval"]["conditions"]["external_pressure_unit"] == "bar"
    assert result["execution"]["native_jobs"][0]["scheduler_job_id"] == "7"


def test_zero_actual_delta_only_temperature_dependent_properties_are_unresolved(tmp_path: Path) -> None:
    reference = _source(
        tmp_path, state_id="ref", target_temperature=300.0,
        actual_temperatures=[300.0, 300.0, 300.0],
    )
    target = _source(
        tmp_path, state_id="target", target_temperature=400.0,
        actual_temperatures=[300.0, 300.0, 300.0],
        volumes=[110.0, 110.0, 110.0],
    )
    request = _request(tmp_path, [("ref", reference), ("target", target)])
    properties = _properties(build_bulk_thermal_response(request))

    assert all(record["status"] == "available" for record in properties["mass_density"])
    assert properties["isotropic_thermal_linear_strain_interval"]["status"] == "available"
    assert properties["isotropic_thermal_strain_tensor_interval"]["status"] == "available"
    for name in (
        "mass_specific_heat_cp_interval",
        "isotropic_linear_thermal_expansion_interval",
        "isotropic_volumetric_thermal_expansion_interval",
    ):
        assert properties[name]["status"] == "unresolved"
        assert properties[name]["value"] is None
        assert "zero" in properties[name]["conditions"]["unresolved_reason"]


@pytest.mark.parametrize("missing", ["source", "volume"])
def test_missing_source_or_required_frame_data_is_unresolved_without_zero_fill(
    tmp_path: Path, missing: str
) -> None:
    reference = None if missing == "source" else _source(tmp_path, state_id="ref", target_temperature=300.0, omit_volume=True)
    if missing == "source":
        reference = None
    target = _source(tmp_path, state_id="target", target_temperature=400.0)
    request = _request(tmp_path, [("ref", reference), ("target", target)])
    properties = _properties(build_bulk_thermal_response(request))

    reference_density = properties["mass_density"][0]
    assert reference_density["value"] is None
    assert reference_density["status"] == "unresolved"
    assert reference_density["value"] != 0
    assert properties["mass_specific_heat_cp_interval"]["value"] is None
    assert properties["mass_specific_heat_cp_interval"]["conditions"]["unresolved_reason"]


def test_interval_requires_same_seed(tmp_path: Path) -> None:
    reference = _source(tmp_path, state_id="ref", target_temperature=300.0, seed=7)
    target = _source(tmp_path, state_id="target", target_temperature=400.0, seed=8)
    request = _request(tmp_path, [("ref", reference), ("target", target)])
    with pytest.raises(ValueError, match="same seed"):
        build_bulk_thermal_response(request)
