"""Contract-only checks for the native PYATB static electronic consumer.

The fixture is explicitly software_contract_only.  It exercises source binding,
format and failure behavior; it is not a CZO native result or a qualification
test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mlcc import dielectric_response


CONTRACT_EVIDENCE = "software_contract_only"
ABACUS_VERSION = "3.10.1"


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _method() -> dict:
    return {
        "engine": "abacus",
        "engine_version": ABACUS_VERSION,
        "abacus_version_target": ABACUS_VERSION,
        "stage": "scf",
        "method_set": "czo-lcao-contract",
        "basis_type": "lcao",
        "dft_functional": "PBE",
        "nspin": 1,
        "lspinorb": False,
        "noncolin": False,
        "occupations": "fixed",
        "smearing_method": "fixed",
        "element_order": ["Ca", "Zr", "O"],
        "initial_moments_muB_by_element": {"Ca": 0.0, "Zr": 0.0, "O": 0.0},
        "pseudopotential_ids": {"Ca": "Ca.upf", "Zr": "Zr.upf", "O": "O.upf"},
        "pseudopotential_metadata": {
            "Ca": {"source": CONTRACT_EVIDENCE},
            "Zr": {"source": CONTRACT_EVIDENCE},
            "O": {"source": CONTRACT_EVIDENCE},
        },
        "pseudopotential_treatment": "contract-only",
        "net_charge": 0,
        "parameters": {
            "smearing_sigma_Ry": None,
            "nbands": 2,
        },
        "kpoints": [1, 1, 1],
        "kpoint_shift": [0.0, 0.0, 0.0],
        "suffix": "CZO_CONTRACT",
        "model_id": "czo-contract-model",
        "version": "v001",
        "orbital_files": {"Ca": "Ca.orb", "Zr": "Zr.orb", "O": "O.orb"},
        "orbital_metadata": {
            "family": "contract-only",
            "version": "fixture",
            "source": CONTRACT_EVIDENCE,
        },
    }


def _native_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, gap: float = 1.0):
    scf = tmp_path / "scf"
    out = scf / "OUT.CZO_CONTRACT"
    post = tmp_path / "pyatb"
    model_path = tmp_path / "model"
    cell = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]
    method = _method()
    task = {
        "task_id": "czo-scf-contract",
        "engine": "abacus",
        "engine_version": ABACUS_VERSION,
        "calculation": "scf",
        "runner": "slurm",
        "status": "COMPLETED",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "scheduler_job_id": "contract-scf",
        "study_id": "czo-firing-validation-v003",
        "model_id": "czo-contract-model",
        "model_version": "v001",
        "model_path": str(model_path),
        "method_set": method["method_set"],
    }
    result = {
        "task_id": task["task_id"],
        "scheduler_job_id": task["scheduler_job_id"],
        "method_set": method["method_set"],
        "stage": "scf",
        "electronic_converged": True,
        "energy_eV": -1.0,
        "energy_definition": "contract",
    }
    post_record = {
        "task_id": "czo-pyatb-contract",
        "runner": "slurm",
        "scheduler_job_id": "contract-pyatb",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "engine": "pyatb",
        "engine_version": "0.9.0-contract",
        "study_id": task["study_id"],
        "model_id": task["model_id"],
        "model_version": task["model_version"],
        "model_path": str(model_path),
        "reference_scf_task_id": task["task_id"],
        "reference_scf_job_id": task["scheduler_job_id"],
        "working_directory": str(post),
        "mode": "direct_static",
        "input_json": "input.json",
        "output_file": "static_dielectric_function.dat",
        "runtime_version_file": "pyatb.version",
    }
    pyatb_input = {
        "INPUT_PARAMETERS": {
            "package": "ABACUS",
            "nspin": 1,
            "HR_unit": "Ry",
            "rR_unit": "Bohr",
            "sparse_format": 1,
            "fermi_energy": 0.0,
            "fermi_energy_unit": "eV",
            "HR_route": str((out / "data-HR-sparse_SPIN0.csr").resolve()),
            "SR_route": str((out / "data-SR-sparse_SPIN0.csr").resolve()),
            "rR_route": str((out / "data-rR-sparse.csr").resolve()),
        },
        "LATTICE": {
            "lattice_constant": 1.0,
            "lattice_constant_unit": "Angstrom",
            "lattice_vector": cell,
        },
        "OPTICAL_CONDUCTIVITY": {
            "occ_band": 1,
            "static_dielectric_only": 1,
            "use_fermi": False,
            "method": 1,
            "grid": [2, 2, 2],
        },
    }
    for path in (
        scf / "task.json",
        scf / "result.json",
        scf / "method.json",
        scf / "INPUT",
        scf / "KPT",
        scf / "STRU",
        scf / "STRU.atom-map.json",
    ):
        if path.name == "task.json":
            _write(path, task)
        elif path.name == "result.json":
            _write(path, result)
        elif path.name == "method.json":
            _write(path, method)
        elif path.name == "KPT":
            path.write_text("K_POINTS\n0\nGamma\n1 1 1 0 0 0\n", encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("contract-only\n", encoding="utf-8")
    for name in ("data-HR-sparse_SPIN0.csr", "data-SR-sparse_SPIN0.csr", "data-rR-sparse.csr"):
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(f"{CONTRACT_EVIDENCE}\n", encoding="utf-8")
    _write(post / "task.json", post_record)
    _write(post / "input.json", pyatb_input)
    (post / "pyatb.version").write_text(post_record["engine_version"] + "\n", encoding="utf-8")
    (post / "static_dielectric_function.dat").write_text(
        "# xx xy xz yx yy yz zx zy zz\n1 2 3 4 5 6 7 8 9\n", encoding="utf-8"
    )

    electronic = {
        "engine_version": ABACUS_VERSION,
        "model_id": task["model_id"],
        "model_version": task["model_version"],
        "nspin": 1,
        "occupations": "fixed",
        "electron_count_neutral": 2,
        "normalized_occupations": [[[2.0, 0.0]]],
        "sampled_mesh_KS_gap_eV": gap,
        "gap_status": "contract-only",
        "source_files": {"task": str((scf / "task.json").resolve())},
    }
    monkeypatch.setattr(dielectric_response, "read_abacus_electronic_task", lambda _path: electronic)
    monkeypatch.setattr(
        dielectric_response,
        "_model_context",
        lambda _path: {
            "model_id": task["model_id"],
            "model_version": task["model_version"],
            "model_path": str(model_path.resolve()),
            "atom_ids": [0, 1],
            "cell_angstrom": cell,
            "volume_A3": 64.0,
        },
    )
    monkeypatch.setattr(dielectric_response, "_validate_model_and_stru", lambda *_args: None)
    monkeypatch.setattr(dielectric_response, "read_model_artifacts", lambda _path: object())
    request = {
        "schema": "mlcc.pyatb-static-electronic-request.v1",
        "scf_task_path": str(scf.resolve()),
        "postprocess_task_path": str((post / "task.json").resolve()),
        "matrices": {
            "HR": {"path": str((out / "data-HR-sparse_SPIN0.csr").resolve()), "unit": "Ry"},
            "SR": {"path": str((out / "data-SR-sparse_SPIN0.csr").resolve()), "unit": "dimensionless"},
            "rR": {"path": str((out / "data-rR-sparse.csr").resolve()), "unit": "Bohr"},
        },
        "minimum_gap_eV": 0.5,
    }
    request_path = _write(tmp_path / "request.json", request)
    return request_path, scf, post, task, method


class _FakeModelAtoms:
    def __init__(self, *, positions: list[list[float]], symbols: list[str]):
        self.cell = SimpleNamespace(array=np.eye(3, dtype=float) * 4.0)
        self._positions = np.asarray(positions, dtype=float)
        self._symbols = list(symbols)
        self.pbc = [True, True, True]

    def get_chemical_symbols(self) -> list[str]:
        return list(self._symbols)

    def get_positions(self) -> np.ndarray:
        return self._positions.copy()


class _FakeModel:
    def __init__(self, path: Path, *, positions: list[list[float]] | None = None, symbols: list[str] | None = None):
        self.model_id = "czo-contract-model"
        self.version = "v001"
        self.artifact_dir = path
        self.atom_ids = [0, 1]
        self.atoms = _FakeModelAtoms(
            positions=positions or [[0.0, 0.0, 0.0], [2.0, 2.0, 2.0]],
            symbols=symbols or ["Ca", "Zr"],
        )


def _patch_model_copy_fixture(
    monkeypatch: pytest.MonkeyPatch,
    source_path: Path,
    copied_model: _FakeModel,
) -> tuple[_FakeModel, list[_FakeModel]]:
    canonical_model = _FakeModel(source_path)
    validated: list[_FakeModel] = []

    def read_model(path: str | Path) -> _FakeModel:
        candidate = Path(path).resolve()
        if candidate == source_path.resolve():
            return canonical_model
        return copied_model

    monkeypatch.setattr(dielectric_response, "read_model_artifacts", read_model)
    monkeypatch.setattr(
        dielectric_response,
        "_validate_model_and_stru",
        lambda _directory, model, _method: validated.append(model),
    )
    return canonical_model, validated


def test_static_reader_preserves_raw_nine_column_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    request, _, post, _, _ = _native_fixture(tmp_path, monkeypatch)
    product = dielectric_response.read_pyatb_static_electronic(request)
    assert product["method_identity"]["orbital_metadata"]["source"] == CONTRACT_EVIDENCE
    assert product["tensor"] == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    assert product["raw_tensor"] == product["tensor"]
    assert product["tensor_order"] == ["xx", "xy", "xz", "yx", "yy", "yz", "zx", "zy", "zz"]
    assert product["status"] == "complete"
    assert [job["role"] for job in product["native_jobs"]] == ["reference_scf", "pyatb_static"]
    assert str((post / "pyatb.version").resolve()) in product["source_refs"]
    assert "model_path" not in product["postprocess_task"]
    assert not any(path.endswith(("model.json", "model.extxyz")) for path in product["source_refs"])
    assert product["scientific_qualification"] is False
    assert product["production_qualification"] is False


def test_static_reader_accepts_task_local_model_copy_with_explicit_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    request, _, post, task, _ = _native_fixture(tmp_path, monkeypatch)
    local_model_path = post / "model"
    source_model_path = Path(task["model_path"])
    post_record = json.loads((post / "task.json").read_text(encoding="utf-8"))
    post_record["model_path"] = str(local_model_path.resolve())
    post_record["source_model_path"] = str(source_model_path.resolve())
    _write(post / "task.json", post_record)
    copied_model = _FakeModel(local_model_path)
    canonical_model, validated = _patch_model_copy_fixture(
        monkeypatch, source_model_path, copied_model
    )

    product = dielectric_response.read_pyatb_static_electronic(request)

    assert product["parent"]["model_path"] == str(source_model_path.resolve())
    assert product["postprocess_task"]["model_path"] == str(local_model_path.resolve())
    assert product["postprocess_task"]["source_model_path"] == str(source_model_path.resolve())
    assert str((local_model_path / "model.json").resolve()) in product["source_refs"]
    assert str((local_model_path / "model.extxyz").resolve()) in product["source_refs"]
    assert str((source_model_path / "model.json").resolve()) in product["source_refs"]
    assert str((source_model_path / "model.extxyz").resolve()) in product["source_refs"]
    assert str(local_model_path.resolve()) not in product["source_refs"]
    assert str(source_model_path.resolve()) not in product["source_refs"]
    assert validated == [copied_model]
    assert canonical_model.model_id == copied_model.model_id


def test_static_reader_rejects_copy_with_wrong_explicit_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    request, _, post, _, _ = _native_fixture(tmp_path, monkeypatch)
    post_record = json.loads((post / "task.json").read_text(encoding="utf-8"))
    post_record["model_path"] = str((post / "model").resolve())
    post_record["source_model_path"] = str((tmp_path / "other-model").resolve())
    _write(post / "task.json", post_record)

    with pytest.raises(ValueError, match="source_model_path differs"):
        dielectric_response.read_pyatb_static_electronic(request)


def test_static_reader_rejects_copy_with_different_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    request, _, post, task, _ = _native_fixture(tmp_path, monkeypatch)
    local_model_path = post / "model"
    source_model_path = Path(task["model_path"])
    post_record = json.loads((post / "task.json").read_text(encoding="utf-8"))
    post_record["model_path"] = str(local_model_path.resolve())
    post_record["source_model_path"] = str(source_model_path.resolve())
    _write(post / "task.json", post_record)
    copied_model = _FakeModel(
        local_model_path,
        positions=[[0.0, 0.0, 0.0], [2.0, 2.0, 2.1]],
    )
    _patch_model_copy_fixture(monkeypatch, source_model_path, copied_model)

    with pytest.raises(ValueError, match="structure differs"):
        dielectric_response.read_pyatb_static_electronic(request)


def test_static_reader_rejects_matrix_route_not_bound_to_scf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    request, _, post, _, _ = _native_fixture(tmp_path, monkeypatch)
    document = json.loads((post / "input.json").read_text(encoding="utf-8"))
    document["INPUT_PARAMETERS"]["HR_route"] = str((post / "wrong-HR.csr").resolve())
    _write(post / "input.json", document)
    with pytest.raises(ValueError, match="HR_route"):
        dielectric_response.read_pyatb_static_electronic(request)


def test_static_reader_rejects_nonempty_matrix_requirement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    request, scf, _, _, _ = _native_fixture(tmp_path, monkeypatch)
    (scf / "OUT.CZO_CONTRACT" / "data-HR-sparse_SPIN0.csr").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="HR.*empty"):
        dielectric_response.read_pyatb_static_electronic(request)


def test_static_reader_rejects_static_output_header_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    request, _, post, _, _ = _native_fixture(tmp_path, monkeypatch)
    (post / "static_dielectric_function.dat").write_text(
        "# xx xy xz yx yy yz zx zy bad\n1 2 3 4 5 6 7 8 9\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="nine-column header"):
        dielectric_response.read_pyatb_static_electronic(request)


def test_static_reader_preserves_missing_matrix_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    request, scf, _, _, _ = _native_fixture(tmp_path, monkeypatch)
    (scf / "OUT.CZO_CONTRACT" / "data-SR-sparse_SPIN0.csr").unlink()
    with pytest.raises(FileNotFoundError):
        dielectric_response.read_pyatb_static_electronic(request)


def test_static_reader_marks_gap_gate_unresolved_without_fake_tensor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    request, _, _, _, _ = _native_fixture(tmp_path, monkeypatch, gap=0.1)
    product = dielectric_response.read_pyatb_static_electronic(request)
    assert product["method_identity"]["orbital_metadata"]["source"] == CONTRACT_EVIDENCE
    assert product["tensor"] is None
    assert product["raw_tensor"] == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    assert product["status"] == "unresolved"
    assert "sampled_mesh_gap_below_minimum" in product["unresolved_reasons"]


def test_native_binder_reloads_request_and_rejects_tampered_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    request, _, _, _, _ = _native_fixture(tmp_path, monkeypatch)
    product = dielectric_response.read_pyatb_static_electronic(request)
    product_path = _write(tmp_path / "product.json", product)
    bound = dielectric_response.bind_native_electronic_input(product, product_path)
    assert bound["source_path"] == str(product_path.resolve())
    rebound_without_saved_product = dielectric_response.bind_native_electronic_input(product)
    assert "source_path" not in rebound_without_saved_product
    with pytest.raises(ValueError, match="input_path"):
        dielectric_response.bind_native_electronic_input(product, request)
    conflicting = copy.deepcopy(product)
    conflicting["source_path"] = str((tmp_path / "other-product.json").resolve())
    with pytest.raises(ValueError, match="source_path"):
        dielectric_response.bind_native_electronic_input(conflicting, product_path)
    tampered = copy.deepcopy(product)
    tampered["tensor"] = np.eye(3).tolist()
    with pytest.raises(ValueError, match="native electronic product"):
        dielectric_response.bind_native_electronic_input(tampered, product_path)


def test_combine_native_electronic_without_born_keeps_ionic_total_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    request, _, _, task, method = _native_fixture(tmp_path, monkeypatch)
    product = dielectric_response.read_pyatb_static_electronic(request)
    product_path = _write(tmp_path / "product.json", product)
    result = dielectric_response.combine_dielectric_contributions(
        None, product, None, electronic_path=product_path
    )
    assert result["epsilon_infinity"] == product["tensor"]
    assert result["delta_epsilon_ionic"] is None
    assert result["epsilon_static"] is None
    assert result["status"] == "unresolved"
    assert result["contribution_provenance"]["electronic"]["provenance_kind"] == "native_derived"

    born_context = {
        "parent": {
            "study_id": task["study_id"],
            "model_id": task["model_id"],
            "model_version": task["model_version"],
            "model_path": str((tmp_path / "model").resolve()),
        },
        "atom_ids": [0, 1],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
        "common_method": dielectric_response._native_method_identity(method, tmp_path / "scf"),
    }
    ionic = {
        "schema": "mlcc.ionic-dielectric-response.v1",
        "context": born_context,
        "unit": "dimensionless",
        "electrical_boundary": "fixed_E_zero",
        "mechanical_boundary": "fixed_cell",
        "nac": "not_applied",
        "delta_epsilon_ionic": np.eye(3).tolist(),
    }
    born = {"context": born_context}
    combined = dielectric_response.combine_dielectric_contributions(
        born, product, ionic, electronic_path=product_path
    )
    np.testing.assert_allclose(combined["epsilon_static"], np.asarray(product["tensor"]) + np.eye(3))


def test_native_combination_rejects_pw_or_different_nao_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    request, _, _, task, method = _native_fixture(tmp_path, monkeypatch)
    product = dielectric_response.read_pyatb_static_electronic(request)
    product_path = _write(tmp_path / "product.json", product)
    context = {
        "parent": {
            "study_id": task["study_id"],
            "model_id": task["model_id"],
            "model_version": task["model_version"],
            "model_path": str((tmp_path / "model").resolve()),
        },
        "atom_ids": [0, 1],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
        "common_method": dielectric_response._native_method_identity(method, tmp_path / "scf"),
    }
    for field, value in (("basis_type", "pw"), ("orbital_metadata", {"source": "different-nao"})):
        candidate = copy.deepcopy(context)
        candidate["common_method"][field] = value
        with pytest.raises(ValueError, match="context"):
            dielectric_response.combine_dielectric_contributions(
                {"context": candidate}, product, None, electronic_path=product_path
            )
