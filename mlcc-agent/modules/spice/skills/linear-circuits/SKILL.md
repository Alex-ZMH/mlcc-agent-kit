---
name: spice-linear-circuits
description: Controlled native ngspice AC impedance (single or parallel RLC) and finite-source single-pulse transient.
---

公网调用统一见[公网操作入口](../../../../skills/references/public-operations.md)；本文件只补充方法 schema、单位和结果解释。

本文件是按需读取的方法细节；创建、提交、查询和读取以[顶层运行Skill](../../../../skills/run-mlcc-spice/SKILL.md)及[公共生命周期](../../../../skills/references/task-lifecycle.md)为准。专业输入/schema、物理定义与检查仍由本模块维护。

Use the host-bound operation: `spice.ac_impedance_si` / `spice.transient_si` accept explicit SI numbers (F, ohm, H, Hz, V, A, s); `spice.ac_impedance` / `spice.transient` accept structured value/unit/source quantities. Shared UNIT core1.0.0/catalog1.2.0 provides capacitance/F, resistance/ohm and inductance/H. Preserve the authorized representation; the deterministic Adapter invokes the unique shared core and retains its audit. Do not convert values mentally, drop user units, use F/m as F, or switch operations in a bound session. UNIT admission and SI/quantity native equivalence have Main acceptance evidence; they do not grant scientific or per-task sampling acceptance.

Every model needs safe model_name/model_version, source synthetic/manual, explicit nonempty validated_conditions, C>0, ESR/ESL>=0, and null or positive terminal leakage. No measured/vendor/FEM source, arbitrary netlist, include, file path, executable, deployment, shell, fitting, nonlinear, temperature/bias law, or cross-scale transfer. Clarify missing scientific values; use exactly a user-authorized input/example without changing any field. Demonstration numbers are selected synthetic fixtures, never material defaults.

AC accepts one to eight independent series RLC branches in parallel; optional leakage is parallel across each complete branch. Port current is positive into DUT; Z=V(port)/i(vtest). 1 V AC is linear normalization, with RMS interpretation solely for Re(V conj(I)) power bookkeeping. Explain sampled minima and interpolated imaginary zeros separately. A branch L/C cancellation frequency is not a network antiresonance; ESL=0 has no series SRF. Network peaks require sweep/refinement evidence; one ordinary task has sampling_sensitivity=not_checked. Ideal lossless exact resonance can be singular or numerically ill-conditioned; preserve native/quality failure.

Transient uses finite positive source R, independent external line L, baseline DC operating point (no UIC), explicit delay/rise/hold/fall/stop/maxstep, one finite pulse and recovery. Ifeed-Iload-Icap=0; capacitor power/current is negative while delivering to the bus. Never take absolute values to hide direction. RMS is over the actual finite pulse/recovery sample window, not periodic steady-state ripple. Comparisons across no-C/ideal-C/nonideal-C are valid only with the same source/load; parasitics do not imply every metric worsens at every instant.

TaskRecord/SiteRunner controls the explicitly authorized Slurm lifecycle. Creation stages inputs without submission; adapter preflight runs inside the allocation. query checks the scheduler, collect retrieves evidence and read-result reads saved results. A follow-up uses the existing task and never resubmits or starts an inner worker. Report actual execution, numerical QC, scientific not_checked, errors/limitations, native raw/CSV/metrics/curve references. Historical qualification does not upgrade a new task's unchecked convergence/material/device status. No calculation/QC decisions are delegated to an LLM.
