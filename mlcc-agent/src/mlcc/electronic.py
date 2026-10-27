"""Direct extraction of electronic levels from a completed ABACUS SCF task.

The ABACUS ``istate.info`` file stores occupations already multiplied by the
weight of the corresponding k point.  This module keeps those native values
and also exposes the explicitly normalised occupations used for electron
counting and for the sampled-mesh gap.  When native k-point weights are
rounded, the normalisation uses exact ``1/N`` weights only after the complete
uniform Gamma mesh and each native print interval have been verified; the
original printed weights remain in the returned evidence.  Charged
first-slice SCF extraction keeps the neutral ``AUTOSET`` count separate from
ABACUS's adjusted target marker and remains explicitly unqualified for defect
science.  It deliberately does not add the result to the task's historical
``result.json``; a caller may serialise the returned mapping wherever its
workflow requires.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ABACUS_VERSION = "3.10.1"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_HEADER_ONE = re.compile(
    rf"^\s*BAND\s+Energy\(ev\)\s+Occupation\s+Kpoint\s*=\s*(\d+)\s+\(([^)]*)\)\s*$",
    re.IGNORECASE,
)
_HEADER_TWO = re.compile(
    rf"^\s*BAND\s+Spin\s+up\s+Energy\(ev\)\s+Occupation\s+"
    rf"Spin\s+down\s+Energy\(ev\)\s+Occupation\s+Kpoint\s*=\s*(\d+)\s+\(([^)]*)\)\s*$",
    re.IGNORECASE,
)
_ROW_ONE = re.compile(rf"^\s*(\d+)\s+({_FLOAT})\s+({_FLOAT})\s*$")
_ROW_TWO = re.compile(
    rf"^\s*(\d+)\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s*$"
)
_KPOINT_ROW = re.compile(rf"^\s*(\d+)\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s*$")
_NKTOTAL = re.compile(r"nkstot\s+now\s*=\s*(\d+)", re.IGNORECASE)
_EFERMI = re.compile(rf"^\s*EFERMI\s*=\s*({_FLOAT})\s+eV\s*$", re.IGNORECASE)
_NSPIN_LOG = re.compile(r"STATE ENERGY\(eV\).*NSPIN\s*==\s*(\d+)", re.IGNORECASE)
_AUTOSET_ELECTRONS = re.compile(
    rf"^\s*AUTOSET\s+number\s+of\s+electrons\s*:\s*=\s*({_FLOAT})\s*$",
    re.IGNORECASE,
)
_NELEC_DELTA = re.compile(rf"\bnelec_delta\s*:\s*(?:=\s*)?({_FLOAT})\b", re.IGNORECASE)
_NELEC_NOW = re.compile(rf"\bnelec\s+now\s*:\s*(?:=\s*)?({_FLOAT})\b", re.IGNORECASE)

_OCCUPATION_TOLERANCE = 1.0e-8
_WEIGHT_SUM_TOLERANCE = 1.0e-8
_ELECTRON_COUNT_TOLERANCE = 1.0e-5


def _as_float(token: str) -> float:
    """Parse an ABACUS number, including Fortran ``D`` exponents."""

    value = float(token.replace("D", "E").replace("d", "e"))
    if not math.isfinite(value):
        raise ValueError(f"non-finite native numeric value: {token!r}")
    return value


def _printed_half_step(raw: str) -> float:
    """Return the half quantum represented by one native numeric token.

    ABACUS prints native k-point weights with four decimal places.  The
    printed value is therefore evidence for an interval, not an exact value;
    the original token is retained by the caller.  An integer coordinate is
    treated as exact because ABACUS uses bare ``0`` for exact zero headers in
    ``istate.info``.
    """

    clean = raw.strip().upper().replace("D", "E")
    mantissa, separator, exponent_text = clean.partition("E")
    if not separator and "." not in mantissa:
        return 0.0
    decimal_places = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
    exponent = int(exponent_text) if separator else 0
    half_step = 0.5 * (10.0 ** (exponent - decimal_places))
    if not math.isfinite(half_step) or half_step < 0.0:
        raise ValueError(f"native numeric token has an invalid print interval: {raw!r}")
    return half_step


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _require_equal(label: str, left: Any, right: Any) -> None:
    if left != right:
        raise ValueError(f"{label} mismatch: {left!r} != {right!r}")


def _native_output_dir(task_dir: Path, result: Mapping[str, Any], method: Mapping[str, Any]) -> Path:
    """Resolve and identify the native output directory belonging to this task."""

    suffix = method.get("suffix")
    if not isinstance(suffix, str) or not suffix:
        raise ValueError("method.suffix is required to identify the ABACUS native output directory")
    native_dir = task_dir / f"OUT.{suffix}"
    if not native_dir.is_dir():
        raise FileNotFoundError(native_dir)

    source_files = result.get("source_files")
    if not isinstance(source_files, Mapping):
        raise ValueError("result.source_files is required for native electronic extraction")
    source_log = source_files.get("running_scf.log")
    if not isinstance(source_log, str) or not source_log:
        raise ValueError("result.source_files.running_scf.log is required")
    reported_log = Path(source_log)
    if not reported_log.is_absolute():
        reported_log = task_dir / reported_log
    if reported_log.resolve() != (native_dir / "running_scf.log").resolve():
        raise ValueError(
            "result.source_files.running_scf.log does not identify the task's OUT.<method.suffix> log"
        )
    return native_dir


def _parse_input(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    parameters: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if fields[0].upper() == "INPUT_PARAMETERS":
            continue
        if len(fields) < 2:
            raise ValueError(f"invalid ABACUS INPUT line in {path}: {line!r}")
        parameters[fields[0].lower()] = fields[1]
    return parameters


def _integer_charge(value: Any, *, name: str, default: int | None = None) -> int:
    """Return an explicit finite integer charge, preserving neutral history."""

    if value is None:
        if default is None:
            raise ValueError(f"{name} is required")
        return int(default)
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if not math.isfinite(numeric) or not math.isclose(numeric, round(numeric), rel_tol=0.0, abs_tol=0.0):
        raise ValueError(f"{name} must be an integer")
    return int(round(numeric))


def _optional_integer_field(parameters: Mapping[str, str], name: str) -> int | None:
    value = parameters.get(name)
    if value is None:
        return None
    return _integer_charge(value, name=f"INPUT {name}")


def _native_electron_markers(path: Path) -> dict[str, Any]:
    """Read ABACUS's neutral and adjusted electron-count log markers.

    With ``nelec=0`` ABACUS prints the neutral UPF-valence count in the
    ``AUTOSET`` line.  When ``nelec_delta`` is active, the 3.10.1 source then
    prints the applied delta and the adjusted ``nelec now`` value.  These are
    kept as separate evidence fields; the AUTOSET count is never relabelled as
    the charged target.
    """

    if not path.is_file():
        raise FileNotFoundError(path)
    autoset: list[float] = []
    deltas: list[float] = []
    adjusted: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _AUTOSET_ELECTRONS.match(line)
        if match is not None:
            autoset.append(_as_float(match.group(1)))
        match = _NELEC_DELTA.search(line)
        if match is not None:
            deltas.append(_as_float(match.group(1)))
        match = _NELEC_NOW.search(line)
        if match is not None:
            adjusted.append(_as_float(match.group(1)))
    if not autoset:
        raise ValueError(f"native AUTOSET electron-count marker not found in {path}")
    neutral = autoset[-1]
    if neutral < 0.0:
        raise ValueError(f"native AUTOSET electron count is negative in {path}")
    return {
        "neutral": neutral,
        "delta": deltas[-1] if deltas else None,
        "target": adjusted[-1] if adjusted else None,
        "autoset_values": autoset,
        "delta_values": deltas,
        "target_values": adjusted,
        "source": str(path),
    }


def _parse_input_kmesh(path: Path) -> tuple[list[int], list[int]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 4 or lines[0] != "K_POINTS" or lines[1] != "0" or lines[2] != "Gamma":
        raise ValueError("only the four-line Gamma KPT form is accepted: K_POINTS/0/Gamma/mesh 0 0 0")
    fields = lines[3].split()
    if len(fields) != 6:
        raise ValueError(f"Gamma KPT mesh line must contain six integers in {path}")
    try:
        mesh = [int(fields[index]) for index in range(3)]
        shift = [int(fields[index]) for index in range(3, 6)]
    except ValueError as error:
        raise ValueError(f"Gamma KPT mesh line must contain integers in {path}") from error
    if not all(value > 0 for value in mesh) or shift != [0, 0, 0]:
        raise ValueError("only a positive Gamma mesh with zero shift is accepted")
    return mesh, shift


def _parse_native_kpoints(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    expected_total: int | None = None
    for line in lines:
        match = _NKTOTAL.search(line)
        if match:
            expected_total = int(match.group(1))
            break

    marker_index = next(
        (index for index, line in enumerate(lines) if line.strip().upper() == "K-POINTS DIRECT COORDINATES"),
        None,
    )
    if marker_index is None:
        raise ValueError(f"native direct k-point table not found in {path}")

    rows: list[tuple[int, float, float, float, float]] = []
    raw_coordinate_tokens: list[tuple[str, str, str]] = []
    raw_weight_tokens: list[str] = []
    coordinate_half_steps: list[tuple[float, float, float]] = []
    weight_half_steps: list[float] = []
    started = False
    for line in lines[marker_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            if started:
                break
            continue
        match = _KPOINT_ROW.match(line)
        if match is None:
            if started:
                raise ValueError(f"invalid native k-point row in {path}: {line!r}")
            continue
        started = True
        coordinate_tokens = tuple(match.group(index) for index in (2, 3, 4))
        weight_token = match.group(5)
        rows.append(
            (
                int(match.group(1)),
                *(_as_float(token) for token in coordinate_tokens),
                _as_float(weight_token),
            )
        )
        raw_coordinate_tokens.append(coordinate_tokens)
        raw_weight_tokens.append(weight_token)
        coordinate_half_steps.append(tuple(_printed_half_step(token) for token in coordinate_tokens))
        weight_half_steps.append(_printed_half_step(weight_token))
    if not rows:
        raise ValueError(f"native direct k-point table is empty in {path}")

    indices = [row[0] for row in rows]
    if indices != list(range(1, len(rows) + 1)):
        raise ValueError(f"native k-point indices are not contiguous in {path}: {indices}")
    if expected_total is not None and expected_total != len(rows):
        raise ValueError(
            f"native k-point count mismatch in {path}: nkstot={expected_total}, table={len(rows)}"
        )

    coordinates = np.asarray([row[1:4] for row in rows], dtype=float)
    weights = np.asarray([row[4] for row in rows], dtype=float)
    if not np.all(np.isfinite(coordinates)) or not np.all(np.isfinite(weights)):
        raise ValueError(f"non-finite native k-point coordinate or weight in {path}")
    if np.any(weights <= 0.0):
        raise ValueError(f"native k-point weights must be positive in {path}")
    weight_sum = float(np.sum(weights))
    weight_half_sum = float(np.sum(np.asarray(weight_half_steps, dtype=float)))

    return {
        "coordinates": coordinates,
        "weights": weights,
        "weight_sum": weight_sum,
        "weight_sum_interval": (weight_sum - weight_half_sum, weight_sum + weight_half_sum),
        "raw_coordinate_tokens": raw_coordinate_tokens,
        "raw_weight_tokens": raw_weight_tokens,
        "coordinate_half_steps": np.asarray(coordinate_half_steps, dtype=float),
        "weight_half_steps": np.asarray(weight_half_steps, dtype=float),
        "expected_total": expected_total,
    }


def _verify_gamma_cartesian_mesh(
    coordinates: np.ndarray,
    mesh: Sequence[int],
    coordinate_half_steps: np.ndarray,
) -> None:
    """Check the Gamma Cartesian product using native print intervals."""

    expected_coordinates = np.asarray(
        [
            (i / int(mesh[0]), j / int(mesh[1]), k / int(mesh[2]))
            for i in range(int(mesh[0]))
            for j in range(int(mesh[1]))
            for k in range(int(mesh[2]))
        ],
        dtype=float,
    )
    if coordinates.shape != expected_coordinates.shape:
        raise ValueError(
            f"native Gamma k-point count {coordinates.shape[0]} does not match mesh {list(mesh)}"
        )
    if coordinate_half_steps.shape != coordinates.shape or not np.all(np.isfinite(coordinate_half_steps)):
        raise ValueError("native Gamma coordinate print intervals have an invalid shape")
    if np.any(coordinate_half_steps < 0.0):
        raise ValueError("native Gamma coordinate print intervals must be non-negative")
    matched: list[int] = []
    for row_index, coordinate in enumerate(coordinates):
        half_steps = coordinate_half_steps[row_index]
        candidates = np.flatnonzero(
            np.all(
                np.abs(expected_coordinates - coordinate[np.newaxis, :])
                <= half_steps[np.newaxis, :],
                axis=1,
            )
        )
        if candidates.size != 1:
            raise ValueError(
                f"native k-point {coordinate.tolist()} is not a unique zero-shift Gamma mesh point"
            )
        index = int(candidates[0])
        if index in matched:
            raise ValueError(
                f"native Gamma Cartesian product contains a duplicate point {coordinate.tolist()}"
            )
        matched.append(index)
    if len(matched) != expected_coordinates.shape[0]:
        raise ValueError("native Gamma Cartesian product is incomplete")


def _parse_istate(path: Path, expected_nspin: int) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish_block(block: dict[str, Any]) -> None:
        rows = block["rows"]
        if not rows:
            raise ValueError(f"empty native istate block for k point {block['kpoint_index']} in {path}")
        expected_bands = list(range(1, len(rows) + 1))
        actual_bands = [row[0] for row in rows]
        if actual_bands != expected_bands:
            raise ValueError(
                f"native band indices are not contiguous for k point {block['kpoint_index']} in {path}: "
                f"{actual_bands[:5]}..."
            )
        blocks.append(block)

    for line in lines:
        header_two = _HEADER_TWO.match(line)
        header_one = _HEADER_ONE.match(line)
        if header_two is not None or header_one is not None:
            if current is not None:
                finish_block(current)
            match = header_two if header_two is not None else header_one
            parsed_nspin = 2 if header_two is not None else 1
            if parsed_nspin != expected_nspin:
                raise ValueError(
                    f"native istate nspin={parsed_nspin} does not match method nspin={expected_nspin}"
                )
            current = {
                "kpoint_index": int(match.group(1)),
                "coordinate": np.asarray(
                    [_as_float(token) for token in match.group(2).split()], dtype=float
                ),
                "rows": [],
                "nspin": parsed_nspin,
            }
            if current["coordinate"].shape != (3,):
                raise ValueError(f"native istate k-point coordinate is not three-dimensional in {path}")
            continue

        if current is None:
            if line.strip():
                raise ValueError(f"unexpected nonempty content before native istate header in {path}: {line!r}")
            continue
        if not line.strip():
            continue
        row_match = (_ROW_TWO if expected_nspin == 2 else _ROW_ONE).match(line)
        if row_match is None:
            raise ValueError(f"invalid or incomplete native istate row in {path}: {line!r}")
        if expected_nspin == 1:
            current["rows"].append(
                (
                    int(row_match.group(1)),
                    _as_float(row_match.group(2)),
                    _as_float(row_match.group(3)),
                )
            )
        else:
            current["rows"].append(
                (
                    int(row_match.group(1)),
                    _as_float(row_match.group(2)),
                    _as_float(row_match.group(3)),
                    _as_float(row_match.group(4)),
                    _as_float(row_match.group(5)),
                )
            )
    if current is not None:
        finish_block(current)
    if not blocks:
        raise ValueError(f"native istate.info has no k-point blocks in {path}")

    indices = [block["kpoint_index"] for block in blocks]
    if indices != list(range(1, len(blocks) + 1)):
        raise ValueError(f"native istate k-point indices are not contiguous in {path}: {indices}")
    band_count = len(blocks[0]["rows"])
    if any(len(block["rows"]) != band_count for block in blocks):
        raise ValueError(f"native istate blocks have inconsistent band counts in {path}")

    energies = np.empty((expected_nspin, len(blocks), band_count), dtype=float)
    occupations = np.empty_like(energies)
    coordinates = np.empty((len(blocks), 3), dtype=float)
    for kpoint_index, block in enumerate(blocks):
        coordinates[kpoint_index] = block["coordinate"]
        for band_index, row in enumerate(block["rows"]):
            if expected_nspin == 1:
                energies[0, kpoint_index, band_index] = row[1]
                occupations[0, kpoint_index, band_index] = row[2]
            else:
                energies[0, kpoint_index, band_index] = row[1]
                occupations[0, kpoint_index, band_index] = row[2]
                energies[1, kpoint_index, band_index] = row[3]
                occupations[1, kpoint_index, band_index] = row[4]
    if not np.all(np.isfinite(energies)) or not np.all(np.isfinite(occupations)):
        raise ValueError(f"native istate energies or occupations are non-finite in {path}")

    return {
        "energies": energies,
        "occupations": occupations,
        "coordinates": coordinates,
        "band_count": band_count,
        "kpoint_count": len(blocks),
    }


def _parse_fermi_and_convergence(
    path: Path, expected_nspin: int
) -> tuple[float, str, float]:
    if not path.is_file():
        raise FileNotFoundError(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    fermi_values: list[float] = []
    nspin_values: list[int] = []
    for line in lines:
        match = _EFERMI.match(line)
        if match is not None:
            fermi_values.append(_as_float(match.group(1)))
        spin_match = _NSPIN_LOG.search(line)
        if spin_match is not None:
            nspin_values.append(int(spin_match.group(1)))
    if not fermi_values:
        raise ValueError(f"final EFERMI line not found in {path}")
    if not nspin_values or nspin_values[-1] != expected_nspin:
        raise ValueError(
            f"native STATE ENERGY nspin marker does not match method nspin={expected_nspin} in {path}"
        )
    if not any("charge density convergence is achieved" in line.lower() for line in lines):
        raise ValueError(f"native electronic convergence marker not found in {path}")
    native_log_electron_count = _native_electron_markers(path)["neutral"]
    return (
        fermi_values[-1],
        "ABACUS final EFERMI line; SCF electronic chemical-potential reference",
        native_log_electron_count,
    )


def _declared_electron_count(
    method: Mapping[str, Any], result: Mapping[str, Any]
) -> tuple[float, str]:
    metadata = method.get("pseudopotential_metadata")
    final_atoms = result.get("final_atoms")
    symbols = final_atoms.get("symbols") if isinstance(final_atoms, Mapping) else None
    if not isinstance(metadata, Mapping):
        raise ValueError("method.pseudopotential_metadata is required for electron-count validation")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("result.final_atoms.symbols is required for electron-count validation")

    total = 0.0
    for symbol in symbols:
        entry = metadata.get(symbol)
        if not isinstance(entry, Mapping) or entry.get("valence_electrons_per_atom") is None:
            raise ValueError(f"missing pseudopotential valence metadata for element {symbol!r}")
        value = float(entry["valence_electrons_per_atom"])
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"invalid pseudopotential valence for {symbol}: {value!r}")
        total += value

    qualification = method.get("input_qualification")
    if qualification is not None:
        if not isinstance(qualification, Mapping):
            raise ValueError("method.input_qualification must be an object when present")
        electron_count = qualification.get("electron_count")
        if not isinstance(electron_count, Mapping):
            raise ValueError("method.input_qualification.electron_count is required when present")
        declared = electron_count.get("neutral_valence_electrons")
        if declared is None:
            raise ValueError("method.input_qualification electron count is missing")
        declared_value = float(declared)
        if not math.isfinite(declared_value) or declared_value < 0.0:
            raise ValueError(f"invalid qualified electron count: {declared!r}")
        if not math.isclose(declared_value, total, rel_tol=0.0, abs_tol=_ELECTRON_COUNT_TOLERANCE):
            raise ValueError(
                "method input qualification electron count does not match "
                f"pseudopotential metadata and atom symbols: {declared_value} != {total}"
            )
    return total, "method.pseudopotential_metadata*result.final_atoms"


def _native_charge_fields(method: Mapping[str, Any], net_charge: int) -> tuple[int | None, int | None]:
    """Read the canonical flattened native charge fields."""

    raw_nelec = method.get("nelec")
    raw_delta = method.get("nelec_delta")
    nelec = None if raw_nelec is None else _integer_charge(raw_nelec, name="method.nelec")
    delta = None if raw_delta is None else _integer_charge(raw_delta, name="method.nelec_delta")
    if net_charge == 0:
        # Historical method records did not carry these fields.  When they are
        # present, however, they still must describe the neutral native input.
        nelec = 0 if nelec is None else nelec
        delta = 0 if delta is None else delta
    return nelec, delta


def _electron_count_contract(
    method: Mapping[str, Any],
    result: Mapping[str, Any],
    input_parameters: Mapping[str, str],
    *,
    require_charged: bool = False,
) -> dict[str, Any]:
    """Validate the MLCC q/delta/native electron-count contract.

    ``neutral_valence_electrons`` comes only from the retained UPF metadata and
    final atom symbols.  ``target_electrons`` is derived as Nneutral-q.  The
    native ABACUS ``nelec=0`` input is therefore intentionally represented by
    ``nelec_delta=-q`` rather than by writing q into ``nelec``.
    """

    neutral, neutral_source = _declared_electron_count(method, result)
    raw_charge = method.get("net_charge")
    net_charge = _integer_charge(raw_charge, name="method.net_charge", default=0)
    delta = -net_charge
    target = neutral - float(net_charge)
    if not math.isfinite(target) or target <= 0.0:
        raise ValueError(f"target electron count must be positive and finite: {target!r}")
    if not math.isclose(target, round(target), rel_tol=0.0, abs_tol=_ELECTRON_COUNT_TOLERANCE):
        raise ValueError(f"target electron count must be integral: {target!r}")
    target = float(round(target))
    if require_charged and net_charge == 0:
        raise ValueError("charged electron validation requires nonzero method.net_charge")

    method_nelec, method_delta = _native_charge_fields(method, net_charge)
    if net_charge != 0 and (method_nelec is None or method_delta is None):
        raise ValueError("charged method must declare flattened nelec=0 and nelec_delta=-net_charge")
    if method_nelec is not None and method_nelec != 0:
        raise ValueError(f"method.nelec must be 0 for the ABACUS delta contract: {method_nelec}")
    if method_delta is not None and method_delta != delta:
        raise ValueError(f"method.nelec_delta must equal -net_charge: {method_delta} != {delta}")

    input_nelec = _optional_integer_field(input_parameters, "nelec")
    input_delta = _optional_integer_field(input_parameters, "nelec_delta")
    if net_charge != 0 and (input_nelec is None or input_delta is None):
        raise ValueError("charged INPUT must declare nelec=0 and nelec_delta=-net_charge")
    if input_nelec is not None and input_nelec != 0:
        raise ValueError(f"INPUT nelec must be 0 for the ABACUS delta contract: {input_nelec}")
    if input_delta is not None and input_delta != delta:
        raise ValueError(f"INPUT nelec_delta must equal -net_charge: {input_delta} != {delta}")

    qualification = method.get("input_qualification")
    qualification_electrons: Mapping[str, Any] | None = None
    if qualification is not None:
        if not isinstance(qualification, Mapping):
            raise ValueError("method.input_qualification must be an object when present")
        raw_electrons = qualification.get("electron_count")
        if raw_electrons is not None and not isinstance(raw_electrons, Mapping):
            raise ValueError("method.input_qualification.electron_count must be an object")
        qualification_electrons = raw_electrons if isinstance(raw_electrons, Mapping) else None
        if qualification_electrons is not None:
            declared_neutral = qualification_electrons.get("neutral_valence_electrons")
            if declared_neutral is None:
                raise ValueError("method.input_qualification electron count is missing neutral_valence_electrons")
            if not math.isclose(float(declared_neutral), neutral, rel_tol=0.0, abs_tol=_ELECTRON_COUNT_TOLERANCE):
                raise ValueError(
                    "method input qualification neutral electron count does not match native metadata: "
                    f"{declared_neutral} != {neutral}"
                )
            if net_charge != 0:
                required_fields = ("target_electrons", "net_charge", "nelec_delta")
                missing = [field for field in required_fields if field not in qualification_electrons]
                if missing:
                    raise ValueError(
                        "charged method input qualification electron count is missing: "
                        + ", ".join(missing)
                    )
            if "target_electrons" in qualification_electrons and not math.isclose(
                float(qualification_electrons["target_electrons"]),
                target,
                rel_tol=0.0,
                abs_tol=_ELECTRON_COUNT_TOLERANCE,
            ):
                raise ValueError("method input qualification target electron count does not match net_charge")
            if "net_charge" in qualification_electrons and _integer_charge(
                qualification_electrons["net_charge"], name="input qualification net_charge"
            ) != net_charge:
                raise ValueError("method input qualification net_charge does not match method.net_charge")
            if "nelec" in qualification_electrons and _integer_charge(
                qualification_electrons["nelec"], name="input qualification nelec"
            ) != 0:
                raise ValueError("method input qualification nelec must be 0")
            if "nelec_delta" in qualification_electrons and _integer_charge(
                qualification_electrons["nelec_delta"], name="input qualification nelec_delta"
            ) != delta:
                raise ValueError("method input qualification nelec_delta does not match -net_charge")

    return {
        "electron_count_neutral": float(neutral),
        "electron_count_neutral_source": neutral_source,
        "electron_count_target": target,
        "net_charge": int(net_charge),
        "nelec": 0 if method_nelec is None else int(method_nelec),
        "nelec_delta": int(delta),
        "method_nelec": method_nelec,
        "method_nelec_delta": method_delta,
        "input_nelec": input_nelec,
        "input_nelec_delta": input_delta,
        "qualification_electron_count": dict(qualification_electrons)
        if qualification_electrons is not None
        else None,
        "charged": net_charge != 0,
    }


def _validate_occupation_weights(
    weighted: np.ndarray, weights: np.ndarray, occupation_capacity: float
) -> tuple[np.ndarray, float, bool]:
    if weighted.ndim != 3 or weighted.shape[1] != weights.shape[0]:
        raise ValueError("occupation array and k-point weights have incompatible shapes")
    normalized = weighted / weights[np.newaxis, :, np.newaxis]
    if not np.all(np.isfinite(normalized)):
        raise ValueError("normalised occupations are non-finite")
    if np.any(weighted < -_OCCUPATION_TOLERANCE) or np.any(
        weighted > occupation_capacity * weights[np.newaxis, :, np.newaxis] + _OCCUPATION_TOLERANCE
    ):
        raise ValueError(
            "native weighted occupations are outside [0, occupation_capacity*k-point weight]"
        )
    if np.any(normalized < -_OCCUPATION_TOLERANCE) or np.any(
        normalized > occupation_capacity + _OCCUPATION_TOLERANCE
    ):
        raise ValueError(f"normalised occupations are outside [0, {occupation_capacity}]")
    normalized = np.clip(normalized, 0.0, occupation_capacity)
    electron_count = float(np.sum(weighted))
    fractional = bool(np.any(np.abs(normalized) > _OCCUPATION_TOLERANCE) and np.any(
        (normalized > _OCCUPATION_TOLERANCE)
        & (normalized < occupation_capacity - _OCCUPATION_TOLERANCE)
    ))
    return normalized, electron_count, fractional


def _validate_native_electron_evidence(
    *,
    native_log: Path,
    native_istate: Path,
    native_kpoints: Path,
    input_mesh: Sequence[int],
    method: Mapping[str, Any],
    contract: Mapping[str, Any],
    expected_nspin: int,
    nbands: int,
) -> dict[str, Any]:
    """Parse and validate one native ABACUS electron-count evidence set."""

    fermi_eV, fermi_reference, native_log_neutral = _parse_fermi_and_convergence(
        native_log, expected_nspin
    )
    markers = _native_electron_markers(native_log)
    if not math.isclose(
        native_log_neutral,
        contract["electron_count_neutral"],
        rel_tol=0.0,
        abs_tol=_ELECTRON_COUNT_TOLERANCE,
    ):
        raise ValueError(
            "native AUTOSET electron count (neutral) does not match metadata: "
            f"{native_log_neutral} != {contract['electron_count_neutral']}"
        )
    native_delta = markers["delta"]
    native_log_target = native_log_neutral
    if contract["charged"]:
        if native_delta is None or markers["target"] is None:
            raise ValueError(
                "charged native log must contain nelec_delta and adjusted nelec now markers"
            )
        if not math.isclose(
            native_delta,
            contract["nelec_delta"],
            rel_tol=0.0,
            abs_tol=_ELECTRON_COUNT_TOLERANCE,
        ):
            raise ValueError(
                "native nelec_delta does not match method charge: "
                f"{native_delta} != {contract['nelec_delta']}"
            )
        native_log_target = float(markers["target"])
        if not math.isclose(
            native_log_target,
            contract["electron_count_target"],
            rel_tol=0.0,
            abs_tol=_ELECTRON_COUNT_TOLERANCE,
        ):
            raise ValueError(
                "native adjusted electron count does not match target electron count: "
                f"{native_log_target} != {contract['electron_count_target']}"
            )
    else:
        if native_delta is not None and not math.isclose(
            native_delta, 0.0, rel_tol=0.0, abs_tol=_ELECTRON_COUNT_TOLERANCE
        ):
            raise ValueError("neutral native log contains nonzero nelec_delta")
        if markers["target"] is not None and not math.isclose(
            float(markers["target"]),
            contract["electron_count_neutral"],
            rel_tol=0.0,
            abs_tol=_ELECTRON_COUNT_TOLERANCE,
        ):
            raise ValueError("neutral native log contains a non-neutral adjusted electron count")

    kpoints = _parse_native_kpoints(native_kpoints)
    istate = _parse_istate(native_istate, expected_nspin)
    if istate["kpoint_count"] != kpoints["coordinates"].shape[0]:
        raise ValueError("native istate and kpoints have different k-point counts")
    if istate["band_count"] != nbands:
        raise ValueError(
            f"native istate band count {istate['band_count']} does not match method nbands {nbands}"
        )
    if len(input_mesh) != 3 or math.prod(input_mesh) != kpoints["coordinates"].shape[0]:
        raise ValueError(
            f"INPUT KPT mesh {list(input_mesh)} does not describe native k-point count "
            f"{kpoints['coordinates'].shape[0]}"
        )
    method_mesh = method.get("kpoints")
    if list(method_mesh or []) != list(input_mesh):
        raise ValueError(f"method/Input KPT mesh mismatch: {method_mesh} != {list(input_mesh)}")
    _verify_gamma_cartesian_mesh(
        kpoints["coordinates"], input_mesh, kpoints["coordinate_half_steps"]
    )
    if not np.allclose(istate["coordinates"], kpoints["coordinates"], rtol=0.0, atol=1.0e-7):
        raise ValueError("native istate and kpoints direct coordinates do not match")
    uniform_weight = 1.0 / len(kpoints["weights"])
    weight_half_steps = kpoints["weight_half_steps"]
    if np.any(
        np.abs(kpoints["weights"] - uniform_weight) > weight_half_steps
    ):
        raise ValueError(
            "native k-point weights are not a uniform mesh within their native print intervals"
        )
    weight_sum_interval = kpoints["weight_sum_interval"]
    if not weight_sum_interval[0] <= 1.0 <= weight_sum_interval[1]:
        raise ValueError(
            "native k-point weight print intervals cannot contain a unit weight sum: "
            f"{weight_sum_interval}"
        )
    uniform_weights = np.full_like(kpoints["weights"], uniform_weight)
    kpoints["uniform_reference_weights"] = uniform_weights

    occupation_capacity = 2.0 if expected_nspin == 1 else 1.0
    normalized, native_electron_count, fractional = _validate_occupation_weights(
        istate["occupations"], kpoints["uniform_reference_weights"], occupation_capacity
    )
    if contract["charged"] and fractional:
        raise ValueError("charged first-slice fixed SCF has fractional native occupations")
    native_log_abs_error = abs(native_electron_count - native_log_target)
    if native_log_abs_error > _ELECTRON_COUNT_TOLERANCE:
        raise ValueError(
            "weighted native occupation count does not match the native target electron count marker: "
            f"{native_electron_count} != {native_log_target}"
        )
    declared_target_abs_error = abs(native_electron_count - contract["electron_count_target"])
    if declared_target_abs_error > _ELECTRON_COUNT_TOLERANCE:
        raise ValueError(
            "native electron count does not match the declared target electron count: "
            f"{native_electron_count} != {contract['electron_count_target']}"
        )
    return {
        "fermi_eV": fermi_eV,
        "fermi_reference": fermi_reference,
        "native_log_neutral": native_log_neutral,
        "native_log_target": native_log_target,
        "native_delta": native_delta,
        "kpoints": kpoints,
        "istate": istate,
        "normalized": normalized,
        "native_electron_count": native_electron_count,
        "fractional": fractional,
        "native_log_abs_error": native_log_abs_error,
        "declared_target_abs_error": declared_target_abs_error,
    }


def _locations_and_gap(
    energies: np.ndarray,
    normalized: np.ndarray,
    spin_channels: Sequence[str],
    occupation_capacity: float,
) -> tuple[float | None, float | None, float | None, dict[str, Any] | None, dict[str, Any] | None]:
    occupied = normalized > occupation_capacity / 2.0
    unoccupied = normalized <= occupation_capacity / 2.0
    if not np.any(occupied) or not np.any(unoccupied):
        return None, None, None, None, None
    occupied_energies = np.where(occupied, energies, -np.inf)
    unoccupied_energies = np.where(unoccupied, energies, np.inf)
    vbm_flat = int(np.argmax(occupied_energies))
    cbm_flat = int(np.argmin(unoccupied_energies))
    vbm_index = np.unravel_index(vbm_flat, energies.shape)
    cbm_index = np.unravel_index(cbm_flat, energies.shape)

    def location(index: tuple[int, int, int]) -> dict[str, Any]:
        spin, kpoint, band = index
        return {
            "spin_index": int(spin),
            "spin_channel": spin_channels[spin],
            "kpoint_index": int(kpoint + 1),
            "band_index": int(band + 1),
        }

    vbm = float(energies[vbm_index])
    cbm = float(energies[cbm_index])
    return vbm, cbm, cbm - vbm, location(vbm_index), location(cbm_index)


def read_abacus_electronic_task(task_path: str | Path) -> dict[str, Any]:
    """Read and qualify native electronic levels for one completed ABACUS SCF.

    The returned arrays use ``[spin][kpoint][band]`` order.  Energies are in
    eV.  ``weighted_occupations`` are the values printed by ABACUS and
    ``normalized_occupations`` divide each k-point column by its native k-point
    weight.  The gap, when available, is a sampled uniform-mesh Kohn-Sham gap;
    it is never labelled a fundamental or band-path gap and is never precision
    qualified by this function.
    """

    task_dir = Path(task_path).expanduser().resolve()
    if not task_dir.is_dir():
        raise FileNotFoundError(task_dir)
    task = _read_json(task_dir / "task.json")
    result = _read_json(task_dir / "result.json")
    method = _read_json(task_dir / "method.json")
    input_parameters = _parse_input(task_dir / "INPUT")
    input_mesh, input_shift = _parse_input_kmesh(task_dir / "KPT")

    if task.get("engine") != "abacus":
        raise ValueError(f"task engine must be abacus: {task.get('engine')!r}")
    if task.get("engine_version") != ABACUS_VERSION:
        raise ValueError(f"task ABACUS version must be {ABACUS_VERSION}: {task.get('engine_version')!r}")
    if str(task.get("calculation", "")).lower() != "scf":
        raise ValueError(f"electronic extraction requires an SCF task: {task.get('calculation')!r}")
    if str(task.get("status", "")).upper() != "COMPLETED":
        raise ValueError(f"task scheduler status is not COMPLETED: {task.get('status')!r}")
    if str(task.get("scheduler_state", "")).upper() != "COMPLETED":
        raise ValueError(f"task scheduler state is not COMPLETED: {task.get('scheduler_state')!r}")
    if task.get("exit_code") != "0:0":
        raise ValueError(f"task scheduler exit code is not 0:0: {task.get('exit_code')!r}")

    _require_equal("result.task_id", result.get("task_id"), task.get("task_id"))
    _require_equal("result.scheduler_job_id", result.get("scheduler_job_id"), task.get("scheduler_job_id"))
    _require_equal("result.method_set", result.get("method_set"), task.get("method_set"))
    _require_equal("method.method_set", method.get("method_set"), task.get("method_set"))
    if task.get("model_id") is None or task.get("model_version") is None:
        raise ValueError("task.model_id and task.model_version are required")
    _require_equal("method.model_id", method.get("model_id"), task.get("model_id"))
    _require_equal("method.version", method.get("version"), task.get("model_version"))
    if str(result.get("stage", "")).lower() != "scf":
        raise ValueError(f"result stage must be scf: {result.get('stage')!r}")
    if result.get("electronic_converged") is not True:
        raise ValueError("result does not declare electronic_converged=true")
    parent_energy_zero_eV = result.get("energy_eV")
    if not isinstance(parent_energy_zero_eV, (int, float)) or not math.isfinite(float(parent_energy_zero_eV)):
        raise ValueError("result.energy_eV is required as the parent energy reference")
    parent_energy_zero_definition = result.get("energy_definition") or result.get(
        "energy_default_definition"
    )
    if not isinstance(parent_energy_zero_definition, str) or not parent_energy_zero_definition:
        raise ValueError("result energy definition is required as the parent energy reference")

    if method.get("engine") != "abacus":
        raise ValueError(f"method engine must be abacus: {method.get('engine')!r}")
    if str(method.get("stage", "")).lower() != "scf":
        raise ValueError(f"method stage must be scf: {method.get('stage')!r}")
    method_version = method.get("abacus_version_target", method.get("engine_version"))
    if method_version != ABACUS_VERSION:
        raise ValueError(f"method ABACUS version must be {ABACUS_VERSION}: {method_version!r}")
    nspin = method.get("nspin")
    if nspin not in (1, 2):
        raise ValueError(f"method nspin must be 1 or 2: {nspin!r}")
    occupations = method.get("occupations")
    if occupations not in ("fixed", "smearing"):
        raise ValueError(f"method occupations must be fixed or smearing: {occupations!r}")
    if result.get("occupations") != occupations:
        raise ValueError(f"result/method occupations mismatch: {result.get('occupations')!r} != {occupations!r}")

    input_nspin = int(input_parameters.get("nspin", "-1"))
    if input_nspin != nspin:
        raise ValueError(f"INPUT/method nspin mismatch: {input_nspin} != {nspin}")
    input_calculation = input_parameters.get("calculation", "").lower()
    if input_calculation != "scf":
        raise ValueError(f"INPUT calculation must be scf: {input_calculation!r}")
    method_parameters = method.get("parameters")
    if not isinstance(method_parameters, Mapping):
        raise ValueError("method.parameters is required")
    nbands = int(method_parameters.get("nbands", -1))
    if nbands <= 0 or int(input_parameters.get("nbands", "-1")) != nbands:
        raise ValueError("INPUT/method nbands mismatch or invalid nbands")
    method_smearing = method.get("smearing_method")
    input_smearing = input_parameters.get("smearing_method")
    if occupations == "fixed":
        if input_smearing != "fixed" or method_smearing not in (None, "fixed"):
            raise ValueError("fixed occupation task must have smearing_method=fixed in method and INPUT")
        if method_parameters.get("smearing_sigma_Ry") is not None or "smearing_sigma" in input_parameters:
            raise ValueError("fixed occupation task must not declare a smearing sigma")
    else:
        if not isinstance(method_smearing, str) or input_smearing != method_smearing:
            raise ValueError("smearing method mismatch between method and INPUT")
        method_sigma = method_parameters.get("smearing_sigma_Ry")
        input_sigma = input_parameters.get("smearing_sigma")
        if method_sigma is None or input_sigma is None:
            raise ValueError("finite-smearing task must declare smearing_sigma in method and INPUT")
        if not math.isclose(float(method_sigma), float(input_sigma), rel_tol=0.0, abs_tol=1.0e-10):
            raise ValueError("smearing sigma mismatch between method and INPUT")

    electron_contract = _electron_count_contract(method, result, input_parameters)
    for label, mapping in (("task", task), ("result", result)):
        if "net_charge" in mapping:
            recorded = _integer_charge(mapping.get("net_charge"), name=f"{label}.net_charge")
            if recorded != electron_contract["net_charge"]:
                raise ValueError(
                    f"{label}.net_charge does not match method.net_charge: "
                    f"{recorded} != {electron_contract['net_charge']}"
                )
        if "nelec" in mapping:
            recorded = _integer_charge(mapping.get("nelec"), name=f"{label}.nelec")
            if recorded != electron_contract["nelec"]:
                raise ValueError(f"{label}.nelec does not match method.nelec")
        if "nelec_delta" in mapping:
            recorded = _integer_charge(mapping.get("nelec_delta"), name=f"{label}.nelec_delta")
            if recorded != electron_contract["nelec_delta"]:
                raise ValueError(f"{label}.nelec_delta does not match method.nelec_delta")
    if electron_contract["charged"]:
        if nspin != 1 or occupations != "fixed":
            raise ValueError("charged electronic extraction requires nspin=1 fixed occupations")
        for field in ("lspinorb", "noncolin"):
            if method.get(field) is not False:
                raise ValueError(f"charged electronic extraction requires {field}=false")
            if field not in input_parameters or _integer_charge(
                input_parameters[field], name=f"INPUT {field}"
            ) != 0:
                raise ValueError(f"charged electronic extraction requires INPUT {field}=0")
        target = electron_contract["electron_count_target"]
        if not math.isclose(target / 2.0, round(target / 2.0), rel_tol=0.0, abs_tol=_ELECTRON_COUNT_TOLERANCE):
            raise ValueError("charged nspin=1 fixed occupations require an even target electron count")
        if "nupdown" in input_parameters:
            raise ValueError("charged first-slice SCF must not declare nupdown")
        gate_flag = input_parameters.get("gate_flag")
        if gate_flag is not None and _integer_charge(gate_flag, name="INPUT gate_flag") != 0:
            raise ValueError("charged first-slice SCF requires gate_flag=0 or an omitted gate_flag")
        if input_parameters.get("smearing_method", "").lower() != "fixed":
            raise ValueError("charged first-slice SCF requires INPUT smearing_method=fixed")
        if "smearing_sigma" in input_parameters:
            raise ValueError("charged first-slice fixed SCF must not declare smearing_sigma")
        if method_smearing not in (None, "fixed"):
            raise ValueError("charged first-slice fixed SCF requires method smearing_method=fixed or null")

    native_dir = _native_output_dir(task_dir, result, method)
    native_log = native_dir / "running_scf.log"
    native_istate = native_dir / "istate.info"
    native_kpoints = native_dir / "kpoints"
    native_evidence = _validate_native_electron_evidence(
        native_log=native_log,
        native_istate=native_istate,
        native_kpoints=native_kpoints,
        input_mesh=input_mesh,
        method=method,
        contract=electron_contract,
        expected_nspin=nspin,
        nbands=nbands,
    )
    fermi_eV = native_evidence["fermi_eV"]
    fermi_reference = native_evidence["fermi_reference"]
    native_log_electron_count = native_evidence["native_log_neutral"]
    native_log_target_electron_count = native_evidence["native_log_target"]
    native_delta = native_evidence["native_delta"]
    kpoints = native_evidence["kpoints"]
    istate = native_evidence["istate"]
    normalized = native_evidence["normalized"]
    native_electron_count = native_evidence["native_electron_count"]
    fractional = native_evidence["fractional"]
    native_log_electron_count_abs_error = native_evidence["native_log_abs_error"]
    native_log_electron_count_match = native_log_electron_count_abs_error <= _ELECTRON_COUNT_TOLERANCE
    declared_electron_count = electron_contract["electron_count_neutral"]
    declared_source = electron_contract["electron_count_neutral_source"]
    electron_count_abs_error = native_evidence["declared_target_abs_error"]
    electron_count_match = electron_count_abs_error <= _ELECTRON_COUNT_TOLERANCE

    occupation_capacity = 2.0 if nspin == 1 else 1.0
    spin_channels = ["up"] if nspin == 1 else ["up", "down"]
    vbm_eV: float | None = None
    cbm_eV: float | None = None
    gap_eV: float | None = None
    vbm_location: dict[str, Any] | None = None
    cbm_location: dict[str, Any] | None = None
    if occupations == "fixed" and not fractional:
        vbm_eV, cbm_eV, gap_eV, vbm_location, cbm_location = _locations_and_gap(
            istate["energies"], normalized, spin_channels, occupation_capacity
        )
        if gap_eV is None:
            gap_status = "unavailable_without_both_occupied_and_unoccupied_states"
            gap_reason = "fixed occupations did not provide both occupied and unoccupied levels"
        else:
            gap_status = "sampled_mesh_KS_gap"
            gap_reason = "fixed integer occupations on the native uniform SCF mesh"
    elif occupations == "smearing":
        gap_status = "unavailable_finite_smearing"
        gap_reason = "finite_smearing_partial_occupations; no sampled-mesh gap is reported"
    else:
        gap_status = "unavailable_non_integer_fixed_occupations"
        gap_reason = "fixed-occupation native levels were not integer full/empty"

    source_files = {
        "task.json": str(task_dir / "task.json"),
        "result.json": str(task_dir / "result.json"),
        "method.json": str(task_dir / "method.json"),
        "INPUT": str(task_dir / "INPUT"),
        "KPT": str(task_dir / "KPT"),
        "running_scf.log": str(native_log),
        "istate.info": str(native_istate),
        "kpoints": str(native_kpoints),
    }
    return {
        "schema": "mlcc.abacus-electronic.v001",
        "task_id": task["task_id"],
        "scheduler_job_id": task["scheduler_job_id"],
        "method_set": task["method_set"],
        "model_id": task.get("model_id"),
        "model_version": task.get("model_version"),
        "engine": "abacus",
        "engine_version": ABACUS_VERSION,
        "parent_energy_zero_eV": float(parent_energy_zero_eV),
        "parent_energy_zero_definition": parent_energy_zero_definition,
        "parent_fermi_level_eV": fermi_eV,
        "stage": "scf",
        "native_completed": True,
        "native_exit_code": "0:0",
        "electronic_converged": True,
        "scientific_qualification": False,
        "production_qualification": False,
        "nspin": nspin,
        "spin_channels": spin_channels,
        "spin_degeneracy": 2 if nspin == 1 else 1,
        "occupation_capacity_per_spin_channel": occupation_capacity,
        "occupations": occupations,
        "smearing_method": method_smearing,
        "smearing_sigma_Ry": (
            None if occupations == "fixed" else float(method_parameters["smearing_sigma_Ry"])
        ),
        "kpoint_coordinate_system": "direct_reciprocal_lattice",
        "kpoint_coordinates": kpoints["coordinates"].tolist(),
        "kpoint_weights": kpoints["weights"].tolist(),
        "kpoint_weight_sum": kpoints["weight_sum"],
        "kpoint_weight_sum_print_interval": list(kpoints["weight_sum_interval"]),
        "kpoint_weights_uniform_reference": kpoints["uniform_reference_weights"].tolist(),
        "kpoint_weight_reference_rule": (
            "exact 1/N after native printed weight intervals prove the declared complete "
            "uniform Gamma mesh; native printed weights remain in kpoint_weights"
        ),
        "kpoint_mesh": input_mesh,
        "kpoint_mesh_shift": input_shift,
        "kpoint_mesh_rule": "K_POINTS/0/Gamma with zero shift; complete Cartesian product",
        "uniform_kmesh_verified": True,
        "band_indices": list(range(1, nbands + 1)),
        "array_order": "spin,kpoint,band",
        "band_energies_eV": istate["energies"].tolist(),
        "weighted_occupations": istate["occupations"].tolist(),
        "normalized_occupations": normalized.tolist(),
        "occupation_normalization": (
            "native istate.info occupation divided by the verified uniform reference "
            "weights (exact 1/N), accepted only after native printed weight intervals "
            "prove the complete uniform Gamma mesh; raw rounded native weights remain "
            "in kpoint_weights; nspin=1 full occupancy is 2 and nspin=2 full occupancy is 1"
        ),
        "electron_count_native": native_electron_count,
        "electron_count_neutral": electron_contract["electron_count_neutral"],
        "electron_count_neutral_source": electron_contract["electron_count_neutral_source"],
        "electron_count_target": electron_contract["electron_count_target"],
        "electron_count_net_charge": electron_contract["net_charge"],
        "electron_count_nelec": electron_contract["nelec"],
        "electron_count_nelec_delta": electron_contract["nelec_delta"],
        "electron_count_native_log": native_log_electron_count,
        "electron_count_native_log_source": "running_scf.log AUTOSET number of electrons",
        "electron_count_native_log_abs_error": native_log_electron_count_abs_error,
        "electron_count_native_log_match": native_log_electron_count_match,
        "electron_count_native_log_neutral": native_log_electron_count,
        "electron_count_native_log_target": native_log_target_electron_count,
        "electron_count_log_neutral": native_log_electron_count,
        "electron_count_log_target": native_log_target_electron_count,
        "electron_count_native_log_adjusted_source": (
            "running_scf.log nelec now marker"
            if electron_contract["charged"]
            else "running_scf.log AUTOSET number of electrons"
        ),
        "electron_count_native_delta": native_delta,
        "electron_count_q": electron_contract["net_charge"],
        "electron_count_delta": electron_contract["nelec_delta"],
        "electron_count_native_delta_source": (
            "running_scf.log nelec_delta marker" if native_delta is not None else None
        ),
        "electron_count_native_log_neutral_match": abs(
            electron_contract["electron_count_neutral"] - native_log_electron_count
        )
        <= _ELECTRON_COUNT_TOLERANCE,
        "electron_count_native_log_target_match": native_log_electron_count_match,
        "electron_count_declared": declared_electron_count,
        "electron_count_declared_source": declared_source,
        "electron_count_declared_target": electron_contract["electron_count_target"],
        "electron_count_abs_error": electron_count_abs_error,
        "electron_count_tolerance": _ELECTRON_COUNT_TOLERANCE,
        "electron_count_match": electron_count_match,
        "fermi_level_eV": fermi_eV,
        "fermi_reference": fermi_reference,
        "sampled_mesh_KS_gap_eV": gap_eV,
        "vbm_eV": vbm_eV,
        "cbm_eV": cbm_eV,
        "vbm_location": vbm_location,
        "cbm_location": cbm_location,
        "vbm_reference": (
            "sampled charged level; not defect-aligned VBM"
            if electron_contract["charged"]
            else "sampled native uniform-mesh level"
        ),
        "gap_status": gap_status,
        "gap_reason": gap_reason,
        "gap_qualification": {
            "definition": "minimum unoccupied level minus maximum occupied level on the native uniform SCF mesh",
            "is_fundamental_gap": False,
            "is_band_path_gap": False,
            "is_defect_aligned_vbm": False,
            "charged_reference_aligned": False if electron_contract["charged"] else None,
            "charged_vbm_alignment": "not_performed" if electron_contract["charged"] else None,
            "precision_qualified": False,
            "scope": "sampled_mesh_KS_gap only",
        },
        "fractional_occupations_present": fractional,
        "source_files": source_files,
        "native_format": "ABACUS istate.info plus native kpoints and running_scf.log",
        "qualification": {
            "status": (
                "raw_charged_scf_unqualified"
                if electron_contract["charged"]
                else "raw_native_electronic_extraction"
            ),
            "scientific_precision_qualified": False,
            "scientific_qualification": False,
            "production_qualification": False,
            "charged_scf": electron_contract["charged"],
            "historical_result_unchanged": True,
        },
    }


def validate_charged_scf_electrons(
    task_directory: str | Path,
    method_mapping: Mapping[str, Any],
    parsed_result_mapping: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate native electron-count evidence for the first charged SCF slice.

    This helper is intentionally independent of ``task.json`` and
    ``result.json`` serialization so :mod:`mlcc.abacus_tasks` can call it while
    assembling a result.  It reads the real ``INPUT``, ``KPT`` and ABACUS
    ``OUT.<suffix>`` files, validates weighted occupations, and returns raw
    evidence only.  It does not compute a defect formation energy, VBM
    alignment, dielectric correction, or any other charged-defect property.
    """

    task_dir = Path(task_directory).expanduser().resolve()
    if not task_dir.is_dir():
        raise FileNotFoundError(task_dir)
    if not isinstance(method_mapping, Mapping):
        raise TypeError("method_mapping must be a mapping")
    if not isinstance(parsed_result_mapping, Mapping):
        raise TypeError("parsed_result_mapping must be a mapping")

    input_parameters = _parse_input(task_dir / "INPUT")
    contract = _electron_count_contract(
        method_mapping,
        parsed_result_mapping,
        input_parameters,
        require_charged=True,
    )
    if parsed_result_mapping.get("electronic_converged") is not True:
        raise ValueError("charged electron validation requires parsed electronic_converged=true")
    for field in ("lspinorb", "noncolin"):
        if method_mapping.get(field) is not False:
            raise ValueError(f"charged electron validation requires {field}=false")
    if str(method_mapping.get("stage", "scf")).lower() != "scf":
        raise ValueError("charged electron validation requires a fixed-cell SCF method")
    if method_mapping.get("nspin") != 1 or method_mapping.get("occupations") != "fixed":
        raise ValueError("charged electron validation requires nspin=1 fixed occupations")
    target = float(contract["electron_count_target"])
    if not math.isclose(target / 2.0, round(target / 2.0), rel_tol=0.0, abs_tol=_ELECTRON_COUNT_TOLERANCE):
        raise ValueError("charged nspin=1 fixed occupations require an even target electron count")
    if input_parameters.get("calculation", "").lower() != "scf":
        raise ValueError("charged electron validation requires INPUT calculation=scf")
    if int(input_parameters.get("nspin", "-1")) != 1:
        raise ValueError("charged electron validation requires INPUT nspin=1")
    for field in ("lspinorb", "noncolin"):
        if field not in input_parameters or _integer_charge(
            input_parameters[field], name=f"INPUT {field}"
        ) != 0:
            raise ValueError(f"charged electron validation requires INPUT {field}=0")
    if "nupdown" in input_parameters:
        raise ValueError("charged first-slice SCF must not declare nupdown")
    gate_flag = input_parameters.get("gate_flag")
    if gate_flag is not None and _integer_charge(gate_flag, name="INPUT gate_flag") != 0:
        raise ValueError("charged first-slice SCF requires gate_flag=0 or an omitted gate_flag")
    if input_parameters.get("smearing_method", "").lower() != "fixed":
        raise ValueError("charged first-slice SCF requires INPUT smearing_method=fixed")
    if "smearing_sigma" in input_parameters:
        raise ValueError("charged first-slice fixed SCF must not declare smearing_sigma")
    if method_mapping.get("smearing_method") not in (None, "fixed"):
        raise ValueError("charged first-slice fixed SCF requires method smearing_method=fixed or null")

    method_parameters = method_mapping.get("parameters")
    if not isinstance(method_parameters, Mapping):
        raise ValueError("method.parameters is required for charged electron validation")
    nbands = int(method_parameters.get("nbands", -1))
    if nbands <= 0 or int(input_parameters.get("nbands", "-1")) != nbands:
        raise ValueError("charged INPUT/method nbands mismatch or invalid nbands")

    suffix = method_mapping.get("suffix")
    if not isinstance(suffix, str) or not suffix:
        raise ValueError("method.suffix is required for charged electron validation")
    native_dir = task_dir / f"OUT.{suffix}"
    native_log = native_dir / "running_scf.log"
    native_istate = native_dir / "istate.info"
    native_kpoints = native_dir / "kpoints"
    input_mesh, input_shift = _parse_input_kmesh(task_dir / "KPT")
    native_evidence = _validate_native_electron_evidence(
        native_log=native_log,
        native_istate=native_istate,
        native_kpoints=native_kpoints,
        input_mesh=input_mesh,
        method=method_mapping,
        contract=contract,
        expected_nspin=1,
        nbands=nbands,
    )
    fermi_eV = native_evidence["fermi_eV"]
    native_autoset = native_evidence["native_log_neutral"]
    native_target = native_evidence["native_log_target"]
    native_delta = native_evidence["native_delta"]
    kpoints = native_evidence["kpoints"]
    istate = native_evidence["istate"]
    native_occupation_count = native_evidence["native_electron_count"]
    fractional = native_evidence["fractional"]
    return {
        "status": "raw_charged_scf_unqualified",
        "scientific_precision_qualified": False,
        "scientific_qualification": False,
        "production_qualification": False,
        "task_directory": str(task_dir),
        "native_log": str(native_log),
        "native_fermi_level_eV": fermi_eV,
        "electron_count_neutral": contract["electron_count_neutral"],
        "electron_count_target": target,
        "electron_count_native_log_neutral": native_autoset,
        "electron_count_native_log_target": native_target,
        "electron_count_log_neutral": native_autoset,
        "electron_count_log_target": native_target,
        "electron_count_native": native_occupation_count,
        "net_charge": contract["net_charge"],
        "nelec": contract["nelec"],
        "nelec_delta": contract["nelec_delta"],
        "electron_count_q": contract["net_charge"],
        "electron_count_delta": contract["nelec_delta"],
        "native_nelec_delta": native_delta,
        "input_kpoint_mesh": input_mesh,
        "input_kpoint_shift": input_shift,
        "native_kpoint_count": int(kpoints["coordinates"].shape[0]),
        "native_band_count": int(istate["band_count"]),
        "fractional_occupations_present": fractional,
        "electron_count_match": True,
        "vbm_reference": "sampled charged levels are not defect-aligned VBM data",
    }


