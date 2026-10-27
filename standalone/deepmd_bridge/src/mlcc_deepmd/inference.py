"""Same frozen model, same geometry: Python and native LAMMPS interface gate.

These functions perform numerical work and must run inside a Slurm job on
the configured compute site. MLCC's existing LAMMPS geometry/rotation/parser
is reused without modifying the installed bundle.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
from ase import Atoms

GPA_PER_EV_A3 = 160.21766208


def prepare_interface_case(frame: dict, model_file: str | Path, directory: str | Path,
                           *, type_map: list[str], plugin: str | None = None) -> dict:
    """Stage a declared engineering frame and frozen PT model for run0."""
    from mlcc.lammps import prepare_lammps
    from mlcc.modeling import ModelArtifacts

    source_model = Path(model_file).resolve()
    if source_model.suffix != ".pth":
        raise ValueError("the selected PyTorch TorchScript route requires a frozen .pth model")
    output = Path(directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    atoms = Atoms(frame["elements"], positions=frame["positions_angstrom"],
                  cell=frame["cell_angstrom"], pbc=True)
    atoms.set_array("atom_id", np.asarray(frame["atom_ids"], dtype=int))
    model = ModelArtifacts(frame["model_id"], frame["model_version"], atoms,
                           {"source_task_id": frame["source_task_id"]}, output)
    shutil.copyfile(source_model, output / "frozen.pth")
    potential = {
        "potential_id": "deepmd-engineering", "version": "0.1.0",
        "source": str(source_model), "license": "project engineering model; not distributed",
        "pair_style": "deepmd frozen.pth", "pair_coeff": ["* * " + " ".join(type_map)],
        "fixture": True, "production_qualification": False,
        "units": "metal", "atom_style": "atomic", "elements": type_map,
        "element_order": type_map, "model_ids": [model.model_id],
        "files": [{"local_path": str(source_model), "filename": "frozen.pth"}],
    }
    protocol = {
        "purpose": "potential_qualification", "kind": "run0", "static_tensor": True,
        "experiment_scope": "same frozen DeePMD model interface; no material qualification",
        "units": "metal", "boundary": ["p", "p", "p"], "timestep_ps": 0.001,
    }
    prepare_lammps(model, output, potential=potential, protocol=protocol)
    if plugin:
        input_path = output / "in.lammps"
        input_path.write_text(f'plugin load "{plugin}"\n' + input_path.read_text(encoding="utf-8"),
                              encoding="utf-8", newline="\n")
    (output / "frame.json").write_text(json.dumps(frame, indent=2) + "\n", encoding="utf-8")
    return {"directory": str(output), "model": str(output / "frozen.pth"),
            "type_map": type_map, "plugin": plugin, "production_qualification": False}


def evaluate_frozen(directory: str | Path) -> dict:
    """Evaluate the staged frozen model using the exact source geometry."""
    from deepmd.infer import DeepPot
    import deepmd
    import torch

    output = Path(directory)
    frame = json.loads((output / "frame.json").read_text(encoding="utf-8"))
    method = json.loads((output / "method.json").read_text(encoding="utf-8"))
    dp = DeepPot(str(output / "frozen.pth"))
    type_map = dp.get_type_map()
    if type_map != method["element_order"]:
        raise ValueError("frozen model type_map differs from LAMMPS atom types")
    atype = [type_map.index(symbol) for symbol in frame["elements"]]
    energy, forces, virial = dp.eval(
        np.asarray(frame["positions_angstrom"]).reshape(1, -1),
        np.asarray(frame["cell_angstrom"]).reshape(1, 9), atype)
    result = {
        "schema": "mlcc.deepmd-frozen-evaluation.v1",
        "model_file": str((output / "frozen.pth").resolve()),
        "source_task_id": frame["source_task_id"], "type_map": type_map,
        "atom_ids": frame["atom_ids"], "elements": frame["elements"],
        "positions_angstrom": frame["positions_angstrom"], "cell_angstrom": frame["cell_angstrom"],
        "energy_eV": float(energy[0, 0]), "forces_eV_per_A": forces[0].tolist(),
        "virial_eV": virial[0].reshape(3, 3).tolist(),
        "deepmd_version": deepmd.__version__, "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(), "production_qualification": False,
    }
    (output / "python-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def compare_interface(directory: str | Path, *, energy_atol: float = 1e-6,
                      force_atol: float = 1e-6, virial_atol: float = 1e-5) -> dict:
    """Compare native E/F/virial in the source Cartesian frame, saving failure."""
    from mlcc.lammps import parse_lammps_outputs

    output = Path(directory)
    reference = json.loads((output / "python-result.json").read_text(encoding="utf-8"))
    native = parse_lammps_outputs(output)
    if native["atom_ids"] != reference["atom_ids"] or native["elements"] != reference["elements"]:
        raise ValueError("native LAMMPS atom identity differs from frozen model evaluation")
    cell = np.asarray(reference["cell_angstrom"])
    np.testing.assert_allclose(native["cell_angstrom"], cell, atol=1e-10, rtol=0)
    # Permit only periodic image changes introduced by LAMMPS wrapping.
    fractional_delta = (np.asarray(native["positions_angstrom"]) - reference["positions_angstrom"]) @ np.linalg.inv(cell)
    np.testing.assert_allclose(fractional_delta, np.rint(fractional_delta), atol=1e-9, rtol=0)
    virial = -np.asarray(native["stress_GPa"]) * abs(np.linalg.det(cell)) / GPA_PER_EV_A3
    errors = {
        "energy_eV": abs(native["energy_eV"] - reference["energy_eV"]),
        "force_eV_per_A": float(np.max(np.abs(np.asarray(native["forces_eV_per_A"]) - reference["forces_eV_per_A"]))),
        "virial_eV": float(np.max(np.abs(virial - reference["virial_eV"]))),
    }
    tolerances = dict(energy_eV=energy_atol, force_eV_per_A=force_atol, virial_eV=virial_atol)
    result = {
        "schema": "mlcc.deepmd-interface-acceptance.v1",
        "status": "passed" if all(errors[key] <= tolerances[key] for key in errors) else "failed",
        "max_absolute_errors": errors, "absolute_tolerances": tolerances,
        "native_virial_eV": virial.tolist(), "python_virial_eV": reference["virial_eV"],
        "native_result": native, "python_result": reference,
        "scientific_status": "not_qualified", "design_assessment": "not_assessed",
        "scope": "one frozen model, one geometry, declared runtime and device only",
    }
    (output / "interface-acceptance.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if result["status"] != "passed":
        raise ValueError(f"DeePMD/LAMMPS interface mismatch: {errors}")
    return result
