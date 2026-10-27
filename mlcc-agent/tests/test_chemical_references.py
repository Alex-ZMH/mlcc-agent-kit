"""Software-contract tests for the chemical-reference source adapter.

Every task, model, saved electronic record, and native file in this module is
an explicit ``software_contract_only`` fixture.  The files exercise source
binding and normalization; they are not DFT output and must not be used as a
scientific or production qualification result.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from mlcc.chemical_references import (
    assemble_chemical_reference_set,
    build_chemical_reference_set,
    read_chemical_reference,
)


ENERGY_DEFINITION = (
    "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham at fixed occupations in eV"
)


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _source_case(
    root: Path,
    name: str,
    composition: dict[str, int],
    energy: float,
    *,
    method_set: str | None = None,
    nspin: int = 1,
    kpoints: list[int] | None = None,
    nbands: int = 8,
    dft_functional: str = "PBE",
) -> dict[str, Any]:
    """Write a complete saved-source fixture for defect_references binding."""

    root = root / name
    task_path = root / "task"
    model_path = root / "model"
    study_path = root / "study.json"
    task_id = f"software-contract-{name}"
    scheduler_job_id = str(7000 + len(name))
    model_id = f"model-{name}"
    model_version = "v001"
    method_set = method_set or f"method-{name}"
    suffix = "ContractSCF"
    kpoints = list(kpoints or [2, 2, 2])
    elements = list(composition)
    symbols = [element for element, count in composition.items() for _ in range(count)]
    atom_ids = list(range(len(symbols)))
    lattice_size = float(max(8, len(symbols) + 4))
    lattice = [
        [lattice_size, 0.0, 0.0],
        [0.0, lattice_size, 0.0],
        [0.0, 0.0, lattice_size],
    ]
    positions = [[float(index), 0.0, 0.0] for index in atom_ids]
    atoms = [
        {
            "atom_id": index,
            "element": symbol,
            "cart_coords_angstrom": positions[index],
        }
        for index, symbol in enumerate(symbols)
    ]

    pseudopotential_ids = {
        element: f"{element}.NC.PBE.v001" for element in elements
    }
    pseudopotential_metadata = {
        element: {
            "type": "norm_conserving",
            "valence_electrons": 8,
            "relativistic": "scalar",
        }
        for element in elements
    }
    pseudopotential_treatment = {
        element: "scalar_relativistic_norm_conserving" for element in elements
    }

    model = {
        "model_id": model_id,
        "version": model_version,
        "atom_ids": atom_ids,
        "lattice_angstrom": lattice,
        "atoms": atoms,
        "composition": dict(composition),
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    _write_json(model_path / "model.json", model)
    study = {
        "study_id": f"study-{name}",
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
            "net_charge": 0,
        },
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    method = {
        "model_id": model_id,
        "version": model_version,
        "method_set": method_set,
        "suffix": suffix,
        "net_charge": 0,
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "basis_type": "pw",
        "dft_functional": dft_functional,
        "nspin": nspin,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "element_order": elements,
        "initial_moments_muB_by_element": {element: 0.0 for element in elements},
        "pseudopotential_ids": pseudopotential_ids,
        "pseudopotential_metadata": pseudopotential_metadata,
        "pseudopotential_treatment": pseudopotential_treatment,
        "smearing_method": "fixed",
        "ks_solver": "dav",
        "kpoints": kpoints,
        "kpoint_shift": [0, 0, 0],
        "kpoint_rule": "Gamma",
        "mixing_type": "plain",
        "symmetry": "none",
        "parameters": {
            "smearing_sigma_Ry": 0.0,
            "ecutwfc_Ry": 100.0,
            "scf_thr": 1.0e-4,
            "scf_nmax": 100,
            "nbands": nbands,
            "mixing_beta": 0.7,
        },
        "fixture": True,
        "fixture_purpose": "software_contract_only",
    }
    final_atoms = {
        "symbols": symbols,
        "positions_angstrom": positions,
        "cell_angstrom": lattice,
        "pbc": [True, True, True],
    }
    result = {
        "task_id": task_id,
        "scheduler_job_id": scheduler_job_id,
        "method_set": method_set,
        "electronic_converged": True,
        "atom_ids": atom_ids,
        "final_atoms": final_atoms,
        "energy_eV": energy,
        "energy_unit": "eV",
        "energy_definition": ENERGY_DEFINITION,
        "net_charge": 0,
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
    for name_value in ("INPUT", "KPT"):
        (task_path / name_value).write_text(
            "software-contract-only placeholder; no native calculation\n",
            encoding="utf-8",
        )
    native_path = task_path / f"OUT.{suffix}"
    for name_value in ("running_scf.log", "istate.info", "kpoints"):
        native_path.mkdir(parents=True, exist_ok=True)
        (native_path / name_value).write_text(
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
        "schema": "mlcc.abacus-electronic.v001",
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
        "electron_count_q": 0,
        "electron_count_delta": 0,
        "electron_count_neutral": 10.0,
        "electron_count_target": 10.0,
        "electron_count_native": 10.0,
        "vbm_eV": None,
        "cbm_eV": None,
        "sampled_mesh_KS_gap_eV": None,
        "fermi_level_eV": None,
        "vbm_reference": None,
        "fermi_reference": None,
        "gap_status": "unresolved",
        "gap_qualification": {"precision_qualified": False},
        "kpoint_coordinate_system": "fractional",
        "kpoint_mesh": kpoints,
        "kpoint_mesh_shift": [0, 0, 0],
        "parent_energy_zero_eV": energy,
        "parent_energy_zero_definition": ENERGY_DEFINITION,
        "source_files": source_files,
    }
    electronic_path = _write_json(task_path / "electronic.json", electronic)
    return {
        "task_path": task_path,
        "electronic_path": electronic_path,
        "task": task,
        "method": method,
        "result": result,
        "electronic": electronic,
    }


def _reference_spec(
    case: dict[str, Any],
    reference_id: str,
    role: str,
    phase_id: str,
    formula_stoichiometry: dict[str, int],
) -> dict[str, Any]:
    return {
        "reference_id": reference_id,
        "role": role,
        "phase_id": phase_id,
        "phase_selection_source": "software_contract_only explicit declaration",
        "formula_stoichiometry": formula_stoichiometry,
        "task_path": str(case["task_path"]),
        "electronic_path": str(case["electronic_path"]),
    }


def _request(
    references: list[dict[str, Any]],
    *,
    elements: list[str],
    host_reference_id: str,
    elemental_reference_ids: dict[str, str | None],
    competing_reference_ids: list[str] | None,
    selected_delta_mu: dict[str, float] | None = None,
    reference_set_id: str = "software-contract-reference-set",
) -> dict[str, Any]:
    return {
        "schema": "mlcc.chemical-reference-request.v1",
        "reference_set_id": reference_set_id,
        "elements": elements,
        "host_reference_id": host_reference_id,
        "elemental_reference_ids": elemental_reference_ids,
        "competing_reference_ids": competing_reference_ids,
        "selected_delta_mu": selected_delta_mu,
        "references": references,
    }


def _single_element_request(tmp_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    host_case = _source_case(tmp_path, "host", {"Ca": 2}, -4.0)
    ca_case = _source_case(tmp_path, "ca", {"Ca": 4}, -8.0)
    host_spec = _reference_spec(host_case, "host", "host", "Ca_host", {"Ca": 1})
    ca_spec = _reference_spec(ca_case, "ca", "elemental", "Ca_element", {"Ca": 1})
    request = _request(
        [host_spec, ca_spec],
        elements=["Ca"],
        host_reference_id="host",
        elemental_reference_ids={"Ca": "ca"},
        competing_reference_ids=[],
    )
    references = [read_chemical_reference(host_spec), read_chemical_reference(ca_spec)]
    return request, references


def test_read_formula_normalizes_cell_energy_and_preserves_saved_source(tmp_path: Path) -> None:
    case = _source_case(tmp_path, "czo-host", {"Ca": 4, "Zr": 4, "O": 12}, -40.0)
    spec = _reference_spec(
        case,
        "czo-host",
        "host",
        "CaZrO3_orthorhombic_Pnma",
        {"Ca": 1, "Zr": 1, "O": 3},
    )

    reference = read_chemical_reference(spec)

    assert reference["schema"] == "mlcc.chemical-reference.v1"
    assert reference["reference_id"] == "czo-host"
    assert reference["role"] == "host"
    assert reference["phase_id"] == "CaZrO3_orthorhombic_Pnma"
    assert reference["formula_stoichiometry"] == {"Ca": 1, "Zr": 1, "O": 3}
    assert reference["cell_composition"] == {"Ca": 4, "Zr": 4, "O": 12}
    assert reference["formula_units"] == 4
    assert reference["total_energy_eV_cell"] == pytest.approx(-40.0)
    assert reference["energy_eV_per_formula_unit"] == pytest.approx(-10.0)
    assert reference["elemental_mu_eV_per_atom"] is None
    assert reference["evidence_kind"] == "software_contract_only"
    assert reference["source"]["task_id"] == case["task"]["task_id"]
    assert reference["source"]["native_job"]["scheduler_job_id"] == case["task"]["scheduler_job_id"]
    assert reference["source"]["method"]["method_set"] == case["method"]["method_set"]
    assert reference["source"]["electronic_source"]["evidence_kind"] == "software_contract_only"
    assert reference["source"]["parent_total_energy_provenance"]["is_potential_zero"] is False


def test_read_elemental_reference_uses_atom_denominator_for_molecular_formula(
    tmp_path: Path,
) -> None:
    case = _source_case(tmp_path, "oxygen", {"O": 6}, -12.0)
    spec = _reference_spec(case, "oxygen", "elemental", "declared-O2", {"O": 2})

    reference = read_chemical_reference(spec)

    assert reference["formula_units"] == 3
    assert reference["energy_eV_per_formula_unit"] == pytest.approx(-4.0)
    assert reference["elemental_mu_eV_per_atom"] == pytest.approx(-2.0)
    assert reference["cell_composition"] == {"O": 6}


def test_read_rejects_noninteger_or_incompatible_formula_stoichiometry(
    tmp_path: Path,
) -> None:
    case = _source_case(tmp_path, "czo-host", {"Ca": 4, "Zr": 4, "O": 12}, -40.0)
    noninteger = _reference_spec(
        case, "bad", "host", "bad", {"Ca": 1.5, "Zr": 1, "O": 3}
    )
    with pytest.raises(ValueError):
        read_chemical_reference(noninteger)

    incompatible = _reference_spec(
        case, "bad", "host", "bad", {"Ca": 1, "Zr": 1, "O": 2}
    )
    with pytest.raises(ValueError):
        read_chemical_reference(incompatible)


@pytest.mark.parametrize(
    "formula",
    [
        {"Ca": True, "Zr": 1, "O": 3},
        {"Ca": 0, "Zr": 1, "O": 3},
    ],
)
def test_read_rejects_boolean_or_zero_formula_counts(
    tmp_path: Path, formula: dict[str, Any]
) -> None:
    case = _source_case(tmp_path, "czo-host", {"Ca": 4, "Zr": 4, "O": 12}, -40.0)
    spec = _reference_spec(case, "bad", "host", "bad", formula)

    with pytest.raises(ValueError):
        read_chemical_reference(spec)


def test_read_rejects_result_symbols_that_do_not_match_model_composition(
    tmp_path: Path,
) -> None:
    case = _source_case(tmp_path, "composition", {"Ca": 2}, -4.0)
    result_path = case["task_path"] / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["final_atoms"]["symbols"] = ["Ca", "O"]
    _write_json(result_path, result)
    spec = _reference_spec(case, "composition", "host", "Ca", {"Ca": 1})

    with pytest.raises(ValueError):
        read_chemical_reference(spec)


def test_read_rejects_elemental_reference_with_multiple_elements(tmp_path: Path) -> None:
    case = _source_case(tmp_path, "mixed-element", {"Ca": 2, "O": 2}, -4.0)
    spec = _reference_spec(case, "mixed-element", "elemental", "CaO", {"Ca": 1, "O": 1})

    with pytest.raises(ValueError):
        read_chemical_reference(spec)


def test_read_requires_saved_energy_definition_to_match_fixed_occupation_method(
    tmp_path: Path,
) -> None:
    case = _source_case(tmp_path, "energy-definition", {"Ca": 2}, -4.0)
    result_path = case["task_path"] / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["energy_definition"] = "wrong total-energy definition"
    _write_json(result_path, result)
    electronic_path = case["electronic_path"]
    electronic = json.loads(electronic_path.read_text(encoding="utf-8"))
    electronic["parent_energy_zero_definition"] = "wrong total-energy definition"
    _write_json(electronic_path, electronic)

    spec = _reference_spec(case, "energy-definition", "host", "Ca", {"Ca": 1})
    with pytest.raises(ValueError):
        read_chemical_reference(spec)


def test_read_rejects_energy_definition_changed_on_only_one_side(
    tmp_path: Path,
) -> None:
    for changed_side in ("result", "electronic"):
        case = _source_case(tmp_path, f"energy-{changed_side}", {"Ca": 2}, -4.0)
        if changed_side == "result":
            path = case["task_path"] / "result.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["energy_definition"] = "different result definition"
        else:
            path = case["electronic_path"]
            value = json.loads(path.read_text(encoding="utf-8"))
            value["parent_energy_zero_definition"] = "different electronic definition"
        _write_json(path, value)
        spec = _reference_spec(case, f"energy-{changed_side}", "host", "Ca", {"Ca": 1})

        with pytest.raises(ValueError):
            read_chemical_reference(spec)


@pytest.mark.parametrize("fixture_location", ["task", "result"])
def test_read_rejects_task_or_result_fixture_without_software_marker(
    tmp_path: Path, fixture_location: str
) -> None:
    case = _source_case(tmp_path, f"fixture-{fixture_location}", {"Ca": 2}, -4.0)
    for filename in ("task.json", "result.json", "method.json"):
        path = case["task_path"] / filename
        value = json.loads(path.read_text(encoding="utf-8"))
        value["fixture"] = False
        value.pop("fixture_purpose", None)
        _write_json(path, value)
    model_path = case["task"]["model_path"] + "/model.json"
    model_file = Path(model_path)
    model = json.loads(model_file.read_text(encoding="utf-8"))
    model["fixture"] = False
    model.pop("fixture_purpose", None)
    _write_json(model_file, model)

    fixture_path = case["task_path"] / f"{fixture_location}.json"
    fixture_value = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_value["fixture"] = True
    _write_json(fixture_path, fixture_value)
    electronic_path = case["electronic_path"]
    electronic = json.loads(electronic_path.read_text(encoding="utf-8"))
    electronic["evidence_kind"] = "native_saved_source"
    _write_json(electronic_path, electronic)

    spec = _reference_spec(
        case, f"fixture-{fixture_location}", "host", "Ca", {"Ca": 1}
    )
    with pytest.raises(ValueError):
        read_chemical_reference(spec)


def test_assemble_complete_set_builds_formula_region_and_lists_protocol_differences(
    tmp_path: Path,
) -> None:
    host = _source_case(
        tmp_path,
        "host",
        {"Ca": 2, "Zr": 2, "O": 6},
        -20.0,
        method_set="method-host",
        nspin=1,
        kpoints=[2, 2, 2],
        nbands=8,
    )
    ca = _source_case(
        tmp_path,
        "ca",
        {"Ca": 4},
        -8.0,
        method_set="method-ca",
        nspin=2,
        kpoints=[3, 2, 2],
        nbands=9,
    )
    zr = _source_case(
        tmp_path,
        "zr",
        {"Zr": 4},
        -12.0,
        method_set="method-zr",
        nspin=1,
        kpoints=[2, 3, 2],
        nbands=10,
    )
    oxygen = _source_case(
        tmp_path,
        "oxygen",
        {"O": 6},
        -6.0,
        method_set="method-o",
        nspin=2,
        kpoints=[2, 2, 3],
        nbands=11,
    )
    cao = _source_case(
        tmp_path,
        "cao",
        {"Ca": 2, "O": 2},
        -6.0,
        method_set="method-cao",
        nspin=1,
        kpoints=[3, 3, 2],
        nbands=12,
    )
    specs = [
        _reference_spec(host, "host", "host", "CaZrO3_Pnma", {"Ca": 1, "Zr": 1, "O": 3}),
        _reference_spec(ca, "ca", "elemental", "declared-Ca", {"Ca": 1}),
        _reference_spec(zr, "zr", "elemental", "declared-Zr", {"Zr": 1}),
        _reference_spec(oxygen, "oxygen", "elemental", "declared-O2", {"O": 2}),
        _reference_spec(cao, "cao", "competing", "declared-CaO", {"Ca": 1, "O": 1}),
    ]
    request = _request(
        specs,
        elements=["Ca", "Zr", "O"],
        host_reference_id="host",
        elemental_reference_ids={"Ca": "ca", "Zr": "zr", "O": "oxygen"},
        competing_reference_ids=["cao"],
    )
    references = [read_chemical_reference(spec) for spec in specs]

    result = assemble_chemical_reference_set(request, references)
    _write_json(tmp_path / "software-reference-set.json", result)
    _write_json(tmp_path / "software-request.json", request)

    assert result["schema"] == "mlcc.chemical-reference-set.v1"
    assert result["missing"] == ["selected_delta_mu"]
    assert result["region_request"] is not None
    assert result["region_request"]["mu_ref"]["Ca"]["value_eV_per_atom"] == pytest.approx(-2.0)
    assert result["region_request"]["mu_ref"]["Zr"]["value_eV_per_atom"] == pytest.approx(-3.0)
    assert result["region_request"]["mu_ref"]["O"]["value_eV_per_atom"] == pytest.approx(-1.0)
    assert result["region_request"]["host"]["formation_energy_eV"] == pytest.approx(-2.0)
    assert result["region_request"]["competing_phases"][0]["formation_energy_eV"] == pytest.approx(0.0)
    assert result["scientific_qualification"] is False
    assert result["production_qualification"] is False
    assert all(
        reference["reference_method_id"] == request["reference_set_id"]
        and reference["method_set"] == next(
            spec_case["method"]["method_set"]
            for spec_case in (host, ca, zr, oxygen, cao)
            if spec_case["task"]["task_id"] == reference["source"]["task_id"]
        )
        for reference in result["references"]
    )
    comparison_text = json.dumps(result["method_comparison"], sort_keys=True)
    assert "nspin" in comparison_text
    assert "kpoints" in comparison_text
    assert "nbands" in comparison_text


def test_assemble_keeps_null_selections_distinct_from_explicit_empty_competitors(
    tmp_path: Path,
) -> None:
    host = _source_case(tmp_path, "host", {"Ca": 2}, -4.0)
    ca = _source_case(tmp_path, "ca", {"Ca": 4}, -8.0)
    host_spec = _reference_spec(host, "host", "host", "Ca", {"Ca": 1})
    ca_spec = _reference_spec(ca, "ca", "elemental", "Ca", {"Ca": 1})
    references = [read_chemical_reference(host_spec), read_chemical_reference(ca_spec)]

    unresolved = _request(
        [host_spec, ca_spec],
        elements=["Ca"],
        host_reference_id="host",
        elemental_reference_ids={"Ca": "ca"},
        competing_reference_ids=None,
    )
    unresolved_result = assemble_chemical_reference_set(unresolved, references)
    assert "competing_phase_selection" in unresolved_result["missing"]
    assert unresolved_result["region_request"] is None

    explicit_empty = copy.deepcopy(unresolved)
    explicit_empty["competing_reference_ids"] = []
    explicit_result = assemble_chemical_reference_set(explicit_empty, references)
    assert "competing_phase_selection" not in explicit_result["missing"]
    assert explicit_result["region_request"] is not None
    assert explicit_result["region_request"]["competing_phases"] == []
    assert "selected_delta_mu" in explicit_result["missing"]


def test_assemble_rejects_common_pseudopotential_or_physics_conflicts(
    tmp_path: Path,
) -> None:
    request, references = _single_element_request(tmp_path)

    pp_conflict = copy.deepcopy(references)
    pp_conflict[1]["source"]["method"]["pseudopotential_metadata"]["Ca"]["valence_electrons"] = 9
    with pytest.raises(ValueError):
        assemble_chemical_reference_set(request, pp_conflict)

    physics_conflict = copy.deepcopy(references)
    physics_conflict[1]["source"]["method"]["dft_functional"] = "PBE0"
    with pytest.raises(ValueError):
        assemble_chemical_reference_set(request, physics_conflict)


def test_assemble_rejects_explicit_extra_hubbard_u_or_external_field(
    tmp_path: Path,
) -> None:
    request, references = _single_element_request(tmp_path)
    for field, value in (
        ("hubbard_u", {"Ca": 1.0}),
        ("external_field", [0.0, 0.0, 1.0]),
    ):
        changed = copy.deepcopy(references)
        changed[1]["source"]["method"][field] = value
        with pytest.raises(ValueError):
            assemble_chemical_reference_set(request, changed)


def test_assemble_rejects_reference_role_or_id_mismatch(tmp_path: Path) -> None:
    request, references = _single_element_request(tmp_path)

    wrong_id = copy.deepcopy(references)
    wrong_id[0]["reference_id"] = "other-host"
    with pytest.raises(ValueError):
        assemble_chemical_reference_set(request, wrong_id)

    wrong_role = copy.deepcopy(references)
    wrong_role[0]["role"] = "elemental"
    with pytest.raises(ValueError):
        assemble_chemical_reference_set(request, wrong_role)


def test_assemble_requires_an_explicit_element_mapping_for_every_element(
    tmp_path: Path,
) -> None:
    request, references = _single_element_request(tmp_path)
    request["elemental_reference_ids"] = {}

    with pytest.raises(ValueError):
        assemble_chemical_reference_set(request, references)


def test_build_resolves_task_and_electronic_paths_relative_to_request_file(
    tmp_path: Path,
) -> None:
    request_root = tmp_path / "request-root"
    case = _source_case(request_root, "host", {"Ca": 2}, -4.0)
    task_relative = case["task_path"].relative_to(request_root).as_posix()
    electronic_relative = case["electronic_path"].relative_to(request_root).as_posix()
    spec = {
        "reference_id": "host",
        "role": "host",
        "phase_id": "Ca",
        "phase_selection_source": "software_contract_only explicit declaration",
        "formula_stoichiometry": {"Ca": 1},
        "task_path": task_relative,
        "electronic_path": electronic_relative,
    }
    request = _request(
        [spec],
        elements=["Ca"],
        host_reference_id="host",
        elemental_reference_ids={"Ca": None},
        competing_reference_ids=None,
    )
    request_path = _write_json(request_root / "request.json", request)

    result = build_chemical_reference_set(request_path)

    assert result["references"][0]["reference_id"] == "host"
    assert result["references"][0]["source"]["task_id"] == case["task"]["task_id"]
    assert Path(result["references"][0]["source"]["task_path"]).is_absolute()
    assert "elemental_reference:Ca" in result["missing"]
    assert "competing_phase_selection" in result["missing"]

