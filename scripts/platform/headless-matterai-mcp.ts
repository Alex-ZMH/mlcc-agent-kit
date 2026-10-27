import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { spawn as nodeSpawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  createWorkspaceContainmentGuard,
  listZeusAgents,
  listZeusSkills,
  loadBundleRuntimeRegistry,
  resolveAgentRunProfile,
  startAgentRun,
  type AgentRuntimeEvent,
} from '../../workspace/runtime/matterai/packages/core-engine/src/index.ts'
import { parseZeusMcpConfig } from '../../workspace/runtime/matterai/packages/mcp-adapter/src/index.ts'
import { CodexCliRuntime, type CodexCliSpawn } from '../../workspace/runtime/matterai/packages/codex-runtime/src/index.ts'
import type { McpServerDefinition } from '../../workspace/runtime/matterai/packages/shared-types/src/index.ts'

type StdioMcpServer = Extract<McpServerDefinition, { type: 'stdio' }>
type Report = Record<string, unknown>

const DEFAULT_WORKSPACE = resolve(fileURLToPath(new URL('../../workspace/', import.meta.url)))
const DEFAULT_REPORT = 'workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v002.json'
const EXPECTED_SERVER = 'mlcc'
const EXPECTED_TOOL = 'mlcc_list_tasks'
const WORKSPACE_PLACEHOLDER = 'zeus://workspace/current'

