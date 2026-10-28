# Static tangent dielectric tensors 0.4.0

Two additive operations: `dielectric_tangent` and `dielectric_tangent_si`. The eight previous scalar/vector operations retain their contracts and science. This migrates reviewed `ferroelectric_tangent_poc` V0.3-delivery-fix.1 into the module; no runtime import of experiments and no public Runtime, UNIT or Scientific Core changes.

## Definition and equations

The registered output is the complete derivative of volume-averaged D with respect to prescribed uniform Ebar: every 2×2/3×3 component, including signed cross terms. phi=psi−Ebar·x, all outer psi=0, E=Ebar−grad(psi), D=epsilon_b E+P. The frozen vector quartic/gradient forms and mixed spaces are reused. UFL differentiates the full static residual and average-D functional. One factorization handles two/three sensitivity right-hand sides. There is no BE mass term, dt, old-state regularization, artificial pinning or mobility dependence.

The source stability gate eliminates psi and examines the constrained mass-scaled P energy Hessian; it does not demand positivity of the full mixed saddle Jacobian. Reviewed source tolerances/soft-mode classifications and independent simplex/quadrature readback remain unchanged. Source fixed-voltage P-end constraints are retained. Native FD, when requested, starts every +/- solve from the same saved center and independently solves back from each perturbed state. Historical FD does not mark a new point passed.

Uniform branch-local responses differ from finite fixed-end wall apparent responses. Wall half-length is explicit in [1,8] reduced units; the stable finite specimens and near-singular long-wall cases stay distinguishable. A wall response depends on specimen size and end constraints and is not a universal bulk coefficient. Rejected states retain diagnostic fields and an empty response bundle; public execution fails with `TANGENT_NOT_VALID`, never a valid-looking tensor.

## Reuse and operational bounds

Existing module vector kernel/physics, shared Core `integral_local`, DG0 interpolation/cell readback and fixed-version bootstrap are consumed. Specialized mixed sensitivity NPZ/VTU/XDMF/HDF5 remains local because Core V0.1 scalar/static export does not represent this data. AD, dense Schur/Hessian analysis and scientific branch workflow remain module-owned, not new common-core APIs. Each task records Core provenance.

Existing explicit WSL/native Linux transport, task identity/hash admission, independent environment, standard-library adapter and artifact contracts are reused. Dense stability analysis is bounded to 3300 total DOFs, matching the reviewed largest tested extent; this is an operational safety cap, not a scientific convergence threshold. Existing host cell/work/output-history budgets also apply. Requests are rejected rather than automatically changing mesh, coefficients or branch path. Deployment timeout and no-retry policy are unchanged.

## UNIT

Raw SI quantities pass once through the unique `mlcc/units.py` core. Reuse the four reference scales l0 [m], P0 [C/m²], t0 [s], f0 [J/m³] and existing `scaling.derive` factors; no unit table or vacuum-permittivity constant is copied. a,b,c are explicit reduced quantities with unit 1, g is physical gradient coefficient, epsilon is absolute background F/m, initial P is C/m², bias path is V/m and wall half-length is length. Counts, direction/component identities, equilibrium tolerances and validation selections are unscaled. t0 is retained for compatibility and does not introduce dynamics.

E0=f0/P0; epsilon_abs,SI=(P0/E0) epsilon_nd=(P0²/f0) epsilon_nd in **F/m**, in both 2D and 3D. Apply the same factor to total, background, polarization contribution and frozen tensors without truncating cross terms. Relative permittivity stays null: conversion to εr would require an explicit physical reference and separately reviewed downstream use. Absolute F/m, reduced absolute D/E and dimensionless relative εr are distinct physical semantics.

Original input, canonical SI, solver input and per-field UNIT audit remain separate. Physical fields and sensitivities live in si/: dP/dE is F/m, dphi/dE is m, dE/dE is dimensionless; indices are never rescaled. Original ND sensitivity/residual/stability evidence remains intact, with separate SI file roundtrip checks. Reference scales are synthetic physical views, not real material calibration.

## Agent and delivery

Independent method Skill and strict operation schemas are discovered through module.json. Professional dependencies stay inside the native science process. Only deterministic code executes and admits evidence; online-model quality is not claimed by schema tests or routing fixtures. No automatic RVE/FEM/SPICE injection, arbitrary spatial/tensor background, periodic/open-circuit response, finite-frequency complex dielectric or electroelasticity is added.

Examples include off-axis 2D/3D full tensors, SI/unit-equivalent inputs, finite constrained walls and diagnostic unstable/soft-wall rejection. Current source freeze is [TANGENT_SOURCES.json](TANGENT_SOURCES.json); historical VECTOR_SOURCES and earlier indices remain immutable. New real Runtime regressions and source comparisons are documented in [verification](../../docs/verification/phase-tangent-2026-10-27/README.md).
