"""Explicit windows on saved local-ionic + Hartree electron-potential grids.

phi[V] = -Ue[eV]; E_normal[V/angstrom] = +dUe/ds. These are unsmoothed
plane-mean component secants, not a macroscopic field or dielectric response.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

import numpy as np

from .potential_alignment import _grid

_METHOD_FIELDS = (
    "engine", "abacus_version_target", "stage", "model_id", "version", "dft_functional",
    "basis_type", "nspin", "lspinorb", "noncolin", "initial_moments_muB_by_element",
    "occupations", "smearing_method", "symmetry", "net_charge", "nelec", "nelec_delta",
    "charge_convention", "element_order", "kpoints", "kpoint_rule", "parameters",
    "pseudopotential_ids", "pseudopotential_treatment",
)
_PP_FIELDS = (
    "element", "functional", "valence_electrons_per_atom", "relativity",
    "has_spin_orbit", "type",
)
_CONTROL_FIELDS = (
    "efield_flag", "dip_cor_flag", "gate_flag", "imp_sol", "efield_dir", "efield_pos_max",
    "efield_pos_dec", "efield_amp", "gate_pos", "gate_relax", "zgate",
    "block", "block_down", "block_up", "block_height", "relax",
    "use_paw", "lspinorb", "noncolin", "vl_in_h", "vion_in_h", "vh_in_h",
)


def _physical_method(method: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{key: method[key] for key in _METHOD_FIELDS},
        "pseudopotential_metadata": {
            element: {key: header[key] for key in _PP_FIELDS}
            for element, header in method["pseudopotential_metadata"].items()
        },
        "optional_parameters": {
            key: {"present": key in method, "value": method.get(key)}
            for key in ("kpoint_shift", "gamma_only", "init_chg", "pw_diag_thr", "numerical_orbital_ids")
        },
        "numerical_orbitals": {
            "present": "numerical_orbitals" in method,
            "files": {element: {key: value for key, value in orbital.items() if key != "source"}
                      for element, orbital in method.get("numerical_orbitals", {}).items()},
        },
    }


def _atom_mapping(atom_map: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{key: atom_map[key] for key in
           ("schema", "model_id", "version", "source_atom_ids", "element_order")},
        "abacus_order": [
            {key: entry[key] for key in ("abacus_index", "source_index", "atom_id", "element")}
            for entry in sorted(atom_map["abacus_order"], key=lambda item: item["abacus_index"])
        ],
    }


def _controls(potential: Mapping[str, Any]) -> dict[str, Any]:
    # The native product preserves requested INPUT and native OUT.INPUT separately.
    inputs = potential["input_parameters"]
    return {
        "conditions": deepcopy(potential["conditions"]),
        "input_parameters": {
            section: {key: {"present": key in inputs[section], "value": inputs[section].get(key)}
                      for key in _CONTROL_FIELDS}
            for section in ("INPUT", "OUT.INPUT")
        },
    }


def validate_electrical_selection(selection: Mapping[str, Any], shape: tuple[int, ...] | None = None) -> None:
    """Validate explicit windows; a missing-source request has no grid upper bound yet."""
    axis = selection["grid_axis"]
    if type(axis) is not int or axis not in (0, 1, 2):
        raise ValueError("grid_axis must be 0, 1 or 2")
    if type(selection["orientation"]) is not int or selection["orientation"] not in (-1, 1):
        raise ValueError("orientation must be +1 or -1")
    if len(selection["boundary"]) != 3 or any(value not in ("p", "f") for value in selection["boundary"]):
        raise ValueError("boundary must contain three p/f values")
    if selection["derivative"] != "adjacent_planes_no_wrap":
        raise ValueError("derivative must be adjacent_planes_no_wrap")
    if not isinstance(selection["source"], str) or not selection["source"].strip():
        raise ValueError("selection source must be explicit")
    regions = selection["regions"]
    if set(regions) != {"from", "to"}:
        raise ValueError("regions must contain exactly from and to")
    for region in regions.values():
        for key in ("region_id", "reason"):
            if not isinstance(region[key], str) or not region[key].strip():
                raise ValueError(f"region {key} must be explicit")
        bounds = region["index_range"]
        if len(bounds) != 2 or any(type(value) is not int for value in bounds):
            raise ValueError("index_range must contain two integers")
        lo, hi = bounds
        if not 0 <= lo < hi or (shape is not None and hi > shape[axis]):
            raise ValueError("region must be a nonempty in-grid half-open range")
    left, right = regions["from"], regions["to"]
    if left["region_id"] == right["region_id"]:
        raise ValueError("region IDs must differ")
    if max(left["index_range"][0], right["index_range"][0]) < min(left["index_range"][1], right["index_range"][1]):
        raise ValueError("region windows must not overlap")


def grid_normal(cube: Mapping[str, Any], axis: int) -> np.ndarray:
    """Unit transverse-plane normal pointing toward increasing selected grid index."""
    steps = np.asarray(cube["step_vectors_angstrom"], dtype=float)
    other = [index for index in range(3) if index != axis]
    normal = np.cross(steps[other[0]], steps[other[1]])
    length = np.linalg.norm(normal)
    if not np.isfinite(length) or length == 0:
        raise ValueError("transverse grid vectors must span a plane")
    normal = normal / length
    projection = float(steps[axis] @ normal)
    if not np.isfinite(projection) or projection == 0:
        raise ValueError("selected grid step must have a nonzero normal projection")
    return normal if projection > 0 else -normal


def _profile(potential: Mapping[str, Any], selection: Mapping[str, Any], shape: tuple[int, ...], values: np.ndarray) -> dict[str, Any]:
    axis = selection["grid_axis"]
    if shape[axis] < 2:
        raise ValueError("field requires at least two native grid planes")
    cube = potential["cube"]
    normal = grid_normal(cube, axis) * selection["orientation"]
    step = np.asarray(cube["step_vectors_angstrom"][axis])
    spacing = float(step @ normal)
    origin = float(np.asarray(cube["origin_angstrom"]) @ normal)
    positions = origin + np.arange(shape[axis]) * spacing
    means = values.mean(axis=tuple(index for index in range(3) if index != axis))
    regions = {}
    for name, region in selection["regions"].items():
        lo, hi = region["index_range"]
        selected = means[lo:hi]
        spread = float(selected.std(ddof=0))
        regions[name] = {
            **deepcopy(region), "plane_count": hi - lo,
            "grid_point_count": (hi - lo) * int(np.prod(shape)) // shape[axis],
            "mean_position_angstrom": float(positions[lo:hi].mean()),
            "mean_electron_potential_energy_eV": float(selected.mean()),
            "mean_potential_V": float(-selected.mean()),
            "spread": {"electron_potential_energy_eV": spread, "potential_V": spread},
            "spread_definition": "population spread of plane means, not independent-sample uncertainty",
        }
    left, right = regions["from"], regions["to"]
    delta_u = right["mean_electron_potential_energy_eV"] - left["mean_electron_potential_energy_eV"]
    delta_s = right["mean_position_angstrom"] - left["mean_position_angstrom"]
    identity_fields = ("task_id", "scheduler_job_id", "study_id", "model_id", "model_version", "method_set",
                       "source_files", "status", "native_output_observed", "native_GPU_accepted")
    return {
        "identity": {key: deepcopy(potential.get(key)) for key in identity_fields},
        "normal_cartesian": normal.tolist(), "normal_spacing_angstrom": spacing,
        "plane_profile": [
            {"plane_index": index, "position_angstrom": float(position),
             "mean_electron_potential_energy_eV": float(value), "potential_V": float(-value)}
            for index, (position, value) in enumerate(zip(positions, means))
        ],
        "adjacent_plane_secants": [
            {"left_plane_index": index, "right_plane_index": index + 1,
             "midpoint_position_angstrom": float((positions[index] + positions[index + 1]) / 2),
             "field_V_per_angstrom": float((means[index + 1] - means[index]) / spacing)}
            for index in range(shape[axis] - 1)
        ],
        "regions": regions,
        "regional_response": {"delta_Ue_eV": delta_u, "delta_phi_V": -delta_u,
                              "delta_s_angstrom": delta_s, "secant_field_V_per_angstrom": delta_u / delta_s},
        "energy_zero": deepcopy(potential["energy_zero"]),
        "electrostatic_controls": _controls(potential),
    }


def _reference_pair(target: Mapping[str, Any], reference: Mapping[str, Any]) -> None:
    for key in ("model_id", "model_version", "method_set", "kind", "sign_convention", "energy_zero"):
        if target[key] != reference[key]:
            raise ValueError(f"reference {key} differs from target")
    if _physical_method(target["method"]) != _physical_method(reference["method"]):
        raise ValueError("reference physical method differs from target")
    if _atom_mapping(target["atom_map"]) != _atom_mapping(reference["atom_map"]):
        raise ValueError("reference atom mapping differs from target")
    if _controls(target) != _controls(reference):
        raise ValueError("reference external-field or boundary controls differ from target")
    for key in ("shape", "origin_bohr", "step_vectors_bohr", "cell_bohr"):
        if target["cube"][key] != reference["cube"][key]:
            raise ValueError(f"reference grid {key} differs; no resampling")


def calculate_interface_electrical(
    potential: Mapping[str, Any], selection: Mapping[str, Any],
    reference_potential: Mapping[str, Any] | None = None, *, reference_description: str | None = None,
) -> dict[str, Any]:
    """Calculate explicit region/adjacent-plane secants; never read native files."""
    shape, values = _grid(potential)
    validate_electrical_selection(selection, shape)
    target = _profile(potential, selection, shape, values)
    fixture = potential.get("evidence_kind") == "software_contract_only" or potential["cube"].get("evidence_kind") == "software_contract_only"
    result = {
        "schema": "mlcc.interface-electrical-response.v1", "status": "saved_grid_arithmetic_only",
        "selection": deepcopy(dict(selection)), "boundary": deepcopy(selection["boundary"]),
        "grid_shape": list(shape), "normal_cartesian": target["normal_cartesian"],
        "normal_spacing_magnitude_angstrom": abs(target["normal_spacing_angstrom"]),
        "target": target, "reference": None, "reference_comparison": None,
        "sign_convention": "phi_V=-Ue_eV; E_normal=+dUe/ds=-dphi/ds",
        "field_scope": "unsmoothed plane-average local-ionic+Hartree component secants; excludes XC/nonlocal terms; no periodic wrap or inferred macroscopic field",
        "absolute_gauge_note": "Each state's absolute potential retains its source gauge; only regional/field differences are compared.",
        "evidence_kind": "software_contract_only" if fixture else "saved_grid_arithmetic_only",
        "scientific_qualification": False, "production_qualification": False,
    }
    if reference_potential is None:
        if reference_description is not None:
            raise ValueError("reference_description requires reference_potential")
        return result
    if not isinstance(reference_description, str) or not reference_description.strip():
        raise ValueError("reference_description is required")
    _reference_pair(potential, reference_potential)
    reference_shape, reference_values = _grid(reference_potential)
    reference = _profile(reference_potential, selection, reference_shape, reference_values)
    result["reference"] = reference
    if reference_potential.get("evidence_kind") == "software_contract_only" or reference_potential["cube"].get("evidence_kind") == "software_contract_only":
        result["evidence_kind"] = "software_contract_only"
    target_region, reference_region = target["regional_response"], reference["regional_response"]
    result["reference_comparison"] = {
        "description": reference_description, "direction": "target_minus_reference",
        "delta_delta_phi_V": target_region["delta_phi_V"] - reference_region["delta_phi_V"],
        "delta_delta_Ue_eV": target_region["delta_Ue_eV"] - reference_region["delta_Ue_eV"],
        "delta_secant_field_V_per_angstrom": target_region["secant_field_V_per_angstrom"] - reference_region["secant_field_V_per_angstrom"],
        "adjacent_field_differences_V_per_angstrom": [
            target_field["field_V_per_angstrom"] - reference_field["field_V_per_angstrom"]
            for target_field, reference_field in zip(target["adjacent_plane_secants"], reference["adjacent_plane_secants"])
        ],
        "absolute_profile_difference": None,
    }
    return result
