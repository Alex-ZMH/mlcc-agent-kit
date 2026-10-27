"""Create and parse explicit ABACUS tasks; scheduling stays in SiteRunner."""
from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
import shlex

import numpy as np
from ase.io import read, write

from .abacus import (
    AbacusMethod,
    AbacusExecution,
    AbacusParameters,
    abacus_method_from_config,
    _normalize_output_control,
    prepare_abacus,
    parse_abacus_outputs,
)
from .modeling import read_model_artifacts
from .tasks import TaskRecord, load_task, save_task
from .strain import isotropic_strain_model
from .method_tasks import check_method_configuration, method_numerical_orbitals
from .elastic import voigt_strain_model
from .electronic import validate_charged_scf_electrons


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


_OUTPUT_CONTROL_FIELDS = {
    "out_pot", "out_interval", "efield_flag", "dip_cor_flag", "gate_flag",
    "imp_sol", "use_paw", "vl_in_h", "vion_in_h", "vh_in_h", "output_control",
}


def _validate_output_control_placement(config, request):
    """Reject output controls outside the canonical method-config location."""

    for name in _OUTPUT_CONTROL_FIELDS:
        if name in config and name != "output_control":
            raise ValueError(f"method configuration {name} must be inside output_control")
    for name in _OUTPUT_CONTROL_FIELDS:
        if name in request:
            raise ValueError(f"request {name} is not a method output-control field")
    parameters = config.get("parameters")
    if isinstance(parameters, dict):
        misplaced = _OUTPUT_CONTROL_FIELDS.intersection(parameters)
        if misplaced:
            raise ValueError("parameters contains output-control fields: " + ", ".join(sorted(misplaced)))
    request_parameters = request.get("parameters")
    if isinstance(request_parameters, dict):
        misplaced = _OUTPUT_CONTROL_FIELDS.intersection(request_parameters)
        if misplaced:
            raise ValueError("request parameters contains output-control fields: " + ", ".join(sorted(misplaced)))
    return _normalize_output_control(config.get("output_control"))


def _grain_sources_requested(study, model) -> bool:
    """Return whether this task carries the explicit grain-boundary source contract."""

    return model.metadata.get("spatial_mode") == "grain_boundary" or study.get("grain_boundary") is not None


