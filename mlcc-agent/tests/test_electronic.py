"""Native ABACUS electronic extraction and DOS checks.

The positive cases read the retained job37/job40 native outputs.  Negative
cases copy those task directories into pytest's temporary directory before
damaging a copy, so no historical task or scientific output is changed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from mlcc.electronic import (
    _electron_count_contract,
    _native_electron_markers,
    gaussian_dos,
    read_abacus_electronic_task,
)


ROOT = Path(__file__).resolve().parents[2]
CZO_TASK = ROOT / "workspace" / "tasks" / "p4-czo-compatibility-scf-v001"
NI_TASK = ROOT / "workspace" / "tasks" / "h1-ni-scf-v003"


def _copy_task(source: Path, tmp_path: Path) -> Path:
    target = tmp_path / source.name
    shutil.copytree(source, target)
    result_file = target / "result.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    method = json.loads((target / "method.json").read_text(encoding="utf-8"))
    result["source_files"]["running_scf.log"] = str(
        target / f"OUT.{method['suffix']}" / "running_scf.log"
    )
    result_file.write_text(json.dumps(result), encoding="utf-8")
    return target


def _relabel_czo_copy_as_charged(copied: Path, *, gate_flag: int | None = None) -> None:
    """Relabel retained job40 inputs only; native output remains neutral on purpose."""

    method_file = copied / "method.json"
    method = json.loads(method_file.read_text(encoding="utf-8"))
    method.update(net_charge=2, nelec=0, nelec_delta=-2)
    electron_count = method["input_qualification"]["electron_count"]
    electron_count.update(
        neutral_valence_electrons=160.0,
        target_electrons=158.0,
        net_charge=2,
        nelec_delta=-2,
    )
    method_file.write_text(json.dumps(method), encoding="utf-8")
    input_file = copied / "INPUT"
    text = input_file.read_text(encoding="utf-8")
    text += "nelec                0\nnelec_delta          -2\n"
    if gate_flag is not None:
        text += f"gate_flag            {gate_flag}\n"
    input_file.write_text(text, encoding="utf-8")


def test_czo_native_fixed_levels_and_sampled_mesh_gap() -> None:
    electronic = read_abacus_electronic_task(CZO_TASK)

    assert electronic["task_id"] == "p4-czo-compatibility-scf-v001"
    assert electronic["nspin"] == 1
    assert electronic["spin_degeneracy"] == 2
    assert electronic["occupations"] == "fixed"
    assert electronic["kpoint_mesh"] == [2, 2, 2]
    assert electronic["uniform_kmesh_verified"] is True
    assert np.isclose(electronic["kpoint_weight_sum"], 1.0)
    assert np.asarray(electronic["band_energies_eV"]).shape == (1, 8, 88)
    assert np.asarray(electronic["weighted_occupations"]).shape == (1, 8, 88)
    assert np.allclose(np.asarray(electronic["normalized_occupations"])[:, :, :80], 2.0)
    assert np.allclose(np.asarray(electronic["normalized_occupations"])[:, :, 80:], 0.0)
    assert electronic["electron_count_native"] == pytest.approx(160.0)
    assert electronic["electron_count_native_log"] == pytest.approx(160.0)
    assert electronic["electron_count_native_log_match"] is True
    assert electronic["electron_count_native_log_abs_error"] == pytest.approx(0.0)
    assert electronic["electron_count_declared"] == pytest.approx(160.0)
    assert electronic["electron_count_match"] is True
    assert electronic["fermi_level_eV"] == pytest.approx(8.6601116381)
    assert electronic["fractional_occupations_present"] is False
    assert electronic["sampled_mesh_KS_gap_eV"] == pytest.approx(4.036775419048563)
    assert electronic["vbm_eV"] == pytest.approx(8.660111638055646)
    assert electronic["cbm_eV"] == pytest.approx(12.69688705710421)
    assert electronic["gap_qualification"]["is_fundamental_gap"] is False
    assert electronic["gap_qualification"]["is_band_path_gap"] is False
    assert electronic["gap_qualification"]["precision_qualified"] is False


def test_ni_native_spin_channels_and_smearing_gap_is_suppressed() -> None:
    electronic = read_abacus_electronic_task(NI_TASK)

    assert electronic["task_id"] == "h1-ni-scf-v003"
    assert electronic["nspin"] == 2
    assert electronic["spin_channels"] == ["up", "down"]
    assert electronic["spin_degeneracy"] == 1
    assert electronic["occupations"] == "smearing"
    assert np.asarray(electronic["band_energies_eV"]).shape == (2, 8, 56)
    assert np.asarray(electronic["weighted_occupations"])[0, 0, 0] == pytest.approx(0.125)
    assert np.asarray(electronic["normalized_occupations"])[0, 0, 0] == pytest.approx(1.0)
    assert electronic["electron_count_native"] == pytest.approx(72.0, abs=2.0e-6)
    assert electronic["electron_count_native_log"] == pytest.approx(72.0)
    assert electronic["electron_count_native_log_match"] is True
    assert electronic["electron_count_native_log_abs_error"] == pytest.approx(1.2155673e-6)
    assert electronic["electron_count_declared"] == pytest.approx(72.0)
    assert electronic["electron_count_match"] is True
    assert electronic["fermi_level_eV"] == pytest.approx(19.771381313)
    assert electronic["fractional_occupations_present"] is True
    assert electronic["sampled_mesh_KS_gap_eV"] is None
    assert electronic["vbm_eV"] is None
    assert electronic["cbm_eV"] is None
    assert electronic["gap_status"] == "unavailable_finite_smearing"
    assert "finite_smearing_partial_occupations" in electronic["gap_reason"]


@pytest.mark.parametrize(
    ("task_name", "grid_min", "grid_max", "expected_states"),
    [
        ("p4-czo-compatibility-scf-v001", -45.0, 20.0, 176.0),
        ("h1-ni-scf-v003", -90.0, 50.0, 112.0),
    ],
)
def test_gaussian_dos_includes_spin_weight_and_reports_finite_window(
    task_name: str, grid_min: float, grid_max: float, expected_states: float
) -> None:
    source = CZO_TASK if task_name.startswith("p4-") else NI_TASK
    electronic = read_abacus_electronic_task(source)
    grid = np.linspace(grid_min, grid_max, 5001)
    dos = gaussian_dos(electronic, grid, sigma_eV=0.1)

    assert dos["unit"] == "states/eV/cell"
    assert dos["include_occupied_and_unoccupied"] is True
    assert dos["is_ldos"] is False
    assert dos["precision_qualified"] is False
    assert dos["weighted_state_count"] == pytest.approx(expected_states)
    assert dos["finite_grid_integral_states_per_cell"] == pytest.approx(expected_states, abs=1.0e-6)
    assert abs(dos["finite_grid_integral_error_states_per_cell"]) < 1.0e-6
    assert np.all(np.isfinite(np.asarray(dos["dos_states_per_eV_per_cell"])))
    assert np.any(np.asarray(dos["dos_states_per_eV_per_cell"]) > 0.0)


def test_gaussian_dos_mathematical_spin_degeneracy() -> None:
    electronic = {
        "band_energies_eV": [[[0.0, 1.0]]],
        "kpoint_weights": [1.0],
        "nspin": 1,
        "spin_channels": ["up"],
        "spin_degeneracy": 2,
        "occupation_capacity_per_spin_channel": 2,
        "task_id": "math-test",
        "scheduler_job_id": "math-job",
        "method_set": "math-method",
        "model_id": "math-model",
        "model_version": "v001",
        "source_files": {"istate.info": "math"},
        "parent_energy_zero_eV": -1.0,
        "parent_energy_zero_definition": "synthetic mathematical input",
        "fermi_level_eV": 0.5,
    }
    grid = np.linspace(-10.0, 11.0, 4201)
    dos = gaussian_dos(electronic, grid, sigma_eV=0.1)

    assert dos["weighted_state_count"] == pytest.approx(4.0)
    assert dos["finite_grid_integral_states_per_cell"] == pytest.approx(4.0, abs=1.0e-6)
    assert dos["task_id"] == "math-test"
    assert dos["parent_energy_zero_eV"] == pytest.approx(-1.0)
    assert dos["fermi_level_eV"] == pytest.approx(0.5)


def test_gaussian_dos_rejects_inconsistent_spin_degeneracy() -> None:
    electronic = {
        "band_energies_eV": [[[0.0]]],
        "kpoint_weights": [1.0],
        "nspin": 1,
        "spin_channels": ["up"],
        "spin_degeneracy": 1,
        "occupation_capacity_per_spin_channel": 2,
        "task_id": "math-test",
        "scheduler_job_id": "math-job",
        "method_set": "math-method",
        "model_id": "math-model",
        "model_version": "v001",
        "source_files": {"istate.info": "math"},
        "parent_energy_zero_eV": -1.0,
        "parent_energy_zero_definition": "synthetic mathematical input",
        "fermi_level_eV": 0.5,
    }

    with pytest.raises(ValueError, match="spin_degeneracy"):
        gaussian_dos(electronic, np.linspace(-1.0, 1.0, 11), sigma_eV=0.1)


def test_missing_native_file_is_rejected_without_synthesising_data(tmp_path: Path) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    (copied / "OUT.CZOCompat" / "istate.info").unlink()

    with pytest.raises(FileNotFoundError):
        read_abacus_electronic_task(copied)


def test_incomplete_last_istate_block_is_rejected(tmp_path: Path) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    native_file = copied / "OUT.CZOCompat" / "istate.info"
    lines = native_file.read_text(encoding="utf-8").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    lines.pop()
    native_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inconsistent band counts|contiguous"):
        read_abacus_electronic_task(copied)


def test_task_and_method_identity_are_validated(tmp_path: Path) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    result_file = copied / "result.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    result["method_set"] = "wrong-method-id"
    result_file.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(ValueError, match="result.method_set mismatch"):
        read_abacus_electronic_task(copied)


def test_result_native_source_path_is_validated(tmp_path: Path) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    result_file = copied / "result.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    result["source_files"]["running_scf.log"] = str(tmp_path / "other" / "running_scf.log")
    result_file.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(ValueError, match="source_files.running_scf.log"):
        read_abacus_electronic_task(copied)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_id", "wrong-model", "method.model_id mismatch"),
        ("version", "wrong-version", "method.version mismatch"),
    ],
)
def test_method_model_identity_is_validated(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    method_file = copied / "method.json"
    method = json.loads(method_file.read_text(encoding="utf-8"))
    method[field] = value
    method_file.write_text(json.dumps(method), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        read_abacus_electronic_task(copied)


def test_weighted_native_occupations_are_compared_with_log_autoset_count(tmp_path: Path) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    native_log = copied / "OUT.CZOCompat" / "running_scf.log"
    text = native_log.read_text(encoding="utf-8")
    text = text.replace("AUTOSET number of electrons:  = 160", "AUTOSET number of electrons:  = 159")
    native_log.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="AUTOSET electron count"):
        read_abacus_electronic_task(copied)


def test_native_gamma_cartesian_product_rejects_duplicate_point(tmp_path: Path) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    native_kpoints = copied / "OUT.CZOCompat" / "kpoints"
    text = native_kpoints.read_text(encoding="utf-8")
    text = text.replace(
        "       8  0.50000000  0.50000000  0.50000000  0.1250",
        "       8  0.00000000  0.50000000  0.50000000  0.1250",
    )
    native_kpoints.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate|Cartesian product"):
        read_abacus_electronic_task(copied)


def test_kpt_parser_rejects_non_gamma_shift_form(tmp_path: Path) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    kpt = copied / "KPT"
    text = kpt.read_text(encoding="utf-8").replace("2 2 2 0 0 0", "2 2 2 1 0 0")
    kpt.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="Gamma mesh with zero shift"):
        read_abacus_electronic_task(copied)


def test_input_and_method_occupation_settings_are_validated(tmp_path: Path) -> None:
    copied = _copy_task(CZO_TASK, tmp_path)
    method_file = copied / "method.json"
    method = json.loads(method_file.read_text(encoding="utf-8"))
    method["nspin"] = 2
    method_file.write_text(json.dumps(method), encoding="utf-8")

    with pytest.raises(ValueError, match="INPUT/method nspin mismatch"):
        read_abacus_electronic_task(copied)


def test_charged_electron_contract_reports_neutral_target_and_delta() -> None:
    """Unit-format contract check; no native result is treated as scientific evidence."""

    method = {
        "net_charge": 2,
        "nelec": 0,
        "nelec_delta": -2,
        "pseudopotential_metadata": {
            "Ca": {"valence_electrons_per_atom": 10},
            "Zr": {"valence_electrons_per_atom": 12},
            "O": {"valence_electrons_per_atom": 6},
        },
        "input_qualification": {
            "electron_count": {
                "neutral_valence_electrons": 160,
                "target_electrons": 158,
                "net_charge": 2,
                "nelec_delta": -2,
            }
        },
    }
    result = {
        "final_atoms": {
            "symbols": ["Ca", "Ca", "Ca", "Ca", "Zr", "Zr", "Zr", "Zr"]
            + ["O"] * 12
        }
    }
    contract = _electron_count_contract(
        method,
        result,
        {"nelec": "0", "nelec_delta": "-2"},
        require_charged=True,
    )

    assert contract["electron_count_neutral"] == pytest.approx(160.0)
    assert contract["electron_count_target"] == pytest.approx(158.0)
    assert contract["net_charge"] == 2
    assert contract["nelec"] == 0
    assert contract["nelec_delta"] == -2
    assert contract["charged"] is True


def test_native_charge_markers_keep_autoset_neutral_separate(tmp_path: Path) -> None:
    """The marker parser distinguishes AUTOSET Nneutral from adjusted Ntarget."""

    log = tmp_path / "running_scf.log"
    log.write_text(
        "AUTOSET number of electrons:  = 160\n"
        "WARNING: applying nelec_delta: -2\n"
        "nelec now: 158\n",
        encoding="utf-8",
    )

    markers = _native_electron_markers(log)

    assert markers["neutral"] == pytest.approx(160.0)
    assert markers["delta"] == pytest.approx(-2.0)
    assert markers["target"] == pytest.approx(158.0)


def test_relabelled_charged_copy_rejects_neutral_native_log(tmp_path: Path) -> None:
    """A relabelled neutral output cannot be accepted as charged evidence."""

    copied = _copy_task(CZO_TASK, tmp_path)
    _relabel_czo_copy_as_charged(copied)

    with pytest.raises(ValueError, match="charged native log must contain"):
        read_abacus_electronic_task(copied)


def test_charged_gate_flag_is_rejected_before_native_output(tmp_path: Path) -> None:
    """The first charged slice does not permit the slab-only gatefield path."""

    copied = _copy_task(CZO_TASK, tmp_path)
    _relabel_czo_copy_as_charged(copied, gate_flag=1)

    with pytest.raises(ValueError, match="gate_flag=0"):
        read_abacus_electronic_task(copied)
