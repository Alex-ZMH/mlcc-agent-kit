# Operation task creation and executor errors · 0.60.6

The repair is based on the developer-delivered **0.60.5**, backed up before any
changes at commit `5718e1839d9e27f3e83361e25a7ba1c14f16350f` on
`codex/developer-0605-backup-20261103`. The earlier local 0.60.3 record did not
describe the current deployment. The source archive remains in the private
operator workspace; credentials, site configuration and user scientific data
are excluded from GitHub.

## What failed

The visible operation-task interface still used ordinary `ValueError` for
expected caller errors. MCP 2.3.0 hides those messages as unexpected tool
failures. The 0.60.3 scale-task repair did not cover this separate operation
interface. A valid operation request can include
`"schema": "mlcc.operation-task-request.v1"`; removing every `schema` field is
not the general fix.

Slurm jobs **880** and **881** were actually submitted and finished
`FAILED / 1:0` after two and one seconds, respectively. Both had empty stdout
and stderr and no saved operation result. Their execution wrapper redirected
CLI stderr into a buffer. The CLI uses `argparse.parser.exit` for domain input
errors, which raises `SystemExit`; `except Exception` did not catch it. The
buffer and result were therefore lost before writing.

The saved request referenced by 880 used `source` instead of `source_path`.
The request referenced by 881 contained only `source_path`, omitting the
required provenance, identity, material and selected phase. The executor's
rejection when run outside Slurm is a separate guard and does not establish
that those real jobs lacked an allocation.

## Changes

- Expose the operation task request schema in both MCP `tools/list` and
  `mlcc_describe_operations`. Convert explicitly identified caller errors to
  `ToolError`, preserving field names and argparse diagnostics. Invalid
  creation does not stage a task. Site and internal faults retain their
  original exception handling.
- Return the existing request-file contract when describing `import-model`,
  `derive-supercell` or `derive-defect`. This distinguishes CLI paths, the
  platform request envelope and the scientific JSON document. No parameter
  alias, phase choice or missing provenance is inferred.
- Save `SystemExit` as a failed operation result with the actual exit code,
  original stderr and readable error message. Preserve the process exit code
  and existing collect/read routes.

Creation continues to stage inputs only. Structure reading, scientific
validation and geometry generation remain inside Slurm; this repair does not
introduce an early numerical preflight, retry loop or a second runner.

## Validation and deployment

Current evidence is recorded in
[`evidence/operation-entry-repair-20261103.json`](evidence/operation-entry-repair-20261103.json).
The isolated real-allocation regression exercises both historical malformed
input shapes and a one-to-two-atom software fixture through import, supercell
and explicit vacancy derivation. These checks do not execute the user's
material workflow or establish material qualification. Jobs 880/881 and their
payloads are retained unchanged; no SCF, MD or solver matrix is submitted.

0.60.5 is the rollback target. Installing a candidate is distinct from
activating the Worker and publishing its catalog. Existing conversation pins
are not automatically migrated; a newly published version is selected in a
new conversation. The final evidence records which of those steps completed.
