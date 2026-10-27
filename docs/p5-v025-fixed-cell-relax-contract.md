# 0.25 candidate: fixed-cell ionic relaxation source bridge

2026-10-23. Enabled0.24/rollback0.23 remain frozen. This slice implements explicit ionic degrees of freedom, native stop/geometry provenance, and saved-relax→new Model/Study→existing SCF/Berry input creators. No variable-cell relaxation, NEB, optimization framework, phase/dopant selection, automatic parameter change or DFT submission.

## Ownership

- Main owns this contract, abacus.py, abacus_tasks.py, their affected tests, public CLI, final integration/acceptance and plans. A bounded main-owned Luna may implement those exact producer files.
- Existing implementation chat01a15851-eb0c-7832-ba67-4833802afd0f exclusively owns relaxed_structure_bridge.py, test_relaxed_structure_bridge.py and workspace/reports/relaxed-structure-bridge-v001/. It must not modify shared producer/CLI files or submit DFT.
- No second consumer implementation. All numerical/modeling/tests/postprocessing run on v100 through Slurm; local edits/transfers/evidence viewing only.

## Native3.10.1 semantics and supported constraint scope

The exact saved version source is workspace/reports/berry-gpu-build-v001/source-audit/source-tree/abacus-develop-3.10.1. module_relax/relax_new/relax.cpp setup_gradient masks Cartesian force components, while its displacement path converts to Direct then masks those components. Consequently partial per-axis masks are supported here only for positive diagonal axis-aligned orthorhombic cells. All-free atoms and whole frozen atoms (111/000) are valid for general fixed cells. Reject a partial mask on a skew or rotated cell; do not silently switch relax_new or reinterpret coordinates. First slice uses relax_new=true and relax_method=cg explicitly. Position coordinate format Direct does not redefine the constraint axes.

Native convergence uses the maximum absolute force component over movable degrees of freedom, not the maximum atomic force norm and not the constraint reaction. Preserve full raw forces as well as the masked criterion. Require at least one movable degree of freedom for a new relax request.

Native markers: electronic success/failure are charge-density convergence / convergence not achieved; ionic success/failure are Relaxation is converged! / not converged yet (old Ion relaxation wording still readable). Parse final evaluated ionic step, explicit relax_nmax and native finish. No marker alone overrides an electronic failure. Reaching relax_nmax without ionic convergence is iteration exhaustion, never convergence.

The new relax driver evaluates E/F, may move atoms, then writes STRU_ION_D. If ionic convergence is false, that file may be an unevaluated proposed geometry. Preserve it with an explicit role and final_geometry_matches_last_evaluation=false; never promote it or associate its geometry with the last E/F as a converged state. No extra SCF is triggered automatically.

## Request and producer data contract

The existing create-abacus calculation=relax entry requires input_transformation=null and an explicit ionic_constraints object:

```json
{"coordinate_basis":"cartesian","atom_ids":[0,1],"move_flags":[[0,0,0],[1,1,1]]}
```

atom_ids cover every model atom exactly once, flags are integer0/1; normalize to model source-ID order, then emit native m flags in ABACUS grouped-species order. Public SCF rejects ionic_constraints. Existing low-level prepare_abacus callers omitting it retain all-free behavior for historical software evidence. No ASE constraint is silently dropped: unsupported pre-existing ASE constraints must be rejected when preparing relax inputs unless represented by this explicit contract.

Store normalized ionic_constraints in method.json and TaskRecord with schema=mlcc.ionic-constraints.v1, coordinate_basis=cartesian, atom_ids, move_flags, relax_new=true and origin=explicit_request (or legacy_all_free at the low-level writer). Emit relax_new=1 for this supported CG relax path. Keep neutral-only relax and the existing physical convergence controls.

parse_abacus_outputs adds a relaxation record; parse_abacus_task retains it in result.json and records final_structure_file=absolute final.extxyz. Existing top-level E/F/stress/final_atoms and native flags remain. The canonical relaxation record has:

- schema=mlcc.fixed-cell-relaxation-result.v1, cell_constraint=fixed_cell;
- ionic_constraints: normalized flags actually read from original STRU, bound to atom IDs; when saved method constraints exist they must match;
- relax_new (actual echoed native value), ionic_steps, relax_nmax;
- native_stop_reason: ionic_converged, electronic_not_converged, ionic_iteration_limit, not_converged, or native_completion_unconfirmed; retain native marker text;
- electronic_converged, ionic_converged, native_completed;
- force_metric=max_abs_movable_cartesian_component, force_threshold_eV_per_A, max_free_force_component_eV_per_A, max_all_force_component_eV_per_A;
- fixed_cell_verified, frozen_dofs_verified;
- final_geometry_matches_last_evaluation, final_geometry_role;
- geometry_promotable: true only with native completion, both convergence flags, free-DOF force threshold, unchanged cell and frozen-DOF checks, matching native final geometry/last evaluation. A failed criterion stays false and cannot be exported.

