"""Small, explicit defect-thermodynamics contracts.

The functions in this module deliberately separate two kinds of work:

* :func:`chemical_potential_region`, :func:`formation_energy_terms`, and
  :func:`binding_energy` are mathematical post-processing functions.  They
  consume caller supplied numbers and never claim that the numbers came from
  a qualified material calculation.
* :func:`neutral_formation_from_tasks` is a narrow evidence adapter.  It reads
  two completed ABACUS task directories and a derived ``model.json`` from
  ``model_derivatives.py`` and only produces a *raw*, neutral formation-energy
  record after checking the native energy, model lineage, cell, and method
  identity.  When the chemical point is omitted, the same checks produce only
  the native host/defect energy difference and provenance; no formation energy
  is inferred.  Its current native scope is a fixed-cell SCF pair with common
  method physics and explicitly recorded common/new pseudopotential or
  numerical-orbital resources.  Host and defect compositions may differ (for
  example, a substitution can add a new element), but the adapter does not
  infer a resource for an element that is not present in the corresponding
  method record.  It does not run a solver or qualify a method.

Charged tasks intentionally remain outside the current ABACUS task contract.
The adapter returns ``blocked_current_charge_adapter`` for a non-zero charge;
it does not treat an input flag or an arbitrary boolean as evidence of a
charged-supercell or FNV/eFNV capability.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path
from typing import Any, Literal

import numpy as np
from scipy.optimize import linprog

from .elastic import _atom_mapping_valid, _load_bundle, _native_input_compatibility, _structure_match
from .modeling import read_model_artifacts


ABACUS_VERSION = "3.10.1"
_CELL_TOL = 1.0e-7

__all__ = [
    "chemical_potential_region",
    "formation_energy_terms",
    "binding_energy",
    "compare_variant_method_records",
    "neutral_formation_from_tasks",
]


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any, *, name: str) -> float:
    if not _finite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _integer(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _nonempty_text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _finite_vector(values: Any, *, name: str) -> list[float]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a finite sequence")
    result = [_number(value, name=f"{name}[{index}]") for index, value in enumerate(values)]
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _stoichiometry(value: Any, *, name: str, elements: set[str] | None = None) -> dict[str, int]:
    raw = _mapping(value, name=name)
    result: dict[str, int] = {}
    for key, item in raw.items():
        element = _nonempty_text(str(key), name=f"{name} element")
        count = _integer(item, name=f"{name}[{element}]")
        if count < 0:
            raise ValueError(f"{name}[{element}] must be non-negative")
        if count:
            result[element] = count
    if not result:
        raise ValueError(f"{name} must contain at least one positive count")
    if elements is not None and not set(result).issubset(elements):
        unknown = sorted(set(result) - elements)
        raise ValueError(f"{name} contains elements outside the explicit element list: {unknown}")
    return result


def _delta_composition(value: Any, *, name: str) -> dict[str, int]:
    raw = _mapping(value, name=name)
    result: dict[str, int] = {}
    for key, item in raw.items():
        element = _nonempty_text(str(key), name=f"{name} element")
        count = _integer(item, name=f"{name}[{element}]")
        if count:
            result[element] = count
    return result


def _source_tasks(value: Any, *, name: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ValueError(f"{name} must be a non-empty list of task IDs")
    return [_nonempty_text(item, name=f"{name} item") for item in value]


def _reference_identity(record: Mapping[str, Any], *, name: str) -> tuple[str, str, str, str]:
    engine = _nonempty_text(record.get("engine"), name=f"{name}.engine")
    version = _nonempty_text(record.get("engine_version"), name=f"{name}.engine_version")
    method_set = _nonempty_text(record.get("method_set"), name=f"{name}.method_set")
    energy_definition = _nonempty_text(
        record.get("energy_definition"), name=f"{name}.energy_definition"
    )
    return engine, version, method_set, energy_definition


_ABSENT = object()
_METHOD_TOP = {
    "schema", "engine", "engine_version", "abacus_version_target", "stage", "model_id",
    "version", "suffix", "device", "dft_functional", "basis_type", "ks_solver", "nspin",
    "lspinorb", "noncolin", "initial_moments_muB_by_element",
    "initial_magnetic_moment_muB_per_atom", "occupations", "smearing_method", "mixing_type",
    "relax_method", "symmetry", "net_charge", "nelec", "nelec_delta", "charge_convention",
    "element_order", "kpoints", "kpoint_rule", "kpoint_shift", "parameters",
    "pseudopotentials", "numerical_orbitals", "numerical_orbital_ids",
    "numerical_orbital_library", "method_set", "parent_method_set", "source_configuration",
    "fixture", "production_qualification", "scientific_qualification",
    "numerical_precision_qualified", "numerical_execution_qualified", "scope",
    "pseudopotential_ids", "pseudopotential_treatment", "pseudopotential_metadata",
    "input_qualification", "compatibility_reference", "stress_convention", "science",
    "execution", "gamma_only", "init_chg", "lcao_output", "berry", "ionic_constraints",
    "relax_new", "output_control", "requested_artifacts", "orbital_header_snapshot",
    "orbital_input_qualification", "method_input_qualified", "electron_count",
    "site_resources", "limitations", "execution_profile", "execution_decision",
    "purpose", "production_material", "binary", "potential", "geometry",
    "predeclared_acceptance", "predeclared_engineering_thresholds", "batch_budget",
    "supersedes", "revision_reason", "kmesh_rule", "cross_engine_comparison",
    "execution_budget", "reference_task_500eV", "parallel_route_evidence", "model",
    "created_date", "case", "energy_definition",
}
_SCIENCE = {
    "suffix", "basis_type", "dft_functional", "nspin", "initial_moments_muB_by_element", "occupations",
    "smearing_method", "mixing_type", "relax_method", "symmetry", "lspinorb",
    "noncolin", "net_charge",
}
_EXECUTION = {"device", "ks_solver"}
_PARAMETERS = {
    "ecutwfc_Ry", "scf_thr", "scf_nmax", "nbands", "smearing_sigma_Ry", "mixing_beta",
    "force_thr_eV_per_A", "relax_nmax", "cal_force", "cal_stress", "cutoff_comparison_Ry",
    "pw_diag_thr", "mixing_ndim", "mixing_restart", "diago_thr", "ecutrho_Ry", "ecutrho",
}
_PP_META = {
    "element", "functional", "valence_electrons_per_atom", "relativity",
    "has_spin_orbit", "type", "qualification",
}
_PP_CONFIG = ("pseudopotential_ids", "pseudopotential_treatment", "pseudopotential_metadata")
_PP_NATIVE = ("pseudopotentials", "pseudopotential_ids", "pseudopotential_treatment", "pseudopotential_metadata")
_NAO_CONFIG = ("numerical_orbital_ids",)
_NAO_NATIVE = ("numerical_orbitals", "numerical_orbital_ids")


def _element_names(value: Any, *, name: str) -> set[str]:
    if isinstance(value, Mapping):
        values = value.keys()
    elif isinstance(value, (set, frozenset, list, tuple)):
        values = value
    else:
        raise ValueError(f"{name} must be an element mapping or sequence")
    result = {_nonempty_text(str(item), name=f"{name} element") for item in values}
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(
            right, sort_keys=True, ensure_ascii=False
        )


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _path_value(record: Mapping[str, Any], path: Sequence[str]) -> Any:
    value: Any = record
    for part in path:
        if not isinstance(value, Mapping) or part not in value:
            return _ABSENT
        value = value[part]
    return value


def _unknown_fields(record: Mapping[str, Any], label: str) -> list[str]:
    result = [f"{label}.{key}" for key in record if key not in _METHOD_TOP]
    for name, allowed in (("science", _SCIENCE), ("execution", _EXECUTION), ("parameters", _PARAMETERS)):
        value = record.get(name)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            result.append(f"{label}.{name} (not an object)")
        else:
            result.extend(f"{label}.{name}.{key}" for key in value if key not in allowed)
    metadata = record.get("pseudopotential_metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        result.append(f"{label}.pseudopotential_metadata (not an object)")
    elif isinstance(metadata, Mapping):
        for element, item in metadata.items():
            if not isinstance(item, Mapping):
                result.append(f"{label}.pseudopotential_metadata.{element} (not an object)")
            else:
                result.extend(
                    f"{label}.pseudopotential_metadata.{element}.{key}"
                    for key in item if key not in _PP_META
                )
    return result


def _method_contract(
    record: Mapping[str, Any], *, kind: Literal["configuration", "native"], label: str
) -> tuple[dict[str, Any], list[str], list[str]]:
    if kind not in ("configuration", "native"):
        raise ValueError("record_kind must be 'configuration' or 'native'")
    if kind == "configuration":
        paths = {
            "engine": ("engine",), "engine_version": ("engine_version",),
            "basis_type": ("basis_type",), "dft_functional": ("science", "dft_functional"),
            "ks_solver": ("execution", "ks_solver"), "nspin": ("science", "nspin"),
            "lspinorb": ("science", "lspinorb"), "noncolin": ("science", "noncolin"),
            "initial_moments_muB_by_element": ("science", "initial_moments_muB_by_element"),
            "occupations": ("science", "occupations"), "smearing_method": ("science", "smearing_method"),
            "mixing_type": ("science", "mixing_type"), "relax_method": ("science", "relax_method"),
            "symmetry": ("science", "symmetry"), "net_charge": ("net_charge",),
            "charge_convention": ("charge_convention",), "element_order": ("element_order",),
            "kpoints": ("kpoints",), "kpoint_rule": ("kpoint_rule",),
            "kpoint_shift": ("kpoint_shift",), "gamma_only": ("gamma_only",),
            "init_chg": ("init_chg",), "nelec": ("nelec",), "nelec_delta": ("nelec_delta",),
            "stage": ("stage",), "parameters": ("parameters",),
        }
        defaults = {"lspinorb": False, "noncolin": False, "net_charge": 0}
        optional = {
            "charge_convention", "kpoint_rule", "kpoint_shift", "gamma_only", "init_chg",
            "nelec", "nelec_delta", "stage", "lspinorb", "noncolin", "net_charge",
        }
        pp_fields, nao_fields = _PP_CONFIG, _NAO_CONFIG
    else:
        paths = {
            "engine": ("engine",), "engine_version": ("abacus_version_target",),
            "basis_type": ("basis_type",), "dft_functional": ("dft_functional",),
            "ks_solver": ("ks_solver",), "nspin": ("nspin",), "lspinorb": ("lspinorb",),
            "noncolin": ("noncolin",), "initial_moments_muB_by_element": ("initial_moments_muB_by_element",),
            "occupations": ("occupations",), "smearing_method": ("smearing_method",),
            "mixing_type": ("mixing_type",), "relax_method": ("relax_method",),
            "symmetry": ("symmetry",), "net_charge": ("net_charge",),
            "charge_convention": ("charge_convention",), "element_order": ("element_order",),
            "kpoints": ("kpoints",), "kpoint_rule": ("kpoint_rule",),
            "kpoint_shift": ("kpoint_shift",), "gamma_only": ("gamma_only",),
            "init_chg": ("init_chg",), "nelec": ("nelec",), "nelec_delta": ("nelec_delta",),
            "stage": ("stage",), "parameters": ("parameters",),
        }
        defaults = {}
        optional = {"kpoint_shift", "gamma_only", "init_chg"}
        pp_fields, nao_fields = _PP_NATIVE, _NAO_NATIVE
    missing = []
    for key, path in paths.items():
        value = _path_value(record, path)
        if value is _ABSENT:
            if key in defaults:
                value = defaults[key]
            elif key in optional:
                value = None
            else:
                missing.append(f"{label}.{'.'.join(path)}")
        paths[key] = value
    method_set = record.get("method_set")
    if not isinstance(method_set, str) or not method_set.strip():
        missing.append(f"{label}.method_set")
        method_set = None
    contract = dict(paths, method_set=method_set, pp_fields=pp_fields, nao_fields=nao_fields)
    electron = {key: _json_value(paths[key]) for key in ("net_charge", "nelec", "nelec_delta") if paths[key] not in (_ABSENT, None)}
    if isinstance(record.get("electron_count"), Mapping):
        electron["electron_count"] = _json_value(record["electron_count"])
    contract["electron_snapshot"] = electron
    return contract, missing, _unknown_fields(record, label)


def _resource_records(
    record: Mapping[str, Any], elements: set[str], names: Sequence[str], label: str, missing: list[str]
) -> dict[str, dict[str, Any]]:
    result = {}
    for element in sorted(elements):
        signature = {}
        for name in names:
            value = record.get(name)
            if not isinstance(value, Mapping) or element not in value:
                missing.append(f"{label}.{name}.{element}")
            else:
                signature[name] = _json_value(value[element])
        result[element] = signature
    return result


def compare_variant_method_records(
    host_method: Mapping[str, Any], defect_method: Mapping[str, Any], *,
    host_elements: Mapping[str, Any] | Sequence[str] | set[str],
    defect_elements: Mapping[str, Any] | Sequence[str] | set[str],
    record_kind: Literal["configuration", "native"],
) -> dict[str, Any]:
    """Compare explicit ABACUS configuration/native records component-wise."""
    if not isinstance(host_method, Mapping) or not isinstance(defect_method, Mapping):
        raise ValueError("host_method and defect_method must be JSON objects")
    host_names, defect_names = _element_names(host_elements, name="host_elements"), _element_names(
        defect_elements, name="defect_elements"
    )
    host, host_missing, host_unsupported = _method_contract(host_method, kind=record_kind, label="host_method")
    defect, defect_missing, defect_unsupported = _method_contract(defect_method, kind=record_kind, label="defect_method")
    missing = host_missing + defect_missing
    unsupported = sorted(set(host_unsupported + defect_unsupported))
    mismatches = []
    common = host_names & defect_names
    new, removed = sorted(defect_names - host_names), sorted(host_names - defect_names)
    physical = (
        "engine", "engine_version", "basis_type", "dft_functional", "ks_solver", "nspin",
        "lspinorb", "noncolin", "occupations", "smearing_method",
        "mixing_type", "relax_method", "symmetry", "net_charge", "charge_convention", "kpoints",
        "kpoint_rule", "kpoint_shift", "gamma_only", "init_chg", "nelec_delta", "stage",
    )
    for key in physical:
        left, right = host[key], defect[key]
        if left is not _ABSENT and right is not _ABSENT and not _equal(left, right):
            mismatches.append({"field": key, "reason": "common_physical_mismatch", "host": _json_value(left), "defect": _json_value(right)})
    for label, contract in (("host", host), ("defect", defect)):
        net, delta = contract["net_charge"], contract["nelec_delta"]
        if contract["nelec"] not in (_ABSENT, None, 0):
            mismatches.append({"field": f"{label}.nelec", "reason": "electron_charge_contract_mismatch", "nelec": contract["nelec"], "required": "automatic neutral valence count (nelec=0)"})
        if net is not _ABSENT and delta not in (_ABSENT, None):
            try:
                valid = float(delta) == -float(net)
            except (TypeError, ValueError):
                valid = False
            if not valid:
                mismatches.append({"field": f"{label}.nelec_delta", "reason": "electron_charge_contract_mismatch", "net_charge": _json_value(net), "nelec_delta": _json_value(delta)})
    host_moments, defect_moments = host["initial_moments_muB_by_element"], defect["initial_moments_muB_by_element"]
    if isinstance(host_moments, Mapping) and isinstance(defect_moments, Mapping):
        for element in sorted(common):
            if element not in host_moments or element not in defect_moments:
                missing.append(f"common initial moment {element}")
            elif not _equal(host_moments[element], defect_moments[element]):
                mismatches.append({
                    "field": f"initial_moments_muB_by_element.{element}",
                    "reason": "common_physical_mismatch",
                    "host": _json_value(host_moments[element]),
                    "defect": _json_value(defect_moments[element]),
                })
    left_parameters, right_parameters = host["parameters"], defect["parameters"]
    parameter_differences = {}
    if isinstance(left_parameters, Mapping) and isinstance(right_parameters, Mapping):
        required_parameters = {"ecutwfc_Ry", "scf_thr", "scf_nmax", "nbands", "smearing_sigma_Ry", "mixing_beta", "force_thr_eV_per_A", "relax_nmax"}
        for label, values in (("host", left_parameters), ("defect", right_parameters)):
            missing.extend(f"common parameter {label}.{key}" for key in sorted(required_parameters - values.keys()))
        for key in sorted(set(left_parameters) | set(right_parameters)):
            left_has, right_has = key in left_parameters, key in right_parameters
            left, right = left_parameters.get(key), right_parameters.get(key)
            if key == "nbands":
                if left_has != right_has:
                    missing.append("composition parameter nbands")
                elif left_has and not _equal(left, right):
                    parameter_differences[key] = {"host": _json_value(left), "defect": _json_value(right)}
            elif left_has != right_has:
                missing.append(f"common parameter {key}")
            elif left_has and not _equal(left, right):
                mismatches.append({"field": f"parameters.{key}", "reason": "common_physical_mismatch", "host": _json_value(left), "defect": _json_value(right)})
    else:
        missing.append("both method.parameters mappings")
    for label, contract, expected in (("host", host, host_names), ("defect", defect, defect_names)):
        order = contract["element_order"]
        if order is _ABSENT:
            continue
        order = [str(value) for value in order]
        if len(order) != len(set(order)) or set(order) != expected:
            mismatches.append({"field": f"{label}.element_order", "reason": "element_order_does_not_match_model_composition", "declared": order, "expected": sorted(expected)})
    pp_host = _resource_records(host_method, host_names, host["pp_fields"], "host pseudopotential", missing)
    pp_defect = _resource_records(defect_method, defect_names, defect["pp_fields"], "defect pseudopotential", missing)
    nao_host = nao_defect = {}
    nao_required = str(host["basis_type"]).lower() == "lcao" or str(defect["basis_type"]).lower() == "lcao"
    if nao_required:
        nao_host = _resource_records(host_method, host_names, host["nao_fields"], "host numerical_orbital", missing)
        nao_defect = _resource_records(defect_method, defect_names, defect["nao_fields"], "defect numerical_orbital", missing)
    for label, left, right, names in (
        ("pseudopotential", pp_host, pp_defect, host["pp_fields"]),
        ("numerical_orbital", nao_host, nao_defect, host["nao_fields"]),
    ):
        if label == "numerical_orbital" and not nao_required:
            continue
        for element in sorted(common):
            for name in names:
                if name not in left.get(element, {}) or name not in right.get(element, {}):
                    missing.append(f"common {label} resource {name}.{element}")
                elif not _equal(left[element][name], right[element][name]):
                    mismatches.append({"field": f"{name}.{element}", "reason": f"common_{label}_mismatch", "host": left[element][name], "defect": right[element][name]})
    host_nelec, defect_nelec = host["nelec"], defect["nelec"]
    if (host_nelec is _ABSENT) != (defect_nelec is _ABSENT) or (host_nelec is None) != (defect_nelec is None):
        missing.append("composition electron count nelec")
    composition = {
        "element_set": {"host_only": removed, "defect_only": new},
        "method_set": {"host": host["method_set"], "defect": defect["method_set"], "same": host["method_set"] == defect["method_set"]},
        "electron_count": {"host": host["electron_snapshot"], "defect": defect["electron_snapshot"]},
    }
    if parameter_differences:
        composition["parameters"] = parameter_differences
    moment_differences = {
        element: {
            "host": host_moments.get(element) if isinstance(host_moments, Mapping) else None,
            "defect": defect_moments.get(element) if isinstance(defect_moments, Mapping) else None,
        }
        for element in sorted(host_names | defect_names)
        if element not in common
    }
    if moment_differences:
        composition["initial_moments_muB_by_element"] = moment_differences
    host_order, defect_order = host["element_order"], defect["element_order"]
    if host_order is not _ABSENT and defect_order is not _ABSENT and host_order != defect_order:
        composition["element_order"] = {"host": host_order, "defect": defect_order}
    host_meta, defect_meta = host_method.get("pseudopotential_metadata"), defect_method.get("pseudopotential_metadata")
    if isinstance(host_meta, Mapping) and isinstance(defect_meta, Mapping):
        valence = {}
        for element in sorted(host_names | defect_names):
            if element in common:
                continue
            h, d = host_meta.get(element), defect_meta.get(element)
            valence[element] = {
                "host": h.get("valence_electrons_per_atom") if isinstance(h, Mapping) else None,
                "defect": d.get("valence_electrons_per_atom") if isinstance(d, Mapping) else None,
            }
        if valence:
            composition["valence_electrons_per_atom"] = valence
    physical_failure = any(item["reason"] in {"common_physical_mismatch", "electron_charge_contract_mismatch"} for item in mismatches)
    result = {
        "status": "comparable" if not missing and not unsupported and not mismatches else "incompatible",
        "passed": not missing and not unsupported and not mismatches,
        "common_physics": (
            not physical_failure
            and not unsupported
            and not any(
                item.startswith(
                    (
                        "host_method.",
                        "defect_method.",
                        "common parameter",
                        "both method.parameters",
                        "common initial moment",
                        "composition electron count",
                    )
                )
                for item in missing
            )
        ),
        "common_element_pseudopotentials": not any(item.startswith("common pseudopotential") for item in missing) and not any(item["reason"] == "common_pseudopotential_mismatch" for item in mismatches),
        "common_element_numerical_orbitals": not any(item.startswith("common numerical_orbital") for item in missing) and not any(item["reason"] == "common_numerical_orbital_mismatch" for item in mismatches),
        "record_kind": record_kind, "host_elements": sorted(host_names), "defect_elements": sorted(defect_names),
        "common_elements": sorted(common), "new_elements": new, "removed_elements": removed,
        "composition_related_differences": composition,
        "resource_records": {"pseudopotentials": {"host": pp_host, "defect": pp_defect}, "numerical_orbitals": {"host": nao_host, "defect": nao_defect}},
        "resource_coverage": {
            "pseudopotentials": {"applicable": True, "host": {e: len(pp_host[e]) == len(host["pp_fields"]) for e in sorted(host_names)}, "defect": {e: len(pp_defect[e]) == len(defect["pp_fields"]) for e in sorted(defect_names)}},
            "numerical_orbitals": {"applicable": nao_required, "host": {e: len(nao_host[e]) == len(host["nao_fields"]) for e in sorted(host_names)} if nao_required else {}, "defect": {e: len(nao_defect[e]) == len(defect["nao_fields"]) for e in sorted(defect_names)} if nao_required else {}},
        },
        "missing": missing, "unsupported": unsupported, "mismatches": mismatches,
    }
    return result


def _reference_method_group(record: Mapping[str, Any], *, name: str) -> str | None:
    value = record.get("reference_method_id")
    if value is None:
        return None
    return _nonempty_text(value, name=f"{name}.reference_method_id")


def _reference_identity_matches(
    actual: tuple[str, str, str, str],
    expected: tuple[str, str, str, str],
    *,
    allow_method_set_difference: bool,
) -> bool:
    if actual[0] != expected[0] or actual[1] != expected[1] or actual[3] != expected[3]:
        return False
    return allow_method_set_difference or actual[2] == expected[2]


def _check_reference_identity(
    record: Mapping[str, Any],
    expected: tuple[str, str, str, str],
    *,
    name: str,
) -> None:
    actual = _reference_identity(record, name=name)
    if actual != expected:
        raise ValueError(f"{name} method/energy reference differs from the common reference")


def _parse_mu_reference(
    value: Any, *, element: str
) -> tuple[float, str, tuple[str, str, str, str], str | None]:
    record = _mapping(value, name=f"mu_ref[{element}]")
    numeric = _number(record.get("value_eV_per_atom"), name=f"mu_ref[{element}].value_eV_per_atom")
    source = _nonempty_text(record.get("source"), name=f"mu_ref[{element}].source")
    return (
        numeric,
        source,
        _reference_identity(record, name=f"mu_ref[{element}]"),
        _reference_method_group(record, name=f"mu_ref[{element}]"),
    )


def _phase_record(
    value: Any,
    *,
    name: str,
    elements: set[str],
    expected_reference: tuple[str, str, str, str] | None,
) -> tuple[dict[str, Any], tuple[str, str, str, str]]:
    record = _mapping(value, name=name)
    phase_id = _nonempty_text(record.get("phase_id"), name=f"{name}.phase_id")
    stoich = _stoichiometry(record.get("stoichiometry"), name=f"{name}.stoichiometry", elements=elements)
    formation = _number(record.get("formation_energy_eV"), name=f"{name}.formation_energy_eV")
    sources = _source_tasks(record.get("source_tasks"), name=f"{name}.source_tasks")
    identity = _reference_identity(record, name=name)
    reference_method_id = _reference_method_group(record, name=name)
    if expected_reference is not None and identity != expected_reference:
        raise ValueError(f"{name} does not use the common engine/method/energy definition")
    result = {
        "phase_id": phase_id,
        "stoichiometry": stoich,
        "formation_energy_eV": formation,
        "source_tasks": sources,
        "engine": identity[0],
        "engine_version": identity[1],
        "method_set": identity[2],
        "energy_definition": identity[3],
    }
    if reference_method_id is not None:
        result["reference_method_id"] = reference_method_id
    return result, identity


def _linear_constraints(
    elements: list[str],
    host: Mapping[str, Any],
    competing: list[Mapping[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    index = {element: offset for offset, element in enumerate(elements)}
    a_eq = np.zeros((1, len(elements)), dtype=float)
    for element, count in host["stoichiometry"].items():
        a_eq[0, index[element]] = float(count)
    b_eq = np.asarray([float(host["formation_energy_eV"])], dtype=float)
    a_ub = []
    b_ub = []
    for phase in competing:
        row = np.zeros(len(elements), dtype=float)
        for element, count in phase["stoichiometry"].items():
            row[index[element]] = float(count)
        a_ub.append(row)
        b_ub.append(float(phase["formation_energy_eV"]))
    return (
        np.asarray(a_ub, dtype=float) if a_ub else np.empty((0, len(elements)), dtype=float),
        np.asarray(b_ub, dtype=float),
        a_eq,
        b_eq,
    )


def _point_residuals(
    delta_mu: Mapping[str, Any],
    elements: list[str],
    host: Mapping[str, Any],
    competing: list[Mapping[str, Any]],
    mu_ref: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    point = {element: _number(delta_mu.get(element), name=f"selected_delta_mu[{element}]") for element in elements}
    host_lhs = sum(host["stoichiometry"].get(element, 0) * point[element] for element in elements)
    competition = {
        phase["phase_id"]: {
            "lhs_eV": sum(phase["stoichiometry"].get(element, 0) * point[element] for element in elements),
            "rhs_eV": phase["formation_energy_eV"],
            "residual_eV": phase["formation_energy_eV"]
            - sum(phase["stoichiometry"].get(element, 0) * point[element] for element in elements),
        }
        for phase in competing
    }
    return {
        "delta_mu_eV_per_atom": point,
        "mu_eV_per_atom": {
            element: mu_ref[element]["value_eV_per_atom"] + point[element]
            for element in elements
        },
        "host_residual_eV": host_lhs - host["formation_energy_eV"],
        "element_upper_bound_residual_eV": {
            element: -point[element] for element in elements
        },
        "competition": competition,
        "feasible": (
            abs(host_lhs - host["formation_energy_eV"]) <= 1.0e-8
            and all(point[element] <= 1.0e-8 for element in elements)
            and all(value["residual_eV"] >= -1.0e-8 for value in competition.values())
        ),
    }


def chemical_potential_region(request: Mapping[str, Any]) -> dict[str, Any]:
    """Solve the explicitly supplied 0 K chemical-potential inequalities.

    The returned region is a linear-programming feasibility and coordinate
    bound report.  No ``rich``/``poor`` point is selected automatically.
    ``temperature_model`` and ``oxygen_reservoir`` are metadata only; a
    finite-temperature or pO2 conversion requires caller-supplied free-energy
    inputs and is rejected when only a label is provided.
    """

    request = _mapping(request, name="chemical potential request")
    elements_raw = request.get("elements")
    if isinstance(elements_raw, (str, bytes)) or not isinstance(elements_raw, Sequence) or not elements_raw:
        raise ValueError("elements must be a non-empty ordered list")
    elements = [_nonempty_text(item, name="elements item") for item in elements_raw]
    if len(set(elements)) != len(elements):
        raise ValueError("elements must not contain duplicates")

    physics = _mapping(request.get("physics"), name="physics")
    temperature_model = _nonempty_text(physics.get("temperature_model"), name="physics.temperature_model")
    free_energy_sources = physics.get("free_energy_sources")
    if temperature_model != "0K_DFT_formation_energy" and (
        isinstance(free_energy_sources, (str, bytes))
        or not isinstance(free_energy_sources, Sequence)
        or not free_energy_sources
    ):
        raise ValueError(
            "non-0K chemical potentials require explicit physics.free_energy_sources"
        )
    if physics.get("oxygen_reservoir") is not None and not isinstance(
        physics.get("oxygen_reservoir"), Mapping
    ):
        raise ValueError("physics.oxygen_reservoir must be an explicit object or null")

    mu_ref_raw = _mapping(request.get("mu_ref"), name="mu_ref")
    if set(mu_ref_raw) != set(elements):
        raise ValueError("mu_ref must cover every explicit element exactly once")
    mu_ref: dict[str, dict[str, Any]] = {}
    mu_reference_identity: tuple[str, str, str, str] | None = None
    mu_reference_identities: list[tuple[str, str, str, str]] = []
    mu_reference_groups: list[str | None] = []
    for element in elements:
        value, source, identity, reference_method_id = _parse_mu_reference(
            mu_ref_raw[element], element=element
        )
        if mu_reference_identity is None:
            mu_reference_identity = identity
        mu_reference_identities.append(identity)
        mu_reference_groups.append(reference_method_id)
        mu_ref_record = {
            "value_eV_per_atom": value,
            "source": source,
            "engine": identity[0],
            "engine_version": identity[1],
            "method_set": identity[2],
            "energy_definition": identity[3],
        }
        if reference_method_id is not None:
            mu_ref_record["reference_method_id"] = reference_method_id
        mu_ref[element] = mu_ref_record

    host_raw = _mapping(request.get("host"), name="host")
    host, reference = _phase_record(
        host_raw,
        name="host",
        elements=set(elements),
        expected_reference=None,
    )
    competing_raw = request.get("competing_phases")
    if isinstance(competing_raw, (str, bytes)) or not isinstance(competing_raw, Sequence):
        raise ValueError("competing_phases must be a list")
    competing: list[dict[str, Any]] = []
    competing_references: list[tuple[str, str, str, str]] = []
    seen_phase_ids: set[str] = set()
    for offset, item in enumerate(competing_raw):
        phase, phase_reference = _phase_record(
            item,
            name=f"competing_phases[{offset}]",
            elements=set(elements),
            expected_reference=None,
        )
        if phase["phase_id"] in seen_phase_ids or phase["phase_id"] == host["phase_id"]:
            raise ValueError(f"duplicate phase_id {phase['phase_id']!r}")
        seen_phase_ids.add(phase["phase_id"])
        competing_references.append(phase_reference)
        competing.append(phase)

    declared_reference_groups = [
        *mu_reference_groups,
        host.get("reference_method_id"),
        *(phase.get("reference_method_id") for phase in competing),
    ]
    explicit_reference_groups = [group for group in declared_reference_groups if group is not None]
    reference_method_id: str | None = None
    if explicit_reference_groups:
        if any(group is None for group in declared_reference_groups):
            raise ValueError(
                "reference_method_id must be declared for every chemical-potential reference"
            )
        if len(set(explicit_reference_groups)) != 1:
            raise ValueError("all chemical-potential references must share reference_method_id")
        reference_method_id = explicit_reference_groups[0]

    allow_method_set_difference = reference_method_id is not None
    if mu_reference_identity is None:
        raise ValueError("mu_ref must contain at least one reference")
    if any(
        not _reference_identity_matches(
            identity,
            mu_reference_identity,
            allow_method_set_difference=allow_method_set_difference,
        )
        for identity in mu_reference_identities
    ):
        raise ValueError("all mu_ref elements must share engine/version/method/energy definition")
    if not _reference_identity_matches(
        reference,
        mu_reference_identity,
        allow_method_set_difference=allow_method_set_difference,
    ):
        raise ValueError("mu_ref and host must share engine/version/method/energy definition")
    if any(
        not _reference_identity_matches(
            phase_reference,
            reference,
            allow_method_set_difference=allow_method_set_difference,
        )
        for phase_reference in competing_references
    ):
        raise ValueError("all chemical-potential references must share engine/method/energy definition")

    a_ub, b_ub, a_eq, b_eq = _linear_constraints(elements, host, competing)
    bounds = [(None, 0.0) for _ in elements]
    feasibility = linprog(
        np.zeros(len(elements), dtype=float),
        A_ub=a_ub if a_ub.size else None,
        b_ub=b_ub if b_ub.size else None,
        A_eq=a_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    if feasibility.success:
        feasible = True
    elif feasibility.status == 2:
        feasible = False
    elif feasibility.status == 3:
        feasible = True
    else:
        raise ValueError(
            f"chemical-potential feasibility LP failed with status {feasibility.status}: {feasibility.message}"
        )
    coordinate_bounds: dict[str, dict[str, Any]] = {}
    for index, element in enumerate(elements):
        minimum = linprog(
            np.eye(1, len(elements), index, dtype=float).ravel(),
            A_ub=a_ub if a_ub.size else None,
            b_ub=b_ub if b_ub.size else None,
            A_eq=a_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs",
        )
        maximum = linprog(
            -np.eye(1, len(elements), index, dtype=float).ravel(),
            A_ub=a_ub if a_ub.size else None,
            b_ub=b_ub if b_ub.size else None,
            A_eq=a_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs",
        )
        for label, result in (("min", minimum), ("max", maximum)):
            if not result.success and result.status not in (2, 3):
                raise ValueError(
                    f"chemical-potential {label} LP for {element} failed with status "
                    f"{result.status}: {result.message}"
                )
            if feasible and result.status == 2:
                raise ValueError(
                    f"chemical-potential {label} LP for {element} is infeasible despite a feasible region"
                )
        coordinate_bounds[element] = {
            "min_delta_mu_eV_per_atom": float(minimum.fun) if minimum.success else None,
            "max_delta_mu_eV_per_atom": float(-maximum.fun) if maximum.success else None,
            "min_status": "optimal" if minimum.success else ("unbounded" if minimum.status == 3 else "infeasible"),
            "max_status": "optimal" if maximum.success else ("unbounded" if maximum.status == 3 else "infeasible"),
        }

    selected = request.get("selected_delta_mu")
    selected_report = None
    if selected is not None:
        selected_mapping = _mapping(selected, name="selected_delta_mu")
        if set(selected_mapping) != set(elements):
            raise ValueError("selected_delta_mu must cover the explicit element list exactly")
        selected_report = _point_residuals(selected, elements, host, competing, mu_ref)

    reference_record = {
        "engine": reference[0],
        "engine_version": reference[1],
        "method_set": reference[2],
        "energy_definition": reference[3],
    }
    if reference_method_id is not None:
        reference_record["reference_method_id"] = reference_method_id

    return {
        "schema": "mlcc.chemical-potential-region.v1",
        "status": "feasible" if feasible else "empty_region",
        "elements": elements,
        "physics": dict(physics),
        "reference": reference_record,
        "mu_ref": mu_ref,
        "host": host,
        "competing_phases": competing,
        "constraints": {
            "host_equality": {
                "stoichiometry": dict(host["stoichiometry"]),
                "rhs_eV": host["formation_energy_eV"],
            },
            "competition_inequalities": [
                {"phase_id": phase["phase_id"], "stoichiometry": dict(phase["stoichiometry"]), "rhs_eV": phase["formation_energy_eV"]}
                for phase in competing
            ],
            "element_upper_bounds": {element: 0.0 for element in elements},
        },
        "coordinate_bounds": coordinate_bounds,
        "selected_point": selected_report,
        "automatic_rich_poor_selection": False,
        "scientific_status": "mathematical_region_only",
        "production_qualification": False,
    }


_CORRECTION_COMPONENTS = (
    "potential_alignment_eV",
    "image_charge_eV",
    "band_filling_eV",
    "other_eV",
)


def _correction_terms(value: Mapping[str, Any] | None, *, q: int) -> dict[str, Any]:
    if value is None:
        if q != 0:
            raise ValueError("q != 0 requires explicit correction_terms with total_eV")
        return {"components_eV": {}, "total_eV": 0.0, "alignment_count": 0}
    raw = _mapping(value, name="correction_terms")
    if "alignment_eV" in raw:
        raise ValueError("potential alignment may be supplied only once as potential_alignment_eV")
    unknown = set(raw) - set(_CORRECTION_COMPONENTS) - {"total_eV", "method", "qualification"}
    if unknown:
        raise ValueError(f"correction_terms contains unsupported fields: {sorted(unknown)}")
    components: dict[str, float] = {}
    for key in _CORRECTION_COMPONENTS:
        if key in raw:
            components[key] = _number(raw[key], name=f"correction_terms.{key}")
    if "total_eV" not in raw:
        raise ValueError("correction_terms.total_eV is required")
    total = _number(raw["total_eV"], name="correction_terms.total_eV")
    component_sum = float(sum(components.values()))
    if not math.isclose(total, component_sum, rel_tol=0.0, abs_tol=1.0e-8):
        raise ValueError("correction_terms.total_eV differs from the explicit component sum")
    if q != 0 and not components:
        raise ValueError("q != 0 requires at least one explicit correction component")
    return {
        "components_eV": components,
        "total_eV": total,
        "alignment_count": int("potential_alignment_eV" in components),
        "method": raw.get("method"),
        "qualification": raw.get("qualification"),
    }


def formation_energy_terms(
    Edef: float,
    Ehost: float,
    deltaN: Mapping[str, Any],
    mu: Mapping[str, Any],
    q: int,
    vbm: float | None,
    ef_grid: Sequence[float] | None,
    correction_terms: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate the explicit 0 K formation-energy expression on an EF grid."""

    defect_energy = _number(Edef, name="Edef")
    host_energy = _number(Ehost, name="Ehost")
    charge = _integer(q, name="q")
    delta = _delta_composition(deltaN, name="deltaN")
    mu_raw = _mapping(mu, name="mu")
    if not set(delta).issubset(set(mu_raw)):
        raise ValueError("mu must cover every element present in deltaN")
    chemical = {element: _number(value, name=f"mu[{element}]") for element, value in mu_raw.items()}

    if charge == 0:
        vbm_value = None if vbm is None else _number(vbm, name="vbm")
        ef_values = [] if ef_grid is None else [_number(value, name="ef_grid item") for value in ef_grid]
    else:
        vbm_value = _number(vbm, name="vbm")
        ef_values = _finite_vector(ef_grid, name="ef_grid")
    correction = _correction_terms(correction_terms, q=charge)
    base_difference = defect_energy - host_energy
    chemical_term = -sum(delta[element] * chemical[element] for element in delta)
    raw_without_fermi = base_difference + chemical_term

    curve = []
    if not ef_values:
        curve = [
            {
                "ef_eV": None,
                "fermi_term_eV": 0.0,
                "formation_energy_eV": raw_without_fermi + correction["total_eV"],
            }
        ]
    else:
        for value in ef_values:
            fermi_term = float(charge * (vbm_value + value)) if charge else 0.0
            curve.append(
                {
                    "ef_eV": value,
                    "fermi_term_eV": fermi_term,
                    "formation_energy_eV": raw_without_fermi + fermi_term + correction["total_eV"],
                }
            )
    scalar = curve[0]["formation_energy_eV"] if len(curve) == 1 else None
    return {
        "schema": "mlcc.formation-energy.v1",
        "units": {
            "energy": "eV",
            "chemical_potential": "eV/atom",
            "fermi_level": "eV relative to host VBM",
        },
        "formula": "Edef - Ehost - sum(deltaN_i * mu_i) + q * (EVBM + EF) + Ecorr",
        "q": charge,
        "charge_convention": "q_positive_removes_electrons",
        "Edef_eV": defect_energy,
        "Ehost_eV": host_energy,
        "deltaN": delta,
        "mu_eV_per_atom": chemical,
        "vbm_eV": vbm_value,
        "ef_grid_eV": ef_values,
        "energy_difference_eV": base_difference,
        "chemical_potential_term_eV": chemical_term,
        "correction": correction,
        "raw_formation_energy_without_correction_eV": (
            raw_without_fermi if not ef_values else None
        ),
        "formation_energy_eV": scalar,
        "curve": curve,
        "scientific_status": "mathematical_postprocess_unqualified",
        "production_qualification": False,
        "size_convergence_qualified": False,
    }


