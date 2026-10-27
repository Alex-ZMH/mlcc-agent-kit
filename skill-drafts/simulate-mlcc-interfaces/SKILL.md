---
name: simulate-mlcc-interfaces
description: >-
  Plan, build, and review ABACUS DFT and LAMMPS MD studies of ceramic/metal
  interfaces in multilayer ceramic capacitors, including retained polymer
  interlayers or temporary binders and transfer of atomistic results to
  thermomechanical fracture models. Use for MLCC interface mismatch,
  residual stress, adhesion, cracking, and delamination workflows.
---

# Simulate MLCC interfaces

This is a project-local discussion draft. Its reference case is BaTiO3/Ni,
with separate retained-polymer and temporary-binder branches. Preserve the
user's actual materials and process when those become available.

Historical scientific background only: ../../PLAN.md is the current stage
plan and ../../mlcc-agent contains the portable domain definitions. VASP is
the initial engineering bootstrap, followed by explicit ABACUS production
migration. Continuum fracture discussion below is a future parameter-handoff
reference, not a current FEM/phase-field implementation or a LAMMPS capability.

## Choose the physical question

Identify the failure observable, processing or service stage, material
chemistry, temperature/load history, and available experimental constraints.
Proceed with explicit provisional assumptions when information is missing.
Ask only for information that changes the physical model or execution.

This skill covers the interface/mechanics branch. The project now also
includes dielectric, ferroelectric, defect, thermal, magnetic when warranted,
and device electrical planning. Start from explicit host/phase/dopant
selection for those broader requests, then use this branch for interface
properties. Both polymer roles remain requested; polymer chemistry is not
selected. PI and PVB are candidate examples, not confirmed materials or
demonstrated remedies.

Read [the mechanics workflow](references/mechanics-workflow.md) for the
case design, calculation stages, parameter transfer, and acceptance gates.
Read [the source evidence](references/open-source-evidence.md) when choosing
software or checking a claimed existing implementation.
Use [the project contract](references/project-contract.json) to distinguish
confirmed decisions, proposed settings, and parameters awaiting evidence.

Implement this branch with direct functions and explicit inputs. The user
prohibits defensive programming and checksum verification. Record readable
model versions and resource paths; propagate failures without automatic
retries, invented defaults, or switching calculators.

## Build physically distinct models

- Establish BaTiO3 and Ni bulk references before interpreting an interface.
- Distinguish crystallographic mismatch, thermal expansion mismatch,
  differential sintering shrinkage, and transformation strain.
- Generate and rank small commensurate cells; record the full in-plane strain
  tensors, orientation, termination, stoichiometry, and initial registry.
  Do not force a small coherent interface to represent a relaxed polycrystal.
- Treat the retained polymer as a post-sintering assembly hypothesis unless
  a compatible processing route is established. Its two interfaces and its
  own cohesive failure are separate candidate crack paths.
- For a temporary binder, transfer the post-debinding contact, porosity,
  and residue state into the later model. Removing polymer atoms is not
  a validated simulation of burnout or sintering.

## Establish ABACUS reference calculations

Record the code version, functional, dispersion treatment, pseudopotential
and orbital versions/paths, spin state, occupation/smearing settings, basis,
k-point density, convergence thresholds, and relaxation constraints.
Validate Ni magnetism and BaTiO3 structure for the temperature regime.
Use a common theoretical level for a connected training dataset; a
multi-level correction requires an explicit separate formulation.

For interfaces, converge the physical observables: adhesion/separation work,
traction, registry preference, and relaxed structure. Check LCAO against
PW anchors for interface binding and stress before using LCAO at scale.
Compare separated fragments at the same in-plane cell and consistent
composition. Count the interfaces actually separated and account for
inequivalent interfaces or polar terminations.

## Select and qualify the force model

Prefer an ABACUS-labeled model with explicit coverage of the required
bulk, surface, interface, separation, shear, and polymer environments.
Do not assume a bulk potential, a universal model, an EAM/oxide/polymer
mixture, or a ReaxFF parameter file is qualified for the target interface.

A calibrated hybrid model may be appropriate for a declared nonreactive
regime. Check all cross interactions, many-body scope, charges, long-range
terms, and excluded bonded interactions against DFT. Reactive debinding,
metal oxidation, and bond rupture need their own validated coverage.

Split data by parent trajectory, chemistry, interface registry, loading
path, and temperature where useful. Adjacent frames from one trajectory
are not independent test evidence. Inspect errors on rare interface atoms
and mechanical observables rather than accepting an average force error.

Use committee disagreement to acquire data, calibrated against withheld
DFT errors. Add stretched configurations and separated surfaces deliberately;
equilibrium AIMD does not supply fracture coverage. Check cutoff and
cell-size dependence for electrostatic and dispersion interactions.

## Run MD for transferable observables

Use bulk NPT for thermal reference properties when physically appropriate.
Do not barostat a vacuum slab or an opening interface as if it were bulk.
For opening/shear, define grips, thermostat regions, traction area, lateral
constraints, unloading, and work accounting. Check size, timestep, loading
rate, and independent polymer realizations.

Report intrinsic separation work, traction-separation response, polymer
relaxation, Ni plasticity, and apparent work as different observables.
High-rate MD work is rate-specific; transfer laboratory-rate dissipation
through a calibrated constitutive law rather than relabeling it as Gc.

## Transfer into fracture and thermal mechanics

Maintain a parameter ledger with value, unit, temperature, loading rate,
orientation, source calculation, uncertainty, and validity envelope.
The project contract gives the initial record shape.

Use anisotropic elasticity and thermal eigenstrain when warranted. Model
Ni plasticity and polymer viscoelasticity when they affect stress relief.
Derive residual stress from a process history and a justified stress-free
reference state. A relaxed DFT cell does not define device residual stress.

DFT reversible separation work Wsep, MD apparent separation work,
thermodynamic interface energy, and effective fracture resistance Gc are
different quantities. Avoid counting Ni plasticity or polymer dissipation
both inside Gc and again in the continuum constitutive law.

Use bulk phase-field fracture plus explicit cohesive interfaces as a
practical first model. If using diffuse interface fracture instead, verify
that strength and dissipated energy are reproduced as interface width,
regularization length, and mesh change. Do not assign the atomistic
interface width as the phase-field crack length by default.

Classical AT1/AT2 strength depends on regularization length. Use a qualified
cohesive formulation when strength and separation energy must be fitted
independently. A viscoelastic-only polymer cannot predict polymer cohesive
fracture; add and calibrate damage only when that failure path is required.

## Report and execute

For planning, deliver the causal hypotheses, comparison matrix, calculation
dependencies, parameter ledger, compute-volume estimate, and acceptance
criteria. Mark proposed numerical targets as targets.

For implementation, first inspect existing project instructions and runtime
capabilities. Pin a compatible ABACUS/dpdata/DeePMD/LAMMPS/DP-GEN tuple and
use its actual schemas. Do not infer DP-GEN keys from dpdata format names.
Keep processing templates separate from measured results.

Distinguish prepared inputs, submitted jobs, completed calculations,
validated force fields, and interpreted scientific results. Preserve
failed-job records and report the original error directly.
