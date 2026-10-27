from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

import mlcc.dielectric_response as dielectric_response
import mlcc.property_delivery as property_delivery
from mlcc.property_delivery import deliver_p5_properties


def _context(*, study_id: str = "p5-study", model_path: str = "/model") -> dict:
    return {
        "parent": {
            "study_id": study_id,
            "model_id": "fixture-model",
            "model_version": "v001",
            "model_path": model_path,
        },
        "atom_ids": [10, 20],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
        "common_method": {"engine": "math-fixture", "method": "coupled-spring", "version": "v001"},
    }


def _native_method() -> dict:
    return {
        "engine": "abacus",
        "abacus_version_target": "3.10.1",
        "basis_type": "pw",
        "dft_functional": "PBE",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "element_order": ["Na", "Cl"],
        "initial_moments_muB_by_element": {"Na": 0, "Cl": 0},
        "pseudopotential_ids": {"Na": "Na.upf", "Cl": "Cl.upf"},
        "pseudopotential_metadata": {"Na": {}, "Cl": {}},
        "pseudopotential_treatment": {"Na": "scalar", "Cl": "scalar"},
        "net_charge": 0,
        "parameters": {"smearing_sigma_Ry": None},
    }


def _born(*, study_id: str = "p5-study", model_path: str = "/model", unresolved: bool = False) -> dict:
    return {
        "schema": "mlcc.born-charge-columns.v1",
        "context": _context(study_id=study_id, model_path=model_path),
        "unit": "e",
        "atom_ids": [10, 20],
        "full_born_tensors_e": None
        if unresolved
        else [[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]],
        "missing_columns": [{"atom_id": 10, "cartesian_axis": 0, "reasons": ["branch_unresolved"]}]
        if unresolved
        else [],
        "sources": [{"source_mode": "software_math_only", "reference": "math://born"}],
        "qualification": {"complete": not unresolved, "scientific_qualification": False},
    }


def _gamma(*, context: dict | None = None) -> dict:
    context = context or _context()
    matrix = (2.0 * np.block([[np.eye(3), -np.eye(3)], [-np.eye(3), np.eye(3)]]))
    return {
        "schema": "mlcc.gamma-force-constants.v1",
        "parent": context["parent"],
        "atom_ids": context["atom_ids"],
        "cell_angstrom": context["cell_angstrom"],
        "volume_A3": context["volume_A3"],
        "matrix_basis": "parent_atom_major_cartesian",
        "unit": "eV/angstrom^2",
        "matrix_eV_per_A2": matrix.tolist(),
        "method_identity": context["common_method"],
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "source": {"source_mode": "software_math_only", "harmonic_result": "math://gamma"},
        "qualification": {"source_mode": "software_math_only", "scientific": False, "production": False},
    }


def _electronic(*, context: dict | None = None) -> dict:
    context = context or _context()
    return {
        "parent": context["parent"],
        "atom_ids": context["atom_ids"],
        "cell_angstrom": context["cell_angstrom"],
        "volume_A3": context["volume_A3"],
        "method_identity": context["common_method"],
        "kind": "epsilon_infinity_relative",
        "unit": "dimensionless",
        "tensor": (2.0 * np.eye(3)).tolist(),
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "ions": "clamped",
        "source_refs": ["math://electronic"],
    }


def _external_electronic(*, context: dict | None = None, source_path: Path | None = None) -> dict:
    electronic = _electronic(context=context)
    electronic["provenance_kind"] = "external_supplied"
    electronic["qualification"] = {
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
        "source_quality": "caller_supplied",
    }
    if source_path is not None:
        electronic["source_path"] = str(source_path.resolve())
    return electronic


def _ionic(*, context: dict | None = None, unresolved: bool = False) -> dict:
    context = context or _context()
    delta = None if unresolved else (1.5 * np.eye(3)).tolist()
    return {
        "schema": "mlcc.ionic-dielectric-response.v1",
        "context": context,
        "unit": "dimensionless",
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "delta_epsilon_ionic": delta,
        "status": "unresolved" if unresolved else "complete",
        "unresolved_reasons": ["born_tensor_incomplete"] if unresolved else [],
        "method_identity": context["common_method"],
        "gamma_source": {"source_mode": "software_math_only", "harmonic_result": "math://gamma"},
        "born_source": {"schema": "mlcc.born-charge-columns.v1", "sources": [{"source_mode": "software_math_only", "reference": "math://born"}]},
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }


