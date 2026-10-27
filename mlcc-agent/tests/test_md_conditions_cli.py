"""Focused public CLI checks for the MD-01 conditions entry.

The real collection is supplied by the completed MD engineering task.  The
test intentionally keeps the missing-window result unresolved and creates an
explicit engineering request from that collection's own identifiers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mlcc.cli import main


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_COLLECTION = _ROOT / "workspace" / "reports" / "md-series-v011-v001" / "collection.json"


def _collection_path() -> Path:
    return Path(os.environ.get("MLCC_MD_COLLECTION", str(_DEFAULT_COLLECTION)))


def test_md_conditions_cli_preserves_missing_windows(tmp_path: Path) -> None:
    collection = _collection_path()
    assert collection.is_file()
    output = tmp_path / "conditions-missing.json"

    assert main([
        "md-conditions",
        "--collection",
        str(collection),
        "--output",
        str(output),
    ]) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == "mlcc.md-conditions.v1"
    assert result["windows"]["equilibration_window"]["status"] == "unresolved_missing"
    assert result["windows"]["production_window"]["status"] == "unresolved_missing"
    assert result["windows"]["equilibration_window"]["count"] is None
    assert result["windows"]["production_window"]["count"] is None
    assert result["production_qualification"] is False
    assert result["sampling_equilibrium_qualified"] is False


def test_md_conditions_cli_accepts_optional_engineering_window_request(tmp_path: Path) -> None:
    collection = _collection_path()
    assert collection.is_file()
    collection_data = json.loads(collection.read_text(encoding="utf-8"))
    request = {
        "schema": "mlcc.md-window-request.v1",
        "task_id": collection_data["task_id"],
        "scheduler_job_id": collection_data["native_job"]["scheduler_job_id"],
        "purpose": "engineering_postprocessing_selection",
        "equilibration_window": {"start_step": 0, "end_step": 40},
        "production_window": {"start_step": 50, "end_step": 100},
    }
    request_path = tmp_path / "engineering-windows.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    output = tmp_path / "conditions-selected.json"

    assert main([
        "md-conditions",
        "--collection",
        str(collection),
        "--window-request",
        str(request_path),
        "--output",
        str(output),
    ]) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["windows"]["equilibration_window"]["status"] == "selected_for_engineering_postprocessing"
    assert result["windows"]["production_window"]["status"] == "selected_for_engineering_postprocessing"
    assert result["windows"]["equilibration_window"]["count"] == 5
    assert result["windows"]["production_window"]["count"] == 6
    assert result["production_qualification"] is False
    assert result["sampling_equilibrium_qualified"] is False


def test_md_conditions_cli_does_not_overwrite_existing_output(tmp_path: Path) -> None:
    collection = _collection_path()
    assert collection.is_file()
    output = tmp_path / "conditions.json"
    sentinel = '{"sentinel": true}\n'
    output.write_text(sentinel, encoding="utf-8")

    try:
        main([
            "md-conditions",
            "--collection",
            str(collection),
            "--output",
            str(output),
        ])
    except SystemExit as error:
        assert error.code == 1
    else:
        raise AssertionError("md-conditions unexpectedly overwrote an existing output")
    assert output.read_text(encoding="utf-8") == sentinel
