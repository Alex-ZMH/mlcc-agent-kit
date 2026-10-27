"""Algorithm-only thermal-stress difference fixtures.

The tensors and histories below are mathematical fixtures.  They are not
native material or thermal-stress evidence.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from mlcc.thermal_stress import thermal_stress_change


CELL = [[4.0, 0.2, 0.0], [0.0, 4.1, 0.1], [0.0, 0.0, 5.0]]
FRAME_KEYS = [
    {"step": 0, "physical_time_ps": 0.0},
    {"step": 10, "physical_time_ps": 1.0},
]
REFERENCE_STRESS = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
TARGET_STRESS = [[1.5, 1.5, 3.2], [4.5, 5.5, 6.5], [7.5, 8.5, 10.0]]


def _identity(*, version: str = "v001", stress_fields: bool = True) -> dict[str, object]:
    return {
        "study_id": "ni-study",
        "model_id": "ni-model",
        "model_version": version,
        "potential_id": "ni-potential",
        "potential_version": "v001",
        "method_set": "lammps-ni-v001",
        "source_atom_ids": [10, 20],
        "source_cell_angstrom": copy.deepcopy(CELL),
        "contribution": "virial",
        "kinetic_included": False,
        "native_component_order": ["xx", "yy", "zz", "xy", "xz", "yz", "yx", "zx", "zy"],
        **({} if stress_fields else {
            "source_atom_ids": None,
            "source_cell_angstrom": None,
            "contribution": None,
            "kinetic_included": None,
            "native_component_order": None,
        }),
    }


def _constraint(*, loading: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "cell_angstrom": copy.deepcopy(CELL),
        "boundary": ["p", "p", "p"],
        "fixed_atom_ids": [10],
        "loading": {"kind": "none"} if loading is None else loading,
    }


def _history(
    state_id: str,
    *,
    loading: dict[str, object] | None = None,
    frame_keys: list[dict[str, object]] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    frame_keys = FRAME_KEYS if frame_keys is None else frame_keys
    temperature = {
        "schema": "mlcc.region-temperature-history.v1",
        "task_id": state_id,
        "native_job_id": f"job-{state_id}",
        "model_id": "ni-model",
        "model_version": "v001",
        "region_id": "left",
        "atom_ids": [10, 20],
        "samples": [
            {**key, "temperature_K": 300.0 + 20.0 * index}
            for index, key in enumerate(frame_keys)
        ],
        "source_files": {"temperature.json": f"{state_id}-temperature.json"},
    }
    mechanical = {
        "schema": "mlcc.mechanical-history.v1",
        "task_id": state_id,
        "native_job_id": f"job-{state_id}",
        "model_id": "ni-model",
        "model_version": "v001",
        "region_id": "left",
        "atom_ids": [10, 20],
        "protocol": {"boundary": ["p", "p", "p"]},
        "samples": [
            {**key, "constraint": _constraint(loading=loading)}
            for key in frame_keys
        ],
        "source_files": {"mechanical.json": f"{state_id}-mechanical.json"},
    }
    return temperature, mechanical


def _state(
    state_id: str,
    stress: list[list[float]] | None,
    *,
    version: str = "v001",
    volume: float | None = 10.0,
    histories: bool = True,
    loading: dict[str, object] | None = None,
    stress_fields: bool = True,
    frame_keys: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    selected_frame_keys = FRAME_KEYS if frame_keys is None else frame_keys
    temperature, mechanical = _history(state_id, loading=loading, frame_keys=selected_frame_keys)
    return {
        "state_id": state_id,
        "identity": _identity(version=version, stress_fields=stress_fields),
        "region": {
            "region_id": "left",
            "atom_ids": [10, 20],
            "volume_angstrom3": volume,
            "volume_definition": "explicit_left_region" if volume is not None else None,
        },
        "stress_GPa": stress,
        "frame_keys": copy.deepcopy(selected_frame_keys),
        "temperature_history": temperature if histories else None,
        "mechanical_history": mechanical if histories else None,
        "missing_evidence": [],
        "source_refs": [f"{state_id}/local-stress.json"],
    }


def test_non_symmetric_stress_difference_preserves_full_tensor_and_history() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS)
    result = thermal_stress_change(reference, [target])

    expected = np.asarray(TARGET_STRESS) - np.asarray(REFERENCE_STRESS)
    assert result["schema"] == "mlcc.thermal-stress-response.v1"
    assert result["status"] == "available"
    state = result["states"][0]
    np.testing.assert_allclose(state["stress_change_GPa"], expected)
    np.testing.assert_allclose(state["thermal_stress_change_GPa"], expected)
    assert not np.allclose(np.asarray(state["stress_change_GPa"]), np.asarray(state["stress_change_GPa"]).T)
    assert state["classification"] == "same_constraint_thermal_stress_change"
    assert state["frame_keys"] == FRAME_KEYS
    assert state["temperature_history"] == target["temperature_history"]
    assert state["mechanical_history"] == target["mechanical_history"]
    assert result["production_qualified"] is False


def test_changed_loading_keeps_observed_difference_but_withholds_thermal_difference() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state(
        "target",
        TARGET_STRESS,
        loading={"kind": "declared", "definition": "uniaxial_strain", "parameters": {"eps": 0.01}},
    )
    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["stress_change_GPa"] is not None
    assert state["thermal_stress_change_GPa"] is None
    assert state["classification"] == "mixed_thermal_mechanical_change"
    assert any("loading history differs" in reason for reason in state["missing_evidence"])
    assert result["status"] == "partial"


def test_different_reference_and_target_windows_allow_constant_constraints() -> None:
    reference = _state("reference", REFERENCE_STRESS, frame_keys=FRAME_KEYS)
    target_keys = [
        {"step": 20, "physical_time_ps": 2.0},
        {"step": 30, "physical_time_ps": 3.0},
        {"step": 40, "physical_time_ps": 4.0},
    ]
    target = _state("target", TARGET_STRESS, frame_keys=target_keys)
    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["classification"] == "same_constraint_thermal_stress_change"
    assert state["thermal_stress_change_GPa"] == state["stress_change_GPa"]
    assert state["frame_keys"] == target_keys
    assert result["status"] == "available"


def test_internal_loading_change_in_either_history_is_mixed() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS)
    target["mechanical_history"]["samples"][1]["constraint"]["loading"] = {  # type: ignore[index]
        "kind": "declared",
        "definition": "uniaxial_strain",
        "parameters": {"eps": 0.01},
    }
    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["classification"] == "mixed_thermal_mechanical_change"
    assert state["stress_change_GPa"] is not None
    assert state["thermal_stress_change_GPa"] is None


def test_one_missing_mechanical_history_is_not_called_mixed() -> None:
    reference = _state("reference", REFERENCE_STRESS, histories=False)
    target = _state("target", TARGET_STRESS)
    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["classification"] == "stress_change_without_history"
    assert state["stress_change_GPa"] is not None
    assert state["thermal_stress_change_GPa"] is None


def test_missing_history_retains_ordinary_difference_without_inference() -> None:
    reference = _state("reference", REFERENCE_STRESS, histories=False)
    target = _state("target", TARGET_STRESS, histories=False)
    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["stress_change_GPa"] is not None
    assert state["thermal_stress_change_GPa"] is None
    assert state["classification"] == "stress_change_without_history"
    assert any("temperature_history" in reason for reason in state["missing_evidence"])
    assert any("mechanical_history" in reason for reason in state["missing_evidence"])


def test_explicit_null_history_samples_remain_missing_without_mapping() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS)
    target["temperature_history"]["samples"] = None  # type: ignore[index]

    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["stress_change_GPa"] is not None
    assert state["thermal_stress_change_GPa"] is None
    assert state["classification"] == "stress_change_without_history"
    assert any("temperature_history.samples" in reason for reason in state["missing_evidence"])


@pytest.mark.parametrize(
    ("reference", "target", "missing_fragment"),
    [
        (None, _state("target", TARGET_STRESS), "reference_state"),
        (_state("reference", REFERENCE_STRESS), _state("target", TARGET_STRESS, volume=None), "volume_angstrom3"),
        (_state("reference", REFERENCE_STRESS), _state("target", None), "stress_GPa"),
    ],
)
def test_missing_reference_volume_or_stress_remains_null(
    reference: dict[str, object] | None,
    target: dict[str, object],
    missing_fragment: str,
) -> None:
    result = thermal_stress_change(reference, [target])
    state = result["states"][0]

    assert state["stress_change_GPa"] is None
    assert state["thermal_stress_change_GPa"] is None
    assert any(missing_fragment in reason for reason in result["missing_evidence"])


def test_incompatible_stress_identity_is_an_original_value_error() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS, version="v002")

    with pytest.raises(ValueError, match="model_version"):
        thermal_stress_change(reference, [target])


def test_missing_stress_identity_withholds_difference_instead_of_matching_nulls() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS)
    target["identity"]["method_set"] = None  # type: ignore[index]

    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["stress_change_GPa"] is None
    assert state["thermal_stress_change_GPa"] is None
    assert any("identity:method_set" in item for item in result["missing_evidence"])


def test_both_missing_identities_do_not_match_as_compatible() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS)
    for key in reference["identity"]:
        reference["identity"][key] = None  # type: ignore[index]
        target["identity"][key] = None  # type: ignore[index]

    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["stress_change_GPa"] is None
    assert state["thermal_stress_change_GPa"] is None
    assert any("reference:identity:study_id" in item for item in result["missing_evidence"])
    assert any("state:target:identity:study_id" in item for item in result["missing_evidence"])


def test_reference_missing_evidence_is_preserved_in_output_missing() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    reference["missing_evidence"] = ["reference_source_history"]
    target = _state("target", TARGET_STRESS)

    result = thermal_stress_change(reference, [target])

    assert "reference_source_history" in result["missing_evidence"]


def test_temperature_only_state_does_not_invent_region_or_stress_mapping() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state(
        "temperature-only",
        None,
        volume=None,
        histories=False,
        stress_fields=False,
        frame_keys=[],
    )
    target["region"] = {
        "region_id": None,
        "atom_ids": None,
        "volume_angstrom3": None,
        "volume_definition": None,
    }
    result = thermal_stress_change(reference, [target])

    state = result["states"][0]
    assert state["stress_change_GPa"] is None
    assert state["thermal_stress_change_GPa"] is None
    assert state["region"]["atom_ids"] is None
    assert state["frame_keys"] == []
    assert result["status"] == "unresolved"


def test_history_frame_keys_must_match_exactly() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS)
    target["temperature_history"]["samples"][1]["step"] = 11  # type: ignore[index]

    with pytest.raises(ValueError, match="temperature history frame keys"):
        thermal_stress_change(reference, [target])


def test_nonpositive_volume_is_an_original_value_error() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS, volume=0.0)

    with pytest.raises(ValueError, match="volume_angstrom3"):
        thermal_stress_change(reference, [target])


def test_mechanical_cell_must_match_each_state_source_cell() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS)
    target["mechanical_history"]["samples"][0]["constraint"]["cell_angstrom"] = [  # type: ignore[index]
        [4.1, 0.2, 0.0], [0.0, 4.1, 0.1], [0.0, 0.0, 5.0]
    ]

    with pytest.raises(ValueError, match="constraint cell differs"):
        thermal_stress_change(reference, [target])


def test_negative_temperature_is_an_original_value_error() -> None:
    reference = _state("reference", REFERENCE_STRESS)
    target = _state("target", TARGET_STRESS)
    target["temperature_history"]["samples"][0]["temperature_K"] = -1.0  # type: ignore[index]

    with pytest.raises(ValueError, match="non-negative"):
        thermal_stress_change(reference, [target])


def test_history_frame_keys_are_validated_when_reference_stress_is_missing() -> None:
    reference = _state("reference", None)
    reference["temperature_history"]["samples"][0]["step"] = 1  # type: ignore[index]
    target = _state("target", TARGET_STRESS)

    with pytest.raises(ValueError, match="temperature history frame keys"):
        thermal_stress_change(reference, [target])
