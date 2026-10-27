from __future__ import annotations

import pytest

from mlcc.md_thermo_diagnostics import analyze_thermo_diagnostics


UNITS = {"temp": "K", "etotal": "eV", "press": "bar"}


def _request(
    fields: dict[str, object],
    *,
    blocks: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    request: dict[str, object] = {"fields": fields}
    if blocks is not None:
        request["blocks"] = blocks
    return request


def test_nonuniform_time_ols_and_native_indices_are_preserved() -> None:
    rows = [
        {"step": 0, "physical_time_ps": 0.0, "temp": 1.0},
        {"step": 2, "physical_time_ps": 1.0, "temp": 3.0},
        {"step": 5, "physical_time_ps": 3.0, "temp": 7.0},
    ]
    result = analyze_thermo_diagnostics(
        rows,
        row_indices=[100, 105, 120],
        units=UNITS,
        request=_request(
            {"temp": {"max_abs_slope_per_ps": 2.0, "anomaly_z_threshold": 1.0}}
        ),
    )

    field = result["fields"]["temp"]  # type: ignore[index]
    assert result["status"] == "available"
    assert result["row_indices"] == [100, 105, 120]
    assert field["unit"] == "K"
    assert field["values"] == [1.0, 3.0, 7.0]
    assert field["sample_variance"] == pytest.approx(28.0 / 3.0)
    assert field["sample_variance_unit"] == "K^2"
    assert field["ols"]["slope_per_ps"] == pytest.approx(2.0)
    assert field["ols"]["slope_unit"] == "K/ps"
    assert field["ols"]["intercept_unit"] == "K"
    assert field["ols"]["residuals_unit"] == "K"
    assert field["ols"]["intercept"] == pytest.approx(1.0)
    assert field["ols"]["duration_ps"] == pytest.approx(3.0)
    assert field["ols"]["residuals"] == pytest.approx([0.0, 0.0, 0.0])
    assert field["ols"]["r_squared"] == pytest.approx(1.0)
    assert field["drift"]["status"] == "pass"
    assert field["anomaly"]["anomalies"][0] == {
        "row_index": 100,
        "step": 0,
        "physical_time_ps": 0.0,
        "value": 1.0,
        "absolute_z_score": pytest.approx(1.0690449676),
    }
    assert field["anomaly"]["anomalies"][1]["row_index"] == 120


def test_constant_series_has_zero_z_scores_and_undefined_r_squared() -> None:
    rows = [
        {"step": 10, "physical_time_ps": 0.0, "temp": 0.1},
        {"step": 20, "physical_time_ps": 0.5, "temp": 0.1},
        {"step": 30, "physical_time_ps": 2.0, "temp": 0.1},
    ]
    result = analyze_thermo_diagnostics(
        rows,
        row_indices=[7, 8, 9],
        units=UNITS,
        request=_request(
            {"temp": {"max_abs_slope_per_ps": 0.0, "anomaly_z_threshold": 0.0}}
        ),
    )

    field = result["fields"]["temp"]  # type: ignore[index]
    assert field["sample_variance"] == 0.0
    assert field["ols"]["slope_per_ps"] == pytest.approx(0.0)
    assert field["ols"]["r_squared"] is None
    assert field["ols"]["r_squared_unresolved_reason"] == "constant_values_r_squared_undefined"
    assert field["anomaly"]["population_std"] == pytest.approx(0.0)
    assert field["anomaly"]["z_scores"] == [0.0, 0.0, 0.0]
    assert field["anomaly"]["population_std_zero_reason"]
    assert field["anomaly"]["status"] == "pass"


def test_explicit_inclusive_blocks_keep_native_indices_and_descriptive_dispersion() -> None:
    rows = [
        {"step": 0, "physical_time_ps": 0.0, "temp": 1.0},
        {"step": 1, "physical_time_ps": 1.0, "temp": 3.0},
        {"step": 3, "physical_time_ps": 3.0, "temp": 7.0},
        {"step": 4, "physical_time_ps": 6.0, "temp": 13.0},
    ]
    result = analyze_thermo_diagnostics(
        rows,
        row_indices=[40, 41, 43, 44],
        units=UNITS,
        request=_request(
            {"temp": {"max_abs_slope_per_ps": 100.0, "anomaly_z_threshold": 100.0}},
            blocks=[
                {"block_id": "early", "start_step": 0, "end_step": 1},
                {"block_id": "late", "start_step": 3, "end_step": 4},
            ],
        ),
    )

    blocks = result["blocks"]  # type: ignore[assignment]
    assert blocks[0]["row_indices"] == [40, 41]
    assert blocks[0]["steps"] == [0, 1]
    assert blocks[0]["physical_time_ps_range"] == [0.0, 1.0]
    assert blocks[0]["mean"]["temp"] == pytest.approx(2.0)
    assert blocks[1]["row_indices"] == [43, 44]
    assert blocks[1]["mean"]["temp"] == pytest.approx(10.0)
    assert result["block_mean_dispersion"]["temp"]["count"] == 2  # type: ignore[index]
    assert result["block_mean_dispersion"]["temp"]["sample_variance"] == pytest.approx(32.0)  # type: ignore[index]
    assert result["block_mean_scope"] == "descriptive_block_mean_dispersion_not_replica_or_CI_SE"


def test_missing_thresholds_keep_quantities_but_leave_judgments_unresolved() -> None:
    rows = [
        {"step": 0, "physical_time_ps": 0.0, "temp": 2.0},
        {"step": 1, "physical_time_ps": 1.0, "temp": 4.0},
        {"step": 2, "physical_time_ps": 2.0, "temp": 6.0},
    ]
    result = analyze_thermo_diagnostics(
        rows,
        row_indices=[1, 2, 3],
        units=UNITS,
        request=_request({"temp": {}}),
    )

    field = result["fields"]["temp"]  # type: ignore[index]
    assert result["status"] == "partial"
    assert field["mean"] == pytest.approx(4.0)
    assert field["sample_variance"] == pytest.approx(4.0)
    assert field["ols"]["slope_per_ps"] == pytest.approx(2.0)
    assert field["drift"]["status"] == "unresolved"
    assert field["anomaly"]["status"] == "unresolved"
    assert field["anomaly"]["anomalies"] is None


def test_single_sample_keeps_unresolved_variance_and_fit() -> None:
    result = analyze_thermo_diagnostics(
        [{"step": 8, "physical_time_ps": 4.0, "temp": 9.0}],
        row_indices=[88],
        units=UNITS,
        request=_request({"temp": {"anomaly_z_threshold": 3.0}}),
    )

    field = result["fields"]["temp"]  # type: ignore[index]
    assert result["status"] == "partial"
    assert field["sample_variance"] is None
    assert field["sample_variance_unresolved_reason"] == "temp: fewer_than_two_samples"
    assert field["ols"]["reason"] == "fewer_than_two_samples"
    assert field["anomaly"]["population_std"] == pytest.approx(0.0)
    assert field["anomaly"]["anomalies"] == []
    assert result["block_mean_dispersion"]["temp"]["sample_variance"] is None  # type: ignore[index]
    assert result["block_mean_dispersion"]["temp"]["sample_variance_unresolved_reason"] == "blocks_not_requested"  # type: ignore[index]

    block_result = analyze_thermo_diagnostics(
        [{"step": 8, "physical_time_ps": 4.0, "temp": 9.0}],
        row_indices=[88],
        units=UNITS,
        request=_request(
            {"temp": {"anomaly_z_threshold": 3.0}},
            blocks=[{"block_id": "single", "start_step": 8, "end_step": 8}],
        ),
    )
    assert block_result["blocks"][0]["sample_variance"]["temp"] is None  # type: ignore[index]
    assert block_result["blocks"][0]["sample_variance_unresolved_reason"]["temp"] == "temp block single: fewer_than_two_samples"  # type: ignore[index]


def test_nonpositive_time_span_keeps_ols_unresolved() -> None:
    result = analyze_thermo_diagnostics(
        [
            {"step": 0, "physical_time_ps": 2.0, "temp": 1.0},
            {"step": 1, "physical_time_ps": 2.0, "temp": 2.0},
        ],
        row_indices=[20, 21],
        units=UNITS,
        request=_request({"temp": {"max_abs_slope_per_ps": 1.0, "anomaly_z_threshold": 3.0}}),
    )

    field = result["fields"]["temp"]  # type: ignore[index]
    assert result["status"] == "partial"
    assert field["ols"]["duration_ps"] == pytest.approx(0.0)
    assert field["ols"]["reason"] == "physical_time_ps has no positive span"
    assert field["drift"]["status"] == "unresolved"


def test_block_overlap_and_unselected_endpoint_are_original_errors() -> None:
    rows = [
        {"step": 0, "physical_time_ps": 0.0, "temp": 1.0},
        {"step": 2, "physical_time_ps": 1.0, "temp": 2.0},
        {"step": 4, "physical_time_ps": 2.0, "temp": 3.0},
    ]
    with pytest.raises(ValueError, match="overlap"):
        analyze_thermo_diagnostics(
            rows,
            row_indices=[0, 1, 2],
            units=UNITS,
            request=_request(
                {"temp": {}},
                blocks=[
                    {"block_id": "a", "start_step": 0, "end_step": 2},
                    {"block_id": "b", "start_step": 2, "end_step": 4},
                ],
            ),
        )

    with pytest.raises(ValueError, match="endpoints"):
        analyze_thermo_diagnostics(
            rows,
            row_indices=[0, 1, 2],
            units=UNITS,
            request=_request(
                {"temp": {}},
                blocks=[{"block_id": "gap", "start_step": 1, "end_step": 4}],
            ),
        )

    with pytest.raises(ValueError, match="endpoints"):
        analyze_thermo_diagnostics(
            [],
            row_indices=[],
            units=UNITS,
            request=_request(
                {"temp": {}},
                blocks=[{"block_id": "empty", "start_step": 0, "end_step": 0}],
            ),
        )
