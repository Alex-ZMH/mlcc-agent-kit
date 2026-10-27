# P5.07 — 0.24 strain producer and polarization response contract

Frozen implementation contract, 2026-10-23. Enabled0.23.0; rollback0.22.0. This is engineering system development, not material qualification.

## Scope / ownership

Only neutral periodic static **clamped-ion / fixed fractional coordinates**, zero external field, ABACUS3.10.1 PW nspin1 fixed occupations without SOC/noncollinearity. Preserve caller phase/dopant/method/PP/kmesh/shift/charge. Reject relaxed-ion, finite-field and mixed-component strain in this slice. Do not choose BTO phase or infer ferroelectricity from CZO values.

Main owns this contract, CLI/Study, integration/plans/release. Main's Luna owns ONLY `mlcc-agent/src/mlcc/berry_strain_response.py`, `mlcc-agent/tests/test_berry_strain_response.py`, `workspace/reports/berry-strain-response-v001/`. Existing implementation chat `01a15851-eb0c-7832-ba67-4833802afd0f` owns ONLY `mlcc-agent/src/mlcc/polarization_strain.py`, `mlcc-agent/tests/test_polarization_strain.py`, `workspace/reports/polarization-strain-v001/`. Shared files remain main-owned. Reuse existing runner/native creators.

## Strain definition

Reuse `elastic.voigt_strain_model`: engineering Voigt `(xx,yy,zz,yz,xz,xy)`, dimensionless normal strain and shear gamma=2 epsilon_offdiag. `F=I+epsilon`; row cell `C_s=C_0 @ F.T`. Fractional positions, atom IDs and atom-ID/element mapping stay fixed. Caller supplies explicit ±h points in a selected component; never expand six components automatically. Retain existing strain record, reference/derived cells/volumes. A central pair requires opposite equal nonzero amplitude in the same component. No lattice basis reorientation between points.

Coefficient is stress-form piezoelectric `e`, C/m^2 per dimensionless engineering-Voigt strain, not stress-driven `d` or Born displacement response C/m^2/angstrom. A component is a column/partial column, not a full tensor. Step/electronic precision remain unqualified.

## Producer interface

`create_berry_strain_response(study_path, model_path, method_path, site_path, request_path, output_path) -> manifest`.

Request schema `mlcc.abacus-berry-strain-response-request.v1`: `response_id`, `charge_state:0`, `mechanical_boundary:"clamped_ion_fixed_fractional"`, explicit `points`. Each point: `point_id`, `child_model_id`, `child_model_version`, `child_study_id`, `scf_task_id`, `voigt_component` (one of six labels), signed nonzero `strain`, `gdirs` (unique selected1/2/3), `scf_resource_request` (explicit time0), optional `scf_required_results`, `berry` (existing reference SCF options). Optional parent identity fields must agree. Reject duplicate point/model/Study/task IDs before writing. Do not generate implicit points/amplitudes.

Materialize child via `_write_derived`, preserving parent provenance/atom lineage; child Study paths point to child. Invoke `create_berry_reference_task` on child with `input_transformation=None`. Bind `berry_strain_response` metadata to model, Study, Task. No submission.

Output `response-manifest.json`, schema `mlcc.abacus-berry-strain-response.v1`:

- `response_id`, `manifest_path`, `request_path`, `method_path`, `site_path`, status `scf_inputs_written_not_submitted`, `mechanical_boundary`, `charge_state:0`, qualification false.
- `parent_study:{study_id,study_path}`, `parent_model:{model_id,version,path,charge_state}`.
- `reference_lattice_angstrom`, `reference_volume_A3`, `voigt_order`, `engineering_shear:true`.
- `points[]`: point/child IDs, `voigt_component`, signed `strain`, `strain_voigt`, `strain_record` (existing elastic record), `gdirs`, `model_path`, `study_path`, `scf_request_path`, **scf_task_path to task.json**, `scf_task` summary, `nscf_tasks:[]`.

`create_berry_strain_nscf(manifest_path, point_id, site_path, method_path, request_path) -> task`: reuse point-specific saved SCF preflight and existing `create_berry_nscf_task` native charge validation, no transformation. Require manifest method/site, SCF/child identity/geometry, requested gdir/time0. Bind `berry_strain_response`; append `nscf_tasks` record `{task_id,task_path,request_path,gdir,...}`. No submit/automatic direction/branch/retry. Unrun SCF blocks NSCF truthfully.

## Saved-result consumer interface

`analyze_polarization_strain(request_path) -> result`. Request:

```json
{
  "schema":"mlcc.polarization-strain-request.v1",
  "response_id":"explicit-response-id",
  "manifest_path":"/absolute/path/response-manifest.json",
  "pairs":[{"pair_id":"yy-h","voigt_component":"yy","minus_point_id":"ym","plus_point_id":"yp"}],
  "sources":[{"point_id":"ym","gdir":1,"task_file":"/absolute/task.json",
    "result_file":"/absolute/result.json","branch_integer":null,"branch_basis":null}]
}
```

`sources:[]` is valid; report missing point/direction sources. Each provided source must match a point and registered NSCF task/gdir. Unknown/duplicate sources/pair IDs are errors. Missing sources stay missing; supplied stale/mismatched/failed sources raise original errors. Branch integer + nonempty basis is caller declaration, no automatic nearest-neighbour unwrap.

