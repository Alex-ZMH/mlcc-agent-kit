# 0.23 P5 ordered SCF energy path contract

Status: implementation contract, 2026-10-23. 0.22 remains enabled until new-path integration acceptance. Implements the energy-source portion of P5.02–P5.04 in `P0-P12-execution-handoff.md`, not complete ferroelectric material qualification.

## Ownership and API

Existing implementation chat exclusively owns `mlcc-agent/src/mlcc/polarization_energy.py`, `mlcc-agent/tests/test_polarization_energy.py` and `workspace/reports/polarization-energy-v001`. Main owns shared modules, CLI, Study delivery and release. No edits to upstream or frozen releases.

Module public entry: `analyze_polarization_energy_path(request_path) -> dict`. CLI owned by main: `polarization-energy --request REQUEST --output RESULT`. Saved-result consumer owned by main: `deliver-properties --study STUDY --polarization-energy RESULT --output DELIVERY`; it must not rerun the source adapter or energy arithmetic.

## Explicit request

Schema `mlcc.polarization-energy-request.v1` contains:

- `path_id`, `path_basis` (a nonempty description of how geometries were chosen), `parent_study_file`, `parent_model_path`.
- `path_coordinate`: `{name, unit}`; coordinates below are caller-declared labels, not automatically inferred displacements.
- `mechanical_constraint`: `{kind: "fixed_cell", description: ...}`. First slice covers fixed cells and supplied single-point geometries only. Reject variable-cell, imposed-stress/enthalpy, constrained-relaxation and NEB claims explicitly rather than silently treating them as fixed cell.
- `reference_point_id`, referring to an existing ordered point.
- `points`: at least two unique `{point_id, coordinate, scf_task_file, scf_result_file, berry_result_file}` records in strictly increasing coordinate order. `berry_result_file` may be null. Task/result paths are explicit and resolve to the same saved task result. Do not generate/interpolate geometries or energy points.

Different child model IDs and Study IDs are allowed. Each point must bind its own task/model/method/result; each child must declare the supplied common parent (or be that parent). Preserve per-point child Study identity and parent link. Matching child IDs is not a scientific comparison criterion.

## Source and physical checks

Use saved native SCF `result.json`; never read Berry NSCF total energy as the energy source. Do not rerun ABACUS/native parsers or add an electronic-band prerequisite for a scalar SCF energy.

Require recorded Slurm COMPLETED/0:0, matching task/job/result identity, `calculation=scf`, saved `stage=scf`, electronic convergence true, finite whole-cell `energy_eV`, `energy_unit=eV`, and exact existing `_energy_definition("fixed")`. Retain original source files and qualification flags. Missing/invalid/unconverged sources must yield an explicit error or unavailable point, never a substituted/interpolated value. A partial or invalid path must not be reported complete.

First slice is ABACUS 3.10.1 PW, neutral nspin=1, fixed occupations, non-SOC/noncollinear false. Compare common recorded physical and numerical settings: XC, basis, spin/occupation/charge, element order, PP IDs/metadata/treatment, k mesh/shift, cutoff, SCF threshold, bands, mixing/solver/symmetry and energy definition. Exclude only record identity/output routing/device metadata from equality; preserve method_set IDs even when physically equivalent aliases differ. Reject unsupported additional physical fields rather than ignoring them. Reuse existing method/geometry helpers where applicable; do not invent a new parser.

Require common composition, atom IDs→elements, periodicity, cell (absolute 1e-8 Å tolerance), and explicit parent lineage. Each saved final geometry must match its point model by atom IDs, including periodic equivalent positions. Keep ordered positions/cell and mapping evidence in each output point. The scope is supplied fixed-cell single-point sampling, not relaxed energy minima.

Optional saved Berry records must bind the same point's model/Study and exact charge-producing SCF task/job through their existing saved reference fields. Retain representative polarization, direction, quantum, branch status and references. Missing Berry or unresolved branch/insulating qualification does not block a valid energy curve. Do not recompute branches or DeltaP here; `polarization_coordinate` and `delta_polarization` remain unavailable unless consuming a separately reviewed compatible saved path in a later slice.

## Calculations and output

Output schema `mlcc.polarization-energy-path.v1` preserves `request_path`, `path_id`, `parent = {study_id, study_file, model_id, model_version, model_path}`, `path_basis`, `path_coordinate`, `mechanical_constraint`, `reference_point_id`, ordered point sources and returns:

- `points[i].energy_eV_cell` and `relative_energy_eV_cell = Ei - E(reference_point_id)`.
- `endpoint_difference_eV_cell = E(last) - E(first)`.
- `sampled_maximum`: maximum energy and relative energy, with all tied point IDs, coordinates and source task/job references.
- `status`, `evidence_kind`, `native_jobs`, `missing` and original qualification flags. Whole-cell eV is mandatory; no per-formula normalization is inferred.
- `neb_barrier_eV`, `finite_temperature_free_energy_eV`, `spontaneous_polarization`, `double_well_qualified` and ferroelectric/material production qualification remain null/false as appropriate.

An endpoint difference or sampled maximum is not a NEB barrier, double-well proof or finite-temperature free energy. The existing CZO atom8 ±0.01 Å data demonstrate the system path only; do not label it ferroelectric switching or select a BTO phase.

## Acceptance and budget

Reuse saved SCF177/178 (and 50 only if actually comparable) plus saved187/188 reference provenance. No new DFT/MD/training. A complete native engineering path and explicit software-only mathematical examples are separate evidence classes; neither grants material production qualification.

Module: one focused v100 Slurm job, CPU partition, one task/one CPU, 2 GiB, 2 minutes, no-requeue, numerical library threads=1. Check only new arithmetic/source binding, negative NSCF and method/lineage/cell/source mismatches, unresolved Berry and distinct child Study/model acceptance. Main installed integration: one job with the same budget, only new CLI/Study dispatch and saved-result consumption. Reuse module results; do not repeat source parsing/arithmetic or frozen tests at installation. Preserve native job IDs and scheduler terminal states.
