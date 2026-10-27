from __future__ import annotations

import copy
import json
import os
import shutil
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from mlcc.cli import main
from mlcc.tasks import TaskRecord, load_task, save_task
from mlcc.workflow import inspect_task, require_result_dependencies, source_evidence, task_chain_snapshot


ROOT = Path(__file__).resolve().parents[2]
REAL_LAMMPS_TASK = ROOT / "workspace" / "tasks" / "p9-ni-lammps-run0-v001"
REAL_LAMMPS_AVAILABLE = all(
    (REAL_LAMMPS_TASK / name).is_file()
    for name in ("task.json", "result.json", "log.lammps", "dump.final")
)
REAL_BERRY_TASK = Path(os.environ.get("MLCC_BERRY_NATIVE_TASK", str(ROOT / "workspace" / "tasks" / "p5-czo-berry-gdir1-v001")))


def _real_berry_available() -> bool:
    task_path = REAL_BERRY_TASK / "task.json"
    result_path = REAL_BERRY_TASK / "result.json"
    if not task_path.is_file() or not result_path.is_file():
        return False
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    source_files = result.get("source_files")
    if not isinstance(source_files, dict):
        return False
    if any(
        not isinstance(source_files.get(name), str)
        for name in ("running_nscf.log", "INPUT", "KPT", "STRU")
    ):
        return False
    return all(
        name in source_files
        and (
            Path(source_files[name])
            if Path(source_files[name]).is_absolute()
            else result_path.parent / source_files[name]
        ).is_file()
        for name in ("running_nscf.log", "INPUT", "KPT", "STRU")
    )


REAL_BERRY_AVAILABLE = _real_berry_available()


def write_task(root: Path, task_id: str, **values) -> TaskRecord:
    task_dir = root / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "task_id": task_id,
        "status": "defined",
        "scientific_status": "not_calculated",
        "model_id": "fixture-model",
        "model_version": "v001",
        "method_set": "fixture-method-v001",
        **values,
    }
    task = TaskRecord(data, task_dir / "task.json")
    save_task(task)
    return task


def write_result(task: TaskRecord, scientific_status: str, source_name: str = "OUTCAR") -> Path:
    source = task.path.parent / source_name
    source.write_text("native output\n", encoding="utf-8")
    result_path = task.path.parent / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "scientific_status": scientific_status,
                "source_artifact": str(source),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    task.set(result_file=str(result_path))
    save_task(task)
    return result_path


def completed_task(root: Path, task_id: str, scientific_status: str = "converged") -> TaskRecord:
    task = write_task(
        root,
        task_id,
        status="COMPLETED",
        scheduler_job_id="101",
        scheduler_state="COMPLETED",
        exit_code="0:0",
        collect_status="collected",
    )
    write_result(task, scientific_status)
    task.set(scientific_status=scientific_status)
    save_task(task)
    return task


def test_charged_scf_cannot_be_promoted_by_a_converged_label(tmp_path):
    # State-machine fixture only: no charged native result is fabricated.
    parent = completed_task(tmp_path, "charged-label-only")
    parent.set(engine="abacus", net_charge=2)
    save_task(parent)
    assert inspect_task(parent)["action"] == "review_original_error"
    child = write_task(tmp_path, "charged-consumer", required_results=[{
        "task_id": parent.task_id,
        "result_file": "result.json",
        "scientific_status": "converged",
    }])
    with pytest.raises(ValueError, match="raw charged SCF"):
        require_result_dependencies(child, tmp_path)


def berry_nscf_task(root: Path, task_id: str, *, collect_status: str | None = None) -> TaskRecord:
    values = {
        "status": "COMPLETED",
        "stage": "P5",
        "calculation": "nscf",
        "engine": "abacus",
        "scheduler_job_id": "501",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "model_id": "czo-model",
        "model_version": "v001",
        "method_set": "czo-berry-v001",
        "berry": {
            "role": "nscf",
            "gdir": 1,
            "source_reference_task_id": "p5-czo-berry-reference-v001",
        },
    }
    if collect_status is not None:
        values["collect_status"] = collect_status
    return write_task(root, task_id, **values)


