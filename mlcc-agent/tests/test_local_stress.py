from __future__ import annotations

import copy

import numpy as np
import pytest

from mlcc.local_stress import local_stress_from_frames


SOURCE_CELL = [
    [2.598076211, -1.5, 0.0],
    [2.759807621, 3.314101615, 0.0],
    [0.2, 0.5, 5.0],
]


def _request(*, window: dict[str, object] | None = None, regions: list[dict[str, object]] | None = None) -> dict[str, object]:
    if window is None:
        window = {"kind": "whole_record"}
    if regions is None:
        regions = [
            {
                "region_id": "left",
                "atom_ids": [10, 30],
                "volume_angstrom3": 10.0,
                "volume_definition": "explicit_left_slab_volume",
            },
            {
                "region_id": "right",
                "atom_ids": [20],
                "volume_angstrom3": 5.0,
                "volume_definition": "explicit_right_slab_volume",
            },
        ]
    return {
        "schema": "mlcc.local-stress-analysis.v1",
        "source_kind": "mathematical_fixture",
        "fixture": True,
        "fixture_purpose": "mathematical_fixture",
        "observation_window": window,
        "regions": regions,
    }


def _frames() -> list[dict[str, object]]:
    first = {
        "step": 0,
        "physical_time_ps": 0.0,
        "atom_ids": [10, 20, 30],
        "stress_volume_components_bar_A3": [
            [100.0, 200.0, 300.0, 30.0, 40.0, 50.0],
            [10.0, 20.0, 30.0, 3.0, 4.0, 5.0],
            [-5.0, -6.0, -7.0, -1.0, -2.0, -3.0],
        ],
    }
    second = {
        "step": 10,
        "physical_time_ps": 1.0,
        "atom_ids": [20, 30, 10],
        "stress_volume_components_bar_A3": [
            [12.0, 22.0, 32.0, 4.0, 5.0, 6.0],
            [-7.0, -8.0, -9.0, -2.0, -3.0, -4.0],
            [102.0, 202.0, 302.0, 32.0, 42.0, 52.0],
        ],
    }
    return [first, second]


def _regions(result: dict[str, object]) -> dict[str, dict[str, object]]:
    return {region["region_id"]: region for region in result["regions"]}  # type: ignore[index]


def test_non_equal_atom_groups_average_extensive_sum_and_rotate_stress() -> None:
    result = local_stress_from_frames(_request(), _frames(), SOURCE_CELL)

    assert result["schema"] == "mlcc.local-stress-response.v1"
    assert result["status"] == "mathematical_fixture"
    assert result["production_qualified"] is False
    assert result["scope"] == "fixed_atom_group_virial_average"
    assert result["contribution"] == "virial"
    assert result["kinetic_included"] is False
    assert result["stress_volume_component_order"] == ["xx", "yy", "zz", "xy", "xz", "yz"]
    assert result["stress_volume_basis"] == "lammps_prism"
    assert result["thermal_stress"] is None
    assert result["missing_evidence"] == []

    left = _regions(result)["left"]
    right = _regions(result)["right"]
    left_mean = np.asarray(left["stress_volume_sum_bar_A3_mean"], dtype=float)
    right_mean = np.asarray(right["stress_volume_sum_bar_A3_mean"], dtype=float)
    np.testing.assert_allclose(left_mean, [95.0, 194.0, 293.0, 29.5, 38.5, 47.5])
    np.testing.assert_allclose(right_mean, [11.0, 21.0, 31.0, 3.5, 4.5, 5.5])
    assert left["stress_volume_sum_bar_A3_by_frame"][0]["components"] == pytest.approx(  # type: ignore[index]
        [95.0, 194.0, 293.0, 29.0, 38.0, 47.0]
    )
    assert right["volume_source"] == {  # type: ignore[index]
        "volume_angstrom3": 5.0,
        "volume_definition": "explicit_right_slab_volume",
    }

    theta = np.deg2rad(30.0)
    rotation = np.array(
        [[np.cos(theta), np.sin(theta), 0.0], [-np.sin(theta), np.cos(theta), 0.0], [0.0, 0.0, 1.0]]
    )
    native_stress = np.array(
        [
            [95.0, 29.5, 38.5],
            [29.5, 194.0, 47.5],
            [38.5, 47.5, 293.0],
        ]
    ) / 10.0 * 1.0e-4
    expected = rotation @ native_stress @ rotation.T
    expected_pressure = (-left_mean / 10.0).tolist()
    np.testing.assert_allclose(left["pressure_components_bar"], expected_pressure)
    np.testing.assert_allclose(left["stress_GPa"], expected, atol=1.0e-12)
    assert float(np.trace(np.asarray(left["stress_GPa"], dtype=float))) == pytest.approx(
        1.0e-4 * (95.0 + 194.0 + 293.0) / 10.0
    )
    assert left["stress_sign"] == "tension_positive"
    assert left["tensor_basis"] == "source_cartesian"


def test_missing_volume_keeps_extensive_sum_without_inventing_stress() -> None:
    regions = _request()["regions"]  # type: ignore[index]
    regions[1]["volume_angstrom3"] = None
    regions[1]["volume_definition"] = "awaiting_explicit_region_volume"
    result = local_stress_from_frames(_request(regions=regions), _frames(), SOURCE_CELL)

    assert result["status"] == "partial"
    right = _regions(result)["right"]
    assert right["status"] == "partial"
    assert right["stress_volume_sum_bar_A3_mean"] == pytest.approx([11.0, 21.0, 31.0, 3.5, 4.5, 5.5])
    assert right["stress_GPa"] is None
    assert "region:right:volume_angstrom3" in result["missing_evidence"]


def test_null_window_preserves_raw_frames_and_leaves_regions_unresolved() -> None:
    request = _request()
    request["observation_window"] = None
    result = local_stress_from_frames(request, _frames(), SOURCE_CELL)

    assert result["status"] == "unresolved"
    assert result["raw_frames"] == _frames()
    assert result["selected_indices"] is None
    assert result["selected_frames"] is None
    assert result["missing_evidence"] == ["observation_window"]
    assert all(region["status"] == "unresolved" for region in result["regions"])  # type: ignore[index]


def test_missing_frames_and_empty_regions_are_unresolved() -> None:
    result = local_stress_from_frames(_request(regions=[]), None, SOURCE_CELL)

    assert result["status"] == "unresolved"
    assert result["raw_frames"] is None
    assert result["regions"] == []
    assert result["missing_evidence"] == ["frames", "regions"]


def test_unknown_region_atom_id_is_original_value_error() -> None:
    regions = copy.deepcopy(_request()["regions"])  # type: ignore[index]
    regions[0]["atom_ids"] = [10, 99]

    with pytest.raises(ValueError, match="atom ID 99.*absent"):
        local_stress_from_frames(_request(regions=regions), _frames(), SOURCE_CELL)


def test_invalid_volume_is_rejected_without_zero_fill() -> None:
    regions = copy.deepcopy(_request()["regions"])  # type: ignore[index]
    regions[0]["volume_angstrom3"] = 0.0

    with pytest.raises(ValueError, match="volume_angstrom3 must be positive"):
        local_stress_from_frames(_request(regions=regions), _frames(), SOURCE_CELL)
