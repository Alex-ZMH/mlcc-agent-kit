# SPICE 0.2.0 — SI and structured quantities

Independent Windows standard-library Adapter → existing Ubuntu-24.04 WSL spice-env → **ngspice 41**. This is working native scientific execution, not an analytic solver or prototype-output replay. Shared UNIT core1.0.0/catalog1.2.0 now provides C/R/L; all four operations are registered. Main verified 8 new successful native tasks, three SI/quantity pairs with exactly equal raw vectors, and a real LLM execution/read-only follow-up. See [current report](../../docs/verification/spice-closure-2026-10-24/report.md) and [release sources](UNITS_SOURCES.json).

## Operations and inputs

| Operation | Input | Results |
|---|---|---|
| `ac_impedance_si` / `ac_impedance` | 1–8 model branches, explicit Hz endpoints, integer points_per_decade, single_frequency | Native complex Z/current/voltage CSV, phase deg, sampled minimum, interpolated imaginary zeros, branch L/C cancellation and sampled network maxima, RMS-normalized power |
| `transient_si` / `transient` | nullable model, explicit source/load/timeline circuit, maxstep_s | Signed source/load/cap currents and capacitor power, voltage droop/overshoot, finite pulse/recovery RMS, leakage-aware DC and energy diagnostics |

All quantities in `_si` operations are explicit SI numbers: F, ohm, H, Hz, s, V, A. Quantity operations accept explicit value/unit/source records (including compatible replay), mapped by the unique shared core; use single-quantities.json and transient-quantities.json. Do not strip units to force them through an SI operation. Scientific model source is synthetic/manual only. Model metadata: safe model_name, model_version, source, nonempty validated_conditions (`type`, `temperature`, `dc_bias`, `note` finite text fields). C>0, ESR/ESL>=0, enabled leakage>0; null disables leakage. Zero ESR/ESL omit components. Topology is a series RLC branch with optional terminal leakage in parallel; parallel networks have no shared PCB L. External transient line L is distinct from each MLCC ESL.

AC uses a 1-V small-signal voltage source and 0-V current probe into DUT; Z=V/I. Re(V conj(I)) uses RMS interpretation only for normalized power; no peak 1/2 or real wideband voltage rating is implied. Single-frequency requests use count=1 and identical endpoints. DEC sweeps require endpoint alignment to the explicit log grid; endpoint/grid/actual count are checked. Imaginary zeros are interpolated only within saved samples. A series branch SRF and network antiresonance are different; no SRF is invented for ESL=0/out-of-band. Lossless exact resonance can fail numerical acceptance even when native output is finite.

Transient uses baseline DC operating point, no UIC, finite positive source R and finite rise/fall. delay and hold are positive; stop includes full pulse and recovery. Supply/baseline/pulse increment and L are nonnegative in this version. `Ifeed-Iload-Icap=0`; capacitor current/power can be negative while delivering energy. RMS uses the first actual sample >=delay through stop, recorded in metrics. It is not periodic steady-state ripple. The 100 ns post-rise diagnostic must fit the requested timeline.

Non-goals: C(V), temperature laws, frequency-dependent fitting, measured/vendor model loading, parameter inversion, PCB extraction, arbitrary netlists/includes/control text, Buck control, periodic ripple qualification, FEM/RVE automatic input, electrothermal feedback, new Agent/Web/scheduler. Calibration and device applicability remain not_checked.

## Deployment and commands

Python 3.11+, public layer stdlib only. NumPy/Matplotlib are imported only by scientific workers in the existing spice-env. No FEniCS/PETSc/scientific_core dependency. No environment installation or upgrade performed. Current verified backend: Python 3.11.17, ngspice 41, NumPy 2.4.6, Matplotlib 3.11.2. The deployment sample is host configuration, never scientific input; adjust absolute paths when moving the complete Bundle.

```powershell
$MlccPython = 'C:/Users/Xiang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$env:MLCC_SPICE_DEPLOYMENT = 'D:/Zhaoxiang/code/mlcc-main/modules/spice/deployment.example.json'
& $MlccPython -m mlcc check
& $MlccPython -m mlcc describe spice
& $MlccPython -m mlcc preflight spice ac_impedance_si --input modules/spice/examples/single-si.json
& $MlccPython -m mlcc preflight spice transient_si --input modules/spice/examples/transient-si.json
Get-Content modules/spice/examples/adapter-preflight.json -Raw | & $MlccPython -I modules/spice/adapter.py
$q = & $MlccPython -m mlcc run spice ac_impedance_si --input modules/spice/examples/parallel-si.json --defer | ConvertFrom-Json
& $MlccPython -m mlcc worker $q.task_id
& $MlccPython -m mlcc status $q.task_id
& $MlccPython -m mlcc result $q.task_id
& $MlccPython -m mlcc artifact $q.task_id artifacts/solver/output.raw
```

Analogous transient execution uses `transient_si` / `examples/transient-si.json`. Examples include no capacitor, ideal C, leakage, invalid C/edge values and ill-conditioned ideal LC. Arbitrary cwd: use absolute adapter path, or public CLI `--project D:/Zhaoxiang/code/mlcc-main` before subcommand. No runtime sys.path/cwd dependency; scientific package uses a fixed file-relative isolated bootstrap.

WSL deployment probe only, no solver analysis or output:

