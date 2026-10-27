"""Thin LAMMPS data, input, and native-result adapter.

This module owns the small LAMMPS surface needed by the MLCC engineering
fixture.  It deliberately supports only ``units metal`` with ``atom_style
atomic``.  ASE's LAMMPS ``Prism`` performs the Cartesian rotation for a
triclinic cell; the atom map records that rotation and the stable source atom
IDs used for the LAMMPS 1-based IDs.

The potential and protocol are caller-owned explicit records.  This adapter
does not copy potential files, infer a potential, add charges, assign a
temperature or seed, or grant production qualification.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
from pathlib import Path
import math
from typing import Any

import numpy as np
from ase import Atoms
from ase.calculators.lammps import Prism
from ase.data import atomic_numbers
from ase.io.lammpsdata import read_lammps_data, write_lammps_data

from .modeling import ModelArtifacts


LAMMPS_UNITS = "metal"
LAMMPS_ATOM_STYLE = "atomic"
_THERMO_FIELDS = ("Step", "Temp", "PotEng", "KinEng", "TotEng", "Press")
_PRESSURE_FIELDS = ("Pxx", "Pyy", "Pzz", "Pxy", "Pxz", "Pyz")
_DUMP_FIELDS = ("id", "type", "x", "y", "z", "fx", "fy", "fz")


def _model_atoms(model: ModelArtifacts) -> tuple[Atoms, list[int]]:
    if not isinstance(model, ModelArtifacts):
        raise TypeError("LAMMPS export requires a persisted ModelArtifacts value")
    atoms = model.atoms
    if len(atoms) == 0:
        raise ValueError("LAMMPS export requires at least one atom")
    if not bool(np.all(np.asarray(atoms.pbc, dtype=bool))):
        raise ValueError("LAMMPS export requires a three-dimensional periodic cell")
    cell = np.asarray(atoms.cell.array, dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("LAMMPS export requires a finite 3x3 cell")
    if abs(float(np.linalg.det(cell))) <= 1.0e-12:
        raise ValueError("LAMMPS export requires a non-zero cell volume")
    if "initial_charges" in atoms.arrays:
        initial_charges = np.asarray(atoms.arrays["initial_charges"], dtype=float)
        if not np.all(np.isfinite(initial_charges)):
            raise ValueError("LAMMPS atom_style atomic cannot represent non-finite initial charges")
        if not np.allclose(initial_charges, 0.0, rtol=0.0, atol=1.0e-12):
            raise ValueError("LAMMPS atom_style atomic cannot represent non-zero initial charges")
    derivation = model.metadata.get("derivation")
    if isinstance(derivation, Mapping) and "charge_state" in derivation:
        if float(derivation["charge_state"]) != 0.0:
            raise ValueError("LAMMPS atom_style atomic cannot represent a charged derivation")
    if "atom_id" not in atoms.arrays:
        raise ValueError("LAMMPS export requires model atom_id values")
    raw_ids = np.asarray(atoms.arrays["atom_id"])
    if not np.issubdtype(raw_ids.dtype, np.integer):
        raise ValueError("LAMMPS model atom_id values must be integers")
    atom_ids = [int(value) for value in raw_ids]
    if len(set(atom_ids)) != len(atom_ids) or any(value < 0 for value in atom_ids):
        raise ValueError("LAMMPS model atom_id values must be unique and non-negative")
    symbols = [str(value) for value in atoms.get_chemical_symbols()]
    masses = np.asarray(atoms.get_masses(), dtype=float)
    for element in dict.fromkeys(symbols):
        element_masses = masses[[index for index, symbol in enumerate(symbols) if symbol == element]]
        if not np.allclose(element_masses, element_masses[0], rtol=0.0, atol=1.0e-12):
            raise ValueError(
                f"LAMMPS atom_style atomic cannot represent multiple masses for element {element}"
            )
    return atoms, atom_ids


def _validate_units_style(units: str, atom_style: str) -> None:
    if units != LAMMPS_UNITS:
        raise ValueError("LAMMPS adapter supports units='metal' only")
    if atom_style != LAMMPS_ATOM_STYLE:
        raise ValueError("LAMMPS adapter supports atom_style='atomic' only")


def _element_order(atoms: Atoms, element_order: Sequence[str]) -> list[str]:
    elements = [str(value) for value in element_order]
    symbols = [str(value) for value in atoms.get_chemical_symbols()]
    if not elements or len(elements) != len(set(elements)):
        raise ValueError("LAMMPS element_order must contain unique elements")
    if set(elements) != set(symbols):
        raise ValueError("LAMMPS element_order must cover model elements exactly")
    return elements


def export_lammps_data(
    model: ModelArtifacts,
    directory: str | Path,
    *,
    element_order: list[str],
    units: str,
    atom_style: str,
) -> dict[str, Any]:
    """Export one periodic model as a LAMMPS ``atomic`` data file.

    LAMMPS IDs follow the model's source order and start at one.  ``element_order``
    defines the type numbers, while the map records the source atom ID for
    every LAMMPS ID.  Positions and the cell are transformed with ASE Prism.
    """

    _validate_units_style(units, atom_style)
    atoms, source_atom_ids = _model_atoms(model)
    elements = _element_order(atoms, element_order)
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    prism = Prism(np.asarray(atoms.cell.array, dtype=float), pbc=atoms.pbc, reduce_cell=False)
    data_path = output / "model.data"
    atom_map_path = output / "atom-map.json"

    # ASE writes the native data sections, masses, type numbers, and Prism-
    # rotated coordinates.  ``atomic`` has no charge field or topology.
    write_lammps_data(
        str(data_path),
        atoms,
        specorder=elements,
        force_skew=True,
        prismobj=prism,
        masses=True,
        velocities=False,
        atom_type_labels=False,
        units=units,
        bonds=False,
        atom_style=atom_style,
    )

    symbols = [str(value) for value in atoms.get_chemical_symbols()]
    type_by_element = {element: index + 1 for index, element in enumerate(elements)}
    mass_by_element = {
        element: float(atoms.get_masses()[symbols.index(element)]) for element in elements
    }
    lammps_prism = [float(value) for value in prism.get_lammps_prism()]
    lammps_cell = np.asarray(prism.cell, dtype=float)
    atom_entries = [
        {
            "lammps_id": index + 1,
            "source_index": index,
            "source_atom_id": source_atom_ids[index],
            "type": type_by_element[symbols[index]],
            "element": symbols[index],
        }
        for index in range(len(atoms))
    ]
    atom_map = {
        "schema": "mlcc.lammps-atom-map.v1",
        "model_id": model.model_id,
        "version": model.version,
        "units": units,
        "atom_style": atom_style,
        "source_atom_ids": source_atom_ids,
        "element_order": elements,
        "elements_by_type": {str(index + 1): element for index, element in enumerate(elements)},
        "masses_by_type": {str(type_by_element[element]): mass_by_element[element] for element in elements},
        "mass_source": "ModelAtoms masses",
        "atoms": atom_entries,
        "source_cell_angstrom": np.asarray(atoms.cell.array, dtype=float).tolist(),
        "lammps_cell_angstrom": lammps_cell.tolist(),
        "lammps_prism": lammps_prism,
        "lammps_origin_angstrom": [0.0, 0.0, 0.0],
        "rotation_matrix_ase_to_lammps": np.asarray(prism.rot_mat, dtype=float).tolist(),
        "coordinate_units": "angstrom",
        "mass_units": "g/mol",
    }
    atom_map_path.write_text(json.dumps(atom_map, indent=2) + "\n", encoding="utf-8")
    return {
        "model_id": model.model_id,
        "version": model.version,
        "units": units,
        "atom_style": atom_style,
        "element_order": elements,
        "data_path": str(data_path),
        "atom_map_path": str(atom_map_path),
        "files": ["model.data", "atom-map.json"],
        "atom_map": atom_map,
    }


def validate_lammps_model(model: ModelArtifacts, directory: str | Path) -> None:
    """Check that native data and atom-map files bind to the supplied model."""

    atoms, source_atom_ids = _model_atoms(model)
    output = Path(directory)
    atom_map = json.loads((output / "atom-map.json").read_text(encoding="utf-8"))
    data_path = output / "model.data"
    if atom_map["model_id"] != model.model_id or atom_map["version"] != model.version:
        raise ValueError("LAMMPS atom map model identity differs from supplied model")
    if atom_map["units"] != LAMMPS_UNITS or atom_map["atom_style"] != LAMMPS_ATOM_STYLE:
        raise ValueError("LAMMPS atom map units or atom_style are not the atomic metal contract")
    if atom_map["coordinate_units"] != "angstrom":
        raise ValueError("LAMMPS atom map coordinate_units must be angstrom")
    if atom_map["mass_units"] != "g/mol":
        raise ValueError("LAMMPS atom map mass_units must be g/mol")
    if atom_map["lammps_origin_angstrom"] != [0, 0, 0]:
        raise ValueError("LAMMPS atom map origin must be [0, 0, 0] angstrom")

    symbols = [str(value) for value in atoms.get_chemical_symbols()]
    entries = atom_map["atoms"]
    if len(entries) != len(atoms):
        raise ValueError("LAMMPS atom map atom count differs from supplied model")
    element_order = [str(value) for value in atom_map["element_order"]]
    if not element_order or len(element_order) != len(set(element_order)):
        raise ValueError("LAMMPS atom map element_order is invalid")
    if set(element_order) != set(symbols):
        raise ValueError("LAMMPS atom map elements differ from supplied model")
    type_by_element = {element: index + 1 for index, element in enumerate(element_order)}
    expected_elements_by_type = {
        str(type_id): element for element, type_id in type_by_element.items()
    }
    if atom_map["elements_by_type"] != expected_elements_by_type:
        raise ValueError("LAMMPS atom map elements_by_type differs from element_order")
    if [int(value) for value in atom_map["source_atom_ids"]] != source_atom_ids:
        raise ValueError("LAMMPS atom map source atom IDs differ from supplied model")

    for source_index, (entry, symbol, source_atom_id) in enumerate(
        zip(entries, symbols, source_atom_ids)
    ):
        if int(entry["source_index"]) != source_index:
            raise ValueError("LAMMPS atom map source indices are not stable")
        if int(entry["lammps_id"]) != source_index + 1:
            raise ValueError("LAMMPS atom map IDs are not stable 1-based IDs")
        if int(entry["source_atom_id"]) != source_atom_id:
            raise ValueError("LAMMPS atom map source atom ID differs from supplied model")
        if str(entry["element"]) != symbol or int(entry["type"]) != type_by_element[symbol]:
            raise ValueError("LAMMPS atom map element or type differs from supplied model")

    source_cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    prism = Prism(np.asarray(atoms.cell.array, dtype=float), pbc=atoms.pbc, reduce_cell=False)
    if not np.allclose(source_cell, atoms.cell.array, rtol=0.0, atol=1.0e-10):
        raise ValueError("LAMMPS atom map source cell differs from supplied model")
    if not np.allclose(
        np.asarray(atom_map["lammps_cell_angstrom"], dtype=float),
        np.asarray(prism.cell, dtype=float),
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("LAMMPS atom map Prism cell differs from supplied model")
    if not np.allclose(
        np.asarray(atom_map["lammps_prism"], dtype=float),
        np.asarray(prism.get_lammps_prism(), dtype=float),
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("LAMMPS atom map Prism parameters differ from supplied model")
    if not np.allclose(
        np.asarray(atom_map["rotation_matrix_ase_to_lammps"], dtype=float),
        np.asarray(prism.rot_mat, dtype=float),
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("LAMMPS atom map rotation differs from supplied model")

    model_masses = np.asarray(atoms.get_masses(), dtype=float)
    masses_by_type = atom_map["masses_by_type"]
    if set(masses_by_type) != set(expected_elements_by_type):
        raise ValueError("LAMMPS atom map masses_by_type keys differ from element types")
    expected_masses_by_type = {
        str(type_id): float(model_masses[symbols.index(element)])
        for element, type_id in type_by_element.items()
    }
    for type_id, expected_mass in expected_masses_by_type.items():
        if not np.isclose(float(masses_by_type[type_id]), expected_mass, rtol=0.0, atol=1.0e-7):
            raise ValueError("LAMMPS atom map masses differ from supplied model")

    z_of_type = {
        int(type_id): atomic_numbers[element]
        for type_id, element in expected_elements_by_type.items()
    }
    data_atoms = read_lammps_data(
        str(data_path),
        Z_of_type=z_of_type,
        sort_by_id=True,
        units=LAMMPS_UNITS,
        atom_style=LAMMPS_ATOM_STYLE,
    )
    if data_atoms.arrays["id"].tolist() != list(range(1, len(atoms) + 1)):
        raise ValueError("LAMMPS model.data atom IDs are not stable 1-based IDs")
    expected_types = [type_by_element[symbol] for symbol in symbols]
    if data_atoms.arrays["type"].tolist() != expected_types:
        raise ValueError("LAMMPS model.data atom types differ from atom map")
    if data_atoms.get_chemical_symbols() != symbols:
        raise ValueError("LAMMPS model.data elements differ from supplied model")
    if not np.allclose(
        np.asarray(data_atoms.cell.array, dtype=float),
        np.asarray(prism.cell, dtype=float),
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("LAMMPS model.data cell differs from supplied model")
    if not np.allclose(data_atoms.get_celldisp(), 0.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("LAMMPS model.data cell displacement must be zero")
    expected_positions = prism.vector_to_lammps(np.asarray(atoms.positions, dtype=float))
    if not np.allclose(
        np.asarray(data_atoms.positions, dtype=float),
        expected_positions,
        rtol=0.0,
        atol=1.0e-10,
    ):
        raise ValueError("LAMMPS model.data initial positions differ from supplied model")
    if not np.allclose(
        np.asarray(data_atoms.get_masses(), dtype=float), model_masses,
        rtol=0.0,
        atol=1.0e-7,
    ):
        raise ValueError("LAMMPS model.data masses differ from supplied model")


def _nonempty_string(record: Mapping[str, Any], key: str) -> str:
    value = str(record[key])
    if not value:
        raise ValueError(f"LAMMPS potential {key} must be non-empty")
    return value


def _is_mace_potential(potential: Mapping[str, Any]) -> bool:
    """Return whether *potential* requests the explicit native ML-MACE route."""

    return str(potential["pair_style"]).split(maxsplit=1)[0] in {"mace", "mace/kk"}


def _validate_mace_pair_binding(
    potential: Mapping[str, Any],
    *,
    element_order: Sequence[str],
) -> None:
    """Validate the native MACE model token and its element mapping.

    The ML-MACE pair style consumes one TorchScript model followed by the
    element names in LAMMPS atom-type order.  Keep this check at the
    input boundary so a staged file or a reordered element list cannot be
    silently accepted as a different calculation.
    """

    pair_coeff = potential.get("pair_coeff")
    if not isinstance(pair_coeff, list) or len(pair_coeff) != 1:
        raise ValueError("MACE potential requires one pair_coeff mapping")
    tokens = str(pair_coeff[0]).split()
    if len(tokens) < 4 or tokens[:2] != ["*", "*"]:
        raise ValueError("MACE pair_coeff must be '* * model element...'")
    model_token = tokens[2]
    if not model_token or Path(model_token).is_absolute() or ".." in Path(model_token).parts:
        raise ValueError("MACE pair_coeff model must name a staged relative file")
    staged_names = {Path(str(item["filename"])).as_posix() for item in potential["files"]}
    if model_token not in staged_names:
        raise ValueError("MACE pair_coeff model is not bound to a staged potential file")
    mapped_elements = tokens[3:]
    if mapped_elements != [str(value) for value in element_order]:
        raise ValueError("MACE pair_coeff element order differs from potential element_order")


def _validate_potential(
    potential: Mapping[str, Any],
    *,
    model_id: str,
    model_elements: Sequence[str],
    element_order: Sequence[str],
    units: str,
    atom_style: str,
    protocol: Mapping[str, Any],
) -> None:
    for key in (
        "potential_id",
        "version",
        "source",
        "license",
        "pair_style",
    ):
        _nonempty_string(potential, key)
    qualification = protocol.get("purpose") in {
        "potential_qualification",
        "interface_normal_response",
        "interface_tangential_response",
        "interface_thermal_response",
        "interface_local_stress",
        "vacancy_migration",
        "md_native_sampling",
        "md_bulk_thermal",
        "bulk_thermal_transport",
    }
    if qualification:
        for key in ("potential_id", "version", "source", "license"):
            if not isinstance(potential[key], str) or not potential[key].strip():
                raise ValueError(f"LAMMPS qualification candidate requires explicit {key}")
        if not isinstance(potential["fixture"], bool) or potential["production_qualification"] is not False:
            raise ValueError("LAMMPS qualification candidate must declare fixture and production_qualification=false")
    elif potential["fixture"] is not True:
        raise ValueError("LAMMPS adapter accepts fixture potentials only")
    if potential.get("production_qualification") is True:
        raise ValueError("LAMMPS fixture potential cannot be production-qualified")
    if str(potential["units"]) != units or str(potential["atom_style"]) != atom_style:
        raise ValueError("LAMMPS potential units and atom_style differ from export")
    elements = [str(value) for value in potential["elements"]]
    potential_order = [str(value) for value in potential["element_order"]]
    if len(elements) != len(set(elements)):
        raise ValueError("LAMMPS potential elements must be unique")
    if potential_order != list(element_order):
        raise ValueError("LAMMPS potential element_order differs from model export")
    if set(elements) != set(model_elements) or set(elements) != set(element_order):
        raise ValueError("LAMMPS potential elements do not cover the model exactly")
    model_ids = [str(value) for value in potential["model_ids"]]
    if model_id not in model_ids:
        raise ValueError("LAMMPS potential is not applicable to this model_id")
    pair_coeff = potential["pair_coeff"]
    if not isinstance(pair_coeff, list) or not pair_coeff or any(
        not isinstance(value, str) or not value.strip() for value in pair_coeff
    ):
        raise ValueError("LAMMPS potential pair_coeff must be a non-empty list of strings")
    files = potential["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("LAMMPS potential files must be a non-empty list")
    for item in files:
        if not isinstance(item, Mapping):
            raise ValueError("LAMMPS potential files must contain mappings")
        if not str(item["local_path"]) or not str(item["filename"]):
            raise ValueError("LAMMPS potential file paths must be non-empty")
    if _is_mace_potential(potential):
        if potential["pair_style"] != "mace no_domain_decomposition":
            raise ValueError("MACE requires the supported pair_style 'mace no_domain_decomposition'")
        if protocol.get("purpose") not in {
            "potential_qualification",
            "interface_normal_response",
            "interface_tangential_response",
            "interface_thermal_response",
            "interface_local_stress",
        }:
            raise ValueError(
                "native MACE requires an explicit static candidate or supported interface protocol"
            )
        if protocol.get("purpose") == "interface_thermal_response":
            from .lammps_interface_thermal import validate_thermal_protocol
            validate_thermal_protocol(protocol)
        elif protocol.get("kind") not in {"run0", "interface_normal", "interface_tangential"} or protocol.get("static_tensor") is not True:
            raise ValueError("native MACE requires an explicit static or interface thermal protocol")
        if potential.get("production_qualification") is not False:
            raise ValueError("native MACE qualification must remain production_qualification=false")
        _validate_mace_pair_binding(potential, element_order=element_order)
    if protocol.get("purpose") in {"potential_qualification", "interface_local_stress"}:
        from .lammps_local_stress import local_stress_enabled, validate_local_stress_potential

        if local_stress_enabled(protocol):
            validate_local_stress_potential(protocol, potential)
    if protocol.get("purpose") == "md_native_sampling":
        from .lammps_md_sampling import validate_md_sampling_potential

        validate_md_sampling_potential(protocol, potential)


def _positive_int(record: Mapping[str, Any], key: str) -> int:
    value = record[key]
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) <= 0:
        raise ValueError(f"LAMMPS protocol {key} must be a positive integer")
    return int(value)


def _positive_float(record: Mapping[str, Any], key: str) -> float:
    value = float(record[key])
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"LAMMPS protocol {key} must be positive and finite")
    return value


def validate_lammps_protocol(protocol: Mapping[str, Any]) -> None:
    if str(protocol["units"]) != LAMMPS_UNITS:
        raise ValueError("LAMMPS protocol units must be metal")
    boundary = [str(value) for value in protocol["boundary"]]
    if boundary != ["p", "p", "p"]:
        raise ValueError("LAMMPS protocol boundary must be p p p")
    kind = str(protocol["kind"])
    from .md_unwrapped import validate_unwrapped_protocol

    validate_unwrapped_protocol(protocol)
    from .lammps_md_sampling import validate_md_sampling_protocol

    validate_md_sampling_protocol(protocol)
    from .lammps_bulk_thermal import validate_bulk_thermal_protocol

    validate_bulk_thermal_protocol(protocol)
    purpose = protocol.get("purpose")
    if purpose == "potential_qualification":
        if kind != "run0" or protocol.get("static_tensor") is not True:
            raise ValueError("LAMMPS potential_qualification requires run0 and static_tensor=true")
        if not isinstance(protocol["experiment_scope"], str) or not protocol["experiment_scope"].strip():
            raise ValueError("LAMMPS potential_qualification requires a predeclared experiment_scope")
        if "local_stress" in protocol:
            from .lammps_local_stress import validate_local_stress_protocol

            validate_local_stress_protocol(protocol)
    elif purpose == "interface_normal_response":
        if kind != "interface_normal" or protocol.get("static_tensor") is not True:
            raise ValueError(
                "LAMMPS interface_normal_response requires interface_normal and static_tensor=true"
            )
        if not isinstance(protocol["experiment_scope"], str) or not protocol["experiment_scope"].strip():
            raise ValueError("LAMMPS interface_normal_response requires a predeclared experiment_scope")
    elif purpose == "interface_tangential_response":
        if kind != "interface_tangential" or protocol.get("static_tensor") is not True:
            raise ValueError(
                "LAMMPS interface_tangential_response requires interface_tangential and static_tensor=true"
            )
        if not isinstance(protocol["experiment_scope"], str) or not protocol["experiment_scope"].strip():
            raise ValueError("LAMMPS interface_tangential_response requires a predeclared experiment_scope")
    elif purpose == "interface_thermal_response":
        from .lammps_interface_thermal import validate_thermal_protocol
        validate_thermal_protocol(protocol)
    elif purpose == "bulk_thermal_transport":
        from .lammps_bulk_heat import validate_bulk_heat_protocol

        validate_bulk_heat_protocol(protocol)
        _nonempty_string(protocol, "experiment_scope")
    elif purpose == "interface_local_stress":
        from .lammps_local_stress import validate_local_stress_protocol
        validate_local_stress_protocol(protocol)
        _nonempty_string(protocol, "experiment_scope")
    elif purpose in {"md_native_sampling", "md_bulk_thermal"}:
        _nonempty_string(protocol, "experiment_scope")
    elif purpose is not None:
        raise ValueError(
            "unsupported LAMMPS protocol purpose"
        )
    if "static_tensor" in protocol:
        if not isinstance(protocol["static_tensor"], bool):
            raise ValueError("LAMMPS static_tensor must be boolean")
        if protocol["static_tensor"] and kind not in {"run0", "interface_normal", "interface_tangential"}:
            raise ValueError("LAMMPS static_tensor requires run0, interface_normal or interface_tangential")
    if kind == "interface_normal":
        from .lammps_interface_normal import validate_normal_protocol

        validate_normal_protocol(protocol)
        return
    if kind == "interface_tangential":
        from .lammps_interface_normal import validate_tangential_protocol

        validate_tangential_protocol(protocol)
        return
    if kind == "run0":
        _positive_float(protocol, "timestep_ps")
        if "temperature_K" in protocol or "seed" in protocol:
            raise ValueError("LAMMPS run0 protocol must not define temperature_K or seed")
        return
    if kind != "md":
        raise ValueError("LAMMPS protocol kind must be run0 or md")
    ensemble = str(protocol["ensemble"])
    if ensemble not in {"nve", "nvt"} and not (
        ensemble == "npt" and purpose == "md_bulk_thermal"
    ):
        raise ValueError("LAMMPS MD ensemble must be nve/nvt or explicit md_bulk_thermal npt")
    _positive_int(protocol, "steps")
    _positive_float(protocol, "timestep_ps")
    _positive_float(protocol, "temperature_K")
    _positive_int(protocol, "seed")
    _positive_int(protocol, "thermo_every")
    _positive_int(protocol, "dump_every")
    if int(protocol["steps"]) % int(protocol["dump_every"]) != 0:
        raise ValueError("LAMMPS MD dump_every must divide steps for a recorded final frame")
    if ensemble in {"nvt", "npt"}:
        _positive_float(protocol, "tdamp_ps")


def _write_dump_command() -> str:
    return "write_dump all custom dump.final id type x y z fx fy fz modify sort id format float %.16g"


def _thermo_commands(protocol: Mapping[str, Any]) -> list[str]:
    if protocol.get("purpose") == "md_bulk_thermal":
        from .lammps_bulk_thermal import bulk_thermal_thermo_commands

        return bulk_thermal_thermo_commands(protocol)
    if protocol.get("static_tensor", False):
        return [
            "velocity all set 0.0 0.0 0.0",
            "compute mlcc_static_pressure all pressure NULL virial",
            "thermo_style custom step temp pe ke etotal press pxx pyy pzz pxy pxz pyz",
            "thermo_modify press mlcc_static_pressure format float %.16g",
        ]
    return ["thermo_style custom step temp pe ke etotal press", "thermo_modify format float %.16g"]


def _native_setup_commands(potential: Mapping[str, Any]) -> list[str]:
    """Return setup commands whose ordering is part of the native input contract."""

    if str(potential["pair_style"]).split(maxsplit=1)[0] == "deepmd":
        plugin = potential.get("plugin")
        if isinstance(plugin, str) and plugin.strip():
            return [f'plugin load "{plugin}"']
    if not _is_mace_potential(potential):
        return []
    return [
        "package kokkos neigh half newton on",
        "atom_modify map yes",
        "atom_modify sort 0 0.0",
        "newton on",
    ]


def _native_input_commands(
    potential: Mapping[str, Any],
    protocol: Mapping[str, Any],
    masses_by_type: Mapping[str, Any],
    atom_map: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return the fixed domain commands that must be echoed by LAMMPS."""

    setup = _native_setup_commands(potential)
    commands = [
        *setup[:1],
        "units metal",
        "atom_style atomic",
        *setup[1:3],
        "boundary p p p",
        *setup[3:],
        "read_data model.data",
        f"pair_style {potential['pair_style']}",
        *(f"pair_coeff {value}" for value in potential["pair_coeff"]),
        *(
            f"mass {type_id} {float(masses_by_type[type_id]):.12g}"
            for type_id in sorted(masses_by_type, key=int)
        ),
        *_thermo_commands(protocol),
    ]
    if protocol["kind"] == "interface_normal":
        if atom_map is None:
            raise ValueError("LAMMPS interface_normal input requires atom_map")
        from .lammps_interface_normal import normal_input_commands

        commands.extend(normal_input_commands(protocol, atom_map))
    elif protocol["kind"] == "interface_tangential":
        if atom_map is None:
            raise ValueError("LAMMPS interface_tangential input requires atom_map")
        from .lammps_interface_normal import tangential_input_commands

        commands.extend(tangential_input_commands(protocol, atom_map))
    elif protocol["kind"] == "run0":
        from .lammps_local_stress import local_stress_enabled

        if local_stress_enabled(protocol):
            from .lammps_local_stress import local_stress_before_run_commands

            commands.extend(local_stress_before_run_commands(protocol, potential))
        commands.extend(
            [
                f"timestep {float(protocol['timestep_ps']):.12g}",
                "thermo 1",
                "run 0",
                _write_dump_command(),
            ]
        )
        if local_stress_enabled(protocol):
            from .lammps_local_stress import local_stress_after_run_commands
            commands.extend(local_stress_after_run_commands(protocol))
    else:
        temperature = float(protocol["temperature_K"])
        seed = int(protocol["seed"])
        commands.extend(
            [
                f"velocity all create {temperature:.12g} {seed} mom yes rot no dist gaussian",
                f"timestep {float(protocol['timestep_ps']):.12g}",
            ]
        )
        if protocol["ensemble"] == "nve":
            commands.append("fix integrator all nve")
        elif protocol["ensemble"] == "npt":
            from .lammps_bulk_thermal import bulk_thermal_integrator_command

            commands.append(bulk_thermal_integrator_command(protocol))
        else:
            commands.append(
                f"fix integrator all nvt temp {temperature:.12g} {temperature:.12g} "
                f"{float(protocol['tdamp_ps']):.12g}"
            )
        from .md_unwrapped import unwrapped_input_commands

        unwrapped_commands = unwrapped_input_commands(protocol)
        commands.extend(unwrapped_commands[:2])
        if protocol.get("purpose") == "md_native_sampling":
            from .lammps_md_sampling import md_sampling_before_run_commands

            commands.extend(md_sampling_before_run_commands(protocol))
        if protocol.get("purpose") == "interface_thermal_response":
            from .lammps_interface_thermal import thermal_before_run_commands
            commands.extend(thermal_before_run_commands(protocol, atom_map))
        if protocol.get("purpose") == "bulk_thermal_transport":
            from .lammps_bulk_heat import bulk_heat_before_run_commands

            commands.extend(bulk_heat_before_run_commands(protocol, atom_map))
        commands.extend(
            [
                f"dump trajectory all custom {int(protocol['dump_every'])} trajectory.lammpstrj id type x y z fx fy fz",
                "dump_modify trajectory sort id format float %.16g",
                f"thermo {int(protocol['thermo_every'])}",
                f"run {int(protocol['steps'])}",
                "unfix integrator",
                "undump trajectory",
                _write_dump_command(),
            ]
        )
        if unwrapped_commands:
            commands.append(unwrapped_commands[2])
        if protocol.get("purpose") == "md_native_sampling":
            from .lammps_md_sampling import md_sampling_after_run_commands

            commands.extend(md_sampling_after_run_commands(protocol))
        if protocol.get("purpose") == "interface_thermal_response":
            from .lammps_interface_thermal import thermal_after_run_commands
            commands.extend(thermal_after_run_commands(protocol))
        if protocol.get("purpose") == "bulk_thermal_transport":
            from .lammps_bulk_heat import bulk_heat_after_run_commands

            commands.extend(bulk_heat_after_run_commands(protocol))
    return commands


