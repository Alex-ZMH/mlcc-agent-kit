---
name: mlcc-vector-ferroelectric
description: Prepare and interpret full-vector 2D/3D LGD phase_field vector_steady/vector_evolve and explicit-scale SI variants, including 90/180-degree polarization walls and controlled dynamic electric loading.
---

# Full-vector ferroelectric method

公网调用统一见[公网操作入口](../../../../skills/references/public-operations.md)；本文件只补充方法 schema、单位和结果解释。

本文件是按需读取的方法细节；创建、提交、查询和读取以[顶层运行Skill](../../../../skills/run-mlcc-phase-field/SKILL.md)及[公共生命周期](../../../../skills/references/task-lifecycle.md)为准。专业输入/schema、物理定义与检查仍由本模块维护。

Use module `phase_field`, operations `vector_steady`, `vector_evolve`, `vector_steady_si`, `vector_evolve_si`. These are additive to the four scalar operations, whose fixed scalar-y physics, RT0 and input contracts remain separate. Prefer an authoritative provided input file unchanged; clarify missing parameters, units and sources. Do not substitute synthetic example parameters for actual material input.

The registered profile is `synthetic_tetragonal_quartic_v1`, full two-component P in 2D or three-component P in 3D, plus self-consistent phi. The energy is `a sum(Pi²)+b sum(Pi⁴)+c sum(Pi²Pj²)`; no scalar-model 1/2 or 1/4 convention is implied. Parameters must satisfy a<0,b>0,c>2b,g/epsilon/mobility>0. This has no elasticity, electrostriction, grain orientation, temperature/material calibration or RVE coupling.

Boundary condition is explicitly `all_surface_voltage`: phi=-E_applied·x on every outer face. Electric field enters only through voltage; never add a second body driving field. Initial states are explicit uniform vector, the fixed xyz perturbation fixture, neutral 180 wall, 90xy wall, or 3D-only 90xz wall. Wall frame/geometry remain those of the frozen experiment. Width_factor is a multiple of reduced analytic delta=sqrt(g/abs(a)); source scalar-wall width has different semantics. All wall-end polarizations are fixed; transverse polarization boundary is natural.

`vector_steady` requires a constant field and can explicitly relax for evolution.end before the stationary solve; end=0 means no relaxation. `vector_evolve` requires end>0. Field protocols are constant, triangle(direction/amplitude/period), or ordered stairs(times/values). Stairs are split at each specified boundary; no interpolation or waveform coarsening. End,dt,max_steps,max_halvings and mesh counts are explicit. The frozen integrator requires reduced dt<=0.2; failed nonlinear steps may roll back and halve only within the declared bound. Host work/history/cell budgets and the frozen 25000-DOF cap reject excessive requests without changing the physics or mesh.

Dimensionless input requires parameters a,b,c,g,epsilon,mobility, reduced vector values/field/time and a source. SI variants require raw `{value,unit,source}` quantities and positive length/polarization/time/energy_density reference scales. In SI input a,b,c,mobility are explicitly **reduced_parameters** with unit `1`; g is physical gradient coefficient, epsilon is absolute F/m, initial polarization is C/m², wall width is length, field is V/m, and integration/protocol times are physical time. Count, direction and algorithm bounds remain dimensionless. Relative epsilon_r is not interchangeable with reduced epsilon or absolute epsilon.

Only the shared UNIT core performs generic conversion. The adapter keeps original quantities, canonical SI, per-field audit and the reduced input. The solver never reconverts original display units. Four-scale mapping reuses the existing module scaling primitives; physical a/b/c and mobility are derived with the explicitly documented vector energy convention. Scales are not material calibration. Reduced ND evidence and QC stay intact; SI NPZ/VTU, physical history and readback are separate. 2D integrated energy is J/m, 3D J; wall excess energy per physical wall area is J/m². No invented 2D thickness.

Results have solver_dimensionless, optional results_si and unit_mapping, plus native artifact refs. Full vector NPZ contains every accepted P component/phi/time; VTU/XDMF/HDF5 contain the final accepted volume. A 3D PNG is only a labelled nodal slice. Figures use actual saved fields/history. Independent saved-simplex residual reconstruction, Gauss/constitutive/enthalpy and cross-format checks determine numerical status. The old scalar RT0 is not part of this vector model.

Interpret triangle P–E as a finite dynamic trajectory. The example is a controlled synthetic single-domain cycle, not measured/quasistatic material Ec or validated general multidomain hysteresis. The c=6b analytic-wall benchmark has a neutral splitting mode for the 180 wall; Newton convergence alone does not establish unique/stable equilibrium. Optional bias derivatives require explicitly comparing separate steady runs and branch consistency; this module does not silently aggregate a material C(V) model.

Preserve per-task mesh/time convergence, material validity, stability, electroelasticity and general multidomain-cycle not_checked items. Read saved result/artifact only during follow-up; no solve or retry on query. Host selection WSL/native Linux, scheduling and execution authorization remain outside science input. Do not infer native process termination after client timeout.

Contracts: [reduced evolution](../../schemas/vector_evolve.input.schema.json), [SI evolution](../../schemas/vector_evolve_si.input.schema.json), [results](../../schemas/vector.result.schema.json). Examples: [90xy wall](../../examples/vector-wall90-2d.json), [3D stairs](../../examples/vector-stairs-3d.json), [dynamic P-E](../../examples/vector-pe-2d.json), [SI example](../../examples/vector-uniform-2d-si.json).
