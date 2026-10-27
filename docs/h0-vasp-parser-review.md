# H0 VASP parser review: real Ni fixture job 20

Review date: 2026-10-20  
Scope: read-only review of the collected single-GPU VASP fixture run and the
existing `parse_vasp_outputs` result. This document does not change the
parser, rerun VASP, or claim a production-material result.

## Evidence reviewed

The reviewed task is
[`workspace/tasks/h0-ni-single-v004`](../workspace/tasks/h0-ni-single-v004/).
Its Slurm record in `task.json` reports job `20`, partition `gpu`, one V100,
`COMPLETED`, exit `0:0`, and runtime `00:07:29`. The recorded submission was
through `ssh v100 ... sbatch --parsable job.sbatch`; the final scheduler query
was `ssh v100 scontrol show job 20`. The collected files include `vasprun.xml`,
`OUTCAR`, `CONTCAR`, `OSZICAR`, the stdout/stderr logs, and the input files.

The calculation is the four-atom, cubic Ni engineering fixture. `INCAR` has
`ISPIN=2`, `ENCUT=400`, `ISMEAR=1`, `SIGMA=0.2`, `EDIFF=1e-7`,
`EDIFFG=-0.02`, `NSW=0`, and `IBRION=-1`; `KPOINTS` is Gamma `9 9 9`.
Therefore this is a static SCF validation of the parser and engine wiring. It
is not an ionic relaxation and is not a CaZrO3 production calculation.

The independent XML check used the project environment and deliberately
disabled POTCAR parsing:

```powershell
& .\workspace\.venv\Scripts\python.exe -c 'from pathlib import Path; import numpy as np; from pymatgen.io.vasp import Vasprun; from pymatgen.core import Structure; d=Path("workspace/tasks/h0-ni-single-v004"); v=Vasprun(str(d/"vasprun.xml"), parse_dos=False, parse_eigen=False, parse_potcar_file=False); s=v.ionic_steps[-1]; c=Structure.from_file(str(d/"CONTCAR")); print("ionic_steps", len(v.ionic_steps)); print("energies", s["e_fr_energy"], v.final_energy, s["e_wo_entrp"]); print("convergence", v.converged_electronic, v.converged_ionic); print("force_max_eV_per_A", np.max(np.linalg.norm(np.asarray(s["forces"]), axis=1))); print("stress_raw_kbar", np.asarray(s["stress"])); print("xml_species", [site.specie.symbol for site in v.final_structure]); print("xml_vs_contcar_max_cart_A", np.max(np.abs(np.asarray(v.final_structure.cart_coords)-np.asarray(c.cart_coords))))'
```

The command completed with `ionic_steps 1`, energies
`-21.87778308`, `-21.87619034`, and `-21.87300486` eV, electronic and
pymatgen ionic flags both `True`, maximum force `0.2723990400645483` eV/A,
four Ni symbols, and a maximum XML/CONTCAR Cartesian difference of
`9.6e-9` A.

## Energies

The three values in `result.json` match the final VASP XML/OUTCAR records:

| Result field | Value | Meaning |
| --- | ---: | --- |
| `e_fr_energy` | -21.87778308 eV | finite-smearing `free energy TOTEN` |
| `e_0_energy` / `energy_eV` | -21.87619034 eV | `energy(sigma->0)` |
| `e_wo_entrp` | -21.87300486 eV | energy without entropy |

These are total four-atom cell energies, not energies per atom. The method
record declares `e_fr_energy` as the finite-smearing energy whose derivative is
used for the metal forces/stress. The parser does not use an OUTCAR energy
fallback; the values above come from the selected pymatgen `Vasprun` fields.

## Forces and stress

The XML final-step forces and the final OUTCAR force table agree row by row in
eV/A. The result preserves the four POSCAR/CONTCAR rows and reports
`max_force_eV_per_A = 0.2723990400645483`. The force sum is approximately
`(1e-8, 0, 0)` eV/A, consistent with the final VASP drift line.

The result stress is consistent with the raw XML and OUTCAR stress. VASP
prints the matrix in kBar; the adapter converts it with `0.1 kBar = 0.1 GPa`
and preserves the declared VASP compression-positive representation. The
result's tensile-positive matrix is exactly the negative of that matrix. The
Voigt order is explicitly `[xx, yy, zz, yz, xz, xy]`.

