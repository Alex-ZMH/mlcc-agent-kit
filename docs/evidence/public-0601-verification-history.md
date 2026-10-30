# Public 0.60.1 verification history

## What was verified

- v100 user-level Node `22.23.2`, Codex `0.146.0`, Python `3.12.3` and MCP
  `2.3.0` were present; the Worker healthcheck returned `1`.
- The existing scientific environment already had `numpy`, `ase`, `scipy`,
  `phonopy`, `phonors`, `symfc`, `h5py` and `pymatgen`. It was not changed.
- The candidate Bundle exposes 13 MCP tools, 8 top-level Skill routes, 7
  nested module-method routes and 114 CLI catalog routes. The public catalog
  returned all 15 Skills; individual Skill filters passed in the v100 probe.
  Four generic operation-contract reads, four scale-contract reads, eight
  public `*-0601` tasks created and prepared, and six historical
  `mlcc_read_result` calls completed. Prepared task job IDs were all `null`.
- Five repaired public calls completed, and the same thread/provider session
  continued successfully across a Worker restart. No Slurm command or
  scientific computation was submitted. Seven Linux control tests passed.
- The Worker runtime has three small source patches: Node resolution through
  `process.execPath`; removal of the rejected native
  `model_supports_reasoning_summaries` override while retaining the catalog
  capability; and artifact-boundary handling for site config and task payloads
  at two entry points. The targeted config test passed, both artifact-boundary
  tests passed, and final Worker typecheck passed. The Node-path suite remains
  39 initial passes plus one targeted corrected pass, not a complete final
  40-case rerun.

These checks establish the candidate public control path and current Worker
deployment, not scientific execution or material qualification.

