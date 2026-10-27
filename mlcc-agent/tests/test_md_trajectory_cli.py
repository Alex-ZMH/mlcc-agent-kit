"""Focused public CLI checks for the MD-00 collection entry point."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from mlcc.cli import main


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "workspace" / "tasks" / "p10-ni-lammps-nve100-v001"


def _copy_job45(tmp_path: Path) -> Path:
    source = Path(os.environ.get("MLCC_MD_SOURCE_TASK", str(DEFAULT_SOURCE)))
    assert source.is_dir(), f"real Slurm job45 artifact unavailable: {source}"
    target = tmp_path / "job45"
    shutil.copytree(source, target)
    return target


def test_md_collection_cli_writes_complete_native_collection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    task = _copy_job45(tmp_path)
    output = tmp_path / "collection.json"

    assert main(["md-collection", "--task", str(task), "--output", str(output)]) == 0

    collection = json.loads(output.read_text(encoding="utf-8"))
    assert collection["schema"] == "mlcc.md-collection.v1"
    assert collection["native_job"]["scheduler_job_id"] == "45"
    assert [row["step"] for row in collection["thermo"]["rows"]] == list(range(0, 101, 10))
    assert [frame["step"] for frame in collection["trajectory"]["frames"]] == list(range(0, 101, 10))
    assert collection["production_qualification"] is False
    assert collection["sampling_equilibrium_qualified"] is False

    printed = json.loads(capsys.readouterr().out)
    assert Path(printed["output"]) == output.resolve()
    assert printed["status"] == "written"


def test_md_collection_cli_does_not_overwrite_existing_output(tmp_path: Path) -> None:
    task = _copy_job45(tmp_path)
    output = tmp_path / "collection.json"
    output.write_text('{"sentinel": true}\n', encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        main(["md-collection", "--task", str(task), "--output", str(output)])

    assert error.value.code == 1
    assert output.read_text(encoding="utf-8") == '{"sentinel": true}\n'