def _input_text(
    potential: Mapping[str, Any],
    protocol: Mapping[str, Any],
    masses_by_type: Mapping[str, Any],
    atom_map: Mapping[str, Any] | None = None,
) -> str:
    setup = _native_setup_commands(potential)
    lines = [
        "# MLCC LAMMPS potential qualification"
        if protocol.get("purpose") == "potential_qualification"
        else "# MLCC LAMMPS interface normal response"
        if protocol.get("purpose") == "interface_normal_response"
        else "# MLCC LAMMPS interface tangential response"
        if protocol.get("purpose") == "interface_tangential_response"
        else "# MLCC LAMMPS interface thermal response"
        if protocol.get("purpose") == "interface_thermal_response"
        else "# MLCC LAMMPS local virial stress"
        if protocol.get("purpose") == "interface_local_stress"
        else "# MLCC LAMMPS engineering fixture",
        "clear",
        *setup[:1],
        "units metal",
        "atom_style atomic",
        *setup[1:3],
        "boundary p p p",
        *setup[3:],
        "read_data model.data",
        f"pair_style {potential['pair_style']}",
    ]
    lines.extend(f"pair_coeff {value}" for value in potential["pair_coeff"])
    lines.extend(
        f"mass {type_id} {float(masses_by_type[type_id]):.12g}"
        for type_id in sorted(masses_by_type, key=int)
    )
    lines.extend(_thermo_commands(protocol))
    if protocol["kind"] == "interface_normal":
        if atom_map is None:
            raise ValueError("LAMMPS interface_normal input requires atom_map")
        from .lammps_interface_normal import normal_input_commands

        lines.extend(normal_input_commands(protocol, atom_map))
    elif protocol["kind"] == "interface_tangential":
        if atom_map is None:
            raise ValueError("LAMMPS interface_tangential input requires atom_map")
        from .lammps_interface_normal import tangential_input_commands

        lines.extend(tangential_input_commands(protocol, atom_map))
    elif protocol["kind"] == "run0":
        from .lammps_local_stress import local_stress_enabled

        if local_stress_enabled(protocol):
            from .lammps_local_stress import local_stress_before_run_commands

            lines.extend(local_stress_before_run_commands(protocol, potential))
        lines.extend(
            [
                f"timestep {float(protocol['timestep_ps']):.12g}",
                "thermo 1",
                "run 0",
                _write_dump_command(),
            ]
        )
        if local_stress_enabled(protocol):
            from .lammps_local_stress import local_stress_after_run_commands
            lines.extend(local_stress_after_run_commands(protocol))
    else:
        temperature = float(protocol["temperature_K"])
        seed = int(protocol["seed"])
        lines.extend(
            [
                f"velocity all create {temperature:.12g} {seed} mom yes rot no dist gaussian",
                f"timestep {float(protocol['timestep_ps']):.12g}",
            ]
        )
        if protocol["ensemble"] == "nve":
            lines.append("fix integrator all nve")
        elif protocol["ensemble"] == "npt":
            from .lammps_bulk_thermal import bulk_thermal_integrator_command

            lines.append(bulk_thermal_integrator_command(protocol))
        else:
            lines.append(
                f"fix integrator all nvt temp {temperature:.12g} {temperature:.12g} "
                f"{float(protocol['tdamp_ps']):.12g}"
            )
        from .md_unwrapped import unwrapped_input_commands

        unwrapped_commands = unwrapped_input_commands(protocol)
        lines.extend(unwrapped_commands[:2])
        if protocol.get("purpose") == "md_native_sampling":
            from .lammps_md_sampling import md_sampling_before_run_commands

            lines.extend(md_sampling_before_run_commands(protocol))
        if protocol.get("purpose") == "interface_thermal_response":
            from .lammps_interface_thermal import thermal_before_run_commands
            lines.extend(thermal_before_run_commands(protocol, atom_map))
        if protocol.get("purpose") == "bulk_thermal_transport":
            from .lammps_bulk_heat import bulk_heat_before_run_commands

            lines.extend(bulk_heat_before_run_commands(protocol, atom_map))
        lines.extend(
            [
                f"dump trajectory all custom {int(protocol['dump_every'])} trajectory.lammpstrj id type x y z fx fy fz",
                "dump_modify trajectory sort id format float %.16g",
                f"thermo {int(protocol['thermo_every'])}",
                f"run {int(protocol['steps'])}",
                "unfix integrator",
                "undump trajectory",
                _write_dump_command(),
            ]
        )
        if unwrapped_commands:
            lines.append(unwrapped_commands[2])
        if protocol.get("purpose") == "md_native_sampling":
            from .lammps_md_sampling import md_sampling_after_run_commands

            lines.extend(md_sampling_after_run_commands(protocol))
        if protocol.get("purpose") == "interface_thermal_response":
            from .lammps_interface_thermal import thermal_after_run_commands
            lines.extend(thermal_after_run_commands(protocol))
        if protocol.get("purpose") == "bulk_thermal_transport":
            from .lammps_bulk_heat import bulk_heat_after_run_commands

            lines.extend(bulk_heat_after_run_commands(protocol))
    return "\n".join(lines) + "\n"


