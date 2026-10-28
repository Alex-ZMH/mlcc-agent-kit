# SPICE acceptance — 0.2.0 receipt and historical 0.1.0 SI migration

## 2026-10-24 current Main receipt — supersedes the historical pending status

SPICE 0.2.0 registers ac_impedance_si / transient_si / ac_impedance / transient. The shared core1.0.0/catalog1.2.0 prerequisite is resolved; no second conversion table was added. Main's new acceptance has 25 module tests, 15 preflight rejections, 8 successful native tasks, three exactly equal SI/quantity raw-vector pairs, and real LLM execution with a hash-stable read-only follow-up. Physics and professional schemas are unchanged. See [full Main report](../../docs/verification/spice-closure-2026-10-24/report.md), [UNIT release sources](UNITS_SOURCES.json) and [machine index](../../docs/verification/spice-closure-2026-10-24.json).

Cold WSL startup may exceed the original 6-second preflight probe; the blocked attempts were preserved and environment readiness explicitly checked before the saved proposal was approved. Per-task sampling, material/device applicability and periodic steady state remain not_checked. The dated text below describes the original 2026-10-23 SI-only stage; it is retained as history, not a current blocker.

2026-10-23, Windows Main → stdlib Adapter → Ubuntu-24.04 WSL spice-env → native ngspice. This report does not claim full completion while the public C/R/L catalog remains absent. Material/device applicability is not_checked, as scoped; no scientific owner/product sign-off is inferred.

## Contract and source boundary

Only `modules/spice/` source/deployment/docs/tests were changed. Runtime and Agent generated their own new records under outputs. No public/core/other module/experiment source changed. [Protected-file comparison](work/runtime-qualification-20261023/protected.comparison.json) is identical during the full batch; final audit separately records the final state. Prototype `freeze.py --check` matched all 1185 files before migration; no original solve rerun/refreeze. [SOURCES.json](SOURCES.json) records exact original and migrated hashes and reasons; production imports no experiments, Main, other scientific modules or FEniCS core.

Formal registered operations: `ac_impedance_si` (single + controlled parallel), `transient_si`. Both queued, explicit worker, interface 1.0, evidence real_computation only on validated native success. Input/output schemas are inline supported public subset. Finite bounded conditions keys support the existing strict bounded LLM host. Quantity adapters/schemas are prepared but unregistered pending Main; no all-reject stub is advertised as a capability.

## Default and CLI checks

Baseline public tests: 90 total, 89 pass / 1 Windows symlink-privilege skip. Final public tests: same outcome in [public log](work/public-tests-final.log). Module lightweight tests: **21 passed**, [log](work/lightweight-tests-final.log). Neither default suite launches WSL/ngspice/online model. Tests cover schema/domain/source/duplicate JSON/nonfinite/bool/counts/identifier injection/case conflicts, SI canonical/audit immutability, available UNIT equivalence/replay, explicit pointer coverage, direct Adapter/CLI admission consistency, arbitrary cwd, no professional import on Windows, preflight no-execute, budget refusal, host schema compilation and mocked outer timeout with native termination UNKNOWN/no retry.

Commands (README interpreter, cwd Bundle root):

```text
python -B -m unittest discover -s tests -v
python -B -m unittest discover -s modules/spice/tests -v
python -B -m mlcc check
python -B -m mlcc describe spice
python -B -m mlcc preflight spice ac_impedance_si --input modules/spice/examples/single-si.json
```

Structure valid (8 modules); describe discovers spice from module.json; live preflight ready using configured absolute ngspice. Invalid examples reject before scientific execution. Exact real CLI argv/stdout/stderr/return codes for every full-batch submission, worker and read operation are in [commands.json](work/runtime-qualification-20261023/commands.json).

## New full scientific batch

[Runtime batch](work/runtime-qualification-20261023/summary.json): **27 new tasks / 27 real ngspice analyses**, all succeeded. Three capabilities each traverse formal Runtime→Adapter→WSL, not just a standalone migrated script. Single 7 cases, transient/RC 12 cases, parallel 8 cases. [Task index](work/runtime-qualification-20261023/index.json) maps original case labels to fresh task IDs and absolute native evidence; no old experiment output is used as new evidence. Actual environment: Python 3.11.17, ngspice 41, NumPy 2.4.6, Matplotlib 3.11.2, one configured thread; absolute executables recorded per task. No package install/upgrade.

[Numerical qualification](work/runtime-qualification-20261023/qualification/acceptance.json) reopens the fresh native outputs and applies unchanged `cases/validation.json` and original migrated stage checks. All three stages pass. All raw vectors have the same sample grids/shapes as the frozen original; **maximum pointwise/global-vector relative difference = 0.0**, tolerance 1e-12 unchanged. No interpolation, tolerance relaxation or compressed-file byte comparison was needed.

| Numerical observation | Value / interpretation |
|---|---|
| Single max complex Z relative error, including finite leakage | 7.945026277744505e-9, threshold 1e-8 |
| Interpolated imaginary-zero frequency relative error | 1.020597596657069e-6, threshold 2e-5 |
| Sampled-minimum frequency relative error | 3.797004838215212e-4, threshold .003 |
| Direct series cancellation point | ESR relative error 0 |
| RC finite-ramp errors at 20/10/5 ns | 1.3914648e-5 / 7.3899535e-6 / 1.9183894e-6 V; decreasing, below 2e-5 V |
| Fine parallel antiresonance peak | about 41.2691 MHz / 2.8486632 ohm |
| Damped B ESR=.25 ohm peak | about .354451 ohm; ratio .12442713 |
| Ordinary task QC | sampling_sensitivity and full UNIT not_checked; no historical PASS copied |

