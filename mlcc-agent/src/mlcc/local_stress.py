"""Direct local virial-stress consumption for explicit atom groups."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

import numpy as np
from ase.calculators.lammps import Prism

from .lammps import pressure_tensor_to_source
from .md_thermo import _observation_rows


REQUEST_SCHEMA = "mlcc.local-stress-analysis.v1"
RESPONSE_SCHEMA = "mlcc.local-stress-response.v1"
SCOPE = "fixed_atom_group_virial_average"
STRESS_VOLUME_COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz"]
STRESS_VOLUME_COMPONENT_ORDER_CENTROID = [
    "xx",
    "yy",
    "zz",
    "xy",
    "xz",
    "yz",
    "yx",
    "zx",
    "zy",
]
STRESS_VOLUME_BASIS = "lammps_prism"


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _validate_regions(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    regions = list(request["regions"])
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for region in regions:
        region_id = region["region_id"]
        if not isinstance(region_id, str) or not region_id.strip() or region_id in seen:
            raise ValueError("region_id must be non-empty and unique")
        atom_ids = list(region["atom_ids"])
        if not atom_ids or any(type(atom_id) is not int for atom_id in atom_ids):
            raise ValueError(f"region {region_id} atom_ids must be non-empty source integer IDs")
        if len(set(atom_ids)) != len(atom_ids):
            raise ValueError(f"region {region_id} atom_ids must be unique")
        volume = region["volume_angstrom3"]
        definition = region["volume_definition"]
        if volume is None:
            if definition is not None and (not isinstance(definition, str) or not definition.strip()):
                raise ValueError(f"region {region_id} volume_definition must be non-empty when present")
        else:
            volume = _finite(volume, f"region {region_id} volume_angstrom3")
            if volume <= 0.0:
                raise ValueError(f"region {region_id} volume_angstrom3 must be positive")
            if not isinstance(definition, str) or not definition.strip():
                raise ValueError(f"region {region_id} volume_definition is required with explicit volume")
        seen.add(region_id)
        validated.append(
            {
                "region_id": region_id,
                "atom_ids": atom_ids,
                "volume_angstrom3": volume,
                "volume_definition": definition,
            }
        )
    return validated


def _validate_request(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError(f"local stress request schema must be {REQUEST_SCHEMA}")
    return _validate_regions(request)


def _component_order(component_order: Sequence[str] | None) -> tuple[list[str], bool]:
    """Resolve the explicit stress component contract.

    The historical six component path is selected when the caller omits
    ``component_order`` or supplies its exact order.  The nine component
    centroid path requires the exact asymmetric order emitted by the native
    adapter; in particular, the array width is never used to infer a
    component convention.
    """

    if component_order is None:
        return list(STRESS_VOLUME_COMPONENT_ORDER), False
    order = list(component_order)
    if order == STRESS_VOLUME_COMPONENT_ORDER:
        return order, False
    if order != STRESS_VOLUME_COMPONENT_ORDER_CENTROID:
        raise ValueError(
            "component_order must be exactly six-component "
            f"{STRESS_VOLUME_COMPONENT_ORDER} or nine-component "
            f"{STRESS_VOLUME_COMPONENT_ORDER_CENTROID}"
        )
    return order, True


def _frame_arrays(
    frame: Mapping[str, Any], component_order: Sequence[str]
) -> tuple[dict[int, int], np.ndarray]:
    if "component_order" in frame and frame["component_order"] != list(component_order):
        raise ValueError("frame component_order differs from the declared component_order")
    if type(frame["step"]) is not int:
        raise ValueError("frame step must be an integer")
    _finite(frame["physical_time_ps"], "frame physical_time_ps")
    atom_ids = list(frame["atom_ids"])
    if any(type(atom_id) is not int for atom_id in atom_ids):
        raise ValueError("frame atom_ids must be source integer IDs")
    if len(set(atom_ids)) != len(atom_ids):
        raise ValueError("frame atom_ids must be unique")
    components = np.asarray(frame["stress_volume_components_bar_A3"], dtype=float)
    component_count = len(component_order)
    if components.shape != (len(atom_ids), component_count):
        raise ValueError(
            "stress_volume_components_bar_A3 must have one "
            f"{component_count}-component row per atom for component_order "
            f"{list(component_order)}"
        )
    if not np.all(np.isfinite(components)):
        raise ValueError("stress_volume_components_bar_A3 must be finite")
    return {atom_id: index for index, atom_id in enumerate(atom_ids)}, components


def _region_product(
    region: Mapping[str, Any],
    selected_frames: list[dict[str, Any]] | None,
    frame_arrays: list[tuple[dict[int, int], np.ndarray]] | None,
    source_cell_angstrom: Sequence[Sequence[float]],
    component_order: Sequence[str],
    centroid_components: bool,
) -> dict[str, Any]:
    region_id = region["region_id"]
    volume = region["volume_angstrom3"]
    definition = region["volume_definition"]
    product: dict[str, Any] = {
        "region_id": region_id,
        "atom_ids": list(region["atom_ids"]),
        "volume_source": {
            "volume_angstrom3": volume,
            "volume_definition": definition,
        },
        "stress_volume_component_order": list(component_order),
        "stress_volume_basis": STRESS_VOLUME_BASIS,
        "stress_volume_sum_bar_A3_by_frame": [],
        "stress_volume_sum_bar_A3_mean": None,
        "pressure_components_bar": None,
        "pressure_tensor_GPa": None,
        "stress_GPa": None,
        "stress_sign": "tension_positive",
        "tensor_basis": "source_cartesian",
        "status": "unresolved",
        "missing_evidence": [],
    }
    if selected_frames is None or not selected_frames or frame_arrays is None:
        product["missing_evidence"].append("selected_frames")
        if volume is None:
            product["missing_evidence"].append(f"region:{region_id}:volume_angstrom3")
        return product

    sums: list[np.ndarray] = []
    for frame, (atom_positions, components) in zip(selected_frames, frame_arrays):
        indices: list[int] = []
        for atom_id in region["atom_ids"]:
            if atom_id not in atom_positions:
                raise ValueError(f"region {region_id} atom ID {atom_id} is absent from frame step {frame['step']}")
            indices.append(atom_positions[atom_id])
        total = np.sum(components[indices], axis=0)
        sums.append(total)
        product["stress_volume_sum_bar_A3_by_frame"].append(
            {
                "step": frame["step"],
                "physical_time_ps": frame["physical_time_ps"],
                "components": total.tolist(),
            }
        )
    mean_sum = np.mean(np.asarray(sums, dtype=float), axis=0)
    product["stress_volume_sum_bar_A3_mean"] = mean_sum.tolist()
    if volume is None:
        product["status"] = "partial"
        product["missing_evidence"].append(f"region:{region_id}:volume_angstrom3")
        return product

    pressure_components = (-mean_sum / volume).tolist()
    if centroid_components:
        xx, yy, zz, xy, xz, yz, yx, zx, zy = pressure_components
        native_pressure = np.asarray(
            [[xx, xy, xz], [yx, yy, yz], [zx, zy, zz]], dtype=float
        )
        rotation = Prism(
            np.asarray(source_cell_angstrom, dtype=float),
            pbc=True,
            reduce_cell=False,
        ).rot_mat
        pressure = rotation @ native_pressure @ rotation.T * 1.0e-4
        product.update(
            {
                "status": "available",
                "pressure_components_bar": pressure_components,
                "pressure_tensor_GPa": pressure.tolist(),
                "stress_GPa": (-pressure).tolist(),
                "stress_sign": "tension_positive",
                "tensor_basis": "source_cartesian",
                "conversion": {
                    "pressure_component_order": list(component_order),
                    "pressure_sign": "compression_positive",
                    "stress_unit": "GPa",
                    "tensor_contribution": "virial_only_zero_velocity",
                    "formula": (
                        "pressure_bar=-stress_volume_sum_bar_A3_mean/volume_angstrom3; "
                        "native asymmetric tensor rotated via ASE Prism"
                    ),
                },
            }
        )
        return product

    converted = pressure_tensor_to_source(pressure_components, source_cell_angstrom)
    product.update(
        {
            "status": "available",
            "pressure_components_bar": pressure_components,
            "pressure_tensor_GPa": converted["pressure_tensor_GPa"],
            "stress_GPa": converted["stress_GPa"],
            "stress_sign": converted["stress_sign"],
            "tensor_basis": converted["tensor_basis"],
            "conversion": {
                "pressure_component_order": converted["pressure_component_order"],
                "pressure_sign": converted["pressure_sign"],
                "stress_unit": converted["stress_unit"],
                "tensor_contribution": converted["tensor_contribution"],
                "formula": "pressure_bar=-stress_volume_sum_bar_A3_mean/volume_angstrom3; source conversion via pressure_tensor_to_source",
            },
        }
    )
    return product


def local_stress_from_frames(
    request: Mapping[str, Any],
    frames: Sequence[Mapping[str, Any]] | None,
    source_cell_angstrom: Sequence[Sequence[float]],
    *,
    component_order: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Average explicit virial sums over selected frames and fixed atom groups."""

    regions = _validate_request(request)
    resolved_component_order, centroid_components = _component_order(component_order)
    source_cell = np.asarray(source_cell_angstrom, dtype=float)
    if source_cell.shape != (3, 3) or not np.all(np.isfinite(source_cell)):
        raise ValueError("source_cell_angstrom must be a finite 3x3 cell")

    raw_frames = None if frames is None else [dict(frame) for frame in frames]
    window = request["observation_window"]
    if raw_frames is None:
        selected_indices, selected_frames, selection_reason = None, None, "frames are missing"
    elif not raw_frames:
        selected_indices, selected_frames, selection_reason = None, None, "frames are empty"
    elif window is None:
        selected_indices, selected_frames, selection_reason = None, None, "observation_window is unresolved"
    else:
        selected_indices, selected = _observation_rows(raw_frames, window)
        selected_frames, selection_reason = [dict(frame) for frame in selected], None

    frame_arrays = (
        None
        if selected_frames is None
        else [_frame_arrays(frame, resolved_component_order) for frame in selected_frames]
    )
    region_products = [
        _region_product(
            region,
            selected_frames,
            frame_arrays,
            source_cell_angstrom,
            resolved_component_order,
            centroid_components,
        )
        for region in regions
    ]
    missing_evidence: list[str] = []
    if window is None:
        missing_evidence.append("observation_window")
    if raw_frames is None or not raw_frames:
        missing_evidence.append("frames")
    if not regions:
        missing_evidence.append("regions")
    for region in region_products:
        missing_evidence.extend(
            item for item in region["missing_evidence"] if item != "selected_frames"
        )

    if selection_reason is not None or not raw_frames or raw_frames is None or not regions:
        status = "unresolved"
    elif all(region["status"] == "available" for region in region_products):
        status = "available"
    else:
        status = "partial"

    source_kind = request.get("source_kind")
    fixture_purpose = request.get("fixture_purpose")
    if status == "available" and (source_kind == "mathematical_fixture" or fixture_purpose == "mathematical_fixture"):
        status = "mathematical_fixture"
    return {
        "schema": RESPONSE_SCHEMA,
        "status": status,
        "production_qualified": False,
        "source": {
            "kind": source_kind,
            "fixture": request.get("fixture"),
            "fixture_purpose": fixture_purpose,
        },
        "request": copy.deepcopy(dict(request)),
        "observation_window": copy.deepcopy(window),
        "scope": SCOPE,
        "contribution": "virial",
        "kinetic_included": False,
        "stress_volume_component_order": list(resolved_component_order),
        "stress_volume_basis": STRESS_VOLUME_BASIS,
        "thermal_stress": None,
        "thermal_stress_status": {
            "status": "unresolved",
            "reason": "no explicit stress-free reference or thermal history",
        },
        "source_cell_angstrom": source_cell.tolist(),
        "raw_frames": raw_frames,
        "selected_indices": selected_indices,
        "selected_frames": selected_frames,
        "selection_status": "available" if selection_reason is None else "unresolved",
        "selection_reason": selection_reason,
        "regions": region_products,
        "missing_evidence": list(dict.fromkeys(missing_evidence)),
        "units": {
            "stress_volume": "bar*angstrom^3",
            "pressure": "bar",
            "stress": "GPa",
            "volume": "angstrom^3",
            "time": "ps",
        },
    }


__all__ = ["local_stress_from_frames"]
