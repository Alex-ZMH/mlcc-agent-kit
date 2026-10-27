"""Consume saved electronic levels as source-bound, unaligned references.

No native level parser, potential alignment, or formation-energy calculation
is implemented here.  These records describe the original calculation's
energy convention; separate calculations do not acquire a common potential
zero by being collected together.
"""
from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

REFERENCE_SCHEMA = "mlcc.defect-electronic-reference.v1"
ELECTRONIC_SCHEMA = "mlcc.abacus-electronic.v001"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def defect_electronic_reference(
    task_path: str | Path, electronic: Mapping[str, Any], *, role: str,
) -> dict[str, Any]:
    """Bind an existing reader result to one explicit host or defect task."""
    directory = Path(task_path).resolve()
    if directory.is_file():
        directory = directory.parent
    task_file = directory / "task.json"
    task = _read(task_file)
    result = _read(directory / "result.json")
    method = _read(directory / "method.json")
    if role not in ("host", "defect"):
        raise ValueError("reference role must be host or defect")
    if electronic["schema"] != ELECTRONIC_SCHEMA:
        raise ValueError("unsupported saved electronic schema")
    if (task["engine"], task["engine_version"], task["calculation"]) != ("abacus", "3.10.1", "scf"):
        raise ValueError("electronic reference requires ABACUS 3.10.1 SCF")
    if (task["status"], task["scheduler_state"], task["exit_code"]) != ("COMPLETED", "COMPLETED", "0:0"):
        raise ValueError("electronic reference task must be COMPLETED/0:0")
    if electronic["native_completed"] is not True or electronic["native_exit_code"] != "0:0":
        raise ValueError("saved electronic native completion differs")
    if result["electronic_converged"] is not True or electronic["electronic_converged"] is not True:
        raise ValueError("electronic reference requires saved electronic convergence")
    for key in ("task_id", "scheduler_job_id", "method_set"):
        if electronic[key] != task[key] or result[key] != task[key]:
            raise ValueError(f"electronic/result {key} differs from task")
    for key in ("engine", "engine_version", "model_id", "model_version"):
        if electronic[key] != task[key]:
            raise ValueError(f"electronic {key} differs from task")
    if (method["model_id"], method["version"], method["method_set"]) != (task["model_id"], task["model_version"], task["method_set"]):
        raise ValueError("method model or identity differs from task")
    if (method["engine"], method["abacus_version_target"]) != (task["engine"], task["engine_version"]):
        raise ValueError("method engine differs from task")
    study_file = Path(task["study_file"]).resolve()
    study = _read(study_file)
    if study["study_id"] != task["study_id"]:
        raise ValueError("Study identity differs from task")
    if (study["model"]["model_id"], study["model"]["version"]) != (task["model_id"], task["model_version"]):
        raise ValueError("Study model differs from task")
    model_file = Path(task["model_path"]).resolve() / "model.json"
    model = _read(model_file)
    if (model["model_id"], model["version"]) != (task["model_id"], task["model_version"]):
        raise ValueError("persisted model differs from task")
    atom_map_file = directory / "STRU.atom-map.json"
    atom_map = _read(atom_map_file)
    if (atom_map["model_id"], atom_map["version"]) != (task["model_id"], task["model_version"]):
        raise ValueError("atom map model differs from task")
    if atom_map["source_atom_ids"] != model["atom_ids"] or result["atom_ids"] != model["atom_ids"]:
        raise ValueError("reference atom IDs differ from model")
    if not np.allclose(result["final_atoms"]["cell_angstrom"], model["lattice_angstrom"], rtol=0, atol=1e-7):
        raise ValueError("fixed-cell result differs from model cell")
    if task["calculation_conditions"]["cell_constraint"] != "fixed_cell":
        raise ValueError("electronic reference requires fixed_cell")
    q = method["net_charge"]
    if isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q) or int(q) != q:
        raise ValueError("reference requires an explicit integer net_charge")
    if electronic["electron_count_q"] != q or electronic["electron_count_delta"] != -q:
        raise ValueError("electronic charge differs from method")
    if electronic["kpoint_mesh"] != method["kpoints"]:
        raise ValueError("saved electronic mesh differs from method")
    if "kpoint_shift" in method and electronic["kpoint_mesh_shift"] != method["kpoint_shift"]:
        raise ValueError("saved electronic mesh shift differs from method")
    for record in (task, result, task["calculation_conditions"]):
        if "net_charge" in record and record["net_charge"] != q:
            raise ValueError("saved task/result charge differs from method")
    descriptor = model.get("derivation")
    parent = model.get("parent_model")
    if role == "host":
        if q != 0 or (descriptor is not None and descriptor["kind"] == "explicit_defect_sequence"):
            raise ValueError("host role requires a neutral non-defect parent model")
    else:
        if model["derivation_schema"] != "mlcc.model-derivation.v1" or descriptor["kind"] != "explicit_defect_sequence":
            raise ValueError("defect role requires an explicit defect descriptor")
        if (descriptor["model_id"], descriptor["version"], descriptor["charge_state"]) != (model["model_id"], model["version"], q):
            raise ValueError("defect descriptor identity or charge differs")
        parent_file = Path(parent["path"]).resolve() / "model.json"
        parent_model = _read(parent_file)
        if (parent_model["model_id"], parent_model["version"]) != (parent["model_id"], parent["version"]):
            raise ValueError("defect parent model identity differs")
        if not np.allclose(parent_model["lattice_angstrom"], model["lattice_angstrom"], rtol=0, atol=1e-7):
            raise ValueError("defect reference parent cell differs")
    sources = dict(electronic["source_files"])
    native_dir = directory / f"OUT.{method['suffix']}"
    expected = {name: directory / name for name in ("task.json", "result.json", "method.json", "INPUT", "KPT")}
    expected.update({name: native_dir / name for name in ("running_scf.log", "istate.info", "kpoints")})
    for name, path in expected.items():
        if Path(sources[name]).resolve() != path:
            raise ValueError(f"electronic source {name} is not bound to the task")
        if not path.is_file():
            raise FileNotFoundError(path)
    if electronic["parent_energy_zero_eV"] != result["energy_eV"] or result["energy_unit"] != "eV":
        raise ValueError("parent total-energy provenance differs from saved result")
    for key in ("vbm_eV", "cbm_eV", "sampled_mesh_KS_gap_eV", "fermi_level_eV"):
        value = electronic[key]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError(f"electronic {key} must be finite or unresolved")
    return {
        "schema": REFERENCE_SCHEMA, "role": role,
        "status": "sampled_host_reference_unaligned" if role == "host" else "sampled_defect_levels_unaligned",
        "task_id": task["task_id"], "task_path": str(directory),
        "native_job": {key: task[key] for key in ("scheduler_job_id", "scheduler_state", "exit_code", "runner")},
        "study": {"study_id": study["study_id"], "source_file": str(study_file)},
        "model": {"model_id": model["model_id"], "version": model["version"], "path": str(model_file.parent), "metadata_file": str(model_file), "atom_ids": model["atom_ids"], "cell_angstrom": model["lattice_angstrom"], "atoms": model["atoms"], "atom_lineage": model.get("atom_lineage")},
        "parent_model": copy.deepcopy(parent), "defect_descriptor": copy.deepcopy(descriptor),
        "atom_map": {"source_file": str(atom_map_file), "record": atom_map},
        "method": copy.deepcopy(method), "conditions": copy.deepcopy(task["calculation_conditions"]),
        "kpoint_sampling": {
            "saved_electronic_mesh": electronic["kpoint_mesh"],
            "saved_electronic_shift": electronic["kpoint_mesh_shift"],
            "method_mesh": method["kpoints"],
            "method_shift": method.get("kpoint_shift"),
            "method_shift_status": "recorded" if "kpoint_shift" in method else "not_recorded",
        },
        "charge": {"q": q, "convention": "q_positive_removes_electrons", "neutral_electrons": electronic["electron_count_neutral"], "target_electrons": electronic["electron_count_target"], "native_electrons": electronic["electron_count_native"], "nelec_delta": electronic["electron_count_delta"], "production_compensation_selected": False},
        "levels": {"unit": "eV", "vbm_eV": electronic["vbm_eV"], "cbm_eV": electronic["cbm_eV"], "sampled_mesh_KS_gap_eV": electronic["sampled_mesh_KS_gap_eV"], "fermi_level_eV": electronic["fermi_level_eV"], "vbm_reference": electronic["vbm_reference"], "fermi_reference": electronic["fermi_reference"], "gap_status": electronic["gap_status"], "gap_qualification": copy.deepcopy(electronic["gap_qualification"]), "kpoint_coordinate_system": electronic["kpoint_coordinate_system"]},
        "parent_total_energy_provenance": {"value_eV": electronic["parent_energy_zero_eV"], "definition": electronic["parent_energy_zero_definition"], "original_field": "parent_energy_zero_eV", "is_potential_zero": False},
        "source_files": sources, "electronic_source": copy.deepcopy(dict(electronic)),
        "aligned_host_vbm_eV": None, "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None, "charged_formation_energy_eV": None,
        "missing_evidence": ["electrostatic_potential_grid", "common_potential_reference", "charge_correction_sources"],
        "scientific_qualification": False, "production_qualification": False,
    }


