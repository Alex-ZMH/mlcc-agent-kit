"""Explicit-region electron potential-energy differences, without corrections.

Saved task sources and explicit atom lineage establish provenance. Neither a
region average nor a shifted VBM candidate establishes a physical far field.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .defect_references import build_defect_electronic_reference
from .electrostatic_potential import RY_TO_EV, BOHR_TO_ANGSTROM, HEADER_HALF_QUANTUM_BOHR


_ENERGY_ZERO = {
    "Hartree_G0": "zero", "local_ionic_G0": "retained_pseudopotential_convention",
    "total_mean_subtracted": False, "fermi_subtracted": False, "vacuum_subtracted": False,
}
_UNQUALIFIED = {
    "potential_alignment_eV": None, "aligned_host_vbm_eV": None, "correction_terms": None,
    "FNV_eFNV_correction_eV": None, "charged_formation_energy_eV": None,
    "native_alignment_accepted": False, "scientific_qualification": False, "production_qualification": False,
}


def _read(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _software(potential: Mapping[str, Any]) -> bool:
    return potential.get("evidence_kind") == "software_contract_only" or potential["cube"]["evidence_kind"] == "software_contract_only"


def _grid(potential: Mapping[str, Any]) -> tuple[tuple[int, int, int], np.ndarray]:
    if potential["schema"] != "mlcc.abacus-electrostatic-potential.v1":
        raise ValueError("a saved task potential is required, not a bare cube")
    if (potential["kind"], potential["value_unit"], potential["geometry_unit"], potential["sign_convention"]) != (
        "local_ionic_plus_hartree", "Ry", "Bohr", "electron_potential_energy"
    ):
        raise ValueError("potential kind, units or electron-energy sign convention differs")
    if potential["energy_zero"] != _ENERGY_ZERO:
        raise ValueError("potential must retain its original zero without mean/Fermi/vacuum subtraction")
    if potential["includes_XC"] is not False or potential["includes_nonlocal_pseudopotential"] is not False:
        raise ValueError("selected potential must contain only local ionic plus Hartree terms")
    cube = potential["cube"]
    if cube["schema"] != "mlcc.abacus-electrostatic-cube.v1":
        raise ValueError("unsupported saved cube schema")
    shape = tuple(cube["shape"])
    if len(shape) != 3 or any(type(n) is not int or n <= 0 for n in shape):
        raise ValueError("grid shape must have three positive integer dimensions")
    if (cube["axis_order"], cube["flat_index"]) != ("x_outer_y_middle_z_inner", "(ix*ny+iy)*nz+iz"):
        raise ValueError("potential requires explicit z-fast grid indexing")
    conversion = cube["unit_conversion"]
    if conversion["Ry_to_eV"] != RY_TO_EV or conversion["Bohr_to_angstrom"] != BOHR_TO_ANGSTROM:
        raise ValueError("potential conversion differs from ABACUS 3.10.1 constants")
    geometries = {}
    for name, dims in (("origin", (3,)), ("step_vectors", (3, 3)), ("cell", (3, 3))):
        bohr, angstrom = np.asarray(cube[f"{name}_bohr"], dtype=float), np.asarray(cube[f"{name}_angstrom"], dtype=float)
        if bohr.shape != dims or angstrom.shape != dims or not np.isfinite(bohr).all() or not np.isfinite(angstrom).all():
            raise ValueError(f"invalid {name} geometry")
        if not np.allclose(angstrom, bohr * BOHR_TO_ANGSTROM, rtol=0, atol=1e-10):
            raise ValueError(f"{name} Bohr/angstrom conversion differs")
        geometries[name] = bohr
    if np.linalg.det(geometries["step_vectors"]) == 0 or not np.allclose(
        geometries["cell"], geometries["step_vectors"] * np.asarray(shape)[:, None], rtol=0, atol=1e-10
    ):
        raise ValueError("grid step vectors and shape do not define the recorded cell")
    ry, ev = np.asarray(cube["values_Ry"], dtype=float), np.asarray(cube["values_eV"], dtype=float)
    if ry.shape != (int(np.prod(shape)),) or ev.shape != ry.shape or not np.isfinite(ry).all() or not np.isfinite(ev).all():
        raise ValueError("potential scalar count or finite-value contract differs")
    if not np.allclose(ev, ry * RY_TO_EV, rtol=0, atol=1e-10):
        raise ValueError("saved Ry/eV potential conversion differs")
    return shape, (ry * RY_TO_EV).reshape(shape)


def _region(selection: Mapping[str, Any], shape: tuple[int, int, int]) -> np.ndarray:
    if selection["kind"] != "index_boxes":
        raise ValueError("only explicit index_boxes are supported")
    for key in ("reason", "source"):
        if not isinstance(selection[key], str) or not selection[key].strip():
            raise ValueError(f"selection {key} must be explicit")
    if not selection["boxes"]:
        raise ValueError("selection must contain at least one nonempty box")
    mask = np.zeros(shape, dtype=bool)
    for box in selection["boxes"]:
        lower, upper = box["lower"], box["upper"]
        if len(lower) != 3 or len(upper) != 3 or any(type(v) is not int for v in [*lower, *upper]):
            raise ValueError("region bounds must be three integer indices")
        if any(not 0 <= lo < hi <= n for lo, hi, n in zip(lower, upper, shape)):
            raise ValueError("region must be a nonempty in-grid half-open box")
        mask[tuple(slice(lo, hi) for lo, hi in zip(lower, upper))] = True
    return mask


def calculate_regional_potential_difference(
    host_potential: Mapping[str, Any], defect_potential: Mapping[str, Any], selection: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute mean_R(Vdefect - Vhost); no q factor or correction energy."""
    host_shape, host_values = _grid(host_potential)
    defect_shape, defect_values = _grid(defect_potential)
    if host_shape != defect_shape:
        raise ValueError("host and defect grid shapes differ; resampling is unsupported")
    # Two printed headers each carry a half-quantum uncertainty in Bohr.
    for key in ("origin_bohr", "step_vectors_bohr", "cell_bohr"):
        tolerance = 2 * HEADER_HALF_QUANTUM_BOHR
        if key == "cell_bohr":
            tolerance = tolerance * np.asarray(host_shape)[:, None]
        if not np.all(np.abs(np.asarray(host_potential["cube"][key]) - np.asarray(defect_potential["cube"][key])) <= tolerance + 1e-12):
            raise ValueError(f"host and defect {key} differ beyond header print precision")
    mask = _region(selection, host_shape)
    host, defect = host_values[mask], defect_values[mask]
    difference = defect - host
    return {
        "schema": "mlcc.regional-potential-difference.v1",
        "delta_v_defect_minus_host_eV": float(np.mean(difference)),
        "sample_count": int(difference.size),
        "host_mean_eV": float(np.mean(host)), "defect_mean_eV": float(np.mean(defect)),
        "difference_min_eV": float(np.min(difference)), "difference_max_eV": float(np.max(difference)),
        "difference_population_std_eV": float(np.std(difference, ddof=0)),
        "difference_peak_to_peak_eV": float(np.ptp(difference)),
        "selection": deepcopy(dict(selection)), "grid_shape": list(host_shape),
        "difference_direction": "defect_minus_host_electron_potential_energy",
        "sampling": "equal-weight grid-point union; population standard deviation, not uncertainty of independent samples",
        "geometry_tolerance": "sum of two six-decimal Bohr header half-quanta; no spatial transform",
        "far_field_qualified": False,
        "evidence_kind": "software_contract_only" if _software(host_potential) or _software(defect_potential) else "saved_grid_arithmetic_only",
        **_UNQUALIFIED,
    }


