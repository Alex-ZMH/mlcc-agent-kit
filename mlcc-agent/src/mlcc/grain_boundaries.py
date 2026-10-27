"""Direct grain-boundary geometry construction for MLCC models.

This module deliberately implements one small geometry contract.  It accepts
one periodic parent model, two explicitly supplied integer supercell
transforms, and two Cartesian rotations.  Matching is checked from the
declared cells; no CSL search, strain relaxation, atom deletion, or scheduler
operation is performed here.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from ase import Atoms
from ase.build.supercells import lattice_points_in_supercell
from ase.neighborlist import neighbor_list

from .modeling import ModelArtifacts, read_model_artifacts, write_model_artifacts


_GEOMETRY_TOLERANCE = 1.0e-8


def _integer_charge(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an explicit integer")
    return int(value)


def _finite_matrix(value: Any, *, name: str, shape: tuple[int, int]) -> np.ndarray:
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != shape or not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must be a finite {shape[0]}x{shape[1]} matrix")
    return matrix


def _finite_vector(value: Any, *, name: str, size: int) -> np.ndarray:
    vector = np.asarray(value, dtype=float)
    if vector.shape != (size,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must be a finite vector of length {size}")
    return vector


def _integer_transform(value: Any, *, name: str) -> np.ndarray:
    matrix = np.asarray(value)
    if matrix.shape != (3, 3):
        raise ValueError(f"{name} must be a 3x3 integer matrix")
    if not np.issubdtype(matrix.dtype, np.integer):
        as_float = np.asarray(value, dtype=float)
        if not np.all(np.isfinite(as_float)) or not np.allclose(
            as_float, np.rint(as_float), rtol=0.0, atol=0.0
        ):
            raise ValueError(f"{name} must be a 3x3 integer matrix")
        matrix = np.rint(as_float).astype(np.int64)
    else:
        matrix = matrix.astype(np.int64, copy=False)
    determinant = int(round(float(np.linalg.det(matrix))))
    if determinant <= 0:
        raise ValueError(f"{name} must have a positive integer determinant")
    if not np.isclose(float(np.linalg.det(matrix)), float(determinant), rtol=0.0, atol=1.0e-8):
        raise ValueError(f"{name} determinant is not an integer")
    return matrix


def _proper_rotation(value: Any, *, name: str) -> np.ndarray:
    rotation = _finite_matrix(value, name=name, shape=(3, 3))
    if not np.allclose(rotation @ rotation.T, np.eye(3), rtol=0.0, atol=_GEOMETRY_TOLERANCE):
        raise ValueError(f"{name} must be an orthogonal Cartesian rotation")
    determinant = float(np.linalg.det(rotation))
    if not np.isclose(determinant, 1.0, rtol=0.0, atol=_GEOMETRY_TOLERANCE):
        raise ValueError(f"{name} must be a proper Cartesian rotation")
    return rotation


def _fractional_translation(value: Any, *, name: str) -> np.ndarray:
    translation = _finite_vector(value, name=name, size=2)
    if np.any(translation < 0.0) or np.any(translation >= 1.0):
        raise ValueError(f"{name} must lie in the half-open interval [0, 1)^2")
    return translation


def _image_points(transform: np.ndarray) -> list[np.ndarray]:
    points = np.asarray(lattice_points_in_supercell(transform.astype(float)), dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("ASE lattice_points_in_supercell returned invalid image points")
    expected = int(round(float(np.linalg.det(transform))))
    if len(points) != expected:
        raise ValueError("ASE lattice_points_in_supercell returned an incomplete supercell")
    images: list[np.ndarray] = []
    for point in points:
        image_float = point @ transform
        image = np.rint(image_float).astype(np.int64)
        if not np.allclose(image_float, image, rtol=0.0, atol=_GEOMETRY_TOLERANCE):
            raise ValueError("ASE supercell image point is not an integer parent image")
        images.append(image)
    return images


def _parent_charge_record(metadata: Mapping[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    if "charge_state" in metadata:
        value = metadata["charge_state"]
        charge = _integer_charge(value, name="parent metadata charge_state")
        if charge != 0:
            raise ValueError("parent metadata charge_state must be neutral for grain-boundary geometry")
        record["metadata.charge_state"] = {"present": True, "value": charge}
    else:
        record["metadata.charge_state"] = {"present": False, "value": None}

    if "net_charge" in metadata:
        value = metadata["net_charge"]
        charge = _integer_charge(value, name="parent metadata net_charge")
        if charge != 0:
            raise ValueError("parent metadata net_charge must be neutral for grain-boundary geometry")
        record["metadata.net_charge"] = {"present": True, "value": charge}
    else:
        record["metadata.net_charge"] = {"present": False, "value": None}

    if "derivation" in metadata:
        derivation = metadata["derivation"]
        if not isinstance(derivation, Mapping):
            raise ValueError("parent metadata derivation must be an object when present")
        if "charge_state" in derivation:
            value = derivation["charge_state"]
            charge = _integer_charge(value, name="parent metadata derivation.charge_state")
            if charge != 0:
                raise ValueError("parent metadata derivation.charge_state must be neutral")
            record["metadata.derivation.charge_state"] = {"present": True, "value": charge}
        else:
            record["metadata.derivation.charge_state"] = {"present": False, "value": None}
        if "net_charge" in derivation:
            value = derivation["net_charge"]
            charge = _integer_charge(value, name="parent metadata derivation.net_charge")
            if charge != 0:
                raise ValueError("parent metadata derivation.net_charge must be neutral")
            record["metadata.derivation.net_charge"] = {"present": True, "value": charge}
        else:
            record["metadata.derivation.net_charge"] = {"present": False, "value": None}
    else:
        record["metadata.derivation.charge_state"] = {"present": False, "value": None}
        record["metadata.derivation.net_charge"] = {"present": False, "value": None}
    return record


def _validate_parent(parent: ModelArtifacts) -> np.ndarray:
    atoms = parent.atoms
    if len(atoms) == 0:
        raise ValueError("grain-boundary parent model contains no atoms")
    if not bool(np.all(np.asarray(atoms.pbc, dtype=bool))):
        raise ValueError("grain-boundary parent model must be three-dimensional periodic")
    cell = np.asarray(atoms.cell.array, dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("grain-boundary parent model must have a finite 3x3 cell")
    if abs(float(np.linalg.det(cell))) <= 1.0e-12:
        raise ValueError("grain-boundary parent model cell must have non-zero volume")
    if "atom_id" not in atoms.arrays:
        raise ValueError("grain-boundary parent model must carry atom_id values")
    if "initial_magmoms" in atoms.arrays:
        magmoms = np.asarray(atoms.arrays["initial_magmoms"])
        if magmoms.ndim != 1 or len(magmoms) != len(atoms):
            raise ValueError(
                "noncollinear initial_magmoms require an explicit rotation extension; "
                "the current grain-boundary contract accepts scalar moments only"
            )
    return cell


def _validate_pristine_parent(parent: ModelArtifacts) -> None:
    if parent.metadata["spatial_mode"] != "pristine":
        raise ValueError(
            "grain-boundary first slice requires a parent with spatial_mode=pristine"
        )
    if parent.metadata["dopants"]:
        raise ValueError(
            "grain-boundary first slice requires a parent with an empty dopants list"
        )
    dopants_path = Path(parent.artifact_dir) / parent.metadata["dopants_file"]
    dopants_document = json.loads(dopants_path.read_text(encoding="utf-8"))
    if dopants_document["spatial_mode"] != "pristine":
        raise ValueError(
            "grain-boundary first slice requires dopants.json spatial_mode=pristine"
        )
    if dopants_document["dopants"]:
        raise ValueError(
            "grain-boundary first slice requires dopants.json to contain no dopants"
        )


def _validate_request(
    request: Mapping[str, Any],
    parent_cell: np.ndarray,
) -> tuple[dict[str, Any], list[dict[str, Any]], np.ndarray, np.ndarray, float]:
    model_id = request["model_id"]
    version = request["version"]
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("grain-boundary model_id must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("grain-boundary version must be a non-empty string")
    if request["purpose"] != "engineering_geometry":
        raise ValueError("grain-boundary request purpose must be engineering_geometry")
    parent_charge_state = _integer_charge(request["parent_charge_state"], name="parent_charge_state")
    charge_state = _integer_charge(request["charge_state"], name="charge_state")
    if parent_charge_state != 0 or charge_state != 0:
        raise ValueError("grain-boundary geometry currently accepts only explicit neutral charge_state=0")

    boundary_plane = request["boundary_plane"]
    normal = _finite_vector(boundary_plane["normal_cartesian"], name="boundary_plane.normal_cartesian", size=3)
    normal_norm = float(np.linalg.norm(normal))
    if normal_norm <= 1.0e-12:
        raise ValueError("boundary_plane.normal_cartesian must be non-zero")
    unit_normal = normal / normal_norm

    explicit_cell = _finite_matrix(request["periodic_cell_angstrom"], name="periodic_cell_angstrom", shape=(3, 3))
    if abs(float(np.linalg.det(explicit_cell))) <= 1.0e-12:
        raise ValueError("periodic_cell_angstrom must have non-zero volume")

    overlap_policy = request["overlap_policy"]
    if overlap_policy["action"] != "reject":
        raise ValueError("grain-boundary overlap_policy.action must be reject")
    minimum_distance = float(overlap_policy["minimum_distance_angstrom"])
    if not np.isfinite(minimum_distance) or minimum_distance <= 0.0:
        raise ValueError("overlap_policy.minimum_distance_angstrom must be positive and finite")

    raw_grains = request["grains"]
    if not isinstance(raw_grains, list) or len(raw_grains) != 2:
        raise ValueError("grain-boundary request must contain exactly two grains")
    grains: list[dict[str, Any]] = []
    seen_ids: list[int] = []
    for index, raw in enumerate(raw_grains):
        grain_id = _integer_charge(raw["grain_id"], name=f"grains[{index}].grain_id")
        seen_ids.append(grain_id)
        transform = _integer_transform(raw["integer_transform"], name=f"grains[{index}].integer_transform")
        rotation = _proper_rotation(raw["rotation_cartesian"], name=f"grains[{index}].rotation_cartesian")
        termination = float(raw["termination_fraction"])
        if not np.isfinite(termination) or termination < 0.0 or termination >= 1.0:
            raise ValueError(f"grains[{index}].termination_fraction must lie in [0, 1)")
        translation = _fractional_translation(
            raw["in_plane_translation_fractional"],
            name=f"grains[{index}].in_plane_translation_fractional",
        )
        grain_cell = transform @ parent_cell @ rotation.T
        c0, c1, c2 = grain_cell
        if abs(float(np.dot(c0, unit_normal))) > _GEOMETRY_TOLERANCE:
            raise ValueError(f"grains[{index}] first cell vector is not in the declared boundary plane")
        if abs(float(np.dot(c1, unit_normal))) > _GEOMETRY_TOLERANCE:
            raise ValueError(f"grains[{index}] second cell vector is not in the declared boundary plane")
        parallel = float(np.dot(c2, unit_normal))
        if parallel <= _GEOMETRY_TOLERANCE:
            raise ValueError(f"grains[{index}] third cell vector is not positive along the declared normal")
        if not np.allclose(c2, parallel * unit_normal, rtol=0.0, atol=_GEOMETRY_TOLERANCE):
            raise ValueError(f"grains[{index}] third cell vector is not parallel to the declared normal")
        grains.append(
            {
                "grain_id": grain_id,
                "integer_transform": transform,
                "rotation_cartesian": rotation,
                "termination_fraction": termination,
                "in_plane_translation_fractional": translation,
                "grain_cell": grain_cell,
                "images": _image_points(transform),
            }
        )
    if seen_ids != [0, 1]:
        raise ValueError("grain IDs must be the explicit ordered pair [0, 1]")

    grain_a = grains[0]["grain_cell"]
    grain_b = grains[1]["grain_cell"]
    if not np.allclose(grain_a[:2], grain_b[:2], rtol=0.0, atol=_GEOMETRY_TOLERANCE):
        raise ValueError("grain in-plane cell vectors do not match exactly")
    final_cell = np.vstack((grain_a[:2], grain_a[2] + grain_b[2]))
    if not np.allclose(final_cell, explicit_cell, rtol=0.0, atol=_GEOMETRY_TOLERANCE):
        raise ValueError("periodic_cell_angstrom does not equal the explicit grain-cell stack")

    normalized_request = {
        "model_id": model_id,
        "version": version,
        "purpose": request["purpose"],
        "parent_charge_state": parent_charge_state,
        "charge_state": charge_state,
        "grains": [
            {
                "grain_id": item["grain_id"],
                "integer_transform": item["integer_transform"].tolist(),
                "rotation_cartesian": item["rotation_cartesian"].tolist(),
                "termination_fraction": item["termination_fraction"],
                "in_plane_translation_fractional": item["in_plane_translation_fractional"].tolist(),
            }
            for item in grains
        ],
        "boundary_plane": {
            "normal_cartesian": normal.tolist(),
            "unit_normal_cartesian": unit_normal.tolist(),
        },
        "periodic_cell_angstrom": explicit_cell.tolist(),
        "overlap_policy": {
            "action": overlap_policy["action"],
            "minimum_distance_angstrom": minimum_distance,
        },
    }
    return normalized_request, grains, explicit_cell, unit_normal, minimum_distance


def _build_atoms_and_lineage(
    parent: ModelArtifacts,
    grains: list[dict[str, Any]],
    final_cell: np.ndarray,
) -> tuple[Atoms, list[dict[str, Any]]]:
    parent_atoms = parent.atoms
    parent_cell = np.asarray(parent_atoms.cell.array, dtype=float)
    parent_positions = np.asarray(parent_atoms.get_positions(), dtype=float)
    parent_ids = np.asarray(parent_atoms.arrays["atom_id"], dtype=np.int64)
    symbols: list[str] = []
    positions: list[np.ndarray] = []
    grain_ids: list[int] = []
    lineage: list[dict[str, Any]] = []
    magnetic_moments: list[float] | None = [] if "initial_magmoms" in parent_atoms.arrays else None
    initial_charges: list[Any] | None = [] if "initial_charges" in parent_atoms.arrays else None
    masses: list[float] | None = [] if "masses" in parent_atoms.arrays else None
    parent_magmoms = np.asarray(parent_atoms.arrays["initial_magmoms"]) if magnetic_moments is not None else None
    parent_charges = np.asarray(parent_atoms.arrays["initial_charges"]) if initial_charges is not None else None
    parent_masses = np.asarray(parent_atoms.arrays["masses"]) if masses is not None else None
    atom_id = 0
    for grain_index, grain in enumerate(grains):
        transform = grain["integer_transform"]
        rotation = grain["rotation_cartesian"]
        grain_cell = grain["grain_cell"]
        translation_fractional = np.array(
            [
                grain["in_plane_translation_fractional"][0],
                grain["in_plane_translation_fractional"][1],
                grain["termination_fraction"],
            ],
            dtype=float,
        )
        translation_cartesian = translation_fractional @ grain_cell
        stack_offset = np.zeros(3, dtype=float) if grain_index == 0 else grains[0]["grain_cell"][2].copy()
        for image in grain["images"]:
            for parent_index, parent_position in enumerate(parent_positions):
                unwrapped = (parent_position + image @ parent_cell) @ rotation.T
                translated = unwrapped + translation_cartesian
                fractional = np.linalg.solve(grain_cell.T, translated)
                wrap = np.floor(fractional).astype(np.int64)
                wrapped = translated - wrap @ grain_cell
                effective_image = image - wrap @ transform
                final_position = wrapped + stack_offset
                reconstructed = (
                    (parent_position + effective_image @ parent_cell) @ rotation.T
                    + translation_cartesian
                    + stack_offset
                )
                if not np.allclose(final_position, reconstructed, rtol=0.0, atol=2.0e-8):
                    raise ValueError("grain-boundary atom reconstruction differs from wrapped position")
                symbols.append(str(parent_atoms.get_chemical_symbols()[parent_index]))
                positions.append(final_position)
                grain_ids.append(int(grain["grain_id"]))
                if magnetic_moments is not None:
                    magnetic_moments.append(float(parent_magmoms[parent_index]))
                if initial_charges is not None:
                    initial_charges.append(parent_charges[parent_index].item())
                if masses is not None:
                    masses.append(float(parent_masses[parent_index]))
                lineage.append(
                    {
                        "atom_id": atom_id,
                        "element": symbols[-1],
                        "grain_id": int(grain["grain_id"]),
                        "parent_atom_id": int(parent_ids[parent_index]),
                        "parent_index": int(parent_index),
                        "parent_image": [int(value) for value in image],
                        "effective_parent_image": [int(value) for value in effective_image],
                        "wrap_integer": [int(value) for value in wrap],
                        "integer_transform": transform.tolist(),
                        "rotation_cartesian": rotation.tolist(),
                        "translation_fractional": translation_fractional.tolist(),
                        "translations": {
                            "fractional": translation_fractional.tolist(),
                            "cartesian_angstrom": [float(value) for value in translation_cartesian],
                        },
                        "stack_offset_angstrom": [float(value) for value in stack_offset],
                        "position_reconstruction": [float(value) for value in reconstructed],
                    }
                )
                atom_id += 1

    child = Atoms(symbols=symbols, positions=np.asarray(positions), cell=final_cell, pbc=True)
    child.new_array("atom_id", np.arange(len(child), dtype=np.int64))
    child.new_array("grain_id", np.asarray(grain_ids, dtype=np.int64))
    if magnetic_moments is not None:
        child.new_array("initial_magmoms", np.asarray(magnetic_moments, dtype=float))
    if initial_charges is not None:
        child.new_array("initial_charges", np.asarray(initial_charges, dtype=parent_charges.dtype))
    if masses is not None:
        child.set_masses(np.asarray(masses, dtype=float))
    return child, lineage


def _distance_report(child: Atoms, minimum_distance: float) -> dict[str, Any]:
    atom_ids = np.asarray(child.arrays["atom_id"], dtype=np.int64)
    grain_ids = np.asarray(child.arrays["grain_id"], dtype=np.int64)
    all_distances = np.asarray(child.get_all_distances(mic=True), dtype=float)
    if len(child) > 1:
        upper_i, upper_j = np.triu_indices(len(child), k=1)
        minimum_index = int(np.argmin(all_distances[upper_i, upper_j]))
        distinct_i = int(upper_i[minimum_index])
        distinct_j = int(upper_j[minimum_index])
        distinct_minimum = float(all_distances[distinct_i, distinct_j])
        distinct_pair = {
            "child_atom_ids": [int(atom_ids[distinct_i]), int(atom_ids[distinct_j])]
        }
    else:
        distinct_minimum = None
        distinct_pair = None
    overlap_i, overlap_j, overlap_d, overlap_shift = neighbor_list(
        "ijdS", child, minimum_distance, self_interaction=True
    )
    for i, j, distance, shift in zip(overlap_i, overlap_j, overlap_d, overlap_shift):
        shift_list = [int(value) for value in shift]
        if int(i) == int(j) and not any(shift_list):
            continue
        if float(distance) < minimum_distance:
            raise ValueError(
                "grain-boundary overlap rejected: "
                f"child_atom_ids=({int(atom_ids[i])},{int(atom_ids[j])}), "
                f"grains=({int(grain_ids[i])},{int(grain_ids[j])}), "
                f"image_shift={shift_list}, distance_angstrom={float(distance):.12g}, "
                f"minimum_distance_angstrom={minimum_distance:.12g}"
            )
    return {
        "minimum_distinct_atom_mic_distance_angstrom": distinct_minimum,
        "minimum_distinct_atom_pair": distinct_pair,
        "minimum_self_image_distance_angstrom": None,
        "minimum_self_image": None,
        "self_image_check": (
            "periodic self-images were checked for overlap only at the explicit "
            "threshold with ASE neighbor_list; a full self-image minimum was not computed"
        ),
        "overlap_threshold_angstrom": float(minimum_distance),
    }


def _write_metadata(
    model: ModelArtifacts,
    parent: ModelArtifacts,
    parent_path: str | Path,
    request: dict[str, Any],
    original_request: Any,
    grains: list[dict[str, Any]],
    final_cell: np.ndarray,
    normal: np.ndarray,
    parent_charge: dict[str, Any],
    distance_report: dict[str, Any],
    lineage: list[dict[str, Any]],
) -> None:
    metadata = dict(model.metadata)
    parent_reference = {
        "model_id": parent.model_id,
        "version": parent.version,
        "path": str(Path(parent_path).resolve()),
        "fixture": bool(parent.metadata["fixture"]),
    }
    metadata.update(
        {
            "construction_purpose": "engineering_geometry",
            "spatial_mode": "grain_boundary",
            "selection_status": "engineering_gb_not_user_selected",
            "material_selection_confirmed": False,
            "scientific_status": "engineering_grain_boundary_unrelaxed_not_qualified",
            "production_qualified": False,
            "phase_relaxed": None,
            "parent_models": [parent_reference],
            "parent_model": parent_reference,
            "charge_state": 0,
            "derivation": {
                "kind": "grain_boundary_geometric_neutral_convention",
                "charge_state": 0,
                "parent_charge_state": 0,
                "parent_metadata_charge": parent_charge,
                "source": "explicit engineering_geometry request",
            },
            "charge_contract": {
                "parent_charge_state": 0,
                "charge_state": 0,
                "parent_metadata": parent_charge,
                "neutral_geometric_assumption": True,
            },
            "neutral_geometric_assumption": True,
            "grain_boundary_request": request,
            "grain_boundary_request_normalized": request,
            "grain_boundary_request_original": original_request,
            "grain_boundary_parent_scope": (
                "first_slice_requires_parent_spatial_mode_pristine_and_empty_dopants"
            ),
            "grain_boundary_geometry": {
                "parent_cell_angstrom": np.asarray(parent.atoms.cell.array, dtype=float).tolist(),
                "grain_cells_angstrom": [grain["grain_cell"].tolist() for grain in grains],
                "periodic_cell_angstrom": final_cell.tolist(),
                "boundary_plane_unit_normal_cartesian": normal.tolist(),
                "periodic_interfaces": 2,
                "composition_determinant_sum": int(
                    sum(int(round(float(np.linalg.det(grain["integer_transform"])))) for grain in grains)
                ),
            },
            "atom_lineage": lineage,
            "atom_lineage_file": "atom-lineage.json",
        }
    )
    model.metadata = metadata
    output = Path(model.artifact_dir)
    (output / "model.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    dopants = json.loads((output / "dopants.json").read_text(encoding="utf-8"))
    dopants.update(
        {
            "spatial_mode": "grain_boundary",
            "selection_status": "engineering_gb_not_user_selected",
            "material_selection_confirmed": False,
            "production_qualified": False,
        }
    )
    (output / "dopants.json").write_text(
        json.dumps(dopants, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    geometry_record = {
        "schema": "mlcc.grain-boundary.v1",
        "model_id": model.model_id,
        "version": model.version,
        "parent_model": parent_reference,
        "request": copy.deepcopy(request),
        "request_normalized": copy.deepcopy(request),
        "request_original": copy.deepcopy(original_request),
        "scope": "first_slice_requires_parent_spatial_mode_pristine_and_empty_dopants",
        "geometry": metadata["grain_boundary_geometry"],
        "checks": {
            "periodic_interfaces": 2,
            "composition_parent_atom_count": int(len(parent.atoms)),
            "composition_grain_atom_counts": [
                int(len(parent.atoms) * round(float(np.linalg.det(grain["integer_transform"]))))
                for grain in grains
            ],
            "composition_total_atom_count": int(len(model.atoms)),
            "composition_determinant_sum": int(metadata["grain_boundary_geometry"]["composition_determinant_sum"]),
            "distance": distance_report,
            "scientific_status": metadata["scientific_status"],
            "production_qualified": False,
        },
        "charge": metadata["charge_contract"],
        "atom_lineage_file": "atom-lineage.json",
    }
    (output / "grain-boundary.json").write_text(
        json.dumps(geometry_record, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_grain_boundary(
    parent_path: str | Path,
    request: Mapping[str, Any],
    output_path: str | Path,
) -> ModelArtifacts:
    """Build and persist an explicitly matched two-grain periodic geometry."""

    parent = read_model_artifacts(parent_path)
    _validate_pristine_parent(parent)
    parent_cell = _validate_parent(parent)
    parent_charge = _parent_charge_record(parent.metadata)
    original_request = copy.deepcopy(dict(request))
    normalized_request, grains, final_cell, unit_normal, minimum_distance = _validate_request(
        request, parent_cell
    )
    child, lineage = _build_atoms_and_lineage(parent, grains, final_cell)
    expected_count = int(
        len(parent.atoms)
        * sum(int(round(float(np.linalg.det(grain["integer_transform"])))) for grain in grains)
    )
    if len(child) != expected_count:
        raise ValueError(
            f"grain-boundary composition count mismatch: {len(child)} != determinant sum {expected_count}"
        )
    distance_report = _distance_report(child, minimum_distance)
    material = parent.metadata.get("material")
    parent_perturbation = parent.metadata.get("engineering_perturbation")
    construction = {
        "kind": "grain_boundary_geometry",
        "parent_model": {"model_id": parent.model_id, "version": parent.version},
        "parent_engineering_perturbation": parent_perturbation,
        "request": normalized_request,
    }
    result = write_model_artifacts(
        child,
        output_path,
        model_id=normalized_request["model_id"],
        version=normalized_request["version"],
        fixture=bool(parent.metadata["fixture"]),
        fixture_purpose=parent.metadata.get("fixture_purpose"),
        phase_requested=parent.metadata.get("phase_requested", "parent_phase_inherited"),
        source_path=str(Path(parent_path).resolve()),
        source_version=parent.version,
        engineering_perturbation=construction,
        source_atoms=child,
        material=material,
        source_format="extxyz",
        source_reference=parent.metadata.get("source_reference"),
        selection_status="engineering_gb_not_user_selected",
        material_selection_confirmed=False,
        basis_transform={
            "kind": "grain_boundary",
            "parent_model_id": parent.model_id,
            "parent_model_version": parent.version,
            "grain_cells_angstrom": [grain["grain_cell"].tolist() for grain in grains],
            "periodic_cell_angstrom": final_cell.tolist(),
        },
        atom_lineage=lineage,
        source_original_file=parent.metadata.get("source_original_file"),
        scientific_status="engineering_grain_boundary_unrelaxed_not_qualified",
    )
    _write_metadata(
        result,
        parent,
        parent_path,
        normalized_request,
        original_request,
        grains,
        final_cell,
        unit_normal,
        parent_charge,
        distance_report,
        lineage,
    )
    return result


__all__ = ["build_grain_boundary"]
