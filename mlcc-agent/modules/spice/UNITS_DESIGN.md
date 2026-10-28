# Quantity admission design

## 2026-10-24 current Main receipt — supersedes the historical pending status

SPICE 0.2.0 registers ac_impedance_si / transient_si / ac_impedance / transient. The shared core1.0.0/catalog1.2.0 prerequisite is resolved; no second conversion table was added. Main's new acceptance has 25 module tests, 15 preflight rejections, 8 successful native tasks, three exactly equal SI/quantity raw-vector pairs, and real LLM execution with a hash-stable read-only follow-up. Physics and professional schemas are unchanged. See [full Main report](../../docs/verification/spice-closure-2026-10-24/report.md), [UNIT release sources](UNITS_SOURCES.json) and [machine index](../../docs/verification/spice-closure-2026-10-24.json).

Cold WSL startup may exceed the original 6-second preflight probe; the blocked attempts were preserved and environment readiness explicitly checked before the saved proposal was approved. Per-task sampling, material/device applicability and periodic steady state remain not_checked. The dated text below describes the original 2026-10-23 SI-only stage; it is retained as history, not a current blocker.

Windows `spice_module/contract.py` owns one canonicalize entry used by preflight and execute. Every external field has an explicit JSON Pointer and expected kind; `mlcc/units.py` in the same Bundle is invoked with `[sys.executable, '-I', absolute_core_path]`, JSON stdin, shell=False, timeout, strict finite/duplicate-key decoding, response/core checks and audit coverage. No scientific dependencies on Windows, no second conversion table, no raw units interpreted in WSL.

| Field | Expected kind / canonical |
|---|---|
| models[i]/model capacitance_F | capacitance / F, pending Main |
| esr_ohm, leakage_resistance_ohm, source_resistance_ohm | resistance / ohm, pending Main |
| esl_H, line_inductance_H | inductance / H, pending Main; separate physical fields |
| fmin_Hz, fmax_Hz | frequency / Hz |
| supply_V | electric_potential / V |
| baseline_A, step_A | current / A |
| delay/rise/hold/fall/stop_s, maxstep_s | time / s |
| points_per_decade | count, strict JSON integer, no scaling/bool |

Quantity schemas explicitly require `{value,unit,source:{kind,reference}}`, source synthetic_test/manual. Scientific model metadata remains source synthetic/manual and explicit applicable conditions. The retained `_F/_ohm/_H/_s` keys denote the internal target semantics; quantity operations carry containers at those pointers, not bare numbers. null model disables the capacitor; null leakage disables that branch and is skipped. Domain positivity is validated after shared-core conversion, never before only.

`ac_impedance_si` and `transient_si` are intentionally separate fixed-SI compatibility operations. Available kinds still use shared-core `bare_unit` and retain quantity records. Missing C/R/L kinds are retained as **fixed_si_fields**, not fabricated `mlcc.quantity.v1` records. `unit_admission` remains not_checked and full multi-unit completion is blocked. This is an intermediate scientific delivery, not a replacement for the required UNIT extension.

Prepared `ac_impedance`/`transient` adapters and strict schemas verify actual required kind/canonical semantics, allow append-compatible catalog versions, and reject UNITS_CATALOG_GAP now. They are not advertised in module.json. Main must publish the kinds before registration/full equivalence acceptance. There are no hidden conversion factors or guesses about future catalog version.

Task records preserve Runtime's original payload. Module artifacts separately retain `input.original.json`, `input.canonical-si.json`, `unit_normalization.json`, `input.solver-si.json`, actual circuit.cir, source and environment hashes. Repeated preflight/execute starts with the same original representation. Canonical WSL recheck validates SI only; it does not call UNIT again. Shared quantity records are replay-verified in tests; a canonical numeric value is never rescaled using a previous raw-unit context.

Power W and phase deg are fixed output declarations. No generalized power/angle input conversion is introduced. SPICE m/M/MEG textual suffixes are never used; all deck numbers use explicit finite scientific notation.
