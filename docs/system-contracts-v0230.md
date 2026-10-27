# 0.23 P5 SCF energy path delivery

0.23.0 has passed its changed-path module, installed consumer and original MatterAI host checks and is enabled/frozen. 0.22.0 is the rollback release; source metadata advances to0.24.0. Registry, MCP and local Python binding all select0.23.0. [Release evidence](../workspace/reports/polarization-energy-integration-v001/acceptance.json).

## Delivered behavior

`polarization-energy --request REQUEST --output RESULT` consumes explicit ordered fixed-cell SCF sources, checks common physical/numerical conditions, atom mapping and parent lineage, and computes relative whole-cell eV, endpoint difference and the sampled maximum with its sources. `deliver-properties --study PARENT_STUDY --polarization-energy RESULT --output DELIVERY` consumes the saved result without recalculating the path. [Request/physical contract](p5-v023-energy-path-contract.md).

Different child Study/model IDs are retained through a shared explicit parent. Missing Berry or unresolved branches do not suppress valid SCF energies. Berry NSCF energies are never used as SCF reference energies. Explicit Study model paths, task/result/job identities, saved input parameters and original qualification/fixture flags remain bound to each point.

## Actual acceptance

| Evidence | Result | Scope |
|---|---|---|
| v100 Slurm211 | COMPLETED/0:0,3seconds,29new checks | New energy/source adapter and one public CLI execution; software fixtures separated from native engineering |
| v100 Slurm212 | COMPLETED/0:0,3seconds,10new checks | Installed CLI/Study dispatch and one saved native-path delivery; no repeated source parsing or path arithmetic |
| Original MatterAI host | passed,0.23.0,7MCP tools | Installed bundle discovery, actual `mlcc_list_tasks` call and aligned runtime binding |
| Release/install comparison |137text files equal | Direct comparison, no hashes |

Both new jobs requested1CPU/2GiB/2minutes/no-requeue with numerical library threads1; Slurm allocated2CPU hardware threads to each request. They performed postprocessing/software checks only. No new DFT, MD or training, no frozen acceptance reruns and no material accuracy optimization.

The real path reuses GPU SCF177/178 and saved Berry180/183 parsed by187. The ordered CZO atom8 −0.01/+0.01Å samples yield an endpoint difference of **+0.003013417335751001eV/cell**; the highest sampled point is178. This demonstrates two supplied fixed-cell structural samples and parameter delivery, not a resolved ferroelectric switching path. [Installed result](../workspace/reports/polarization-energy-integration-v001/installed-212/delivery.json).

## Remaining boundaries

Physical branch/insulating-path/ferroelectric qualification remain missing. NEB barrier, spontaneous polarization and finite-temperature free energy remain null; double-well/material production qualification remains false. The first slice does not implement variable-cell, imposed-pressure, constrained-relaxed or NEB energy paths. It does not complete P5.02–P5.04 as a scientific material study.

Complete Born/Γ/electronic dielectric sources, physical Berry paths and later P5 response work remain in the queue. P4 full charge correction is deferred after its source review; no FNV dependency was installed and no correction producer was implemented in this release. MACE parameter discrepancy remains deferred and does not block independent system development.

Older software copies await recorded retirement;0.22 rollback, scientific inputs/native outputs/evidence, shared0.9 environment and0.15 dependencies/build tools are preserved. No old copy was deleted in this slice.
