"""Focused arithmetic checks for the P5 ordered SCF-energy path.

The arithmetic cases are mathematical inputs to the private helper.  The
wrapper cases use temporary JSON and ABACUS input files marked
``software_contract_only``; they are source-binding fixtures, never native DFT
evidence.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mlcc.abacus import _energy_definition
from mlcc.polarization_energy import _energy_summary, analyze_polarization_energy_path


def _point(
    point_id: str,
    coordinate: float,
    energy_eV_cell: float,
    task_id: str,
    scheduler_job_id: str,
) -> dict[str, object]:
    return {
        "point_id": point_id,
        "coordinate": coordinate,
        "energy_eV_cell": energy_eV_cell,
        "task_id": task_id,
        "native_job": {"scheduler_job_id": scheduler_job_id},
    }


def test_energy_summary_returns_relative_energies_endpoint_and_sampled_maximum():
    points = [
        _point("p-minus", -1.0, -10.0, "task-minus", "177"),
        _point("p-zero", 0.0, -8.5, "task-zero", "179"),
        _point("p-plus", 1.0, -9.5, "task-plus", "178"),
    ]

    result = _energy_summary(points, "p-minus")

    assert result["reference_point_id"] == "p-minus"
    assert [point["point_id"] for point in result["points"]] == ["p-minus", "p-zero", "p-plus"]
    assert [point["coordinate"] for point in result["points"]] == [-1.0, 0.0, 1.0]
    assert [point["energy_eV_cell"] for point in result["points"]] == [-10.0, -8.5, -9.5]
    assert [point["relative_energy_eV_cell"] for point in result["points"]] == [0.0, 1.5, 0.5]
    assert result["points"][1]["task_id"] == "task-zero"
    assert result["points"][1]["native_job"] == {"scheduler_job_id": "179"}
    assert result["endpoint_difference_eV_cell"] == pytest.approx(0.5)
    assert result["sampled_maximum"]["energy_eV_cell"] == pytest.approx(-8.5)
    assert result["sampled_maximum"]["relative_energy_eV_cell"] == pytest.approx(1.5)
    assert result["sampled_maximum"]["point_ids"] == ["p-zero"]
    assert result["sampled_maximum"]["coordinates"] == [0.0]
    assert result["sampled_maximum"]["sources"] == [
        {"point_id": "p-zero", "task_id": "task-zero", "native_job": {"scheduler_job_id": "179"}}
    ]


def test_energy_summary_preserves_all_tied_sampled_maximum_sources():
    points = [
        _point("left", -1.0, 2.0, "task-left", "201"),
        _point("reference", 0.0, 1.0, "task-reference", "202"),
        _point("right", 1.0, 2.0, "task-right", "203"),
    ]

    result = _energy_summary(points, "reference")

    assert result["reference_point_id"] == "reference"
    assert [point["relative_energy_eV_cell"] for point in result["points"]] == [1.0, 0.0, 1.0]
    assert result["endpoint_difference_eV_cell"] == pytest.approx(0.0)
    assert result["sampled_maximum"]["energy_eV_cell"] == pytest.approx(2.0)
    assert result["sampled_maximum"]["relative_energy_eV_cell"] == pytest.approx(1.0)
    assert result["sampled_maximum"]["point_ids"] == ["left", "right"]
    assert result["sampled_maximum"]["coordinates"] == [-1.0, 1.0]
    assert result["sampled_maximum"]["sources"] == [
        {"point_id": "left", "task_id": "task-left", "native_job": {"scheduler_job_id": "201"}},
        {"point_id": "right", "task_id": "task-right", "native_job": {"scheduler_job_id": "203"}},
    ]


def test_energy_summary_uses_declared_reference_even_when_not_first_point():
    points = [
        _point("p0", -2.0, 5.0, "task-0", "210"),
        _point("p1", -1.0, 3.0, "task-1", "211"),
        _point("p2", 0.0, 4.0, "task-2", "212"),
    ]

    result = _energy_summary(points, "p1")

    assert [point["relative_energy_eV_cell"] for point in result["points"]] == [2.0, 0.0, 1.0]
    assert result["endpoint_difference_eV_cell"] == pytest.approx(-1.0)
    assert result["sampled_maximum"]["point_ids"] == ["p0"]
    assert result["sampled_maximum"]["coordinates"] == [-2.0]


def test_energy_summary_rejects_unknown_reference_point():
    points = [
        _point("p0", 0.0, 0.0, "task-0", "220"),
        _point("p1", 1.0, 1.0, "task-1", "221"),
    ]

    with pytest.raises((KeyError, ValueError), match="reference"):
        _energy_summary(points, "missing")


def test_energy_summary_rejects_duplicate_point_ids():
    points = [
        _point("duplicate", 0.0, 0.0, "task-0", "230"),
        _point("duplicate", 1.0, 1.0, "task-1", "231"),
    ]

    with pytest.raises(ValueError, match="point_id|duplicate"):
        _energy_summary(points, "duplicate")


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fixture_method(model_id: str) -> dict[str, object]:
    elements = ["Ca", "Zr", "O"]
    return {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "stage": "scf",
        "model_id": model_id,
        "version": "v001",
        "suffix": "EnergyFixture",
        "device": "gpu",
        "dft_functional": "PBE",
        "basis_type": "pw",
        "ks_solver": "cg",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "initial_moments_muB_by_element": {element: 0 for element in elements},
        "occupations": "fixed",
        "smearing_method": None,
        "mixing_type": "broyden",
        "relax_method": "cg",
        "symmetry": -1,
        "net_charge": 0,
        "nelec": 0,
        "nelec_delta": 0,
        "charge_convention": "positive q removes q electrons",
        "element_order": elements,
        "kpoints": [2, 2, 2],
        "kpoint_rule": "explicit_mesh",
        "kpoint_shift": [0.0, 0.0, 0.0],
        "pw_diag_thr": 0.01,
        "parameters": {
            "ecutwfc_Ry": 100,
            "scf_thr": 0.0001,
            "scf_nmax": 100,
            "nbands": 6,
            "smearing_sigma_Ry": None,
            "mixing_beta": 0.3,
            "force_thr_eV_per_A": None,
            "relax_nmax": None,
        },
        "pseudopotentials": {
            element: {"filename": f"{element}.upf", "source": f"software_contract_only/{element}.upf"}
            for element in elements
        },
        "science": {
            "suffix": "EnergyFixture",
            "dft_functional": "PBE",
            "nspin": 1,
            "initial_moments_muB_by_element": {element: 0 for element in elements},
            "occupations": "fixed",
            "smearing_method": None,
            "mixing_type": "broyden",
            "relax_method": "cg",
            "symmetry": -1,
            "lspinorb": False,
            "noncolin": False,
        },
        "execution": {"device": "gpu", "ks_solver": "cg"},
        "stress_convention": {"unit": "GPa", "sign": "software_contract_only"},
        "berry": {
            "schema": "mlcc.abacus-berry.v1",
            "role": "reference_scf",
            "berry_phase": 0,
            "symmetry": -1,
            "pw_diag_thr": None,
            "out_chg": 1,
            "nspin": 1,
            "lspinorb": False,
            "noncolin": False,
            "occupations": "fixed",
            "kpar": 1,
        },
        "method_set": "software-energy-method-v001",
        "parent_method_set": "software-parent-method-v001",
        "source_configuration": "software_contract_only",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "pseudopotential_ids": {element: f"{element}-fixture" for element in elements},
        "pseudopotential_metadata": {element: {"element": element, "functional": "PBE"} for element in elements},
        "pseudopotential_treatment": {element: "software_contract_only" for element in elements},
    }


def _input_text() -> str:
    return """INPUT_PARAMETERS