def read_defect_electronic_reference(
    task_path: str | Path, electronic_path: str | Path, *, role: str,
) -> dict[str, Any]:
    """Read a saved electronic result without rerunning its numerical parser."""
    path = Path(electronic_path).resolve()
    reference = defect_electronic_reference(task_path, _read(path), role=role)
    reference["electronic_source_file"] = str(path)
    return reference


def build_defect_electronic_reference(
    host_electronic_path: str | Path,
    defect_electronic_path: str | Path,
    descriptor_path: str | Path,
) -> dict[str, Any]:
    """Collect a descriptor-bound pair, explicitly reporting method differences.

    Pairing establishes lineage only.  It never aligns energy zeros or enables
    a charged formation-energy calculation.
    """
    records = []
    for path_value, role in ((host_electronic_path, "host"), (defect_electronic_path, "defect")):
        path = Path(path_value).resolve()
        electronic = _read(path)
        record = defect_electronic_reference(electronic["source_files"]["task.json"], electronic, role=role)
        record["electronic_source_file"] = str(path)
        records.append(record)
    host, defect = records
    descriptor_file = Path(descriptor_path).resolve()
    if descriptor_file != Path(defect["model"]["metadata_file"]):
        raise ValueError("explicit descriptor is not the defect task model metadata")
    parent = defect["parent_model"]
    if (parent["model_id"], parent["version"], str(Path(parent["path"]).resolve())) != (
        host["model"]["model_id"], host["model"]["version"], host["model"]["path"]
    ):
        raise ValueError("host reference is not the descriptor parent model")
    if not np.allclose(host["model"]["cell_angstrom"], defect["model"]["cell_angstrom"], rtol=0, atol=1e-7):
        raise ValueError("host and defect reference cells differ")
    physical_keys = (
        "engine", "abacus_version_target", "basis_type", "dft_functional",
        "nspin", "lspinorb", "noncolin", "occupations", "element_order",
        "initial_moments_muB_by_element", "pseudopotential_ids",
        "pseudopotential_metadata", "pseudopotential_treatment",
    )
    numerical_keys = ("ks_solver", "kpoints", "kpoint_rule", "mixing_type", "symmetry")
    optional_numerical_keys = ("kpoint_shift", "pw_diag_thr", "berry")
    physical = []
    numerical = []
    missing = []
    for record in records:
        method = record["method"]
        physical.append({**{key: copy.deepcopy(method[key]) for key in physical_keys if key in method},
                         "smearing_sigma_Ry": method["parameters"]["smearing_sigma_Ry"],
                         "smearing_method": method["smearing_method"]})
        numerical.append({**{key: copy.deepcopy(method[key]) for key in (*numerical_keys, *optional_numerical_keys) if key in method},
                          "parameters": copy.deepcopy(method["parameters"]),
                          "electronic.kpoint_mesh": record["kpoint_sampling"]["saved_electronic_mesh"],
                          "electronic.kpoint_mesh_shift": record["kpoint_sampling"]["saved_electronic_shift"]})
        missing.append([key for key in (*physical_keys, *numerical_keys) if key not in method])
    physical_differences = {key: [physical[0].get(key), physical[1].get(key)]
                            for key in sorted(set(physical[0]) | set(physical[1]))
                            if physical[0].get(key) != physical[1].get(key)}
    numerical_differences = {key: [numerical[0].get(key), numerical[1].get(key)]
                             for key in sorted(set(numerical[0]) | set(numerical[1]))
                             if numerical[0].get(key) != numerical[1].get(key)}
    same = not physical_differences and not numerical_differences and not any(missing)
    return {
        "schema": "mlcc.defect-reference-pair.v1",
        "status": "matching_recorded_fields_unaligned" if same else "different_or_incomplete_recorded_fields_unaligned",
        "host": host, "defect": defect, "descriptor_path": str(descriptor_file),
        "method_comparison": {
            "same_recorded_comparison_fields": same,
            "scope": "listed saved fields only; not complete physical-method or numerical-protocol equivalence",
            "compared_physical_fields": [*physical_keys, "smearing_method", "parameters.smearing_sigma_Ry"],
            "compared_numerical_fields": [*numerical_keys, *optional_numerical_keys, "parameters", "electronic.kpoint_mesh", "electronic.kpoint_mesh_shift"],
            "unassessed_method_fields_by_role": {
                record["role"]: sorted(set(record["method"]) - set((*physical_keys, *numerical_keys, *optional_numerical_keys, "parameters", "smearing_method")))
                for record in records
            },
            "same_method_label": host["method"]["method_set"] == defect["method"]["method_set"],
            "physical_differences": physical_differences,
            "numerical_differences": numerical_differences,
            "missing_fields_by_role": dict(zip(("host", "defect"), missing)),
            "charge_comparison": "q differs only as explicitly declared by each task and defect descriptor",
        },
        "energy_reference": "each source retains its native sampled KS levels; no common potential zero established",
        "aligned_host_vbm_eV": None, "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None, "charged_formation_energy_eV": None,
        "missing_evidence": ["electrostatic_potential_grid", "common_potential_reference", "chemical_potentials", "dielectric_screening", "charge_correction_sources"],
        "scientific_qualification": False, "production_qualification": False,
    }
