"""Ordered fixed-cell SCF energy observations from saved native results.

No native energy/Berry parser, branch selection, relaxation or barrier model.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path

import numpy as np

from .abacus import _energy_definition
from .berry import _read_input, _read_kpt, _bool_input
from .chemical_references import _METHOD_FIELDS, _SCIENCE_FIELDS, _PARAMETER_FIELDS


_ADDITIONAL_METHOD_FIELDS = {
    "nelec", "nelec_delta", "charge_convention", "scientific_qualification",
    "production_qualification", "binary_source",
}
_METHOD_METADATA = {
    "schema", "model_id", "version", "suffix", "device", "method_set", "parent_method_set",
    "source_configuration", "fixture", "fixture_purpose", "binary_source", "input_qualification",
    "compatibility_reference", "scientific_qualification", "production_qualification",
    "pseudopotentials", "stress_convention", "output_control", "requested_artifacts",
}
_BERRY_METADATA = {
    "schema", "gdir", "charge_density", "read_file_dir", "out_chg", "init_chg", "device",
    "binary_source", "implementation_id", "gpu_build", "scope", "numerical_qualification",
    "qualification_status",
}
_BERRY_PHYSICS = {"role", "berry_phase", "symmetry", "pw_diag_thr", "nspin", "lspinorb", "noncolin", "occupations", "kpar"}
_NATIVE_NUMERICS = ("ecutwfc", "scf_thr", "scf_nmax", "nbands", "mixing_type", "mixing_beta", "ks_solver", "symmetry", "pw_diag_thr", "scf_thr_type", "kpar")
_TOP_INPUT_FIELDS = {
    "suffix", "pseudo_dir", "calculation", "device", "dft_functional", "basis_type", "ks_solver",
    "ecutwfc", "scf_thr", "scf_nmax", "nbands", "nspin", "lspinorb", "noncolin", "mixing_type",
    "mixing_beta", "symmetry", "cal_force", "cal_stress", "smearing_method", "out_chg", "kpar",
    "pw_diag_thr", "nelec", "nelec_delta", "berry_phase",
}
_NATIVE_ROUTING_FIELDS = {"suffix", "pseudo_dir", "orbital_dir", "read_file_dir", "stru_file", "kpoint_file", "device"}
_UNQUALIFIED = {
    "neb_barrier_eV": None, "finite_temperature_free_energy_eV": None,
    "spontaneous_polarization": None, "polarization_coordinate": None,
    "delta_polarization": None, "double_well_qualified": False,
    "ferroelectric_qualification": False, "scientific_qualification": False,
    "production_qualification": False,
}


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be explicit nonempty text")
    return value


def _path(base, value):
    return (base / value).resolve()


def _software(record):
    return record.get("evidence_kind") == "software_contract_only" or record.get("fixture") is True or record.get("fixture_purpose") == "software_contract_only"


def _study_model_path(study, study_file, expected):
    for key in ("path", "model_path"):
        if key in study["model"] and study["model"][key] is not None:
            if _path(study_file.parent, study["model"][key]) != expected:
                raise ValueError("Study declared model path differs from bound model")


def _energy_summary(points, reference_point_id):
    """Whole-cell arithmetic; all input points must already be source-valid."""
    ids = [p["point_id"] for p in points]
    if len(points) < 2 or len(ids) != len(set(ids)) or reference_point_id not in ids:
        raise ValueError("energy path requires two unique point_id values and an existing reference")
    coordinates = [_number(p["coordinate"], "coordinate") for p in points]
    if any(b <= a for a, b in zip(coordinates, coordinates[1:])):
        raise ValueError("path coordinates must be strictly increasing")
    energies = [_number(p["energy_eV_cell"], "whole-cell energy") for p in points]
    reference = energies[ids.index(reference_point_id)]
    output = [dict(deepcopy(p), relative_energy_eV_cell=e - reference) for p, e in zip(points, energies)]
    maximum = max(energies)
    tied = [p for p in output if p["energy_eV_cell"] == maximum]
    return {
        "reference_point_id": reference_point_id, "points": output,
        "endpoint_difference_eV_cell": energies[-1] - energies[0],
        "sampled_maximum": {
            "energy_eV_cell": maximum, "relative_energy_eV_cell": maximum - reference,
            "point_ids": [p["point_id"] for p in tied], "coordinates": [p["coordinate"] for p in tied],
            "sources": [{"point_id": p["point_id"], "task_id": p["task_id"], "native_job": deepcopy(p["native_job"])} for p in tied],
        },
    }


def _geometry(model):
    atoms = {a["atom_id"]: a for a in model["atoms"]}
    ids = model["atom_ids"]
    if len(atoms) != len(model["atoms"]) or len(ids) != len(set(ids)) or set(ids) != set(atoms):
        raise ValueError("model atom IDs must uniquely cover model atoms")
    symbols = {atom_id: atoms[atom_id]["element"] for atom_id in ids}
    if dict(Counter(symbols.values())) != model["composition"]:
        raise ValueError("model composition differs from explicit atoms")
    cell = np.asarray(model["lattice_angstrom"], dtype=float)
    positions = np.asarray([atoms[i]["cart_coords_angstrom"] for i in ids], dtype=float)
    if cell.shape != (3, 3) or positions.shape != (len(ids), 3) or not np.isfinite(cell).all() or not np.isfinite(positions).all() or np.linalg.det(cell) == 0:
        raise ValueError("invalid finite periodic model geometry")
    if model["pbc"] != [True, True, True]:
        raise ValueError("energy path requires fully periodic bulk geometry")
    return ids, symbols, cell, positions


def _same_positions(first, second, cell):
    delta = np.asarray(first) - np.asarray(second)
    delta -= np.rint(delta @ np.linalg.inv(cell)) @ cell
    return np.isfinite(delta).all() and np.all(np.abs(delta) <= 1e-7)


def _method_signature(method, directory):
    unknown = set(method) - _METHOD_FIELDS - _ADDITIONAL_METHOD_FIELDS
    unknown |= {f"science.{k}" for k in set(method["science"]) - _SCIENCE_FIELDS - {"net_charge", "nelec", "nelec_delta", "charge_convention"}}
    unknown |= {f"parameters.{k}" for k in set(method["parameters"]) - _PARAMETER_FIELDS}
    unknown |= {f"execution.{k}" for k in set(method["execution"]) - {"device", "ks_solver"}}
    unknown |= {f"berry.{k}" for k in set(method["berry"]) - _BERRY_METADATA - _BERRY_PHYSICS}
    if unknown:
        raise ValueError(f"unsupported energy-path physical fields: {sorted(unknown)}")
    for key in ("element_order", "pseudopotential_ids", "pseudopotential_metadata", "pseudopotential_treatment"):
        if not method[key]:
            raise ValueError(f"explicit {key} is required")
    for key in ("pseudopotential_ids", "pseudopotential_metadata", "pseudopotential_treatment"):
        if set(method[key]) != set(method["element_order"]):
            raise ValueError("pseudopotential records must cover the declared elements")
    if (method["engine"], method["abacus_version_target"], method["basis_type"], method["stage"], method["occupations"], method["nspin"], method["net_charge"]) != ("abacus", "3.10.1", "pw", "scf", "fixed", 1, 0):
        raise ValueError("energy path requires neutral fixed-occupation nspin1 ABACUS3.10.1 PW SCF")
    if method["lspinorb"] is not False or method["noncolin"] is not False:
        raise ValueError("SOC/noncollinear energy paths are outside this slice")
    if method["berry"]["role"] != "reference_scf" or method["berry"]["out_chg"] != 1 or method["berry"]["berry_phase"] != 0:
        raise ValueError("SCF must be the recorded charge-producing reference")
    signature = {k: deepcopy(v) for k, v in method.items() if k not in _METHOD_METADATA}
    signature["science"] = {k: v for k, v in method["science"].items() if k != "suffix"}
    signature["execution"] = {k: v for k, v in method["execution"].items() if k != "device"}
    signature["berry"] = {k: v for k, v in method["berry"].items() if k not in _BERRY_METADATA}
    # Reuse input readers only: no SCF log, energy, level or Berry parser.
    top = _read_input(directory / "INPUT")
    native = _read_input(directory / f"OUT.{method['suffix']}" / "INPUT", allow_blank_values=True)
    mesh, shift = _read_kpt(directory / "KPT")
    if list(mesh) != method["kpoints"]:
        raise ValueError("saved KPT mesh differs from method")
    if "kpoint_shift" in method and list(shift) != method["kpoint_shift"]:
        raise ValueError("saved KPT shift differs from method")
    if set(top) - _TOP_INPUT_FIELDS:
        raise ValueError(f"unsupported additional input fields: {sorted(set(top) - _TOP_INPUT_FIELDS)}")
    if native["calculation"] != "scf" or top["calculation"] != "scf" or native["basis_type"] != "pw" or native["smearing_method"] != "fixed" or top["smearing_method"] != "fixed":
        raise ValueError("native INPUT is not the requested fixed-occupation PW SCF")
    for key in ("lspinorb", "noncolin", "efield_flag", "dip_cor_flag", "gate_flag", "berry_phase", "dft_plus_u"):
        if _bool_input(native[key], key=key):
            raise ValueError(f"unsupported native physical setting {key}")
        if key in top and _bool_input(top[key], key=key):
            raise ValueError(f"unsupported task input physical setting {key}")
    if native["vdw_method"] != "none" or float(native["nelec_delta"]) != 0 or float(native["nelec"]) != 0:
        raise ValueError("native dispersion or changed electron number is unsupported")
    for key in ("nelec", "nelec_delta"):
        if key in top and float(top[key]) != 0:
            raise ValueError(f"task INPUT {key} differs from neutral SCF")
    for owner in (method, method["berry"], method["parameters"], top):
        if owner.get("pw_diag_thr") is not None and float(owner["pw_diag_thr"]) != float(native["pw_diag_thr"]):
            raise ValueError("explicit pw_diag_thr differs from native INPUT")
    for owner in (method["berry"], top):
        if owner.get("kpar") is not None and float(owner["kpar"]) != float(native["kpar"]):
            raise ValueError("explicit kpar differs from native INPUT")
    if int(native["out_chg"].split()[0]) != 1 or int(top["out_chg"].split()[0]) != 1:
        raise ValueError("native source did not request charge output")
    for key, value in {"ecutwfc": method["parameters"]["ecutwfc_Ry"], "scf_thr": method["parameters"]["scf_thr"], "scf_nmax": method["parameters"]["scf_nmax"], "nbands": method["parameters"]["nbands"], "mixing_beta": method["parameters"]["mixing_beta"], "symmetry": method["symmetry"], "nspin": 1}.items():
        if float(native[key]) != value or float(top[key]) != value:
            raise ValueError(f"native/input/method {key} differs")
    for key in ("ks_solver", "mixing_type", "dft_functional"):
        if native[key].lower() != method[key].lower() or top[key].lower() != method[key].lower():
            raise ValueError(f"native/input/method {key} differs")
    signature["effective_native_numerics"] = {k: native[k] for k in _NATIVE_NUMERICS}
    signature["native_recorded_settings"] = {k: v for k, v in native.items() if k not in _NATIVE_ROUTING_FIELDS}
    signature["kpoint_mesh"] = list(mesh)
    signature["effective_kpoint_shift"] = list(shift)
    return signature, {"task_INPUT": top, "native_INPUT": native}


def _berry_attachment(path, task, task_file, result_file, method):
    berry = _read(path)
    if berry["schema"] != "mlcc.abacus-polarization.v1" or berry["stage"] != "nscf" or berry["native_completed"] is not True:
        raise ValueError("Berry attachment must be a saved completed native NSCF result")
    ref = berry["reference_scf_validation"]
    if berry["reference_scf_converged"] is not True or ref["native_completed"] is not True:
        raise ValueError("Berry attachment lacks saved SCF reference completion")
    if berry["reference_task_id"] != task["task_id"] or berry["reference_scf_task_id"] != task["task_id"] or ref["task_id"] != task["task_id"]:
        raise ValueError("Berry attachment belongs to another SCF reference")
    if Path(ref["task_file"]).resolve() != task_file or Path(ref["electronic_source"]["result.json"]).resolve() != result_file:
        raise ValueError("Berry SCF source paths differ")
    for key in ("model_id", "model_version"):
        if berry[key] != task[key] or ref[key] != task[key]:
            raise ValueError("Berry attachment model differs from SCF")
    berry_task_file = Path(berry["source_files"]["INPUT"]).parent / "task.json"
    berry_task = _read(berry_task_file)
    if Path(berry_task["result_file"]).resolve() != path or berry_task["study_id"] != task["study_id"]:
        raise ValueError("Berry attachment result/Study differs")
    if berry_task["task_id"] != berry["task_id"] or str(berry_task["scheduler_job_id"]) != str(berry["scheduler_job_id"]):
        raise ValueError("Berry attachment native job identity differs")
    if (berry_task["scheduler_state"], berry_task["exit_code"]) != ("COMPLETED", "0:0"):
        raise ValueError("Berry attachment scheduler did not complete")
    if berry_task["berry"]["source_reference_task_id"] != task["task_id"] or Path(berry_task["berry"]["source_reference_task_file"]).resolve() != task_file:
        raise ValueError("Berry declared reference task differs")
    dependencies = [d for d in berry_task["dependency_evidence"] if d["task_id"] == task["task_id"]]
    if len(dependencies) != 1:
        raise ValueError("Berry attachment requires one saved SCF dependency")
    source_scf = dependencies[0]
    if str(source_scf["scheduler_job_id"]) != str(task["scheduler_job_id"]) or Path(source_scf["task_file"]).resolve() != task_file or Path(source_scf["result_file"]).resolve() != result_file:
        raise ValueError("Berry charge-producing SCF job differs")
    if (source_scf["scheduler_state"], source_scf["exit_code"]) != ("COMPLETED", "0:0"):
        raise ValueError("Berry saved SCF dependency did not complete")
    charges = [str(task_file.parent / f"OUT.{method['suffix']}" / name) for name in method["berry"]["charge_density"]["files"]]
    if ref["charge_files"] != charges or berry["reference_charge_source"]["source_paths"] != charges:
        raise ValueError("Berry charge artifacts differ from same-task SCF")
    return {"result_file": str(path), "task_file": str(berry_task_file), "saved_result": berry,
            "reference_scf_job": {"task_id": task["task_id"], "scheduler_job_id": task["scheduler_job_id"]},
            "polarization_coordinate": None, "delta_polarization": None}


def _point(spec, base, parent, parent_model, parent_study):
    task_file, result_file = _path(base, spec["scf_task_file"]), _path(base, spec["scf_result_file"])
    directory = task_file.parent
    task, result, method = _read(task_file), _read(result_file), _read(directory / "method.json")
    if result_file != Path(task["result_file"]).resolve() or result_file != directory / "result.json":
        raise ValueError("SCF result path is not the task's saved result")
    if (task["engine"], task["engine_version"], task["calculation"], result["stage"]) != ("abacus", "3.10.1", "scf", "scf"):
        raise ValueError("energy source must be SCF, never Berry NSCF")
    if task["runner"] != "slurm" or (task["scheduler_state"], task["exit_code"], task["status"]) != ("COMPLETED", "0:0", "COMPLETED"):
        raise ValueError("SCF energy requires recorded Slurm COMPLETED/0:0")
    for key in ("task_id", "scheduler_job_id", "method_set"):
        if result[key] != task[key]:
            raise ValueError(f"SCF result {key} differs from task")
    if result["electronic_converged"] is not True:
        raise ValueError("SCF energy point is electronically unconverged")
    for record in (task, result, method):
        for key in ("net_charge", "nelec_delta"):
            if key in record and record[key] != 0:
                raise ValueError("SCF source charge records must be neutral")
    if result["energy_unit"] != "eV" or result["energy_definition"] != _energy_definition("fixed") or result["occupations"] != "fixed":
        raise ValueError("SCF energy must retain fixed-occupation whole-cell eV definition")
    energy = _number(result["energy_eV"], "SCF energy_eV")
    model_path, study_file = Path(task["model_path"]).resolve(), Path(task["study_file"]).resolve()
    model, study = _read(model_path / "model.json"), _read(study_file)
    _study_model_path(study, study_file, model_path)
    identity = (task["model_id"], task["model_version"])
    for declared in ((model["model_id"], model["version"]), (method["model_id"], method["version"]), (study["model"]["model_id"], study["model"]["version"])):
        if declared != identity:
            raise ValueError("SCF task/model/method/Study identity differs")
    if method["method_set"] != task["method_set"] or study["study_id"] != task["study_id"]:
        raise ValueError("SCF method_set or Study differs")
    ids, symbols, cell, positions = _geometry(model)
    parent_ids, parent_symbols, parent_cell, parent_positions = _geometry(parent_model)
    if ids != parent_ids or symbols != parent_symbols or not np.allclose(cell, parent_cell, rtol=0, atol=1e-8):
        raise ValueError("path point composition/atom map/fixed cell differs from parent")
    if model_path != Path(parent["model_path"]):
        ancestor = model["parent_model"]
        if (ancestor["model_id"], ancestor["version"], str(Path(ancestor["path"]).resolve())) != (parent["model_id"], parent["model_version"], parent["model_path"]):
            raise ValueError("child model does not bind the explicit common parent")
        if study["parent_study_id"] != parent["study_id"] or model["parent_study_id"] != parent["study_id"]:
            raise ValueError("child Study/model parent Study differs")
        lineage = model["atom_lineage"]
        if len(lineage) != len(ids) or {a["child_atom_id"] for a in lineage} != set(ids):
            raise ValueError("child atom lineage is incomplete")
        for entry in lineage:
            aid = entry["child_atom_id"]
            if entry["parent_atom_id"] != aid or entry["element"] != symbols[aid] or entry["parent_image"] != [0, 0, 0]:
                raise ValueError("child lineage must retain same-cell atom identities")
    elif study["study_id"] != parent_study["study_id"]:
        raise ValueError("parent model point must use the explicit parent Study")
    atom_map = _read(directory / "STRU.atom-map.json")
    if (atom_map["model_id"], atom_map["version"]) != identity or atom_map["source_atom_ids"] != ids:
        raise ValueError("SCF atom map identity differs from model")
    rows = atom_map["abacus_order"]
    if len(rows) != len(ids) or {r["atom_id"]: r["element"] for r in rows} != symbols or sorted(r["abacus_index"] for r in rows) != list(range(len(ids))):
        raise ValueError("SCF atom map elements/order differ")
    for row in rows:
        if ids[row["source_index"]] != row["atom_id"]:
            raise ValueError("SCF atom map source index differs from stable ID")
    final = result["final_atoms"]
    if result["atom_ids"] != ids or final["symbols"] != [symbols[i] for i in ids] or final["pbc"] != model["pbc"]:
        raise ValueError("saved SCF atom identities/periodicity differ")
    if not np.allclose(final["cell_angstrom"], cell, rtol=0, atol=1e-8) or not _same_positions(final["positions_angstrom"], positions, cell):
        raise ValueError("saved SCF final geometry differs from point model")
    conditions = task["calculation_conditions"]
    if conditions["cell_constraint"] != "fixed_cell" or conditions["applied_external_pressure_Pa"] is not None:
        raise ValueError("only fixed-cell energy, not imposed-pressure enthalpy, is supported")
    native_dir = directory / f"OUT.{method['suffix']}"
    expected_sources = {"running_scf.log": native_dir / "running_scf.log", "INPUT": directory / "INPUT", "method.json": directory / "method.json", "STRU.atom-map.json": directory / "STRU.atom-map.json"}
    for key, path in expected_sources.items():
        if Path(result["source_files"][key]).resolve() != path or not path.is_file():
            raise ValueError(f"saved SCF source {key} differs or is absent")
    signature, inputs = _method_signature(method, directory)
    if set(method["element_order"]) != set(model["composition"]):
        raise ValueError("method elements differ from model composition")
    software = any(_software(r) for r in (task, result, model, method, study, parent_model, parent_study))
    berry_path = spec["berry_result_file"]
    berry = None if berry_path is None else _berry_attachment(_path(base, berry_path), task, task_file, result_file, method)
    return {
        "point_id": _text(spec["point_id"], "point_id"), "coordinate": _number(spec["coordinate"], "coordinate"),
        "task_id": task["task_id"], "study_id": study["study_id"], "model_id": model["model_id"], "model_version": model["version"],
        "native_job": {k: task[k] for k in ("scheduler_job_id", "scheduler_state", "exit_code", "runner")},
        "energy_eV_cell": energy, "energy_definition": result["energy_definition"], "electronic_converged": True,
        "source": {"task_file": str(task_file), "result_file": str(result_file), "method_file": str(directory / "method.json"), "model_file": str(model_path / "model.json"), "study_file": str(study_file), "source_files": deepcopy(result["source_files"])},
        "geometry": {"atom_ids": ids, "symbols": [symbols[i] for i in ids], "cell_angstrom": cell.tolist(), "positions_angstrom": positions.tolist(), "pbc": model["pbc"], "composition": model["composition"], "atom_map": atom_map, "parent_model": model.get("parent_model"), "atom_lineage": model.get("atom_lineage")},
        "method": method, "common_method": signature, "input_records": inputs, "conditions": conditions,
        "berry": berry, "evidence_kind": "software_contract_only" if software else "native_saved_scf_engineering",
        "original_qualification_flags": {label: {k: record.get(k) for k in ("scientific_status", "scientific_qualification", "production_qualification", "numerical_qualification", "production_label", "fixture", "fixture_purpose", "evidence_kind")} for label, record in (("task", task), ("result", result), ("model", model), ("method", method), ("study", study))},
    }


def analyze_polarization_energy_path(request_path):
    """Bind saved SCF sources and calculate an explicitly ordered energy path."""
    request_path = Path(request_path).resolve()
    request = _read(request_path)
    if request["schema"] != "mlcc.polarization-energy-request.v1":
        raise ValueError("unsupported polarization energy request schema")
    for key in ("path_id", "path_basis", "reference_point_id"):
        _text(request[key], key)
    for key in ("name", "unit"):
        _text(request["path_coordinate"][key], f"path_coordinate.{key}")
    constraint = request["mechanical_constraint"]
    if set(constraint) != {"kind", "description"} or constraint["kind"] != "fixed_cell":
        raise ValueError("only supplied fixed-cell single points are supported; no NEB, stress or constrained relaxation")
    _text(constraint["description"], "mechanical_constraint.description")
    base = request_path.parent
    parent_path, study_file = _path(base, request["parent_model_path"]), _path(base, request["parent_study_file"])
    model, study = _read(parent_path / "model.json"), _read(study_file)
    _study_model_path(study, study_file, parent_path)
    if (study["model"]["model_id"], study["model"]["version"]) != (model["model_id"], model["version"]):
        raise ValueError("parent Study and model differ")
    parent = {"study_id": study["study_id"], "study_file": str(study_file), "model_id": model["model_id"], "model_version": model["version"], "model_path": str(parent_path)}
    points = [_point(s, base, parent, model, study) for s in request["points"]]
    if len(points) < 2:
        raise ValueError("energy path requires at least two saved SCF points")
    for key in ("task_id",):
        if len({p[key] for p in points}) != len(points):
            raise ValueError("duplicate SCF task cannot supply independent path points")
    if len({str(p["native_job"]["scheduler_job_id"]) for p in points}) != len(points):
        raise ValueError("duplicate native SCF job in energy path")
    for p in points[1:]:
        if p["common_method"] != points[0]["common_method"] or p["conditions"] != points[0]["conditions"]:
            raise ValueError("energy path physical/numerical/mechanical conditions differ")
    summary = _energy_summary(points, request["reference_point_id"])
    missing = [f"{p['point_id']}.berry_result" for p in points if p["berry"] is None]
    missing += ["reviewed_polarization_coordinate", "insulating_path_qualification", "ferroelectric_path_qualification"]
    return {
        "schema": "mlcc.polarization-energy-path.v1", "path_id": request["path_id"], "request_path": str(request_path),
        "path_basis": request["path_basis"], "path_coordinate": request["path_coordinate"], "mechanical_constraint": constraint,
        "parent": parent, **summary, "status": "computed_scf_energy_path_unqualified", "energy_unit": "eV/cell",
        "evidence_kind": "software_contract_only" if any(p["evidence_kind"] == "software_contract_only" for p in points) else "native_saved_scf_engineering",
        "native_jobs": [dict(p["native_job"], task_id=p["task_id"], point_id=p["point_id"]) for p in points],
        "common_method": points[0]["common_method"], "missing": missing, **_UNQUALIFIED,
        "parent_original_qualification_flags": {label: {key: record.get(key) for key in ("fixture", "fixture_purpose", "evidence_kind", "scientific_qualification", "production_qualification")} for label, record in (("model", model), ("study", study))},
    }
