"""Focused checks for the scalar FNV charge-correction adapter.

The released GaN files are an external reference fixture.  Mathematical
fixtures in the remaining tests exercise only the new adapter contract; they
do not stand in for native ABACUS output.
"""

from __future__ import annotations

import copy
from importlib.metadata import version as package_version
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.analysis.defects.corrections import freysoldt as released_backend
import pytest

import mlcc.charge_correction as charge_correction
from mlcc.electrostatic_potential import BOHR_TO_ANGSTROM, RY_TO_EV
from mlcc.potential_alignment import _ENERGY_ZERO
from test_potential_alignment import _write_wrapper_fixture


def _parameters() -> dict[str, Any]:
    return {
        "q": 1,
        "dielectric": {
            "value": 5.0,
            "unit": "dimensionless",
            "source": "external_reference_v_N_GaN",
        },
        "defect_frac_coords": [0.16666658, 0.33333331, 0.16008467],
        "q_model": {"beta": 1.0, "expnorm": 0.0, "gamma": 1.0, "unit": "Bohr"},
        "integration": {"energy_cutoff_eV": 520.0, "mad_tol": 1.0e-4, "step": 1.0e-4},
        "sampling": {
            "policy": "midpoint_after_defect_shift",
            "axes": [0, 1, 2],
            "width_angstrom": 1.0,
        },
    }


def _periodic_inputs(
    shape: tuple[int, int, int] = (4, 4, 4),
) -> tuple[list[list[float]], list[list[float]], list[list[float]], list[list[float]]]:
    cell = [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]]
    grids = [
        (np.arange(n, dtype=float) * cell[axis][axis] / n).tolist()
        for axis, n in enumerate(shape)
    ]
    host = [np.zeros(n, dtype=float).tolist() for n in shape]
    defect = [(np.arange(n, dtype=float) * 0.1).tolist() for n in shape]
    return cell, grids, host, defect


def test_released_backend_version_is_pinned() -> None:
    assert package_version("pymatgen-analysis-defects") == charge_correction.BACKEND_VERSION


