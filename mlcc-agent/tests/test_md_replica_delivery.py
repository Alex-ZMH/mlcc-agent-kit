"""MD-05 saved-summary Study delivery checks.

The product and Study are supplied by the v100 acceptance environment.  These
tests consume the saved summary and deliberately forbid the replica kernel,
thermo analysis, and native collection reader from running again.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import mlcc.md_replica as md_replica
import mlcc.md_thermo as md_thermo
import mlcc.md_trajectory as md_trajectory
import mlcc.property_delivery as property_delivery
from mlcc.property_delivery import deliver_md_replica_properties


def _real_paths() -> tuple[Path, Path]:
    product_path = Path(os.environ["MLCC_REPLICA_PRODUCT"]).expanduser()
    study_path = Path(os.environ["MLCC_MD_STUDY"]).expanduser()
    return study_path, product_path


def _forbid_recomputation(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("saved MD-05 delivery must not rerun a summary, thermo, or native parser")

    monkeypatch.setattr(md_replica, "summarize_md_replicas", forbidden)
    monkeypatch.setattr(md_thermo, "analyze_md_thermo", forbidden)
    monkeypatch.setattr(md_trajectory, "read_md_collection", forbidden)
    # Also catch a direct alias if the public delivery module imported one at
    # module load time rather than resolving it from the domain module.
    for name in ("summarize_md_replicas", "analyze_md_thermo", "read_md_collection"):
        monkeypatch.setattr(property_delivery, name, forbidden, raising=False)


def test_saved_replica_summary_is_delivered_in_the_same_ni_study(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_path, product_path = _real_paths()
    product = json.loads(product_path.read_text(encoding="utf-8"))
    study = json.loads(study_path.read_text(encoding="utf-8"))
    assert product["schema"] == "mlcc.md-replica-summary.v1"
    _forbid_recomputation(monkeypatch)

    result = deliver_md_replica_properties(study_path, product_path)

    assert result["schema"] == "mlcc.md-replica-property-delivery.v1"
    assert result["study_id"] == study["study_id"]
    assert result["product"] == product
    assert result["statistics"] == product["statistics"]
    assert result["statistics_status"] == product["statistics_status"]
    assert result["sources"] == product["sources"]
    assert result["task_refs"]
    assert result["artifacts"]


def test_saved_replica_summary_rejects_a_different_study(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_path, product_path = _real_paths()
    study = json.loads(study_path.read_text(encoding="utf-8"))
    study["study_id"] = "different-study"
    wrong_study_path = tmp_path / "wrong-study.json"
    wrong_study_path.write_text(json.dumps(study, indent=2) + "\n", encoding="utf-8")
    _forbid_recomputation(monkeypatch)

    with pytest.raises(ValueError, match="study_id|Study"):
        deliver_md_replica_properties(wrong_study_path, product_path)


@pytest.mark.parametrize("mismatch", ["observable", "native_job"])
def test_saved_source_identity_mismatch_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str,
) -> None:
    study_path, product_path = _real_paths()
    product = json.loads(product_path.read_text(encoding="utf-8"))
    assert product["sources"]
    if mismatch == "observable":
        product["sources"][0]["observable"]["observable_id"] = "MD_total_energy_final_minus_initial"
        expected = "observable"
    else:
        product["sources"][0]["native_job"]["scheduler_job_id"] = "different-native-job"
        expected = "job|scheduler"
    wrong_product_path = tmp_path / f"wrong-{mismatch}.json"
    wrong_product_path.write_text(json.dumps(product, indent=2) + "\n", encoding="utf-8")
    _forbid_recomputation(monkeypatch)

    with pytest.raises(ValueError, match=expected):
        deliver_md_replica_properties(study_path, wrong_product_path)
