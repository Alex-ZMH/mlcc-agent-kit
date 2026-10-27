"""Create an explicit neutral host/defect ABACUS SCF task pair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .abacus_tasks import create_abacus_task
from .abacus import _energy_definition
from .defect_thermodynamics import (
    compare_variant_method_records,
    _delta_composition,
    _load_descriptor,
    _mapping,
    _nonempty_text,
    _number,
    _reference_identity,
    _stoichiometry,
)
from .method_tasks import check_method_configuration
from .modeling import read_model_artifacts


_CELL_TOL = 1.0e-8


def create_neutral_defect_task_pair(
    *,
    host_model_path: str | Path,
    defect_model_path: str | Path,
    host_study_path: str | Path,
    defect_study_path: str | Path,
    method_path: str | Path,
    site_path: str | Path,
    host_request_path: str | Path,
    defect_request_path: str | Path,
    chemical_reference_path: str | Path | None = None,
    output_path: str | Path | None = None,
    defect_method_path: str | Path | None = None,
) -> dict[str, Any]:
    """Materialise two explicit, neutral, fixed-cell ABACUS SCF tasks.

    The host and defect studies are separate files because the existing task
    creator binds one ``study.model`` identity per task. ``method_path`` is
    retained as the host method argument; ``defect_method_path`` is optional
    and defaults to it for the historical same-method path. All domain checks
    run before either creator call. This function never selects a defect,
    changes a method, submits a task, or marks scientific qualification.
    """
    host_model = read_model_artifacts(host_model_path)
    defect_model = read_model_artifacts(defect_model_path)
    descriptor = _load_descriptor(Path(defect_model_path) / "model.json")
    derivation = _mapping(descriptor["derivation"], name="defect derivation")
    if int(derivation["charge_state"]) != 0:
        raise ValueError("neutral defect task pair requires charge_state=0")

    host_identity = (host_model.model_id, host_model.version)
    defect_identity = (defect_model.model_id, defect_model.version)
    parent = _mapping(descriptor["parent_model"], name="defect parent_model")
    if (parent["model_id"], parent["version"]) != host_identity:
        raise ValueError("defect parent_model identity does not match the supplied host model")
    if Path(parent["path"]).resolve() != host_model.artifact_dir.resolve():
        raise ValueError("defect parent_model.path does not match the supplied host model")

    host_composition = _stoichiometry(host_model.metadata["composition"], name="host composition")
    defect_composition = _stoichiometry(defect_model.metadata["composition"], name="defect composition")
    parent_composition = _stoichiometry(derivation["composition_parent"], name="derivation.composition_parent")
    child_composition = _stoichiometry(derivation["composition_child"], name="derivation.composition_child")
    delta = _delta_composition(derivation["composition_delta"], name="derivation.composition_delta")
    actual_delta = {
        element: defect_composition.get(element, 0) - host_composition.get(element, 0)
        for element in set(host_composition) | set(defect_composition)
        if defect_composition.get(element, 0) - host_composition.get(element, 0)
    }
    if parent_composition != host_composition or child_composition != defect_composition:
        raise ValueError("defect derivation stoichiometry does not match host/defect models")
    if delta != actual_delta:
        raise ValueError("defect derivation composition_delta does not match host/defect models")
    if not np.allclose(host_model.atoms.cell.array, defect_model.atoms.cell.array, rtol=0.0, atol=_CELL_TOL):
        raise ValueError("host and defect models must use the same supercell")
    if host_model.atoms.pbc.tolist() != defect_model.atoms.pbc.tolist():
        raise ValueError("host and defect models must use the same periodic-cell contract")

    host_study = json.loads(Path(host_study_path).read_text(encoding="utf-8"))
    defect_study = json.loads(Path(defect_study_path).read_text(encoding="utf-8"))
    host_selected = _mapping(host_study["model"], name="host study.model")
    defect_selected = _mapping(defect_study["model"], name="defect study.model")
    if (host_selected["model_id"], host_selected["version"]) != host_identity:
        raise ValueError("host study.model does not match host model")
    if (defect_selected["model_id"], defect_selected["version"]) != defect_identity:
        raise ValueError("defect study.model does not match defect model")
    if host_study.get("case_id") != defect_study.get("case_id") or host_study.get("case_role") != defect_study.get("case_role"):
        raise ValueError("host and defect studies must belong to the same case domain")
    if bool(host_study.get("case_role") == "engineering_fixture") != bool(host_model.metadata.get("fixture")):
        raise ValueError("host study and model fixture roles differ")
    if bool(defect_study.get("case_role") == "engineering_fixture") != bool(defect_model.metadata.get("fixture")):
        raise ValueError("defect study and model fixture roles differ")
    if host_study.get("case_role") != "engineering_fixture":
        for field in ("material", "phase_requested"):
            if host_selected.get(field) != host_model.metadata.get(field):
                raise ValueError(f"host study.model.{field} does not match host model")
            if defect_selected.get(field) != defect_model.metadata.get(field):
                raise ValueError(f"defect study.model.{field} does not match defect model")
    for model, study, label in ((host_model, host_study, "host"), (defect_model, defect_study, "defect")):
        binding = model.metadata.get("study_binding")
        if binding is not None and binding != study.get("study_id"):
            raise ValueError(f"{label} model study_binding differs from study_id")

    def request(path: str | Path, label: str) -> str:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        task_id = _nonempty_text(value.get("task_id"), name=f"{label}.task_id")
        if Path(task_id).name != task_id:
            raise ValueError(f"{label}.task_id must be a plain directory name")
        if value.get("calculation") != "scf":
            raise ValueError(f"{label} must request calculation=scf")
        if value.get("input_transformation") is not None:
            raise ValueError(f"{label} must use input_transformation=null")
        if not isinstance(value.get("required_results"), list):
            raise ValueError(f"{label}.required_results must be a list")
        _mapping(value.get("resource_request"), name=f"{label}.resource_request")
        return task_id

    host_task_id = request(host_request_path, "host request")
    defect_task_id = request(defect_request_path, "defect request")
    if host_task_id == defect_task_id:
        raise ValueError("host and defect requests must use distinct task_id values")

    host_method_path = Path(method_path)
    defect_method_file = Path(defect_method_path) if defect_method_path is not None else host_method_path
    host_method = json.loads(host_method_path.read_text(encoding="utf-8"))
    defect_method = json.loads(defect_method_file.read_text(encoding="utf-8"))
    site = json.loads(Path(site_path).read_text(encoding="utf-8"))
    point = None
    if chemical_reference_path is not None:
        point = json.loads(Path(chemical_reference_path).read_text(encoding="utf-8"))
        mu = _mapping(point.get("mu_eV_per_atom"), name="chemical_point.mu_eV_per_atom")
        reference_identity = _reference_identity(point, name="chemical_point")
        _nonempty_text(point.get("source_reference"), name="chemical_point.source_reference")
        if not set(delta).issubset(mu):
            raise ValueError("chemical_point.mu_eV_per_atom must cover every defect composition delta")
        for element in delta:
            _number(mu[element], name=f"chemical_point.mu_eV_per_atom.{element}")
    else:
        reference_identity = None
    host_engine_version = host_method.get("engine_version", host_method.get("abacus_version_target"))
    if reference_identity is not None:
        if reference_identity[:3] != (host_method["engine"], host_engine_version, host_method["method_set"]):
            raise ValueError("chemical point method identity differs from ABACUS method")
        host_science = host_method.get("science", {})
        if not isinstance(host_science, dict):
            host_science = {}
        host_occupations = host_method.get("occupations", host_science.get("occupations"))
        if reference_identity[3] != _energy_definition(host_occupations):
            raise ValueError("chemical point energy definition differs from ABACUS method")
    method_comparison = compare_variant_method_records(
        host_method,
        defect_method,
        host_elements=set(host_composition),
        defect_elements=set(defect_composition),
        record_kind="configuration",
    )
    if not method_comparison["passed"]:
        raise ValueError(
            "host and defect ABACUS method contracts are incompatible: "
            + json.dumps(method_comparison, sort_keys=True, ensure_ascii=False)
        )
    for model, label, method, method_file in (
        (host_model, "host", host_method, host_method_path),
        (defect_model, "defect", defect_method, defect_method_file),
    ):
        if "input_qualification" in method:
            qualification = check_method_configuration(model, method, site, method_file)
            if not qualification["input_qualified"]:
                raise ValueError(f"{label} ABACUS method input qualification failed: {qualification['issues']}")

    workspace = Path(site["workspace"]["local"]).resolve()
    tasks = workspace / "tasks"
    if not tasks.is_dir():
        raise FileNotFoundError(tasks)
    if (tasks / host_task_id).exists() or (tasks / defect_task_id).exists():
        raise FileExistsError("host or defect task directory already exists")
    if output_path is not None and Path(output_path).exists():
        raise FileExistsError(output_path)

    # Keep the existing creator's original errors and records. If the second
    # call fails after the first materialises, the first task is retained.
    create_abacus_task(study_path=host_study_path, model_path=host_model_path,
                       method_path=host_method_path, site_path=site_path,
                       request_path=host_request_path)
    create_abacus_task(study_path=defect_study_path, model_path=defect_model_path,
                       method_path=defect_method_file, site_path=site_path,
                       request_path=defect_request_path)

    pair = {
        "schema": "mlcc.neutral-defect-task-pair.v1",
        "status": "tasks_defined_not_submitted",
        "scientific_status": "not_calculated",
        "production_qualification": False,
        "host_task": str((tasks / host_task_id / "task.json").resolve()),
        "defect_task": str((tasks / defect_task_id / "task.json").resolve()),
        "descriptor_path": str((Path(defect_model_path) / "model.json").resolve()),
        "chemical_reference": (
            str(Path(chemical_reference_path).resolve())
            if chemical_reference_path is not None else None
        ),
        "source_method": str(host_method_path.resolve()),
        "source_methods": {
            "host": str(host_method_path.resolve()),
            "defect": str(defect_method_file.resolve()),
        },
        "method_comparison": method_comparison,
        "source_site": str(Path(site_path).resolve()),
        "lineage": {
            "parent_model": dict(parent),
            "composition_delta": delta,
            "charge_state": 0,
            "same_supercell": True,
            "host_elements": method_comparison["host_elements"],
            "defect_elements": method_comparison["defect_elements"],
            "new_elements": method_comparison["new_elements"],
            "removed_elements": method_comparison["removed_elements"],
        },
        "postprocessing": {
            "adapter": "mlcc.defect_thermodynamics.neutral_formation_from_tasks",
            "requires_completed_native_scf": True,
            "formation_energy_written": False,
            "formation_energy_deferred": chemical_reference_path is None,
        },
    }
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(pair, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        pair["pair_manifest"] = str(output.resolve())
    return pair


__all__ = ["create_neutral_defect_task_pair"]
