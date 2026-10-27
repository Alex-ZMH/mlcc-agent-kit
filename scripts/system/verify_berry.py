"""Exercise the 0.10.0 ABACUS Berry entry points on saved v100 evidence.

The script consumes the two real CZO P5 task directories and writes only an
acceptance report plus input-only task copies below ``--report-dir``.  It
never submits a scheduler job and never changes the source task directories.
The real Berry NSCF directory is copied before parsing so the parser's result
write is isolated from the collected evidence.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCF_TASK_ID = "p5-czo-berry-scf-v001"
DEFAULT_NSCF_TASK = ROOT / "workspace/tasks/p5-czo-berry-gdir1-v001"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return path


def _source_paths(result: dict[str, Any], result_path: Path) -> list[Path]:
    values = result.get("source_files")
    if not isinstance(values, dict) or not values:
        raise ValueError(f"result source_files is missing or empty: {result_path}")
    paths: list[Path] = []
    for value in values.values():
        if not isinstance(value, str) or not value:
            raise ValueError(f"result source_files contains a non-path value: {result_path}")
        source = Path(value)
        if not source.is_absolute():
            source = result_path.parent / source
        paths.append(source.resolve())
    return paths


def _native_identity(directory: Path, *, require_result: bool = True) -> dict[str, Any]:
    task_path = directory / "task.json"
    method_path = directory / "method.json"
    result_path = directory / "result.json"
    required_paths = [task_path, method_path]
    if require_result:
        required_paths.append(result_path)
    for required in required_paths:
        if not required.is_file():
            raise FileNotFoundError(required)
    task = _json(task_path)
    method = _json(method_path)
    result = _json(result_path) if result_path.is_file() else None
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        raise ValueError(f"native task is not COMPLETED/0:0: {task_path}")
    job_id = task.get("scheduler_job_id")
    if job_id in (None, ""):
        raise ValueError(f"native task has no scheduler job ID: {task_path}")
    if result is not None:
        if result.get("scheduler_job_id") != job_id:
            raise ValueError(f"native result/job identity differs: {result_path}")
        if result.get("task_id") != task.get("task_id"):
            raise ValueError(f"native result/task identity differs: {result_path}")
    return {"task": task, "method": method, "result": result,
            "task_path": task_path, "method_path": method_path, "result_path": result_path}


def _prepare_input_configuration(
    report: Path,
    *,
    method_source: Path,
    study_source: Path,
    model_source: Path,
    site_source: Path,
    reference_request_source: Path,
    nscf_request_source: Path,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    """Prepare all input-only copies inside ``report`` from explicit sources."""

    method = _json(method_source)
    qualification = method.get("input_qualification")
    if not isinstance(qualification, dict) or not isinstance(qualification.get("header_snapshot"), str):
        raise ValueError("explicit Berry method configuration must declare input_qualification.header_snapshot")
    snapshot_source = (method_source.parent / qualification["header_snapshot"]).resolve()
    if not snapshot_source.is_file():
        raise FileNotFoundError(f"configured Berry UPF header snapshot: {snapshot_source}")
    snapshot_copy = report / "czo-upf-headers-v001.json"
    shutil.copy2(snapshot_source, snapshot_copy)
    qualification["header_snapshot"] = str(snapshot_copy)
    method_path = _write_json(report / "berry-method-input-only.json", method)

    if not study_source.is_file() or not model_source.is_dir() or not site_source.is_file():
        raise FileNotFoundError("explicit CZO Berry study/model/site source is missing")
    if not reference_request_source.is_file() or not nscf_request_source.is_file():
        raise FileNotFoundError("explicit Berry reference/NSCF request template is missing")

    model_path = report / "input-model"
    shutil.copytree(model_source, model_path)
    study_path = report / "input-study.json"
    _write_json(study_path, _json(study_source))
    site = _json(site_source)
    workspace = report / "input-workspace"
    workspace.mkdir(parents=True, exist_ok=False)
    if not isinstance(site.get("workspace"), dict):
        raise ValueError("site configuration must contain workspace object")
    site["workspace"]["local"] = str(workspace)
    site_path = _write_json(report / "site-input-only.json", site)

    reference_request = _json(reference_request_source)
    reference_request["task_id"] = "p5-czo-berry-scf-input-only-v001"
    reference_request["required_results"] = []
    reference_request_path = _write_json(report / "reference-request-input-only.json", reference_request)
    nscf_request = _json(nscf_request_source)
    nscf_request["task_id"] = "p5-czo-berry-gdir1-input-only-v001"
    nscf_request["required_results"] = []
    nscf_request_path = _write_json(report / "nscf-request-input-only.json", nscf_request)
    return model_path, study_path, method_path, site_path, reference_request_path, nscf_request_path


def _run_command(
    report: Path,
    env: dict[str, str],
    name: str,
    arguments: list[Any],
    *,
    expected: int = 0,
) -> tuple[subprocess.CompletedProcess[str], Any | None]:
    command = [sys.executable, "-m", "mlcc.cli", *[str(value) for value in arguments]]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    (report / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (report / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != expected:
        raise AssertionError(
            f"{name}: expected exit {expected}, got {completed.returncode}: {completed.stderr}"
        )
    parsed: Any | None = None
    if completed.stdout.strip():
        parsed = json.loads(completed.stdout)
    return completed, parsed


def _check_required_results_gate(
    *, report: Path, nscf_task_id: str, parsed_result: dict[str, Any], parsed_task: dict[str, Any]
) -> bool:
    """Ensure an unqualified engineering Berry result cannot be a dependency."""

    # Use a copy of the parsed real result under the input-only workspace.  It
    # is still native evidence from the copied v100 task; only its dependency
    # role is synthetic for this negative contract check.
    dependency_workspace = report / "input-workspace"
    dependency_dir = dependency_workspace / "tasks" / nscf_task_id
    dependency_dir.mkdir(parents=True, exist_ok=False)
    dependency_task = deepcopy(parsed_task)
    dependency_task["task_id"] = nscf_task_id
    dependency_task_path = dependency_dir / "task.json"
    _write_json(dependency_task_path, dependency_task)
    dependency_result = deepcopy(parsed_result)
    dependency_result["task_id"] = nscf_task_id
    dependency_result_path = dependency_dir / "result.json"
    _write_json(dependency_result_path, dependency_result)

    from mlcc.tasks import TaskRecord
    from mlcc.workflow import require_result_dependencies

    candidate = TaskRecord(
        {
            "task_id": "berry-dependent-input-only-v001",
            "required_results": [
                {
                    "task_id": nscf_task_id,
                    "result_file": "result.json",
                    "scientific_status": dependency_result["scientific_status"],
                }
            ],
        }
    )
    try:
        require_result_dependencies(candidate, dependency_workspace)
    except ValueError as error:
        return "not an accepted converged dependency" in str(error)
    return False


def _run_acceptance(report: Path, bundle: Path, nscf_dir: Path, method_source: Path) -> dict[str, Any]:
    env = dict(os.environ, PYTHONPATH=str(bundle / "src"))
    workspace = ROOT / "workspace"
    scf_dir = workspace / "tasks" / SCF_TASK_ID
    if not scf_dir.is_dir() or not nscf_dir.is_dir():
        raise FileNotFoundError(
            f"real v100 Berry task directories are required: {scf_dir}, {nscf_dir}"
        )

    scf = _native_identity(scf_dir)
    nscf = _native_identity(nscf_dir, require_result=False)
    nscf_task_id = nscf["task"].get("task_id")
    if not isinstance(nscf_task_id, str) or not nscf_task_id:
        raise ValueError("selected Berry NSCF task must declare task_id")
    study_source = workspace / "configs/cases/cazro3-firing-v003.json"
    model_source = workspace / "models/cazro3-pnma-pristine/v001"
    site_source = workspace / "configs/site.v100-berry-dev-v001.json"
    reference_request_source = workspace / "configs/berry-reference-request-v001.json"
    nscf_request_source = workspace / "configs/berry-gdir1-cpu-request-v001.json"
    for source in (
        method_source,
        study_source,
        model_source,
        site_source,
        reference_request_source,
        nscf_request_source,
    ):
        if not source.exists():
            raise FileNotFoundError(source)
    model_path, study_path, method_path, site_path, reference_request_path, nscf_request_path = (
        _prepare_input_configuration(
            report,
            method_source=method_source,
            study_source=study_source,
            model_source=model_source,
            site_source=site_source,
            reference_request_source=reference_request_source,
            nscf_request_source=nscf_request_source,
        )
    )
    input_workspace = report / "input-workspace"
    input_tasks = input_workspace / "tasks"

    checks: dict[str, bool] = {}
    command_records: list[dict[str, Any]] = []
    details: dict[str, Any] = {
        "source_tasks": {
            "reference": str(scf_dir),
            "nscf": str(nscf_dir),
            "reference_job_id": scf["task"].get("scheduler_job_id"),
            "nscf_job_id": nscf["task"].get("scheduler_job_id"),
        },
        "new_numerical_jobs": [],
        "input_only_workspace": str(input_workspace),
    }

    # Source task/result identity and native source evidence are checked before
    # any parser call so missing evidence is a hard acceptance failure.
    scf_sources = _source_paths(scf["result"], scf["result_path"])
    checks["reference_native_completed_and_sources"] = (
        scf["task"].get("scheduler_state") == "COMPLETED"
        and scf["task"].get("exit_code") == "0:0"
        and bool(scf["task"].get("scheduler_job_id"))
        and all(path.is_file() for path in scf_sources)
    )
    nscf_native_required = [
        nscf_dir / "task.json",
        nscf_dir / "method.json",
        nscf_dir / "INPUT",
        nscf_dir / "KPT",
        nscf_dir / "STRU",
        nscf_dir / "STRU.atom-map.json",
    ]
    nscf_suffix = nscf["method"].get("suffix")
    if not isinstance(nscf_suffix, str) or not nscf_suffix:
        raise ValueError("real Berry NSCF method suffix is missing")
    nscf_native_required.extend(
        [nscf_dir / f"OUT.{nscf_suffix}" / "running_nscf.log", nscf_dir / f"OUT.{nscf_suffix}" / "INPUT"]
    )
    checks["nscf_native_completed_and_sources"] = (
        nscf["task"].get("scheduler_state") == "COMPLETED"
        and nscf["task"].get("exit_code") == "0:0"
        and bool(nscf["task"].get("scheduler_job_id"))
        and all(path.is_file() for path in nscf_native_required)
    )

    completed, created_reference = _run_command(
        report,
        env,
        "create-reference",
        [
            "create-berry-reference",
            "--study",
            study_path,
            "--model",
            model_path,
            "--method",
            method_path,
            "--site",
            site_path,
            "--request",
            reference_request_path,
        ],
    )
    command_records.append({"name": "create-reference", "exit_code": completed.returncode, "expected_exit_code": 0})
    if not isinstance(created_reference, dict):
        raise ValueError("create-berry-reference did not return a task object")
    created_reference_dir = input_tasks / created_reference["task_id"]
    checks["create_reference_input_only"] = (
        created_reference["task_id"] == "p5-czo-berry-scf-input-only-v001"
        and created_reference["scheduler_job_id"] is None
        and created_reference["status"] == "defined"
        and created_reference["production_label"] is False
        and created_reference_dir.is_dir()
        and (created_reference_dir / "INPUT").is_file()
        and (created_reference_dir / "STRU").is_file()
    )

    completed, created_nscf = _run_command(
        report,
        env,
        "create-nscf",
        [
            "create-berry-nscf",
            "--reference-task",
            scf_dir / "task.json",
            "--method",
            method_path,
            "--site",
            site_path,
            "--request",
            nscf_request_path,
        ],
    )
    command_records.append({"name": "create-nscf", "exit_code": completed.returncode, "expected_exit_code": 0})
    if not isinstance(created_nscf, dict):
        raise ValueError("create-berry-nscf did not return a task object")
    created_nscf_dir = input_tasks / created_nscf["task_id"]
    checks["create_nscf_bound_to_real_scf_without_submission"] = (
        created_nscf["task_id"] == "p5-czo-berry-gdir1-input-only-v001"
        and created_nscf["scheduler_job_id"] is None
        and created_nscf["status"] == "defined"
        and created_nscf["berry"]["source_reference_task_id"] == SCF_TASK_ID
        and created_nscf_dir.is_dir()
        and all((created_nscf_dir / name).is_file() for name in ("INPUT", "KPT", "STRU", "SPIN1_CHG.cube"))
    )

    parse_copy = report / "parsed-native-nscf"
    shutil.copytree(nscf_dir, parse_copy)
    parse_task_path = parse_copy / "task.json"
    completed, parsed_result_value = _run_command(
        report, env, "parse-berry", ["parse-berry", "--task", parse_task_path]
    )
    command_records.append({"name": "parse-berry", "exit_code": completed.returncode, "expected_exit_code": 0})
    if not isinstance(parsed_result_value, dict):
        raise ValueError("parse-berry did not return a result object")
    parsed_result_path = parse_copy / "result.json"
    parsed_task = _json(parse_copy / "task.json")
    parsed_result = _json(parsed_result_path)
    parsed_sources = _source_paths(parsed_result, parsed_result_path)
    checks["parse_real_nscf_preserves_native_identity"] = (
        parsed_result.get("task_id") == nscf_task_id
        and parsed_result.get("scheduler_job_id") == nscf["task"].get("scheduler_job_id")
        and parsed_result.get("native_completed") is True
        and parsed_result.get("nscf_completed") is True
        and all(path.is_file() for path in parsed_sources)
    )
    checks["berry_engineering_result_remains_unqualified"] = (
        parsed_result.get("scientific_status") == "evaluated_polarization_unqualified"
        and parsed_result.get("scientific_qualification") is False
        and parsed_result.get("numerical_qualification") is False
        and parsed_result.get("production_qualification") is False
        and parsed_result.get("production_label") is False
        and parsed_result.get("branch_status") == "not_unwrapped"
        and parsed_result.get("branch_unwrapped") is False
    )

    completed, resumed = _run_command(
        report,
        env,
        "resume-plan",
        ["resume-plan", "--task", parse_task_path, "--site", site_path],
    )
    command_records.append({"name": "resume-plan", "exit_code": completed.returncode, "expected_exit_code": 0})
    if not isinstance(resumed, dict):
        raise ValueError("resume-plan did not return a decision object")
    checks["resume_plan_reports_engineering_completion"] = (
        resumed.get("action") == "completed"
        and resumed.get("scientific_qualification") is False
        and resumed.get("production_qualification") is False
        and resumed.get("branch_status") == "not_unwrapped"
    )

    checks["required_results_reject_unqualified_berry"] = _check_required_results_gate(
        report=report,
        nscf_task_id=nscf_task_id,
        parsed_result=parsed_result,
        parsed_task=parsed_task,
    )

    nspin2_method = deepcopy(_json(method_path))
    nspin2_method.setdefault("science", {})["nspin"] = 2
    nspin2_method["nspin"] = 2
    nspin2_method_path = _write_json(report / "nspin2-method-rejection.json", nspin2_method)
    nspin2_request = _json(reference_request_path)
    nspin2_request["task_id"] = "p5-czo-berry-nspin2-rejected-v001"
    nspin2_request_path = _write_json(report / "nspin2-reference-request.json", nspin2_request)
    nspin2_dir = input_tasks / nspin2_request["task_id"]
    nspin2_completed, _ = _run_command(
        report,
        env,
        "reject-nspin2",
        [
            "create-berry-reference",
            "--study",
            study_path,
            "--model",
            model_path,
            "--method",
            nspin2_method_path,
            "--site",
            site_path,
            "--request",
            nspin2_request_path,
        ],
        expected=1,
    )
    command_records.append({"name": "reject-nspin2", "exit_code": nspin2_completed.returncode,
                            "expected_exit_code": 1})
    checks["nspin2_rejected_before_task_directory"] = (
        nspin2_completed.returncode == 1
        and "unsupported_spin_resolved_occupations" in nspin2_completed.stderr
        and not nspin2_dir.exists()
    )

    conditions = parsed_task.get("calculation_conditions")
    study = _json(study_path)
    firing_range = study.get("model", {}).get("temperature_range_K")
    if not isinstance(firing_range, list):
        firing_range = []
    checks["p5_static_temperature_is_not_firing_temperature"] = (
        isinstance(conditions, dict)
        and conditions.get("lattice_temperature_K") is None
        and conditions.get("reference_temperature_K") == 0
        and conditions.get("lattice_temperature_K") not in firing_range
        and parsed_result.get("temperature_K") not in firing_range
    )
    method_kpoints = parsed_result.get("kpoints", nscf["method"].get("kpoints"))
    checks["gamma_2x2x2_direction_is_smoke_only"] = (
        method_kpoints == [2, 2, 2]
        and parsed_result.get("gdir") == 1
        and parsed_result.get("kpoint_qualification") == "smoke_only"
    )

    details.update(
        parsed_result={
            "task_id": parsed_result.get("task_id"),
            "scheduler_job_id": parsed_result.get("scheduler_job_id"),
            "scientific_status": parsed_result.get("scientific_status"),
            "branch_status": parsed_result.get("branch_status"),
            "source_count": len(parsed_sources),
        },
        resumed=resumed,
        nspin2_stderr=(report / "reject-nspin2.stderr.txt").read_text(encoding="utf-8"),
    )
    return {
        "schema": "mlcc.system-berry-acceptance.v001",
        "bundle_root": str(bundle),
        "passed": all(checks.values()),
        "checks": checks,
        "details": details,
        "commands": [
            {**record, "stdout": str(report / f"{record['name']}.stdout.txt"),
             "stderr": str(report / f"{record['name']}.stderr.txt")}
            for record in command_records
        ],
        "new_numerical_jobs": [],
        "native_source_jobs": [
            scf["task"].get("scheduler_job_id"),
            nscf["task"].get("scheduler_job_id"),
        ],
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
        "branch_unwrapped": False,
        "temperature_matrix_started": False,
        "design_assessment": "not_assessed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--nscf-task", type=Path, default=DEFAULT_NSCF_TASK,
                        help="completed real v100 Berry NSCF task directory")
    parser.add_argument("--method", type=Path,
                        default=ROOT / "workspace/configs/cazro3-berry-capability-v001.json",
                        help="explicit Berry method configuration")
    args = parser.parse_args()
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    bundle = args.bundle_root.resolve()
    try:
        acceptance = _run_acceptance(
            report, bundle, args.nscf_task.resolve(), args.method.resolve()
        )
    except Exception as error:
        acceptance = {
            "schema": "mlcc.system-berry-acceptance.v001",
            "bundle_root": str(bundle),
            "passed": False,
            "checks": {},
            "fatal_error": f"{type(error).__name__}: {error}",
            "new_numerical_jobs": [],
            "scientific_qualification": False,
            "numerical_qualification": False,
            "production_qualification": False,
            "branch_unwrapped": False,
            "temperature_matrix_started": False,
        }
    _write_json(report / "acceptance.json", acceptance)
    print(json.dumps({"passed": acceptance["passed"], "checks": len(acceptance.get("checks", {})),
                      "report": str(report / "acceptance.json")}, ensure_ascii=False))
    return 0 if acceptance["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
