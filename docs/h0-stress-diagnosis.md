# H0 VASP stress and finite-strain diagnosis

Review date: 2026-10-20. This is a read-only diagnosis of the already
collected Ni engineering-fixture jobs. It does not change the comparison
result, acceptance thresholds, task records, or any input file, and it does
not claim a production-material conclusion.

## Scope and evidence

The comparison is implemented by
[`scripts/h0/compare_vasp.py`](../scripts/h0/compare_vasp.py) and its output is
[`workspace/reports/h0/vasp-comparison.json`](../workspace/reports/h0/vasp-comparison.json).
The relevant as-run tasks are:

| Task | Slurm job | Cell parameter | ENCUT | KPAR | K mesh | Status |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `h0-ni-single-v004` | 20 | 3.5200 A | 400 eV | unset | Gamma 9x9x9 | COMPLETED, 0:0 |
| `h0-ni-four-v004` | 21 | 3.5200 A | 400 eV | 4 | Gamma 9x9x9 | COMPLETED, 0:0 |
| `h0-ni-cutoff500-v004` | 24 | 3.5200 A | 500 eV | 4 | Gamma 9x9x9 | COMPLETED, 0:0 |
| `h0-ni-strainminus-v004` | 25 | 3.5024 A = 0.995 x 3.52 | 400 eV | 4 | Gamma 9x9x9 | COMPLETED, 0:0 |
| `h0-ni-strainplus-v004` | 26 | 3.5376 A = 1.005 x 3.52 | 400 eV | 4 | Gamma 9x9x9 | COMPLETED, 0:0 |

The task records and raw files are under
[`workspace/tasks`](../workspace/tasks/). `run-vasp.sh` is byte-for-byte the
same across these cases. The strain POSCARs retain the same direct
coordinates, so `scale_atoms=True` was applied consistently: the engineered
0.03 A displacement is 0.02985 A and 0.03015 A in the minus and plus cells.
The KPOINTS files are identical Gamma-centered 9x9x9 meshes. The only INCAR
changes are the explicit `ENCUT=500` in job 24 and `KPAR=4` in the four-rank
jobs; the single-rank base has no KPAR line. Job 21 provides a same-cell,
same-400-eV four-rank control: its parsed energy and stress agree with job 20
to the stored precision, so the single-versus-four KPAR/rank difference does
not explain the observed strain result.

## What `compare_vasp.py` actually tests

The helper reads `result.json` and asserts only `electronic_converged`; it does
not independently re-query Slurm. The task records nevertheless show native
Slurm completion and exit `0:0` for all five jobs.

For the 400/500 comparison it computes the per-atom absolute difference in
`e_fr_energy`, the maximum Cartesian force-component difference, and the
maximum component difference of the stored tensile-positive stress matrix. It
does not compare stress traces in that branch.

For the strain check it uses the 400-eV base cell volume

```text
V0 = det([[3.52, 0, 0], [0, 3.52, 0], [0, 0, 3.52]])
   = 43.614208 A^3
```

and the declared linear strain `epsilon=0.005`:

```text
dF/d epsilon = (F_plus - F_minus) / (2 epsilon V0) * 160.21766208
```

Here `F` is the stored finite-smearing `e_fr_energy` and the conversion is
from eV/A^3 to GPa. The comparison is against the trace of the stored
tensile-positive VASP stress. This is the correct central-difference relation
for an isotropic linear strain at the unstrained cell if the stress and energy
are converged consistently.

## Independent numerical review

The parsed values are:

| Case | `e_fr_energy` (eV) | raw stress trace (kBar) | tensile-positive trace (GPa) |
| --- | ---: | ---: | ---: |
| 400 eV base | -21.87778308 | -31.89772587 | 3.189772587 |
| 500 eV base | -21.87369119 | -13.62698599 | 1.362698599 |
| -0.5% strain | -21.87356440 | 59.16619513 | -5.916619513 |
| +0.5% strain | -21.87016266 | -115.62334646 | 11.562334646 |

The 400-to-500 eV stress change is real in the collected result:

```text
energy difference per atom: 0.0010229725 eV
maximum force-component difference: 0.00019608 eV/A
maximum stress-component difference: 0.609389879 GPa
```

The maximum stress difference is the diagonal `yy` component. The trace
changes by 1.827073988 GPa, from 3.189772587 to 1.362698599 GPa in the
tensile-positive representation.

