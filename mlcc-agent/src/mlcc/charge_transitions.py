"""Exact affine charge-state envelopes.

This module is deliberately a mathematical postprocessor.  It consumes the
explicit terms returned by :func:`mlcc.defect_thermodynamics.formation_energy_terms`
and does not inspect files, sample ``curve`` values, or infer a band gap.

All comparisons are made with :class:`fractions.Fraction`.  The public result
uses floats for JSON-friendly coordinates, so a very narrow exact interval can
have two equal displayed float endpoints while still being reported as an
``interval``.  The classification is performed before that conversion.

The outer adapter is responsible for consistent host and defect identity,
method, chemical-potential point, and VBM/reference provenance.  This module
does not infer or judge any of those scientific identities.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any


__all__ = ["charge_transition_envelope"]


_SCHEMA = "mlcc.formation-energy.v1"


def _finite_fraction(value: Any, *, name: str) -> Fraction:
    """Convert one finite numeric value without introducing a tolerance."""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number")
    return Fraction(value)


def _integer(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _charges(line_by_id: Mapping[str, Mapping[str, Any]], record_ids: Sequence[str]) -> list[int]:
    return sorted({int(line_by_id[record_id]["q"]) for record_id in record_ids}, reverse=True)


def _minimum_ids(
    lines: Sequence[Mapping[str, Any]],
    x: Fraction,
) -> tuple[Fraction, list[str]]:
    values = [(line["intercept"] + line["q"] * x, line["record_id"]) for line in lines]
    minimum = min(value for value, _ in values)
    return minimum, [record_id for value, record_id in values if value == minimum]


def _stable_interval(
    lines: Sequence[Mapping[str, Any]],
    line: Mapping[str, Any],
    lower_domain: Fraction,
    upper_domain: Fraction,
) -> tuple[Fraction, Fraction] | None:
    """Intersect ``line <= every other line`` over the supplied domain."""

    lower = lower_domain
    upper = upper_domain
    for other in lines:
        if other is line:
            continue
        slope_difference = line["q"] - other["q"]
        intercept_difference = other["intercept"] - line["intercept"]
        if slope_difference == 0:
            if intercept_difference < 0:
                return None
            continue
        crossing = intercept_difference / slope_difference
        if slope_difference > 0:
            if crossing < upper:
                upper = crossing
        else:
            if crossing > lower:
                lower = crossing
        if lower > upper:
            return None
    return lower, upper


def _same_charge_groups(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for line in lines:
        grouped.setdefault(line["q"], []).append(line)
    groups: list[dict[str, Any]] = []
    for charge in sorted(grouped, reverse=True):
        members = grouped[charge]
        if len(members) < 2:
            continue
        minimum = min(line["intercept"] for line in members)
        groups.append(
            {
                "q": charge,
                "record_ids": [line["record_id"] for line in members],
                "minimum_intercept_record_ids": [
                    line["record_id"] for line in members if line["intercept"] == minimum
                ],
                "higher_intercept_record_ids": [
                    line["record_id"] for line in members if line["intercept"] > minimum
                ],
            }
        )
    return groups


def _coincident_line_groups(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, Fraction], list[Mapping[str, Any]]] = {}
    for line in lines:
        grouped.setdefault((line["q"], line["intercept"]), []).append(line)
    groups = []
    for (charge, intercept), members in sorted(
        grouped.items(), key=lambda item: (-item[0][0], item[0][1])
    ):
        if len(members) < 2:
            continue
        groups.append(
            {
                "q": charge,
                "intercept_eV": float(intercept),
                "record_ids": [line["record_id"] for line in members],
            }
        )
    return groups


def charge_transition_envelope(
    formation_records: Mapping[str, Mapping[str, Any]],
    ef_interval_eV: Sequence[Any],
    *,
    source_refs: Mapping[str, str],
) -> dict[str, Any]:
    """Return the exact lower envelope of supplied affine charge-state lines.

    ``formation_records`` must contain the direct output of
    ``formation_energy_terms``.  The explicit ``ef_interval_eV`` is evaluated
    as a closed interval.  Pairwise inequalities determine each line's true
    stability interval; no sparse ``curve`` grid is sampled.  Host, method,
    chemical-potential, VBM/reference, and defect-identity consistency remain
    the responsibility of the outer adapter.
    """

    if not isinstance(formation_records, Mapping) or not formation_records:
        raise ValueError("formation_records must be a nonempty mapping")
    record_ids = list(formation_records)
    if any(
        not isinstance(record_id, str) or not record_id.strip()
        for record_id in record_ids
    ):
        raise ValueError("formation_records keys must be nonempty strings")

    if not isinstance(source_refs, Mapping) or set(source_refs) != set(record_ids):
        raise ValueError("source_refs must cover every formation record exactly once")
    for record_id in record_ids:
        source_ref = source_refs[record_id]
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise ValueError(f"source_refs[{record_id!r}] must be a nonempty string")

    if isinstance(ef_interval_eV, (str, bytes, Mapping)) or len(ef_interval_eV) != 2:
        raise ValueError("ef_interval_eV must be [minimum, maximum]")
    lower_domain = _finite_fraction(ef_interval_eV[0], name="ef_interval_eV.minimum")
    upper_domain = _finite_fraction(ef_interval_eV[1], name="ef_interval_eV.maximum")
    if lower_domain >= upper_domain:
        raise ValueError("ef_interval_eV minimum must be less than maximum")

    lines: list[dict[str, Any]] = []
    for record_id in record_ids:
        record = formation_records[record_id]
        if not isinstance(record, Mapping):
            raise ValueError(f"formation_records[{record_id!r}] must be a mapping")
        if record["schema"] != _SCHEMA:
            raise ValueError(f"formation_records[{record_id!r}] has unsupported schema")
        charge = _integer(record["q"], name=f"formation_records[{record_id!r}].q")
        energy_difference = _finite_fraction(
            record["energy_difference_eV"],
            name=f"formation_records[{record_id!r}].energy_difference_eV",
        )
        chemical_term = _finite_fraction(
            record["chemical_potential_term_eV"],
            name=f"formation_records[{record_id!r}].chemical_potential_term_eV",
        )
        correction = record["correction"]
        if not isinstance(correction, Mapping):
            raise ValueError(f"formation_records[{record_id!r}].correction must be a mapping")
        correction_total = _finite_fraction(
            correction["total_eV"],
            name=f"formation_records[{record_id!r}].correction.total_eV",
        )
        vbm = record["vbm_eV"]
        if charge:
            if vbm is None:
                raise ValueError(f"formation_records[{record_id!r}].vbm_eV is required for q != 0")
            vbm_term = _finite_fraction(vbm, name=f"formation_records[{record_id!r}].vbm_eV") * charge
        else:
            if vbm is not None:
                _finite_fraction(vbm, name=f"formation_records[{record_id!r}].vbm_eV")
            vbm_term = Fraction(0)
        lines.append(
            {
                "record_id": record_id,
                "q": charge,
                "intercept": energy_difference + chemical_term + correction_total + vbm_term,
            }
        )

    line_by_id = {line["record_id"]: line for line in lines}
    stability: dict[str, tuple[Fraction, Fraction] | None] = {
        line["record_id"]: _stable_interval(lines, line, lower_domain, upper_domain)
        for line in lines
    }

    records_output: list[dict[str, Any]] = []
    for line in lines:
        interval = stability[line["record_id"]]
        if interval is None:
            state = "unstable"
            interval_output = None
        elif interval[0] < interval[1]:
            state = "interval"
            interval_output = [float(interval[0]), float(interval[1])]
        else:
            state = "point_only"
            interval_output = [float(interval[0]), float(interval[1])]
        records_output.append(
            {
                "record_id": line["record_id"],
                "q": line["q"],
                "intercept_eV": float(line["intercept"]),
                "source_ref": source_refs[line["record_id"]],
                "stability": state,
                "stability_interval_eV": interval_output,
            }
        )

    breakpoints = {lower_domain, upper_domain}
    for interval in stability.values():
        if interval is not None:
            breakpoints.update(interval)
    breakpoints = sorted(breakpoints)
    segment_winners: list[list[str]] = []
    for left, right in zip(breakpoints, breakpoints[1:]):
        midpoint = (left + right) / 2
        _, winners = _minimum_ids(lines, midpoint)
        segment_winners.append(winners)

    stable_intervals: list[dict[str, Any]] = []
    for index, winners in enumerate(segment_winners):
        if stable_intervals and winners == stable_intervals[-1]["record_ids"]:
            stable_intervals[-1]["ef_interval_eV"][1] = float(breakpoints[index + 1])
            continue
        stable_intervals.append(
            {
                "ef_interval_eV": [float(breakpoints[index]), float(breakpoints[index + 1])],
                "record_ids": winners,
                "charges": _charges(line_by_id, winners),
            }
        )

    transitions: list[dict[str, Any]] = []
    for index in range(1, len(breakpoints) - 1):
        left_winners = segment_winners[index - 1]
        right_winners = segment_winners[index]
        if left_winners == right_winners:
            continue
        ef = breakpoints[index]
        formation_energy, degenerate = _minimum_ids(lines, ef)
        transitions.append(
            {
                "ef_eV": float(ef),
                "formation_energy_eV": float(formation_energy),
                "left_record_ids": left_winners,
                "right_record_ids": right_winners,
                "left_charges": _charges(line_by_id, left_winners),
                "right_charges": _charges(line_by_id, right_winners),
                "degenerate_record_ids": degenerate,
                "degenerate_charges": _charges(line_by_id, degenerate),
            }
        )

    boundaries: list[dict[str, Any]] = []
    for ef in (lower_domain, upper_domain):
        formation_energy, boundary_ids = _minimum_ids(lines, ef)
        boundaries.append(
            {
                "ef_eV": float(ef),
                "formation_energy_eV": float(formation_energy),
                "record_ids": boundary_ids,
                "charges": _charges(line_by_id, boundary_ids),
            }
        )

    return {
        "schema": "mlcc.charge-transitions.v1",
        "ef_interval_eV": [float(lower_domain), float(upper_domain)],
        "units": {
            "energy": "eV",
            "fermi_level": "eV relative to host VBM",
        },
        "records": records_output,
        "stable_intervals": stable_intervals,
        "transitions": transitions,
        "boundaries": boundaries,
        "same_charge_groups": _same_charge_groups(lines),
        "coincident_line_groups": _coincident_line_groups(lines),
        "source_refs": {record_id: source_refs[record_id] for record_id in record_ids},
        "scientific_status": "mathematical_postprocess_unqualified",
        "production_qualification": False,
    }
