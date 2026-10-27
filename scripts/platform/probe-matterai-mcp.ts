import { realpath, stat } from 'node:fs/promises'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

type McpServer = {
  type: 'stdio' | 'http' | 'sse'
  name: string
  command?: string
  args?: string[]
  url?: string
  allowedTools: string[]
}

type McpTool = {
  name: string
  description?: string
}

type PlatformModules = {
  loadZeusMcpServers: (
    configPath: string,
    workspaceRoot?: string,
    containment?: string,
  ) => Promise<McpServer[]>
  McpTrustStore: new (baseDir: string) => {
    find(workspaceRoot: string, serverName: string, fingerprint: string): Promise<unknown>
  }
  McpExecutionGate: new (options: { trustStore: unknown }) => {
    requireTrustedServer(input: {
      workspaceRoot: string
      configPath: string
      serverName: string
    }): Promise<McpServer>
  }
  createMcpSecuritySummary: (server: McpServer, workspaceRoot: string) => unknown
  fingerprintMcpSecuritySummary: (summary: unknown) => string
  loadListMcpTools: () => Promise<(
    server: McpServer,
    workspaceRoot: string,
    assertExecutionAllowed: () => Promise<McpServer>,
  ) => Promise<{ tools: McpTool[] }>>
}

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

function argumentValue(name: string): string | undefined {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

function resolveTarget(value: string | undefined, fallback: string): string {
  return resolve(value ? (isAbsolute(value) ? value : join(repositoryRoot, value)) : fallback)
}

function printUsage(): void {
  console.log(`Usage: probe-matterai-mcp.ts [options]

Options:
  --workspace <path>       MLCC workspace; defaults to ./workspace
  --matterai-root <path>   MatterAI source root used for platform imports
  --user-data-root <path>  Electron userData root containing mcp-trust-v1.json
  --server <name>          Server name when the config contains more than one server
  --help                   Show this help

The probe never writes .zeus/mcp.json or the trust store. It calls the MatterAI
loader, trust gate, and listMcpTools exports only after a configured server exists.
`)
}

async function pathExists(pathname: string): Promise<boolean> {
  try {
    await stat(pathname)
    return true
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return false
    }
    throw error
  }
}

async function loadPlatformModules(platformRoot: string): Promise<PlatformModules> {
  const runtimeModule = await import(pathToFileURL(
    join(platformRoot, 'apps/desktop/electron/runtime/runtime-container.ts'),
  ).href) as { loadZeusMcpServers: PlatformModules['loadZeusMcpServers'] }
  const trustStoreModule = await import(pathToFileURL(
    join(platformRoot, 'apps/desktop/electron/runtime/mcp-trust-store.ts'),
  ).href) as { McpTrustStore: PlatformModules['McpTrustStore'] }
  const gateModule = await import(pathToFileURL(
    join(platformRoot, 'apps/desktop/electron/ipc/mcp-execution-gate.ts'),
  ).href) as { McpExecutionGate: PlatformModules['McpExecutionGate'] }
  const trustPolicyModule = await import(pathToFileURL(
    join(platformRoot, 'apps/desktop/electron/runtime/mcp-trust-policy.ts'),
  ).href) as {
    createMcpSecuritySummary: PlatformModules['createMcpSecuritySummary']
    fingerprintMcpSecuritySummary: PlatformModules['fingerprintMcpSecuritySummary']
  }
  return {
    loadZeusMcpServers: runtimeModule.loadZeusMcpServers,
    McpTrustStore: trustStoreModule.McpTrustStore,
    McpExecutionGate: gateModule.McpExecutionGate,
    createMcpSecuritySummary: trustPolicyModule.createMcpSecuritySummary,
    fingerprintMcpSecuritySummary: trustPolicyModule.fingerprintMcpSecuritySummary,
    loadListMcpTools: async () => {
      const agentModule = await import(pathToFileURL(
        join(platformRoot, 'apps/desktop/electron/ipc/agent-ipc.ts'),
      ).href) as {
        listMcpTools: (
          server: McpServer,
          workspaceRoot: string,
          assertExecutionAllowed: () => Promise<McpServer>,
        ) => Promise<{ tools: McpTool[] }>
      }
      return agentModule.listMcpTools
    },
  }
}

