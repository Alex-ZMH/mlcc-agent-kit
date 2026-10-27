"""Direct conversion of an externally reviewed native affine Born family.

The native family reader deliberately leaves the polarization branch free.  This
module only applies a caller supplied integer branch and only after the caller
has supplied explicit continuity evidence for every independent displacement.
It does not infer a branch, project a tensor, or alter the saved native family.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from .dielectric_response import read_native_born_family


AFFINE_REVIEW_SCHEMA = "mlcc.native-born-affine-review.v1"
BORN_SCHEMA = "mlcc.born-charge-columns.v1"
_AXES = {
    "tensor": ["atom", "polarization", "displacement"],
    "polarization": ["x", "y", "z"],
    "displacement": ["x", "y", "z"],
    "basis": "Cartesian",
}


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _absolute_path(value: Any, name: str) -> Path:
    if isinstance(value, Path):
        path = value.expanduser()
    elif isinstance(value, str) and value.strip():
        path = Path(value).expanduser()
    else:
        raise ValueError(f"{name} must be an absolute path")
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path.resolve()


def _integer_list(value: Any, name: str, length: int) -> list[int]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{name} must contain exactly {length} integers")
    result: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{name}[{index}] must be an integer")
        result.append(item)
    return result


def _affine_arrays(affine: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, list[Any]]:
    if affine.get("axes") != _AXES:
        raise ValueError("Born affine coefficients must declare Cartesian axes")
    labels = affine["integer_labels"]
    if not isinstance(labels, list) or not labels:
        raise ValueError("Born affine integer_labels must be a non-empty list")
    base = np.asarray(affine["base_tensor_e"], dtype=float)
    coefficients = np.asarray(affine["coefficient_tensors_e"], dtype=float)
    if base.ndim != 3 or base.shape[1:] != (3, 3) or not np.all(np.isfinite(base)):
        raise ValueError("Born affine base_tensor_e must be a finite N x 3 x 3 array")
    expected = (len(labels), base.shape[0], 3, 3)
    if coefficients.shape != expected or not np.all(np.isfinite(coefficients)):
        raise ValueError(
            "Born affine coefficient_tensors_e must be a finite L x N x 3 x 3 array"
        )
    return base, coefficients, labels


def evaluate_born_affine(affine: Mapping[str, Any], integer_shifts: list[int]) -> list[list[list[float]]]:
    """Evaluate ``base + sum(shift[k] * coefficient[k])`` in Cartesian order."""

    base, coefficients, labels = _affine_arrays(_require_mapping(affine, "affine"))
    shifts = _integer_list(integer_shifts, "integer_shifts", len(labels))
    tensor = base + np.tensordot(np.asarray(shifts, dtype=float), coefficients, axes=(0, 0))
    return tensor.tolist()


def _family_groups(born: Mapping[str, Any]) -> list[tuple[int, int]]:
    raw = _require_mapping(born["raw_product"], "born.raw_product")
    affine = _require_mapping(raw["affine_family"], "born.raw_product.affine_family")
    labels = affine["integer_labels"]
    groups: list[tuple[int, int]] = []
    group_axes: dict[tuple[int, int], set[int]] = {}
    if not isinstance(labels, list) or not labels:
        raise ValueError("Born affine integer_labels must be a non-empty list")
    for index, label_value in enumerate(labels):
        label = _require_mapping(label_value, f"integer_labels[{index}]")
        atom_id = label["atom_id"]
        direction = label["direction_index"]
        if isinstance(atom_id, bool) or not isinstance(atom_id, int):
            raise ValueError(f"integer_labels[{index}].atom_id must be an integer")
        if atom_id not in raw["atom_ids"]:
            raise ValueError("Born affine label atom is not an independent displaced site")
        if isinstance(direction, bool) or not isinstance(direction, int):
            raise ValueError(f"integer_labels[{index}].direction_index must be an integer")
        if label["label_index"] != index:
            raise ValueError("Born affine label_index differs from coefficient order")
        if direction not in (0, 1, 2) or label["direction"] != ("x", "y", "z")[direction]:
            raise ValueError("Born affine displacement axis differs from Cartesian label")
        polarization_index = label["polarization_lattice_axis_index"]
        if (type(polarization_index) is not int or polarization_index not in (0, 1, 2)
                or label["polarization_lattice_axis"] != ("a", "b", "c")[polarization_index]):
            raise ValueError("Born affine polarization axis differs from lattice label")
        atom_index = label["atom_index"]
        atom_ids = affine["atom_ids_in_tensor_order"]
        if (type(atom_index) is not int or atom_index < 0 or atom_index >= len(atom_ids)
                or atom_ids[atom_index] != atom_id):
            raise ValueError("Born affine atom mapping differs from tensor order")
        key = (atom_id, direction)
        axes = group_axes.setdefault(key, set())
        if polarization_index in axes:
            raise ValueError("Born affine displacement group repeats a polarization axis")
        axes.add(polarization_index)
        if key not in groups:
            groups.append(key)
    if not groups:
        raise ValueError("native Born family must declare independent displacement groups")
    if any(axes != {0, 1, 2} for axes in group_axes.values()):
        raise ValueError("Born affine displacement group must cover lattice axes a,b,c")
    return groups


def _review_evidence(
    born: Mapping[str, Any], review: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[tuple[int, int]]]:
    entries = review.get("continuous_branch_evidence")
    expected_groups = _family_groups(born)
    if entries is None:
        return [], [], expected_groups
    if not isinstance(entries, list):
        raise ValueError("continuous_branch_evidence must be a list")
    seen: set[tuple[int, int]] = set()
    declared: set[tuple[int, int]] = set()
    snapshots: list[dict[str, Any]] = []
    refs: list[str] = []
    for index, entry_value in enumerate(entries):
        entry = _require_mapping(entry_value, f"continuous_branch_evidence[{index}]")
        atom_id = entry["atom_id"]
        direction = entry["direction_index"]
        if isinstance(atom_id, bool) or not isinstance(atom_id, int):
            raise ValueError(f"continuous_branch_evidence[{index}].atom_id must be an integer")
        if isinstance(direction, bool) or not isinstance(direction, int):
            raise ValueError(
                f"continuous_branch_evidence[{index}].direction_index must be an integer"
            )
        key = (atom_id, direction)
        if key not in expected_groups:
            raise ValueError("continuous branch evidence names an unknown displacement group")
        if key in declared:
            raise ValueError("continuous branch evidence contains a duplicate displacement group")
        declared.add(key)
        if entry.get("kind") != "continuous_polarization_path":
            continue
        source_refs = entry.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            continue
        if not isinstance(entry.get("rationale"), str) or not entry["rationale"].strip():
            continue
        seen.add(key)
        copied = copy.deepcopy(dict(entry))
        source_texts: list[dict[str, str]] = []
        for ref_index, ref_value in enumerate(source_refs):
            ref_path = _absolute_path(
                ref_value,
                f"continuous_branch_evidence[{index}].source_refs[{ref_index}]",
            )
            if not ref_path.is_file():
                raise FileNotFoundError(str(ref_path))
            text = ref_path.read_text(encoding="utf-8")
            if not text.strip():
                raise ValueError(f"continuous branch evidence source is empty: {ref_path}")
            ref_text = str(ref_path)
            refs.append(ref_text)
            source_texts.append({"path": ref_text, "text": text})
        copied["source_refs"] = [item["path"] for item in source_texts]
        copied["source_texts"] = source_texts
        snapshots.append(copied)
    missing = [group for group in expected_groups if group not in seen]
    return snapshots, refs, missing


def _review_context_check(born: Mapping[str, Any], review: Mapping[str, Any], review_path: Path) -> None:
    if review.get("schema") != AFFINE_REVIEW_SCHEMA:
        raise ValueError("Born affine review schema is unsupported")
    family_path = _absolute_path(review.get("family_path"), "review.family_path")
    native_family_path = _absolute_path(
        born["source"]["native_born_family"], "born.source.native_born_family"
    )
    if family_path != native_family_path:
        raise ValueError("Born affine review family_path differs from native family")
    if review.get("context") != born["context"]:
        raise ValueError("Born affine review context differs from native family")
    raw = born["raw_product"]
    labels = raw["affine_family"]["integer_labels"]
    if review.get("integer_labels") != labels:
        raise ValueError("Born affine review integer_labels differ from native family")
    for key in ("reviewer", "reviewed_at", "rationale"):
        _require_text(review.get(key), f"review.{key}")
    if not review_path.is_file():
        raise FileNotFoundError(str(review_path))


def _source_refs(born: Mapping[str, Any], additions: list[str]) -> list[str]:
    refs = list(born.get("source_refs", []))
    for value in additions:
        if value not in refs:
            refs.append(value)
    return refs


def _unresolved_product(
    born: Mapping[str, Any], review: Mapping[str, Any] | None, review_path: Path | None,
    review_text: str | None, reason: str, evidence: list[dict[str, Any]], evidence_refs: list[str],
) -> dict[str, Any]:
    product = copy.deepcopy(dict(born))
    source = copy.deepcopy(dict(product["source"]))
    source["native_born_review"] = None if review_path is None else str(review_path)
    product["source"] = source
    product["source_refs"] = _source_refs(
        product, ([] if review_path is None else [str(review_path)]) + evidence_refs
    )
    product["full_born_tensors_e"] = None
    product["columns"] = []
    product["sources"] = [{
        "source_mode": product.get("source_mode"),
        "native_born_family": str(Path(source["native_born_family"]).resolve()),
        "native_born_review": source["native_born_review"],
    }]
    product["status"] = "unresolved"
    reasons = list(product.get("unresolved_reasons", []))
    if reason not in reasons:
        reasons.append(reason)
    product["unresolved_reasons"] = reasons
    product["scientific_qualification"] = False
    product["numerical_qualification"] = False
    product["production_qualification"] = False
    product["review_record"] = None if review is None else copy.deepcopy(dict(review))
    product["review_source_text"] = review_text
    product["review_evidence"] = copy.deepcopy(evidence)
    return product


def _reviewed_columns(
    atom_ids: list[int], tensor: list[list[list[float]]], source_refs: list[str],
    task_ids: list[str],
) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for atom_index, atom_id in enumerate(atom_ids):
        for axis in range(3):
            columns.append({
                "atom_id": atom_id,
                "cartesian_axis": axis,
                "axis_label": ("x", "y", "z")[axis],
                "values_e": [tensor[atom_index][row][axis] for row in range(3)],
                "unit": "e",
                "complete": True,
                "response_paths": list(source_refs),
                "task_ids": list(task_ids),
            })
    return columns


def resolve_born_affine_family(
    born: Mapping[str, Any], review: Mapping[str, Any] | None, *, review_path: str | Path | None,
) -> dict[str, Any]:
    """Apply a reviewed integer branch to an existing native Born product."""

    _require_mapping(born, "born")
    if born.get("schema") != BORN_SCHEMA:
        raise ValueError("born product schema is unsupported")
    review_file = None if review_path is None else _absolute_path(review_path, "review_path")
    if review is None:
        if review_file is not None:
            raise ValueError("review_path requires a review record")
        return _unresolved_product(born, None, None, None, "born_affine_review_missing", [], [])
    _require_mapping(review, "review")
    if review_file is None:
        raise ValueError("accepted Born affine review requires review_path")
    _review_context_check(born, review, review_file)
    review_text = review_file.read_text(encoding="utf-8")
    saved_review = json.loads(review_text)
    if not isinstance(saved_review, Mapping) or dict(saved_review) != dict(review):
        raise ValueError("Born affine review record differs from review file")
    decision = review.get("decision")
    if decision == "deferred":
        return _unresolved_product(born, review, review_file, review_text, "born_affine_review_deferred", [], [])
    if decision == "rejected":
        return _unresolved_product(born, review, review_file, review_text, "born_affine_review_rejected", [], [])
    if decision != "accepted":
        raise ValueError("Born affine review decision is unsupported")
    shifts = _integer_list(review.get("integer_shifts"), "review.integer_shifts", len(review["integer_labels"]))
    evidence, evidence_refs, missing = _review_evidence(born, review)
    if missing:
        product = _unresolved_product(
            born, review, review_file, review_text, "continuous_branch_evidence_missing", evidence, evidence_refs
        )
        product["missing_continuous_branch_groups"] = [list(group) for group in missing]
        return product
    raw = _require_mapping(born["raw_product"], "born.raw_product")
    affine = _require_mapping(raw["affine_family"], "born.raw_product.affine_family")
    tensor = evaluate_born_affine(affine, shifts)
    source = copy.deepcopy(dict(born["source"]))
    source["native_born_review"] = str(review_file)
    refs = _source_refs(born, [str(review_file), *evidence_refs])
    task_ids = [str(job["task_id"]) for job in born.get("native_jobs", []) if "task_id" in job]
    product = copy.deepcopy(dict(born))
    product.update({
        "schema": BORN_SCHEMA,
        "source": source,
        "source_refs": refs,
        "full_born_tensors_e": tensor,
        "columns": _reviewed_columns(list(born["atom_ids"]), tensor, refs, task_ids),
        "missing_columns": [],
        "sources": [{
            "source_mode": product.get("source_mode"),
            "native_born_family": str(Path(source["native_born_family"]).resolve()),
            "native_born_review": str(review_file),
            "kind": "native_born_affine_review",
            "family_path": str(Path(source["native_born_family"]).resolve()),
            "review_path": str(review_file),
            "integer_shifts": list(shifts),
            "source_refs": [str(review_file), *evidence_refs],
        }],
        "status": "reviewed_branch_tensor",
        "unresolved_reasons": [],
        "scientific_qualification": False,
        "numerical_qualification": False,
        "production_qualification": False,
        "review_record": copy.deepcopy(dict(review)),
        "review_source_text": review_text,
        "review_evidence": copy.deepcopy(evidence),
        "selected_branch_shift": list(shifts),
        "continuous_branch_evidence": copy.deepcopy(review["continuous_branch_evidence"]),
    })
    return product


def consume_native_born_review(
    family_path: str | Path, review_path: str | Path | None = None,
) -> dict[str, Any]:
    """Read a saved native family and optionally apply its external review."""

    family_file = _absolute_path(family_path, "family_path")
    born = read_native_born_family(family_file)
    if review_path is None:
        return resolve_born_affine_family(born, None, review_path=None)
    review_file = _absolute_path(review_path, "review_path")
    if not review_file.is_file():
        raise FileNotFoundError(str(review_file))
    review = json.loads(review_file.read_text(encoding="utf-8"))
    _require_mapping(review, "review")
    return resolve_born_affine_family(born, review, review_path=review_file)


__all__ = [
    "evaluate_born_affine",
    "resolve_born_affine_family",
    "consume_native_born_review",
]
