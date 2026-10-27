"""Explicit model derivations for supercells and user-selected defects.

This module only constructs structure artifacts.  It does not choose a site,
charge compensation, random distribution, potential, or numerical task.  A
derived model remains an unrelaxed, unqualified structure until a study binds
it explicitly and a later method/physics qualification supplies evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from ase import Atoms
from ase.build.supercells import lattice_points_in_supercell

from .modeling import ModelArtifacts, read_model_artifacts, write_model_artifacts


_DERIVATION_SCHEMA = "mlcc.model-derivation.v1"


def _required_identity(request: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(request, Mapping):
        raise ValueError("derivation request must be a JSON object")
    model_id = request.get("model_id")
    version = request.get("version")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("derivation request requires model_id")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("derivation request requires version")
    study_id = request.get("study_id")
    if study_id is not None and (not isinstance(study_id, str) or not study_id.strip()):
        raise ValueError("study_id must be a non-empty string when supplied")
    return model_id, version


def _integer_matrix(value: Any) -> np.ndarray:
    matrix = np.asarray(value)
    if matrix.shape != (3, 3):
        raise ValueError("repeat_matrix must be a 3x3 integer matrix")
    if matrix.dtype.kind == "b" or not np.issubdtype(matrix.dtype, np.number):
        raise ValueError("repeat_matrix must be a 3x3 integer matrix")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("repeat_matrix must contain finite values")
    rounded = np.rint(matrix)
    if not np.allclose(matrix, rounded, rtol=0.0, atol=1e-12):
        raise ValueError("repeat_matrix must be a 3x3 integer matrix")
    integer = rounded.astype(np.int64)
    determinant = int(round(float(np.linalg.det(integer))))
    if determinant <= 0:
        raise ValueError("repeat_matrix must be right-handed with positive determinant")
    if not np.isclose(float(np.linalg.det(integer)), determinant, rtol=0.0, atol=1e-10):
        raise ValueError("repeat_matrix determinant must be an integer")
    return integer


def _parent_record(parent: ModelArtifacts) -> dict[str, Any]:
    return {
        "model_id": parent.model_id,
        "version": parent.version,
        "path": str(parent.artifact_dir.resolve()),
    }


def _repeat_initial_magmoms(parent: Atoms, count: int, child_size: int) -> np.ndarray | None:
    if "initial_magmoms" not in parent.arrays:
        return None
    values = np.asarray(parent.arrays["initial_magmoms"])
    if values.shape[0] != child_size // count:
        raise ValueError("parent initial_magmoms length does not match parent atom count")
    return np.tile(values, (count,) + (1,) * (values.ndim - 1))


def _write_derived(
    parent: ModelArtifacts,
    atoms: Atoms,
    output_path: str | Path,
    request: Mapping[str, Any],
    *,
    derivation: dict[str, Any],
    atom_lineage: list[dict[str, Any]],
    basis_transform: dict[str, Any],
    spatial_mode: str,
) -> ModelArtifacts:
    model_id, version = _required_identity(request)
    if (model_id, version) == (parent.model_id, parent.version):
        raise ValueError("derived model must use a new model_id and version")
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"derived model output directory already exists: {output}")
    parent_metadata = parent.metadata
    # write_model_artifacts requires source and working IDs to agree.  The
    # derived child is the canonical structure; parent provenance is recorded
    # explicitly below instead of being treated as a second same-ID structure.
    result = write_model_artifacts(
        atoms,
        output,
        model_id=model_id,
        version=version,
        fixture=bool(parent_metadata.get("fixture", False)),
        fixture_purpose=parent_metadata.get("fixture_purpose"),
        phase_requested=str(parent_metadata.get("phase_requested", "user_selected_phase_pending")),
        source_path=str(parent.artifact_dir.resolve()),
        source_version=f"{parent.model_id}:{parent.version}",
        source_atoms=atoms.copy(),
        material=parent_metadata.get("material"),
        source_format="model_artifacts",
        source_reference=f"parent model {parent.model_id}:{parent.version}",
        selection_status="explicit_derived_model",
        material_selection_confirmed=parent_metadata.get("material_selection_confirmed"),
        basis_transform=basis_transform,
        atom_lineage=atom_lineage,
        scientific_status="derived_structure_not_relaxed",
    )
    metadata = dict(result.metadata)
    parent_ref = _parent_record(parent)
    parent_source_ref = {
        "model_id": parent.model_id,
        "version": parent.version,
        "artifact_dir": str(parent.artifact_dir.resolve()),
        "source_path": parent_metadata.get("source_path"),
        "source_structure_file": parent_metadata.get("source_structure_file"),
    }
    metadata.update(
        {
            "schema": metadata.get("schema", "mlcc.model.v1"),
            "parent_models": [parent_ref],
            "parent_model": parent_ref,
            "parent_source_ref": parent_source_ref,
            "source_structure_role": "generated_child_reference",
            "derivation_schema": _DERIVATION_SCHEMA,
            "derivation": derivation,
            "charge_state": derivation.get("charge_state", 0),
            "spatial_mode": spatial_mode,
            "relaxation_status": "not_run",
            "phase_relaxed": None,
            "production_qualified": False,
            "study_id": request.get("study_id"),
            "study_binding": request.get("study_id"),
            "atom_lineage_file": "atom-lineage.json",
        }
    )
    (output / "model.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lineage_record = json.loads((output / "atom-lineage.json").read_text(encoding="utf-8"))
    lineage_record.update(
        {
            "schema": "mlcc.atom-lineage.v1",
            "parent_model": parent_ref,
            "parent_source_ref": parent_source_ref,
            "source_structure_role": "generated_child_reference",
            "derivation_schema": _DERIVATION_SCHEMA,
            "derivation": derivation,
        }
    )
    (output / "atom-lineage.json").write_text(
        json.dumps(lineage_record, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    dopants = json.loads((output / "dopants.json").read_text(encoding="utf-8"))
    dopants.update(
        {
            "spatial_mode": spatial_mode,
            "derivation_kind": derivation["kind"],
            "operations": derivation.get("operations", []),
            "charge_state": derivation.get("charge_state", 0),
            "compensation": None,
        }
    )
    if derivation["kind"] == "explicit_defect_sequence":
        dopants["composition_delta"] = derivation["composition_delta"]
    (output / "dopants.json").write_text(
        json.dumps(dopants, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    result.metadata = metadata
    return result


def supercell_parent_images(repeat_matrix: Any) -> np.ndarray:
    """Return the integer parent images used by the existing supercell builder."""
    matrix = _integer_matrix(repeat_matrix)
    points_frac = np.asarray(lattice_points_in_supercell(matrix), dtype=float)
    parent_images_float = points_frac @ matrix
    parent_images = np.rint(parent_images_float).astype(np.int64)
    if not np.allclose(parent_images_float, parent_images, rtol=0.0, atol=1e-9):
        raise ValueError("ASE supercell lattice points did not produce integer parent images")
    determinant = int(round(float(np.linalg.det(matrix))))
    if len(parent_images) != determinant:
        raise ValueError("supercell image count differs from the positive matrix determinant")
    if len({tuple(int(value) for value in image) for image in parent_images}) != determinant:
        raise ValueError("supercell parent images are not unique")

    return parent_images


def derive_supercell_model(
    parent_path: str | Path,
    request: Mapping[str, Any],
    output_path: str | Path,
) -> ModelArtifacts:
    """Create an exact integer supercell from one saved model.

    ``request["repeat_matrix"]`` is an explicit right-handed integer matrix
    with positive determinant.  Child atom IDs are newly assigned; each
    lineage entry records the parent atom ID and the integer parent-cell image
    used to form its Cartesian position.
    """

    model_id, version = _required_identity(request)
    if "repeat_matrix" not in request:
        raise ValueError("supercell derivation requires repeat_matrix")
    matrix = _integer_matrix(request["repeat_matrix"])
    parent = read_model_artifacts(parent_path)
    parent_charge_state = _model_charge_state(parent.metadata)
    if parent_charge_state != 0:
        raise ValueError(
            "cannot derive a supercell from a charged parent model without "
            "an explicit supercell charge convention"
        )
    parent_atoms = parent.atoms
    if not bool(np.all(np.asarray(parent_atoms.pbc, dtype=bool))):
        raise ValueError("supercell derivation requires a three-dimensional periodic parent")
    parent_cell = np.asarray(parent_atoms.cell.array, dtype=float)
    parent_frac = np.asarray(parent_atoms.get_scaled_positions(wrap=False), dtype=float)
    parent_ids = parent.atom_ids
    symbols = parent_atoms.get_chemical_symbols()
    parent_images = supercell_parent_images(matrix)
    determinant = len(parent_images)

    child_symbols: list[str] = []
    child_positions: list[list[float]] = []
    lineage: list[dict[str, Any]] = []
    child_id = 0
    for image in parent_images:
        image_list = [int(value) for value in image]
        for index, (symbol, atom_id) in enumerate(zip(symbols, parent_ids)):
            unwrapped_fractional = parent_frac[index] + image
            position = unwrapped_fractional @ parent_cell
            child_symbols.append(str(symbol))
            child_positions.append([float(value) for value in position])
            lineage.append(
                {
                    "child_atom_id": child_id,
                    "parent_atom_id": int(atom_id),
                    "parent_image": image_list,
                    "parent_frac_coords": [float(value) for value in parent_frac[index]],
                    "parent_frac_coords_unwrapped": [float(value) for value in unwrapped_fractional],
                    "element": str(symbol),
                    "kind": "supercell_replica",
                }
            )
            child_id += 1

    child_cell = matrix.astype(float) @ parent_cell
    child = Atoms(symbols=child_symbols, positions=child_positions, cell=child_cell, pbc=parent_atoms.pbc)
    child.new_array("atom_id", np.arange(len(child), dtype=np.int64))
    magmoms = _repeat_initial_magmoms(parent_atoms, determinant, len(child))
    if magmoms is not None:
        child.new_array("initial_magmoms", magmoms)

    derivation = {
        "kind": "exact_integer_supercell",
        "model_id": model_id,
        "version": version,
        "repeat_matrix": matrix.tolist(),
        "determinant": determinant,
        "parent_atom_count": len(parent_atoms),
        "child_atom_count": len(child),
        "charge_state": parent_charge_state,
        "charge_convention": "explicit q metadata; supercell derivation requires a neutral parent",
        "relaxation_status": "not_run",
        "production_qualified": False,
        "study_id": request.get("study_id"),
    }
    basis_transform = {
        "kind": "exact_integer_supercell",
        "fractional_matrix": matrix.tolist(),
        "source_lattice_angstrom": parent_cell.tolist(),
        "target_lattice_angstrom": child_cell.tolist(),
        "parent_model": _parent_record(parent),
    }
    return _write_derived(
        parent,
        child,
        output_path,
        request,
        derivation=derivation,
        atom_lineage=lineage,
        basis_transform=basis_transform,
        spatial_mode="exact_supercell",
    )


def _explicit_charge(request: Mapping[str, Any]) -> int:
    if "charge_state" not in request:
        raise ValueError("defect derivation requires an explicit integer charge_state")
    value = request["charge_state"]
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError("charge_state must be an integer")
    return int(value)


def _model_charge_state(metadata: Mapping[str, Any]) -> int:
    """Read the explicit charge state carried by a model derivation.

    Pristine/source models have no derivation and are therefore neutral for
    this structural operation.  A malformed explicit charge value is an
    input-contract error rather than something to coerce silently.
    """

    derivation = metadata.get("derivation")
    if isinstance(derivation, Mapping) and "charge_state" in derivation:
        value = derivation["charge_state"]
    elif "charge_state" in metadata:
        value = metadata["charge_state"]
    else:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError("parent model charge_state must be an explicit integer")
    return int(value)


def _require_atom_id(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer atom ID")
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _require_element(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(character.isspace() for character in value):
        raise ValueError(f"{name} must be a non-empty element symbol")
    return value.strip()


def derive_defect_model(
    parent_path: str | Path,
    request: Mapping[str, Any],
    output_path: str | Path,
) -> ModelArtifacts:
    """Apply an explicit ordered vacancy/substitution/interstitial sequence.

    Operations act on the atom IDs present at that point in the sequence.  No
    site, compensation, random seed, or charge distribution is inferred.  A
    charge state is metadata only; this function does not claim that a charged
    ABACUS calculation is executable or qualified.
    """

    model_id, version = _required_identity(request)
    charge_state = _explicit_charge(request)
    if request.get("compensation") is not None:
        raise ValueError("defect derivation does not infer or accept compensation")
    if request.get("random_seed") is not None:
        raise ValueError("defect derivation does not infer or accept random placement")
    operations_value = request.get("operations")
    if not isinstance(operations_value, Sequence) or isinstance(operations_value, (str, bytes)) or not operations_value:
        raise ValueError("defect derivation requires a non-empty ordered operations list")

    parent = read_model_artifacts(parent_path)
    parent_atoms = parent.atoms
    cell = np.asarray(parent_atoms.cell.array, dtype=float)
    parent_ids = parent.atom_ids
    symbols = [str(value) for value in parent_atoms.get_chemical_symbols()]
    frac_coords = [list(float(value) for value in row) for row in parent_atoms.get_scaled_positions(wrap=False)]
    atom_ids = list(parent_ids)
    initial_magmoms: list[Any] | None = None
    if "initial_magmoms" in parent_atoms.arrays:
        initial_magmoms = np.asarray(parent_atoms.arrays["initial_magmoms"]).tolist()
    lineage = [
        {
            "child_atom_id": int(atom_id),
            "parent_atom_id": int(atom_id),
            "parent_image": [0, 0, 0],
            "parent_frac_coords": list(frac_coords[index]),
            "parent_frac_coords_unwrapped": list(frac_coords[index]),
            "element": symbols[index],
            "kind": "retained_parent_atom",
        }
        for index, atom_id in enumerate(atom_ids)
    ]
    used_ids = set(int(value) for value in parent_ids)
    operation_records: list[dict[str, Any]] = []
    composition_parent = {element: symbols.count(element) for element in dict.fromkeys(symbols)}

    for order, operation_value in enumerate(operations_value, start=1):
        if not isinstance(operation_value, Mapping):
            raise ValueError("each defect operation must be a JSON object")
        kind = operation_value.get("kind")
        if kind == "vacancy":
            atom_id = _require_atom_id(operation_value.get("atom_id"), "vacancy atom_id")
            if atom_id not in atom_ids:
                raise ValueError(f"vacancy atom_id {atom_id} is not present at operation {order}")
            index = atom_ids.index(atom_id)
            element = symbols.pop(index)
            atom_ids.pop(index)
            frac_coords.pop(index)
            if initial_magmoms is not None:
                initial_magmoms.pop(index)
            lineage = [entry for entry in lineage if int(entry["child_atom_id"]) != atom_id]
            operation_records.append(
                {
                    "order": order,
                    "kind": "vacancy",
                    "atom_id": atom_id,
                    "element": element,
                    "delta_N": {element: -1},
                }
            )
        elif kind == "substitution":
            atom_id = _require_atom_id(operation_value.get("atom_id"), "substitution atom_id")
            if atom_id not in atom_ids:
                raise ValueError(f"substitution atom_id {atom_id} is not present at operation {order}")
            new_element = _require_element(operation_value.get("new_element"), "substitution new_element")
            index = atom_ids.index(atom_id)
            old_element = symbols[index]
            if old_element == new_element:
                raise ValueError("substitution new_element must differ from the current element")
            symbols[index] = new_element
            for entry in lineage:
                if int(entry["child_atom_id"]) == atom_id:
                    entry["element"] = new_element
                    entry["kind"] = "substitution"
                    break
            operation_records.append(
                {
                    "order": order,
                    "kind": "substitution",
                    "atom_id": atom_id,
                    "old_element": old_element,
                    "new_element": new_element,
                    "delta_N": {old_element: -1, new_element: 1},
                }
            )
        elif kind == "interstitial":
            new_atom_id = _require_atom_id(operation_value.get("new_atom_id"), "interstitial new_atom_id")
            if new_atom_id in used_ids:
                raise ValueError(f"interstitial new_atom_id {new_atom_id} has already been used")
            element = _require_element(operation_value.get("element"), "interstitial element")
            frac_value = np.asarray(operation_value.get("frac_coords"), dtype=float)
            if frac_value.shape != (3,) or not np.all(np.isfinite(frac_value)):
                raise ValueError("interstitial frac_coords must be three finite numbers")
            atom_ids.append(new_atom_id)
            used_ids.add(new_atom_id)
            symbols.append(element)
            frac_coords.append([float(value) for value in frac_value])
            if initial_magmoms is not None:
                zero = np.zeros_like(np.asarray(initial_magmoms[0], dtype=float)) if initial_magmoms else 0.0
                initial_magmoms.append(zero.tolist() if isinstance(zero, np.ndarray) else float(zero))
            lineage.append(
                {
                    "child_atom_id": new_atom_id,
                    "parent_atom_id": None,
                    "parent_image": None,
                    "parent_frac_coords": None,
                    "parent_frac_coords_unwrapped": [float(value) for value in frac_value],
                    "element": element,
                    "kind": "interstitial",
                }
            )
            operation_records.append(
                {
                    "order": order,
                    "kind": "interstitial",
                    "new_atom_id": new_atom_id,
                    "element": element,
                    "frac_coords": [float(value) for value in frac_value],
                    "delta_N": {element: 1},
                }
            )
        else:
            raise ValueError(f"unsupported explicit defect operation kind: {kind!r}")

    if len(set(atom_ids)) != len(atom_ids):
        raise ValueError("derived defect atom IDs must be unique")
    positions = np.asarray(frac_coords, dtype=float) @ cell
    child = Atoms(symbols=symbols, positions=positions, cell=cell, pbc=parent_atoms.pbc)
    child.new_array("atom_id", np.asarray(atom_ids, dtype=np.int64))
    if initial_magmoms is not None:
        child.new_array("initial_magmoms", np.asarray(initial_magmoms))

    composition_child = {element: symbols.count(element) for element in dict.fromkeys(symbols)}
    all_elements = list(dict.fromkeys([*composition_parent, *composition_child]))
    composition_delta = {
        element: int(composition_child.get(element, 0) - composition_parent.get(element, 0))
        for element in all_elements
        if composition_child.get(element, 0) - composition_parent.get(element, 0) != 0
    }
    derivation = {
        "kind": "explicit_defect_sequence",
        "model_id": model_id,
        "version": version,
        "operations": operation_records,
        "composition_parent": composition_parent,
        "composition_child": composition_child,
        "composition_delta": composition_delta,
        "charge_state": charge_state,
        "charge_convention": "explicit q metadata; charged DFT capability not qualified",
        "relaxation_status": "not_run",
        "production_qualified": False,
        "study_id": request.get("study_id"),
    }
    basis_transform = {
        "kind": "defect_derivation_same_cell",
        "fractional_matrix": np.eye(3, dtype=int).tolist(),
        "source_lattice_angstrom": cell.tolist(),
        "target_lattice_angstrom": cell.tolist(),
        "parent_model": _parent_record(parent),
    }
    return _write_derived(
        parent,
        child,
        output_path,
        request,
        derivation=derivation,
        atom_lineage=lineage,
        basis_transform=basis_transform,
        spatial_mode="explicit_defect_sequence",
    )


__all__ = ["derive_supercell_model", "derive_defect_model"]
