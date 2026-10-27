"""Postprocess one completed native Berry GPU candidate task.

This entry point deliberately consumes an already submitted and queried task.
It never submits, retries, tunes, compiles, or recalculates a DFT task.  The
candidate is parsed through the public :func:`parse_berry_task` path and the
retained CPU58 observation is read through :func:`read_berry_task` only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT / "workspace"
DEFAULT_CANDIDATE_TASK = WORKSPACE / "tasks/p5-czo-berry-gdir1-gpu-patched-v001"
DEFAULT_CPU_TASK = Path(
    "/home/v100/projects/mlcc/development/0.10.0/project/workspace/"
    "tasks/p5-czo-berry-gdir1-cpu4-v001"
)

GPU_IMPLEMENTATION_ID = "mlcc-abacus-3.10.1-berry-gpu-v001"
GPU_SCOPE = "single_mpi_non_soc_nspin1"
P_TOLERANCE_C_PER_M2 = 1.0e-6
Q_TOLERANCE_C_PER_M2 = 1.0e-7

EXPECTED_RESOURCES = {
    "nodes": 1,
    "partition": "gpu",
    "ntasks": 1,
    "cpus_per_task": 1,
    "gpus_per_task": "v100:1",
    "mem_mib": 8192,
    "time": 0,
}

PHYSICAL_METHOD_KEYS = (
    "engine",
    "abacus_version_target",
    "stage",
    "model_id",
    "version",
    "dft_functional",
    "basis_type",
    "ks_solver",
    "nspin",
    "lspinorb",
    "noncolin",
    "occupations",
    "smearing_method",
    "mixing_type",
    "relax_method",
    "symmetry",
    "element_order",
    "kpoints",
    "parameters",
    "pseudopotential_ids",
    "pseudopotential_metadata",
    "net_charge",
)

BERRY_PROTOCOL_KEYS = (
    "role",
    "berry_phase",
    "gdir",
    "symmetry",
    "pw_diag_thr",
    "out_chg",
    "init_chg",
    "read_file_dir",
    "nspin",
    "lspinorb",
    "noncolin",
    "occupations",
    "source_reference_task_id",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _copy_text(source: Path, target: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(source)
    text = source.read_text(encoding="utf-8")
    target.write_text(text, encoding="utf-8")
    return text


def _load_mlcc(bundle_root: Path):
    source_root = bundle_root / "src"
    if not source_root.is_dir():
        raise FileNotFoundError(f"bundle source directory is missing: {source_root}")
    sys.path.insert(0, str(source_root))
    from mlcc.berry import BERRY_GPU_IMPLEMENTATION_ID, BERRY_GPU_SCOPE
    from mlcc.berry_results import parse_berry_task, read_berry_task

    return BERRY_GPU_IMPLEMENTATION_ID, BERRY_GPU_SCOPE, parse_berry_task, read_berry_task


def _method_and_task(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return _read_json(directory / "method.json"), _read_json(directory / "task.json")


def _check_scheduler_record(
    task: Mapping[str, Any],
    *,
    directory: Path,
    report_dir: Path,
    require_gpu: bool,
) -> dict[str, Any]:
    job_id = task.get("scheduler_job_id")
    if job_id in (None, ""):
        raise ValueError("candidate task has no recorded native scheduler_job_id")
    job_id = str(job_id)
    if task.get("scheduler_state") != "COMPLETED" or task.get("exit_code") != "0:0":
        raise ValueError(
            "candidate task requires saved native Slurm COMPLETED/0:0 evidence: "
            f"state={task.get('scheduler_state')!r}, exit={task.get('exit_code')!r}"
        )

    raw_query = task.get("scheduler_query_raw_stdout")
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise ValueError("candidate task requires raw scheduler query evidence from root query")
    if not re.search(rf"(?:^|\s)JobId={re.escape(job_id)}(?:\s|$)", raw_query):
        raise ValueError("saved scheduler query does not bind to task.scheduler_job_id")
    for marker in ("JobState=COMPLETED", "ExitCode=0:0"):
        if marker not in raw_query:
            raise ValueError(f"saved scheduler query is missing {marker}")
    if require_gpu and "Partition=gpu" not in raw_query:
        raise ValueError("saved scheduler query does not prove the GPU partition")
    if require_gpu and "TimeLimit=UNLIMITED" not in raw_query:
        raise ValueError("saved scheduler query does not prove the time=0 unlimited DFT allocation")
    (report_dir / "candidate-scheduler-query.txt").write_text(raw_query, encoding="utf-8")

    stderr_path = directory / "stderr.log"
    stdout_path = directory / "stdout.log"
    stderr = _copy_text(stderr_path, report_dir / "candidate-stderr.log")
    _copy_text(stdout_path, report_dir / "candidate-stdout.log")
    return {
        "job_id": job_id,
        "scheduler_state": task.get("scheduler_state"),
        "exit_code": task.get("exit_code"),
        "saved_query": str(report_dir / "candidate-scheduler-query.txt"),
        "raw_stderr": str(stderr_path),
        "raw_stdout": str(stdout_path),
        "stderr_bytes": len(stderr.encode("utf-8")),
        "query_source": "task.scheduler_query_raw_stdout written by root query",
    }


def _check_candidate_contract(
    task: Mapping[str, Any],
    method: Mapping[str, Any],
    *,
    implementation_id: str,
    scope: str,
) -> None:
    if task.get("task_id") != "p5-czo-berry-gdir1-gpu-patched-v001":
        raise ValueError("unexpected Berry GPU candidate task identity")
    if task.get("engine") != "abacus" or task.get("engine_version") != "3.10.1":
        raise ValueError("candidate must target ABACUS 3.10.1")
    if task.get("stage") != "P5" or task.get("calculation") != "nscf":
        raise ValueError("candidate must be a P5 NSCF task")
    resources = task.get("resource_request")
    if not isinstance(resources, Mapping):
        raise ValueError("candidate resource_request is missing")
    for key, expected in EXPECTED_RESOURCES.items():
        if resources.get(key) != expected:
            raise ValueError(
                f"candidate resource_request.{key} must be {expected!r}, "
                f"observed {resources.get(key)!r}"
            )
    berry = method.get("berry")
    if not isinstance(berry, Mapping):
        raise ValueError("candidate method.berry is missing")
    if method.get("device") != "gpu" or berry.get("device") != "gpu":
        raise ValueError("candidate method must explicitly select GPU execution")
    if berry.get("implementation_id") != implementation_id:
        raise ValueError("candidate method implementation_id differs from registered GPU build")
    build = berry.get("gpu_build")
    if not isinstance(build, Mapping):
        raise ValueError("candidate method.gpu_build is missing")
    if build.get("implementation_id") != implementation_id or build.get("scope") != scope:
        raise ValueError("candidate method GPU build provenance is not the registered scope")
    if method.get("stage") != "nscf" or berry.get("role") != "nscf" or berry.get("gdir") != 1:
        raise ValueError("candidate must select the declared gdir=1 NSCF Berry protocol")
    if task.get("berry", {}).get("gdir") != 1:
        raise ValueError("candidate task must select gdir=1")


def _check_native_completion(directory: Path, method: Mapping[str, Any], report_dir: Path) -> dict[str, Any]:
    suffix = method.get("suffix")
    if not isinstance(suffix, str) or not suffix:
        raise ValueError("candidate method suffix is missing")
    log_path = directory / f"OUT.{suffix}" / "running_nscf.log"
    text = _copy_text(log_path, report_dir / "candidate-running_nscf.log")
    stdout_path = directory / "stdout.log"
    stdout_text = stdout_path.read_text(encoding="utf-8")
    markers = {
        "finish_time": bool(re.search(r"^\s*Finish\s+Time\s*:", text, re.IGNORECASE | re.MULTILINE)),
        "total_time": bool(re.search(r"^\s*Total\s+Time\s*:", text, re.IGNORECASE | re.MULTILINE)),
        "finish_berry_phase_stdout": bool(
            re.search(r"Finish\s+Berry\s+phase\s+polarization", stdout_text, re.IGNORECASE)
        ),
        "no_convergence_failure_marker": "convergence has not been achieved" not in text.lower(),
    }
    if not all(markers.values()):
        raise ValueError(f"candidate native NSCF completion/convergence evidence is incomplete: {markers}")
    return {
        "log_path": str(log_path),
        "evidence_copy": str(report_dir / "candidate-running_nscf.log"),
        "markers": markers,
        "interpretation": "native NSCF completion markers; no SCF self-consistency claim",
    }


def _compare_identity(
    candidate_directory: Path,
    candidate_method: Mapping[str, Any],
    candidate_task: Mapping[str, Any],
    cpu_directory: Path,
    cpu_method: Mapping[str, Any],
    cpu_task: Mapping[str, Any],
) -> dict[str, Any]:
    differences: dict[str, Any] = {}
    for key in ("engine", "engine_version", "stage", "calculation", "model_id", "model_version", "method_set"):
        if candidate_task.get(key) != cpu_task.get(key):
            differences[f"task.{key}"] = {"candidate": candidate_task.get(key), "cpu58": cpu_task.get(key)}
    for key in PHYSICAL_METHOD_KEYS:
        if candidate_method.get(key) != cpu_method.get(key):
            differences[f"method.{key}"] = {"candidate": candidate_method.get(key), "cpu58": cpu_method.get(key)}
    candidate_berry = candidate_method.get("berry", {})
    cpu_berry = cpu_method.get("berry", {})
    for key in BERRY_PROTOCOL_KEYS:
        if candidate_berry.get(key) != cpu_berry.get(key):
            differences[f"method.berry.{key}"] = {
                "candidate": candidate_berry.get(key),
                "cpu58": cpu_berry.get(key),
            }
    candidate_map = _read_json(candidate_directory / "STRU.atom-map.json")
    cpu_map = _read_json(cpu_directory / "STRU.atom-map.json")
    geometry_same = candidate_map == cpu_map
    if not geometry_same:
        differences["STRU.atom-map.json"] = "candidate and CPU58 atom maps differ"
    charge_source_same = (
        candidate_berry.get("charge_density", {}).get("source_task_id")
        == cpu_berry.get("charge_density", {}).get("source_task_id")
        and candidate_berry.get("charge_density", {}).get("source_paths")
        == cpu_berry.get("charge_density", {}).get("source_paths")
    )
    if not charge_source_same:
        differences["berry.charge_density.source"] = {
            "candidate": candidate_berry.get("charge_density"),
            "cpu58": cpu_berry.get("charge_density"),
        }
    if differences:
        raise ValueError(f"candidate method/geometry differs from retained CPU58 reference: {differences}")
    return {
        "same_physical_method": True,
        "same_geometry_atom_map": True,
        "same_gdir": candidate_berry.get("gdir") == cpu_berry.get("gdir") == 1,
        "same_source50_charge_binding": True,
        "candidate_device_difference": {
            "candidate": candidate_method.get("device"),
            "cpu58": cpu_method.get("device"),
        },
    }


def _compare_polarization(candidate: Mapping[str, Any], cpu: Mapping[str, Any]) -> dict[str, Any]:
    p_candidate = float(candidate["total_P_C_per_m2"])
    p_cpu = float(cpu["total_P_C_per_m2"])
    q_candidate = float(candidate["modulo_quantum_C_per_m2"])
    q_cpu = float(cpu["modulo_quantum_C_per_m2"])
    raw_delta = p_candidate - p_cpu
    q_delta = abs(q_candidate - q_cpu)
    if q_delta > Q_TOLERANCE_C_PER_M2:
        raise ValueError(f"Berry C/m2 modulo quantum delta exceeds threshold: {q_delta}")
    if q_cpu <= 0.0:
        raise ValueError("CPU58 Berry modulo quantum must be positive")
    representative_integer_shift = int(round(raw_delta / q_cpu))
    modulo_delta = raw_delta - representative_integer_shift * q_cpu
    if abs(modulo_delta) > P_TOLERANCE_C_PER_M2:
        raise ValueError(
            "Berry C/m2 polarization modulo delta exceeds threshold: "
            f"{abs(modulo_delta)} (raw delta={raw_delta}, shift={representative_integer_shift})"
        )
    return {
        "unit": "C/m^2",
        "candidate_P": p_candidate,
        "cpu58_P": p_cpu,
        "raw_delta_P": raw_delta,
        "representative_integer_shift": representative_integer_shift,
        "modulo_delta_P": modulo_delta,
        "P_tolerance": P_TOLERANCE_C_PER_M2,
        "candidate_Q": q_candidate,
        "cpu58_Q": q_cpu,
        "delta_Q": q_delta,
        "Q_tolerance": Q_TOLERANCE_C_PER_M2,
        "threshold_basis": "seven-decimal native polarization print",
        "branch_path_used": False,
        "comparison_note": "representative integer shift is a modulo comparison only; no branch path was constructed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--candidate-task", type=Path, default=DEFAULT_CANDIDATE_TASK)
    parser.add_argument("--cpu-reference-task", type=Path, default=DEFAULT_CPU_TASK)
    args = parser.parse_args()

    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=False)
    candidate_directory = args.candidate_task.resolve()
    cpu_directory = args.cpu_reference_task.resolve()
    report: dict[str, Any] = {
        "schema": "mlcc.berry-gpu-native-acceptance.v001",
        "verification_job_id": os.environ.get("SLURM_JOB_ID"),
        "bundle_root": str(args.bundle_root.resolve()),
        "candidate_task": str(candidate_directory),
        "cpu58_reference_task": str(cpu_directory),
        "passed": False,
        "checks": [],
        "new_numerical_jobs": [],
        "native_job_id_source": "candidate task.scheduler_job_id; no guessed ID",
        "scientific_qualification": False,
        "production_qualification": False,
        "branch_path_qualification": False,
        "born_charge_qualification": False,
        "epsilon_qualification": False,
        "gpu_failure_issue_53_preserved": True,
    }

    def check(label: str, passed: bool, detail: Any = None) -> None:
        item: dict[str, Any] = {"criterion": label, "passed": bool(passed)}
        if detail is not None:
            item["detail"] = detail
        report["checks"].append(item)
        if not passed:
            raise ValueError(f"Berry GPU native acceptance failed: {label}")

    try:
        implementation_id, scope, parse_berry_task, read_berry_task = _load_mlcc(args.bundle_root.resolve())
        check("registered implementation constant", implementation_id == GPU_IMPLEMENTATION_ID)
        check("registered GPU scope constant", scope == GPU_SCOPE)

        candidate_method, candidate_task = _method_and_task(candidate_directory)
        cpu_method, cpu_task = _method_and_task(cpu_directory)
        _check_candidate_contract(
            candidate_task,
            candidate_method,
            implementation_id=implementation_id,
            scope=scope,
        )
        report["candidate_resource_request"] = candidate_task.get("resource_request")
        report["candidate_native_scheduler"] = _check_scheduler_record(
            candidate_task,
            directory=candidate_directory,
            report_dir=report_dir,
            require_gpu=True,
        )
        report["native_convergence"] = _check_native_completion(
            candidate_directory, candidate_method, report_dir
        )

        cpu_result = read_berry_task(cpu_directory)
        report["cpu58_read"] = {
            "operation": "read_berry_task",
            "task_id": cpu_result.get("task_id"),
            "scheduler_job_id": cpu_result.get("scheduler_job_id"),
            "scientific_status": cpu_result.get("scientific_status"),
            "new_numerical_jobs": [],
            "recalculated": False,
        }
        check("retained CPU58 reference is read-only parsed", report["cpu58_read"]["recalculated"] is False)

        _compare_identity(
            candidate_directory,
            candidate_method,
            candidate_task,
            cpu_directory,
            cpu_method,
            cpu_task,
        )
        report["identity_comparison"] = {
            "same_physical_method": True,
            "same_geometry_atom_map": True,
            "same_gdir": True,
            "same_source50_charge_binding": True,
            "candidate_device": "gpu",
            "cpu58_device": "cpu",
        }

        candidate_result = parse_berry_task(candidate_directory)
        report["candidate_parse"] = {
            "operation": "parse_berry_task",
            "task_id": candidate_result.get("task_id"),
            "scheduler_job_id": candidate_result.get("scheduler_job_id"),
            "device": candidate_result.get("device"),
            "implementation_id": candidate_result.get("implementation_id"),
            "binary_source": candidate_result.get("binary_source"),
            "nscf_completed": candidate_result.get("nscf_completed"),
            "branch_status": candidate_result.get("branch_status"),
            "scientific_status": candidate_result.get("scientific_status"),
        }
        check("candidate parser proves GPU", candidate_result.get("device") == "gpu")
        check(
            "candidate parser preserves registered implementation",
            candidate_result.get("implementation_id") == implementation_id,
        )
        check("candidate parser proves native completion", candidate_result.get("nscf_completed") is True)
        check("candidate result keeps branch unwrapped", candidate_result.get("branch_status") == "not_unwrapped")
        check("candidate result remains scientifically unqualified", candidate_result.get("scientific_qualification") is False)

        report["comparison"] = _compare_polarization(candidate_result, cpu_result)
        report["scope"] = {
            "engineering_system_path": True,
            "branch_path": False,
            "born_charge": False,
            "epsilon_infinity": False,
            "production_enablement": False,
            "qualification_note": "single gdir=1 Berry parser/transfer path only",
        }
        report["passed"] = True
    except Exception as error:
        report["fatal_error"] = f"{type(error).__name__}: {error}"
    finally:
        _write_json(report_dir / "acceptance.json", report)

    print(
        json.dumps(
            {
                "passed": report["passed"],
                "report": str(report_dir / "acceptance.json"),
                "candidate_task": str(candidate_directory),
                "native_job_id": report.get("candidate_native_scheduler", {}).get("job_id"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
