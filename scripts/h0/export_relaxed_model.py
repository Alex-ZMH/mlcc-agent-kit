"""Materialize the real H0 fixed-cell relaxation as a derived model.

The geometry is taken directly from ``parse_vasp_outputs(...).final_atoms``
for the completed relaxation task.  This script does not generate, optimize,
or otherwise alter atomic coordinates; it only serializes the parsed result,
records provenance, and checks the already submitted post-relax input.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version as package_version
import json
from pathlib import Path
import sys

import numpy as np
from pymatgen.core import Structure
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mlcc-agent" / "src"))

from mlcc.modeling import read_model_artifacts, write_model_artifacts  # noqa: E402
from mlcc.vasp import parse_vasp_outputs  # noqa: E402


DEFAULT_PARENT_MODEL = ROOT / "workspace" / "models" / "ni-fcc-engineering" / "v001"
DEFAULT_REPORT = ROOT / "workspace" / "reports" / "h0" / "relax-lineage.json"

SYMPREC_ANGSTROM = 1e-5
ANGLE_TOLERANCE_DEG = 5.0


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _periodic_delta(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    delta = np.asarray(left, dtype=float) - np.asarray(right, dtype=float)
    return delta - np.rint(delta)


def _assert_task_completed(task_dir: Path) -> dict[str, object]:
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert task["task_id"] == task_dir.name, (task["task_id"], task_dir.name)
    assert task["status"] == "COMPLETED", task["status"]
    assert task["exit_code"] == "0:0", task["exit_code"]
    return task


def _compare_structures(
    left: Structure,
    right: Structure,
    *,
    coordinate_atol: float = 1e-10,
) -> dict[str, float]:
    assert len(left) == len(right), (len(left), len(right))
    assert [site.specie.symbol for site in left] == [site.specie.symbol for site in right]
    np.testing.assert_allclose(left.lattice.matrix, right.lattice.matrix, rtol=0.0, atol=1e-10)
    periodic_delta = _periodic_delta(left.frac_coords, right.frac_coords)
    np.testing.assert_allclose(periodic_delta, 0.0, rtol=0.0, atol=coordinate_atol)
    return {
        "cell_max_abs_A": float(np.max(np.abs(left.lattice.matrix - right.lattice.matrix))),
        "periodic_fractional_max_abs": float(np.max(np.abs(periodic_delta))),
        "cartesian_max_abs_A": float(np.max(np.abs(left.cart_coords - right.cart_coords))),
    }


def _symmetry_record(structure: Structure, symprec: float, angle_tolerance: float) -> dict[str, object]:
    analyzer = SpacegroupAnalyzer(
        structure,
        symprec=float(symprec),
        angle_tolerance=float(angle_tolerance),
    )
    symmetrized = analyzer.get_symmetrized_structure()
    return {
        "detector": "pymatgen.symmetry.analyzer.SpacegroupAnalyzer",
        "symprec_angstrom": float(symprec),
        "angle_tolerance_degree": float(angle_tolerance),
        "space_group_symbol": analyzer.get_space_group_symbol(),
        "space_group_number": int(analyzer.get_space_group_number()),
        "crystal_system": analyzer.get_crystal_system(),
        "lattice_type": analyzer.get_lattice_type(),
        "point_group_symbol": analyzer.get_point_group_symbol(),
        "equivalent_indices": [[int(index) for index in group] for group in symmetrized.equivalent_indices],
    }


def materialize(
    relax_task_dir: Path,
    post_task_dir: Path,
    parent_model_dir: Path,
    output_dir: Path,
    report_path: Path,
    *,
    model_version: str,
    symprec: float,
    angle_tolerance: float,
) -> dict[str, object]:
    relax_task_dir = relax_task_dir.resolve()
    post_task_dir = post_task_dir.resolve()
    parent_model_dir = parent_model_dir.resolve()
    output_dir = output_dir.resolve()
    report_path = report_path.resolve()

    relax_task = _assert_task_completed(relax_task_dir)
    post_task = _assert_task_completed(post_task_dir)
    relax_method = json.loads((relax_task_dir / "method.json").read_text(encoding="utf-8"))
    parent = read_model_artifacts(parent_model_dir)
    parent_metadata = json.loads((parent_model_dir / "model.json").read_text(encoding="utf-8"))

    assert relax_method["engine"] == "vasp", relax_method["engine"]
    assert relax_method["stage"] == "relax", relax_method["stage"]
    assert int(relax_method["parameters"]["ISIF"]) == 2, relax_method["parameters"]["ISIF"]
    assert int(relax_method["parameters"]["NSW"]) > 0, relax_method["parameters"]["NSW"]
    assert int(relax_method["parameters"]["IBRION"]) == 2, relax_method["parameters"]["IBRION"]
    assert post_task["structure_source"] == _relative(relax_task_dir / "CONTCAR"), (
        post_task["structure_source"],
        _relative(relax_task_dir / "CONTCAR"),
    )

    parsed_relax = parse_vasp_outputs(relax_task_dir, stage="relax")
    assert parsed_relax.electronic_converged is True
    assert parsed_relax.ionic_converged is True
    relaxed_force_max = float(np.linalg.norm(parsed_relax.forces_eV_per_A, axis=1).max())
    force_threshold = abs(float(relax_method["parameters"]["EDIFFG"]))
    assert relaxed_force_max < force_threshold, (relaxed_force_max, force_threshold)

    relaxed_atoms = parsed_relax.final_atoms
    assert parsed_relax.atom_ids == parent.atom_ids
    assert relaxed_atoms.get_chemical_symbols() == parent.atoms.get_chemical_symbols()
    np.testing.assert_allclose(relaxed_atoms.cell.array, parent.atoms.cell.array, rtol=0.0, atol=1e-10)
    assert relaxed_atoms.pbc.tolist() == parent.atoms.pbc.tolist()

    relax_final = Structure.from_file(str(relax_task_dir / "CONTCAR"))
    post_input = Structure.from_file(str(post_task_dir / "POSCAR"))
    task_input_match = _compare_structures(relax_final, post_input)
    parsed_final_match = _compare_structures(
        AseAtomsAdaptor().get_structure(relaxed_atoms),
        relax_final,
    )

    # source.cif is the perturbed parent input model geometry.  The pristine
    # parent source.cif is retained as an explicit provenance link below.
    artifacts = write_model_artifacts(
        relaxed_atoms,
        output_dir,
        model_id="ni-fcc-engineering-relaxed",
        version=model_version,
        fixture=True,
        fixture_purpose="fixed_cell_relaxation_derivative",
        phase_requested=str(parent_metadata["phase_requested"]),
        source_path=_relative(relax_task_dir / "CONTCAR"),
        source_version=(
            f"VASP job {relax_task['scheduler_job_id']}; parse_vasp_outputs; "
            f"ASE {package_version('ase')}; pymatgen {package_version('pymatgen')}; "
            f"pymatgen-core {__import__('pymatgen.core').core.__version__}"
        ),
        engineering_perturbation=parent_metadata.get("engineering_perturbation"),
        source_atoms=parent.atoms,
    )
    assert {path.name for path in output_dir.iterdir()} == {
        "source.cif",
        "model.extxyz",
        "model.json",
        "dopants.json",
    }

    exported = read_model_artifacts(output_dir)
    exported_structure = AseAtomsAdaptor().get_structure(exported.atoms)
    symmetry = _symmetry_record(exported_structure, symprec, angle_tolerance)
    # ASE's extxyz writer emits eight decimal places for coordinates; retain
    # that serialization tolerance when checking the persisted derived model.
    exported_match = _compare_structures(exported_structure, relax_final, coordinate_atol=2e-8)
    source_cif = Structure.from_file(str(output_dir / "source.cif"))
    parent_structure = AseAtomsAdaptor().get_structure(parent.atoms)
    source_match = _compare_structures(source_cif, parent_structure, coordinate_atol=1e-8)

    model_json_path = output_dir / "model.json"
    model_metadata = json.loads(model_json_path.read_text(encoding="utf-8"))
    model_metadata.update(
        {
            "model_version": model_version,
            "phase_relaxed": f"{symmetry['space_group_symbol']}_relaxed",
            "source_cif_role": "parent input model geometry",
            "parent_models": [
                {
                    "model_id": parent_metadata["model_id"],
                    "version": parent_metadata["version"],
                    "path": _relative(parent_model_dir),
                }
            ],
            "source_task": relax_task["task_id"],
            "source_job_id": str(relax_task["scheduler_job_id"]),
            "source_result": _relative(relax_task_dir / "result.json"),
            "materialization": {
                "stage": "result",
                "geometry": "parse_vasp_outputs.final_atoms",
                "source_task": relax_task["task_id"],
                "source_job_id": str(relax_task["scheduler_job_id"]),
                "geometry_recomputed": False,
            },
            "original_source": {
                "parent_model": _relative(parent_model_dir),
                "parent_input_model": _relative(parent_model_dir / "model.extxyz"),
                "original_pristine_source_cif": _relative(parent_model_dir / "source.cif"),
                "source_cif_in_derived_model": "parent input model geometry",
            },
            "relaxation": {
                "kind": "fixed_cell_ionic",
                "cell_constraint": "fixed",
                "isif": int(relax_method["parameters"]["ISIF"]),
                "ibrion": int(relax_method["parameters"]["IBRION"]),
                "nsw": int(relax_method["parameters"]["NSW"]),
                "ediffg_eV_per_A": float(relax_method["parameters"]["EDIFFG"]),
                "ionic_converged": bool(parsed_relax.ionic_converged),
                "max_force_eV_per_A": relaxed_force_max,
                "source_task": relax_task["task_id"],
                "source_job_id": str(relax_task["scheduler_job_id"]),
            },
            "symmetry": symmetry,
        }
    )
    model_json_path.write_text(
        json.dumps(model_metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    dopants_path = output_dir / "dopants.json"
    dopants = json.loads(dopants_path.read_text(encoding="utf-8"))
    dopants.update(
        {
            "model_id": "ni-fcc-engineering-relaxed",
            "version": model_version,
            "model_version": model_version,
            "parent_models": model_metadata["parent_models"],
            "source_task": relax_task["task_id"],
            "source_job_id": str(relax_task["scheduler_job_id"]),
            "materialization_stage": "result",
        }
    )
    dopants_path.write_text(
        json.dumps(dopants, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    # Re-read after metadata augmentation to keep the persisted four-file
    # contract in the validation path.
    persisted = read_model_artifacts(output_dir)
    assert persisted.model_id == "ni-fcc-engineering-relaxed"
    assert persisted.version == model_version
    persisted_match = _compare_structures(
        AseAtomsAdaptor().get_structure(persisted.atoms),
        relax_final,
        coordinate_atol=2e-8,
    )

    report = {
        "schema": "mlcc.h0.relax-lineage.v1",
        "materialization_stage": "result",
        "model_version": model_version,
        "materialized_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": [str(value) for value in sys.argv],
        "pymatgen_version": package_version("pymatgen"),
        "pymatgen_core_version": __import__("pymatgen.core").core.__version__,
        "parent_model": {
            "model_id": parent_metadata["model_id"],
            "version": parent_metadata["version"],
            "path": _relative(parent_model_dir),
            "source_cif": _relative(parent_model_dir / "source.cif"),
            "original_pristine_source_cif": _relative(parent_model_dir / "source.cif"),
        },
        "derived_model": {
            "model_id": "ni-fcc-engineering-relaxed",
            "version": model_version,
            "model_version": model_version,
            "path": _relative(output_dir),
            "files": [_relative(output_dir / name) for name in ("source.cif", "model.extxyz", "model.json", "dopants.json")],
            "geometry_file": _relative(output_dir / "model.extxyz"),
            "source_cif_role": "parent input model geometry",
            "original_pristine_source_cif": _relative(parent_model_dir / "source.cif"),
            "phase_relaxed": f"{symmetry['space_group_symbol']}_relaxed",
        },
        "as_run_tasks": {
            "relax": {
                "task_id": relax_task["task_id"],
                "scheduler_job_id": str(relax_task["scheduler_job_id"]),
                "path": _relative(relax_task_dir),
                "result": _relative(relax_task_dir / "result.json"),
                "contcar": _relative(relax_task_dir / "CONTCAR"),
                "status": relax_task["status"],
                "exit_code": relax_task["exit_code"],
            },
            "post_relax": {
                "task_id": post_task["task_id"],
                "scheduler_job_id": str(post_task["scheduler_job_id"]),
                "path": _relative(post_task_dir),
                "result": _relative(post_task_dir / "result.json"),
                "poscar": _relative(post_task_dir / "POSCAR"),
                "structure_source": post_task["structure_source"],
                "status": post_task["status"],
                "exit_code": post_task["exit_code"],
            },
        },
        "relaxation": {
            "fixed_cell": True,
            "isif": int(relax_method["parameters"]["ISIF"]),
            "ionic_converged": bool(parsed_relax.ionic_converged),
            "electronic_converged": bool(parsed_relax.electronic_converged),
            "max_force_eV_per_A": relaxed_force_max,
            "force_threshold_eV_per_A": force_threshold,
        },
        "checks": {
            "relax_final_matches_parsed_final_atoms": parsed_final_match,
            "post_relax_poscar_matches_relax_contcar": task_input_match,
            "fixed_cell_matches_parent_model": {
                "passed": True,
                "cell_max_abs_A": float(np.max(np.abs(relaxed_atoms.cell.array - parent.atoms.cell.array))),
            },
            "derived_model_matches_relax_contcar": exported_match,
            "persisted_model_matches_relax_contcar": persisted_match,
            "derived_source_cif_matches_parent_input_model": source_match,
        },
        "symmetry": symmetry,
        "notes": [
            f"Derived model geometry was materialized from parse_vasp_outputs.final_atoms after {relax_task['task_id']} completed.",
            "No geometry was generated or recalculated by this script.",
            f"{post_task['task_id']} POSCAR and method/atom-map/model_version were read only and left unchanged.",
            "The model remains an Ni engineering fixture and is not a production material qualification.",
            "The derived source.cif records the perturbed parent input model; the pristine parent source.cif is linked in original_pristine_source_cif.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relax-task", type=Path, required=True)
    parser.add_argument("--post-task", type=Path, required=True)
    parser.add_argument("--parent-model", type=Path, default=DEFAULT_PARENT_MODEL)
    parser.add_argument("--model-version", default="v001")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--symprec", type=float, default=SYMPREC_ANGSTROM)
    parser.add_argument("--angle-tolerance", type=float, default=ANGLE_TOLERANCE_DEG)
    args = parser.parse_args()
    output_arg = args.output
    if output_arg is None:
        output_arg = Path("workspace") / "models" / "ni-fcc-engineering-relaxed" / args.model_version
    paths = {
        "relax_task": args.relax_task if args.relax_task.is_absolute() else ROOT / args.relax_task,
        "post_task": args.post_task if args.post_task.is_absolute() else ROOT / args.post_task,
        "parent_model": args.parent_model if args.parent_model.is_absolute() else ROOT / args.parent_model,
        "output": output_arg if output_arg.is_absolute() else ROOT / output_arg,
        "report": args.report if args.report.is_absolute() else ROOT / args.report,
    }
    report = materialize(
        paths["relax_task"],
        paths["post_task"],
        paths["parent_model"],
        paths["output"],
        paths["report"],
        model_version=args.model_version,
        symprec=args.symprec,
        angle_tolerance=args.angle_tolerance,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