Native input/echo, log, STRU_ION_D, atom map and method paths remain in source_files. Missing evidence is not fabricated. Historical all-free Ni33 can be reparsed in a clearly recorded evidence copy to obtain the new fields; the original task/results and historic walltime stay unchanged.

## Saved structure bridge / public interface

Implementation module API:

`derive_relaxed_structure(*, task_path, parent_model_path, study_path, request_path, output_path) -> dict`

Request requires new model_id, version, study_id. It writes output_path/model/ with existing write_model_artifacts plus output_path/study.json and bridge.json. Read the saved TaskRecord/method/result/final.extxyz; do not invoke native parsers or response math. Require real saved COMPLETED/0:0, engine=abacus/3.10.1, method.stage=relax, correct task/job/model/result bindings and relaxation.geometry_promotable=true. Original parent IDs, element order, final_atoms IDs, constant cell and final.extxyz/result consistency must match. The provided parent Study must select that parent Model and fixture role; when TaskRecord study identity exists it must match. For historical33 with no Study field, explicitly record study_binding_origin=caller_supplied_parent_study_matching_source_model; do not invent a historic study binding.

Preserve parent material/phase_requested/fixture/dopants/charge (neutral), every atom ID with one-to-one parent lineage, original source task/job/method/result/native paths and constraints. New model metadata carries relaxation_source with task_file, result_file, method_file, scheduler_job_id, parent_model, relaxation and final_structure_file. Do not infer phase_relaxed, polar state, material qualification or production suitability. Child Study uses explicit request study_id, selects new Model, records parent_study_id and relaxation_source. No inherited clamped-ion strain binding may be misrepresented as a relaxed-ion response contract.

Thin optional adapter in the same module:

`create_relaxed_scf(*, bridge_path, method_path, site_path, request_path) -> dict`

It reads/validates bridge.json, uses its child Model/Study, and dispatches the caller's calculation=scf request to existing create_abacus_task, or create_berry_reference_task only when request.berry.role=reference_scf. It must preserve source relaxation dependency and provenance in created TaskRecord; no engine run, charge reuse from relax, implicit Berry qualification or new physical parameters. If the existing Berry creator rejects the chosen model/method (e.g. Ni smearing), propagate that error. It creates a fresh SCF charge source for any later existing Berry NSCF task.

Main adds public CLI derive-relaxed-structure (--task --parent-model --study --request --output) and create-relaxed-scf (--bridge --method --site --request), keeping the existing seven-MCP runner architecture. Implementation chat owns no CLI edits.

## Evidence and first acceptance

Reuse actual Ni33 workspace/tasks/h1-ni-relax-v001 (GPU, COMPLETED/0:0; five ionic steps, final electron/ion convergence; all atoms free). Reparse only changed metadata/criterion in a new v100 evidence copy; do not rerun native relax or alter original historical budgets. Parent model is workspace/models/ni-fcc-engineering/v001 and parent Study workspace/configs/cases/ni-engineering-v001.json. Request phase/dopant choices remain unchanged.

Historical binding clarification: the old engineering Study labels the phase `fcc_conventional_4_atoms`, whereas the selected Model uses `fcc_engineering_fixture`. For this new saved-source consumption, use the explicitly recorded caller-supplied `workspace/reports/fixed-cell-relax-producer-v001/ni33-parent-study-v001.json` (new Study ID and the same Model's existing phase label). It retains both historical labels and its source Study. No geometry, material choice, historic task or historic Study is changed, and no historical Study association is invented for job33.

One targeted v100 CPU Slurm job for producer changes, then bridge-owner's affected checks/native-saved promotion/SCF input. Budgets1CPU/2GiB/10min, no-requeue. Tests may establish software masks/rejections/stop cases; they do not establish new native constrained dynamics. The real Ni bridge proves saved source→model/Study→SCF input, not insulating Berry or a production relaxed-ion coefficient. Existing 221/222 are SCFs and must be rejected as relax sources. No new DFT is part of this protocol; if a changed engine path requires it, main records separate necessity and a minimal explicit GPU/time0 protocol first.