suffix EnergyFixture
pseudo_dir ./
calculation scf
device gpu
dft_functional PBE
basis_type pw
ks_solver cg
ecutwfc 100
scf_thr 0.0001
scf_nmax 100
nbands 6
nspin 1
lspinorb 0
noncolin 0
mixing_type broyden
mixing_beta 0.3
symmetry -1
cal_force 1
cal_stress 1
smearing_method fixed
out_chg 1
kpar 1
pw_diag_thr 0.01
nelec 0
nelec_delta 0
berry_phase 0
"""


def _native_input_text() -> str:
    return """INPUT_PARAMETERS
suffix EnergyFixture
pseudo_dir ./
calculation scf
device gpu
dft_functional PBE
basis_type pw
ks_solver cg
ecutwfc 100
scf_thr 0.0001
scf_nmax 100
nbands 6
nspin 1
lspinorb 0
noncolin 0
mixing_type broyden
mixing_beta 0.3
symmetry -1
cal_force 1
cal_stress 1
smearing_method fixed
out_chg 1
kpar 1
pw_diag_thr 0.01
nelec 0
nelec_delta 0
berry_phase 0
scf_thr_type 1
efield_flag 0
dip_cor_flag 0
gate_flag 0
dft_plus_u 0
vdw_method none
"""


def _write_software_energy_fixture(tmp_path: Path) -> dict[str, object]:
    parent_model_dir = tmp_path / "models" / "parent"
    parent_study_file = tmp_path / "studies" / "parent.json"
    cell = [[6.0, 0.0, 0.0], [0.0, 6.0, 0.0], [0.0, 0.0, 6.0]]
    atoms = [
        {"atom_id": 0, "element": "Ca", "cart_coords_angstrom": [0.0, 0.0, 0.0]},
        {"atom_id": 1, "element": "Zr", "cart_coords_angstrom": [2.0, 2.0, 2.0]},
        {"atom_id": 2, "element": "O", "cart_coords_angstrom": [4.0, 4.0, 4.0]},
    ]
    parent_model = {
        "schema": "mlcc.model.v1",
        "model_id": "software-parent-model",
        "version": "v001",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "evidence_kind": "software_contract_only",
        "composition": {"Ca": 1, "Zr": 1, "O": 1},
        "atom_ids": [0, 1, 2],
        "atoms": atoms,
        "lattice_angstrom": cell,
        "pbc": [True, True, True],
    }
    parent_model_dir.mkdir(parents=True, exist_ok=True)
    _write_json(parent_model_dir / "model.json", parent_model)
    _write_json(
        parent_study_file,
        {
            "study_id": "software-parent-study",
            "model": {"model_id": "software-parent-model", "version": "v001"},
        },
    )

    point_records: dict[str, dict[str, Path]] = {}
    request_points: list[dict[str, object]] = []
    for name, coordinate, energy, scheduler_job_id in (
        ("minus", -1.0, -10.0, "177"),
        ("plus", 1.0, -9.0, "178"),
    ):
        model_id = f"software-child-{name}"
        study_id = f"software-child-study-{name}"
        model_dir = tmp_path / "models" / name
        study_file = tmp_path / "studies" / f"{name}.json"
        task_dir = tmp_path / "tasks" / name
        native_dir = task_dir / "OUT.EnergyFixture"
        native_dir.mkdir(parents=True, exist_ok=True)
        lineage = [
            {
                "child_atom_id": atom["atom_id"],
                "parent_atom_id": atom["atom_id"],
                "element": atom["element"],
                "parent_image": [0, 0, 0],
            }
            for atom in atoms
        ]
        model = {
            **copy.deepcopy(parent_model),
            "model_id": model_id,
            "parent_model": {
                "model_id": "software-parent-model",
                "version": "v001",
                "path": str(parent_model_dir.resolve()),
            },
            "parent_study_id": "software-parent-study",
            "atom_lineage": lineage,
        }
        _write_json(model_dir / "model.json", model)
        _write_json(
            study_file,
            {
                "study_id": study_id,
                "model": {"model_id": model_id, "version": "v001"},
                "parent_study_id": "software-parent-study",
            },
        )
        method = _fixture_method(model_id)
        _write_json(task_dir / "method.json", method)
        (task_dir / "INPUT").write_text(_input_text(), encoding="utf-8")
        (native_dir / "INPUT").write_text(_native_input_text(), encoding="utf-8")
        (task_dir / "KPT").write_text("K_POINTS\n0\nGamma\n2 2 2 0 0 0\n", encoding="utf-8")
        (native_dir / "running_scf.log").write_text("software_contract_only\n", encoding="utf-8")
        atom_map = {
            "schema": "mlcc.abacus-atom-map.v1",
            "abacus_version_target": "3.10.1",
            "model_id": model_id,
            "version": "v001",
            "source_atom_ids": [0, 1, 2],
            "element_order": ["Ca", "Zr", "O"],
            "abacus_order": [
                {"abacus_index": i, "source_index": i, "atom_id": i, "element": atom["element"], "label": f"{atom['element']}{i + 1}"}
                for i, atom in enumerate(atoms)
            ],
        }
        _write_json(task_dir / "STRU.atom-map.json", atom_map)
        task_file = task_dir / "task.json"
        result_file = task_dir / "result.json"
        source_files = {
            "running_scf.log": str((native_dir / "running_scf.log").resolve()),
            "INPUT": str((task_dir / "INPUT").resolve()),
            "method.json": str((task_dir / "method.json").resolve()),
            "STRU.atom-map.json": str((task_dir / "STRU.atom-map.json").resolve()),
        }
        task = {
            "task_id": f"software-energy-{name}-scf",
            "study_id": study_id,
            "case_id": "software_cazro3",
            "case_role": "software_contract_only",
            "engine": "abacus",
            "engine_version": "3.10.1",
            "calculation": "scf",
            "model_id": model_id,
            "model_version": "v001",
            "model_path": str(model_dir.resolve()),
            "study_file": str(study_file.resolve()),
            "method_set": "software-energy-method-v001",
            "fixture": True,
            "evidence_kind": "software_contract_only",
            "runner": "slurm",
            "scheduler_job_id": scheduler_job_id,
            "scheduler_state": "COMPLETED",
            "status": "COMPLETED",
            "exit_code": "0:0",
            "result_file": str(result_file.resolve()),
            "calculation_conditions": {
                "calculation_kind": "single_point_scf",
                "lattice_temperature_K": None,
                "reference_temperature_K": 0,
                "applied_external_pressure_Pa": None,
                "cell_constraint": "fixed_cell",
                "occupations": "fixed",
                "electronic_smearing_Ry": None,
            },
        }
        result = {
            "schema": "mlcc.abacus-result.v1",
            "task_id": task["task_id"],
            "scheduler_job_id": scheduler_job_id,
            "method_set": "software-energy-method-v001",
            "stage": "scf",
            "energy_eV": energy,
            "energy_unit": "eV",
            "energy_definition": _energy_definition("fixed"),
            "occupations": "fixed",
            "electronic_converged": True,
            "ionic_converged": None,
            "scf_iterations": 4,
            "net_charge": 0,
            "nelec": 0,
            "nelec_delta": 0,
            "final_atoms": {
                "symbols": ["Ca", "Zr", "O"],
                "positions_angstrom": [atom["cart_coords_angstrom"] for atom in atoms],
                "cell_angstrom": cell,
                "pbc": [True, True, True],
            },
            "atom_ids": [0, 1, 2],
            "source_files": source_files,
            "fixture": True,
            "evidence_kind": "software_contract_only",
            "scientific_status": "software_contract_only",
            "scientific_qualification": False,
            "production_qualification": False,
        }
        _write_json(task_file, task)
        _write_json(result_file, result)
        point_records[name] = {"task": task_file, "result": result_file, "method": task_dir / "method.json", "model": model_dir / "model.json", "study": study_file}
        request_points.append(
            {
                "point_id": name,
                "coordinate": coordinate,
                "scf_task_file": task_file.relative_to(tmp_path).as_posix(),
                "scf_result_file": result_file.relative_to(tmp_path).as_posix(),
                "berry_result_file": None,
            }
        )

    request_file = tmp_path / "request.json"
    _write_json(
        request_file,
        {
            "schema": "mlcc.polarization-energy-request.v1",
            "path_id": "software-energy-path-v001",
            "path_basis": "software contract fixed-cell ordered displacement labels",
            "parent_study_file": parent_study_file.relative_to(tmp_path).as_posix(),
            "parent_model_path": parent_model_dir.relative_to(tmp_path).as_posix(),
            "path_coordinate": {"name": "declared_displacement", "unit": "arb"},
            "mechanical_constraint": {"kind": "fixed_cell", "description": "software fixture fixed cell"},
            "reference_point_id": "minus",
            "points": request_points,
        },
    )
    return {"request": request_file, "points": point_records}


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_software_contract_wrapper_accepts_distinct_child_studies_without_berry(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    result = analyze_polarization_energy_path(fixture["request"])

    assert result["schema"] == "mlcc.polarization-energy-path.v1"
    assert result["status"] == "computed_scf_energy_path_unqualified"
    assert result["evidence_kind"] == "software_contract_only"
    assert [point["point_id"] for point in result["points"]] == ["minus", "plus"]
    assert [point["relative_energy_eV_cell"] for point in result["points"]] == [0.0, 1.0]
    assert result["endpoint_difference_eV_cell"] == pytest.approx(1.0)
    assert result["sampled_maximum"]["point_ids"] == ["plus"]
    assert result["sampled_maximum"]["sources"][0]["native_job"]["scheduler_job_id"] == "178"
    assert result["points"][0]["study_id"] != result["points"][1]["study_id"]
    assert result["points"][0]["model_id"] != result["points"][1]["model_id"]
    assert "minus.berry_result" in result["missing"]
    assert "plus.berry_result" in result["missing"]
    assert result["double_well_qualified"] is False
    output_path = tmp_path / "software-energy-path.json"
    _write_json(output_path, result)
    assert _load_json(output_path)["schema"] == "mlcc.polarization-energy-path.v1"


def test_wrapper_rejects_nscf_source(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    task_path = fixture["points"]["plus"]["task"]
    task = _load_json(task_path)
    task["calculation"] = "nscf"
    _write_json(task_path, task)
    with pytest.raises(ValueError, match="SCF|NSCF"):
        analyze_polarization_energy_path(fixture["request"])


def test_wrapper_rejects_electronically_unconverged_source(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    result_path = fixture["points"]["plus"]["result"]
    result = _load_json(result_path)
    result["electronic_converged"] = False
    _write_json(result_path, result)
    with pytest.raises(ValueError, match="unconverged"):
        analyze_polarization_energy_path(fixture["request"])


def test_wrapper_rejects_method_numerical_mismatch(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    method_path = fixture["points"]["plus"]["method"]
    method = _load_json(method_path)
    method["parameters"]["scf_thr"] = 0.0002
    _write_json(method_path, method)
    with pytest.raises(ValueError, match="scf_thr"):
        analyze_polarization_energy_path(fixture["request"])


def test_wrapper_rejects_unknown_native_physical_field(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    input_path = fixture["points"]["plus"]["task"].parent / "INPUT"
    input_path.write_text(input_path.read_text(encoding="utf-8") + "efield_amp 0.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="additional input fields|physical setting"):
        analyze_polarization_energy_path(fixture["request"])


def test_wrapper_rejects_child_lineage_mismatch(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    model_path = fixture["points"]["plus"]["model"]
    model = _load_json(model_path)
    model["atom_lineage"][0]["parent_atom_id"] = 1
    _write_json(model_path, model)
    with pytest.raises(ValueError, match="lineage"):
        analyze_polarization_energy_path(fixture["request"])


def test_wrapper_rejects_child_cell_mismatch(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    model_path = fixture["points"]["plus"]["model"]
    model = _load_json(model_path)
    model["lattice_angstrom"][0][0] = 6.1
    _write_json(model_path, model)
    with pytest.raises(ValueError, match="fixed cell|geometry"):
        analyze_polarization_energy_path(fixture["request"])


def test_wrapper_rejects_result_source_binding_mismatch(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    result_path = fixture["points"]["plus"]["result"]
    result = _load_json(result_path)
    result["source_files"]["INPUT"] = str(fixture["points"]["minus"]["task"].parent / "INPUT")
    _write_json(result_path, result)
    with pytest.raises(ValueError, match="source INPUT|source .*differs"):
        analyze_polarization_energy_path(fixture["request"])


def test_wrapper_rejects_non_fixed_cell_request(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    request_path = fixture["request"]
    request = _load_json(request_path)
    request["mechanical_constraint"]["kind"] = "neb"
    _write_json(request_path, request)
    with pytest.raises(ValueError, match="fixed-cell|fixed cell|NEB"):
        analyze_polarization_energy_path(request_path)


@pytest.mark.parametrize("path_key", ["path", "model_path"])
def test_wrapper_rejects_parent_study_model_path_mismatch(tmp_path, path_key):
    fixture = _write_software_energy_fixture(tmp_path)
    study_path = tmp_path / "studies" / "parent.json"
    study = _load_json(study_path)
    study.setdefault("model", {})[path_key] = str((tmp_path / "wrong-parent-model").resolve())
    _write_json(study_path, study)

    with pytest.raises(ValueError, match="Study declared model path"):
        analyze_polarization_energy_path(fixture["request"])


@pytest.mark.parametrize("path_key", ["path", "model_path"])
def test_wrapper_rejects_child_study_model_path_mismatch(tmp_path, path_key):
    fixture = _write_software_energy_fixture(tmp_path)
    study_path = fixture["points"]["plus"]["study"]
    study = _load_json(study_path)
    study.setdefault("model", {})[path_key] = str((tmp_path / "wrong-child-model").resolve())
    _write_json(study_path, study)

    with pytest.raises(ValueError, match="Study declared model path"):
        analyze_polarization_energy_path(fixture["request"])


def _mark_software_fixture_without_evidence_kind(path: Path) -> None:
    record = _load_json(path)
    record.pop("evidence_kind", None)
    record["fixture"] = True
    record["fixture_purpose"] = "software_contract_only"
    _write_json(path, record)


def test_wrapper_accepts_fixture_markers_without_evidence_kind(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    _mark_software_fixture_without_evidence_kind(tmp_path / "models" / "parent" / "model.json")
    _mark_software_fixture_without_evidence_kind(tmp_path / "studies" / "parent.json")
    for point in fixture["points"].values():
        for key in ("task", "result", "method", "model", "study"):
            _mark_software_fixture_without_evidence_kind(point[key])

    result = analyze_polarization_energy_path(fixture["request"])

    assert result["evidence_kind"] == "software_contract_only"
    for point in result["points"]:
        assert point["evidence_kind"] == "software_contract_only"
        for flags in point["original_qualification_flags"].values():
            assert flags["fixture"] is True
            assert flags["fixture_purpose"] == "software_contract_only"
            assert flags["evidence_kind"] is None
    for flags in result["parent_original_qualification_flags"].values():
        assert flags["fixture"] is True
        assert flags["fixture_purpose"] == "software_contract_only"
        assert flags["evidence_kind"] is None


def test_wrapper_accepts_periodic_equivalent_saved_final_position(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    result_path = fixture["points"]["plus"]["result"]
    result = _load_json(result_path)
    result["final_atoms"]["positions_angstrom"][0][0] += 6.0
    _write_json(result_path, result)

    output = analyze_polarization_energy_path(fixture["request"])

    assert output["status"] == "computed_scf_energy_path_unqualified"
    assert [point["relative_energy_eV_cell"] for point in output["points"]] == [0.0, 1.0]


def test_wrapper_accepts_method_set_alias_when_each_source_binds_it(tmp_path):
    fixture = _write_software_energy_fixture(tmp_path)
    alias = "software-energy-method-alias-v009"
    point = fixture["points"]["plus"]
    for key in ("task", "result", "method"):
        record_path = point[key]
        record = _load_json(record_path)
        record["method_set"] = alias
        _write_json(record_path, record)

    output = analyze_polarization_energy_path(fixture["request"])

    assert output["status"] == "computed_scf_energy_path_unqualified"
    assert output["points"][1]["method"]["method_set"] == alias
    assert output["common_method"] == output["points"][0]["common_method"]


@pytest.mark.parametrize("location", ["method", "berry", "parameters", "top_input"])
def test_wrapper_rejects_explicit_pw_diag_thr_mismatch(tmp_path, location):
    fixture = _write_software_energy_fixture(tmp_path)
    point = fixture["points"]["plus"]
    if location == "top_input":
        input_path = point["task"].parent / "INPUT"
        input_path.write_text(
            input_path.read_text(encoding="utf-8").replace("pw_diag_thr 0.01", "pw_diag_thr 0.02"),
            encoding="utf-8",
        )
    else:
        method_path = point["method"]
        method = _load_json(method_path)
        if location == "berry":
            method["berry"]["pw_diag_thr"] = 0.02
        elif location == "parameters":
            method["parameters"]["pw_diag_thr"] = 0.02
        else:
            method["pw_diag_thr"] = 0.02
        _write_json(method_path, method)

    with pytest.raises(ValueError, match="pw_diag_thr"):
        analyze_polarization_energy_path(fixture["request"])


@pytest.mark.parametrize("location", ["berry", "top_input"])
def test_wrapper_rejects_explicit_kpar_mismatch(tmp_path, location):
    fixture = _write_software_energy_fixture(tmp_path)
    point = fixture["points"]["plus"]
    if location == "top_input":
        input_path = point["task"].parent / "INPUT"
        input_path.write_text(
            input_path.read_text(encoding="utf-8").replace("kpar 1", "kpar 2"),
            encoding="utf-8",
        )
    else:
        method_path = point["method"]
        method = _load_json(method_path)
        method["berry"]["kpar"] = 2
        _write_json(method_path, method)

    with pytest.raises(ValueError, match="kpar"):
        analyze_polarization_energy_path(fixture["request"])


@pytest.mark.parametrize("field", ["nelec", "nelec_delta"])
def test_wrapper_rejects_nonzero_task_input_electron_count(tmp_path, field):
    fixture = _write_software_energy_fixture(tmp_path)
    input_path = fixture["points"]["plus"]["task"].parent / "INPUT"
    input_path.write_text(
        input_path.read_text(encoding="utf-8").replace(f"{field} 0", f"{field} 1"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=field):
        analyze_polarization_energy_path(fixture["request"])

