"""Pure-stdlib parsing of the native fields in an ABACUS UPF header.

The parser is intentionally independent from the scientific Python stack so a
site resource catalog can be inspected before a task imports NumPy or ASE.
Only values written by the UPF itself are returned.  In particular, f-electron
core treatment belongs to the catalog/provider evidence and is not inferred
from a filename.
"""

from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any


_UPF_ROOT_RE = re.compile(r"<UPF\b(?P<attrs>[^>]*)>", re.IGNORECASE)
_PP_HEADER_RE = re.compile(
    r"<PP_HEADER\b(?P<attrs>[^>]*?)(?:/>|>.*?</PP_HEADER\s*>)",
    re.IGNORECASE | re.DOTALL,
)
_XML_ATTR_RE = re.compile(
    r"(?P<name>[A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)

# Quantum ESPRESSO/UPF writes the PBE exchange-correlation functional either
# as ``PBE`` or as its component tokens.  The raw value remains in ``functional``.
_PBE_FUNCTIONAL_TOKENS = {"PBE", "SLA PW PBX PBC"}


def _attrs_from_text(text: str) -> dict[str, str]:
    return {match.group("name"): match.group("value") for match in _XML_ATTR_RE.finditer(text)}


def _bool_attribute(value: Any, *, name: str, source_path: str) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value).strip().upper()
    if token in {"T", "TRUE", "YES", "1"}:
        return True
    if token in {"F", "FALSE", "NO", "0"}:
        return False
    raise ValueError(f"UPF {source_path} has invalid {name} attribute {value!r}")


def _find_xml_attributes(text: str, tag: str) -> tuple[dict[str, str], str]:
    """Return attributes and the exact native tag fragment for ``tag``."""

    match = _UPF_ROOT_RE.search(text) if tag == "UPF" else _PP_HEADER_RE.search(text)
    if match is None:
        raise ValueError(f"UPF input is missing <{tag}>")
    raw = match.group(0)
    attrs = _attrs_from_text(match.group("attrs"))
    return attrs, raw


def normalize_functional(value: str) -> str:
    """Normalize only known native PBE spellings; preserve unknown values."""

    raw = " ".join(str(value).strip().split())
    return "PBE" if raw.upper() in _PBE_FUNCTIONAL_TOKENS else raw


def parse_upf_header(text: str, source_path: str | Path) -> dict[str, Any]:
    """Parse the native UPF 2.x root and ``PP_HEADER`` attributes.

    The raw ``PP_HEADER`` string is retained verbatim for auditability.  Only
    explicit UPF root and PP_HEADER tags are read; no functional, f-electron,
    or relativistic property is inferred when an attribute is absent.
    """

    if not isinstance(text, str) or not text.strip():
        raise ValueError("UPF input text must be non-empty")
    path_text = str(source_path)
    root_attrs, _ = _find_xml_attributes(text, "UPF")
    header_attrs, raw_header = _find_xml_attributes(text, "PP_HEADER")

    version = str(root_attrs.get("version", "")).strip()
    if not re.fullmatch(r"2(?:\.[0-9]+){1,2}", version):
        raise ValueError(f"UPF {path_text} requires a UPF 2.x root version, got {version!r}")

    required = (
        "element",
        "pseudo_type",
        "functional",
        "z_valence",
        "relativistic",
        "has_so",
        "is_ultrasoft",
        "is_paw",
    )
    missing = [name for name in required if name not in header_attrs]
    if missing:
        raise ValueError(f"UPF {path_text} PP_HEADER missing attributes: {', '.join(missing)}")
    try:
        z_valence = float(str(header_attrs["z_valence"]).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"UPF {path_text} has invalid z_valence") from exc
    if not math.isfinite(z_valence) or z_valence <= 0.0:
        raise ValueError(f"UPF {path_text} requires positive finite z_valence")

    functional = str(header_attrs["functional"]).strip()
    normalized_functional = normalize_functional(functional)
    return {
        "source_path": path_text,
        "upf_version": version,
        "raw_header": raw_header,
        "element": str(header_attrs["element"]).strip(),
        "functional": functional,
        "functional_normalized": normalized_functional,
        "functional_is_pbe": normalized_functional == "PBE",
        "z_valence": z_valence,
        "pseudo_type": str(header_attrs["pseudo_type"]).strip(),
        "relativistic": str(header_attrs["relativistic"]).strip(),
        "has_so": _bool_attribute(header_attrs["has_so"], name="has_so", source_path=path_text),
        "is_ultrasoft": _bool_attribute(header_attrs["is_ultrasoft"], name="is_ultrasoft", source_path=path_text),
        "is_paw": _bool_attribute(header_attrs["is_paw"], name="is_paw", source_path=path_text),
    }


def read_upf_header(path: str | Path) -> dict[str, Any]:
    """Read and parse one caller-authorized UPF header source file."""

    source = Path(path)
    return parse_upf_header(source.read_text(encoding="utf-8"), source)


__all__ = ["normalize_functional", "parse_upf_header", "read_upf_header"]
