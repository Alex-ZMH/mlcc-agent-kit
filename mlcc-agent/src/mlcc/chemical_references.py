"""Declared phase references from saved neutral ABACUS sources.

No phase selection, native electronic parser, stability solver or scheduler.
Normalized energies remain scientifically unqualified source observations.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any

from .abacus import _energy_definition
from .defect_references import defect_electronic_reference


def _read(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _normalize(composition: dict, formula: dict, energy: float) -> tuple[int, float]:
    for name, counts in (("cell composition", composition), ("formula_stoichiometry", formula)):
        if not counts or any(type(n) is not int or n <= 0 for n in counts.values()):
            raise ValueError(f"{name} requires positive integer counts")
    if set(composition) != set(formula):
        raise ValueError("formula and cell composition must contain the same elements")
    element = next(iter(formula))
    units, remainder = divmod(composition[element], formula[element])
    if remainder or units < 1 or any(composition[e] != units * n for e, n in formula.items()):
        raise ValueError("cell composition must be an integer number of the declared formula units")
    if isinstance(energy, bool) or not isinstance(energy, (int, float)) or not math.isfinite(energy):
        raise ValueError("whole-cell reference energy must be finite eV")
    return units, energy / units


# Supported writer fields: unknown physical additions (U, fields, vdW, etc.)
# cannot silently enter a chemical reference group.
_METHOD_FIELDS = {
    "schema", "engine", "abacus_version_target", "stage", "model_id", "version", "suffix",
    "device", "dft_functional", "basis_type", "ks_solver", "nspin", "lspinorb", "noncolin",
    "initial_moments_muB_by_element", "occupations", "smearing_method", "mixing_type",
    "relax_method", "symmetry", "element_order", "kpoints", "kpoint_rule", "kpoint_shift",
    "pw_diag_thr", "parameters", "pseudopotentials", "science", "execution",
    "stress_convention", "berry", "method_set", "parent_method_set", "source_configuration",
    "fixture", "fixture_purpose", "pseudopotential_ids", "pseudopotential_metadata", "net_charge",
    "input_qualification", "pseudopotential_treatment", "compatibility_reference", "output_control", "requested_artifacts",
}
_SCIENCE_FIELDS = {
    "suffix", "dft_functional", "nspin", "initial_moments_muB_by_element", "occupations",
    "smearing_method", "mixing_type", "relax_method", "symmetry", "lspinorb", "noncolin",
}
_PARAMETER_FIELDS = {
    "ecutwfc_Ry", "scf_thr", "scf_nmax", "nbands", "smearing_sigma_Ry", "mixing_beta",
    "force_thr_eV_per_A", "relax_nmax", "pw_diag_thr",
}
_COMMON_FIELDS = ("engine", "abacus_version_target", "basis_type", "dft_functional", "lspinorb", "noncolin", "occupations")
_VARIABLE_FIELDS = ("method_set", "nspin", "initial_moments_muB_by_element", "symmetry", "ks_solver", "device", "parameters", "kpoints", "kpoint_shift", "kpoint_rule", "pw_diag_thr")


def _physical_method(source: Mapping[str, Any]) -> dict:
    method = source["method"]
    unsupported = sorted(set(method) - _METHOD_FIELDS)
    unsupported += [f"science.{k}" for k in sorted(set(method.get("science", {})) - _SCIENCE_FIELDS)]
    unsupported += [f"parameters.{k}" for k in sorted(set(method["parameters"]) - _PARAMETER_FIELDS)]
    if unsupported:
        raise ValueError(f"unsupported chemical reference method fields: {unsupported}")
    if (method["engine"], method["abacus_version_target"], method["basis_type"]) != ("abacus", "3.10.1", "pw"):
        raise ValueError("chemical references require ABACUS 3.10.1 PW")
    if method["net_charge"] != 0 or method["occupations"] != "fixed":
        raise ValueError("chemical references require neutral fixed occupations")
    if method["lspinorb"] is not False or method["noncolin"] is not False or method["nspin"] not in (1, 2):
        raise ValueError("chemical references require non-SOC collinear spin")
    definition = source["parent_total_energy_provenance"]["definition"]
    if definition != _energy_definition("fixed"):
        raise ValueError("chemical reference energy definition must be fixed-occupation whole-cell eV")
    return {**{key: method[key] for key in _COMMON_FIELDS}, "energy_definition": definition}


def read_chemical_reference(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Bind one saved source; the phase is an explicit caller declaration."""
    for key in ("reference_id", "phase_id", "phase_selection_source"):
        if not isinstance(spec[key], str) or not spec[key].strip():
            raise ValueError(f"{key} must be explicit")
    if spec["role"] not in ("host", "elemental", "competing"):
        raise ValueError("reference role must be host, elemental or competing")
    electronic_path = Path(spec["electronic_path"]).resolve()
    electronic = _read(electronic_path)
    source = defect_electronic_reference(spec["task_path"], electronic, role="host")
    source["electronic_source_file"] = str(electronic_path)
    _physical_method(source)
    if source["native_job"]["runner"] != "slurm" or not str(source["native_job"]["scheduler_job_id"]).isdigit():
        raise ValueError("chemical reference requires native Slurm job provenance")
    result = _read(source["source_files"]["result.json"])
    task = _read(source["source_files"]["task.json"])
    model = _read(source["model"]["metadata_file"])
    evidence_kind = electronic.get("evidence_kind", "native_saved_source")
    if evidence_kind not in ("native_saved_source", "software_contract_only"):
        raise ValueError("unsupported saved source evidence kind")
    if any(record.get("fixture") for record in (model, source["method"], task, result)) and evidence_kind != "software_contract_only":
        raise ValueError("engineering fixture is not a native chemical phase reference")
    if result["energy_definition"] != electronic["parent_energy_zero_definition"]:
        raise ValueError("saved electronic and result energy definition differ")
    composition = dict(model["composition"])
    if dict(Counter(result["final_atoms"]["symbols"])) != composition:
        raise ValueError("result atom counts differ from model composition")
    formula = dict(spec["formula_stoichiometry"])
    energy = source["parent_total_energy_provenance"]["value_eV"]
    units, per_formula = _normalize(composition, formula, energy)
    if spec["role"] == "elemental" and len(composition) != 1:
        raise ValueError("elemental reference must contain one element")
    return {
        "schema": "mlcc.chemical-reference.v1",
        **{key: spec[key] for key in ("reference_id", "role", "phase_id", "phase_selection_source")},
        "formula_stoichiometry": formula, "cell_composition": composition,
        "formula_units": units, "total_energy_eV_cell": energy,
        "energy_eV_per_formula_unit": per_formula,
        "elemental_mu_eV_per_atom": energy / sum(composition.values()) if spec["role"] == "elemental" else None,
        "normalization": "cell_composition = formula_units * formula_stoichiometry; total energy in eV/cell",
        "phase_status": "explicitly_declared_not_stability_verified",
        "method_set": source["method"]["method_set"],
        "source": source, "evidence_kind": evidence_kind,
        "scientific_qualification": False, "production_qualification": False,
    }


