"""Explicit UPF header inspection and ABACUS method input qualification."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Mapping

from .method_inputs import normalize_functional, parse_nao_header, parse_upf_header, qualify_method_inputs
from .modeling import read_model_artifacts
from .tasks import utc_now


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def method_pseudopotentials(config, site):
    """Resolve only the explicitly selected resource IDs from the site."""
    return {
        element: site["abacus"]["pseudopotential_files"][config["pseudopotential_ids"][element]]
        for element in config["element_order"]
    }


def method_numerical_orbitals(config, site) -> dict[str, str]:
    """Resolve the explicitly selected LCAO orbital IDs from a site record."""

    if not isinstance(config, Mapping) or not isinstance(site, Mapping):
        raise TypeError("config and site must be mappings")
    element_order = config.get("element_order")
    if not isinstance(element_order, (list, tuple)) or not element_order:
        raise ValueError("element_order is required for numerical-orbital selection")
    ids = config.get("numerical_orbital_ids")
    if not isinstance(ids, Mapping):
        raise ValueError("LCAO methods require numerical_orbital_ids")
    abacus = site.get("abacus")
    resources = abacus.get("numerical_orbital_files") if isinstance(abacus, Mapping) else None
    if not isinstance(resources, Mapping):
        raise ValueError("site.abacus.numerical_orbital_files is required for LCAO methods")

    selected: dict[str, str] = {}
    for value in element_order:
        element = str(value)
        resource_id = ids.get(element)
        if resource_id in (None, ""):
            raise ValueError(f"numerical_orbital_ids is missing {element}")
        if resource_id not in resources:
            raise ValueError(f"site numerical_orbital_files is missing resource {resource_id!r} for {element}")
        path = resources[resource_id]
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"site numerical orbital resource {resource_id!r} for {element} has no path")
        selected[element] = path
    if set(str(key) for key in ids) != set(selected):
        raise ValueError("numerical_orbital_ids must cover element_order exactly")
    return selected


def inspect_site_upf_headers(method_path, site_path):
    """Read selected native headers from the configured site, without a solver."""
    config, site = _load(method_path), _load(site_path)
    selected = method_pseudopotentials(config, site)
    transport = site.get("ssh", {}).get("transport", "ssh")
    if transport == "local":
        raw = {}
        for element, filename in selected.items():
            source = Path(filename)
            text = source.read_text(encoding="utf-8")
            root = re.search(r"<UPF\b[^>]*>", text)
            header = re.search(r"<PP_HEADER\b[^>]*>", text, re.S)
            if root is None or header is None:
                raise ValueError(f"UPF {source} is missing a native UPF or PP_HEADER tag")
            raw[element] = {
                "source_path": str(source),
                "native_excerpt": root.group(0) + "\n" + header.group(0),
            }
        headers = {
            element: parse_upf_header(record["native_excerpt"], record["source_path"])
            for element, record in raw.items()
        }
        return {
            "schema": "mlcc.upf-header-snapshot.v1",
            "observed_at": utc_now(),
            "ssh_alias": site["ssh"]["alias"],
            "transport": "local",
            "method_set": config["method_set"],
            "headers": headers,
            "native_excerpts": raw,
            "command": ["local-read", *[str(path) for path in selected.values()]],
            "stderr": "",
            "numerical_jobs": [],
        }
    script = """import json, re, sys
from pathlib import Path
selected = json.loads(sys.argv[1])
records = {}
for element, filename in selected.items():
    text = Path(filename).read_text()
    root = re.search(r'<UPF\\b[^>]*>', text).group(0)
    header = re.search(r'<PP_HEADER\\b[^>]*>', text, re.S).group(0)
    records[element] = {'source_path': filename, 'native_excerpt': root + '\\n' + header}
