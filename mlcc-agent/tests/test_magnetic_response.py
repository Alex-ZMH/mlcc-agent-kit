"""Contract checks for the saved ABACUS magnetic-result consumer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc.magnetic_response import read_abacus_magnetic_task


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _native_log(
    total: float | None,
    *,
    converged: bool = True,
    finished: bool = True,
    stage: str = "scf",
    ionic_converged: bool = True,
) -> str:
    lines = [
        "The readin total magnetization is 2.4",
        "total magnetism (Bohr mag/cell) = 0.6",
    ]
    if total is None:
        lines.pop()
    else:
        lines[-1] = f"total magnetism (Bohr mag/cell) = {total:.12g}"
    lines.append(
        "charge density convergence is achieved"
        if converged
        else "!! convergence has not been achieved @_@"
    )
    if stage == "relax":
        lines.append(
            "Relaxation is converged!"
            if ionic_converged
            else "Relaxation is not converged yet!"
        )
    if finished:
        lines.append("Finish Time  : Wed Oct 21 12:14:50 2026")
    return "\n".join(lines) + "\n"


def write_magnetic_fixture(
    root: Path,
    *,
    total: float | None = 2.4,
    converged: bool = True,
    finished: bool = True,
    nspin: int = 2,
    initial_seed: float | None = 0.6,
    task_id: str = "magnetic-fixture",
    job_id: str = "9001",
    stage: str = "scf",
    ionic_converged: bool = True,
) -> Path:
    """Write the minimum saved-task layout used by reader and delivery tests."""

    task_dir = root / task_id
    native_dir = task_dir / "OUT.NiPW"
    native_dir.mkdir(parents=True)
    task = {
        "task_id": task_id,
        "engine": "abacus",
        "engine_version": "3.10.1",
        "model_id": "ni-fcc-engineering",
        "model_version": "v001",
        "method_set": "ni-method-v001",
        "runner": "slurm",
        "scheduler_job_id": job_id,
        "status": "COMPLETED",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
    }
    method = {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "model_id": "ni-fcc-engineering",
        "version": "v001",
        "method_set": "ni-method-v001",
        "suffix": "NiPW",
        "stage": stage,
        "nspin": nspin,
    }
    if initial_seed is not None:
        method["initial_magnetic_moment_muB_per_atom"] = initial_seed
    result = {
        "task_id": task_id,
        "scheduler_job_id": job_id,
        "method_set": "ni-method-v001",
        "stage": stage,
        "source_files": {
            f"running_{stage}.log": str(native_dir / f"running_{stage}.log"),
            "STRU.atom-map.json": str(task_dir / "STRU.atom-map.json"),
        },
    }
    result["total_magnetization_muB"] = total
    result["native_completed"] = None
    atom_map = {
        "schema": "mlcc.abacus-atom-map.v1",
        "abacus_version_target": "3.10.1",
        "model_id": "ni-fcc-engineering",
        "version": "v001",
        "source_atom_ids": [0, 1, 2, 3],
        "abacus_order": [
            {"abacus_index": index, "source_index": index, "atom_id": index, "element": "Ni"}
            for index in range(4)
        ],
    }
    _write_json(task_dir / "task.json", task)
    _write_json(task_dir / "method.json", method)
    _write_json(task_dir / "result.json", result)
    _write_json(task_dir / "STRU.atom-map.json", atom_map)
    (task_dir / "INPUT").write_text(
        "INPUT_PARAMETERS\n"
        "suffix NiPW\n"
        f"calculation {stage}\n"
        f"nspin {nspin}\n"
        "smearing_method gauss\n",
        encoding="utf-8",
    )
    (native_dir / f"running_{stage}.log").write_text(
        _native_log(
            total,
            converged=converged,
            finished=finished,
            stage=stage,
            ionic_converged=ionic_converged,
        ),
        encoding="utf-8",
    )
    return task_dir


def test_saved_total_is_separate_from_initial_seed_and_average(tmp_path: Path):
    task_dir = write_magnetic_fixture(tmp_path, total=2.41425570809)
    product = read_abacus_magnetic_task(task_dir)
    assert product["schema"] == "mlcc.abacus-magnetic.v001"
    assert product["total_magnetization_muB"] == pytest.approx(2.41425570809)
    assert product["mean_magnetization_muB_per_atom"] == pytest.approx(2.41425570809 / 4)
    assert product["initial_seed"]["initial_magnetic_moment_muB_per_atom"] == pytest.approx(0.6)
    assert product["local_moments_muB"] is None
    assert product["magnetic_order"] == "unassessed"


def test_missing_native_total_is_missing_not_zero(tmp_path: Path):
    task_dir = write_magnetic_fixture(tmp_path, total=None)
    product = read_abacus_magnetic_task(task_dir)
    assert product["status"] == "missing"
    assert product["total_magnetization_muB"] is None
    assert product["mean_magnetization_muB_per_atom"] is None


def test_unconverged_native_total_is_retained(tmp_path: Path):
    task_dir = write_magnetic_fixture(tmp_path, total=1.25, converged=False, finished=False)
    product = read_abacus_magnetic_task(task_dir)
    assert product["status"] == "unconverged"
    assert product["total_magnetization_muB"] == pytest.approx(1.25)
    assert product["mean_magnetization_muB_per_atom"] == pytest.approx(1.25 / 4)
    assert product["native_electronic_converged"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "FAILED"),
        ("scheduler_state", "FAILED"),
        ("exit_code", "1:0"),
    ],
    ids=["status-FAILED", "scheduler_state-FAILED", "exit_code-1:0"],
)
def test_noncompleted_scheduler_state_is_incomplete_task(tmp_path: Path, field: str, value: str):
    task_dir = write_magnetic_fixture(tmp_path, total=2.4)
    task_path = task_dir / "task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task[field] = value
    _write_json(task_path, task)

    product = read_abacus_magnetic_task(task_dir)

    assert product["status"] == "incomplete_task"
    assert product["total_magnetization_muB"] == pytest.approx(2.4)
    assert product["mean_magnetization_muB_per_atom"] == pytest.approx(0.6)
    assert product["scheduler_status"] == task["status"]
    assert product["scheduler_state"] == task["scheduler_state"]
    assert product["exit_code"] == task["exit_code"]


@pytest.mark.parametrize(
    ("ionic_converged", "expected_status"),
    [(False, "unconverged"), (True, "available")],
    ids=["relax-ionic-false", "relax-ionic-true"],
)
def test_relax_status_requires_ionic_convergence(
    tmp_path: Path, ionic_converged: bool, expected_status: str
):
    task_dir = write_magnetic_fixture(
        tmp_path,
        total=2.4,
        stage="relax",
        ionic_converged=ionic_converged,
    )

    product = read_abacus_magnetic_task(task_dir)

    assert product["status"] == expected_status
    assert product["native_electronic_converged"] is True
    assert product["native_ionic_converged"] is ionic_converged
    assert product["native_completed"] is True
    assert product["total_magnetization_muB"] == pytest.approx(2.4)
    assert product["mean_magnetization_muB_per_atom"] == pytest.approx(0.6)


def test_nspin_one_missing_total_stays_missing(tmp_path: Path):
    task_dir = write_magnetic_fixture(tmp_path, total=None, nspin=1, initial_seed=None)
    product = read_abacus_magnetic_task(task_dir)
    assert product["nspin"] == 1
    assert product["total_magnetization_muB"] is None
    assert product["mean_magnetization_muB_per_atom"] is None


def test_identity_mismatch_is_rejected(tmp_path: Path):
    task_dir = write_magnetic_fixture(tmp_path)
    result_path = task_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["method_set"] = "other-method"
    _write_json(result_path, result)
    with pytest.raises(ValueError, match="result.method_set mismatch"):
        read_abacus_magnetic_task(task_dir)


def test_optional_electronic_product_is_bound_without_new_observables(tmp_path: Path):
    task_dir = write_magnetic_fixture(tmp_path)
    electronic_path = tmp_path / "electronic.json"
    _write_json(
        electronic_path,
        {
            "schema": "mlcc.abacus-electronic.v001",
            "task_id": "magnetic-fixture",
            "scheduler_job_id": "9001",
            "method_set": "ni-method-v001",
            "model_id": "ni-fcc-engineering",
            "model_version": "v001",
            "nspin": 2,
            "spin_channels": ["up", "down"],
            "occupations": "smearing",
            "band_energies_eV": [[[1.0]]],
            "weighted_occupations": [[[0.5]]],
            "normalized_occupations": [[[1.0]]],
        },
    )
    product = read_abacus_magnetic_task(task_dir, electronic_path)
    assert product["electronic_path"] == str(electronic_path.resolve())
    assert product["electronic"]["spin_channels"] == ["up", "down"]
    assert product["electronic"]["band_energies_eV"] == [[[1.0]]]


def test_input_nspin_mismatch_is_rejected(tmp_path: Path):
    task_dir = write_magnetic_fixture(tmp_path, nspin=2)
    input_path = task_dir / "INPUT"
    input_path.write_text(
        input_path.read_text(encoding="utf-8").replace("nspin 2", "nspin 1"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="INPUT/method nspin mismatch"):
        read_abacus_magnetic_task(task_dir)


def test_optional_electronic_product_with_wrong_job_is_rejected(tmp_path: Path):
    task_dir = write_magnetic_fixture(tmp_path, job_id="9001")
    electronic_path = tmp_path / "electronic.json"
    _write_json(
        electronic_path,
        {
            "schema": "mlcc.abacus-electronic.v001",
            "task_id": "magnetic-fixture",
            "scheduler_job_id": "different-job",
            "method_set": "ni-method-v001",
            "model_id": "ni-fcc-engineering",
            "model_version": "v001",
            "nspin": 2,
        },
    )
    with pytest.raises(ValueError, match="electronic.scheduler_job_id mismatch"):
        read_abacus_magnetic_task(task_dir, electronic_path)
