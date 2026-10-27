"""Text and input-contract fixtures for fixed-cell internal relaxation.

The log snippets below are parser fixtures only.  They are not native LAMMPS
results and do not establish an executed or scientifically qualified task.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from mlcc.lammps_interface_normal import (
    _minimization_rows,
    normal_input_commands,
    validate_normal_protocol,
)


def _protocol() -> dict[str, object]:
    return {
        "kind": "interface_normal",
        "purpose": "interface_normal_response",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "none",
        "static_tensor": True,
        "experiment_scope": "mathematical fixture for clamped internal relaxation",
        "timestep_ps": 0.001,
        "normal_response": {
            "schema": "mlcc.interface-normal-protocol.v1",
            "kinematics": "fixed_cell_clamped_internal_relaxation",
            "normal_cartesian": [0.0, 0.0, 1.0],
            "area_angstrom2": 20.0,
            "interface_count": 2,
            "fixed_atom_ids": [20],
            "moving_atom_ids": [90],
            "free_atom_ids": [5],
            "minimization": {
                "min_style": "cg",
                "etol": 1.0e-12,
                "ftol_eV_per_A": 1.0e-8,
                "maxiter": 25,
                "maxeval": 50,
            },
            "points": [
                {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
                {"point_id": "load", "branch": "loading", "displacement_angstrom": 0.01},
                {"point_id": "return", "branch": "unloading", "displacement_angstrom": 0.0},
            ],
        },
    }


def _atom_map() -> dict[str, object]:
    return {
        "model_id": "ni-layered-fixture",
        "version": "v001",
        "source_cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
        "atoms": [
            {"source_index": 0, "source_atom_id": 20, "lammps_id": 3, "type": 1},
            {"source_index": 1, "source_atom_id": 5, "lammps_id": 1, "type": 1},
            {"source_index": 2, "source_atom_id": 90, "lammps_id": 2, "type": 1},
        ],
    }


def _stats(reason: str = "force tolerance") -> str:
    return "\n".join(
        [
            "MLCC_NORMAL_MIN_BEGIN index=0",
            "Minimization stats:",
            f"  Stopping criterion = {reason}",
            "  Energy initial, next-to-last, final = ",
            "    -1.0 -1.2 -1.2",
            "  Force two-norm initial, final = 2.0 1.0e-9",
            "  Force max component initial, final = 1.5 8.0e-10",
            "  Final line search alpha, max atom move = 1.0 0.01",
            "  Iterations, force evaluations = 7 9",
            "MLCC_NORMAL_MIN_END index=0",
        ]
    )


def test_relaxation_commands_keep_free_atoms_free_and_restore_raw_forces():
    protocol = _protocol()
    validate_normal_protocol(protocol)
    commands = normal_input_commands(protocol, _atom_map())

    assert commands[:3] == [
        "group mlcc_normal_fixed id 3",
        "group mlcc_normal_moving id 2",
        "group mlcc_normal_free id 1",
    ]
    assert not any("displace_atoms mlcc_normal_free" in command for command in commands)
    assert commands.count("fix mlcc_normal_fixed_clamp mlcc_normal_fixed setforce 0 0 0") == 3
    assert commands.count("fix mlcc_normal_moving_clamp mlcc_normal_moving setforce 0 0 0") == 3
    assert "thermo_modify norm no" in commands
    assert "neigh_modify every 1 delay 0 check yes" in commands
    assert commands.count("min_style cg") == 3
    assert commands.count("minimize 1e-12 1e-08 25 50") == 3
    assert commands.count('print "MLCC_NORMAL_MIN_BEGIN index=0"') == 1
    assert commands.count('print "MLCC_NORMAL_MIN_END index=0"') == 1
    assert commands.count("unfix mlcc_normal_fixed_clamp") == 3
    assert commands.count("unfix mlcc_normal_moving_clamp") == 3
    assert commands.count("run 0 pre yes") == 3
    assert all(
        commands.index("run 0 pre yes") < commands.index('print "MLCC_NORMAL index=0 pe=$(pe:%.16g)"')
        for _ in [0]
    )
    assert not any("storeforce" in command for command in commands)


def test_relaxation_requires_explicit_minimization_and_disjoint_groups():
    protocol = _protocol()
    protocol["normal_response"] = deepcopy(protocol["normal_response"])
    protocol["normal_response"]["minimization"] = {
        "min_style": "cg",
        "etol": 0.0,
        "ftol_eV_per_A": 0.0,
        "maxiter": 25,
        "maxeval": 50,
    }
    with pytest.raises(ValueError, match="positive etol or ftol"):
        validate_normal_protocol(protocol)

    protocol = _protocol()
    protocol["normal_response"] = deepcopy(protocol["normal_response"])
    protocol["normal_response"]["free_atom_ids"] = [90]
    with pytest.raises(ValueError, match="must not overlap"):
        validate_normal_protocol(protocol)


def test_native_minimization_summary_retains_convergence_fields():
    result = _minimization_rows(_stats(), [{}])
    assert result == [
        {
            "stopping_criterion": "force tolerance",
            "iterations": 7,
            "force_evaluations": 9,
            "force_two_norm_initial": pytest.approx(2.0),
            "force_two_norm_final": pytest.approx(1.0e-9),
            "force_max_component_initial": pytest.approx(1.5),
            "force_max_component_final": pytest.approx(8.0e-10),
            "energy_initial": pytest.approx(-1.0),
            "energy_penultimate": pytest.approx(-1.2),
            "energy_final": pytest.approx(-1.2),
            "raw_summary": "\n".join(_stats().splitlines()[1:-1]),
            "converged": True,
        }
    ]


def test_native_minimization_exhaustion_is_not_converged():
    result = _minimization_rows(_stats("max iterations"), [{}])[0]
    assert result["stopping_criterion"] == "max iterations"
    assert result["converged"] is False


def test_native_minimization_missing_stats_is_an_error():
    text = "\n".join(
        [
            "MLCC_NORMAL_MIN_BEGIN index=0",
            "MLCC_NORMAL_MIN_END index=0",
        ]
    )
    with pytest.raises(ValueError, match="no native Minimization stats block"):
        _minimization_rows(text, [{}])