def gaussian_dos(
    electronic: Mapping[str, Any], energy_grid_eV: Sequence[float], sigma_eV: float
) -> dict[str, Any]:
    """Return explicitly Gaussian-smoothed DOS for every parsed eigenlevel.

    The parser's k-point weights are applied once per level.  NSPIN=1 carries
    one channel with an implicit degeneracy of two; NSPIN=2 carries two
    explicit channels with degeneracy one each.  The result is a DOS per cell,
    not an LDOS and not a precision-qualified observable.
    """

    grid = np.asarray(energy_grid_eV, dtype=float)
    if grid.ndim != 1 or grid.size < 2 or not np.all(np.isfinite(grid)):
        raise ValueError("energy_grid_eV must be a finite one-dimensional grid with at least two points")
    if np.any(np.diff(grid) <= 0.0):
        raise ValueError("energy_grid_eV must be strictly increasing")
    sigma = float(sigma_eV)
    if not math.isfinite(sigma) or sigma <= 0.0:
        raise ValueError("sigma_eV must be finite and positive")

    nspin = electronic.get("nspin")
    if nspin not in (1, 2) or isinstance(nspin, bool):
        raise ValueError("electronic nspin must be exactly 1 or 2")
    expected_channels = ["up"] if nspin == 1 else ["up", "down"]
    expected_degeneracy = 2.0 if nspin == 1 else 1.0
    expected_occupation_capacity = 2.0 if nspin == 1 else 1.0
    spin_channels = electronic.get("spin_channels")
    if spin_channels != expected_channels:
        raise ValueError(
            f"electronic spin_channels must be {expected_channels!r} for nspin={nspin}"
        )
    identity_fields = (
        "task_id",
        "scheduler_job_id",
        "method_set",
        "model_id",
        "model_version",
        "source_files",
    )
    for field in identity_fields:
        if field not in electronic or electronic[field] in (None, ""):
            raise ValueError(f"electronic {field} is required for DOS provenance")
    if not isinstance(electronic["source_files"], Mapping):
        raise ValueError("electronic source_files must be an object for DOS provenance")
    fermi_level_eV = electronic.get("fermi_level_eV")
    if not isinstance(fermi_level_eV, (int, float)) or not math.isfinite(float(fermi_level_eV)):
        raise ValueError("electronic fermi_level_eV is required for DOS provenance")
    parent_energy_zero_eV = electronic.get("parent_energy_zero_eV")
    if not isinstance(parent_energy_zero_eV, (int, float)) or not math.isfinite(
        float(parent_energy_zero_eV)
    ):
        raise ValueError("electronic parent_energy_zero_eV is required for DOS provenance")
    parent_energy_zero_definition = electronic.get("parent_energy_zero_definition")
    if not isinstance(parent_energy_zero_definition, str) or not parent_energy_zero_definition:
        raise ValueError("electronic parent_energy_zero_definition is required for DOS provenance")

    energies = np.asarray(electronic["band_energies_eV"], dtype=float)
    weights = np.asarray(
        electronic.get("kpoint_weights_uniform_reference", electronic["kpoint_weights"]),
        dtype=float,
    )
    if energies.ndim != 3:
        raise ValueError("electronic band_energies_eV must have [spin][kpoint][band] shape")
    if energies.shape[0] != nspin:
        raise ValueError("electronic nspin does not match band_energies_eV spin channels")
    if weights.ndim != 1 or energies.shape[1] != weights.size:
        raise ValueError("electronic band energies and k-point weights have incompatible shapes")
    if not np.all(np.isfinite(energies)) or not np.all(np.isfinite(weights)) or np.any(weights <= 0.0):
        raise ValueError("electronic band energies and k-point weights must be finite and positive")
    if not math.isclose(float(np.sum(weights)), 1.0, rel_tol=0.0, abs_tol=_WEIGHT_SUM_TOLERANCE):
        raise ValueError("electronic k-point weights must sum to one")

    spin_degeneracy = electronic.get("spin_degeneracy")
    if not isinstance(spin_degeneracy, (int, float)) or isinstance(spin_degeneracy, bool):
        raise ValueError("electronic spin_degeneracy is required")
    if float(spin_degeneracy) != expected_degeneracy:
        raise ValueError(
            f"electronic spin_degeneracy must be {expected_degeneracy:g} for nspin={nspin}"
        )
    occupation_capacity = electronic.get("occupation_capacity_per_spin_channel")
    if not isinstance(occupation_capacity, (int, float)) or isinstance(occupation_capacity, bool):
        raise ValueError("electronic occupation capacity is required")
    if float(occupation_capacity) != expected_occupation_capacity:
        raise ValueError(
            "electronic occupation capacity does not match nspin and spin degeneracy"
        )
    level_energies = energies.reshape(-1)
    spin_channel_count = energies.shape[0]
    level_weights = np.broadcast_to(weights[np.newaxis, :, np.newaxis], energies.shape).reshape(-1)
    if spin_channel_count == 1:
        level_weights = level_weights * spin_degeneracy
    gaussian_prefactor = 1.0 / (sigma * math.sqrt(2.0 * math.pi))
    differences = (grid[:, np.newaxis] - level_energies[np.newaxis, :]) / sigma
    dos = gaussian_prefactor * np.sum(
        np.exp(-0.5 * differences * differences) * level_weights[np.newaxis, :], axis=1
    )
    finite_integral = float(np.trapezoid(dos, grid))
    weighted_state_count = float(np.sum(level_weights))
    integral_error = finite_integral - weighted_state_count
    relative_error = integral_error / weighted_state_count if weighted_state_count else None
    return {
        "schema": "mlcc.abacus-electronic-dos.v001",
        "task_id": electronic["task_id"],
        "scheduler_job_id": electronic["scheduler_job_id"],
        "method_set": electronic["method_set"],
        "model_id": electronic["model_id"],
        "model_version": electronic["model_version"],
        "source_files": dict(electronic["source_files"]),
        "parent_energy_zero_eV": float(parent_energy_zero_eV),
        "parent_energy_zero_definition": parent_energy_zero_definition,
        "fermi_level_eV": float(fermi_level_eV),
        "energy_grid_eV": grid.tolist(),
        "sigma_eV": sigma,
        "dos_states_per_eV_per_cell": dos.tolist(),
        "unit": "states/eV/cell",
        "spin_channels": electronic.get("spin_channels"),
        "spin_channel_count": int(energies.shape[0]),
        "spin_degeneracy": spin_degeneracy,
        "kpoint_weight_normalization": "each eigenlevel carries its native k-point weight; nspin=1 implicit spin degeneracy is applied once, while explicit nspin=2 channels are summed",
        "include_occupied_and_unoccupied": True,
        "is_ldos": False,
        "weighted_state_count": weighted_state_count,
        "finite_grid_integral_states_per_cell": finite_integral,
        "finite_grid_integral_error_states_per_cell": integral_error,
        "finite_grid_integral_relative_error": relative_error,
        "energy_window_eV": [float(grid[0]), float(grid[-1])],
        "band_window_eV": [float(np.min(level_energies)), float(np.max(level_energies))],
        "status": "explicit_gaussian_smoothing_only",
        "precision_qualified": False,
    }