def _check_lineage(pair: Mapping[str, Any]) -> dict:
    host, defect = pair["host"], pair["defect"]
    host_model, child_model = host["model"], defect["model"]
    parent = defect["parent_model"]
    if (parent["model_id"], parent["version"], str(Path(parent["path"]).resolve())) != (
        host_model["model_id"], host_model["version"], str(Path(host_model["path"]).resolve())
    ):
        raise ValueError("defect lineage does not refer to the host model")
    if host["charge"]["q"] != 0:
        raise ValueError("alignment host must be neutral")
    for source in (host, defect):
        if source["charge"]["convention"] != "q_positive_removes_electrons" or source["charge"]["q"] != source["method"]["net_charge"]:
            raise ValueError("charge sign or method/descriptor charge differs")
    descriptor = defect["defect_descriptor"]
    if descriptor["kind"] != "explicit_defect_sequence" or descriptor["charge_state"] != defect["charge"]["q"]:
        raise ValueError("explicit defect charge descriptor required")
    host_atoms = {a["atom_id"]: a for a in host_model["atoms"]}
    child_atoms = {a["atom_id"]: a for a in child_model["atoms"]}
    for model, atoms in ((host_model, host_atoms), (child_model, child_atoms)):
        if len(atoms) != len(model["atoms"]) or set(atoms) != set(model["atom_ids"]):
            raise ValueError("model atom IDs are not unique and complete")
    parent_counts = dict(Counter(a["element"] for a in host_atoms.values()))
    child_counts = dict(Counter(a["element"] for a in child_atoms.values()))
    delta = {e: child_counts.get(e, 0) - parent_counts.get(e, 0) for e in set(parent_counts) | set(child_counts) if child_counts.get(e, 0) != parent_counts.get(e, 0)}
    if descriptor["composition_parent"] != parent_counts or descriptor["composition_child"] != child_counts or descriptor["composition_delta"] != delta:
        raise ValueError("descriptor composition change differs from explicit model atoms")
    entries = child_model["atom_lineage"]
    if len(entries) != len(child_atoms) or {e["child_atom_id"] for e in entries} != set(child_atoms):
        raise ValueError("defect atom lineage must cover each child atom exactly once")
    expected = {atom_id: {"element": atom["element"], "parent_atom_id": atom_id, "kind": "retained_parent_atom"}
                for atom_id, atom in host_atoms.items()}
    for operation in descriptor["operations"]:
        kind = operation["kind"]
        if kind == "vacancy":
            removed = expected.pop(operation["atom_id"])
            if removed["element"] != operation["element"]:
                raise ValueError("vacancy descriptor element differs from parent sequence")
        elif kind == "substitution":
            atom = expected[operation["atom_id"]]
            if atom["element"] != operation["old_element"]:
                raise ValueError("substitution descriptor element differs from parent sequence")
            atom.update(element=operation["new_element"], kind="substitution")
        elif kind == "interstitial":
            atom_id = operation["new_atom_id"]
            if atom_id in expected or atom_id in host_atoms:
                raise ValueError("interstitial must have a new atom ID")
            expected[atom_id] = {"element": operation["element"], "parent_atom_id": None, "kind": "interstitial"}
        else:
            raise ValueError("unsupported explicit defect operation")
    if set(expected) != set(child_atoms):
        raise ValueError("defect operation sequence differs from child atom IDs")
    parents = []
    for entry in entries:
        if {key: entry[key] for key in ("element", "parent_atom_id", "kind")} != expected[entry["child_atom_id"]]:
            raise ValueError("atom lineage differs from explicit defect operations")
        if entry["element"] != child_atoms[entry["child_atom_id"]]["element"]:
            raise ValueError("lineage element differs from child atom")
        pid = entry["parent_atom_id"]
        if pid is None:
            if entry["kind"] != "interstitial":
                raise ValueError("only an explicit interstitial may lack a parent atom")
        else:
            if pid not in host_atoms or entry["kind"] not in ("retained_parent_atom", "substitution") or entry["parent_image"] != [0, 0, 0]:
                raise ValueError("lineage must use explicit same-cell parent atoms")
            if entry["kind"] == "retained_parent_atom" and entry["element"] != host_atoms[pid]["element"]:
                raise ValueError("retained parent element differs")
            parents.append(pid)
    if len(parents) != len(set(parents)):
        raise ValueError("same-cell lineage repeats a parent atom")
    return {"composition_parent": parent_counts, "composition_child": child_counts, "composition_delta": delta,
            "host_charge_q": host["charge"]["q"], "defect_charge_q": defect["charge"]["q"],
            "charge_convention": "q_positive_removes_electrons", "atom_lineage": deepcopy(entries)}


