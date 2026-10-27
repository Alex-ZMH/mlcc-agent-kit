"""M4 external-structure import contract tests.

The fixture is a four-site engineering structure with reordered source atoms
and 1e-7 Angstrom cell/coordinate perturbations.  It is deliberately not an SQS search
result.  These tests are new-path checks only; the Slurm acceptance job runs
the successful model-generation path with the configured runtime.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.io import read as ase_read

from mlcc.composition_sqs_import import import_sqs_configuration
from mlcc.model_derivatives import supercell_parent_images
from mlcc.modeling import read_model_artifacts, write_model_artifacts


FIXTURE = Path(__file__).parent / "fixtures" / "composition-sqs-import-v001" / "toy-external-reordered.extxyz"


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _parent(tmp_path: Path) -> tuple[Path, Path]:
    parent_dir = tmp_path / "parent-model"
    atoms = Atoms(
        symbols=["Mg", "O"],
        positions=[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
        cell=[[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([7, 19], dtype=np.int64))
    write_model_artifacts(
        atoms,
        parent_dir,
        model_id="toy-parent",
        version="v001",
        fixture=True,
        fixture_purpose="m4_external_sqs_import_parent",
        phase_requested="toy_parent_phase",
        source_path="m4-test-parent",
        source_version="m4-v001",
        material="MgO",
    )
    study = {
        "study_id": "toy-parent-study",
        "case_id": "toy-parent-case",
        "case_role": "engineering_fixture",
        "model": {
            "model_id": "toy-parent",
            "version": "v001",
            "path": str(parent_dir.resolve()),
        },
        "selected_required_tasks": [],
    }
    study_path = _write(tmp_path / "parent-study.json", study)
    return parent_dir, study_path


def _composition(parent_dir: Path, study_path: Path) -> dict:
    return {
        "schema": "mlcc.dopant-composition-request.v1",
        "study_id": "toy-imported-child-study",
        "parent_study": str(study_path.resolve()),
        "parent_model": {
            "model_id": "toy-parent",
            "version": "v001",
            "path": str(parent_dir.resolve()),
        },
        "reference_model": {
            "model_id": "toy-imported-reference",
            "version": "v001",
        },
        "child_model": {
            "model_id": "toy-imported-child",
            "version": "v001",
        },
        "repeat_matrix": [[1, 1, 0], [0, 2, 0], [0, 0, 1]],
        "max_atoms": 8,
        "recipe": {"kind": "engineering_fixture", "source": "external_sqs_import_test"},
        "sublattices": [
            {
                "id": "cation",
                "allowed_atom_ids": [7],
                "allowed_parent_elements": ["Mg"],
            },
            {
                "id": "anion",
                "allowed_atom_ids": [19],
                "allowed_parent_elements": ["O"],
            },
        ],
        "components": [{"element": "Ca", "sublattice": "cation", "count": 1}],
        "compensation": {
            "status": "specified",
            "net_charge": 0,
            "ionic_charge_delta": 0,
            "electronic_compensation_charge": 0,
            "source": "engineering_fixture_isovalent_substitution",
            "formal_valences": [
                {"sublattice": "cation", "element": "Mg", "valence": 2, "source": "fixture"},
                {"sublattice": "cation", "element": "Ca", "valence": 2, "source": "fixture"},
                {"sublattice": "anion", "element": "O", "valence": -2, "source": "fixture"},
            ],
            "operations": [],
        },
    }


def _request(tmp_path: Path, *, correlation_file: Path | None = None) -> tuple[Path, dict, Path]:
    parent_dir, study_path = _parent(tmp_path)
    composition_request = _composition(parent_dir, study_path)
    parent_images = [
        [int(value) for value in image]
        for image in supercell_parent_images(composition_request["repeat_matrix"])
    ]
    if len(parent_images) != 2:
        raise AssertionError("toy fixture requires exactly two canonical parent images")
    request = {
        "schema": "mlcc.sqs-import-request.v1",
        "composition_request": composition_request,
        "external_structure": {
            "path": str(FIXTURE.resolve()),
            "format": "extxyz",
            "frame_index": 0,
            "length_unit": "angstrom",
            "provenance": {
                "kind": "engineering_fixture",
                "description": "reordered toy structure; no SQS search was run",
                "tool_name": None,
                "tool_version": None,
                "job_id": None,
                "stopping_status": None,
            },
        },
        "atom_mapping": [
            {
                "source_index": 3,
                "parent_atom_id": 7,
                "parent_image": parent_images[1],
                "sublattice": "cation",
            },
            {
                "source_index": 2,
                "parent_atom_id": 19,
                "parent_image": parent_images[0],
                # An unchanged parent site may omit the sublattice label.
                "sublattice": None,
            },
            {
                "source_index": 1,
                "parent_atom_id": 7,
                "parent_image": parent_images[0],
                "sublattice": "cation",
            },
            {
                "source_index": 0,
                "parent_atom_id": 19,
                "parent_image": parent_images[1],
                "sublattice": None,
            },
        ],
        "mapping_tolerance_angstrom": 1.0e-5,
        "correlation_file": None if correlation_file is None else str(correlation_file.resolve()),
    }
    request_path = _write(tmp_path / "sqs-import-request.json", request)
    return request_path, request, parent_dir


def _copy_request(tmp_path: Path, request: dict) -> Path:
    return _write(tmp_path / "modified-request.json", request)


def test_import_preserves_external_geometry_source_order_and_m1_binding(tmp_path: Path) -> None:
    request_path, request, _ = _request(tmp_path)
    original_source = FIXTURE.read_bytes()

    result = import_sqs_configuration(request_path, tmp_path / "imported")

    assert result["schema"] == "mlcc.composition-build.v1"
    imported = result["imported_configuration"]
    assert imported["geometry_scope"] == "full_occupancy_substitution_fixed_parent_lattice"
    assert imported["geometry_preserved"] is True
    assert imported["correlation_assessment"] == "not_evaluated"
    assert imported["external_structure"]["path"] == str(FIXTURE.resolve())
    assert imported["external_structure"]["format"] == "extxyz"
    assert imported["external_structure"]["frame_index"] == 0
    assert imported["external_structure"]["length_unit"] == "angstrom"
    assert imported["external_structure"]["provenance"]["kind"] == "engineering_fixture"
    assert "no SQS search was run" in imported["external_structure"]["provenance"]["description"]
    assert imported["mapping_tolerance_angstrom"] == pytest.approx(1.0e-5)
    assert imported["correlation_file"] is None
    assert imported["correlation_text"] is None
    assert imported["analysis_scheduler_job_id"] == os.environ.get("SLURM_JOB_ID")
    assert FIXTURE.read_bytes() == original_source

    mapping = {entry["source_index"]: entry for entry in imported["atom_mapping"]}
    assert [entry["source_index"] for entry in imported["atom_mapping"]] == [0, 1, 2, 3]
    expected_images = [
        [int(value) for value in image]
        for image in supercell_parent_images(request["composition_request"]["repeat_matrix"])
    ]
    assert mapping[0]["parent_atom_id"] == 19
    assert mapping[0]["parent_image"] == expected_images[1]
    assert mapping[1]["parent_atom_id"] == 7
    assert mapping[1]["parent_image"] == expected_images[0]
    assert mapping[2]["parent_atom_id"] == 19
    assert mapping[2]["parent_image"] == expected_images[0]
    assert mapping[3]["parent_atom_id"] == 7
    assert mapping[3]["parent_image"] == expected_images[1]
    assert all("child_atom_id" in entry for entry in mapping.values())
    assert [mapping[index]["source_atom_id"] for index in range(4)] == [903, 900, 901, 902]

    model_path = Path(result["model_path"])
    model = read_model_artifacts(model_path)
    source_atoms = ase_read(str(FIXTURE), format="extxyz", index=0)
    assert Counter(model.atoms.get_chemical_symbols()) == Counter({"Ca": 1, "Mg": 1, "O": 2})
    assert model.metadata["element_order"] == ["O", "Ca", "Mg"]
    assert model.metadata["fixture"] is True
    np.testing.assert_allclose(
        model.atoms.cell.array, source_atoms.cell.array, rtol=0.0, atol=1.0e-10
    )
    np.testing.assert_allclose(
        np.asarray(model.metadata["lattice_angstrom"], dtype=float),
        source_atoms.cell.array,
        rtol=0.0,
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        np.asarray(model.metadata["source_lattice_angstrom"], dtype=float),
        source_atoms.cell.array,
        rtol=0.0,
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        np.asarray(
            [item["cart_coords_angstrom"] for item in model.metadata["atoms"]],
            dtype=float,
        ),
        source_atoms.get_positions(),
        rtol=0.0,
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        np.asarray(
            [item["cart_coords_angstrom"] for item in model.metadata["source_atoms"]],
            dtype=float,
        ),
        source_atoms.get_positions(),
        rtol=0.0,
        atol=1.0e-12,
    )
    basis_transform = model.metadata["basis_transform"]
    np.testing.assert_allclose(
        np.asarray(basis_transform["source_lattice_angstrom"], dtype=float),
        source_atoms.cell.array,
        rtol=0.0,
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        np.asarray(basis_transform["target_lattice_angstrom"], dtype=float),
        source_atoms.cell.array,
        rtol=0.0,
        atol=1.0e-12,
    )
    positions = model.atoms.get_positions()
    for source_index, entry in mapping.items():
        child_index = model.atom_ids.index(entry["child_atom_id"])
        np.testing.assert_allclose(
            positions[child_index],
            source_atoms.get_positions()[source_index],
            rtol=0.0,
            atol=1.0e-10,
        )

    child_study = json.loads(Path(result["study_path"]).read_text(encoding="utf-8"))
    assert child_study["study_id"] == request["composition_request"]["study_id"]
    assert child_study["parent_study_id"] == "toy-parent-study"
    assert child_study["parent_study_path"] == str(
        Path(request["composition_request"]["parent_study"]).resolve()
    )
    assert child_study["model"]["model_id"] == request["composition_request"]["child_model"]["model_id"]
    assert child_study["model"]["path"] == str(model_path.resolve())
    assert child_study["model"]["element_order"] == ["O", "Ca", "Mg"]
    assert child_study["model"]["fixture"] is True
    assert child_study["composition_status"] == "resolved"
    assert child_study["composition_compensation"]["net_charge"] == 0
    assert imported["native_job"] is None

    lineage = json.loads(
        (model_path / "atom-lineage.json").read_text(encoding="utf-8")
    )["entries"]
    lineage_by_child = {int(entry["child_atom_id"]): entry for entry in lineage}
    for entry in mapping.values():
        lineage_entry = lineage_by_child[int(entry["child_atom_id"])]
        assert lineage_entry["source_index"] == entry["source_index"]
        assert lineage_entry["source_atom_id"] == entry["source_atom_id"]
        assert lineage_entry["composition_parent_atom_id"] == entry["parent_atom_id"]
        assert lineage_entry["composition_parent_image"] == entry["parent_image"]


def test_import_preserves_correlation_text_without_assigning_quality(tmp_path: Path) -> None:
    correlation = tmp_path / "external-bestcorr.txt"
    correlation.write_text("2 1.0 0.125 0.000 0.125\n", encoding="utf-8")
    request_path, _, _ = _request(tmp_path, correlation_file=correlation)

    result = import_sqs_configuration(request_path, tmp_path / "imported")

    imported = result["imported_configuration"]
    assert imported["correlation_file"] == str(correlation.resolve())
    assert imported["correlation_text"] == correlation.read_text(encoding="utf-8")
    assert imported["correlation_assessment"] == "not_evaluated"
    assert "quality_pass" not in imported
    assert imported["external_structure"]["provenance"]["job_id"] is None


def test_duplicate_source_mapping_is_rejected_before_output_creation(tmp_path: Path) -> None:
    request_path, request, _ = _request(tmp_path)
    request["atom_mapping"][1]["source_index"] = 1
    modified = _copy_request(tmp_path, request)
    output = tmp_path / "duplicate-output"

    with pytest.raises(ValueError, match="unique|source_index"):
        import_sqs_configuration(modified, output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["null_sublattice", "component_conflict"])
def test_changed_substitution_requires_explicit_sublattice_and_component(
    tmp_path: Path, mutation: str
) -> None:
    request_path, request, _ = _request(tmp_path)
    # source_index=1 is the Ca-for-Mg substitution; null is valid only for an
    # unchanged parent site and must not trigger component inference.
    if mutation == "null_sublattice":
        changed_mapping = next(
            entry for entry in request["atom_mapping"] if entry["source_index"] == 1
        )
        changed_mapping["sublattice"] = None
        message = "sublattice|explicit"
    else:
        request["composition_request"]["components"][0]["element"] = "Sr"
        message = "component|composition|substitution"
    output = tmp_path / "implicit-sublattice-output"

    with pytest.raises(ValueError, match=message):
        import_sqs_configuration(_copy_request(tmp_path, request), output)
    assert not output.exists()


@pytest.mark.parametrize("mapping_mutation", ["missing", "out_of_range"])
def test_missing_or_out_of_range_source_mapping_is_rejected(
    tmp_path: Path, mapping_mutation: str
) -> None:
    request_path, request, _ = _request(tmp_path)
    if mapping_mutation == "missing":
        request["atom_mapping"] = request["atom_mapping"][:1]
    else:
        request["atom_mapping"][1]["source_index"] = 4

    with pytest.raises(ValueError, match="one entry|source_index|within|cover"):
        import_sqs_configuration(
            _copy_request(tmp_path, request), tmp_path / f"bad-{mapping_mutation}"
        )


def test_cell_outside_declared_tolerance_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad-cell.extxyz"
    source.write_text(
        FIXTURE.read_text(encoding="utf-8").replace("2.0000001 2.0000000", "2.0010000 2.0000000"),
        encoding="utf-8",
    )
    request_path, request, _ = _request(tmp_path)
    request["external_structure"]["path"] = str(source.resolve())
    output = tmp_path / "bad-cell-output"

    with pytest.raises(ValueError, match="cell|tolerance|geometry"):
        import_sqs_configuration(_copy_request(tmp_path, request), output)
    assert not output.exists()


def test_position_outside_declared_tolerance_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad-position.extxyz"
    source.write_text(
        FIXTURE.read_text(encoding="utf-8").replace("1.0000001 3.0000000", "1.0010000 3.0000000"),
        encoding="utf-8",
    )
    request_path, request, _ = _request(tmp_path)
    request["external_structure"]["path"] = str(source.resolve())
    output = tmp_path / "bad-position-output"

    with pytest.raises(ValueError, match="position|tolerance|geometry"):
        import_sqs_configuration(_copy_request(tmp_path, request), output)
    assert not output.exists()


@pytest.mark.parametrize(
    "operation",
    [
        {
            "kind": "vacancy",
            "sublattice": "cation",
            "parent_atom_id": 7,
            "parent_image": [0, 0, 0],
        },
        {
            "kind": "interstitial",
            "element": "H",
            "sublattice": "interstitial",
            "new_atom_id": 20,
        },
    ],
)
def test_vacancy_and_interstitial_inputs_are_explicitly_unsupported(tmp_path: Path, operation: dict) -> None:
    request_path, request, _ = _request(tmp_path)
    request["composition_request"]["compensation"]["operations"] = [operation]
    output = tmp_path / "unsupported-output"

    with pytest.raises(ValueError, match="vacancy|interstitial|unsupported"):
        import_sqs_configuration(_copy_request(tmp_path, request), output)
    assert not output.exists()


def test_multiframe_extxyz_requires_explicit_frame_selection(tmp_path: Path) -> None:
    source = tmp_path / "two-frames.extxyz"
    source.write_text(
        FIXTURE.read_text(encoding="utf-8") + "\n" + FIXTURE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    request_path, request, _ = _request(tmp_path)
    request["external_structure"]["path"] = str(source.resolve())
    request["external_structure"]["frame_index"] = None
    output = tmp_path / "multiframe-output"

    with pytest.raises(ValueError, match="frame|source_index|multiple"):
        import_sqs_configuration(_copy_request(tmp_path, request), output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("format", "poscar", "extxyz|format"), ("length_unit", "fractional", "angstrom|unit")],
)
def test_external_format_and_coordinate_unit_are_explicit(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    request_path, request, _ = _request(tmp_path)
    request["external_structure"][field] = value
    output = tmp_path / f"bad-{field}"

    with pytest.raises(ValueError, match=message):
        import_sqs_configuration(_copy_request(tmp_path, request), output)
    assert not output.exists()
