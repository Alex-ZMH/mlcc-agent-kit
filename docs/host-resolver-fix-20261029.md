# Host workspace resolver note

The `AgentWorkspaceResolverError` fix belongs to the private MatterAI host
runtime, not to this portable MLCC bundle. The host change repairs a legacy ACL
only on the server-derived final project directory; root, tenant, and parent
directory ACLs remain strict. This keeps the bundle independent of Windows
workspace internals.

The local host regression suite passed four tests on 2026-10-29, including the
legacy project-leaf repair and rejection of an unsafe root ACL. The source and
test are kept in the local host runtime under
`workspace/runtime/matterai/apps/server/src/agent/`; that private runtime tree
is excluded from this GitHub repository by design.

The public MLCC bundle therefore records the host prerequisite and its evidence
without copying or modifying the upstream host project.
