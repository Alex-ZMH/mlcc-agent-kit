from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from mlcc.cli import build_parser
import mlcc.defect_thermodynamics as defect_thermodynamics
from mlcc.defect_thermodynamics import (
    _load_task_bundle,
    binding_energy,
    chemical_potential_region,
    formation_energy_terms,
    neutral_formation_from_tasks,
)


def _identity_fields() -> dict[str, str]:
    return {
        "engine": "abacus",
        "engine_version": "3.10.1",
        "method_set": "test-abacus-pbe-v001",
        "energy_definition": "test native E_KohnSham in eV",
    }


def _chemical_request(*, empty: bool = False) -> dict:
    identity = _identity_fields()
    return {
        "schema": "mlcc.chemical-potential-request.v1",
        "elements": ["Ca", "Zr", "O"],
        "mu_ref": {
            "Ca": {"value_eV_per_atom": -1.0, "source": "test Ca reference", **identity},
            "Zr": {"value_eV_per_atom": -2.0, "source": "test Zr reference", **identity},
            "O": {"value_eV_per_atom": -3.0, "source": "test O reference", **identity},
        },
        "physics": {
            "temperature_model": "0K_DFT_formation_energy",
            "temperature_K": 0.0,
            "pressure_role": "not_applied",
            "oxygen_reservoir": None,
        },
        "host": {
            "phase_id": "CaZrO3",
            "stoichiometry": {"Ca": 1, "Zr": 1, "O": 3},
            "formation_energy_eV": 1.0 if empty else -10.0,
            "source_tasks": ["test-host-reference"],
            **identity,
        },
        "competing_phases": [
            {
                "phase_id": "CaO",
                "stoichiometry": {"Ca": 1, "O": 1},
                "formation_energy_eV": -3.0,
                "source_tasks": ["test-CaO-reference"],
                **identity,
            },
            {
                "phase_id": "ZrO2",
                "stoichiometry": {"Zr": 1, "O": 2},
                "formation_energy_eV": -4.0,
                "source_tasks": ["test-ZrO2-reference"],
                **identity,
            },
        ],
        "selected_delta_mu": {"Ca": -3.0, "Zr": -4.0, "O": -1.0},
    }


def test_chemical_potential_region_reports_feasibility_bounds_and_selected_residuals():
    report = chemical_potential_region(_chemical_request())

    assert report["status"] == "feasible"
    assert report["automatic_rich_poor_selection"] is False
    assert report["selected_point"]["feasible"] is True
    assert abs(report["selected_point"]["host_residual_eV"]) < 1.0e-8
    assert report["selected_point"]["mu_eV_per_atom"] == {
        "Ca": pytest.approx(-4.0),
        "Zr": pytest.approx(-6.0),
        "O": pytest.approx(-4.0),
    }
    assert report["coordinate_bounds"]["O"]["max_delta_mu_eV_per_atom"] == pytest.approx(0.0)
    assert report["scientific_status"] == "mathematical_region_only"
    assert report["production_qualification"] is False


def test_chemical_potential_region_keeps_empty_region_explicit():
    report = chemical_potential_region(_chemical_request(empty=True))

    assert report["status"] == "empty_region"
    assert report["selected_point"]["feasible"] is False
    assert report["automatic_rich_poor_selection"] is False


def test_chemical_potential_region_rejects_reference_mismatch():
    request = _chemical_request()
    request["competing_phases"][0]["method_set"] = "different-method"

    with pytest.raises(ValueError, match="common engine/method/energy definition"):
        chemical_potential_region(request)


def test_chemical_potential_region_rejects_mu_reference_mismatch():
    request = _chemical_request()
    request["mu_ref"]["O"]["method_set"] = "different-method"

    with pytest.raises(ValueError, match="all mu_ref elements must share"):
        chemical_potential_region(request)


def test_chemical_potential_region_rejects_nonempty_lp_solver_error(monkeypatch):
    def failed_linprog(*args, **kwargs):
        return SimpleNamespace(success=False, status=4, message="numerical failure", fun=None)

    monkeypatch.setattr(defect_thermodynamics, "linprog", failed_linprog)
    with pytest.raises(ValueError, match="status 4: numerical failure"):
        chemical_potential_region(_chemical_request())


