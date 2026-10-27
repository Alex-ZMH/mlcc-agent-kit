from __future__ import annotations

import itertools
import json

import pytest

from mlcc.md_msd import compute_tracer_msd


def _request(
    atom_ids: list[int],
    *,
    start_ps: float = 1.0,
    end_ps: float = 4.0,
    thresholds: dict[str, object] | None = None,
) -> dict[str, object]:
    request: dict[str, object] = {
        "source_atom_ids": atom_ids,
        "dimensions": 3,
        "com_policy": "none",
        "fick_window": {"start_ps": start_ps, "end_ps": end_ps},
    }
    if thresholds is not None:
        request["thresholds"] = thresholds
    return request


def _two_atom_linear_frames() -> list[dict[str, object]]:
    return [
        {
            "step": index,
            "physical_time_ps": float(index),
            "source_atom_ids": [10, 20],
            "positions_angstrom": [[float(index), 0.0, 0.0], [0.0, 2.0 * index, 0.0]],
        }
        for index in range(4)
    ]


def _random_walk_fixture() -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    signs = list(itertools.product((-1.0, 1.0), repeat=5))
    atom_ids = list(range(100, 100 + len(signs)))
    for frame_index in range(6):
        positions = []
        for sign_sequence in signs:
            x = sum(sign_sequence[:frame_index])
            positions.append([x, 0.0, 0.0])
        frames.append(
            {
                "step": frame_index,
                "physical_time_ps": float(frame_index),
                "source_atom_ids": atom_ids,
                "positions_angstrom": positions,
            }
        )
    return frames


def test_all_positive_lags_average_all_origins_and_selected_atoms() -> None:
    frames = _two_atom_linear_frames()
    result = compute_tracer_msd(frames, request=_request([10, 20], end_ps=3.0))

    assert result["schema"] == "mlcc.md-msd.v1"
    assert result["status"] == "partial"
    assert result["source_atom_ids"] == [10, 20]
    assert result["lag_ps"] == pytest.approx([1.0, 2.0, 3.0])
    assert result["MSD_A2"] == pytest.approx([2.5, 10.0, 22.5])
    assert result["origin_count"] == [3, 2, 1]
    assert result["atom_origin_pair_count"] == [6, 4, 2]
    assert result["frames"] == frames
    assert result["D_A2_per_ps"] is None
    assert result["D_m2_per_s"] is None


def test_analytic_random_walk_passes_explicit_fick_window(tmp_path) -> None:
    frames = _random_walk_fixture()
    atom_ids = list(range(100, 132))
    result = compute_tracer_msd(
        frames,
        request=_request(
            atom_ids,
            thresholds={
                "minimum_r_squared": 0.99,
                "maximum_relative_slope_spread": 0.05,
                "log_msd_exponent_range": [0.95, 1.05],
                "minimum_msd_change_A2": 2.0,
            },
        ),
    )

    assert result["status"] == "available"
    assert result["MSD_A2"] == pytest.approx([1.0, 2.0, 3.0, 4.0, 5.0])
    assert result["fick"]["selected_lag_ps"] == pytest.approx([1.0, 2.0, 3.0, 4.0])  # type: ignore[index]
    assert result["fick"]["fit"]["slope_A2_per_ps"] == pytest.approx(1.0)  # type: ignore[index]
    assert result["fick"]["relative_slope_spread"] == pytest.approx(0.0)  # type: ignore[index]
    assert result["fick"]["log_msd_exponent"] == pytest.approx(1.0)  # type: ignore[index]
    assert result["D_A2_per_ps"] == pytest.approx(1.0 / 6.0)
    assert result["D_m2_per_s"] == pytest.approx(1.0e-8 / 6.0)
    assert result["fick"]["diagnostics"]["status"] == "pass"  # type: ignore[index]
    (tmp_path / "math-msd-result.json").write_text(
        json.dumps(
            {
                "fixture_kind": "mathematical",
                "fixture": "all_32_sign_sequences_5_steps",
                "result": result,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_ballistic_trajectory_fails_explicit_fick_diagnostics() -> None:
    frames = [
        {
            "step": index,
            "physical_time_ps": float(index),
            "source_atom_ids": [5],
            "positions_angstrom": [[float(index * index), 0.0, 0.0]],
        }
        for index in range(6)
    ]
    result = compute_tracer_msd(
        frames,
        request=_request(
            [5],
            thresholds={
                "minimum_r_squared": 0.99,
                "maximum_relative_slope_spread": 0.1,
                "log_msd_exponent_range": [0.8, 1.2],
            },
        ),
    )

    assert result["status"] == "partial"
    assert result["MSD_A2"] is not None
    assert result["D_A2_per_ps"] is None
    assert result["fick"]["diagnostics"]["status"] == "fail"  # type: ignore[index]


def test_zero_constant_tracer_keeps_nonpositive_log_msd_unresolved() -> None:
    frames = [
        {
            "step": index,
            "physical_time_ps": float(index),
            "source_atom_ids": [9],
            "positions_angstrom": [[0.0, 0.0, 0.0]],
        }
        for index in range(6)
    ]
    result = compute_tracer_msd(
        frames,
        request=_request(
            [9],
            thresholds={
                "minimum_r_squared": 0.0,
                "maximum_relative_slope_spread": 0.0,
                "log_msd_exponent_range": [0.0, 2.0],
            },
        ),
    )

    assert result["MSD_A2"] == pytest.approx([0.0] * 5)
    assert result["D_A2_per_ps"] is None
    assert result["fick"]["log_msd_exponent"] is None  # type: ignore[index]
    assert "strictly positive" in result["fick"]["log_msd_exponent_unresolved_reason"]  # type: ignore[index]


def test_nonuniform_physical_time_does_not_use_frame_index_as_time() -> None:
    frames = _two_atom_linear_frames()
    frames[2]["physical_time_ps"] = 2.5
    result = compute_tracer_msd(frames, request=_request([10, 20], end_ps=3.0))

    assert result["status"] == "unresolved"
    assert result["MSD_A2"] is None
    assert result["lag_ps"] is None
    assert result["time"]["reason"] == "physical_time_ps sampling is nonuniform"  # type: ignore[index]
    assert result["MSD_A2_unresolved_reason"] == "physical_time_ps sampling is nonuniform"
    assert result["D_A2_per_ps_unresolved_reason"] == "physical_time_ps sampling is nonuniform"
    assert result["unresolved_reasons"] == ["physical_time_ps sampling is nonuniform"]


def test_missing_thresholds_keep_msd_and_fit_but_leave_diffusion_unresolved() -> None:
    result = compute_tracer_msd(_random_walk_fixture(), request=_request(list(range(100, 132))))

    assert result["status"] == "partial"
    assert result["MSD_A2"] is not None
    assert result["fick"]["fit"] is not None  # type: ignore[index]
    assert result["fick"]["diagnostics"]["status"] == "unresolved"  # type: ignore[index]
    assert result["D_A2_per_ps"] is None
    assert result["D_m2_per_s"] is None


def test_missing_requested_atom_id_is_an_original_value_error() -> None:
    with pytest.raises(ValueError, match="absent from frame"):
        compute_tracer_msd(_two_atom_linear_frames(), request=_request([10, 99], end_ps=3.0))
