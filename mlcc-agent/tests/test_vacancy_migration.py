"""Pure local-site vacancy migration tests.

The MD/NEB readers and Slurm acceptance are deliberately outside this test
file.  These cases exercise only fixed-cell assignment and adjacent-frame
semantics.
"""

from __future__ import annotations

import numpy as np
import pytest

from mlcc.vacancy_migration import analyze_vacancy_frames


CELL = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]
SITE_IDS = [10, 30, 50]
SITE_POSITIONS = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]


def _frame(
    source_atom_ids: list[int],
    positions: list[list[float]],
    *,
    step: int = 0,
    time_ps: float = 0.0,
    **metadata,
) -> dict:
    return {
        "source_atom_ids": source_atom_ids,
        "positions_angstrom": positions,
        "coordinate_basis": "source_cartesian",
        "step": step,
        "physical_time_ps": time_ps,
        **metadata,
    }


def _analyze(frames: list[dict], *, mode: str = "md_time", sites=SITE_IDS, positions=SITE_POSITIONS, mobile=(101, 303), radius=0.15, tolerance=0.02, confirmation_frames: int = 1) -> dict:
    return analyze_vacancy_frames(
        frames,
        site_atom_ids=sites,
        site_positions_angstrom=positions,
        cell_angstrom=CELL,
        pbc=[True, True, True],
        mobile_atom_ids=list(mobile),
        mode=mode,
        assignment_radius_angstrom=radius,
        ambiguity_tolerance_angstrom=tolerance,
        confirmation_frames=confirmation_frames,
    )


def test_reordered_frame_rows_do_not_create_a_jump_and_metadata_survives() -> None:
    result = _analyze([
        _frame([303, 101], [[2.0, 0.0, 0.0], [1.0, 0.0, 0.0]], step=0, tag="before"),
        _frame([101, 303], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], step=1, time_ps=0.5, tag="after"),
    ])

    assert result["status"] == "resolved"
    assert result["jump_events"] == []
    assert result["frames"][0]["source_frame"]["tag"] == "before"
    assert result["frames"][0]["vacancy_site_atom_id"] == 10


def test_single_vacancy_jump_is_observed_between_adjacent_frames() -> None:
    result = _analyze([
        _frame([101, 303], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], step=10, time_ps=1.0),
        _frame([303, 101], [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], step=11, time_ps=1.1),
    ])

    event = result["jump_events"][0]
    assert event["old_vacancy_site_atom_id"] == 10
    assert event["new_vacancy_site_atom_id"] == 50
    assert event["moving_atom_id"] == 303
    assert event["moving_atom_old_site_atom_id"] == 50
    assert event["moving_atom_new_site_atom_id"] == 10
    assert event["physical_time_ps_from"] == 1.0
    assert event["physical_time_ps_to"] == 1.1
    assert "jump_time_ps" not in event


def test_two_frame_confirmation_records_confirmation_indices() -> None:
    result = _analyze([
        _frame([101, 303], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], step=10, time_ps=1.0),
        _frame([303, 101], [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], step=11, time_ps=1.1),
        _frame([101, 303], [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]], step=12, time_ps=1.2),
    ], confirmation_frames=2)

    assert len(result["jump_events"]) == 1
    assert result["jump_events"][0]["confirmation_frame_indices"] == [1, 2]
    assert result["unresolved_transitions"] == []


def test_confirmation_window_ending_at_last_frame_is_insufficient() -> None:
    result = _analyze([
        _frame([101, 303], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], step=10, time_ps=1.0),
        _frame([303, 101], [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], step=11, time_ps=1.1),
    ], confirmation_frames=2)

    assert result["jump_events"] == []
    assert len(result["unresolved_transitions"]) == 1
    transition = result["unresolved_transitions"][0]
    assert transition["reason"] == "insufficient_frames"
    assert transition["not_confirmed"] is True
    assert transition["confirmation_frame_indices"] == [1]


