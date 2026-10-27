import { readFile, readdir } from 'node:fs/promises'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

type ActivationEntry = {
  name: string
  version: string
  enabled: boolean
}

type McpRawServer = {
  type?: string
  allowedTools?: unknown
}

type McpConfig = {
  servers?: Record<string, McpRawServer>
}

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

function argumentValue(name: string): string | undefined {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

function resolveTarget(value: string | undefined, fallback: string): string {
  return resolve(value ? (isAbsolute(value) ? value : join(repositoryRoot, value)) : fallback)
}

async function inspectProject(label: string, projectRoot: string): Promise<void> {
  const zeusRoot = join(projectRoot, '.zeus')
  const activationPath = join(zeusRoot, 'bundles.json')
  const activation = JSON.parse(await readFile(activationPath, 'utf8')) as {
    bundles?: ActivationEntry[]
  }
  const bundleEntries = activation.bundles ?? []
  const bundleCatalog = await readdir(join(zeusRoot, 'bundles'))
  const mcpConfigPath = join(zeusRoot, 'mcp.json')

  console.log(`target=${label}`)
  console.log(`projectRoot=${projectRoot}`)
  console.log(`activationPath=${activationPath}`)
  console.log(`enabledBundles=${JSON.stringify(bundleEntries)}`)
  console.log(`bundleCatalog=${JSON.stringify(bundleCatalog)}`)

  try {
    const mcpConfig = JSON.parse(await readFile(mcpConfigPath, 'utf8')) as McpConfig
    const servers = Object.entries(mcpConfig.servers ?? {}).map(([name, server]) => ({
      name,
      type: server.type,
      allowedTools: Array.isArray(server.allowedTools) ? server.allowedTools : [],
    }))
    console.log(`mcpConfigPath=${mcpConfigPath}`)
    console.log(`mcpServers=${JSON.stringify(servers)}`)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
      throw error
    }
    console.log(`mcpConfigPath=${mcpConfigPath}`)
    console.log('mcpConfig=absent')
    console.log('mcpServers=[]')
  }

  console.log('mcpTrustStore=mcp-trust-v1.json (MatterAI desktop userDataRoot; outside project .zeus)')
  console.log('trustState=not-created-by-this-read-only-inspection')
}

const workspaceRoot = resolveTarget(argumentValue('--workspace'), join(repositoryRoot, 'workspace'))
const sandboxRoot = argumentValue('--sandbox')

async function main(): Promise<void> {
  await inspectProject('workspace', workspaceRoot)
  if (sandboxRoot) {
    await inspectProject('sandbox', resolveTarget(sandboxRoot, sandboxRoot))
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
