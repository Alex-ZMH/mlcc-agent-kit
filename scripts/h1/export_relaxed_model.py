"""Materialize the completed ABACUS Ni fixture relaxation as a model artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from ase.io import read

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mlcc-agent" / "src"))

from mlcc.abacus import parse_abacus_outputs  # noqa: E402
from mlcc.modeling import read_model_artifacts, write_model_artifacts  # noqa: E402


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _same_input(left, right) -> None:
    assert left.get_chemical_symbols() == right.get_chemical_symbols()
    assert left.arrays["atom_id"].tolist() == right.arrays["atom_id"].tolist()
    np.testing.assert_allclose(left.cell.array, right.cell.array, rtol=0.0, atol=2e-8)
    np.testing.assert_allclose(left.get_positions(), right.get_positions(), rtol=0.0, atol=2e-8)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, default=ROOT / "workspace/tasks/h1-ni-relax-v001")
    parser.add_argument("--parent-model", type=Path, default=ROOT / "workspace/models/ni-fcc-engineering/v001")
    parser.add_argument("--output", type=Path, default=ROOT / "workspace/models/ni-abacus-engineering-relaxed/v001")
    parser.add_argument("--post-input", type=Path)
    args = parser.parse_args()
    task_dir, parent_dir, output_dir = (path.resolve() for path in (args.task, args.parent_model, args.output))
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    method = json.loads((task_dir / "method.json").read_text(encoding="utf-8"))
    assert task["stage"] == "P4"
    assert task["engine"] == method["engine"] == "abacus"
    assert task["engine_version"] == method["abacus_version_target"] == "3.10.1"
    assert method["stage"] == "relax"
    assert task["method_set"] == method["method_set"]
    assert task["model_id"] == method["model_id"] and task["model_version"] == method["version"]
    assert method["parameters"]["force_thr_eV_per_A"] == 0.02
    assert method["parameters"]["relax_nmax"] == 40
    assert not output_dir.exists()
    assert task["status"] == "COMPLETED" and task["exit_code"] == "0:0"
    parent = read_model_artifacts(parent_dir)
    input_atoms = read(task_dir / "input.extxyz")
    _same_input(parent.atoms, input_atoms)
    parser_model = read_model_artifacts(parent_dir)
    parser_model.atoms = input_atoms
    parsed = parse_abacus_outputs(task_dir, source_model=parser_model, stage="relax",
                                  log_path=task_dir / "OUT.NiPW/running_relax.log",
                                  final_stru_path=task_dir / "OUT.NiPW/STRU_ION_D")
    assert parsed.electronic_converged is True and parsed.ionic_converged is True
    assert parsed.atom_ids == parent.atom_ids
    force_threshold = float(method["parameters"]["force_thr_eV_per_A"])
    max_force = float(np.linalg.norm(parsed.forces_eV_per_A, axis=1).max())
    assert max_force < force_threshold
    if args.post_input is not None:
        _same_input(parsed.final_atoms, read(args.post_input.resolve()))
    write_model_artifacts(parsed.final_atoms, output_dir, model_id="ni-abacus-engineering-relaxed", version="v001",
                          fixture=True, fixture_purpose="abacus_fixed_cell_relaxation_derivative",
                          material=parent.metadata["material"],
                          phase_requested=str(parent.metadata["phase_requested"]),
                          source_path=_relative(task_dir / "OUT.NiPW/STRU_ION_D"),
                          source_version=f"ABACUS {task['engine_version']}; method {task['method_set']}; Slurm job {task['scheduler_job_id']}",
                          source_atoms=parent.atoms)
    metadata_path = output_dir / "model.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    lineage = [{"derived_atom_id": int(i), "parent_atom_id": int(i), "element": symbol}
               for i, symbol in zip(parent.atom_ids, parent.atoms.get_chemical_symbols())]
    metadata.update(engine="abacus", engine_version=task["engine_version"], method_set=task["method_set"],
                    method={key: method[key] for key in ("engine", "abacus_version_target", "stage", "basis_type", "ks_solver", "method_set")},
                    source_task=task["task_id"], source_job_id=str(task["scheduler_job_id"]),
                    source_method=_relative(task_dir / "method.json"),
                    parent_models=[{"model_id": parent.model_id, "version": parent.version, "path": _relative(parent_dir)}],
                    atom_id_parent_lineage=lineage,
                    relaxation={"force_thr_eV_per_A": force_threshold, "max_force_eV_per_A": max_force,
                                "electronic_converged": True, "ionic_converged": True},
                    materialization={"geometry": "parse_abacus_outputs.final_atoms", "geometry_recomputed": False})
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    dopants_path = output_dir / "dopants.json"
    dopants = json.loads(dopants_path.read_text(encoding="utf-8"))
    dopants.update(source_task=task["task_id"], source_job_id=str(task["scheduler_job_id"]), parent_models=metadata["parent_models"])
    dopants_path.write_text(json.dumps(dopants, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": _relative(output_dir), "source_task": task["task_id"],
                      "source_job_id": str(task["scheduler_job_id"]), "atom_ids": parent.atom_ids}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
