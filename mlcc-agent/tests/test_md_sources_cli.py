"""Focused public CLI checks for the MD-02 source-selection entry."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mlcc.cli import main


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_COLLECTION = _ROOT / "workspace" / "reports" / "md-series-v011-v001" / "collection.json"


def _collection_path() -> Path:
    return Path(os.environ.get("MLCC_MD_COLLECTION", str(_DEFAULT_COLLECTION)))


def _source_request(collection: Path) -> dict[str, object]:
    record = json.loads(collection.read_text(encoding="utf-8"))
    return {
        "collection_paths": [str(collection)],
        "model_id": record["model"]["model_id"],
        "model_version": record["model"]["version"],
        "potential_id": record["potential"]["potential_id"],
        "potential_version": record["potential"]["version"],
        "elements": sorted(set(record["legacy_final_result"]["elements"])),
    }


def test_md_sources_cli_selects_real_collection_and_preserves_unresolved_replica(
    tmp_path: Path,
) -> None:
    collection = _collection_path()
    assert collection.is_file()
    request_path = tmp_path / "source-request.json"
    request_path.write_text(json.dumps(_source_request(collection)), encoding="utf-8")
    output = tmp_path / "source-selection.json"

    assert main([
        "md-sources",
        "--request",
        str(request_path),
        "--output",
        str(output),
    ]) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == "mlcc.md-source-selection.v1"
    assert result["source_selection"]["source_count"] == 1
    assert result["source_selection"]["scientific_qualification"] is False
    assert result["replica_aggregation"]["status"] == "unresolved"
    assert result["replica_aggregation"]["qualified"] is False
    assert result["replica_aggregation"]["replica_ids_unique"] is None
    assert result["production_qualification"] is False
    assert result["sources"][0]["mapping"]["elements"]


def test_md_sources_cli_rejects_wrong_model_identity(tmp_path: Path) -> None:
    collection = _collection_path()
    assert collection.is_file()
    request = _source_request(collection)
    request["model_id"] = "model-identity-does-not-match"
    request_path = tmp_path / "wrong-source-request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    output = tmp_path / "should-not-be-written.json"

    try:
        main([
            "md-sources",
            "--request",
            str(request_path),
            "--output",
            str(output),
        ])
    except SystemExit as error:
        assert error.code == 1
    else:
        raise AssertionError("md-sources accepted a mismatched model identity")
    assert not output.exists()