print(json.dumps(records))
"""
    command = [site.get("ssh_program", "ssh"), site["ssh"]["alias"],
               shlex.join([site["python"]["remote_executable"], "-c", script, json.dumps(selected)])]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    raw = json.loads(result.stdout)
    headers = {element: parse_upf_header(record["native_excerpt"], record["source_path"])
               for element, record in raw.items()}
    return {"schema": "mlcc.upf-header-snapshot.v1", "observed_at": utc_now(),
            "ssh_alias": site["ssh"]["alias"], "method_set": config["method_set"],
            "headers": headers, "native_excerpts": raw,
            "command": command, "stderr": result.stderr, "numerical_jobs": []}


def inspect_site_nao_headers(method_path, site_path):
    """Read the selected native NAO headers directly from the selected site.

    The caller runs this function in the site's Slurm allocation.  It reads
    only the explicitly selected orbital and pairing-record paths; it neither
    scans a library nor opens a loopback SSH connection.
    """

    config, site = _load(method_path), _load(site_path)
    if config["basis_type"] != "lcao":
        raise ValueError("NAO header inspection requires an explicit LCAO method")
    library_id = config.get("numerical_orbital_library_id")
    if library_id is not None:
        if not isinstance(library_id, str) or not library_id.strip():
            raise ValueError("numerical_orbital_library_id must be a non-empty registered library ID")
        library_id = library_id.strip()
        abacus = site.get("abacus")
        libraries = abacus.get("numerical_orbital_libraries") if isinstance(abacus, Mapping) else None
        if not isinstance(libraries, Mapping) or library_id not in libraries:
            raise ValueError(f"site.abacus.numerical_orbital_libraries is missing {library_id!r}")
        library = libraries[library_id]
    else:
        library = config["numerical_orbital_library"]
    if not isinstance(library, Mapping):
        raise ValueError("numerical_orbital_library must be a mapping")
    required_library_fields = ("name", "version", "functional", "pairing_source", "pseudopotential_map")
    missing_library_fields = [name for name in required_library_fields if name not in library]
    if missing_library_fields:
        raise ValueError(
            "numerical_orbital_library is missing fields: "
            + ", ".join(missing_library_fields)
        )
    for name in required_library_fields:
        if not isinstance(library[name], str) or not library[name].strip():
            raise ValueError(f"numerical_orbital_library.{name} must be a non-empty path or value")

    declared_functional = library["functional"].strip()
    method_functional = str(config["science"]["dft_functional"]).strip()
    if normalize_functional(declared_functional) != "PBE" or method_functional.upper() != "PBE":
        raise ValueError("numerical-orbital library and science.dft_functional must both declare PBE")

    method_file = Path(method_path).resolve()

    def _selected_path(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else method_file.parent / path

    pairing_path = _selected_path(library["pairing_source"])
    pairing_text = pairing_path.read_text(encoding="utf-8")
    if not pairing_text.strip():
        raise ValueError("numerical-orbital pairing source must contain the selected library record")
    map_path = _selected_path(library["pseudopotential_map"])
    map_text = map_path.read_text(encoding="utf-8")
    pseudopotential_map = json.loads(map_text)
    if not isinstance(pseudopotential_map, Mapping):
        raise ValueError("numerical_orbital_library.pseudopotential_map must contain an element-to-filename mapping")

    element_order = config["element_order"]
    if not isinstance(element_order, (list, tuple)) or not element_order:
        raise ValueError("element_order is required for NAO header inspection")
    elements = [str(element) for element in element_order]
    if len(elements) != len(set(elements)):
        raise ValueError("element_order must not contain duplicate elements")
    if not set(elements).issubset(pseudopotential_map):
        raise ValueError("pseudopotential_map must contain every selected element")

    pseudopotentials = method_pseudopotentials(config, site)
    numerical_orbitals = method_numerical_orbitals(config, site)
    numerical_ids = config["numerical_orbital_ids"]
    pseudopotential_ids = config["pseudopotential_ids"]
    native_excerpts: dict[str, dict[str, Any]] = {}
    for element in elements:
        orbital_path = Path(numerical_orbitals[element])
        orbital_text = orbital_path.read_text(encoding="utf-8")
        summary_end = re.search(r"(?im)^[ \t]*SUMMARY[ \t]+END[ \t]*$", orbital_text)
        if summary_end is None:
            raise ValueError(f"NAO {orbital_path} header is missing SUMMARY END")
        native_excerpt = orbital_text[:summary_end.end()]
        parsed = parse_nao_header(native_excerpt, orbital_path)
        if str(parsed["element"]).strip() != element:
            raise ValueError(f"NAO header element for {element} does not match element_order")

        pseudopotential_path = Path(pseudopotentials[element])
        mapped_filename = pseudopotential_map[element]
        if not isinstance(mapped_filename, str) or not mapped_filename.strip():
            raise ValueError(f"pseudopotential_map has no filename for {element}")
        if mapped_filename.strip() != pseudopotential_path.name:
            raise ValueError(
                f"pseudopotential_map filename for {element} does not match the selected UPF"
            )

        native_excerpts[element] = {
            "source_path": str(orbital_path),
            "orbital_id": str(numerical_ids[element]),
            "native_excerpt": native_excerpt,
            "functional": declared_functional,
            "source_kind": "declared_library_pairing",
            "paired_pseudopotential_id": str(pseudopotential_ids[element]),
            "paired_pseudopotential_source": str(pseudopotential_path),
        }

    snapshot = {
        "schema": "mlcc.nao-header-snapshot.v1",
        "ssh_alias": site["ssh"]["alias"],
        "method_set": config["method_set"],
        "library": library["name"],
        "library_version": library["version"],
        "pairing_source": str(pairing_path),
        "observed_at": utc_now(),
        "native_excerpts": native_excerpts,
        "pairing_native_excerpt": pairing_text,
        "pseudopotential_map_path": str(map_path),
        "pseudopotential_map_text": map_text,
        "input_qualified": False,
        "scientific_qualification": False,
        "production_qualification": False,
        "inspection": "explicit_native_files_read_on_configured_site",
        "numerical_jobs": [],
    }
    if library_id is not None:
        snapshot["library_id"] = library_id
    return snapshot


def check_method_configuration(model, config, site, method_path):
    """Recompute qualification from the selected native header snapshot."""
    qualification = config["input_qualification"]
    reference = Path(qualification["header_snapshot"])
    if not reference.is_absolute():
        reference = Path(method_path).resolve().parent / reference
    snapshot = _load(reference)
    if snapshot["ssh_alias"] != site["ssh"]["alias"]:
        raise ValueError("UPF snapshot belongs to a different site")
    if snapshot["method_set"] != config["method_set"]:
        raise ValueError("UPF snapshot belongs to a different method_set")
    # Re-read native excerpts rather than accepting an editable passed flag.
    headers = {element: parse_upf_header(raw["native_excerpt"], raw["source_path"])
               for element, raw in snapshot["native_excerpts"].items()}
    pseudo_paths = method_pseudopotentials(config, site)
    orbital_headers: dict[str, dict[str, Any]] | None = None
    orbital_paths: dict[str, str] | None = None
    orbital_snapshot_path: Path | None = None
    if config.get("basis_type") == "lcao":
        orbital_snapshot_path = Path(qualification["orbital_header_snapshot"])
        if not orbital_snapshot_path.is_absolute():
            orbital_snapshot_path = Path(method_path).resolve().parent / orbital_snapshot_path
        orbital_snapshot = _load(orbital_snapshot_path)
        if orbital_snapshot["schema"] != "mlcc.nao-header-snapshot.v1":
            raise ValueError("NAO snapshot schema must be mlcc.nao-header-snapshot.v1")
        if orbital_snapshot["ssh_alias"] != site["ssh"]["alias"]:
            raise ValueError("NAO snapshot belongs to a different site")
        if orbital_snapshot["method_set"] != config["method_set"]:
            raise ValueError("NAO snapshot belongs to a different method_set")
        orbital_paths = method_numerical_orbitals(config, site)
        orbital_headers = {}
        for element, raw in orbital_snapshot["native_excerpts"].items():
            parsed = parse_nao_header(raw["native_excerpt"], raw["source_path"])
            parsed.update(
                orbital_id=raw["orbital_id"],
                functional=raw["functional"],
                source_kind=raw["source_kind"],
                paired_pseudopotential_id=raw["paired_pseudopotential_id"],
                paired_pseudopotential_source=raw["paired_pseudopotential_source"],
                pairing_source=orbital_snapshot["pairing_source"],
                library=orbital_snapshot["library"],
                library_version=orbital_snapshot["library_version"],
            )
            orbital_headers[str(element)] = parsed
    report = qualify_method_inputs(
        model,
        config,
        headers,
        pseudo_paths,
        orbital_headers=orbital_headers,
        orbital_paths=orbital_paths,
    )
    if config.get("basis_type") == "lcao":
        report["orbital_header_snapshot"] = str(orbital_snapshot_path.resolve())
    report.update(header_snapshot=str(reference.resolve()),
                  header_observed_at=snapshot["observed_at"], ssh_alias=snapshot["ssh_alias"],
                  model_id=model.model_id, model_version=model.version, method_set=config["method_set"])
    return report


def qualify_abacus_configuration(model_path, method_path, site_path):
    return check_method_configuration(read_model_artifacts(model_path), _load(method_path),
                                      _load(site_path), method_path)
