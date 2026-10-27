"""Focused ABACUS electrostatic-potential format tests.

Every cube in this module is a software-contract fixture.  The files do not
claim native ABACUS output, GPU support, or scientific qualification.  Native
task binding is owned by the main integration and is intentionally not tested
here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mlcc.abacus import BOHR_PER_ANGSTROM
from mlcc.electrostatic_potential import (
    _map_cube_atoms,
    read_abacus_electrostatic_cube,
    read_abacus_electrostatic_task,
)


_STEP_HEADER = "STEP: 0  Cubefile created from ABACUS. Inner loop is z, followed by y and x"
_STEP_VECTORS_BOHR = (
    (1.0, 0.1, 0.0),
    (0.0, 1.5, 0.2),
    (0.3, 0.0, 2.0),
)
_GRID = (2, 2, 2)
_ORIGIN_BOHR = (0.2, 0.3, 0.4)
_ATOMS = (
    (20, 10.0, (0.25, 0.50, 0.75)),
    (8, 6.0, (1.25, 1.50, 1.75)),
)
_VALUES = (0.5, -1.25, 2.0, 3.5, 4.25, 5.5, 6.75, 8.0)


def _cube_text(
    *,
    values: str | list[float] | tuple[float, ...] = _VALUES,
    marker: bool = True,
    nspin: int = 1,
    second_line: str | None = None,
    first_line: str | None = None,
    step_vectors: tuple[tuple[float, float, float], ...] = _STEP_VECTORS_BOHR,
    atom_lines: tuple[tuple[int, float, tuple[float, float, float]], ...] = _ATOMS,
) -> str:
    """Return a documented-format cube fixture, never a native result."""

    header = first_line if first_line is not None else _STEP_HEADER
    if marker:
        header += " [software_contract_only]"
    line2 = second_line if second_line is not None else f"{nspin} (nspin)"
    lines = [
        header,
        line2,
        f"{len(atom_lines)} {_ORIGIN_BOHR[0]} {_ORIGIN_BOHR[1]} {_ORIGIN_BOHR[2]}",
    ]
    for count, vector in zip(_GRID, step_vectors):
        lines.append(f"{count} {vector[0]} {vector[1]} {vector[2]}")
    for atomic_number, valence_charge, position in atom_lines:
        lines.append(
            f"{atomic_number} {valence_charge} {position[0]} {position[1]} {position[2]}"
        )
    if isinstance(values, str):
        value_text = values
    else:
        value_text = " ".join(str(value) for value in values)
    lines.append(value_text)
    return "\n".join(lines) + "\n"


def _write_cube(tmp_path: Path, *, name: str = "ElecStaticPot.cube", **kwargs) -> Path:
    path = tmp_path / name
    path.write_text(_cube_text(**kwargs), encoding="utf-8")
    return path


def test_cube_parser_preserves_nonorthogonal_xyz_zfast_units_and_values(tmp_path):
    path = _write_cube(tmp_path)

    cube = read_abacus_electrostatic_cube(path)

    expected_steps = np.asarray(_STEP_VECTORS_BOHR, dtype=float)
    expected_cell = expected_steps * np.asarray(_GRID, dtype=float)[:, None]
    assert cube["schema"] == "mlcc.abacus-electrostatic-cube.v1"
    assert cube["shape"] == list(_GRID)
    assert cube["origin_bohr"] == pytest.approx(_ORIGIN_BOHR)
    assert cube["origin_angstrom"] == pytest.approx(
        np.asarray(_ORIGIN_BOHR) / BOHR_PER_ANGSTROM
    )
    assert np.asarray(cube["step_vectors_bohr"]) == pytest.approx(expected_steps)
    assert np.asarray(cube["cell_bohr"]) == pytest.approx(expected_cell)
    assert np.asarray(cube["step_vectors_angstrom"]) == pytest.approx(
        expected_steps / BOHR_PER_ANGSTROM
    )
    assert np.asarray(cube["cell_angstrom"]) == pytest.approx(
        expected_cell / BOHR_PER_ANGSTROM
    )
    assert cube["values_Ry"] == pytest.approx(list(_VALUES))
    assert cube["values_eV"] == pytest.approx([value * 13.605698 for value in _VALUES])
    assert [atom["atomic_number"] for atom in cube["atoms"]] == [20, 8]
    assert [atom["valence_charge"] for atom in cube["atoms"]] == [10.0, 6.0]
    assert np.asarray([atom["position_bohr"] for atom in cube["atoms"]]) == pytest.approx(
        np.asarray([[0.25, 0.5, 0.75], [1.25, 1.5, 1.75]])
    )
    assert np.asarray([atom["position_angstrom"] for atom in cube["atoms"]]) == pytest.approx(
        np.asarray([[0.25, 0.5, 0.75], [1.25, 1.5, 1.75]]) / BOHR_PER_ANGSTROM
    )
    assert cube["native_output_observed"] is False
    assert cube["native_GPU_accepted"] is False
    assert cube["evidence_kind"] == "software_contract_only"


@pytest.mark.parametrize("nspin", (1, 2))
def test_cube_parser_accepts_scalar_nspin_one_or_two_and_unbound_header(tmp_path, nspin):
    path = _write_cube(tmp_path, marker=False, nspin=nspin)

    cube = read_abacus_electrostatic_cube(path)

    assert cube["evidence_kind"] == "unbound_native_format"
    assert cube["native_output_observed"] is False
    assert cube["native_GPU_accepted"] is False


@pytest.mark.parametrize("name", ("CHG.cube", "POT.cube", "ElecStaticPot.CUBE"))
def test_cube_parser_requires_exact_electrostatic_potential_filename(tmp_path, name):
    path = _write_cube(tmp_path, name=name)

    with pytest.raises(ValueError):
        read_abacus_electrostatic_cube(path)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"first_line": "STEP: 1  not an ABACUS cube"},
        {"second_line": "2 (nspin) 0.636506 (fermi energy, in Ry)"},
        {"second_line": "4 (nspin)"},
    ),
)
def test_cube_parser_rejects_wrong_step_or_density_header(tmp_path, kwargs):
    path = _write_cube(tmp_path, **kwargs)

    with pytest.raises(ValueError):
        read_abacus_electrostatic_cube(path)


@pytest.mark.parametrize(
    "values",
    (
        _VALUES[:-1],
        "0.5 -1.25 2.0 3.5 4.25 5.5 6.75 nan",
        "0.5 -1.25 2.0 3.5 4.25 5.5 6.75 1,2",
    ),
)
def test_cube_parser_rejects_missing_nan_or_non_scalar_grid_data(tmp_path, values):
    path = _write_cube(tmp_path, values=values)

    with pytest.raises((ValueError, TypeError)):
        read_abacus_electrostatic_cube(path)


def test_cube_parser_preserves_missing_file_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_abacus_electrostatic_cube(tmp_path / "ElecStaticPot.cube")


def _mapping_inputs():
    """Return a source-order result and a permuted ABACUS atom map."""

    source_positions_angstrom = np.asarray(
        [
            [1.25, 1.50, 1.75],  # source atom 11: O, cube index 1
            [0.25, 0.50, 0.75],  # source atom 10: Ca, cube index 0
        ],
        dtype=float,
    ) / BOHR_PER_ANGSTROM
    result = {
        "atom_ids": [11, 10],
        "final_atoms": {
            "symbols": ["O", "Ca"],
            "positions_angstrom": source_positions_angstrom.tolist(),
            "cell_angstrom": (
                np.asarray(_STEP_VECTORS_BOHR) * np.asarray(_GRID)[:, None]
                / BOHR_PER_ANGSTROM
            ).tolist(),
        },
    }
    atom_map = {
        "source_atom_ids": [11, 10],
        "abacus_order": [
            {
                "abacus_index": 0,
                "source_index": 1,
                "atom_id": 10,
                "element": "Ca",
                "label": "Ca1",
            },
            {
                "abacus_index": 1,
                "source_index": 0,
                "atom_id": 11,
                "element": "O",
                "label": "O1",
            },
        ],
    }
    method = {
        "element_order": ["Ca", "O"],
        "pseudopotential_metadata": {
            "Ca": {"element": "Ca", "valence_electrons_per_atom": 10.0},
            "O": {"element": "O", "valence_electrons_per_atom": 6.0},
        },
    }
    return result, atom_map, method


def test_map_cube_atoms_binds_abacus_order_to_source_ids_and_geometry(tmp_path):
    cube = read_abacus_electrostatic_cube(_write_cube(tmp_path))
    result, atom_map, method = _mapping_inputs()

    mapped = _map_cube_atoms(cube, atom_map, result, method)

    assert {(entry["atom_id"], entry["source_index"]) for entry in mapped} == {
        (10, 1),
        (11, 0),
    }


@pytest.mark.parametrize(
    "change",
    (
        {"element": "O"},
        {"atom_id": 99},
        {"source_index": 0},
    ),
)
def test_map_cube_atoms_rejects_wrong_atom_mapping(tmp_path, change):
    cube = read_abacus_electrostatic_cube(_write_cube(tmp_path))
    result, atom_map, method = _mapping_inputs()
    atom_map = json.loads(json.dumps(atom_map))
    atom_map["abacus_order"][0].update(change)

    with pytest.raises(ValueError):
        _map_cube_atoms(cube, atom_map, result, method)


@pytest.mark.parametrize(
    "cube_change",
    (
        {"atomic_number": 8},
        {"valence_charge": 11.0},
    ),
)
def test_map_cube_atoms_rejects_species_or_valence_mismatch(tmp_path, cube_change):
    cube = read_abacus_electrostatic_cube(_write_cube(tmp_path))
    result, atom_map, method = _mapping_inputs()
    cube = json.loads(json.dumps(cube))
    cube["atoms"][0].update(cube_change)

    with pytest.raises(ValueError):
        _map_cube_atoms(cube, atom_map, result, method)


@pytest.mark.parametrize("field", ("positions_angstrom", "cell_angstrom"))
def test_map_cube_atoms_rejects_result_geometry_mismatch(tmp_path, field):
    cube = read_abacus_electrostatic_cube(_write_cube(tmp_path))
    result, atom_map, method = _mapping_inputs()
    result = json.loads(json.dumps(result))
    if field == "positions_angstrom":
        result["final_atoms"][field][0][0] += 1e-3
    else:
        result["final_atoms"][field][0][0] += 1e-3

    with pytest.raises(ValueError):
        _map_cube_atoms(cube, atom_map, result, method)


@pytest.mark.parametrize(("step_delta_bohr", "reject"), ((0.4e-6, False), (0.6e-6, True)))
def test_map_cube_atoms_applies_six_decimal_cell_tolerance_per_grid_row(
    tmp_path, step_delta_bohr, reject
):
    step_vectors = [list(vector) for vector in _STEP_VECTORS_BOHR]
    step_vectors[0][0] += step_delta_bohr
    path = _write_cube(tmp_path, step_vectors=tuple(tuple(vector) for vector in step_vectors))
    cube = read_abacus_electrostatic_cube(path)
    result, atom_map, method = _mapping_inputs()

    if reject:
        with pytest.raises(ValueError):
            _map_cube_atoms(cube, atom_map, result, method)
    else:
        mapped = _map_cube_atoms(cube, atom_map, result, method)
        assert {(entry["atom_id"], entry["source_index"]) for entry in mapped} == {
            (10, 1),
            (11, 0),
        }


def _write_software_contract_task(tmp_path: Path) -> Path:
    task_dir = tmp_path / "software-contract-task"
    model_dir = tmp_path / "software-contract-model"
    study_path = tmp_path / "software-contract-study.json"
    task_dir.mkdir()
    model_dir.mkdir()
    (model_dir / "model.json").write_text("{}\n", encoding="utf-8")
    study_path.write_text("{}\n", encoding="utf-8")
    for filename in ("result.json", "method.json", "STRU.atom-map.json"):
        (task_dir / filename).write_text("{}\n", encoding="utf-8")
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "fixture_purpose": "software_contract_only",
                "model_path": str(model_dir),
                "study_file": str(study_path),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return task_dir


def test_task_reader_rejects_software_contract_before_native_validation(tmp_path):
    task_dir = _write_software_contract_task(tmp_path)

    with pytest.raises(ValueError, match="software contract fixture"):
        read_abacus_electrostatic_task(task_dir)

