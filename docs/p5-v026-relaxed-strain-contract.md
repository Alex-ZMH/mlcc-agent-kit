# 0.26: saved fixed-cell relaxed strain sources

2026-10-23. 0.25 remains enabled/frozen; 0.24 is rollback. Extend the existing strain producer/consumer, not the response algebra or runner. Native addendum A and software slice B are distinct evidence.

## Scope and ownership

- Main: contract, berry_strain_response.py and its tests (bounded Luna implementation), public integration, review, acceptance and plans; main controls native A.
- Existing implementation chat 01a15851-eb0c-7832-ba67-4833802afd0f exclusively owns polarization_strain.py, test_polarization_strain.py and workspace/reports/polarization-strain-relaxed-v001/.
- Main Luna A owns only workspace/reports/constrained-relax-native-v001/ report scripts. No overlapping product edits or duplicate tests. All modeling/postprocessing/tests on v100 Slurm.

## B: minimal saved-source entry

Keep existing v1 request/manifest/binding schemas, with explicit mechanical_boundary discrimination. The unchanged clamped_ion_fixed_fractional branch retains its strict fixed-fractional/no-relax checks. New boundaries are relaxed_ion_fixed_cell (all atom components free) and constrained_ion_fixed_cell (at least one frozen and one movable component). One manifest cannot mix these. Neither boundary grants scientific qualification.

create_berry_strain_response accepts the new boundaries only with exactly two distinct saved bridge points, equal opposite nonzero strains of one Voigt component. Existing point request fields remain; add relaxed_structure_bridge (absolute bridge.json path). child_model_id/version and child_study_id must match that bridge's promoted child; these are assertions, not requests to overwrite it. Each bridge must already exist from the accepted 0.25 derive_relaxed_structure entry. Missing bridge input is an actionable source error, not a fabricated point. No new automatic relax orchestration or CLI is added. Explicit strained pre-relax Models can be materialized with the existing strain producer; its unsubmitted SCF inputs need not be executed. Existing create-abacus relax and derive-relaxed-structure produce the saved bridge. Native +/- relax runs are outside this software slice.

The new producer uses create_relaxed_scf for a fresh Berry reference SCF on each promoted Model, then adds the response task binding. It does not edit the source Model, Study, bridge or prior task. A response need not overwrite generic bridge Model/Study metadata with a response binding: their relaxation_source is already bound to the bridge. The manifest and new SCF/NSCF tasks carry the response-specific binding.

Existing manifest point fields identify the promoted final Model/Study and fresh SCF. Additional canonical point and task-binding fields:

- mechanical_boundary; relaxation_scope = all_internal_dofs or selected_internal_dofs;
- pre_relax_model = {model_id, version, path}; pre_relax_study = {study_id, study_path};
- relaxed_structure_bridge = absolute bridge.json path;
- relaxation_source = exact canonical bridge.relaxation_source, including native task/result/method/job and actual constraints;
- ionic_constraints = exact normalized relaxation_source.relaxation.ionic_constraints.

The root manifest parent remains the common unstrained Model/Study. Bridge parent is the pre-relax strained point; bridge child is the final relaxed point. Validate root -> pre-relax atom IDs/elements/neutral charge/phase/dopants/case/parent identities and explicit engineering-Voigt cell with unchanged fractional coordinates at strain construction. Validate bridge through the existing saved-source gate, including actual convergence/geometry_promotable, final evaluated geometry, fixed cell/frozen components and final Model/Study identity. Final fractional positions may differ from root; final cell must equal the point's pre-relax strained cell. strain_record describes the *initial deformation*, not a claim that final fractional coordinates stayed fixed.

Compare the two points' canonical atom-ID/move-flag selection and coordinate basis exactly (provenance origin need not encode a new physical criterion). Require same relaxation method controls, force metric and threshold, and same physical method/pseudopotentials, excluding explicitly stage-specific SCF/relax output controls. Do not mix partial and all-free cases or opposite points from unrelated source chains. Exact signed strain and source binding must be checked again before NSCF/analysis.

Producer supplies a read-only helper _validate_relaxed_point(manifest, point), reused by the consumer. It returns model (ModelArtifacts), study (dict), pre_relax_model (ModelArtifacts), pre_relax_study (dict), relaxation_source, ionic_constraints and relaxation_scope. It reads saved sources, never reparses native output or creates/submits a task. Consumer need not duplicate the bridge gate. Producer NSCF preflight uses this helper for relaxed points, retaining existing own-SCF charge, method, atom map and response identity checks.

## B: consumer and labels

Reuse _pair_response unchanged. Parent-reference proper and point-Cartesian improper central differences keep their existing definitions. Missing Berry direction or explicit physical branch remains null/unresolved. If declared saved evidence is inconsistent, report the original error. Do not invent missing relax sources; a valid new manifest contains two proven bridges but may have no SCF/Berry results yet.

Use mechanical_boundary from manifest in saved-source and result metadata. response_type is relaxed_ion_stress_form_piezoelectric_e for all-free, constrained_ion_stress_form_piezoelectric_e for partial. Add relaxation_scope and ionic_constraints to the output and retain per-point bridge/native sources. Partial constrained response must not be called full relaxed-ion piezoelectric response. relaxed_ion_response may describe the all-free result only; it stays null for partial; expose constrained_ion_response separately for partial, without duplicating numerical arrays (a scope/status descriptor suffices). Full tensor/step/native scientific qualification remain false. Out-of-scope still includes stress_driven_d/electrostriction/finite_field; partial also retains full_relaxed_ion.

Native job provenance includes source relax jobs as well as each point's own SCF/Berry jobs, with roles explicit. Existing public Study delivery should carry these new fields; main checks this without changing seven-MCP routing or adding a new framework.

## Verification boundaries

B checks only changed source binding, all-free/partial distinction, equal +/- selection, borrowed source/method/mask rejection, incomplete branches/directions and existing math with explicitly labeled software fixtures. Use installed0.25 evidence where genuinely applicable; no native +/- relax or Berry matrix, frozen test suite or new material calculation. Mathematical fixtures never become native production results. Main reviews focused evidence then accepts/installs0.26 only if the public changed path works.

A is a separate single unstrained CZO20 engineering chain: explicit O atom ID8 Cartesian x movable, all other components frozen; no displacement/strain. New engineering force threshold0.02 eV/A, relax_nmax8, existing electronic threshold1e-4/scf_nmax100. Exact proven GPU runtime and pseudopotentials; at most relax -> fresh Berry reference SCF -> gdir1 NSCF, each1V100/1MPI/1CPU/8GiB/time0/no-requeue, serial. If relax is not promotable, stop dependent tasks and record actual failure without retries/parameter changes. Its source is not either endpoint of B and cannot establish a strain derivative. If product code unchanged, A adds evidence to0.25 without a release bump or host rerun.
