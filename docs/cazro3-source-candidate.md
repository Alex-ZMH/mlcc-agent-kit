# CaZrO3 Pnma source candidate

Status: **source candidate for the user-selected undoped CaZrO3 orthorhombic
baseline**. This note does not mark the production structure as accepted and
does not select a temperature, supercell, dopant, compensation model, or
production DFT method.

## Primary candidate: COD 1532747

The raw candidate is stored at
[`workspace/sources/cazro3/COD-1532747.cif`](../workspace/sources/cazro3/COD-1532747.cif).
It was downloaded directly from the [COD CIF endpoint](https://www.crystallography.net/cod/1532747.cif)
on 2026-10-20. The [COD information card](https://www.crystallography.net/cod/1532747.html)
identifies the entry as CaZrO3, gives 20 atoms (`Z = 4`), and states that COD
data are public-domain/CC0. The file is retained verbatim; no axis transform,
relaxation, or generated coordinates were written over it.

The COD record cites:

> I. Levin, T. G. Amos, S. M. Bell, L. Farber, R. S. Roth, T. A. Vanderah,
> and B. H. Toby, “Phase equilibria, crystal structures and dielectric anomaly
> in the BaZrO3–CaZrO3 system,” *Journal of Solid State Chemistry* **175**,
> 170–181 (2003), DOI [10.1016/S0022-4596(03)00220-2](https://doi.org/10.1016/S0022-4596(03)00220-2).

The raw CIF records the following cell and setting:

| quantity | raw COD value |
|---|---:|
| chemical formula | Ca O3 Zr |
| space-group number | 62 |
| Hermann–Mauguin symbol in CIF | P c m n |
| Hall symbol | -P 2n 2ac |
| a, b, c | 5.58305, 8.00703, 5.75904 Å |
| volume | 257.4501 Å³ |
| Z / atom count | 4 / 20 |
| Wyckoff content | Ca 4c, Zr 4b, O1 4c, O2 8d |

The Levin paper reports neutron-powder Rietveld refinements for the CaZrO3
end member at 173, 298, 373, and 473 K. Its Table 2 identifies the same
173-K cell and coordinates as the COD file (for example, 5.58305, 8.00703,
5.75904 Å and the Ca/O coordinates in the downloaded CIF). This temperature
assignment is an inference from the exact numerical match: the COD CIF itself
does not carry a usable diffraction-temperature tag.

The same paper states that the end-member samples were made by solid-state
reaction from CaCO3, BaCO3, and ZrO2, with a 950 °C calcine followed by several
1400–1550 °C heatings. Neutron data were collected at NIST BT-1 in He exchange
gas; the paper's experimental details and temperature series are available in
the [public article transcription](https://doczz.net/doc/8286910/phase-equilibria--crystal-structures--and-dielectric-anomaly)
and the publication record is also maintained by [NIST](https://www.nist.gov/publications/phase-equilibria-crystal-structures-and-dielectric-anomaly-bazro3-cazro3-system).
The paper does not report an applied pressure for these refinements; retain
pressure as “not reported” until the study records an explicit ambient-pressure
assumption. The samples were sealed under He exchange gas in vanadium
containers during neutron measurements.

## Setting and temperature cross-check

The user selected **Pnma**. The primary sources use equivalent No. 62
settings with different Hermann–Mauguin strings: the Levin/COD file uses
`Pcmn`, while the paper discusses the Ca-rich end member as `Pbnm`. These
strings must not be treated as interchangeable text labels. The production
loader must make an explicit axis/setting transform and record it together
with the atom mapping. The raw CIF above remains in its original `Pcmn`
setting until that mapping is accepted.

As a local software check, the current pymatgen environment reads the raw
file as 20 sites of CaZrO3 and `SpacegroupAnalyzer` identifies No. 62 as
`Pnma`. Its conventional-standard representation reorders the cell lengths
to `(5.58305, 5.75904, 8.00703) Å`; this is a software standardization result,
not a replacement for a documented crystallographic setting transform.

For a room-temperature cross-check, the AIST Crystal Structure Gallery gives
CaZrO3 at 27 °C in `Pcmn` with `a = 5.5912(1)`, `b = 8.0171(2)`, and
`c = 5.7616(1) Å`, `V = 258.26(2) Å³`, `Z = 4`, and the refined fractional
coordinates. It cites the original neutron study by H. J. A. Koopmans,
G. M. H. van de Velde, and P. J. Gellings, *Acta Crystallographica Section C*
**39**, 1323–1325 (1983), DOI
[10.1107/S0108270183008392](https://doi.org/10.1107/S0108270183008392).
See the [IUCr record](https://journals.iucr.org/paper?buy=yes&cnor=a22710)
and the [AIST data page](https://unit.aist.go.jp/mmri/ja/organization/db-nomura/common/struc-coord/CaZrO3-c.html).
The AIST page is a useful room-temperature cross-check, but it is an HTML
table rather than a deposited CIF; no CIF was synthesized from that table.

## Local validation performed

Using the project environment:

```text
workspace/.venv/Scripts/python.exe -  [inline pymatgen check]
formula CaZrO3
n_sites 20
lattice [5.58305, 8.00703, 5.75904] volume 257.45010182
SpacegroupAnalyzer: Pnma, No. 62
conventional standard sites: 20
```

This validates file readability, composition, atom count, cell volume, and
space-group number only. It is not a DFT, force, phonon, dielectric, or
production-phase validation.

## Decision needed before production use

1. Confirm whether the baseline should use the 173-K COD structure or a
   room-temperature structure represented by the 298-K primary table/AIST
   cross-check. The current COD file is not a room-temperature CIF.
2. Confirm the exact Pnma axis convention expected by the production study.
   Apply and record one explicit setting transform before writing
   `source.cif`/model artifacts; do not silently infer it from a library's
   standardization.
3. Keep the undoped CaZrO3 baseline separate from later dopant/compensation
   studies. No dopant, vacancy, phase mixture, or interface was selected by
   this investigation.

