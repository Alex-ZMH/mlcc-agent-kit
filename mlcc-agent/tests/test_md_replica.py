"""MD-05 scalar replica contract tests.

The real-source checks consume the saved job-45/job-450 delivery.  Temporary
JSON copies are used only to exercise metadata rejection paths; no native
trajectory or thermo record is parsed or fabricated.  The two-value math
checks are explicitly algorithm-only.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path

import pytest

from mlcc.md_replica import _gate_reasons, _sample_summary, summarize_md_replicas


def _delivery_source() -> Path:
    value = os.environ.get("MLCC_MD_REPLICA_DELIVERY")
    if not value:
        raise AssertionError("v100 acceptance must set MLCC_MD_REPLICA_DELIVERY")
    return Path(value)


def _stage_delivery(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    source = _delivery_source()
    assert source.is_file(), f"saved MD replica delivery unavailable: {source}"
    delivery = json.loads(source.read_text(encoding="utf-8"))
    source_collection = Path(delivery["artifacts"]["collection"])
    assert source_collection.is_file(), f"saved MD replica collection unavailable: {source_collection}"
    collection = json.loads(source_collection.read_text(encoding="utf-8"))
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    delivery["artifacts"]["collection"] = str(collection_path)
    delivery["source_selection"]["sources"][0]["collection_path"] = str(collection_path)
    source_thermo = Path(delivery["artifacts"]["thermo"])
    assert source_thermo.is_file(), f"saved MD thermo artifact unavailable: {source_thermo}"
    thermo = json.loads(source_thermo.read_text(encoding="utf-8"))
    thermo_path = tmp_path / "thermo.json"
    thermo_path.write_text(json.dumps(thermo, indent=2), encoding="utf-8")
    delivery["artifacts"]["thermo"] = str(thermo_path)
    delivery_path = tmp_path / "delivery.json"
    delivery_path.write_text(json.dumps(delivery, indent=2), encoding="utf-8")
    return delivery_path, delivery, collection


def _request(delivery_path: Path, delivery: dict[str, object], *, observable_id: str = "MD_temperature_sample_mean") -> dict[str, object]:
    model = delivery["model"]
    potential = delivery["potential"]
    return {
        "schema": "mlcc.md-replica-request.v1",
        "source_selection": {
            "model_id": model["model_id"],
            "model_version": model["version"],
            "potential_id": potential["potential_id"],
            "potential_version": potential["version"],
            "elements": list(delivery["source_selection"]["request"]["elements"]),
        },
        "observable_id": observable_id,
        "sources": [{"delivery_path": str(delivery_path), "replica_id": None, "independence": None}],
        "interval": {"mode": "descriptive"},
    }


def test_sample_summary_descriptive_is_equal_weight_and_has_no_ci() -> None:
    # Algorithm-only values; these are not native MD replicas.
    result = _sample_summary([1.0, 3.0], interval={"mode": "descriptive"})

    assert result["mean"] == pytest.approx(2.0)
    assert result["standard_deviation"] == pytest.approx(math.sqrt(2.0))
    assert result["standard_error"] is None
    assert result["confidence_interval"] is None
    assert result["replica_count"] == 2


def test_sample_summary_student_t_uses_df_n_minus_one_not_1_96() -> None:
    # Algorithm-only values; n=2 makes the t critical value visibly distinct.
    result = _sample_summary(
        [1.0, 3.0],
        interval={"mode": "student_t", "confidence": 0.95, "iid_replica_estimates": True},
    )

    assert result["mean"] == pytest.approx(2.0)
    assert result["standard_deviation"] == pytest.approx(math.sqrt(2.0))
    assert result["standard_error"] == pytest.approx(1.0)
    assert result["confidence_interval"][0] == pytest.approx(2.0 - 12.7062047364, rel=1e-8)
    assert result["confidence_interval"][1] == pytest.approx(2.0 + 12.7062047364, rel=1e-8)
    assert result["confidence_interval"][0] < -10.0


@pytest.mark.parametrize(
    ("observable_id", "expected"),
    [
        ("MD_temperature_sample_mean", 164.29835101990727),
        ("MD_total_energy_final_minus_initial", 2.8489724890334855e-05),
    ],
)
def test_real_job45_single_source_preserves_unresolved_replica_status(
    tmp_path: Path, observable_id: str, expected: float,
) -> None:
    delivery_path, delivery, _ = _stage_delivery(tmp_path)
    result = summarize_md_replicas(_request(delivery_path, delivery, observable_id=observable_id))

    assert result["schema"] == "mlcc.md-replica-summary.v1"
    assert result["status"] == "summarized_engineering_observation"
    assert result["observed_source_count"] == 1
    assert result["replica_count"] == 0
    assert result["values"] == [expected]
    assert result["statistics"]["mean"] == pytest.approx(expected)
    assert result["statistics"]["standard_deviation"] is None
    assert result["statistics"]["standard_error"] is None
    assert result["statistics"]["confidence_interval"] is None
    assert result["statistics_status"] == "unresolved"
    assert any("replica_id" in reason for reason in result["statistics_unresolved_reasons"])
    assert result["sources"][0]["native_job"]["scheduler_job_id"] == "45"
    assert result["sources"][0]["analysis_scheduler_job_id"] == "450"
    assert result["sources"][0]["scientific_status"] == "unqualified"
    assert result["sources"][0]["source_files"]["method.json"]


def _algorithm_replica(replica_id: str, velocity_seed: int, independence: dict[str, object] | None) -> dict[str, object]:
    """Algorithm-only gate record; it contains no native task or trajectory."""

    return {
        "replica": {
            "replica_id": replica_id,
            "packing_seed": None,
            "velocity_seed": velocity_seed,
            "independence": independence,
        }
    }


def test_algorithm_only_gate_accepts_distinct_declared_replicas() -> None:
    independence = {"basis": "same_fixed_parent_distinct_velocity_seeds", "independently_executed": True}
    reasons = _gate_reasons(
        [_algorithm_replica("r1", 11, independence), _algorithm_replica("r2", 12, independence)],
        {"mode": "descriptive"},
    )
    assert reasons == []


def test_algorithm_only_gate_withholds_student_t_without_iid_declaration() -> None:
    independence = {"basis": "same_fixed_parent_distinct_velocity_seeds", "independently_executed": True}
    reasons = _gate_reasons(
        [_algorithm_replica("r1", 11, independence), _algorithm_replica("r2", 12, independence)],
        {"mode": "student_t", "confidence": 0.95},
    )
    assert any("iid_replica_estimates" in reason for reason in reasons)


def test_student_t_without_iid_declaration_withholds_single_source_statistics(tmp_path: Path) -> None:
    delivery_path, delivery, _ = _stage_delivery(tmp_path)
    request = _request(delivery_path, delivery)
    request["interval"] = {"mode": "student_t", "confidence": 0.95}

    result = summarize_md_replicas(request)

    assert result["statistics"]["mean"] is not None
    assert result["statistics"]["standard_deviation"] is None
    assert result["statistics"]["standard_error"] is None
    assert result["statistics"]["confidence_interval"] is None
    assert any("iid_replica_estimates" in reason for reason in result["statistics_unresolved_reasons"])


def test_same_native_delivery_cannot_be_counted_twice(tmp_path: Path) -> None:
    delivery_path, delivery, _ = _stage_delivery(tmp_path)
    request = _request(delivery_path, delivery)
    request["sources"] = [copy.deepcopy(request["sources"][0]), copy.deepcopy(request["sources"][0])]

    with pytest.raises(ValueError, match="repeated"):
        summarize_md_replicas(request)


def test_distinct_delivery_copies_with_same_native_job_are_rejected(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_path, first_delivery, _ = _stage_delivery(first_dir)
    second_path, _, _ = _stage_delivery(second_dir)
    request = _request(first_path, first_delivery)
    request["sources"] = [
        request["sources"][0],
        {"delivery_path": str(second_path), "replica_id": None, "independence": None},
    ]

    with pytest.raises(ValueError, match="repeated"):
        summarize_md_replicas(request)


def test_request_cannot_fabricate_missing_replica_id(tmp_path: Path) -> None:
    delivery_path, delivery, _ = _stage_delivery(tmp_path)
    request = _request(delivery_path, delivery)
    request["sources"][0]["replica_id"] = "replica-1"

    with pytest.raises(ValueError, match="cannot replace"):
        summarize_md_replicas(request)


def test_collection_cannot_fabricate_missing_replica_id(tmp_path: Path) -> None:
    delivery_path, delivery, _ = _stage_delivery(tmp_path)
    collection_path = Path(delivery["artifacts"]["collection"])
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    collection["sampling_metadata"]["replica_id"] = "fabricated-replica"
    collection_path.write_text(json.dumps(collection, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="native method replica_id"):
        summarize_md_replicas(_request(delivery_path, delivery))


def test_delivery_condition_mismatch_is_rejected(tmp_path: Path) -> None:
    delivery_path, delivery, _ = _stage_delivery(tmp_path)
    delivery["conditions"]["conditions"]["engine"] = "other-engine"
    delivery_path.write_text(json.dumps(delivery, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="engine|conditions"):
        summarize_md_replicas(_request(delivery_path, delivery))


def test_saved_observation_window_mismatch_is_rejected(tmp_path: Path) -> None:
    delivery_path, delivery, _ = _stage_delivery(tmp_path)
    window = delivery["observables"][0]["conditions"]["observation_window"]
    window["step_range"] = [10, 100]
    delivery_path.write_text(json.dumps(delivery, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="observation window"):
        summarize_md_replicas(_request(delivery_path, delivery))


def test_invalid_student_t_confidence_is_rejected_before_source_read(tmp_path: Path) -> None:
    delivery_path, delivery, _ = _stage_delivery(tmp_path)
    request = _request(delivery_path, delivery)
    request["interval"] = {"mode": "student_t", "confidence": 1.0, "iid_replica_estimates": True}

    with pytest.raises(ValueError, match="confidence"):
        summarize_md_replicas(request)
