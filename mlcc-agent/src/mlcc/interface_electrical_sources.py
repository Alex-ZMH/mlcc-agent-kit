"""Bind saved interface potential JSON; never read cube/INPUT/log or run an engine."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .electrostatic_potential import BOHR_TO_ANGSTROM, HEADER_HALF_QUANTUM_BOHR
from .interface_electrical import calculate_interface_electrical, grid_normal, validate_electrical_selection

REQUEST_SCHEMA = "mlcc.interface-electrical-request.v1"
PRODUCT_SCHEMA = "mlcc.interface-electrical-product.v1"
_JSON_SOURCES = ("task.json", "result.json", "method.json", "model.json", "Study", "STRU.atom-map.json")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _path(value: str | Path, base: Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def _check(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} differs")


def _text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be explicit")


def _study(study: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    _check(study["schema"], "mlcc.study.v1", "Study schema")
    _check(study["model"]["spatial_mode"], "layered_interface", "Study spatial_mode")
    _check(study["interface"]["schema"], "mlcc.interface-study-binding.v1", "Study interface schema")
    _check(request["study_id"], study["study_id"], "request.study_id")
    _check(study["interface"]["request"]["schema"], "mlcc.layered-interface-request.v1", "interface request schema")
    _check([parent["side"] for parent in study["interface"]["parent_models"]], ["a", "b"], "interface parent sides")


def _bind_atoms(potential: Mapping[str, Any], model: Mapping[str, Any], result: Mapping[str, Any], selection: Mapping[str, Any]) -> None:
    atom_map, cube, final = potential["atom_map"], potential["cube"], result["final_atoms"]
    _check(atom_map["schema"], "mlcc.abacus-atom-map.v1", "atom map schema")
    _check((atom_map["model_id"], atom_map["version"]), (model["model_id"], model["version"]), "atom map model")
    source_ids = atom_map["source_atom_ids"]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("source atom IDs must be unique")
    _check(model["atom_ids"], source_ids, "model atom IDs")
    _check(result["atom_ids"], source_ids, "result atom IDs")
    _check([atom["atom_id"] for atom in model["atoms"]], source_ids, "model atom row order")
    periodic = [value == "p" for value in selection["boundary"]]
    _check(final["pbc"], periodic, "result PBC")
    _check(model["pbc"], periodic, "model PBC")
    cell = np.asarray(final["cell_angstrom"], dtype=float)
    cube_cell = np.asarray(cube["cell_angstrom"], dtype=float)
    tolerance = np.asarray(cube["shape"])[:, None] * HEADER_HALF_QUANTUM_BOHR * BOHR_TO_ANGSTROM + 1e-8
    for label, candidate in (("result", cell), ("model", np.asarray(model["lattice_angstrom"], dtype=float))):
        if candidate.shape != (3, 3) or not np.isfinite(candidate).all() or not np.all(np.abs(candidate - cube_cell) <= tolerance):
            raise ValueError(f"cube cell differs from {label} cell beyond header precision")
    mapped = potential["mapped_atoms"]
    order = sorted(atom_map["abacus_order"], key=lambda entry: entry["abacus_index"])
    if len(mapped) != len(source_ids) or [entry["abacus_index"] for entry in order] != list(range(len(source_ids))):
        raise ValueError("ABACUS atom order is incomplete")
    indices = [atom["source_index"] for atom in mapped]
    if sorted(indices) != list(range(len(source_ids))):
        raise ValueError("mapped source indices must be a complete unique permutation")
    for atom, entry in zip(mapped, order):
        for key in ("abacus_index", "source_index", "atom_id", "element"):
            _check(atom[key], entry[key], f"mapped atom {key}")
        index = atom["source_index"]
        _check(atom["atom_id"], source_ids[index], "mapped atom ID")
        _check(atom["element"], final["symbols"][index], "mapped result element")
        _check(atom["element"], model["atoms"][index]["element"], "mapped model element")
    positions = np.asarray([atom["position_angstrom"] for atom in mapped], dtype=float)
    inverse_cell = np.linalg.inv(cell)
    for label, expected in (("result", final["positions_angstrom"]),
                            ("model", [atom["cart_coords_angstrom"] for atom in model["atoms"]])):
        expected = np.asarray(expected, dtype=float)
        if positions.shape != (len(source_ids), 3) or expected.shape != positions.shape or not np.isfinite(positions).all() or not np.isfinite(expected).all():
            raise ValueError("source atomic coordinates must be finite N by 3 arrays")
        delta = positions - expected[indices]
        delta -= (np.rint(delta @ inverse_cell) * periodic) @ cell
        if np.any(np.abs(delta) > HEADER_HALF_QUANTUM_BOHR * BOHR_TO_ANGSTROM + 1e-8):
            raise ValueError(f"mapped coordinates differ from {label} positions")


def _load(path: Path, study: Mapping[str, Any], selection: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    potential = _read(path)
    _check(potential["schema"], "mlcc.abacus-electrostatic-potential.v1", "potential schema")
    for key, expected in (("study_id", study["study_id"]), ("model_id", study["model"]["model_id"]), ("model_version", study["model"]["version"])):
        _check(potential[key], expected, f"potential.{key}")
    files = {key: _path(potential["source_files"][key], path.parent) for key in _JSON_SOURCES}
    records = {key: _read(file) for key, file in files.items()}
    task, result, method, model, saved_study, atom_map = (records[key] for key in _JSON_SOURCES)
    for label, record in (("task", task), ("result", result)):
        for key in ("task_id", "scheduler_job_id", "method_set"):
            _check(record[key], potential[key], f"saved {label}.{key}")
    _check((task["model_id"], task["model_version"], task["study_id"]),
           (potential["model_id"], potential["model_version"], study["study_id"]), "task identity")
    _check((task["engine"], task["engine_version"], task["calculation"], task["runner"]),
           ("abacus", "3.10.1", "scf", "slurm"), "native source engine/runner")
    _check((task["status"], task["scheduler_state"], task["exit_code"]), ("COMPLETED", "COMPLETED", "0:0"), "task terminal")
    _check(result["electronic_converged"], True, "saved result convergence")
    _check(result["stage"], "scf", "saved result stage")
    fields = potential["native_job"]["scheduler_fields"]
    _check((str(fields["JobId"]), fields["JobState"], fields["ExitCode"]),
           (str(task["scheduler_job_id"]), task["scheduler_state"], task["exit_code"]), "saved scheduler evidence")
    _check(method, potential["method"], "saved method")
    _check(method["method_set"], potential["method_set"], "saved method_set")
    _check((method["engine"], method["abacus_version_target"], method["stage"], method["model_id"], method["version"]),
           ("abacus", "3.10.1", "scf", potential["model_id"], potential["model_version"]), "method identity")
    _check(potential["conditions"], task["calculation_conditions"], "saved calculation conditions")
    _check(atom_map, potential["atom_map"], "saved atom map")
    _check(atom_map["element_order"], method["element_order"], "method element order")
    _check((model["schema"], model["model_id"], model["version"], model["spatial_mode"]),
           ("mlcc.model.v1", potential["model_id"], potential["model_version"], "layered_interface"), "source model")
    _check((saved_study["study_id"], saved_study["model"]), (study["study_id"], study["model"]), "saved Study identity")
    _check(saved_study["interface"], study["interface"], "saved Study interface")
    _check(model["boundary"], selection["boundary"], "selection boundary")
    _check(study["interface"]["request"]["boundary"], selection["boundary"], "Study boundary")
    _bind_atoms(potential, model, result, selection)
    record_path = _path(model["interface_file"], files["model.json"].parent)
    interface = _read(record_path)
    _check((interface["schema"], interface["model_id"], interface["version"]),
           ("mlcc.layered-interface.v1", model["model_id"], model["version"]), "interface record")
    _check(interface["request"], study["interface"]["request"], "interface request")
    _check(interface["parent_models"], study["interface"]["parent_models"], "interface parents")
    _check(model["parent_models"], interface["parent_models"], "model parents")
    normal = np.asarray(model["interface_geometry"]["normal_cartesian"], dtype=float)
    if normal.shape != (3,) or not np.isfinite(normal).all() or not np.isclose(np.linalg.norm(normal), 1, rtol=0, atol=1e-8):
        raise ValueError("saved interface normal must be a finite unit vector")
    _check(interface["geometry"]["normal_cartesian"], normal.tolist(), "interface record normal")
    if not np.isclose(abs(float(grid_normal(potential["cube"], selection["grid_axis"]) @ normal)), 1, rtol=0, atol=1e-8):
        raise ValueError("selection grid_axis does not match the saved interface normal")
    fixture = potential.get("evidence_kind") == "software_contract_only" or potential["cube"].get("evidence_kind") == "software_contract_only"
    if not fixture:
        _check(potential["status"], "native_source_bound_unaligned", "potential status")
        _check(potential["native_output_observed"], True, "potential native output")
        _check(potential["electronic_converged"], True, "potential convergence")
    summary = {key: deepcopy(potential[key]) for key in (
        "task_id", "scheduler_job_id", "study_id", "model_id", "model_version", "method_set", "method",
        "native_job", "status", "native_output_observed", "electronic_converged", "energy_zero", "source_files",
    )}
    summary.update(path=str(path), interface_record_path=str(record_path),
                   evidence_kind="software_contract_only" if fixture else "native_saved_source")
    return potential, summary


def build_interface_electrical_product(study: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Consume saved sources, or preserve an explicit missing-source/null response."""
    _check(request["schema"], REQUEST_SCHEMA, "request schema")
    _study(study, request)
    potential_path, selection = request["potential_path"], request["selection"]
    reference_path, description = request.get("reference_potential_path"), request.get("reference_description")
    if selection is not None:
        validate_electrical_selection(selection)
    product = {
        "schema": PRODUCT_SCHEMA, "study_id": study["study_id"], "case_id": study["case_id"], "case_role": study["case_role"],
        "model_id": study["model"]["model_id"], "model_version": study["model"]["version"],
        "analysis_scheduler_job_id": os.environ.get("SLURM_JOB_ID"),
        "interface": deepcopy(study["interface"]), "selection": deepcopy(selection),
        "method_set": None, "source": None, "reference": None, "source_files": {}, "source_refs": [],
        "response": None, "status": "unresolved", "missing_evidence": [],
        "scientific_qualification": False, "production_qualification": False,
    }
    if potential_path is None:
        if reference_path is not None or description is not None:
            raise ValueError("reference comparison requires a target potential")
        _text(request["missing_source_reason"], "missing_source_reason")
        product["missing_evidence"] = [request["missing_source_reason"]]
        return product
    if selection is None:
        raise ValueError("selection is required with a saved potential")
    _text(potential_path, "potential_path")
    target, target_source = _load(Path(potential_path).resolve(), study, selection)
    reference, reference_source = None, None
    if reference_path is not None:
        _text(description, "reference_description")
        _text(reference_path, "reference_potential_path")
        reference, reference_source = _load(Path(reference_path).resolve(), study, selection)
        _check(reference_source["evidence_kind"], target_source["evidence_kind"], "reference evidence kind")
    elif description is not None:
        raise ValueError("reference_description requires reference_potential_path")
    response = calculate_interface_electrical(target, selection, reference_potential=reference, reference_description=description)
    refs = []
    for source in (target_source, reference_source):
        if source is not None:
            refs.extend([source["path"], source["interface_record_path"], *source["source_files"].values()])
    product.update(
        method_set=target["method_set"], source=target_source, reference=reference_source,
        source_files=deepcopy(target["source_files"]), source_refs=refs, response=response,
        status="computed_software_contract_only" if target_source["evidence_kind"] == "software_contract_only" else "computed_unqualified",
    )
    return product