def prepare_lammps(
    model: ModelArtifacts,
    directory: str | Path,
    *,
    potential: dict[str, Any],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    """Prepare the fixed LAMMPS data/input/method file set."""

    atoms, _ = _model_atoms(model)
    units = str(potential["units"])
    atom_style = str(potential["atom_style"])
    _validate_units_style(units, atom_style)
    element_order = [str(value) for value in potential["element_order"]]
    model_elements = [str(value) for value in atoms.get_chemical_symbols()]
    validate_lammps_protocol(protocol)
    _validate_potential(
        potential,
        model_id=model.model_id,
        model_elements=model_elements,
        element_order=element_order,
        units=units,
        atom_style=atom_style,
        protocol=protocol,
    )
    output = Path(directory)
    export = export_lammps_data(
        model,
        output,
        element_order=element_order,
        units=units,
        atom_style=atom_style,
    )
    input_path = output / "in.lammps"
    method_path = output / "method.json"
    input_path.write_text(
        _input_text(
            potential,
            protocol,
            export["atom_map"]["masses_by_type"],
            export["atom_map"],
        ),
        encoding="utf-8",
        newline="\n",
    )
    method = {
        "schema": "mlcc.lammps-method.v1",
        "engine": "lammps",
        "model_id": model.model_id,
        "version": model.version,
        "units": units,
        "atom_style": atom_style,
        "element_order": element_order,
        "mass_source": "ModelAtoms masses",
        "potential": dict(potential),
        "protocol": dict(protocol),
        "production_qualification": False,
        "files": {
            "model.data": str(output / "model.data"),
            "atom-map.json": str(output / "atom-map.json"),
            "in.lammps": str(input_path),
            "method.json": str(method_path),
            "log.lammps": str(output / "log.lammps"),
            "dump.final": str(output / "dump.final"),
        },
    }
    from .lammps_local_stress import local_stress_enabled

    if local_stress_enabled(protocol):
        method["files"]["local-stress.lammpstrj"] = str(output / "local-stress.lammpstrj")
    if protocol["kind"] == "md":
        method["files"]["trajectory.lammpstrj"] = str(output / "trajectory.lammpstrj")
        from .md_unwrapped import unwrapped_output_files

        for filename in unwrapped_output_files(protocol):
            method["files"][filename] = str(output / filename)
        from .lammps_md_sampling import md_sampling_output_files

        for filename in md_sampling_output_files(protocol):
            method["files"][filename] = str(output / filename)
        if protocol.get("purpose") == "interface_thermal_response":
            for filename in ("thermal-energy.dat", "thermal-profile.dat"):
                method["files"][filename] = str(output / filename)
        if protocol.get("purpose") == "bulk_thermal_transport":
            from .lammps_bulk_heat import bulk_heat_output_files

            for filename in bulk_heat_output_files(protocol):
                method["files"][filename] = str(output / filename)
    elif protocol["kind"] == "interface_normal":
        method["files"].pop("dump.final", None)
        from .lammps_interface_normal import normal_output_files

        for filename in normal_output_files(protocol):
            method["files"][filename] = str(output / filename)
    elif protocol["kind"] == "interface_tangential":
        method["files"].pop("dump.final", None)
        from .lammps_interface_normal import tangential_output_files

        for filename in tangential_output_files(protocol):
            method["files"][filename] = str(output / filename)
    method_path.write_text(json.dumps(method, indent=2) + "\n", encoding="utf-8")
    return {
        **export,
        "input_path": str(input_path),
        "method_path": str(method_path),
        "files": ["model.data", "atom-map.json", "in.lammps", "method.json"],
        "potential": dict(potential),
        "protocol": dict(protocol),
        "production_qualification": False,
    }


def _finite_row(values: Sequence[str], *, context: str) -> list[float]:
    row = [float(value) for value in values]
    if not np.all(np.isfinite(np.asarray(row, dtype=float))):
        raise ValueError(f"LAMMPS {context} contains non-finite values")
    return row


def _integer_token(value: str, *, context: str) -> int:
    number = float(value)
    if not math.isfinite(number) or int(number) != number:
        raise ValueError(f"LAMMPS {context} integer is invalid")
    return int(number)


def _prism_from_lammps_bounds(box_rows: Sequence[Sequence[float]]) -> list[float]:
    """Recover ``xhi-xlo, yhi-ylo, zhi-zlo, xy, xz, yz`` from dump bounds."""

    values = np.asarray(box_rows, dtype=float)
    if values.shape != (3, 3):
        raise ValueError("LAMMPS triclinic bounds must be a 3x3 matrix")
    xlo_bound, xhi_bound, xy = (float(value) for value in values[0])
    ylo_bound, yhi_bound, xz = (float(value) for value in values[1])
    zlo_bound, zhi_bound, yz = (float(value) for value in values[2])
    xlo = xlo_bound - min(0.0, xy, xz, xy + xz)
    xhi = xhi_bound - max(0.0, xy, xz, xy + xz)
    ylo = ylo_bound - min(0.0, yz)
    yhi = yhi_bound - max(0.0, yz)
    return [xhi - xlo, yhi - ylo, zhi_bound - zlo_bound, xy, xz, yz]


def _parse_thermo(text: str, protocol: Mapping[str, Any]) -> dict[str, float | int]:
    lines = text.splitlines()
    fields = _THERMO_FIELDS + (_PRESSURE_FIELDS if protocol.get("static_tensor", False) else ())
    headers = [index for index, line in enumerate(lines) if tuple(line.split()) == fields]
    if not headers:
        raise ValueError("LAMMPS log.lammps is missing the requested thermo header")
    rows: list[dict[str, float | int]] = []
    for line in lines[headers[-1] + 1 :]:
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "Loop":
            break
        if len(tokens) != len(fields):
            raise ValueError("LAMMPS thermo row differs from the fixed thermo header")
        step = _integer_token(tokens[0], context="thermo step")
        values = _finite_row(tokens[1:], context="thermo")
        rows.append(
            {
                "step": step,
                "temp": values[0],
                "pe": values[1],
                "ke": values[2],
                "etotal": values[3],
                "press": values[4],
            }
        )
        if protocol.get("static_tensor", False):
            rows[-1].update(dict(zip((name.lower() for name in _PRESSURE_FIELDS), values[5:])))
    if not rows:
        raise ValueError("LAMMPS log.lammps contains no thermo data")
    final = rows[-1]
    expected_step = 0 if protocol["kind"] == "run0" else int(protocol["steps"])
    if int(final["step"]) != expected_step:
        raise ValueError("LAMMPS thermo final step differs from protocol")
    if protocol.get("static_tensor", False):
        if final["temp"] != 0.0 or final["ke"] != 0.0:
            raise ValueError("LAMMPS static tensor requires zero temperature and kinetic energy")
        trace_pressure = (final["pxx"] + final["pyy"] + final["pzz"]) / 3.0
        if not math.isclose(final["press"], trace_pressure, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError("LAMMPS scalar pressure differs from tensor trace")
    return final


def pressure_tensor_to_source(components_bar: Sequence[float], source_cell: Sequence[Sequence[float]]) -> dict[str, Any]:
    """Convert native xx,yy,zz,xy,xz,yz pressure to source Cartesian stress.

    LAMMPS metal pressure is compression-positive in bar.  ASE Prism uses
    row vectors x_lammps = x_source @ R, so P_source = R @ P_lammps @ R.T.
    Mechanical tensile-positive stress is -P, with 1 bar = 1e-4 GPa.
    """
    xx, yy, zz, xy, xz, yz = _finite_row(components_bar, context="pressure tensor")
    native = np.asarray([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]])
    rotation = Prism(np.asarray(source_cell, dtype=float), pbc=True, reduce_cell=False).rot_mat
    pressure = rotation @ native @ rotation.T * 1e-4
    return {
        "pressure_components_bar": [xx, yy, zz, xy, xz, yz],
        "pressure_component_order": ["xx", "yy", "zz", "xy", "xz", "yz"],
        "pressure_tensor_GPa": pressure.tolist(),
        "pressure_sign": "compression_positive",
        "stress_GPa": (-pressure).tolist(),
        "stress_unit": "GPa",
        "stress_sign": "tension_positive",
        "tensor_basis": "source_cartesian",
        "tensor_contribution": "virial_only_zero_velocity",
    }


def _validate_native_log(text: str) -> str:
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise ValueError("LAMMPS log.lammps has no version first line")
    if not lines[0].strip().startswith("LAMMPS"):
        raise ValueError("LAMMPS log.lammps version first line must start with LAMMPS")
    for line in lines:
        if re.search(r"\bERROR\b", line, flags=re.IGNORECASE):
            raise RuntimeError(line)
    if not any(re.match(r"^\s*units\s+metal(?:\s|$)", line) for line in lines):
        raise ValueError("LAMMPS log.lammps does not record units metal")
    if not any(re.match(r"^\s*atom_style\s+atomic(?:\s|$)", line) for line in lines):
        raise ValueError("LAMMPS log.lammps does not record atom_style atomic")
    if not any("Total wall time" in line for line in lines):
        raise ValueError("LAMMPS log.lammps is missing Total wall time")
    return lines[0].strip()


def _validate_native_input_echo(
    log_text: str,
    input_text: str,
    potential: Mapping[str, Any],
    protocol: Mapping[str, Any],
    masses_by_type: Mapping[str, Any],
    atom_map: Mapping[str, Any] | None = None,
) -> None:
    """Bind native log command echo to the prepared fixed input contract."""

    expected = _native_input_commands(potential, protocol, masses_by_type, atom_map)
    prepared_lines = [line.strip() for line in input_text.splitlines()]
    log_lines = [line.strip() for line in log_text.splitlines()]
    for context, lines in (("prepared input", prepared_lines), ("native log", log_lines)):
        cursor = -1
        for command in expected:
            try:
                cursor = lines.index(command, cursor + 1)
            except ValueError as error:
                raise ValueError(
                    f"LAMMPS {context} is missing or reorders prepared command: {command}"
                ) from error


def _parse_dump(
    text: str,
    atom_map: Mapping[str, Any],
    *,
    coordinate_columns: Sequence[str] = ("x", "y", "z"),
) -> tuple[int, list[tuple[int, int, list[float], list[float]]]]:
    columns = tuple(str(value) for value in coordinate_columns)
    if columns not in {("x", "y", "z"), ("xu", "yu", "zu")}:
        raise ValueError("LAMMPS dump coordinate columns must be x/y/z or xu/yu/zu")
    dump_fields = ("id", "type", *columns, "fx", "fy", "fz")
    all_lines = text.splitlines()
    frame_starts = [index for index, line in enumerate(all_lines) if line.strip() == "ITEM: TIMESTEP"]
    if not frame_starts:
        raise ValueError("LAMMPS dump.final is missing the native timestep header")
    lines = all_lines[frame_starts[-1] :]
    if len(lines) < 10:
        raise ValueError("LAMMPS dump.final is missing the final frame")
    step = _integer_token(lines[1].strip(), context="dump timestep")
    if lines[2].strip() != "ITEM: NUMBER OF ATOMS":
        raise ValueError("LAMMPS dump.final is missing the atom-count header")
    count = _integer_token(lines[3].strip(), context="dump atom count")
    if not lines[4].startswith("ITEM: BOX BOUNDS"):
        raise ValueError("LAMMPS dump.final is missing the box header")
    box_header = lines[4].split()
    if box_header[3:6] != ["xy", "xz", "yz"] or box_header[6:] != ["pp", "pp", "pp"]:
        raise ValueError("LAMMPS dump.final box header is not triclinic p p p")
    box_rows = np.asarray([_finite_row(lines[index].split(), context="dump box") for index in range(5, 8)], dtype=float)
    if box_rows.shape != (3, 3):
        raise ValueError("LAMMPS dump.final box must contain three rows")
    if not lines[8].startswith("ITEM: ATOMS "):
        raise ValueError("LAMMPS dump.final is missing the atom header")
    if tuple(lines[8].split()[2:]) != dump_fields:
        raise ValueError("LAMMPS dump.final atom columns differ from the fixed custom dump")
    if count < 1 or len(lines) < 9 + count:
        raise ValueError("LAMMPS dump.final atom rows are incomplete")
    rows = []
    for line in lines[9 : 9 + count]:
        tokens = line.split()
        if len(tokens) != len(dump_fields):
            raise ValueError("LAMMPS dump.final atom row has the wrong column count")
        atom_id = _integer_token(tokens[0], context="dump atom id")
        atom_type = _integer_token(tokens[1], context="dump atom type")
        values = _finite_row(tokens[2:], context="dump atom")
        rows.append((atom_id, atom_type, values[:3], values[3:]))
    ids = [row[0] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("LAMMPS dump.final contains duplicate atom IDs")
    expected_entries = atom_map["atoms"]
    if count != len(expected_entries):
        raise ValueError("LAMMPS dump atom count differs from atom map")
    expected_by_id = {int(entry["lammps_id"]): entry for entry in expected_entries}
    if set(ids) != set(expected_by_id):
        raise ValueError("LAMMPS dump atom IDs differ from atom map")
    for atom_id, atom_type, _, _ in rows:
        if atom_type != int(expected_by_id[atom_id]["type"]):
            raise ValueError("LAMMPS dump atom type differs from atom map")
    prism_values = [float(value) for value in atom_map["lammps_prism"]]
    observed = _prism_from_lammps_bounds(box_rows)
    if not np.allclose(observed, prism_values, rtol=0.0, atol=1.0e-7):
        raise ValueError("LAMMPS dump box differs from atom-map Prism cell")
    return step, rows


def _compare_md_final_frames(
    trajectory_step: int,
    trajectory_rows: Sequence[tuple[int, int, Sequence[float], Sequence[float]]],
    final_step: int,
    final_rows: Sequence[tuple[int, int, Sequence[float], Sequence[float]]],
) -> None:
    """Compare MD trajectory and final dump rows by native atom ID."""

    if trajectory_step != final_step:
        raise ValueError("LAMMPS trajectory and dump.final steps differ")
    trajectory_by_id = {int(row[0]): row for row in trajectory_rows}
    final_by_id = {int(row[0]): row for row in final_rows}
    if set(trajectory_by_id) != set(final_by_id):
        raise ValueError("LAMMPS trajectory and dump.final atom IDs differ")
    for atom_id in sorted(final_by_id):
        trajectory_row = trajectory_by_id[atom_id]
        final_row = final_by_id[atom_id]
        if int(trajectory_row[1]) != int(final_row[1]):
            raise ValueError("LAMMPS trajectory and dump.final atom types differ")
        if not np.allclose(
            np.asarray(trajectory_row[2], dtype=float),
            np.asarray(final_row[2], dtype=float),
            rtol=0.0,
            atol=1.0e-12,
        ):
            raise ValueError("LAMMPS trajectory and dump.final coordinates differ in angstrom")
        if not np.allclose(
            np.asarray(trajectory_row[3], dtype=float),
            np.asarray(final_row[3], dtype=float),
            rtol=0.0,
            atol=1.0e-12,
        ):
            raise ValueError("LAMMPS trajectory and dump.final forces differ in eV/A")


def parse_lammps_outputs(directory: str | Path) -> dict[str, Any]:
    """Parse the fixed native log and final custom dump into source order."""

    output = Path(directory)
    method_path = output / "method.json"
    map_path = output / "atom-map.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    atom_map = json.loads(map_path.read_text(encoding="utf-8"))
    potential = method["potential"]
    protocol = method["protocol"]
    if protocol.get("kind") == "interface_normal":
        from .lammps_interface_normal import parse_normal_outputs

        return parse_normal_outputs(output, method, atom_map)
    if protocol.get("kind") == "interface_tangential":
        from .lammps_interface_normal import parse_tangential_outputs

        return parse_tangential_outputs(output, method, atom_map)
    units = str(method["units"])
    atom_style = str(method["atom_style"])
    _validate_units_style(units, atom_style)
    validate_lammps_protocol(protocol)
    map_elements = [str(value) for value in atom_map["element_order"]]
    _validate_potential(
        potential,
        model_id=str(method["model_id"]),
        model_elements=[str(entry["element"]) for entry in atom_map["atoms"]],
        element_order=map_elements,
        units=units,
        atom_style=atom_style,
        protocol=protocol,
    )
    model_data_path = output / "model.data"
    model_data_path.stat()
    staged_potential_paths: list[tuple[str, Path]] = []
    for item in potential["files"]:
        filename = Path(str(item["filename"]))
        if filename.is_absolute() or ".." in filename.parts:
            raise ValueError("LAMMPS staged potential filename must stay inside the task directory")
        staged_path = output / filename
        staged_path.stat()
        staged_potential_paths.append((filename.as_posix(), staged_path))
    if method["production_qualification"] is not False:
        raise ValueError("LAMMPS result production_qualification must remain false")
    if atom_map["model_id"] != method["model_id"] or atom_map["version"] != method["version"]:
        raise ValueError("LAMMPS atom map identity differs from method.json")
    if atom_map["units"] != units or atom_map["atom_style"] != atom_style:
        raise ValueError("LAMMPS atom map units or atom_style differs from method.json")
    if [str(value) for value in method["element_order"]] != map_elements:
        raise ValueError("LAMMPS method and atom map element_order differ")
    map_source_ids = [int(value) for value in atom_map["source_atom_ids"]]
    map_entries_by_source = sorted(atom_map["atoms"], key=lambda entry: int(entry["source_index"]))
    if map_source_ids != [int(entry["source_atom_id"]) for entry in map_entries_by_source]:
        raise ValueError("LAMMPS atom map source IDs are inconsistent")
    bulk_thermal = None
    dump_atom_map = atom_map
    if protocol.get("purpose") == "md_bulk_thermal":
        from .lammps_bulk_thermal import read_bulk_thermal_outputs

        bulk_thermal = read_bulk_thermal_outputs(output, protocol, atom_map)
        final_bulk_frame = bulk_thermal["frames"][-1]
        # The original atom map remains the initial-cell mapping.  Only the
        # final dump's expected box follows the native NPT cell.
        dump_atom_map = {**atom_map, "lammps_prism": final_bulk_frame["lammps_prism"]}
    trajectory_path: Path | None = None
    trajectory_rows: list[tuple[int, int, list[float], list[float]]] | None = None
    trajectory_step: int | None = None
    if protocol["kind"] == "md":
        trajectory_path = output / "trajectory.lammpstrj"
        trajectory_path.stat()
        trajectory_step, trajectory_rows = _parse_dump(
            trajectory_path.read_text(encoding="utf-8"), dump_atom_map
        )
        if trajectory_step != int(protocol["steps"]):
            raise ValueError("LAMMPS trajectory final step differs from protocol")
    log_path = output / "log.lammps"
    dump_path = output / "dump.final"
    input_path = output / "in.lammps"
    log_text = log_path.read_text(encoding="utf-8")
    lammps_version = _validate_native_log(log_text)
    _validate_native_input_echo(
        log_text,
        input_path.read_text(encoding="utf-8"),
        potential,
        protocol,
        atom_map["masses_by_type"],
        atom_map=atom_map,
    )
    if bulk_thermal is None:
        thermo = _parse_thermo(log_text, protocol)
    else:
        thermo = {
            "step": final_bulk_frame["step"],
            "temp": final_bulk_frame["temperature_K"],
            "pe": final_bulk_frame["potential_energy_eV"],
            "ke": final_bulk_frame["kinetic_energy_eV"],
            "etotal": final_bulk_frame["total_energy_eV"],
            "press": final_bulk_frame["pressure_bar"],
        }
    dump_step, dump_rows = _parse_dump(
        dump_path.read_text(encoding="utf-8"), dump_atom_map
    )
    if dump_step != int(thermo["step"]):
        raise ValueError("LAMMPS dump step differs from thermo step")
    if trajectory_rows is not None and trajectory_step is not None:
        _compare_md_final_frames(trajectory_step, trajectory_rows, dump_step, dump_rows)
    source_entries = map_entries_by_source
    if [int(entry["source_index"]) for entry in source_entries] != list(range(len(source_entries))):
        raise ValueError("LAMMPS atom map source indices are not stable source order")
    positions_by_id = {row[0]: row[2] for row in dump_rows}
    forces_by_id = {row[0]: row[3] for row in dump_rows}
    source_cell = np.asarray(atom_map["source_cell_angstrom"], dtype=float)
    prism = Prism(source_cell, pbc=True, reduce_cell=False)
    lammps_positions = np.asarray(
        [positions_by_id[int(entry["lammps_id"])] for entry in source_entries], dtype=float
    )
    lammps_forces = np.asarray(
        [forces_by_id[int(entry["lammps_id"])] for entry in source_entries], dtype=float
    )
    source_positions = prism.vector_to_ase(lammps_positions, wrap=bulk_thermal is None).tolist()
    source_forces = prism.vector_to_ase(lammps_forces, wrap=False).tolist()
    source_ids = [int(entry["source_atom_id"]) for entry in source_entries]
    result = {
        "schema": "mlcc.lammps-result.v1",
        "engine": "lammps",
        "engine_version": lammps_version,
        "lammps_version": lammps_version,
        "model_id": method["model_id"],
        "version": method["version"],
        "units": units,
        "atom_style": atom_style,
        "step": int(thermo["step"]),
        "thermo": thermo,
        "thermo_units": {
            "temp": "K",
            "pe": "eV",
            "ke": "eV",
            "etotal": "eV",
            "press": "bar",
        },
        "energy_eV": float(thermo["pe"]),
        "potential_energy_eV": float(thermo["pe"]),
        "temperature_K": float(thermo["temp"]),
        "pressure_bar": float(thermo["press"]),
        "pressure_GPa": float(thermo["press"]) * 1.0e-4,
        "atom_ids": source_ids,
        "types": [int(entry["type"]) for entry in source_entries],
        "elements": [str(entry["element"]) for entry in source_entries],
        "positions_angstrom": source_positions,
        "forces_eV_per_A": source_forces,
        "cell_angstrom": source_cell.tolist(),
        "potential": potential,
        "protocol": protocol,
        "production_qualification": False,
        "source_files": {
            "method.json": str(method_path),
            "atom-map.json": str(map_path),
            "in.lammps": str(input_path),
            "model.data": str(model_data_path),
            "log.lammps": str(log_path),
            "dump.final": str(dump_path),
        },
    }
    if protocol.get("static_tensor", False):
        result.update(pressure_tensor_to_source(
            [thermo[name.lower()] for name in _PRESSURE_FIELDS], source_cell
        ))
        result["thermo_units"].update({name.lower(): "bar" for name in _PRESSURE_FIELDS})
    if bulk_thermal is not None:
        result["cell_angstrom"] = final_bulk_frame["cell_angstrom"]
        result["cell_origin_angstrom"] = prism.vector_to_ase(
            np.asarray([final_bulk_frame["origin_lammps_angstrom"]]), wrap=False
        )[0].tolist()
        result["bulk_thermal_series"] = bulk_thermal
    if protocol.get("purpose") == "bulk_thermal_transport":
        from .lammps_bulk_heat import read_bulk_heat_outputs

        result["bulk_heat_source"] = read_bulk_heat_outputs(output, protocol, atom_map)
        result["source_files"].update(result["bulk_heat_source"]["source_files"])
    for filename, staged_path in staged_potential_paths:
        result["source_files"][filename] = str(staged_path)
    if trajectory_path is not None:
        result["source_files"]["trajectory.lammpstrj"] = str(trajectory_path)
    if protocol.get("purpose") == "md_native_sampling":
        from .lammps_md_sampling import md_sampling_output_files

        for filename in [*md_sampling_output_files(protocol), "trajectory.unwrapped.lammpstrj"]:
            source_path = output / filename
            source_path.stat()
            result["source_files"][filename] = str(source_path)
    return result
