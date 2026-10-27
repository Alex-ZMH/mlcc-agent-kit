from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mlcc.model_derivatives import derive_defect_model, derive_supercell_model
from mlcc.modeling import read_model_artifacts


ROOT = Path(__file__).resolve().parents[2]
CZO_MODEL = ROOT / "workspace" / "models" / "cazro3-pnma-pristine" / "v001"


def test_supercell_preserves_parent_images_and_exact_geometry(tmp_path):
    parent = read_model_artifacts(CZO_MODEL)
    matrix = [[2, 1, 0], [0, 1, 0], [0, 0, 1]]
    derived = derive_supercell_model(
        CZO_MODEL,
        {
            "model_id": "cazro3-pnma-supercell-test",
            "version": "v001",
            "repeat_matrix": matrix,
            "study_id": "czo-structure-test",
        },
        tmp_path / "supercell",
    )

    assert len(derived.atoms) == 2 * len(parent.atoms)
    assert derived.atom_ids == list(range(40))
    assert abs(np.linalg.det(derived.atoms.cell.array)) == pytest.approx(
        2.0 * abs(np.linalg.det(parent.atoms.cell.array)), rel=1e-12
    )
    assert derived.metadata["parent_models"][0]["model_id"] == parent.model_id
    assert derived.metadata["parent_models"][0]["version"] == parent.version
    assert derived.metadata["study_binding"] == "czo-structure-test"
    assert derived.metadata["relaxation_status"] == "not_run"
    assert derived.metadata["production_qualified"] is False
    assert derived.metadata["charge_state"] == 0
    assert derived.metadata["source_structure_role"] == "generated_child_reference"
    assert derived.metadata["parent_source_ref"]["model_id"] == parent.model_id
    assert derived.metadata["parent_source_ref"]["version"] == parent.version
    assert derived.metadata["parent_source_ref"]["source_path"] == parent.metadata["source_path"]

    lineage = json.loads((derived.artifact_dir / "atom-lineage.json").read_text(encoding="utf-8"))
    assert len(lineage["entries"]) == len(derived.atoms)
    assert lineage["source_structure_role"] == "generated_child_reference"
    assert lineage["parent_source_ref"]["model_id"] == parent.model_id
    parent_cell = parent.atoms.cell.array
    parent_frac = parent.atoms.get_scaled_positions(wrap=False)
    parent_ids = parent.atom_ids
    for index, entry in enumerate(lineage["entries"]):
        parent_index = parent_ids.index(entry["parent_atom_id"])
        image = np.asarray(entry["parent_image"], dtype=int)
        expected = (parent_frac[parent_index] + image) @ parent_cell
        assert derived.atoms.positions[index] == pytest.approx(expected, abs=1e-10)
        assert all(isinstance(value, int) for value in entry["parent_image"])

    loaded = read_model_artifacts(derived.artifact_dir)
    assert loaded.atom_ids == derived.atom_ids
    assert loaded.metadata["parent_model"]["path"] == str(CZO_MODEL.resolve())
    assert loaded.metadata["source_structure_role"] == "generated_child_reference"
    dopants = json.loads((derived.artifact_dir / "dopants.json").read_text(encoding="utf-8"))
    assert dopants["spatial_mode"] == "exact_supercell"
    assert dopants["derivation_kind"] == "exact_integer_supercell"
    assert dopants["operations"] == []
    assert dopants["charge_state"] == 0


@pytest.mark.parametrize(
    "matrix, match",
    [
        ([[1, 0, 0], [0, 1, 0], [0, 0, 0]], "positive determinant"),
        ([[-1, 0, 0], [0, 1, 0], [0, 0, 1]], "positive determinant"),
        ([[1.5, 0, 0], [0, 1, 0], [0, 0, 1]], "integer matrix"),
    ],
)
def test_supercell_requires_explicit_right_handed_integer_matrix(tmp_path, matrix, match):
    with pytest.raises(ValueError, match=match):
        derive_supercell_model(
            CZO_MODEL,
            {"model_id": "bad", "version": "v001", "repeat_matrix": matrix},
            tmp_path / "bad",
        )


