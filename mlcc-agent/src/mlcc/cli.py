"""Thin CLI for the MLCC task lifecycle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

import numpy as np

from .site_runner import RunnerError, runner_for_task
from .tasks import load_task
from .workflow import inspect_task
from .studies import load_study, study_summary
from .results import make_dft_result
from .abacus_tasks import create_abacus_task, parse_abacus_task
from .modeling import import_model_artifacts, read_model_artifacts
from .method_tasks import inspect_site_upf_headers, inspect_site_nao_headers, qualify_abacus_configuration
from .electronic import read_abacus_electronic_task, gaussian_dos
from .elastic import plan_elastic_strains, analyze_elastic_tasks, calibrate_tensor_stress
from .model_derivatives import derive_supercell_model, derive_defect_model
from .defect_thermodynamics import (chemical_potential_region, formation_energy_terms,
                                   binding_energy, neutral_formation_from_tasks)
from .property_delivery import (
    assess_design,
    deliver_chemical_references,
    deliver_potential_alignment,
    deliver_polarization_energy,
    deliver_polarization_strain,
    deliver_defect_references,
    deliver_electronic_properties,
    deliver_p5_properties,
    deliver_berry_polarization,
    deliver_md_properties,
    deliver_charge_properties,
)
from .berry_branch_review import (
    consume_berry_branch_review,
    review_berry_response_branches,
)
from .phonons import generate_phonon_displacement_plan, compute_harmonic_qpoints
from .phonon_forces import collect_phonon_forces
from .phonon_tasks import create_phonon_task
from .lammps_tasks import create_lammps_task, parse_lammps_task
from .md_trajectory import read_md_collection
from .md_conditions import read_md_conditions
from .md_sources import select_md_sources
from .dielectric_response import (
    aggregate_born_columns,
    calculate_ionic_dielectric,
    combine_dielectric_contributions,
    read_pyatb_static_electronic,
)
from .phonon_gamma import compute_gamma_fixed_cell_hessian


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mlcc")
    subparsers = parser.add_subparsers(dest="action", required=True)
    for name in ("prepare", "transfer", "submit", "status", "query", "cancel", "collect"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--task", required=True, type=Path)
        subparser.add_argument("--site", required=True, type=Path)
    subparser = subparsers.add_parser("resume-plan")
    subparser.add_argument("--task", required=True, type=Path)
    subparser.add_argument("--site", required=True, type=Path)
    subparser = subparsers.add_parser("study-plan")
    subparser.add_argument("--study", required=True, type=Path)
    subparser = subparsers.add_parser("deliver-result")
    subparser.add_argument("--task", required=True, type=Path)
    subparser.add_argument("--study", required=True, type=Path)
    subparser.add_argument("--conditions", required=True, type=Path)
    subparser = subparsers.add_parser("create-abacus")
    for name in ("study", "model", "method", "site", "request"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("parse-abacus")
    subparser.add_argument("--task", required=True, type=Path)
    subparser.add_argument("--site", required=True, type=Path)
    subparser = subparsers.add_parser("derive-relaxed-structure")
    for name in ("task", "parent-model", "study", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("create-relaxed-scf")
    for name in ("bridge", "method", "site", "request"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("create-berry-reference")
    for name in ("study", "model", "method", "site", "request"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("create-berry-nscf")
    for name in ("reference-task", "method", "site", "request"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("parse-berry")
    subparser.add_argument("--task", required=True, type=Path)
    subparser = subparsers.add_parser("create-berry-response")
    for name in ("study", "model", "method", "site", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("create-berry-response-nscf")
    for name in ("manifest", "site", "method", "request"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser.add_argument("--point-id", required=True)
    subparser = subparsers.add_parser("create-berry-strain")
    for name in ("study", "model", "method", "site", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("create-berry-strain-nscf")
    for name in ("manifest", "site", "method", "request"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser.add_argument("--point-id", required=True)
    subparser = subparsers.add_parser("ceramic-data")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("ceramic-training-bind")
    subparser.add_argument("--collection", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    for name in ("create-ceramic-training", "create-ceramic-lammps"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--request", required=True, type=Path)
    subparser = subparsers.add_parser("finalize-ceramic-training")
    subparser.add_argument("--task", required=True, type=Path)
    subparser.add_argument("--scheduler-record", required=True, type=Path)
    subparser = subparsers.add_parser("parse-ceramic-lammps")
    subparser.add_argument("--task", required=True, type=Path)
    subparser = subparsers.add_parser("import-model")
    subparser.add_argument(
        "--request",
        required=True,
        type=Path,
        help="JSON request file; a relative source_path is resolved from this file's directory",
    )
    subparser.add_argument("--output", required=True, type=Path)
    for name in ("derive-supercell", "derive-defect"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--parent", required=True, type=Path)
        subparser.add_argument("--request", required=True, type=Path)
        subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("create-grain-boundary")
    for name in ("parent", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("bind-grain-boundary-study")
    subparser.add_argument("--parent-study", required=True, type=Path)
    subparser.add_argument("--model", required=True, type=Path)
    subparser.add_argument("--study-id", required=True)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("create-interface")
    for name in ("side-a", "side-b", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("bind-interface-study")
    for name in ("model", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("inspect-upf")
    for name in ("method", "site", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("inspect-nao", help="read explicitly selected native NAO headers on the configured calculation site")
    for name in ("method", "site", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("qualify-method")
    for name in ("model", "method", "site", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("electronic")
    subparser.add_argument("--task", required=True, type=Path, help="completed task directory")
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("magnetic", help="consume saved native collinear ABACUS magnetic outputs")
    subparser.add_argument("--task", required=True, type=Path)
    subparser.add_argument("--electronic", type=Path, help="optional saved electronic product from the same task")
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("transport", help="compute tau-normalized transport from saved ABACUS bands")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "electronic-dielectric",
        help="read a source-bound PYATB direct-static electronic dielectric product",
    )
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("electrostatic-potential")
    subparser.add_argument("--task", required=True, type=Path, help="source-bound out_pot=2 SCF task")
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("electronic-dos")
    subparser.add_argument("--task", required=True, type=Path, help="completed task directory")
    for name in ("emin", "emax", "sigma"):
        subparser.add_argument(f"--{name}", required=True, type=float, help="energy in eV")
    subparser.add_argument("--points", required=True, type=int)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("elastic-plan")
    subparser.add_argument("--model", required=True, type=Path)
    subparser.add_argument("--amplitudes", required=True, type=float, nargs="+")
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("elastic-analyze")
    subparser.add_argument("--reference-task", required=True, type=Path)
    subparser.add_argument("--strained-tasks", required=True, type=Path, nargs="+")
    for name in ("calibration", "thresholds", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("elastic-calibrate")
    subparser.add_argument("--reference-task", required=True, type=Path)
    subparser.add_argument("--strained-tasks", required=True, type=Path, nargs="+")
    for name in ("thresholds", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("potential-alignment", "chemical-references", "chemical-potential-region", "formation-energy", "binding-energy", "compare-potential"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--request", required=True, type=Path)
        subparser.add_argument("--output", required=True, type=Path)
    for name in ("charge-correction", "charged-formation", "charge-transitions"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--request", required=True, type=Path)
        subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("neutral-formation")
    for name in ("host-task", "defect-task", "descriptor", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    chemical_source = subparser.add_mutually_exclusive_group()
    chemical_source.add_argument("--chemical-point", type=Path)
    chemical_source.add_argument("--chemical-reference-delivery", type=Path)
    subparser = subparsers.add_parser("create-neutral-defect-pair")
    for name in ("host-model", "defect-model", "host-study", "defect-study", "method", "site",
                 "host-request", "defect-request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser.add_argument("--defect-method", type=Path, help="explicit defect method; omitted uses the host --method")
    subparser.add_argument("--chemical-reference", type=Path, help="optional saved chemical reference; omitted leaves formation energy unresolved")
    subparser = subparsers.add_parser("deliver-properties")
    subparser.add_argument("--study", required=True, type=Path)
    delivery_source = subparser.add_mutually_exclusive_group(required=True)
    delivery_source.add_argument("--tasks", type=Path, nargs="+")
    delivery_source.add_argument("--magnetic", type=Path, help="deliver a saved magnetic product into its Study")
    delivery_source.add_argument("--transport", type=Path, help="deliver a saved electronic transport product into its Study")
    delivery_source.add_argument("--md-replicas", type=Path, help="deliver one saved MD scalar replica summary into its source Study")
    delivery_source.add_argument("--interface", type=Path, help="deliver explicit layered interface model and task input sources")
    delivery_source.add_argument("--interface-normal", type=Path, help="deliver a saved constrained normal response product")
    delivery_source.add_argument("--interface-tangential", type=Path, help="deliver a saved clamped tangential response product")
    delivery_source.add_argument("--interface-thermal", type=Path, help="deliver a saved interface thermal response product")
    delivery_source.add_argument("--interface-electrical", type=Path, help="deliver a saved interface potential response product")
    delivery_source.add_argument("--local-stress", type=Path, help="deliver saved explicit atom-group virial stress")
    delivery_source.add_argument("--thermal-stress", type=Path, help="deliver saved stress changes and explicit temperature/loading histories")
    delivery_source.add_argument("--domain-parameters", type=Path, help="deliver saved named domain parameters and their source states")
    delivery_source.add_argument("--p5", type=Path, help="consume saved P5 products into this Study delivery")
    delivery_source.add_argument("--dielectric-modes", type=Path, help="deliver saved Born/Gamma mode contributions into their Study")
    delivery_source.add_argument("--composition", type=Path, help="deliver a saved composition build or baseline/variant comparison")
    delivery_source.add_argument("--vacancy-migration", type=Path, help="deliver saved vacancy site occupancy and path events into their Study")
    delivery_source.add_argument("--continuum", type=Path, help="deliver a saved SI continuum parameter package into its Study")
    delivery_source.add_argument(
        "--defect-references", type=Path,
        help="consume saved host/defect electronic references into this Study delivery",
    )
    delivery_source.add_argument("--chemical-references", type=Path,
                                help="consume saved normalized chemical references into this Study")
    delivery_source.add_argument("--potential-alignment", type=Path,
                                help="consume saved regional potential-difference diagnostics into this Study")
    delivery_source.add_argument("--polarization-energy", type=Path,
                                help="consume a saved ordered SCF energy path into its parent Study")
    delivery_source.add_argument("--polarization-strain", type=Path,
                                help="deliver a saved clamped-ion strain response to its parent Study")
    delivery_source.add_argument("--charge-correction", type=Path,
                                help="deliver a saved charge-correction product into this Study")
    delivery_source.add_argument("--charged-formation", type=Path,
                                help="deliver a saved charged-formation product into this Study")
    delivery_source.add_argument("--charge-transitions", type=Path,
                                help="deliver a saved charge-transition collection into this Study")
    subparser.add_argument("--targets", type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "deliver-polarization",
        help="deliver one native single-direction Berry polarization observation",
    )
    for name in ("study", "task", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser.add_argument("--targets", type=Path)
    subparser = subparsers.add_parser(
        "polarization-path", help="consume an explicitly declared fixed-cell Berry path"
    )
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("berry-response", help="collect explicit fixed-cell displacement responses")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("polarization-energy", help="analyze a declared path of saved SCF energies")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("polarization-strain", help="consume saved Berry sources for explicit strain pairs")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "berry-branch-review",
        help="review numerical Berry branch suggestions without authorizing a branch",
    )
    subparser.add_argument("--response", required=True, type=Path, help="saved Berry response result JSON")
    subparser.add_argument("--policy", required=True, type=Path, help="explicit branch-review policy JSON")
    subparser.add_argument("--out", required=True, type=Path, help="new branch-review suggestion JSON")
    subparser = subparsers.add_parser(
        "berry-branch-consume",
        help="consume an externally reviewed Berry branch record without changing its request",
    )
    subparser.add_argument("--response", required=True, type=Path, help="saved Berry response result JSON")
    subparser.add_argument("--review", required=True, type=Path, help="external branch-review record JSON")
    subparser.add_argument("--out", required=True, type=Path, help="new branch-review consumption JSON")
    subparser = subparsers.add_parser(
        "born-charges",
        help="aggregate explicit Cartesian Born columns from saved Berry responses",
    )
    subparser.add_argument("--model", required=True, type=Path)
    subparser.add_argument("--responses", required=True, type=Path, nargs="+")
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "born-affine", help="consume an explicitly reviewed native LCAO Born affine family",
    )
    subparser.add_argument("--family", required=True, type=Path)
    subparser.add_argument("--review", type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "gamma-process", help="explicitly symmetrize native Gamma and remove only rigid translations",
    )
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "ionic-dielectric",
        help="calculate the fixed-cell ionic dielectric response from Born and Gamma inputs",
    )
    subparser.add_argument("--born", required=True, type=Path)
    subparser.add_argument("--gamma", type=Path)
    subparser.add_argument("--thresholds", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "dielectric",
        help="combine electronic and ionic dielectric contributions",
    )
    subparser.add_argument("--born", required=True, type=Path)
    subparser.add_argument("--electronic", type=Path)
    subparser.add_argument("--ionic", type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "phonon-gamma",
        help="convert an accepted harmonic result to a fixed-cell Gamma Hessian",
    )
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "phonon-nac", help="calculate the Gamma directional polar correction from saved force constants",
    )
    for name in ("request", "born", "electronic", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("assess-design")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("phonon-plan")
    for name in ("model", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("create-phonon")
    for name in ("plan", "study", "method", "site", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("phonon-forces", "phonon-qpoints"):
        subparser = subparsers.add_parser(name)
        for field in ("plan", "thresholds", "output"):
            subparser.add_argument(f"--{field}", required=True, type=Path)
        subparser.add_argument("--tasks", required=True, type=Path, nargs="*")
        subparser.add_argument(
            "--reference-task-record",
            type=Path,
            help="explicit P4 parent reference task.json or directory; omit for legacy P7 reference identity",
        )
        if name == "phonon-qpoints":
            subparser.add_argument("--qpoints", required=True, type=Path,
                                   help="JSON array of primitive reciprocal fractional q points")
    subparser = subparsers.add_parser("create-lammps-neb", help="prepare one explicitly defined multi-image LAMMPS NEB task")
    for name in ("study", "model", "final-model", "potential", "protocol", "site", "request"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("parse-lammps-neb", help="read and save the original NEB path and stopping records")
    subparser.add_argument("--task", required=True, type=Path)
    subparser = subparsers.add_parser("create-lammps")
    for name in ("study", "model", "potential", "protocol", "site", "request"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("parse-lammps")
    subparser.add_argument("--task", required=True, type=Path)
    subparser = subparsers.add_parser(
        "interface-normal", help="read rigid or explicitly clamped and internally relaxed normal response"
    )
    subparser.add_argument("--task", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("interface-thermal")
    for name in ("task", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("interface-tangential", help="read explicit fixed-cell clamped tangential response")
    subparser.add_argument("--task", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("dielectric-modes", help="resolve saved Born/Gamma modes in the explicit translation-free displacement gauge")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("plan-composition", help="compile an explicit composition and build its reference and variant models")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--models-output", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("compare-compositions", help="compare explicit saved properties from a baseline and its composition variants")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("vacancy-migration", help="analyze explicit vacancy site occupancy in saved MD or NEB frames")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("plan-configurations", help="build a finite set of explicitly seeded composition configurations")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--models-output", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("import-sqs", help="import an explicitly mapped external composition structure and preserve its source evidence")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--models-output", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("export-continuum", help="build a source-bound SI continuum parameter package from saved properties")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("export-comsol", help="export a saved parameter package and COMSOL template into a new directory")
    subparser.add_argument("--package", required=True, type=Path)
    subparser.add_argument("--output-dir", required=True, type=Path)
    subparser = subparsers.add_parser("interface-electrical", help="consume saved interface potential with explicit regions and direction")
    for name in ("study", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("local-stress")
    for name in ("task", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("thermal-stress", help="compare saved regional stress under explicit reference and histories")
    for name in ("study", "request", "output"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser = subparsers.add_parser("md-thermal-sources", help="bind saved native MD virial frames and observed temperatures to stress and history products")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output-dir", required=True, type=Path)
    subparser = subparsers.add_parser("bulk-thermodynamics", help="derive cell density and fixed-volume heat-capacity intervals from saved MD observations")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("bulk-thermal-response", help="derive density, heat-capacity and isotropic expansion intervals from saved NPT observations")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("lammps-elastic-response", help="derive stiffness and reference stress from saved static LAMMPS results")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("bulk-thermal-transport", help="derive directional heat flux, temperature gradient and conductivity from saved bulk NEMD observations")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("saved-domain-parameters", help="copy saved barriers, interface curves, stress, MSD, replica statistics or occupancy into named domain parameters")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("abacus-domain-parameters", help="copy saved ABACUS energy, forces, stress, electron count and sampled band gap into domain parameters")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "md-collection",
        help="read a completed fixed-format LAMMPS MD task into a complete native collection",
    )
    subparser.add_argument("--task", required=True, type=Path, help="completed MD task directory")
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "md-conditions",
        help="validate an accepted MD collection and select declared post-processing windows",
    )
    subparser.add_argument("--collection", required=True, type=Path,
                           help="accepted mlcc.md-collection.v1 JSON")
    subparser.add_argument("--window-request", type=Path,
                           help="optional mlcc.md-window-request.v1 JSON")
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser(
        "md-sources",
        help="select explicit model, potential and element sources from accepted MD collections",
    )
    subparser.add_argument("--request", required=True, type=Path,
                           help="JSON source-selection request")
    subparser.add_argument("--output", required=True, type=Path)
    subparser = subparsers.add_parser("deliver-md", help="deliver one native MD task through conditions, sources and explicit thermo/RDF/MSD requests")
    for name in ("study", "task", "request", "output-directory"):
        subparser.add_argument(f"--{name}", required=True, type=Path)
    subparser.add_argument("--window-request", type=Path)
    subparser.add_argument("--targets", type=Path)
    subparser.add_argument("--collection", type=Path, help="consume an existing collection bound to this task without reparsing native logs")
    subparser = subparsers.add_parser("md-replicas", help="summarize one explicit scalar observable from saved MD deliveries")
    subparser.add_argument("--request", required=True, type=Path)
    subparser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "md-thermal-sources":
            from .thermal_stress_sources import build_md_thermal_sources
            result = build_md_thermal_sources(args.request, args.output_dir)
            print(json.dumps({"output": result["artifacts"]["manifest"], "status": result["status"]}, ensure_ascii=False))
            return 0
        if args.action == "deliver-md":
            result = deliver_md_properties(args.study, args.task, args.request, args.output_directory,
                                           window_request_path=args.window_request, targets_path=args.targets,
                                           collection_path=args.collection)
            print(json.dumps({"output": result["artifacts"]["delivery"], "status": result["status"]}, ensure_ascii=False))
            return 0
        if args.action in ("berry-branch-review", "berry-branch-consume"):
            response = json.loads(args.response.read_text(encoding="utf-8"))
            if args.action == "berry-branch-review":
                policy = json.loads(args.policy.read_text(encoding="utf-8"))
                result = review_berry_response_branches(response, policy)
            else:
                review = json.loads(args.review.read_text(encoding="utf-8"))
                result = consume_berry_branch_review(response, review)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
            print(
                json.dumps(
                    {"output": str(args.out.resolve()), "status": result.get("decision", "written")},
                    ensure_ascii=False,
                )
            )
            return 0
        if args.action in ("electronic", "magnetic", "transport", "electronic-dielectric", "electronic-dos", "electrostatic-potential", "potential-alignment", "chemical-references", "elastic-plan", "elastic-analyze",
                           "elastic-calibrate", "chemical-potential-region", "formation-energy",
                           "binding-energy", "compare-potential", "neutral-formation", "deliver-properties", "assess-design",
                           "charge-correction", "charged-formation", "charge-transitions",
                           "deliver-polarization", "polarization-path", "polarization-energy", "polarization-strain", "berry-response", "phonon-forces", "phonon-qpoints", "md-collection", "md-conditions", "md-sources", "md-replicas",
                           "born-charges", "born-affine", "gamma-process", "ionic-dielectric", "dielectric", "phonon-gamma", "phonon-nac", "thermal-stress", "bulk-thermodynamics", "bulk-thermal-response", "lammps-elastic-response", "bulk-thermal-transport", "saved-domain-parameters", "abacus-domain-parameters"):
            if args.action in ("phonon-forces", "phonon-qpoints"):
                thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
                collection = collect_phonon_forces(
                    args.plan,
                    args.tasks,
                    thresholds,
                    reference_task_record=args.reference_task_record,
                )
                result = collection
                if args.action == "phonon-qpoints" and collection["ready_for_harmonic"]:
                    qpoints = json.loads(args.qpoints.read_text(encoding="utf-8"))
                    result = compute_harmonic_qpoints(args.plan, collection["force_bundle"], qpoints)
                    result.update(status="native_harmonic_unqualified", native_force_collection=collection)
            elif args.action == "electronic":
                result = read_abacus_electronic_task(args.task)
            elif args.action == "magnetic":
                from .magnetic_response import read_abacus_magnetic_task
                result = read_abacus_magnetic_task(args.task, args.electronic)
            elif args.action == "transport":
                from .transport import build_transport
                result = build_transport(args.request)
            elif args.action == "thermal-stress":
                from .thermal_stress_sources import build_thermal_stress
                result = build_thermal_stress(args.study, args.request)
            elif args.action == "bulk-thermodynamics":
                from .bulk_thermodynamics import build_bulk_thermodynamics
                result = build_bulk_thermodynamics(args.request)
            elif args.action == "bulk-thermal-response":
                from .bulk_thermal_response import build_bulk_thermal_response
                result = build_bulk_thermal_response(args.request)
            elif args.action == "lammps-elastic-response":
                from .lammps_elastic_response import build_lammps_elastic_response
                result = build_lammps_elastic_response(args.request)
            elif args.action == "bulk-thermal-transport":
                from .bulk_thermal_transport import build_bulk_thermal_transport
                result = build_bulk_thermal_transport(args.request)
            elif args.action == "saved-domain-parameters":
                from .saved_domain_parameters import build_saved_domain_parameters
                result = build_saved_domain_parameters(args.request)
            elif args.action == "abacus-domain-parameters":
                from .abacus_domain_parameters import build_abacus_domain_parameters
                result = build_abacus_domain_parameters(args.request)
            elif args.action == "electronic-dielectric":
                result = read_pyatb_static_electronic(args.request)
            elif args.action == "electrostatic-potential":
                from .electrostatic_potential import read_abacus_electrostatic_task
                result = read_abacus_electrostatic_task(args.task)
            elif args.action == "chemical-references":
                from .chemical_references import build_chemical_reference_set
                result = build_chemical_reference_set(args.request)
            elif args.action == "potential-alignment":
                from .potential_alignment import build_potential_alignment
                result = build_potential_alignment(args.request)
            elif args.action == "charge-correction":
                from .charge_correction import build_charge_correction
                result = build_charge_correction(args.request)
            elif args.action == "charged-formation":
                from .charged_defect import build_charged_formation
                result = build_charged_formation(args.request)
            elif args.action == "charge-transitions":
                from .charge_transition_adapter import build_charge_transitions
                result = build_charge_transitions(args.request)
            elif args.action == "electronic-dos":
                if args.points < 2:
                    raise ValueError("DOS points must be at least two")
                result = gaussian_dos(read_abacus_electronic_task(args.task),
                                      np.linspace(args.emin, args.emax, args.points), args.sigma)
            elif args.action == "elastic-plan":
                result = plan_elastic_strains(read_model_artifacts(args.model), args.amplitudes)
            elif args.action in ("elastic-analyze", "elastic-calibrate"):
                thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
                if args.action == "elastic-calibrate":
                    result = calibrate_tensor_stress(args.reference_task, args.strained_tasks, thresholds)
                else:
                    result = analyze_elastic_tasks(args.reference_task, args.strained_tasks,
                                                   args.calibration, thresholds)
            elif args.action == "neutral-formation":
                point = (
                    None
                    if args.chemical_point is None
                    else json.loads(args.chemical_point.read_text(encoding="utf-8"))
                )
                if args.chemical_reference_delivery is not None:
                    delivery = json.loads(args.chemical_reference_delivery.read_text(encoding="utf-8"))
                    if delivery["schema"] != "mlcc.chemical-reference-delivery.v1":
                        raise ValueError("unsupported chemical-reference delivery")
                    host_path = args.host_task.resolve()
                    if host_path.is_file():
                        host_path = host_path.parent
                    if host_path != Path(delivery["host"]["source"]["task_path"]).resolve():
                        raise ValueError("chemical-reference delivery host differs from requested host task")
                    point = delivery["chemical_point"]
                result = neutral_formation_from_tasks(args.host_task, args.defect_task, point, args.descriptor)
            elif args.action == "deliver-properties":
                if args.domain_parameters is not None:
                    from .property_delivery import deliver_domain_parameters
                    if args.targets is not None:
                        raise ValueError("domain parameter delivery does not assess design targets")
                    result = deliver_domain_parameters(args.study, args.domain_parameters)
                elif args.thermal_stress is not None:
                    from .property_delivery import deliver_thermal_stress
                    if args.targets is not None:
                        raise ValueError("thermal stress delivery does not assess design targets")
                    result = deliver_thermal_stress(args.study, args.thermal_stress)
                elif args.md_replicas is not None:
                    from .property_delivery import deliver_md_replica_properties
                    if args.targets is not None:
                        raise ValueError("MD replica delivery does not assess design targets")
                    result = deliver_md_replica_properties(args.study, args.md_replicas)
                elif args.local_stress is not None:
                    from .property_delivery import deliver_local_stress
                    if args.targets is not None:
                        raise ValueError("local stress delivery does not assess design targets")
                    result = deliver_local_stress(args.study, args.local_stress)
                elif args.interface_electrical is not None:
                    from .property_delivery import deliver_interface_electrical
                    if args.targets is not None:
                        raise ValueError("interface electrical delivery does not assess design targets")
                    result = deliver_interface_electrical(args.study, args.interface_electrical)
                elif args.interface_thermal is not None:
                    from .property_delivery import deliver_interface_thermal
                    if args.targets is not None:
                        raise ValueError("interface thermal delivery does not assess design targets")
                    result = deliver_interface_thermal(args.study, args.interface_thermal)
                elif args.interface_tangential is not None:
                    from .property_delivery import deliver_interface_tangential
                    if args.targets is not None:
                        raise ValueError("constrained tangential response delivery does not assess design targets")
                    result = deliver_interface_tangential(args.study, args.interface_tangential)
                elif args.interface_normal is not None:
                    from .property_delivery import deliver_interface_normal
                    if args.targets is not None:
                        raise ValueError("constrained normal response delivery does not assess design targets")
                    result = deliver_interface_normal(args.study, args.interface_normal)
                elif args.interface is not None:
                    from .property_delivery import deliver_interface_inputs
                    if args.targets is not None:
                        raise ValueError("interface input delivery does not assess response targets")
                    result = deliver_interface_inputs(args.study, args.interface)
                elif args.transport is not None:
                    from .property_delivery import deliver_transport_properties
                    result = deliver_transport_properties(args.study, args.transport, args.targets)
                elif args.magnetic is not None:
                    from .property_delivery import deliver_magnetic_properties
                    result = deliver_magnetic_properties(args.study, args.magnetic, args.targets)
                elif args.continuum is not None:
                    from .property_delivery import deliver_continuum_package
                    if args.targets is not None:
                        raise ValueError("continuum delivery does not assess design targets")
                    result = deliver_continuum_package(args.study, args.continuum)
                elif args.vacancy_migration is not None:
                    from .property_delivery import deliver_vacancy_migration
                    if args.targets is not None:
                        raise ValueError("vacancy migration delivery does not assess design targets")
                    result = deliver_vacancy_migration(args.study, args.vacancy_migration)
                elif args.composition is not None:
                    from .property_delivery import deliver_composition_product
                    if args.targets is not None:
                        raise ValueError("composition delivery does not assess design targets")
                    result = deliver_composition_product(args.study, args.composition)
                elif args.dielectric_modes is not None:
                    from .property_delivery import deliver_dielectric_modes
                    if args.targets is not None:
                        raise ValueError("dielectric mode delivery does not assess design targets")
                    result = deliver_dielectric_modes(args.study, args.dielectric_modes)
                elif args.p5 is not None:
                    result = deliver_p5_properties(args.study, args.p5, args.targets)
                elif args.charge_correction is not None:
                    result = deliver_charge_properties(args.study, args.charge_correction, args.targets)
                elif args.charged_formation is not None:
                    result = deliver_charge_properties(args.study, args.charged_formation, args.targets)
                elif args.charge_transitions is not None:
                    result = deliver_charge_properties(args.study, args.charge_transitions, args.targets)
                elif args.defect_references is not None:
                    result = deliver_defect_references(args.study, args.defect_references, args.targets)
                elif args.chemical_references is not None:
                    result = deliver_chemical_references(args.study, args.chemical_references, args.targets)
                elif args.potential_alignment is not None:
                    result = deliver_potential_alignment(args.study, args.potential_alignment, args.targets)
                elif args.polarization_energy is not None:
                    result = deliver_polarization_energy(args.study, args.polarization_energy, args.targets)
                elif args.polarization_strain is not None:
                    result = deliver_polarization_strain(args.study, args.polarization_strain, args.targets)
                else:
                    result = deliver_electronic_properties(args.study, args.tasks, args.targets)
            elif args.action == "deliver-polarization":
                result = deliver_berry_polarization(args.study, args.task, args.targets)
            elif args.action == "polarization-path":
                from .polarization import analyze_polarization_path
                result = analyze_polarization_path(args.request)
            elif args.action == "polarization-energy":
                from .polarization_energy import analyze_polarization_energy_path
                result = analyze_polarization_energy_path(args.request)
            elif args.action == "polarization-strain":
                from .polarization_strain import analyze_polarization_strain
                result = analyze_polarization_strain(args.request)
            elif args.action == "berry-response":
                from .berry_response_results import analyze_berry_displacement_response
                result = analyze_berry_displacement_response(args.request)
            elif args.action == "born-charges":
                result = aggregate_born_columns(args.model, args.responses)
            elif args.action == "born-affine":
                from .born_affine import consume_native_born_review
                result = consume_native_born_review(args.family, args.review)
            elif args.action == "gamma-process":
                from .gamma_processing import process_native_gamma
                result = process_native_gamma(args.request)
            elif args.action == "ionic-dielectric":
                born = json.loads(args.born.read_text(encoding="utf-8"))
                gamma = None if args.gamma is None else json.loads(args.gamma.read_text(encoding="utf-8"))
                thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
                result = calculate_ionic_dielectric(born, gamma, thresholds=thresholds)
            elif args.action == "dielectric":
                born = json.loads(args.born.read_text(encoding="utf-8"))
                electronic = None if args.electronic is None else json.loads(args.electronic.read_text(encoding="utf-8"))
                ionic = None if args.ionic is None else json.loads(args.ionic.read_text(encoding="utf-8"))
                result = combine_dielectric_contributions(born, electronic, ionic, electronic_path=args.electronic)
            elif args.action == "phonon-nac":
                from .phonon_nac import compute_gamma_directional_nac
                result = compute_gamma_directional_nac(
                    json.loads(args.request.read_text(encoding="utf-8")),
                    json.loads(args.born.read_text(encoding="utf-8")),
                    json.loads(args.electronic.read_text(encoding="utf-8")),
                    born_path=args.born,
                    electronic_path=args.electronic,
                )
            elif args.action == "phonon-gamma":
                request = json.loads(args.request.read_text(encoding="utf-8"))
                result = compute_gamma_fixed_cell_hessian(
                    request["harmonic_result_path"],
                    request["plan_path"],
                    parent=request["parent"],
                    method_identity=request["method_identity"],
                    source_binding=request["source_binding"],
                    geometry_tolerance_angstrom=request["geometry_tolerance_angstrom"],
                    mass_tolerance_amu=request["mass_tolerance_amu"],
                    volume_tolerance_A3=request["volume_tolerance_A3"],
                    dynamical_imag_tolerance=request["dynamical_imag_tolerance"],
                    output_path=None,
                )
            elif args.action == "md-collection":
                result = read_md_collection(args.task)
            elif args.action == "md-conditions":
                result = read_md_conditions(args.collection, args.window_request)
            else:
                request = json.loads(args.request.read_text(encoding="utf-8"))
                if args.action == "chemical-potential-region":
                    result = chemical_potential_region(request)
                elif args.action == "formation-energy":
                    result = formation_energy_terms(**request)
                elif args.action == "assess-design":
                    result = assess_design(request["requirements"], request["observables"])
                elif args.action == "compare-potential":
                    from .potential_qualification import compare_potential_tasks
                    result = compare_potential_tasks(
                        request["pairs"], request["reference_pair_id"], request["tolerances"],
                        abacus_stress_mapping=request.get("abacus_stress_mapping"))
                elif args.action == "md-sources":
                    result = select_md_sources(**request)
                elif args.action == "md-replicas":
                    from .md_replica import summarize_md_replicas
                    result = summarize_md_replicas(request)
                    result.update(request_path=str(args.request.resolve()), analysis_request=request,
                                  analysis_scheduler_job_id=os.environ.get("SLURM_JOB_ID"))
                else:
                    result = binding_energy(request["formation_records"], request["stoichiometric_coefficients"])
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
            print(json.dumps({"output": str(args.output.resolve()),
                              "status": result.get("status", "written")}, ensure_ascii=False))
            return 1 if str(result.get("status", "")).startswith("blocked") else 0
        elif args.action in ("inspect-upf", "inspect-nao", "qualify-method"):
            if args.action == "inspect-upf":
                result = inspect_site_upf_headers(args.method, args.site)
            elif args.action == "inspect-nao":
                result = inspect_site_nao_headers(args.method, args.site)
            else:
                result = qualify_abacus_configuration(args.model, args.method, args.site)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if args.action in ("inspect-upf", "inspect-nao") or result["input_qualified"] else 1
        elif args.action == "create-abacus":
            result = create_abacus_task(study_path=args.study, model_path=args.model,
                                       method_path=args.method, site_path=args.site, request_path=args.request)
        elif args.action == "derive-relaxed-structure":
            from .relaxed_structure_bridge import derive_relaxed_structure
            result = derive_relaxed_structure(
                task_path=args.task, parent_model_path=args.parent_model, study_path=args.study,
                request_path=args.request, output_path=args.output)
        elif args.action == "create-relaxed-scf":
            from .relaxed_structure_bridge import create_relaxed_scf
            result = create_relaxed_scf(
                bridge_path=args.bridge, method_path=args.method,
                site_path=args.site, request_path=args.request)
        elif args.action == "create-neutral-defect-pair":
            from .defect_tasks import create_neutral_defect_task_pair
            result = create_neutral_defect_task_pair(
                host_model_path=args.host_model, defect_model_path=args.defect_model,
                host_study_path=args.host_study, defect_study_path=args.defect_study,
                method_path=args.method, site_path=args.site,
                defect_method_path=args.defect_method,
                host_request_path=args.host_request, defect_request_path=args.defect_request,
                chemical_reference_path=args.chemical_reference, output_path=args.output)
        elif args.action == "create-berry-reference":
            from .berry_tasks import create_berry_reference_task
            result = create_berry_reference_task(study_path=args.study, model_path=args.model,
                                                method_path=args.method, site_path=args.site,
                                                request_path=args.request)
        elif args.action == "create-berry-nscf":
            from .berry_tasks import create_berry_nscf_task
            result = create_berry_nscf_task(reference_task_path=args.reference_task,
                                           method_path=args.method, site_path=args.site,
                                           request_path=args.request)
        elif args.action == "parse-berry":
            from .berry_results import parse_berry_task
            result = parse_berry_task(args.task)
        elif args.action == "create-berry-response":
            from .berry_response import create_berry_displacement_response
            result = create_berry_displacement_response(
                args.study, args.model, args.method, args.site, args.request, args.output)
        elif args.action == "create-berry-response-nscf":
            from .berry_response import create_berry_response_nscf
            result = create_berry_response_nscf(
                args.manifest, args.point_id, args.site, args.method, args.request)
        elif args.action == "create-berry-strain":
            from .berry_strain_response import create_berry_strain_response
            result = create_berry_strain_response(
                args.study, args.model, args.method, args.site, args.request, args.output)
        elif args.action == "create-berry-strain-nscf":
            from .berry_strain_response import create_berry_strain_nscf
            result = create_berry_strain_nscf(
                args.manifest, args.point_id, args.site, args.method, args.request)
        elif args.action == "ceramic-data":
            from .ceramic_data import convert_ceramic_systems
            result = convert_ceramic_systems(args.request, args.output)
        elif args.action == "ceramic-training-bind":
            from .ceramic_training import bind_ceramic_training_dataset
            result = bind_ceramic_training_dataset(args.collection, args.output)
        elif args.action == "create-ceramic-training":
            from .ceramic_training import create_ceramic_training_task
            from mlcc_deepmd.training import DeepMDTrainingConfig
            request = json.loads(args.request.read_text(encoding="utf-8"))
            workspace = Path(request["workspace"])
            task_id = request["task_id"]
            config = DeepMDTrainingConfig.from_input_json(
                request["input_file"], workdir=workspace / "tasks" / task_id,
                **request["training_config"])
            task = create_ceramic_training_task(
                workspace, task_id, config, request["input_file"],
                request["collection"], request["interface_acceptance"],
                account=request["account"])
            result = task.data
        elif args.action == "finalize-ceramic-training":
            from .ceramic_training import finalize_ceramic_training_task
            scheduler_record = json.loads(args.scheduler_record.read_text(encoding="utf-8"))
            result = finalize_ceramic_training_task(args.task, scheduler_record).data
        elif args.action == "create-ceramic-lammps":
            from .ceramic_md import create_ceramic_lammps_task
            request = json.loads(args.request.read_text(encoding="utf-8"))
            result = create_ceramic_lammps_task(
                request["workspace"], request["task_id"], request["collection"],
                request["system_id"], request["model_card"], request["protocol"],
                request["site"], request["resource_request"]).data
        elif args.action == "parse-ceramic-lammps":
            from .ceramic_md import finalize_ceramic_lammps_task
            result = finalize_ceramic_lammps_task(args.task)
        elif args.action == "phonon-plan":
            request = json.loads(args.request.read_text(encoding="utf-8"))
            result = generate_phonon_displacement_plan(args.model, request, args.output)
        elif args.action == "create-phonon":
            result = create_phonon_task(plan_path=args.plan, study_path=args.study,
                                       method_path=args.method, site_path=args.site,
                                       request_path=args.request, output_path=args.output)
        elif args.action == "create-lammps-neb":
            from .neb_tasks import create_lammps_neb_task
            result = create_lammps_neb_task(study_path=args.study, model_path=args.model,
                                           final_model_path=args.final_model, potential_path=args.potential,
                                           protocol_path=args.protocol, site_path=args.site, request_path=args.request)
        elif args.action == "parse-lammps-neb":
            from .neb_tasks import parse_lammps_neb_task
            result = parse_lammps_neb_task(args.task)
        elif args.action == "create-lammps":
            result = create_lammps_task(study_path=args.study, model_path=args.model,
                                       potential_path=args.potential, protocol_path=args.protocol,
                                       site_path=args.site, request_path=args.request)
        elif args.action == "parse-lammps":
            result = parse_lammps_task(args.task)
        elif args.action == "create-grain-boundary":
            from .grain_boundaries import build_grain_boundary
            request = json.loads(args.request.read_text(encoding="utf-8"))
            model = build_grain_boundary(args.parent, request, args.output)
            result = {
                "model_id": model.model_id,
                "version": model.version,
                "artifact_dir": str(model.artifact_dir.resolve()),
                "metadata": model.metadata,
            }
        elif args.action == "local-stress":
            from .local_stress_tasks import read_local_stress_task
            result = read_local_stress_task(args.task, args.request)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "export-continuum":
            from .continuum_parameters import build_continuum_parameter_package
            result = build_continuum_parameter_package(args.request)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "export-comsol":
            from .comsol_export import export_comsol_material_package
            result = export_comsol_material_package(args.package, args.output_dir)
        elif args.action == "plan-composition":
            from .dopant_composition import build_composition_model
            result = build_composition_model(args.request, args.models_output)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "vacancy-migration":
            from .vacancy_migration import analyze_vacancy_migration_request
            result = analyze_vacancy_migration_request(args.request)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "plan-configurations":
            from .composition_configurations import build_composition_configurations
            result = build_composition_configurations(args.request, args.models_output)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "import-sqs":
            from .composition_sqs_import import import_sqs_configuration
            result = import_sqs_configuration(args.request, args.models_output)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "compare-compositions":
            from .composition_comparison import analyze_composition_comparison_request
            result = analyze_composition_comparison_request(args.request)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "dielectric-modes":
            from .dielectric_modes import analyze_dielectric_modes_request
            result = analyze_dielectric_modes_request(args.request)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "interface-electrical":
            from .interface_electrical_sources import build_interface_electrical_product
            study = json.loads(args.study.read_text(encoding="utf-8"))
            request = json.loads(args.request.read_text(encoding="utf-8"))
            request_path, study_path = args.request.resolve(), args.study.resolve()
            for field in ("potential_path", "reference_potential_path"):
                if request.get(field) is not None:
                    source_path = Path(request[field])
                    request[field] = str((source_path if source_path.is_absolute() else request_path.parent / source_path).resolve())
            result = build_interface_electrical_product(study, request)
            result["request_path"], result["study_path"] = str(request_path), str(study_path)
            result["source_refs"].extend([str(request_path), str(study_path)])
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "interface-thermal":
            from .interface_thermal_tasks import read_interface_thermal_task
            result = read_interface_thermal_task(args.task, args.request)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "interface-tangential":
            from .interface_tangential_tasks import read_interface_tangential_task
            result = read_interface_tangential_task(args.task)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "interface-normal":
            from .interface_normal_tasks import read_interface_normal_task
            result = read_interface_normal_task(args.task)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        elif args.action == "create-interface":
            from .interfaces import build_layered_interface
            request = json.loads(args.request.read_text(encoding="utf-8"))
            model = build_layered_interface(args.side_a, args.side_b, request, args.output)
            result = {"model_id": model.model_id, "version": model.version,
                      "artifact_dir": str(model.artifact_dir.resolve()), "metadata": model.metadata}
        elif args.action == "bind-interface-study":
            from .interface_sources import bind_interface_study
            request = json.loads(args.request.read_text(encoding="utf-8"))
            result = bind_interface_study(args.model, request, args.output)
        elif args.action == "bind-grain-boundary-study":
            from .grain_studies import bind_grain_boundary_study
            result = bind_grain_boundary_study(
                args.parent_study, args.model, args.study_id, args.output
            )
        elif args.action in ("derive-supercell", "derive-defect"):
            request = json.loads(args.request.read_text(encoding="utf-8"))
            derive = derive_supercell_model if args.action == "derive-supercell" else derive_defect_model
            model = derive(args.parent, request, args.output)
            result = {"model_id": model.model_id, "version": model.version,
                      "artifact_dir": str(model.artifact_dir.resolve()), "metadata": model.metadata}
        elif args.action == "import-model":
            request = json.loads(args.request.read_text(encoding="utf-8"))
            if isinstance(request, dict) and isinstance(request.get("source_path"), str):
                source_path = Path(request["source_path"])
                if not source_path.is_absolute():
                    request = dict(request)
                    request["source_path"] = str((args.request.parent / source_path).resolve())
            imported = import_model_artifacts(request, args.output)
            result = {
                "model_id": imported.model_id,
                "version": imported.version,
                "artifact_dir": str(imported.artifact_dir),
                "metadata": imported.metadata,
            }
        elif args.action == "parse-abacus":
            result = parse_abacus_task(args.task, args.site)
        elif args.action == "study-plan":
            result = study_summary(load_study(args.study))
        elif args.action == "deliver-result":
            conditions = json.loads(args.conditions.read_text(encoding="utf-8"))
            result = make_dft_result(load_task(args.task), load_study(args.study), conditions)
        elif args.action == "resume-plan":
            result = inspect_task(load_task(args.task))
        else:
            runner, task = runner_for_task(args.site, args.task)
            method = getattr(runner, "query" if args.action == "status" else args.action)
            result = method(task)
    except (RunnerError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

