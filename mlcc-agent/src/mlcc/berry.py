"""Strict native ABACUS 3.10.1 Berry-phase output parsing.

The parser consumes the task protocol together with the files written by the
ABACUS run.  A task-side result record is deliberately not a source of
polarization values.  The returned observation is not branch-unwrapped and is
unqualified:
the parser does not choose a reference branch, infer spontaneous polarization,
or grant a dielectric/material qualification.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np

from .abacus import ABACUS_VERSION, BOHR_PER_ANGSTROM, _read_stru
from .modeling import ModelArtifacts


BERRY_GPU_IMPLEMENTATION_ID = "mlcc-abacus-3.10.1-berry-gpu-v001"
BERRY_GPU_SCOPE = "single_mpi_non_soc_nspin1"

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_VERSION_RE = re.compile(
    r"\bABACUS(?:\s+version)?\s+v?(?P<version>\d+\.\d+\.\d+)\b",
    re.IGNORECASE,
)
_PHASE_RE = re.compile(
    r"^\s*(?P<label>The Ionic Phase|Electronic Phase)\s*:\s*(?P<value>"
    + _NUMBER
    + r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DIRECTION_RE = re.compile(
    r"^\s*The calculated polarization direction is in R(?P<gdir>[123]) direction\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_P_ROW_RE = re.compile(
    r"^\s*P\s*=\s*(?P<value>"
    + _NUMBER
    + r")\s*\(\s*mod\s+(?P<mod>"
    + _NUMBER
    + r")\s*\)\s*\(\s*(?P<x>"
    + _NUMBER
    + r")\s*,\s*(?P<y>"
    + _NUMBER
    + r")\s*,\s*(?P<z>"
    + _NUMBER
    + r")\s*\)\s*(?P<unit>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DIRECT_ROW_RE = re.compile(
    r"^\s*(?P<label>taud_[A-Za-z]+\d+)\s+(?P<x>"
    + _NUMBER
    + r")\s+(?P<y>"
    + _NUMBER
    + r")\s+(?P<z>"
    + _NUMBER
    + r")\s+(?P<mag>"
    + _NUMBER
    + r")\s+",
    re.MULTILINE,
)
_PP_BLOCK_RE = re.compile(
    r"Read\s+in\s+pseudopotential\s+file\s+is\s+(?P<name>\S+)"
    r"(?P<body>.*?)(?=Read\s+in\s+pseudopotential\s+file\s+is\s+|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_VALENCE_RE = re.compile(r"valence\s+electrons\s*=\s*(?P<value>" + _NUMBER + r")", re.IGNORECASE)
_FUNCTIONAL_RE = re.compile(
    r"exchange[- ]correlation\s+functional\s*=\s*(?P<value>\S+)", re.IGNORECASE
)
_CHARGE_READ_RE = re.compile(
    r"^\s*Read\s+in\s+the\s+charge\s+density\s*:\s*(?P<path>\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# ABACUS 3.10.1 source/module_io/berryphase.cpp uses these source constants
# for the native unit conversion.  They intentionally match the release's
# printed values instead of replacing them with a newer CODATA conversion.
_ABACUS_BERRY_CHARGE = 1.60097e-19
_ABACUS_BERRY_BOHR_M = 5.29177e-11
_E_PER_BOHR2_TO_C_PER_M2 = _ABACUS_BERRY_CHARGE / (_ABACUS_BERRY_BOHR_M**2)


def _number(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].split("//", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _read_input(path: Path, *, allow_blank_values: bool = False) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _clean_lines(path.read_text(encoding="utf-8")):
        if line.upper() == "INPUT_PARAMETERS":
            continue
        tokens = line.split()
        if len(tokens) < 2:
            if allow_blank_values and len(tokens) == 1:
                key = tokens[0].lower()
                if key in values:
                    raise ValueError(f"ABACUS INPUT repeats keyword: {key}")
                values[key] = ""
                continue
            raise ValueError(f"ABACUS INPUT line is not a key/value pair: {line!r}")
        key = tokens[0].lower()
        if key in values:
            raise ValueError(f"ABACUS INPUT repeats keyword: {key}")
        values[key] = " ".join(tokens[1:])
    return values


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Berry task is missing required {label}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Berry {label} must contain a JSON object")
    return value


def _required(mapping: Mapping[str, Any], key: str, label: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise ValueError(f"Berry {label} is missing required field {key!r}")
    return mapping[key]


def _bool_input(value: str, *, key: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"ABACUS INPUT {key} must be 0/1 or true/false: {value!r}")


def _int_input(values: Mapping[str, str], key: str) -> int:
    raw = values.get(key)
    if raw is None:
        raise ValueError(f"ABACUS INPUT is missing required keyword {key!r}")
    try:
        parsed = int(raw.split()[0])
    except (TypeError, ValueError) as error:
        raise ValueError(f"ABACUS INPUT {key} must be an integer: {raw!r}") from error
    return parsed


def _float_input(values: Mapping[str, str], key: str) -> float:
    raw = values.get(key)
    if raw is None:
        raise ValueError(f"ABACUS INPUT is missing required keyword {key!r}")
    try:
        parsed = _number(raw.split()[0])
    except (TypeError, ValueError) as error:
        raise ValueError(f"ABACUS INPUT {key} must be numeric: {raw!r}") from error
    if not math.isfinite(parsed):
        raise ValueError(f"ABACUS INPUT {key} must be finite")
    return parsed


def _expected_vector(value: Any, *, key: str, integer: bool) -> tuple[Any, Any, Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"Berry expected {key} must contain three values")
    output: list[Any] = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError(f"Berry expected {key} must not contain booleans")
        try:
            converted = int(item) if integer else float(item)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Berry expected {key} contains a non-numeric value") from error
        if integer and converted != item:
            raise ValueError(f"Berry expected {key} must contain integers")
        if not math.isfinite(float(converted)):
            raise ValueError(f"Berry expected {key} must contain finite values")
        output.append(converted)
    return tuple(output)  # type: ignore[return-value]


def _read_kpt(path: Path) -> tuple[tuple[int, int, int], tuple[float, float, float]]:
    lines = _clean_lines(path.read_text(encoding="utf-8"))
    if len(lines) != 4 or lines[0].upper() != "K_POINTS":
        raise ValueError("ABACUS KPT must be explicit K_POINTS/0/Gamma/mesh input")
    if lines[1] != "0" or lines[2].lower() != "gamma":
        raise ValueError("ABACUS KPT must use an explicit Gamma mesh")
    tokens = lines[3].split()
    if len(tokens) != 6:
        raise ValueError("ABACUS KPT Gamma mesh must have three mesh and three shift values")
    try:
        mesh = tuple(int(token) for token in tokens[:3])
        shift = tuple(_number(token) for token in tokens[3:])
    except ValueError as error:
        raise ValueError("ABACUS KPT mesh and shifts must be numeric") from error
    if any(value <= 0 for value in mesh):
        raise ValueError("ABACUS KPT mesh values must be positive")
    if not all(math.isfinite(value) for value in shift):
        raise ValueError("ABACUS KPT shifts must be finite")
    return mesh, shift


def _reference_fields(method: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    """Read the one current Berry reference contract, without aliases."""

    berry = method.get("berry")
    if not isinstance(berry, Mapping):
        raise ValueError("Berry method.json requires a berry object")
    reference_id = berry.get("source_reference_task_id")
    if not isinstance(reference_id, str) or not reference_id:
        raise ValueError("Berry method.json berry.source_reference_task_id is required")
    charge = berry.get("charge_density")
    if not isinstance(charge, Mapping):
        raise ValueError("Berry method.json berry.charge_density is required")
    files = charge.get("files")
    source_paths = charge.get("source_paths")
    if (
        not isinstance(files, list)
        or not files
        or any(not isinstance(value, str) or not value for value in files)
    ):
        raise ValueError("Berry method.json berry.charge_density.files is required")
    if (
        not isinstance(source_paths, list)
        or len(source_paths) != len(files)
        or any(not isinstance(value, str) or not value for value in source_paths)
        or [Path(value).name for value in source_paths] != files
    ):
        raise ValueError("Berry method.json berry.charge_density.source_paths must name the declared files")
    if charge.get("directory") != "task_root":
        raise ValueError("Berry method.json berry.charge_density.directory must be task_root")
    if charge.get("source_task_id") != reference_id:
        raise ValueError("Berry charge_density.source_task_id differs from source_reference_task_id")
    if any(Path(value).name != value or Path(value).is_absolute() for value in files):
        raise ValueError("Berry charge_density.files must be task-root filenames")
    return reference_id, charge


def _read_stru_contract(path: Path) -> dict[str, Any]:
    """Read the PP names, initial moments, and direct rows from one STRU."""

    lines = _clean_lines(path.read_text(encoding="utf-8"))
    try:
        species_start = lines.index("ATOMIC_SPECIES") + 1
        lattice_start = lines.index("LATTICE_CONSTANT")
        positions_start = lines.index("ATOMIC_POSITIONS") + 1
    except ValueError as error:
        raise ValueError(f"ABACUS STRU is missing a required section: {path}") from error
    species: list[str] = []
    pseudo: dict[str, str] = {}
    species_end = lines.index("NUMERICAL_ORBITAL") if "NUMERICAL_ORBITAL" in lines else lattice_start
    for line in lines[species_start:species_end]:
        tokens = line.split()
        if len(tokens) < 3:
            raise ValueError(f"ABACUS STRU has an invalid ATOMIC_SPECIES row: {line!r}")
        element = str(tokens[0])
        if element in pseudo:
            raise ValueError(f"ABACUS STRU repeats species {element}")
        species.append(element)
        pseudo[element] = Path(tokens[2]).name
    mode = lines[positions_start]
    if mode.lower() != "direct":
        raise ValueError(f"ABACUS Berry STRU must use Direct coordinates: {mode}")
    records: list[dict[str, Any]] = []
    moments: dict[str, float] = {}
    cursor = positions_start + 1
    while cursor < len(lines):
        element = lines[cursor].split()[0]
        if element not in pseudo:
            raise ValueError(f"ABACUS STRU contains an unlisted element block: {element}")
        if cursor + 2 >= len(lines):
            raise ValueError(f"ABACUS STRU has an incomplete {element} block")
        try:
            moment = _number(lines[cursor + 1].split()[0])
            count = int(lines[cursor + 2].split()[0])
        except (TypeError, ValueError) as error:
            raise ValueError(f"ABACUS STRU has an invalid {element} block") from error
        if not math.isfinite(moment) or count < 0:
            raise ValueError(f"ABACUS STRU {element} moment/count is invalid")
        if element in moments:
            raise ValueError(f"ABACUS STRU repeats ATOMIC_POSITIONS block for {element}")
        moments[element] = moment
        cursor += 3
        for _ in range(count):
            if cursor >= len(lines):
                raise ValueError(f"ABACUS STRU {element} block is truncated")
            tokens = lines[cursor].split()
            if len(tokens) < 3:
                raise ValueError(f"ABACUS STRU has an invalid direct coordinate row: {lines[cursor]!r}")
            try:
                frac = [_number(token) for token in tokens[:3]]
            except ValueError as error:
                raise ValueError(f"ABACUS STRU has a non-numeric coordinate row: {lines[cursor]!r}") from error
            records.append({"element": element, "frac": frac, "moment": moment})
            cursor += 1
    if set(moments) != set(species):
        raise ValueError("ABACUS STRU ATOMIC_POSITIONS blocks do not match ATOMIC_SPECIES")
    return {"species": species, "pseudo": pseudo, "moments": moments, "records": records}


def _method_pseudopotentials(method: Mapping[str, Any], species: Sequence[str]) -> dict[str, str]:
    records = method.get("pseudopotentials")
    if not isinstance(records, Mapping):
        raise ValueError("Berry method.json pseudopotentials are required")
    output: dict[str, str] = {}
    for element in species:
        record = records.get(element)
        if not isinstance(record, Mapping) or not isinstance(record.get("filename"), str) or not record["filename"]:
            raise ValueError(f"Berry method.json pseudopotential filename is missing for {element}")
        output[element] = Path(record["filename"]).name
    if set(records) != set(species):
        raise ValueError("Berry method.json pseudopotentials do not match STRU species")
    return output


def _periodic_fractional_close(actual: Sequence[float], expected: Sequence[float], *, atol: float) -> bool:
    """Compare direct coordinates after removing whole-cell translations."""

    delta = np.asarray(actual, dtype=float) - np.asarray(expected, dtype=float)
    delta -= np.rint(delta)
    return bool(np.all(np.abs(delta) <= atol))


def _validate_model_and_stru(
    directory: Path,
    source_model: ModelArtifacts,
    method: Mapping[str, Any],
) -> tuple[dict[str, Any], Any, Path, dict[str, Any]]:
    if not isinstance(source_model, ModelArtifacts):
        raise TypeError("Berry output parsing requires a persisted ModelArtifacts value")
    source_atoms = source_model.atoms
    if "atom_id" not in source_atoms.arrays:
        raise ValueError("Berry output parsing requires source atom_id values")
    map_path = directory / "STRU.atom-map.json"
    atom_map = _json(map_path, "STRU.atom-map.json")
    if atom_map.get("abacus_version_target") != ABACUS_VERSION:
        raise ValueError("Berry atom map must target ABACUS 3.10.1")
    if atom_map.get("model_id") != source_model.model_id or atom_map.get("version") != source_model.version:
        raise ValueError("Berry STRU atom map model identity differs from source_model")
    source_ids = [int(value) for value in atom_map.get("source_atom_ids", [])]
    source_atom_ids = [int(value) for value in source_atoms.arrays["atom_id"]]
    if source_ids != source_atom_ids:
        raise ValueError("Berry STRU atom map source IDs differ from source_model")
    entries = atom_map.get("abacus_order")
    if not isinstance(entries, list) or len(entries) != len(source_atoms):
        raise ValueError("Berry STRU atom map must contain one abacus_order entry per source atom")
    symbols = source_atoms.get_chemical_symbols()
    seen_source_indices: set[int] = set()
    ordered_entries: list[Mapping[str, Any]] = []
    for index, entry in enumerate(sorted(entries, key=lambda item: int(item.get("abacus_index", -1)))):
        if not isinstance(entry, Mapping) or int(entry.get("abacus_index", -1)) != index:
            raise ValueError("Berry STRU atom map abacus indices are not contiguous")
        source_index = int(entry.get("source_index", -1))
        if source_index < 0 or source_index >= len(source_atoms) or source_index in seen_source_indices:
            raise ValueError("Berry STRU atom map source index is invalid or repeated")
        seen_source_indices.add(source_index)
        if int(entry.get("atom_id", -1)) != int(source_atoms.arrays["atom_id"][source_index]):
            raise ValueError("Berry STRU atom map atom ID differs from source_model")
        if str(entry.get("element")) != str(symbols[source_index]):
            raise ValueError("Berry STRU atom map element differs from source_model")
        ordered_entries.append(entry)
    if seen_source_indices != set(range(len(source_atoms))):
        raise ValueError("Berry STRU atom map does not cover source_model atoms")
    stru_path = directory / "STRU"
    stru_contract = _read_stru_contract(stru_path)
    native_atoms = _read_stru(stru_path, atom_map)
    if native_atoms.get_chemical_symbols() != symbols:
        raise ValueError("Berry native STRU element order differs from source_model")
    if [int(value) for value in native_atoms.arrays["atom_id"]] != source_atom_ids:
        raise ValueError("Berry native STRU atom IDs differ from source_model")
    if not np.allclose(native_atoms.cell.array, source_atoms.cell.array, rtol=0.0, atol=1e-8):
        raise ValueError("Berry native STRU lattice differs from source_model")
    native_frac = native_atoms.get_scaled_positions(wrap=False)
    source_frac = source_atoms.get_scaled_positions(wrap=False)
    if native_frac.shape != source_frac.shape or not all(
        _periodic_fractional_close(native, source, atol=5e-8)
        for native, source in zip(native_frac, source_frac)
    ):
        raise ValueError("Berry native STRU coordinates differ from source_model")
    method_model = method.get("model_id")
    method_version = method.get("version")
    if method_model != source_model.model_id or method_version != source_model.version:
        raise ValueError("Berry method.json model identity differs from source_model")
    method_elements = method.get("element_order")
    if method_elements != stru_contract["species"]:
        raise ValueError("Berry method element_order differs from native STRU")
    expected_pseudo = _method_pseudopotentials(method, stru_contract["species"])
    if expected_pseudo != stru_contract["pseudo"]:
        raise ValueError("Berry native STRU pseudopotential filenames differ from method.json")
    moments = method.get("initial_moments_muB_by_element")
    if not isinstance(moments, Mapping) or set(moments) != set(stru_contract["species"]):
        raise ValueError("Berry method initial_moments_muB_by_element must cover STRU species")
    for element in stru_contract["species"]:
        try:
            expected_moment = float(moments[element])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Berry method initial moment is not numeric for {element}") from error
        if not math.isfinite(expected_moment) or not math.isclose(
            expected_moment, float(stru_contract["moments"][element]), rel_tol=0.0, abs_tol=1e-10
        ):
            raise ValueError(f"Berry STRU initial moment differs from method.json for {element}")
    return atom_map, native_atoms, stru_path, stru_contract


def _normalise_unit(unit: str) -> str | None:
    clean = re.sub(r"\s+", "", unit).replace("Ω", "omega").replace("Ω", "omega").lower()
    if clean in {"(e/omega).bohr", "(e/omega)bohr"}:
        return "e_per_omega_bohr"
    if clean in {"e/bohr^2", "e/bohr2"}:
        return "e_per_bohr2"
    if clean in {"c/m^2", "c/m2"}:
        return "c_per_m2"
    return None


def _printed_half_step(raw: str) -> float:
    """Return half of the decimal quantum represented by one native token."""

    clean = raw.strip().replace("d", "e").replace("D", "E")
    mantissa, separator, exponent_text = clean.partition("E")
    decimal_places = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
    exponent = int(exponent_text) if separator else 0
    half_step = 0.5 * (10.0 ** (exponent - decimal_places))
    if not math.isfinite(half_step) or half_step <= 0.0:
        raise ValueError(f"Berry native numeric token has an invalid print interval: {raw!r}")
    return half_step


def _require_fixed_decimal_places(raw: str, places: int, label: str) -> None:
    """Require the fixed-point precision used by ABACUS's native Berry print."""

    clean = raw.strip()
    mantissa = clean.lstrip("+-")
    if "e" in mantissa.lower() or "." not in mantissa:
        raise ValueError(f"Berry native {label} must use fixed {places}-decimal output")
    _, fraction = mantissa.split(".", 1)
    if len(fraction) != places:
        raise ValueError(f"Berry native {label} must use fixed {places}-decimal output")