def create_abacus_task(*, study_path, model_path, method_path, site_path, request_path):
    """Materialize one configured SCF/relax task without transfer or submission."""
    study, config, site, request = map(_json, (study_path, method_path, site_path, request_path))
    basis = config["basis_type"]
    if config["engine"] != "abacus" or config["engine_version"] != "3.10.1" or basis not in ("pw", "lcao"):
        raise ValueError("this adapter requires ABACUS 3.10.1 PW or LCAO")
    method_fields = {"basis_type", "numerical_orbital_ids", "numerical_orbitals", "lcao_output"}
    if method_fields.intersection(request) or method_fields.intersection(request.get("parameters", {})):
        raise ValueError("basis, numerical orbitals and LCAO output must be selected by the method configuration")
    if method_fields.intersection(config.get("parameters", {})):
        raise ValueError("basis, numerical orbital IDs and LCAO output belong at the method configuration top level")
    if basis == "lcao" and "numerical_orbitals" in config:
        raise ValueError("LCAO methods select numerical_orbital_ids; resource paths belong in the site configuration")
    if basis == "pw" and any(name in config for name in ("numerical_orbital_ids", "numerical_orbitals", "lcao_output")):
        raise ValueError("PW methods must not define LCAO orbital or output settings")
    stage = request["calculation"]
    if stage not in ("scf", "relax"):
        raise ValueError("current PW task calculations are scf and fixed-cell relax")
    output_control = _validate_output_control_placement(config, request)
    if basis == "lcao" and (stage != "scf" or output_control is not None):
        raise ValueError("LCAO currently supports fixed-cell SCF without electrostatic output_control")
    if output_control is not None:
        if stage != "scf":
            raise ValueError("electrostatic potential output requires a fixed-cell SCF stage")
        if request.get("input_transformation") is not None:
            raise ValueError("electrostatic potential output does not support strain transformations")
    model = read_model_artifacts(model_path)
    derivation = model.metadata.get("derivation", {})
    if isinstance(derivation, dict) and "charge_state" in derivation:
        model_charge = derivation["charge_state"]
    else:
        model_charge = model.metadata.get("charge_state", 0)
    if isinstance(model_charge, bool) or not isinstance(model_charge, (int, np.integer)):
        raise ValueError("model derivation charge_state must be an explicit integer")
    model_charge = int(model_charge)
    model_study = model.metadata.get("study_binding")
    if model_study is not None and model_study != study["study_id"]:
        raise ValueError("derived model study_binding differs from the requested study")
    if (study["model"]["model_id"], study["model"]["version"]) != (model.model_id, model.version):
        raise ValueError("study must explicitly select this model ID and version")
    fixture = study["case_role"] == "engineering_fixture"
    if fixture != model.metadata["fixture"]:
        raise ValueError("study and model fixture roles differ")
    if not fixture:
        for field in ("material", "phase_requested"):
            selected = study["model"][field]
            if not selected or selected != model.metadata[field]:
                raise ValueError(f"study {field} must match the explicitly selected model")
    try:
        method = abacus_method_from_config(config)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ABACUS method charge contract is invalid: {exc}") from exc
    if method.net_charge != model_charge:
        raise ValueError(
            "model derivation charge_state must equal method net_charge "
            f"({model_charge} != {method.net_charge})"
        )
    if basis == "lcao" and (method.net_charge != 0 or method.nspin != 1 or method.occupations != "fixed"):
        raise ValueError("LCAO currently requires neutral nspin=1 fixed-occupation SCF")
    if method.net_charge != 0:
        if stage != "scf":
            raise ValueError("charged ABACUS tasks support fixed-cell SCF only")
        if request.get("input_transformation") is not None:
            raise ValueError("charged ABACUS tasks do not support strain transformations")
    execution = AbacusExecution(**config["execution"])
    parameters = AbacusParameters(**{field.name: config["parameters"][field.name] for field in fields(AbacusParameters)})
    element_order = config["element_order"]
    pseudo_files = {element: site["abacus"]["pseudopotential_files"][config["pseudopotential_ids"][element]]
                    for element in element_order}
    orbital_files = method_numerical_orbitals(config, site) if basis == "lcao" else None
    selected_files = [*pseudo_files.values(), *(orbital_files.values() if orbital_files else [])]
    names = [Path(path).name for path in selected_files]
    if len(names) != len(set(names)):
        raise ValueError("selected ABACUS resources have colliding basenames")
    input_qualification = None
    if "input_qualification" in config:
        input_qualification = check_method_configuration(model, config, site, method_path)
        if not input_qualification["input_qualified"]:
            raise ValueError("ABACUS method input qualification failed: "
                             + json.dumps(input_qualification["issues"], ensure_ascii=False))
    elif basis == "lcao":
        raise ValueError("LCAO tasks require explicit UPF and numerical orbital input qualification")
    elif method.net_charge != 0:
        raise ValueError("charged ABACUS tasks require explicit method input qualification")
    elif not fixture:
        raise ValueError("non-fixture ABACUS tasks require explicit method input qualification")
    transformation = request["input_transformation"]
    grain_sources_requested = _grain_sources_requested(study, model)
    if transformation is not None:
        if stage != "scf":
            raise ValueError("strain transformations currently require fixed-fractional-coordinate SCF")
        reference = {"model_id": model.model_id, "version": model.version}
        if transformation["kind"] == "isotropic_strain":
            model.atoms, strain_record = isotropic_strain_model(
                model.atoms, transformation["epsilon"], reference_model=reference)
        elif transformation["kind"] == "voigt_strain":
            model.atoms, strain_record = voigt_strain_model(
                model.atoms, transformation["strain_voigt"], reference_model=reference)
        else:
            raise ValueError("implemented strain transformations are isotropic_strain and voigt_strain")
        transformation = {**transformation, **strain_record}
    if stage == "relax":
        if "ionic_constraints" not in request or request["ionic_constraints"] is None:
            raise ValueError("fixed-cell relax requires explicit ionic_constraints")
        ionic_constraints = request["ionic_constraints"]
    else:
        if "ionic_constraints" in request:
            raise ValueError("SCF requests must not define ionic_constraints")
        ionic_constraints = None
    directory = Path(site["workspace"]["local"]) / "tasks" / request["task_id"]
    directory.mkdir()
    grain_binding = None
    if grain_sources_requested:
        # Source provenance must describe the original geometry even when the
        # requested ABACUS input is a transformed SCF.  The helper performs the
        # Study/Model/lineage checks and stages only the two static JSON files.
        source_model = read_model_artifacts(model_path) if transformation is not None else model
        from .grain_task_sources import stage_grain_task_sources

        grain_binding = stage_grain_task_sources(
            study,
            source_model,
            directory,
            study_file=str(Path(study_path).resolve()),
        )
    lcao_arguments = ({"numerical_orbitals": orbital_files, "lcao_output": config.get("lcao_output")}
                      if basis == "lcao" else {})
    prepared = prepare_abacus(model, directory, parameters=parameters, method=method, execution=execution,
                              stage=stage, pseudopotentials=pseudo_files, element_order=element_order,
                              kpoints=config["kpoints"], input_qualification=input_qualification,
                              output_control=output_control, ionic_constraints=ionic_constraints, **lcao_arguments)
    write(directory / "input.extxyz", model.atoms)
    generated = _json(directory / "method.json")
    generated.update(method_set=config["method_set"], parent_method_set=config["parent_method_set"],
                     source_configuration=str(Path(method_path).resolve()), fixture=fixture,
                     pseudopotential_ids=config["pseudopotential_ids"],
                     pseudopotential_metadata=config["pseudopotential_metadata"])
    if input_qualification is not None:
        generated.update(input_qualification=input_qualification,
                         pseudopotential_treatment=config["pseudopotential_treatment"],
                         compatibility_reference=config.get("compatibility_reference"))
        (directory / "method-input-qualification.json").write_text(
            json.dumps(input_qualification, indent=2) + "\n", encoding="utf-8")
    generated.update(
        net_charge=int(method.net_charge),
        nelec=0,
        nelec_delta=-int(method.net_charge),
        charge_convention="positive q removes q electrons",
    )
    if basis == "lcao":
        generated["numerical_orbital_ids"] = dict(config["numerical_orbital_ids"])
        generated["orbital_header_snapshot"] = input_qualification["orbital_header_snapshot"]
        generated["orbital_input_qualification"] = input_qualification["checks"]["numerical_orbitals"]
        output = config.get("lcao_output")
        if output is not None:
            requested = generated.setdefault("requested_artifacts", {})
            for key, flag, filename in (
                ("hamiltonian", "out_mat_hs2", "data-HR-sparse_SPIN0.csr"),
                ("overlap", "out_mat_hs2", "data-SR-sparse_SPIN0.csr"),
                ("position", "out_mat_r", "data-rR-sparse.csr"),
            ):
                if output[flag] == 1:
                    requested[key] = {"relative_path": f"OUT.{method.suffix}/{filename}",
                                      "native_output_observed": False}
    (directory / "method.json").write_text(json.dumps(generated, indent=2) + "\n", encoding="utf-8")
    resources = request["resource_request"]
    cp_commands = [f"cp {shlex.quote(source)} {shlex.quote(Path(source).name)}" for source in selected_files]
    launch = [site["abacus"]["mpi_launcher"], "-launcher", "slurm", "-rmk", "slurm", "-n",
              str(resources["ntasks"]), "-bind-to", "core", site["abacus"]["binary"]]
    script = "\n".join(["#!/bin/bash", "set -e", *cp_commands, "date --iso-8601=seconds",
                         "printf 'Slurm job=%s ranks=%s visible_gpus=%s\\n' \"$SLURM_JOB_ID\" \"$SLURM_NTASKS\" \"$CUDA_VISIBLE_DEVICES\"",
                         *(["nvidia-smi --query-gpu=index,uuid,pci.bus_id,name --format=csv > gpu-inventory.csv"] if execution.device == "gpu" else []),
                         shlex.join(launch), ""])
    (directory / "run-abacus.sh").write_text(script, encoding="utf-8", newline="\n")
    conditions = {"calculation_kind": "static_dft_reference", "lattice_temperature_K": None,
                  "reference_temperature_K": 0, "applied_external_pressure_Pa": None,
                  "cell_constraint": "fixed_cell", "occupations": method.occupations,
                  "electronic_smearing_Ry": parameters.smearing_sigma_Ry,
                  "net_charge": int(method.net_charge),
                  "nelec": 0, "nelec_delta": -int(method.net_charge)}
    transfer_paths = [*prepared.files, "run-abacus.sh"]
    task_data = {
        "task_id": request["task_id"], "stage": "P4", "calculation": stage,
        "study_id": study["study_id"], "case_id": study["case_id"], "case_role": study["case_role"],
        "engine": "abacus", "engine_version": "3.10.1", "model_id": model.model_id,
        "basis_type": basis,
        "model_version": model.version, "model_path": str(Path(model_path).resolve()),
        "method_set": config["method_set"], "fixture": fixture, "production_label": False,
        "net_charge": int(method.net_charge),
        "nelec": 0, "nelec_delta": -int(method.net_charge),
        "method_input_qualified": input_qualification is not None and input_qualification["input_qualified"],
        "study_file": str(Path(study_path).resolve()), "calculation_conditions": conditions,
        "required_results": request["required_results"],
        "depends_on": [item["task_id"] for item in request["required_results"]],
        "input_transformation": transformation, "resource_request": resources,
        "runner": "slurm", "scheduler_job_id": None, "command": ["/bin/bash", "run-abacus.sh"],
        "environment_script": site["abacus"]["environment_script"],
        "transfer_paths": transfer_paths,
        "collect_paths": ["stdout.log", "stderr.log", f"OUT.{method.suffix}",
                          *(["gpu-inventory.csv"] if execution.device == "gpu" else [])],
        "status": "defined", "scientific_status": "not_calculated",
        "structure_source": str(directory / "input.extxyz"),
    }
    if basis == "lcao":
        task_data.update(numerical_orbital_ids=dict(config["numerical_orbital_ids"]),
                         numerical_orbitals=generated["numerical_orbitals"],
                         orbital_header_snapshot=generated["orbital_header_snapshot"],
                         lcao_output=config.get("lcao_output"))
    if "ionic_constraints" in generated:
        task_data["ionic_constraints"] = generated["ionic_constraints"]
    if "requested_artifacts" in generated:
        task_data["requested_artifacts"] = generated["requested_artifacts"]
    if grain_binding is not None:
        transfer_paths.extend(grain_binding["transfer_paths"])
        task_data["transfer_paths"] = transfer_paths
        task_data["grain_boundary_sources"] = grain_binding
        task_data["study"] = {
            "study_id": study["study_id"],
            "case_id": study["case_id"],
            "case_role": study["case_role"],
            "model": dict(study["model"]),
            "parent_study_id": study.get("parent_study_id"),
            "grain_boundary": study["grain_boundary"],
        }
    task = TaskRecord(task_data, directory / "task.json")
    task.record_event("create", study_file=str(Path(study_path)), method_file=str(Path(method_path)),
                      request_file=str(Path(request_path)), result="native_inputs_written_not_submitted")
    save_task(task)
    return task.data


