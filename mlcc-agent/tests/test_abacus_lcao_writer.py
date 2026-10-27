"""Focused 0.31 ABACUS LCAO writer contract checks.

These tests exercise input-file, STRU, and atom-map generation only.  The
orbital paths are explicit source selections in a software fixture; no
orbital or pseudopotential data is copied and no ABACUS calculation is run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from mlcc.abacus import (
    AbacusExecution,
    AbacusMethod,
    AbacusParameters,
    abacus_method_from_config,
    prepare_abacus,
)
from mlcc.modeling import ModelArtifacts


ELEMENT_ORDER = ["Ca", "O", "Zr"]
PSEUDOPOTENTIALS = {
    "Ca": "/site/PPORBs/pseudopotentials/Ca.upf",
    "O": "/site/PPORBs/pseudopotentials/O.upf",
    "Zr": "/site/PPORBs/pseudopotentials/Zr_ONCV_PBE-1.0.upf",
}
ORBITAL_SOURCES = {
    "Ca": "/site/PPORBs/orbitals-efficiency/Ca_gga.orb",
    "O": "/site/PPORBs/orbitals-efficiency/O_gga.orb",
    "Zr": "/site/PPORBs/orbitals-efficiency/Zr_gga.orb",
}
LCAO_OUTPUT = {
    "out_chg": 0,
    "out_bandgap": 1,
    "out_mat_hs2": 1,
    "out_mat_r": 0,
}


def _model(tmp_path: Path) -> ModelArtifacts:
    """Return an interleaved, non-contiguous-ID model fixture."""

    atoms = Atoms(
        symbols=["O", "Ca", "Zr", "O"],
        scaled_positions=[
            [0.0, 0.0, 0.0],
            [0.25, 0.25, 0.25],
            [0.50, 0.50, 0.50],
            [0.75, 0.75, 0.75],
        ],
        cell=np.diag([5.0, 5.5, 6.0]),
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([70, 10, 50, 20], dtype=int))
    return ModelArtifacts("czo-lcao-writer-fixture", "v001", atoms, {}, tmp_path / "model")


def _method(*, basis_type: str = "lcao", nspin: int = 1, net_charge: int = 0) -> AbacusMethod:
    return AbacusMethod(
        suffix="CZOContract",
        dft_functional="PBE",
        nspin=nspin,
        initial_moments_muB_by_element={element: 0.0 for element in ELEMENT_ORDER},
        occupations="fixed",
        smearing_method=None,
        mixing_type="broyden",
        relax_method="cg",
        symmetry=-1,
        basis_type=basis_type,
        net_charge=net_charge,
    )


def _parameters(*, relax: bool = False) -> AbacusParameters:
    return AbacusParameters(
        ecutwfc_Ry=120.0,
        scf_thr=1e-4,
        scf_nmax=100,
        nbands=32,
        smearing_sigma_Ry=None,
        mixing_beta=0.3,
        force_thr_eV_per_A=0.1 if relax else None,
        relax_nmax=8 if relax else None,
    )


def _prepare(
    tmp_path: Path,
    *,
    name: str = "task",
    method: AbacusMethod | None = None,
    execution: AbacusExecution | None = None,
    parameters: AbacusParameters | None = None,
    stage: str = "scf",
    numerical_orbitals: dict[str, str] | None = None,
    lcao_output: dict[str, int] | None = None,
    berry: dict[str, object] | None = None,
    output_control: dict[str, int] | None = None,
):
    return prepare_abacus(
        _model(tmp_path),
        tmp_path / name,
        method=method or _method(),
        execution=execution or AbacusExecution(device="gpu", ks_solver="cusolver"),
        parameters=parameters or _parameters(),
        stage=stage,
        pseudopotentials=PSEUDOPOTENTIALS,
        element_order=ELEMENT_ORDER,
        kpoints=(2, 2, 2),
        numerical_orbitals=numerical_orbitals,
        lcao_output=lcao_output,
        berry=berry,
        output_control=output_control,
    )


def _input_value(input_text: str, key: str) -> str | None:
    for line in input_text.splitlines():
        fields = line.split(None, 1)
        if fields and fields[0] == key:
            return fields[1].strip() if len(fields) == 2 else ""
    return None


def _science_config(*, basis_type: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "suffix": "CZOContract",
        "dft_functional": "PBE",
        "nspin": 1,
        "initial_moments_muB_by_element": {element: 0.0 for element in ELEMENT_ORDER},
        "occupations": "fixed",
        "smearing_method": None,
        "mixing_type": "broyden",
        "relax_method": "cg",
        "symmetry": -1,
        "lspinorb": False,
        "noncolin": False,
    }
    if basis_type is not None:
        payload["basis_type"] = basis_type
    return payload


def test_method_config_uses_explicit_top_level_basis_and_rejects_conflict():
    config = {"basis_type": "lcao", "science": _science_config()}
    method = abacus_method_from_config(config)
    assert method.basis_type == "lcao"

    conflict = {"basis_type": "lcao", "science": _science_config(basis_type="pw")}
    with pytest.raises(ValueError):
        abacus_method_from_config(conflict)


def test_lcao_writer_emits_orbitals_outputs_and_source_atom_map(tmp_path: Path):
    prepared = _prepare(
        tmp_path,
        numerical_orbitals=ORBITAL_SOURCES,
        lcao_output=LCAO_OUTPUT,
    )
    task_dir = Path(prepared.directory)
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    assert _input_value(input_text, "basis_type") == "lcao"
    assert _input_value(input_text, "device") == "gpu"
    assert _input_value(input_text, "ks_solver") == "cusolver"
    assert _input_value(input_text, "orbital_dir") == "./"
    assert _input_value(input_text, "gamma_only") == "0"
    assert _input_value(input_text, "init_chg") == "auto"
    for key, value in LCAO_OUTPUT.items():
        assert _input_value(input_text, key) == str(value)

    stru = (task_dir / "STRU").read_text(encoding="utf-8")
    orbital_section = stru.split("NUMERICAL_ORBITAL\n", 1)[1].split("\n\nLATTICE_CONSTANT", 1)[0]
    assert orbital_section.splitlines() == ["Ca_gga.orb", "O_gga.orb", "Zr_gga.orb"]

    mapping = json.loads((task_dir / "STRU.atom-map.json").read_text(encoding="utf-8"))
    assert mapping["source_atom_ids"] == [70, 10, 50, 20]
    assert [entry["atom_id"] for entry in mapping["abacus_order"]] == [10, 70, 20, 50]
    assert [entry["element"] for entry in mapping["abacus_order"]] == ["Ca", "O", "O", "Zr"]

    method = json.loads((task_dir / "method.json").read_text(encoding="utf-8"))
    assert method["basis_type"] == "lcao"
    assert method["numerical_orbitals"] == {
        element: {"source": source, "filename": Path(source).name}
        for element, source in ORBITAL_SOURCES.items()
    }
    assert method["lcao_output"] == LCAO_OUTPUT


@pytest.mark.parametrize(
    ("case", "kwargs"),
    [
        ("missing_orbital", {"numerical_orbitals": {"Ca": ORBITAL_SOURCES["Ca"], "O": ORBITAL_SOURCES["O"]}}),
        ("extra_orbital", {"numerical_orbitals": {**ORBITAL_SOURCES, "H": "/site/PPORBs/orbitals/H.orb"}}),
        ("pw_with_orbitals", {"method": _method(basis_type="pw"), "execution": AbacusExecution("gpu", "cg"), "numerical_orbitals": ORBITAL_SOURCES}),
        ("pw_with_lcao_output", {"method": _method(basis_type="pw"), "execution": AbacusExecution("gpu", "cg"), "lcao_output": LCAO_OUTPUT}),
        (
            "wrong_solver",
            {"execution": AbacusExecution(device="gpu", ks_solver="cg"), "numerical_orbitals": ORBITAL_SOURCES},
        ),
        (
            "relax_stage",
            {"parameters": _parameters(relax=True), "stage": "relax", "numerical_orbitals": ORBITAL_SOURCES},
        ),
        ("charged", {"method": _method(net_charge=1), "numerical_orbitals": ORBITAL_SOURCES}),
        ("spin_two", {"method": _method(nspin=2), "numerical_orbitals": ORBITAL_SOURCES}),
        (
            "berry",
            {"berry": {"role": "reference_scf", "out_chg": 1}, "numerical_orbitals": ORBITAL_SOURCES},
        ),
        (
            "lcao_output_control",
            {"output_control": {"out_pot": 2}, "numerical_orbitals": ORBITAL_SOURCES},
        ),
        ("cpu_solver", {"execution": AbacusExecution("cpu", "cusolver"), "numerical_orbitals": ORBITAL_SOURCES}),
        ("incomplete_outputs", {"numerical_orbitals": ORBITAL_SOURCES, "lcao_output": {"out_chg": 1}}),
        ("noninteger_output", {"numerical_orbitals": ORBITAL_SOURCES, "lcao_output": {**LCAO_OUTPUT, "out_chg": True}}),
    ],
    ids=["missing_orbital", "extra_orbital", "pw_with_orbitals", "pw_with_lcao_output",
         "wrong_solver", "relax_stage", "charged", "spin_two", "berry", "lcao_output_control",
         "cpu_solver", "incomplete_outputs", "noninteger_output"],
)
def test_lcao_writer_rejects_out_of_scope_contract(tmp_path: Path, case: str, kwargs: dict[str, object]):
    with pytest.raises(ValueError):
        _prepare(tmp_path, name=case, **kwargs)


def test_pw_writer_reference_has_no_lcao_fields_or_leaks(tmp_path: Path):
    _prepare(
        tmp_path,
        name="pw",
        method=_method(basis_type="pw"),
        execution=AbacusExecution(device="gpu", ks_solver="cg"),
        numerical_orbitals=None,
        lcao_output=None,
    )
    task_dir = tmp_path / "pw"
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    assert _input_value(input_text, "basis_type") == "pw"
    for key in ("orbital_dir", "gamma_only", "init_chg", *LCAO_OUTPUT):
        assert _input_value(input_text, key) is None
    assert "NUMERICAL_ORBITAL" not in (task_dir / "STRU").read_text(encoding="utf-8")

    method = json.loads((task_dir / "method.json").read_text(encoding="utf-8"))
    assert method["basis_type"] == "pw"
    assert "numerical_orbitals" not in method
    assert "lcao_output" not in method


def test_lcao_optional_outputs_are_not_synthesized(tmp_path: Path):
    prepared = _prepare(tmp_path, numerical_orbitals=ORBITAL_SOURCES)
    input_text = (prepared.directory / "INPUT").read_text()
    assert all(_input_value(input_text, field) is None for field in LCAO_OUTPUT)
    assert "lcao_output" not in json.loads((prepared.directory / "method.json").read_text())