function printConfiguredServers(servers: McpServer[]): void {
  console.log(`configuredServers=${JSON.stringify(servers.map((server) => ({
    name: server.name,
    type: server.type,
    allowedTools: server.allowedTools,
  })))}`)
}

async function main(): Promise<void> {
  if (process.argv.includes('--help')) {
    printUsage()
    return
  }

  const workspaceRoot = await realpath(resolveTarget(argumentValue('--workspace'), join(repositoryRoot, 'workspace')))
  const configPath = join(workspaceRoot, '.zeus', 'mcp.json')
  console.log(`workspaceRoot=${workspaceRoot}`)
  console.log(`mcpConfigPath=${configPath}`)

  if (!await pathExists(configPath)) {
    console.log('mcpConfig=absent')
    console.log('status=no-configured-server')
    return
  }

  const platformRoot = resolveTarget(
    argumentValue('--matterai-root'),
    join(repositoryRoot, 'MatterAI-main', 'MatterAI-main'),
  )
  const platform = await loadPlatformModules(platformRoot)
  const configuredServers = await platform.loadZeusMcpServers(configPath, workspaceRoot, workspaceRoot)
  printConfiguredServers(configuredServers)

  if (configuredServers.length === 0) {
    console.log('status=no-configured-server')
    return
  }

  const userDataRootValue = argumentValue('--user-data-root')
  if (!userDataRootValue) {
    console.error('status=mcp_trust_store_root_required')
    console.error('formalReviewEntry=renderer zeus.mcp.review -> IPC mcp:review -> McpExecutionGate.reviewWithNativeDialog')
    console.error('probeAction=not_started; provide the actual Electron userDataRoot after platform review')
    process.exitCode = 3
    return
  }

  const userDataRoot = resolveTarget(userDataRootValue, userDataRootValue)
  const trustStore = new platform.McpTrustStore(userDataRoot)
  const requestedServerName = argumentValue('--server')
  const serverName = requestedServerName ?? (
    configuredServers.length === 1 ? configuredServers[0]!.name : undefined
  )
  if (!serverName) {
    throw new Error('mcp_server_name_required_for_multiple_servers')
  }

  const server = configuredServers.find((candidate) => candidate.name === serverName)
  if (!server) {
    throw new Error(`mcp_server_not_found: ${serverName}`)
  }
  const summary = platform.createMcpSecuritySummary(server, workspaceRoot)
  const fingerprint = platform.fingerprintMcpSecuritySummary(summary)
  const trustRecord = server.allowedTools.length > 0
    ? await trustStore.find(workspaceRoot, serverName, fingerprint)
    : null
  console.log(`trustReviews=${JSON.stringify([{
    server: serverName,
    trustState: trustRecord ? 'trusted' : 'review-required',
  }])}`)

  if (!trustRecord) {
    console.error('status=mcp_review_required')
    console.error('formalReviewEntry=renderer zeus.mcp.review -> IPC mcp:review -> McpExecutionGate.reviewWithNativeDialog')
    console.error('probeAction=not_started; no child process was spawned and no trust record was written')
    process.exitCode = 3
    return
  }

  const gate = new platform.McpExecutionGate({ trustStore })
  const trustedServer = await gate.requireTrustedServer({
    workspaceRoot,
    configPath,
    serverName,
  })
  const listMcpTools = await platform.loadListMcpTools()
  const listed = await listMcpTools(
    trustedServer,
    workspaceRoot,
    () => gate.requireTrustedServer({ workspaceRoot, configPath, serverName }),
  )
  console.log(`status=connected`)
  console.log(`server=${serverName}`)
  console.log(`toolsList=${JSON.stringify(listed.tools)}`)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
