from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from mlcc.site_runner import SiteConfig, SiteRunner
from mlcc.tasks import TaskRecord, load_task, save_task


def test_site_config_local_transport_is_explicit_and_ssh_remains_default(tmp_path: Path) -> None:
    base = {
        "ssh": {"alias": "v100"},
        "workspace": {"local": str(tmp_path), "remote_root": str(tmp_path / "remote")},
        "runner": {"selected": "slurm"},
    }

    assert SiteConfig.from_mapping(base).transport == "ssh"
    local = SiteConfig.from_mapping({**base, "ssh": {"alias": "v100", "transport": "local"}})
    assert local.transport == "local"
    with pytest.raises(ValueError, match="ssh.transport"):
        SiteConfig.from_mapping({**base, "ssh": {"alias": "v100", "transport": "direct"}})


@pytest.mark.skipif(shutil.which("sh") is None, reason="local transport requires a POSIX sh")
def test_local_runner_uses_real_shell_and_preserves_copy_events(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    remote_root = tmp_path / "remote"
    local_root.mkdir()
    (local_root / "INCAR").write_text("input\n", encoding="utf-8")
    (local_root / "payload").mkdir()
    (local_root / "payload" / "request.json").write_text("{}\n", encoding="utf-8")
    task_path = local_root / "task.json"
    task = TaskRecord(
        {
            "task_id": "local-001",
            "stage": "integration",
            "engine": "test-stub",
            "command": ["printf", "control-only"],
            "resource_request": {"partition": "cpu", "time": "00:01:00"},
            "transfer_paths": ["INCAR", "payload"],
            "collect_paths": ["OUTCAR", {"remote": "artifacts", "local": "results/artifacts"}],
        },
        task_path,
    )
    save_task(task)
    config = SiteConfig.from_mapping(
        {
            "ssh": {"alias": "v100", "transport": "local"},
            "workspace": {"local": str(local_root), "remote_root": str(remote_root)},
            "runner": {"selected": "slurm", "slurm": {"default_partition": "cpu"}},
        }
    )
    runner = SiteRunner(config)

    control = subprocess.run(
        runner._ssh_command("printf control-ok"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert control.returncode == 0
    assert control.stdout == "control-ok"

    runner.prepare(task)
    runner.transfer(task)
    remote_task = Path(task.data["remote_workdir"])
    assert (remote_task / "job.sbatch").is_file()
    assert (remote_task / "payload" / "request.json").read_text(encoding="utf-8") == "{}\n"

    (remote_task / "OUTCAR").write_text("result\n", encoding="utf-8")
    (remote_task / "artifacts").mkdir()
    (remote_task / "artifacts" / "summary.json").write_text("{}\n", encoding="utf-8")
    collected = runner.collect(task)

    assert collected["collect_status"] == "collected"
    assert (local_root / "OUTCAR").read_text(encoding="utf-8") == "result\n"
    assert (local_root / "results" / "artifacts" / "summary.json").read_text(encoding="utf-8") == "{}\n"
    saved = load_task(task_path).data
    assert [event["action"] for event in saved["events"]] == [
        "prepare",
        "transfer_mkdir",
        "transfer",
        "collect",
        "collect",
    ]
    assert saved["status"] == "transferred"
