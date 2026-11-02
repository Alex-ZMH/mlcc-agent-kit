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
The existing deployment/version remains available for old pinned conversations;
task 842 is not recreated, resubmitted, cancelled or modified by this upgrade.
