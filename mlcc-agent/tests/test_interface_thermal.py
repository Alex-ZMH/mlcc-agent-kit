from __future__ import annotations

import pytest

from mlcc.interface_thermal import EV_PER_PS_TO_W, thermal_response_from_samples


def _request(
    *,
    window: dict[str, object] | None = None,
    allocation: dict[str, object] | None = None,
    pairs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if window is None:
        window = {"kind": "whole_record"}
    if pairs is None:
        pairs = [
            {
                "interface_id": "AB",
                "upstream_bin_ids": [1, 2],
                "downstream_bin_ids": [3],
                "direction_sign": 1,
            },
            {
                "interface_id": "BA",
                "upstream_bin_ids": [3],
                "downstream_bin_ids": [1, 2],
                "direction_sign": -1,
            },
        ]
    return {
        "schema": "mlcc.interface-thermal-analysis.v1",
        "source_kind": "mathematical_fixture",
        "fixture": True,
        "fixture_purpose": "mathematical_fixture",
        "observation_window": window,
        "area_angstrom2": 4.0,
        "normal_cartesian": [0.0, 0.0, 1.0],
        "interface_count": 2,
        "temperature_pairs": pairs,
        "heat_allocation": allocation,
    }


def _allocation() -> dict[str, object]:
    return {
        "power_reference": "hot_input",
        "fractions": {"AB": 0.25, "BA": 0.75},
        "source": "mathematical parallel-path allocation fixture",
    }


def _energy_rows() -> list[dict[str, object]]:
    return [
        {
            "step": 0,
            "physical_time_ps": 0.0,
            "hot_reservoir_eV": 0.0,
            "cold_reservoir_eV": 0.0,
        },
        {
            "step": 10,
            "physical_time_ps": 1.0,
            "hot_reservoir_eV": -2.0,
            "cold_reservoir_eV": 1.0,
        },
    ]


def _profile_frames(*, equal_temperature: bool = False, empty_bin: bool = False) -> list[dict[str, object]]:
    first = {1: 400.0, 2: 390.0, 3: 300.0, 4: 290.0}
    second = {1: 402.0, 2: 392.0, 3: 302.0, 4: 292.0}
    if equal_temperature:
        first[2] = first[1]
        first[3] = first[1]
        second[2] = second[1]
        second[3] = second[1]
    frames: list[dict[str, object]] = []
    for step, values in ((0, first), (10, second)):
        frames.append(
            {
                "step": step,
                "physical_time_ps": step / 10.0,
                "bins": [
                    {
                        "bin_id": bin_id,
                        "coordinate_angstrom": float(bin_id),
                        "atom_count": 0 if empty_bin and bin_id == 2 else 4,
                        "temperature_K": temperature,
                    }
                    for bin_id, temperature in values.items()
                ],
            }
        )
    return frames


def _pairs(result: dict[str, object]) -> dict[str, dict[str, object]]:
    return {pair["interface_id"]: pair for pair in result["temperature"]["pairs"]}  # type: ignore[index]


def test_power_sign_units_direction_and_explicit_non_equal_split() -> None:
    result = thermal_response_from_samples(
        _request(allocation=_allocation()), _energy_rows(), _profile_frames()
    )

    assert result["schema"] == "mlcc.interface-thermal-response.v1"
    assert result["status"] == "mathematical_fixture"
    assert result["production_qualified"] is False
    assert result["source"]["fixture_purpose"] == "mathematical_fixture"  # type: ignore[index]
    assert result["steady_state"]["status"] == "unresolved"  # type: ignore[index]

    power = result["energy"]["power"]  # type: ignore[index]
    hot_w = 2.0 * EV_PER_PS_TO_W
    cold_w = EV_PER_PS_TO_W
    assert power["hot_input_eV_per_ps"] == pytest.approx(2.0)  # type: ignore[index]
    assert power["cold_extraction_eV_per_ps"] == pytest.approx(1.0)  # type: ignore[index]
    assert power["net_power_eV_per_ps"] == pytest.approx(1.0)  # type: ignore[index]
    assert power["hot_input_W"] == pytest.approx(hot_w)  # type: ignore[index]
    assert power["cold_extraction_W"] == pytest.approx(cold_w)  # type: ignore[index]
    assert power["net_power_W"] == pytest.approx(hot_w - cold_w)  # type: ignore[index]
    assert power["total_source_power_per_area_W_per_m2"] == pytest.approx(hot_w / 4.0e-20)  # type: ignore[index]
    assert result["energy"]["raw_rows"] == _energy_rows()  # type: ignore[index]

    pairs = _pairs(result)
    assert pairs["AB"]["direction_vector"] == pytest.approx([0.0, 0.0, 1.0])
    assert pairs["BA"]["direction_vector"] == pytest.approx([0.0, 0.0, -1.0])
    assert pairs["AB"]["temperature_difference_kind"] == "slab_mean_difference_not_extrapolated_jump"
    assert pairs["AB"]["temperature_difference_K"] == pytest.approx(95.0)
    assert pairs["BA"]["temperature_difference_K"] == pytest.approx(-95.0)
    area_m2 = 4.0e-20
    ab_flux = 0.25 * hot_w / area_m2
    ba_flux = 0.75 * hot_w / area_m2
    assert pairs["AB"]["heat_flux_J_W_per_m2"] == pytest.approx(ab_flux)
    assert pairs["BA"]["heat_flux_J_W_per_m2"] == pytest.approx(ba_flux)
    assert ab_flux + ba_flux == pytest.approx(power["total_source_power_per_area_W_per_m2"])  # type: ignore[index]
    assert pairs["AB"]["conductance_G_W_per_m2_K"] == pytest.approx(ab_flux / 95.0)
    assert pairs["AB"]["resistance_R_m2_K_per_W"] == pytest.approx(95.0 / ab_flux)
    assert result["missing_evidence"] == []


def test_missing_allocation_keeps_power_and_temperature_without_flux() -> None:
    result = thermal_response_from_samples(
        _request(allocation=None), _energy_rows(), _profile_frames()
    )

    assert result["status"] == "partial"
    assert result["energy"]["power"]["hot_input_W"] is not None  # type: ignore[index]
    for pair in _pairs(result).values():
        assert pair["status"] == "available_without_flux"
        assert pair["temperature_difference_K"] is not None
        assert pair["heat_flux_J_W_per_m2"] is None
        assert pair["conductance_G_W_per_m2_K"] is None
        assert pair["resistance_R_m2_K_per_W"] is None
    assert result["missing_evidence"] == ["heat_allocation"]


def test_unresolved_window_preserves_raw_samples_and_reports_dependencies() -> None:
    request = _request(window=None, allocation=_allocation())
    request["observation_window"] = None
    result = thermal_response_from_samples(request, _energy_rows(), _profile_frames())

    assert result["status"] == "unresolved"
    assert result["energy"]["raw_rows"] == _energy_rows()  # type: ignore[index]
    assert result["energy"]["selected_rows"] is None  # type: ignore[index]
    assert result["energy"]["power"]["hot_input_W"] is None  # type: ignore[index]
    assert result["temperature"]["raw_profile_frames"] == _profile_frames()  # type: ignore[index]
    assert all(pair["status"] == "unresolved" for pair in _pairs(result).values())
    assert result["missing_evidence"] == ["observation_window"]


def test_empty_profile_bin_is_unresolved_without_zero_temperature_fill() -> None:
    pairs = [
        {
            "interface_id": "AB",
            "upstream_bin_ids": [1, 2],
            "downstream_bin_ids": [3],
            "direction_sign": 1,
        },
        {
            "interface_id": "BA",
            "upstream_bin_ids": [3],
            "downstream_bin_ids": [4],
            "direction_sign": -1,
        },
    ]
    result = thermal_response_from_samples(
        _request(allocation=_allocation(), pairs=pairs),
        _energy_rows(),
        _profile_frames(empty_bin=True),
    )

    assert result["status"] == "partial"
    assert _pairs(result)["AB"]["status"] == "unresolved"
    assert _pairs(result)["AB"]["temperature_difference_K"] is None
    assert "atom_count=0" in _pairs(result)["AB"]["reason"]
    assert _pairs(result)["BA"]["status"] == "available"
    assert "temperature_bins_AB" in result["missing_evidence"]


def test_zero_denominators_only_null_the_corresponding_quotient() -> None:
    zero_flux = thermal_response_from_samples(
        _request(
            allocation={
                "power_reference": "hot_input",
                "fractions": {"AB": 0.0, "BA": 1.0},
                "source": "explicit zero-flux math fixture",
            }
        ),
        _energy_rows(),
        _profile_frames(),
    )
    ab = _pairs(zero_flux)["AB"]
    assert ab["heat_flux_J_W_per_m2"] == pytest.approx(0.0)
    assert ab["conductance_G_W_per_m2_K"] == pytest.approx(0.0)
    assert "conductance_reason" not in ab
    assert ab["resistance_R_m2_K_per_W"] is None
    assert ab["resistance_reason"] == "zero_heat_flux"

    zero_temperature = thermal_response_from_samples(
        _request(allocation=_allocation()), _energy_rows(), _profile_frames(equal_temperature=True)
    )
    ba = _pairs(zero_temperature)["BA"]
    assert ba["temperature_difference_K"] == pytest.approx(0.0)
    assert ba["conductance_G_W_per_m2_K"] is None
    assert ba["conductance_reason"] == "zero_temperature_difference"
    assert ba["resistance_R_m2_K_per_W"] == pytest.approx(0.0)


def test_empty_temperature_pair_request_does_not_select_bins() -> None:
    result = thermal_response_from_samples(
        _request(allocation=None, pairs=[]), _energy_rows(), _profile_frames()
    )

    assert result["status"] == "partial"
    assert result["energy"]["power"]["hot_input_W"] is not None  # type: ignore[index]
    assert result["temperature"]["pairs"] == []  # type: ignore[index]
    assert result["missing_evidence"] == ["temperature_pairs"]


def test_missing_native_samples_preserve_unresolved_dependencies() -> None:
    result = thermal_response_from_samples(_request(allocation=None), None, None)

    assert result["status"] == "unresolved"
    assert result["missing_evidence"] == ["energy_rows", "profile_frames", "heat_allocation"]
    assert result["energy"]["raw_rows"] is None  # type: ignore[index]
    assert result["energy"]["power"]["hot_input_W"] is None  # type: ignore[index]
    assert all(pair["status"] == "unresolved" for pair in _pairs(result).values())


def test_profile_selection_is_independent_when_energy_rows_are_missing() -> None:
    result = thermal_response_from_samples(_request(allocation=None), None, _profile_frames())

    assert result["status"] == "unresolved"
    assert result["energy"]["power"]["hot_input_W"] is None  # type: ignore[index]
    assert result["temperature"]["selection_status"] == "available"  # type: ignore[index]
    assert _pairs(result)["AB"]["temperature_difference_K"] == pytest.approx(95.0)
    assert _pairs(result)["AB"]["status"] == "available_without_flux"
    assert result["missing_evidence"] == ["energy_rows", "heat_allocation"]


def test_missing_profile_keeps_declared_flux_but_temperature_unresolved() -> None:
    result = thermal_response_from_samples(_request(allocation=_allocation()), _energy_rows(), None)

    assert result["status"] == "partial"
    assert result["energy"]["power"]["hot_input_W"] is not None  # type: ignore[index]
    ab = _pairs(result)["AB"]
    assert ab["status"] == "unresolved"
    assert ab["heat_flux_J_W_per_m2"] is not None
    assert ab["temperature_difference_K"] is None
    assert result["missing_evidence"] == ["profile_frames"]