def _copy_real_lammps_task(tmp_path: Path) -> TaskRecord:
    copied = tmp_path / REAL_LAMMPS_TASK.name
    shutil.copytree(REAL_LAMMPS_TASK, copied)
    task_path = copied / "task.json"
    result_path = copied / "result.json"
    task_data = json.loads(task_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    task_data["result_file"] = str(result_path)
    result["source_files"] = {
        key: str(copied / Path(value).name)
        for key, value in result["source_files"].items()
    }
    task_path.write_text(json.dumps(task_data, indent=2) + "\n", encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return load_task(task_path)


def test_unknown_submission_never_recommends_resubmit(tmp_path: Path):
    task = write_task(
        tmp_path,
        "unknown-001",
        status="SUBMITTED_UNKNOWN",
        submitted_unknown=True,
        submission_attempt_started_at="2026-10-21T00:00:00+00:00",
        submission_state="unknown",
    )

    plan = inspect_task(task)

    assert plan["action"] == "resolve_submission_unknown"
    assert plan["action"] != "submit"


def test_failed_scientific_result_is_not_completed_despite_native_exit_zero(tmp_path: Path):
    task = completed_task(tmp_path, "failed-science-001", scientific_status="not_converged")

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"
    assert "scientific_status" in plan["reason"]


def test_invalid_converged_prefix_is_not_scientific_completion(tmp_path: Path):
    task = completed_task(tmp_path, "invalid-prefix-001", scientific_status="converged_but_invalid")

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"


def test_abacus_berry_result_without_native_evidence_is_reviewed(tmp_path: Path):
    task = berry_nscf_task(tmp_path, "berry-incomplete-001")
    result_path = task.path.parent / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "schema": "mlcc.abacus-polarization.v1",
                "engine": "abacus",
                "stage": "nscf",
                "task_id": task.task_id,
                "scheduler_job_id": task.scheduler_job_id,
                "model_id": task.data["model_id"],
                "model_version": task.data["model_version"],
                "method_set": task.data["method_set"],
                "gdir": 1,
                "reference_task_id": "p5-czo-berry-reference-v001",
                "branch_status": "not_unwrapped",
                "scientific_status": "evaluated_polarization_unqualified",
                "scientific_qualification": False,
                "numerical_qualification": False,
                "production_qualification": False,
                "production_label": False,
                "source_files": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    task.set(result_file=str(result_path))
    save_task(task)

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"
    assert plan["scientific_status"] == "evaluated_polarization_unqualified"
    assert "native" in plan["reason"]


def test_abacus_ordinary_nscf_source_is_not_berry_native_evidence(tmp_path: Path):
    result_path = tmp_path / "result.json"
    source_files = {}
    for name in ("running_nscf.log", "INPUT", "KPT", "STRU"):
        source = tmp_path / name
        source.write_text("", encoding="utf-8")
        source_files[name] = str(source)
    result = {
        "schema": "mlcc.abacus-nscf.v1",
        "engine": "abacus",
        "stage": "nscf",
        "scientific_status": "converged",
        "source_files": source_files,
    }
    result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")

    _, invalid, reason = source_evidence(result, result_path, engine="abacus")

    assert reason == "unsupported_abacus_nscf_source"
    assert invalid


def test_abacus_berry_completed_without_result_collects_or_parses(tmp_path: Path):
    collect_task = berry_nscf_task(tmp_path, "berry-collect-001")
    plan = inspect_task(collect_task)
    assert plan["action"] == "collect"

    parse_task = berry_nscf_task(tmp_path, "berry-parse-001", collect_status="collected")
    plan = inspect_task(parse_task)
    assert plan["action"] == "parse"


def test_berry_polarization_cannot_satisfy_scientific_dependency(tmp_path: Path):
    child = write_task(
        tmp_path,
        "berry-dependent-child",
        required_results=[
            {
                "task_id": "p5-czo-berry-gdir1-v001",
                "result_file": "result.json",
                "scientific_status": "evaluated_polarization_unqualified",
            }
        ],
    )

    with pytest.raises(ValueError, match="accepted converged dependency"):
        require_result_dependencies(child, tmp_path)


def test_mismatched_result_task_id_is_not_scientific_completion(tmp_path: Path):
    task = completed_task(tmp_path, "mismatched-result-001")
    result_path = task.path.parent / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["task_id"] = "other-task"
    result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"


def test_missing_one_of_multiple_source_artifacts_is_not_completion(tmp_path: Path):
    task = completed_task(tmp_path, "partial-source-001")
    existing = task.path.parent / "OUTCAR"
    missing = task.path.parent / "missing.log"
    result_path = task.path.parent / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "scientific_status": "converged",
                "source_files": {"output": str(existing), "log": str(missing)},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"


def test_parsed_result_json_cannot_be_a_completion_source(tmp_path: Path):
    task = completed_task(tmp_path, "parsed-source-001")
    other_result = task.path.parent / "parsed.json"
    other_result.write_text(
        json.dumps({"task_id": "other-task", "scientific_status": "converged"}) + "\n",
        encoding="utf-8",
    )
    result_path = task.path.parent / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "scientific_status": "converged",
                "source_files": {"parsed": str(other_result)},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"


def test_missing_result_dependency_keeps_native_and_scientific_evidence_separate(tmp_path: Path):
    parent = write_task(
        tmp_path,
        "parent-001",
        status="COMPLETED",
        scheduler_job_id="102",
        scheduler_state="COMPLETED",
        exit_code="0:0",
    )
    child = write_task(
        tmp_path,
        "child-001",
        required_results=[
            {
                "task_id": parent.task_id,
                "result_file": "result.json",
                "scientific_status": "converged",
            }
        ],
    )

    with pytest.raises(ValueError, match="does not exist"):
        require_result_dependencies(child, tmp_path)


def test_dependency_provenance_requires_matching_task_and_all_sources(tmp_path: Path):
    parent = completed_task(tmp_path, "parent-002")
    child = write_task(
        tmp_path,
        "child-002",
        required_results=[
            {
                "task_id": parent.task_id,
                "result_file": "result.json",
                "scientific_status": "converged",
            }
        ],
    )

    provenance = require_result_dependencies(child, tmp_path)

    assert provenance[0]["task_id"] == parent.task_id
    assert provenance[0]["source_files"] == [str(parent.path.parent / "OUTCAR")]

    result_path = parent.path.parent / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["task_id"] = "other-task"
    result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="belongs to task"):
        require_result_dependencies(child, tmp_path)


def test_completed_chain_snapshot_links_real_files_and_action(tmp_path: Path):
    task = completed_task(tmp_path, "complete-001")
    model_path = tmp_path / "models" / "fixture-model" / "v001"
    model_path.mkdir(parents=True)
    (task.path.parent / "method.json").write_text("{}\n", encoding="utf-8")

    snapshot = task_chain_snapshot([task.path])

    assert snapshot[0]["suggested_action"] == "completed"
    assert snapshot[0]["job_id"] == "101"
    assert snapshot[0]["result_exists"] is True
    assert snapshot[0]["model_id"] == "fixture-model"
    assert snapshot[0]["model_version"] == "v001"
    assert snapshot[0]["method_set"] == "fixture-method-v001"
    assert snapshot[0]["model_exists"] is True
    assert snapshot[0]["method_exists"] is True
    assert Path(snapshot[0]["model_path"]) == model_path
    assert Path(snapshot[0]["method_path"]).is_file()


def test_resume_plan_cli_is_read_only_and_accepts_site_argument(tmp_path: Path):
    task = write_task(tmp_path, "defined-001")
    before = task.path.read_text(encoding="utf-8")
    output = StringIO()

    with redirect_stdout(output):
        assert main(["resume-plan", "--task", str(task.path), "--site", str(tmp_path / "site.json")]) == 0

    plan = json.loads(output.getvalue())
    assert plan["action"] == "prepare"
    assert task.path.read_text(encoding="utf-8") == before


@pytest.mark.skipif(
    not REAL_BERRY_AVAILABLE,
    reason="future real P5 Berry NSCF task artifacts are not available",
)
def test_inspect_real_berry_nscf_remains_unqualified():
    task = load_task(REAL_BERRY_TASK / "task.json")

    plan = inspect_task(task)

    assert plan["action"] == "completed"
    assert plan["scientific_status"] == "evaluated_polarization_unqualified"
    assert plan["branch_status"] == "not_unwrapped"
    assert plan["scientific_qualification"] is False
    assert plan["numerical_qualification"] is False
    assert plan["production_qualification"] is False
    assert plan["production_label"] is False
    assert "engineering polarization" in plan["reason"]


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 real LAMMPS task artifacts are not available",
)
def test_inspect_real_lammps_run0_is_engineering_evaluation(tmp_path: Path):
    task = load_task(REAL_LAMMPS_TASK / "task.json")

    plan = inspect_task(task)

    assert plan["action"] == "completed"
    assert plan["scientific_status"] == "evaluated_engineering_fixture"
    assert plan["scientific_qualification"] is False
    assert "engineering evaluation" in plan["reason"]
    assert {Path(value).name for value in plan["source_artifacts"]} >= {"log.lammps", "dump.final"}


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 real LAMMPS task artifacts are not available",
)
def test_lammps_source_evidence_requires_both_native_outputs(tmp_path: Path):
    task = load_task(REAL_LAMMPS_TASK / "task.json")
    result_path = Path(task.data["result_file"])
    result = json.loads(result_path.read_text(encoding="utf-8"))

    paths, invalid, reason = source_evidence(result, result_path, engine="lammps")

    assert reason == "complete"
    assert invalid == []
    assert {path.name for path in paths} >= {"log.lammps", "dump.final"}

    missing = copy.deepcopy(result)
    del missing["source_files"]["dump.final"]
    _, invalid, reason = source_evidence(missing, result_path, engine="lammps")
    assert reason == "missing_lammps_native_outputs"
    assert any(path.name == "dump.final" for path in invalid)


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 real LAMMPS task artifacts are not available",
)
def test_inspect_lammps_refuses_tampered_copy_without_dump_or_identity(tmp_path: Path):
    copied = _copy_real_lammps_task(tmp_path)
    (copied.path.parent / "dump.final").unlink()

    plan = inspect_task(copied)

    assert plan["action"] == "review_original_error"
    assert plan["scientific_status"] == "evaluated_engineering_fixture"

    copied_identity = _copy_real_lammps_task(tmp_path / "identity")
    result_path = copied_identity.path.parent / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["task_id"] = "other-task"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    plan = inspect_task(load_task(copied_identity.path))

    assert plan["action"] == "review_original_error"


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 real LAMMPS task artifacts are not available",
)
def test_inspect_lammps_md_without_trajectory_is_blocked(monkeypatch, tmp_path: Path):
    copied = _copy_real_lammps_task(tmp_path)
    task = copied
    task.data["calculation"] = "md"
    task.data["protocol"] = {**task.data["protocol"], "kind": "md"}
    result_path = task.path.parent / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["protocol"] = {**result["protocol"], "kind": "md"}
    result["scientific_status"] = "executed_engineering_fixture"

    monkeypatch.setattr("mlcc.workflow._read_result", lambda _task: (result_path, result))

    _, invalid, reason = source_evidence(result, result_path, engine="lammps")
    assert reason == "missing_lammps_native_outputs"
    assert any(path.name == "trajectory.lammpstrj" for path in invalid)

    wrong_name = copy.deepcopy(result)
    wrong_path = tmp_path / "trajectory.other"
    wrong_path.write_text("not a native MD trajectory\n", encoding="utf-8")
    wrong_name["source_files"]["trajectory.lammpstrj"] = str(wrong_path)
    _, invalid, reason = source_evidence(wrong_name, result_path, engine="lammps")
    assert reason == "lammps_native_source_name_mismatch"
    assert any(path.name == "trajectory.other" for path in invalid)

    plan = inspect_task(task)

    assert plan["action"] == "review_original_error"
    assert plan["scientific_status"] == "executed_engineering_fixture"
    assert "trajectory.lammpstrj" in plan["reason"]