def _formation_scalar(record: Mapping[str, Any], *, name: str) -> float:
    if "formation_energy_eV" not in record or record["formation_energy_eV"] is None:
        raise ValueError(f"{name}.formation_energy_eV must be one explicit scalar")
    return _number(record["formation_energy_eV"], name=f"{name}.formation_energy_eV")


def binding_energy(
    formation_records: Mapping[str, Mapping[str, Any]],
    stoichiometric_coefficients: Mapping[str, Any],
) -> dict[str, Any]:
    """Calculate a conserved-reaction binding energy from scalar records.

    Coefficients are signed: positive values are reactants/isolated defects
    and negative values are products/complexes.  A positive result is
    favorable under the explicitly supplied reaction convention.
    """

    records = _mapping(formation_records, name="formation_records")
    coefficients_raw = _mapping(stoichiometric_coefficients, name="stoichiometric_coefficients")
    if not records or set(coefficients_raw) != set(records):
        raise ValueError("stoichiometric_coefficients must cover every formation record exactly once")
    coefficients: dict[str, int] = {}
    for key, value in coefficients_raw.items():
        coefficient = _integer(value, name=f"stoichiometric_coefficients[{key}]")
        if coefficient == 0:
            raise ValueError("stoichiometric coefficients must be non-zero")
        coefficients[str(key)] = coefficient
    if not any(value > 0 for value in coefficients.values()) or not any(value < 0 for value in coefficients.values()):
        raise ValueError("binding reaction requires both reactant and product coefficients")

    first: Mapping[str, Any] | None = None
    identities: dict[str, Any] | None = None
    union_elements: set[str] = set()
    composition_balance: dict[str, int] = {}
    charge_balance = 0
    energy = 0.0
    terms: dict[str, float] = {}
    for record_id, record_value in records.items():
        record = _mapping(record_value, name=f"formation_records[{record_id}]")
        scalar = _formation_scalar(record, name=f"formation_records[{record_id}]")
        delta = _delta_composition(record.get("deltaN"), name=f"formation_records[{record_id}].deltaN")
        charge = _integer(record.get("q"), name=f"formation_records[{record_id}].q")
        identity_fields = (
            _nonempty_text(record.get("engine"), name=f"formation_records[{record_id}].engine"),
            _nonempty_text(record.get("engine_version"), name=f"formation_records[{record_id}].engine_version"),
            _nonempty_text(record.get("method_set"), name=f"formation_records[{record_id}].method_set"),
            _nonempty_text(record.get("energy_definition"), name=f"formation_records[{record_id}].energy_definition"),
            _nonempty_text(record.get("host_reference_id"), name=f"formation_records[{record_id}].host_reference_id"),
            _nonempty_text(record.get("chemical_potential_reference"), name=f"formation_records[{record_id}].chemical_potential_reference"),
            _nonempty_text(record.get("fermi_reference"), name=f"formation_records[{record_id}].fermi_reference"),
        )
        if identities is None:
            identities = {
                "engine": identity_fields[0],
                "engine_version": identity_fields[1],
                "method_set": identity_fields[2],
                "energy_definition": identity_fields[3],
                "host_reference_id": identity_fields[4],
                "chemical_potential_reference": identity_fields[5],
                "fermi_reference": identity_fields[6],
            }
        elif tuple(identities.values()) != identity_fields:
            raise ValueError("binding records must share engine, method, host, chemical-potential, and EF references")
        first = record if first is None else first
        multiplier = coefficients[str(record_id)]
        energy += multiplier * scalar
        terms[str(record_id)] = multiplier * scalar
        for element in delta:
            union_elements.add(element)
            composition_balance[element] = composition_balance.get(element, 0) + multiplier * delta[element]
        charge_balance += multiplier * charge

    if any(value != 0 for value in composition_balance.values()):
        raise ValueError(f"binding reaction composition is not conserved: {composition_balance}")
    if charge_balance != 0:
        raise ValueError(f"binding reaction charge is not conserved: {charge_balance}")
    assert identities is not None
    return {
        "schema": "mlcc.binding-energy.v1",
        "binding_energy_eV": float(energy),
        "positive_means": "the explicitly defined binding reaction is favorable",
        "stoichiometric_coefficients": coefficients,
        "formation_terms_eV": terms,
        "composition_balance": {element: composition_balance.get(element, 0) for element in sorted(union_elements)},
        "charge_balance": charge_balance,
        "reference": identities,
        "scientific_status": "mathematical_postprocess_unqualified",
        "production_qualification": False,
        "neb_or_rate_inference": False,
    }


