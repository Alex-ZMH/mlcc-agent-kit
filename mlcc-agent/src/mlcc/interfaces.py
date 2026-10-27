"""Explicit periodic layered interfaces from two already-oriented models."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from ase import Atoms
from ase.neighborlist import neighbor_list

from .modeling import ModelArtifacts, read_model_artifacts, write_model_artifacts


_REQUEST_SCHEMA = "mlcc.layered-interface-request.v1"
_INTERFACE_SCHEMA = "mlcc.layered-interface.v1"
_TOLERANCE = 1.0e-8


def _cell(value: Any, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (3, 3) or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite 3x3 cell")
    if float(np.linalg.det(result)) <= _TOLERANCE:
        raise ValueError(f"{name} must have a positive right-handed volume")
    return result


def _vector(value: Any, name: str, size: int) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (size,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite length-{size} vector")
    return result


def _repeat(value: Any, name: str) -> np.ndarray:
    result = np.asarray(value)
    if result.shape != (3,):
        raise ValueError(f"{name} must contain three positive integers")
    if any(isinstance(item, (bool, np.bool_)) for item in result.tolist()):
        raise ValueError(f"{name} must contain three positive integers")
    integer = result.astype(np.int64)
    if not np.all(result == integer) or np.any(integer <= 0):
        raise ValueError(f"{name} must contain three positive integers")
    return integer


def _validate_oriented_cell(cell: np.ndarray, name: str) -> None:
    if np.max(np.abs(cell[:2, 2])) > _TOLERANCE:
        raise ValueError(f"{name} a/b vectors must lie in the xy plane")
    if np.max(np.abs(cell[2, :2])) > _TOLERANCE or cell[2, 2] <= _TOLERANCE:
        raise ValueError(f"{name} c vector must be positive along +z")
    if np.linalg.norm(np.cross(cell[0], cell[1])) <= _TOLERANCE:
        raise ValueError(f"{name} a/b vectors must span an in-plane cell")


def _parent_record(side: str, path: str | Path, parent: ModelArtifacts) -> dict[str, Any]:
    metadata = parent.metadata
    return {
        "side": side,
        "model_id": parent.model_id,
        "version": parent.version,
        "path": str(Path(path).resolve()),
        "fixture": bool(metadata.get("fixture", False)),
        "material": metadata.get("material"),
        "phase_requested": metadata.get("phase_requested"),
        "source_reference": metadata.get("source_reference"),
        "source_files": {
            "model": str((Path(path).resolve() / metadata["structure_file"]).resolve()),
            "source": metadata.get("source_original_file"),
        },
    }


def _validate_parent(parent: ModelArtifacts, name: str) -> None:
    if len(parent.atoms) == 0:
        raise ValueError(f"{name} model contains no atoms")
    if not bool(np.all(np.asarray(parent.atoms.pbc, dtype=bool))):
        raise ValueError(f"{name} model must be three-dimensionally periodic")
    source_cell = np.asarray(parent.atoms.cell.array, dtype=float)
    _cell(source_cell, f"{name} model cell")
    _validate_oriented_cell(source_cell, f"{name} model cell")
    if "charge_state" in parent.metadata and parent.metadata["charge_state"] != 0:
        raise ValueError(f"{name} parent metadata charge_state must be neutral")
    if "net_charge" in parent.metadata and parent.metadata["net_charge"] != 0:
        raise ValueError(f"{name} parent metadata net_charge must be neutral")


def _side_request(request: Mapping[str, Any], side: str) -> dict[str, Any]:
    raw = request["sides"][side]
    repeat = _repeat(raw["repeat"], f"sides.{side}.repeat")
    target = _cell(raw["target_cell_angstrom"], f"sides.{side}.target_cell_angstrom")
    _validate_oriented_cell(target, f"sides.{side}.target_cell_angstrom")
    origin = _vector(raw["origin_shift_fractional"], f"sides.{side}.origin_shift_fractional", 3)
    if np.any(origin < 0.0) or np.any(origin >= 1.0):
        raise ValueError(f"sides.{side}.origin_shift_fractional must lie in [0, 1)")
    translation = _vector(
        raw["translation_inplane_angstrom"],
        f"sides.{side}.translation_inplane_angstrom",
        2,
    )
    repeated_cell = repeat[:, None] * target
    return {
        "repeat": repeat,
        "target_cell": target,
        "origin_shift": origin,
        "translation": translation,
        "repeat_cell": repeated_cell,
    }


def _prepare_side(
    side: str,
    parent: ModelArtifacts,
    config: dict[str, Any],
) -> dict[str, Any]:
    source_fractional = parent.atoms.get_scaled_positions(wrap=False)
    parent_ids = np.asarray(parent.atoms.arrays["atom_id"], dtype=np.int64)
    symbols = parent.atoms.get_chemical_symbols()
    raw_positions: list[np.ndarray] = []
    records: list[dict[str, Any]] = []
    repeat = config["repeat"]
    target_cell = config["target_cell"]
    origin = config["origin_shift"]
    translation = config["translation"]
    for image_z in range(int(repeat[2])):
        for image_y in range(int(repeat[1])):
            for image_x in range(int(repeat[0])):
                image = np.asarray([image_x, image_y, image_z], dtype=np.int64)
                for parent_index, fractional in enumerate(source_fractional):
                    cut_fractional = fractional - origin
                    wrapped_fractional = np.mod(cut_fractional, 1.0)
                    repeated_fractional = wrapped_fractional + image
                    position = repeated_fractional @ target_cell
                    position = position + np.asarray([translation[0], translation[1], 0.0])
                    raw_positions.append(position)
                    records.append(
                        {
                            "side": side,
                            "parent_atom_id": int(parent_ids[parent_index]),
                            "parent_index": int(parent_index),
                            "parent_fractional": [float(value) for value in fractional],
                            "cut_fractional": [float(value) for value in cut_fractional],
                            "wrapped_fractional": [float(value) for value in wrapped_fractional],
                            "repeat_image": [int(value) for value in image],
                            "element": str(symbols[parent_index]),
                            "origin_shift_fractional": origin.tolist(),
                            "target_cell_angstrom": target_cell.tolist(),
                            "translation_inplane_angstrom": translation.tolist(),
                            "position_before_layer_offset_angstrom": [float(value) for value in position],
                        }
                    )
    positions = np.asarray(raw_positions, dtype=float)
    minimum_z = float(np.min(positions[:, 2]))
    maximum_z = float(np.max(positions[:, 2]))
    thickness = maximum_z - minimum_z
    for record, position in zip(records, positions):
        record["layer_offset_angstrom"] = [0.0, 0.0, -minimum_z]
        record["position_layer_local_angstrom"] = [
            float(position[0]),
            float(position[1]),
            float(position[2] - minimum_z),
        ]
    return {
        "positions": positions - np.asarray([0.0, 0.0, minimum_z]),
        "records": records,
        "occupied_thickness": thickness,
        "nominal_thickness": float(repeat[2] * target_cell[2, 2]),
    }


def _distance_report(atoms: Atoms, threshold: float) -> dict[str, Any]:
    ids = np.asarray(atoms.arrays["atom_id"], dtype=np.int64)
    sides = np.asarray(atoms.arrays["side_id"], dtype=object)
    indices, partners, distances, shifts = neighbor_list(
        "ijdS", atoms, threshold, self_interaction=True
    )
    for index, partner, distance, shift in zip(indices, partners, distances, shifts):
        shift_values = [int(value) for value in shift]
        if int(index) == int(partner) and not any(shift_values):
            continue
        if float(distance) < threshold:
            raise ValueError(
                "layered-interface overlap rejected: "
                f"child_atom_ids=({int(ids[index])},{int(ids[partner])}), "
                f"sides=({sides[index]},{sides[partner]}), "
                f"image_shift={shift_values}, distance_angstrom={float(distance):.12g}, "
                f"minimum_distance_angstrom={threshold:.12g}"
            )
    return {
        "checked_threshold_angstrom": float(threshold),
        "overlap_violation_count": 0,
        "overlap_checked_with_ase_neighbor_list": True,
    }


def _write_metadata(
    result: ModelArtifacts,
    request: dict[str, Any],
    parent_models: list[dict[str, Any]],
    geometry: dict[str, Any],
    checks: dict[str, Any],
    lineage: list[dict[str, Any]],
    source_arrays: dict[str, Any],
    material_label: str,
) -> None:
    metadata = dict(result.metadata)
    metadata.update(
        {
            "spatial_mode": "layered_interface",
            "interface_file": "layered-interface.json",
            "atom_lineage_file": "atom-lineage.json",
            "atom_lineage": lineage,
            "parent_models": parent_models,
            "material": material_label,
            "material_selection_confirmed": False,
            "selection_status": "engineering_interface_not_user_selected",
            "scientific_status": "engineering_layered_interface_unrelaxed_not_qualified",
            "production_qualified": False,
            "charge_state": 0,
            "boundary": ["p", "p", "p"],
            "interface_request": request,
            "interface_geometry": geometry,
            "interface_checks": checks,
            "source_array_availability": source_arrays,
        }
    )
    result.metadata = metadata
    output = Path(result.artifact_dir)
    (output / "model.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    dopants = json.loads((output / "dopants.json").read_text(encoding="utf-8"))
    dopants.update(
        {
            "spatial_mode": "layered_interface",
            "material": material_label,
            "material_selection_confirmed": False,
            "production_qualified": False,
            "parent_models": parent_models,
        }
    )
    (output / "dopants.json").write_text(
        json.dumps(dopants, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    record = {
        "schema": _INTERFACE_SCHEMA,
        "model_id": result.model_id,
        "version": result.version,
        "construction_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "request": copy.deepcopy(request),
        "parent_models": parent_models,
        "geometry": geometry,
        "checks": checks,
        "atom_lineage_file": "atom-lineage.json",
        "lineage": lineage,
    }
    (output / "layered-interface.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_layered_interface(
    side_a_path: str | Path,
    side_b_path: str | Path,
    request: Mapping[str, Any],
    output_path: str | Path,
) -> ModelArtifacts:
    """Build a periodic interface from two explicitly oriented source models."""

    if request["schema"] != _REQUEST_SCHEMA:
        raise ValueError(f"layered interface request schema must be {_REQUEST_SCHEMA}")
    model_id = request["model_id"]
    version = request["version"]
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("layered interface model_id must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise ValueError("layered interface version must be a non-empty string")
    fixture = request["fixture"]
    if not isinstance(fixture, bool):
        raise ValueError("layered interface fixture must be a boolean")
    fixture_purpose = request["fixture_purpose"]
    if fixture and (not isinstance(fixture_purpose, str) or not fixture_purpose):
        raise ValueError("layered interface fixture_purpose must be a non-empty string")
    if request["charge_state"] != 0:
        raise ValueError("layered interface currently accepts only charge_state=0")
    if request["boundary"] != ["p", "p", "p"]:
        raise ValueError("layered interface requires boundary=['p', 'p', 'p']")
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(str(output))

    side_a = read_model_artifacts(side_a_path)
    side_b = read_model_artifacts(side_b_path)
    if (model_id, version) in {
        (side_a.model_id, side_a.version),
        (side_b.model_id, side_b.version),
    }:
        raise ValueError("layered interface identity must differ from both parent models")
    _validate_parent(side_a, "side a")
    _validate_parent(side_b, "side b")
    for side, parent in (("a", side_a), ("b", side_b)):
        if "initial_charges" in parent.atoms.arrays and not np.allclose(
            np.asarray(parent.atoms.arrays["initial_charges"], dtype=float), 0.0, rtol=0.0, atol=1.0e-12
        ):
            raise ValueError(f"side {side} initial_charges must be zero for atomic/metal geometry")
    config_a = _side_request(request, "a")
    config_b = _side_request(request, "b")
    if not np.allclose(config_a["repeat_cell"][:2], config_b["repeat_cell"][:2], rtol=0.0, atol=_TOLERANCE):
        raise ValueError("side a and side b repeated in-plane cells do not match exactly")
    gap_ab = float(request["gap_ab_angstrom"])
    gap_ba = float(request["gap_ba_angstrom"])
    minimum_distance = float(request["minimum_distance_angstrom"])
    if not np.isfinite(gap_ab) or gap_ab < 0.0:
        raise ValueError("gap_ab_angstrom must be finite and non-negative")
    if not np.isfinite(gap_ba) or gap_ba < 0.0:
        raise ValueError("gap_ba_angstrom must be finite and non-negative")
    if not np.isfinite(minimum_distance) or minimum_distance <= 0.0:
        raise ValueError("minimum_distance_angstrom must be finite and positive")

    prepared_a = _prepare_side("a", side_a, config_a)
    prepared_b = _prepare_side("b", side_b, config_b)
    common_cell = np.asarray(config_a["repeat_cell"], dtype=float)
    total_c = prepared_a["occupied_thickness"] + gap_ab + prepared_b["occupied_thickness"] + gap_ba
    final_cell = np.asarray(
        [common_cell[0], common_cell[1], [0.0, 0.0, total_c]],
        dtype=float,
    )
    positions_a = prepared_a["positions"]
    positions_b = prepared_b["positions"] + np.asarray(
        [0.0, 0.0, prepared_a["occupied_thickness"] + gap_ab]
    )
    symbols_a = [record["element"] for record in prepared_a["records"]]
    symbols_b = [record["element"] for record in prepared_b["records"]]
    symbols = symbols_a + symbols_b
    positions = np.vstack((positions_a, positions_b))
    child = Atoms(symbols=symbols, positions=positions, cell=final_cell, pbc=True)
    child.new_array("atom_id", np.arange(len(child), dtype=np.int64))
    child.new_array("side_id", np.asarray(["a"] * len(symbols_a) + ["b"] * len(symbols_b), dtype="U1"))

    source_arrays: dict[str, Any] = {}
    for array_name in ("initial_magmoms", "initial_charges", "masses"):
        present_a = array_name in side_a.atoms.arrays
        present_b = array_name in side_b.atoms.arrays
        propagated = present_a and present_b
        source_arrays[array_name] = {
            "side_a_present": present_a,
            "side_b_present": present_b,
            "propagated_to_child": propagated,
            "raw_values": {
                "a": side_a.atoms.arrays[array_name].tolist() if present_a else None,
                "b": side_b.atoms.arrays[array_name].tolist() if present_b else None,
            },
        }
        if propagated:
            values = []
            for prepared, parent in ((prepared_a, side_a), (prepared_b, side_b)):
                for record in prepared["records"]:
                    values.append(parent.atoms.arrays[array_name][record["parent_index"]])
            values_array = np.asarray(values)
            if array_name == "masses":
                child.set_masses(np.asarray(values_array, dtype=float))
            else:
                child.new_array(array_name, values_array)

    lineage: list[dict[str, Any]] = []
    for side_index, (prepared, parent, parent_path, offset) in enumerate(
        (
            (prepared_a, side_a, side_a_path, np.asarray([0.0, 0.0, 0.0])),
            (prepared_b, side_b, side_b_path, np.asarray([0.0, 0.0, prepared_a["occupied_thickness"] + gap_ab])),
        )
    ):
        parent_reference = _parent_record("a" if side_index == 0 else "b", parent_path, parent)
        for record in prepared["records"]:
            atom_id = len(lineage)
            position = positions[atom_id]
            entry = dict(record)
            entry.update(
                {
                    "atom_id": atom_id,
                    "parent_model_id": parent.model_id,
                    "parent_model_version": parent.version,
                    "parent_model_path": parent_reference["path"],
                    "stack_offset_angstrom": [float(value) for value in offset],
                    "position_reconstruction_angstrom": [float(value) for value in position],
                }
            )
            lineage.append(entry)

    distance = _distance_report(child, minimum_distance)
    geometry = {
        "cell_angstrom": final_cell.tolist(),
        "area_angstrom2": float(np.linalg.norm(np.cross(final_cell[0], final_cell[1]))),
        "normal_cartesian": [0.0, 0.0, 1.0],
        "thickness": {
            "a": {
                "nominal_angstrom": prepared_a["nominal_thickness"],
                "occupied_angstrom": prepared_a["occupied_thickness"],
            },
            "b": {
                "nominal_angstrom": prepared_b["nominal_thickness"],
                "occupied_angstrom": prepared_b["occupied_thickness"],
            },
        },
        "gaps_angstrom": {"ab": gap_ab, "ba": gap_ba},
        "interface_count": 2,
        "interface_equivalence": "unresolved",
        "target_cells_angstrom": {
            "a": config_a["target_cell"].tolist(),
            "b": config_b["target_cell"].tolist(),
        },
        "repeat": {"a": config_a["repeat"].tolist(), "b": config_b["repeat"].tolist()},
        "origin_shift_fractional": {
            "a": config_a["origin_shift"].tolist(),
            "b": config_b["origin_shift"].tolist(),
        },
        "translation_inplane_angstrom": {
            "a": config_a["translation"].tolist(),
            "b": config_b["translation"].tolist(),
        },
        "deformation_matrices": {
            "a": np.linalg.solve(np.asarray(side_a.atoms.cell.array, dtype=float), config_a["target_cell"]).tolist(),
            "b": np.linalg.solve(np.asarray(side_b.atoms.cell.array, dtype=float), config_b["target_cell"]).tolist(),
        },
    }
    parent_models = [
        _parent_record("a", side_a_path, side_a),
        _parent_record("b", side_b_path, side_b),
    ]
    checks = {
        "atom_count": int(len(child)),
        "side_atom_counts": {"a": int(len(symbols_a)), "b": int(len(symbols_b))},
        "periodic_interfaces": 2,
        "interface_equivalence": "unresolved",
        "distance": distance,
        "source_arrays": source_arrays,
        "charge_state": 0,
        "boundary": ["p", "p", "p"],
        "scientific_status": "engineering_layered_interface_unrelaxed_not_qualified",
        "production_qualified": False,
    }
    material_label = f"{side_a.metadata.get('material', 'unresolved')}+{side_b.metadata.get('material', 'unresolved')}"
    resolved_output = output.resolve()
    if resolved_output in {Path(side_a_path).resolve(), Path(side_b_path).resolve()}:
        raise ValueError("layered interface output must be separate from both parent models")
    result = write_model_artifacts(
        child,
        output,
        model_id=model_id,
        version=version,
        fixture=fixture,
        fixture_purpose=fixture_purpose,
        phase_requested="layered_interface_no_single_space_group",
        source_path=f"{Path(side_a_path).resolve()}|{Path(side_b_path).resolve()}",
        source_version=f"{side_a.model_id}:{side_a.version};{side_b.model_id}:{side_b.version}",
        engineering_perturbation={"kind": "explicit_layered_interface", "request": copy.deepcopy(dict(request))},
        source_atoms=child.copy(),
        material=material_label,
        source_format="extxyz",
        selection_status="engineering_interface_not_user_selected",
        material_selection_confirmed=False,
        basis_transform={"kind": "layered_interface", "geometry": geometry},
        atom_lineage=lineage,
        scientific_status="engineering_layered_interface_unrelaxed_not_qualified",
    )
    _write_metadata(result, dict(request), parent_models, geometry, checks, lineage, source_arrays, material_label)
    return result


__all__ = ["build_layered_interface"]
