"""Explicit local crystal imports, atom lineage, and the separate Ni fixture."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as package_version
import json
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

import numpy as np
import ase
from ase import Atoms
from ase.build import bulk
from ase.io import read as ase_read
from ase.io import write as ase_write
import pymatgen.core
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.cif import CifWriter
from pymatgen.io.vasp import Poscar
from pymatgen.io.cif import CifParser


MODEL_SCHEMA = "mlcc.model.v1"
DOPANT_SCHEMA = "mlcc.dopants.v1"
ATOM_LINEAGE_SCHEMA = "mlcc.atom-lineage.v1"


def _runtime_tool_versions() -> dict[str, str]:
    """Return the actual modeling packages used for artifact generation."""

    return {
        "ase": str(ase.__version__),
        "pymatgen": str(package_version("pymatgen")),
        "pymatgen-core": str(pymatgen.core.__version__),
    }


@dataclass
class ModelArtifacts:
    """An explicit atom model and its persisted MLCC metadata."""

    model_id: str
    version: str
    atoms: Atoms
    metadata: dict[str, Any]
    artifact_dir: Path

    @property
    def atom_ids(self) -> list[int]:
        return [int(value) for value in self.atoms.arrays["atom_id"]]


def _atom_ids(atoms: Atoms) -> np.ndarray:
    """Return the required stable atom IDs, checking the model invariant."""

    if "atom_id" not in atoms.arrays:
        raise ValueError("model must carry an integer atom_id array")
    raw_ids = np.asarray(atoms.arrays["atom_id"])
    if not np.issubdtype(raw_ids.dtype, np.integer):
        raise ValueError("atom_id values must be integers")
    ids = raw_ids.astype(np.int64, copy=False)
    if len(ids) != len(atoms) or len(set(int(value) for value in ids)) != len(ids):
        raise ValueError("atom_id values must be unique and cover every atom")
    if np.any(ids < 0):
        raise ValueError("atom_id values must be non-negative")
    return ids


def _set_atom_ids(atoms: Atoms, ids: Sequence[int]) -> None:
    values = np.asarray([int(value) for value in ids], dtype=int)
    if len(values) != len(atoms):
        raise ValueError("atom_id count does not match atom count")
    if "atom_id" in atoms.arrays:
        atoms.set_array("atom_id", values)
    else:
        atoms.new_array("atom_id", values)


def _atoms_json(atoms: Atoms, ids: Sequence[int]) -> list[dict[str, Any]]:
    scaled = atoms.get_scaled_positions(wrap=False)
    cartesian = atoms.get_positions()
    return [
        {
            "atom_id": int(atom_id),
            "element": str(symbol),
            "frac_coords": [float(value) for value in scaled[index]],
            "cart_coords_angstrom": [float(value) for value in cartesian[index]],
        }
        for index, (atom_id, symbol) in enumerate(zip(ids, atoms.get_chemical_symbols()))
    ]


def _metadata_for_model(
    atoms: Atoms,
    *,
    model_id: str,
    version: str,
    fixture: bool,
    fixture_purpose: str | None,
    phase_requested: str,
    source_path: str,
    source_version: str,
    engineering_perturbation: dict[str, Any] | None,
    source_atoms: Atoms,
    material: str | None = None,
    source_format: str | None = None,
    source_reference: str | None = None,
    selection_status: str | None = None,
    material_selection_confirmed: bool | None = None,
    basis_transform: dict[str, Any] | None = None,
    atom_lineage: list[dict[str, Any]] | None = None,
    source_original_file: str | None = None,
    source_structure_file: str = "source.cif",
    scientific_status: str | None = None,
    source_index_basis: str | None = None,
    source_asymmetric_site_mapping: str | None = None,
) -> dict[str, Any]:
    ids = _atom_ids(atoms)
    source_ids = _atom_ids(source_atoms)
    if source_ids.tolist() != ids.tolist():
        raise ValueError("source and model atom IDs must be identical")
    symbols = atoms.get_chemical_symbols()
    element_order = list(dict.fromkeys(symbols))
    composition = {element: int(symbols.count(element)) for element in element_order}
    initial_magnetic_moments = (
        np.asarray(atoms.arrays["initial_magmoms"], dtype=float).tolist()
        if "initial_magmoms" in atoms.arrays
        else None
    )
    source_initial_magnetic_moments = (
        np.asarray(source_atoms.arrays["initial_magmoms"], dtype=float).tolist()
        if "initial_magmoms" in source_atoms.arrays
        else None
    )
    return {
        "schema": MODEL_SCHEMA,
        "model_id": model_id,
        "version": version,
        "fixture": bool(fixture),
        "fixture_purpose": fixture_purpose,
        "engineering_perturbation": engineering_perturbation,
        "scientific_status": scientific_status
        or ("engineering_fixture_not_production" if fixture else "model"),
        "production_qualified": False if not fixture else None,
        "material": "Ni" if fixture and material is None else material,
        "material_selection_confirmed": (
            (False if fixture else True)
            if material_selection_confirmed is None
            else bool(material_selection_confirmed)
        ),
        "selection_status": selection_status or ("engineering_fixture" if fixture else "user_selected"),
        "phase_requested": phase_requested,
        "phase_relaxed": None,
        "source_path": source_path,
        "source_format": source_format,
        "source_reference": source_reference,
        "source_version": source_version,
        "tool_versions": _runtime_tool_versions(),
        "structure_file": "model.extxyz",
        "source_structure_file": source_structure_file,
        "source_original_file": source_original_file,
        "source_index_basis": source_index_basis,
        "source_asymmetric_site_mapping": source_asymmetric_site_mapping,
        "composition": composition,
        "element_order": element_order,
        "atom_ids": [int(value) for value in ids],
        "atom_id_origin": atoms.info.get("mlcc_atom_id_origin"),
        "source_atom_id_origin": source_atoms.info.get("mlcc_atom_id_origin"),
        "atoms": _atoms_json(atoms, ids),
        "source_atoms": _atoms_json(source_atoms, source_ids),
        "lattice_angstrom": [[float(value) for value in row] for row in atoms.cell.array],
        "source_lattice_angstrom": [[float(value) for value in row] for row in source_atoms.cell.array],
        "pbc": [bool(value) for value in atoms.pbc],
        "source_pbc": [bool(value) for value in source_atoms.pbc],
        "initial_magnetic_moments_muB": initial_magnetic_moments,
        "source_initial_magnetic_moments_muB": source_initial_magnetic_moments,
        "parent_models": [],
        "dopants_file": "dopants.json",
        "dopants": [],
        "spatial_mode": "pristine",
        "random_seed": None,
        "vasp_element_order": element_order,
        "basis_transform": basis_transform
        or {
            "kind": "identity",
            "fractional_matrix": np.eye(3, dtype=int).tolist(),
            "fractional_translation": [0.0, 0.0, 0.0],
            "source_lattice_angstrom": [
                [float(value) for value in row] for row in source_atoms.cell.array
            ],
            "target_lattice_angstrom": [
                [float(value) for value in row] for row in atoms.cell.array
            ],
        },
        "atom_lineage_file": "atom-lineage.json" if atom_lineage is not None else None,
        "atom_lineage": atom_lineage,
    }


def write_model_artifacts(
    atoms: Atoms,
    output_dir: str | Path,
    *,
    model_id: str,
    version: str,
    fixture: bool,
    fixture_purpose: str | None = None,
    phase_requested: str = "user_selected_phase_pending",
    source_path: str = "mlcc-generated",
    source_version: str = "h0-v001",
    engineering_perturbation: dict[str, Any] | None = None,
    source_atoms: Atoms | None = None,
    material: str | None = None,
    source_format: str | None = None,
    source_reference: str | None = None,
    selection_status: str | None = None,
    material_selection_confirmed: bool | None = None,
    basis_transform: dict[str, Any] | None = None,
    atom_lineage: list[dict[str, Any]] | None = None,
    source_original_file: str | None = None,
    scientific_status: str | None = None,
    source_index_basis: str | None = None,
    source_asymmetric_site_mapping: str | None = None,
) -> ModelArtifacts:
    """Write the explicit model files required by the H0 data contract."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _atom_ids(atoms)
    source_structure = atoms if source_atoms is None else source_atoms
    metadata = _metadata_for_model(
        atoms,
        model_id=model_id,
        version=version,
        fixture=fixture,
        fixture_purpose=fixture_purpose,
        phase_requested=phase_requested,
        source_path=source_path,
        source_version=source_version,
        engineering_perturbation=engineering_perturbation,
        source_atoms=source_structure,
        material=material,
        source_format=source_format,
        source_reference=source_reference,
        selection_status=selection_status,
        material_selection_confirmed=material_selection_confirmed,
        basis_transform=basis_transform,
        atom_lineage=atom_lineage,
        source_original_file=source_original_file,
        scientific_status=scientific_status,
        source_index_basis=source_index_basis,
        source_asymmetric_site_mapping=source_asymmetric_site_mapping,
    )

    source_cif_structure = AseAtomsAdaptor().get_structure(source_structure)
    CifWriter(source_cif_structure).write_file(str(output / "source.cif"))
    ase_write(str(output / "model.extxyz"), atoms, format="extxyz")
    (output / "model.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    dopants = {
        "schema": DOPANT_SCHEMA,
        "model_id": model_id,
        "version": version,
        "fixture": bool(fixture),
        "fixture_purpose": fixture_purpose,
        "material": metadata["material"],
        "material_selection_confirmed": metadata["material_selection_confirmed"],
        "spatial_mode": "pristine",
        "random_seed": None,
        "dopants": [],
        "compensation": None,
    }
    (output / "dopants.json").write_text(
        json.dumps(dopants, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if atom_lineage is not None:
        (output / "atom-lineage.json").write_text(
            json.dumps(
                {
                    "schema": ATOM_LINEAGE_SCHEMA,
                    "model_id": model_id,
                    "version": version,
                    "entries": atom_lineage,
                },
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
    return ModelArtifacts(model_id, version, atoms, metadata, output)


def _source_format(source_path: Path, requested: Any) -> str:
    if requested is not None:
        value = str(requested).strip().lower()
        if value not in {"poscar", "cif", "extxyz"}:
            raise ValueError(f"unsupported structure source format: {requested}")
        return value
    if source_path.name.upper() in {"POSCAR", "CONTCAR"}:
        return "poscar"
    suffix = source_path.suffix.lower()
    if suffix == ".cif":
        return "cif"
    if suffix in {".extxyz", ".xyz"}:
        return "extxyz"
    if suffix in {".vasp", ".poscar"}:
        return "poscar"
    raise ValueError(f"cannot infer structure source format from {source_path.name}")


def _requested_index(request: Mapping[str, Any]) -> int | None:
    if "source_index" not in request or request["source_index"] is None:
        return None
    value = request["source_index"]
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError("source frame index must be an integer")
    return int(value)


def _validate_periodic_crystal(atoms: Atoms) -> None:
    if len(atoms) == 0:
        raise ValueError("structure source contains no atoms")
    if not bool(np.all(np.asarray(atoms.pbc, dtype=bool))):
        raise ValueError("structure source must be a three-dimensional periodic crystal")
    cell = np.asarray(atoms.cell.array, dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("structure source must have a finite three-dimensional cell")
    volume = float(abs(np.linalg.det(cell)))
    if volume <= 1e-10:
        raise ValueError("structure source cell must have non-zero volume")


def _validate_explicit_occupancy(structure: Any) -> None:
    for index, site in enumerate(structure.sites):
        if not bool(site.is_ordered) or len(site.species) != 1:
            raise ValueError(f"fractional occupancy or mixed occupancy is not supported at CIF site {index}")
        occupancy = float(next(iter(site.species.values())))
        if not np.isclose(occupancy, 1.0, rtol=0.0, atol=1e-12):
            raise ValueError(f"fractional occupancy is not supported at CIF site {index}")


def _read_import_source(
    source_path: Path,
    source_format: str,
    source_index: int | None,
) -> tuple[Atoms, str]:
    """Read one explicit source frame without online lookup or last-frame fallback."""

    if source_format == "cif":
        parser = CifParser(str(source_path))
        block_count = len(parser.as_dict())
        structures = parser.parse_structures(primitive=False, on_error="raise")
        if len(structures) != block_count:
            raise ValueError(
                "CIF structure block count does not match parsed structure count: "
                f"{block_count} blocks, {len(structures)} structures"
            )
        if len(structures) != 1 and source_index is None:
            raise ValueError("CIF contains multiple structure blocks; source_index is required")
        index = 0 if source_index is None else source_index
        if not 0 <= index < len(structures):
            raise ValueError(f"source_index {index} is outside CIF structure blocks")
        structure = structures[index]
        _validate_explicit_occupancy(structure)
        atoms = AseAtomsAdaptor().get_atoms(structure)
        return atoms, f"cif_block_{index}"
    if source_format == "poscar":
        if source_index not in (None, 0):
            raise ValueError("POSCAR has one structure; source_index must be 0")
        structure = Poscar.from_file(str(source_path), check_for_potcar=False).structure
        atoms = AseAtomsAdaptor().get_atoms(structure)
        return atoms, "poscar"
    if source_format == "extxyz":
        frames = ase_read(str(source_path), format="extxyz", index=":")
        if isinstance(frames, Atoms):
            frames = [frames]
        if not isinstance(frames, list):
            frames = list(frames)
        if len(frames) != 1 and source_index is None:
            raise ValueError("extxyz contains multiple frames; source_index is required")
        index = 0 if source_index is None else source_index
        if not 0 <= index < len(frames):
            raise ValueError(f"source_index {index} is outside extxyz frames")
        atoms = frames[index]
        if "atom_id" in atoms.arrays:
            raw_ids = np.asarray(atoms.arrays["atom_id"])
            if not np.issubdtype(raw_ids.dtype, np.integer):
                raise ValueError("extxyz atom_id values must be integers")
            ids = raw_ids.astype(np.int64, copy=False)
            if len(set(int(value) for value in ids)) != len(ids) or np.any(ids < 0):
                raise ValueError("extxyz atom_id values must be unique non-negative integers")
            atom_id_origin = "source_extxyz"
        else:
            _set_atom_ids(atoms, range(len(atoms)))
            atom_id_origin = "assigned_source_order"
        atoms.info["mlcc_atom_id_origin"] = atom_id_origin
        return atoms, f"extxyz_frame_{index}"
    raise ValueError(f"unsupported structure source format: {source_format}")


def _identity_transform(atoms: Atoms) -> dict[str, Any]:
    lattice = [[float(value) for value in row] for row in atoms.cell.array]
    return {
        "kind": "identity",
        "fractional_matrix": np.eye(3, dtype=int).tolist(),
        "fractional_translation": [0.0, 0.0, 0.0],
        "axis_reference": "source setting retained",
        "source_lattice_angstrom": lattice,
        "target_lattice_angstrom": lattice,
        "rotation_cartesian": np.eye(3).tolist(),
        "determinant_rotation": 1.0,
    }


def _apply_basis_transform(
    source_atoms: Atoms,
    transform: Mapping[str, Any] | None,
) -> tuple[Atoms, dict[str, Any], list[dict[str, Any]]]:
    source = source_atoms.copy()
    _validate_periodic_crystal(source)
    source_ids = _atom_ids(source).tolist()
    source_symbols = source.get_chemical_symbols()
    if transform is None:
        identity = _identity_transform(source)
        lineage = [
            {
                "source_index": index,
                "source_atom_id": int(atom_id),
                "working_index": index,
                "working_atom_id": int(atom_id),
                "element": str(symbol),
                "source_frac_coords": [float(value) for value in source.get_scaled_positions(wrap=False)[index]],
                "working_frac_coords": [float(value) for value in source.get_scaled_positions(wrap=False)[index]],
                "periodic_shift": [0, 0, 0],
            }
            for index, (atom_id, symbol) in enumerate(zip(source_ids, source_symbols))
        ]
        return source, identity, lineage

    if not isinstance(transform, Mapping):
        raise ValueError("basis transform must be a JSON object")
    matrix_value = transform.get("fractional_matrix")
    translation_value = transform.get("fractional_translation")
    target_lattice_value = transform.get("target_lattice_angstrom")
    if matrix_value is None or translation_value is None or target_lattice_value is None:
        raise ValueError("basis transform requires fractional_matrix, fractional_translation and target_lattice_angstrom")
    matrix = np.asarray(matrix_value, dtype=float)
    translation = np.asarray(translation_value, dtype=float)
    target_lattice = np.asarray(target_lattice_value, dtype=float)
    axis_reference = transform.get("axis_reference")
    if not isinstance(axis_reference, str) or not axis_reference.strip():
        raise ValueError("basis transform requires an explicit axis_reference")
    if matrix.shape != (3, 3) or translation.shape != (3,) or target_lattice.shape != (3, 3):
        raise ValueError("basis transform has invalid matrix, translation or target lattice shape")
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(translation)) or not np.all(np.isfinite(target_lattice)):
        raise ValueError("basis transform contains non-finite values")
    integer_matrix = np.rint(matrix)
    if not np.allclose(matrix, integer_matrix, rtol=0.0, atol=1e-12):
        raise ValueError("basis transform fractional_matrix must be an integer unimodular matrix")
    matrix = integer_matrix.astype(np.int64)
    matrix_det = int(round(np.linalg.det(matrix)))
    if abs(matrix_det) != 1:
        raise ValueError("basis transform fractional_matrix must be an integer unimodular matrix")
    source_lattice = np.asarray(source.cell.array, dtype=float)
    source_volume = float(abs(np.linalg.det(source_lattice)))
    target_volume = float(abs(np.linalg.det(target_lattice)))
    if target_volume <= 1e-10 or not np.isclose(source_volume, target_volume, rtol=1e-8, atol=1e-8):
        raise ValueError("basis transform must preserve the source cell volume")
    rotation = np.linalg.inv(source_lattice) @ matrix.T @ target_lattice
    if not np.allclose(rotation.T @ rotation, np.eye(3), rtol=0.0, atol=1e-7):
        raise ValueError("basis transform is not a Cartesian orthogonal setting transform")
    rotation_det = float(np.linalg.det(rotation))
    if rotation_det <= 0.0:
        raise ValueError("basis transform must preserve a right-handed cell")
    vector_arrays = [
        name
        for name in ("initial_magmoms", "momenta")
        if name in source.arrays
        and np.asarray(source.arrays[name]).ndim >= 2
        and np.asarray(source.arrays[name]).shape[-1] == 3
    ]
    if vector_arrays and not np.allclose(rotation, np.eye(3), rtol=0.0, atol=1e-7):
        names = ", ".join(vector_arrays)
        raise ValueError(
            f"basis transform with Cartesian rotation does not support vector arrays: {names}"
        )

    source_frac = source.get_scaled_positions(wrap=False)
    transformed_unwrapped = np.asarray([matrix @ values + translation for values in source_frac], dtype=float)
    transformed = transformed_unwrapped - np.floor(transformed_unwrapped)
    working = source.copy()
    working.set_cell(target_lattice, scale_atoms=False)
    working.set_scaled_positions(transformed)
    _set_atom_ids(working, source_ids)
    if working.get_chemical_symbols() != source_symbols:
        raise ValueError("basis transform changed element order")

    # Compare all atom displacements to atom 0 in Cartesian space.  The
    # comparison uses unwrapped fractional coordinates so periodic reductions
    # cannot hide a bad mapping.
    expected = (source_frac - source_frac[0]) @ source_lattice @ rotation
    actual = (transformed_unwrapped - transformed_unwrapped[0]) @ target_lattice
    if not np.allclose(actual, expected, rtol=0.0, atol=1e-7):
        raise ValueError("basis transform does not preserve periodic atom mapping")

    lineage: list[dict[str, Any]] = []
    for index, (atom_id, symbol) in enumerate(zip(source_ids, source_symbols)):
        shift = np.rint(transformed_unwrapped[index] - transformed[index]).astype(int)
        lineage.append(
            {
                "source_index": index,
                "source_atom_id": int(atom_id),
                "working_index": index,
                "working_atom_id": int(atom_id),
                "element": str(symbol),
                "source_frac_coords": [float(value) for value in source_frac[index]],
                "working_frac_coords": [float(value) for value in transformed[index]],
                "working_frac_coords_unwrapped": [float(value) for value in transformed_unwrapped[index]],
                "periodic_shift": [int(value) for value in shift],
            }
        )
    record = {
        "kind": str(transform.get("kind", "equivalent_setting")),
        "fractional_matrix": matrix.tolist(),
        "fractional_translation": translation.tolist(),
        "axis_reference": axis_reference,
        "source_lattice_angstrom": source_lattice.tolist(),
        "target_lattice_angstrom": target_lattice.tolist(),
        "rotation_cartesian": rotation.tolist(),
        "determinant_rotation": rotation_det,
    }
    return working, record, lineage


def import_model_artifacts(request: Mapping[str, Any], output_dir: str | Path) -> ModelArtifacts:
    """Import one explicit local crystal structure into the MLCC model contract.

    This is deliberately a local, parent-model operation.  It does not query a
    structure database, select a phase, generate dopants, create a supercell,
    relax atoms, or submit a numerical task.  The request must identify the
    selected phase and the exact source file.
    """

    if not isinstance(request, Mapping):
        raise ValueError("model import request must be a JSON object")
    source_value = request.get("source_path")
    source_reference = request.get("source_reference")
    model_id = request.get("model_id")
    version = request.get("version")
    material = request.get("material")
    phase_requested = request.get("phase_requested")
    if not isinstance(source_value, str) or not source_value.strip():
        raise ValueError("model import requires source_path")
    if not isinstance(source_reference, str) or not source_reference.strip():
        raise ValueError("model import requires source_reference")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("model import requires model_id")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("model import requires version")
    if not isinstance(material, str) or not material.strip():
        raise ValueError("model import requires material")
    if not isinstance(phase_requested, str) or not phase_requested.strip():
        raise ValueError("model import requires an explicitly selected phase_requested")
    fixture_value = request.get("fixture", False)
    if not isinstance(fixture_value, bool):
        raise ValueError("fixture must be a boolean")
    fixture = fixture_value
    fixture_purpose = request.get("fixture_purpose")
    if fixture and (not isinstance(fixture_purpose, str) or not fixture_purpose.strip()):
        raise ValueError("fixture model import requires fixture_purpose")

    source_path = Path(source_value)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"model import output directory already exists: {output}")

    source_format = _source_format(source_path, request.get("source_format"))
    source_index = _requested_index(request)
    source_atoms, source_block = _read_import_source(source_path, source_format, source_index)
    if source_format != "extxyz" or "atom_id" not in source_atoms.arrays:
        _set_atom_ids(source_atoms, range(len(source_atoms)))
        source_atoms.info["mlcc_atom_id_origin"] = "assigned_source_order"
    _validate_periodic_crystal(source_atoms)
    transform_request = request.get("basis_transform")
    if transform_request is not None and not isinstance(transform_request, Mapping):
        raise ValueError("basis transform must be a JSON object")
    working_atoms, transform_record, lineage = _apply_basis_transform(
        source_atoms,
        transform_request,
    )

    source_suffix = source_path.suffix.lower().lstrip(".") or source_format
    original_name = f"source.original.{source_suffix}"
    source_version = str(request.get("source_version", "unspecified"))
    selection_status = str(
        request.get("selection_status", "engineering_fixture" if fixture else "user_selected")
    )
    material_selection_confirmed_value = request.get("material_selection_confirmed", not fixture)
    if not isinstance(material_selection_confirmed_value, bool):
        raise ValueError("material_selection_confirmed must be a boolean")
    material_selection_confirmed = material_selection_confirmed_value
    metadata_source_path = str(source_path)
    result = write_model_artifacts(
        working_atoms,
        output,
        model_id=model_id,
        version=version,
        fixture=fixture,
        fixture_purpose=fixture_purpose,
        phase_requested=phase_requested,
        source_path=metadata_source_path,
        source_version=source_version,
        source_atoms=source_atoms,
        material=material,
        source_format=source_format,
        source_reference=source_reference,
        selection_status=selection_status,
        material_selection_confirmed=material_selection_confirmed,
        basis_transform=transform_record,
        atom_lineage=lineage,
        source_original_file=original_name,
        scientific_status="engineering_fixture_not_production" if fixture else "source_reference_unrelaxed",
        source_index_basis=(
            "full_expanded_structure_order" if source_format == "cif" else "source_atom_order"
        ),
        source_asymmetric_site_mapping=(
            "not_one_to_one_for_cif_asymmetric_sites" if source_format == "cif" else None
        ),
    )
    ase_write(str(output / "source.extxyz"), source_atoms, format="extxyz")
    shutil.copyfile(source_path, output / original_name)
    metadata = dict(result.metadata)
    metadata.update(
        {
            "source_block": source_block,
            "source_index": 0 if source_index is None else source_index,
            "relaxation_status": "not_run",
            "production_qualified": False,
        }
    )
    (output / "model.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lineage_path = output / "atom-lineage.json"
    lineage_record = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage_record.update(
        {
            "source_index_basis": metadata["source_index_basis"],
            "source_structure_file": "source.extxyz",
            "source_asymmetric_site_mapping": metadata["source_asymmetric_site_mapping"],
        }
    )
    lineage_path.write_text(
        json.dumps(lineage_record, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    result.metadata = metadata
    return result


def build_nickel_fcc_fixture(
    output_dir: str | Path,
    *,
    model_id: str = "ni-fcc-engineering",
    version: str = "v001",
    lattice_constant_angstrom: float = 3.52,
    repeat: tuple[int, int, int] = (1, 1, 1),
    displaced_atom_id: int | None = None,
    displacement_angstrom: float = 0.0,
) -> ModelArtifacts:
    """Build and persist a conventional-cell Ni fcc connection-test fixture.

    The conventional cubic cell is used intentionally: it has four explicit Ni
    atoms and makes the element/atom ordering visible in a VASP round trip.
    The result is an engineering fixture and carries no production phase or
    dopant selection.
    """

    atoms = bulk("Ni", crystalstructure="fcc", a=float(lattice_constant_angstrom), cubic=True)
    atoms = atoms.repeat(tuple(int(value) for value in repeat))
    _set_atom_ids(atoms, range(len(atoms)))
    source_atoms = atoms.copy()
    perturbation = None
    if displaced_atom_id is not None:
        if not 0 <= int(displaced_atom_id) < len(atoms):
            raise ValueError("displaced_atom_id is outside the fixture atom IDs")
        atoms.positions[int(displaced_atom_id), 0] += float(displacement_angstrom)
        perturbation = {
            "kind": "engineering_displacement",
            "atom_id": int(displaced_atom_id),
            "vector_angstrom": [float(displacement_angstrom), 0.0, 0.0],
        }
    elif float(displacement_angstrom) != 0.0:
        raise ValueError("displacement_angstrom requires displaced_atom_id")
    atoms.info["mlcc_fixture"] = True
    atoms.info["fixture_purpose"] = "connection_test"
    versions = _runtime_tool_versions()
    return write_model_artifacts(
        atoms,
        output_dir,
        model_id=model_id,
        version=version,
        fixture=True,
        fixture_purpose="connection_test",
        phase_requested="fcc_engineering_fixture",
        source_path="ase.build.bulk(Ni, fcc, cubic=True)",
        source_version=(
            f"ASE {versions['ase']}; "
            f"pymatgen {versions['pymatgen']}; "
            f"pymatgen-core {versions['pymatgen-core']}"
        ),
        engineering_perturbation=perturbation,
        source_atoms=source_atoms,
        material="Ni",
    )


def read_model_artifacts(model_dir: str | Path) -> ModelArtifacts:
    """Read the H0 model files and restore the recorded atom IDs."""

    directory = Path(model_dir)
    metadata = json.loads((directory / "model.json").read_text(encoding="utf-8"))
    atoms = ase_read(str(directory / metadata["structure_file"]), format="extxyz", index=0)
    ids = [int(value) for value in metadata["atom_ids"]]
    if len(ids) != len(atoms):
        raise ValueError("model.json atom_ids count does not match model.extxyz")
    existing_ids = _atom_ids(atoms).tolist()
    if existing_ids != ids:
        raise ValueError("model.extxyz atom_id values differ from model.json")
    if [str(value) for value in atoms.get_chemical_symbols()] != [
        str(item["element"]) for item in metadata["atoms"]
    ]:
        raise ValueError("model.extxyz atom order differs from model.json")
    metadata_composition = {str(key): int(value) for key, value in metadata["composition"].items()}
    symbols = atoms.get_chemical_symbols()
    composition = {element: int(symbols.count(element)) for element in dict.fromkeys(symbols)}
    if composition != metadata_composition:
        raise ValueError("model.extxyz composition differs from model.json")
    if not np.allclose(atoms.cell.array, np.asarray(metadata["lattice_angstrom"], dtype=float), atol=1e-8, rtol=0.0):
        raise ValueError("model.extxyz lattice differs from model.json")
    expected_positions = np.asarray(
        [item["cart_coords_angstrom"] for item in metadata["atoms"]], dtype=float
    )
    if not np.allclose(atoms.get_positions(), expected_positions, atol=1e-8, rtol=0.0):
        raise ValueError("model.extxyz coordinates differ from model.json")
    if [bool(value) for value in atoms.pbc] != [bool(value) for value in metadata["pbc"]]:
        raise ValueError("model.extxyz periodic boundary flags differ from model.json")
    return ModelArtifacts(
        model_id=str(metadata["model_id"]),
        version=str(metadata["version"]),
        atoms=atoms,
        metadata=metadata,
        artifact_dir=directory,
    )


def model_structure(atoms: Atoms):
    """Return the pymatgen Structure corresponding to an explicit ASE model."""

    _atom_ids(atoms)
    return AseAtomsAdaptor().get_structure(atoms)