def _task_directory(task: str | Path) -> Path:
    path = Path(task)
    if path.is_file():
        if path.name != "task.json":
            raise ValueError(f"task path must be a task directory or task.json: {path}")
        return path.parent.resolve()
    if path.is_dir():
        return path.resolve()
    raise FileNotFoundError(path)


def _load_task_bundle(task: str | Path) -> dict[str, Any]:
    directory = _task_directory(task)
    native_bundle = _load_bundle(directory)

    task_data = _mapping(native_bundle.get("task"), name=f"{directory}.task")
    method = _mapping(native_bundle.get("method"), name=f"{directory}.method")
    result = _mapping(native_bundle.get("result"), name=f"{directory}.result")
    task_id = _nonempty_text(task_data.get("task_id"), name="task.task_id")
    if result.get("task_id") != task_id:
        raise ValueError(f"result.task_id for {task_id} differs from task.json")
    if task_data.get("engine") != "abacus" or task_data.get("engine_version") != ABACUS_VERSION:
        raise ValueError(f"{task_id} is not an ABACUS {ABACUS_VERSION} task")
    if task_data.get("scheduler_state") != "COMPLETED" or task_data.get("exit_code") != "0:0":
        raise ValueError(f"{task_id} lacks a saved COMPLETED/0:0 scheduler result")
    if task_data.get("fixture") or result.get("fixture"):
        raise ValueError("engineering fixture tasks cannot supply material formation energies")
    if str(result.get("scientific_status", "")) != "converged":
        raise ValueError(f"{task_id} does not have a converged scientific result")

    if method.get("engine") != "abacus" or method.get("abacus_version_target") != ABACUS_VERSION:
        raise ValueError(f"{task_id} method.json is not an ABACUS {ABACUS_VERSION} method")
    if method.get("model_id") != task_data.get("model_id") or method.get("version") != task_data.get("model_version"):
        raise ValueError(f"{task_id} task and method model identities differ")
    if method.get("method_set") != task_data.get("method_set") or result.get("method_set") != task_data.get("method_set"):
        raise ValueError(f"{task_id} task, method, and result method_set identities differ")
    if method.get("stage") != "scf" or task_data.get("calculation") != "scf" or result.get("stage") != "scf":
        raise ValueError(f"{task_id} defect formation adapter supports fixed-cell SCF tasks only")
    if method.get("net_charge") != 0:
        raise ValueError(f"{task_id} native ABACUS task is not explicitly neutral (net_charge=0 required)")
    if not _native_input_compatibility(native_bundle):
        raise ValueError(f"{task_id} native INPUT is incompatible with method.json")
    if list(method.get("kpoints", [])) != native_bundle["kpt"].get("grid"):
        raise ValueError(f"{task_id} native KPT grid differs from method.json")
    if native_bundle["kpt"].get("offset") != [0, 0, 0]:
        raise ValueError(f"{task_id} native KPT must use the explicit Gamma mesh with zero offset")
    if method.get("kpoint_rule") != "explicit_mesh":
        raise ValueError(f"{task_id} method.json must record kpoint_rule=explicit_mesh")
    if not _atom_mapping_valid(native_bundle):
        raise ValueError(f"{task_id} native STRU atom mapping does not match input/result atom IDs")
    if not native_bundle.get("native_result_consistent"):
        raise ValueError(f"{task_id} result is inconsistent with native energy/stress/convergence evidence")
    source_evidence = _mapping(native_bundle.get("source_evidence"), name=f"{task_id}.source_evidence")
    if source_evidence.get("reason") != "complete" or source_evidence.get("paths_belong_to_task") is not True:
        raise ValueError(f"{task_id} result source evidence is incomplete or leaves the task directory")

    atoms = native_bundle["atoms"]
    if not bool(np.all(np.asarray(atoms.pbc, dtype=bool))):
        raise ValueError(f"{task_id} input.extxyz must be a periodic crystal")
    native_stru = native_bundle.get("native_stru")
    final_atoms = native_bundle.get("final_atoms")
    if native_stru is None or final_atoms is None:
        raise ValueError(f"{task_id} requires native STRU and final.extxyz geometry evidence")
    cell_tolerance = _CELL_TOL
    if not _structure_match(atoms, native_stru, _CELL_TOL, cell_tolerance)["passed"]:
        raise ValueError(f"{task_id} native STRU geometry differs from input.extxyz")
    if not _structure_match(atoms, final_atoms, _CELL_TOL, cell_tolerance)["passed"]:
        raise ValueError(f"{task_id} final.extxyz geometry differs from fixed-cell input.extxyz")
    if not _result_final_geometry_matches(result, final_atoms):
        raise ValueError(f"{task_id} result.final_atoms differs from final.extxyz")

    model_path_value = task_data.get("model_path")
    if model_path_value is None:
        raise ValueError(f"{task_id} must record model_path for defect lineage")
    model_path = Path(str(model_path_value))
    if not model_path.is_absolute():
        model_path = (directory / model_path).resolve()
    model_json = model_path / "model.json"
    if not model_json.is_file():
        raise ValueError(f"{task_id} model lineage is missing {model_json}")
    model_artifacts = read_model_artifacts(model_path)
    model = dict(model_artifacts.metadata)
    if (model_artifacts.model_id, model_artifacts.version) != (
        task_data.get("model_id"),
        task_data.get("model_version"),
    ):
        raise ValueError(f"{task_id} model.json identity differs from task.json")
    expected_cell = np.asarray(model.get("lattice_angstrom"), dtype=float)
    if expected_cell.shape != (3, 3) or not np.allclose(atoms.cell.array, expected_cell, rtol=0.0, atol=_CELL_TOL):
        raise ValueError(f"{task_id} input.extxyz cell differs from model.json")
    if not _structure_match(model_artifacts.atoms, atoms, _CELL_TOL, _CELL_TOL)["passed"]:
        raise ValueError(f"{task_id} input.extxyz coordinates/elements/IDs differ from model.extxyz")
    model_composition = _stoichiometry(model.get("composition"), name=f"{task_id}.model.composition")
    atoms_composition = {element: int(atoms.get_chemical_symbols().count(element)) for element in dict.fromkeys(atoms.get_chemical_symbols())}
    if model_composition != atoms_composition:
        raise ValueError(f"{task_id} input.extxyz composition differs from model.json")

    method_identity = _method_physics(method, task_data)
    return {
        "directory": directory,
        "model_path": model_path.resolve(),
        "task": dict(task_data),
        "method": dict(method),
        "result": dict(result),
        "native_energy_eV": float(native_bundle["native_energy_eV"]),
        "native_log": native_bundle["native_log"],
        "atoms": atoms,
        "model": dict(model),
        "method_identity": method_identity,
        "native_bundle": native_bundle,
    }


