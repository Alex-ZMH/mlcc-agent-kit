"""LAMMPS multi-replica NEB input and native-result adapter.

This module is intentionally independent from the ordinary LAMMPS MD task
builder.  It prepares one explicit ``neb``/``fix neb`` calculation using the
same model-data and ASE ``Prism`` conversion as :mod:`mlcc.lammps`, then
parses the master and per-replica native logs without turning an exhausted
iteration budget into a converged result.

The protocol describes an engineering vacancy path.  Image number is a
reaction-coordinate index; it is never interpreted as MD time.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from ase.calculators.lammps import Prism

from .lammps import (
    _validate_potential,
    _model_atoms,
    _native_setup_commands,
    _parse_dump,
    export_lammps_data,
)
from .modeling import ModelArtifacts


NEB_PROTOCOL_SCHEMA = "mlcc.lammps-neb-protocol.v1"
NEB_RESULT_SCHEMA = "mlcc.lammps-neb-result.v1"
METHOD_SCHEMA = "mlcc.lammps-method.v1"


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _positive_int(value: Any, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _finite_number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{name} must be a finite number >= {minimum}")
    return result


def _integer_vector(value: Any, name: str) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{name} must contain three integers")
    return [_integer(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _source_atom_ids(model: ModelArtifacts) -> list[int]:
    atoms, ids = _model_atoms(model)
    if len(ids) != len(set(ids)):
        raise ValueError("LAMMPS NEB model atom IDs must be unique")
    return [int(value) for value in ids]


def validate_neb_protocol(protocol: Mapping[str, Any]) -> None:
    """Validate the explicit, dimensioned NEB request contract."""

    record = _mapping(protocol, "NEB protocol")
    if record.get("schema") != NEB_PROTOCOL_SCHEMA:
        raise ValueError(f"NEB protocol schema must be {NEB_PROTOCOL_SCHEMA}")
    if record.get("kind") != "neb":
        raise ValueError("NEB protocol kind must be 'neb'")
    if record.get("purpose") != "vacancy_migration":
        raise ValueError("NEB protocol purpose must be 'vacancy_migration'")
    endpoint_minimization = _mapping(record.get("endpoint_minimization"), "NEB protocol endpoint_minimization")
    if endpoint_minimization.get("min_style") != "cg":
        raise ValueError("NEB endpoint_minimization.min_style must be cg")
    _finite_number(endpoint_minimization.get("etol"), "NEB endpoint_minimization.etol")
    _finite_number(
        endpoint_minimization.get("ftol_eV_per_angstrom"),
        "NEB endpoint_minimization.ftol_eV_per_angstrom",
    )
    _positive_int(endpoint_minimization.get("max_iterations"), "NEB endpoint_minimization.max_iterations")
    _positive_int(endpoint_minimization.get("max_evaluations"), "NEB endpoint_minimization.max_evaluations")
    images = _positive_int(record.get("images"), "NEB protocol images", minimum=3)
    _positive_int(record.get("ranks_per_image"), "NEB protocol ranks_per_image")
    min_style = _nonempty(record.get("min_style"), "NEB protocol min_style")
    if min_style not in {"quickmin", "fire"}:
        raise ValueError("NEB protocol min_style must be quickmin or fire")
    _finite_number(record.get("timestep_ps"), "NEB protocol timestep_ps", minimum=1.0e-15)
    _finite_number(record.get("etol"), "NEB protocol etol")
    _finite_number(record.get("ftol_eV_per_angstrom"), "NEB protocol ftol_eV_per_angstrom")
    max_iterations = _positive_int(record.get("max_iterations"), "NEB protocol max_iterations")
    climb_iterations = _positive_int(record.get("climb_iterations"), "NEB protocol climb_iterations")
    output_every = _positive_int(record.get("output_every"), "NEB protocol output_every")
    if max_iterations % output_every or climb_iterations % output_every:
        raise ValueError("NEB output_every must divide both iteration limits")
    _finite_number(
        record.get("spring_eV_per_angstrom2"),
        "NEB protocol spring_eV_per_angstrom2",
        minimum=1.0e-15,
    )
    neb_ids = record.get("neb_atom_ids")
    if not isinstance(neb_ids, list) or not neb_ids:
        raise ValueError("NEB protocol neb_atom_ids must be a non-empty list")
    parsed_ids = [_integer(value, "NEB protocol neb_atom_ids entry") for value in neb_ids]
    if len(parsed_ids) != len(set(parsed_ids)) or any(value < 0 for value in parsed_ids):
        raise ValueError("NEB protocol neb_atom_ids must be unique non-negative IDs")
    endpoint_policy = _nonempty(record.get("endpoint_policy"), "NEB protocol endpoint_policy")
    if endpoint_policy not in {"fixed", "relax"}:
        raise ValueError("NEB protocol endpoint_policy must be fixed or relax")
    shifts = record.get("final_image_shifts")
    if not isinstance(shifts, list) or not shifts:
        raise ValueError("NEB protocol final_image_shifts must be a non-empty list")
    shift_ids: list[int] = []
    for index, value in enumerate(shifts):
        item = _mapping(value, f"NEB protocol final_image_shifts[{index}]")
        atom_id = _integer(item.get("atom_id"), f"NEB protocol final_image_shifts[{index}].atom_id")
        if atom_id < 0:
            raise ValueError("NEB final_image_shifts atom IDs must be non-negative")
        _integer_vector(item.get("image"), f"NEB protocol final_image_shifts[{index}].image")
        shift_ids.append(atom_id)
    if len(shift_ids) != len(set(shift_ids)):
        raise ValueError("NEB final_image_shifts must contain each atom ID once")
    _mapping(record.get("path_provenance"), "NEB protocol path_provenance")


def _validate_endpoint_models(initial: ModelArtifacts, final: ModelArtifacts) -> tuple[list[int], dict[int, int], np.ndarray]:
    initial_atoms, initial_ids = _model_atoms(initial)
    final_atoms, final_ids = _model_atoms(final)
    if set(initial_ids) != set(final_ids):
        raise ValueError("NEB endpoints must contain the same stable atom IDs")
    initial_by_id = {int(atom_id): index for index, atom_id in enumerate(initial_ids)}
    final_by_id = {int(atom_id): index for index, atom_id in enumerate(final_ids)}
    if not np.allclose(initial_atoms.cell.array, final_atoms.cell.array, rtol=0.0, atol=1.0e-10):
        raise ValueError("NEB endpoints must use the same periodic cell")
    initial_symbols = initial_atoms.get_chemical_symbols()
    final_symbols = final_atoms.get_chemical_symbols()
    for atom_id in initial_by_id:
        if initial_symbols[initial_by_id[atom_id]] != final_symbols[final_by_id[atom_id]]:
            raise ValueError("NEB endpoints must preserve element identity by stable atom ID")
    return [int(value) for value in initial_ids], final_by_id, np.asarray(initial_atoms.cell.array, dtype=float)


def _restricted_half_length_status(native_delta: Sequence[float], prism: Prism) -> dict[str, Any]:
    """Report the sufficient no-remap condition used by LAMMPS.

    LAMMPS works in restricted-triclinic coordinates and tests z, then y, then
    x with a strict ``> half`` comparison.  This adapter does not reproduce
    that operation (and never uses fractional-coordinate flooring); it records
    only the condition that guarantees an explicit displacement is unchanged.
    """

    values = np.asarray(native_delta, dtype=float)
    if values.shape != (3,) or not np.all(np.isfinite(values)):
        raise ValueError("NEB native displacement must be a finite three-vector")
    xprd, yprd, zprd, _xy, _xz, _yz = (float(value) for value in prism.get_lammps_prism())
    half_lengths = np.asarray([xprd / 2.0, yprd / 2.0, zprd / 2.0], dtype=float)
    within = np.less_equal(np.abs(values), half_lengths)
    return {
        "native_displacement_angstrom": [float(value) for value in values],
        "restricted_half_lengths_angstrom": [float(value) for value in half_lengths],
        "within_restricted_half_lengths": [bool(value) for value in within],
        "minimum_image_unchanged": bool(np.all(within)),
        "minimum_image_axis_order": ["z", "y", "x"],
        "minimum_image_comparison": "strict_greater_than_half_length",
    }


def _endpoint_path_records(
    initial: ModelArtifacts,
    final: ModelArtifacts,
    protocol: Mapping[str, Any],
    *,
    source_ids: Sequence[int],
    final_by_id: Mapping[int, int],
) -> tuple[list[dict[str, Any]], dict[int, np.ndarray], np.ndarray, np.ndarray]:
    """Build source-order endpoint displacements and explicit image shifts."""

    initial_atoms, _initial_ids = _model_atoms(initial)
    final_atoms, _final_ids = _model_atoms(final)
    shifts = {
        int(item["atom_id"]): np.asarray(
            _integer_vector(item["image"], "final_image_shifts.image"), dtype=float
        )
        for item in protocol["final_image_shifts"]
    }
    if set(shifts) != set(source_ids):
        raise ValueError("NEB final_image_shifts must cover every endpoint atom ID exactly")
    # Keep the persisted Cartesian endpoint coordinates verbatim.  LAMMPS
    # performs its own periodic remap on ``read_data``; canonicalising here
    # would silently change the declared endpoint image before native input.
    initial_positions = np.asarray(initial_atoms.positions, dtype=float)
    final_positions = np.asarray(final_atoms.positions, dtype=float)
    cell = np.asarray(initial_atoms.cell.array, dtype=float)
    prism = Prism(cell, pbc=True, reduce_cell=False)
    initial_native = np.asarray(prism.vector_to_lammps(initial_positions), dtype=float)
    final_native = np.asarray(prism.vector_to_lammps(final_positions), dtype=float)
    records: list[dict[str, Any]] = []
    for source_index, atom_id_value in enumerate(source_ids):
        atom_id = int(atom_id_value)
        final_index = int(final_by_id[atom_id])
        image = shifts[atom_id]
        initial_position = np.asarray(initial_positions[source_index], dtype=float)
        final_position = np.asarray(final_positions[final_index], dtype=float)
        selected_final = final_position + image @ cell
        selected_delta = selected_final - initial_position
        selected_final_native = final_native[final_index] + np.asarray(
            prism.vector_to_lammps(image @ cell), dtype=float
        )
        selected_native_delta = selected_final_native - initial_native[source_index]
        records.append(
            {
                "source_atom_id": atom_id,
                "source_index": source_index,
                "image": [int(value) for value in image],
                "initial_position_angstrom": [float(value) for value in initial_atoms.positions[source_index]],
                "initial_source_position_angstrom": [float(value) for value in initial_position],
                "final_position_angstrom": [float(value) for value in final_atoms.positions[final_index]],
                "final_source_position_angstrom": [float(value) for value in final_position],
                "selected_final_position_angstrom": [float(value) for value in selected_final],
                "selected_displacement_angstrom": [float(value) for value in selected_delta],
                "selected_native_final_position_angstrom": [float(value) for value in selected_final_native],
                **_restricted_half_length_status(selected_native_delta, prism),
            }
        )
    return (
        records,
        shifts,
        np.asarray(initial_positions, dtype=float),
        np.asarray(final_positions, dtype=float),
    )


def _image_atoms(
    initial: ModelArtifacts,
    final: ModelArtifacts,
    protocol: Mapping[str, Any],
    *,
    source_ids: Sequence[int],
    final_by_id: Mapping[int, int],
    image_index: int,
) -> tuple[ModelArtifacts, list[dict[str, Any]], dict[str, Any]]:
    """Create one explicit linear-interpolation image in source atom order."""

    records, shifts, initial_positions, final_positions = _endpoint_path_records(
        initial,
        final,
        protocol,
        source_ids=source_ids,
        final_by_id=final_by_id,
    )
    initial_atoms, _ = _model_atoms(initial)
    fraction = float(image_index) / float(int(protocol["images"]) - 1)
    image_atoms = initial_atoms.copy()
    image_positions = np.asarray(initial_positions, dtype=float).copy()
    cell = np.asarray(initial_atoms.cell.array, dtype=float)
    for source_index, atom_id_value in enumerate(source_ids):
        atom_id = int(atom_id_value)
        final_index = int(final_by_id[atom_id])
        target = np.asarray(final_positions[final_index], dtype=float) + shifts[atom_id] @ cell
        image_positions[source_index] = (1.0 - fraction) * initial_positions[source_index] + fraction * target
    image_atoms.positions = image_positions
    image_model = ModelArtifacts(
        initial.model_id,
        initial.version,
        image_atoms,
        dict(initial.metadata),
        initial.artifact_dir,
    )
    image_records: list[dict[str, Any]] = []
    prism = Prism(cell, pbc=True, reduce_cell=False)
    for record in records:
        source_index = int(record["source_index"])
        atom_id = int(record["source_atom_id"])
        final_index = int(final_by_id[atom_id])
        target = np.asarray(final_positions[final_index], dtype=float) + shifts[atom_id] @ cell
        native_start = np.asarray(prism.vector_to_lammps(initial_positions[source_index]), dtype=float)
        native_end = np.asarray(prism.vector_to_lammps(target), dtype=float)
        native_delta = (native_end - native_start) / float(int(protocol["images"]) - 1)
        segment_status = _restricted_half_length_status(native_delta, prism)
        if not segment_status["minimum_image_unchanged"]:
            raise ValueError(
                f"NEB explicit image segment for atom {atom_id} exceeds a restricted-triclinic half length"
            )
        image_record = dict(record)
        image_record.update(
            {
                "image_index": image_index,
                "fraction": fraction,
                "image_position_angstrom": [float(value) for value in image_positions[source_index]],
                "image_native_position_angstrom": [
                    float(value) for value in prism.vector_to_lammps(image_positions[source_index])
                ],
                "adjacent_segment": segment_status,
            }
        )
        image_records.append(image_record)
    return image_model, image_records, {
        "image_index": image_index,
        "fraction": fraction,
        "atom_displacements": image_records,
    }


def _neb_input_text(
    export: Mapping[str, Any],
    potential: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> str:
    atom_map = export["atom_map"]
    masses = atom_map["masses_by_type"]
    native_ids = {
        int(entry["source_atom_id"]): int(entry["lammps_id"])
        for entry in atom_map["atoms"]
    }
    neb_native_ids = [native_ids[int(value)] for value in protocol["neb_atom_ids"]]
    world_ids = " ".join(str(index) for index in range(int(protocol["images"])))
    endpoint = protocol["endpoint_minimization"]
    endpoint_etol = float(endpoint["etol"])
    endpoint_ftol = float(endpoint["ftol_eV_per_angstrom"])
    endpoint_max_iterations = int(endpoint["max_iterations"])
    endpoint_max_evaluations = int(endpoint["max_evaluations"])
    dump_columns = "id type xu yu zu fx fy fz"
    lines = [
        *_native_setup_commands(potential),
        f"variable replica world {world_ids}",
        "units metal",
        "atom_style atomic",
        "atom_modify map array",
        "atom_modify sort 0 0.0",
        "boundary p p p",
        "read_data images/image-${replica}/model.data",
        f"pair_style {potential['pair_style']}",
        *(f"pair_coeff {value}" for value in potential["pair_coeff"]),
        *(f"mass {type_id} {float(masses[type_id]):.12g}" for type_id in sorted(masses, key=int)),
        f"group neb_atoms id {' '.join(str(value) for value in neb_native_ids)}",
        f"timestep {float(protocol['timestep_ps']):.16g}",
        f"thermo {int(protocol['output_every'])}",
        "thermo_style custom step pe",
        "thermo_modify norm no",
        "min_style cg",
        "min_modify norm two",
        f"shell mkdir -p images/image-${{replica}}",
        f"partition yes 1 minimize {endpoint_etol:.16g} {endpoint_ftol:.16g} {endpoint_max_iterations} {endpoint_max_evaluations}",
        f"partition yes {int(protocol['images'])} minimize {endpoint_etol:.16g} {endpoint_ftol:.16g} {endpoint_max_iterations} {endpoint_max_evaluations}",
        f"partition yes 1 write_dump all custom images/image-${{replica}}/endpoint-final.lammpstrj {dump_columns} modify sort id format float %.16g",
        f"partition yes {int(protocol['images'])} write_dump all custom images/image-${{replica}}/endpoint-final.lammpstrj {dump_columns} modify sort id format float %.16g",
        "reset_timestep 0",
        "velocity all set 0.0 0.0 0.0",
        f"min_style {protocol['min_style']}",
        "min_modify norm two",
        f"fix neb neb_atoms neb {float(protocol['spring_eV_per_angstrom2']):.16g} parallel neigh",
    ]
    if protocol["endpoint_policy"] == "fixed":
        lines.extend(
            [
                "partition yes 1 fix neb_endpoint_start all setforce 0.0 0.0 0.0",
                f"partition yes {int(protocol['images'])} fix neb_endpoint_final all setforce 0.0 0.0 0.0",
            ]
        )
    lines.extend(
        [
            f"neb {float(protocol['etol']):.16g} {float(protocol['ftol_eV_per_angstrom']):.16g} "
            f"{int(protocol['max_iterations'])} {int(protocol['climb_iterations'])} "
            f"{int(protocol['output_every'])} none verbosity verbose",
            f"write_dump all custom images/image-${{replica}}/final.lammpstrj {dump_columns} modify sort id format float %.16g",
        ]
    )
    return "\n".join(lines) + "\n"


def prepare_lammps_neb(
    initial_model: ModelArtifacts,
    final_model: ModelArtifacts,
    directory: str | Path,
    *,
    potential: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Write one explicit multi-replica LAMMPS NEB input bundle."""

    if not isinstance(initial_model, ModelArtifacts) or not isinstance(final_model, ModelArtifacts):
        raise TypeError("LAMMPS NEB requires persisted initial and final ModelArtifacts")
    validate_neb_protocol(protocol)
    source_ids, final_by_id, cell = _validate_endpoint_models(initial_model, final_model)
    initial_atoms, _ = _model_atoms(initial_model)
    if set(int(value) for value in protocol["neb_atom_ids"]) - set(source_ids):
        raise ValueError("NEB protocol neb_atom_ids contains an unknown source atom ID")
    _validate_potential(
        potential,
        model_id=initial_model.model_id,
        model_elements=initial_atoms.get_chemical_symbols(),
        element_order=[str(value) for value in potential["element_order"]],
        units="metal",
        atom_style="atomic",
        protocol=protocol,
    )
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    element_order = [str(value) for value in potential["element_order"]]
    export = export_lammps_data(
        initial_model,
        output,
        element_order=element_order,
        units="metal",
        atom_style="atomic",
    )
    path_records, _shifts, _initial_source, _final_source = _endpoint_path_records(
        initial_model,
        final_model,
        protocol,
        source_ids=source_ids,
        final_by_id=final_by_id,
    )
    image_data_paths: list[str] = []
    image_maps: list[str] = []
    image_metadata: list[dict[str, Any]] = []
    images_root = output / "images"
    images_root.mkdir(parents=True, exist_ok=True)
    for image_index in range(int(protocol["images"])):
        image_directory = images_root / f"image-{image_index}"
        image_model, image_records, image_record = _image_atoms(
            initial_model,
            final_model,
            protocol,
            source_ids=source_ids,
            final_by_id=final_by_id,
            image_index=image_index,
        )
        image_export = export_lammps_data(
            image_model,
            image_directory,
            element_order=element_order,
            units="metal",
            atom_style="atomic",
        )
        if image_export["atom_map"] != export["atom_map"]:
            raise ValueError(f"NEB image {image_index} atom map differs from the common atom map")
        image_data_paths.append(str(image_directory / "model.data"))
        image_maps.append(str(image_directory / "atom-map.json"))
        image_record["model_data"] = str(image_directory / "model.data")
        image_record["atom_map"] = str(image_directory / "atom-map.json")
        image_record["atom_displacements"] = image_records
        image_metadata.append(image_record)
    input_path = output / "in.lammps"
    input_path.write_text(_neb_input_text(export, potential, protocol), encoding="utf-8", newline="\n")
    method_path = output / "method.json"
    image_final_dumps = [
        str(images_root / f"image-{index}" / "final.lammpstrj")
        for index in range(int(protocol["images"]))
    ]
    image_endpoint_dumps = {
        "initial": str(images_root / "image-0" / "endpoint-final.lammpstrj"),
        "final": str(images_root / f"image-{int(protocol['images']) - 1}" / "endpoint-final.lammpstrj"),
    }
    method = {
        "schema": METHOD_SCHEMA,
        "engine": "lammps",
        "model_id": initial_model.model_id,
        "version": initial_model.version,
        "final_model_id": final_model.model_id,
        "final_version": final_model.version,
        "units": "metal",
        "atom_style": "atomic",
        "element_order": [str(value) for value in potential["element_order"]],
        "potential": dict(potential),
        "protocol": dict(protocol),
        "production_qualification": False,
        "endpoint_displacements": path_records,
        "path_provenance": dict(protocol["path_provenance"]),
        "files": {
            "model.data": str(output / "model.data"),
            "atom-map.json": str(output / "atom-map.json"),
            "in.lammps": str(input_path),
            "method.json": str(method_path),
            "log.lammps": str(output / "log.lammps"),
            "image_atom_maps": image_maps,
            "image_data": image_data_paths,
            "image_dumps": image_final_dumps,
            "endpoint_dumps": image_endpoint_dumps,
            "image_logs": [str(output / f"log.lammps.{index}") for index in range(int(protocol["images"]))],
        },
    }
    method_path.write_text(json.dumps(method, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    neb_input = {
        "schema": "mlcc.lammps-neb-input.v1",
        "initial_model": {"model_id": initial_model.model_id, "version": initial_model.version},
        "final_model": {"model_id": final_model.model_id, "version": final_model.version},
        "images": int(protocol["images"]),
        "ranks_per_image": int(protocol["ranks_per_image"]),
        "endpoint_policy": protocol["endpoint_policy"],
        "endpoint_minimization": dict(protocol["endpoint_minimization"]),
        "path_provenance": dict(protocol["path_provenance"]),
        "image_records": image_metadata,
        "neb_atom_ids": [int(value) for value in protocol["neb_atom_ids"]],
        "atom_map_path": str(output / "atom-map.json"),
        "source_cell_angstrom": cell.tolist(),
        "reaction_coordinate_is_time": False,
        "time_ps": None,
    }
    (output / "neb-input.json").write_text(json.dumps(neb_input, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    transfer_paths = [
        "model.data",
        "atom-map.json",
        "in.lammps",
        "method.json",
        "neb-input.json",
        *[f"images/image-{index}/model.data" for index in range(int(protocol["images"]))],
        *[f"images/image-{index}/atom-map.json" for index in range(int(protocol["images"]))],
    ]
    collect_paths = [
        "stdout.log",
        "stderr.log",
        "log.lammps",
        *[f"log.lammps.{index}" for index in range(int(protocol["images"]))],
        *[f"images/image-{index}/endpoint-final.lammpstrj" for index in (0, int(protocol["images"]) - 1)],
        *[f"images/image-{index}/final.lammpstrj" for index in range(int(protocol["images"]))],
    ]
    return {
        "schema": "mlcc.lammps-neb-input.v1",
        "method_path": str(method_path),
        "input_path": str(input_path),
        "atom_map_path": str(output / "atom-map.json"),
        "neb_input_path": str(output / "neb-input.json"),
        "image_data_paths": image_data_paths,
        "image_atom_map_paths": image_maps,
        "image_final_dump_paths": image_final_dumps,
        "image_endpoint_dump_paths": image_endpoint_dumps,
        "files": transfer_paths,
        "transfer_paths": transfer_paths,
        "collect_paths": collect_paths,
        "output_files": [*transfer_paths, *collect_paths],
        "potential": dict(potential),
        "protocol": dict(protocol),
        "production_qualification": False,
    }


_MASTER_HEADER_PREFIX = ("Step", "MaxReplicaForce", "MaxAtomForce", "GradV0", "GradV1", "GradVc", "EBF", "EBR", "RDT")


def _master_header_key(name: str) -> str:
    explicit = {
        "MaxReplicaForce": "max_replica_force",
        "MaxAtomForce": "max_atom_force",
        "GradV0": "gradient_initial",
        "GradV1": "gradient_final",
        "GradVc": "gradient_climbing",
        "gradV0": "gradv0",
        "gradV1": "gradv1",
        "gradVc": "gradvc",
        "EBF": "ebf",
        "EBR": "ebr",
        "RDT": "rdt",
    }
    if name in explicit:
        return explicit[name]
    image_match = re.fullmatch(r"(RD|PE)(\d+)", name)
    if image_match:
        return image_match.group(1).lower() + image_match.group(2)
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _float_token(token: str, *, allow_nan: bool = False) -> float | None:
    if allow_nan and token.strip().lower() == "undefined":
        return None
    value = float(token)
    if not math.isfinite(value):
        if allow_nan and math.isnan(value):
            return None
        raise ValueError("LAMMPS NEB native output contains a non-finite required value")
    return value


def _parse_master_history(text: str, images: int) -> tuple[dict[str, list[dict[str, Any]]], int | None]:
    lines = text.splitlines()
    phases: dict[str, list[dict[str, Any]]] = {"regular": [], "climbing": []}
    phase = "regular"
    climbing_replica: int | None = None
    headers: list[str] | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = re.search(r"Climbing replica\s*=\s*(\d+)", stripped, flags=re.IGNORECASE)
        if match:
            climbing_replica = int(match.group(1))
            phase = "climbing"
            headers = None
            continue
        tokens = stripped.split()
        if len(tokens) >= len(_MASTER_HEADER_PREFIX) and tuple(tokens[: len(_MASTER_HEADER_PREFIX)]) == _MASTER_HEADER_PREFIX:
            headers = tokens
            continue
        if headers is None or not tokens or len(tokens) != len(headers):
            continue
        if not re.fullmatch(r"[+-]?\d+", tokens[0]):
            continue
        step = int(tokens[0])
        row: dict[str, Any] = {
            "step": step,
            "raw_line": line,
            "raw_header": list(headers),
            "raw_tokens": {},
        }
        for name, token in zip(headers[1:], tokens[1:]):
            key = _master_header_key(name)
            allow_nan = key.startswith(("pathangle", "angletangrad", "anglegrad"))
            row[key] = _float_token(token, allow_nan=allow_nan)
            row["raw_tokens"][key] = token
        image_energy = [f"pe{index}" for index in range(1, images + 1)]
        image_rd = [f"rd{index}" for index in range(1, images + 1)]
        observed_image_keys = {key for key in row if re.fullmatch(r"(?:pe|rd)\d+", key)}
        if observed_image_keys != set((*image_energy, *image_rd)):
            raise ValueError("LAMMPS NEB history image count differs from protocol")
        required = [
            "max_replica_force",
            "max_atom_force",
            "gradient_initial",
            "gradient_final",
            "gradient_climbing",
            "ebf",
            "ebr",
            "rdt",
            *image_energy,
            *image_rd,
        ]
        if any(key not in row or row[key] is None for key in required):
            raise ValueError("LAMMPS NEB master history is missing a finite required field")
        phases[phase].append(row)
    if not phases["regular"] or not phases["climbing"]:
        raise ValueError("LAMMPS NEB master log must contain regular and climbing histories")
    if climbing_replica is None or not 1 <= climbing_replica <= images:
        raise ValueError("LAMMPS NEB master log has no valid native climbing replica")
    return phases, climbing_replica


def _parse_minimization_stats(text: str, *, image_index: int) -> list[dict[str, Any]]:
    lines = text.splitlines()
    records: list[dict[str, Any]] = []
    starts = [index for index, line in enumerate(lines) if "Minimization stats:" in line]
    for start_index, index in enumerate(starts):
        block_end = starts[start_index + 1] if start_index + 1 < len(starts) else len(lines)
        block = lines[index:block_end]
        stopping = next((item.split("=", 1)[1].strip() for item in block if "Stopping criterion" in item and "=" in item), None)
        iteration_values = None
        for line_index, item in enumerate(block):
            if "Iterations, force evaluations" not in item:
                continue
            candidate = item.split("=", 1)[1].split() if "=" in item else []
            if len(candidate) < 2 and line_index + 1 < len(block):
                candidate = block[line_index + 1].split()
            iteration_values = candidate
            break
        force_line = None
        energy_line = None
        force_max_line = None
        for line_index, item in enumerate(block):
            if "Force two-norm initial, final" in item and "=" in item:
                candidate = item.split("=", 1)[1].split()
                if len(candidate) < 2 and line_index + 1 < len(block):
                    candidate = block[line_index + 1].split()
                force_line = candidate
            if "Force max component initial, final" in item and "=" in item:
                candidate = item.split("=", 1)[1].split()
                if len(candidate) < 2 and line_index + 1 < len(block):
                    candidate = block[line_index + 1].split()
                force_max_line = candidate
            if "Energy initial, next-to-last, final" in item and "=" in item:
                candidate = item.split("=", 1)[1].split()
                if len(candidate) < 3 and line_index + 1 < len(block):
                    candidate = block[line_index + 1].split()
                energy_line = candidate
        if stopping is None or iteration_values is None or force_line is None or force_max_line is None or energy_line is None:
            continue
        if len(iteration_values) < 2 or len(force_line) < 2 or len(force_max_line) < 2 or len(energy_line) < 3:
            continue
        numeric_values = [*energy_line[:3], *force_line[:2], *force_max_line[:2]]
        parsed_values = [float(value) for value in numeric_values]
        if not all(math.isfinite(value) for value in parsed_values):
            raise ValueError("LAMMPS NEB minimization stats contain non-finite values")
        if not re.fullmatch(r"[+-]?\d+", iteration_values[0]) or not re.fullmatch(r"[+-]?\d+", iteration_values[1]):
            raise ValueError("LAMMPS NEB minimization iterations are not integer")
        iterations_value = int(iteration_values[0])
        force_evaluations = int(iteration_values[1])
        records.append(
            {
                "image_index": image_index,
                "stopping_criterion": stopping,
                "iterations": iterations_value,
                "force_evaluations": force_evaluations,
                "energy_initial_eV": parsed_values[0],
                "energy_next_to_last_eV": parsed_values[1],
                "energy_final_eV": parsed_values[2],
                "force_two_norm_initial_eV_per_angstrom": parsed_values[3],
                "force_two_norm_final_eV_per_angstrom": parsed_values[4],
                "force_max_initial_eV_per_angstrom": parsed_values[5],
                "force_max_final_eV_per_angstrom": parsed_values[6],
                "raw_tokens": {
                    "stopping_criterion": stopping,
                    "iterations": iteration_values[0],
                    "force_evaluations": iteration_values[1],
                    "energy": list(energy_line[:3]),
                    "force_two_norm": list(force_line[:2]),
                    "force_max_component": list(force_max_line[:2]),
                },
                "raw_block": "\n".join(block),
            }
        )
    return records


def _converged_stop(value: str, *, etol: float, ftol: float) -> bool:
    text = " ".join(value.lower().split())
    if text == "energy tolerance":
        return float(etol) > 0.0
    if text == "force tolerance":
        return float(ftol) > 0.0
    return False


def _engine_version_from_logs(texts: Sequence[str]) -> str | None:
    versions: list[str] = []
    for text in texts:
        for line in text.splitlines():
            match = re.search(r"^\s*(LAMMPS\s*\([^\n]+\))\s*$", line)
            if match:
                versions.append(match.group(1).strip())
                break
    if not versions:
        raise ValueError("LAMMPS NEB native logs have no engine version banner")
    if len(set(versions)) != 1:
        raise ValueError("LAMMPS NEB native logs report inconsistent engine banners")
    return versions[0]


def _validate_neb_input_binding(
    input_text: str,
    atom_map: Mapping[str, Any],
    potential: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    """Check the saved input against the same command writer used at prepare time."""

    expected = _neb_input_text({"atom_map": atom_map}, potential, protocol)
    prepared_lines = [line.strip() for line in input_text.splitlines() if line.strip()]
    expected_lines = [line.strip() for line in expected.splitlines() if line.strip()]
    cursor = -1
    for command in expected_lines:
        try:
            cursor = prepared_lines.index(command, cursor + 1)
        except ValueError as error:
            raise ValueError(f"LAMMPS NEB input is missing or reorders prepared command: {command}") from error


def _validate_neb_native_echo(
    partition_logs: Sequence[str],
    atom_map: Mapping[str, Any],
    potential: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    """Bind every partition's echoed native commands to the prepared values."""
    expected_lines = [
        line.strip()
        for line in _neb_input_text({"atom_map": atom_map}, potential, protocol).splitlines()
        if line.strip()
    ]
    required = [
        "units metal",
        "atom_style atomic",
        "min_style cg",
        f"min_style {protocol['min_style']}",
        f"fix neb neb_atoms neb {float(protocol['spring_eV_per_angstrom2']):.16g} parallel neigh",
        (
            f"neb {float(protocol['etol']):.16g} {float(protocol['ftol_eV_per_angstrom']):.16g} "
            f"{int(protocol['max_iterations'])} {int(protocol['climb_iterations'])} "
            f"{int(protocol['output_every'])} none verbosity verbose"
        ),
    ]
    for image_index, text in enumerate(partition_logs):
        lines = [line.strip() for line in text.splitlines()]
        expanded = [line.replace("${replica}", str(image_index)) for line in lines]
        for command in required:
            if command not in lines and command not in expanded:
                raise ValueError(f"LAMMPS NEB partition log {image_index} is missing native command: {command}")
        read_data = f"read_data images/image-{image_index}/model.data"
        if read_data not in lines and "read_data images/image-${replica}/model.data" not in lines:
            raise ValueError(f"LAMMPS NEB partition log {image_index} is missing its image read_data command")
    if not expected_lines:
        raise ValueError("LAMMPS NEB prepared input has no native commands")


def parse_lammps_neb_outputs(directory: str | Path) -> dict[str, Any]:
    """Parse saved native master/per-image NEB output and preserve stop state."""

    output = Path(directory)
    method_path = output / "method.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    if method.get("schema") != METHOD_SCHEMA:
        raise ValueError(f"LAMMPS NEB method schema must be {METHOD_SCHEMA}")
    if method.get("production_qualification") is not False:
        raise ValueError("LAMMPS NEB method production_qualification must remain false")
    protocol = _mapping(method.get("protocol"), "method.protocol")
    validate_neb_protocol(protocol)
    atom_map = json.loads((output / "atom-map.json").read_text(encoding="utf-8"))
    map_source_ids = {int(value) for value in atom_map["source_atom_ids"]}
    shift_source_ids = {int(item["atom_id"]) for item in protocol["final_image_shifts"]}
    if shift_source_ids != map_source_ids:
        raise ValueError("NEB final_image_shifts must cover every atom ID in atom-map.json")
    if not set(int(value) for value in protocol["neb_atom_ids"]).issubset(map_source_ids):
        raise ValueError("NEB protocol neb_atom_ids contains an unknown atom-map source ID")
    _validate_potential(
        method.get("potential"),
        model_id=str(method["model_id"]),
        model_elements=[str(entry["element"]) for entry in atom_map["atoms"]],
        element_order=[str(value) for value in method["element_order"]],
        units=str(method["units"]),
        atom_style=str(method["atom_style"]),
        protocol=protocol,
    )
    input_path = output / "in.lammps"
    input_text = input_path.read_text(encoding="utf-8")
    _validate_neb_input_binding(input_text, atom_map, method.get("potential"), protocol)
    log_path = output / "log.lammps"
    log_text = log_path.read_text(encoding="utf-8")
    if any(re.search(r"\bERROR\b", line, flags=re.IGNORECASE) for line in log_text.splitlines()):
        error_line = next(line for line in log_text.splitlines() if re.search(r"\bERROR\b", line, flags=re.IGNORECASE))
        raise RuntimeError(error_line)
    phases, climbing_replica = _parse_master_history(log_text, int(protocol["images"]))
    stopping: list[dict[str, Any]] = []
    partition_log_texts: list[str] = []
    for image_index in range(int(protocol["images"])):
        path = output / f"log.lammps.{image_index}"
        if not path.exists():
            raise FileNotFoundError(path)
        partition_log_text = path.read_text(encoding="utf-8")
        if any(re.search(r"\bERROR\b", line, flags=re.IGNORECASE) for line in partition_log_text.splitlines()):
            error_line = next(line for line in partition_log_text.splitlines() if re.search(r"\bERROR\b", line, flags=re.IGNORECASE))
            raise RuntimeError(error_line)
        partition_log_texts.append(partition_log_text)
        image_records = _parse_minimization_stats(partition_log_text, image_index=image_index)
        expected_blocks = 3 if image_index in {0, int(protocol["images"]) - 1} else 2
        if len(image_records) != expected_blocks:
            expected_word = "three" if expected_blocks == 3 else "two"
            raise ValueError(
                f"LAMMPS NEB partition log {path} must contain exactly {expected_word} minimization stats blocks"
            )
        for block_index, record in enumerate(image_records):
            record["phase"] = (
                "endpoint"
                if expected_blocks == 3 and block_index == 0
                else ("regular" if (block_index == expected_blocks - 2) else "climbing")
            )
        stopping.extend(image_records)
    _validate_neb_native_echo(partition_log_texts, atom_map, method.get("potential"), protocol)
    records_by_image: dict[int, list[dict[str, Any]]] = {}
    for record in stopping:
        records_by_image.setdefault(int(record["image_index"]), []).append(record)
    endpoint_stops = [records_by_image[index][0] for index in (0, int(protocol["images"]) - 1)]
    regular_stops = [records_by_image[index][-2] for index in range(int(protocol["images"]))]
    climbing_stops = [records_by_image[index][-1] for index in range(int(protocol["images"]))]
    endpoint_settings = protocol["endpoint_minimization"]
    phase_converged = {
        "endpoint": bool(endpoint_stops)
        and all(
            _converged_stop(
                str(item["stopping_criterion"]),
                etol=float(endpoint_settings["etol"]),
                ftol=float(endpoint_settings["ftol_eV_per_angstrom"]),
            )
            for item in endpoint_stops
        ),
        "regular": bool(regular_stops)
        and all(
            _converged_stop(
                str(item["stopping_criterion"]),
                etol=float(protocol["etol"]),
                ftol=float(protocol["ftol_eV_per_angstrom"]),
            )
            for item in regular_stops
        ),
        "climbing": bool(climbing_stops)
        and all(
            _converged_stop(
                str(item["stopping_criterion"]),
                etol=float(protocol["etol"]),
                ftol=float(protocol["ftol_eV_per_angstrom"]),
            )
            for item in climbing_stops
        ),
    }
    final_row = phases["climbing"][-1]
    image_energy = [float(final_row[f"pe{index}"]) for index in range(1, int(protocol["images"]) + 1)]
    highest_image = int(np.argmax(np.asarray(image_energy, dtype=float))) + 1
    highest_is_endpoint = highest_image in {1, int(protocol["images"])}
    climbing_image_energy = float(final_row[f"pe{int(climbing_replica)}"])
    image_dumps: list[dict[str, Any]] = []
    endpoint_dumps: list[dict[str, Any]] = []
    climbing_final_step = int(phases["climbing"][-1]["step"])
    source_entries = sorted(atom_map["atoms"], key=lambda item: int(item["source_index"]))
    source_by_lammps_id = {int(item["lammps_id"]): item for item in source_entries}
    source_cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    source_prism = Prism(source_cell, pbc=True, reduce_cell=False)
    for image_index in range(int(protocol["images"])):
        image_directory = output / "images" / f"image-{image_index}"
        image_map_path = image_directory / "atom-map.json"
        if not image_map_path.exists():
            raise FileNotFoundError(image_map_path)
        image_map = json.loads(image_map_path.read_text(encoding="utf-8"))
        if image_map != atom_map:
            raise ValueError(f"NEB image atom map differs from the common atom map: {image_map_path}")
        image_data_path = image_directory / "model.data"
        if not image_data_path.exists():
            raise FileNotFoundError(image_data_path)
        dump_path = image_directory / "final.lammpstrj"
        if not dump_path.exists():
            raise FileNotFoundError(dump_path)
        step, rows = _parse_dump(dump_path.read_text(encoding="utf-8"), atom_map, coordinate_columns=("xu", "yu", "zu"))
        if step != climbing_final_step:
            raise ValueError(f"NEB image dump step differs from the final climbing step: {dump_path}")
        final_image_index = image_index + 1
        image_dumps.append(
            {
                "image_index": image_index,
                "step": step,
                "path": str(dump_path),
                "reaction_coordinate": float(final_row[f"rd{final_image_index}"]),
                "energy_eV": float(final_row[f"pe{final_image_index}"]),
                "source_atom_ids": [int(source_by_lammps_id[int(row[0])]["source_atom_id"]) for row in rows],
                "source_cell_angstrom": source_cell.tolist(),
                "atom_map_file": str(image_map_path),
                "time_ps": None,
                "mode": "neb_path",
                "force_role": "native_force_with_NEB_and_endpoint_constraints",
                "atom_ids": [int(row[0]) for row in rows],
                "rows": [
                    {
                        "lammps_id": int(row[0]),
                        "source_atom_id": int(source_by_lammps_id[int(row[0])]["source_atom_id"]),
                        "type": int(row[1]),
                        "positions_lammps_angstrom": [float(value) for value in row[2]],
                        "positions_angstrom": [
                            float(value)
                            for value in source_prism.vector_to_ase(np.asarray(row[2], dtype=float), wrap=False)
                        ],
                        "forces_eV_per_angstrom": [float(value) for value in row[3]],
                        "forces_source_eV_per_angstrom": [
                            float(value)
                            for value in source_prism.vector_to_ase(np.asarray(row[3], dtype=float), wrap=False)
                        ],
                    }
                    for row in rows
                ],
                "force_semantics": "native_total_including_fix_neb",
            }
        )
        if image_index in {0, int(protocol["images"]) - 1}:
            for stage in ("endpoint-final",):
                endpoint_path = image_directory / f"{stage}.lammpstrj"
                if not endpoint_path.exists():
                    raise FileNotFoundError(endpoint_path)
                endpoint_step, endpoint_rows = _parse_dump(
                    endpoint_path.read_text(encoding="utf-8"),
                    atom_map,
                    coordinate_columns=("xu", "yu", "zu"),
                )
                endpoint_dumps.append(
                    {
                        "image_index": image_index,
                        "stage": stage,
                        "step": endpoint_step,
                        "path": str(endpoint_path),
                        "atom_ids": [int(row[0]) for row in endpoint_rows],
                    }
                )
    path_endpoint_converged = bool(phase_converged["endpoint"])
    native_converged = bool(phase_converged["climbing"])
    stop_reason = "climbing_phase_met_declared_tolerance" if native_converged else "iteration_or_native_stop_not_converged"
    return {
        "schema": NEB_RESULT_SCHEMA,
        "engine": "lammps",
        "model_id": method["model_id"],
        "version": method["version"],
        "final_model_id": method.get("final_model_id"),
        "final_version": method.get("final_version"),
        "engine_version": _engine_version_from_logs([log_text, *partition_log_texts]),
        "units": method["units"],
        "atom_style": method["atom_style"],
        "protocol": dict(protocol),
        "path_provenance": protocol.get("path_provenance"),
        "images": int(protocol["images"]),
        "endpoint_displacements": method.get("endpoint_displacements", []),
        "potential": method.get("potential"),
        "mode": "neb_path",
        "time_ps": None,
        "history": {phase: rows for phase, rows in phases.items()},
        "stopping": {
            "records": stopping,
            "regular": regular_stops,
            "climbing": climbing_stops,
            "endpoint": endpoint_stops,
            "phase_converged": phase_converged,
            "reason": stop_reason,
        },
        "barrier": {
            "forward_eV": float(final_row["ebf"]),
            "backward_eV": float(final_row["ebr"]),
            "highest_final_image": highest_image,
            "highest_final_image_zero_based": highest_image - 1,
            "highest_final_image_energy_eV": float(final_row[f"pe{highest_image}"]),
            "highest_final_image_is_endpoint": highest_is_endpoint,
            "climbing_replica": climbing_replica,
            "climbing_replica_zero_based": None if climbing_replica is None else climbing_replica - 1,
            "climbing_replica_energy_eV": climbing_image_energy,
            "climbing_replica_is_endpoint": climbing_replica in {1, int(protocol["images"])},
            "highest_image_is_climbing_replica": climbing_replica == highest_image,
            "internal_saddle_candidate": not highest_is_endpoint,
        },
        "regular_native_converged": phase_converged["regular"],
        "climbing_native_converged": phase_converged["climbing"],
        "path_endpoint_converged": path_endpoint_converged,
        "native_converged": native_converged,
        "scientific_status": "neb_native_converged" if native_converged else "neb_native_unconverged",
        "production_qualification": False,
        "atom_map": str(output / "atom-map.json"),
        "image_dumps": image_dumps,
        "endpoint_dumps": endpoint_dumps,
        "source_files": {
            "method.json": str(method_path),
            "atom-map.json": str(output / "atom-map.json"),
            "in.lammps": str(input_path),
            "log.lammps": str(log_path),
            "image_atom_maps": [
                str(output / "images" / f"image-{index}" / "atom-map.json")
                for index in range(int(protocol["images"]))
                if (output / "images" / f"image-{index}" / "atom-map.json").exists()
            ],
            "image_data": [
                str(output / "images" / f"image-{index}" / "model.data")
                for index in range(int(protocol["images"]))
                if (output / "images" / f"image-{index}" / "model.data").exists()
            ],
            "image_logs": [str(output / f"log.lammps.{index}") for index in range(int(protocol["images"])) if (output / f"log.lammps.{index}").exists()],
            "image_dumps": [
                str(output / "images" / f"image-{index}" / "final.lammpstrj")
                for index in range(int(protocol["images"]))
            ],
            "endpoint_dumps": [item["path"] for item in endpoint_dumps],
        },
    }


__all__ = [
    "NEB_PROTOCOL_SCHEMA",
    "NEB_RESULT_SCHEMA",
    "parse_lammps_neb_outputs",
    "prepare_lammps_neb",
    "validate_neb_protocol",
]
