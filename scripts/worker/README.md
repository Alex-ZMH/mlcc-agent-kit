# v100 Worker operator boundary

This directory documents the 0.60.2 user-level v100 Worker. It is an operator
guide, not a launcher. `deployment_mlcc_v100_0_60_2` revision 4 is published;
the Worker healthcheck is `1`, the service is active and its database heartbeat
is online. The 0.60.1 catalog is unpublished but remains enabled for rollback.
Two consecutive ordinary-user read-only turns passed in the same thread and
Codex provider session on revision 4. A third turn confirmed the Bh metadata
correction after the Worker resource update. All three runs completed; their
four tool calls used only `mlcc_describe_dft_resources` and created zero
`task.json` files. No material calculation has been submitted.

The required private resource registration reports 117 available UPF elements,
83 paired NAO resources and `Og` missing. Slurm job 776 was explicitly exempted
as a release precondition because the v100 node was occupied; it remains
`PENDING`, was not cancelled or bypassed, and is not a pass result.

The latest private catalog metadata correction records Bh as Z=107, `nc=10`,
`nv=8`, with 4f core and 5f valence; Tm remains Z=69, `nc=10`, `nv=4`, with
4f core. The metadata-only correction was applied in generator commit
`ef490a8`; it added no solver or test job. See [`docs/abacus-library-20261030.md`](../../docs/abacus-library-20261030.md)
for the detailed resource and qualification limits.

## Observed prerequisites

The v100 user directory contained:

- Node `22.23.2` and Codex `0.146.0`;
- Python `3.12.3` and MCP `2.3.0`;
- Worker healthcheck output `1`;
- existing scientific packages `numpy`, `ase`, `scipy`, `phonopy`, `phonors`,
  `symfc`, `h5py` and `pymatgen`.

The scientific environment was not modified. MCP dependencies were read-only
migrated from the verified Docker SDK; a PyPI install attempt encountered an
index timeout. The Worker runtime has one Node path change, from a fixed
`/usr/local/bin/node` to `process.execPath`; typecheck passed, 39 cases passed
the initial suite, and the remaining case passed a targeted recheck after its
hard-coded expectation was updated. Other runtime adapters are unchanged.

The private runtime carries three small patches:

1. `runtime-node-path.patch`: resolve Node through `process.execPath`.
2. `codex-config-0146.patch`: remove the rejected native
   `model_supports_reasoning_summaries` override while retaining the catalog
   `supports_reasoning_summaries` capability.
3. `mlcc-artifact-boundary.patch`: at two entry points, skip
   `configs/site.v100.json` and `tasks/*/payload`, including an optional
   `project/` prefix.

The targeted Codex config test passed, two artifact-boundary targeted tests
passed and final Worker typecheck passed. The Node-path suite remains 39
initial passes plus one targeted corrected pass, not a complete final 40-case
rerun. Private report packages are outside GitHub: `worker-runtime-final.tar.gz`
and `mcp-sdk.tar.gz`; the runtime base was rebuilt from six source/test files.

## Private configuration

Values must be supplied by the operator on v100 and must not be committed:

```text
ZEUS_WORKER_CONFIG=<protected inline JSON Worker configuration>
ZEUS_WORKER_BUNDLE_PYTHON=<private bundle Python path>
ZEUS_CODEX_COMMAND=<private Codex command>
ZEUS_WORKER_EXECUTABLE_PATH=<private Worker executable path>
MLCC_SITE_CONFIG=<private v100 site config path>
MLCC_WORKSPACE_ROOT=<private managed workspace root>
```

The Worker connects outbound to `https://agent.mattok.cn`. Its active private
execution target identifies the approved `workerId`, `target`, `deployment`,
`providerNamespace` and pinned candidate revision. The MCP environment allowlist
contains only the two MLCC keys `MLCC_SITE_CONFIG` and
`MLCC_WORKSPACE_ROOT`. A v100-local site uses `ssh.transport="local"` to
control the existing Slurm installation.

Do not copy credentials, private host configuration, runtime binaries or the
full scientific environment into GitHub. Keep the existing `0.60.0` target and
durable session pins unchanged.

## Safe checks only

The following checks inspect the runtime and do not submit or query a job:

```bash
node --version
python --version
python -c 'import importlib.metadata as m; print(m.version("mcp"))'
npm run typecheck --workspace @zeus/worker
npm run test --workspace @zeus/worker
npm --silent run healthcheck --workspace @zeus/worker
```

Do not restart `npm start` or systemd merely to repeat validation. The completed
read-only acceptance did not run `sbatch`, `scontrol`, submit, query, collect or
scientific commands; it intentionally left the new task count at zero. This
control result is not authorization for a material calculation.

## Publication and validation state

The current 0.60.2 publication uses the existing `target_mlcc_v100` and
`worker_mlcc_v100_01`. The operator must retain the 0.60.1 configuration and
enabled deployment for rollback. The ordinary-user two-round read-only
acceptance is complete and passed; do not extend that result to material
calculation or scientific qualification.

### Historical 0.60.1 publication record

Apply `runtime-node-path.patch` to the matching host release, not the read-only
upstream reference tree. The private Worker package includes both scoped stdio
scripts used by that release:
`.zeus/mcp-servers/knowledge_graph.cjs` and
`.zeus/mcp-servers/research_workbench.cjs`. Missing a host-owned MCP can also
break restored-thread tool inventory even when the MLCC MCP itself starts.

The LF metadata fix was applied before publication. Under the immutable-store
rule, the same unpublished deployment ID advanced from revision 2 to final
revision 3. The former `0.60.0` catalog publication was cancelled while its
deployment remained enabled and historical pins stayed unchanged.

User confirmation has been received and `target_mlcc_v100` was created. The
server pairing credentials are active, `zeus.service` is active,
`mlcc-worker.service` is started and the database heartbeat is online. Five
repaired public calls completed, and the same thread/provider session continued
successfully across a Worker restart. At the time of this document:

- the new target exists;
- the paired server environment is active;
- the v100 Worker service is started;
- the candidate is published and visible/hireable;
- the public control round and second-turn continuation are verified; and
- no real submit/query/collect or scientific computation was executed.

Because only one same-name catalog record may be published, an old conversation
must start a new conversation to select `0.60.1`; do not claim that an old
conversation continued on the new revision. A real computation requires
separate authorization.

### Historical 0.60.1 evidence

The sanitized control evidence is retained at
`workspace/reports/public-mlcc-eight-skill-20261029/` and
`workspace/reports/public-mlcc-second-turn-20261029/`. The candidate records
13 MCP tools, 8 top-level Skills, 7 nested routes and 114 CLI routes; the public
catalog returned all 15 Skills, individual Skill filters passed in the v100
probe, four generic operation-contract reads, four scale-contract reads, eight
public `*-0601` tasks created and prepared, and six historical result reads
completed without a new Slurm submission. DFT489 is
`raw_charged_scf_unqualified`, MD45 is `executed_engineering_fixture`, and the
four continuum results are `not_checked`. The four generic scientific inputs
remain `deferred_not_input_ready`.

The initial continuum read used JSON-only copies and failed. Restoring the
original payload/schema/artifacts directories made all four reads succeed; the
original task/result records were unchanged and this did not reveal a source
portability bug. The initial public error was the old native
`model_supports_reasoning_summaries` override being rejected by Codex 0.146;
`codex-config-0146.patch` removes only that native setting and retains the
catalog capability.