def _result_final_geometry_matches(result: Mapping[str, Any], final_atoms: Any) -> bool:
    record = result.get("final_atoms")
    if not isinstance(record, Mapping):
        return False
    symbols = record.get("symbols")
    positions = np.asarray(record.get("positions_angstrom"), dtype=float)
    cell = np.asarray(record.get("cell_angstrom"), dtype=float)
    pbc = record.get("pbc")
    return bool(
        isinstance(symbols, list)
        and symbols == final_atoms.get_chemical_symbols()
        and positions.shape == (len(final_atoms), 3)
        and np.allclose(positions, final_atoms.get_positions(), rtol=0.0, atol=_CELL_TOL)
        and cell.shape == (3, 3)
        and np.allclose(cell, final_atoms.cell.array, rtol=0.0, atol=_CELL_TOL)
        and isinstance(pbc, list)
        and pbc == [bool(value) for value in final_atoms.pbc]
    )


def _method_physics(method: Mapping[str, Any], task: Mapping[str, Any]) -> tuple[Any, ...]:
    parameters = _mapping(method.get("parameters"), name="method.parameters")
    pseudopotentials = _mapping(method.get("pseudopotentials"), name="method.pseudopotentials")
    return (
        task.get("engine"),
        task.get("engine_version"),
        task.get("method_set"),
        method.get("dft_functional"),
        method.get("basis_type"),
        method.get("ks_solver"),
        method.get("nspin"),
        method.get("lspinorb"),
        method.get("noncolin"),
        method.get("occupations"),
        method.get("smearing_method"),
        method.get("mixing_type"),
        method.get("symmetry"),
        tuple(method.get("element_order", [])),
        tuple(method.get("kpoints", [])),
        method.get("kpoint_rule"),
        tuple((key, parameters.get(key)) for key in (
            "ecutwfc_Ry", "scf_thr", "scf_nmax", "nbands", "smearing_sigma_Ry", "mixing_beta"
        )),
        json.dumps(pseudopotentials, sort_keys=True, ensure_ascii=False),
    )


