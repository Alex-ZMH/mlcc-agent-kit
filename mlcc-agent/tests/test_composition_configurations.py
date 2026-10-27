"""Pure M4 seeded-assignment contract tests.

Model generation and the public ``plan-configurations`` command are exercised
once by the v100 Slurm acceptance job.  These tests cover only the new random
assignment and finite-request semantics.
"""

from __future__ import annotations

import copy
import json

import pytest

from mlcc.composition_configurations import (
    RANDOM_ALGORITHM,
    _validate_configurations,
    build_composition_configurations,
    sample_composition_assignments,
)
from mlcc.model_derivatives import supercell_parent_images


def _composition() -> dict:
    return {
        "parent_model": {
            "model_id": "ni-engineering",
            "version": "v001",
            "path": "../models/ni-engineering/v001",
        },
        "parent_study": "../studies/ni-engineering.json",
        "repeat_matrix": [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
        "max_atoms": 8,
        "sublattices": [
            {"id": "a_site", "allowed_atom_ids": [0, 2], "allowed_parent_elements": ["Ni"]},
            {"id": "b_site", "allowed_atom_ids": [1, 3], "allowed_parent_elements": ["Ni"]},
        ],
        "components": [
            {"element": "Cu", "sublattice": "a_site", "count": 1},
            {
                "element": "Co",
                "sublattice": "b_site",
                "concentration": {"numerator": 1, "denominator": 2, "basis": "sublattice"},
            },
        ],
        "compensation": {"status": "specified", "operations": []},
        "recipe": {"kind": "engineering_fixture", "source": "m4-test"},
    }


def _sample(composition: dict, *, images: list[list[int]] | None = None, seed: int = 37) -> list[dict]:
    return sample_composition_assignments(
        composition,
        parent_atom_ids=[0, 1, 2, 3],
        parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
        parent_images=images or [[0, 0, 0], [1, 0, 0]],
        seed=seed,
    )


def test_same_seed_is_stable_when_allowed_ids_and_images_are_reordered() -> None:
    composition = _composition()
    reordered = copy.deepcopy(composition)
    reordered["sublattices"] = [
        {**composition["sublattices"][1], "allowed_atom_ids": [3, 1]},
        {**composition["sublattices"][0], "allowed_atom_ids": [2, 0]},
    ]
    first = _sample(composition, images=[[0, 0, 0], [1, 0, 0]])
    second = _sample(reordered, images=[[1, 0, 0], [0, 0, 0]])
    assert first == second
    assert {item["algorithm"] for item in first} == {RANDOM_ALGORITHM}
    assert {item["seed"] for item in first} == {37}


def test_multi_component_counts_include_exact_fraction() -> None:
    assignments = _sample(_composition())
    assert len(assignments) == 3
    assert sum(item["element"] == "Cu" for item in assignments) == 1
    assert sum(item["element"] == "Co" for item in assignments) == 2
    assert len({(item["parent_atom_id"], tuple(item["parent_image"])) for item in assignments}) == 3


def test_compensation_site_is_reserved_before_random_selection() -> None:
    composition = _composition()
    composition["components"] = [{"element": "Co", "sublattice": "b_site", "count": 1}]
    composition["compensation"] = {
        "status": "specified",
        "operations": [
            {
                "kind": "vacancy",
                "sublattice": "b_site",
                "parent_atom_id": 1,
                "parent_image": [0, 0, 0],
            }
        ],
    }
    assignments = _sample(composition, seed=5)
    assert all((item["parent_atom_id"], item["parent_image"]) != (1, [0, 0, 0]) for item in assignments)


def test_fraction_that_is_not_an_integer_is_rejected() -> None:
    composition = _composition()
    composition["components"] = [
        {
            "element": "Cu",
            "sublattice": "a_site",
            "concentration": {"numerator": 1, "denominator": 3, "basis": "sublattice"},
        }
    ]
    with pytest.raises(ValueError, match="exact integer"):
        _sample(composition)


def test_negative_seed_is_rejected_before_sampling() -> None:
    with pytest.raises(ValueError, match="at least 0"):
        _sample(_composition(), seed=-1)


def test_zero_count_same_element_is_accepted_and_non_diagonal_images_keep_parent_ids() -> None:
    composition = _composition()
    composition["sublattices"] = [
        {"id": "a_site", "allowed_atom_ids": [10, 30], "allowed_parent_elements": ["Ni"]},
        {"id": "b_site", "allowed_atom_ids": [20, 40], "allowed_parent_elements": ["Ni"]},
    ]
    composition["components"] = [
        {"element": "Ni", "sublattice": "a_site", "count": 0},
        {"element": "Co", "sublattice": "b_site", "count": 1},
    ]
    matrix = [[2, 1, 0], [0, 1, 0], [0, 0, 1]]
    images = supercell_parent_images(matrix).tolist()
    assignments = sample_composition_assignments(
        composition,
        parent_atom_ids=[10, 20, 30, 40],
        parent_symbols={10: "Ni", 20: "Ni", 30: "Ni", 40: "Ni"},
        parent_images=images,
        seed=9,
    )
    assert len(images) == 2
    assert len(assignments) == 1
    assert assignments[0]["parent_atom_id"] in {20, 40}
    assert assignments[0]["parent_image"] in images


def test_configuration_budget_is_rejected_before_parent_model_read(tmp_path) -> None:
    request = {
        "schema": "mlcc.composition-configurations-request.v1",
        "configuration_set_id": "set-001",
        "composition_request": {},
        "max_configurations": 1,
        "configurations": [
            _configuration("cfg-001", "study-001", 1, "001"),
            _configuration("cfg-002", "study-002", 2, "002"),
        ],
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds max_configurations"):
        build_composition_configurations(request_path, tmp_path / "output")


def test_same_element_and_overlapping_sublattice_are_rejected() -> None:
    composition = _composition()
    composition["components"] = [{"element": "Ni", "sublattice": "a_site", "count": 1}]
    with pytest.raises(ValueError, match="same-element"):
        _sample(composition)

    composition = _composition()
    composition["sublattices"][1]["allowed_atom_ids"] = [0, 1]
    with pytest.raises(ValueError, match="pools overlap"):
        _sample(composition)


def _configuration(configuration_id: str, study_id: str, seed: int, model_suffix: str) -> dict:
    return {
        "configuration_id": configuration_id,
        "seed": seed,
        "study_id": study_id,
        "reference_model": {"model_id": f"reference-{model_suffix}", "version": "v001"},
        "child_model": {"model_id": f"child-{model_suffix}", "version": "v001"},
    }


def test_request_uses_finite_explicit_configuration_identities() -> None:
    values = [
        _configuration("cfg-001", "study-001", 1, "001"),
        _configuration("cfg-002", "study-002", 2, "002"),
    ]
    result = _validate_configurations(values)
    assert [item["configuration_id"] for item in result] == ["cfg-001", "cfg-002"]
    assert [item["seed"] for item in result] == [1, 2]

    duplicate = copy.deepcopy(values)
    duplicate[1]["configuration_id"] = duplicate[0]["configuration_id"]
    with pytest.raises(ValueError, match="duplicate configuration_id"):
        _validate_configurations(duplicate)

    duplicate = copy.deepcopy(values)
    duplicate[1]["child_model"] = duplicate[0]["child_model"]
    with pytest.raises(ValueError, match="duplicate configuration model identity"):
        _validate_configurations(duplicate)

    invalid_path = copy.deepcopy(values)
    invalid_path[0]["configuration_id"] = "../cfg-001"
    with pytest.raises(ValueError, match="single path segment"):
        _validate_configurations(invalid_path)