def test_rotated_nonorthogonal_cell_reports_local_site_image() -> None:
    cell = np.asarray([[3.0, 0.0, 0.0], [1.0, 2.5, 0.0], [0.3, 0.2, 4.0]])
    site_fractional = np.asarray([0.1, 0.1, 0.1])
    other_fractional = np.asarray([0.55, 0.55, 0.55])
    site_positions = [
        (site_fractional @ cell).tolist(),
        (other_fractional @ cell).tolist(),
    ]
    mobile_position = (site_fractional @ cell + cell[0]).tolist()
    result = analyze_vacancy_frames(
        [{
            "source_atom_ids": [900],
            "positions_angstrom": [mobile_position],
            "coordinate_basis": "source_cartesian",
            "step": 0,
            "physical_time_ps": 0.0,
        }],
        site_atom_ids=[70, 150],
        site_positions_angstrom=site_positions,
        cell_angstrom=cell.tolist(),
        pbc=[True, True, True],
        mobile_atom_ids=[900],
        mode="md_time",
        assignment_radius_angstrom=0.05,
        ambiguity_tolerance_angstrom=0.001,
        confirmation_frames=1,
    )

    assignment = result["frames"][0]["assignments"][0]
    assert result["status"] == "resolved"
    assert assignment["site_atom_id"] == 70
    assert assignment["site_image"] == [1, 0, 0]


def test_noncontinuous_ids_and_ambiguous_nearest_site_remain_unresolved() -> None:
    result = analyze_vacancy_frames(
        [{
            "source_atom_ids": [901],
            "coordinate_basis": "source_cartesian",
            "positions_angstrom": [[0.5, 0.0, 0.0]],
            "step": 0,
            "physical_time_ps": 0.0,
        }],
        site_atom_ids=[70, 150],
        site_positions_angstrom=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        cell_angstrom=CELL,
        pbc=[True, True, True],
        mobile_atom_ids=[901],
        mode="md_time",
        assignment_radius_angstrom=1.0,
        ambiguity_tolerance_angstrom=0.01,
        confirmation_frames=1,
    )

    frame = result["frames"][0]
    assert frame["status"] == "unresolved"
    assert "ambiguous" in frame["atom_candidates"][0]["reason"]
    assert frame["atom_candidates"][0]["candidates"][0]["site_atom_id"] == 70


def test_multiple_occupancy_is_detailed_and_unresolved() -> None:
    result = _analyze([
        _frame([101, 303], [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    ])

    frame = result["frames"][0]
    occupancy = next(item for item in frame["site_occupancy"] if item["site_atom_id"] == 10)
    assert frame["status"] == "unresolved"
    assert len(occupancy["occupants"]) == 2
    assert any("multiple mobile atoms" in reason for reason in frame["unresolved_reasons"])


def test_missing_frame_coordinates_are_unresolved_without_filling_values() -> None:
    missing = {"source_atom_ids": [101, 303], "step": 1, "physical_time_ps": 0.5, "tag": "missing"}
    missing_ids = {"positions_angstrom": [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], "step": 2, "physical_time_ps": 1.0}
    result = _analyze([_frame([101, 303], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]), missing, missing_ids])

    assert result["frames"][1]["status"] == "unresolved"
    assert result["frames"][1]["assignments"] == []
    assert "missing positions_angstrom" in result["frames"][1]["unresolved_reasons"]
    assert result["jump_events"] == []
    assert result["frames"][2]["assignments"] == []
    assert "missing source_atom_ids" in result["frames"][2]["unresolved_reasons"]

    duplicate = _frame([101, 101], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="unique IDs"):
        _analyze([duplicate])


def test_neb_uses_site_changes_and_null_time_without_rates() -> None:
    first = _frame([101, 303], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], tag="neb-0")
    second = _frame([303, 101], [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], tag="neb-1")
    for index, frame in enumerate((first, second)):
        frame.pop("step")
        frame["image_index"] = index
        frame["reaction_coordinate"] = float(index)
        frame["physical_time_ps"] = None
    result = _analyze([first, second], mode="neb_path")

    assert "jump_events" not in result
    assert len(result["site_changes"]) == 1
    assert all(frame["physical_time_ps"] is None for frame in result["frames"])
    assert result["site_changes"][0]["reaction_coordinate_from"] == 0.0
    assert result["site_changes"][0]["reaction_coordinate_to"] == 1.0
    assert all("rate" not in key and "diffusion" not in key for key in result)


def test_unresolved_intervening_frame_is_not_bridged() -> None:
    initial = _frame([101, 303], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], step=0)
    ambiguous = _frame([101, 303], [[0.5, 0.0, 0.0], [2.0, 0.0, 0.0]], step=1, time_ps=0.5)
    final = _frame([303, 101], [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], step=2, time_ps=1.0)
    result = _analyze([initial, ambiguous, final], tolerance=0.01, radius=1.0)

    assert result["jump_events"] == []
    assert len(result["unresolved_transitions"]) == 2
    assert result["frames"][1]["status"] == "unresolved"
