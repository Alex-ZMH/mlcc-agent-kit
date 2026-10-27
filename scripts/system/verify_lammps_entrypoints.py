"""Exercise LAMMPS CLI on a genuine job41 evidence copy and new input only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    report = args.report_dir.resolve()
    report.mkdir(parents=True)
    env = dict(os.environ, PYTHONPATH=str(args.bundle_root.resolve() / "src"))
    workspace = ROOT / "workspace"
    original = workspace / "tasks/p9-ni-lammps-run0-v001"
    original_task_text = (original / "task.json").read_text(encoding="utf-8")
    original_result_text = (original / "result.json").read_text(encoding="utf-8")
    task = json.loads(original_task_text)
    original_result = json.loads(original_result_text)
    evidence = report / "job41-evidence-copy"
    shutil.copytree(original, evidence)
    (evidence / "copy-origin.json").write_text(json.dumps({
        "source_directory": str(original.resolve()), "scheduler_job_id": "41",
        "purpose": "installed parser regression on copied real evidence; no new calculation",
    }, indent=2) + "\n", encoding="utf-8")
    commands = []

    def write(name, value):
        path = report / name
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        return path

    def run(name, arguments):
        command = [sys.executable, "-m", "mlcc.cli", *map(str, arguments)]
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                   encoding="utf-8", capture_output=True)
        (report / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (report / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        commands.append({"command": command, "exit_code": completed.returncode})
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    parsed = run("parse", ["parse-lammps", "--task", evidence / "task.json"])
    continuation = run("resume", ["resume-plan", "--task", evidence / "task.json",
                                   "--site", task["site_file"]])
    site = json.loads(Path(task["site_file"]).read_text(encoding="utf-8"))
    site["workspace"]["local"] = str(report / "input-workspace")
    site_path = write("input-only-site.json", site)
    request_path = write("input-only-request.json", {
        "task_id": "lammps-input-only-acceptance", "resource_request": task["resource_request"],
        "required_results": [],
    })
    new_input = run("create", ["create-lammps", "--study",
        workspace / "configs/cases/ni-lammps-engineering-v001.json", "--model", task["model_path"],
        "--potential", task["potential_file"], "--protocol", task["protocol_file"],
        "--site", site_path, "--request", request_path])
    checks = {
        "native_job41_identity": parsed["scheduler_job_id"] == "41" and parsed["task_id"] == task["task_id"],
        "native_terminal_state": parsed["scheduler_state"] == "COMPLETED" and parsed["exit_code"] == "0:0",
        "native_values_unchanged": all(parsed[key] == original_result[key]
            for key in ("energy_eV", "forces_eV_per_A", "positions_angstrom", "pressure_GPa", "atom_ids")),
        "raw_run0_not_md": parsed["step"] == 0 and parsed["protocol"]["kind"] == "run0",
        "engineering_status": parsed["scientific_status"] == "evaluated_engineering_fixture"
            and parsed["production_qualification"] is False,
        "workflow_recognizes_engineering_completion": continuation["action"] == "completed"
            and continuation["scientific_qualification"] is False,
        "input_created_without_submission": new_input["status"] == "defined"
            and new_input["scheduler_job_id"] is None and new_input["runner"] == "slurm",
        "potential_and_protocol_retained": new_input["potential"] == task["potential"] and new_input["protocol"] == task["protocol"],
        "original_job41_preserved": (original / "task.json").read_text(encoding="utf-8") == original_task_text
            and (original / "result.json").read_text(encoding="utf-8") == original_result_text,
    }
    acceptance = {"passed": all(checks.values()), "checks": checks, "commands": commands,
                  "native_source_job": "41", "new_numerical_jobs": [],
                  "production_qualification": False, "MD_sampling_qualification": False}
    write("acceptance.json", acceptance)
    print(json.dumps({"passed": acceptance["passed"], "checks": len(checks), "report": str(report)}))
    return 0 if acceptance["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