The original finer sampling/finite-ramp/KCL/DC/power/energy conditions pass with the original topology, line L and Gear2 tolerances. No calibration/product threshold was invented. Source/branch port signs and finite-window RMS definitions are preserved. Curve PNGs for fine transient and parallel tasks were visually inspected: labels/units/legends readable, no overlap/clipping.

Every batch task has read-only status/result/artifact and repeated terminal worker checks; **all 27 task trees have identical before/after SHA256**, including record/log/artifacts. No query triggers computation.

## Failures and edge behavior

[Explicit backend/structural harness](work/native-failures-20261023/acceptance.json) preserves actual missing-subcircuit failure, true exit-0/no-output failure, wrong endpoint/vector/start/count rejections, two instances of the same model, and corrupted raw point count/truncation/nonfinite checks. These are harness-only deliberately invalid decks, never a public arbitrary-netlist operation. There are 8 actual solver invocations in this harness, not 11: 11 reported categories include three structural raw corruptions. Exact ideal-LC floating-point resonance returned finite ill-conditioned data in the low-level probe; this is preserved as an observation, not a claimed valid impedance.

Formal task `task-a4da7c3383b14b3c90826bd1e55cff38` then exercises that ill-conditioned LC through Runtime. Native numbers are finite, but independent relative comparison is .5; **formal execution fails**, retains native/readback diagnostics and does not publish success values. This is expected failure, not a failed delivery hidden by exit 0.

Formal leakage transient `task-88b13f95818a49779cfa800a0fdfdad0` succeeded. A final targeted case `task-9335bf1959504fad933839ca26d710bc` verifies separated ESR/leakage/total dissipation labels and added source/load current CSV readback; [final leakage report](work/leakage-metrics-final-20261023/acceptance.json). No full 27-case repeat was required: numerical topology/normal cases are unchanged. Baseline, original attempt and targeted evidence are retained separately.

The first negative harness attempt failed because its intended nonfinite mutation did not match native whitespace, leaving valid raw data. The harness now asserts mutation actually changes data. Existing real results were reused only to complete that explicit harness audit, not represented as new computation; old unchanged and corrected corrupted files remain. [Development observations](work/development-observations.json) records this and deployment setup events.

## UNIT and scientific boundaries

[UNIT machine gate](work/units-20261023.json): **blocked**, core 1.0.0/catalog 1.1.0 has no capacitance/resistance/inductance kinds. Existing Hz/MHz, s/ns, V/mV, A/mA conversions/replay pass; SI C/R/L are explicit compatibility fields with no local conversion. Full F/nF/uF, ohm/mohm and H/nH formal equivalence is **not_checked**. See [UNIT report](UNITS_ACCEPTANCE.md), [design](UNITS_DESIGN.md), [Main proposal](INTERFACE_PROPOSAL.md).

Material calibration, measured/product applicability, cross-scale transfer, per-user-task refinement and periodic steady-state ripple acceptance remain not_checked/outside scope. The current formal native success does not upgrade them.

## Agent evidence

The public host configuration initially referenced a nonexistent old Codex executable: CODEX_UNAVAILABLE, no model call or task. A module-local binding selects the actually installed executable, preserving the same provider/model gpt-6.1-sol, effort low, normal login and no-tools policy. No public config was modified, no credentials were read and no provider fallback performed. The original setup failure remains in `work/agent-e2e-20261023/`.

**Actual online PASS:** session `agent-fb38a8a651b344a0890aa118abc56e86`, task `task-e38e0a7bda174eb8a5864c5f40e882cf`; two real turns, four successful bounded model calls, exactly one session submission/worker/running event. First turn succeeded with the authorized example unchanged; same-session follow-up computed_this_turn=false and task-tree hashes unchanged. [Authoritative saved-session audit](work/agent-e2e-current-host-20261023/acceptance.session-audit.json), [complete real dialogue](../../outputs/agent/agent-fb38a8a651b344a0890aa118abc56e86/conversation.md).

Initial Agent harness whole-directory counting included the separately executed targeted leakage task during model latency and reported FAIL despite the read-only hash check passing. The final audit attributes ownership using actual session task_created and host_worker_requested events; no model/science call was repeated, no original report/transcript was edited. The future harness now does this directly. A first saved-audit invocation also needed explicit UTF-8 on Windows and failed before writing a report; the corrected read-only audit passed. Original model prose is retained even where it calls limitations warnings or says its fact card lacks independent input-equality evidence; the deterministic saved input equality check is passed. Server model/effort echo remains null when the CLI does not emit it.

Final runtime total for this migration is 31 formal tasks (30 scientific execution successes, 1 intentional ideal-LC numerical rejection), plus 8 explicit low-level backend harness invocations. This is distinct from 27 analyses in the one complete qualification batch. [Final source/freeze/task audit](work/final-audit-release.json) records the final code manifest and original experiment integrity; science/material not_checked and full UNIT blocked remain unchanged.
