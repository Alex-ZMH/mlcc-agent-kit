from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

import mlcc.berry_response_results as response_module
from mlcc.modeling import write_model_artifacts


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _method() -> dict:
    return {
        "method_set": "berry-response-method-v001",
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "basis_type": "pw",
        "dft_functional": "PBE",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "element_order": ["Ca", "Zr", "O"],
        "parameters": {"ecutwfc_Ry": 80.0, "scf_thr": 1.0e-8},
        "initial_moments_muB_by_element": {"Ca": 0.0, "Zr": 0.0, "O": 0.0},
        "pseudopotential_ids": {"Ca": "ca-v1", "Zr": "zr-v1", "O": "o-v1"},
        "pseudopotential_metadata": {"Ca": {"functional": "PBE"}},
        "pseudopotential_treatment": "norm_conserving",
        "net_charge": 0,
        "kpoints": [2, 2, 2],
    }


def _base_atoms() -> Atoms:
    # Row vectors are intentionally non-orthogonal so the gdir-to-Cartesian
    # reprojection is exercised by the tests.
    atoms = Atoms(
        symbols=["Ca", "Zr", "O"],
        scaled_positions=[[0.0, 0.0, 0.0], [0.27, 0.31, 0.19], [0.63, 0.16, 0.52]],
        cell=[[3.6, 0.0, 0.0], [0.4, 3.1, 0.0], [0.2, 0.3, 4.2]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([10, 20, 30], dtype=int))
    return atoms


def _patch_child_metadata(child_path: Path, *, parent: dict, study_id: str) -> None:
    metadata_path = child_path / "model.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "parent_study_id": "parent-study",
            "study_binding": study_id,
            "parent_models": [
                {
                    "model_id": parent["model_id"],
                    "version": parent["version"],
                    "path": str(parent["path"].resolve()),
                }
            ],
            "derivation": {"parent_study_id": "parent-study"},
        }
    )
    _write_json(metadata_path, metadata)