def _compare_methods(references: list[dict]) -> dict:
    physical = {r["reference_id"]: _physical_method(r["source"]) for r in references}
    first = next(iter(physical.values()))
    if any(values != first for values in physical.values()):
        raise ValueError("chemical reference common physical fields differ")
    pp_by_element: dict[str, dict] = {}
    for reference in references:
        method = reference["source"]["method"]
        for element in reference["cell_composition"]:
            identity = {key: deepcopy(method[key][element]) for key in (
                "pseudopotential_ids", "pseudopotential_metadata", "pseudopotential_treatment"
            )}
            if element in pp_by_element and identity != pp_by_element[element]:
                raise ValueError(f"chemical reference pseudopotential identity differs for {element}")
            pp_by_element[element] = identity
    differences = {}
    for key in _VARIABLE_FIELDS:
        values = {r["reference_id"]: deepcopy(r["source"]["method"].get(key)) for r in references}
        baseline = next(iter(values.values()))
        if any(value != baseline for value in values.values()):
            differences[key] = values
    return {
        "status": "recorded_physics_and_common_element_PP_match",
        "common_fields": first, "common_element_pseudopotentials": pp_by_element,
        "per_reference_differences": differences,
        "scope": "listed recorded physics and common-element PP only; numerical precision, magnetic ground state and phase stability unqualified",
        "scientific_qualification": False,
    }


