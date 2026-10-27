"""Software-contract tests for explicit regional electrostatic-potential alignment.

The potentials and saved reference pair in this module are mathematical,
``software_contract_only`` fixtures.  They exercise units, grid identity,
selection semantics, and provenance binding; they are not native DFT output
and cannot establish scientific or production qualification.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Callable

import pytest

import mlcc.potential_alignment as potential_alignment
from mlcc.electrostatic_potential import BOHR_TO_ANGSTROM, RY_TO_EV


POTENTIAL_SCHEMA = "mlcc.abacus-electrostatic-potential.v1"
PAIR_SCHEMA = "mlcc.defect-reference-pair.v1"
REFERENCE_SCHEMA = "mlcc.defect-electronic-reference.v1"


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _cell_from_steps(shape: tuple[int, int, int], steps: list[list[float]]) -> list[list[float]]:
    return [[steps[index][component] * shape[index] for component in range(3)] for index in range(3)]


def _cube(
    values_ry: list[float],
    *,
    shape: tuple[int, int, int] = (2, 2, 2),
    origin_bohr: list[float] | None = None,
    steps_bohr: list[list[float]] | None = None,
) -> dict[str, Any]:
    origin = list(origin_bohr or [0.0, 0.0, 0.0])
    steps = copy.deepcopy(steps_bohr or [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    cell = _cell_from_steps(shape, steps)
    return {
        "schema": "mlcc.abacus-electrostatic-cube.v1",
        "source_file": "software-contract-only/ElecStaticPot.cube",
        "comments": [
            "STEP: 0  Cubefile created from ABACUS. Inner loop is z, followed by y and x [software_contract_only]",
            "1 (nspin)",
        ],
        "step": 0,
        "nspin": 1,
        "shape": list(shape),
        "origin_bohr": origin,
        "step_vectors_bohr": steps,
        "cell_bohr": cell,
        "origin_angstrom": [value * BOHR_TO_ANGSTROM for value in origin],
        "step_vectors_angstrom": [
            [value * BOHR_TO_ANGSTROM for value in row] for row in steps
        ],
        "cell_angstrom": [
            [value * BOHR_TO_ANGSTROM for value in row] for row in cell
        ],
        "atoms": [],
        "values_Ry": list(values_ry),
        "values_eV": [value * RY_TO_EV for value in values_ry],
        "axis_order": "x_outer_y_middle_z_inner",
        "flat_index": "(ix*ny+iy)*nz+iz",
        "unit_conversion": {
            "Ry_to_eV": RY_TO_EV,
            "Bohr_to_angstrom": BOHR_TO_ANGSTROM,
            "Bohr_constant_source": "mlcc.abacus.BOHR_PER_ANGSTROM reciprocal",
        },
        "print_precision": {
            "geometry_decimal_places": 6,
            "potential_scientific_decimal_places": 9,
            "geometry_half_quantum_bohr": 0.5e-6,
            "cell_row_half_quantum_bohr": [n * 0.5e-6 for n in shape],
            "potential_half_quantum_rule_Ry": "0.5 * 10**(printed_exponent - 9)",
        },
        "evidence_kind": "software_contract_only",
        "native_output_observed": False,
        "native_GPU_accepted": False,
        "scientific_qualification": False,
        "production_qualification": False,
    }


def _potential(
    values_ry: list[float],
    *,
    task_id: str = "software-host-task",
    scheduler_job_id: str = "software-job-205",
    study_id: str = "software-host-study",
    model_id: str = "czo-host-model",
    model_version: str = "v001",
    method_set: str = "abacus-contract-scf",
    shape: tuple[int, int, int] = (2, 2, 2),
    origin_bohr: list[float] | None = None,
    steps_bohr: list[list[float]] | None = None,
    net_charge: int = 0,
    host_vbm_eV: float | None = None,
) -> dict[str, Any]:
    cube = _cube(
        values_ry,
        shape=shape,
        origin_bohr=origin_bohr,
        steps_bohr=steps_bohr,
    )
    task_root = Path("software-contract-only") / task_id
    source_files = {
        "task.json": str(task_root / "task.json"),
        "result.json": str(task_root / "result.json"),
        "method.json": str(task_root / "method.json"),
        "model.json": str(task_root / "model.json"),
        "Study": str(task_root / "study.json"),
        "INPUT": str(task_root / "INPUT"),
        "OUT.INPUT": str(task_root / "OUT.INPUT"),
        "KPT": str(task_root / "KPT"),
        "STRU": str(task_root / "STRU"),
        "ElecStaticPot.cube": str(task_root / "ElecStaticPot.cube"),
    }
    method = {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "abacus_version_target": "3.10.1",
        "model_id": model_id,
        "version": model_version,
        "method_set": method_set,
        "basis_type": "pw",
        "dft_functional": "PBE",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "element_order": ["Ca", "Zr", "O"],
        "initial_moments_muB_by_element": {"Ca": 0.0, "Zr": 0.0, "O": 0.0},
        "pseudopotential_ids": {"Ca": "Ca-NC", "Zr": "Zr-NC", "O": "O-NC"},
        "pseudopotential_metadata": {
            "Ca": {"type": "NC"},
            "Zr": {"type": "NC"},
            "O": {"type": "NC"},
        },
        "pseudopotential_treatment": "norm_conserving",
        "ks_solver": "dav",
        "kpoints": [1, 1, 1],
        "kpoint_rule": "Gamma",
        "kpoint_shift": [0.0, 0.0, 0.0],
        "mixing_type": "plain",
        "symmetry": False,
        "pw_diag_thr": 1e-5,
        "berry": False,
        "parameters": {"smearing_sigma_Ry": 0.01},
        "smearing_method": "fixed",
        "net_charge": net_charge,
        "suffix": "ContractSCF",
    }
    record: dict[str, Any] = {
        "schema": POTENTIAL_SCHEMA,
        "status": "software_contract_fixture_unaligned",
        "task_id": task_id,
        "scheduler_job_id": scheduler_job_id,
        "native_job": {
            "scheduler_job_id": scheduler_job_id,
            "scheduler_state": "COMPLETED",
            "exit_code": "0:0",
            "runner": "slurm",
            "scheduler_fields": {"JobId": scheduler_job_id, "JobState": "COMPLETED"},
            "raw_scontrol": f"JobId={scheduler_job_id} JobState=COMPLETED",
        },
        "study_id": study_id,
        "model_id": model_id,
        "model_version": model_version,
        "method_set": method_set,
        "method": method,
        "conditions": {"cell_constraint": "fixed_cell", "net_charge": net_charge, "calculation": "scf"},
        "input_parameters": {"out_pot": 2},
        "atom_map": {
            "source_file": str(task_root / "STRU.atom-map.json"),
            "record": {"model_id": model_id, "version": model_version, "source_atom_ids": [0, 1]},
        },
        "mapped_atoms": [],
        "kind": "local_ionic_plus_hartree",
        "value_unit": "Ry",
        "geometry_unit": "Bohr",
        "sign_convention": "electron_potential_energy",
        "includes_XC": False,
        "includes_nonlocal_pseudopotential": False,
        "energy_zero": {
            "Hartree_G0": "zero",
            "local_ionic_G0": "retained_pseudopotential_convention",
            "total_mean_subtracted": False,
            "fermi_subtracted": False,
            "vacuum_subtracted": False,
        },
        "cube": cube,
        "source_files": source_files,
        "native_output_observed": False,
        "native_GPU_accepted": False,
        "electronic_converged": False,
        "scientific_qualification": False,
        "production_qualification": False,
        "aligned_host_vbm_eV": None,
        "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None,
        "charged_formation_energy_eV": None,
        "evidence_kind": "software_contract_only",
    }
    if host_vbm_eV is not None:
        record["host_vbm_eV"] = host_vbm_eV
    return record


def _selection(
    boxes: list[tuple[tuple[int, int, int], tuple[int, int, int]]],
) -> dict[str, Any]:
    return {
        "kind": "index_boxes",
        "boxes": [
            {"lower": list(lower), "upper": list(upper)} for lower, upper in boxes
        ],
        "reason": "explicit software-contract region",
        "source": "test declaration",
    }


def _flat_index(shape: tuple[int, int, int], ix: int, iy: int, iz: int) -> int:
    return (ix * shape[1] + iy) * shape[2] + iz


def test_constant_shift_reports_defect_minus_host_direction() -> None:
    host = _potential([0.0] * 8)
    defect = _potential([2.0 / RY_TO_EV] * 8, task_id="software-defect-task", scheduler_job_id="software-job-121", study_id="software-defect-study", model_id="czo-defect-model")

    result = potential_alignment.calculate_regional_potential_difference(
        host, defect, _selection([((0, 0, 0), (2, 2, 2))])
    )

    assert result["delta_v_defect_minus_host_eV"] == pytest.approx(2.0)
    assert result["sample_count"] == 8
    assert result["host_mean_eV"] == pytest.approx(0.0)
    assert result["defect_mean_eV"] == pytest.approx(2.0)
    assert result["difference_min_eV"] == pytest.approx(2.0)
    assert result["difference_max_eV"] == pytest.approx(2.0)
    assert result["difference_population_std_eV"] == pytest.approx(0.0)
    assert result["difference_peak_to_peak_eV"] == pytest.approx(0.0)
    assert result["evidence_kind"] == "software_contract_only"


def test_nonuniform_difference_reports_population_statistics() -> None:
    differences_ry = [0.0, 0.1, -0.2, 0.3, 0.4, -0.1, 0.2, -0.3]
    host = _potential([0.0] * 8)
    defect = _potential(
        differences_ry,
        task_id="software-defect-task",
        scheduler_job_id="software-job-121",
        study_id="software-defect-study",
        model_id="czo-defect-model",
    )
    selection = _selection([((0, 0, 0), (2, 2, 2))])

    result = potential_alignment.calculate_regional_potential_difference(host, defect, selection)
    differences_eV = [value * RY_TO_EV for value in differences_ry]
    mean = sum(differences_eV) / len(differences_eV)
    variance = sum((value - mean) ** 2 for value in differences_eV) / len(differences_eV)

    assert result["delta_v_defect_minus_host_eV"] == pytest.approx(mean)
    assert result["difference_min_eV"] == pytest.approx(min(differences_eV))
    assert result["difference_max_eV"] == pytest.approx(max(differences_eV))
    assert result["difference_population_std_eV"] == pytest.approx(math.sqrt(variance))
    assert result["difference_peak_to_peak_eV"] == pytest.approx(max(differences_eV) - min(differences_eV))


def test_overlapping_boxes_form_an_equal_weight_union_without_double_counting() -> None:
    shape = (3, 2, 2)
    host_values = [float(index) for index in range(math.prod(shape))]
    defect_values = [value + 0.25 / RY_TO_EV for value in host_values]
    host = _potential(host_values, shape=shape)
    defect = _potential(
        defect_values,
        shape=shape,
        task_id="software-defect-task",
        scheduler_job_id="software-job-121",
        study_id="software-defect-study",
        model_id="czo-defect-model",
    )
    selection = _selection(
        [
            ((0, 0, 0), (2, 2, 1)),
            ((1, 0, 0), (3, 2, 1)),
        ]
    )

    result = potential_alignment.calculate_regional_potential_difference(host, defect, selection)

    selected = {
        _flat_index(shape, ix, iy, iz)
        for lower, upper in [((0, 0, 0), (2, 2, 1)), ((1, 0, 0), (3, 2, 1))]
        for ix in range(lower[0], upper[0])
        for iy in range(lower[1], upper[1])
        for iz in range(lower[2], upper[2])
    }
    assert len(selected) == 6
    assert result["sample_count"] == len(selected)
    assert result["delta_v_defect_minus_host_eV"] == pytest.approx(0.25)
    assert result["difference_population_std_eV"] == pytest.approx(0.0)


def test_nonorthogonal_grid_is_checked_as_full_vectors_not_diagonal_lengths() -> None:
    shape = (2, 2, 1)
    steps = [[1.0, 0.2, 0.0], [0.0, 1.0, 0.3], [0.1, 0.0, 2.0]]
    host = _potential([0.0] * 4, shape=shape, steps_bohr=steps)
    defect = _potential(
        [0.5 / RY_TO_EV] * 4,
        shape=shape,
        steps_bohr=steps,
        task_id="software-defect-task",
        scheduler_job_id="software-job-121",
        study_id="software-defect-study",
        model_id="czo-defect-model",
    )

    result = potential_alignment.calculate_regional_potential_difference(
        host, defect, _selection([((0, 0, 0), (2, 2, 1))])
    )

    assert result["sample_count"] == 4
    assert result["delta_v_defect_minus_host_eV"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    "defect_kwargs, defect_values",
    [
        ({"origin_bohr": [0.25, 0.0, 0.0]}, [0.1] * 8),
        ({"steps_bohr": [[1.0, 0.1, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]}, [0.1] * 8),
        ({"shape": (1, 2, 2)}, [0.1] * 4),
    ],
    ids=["origin-difference", "step-vector-difference", "shape-difference"],
)
def test_rejects_two_individually_self_consistent_but_different_grids(
    defect_kwargs: dict[str, Any], defect_values: list[float],
) -> None:
    host = _potential([0.0] * 8)
    defect = _potential(
        defect_values,
        task_id="software-defect-task",
        scheduler_job_id="software-job-121",
        study_id="software-defect-study",
        model_id="czo-defect-model",
        **defect_kwargs,
    )

    with pytest.raises(ValueError):
        potential_alignment.calculate_regional_potential_difference(
            host,
            defect,
            _selection([((0, 0, 0), (2, 2, 2))]),
        )


@pytest.mark.parametrize(
    "mutate_host, mutate_defect",
    [
        (lambda host, defect: host.update({"value_unit": "eV"}), lambda host, defect: None),
        (lambda host, defect: None, lambda host, defect: defect.update({"geometry_unit": "Angstrom"})),
        (lambda host, defect: host.update({"kind": "voltage"}), lambda host, defect: None),
        (lambda host, defect: host.update({"sign_convention": "positive_test_charge"}), lambda host, defect: None),
        (lambda host, defect: host.update({"schema": "wrong.schema"}), lambda host, defect: None),
        (lambda host, defect: host["energy_zero"].update({"fermi_subtracted": True}), lambda host, defect: None),
        (lambda host, defect: host["cube"].update({"shape": [2, 2, 1]}), lambda host, defect: None),
        (lambda host, defect: host["cube"].update({"origin_bohr": [0.1, 0.0, 0.0]}), lambda host, defect: None),
        (lambda host, defect: host["cube"].update({"step_vectors_bohr": [[1.0, 0.1, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]}), lambda host, defect: None),
        (lambda host, defect: host["cube"].update({"cell_bohr": [[2.1, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]]}), lambda host, defect: None),
        (lambda host, defect: None, lambda host, defect: defect["cube"].update({"values_eV": [0.0] * 8})),
        (lambda host, defect: None, lambda host, defect: defect["cube"].update({"axis_order": "z_outer_y_middle_x_inner"})),
    ],
    ids=[
        "value_unit",
        "geometry_unit",
        "kind",
        "sign_convention",
        "schema",
        "energy_zero",
        "shape",
        "origin",
        "step_vectors",
        "cell",
        "value_conversion",
        "axis_order",
    ],
)
def test_rejects_potential_contract_mismatches(
    mutate_host: Callable[[dict[str, Any], dict[str, Any]], None],
    mutate_defect: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    host = _potential([0.0] * 8)
    defect = _potential(
        [0.1] * 8,
        task_id="software-defect-task",
        scheduler_job_id="software-job-121",
        study_id="software-defect-study",
        model_id="czo-defect-model",
    )
    mutate_host(host, defect)
    mutate_defect(host, defect)

    with pytest.raises((ValueError, KeyError)):
        potential_alignment.calculate_regional_potential_difference(
            host, defect, _selection([((0, 0, 0), (2, 2, 2))])
        )


@pytest.mark.parametrize(
    "selection",
    [
        {"kind": "index_boxes", "boxes": [], "reason": "empty", "source": "test"},
        {"kind": "index_boxes", "boxes": [{"lower": [-1, 0, 0], "upper": [1, 1, 1]}], "reason": "negative", "source": "test"},
        {"kind": "index_boxes", "boxes": [{"lower": [0, 0, 0], "upper": [3, 1, 1]}], "reason": "outside", "source": "test"},
        {"kind": "index_boxes", "boxes": [{"lower": [1, 0, 0], "upper": [1, 1, 1]}], "reason": "empty", "source": "test"},
        {"kind": "index_boxes", "boxes": [{"lower": [0.0, 0, 0], "upper": [1, 1, 1]}], "reason": "noninteger", "source": "test"},
        {"kind": "cartesian_boxes", "boxes": [{"lower": [0, 0, 0], "upper": [1, 1, 1]}], "reason": "wrong kind", "source": "test"},
    ],
    ids=["empty", "negative", "outside", "zero-volume", "noninteger", "wrong-kind"],
)
def test_rejects_invalid_index_box_selection(selection: dict[str, Any]) -> None:
    host = _potential([0.0] * 8)
    defect = _potential([0.1] * 8, task_id="software-defect-task", scheduler_job_id="software-job-121", study_id="software-defect-study", model_id="czo-defect-model")

    with pytest.raises((ValueError, KeyError)):
        potential_alignment.calculate_regional_potential_difference(host, defect, selection)


def _source_files(root: Path, task_id: str) -> dict[str, str]:
    directory = root / task_id
    native = directory / "OUT.ContractSCF"
    paths = {
        "task.json": str(directory / "task.json"),
        "result.json": str(directory / "result.json"),
        "method.json": str(directory / "method.json"),
        "model.json": str(directory / "model.json"),
        "Study": str(directory / "study.json"),
        "INPUT": str(directory / "INPUT"),
        "OUT.INPUT": str(native / "INPUT"),
        "KPT": str(directory / "KPT"),
        "STRU": str(directory / "STRU"),
        "STRU.atom-map.json": str(directory / "STRU.atom-map.json"),
        "running_scf.log": str(native / "running_scf.log"),
        "istate.info": str(native / "istate.info"),
        "kpoints": str(native / "kpoints"),
        "ElecStaticPot.cube": str(native / "ElecStaticPot.cube"),
    }
    for path in paths.values():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("software_contract_only\n", encoding="utf-8")
    return paths


def _method_for_pair(model_id: str, version: str, method_set: str, *, net_charge: int = 0) -> dict[str, Any]:
    return {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "abacus_version_target": "3.10.1",
        "model_id": model_id,
        "version": version,
        "method_set": method_set,
        "basis_type": "pw",
        "dft_functional": "PBE",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "element_order": ["Ca", "Zr", "O"],
        "initial_moments_muB_by_element": {"Ca": 0.0, "Zr": 0.0, "O": 0.0},
        "pseudopotential_ids": {"Ca": "Ca-NC", "Zr": "Zr-NC", "O": "O-NC"},
        "pseudopotential_metadata": {"Ca": {"type": "NC"}, "Zr": {"type": "NC"}, "O": {"type": "NC"}},
        "pseudopotential_treatment": "norm_conserving",
        "ks_solver": "dav",
        "kpoints": [1, 1, 1],
        "kpoint_rule": "Gamma",
        "kpoint_shift": [0.0, 0.0, 0.0],
        "mixing_type": "plain",
        "symmetry": False,
        "pw_diag_thr": 1e-5,
        "berry": False,
        "parameters": {"smearing_sigma_Ry": 0.01},
        "smearing_method": "fixed",
        "net_charge": net_charge,
        "suffix": "ContractSCF",
    }


def _pair_fixture(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, Path]]:
    source_root = tmp_path / "native-source-placeholders"
    host_task = "software-host-task"
    defect_task = "software-defect-task"
    host_files = _source_files(source_root, host_task)
    defect_files = _source_files(source_root, defect_task)
    host_model_path = source_root / host_task / "model"
    defect_model_path = source_root / defect_task / "model"
    host_model_path.mkdir(parents=True, exist_ok=True)
    defect_model_path.mkdir(parents=True, exist_ok=True)
    host_model_json = host_model_path / "model.json"
    defect_model_json = defect_model_path / "model.json"
    host_model_json.write_text("software_contract_only\n", encoding="utf-8")
    defect_model_json.write_text("software_contract_only\n", encoding="utf-8")
    host_files["model.json"] = str(host_model_json)
    defect_files["model.json"] = str(defect_model_json)

    cell = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]
    atoms = [
        {"atom_id": 0, "element": "Ca", "cart_coords_angstrom": [0.0, 0.0, 0.0]},
        {"atom_id": 1, "element": "O", "cart_coords_angstrom": [2.0, 2.0, 2.0]},
    ]
    lineage = [
        {"child_atom_id": 0, "element": "Ca", "parent_atom_id": 0, "kind": "retained_parent_atom", "parent_image": [0, 0, 0]},
        {"child_atom_id": 1, "element": "O", "parent_atom_id": 1, "kind": "retained_parent_atom", "parent_image": [0, 0, 0]},
    ]
    host_model = {
        "model_id": "czo-host-model",
        "version": "v001",
        "path": str(host_model_path),
        "metadata_file": str(host_model_json),
        "atom_ids": [0, 1],
        "cell_angstrom": cell,
        "atoms": atoms,
        "atom_lineage": lineage,
    }
    defect_model = {
        "model_id": "czo-defect-model",
        "version": "v001",
        "path": str(defect_model_path),
        "metadata_file": str(defect_model_json),
        "atom_ids": [0, 1],
        "cell_angstrom": cell,
        "atoms": atoms,
        "atom_lineage": lineage,
    }
    host_method = _method_for_pair("czo-host-model", "v001", "abacus-contract-scf")
    defect_method = _method_for_pair("czo-defect-model", "v001", "abacus-contract-scf", net_charge=1)
    host = {
        "schema": REFERENCE_SCHEMA,
        "role": "host",
        "status": "sampled_host_reference_unaligned",
        "task_id": host_task,
        "task_path": str(source_root / host_task),
        "native_job": {"scheduler_job_id": "software-job-205", "scheduler_state": "COMPLETED", "exit_code": "0:0", "runner": "slurm"},
        "study": {"study_id": "software-host-study", "source_file": host_files["Study"]},
        "model": host_model,
        "parent_model": None,
        "defect_descriptor": None,
        "atom_map": {"source_file": host_files["STRU.atom-map.json"], "record": {"model_id": "czo-host-model", "version": "v001", "source_atom_ids": [0, 1]}},
        "method": host_method,
        "conditions": {"cell_constraint": "fixed_cell", "net_charge": 0, "calculation": "scf"},
        "charge": {"q": 0, "convention": "q_positive_removes_electrons"},
        "levels": {"unit": "eV", "vbm_eV": -2.5, "cbm_eV": 1.0},
        "parent_total_energy_provenance": {"value_eV": -10.0, "definition": "software contract total energy", "original_field": "parent_energy_zero_eV", "is_potential_zero": False},
        "source_files": host_files,
        "electronic_source": {"evidence_kind": "software_contract_only", "source_files": host_files},
        "scientific_qualification": False,
        "production_qualification": False,
    }
    defect = {
        "schema": REFERENCE_SCHEMA,
        "role": "defect",
        "status": "sampled_defect_levels_unaligned",
        "task_id": defect_task,
        "task_path": str(source_root / defect_task),
        "native_job": {"scheduler_job_id": "software-job-121", "scheduler_state": "COMPLETED", "exit_code": "0:0", "runner": "slurm"},
        "study": {"study_id": "software-defect-study", "source_file": defect_files["Study"]},
        "model": defect_model,
        "parent_model": {"model_id": "czo-host-model", "version": "v001", "path": str(host_model_path)},
        "defect_descriptor": {
            "kind": "explicit_defect_sequence",
            "model_id": "czo-defect-model",
            "version": "v001",
            "charge_state": 1,
            "composition_parent": {"Ca": 1, "O": 1},
            "composition_child": {"Ca": 1, "O": 1},
            "composition_delta": {},
            "operations": [],
        },
        "atom_map": {"source_file": defect_files["STRU.atom-map.json"], "record": {"model_id": "czo-defect-model", "version": "v001", "source_atom_ids": [0, 1]}},
        "method": defect_method,
        "conditions": {"cell_constraint": "fixed_cell", "net_charge": 1, "calculation": "scf"},
        "charge": {"q": 1, "convention": "q_positive_removes_electrons"},
        "levels": {"unit": "eV", "vbm_eV": -2.0, "cbm_eV": 1.2},
        "parent_total_energy_provenance": {"value_eV": -9.0, "definition": "software contract total energy", "original_field": "parent_energy_zero_eV", "is_potential_zero": False},
        "source_files": defect_files,
        "electronic_source": {"evidence_kind": "software_contract_only", "source_files": defect_files},
        "scientific_qualification": False,
        "production_qualification": False,
    }
    pair = {
        "schema": PAIR_SCHEMA,
        "status": "matching_recorded_fields_unaligned",
        "host": host,
        "defect": defect,
        "descriptor_path": str(defect_model_json),
        "method_comparison": {
            "same_recorded_comparison_fields": True,
            "scope": "listed saved fields only; software contract fixture",
            "physical_differences": {},
            "numerical_differences": {},
        },
        "energy_reference": "each source retains its native sampled KS levels; no common potential zero established",
        "scientific_qualification": False,
        "production_qualification": False,
    }
    paths = {
        "host_electronic": tmp_path / "host-electronic.json",
        "defect_electronic": tmp_path / "defect-electronic.json",
        "descriptor": defect_model_json,
    }
    for path in paths.values():
        if path == defect_model_json:
            continue
        _write_json(path, {"schema": "software_contract_only"})
    potential_paths = {
        "host": tmp_path / "host-potential.json",
        "defect": tmp_path / "defect-potential.json",
    }
    return pair, paths, potential_paths


def _write_wrapper_fixture(
    tmp_path: Path,
    *,
    include_defect_potential: bool = True,
    selection: dict[str, Any] | None = None,
    bad_host_binding: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    pair, paths, potential_paths = _pair_fixture(tmp_path)
    steps_bohr = [
        [2.0 / BOHR_TO_ANGSTROM, 0.0, 0.0],
        [0.0, 2.0 / BOHR_TO_ANGSTROM, 0.0],
        [0.0, 0.0, 2.0 / BOHR_TO_ANGSTROM],
    ]
    host_potential = _potential(
        [0.0] * 8,
        task_id="wrong-host-task" if bad_host_binding else "software-host-task",
        scheduler_job_id="wrong-job" if bad_host_binding else "software-job-205",
        study_id="software-host-study",
        model_id="czo-host-model",
        steps_bohr=steps_bohr,
    )
    defect_potential = _potential(
        [1.0 / RY_TO_EV] * 8,
        task_id="software-defect-task",
        scheduler_job_id="software-job-121",
        study_id="software-defect-study",
        model_id="czo-defect-model",
        steps_bohr=steps_bohr,
        net_charge=1,
    )
    host_potential["source_files"] = pair["host"]["source_files"]
    defect_potential["source_files"] = pair["defect"]["source_files"]
    host_potential["atom_map"] = copy.deepcopy(pair["host"]["atom_map"]["record"])
    defect_potential["atom_map"] = copy.deepcopy(pair["defect"]["atom_map"]["record"])
    host_potential["mapped_atoms"] = [
        {"atom_id": 0, "element": "Ca", "position_angstrom": [0.0, 0.0, 0.0]},
        {"atom_id": 1, "element": "O", "position_angstrom": [2.0, 2.0, 2.0]},
    ]
    defect_potential["mapped_atoms"] = copy.deepcopy(host_potential["mapped_atoms"])
    host_potential["cube"]["source_file"] = host_potential["source_files"]["ElecStaticPot.cube"]
    defect_potential["cube"]["source_file"] = defect_potential["source_files"]["ElecStaticPot.cube"]
    _write_json(potential_paths["host"], host_potential)
    if include_defect_potential:
        _write_json(potential_paths["defect"], defect_potential)
    request = {
        "schema": "mlcc.potential-alignment-request.v1",
        "alignment_id": "software-contract-alignment",
        "host_electronic_path": paths["host_electronic"].name,
        "defect_electronic_path": paths["defect_electronic"].name,
        "descriptor_path": paths["descriptor"].relative_to(tmp_path).as_posix(),
        "host_potential_path": potential_paths["host"].name,
        "defect_potential_path": potential_paths["defect"].name if include_defect_potential else None,
        "selection": selection,
    }
    request_path = _write_json(tmp_path / "request.json", request)
    return request, pair, request_path


def test_build_reports_missing_grid_and_selection_without_fabricating_zero_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, pair, request_path = _write_wrapper_fixture(tmp_path, include_defect_potential=False, selection=None)
    monkeypatch.setattr(
        potential_alignment,
        "build_defect_electronic_reference",
        lambda *args: copy.deepcopy(pair),
    )

    result = potential_alignment.build_potential_alignment(request_path)

    assert result["status"] == "missing_inputs"
    assert set(result["missing"]) == {"defect_potential", "selection"}
    assert result["difference"] is None
    assert result["candidate_host_vbm_on_defect_gauge_eV"] is None
    assert result["evidence_kind"] == "software_contract_only"


def test_wrapper_rejects_provided_host_potential_binding_before_missing_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, pair, request_path = _write_wrapper_fixture(tmp_path, include_defect_potential=False, selection=None, bad_host_binding=True)
    monkeypatch.setattr(
        potential_alignment,
        "build_defect_electronic_reference",
        lambda *args: copy.deepcopy(pair),
    )

    with pytest.raises(ValueError):
        potential_alignment.build_potential_alignment(request_path)


def test_wrapper_rejects_complete_pair_with_unmatched_recorded_method_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _selection([((0, 0, 0), (2, 2, 2))])
    _, pair, request_path = _write_wrapper_fixture(tmp_path, selection=selection)
    pair["method_comparison"]["same_recorded_comparison_fields"] = False
    monkeypatch.setattr(
        potential_alignment,
        "build_defect_electronic_reference",
        lambda *args: copy.deepcopy(pair),
    )

    with pytest.raises(ValueError):
        potential_alignment.build_potential_alignment(request_path)


@pytest.mark.parametrize("mutation", ["parent_id", "composition_delta"], ids=["lineage-parent-id", "descriptor-delta"])
def test_wrapper_rejects_tampered_defect_lineage_or_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    selection = _selection([((0, 0, 0), (2, 2, 2))])
    _, pair, request_path = _write_wrapper_fixture(tmp_path, selection=selection)
    if mutation == "parent_id":
        pair["defect"]["model"]["atom_lineage"][0]["parent_atom_id"] = 1
    else:
        pair["defect"]["defect_descriptor"]["composition_delta"] = {"O": 1}
    monkeypatch.setattr(
        potential_alignment,
        "build_defect_electronic_reference",
        lambda *args: copy.deepcopy(pair),
    )

    with pytest.raises(ValueError):
        potential_alignment.build_potential_alignment(request_path)


def test_complete_software_alignment_preserves_candidate_vbm_and_null_legacy_corrections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _selection([((0, 0, 0), (2, 2, 2))])
    _, pair, request_path = _write_wrapper_fixture(tmp_path, include_defect_potential=True, selection=selection)
    monkeypatch.setattr(
        potential_alignment,
        "build_defect_electronic_reference",
        lambda *args: copy.deepcopy(pair),
    )

    result = potential_alignment.build_potential_alignment(request_path)
    output_path = tmp_path / "software-alignment.json"
    _write_json(output_path, result)

    assert output_path.is_file()
    assert result["status"] == "computed_regional_difference_unqualified"
    assert result["difference"]["delta_v_defect_minus_host_eV"] == pytest.approx(1.0)
    assert result["candidate_host_vbm_on_defect_gauge_eV"] == pytest.approx(-1.5)
    assert result["evidence_kind"] == "software_contract_only"
    assert result["missing"] == []
    assert result["native_alignment_accepted"] is False
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False
    for key in (
        "potential_alignment_eV",
        "aligned_host_vbm_eV",
        "correction_terms",
        "FNV_eFNV_correction_eV",
        "charged_formation_energy_eV",
    ):
        assert result[key] is None
    assert result["references"] == pair


def test_complete_software_vacancy_preserves_explicit_atom_count_and_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _selection([((0, 0, 0), (2, 2, 2))])
    _, pair, request_path = _write_wrapper_fixture(tmp_path, selection=selection)
    defect_model = pair["defect"]["model"]
    defect_model["atom_ids"] = [0]
    defect_model["atoms"] = [copy.deepcopy(defect_model["atoms"][0])]
    defect_model["atom_lineage"] = [
        {
            "child_atom_id": 0,
            "element": "Ca",
            "parent_atom_id": 0,
            "kind": "retained_parent_atom",
            "parent_image": [0, 0, 0],
        }
    ]
    pair["defect"]["defect_descriptor"]["composition_child"] = {"Ca": 1}
    pair["defect"]["defect_descriptor"]["composition_delta"] = {"O": -1}
    pair["defect"]["defect_descriptor"]["operations"] = [
        {"kind": "vacancy", "atom_id": 1, "element": "O"},
    ]
    pair["defect"]["atom_map"]["record"]["source_atom_ids"] = [0]
    defect_path = request_path.parent / "defect-potential.json"
    defect_potential = json.loads(defect_path.read_text(encoding="utf-8"))
    defect_potential["atom_map"] = copy.deepcopy(pair["defect"]["atom_map"]["record"])
    defect_potential["mapped_atoms"] = [
        {"atom_id": 0, "element": "Ca", "position_angstrom": [0.0, 0.0, 0.0]},
    ]
    _write_json(defect_path, defect_potential)
    monkeypatch.setattr(
        potential_alignment,
        "build_defect_electronic_reference",
        lambda *args: copy.deepcopy(pair),
    )

    result = potential_alignment.build_potential_alignment(request_path)

    assert result["status"] == "computed_regional_difference_unqualified"
    assert result["lineage"]["composition_parent"] == {"Ca": 1, "O": 1}
    assert result["lineage"]["composition_child"] == {"Ca": 1}
    assert result["lineage"]["composition_delta"] == {"O": -1}
    assert result["lineage"]["defect_charge_q"] == 1