def _dielectric(born: dict, electronic: dict, ionic: dict) -> dict:
    return {
        "schema": "mlcc.dielectric-response.v1",
        "context": born["context"],
        "unit": "dimensionless",
        "epsilon_infinity": electronic["tensor"],
        "delta_epsilon_ionic": ionic["delta_epsilon_ionic"],
        "epsilon_static": (3.5 * np.eye(3)).tolist(),
        "electronic": electronic,
        "ionic": ionic,
        "status": "complete",
        "unresolved_reasons": [],
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _study(tmp_path: Path, *, fixture: bool = True) -> Path:
    return _write(
        tmp_path / "study.json",
        {"study_id": "p5-study", "model": {"model_id": "fixture-model", "version": "v001", "fixture": fixture}},
    )


def _request(tmp_path: Path, paths: dict[str, Path], *, source_mode: str = "software_math_only") -> Path:
    return _write(
        tmp_path / "request.json",
        {
            "schema": "mlcc.p5-property-delivery-request.v1",
            "study_id": "p5-study",
            "source_mode": source_mode,
            **{name: str(path) for name, path in paths.items()},
        },
    )


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        property_delivery,
        "_model_context",
        lambda _path: {
            "model_id": "fixture-model",
            "model_version": "v001",
            "model_path": str(Path("/model").resolve()),
            "atom_ids": [10, 20],
            "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
            "volume_A3": 64.0,
        },
    )


def test_deliver_p5_accepts_full_math_chain_and_preserves_tensors(tmp_path: Path, fake_model):
    born = _born()
    electronic = _electronic()
    ionic = _ionic()
    dielectric = _dielectric(born, electronic, ionic)
    paths = {name: _write(tmp_path / f"{name}.json", value) for name, value in {
        "born": born, "gamma": _gamma(), "electronic": electronic, "ionic": ionic, "dielectric": dielectric
    }.items()}
    result = deliver_p5_properties(_study(tmp_path), _request(tmp_path, paths))
    assert result["schema"] == "mlcc.p5-property-delivery.v1"
    assert result["source_mode"] == "software_math_only"
    assert result["design_assessment"] == "not_assessed"
    assert result["products"]["born"]["full_born_tensors_e"] == born["full_born_tensors_e"]
    assert result["products"]["dielectric"]["epsilon_static"] == dielectric["epsilon_static"]
    assert result["qualification"]["production_qualification"] is False
    assert result["methods"]["comparisons_to_born"]["gamma"]["same_physical_method"] is True


def test_deliver_p5_propagates_unresolved_born_without_zero_fill(tmp_path: Path, fake_model):
    born = _born(unresolved=True)
    ionic = _ionic(unresolved=True)
    ionic["gamma_source"] = None
    born_path = _write(tmp_path / "born.json", born)
    ionic_path = _write(tmp_path / "ionic.json", ionic)
    result = deliver_p5_properties(_study(tmp_path), _request(tmp_path, {"born": born_path, "ionic": ionic_path}))
    assert result["product_status"]["born"]["status"] == "unresolved"
    assert result["product_status"]["born"]["unresolved_reasons"] == ["born_tensor_incomplete", "branch_unresolved"]
    assert result["products"]["born"]["full_born_tensors_e"] is None
    assert result["products"]["dielectric"]["epsilon_static"] is None
    assert result["product_status"]["dielectric"]["unresolved_reasons"]


def test_deliver_p5_rejects_crossed_contexts(tmp_path: Path, fake_model):
    born_path = _write(tmp_path / "born.json", _born())
    bad_context = _context(study_id="other-study")
    gamma_path = _write(tmp_path / "gamma.json", _gamma(context=bad_context))
    with pytest.raises(ValueError, match="context differs"):
        deliver_p5_properties(_study(tmp_path), _request(tmp_path, {"born": born_path, "gamma": gamma_path}))


