"""Focused LAMMPS data and input tests.

These tests cover Prism coordinate algebra and native input preparation only.
No synthetic LAMMPS log or dump is treated as a scientific result; native
result parsing is exercised only after a real returned task is available.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
import pytest
from ase import Atoms
from ase.calculators.lammps import Prism
from ase.io import read

from mlcc.lammps import (
    _compare_md_final_frames,
    _native_input_commands,
    _parse_thermo,
    _prism_from_lammps_bounds,
    export_lammps_data,
    parse_lammps_outputs,
    prepare_lammps,
    pressure_tensor_to_source,
    validate_lammps_protocol,
    validate_lammps_model,
)
from mlcc.modeling import ModelArtifacts, read_model_artifacts


REAL_RUN0 = Path(__file__).resolve().parents[2] / "workspace" / "tasks" / "p9-ni-lammps-run0-v001"
REAL_MODEL = (
    Path(__file__).resolve().parents[2]
    / "workspace"
    / "models"
    / "ni-abacus-engineering-relaxed"
    / "v001"
 )
REAL_RUN0_FILES = (
    "method.json",
    "atom-map.json",
    "in.lammps",
    "log.lammps",
    "dump.final",
    "model.data",
    "Ni_u3.eam",
)


def _copy_real_run0(tmp_path: Path) -> Path:
    if not REAL_RUN0.is_dir() or any(not (REAL_RUN0 / name).is_file() for name in REAL_RUN0_FILES):
        pytest.skip(f"real job41 artifact unavailable: {REAL_RUN0}")
    target = tmp_path / "job41-run0"
    target.mkdir()
    for name in REAL_RUN0_FILES:
        shutil.copy2(REAL_RUN0 / name, target / name)
    return target


def _model(tmp_path: Path) -> ModelArtifacts:
    atoms = Atoms(
        ["Ni", "O", "Ni"],
        positions=[[0.2, 0.4, 0.6], [1.3, 1.1, 2.0], [2.4, 2.5, 3.8]],
        cell=[[4.0, 0.3, 0.2], [0.8, 3.6, 0.4], [0.4, 0.5, 5.2]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([20, 5, 90], dtype=int))
    return ModelArtifacts("ni-triclinic-fixture", "v001", atoms, {}, tmp_path / "model")


def _pure_ni_model(tmp_path: Path) -> ModelArtifacts:
    atoms = Atoms(
        ["Ni", "Ni"],
        positions=[[0.2, 0.4, 0.6], [2.4, 2.5, 3.8]],
        cell=[[4.0, 0.3, 0.2], [0.8, 3.6, 0.4], [0.4, 0.5, 5.2]],
        pbc=True,
    )
    atoms.new_array("atom_id", np.asarray([20, 90], dtype=int))
    return ModelArtifacts("ni-pure-fixture", "v001", atoms, {}, tmp_path / "model")


def _potential(model_id: str) -> dict:
    return {
        "potential_id": "NiEAM-fixture",
        "version": "stable_22Jul2025_update4",
        "source": "official-lammps-potential-repository",
        "license": "GPL fixture use",
        "elements": ["Ni"],
        "element_order": ["Ni"],
        "model_ids": [model_id],
        "units": "metal",
        "atom_style": "atomic",
        "pair_style": "eam",
        "pair_coeff": ["* * Ni_u3.eam"],
        "files": [{"local_path": "/potentials/Ni_u3.eam", "filename": "Ni_u3.eam"}],
        "fixture": True,
    }


def _mace_potential(model_id: str) -> dict:
    return {
        "potential_id": "mace-mp-0b3-candidate",
        "version": "mace-0.3.10-model-v001",
        "source": "ACEsuit MACE-MP-0b3 public candidate",
        "license": "MIT model release; candidate only",
        "elements": ["Ni", "O"],
        "element_order": ["Ni", "O"],
        "model_ids": [model_id],
        "units": "metal",
        "atom_style": "atomic",
        "pair_style": "mace no_domain_decomposition",
        "pair_coeff": ["* * mace-candidate.model-lammps.pt Ni O"],
        "files": [{"local_path": "/potentials/mace-candidate.model-lammps.pt", "filename": "mace-candidate.model-lammps.pt"}],
        "fixture": True,
        "production_qualification": False,
    }


def _mace_qualification_run0() -> dict:
    return {
        **_run0(),
        "purpose": "potential_qualification",
        "static_tensor": True,
        "experiment_scope": "Unit MACE input contract only",
    }


def _run0() -> dict:
    return {
        "kind": "run0",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "timestep_ps": 0.001,
    }


def _md() -> dict:
    return {
        "kind": "md",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "nvt",
        "steps": 20,
        "timestep_ps": 0.001,
        "temperature_K": 330.0,
        "tdamp_ps": 0.1,
        "seed": 12345,
        "thermo_every": 5,
        "dump_every": 10,
    }


def test_export_triclinic_prism_and_stable_atom_mapping(tmp_path: Path):
    model = _model(tmp_path)
    exported = export_lammps_data(
        model,
        tmp_path / "task",
        element_order=["Ni", "O"],
        units="metal",
        atom_style="atomic",
    )

    data = Path(exported["data_path"]).read_text(encoding="utf-8")
    assert "3 atoms" in data
    assert "2 atom types" in data
    assert "Atoms # atomic" in data
    assert "xy xz yz" in data
    assert "charge" not in data.lower()
    loaded = read(
        str(tmp_path / "task" / "model.data"),
        format="lammps-data",
        atom_style="atomic",
        units="metal",
        Z_of_type={1: 28, 2: 8},
    )
    assert loaded.get_chemical_symbols() == ["Ni", "O", "Ni"]
    prism = Prism(model.atoms.cell.array, pbc=True, reduce_cell=False)
    assert loaded.cell.array == pytest.approx(prism.cell, abs=1.0e-10)
    assert loaded.positions == pytest.approx(
        prism.vector_to_lammps(model.atoms.positions), abs=1.0e-10
    )
    atom_map = json.loads(Path(exported["atom_map_path"]).read_text(encoding="utf-8"))
    assert atom_map["source_atom_ids"] == [20, 5, 90]
    assert [entry["lammps_id"] for entry in atom_map["atoms"]] == [1, 2, 3]
    assert [entry["type"] for entry in atom_map["atoms"]] == [1, 2, 1]
    rotation = np.asarray(atom_map["rotation_matrix_ase_to_lammps"], dtype=float)
    assert rotation.shape == (3, 3)
    assert rotation @ rotation.T == pytest.approx(np.eye(3), abs=1e-12)
    assert np.asarray(atom_map["lammps_prism"]) == pytest.approx(prism.get_lammps_prism())
    assert atom_map["lammps_prism"][3] * atom_map["lammps_prism"][4] > 0.0


def test_triclinic_bound_inversion_includes_combined_tilts():
    # For xy=2 and xz=3, xlo_bound uses xy+xz=5 rather than either tilt alone.
    assert _prism_from_lammps_bounds(
        [[0.0, 15.0, 2.0], [0.0, 10.0, 3.0], [0.0, 12.0, 1.0]]
    ) == pytest.approx([10.0, 9.0, 12.0, 2.0, 3.0, 1.0])


def test_export_rejects_multiple_masses_for_one_atomic_type(tmp_path: Path):
    model = _pure_ni_model(tmp_path)
    model.atoms.set_masses([58.0, 60.0])
    with pytest.raises(ValueError, match="multiple masses for element Ni"):
        export_lammps_data(
            model,
            tmp_path / "isotopes",
            element_order=["Ni"],
            units="metal",
            atom_style="atomic",
        )


def test_export_rejects_nonzero_initial_charges(tmp_path: Path):
    model = _pure_ni_model(tmp_path)
    model.atoms.set_initial_charges([0.25, 0.0])
    with pytest.raises(ValueError, match="non-zero initial charges"):
        export_lammps_data(
            model,
            tmp_path / "charged-atoms",
            element_order=["Ni"],
            units="metal",
            atom_style="atomic",
        )


def test_export_rejects_nonzero_derivation_charge_state(tmp_path: Path):
    model = _pure_ni_model(tmp_path)
    model.metadata["derivation"] = {"charge_state": 1}
    with pytest.raises(ValueError, match="charged derivation"):
        export_lammps_data(
            model,
            tmp_path / "charged-derivation",
            element_order=["Ni"],
            units="metal",
            atom_style="atomic",
        )


@pytest.mark.parametrize(
    ("units", "atom_style", "error"),
    [("real", "atomic", "units='metal'"), ("metal", "charge", "atom_style='atomic'")],
)
def test_export_rejects_unimplemented_units_or_atom_style(
    tmp_path: Path, units: str, atom_style: str, error: str
):
    with pytest.raises(ValueError, match=error):
        export_lammps_data(
            _model(tmp_path),
            tmp_path / "task",
            element_order=["Ni", "O"],
            units=units,
            atom_style=atom_style,
        )


def test_prepare_run0_has_explicit_native_contract_and_fixture_status(tmp_path: Path):
    model = _pure_ni_model(tmp_path)
    prepared = prepare_lammps(
        model,
        tmp_path / "run0",
        potential=_potential(model.model_id),
        protocol=_run0(),
    )

    assert prepared["files"] == ["model.data", "atom-map.json", "in.lammps", "method.json"]
    task = tmp_path / "run0"
    assert sorted(path.name for path in task.iterdir()) == sorted(
        ["model.data", "atom-map.json", "in.lammps", "method.json"]
    )
    input_text = (task / "in.lammps").read_text(encoding="utf-8")
    assert "units metal" in input_text
    assert "atom_style atomic" in input_text
    assert "boundary p p p" in input_text
    assert "pair_style eam" in input_text
    assert "pair_coeff * * Ni_u3.eam" in input_text
    assert "mass 1 " in input_text
    assert "timestep 0.001" in input_text
    assert "run 0" in input_text
    assert "velocity all create" not in input_text
    assert "write_dump all custom dump.final id type x y z fx fy fz" in input_text
    commands = _native_input_commands(
        _potential(model.model_id), _run0(), {"1": model.atoms.get_masses()[0]}
    )
    command_positions = [input_text.splitlines().index(command) for command in commands]
    assert command_positions == sorted(command_positions)
    method = json.loads((task / "method.json").read_text(encoding="utf-8"))
    assert method["potential"]["fixture"] is True
    assert method["production_qualification"] is False
    assert method["mass_source"] == "ModelAtoms masses"


def test_prepare_mace_candidate_emits_single_gpu_input_setup_and_binding(tmp_path: Path):
    model = _model(tmp_path)
    prepared = prepare_lammps(
        model,
        tmp_path / "mace-run0",
        potential=_mace_potential(model.model_id),
        protocol=_mace_qualification_run0(),
    )

    input_lines = (tmp_path / "mace-run0" / "in.lammps").read_text(encoding="utf-8").splitlines()
    assert input_lines.index("clear") < input_lines.index("package kokkos neigh half newton on")
    assert input_lines.index("package kokkos neigh half newton on") < input_lines.index("units metal")
    assert input_lines.index("atom_style atomic") < input_lines.index("atom_modify map yes")
    assert input_lines.index("atom_modify sort 0 0.0") < input_lines.index("read_data model.data")
    assert input_lines.index("newton on") < input_lines.index("read_data model.data")
    assert "pair_style mace no_domain_decomposition" in input_lines
    assert "pair_coeff * * mace-candidate.model-lammps.pt Ni O" in input_lines
    assert prepared["potential"]["production_qualification"] is False


@pytest.mark.parametrize(
    "change",
    ["element_order", "model_file", "unsupported_pair_style"],
)
def test_prepare_mace_rejects_unbound_model_or_element_mapping(tmp_path: Path, change: str):
    model = _model(tmp_path)
    potential = _mace_potential(model.model_id)
    if change == "element_order":
        potential["element_order"] = ["O", "Ni"]
    elif change == "unsupported_pair_style":
        potential["pair_style"] = "mace"
    else:
        potential["pair_coeff"] = ["* * unstaged.model-lammps.pt Ni O"]
    with pytest.raises(ValueError, match="MACE"):
        prepare_lammps(model, tmp_path / f"mace-{change}", potential=potential, protocol=_mace_qualification_run0())


def test_prepare_md_requires_explicit_temperature_seed_and_uses_ensemble(tmp_path: Path):
    model = _pure_ni_model(tmp_path)
    task = tmp_path / "md"
    prepare_lammps(model, task, potential=_potential(model.model_id), protocol=_md())
    input_text = (task / "in.lammps").read_text(encoding="utf-8")
    assert "velocity all create 330 12345" in input_text
    assert "fix integrator all nvt temp 330 330 0.1" in input_text
    assert "timestep 0.001" in input_text
    assert "dump trajectory all custom 10 trajectory.lammpstrj id type x y z fx fy fz" in input_text
    assert "dump_modify trajectory sort id format float %.16g" in input_text
    assert "thermo_modify format float %.16g" in input_text
    assert "run 20" in input_text
    commands = _native_input_commands(
        _potential(model.model_id), _md(), {"1": model.atoms.get_masses()[0]}
    )
    command_positions = [input_text.splitlines().index(command) for command in commands]
    assert command_positions == sorted(command_positions)

    missing_seed = _md()
    del missing_seed["seed"]
    with pytest.raises(KeyError, match="seed"):
        prepare_lammps(model, tmp_path / "missing-seed", potential=_potential(model.model_id), protocol=missing_seed)
    missing_tdamp = _md()
    del missing_tdamp["tdamp_ps"]
    with pytest.raises(KeyError, match="tdamp_ps"):
        prepare_lammps(model, tmp_path / "missing-tdamp", potential=_potential(model.model_id), protocol=missing_tdamp)
    nondividing_dump = _md()
    nondividing_dump["dump_every"] = 6
    with pytest.raises(ValueError, match="dump_every must divide steps"):
        prepare_lammps(model, tmp_path / "nondividing-dump", potential=_potential(model.model_id), protocol=nondividing_dump)


def test_prepare_rejects_nonfixture_or_inapplicable_potential(tmp_path: Path):
    model = _pure_ni_model(tmp_path)
    nonfixture = _potential(model.model_id)
    nonfixture["fixture"] = False
    with pytest.raises(ValueError, match="fixture potentials only"):
        prepare_lammps(model, tmp_path / "nonfixture", potential=nonfixture, protocol=_run0())
    other_model = _potential("other-model")
    with pytest.raises(ValueError, match="not applicable"):
        prepare_lammps(model, tmp_path / "other-model", potential=other_model, protocol=_run0())
    production = _potential(model.model_id)
    production["production_qualification"] = True
    with pytest.raises(ValueError, match="production-qualified"):
        prepare_lammps(model, tmp_path / "production", potential=production, protocol=_run0())


def test_parser_waits_for_actual_native_outputs(tmp_path: Path):
    model = _pure_ni_model(tmp_path)
    prepare_lammps(model, tmp_path / "task", potential=_potential(model.model_id), protocol=_run0())
    with pytest.raises(FileNotFoundError):
        parse_lammps_outputs(tmp_path / "task")


def test_parse_real_job41_run0_values_and_provenance(tmp_path: Path):
    task = _copy_real_run0(tmp_path)
    result = parse_lammps_outputs(task)
    if not REAL_MODEL.is_dir():
        pytest.skip(f"real job41 model unavailable: {REAL_MODEL}")
    validate_lammps_model(read_model_artifacts(REAL_MODEL), task)

    assert result["engine"] == "lammps"
    assert result["engine_version"] == "LAMMPS (22 Jul 2025 - Update 4)"
    assert result["lammps_version"] == result["engine_version"]
    assert result["units"] == "metal"
    assert result["atom_style"] == "atomic"
    assert result["step"] == 0
    assert result["atom_ids"] == [0, 1, 2, 3]
    assert result["types"] == [1, 1, 1, 1]
    assert result["energy_eV"] == pytest.approx(-17.79999340275548, abs=1.0e-13)
    assert result["temperature_K"] == pytest.approx(0.0, abs=1.0e-15)
    assert result["pressure_bar"] == pytest.approx(0.7220017493520471, abs=1.0e-13)
    assert "stress_GPa" not in result
    assert "pressure_tensor_GPa" not in result
    assert result["thermo_units"] == {
        "temp": "K",
        "pe": "eV",
        "ke": "eV",
        "etotal": "eV",
        "press": "bar",
    }
    forces = np.asarray(result["forces_eV_per_A"], dtype=float)
    assert forces.shape == (4, 3)
    np.testing.assert_allclose(
        forces,
        [
            [-0.00280363156719745, -6.843792901408893e-06, 2.667082810475091e-06],
            [0.01184487389100381, 5.527596475790597e-06, -4.092990495961971e-06],
            [-0.004521224423121972, -4.321081449314146e-06, -5.409180654948088e-06],
            [-0.004520017900684403, 5.63727787491683e-06, 6.835088340416753e-06],
        ],
        rtol=0.0,
        atol=1.0e-15,
    )
    assert all(Path(value).is_file() for value in result["source_files"].values())
    assert Path(result["source_files"]["model.data"]).name == "model.data"
    assert Path(result["source_files"]["Ni_u3.eam"]).name == "Ni_u3.eam"


def test_validate_real_job41_rejects_corrupt_model_binding(tmp_path: Path):
    task = _copy_real_run0(tmp_path)
    if not REAL_MODEL.is_dir():
        pytest.skip(f"real job41 model unavailable: {REAL_MODEL}")
    atom_map_path = task / "atom-map.json"
    atom_map = json.loads(atom_map_path.read_text(encoding="utf-8"))
    atom_map["atoms"][0]["source_atom_id"] = 99
    atom_map_path.write_text(json.dumps(atom_map, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source atom ID"):
        validate_lammps_model(read_model_artifacts(REAL_MODEL), task)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        (
            "source_cell_angstrom",
            [[3.5200000000785536, 0.0, 0.0], [0.0, 3.5200000000785536, 0.0], [0.0, 0.0, 3.53]],
            "source cell",
        ),
        (
            "rotation_matrix_ase_to_lammps",
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "rotation",
        ),
        ("masses_by_type", {"1": 59.0}, "masses"),
    ],
)
def test_validate_real_job41_rejects_corrupt_map_geometry_or_mass(
    tmp_path: Path, field: str, value: object, error: str
):
    task = _copy_real_run0(tmp_path)
    if not REAL_MODEL.is_dir():
        pytest.skip(f"real job41 model unavailable: {REAL_MODEL}")
    atom_map_path = task / "atom-map.json"
    atom_map = json.loads(atom_map_path.read_text(encoding="utf-8"))
    atom_map[field] = value
    atom_map_path.write_text(json.dumps(atom_map, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        validate_lammps_model(read_model_artifacts(REAL_MODEL), task)


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("positions", "initial positions"),
        ("masses", "model.data masses"),
    ],
)
def test_validate_real_job41_rejects_corrupt_initial_data(
    tmp_path: Path, field: str, error: str
):
    task = _copy_real_run0(tmp_path)
    if not REAL_MODEL.is_dir():
        pytest.skip(f"real job41 model unavailable: {REAL_MODEL}")
    data_path = task / "model.data"
    data_text = data_path.read_text(encoding="utf-8")
    original_text = data_text
    if field == "positions":
        lines = data_text.splitlines()
        atoms_header = next(
            index for index, line in enumerate(lines) if line.strip() == "Atoms # atomic"
        )
        atom_row = next(
            index for index in range(atoms_header + 1, len(lines)) if lines[index].strip()
        )
        columns = lines[atom_row].split()
        original_x = float(columns[2])
        columns[2] = format(original_x + 0.25, ".17g")
        assert float(columns[2]) != original_x
        lines[atom_row] = " ".join(columns)
        data_text = "\n".join(lines) + "\n"
    else:
        data_text = data_text.replace(
            "1      58.693399984901454 # Ni", "1      59.693399984901454 # Ni", 1
        )
    assert data_text != original_text
    data_path.write_text(data_text, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        validate_lammps_model(read_model_artifacts(REAL_MODEL), task)


@pytest.mark.parametrize("missing", ["model.data", "Ni_u3.eam"])
def test_parse_real_job41_requires_native_data_and_staged_potential(
    tmp_path: Path, missing: str
):
    task = _copy_real_run0(tmp_path)
    (task / missing).unlink()
    with pytest.raises(FileNotFoundError):
        parse_lammps_outputs(task)


def _set_copied_method_to_md(task: Path) -> None:
    method_path = task / "method.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method["protocol"] = _md()
    method["files"]["trajectory.lammpstrj"] = str(task / "trajectory.lammpstrj")
    method_path.write_text(json.dumps(method, indent=2) + "\n", encoding="utf-8")


def test_parse_real_job41_requires_md_trajectory(tmp_path: Path):
    task = _copy_real_run0(tmp_path)
    _set_copied_method_to_md(task)
    with pytest.raises(FileNotFoundError):
        parse_lammps_outputs(task)


def test_parse_real_job41_rejects_wrong_md_trajectory_step(tmp_path: Path):
    task = _copy_real_run0(tmp_path)
    _set_copied_method_to_md(task)
    trajectory_path = task / "trajectory.lammpstrj"
    trajectory_path.write_text((task / "dump.final").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="trajectory final step"):
        parse_lammps_outputs(task)


def test_real_log_error_is_preserved_after_copy_corruption(tmp_path: Path):
    task = _copy_real_run0(tmp_path)
    log_path = task / "log.lammps"
    log_path.write_text(
        log_path.read_text(encoding="utf-8") + "\nERROR: injected parser corruption\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match=r"^ERROR: injected parser corruption$"):
        parse_lammps_outputs(task)


def test_real_log_mismatched_potential_command_is_rejected(tmp_path: Path):
    task = _copy_real_run0(tmp_path)
    log_path = task / "log.lammps"
    log_text = log_path.read_text(encoding="utf-8")
    log_path.write_text(
        log_text.replace("pair_coeff * * Ni_u3.eam", "pair_coeff * * Other.eam", 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="native log.*pair_coeff"):
        parse_lammps_outputs(task)


@pytest.mark.parametrize(
    ("corruption", "error"),
    [
        ("id", "atom IDs differ"),
        ("type", "atom type differs"),
        ("step", "dump step differs"),
    ],
)
def test_real_dump_identity_and_step_corruptions_are_rejected(
    tmp_path: Path, corruption: str, error: str
):
    task = _copy_real_run0(tmp_path)
    dump_path = task / "dump.final"
    dump_text = dump_path.read_text(encoding="utf-8")
    if corruption == "id":
        dump_text = dump_text.replace(
            "1 1 0.007977439999999995", "99 1 0.007977439999999995", 1
        )
    elif corruption == "type":
        dump_text = dump_text.replace(
            "1 1 0.007977439999999995", "1 2 0.007977439999999995", 1
        )
    else:
        dump_text = dump_text.replace("ITEM: TIMESTEP\n0\n", "ITEM: TIMESTEP\n1\n", 1)
    dump_path.write_text(dump_text, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        parse_lammps_outputs(task)


def test_md_frame_comparison_matches_rows_by_atom_id_after_reordering():
    trajectory_rows = [
        (2, 1, [2.0, 0.0, 0.0], [0.2, 0.0, 0.0]),
        (1, 1, [1.0, 0.0, 0.0], [0.1, 0.0, 0.0]),
    ]
    final_rows = [
        (1, 1, [1.0, 0.0, 0.0], [0.1, 0.0, 0.0]),
        (2, 1, [2.0, 0.0, 0.0], [0.2, 0.0, 0.0]),
    ]
    _compare_md_final_frames(20, trajectory_rows, 20, final_rows)


@pytest.mark.parametrize(
    ("field", "error"),
    [("coordinates", "coordinates"), ("forces", "forces")],
)
def test_md_frame_comparison_rejects_same_step_coordinate_or_force_mismatch(
    field: str, error: str
):
    trajectory_rows = [(1, 1, [1.0, 0.0, 0.0], [0.1, 0.0, 0.0])]
    final_rows = [(1, 1, [1.0, 0.0, 0.0], [0.1, 0.0, 0.0])]
    if field == "coordinates":
        final_rows[0] = (1, 1, [1.0 + 2.0e-12, 0.0, 0.0], [0.1, 0.0, 0.0])
    else:
        final_rows[0] = (1, 1, [1.0, 0.0, 0.0], [0.1 + 2.0e-12, 0.0, 0.0])
    with pytest.raises(ValueError, match=error):
        _compare_md_final_frames(20, trajectory_rows, 20, final_rows)


def test_static_tensor_input_uses_zero_velocity_virial_compute(tmp_path):
    model = _pure_ni_model(tmp_path)
    protocol = {**_run0(), "static_tensor": True}
    prepare_lammps(model, tmp_path / "tensor", potential=_potential(model.model_id), protocol=protocol)
    text = (tmp_path / "tensor" / "in.lammps").read_text()
    assert "compute mlcc_static_pressure all pressure NULL virial" in text
    assert "velocity all set 0.0 0.0 0.0" in text
    assert "press pxx pyy pzz pxy pxz pyz" in text
    assert "thermo_modify press mlcc_static_pressure format float %.16g" in text
    expected = _native_input_commands(_potential(model.model_id), protocol, {"1": model.atoms.get_masses()[0]})
    indices = [text.splitlines().index(command) for command in expected]
    assert indices == sorted(indices)


@pytest.mark.parametrize("protocol", [{**_md(), "static_tensor": True}, {**_run0(), "static_tensor": "true"}])
def test_static_tensor_rejects_md_or_ambiguous_flag(protocol):
    with pytest.raises(ValueError, match="static_tensor"):
        validate_lammps_protocol(protocol)


def test_pressure_tensor_sign_units_order_and_source_rotation():
    # Analytic tensor transformation, not a synthetic scientific result.
    theta = np.pi / 6
    rotation = np.array([[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]])
    restricted_cell = np.array([[3., 0, 0], [.3, 4., 0], [.2, .5, 5.]])
    source_cell = restricted_cell @ rotation.T
    native = np.array([[100., 30., 40.], [30., 200., 50.], [40., 50., 300.]])
    output = pressure_tensor_to_source([100, 200, 300, 30, 40, 50], source_cell)
    expected = rotation @ native @ rotation.T * 1e-4
    np.testing.assert_allclose(output["pressure_tensor_GPa"], expected, atol=1e-14)
    np.testing.assert_allclose(output["stress_GPa"], -expected, atol=1e-14)
    assert output["pressure_component_order"] == ["xx", "yy", "zz", "xy", "xz", "yz"]
    assert output["stress_sign"] == "tension_positive"
    assert np.trace(output["pressure_tensor_GPa"]) == pytest.approx(.06)


def test_tensor_thermo_contract_is_explicit_and_complete():
    # Isolated numeric table unit test; no engine execution/qualification claim.
    table = "Step Temp PotEng KinEng TotEng Press Pxx Pyy Pzz Pxy Pxz Pyz\n0 0 -8 0 -8 200 100 200 300 30 40 50\nLoop time"
    row = _parse_thermo(table, {**_run0(), "static_tensor": True})
    assert [row[key] for key in ("pxx", "pyy", "pzz", "pxy", "pxz", "pyz")] == [100, 200, 300, 30, 40, 50]
    for invalid, message in [
        (table.replace("300 30 40 50", "300 30 40"), "row differs"),
        (table.replace("0 0 -8 0 -8", "0 2 -8 1 -7"), "zero temperature"),
        (table.replace("-8 200 100", "-8 201 100"), "tensor trace"),
        (table.replace("30 40 50", "30 nan 50"), "non-finite"),
        ("Step Temp PotEng KinEng TotEng Press\n0 0 -8 0 -8 200\nLoop time", "requested thermo header"),
    ]:
        with pytest.raises(ValueError, match=message):
            _parse_thermo(invalid, {**_run0(), "static_tensor": True})
