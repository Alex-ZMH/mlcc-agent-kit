"""Promote saved converged fixed-cell relax geometry and create fresh SCF inputs.

No native parser, solver submission, charge reuse or scientific qualification.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from ase.io import read as ase_read

from .abacus_tasks import create_abacus_task
from .berry_tasks import create_berry_reference_task
from .model_derivatives import _model_charge_state, _write_derived
from .modeling import read_model_artifacts
from .tasks import load_task, save_task


SCHEMA = "mlcc.relaxed-structure-bridge.v1"
_TOL = 1e-7  # saved native/EXTXYZ coordinate serialization, angstrom


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _same_path(first, second):
    return Path(first).resolve() == Path(second).resolve()


def _identity(model):
    return {"model_id": model.model_id, "version": model.version, "path": str(model.artifact_dir.resolve())}


def _finite_array(value, shape, label):
    array = np.asarray(value, dtype=float)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{label} must have finite shape {shape}")
    return array


def _study_model(study, model):
    if (study["model"]["model_id"], study["model"]["version"]) != (model.model_id, model.version):
        raise ValueError("Study must select the explicit parent model")
    if (study["case_role"] == "engineering_fixture") != model.metadata["fixture"]:
        raise ValueError("Study and parent model fixture roles differ")
    for field in ("material", "phase_requested"):
        if study["model"][field] != model.metadata[field]:
            raise ValueError(f"Study and parent model {field} differ")


def _saved_source(task_path, parent_model_path, study_path):
    """Read saved final geometry and its canonical relaxation evidence only."""
    task_file = Path(task_path).resolve()
    task = load_task(task_file)
    data = task.data
    parent = read_model_artifacts(parent_model_path)
    study_file = Path(study_path).resolve()
    study = _read(study_file)
    _study_model(study, parent)
    if data["runner"] != "slurm" or data["scheduler_state"] != "COMPLETED" or data["exit_code"] != "0:0" or task.scheduler_job_id is None:
        raise ValueError("relax promotion requires saved Slurm COMPLETED/0:0 and a native job ID")
    if data["engine"] != "abacus" or data["engine_version"] != "3.10.1":
        raise ValueError("relax bridge requires ABACUS 3.10.1")
    if (data["model_id"], data["model_version"]) != (parent.model_id, parent.version) or data["fixture"] != parent.metadata["fixture"]:
        raise ValueError("relax task parent model/fixture differs")
    if "model_path" in data and not _same_path(data["model_path"], parent.artifact_dir):
        raise ValueError("relax task parent model path differs")
    if "calculation" in data and data["calculation"] != "relax":
        raise ValueError("only saved relax tasks can be promoted")
    if data.get("input_transformation") is not None:
        raise ValueError("relax task must not carry an input strain transformation")
    origin = "caller_supplied_parent_study_matching_source_model"
    if "study_id" in data:
        if data["study_id"] != study["study_id"]:
            raise ValueError("relax task Study identity differs")
        if not _same_path(data["study_file"], study_file):
            raise ValueError("relax task Study path differs")
        origin = "source_task_parent_study"
    method_file = task_file.parent / "method.json"
    method = _read(method_file)
    result_file = (task_file.parent / data["result_file"]).resolve()
    result = _read(result_file)
    if (method["engine"] != "abacus" or method["abacus_version_target"] != "3.10.1" or method["stage"] != "relax"
            or result["stage"] != "relax"):
        raise ValueError("saved method/result must be ABACUS fixed-cell relax")
    if (method["model_id"], method["version"]) != (parent.model_id, parent.version):
        raise ValueError("relax method parent model differs")
    if result["task_id"] != task.task_id or str(result["scheduler_job_id"]) != task.scheduler_job_id:
        raise ValueError("relax result task/job differs")
    if method["method_set"] != data["method_set"] or result["method_set"] != data["method_set"]:
        raise ValueError("relax task/method/result method identity differs")
    if result["fixture"] != data["fixture"]:
        raise ValueError("relax result fixture differs")
    if _model_charge_state(parent.metadata) != 0 or any(record.get("net_charge", 0) != 0 for record in (data, method, result)):
        raise ValueError("fixed-cell relax bridge supports neutral structures only")
    relaxation = result["relaxation"]
    if relaxation["schema"] != "mlcc.fixed-cell-relaxation-result.v1" or relaxation["cell_constraint"] != "fixed_cell":
        raise ValueError("unsupported relaxation evidence schema/cell constraint")
    if relaxation["relax_new"] is not True:
        raise ValueError("relax bridge requires the native relax_new CG branch")
    for key in ("geometry_promotable", "electronic_converged", "ionic_converged", "native_completed",
                "fixed_cell_verified", "frozen_dofs_verified", "final_geometry_matches_last_evaluation"):
        if relaxation[key] is not True:
            raise ValueError(f"relax geometry cannot be promoted: {key} is not true")
    if result["electronic_converged"] is not True or result["ionic_converged"] is not True or relaxation["native_stop_reason"] != "ionic_converged":
        raise ValueError("relax geometry requires both convergence flags and ionic_converged stop")
    if relaxation["final_geometry_role"] != "last_evaluated_ionic_step":
        raise ValueError("relax final geometry must be the last evaluated ionic step")
    if result["scientific_status"] not in ("converged", "converged_engineering_fixture"):
        raise ValueError("relax source lacks converged saved status")
    if relaxation["force_metric"] != "max_abs_movable_cartesian_component":
        raise ValueError("unsupported native relaxation force metric")
    if not 1 <= relaxation["ionic_steps"] <= relaxation["relax_nmax"] or relaxation["relax_nmax"] != method["parameters"]["relax_nmax"]:
        raise ValueError("relaxation step budget differs from method")
    constraints = relaxation["ionic_constraints"]
    if constraints["schema"] != "mlcc.ionic-constraints.v1" or constraints["coordinate_basis"] != "cartesian":
        raise ValueError("relax constraints must use the saved Cartesian contract")
    if constraints["relax_new"] is not True:
        raise ValueError("relax constraints require relax_new=true")
    ids = parent.atom_ids
    flags = np.asarray(constraints["move_flags"])
    if constraints["atom_ids"] != ids or flags.shape != (len(ids), 3) or flags.dtype.kind not in "iu" or not np.isin(flags, [0, 1]).all() or not flags.any():
        raise ValueError("relax constraints must cover parent atom IDs with movable integer0/1 flags")
    for record in (method, data):
        if record.get("ionic_constraints") is not None and record["ionic_constraints"] != constraints:
            raise ValueError("saved task/method constraints differ from parsed native constraints")
    cell = np.asarray(parent.atoms.cell.array)
    partial = np.any((flags.sum(axis=1) != 0) & (flags.sum(axis=1) != 3))
    if partial and (not np.allclose(cell, np.diag(np.diag(cell)), rtol=0, atol=1e-10) or np.any(np.diag(cell) <= 0)):
        raise ValueError("partial Cartesian masks require positive axis-aligned orthorhombic cell")
    if result["atom_ids"] != ids:
        raise ValueError("final result atom IDs differ from parent source order")
    final_file = Path(result["final_structure_file"])
    if not final_file.is_absolute():
        raise ValueError("saved final_structure_file must be absolute")
    final = ase_read(str(final_file), format="extxyz", index=0)
    if final.arrays["atom_id"].tolist() != ids or final.get_chemical_symbols() != parent.atoms.get_chemical_symbols():
        raise ValueError("final EXTXYZ atom identity/element order differs")
    atoms = result["final_atoms"]
    positions = _finite_array(atoms["positions_angstrom"], (len(ids), 3), "saved final positions")
    final_cell = _finite_array(atoms["cell_angstrom"], (3, 3), "saved final cell")
    if atoms["symbols"] != parent.atoms.get_chemical_symbols() or atoms["pbc"] != [True, True, True] or not parent.atoms.pbc.all() or not final.pbc.all():
        raise ValueError("final element order/periodicity differs from periodic parent")
    if not np.allclose(final_cell, cell, atol=_TOL, rtol=0) or not np.allclose(final.cell.array, cell, atol=_TOL, rtol=0):
        raise ValueError("relax final cell changed from fixed parent cell")
    if not np.allclose(final.get_positions(), positions, atol=_TOL, rtol=0):
        raise ValueError("final EXTXYZ coordinates differ from saved result")
    delta = positions - parent.atoms.get_positions()
    delta -= np.rint(delta @ np.linalg.inv(cell)) @ cell
    if np.any(np.abs(delta[flags == 0]) > _TOL):
        raise ValueError("final structure moved a frozen Cartesian degree of freedom")
    forces = _finite_array(result["forces_eV_per_A"], (len(ids), 3), "final forces")
    free_force = float(np.max(np.abs(forces[flags == 1])))
    threshold = relaxation["force_threshold_eV_per_A"]
    if not np.isfinite(threshold) or threshold <= 0 or threshold != method["parameters"]["force_thr_eV_per_A"]:
        raise ValueError("relax force threshold differs from method")
    if free_force > threshold or not np.isclose(free_force, relaxation["max_free_force_component_eV_per_A"], atol=1e-8, rtol=0):
        raise ValueError("saved movable force criterion is not converged/consistent")
    if not np.isclose(np.max(np.abs(forces)), relaxation["max_all_force_component_eV_per_A"], atol=1e-8, rtol=0):
        raise ValueError("saved full-force metric differs")
    sources = result["source_files"]
    for key in ("running_relax.log", "STRU_ION_D", "STRU.atom-map.json", "method.json", "INPUT"):
        if not Path(sources[key]).is_file():
            raise FileNotFoundError(sources[key])
    if not _same_path(sources["method.json"], method_file):
        raise ValueError("native source method path differs")
    atom_map = _read(sources["STRU.atom-map.json"])
    if (atom_map["model_id"], atom_map["version"]) != (parent.model_id, parent.version) or atom_map["source_atom_ids"] != ids:
        raise ValueError("native atom map parent/IDs differ")
    if atom_map["element_order"] != method["element_order"] or set(method["element_order"]) != set(parent.atoms.get_chemical_symbols()):
        raise ValueError("native/method element order differs")
    mapped = atom_map["abacus_order"]
    if len(mapped) != len(ids) or sorted(entry["source_index"] for entry in mapped) != list(range(len(ids))):
        raise ValueError("native atom map does not cover source atoms once")
    for entry in mapped:
        i = entry["source_index"]
        if entry["atom_id"] != ids[i] or entry["element"] != parent.atoms[i].symbol:
            raise ValueError("native source atom mapping differs")
    source = {
        "task_id": task.task_id, "task_file": str(task_file), "result_file": str(result_file),
        "method_file": str(method_file), "method_set": data["method_set"],
        "scheduler_job_id": task.scheduler_job_id, "scheduler_state": data["scheduler_state"], "exit_code": data["exit_code"],
        "parent_model": _identity(parent), "parent_study_file": str(study_file),
        "study_binding_origin": origin, "relaxation": deepcopy(relaxation),
        "final_structure_file": str(final_file), "source_files": deepcopy(sources),
        "scientific_status": result["scientific_status"], "fixture": data["fixture"],
        "scientific_qualification": False, "production_qualification": False,
    }
    return parent, study, final, source


def derive_relaxed_structure(*, task_path, parent_model_path, study_path, request_path, output_path):
    """Promote one saved, physically stopped geometry; never run a calculation."""
    request = _read(request_path)
    for field in ("model_id", "version", "study_id"):
        if not isinstance(request[field], str) or not request[field].strip():
            raise ValueError(f"new {field} must be explicit nonempty text")
    parent, study, final, source = _saved_source(task_path, parent_model_path, study_path)
    if request["study_id"] == study["study_id"] or (request["model_id"], request["version"]) == (parent.model_id, parent.version):
        raise ValueError("promoted structure requires a new model identity and Study ID")
    output = Path(output_path).resolve()
    output.mkdir(parents=True, exist_ok=False)
    lineage = []
    for i, atom_id in enumerate(parent.atom_ids):
        lineage.append({"child_atom_id": atom_id, "parent_atom_id": atom_id, "parent_image": [0, 0, 0],
                        "element": parent.atoms[i].symbol, "kind": "fixed_cell_relaxed_atom",
                        "parent_frac_coords": parent.atoms.get_scaled_positions(wrap=False)[i].tolist(),
                        "child_frac_coords": final.get_scaled_positions(wrap=False)[i].tolist(),
                        "parent_cart_coords_angstrom": parent.atoms.positions[i].tolist(),
                        "child_cart_coords_angstrom": final.positions[i].tolist()})
    derivation = {"kind": "saved_fixed_cell_relaxation", "charge_state": 0, "relaxation_source": source}
    child = _write_derived(parent, final, output / "model", request, derivation=derivation, atom_lineage=lineage,
                           basis_transform={"kind": "fixed_cell_relaxation", "fractional_matrix": np.eye(3, dtype=int).tolist(),
                                            "fractional_translation": [0, 0, 0]}, spatial_mode="fixed_cell_relaxed_structure")
    child.metadata.update(relaxation_source=source, relaxation_status="converged_saved_native_structure",
                          scientific_status="relaxed_structure_unqualified", scientific_qualification=False,
                          production_qualification=False, phase_relaxed=None,
                          dopants=deepcopy(parent.metadata["dopants"]))
    _write(output / "model" / "model.json", child.metadata)
    dopants = _read(parent.artifact_dir / "dopants.json")
    dopants.update(model_id=child.model_id, version=child.version)
    _write(output / "model" / "dopants.json", dopants)
    child_study = deepcopy(study)
    for key in ("berry_strain_response", "berry_response"):
        child_study.pop(key, None)
    child_study.update(study_id=request["study_id"], parent_study_id=study["study_id"], relaxation_source=source,
                       scientific_qualification=False, production_qualification=False, production_qualified=False,
                       scientific_status="relaxed_structure_unqualified",
                       derived_from={"study_id": study["study_id"], "study_file": str(Path(study_path).resolve()),
                                     "model_id": parent.model_id, "model_version": parent.version,
                                     "reason": "saved_fixed_cell_relaxation"})
    child_study["model"].update(model_id=child.model_id, version=child.version,
                                path=str(child.artifact_dir), model_path=str(child.artifact_dir),
                                source_structure=str(child.artifact_dir / "model.extxyz"), phase_relaxed=None,
                                relaxation_status="converged_saved_native_structure", production_qualified=False)
    _write(output / "study.json", child_study)
    bridge = {"schema": SCHEMA, "bridge_path": str(output / "bridge.json"), "request_path": str(Path(request_path).resolve()),
              "parent_model": _identity(parent),
              "parent_study": {"study_id": study["study_id"], "study_path": str(Path(study_path).resolve())},
              "child_model": _identity(child), "child_study": {"study_id": child_study["study_id"], "study_path": str(output / "study.json")},
              "relaxation_source": source, "study_binding_origin": source["study_binding_origin"],
              "status": "promoted_unqualified", "scientific_qualification": False, "production_qualification": False}
    _write(output / "bridge.json", bridge)
    return bridge


def create_relaxed_scf(*, bridge_path, method_path, site_path, request_path):
    """Use the promoted geometry for a fresh SCF; preserve relax provenance."""
    bridge_file = Path(bridge_path).resolve()
    bridge = _read(bridge_file)
    if bridge["schema"] != SCHEMA or not _same_path(bridge["bridge_path"], bridge_file):
        raise ValueError("relaxed bridge schema/path differs")
    source = bridge["relaxation_source"]
    parent, _, final, current_source = _saved_source(source["task_file"], bridge["parent_model"]["path"], bridge["parent_study"]["study_path"])
    if current_source != source or _identity(parent) != bridge["parent_model"]:
        raise ValueError("relaxed bridge saved source changed")
    child = read_model_artifacts(bridge["child_model"]["path"])
    study_file = Path(bridge["child_study"]["study_path"])
    study = _read(study_file)
    _study_model(study, child)
    if _identity(child) != bridge["child_model"] or study["study_id"] != bridge["child_study"]["study_id"]:
        raise ValueError("relaxed bridge child identity differs")
    if child.metadata["relaxation_source"] != source or study["relaxation_source"] != source:
        raise ValueError("relaxed child source provenance differs")
    if (child.atom_ids != parent.atom_ids or child.atoms.get_chemical_symbols() != final.get_chemical_symbols()
            or not np.allclose(child.atoms.cell.array, final.cell.array, atol=_TOL, rtol=0)
            or not np.allclose(child.atoms.positions, final.positions, atol=_TOL, rtol=0)):
        raise ValueError("promoted model differs from saved final structure")
    request = _read(request_path)
    if request["calculation"] != "scf" or request.get("input_transformation") is not None or request.get("ionic_constraints") is not None:
        raise ValueError("relaxed SCF bridge creates untransformed SCF inputs without ionic constraints")
    dependency = {"task_id": source["task_id"], "task_file": source["task_file"],
                  "result_file": source["result_file"], "scientific_status": source["scientific_status"]}
    effective = deepcopy(request)
    requirements = effective["required_results"]
    same = [item for item in requirements if item["task_id"] == source["task_id"]]
    if same and same != [dependency]:
        raise ValueError("requested relax dependency differs from bridge source")
    if not same:
        requirements.append(dependency)
    task_id = effective["task_id"]
    if not isinstance(task_id, str) or not task_id or "/" in task_id or "\\" in task_id or task_id in (".", ".."):
        raise ValueError("SCF task_id must be a single explicit path component")
    effective_path = bridge_file.parent / f"{task_id}.request.json"
    if effective_path.exists():
        raise FileExistsError(effective_path)
    berry = effective.get("berry")
    if berry is not None and berry["role"] != "reference_scf":
        raise ValueError("relaxed SCF bridge supports only Berry reference_scf role")
    _write(effective_path, effective)
    creator = create_berry_reference_task if berry is not None else create_abacus_task
    created = creator(study_path=study_file, model_path=child.artifact_dir, method_path=method_path,
                      site_path=site_path, request_path=effective_path)
    site = _read(site_path)
    task = load_task(Path(site["workspace"]["local"]) / "tasks" / created["task_id"] / "task.json")
    task.set(relaxation_source=deepcopy(source), relaxed_structure_bridge=str(bridge_file))
    task.record_event("relaxed_structure_bridge", source_task_id=source["task_id"], source_job_id=source["scheduler_job_id"],
                      bridge_file=str(bridge_file), result="fresh_scf_inputs_not_submitted")
    save_task(task)
    return task.data
