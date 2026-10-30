"""Materialize the private ABACUS AIS381 catalog from its fixed layout."""
from __future__ import annotations
import argparse, copy, json, re, sys
from pathlib import Path
from typing import Any
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "mlcc-agent" / "src"))
from mlcc.abacus_library import PERIODIC_TABLE
from mlcc.method_inputs import parse_nao_header
from mlcc.upf_headers import normalize_functional, read_upf_header
DATASET_URL = "https://www.aissquare.com/datasets/detail?pageType=datasets&id=381"
DATASET_PROVIDER = "pxlxingliang"
DATASET_LICENSE = "CC BY 4.0"
UNDERLYING_LICENSE_NOTE = "SG15 source pseudopotentials retain CC BY-SA 4.0 and attribution requirements."
NAO_LIMITATION = "Efficiency NAOs are intended for occupied-state properties and are not qualified for high-precision unoccupied-state calculations."
NAO_PAIRING_STATEMENT = "readme.txt: NAOs MUST be used together with corresponding PSPs in apns-pseudopotentials-v1."
def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
def _symbol(value: Any) -> str | None:
    token = str(value).strip().lower()
    return next((item for item in PERIODIC_TABLE if item.lower() == token), None)
def _element_map(path: Path) -> dict[str, str]:
    value = _load(path)
    if not isinstance(value, dict) or len(value) != 83:
        raise ValueError("AIS381 element.json must be the verified 83-entry symbol-to-filename map")
    result = {}
    for raw_symbol, filename in value.items():
        symbol = _symbol(raw_symbol)
        if symbol is None or not isinstance(filename, str) or not filename.strip():
            raise ValueError("AIS381 element.json contains an invalid symbol or filename")
        result[symbol] = Path(filename).name
    if len(result) != 83 or len(set(result.values())) != 83:
        raise ValueError("AIS381 element.json must map 83 distinct element files")
    return result
def _cutoffs(path: Path) -> dict[str, float | None]:
    value = _load(path)
    if not isinstance(value, dict):
        raise ValueError("AIS381 ecutwfc.json must be a symbol-to-cutoff object")
    return {symbol: (None if value[raw] is None else float(value[raw]))
            for raw in value if (symbol := _symbol(raw)) is not None}
def _f_electrons(text: str, source: Path) -> dict[str, Any]:
    match = re.search(r"<PP_INPUTFILE\b[^>]*>(.*?)</PP_INPUTFILE\s*>", text, re.I | re.S)
    empty = lambda evidence: {"treatment": "unknown", "source": "native UPF PP_INPUTFILE", "evidence": evidence}
    if match is None:
        return empty("tag not present")
    lines = []
    for raw in match.group(1).splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith(("!", "//")):
            lines.append(line)
    if not lines:
        return empty("no rows")
    first = lines[0].split()
    # ONCVPSP's fixed-width header joins the symbol and Z for three-digit elements.
    reference_header = re.sub(r"^([A-Z][a-z]?)(?=\d)", r"\1 ", lines[0]).split()
    try:
        element, atomic_number, nc, nv = reference_header[0], float(reference_header[1]), int(reference_header[2]), int(reference_header[3])
    except (IndexError, TypeError, ValueError):
        return empty("invalid native header")
    rows = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            rows.append({"n": int(fields[0]), "l": int(fields[1]), "f": float(fields[2])})
        except (TypeError, ValueError):
            continue
        if len(rows) == nc + nv:
            break
    f_rows = [{**row, "configuration_row": index + 1, "treatment": "core" if index < nc else "valence"}
              for index, row in enumerate(rows) if row["l"] == 3 and row["n"] in (4, 5)]
    treatments = {row["treatment"] for row in f_rows}
    return {"treatment": next(iter(treatments)) if len(treatments) == 1 else "unknown",
            "source": "native UPF PP_INPUTFILE", "source_path": str(source.resolve()), "nc": nc, "nv": nv, "f_rows": f_rows,
            "evidence": {"header": first, "element": element, "atomic_number": atomic_number,
                         "nc": nc, "nv": nv, "f_rows": f_rows}}