def parse_abacus_task(task_path, site_path):
    """Parse the saved method's output directory and retain native conditions."""
    task = load_task(task_path)
    if task.data["scheduler_state"] != "COMPLETED" or task.data["exit_code"] != "0:0":
        raise ValueError("parsing scientific results requires saved native COMPLETED/0:0")
    directory = Path(task_path).resolve().parent
    method = _json(directory / "method.json")
    if "model_path" in task.data:
        model_path = Path(task.data["model_path"])
    else:
        # Historical Ni tasks predate the explicit model-path contract.
        workspace = Path(_json(site_path)["workspace"]["local"])
        model_path = workspace / "models" / task.data["model_id"] / task.data["model_version"]
    model = read_model_artifacts(model_path)
    if (model.model_id, model.version) != (task.data["model_id"], task.data["model_version"]):
        raise ValueError("recorded model path does not match task model ID and version")
    grain_binding = task.data.get("grain_boundary_sources")
    grain_provenance = None
    if grain_binding is not None:
        from .grain_task_sources import read_grain_task_sources

        grain_provenance = read_grain_task_sources(
            directory,
            grain_binding,
            study_id=task.data["study_id"],
            model_id=task.data["model_id"],
            model_version=task.data["model_version"],
            atom_ids=model.atom_ids,
        )
        snapshot = task.data.get("study")
        if not isinstance(snapshot, dict) or snapshot.get("grain_boundary") != grain_binding.get("study_grain_boundary"):
            raise ValueError("saved ABACUS Study grain-boundary snapshot differs from its source binding")
    model.atoms = read(directory / "input.extxyz")
    parsed = parse_abacus_outputs(directory, source_model=model, stage=method["stage"])
    data = parsed.as_dict()
    if method["stage"] == "relax":
        relaxation = parsed.relaxation
        if not isinstance(relaxation, dict):
            raise ValueError("ABACUS relax parsing did not produce a fixed-cell relaxation record")
        saved_task_constraints = task.data.get("ionic_constraints")
        if saved_task_constraints is not None and saved_task_constraints != relaxation["ionic_constraints"]:
            raise ValueError("saved TaskRecord ionic_constraints differ from parsed relaxation constraints")
        # Preserve the historical public max_force field as the per-atom
        # Euclidean norm.  The fixed-cell promotion criterion is recorded
        # separately in relaxation.max_free_force_component_eV_per_A.
        max_force = float(np.linalg.norm(parsed.forces_eV_per_A, axis=1).max())
        passed = relaxation["geometry_promotable"] is True
    else:
        max_force = float(np.linalg.norm(parsed.forces_eV_per_A, axis=1).max())
        passed = parsed.electronic_converged is True
    for values in (parsed.energy_eV, parsed.forces_eV_per_A, parsed.stress_GPa):
        if not np.isfinite(values).all():
            raise ValueError("nonfinite ABACUS energy, force, or stress")
    method_charge_raw = method.get("net_charge", 0)
    task_charge_raw = task.data.get("net_charge", method_charge_raw)
    if (
        isinstance(method_charge_raw, bool)
        or not isinstance(method_charge_raw, (int, np.integer))
        or isinstance(task_charge_raw, bool)
        or not isinstance(task_charge_raw, (int, np.integer))
    ):
        raise ValueError("saved ABACUS task net_charge must be an explicit integer")
    if int(task_charge_raw) != int(method_charge_raw):
        raise ValueError("saved ABACUS task and method net_charge disagree")
    task_charge = int(task_charge_raw)
    if task_charge != 0 and parsed.electronic_converged is True:
        # Bind original charge inputs, native adjusted counts and occupations
        # before publishing any charged result. This still grants no defect
        # formation-energy, VBM-alignment or correction qualification.
        electron_evidence = validate_charged_scf_electrons(directory, method, data)
        data["electron_count_evidence"] = electron_evidence
        data["numerical_qualification"] = False
        status = "raw_charged_scf_unqualified"
    else:
        status = ("converged_engineering_fixture" if task.data["fixture"] else "converged") if passed else "not_converged"
    data.update(task_id=task.task_id, scheduler_job_id=task.scheduler_job_id, method_set=task.data["method_set"],
                model_id=task.data["model_id"], version=task.data["model_version"],
                fixture=task.data["fixture"], production_label=False, max_force_eV_per_A=max_force,
                net_charge=task_charge,
                nelec=0, nelec_delta=-task_charge,
                scientific_qualification=False, production_qualification=False,
                scientific_status=status)
    if grain_binding is not None:
        data.update(
            study_id=task.data["study_id"],
            case_id=task.data["case_id"],
            case_role=task.data["case_role"],
            study_file=task.data["study_file"],
            study=task.data["study"],
            grain_boundary_sources=grain_binding,
            grain_boundary_provenance=grain_provenance,
        )
    write(directory / "final.extxyz", parsed.final_atoms)
    data["final_structure_file"] = str((directory / "final.extxyz").resolve())
    (directory / "result.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    task.set(scientific_status=status, result_file=str(directory / "result.json"))
    task.record_event("parse", scientific_status=status, result_file=str(directory / "result.json"))
    save_task(task)
    return data