def test_deliver_p5_rejects_math_native_mixing(tmp_path: Path, fake_model):
    born_path = _write(tmp_path / "born.json", _born())
    native = _electronic()
    native["method_identity"] = {"engine": "abacus", "method_set": "native"}
    native["source_refs"] = ["/v100/native/electronic.json"]
    native_path = _write(tmp_path / "electronic.json", native)
    with pytest.raises(ValueError, match="source_mode"):
        deliver_p5_properties(_study(tmp_path), _request(tmp_path, {"born": born_path, "electronic": native_path}))


def test_deliver_p5_external_electronic_is_explicit_contribution_and_keeps_qualification(
    tmp_path: Path, fake_model
):
    electronic_path = tmp_path / "electronic-external.json"
    electronic = _external_electronic()
    born_path = _write(tmp_path / "born.json", _born())
    _write(electronic_path, electronic)

    result = deliver_p5_properties(
        _study(tmp_path),
        _request(tmp_path, {"born": born_path, "electronic": electronic_path}),
    )

    expected_source_path = str(electronic_path.resolve())
    delivered_electronic = result["products"]["electronic"]
    assert delivered_electronic["provenance_kind"] == "external_supplied"
    assert delivered_electronic["source_path"] == expected_source_path
    assert delivered_electronic["source_refs"] == electronic["source_refs"]
    assert delivered_electronic["method_identity"] == electronic["method_identity"]
    assert delivered_electronic["qualification"] == electronic["qualification"]
    assert result["product_status"]["electronic"]["source_mode"] == "external_supplied"
    assert result["product_status"]["electronic"]["source_paths"] == [
        expected_source_path,
        *electronic["source_refs"],
    ]
    provenance = result["products"]["dielectric"]["contribution_provenance"]
    assert provenance["electronic"] == {
        "provenance_kind": "external_supplied",
        "source_path": expected_source_path,
        "source_refs": electronic["source_refs"],
    }
    assert provenance["ionic"] is None
    assert result["products"]["dielectric"]["epsilon_static"] is None
    assert result["native_jobs"] == []
    assert result["qualification"]["production_qualification"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("source_mode", "native_source_bound", id="native-source-mode"),
        pytest.param("native_tasks", ["/v100/native/task.json"], id="native-tasks"),
        pytest.param("native_jobs", [{"task_id": "native-1"}], id="native-jobs"),
    ],
)
def test_deliver_p5_rejects_external_electronic_pseudo_native_fields(
    tmp_path: Path, fake_model, field: str, value: object
):
    electronic_path = tmp_path / "electronic-external.json"
    electronic = _external_electronic(source_path=electronic_path)
    electronic[field] = value
    _write(electronic_path, electronic)
    born_path = _write(tmp_path / "born.json", _born())

    with pytest.raises(ValueError, match="native|source_mode"):
        deliver_p5_properties(
            _study(tmp_path),
            _request(tmp_path, {"born": born_path, "electronic": electronic_path}),
        )


def test_deliver_p5_rejects_external_source_path_conflict(tmp_path: Path, fake_model):
    electronic_path = tmp_path / "electronic-external.json"
    conflicting_path = tmp_path / "other-electronic.json"
    electronic = _external_electronic(source_path=conflicting_path)
    _write(electronic_path, electronic)
    _write(conflicting_path, {"source": "separate"})
    born_path = _write(tmp_path / "born.json", _born())

    with pytest.raises(ValueError, match="source_path"):
        deliver_p5_properties(
            _study(tmp_path),
            _request(tmp_path, {"born": born_path, "electronic": electronic_path}),
        )


def test_deliver_p5_rejects_unknown_external_provenance_kind(tmp_path: Path, fake_model):
    electronic_path = tmp_path / "electronic-external.json"
    electronic = _external_electronic(source_path=electronic_path)
    electronic["provenance_kind"] = "unrecognized"
    _write(electronic_path, electronic)
    born_path = _write(tmp_path / "born.json", _born())

    with pytest.raises(ValueError, match="provenance_kind"):
        deliver_p5_properties(
            _study(tmp_path),
            _request(tmp_path, {"born": born_path, "electronic": electronic_path}),
        )