def _pp(path: Path, symbol: str, resource_id: str, family: str, source_url: str | None,
        provider: str, license_value: str, basis_support: list[str] | None = None) -> dict[str, Any]:
    full_path = path.resolve()
    issues: list[str] = []
    try:
        header = read_upf_header(full_path)
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        header, text = None, ""
        issues.append(f"native UPF header could not be parsed: {exc}")
    if header is not None:
        header = {**header, "source_path": str(full_path)}
        if str(header.get("element", "")).strip() != symbol:
            issues.append("native element does not match element.json")
        if normalize_functional(str(header.get("functional", ""))) != "PBE":
            issues.append(f"native functional is not PBE: {header.get('functional')!r}")
        if str(header.get("pseudo_type", "")).upper() != "NC" or header.get("is_ultrasoft") or header.get("is_paw"):
            issues.append("native UPF is not norm-conserving")
    record = {"id": resource_id, "path": str(full_path), "filename": full_path.name,
              "source_url": source_url, "provider": provider, "license": license_value,
              "family": family, "version": "AIS381" if family == "AIS381" else "SUPPLEMENT",
              "header": header, "f_electrons": _f_electrons(text, full_path),
              "input_compatible": header is not None and not issues,
              "scientific_qualification": False, "issues": issues}
    if basis_support is not None:
        record["basis_support"] = basis_support
        issues.append("PW-only supplemental resource has no AIS381 numerical-orbital pairing")
    return record
def _orbital(path: Path, element_map: dict[str, str], pp_root: Path, readme: Path) -> tuple[str, dict[str, Any]] | None:
    full_path = path.resolve()
    try:
        text = full_path.read_text(encoding="utf-8")
        summary_end = re.search(r"(?im)^[ \t]*SUMMARY[ \t]+END[ \t]*$", text)
        if summary_end is None:
            raise ValueError(f"NAO {path} is missing SUMMARY END")
        header = parse_nao_header(text[:summary_end.end()], full_path)
    except (OSError, ValueError):
        return None
    symbol = _symbol(header.get("element"))
    if symbol is None:
        return None
    issues = []
    mapped = element_map.get(symbol)
    if mapped is None or not (pp_root / mapped).is_file():
        issues.append("element.json has no installed matching pseudopotential")
    record = {"id": f"AIS381_{symbol}_NAO_{path.stem}", "path": str(full_path), "filename": path.name,
              "source_url": DATASET_URL, "provider": DATASET_PROVIDER, "license": DATASET_LICENSE,
              "library": "AIS381 orbitals-efficiency", "version": "AIS381", "header": header,
              "library_id": "AIS381_efficiency_v1",
              "pairing_pseudopotential_id": f"AIS381_{symbol}_PBE" if not issues else None,
              "pairing_source": str(readme.resolve()), "pseudopotential_map": str((pp_root / "element.json").resolve()),
              "pairing_evidence": {"statement": NAO_PAIRING_STATEMENT, "element_json_filename": mapped},
              "usage_limitations": NAO_LIMITATION, "issues": issues}
    return symbol, record
def _supplement(root: Path) -> list[tuple[str, Path, str | None, str, str]]:
    result = []
    for resource in _load((root / "manifest.json").resolve()).get("resources", []):
        if not isinstance(resource, dict):
            continue
        for item in resource.get("files", []):
            if not isinstance(item, dict) or not str(item.get("local_path", "")).lower().endswith(".upf"):
                continue
            path = Path(item["local_path"])
            path = (root / path).resolve() if not path.is_absolute() else path.resolve()
            header = read_upf_header(path)
            symbol = _symbol(header.get("element"))
            if symbol and symbol != "Og":
                result.append((symbol, path, item.get("url"), item.get("provider", resource.get("provider", resource.get("source", "SUPPLEMENT"))),
                               item.get("license", resource.get("license", "not_declared"))))
    return result
