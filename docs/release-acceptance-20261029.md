# 0.60.0 cloud delivery acceptance

This branch publishes the 0.60.0 candidate from
`integration/four-scale-compute-20261028`. The Bundle manifest binds one MLCC
Agent to eight Skills:

- `model-mlcc-structures`
- `run-mlcc-dft`
- `run-mlcc-md`
- `run-mlcc-phase-field`
- `run-mlcc-rve`
- `run-mlcc-fem`
- `run-mlcc-spice`
- `compute-mlcc-properties`

The four new remote engineering lifecycles used the existing authorized `v100`
SSH alias and Slurm runner:

| scale | operation | Slurm job | final state | result reader |
| --- | --- | ---: | --- | --- |
| FEM | `electrostatics_2d_quantities` | 702 | `COMPLETED`, `0:0` | passed |
| phase field | `vector_evolve_si` | 703 | `COMPLETED`, `0:0` | passed |
| RVE | `homogenize_electrostatics_2d` | 704 | `COMPLETED`, `0:0` | passed |
| SPICE | `ac_impedance` | 705 | `COMPLETED`, `0:0` | passed |

The local evidence is retained under
`workspace/reports/four-scale-workbench-20261028/lifecycle-20261029/` and is
excluded from Git because it contains task outputs and site-specific paths.
Existing modeling, DFT, MD, and properties evidence was reused rather than
re-running old scientific jobs.

The focused portable checks passed: 37 tests passed and one optional test was
skipped. The full suite still requires private native fixtures and the optional
`BoltzTraP2` transport extra; those dependencies are intentionally not bundled
or installed by this delivery. The Windows-specific host resolver regression
suite passed four tests. Its source remains in the private MatterAI host tree;
see [the resolver note](host-resolver-fix-20261029.md).

Cloud delivery is configuration-ready but not claimed as deployed. The public
endpoint `43.142.15.151:22022` accepted TCP connections during the check, while
the available local SSH identity was rejected. An operator must provide a valid
SSH alias and identity before copying the checkout to the cloud server. No
localhost endpoint is required by the bundle.
