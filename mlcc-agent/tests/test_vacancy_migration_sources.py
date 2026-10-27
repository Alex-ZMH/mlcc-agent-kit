"""New source adapters: original dump mapping and saved NEB image semantics."""

import json

import numpy as np

from mlcc.vacancy_migration import _md_native_frames, _neb_saved_frames


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _native_fixture(directory, *, timestep=True):
    protocol = {"kind": "md", "boundary": ["p", "p", "p"]}
    time = {"initial_step": 0}
    if timestep:
        protocol["timestep_ps"] = 0.0001
        time["timestep_ps"] = 0.0001
    model = {"model_id": "vacancy-fixture", "version": "v001"}
    atom_map = {
        **model, "units": "metal", "lammps_prism": [4, 4, 4, 0, 0, 0],
        "source_cell_angstrom": [[0, -4, 0], [4, 0, 0], [0, 0, 4]],
        "rotation_matrix_ase_to_lammps": [[0, 1, 0], [-1, 0, 0], [0, 0, 1]],
        "lammps_origin_angstrom": [0, 0, 0],
        "atoms": [{"lammps_id": 1, "source_atom_id": 101, "type": 1},
                  {"lammps_id": 2, "source_atom_id": 303, "type": 1}],
    }
    native_job = {"scheduler_job_id": "unit-fixture", "scheduler_state": "COMPLETED", "exit_code": "0:0"}
    _write(directory / "atom-map.json", atom_map)
    _write(directory / "method.json", {**model, "units": "metal", "protocol": protocol,
                                       "potential": {"potential_id": "engineering-fixture"}})
    _write(directory / "md-conditions.json", {"model": model, "protocol": protocol, "time": time,
                                               "native_job": native_job})
    _write(directory / "task.json", {"scheduler_job_id": "unit-fixture", "task_id": "fixture",
                                      "method_set": "fixture", "study": {"study_id": "fixture-study"}})
    header = "ITEM: TIMESTEP\n{step}\nITEM: NUMBER OF ATOMS\n2\nITEM: BOX BOUNDS xy xz yz pp pp pp\n0 4 0\n0 4 0\n0 4 0\nITEM: ATOMS id type x y z fx fy fz\n"
    text = header.format(step=0) + "2 1 2 1 3 0 0 0\n1 1 1 2 3 0 0 0\n"
    text += header.format(step=1) + "1 1 1 2 3 0 0 0\n2 1 2 1 3 0 0 0\n"
    (directory / "trajectory.lammpstrj").write_text(text, encoding="utf-8")


def test_native_md_rotation_uses_mapping_and_retains_missing_unwrap(tmp_path):
    _native_fixture(tmp_path)
    frames, source, cell = _md_native_frames(tmp_path)
    assert frames[0]["source_atom_ids"] == [303, 101]
    assert frames[1]["source_atom_ids"] == [101, 303]
    np.testing.assert_allclose(frames[0]["positions_angstrom"], [[1, -2, 3], [2, -1, 3]])
    assert frames[1]["physical_time_ps"] == 0.0001
    assert frames[0]["native_image_flags"] is None
    assert source["unwrap_evidence"] == "missing"
    assert source["native_job"]["scheduler_job_id"] == "unit-fixture"
    assert cell == [[0, -4, 0], [4, 0, 0], [0, 0, 4]]


def test_missing_native_timestep_is_not_filled_with_zero(tmp_path):
    _native_fixture(tmp_path, timestep=False)
    frames, _, _ = _md_native_frames(tmp_path)
    assert all(frame["physical_time_ps"] is None for frame in frames)
    assert frames[1]["step"] == 1


def test_saved_neb_keeps_minimization_step_separate_from_time_and_preserves_barrier(tmp_path):
    native = {
        "schema": "mlcc.lammps-neb-result.v1", "mode": "neb_path", "time_ps": None,
        "model_id": "vacancy-fixture", "version": "v001", "study": {"study_id": "fixture-study"},
        "potential": {"potential_id": "engineering-fixture"}, "scheduler_job_id": "unit-fixture",
        "scheduler_state": "COMPLETED", "exit_code": "0:0", "path_provenance": {"path_id": "fixture"},
        "barrier": {"forward_eV": 0.3, "backward_eV": 0.2}, "native_converged": False,
        "stopping": {"climbing": "iteration limit"},
        "image_dumps": [{
            "image_index": 0, "step": 200, "reaction_coordinate": 0.0, "energy_eV": -1.0,
            "mode": "neb_path", "time_ps": None, "source_cell_angstrom": [[4,0,0],[0,4,0],[0,0,4]],
            "source_atom_ids": [101], "rows": [{"source_atom_id": 101, "positions_angstrom": [1,2,3]}],
        }],
    }
    path = tmp_path / "neb.json"
    _write(path, native)
    frames, source, _ = _neb_saved_frames(path)
    assert frames[0]["minimization_step"] == 200
    assert "step" not in frames[0]
    assert frames[0]["physical_time_ps"] is None
    assert source["native_result"] == native
    assert source["barrier"] == native["barrier"]
    assert source["native_result"]["native_converged"] is False