def _make_case(
    tmp_path: Path,
    *,
    gdirs: tuple[int, ...] = (1,),
    target_axis: int = 0,
    actual_axis_overrides: dict[str, int] | None = None,
    missing_branch: set[str] | None = None,
) -> tuple[Path, dict[str, object]]:
    delta = 0.01
    parent_path = tmp_path / "models" / "parent"
    parent_atoms = _base_atoms()
    parent_model = write_model_artifacts(
        parent_atoms,
        parent_path,
        model_id="czo-public-parent",
        version="v001",
        fixture=True,
        fixture_purpose="berry-response-algorithm-test",
        material="CaZrO3",
        phase_requested="test-parent-phase",
    )
    parent_study_path = tmp_path / "studies" / "parent-study.json"
    _write_json(
        parent_study_path,
        {
            "study_id": "parent-study",
            "model": {
                "model_id": parent_model.model_id,
                "version": parent_model.version,
            },
        },
    )
    parent_ref = {
        "model_id": parent_model.model_id,
        "version": parent_model.version,
        "path": parent_path,
    }
    native_by_task: dict[str, dict] = {}
    manifest_points: list[dict] = []
    method = _method()
    actual_axis_overrides = actual_axis_overrides or {}
    missing_branch = missing_branch or set()
    slopes = {1: 1.5, 2: 2.0, 3: -0.5}
    lattice = np.asarray(parent_atoms.cell.array, dtype=float)

    for sign, label in ((-1, "minus"), (1, "plus")):
        point_id = label
        child_study_id = f"{point_id}-study"
        child_study_path = tmp_path / "studies" / f"{child_study_id}.json"
        child_model_path = tmp_path / "models" / point_id
        child_atoms = parent_atoms.copy()
        actual_axis = actual_axis_overrides.get(point_id, target_axis)
        child_atoms.positions[0, actual_axis] += sign * delta
        child_model = write_model_artifacts(
            child_atoms,
            child_model_path,
            model_id=f"czo-{point_id}",
            version="v001",
            fixture=True,
            fixture_purpose="berry-response-algorithm-test-child",
            material="CaZrO3",
            phase_requested="test-parent-phase",
        )
        _patch_child_metadata(child_model_path, parent=parent_ref, study_id=child_study_id)
        _write_json(
            child_study_path,
            {
                "study_id": child_study_id,
                "parent_study_id": "parent-study",
                "derived_from": {
                    "study_id": "parent-study",
                    "model_id": parent_model.model_id,
                    "model_version": parent_model.version,
                },
                "model": {"model_id": child_model.model_id, "version": child_model.version},
            },
        )
        scf_task_path = tmp_path / "tasks" / point_id / "scf" / "task.json"
        _write_json(
            scf_task_path,
            {
                "task_id": f"scf-{point_id}",
                "scheduler_job_id": f"scf-job-{point_id}",
                "scheduler_state": "COMPLETED",
                "exit_code": "0:0",
            },
        )
        nscf_records: list[dict] = []
        for gdir in gdirs:
            task_dir = tmp_path / "tasks" / point_id / f"gdir-{gdir}"
            task_path = task_dir / "task.json"
            result_path = task_dir / "result.json"
            task_id = f"native-{point_id}-g{gdir}"
            job_id = f"job-{point_id}-g{gdir}"
            _write_json(
                task_path,
                {
                    "task_id": task_id,
                    "engine": "abacus",
                    "engine_version": "3.10.1",
                    "stage": "P5",
                    "calculation": "nscf",
                    "runner": "slurm",
                    "scheduler_job_id": job_id,
                    "scheduler_state": "COMPLETED",
                    "exit_code": "0:0",
                    "fixture": True,
                    "case_id": "berry-response-test-case",
                    "case_role": "engineering_fixture",
                    "study_id": child_study_id,
                    "study_file": str(child_study_path.resolve()),
                    "model_id": child_model.model_id,
                    "model_version": child_model.version,
                    "model_path": str(child_model_path.resolve()),
                    "method_set": method["method_set"],
                    "result_file": str(result_path.resolve()),
                },
            )
            _write_json(task_dir / "method.json", method)
            _write_json(result_path, {"task_id": task_id, "scheduler_job_id": job_id})
            direction = lattice[gdir - 1]
            unit = direction / np.linalg.norm(direction)
            polarization = 4.0 + gdir + sign * slopes[gdir] * delta
            native_by_task[str(task_path.resolve())] = {
                "task_id": task_id,
                "scheduler_job_id": job_id,
                "engine_version": "3.10.1",
                "method_set": method["method_set"],
                "model_id": child_model.model_id,
                "model_version": child_model.version,
                "gdir": gdir,
                "reference_scf_converged": True,
                "reference_scf_task_id": f"scf-{point_id}",
                "reference_scf_validation": {
                    "task_id": f"scf-{point_id}",
                    "task_file": str(scf_task_path.resolve()),
                    "scheduler_job_id": f"scf-job-{point_id}",
                    "scheduler_state": "COMPLETED",
                    "exit_code": "0:0",
                },
                "total_P_C_per_m2": polarization,
                "modulo_quantum_C_per_m2": 10.0,
                "direction_lattice_vector_angstrom": direction.tolist(),
                "direction_unit_vector_cartesian": unit.tolist(),
                "cartesian_reprojection": (polarization * unit).tolist(),
                "pw_diag_thr": 1.0e-8,
                "kpoint_shift": [0.0, 0.0, 0.0],
                "source_files": {"native_task": str(task_path.resolve())},
            }
            nscf_records.append(
                {
                    "task_id": task_id,
                    "task_path": str(task_path.resolve()),
                    "gdir": gdir,
                    "scheduler_job_id": job_id,
                    "scheduler_state": "COMPLETED",
                    "exit_code": "0:0",
                    "status": "defined",
                }
            )
        manifest_points.append(
            {
                "point_id": point_id,
                "parent_study_id": "parent-study",
                "parent_model": {
                    "model_id": parent_model.model_id,
                    "version": parent_model.version,
                    "path": str(parent_path.resolve()),
                },
                "child_study_id": child_study_id,
                "child_model_id": child_model.model_id,
                "child_model_version": child_model.version,
                "scf_task_id": f"scf-{point_id}",
                "scf_task_path": str(scf_task_path.resolve()),
                "displacements": [{"atom_id": 10, "delta_cartesian_A": [sign * delta, 0.0, 0.0]}],
                "path_coordinate": float(sign),
                "gdirs": list(gdirs),
                "model_path": str(child_model_path.resolve()),
                "study_path": str(child_study_path.resolve()),
                "nscf_tasks": nscf_records,
            }
        )

    manifest_path = tmp_path / "response-manifest.json"
    _write_json(
        manifest_path,
        {
            "schema": "mlcc.abacus-berry-displacement-response.v1",
            "response_id": "berry-response-test",
            "parent_study": {"study_id": "parent-study", "study_path": str(parent_study_path.resolve())},
            "parent_model": {
                "model_id": parent_model.model_id,
                "version": parent_model.version,
                "path": str(parent_path.resolve()),
            },
            "points": manifest_points,
        },
    )
    request_path = tmp_path / "response-results-request.json"
    entries = []
    for gdir in gdirs:
        plus_missing = f"g{gdir}p" in missing_branch
        entries.append(
            {
                "gdir": gdir,
                "branch_integer": {"minus": 0, "plus": None if plus_missing else 0},
                "branch_basis": {
                    "minus": "declared-test-branch",
                    "plus": None if plus_missing else "declared-test-branch",
                },
            }
        )
    _write_json(
        request_path,
        {
            "schema": "mlcc.abacus-berry-displacement-response-results-request.v1",
            "response_id": "berry-response-test",
            "response_manifest": str(manifest_path.resolve()),
            "minus_point_id": "minus",
            "plus_point_id": "plus",
            "target": {"atom_id": 10, "cartesian_axis": target_axis},
            "gdirs": entries,
        },
    )

    def fake_read(task_path: str | Path) -> dict:
        return dict(native_by_task[str(Path(task_path).expanduser().resolve())])

    return request_path, {"native": native_by_task, "fake_read": fake_read, "manifest": manifest_path}


