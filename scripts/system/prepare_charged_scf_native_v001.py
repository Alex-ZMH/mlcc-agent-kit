"""Prepare the CZO oxygen-vacancy charged-SCF validation inputs.

This script is intended to run in a short CPU Slurm allocation on v100.  It
only derives the explicit unrelaxed model, reads the selected native UPF
headers, writes the method/study/request records, and prepares the existing
SiteRunner scripts.  It never transfers or submits a numerical task.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
from typing import Any

from mlcc.abacus_tasks import create_abacus_task
from mlcc.method_inputs import parse_upf_header
from mlcc.method_tasks import method_pseudopotentials
from mlcc.model_derivatives import derive_defect_model
from mlcc.modeling import read_model_artifacts
from mlcc.site_runner import SiteConfig, SiteRunner
from mlcc.tasks import load_task, utc_now


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
PARENT_MODEL = WORKSPACE / "models" / "cazro3-pnma-pristine" / "v001"
BASE_METHOD = WORKSPACE / "configs" / "cazro3-abacus-capability-v002.json"
BASE_STUDY = WORKSPACE / "configs" / "cases" / "cazro3-firing-v003.json"
SOURCE_SITE = WORKSPACE / "configs" / "site.v100-berry-dev-v001.json"

CONFIG_DIR = WORKSPACE / "configs" / "charged-scf-native-v001"
REPORT_DIR = WORKSPACE / "reports" / "charged-scf-native-v001"
REMOTE_WORKSPACE = Path("/home/v100/projects/mlcc/development/0.10.0/project/workspace")
DEFECT_MODEL = WORKSPACE / "models" / "cazro3-pnma-vo8-q2" / "v001"
STUDY_ID = "czo_vo8_q2_scf_validation_v001"
DEFECT_MODEL_ID = "cazro3-pnma-vo8-q2"
DEFECT_VERSION = "v001"


POINTS = (
    {
        "task_id": "p4-czo-vo8-q2-ecut100-k222-v001",
        "method_set": "cazro3-vo8-q2-pw-ecut100-k222-v001",
        "suffix": "CZOVO8Q2E100K222",
        "ecutwfc_Ry": 100,
        "kpoints": [2, 2, 2],
        "header_snapshot": "czo-vo8-q2-ecut100-k222-upf-headers-v001.json",
    },
    {
        "task_id": "p4-czo-vo8-q2-ecut120-k222-v001",
        "method_set": "cazro3-vo8-q2-pw-ecut120-k222-v001",
        "suffix": "CZOVO8Q2E120K222",
        "ecutwfc_Ry": 120,
        "kpoints": [2, 2, 2],
        "header_snapshot": "czo-vo8-q2-ecut120-k222-upf-headers-v001.json",
    },
    {
        "task_id": "p4-czo-vo8-q2-ecut120-k333-v001",
        "method_set": "cazro3-vo8-q2-pw-ecut120-k333-v001",
        "suffix": "CZOVO8Q2E120K333",
        "ecutwfc_Ry": 120,
        "kpoints": [3, 3, 3],
        "header_snapshot": "czo-vo8-q2-ecut120-k333-upf-headers-v001.json",
    },
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite preparation artifact: {path}")
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
    """Read the selected UPF headers from the files visible in this allocation."""

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


def _derive_site() -> tuple[Path, dict[str, Any]]:
    site = deepcopy(_read_json(SOURCE_SITE))
    site["workspace"] = dict(site["workspace"])
    # SiteRunner.prepare is called in the remote checkout.  Keeping both
    # fields remote prevents the generated task records from retaining a D:
    # path that cannot exist on v100.
    site["workspace"]["local"] = str(REMOTE_WORKSPACE)
    site["workspace"]["remote_root"] = str(REMOTE_WORKSPACE)
    site_path = CONFIG_DIR / "site.v100-charged-native-v001.json"
    _write_json(site_path, site)
    return site_path, site


def _derive_model() -> tuple[Path, dict[str, Any]]:
    parent = read_model_artifacts(PARENT_MODEL)
    if "atom_id" not in parent.atoms.arrays:
        raise ValueError("the selected CZO parent model has no atom_id array")
    atom_ids = [int(value) for value in parent.atoms.arrays["atom_id"]]
    if 8 not in atom_ids:
        raise ValueError("the selected CZO parent model has no atom_id=8")
    atom_index = atom_ids.index(8)
    element = parent.atoms.get_chemical_symbols()[atom_index]
    if element != "O":
        raise ValueError(f"atom_id=8 must be O before vacancy derivation, got {element!r}")

    request = {
        "model_id": DEFECT_MODEL_ID,
        "version": DEFECT_VERSION,
        "study_id": STUDY_ID,
        "charge_state": 2,
        "operations": [{"kind": "vacancy", "atom_id": 8}],
    }
    _write_json(CONFIG_DIR / "derive-defect.json", request)
    derive_defect_model(PARENT_MODEL, request, DEFECT_MODEL)
    child = read_model_artifacts(DEFECT_MODEL)
    symbols = child.atoms.get_chemical_symbols()
    composition = {element: symbols.count(element) for element in dict.fromkeys(symbols)}
    return DEFECT_MODEL, {"request": request, "composition": composition}


def _derive_study(composition: dict[str, int]) -> Path:
    study = deepcopy(_read_json(BASE_STUDY))
    study.update(
        {
            "study_id": STUDY_ID,
            "case_id": STUDY_ID,
            "case_role": "scientific_validation",
            "fixture": False,
            "validation_scope": "static_unrelaxed_finite_cell_charged_scf_only",
            "formation_energy_qualification": False,
            "sparse_defect_qualification": False,
            "selected_purposes": ["charged_scf_native_validation"],
            "selected_scenarios": ["static_unrelaxed_finite_cell"],
            "selected_required_tasks": [point["task_id"] for point in POINTS],
            "status": "explicit_unrelaxed_charged_scf_validation_inputs_pending_native_DFT",
            "production_qualification": False,
            "temperature_protocol": {"kind": "static_dft", "grid_C": [], "grid_K": []},
            "derived_from": {"source_study": str(BASE_STUDY), "reason": "explicit_charged_fixed_geometry_SCF_experiment"},
        }
    )
    model = dict(study["model"])
    model.update(
        {
            "model_id": DEFECT_MODEL_ID,
            "version": DEFECT_VERSION,
            "source_structure": str(DEFECT_MODEL / "model.extxyz"),
            "source_status": "explicit_unrelaxed_oxygen_vacancy_validation_reference",
            "initial_scope": "explicit_vo8_q2_validation",
            "composition": composition,
            "fixture": False,
            "relaxation_status": "not_run",
            "production_qualified": False,
            "temperature_K": [],
            "temperature_selection": "not_applicable_static_scf_validation",
            "temperature_range_C": [],
            "temperature_range_K": [],
            "temperature_role": "not_applicable_static_scf_validation",
        }
    )
    study["model"] = model
    path = CONFIG_DIR / "study.json"
    _write_json(path, study)
    return path


def _method_config(point: dict[str, Any], snapshot_name: str) -> dict[str, Any]:
    method = deepcopy(_read_json(BASE_METHOD))
    method["parent_method_set"] = method["method_set"]
    method["stage"] = "scf"
    method["method_set"] = point["method_set"]
    method["net_charge"] = 2
    method["scope"] = "static_unrelaxed_finite_cell_charged_scf_validation_only"
    method["production_qualification"] = False
    method["numerical_precision_qualified"] = False
    method["science"] = dict(method["science"])
    method["science"].update(
        {
            "suffix": point["suffix"],
            "nspin": 1,
            "occupations": "fixed",
            "smearing_method": None,
            "symmetry": -1,
            "lspinorb": False,
            "noncolin": False,
        }
    )
    method["execution"] = {"device": "gpu", "ks_solver": "cg"}
    method["parameters"] = dict(method["parameters"])
    method["parameters"].update(
        {
            "ecutwfc_Ry": point["ecutwfc_Ry"],
            "scf_thr": 1e-8,
            "scf_nmax": 200,
            "nbands": 88,
            "smearing_sigma_Ry": None,
            "mixing_beta": 0.3,
        }
    )
    method["kpoints"] = list(point["kpoints"])
    method["input_qualification"] = {
        "header_snapshot": f"../../reports/charged-scf-native-v001/{snapshot_name}"
    }
    return method


def _request(point: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": point["task_id"],
        "calculation": "scf",
        "input_transformation": None,
        "required_results": [],
        "resource_request": {
            "nodes": 1,
            "partition": "gpu",
            "ntasks": 1,
            "cpus_per_task": 1,
            "mem_mib": 8192,
            "time": 0,
            "gpus_per_task": "v100:1",
            "hint": "nomultithread",
            "job_name": point["task_id"],
        },
    }


def _integer_electron(value: Any, name: str) -> int:
    number = float(value)
    rounded = int(round(number))
    if not math.isclose(number, rounded, rel_tol=0.0, abs_tol=1e-8):
        raise ValueError(f"{name} must be an integer electron count, got {value!r}")
    return rounded


def _prepare_points(
    site_path: Path,
    study_path: Path,
    site: dict[str, Any],
    scheduler_job_id: str,
) -> list[dict[str, Any]]:
    runner = SiteRunner(SiteConfig.from_file(site_path))
    entries: list[dict[str, Any]] = []
    for point in POINTS:
        snapshot_name = point["header_snapshot"]
        method = _method_config(point, snapshot_name)
        method_path = CONFIG_DIR / f"method-{point['task_id']}.json"
        _write_json(method_path, method)
        snapshot_path = REPORT_DIR / snapshot_name
        _native_header_snapshot(method_path, site, snapshot_path, scheduler_job_id)

        request = _request(point)
        request_path = CONFIG_DIR / f"request-{point['task_id']}.json"
        _write_json(request_path, request)
        create_abacus_task(
            study_path=study_path,
            model_path=DEFECT_MODEL,
            method_path=method_path,
            site_path=site_path,
            request_path=request_path,
        )
        task_path = REMOTE_WORKSPACE / "tasks" / point["task_id"] / "task.json"
        task = load_task(task_path)
        runner.prepare(task)
        task = load_task(task_path)
        qualification_path = task_path.parent / "method-input-qualification.json"
        qualification = _read_json(qualification_path)
        electron_count = qualification["electron_count"]
        neutral = _integer_electron(electron_count["neutral_valence_electrons"], "Nneutral")
        target = _integer_electron(electron_count["target_electrons"], "Ntarget")
        if (neutral, target) != (154, 152):
            raise ValueError(
                f"unexpected CZO vacancy electron count for {point['task_id']}: "
                f"Nneutral={neutral}, Ntarget={target}"
            )
        entries.append(
            {
                "task_id": point["task_id"],
                "task_path": str(task_path),
                "task_directory": str(task_path.parent),
                "method_path": str(method_path),
                "request_path": str(request_path),
                "method_set": method["method_set"],
                "header_snapshot": str(snapshot_path),
                "kpoints": point["kpoints"],
                "ecutwfc_Ry": point["ecutwfc_Ry"],
                "resource_request": task.data["resource_request"],
                "status": task.data["status"],
                "scheduler_job_id": task.data["scheduler_job_id"],
                "input_qualification": {
                    "input_qualified": qualification["input_qualified"],
                    "scientific_qualification": qualification["scientific_qualification"],
                    "production_qualification": qualification["production_qualification"],
                    "electron_count": electron_count,
                },
            }
        )
    return entries


def main() -> int:
    scheduler_job_id = os.environ["SLURM_JOB_ID"]
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REMOTE_WORKSPACE / "tasks").mkdir(parents=True, exist_ok=True)

    site_path, site = _derive_site()
    defect_model_path, defect = _derive_model()
    study_path = _derive_study(defect["composition"])
    entries = _prepare_points(site_path, study_path, site, scheduler_job_id)

    manifest = {
        "schema": "mlcc.charged-scf-native-preparation.v001",
        "created_at": utc_now(),
        "scheduler_preparation_job_id": scheduler_job_id,
        "status": "tasks_prepared_not_submitted",
        "production_qualification": False,
        "scientific_scope": "static_unrelaxed_finite_cell_charged_scf_validation_only",
        "formation_energy_qualification": False,
        "sparse_defect_qualification": False,
        "site_path": str(site_path),
        "study_path": str(study_path),
        "parent_model_path": str(PARENT_MODEL),
        "derived_model_path": str(defect_model_path),
        "defect_request_path": str(CONFIG_DIR / "derive-defect.json"),
        "defect": {
            "model_id": DEFECT_MODEL_ID,
            "version": DEFECT_VERSION,
            "study_id": STUDY_ID,
            "operation": {"kind": "vacancy", "atom_id": 8, "element": "O"},
            "charge_state": 2,
            "fixture": False,
        },
        "electron_count": {
            "Nneutral": 154,
            "Ntarget": 152,
            "net_charge": 2,
            "nelec": 0,
            "nelec_delta": -2,
        },
        "comparison_protocol": {
            "cutoff_pair": [
                "p4-czo-vo8-q2-ecut100-k222-v001",
                "p4-czo-vo8-q2-ecut120-k222-v001",
            ],
            "kmesh_pair": [
                "p4-czo-vo8-q2-ecut120-k222-v001",
                "p4-czo-vo8-q2-ecut120-k333-v001",
            ],
            "energy_difference_tolerance_eV_per_atom": 0.001,
            "max_force_difference_tolerance_eV_per_A": 0.02,
            "automatic_parameter_change": False,
        },
        "tasks": entries,
    }
    _write_json(REPORT_DIR / "native-preparation.json", manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