def test_formation_energy_terms_separates_neutral_terms_without_vbm():
    report = formation_energy_terms(
        Edef=-8.0,
        Ehost=-10.0,
        deltaN={"O": 1},
        mu={"O": -1.0, "Ca": -2.0},
        q=0,
        vbm=None,
        ef_grid=None,
        correction_terms=None,
    )

    assert report["chemical_potential_term_eV"] == pytest.approx(1.0)
    assert report["mu_eV_per_atom"]["Ca"] == pytest.approx(-2.0)
    assert report["formation_energy_eV"] == pytest.approx(3.0)
    assert report["curve"] == [
        {"ef_eV": None, "fermi_term_eV": 0.0, "formation_energy_eV": pytest.approx(3.0)}
    ]
    assert report["production_qualification"] is False


def test_formation_energy_terms_requires_explicit_charge_correction_for_q_nonzero():
    with pytest.raises(ValueError, match="requires explicit correction_terms"):
        formation_energy_terms(
            Edef=-7.0,
            Ehost=-10.0,
            deltaN={"O": 1},
            mu={"O": -1.0},
            q=1,
            vbm=2.0,
            ef_grid=[0.0, 1.0],
            correction_terms=None,
        )


def test_formation_energy_terms_outputs_fermi_curve_and_explicit_correction():
    report = formation_energy_terms(
        Edef=-7.0,
        Ehost=-10.0,
        deltaN={"O": 1},
        mu={"O": -1.0},
        q=1,
        vbm=2.0,
        ef_grid=[0.0, 1.0],
        correction_terms={
            "potential_alignment_eV": 0.1,
            "image_charge_eV": 0.2,
            "total_eV": 0.3,
            "method": "test-only-mathematical-input",
        },
    )

    assert report["curve"][0]["formation_energy_eV"] == pytest.approx(6.3)
    assert report["curve"][1]["formation_energy_eV"] == pytest.approx(7.3)
    assert report["correction"]["alignment_count"] == 1
    assert report["formation_energy_eV"] is None


def _formation_record(energy: float, delta: dict[str, int], *, method: str = "test-method") -> dict:
    return {
        "formation_energy_eV": energy,
        "deltaN": delta,
        "q": 0,
        "engine": "abacus",
        "engine_version": "3.10.1",
        "method_set": method,
        "energy_definition": "test native E_KohnSham in eV",
        "host_reference_id": "host-v001",
        "chemical_potential_reference": "mu-v001",
        "fermi_reference": "host-VBM-v001",
    }


def test_binding_energy_requires_composition_and_charge_conservation():
    report = binding_energy(
        {
            "a": _formation_record(2.0, {"O": -1}),
            "b": _formation_record(3.0, {"Zr": -1}),
            "complex": _formation_record(4.0, {"O": -1, "Zr": -1}),
        },
        {"a": 1, "b": 1, "complex": -1},
    )

    assert report["binding_energy_eV"] == pytest.approx(1.0)
    assert report["positive_means"]
    assert report["composition_balance"] == {"O": 0, "Zr": 0}
    assert report["charge_balance"] == 0


def test_binding_energy_rejects_nonconserved_reaction_and_cross_method():
    records = {
        "a": _formation_record(2.0, {"O": -1}),
        "complex": _formation_record(1.0, {"O": -2}),
    }
    with pytest.raises(ValueError, match="composition is not conserved"):
        binding_energy(records, {"a": 1, "complex": -1})

    records["complex"] = _formation_record(1.0, {"O": -1}, method="other-method")
    with pytest.raises(ValueError, match="share engine, method"):
        binding_energy(records, {"a": 1, "complex": -1})


ROOT = Path(__file__).resolve().parents[2]
CZO_TASK = ROOT / "workspace" / "tasks" / "p4-czo-compatibility-scf-v001"


def _copy_real_czo_task(tmp_path: Path) -> Path:
    destination = tmp_path / "p4-czo-job40"
    source = CZO_TASK.resolve()
    shutil.copytree(source, destination)
    result_path = destination / "result.json"
    result_text = result_path.read_text(encoding="utf-8")
    result_path.write_text(
        result_text.replace(str(source), str(destination.resolve())),
        encoding="utf-8",
    )
    return destination


def test_real_czo_job40_native_bundle_is_read_without_synthetic_result():
    bundle = _load_task_bundle(CZO_TASK)
    result = bundle["result"]
    assert bundle["task"]["task_id"] == "p4-czo-compatibility-scf-v001"
    assert bundle["task"]["scheduler_state"] == "COMPLETED"
    assert bundle["method"]["net_charge"] == 0
    assert bundle["native_energy_eV"] == pytest.approx(result["energy_eV"], abs=1.0e-10)
    assert bundle["native_bundle"]["native_result_consistent"] is True
    assert bundle["native_bundle"]["source_evidence"]["reason"] == "complete"


