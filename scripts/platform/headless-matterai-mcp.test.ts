import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parseZeusMcpConfig } from '../../workspace/runtime/matterai/packages/mcp-adapter/src/index.ts'
import {
  expandMcpServerPlaceholders,
  expandWorkspacePlaceholder,
  assertProviderSessionEvents,
  injectHeadlessCodexArgs,
  rawMcpToolEvents,
  selectAuthorizedMcpServer,
} from './headless-matterai-mcp.ts'

const workspace = 'D:/project/mlcc/workspace'
const bundleRoot = 'D:/project/mlcc/workspace/.zeus/bundles/mlcc-agent/0.2.1'
const declaration = {
  name: 'mlcc',
  runtime: 'python' as const,
  entry: 'tools/mlcc_mcp.py',
  args: [
    '--site', 'zeus://workspace/current/configs/site.v100.json',
    '--workspace', 'zeus://workspace/current',
  ],
  allowedTools: ['mlcc_list_tasks', 'mlcc_prepare_calculation'],
}

test('headless host uses the MatterAI MCP parser and expands project placeholders', () => {
  const [server] = parseZeusMcpConfig({
    servers: {
      mlcc: {
        type: 'stdio',
        command: 'zeus://workspace/current/.venv/Scripts/python.exe',
        args: ['zeus://workspace/current/.zeus/bundles/mlcc-agent/0.2.1/tools/mlcc_mcp.py'],
        allowedTools: ['mlcc_list_tasks'],
      },
    },
  })
  assert.equal(expandWorkspacePlaceholder('zeus://workspace/current', workspace), workspace)
  assert.deepEqual(expandMcpServerPlaceholders(server!, workspace), {
    type: 'stdio',
    name: 'mlcc',
    command: join(workspace, '.venv', 'Scripts', 'python.exe'),
    args: [join(workspace, '.zeus', 'bundles', 'mlcc-agent', '0.2.1', 'tools', 'mlcc_mcp.py')],
    allowedTools: ['mlcc_list_tasks'],
  })
})

test('headless host validates project Python, installed Bundle entry, and site/workspace args', () => {
  const server = parseZeusMcpConfig({
    servers: {
      mlcc: {
        type: 'stdio',
        command: 'zeus://workspace/current/.venv/Scripts/python.exe',
        args: [
          'zeus://workspace/current/.zeus/bundles/mlcc-agent/0.2.1/tools/mlcc_mcp.py',
          '--site',
          'zeus://workspace/current/configs/site.v100.json',
          '--workspace',
          'zeus://workspace/current',
        ],
        allowedTools: ['mlcc_list_tasks'],
      },
    },
  })
  const selected = selectAuthorizedMcpServer(server, declaration, bundleRoot, workspace)
  assert.equal(selected.command, resolve(workspace, '.venv', 'Scripts', 'python.exe'))
  assert.equal(selected.args[0], resolve(bundleRoot, declaration.entry))
  assert.throws(
    () => selectAuthorizedMcpServer(
      server.map((entry) => ({ ...entry, args: [...entry.args.slice(0, -1), 'wrong-workspace'] })),
      declaration,
      bundleRoot,
      workspace,
    ),
    /arguments do not match/,
  )
})

test('headless host rejects extra configured servers and unauthorized acceptance tools', () => {
  const server = parseZeusMcpConfig({
    servers: {
      mlcc: {
        type: 'stdio',
        command: 'zeus://workspace/current/.venv/Scripts/python.exe',
        args: ['zeus://workspace/current/.zeus/bundles/mlcc-agent/0.2.1/tools/mlcc_mcp.py'],
        allowedTools: ['mlcc_list_tasks'],
      },
      other: { type: 'stdio', command: 'python', args: [], allowedTools: [] },
    },
  })
  assert.throws(
    () => selectAuthorizedMcpServer(server, declaration, bundleRoot, workspace),
    /exactly one configured MCP server/,
  )
  assert.throws(
    () => selectAuthorizedMcpServer(
      [
        {
          type: 'stdio',
          name: 'mlcc',
          command: 'zeus://workspace/current/.venv/Scripts/python.exe',
          args: [
            'zeus://workspace/current/.zeus/bundles/mlcc-agent/0.2.1/tools/mlcc_mcp.py',
            '--site',
            'zeus://workspace/current/configs/site.v100.json',
            '--workspace',
            'zeus://workspace/current',
          ],
          allowedTools: ['mlcc_prepare_calculation'],
        },
      ],
      declaration,
      bundleRoot,
      workspace,
    ),
    /does not authorize mlcc_list_tasks/,
  )
})

test('headless host injects only Codex config isolation and the authorized MCP approval mode', () => {
  const args = injectHeadlessCodexArgs([
    'exec',
    '--json',
    '--sandbox', 'read-only',
    '-c', 'approval_policy=never',
    '-c', 'mcp_servers.mlcc.enabled_tools=["mlcc_list_tasks"]',
    'acceptance prompt',
  ])
  assert.deepEqual(args.slice(0, 3), ['exec', '--ignore-user-config', '--json'])
  assert.equal(args.includes('mcp_servers.mlcc.default_tools_approval_mode="approve"'), true)
  assert.equal(args.at(-1), 'acceptance prompt')
})

