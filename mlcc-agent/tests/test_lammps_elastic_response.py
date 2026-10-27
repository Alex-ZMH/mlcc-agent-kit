import json
from pathlib import Path

import numpy as np
import pytest

from mlcc.lammps_elastic_response import build_lammps_elastic_response


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _matrix_from_voigt(values: np.ndarray) -> list[list[float]]:
    matrix = np.zeros((3, 3), dtype=float)
    for value, (i, j) in zip(values, ((0, 0), (1, 1), (2, 2), (1, 2), (0, 2), (0, 1))):
        matrix[i, j] = value
        matrix[j, i] = value
    return matrix.tolist()


def _case(tmp_path: Path, *, missing_result: bool = False) -> tuple[Path, np.ndarray]:
    study_path = _write(
        tmp_path / "study.json",
        {
            "study_id": "root-study",
            "case_id": "root-case",
            "case_role": "scientific_validation",
            "model": {"model_id": "root-model", "version": "v001"},
        },
    )
    model_path = tmp_path / "model"
    _write(model_path / "model.json", {"model_id": "root-model", "version": "v001"})
    reference_stress = np.asarray([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=float)
    cij = np.asarray(
        [
            [-10.0, 1.0, 0.0, 0.0, 0.0, 2.0],
            [3.0, -20.0, 4.0, 0.0, 0.0, 0.0],
            [0.0, 5.0, -30.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 40.0, 2.0, -1.0],
            [1.0, 0.0, 3.0, 2.0, -50.0, 6.0],
            [-2.0, 1.0, 0.0, 7.0, 4.0, 60.0],
        ]
    )

    def result(
        task_id: str,
        stress: np.ndarray,
        result_path: Path,
        *,
        child_model_id: str,
        child_study_id: str,
    ) -> str:
        _write(
            result_path,
            {
                "schema": "mlcc.lammps-result.v1",
                "model_id": child_model_id,
                "version": "v001",
                "study_id": child_study_id,
                "case_id": "root-case",
                "task_id": task_id,
                "scheduler_job_id": task_id.replace("task", "job"),
                "scheduler_state": "COMPLETED",
                "exit_code": "0:0",
                "scientific_status": "engineering_fixture",
                "production_qualification": False,
                "stress_GPa": _matrix_from_voigt(stress),
                "stress_unit": "GPa",
                "stress_sign": "tension_positive",
                "tensor_basis": "source_cartesian",
                "atom_ids": [0, 1],
                "parent_model": {
                    "model_id": child_model_id,
                    "version": "v001",
                    "parent_models": [{"model_id": "root-model", "version": "v001"}],
                },
                "source_files": {"atom-map.json": str(result_path.parent / "atom-map.json")},
            },
        )
        return str(result_path)

    reference_path = tmp_path / "results" / "reference.json"
    result(
        "task-reference",
        reference_stress,
        reference_path,
        child_model_id="child-model-reference",
        child_study_id="child-study-reference",
    )
    samples = []
    for direction in range(6):
        for sign in (-1, 1):
            strain = np.zeros(6, dtype=float)
            strain[direction] = sign * 0.001
            path = tmp_path / "results" / f"sample-{direction}-{sign:+d}.json"
            result_stress = reference_stress + cij @ strain
            result_path = path
            if missing_result and direction == 5 and sign == 1:
                result_path = tmp_path / "results" / "missing.json"
            else:
                result(
                    "task-sample-%d-%+d" % (direction, sign),
                    result_stress,
                    path,
                    child_model_id=f"child-model-{direction}-{sign:+d}",
                    child_study_id=f"child-study-{direction}-{sign:+d}",
                )
            samples.append(
                {
                    "task_path": str(tmp_path / "tasks" / f"sample-{direction}-{sign:+d}"),
                    "result_path": str(result_path),
                    "strain_voigt": strain.tolist(),
                }
            )
    request_path = _write(
        tmp_path / "request.json",
        {
            "schema": "mlcc.lammps-elastic-response-request.v1",
            "study_path": str(study_path),
            "model_path": str(model_path),
            "reference": {
                "task_path": str(tmp_path / "tasks" / "reference"),
                "result_path": str(reference_path),
                "strain_voigt": [0.0] * 6,
            },
            "samples": samples,
        },
    )
    return request_path, cij


def test_saved_lammps_stress_uses_voigt_order_reference_subtraction_and_raw_cij(tmp_path: Path) -> None:
    request_path, expected_cij = _case(tmp_path)

    product = build_lammps_elastic_response(request_path)
    stiffness = np.asarray(product["properties"][0]["value"], dtype=float)

    np.testing.assert_allclose(stiffness, expected_cij, rtol=0.0, atol=1.0e-12)
    assert stiffness[0, 1] != stiffness[1, 0]
    assert stiffness[0, 0] < 0.0
    assert product["properties"][0]["conditions"]["stress_sign"] == "tension_positive"
    assert product["properties"][0]["conditions"]["voigt_order"] == [
        "xx", "yy", "zz", "yz", "xz", "xy"
    ]
    assert product["properties"][1]["value"][0][0] == pytest.approx(0.1)
    assert product["model"] == {
        "model_id": "root-model",
        "version": "v001",
        "path": str((tmp_path / "model").resolve()),
    }


def test_saved_result_requires_lammps_tension_positive_gpa_source_tensor(tmp_path: Path) -> None:
    request_path, _ = _case(tmp_path)
    reference_path = tmp_path / "results" / "reference.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["stress_sign"] = "abacus_printed"
    reference_path.write_text(json.dumps(reference) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stress_sign must be tension_positive"):
        build_lammps_elastic_response(request_path)


def test_missing_saved_result_preserves_file_error(tmp_path: Path) -> None:
    request_path, _ = _case(tmp_path, missing_result=True)

    with pytest.raises(FileNotFoundError) as error:
        build_lammps_elastic_response(request_path)
    assert "missing.json" in str(error.value)
