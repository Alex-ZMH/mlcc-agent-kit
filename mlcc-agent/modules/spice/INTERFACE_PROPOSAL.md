# SPICE UNIT prerequisite — resolved, historical Main request below

## 2026-10-24 current Main receipt — supersedes the historical pending status

SPICE 0.2.0 registers ac_impedance_si / transient_si / ac_impedance / transient. The shared core1.0.0/catalog1.2.0 prerequisite is resolved; no second conversion table was added. Main's new acceptance has 25 module tests, 15 preflight rejections, 8 successful native tasks, three exactly equal SI/quantity raw-vector pairs, and real LLM execution with a hash-stable read-only follow-up. Physics and professional schemas are unchanged. See [full Main report](../../docs/verification/spice-closure-2026-10-24/report.md), [UNIT release sources](UNITS_SOURCES.json) and [machine index](../../docs/verification/spice-closure-2026-10-24.json).

Cold WSL startup may exceed the original 6-second preflight probe; the blocked attempts were preserved and environment readiness explicitly checked before the saved proposal was approved. Per-task sampling, material/device applicability and periodic steady state remain not_checked. The dated text below describes the original 2026-10-23 SI-only stage; it is retained as history, not a current blocker.

2026-10-23: current `mlcc/units.py` core 1.0.0 / catalog 1.1.0 has no capacitance, resistance or inductance kinds. This thread changes no public file. SI operations are an explicitly labelled intermediate delivery, not full multi-unit completion.

Request additive kinds `capacitance → F`, `resistance → ohm`, `inductance → H`. Required whitelist: F/mF/uF/nF/pF; ohm/mohm/kohm/Mohm; H/mH/uH/nH/pH. Main decides finite aliases (µ/μ, Ω/mΩ/kΩ/MΩ) and publishes tests. Preserve case: milli and mega differ. No SPICE suffix parsing: netlists always contain finite canonical scientific notation.

Examples: `/models/0/capacitance_F={value:10,unit:nF,source:{kind:synthetic_test,reference:single baseline}}`, `/models/0/esr_ohm` 50 mohm, `/models/0/esl_H` 0.5 nH. Time/frequency/current/voltage already use their existing kinds. Each field is explicitly mapped; null leakage is not converted. Zero ESR/ESL allowed, C and enabled leakage strictly positive after conversion.

Main tests: case/prefix/aliases, bool, nonfinite, tiny nonzero underflow, zero with conflicting unit, unknown/wrong dimension, record replay without double scaling, unchanged old requests and append-compatible catalog. No execution protocol change, no hard dependency on an exact catalog version. Module checks actual required kind/canonical semantics through the existing isolated JSON RPC.

Prepared `ac_impedance` / `transient` quantity adapters and schemas remain **unregistered** until the real catalog provides all three kinds. After publication run module UNIT tests/full equivalence harness and register these two operations using the same output schema/execution/QC as their `_si` counterparts. No alternative conversion table is supplied here.

Other public follow-ups: queued snapshots do not freeze deployment/scientific source contents; WSL client timeout does not prove native termination. Current module records hashes and declares unknown termination without retry; no new scheduler/cancellation API requested for this delivery.
