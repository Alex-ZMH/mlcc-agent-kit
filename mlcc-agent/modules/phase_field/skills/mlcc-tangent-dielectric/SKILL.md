---
name: mlcc-tangent-dielectric
description: Prepare and interpret full static 2D/3D branch-local tangent dielectric tensors using dielectric_tangent and dielectric_tangent_si, with stability, branch, independent AD/FD evidence and explicit absolute F/m units.
---

# Static tangent dielectric response

本文件是按需读取的方法细节；创建、提交、查询和读取以[顶层运行Skill](../../../../skills/run-mlcc-phase-field/SKILL.md)及[公共生命周期](../../../../skills/references/task-lifecycle.md)为准。专业输入/schema、物理定义与检查仍由本模块维护。

Select phase_field dielectric_tangent / dielectric_tangent_si for the complete static d< D >/dEbar tensor. It is extracted by UFL AD of the full coupled equilibrium and displacement functional, with two/three linear sensitivity directions. FD is optional independent nonlinear verification, never the extraction algorithm. Do not confuse this with an assumed matrix background coefficient, a dynamic P–E slope, device capacitance, finite-frequency complex dielectric or material εr.

Preserve authoritative files unchanged. Explicitly supply synthetic quartic a/b/c/g/epsilon, initial state, dimension-matched mesh, nonempty bias loading_path, equilibrium tolerance, requested analytical/FD checks and source. Bias path inherits equilibrium branch states; it is not a time waveform. No dt, old-state, mobility, artificial pins or private require_stable bypass are accepted. Current profile is synthetic_tetragonal_quartic_v1, a<0,b>0,c>2b,g/epsilon>0, single MPI rank, reviewed real DOLFINx. Operational dense stability cap is 3300 total DOFs; do not coarsen inputs silently.

Uniform initial state needs a full P vector. Wall templates are 180/90xy/3D-only90xz and require explicit finite wall_half_length; geometry/frame/end polarization values are fixed by the reviewed source. Stability is the constrained P energy Hessian after eliminating electrostatics; a mixed saddle Jacobian is not expected to be SPD. Unstable, near-singular or unequilibrated states are rejected, retain diagnostics and export zero valid responses. Do not reinterpret Newton convergence or a diagnostic field-readback PASS as valid material tangent. Do not regularize a free wall with a time-mass term.

Distinguish uniform_branch_local_response from finite_fixed_end_multidomain_apparent_response. A finite specimen wall tensor includes wall motion/end/size effects; it is not a universal local coefficient and must not be injected into another homogenization without checking double counting. No elastic/electrostrictive response or true material validation is implemented.

ND tensor units are dimensionless absolute D/E, not relative permittivity. SI input uses explicit quantities and the unique UNIT core with four reference scales l0/P0/t0/f0. Reduced a/b/c have unit 1; physical g and absolute background epsilon, initial polarization, field path and specimen length are admitted separately. E0=f0/P0; every tensor component converts once by P0/E0=P0²/f0 to absolute F/m in both dimensions. Background and polarization contributions add once. Preserve signed off-diagonal components and coordinate convention. Relative permittivity is null; do not label F/m or reduced D/E as εr, or invent epsilon0. Synthetic scales do not establish material calibration; time scale does not make this a dynamic model.

Inputs/original, canonical SI, reduced solver input, per-field audit, raw center/perturbed states, complete mixed sensitivities, branch hash/path, stability diagnostics, frozen-P control, all components and independent saved-field checks are evidence. Physical fields/sensitivities have a separate si view. Tensor extraction and QC are deterministic. Point-specific mesh convergence is not_checked; FD/analytic checks not requested remain not_checked, never borrowed from experiment reports. Material/finite-frequency/electroelastic applicability remains not_checked.

Follow-up reads the same saved task and artifacts; never creates a new solve. Host deployment is an explicit WSL/native Linux choice outside scientific input, with no fallback or resubmission. Input/source scope is unchanged by a model explanation. Generic downstream routing is not enabled: RVE expects its own physical relative-material definition and FEM currently expects scalar isotropic coefficients.

Contracts: [ND](../../schemas/dielectric_tangent.input.schema.json), [SI](../../schemas/dielectric_tangent_si.input.schema.json), [result](../../schemas/tangent.result.schema.json). Examples: [2D off-axis](../../examples/tangent-cross-2d.json), [3D SI](../../examples/tangent-cross-3d-si.json), [finite wall](../../examples/tangent-wall90xz-3d.json), [diagnostic unstable state](../../examples/tangent-unstable-2d.json).