def assemble_chemical_reference_set(request: Mapping[str, Any], references: list[dict]) -> dict[str, Any]:
    """Assemble available sources, without choosing phases, a point or a region."""
    if request["schema"] != "mlcc.chemical-reference-request.v1":
        raise ValueError("unsupported chemical reference request schema")
    if not isinstance(request["reference_set_id"], str) or not request["reference_set_id"].strip():
        raise ValueError("reference_set_id must be explicit")
    elements = request["elements"]
    if not elements or len(set(elements)) != len(elements):
        raise ValueError("elements must be a nonempty unique list")
    elemental_ids = request["elemental_reference_ids"]
    if set(elemental_ids) != set(elements):
        raise ValueError("elemental_reference_ids must cover all elements explicitly")
    by_id = {r["reference_id"]: r for r in references}
    if len(by_id) != len(references):
        raise ValueError("duplicate chemical reference IDs")
    declarations = {s["reference_id"]: s for s in request["references"]}
    if len(declarations) != len(request["references"]) or set(declarations) != set(by_id):
        raise ValueError("reference records must match declared reference IDs exactly")
    for reference in references:
        if reference["schema"] != "mlcc.chemical-reference.v1" or reference["evidence_kind"] not in ("native_saved_source", "software_contract_only"):
            raise ValueError("unsupported chemical reference record or evidence kind")
        spec = declarations[reference["reference_id"]]
        for key in ("role", "phase_id", "phase_selection_source", "formula_stoichiometry"):
            if reference[key] != spec[key]:
                raise ValueError(f"reference {key} differs from its declaration")
        if not set(reference["cell_composition"]).issubset(elements):
            raise ValueError("reference composition contains undeclared elements")
    host = by_id[request["host_reference_id"]]
    if host["role"] != "host" or sum(r["role"] == "host" for r in references) != 1 or set(host["cell_composition"]) != set(elements):
        raise ValueError("exactly one host must cover all declared elements")
    missing = []
    selected_ids = {host["reference_id"]}
    elemental = {}
    for element in elements:
        ref_id = elemental_ids[element]
        if ref_id is None:
            missing.append(f"elemental_reference:{element}")
            continue
        reference = by_id[ref_id]
        if reference["role"] != "elemental" or set(reference["cell_composition"]) != {element}:
            raise ValueError(f"elemental reference role/composition differs for {element}")
        elemental[element] = reference
        selected_ids.add(ref_id)
    competing_ids = request["competing_reference_ids"]
    competing = []
    if competing_ids is None:
        missing.append("competing_phase_selection")
    else:
        if not isinstance(competing_ids, list) or len(set(competing_ids)) != len(competing_ids):
            raise ValueError("competing_reference_ids must be an explicit unique list or null")
        for ref_id in competing_ids:
            reference = by_id[ref_id]
            if reference["role"] != "competing":
                raise ValueError("competing reference role differs")
            competing.append(reference)
            selected_ids.add(ref_id)
    if selected_ids != set(by_id):
        raise ValueError("all declared references must have an explicit selected role")
    if request["selected_delta_mu"] is None:
        missing.append("selected_delta_mu")
    else:
        point = request["selected_delta_mu"]
        if set(point) != set(elements) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point.values()):
            raise ValueError("selected_delta_mu must explicitly cover elements with finite eV/atom values")
    comparison = _compare_methods(references)
    region = None
    if len(elemental) == len(elements) and competing_ids is not None:
        def identity(reference: dict) -> dict:
            method = reference["source"]["method"]
            return {
                "engine": method["engine"], "engine_version": method["abacus_version_target"],
                "method_set": method["method_set"], "reference_method_id": request["reference_set_id"],
                "energy_definition": reference["source"]["parent_total_energy_provenance"]["definition"],
                "reference_id": reference["reference_id"],
            }

        mu_ref = {element: {
            "value_eV_per_atom": reference["elemental_mu_eV_per_atom"],
            "source": reference["source"]["task_id"],
            "source_tasks": [reference["source"]["task_id"]], **identity(reference),
        } for element, reference in elemental.items()}

        def phase(reference: dict) -> dict:
            formula = reference["formula_stoichiometry"]
            return {
                "phase_id": reference["phase_id"], "stoichiometry": deepcopy(formula),
                "formation_energy_eV": reference["energy_eV_per_formula_unit"] - sum(n * mu_ref[e]["value_eV_per_atom"] for e, n in formula.items()),
                "source_tasks": list(dict.fromkeys([reference["source"]["task_id"], *(elemental[e]["source"]["task_id"] for e in formula)])),
                **identity(reference),
            }

        region = {
            "elements": list(elements), "physics": {"temperature_model": "0K_DFT_formation_energy", "oxygen_reservoir": None},
            "mu_ref": mu_ref, "host": phase(host), "competing_phases": [phase(r) for r in competing],
            "selected_delta_mu": deepcopy(request["selected_delta_mu"]),
        }
    return {
        "schema": "mlcc.chemical-reference-set.v1", "reference_set_id": request["reference_set_id"],
        "elements": list(elements), "host_reference_id": request["host_reference_id"],
        "references": [{**deepcopy(r), "method_set": r["source"]["method"]["method_set"], "reference_method_id": request["reference_set_id"]} for r in references],
        "per_reference_methods": {r["reference_id"]: deepcopy(r["source"]["method"]) for r in references},
        "method_comparison": comparison, "missing": missing, "region_request": region,
        "elemental_reference_ids": deepcopy(elemental_ids), "competing_reference_ids": deepcopy(competing_ids),
        "competing_phase_scope": "unresolved" if competing_ids is None else "explicit_declared_subset_not_complete_phase_inventory",
        "selected_delta_mu": deepcopy(request["selected_delta_mu"]),
        "evidence_kind": "native_saved_source" if all(r["evidence_kind"] == "native_saved_source" for r in references) else "software_contract_only",
        "scientific_status": "source_bound_reference_set_unqualified",
        "scientific_qualification": False, "production_qualification": False,
    }


def build_chemical_reference_set(request_path: str | Path) -> dict[str, Any]:
    """Read an explicit manifest; relative source paths are manifest-relative."""
    path = Path(request_path).resolve()
    request = _read(path)
    references = []
    for spec in request["references"]:
        resolved = dict(spec)
        for key in ("task_path", "electronic_path"):
            resolved[key] = str((path.parent / spec[key]).resolve())
        references.append(read_chemical_reference(resolved))
    result = assemble_chemical_reference_set(request, references)
    result["request_path"] = str(path)
    return result