The raw final XML/OUTCAR stress is approximately:

```text
[[-10.58233943,  0.00000189, -0.00000200],
 [ 0.00000243, -10.65780078, -0.00001211],
 [-0.00000263, -0.00001380, -10.65758566]] kBar
```

The parser result contains the corresponding compression-positive matrix
`0.1 * raw` in GPa and the tensile-positive matrix `-0.1 * raw` in GPa. The
small antisymmetric off-diagonal values are retained rather than silently
symmetrized. Independent comparison of the XML matrix, `result.json`, and
OUTCAR shows no stress transpose in this run.

## Atom and magnetic mapping

`POSCAR.atom-map.json`, the XML final structure, and `CONTCAR` all contain the
same four Ni atoms in the same order. The final Cartesian coordinates agree to
`9.6e-9` A, and the first engineered displacement remains at approximately
`x=0.03` A. The real job therefore exercises an identity mapping only; equal
Ni species cannot independently prove a nontrivial atom permutation.

The parser's source-ID mapping is nevertheless exercised by the existing
unit-only parser fixture, which uses distinct source IDs/elements and checks
that forces and per-atom magnetization are restored to source order. On the
real run the returned IDs are `[0, 1, 2, 3]`, matching the source map.

The magnetic rows in `result.json` are the OUTCAR per-ion local projection in
micro-Bohm (`s`, `p`, `d`, `tot`) and are in source-ID order. All four rows are
`(-0.007, -0.025, 0.650, 0.618)`. Their rounded sum is `2.472` micro-Bohm,
whereas the OUTCAR total line is `2.471`; this is ordinary table rounding.
The OSZICAR `mag=2.4199` is a different total scalar and must not be treated
as the same local-projection quantity. No magnetic mapping error is evidenced.

## Convergence interpretation

The scheduler completion and VASP stdout support a successful process exit.
The final OUTCAR says the electronic loop stopped because `EDIFF` was
reached, and the XML has 19 electronic steps with
`converged_electronic=True`. Electronic convergence is therefore supported by
both the raw output and the parsed result.

Pymatgen also reports `converged_ionic=True` for this one-step XML, but the
input is `NSW=0`/`IBRION=-1`: no ionic relaxation was requested and the force
maximum is `0.2724` eV/A, well above `|EDIFFG|=0.02` eV/A. The parser correctly
exports `ionic_converged=null` for the `scf` stage. The result status
`converged_engineering_fixture` should consequently be read as an electronic
fixture result, not a force-relaxed geometry or a production-material
qualification.

## Current test coverage

The current unit-only parser test is useful for ID permutation of both forces
and magnetization, distinct-element/source-ID restoration, energy field
selection, stress units/sign/Voigt naming, and passing
`parse_potcar_file=False`. The real job confirms those transformations against
VASP output for an identity map.

The synthetic stress matrix is symmetric, so that unit test does not by itself
distinguish a transpose. This is a test-coverage limitation rather than a
scientific defect: the real regression script independently compares the
parsed stress with the collected XML and printed OUTCAR stress, checks the
physical symmetry tolerance, and checks every declared Voigt component.

The force test catches atom-row permutation because the synthetic vectors are
distinct, while it does not separately test a Cartesian-axis transpose. The
real XML/OUTCAR force rows agree and show no such transpose. The magnetization
test does catch per-atom ID permutation; the all-Ni real fixture again only
provides an identity mapping check.

## Review conclusion

For job 20, `result.json` is numerically faithful to the final VASP XML,
OUTCAR, and CONTCAR for energies, forces, stress conversion/sign, final
structure, and per-ion magnetization mapping. The parser's explicit
`ionic_converged=null` interpretation is scientifically correct for this
static SCF. No production phase, dopant, relaxation result, or CaZrO3 claim is
made by this evidence.

The remaining unit-test limitation is that its stress case does not exercise a
nontrivial transpose; an explicit Cartesian-axis force permutation case would
also make that coverage more direct. The real-output regression evidence is
recorded separately in `workspace/reports/h0/real-vasp-regression.json`.
