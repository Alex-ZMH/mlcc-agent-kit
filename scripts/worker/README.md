# v100 Worker operator boundary

This directory documents the candidate's user-level v100 Worker. It is an
operator guide, not a launcher. The current state is **published; public
control passed; no compute submitted**. The approved target exists,
`mlcc-worker.service` is started and its database heartbeat is online. Do not
submit a scientific calculation from this candidate without separate
authorization.

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

Do not restart `npm start` or systemd merely to repeat validation. Do not run
`sbatch`, `scontrol`, or any submit, query, collect or scientific command while
this candidate is in the validation round. The v100 control probe intentionally
left all new scheduler job IDs `null`.

## Publication and validation state

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

## Evidence

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
