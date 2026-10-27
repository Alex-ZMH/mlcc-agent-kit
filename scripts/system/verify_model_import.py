"""Verify the installed P2 model-import contract and generate local ABACUS inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

import numpy as np
from ase.io import read as ase_read


ROOT = Path(__file__).resolve().parents[2]
MODEL_RELATIVE = Path("workspace/models/cazro3-pnma-pristine/v001")
SOURCE_RELATIVE = Path("workspace/sources/cazro3/COD-1532747.cif")
ABACUS_CONFIG_RELATIVE = Path("workspace/configs/cazro3-abacus-input-check-v001.json")
TARGET_CELL = np.diag([5.58305, 5.75904, 8.00703])
EXPECTED_COMPOSITION = {"Ca": 4, "Zr": 4, "O": 12}


def _check(checks: dict[str, Any], name: str, condition: bool, detail: Any = None) -> None:
    checks[name] = {"passed": bool(condition), "detail": detail}
    if not condition:
        raise RuntimeError(f"model-import check failed: {name}: {detail}")


def _require_line(text: str, keyword: str, expected: str) -> None:
    pattern = rf"(?m)^\s*{re.escape(keyword)}\s+{re.escape(expected)}\s*$"
    if re.search(pattern, text) is None:
        raise RuntimeError(f"ABACUS INPUT is missing {keyword}={expected}")


def _verify_model(
    model: Any,
    model_dir: Path,
    source_file: Path,
    checks: dict[str, Any],
) -> dict[str, Any]:
    metadata = model.metadata
    required_files = {
        "source.cif",
        "source.extxyz",
        "model.extxyz",
        "model.json",
        "dopants.json",
        "atom-lineage.json",
    }
    _check(
        checks,
        "required_model_artifacts",
        required_files.issubset({path.name for path in model_dir.iterdir()}),
        sorted(required_files),
    )
    source_original_name = metadata.get("source_original_file")
    _check(checks, "source_original_metadata", source_original_name == "source.original.cif", source_original_name)
    source_original = model_dir / str(source_original_name)
    _check(checks, "source_original_exists", source_original.is_file(), str(source_original))
    _check(
        checks,
        "source_original_bytes_equal",
        source_original.read_bytes() == source_file.read_bytes(),
        str(source_file),
    )

    _check(checks, "material", metadata.get("material") == "CaZrO3", metadata.get("material"))
    _check(
        checks,
        "phase_requested",
        metadata.get("phase_requested") == "orthorhombic_Pnma",
        metadata.get("phase_requested"),
    )
    _check(
        checks,
        "source_reference_unrelaxed",
        metadata.get("scientific_status") == "source_reference_unrelaxed",
        metadata.get("scientific_status"),
    )
    _check(checks, "relaxation_not_run", metadata.get("relaxation_status") == "not_run", metadata.get("relaxation_status"))
    _check(checks, "production_not_qualified", metadata.get("production_qualified") is False, metadata.get("production_qualified"))
    _check(checks, "source_reference", "COD 1532747" in str(metadata.get("source_reference")), metadata.get("source_reference"))
    _check(checks, "source_temperature_reference", "173 K" in str(metadata.get("source_version")), metadata.get("source_version"))
    _check(
        checks,
        "source_index_basis",
        metadata.get("source_index_basis") == "full_expanded_structure_order",
        metadata.get("source_index_basis"),
    )

    composition = {str(key): int(value) for key, value in metadata["composition"].items()}
    _check(checks, "composition", composition == EXPECTED_COMPOSITION, composition)
    _check(checks, "atom_count", len(model.atoms) == 20, len(model.atoms))
    _check(checks, "model_atom_ids", model.atom_ids == list(range(20)), model.atom_ids)
    _check(
        checks,
        "target_cell",
        np.allclose(model.atoms.cell.array, TARGET_CELL, rtol=0.0, atol=1e-8),
        model.atoms.cell.array.tolist(),
    )

    source_atoms = ase_read(str(model_dir / "source.extxyz"), format="extxyz", index=0)
    _check(
        checks,
        "source_atom_ids",
        source_atoms.arrays.get("atom_id") is not None
        and source_atoms.arrays["atom_id"].tolist() == list(range(20)),
        source_atoms.arrays.get("atom_id", []).tolist() if "atom_id" in source_atoms.arrays else None,
    )
    source_volume = float(abs(np.linalg.det(source_atoms.cell.array)))
    model_volume = float(abs(np.linalg.det(model.atoms.cell.array)))
    _check(
        checks,
        "source_model_volume_equal",
        np.isclose(source_volume, model_volume, rtol=1e-8, atol=1e-8),
        {"source": source_volume, "model": model_volume},
    )

    basis_transform = metadata.get("basis_transform", {})
    _check(
        checks,
        "audited_basis_transform",
        basis_transform.get("fractional_matrix") == [[-1, 0, 0], [0, 0, -1], [0, -1, 0]],
        basis_transform,
    )
    _check(
        checks,
        "basis_target_cell",
        np.allclose(np.asarray(basis_transform.get("target_lattice_angstrom"), dtype=float), TARGET_CELL, rtol=0.0, atol=1e-8),
        basis_transform.get("target_lattice_angstrom"),
    )

    lineage = json.loads((model_dir / "atom-lineage.json").read_text(encoding="utf-8"))
    entries = lineage.get("entries", [])
    _check(checks, "lineage_schema", lineage.get("schema") == "mlcc.atom-lineage.v1", lineage.get("schema"))
    _check(checks, "lineage_count", len(entries) == 20, len(entries))
    source_ids = [int(entry["source_atom_id"]) for entry in entries]
    working_ids = [int(entry["working_atom_id"]) for entry in entries]
    _check(checks, "lineage_source_ids", source_ids == list(range(20)), source_ids)
    _check(checks, "lineage_working_ids", working_ids == list(range(20)), working_ids)
    _check(
        checks,
        "lineage_coordinates",
        all(
            entry["element"] == model.atoms.get_chemical_symbols()[index]
            and np.allclose(entry["source_frac_coords"], source_atoms.get_scaled_positions(wrap=False)[index], rtol=0.0, atol=1e-8)
            and np.allclose(entry["working_frac_coords"], model.atoms.get_scaled_positions(wrap=False)[index], rtol=0.0, atol=1e-8)
            for index, entry in enumerate(entries)
        ),
        "source and working coordinates agree with their atom lineage",
    )
    _check(
        checks,
        "lineage_index_basis",
        lineage.get("source_index_basis") == "full_expanded_structure_order",
        lineage.get("source_index_basis"),
    )
    _check(
        checks,
        "source_and_working_retained",
        (model_dir / "source.extxyz").is_file() and (model_dir / "model.extxyz").is_file(),
        ["source.extxyz", "model.extxyz"],
    )
    return {
        "model_id": model.model_id,
        "version": model.version,
        "atom_count": len(model.atoms),
        "composition": composition,
        "source_volume_angstrom3": source_volume,
        "model_volume_angstrom3": model_volume,
    }


def _generate_abacus_input(model: Any, config: dict[str, Any], report_dir: Path, checks: dict[str, Any]) -> dict[str, Any]:
    from mlcc.abacus import (
        AbacusExecution,
        AbacusMethod,
        AbacusParameters,
        _read_stru,
        prepare_abacus,
    )

    input_dir = report_dir / "abacus-input"
    science = AbacusMethod(**config["science"])
    execution = AbacusExecution(**config["execution"])
    parameters = AbacusParameters(**config["parameters"])
    pseudopotentials = config["site_resources"]["pseudopotential_files"]
    element_order = [str(value) for value in config["element_order"]]
    kpoints = tuple(int(value) for value in config["kpoints"])
    stage = str(config.get("stage", "scf"))
    _check(checks, "abacus_stage", stage == "scf", stage)
    prepared = prepare_abacus(
        model,
        input_dir,
        method=science,
        execution=execution,
        parameters=parameters,
        stage="scf",
        pseudopotentials=pseudopotentials,
        element_order=element_order,
        kpoints=kpoints,
    )
    input_text = (input_dir / "INPUT").read_text(encoding="utf-8")
    _require_line(input_text, "scf_thr", "0.0001")
    _require_line(input_text, "nbands", "88")
    _require_line(input_text, "smearing_method", "fixed")
    _check(checks, "abacus_kpoints", prepared.kpoints == (2, 2, 2), prepared.kpoints)
    kpt_lines = (input_dir / "KPT").read_text(encoding="utf-8").splitlines()
    _check(checks, "abacus_kpt_file", kpt_lines[-1] == "2 2 2 0 0 0", kpt_lines)
    _check(checks, "abacus_scf_thr", parameters.scf_thr == 1e-4, parameters.scf_thr)
    _check(checks, "abacus_fixed_occupations", science.occupations == "fixed" and science.smearing_method is None, science.occupations)
    _check(checks, "abacus_no_smearing_sigma", "smearing_sigma" not in input_text, input_text)
    _check(checks, "abacus_nbands", parameters.nbands == 88, parameters.nbands)

    mapping_path = input_dir / "STRU.atom-map.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    _check(checks, "abacus_element_order", mapping.get("element_order") == element_order, mapping.get("element_order"))
    _check(checks, "abacus_source_atom_ids", mapping.get("source_atom_ids") == model.atom_ids, mapping.get("source_atom_ids"))
    abacus_order = mapping.get("abacus_order", [])
    _check(checks, "abacus_order_count", len(abacus_order) == 20, len(abacus_order))
    _check(
        checks,
        "abacus_order_elements_and_ids",
        all(
            int(entry["atom_id"]) == int(model.atoms.arrays["atom_id"][int(entry["source_index"])])
            and str(entry["element"]) == model.atoms.get_chemical_symbols()[int(entry["source_index"])]
            for entry in abacus_order
        ),
        abacus_order,
    )
    grouped_elements = [str(entry["element"]) for entry in abacus_order]
    _check(
        checks,
        "abacus_grouping",
        grouped_elements == (["Ca"] * 4 + ["Zr"] * 4 + ["O"] * 12),
        grouped_elements,
    )
    roundtrip = _read_stru(input_dir / "STRU", mapping)
    _check(checks, "abacus_stru_atom_ids_reversible", roundtrip.arrays["atom_id"].tolist() == model.atom_ids, roundtrip.arrays["atom_id"].tolist())
    _check(checks, "abacus_stru_elements_reversible", roundtrip.get_chemical_symbols() == model.atoms.get_chemical_symbols(), roundtrip.get_chemical_symbols())
    _check(
        checks,
        "abacus_stru_coordinates_reversible",
        np.allclose(roundtrip.get_positions(), model.atoms.get_positions(), rtol=0.0, atol=1e-8),
        "STRU direct-coordinate round trip",
    )
    _check(
        checks,
        "no_task_json_created",
        not any(path.name == "task.json" for path in input_dir.rglob("task.json")),
        str(input_dir),
    )
    return {
        "directory": str(input_dir),
        "stage": prepared.stage,
        "files": {name: str(path) for name, path in prepared.files.items()},
        "element_order": prepared.element_order,
        "atom_ids": prepared.abacus_atom_ids,
        "kpoints": list(prepared.kpoints),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    bundle_root = args.bundle_root.resolve()
    checks: dict[str, Any] = {}
    report: dict[str, Any] = {
        "passed": False,
        "bundle_root": str(bundle_root),
        "model_dir": str((ROOT / MODEL_RELATIVE).resolve()),
        "new_numerical_jobs": [],
        "task_json_created": False,
        "ca_so_header_compatibility_verified": False,
        "scientific_method_qualification_verified": False,
        "scope": "installed_P2_model_import_and_local_ABACUS_input_generation_only",
    }
    try:
        bundle_src = bundle_root / "src"
        if not bundle_src.is_dir():
            raise RuntimeError(f"bundle root has no src directory: {bundle_src}")
        sys.path.insert(0, str(bundle_src))
        from mlcc.modeling import read_model_artifacts

        model_dir = ROOT / MODEL_RELATIVE
        source_file = ROOT / SOURCE_RELATIVE
        config_path = ROOT / ABACUS_CONFIG_RELATIVE
        model = read_model_artifacts(model_dir)
        report["model"] = _verify_model(model, model_dir, source_file, checks)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        report["abacus_input"] = _generate_abacus_input(model, config, report_dir, checks)
        report["checks"] = checks
        report["passed"] = True
        report["limitations"] = [
            "Ca full-relativistic/has_so header compatibility with the current nspin=1 adapter was not verified",
            "The generated fixed-occupation, zero-moment input is an input-check selection, not a validated material property",
            "No Slurm request, task.json, SSH transfer, submission, numerical result or production qualification was created",
        ]
    except Exception as error:
        report["checks"] = checks
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    acceptance_path = report_dir / "acceptance.json"
    acceptance_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(acceptance_path)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
