"""Prepare the single 4x4x4 refinement point for the charged CZO SCF run.

The 120 Ry / 3x3x3 task already has a real native result.  This script
reuses its selected model, study, site and method controls, changes only the
declared k-point mesh and the task/method identities, and prepares one new
task.  It does not derive a model, rerun a prior point, transfer files, or
submit a numerical job.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
from typing import Any

from mlcc.abacus_tasks import create_abacus_task
from mlcc.method_inputs import parse_upf_header
from mlcc.method_tasks import method_pseudopotentials
from mlcc.site_runner import SiteConfig, SiteRunner
from mlcc.tasks import load_task, utc_now


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"

SOURCE_TASK_ID = "p4-czo-vo8-q2-ecut120-k333-v001"
TASK_ID = "p4-czo-vo8-q2-ecut120-k444-v002"
SOURCE_METHOD = (
    WORKSPACE
    / "configs"
    / "charged-scf-native-v001"
    / f"method-{SOURCE_TASK_ID}.json"
)
SOURCE_REQUEST = (
    WORKSPACE
    / "configs"
    / "charged-scf-native-v001"
    / f"request-{SOURCE_TASK_ID}.json"
)
SOURCE_STUDY = WORKSPACE / "configs" / "charged-scf-native-v001" / "study.json"
SOURCE_SITE = (
    WORKSPACE
    / "configs"
    / "charged-scf-native-v001"
    / "site.v100-charged-native-v001.json"
)
MODEL_PATH = WORKSPACE / "models" / "cazro3-pnma-vo8-q2" / "v001"

CONFIG_DIR = WORKSPACE / "configs" / "charged-scf-native-v002"
REPORT_DIR = WORKSPACE / "reports" / "charged-scf-native-v002"
METHOD_SET = "cazro3-vo8-q2-pw-ecut120-k444-v002"
METHOD_SUFFIX = "CZOVO8Q2E120K444"
HEADER_SNAPSHOT_NAME = "czo-vo8-q2-ecut120-k444-upf-headers-v002.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite refinement artifact: {path}")
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _native_header_snapshot(
    method_path: Path,
    site: dict[str, Any],
    output_path: Path,
    scheduler_job_id: str,
) -> None:
    """Read native UPF headers visible in this v100 preparation allocation."""

    method = _read_json(method_path)
    raw: dict[str, dict[str, str]] = {}
    headers: dict[str, dict[str, Any]] = {}
    for element, filename in method_pseudopotentials(method, site).items():
        source = Path(filename)
        text = source.read_text(encoding="utf-8")
        root_match = re.search(r"<UPF\b[^>]*>", text)
        header_match = re.search(r"<PP_HEADER\b[^>]*>", text, re.IGNORECASE | re.DOTALL)
        if root_match is None or header_match is None:
            raise ValueError(f"selected UPF is missing a native UPF/PP_HEADER tag: {source}")
        excerpt = root_match.group(0) + "\n" + header_match.group(0)
        raw[element] = {"source_path": str(source), "native_excerpt": excerpt}
        headers[element] = parse_upf_header(excerpt, source)
    _write_json(
        output_path,
        {
            "schema": "mlcc.upf-header-snapshot.v1",
            "observed_at": utc_now(),
            "ssh_alias": site["ssh"]["alias"],
            "method_set": method["method_set"],
            "headers": headers,
            "native_excerpts": raw,
            "scheduler_job_id": scheduler_job_id,
            "inspection": "native_files_read_on_v100_in_Slurm",
            "numerical_jobs": [],
        },
    )


def _method_config() -> dict[str, Any]:
    method = deepcopy(_read_json(SOURCE_METHOD))
    original = _read_json(SOURCE_METHOD)
    method["method_set"] = METHOD_SET
    method["kpoints"] = [4, 4, 4]
    method["science"] = dict(method["science"])
    method["science"]["suffix"] = METHOD_SUFFIX
    method["input_qualification"] = {
        "header_snapshot": f"../../reports/charged-scf-native-v002/{HEADER_SNAPSHOT_NAME}"
    }

    # The refinement point is allowed to differ only in mesh and identity.
    expected = {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "basis_type": "pw",
        "net_charge": 2,
        "stage": "scf",
        "ecutwfc_Ry": 120,
        "scf_thr": 1e-8,
        "scf_nmax": 200,
        "nbands": 88,
        "mixing_beta": 0.3,
        "nspin": 1,
        "occupations": "fixed",
        "symmetry": -1,
        "device": "gpu",
        "ks_solver": "cg",
    }
    actual = {
        "engine": method["engine"],
        "engine_version": method["engine_version"],
        "basis_type": method["basis_type"],
        "net_charge": method["net_charge"],
        "stage": method["stage"],
        "ecutwfc_Ry": method["parameters"]["ecutwfc_Ry"],
        "scf_thr": method["parameters"]["scf_thr"],
        "scf_nmax": method["parameters"]["scf_nmax"],
        "nbands": method["parameters"]["nbands"],
        "mixing_beta": method["parameters"]["mixing_beta"],
        "nspin": method["science"]["nspin"],
        "occupations": method["science"]["occupations"],
        "symmetry": method["science"]["symmetry"],
        "device": method["execution"]["device"],
        "ks_solver": method["execution"]["ks_solver"],
    }
    if actual != expected:
        raise ValueError(f"source method controls differ from the declared refinement protocol: {actual!r}")
    if original["kpoints"] != [3, 3, 3]:
        raise ValueError(f"source method is not the completed 120 Ry / 3x3x3 point: {original['kpoints']!r}")
    return method


def _request() -> dict[str, Any]:
    request = deepcopy(_read_json(SOURCE_REQUEST))
    if request.get("task_id") != SOURCE_TASK_ID:
        raise ValueError(f"source request is bound to {request.get('task_id')!r}, not {SOURCE_TASK_ID!r}")
    resources = dict(request["resource_request"])
    expected = {
        "nodes": 1,
        "partition": "gpu",
        "ntasks": 1,
        "cpus_per_task": 1,
        "mem_mib": 8192,
        "time": 0,
        "gpus_per_task": "v100:1",
    }
    for key, value in expected.items():
        if resources.get(key) != value:
            raise ValueError(f"source task resource {key} must remain {value!r}, got {resources.get(key)!r}")
    request["task_id"] = TASK_ID
    resources["job_name"] = TASK_ID
    request["resource_request"] = resources
    return request


def main() -> int:
    scheduler_job_id = os.environ["SLURM_JOB_ID"]
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "tasks").mkdir(parents=True, exist_ok=True)

    site = _read_json(SOURCE_SITE)
    method = _method_config()
    method_path = CONFIG_DIR / f"method-{TASK_ID}.json"
    _write_json(method_path, method)
    snapshot_path = REPORT_DIR / HEADER_SNAPSHOT_NAME
    _native_header_snapshot(method_path, site, snapshot_path, scheduler_job_id)

    request = _request()
    request_path = CONFIG_DIR / f"request-{TASK_ID}.json"
    _write_json(request_path, request)

    # The existing task creator rereads the already-derived model and study;
    # no model derivation or numerical work is performed here.
    create_abacus_task(
        study_path=SOURCE_STUDY,
        model_path=MODEL_PATH,
        method_path=method_path,
        site_path=SOURCE_SITE,
        request_path=request_path,
    )
    task_path = Path(site["workspace"]["local"]) / "tasks" / TASK_ID / "task.json"
    task = load_task(task_path)
    runner = SiteRunner(SiteConfig.from_file(SOURCE_SITE))
    runner.prepare(task)
    task = load_task(task_path)
    qualification = _read_json(task_path.parent / "method-input-qualification.json")
    electron_count = qualification["electron_count"]
    if (
        float(electron_count["neutral_valence_electrons"]) != 154.0
        or float(electron_count["target_electrons"]) != 152.0
    ):
        raise ValueError(
            "charged refinement must retain CZO vacancy electron counts "
            f"Nneutral=154/Ntarget=152, got {electron_count!r}"
        )

    manifest = {
        "schema": "mlcc.charged-scf-native-refinement-preparation.v002",
        "created_at": utc_now(),
        "scheduler_preparation_job_id": scheduler_job_id,
        "status": "task_prepared_not_submitted",
        "scientific_scope": "single_4x4x4_refinement_point_for_120Ry_charged_fixed_cell_SCF",
        "production_qualification": False,
        "source_task_id": SOURCE_TASK_ID,
        "task_id": TASK_ID,
        "source_method_path": str(SOURCE_METHOD),
        "method_path": str(method_path),
        "source_study_path": str(SOURCE_STUDY),
        "source_site_path": str(SOURCE_SITE),
        "model_path": str(MODEL_PATH),
        "header_snapshot": str(snapshot_path),
        "method_set": METHOD_SET,
        "suffix": METHOD_SUFFIX,
        "kpoints": [4, 4, 4],
        "inherited_controls": {
            "ecutwfc_Ry": 120,
            "scf_thr": 1e-8,
            "scf_nmax": 200,
            "nbands": 88,
            "nspin": 1,
            "occupations": "fixed",
            "symmetry": -1,
            "net_charge": 2,
            "device": "gpu",
            "ks_solver": "cg",
            "mixing_beta": 0.3,
            "resource_request": task.data["resource_request"],
        },
        "comparison_target": {
            "same_ecut_task": SOURCE_TASK_ID,
            "energy_and_force_refinement_only": True,
            "energy_difference_tolerance_eV_per_atom": 0.001,
            "max_atomic_force_vector_difference_eV_per_A": 0.02,
            "automatic_parameter_change": False,
        },
        "task_path": str(task_path),
        "task_status": task.data["status"],
        "scheduler_job_id": task.data["scheduler_job_id"],
        "method_input_qualified": task.data["method_input_qualified"],
        "electron_count": electron_count,
        "scientific_qualification": False,
    }
    _write_json(REPORT_DIR / "native-refinement-preparation.json", manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
