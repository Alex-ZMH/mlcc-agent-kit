# ABACUS resources and public entry · 2026-10-30

ABACUS is the default production DFT engine. Select VASP only when the customer
explicitly requests it; do not fall back after an ABACUS failure. Engine choice,
installed resources, input compatibility, native convergence and material
qualification are separate facts.

## Resource selection

The preferred source is [AIS Square dataset 381](https://www.aissquare.com/datasets/detail?pageType=datasets&id=381),
`ABACUS-APNS-PPORBs-v1(efficiency-clean)`, published by `pxlxingliang` on
2025-09-29. Its public metadata declares CC BY 4.0. Original SG15 attribution
and CC BY-SA 4.0 requirements are retained alongside the dataset declaration.

The inspected archive contains **83 UPF files and 83 numerical orbital files**,
covering H–Bi. The 86-file count in the readiness report included metadata; it
was not the number of UPF resources. The orbital README requires pairing with
the corresponding pseudopotential directory and element map. These are
efficiency orbitals for occupied-state properties; they are not a precision
orbital set for high-accuracy unoccupied-state work.

AIS gaps use [PseudoDojo scalar PBE sources](https://github.com/PseudoDojo/ONCVPSP-PBE-SR)
for Po and Rn, and the [author's heavy-element library](https://github.com/gmatteo/pseudos_ac_she)
for At and Fr–Ts. Those supplemental resources have no fabricated AIS orbital
pairing and are PW-only. The heavy-element repository does not declare a data
redistribution license; its files remain on the private compute site and are
not included in this GitHub repository or a public downloadable Bundle.

Og has no verified NC UPF in the checked author sources. Its directory record
must remain `missing`. A 118-row periodic table is the inspection scope, not a
claim that 118 pseudopotentials or 118 paired orbital sets are installed.
Actual installed counts and unresolved downloads are recorded in the release
evidence, not inferred from an upstream description.

Tm's AIS UPF has `nc=10`, `nv=4`; the native 4f configuration row is inside the
core partition. Its paired efficiency NAO does not restore frozen 4f electrons.
The [published Tm-sp input](https://github.com/PseudoDojo/ONCVPSP-PBE-PDv0.4/blob/master/Tm/Tm-sp.in)
is a separate f-valence source; a matching UPF and NAO have not been generated
or accepted by this release. Do not use the f-core resource to claim Tm 4f DOS
or f-shell magnetism.

## User and method interface

`mlcc_describe_dft_resources()` reads the installed 118-element summary.
Passing `elements=["Ba","Ti","Na","Ca","Tm","O"]` returns native header
metadata, source, limitations and registered resource IDs for those elements.
Absolute resource and pairing-record paths are not returned to the user.

Use `selected[].pseudopotentials[].id` in method `pseudopotential_ids` and
`selected[].orbitals[].id` in `numerical_orbital_ids`. The orbital `library_id`
binds method `numerical_orbital_library_id`. The compute site's registered
library resolves the README and element map. Old explicit library records
continue to work. Do not guess a server path or pair an orbital with a different
pseudopotential.

The existing method inspection API reads resources directly when
`ssh.transport="local"`. It does not open loopback SSH. UPF `PBE` and
`SLA PW PBX PBC` are recognized as the same PBE declaration while the native
string is retained. The method's ABACUS input functional remains canonical
`PBE`.

## Operator installation

Keep the downloaded resources and generated catalog outside the portable
Bundle. Extract the AIS archive into a private versioned directory:

```text
ais381/
  apns-pseudopotentials-v1/
  apns-orbitals-efficiency-v1/
```

Supplement metadata has `resources[].files[]` records with `local_path` and
the exact author `url`, preserving the native inputs and license status.
No converter, engine substitution, automatic download retry or checksum cache
is used.

On the compute site, use the existing scientific environment through Slurm:

```bash
python scripts/resources/build_abacus_catalog.py \
  --ais-root /private/ais381 \
  --site /private/site.json \
  --supplement-root /private/author-supplements \
  --output /private/new-resource-registration
```

The tool reads actual UPF/NAO headers and writes `abacus-library.json`,
`site.updated.json` and `report.json` to a new directory. Existing PP aliases,
other engines and continuum settings are preserved. The generated site points
to its private catalog and adds the registered AIS orbital library. Existing
project site copies refresh from the operator template at MCP startup.

Install the new immutable Bundle, bind its Worker to the generated site, run
the existing Worker healthcheck and publish through the existing operator
catalog flow. Preserve the previous accepted version and protected config for
rollback. Existing conversations retain their deployment pins; use a new
conversation to select this version. No Server/Web release or new credential
is required for this upgrade.

## Acceptance and remaining work

Acceptance consists of focused software checks, actual installed resource
inspection, and two consecutive ordinary-user conversations in the same thread.
Save both completed runs, resource tool calls/results, publication and Worker
metadata, screenshots and a zero-material-submission assertion. Preserve the
initial missing-fixture failure and any failed downloads separately.

The readiness report's claim that Na/Tm compensation necessarily produces
`gap=0` is not a computed result and must not block the software route. Do not
predetermine oxidation state, spin localization or the band gap from the resource
filename. Its claimed absence of a BTO source is project-local: an existing
P4mm baseline with provenance exists in the operator archive and is not silently
injected into another user's project.

The earlier Ca/Tm selection conflicts with the attached Na/Tm report; 5% cannot
be represented by an integer substitution in the specified 2×2×2 cell. Those
scientific inputs remain unresolved. This release submits no material job.
Spin-polarized fixed occupations, PDOS, variable-cell relaxation and charged
response interfaces remain later work; resource registration does not assert
those capabilities or launch a validation campaign.
