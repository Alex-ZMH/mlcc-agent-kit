"""Bind a saved FNV correction to one charged formation-energy record."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .defect_thermodynamics import formation_energy_terms


REQUEST_SCHEMA = "mlcc.charged-formation-request.v1"
CORRECTION_SCHEMA = "mlcc.charge-correction.v1"
DELIVERY_SCHEMA = "mlcc.chemical-reference-delivery.v1"
OUTPUT_SCHEMA = "mlcc.charged-formation.v1"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"saved JSON must be an object: {path}")
    return value


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (root.parent / path if not path.is_absolute() else path).resolve()


def _same_number(left: Any, right: Any, *, name: str) -> None:
    if isinstance(left, bool) or isinstance(right, bool):
        raise ValueError(f"{name} must contain finite numeric values")
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        raise ValueError(f"{name} must contain finite numeric values")
    if not math.isfinite(float(left)) or not math.isfinite(float(right)) or not math.isclose(
        float(left), float(right), rel_tol=0.0, abs_tol=1.0e-10
    ):
        raise ValueError(f"{name} differs between saved sources")


def _model(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record["model"][key] for key in ("model_id", "version", "path")}


def _check_pair_binding(pair: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], int, str, float, float, Any]:
    if pair["schema"] != "mlcc.defect-reference-pair.v1":
        raise ValueError("correction references must be an mlcc.defect-reference-pair.v1 pair")
    host = pair["host"]
    defect = pair["defect"]
    if host["schema"] != "mlcc.defect-electronic-reference.v1" or defect["schema"] != "mlcc.defect-electronic-reference.v1":
        raise ValueError("correction references must contain saved electronic references")
    if _model({"model": defect["parent_model"]}) != _model(host):
        raise ValueError("defect parent model differs from host model")
    if host["charge"]["q"] != 0:
        raise ValueError("host reference must be neutral")
    q = defect["charge"]["q"]
    if type(q) is not int:
        raise ValueError("defect charge q must be an integer")
    if host["charge"]["convention"] != "q_positive_removes_electrons" or defect["charge"]["convention"] != host["charge"]["convention"]:
        raise ValueError("host and defect charge conventions differ")
    host_energy = host["parent_total_energy_provenance"]
    defect_energy = defect["parent_total_energy_provenance"]
    if host_energy["definition"] != defect_energy["definition"]:
        raise ValueError("host and defect total-energy definitions differ")
    return (
        host,
        defect,
        q,
        host["charge"]["convention"],
        host_energy["value_eV"],
        defect_energy["value_eV"],
        pair["method_comparison"],
    )


def _check_calculation(correction: Mapping[str, Any], q: int) -> None:
    calculation = correction["calculation"]
    terms = correction["correction_terms"]
    if not isinstance(calculation, Mapping) or not isinstance(terms, Mapping):
        raise ValueError("computed charge correction requires calculation and correction_terms")
    unknown = set(terms) - {"image_charge_eV", "potential_alignment_eV", "total_eV", "method", "qualification"}
    if unknown:
        raise ValueError(f"charge correction terms contain unsupported fields: {sorted(unknown)}")
    if type(calculation["parameters"]["q"]) is not int or type(calculation["alignment_charge_multiplier"]) is not int:
        raise ValueError("charge correction q fields must be integers")
    if calculation["parameters"]["q"] != q or calculation["alignment_charge_multiplier"] != q:
        raise ValueError("charge correction q differs from the bound defect charge")
    calculation_terms = calculation["correction_terms"]
    if not isinstance(calculation_terms, Mapping):
        raise ValueError("charge correction calculation must preserve correction_terms")
    for field in ("image_charge_eV", "potential_alignment_eV", "total_eV"):
        _same_number(terms[field], calculation_terms[field], name=f"correction_terms.{field}")
        _same_number(terms[field], calculation[field], name=f"calculation.{field}")
    _same_number(
        calculation["image_charge_eV"] + calculation["potential_alignment_eV"],
        calculation["total_eV"],
        name="calculation.total_eV",
    )


def _check_host_source(delivery: Mapping[str, Any], host: Mapping[str, Any]) -> Mapping[str, Any]:
    source = delivery["host"]["source"]
    if source["task_id"] != host["task_id"] or source["task_path"] != host["task_path"]:
        raise ValueError("chemical delivery host source is not bound to the correction host task")
    if _model(source) != _model(host):
        raise ValueError("chemical delivery host source model differs from correction host model")
    if source["study"]["study_id"] != host["study"]["study_id"] or delivery["study_id"] != source["study"]["study_id"]:
        raise ValueError("chemical delivery host source Study differs from correction host Study")
    source_method = source["method"]
    host_method = host["method"]
    for field in (
        "engine", "abacus_version_target", "basis_type", "dft_functional", "method_set",
        "nspin", "lspinorb", "noncolin", "occupations", "smearing_method", "mixing_type",
        "symmetry", "ks_solver", "kpoints", "kpoint_rule", "parameters",
        "pseudopotential_ids", "pseudopotential_metadata", "pseudopotential_treatment",
    ):
        if source_method.get(field) != host_method.get(field):
            raise ValueError(f"chemical delivery host method differs in {field}")
    source_energy = source["parent_total_energy_provenance"]
    host_energy = host["parent_total_energy_provenance"]
    _same_number(source_energy["value_eV"], host_energy["value_eV"], name="host total energy")
    if source_energy["definition"] != host_energy["definition"]:
        raise ValueError("chemical delivery host energy definition differs")
    if source["levels"]["vbm_eV"] != host["levels"]["vbm_eV"]:
        raise ValueError("chemical delivery host VBM differs from correction host VBM")
    return source


def _chemical_point(
    delivery: Mapping[str, Any],
    host: Mapping[str, Any],
    delta: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str | None, list[str], dict[str, float] | None]:
    if delivery["schema"] != DELIVERY_SCHEMA:
        raise ValueError("unsupported chemical-reference delivery schema")
    source = _check_host_source(delivery, host)
    point = delivery["chemical_point"]
    kind = "native_saved_source"
    if point is None:
        point = delivery["mathematical_chemical_point"]
        kind = "software_contract_only"
    if point is None:
        return None, None, ["chemical_reference", "chemical_potential"], None
    if point["evidence_kind"] != kind:
        raise ValueError("chemical point evidence kind does not match its delivery field")
    records = delivery["references"]["references"]
    source_kinds = {record["evidence_kind"] for record in records}
    if source_kinds != {kind} or delivery["references"]["evidence_kind"] != kind:
        raise ValueError("native and software chemical references cannot be mixed")
    if point["source_reference"] != delivery["collection_path"] or point["reference_set_id"] != delivery["reference_set_id"]:
        raise ValueError("chemical point source is not bound to its delivery collection")
    if (point["engine"], point["engine_version"], point["method_set"], point["energy_definition"]) != (
        source["method"]["engine"], source["method"]["abacus_version_target"],
        source["method"]["method_set"], source["parent_total_energy_provenance"]["definition"],
    ):
        raise ValueError("chemical point engine, method, or energy definition differs from host source")
    mu = point["mu_eV_per_atom"]
    if mu is None:
        return point, kind, ["chemical_potential"], None
    missing = [f"chemical_potential:{element}" for element in delta if element not in mu]
    return point, kind, missing, mu


def _identity(
    host: Mapping[str, Any], defect: Mapping[str, Any], comparison: Mapping[str, Any],
    point: Mapping[str, Any] | None, chemical_kind: str | None, delivery: Mapping[str, Any] | None,
) -> dict[str, Any]:
    host_method = host["method"]
    host_source = {
        "task_id": host["task_id"], "task_path": host["task_path"],
        "study": deepcopy(host["study"]), "model": deepcopy(host["model"]),
        "method": deepcopy(host_method),
        "parent_total_energy_provenance": deepcopy(host["parent_total_energy_provenance"]),
        "levels": deepcopy(host["levels"]),
        "electronic_source_file": host.get("electronic_source_file"),
        "source_files": deepcopy(host.get("source_files")),
    }
    return {
        "host_task": {
            "task_id": host["task_id"], "task_path": host["task_path"],
            "study": deepcopy(host["study"]),
        },
        "host_model": deepcopy(host["model"]),
        "physical_method": {
            "engine": host_method["engine"],
            "engine_version": host_method["abacus_version_target"],
            "basis_type": host_method["basis_type"],
            "dft_functional": host_method["dft_functional"],
            "method_set": host_method["method_set"],
            "pseudopotential_ids": deepcopy(host_method["pseudopotential_ids"]),
            "pseudopotential_metadata": deepcopy(host_method["pseudopotential_metadata"]),
            "pseudopotential_treatment": deepcopy(host_method["pseudopotential_treatment"]),
        },
        "energy_definition": host["parent_total_energy_provenance"]["definition"],
        "charge": deepcopy(defect["charge"]),
        "chemical_source": None if point is None else {
            "source_reference": point["source_reference"],
            "reference_set_id": point["reference_set_id"],
            "evidence_kind": chemical_kind,
        },
        "chemical_potential_eV_per_atom": None if point is None else deepcopy(point["mu_eV_per_atom"]),
        "host_vbm": {
            "value_eV": host["levels"]["vbm_eV"],
            "reference": host["levels"].get("vbm_reference"),
            "source": "references.host.levels.vbm_eV",
            "electronic_source_file": host.get("electronic_source_file"),
        },
        "host_source": host_source,
        "method_comparison": deepcopy(comparison),
        "chemical_study_id": None if delivery is None else delivery["study_id"],
        "defect_task": {"task_id": defect["task_id"], "task_path": defect["task_path"], "study": deepcopy(defect["study"])},
    }


def build_charged_formation(request_path: str | Path) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _read(request_file)
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("unsupported charged-formation request schema")
    correction_file = _resolve(request_file, request["correction_path"])
    correction = _read(correction_file)
    if correction["schema"] != CORRECTION_SCHEMA:
        raise ValueError("unsupported charge-correction schema")
    pair = correction["references"]
    host, defect, q, convention, ehost, edef, comparison = _check_pair_binding(pair)
    delta = correction["lineage"]["composition_delta"]
    if correction["lineage"].get("defect_charge_q") is not None and correction["lineage"]["defect_charge_q"] != q:
        raise ValueError("correction lineage defect charge differs from defect reference")
    if correction["lineage"].get("charge_convention") is not None and correction["lineage"]["charge_convention"] != convention:
        raise ValueError("correction lineage charge convention differs from references")
    status = correction["status"]
    if status not in ("computed", "missing"):
        raise ValueError("charge correction status must be computed or missing")
    missing = list(correction["missing"])
    if status == "missing" or missing:
        if "correction" not in missing:
            missing.append("correction")
    elif comparison["same_recorded_comparison_fields"] is not True:
        raise ValueError("computed charge correction requires matching recorded host/defect methods")
    if status == "computed":
        _check_calculation(correction, q)
    ef_grid = request["ef_grid_eV"]
    if ef_grid is None or len(ef_grid) == 0:
        missing.append("ef_grid_eV")
    host_vbm = host["levels"]["vbm_eV"]
    if host_vbm is None:
        missing.append("host_vbm")
    chemical_file = None if request["chemical_delivery_path"] is None else _resolve(request_file, request["chemical_delivery_path"])
    delivery = None if chemical_file is None else _read(chemical_file)
    point = None
    chemical_kind = None
    mu = None
    if delivery is None:
        missing.extend(value for value in ("chemical_reference", "chemical_potential") if value not in missing)
    else:
        point, chemical_kind, chemical_missing, mu = _chemical_point(delivery, host, delta)
        for value in delivery["missing"]:
            if value not in missing:
                missing.append(value)
        for value in chemical_missing:
            if value not in missing:
                missing.append(value)
        if chemical_kind is not None and correction["evidence_kind"] != chemical_kind:
            raise ValueError("computed correction and chemical point evidence kinds cannot be mixed")
    formation = None
    if not missing:
        formation = formation_energy_terms(edef, ehost, delta, mu, q, host_vbm, ef_grid, correction["correction_terms"])
    source_paths = deepcopy(correction["source_paths"])
    source_paths.update({
        "request_path": str(request_file), "correction_path": str(correction_file),
        "chemical_delivery_path": None if chemical_file is None else str(chemical_file),
    })
    return {
        "schema": OUTPUT_SCHEMA,
        "formation_id": request["formation_id"],
        "status": "computed" if formation is not None else "missing",
        "missing": missing,
        "formation": formation,
        "correction": deepcopy(correction),
        "chemical_reference": None if delivery is None else deepcopy(delivery),
        "references": deepcopy(pair),
        "source_paths": source_paths,
        "reference_identity": _identity(host, defect, comparison, point, chemical_kind, delivery),
        "evidence_kind": "software_contract_only" if "software_contract_only" in (correction.get("evidence_kind"), chemical_kind) else correction.get("evidence_kind"),
        "scientific_qualification": False,
        "production_qualification": False,
    }


__all__ = ["build_charged_formation"]
