"""Small, explicit periodic RDF observations for an accepted MD collection.

The function in this module consumes the native, already validated MLCC MD
collection.  It does not parse LAMMPS text, submit a calculation, infer a
production window, or identify peaks.  Coordinates stay in the native prism
Cartesian basis and the finite-particle normalization is kept in the result.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .md_conditions import read_md_conditions
from .md_sources import select_md_sources


_COLLECTION_SCHEMA = "mlcc.md-collection.v1"
_RDF_SCHEMA = "mlcc.md-rdf.v1"


def _read_collection(path: Path) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["schema"] != _COLLECTION_SCHEMA:
        raise ValueError("MD RDF collection schema must be mlcc.md-collection.v1")
    return record


def _observation_frames(
    frames: list[dict[str, Any]], observation_window: dict[str, Any]
) -> tuple[list[int], list[dict[str, Any]]]:
    if not isinstance(observation_window, dict):
        raise ValueError("MD RDF observation_window must be an object")
    if "kind" not in observation_window:
        raise ValueError("MD RDF observation_window requires kind")
    steps = [frame["step"] for frame in frames]
    kind = observation_window["kind"]
    if kind == "whole_record":
        if set(observation_window) != {"kind"}:
            raise ValueError("MD RDF whole_record must not contain step bounds or other selectors")
        indices = list(range(len(frames)))
    elif kind == "step_range":
        if set(observation_window) != {"kind", "start_step", "end_step"}:
            raise ValueError("MD RDF step_range requires only kind, start_step and end_step")
        start_step = observation_window["start_step"]
        end_step = observation_window["end_step"]
        if type(start_step) is not int or type(end_step) is not int:
            raise ValueError("MD RDF step_range endpoints must be integers")
        if end_step <= start_step:
            raise ValueError("MD RDF step_range end_step must be greater than start_step")
        if start_step not in steps or end_step not in steps:
            raise ValueError("MD RDF step_range endpoints must be recorded trajectory steps")
        indices = [index for index, step in enumerate(steps) if start_step <= step <= end_step]
    else:
        raise ValueError(f"MD RDF observation_window kind is unsupported: {kind}")
    return indices, [frames[index] for index in indices]


def _cell_from_prism(prism: Any) -> tuple[np.ndarray, float, np.ndarray, float]:
    """Return cell rows, volume, perpendicular heights and safe cutoff."""

    values = np.asarray(prism, dtype=float)
    if values.shape != (6,) or not np.isfinite(values).all():
        raise ValueError("MD RDF prism requires six finite lengths and tilts")
    lx, ly, lz, xy, xz, yz = (float(value) for value in values)
    if lx <= 0.0 or ly <= 0.0 or lz <= 0.0:
        raise ValueError("MD RDF prism lengths must be positive")
    cell = np.array([[lx, 0.0, 0.0], [xy, ly, 0.0], [xz, yz, lz]], dtype=float)
    volume = float(abs(np.linalg.det(cell)))
    if not math.isfinite(volume) or volume <= 0.0:
        raise ValueError("MD RDF cell volume must be positive and finite")
    inverse = np.linalg.inv(cell)
    # Cell rows are a,b,c.  The inverse-cell columns are the corresponding
    # reciprocal vectors; their norms are one over the opposite face heights.
    face_heights = 1.0 / np.linalg.norm(inverse, axis=0)
    cutoff_limit = float(0.5 * np.min(face_heights))
    if not np.isfinite(face_heights).all() or not math.isfinite(cutoff_limit):
        raise ValueError("MD RDF cell face heights must be finite")
    return cell, volume, face_heights, cutoff_limit


def _validate_grid(r_edges_angstrom: list[float], cutoff_limit: float) -> tuple[list[float], list[float]]:
    if not isinstance(r_edges_angstrom, list) or len(r_edges_angstrom) < 2:
        raise ValueError("MD RDF r_edges_angstrom must contain at least two boundaries")
    edges = []
    for value in r_edges_angstrom:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("MD RDF r_edges_angstrom must contain finite numbers")
        edges.append(float(value))
    if edges[0] != 0.0:
        raise ValueError("MD RDF r_edges_angstrom must start at zero")
    if any(right <= left for left, right in zip(edges, edges[1:])):
        raise ValueError("MD RDF r_edges_angstrom must be strictly increasing")
    if not edges[-1] < cutoff_limit:
        raise ValueError("MD RDF r_edges_angstrom maximum must be strictly below the triclinic half-face cutoff")
    shells = [
        float((4.0 * math.pi / 3.0) * (right**3 - left**3))
        for left, right in zip(edges, edges[1:])
    ]
    return edges, shells


def _wrap_distance(delta: np.ndarray, cell: np.ndarray, inverse: np.ndarray) -> float:
    fractional = delta @ inverse
    fractional -= np.floor(fractional + 0.5)
    wrapped = fractional @ cell
    return float(np.linalg.norm(wrapped))


def _validate_restricted_bounds(frame: dict[str, Any]) -> None:
    """Bind the stored prism to the native restricted-triclinic bounds."""

    bounds = np.asarray(frame["box_bounds_angstrom"], dtype=float)
    if bounds.shape != (3, 3) or not np.isfinite(bounds).all():
        raise ValueError("MD RDF native restricted-triclinic box bounds are invalid")
    prism = np.asarray(frame["lammps_prism_angstrom"], dtype=float)
    xlo, xhi, _ = (float(value) for value in bounds[0])
    ylo, yhi, _ = (float(value) for value in bounds[1])
    zlo, zhi, _ = (float(value) for value in bounds[2])
    xy, xz, yz = bounds[:, 2]
    tilt_extrema = [0.0, xy, xz, xy + xz]
    derived = np.array(
        [
            xhi - xlo - max(tilt_extrema) + min(tilt_extrema),
            yhi - ylo - abs(yz),
            zhi - zlo,
            bounds[0, 2],
            bounds[1, 2],
            bounds[2, 2],
        ],
        dtype=float,
    )
    if not np.allclose(derived, prism, rtol=0.0, atol=1.0e-8):
        raise ValueError("MD RDF prism cell differs from native restricted-triclinic box bounds")


def _pair_counts(
    positions: np.ndarray,
    cell: np.ndarray,
    first_positions: list[int],
    second_positions: list[int],
    edges: list[float],
) -> list[int]:
    inverse = np.linalg.inv(cell)
    counts = [0] * (len(edges) - 1)
    edge_array = np.asarray(edges)
    for center_position in first_positions:
        for neighbour_position in second_positions:
            if center_position == neighbour_position:
                continue
            distance = _wrap_distance(
                positions[neighbour_position] - positions[center_position], cell, inverse
            )
            if distance < edges[-1]:
                bin_index = int(np.searchsorted(edge_array, distance, side="right") - 1)
                counts[bin_index] += 1
    return counts


def _validate_frame_inputs(
    frames: list[dict[str, Any]], selected_indices: list[int], positions_count: int
) -> tuple[np.ndarray, float, np.ndarray, float]:
    first_prism = frames[selected_indices[0]]["lammps_prism_angstrom"]
    first_cell, first_volume, first_heights, first_cutoff = _cell_from_prism(first_prism)
    for index in selected_indices:
        frame = frames[index]
        if frame["coordinate_basis"] != "lammps_prism_cartesian":
            raise ValueError("MD RDF requires lammps_prism_cartesian trajectory coordinates")
        _validate_restricted_bounds(frame)
        positions = np.asarray(frame["positions_angstrom"], dtype=float)
        if positions.shape != (positions_count, 3) or not np.isfinite(positions).all():
            raise ValueError("MD RDF trajectory positions must be finite and match the atom mapping")
        cell, _, _, _ = _cell_from_prism(frame["lammps_prism_angstrom"])
        if not np.allclose(cell, first_cell, rtol=0.0, atol=1.0e-12):
            raise ValueError("MD RDF observation frames must use one fixed periodic cell")
    return first_cell, first_volume, first_heights, first_cutoff


def _frame_result(
    frame: dict[str, Any],
    collection_path: Path,
    cell: np.ndarray,
    volume: float,
    face_heights: np.ndarray,
    cutoff_limit: float,
    positions: np.ndarray,
    center_mapping: dict[str, Any],
    neighbour_mapping: dict[str, Any],
    center_element: str,
    neighbour_element: str,
    edges: list[float],
    shells: list[float],
) -> dict[str, Any]:
    center_positions = [int(value) for value in center_mapping["frame_position_indices"]]
    neighbour_positions = [int(value) for value in neighbour_mapping["frame_position_indices"]]
    center_count = len(center_positions)
    neighbour_count = len(neighbour_positions)
    eligible_count = neighbour_count - int(center_element == neighbour_element)
    if center_count <= 0 or neighbour_count <= 0 or eligible_count <= 0:
        raise ValueError("MD RDF selected species must have eligible atoms; same-species pairs require at least two atoms")
    rho_b = float(neighbour_count / volume)
    rho_eligible = float(eligible_count / volume)
    counts = _pair_counts(positions, cell, center_positions, neighbour_positions, edges)
    denominator = [float(center_count * rho_eligible * shell) for shell in shells]
    g_r = [float(count / value) for count, value in zip(counts, denominator)]
    coordination = []
    running = 0
    for count in counts:
        running += count
        coordination.append(float(running / center_count))
    return {
        "frame_index": int(frame["frame_index"]),
        "step": int(frame["step"]),
        "physical_time_ps": float(frame["physical_time_ps"]),
        "physical_time_fs": float(frame["physical_time_fs"]),
        "source_frame": {
            "collection": str(collection_path),
            "frame_index": int(frame["frame_index"]),
            "coordinate_basis": frame["coordinate_basis"],
            "source_indices": [int(value) for value in frame["source_indices"]],
        },
        "positions_angstrom": positions.tolist(),
        "cell": {
            "coordinate_basis": "lammps_prism_cartesian",
            "prism_angstrom": [float(value) for value in frame["lammps_prism_angstrom"]],
            "matrix_angstrom": cell.tolist(),
            "volume_angstrom3": volume,
            "face_heights_angstrom": [float(value) for value in face_heights],
            "cutoff_limit_angstrom": cutoff_limit,
        },
        "volume_angstrom3": volume,
        "face_heights_angstrom": [float(value) for value in face_heights],
        "cutoff_limit_angstrom": cutoff_limit,
        "atom_indices": {
            "center": {
                "element": center_element,
                "source_indices": [int(value) for value in center_mapping["source_indices"]],
                "source_atom_ids": [int(value) for value in center_mapping["source_atom_ids"]],
                "lammps_atom_ids": [int(value) for value in center_mapping["lammps_atom_ids"]],
                "frame_position_indices": center_positions,
            },
            "neighbour": {
                "element": neighbour_element,
                "source_indices": [int(value) for value in neighbour_mapping["source_indices"]],
                "source_atom_ids": [int(value) for value in neighbour_mapping["source_atom_ids"]],
                "lammps_atom_ids": [int(value) for value in neighbour_mapping["lammps_atom_ids"]],
                "frame_position_indices": neighbour_positions,
            },
        },
        "species_populations": {
            "center_element": center_element,
            "neighbour_element": neighbour_element,
            "N_A": center_count,
            "N_B": neighbour_count,
            "eligible_neighbors": eligible_count,
            "rho_B_per_angstrom3": rho_b,
            "rho_eligible_per_angstrom3": rho_eligible,
        },
        "directed_pair_counts": counts,
        "g_r": g_r,
        "coordination_number": coordination,
    }


def analyze_md_rdf(
    collection_path: str | Path,
    *,
    species_pair: list[str],
    r_edges_angstrom: list[float],
    observation_window: dict[str, Any],
) -> dict[str, Any]:
    """Calculate finite-sample periodic RDF counts for one explicit species pair."""

    path = Path(collection_path)
    record = _read_collection(path)
    conditions = read_md_conditions(path)
    if record["protocol"]["boundary"] != ["p", "p", "p"]:
        raise ValueError("MD RDF requires periodic boundary conditions in all three directions")
    if not isinstance(species_pair, list) or len(species_pair) != 2 or any(
        type(value) is not str or not value for value in species_pair
    ):
        raise ValueError("MD RDF species_pair must contain two non-empty element names")
    center_element, neighbour_element = species_pair
    elements = list(dict.fromkeys(record["legacy_final_result"]["elements"]))
    source_selection = select_md_sources(
        [path],
        model_id=record["model"]["model_id"],
        model_version=record["model"]["version"],
        potential_id=record["potential"]["potential_id"],
        potential_version=record["potential"]["version"],
        elements=elements,
    )
    if center_element not in elements or neighbour_element not in elements:
        missing = center_element if center_element not in elements else neighbour_element
        raise ValueError(f"MD RDF species {missing} is absent from the native element mapping")
    frames = record["trajectory"]["frames"]
    selected_indices, selected_frames = _observation_frames(frames, observation_window)
    positions_count = len(frames[0]["positions_angstrom"])
    cell, volume, face_heights, cutoff_limit = _validate_frame_inputs(
        frames, selected_indices, positions_count
    )
    edges, shells = _validate_grid(r_edges_angstrom, cutoff_limit)
    mappings = source_selection["sources"][0]["mapping"]["elements"]
    center_mapping = mappings[center_element]
    neighbour_mapping = mappings[neighbour_element]
    computed_frames = [
        _frame_result(
            frame,
            path,
            cell,
            volume,
            face_heights,
            cutoff_limit,
            np.asarray(frame["positions_angstrom"], dtype=float),
            center_mapping,
            neighbour_mapping,
            center_element,
            neighbour_element,
            edges,
            shells,
        )
        for frame in selected_frames
    ]
    g_r = [
        float(sum(frame["g_r"][index] for frame in computed_frames) / len(computed_frames))
        for index in range(len(edges) - 1)
    ]
    coordination = [
        float(sum(frame["coordination_number"][index] for frame in computed_frames) / len(computed_frames))
        for index in range(len(edges) - 1)
    ]
    total_counts = [
        int(sum(frame["directed_pair_counts"][index] for frame in computed_frames))
        for index in range(len(edges) - 1)
    ]
    first_frame = selected_frames[0]
    last_frame = selected_frames[-1]
    return {
        "schema": _RDF_SCHEMA,
        "status": "described_engineering_observation",
        "task_id": record["task_id"],
        "native_job": dict(record["native_job"]),
        "model": dict(record["model"]),
        "potential": dict(record["potential"]),
        "lineage": dict(record["lineage"]),
        "source_files": dict(record["source_files"]),
        "source_selection": source_selection,
        "conditions": conditions,
        "observation": {
            "request": dict(observation_window),
            "indices": [int(index) for index in selected_indices],
            "frame_indices": [int(frame["frame_index"]) for frame in selected_frames],
            "sample_count": len(selected_frames),
            "step_range": [int(first_frame["step"]), int(last_frame["step"])],
            "physical_time_ps_range": [float(first_frame["physical_time_ps"]), float(last_frame["physical_time_ps"])],
            "physical_time_fs_range": [float(first_frame["physical_time_fs"]), float(last_frame["physical_time_fs"])],
            "scope": "engineering_observation_not_production",
        },
        "species_pair": [center_element, neighbour_element],
        "grid": {
            "r_edges_angstrom": edges,
            "r_max_angstrom": edges[-1],
            "bin_count": len(edges) - 1,
            "bins": [
                {
                    "lower_angstrom": edges[index],
                    "upper_angstrom": edges[index + 1],
                    "shell_volume_angstrom3": shells[index],
                }
                for index in range(len(shells))
            ],
        },
        "normalization": {
            "pair_direction": "A_center_to_B_neighbor",
            "same_species_pair_counting": "each unordered same-species pair contributes two directed records",
            "rho_B_formula": "N_B / V",
            "rho_eligible_formula": "(N_B - delta_AB) / V",
            "g_r_formula": "directed_pair_counts / (N_A * rho_eligible * shell_volume)",
            "coordination_number_formula": "cumulative_directed_pair_counts / N_A",
            "density_unit": "1/angstrom^3",
            "count_scope": "finite periodic images within the strict half-face cutoff",
        },
        "frames": computed_frames,
        "aggregate": {
            "weighting": "equal_frame_mean",
            "frame_count": len(computed_frames),
            "mean_g_r": g_r,
            "mean_coordination_number": coordination,
            "total_directed_pair_counts": total_counts,
        },
        "first_peak": {
            "status": "unresolved",
            "position_angstrom": None,
            "reason": "no_pairs_within_legal_cutoff" if sum(total_counts) == 0 else "peak_analysis_not_performed",
        },
        "diagnostics": {
            "sampling_statistics": {"status": "unresolved", "reason": "not evaluated by the minimal RDF observation"},
            "equilibrium": {"status": "unresolved", "reason": "sampling and equilibrium are not evaluated"},
            "production": {"status": "unresolved", "reason": "the observation range is not a production qualification"},
        },
        "production_qualification": False,
        "sampling_equilibrium_qualified": False,
    }


__all__ = ["analyze_md_rdf"]