def test_one_gdir_returns_signed_derivative_and_nonorthogonal_contribution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    request_path, context = _make_case(tmp_path, gdirs=(1,))
    monkeypatch.setattr(response_module, "read_berry_task", context["fake_read"])

    result = response_module.analyze_berry_displacement_response(request_path)

    direction = result["directions"][0]
    assert result["status"] == "incomplete_cartesian_response"
    assert direction["dP_gdir_du_C_per_m2_per_angstrom"] == pytest.approx(1.5)
    expected_unit = np.asarray([3.6, 0.0, 0.0]) / 3.6
    np.testing.assert_allclose(
        direction["cartesian_contribution_dP_du_C_per_m2_per_angstrom"],
        1.5 * expected_unit,
    )
    assert result["cartesian_response"]["dP_cartesian_du_C_per_m2_per_angstrom"] is None
    assert result["born_charge_column"] is None
    assert result["qualification"]["scientific_qualification"] is False


def test_three_gdirs_sum_reprojected_cartesian_derivative_and_one_born_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request_path, context = _make_case(tmp_path, gdirs=(1, 2, 3))
    monkeypatch.setattr(response_module, "read_berry_task", context["fake_read"])

    result = response_module.analyze_berry_displacement_response(request_path)

    cell = np.asarray(_base_atoms().cell.array, dtype=float)
    slopes = np.asarray([1.5, 2.0, -0.5])
    expected = sum((slope * cell[index] / np.linalg.norm(cell[index]) for index, slope in enumerate(slopes)))
    np.testing.assert_allclose(result["cartesian_response"]["dP_cartesian_du_C_per_m2_per_angstrom"], expected)
    assert result["status"] == "evaluated_cartesian_response_unqualified"
    assert result["qualification"]["complete_cartesian_response"] is True
    assert result["born_charge_column"]["complete"] is True
    volume = abs(float(np.linalg.det(cell)))
    expected_born = expected * volume * 1.0e-20 / 1.602176634e-19
    np.testing.assert_allclose(result["born_charge_column"]["values_e"], expected_born)
    assert result["epsilon_infinity"] is None
    assert result["ionic_dielectric"] is None
    assert result["static_dielectric"] is None
    assert result["qualification"]["production_qualification"] is False


def test_missing_branch_keeps_direction_and_cartesian_dependent_values_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request_path, context = _make_case(tmp_path, gdirs=(1, 2, 3), missing_branch={"g2p"})
    monkeypatch.setattr(response_module, "read_berry_task", context["fake_read"])

    result = response_module.analyze_berry_displacement_response(request_path)

    missing = next(item for item in result["directions"] if item["gdir"] == 2)
    assert missing["branch_resolved"] is False
    assert missing["delta_P_gdir_C_per_m2"] is None
    assert missing["dP_gdir_du_C_per_m2_per_angstrom"] is None
    assert missing["cartesian_contribution_dP_du_C_per_m2_per_angstrom"] is None
    assert result["status"] == "unresolved_missing_branch"
    assert result["cartesian_response"]["dP_cartesian_du_C_per_m2_per_angstrom"] is None
    assert result["born_charge_column"] is None
    assert result["qualification"]["complete_cartesian_response"] is False


def test_wrong_plus_displacement_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    request_path, context = _make_case(tmp_path, gdirs=(1,), actual_axis_overrides={"plus": 1})
    monkeypatch.setattr(response_module, "read_berry_task", context["fake_read"])

    with pytest.raises(ValueError, match="displacement does not equal"):
        response_module.analyze_berry_displacement_response(request_path)


def test_manifest_task_identity_mismatch_is_rejected_before_native_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request_path, context = _make_case(tmp_path, gdirs=(1,))
    manifest_path = context["manifest"]
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest["points"][0]["nscf_tasks"][0]["task_id"] = "unbound-task-id"
    _write_json(Path(manifest_path), manifest)
    called = False

    def fail_if_called(_task_path: str | Path) -> dict:
        nonlocal called
        called = True
        raise AssertionError("native reader must not run for a manifest identity mismatch")

    monkeypatch.setattr(response_module, "read_berry_task", fail_if_called)
    with pytest.raises(ValueError, match="manifest NSCF task identity"):
        response_module.analyze_berry_displacement_response(request_path)
    assert called is False


def test_native_scf_source_path_mismatch_is_rejected_even_with_matching_task_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request_path, context = _make_case(tmp_path, gdirs=(1,))
    native = next(iter(context["native"].values()))
    native["reference_scf_validation"]["task_file"] = str(
        (tmp_path / "wrong-scf-source" / "task.json").resolve()
    )
    monkeypatch.setattr(response_module, "read_berry_task", context["fake_read"])

    with pytest.raises(ValueError, match="native SCF source task path differs"):
        response_module.analyze_berry_displacement_response(request_path)