def build(ais_root: Path, site_path: Path, output: Path, supplement_root: Path | None = None) -> tuple[Path, Path, Path]:
    ais_root, site_path, output = ais_root.resolve(), site_path.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"output must be a new directory: {output}")
    pp_root, orb_root = ais_root / "apns-pseudopotentials-v1", ais_root / "apns-orbitals-efficiency-v1"
    element_path, cutoff_path = pp_root / "element.json", pp_root / "ecutwfc.json"
    pp_readme, orb_readme = pp_root / "readme.txt", orb_root / "readme.txt"
    element_map, cutoff_map = _element_map(element_path), _cutoffs(cutoff_path)
    pp_files = {path.name: path.resolve() for path in pp_root.iterdir() if path.suffix.lower() == ".upf"}
    pp_records: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in PERIODIC_TABLE}
    orbital_records: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in PERIODIC_TABLE}
    for symbol, filename in element_map.items():
        if filename in pp_files:
            pp_records[symbol].append(_pp(pp_files[filename], symbol, f"AIS381_{symbol}_PBE", "AIS381", DATASET_URL, DATASET_PROVIDER, DATASET_LICENSE))
    ais_count = sum(map(len, pp_records.values()))
    for path in sorted(orb_root.iterdir()):
        if path.suffix.lower() != ".orb":
            continue
        parsed = _orbital(path, element_map, pp_root, orb_readme)
        if parsed is not None:
            symbol, record = parsed
            orbital_records[symbol].append(record)
    supplement_count = 0
    if supplement_root is not None:
        for symbol, path, url, provider, license_value in _supplement(supplement_root.resolve()):
            if any(item["input_compatible"] for item in pp_records[symbol]):
                continue
            pp_records[symbol].append(_pp(path, symbol, f"SUPPLEMENT_{symbol}_PBE_{path.stem}", "SUPPLEMENT", url, provider, license_value, ["pw"]))
            supplement_count += 1
    elements = []
    for number, symbol in enumerate(PERIODIC_TABLE, 1):
        resources = pp_records[symbol]
        preferred = next((item for item in resources if item["input_compatible"]), None)
        elements.append({"symbol": symbol, "atomic_number": number, "status": "available" if preferred else ("unqualified" if resources else "missing"),
                         "preferred_pseudopotential_id": preferred["id"] if preferred else None, "pseudopotentials": resources,
                         "orbitals": orbital_records[symbol], "recommended_ecutwfc_Ry": cutoff_map.get(symbol),
                         "scientific_qualification": False, "issues": [] if preferred else ["no input-compatible PBE/NC resource"]})
    catalog = {"schema": "mlcc.abacus-library.v1", "version": "20261030-v001", "engine": "abacus", "default_production_engine": "abacus",
               "sources": [{"dataset": "AIS381", "source_url": DATASET_URL, "provider": DATASET_PROVIDER, "license": DATASET_LICENSE,
                            "underlying_license_note": UNDERLYING_LICENSE_NOTE, "pseudopotential_readme": str(pp_readme.resolve()),
                            "element_map": str(element_path.resolve()), "cutoff_map": str(cutoff_path.resolve())},
                           {"dataset": "AIS381", "orbital_readme": str(orb_readme.resolve()), "source_url": DATASET_URL,
                            "provider": DATASET_PROVIDER, "license": DATASET_LICENSE, "usage_limitations": NAO_LIMITATION}],
               "elements": elements, "scientific_qualification": False}
    site = copy.deepcopy(_load(site_path))
    abacus = site.setdefault("abacus", {})
    pp_mapping, orb_mapping = dict(abacus.get("pseudopotential_files", {})), dict(abacus.get("numerical_orbital_files", {}))
    for element in elements:
        for resource in element["pseudopotentials"]:
            pp_mapping[resource["id"]] = resource["path"]
        for orbital in element["orbitals"]:
            orb_mapping[orbital["id"]] = orbital["path"]
    abacus["pseudopotential_files"], abacus["numerical_orbital_files"] = pp_mapping, orb_mapping
    libraries = dict(abacus.get("numerical_orbital_libraries", {}))
    libraries["AIS381_efficiency_v1"] = {
        "name": "AIS381 orbitals-efficiency", "version": "AIS381", "functional": "PBE",
        "pairing_source": str(orb_readme.resolve()), "pseudopotential_map": str(element_path.resolve()),
    }
    abacus["numerical_orbital_libraries"] = libraries
    abacus["pseudopotential_directory"], abacus["orbital_directory"] = str(pp_root), str(orb_root)
    abacus.pop("capabilities", None)
    abacus.pop("production_migration_complete", None)
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog_path, site_output, report_path = output / "abacus-library.json", output / "site.updated.json", output / "report.json"
    abacus["resource_catalog"] = str(catalog_path.resolve())
    abacus["native_resource_evidence"] = {"pseudopotential_directory": str(pp_root), "orbital_directory": str(orb_root),
                                           "element_map": str(element_path.resolve()), "scientific_qualification": False}
    site["default_production_engine"] = "abacus"
    report = {"elements": len(elements), "available": sum(item["status"] == "available" for item in elements),
              "missing": sum(item["status"] == "missing" for item in elements), "unqualified": sum(item["status"] == "unqualified" for item in elements),
              "ais381_pseudopotentials": ais_count, "ais381_orbitals": sum(map(len, orbital_records.values())),
              "supplement_pseudopotentials": supplement_count, "scientific_qualification": False, "no_calculation": True}
    output.mkdir()
    for path, value in ((catalog_path, catalog), (site_output, site), (report_path, report)):
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return catalog_path, site_output, report_path
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ais-root", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--supplement-root", type=Path)
    args = parser.parse_args()
    catalog, site, report = build(args.ais_root, args.site, args.output, args.supplement_root)
    print(json.dumps({"catalog": str(catalog), "site": str(site), "report": str(report)}, ensure_ascii=False))
    return 0
if __name__ == "__main__": raise SystemExit(main())