def test_real_czo_job40_tampered_input_is_rejected(tmp_path: Path):
    copied = _copy_real_czo_task(tmp_path)
    input_path = copied / "INPUT"
    input_path.write_text(
        input_path.read_text(encoding="utf-8").replace("ecutwfc              100", "ecutwfc              101"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="native INPUT is incompatible"):
        _load_task_bundle(copied)


def test_real_czo_job40_tampered_result_energy_is_rejected(tmp_path: Path):
    copied = _copy_real_czo_task(tmp_path)
    result_path = copied / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["energy_eV"] = float(result["energy_eV"]) + 1.0
    result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="result is inconsistent with native energy"):
        _load_task_bundle(copied)


def test_neutral_formation_waits_for_a_real_native_defect_pair(tmp_path: Path):
    parent_model_path = ROOT / "workspace" / "models" / "cazro3-pnma-pristine" / "v001"
    descriptor = tmp_path / "derived-defect-model.json"
    descriptor.write_text(
        json.dumps(
            {
                "model_id": "cazro3-explicit-defect-awaiting",
                "version": "v001",
                "production_qualified": False,
                "composition": {"Ca": 4, "Zr": 4, "O": 13},
                "parent_model": {
                    "model_id": "cazro3-pnma-pristine",
                    "version": "v001",
                    "path": str(parent_model_path.resolve()),
                },
                "derivation_schema": "mlcc.model-derivation.v1",
                "derivation": {
                    "kind": "explicit_defect_sequence",
                    "operations": [
                        {"kind": "interstitial", "element": "O", "delta_N": {"O": 1}}
                    ],
                    "composition_parent": {"Ca": 4, "Zr": 4, "O": 12},
                    "composition_child": {"Ca": 4, "Zr": 4, "O": 13},
                    "composition_delta": {"O": 1},
                    "charge_state": 0,
                    "production_qualified": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        neutral_formation_from_tasks(
            CZO_TASK,
            ROOT / "workspace" / "tasks" / "p4-czo-defect-neutral",
            {},
            descriptor,
        )


def test_neutral_formation_blocks_nonzero_charge_before_task_claim(tmp_path: Path):
    host_model_path = tmp_path / "models" / "host" / "v001"
    defect_model_path = tmp_path / "models" / "defect" / "v001"
    host_model_path.mkdir(parents=True)
    defect_model_path.mkdir(parents=True)
    (host_model_path / "model.json").write_text(
        json.dumps(
            {
                "model_id": "host",
                "version": "v001",
                "composition": {"Ca": 1, "O": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    descriptor = defect_model_path / "model.json"
    descriptor.write_text(
        json.dumps(
            {
                "model_id": "defect",
                "version": "v001",
                "production_qualified": False,
                "composition": {"Ca": 1},
                "parent_model": {
                    "model_id": "host",
                    "version": "v001",
                    "path": str(host_model_path.resolve()),
                },
                "derivation_schema": "mlcc.model-derivation.v1",
                "derivation": {
                    "kind": "explicit_defect_sequence",
                    "operations": [{"kind": "vacancy", "atom_id": 1, "delta_N": {"O": -1}}],
                    "composition_parent": {"Ca": 1, "O": 1},
                    "composition_child": {"Ca": 1},
                    "composition_delta": {"O": -1},
                    "charge_state": 1,
                    "production_qualified": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = neutral_formation_from_tasks(
        tmp_path / "missing-host",
        tmp_path / "missing-defect",
        {},
        descriptor,
    )

    assert report["status"] == "blocked_current_charge_adapter"
    assert report["production_qualification"] is False
    assert any("charged-supercell" in issue for issue in report["issues"])


def _fake_neutral_pair(tmp_path: Path):
    host_model_path = tmp_path / "models" / "host" / "v001"
    defect_model_path = tmp_path / "models" / "defect" / "v001"
    host_model_path.mkdir(parents=True)
    defect_model_path.mkdir(parents=True)
    descriptor_path = defect_model_path / "model.json"
    descriptor = {
        "model_id": "defect",
        "version": "v001",
        "production_qualified": False,
        "composition": {"Ca": 1},
        "parent_model": {
            "model_id": "host",
            "version": "v001",
            "path": str(host_model_path.resolve()),
        },
        "derivation_schema": "mlcc.model-derivation.v1",
        "derivation": {
            "kind": "explicit_defect_sequence",
            "composition_parent": {"Ca": 1, "O": 1},
            "composition_child": {"Ca": 1},
            "composition_delta": {"O": -1},
            "charge_state": 0,
            "production_qualified": False,
        },
    }
    identity = ("abacus", "3.10.1", "test-method", "test native E")
    cell = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    def bundle(task_id: str, model_id: str, model_path: Path, energy: float, job_id: str, composition: dict):
        return {
            "directory": tmp_path / task_id,
            "model_path": model_path.resolve(),
            "task": {
                "task_id": task_id,
                "model_id": model_id,
                "model_version": "v001",
                "engine": "abacus",
                "engine_version": "3.10.1",
                "method_set": "test-method",
                "scheduler_job_id": job_id,
                "scheduler_state": "COMPLETED",
                "exit_code": "0:0",
            },
            "method": {"pseudopotentials": {"Ca": "ca.upf", "O": "o.upf"}},
            "result": {
                "energy_definition": "test native E",
                "final_atoms": {"cell_angstrom": cell},
            },
            "native_energy_eV": energy,
            "native_log": tmp_path / f"{task_id}.running_scf.log",
            "atoms": SimpleNamespace(cell=SimpleNamespace(array=cell)),
            "model": {"composition": composition},
            "method_identity": identity,
        }

    host = bundle("host-task", "host", host_model_path, -10.0, "50", {"Ca": 1, "O": 1})
    defect = bundle("defect-task", "defect", defect_model_path, -8.5, "51", {"Ca": 1, "O": 0})
    return descriptor_path, descriptor, host, defect


def _patch_fake_neutral_pair(monkeypatch, descriptor_path, descriptor, host, defect):
    calls = []

    def load_task_bundle(path):
        calls.append(Path(path))
        return host if Path(path).name == "host-task" else defect

    monkeypatch.setattr(defect_thermodynamics, "_load_descriptor", lambda path: descriptor)
    monkeypatch.setattr(defect_thermodynamics, "_load_task_bundle", load_task_bundle)
    return calls


def test_neutral_formation_without_chemical_point_returns_native_energy_only(tmp_path: Path, monkeypatch):
    descriptor_path, descriptor, host, defect = _fake_neutral_pair(tmp_path)
    calls = _patch_fake_neutral_pair(monkeypatch, descriptor_path, descriptor, host, defect)

    report = neutral_formation_from_tasks(
        tmp_path / "host-task",
        tmp_path / "defect-task",
        None,
        descriptor_path,
    )

    assert calls == [tmp_path / "host-task", tmp_path / "defect-task"]
    assert report["status"] == "raw_neutral_energy_only"
    assert report["scientific_status"] == "raw_neutral_energy_unqualified"
    assert report["production_qualification"] is False
    assert report["size_convergence_qualified"] is False
    assert report["Ehost_eV"] == pytest.approx(-10.0)
    assert report["Edefect_eV"] == pytest.approx(-8.5)
    assert report["raw_energy_difference_eV"] == pytest.approx(1.5)
    assert report["deltaN"] == {"O": -1}
    assert report["source_tasks"] == ["host-task", "defect-task"]
    assert report["source_jobs"] == {"host": "50", "defect": "51"}
    assert report["raw_formation_energy_eV"] is None
    assert report["corrected_formation_energy_eV"] is None
    assert report["chemical_point"] is None


def test_neutral_formation_empty_chemical_point_still_requires_mu(tmp_path: Path, monkeypatch):
    descriptor_path, descriptor, host, defect = _fake_neutral_pair(tmp_path)
    _patch_fake_neutral_pair(monkeypatch, descriptor_path, descriptor, host, defect)

    with pytest.raises(ValueError, match="chemical_point.mu_eV_per_atom"):
        neutral_formation_from_tasks(
            tmp_path / "host-task",
            tmp_path / "defect-task",
            {},
            descriptor_path,
        )


def test_neutral_formation_wrong_chemical_reference_remains_rejected(tmp_path: Path, monkeypatch):
    descriptor_path, descriptor, host, defect = _fake_neutral_pair(tmp_path)
    _patch_fake_neutral_pair(monkeypatch, descriptor_path, descriptor, host, defect)
    point = {
        "mu_eV_per_atom": {"O": -5.0},
        "engine": "abacus",
        "engine_version": "3.10.1",
        "method_set": "wrong-method",
        "energy_definition": "test native E",
        "source_reference": "test reference",
    }

    with pytest.raises(ValueError, match="chemical point method_set"):
        neutral_formation_from_tasks(
            tmp_path / "host-task",
            tmp_path / "defect-task",
            point,
            descriptor_path,
        )


def test_neutral_formation_cli_makes_chemical_point_optional():
    args = build_parser().parse_args(
        [
            "neutral-formation",
            "--host-task",
            "host-task",
            "--defect-task",
            "defect-task",
            "--descriptor",
            "descriptor.json",
            "--output",
            "report.json",
        ]
    )

    assert args.chemical_point is None

