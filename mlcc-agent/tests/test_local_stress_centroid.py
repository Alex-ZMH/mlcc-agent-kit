from __future__ import annotations

import copy

import numpy as np
import pytest

from mlcc.local_stress import local_stress_from_frames


COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz", "yx", "zx", "zy"]
SOURCE_CELL = [
    [0.0, 3.0, 0.0],
    [-4.0, 0.0, 0.0],
    [0.0, 0.0, 5.0],
]


def _request(*, volume: float | None = 5.0) -> dict[str, object]:
    return {
        "schema": "mlcc.local-stress-analysis.v1",
        "source_kind": "mathematical_fixture",
        "fixture": True,
        "fixture_purpose": "mathematical_fixture",
        "observation_window": {"kind": "whole_record"},
        "regions": [
            {
                "region_id": "centroid",
                "atom_ids": [10, 20],
                "volume_angstrom3": volume,
                "volume_definition": (
                    "explicit_centroid_volume" if volume is not None else "volume_pending"
                ),
            }
        ],
    }


def _frames() -> list[dict[str, object]]:
    return [
        {
            "step": 0,
            "physical_time_ps": 0.0,
            "atom_ids": [10, 20, 30],
            "stress_volume_components_bar_A3": [
                [100.0, 200.0, 300.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
                [10.0, 20.0, 30.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
                [0.0] * 9,
            ],
        },
        {
            "step": 10,
            "physical_time_ps": 1.0,
            "atom_ids": [20, 30, 10],
            "stress_volume_components_bar_A3": [
                [20.0, 30.0, 40.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
                [0.0] * 9,
                [80.0, 160.0, 240.0, 35.0, 45.0, 55.0, 65.0, 75.0, 85.0],
            ],
        },
    ]


def _region(result: dict[str, object]) -> dict[str, object]:
    return result["regions"][0]  # type: ignore[index]


def test_centroid_keeps_asymmetric_native_tensor_with_analytic_prism_orientation() -> None:
    result = local_stress_from_frames(
        _request(), _frames(), SOURCE_CELL, component_order=COMPONENT_ORDER
    )

    assert result["status"] == "mathematical_fixture"
    assert result["production_qualified"] is False
    assert result["stress_volume_component_order"] == COMPONENT_ORDER
    region = _region(result)
    assert region["stress_volume_component_order"] == COMPONENT_ORDER
    assert region["stress_volume_sum_bar_A3_mean"] == pytest.approx(
        [105.0, 205.0, 305.0, 42.0, 53.0, 64.0, 75.0, 86.0, 97.0]
    )
    assert region["stress_volume_sum_bar_A3_by_frame"][0]["components"] == pytest.approx(  # type: ignore[index]
        [110.0, 220.0, 330.0, 44.0, 55.0, 66.0, 77.0, 88.0, 99.0]
    )

    mean_sum = np.asarray(region["stress_volume_sum_bar_A3_mean"], dtype=float)
    pressure_components = -mean_sum / 5.0
    expected_stress = np.asarray(
        [
            [0.0041, -0.0015, -0.00128],
            [-0.00084, 0.0021, 0.00106],
            [-0.00194, 0.00172, 0.0061],
        ]
    )
    expected_pressure = -expected_stress

    np.testing.assert_allclose(region["pressure_components_bar"], pressure_components)
    np.testing.assert_allclose(region["pressure_tensor_GPa"], expected_pressure)
    np.testing.assert_allclose(region["stress_GPa"], expected_stress)
    assert not np.allclose(expected_stress, expected_stress.T)
    assert region["conversion"]["pressure_component_order"] == COMPONENT_ORDER  # type: ignore[index]


def test_centroid_missing_volume_preserves_full_nine_component_sum() -> None:
    request = _request(volume=None)
    result = local_stress_from_frames(
        request, _frames(), SOURCE_CELL, component_order=COMPONENT_ORDER
    )

    region = _region(result)
    assert result["status"] == "partial"
    assert region["status"] == "partial"
    assert region["stress_volume_sum_bar_A3_mean"] == pytest.approx(
        [105.0, 205.0, 305.0, 42.0, 53.0, 64.0, 75.0, 86.0, 97.0]
    )
    assert region["stress_GPa"] is None
    assert region["pressure_tensor_GPa"] is None
    assert "region:centroid:volume_angstrom3" in result["missing_evidence"]  # type: ignore[operator]


def test_centroid_requires_exact_order_and_matching_width() -> None:
    with pytest.raises(ValueError, match="component_order must be exactly"):
        local_stress_from_frames(
            _request(), _frames(), SOURCE_CELL, component_order=COMPONENT_ORDER[:-1]
        )

    six_component_frames = copy.deepcopy(_frames())
    for frame in six_component_frames:
        frame["stress_volume_components_bar_A3"] = [
            values[:6] for values in frame["stress_volume_components_bar_A3"]  # type: ignore[index]
        ]
    with pytest.raises(ValueError, match="9-component row"):
        local_stress_from_frames(
            _request(), six_component_frames, SOURCE_CELL, component_order=COMPONENT_ORDER
        )

    with pytest.raises(ValueError, match="6-component row"):
        local_stress_from_frames(_request(), _frames(), SOURCE_CELL)


def test_explicit_six_component_order_matches_legacy_default() -> None:
    six_component_frames = copy.deepcopy(_frames())
    for frame in six_component_frames:
        frame["stress_volume_components_bar_A3"] = [
            values[:6] for values in frame["stress_volume_components_bar_A3"]  # type: ignore[index]
        ]

    legacy = local_stress_from_frames(_request(), six_component_frames, SOURCE_CELL)
    explicit = local_stress_from_frames(
        _request(),
        six_component_frames,
        SOURCE_CELL,
        component_order=["xx", "yy", "zz", "xy", "xz", "yz"],
    )

    assert explicit == legacy


def test_centroid_rejects_contradictory_frame_component_order() -> None:
    frames = _frames()
    frames[0]["component_order"] = list(reversed(COMPONENT_ORDER))
    with pytest.raises(ValueError, match="frame component_order differs"):
        local_stress_from_frames(
            _request(), frames, SOURCE_CELL, component_order=COMPONENT_ORDER
        )
