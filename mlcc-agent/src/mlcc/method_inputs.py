"""Direct ABACUS method-input compatibility checks.

This module checks the inputs that are needed before an ABACUS PW or LCAO method can
be handed to the task writer.  It deliberately does not run ABACUS, infer a
missing pseudopotential, or assign a scientific/material qualification.  A
successful report means that the declared model, UPF headers, spin/occupation
contract, and native-input interface are self-consistent only.

``parse_upf_header`` accepts either a complete UPF 2.x file or a preserved
``<UPF>``/``<PP_HEADER>`` fragment.  ``qualify_method_inputs`` accepts a
``ModelArtifacts`` instance, a method configuration, parsed UPF headers keyed
by element, and the pseudopotential path mapping used by the method.

The first charged slice supports only explicit integer ``net_charge`` values
for fixed-cell, non-SOC, ``nspin=1`` fixed-occupation SCF.  Positive q removes
q electrons and is written to ABACUS as ``nelec=0`` and
``nelec_delta=-q``.  Charged results remain raw/unqualified until native
electron-count binding is performed.  Spin-polarized fixed occupations remain
unsupported until a native spin-electron occupation definition is implemented;
initial magnetic moments do not define those populations.
"""

from __future__ import annotations

from dataclasses import fields
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np

from .abacus import (
    ABACUS_VERSION,
    AbacusExecution,
    AbacusMethod,
    AbacusParameters,
    abacus_method_from_config,
)
from .modeling import ModelArtifacts
from .upf_headers import normalize_functional, parse_upf_header, read_upf_header


_NAO_ELEMENT_RE = re.compile(r"^\s*Element\s+(?P<value>\S.*?)\s*$", re.IGNORECASE)
_NAO_ECUT_RE = re.compile(
    r"^\s*Energy\s+Cutoff\s*\(\s*Ry\s*\)\s+(?P<value>[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+\-]?\d+)?)\s*$",
    re.IGNORECASE,
)
_NAO_RADIUS_RE = re.compile(
    r"^\s*Radius\s+Cutoff\s*\(\s*a\.u\.\s*\)\s+(?P<value>[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+\-]?\d+)?)\s*$",
    re.IGNORECASE,
)
_NAO_LMAX_RE = re.compile(r"^\s*Lmax\s+(?P<value>\d+)\s*$", re.IGNORECASE)
_NAO_RADIAL_RE = re.compile(
    r"^\s*Number\s+of\s+(?P<orbital>[spdfg])\s*orbital(?:s)?\s*[-=]*>\s*(?P<count>\d+)\s*$",
    re.IGNORECASE,
)