def test_deliver_p5_rejects_external_empty_source_refs(tmp_path: Path, fake_model):
    electronic_path = tmp_path / "electronic-external.json"
    electronic = _external_electronic(source_path=electronic_path)
    electronic["source_refs"] = []
    _write(electronic_path, electronic)
    born_path = _write(tmp_path / "born.json", _born())

    with pytest.raises(ValueError, match="source_refs"):
        deliver_p5_properties(
            _study(tmp_path),
            _request(tmp_path, {"born": born_path, "electronic": electronic_path}),
        )


def test_deliver_p5_rejects_undeclared_non_math_electronic_input(tmp_path: Path, fake_model):
    electronic_path = tmp_path / "electronic-native.json"
    electronic = _electronic()
    electronic["method_identity"] = _native_method()
    _write(electronic_path, electronic)
    born_path = _write(tmp_path / "born.json", _born())

    with pytest.raises(ValueError, match="source_mode"):
        deliver_p5_properties(
            _study(tmp_path),
            _request(tmp_path, {"born": born_path, "electronic": electronic_path}),
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        pytest.param("context", "context differs", id="context"),
        pytest.param("method", "context differs", id="method"),
        pytest.param("unit", "electronic.unit", id="unit"),
        pytest.param("boundary", "electronic.electrical_boundary", id="boundary"),
    ],
)
def test_deliver_p5_rejects_external_electronic_contract_mismatch(
    tmp_path: Path, fake_model, mutation: str, match: str
):
    electronic_path = tmp_path / "electronic-external.json"
    electronic = _external_electronic(source_path=electronic_path)
    if mutation == "context":
        electronic["parent"] = copy.deepcopy(electronic["parent"])
        electronic["parent"]["study_id"] = "other-study"
    elif mutation == "method":
        electronic["method_identity"] = {**electronic["method_identity"], "version": "other"}
    elif mutation == "unit":
        electronic["unit"] = "eV"
    elif mutation == "boundary":
        electronic["electrical_boundary"] = "fixed_D_zero"
    _write(electronic_path, electronic)
    born_path = _write(tmp_path / "born.json", _born())

    with pytest.raises(ValueError, match=match):
        deliver_p5_properties(
            _study(tmp_path),
            _request(tmp_path, {"born": born_path, "electronic": electronic_path}),
        )


def test_deliver_p5_rejects_saved_external_contribution_provenance_override(tmp_path: Path, fake_model):
    electronic_path = tmp_path / "electronic-external.json"
    electronic = _external_electronic(source_path=electronic_path)
    _write(electronic_path, electronic)
    born = _born()
    born_path = _write(tmp_path / "born.json", born)
    saved = {
        "schema": "mlcc.dielectric-response.v1",
        "context": born["context"],
        "unit": "dimensionless",
        "epsilon_infinity": electronic["tensor"],
        "delta_epsilon_ionic": None,
        "epsilon_static": None,
        "electronic": copy.deepcopy(electronic),
        "ionic": None,
        "contribution_provenance": {
            "electronic": {
                "provenance_kind": "external_supplied",
                "source_path": str((tmp_path / "overridden.json").resolve()),
                "source_refs": electronic["source_refs"],
            },
            "ionic": None,
        },
        "status": "unresolved",
        "unresolved_reasons": ["electronic_or_ionic_contribution_missing"],
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }
    dielectric_path = _write(tmp_path / "dielectric.json", saved)

    with pytest.raises(ValueError, match="contribution_provenance"):
        deliver_p5_properties(
            _study(tmp_path),
            _request(
                tmp_path,
                {"born": born_path, "electronic": electronic_path, "dielectric": dielectric_path},
            ),
        )


@pytest.mark.parametrize("field", ["unit", "full_born_tensors_e"])
def test_deliver_p5_rejects_born_unit_or_shape(tmp_path: Path, fake_model, field: str):
    born = _born()
    born[field] = "bad" if field == "unit" else [[1.0, 2.0]]
    born_path = _write(tmp_path / "born.json", born)
    with pytest.raises(ValueError, match="Born"):
        deliver_p5_properties(_study(tmp_path), _request(tmp_path, {"born": born_path}))


