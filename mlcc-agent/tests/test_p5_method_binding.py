"""Focused tests for the P5 physical-method/source binding contract.

These checks exercise method identity only.  They do not assert numerical
convergence or scientific/material qualification.  The ABACUS fixture is
loaded from the saved job188 response when that evidence is available so the
test uses the same complete method record as the native Berry consumer.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping

import pytest

from mlcc.dielectric_response import (
    _context_equal,
    p5_method_comparison,
    p5_method_identity,
)


_BERRY_RESPONSE_RELATIVE = Path(
    "reports/berry-response-native-v001/berry-response-results.gpu-v002.json"
)
_BERRY_RESPONSE_WORKSPACE_RELATIVE = Path(
    "workspace/reports/berry-response-native-v001/berry-response-results.gpu-v002.json"
)


def _saved_berry_response_path() -> Path:
    """Find the shared native report from either local or v100 source roots."""

    configured = os.environ.get("MLCC_P5_BERRY_RESPONSE")
    if configured:
        return Path(configured).expanduser()

    return Path(__file__).resolve().parents[2] / _BERRY_RESPONSE_WORKSPACE_RELATIVE


def _native_abacus_method() -> dict[str, Any]:
    path = _saved_berry_response_path()
    response = json.loads(path.read_text(encoding="utf-8"))
    return copy.deepcopy(response["common_method"])


def _context(method: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "parent": {
            "study_id": "p5-method-binding-study",
            "model_id": "p5-method-binding-model",
            "model_version": "v001",
            "model_path": "/p5-method-binding/model",
        },
        "atom_ids": [101, 205],
        "cell_angstrom": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
        "volume_A3": 64.0,
        "common_method": copy.deepcopy(dict(method)),
    }


def test_abacus_numeric_controls_and_method_set_are_preserved_as_protocol_differences() -> None:
    baseline = _native_abacus_method()
    changed = copy.deepcopy(baseline)
    changed["method_set"] = "same-physics-different-protocol"
    changed["pw_diag_thr"] = 5.0e-7
    changed.pop("kpoint_shift")
    changed["kpoints"] = [3, 3, 3]
    changed["parameters"]["ecutwfc_Ry"] = 120
    changed["parameters"].pop("scf_thr")

    comparison = p5_method_comparison(baseline, changed)

    assert comparison["same_physical_method"] is True
    assert comparison["scientific_precision_qualified"] is False
    assert comparison["original_methods"][1]["method_set"] == changed["method_set"]
    assert "method_set" not in comparison["physical_identities"][0]
    assert "method_set" not in comparison["physical_identities"][1]
    assert comparison["numerical_protocols_equal"] is False
    assert comparison["numerical_protocols"][0]["record"]["kpoint_shift"] == baseline["kpoint_shift"]
    assert "kpoint_shift" in comparison["numerical_protocols"][1]["missing_fields"]
    assert "parameters.scf_thr" in comparison["numerical_protocols"][1]["missing_fields"]
    assert comparison["numerical_protocols"][1]["record"]["pw_diag_thr"] == changed["pw_diag_thr"]


@pytest.mark.parametrize(
    "change",
    [
        "pseudopotential",
        "exchange_correlation",
        "spin",
        "charge",
        "smearing",
        "unknown_physical_field",
    ],
)
def test_physical_method_differences_are_rejected_by_identity_and_context(change: str) -> None:
    baseline = _native_abacus_method()
    changed = copy.deepcopy(baseline)
    if change == "pseudopotential":
        changed["pseudopotential_ids"]["Ca"] = "different-Ca-pseudopotential"
    elif change == "exchange_correlation":
        changed["dft_functional"] = "SCAN"
    elif change == "spin":
        changed["nspin"] = 2
    elif change == "charge":
        changed["net_charge"] = 1
    elif change == "smearing":
        changed["parameters"]["smearing_sigma_Ry"] = 0.01
    elif change == "unknown_physical_field":
        changed["p5_unknown_physical_control"] = "changed"
        baseline["p5_unknown_physical_control"] = "baseline"

    comparison = p5_method_comparison(baseline, changed)

    assert comparison["same_physical_method"] is False
    assert comparison["scientific_precision_qualified"] is False
    assert not _context_equal(_context(baseline), _context(changed))


def test_math_source_identity_is_exact_and_not_promoted_to_scientific_qualification() -> None:
    baseline = {"engine": "math-fixture", "method": "coupled-spring", "version": "v001"}
    same = copy.deepcopy(baseline)
    changed = {**baseline, "version": "v002"}

    assert p5_method_identity(baseline) == baseline
    same_comparison = p5_method_comparison(baseline, same)
    assert same_comparison["same_physical_method"] is True
    assert same_comparison["numerical_protocols_equal"] is True
    assert same_comparison["scientific_precision_qualified"] is False

    changed_comparison = p5_method_comparison(baseline, changed)
    assert changed_comparison["same_physical_method"] is False
    assert changed_comparison["scientific_precision_qualified"] is False