For the strain pair:

```text
F_plus - F_minus = 0.003401740000001041 eV
central derivative trace = 1.249635966802805 GPa
reported base tensile trace = 3.189772587 GPa
absolute difference = 1.9401366201971952 GPa
```

The one-sided energy slopes make the finite-step behavior visible. Using the
same `V0` and conversion, the minus-to-base slope is `-3.099481007 GPa` and
the base-to-plus slope is `5.598752941 GPa`; their average is the reported
`1.249635967 GPa`. The stress traces at the three cells are
`-5.916619513`, `3.189772587`, and `11.562334646 GPa`, respectively. The
large change over the interval means that the +/-0.5% pair is not evidence of
a locally linear derivative.

Changing the energy label does not remove the discrepancy. Repeating the
same central calculation with the collected values gives:

| Energy label | Central derivative trace (GPa) |
| --- | ---: |
| `e_fr_energy` | 1.249635967 |
| `e_0_energy` | 1.396617173 |
| `e_wo_entrp` | 1.690590604 |

The method record correctly selects finite-smearing `e_fr_energy` for metal
force/stress derivative comparisons; the failure is therefore not fixed by
silently changing the energy field.

## Raw VASP association and cutoff observation

For every case, the final `vasprun.xml` ionic step and the final OUTCAR block
agree on the free energy and stress. For example, the base OUTCAR records:

```text
free  energy   TOTEN  = -21.87778308 eV
energy without entropy = -21.87300486 energy(sigma->0) = -21.87619034
in kB -10.58234 -10.65780 -10.65759 0.00000 -0.00001 -0.00000
external pressure = -10.63 kB  Pullay stress = 0.00 kB
```

The 500-eV block records `TOTEN=-21.87369119 eV` and diagonal stress
`-4.49918, -4.56390, -4.56391 kB`. The parser's 0.1 kBar-to-GPa conversion
and tensile sign are consistent with these raw records. All cases have one
static ionic step and electronic convergence (`18` or `19` electronic steps).

The stress change with ENCUT is evidence that the reported stress is not
cutoff-converged at the 400-eV fixture setting. It is compatible with a
basis/cutoff (often called Pulay or incomplete-plane-wave) contribution, but
the hypothesis is not proven by these jobs: VASP prints `Pullay stress = 0.00
kB` to two decimal places for the final blocks, and no independent ENCUT
convergence series exists. The observed cutoff dependence must therefore be
recorded as a numerical convergence failure, not assigned a confirmed cause.

The finite-strain mismatch has additional possible contributors that are not
separated by the present data: the 0.5% step is too large for a local linear
derivative in this strained, displaced Ni fixture; the fixed 9x9x9 discrete
k-point mesh has no independent k-mesh convergence check; and finite
smearing (`ISMEAR=1`, `SIGMA=0.2`) makes the relevant free energy and stress
sampling-sensitive. The same-cell four-rank control rules out an observed
rank/KPAR effect at the stored precision, but does not replace a convergence
study.

## Minimum additional experiment

The smallest next experiment that distinguishes the most immediate ambiguity
is a **two-job smaller central difference**:

1. Reuse the exact job-20 geometry and method, with `ENCUT=400`, `KPAR=4`,
   Gamma 9x9x9, `ISMEAR=1`, `SIGMA=0.2`, `NSW=0`, and linear strains
   `epsilon=-0.001` and `+0.001`.
2. Use the same remote Ni POTCAR and the same four-rank Slurm resource shape.
3. Compare the new `e_fr_energy` central derivative to the existing 400-eV
   base tensile trace, retaining the raw OUTCAR/XML stress and original job
   records.

If the smaller-step derivative moves toward `3.19 GPa`, the current failure is
primarily a finite-step/nonlinear-strain issue. If it remains near `1.25 GPa`,
the stress/energy mismatch persists at a local step. The smallest follow-up
that then tests cutoff dependence of that derivative is the corresponding
`-0.001/+0.001` pair at `ENCUT=500`, with all other fields unchanged; the
existing 500-eV base job supplies the central stress reference. A single
additional 600-eV base job can show whether the unstrained stress continues to
move with cutoff, but it cannot by itself establish the finite-strain
derivative relation.

No new job was submitted during this diagnosis. The current engineering
fixture remains outside production qualification, and the existing failed
checks remain recorded as failed in `vasp-comparison.json`.
