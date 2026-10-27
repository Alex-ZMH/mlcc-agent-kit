"""MD-07 RDF contract tests.

The geometry cases below are mathematical fixtures.  The job45 case consumes
the accepted native collection and is intended to run only in the v100 Slurm
acceptance job; no test starts LAMMPS or another numerical task.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil

import numpy as np
import pytest

from mlcc.md_rdf import (
    _cell_from_prism,
    _frame_result,
    _pair_counts,
    _validate_grid,
    _validate_restricted_bounds,
    _wrap_distance,
    analyze_md_rdf,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COLLECTION = ROOT / "workspace" / "reports" / "md-series-v011-v001" / "collection.json"


def _source() -> Path:
    return Path(os.environ.get("MLCC_MD_COLLECTION", str(DEFAULT_COLLECTION)))


def _load_copy(tmp_path: Path, name: str) -> tuple[Path, dict[str, object]]:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    target = tmp_path / f"{name}.json"
    shutil.copy2(source, target)
    return target, json.loads(target.read_text(encoding="utf-8"))


def _write(path: Path, record: dict[str, object]) -> None:
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _mapping(element: str, positions: list[int]) -> dict[str, object]:
    return {
        "source_indices": list(positions),
        "source_atom_ids": list(positions),
        "lammps_atom_ids": [position + 1 for position in positions],
        "frame_position_indices": list(positions),
    }


def _geometry_frame(
    *,
    elements: tuple[str, str],
    positions: list[list[float]],
    prism: list[float] | None = None,
) -> dict[str, object]:
    prism = [4.0, 4.0, 4.0, 0.0, 0.0, 0.0] if prism is None else prism
    cell, volume, heights, cutoff = _cell_from_prism(prism)
    edges, shells = _validate_grid([0.0, 1.5, 1.9], cutoff)
    frame = {
        "frame_index": 0,
        "step": 0,
        "physical_time_ps": 0.0,
        "physical_time_fs": 0.0,
        "coordinate_basis": "lammps_prism_cartesian",
        "lammps_prism_angstrom": prism,
        "source_indices": list(range(len(positions))),
    }
    result = _frame_result(
        frame,
        Path("geometry.json"),
        cell,
        volume,
        heights,
        cutoff,
        np.asarray(positions, dtype=float),
        _mapping(elements[0], [0, 1] if elements[0] == elements[1] else [0]),
        _mapping(elements[1], [0, 1] if elements[0] == elements[1] else [1]),
        elements[0],
        elements[1],
        edges,
        shells,
    )
    return result


def test_cell_uses_prism_rows_and_inverse_columns_for_skew_cutoff() -> None:
    cell, volume, heights, cutoff = _cell_from_prism([4.0, 5.0, 6.0, 1.0, 0.5, 0.75])

    assert np.allclose(cell, [[4.0, 0.0, 0.0], [1.0, 5.0, 0.0], [0.5, 0.75, 6.0]])
    assert volume == pytest.approx(120.0)
    expected = [120.0 / np.linalg.norm(np.cross(cell[j], cell[k])) for j, k in [(1, 2), (2, 0), (0, 1)]]
    assert np.allclose(heights, expected)
    assert cutoff == pytest.approx(0.5 * min(expected))


def test_wrap_distance_handles_skew_periodic_boundary() -> None:
    cell, _, _, _ = _cell_from_prism([4.0, 5.0, 6.0, 1.0, 0.5, 0.75])
    inverse = np.linalg.inv(cell)
    delta = np.array([0.02, 0.01, 0.0]) @ cell

    assert _wrap_distance(delta, cell, inverse) == pytest.approx(np.linalg.norm(delta))
    boundary = np.array([0.98, 0.98, 0.0]) @ cell
    assert _wrap_distance(boundary, cell, inverse) == pytest.approx(np.linalg.norm(np.array([-0.02, -0.02, 0.0]) @ cell))
    assert _pair_counts(np.array([[0, 0, 0], boundary]), cell, [0, 1], [0, 1], [0, 0.2, 0.5]) == [2, 0]
    _validate_restricted_bounds({"lammps_prism_angstrom": [4, 5, 6, 1, 0.5, 0.75],
                                 "box_bounds_angstrom": [[0, 5.5, 1], [0, 5.75, 0.5], [0, 6, 0.75]]})


def test_pair_counts_are_directed_for_same_species() -> None:
    cell, _, _, _ = _cell_from_prism([4.0, 4.0, 4.0, 0.0, 0.0, 0.0])
    positions = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=float)
    counts = _pair_counts(positions, cell, [0, 1], [0, 1], [0.0, 1.5, 1.9])

    assert counts == [2, 0]


def test_same_and_different_species_use_eligible_density() -> None:
    # Two distinct species have one directed pair; the same two atoms have
    # two directed records and N_B - delta_AB removes the self population.
    different = _geometry_frame(elements=("A", "B"), positions=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    same = _geometry_frame(elements=("A", "A"), positions=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

    assert different["directed_pair_counts"] == [1, 0]
    assert same["directed_pair_counts"] == [2, 0]
    assert different["species_populations"]["rho_B_per_angstrom3"] == pytest.approx(1.0 / 64.0)
    assert same["species_populations"]["rho_B_per_angstrom3"] == pytest.approx(2.0 / 64.0)
    assert same["species_populations"]["rho_eligible_per_angstrom3"] == pytest.approx(1.0 / 64.0)
    assert same["g_r"][0] == pytest.approx(different["g_r"][0])
    assert same["g_r"][0] == pytest.approx(64.0 / (4 * math.pi / 3 * 1.5**3))
    assert same["coordination_number"] == [1.0, 1.0]


def test_rejects_cutoff_beyond_short_skew_face() -> None:
    _, _, _, cutoff = _cell_from_prism([4.0, 5.0, 6.0, 1.0, 0.5, 0.75])
    with pytest.raises(ValueError, match="strictly below"):
        _validate_grid([0.0, cutoff], cutoff)


def test_job45_rdf_whole_record_is_zero_inside_legal_cutoff() -> None:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    before = source.read_text(encoding="utf-8")
    result = analyze_md_rdf(
        source,
        species_pair=["Ni", "Ni"],
        r_edges_angstrom=[0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75],
        observation_window={"kind": "whole_record"},
    )

    assert source.read_text(encoding="utf-8") == before
    assert result["schema"] == "mlcc.md-rdf.v1"
    assert result["native_job"]["scheduler_job_id"] == "45"
    assert result["observation"]["sample_count"] == 11
    assert result["observation"]["frame_indices"] == list(range(11))
    assert result["production_qualification"] is False
    assert result["first_peak"]["status"] == "unresolved"
    assert result["aggregate"]["total_directed_pair_counts"] == [0] * 7
    assert result["aggregate"]["mean_g_r"] == [0.0] * 7


def test_job45_explicit_trajectory_window() -> None:
    result = analyze_md_rdf(_source(), species_pair=["Ni", "Ni"], r_edges_angstrom=[0.0, 1.75],
                            observation_window={"kind": "step_range", "start_step": 50, "end_step": 100})
    assert result["observation"]["frame_indices"] == [5, 6, 7, 8, 9, 10]
    assert result["observation"]["physical_time_fs_range"] == [50.0, 100.0]
    assert result["conditions"]["windows"]["production_window"]["status"] == "unresolved_missing"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda record: [frame.update({"coordinate_basis": "source_cartesian"}) for frame in record["trajectory"]["frames"]], "lammps_prism_cartesian"),
        (lambda record: record["protocol"].update({"boundary": ["p", "p", "f"]}), "periodic boundary"),
    ],
)
def test_rejects_basis_or_nonperiodic_input(tmp_path: Path, mutation, message: str) -> None:
    path, record = _load_copy(tmp_path, "invalid")
    mutation(record)
    _write(path, record)
    with pytest.raises(ValueError, match=message):
        analyze_md_rdf(
            path,
            species_pair=["Ni", "Ni"],
            r_edges_angstrom=[0.0, 0.25, 0.5],
            observation_window={"kind": "whole_record"},
        )


def test_rejects_missing_species_grid_and_window(tmp_path: Path) -> None:
    source = _source()
    with pytest.raises(ValueError, match="absent"):
        analyze_md_rdf(source, species_pair=["O", "O"], r_edges_angstrom=[0.0, 0.5], observation_window={"kind": "whole_record"})
    with pytest.raises(ValueError, match="strictly below"):
        analyze_md_rdf(source, species_pair=["Ni", "Ni"], r_edges_angstrom=[0.0, 1.761], observation_window={"kind": "whole_record"})
    with pytest.raises(ValueError, match="endpoints"):
        analyze_md_rdf(source, species_pair=["Ni", "Ni"], r_edges_angstrom=[0.0, 0.5], observation_window={"kind": "step_range", "start_step": 1, "end_step": 100})


def test_rejects_prism_mismatch_with_native_box_bounds(tmp_path: Path) -> None:
    path, record = _load_copy(tmp_path, "bounds")
    record["trajectory"]["frames"][0]["box_bounds_angstrom"][0][1] += 0.1
    _write(path, record)

    with pytest.raises(ValueError, match="box bounds"):
        analyze_md_rdf(
            path,
            species_pair=["Ni", "Ni"],
            r_edges_angstrom=[0.0, 0.5],
            observation_window={"kind": "whole_record"},
        )
