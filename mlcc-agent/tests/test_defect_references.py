"""Software-contract tests for saved defect electronic references.

The task, model, native-output, and electronic JSON files in these tests are
explicit contract fixtures only.  The native files contain placeholders and
are never treated as real DFT evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc.defect_references import (
    ELECTRONIC_SCHEMA,
    REFERENCE_SCHEMA,
    build_defect_electronic_reference,
    defect_electronic_reference,
    read_defect_electronic_reference,
)


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _make_contract_case(
    tmp_path: Path,
    *,
    role: str = "host",
    charge: int = 0,
) -> dict[str, Path | dict]:
    """Create a small software-only task/reference contract fixture."""

    root = tmp_path / f"{role}-q{charge}"
    task_path = root / "task"
    model_path = root / "model"
    study_path = root / "study.json"
    task_id = f"software-contract-{role}-q{charge}"
    scheduler_job_id = f"job-{charge + 100}"
    model_id = f"czo-{role}-model"
    model_version = "v001"
    method_set = f"software-contract-method-q{charge}"
    suffix = "ContractSCF"
    atom_ids = [0, 1]
    lattice = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]
    atoms = [
        {"element": "Ca", "cart_coords_angstrom": [0.0, 0.0, 0.0]},
        {"element": "O", "cart_coords_angstrom": [2.0, 2.0, 2.0]},
    ]

    model = {
        "model_id": model_id,
        "version": model_version,
        "atom_ids": atom_ids,
        "lattice_angstrom": lattice,
        "atoms": atoms,
        "atom_lineage": [
            {"atom_id": 0, "parent_atom_id": 0, "operation": "preserved"},
            {"atom_id": 1, "parent_atom_id": 1, "operation": "preserved"},
        ],
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    parent_model = None
    if role == "defect":
        parent_path = root / "parent-model"
        parent_model = {
            "model_id": "czo-host-parent",
            "version": "v001",
            "atom_ids": atom_ids,
            "lattice_angstrom": lattice,
            "atoms": atoms,
            "fixture": True,
            "fixture_purpose": "software_contract_only",
        }
        _write_json(parent_path / "model.json", parent_model)
        model.update(
            {
                "derivation_schema": "mlcc.model-derivation.v1",
                "derivation": {
                    "kind": "explicit_defect_sequence",
                    "model_id": model_id,
                    "version": model_version,
                    "charge_state": charge,
                },
                "parent_model": {
                    "model_id": parent_model["model_id"],
                    "version": parent_model["version"],
                    "path": str(parent_path),
                },
            }
        )
    _write_json(model_path / "model.json", model)

    study = {
        "study_id": f"software-contract-study-{role}-q{charge}",
        "model": {"model_id": model_id, "version": model_version},
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    _write_json(study_path, study)

    task = {
        "task_id": task_id,
        "scheduler_job_id": scheduler_job_id,
        "status": "COMPLETED",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "runner": "slurm",
        "engine": "abacus",
        "engine_version": "3.10.1",
        "calculation": "scf",
        "study_id": study["study_id"],
        "study_file": str(study_path),
        "model_id": model_id,
        "model_version": model_version,
        "model_path": str(model_path),
        "method_set": method_set,
        "calculation_conditions": {
            "cell_constraint": "fixed_cell",
            "net_charge": charge,
        },
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    method = {
        "model_id": model_id,
        "version": model_version,
        "method_set": method_set,
        "suffix": suffix,
        "net_charge": charge,
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "basis_type": "pw",
        "dft_functional": "PBE",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "element_order": ["Ca", "O"],
        "initial_moments_muB_by_element": {"Ca": 0.0, "O": 0.0},
        "pseudopotential_ids": {"Ca": "Ca.upf", "O": "O.upf"},
        "pseudopotential_metadata": {
            "Ca": {"source": "software_contract_only"},
            "O": {"source": "software_contract_only"},
        },
        "pseudopotential_treatment": {"Ca": "fixture", "O": "fixture"},
        "smearing_method": "fixed",
        "ks_solver": "dav",
        "kpoints": [2, 2, 2],
        "kpoint_rule": "Gamma",
        "mixing_type": "plain",
        "symmetry": "none",
        "parameters": {"smearing_sigma_Ry": 0.0, "ecutwfc_Ry": 100.0},
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    result = {
        "task_id": task_id,
        "scheduler_job_id": scheduler_job_id,
        "method_set": method_set,
        "electronic_converged": True,
        "atom_ids": atom_ids,
        "final_atoms": {"cell_angstrom": lattice},
        "energy_eV": -12.5,
        "energy_unit": "eV",
        "net_charge": charge,
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    atom_map = {
        "model_id": model_id,
        "version": model_version,
        "source_atom_ids": atom_ids,
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }

    _write_json(task_path / "task.json", task)
    _write_json(task_path / "result.json", result)
    _write_json(task_path / "method.json", method)
    _write_json(task_path / "STRU.atom-map.json", atom_map)
    for name in ("INPUT", "KPT"):
        (task_path / name).write_text(
            "software-contract-only placeholder; no native calculation\n",
            encoding="utf-8",
        )
    native_path = task_path / f"OUT.{suffix}"
    for name in ("running_scf.log", "istate.info", "kpoints"):
        (native_path / name).parent.mkdir(parents=True, exist_ok=True)
        (native_path / name).write_text(
            "software-contract-only placeholder; no native calculation\n",
            encoding="utf-8",
        )

    source_files = {
        "task.json": str(task_path / "task.json"),
        "result.json": str(task_path / "result.json"),
        "method.json": str(task_path / "method.json"),
        "INPUT": str(task_path / "INPUT"),
        "KPT": str(task_path / "KPT"),
        "running_scf.log": str(native_path / "running_scf.log"),
        "istate.info": str(native_path / "istate.info"),
        "kpoints": str(native_path / "kpoints"),
    }
    electronic = {
        "schema": ELECTRONIC_SCHEMA,
        "evidence_kind": "software_contract_only",
        "native_completed": True,
        "native_exit_code": "0:0",
        "electronic_converged": True,
        "task_id": task_id,
        "scheduler_job_id": scheduler_job_id,
        "method_set": method_set,
        "engine": "abacus",
        "engine_version": "3.10.1",
        "model_id": model_id,
        "model_version": model_version,
        "electron_count_q": charge,
        "electron_count_delta": -charge,
        "electron_count_neutral": 10.0,
        "electron_count_target": 10.0 - charge,
        "electron_count_native": 10.0 - charge,
        "vbm_eV": 1.25,
        "cbm_eV": 2.75,
        "sampled_mesh_KS_gap_eV": 1.5,
        "fermi_level_eV": 1.25,
        "vbm_reference": "sampled_neutral_level" if charge == 0 else "sampled_charged_level",
        "fermi_reference": "native_scf_fermi_level",
        "gap_status": "sampled_mesh_only",
        "gap_qualification": {"precision_qualified": False},
        "kpoint_coordinate_system": "fractional",
        "kpoint_mesh": [2, 2, 2],
        "kpoint_mesh_shift": [0, 0, 0],
        "parent_energy_zero_eV": result["energy_eV"],
        "parent_energy_zero_definition": "saved task total energy; not a potential zero",
        "source_files": source_files,
    }
    electronic_path = _write_json(task_path / "electronic.json", electronic)
    return {
        "task_path": task_path,
        "electronic_path": electronic_path,
        "study_path": study_path,
        "model_path": model_path,
        "task": task,
        "result": result,
        "method": method,
        "electronic": electronic,
    }


def _make_pair_case(tmp_path: Path, *, different_kpoints: bool = False) -> dict[str, dict]:
    host = _make_contract_case(tmp_path, role="host", charge=0)
    defect = _make_contract_case(tmp_path, role="defect", charge=2)

    host_model_file = host["model_path"] / "model.json"
    host_model = json.loads(host_model_file.read_text(encoding="utf-8"))
    defect_model_file = defect["model_path"] / "model.json"
    defect_model = json.loads(defect_model_file.read_text(encoding="utf-8"))
    defect_model["parent_model"] = {
        "model_id": host_model["model_id"],
        "version": host_model["version"],
        "path": str(host["model_path"]),
    }
    _write_json(defect_model_file, defect_model)

    host_method_file = host["task_path"] / "method.json"
    host_method = json.loads(host_method_file.read_text(encoding="utf-8"))
    defect_method_file = defect["task_path"] / "method.json"
    defect_method = json.loads(defect_method_file.read_text(encoding="utf-8"))
    defect_method["method_set"] = host_method["method_set"]
    if different_kpoints:
        defect_method["kpoints"] = [3, 3, 3]
    _write_json(defect_method_file, defect_method)

    for filename in ("task.json", "result.json"):
        file = defect["task_path"] / filename
        value = json.loads(file.read_text(encoding="utf-8"))
        value["method_set"] = host_method["method_set"]
        _write_json(file, value)
    defect_electronic_file = defect["electronic_path"]
    defect_electronic = json.loads(defect_electronic_file.read_text(encoding="utf-8"))
    defect_electronic["method_set"] = host_method["method_set"]
    if different_kpoints:
        defect_electronic["kpoint_mesh"] = [3, 3, 3]
    _write_json(defect_electronic_file, defect_electronic)
    return {"host": host, "defect": defect}


def test_neutral_host_reference_binds_saved_electronic_contract(tmp_path: Path) -> None:
    case = _make_contract_case(tmp_path, role="host", charge=0)

    reference = defect_electronic_reference(
        case["task_path"], case["electronic"], role="host"
    )

    assert reference["schema"] == REFERENCE_SCHEMA
    assert reference["role"] == "host"
    assert reference["status"] == "sampled_host_reference_unaligned"
    assert reference["charge"]["q"] == 0
    assert reference["model"]["atom_ids"] == [0, 1]
    assert reference["kpoint_sampling"]["saved_electronic_mesh"] == [2, 2, 2]
    assert reference["kpoint_sampling"]["saved_electronic_shift"] == [0, 0, 0]
    assert reference["kpoint_sampling"]["method_shift_status"] == "not_recorded"
    assert reference["aligned_host_vbm_eV"] is None
    assert reference["potential_alignment_eV"] is None
    assert reference["scientific_qualification"] is False
    assert reference["production_qualification"] is False
    assert reference["parent_total_energy_provenance"]["is_potential_zero"] is False
    assert reference["electronic_source"]["evidence_kind"] == "software_contract_only"


def test_charged_defect_reference_preserves_lineage_but_stays_unaligned(
    tmp_path: Path,
) -> None:
    case = _make_contract_case(tmp_path, role="defect", charge=2)

    reference = read_defect_electronic_reference(
        case["task_path"], case["electronic_path"], role="defect"
    )

    assert reference["status"] == "sampled_defect_levels_unaligned"
    assert reference["charge"]["q"] == 2
    assert reference["parent_model"]["model_id"] == "czo-host-parent"
    assert reference["defect_descriptor"]["kind"] == "explicit_defect_sequence"
    assert reference["defect_descriptor"]["charge_state"] == 2
    assert reference["levels"]["vbm_reference"] == "sampled_charged_level"
    assert reference["model"]["atom_lineage"][0]["parent_atom_id"] == 0
    assert reference["aligned_host_vbm_eV"] is None
    assert reference["potential_alignment_eV"] is None
    assert reference["scientific_qualification"] is False
    assert reference["production_qualification"] is False


def test_charged_reference_cannot_be_bound_as_host(tmp_path: Path) -> None:
    case = _make_contract_case(tmp_path, role="defect", charge=2)

    with pytest.raises(ValueError, match="host role requires a neutral"):
        read_defect_electronic_reference(
            case["task_path"], case["electronic_path"], role="host"
        )


def test_defect_descriptor_charge_must_match_task_charge(tmp_path: Path) -> None:
    case = _make_contract_case(tmp_path, role="defect", charge=2)
    model_file = case["model_path"] / "model.json"
    model = json.loads(model_file.read_text(encoding="utf-8"))
    model["derivation"]["charge_state"] = 1
    _write_json(model_file, model)

    with pytest.raises(ValueError, match="descriptor identity or charge"):
        read_defect_electronic_reference(
            case["task_path"], case["electronic_path"], role="defect"
        )


def test_saved_electronic_job_and_source_paths_are_bound_to_task(
    tmp_path: Path,
) -> None:
    case = _make_contract_case(tmp_path, role="host", charge=0)
    electronic_file = case["electronic_path"]
    electronic = json.loads(electronic_file.read_text(encoding="utf-8"))
    electronic["scheduler_job_id"] = "wrong-job"
    _write_json(electronic_file, electronic)

    with pytest.raises(ValueError, match="scheduler_job_id differs"):
        read_defect_electronic_reference(
            case["task_path"], electronic_file, role="host"
        )

    electronic["scheduler_job_id"] = case["task"]["scheduler_job_id"]
    electronic["source_files"]["istate.info"] = str(tmp_path / "wrong-istate.info")
    _write_json(electronic_file, electronic)

    with pytest.raises(ValueError, match="electronic source istate.info"):
        read_defect_electronic_reference(
            case["task_path"], electronic_file, role="host"
        )


def test_study_and_persisted_model_identity_are_checked(tmp_path: Path) -> None:
    case = _make_contract_case(tmp_path, role="host", charge=0)
    study = json.loads(case["study_path"].read_text(encoding="utf-8"))
    study["model"]["version"] = "wrong-version"
    _write_json(case["study_path"], study)

    with pytest.raises(ValueError, match="Study model differs"):
        read_defect_electronic_reference(
            case["task_path"], case["electronic_path"], role="host"
        )

    study["model"]["version"] = case["task"]["model_version"]
    _write_json(case["study_path"], study)
    model_file = case["model_path"] / "model.json"
    model = json.loads(model_file.read_text(encoding="utf-8"))
    model["model_id"] = "wrong-model"
    _write_json(model_file, model)

    with pytest.raises(ValueError, match="persisted model differs"):
        read_defect_electronic_reference(
            case["task_path"], case["electronic_path"], role="host"
        )


def test_total_energy_provenance_is_explicitly_not_a_potential_zero(
    tmp_path: Path,
) -> None:
    case = _make_contract_case(tmp_path, role="host", charge=0)

    reference = read_defect_electronic_reference(
        case["task_path"], case["electronic_path"], role="host"
    )

    provenance = reference["parent_total_energy_provenance"]
    assert provenance["value_eV"] == case["result"]["energy_eV"]
    assert provenance["original_field"] == "parent_energy_zero_eV"
    assert provenance["is_potential_zero"] is False
    assert "common_potential_reference" in reference["missing_evidence"]
    assert reference["potential_alignment_eV"] is None


def test_invalid_reference_schema_is_rejected_before_binding(tmp_path: Path) -> None:
    case = _make_contract_case(tmp_path, role="host", charge=0)
    electronic_file = case["electronic_path"]
    electronic = json.loads(electronic_file.read_text(encoding="utf-8"))
    electronic["schema"] = "wrong.electronic.schema"
    _write_json(electronic_file, electronic)

    with pytest.raises(ValueError, match="unsupported saved electronic schema"):
        read_defect_electronic_reference(
            case["task_path"], electronic_file, role="host"
        )


def test_historical_neutral_host_may_omit_saved_task_charge_fields(
    tmp_path: Path,
) -> None:
    case = _make_contract_case(tmp_path, role="host", charge=0)
    task_file = case["task_path"] / "task.json"
    task = json.loads(task_file.read_text(encoding="utf-8"))
    task.pop("net_charge", None)
    task["calculation_conditions"].pop("net_charge", None)
    _write_json(task_file, task)
    result_file = case["task_path"] / "result.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    result.pop("net_charge", None)
    _write_json(result_file, result)

    reference = read_defect_electronic_reference(
        case["task_path"], case["electronic_path"], role="host"
    )

    assert reference["charge"]["q"] == 0
    assert reference["scientific_qualification"] is False


def test_pair_binds_parent_descriptor_and_keeps_alignment_unresolved(
    tmp_path: Path,
) -> None:
    pair = _make_pair_case(tmp_path)
    host = pair["host"]
    defect = pair["defect"]

    paired = build_defect_electronic_reference(
        host["electronic_path"],
        defect["electronic_path"],
        defect["model_path"] / "model.json",
    )

    assert paired["schema"] == "mlcc.defect-reference-pair.v1"
    assert paired["status"] == "matching_recorded_fields_unaligned"
    assert paired["method_comparison"]["same_recorded_comparison_fields"] is True
    assert paired["method_comparison"]["same_method_label"] is True
    assert paired["defect"]["parent_model"]["model_id"] == paired["host"]["model"]["model_id"]
    assert paired["host"]["kpoint_sampling"]["method_shift_status"] == "not_recorded"
    assert paired["defect"]["kpoint_sampling"]["method_shift_status"] == "not_recorded"
    assert "electronic.kpoint_mesh" in paired["method_comparison"]["compared_numerical_fields"]
    assert "electronic.kpoint_mesh_shift" in paired["method_comparison"]["compared_numerical_fields"]
    assert "suffix" in paired["method_comparison"]["unassessed_method_fields_by_role"]["host"]
    assert paired["aligned_host_vbm_eV"] is None
    assert paired["potential_alignment_eV"] is None
    assert paired["scientific_qualification"] is False
    assert paired["production_qualification"] is False


def test_pair_reports_numerical_protocol_difference_without_alignment(
    tmp_path: Path,
) -> None:
    pair = _make_pair_case(tmp_path, different_kpoints=True)
    host = pair["host"]
    defect = pair["defect"]

    paired = build_defect_electronic_reference(
        host["electronic_path"],
        defect["electronic_path"],
        defect["model_path"] / "model.json",
    )

    comparison = paired["method_comparison"]
    assert paired["status"] == "different_or_incomplete_recorded_fields_unaligned"
    assert comparison["same_recorded_comparison_fields"] is False
    assert "kpoints" in comparison["numerical_differences"]
    assert "electronic.kpoint_mesh" in comparison["numerical_differences"]
    assert paired["aligned_host_vbm_eV"] is None
    assert paired["potential_alignment_eV"] is None


def test_pair_rejects_wrong_descriptor_or_parent_model(
    tmp_path: Path,
) -> None:
    descriptor_pair = _make_pair_case(tmp_path / "descriptor")
    with pytest.raises(ValueError, match="explicit descriptor"):
        build_defect_electronic_reference(
            descriptor_pair["host"]["electronic_path"],
            descriptor_pair["defect"]["electronic_path"],
            tmp_path / "descriptor" / "wrong-model.json",
        )

    parent_pair = _make_pair_case(tmp_path / "parent")
    defect_model_file = parent_pair["defect"]["model_path"] / "model.json"
    defect_model = json.loads(defect_model_file.read_text(encoding="utf-8"))
    defect_model["parent_model"]["model_id"] = "wrong-parent"
    _write_json(defect_model_file, defect_model)

    with pytest.raises(ValueError, match="defect parent model identity"):
        build_defect_electronic_reference(
            parent_pair["host"]["electronic_path"],
            parent_pair["defect"]["electronic_path"],
            defect_model_file,
        )


def test_saved_mesh_shift_must_match_recorded_method_shift(tmp_path: Path) -> None:
    case = _make_contract_case(tmp_path, role="host", charge=0)
    method_file = case["task_path"] / "method.json"
    method = json.loads(method_file.read_text(encoding="utf-8"))
    method["kpoint_shift"] = [1, 0, 0]
    _write_json(method_file, method)

    with pytest.raises(ValueError, match="mesh shift differs from method"):
        read_defect_electronic_reference(
            case["task_path"], case["electronic_path"], role="host"
        )


def test_saved_mesh_must_match_method_mesh(tmp_path: Path) -> None:
    case = _make_contract_case(tmp_path, role="host", charge=0)
    electronic_file = case["electronic_path"]
    electronic = json.loads(electronic_file.read_text(encoding="utf-8"))
    electronic["kpoint_mesh"] = [3, 3, 3]
    _write_json(electronic_file, electronic)

    with pytest.raises(ValueError, match="saved electronic mesh differs from method"):
        read_defect_electronic_reference(
            case["task_path"], electronic_file, role="host"
        )