def test_defect_sequence_preserves_ids_and_records_stoichiometry(tmp_path):
    parent = read_model_artifacts(CZO_MODEL)
    derived = derive_defect_model(
        CZO_MODEL,
        {
            "model_id": "cazro3-explicit-defect-test",
            "version": "v001",
            "study_id": "czo-defect-contract-test",
            "charge_state": 1,
            "operations": [
                {"kind": "vacancy", "atom_id": 0},
                {"kind": "substitution", "atom_id": 4, "new_element": "Ti"},
                {
                    "kind": "interstitial",
                    "new_atom_id": 100,
                    "element": "O",
                    "frac_coords": [0.25, 0.25, 0.25],
                },
            ],
        },
        tmp_path / "defect",
    )

    assert len(derived.atoms) == len(parent.atoms)
    assert 0 not in derived.atom_ids
    assert 100 in derived.atom_ids
    assert derived.metadata["composition"] == {"Ca": 3, "Zr": 3, "O": 13, "Ti": 1}
    assert derived.metadata["derivation"]["composition_delta"] == {
        "Ca": -1,
        "O": 1,
        "Zr": -1,
        "Ti": 1,
    }
    assert derived.metadata["derivation"]["charge_state"] == 1
    assert derived.metadata["production_qualified"] is False
    assert derived.metadata["relaxation_status"] == "not_run"
    assert derived.metadata["study_id"] == "czo-defect-contract-test"
    assert derived.metadata["derivation"]["operations"][0]["delta_N"] == {"Ca": -1}
    assert derived.metadata["derivation"]["operations"][1]["delta_N"] == {"Zr": -1, "Ti": 1}
    assert derived.metadata["derivation"]["operations"][2]["delta_N"] == {"O": 1}

    dopants = json.loads((derived.artifact_dir / "dopants.json").read_text(encoding="utf-8"))
    assert derived.metadata["spatial_mode"] == "explicit_defect_sequence"
    assert dopants["spatial_mode"] == "explicit_defect_sequence"
    assert dopants["derivation_kind"] == "explicit_defect_sequence"
    assert dopants["compensation"] is None
    assert dopants["charge_state"] == 1
    assert len(dopants["operations"]) == 3
    assert read_model_artifacts(derived.artifact_dir).atom_ids == derived.atom_ids
    assert parent.atom_ids == list(range(20))


def test_derived_models_require_a_new_identity(tmp_path):
    parent = read_model_artifacts(CZO_MODEL)
    with pytest.raises(ValueError, match="new model_id and version"):
        derive_supercell_model(
            CZO_MODEL,
            {
                "model_id": parent.model_id,
                "version": parent.version,
                "repeat_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            },
            tmp_path / "same-supercell-identity",
        )
    with pytest.raises(ValueError, match="new model_id and version"):
        derive_defect_model(
            CZO_MODEL,
            {
                "model_id": parent.model_id,
                "version": parent.version,
                "charge_state": 0,
                "operations": [{"kind": "vacancy", "atom_id": 0}],
            },
            tmp_path / "same-defect-identity",
        )


def test_supercell_rejects_charged_parent_without_charge_convention(tmp_path):
    charged = derive_defect_model(
        CZO_MODEL,
        {
            "model_id": "cazro3-charged-parent-test",
            "version": "v001",
            "charge_state": 1,
            "operations": [{"kind": "vacancy", "atom_id": 0}],
        },
        tmp_path / "charged-parent",
    )
    assert charged.metadata["charge_state"] == 1
    with pytest.raises(ValueError, match="charged parent model"):
        derive_supercell_model(
            charged.artifact_dir,
            {
                "model_id": "cazro3-charged-parent-supercell-test",
                "version": "v001",
                "repeat_matrix": [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
            },
            tmp_path / "charged-supercell",
        )


def test_defect_sequence_rejects_implicit_compensation_randomness_and_id_reuse(tmp_path):
    base = {
        "model_id": "bad-defect",
        "version": "v001",
        "charge_state": 0,
        "operations": [{"kind": "vacancy", "atom_id": 0}],
    }
    with pytest.raises(ValueError, match="compensation"):
        derive_defect_model(CZO_MODEL, {**base, "compensation": "automatic"}, tmp_path / "comp")
    with pytest.raises(ValueError, match="random"):
        derive_defect_model(CZO_MODEL, {**base, "random_seed": 7}, tmp_path / "random")
    with pytest.raises(ValueError, match="already been used"):
        derive_defect_model(
            CZO_MODEL,
            {
                "model_id": "bad-id",
                "version": "v001",
                "charge_state": 0,
                "operations": [
                    {"kind": "vacancy", "atom_id": 0},
                    {"kind": "interstitial", "new_atom_id": 0, "element": "O", "frac_coords": [0, 0, 0]},
                ],
            },
            tmp_path / "reuse",
        )