def parse_nao_header(text: str, source_path: str | Path) -> dict[str, Any]:
    """Parse only native fields from an ABACUS numerical-orbital header.

    The native efficiency-orbital header contains the element, cutoff, radius,
    maximum angular momentum, and radial orbital counts.  It does not declare
    an exchange-correlation functional or a pseudopotential pairing.  Those
    values are deliberately left to the explicit library-pairing metadata
    consumed by :func:`qualify_lcao_orbitals`.
    """

    if not isinstance(text, str) or not text.strip():
        raise ValueError("NAO header text must be non-empty")
    path_text = str(source_path)
    lines = text.splitlines()

    def _match(pattern: re.Pattern[str], label: str) -> str:
        for line in lines:
            match = pattern.match(line)
            if match:
                return match.group("value").strip()
        raise ValueError(f"NAO {path_text} header is missing {label}")

    element = _match(_NAO_ELEMENT_RE, "Element")
    try:
        energy_cutoff = float(_match(_NAO_ECUT_RE, "Energy Cutoff(Ry)"))
        radius_cutoff = float(_match(_NAO_RADIUS_RE, "Radius Cutoff(a.u.)"))
        lmax = int(_match(_NAO_LMAX_RE, "Lmax"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NAO {path_text} header contains an invalid native numeric field") from exc

    radial_counts: dict[str, int] = {}
    for line in lines:
        match = _NAO_RADIAL_RE.match(line)
        if match:
            orbital = match.group("orbital").lower()
            if orbital in radial_counts:
                raise ValueError(f"NAO {path_text} header repeats the {orbital} radial count")
            radial_counts[orbital] = int(match.group("count"))
    if not radial_counts:
        raise ValueError(f"NAO {path_text} header is missing radial orbital counts")
    if not math.isfinite(energy_cutoff) or energy_cutoff <= 0.0:
        raise ValueError(f"NAO {path_text} requires positive finite Energy Cutoff(Ry)")
    if not math.isfinite(radius_cutoff) or radius_cutoff <= 0.0:
        raise ValueError(f"NAO {path_text} requires positive finite Radius Cutoff(a.u.)")
    if lmax < 0:
        raise ValueError(f"NAO {path_text} requires non-negative Lmax")

    return {
        "source_path": path_text,
        "native_excerpt": text,
        "element": element,
        "energy_cutoff_Ry": energy_cutoff,
        "radius_cutoff_au": radius_cutoff,
        "lmax": lmax,
        "radial_counts": radial_counts,
    }


def qualify_lcao_orbitals(
    config: Mapping[str, Any],
    orbital_headers: Mapping[str, Mapping[str, Any]] | None,
    orbital_paths: Mapping[str, str | Path] | None,
) -> dict[str, Any]:
    """Qualify explicit LCAO numerical-orbital and UPF pairing metadata.

    The parsed native headers are intentionally separate from the declared
    library pairing.  In particular, a filename containing ``gga`` does not
    establish PBE.  The caller must provide the declared functional,
    library/version, pairing record, orbital ID, and paired pseudopotential
    metadata alongside each parsed native header.
    """

    report: dict[str, Any] = {
        "schema": "mlcc.lcao-orbital-qualification.v1",
        "basis_type": config.get("basis_type"),
        "required": config.get("basis_type") == "lcao",
        "passed": False,
        "input_qualified": False,
        "scientific_qualification": False,
        "production_qualification": False,
        "source_kind": "declared_library_pairing",
        "issues": [],
        "checks": {},
        "orbital_headers": {},
    }
    if config.get("basis_type") != "lcao":
        report["passed"] = True
        report["input_qualified"] = True
        report["required"] = False
        return report

    headers = orbital_headers if isinstance(orbital_headers, Mapping) else {}
    paths = orbital_paths if isinstance(orbital_paths, Mapping) else {}
    element_order = config["element_order"]
    if not isinstance(element_order, Sequence) or isinstance(element_order, (str, bytes)):
        expected_elements: list[str] = []
        report["issues"].append("LCAO element_order is required for numerical-orbital qualification")
    else:
        expected_elements = [str(value) for value in element_order]
    expected_set = set(expected_elements)

    def _record_check(name: str, passed: bool, detail: Any = None) -> None:
        report["checks"][name] = {"passed": bool(passed)}
        if detail is not None:
            report["checks"][name]["detail"] = detail

    def _issue(message: str) -> None:
        report["issues"].append(message)

    header_keys = {str(key) for key in headers}
    path_keys = {str(key) for key in paths}
    elements_ok = header_keys == expected_set and path_keys == expected_set and len(expected_elements) == len(expected_set)
    _record_check("elements", elements_ok, {"expected": expected_elements, "headers": sorted(header_keys), "paths": sorted(path_keys)})
    if not elements_ok:
        _issue("LCAO numerical orbital headers and paths must cover element_order exactly")

    numerical_ids = config["numerical_orbital_ids"]
    ids_ok = isinstance(numerical_ids, Mapping) and {str(key) for key in numerical_ids} == expected_set
    _record_check("orbital_ids", ids_ok, numerical_ids)
    if not ids_ok:
        _issue("numerical_orbital_ids must explicitly cover each LCAO element")

    parameters = config["parameters"]
    ecut = parameters["ecutwfc_Ry"]
    ecut_ok = _finite_number(ecut) and float(ecut) > 0.0
    if not ecut_ok:
        _issue("parameters.ecutwfc_Ry must be positive for LCAO numerical-orbital qualification")

    science = config["science"]
    method_functional = science["dft_functional"]
    method_pbe = str(method_functional or "").strip().upper() == "PBE"
    _record_check("method_pbe", method_pbe, method_functional)
    if not method_pbe:
        _issue("LCAO method dft_functional must be explicit PBE")

    pseudo_ids = config["pseudopotential_ids"]
    pseudo_paths = config["_pseudopotential_files"]

    seen_names: list[str] = []
    path_identity_ok = True
    ids_binding_ok = True
    pseudo_binding_ok = True
    functional_ok = True
    library_ok = True
    cutoff_ok = ecut_ok
    radial_ok = True
    element_match_ok = True
    for element in expected_elements:
        header = headers.get(element)
        if not isinstance(header, Mapping):
            _issue(f"missing parsed NAO header for {element}")
            path_identity_ok = ids_binding_ok = pseudo_binding_ok = functional_ok = library_ok = cutoff_ok = radial_ok = element_match_ok = False
            continue
        native = dict(header)
        report["orbital_headers"][element] = native
        if str(native.get("element", "")).strip() != element:
            element_match_ok = False
            _issue(f"NAO header element for {element} does not match the mapping key")
        source_path = str(native["source_path"]).strip()
        selected_path = str(paths[element]).strip()
        if not source_path or source_path != selected_path:
            path_identity_ok = False
            _issue(f"NAO header source_path for {element} does not match selected numerical orbital path")
        if selected_path:
            seen_names.append(Path(selected_path).name)
        configured_id = numerical_ids[element]
        orbital_id = native["orbital_id"]
        if configured_id in (None, "") or str(orbital_id).strip() != str(configured_id).strip():
            ids_binding_ok = False
            _issue(f"NAO orbital_id for {element} does not match numerical_orbital_ids")

        paired_id = native["paired_pseudopotential_id"]
        configured_pseudo_id = pseudo_ids[element]
        if configured_pseudo_id in (None, "") or str(paired_id).strip() != str(configured_pseudo_id).strip():
            pseudo_binding_ok = False
            _issue(f"NAO paired_pseudopotential_id for {element} does not match pseudopotential_ids")
        paired_source = native["paired_pseudopotential_source"]
        expected_pseudo_source = str(pseudo_paths[element]).strip()
        if not str(paired_source or "").strip() or (expected_pseudo_source and str(paired_source).strip() != expected_pseudo_source):
            pseudo_binding_ok = False
            _issue(f"NAO paired_pseudopotential_source for {element} is missing or does not match the selected UPF")

        declared_functional = native["functional"]
        source_kind = native["source_kind"]
        if normalize_functional(str(declared_functional or "")) != "PBE":
            functional_ok = False
            _issue(f"NAO declared library functional for {element} must be PBE")
        if str(source_kind or "").strip() != "declared_library_pairing":
            functional_ok = False
            _issue(f"NAO functional for {element} must have source_kind='declared_library_pairing'")

        library = native["library"]
        library_version = native["library_version"]
        pairing_source = native["pairing_source"]
        if not str(library or "").strip() or not str(library_version or "").strip() or not str(pairing_source or "").strip():
            library_ok = False
            _issue(f"NAO library/library_version/pairing_source metadata for {element} must be non-empty")

        cutoff = native["energy_cutoff_Ry"]
        radius = native["radius_cutoff_au"]
        lmax = native["lmax"]
        counts = native["radial_counts"]
        if not _finite_number(cutoff) or float(cutoff) <= 0.0:
            cutoff_ok = False
            _issue(f"NAO energy cutoff for {element} must be positive")
        elif ecut_ok and float(ecut) < float(cutoff):
            cutoff_ok = False
            _issue(f"parameters.ecutwfc_Ry is below the native NAO cutoff for {element}")
        if not _finite_number(radius) or float(radius) <= 0.0:
            radial_ok = False
            _issue(f"NAO radius cutoff for {element} must be positive")
        if isinstance(lmax, bool) or not isinstance(lmax, (int, np.integer)) or int(lmax) < 0:
            radial_ok = False
            _issue(f"NAO Lmax for {element} must be a non-negative integer")
        if not isinstance(counts, Mapping) or not counts:
            radial_ok = False
            _issue(f"NAO radial orbital counts for {element} are required")
        else:
            max_nonzero = -1
            angular = {"s": 0, "p": 1, "d": 2, "f": 3, "g": 4}
            for orbital, count in counts.items():
                label = str(orbital).lower()
                if label not in angular or isinstance(count, bool) or not isinstance(count, (int, np.integer)) or int(count) < 0:
                    radial_ok = False
                    _issue(f"NAO radial orbital count for {element} is invalid")
                elif int(count) > 0:
                    max_nonzero = max(max_nonzero, angular[label])
            if isinstance(lmax, (int, np.integer)) and max_nonzero > int(lmax):
                radial_ok = False
                _issue(f"NAO radial orbital counts exceed Lmax for {element}")

    names_ok = len(seen_names) == len(set(seen_names))
    _record_check("distinct_staged_orbital_filenames", names_ok, seen_names)
    if not names_ok:
        _issue("numerical orbitals must have distinct filenames when staged into one ABACUS directory")
    _record_check("native_element_identity", element_match_ok)
    _record_check("path_identity", path_identity_ok)
    _record_check("orbital_pseudopotential_binding", ids_binding_ok and pseudo_binding_ok)
    _record_check("declared_library_pairing", functional_ok and library_ok, {"source_kind": "declared_library_pairing"})
    _record_check("ecutwfc_vs_native_nao", cutoff_ok)
    _record_check("native_header_geometry", radial_ok)

    passed = not report["issues"]
    report["passed"] = passed
    report["input_qualified"] = passed
    return report


def _model_composition(model: Any) -> dict[str, int]:
    if not isinstance(model, ModelArtifacts):
        raise TypeError("model must be a ModelArtifacts instance")
    symbols = [str(value) for value in model.atoms.get_chemical_symbols()]
    return {element: symbols.count(element) for element in dict.fromkeys(symbols)}


def _check(report: dict[str, Any], name: str, passed: bool, detail: Any = None) -> None:
    report["checks"][name] = {"passed": bool(passed)}
    if detail is not None:
        report["checks"][name]["detail"] = detail


def _problem(report: dict[str, Any], message: str) -> None:
    report["issues"].append(message)


def _finite_number(value: Any) -> bool:
    try:
        return bool(math.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _explicit_integer(value: Any) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(value, bool)


def qualify_method_inputs(
    model: Any,
    config: Mapping[str, Any],
    headers: Mapping[str, Mapping[str, Any]],
    pseudopotential_files: Mapping[str, str | Path],
    orbital_headers: Mapping[str, Mapping[str, Any]] | None = None,
    orbital_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Return an auditable input-compatibility report for an ABACUS method.

    The function accumulates original, actionable domain problems instead of
    raising on a failed qualification.  Callers should use
    :func:`parse_upf_header` or :func:`read_upf_header` to create headers.
    ``input_qualified`` and ``passed`` always describe interface/input
    consistency only; ``production_qualification`` is always ``False``.
    """

    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    report: dict[str, Any] = {
        "schema": "mlcc.method-input-qualification.v1",
        "scope": "ABACUS 3.10.1 PW/LCAO input self-consistency and engine-interface compatibility; no precision or material qualification",
        "input_qualified": False,
        "passed": False,
        "scientific_qualification": False,
        "production_qualification": False,
        "issues": [],
        "checks": {},
        "electron_count": {},
    }

    composition = _model_composition(model)
    report["model"] = {"composition": composition, "elements": list(composition)}
    science = config.get("science")
    if not isinstance(science, Mapping):
        raise ValueError("method science must be a mapping")

    engine_ok = config.get("engine") == "abacus"
    version = config["engine_version"]
    version_ok = version == ABACUS_VERSION
    basis_type = config.get("basis_type")
    basis_ok = basis_type in ("pw", "lcao")
    _check(report, "engine", engine_ok, config["engine"])
    _check(report, "engine_version", version_ok, version)
    _check(report, "basis_type", basis_ok, basis_type)
    if not engine_ok:
        _problem(report, "method engine must be abacus")
    if not version_ok:
        _problem(report, f"method engine version must be {ABACUS_VERSION}")
    if not basis_ok:
        _problem(report, "method basis_type must be pw or lcao")

    # The top-level value is canonical.  Keep a nested science copy optional
    # for compatibility with hand-authored method records, but never let it
    # silently override the canonical value.
    top_charge_present = "net_charge" in config
    top_charge = config.get("net_charge")
    nested_charge_present = "net_charge" in science
    nested_charge = science.get("net_charge")
    charge_ok = top_charge_present and _explicit_integer(top_charge)
    if not top_charge_present:
        _problem(report, "net_charge must be explicitly declared at method-config top level")
    elif not charge_ok:
        _problem(report, "net_charge must be an explicit integer")
    if nested_charge_present:
        nested_ok = _explicit_integer(nested_charge)
        if not nested_ok:
            charge_ok = False
            _problem(report, "science.net_charge must be an explicit integer when supplied")
        elif top_charge_present and charge_ok and int(nested_charge) != int(top_charge):
            charge_ok = False
            _problem(report, "science.net_charge disagrees with top-level net_charge")
        elif not top_charge_present and int(nested_charge) != 0:
            charge_ok = False
            _problem(report, "top-level net_charge is required for a non-neutral method")
    canonical_charge = top_charge if top_charge_present else 0
    method_ok = True
    try:
        method = abacus_method_from_config(config)
    except (TypeError, ValueError) as exc:
        method_ok = False
        _problem(report, f"ABACUS method construction failed: {exc}")
        # Continue collecting the independent header/path checks with a
        # neutral placeholder only when construction itself was malformed.
        method_payload = dict(science)
        method_payload.pop("net_charge", None)
        method_payload["net_charge"] = canonical_charge
        try:
            method = AbacusMethod(**method_payload)
        except (TypeError, ValueError):
            method = None
    if method is not None:
        try:
            method.validate(config["element_order"])
        except ValueError as exc:
            method_ok = False
            _problem(report, f"ABACUS method validation failed: {exc}")
    _check(report, "method", method_ok)
    execution_ok = True
    try:
        AbacusExecution(**config["execution"]).validate(basis_type=basis_type)
    except ValueError as exc:
        execution_ok = False
        _problem(report, f"ABACUS execution validation failed: {exc}")
    _check(report, "execution", execution_ok)

    element_order = config["element_order"]
    elements_ok = isinstance(element_order, Sequence) and not isinstance(element_order, (str, bytes))
    configured_elements = [str(value) for value in element_order] if elements_ok else []
    elements_ok = elements_ok and len(configured_elements) == len(set(configured_elements))
    elements_ok = elements_ok and set(configured_elements) == set(composition)
    _check(report, "model_elements", elements_ok, {"model": list(composition), "configured": configured_elements})
    if not elements_ok:
        _problem(report, "element_order must contain each model element exactly once")

    header_keys = {str(key) for key in headers} if isinstance(headers, Mapping) else set()
    pseudo_keys = {str(key) for key in pseudopotential_files} if isinstance(pseudopotential_files, Mapping) else set()
    mappings_ok = header_keys == set(composition) and pseudo_keys == set(composition)
    _check(report, "header_and_pseudopotential_elements", mappings_ok, {"headers": sorted(header_keys), "pseudopotentials": sorted(pseudo_keys)})
    if not mappings_ok:
        _problem(report, "headers and pseudopotential_files must cover exactly the model elements")
    filenames = [Path(str(path)).name for path in pseudopotential_files.values()]
    unique_filenames = len(filenames) == len(set(filenames))
    _check(report, "distinct_staged_UPF_filenames", unique_filenames, filenames)
    if not unique_filenames:
        _problem(report, "pseudopotentials must have distinct filenames when staged into one ABACUS directory")

    parsed_headers: dict[str, dict[str, Any]] = {}
    all_pbe = True
    all_nc = True
    all_local_files = True
    for element in sorted(set(composition) | header_keys | pseudo_keys):
        header = headers.get(element) if isinstance(headers, Mapping) else None
        pseudo = pseudopotential_files.get(element) if isinstance(pseudopotential_files, Mapping) else None
        if not isinstance(header, Mapping):
            _problem(report, f"missing parsed UPF header for {element}")
            continue
        parsed_headers[element] = dict(header)
        if str(header.get("element", "")).strip() != element:
            _problem(report, f"UPF header element for {element} does not match the mapping key")
        if pseudo is None or str(header.get("source_path", "")) != str(pseudo):
            all_local_files = False
            _problem(report, f"UPF header source_path for {element} does not match pseudopotential_files")
        functional = str(header.get("functional", "")).strip()
        if normalize_functional(functional) != "PBE":
            all_pbe = False
            _problem(report, f"UPF {element} functional must be explicit PBE, got {functional!r}")
        if str(header.get("pseudo_type", "")).strip().upper() != "NC" or bool(header.get("is_ultrasoft", True)) or bool(header.get("is_paw", True)):
            all_nc = False
            _problem(report, f"UPF {element} must be NC with is_ultrasoft=false and is_paw=false")
    configured_functional = str(science.get("dft_functional", "")).strip()
    dft_ok = configured_functional.upper() == "PBE" and all_pbe
    _check(report, "pbe_functional", dft_ok, {"configured": configured_functional, "headers": {key: value.get("functional") for key, value in parsed_headers.items()}})
    _check(report, "header_path_identity", all_local_files, None)
    _check(report, "norm_conserving", all_nc, None)
    if configured_functional.upper() != "PBE":
        _problem(report, "method dft_functional must be explicit PBE")

    metadata = config.get("pseudopotential_metadata")
    metadata_keys = {str(key) for key in metadata} if isinstance(metadata, Mapping) else set()
    metadata_ok = isinstance(metadata, Mapping) and metadata_keys == set(composition)
    required_metadata_fields = (
        "element",
        "functional",
        "valence_electrons_per_atom",
        "relativity",
        "has_spin_orbit",
        "type",
    )
    if not metadata_ok:
        _problem(report, "pseudopotential_metadata must explicitly cover each model element")
    else:
        for element in composition:
            record = metadata.get(element)
            header = parsed_headers.get(element)
            if not isinstance(record, Mapping):
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata for {element} must be a mapping")
                continue
            missing_metadata = [name for name in required_metadata_fields if name not in record]
            if missing_metadata:
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata for {element} missing fields: {', '.join(missing_metadata)}")
                continue
            if not isinstance(header, Mapping):
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata for {element} has no parsed UPF header")
                continue
            metadata_element = str(record["element"]).strip()
            native_element = str(header.get("element", "")).strip()
            if metadata_element != element or metadata_element != native_element:
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata element for {element} does not match the native UPF header")
            metadata_functional = normalize_functional(str(record["functional"]).strip())
            native_functional = normalize_functional(str(header.get("functional", "")).strip())
            if metadata_functional != native_functional:
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata functional for {element} does not match the native UPF header")
            native_z_valence = header.get("z_valence")
            if (not _finite_number(record["valence_electrons_per_atom"])
                    or not _finite_number(native_z_valence)
                    or not math.isclose(float(record["valence_electrons_per_atom"]), float(native_z_valence), rel_tol=0.0, abs_tol=1e-8)):
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata valence_electrons_per_atom for {element} does not match the native UPF header")
            metadata_relativistic = str(record["relativity"]).strip().lower()
            native_relativistic = str(header.get("relativistic", "")).strip().lower()
            if native_relativistic not in {"scalar", "full"}:
                metadata_ok = False
                _problem(report, f"UPF {element} relativistic must be scalar or full, got {header.get('relativistic')!r}")
            if metadata_relativistic != native_relativistic:
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata relativity for {element} does not match the native UPF header")
            if not isinstance(record["has_spin_orbit"], bool) or record["has_spin_orbit"] is not header.get("has_so"):
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata has_spin_orbit for {element} does not match the native UPF header")
            metadata_type = str(record["type"]).strip().upper()
            if metadata_type not in {"NC", "ONCV_NC"}:
                metadata_ok = False
                _problem(report, f"pseudopotential_metadata type for {element} must be NC or ONCV_NC")
    _check(report, "pseudopotential_metadata", metadata_ok, metadata)

    nspin = science.get("nspin")
    nspin_ok = nspin in (1, 2)
    _check(report, "nspin", nspin_ok, nspin)
    if not nspin_ok:
        _problem(report, "nspin must be 1 or 2")
    moments = science.get("initial_moments_muB_by_element")
    moments_ok = isinstance(moments, Mapping) and set(str(key) for key in moments) == set(composition)
    if moments_ok:
        moments_ok = all(_finite_number(value) for value in moments.values())
    if moments_ok and nspin == 1:
        moments_ok = all(float(value) == 0.0 for value in moments.values())
    _check(report, "initial_moments", moments_ok, moments)
    if not moments_ok:
        _problem(report, "initial_moments_muB_by_element must cover elements with finite values; nspin=1 requires all zero")

    flags_ok = True
    for name in ("lspinorb", "noncolin"):
        if name not in science:
            flags_ok = False
            _problem(report, f"science.{name} must be explicitly false")
        elif science[name] is not False:
            flags_ok = False
            _problem(report, f"science.{name} must be explicitly false")
    _check(report, "spin_orbit_flags", flags_ok, {name: science.get(name) for name in ("lspinorb", "noncolin")})

    treatment = config.get("pseudopotential_treatment")
    treatment_ok = isinstance(treatment, Mapping) and set(str(key) for key in treatment) == set(composition)
    if not treatment_ok:
        _problem(report, "pseudopotential_treatment must explicitly cover each model element")
    else:
        for element in composition:
            selected = treatment[element]
            header = parsed_headers.get(element, {})
            if selected not in {"scalar", "abacus_3.10.1_average_j"}:
                treatment_ok = False
                _problem(report, f"unsupported pseudopotential_treatment for {element}: {selected!r}")
            elif selected == "scalar" and (
                    bool(header.get("has_so", True))
                    or str(header.get("relativistic", "")).strip().lower() != "scalar"):
                treatment_ok = False
                _problem(report, f"scalar treatment for {element} requires scalar-relativistic UPF with has_so=false")
            elif selected == "abacus_3.10.1_average_j":
                if not bool(header.get("has_so", False)) or str(header.get("relativistic", "")).strip().lower() != "full":
                    treatment_ok = False
                    _problem(report, f"average_j treatment for {element} requires full-relativistic UPF has_so=true")
                if nspin not in (1, 2):
                    treatment_ok = False
                    _problem(report, f"average_j treatment for {element} requires nspin=1 or 2")
                if science.get("lspinorb") is not False or science.get("noncolin") is not False:
                    treatment_ok = False
                    _problem(report, f"average_j treatment for {element} requires lspinorb=false and noncolin=false")
                reference = config.get("compatibility_reference")
                if not isinstance(reference, str) or not reference.strip():
                    treatment_ok = False
                    _problem(report, f"average_j treatment for {element} requires non-empty compatibility_reference")
    _check(report, "pseudopotential_treatment", treatment_ok, treatment)

    kpoints = config.get("kpoints")
    kpoints_ok = isinstance(kpoints, Sequence) and not isinstance(kpoints, (str, bytes)) and len(kpoints) == 3 and all(isinstance(value, (int, np.integer)) and not isinstance(value, bool) and int(value) > 0 for value in kpoints)
    _check(report, "kpoints", kpoints_ok, kpoints)
    if not kpoints_ok:
        _problem(report, "kpoints must contain exactly three positive integers")

    parameters = config.get("parameters")
    params_ok = True
    params_obj = None
    if not isinstance(parameters, Mapping):
        params_ok = False
        _problem(report, "parameters mapping is required")
    else:
        required_fields = {field.name for field in fields(AbacusParameters)}
        missing_params = sorted(required_fields - set(parameters))
        if missing_params:
            params_ok = False
            _problem(report, f"parameters missing fields: {', '.join(missing_params)}")
        else:
            try:
                params_obj = AbacusParameters(**{field.name: parameters[field.name] for field in fields(AbacusParameters)})
                stage = config.get("stage", "scf")
                if stage not in ("scf", "relax"):
                    raise ValueError("stage must be scf or relax")
                params_obj.validate(stage)
            except (TypeError, ValueError) as exc:
                params_ok = False
                _problem(report, f"parameters.validate failed: {exc}")
    _check(report, "parameters", params_ok, parameters)

    net_charge = canonical_charge
    _check(
        report,
        "net_charge",
        charge_ok,
        {
            "canonical": net_charge,
            "science_copy": nested_charge if nested_charge_present else None,
            "native_nelec": 0,
            "native_nelec_delta": -int(net_charge) if _explicit_integer(net_charge) else None,
        },
    )
    report["net_charge"] = net_charge
    report["nelec"] = 0
    report["nelec_delta"] = -int(net_charge) if _explicit_integer(net_charge) else None

    charged_contract_ok = True
    if _explicit_integer(net_charge) and int(net_charge) != 0:
        stage = config.get("stage", "scf")
        if stage != "scf":
            charged_contract_ok = False
            _problem(report, "charged method input qualification supports fixed-cell scf only")
        if method is None or method.nspin != 1:
            charged_contract_ok = False
            _problem(report, "charged method input qualification requires nspin=1")
        if method is None or method.occupations != "fixed":
            charged_contract_ok = False
            _problem(report, "charged method input qualification requires fixed occupations")
    _check(report, "charged_scf_contract", charged_contract_ok, {"stage": config.get("stage", "scf")})

    neutral_electrons = None
    if parsed_headers and all(element in parsed_headers for element in composition):
        neutral_electrons = float(sum(float(parsed_headers[element]["z_valence"]) * count for element, count in composition.items()))
    target_electrons = None
    if neutral_electrons is not None and _explicit_integer(net_charge):
        target_electrons = neutral_electrons - int(net_charge)
    report["electron_count"] = {
        "neutral_valence_electrons": neutral_electrons,
        "target_electrons": target_electrons,
        "net_charge": net_charge,
        "nelec": 0,
        "nelec_delta": report["nelec_delta"],
    }
    electron_ok = target_electrons is not None and math.isfinite(target_electrons) and target_electrons > 0.0
    if not electron_ok:
        _problem(report, "target electron count must be positive and finite")
    nbands = params_obj.nbands if params_obj is not None else None
    occupation = science.get("occupations")
    sigma = params_obj.smearing_sigma_Ry if params_obj is not None else None
    smearing_method = science.get("smearing_method")
    occupations_ok = occupation in ("fixed", "smearing")
    if occupation == "fixed":
        if smearing_method is not None or sigma is not None:
            occupations_ok = False
            _problem(report, "fixed occupations require smearing_method and smearing_sigma_Ry to be null")
        if nspin == 1 and electron_ok and nbands is not None:
            if not math.isclose(target_electrons / 2.0, round(target_electrons / 2.0), abs_tol=1e-8):
                occupations_ok = False
                _problem(report, "nspin=1 fixed occupations require an even target electron count")
            elif nbands < int(round(target_electrons / 2.0)):
                occupations_ok = False
                _problem(report, "nspin=1 fixed occupations require nbands >= target_electrons/2")
        if nspin == 2:
            occupations_ok = False
            _problem(report, "nspin=2 fixed occupations are unsupported until a spin-electron occupation definition is implemented")
    elif occupation == "smearing":
        if not smearing_method or sigma is None or sigma <= 0.0:
            occupations_ok = False
            _problem(report, "smearing occupations require smearing_method and positive smearing_sigma_Ry")
        if electron_ok and nbands is not None:
            minimum_empty = int(math.ceil(target_electrons / 2.0 - 1e-12))
            if nspin == 1 and nbands <= minimum_empty:
                occupations_ok = False
                _problem(report, "nspin=1 smearing requires nbands > ceil(neutral_electrons/2) for an empty band")
            if nspin == 2 and (2 * nbands < target_electrons or nbands <= minimum_empty):
                occupations_ok = False
                _problem(report, "nspin=2 smearing requires 2*nbands >= electrons and nbands > ceil(electrons/2)")
    else:
        _problem(report, "occupations must be fixed or smearing")
    _check(report, "occupations_and_band_capacity", occupations_ok, {"occupations": occupation, "nbands": nbands, "electron_count": target_electrons})
    report["electron_count"]["nbands"] = nbands
    report["electron_count"]["occupation_capacity_note"] = "For nspin=2 smearing, total capacity and a nominal empty band are checked; per-spin final occupations still require native-output review. Charged nspin=1 fixed inputs require a positive even target electron count."

    if basis_type == "lcao":
        orbital_config = dict(config)
        orbital_config["_pseudopotential_files"] = dict(pseudopotential_files)
        numerical_report = qualify_lcao_orbitals(orbital_config, orbital_headers, orbital_paths)
        report["checks"]["numerical_orbitals"] = numerical_report
        if not numerical_report["passed"]:
            report["issues"].extend(
                f"LCAO numerical orbitals: {issue}" for issue in numerical_report["issues"]
            )

    report["issues"] = list(dict.fromkeys(report["issues"]))
    passed = len(report["issues"]) == 0
    report["input_qualified"] = passed
    report["passed"] = passed
    report["production_qualification"] = False
    report["pseudopotentials"] = parsed_headers
    return report