@pytest.mark.parametrize("field", ["unit", "matrix_eV_per_A2"])
def test_deliver_p5_rejects_gamma_unit_or_shape(tmp_path: Path, fake_model, field: str):
    gamma = _gamma()
    gamma[field] = "bad" if field == "unit" else [[1.0]]
    born_path = _write(tmp_path / "born.json", _born())
    gamma_path = _write(tmp_path / "gamma.json", gamma)
    with pytest.raises(ValueError, match="Gamma"):
        deliver_p5_properties(_study(tmp_path), _request(tmp_path, {"born": born_path, "gamma": gamma_path}))


def test_deliver_p5_marks_missing_optional_products_explicitly(tmp_path: Path, fake_model):
    born_path = _write(tmp_path / "born.json", _born())
    result = deliver_p5_properties(_study(tmp_path), _request(tmp_path, {"born": born_path}))
    assert result["products"]["gamma"] is None
    assert result["products"]["electronic"] is None
    assert result["products"]["ionic"] is None
    assert result["product_status"]["gamma"]["status"] == "missing"
    assert result["product_status"]["electronic"]["status"] == "missing"
    assert result["product_status"]["ionic"]["status"] == "missing"


def test_deliver_p5_rejects_crossed_ionic_source(tmp_path: Path, fake_model):
    born = _born()
    ionic = _ionic()
    ionic["born_source"]["sources"] = [{"source_mode": "software_math_only", "reference": "math://other-born"}]
    paths = {
        "born": _write(tmp_path / "born.json", born),
        "gamma": _write(tmp_path / "gamma.json", _gamma()),
        "ionic": _write(tmp_path / "ionic.json", ionic),
    }
    with pytest.raises(ValueError, match="born_source"):
        deliver_p5_properties(_study(tmp_path), _request(tmp_path, paths))


def test_deliver_p5_rejects_broadcastable_dielectric_shape(tmp_path: Path, fake_model):
    born = _born()
    electronic = _electronic()
    ionic = _ionic()
    dielectric = _dielectric(born, electronic, ionic)
    dielectric["epsilon_static"] = [3.5, 3.5, 3.5]
    paths = {
        name: _write(tmp_path / f"{name}.json", value)
        for name, value in {
            "born": born,
            "gamma": _gamma(),
            "electronic": electronic,
            "ionic": ionic,
            "dielectric": dielectric,
        }.items()
    }
    with pytest.raises(ValueError, match="dielectric.epsilon_static"):
        deliver_p5_properties(_study(tmp_path), _request(tmp_path, paths))


def test_deliver_p5_rejects_changed_nested_diagnostic(tmp_path: Path, fake_model):
    born = _born()
    electronic = _electronic()
    ionic = _ionic()
    dielectric = _dielectric(born, electronic, ionic)
    dielectric["ionic"] = copy.deepcopy(ionic)
    dielectric["ionic"]["status"] = "unresolved"
    paths = {
        name: _write(tmp_path / f"{name}.json", value)
        for name, value in {
            "born": born,
            "gamma": _gamma(),
            "electronic": electronic,
            "ionic": ionic,
            "dielectric": dielectric,
        }.items()
    }
    with pytest.raises(ValueError, match="saved dielectric ionic"):
        deliver_p5_properties(_study(tmp_path), _request(tmp_path, paths))


def _write_native_born_fixture(tmp_path: Path) -> tuple[Path, dict]:
    nscf_task = _write(
        tmp_path / "nscf-task.json",
        {"task_id": "nscf-1", "scheduler_job_id": 111, "scheduler_state": "COMPLETED", "exit_code": "0:0", "runner": "slurm"},
    )
    scf_task = _write(
        tmp_path / "scf-task.json",
        {"task_id": "scf-1", "scheduler_job_id": 110, "scheduler_state": "COMPLETED", "exit_code": "0:0", "runner": "slurm"},
    )
    native_context = _context()
    native_context["common_method"] = _native_method()
    response_path = _write(
        tmp_path / "response.json",
        {
            "parent": {
                "study_id": "p5-study",
                "model_id": "fixture-model",
                "model_version": "v001",
                "model_path": str(Path("/model").resolve()),
            },
            "common_method": _native_method(),
            "directions": [
                {
                    "minus": {
                        "task": {"task_id": "nscf-1"},
                        "source": {"task_file": str(nscf_task)},
                        "native_result": {"reference_scf_validation": {"task_id": "scf-1", "task_file": str(scf_task)}},
                        "scf_job": {"task_id": "scf-1", "task_file": str(scf_task)},
                    },
                    "plus": {
                        "task": {"task_id": "nscf-1"},
                        "source": {"task_file": str(nscf_task)},
                        "native_result": {"reference_scf_validation": {"task_id": "scf-1", "task_file": str(scf_task)}},
                        "scf_job": {"task_id": "scf-1", "task_file": str(scf_task)},
                    },
                }
            ]
        },
    )
    born = _born()
    born["context"] = native_context
    born["sources"] = [{"source_mode": "native_source_bound", "response_path": str(response_path)}]
    born["response_paths"] = [str(response_path)]
    born_path = _write(tmp_path / "born-native.json", born)
    return born_path, native_context


