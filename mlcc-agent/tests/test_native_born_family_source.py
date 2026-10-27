"""Software-contract checks for native affine Born-family delivery."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mlcc.dielectric_response import read_native_born_family
from test_native_gamma_delivery_source import _native_fixture


CONTRACT_EVIDENCE = "software_contract_only"


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _clone_displacement_task(
    source_root: Path,
    target_root: Path,
    *,
    task_id: str,
    scheduler_job_id: str,
    study_id: str,
) -> dict:
    target_root.mkdir(parents=True, exist_ok=True)
    for name in ("method.json", "KPT", "STRU", "STRU.atom-map.json"):
        source = source_root / name
        target = target_root / name
        if name.endswith(".json"):
            _write(target, json.loads(source.read_text(encoding="utf-8")))
        else:
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    task = json.loads((source_root / "task.json").read_text(encoding="utf-8"))
    task.update(
        {
            "task_id": task_id,
            "scheduler_job_id": scheduler_job_id,
            "study_id": study_id,
            "method_file": str((target_root / "method.json").resolve()),
            "study_file": str((target_root / "study.json").resolve()),
        }
    )
    _write(target_root / "task.json", task)
    _write(
        target_root / "result.json",
        {"task_id": task_id, "scheduler_job_id": scheduler_job_id},
    )
    _write(target_root / "electronic.json", {"task_id": task_id})
    _write(target_root / "study.json", {"study_id": study_id})
    (target_root / "input.extxyz").write_text(f"{CONTRACT_EVIDENCE}\n", encoding="utf-8")
    return task


def _pyatb_point(
    root: Path,
    *,
    task_id: str,
    scheduler_job_id: str,
    scf_task_id: str,
    scf_scheduler_job_id: str,
    polarization_value: float,
) -> tuple[dict, Path]:
    root.mkdir(parents=True, exist_ok=True)
    output_file = root / "Out" / "Polarization" / "polarization.dat"
    out_input_json = root / "Out" / "input.json"
    input_file = root / "Input"
    raw_output_file = root / "polarization.raw.txt"
    record_file = root / "polarization-record.json"
    raw_output_text = (
        "The Ionic Phase      :        0.010000        0.000000        0.000000\n"
        "The Electronic Phase :       -0.004000        0.000000        0.000000\n"
        f"The calculated polarization direction is in a, P = {polarization_value: .6f} (mod 0.700000) C/m^2.\n"
        "The calculated polarization direction is in b, P =        0.000000 (mod 0.700000) C/m^2.\n"
        "The calculated polarization direction is in c, P =        0.000000 (mod 0.700000) C/m^2.\n"
    )
    ionic_phase = {
        "values": [0.01, 0.0, 0.0],
        "raw_tokens": ["0.010000", "0.000000", "0.000000"],
        "unit": "dimensionless_reduced_phase",
    }
    electronic_phase = {
        "values": [-0.004, 0.0, 0.0],
        "raw_tokens": ["-0.004000", "0.000000", "0.000000"],
        "unit": "dimensionless_reduced_phase",
    }
    polarization = {
        "a": {
            "value_C_m2": polarization_value,
            "quantum_C_m2": 0.7,
            "unit": "C/m^2",
            "value_raw_token": f"{polarization_value:.6f}",
            "quantum_raw_token": "0.700000",
        },
        "b": {
            "value_C_m2": 0.0,
            "quantum_C_m2": 0.7,
            "unit": "C/m^2",
            "value_raw_token": "0.000000",
            "quantum_raw_token": "0.700000",
        },
        "c": {
            "value_C_m2": 0.0,
            "quantum_C_m2": 0.7,
            "unit": "C/m^2",
            "value_raw_token": "0.000000",
            "quantum_raw_token": "0.700000",
        },
    }
    branch = {
        "status": "unselected",
        "physical_branch_selected": False,
        "integer_shift": None,
        "nearest_quantum_applied": False,
    }
    task = {
        "schema": "mlcc.pyatb-postprocess-task.v1",
        "task_id": task_id,
        "engine": "pyatb",
        "engine_version": "1.1.2.dev0",
        "runner": "slurm",
        "scheduler_job_id": scheduler_job_id,
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "reference_scf_task_id": scf_task_id,
        "reference_scf_job_id": scf_scheduler_job_id,
    }
    _write(root / "task.json", task)
    input_file.write_text(f"{CONTRACT_EVIDENCE}\n", encoding="utf-8")
    _write(out_input_json, {"contract": CONTRACT_EVIDENCE})
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(raw_output_text, encoding="utf-8")
    raw_output_file.write_text(raw_output_text, encoding="utf-8")
    _write(
        record_file,
        {
            "phase_unit": "dimensionless_reduced_phase",
            "ionic_phase": {key: ionic_phase[key] for key in ("values", "raw_tokens")},
            "electronic_phase": {key: electronic_phase[key] for key in ("values", "raw_tokens")},
            "polarization": polarization,
            "raw_output_text": raw_output_text,
        },
    )
    source = {
        "task_id": task_id,
        "job_id": scheduler_job_id,
        "task_path": str(root.resolve()),
        "input": str(input_file.resolve()),
        "out_input_json": str(out_input_json.resolve()),
        "polarization_output": str(output_file.resolve()),
        "raw_output_file": str(raw_output_file.resolve()),
        "raw_output_text": raw_output_text,
        "record_file": str(record_file.resolve()),
        "ionic_phase": copy.deepcopy(ionic_phase),
        "electronic_phase": copy.deepcopy(electronic_phase),
        "polarization": copy.deepcopy(polarization),
        "branch": branch,
    }
    return source, output_file


def _born_family_fixture(tmp_path: Path) -> tuple[Path, dict, Path]:
    _, displacement_root, _ = _native_fixture(tmp_path)
    task_root = displacement_root.parent
    reference_root = task_root / "reference"
    model_path = tmp_path / "model"
    reference_task = json.loads((reference_root / "task.json").read_text(encoding="utf-8"))
    method = json.loads((reference_root / "method.json").read_text(encoding="utf-8"))
    parent = {
        "study_id": reference_task["study_id"],
        "model_id": reference_task["model_id"],
        "model_version": reference_task["model_version"],
        "model_path": reference_task["model_path"],
    }

    plus_task = _clone_displacement_task(
        displacement_root,
        task_root / "born-displacement-plus",
        task_id="czo-contract-displacement-plus",
        scheduler_job_id="284-contract-plus",
        study_id="czo-contract-displacement-plus-study",
    )
    minus_task = _clone_displacement_task(
        displacement_root,
        task_root / "born-displacement-minus",
        task_id="czo-contract-displacement-minus",
        scheduler_job_id="285-contract-minus",
        study_id="czo-contract-displacement-minus-study",
    )
    reference_pyatb, _ = _pyatb_point(
        tmp_path / "pyatb-reference",
        task_id="czo-contract-pyatb-reference",
        scheduler_job_id="311-contract",
        scf_task_id=reference_task["task_id"],
        scf_scheduler_job_id=reference_task["scheduler_job_id"],
        polarization_value=0.0,
    )
    plus_pyatb, plus_output = _pyatb_point(
        tmp_path / "pyatb-plus",
        task_id="czo-contract-pyatb-plus",
        scheduler_job_id="316-contract",
        scf_task_id=plus_task["task_id"],
        scf_scheduler_job_id=plus_task["scheduler_job_id"],
        polarization_value=0.0015,
    )
    minus_pyatb, _ = _pyatb_point(
        tmp_path / "pyatb-minus",
        task_id="czo-contract-pyatb-minus",
        scheduler_job_id="317-contract",
        scf_task_id=minus_task["task_id"],
        scf_scheduler_job_id=minus_task["scheduler_job_id"],
        polarization_value=-0.0015,
    )

    reference = {
        **reference_pyatb,
        "reference_scf_task_id": reference_task["task_id"],
        "reference_scf_job_id": reference_task["scheduler_job_id"],
        "study_id": parent["study_id"],
        "model_id": parent["model_id"],
        "model_version": parent["model_version"],
        "model_path": parent["model_path"],
        "native_scf_task_id": reference_task["task_id"],
        "native_scf_task_path": str(reference_root.resolve()),
        "native_scf_job_id": reference_task["scheduler_job_id"],
    }

    def source_scf(root: Path, task: dict) -> dict:
        return {
            "task_id": task["task_id"],
            "job_id": task["scheduler_job_id"],
            "task_path": str(root.resolve()),
            "study_id": task["study_id"],
            "model_id": task["model_id"],
            "model_version": task["model_version"],
            "model_path": task["model_path"],
            "stru": str((root / "STRU").resolve()),
            "input_extxyz": str((root / "input.extxyz").resolve()),
        }

    def manifest(root: Path, task: dict, sign: str, vector: list[float]) -> dict:
        return {
            "index": 1 if sign == "+" else 2,
            "source_task_id": task["task_id"],
            "source_task_path": str(root.resolve()),
            "atom_id": 0,
            "atom_index": 0,
            "element": "Ca",
            "direction": 0,
            "direction_label": "x",
            "sign": sign,
            "vector_A": vector,
            "distance_A": abs(vector[0]),
        }

    def pair(
        root: Path,
        task: dict,
        pyatb: dict,
        sign: str,
        vector: list[float],
    ) -> dict:
        point = {
            "manifest": manifest(root, task, sign, vector),
            "source_scf": source_scf(root, task),
            "pyatb": pyatb,
            "ionic_phase": copy.deepcopy(pyatb["ionic_phase"]),
            "electronic_phase": copy.deepcopy(pyatb["electronic_phase"]),
            "polarization": copy.deepcopy(pyatb["polarization"]),
            "branch": copy.deepcopy(pyatb["branch"]),
            "delta_u_A": vector[0],
            "displacement_delta_vector_A": vector,
            "displacement_denominator_definition": "plus_vector_A[direction] - minus_vector_A[direction]",
            "quantum_consistency": {
                "plus_C_m2": [0.7, 0.7, 0.7],
                "minus_C_m2": [0.7, 0.7, 0.7],
                "equal_within_1e-12": True,
                "absolute_difference_C_m2": [0.0, 0.0, 0.0],
            },
            "delta_wrapped_lattice_C_m2": [0.003, 0.0, 0.0],
            "deltaP_family": {
                "formula": "deltaP(n) = delta_wrapped_lattice_C_m2 + diag(Q_C_m2) @ n",
                "n_domain": "Z^3",
                "quantum_diagonal_C_m2": [[0.7, 0.0, 0.0], [0.0, 0.7, 0.0], [0.0, 0.0, 0.7]],
                "branch_shift_vector_C_m2": "diag(Q_C_m2) @ n",
                "n": "integer vector; physical branch not selected",
            },
            "derivative_base_C_m2_per_A": [0.15, 0.0, 0.0],
            "derivative_branch_step_C_m2_per_A": [35.0, 35.0, 35.0],
            "derivative_branch_step_matrix_C_m2_per_A": [
                [35.0, 0.0, 0.0],
                [0.0, 35.0, 0.0],
                [0.0, 0.0, 35.0],
            ],
            "conditional_zero_relative_branch_born_column_e": [2.4, 0.0, 0.0],
            "conditional_branch_step_born_column_e": [560.0, 560.0, 560.0],
            "born_coefficient_definition": {
                "formula": "Z_conditional(e) = volume_A3 * 1e-20 / e * derivative_C_m2_per_A",
                "rows": "lattice polarization directions a,b,c",
                "column": "x",
                "units": "e",
                "branch": "zero-relative n=(0,0,0) coefficient only",
                "physical_born_tensor": False,
            },
            "branch_status": "unresolved_physical_branch",
            "selected_branch_shift": None,
            "unresolved_reasons": ["physical branch is intentionally unresolved in the software contract"],
        }
        return point

    plus = pair(
        task_root / "born-displacement-plus",
        plus_task,
        plus_pyatb,
        "+",
        [0.01, 0.0, 0.0],
    )
    minus = pair(
        task_root / "born-displacement-minus",
        minus_task,
        minus_pyatb,
        "-",
        [-0.01, 0.0, 0.0],
    )
    collection_path = tmp_path / "ordered-polarization-collection.json"
    collection = {
        "schema": "mlcc.native-ordered-polarization-collection.v1",
        "parent": parent,
        "ordered_points": [plus, minus],
        "ordered_point_count": 2,
    }
    _write(collection_path, collection)

    postprocess_path = tmp_path / "born-family-postprocess-task.json"
    _write(
        postprocess_path,
        {
            "schema": "mlcc.native-born-family-postprocess-task.v1",
            "task_id": "czo-contract-born-family-postprocess",
            "engine": "mlcc",
            "engine_version": "contract",
            "runner": "slurm",
            "scheduler_job_id": "349-contract",
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "study_id": parent["study_id"],
        },
    )
    affine_family = {
        "definition": "base_tensor_e + sum(n_i * coefficient_tensor_i_e)",
        "n_domain": "Z^3",
        "base_tensor_e": [
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]],
        ],
        "coefficient_tensors_e": [
            [
                [[0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.0, 0.1]],
                [[0.2, 0.0, 0.0], [0.0, 0.2, 0.0], [0.0, 0.0, 0.2]],
            ],
            [
                [[0.3, 0.0, 0.0], [0.0, 0.3, 0.0], [0.0, 0.0, 0.3]],
                [[0.4, 0.0, 0.0], [0.0, 0.4, 0.0], [0.0, 0.0, 0.4]],
            ],
        ],
        "integer_labels": [[0, 0, 0], [1, 0, 0]],
        "physical_branch_selected": False,
        "physical_born_tensor": None,
        "selection_policy": {
            "selected_branch_shift": None,
            "nearest_quantum_applied": False,
            "asr_projected": False,
        },
        "atom_ids_in_tensor_order": [0, 1],
        "atom_elements_in_tensor_order": ["Ca", "Zr"],
        "axes": {
            "tensor": ["atom", "polarization", "displacement"],
            "polarization": ["x", "y", "z"],
            "displacement": ["x", "y", "z"],
            "basis": "Cartesian",
        },
    }
    raw = {
        "schema": "mlcc.native-born-branch-family.v1",
        "status": "unresolved_physical_branch",
        "source_mode": "native_source_bound",
        "provenance_kind": "native_derived",
        "parent": parent,
        "common_method": method,
        "reference": reference,
        "atom_ids": [0, 1],
        "atom_elements": ["Ca", "Zr"],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
        "axes": {"tensor": ["atom", "polarization", "displacement"]},
        "polarization_axes": ["a", "b", "c"],
        "polarization_basis": "lattice",
        "displacement_axes": ["x", "y", "z"],
        "displacement_basis": "Cartesian",
        "unit": "e",
        "pairs": [
            {
                "pair_index": 1,
                "atom_id": 0,
                "atom_index": 0,
                "element": "Ca",
                "direction": 0,
                "direction_label": "x",
                "plus": plus,
                "minus": minus,
            }
        ],
        "conditional_zero_relative_branch_born_column_e": [2.4, 0.0, 0.0],
        "affine_family": affine_family,
        "born_effective_charge_tensor": None,
        "born_status": "unresolved_physical_branch",
        "selected_branch_shift": None,
        "unresolved_reasons": [
            "physical branch is intentionally unresolved in the software contract",
            "integer polarization quantum shifts remain free",
        ],
        "scheduler_observations": [],
        "scientific_qualification": False,
        "production_qualification": False,
        "source": {
            "collection_file": str(collection_path.resolve()),
            "postprocess_task_files": [str(postprocess_path.resolve())],
        },
    }
    family_path = tmp_path / "born-family.json"
    _write(family_path, raw)
    return family_path, raw, plus_output


def test_native_born_family_preserves_affine_and_raw_polarization_data(tmp_path: Path):
    family_path, raw, _ = _born_family_fixture(tmp_path)
    product = read_native_born_family(family_path)

    assert product["full_born_tensors_e"] is None
    assert product["columns"] == []
    assert product["status"] == "unresolved"
    assert product["raw_product"]["affine_family"] == raw["affine_family"]
    assert product["raw_product"]["pairs"][0]["plus"]["deltaP_family"] == raw["pairs"][0]["plus"]["deltaP_family"]
    assert product["raw_product"]["pairs"][0]["plus"]["pyatb"]["raw_output_text"] == raw["pairs"][0]["plus"]["pyatb"]["raw_output_text"]
    reference_electronic = Path(product["insulation_evidence"][0]["source_path"])
    assert reference_electronic.name == "electronic.json"
    assert reference_electronic.parent.name == "reference"


def test_native_born_family_rejects_selected_branch(tmp_path: Path):
    family_path, raw, _ = _born_family_fixture(tmp_path)
    raw["affine_family"]["physical_branch_selected"] = True
    _write(family_path, raw)

    with pytest.raises(ValueError, match="selected physical tensors"):
        read_native_born_family(family_path)


def test_native_born_family_maps_independent_sites_to_full_affine_order(tmp_path: Path):
    family_path, raw, _ = _born_family_fixture(tmp_path)
    raw["atom_ids"] = [0]
    raw["atom_elements"] = ["Ca"]
    _write(family_path, raw)
    product = read_native_born_family(family_path)
    assert product["raw_product"]["atom_ids"] == [0]
    assert product["context"]["atom_ids"] == [0, 1]
    assert product["atom_ids"] == [0, 1]
    assert len(product["missing_columns"]) == 6


def test_native_born_family_rejects_saved_point_raw_polarization_mismatch(tmp_path: Path):
    family_path, _, plus_output = _born_family_fixture(tmp_path)
    plus_output.write_text("tampered native polarization output\n", encoding="utf-8")

    with pytest.raises(ValueError, match="raw text differs from native output"):
        read_native_born_family(family_path)


def test_native_born_family_binds_record_phase_unit_at_top_level(tmp_path: Path):
    family_path, raw, _ = _born_family_fixture(tmp_path)
    record_path = Path(raw["pairs"][0]["plus"]["pyatb"]["record_file"])
    record = json.loads(record_path.read_text())
    assert "unit" not in record["ionic_phase"]
    assert record["phase_unit"] == raw["pairs"][0]["plus"]["ionic_phase"]["unit"]
    product = read_native_born_family(family_path)
    assert product["raw_product"]["pairs"][0]["plus"]["ionic_phase"] == raw["pairs"][0]["plus"]["ionic_phase"]
