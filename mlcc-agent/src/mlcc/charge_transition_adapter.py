"""Consume saved charged-formation records as one transition collection."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .charge_transitions import charge_transition_envelope


REQUEST_SCHEMA = "mlcc.charge-transition-request.v1"
FORMATION_SCHEMA = "mlcc.charged-formation.v1"
OUTPUT_SCHEMA = "mlcc.charge-transition-collection.v1"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"saved JSON must be an object: {path}")
    return value


def _chemical_source(product: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    delivery = product["chemical_reference"]
    if delivery is None:
        return None, None
    point = delivery["chemical_point"]
    if point is None:
        point = delivery["mathematical_chemical_point"]
    if point is None:
        return None, None
    source = {
        "source_reference": point["source_reference"],
        "reference_set_id": point["reference_set_id"],
        "evidence_kind": point["evidence_kind"],
    }
    return deepcopy(source), deepcopy(point["mu_eV_per_atom"])


def _bind_product(product: dict[str, Any], path: Path, name: str) -> dict[str, Any]:
    if product["schema"] != FORMATION_SCHEMA:
        raise ValueError(f"formation product {name!r} has unsupported schema")
    if product["status"] not in ("computed", "missing"):
        raise ValueError(f"formation product {name!r} has unsupported status")
    if not isinstance(product["missing"], list):
        raise ValueError(f"formation product {name!r}.missing must be a list")
    references = product["references"]
    host = references["host"]
    defect = references["defect"]
    identity = product["reference_identity"]
    host_method = host["method"]
    host_energy = host["parent_total_energy_provenance"]
    host_levels = host["levels"]
    defect_energy = defect["parent_total_energy_provenance"]
    descriptor = defect["defect_descriptor"]
    chemical_source, mu = _chemical_source(product)
    physical_method = {
        "engine": host_method["engine"],
        "engine_version": host_method["abacus_version_target"],
        "basis_type": host_method["basis_type"],
        "dft_functional": host_method["dft_functional"],
        "method_set": host_method["method_set"],
        "pseudopotential_ids": deepcopy(host_method["pseudopotential_ids"]),
        "pseudopotential_metadata": deepcopy(host_method["pseudopotential_metadata"]),
        "pseudopotential_treatment": deepcopy(host_method["pseudopotential_treatment"]),
    }
    host_task = {"task_id": host["task_id"], "task_path": host["task_path"], "study": deepcopy(host["study"])}
    host_vbm = {
        "value_eV": host_levels["vbm_eV"],
        "reference": host_levels.get("vbm_reference"),
        "source": "references.host.levels.vbm_eV",
        "electronic_source_file": host.get("electronic_source_file"),
    }
    expected_identity = {
        "host_task": host_task,
        "host_model": deepcopy(host["model"]),
        "physical_method": physical_method,
        "energy_definition": host_energy["definition"],
        "charge": deepcopy(defect["charge"]),
        "chemical_source": chemical_source,
        "chemical_potential_eV_per_atom": mu,
        "host_vbm": host_vbm,
        "host_source": {
            "task_id": host["task_id"], "task_path": host["task_path"],
            "study": deepcopy(host["study"]), "model": deepcopy(host["model"]),
            "method": deepcopy(host_method),
            "parent_total_energy_provenance": deepcopy(host_energy),
            "levels": deepcopy(host_levels),
            "electronic_source_file": host.get("electronic_source_file"),
            "source_files": deepcopy(host.get("source_files")),
        },
        "method_comparison": deepcopy(references["method_comparison"]),
        "chemical_study_id": None if product["chemical_reference"] is None else product["chemical_reference"]["study_id"],
        "defect_task": {
            "task_id": defect["task_id"], "task_path": defect["task_path"], "study": deepcopy(defect["study"]),
        },
    }
    for field, expected in expected_identity.items():
        if identity[field] != expected:
            raise ValueError(f"formation product {name!r} reference_identity.{field} differs from references")

    formation = product["formation"]
    if product["status"] == "computed" and formation is None:
        raise ValueError(f"formation product {name!r} computed status has no formation")
    if product["status"] == "missing" and formation is not None:
        raise ValueError(f"formation product {name!r} missing status has a formation")
    if formation is not None:
        if formation["schema"] != "mlcc.formation-energy.v1":
            raise ValueError(f"formation product {name!r} has unsupported formation schema")
        if formation["q"] != defect["charge"]["q"]:
            raise ValueError(f"formation product {name!r} q differs from defect reference")
        if formation["charge_convention"] != defect["charge"]["convention"]:
            raise ValueError(f"formation product {name!r} charge convention differs")
        if formation["mu_eV_per_atom"] != mu:
            raise ValueError(f"formation product {name!r} chemical potentials differ from source")
        if formation["vbm_eV"] != host_levels["vbm_eV"]:
            raise ValueError(f"formation product {name!r} VBM differs from host source")
        if formation["Edef_eV"] != defect_energy["value_eV"] or formation["Ehost_eV"] != host_energy["value_eV"]:
            raise ValueError(f"formation product {name!r} energies differ from references")
        if formation["energy_difference_eV"] != defect_energy["value_eV"] - host_energy["value_eV"]:
            raise ValueError(f"formation product {name!r} energy_difference differs from references")
        if formation["deltaN"] != descriptor["composition_delta"]:
            raise ValueError(f"formation product {name!r} composition_delta differs from descriptor")
    return {
        "host": host,
        "identity": identity,
        "common": {
            "host_source": deepcopy(identity["host_source"]),
            "host_task": host_task,
            "host_model": deepcopy(host["model"]),
            "physical_method": physical_method,
            "energy_definition": host_energy["definition"],
            "charge_convention": defect["charge"]["convention"],
            "chemical_source": chemical_source,
            "chemical_potential_eV_per_atom": mu,
            "host_vbm": host_vbm,
            "defect_descriptor": {
                "operations": deepcopy(descriptor.get("operations")),
                "composition_delta": deepcopy(descriptor["composition_delta"]),
            },
        },
        "formation": formation,
        "source_ref": f"{path}#/formation",
    }


def build_charge_transitions(request_path: str | Path) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _read(request_file)
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("unsupported charge-transition request schema")
    transition_id = request["transition_id"]
    formation_paths = request["formation_paths"]
    if not isinstance(transition_id, str) or not transition_id.strip() or not isinstance(formation_paths, dict) or not formation_paths:
        raise ValueError("transition_id and nonempty formation_paths are required")
    interval = request["ef_interval_eV"]
    products: dict[str, dict[str, Any]] = {}
    paths: dict[str, str] = {}
    bound: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for key, value in formation_paths.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("formation_paths keys must be nonempty strings")
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = request_file.parent / path
        path = path.resolve()
        product = _read(path)
        products[key] = deepcopy(product)
        paths[key] = str(path)
        bound[key] = _bind_product(product, path, key)
        if product["status"] == "missing":
            missing.extend(f"{key}:{item}" for item in product["missing"])
            missing.append(f"{key}:formation")

    first = next(iter(bound.values()))
    common = first["common"]
    for key, value in bound.items():
        if value["common"] != common:
            raise ValueError(f"formation product {key!r} common host/reference identity differs")

    envelope = None
    status = "missing" if missing else "computed"
    if status == "computed":
        envelope = charge_transition_envelope(
            {key: value["formation"] for key, value in bound.items()},
            interval,
            source_refs={key: value["source_ref"] for key, value in bound.items()},
        )
    native_jobs: list[dict[str, Any]] = []
    for product in products.values():
        for role in ("host", "defect"):
            job = product["references"][role]["native_job"]
            if job not in native_jobs:
                native_jobs.append(deepcopy(job))
    return {
        "schema": OUTPUT_SCHEMA,
        "transition_id": transition_id,
        "formation_paths": paths,
        "source_paths": paths,
        "products": products,
        "reference_identity": deepcopy(first["identity"]),
        "host": deepcopy(first["host"]),
        "common": deepcopy(common),
        "status": status,
        "missing": missing,
        "envelope": envelope,
        "native_jobs": native_jobs,
        "scientific_qualification": False,
        "production_qualification": False,
    }


__all__ = ["build_charge_transitions"]
