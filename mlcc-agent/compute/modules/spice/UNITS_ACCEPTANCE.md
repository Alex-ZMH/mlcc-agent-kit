# UNIT acceptance — 0.2.0 receipt and prerequisite history

## 2026-10-24 current Main receipt — supersedes the historical pending status

SPICE 0.2.0 registers ac_impedance_si / transient_si / ac_impedance / transient. The shared core1.0.0/catalog1.2.0 prerequisite is resolved; no second conversion table was added. Main's new acceptance has 25 module tests, 15 preflight rejections, 8 successful native tasks, three exactly equal SI/quantity raw-vector pairs, and real LLM execution with a hash-stable read-only follow-up. Physics and professional schemas are unchanged. See [full Main report](../../docs/verification/spice-closure-2026-10-24/report.md), [UNIT release sources](UNITS_SOURCES.json) and [machine index](../../docs/verification/spice-closure-2026-10-24.json).

Cold WSL startup may exceed the original 6-second preflight probe; the blocked attempts were preserved and environment readiness explicitly checked before the saved proposal was approved. Per-task sampling, material/device applicability and periodic steady state remain not_checked. The dated text below describes the original 2026-10-23 SI-only stage; it is retained as history, not a current blocker.

2026-10-23 verified live: core 1.0.0, catalog 1.1.0. Capacitance/F, resistance/ohm, inductance/H are absent. [Machine gate](work/units-20261023.json) reports blocked and full_UNIT=not_checked. No public core/schema/test was modified, no local factor registry exists, and the full quantity operations are not advertised as implemented.

Passed in lightweight tests: strict SI model/domain/source admission, original payload unchanged, explicit pointers, null leakage skipped, ESL vs external L retained, canonical SI recheck without scaling, raw quantity audit replay, existing Hz/MHz, s/ns, V/mV and A/mA shared-core equivalence and wrong-dimension/unknown/bool rejection. Fixed-SI C/R/L fields are recorded separately with their explicit units, not forged shared-core records. Every 27-case Runtime record preserves raw input; canonical/solver values and audit are separate artifacts.

Not checked / blocked: full public F/nF/uF, ohm/mohm and H/nH admission and equivalent real tasks; C/R/L aliases/prefix/case/underflow compatibility; full multi-unit Runtime/Adapter/WSL equivalence for both operations. Shared current/frequency/time/voltage tests alone do not satisfy that requirement.

Prepared `harness/unit_acceptance.py` will perform actual core equivalence/replay, typed field mapping, input immutability and rejection checks **after** publication. Its future partial_pass still requires registering the two quantity operations and running new formal Runtime equivalent tasks. Nothing automatically installs/patches a core, changes catalog versions, or turns unavailable tests into pass.

Main action is specified in [INTERFACE_PROPOSAL.md](INTERFACE_PROPOSAL.md). The current delivery is functional SI migration with new real numerical evidence, not final completion of the full SPICE development prompt.
