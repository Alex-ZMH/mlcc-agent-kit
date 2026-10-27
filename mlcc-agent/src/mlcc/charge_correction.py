"""Scalar FNV from explicit periodic electron-potential-energy grids."""
from __future__ import annotations

from copy import deepcopy
from importlib.metadata import version
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .defect_references import build_defect_electronic_reference
from .electrostatic_potential import HEADER_HALF_QUANTUM_BOHR
from .potential_alignment import _check_lineage, _grid, _validate_saved_potential


BACKEND_VERSION = "2026.3.20"
BACKEND_SOURCE = "https://github.com/materialsproject/pymatgen-analysis-defects/tree/v2026.3.20"


def _parameters(parameters: Mapping[str, Any]) -> None:
    if type(parameters["q"]) is not int:
        raise ValueError("FNV q must be an integer; positive q removes electrons")
    dielectric = parameters["dielectric"]
    epsilon = dielectric["value"]
    if type(epsilon) not in (int, float) or not np.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("scalar FNV requires an explicit positive scalar dielectric; tensors are not averaged")
    if dielectric["unit"] != "dimensionless" or not dielectric["source"]:
        raise ValueError("dielectric needs dimensionless units and an explicit source")
    position = np.asarray(parameters["defect_frac_coords"], dtype=float)
    if position.shape != (3,) or not np.isfinite(position).all() or np.any(position < 0) or np.any(position >= 1):
        raise ValueError("defect_frac_coords must contain three explicit fractional coordinates in [0,1)")
    model = parameters["q_model"]
    if model["unit"] != "Bohr" or model["beta"] <= 0 or model["gamma"] <= 0 or not 0 <= model["expnorm"] <= 1:
        raise ValueError("QModel requires positive beta/gamma in Bohr and expnorm in [0,1]")
    integration = parameters["integration"]
    if any(not np.isfinite(integration[k]) or integration[k] <= 0 for k in ("energy_cutoff_eV", "mad_tol", "step")):
        raise ValueError("FNV integration parameters must be explicit positive finite values")
    sampling = parameters["sampling"]
    if sampling["policy"] != "midpoint_after_defect_shift" or sampling["axes"] != [0, 1, 2]:
        raise ValueError("scalar FNV uses explicit midpoint-after-defect-shift windows on axes [0,1,2]")
    if not np.isfinite(sampling["width_angstrom"]) or sampling["width_angstrom"] <= 0:
        raise ValueError("sampling width must be positive angstrom")


