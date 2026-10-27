"""MD-02 source and native element selection tests.

Tests consume the accepted job45 collection and mutate temporary JSON copies
only.  No native task, parser or simulation is started here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from mlcc.md_sources import select_md_sources


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COLLECTION = ROOT / "workspace" / "reports" / "md-series-v011-v001" / "collection.json"


def _source() -> Path:
    return Path(os.environ.get("MLCC_MD_COLLECTION", str(DEFAULT_COLLECTION)))


def _load_copy(tmp_path: Path, name: str) -> tuple[Path, dict[str, object]]:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    target = tmp_path / f"{name}.json"
    shutil.copy2(source, target)
    return target, json.loads(target.read_text(encoding="utf-8"))


def _write(path: Path, record: dict[str, object]) -> None:
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _unique_source_files(record: dict[str, object], tmp_path: Path, name: str) -> None:
    for source_name in record["source_files"]:
        record["source_files"][source_name] = str(tmp_path / name / source_name)
    for source_name in record["legacy_final_result"]["source_files"]:
        record["legacy_final_result"]["source_files"][source_name] = record["source_files"][source_name]


def _request(record: dict[str, object]) -> dict[str, str]:
    return {
        "model_id": record["model"]["model_id"],
        "model_version": record["model"]["version"],
        "potential_id": record["potential"]["potential_id"],
        "potential_version": record["potential"]["version"],
    }


def test_select_md_sources_real_job45_nickel(tmp_path: Path) -> None:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    before = source.read_text(encoding="utf-8")
    record = json.loads(before)

    result = select_md_sources([source], **_request(record), elements=["Ni"])

    assert source.read_text(encoding="utf-8") == before
    assert result["schema"] == "mlcc.md-source-selection.v1"
    assert result["source_selection"] == {
        "status": "selected_for_engineering_source_binding",
        "source_count": 1,
        "scientific_qualification": False,
    }
    selected = result["sources"][0]
    assert selected["collection_path"] == str(source)
    assert selected["task_id"] == "p10-ni-lammps-nve100-v001"
    assert selected["native_job"]["scheduler_job_id"] == "45"
    assert selected["native_job"]["scheduler_state"] == "COMPLETED"
    assert selected["model"]["model_id"] == "ni-abacus-engineering-relaxed"
    assert selected["potential"]["potential_id"] == "Ni-u3-Foiles1986"
    assert selected["replica"] == {
        "replica_id": None,
        "packing_seed": None,
        "velocity_seed": 20261022,
        "status": "unresolved_missing_replica_id",
    }
    nickel = selected["mapping"]["elements"]["Ni"]
    assert nickel["source_atom_ids"] == [0, 1, 2, 3]
    assert nickel["lammps_atom_ids"] == [1, 2, 3, 4]
    assert nickel["source_indices"] == [0, 1, 2, 3]
    assert nickel["frame_position_indices"] == [0, 1, 2, 3]
    assert nickel["type_ids"] == [1, 1, 1, 1]
    assert nickel["first_frame"]["coordinate_basis"] == "lammps_prism_cartesian"
    assert selected["mapping"]["atom_mapping"]["frame_count"] == 11
    assert selected["mapping"]["atom_mapping"]["legacy_coordinate_basis"] == "source_cartesian"
    assert result["replica_aggregation"]["status"] == "unresolved"
    assert result["replica_aggregation"]["qualified"] is False
    assert "mean" not in result["replica_aggregation"]


def test_rejects_repeated_collection_and_source_paths(tmp_path: Path) -> None:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    record = json.loads(source.read_text(encoding="utf-8"))
    copied_path, _ = _load_copy(tmp_path, "copy")

    with pytest.raises(ValueError, match="is repeated"):
        select_md_sources([source, copied_path], **_request(record), elements=["Ni"])

    with pytest.raises(ValueError, match="collection path is repeated"):
        select_md_sources([source, source], **_request(record), elements=["Ni"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model", {"model_id": "other-model"}, "model identity"),
        ("potential", {"potential_id": "other-potential"}, "potential identity"),
    ],
)
def test_rejects_requested_identity_mismatch(
    tmp_path: Path,
    field: str,
    value: dict[str, str],
    message: str,
) -> None:
    source_path, record = _load_copy(tmp_path, "identity")
    request = _request(record)
    request[f"{field}_id"] = value[f"{field}_id"]

    with pytest.raises(ValueError, match=message):
        select_md_sources([source_path], **request, elements=["Ni"])


def test_rejects_missing_native_element(tmp_path: Path) -> None:
    source_path, record = _load_copy(tmp_path, "element")

    with pytest.raises(ValueError, match="element O is absent"):
        select_md_sources([source_path], **_request(record), elements=["O"])


def test_rejects_failed_native_job(tmp_path: Path) -> None:
    source_path, record = _load_copy(tmp_path, "job")
    record["native_job"]["scheduler_state"] = "FAILED"
    _write(source_path, record)

    with pytest.raises(ValueError, match="COMPLETED"):
        select_md_sources([source_path], **_request(record), elements=["Ni"])


def test_rejects_first_frame_legacy_mapping_mismatch(tmp_path: Path) -> None:
    source_path, record = _load_copy(tmp_path, "mapping")
    record["legacy_final_result"]["types"][0] = 2
    _write(source_path, record)

    with pytest.raises(ValueError, match="atom types differ"):
        select_md_sources([source_path], **_request(record), elements=["Ni"])


def test_duplicate_velocity_seed_blocks_replica_aggregation(tmp_path: Path) -> None:
    first_path, first = _load_copy(tmp_path, "first")
    second_path, second = _load_copy(tmp_path, "second")
    # Temporary metadata fixture only, never evidence for another native job.
    second["task_id"] = "unit-test-only-second"
    second["native_job"]["scheduler_job_id"] = "unit-test-only-second"
    second["legacy_final_result"]["task_id"] = second["task_id"]
    second["legacy_final_result"]["scheduler_job_id"] = second["native_job"]["scheduler_job_id"]
    second["sampling_metadata"]["replica_id"] = "replica-2"
    _unique_source_files(second, tmp_path, "second-source")
    # Shared potential data is allowed; only trajectory/task evidence is unique.
    second["source_files"]["Ni_u3.eam"] = first["source_files"]["Ni_u3.eam"]
    second["legacy_final_result"]["source_files"]["Ni_u3.eam"] = first["source_files"]["Ni_u3.eam"]
    _write(second_path, second)

    result = select_md_sources(
        [first_path, second_path],
        **_request(first),
        elements=["Ni"],
    )

    assert result["source_selection"]["source_count"] == 2
    assert result["replica_aggregation"]["status"] == "rejected_replica_aggregation"
    assert result["replica_aggregation"]["qualified"] is False
    assert result["replica_aggregation"]["velocity_seeds_unique"] is False
    assert "mean" not in result["replica_aggregation"]


def test_rejects_collection_job_relabeling(tmp_path: Path) -> None:
    path, record = _load_copy(tmp_path, "relabeled-job")
    record["native_job"]["scheduler_job_id"] = "unit-test-only-wrong-job"
    _write(path, record)
    with pytest.raises(ValueError, match="native job identity"):
        select_md_sources([path], **_request(record), elements=["Ni"])


def test_rejects_source_index_mismatch(tmp_path: Path) -> None:
    path, record = _load_copy(tmp_path, "wrong-source-index")
    record["trajectory"]["frames"][0]["source_indices"] = [1, 0, 2, 3]
    _write(path, record)
    with pytest.raises(ValueError, match="source index"):
        select_md_sources([path], **_request(record), elements=["Ni"])