test('replays the saved 0.163 provider JSONL and validates the real MCP result', () => {
  const reportPath = fileURLToPath(new URL('../../workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v003.json', import.meta.url))
  const report = JSON.parse(readFileSync(reportPath, 'utf8')) as {
    runtime: { invocation: { stdoutJsonl: string[] } }
  }
  const stdoutJsonl = report.runtime.invocation.stdoutJsonl
  const mcpEvents = rawMcpToolEvents(stdoutJsonl)
  assert.equal(mcpEvents.length, 2)
  assert.deepEqual(
    mcpEvents.map(({ phase, server, tool, status }) => ({ phase, server, tool, status })),
    [
      { phase: 'item.started', server: 'mlcc', tool: 'mlcc_list_tasks', status: 'in_progress' },
      { phase: 'item.completed', server: 'mlcc', tool: 'mlcc_list_tasks', status: 'completed' },
    ],
  )
  const completed = mcpEvents[1]!
  assert.equal(completed.error, null)
  assert.equal(completed.result?.error ?? null, null)
  assert.notEqual(completed.result?.isError, true)
  const taskText = completed.result?.content.find((content) => content.type === 'text')?.text
  assert.equal(JSON.parse(taskText!).tasks.length, 23)
  assert.doesNotThrow(() => assertProviderSessionEvents([
    { type: 'run.started', runId: 'replay', threadId: 'replay-thread', at: '2026-10-21T00:00:00.000Z' },
    {
      type: 'runtime.provider-session',
      runId: 'replay',
      provider: 'codex',
      providerSessionId: '01a15c9f-37ba-7b60-9e2e-eeb248f810d0',
      at: '2026-10-21T00:00:00.000Z',
    },
    { type: 'run.completed', runId: 'replay', summary: 'replayed', at: '2026-10-21T00:00:00.000Z' },
  ], stdoutJsonl, 0))
})

test('headless host accepts a transient runtime failure when the final turn and runtime complete', () => {
  const stdoutJsonl = [
    JSON.stringify({ type: 'item.started', item: { id: 'call', type: 'mcp_tool_call', server: 'mlcc', tool: 'mlcc_list_tasks', status: 'in_progress', error: null, result: null } }),
    JSON.stringify({ type: 'item.completed', item: { id: 'call', type: 'mcp_tool_call', server: 'mlcc', tool: 'mlcc_list_tasks', status: 'completed', error: null, result: { content: [{ type: 'text', text: JSON.stringify({ tasks: [] }) }], error: null, isError: false } } }),
    JSON.stringify({ type: 'turn.completed' }),
  ]
  assert.doesNotThrow(() => assertProviderSessionEvents([
    { type: 'run.started', runId: 'replay', threadId: 'replay-thread', at: '2026-10-22T00:00:00.000Z' },
    { type: 'runtime.provider-session', runId: 'replay', provider: 'codex', providerSessionId: 'session', at: '2026-10-22T00:00:00.000Z' },
    { type: 'run.failed', runId: 'replay', error: { category: 'runtime', message: 'transient' }, at: '2026-10-22T00:00:01.000Z' },
    { type: 'run.completed', runId: 'replay', summary: 'recovered', at: '2026-10-22T00:00:02.000Z' },
  ], stdoutJsonl, 0))
})

test('headless host rejects a terminal runtime failure after a completed turn', () => {
  const stdoutJsonl = [
    JSON.stringify({ type: 'item.started', item: { id: 'call', type: 'mcp_tool_call', server: 'mlcc', tool: 'mlcc_list_tasks', status: 'in_progress', error: null, result: null } }),
    JSON.stringify({ type: 'item.completed', item: { id: 'call', type: 'mcp_tool_call', server: 'mlcc', tool: 'mlcc_list_tasks', status: 'completed', error: null, result: { content: [{ type: 'text', text: JSON.stringify({ tasks: [] }) }], error: null, isError: false } } }),
    JSON.stringify({ type: 'turn.completed' }),
  ]
  assert.throws(() => assertProviderSessionEvents([
    { type: 'run.started', runId: 'replay', threadId: 'replay-thread', at: '2026-10-22T00:00:00.000Z' },
    { type: 'runtime.provider-session', runId: 'replay', provider: 'codex', providerSessionId: 'session', at: '2026-10-22T00:00:00.000Z' },
    { type: 'run.completed', runId: 'replay', summary: 'completed', at: '2026-10-22T00:00:01.000Z' },
    { type: 'run.failed', runId: 'replay', error: { category: 'runtime', message: 'terminal' }, at: '2026-10-22T00:00:02.000Z' },
  ], stdoutJsonl, 0), /final runtime state was run\.failed/)
})

test('headless host rejects a nonzero provider process after completed runtime events', () => {
  const stdoutJsonl = [
    JSON.stringify({ type: 'item.started', item: { id: 'call', type: 'mcp_tool_call', server: 'mlcc', tool: 'mlcc_list_tasks', status: 'in_progress', error: null, result: null } }),
    JSON.stringify({ type: 'item.completed', item: { id: 'call', type: 'mcp_tool_call', server: 'mlcc', tool: 'mlcc_list_tasks', status: 'completed', error: null, result: { content: [{ type: 'text', text: JSON.stringify({ tasks: [] }) }], error: null, isError: false } } }),
    JSON.stringify({ type: 'turn.completed' }),
  ]
  assert.throws(() => assertProviderSessionEvents([
    { type: 'run.started', runId: 'replay', threadId: 'replay-thread', at: '2026-10-22T00:00:00.000Z' },
    { type: 'runtime.provider-session', runId: 'replay', provider: 'codex', providerSessionId: 'session', at: '2026-10-22T00:00:00.000Z' },
    { type: 'run.completed', runId: 'replay', summary: 'completed', at: '2026-10-22T00:00:01.000Z' },
  ], stdoutJsonl, 1), /provider process exited with code 1/)
})