def freysoldt_correction(
    cell_angstrom: Sequence[Sequence[float]],
    axis_grids_angstrom: Sequence[Sequence[float]],
    host_planar_eV: Sequence[Sequence[float]],
    defect_planar_eV: Sequence[Sequence[float]],
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Call the pinned released backend, preserving its errors and signs."""
    _parameters(parameters)
    installed = version("pymatgen-analysis-defects")
    if installed != BACKEND_VERSION:
        raise ValueError(f"FNV backend requires {BACKEND_VERSION}; installed {installed}")
    from pymatgen.analysis.defects.corrections.freysoldt import perform_es_corr, perform_pot_corr
    from pymatgen.analysis.defects.utils import QModel
    from pymatgen.core import Lattice

    lattice = Lattice(cell_angstrom)
    q = parameters["q"]
    epsilon = parameters["dielectric"]["value"]
    model = parameters["q_model"]
    q_model = QModel(beta=model["beta"], expnorm=model["expnorm"], gamma=model["gamma"])
    integration = parameters["integration"]
    width = parameters["sampling"]["width_angstrom"]
    if not len(axis_grids_angstrom) == len(host_planar_eV) == len(defect_planar_eV) == 3:
        raise ValueError("three periodic axis grids and planar potentials are required")
    axes = []
    for axis in range(3):
        grid = np.asarray(axis_grids_angstrom[axis], dtype=float)
        host = np.asarray(host_planar_eV[axis], dtype=float)
        defect = np.asarray(defect_planar_eV[axis], dtype=float)
        if grid.ndim != 1 or len(grid) < 2 or host.shape != grid.shape or defect.shape != grid.shape:
            raise ValueError("each periodic grid must match its host/defect planar potential")
        expected = np.arange(len(grid)) * lattice.abc[axis] / len(grid)
        if not np.allclose(grid, expected, rtol=0, atol=1e-10):
            raise ValueError("FNV requires x_i=i*L/N without the periodic endpoint")
        if not np.isfinite(host).all() or not np.isfinite(defect).all():
            raise ValueError("planar potentials must contain finite electron energies in eV")
        half_window = int((width / 2) / (grid[1] - grid[0]))
        middle = len(grid) // 2
        if middle - half_window < 0 or middle + half_window >= len(grid):
            raise ValueError("explicit sampling window exceeds the periodic grid")
        axes.append((grid, host, defect))
    image_energy = perform_es_corr(
        lattice, q, epsilon, q_model, energy_cutoff=integration["energy_cutoff_eV"],
        mad_tol=integration["mad_tol"], step=integration["step"],
    )
    shifts, samples = [], []
    for axis, (grid, host, defect) in enumerate(axes):
        shift, metadata = perform_pot_corr(
            grid, host, defect, lattice, q, parameters["defect_frac_coords"], axis,
            epsilon, q_model, mad_tol=integration["mad_tol"], widthsample=width,
        )
        plot = metadata["pot_plot_data"]
        shifts.append(float(shift))
        samples.append({
            "axis": axis, "axis_grid_angstrom": grid.tolist(),
            "long_range_model_eV": np.asarray(plot["Vr"]).tolist(),
            "defect_minus_host_eV": np.asarray(plot["dft_diff"]).tolist(),
            "short_range_eV": np.asarray(plot["short_range"]).tolist(),
            "sampling_indices_half_open": list(plot["check"]),
            "alignment_shift_eV": float(shift),
        })
    mean_shift = float(np.mean(shifts))
    alignment_energy = q * mean_shift
    total = float(image_energy + alignment_energy)
    return {
        "schema": "mlcc.scalar-fnv.v1", "method": "FNV_scalar",
        "backend": {"package": "pymatgen-analysis-defects", "version": installed, "source": BACKEND_SOURCE},
        "parameters": deepcopy(dict(parameters)), "cell_angstrom": lattice.matrix.tolist(),
        "image_charge_eV": float(image_energy), "axis_alignment_shifts_eV": shifts,
        "mean_alignment_shift_eV": mean_shift, "alignment_charge_multiplier": q,
        "potential_alignment_eV": alignment_energy, "total_eV": total,
        "convention": "electron potential energy; short=Vdefect-Vhost-Vmodel; alignment=q*mean(short); total=image+alignment",
        "axes": samples,
        "correction_terms": {
            "image_charge_eV": float(image_energy), "potential_alignment_eV": alignment_energy,
            "total_eV": total, "method": "FNV_scalar",
        },
    }


def correction_from_saved_grids(
    host_potential: Mapping[str, Any], defect_potential: Mapping[str, Any], parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Use ABACUS Ry/Bohr grids, with their recorded cell and electron sign."""
    host_shape, host = _grid(host_potential)
    defect_shape, defect = _grid(defect_potential)
    if host_shape != defect_shape:
        raise ValueError("FNV host/defect grid shapes differ; no resampling is performed")
    for key in ("origin_bohr", "step_vectors_bohr", "cell_bohr"):
        tolerance = 2 * HEADER_HALF_QUANTUM_BOHR
        if key == "cell_bohr":
            tolerance = tolerance * np.asarray(host_shape)[:, None]
        if np.any(np.abs(np.asarray(host_potential["cube"][key]) - np.asarray(defect_potential["cube"][key])) > tolerance + 1e-12):
            raise ValueError(f"FNV host/defect {key} differ beyond cube header precision")
    cube = defect_potential["cube"]
    if np.any(np.asarray(cube["origin_bohr"]) != 0):
        raise ValueError("current ABACUS FNV adapter requires the native zero-origin periodic grid")
    cell = np.asarray(cube["cell_angstrom"])
    lengths = np.linalg.norm(cell, axis=1)
    grids = [np.arange(n) * lengths[axis] / n for axis, n in enumerate(defect_shape)]
    averages = lambda values: [values.mean(axis=tuple(i for i in range(3) if i != axis)) for axis in range(3)]
    return freysoldt_correction(cell, grids, averages(host), averages(defect), parameters)


def build_charge_correction(request_path: str | Path) -> dict[str, Any]:
    """Bind existing sources, calculate FNV, or retain explicitly missing data."""
    request_file = Path(request_path).resolve()
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if request["schema"] != "mlcc.charge-correction-request.v1":
        raise ValueError("unsupported charge-correction request schema")
    paths = {key: None if request[key] is None else str((request_file.parent / request[key]).resolve()) for key in (
        "host_electronic_path", "defect_electronic_path", "descriptor_path", "host_potential_path", "defect_potential_path",
    )}
    pair = build_defect_electronic_reference(paths["host_electronic_path"], paths["defect_electronic_path"], paths["descriptor_path"])
    lineage = _check_lineage(pair)
    missing, grids, potentials = [], {}, {}
    for role in ("host", "defect"):
        path = paths[f"{role}_potential_path"]
        if path is None:
            missing.append(f"{role}_potential")
            potentials[role] = None
        else:
            grids[role] = json.loads(Path(path).read_text(encoding="utf-8"))
            potentials[role] = {**_validate_saved_potential(grids[role], pair[role]), "saved_potential_path": path}
    parameters = request["parameters"]
    if parameters is None:
        missing.append("parameters")
    else:
        _parameters(parameters)
        if parameters["q"] != pair["defect"]["charge"]["q"]:
            raise ValueError("FNV q differs from the bound defect source")
    calculation = None
    if not missing:
        if pair["method_comparison"]["same_recorded_comparison_fields"] is not True:
            raise ValueError("FNV requires matching recorded host/defect methods")
        calculation = correction_from_saved_grids(grids["host"], grids["defect"], parameters)
    software = any(record["electronic_source"].get("evidence_kind") == "software_contract_only" for record in (pair["host"], pair["defect"]))
    software = software or any(p is not None and p["evidence_kind"] == "software_contract_only" for p in potentials.values())
    return {
        "schema": "mlcc.charge-correction.v1", "correction_id": request["correction_id"],
        "request_path": str(request_file), "status": "missing" if missing else "computed",
        "references": pair, "source_paths": paths, "potentials": potentials, "lineage": lineage,
        "parameters": deepcopy(parameters), "missing": missing, "calculation": calculation,
        "correction_terms": None if calculation is None else calculation["correction_terms"],
        "evidence_kind": "software_contract_only" if software else "native_saved_source",
        "scientific_qualification": False, "production_qualification": False,
    }