def _printed_interval(value: float, half_step: float) -> tuple[float, float]:
    return float(value) - float(half_step), float(value) + float(half_step)


def _scaled_interval(interval: tuple[float, float], factor: float) -> tuple[float, float]:
    endpoints = (interval[0] * factor, interval[1] * factor)
    return min(endpoints), max(endpoints)


def _intervals_overlap(first: tuple[float, float], second: tuple[float, float]) -> bool:
    return max(first[0], second[0]) <= min(first[1], second[1])


def _parse_polarization_rows(text: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for match in _P_ROW_RE.finditer(text):
        unit = _normalise_unit(match.group("unit"))
        if unit is None:
            continue
        if unit in rows:
            raise ValueError(f"Berry log contains repeated native polarization unit {unit}")
        raw_value = match.group("value")
        raw_modulo = match.group("mod")
        raw_cartesian = [match.group(axis) for axis in ("x", "y", "z")]
        _require_fixed_decimal_places(raw_value, 7, f"{unit or 'polarization'} value")
        _require_fixed_decimal_places(raw_modulo, 7, f"{unit or 'polarization'} modulo")
        for index, raw_component in enumerate(raw_cartesian):
            _require_fixed_decimal_places(raw_component, 7, f"{unit or 'polarization'} Cartesian component {index}")
        values = {
            "value": _number(raw_value),
            "modulo": _number(raw_modulo),
            "cartesian_reprojection": [
                _number(raw_cartesian[0]),
                _number(raw_cartesian[1]),
                _number(raw_cartesian[2]),
            ],
            "unit": unit,
            "native_unit": " ".join(match.group("unit").split()),
            "_value_half_step": _printed_half_step(raw_value),
            "_modulo_half_step": _printed_half_step(raw_modulo),
            "_cartesian_half_steps": [_printed_half_step(value) for value in raw_cartesian],
        }
        if not math.isfinite(values["value"]) or not math.isfinite(values["modulo"]):
            raise ValueError("Berry native polarization values must be finite")
        if values["modulo"] <= 0.0:
            raise ValueError("Berry native polarization quantum must be positive")
        if not all(math.isfinite(float(value)) for value in values["cartesian_reprojection"]):
            raise ValueError("Berry native Cartesian reprojection must be finite")
        rows[unit] = values
    expected = {"e_per_omega_bohr", "e_per_bohr2", "c_per_m2"}
    if set(rows) != expected:
        missing = sorted(expected - set(rows))
        raise ValueError(f"Berry native log must contain exactly three P/quantum unit rows; missing {missing}")
    return rows


def _parse_native_pp_records(
    text: str, expected_pseudo: Mapping[str, str], expected_functional: str
) -> dict[str, dict[str, float | str]]:
    records: dict[str, dict[str, float | str]] = {}
    for match in _PP_BLOCK_RE.finditer(text):
        name = Path(match.group("name")).name
        body = match.group("body")
        valence_match = _VALENCE_RE.search(body)
        functional_match = _FUNCTIONAL_RE.search(body)
        if valence_match is None or functional_match is None:
            raise ValueError(f"Berry native log pseudopotential block is incomplete for {name}")
        valence = _number(valence_match.group("value"))
        if not math.isfinite(valence) or valence <= 0.0:
            raise ValueError(f"Berry native log has invalid valence electrons for {name}")
        functional = functional_match.group("value")
        if name in records:
            raise ValueError(f"Berry native log repeats pseudopotential {name}")
        records[name] = {"valence_electrons": valence, "functional": functional}
    if set(records) != set(expected_pseudo.values()):
        raise ValueError("Berry native log pseudopotential names differ from native STRU")
    for element, name in expected_pseudo.items():
        observed = records[name]
        if str(observed["functional"]).lower() != str(expected_functional).lower():
            raise ValueError(f"Berry native log pseudopotential functional differs for {element}")
        valence = float(observed["valence_electrons"])
        if not math.isclose(valence, round(valence), rel_tol=0.0, abs_tol=1e-8):
            raise ValueError(f"Berry native log valence electrons are non-integral for {element}")
    return records


def _parse_native_direct_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in _DIRECT_ROW_RE.finditer(text):
        label = match.group("label")
        element_match = re.match(r"taud_(?P<element>[A-Za-z]+)(?P<index>\d+)$", label, re.IGNORECASE)
        if element_match is None:
            raise ValueError(f"Berry native log direct-coordinate label is invalid: {label}")
        rows.append(
            {
                "label": label,
                "element": element_match.group("element"),
                "index": int(element_match.group("index")),
                "frac": [_number(match.group(axis)) for axis in ("x", "y", "z")],
                "moment": _number(match.group("mag")),
            }
        )
    if not rows:
        raise ValueError("Berry native log is missing DIRECT COORDINATES rows")
    return rows


def _validate_native_geometry(
    text: str,
    *,
    stru_contract: Mapping[str, Any],
    atom_map: Mapping[str, Any],
    source_model: ModelArtifacts,
) -> None:
    rows = _parse_native_direct_rows(text)
    expected_records = list(stru_contract["records"])
    if len(rows) != len(expected_records):
        raise ValueError("Berry native log atom count differs from native STRU")
    element_indices: dict[str, int] = {}
    for row, expected in zip(rows, expected_records):
        element = str(expected["element"])
        element_indices[element] = element_indices.get(element, 0) + 1
        if row["element"] != element or row["index"] != element_indices[element]:
            raise ValueError("Berry native log atom labels are not ordered by STRU element blocks")
        if not _periodic_fractional_close(row["frac"], expected["frac"], atol=5e-8):
            raise ValueError(
                "Berry native log direct coordinates differ from native STRU beyond periodic equivalence"
            )
        if not math.isclose(float(row["moment"]), float(expected["moment"]), rel_tol=0.0, abs_tol=5e-7):
            raise ValueError("Berry native log initial magnetic moments differ from native STRU")
    ordered_entries = sorted(atom_map["abacus_order"], key=lambda item: int(item["abacus_index"]))
    source_frac = source_model.atoms.get_scaled_positions(wrap=False)
    if len(ordered_entries) != len(rows):
        raise ValueError("Berry native atom map and native log atom count differ")
    for row, entry in zip(rows, ordered_entries):
        source_index = int(entry["source_index"])
        if str(entry["element"]) != str(source_model.atoms.get_chemical_symbols()[source_index]):
            raise ValueError("Berry atom map element differs from source_model during native log validation")
        if not _periodic_fractional_close(row["frac"], source_frac[source_index], atol=5e-8):
            raise ValueError("Berry native log atom mapping differs from source_model beyond periodic equivalence")


def _compare_input_value(top: str, native: str, key: str) -> None:
    float_keys = {"ecutwfc", "scf_thr", "nbands_mul", "pw_diag_thr", "mixing_beta"}
    int_keys = {"nbands", "nspin", "lspinorb", "noncolin", "symmetry", "berry_phase", "gdir"}
    if key in float_keys:
        try:
            left = _number(top.split()[0])
            right = _number(native.split()[0])
        except (IndexError, ValueError) as error:
            raise ValueError(f"Berry native INPUT {key} is not numeric") from error
        if not math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError(f"Berry native OUT INPUT {key} differs from top-level INPUT")
        return
    if key in int_keys:
        try:
            left = int(top.split()[0])
            right = int(native.split()[0])
        except (IndexError, ValueError) as error:
            raise ValueError(f"Berry native INPUT {key} is not an integer") from error
        if left != right:
            raise ValueError(f"Berry native OUT INPUT {key} differs from top-level INPUT")
        return
    if top.strip().lower() != native.strip().lower():
        raise ValueError(f"Berry native OUT INPUT {key} differs from top-level INPUT")


def _validate_read_file_dir(
    directory: Path,
    *,
    top: Mapping[str, str],
    native: Mapping[str, str],
    berry: Mapping[str, Any],
) -> None:
    method_value = berry.get("read_file_dir")
    if not isinstance(method_value, str) or not method_value.strip():
        raise ValueError("Berry method.berry.read_file_dir is required")

    def resolve(value: str, label: str) -> Path:
        candidate = Path(value.strip())
        resolved = (candidate if candidate.is_absolute() else directory / candidate).resolve()
        if resolved != directory.resolve():
            raise ValueError(f"Berry {label} read_file_dir must point to the current task root")
        return resolved

    method_root = resolve(method_value, "method.berry")
    top_value = top.get("read_file_dir")
    native_value = native.get("read_file_dir")
    if not isinstance(top_value, str) or not top_value.strip():
        raise ValueError("Berry top-level INPUT read_file_dir is required")
    if not isinstance(native_value, str) or not native_value.strip():
        raise ValueError("Berry native OUT INPUT read_file_dir is required")
    if resolve(top_value, "top-level INPUT") != method_root:
        raise ValueError("Berry top-level INPUT read_file_dir differs from method.berry.read_file_dir")
    if resolve(native_value, "native OUT INPUT") != method_root:
        raise ValueError("Berry native OUT INPUT read_file_dir differs from method.berry.read_file_dir")


def _validate_native_input_echo(
    directory: Path,
    suffix: str,
    top: Mapping[str, str],
    berry: Mapping[str, Any],
) -> tuple[Path, dict[str, str]]:
    output_input = directory / f"OUT.{suffix}" / "INPUT"
    native = _read_input(output_input, allow_blank_values=True)
    keys = (
        "suffix",
        "calculation",
        "device",
        "dft_functional",
        "basis_type",
        "ks_solver",
        "ecutwfc",
        "nbands",
        "nspin",
        "lspinorb",
        "noncolin",
        "mixing_type",
        "mixing_beta",
        "symmetry",
        "smearing_method",
        "init_chg",
        "berry_phase",
        "gdir",
        "pw_diag_thr",
    )
    for key in keys:
        if key not in top:
            raise ValueError(f"Berry top-level INPUT is missing required comparison keyword {key!r}")
        if key not in native:
            raise ValueError(f"Berry native OUT INPUT is missing required comparison keyword {key!r}")
        _compare_input_value(top[key], native[key], key)
    _validate_read_file_dir(directory, top=top, native=native, berry=berry)
    if native.get("kpar") != "1" or top.get("kpar", "1") != "1":
        raise ValueError("ABACUS 3.10.1 Berry CPU overlap requires kpar=1")
    return output_input, native


def _validate_device(
    directory: Path,
    *,
    top: Mapping[str, str],
    native: Mapping[str, str],
    method: Mapping[str, Any],
    berry: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """Validate the historical CPU path or a registered isolated GPU build.

    CPU remains the historical path and needs no build registration.  GPU is
    accepted only when the method carries the candidate build record and the
    parser's protocol supplies the same registration; a device flag alone is
    never sufficient to release the unpatched native implementation.
    """

    method_device = method.get("device")
    if not isinstance(method_device, str) or method_device.strip().lower() not in ("cpu", "gpu"):
        raise ValueError("Berry method device must be cpu or gpu")
    device = method_device.strip().lower()
    for label, values in (("top-level INPUT", top), ("native OUT INPUT", native)):
        input_device = values.get("device")
        if not isinstance(input_device, str) or input_device.strip().lower() != device:
            raise ValueError(
                f"Berry {label} device must match method device {device} "
                f"(observed {input_device!r})"
            )

    stdout_path = directory / "stdout.log"
    try:
        stdout = stdout_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ValueError(f"Berry native stdout is required to prove {device} execution: {stdout_path}") from error
    devices = re.findall(
        r"^\s*RUNNING\s+WITH\s+DEVICE\s*:\s*(?P<device>[A-Za-z]+)\b",
        stdout,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not devices or any(item.lower() != device for item in devices):
        raise ValueError(f"Berry native stdout must prove RUNNING WITH DEVICE : {device.upper()}")

    if device == "cpu":
        return stdout_path, {"device": "cpu"}

    implementation_id = berry.get("implementation_id")
    build = berry.get("gpu_build")
    # ``berry_results.read_berry_task`` passes the method.berry mapping as the
    # expected protocol, where the nested record is named ``gpu_build``;
    # callers that retain the site-level name may use ``berry_gpu_build``.
    expected_build = expected.get("berry_gpu_build", expected.get("gpu_build"))
    if not isinstance(implementation_id, str) or not implementation_id.strip():
        raise ValueError("Berry GPU method requires a registered implementation_id")
    if implementation_id.strip() != BERRY_GPU_IMPLEMENTATION_ID:
        raise ValueError(
            "Berry GPU method implementation_id is not the supported candidate "
            f"{BERRY_GPU_IMPLEMENTATION_ID!r}"
        )
    if not isinstance(build, Mapping):
        raise ValueError("Berry GPU method requires a registered gpu_build record")
    if not isinstance(expected_build, Mapping):
        raise ValueError("Berry GPU parser requires the registered candidate build protocol")
    for label, record in (("method", build), ("protocol", expected_build)):
        if record.get("implementation_id") != implementation_id:
            raise ValueError(f"Berry GPU {label} build implementation_id differs from method")
        if record.get("scope") != BERRY_GPU_SCOPE:
            raise ValueError(f"Berry GPU {label} build scope must be {BERRY_GPU_SCOPE!r}")
        binary = record.get("binary")
        if not isinstance(binary, str) or not binary.strip():
            raise ValueError(f"Berry GPU {label} build binary is required")
    expected_id = expected.get("implementation_id", expected_build.get("implementation_id"))
    if expected_id != implementation_id:
        raise ValueError("Berry GPU implementation_id differs from expected protocol")
    if dict(build) != dict(expected_build):
        raise ValueError("Berry GPU method build record differs from expected protocol")
    source = berry.get("binary_source")
    if source not in (None, build.get("binary")):
        raise ValueError("Berry GPU binary_source differs from the registered build binary")
    return stdout_path, {
        "device": "gpu",
        "implementation_id": implementation_id,
        "binary_source": source or build.get("binary"),
        "gpu_build": dict(build),
    }


def _validate_native_charge_read(
    directory: Path,
    *,
    text: str,
    berry: Mapping[str, Any],
    charge_density: Mapping[str, Any],
) -> None:
    """Bind ABACUS's final native charge-read print to the copied charge file."""

    files = charge_density.get("files")
    read_file_dir = berry.get("read_file_dir")
    declared_charge_dir = charge_density.get("read_file_dir")
    if not isinstance(files, list) or not files:
        raise ValueError("Berry charge-density files are required for native charge-read validation")
    if not isinstance(read_file_dir, str) or not read_file_dir.strip():
        raise ValueError("Berry read_file_dir is required for native charge-read validation")
    if declared_charge_dir != read_file_dir:
        raise ValueError("Berry charge-density read_file_dir differs from berry.read_file_dir")
    expected_paths = [
        (directory / Path(read_file_dir.strip()) / str(filename)).resolve() for filename in files
    ]
    matches = list(_CHARGE_READ_RE.finditer(text))
    if not matches:
        raise ValueError("Berry native log is missing the charge-density read marker")
    if len(matches) != len(expected_paths):
        raise ValueError("Berry native charge-density read markers do not match declared files")
    native_paths = [
        (Path(match.group("path")) if Path(match.group("path")).is_absolute() else directory / Path(match.group("path"))).resolve()
        for match in matches
    ]
    if native_paths[-1] != expected_paths[-1]:
        raise ValueError("Berry native final charge-density read path differs from declared file")
    if native_paths != expected_paths:
        raise ValueError("Berry native charge-density read paths differ from declared files or directory")


def _validate_native_pseudopotential_echo(
    directory: Path,
    suffix: str,
    *,
    stru_contract: Mapping[str, Any],
    atom_map: Mapping[str, Any],
    source_model: ModelArtifacts,
    log_text: str,
    method: Mapping[str, Any],
) -> dict[str, dict[str, float | str]]:
    pp_records = _parse_native_pp_records(log_text, stru_contract["pseudo"], str(method["dft_functional"]))
    _validate_native_geometry(
        log_text,
        stru_contract=stru_contract,
        atom_map=atom_map,
        source_model=source_model,
    )
    native_stru_path = directory / f"OUT.{suffix}" / "STRU"
    if native_stru_path.is_file():
        native_contract = _read_stru_contract(native_stru_path)
        if native_contract["pseudo"] != stru_contract["pseudo"] or native_contract["moments"] != stru_contract["moments"]:
            raise ValueError("Berry native OUT STRU pseudopotential or initial-moment echo differs")
    return pp_records


def _validate_native_polarization(
    rows: Mapping[str, Mapping[str, Any]],
    *,
    native_atoms: Any,
    gdir: int,
    modulus: int,
) -> dict[str, float | int]:
    direction_vector = np.asarray(native_atoms.cell.array[gdir - 1], dtype=float)
    direction_norm_angstrom = float(np.linalg.norm(direction_vector))
    volume_angstrom3 = abs(float(np.linalg.det(native_atoms.cell.array)))
    if direction_norm_angstrom <= 0.0 or volume_angstrom3 <= 0.0:
        raise ValueError("Berry STRU direction lattice vector or cell volume is invalid")
    direction_unit = direction_vector / direction_norm_angstrom
    value_intervals = {
        unit: _printed_interval(float(row["value"]), float(row["_value_half_step"]))
        for unit, row in rows.items()
    }
    modulo_intervals = {
        unit: _printed_interval(float(row["modulo"]), float(row["_modulo_half_step"]))
        for unit, row in rows.items()
    }
    for unit, row in rows.items():
        cartesian_half_steps = [float(value) for value in row["_cartesian_half_steps"]]
        for index, component in enumerate(row["cartesian_reprojection"]):
            observed = _printed_interval(float(component), cartesian_half_steps[index])
            predicted = _scaled_interval(value_intervals[unit], float(direction_unit[index]))
            if not _intervals_overlap(observed, predicted):
                raise ValueError(
                    f"Berry native {unit} Cartesian reprojection is inconsistent with its direction "
                    "beyond print intervals"
                )
    rmod_bohr = direction_norm_angstrom * BOHR_PER_ANGSTROM
    volume_bohr3 = volume_angstrom3 * BOHR_PER_ANGSTROM**3
    expected_quantum = {
        "e_per_omega_bohr": rmod_bohr * modulus,
        "e_per_bohr2": (rmod_bohr / volume_bohr3) * modulus,
        "c_per_m2": (rmod_bohr / volume_bohr3) * _E_PER_BOHR2_TO_C_PER_M2 * modulus,
    }
    for unit, row in rows.items():
        expected = expected_quantum[unit]
        if not modulo_intervals[unit][0] <= expected <= modulo_intervals[unit][1]:
            raise ValueError(
                f"Berry native {unit} polarization quantum differs from cell/direction "
                "beyond its print interval"
            )
    conversion_pairs = (
        (
            "e_per_omega_bohr",
            "e_per_bohr2",
            1.0 / volume_bohr3,
            "e/Omega.bohr and e/bohr^2",
        ),
        (
            "e_per_bohr2",
            "c_per_m2",
            _E_PER_BOHR2_TO_C_PER_M2,
            "e/bohr^2 and C/m^2",
        ),
        (
            "e_per_omega_bohr",
            "c_per_m2",
            _E_PER_BOHR2_TO_C_PER_M2 / volume_bohr3,
            "e/Omega.bohr and C/m^2",
        ),
    )
    for first, second, factor, label in conversion_pairs:
        if not _intervals_overlap(_scaled_interval(value_intervals[first], factor), value_intervals[second]):
            raise ValueError(f"Berry native polarization values are inconsistent between {label}")
        if not _intervals_overlap(_scaled_interval(modulo_intervals[first], factor), modulo_intervals[second]):
            raise ValueError(f"Berry native polarization modulo values are inconsistent between {label}")
    return {
        "rmod_bohr": rmod_bohr,
        "cell_volume_bohr3": volume_bohr3,
        "quantum_factor": modulus,
        "quantum_e_per_omega_bohr": expected_quantum["e_per_omega_bohr"],
        "quantum_e_per_bohr2": expected_quantum["e_per_bohr2"],
        "quantum_C_per_m2": expected_quantum["c_per_m2"],
    }


def parse_berry_outputs(
    directory: str | Path,
    *,
    source_model: ModelArtifacts,
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Parse one completed ABACUS 3.10.1 PW NSCF Berry result.

    The expected protocol requires ``gdir``, ``pw_diag_thr`` and
    ``reference_task_id``.  The current 3.10.1 adapter deliberately accepts
    only fixed-occupation nspin=1 calculations because the native source uses
    one occupied-band count for both spin channels.  CPU records remain
    compatible with the historical path; GPU records additionally require an
    explicitly registered candidate build in the method and protocol.  The
    parser verifies the native cell-derived quantum and all three printed unit
    rows but leaves branch selection and scientific qualification to the outer
    workflow.
    """

    if not isinstance(expected, Mapping):
        raise TypeError("Berry expected protocol must be a mapping")
    if not isinstance(source_model, ModelArtifacts):
        raise TypeError("Berry output parsing requires a persisted ModelArtifacts value")
    directory = Path(directory)
    method_path = directory / "method.json"
    method = _json(method_path, "method.json")
    task_path = directory / "task.json"
    task = _json(task_path, "task.json") if task_path.exists() else {}
    berry = method.get("berry")
    if not isinstance(berry, Mapping):
        raise ValueError("Berry method.json berry field must be an object")
    if berry.get("role") != "nscf":
        raise ValueError("Berry method.json berry.role must be nscf")

    if method.get("engine") != "abacus" or method.get("abacus_version_target") != ABACUS_VERSION:
        raise ValueError("Berry method.json must target ABACUS 3.10.1")
    if method.get("basis_type") != "pw":
        raise ValueError("Berry method.json must use PW basis")
    if method.get("stage") != "nscf":
        raise ValueError("Berry method.json stage must be nscf")
    if task:
        if task.get("engine") not in (None, "abacus") or task.get("engine_version") not in (None, ABACUS_VERSION):
            raise ValueError("Berry task identity must target ABACUS 3.10.1")
        if task.get("calculation") not in (None, "nscf"):
            raise ValueError("Berry task calculation must be nscf")
        if task.get("model_id") not in (None, source_model.model_id) or task.get("model_version") not in (
            None,
            source_model.version,
        ):
            raise ValueError("Berry task model identity differs from source_model")
        if task.get("method_set") not in (None, method.get("method_set")):
            raise ValueError("Berry task/method method_set mismatch")
        task_berry = task.get("berry")
        if task_berry is not None:
            if not isinstance(task_berry, Mapping):
                raise ValueError("Berry task berry field must be an object")
            for key in ("role", "gdir", "pw_diag_thr", "source_reference_task_id", "charge_density"):
                if task_berry.get(key) != berry.get(key):
                    raise ValueError(f"Berry task/method berry.{key} mismatch")

    expected_gdir = _required(expected, "gdir", "protocol")
    if isinstance(expected_gdir, bool) or int(expected_gdir) not in (1, 2, 3) or int(expected_gdir) != expected_gdir:
        raise ValueError("Berry expected gdir must be 1, 2 or 3")
    gdir = int(expected_gdir)
    expected_pw_thr = _required(expected, "pw_diag_thr", "protocol")
    try:
        expected_pw_thr = float(expected_pw_thr)
    except (TypeError, ValueError) as error:
        raise ValueError("Berry expected pw_diag_thr must be numeric") from error
    if not math.isfinite(expected_pw_thr) or expected_pw_thr <= 0.0 or expected_pw_thr > 1.0e-3:
        raise ValueError("Berry expected pw_diag_thr must be finite, positive and <= 1e-3")
    expected_reference = _required(expected, "reference_task_id", "protocol")
    if not isinstance(expected_reference, str) or not expected_reference:
        raise ValueError("Berry expected reference_task_id must be a non-empty string")

    values = _read_input(directory / "INPUT")
    method_set = method.get("method_set")
    if not isinstance(method_set, str) or not method_set:
        raise ValueError("Berry method.json requires a non-empty method_set")
    if expected.get("method_set") not in (None, method_set):
        raise ValueError("Berry expected/method method_set mismatch")
    atom_map, native_atoms, stru_path, stru_contract = _validate_model_and_stru(directory, source_model, method)
    reference_task_id, charge_density = _reference_fields(method)
    if reference_task_id != expected_reference:
        raise ValueError("Berry source_reference_task_id differs from expected protocol")
    for filename in charge_density["files"]:
        charge_path = directory / filename
        if not charge_path.is_file() or charge_path.stat().st_size <= 0:
            raise ValueError(f"Berry native charge-density file is missing or empty: {charge_path}")

    nspin = method.get("nspin")
    if nspin != 1 or isinstance(nspin, bool):
        raise ValueError(
            "unsupported_spin_resolved_occupations: ABACUS 3.10.1 uses one occupied-band count for both spin channels"
        )
    if berry.get("nspin") not in (None, 1):
        raise ValueError("unsupported_spin_resolved_occupations: Berry method nspin must be 1")
    if expected.get("nspin") not in (None, nspin):
        raise ValueError("Berry expected/method nspin mismatch")
    if _int_input(values, "nspin") != nspin:
        raise ValueError("Berry INPUT/method nspin mismatch")
    if values.get("calculation", "").lower() != "nscf":
        raise ValueError("Berry INPUT calculation must be nscf")
    if values.get("basis_type", "").lower() != "pw":
        raise ValueError("Berry INPUT basis_type must be pw")
    if values.get("init_chg", "").lower() != "file":
        raise ValueError("Berry INPUT init_chg must be file")
    if _int_input(values, "berry_phase") != 1:
        raise ValueError("Berry INPUT berry_phase must be 1")
    if _int_input(values, "symmetry") != -1:
        raise ValueError("Berry INPUT symmetry must be -1")
    if method.get("symmetry") != -1 or berry.get("symmetry") != -1:
        raise ValueError("Berry method symmetry must be -1")
    if _bool_input(values.get("lspinorb", ""), key="lspinorb"):
        raise ValueError("Berry INPUT lspinorb must be false")
    if _bool_input(values.get("noncolin", ""), key="noncolin"):
        raise ValueError("Berry INPUT noncolin must be false")
    if method.get("lspinorb") is not False or method.get("noncolin") is not False:
        raise ValueError("Berry method must explicitly select non-SOC collinear calculations")
    if berry.get("lspinorb") not in (None, False) or berry.get("noncolin") not in (None, False):
        raise ValueError("Berry berry method must select non-SOC collinear calculations")
    if method.get("occupations") != "fixed" or berry.get("occupations") != "fixed":
        raise ValueError("Berry method occupations must be fixed")
    if values.get("smearing_method", "").lower() != "fixed" or "smearing_sigma" in values:
        raise ValueError("Berry fixed occupations must use smearing_method=fixed without smearing_sigma")
    if berry.get("berry_phase") != 1 or berry.get("init_chg") != "file":
        raise ValueError("Berry berry protocol must declare berry_phase=1 and init_chg=file")

    method_gdir = berry.get("gdir")
    if method_gdir != gdir:
        raise ValueError("Berry method berry.gdir differs from expected protocol")
    method_pw_thr = berry.get("pw_diag_thr")
    if method_pw_thr is None or not math.isclose(float(method_pw_thr), expected_pw_thr, rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError("Berry method berry.pw_diag_thr differs from expected protocol")
    native_gdir = _int_input(values, "gdir")
    if native_gdir != gdir:
        raise ValueError("Berry INPUT gdir differs from expected protocol")
    native_pw_thr = _float_input(values, "pw_diag_thr")
    if native_pw_thr > 1.0e-3 or not math.isclose(native_pw_thr, expected_pw_thr, rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError("Berry INPUT pw_diag_thr differs from expected protocol")

    parameters = method.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("Berry method.json parameters are required for native input identity")
    if method.get("dft_functional") != values.get("dft_functional"):
        raise ValueError("Berry method dft_functional differs from top-level INPUT")
    if method.get("ks_solver") != values.get("ks_solver") or method.get("mixing_type") != values.get("mixing_type"):
        raise ValueError("Berry method solver/mixing identity differs from top-level INPUT")
    for key, parameter_key in (("ecutwfc", "ecutwfc_Ry"), ("nbands", "nbands")):
        if parameter_key not in parameters:
            raise ValueError(f"Berry method parameters missing {parameter_key}")
        if key == "nbands":
            if _int_input(values, key) != int(parameters[parameter_key]):
                raise ValueError("Berry method nbands differs from top-level INPUT")
        elif not math.isclose(_float_input(values, key), float(parameters[parameter_key]), rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("Berry method ecutwfc differs from top-level INPUT")

    mesh, shift = _read_kpt(directory / "KPT")
    expected_mesh = expected.get("kpoints")
    if expected_mesh is None:
        expected_mesh = method.get("kpoints")
    if expected_mesh is None:
        raise ValueError("Berry protocol/method must record expected kpoints")
    expected_mesh_tuple = _expected_vector(expected_mesh, key="kpoints", integer=True)
    if mesh != expected_mesh_tuple:
        raise ValueError("Berry native KPT mesh differs from expected protocol")
    expected_shift = expected.get("kpoint_shift", (0.0, 0.0, 0.0))
    expected_shift_tuple = _expected_vector(expected_shift, key="kpoint_shift", integer=False)
    if not np.allclose(np.asarray(shift), np.asarray(expected_shift_tuple), rtol=0.0, atol=1.0e-12):
        raise ValueError("Berry native KPT shift differs from expected protocol")

    suffix = method.get("suffix")
    if not isinstance(suffix, str) or not suffix:
        raise ValueError("Berry method.json requires a non-empty suffix")
    output_input_path, native_input = _validate_native_input_echo(directory, suffix, values, berry)
    stdout_path, device_metadata = _validate_device(
        directory,
        top=values,
        native=native_input,
        method=method,
        berry=berry,
        expected=expected,
    )
    log_path = directory / f"OUT.{suffix}" / "running_nscf.log"
    text = log_path.read_text(encoding="utf-8")
    _validate_native_charge_read(
        directory,
        text=text,
        berry=berry,
        charge_density=charge_density,
    )
    versions = [match.group("version") for match in _VERSION_RE.finditer(text)]
    if not versions or any(version != ABACUS_VERSION for version in versions):
        raise ValueError("Berry native log does not prove exact ABACUS 3.10.1")
    if "POLARIZATION CALCULATION" not in text.upper() or "VALUES OF POLARIZATION" not in text.upper():
        raise ValueError("Berry native log is missing the polarization calculation marker")
    if not re.search(r"^\s*Finish\s+Time\s*:", text, re.IGNORECASE | re.MULTILINE):
        raise ValueError("Berry native log is missing the ABACUS Finish Time completion marker")
    if not re.search(r"^\s*Total\s+Time\s*:", text, re.IGNORECASE | re.MULTILINE):
        raise ValueError("Berry native log is missing the ABACUS Total Time completion marker")

    pp_records = _validate_native_pseudopotential_echo(
        directory,
        suffix,
        stru_contract=stru_contract,
        atom_map=atom_map,
        source_model=source_model,
        log_text=text,
        method=method,
    )
    phases: dict[str, float] = {}
    for match in _PHASE_RE.finditer(text):
        key = "ionic" if match.group("label").lower().startswith("the ionic") else "electronic"
        if key in phases:
            raise ValueError(f"Berry native log contains repeated {key} phase")
        raw_phase = match.group("value")
        _require_fixed_decimal_places(raw_phase, 5, f"{key} phase")
        phase = _number(raw_phase)
        if not math.isfinite(phase):
            raise ValueError(f"Berry native {key} phase must be finite")
        phases[key] = phase
    if set(phases) != {"ionic", "electronic"}:
        raise ValueError("Berry native log must contain ionic and electronic phases")
    direction_matches = list(_DIRECTION_RE.finditer(text))
    if len(direction_matches) != 1 or int(direction_matches[0].group("gdir")) != gdir:
        raise ValueError("Berry native polarization direction differs from expected gdir")
    rows = _parse_polarization_rows(text)
    zvals = [float(record["valence_electrons"]) for record in pp_records.values()]
    quantum_factor = 1 if any(int(round(value)) % 2 for value in zvals) else 2
    quantum = _validate_native_polarization(rows, native_atoms=native_atoms, gdir=gdir, modulus=quantum_factor)
    direction_vector = np.asarray(native_atoms.cell.array[gdir - 1], dtype=float)
    direction_norm = float(np.linalg.norm(direction_vector))
    direction_unit = direction_vector / direction_norm
    public_rows = {
        unit: {key: value for key, value in row.items() if not key.startswith("_")}
        for unit, row in rows.items()
    }

    task_id = task.get("task_id", method.get("task_id"))
    native_sources: dict[str, str] = {
        "INPUT": str(directory / "INPUT"),
        "native_INPUT": str(output_input_path),
        "KPT": str(directory / "KPT"),
        "STRU": str(stru_path),
        "STRU.atom-map.json": str(directory / "STRU.atom-map.json"),
        "method.json": str(method_path),
        "running_nscf.log": str(log_path),
        "stdout.log": str(stdout_path),
    }
    for index, filename in enumerate(charge_density["files"]):
        native_sources[f"charge_density_{index}"] = str(directory / filename)
    result = {
        "schema": "mlcc.abacus-polarization.v1",
        "engine": "abacus",
        "engine_version": ABACUS_VERSION,
        "method_set": method_set,
        "task_id": task_id,
        "reference_task_id": reference_task_id,
        "reference_scf_task_id": reference_task_id,
        "reference_scf_status": "not_checked_by_nscf_parser",
        "reference_charge_source": dict(charge_density),
        "model_id": source_model.model_id,
        "model_version": source_model.version,
        "stage": "nscf",
        "basis_type": "pw",
        "device": device_metadata["device"],
        "nspin": 1,
        "occupations": "fixed",
        "lspinorb": False,
        "noncolin": False,
        "symmetry": -1,
        "berry_phase": True,
        "gdir": gdir,
        "direction_lattice_vector_angstrom": direction_vector.tolist(),
        "direction_unit_vector_cartesian": direction_unit.tolist(),
        "kpoints": list(mesh),
        "kpoint_shift": list(shift),
        "pw_diag_thr": native_pw_thr,
        "ionic_phase": phases["ionic"],
        "electronic_phase": phases["electronic"],
        "polarization_rows": public_rows,
        "native_polarization_rows": public_rows,
        "total_P_e_per_omega_bohr": public_rows["e_per_omega_bohr"]["value"],
        "modulo_quantum_e_per_omega_bohr": public_rows["e_per_omega_bohr"]["modulo"],
        "total_P_e_per_bohr2": public_rows["e_per_bohr2"]["value"],
        "modulo_quantum_e_per_bohr2": public_rows["e_per_bohr2"]["modulo"],
        "total_P_C_per_m2": public_rows["c_per_m2"]["value"],
        "modulo_quantum_C_per_m2": public_rows["c_per_m2"]["modulo"],
        "cartesian_reprojection": public_rows["c_per_m2"]["cartesian_reprojection"],
        "native_cartesian_reprojection_C_per_m2": public_rows["c_per_m2"]["cartesian_reprojection"],
        "quantum_check": quantum,
        "native_pp_valence_electrons": {name: record["valence_electrons"] for name, record in pp_records.items()},
        "native_completed": True,
        "nscf_completed": True,
        "completion_marker": "Finish Time + Total Time",
        "nscf_completion_marker": "Finish Time + Total Time",
        "branch_status": "not_unwrapped",
        "branch_unwrapped": False,
        "electronic_converged": None,
        "reference_scf_converged": None,
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
        "scientific_status": "evaluated_polarization_unqualified",
        "source_files": native_sources,
        "native_format": "ABACUS 3.10.1 running_nscf.log POLARIZATION CALCULATION",
    }
    if device_metadata.get("implementation_id"):
        result["implementation_id"] = device_metadata["implementation_id"]
    if device_metadata.get("binary_source"):
        result["binary_source"] = device_metadata["binary_source"]
    return result