def test_official_gan_q1_reference_uses_locpot_and_tag_corr_align() -> None:
    reference_text = os.environ.get("MLCC_FNV_REFERENCE")
    if not reference_text:
        pytest.skip("MLCC_FNV_REFERENCE must point to the read-only v_N_GaN fixture")
    reference = Path(reference_text)
    if not reference.is_dir():
        pytest.skip("MLCC_FNV_REFERENCE is unavailable on this host")

    locpot = released_backend.Locpot
    bulk = locpot.from_file(reference / "bulk" / "LOCPOT.gz")
    defect = locpot.from_file(reference / "q1" / "LOCPOT.gz")
    q_model = released_backend.QModel(beta=1.0, expnorm=0.0, gamma=1.0)
    official = released_backend.get_freysoldt_correction(
        q=1,
        dielectric=5.0,
        bulk_locpot=bulk,
        defect_locpot=defect,
        defect_frac_coords=_parameters()["defect_frac_coords"],
        energy_cutoff=520.0,
        mad_tol=1.0e-4,
        q_model=q_model,
        step=1.0e-4,
    )

    corr_align = reference / "q1" / "corr_align.out"
    reference_line = corr_align.read_text(encoding="utf-8").splitlines()[-1]
    expected = float(reference_line.split()[3])
    # sxdefectalign is a separate implementation: retain its difference below.
    # The adapter contract is equality to the actual pinned backend invocation.
    assert official.correction_energy == pytest.approx(0.1799, abs=5.0e-4)

    grids = [bulk.get_axis_grid(axis) for axis in range(3)]
    host = [bulk.get_average_along_axis(axis) for axis in range(3)]
    defect_avg = [defect.get_average_along_axis(axis) for axis in range(3)]
    adapted = charge_correction.freysoldt_correction(
        defect.structure.lattice.matrix,
        grids,
        host,
        defect_avg,
        _parameters(),
    )
    assert adapted["total_eV"] == pytest.approx(float(official.correction_energy), abs=1.0e-12)
    assert adapted["backend"]["version"] == "2026.3.20"
    result_path_text = os.environ.get("MLCC_FNV_RESULT")
    if result_path_text:
        Path(result_path_text).write_text(
            json.dumps(
                {
                    "schema": "mlcc.fnv.external-reference-evidence.v1",
                    "source": {
                        "kind": "external_reference",
                        "engine": "VASP",
                        "release_tag": "v2026.3.20",
                        "backend_source": charge_correction.BACKEND_SOURCE,
                        "bulk_locpot": str(reference / "bulk" / "LOCPOT.gz"),
                        "defect_locpot": str(reference / "q1" / "LOCPOT.gz"),
                        "corr_align": str(corr_align),
                    },
                    "official": {
                        "correction_energy_eV": float(official.correction_energy),
                        "corr_align_reference_eV": expected,
                        "difference_from_corr_align_eV": float(official.correction_energy) - expected,
                    },
                    "adapted": adapted,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def test_scalar_adapter_passes_qmodel_sampling_and_counts_q_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell, grids, host, defect = _periodic_inputs()
    parameters = _parameters()
    parameters["q"] = 2
    captured: dict[str, Any] = {"pot": []}

    def fake_es(lattice, q, dielectric, q_model, **kwargs):
        captured["es"] = (lattice, q, dielectric, q_model, kwargs)
        return 1.25

    def fake_pot(grid, pureavg, defavg, lattice, q, defect_frac_coords, axis, dielectric, q_model, **kwargs):
        captured["pot"].append((grid, pureavg, defavg, lattice, q, defect_frac_coords, axis, dielectric, q_model, kwargs))
        size = len(grid)
        return 0.1 * (axis + 1), {
            "pot_plot_data": {
                "Vr": [0.0] * size,
                "dft_diff": [0.0] * size,
                "short_range": [0.0] * size,
                "check": [1, 3],
            }
        }

    monkeypatch.setattr(released_backend, "perform_es_corr", fake_es)
    monkeypatch.setattr(released_backend, "perform_pot_corr", fake_pot)

    result = charge_correction.freysoldt_correction(cell, grids, host, defect, parameters)

    _, q, dielectric, q_model, es_kwargs = captured["es"]
    assert q == 2
    assert dielectric == 5.0
    assert (q_model.beta, q_model.expnorm, q_model.gamma) == (1.0, 0.0, 1.0)
    assert es_kwargs == {"energy_cutoff": 520.0, "mad_tol": 1.0e-4, "step": 1.0e-4}
    assert len(captured["pot"]) == 3
    assert all(call[-1] == {"mad_tol": 1.0e-4, "widthsample": 1.0} for call in captured["pot"])
    assert result["axis_alignment_shifts_eV"] == pytest.approx([0.1, 0.2, 0.3])
    assert result["mean_alignment_shift_eV"] == pytest.approx(0.2)
    assert result["potential_alignment_eV"] == pytest.approx(0.4)
    assert result["total_eV"] == pytest.approx(1.65)


def test_periodic_endpoint_is_rejected() -> None:
    cell, grids, host, defect = _periodic_inputs()
    grids[1] = np.linspace(0.0, cell[1][1], len(grids[1])).tolist()

    with pytest.raises(ValueError, match="without the periodic endpoint"):
        charge_correction.freysoldt_correction(cell, grids, host, defect, _parameters())


def test_dielectric_tensor_is_rejected_without_averaging() -> None:
    cell, grids, host, defect = _periodic_inputs()
    parameters = _parameters()
    parameters["dielectric"]["value"] = [[5.0, 0.0, 0.0], [0.0, 6.0, 0.0], [0.0, 0.0, 7.0]]

    with pytest.raises(ValueError, match="scalar FNV requires"):
        charge_correction.freysoldt_correction(cell, grids, host, defect, parameters)


def _saved_potential(values_ry: list[float], *, shape: tuple[int, int, int] = (2, 3, 4)) -> dict[str, Any]:
    steps_bohr = np.eye(3).tolist()
    cell_bohr = (np.asarray(steps_bohr) * np.asarray(shape)[:, None]).tolist()
    return {
        "schema": "mlcc.abacus-electrostatic-potential.v1",
        "kind": "local_ionic_plus_hartree",
        "value_unit": "Ry",
        "geometry_unit": "Bohr",
        "sign_convention": "electron_potential_energy",
        "energy_zero": copy.deepcopy(_ENERGY_ZERO),
        "includes_XC": False,
        "includes_nonlocal_pseudopotential": False,
        "cube": {
            "schema": "mlcc.abacus-electrostatic-cube.v1",
            "shape": list(shape),
            "origin_bohr": [0.0, 0.0, 0.0],
            "step_vectors_bohr": steps_bohr,
            "cell_bohr": cell_bohr,
            "origin_angstrom": [0.0, 0.0, 0.0],
            "step_vectors_angstrom": (np.asarray(steps_bohr) * BOHR_TO_ANGSTROM).tolist(),
            "cell_angstrom": (np.asarray(cell_bohr) * BOHR_TO_ANGSTROM).tolist(),
            "values_Ry": list(values_ry),
            "values_eV": (np.asarray(values_ry) * RY_TO_EV).tolist(),
            "axis_order": "x_outer_y_middle_z_inner",
            "flat_index": "(ix*ny+iy)*nz+iz",
            "unit_conversion": {"Ry_to_eV": RY_TO_EV, "Bohr_to_angstrom": BOHR_TO_ANGSTROM},
        },
    }


def test_saved_abacus_grid_converts_ry_bohr_and_preserves_z_fast_planar_means(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shape = (2, 3, 4)
    host_values = [float(i) for i in range(np.prod(shape))]
    defect_values = [value + 1.0 for value in host_values]
    host = _saved_potential(host_values, shape=shape)
    defect = _saved_potential(defect_values, shape=shape)
    captured: dict[str, Any] = {}

    def fake_correction(cell, grids, host_planar, defect_planar, parameters):
        captured.update(
            cell=cell,
            grids=grids,
            host_planar=host_planar,
            defect_planar=defect_planar,
            parameters=parameters,
        )
        return {"schema": "fixture", "total_eV": 0.0}

    monkeypatch.setattr(charge_correction, "freysoldt_correction", fake_correction)
    result = charge_correction.correction_from_saved_grids(host, defect, {"q": 1})

    assert result == {"schema": "fixture", "total_eV": 0.0}
    assert [len(grid) for grid in captured["grids"]] == [2, 3, 4]
    assert all(grid[-1] < captured["cell"][axis][axis] for axis, grid in enumerate(captured["grids"]))
    host_array = np.asarray(host_values, dtype=float).reshape(shape) * RY_TO_EV
    defect_array = np.asarray(defect_values, dtype=float).reshape(shape) * RY_TO_EV
    expected_host = [host_array.mean(axis=tuple(i for i in range(3) if i != axis)) for axis in range(3)]
    expected_defect = [defect_array.mean(axis=tuple(i for i in range(3) if i != axis)) for axis in range(3)]
    for actual, expected in zip(captured["host_planar"], expected_host):
        assert actual == pytest.approx(expected)
    for actual, expected in zip(captured["defect_planar"], expected_defect):
        assert actual == pytest.approx(expected)


def test_original_backend_error_is_not_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    cell, grids, host, defect = _periodic_inputs()

    def fail(*_args, **_kwargs):
        raise RuntimeError("published backend failure")

    monkeypatch.setattr(released_backend, "perform_es_corr", fail)
    with pytest.raises(RuntimeError, match="published backend failure"):
        charge_correction.freysoldt_correction(cell, grids, host, defect, _parameters())


def test_build_charge_correction_computes_bound_software_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, pair, alignment_request_path = _write_wrapper_fixture(tmp_path)
    for role, electronic_path in (("host", "host-electronic.json"), ("defect", "defect-electronic.json")):
        pair[role]["levels"]["vbm_reference"] = "software_contract_fixture_levels.vbm_eV"
        pair[role]["electronic_source_file"] = str(tmp_path / electronic_path)

    for role, value_eV in (("host", 0.0), ("defect", 1.0)):
        potential_path = alignment_request_path.parent / (
            "host-potential.json" if role == "host" else "defect-potential.json"
        )
        potential = json.loads(potential_path.read_text(encoding="utf-8"))
        shape = (8, 8, 8)
        step_bohr = 0.5 / BOHR_TO_ANGSTROM
        steps_bohr = [[step_bohr, 0.0, 0.0], [0.0, step_bohr, 0.0], [0.0, 0.0, step_bohr]]
        cell_bohr = [[4.0 / BOHR_TO_ANGSTROM, 0.0, 0.0], [0.0, 4.0 / BOHR_TO_ANGSTROM, 0.0], [0.0, 0.0, 4.0 / BOHR_TO_ANGSTROM]]
        count = int(np.prod(shape))
        cube = potential["cube"]
        cube["shape"] = list(shape)
        cube["step_vectors_bohr"] = steps_bohr
        cube["cell_bohr"] = cell_bohr
        cube["step_vectors_angstrom"] = [[value * BOHR_TO_ANGSTROM for value in row] for row in steps_bohr]
        cube["cell_angstrom"] = [[value * BOHR_TO_ANGSTROM for value in row] for row in cell_bohr]
        cube["values_Ry"] = [value_eV / RY_TO_EV] * count
        cube["values_eV"] = [value_eV] * count
        cube["print_precision"]["cell_row_half_quantum_bohr"] = [n * 0.5e-6 for n in shape]
        potential_path.write_text(json.dumps(potential, indent=2) + "\n", encoding="utf-8")

    alignment_request = json.loads(alignment_request_path.read_text(encoding="utf-8"))
    request = {
        "schema": "mlcc.charge-correction-request.v1",
        "correction_id": "software-contract-charge-correction",
        "host_electronic_path": alignment_request["host_electronic_path"],
        "defect_electronic_path": alignment_request["defect_electronic_path"],
        "descriptor_path": alignment_request["descriptor_path"],
        "host_potential_path": alignment_request["host_potential_path"],
        "defect_potential_path": alignment_request["defect_potential_path"],
        "parameters": _parameters(),
    }
    request_path = tmp_path / "charge-correction-request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        charge_correction,
        "build_defect_electronic_reference",
        lambda *args: copy.deepcopy(pair),
    )

    result = charge_correction.build_charge_correction(request_path)

    assert result["status"] == "computed"
    assert result["missing"] == []
    assert result["calculation"] is not None
    assert result["correction_terms"] == result["calculation"]["correction_terms"]
    assert result["correction_terms"]["total_eV"] == result["calculation"]["total_eV"]
    assert result["correction_terms"]["image_charge_eV"] == result["calculation"]["image_charge_eV"]
    assert result["correction_terms"]["potential_alignment_eV"] == result["calculation"]["potential_alignment_eV"]
    assert result["evidence_kind"] == "software_contract_only"
    assert result["calculation"]["backend"]["version"] == charge_correction.BACKEND_VERSION

    result_path_text = os.environ.get("MLCC_SOFTWARE_CORRECTION_RESULT")
    if result_path_text:
        Path(result_path_text).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