function argumentValue(name: string): string | undefined {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

export function expandWorkspacePlaceholder(value: string, workspaceRoot: string): string {
  if (value === WORKSPACE_PLACEHOLDER) return workspaceRoot
  if (value.startsWith(`${WORKSPACE_PLACEHOLDER}/`)) {
    return join(workspaceRoot, value.slice(WORKSPACE_PLACEHOLDER.length + 1))
  }
  return value
}

export function expandMcpServerPlaceholders(
  server: StdioMcpServer,
  workspaceRoot: string,
): StdioMcpServer {
  return {
    ...server,
    command: expandWorkspacePlaceholder(server.command, workspaceRoot),
    args: server.args.map((arg) => expandWorkspacePlaceholder(arg, workspaceRoot)),
  }
}

function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

function expectedBundleMcpArgs(
  declaration: { args: string[] },
  workspaceRoot: string,
): string[] {
  return declaration.args.map((arg) => expandWorkspacePlaceholder(arg, workspaceRoot))
}

/** Validate the project configuration against the selected installed Bundle. */
export function selectAuthorizedMcpServer(
  configured: readonly McpServerDefinition[],
  declaration: {
    name: string
    runtime: 'python' | 'node'
    entry: string
    args: string[]
    allowedTools: string[]
  },
  bundleRoot: string,
  workspaceRoot: string,
): StdioMcpServer {
  if (configured.length !== 1) {
    throw new Error(`headless host requires exactly one configured MCP server: ${EXPECTED_SERVER}`)
  }
  const candidate = configured[0]
  if (candidate.type !== 'stdio' || candidate.name !== EXPECTED_SERVER) {
    throw new Error(`headless host requires the configured ${EXPECTED_SERVER} server to use stdio`)
  }
  if (declaration.name !== EXPECTED_SERVER || declaration.runtime !== 'python') {
    throw new Error(`Bundle declaration does not identify the ${EXPECTED_SERVER} Python server`)
  }
  const server = expandMcpServerPlaceholders(candidate, workspaceRoot)
  const projectPython = resolve(workspaceRoot, '.venv', 'Scripts', 'python.exe')
  if (resolve(server.command) !== projectPython) {
    throw new Error(`MCP command is not the project Python: ${server.command}`)
  }
  const expectedEntry = resolve(bundleRoot, declaration.entry)
  const expectedArgs = expectedBundleMcpArgs(declaration, workspaceRoot)
  if (server.args[0] !== expectedEntry) {
    throw new Error(`MCP entry does not match the installed Bundle: ${server.args[0]}`)
  }
  const expectedConfiguredArgs = [expectedEntry, ...expectedArgs]
  if (!sameStrings(server.args, expectedConfiguredArgs)) {
    throw new Error('MCP arguments do not match the installed Bundle declaration')
  }
  if (!declaration.allowedTools.includes(EXPECTED_TOOL)) {
    throw new Error(`Bundle does not authorize ${EXPECTED_TOOL}`)
  }
  if (!server.allowedTools.includes(EXPECTED_TOOL)) {
    throw new Error(`Project MCP configuration does not authorize ${EXPECTED_TOOL}`)
  }
  if (!isAbsolute(server.command) || !isAbsolute(server.args[0])) {
    throw new Error('Resolved MCP command and entry must be absolute paths')
  }
  return server
}

type CapturedInvocation = {
  command: string
  args: string[]
  cwd: string
  stdoutJsonl: string[]
  exitCode: number | null
}

type RawMcpResult = {
  content: Array<{ type: string; text: string }>
  structured_content: Record<string, unknown>
  error: unknown
  isError?: boolean
}

type RawMcpToolCall = {
  type: 'mcp_tool_call'
  id: string
  server: string
  tool: string
  status: string
  error: unknown
  result: RawMcpResult | null
}

type RawCodexRecord = {
  type: string
  item?: RawMcpToolCall
}

export type HeadlessRawMcpToolEvent = {
  phase: string
  id: string
  server: string
  tool: string
  name: string
  status: string
  error: unknown
  result: RawMcpResult | null
}

export function injectHeadlessCodexArgs(args: string[]): string[] {
  const prompt = args.at(-1)
  if (prompt === undefined) throw new Error('Codex runtime did not provide a prompt argument')
  const base = args.slice(0, -1)
  if (base[0] !== 'exec') throw new Error('Headless host requires a fresh Codex exec run')
  if (!base.includes('--sandbox') || base[base.indexOf('--sandbox') + 1] !== 'read-only') {
    throw new Error('Headless host requires the Codex read-only sandbox')
  }
  if (!base.includes('approval_policy=never')) {
    throw new Error('Headless host requires approval_policy=never')
  }
  if (!base.includes('mcp_servers.mlcc.enabled_tools=["mlcc_list_tasks"]')) {
    throw new Error('Headless host requires the authorized mlcc_list_tasks tool allowlist')
  }
  return [
    'exec',
    '--ignore-user-config',
    ...base.slice(1),
    '-c',
    'mcp_servers.mlcc.default_tools_approval_mode="approve"',
    prompt,
  ]
}

function createCapturedSpawn(capture: { invocation?: CapturedInvocation }, workspaceRoot: string): CodexCliSpawn {
  return (command, args, options) => {
    const injectedArgs = injectHeadlessCodexArgs(args)
    const invocation: CapturedInvocation = {
      command,
      args: injectedArgs,
      cwd: options.cwd ?? workspaceRoot,
      stdoutJsonl: [],
      exitCode: null,
    }
    capture.invocation = invocation
    const child = nodeSpawn(command, injectedArgs, {
      cwd: invocation.cwd,
      env: options.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    }) as unknown as ChildProcessWithoutNullStreams
    let buffer = ''
    child.stdout.on('data', (chunk) => {
      buffer += String(chunk)
      while (true) {
        const end = buffer.indexOf('\n')
        if (end < 0) break
        const line = buffer.slice(0, end).trim()
        buffer = buffer.slice(end + 1)
        if (line) invocation.stdoutJsonl.push(line)
      }
    })
    child.stdout.on('end', () => {
      const line = buffer.trim()
      if (line) invocation.stdoutJsonl.push(line)
      buffer = ''
    })
    child.once('close', (code) => { invocation.exitCode = code })
    return child
  }
}

function safeInvocation(invocation: CapturedInvocation | undefined): Report | null {
  if (!invocation) return null
  return {
    command: invocation.command,
    args: invocation.args,
    cwd: invocation.cwd,
    stdoutJsonl: invocation.stdoutJsonl,
    childExitCode: invocation.exitCode,
  }
}

function eventSummary(events: readonly AgentRuntimeEvent[]): Report[] {
  return events.map((event) => {
    switch (event.type) {
      case 'runtime.provider-session':
        return { type: event.type, provider: event.provider, providerSessionId: event.providerSessionId, at: event.at }
      case 'run.started':
      case 'run.phase':
      case 'run.completed':
      case 'run.failed':
        return { ...event, ...(event.type === 'run.failed' ? { error: event.error } : {}) }
      case 'tool.requested':
        return { type: event.type, call: event.call, at: event.at }
      case 'tool.output':
        return { type: event.type, toolCallId: event.toolCallId, outcome: event.outcome, text: event.text, at: event.at }
      case 'assistant.delta':
        return { type: event.type, text: event.text, at: event.at }
      case 'run.usage':
        return { type: event.type, usage: event.usage, at: event.at }
      default:
        return { type: event.type, at: event.at }
    }
  })
}

export function rawMcpToolEvents(stdoutJsonl: readonly string[]): HeadlessRawMcpToolEvent[] {
  const mcpEvents: HeadlessRawMcpToolEvent[] = []
  for (const line of stdoutJsonl) {
    const record = JSON.parse(line) as RawCodexRecord
    if (record.item?.type !== 'mcp_tool_call') continue
    const item = record.item
    mcpEvents.push({
      phase: record.type,
      id: item.id,
      server: item.server,
      tool: item.tool,
      name: `mcp__${item.server}__${item.tool}`,
      status: item.status,
      error: item.error,
      result: item.result,
    })
  }
  return mcpEvents
}

function rawCodexTurnEvents(stdoutJsonl: readonly string[]): string[] {
  const turnEvents: string[] = []
  for (const line of stdoutJsonl) {
    const record = JSON.parse(line) as { type?: unknown }
    if (typeof record.type === 'string' && record.type.startsWith('turn.')) turnEvents.push(record.type)
  }
  return turnEvents
}

export function assertProviderSessionEvents(
  events: readonly AgentRuntimeEvent[],
  stdoutJsonl: readonly string[],
  childExitCode: number | null,
): void {
  const mcpEvents = rawMcpToolEvents(stdoutJsonl)
  const names = mcpEvents.map((event) => event.name)
  if (names.length !== 2 || names.some((name) => name !== `mcp__${EXPECTED_SERVER}__${EXPECTED_TOOL}`)) {
    throw new Error(`provider session exposed unexpected MCP tool events: ${JSON.stringify(names)}`)
  }
  const started = mcpEvents.filter((event) => event.phase === 'item.started')
  const completed = mcpEvents.filter((event) => event.phase === 'item.completed')
  if (started.length !== 1 || completed.length !== 1) {
    throw new Error('provider session did not produce one started and one completed mlcc_list_tasks event')
  }
  const completedEvent = completed[0]
  const completedResult = completedEvent.result
  if (
    completedEvent.status !== 'completed'
    || completedEvent.error !== null
    || completedResult === null
    || (completedResult.error !== undefined && completedResult.error !== null)
    || completedResult.isError === true
  ) {
    throw new Error('provider session did not produce one successful mlcc_list_tasks result')
  }
  const taskContent = completedResult.content.find((content) => content.type === 'text')
  if (!taskContent) throw new Error('mlcc_list_tasks result did not contain text content')
  const taskPayload = JSON.parse(taskContent.text) as { tasks?: unknown }
  if (!Array.isArray(taskPayload.tasks)) throw new Error('mlcc_list_tasks result did not contain a task list')
  if (!events.some((event) => event.type === 'run.started')) throw new Error('provider session did not emit run.started')
  const runtimeTerminalEvents = events.filter(
    (event) => event.type === 'run.completed' || event.type === 'run.failed',
  )
  const finalRuntimeEvent = runtimeTerminalEvents.at(-1)
  if (!finalRuntimeEvent) throw new Error('provider session did not emit a terminal runtime event')
  if (finalRuntimeEvent.type !== 'run.completed') {
    throw new Error(`provider session final runtime state was ${finalRuntimeEvent.type}`)
  }
  if (childExitCode !== 0) throw new Error(`provider process exited with code ${String(childExitCode)}`)
  const turnEvents = rawCodexTurnEvents(stdoutJsonl)
  if (turnEvents.at(-1) !== 'turn.completed') {
    throw new Error(`provider final turn state was ${turnEvents.at(-1) ?? 'missing'}`)
  }
  if (!events.some((event) => event.type === 'runtime.provider-session')) throw new Error('provider session did not emit provider session identity')
}

export async function runHeadlessMcpSession(options: {
  workspaceRoot: string
  reportPath: string
}): Promise<Report> {
  const workspaceRoot = resolve(options.workspaceRoot)
  const zeusRoot = join(workspaceRoot, '.zeus')
  const activationConfigPath = join(zeusRoot, 'bundles.json')
  const catalogPath = join(zeusRoot, 'bundles')
  const mcpConfigPath = join(zeusRoot, 'mcp.json')
  const workspaceGuard = createWorkspaceContainmentGuard(workspaceRoot)
  const [projectSkills, projectAgents] = await Promise.all([
    listZeusSkills(join(zeusRoot, 'skills'), workspaceGuard),
    listZeusAgents(join(zeusRoot, 'agents'), workspaceGuard),
  ])
  const registry = await loadBundleRuntimeRegistry({
    catalogPath,
    catalogAuthority: 'workspace',
    workspaceGuard,
    activationConfigPath,
    existingAgents: projectAgents,
    existingSkills: projectSkills,
  })
  const bundle = registry.bundles.find((candidate) => candidate.manifest.name === 'mlcc-agent')
  if (!bundle) throw new Error('Activated mlcc-agent Bundle is missing')
  const agent = [...projectAgents, ...registry.agents].find((candidate) => candidate.name === 'mlcc')
  if (!agent || !agent.enabled) throw new Error('Bundle Agent mlcc is not enabled')
  const skills = [...projectSkills, ...registry.skills]
  const agentProfile = resolveAgentRunProfile(agent, skills)
  const mcpConfig = JSON.parse(await readFile(mcpConfigPath, 'utf8')) as unknown
  const configured = parseZeusMcpConfig(mcpConfig)
  const declaration = bundle.mcpServers.find((server) => server.name === EXPECTED_SERVER)
  if (!declaration) throw new Error(`Bundle does not declare MCP server ${EXPECTED_SERVER}`)
  const configuredServer = selectAuthorizedMcpServer(configured, declaration, bundle.rootPath, workspaceRoot)
  const capture: { invocation?: CapturedInvocation } = {}
  const runtime = new CodexCliRuntime({ spawn: createCapturedSpawn(capture, workspaceRoot) })
  const runId = `headless-${Date.now()}`
  const input = {
    runId,
    threadId: `${runId}-thread`,
    workspacePath: workspaceRoot,
    message: [
      'Perform one non-destructive MatterAI MCP acceptance check.',
      'Call mlcc_list_tasks exactly once through the configured mlcc MCP server and summarize the returned task count and statuses.',
      'Do not call any other tool. Do not prepare, transfer, submit, query, cancel, or collect a calculation. Do not run shell commands and do not modify files.',
    ].join(' '),
    runtimeId: runtime.id,
    agentName: agent.name,
    agentProfile,
    runtimeSettings: {
      sandbox: 'read-only' as const,
      approvalPolicy: 'never' as const,
      mcpServers: [{
        name: configuredServer.name,
        command: configuredServer.command,
        args: configuredServer.args,
        allowedTools: [EXPECTED_TOOL],
      }],
    },
  }
  const events: AgentRuntimeEvent[] = []
  for await (const event of startAgentRun({ runtime, input })) events.push(event)

  const report: Report = {
    status: 'passed',
    scope: 'bundle_registry_and_codex_provider_session',
    provider_session: true,
    host: 'matterai-headless',
    workspaceRoot,
    bundle: {
      name: bundle.manifest.name,
      version: bundle.manifest.version,
      agent: agentProfile.name,
      declaredSkills: bundle.manifest.agent.skills,
    },
    mcp: {
      server: configuredServer.name,
      configuredCommand: configuredServer.command,
      configuredArgs: configuredServer.args,
      bundleEntry: declaration.entry,
      declaredTools: declaration.allowedTools,
      exposedTools: [EXPECTED_TOOL],
    },
    runtime: {
      id: runtime.id,
      sandbox: 'read-only',
      approvalPolicy: 'never',
      invocation: safeInvocation(capture.invocation),
      childExitCode: capture.invocation?.exitCode ?? null,
    },
    events: eventSummary(events),
    provider_mcp_tool_events: rawMcpToolEvents(capture.invocation?.stdoutJsonl ?? []),
    invocation: EXPECTED_TOOL,
  }
  try {
    assertProviderSessionEvents(events, capture.invocation?.stdoutJsonl ?? [], capture.invocation?.exitCode ?? null)
  } catch (error) {
    report.status = 'failed'
    report.error = error instanceof Error ? error.message : String(error)
  }
  await mkdir(dirname(options.reportPath), { recursive: true })
  await writeFile(options.reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  if (report.status !== 'passed') throw new Error(String(report.error))
  return report
}

function resolveFromRoot(value: string | undefined, fallback: string, root: string): string {
  if (!value) return fallback
  return isAbsolute(value) ? resolve(value) : resolve(root, value)
}

async function main(): Promise<void> {
  if (process.argv.includes('--help')) {
    console.log('Usage: headless-matterai-mcp.ts [--workspace <path>] [--report <path>]')
    return
  }
  const repositoryRoot = resolve(fileURLToPath(new URL('../..', import.meta.url)))
  const workspaceRoot = resolveFromRoot(argumentValue('--workspace'), DEFAULT_WORKSPACE, repositoryRoot)
  const reportPath = resolveFromRoot(argumentValue('--report'), join(repositoryRoot, DEFAULT_REPORT), repositoryRoot)
  const report = await runHeadlessMcpSession({ workspaceRoot, reportPath })
  console.log(JSON.stringify({
    status: report.status,
    scope: report.scope,
    provider_session: report.provider_session,
    invocation: report.invocation,
    runtime: report.runtime,
    reportPath,
  }, null, 2))
}

const entryPath = process.argv[1] ? resolve(process.argv[1]) : ''
if (entryPath === resolve(fileURLToPath(import.meta.url))) {
  main().catch((error) => {
    console.error(error)
    process.exitCode = 1
  })
}