def _validate_saved_potential(potential: Mapping[str, Any], reference: Mapping[str, Any]) -> dict:
    """Bind provided saved grid metadata before reporting any missing partner."""
    shape, _ = _grid(potential)
    for key in ("task_id", "method_set"):
        expected = reference[key] if key == "task_id" else reference["method"][key]
        if potential[key] != expected:
            raise ValueError(f"potential {key} differs from electronic source")
    if str(potential["scheduler_job_id"]) != str(reference["native_job"]["scheduler_job_id"]):
        raise ValueError("potential job differs from electronic source")
    if (potential["study_id"], potential["model_id"], potential["model_version"]) != (
        reference["study"]["study_id"], reference["model"]["model_id"], reference["model"]["version"]
    ):
        raise ValueError("potential Study/model differs from electronic source")
    if potential["method"] != reference["method"] or potential["conditions"] != reference["conditions"]:
        raise ValueError("potential method/conditions differ from same-task electronic source")
    if potential["atom_map"] != reference["atom_map"]["record"]:
        raise ValueError("potential atom map differs from electronic source")
    expected_files = {key: reference["source_files"][key] for key in ("task.json", "result.json", "method.json", "INPUT", "KPT", "running_scf.log")}
    expected_files.update({"model.json": reference["model"]["metadata_file"], "Study": reference["study"]["source_file"],
                           "STRU.atom-map.json": reference["atom_map"]["source_file"]})
    task_dir = Path(reference["task_path"]).resolve()
    native_dir = task_dir / f"OUT.{reference['method']['suffix']}"
    expected_files.update({"OUT.INPUT": str(native_dir / "INPUT"), "STRU": str(task_dir / "STRU"),
                           "ElecStaticPot.cube": str(native_dir / "ElecStaticPot.cube")})
    for key, path in expected_files.items():
        if Path(potential["source_files"][key]).resolve() != Path(path).resolve():
            raise ValueError(f"potential source {key} differs from the bound electronic task")
    if Path(potential["cube"]["source_file"]).resolve() != Path(expected_files["ElecStaticPot.cube"]).resolve():
        raise ValueError("saved cube artifact differs from the bound task")
    model = reference["model"]
    mapped = {a["atom_id"]: a for a in potential["mapped_atoms"]}
    if len(mapped) != len(potential["mapped_atoms"]) or set(mapped) != set(model["atom_ids"]):
        raise ValueError("potential mapped atoms differ from model atom IDs")
    cell = np.asarray(model["cell_angstrom"])
    tolerance = np.asarray(shape)[:, None] * HEADER_HALF_QUANTUM_BOHR * BOHR_TO_ANGSTROM + 1e-8
    if not np.all(np.abs(np.asarray(potential["cube"]["cell_angstrom"]) - cell) <= tolerance):
        raise ValueError("potential cell differs from same-task model")
    for atom in model["atoms"]:
        mapped_atom = mapped[atom["atom_id"]]
        if mapped_atom["element"] != atom["element"]:
            raise ValueError("potential mapped atom element differs")
        distance = np.asarray(mapped_atom["position_angstrom"]) - np.asarray(atom["cart_coords_angstrom"])
        distance -= np.rint(distance @ np.linalg.inv(cell)) @ cell
        if np.any(np.abs(distance) > HEADER_HALF_QUANTUM_BOHR * BOHR_TO_ANGSTROM + 1e-8):
            raise ValueError("potential mapped atom position differs from model")
    software = _software(potential) or reference["electronic_source"].get("evidence_kind") == "software_contract_only"
    if not software:
        if potential["status"] != "native_source_bound_unaligned" or potential["native_output_observed"] is not True or potential["electronic_converged"] is not True:
            raise ValueError("potential lacks saved native source/convergence evidence")
        fields = potential["native_job"]["scheduler_fields"]
        if (fields["JobId"], fields["JobState"], fields["ExitCode"]) != (str(potential["scheduler_job_id"]), "COMPLETED", "0:0"):
            raise ValueError("potential saved Slurm completion differs")
        for path in expected_files.values():
            if not Path(path).is_file():
                raise FileNotFoundError(path)
    return {
        "task_id": potential["task_id"], "scheduler_job_id": potential["scheduler_job_id"],
        "native_job": deepcopy(potential["native_job"]),
        "native_output_observed": potential["native_output_observed"],
        "electronic_converged": potential["electronic_converged"],
        "model_id": potential["model_id"], "model_version": potential["model_version"], "study_id": potential["study_id"],
        "method_set": potential["method_set"], "method": deepcopy(potential["method"]),
        "kind": potential["kind"], "value_unit": potential["value_unit"], "geometry_unit": potential["geometry_unit"],
        "sign_convention": potential["sign_convention"], "energy_zero": deepcopy(potential["energy_zero"]),
        "grid": {key: deepcopy(potential["cube"][key]) for key in ("shape", "origin_bohr", "step_vectors_bohr", "cell_bohr", "axis_order", "unit_conversion")},
        "source_files": deepcopy(potential["source_files"]),
        "source_binding_passed": True, "evidence_kind": "software_contract_only" if software else "native_saved_source",
    }


