"""Read-only summaries for a site-managed ABACUS resource catalog.

The catalog is deliberately kept outside the portable bundle.  This module
only reads the private JSON pointer in a site configuration and returns
metadata; it never imports the scientific Python stack, opens a remote
connection, or stages a resource.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


PERIODIC_TABLE = (
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
    "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
)
_ATOMIC_NUMBER = {symbol: number for number, symbol in enumerate(PERIODIC_TABLE, start=1)}
_PRIVATE_METADATA_KEYS = {
    "path",
    "source_path",
    "native_excerpt",
    "native_excerpts",
    "remote_path",
    "local_path",
    "absolute_path",
    "pairing_source",
    "pseudopotential_map",
    "pseudopotential_readme",
    "orbital_readme",
    "element_map",
    "cutoff_map",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"ABACUS resource file {path} must contain a JSON object")
    return value


def _catalog_path(site_path: Path) -> Path:
    site = _read_json(site_path)
    abacus = site.get("abacus")
    if not isinstance(abacus, Mapping):
        raise ValueError("site configuration is missing abacus")
    pointer = abacus.get("resource_catalog")
    if isinstance(pointer, Mapping):
        pointer = pointer.get("path")
    if not isinstance(pointer, str) or not pointer.strip():
        raise ValueError("site.abacus.resource_catalog must point to a JSON file")
    catalog = Path(pointer)
    return catalog if catalog.is_absolute() else site_path.parent / catalog


def _load_catalog(site_path: str | Path) -> dict[str, Any]:
    site = Path(site_path)
    catalog_path = _catalog_path(site)
    catalog = _read_json(catalog_path)
    if catalog.get("schema") != "mlcc.abacus-library.v1":
        raise ValueError("ABACUS resource catalog schema must be mlcc.abacus-library.v1")
    if not isinstance(catalog.get("version"), str) or not catalog["version"].strip():
        raise ValueError("ABACUS resource catalog version is required")
    records = catalog.get("elements")
    if not isinstance(records, list) or len(records) != len(PERIODIC_TABLE):
        raise ValueError("ABACUS resource catalog must contain exactly 118 element records")

    for expected_number, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise ValueError(f"ABACUS resource catalog element {expected_number} is not an object")
        if record.get("atomic_number") != expected_number or record.get("symbol") != PERIODIC_TABLE[expected_number - 1]:
            raise ValueError("ABACUS resource catalog elements must be sorted in atomic-number order")
        if not isinstance(record.get("status"), str) or not record["status"].strip():
            raise ValueError(f"ABACUS resource catalog element {expected_number} has no status")
        for key in ("pseudopotentials", "orbitals", "issues"):
            if not isinstance(record.get(key, []), list):
                raise ValueError(f"ABACUS resource catalog element {expected_number} {key} must be a list")
    return catalog


def _normalize_elements(elements: Iterable[str | int]) -> list[str]:
    normalized: list[str] = []
    for value in elements:
        if isinstance(value, int) and not isinstance(value, bool):
            if value < 1 or value > len(PERIODIC_TABLE):
                raise ValueError(f"unknown atomic number {value}")
            symbol = PERIODIC_TABLE[value - 1]
        else:
            token = str(value).strip()
            symbol = next((candidate for candidate in PERIODIC_TABLE if candidate.lower() == token.lower()), None)
            if symbol is None:
                raise ValueError(f"unknown element symbol {value!r}")
        if symbol in normalized:
            raise ValueError(f"duplicate element {symbol}")
        normalized.append(symbol)
    return normalized


def _has_installed_compatible_pseudopotential(record: Mapping[str, Any]) -> bool:
    for pseudopotential in record.get("pseudopotentials", []):
        if not isinstance(pseudopotential, Mapping):
            continue
        path = pseudopotential.get("path")
        if isinstance(path, str) and path.strip() and pseudopotential.get("input_compatible") is True:
            return True
    return False


def _effective_status(record: Mapping[str, Any]) -> str:
    declared = str(record["status"])
    if declared != "available":
        return declared
    if _has_installed_compatible_pseudopotential(record):
        return "available"
    return "missing" if not record.get("pseudopotentials") else "unqualified"


def _public_metadata(value: Any, key: str | None = None) -> Any:
    """Copy catalog metadata while removing private filesystem references."""

    if key in _PRIVATE_METADATA_KEYS or (key is not None and key.endswith("_path")):
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_name = str(child_key)
            if child_name in _PRIVATE_METADATA_KEYS or child_name.endswith("_path"):
                continue
            result[child_name] = _public_metadata(child_value, child_name)
        return result
    if isinstance(value, list):
        return [_public_metadata(item) for item in value]
    return copy.deepcopy(value)


def _summary(record: Mapping[str, Any]) -> dict[str, Any]:
    pseudopotentials = record.get("pseudopotentials", [])
    orbitals = record.get("orbitals", [])
    return {
        "symbol": record["symbol"],
        "atomic_number": record["atomic_number"],
        "status": _effective_status(record),
        "pseudopotential_count": len(pseudopotentials),
        "orbital_count": len(orbitals),
        "resource_count": len(pseudopotentials) + len(orbitals),
        "preferred_pseudopotential_id": record.get("preferred_pseudopotential_id"),
    }


def _selected_record(record: Mapping[str, Any]) -> dict[str, Any]:
    result = _public_metadata(record)
    result["status"] = _effective_status(record)
    if result["status"] != record["status"]:
        result["catalog_status"] = record["status"]
        result.setdefault("issues", []).append("declared available status has no installed input-compatible pseudopotential")
    return result


def describe_abacus_resources(
    site_path: str | Path,
    elements: Iterable[str | int] | None = None,
) -> dict[str, Any]:
    """Describe site-managed ABACUS resources without exposing private paths.

    Without ``elements`` the result contains one compact summary per canonical
    periodic-table element.  With ``elements`` it additionally contains the
    selected catalog records, retaining native scientific metadata and provider
    f-electron evidence while removing filesystem paths and native path-bearing
    excerpts.  ``available`` means installed and input-compatible only; it does
    not imply material or scientific qualification.
    """

    catalog = _load_catalog(site_path)
    records = {record["symbol"]: record for record in catalog["elements"]}
    result: dict[str, Any] = {
        "schema": "mlcc.abacus-resource-summary.v1",
        "library_schema": catalog["schema"],
        "version": catalog["version"],
        "sources": _public_metadata(catalog.get("sources", [])),
        "default_engine": "abacus",
        "elements": [_summary(record) for record in catalog["elements"]],
    }
    if elements is not None:
        selected_symbols = _normalize_elements(elements)
        result["selected"] = [_selected_record(records[symbol]) for symbol in selected_symbols]
    return result


__all__ = ["PERIODIC_TABLE", "describe_abacus_resources"]