@pytest.mark.skipif(
    not REAL_LAMMPS_AVAILABLE,
    reason="job41 real LAMMPS task artifacts are not available",
)
def test_engineering_lammps_result_is_not_a_scientific_dependency():
    parent = load_task(REAL_LAMMPS_TASK / "task.json")
    child = TaskRecord(
        {
            "task_id": "engineering-dependent-child",
            "required_results": [
                {
                    "task_id": parent.task_id,
                    "result_file": "result.json",
                    "scientific_status": "evaluated_engineering_fixture",
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="accepted converged dependency"):
        require_result_dependencies(child, ROOT / "workspace")


def test_candidate_potential_status_is_not_a_scientific_dependency(tmp_path):
    child = write_task(tmp_path, "candidate-dependent-child", required_results=[{
        "task_id": "candidate-static", "result_file": "result.json",
        "scientific_status": "evaluated_candidate_potential",
    }])
    with pytest.raises(ValueError, match="accepted converged dependency"):
        require_result_dependencies(child, tmp_path)


@pytest.mark.skipif(not REAL_LAMMPS_AVAILABLE, reason="job41 real LAMMPS evidence is required")
def test_candidate_potential_cannot_relabel_legacy_scalar_evidence(tmp_path):
    task = _copy_real_lammps_task(tmp_path)
    result_path = Path(task.data["result_file"])
    result = json.loads(result_path.read_text(encoding="utf-8"))
    protocol = dict(task.data["protocol"], purpose="potential_qualification", static_tensor=True,
                    experiment_scope="Negative contract test: legacy scalar is insufficient")
    task.set(protocol=protocol, production_qualification=False)
    result.update(protocol=protocol, scientific_status="evaluated_candidate_potential")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    save_task(task)
    plan = inspect_task(task)
    assert plan["action"] == "review_original_error"
    assert plan["scientific_status"] == "evaluated_candidate_potential"
