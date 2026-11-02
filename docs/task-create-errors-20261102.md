# Task creation input errors · 2026-11-02

0.60.3 fixes the public four-scale creation boundary. The observed failures omitted
request.task_id and later used platform_task_id plus the internal execution
schema. Ordinary ValueError exceptions were hidden by MCP 2.3.0 as unexpected
errors. The old protocol test checked isError but not the reason text.

The shared schemas/scale-task-request.schema.json now appears in the MCP
create tool's request property and scale descriptions as task_request_schema.
Its required fields are schema=mlcc.scale-task-request.v1, task_id and an explicit
resource_request; study_ref is optional. module_id, operation and scientific
input remain separate tool arguments. No aliases, guessed defaults or retries
are introduced.

Both CLI file input and MCP data input use the same validator before staging.
Invalid requests or scientific input create no task/input/request files.
Only anticipated ScaleInputError becomes MCP ToolError; unexpected filesystem,
site configuration and internal errors retain the SDK's private traceback path.
The existing task, prepare, transfer, submit, query and result protocols are
unchanged. A valid create returns defined with scheduler_job_id=null.

The focused software regression passed 21 tests through actual MCP stdio,
offline task control and public-operation routing. Windows test setup failures
(temp sandbox permissions, UTF-8 decoding, undrained stderr during multiple
negative calls) were retained and corrected in the protocol fixture. They are
not public server failures. No numerical solver, scheduler call or new material
calculation was run for these checks.

Publication and ordinary-user acceptance are recorded in SYSTEM_MANIFEST.json.
The candidate must not be described as published before that record is updated.
The preceding 0.60.2 resource library and ABACUS default remain unchanged.
The old deployment/version is retained for rollback, not concurrently active;
task 842 is not recreated, resubmitted, cancelled or modified by this upgrade.

## Public acceptance

The release is published as revision 5. The first ordinary-user call returned
`request: missing task_id` with the expected schema, and staged no files. A
subsequent full-input model turn streamed reasoning for 17m16s without issuing
a tool call; the operator stopped only that acceptance run. It remains cancelled
and is not counted as passed. No model or provider setting was changed.

A shorter instruction then created exactly one synthetic validation task using
the same supplied input. The following turn actually read the task list: both
turns completed in the same conversation/provider session. Across the full
acceptance there are two create calls (one expected error, one success), one
scale description and two task-list reads. No prepare/transfer/submit/query/
cancel/collect tool was called; the one task stays defined with job ID null.
This is input/control acceptance, not a new numerical or material result.

The host rejected simultaneous activation of two versions with the same Bundle
name before the Worker was restarted. The release therefore uses the existing
single-version activation rule and retains 0.60.2 for rollback. Old pins are
not migrated; a new conversation selects the fixed 0.60.3. No host code change
was introduced. Evidence: [task-create-repair-20261102.json](evidence/task-create-repair-20261102.json).