def build_potential_alignment(request_path: str | Path) -> dict[str, Any]:
    """Bind saved sources once, then calculate or report explicit missing inputs."""
    request_path = Path(request_path).resolve()
    request = _read(request_path)
    if request["schema"] != "mlcc.potential-alignment-request.v1":
        raise ValueError("unsupported potential alignment request schema")
    if not isinstance(request["alignment_id"], str) or not request["alignment_id"].strip():
        raise ValueError("alignment_id must be explicit")
    paths = {key: None if request[key] is None else str((request_path.parent / request[key]).resolve()) for key in (
        "host_electronic_path", "defect_electronic_path", "descriptor_path", "host_potential_path", "defect_potential_path"
    )}
    pair = build_defect_electronic_reference(paths["host_electronic_path"], paths["defect_electronic_path"], paths["descriptor_path"])
    lineage = _check_lineage(pair)
    grids, summaries, missing = {}, {}, []
    for role in ("host", "defect"):
        path = paths[f"{role}_potential_path"]
        if path is None:
            grids[role], summaries[role] = None, None
            missing.append(f"{role}_potential")
        else:
            grids[role] = _read(path)
            summaries[role] = _validate_saved_potential(grids[role], pair[role])
            summaries[role]["saved_potential_path"] = path
    selection = request["selection"]
    if selection is None:
        missing.append("selection")
    else:
        for potential in grids.values():
            if potential is not None:
                _region(selection, tuple(potential["cube"]["shape"]))
    difference, candidate = None, None
    if not missing:
        if pair["method_comparison"]["same_recorded_comparison_fields"] is not True:
            raise ValueError("complete regional comparison requires matching recorded physical and numerical methods")
        difference = calculate_regional_potential_difference(grids["host"], grids["defect"], selection)
        vbm = pair["host"]["levels"]["vbm_eV"]
        if vbm is not None:
            candidate = vbm + difference["delta_v_defect_minus_host_eV"]
    software = any(r["electronic_source"].get("evidence_kind") == "software_contract_only" for r in (pair["host"], pair["defect"]))
    software = software or any(s is not None and s["evidence_kind"] == "software_contract_only" for s in summaries.values())
    if software and difference is not None:
        difference["evidence_kind"] = "software_contract_only"
    return {
        "schema": "mlcc.potential-alignment.v1", "alignment_id": request["alignment_id"], "request_path": str(request_path),
        "status": "missing_inputs" if missing else "computed_regional_difference_unqualified",
        "references": pair, "source_paths": paths, "potentials": summaries, "lineage": lineage,
        "selection": deepcopy(selection), "missing": missing, "difference": difference,
        "candidate_host_vbm_on_defect_gauge_eV": candidate,
        "reference_shift_convention": "host VBM candidate on defect gauge = host VBM + mean_R(Vdefect-Vhost); defect levels on host gauge subtract that difference",
        "charge_convention": "q_positive_removes_electrons; no q factor applied to this regional diagnostic",
        "evidence_kind": "software_contract_only" if software else "native_saved_source",
        "far_field_qualified": False, **_UNQUALIFIED,
    }
