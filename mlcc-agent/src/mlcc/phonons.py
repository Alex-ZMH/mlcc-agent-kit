"""Explicit Phonopy displacement plans and harmonic software calculations.

This module stops at structure planning and a source-bound harmonic calculation.
It does not create an ABACUS task, submit a job, or qualify a material result.
The plan stores ASE/Phonopy structures in Angstrom and preserves the MLCC atom
lineage needed by a later native-force adapter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from ase import Atoms
from ase.io import read as ase_read
from ase.io import write as ase_write
import phonopy
from phonopy import Phonopy
from phonopy.physical_units import get_physical_units
from phonopy.structure.atoms import PhonopyAtoms

from .modeling import ModelArtifacts, read_model_artifacts


PLAN_SCHEMA = "mlcc.phonon-displacement-plan.v1"
HARMONIC_SCHEMA = "mlcc.phonon-harmonic-result.v1"
FORCE_UNIT = "eV/angstrom"
FORCE_CONSTANT_UNIT = "eV/angstrom^2"
DISTANCE_UNIT = "angstrom"
GEOMETRY_ATOL_ANGSTROM = 1e-7
MASS_ATOL_AMU = 1e-8
MAGMOM_ATOL = 1e-8


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _required_bool(request: Mapping[str, Any], name: str) -> bool:
    if name not in request or not isinstance(request[name], bool):
        raise ValueError(f"{name} must be an explicit boolean")
    return bool(request[name])


def _integer_matrix(value: Any, name: str) -> np.ndarray:
    matrix = np.asarray(value)
    if matrix.shape != (3, 3) or matrix.dtype.kind == "b" or not np.issubdtype(matrix.dtype, np.number):
        raise ValueError(f"{name} must be a 3x3 integer matrix")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must contain finite values")
    rounded = np.rint(matrix)
    if not np.allclose(matrix, rounded, rtol=0.0, atol=1e-12):
        raise ValueError(f"{name} must be a 3x3 integer matrix")
    return rounded.astype(np.int64)


def _primitive_matrix(value: Any) -> np.ndarray:
    if value is None or isinstance(value, str):
        raise ValueError("primitive_matrix must be an explicit 3x3 matrix")
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError("primitive_matrix must be an explicit finite 3x3 matrix")
    if abs(float(np.linalg.det(matrix))) <= 1e-12:
        raise ValueError("primitive_matrix must have a non-zero determinant")
    return matrix


def _positive_float(request: Mapping[str, Any], name: str) -> float:
    if name not in request:
        raise ValueError(f"{name} must be explicit")
    value = request[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be a positive finite number")
    result = float(value)
    if not np.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def _model_charge_state(metadata: Mapping[str, Any]) -> int:
    derivation = metadata.get("derivation")
    if isinstance(derivation, Mapping) and "charge_state" in derivation:
        value = derivation["charge_state"]
    elif "charge_state" in metadata:
        value = metadata.get("charge_state", 0)
    else:
        return 0
    if value is None:
        raise ValueError("explicit model charge_state cannot be null")
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError("model charge_state must be an explicit integer")
    return int(value)


def _validate_parent_model(parent: ModelArtifacts) -> None:
    if _model_charge_state(parent.metadata) != 0:
        raise ValueError("charged models are not supported by the phonon displacement plan")
    if parent.atoms.constraints:
        raise ValueError("constrained models are not supported by the phonon displacement plan")
    if not bool(np.all(np.asarray(parent.atoms.pbc, dtype=bool))):
        raise ValueError("phonon displacement planning requires a three-dimensional periodic model")
    cell = np.asarray(parent.atoms.cell.array, dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)) or abs(float(np.linalg.det(cell))) <= 1e-12:
        raise ValueError("phonon displacement planning requires a finite non-zero cell")


def _initial_magnetic_moments(atoms: Atoms) -> np.ndarray | None:
    if "initial_magmoms" not in atoms.arrays:
        return None
    values = np.asarray(atoms.arrays["initial_magmoms"], dtype=float)
    if values.shape[0] != len(atoms) or not np.all(np.isfinite(values)):
        raise ValueError("initial_magmoms must have one finite value per atom")
    return values.copy()


def _phonopy_unitcell(atoms: Atoms) -> PhonopyAtoms:
    magmoms = _initial_magnetic_moments(atoms)
    return PhonopyAtoms(
        symbols=atoms.get_chemical_symbols(),
        scaled_positions=atoms.get_scaled_positions(wrap=False),
        cell=np.asarray(atoms.cell.array, dtype=float),
        masses=np.asarray(atoms.get_masses(), dtype=float),
        magnetic_moments=None if magmoms is None else magmoms,
    )


def _phonopy_to_ase(atoms: PhonopyAtoms, atom_ids: Sequence[int], magmoms: np.ndarray | None = None) -> Atoms:
    ids = [int(value) for value in atom_ids]
    if len(ids) != len(atoms) or len(set(ids)) != len(ids):
        raise ValueError("generated structure atom IDs must be unique and cover every atom")
    result = Atoms(
        numbers=np.asarray(atoms.numbers, dtype=int),
        positions=np.asarray(atoms.positions, dtype=float),
        cell=np.asarray(atoms.cell, dtype=float),
        pbc=True,
    )
    result.set_masses(np.asarray(atoms.masses, dtype=float))
    result.new_array("atom_id", np.asarray(ids, dtype=np.int64))
    source_magmoms = atoms.magnetic_moments if magmoms is None else magmoms
    if source_magmoms is not None:
        result.new_array("initial_magmoms", np.asarray(source_magmoms, dtype=float))
    return result


def _same_periodic_geometry(actual: Atoms, expected: Atoms) -> bool:
    """Compare ordered atoms modulo integer translations of the same cell."""

    if len(actual) != len(expected):
        return False
    if actual.get_chemical_symbols() != expected.get_chemical_symbols():
        return False
    if [bool(value) for value in actual.pbc] != [bool(value) for value in expected.pbc]:
        return False
    if not np.allclose(actual.cell.array, expected.cell.array, rtol=0.0, atol=GEOMETRY_ATOL_ANGSTROM):
        return False
    inverse_cell = np.linalg.inv(np.asarray(expected.cell.array, dtype=float))
    delta_frac = (np.asarray(actual.positions) - np.asarray(expected.positions)) @ inverse_cell
    delta_frac -= np.rint(delta_frac)
    delta_cart = delta_frac @ np.asarray(expected.cell.array, dtype=float)
    return bool(np.allclose(delta_cart, 0.0, rtol=0.0, atol=GEOMETRY_ATOL_ANGSTROM))


def _same_atom_ids(actual: Atoms, expected_ids: Sequence[int]) -> bool:
    return "atom_id" in actual.arrays and actual.arrays["atom_id"].astype(int).tolist() == [int(value) for value in expected_ids]


def _same_masses(actual: Atoms, expected: Sequence[float]) -> bool:
    return bool(
        len(actual) == len(expected)
        and np.allclose(actual.get_masses(), np.asarray(expected, dtype=float), rtol=0.0, atol=MASS_ATOL_AMU)
    )


def _same_magmoms(actual: Atoms, expected: Any) -> bool:
    if expected is None:
        return "initial_magmoms" not in actual.arrays
    if "initial_magmoms" not in actual.arrays:
        return False
    values = np.asarray(actual.arrays["initial_magmoms"], dtype=float)
    expected_values = np.asarray(expected, dtype=float)
    return bool(values.shape == expected_values.shape and np.allclose(values, expected_values, rtol=0.0, atol=MAGMOM_ATOL))


def _lineage_for_supercell(phonon: Phonopy, parent: ModelArtifacts) -> list[dict[str, Any]]:
    supercell = phonon.supercell
    parent_atoms = parent.atoms
    parent_cell = np.asarray(parent_atoms.cell.array, dtype=float)
    parent_frac = np.asarray(parent_atoms.get_scaled_positions(wrap=False), dtype=float)
    parent_ids = parent.atom_ids
    parent_symbols = parent_atoms.get_chemical_symbols()
    inverse_parent_cell = np.linalg.inv(parent_cell)
    s2u_map = np.asarray(supercell.s2u_map, dtype=int)
    u2u_map = {int(key): int(value) for key, value in supercell.u2u_map.items()}
    if len(s2u_map) != len(supercell):
        raise ValueError("Phonopy supercell atom mapping has the wrong length")

    lineage: list[dict[str, Any]] = []
    for child_index, (symbol, position) in enumerate(zip(supercell.symbols, supercell.positions)):
        raw_unit_index = int(s2u_map[child_index])
        if raw_unit_index not in u2u_map:
            raise ValueError("Phonopy supercell mapping does not identify a parent atom")
        parent_index = u2u_map[raw_unit_index]
        if not 0 <= parent_index < len(parent_atoms):
            raise ValueError("Phonopy supercell mapping has an invalid parent index")
        if str(symbol) != str(parent_symbols[parent_index]):
            raise ValueError("Phonopy supercell mapping changed an atom element")
        unwrapped_frac = np.asarray(position, dtype=float) @ inverse_parent_cell
        image_float = unwrapped_frac - parent_frac[parent_index]
        image = np.rint(image_float)
        if not np.allclose(image_float, image, rtol=0.0, atol=1e-8):
            raise ValueError("Phonopy supercell atom does not map to an integer parent image")
        lineage.append(
            {
                "child_atom_id": int(child_index),
                "parent_atom_id": int(parent_ids[parent_index]),
                "parent_image": [int(value) for value in image],
                "parent_frac_coords": [float(value) for value in parent_frac[parent_index]],
                "element": str(symbol),
                "kind": "supercell_replica",
            }
        )
    return lineage


def _phonopy_request(request: Mapping[str, Any]) -> dict[str, Any]:
    phonopy_version = _non_empty_string(request.get("phonopy_version"), "phonopy_version")
    if phonopy_version != str(phonopy.__version__):
        raise ValueError(
            f"phonopy_version {phonopy_version!r} does not match installed {phonopy.__version__!r}"
        )
    repeat_matrix = _integer_matrix(request.get("repeat_matrix"), "repeat_matrix")
    determinant = int(round(float(np.linalg.det(repeat_matrix))))
    if determinant <= 0:
        raise ValueError("repeat_matrix must be right-handed with positive determinant")
    primitive_matrix = _primitive_matrix(request.get("primitive_matrix"))
    distance = _positive_float(request, "distance_angstrom")
    symprec = _positive_float(request, "symprec")
    is_symmetry = _required_bool(request, "is_symmetry")
    hermitianize = _required_bool(request, "hermitianize_dynamical_matrix")
    fixed_values = {
        "is_plusminus": True,
        "is_diagonal": False,
        "is_trigonal": False,
        "calculator": None,
        "calculator_units": "eV/angstrom/amu",
        "lang": "Rust",
    }
    for key, expected in fixed_values.items():
        if key in request and request[key] != expected:
            raise ValueError(f"{key} is fixed to {expected!r} for this phonon plan")
    if "supercell_matrix" in request:
        supplied_supercell = np.asarray(request["supercell_matrix"])
        if (
            supplied_supercell.shape != (3, 3)
            or not np.issubdtype(supplied_supercell.dtype, np.number)
            or not np.all(np.isfinite(supplied_supercell))
            or not np.allclose(supplied_supercell, repeat_matrix.T, rtol=0.0, atol=1e-12)
        ):
            raise ValueError("supercell_matrix conflicts with repeat_matrix.T")
    return {
        "phonopy_version": phonopy_version,
        "repeat_matrix": repeat_matrix.tolist(),
        "supercell_matrix": repeat_matrix.T.tolist(),
        "primitive_matrix": primitive_matrix.tolist(),
        "primitive_matrix_convention": "phonopy_native_column_transform",
        "distance_angstrom": distance,
        "distance_unit": DISTANCE_UNIT,
        "symprec": symprec,
        "is_symmetry": is_symmetry,
        "is_plusminus": True,
        "is_diagonal": False,
        "is_trigonal": False,
        "hermitianize_dynamical_matrix": hermitianize,
        "calculator": None,
        "calculator_units": "eV/angstrom/amu",
        "lang": "Rust",
    }


def _build_phonopy(parent_atoms: Atoms, phonopy_request: Mapping[str, Any]) -> Phonopy:
    repeat_matrix = np.asarray(phonopy_request["repeat_matrix"], dtype=int)
    primitive_matrix = np.asarray(phonopy_request["primitive_matrix"], dtype=float)
    unitcell = _phonopy_unitcell(parent_atoms)
    phonon = Phonopy(
        unitcell,
        supercell_matrix=repeat_matrix.T,
        primitive_matrix=primitive_matrix,
        symprec=float(phonopy_request["symprec"]),
        is_symmetry=bool(phonopy_request["is_symmetry"]),
        hermitianize_dynamical_matrix=bool(phonopy_request["hermitianize_dynamical_matrix"]),
        calculator=None,
        lang=str(phonopy_request["lang"]),
    )
    phonon.generate_displacements(
        distance=float(phonopy_request["distance_angstrom"]),
        is_plusminus=True,
        is_diagonal=False,
        is_trigonal=False,
    )
    return phonon


def _displacement_sign(vector: np.ndarray) -> str:
    index = int(np.argmax(np.abs(vector)))
    return "plus" if float(vector[index]) > 0 else "minus"


def _require_explicit_pairs(displacements: Sequence[Sequence[Any]]) -> None:
    keys: set[tuple[int, tuple[float, float, float]]] = set()
    for item in displacements:
        number = int(item[0])
        vector = np.asarray(item[1:4], dtype=float)
        key = (number, tuple(float(value) for value in np.round(vector, 12)))
        keys.add(key)
    for number, vector in keys:
        opposite = tuple(float(value) for value in np.round(-np.asarray(vector), 12))
        if (number, opposite) not in keys:
            raise ValueError("Phonopy did not produce an explicit plus/minus pair")


def _manifest_path(path: str | Path) -> Path:
    manifest = Path(path)
    if not manifest.is_file():
        raise FileNotFoundError(f"phonon displacement manifest not found: {manifest}")
    return manifest


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def generate_phonon_displacement_plan(
    parent_model_path: str | Path,
    request: Mapping[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    """Generate a fixed-cell explicit plus/minus displacement plan.

    ``repeat_matrix`` uses the MLCC/ASE row-cell convention.  Phonopy 4.8.3
    receives ``M = repeat_matrix.T``; its row-vector cell rule is
    ``cell_super = M.T @ cell_parent``, which therefore gives the MLCC rule
    ``repeat_matrix @ cell_parent``.  All structures and displacement vectors
    remain in Angstrom.
    """

    if not isinstance(request, Mapping):
        raise ValueError("phonon displacement request must be a JSON object")
    plan_id = _non_empty_string(request.get("plan_id"), "plan_id")
    version = _non_empty_string(request.get("version"), "version")
    parent = read_model_artifacts(parent_model_path)
    _validate_parent_model(parent)
    if plan_id == parent.model_id:
        raise ValueError("plan_id must identify a plan and cannot reuse the model_id")
    phonopy_request = _phonopy_request(request)
    phonon = _build_phonopy(parent.atoms, phonopy_request)
    displacements = phonon.displacements
    supercells = phonon.supercells_with_displacements
    if not displacements or supercells is None or len(displacements) != len(supercells):
        raise ValueError("Phonopy returned no aligned displacement structures")
    _require_explicit_pairs(displacements)

    lineage = _lineage_for_supercell(phonon, parent)
    child_atom_ids = [int(index) for index in range(len(phonon.supercell))]
    reference_ase = _phonopy_to_ase(phonon.supercell, child_atom_ids)
    parent_ase = parent.atoms.copy()
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"phonon displacement plan output already exists: {output}")
    structure_dir = output / "structures"
    structure_dir.mkdir(parents=True)
    parent_structure_file = "structures/parent-unitcell.extxyz"
    reference_structure_file = "structures/reference.extxyz"
    ase_write(str(output / parent_structure_file), parent_ase, format="extxyz")
    ase_write(str(output / reference_structure_file), reference_ase, format="extxyz")

    entries: list[dict[str, Any]] = []
    for index, (displacement, supercell) in enumerate(zip(displacements, supercells)):
        vector = np.asarray(displacement[1:4], dtype=float)
        displaced_atom_index = int(displacement[0])
        entry_id = f"disp-{index + 1:06d}"
        child = _phonopy_to_ase(supercell, child_atom_ids)
        structure_file = f"structures/{entry_id}.extxyz"
        ase_write(str(output / structure_file), child, format="extxyz")
        entries.append(
            {
                "entry_id": entry_id,
                "kind": "displacement",
                "displacement_index": int(index),
                "sign": _displacement_sign(vector),
                "phonopy_atom_index": displaced_atom_index,
                "displaced_atom_id": int(child_atom_ids[displaced_atom_index]),
                "displacement_angstrom": [float(value) for value in vector],
                "structure_file": structure_file,
                "atom_ids": child_atom_ids,
                "atom_lineage": lineage,
                "masses": [float(value) for value in child.get_masses()],
                "initial_magmoms": (
                    None
                    if "initial_magmoms" not in child.arrays
                    else np.asarray(child.arrays["initial_magmoms"], dtype=float).tolist()
                ),
            }
        )

    reference = {
        "entry_id": "reference",
        "kind": "reference",
        "structure_file": reference_structure_file,
        "atom_ids": child_atom_ids,
        "atom_lineage": lineage,
        "masses": [float(value) for value in reference_ase.get_masses()],
        "initial_magmoms": (
            None
            if "initial_magmoms" not in reference_ase.arrays
            else np.asarray(reference_ase.arrays["initial_magmoms"], dtype=float).tolist()
        ),
    }
    manifest: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "plan_id": plan_id,
        "version": version,
        "scientific_status": "software_displacement_plan_only",
        "production_qualified": False,
        "scientific_qualification": False,
        "parent_structure_file": parent_structure_file,
        "source_model": {
            "model_id": parent.model_id,
            "version": parent.version,
            "path": str(parent.artifact_dir.resolve()),
            "material": parent.metadata.get("material"),
            "phase_requested": parent.metadata.get("phase_requested"),
        },
        "coordinate_convention": {
            "cell_storage": "row_vectors_angstrom",
            "phonopy_cell_storage": "row_vectors_angstrom",
            "mlcc_repeat_matrix": "row_cell_transform",
            "phonopy_supercell_matrix": "repeat_matrix_transpose",
            "displacement_unit": DISTANCE_UNIT,
        },
        "request": phonopy_request,
        "primitive_cell_angstrom": np.asarray(phonon.primitive.cell, dtype=float).tolist(),
        "q_point_coordinate_basis": "primitive_reciprocal_fractional",
        "reference": reference,
        "displacements": entries,
    }
    _write_json(output / "displacement-manifest.json", manifest)
    return manifest


def load_phonon_displacement_plan(manifest_path: str | Path) -> dict[str, Any]:
    """Load a plan and verify its parent snapshot and every generated structure."""

    path = _manifest_path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"unsupported phonon displacement plan schema: {manifest.get('schema')!r}")
    _non_empty_string(manifest.get("plan_id"), "plan_id")
    _non_empty_string(manifest.get("version"), "version")
    source_model = manifest.get("source_model")
    if not isinstance(source_model, Mapping):
        raise ValueError("phonon displacement plan requires source_model")
    source_model_id = _non_empty_string(source_model.get("model_id"), "source_model.model_id")
    source_model_version = _non_empty_string(source_model.get("version"), "source_model.version")
    source_model_path = Path(_non_empty_string(source_model.get("path"), "source_model.path"))
    if manifest.get("scientific_status") != "software_displacement_plan_only":
        raise ValueError("phonon displacement plans cannot claim a scientific result")
    if manifest.get("production_qualified") is not False or manifest.get("scientific_qualification") is not False:
        raise ValueError("phonon displacement plans cannot claim production or scientific qualification")
    request = manifest.get("request")
    if not isinstance(request, Mapping):
        raise ValueError("phonon displacement plan requires request")
    canonical_request = _phonopy_request(request)
    if dict(request) != canonical_request:
        raise ValueError("saved phonopy request differs from its canonical explicit configuration")
    if manifest.get("q_point_coordinate_basis") != "primitive_reciprocal_fractional":
        raise ValueError("phonon displacement plan must declare primitive reciprocal fractional q points")
    if manifest.get("coordinate_convention") != {
        "cell_storage": "row_vectors_angstrom",
        "phonopy_cell_storage": "row_vectors_angstrom",
        "mlcc_repeat_matrix": "row_cell_transform",
        "phonopy_supercell_matrix": "repeat_matrix_transpose",
        "displacement_unit": DISTANCE_UNIT,
    }:
        raise ValueError("saved coordinate_convention differs from the canonical plan convention")
    reference = manifest.get("reference")
    displacements = manifest.get("displacements")
    if not isinstance(reference, Mapping) or reference.get("entry_id") != "reference" or reference.get("kind") != "reference":
        raise ValueError("phonon displacement plan requires reference entry")
    if not isinstance(displacements, list) or not displacements:
        raise ValueError("phonon displacement plan requires displacement entries")
    entry_ids = [entry.get("entry_id") for entry in displacements if isinstance(entry, Mapping)]
    if len(entry_ids) != len(displacements) or len(set(entry_ids)) != len(entry_ids):
        raise ValueError("phonon displacement entries require unique entry_id values")
    base = path.parent
    for entry in [reference, *displacements]:
        structure_file = entry.get("structure_file")
        if not isinstance(structure_file, str) or not structure_file or Path(structure_file).is_absolute():
            raise ValueError("phonon displacement entries require structure_file")
        if not (base / structure_file).is_file():
            raise FileNotFoundError(f"phonon displacement structure not found: {base / structure_file}")
        atom_ids = entry.get("atom_ids")
        if not isinstance(atom_ids, list) or not atom_ids:
            raise ValueError("phonon displacement entries require atom_ids")
        if len(set(atom_ids)) != len(atom_ids):
            raise ValueError("phonon displacement atom_ids must be unique")
        lineage = entry.get("atom_lineage")
        if not isinstance(lineage, list) or len(lineage) != len(atom_ids):
            raise ValueError("phonon displacement entries require one lineage record per atom")
    parent_structure_file = manifest.get("parent_structure_file")
    if (
        not isinstance(parent_structure_file, str)
        or Path(parent_structure_file).is_absolute()
        or not (base / parent_structure_file).is_file()
    ):
        raise FileNotFoundError("phonon displacement plan parent_structure_file is missing")
    source_parent = read_model_artifacts(source_model_path)
    if (source_parent.model_id, source_parent.version) != (source_model_id, source_model_version):
        raise ValueError("source_model identity differs from the current parent model")
    for field in ("material", "phase_requested"):
        if source_model[field] != source_parent.metadata.get(field):
            raise ValueError(f"source_model {field} differs from the current parent model")
    _validate_parent_model(source_parent)
    parent_snapshot = ase_read(str(base / parent_structure_file), format="extxyz", index=0)
    if not _same_atom_ids(parent_snapshot, source_parent.atom_ids):
        raise ValueError("parent snapshot atom_ids differ from source model")
    if not _same_periodic_geometry(parent_snapshot, source_parent.atoms):
        raise ValueError("parent snapshot geometry differs from source model")
    if not _same_masses(parent_snapshot, source_parent.atoms.get_masses()):
        raise ValueError("parent snapshot masses differ from source model")
    expected_parent_magmoms = (
        None
        if "initial_magmoms" not in source_parent.atoms.arrays
        else np.asarray(source_parent.atoms.arrays["initial_magmoms"], dtype=float).tolist()
    )
    if not _same_magmoms(parent_snapshot, expected_parent_magmoms):
        raise ValueError("parent snapshot initial_magmoms differ from source model")

    phonon = _build_phonopy(source_parent.atoms, canonical_request)
    _require_explicit_pairs(phonon.displacements)
    child_atom_ids = [int(index) for index in range(len(phonon.supercell))]
    lineage = _lineage_for_supercell(phonon, source_parent)
    expected_reference = _phonopy_to_ase(phonon.supercell, child_atom_ids)
    reference_path = base / reference["structure_file"]
    saved_reference = ase_read(str(reference_path), format="extxyz", index=0)
    if not _same_atom_ids(saved_reference, child_atom_ids) or not _same_periodic_geometry(
        saved_reference, expected_reference
    ):
        raise ValueError("saved reference structure differs from reconstructed Phonopy supercell")
    if not _same_masses(saved_reference, expected_reference.get_masses()) or not _same_magmoms(
        saved_reference,
        None if "initial_magmoms" not in expected_reference.arrays else expected_reference.arrays["initial_magmoms"].tolist(),
    ):
        raise ValueError("saved reference masses or initial_magmoms differ from reconstructed supercell")
    if reference.get("atom_ids") != child_atom_ids or reference.get("atom_lineage") != lineage:
        raise ValueError("saved reference atom mapping differs from reconstructed Phonopy mapping")
    if not _same_masses(saved_reference, reference.get("masses", [])) or not _same_magmoms(
        saved_reference, reference.get("initial_magmoms")
    ):
        raise ValueError("saved reference mass or initial_magmom records differ from structure")
    primitive_cell = np.asarray(manifest.get("primitive_cell_angstrom"), dtype=float)
    if primitive_cell.shape != (3, 3) or not np.allclose(
        primitive_cell, np.asarray(phonon.primitive.cell, dtype=float), rtol=0.0, atol=GEOMETRY_ATOL_ANGSTROM
    ):
        raise ValueError("saved primitive_cell_angstrom differs from reconstructed Phonopy primitive cell")
    supercells = phonon.supercells_with_displacements
    if len(displacements) != len(phonon.displacements) or len(supercells) != len(displacements):
        raise ValueError("saved displacement count differs from reconstructed Phonopy dataset")
    for index, (entry, displacement, expected_supercell) in enumerate(
        zip(displacements, phonon.displacements, supercells)
    ):
        expected_entry_id = f"disp-{index + 1:06d}"
        if entry.get("entry_id") != expected_entry_id or entry.get("displacement_index") != index:
            raise ValueError("saved displacement entry ordering differs from the generated plan")
        expected_atom = int(displacement[0])
        expected_vector = np.asarray(displacement[1:4], dtype=float)
        if entry.get("kind") != "displacement" or entry.get("displaced_atom_id") != child_atom_ids[expected_atom]:
            raise ValueError("saved displacement target differs from reconstructed Phonopy atom")
        if entry.get("phonopy_atom_index") != expected_atom or not np.allclose(
            np.asarray(entry.get("displacement_angstrom"), dtype=float),
            expected_vector,
            rtol=0.0,
            atol=1e-12,
        ):
            raise ValueError("saved displacement vector differs from reconstructed Phonopy dataset")
        if entry.get("sign") != _displacement_sign(expected_vector):
            raise ValueError("saved displacement sign differs from reconstructed Phonopy dataset")
        if entry.get("atom_ids") != child_atom_ids or entry.get("atom_lineage") != lineage:
            raise ValueError("saved displacement atom mapping differs from the reference lineage")
        expected_child = _phonopy_to_ase(expected_supercell, child_atom_ids)
        saved_child = ase_read(str(base / entry["structure_file"]), format="extxyz", index=0)
        if not _same_atom_ids(saved_child, child_atom_ids) or not _same_periodic_geometry(saved_child, expected_child):
            raise ValueError(f"saved displacement structure {entry['entry_id']} differs from Phonopy")
        if not _same_masses(saved_child, expected_child.get_masses()) or not _same_magmoms(
            saved_child,
            None if "initial_magmoms" not in expected_child.arrays else expected_child.arrays["initial_magmoms"].tolist(),
        ):
            raise ValueError(f"saved displacement masses or initial_magmoms differ for {entry['entry_id']}")
        if not _same_masses(saved_child, entry.get("masses", [])) or not _same_magmoms(
            saved_child, entry.get("initial_magmoms")
        ):
            raise ValueError(f"saved displacement mass or initial_magmom records differ for {entry['entry_id']}")
    return manifest


def _rebuild_phonopy_from_plan(manifest_path: Path, manifest: Mapping[str, Any]) -> Phonopy:
    base = manifest_path.parent
    parent_atoms = ase_read(str(base / manifest["parent_structure_file"]), format="extxyz", index=0)
    phonon = _build_phonopy(parent_atoms, manifest["request"])
    entries = manifest["displacements"]
    if len(entries) != len(phonon.displacements):
        raise ValueError("saved displacement manifest does not match reconstructed Phonopy dataset")
    for entry, displacement in zip(entries, phonon.displacements):
        expected_atom = int(entry["phonopy_atom_index"])
        expected_vector = np.asarray(entry["displacement_angstrom"], dtype=float)
        if expected_atom != int(displacement[0]) or not np.allclose(
            expected_vector, np.asarray(displacement[1:4], dtype=float), rtol=0.0, atol=1e-12
        ):
            raise ValueError("saved displacement manifest differs from reconstructed Phonopy dataset")
    return phonon


def _force_records(manifest: Mapping[str, Any], force_bundle: Mapping[str, Any]) -> np.ndarray:
    if not isinstance(force_bundle, Mapping):
        raise ValueError("force_bundle must be a JSON object")
    if force_bundle.get("unit") != FORCE_UNIT:
        raise ValueError(f"force_bundle.unit must be exactly {FORCE_UNIT!r}")
    source = _non_empty_string(force_bundle.get("source"), "force_bundle.source")
    records = force_bundle.get("records")
    if not isinstance(records, list):
        raise ValueError("force_bundle.records must be a list")
    entries = manifest["displacements"]
    expected_ids = [str(entry["entry_id"]) for entry in entries]
    actual_ids = [record.get("entry_id") for record in records if isinstance(record, Mapping)]
    if len(actual_ids) != len(records) or len(actual_ids) != len(set(actual_ids)):
        raise ValueError("force records require unique entry_id values")
    if set(actual_ids) != set(expected_ids):
        raise ValueError("force records must match every displacement entry exactly")
    by_id = {str(record["entry_id"]): record for record in records}
    atom_ids = list(manifest["reference"]["atom_ids"])
    collected: list[np.ndarray] = []
    for entry in entries:
        record = by_id[str(entry["entry_id"])]
        source_ref = _non_empty_string(record.get("source_ref"), f"force record {entry['entry_id']} source_ref")
        if record.get("atom_ids") != atom_ids:
            raise ValueError(f"force record {entry['entry_id']} atom_ids do not match the displacement plan")
        values = np.asarray(record.get("forces"), dtype=float)
        if values.shape != (len(atom_ids), 3) or not np.all(np.isfinite(values)):
            raise ValueError(f"force record {entry['entry_id']} forces must have shape (N_atoms, 3)")
        collected.append(values)
    return np.asarray(collected, dtype=float)


def compute_harmonic_qpoints(
    manifest_path: str | Path,
    force_bundle: Mapping[str, Any],
    q_points: Sequence[Sequence[float]],
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Fit traditional finite-difference force constants and calculate q points.

    The input force bundle must identify every displacement entry, use the
    canonical ``eV/angstrom`` unit, and provide a non-empty source reference
    for every force array.  The manifest is rebuilt before fitting, so an
    un-mapped force-constant tensor cannot be supplied directly.
    """

    manifest_file = _manifest_path(manifest_path)
    manifest = load_phonon_displacement_plan(manifest_file)
    q_array = np.asarray(q_points, dtype=float)
    if q_array.ndim != 2 or q_array.shape[1] != 3 or len(q_array) == 0 or not np.all(np.isfinite(q_array)):
        raise ValueError("q_points must be a non-empty finite sequence of three-vectors")
    forces = _force_records(manifest, force_bundle)
    phonon = _rebuild_phonopy_from_plan(manifest_file, manifest)
    if forces.shape != (len(phonon.displacements), len(phonon.supercell), 3):
        raise ValueError("force bundle shape does not match the reconstructed Phonopy plan")
    phonon.forces = forces
    phonon.produce_force_constants(
        calculate_full_force_constants=True,
        fc_calculator="traditional",
        show_drift=False,
    )
    result = phonon.run_qpoints(q_array.tolist(), with_eigenvectors=False)
    units = get_physical_units()
    output: dict[str, Any] = {
        "schema": HARMONIC_SCHEMA,
        "scientific_status": "software_math_only_unqualified",
        "production_qualified": False,
        "scientific_qualification": False,
        "plan": {
            "plan_id": manifest["plan_id"],
            "version": manifest["version"],
            "manifest_path": str(manifest_file.resolve()),
        },
        "force_input": {
            "unit": force_bundle["unit"],
            "source": force_bundle["source"],
            "entry_ids": [str(entry["entry_id"]) for entry in manifest["displacements"]],
            "source_refs": [
                _non_empty_string(
                    next(record["source_ref"] for record in force_bundle["records"] if record["entry_id"] == entry["entry_id"]),
                    f"force record {entry['entry_id']} source_ref",
                )
                for entry in manifest["displacements"]
            ],
        },
        "force_constants_unit": FORCE_CONSTANT_UNIT,
        "force_constants_basis": "phonopy_supercell_atom_order",
        "force_constants": np.asarray(phonon.force_constants, dtype=float).tolist(),
        "primitive_cell_angstrom": np.asarray(phonon.primitive.cell, dtype=float).tolist(),
        "q_point_coordinate_basis": "primitive_reciprocal_fractional",
        "qpoints": np.asarray(result.qpoints, dtype=float).tolist(),
        "frequencies_THz": np.asarray(result.frequencies, dtype=float).tolist(),
        "frequency_unit": "THz",
        "unit_conversion_factor_to_THz": float(units.DefaultToTHz),
        "nac": "not_requested",
        "asr": "not_applied",
        "imaginary_frequencies_preserved": True,
    }
    if output_path is not None:
        _write_json(Path(output_path), output)
    return output


__all__ = [
    "FORCE_CONSTANT_UNIT",
    "FORCE_UNIT",
    "HARMONIC_SCHEMA",
    "PLAN_SCHEMA",
    "compute_harmonic_qpoints",
    "generate_phonon_displacement_plan",
    "load_phonon_displacement_plan",
]