```text
wsl.exe -d Ubuntu-24.04 --exec /home/zhaoxiang/miniconda3/envs/spice-env/bin/python -I -B /mnt/d/Zhaoxiang/code/mlcc-main/modules/spice/science_entry.py --probe --ngspice /home/zhaoxiang/miniconda3/envs/spice-env/bin/ngspice
```

The host passes native request/response file paths through argv without shell. The scientific request includes **canonical SI only**, trusted ngspice absolute path and budget. Native launch examples are preserved per task in `artifacts/native/launch.json` and `request.json`; do not reuse completed directories. Per ngspice process <=120s; WSL client <=150s, Adapter <=180s. No automatic retry/service. An outer WSL timeout leaves native termination UNKNOWN; killing a Windows client proves nothing about Linux tasks. A direct solver subprocess timeout preserves diagnostics and records its own child termination separately.

## Tests and explicit qualification

Default checks start no WSL, ngspice or online model:

```powershell
& $MlccPython -m unittest discover -s tests -v
& $MlccPython -m unittest discover -s modules/spice/tests -v
& $MlccPython modules/spice/harness/unit_acceptance.py --output modules/spice/work/units-NEW.json
```

The offline UNIT script is historical prerequisite admission only; even if it reports partial_pass it is not the full Runtime/scientific test. Full current equivalence evidence is in the Main report above. Explicit real harness (choose **new** output directories; never overwrite evidence):

```powershell
& $MlccPython modules/spice/harness/runtime_batch.py --deployment modules/spice/deployment.example.json --output modules/spice/work/runtime-NEW
wsl.exe -d Ubuntu-24.04 --exec /home/zhaoxiang/miniconda3/envs/spice-env/bin/python -I -B /mnt/d/Zhaoxiang/code/mlcc-main/modules/spice/harness/qualify_saved.py --batch /mnt/d/Zhaoxiang/code/mlcc-main/modules/spice/work/runtime-NEW --windows-root D:/Zhaoxiang/code/mlcc-main
wsl.exe -d Ubuntu-24.04 --exec /home/zhaoxiang/miniconda3/envs/spice-env/bin/python -I -B /mnt/d/Zhaoxiang/code/mlcc-main/modules/spice/harness/native_failures.py --ngspice /home/zhaoxiang/miniconda3/envs/spice-env/bin/ngspice --output /mnt/d/Zhaoxiang/code/mlcc-main/modules/spice/work/failures-NEW
```

27-analysis matrix is a qualification fixture, never the cost of an ordinary user task. `qualify_saved.py` reopens this batch and the frozen prototype, runs the original unchanged thresholds and compares all native vectors. It starts no solver. Original experiment/source/evidence is read-only; no prototype imports or output reuse in production.

## Evidence and limitations

Each Runtime task retains raw input, canonical/solver SI, normalization audit, source manifest, real backend environment, deck/raw/log/stdout/stderr/execution record, CSV/metrics, PNG, independent native readback and hashes. Summary carries no full curve. Output complex values are CSV real/imaginary columns; JSON numbers remain finite. Required checks are split into numerical/scientific; historical PASS is never inherited as a new task's sampling/material QC. Query and repeated terminal worker are read-only and hash-audited.

See [acceptance](ACCEPTANCE.md), [migration](MIGRATION_MATRIX.md), [source hashes](SOURCES.json), [Main handoff](MAIN_HANDOFF.md), [case matrix](harness/cases.json). Machine-specific paths in work evidence are not portable defaults or credentials. Public LLM host executable binding may need refresh independently of scientific deployment.


## Current Main receipt (2026-10-24)

25 module tests pass. Five-suite regression: 251 tests / 250 passed / 1 preexisting Windows symlink skip. Two AC and one transient SI/quantity native-array pairs are exactly equal; all eight new successful tasks and original 27 task snapshots remain unchanged under read-only queries. Material/device/periodic and per-task sampling sensitivity stay not_checked.

Cold WSL startup can exceed the original 6-second module probe. Main preserved both probe blocks and explicitly checked environment readiness before approving the saved Agent proposal; no uncertain solve was retried. Backend/solver/client timeouts remain unchanged. Existing dated SI-stage acceptance and SOURCES.json remain historical; UNITS_SOURCES.json identifies the current 0.2.0 code release.

```powershell
& $MlccPython -m mlcc preflight spice ac_impedance --input modules/spice/examples/single-quantities.json
& $MlccPython -m mlcc preflight spice transient --input modules/spice/examples/transient-quantities.json
```


## 2026-10-26 可选 native Linux 部署接口

新增显式 `transport=native_linux` 的独立部署 schema 与 `deployment/native.example.json`，保留原 WSL 配置和科学输入。依赖在所选 Deployment 预检中确定验证，module.json 不再无条件要求 wsl.exe；这不表示后端已安装或科学预检已通过。使用同一 science_entry.py、独立 Conda Python 和原 UNIT/QC，不经 shell/SSH/自动回退。

配置、版本、检查和临时服务器验证后清理边界见 [main 交接](../../docs/server-deployment-2026-10-26/main-handoff.md)。新增接口未在本机运行科学求解，也不表示服务器永久部署或远程 Agent 已上线。当前源码指纹见 `NATIVE_LINUX_SOURCES.json`；旧 SOURCES / SCIENTIFIC_CORE_SOURCES / UNITS_SOURCES 继续保留为历史冻结。