def test_deliver_p5_preserves_native_born_scheduler_provenance(tmp_path: Path, fake_model, monkeypatch: pytest.MonkeyPatch):
    """software_contract_only: native source-reader validation is stubbed."""
    born_path, _native_context = _write_native_born_fixture(tmp_path)
    # software_contract_only: keep the native-reader stub explicit in this
    # routing test; no production native evidence is created here.
    monkeypatch.setattr(dielectric_response, "_validate_native_sources", lambda _response, _path: None)
    result = deliver_p5_properties(
        _study(tmp_path, fixture=False),
        _request(tmp_path, {"born": born_path}, source_mode="native_source_bound"),
    )
    ids = {(record["task_id"], record["scheduler_job_id"]) for record in result["native_jobs"]}
    assert ("nscf-1", 111) in ids
    assert ("scf-1", 110) in ids
    assert result["native_jobs"][0]["scheduler_state"] == "COMPLETED"


def test_deliver_p5_routes_saved_external_only_composite_with_native_main(
    tmp_path: Path, fake_model, monkeypatch: pytest.MonkeyPatch
):
    """software_contract_only: native-main routing uses saved task stubs."""
    born_path, native_context = _write_native_born_fixture(tmp_path)
    born = json.loads(born_path.read_text(encoding="utf-8"))
    electronic_path = tmp_path / "electronic-external.json"
    electronic = _external_electronic(context=native_context, source_path=electronic_path)
    _write(electronic_path, electronic)
    expected_provenance = {
        "electronic": {
            "provenance_kind": "external_supplied",
            "source_path": str(electronic_path.resolve()),
            "source_refs": electronic["source_refs"],
        },
        "ionic": None,
    }
    saved_dielectric = {
        "schema": "mlcc.dielectric-response.v1",
        "context": born["context"],
        "unit": "dimensionless",
        "epsilon_infinity": electronic["tensor"],
        "delta_epsilon_ionic": None,
        "epsilon_static": None,
        "electronic": copy.deepcopy(electronic),
        "ionic": None,
        "contribution_provenance": expected_provenance,
        "status": "unresolved",
        "unresolved_reasons": ["electronic_or_ionic_contribution_missing"],
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
    }
    dielectric_path = _write(tmp_path / "dielectric-external-only.json", saved_dielectric)
    # software_contract_only: keep the native-reader stub explicit in this
    # routing test; no production native evidence is created here.
    monkeypatch.setattr(dielectric_response, "_validate_native_sources", lambda _response, _path: None)

    result = deliver_p5_properties(
        _study(tmp_path, fixture=False),
        _request(
            tmp_path,
            {"born": born_path, "electronic": electronic_path, "dielectric": dielectric_path},
            source_mode="native_source_bound",
        ),
    )

    assert result["product_status"]["electronic"]["source_mode"] == "external_supplied"
    assert result["product_status"]["dielectric"]["source_mode"] == "native_source_bound"
    assert str(electronic_path.resolve()) in result["product_status"]["electronic"]["source_paths"]
    assert str(electronic_path.resolve()) in result["product_status"]["dielectric"]["source_paths"]
    assert result["products"]["dielectric"]["contribution_provenance"] == expected_provenance
    ids = {(record["task_id"], record["scheduler_job_id"]) for record in result["native_jobs"]}
    assert ("nscf-1", 111) in ids
    assert ("scf-1", 110) in ids
    assert all(record["role"] != "electronic" for record in result["native_jobs"])

