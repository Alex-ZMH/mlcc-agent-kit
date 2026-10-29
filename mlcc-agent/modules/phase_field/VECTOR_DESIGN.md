# Full-vector phase field 0.3.0

Additive migration of the frozen `experiments/ferroelectric_vector_poc` V0.3 experiment. Original experiments, scalar operations, scalar RT0, old schemas and historical source indices remain intact. No runtime import of experiments. Independent method Skill: [vector method](skills/mlcc-vector-ferroelectric/SKILL.md).

## Public operations

`vector_steady`, `vector_evolve`, `vector_steady_si`, `vector_evolve_si` share one 2D/3D mixed CG1 model with independent Px/Py(/Pz)/phi. Existing `steady/evolve/steady_si/evolve_si` retain scalar-y physics and contracts. Native Linux and Windows/WSL use the same scientific entry and explicit host deployment settings.

The vector model accepts explicit synthetic quartic a,b,c,g,epsilon,mobility, uniform/fixed-perturbation/180/90xy/90xz initial states and full-surface voltage control. Constant, triangular and ordered piecewise-constant fields are supported; only constant fields admit a stationary solve. Explicit relaxation end=0 means direct Newton; positive end performs the declared relaxation first. No public manufactured-source/MMS or injected failure control, no silent backend, parameter, mesh or waveform replacement.

## Reuse

- Shared Scientific Core 0.1.0: `integral_local`, `interpolate_dg0`, `cell_dof_values`, `scalar_cell_values`, `owned_cell_count`, with actual per-task Core provenance. Single MPI rank is retained, so local integral semantics match the source.
- Existing scalar deployment transport, process/timeout policy and resource budgets; only resource estimation dispatch is additive. Existing shared UNIT subprocess API is reused.
- Existing `scaling.derive` supplies the four-scale physical factors. Its scalar-profile a/b/alpha/beta constraints are **not** copied into the vector model; vector coefficients use their own energy convention.
- Frozen vector equations, SNES/MUMPS settings, time advancement/voltage-work acceptance, state inheritance and rollback remain in the module. An outer accepted-step resource guard bounds possible history growth.
- Frozen independent NumPy simplex/shape-function/quadrature residual reconstruction, VTU/NPZ/HDF5 comparisons and energy checks are migrated with a package-relative import. Vector CG1/history output remains specialized because Core V0.1 static scalar point I/O does not represent all vector/history fields.

## UNIT and dimensionalization

Reduced operations are explicitly dimensionless. SI operations accept raw structured quantities and four positive independent reference scales: l0 [m], P0 [C/m²], t0 [s], f0 [J/m³]. Unique UNIT core 1.0.0 converts admitted units; catalog 1.2.0 stays unchanged. No local conversion table or fallback exists. Counts, spatial dimension, directions, source records and algorithm controls are not unit-scaled.

SI a,b,c and mobility are explicitly named `reduced_parameters`, with unit 1. Physical g [J m³/C²], epsilon [F/m], initial P, field and integration times are admitted individually. The source quartic energy is a sum(Pi²)+b sum(Pi⁴)+c sum(Pi²Pj²), with no 1/2 or 1/4 factors. Derived physical a=a* f0/P0², b=b* f0/P0⁴, c=c* f0/P0⁴, M=M* P0²/(f0 t0); epsilon*=epsilon f0/P0² and g*=g P0²/(f0 l0²). These are declared synthetic physical views, not material calibration or arbitrary physical Landau-coefficient admission.

E0=f0/P0, phi0=f0 l0/P0; coordinates, P, phi, time and histories are converted once after canonical admission. For wall SI input, physical initial width is l0 delta* width_factor, with delta*=sqrt(g*/abs(a*)). The legacy scalar wall width has different semantics. ND original fields remain in the root; explicit physical NPZ/VTU, unit metadata, mapped history and independent physical-view readback live in `si/`. 2D integrated energy is J/m, 3D J; wall energy per physical wall area is J/m². No thickness is invented. Numerical QC stays dimensionless.

## Evidence and limits

Each task retains original/canonical/solver inputs, shared unit audit, full accepted vector/phi history, native mesh/volume fields, logs, independent residual checks, optional plots and Core provenance. Verification batches retain the matching source release separately. Existing host limits (default max_cells=6000, max_work=4000000, max_history_bytes=67108864) are retained; the source direct-LU cap is 25000 DOFs. The module imposes an explicit operational accepted-step guard <=2000 and source max_halvings<=6, and rejects requests exceeding host budgets. These are operational bounds, not material or accuracy criteria.

Source numerical criteria are in [vector protocol](protocols/vector-protocol.json). Per-task mesh/time convergence, stationary stability, material validity, electroelasticity and general multidomain hysteresis remain not_checked. Triangular single-domain trajectories are dynamic model responses, not experimental/quasistatic Ec. c=6b has a neutral splitting mode for the analytic 180 wall. Optional DC differential studies can be built from explicit separate vector_steady cases; no hidden multi-case C(V) aggregation is registered.

Integration and genuine regression receipts: [main verification](../../docs/verification/phase-vector-2026-10-26/README.md). Source/index is [current vector source release](VECTOR_SOURCES.json); old NATIVE_LINUX_SOURCES/SCIENTIFIC_CORE_SOURCES/UNITS_SOURCES remain historical.
