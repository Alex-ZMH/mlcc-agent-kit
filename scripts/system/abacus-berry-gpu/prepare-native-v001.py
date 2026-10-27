"""Materialize the bounded ABACUS Berry GPU candidate input on v100.

This preparation step deliberately stops at the ordinary MLCC task contract:
it reads the retained 0.10 reference task and qualification snapshot, writes a
candidate site/method/request under the 0.15 workspace, materializes the NSCF
task, and asks :class:`SiteRunner` to write ``job.sbatch``.  It never transfers,
submits, waits for, or interprets a numerical job.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from mlcc.berry import BERRY_GPU_IMPLEMENTATION_ID, BERRY_GPU_SCOPE
from mlcc.berry_tasks import create_berry_nscf_task
from mlcc.site_runner import SiteConfig, SiteRunner
from mlcc.tasks import load_task


OLD_WORKSPACE = Path("/home/v100/projects/mlcc/development/0.10.0/project/workspace")
NEW_WORKSPACE = Path("/home/v100/projects/mlcc/development/0.15.0/project/workspace")

REFERENCE_TASK = OLD_WORKSPACE / "tasks/p5-czo-berry-scf-v001"
REFERENCE_METHOD = OLD_WORKSPACE / "configs/cazro3-berry-capability-v001.json"
REFERENCE_SITE = OLD_WORKSPACE / "configs/site.v100-berry-dev-v001.json"
REFERENCE_REQUEST = OLD_WORKSPACE / "configs/berry-gdir1-request-v001.json"

CANDIDATE_TASK_ID = "p5-czo-berry-gdir1-gpu-patched-v001"
CANDIDATE_BINARY = "/home/v100/projects/mlcc/tools/abacus-berry-gpu-v001/install/bin/abacus"
CANDIDATE_LAUNCHER = "/home/v100/miniforge3/envs/mlcc-abacus-berry-gpu-build-v001/bin/mpiexec.hydra"
CANDIDATE_ENVIRONMENT = "/home/v100/projects/mlcc/configs/abacus-berry-gpu-v001-env.sh"

CONFIG_DIR = NEW_WORKSPACE / "configs" / "berry-gpu-native-v001"
REPORT_DIR = NEW_WORKSPACE / "reports" / "berry-gpu-native-v001"
SITE_PATH = CONFIG_DIR / "site.v100-berry-gpu-v001.json"
METHOD_PATH = CONFIG_DIR / "method.cazro3-berry-gpu-v001.json"
REQUEST_PATH = CONFIG_DIR / "request.p5-czo-berry-gdir1-gpu-patched-v001.json"
TASK_PATH = NEW_WORKSPACE / "tasks" / CANDIDATE_TASK_ID / "task.json"
INPUT_ACCEPTANCE_PATH = REPORT_DIR / "input_acceptance.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _candidate_site() -> dict[str, Any]:
    site = deepcopy(_read_json(REFERENCE_SITE))
    site["ssh"] = dict(site.get("ssh", {}))
    site["ssh"]["alias"] = "v100"
    site["workspace"] = {
        "local": str(NEW_WORKSPACE),
        "remote_root": str(NEW_WORKSPACE),
    }

    abacus = dict(site.get("abacus", {}))
    abacus.update(
        {
            "binary": CANDIDATE_BINARY,
            "mpi_launcher": CANDIDATE_LAUNCHER,
            "environment_script": CANDIDATE_ENVIRONMENT,
            "berry_gpu_build": {
                "implementation_id": BERRY_GPU_IMPLEMENTATION_ID,
                "binary": CANDIDATE_BINARY,
                "scope": BERRY_GPU_SCOPE,
            },
        }
    )
    site["abacus"] = abacus

    runner = dict(site.get("runner", {}))
    slurm = dict(runner.get("slurm", {}))
    slurm["environment_script"] = CANDIDATE_ENVIRONMENT
    runner["slurm"] = slurm
    site["runner"] = runner
    return site


def _candidate_method() -> dict[str, Any]:
    method = deepcopy(_read_json(REFERENCE_METHOD))
    qualification = method.get("input_qualification")
    if not isinstance(qualification, dict):
        raise ValueError("retained Berry method must contain input_qualification")
    header_snapshot = qualification.get("header_snapshot")
    if not isinstance(header_snapshot, str) or not header_snapshot.strip():
        raise ValueError("retained Berry method must contain input_qualification.header_snapshot")
    header_path = Path(header_snapshot)
    if not header_path.is_absolute():
        header_path = REFERENCE_METHOD.parent / header_path
    header_path = header_path.resolve()
    if not header_path.is_file():
        raise FileNotFoundError(f"retained input qualification snapshot is missing: {header_path}")
    qualification["header_snapshot"] = str(header_path)

    # Keep the physical method set and every numerical field identical to the
    # retained host50 reference.  Only the explicit Berry implementation
    # selector is added; the site record remains the authority for its binary.
    berry = dict(method.get("berry", {}))
    berry["implementation_id"] = BERRY_GPU_IMPLEMENTATION_ID
    method["berry"] = berry
    return method


def _candidate_request() -> dict[str, Any]:
    request = deepcopy(_read_json(REFERENCE_REQUEST))
    request["task_id"] = CANDIDATE_TASK_ID
    resources = dict(request.get("resource_request", {}))
    resources.update(
        {
            "nodes": 1,
            "partition": "gpu",
            "ntasks": 1,
            "cpus_per_task": 1,
            "gpus_per_task": "v100:1",
            "hint": "nomultithread",
            "mem_mib": 8192,
            "time": 0,
            "job_name": f"mlcc-{CANDIDATE_TASK_ID}",
        }
    )
    request["resource_request"] = resources
    return request


def _input_acceptance(task: dict[str, Any], site: dict[str, Any], method: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    source_task = _read_json(REFERENCE_TASK / "task.json")
    source_header = method["input_qualification"]["header_snapshot"]
    berry = task.get("berry", {})
    resources = task.get("resource_request", {})
    return {
        "schema": "mlcc.berry-gpu-native-input-acceptance.v001",
        "status": "materialized_not_submitted",
        "materialization_only": True,
        "no_new_dft": True,
        "task_id": task.get("task_id"),
        "task_path": str(TASK_PATH),
        "prepared_script": str(TASK_PATH.parent / "job.sbatch"),
        "source_reference": {
            "task_id": source_task.get("task_id"),
            "task_path": str(REFERENCE_TASK),
            "scheduler_job_id": source_task.get("scheduler_job_id"),
            "method_path": str(REFERENCE_METHOD),
            "input_qualification_header_snapshot": str(source_header),
            "read_only": True,
        },
        "candidate_configuration": {
            "site_path": str(SITE_PATH),
            "method_path": str(METHOD_PATH),
            "request_path": str(REQUEST_PATH),
            "ssh_alias": site["ssh"]["alias"],
            "workspace_local": site["workspace"]["local"],
            "workspace_remote_root": site["workspace"]["remote_root"],
        },
        "resource_request": resources,
        "physical_inputs": {
            "ecutwfc_Ry": method["parameters"]["ecutwfc_Ry"],
            "kpoints": method["kpoints"],
            "scf_thr": method["parameters"]["scf_thr"],
            "nbands": method["parameters"]["nbands"],
            "gdir": request["berry"]["gdir"],
            "pw_diag_thr": request["berry"]["pw_diag_thr"],
            "nspin": method["science"]["nspin"],
            "symmetry": request["berry"]["symmetry"],
        },
        "binary_source": site["abacus"]["binary"],
        "mpi_launcher": site["abacus"]["mpi_launcher"],
        "environment_script": site["abacus"]["environment_script"],
        "implementation_id": BERRY_GPU_IMPLEMENTATION_ID,
        "gpu_build_scope": BERRY_GPU_SCOPE,
        "binary_validation": "not_performed_by_materialization",
        "transfer_submitted": False,
        "slurm_submitted": False,
        "scheduler_job_id": None,
        "scientific_qualification": False,
        "production_qualification": False,
        "qualification_status": "not_assessed_by_input_materialization",
        "native_dft_jobs": [],
    }


def main() -> None:
    site = _candidate_site()
    method = _candidate_method()
    request = _candidate_request()
    _write_json(SITE_PATH, site)
    _write_json(METHOD_PATH, method)
    _write_json(REQUEST_PATH, request)

    create_berry_nscf_task(
        reference_task_path=REFERENCE_TASK,
        method_path=METHOD_PATH,
        site_path=SITE_PATH,
        request_path=REQUEST_PATH,
    )
    runner = SiteRunner(SiteConfig.from_file(SITE_PATH))
    prepared_task = runner.prepare(load_task(TASK_PATH))
    acceptance = _input_acceptance(prepared_task, site, method, request)
    _write_json(INPUT_ACCEPTANCE_PATH, acceptance)
    print(json.dumps(acceptance, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