def _load_descriptor(path: str | Path) -> dict[str, Any]:
    descriptor_path = Path(path)
    if not descriptor_path.is_file():
        raise FileNotFoundError(descriptor_path)
    value = json.loads(descriptor_path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("defect descriptor must be a JSON object")
    for key in ("model_id", "version", "parent_model", "derivation_schema", "derivation"):
        if key not in value:
            raise ValueError(f"derived model metadata requires {key}")
    _nonempty_text(value["model_id"], name="derived model model_id")
    _nonempty_text(value["version"], name="derived model version")
    if value.get("derivation_schema") != "mlcc.model-derivation.v1":
        raise ValueError("derived model metadata must use mlcc.model-derivation.v1")
    if value.get("production_qualified") is not False:
        raise ValueError("derived defect model must record production_qualified=false")
    parent_model = _mapping(value.get("parent_model"), name="derived model parent_model")
    _nonempty_text(parent_model.get("model_id"), name="parent_model.model_id")
    _nonempty_text(parent_model.get("version"), name="parent_model.version")
    parent_path = _nonempty_text(parent_model.get("path"), name="parent_model.path")
    if not Path(parent_path).is_dir():
        raise ValueError(f"derived model parent_model.path is not a directory: {parent_path}")
    derivation = _mapping(value.get("derivation"), name="derived model derivation")
    if derivation.get("kind") != "explicit_defect_sequence":
        raise ValueError("neutral defect formation requires explicit_defect_sequence metadata")
    if derivation.get("production_qualified") is not False:
        raise ValueError("derived defect derivation must record production_qualified=false")
    operations = derivation.get("operations")
    if isinstance(operations, (str, bytes)) or not isinstance(operations, Sequence) or not operations:
        raise ValueError("derived defect derivation requires non-empty operations")
    parent_composition = _stoichiometry(
        derivation.get("composition_parent"), name="derivation.composition_parent"
    )
    child_composition = _stoichiometry(
        derivation.get("composition_child"), name="derivation.composition_child"
    )
    metadata_composition = _stoichiometry(value.get("composition"), name="derived model composition")
    if metadata_composition != child_composition:
        raise ValueError("derived model composition differs from derivation.composition_child")
    derivation_delta = _delta_composition(
        derivation.get("composition_delta"), name="derivation.composition_delta"
    )
    all_elements = set(parent_composition) | set(child_composition)
    computed_delta = {
        element: child_composition.get(element, 0) - parent_composition.get(element, 0)
        for element in all_elements
        if child_composition.get(element, 0) - parent_composition.get(element, 0) != 0
    }
    if derivation_delta != computed_delta:
        raise ValueError("derived model composition_delta differs from parent/child composition")
    _integer(derivation.get("charge_state"), name="derivation.charge_state")
    parent_metadata_path = Path(parent_path) / "model.json"
    if not parent_metadata_path.is_file():
        raise ValueError(f"derived model parent_model.path is missing model.json: {parent_metadata_path}")
    parent_metadata = json.loads(parent_metadata_path.read_text(encoding="utf-8"))
    if not isinstance(parent_metadata, Mapping):
        raise ValueError("derived model parent model.json must contain an object")
    if (parent_metadata.get("model_id"), parent_metadata.get("version")) != (
        parent_model.get("model_id"),
        parent_model.get("version"),
    ):
        raise ValueError("derived model parent_model identity differs from its model.json")
    if _stoichiometry(parent_metadata.get("composition"), name="parent model composition") != parent_composition:
        raise ValueError("derived model parent composition differs from derivation.composition_parent")
    return dict(value)


def _model_ref(value: Any, *, name: str) -> tuple[str, str]:
    record = _mapping(value, name=name)
    return (
        _nonempty_text(record.get("model_id"), name=f"{name}.model_id"),
        _nonempty_text(record.get("version"), name=f"{name}.version"),
    )


def neutral_formation_from_tasks(
    host_task: str | Path,
    defect_task: str | Path,
    chemical_point: Mapping[str, Any] | None,
    descriptor_path: str | Path,
) -> dict[str, Any]:
    """Extract an unqualified neutral energy record from real tasks.

    ``descriptor_path`` points to the derived defect ``model.json`` written by
    :func:`mlcc.model_derivatives.derive_defect_model`.  A non-zero descriptor
    charge returns a blocked report so callers can show the missing charged
    formation-energy adapter without interpreting a neutral method record
    as a charged calculation.  The accepted neutral pair is limited to the
    current fixed-cell SCF contract with common method physics and explicit
    per-method PP/NAO resources. Composition changes are retained in the
    report; they are not treated as a reason to require identical method JSON.
    """

    descriptor = _load_descriptor(descriptor_path)
    derivation = _mapping(descriptor.get("derivation"), name="derived model derivation")
    charge = _integer(derivation.get("charge_state"), name="derivation.charge_state")
    if charge != 0:
        return {
            "schema": "mlcc.neutral-formation-from-tasks.v1",
            "status": "blocked_current_charge_adapter",
            "scientific_status": "blocked_current_charge_adapter",
            "production_qualification": False,
            "size_convergence_qualified": False,
            "charge_state": charge,
            "descriptor_kind": "explicit_defect_sequence",
            "issues": [
                "current formation-energy adapter only accepts explicit net_charge=0",
                "charged formation-energy alignment and FNV/eFNV native evidence are not available",
            ],
            "descriptor_path": str(Path(descriptor_path).resolve()),
        }

    host = _load_task_bundle(host_task)
    defect = _load_task_bundle(defect_task)
    host_ref = _model_ref(descriptor.get("parent_model"), name="parent_model")
    defect_ref = _model_ref(descriptor, name="derived model")
    host_identity = (str(host["task"]["model_id"]), str(host["task"]["model_version"]))
    defect_identity = (str(defect["task"]["model_id"]), str(defect["task"]["model_version"]))
    if host_identity != host_ref:
        raise ValueError("host task model lineage differs from defect descriptor")
    if defect_identity != defect_ref:
        raise ValueError("defect task model lineage differs from defect descriptor")
    descriptor_file = Path(descriptor_path).resolve()
    if defect["model_path"] != descriptor_file.parent:
        raise ValueError("defect task model path differs from derived model descriptor path")
    parent_descriptor_path = Path(str(descriptor["parent_model"]["path"])).resolve()
    if host["model_path"] != parent_descriptor_path:
        raise ValueError("host task model path differs from derived model parent_model.path")
    host_composition = _stoichiometry(host["model"].get("composition"), name="host model composition")
    defect_composition = _stoichiometry(defect["model"].get("composition"), name="defect model composition")
    method_comparison = compare_variant_method_records(
        host["method"],
        defect["method"],
        host_elements=set(host_composition),
        defect_elements=set(defect_composition),
        record_kind="native",
    )
    if not method_comparison["passed"]:
        raise ValueError(
            "host and defect ABACUS method contracts are incompatible: "
            + json.dumps(method_comparison, sort_keys=True, ensure_ascii=False)
        )
    if not np.allclose(host["atoms"].cell.array, defect["atoms"].cell.array, rtol=0.0, atol=_CELL_TOL):
        raise ValueError("host and defect task input cells differ")
    host_final = host["result"].get("final_atoms")
    defect_final = defect["result"].get("final_atoms")
    if isinstance(host_final, Mapping) and isinstance(defect_final, Mapping):
        host_cell = np.asarray(host_final.get("cell_angstrom"), dtype=float)
        defect_cell = np.asarray(defect_final.get("cell_angstrom"), dtype=float)
        if host_cell.shape != (3, 3) or defect_cell.shape != (3, 3) or not np.allclose(
            host_cell, defect_cell, rtol=0.0, atol=_CELL_TOL
        ):
            raise ValueError("host and defect native result cells differ")

    expected_delta = _delta_composition(
        derivation.get("composition_delta"), name="derivation.composition_delta"
    )
    actual_elements = set(host_composition) | set(defect_composition) | set(expected_delta)
    actual_delta = {
        element: defect_composition.get(element, 0) - host_composition.get(element, 0)
        for element in actual_elements
        if defect_composition.get(element, 0) - host_composition.get(element, 0) != 0
    }
    if actual_delta != expected_delta:
        raise ValueError(f"descriptor composition_delta differs from model lineage: {actual_delta} != {expected_delta}")

    host_definition = _nonempty_text(host["result"].get("energy_definition"), name="host result.energy_definition")
    defect_definition = _nonempty_text(defect["result"].get("energy_definition"), name="defect result.energy_definition")
    if host_definition != defect_definition:
        raise ValueError("host and defect tasks do not share an energy definition")

    if chemical_point is None:
        source_tasks = [host["task"]["task_id"], defect["task"]["task_id"]]
        return {
            "schema": "mlcc.neutral-formation-from-tasks.v1",
            "status": "raw_neutral_energy_only",
            "scientific_status": "raw_neutral_energy_unqualified",
            "production_qualification": False,
            "size_convergence_qualified": False,
            "defect_id": descriptor.get("model_id"),
            "descriptor_kind": "explicit_defect_sequence",
            "charge_state": 0,
            "deltaN": expected_delta,
            "Ehost_eV": host["native_energy_eV"],
            "Edefect_eV": defect["native_energy_eV"],
            "raw_energy_difference_eV": float(defect["native_energy_eV"] - host["native_energy_eV"]),
            "raw_formation_energy_eV": None,
            "corrected_formation_energy_eV": None,
            "chemical_point": None,
            "engine": host["task"].get("engine"),
            "engine_version": host["task"].get("engine_version"),
            "method_set": host["task"].get("method_set"),
            "energy_definition": host_definition,
            "method_comparison": method_comparison,
            "new_elements": method_comparison["new_elements"],
            "removed_elements": method_comparison["removed_elements"],
            "source_tasks": source_tasks,
            "source_jobs": {
                "host": host["task"].get("scheduler_job_id"),
                "defect": defect["task"].get("scheduler_job_id"),
            },
            "descriptor_path": str(Path(descriptor_path).resolve()),
            "evidence": {
                "energy_source": "native running_scf.log !FINAL_ETOT_IS",
                "host_native_log": str(host["native_log"]),
                "defect_native_log": str(defect["native_log"]),
                "host_scheduler_state": host["task"].get("scheduler_state"),
                "defect_scheduler_state": defect["task"].get("scheduler_state"),
                "host_exit_code": host["task"].get("exit_code"),
                "defect_exit_code": defect["task"].get("exit_code"),
                "common_method_physics": method_comparison["common_physics"],
                "common_element_pseudopotentials": method_comparison["common_element_pseudopotentials"],
                "common_element_numerical_orbitals": method_comparison["common_element_numerical_orbitals"],
                "method_comparison_passed": method_comparison["passed"],
                "common_energy_definition": True,
                "common_input_cell": True,
                "composition_and_model_lineage": True,
                "chemical_potential_available": False,
                "formation_energy_deferred": True,
            },
        }

    point = _mapping(chemical_point, name="chemical_point")
    mu = _mapping(point.get("mu_eV_per_atom"), name="chemical_point.mu_eV_per_atom")
    if not set(expected_delta).issubset(set(mu)):
        raise ValueError("chemical_point.mu_eV_per_atom must cover every descriptor.composition_delta element")
    point_engine = _nonempty_text(point.get("engine"), name="chemical_point.engine")
    point_engine_version = _nonempty_text(point.get("engine_version"), name="chemical_point.engine_version")
    point_method_set = _nonempty_text(point.get("method_set"), name="chemical_point.method_set")
    energy_definition = _nonempty_text(point.get("energy_definition"), name="chemical_point.energy_definition")
    source_reference = _nonempty_text(point.get("source_reference"), name="chemical_point.source_reference")
    if point_engine != host["task"].get("engine") or point_engine_version != host["task"].get("engine_version"):
        raise ValueError("chemical point engine identity differs from task identity")
    if point_method_set != host["task"].get("method_set"):
        raise ValueError("chemical point method_set differs from task method_set")
    if energy_definition != host_definition or energy_definition != defect_definition:
        raise ValueError("chemical point and task energies do not share an energy definition")
    descriptor_formation = formation_energy_terms(
        defect["native_energy_eV"],
        host["native_energy_eV"],
        expected_delta,
        mu,
        0,
        None,
        None,
        None,
    )
    scalar = descriptor_formation["curve"][0]["formation_energy_eV"]
    return {
        "schema": "mlcc.neutral-formation-from-tasks.v1",
        "status": "raw_neutral_formation_only",
        "scientific_status": "raw_neutral_formation_unqualified",
        "production_qualification": False,
        "size_convergence_qualified": False,
        "defect_id": descriptor.get("model_id"),
        "descriptor_kind": "explicit_defect_sequence",
        "charge_state": 0,
        "deltaN": expected_delta,
        "Ehost_eV": host["native_energy_eV"],
        "Edefect_eV": defect["native_energy_eV"],
        "chemical_point": dict(point),
        "engine": point_engine,
        "engine_version": point_engine_version,
        "method_set": point_method_set,
        "method_comparison": method_comparison,
        "new_elements": method_comparison["new_elements"],
        "removed_elements": method_comparison["removed_elements"],
        "chemical_potential_reference": source_reference,
        "raw_formation_energy_eV": scalar,
        "corrected_formation_energy_eV": None,
        "energy_definition": energy_definition,
        "source_tasks": [host["task"]["task_id"], defect["task"]["task_id"]],
        "descriptor_path": str(Path(descriptor_path).resolve()),
        "evidence": {
            "energy_source": "native running_scf.log !FINAL_ETOT_IS",
            "host_native_log": str(host["native_log"]),
            "defect_native_log": str(defect["native_log"]),
            "common_method_physics": method_comparison["common_physics"],
            "common_element_pseudopotentials": method_comparison["common_element_pseudopotentials"],
            "common_element_numerical_orbitals": method_comparison["common_element_numerical_orbitals"],
            "method_comparison_passed": method_comparison["passed"],
            "common_input_cell": True,
            "composition_and_model_lineage": True,
        },
        "formula_terms": descriptor_formation,
    }

