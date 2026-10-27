# P5.07 native strain bridge — bounded engineering protocol

2026-10-23. This adds native evidence to enabled0.24.0, not an automatic0.25 release. Runtime source is `/home/v100/projects/mlcc/development/0.24.0/installed/0.24.0/src`; interpreter `/home/v100/projects/mlcc/development/0.9.0/venv/bin/python`; shared dependencies0.15.0. Only an actual software defect justifies a candidate fix/affected-path acceptance. Do not rerun0.24 mathematics, installed219 or MatterAI host.

## Necessity and exact scope

Job213 proves geometry/input creation;217/218 prove response software,219 proves saved delivery. None contains native SCF/Berry for a **strained cell**.177/178 and180–185 contain atomic displacement in a fixed cell, so cannot cover the changed native quantum, own-cell charge source or strain manifest binding. Saved outputs therefore cannot establish the missing native producer→parser→new consumer edge.

Use the two already materialized213 CZO20-atom child models, yy strain−0.01/+0.01, neutral, clamped ions/fixed fractions, no applied field. Preserve original phase/dopant selection, fractional coordinates and atom mapping. **Exactly two SCF and two gdir1 Berry NSCF tasks maximum**. gdir1 is transverse to yy and tests the change in quantum with cell volume; one direction suffices for this source/geometry/unit path. Do not add gdir2/3, a reference, second step, additional strain component or material/temperature matrix to obtain a full Cartesian column. Do not repeat old calculations.

Original213 manifest:
`/home/v100/projects/mlcc/reports/berry-strain-response-v001/installed-213/materialized-response/response-manifest.json`.

Parent Study/model remain the declared CZO source under development/0.10.0/project/workspace. The two213 `points/yy-minus/model` and `points/yy-plus/model` directories are reused as scientific structure sources; no new model generation or relaxation.

## Method/runtime binding

Use the previously successful177/178/180–185 GPU method/site snapshots:

- `/home/v100/projects/mlcc/reports/berry-response-native-v001/config-gpu-v002/method.cazro3-berry-gpu-v002.json`
- corresponding `site.v100-berry-gpu-v002.json`
- implementation `mlcc-abacus-3.10.1-berry-gpu-v001`, binary `/home/v100/projects/mlcc/tools/abacus-berry-gpu-v001/install/bin/abacus`
- MPI `/home/v100/miniforge3/envs/mlcc-abacus-berry-gpu-build-v001/bin/mpiexec.hydra`, environment `/home/v100/projects/mlcc/configs/abacus-berry-gpu-v001-env.sh`.

Freeze ABACUS3.10.1 PW/PBE, nspin1 fixed occupations, noSOC/noncollinear, neutral, symmetry−1,100Ry,2×2×2kmesh,scf_thr1e−4,scf_nmax100,88bands,mixing_beta0.3, same PP identities/treatment. These are existing engineering settings, not production precision. Berry NSCF uses existing pw_diag_thr1e−6 protocol and its own point's SCF charge. No parameter tightening, initial-state guessing, method substitution or automatic retry.

213 used the older standardGPU runtime. To keep all four tasks on the already proven BerryGPU runtime without mutating213 evidence, the preparation job reuses213 child model/Study files and existing SCF creator to materialize fresh **unsubmitted** task inputs under the main native report. Preserve a native manifest copy that records original213 manifest/task paths, same response/point/child identities and new method/site/task bindings. Compare new INPUT/STRU/KPT/atom map against213 (expected no scientific changes). This is explicit runtime binding before first execution, not an engine fallback or repeated DFT. Use the existing strain binding functions and runner; no new portable wrapper or parser.

## Resources and order

Each actual DFT: gpu partition,one node,oneV100,oneMPI,oneCPU,8192MiB,explicittime0,no-requeue. This is below the authorized ceiling1V100/1MPI/4CPU/8GiB. Submit **only one DFT at a time**, query and retain its native terminal state before next submission. Do not cancel a normally running DFT based on elapsed time. If the path needs resources above the ceiling, record a blocker instead of increasing resources.

Preparation/first parsing/consumer checks are separate nonDFT Slurm CPU jobs,1CPU/2GiB,at most10minutes. Local machine only edits, transfers controls/files and reads evidence. Submission/query use existing SiteRunner with the previously accepted already-on-v100 control transport; inputs materialized on the execution host are explicitly staged in situ, not described as a nonexistent network transfer. Native job IDs/terminal states remain in each TaskRecord and report.

Order: prepare twoSCF inputs/bindings → SCFminus/query → SCFplus/query → first SCF parsing and twoNSCF creation only if each own SCF converged → NSCFminus/query → NSCFplus/query → first Berry parsing → existing consumer once → parentStudy saved delivery. No automatic retry of any failed step. After a diagnosed software-only failure, repair only that step and reuse all successful native calculations/parsed sources.

## Acceptance / stopping expansion

Acceptance tests the real path: F/cell/volume/fixed fractions/atom IDs, GPU/runtime/protocol mapping, Slurm terminal/exit, native electronic convergence (iteration exhaustion is failure), SCF own-charge linkage, gdir1 and per-point native quantum, saved source/method/task/Study/manifest consistency, and public consumer/Study transfer. Full scalar/reduced source data must remain traceable.

Branch integers and bases remain null; do not choose branches for passing tests. Expect missing branches andgdir2/3; full proper/improper Cartesian vectors can remain null. Response magnitude, expected CZO symmetry/zero, k/step convergence and scientific screening are not reasons for additional DFT. Scientific/production/full-tensor qualification remainfalse. Failure states are retained explicitly; no synthetic sources or values.

## Ownership / outputs

Main owns `workspace/reports/berry-strain-native-v001/`, preparation/transfer/submit/query/collect, native first parsing, necessary producer fixes and final public Study delivery/plan update. Existing implementation chat owns `workspace/reports/polarization-strain-native-v001/` and the saved-source consumer acceptance only; it does not submit/parse DFT or modify producer/sharedCLI. Consumer code may change only for an observed actual defect, with a minimal targeted check. Supervisor's read-only audit does not own code. No FNV/relaxed-ion/MD113/MACE work here.

After the four-task source path and one consumer/Study acceptance, append evidence to0.24 if no software changed. Record actual software paths and exact successes/failures, retain gaps, then return to next ready P5 work. No standalone version bump for documentation/evidence.