Consume saved parsed Berry records. Do NOT call `read_berry_task`/`parse_berry_task` (would reparse logs). Existing `polarization._point_record(..., previous=None)` can validate an individual saved task with its own child Study/gdir, point_id/path_coordinate. Do not use its previous-point fixed-cell comparison or fixed-quantum `_branch_algebra`. Retain SCF/Berry jobs/task/result/method/quantum factor. Override its `geometry.fixed_cell` when describing cross-point path. Separately check child→parent atom IDs/elements/fractions/neutrality, F/cell/volume, Study/model paths, producer binding, and same physical method/kpoints/occupations/charge across supplied sources. No raw-label mixing.

## Proper / improper algebra

ABACUS `gdir=alpha` identifies **lattice vector R_alpha**, not Cartesian axis. Printed P_alpha is a lattice-basis contribution scalar; its Cartesian reprojection is P_alpha R_alpha/|R_alpha|, not full P dotted with that axis in a nonorthogonal cell.

At each point/direction use M=`quantum_check.quantum_factor`, P=`total_P_C_per_m2`, Q=`modulo_quantum_C_per_m2`. Q positive, source-native M checked (nspin1: all PP integer valences even -> M2, otherwise M1). Current CZO M2. Retain each point's own cell-derived quantum and branch n:

`p_alpha = M * (P/Q + n)` (dimensionless reduced charge).

Full Cartesian `P_cart=(e*1e20/volume_A3)*p_row @ cell_A`, e=1.602176634e-19C. Do not assume constant Q or p=P/Q. Compare saved direction/quantum against child cell with native printed precision tolerance, without reparsing.

For ±h in engineering-Voigt component s:

`dp_ds=(p_plus-p_minus)/(2h)`.

`proper_e_C_per_m2=(e*1e20/reference_volume_A3)*dp_ds_row @ reference_cell_A`.

`improper_dP_ds_C_per_m2=(P_cart_plus-P_cart_minus)/(2h)`.

Calculate independently. Constant reduced p yields zero proper despite possible geometric improper response. Common branch shift at both endpoints leaves proper invariant. Do not naively apply unsymmetrized infinitesimal proper/improper correction to engineering shear or demand exact finite-h identity.

All3gdirs + explicit branches needed for full Cartesian column in general cell. Available gdir may yield reduced slope and labelled lattice contribution, full proper/improper vectors remain null until all3 exist. Missing directions are never zeros. Missing branches suppress only dependent outputs. Complete software input must execute equations, never universal null.

Reference: Vanderbilt, *Berry-phase theory of proper piezoelectric response*, J.Phys.Chem.Solids61,147–151(2000), equations15,22–24, https://doi.org/10.1016/S0022-3697(99)00273-5 ; https://www.physics.rutgers.edu/~dhv/pubs/local_preprint/dv_piezo.pdf . ABACUS3.10.1 `berryphase.cpp`449–466,584–625,652–717 and `berry.py::_validate_native_polarization` reviewed.

## Output / delivery

Schema `mlcc.polarization-strain.v1`; `response_id`, `parent:{study_id,study_file,model_id,model_version,model_path}`, `manifest_path`, `mechanical_boundary`, `voigt_order`, `engineering_shear:true`, `reference_lattice_angstrom`, `reference_volume_A3`, `points`, `pairs`, `native_jobs`, `missing`, `status`, `evidence_kind`. Pair: IDs/component/amplitude, reduced slopes by gdir, full `proper_e_C_per_m2`, `improper_dP_ds_C_per_m2` (vector or null), direction missing/branches/sources/units. Scientific/production/full_tensor_qualified false. Relaxed ion/d/electrostriction null/out_of_scope. Math fixtures `evidence_kind=software_contract_only`, no fake native jobs.

Main CLI `create-berry-strain`, `create-berry-strain-nscf`, `polarization-strain --request --output`, `deliver-properties --study --polarization-strain --output` (existing targets optional). Delivery consumes saved result, validates parent identity/paths, preserves values/nulls/provenance, design not_assessed without targets. No algebra/native reparse.

## Acceptance / budget

**No new DFT/MD/training.** Existing strain geometry and ABACUS SCF/Berry paths suffice for this changed binding: validate unsubmitted small tasks' cells/INPUT/STRU/mapping/failure state on v100. Do not relabel177/178 displacement as strain evidence. Native strain-response values remain unvalidated. Any concrete uncovered native risk requires main's written necessity and minimal one-component protocol before DFT.

Each worker may submit one focused nonDFT v100Slurm check: CPU partition,1CPU,2GiB,10minutes,no-requeue; tests/model generation/saved-record arithmetic only. Record job/terminal state. Followup only for diagnosed fixes. Producer: existing small model/method→explicit one-component± requests→cell/fraction/map/Study/Task/INPUT/STRU/time0; unrunSCF rejection. Consumer: complete reduced-charge math, constantp geometric improper, commonbranch shift, nonorthogonal/shear, missing source/branch/gdir, method/charge/parent/cell/source mismatches. Saved native individual reader/rejection allowed, never strain positive. Integration publicCLI/savedresult→Study only; reuse worker artifacts, no rerun suites/arithmetic unnecessarily. Material numerical thresholds do not block software release.
