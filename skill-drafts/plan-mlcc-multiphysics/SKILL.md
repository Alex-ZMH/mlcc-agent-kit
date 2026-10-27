---
name: plan-mlcc-multiphysics
description: >-
  Plan and review MLCC simulations from paraelectric or ferroelectric host
  and phase selection through charge-compensated dopant ensembles, ABACUS
  properties, LAMMPS interfaces, and device electrical and thermal response.
  Use for material selectors, doping-model specifications, and deciding
  which dielectric, ferroelectric, phonon, magnetic, or device routes apply.
---

# Plan MLCC multiphysics

This is a project-local design draft. It specifies models and workflows;
the proposed modeling API and periodic-table selector are not installed tools.

This is historical scientific background, not the current executable plan.
The current plan is ../../PLAN.md and the portable domain definitions are in
../../mlcc-agent. Stage numbers have been reassigned. Bootstrap with VASP,
then migrate explicitly to ABACUS for production. Generic FEM/phase-field and
full device multiphysics are outside the current DFT/MD execution scope.

The current assignment has two parts: pymatgen/ASE models with ferroelectric,
magnetic, phonon, and thermoelectric calculations; then LAMMPS expansion of
the same relaxed structures and microstructure/device connections. Use the
project P0-P12 plan. Implement direct domain functions and explicit adapters.
Do not use defensive programming, checksum verification, automatic fallback,
or automatic retries.

## Define the material before generating atoms

Read [the system plan](references/system-plan.md) to choose the relevant
property chains and scale transitions. Use [the material catalog](references/material-catalog.json)
for initial candidates, not as a substitute for an experimentally or
computationally sourced structure. The initial comparison is CaZrO3 and
BaTiO3; the user has not yet selected their phases or dopants.

Keep these identifiers separate: intended device grade, chemical composition,
parent phase and symmetry setting, selected parent structure, operating
conditions, and actual relaxed structure. C0G/X7R/X5R are device performance
codes, not unique phases, crystal structures, or doping recipes.

Require an explicit phase selection before generating a committed model.
Preserve the imported source path/version, cell basis, symmetry setting,
site labels, and stable atom identifiers. Doping may lower symmetry; retain
the parent-phase provenance and report the descendant's measured symmetry.
Do not silently regenerate a different phase or force doped structures to
retain the parent's space group.

## Make periodic-table choices physically explicit

An element selection is a request to investigate a dopant, not evidence of
solubility, occupation, valence, available pseudopotentials, or a valid force
field. Present candidate sublattices, oxidation states, compensation paths,
and backend support next. Distinguish common candidates from unknown ones
without declaring all periodic-table selections physically equivalent.

Use [the model-request schema](references/model-request.schema.json) as a
data contract for phase, source path/version, dopant details and spatial
sampling. Implement the requested physical model directly instead of
adding a general validation or recovery framework.

Define concentration relative to the selected sublattice and report integer
substitutions and actual concentration. A one-dopant cell does not test
within-cell dopant dispersion. If a dilute charge-neutral defect complex
requires a larger cell, expose that cost instead of silently rounding it.

Study dispersed, unconstrained random, SQS, clustered/defect-bound, and
segregated configurations when each represents a relevant hypothesis.
Maximum dispersion is not an unbiased random distribution. SQS approximates
specified lattice correlations; it does not establish equilibrium defect
pairing or segregation. Record seeds, site mapping, pair statistics,
minimum-image distances including periodic images, and parent relations.

Allow neutral defect complexes, explicit electronic compensation, and
appropriately corrected charged-defect calculations as separate models.
Do not use an oxygen vacancy to compensate an A-site trivalent donor by
default. For amphoteric rare earths, compare A-site and B-site occupation
and chemical potentials rather than choosing from ionic radius alone.

## Select property routes by their observable

Always consider structure, electronic gap/defect character, mechanical
response, and local stability for the actual material hypothesis. Enable
ferroelectric polarization/free-energy calculations for ferroelectric or
phase-transition questions. Enable harmonic phonons for lattice stability,
ionic dielectric response, and thermal reference properties; use
anharmonic methods near unstable/high-temperature reference phases.

Ferroelectric order, magnetic order, and thermoelectric transport are
different phenomena. A nonmagnetic dielectric can be ferroelectric. Use
spin treatment for Ni, open-shell dopants/defects, or an actual magnetic
observable; rare-earth f-core choices cannot support claims about f moments.
The user now explicitly includes thermoelectric calculations: calculate
Seebeck, conductivity/tau and electronic thermal conductivity/tau as a
separate chain from heat transport and electrical self-heating.

Separate electronic epsilon-infinity, ionic contribution, frequency- and
bias-dependent effective permittivity, and device capacitance. A potential
trained only to energy/force/virial does not automatically predict
polarization, dielectric loss, or field-driven switching.

## Check calculator capabilities

After the explicit VASP bootstrap and ABACUS migration, use ABACUS force labels
and its Phonopy interface for harmonic force
constants. Select the actual installed implementation for Berry phase,
Born charges, dielectric response, finite field, spin, SOC and U, and
complete the reference calculation required by that scientific task.

Validate response capabilities against the actual installed ABACUS version.
Documentation for a newer release is not production evidence. An unsupported
response remains explicitly unimplemented until an agreed upgrade or adapter
is completed; do not automatically call VASP or merge its labels into ABACUS data.

Use third-order/anharmonic force information or qualified MD for lattice
thermal conductivity. Include electronic heat transport for a metallic
electrode where relevant. Inspect the many-body/long-range implementation
of any MD heat-current method before trusting conductivity.

## Connect scales explicitly

Treat the user's 1–60 micrometre ceramic thickness as green-film or device
geometry, identified separately. Use small periodic bulk/defect DFT cells
and nanometre MD interfaces to obtain constitutive information. Transfer
to microstructure, thermal mechanics, fracture, and electrical device models.
Do not build a micrometre DFT crystal to represent a capacitor film.

For equal active dielectric gaps in parallel, use geometry and the
appropriate differential constitutive response for capacitance. Each gap
generally sees the terminal voltage, not terminal voltage divided by the
number of layers. Breakdown rating requires field concentration, defects,
transport, history, and statistical/device validation, not Eg alone.

Use electrode/termination geometry and an electrical model for ESR/ESL,
impedance, and self-resonance. Do not identify a phonon frequency with the
capacitor's self-resonant frequency. Avoid counting dielectric loss both
in a complex capacitance and again in a fitted series resistance.

Retain the established interface/fracture workflow for metal/ceramic and
the retained-polymer/temporary-binder branches. A polymer remains a
candidate requiring process, mechanical, and dielectric evaluation.

## Organize the multi-route calculation

Build a dependency graph around a readable model identifier/version and a shared
method/provenance record. Reuse validated common calculations. Run expensive
finite-temperature, full thermal transport, and interface training on
screened representatives instead of every dopant/configuration combination.

Changing chemistry, phase, defect or field state invalidates affected
atomistic results and force-field coverage. Changing only device layer
count or overlap area can reuse qualified material responses within their
validity envelope. Every promoted property records units, temperature,
frequency, field, stress, averaging, uncertainty, and evidence level.

For the automation/backend decision, read [the modeling evidence](references/modeling-evidence.md).
Pymatgen/ASE with symmetry and configuration tools are the preferred open
modeling core. VESTA is a complementary viewer; preserve Materials Studio
as an optional adapter when the user needs native XSD/Forcite work.
