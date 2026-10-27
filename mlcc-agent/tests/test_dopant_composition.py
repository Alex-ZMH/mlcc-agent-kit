"""Pure contract tests for explicit composition planning.

The builder integration test is intentionally kept separate: structure
artifact generation and pytest execution belong to the v100 Slurm acceptance
job.  These cases exercise only the deterministic domain functions.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from mlcc.dopant_composition import (
    PLAN_SCHEMA,
    _inherited_dopant_records,
    compile_dopant_operations,
    resolve_dopant_composition,
)


def test_existing_dopant_sites_follow_images_and_removed_sites_are_not_retained() -> None:
    parent = {"element": "Cu", "sublattice": "metal", "atom_id": 7, "count": 1}
    lineage = [
        {"parent_atom_id": 7, "child_atom_id": 0, "parent_image": [0, 0, 0]},
        {"parent_atom_id": 7, "child_atom_id": 4, "parent_image": [1, 0, 0]},
    ]
    records = _inherited_dopant_records([parent], lineage, [{"kind": "vacancy", "atom_id": 0}])
    assert len(records) == 1
    assert records[0]["atom_id"] == 4
    assert records[0]["parent_image"] == [1, 0, 0]
    assert records[0]["parent_record"] == parent


def _request() -> dict:
    return {
        "schema": "mlcc.dopant-composition-request.v1",
        "study_id": "ni-cu-co-child-study",
        "parent_study": "../studies/ni-parent.json",
        "parent_model": {
            "model_id": "ni-fcc-engineering",
            "version": "v001",
            "path": "../models/ni-fcc-engineering/v001",
        },
        "reference_model": {
            "model_id": "ni-fcc-engineering-2x1x1",
            "version": "v001",
        },
        "child_model": {
            "model_id": "ni-cu-co-engineering",
            "version": "v001",
        },
        "repeat_matrix": [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
        "max_atoms": 8,
        "recipe": {"kind": "engineering_fixture", "source": "test_request"},
        "sublattices": [
            {
                "id": "a_site",
                "allowed_atom_ids": [0, 1],
                "allowed_parent_elements": ["Ni"],
            },
            {
                "id": "b_site",
                "allowed_atom_ids": [2, 3],
                "allowed_parent_elements": ["Ni"],
            },
        ],
        "components": [
            {"element": "Cu", "sublattice": "a_site", "count": 1},
            {
                "element": "Co",
                "sublattice": "b_site",
                "concentration": {
                    "numerator": 1,
                    "denominator": 4,
                    "basis": "sublattice",
                },
            },
        ],
        "site_assignments": [
            {
                "sublattice": "a_site",
                "parent_atom_id": 0,
                "parent_image": [0, 0, 0],
                "element": "Cu",
            },
            {
                "sublattice": "b_site",
                "parent_atom_id": 2,
                "parent_image": [1, 0, 0],
                "element": "Co",
            },
        ],
        "compensation": {
            "status": "specified",
            "net_charge": 1,
            "ionic_charge_delta": 1,
            "electronic_compensation_charge": 0,
            "source": "engineering_fixture",
            "formal_valences": [
                {"element": "Ni", "valence": 0, "source": "engineering_fixture"},
                {"element": "Cu", "valence": 1, "source": "engineering_fixture"},
                {"element": "Co", "valence": 0, "source": "engineering_fixture"},
            ],
            "operations": [
                {
                    "kind": "vacancy",
                    "sublattice": "b_site",
                    "parent_atom_id": 3,
                    "parent_image": [0, 0, 0],
                }
            ],
        },
    }


def test_resolve_uses_exact_reference_supercell_capacity_and_preserves_recipe() -> None:
    plan = resolve_dopant_composition(
        _request(),
        parent_atom_ids=[0, 1, 2, 3],
        parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
    )

    assert plan["schema"] == PLAN_SCHEMA
    assert plan["status"] == "resolved"
    assert plan["recipe"]["kind"] == "engineering_fixture"
    assert plan["sublattices"][0]["supercell_capacity"] == 4
    assert plan["components"][1]["count"] == 1
    assert plan["components"][1]["count_scope"] == "reference_supercell"
    assert plan["compensation"]["net_charge"] == 1


def test_parent_atom_ids_are_required_for_reference_capacity() -> None:
    with pytest.raises(ValueError, match="parent_atom_ids must be supplied"):
        resolve_dopant_composition(_request())


def test_compile_maps_parent_images_and_keeps_explicit_charge_operation() -> None:
    plan = resolve_dopant_composition(
        _request(),
        parent_atom_ids=[0, 1, 2, 3],
        parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
    )
    lineage = [
        {"child_atom_id": 0, "parent_atom_id": 0, "parent_image": [0, 0, 0], "element": "Ni"},
        {"child_atom_id": 1, "parent_atom_id": 2, "parent_image": [1, 0, 0], "element": "Ni"},
        {"child_atom_id": 2, "parent_atom_id": 3, "parent_image": [0, 0, 0], "element": "Ni"},
    ]

    operations = compile_dopant_operations(plan, lineage)

    assert operations == [
        {"kind": "substitution", "atom_id": 0, "new_element": "Cu"},
        {"kind": "substitution", "atom_id": 1, "new_element": "Co"},
        {"kind": "vacancy", "atom_id": 2},
    ]


def test_non_integral_concentration_is_rejected_without_rounding() -> None:
    request = _request()
    request["repeat_matrix"] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    request["components"] = [
        {
            "element": "Cu",
            "sublattice": "a_site",
            "concentration": {"numerator": 1, "denominator": 3, "basis": "sublattice"},
        }
    ]
    request["site_assignments"] = []

    with pytest.raises(ValueError, match="exact integer"):
        resolve_dopant_composition(
            request,
            parent_atom_ids=[0, 1, 2, 3],
            parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
        )


def test_repeat_capacity_must_fit_explicit_atom_limit() -> None:
    request = _request()
    request["max_atoms"] = 7

    with pytest.raises(ValueError, match="above max_atoms"):
        resolve_dopant_composition(
            request,
            parent_atom_ids=[0, 1, 2, 3],
            parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
        )


def test_charge_balance_is_not_silently_neutralized() -> None:
    request = _request()
    request["compensation"]["electronic_compensation_charge"] = 1

    with pytest.raises(ValueError, match="charge balance"):
        resolve_dopant_composition(
            request,
            parent_atom_ids=[0, 1, 2, 3],
            parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
        )


def test_duplicate_final_site_is_rejected() -> None:
    request = _request()
    request["components"] = [{"element": "Cu", "sublattice": "a_site", "count": 2}]
    request["site_assignments"] = [
        {
            "sublattice": "a_site",
            "parent_atom_id": 0,
            "parent_image": [0, 0, 0],
            "element": "Cu",
        },
        {
            "sublattice": "a_site",
            "parent_atom_id": 0,
            "parent_image": [0, 0, 0],
            "element": "Cu",
        },
    ]

    with pytest.raises(ValueError, match="repeats a final occupied site"):
        resolve_dopant_composition(
            request,
            parent_atom_ids=[0, 1, 2, 3],
            parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
        )


def test_duplicate_parent_image_cannot_be_hidden_by_two_sublattice_ids() -> None:
    request = _request()
    request["sublattices"][1]["allowed_atom_ids"] = [0, 2, 3]
    request["components"] = [
        {"element": "Cu", "sublattice": "a_site", "count": 1},
        {"element": "Co", "sublattice": "b_site", "count": 1},
    ]
    request["site_assignments"] = [
        {
            "sublattice": "a_site",
            "parent_atom_id": 0,
            "parent_image": [0, 0, 0],
            "element": "Cu",
        },
        {
            "sublattice": "b_site",
            "parent_atom_id": 0,
            "parent_image": [0, 0, 0],
            "element": "Co",
        },
    ]

    with pytest.raises(ValueError, match="repeats a final occupied site"):
        resolve_dopant_composition(
            request,
            parent_atom_ids=[0, 1, 2, 3],
            parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
        )


def test_unresolved_compensation_is_a_plan_but_cannot_compile_a_child() -> None:
    request = _request()
    request["compensation"] = {
        "status": "unresolved",
        "net_charge": None,
        "ionic_charge_delta": None,
        "electronic_compensation_charge": None,
        "source": "not_selected",
        "formal_valences": [],
        "operations": [],
    }
    plan = resolve_dopant_composition(
        request,
        parent_atom_ids=[0, 1, 2, 3],
        parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
    )

    assert plan["status"] == "unresolved"
    with pytest.raises(ValueError, match="unresolved"):
        compile_dopant_operations(plan, [])


def test_missing_site_formal_valence_becomes_unresolved_without_neutral_child() -> None:
    request = _request()
    request["compensation"]["formal_valences"] = [
        {"element": "Cu", "valence": 1, "source": "engineering_fixture"},
        {"element": "Co", "valence": 0, "source": "engineering_fixture"},
    ]
    plan = resolve_dopant_composition(
        request,
        parent_atom_ids=[0, 1, 2, 3],
        parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
    )

    assert plan["status"] == "unresolved"
    assert "formal valence" in plan["compensation"]["unresolved_reason"]


def test_compensation_substitution_cannot_target_a_selected_site() -> None:
    request = deepcopy(_request())
    request["compensation"]["operations"] = [
        {
            "kind": "substitution",
            "sublattice": "a_site",
            "parent_atom_id": 0,
            "parent_image": [0, 0, 0],
            "element": "Fe",
        }
    ]
    with pytest.raises(ValueError, match="repeats a final occupied site"):
        resolve_dopant_composition(
            request,
            parent_atom_ids=[0, 1, 2, 3],
            parent_symbols={0: "Ni", 1: "Ni", 2: "Ni", 3: "Ni"},
        )
