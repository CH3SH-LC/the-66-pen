/**
 * T02 backend-connection suite — the REAL composition test for
 * `@miliastra/dsh-miliastra`'s business backend.
 *
 * What makes this real rather than a unit test: every case boots the pinned dsh
 * Loader (`boot()` from `@deepseek-ai/dsh-app-boot`) against an empty
 * `cordis.yml`, applies the package's **own shipped `cordis.patch.yml`** through
 * the real patch-dialect parser, and lets the Loader import the plugin entry and
 * settle the entry tree. Nothing calls `apply()` directly and nothing assembles
 * a context by hand.
 *
 * The `tools` service in every case except where noted is the **real**
 * `@deepseek-ai/dsh-tools` registry, mounted as an extra Loader row (with the
 * real `@deepseek-ai/dsh-system-prompt` it injects). Tool names, input schemas
 * and output contracts are therefore read back from the same registry a model
 * would call, not from a stand-in.
 *
 * The MCP server is a fixture: `fixtures/t02-fake-backend/backend/entity_server.py`,
 * a real MCP stdio server (pinned `mcp` Python SDK) driven by a per-case
 * scenario file. It is started by the plugin through the **production argv**
 * (`python -m backend.entity_server`, `cwd = backendRoot's parent`), because the
 * fixture is copied to `<projectRoot>/backend/entity_server.py` — there is no
 * test-only spawn path. The vendored client's connection, handshake, tool
 * discovery, naming, re-sync and reconnect are all the shipping implementation;
 * the fixture never asserts on its own output without the client's round trip.
 *
 * Every claim is cross-checked against a second source: the fixture's own ledger
 * (what the server actually served and was actually asked to call) and the
 * composition's evidence record. Where a claim cannot be observed — the plugin
 * cannot see *why* the vendored client left a structured-output schema
 * unconstrained — the gap is asserted as a gap instead of being papered over.
 *
 * LAYERS THIS SUITE DOES AND DOES NOT REACH
 *
 * - reached: `source` (the plugin source runs through Node's type stripping),
 *   `offline` (no network, no game), `loader` (the pinned Loader mounts the
 *   tree), `mcp` (real MCP stdio handshake and `tools/list` / `tools/call`).
 * - NOT reached: `cli`, `aiToolCall` (no model runs), `liveReadback`, `saveDiff`,
 *   `reopen`, `runtime`, `cleanup`. No game, editor, elevated helper, bridge,
 *   authoring journal or formal save is touched; the only process this suite
 *   starts is the fixture interpreter, and the launch spy in T02-A proves the
 *   composition starts nothing else.
 *
 * Run: `node scripts/run-tests.mjs tests/backend-connection.spec.ts`, or
 *      `node --test tests/backend-connection.spec.ts` from this package.
 *
 * @module @miliastra/dsh-miliastra/tests/backend-connection.spec
 */

import { after, before, test } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { boot, loadOverlayPatches } from '@deepseek-ai/dsh-app-boot'
import type { PatchOptions } from '@deepseek-ai/cordis-plugin-include'
import type { Context } from '@deepseek-ai/cordis'
import {
  BACKEND_ENV_ALLOWLIST,
  BACKEND_EVIDENCE_FILE,
  BACKEND_EVIDENCE_VERSION,
  BACKEND_RECONNECT_POLICY,
  REQUIRED_BUSINESS_TOOLS,
  WRITE_BUSINESS_TOOLS,
  backendEntryPath,
  backendModulePath,
  backendResources,
  buildBackendStdioConfig,
  expectedPublicToolName,
  toolNamePrefix,
} from '../src/backend.ts'

// ---- fixed paths -----------------------------------------------------------

/** This package's directory (`plugins/miliastra`). */
const packageDir = fileURLToPath(new URL('..', import.meta.url))

/** Repository root; the pinned checkout and the project venv live under it. */
const repoRoot = resolve(packageDir, '..', '..')

/** The source entry the Loader imports; never a build artifact. */
const sourceEntryPath = join(packageDir, 'src', 'index.ts')

/** The package's own bundle patch — the artifact under composition. */
const bundlePatchPath = join(packageDir, 'cordis.patch.yml')

/** The fake MCP server copied into every fixture project. */
const fixtureServerPath = join(packageDir, 'fixtures', 't02-fake-backend', 'backend', 'entity_server.py')

/** The project's MCP interpreter — the same one the shipped overlay uses. */
const PYTHON = join(repoRoot, '.runtime', 'mcp-venv', 'Scripts', 'python.exe')

/** The real registry row (an extra Loader row only this suite mounts). */
const TOOLS_URL = pathToFileURL(join(repoRoot, 'vendor', 'deepseek-harness', 'packages', 'core', 'tools', 'lib', 'index.js')).href

/** The real system-prompt service the registry injects. */
const SYSTEM_PROMPT_URL = pathToFileURL(join(repoRoot, 'vendor', 'deepseek-harness', 'packages', 'core', 'system-prompt', 'lib', 'index.js')).href

/** The real business backend whose tool names the contract constant must match. */
const REAL_BACKEND_PATH = join(repoRoot, 'backend', 'entity_server.py')

/** Cordis `FiberState.ACTIVE`; the const enum has no runtime object. */
const FIBER_ACTIVE = 2

/** Namespace every fixture project composes under. */
const SERVER_NAME = 'mwfixture'

/** Every temp root this suite created; removed in `after()`. */
const tempRoots: string[] = []

/** Where a `T02_SAMPLE_DIR` run mirrors the live resource-handle samples. */
const SAMPLE_DIR = process.env.T02_SAMPLE_DIR ?? ''

// ---- canonical JSON comparison --------------------------------------------

/** Canonical JSON of a value: object keys sorted, so two encodings compare equal. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value !== null && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`
  }
  return JSON.stringify(value) ?? 'undefined'
}

// ---- fixture project -------------------------------------------------------

/** One fake MCP tool as the scenario declares it. */
interface ScenarioTool {
  name: string
  description?: string
  inputSchema?: Record<string, unknown>
  outputSchema?: Record<string, unknown> | null
}

/** The scenario file the fake server reads at start-up. */
interface Scenario {
  name: string
  nonce: string
  tools: ScenarioTool[]
  behaviors?: Record<string, string>
  responses?: Record<string, Record<string, unknown>>
  hangSeconds?: number
  startup?: string
  startupExitCode?: number
  dropExitCode?: number
}

/** One hermetic fixture project tree and the paths that point into it. */
interface FixtureProject {
  /** Temp root; every path below lives under it. */
  readonly root: string
  /** Project checkout stand-in the plugin is configured with. */
  readonly projectRoot: string
  /** Backend directory holding the fixture server. */
  readonly backendRoot: string
  /** Evidence directory inside the project root. */
  readonly evidenceRoot: string
  /** The fixture server's own ledger (what it served and was asked to call). */
  readonly ledgerPath: string
  /** The scenario the fixture server reads. */
  readonly scenarioPath: string
}

/**
 * Create a hermetic fixture project.
 *
 * The path is deliberately awkward for the ready case (CJK, spaces,
 * parentheses): the config contract promises verbatim pass-through of operator
 * paths into a spawn without a shell, and a path needing no quoting would not
 * test that.
 * @param label - short run label used in the directory name.
 * @param scenario - the scenario the fixture server will read.
 * @param options - `awkward: false` picks a plain ASCII path.
 * @returns the fixture project.
 */
function makeProject(label: string, scenario: Scenario, options: { awkward?: boolean } = {}): FixtureProject {
  const root = mkdtempSync(join(tmpdir(), `miliastra-t02-${label}-`))
  tempRoots.push(root)
  const projectRoot = options.awkward === false
    ? join(root, 'project')
    : join(root, '千星 项目 (t02 fixture)')
  const backendRoot = join(projectRoot, 'backend')
  const evidenceRoot = join(projectRoot, '.runtime', 'cordis-evidence')
  mkdirSync(backendRoot, { recursive: true })
  mkdirSync(join(projectRoot, '工具'), { recursive: true })
  if (scenario.startup !== 'missing-entry') {
    writeFileSync(join(backendRoot, 'entity_server.py'), readFileSync(fixtureServerPath))
    // The composition now hands its write gate the real ledger port, and that port
    // runs `python -m backend.ledger_port --root <projectRoot>/.runtime/business-ledger`
    // with this project as its cwd. A fixture project that cannot serve that module
    // makes every write refuse `LIFECYCLE_LEDGER_UNAVAILABLE` before the transport,
    // which is fail-closed but is not what these cases are about. The two modules are
    // the ledger's whole read surface and are copied from the checkout, not stubbed.
    for (const module of ['ledger_port.py', 'operation_state.py', '__init__.py']) {
      writeFileSync(join(backendRoot, module), readFileSync(join(repoRoot, 'backend', module)))
    }
  }
  const scenarioPath = join(backendRoot, 'scenario.json')
  writeFileSync(scenarioPath, `${JSON.stringify(scenario, null, 2)}\n`, 'utf8')
  return {
    root,
    projectRoot,
    backendRoot,
    evidenceRoot,
    ledgerPath: join(projectRoot, 'fake-server-ledger.jsonl'),
    scenarioPath,
  }
}

/**
 * The scenario every case starts from: all seven business tools, each with a
 * nonce in its description so a table read back from the registry can only
 * match if it came over the wire from *this* server instance.
 * @param nonce - per-run marker placed in every description.
 * @param overrides - scenario fields to replace.
 * @returns the scenario.
 */
function businessScenario(nonce: string, overrides: Partial<Scenario> = {}): Scenario {
  return {
    name: 'business',
    nonce,
    tools: REQUIRED_BUSINESS_TOOLS.map(name => ({
      name,
      description: `fixture ${name} [${nonce}]`,
      inputSchema: {
        type: 'object',
        properties: {
          levelHandle: { type: 'string' },
          requestId: { type: 'string' },
          entityIds: { type: 'array', items: { type: 'integer' } },
        },
      },
    })),
    ...overrides,
  }
}

// ---- ledger and evidence ---------------------------------------------------

/** One line of the fixture server's ledger. */
interface LedgerRecord {
  event: string
  pid?: number
  scenario?: string
  tool?: string
  behavior?: string
  arguments?: Record<string, unknown>
  served?: Array<{ name: string, description: string, inputSchema: unknown, outputSchema: unknown }>
  module?: string
  executable?: string
  argv?: string[]
  cwd?: string
  envKeys?: string[]
}

/** Read the fixture server's ledger (empty when it never started). */
function ledger(project: FixtureProject): LedgerRecord[] {
  if (!existsSync(project.ledgerPath)) return []
  return readFileSync(project.ledgerPath, 'utf8').split('\n').filter(Boolean)
    .map(line => JSON.parse(line) as LedgerRecord)
}

/** Ledger records of one event kind. */
function ledgerOf(project: FixtureProject, event: string): LedgerRecord[] {
  return ledger(project).filter(record => record.event === event)
}

/** Call records for one raw tool name. */
function callsFor(project: FixtureProject, rawName: string): LedgerRecord[] {
  return ledgerOf(project, 'tools/call').filter(record => record.tool === rawName)
}

/** One-line summary of what the fixture server observed, for failure messages. */
function ledgerSummary(project: FixtureProject): string {
  return ledger(project)
    .map(record => record.event === 'tools/call' ? `call:${record.tool}` : record.event)
    .join(' | ')
}

/** The composition's evidence records (empty when none was written). */
function evidence(project: FixtureProject): Array<Record<string, any>> {
  const path = join(project.evidenceRoot, BACKEND_EVIDENCE_FILE)
  if (!existsSync(path)) return []
  return readFileSync(path, 'utf8').split('\n').filter(Boolean).map(line => JSON.parse(line) as Record<string, any>)
}

/** Poll until `check` returns a value, or fail after `timeoutMs`. */
async function waitFor<T>(check: () => T | undefined, timeoutMs: number, label: string): Promise<T> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const value = check()
    if (value !== undefined) return value
    if (Date.now() >= deadline) assert.fail(`timed out after ${timeoutMs}ms waiting for ${label}`)
    await new Promise<void>((resolve) => { setTimeout(resolve, 25) })
  }
}

/** Whether a process is still alive (best effort; Windows-aware). */
function processAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

// ---- boot harness ----------------------------------------------------------

/** Registry snapshots taken on every `tools/change` notification. */
interface RegistryTimeline {
  readonly snapshots: string[][]
  stop(): void
}

/**
 * Observe the live registry's visible tool names on every change.
 *
 * Independent of the composition under test: it subscribes to the registry's
 * own change notification on the host context, so a case whose activation
 * rejects (and whose context is then disposed) can still be asked what the
 * registry held while it was alive.
 * @param ctx - the host context, after the registry row mounted.
 * @returns the recorded snapshots and a stop function.
 */
function watchRegistry(ctx: Context): RegistryTimeline {
  const snapshots: string[][] = []
  const record = (): void => {
    try {
      const tools = ctx.get('tools')
      snapshots.push((tools.schemas() as Array<{ name: string }>).map(schema => schema.name))
    } catch {
      snapshots.push([])
    }
  }
  const dispose = ctx.on('tools/change' as never, record as never)
  return {
    snapshots,
    stop: () => { (dispose as unknown as () => void)() },
  }
}

/** Result of one boot. */
interface Booted {
  /** The settled root context. */
  readonly ctx: Context
  /** The real registry. */
  readonly tools: any
  /** Names visible in the real registry right now. */
  readonly visible: () => string[]
  /** Timeline of registry snapshots. */
  readonly timeline: RegistryTimeline
}

/** Options for {@link bootComposition}. */
interface BootOptions {
  /** Resolved-config overrides. */
  overrides?: Record<string, unknown>
  /** Extra Loader rows (e.g. a squatter plugin). */
  extraRows?: NonNullable<PatchOptions['insert']>
  /** Mount the real `tools`/`system-prompt` rows (default true). */
  withRegistry?: boolean
  /** Leave the shipped row specifier in place (composes the built entry). */
  builtEntry?: boolean
}

/**
 * The config an operator override row would write for one fixture project.
 * @param project - fixture project.
 * @param overrides - fields to replace.
 * @returns the row config.
 */
function configFor(project: FixtureProject, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    projectRoot: project.projectRoot,
    backendRoot: '',
    pythonExecutable: PYTHON,
    evidenceRoot: project.evidenceRoot,
    serverName: SERVER_NAME,
    toolCallTimeoutMs: 60_000,
    backendModule: '',
    failOnStartupError: true,
    ...overrides,
  }
}

/**
 * Boot the package through the real Loader with the real registry.
 * @param project - fixture project.
 * @param options - config overrides and extra rows.
 * @returns the settled context, the registry, and the change timeline.
 */
async function bootComposition(project: FixtureProject, options: BootOptions = {}): Promise<Booted> {
  const rootConfig = join(project.root, 'cordis.yml')
  writeFileSync(rootConfig, '# miliastra T02 fixture root: an empty entry list\n[]\n')

  const bundle = loadOverlayPatches('miliastra-t02', bundlePatchPath)
  assert.ok(bundle.length > 0, 'the package must ship a non-empty cordis.patch.yml')
  // The row's module specifier points at the source entry: a behavioral case
  // must not be satisfiable by a stale `lib/`. The one case whose subject IS the
  // published artifact leaves the shipped specifier in place, so the Loader
  // resolves this package by name exactly as an installed profile does.
  if (options.builtEntry !== true) {
    for (const patch of bundle) {
      for (const row of patch.insert ?? []) {
        if (row.id === 'miliastra') row.name = sourceEntryPath
      }
    }
  }
  const registryRows: NonNullable<PatchOptions['insert']> = options.withRegistry === false ? [] : [
    { id: 't02-system-prompt', name: SYSTEM_PROMPT_URL },
    { id: 't02-tools', name: TOOLS_URL },
  ]
  const patches: PatchOptions[] = [
    { insert: registryRows },
    { insert: options.extraRows ?? [] },
    ...bundle,
    { id: 'miliastra', config: configFor(project, options.overrides ?? {}) },
  ]

  let timeline: RegistryTimeline | undefined
  const ctx = await boot('miliastra-t02', rootConfig, patches, (hostCtx: Context) => {
    timeline = watchRegistry(hostCtx)
  }, pathToFileURL(join(packageDir, 'package.json')).href)
  timeline ??= { snapshots: [], stop: () => {} }
  const tools = ctx.get('tools')
  return {
    ctx,
    tools,
    visible: () => (tools.schemas() as Array<{ name: string }>).map(schema => schema.name),
    timeline,
  }
}

/**
 * Assert that a boot rejected and return the error, disposing a context that
 * settled anyway so a failed expectation cannot leak a live tree.
 * @param pending - the boot promise under test.
 * @returns the rejection reason.
 */
async function bootRejection(pending: Promise<Booted>): Promise<Error> {
  const outcome = await pending.then(
    async (settled) => { settled.timeline.stop(); await settled.ctx.fiber.dispose(); return undefined },
    (error: unknown) => error,
  )
  assert.ok(outcome instanceof Error, 'expected the composition to reject, but it settled')
  return outcome as Error
}

/** Collect every error reachable through `cause` and `AggregateError.errors`. */
function errorChain(error: unknown): Error[] {
  const found: Error[] = []
  const queue: unknown[] = [error]
  while (queue.length > 0) {
    const current = queue.shift()
    if (!(current instanceof Error)) continue
    found.push(current)
    if (current instanceof AggregateError) queue.push(...current.errors)
    if (current.cause !== undefined) queue.push(current.cause)
  }
  return found
}

/** The messages of one error's whole chain, joined for substring assertions. */
function chainText(error: unknown): string {
  return errorChain(error).map(entry => entry.message).join('\n')
}

/** Return the single `miliastra` entry the Loader created. */
function miliastraEntry(ctx: Context): { fiber?: { state: number, ctx: Context } } {
  const entries = [...ctx.loader.entries()].filter(entry => entry.options.id === 'miliastra')
  assert.equal(entries.length, 1, 'exactly one miliastra entry must be mounted')
  return entries[0] as unknown as { fiber?: { state: number, ctx: Context } }
}

/** Dispatch one tool through the REAL registry pipeline. */
async function dispatchTool(
  booted: Booted,
  publicName: string,
  args: Record<string, unknown>,
  callId = `t02-${publicName}-${Math.random().toString(36).slice(2, 8)}`,
): Promise<any> {
  return await booted.tools.execute({
    callId,
    name: publicName,
    arguments: args,
    signal: new AbortController().signal,
  })
}

/** The resource handle of the composition on the miliastra entry. */
function handleOf(booted: Booted) {
  const entry = miliastraEntry(booted.ctx)
  assert.ok(entry.fiber !== undefined, 'the miliastra entry must have a fiber')
  const handle = backendResources(entry.fiber.ctx)
  assert.ok(handle !== undefined, 'the composition must publish a resource handle')
  return handle
}

/** Registry names inside this server's namespace. */
function ownedNames(booted: Booted): string[] {
  const prefix = toolNamePrefix(SERVER_NAME)
  return booted.visible().filter(name => name.startsWith(prefix)).sort()
}

// ---- child-process spy -----------------------------------------------------

const require = createRequire(import.meta.url)
const childProcess = require('node:child_process') as Record<string, unknown>

/** Launch entry points the spy wraps. */
const SPY_TARGETS = ['spawn', 'spawnSync', 'exec', 'execFile', 'execSync', 'execFileSync', 'fork'] as const

/** Install the launch spy (same shape as the T01 suite's, but asserted positively). */
function installLaunchSpy(): { stop: () => Array<{ target: string, args: unknown[] }> } {
  const calls: Array<{ target: string, args: unknown[] }> = []
  const originals = new Map<string, unknown>()
  for (const target of SPY_TARGETS) {
    const original = childProcess[target]
    if (typeof original !== 'function') continue
    originals.set(target, original)
    childProcess[target] = (...args: unknown[]): unknown => {
      calls.push({ target, args })
      return (original as (...inner: unknown[]) => unknown)(...args)
    }
  }
  assert.ok(originals.size > 0, 'the launch spy must wrap at least one child_process entry point')
  return {
    stop: () => {
      for (const [target, original] of originals) childProcess[target] = original
      return calls
    },
  }
}

// ---- suite setup -----------------------------------------------------------

before(() => {
  assert.ok(existsSync(PYTHON),
    `${PYTHON} is missing: this offline suite starts the fake MCP backend with the project's own MCP interpreter`)
  assert.ok(existsSync(fixtureServerPath), `${fixtureServerPath} is missing`)
})

after(() => {
  for (const root of tempRoots) rmSync(root, { recursive: true, force: true })
})

// ---- cases -----------------------------------------------------------------

test('T02-A composes the vendored client through the real Loader and publishes the served table', async () => {
  const nonce = `nonce-${Date.now().toString(36)}`
  const project = makeProject('ready', businessScenario(nonce))
  const spy = installLaunchSpy()
  let booted: Booted
  try {
    booted = await bootComposition(project)
  } finally {
    const calls = spy.stop()
    // The composition starts exactly one process — the configured interpreter —
    // and never the game, the editor, the helper, or the bridge.
    assert.equal(calls.length, 1, `the composition must launch exactly one process, saw ${JSON.stringify(calls.map(call => call.target))}`)
    assert.equal(calls[0]!.target, 'spawn')
    assert.equal(calls[0]!.args[0], PYTHON, 'the spawned command must be the resolved interpreter')
    assert.deepEqual(calls[0]!.args[1], ['-m', 'backend.entity_server'], 'arguments must be argv entries, not a shell string')
  }
  try {
    booted.timeline.stop()
    assert.equal(miliastraEntry(booted.ctx).fiber?.state, FIBER_ACTIVE, 'the miliastra entry must settle ACTIVE')

    // 1. The real registry holds this server's tools under the namespace rule.
    const expected = REQUIRED_BUSINESS_TOOLS.map(name => expectedPublicToolName(SERVER_NAME, name))
    assert.deepEqual(ownedNames(booted), [...expected].sort(),
      'the registry must expose exactly the business tools, under mcp__<serverName>__<rawName>')

    // 2. The schemas came over the wire: compare the registry's projection with
    //    what the fixture server recorded serving (three-way against the
    //    plugin's own evidence below). The nonce in each description can only
    //    match if this server instance's tools/list produced it.
    const served = ledgerOf(project, 'tools/list')
    assert.equal(served.length >= 1, true, 'the fixture server must have been asked for its tool list')
    const servedByName = new Map((served.at(-1)!.served ?? []).map(row => [row.name, row]))
    const registrySchemas = new Map((booted.tools.schemas() as Array<{ name: string, description: string, parameters: unknown }>)
      .map(schema => [schema.name, schema]))
    for (const rawName of REQUIRED_BUSINESS_TOOLS) {
      const publicName = expectedPublicToolName(SERVER_NAME, rawName)
      const published = registrySchemas.get(publicName)
      const asServed = servedByName.get(rawName)
      assert.ok(published !== undefined, `${publicName} must be in the registry`)
      assert.ok(asServed !== undefined, `${rawName} must be in the server's served list`)
      assert.equal(published!.description, asServed!.description, `${publicName} description must come from the wire`)
      assert.ok(published!.description.includes(nonce), `${publicName} must carry this run's nonce`)
      assert.equal(canonical(published!.parameters), canonical(asServed!.inputSchema),
        `${publicName} input schema must be the served schema, unrewritten`)
    }

    // 3. The child's own view: it ran as the fixed module, with the configured
    //    interpreter, from the backend directory's parent.
    const startups = ledgerOf(project, 'startup')
    assert.equal(startups.length, 1, 'exactly one server generation must have started')
    assert.equal(startups[0]!.module, 'backend', 'the child must run as the backend module package')
    assert.equal(resolve(startups[0]!.executable!), resolve(PYTHON), 'the child must be the configured interpreter')
    assert.equal(resolve(startups[0]!.cwd!), resolve(project.projectRoot), 'the child must run from the backendRoot parent')

    // 4. The plugin's evidence agrees with the registry and records the mapping.
    const records = evidence(project)
    assert.equal(records.length, 1, 'one composition must write exactly one evidence record')
    const record = records[0]!
    assert.equal(record.schemaVersion, BACKEND_EVIDENCE_VERSION)
    assert.equal(record.state, 'ready')
    assert.equal(record.serverName, SERVER_NAME)
    assert.deepEqual(record.tools.map((tool: any) => tool.publicName), expected, 'evidence tool order is registration order')
    assert.deepEqual(record.required, { missing: [], unexpected: [] })
    assert.equal(record.registry.observable, true)
    assert.deepEqual(record.registry.mismatches, [])
    for (const tool of record.tools) {
      assert.equal(canonical(tool.inputSchema), canonical(servedByName.get(tool.rawName)!.inputSchema))
    }
    assert.deepEqual(record.mapping, {
      transport: 'stdio',
      command: PYTHON,
      args: ['-m', 'backend.entity_server'],
      cwd: project.projectRoot,
      envAllowlist: { ...BACKEND_ENV_ALLOWLIST },
      toolCallTimeoutMs: 60_000,
      failOnStartupError: true,
      reconnect: { ...BACKEND_RECONNECT_POLICY },
    })

    // 5. A real dispatch through the real registry reaches the fixture server
    //    and returns what the server answered.
    const result = await dispatchTool(booted, expectedPublicToolName(SERVER_NAME, 'mw_scene_read_entities'),
      { levelHandle: 'handle-1' })
    assert.equal(result.isError, false, `the read must succeed: ${JSON.stringify(result)}`)
    const structured = (result.value as { structuredContent?: Record<string, unknown> }).structuredContent
    assert.equal(structured?.nonce, nonce, 'the structured result must carry this run\'s nonce')
    assert.deepEqual(structured?.echo, { levelHandle: 'handle-1' }, 'the server must have received the arguments')
    assert.equal(callsFor(project, 'mw_scene_read_entities').length, 1)

    // 6. The resource handle T03 consumes is present and owns the namespace.
    const handle = handleOf(booted)
    assert.equal(handle.serverName, SERVER_NAME)
    assert.equal(handle.toolsPrefix, toolNamePrefix(SERVER_NAME))
    assert.deepEqual([...handle.toolNames], expected)
    assert.equal(handle.state, 'ready')

    // 7. Disposal releases the tools and the child process.
    const started = startups[0]!.pid!
    const report = await handle.dispose({ reason: 'T02-A' })
    assert.equal(report.connectionDisposed, true)
    assert.deepEqual(ownedNames(booted), [], 'disposal must unregister this server\'s tools')
    await waitFor(() => processAlive(started) ? undefined : true, 5_000, 'the fixture server to exit after disposal')
  } finally {
    await booted!.ctx.fiber.dispose()
  }
})

test('T02-B a backend that fails to start publishes nothing and is reported as failed', async () => {
  const project = makeProject('crash', businessScenario('crash', { startup: 'crash', startupExitCode: 3 }), { awkward: false })
  const error = await bootRejection(bootComposition(project))
  assert.match(chainText(error), /BACKEND_NOT_READY/, 'activation must fail under the default policy')
  assert.match(chainText(error), /backend did not start/, 'the diagnostic must say the backend did not start')

  // Provenance: the tree that rejected is mounted by the PINNED Loader, and the
  // MCP client this composition uses is the PINNED vendored package rather than
  // a registry copy — the two supply-chain facts the naming of this suite's
  // evidence rests on.
  assert.equal(errorChain(error).some(entry => (entry.stack ?? '').includes('vendor/deepseek-harness/vendor/loader')), true,
    'the stack of the rejected composition must run through the pinned Loader')
  assert.equal(import.meta.resolve('@deepseek-ai/dsh-mcp-client').includes('packages/mcp/mcp-client'), true,
    'the client must resolve to the pinned checkout, not a downloaded copy')

  const records = evidence(project)
  assert.equal(records.length, 1, 'a failed composition still writes its evidence')
  assert.equal(records[0]!.state, 'failed')
  assert.deepEqual(records[0]!.tools, [], 'a failed composition publishes no tool')
  assert.equal(records[0]!.detail.startsWith('backend did not start:'), true)

  // The child reached its own start-up path and refused before any handshake.
  assert.deepEqual(ledgerOf(project, 'tools/list'), [], 'no tool list may be served by a backend that refused to start')
  assert.equal(ledgerOf(project, 'startup-crash').length, 1)
})

test('T02-C an incomplete business tool table is refused instead of published partially', async () => {
  const scenario = businessScenario('subset')
  const dropped = [REQUIRED_BUSINESS_TOOLS[1]!, REQUIRED_BUSINESS_TOOLS[5]!]
  scenario.tools = scenario.tools.filter(tool => !dropped.includes(tool.name))
  const project = makeProject('subset', scenario, { awkward: false })
  const booted = await bootComposition(project, { overrides: { failOnStartupError: false } })
  try {
    // The lenient policy mounts the plugin; the composition still refuses its table.
    assert.equal(miliastraEntry(booted.ctx).fiber?.state, FIBER_ACTIVE)
    const prefix = toolNamePrefix(SERVER_NAME)
    assert.deepEqual(booted.visible().filter(name => name.startsWith(prefix)), [],
      'no partial business table may ever be visible')

    // The table really was published first and then revoked: the change timeline
    // must show a moment with the served tools AND a later moment without them.
    const withTools = booted.timeline.snapshots.filter(snapshot => snapshot.some(name => name.startsWith(prefix)))
    assert.ok(withTools.length > 0, 'the served tools must have reached the registry before being refused')
    assert.deepEqual(booted.timeline.snapshots.at(-1)!.filter(name => name.startsWith(prefix)), [],
      'the last registry state must hold none of this server\'s tools')

    const record = evidence(project).at(-1)!
    assert.equal(record.state, 'unavailable')
    assert.deepEqual(record.required.missing,
      dropped.map(name => expectedPublicToolName(SERVER_NAME, name)).sort(),
      'the missing tools must be named exactly')
    assert.equal(record.detail.includes(expectedPublicToolName(SERVER_NAME, dropped[0]!)), true)
    // The mismatch is a tool-table fact, not a dead connection: the server did serve.
    assert.equal(ledgerOf(project, 'tools/list').length >= 1, true)
  } finally {
    booted.timeline.stop()
    await booted.ctx.fiber.dispose()
  }
})

test('T02-D two server tools colliding on one public name fail the composition', async () => {
  const scenario = businessScenario('collision')
  // Two entries with the SAME raw name: a tools/list a conforming server would
  // never send. Note the other collision shape — two distinct raw names that
  // normalize onto one public name — is NOT an error: the client appends a
  // 12-hex-char identity hash, so those stay distinguishable (asserted below).
  scenario.tools = [
    ...scenario.tools,
    { name: REQUIRED_BUSINESS_TOOLS[0]!, description: 'duplicate of the first tool', inputSchema: { type: 'object', properties: {} } },
  ]
  const project = makeProject('collision', scenario, { awkward: false })
  const error = await bootRejection(bootComposition(project))
  assert.match(chainText(error), /listed tool .* more than once|already registered/,
    'the duplicate must be refused by name, not silently resolved')
  // Provenance of the refusal, by text origin rather than by stack frames: the
  // Loader rewrites the frames of aggregated tree errors, so the sentence that
  // identifies the check is the reliable trace. The vendored client owns it, and
  // neither this plugin nor the fixture may contain it.
  const clientSource = readFileSync(join(repoRoot, 'vendor', 'deepseek-harness', 'packages', 'mcp', 'mcp-client', 'src', 'tools.ts'), 'utf8')
  assert.equal(clientSource.includes('more than once'), true,
    'the pinned vendored client must be the component that refuses a repeated tool name')
  for (const own of [join(packageDir, 'src', 'backend.ts'), fixtureServerPath]) {
    assert.equal(readFileSync(own, 'utf8').includes('more than once'), false,
      `the refusal must not be a local re-implementation (${own})`)
  }

  const records = evidence(project)
  assert.equal(records.length, 1)
  assert.equal(records[0]!.state, 'failed')
  assert.deepEqual(records[0]!.tools, [], 'a colliding table publishes nothing')

  // The OTHER collision shape is not a failure: two distinct raw names that
  // normalize onto one clean public name gain a 12-hex-char identity hash, so
  // they stay distinguishable. They are then outside the business contract, and
  // the gate must treat them as writes rather than let them through ungated.
  const hashedScenario = businessScenario('hashed')
  hashedScenario.tools = [
    ...hashedScenario.tools,
    // A dot is legal in an MCP tool name but not in the client's public-name
    // vocabulary, so this pair normalizes onto one clean public name.
    { name: 'mw.scene.hashed', description: 'normalizes onto a clean name', inputSchema: { type: 'object', properties: {} } },
    { name: 'mw_scene_hashed', description: 'the clean name', inputSchema: { type: 'object', properties: {} } },
  ]
  const hashedProject = makeProject('hashed', hashedScenario, { awkward: false })
  const hashedBoot = await bootComposition(hashedProject)
  try {
    const prefix = toolNamePrefix(SERVER_NAME)
    const extra = hashedBoot.visible().filter(name => name.startsWith(prefix) && name.includes('hashed')).sort()
    assert.equal(extra.length, 2, `both collision-shaped tools must stay published and distinct: ${JSON.stringify(extra)}`)
    assert.notEqual(extra[0], extra[1])
    assert.equal(extra.some(name => name.includes('_') && /_[0-9a-f]{12}$/.test(name)), true,
      'the lossy name must carry the client\'s identity hash')

    const record = evidence(hashedProject).at(-1)!
    assert.equal(record.state, 'ready', 'a lossy-but-distinct name is drift, not a failure')
    assert.deepEqual([...record.required.unexpected].sort(), extra,
      'tools outside the business contract must be reported as unexpected')
    assert.equal(record.detail.includes('outside the business contract'), true)

    // Fail closed: an unexpected tool is gated like a write.
    const handle = handleOf(hashedBoot)
    await handle.drain({ reason: 'T02-D probe', timeoutMs: 0 })
    const refused = await dispatchTool(hashedBoot, extra[0]!, {})
    assert.equal(refused.isError, true, 'an unexpected tool must be gated, not dispatched ungated')
    assert.equal(ledgerOf(hashedProject, 'tools/call').length, 0, 'a gated unexpected tool must not reach the server')
  } finally {
    hashedBoot.timeline.stop()
    await hashedBoot.ctx.fiber.dispose()
  }
})

test('T02-E a call that outlives the tool timeout becomes unknown and is never re-sent', async () => {
  const scenario = businessScenario('timeout', {
    behaviors: { mw_scene_create_entity: 'hang' },
    hangSeconds: 30,
  })
  const project = makeProject('timeout', scenario, { awkward: false })
  const booted = await bootComposition(project, { overrides: { toolCallTimeoutMs: 1_500 } })
  try {
    const handle = handleOf(booted)
    const writeName = expectedPublicToolName(SERVER_NAME, 'mw_scene_create_entity')
    const callId = 't02-e-timeout-write'
    const outcome = await dispatchTool(booted, writeName, { levelHandle: 'h', templateId: 1, requestId: 'r-1', position: [0, 0, 0] }, callId)
    assert.equal(outcome.isError, true, 'a call that outlives the timeout must fail')

    const drain = await handle.drain({ reason: 'T02-E', timeoutMs: 2_000 })
    assert.equal(drain.unknown.length, 1, 'the timed-out write must be recorded as unknown')
    assert.equal(drain.unknown[0]!.toolName, writeName)
    assert.equal(drain.unknown[0]!.state, 'unknown')
    // The operation key is the CALLER's business idempotency key, and that key is the
    // tool's own `requestId`: `contracts/contract.json` maps it
    // (`idempotency.aliasesAcceptedOnInput.requestId = "operationId"`,
    // `boundary.allowedInToolCall` operationId aliasOnDisk "requestId"). The
    // provider-minted registry callId is NOT usable as a ledger key -- the PTC bridge
    // mints `${callId}:ptc:${n}`, which `OPERATION_ID_PATTERN` refuses, and it is
    // unique per call, so a repeat of one business operation could never be recognised.
    assert.equal(drain.unknown[0]!.operationId, 'r-1',
      'the ledger must key on the CALLER\'s business idempotency key, so T06 can reconcile without a second id')

    // No re-dispatch: the server saw the write exactly once, and still does
    // after the composition has been left running longer than the timeout.
    await new Promise<void>((resolve) => { setTimeout(resolve, 2_000) })
    assert.equal(callsFor(project, 'mw_scene_create_entity').length, 1, 'a timed-out write must never be re-sent')

    // The connection itself survived: a read still round-trips.
    const readName = expectedPublicToolName(SERVER_NAME, 'mw_scene_capabilities')
    const read = await dispatchTool(booted, readName, {})
    assert.equal(read.isError, false, `the connection must stay usable after a per-call timeout: ${JSON.stringify(read)}`)
    assert.equal(callsFor(project, 'mw_scene_capabilities').length, 1)
  } finally {
    booted.timeline.stop()
    await booted.ctx.fiber.dispose()
  }
})

test('T02-F reconnecting restores the connection and never re-dispatches the lost write', async () => {
  const scenario = businessScenario('reconnect', {
    behaviors: { mw_scene_save_level: 'drop' },
    dropExitCode: 7,
  })
  const project = makeProject('reconnect', scenario, { awkward: false })
  const booted = await bootComposition(project)
  try {
    const writeName = expectedPublicToolName(SERVER_NAME, 'mw_scene_save_level')
    const outcome = await dispatchTool(booted, writeName, { levelHandle: 'h', requestId: 'r-reconnect' })
    assert.equal(outcome.isError, true, 'the dropped call must fail')

    // The supervisor reconnects on its own, and the new generation re-syncs:
    // waiting for a *second* tools/list is the only honest signal — the first
    // generation's table stays registered until the new sync replaces it, so
    // "seven names are visible" is true before, during, and after the reconnect.
    await waitFor(() => ledgerOf(project, 'startup').length >= 2 ? true : undefined, 20_000,
      'the fixture server to be restarted by the client\'s reconnect')
    await waitFor(() => ledgerOf(project, 'tools/list').length >= 2 ? true : undefined, 20_000,
      'the reconnected client to re-sync its tool list')
    assert.equal(booted.visible().filter(name => name.startsWith(toolNamePrefix(SERVER_NAME))).length,
      REQUIRED_BUSINESS_TOOLS.length, 'the re-synced table must hold every business tool')

    // The lost write is still exactly one dispatch across both generations.
    assert.equal(callsFor(project, 'mw_scene_save_level').length, 1,
      'a reconnect must restore the connection only — never re-send the lost write')
    const handle = handleOf(booted)
    const drain = await handle.drain({ reason: 'T02-F', timeoutMs: 1_000 })
    assert.equal(drain.unknown.length, 1, 'the lost write must be reported as unknown for reconciliation')
    assert.equal(drain.unknown[0]!.toolName, writeName)

    // And the reconnected connection really works: a fresh write goes out once.
    const readName = expectedPublicToolName(SERVER_NAME, 'mw_scene_discover_level')
    const read = await dispatchTool(booted, readName, {})
    assert.equal(read.isError, false,
      `the reconnected connection must serve calls: ${JSON.stringify(read)} [ledger: ${ledgerSummary(project)}]`)
    assert.equal(callsFor(project, 'mw_scene_discover_level').length, 1)
  } finally {
    booted.timeline.stop()
    await booted.ctx.fiber.dispose()
  }
})

test('T02-G the child gets the scrubbed parent environment plus the documented allowlist', async () => {
  const markers = {
    credential: 'T02_FIXTURE_API_KEY',
    password: 'T02_FIXTURE_PASSWORD',
    dsh: 'DSH_T02_SENTINEL',
    benign: 'T02_FIXTURE_BENIGN',
  }
  const previous = new Map(Object.entries(markers).map(([, name]) => [name, process.env[name]]))
  process.env[markers.credential] = 'must-not-reach-the-backend'
  process.env[markers.password] = 'must-not-reach-the-backend'
  process.env[markers.dsh] = 'must-not-reach-the-backend'
  process.env[markers.benign] = 'ordinary-value'
  try {
    const project = makeProject('env', businessScenario('env'), { awkward: false })
    const booted = await bootComposition(project)
    try {
      const envKeys = ledgerOf(project, 'startup').at(-1)!.envKeys ?? []
      assert.equal(envKeys.includes(markers.credential), false, 'credential-shaped names must be scrubbed')
      assert.equal(envKeys.includes(markers.password), false, 'credential-shaped names must be scrubbed')
      assert.equal(envKeys.includes(markers.dsh), false, 'DSH_* names must be scrubbed')
      assert.equal(envKeys.includes(markers.benign), true, 'the scrub must not be a blanket denial of the parent environment')
      for (const name of Object.keys(BACKEND_ENV_ALLOWLIST)) {
        assert.equal(envKeys.includes(name), true, `${name} must reach the backend`)
        assert.equal(name.toUpperCase().includes('KEY') || name.toUpperCase().includes('TOKEN'), false,
          'the allowlist must never carry a credential-shaped name')
      }
      const record = evidence(project).at(-1)!
      assert.deepEqual(record.mapping.envAllowlist, { ...BACKEND_ENV_ALLOWLIST })
      assert.equal(JSON.stringify(record.mapping).includes('must-not-reach-the-backend'), false,
        'no credential value may appear in the evidence record')
    } finally {
      booted.timeline.stop()
      await booted.ctx.fiber.dispose()
    }
  } finally {
    for (const [name, value] of previous) {
      if (value === undefined) delete process.env[name]
      else process.env[name] = value
    }
  }
})

test('T02-H an output schema the client cannot carry is left unconstrained, not mangled or dropped', async () => {
  const supported = { type: 'object', properties: { count: { type: 'integer' } }, required: ['count'] }
  // `format` is outside the enforced JSON-Schema subset, so the vendored client
  // falls back to an unconstrained structuredContent instead of copying through
  // a contract it cannot enforce.
  const unsupported = {
    type: 'object',
    properties: { stamp: { type: 'string', format: 'date-time' } },
    required: ['stamp'],
  }
  const scenario = businessScenario('schema')
  scenario.tools = [
    { ...scenario.tools[0]!, outputSchema: supported },
    { ...scenario.tools[1]!, outputSchema: unsupported },
    ...scenario.tools.slice(2),
  ]
  scenario.responses = {
    [REQUIRED_BUSINESS_TOOLS[0]!]: { count: 4 },
    [REQUIRED_BUSINESS_TOOLS[1]!]: { stamp: '2026-10-02T00:00:00Z' },
  }
  const project = makeProject('schema', scenario, { awkward: false })
  const booted = await bootComposition(project)
  try {
    const declaredName = expectedPublicToolName(SERVER_NAME, REQUIRED_BUSINESS_TOOLS[0]!)
    const unconstrainedName = expectedPublicToolName(SERVER_NAME, REQUIRED_BUSINESS_TOOLS[1]!)
    const declaredDefinition = booted.tools.get(declaredName)
    const unconstrainedDefinition = booted.tools.get(unconstrainedName)
    assert.ok(declaredDefinition !== undefined && unconstrainedDefinition !== undefined,
      'both tools must still be published — an unsupported output schema is not a reason to drop a tool')

    // Positive control: a supported advertised schema is reproduced verbatim.
    const declaredOutput = declaredDefinition.output.schema as { properties: Record<string, unknown>, required: string[] }
    assert.equal(canonical(declaredOutput.properties.structuredContent), canonical(supported))
    assert.equal(declaredOutput.required.includes('structuredContent'), true)

    // The unsupported one is unconstrained — and nothing of it leaks through.
    const fallbackOutput = unconstrainedDefinition.output.schema as { properties: Record<string, unknown>, required: string[] }
    assert.deepEqual(fallbackOutput.properties.structuredContent, {},
      'an unsupported output schema must become an unconstrained schema, not a partial copy')
    assert.equal(fallbackOutput.required.includes('structuredContent'), false)
    assert.equal(JSON.stringify(fallbackOutput).includes('date-time'), false,
      'no keyword the client cannot enforce may survive into the registered schema')

    // The plugin reports the difference it can observe, and claims no more.
    const record = evidence(project).at(-1)!
    const byRaw = new Map<string, any>(record.tools.map((tool: any) => [tool.rawName, tool] as const))
    assert.equal(byRaw.get(REQUIRED_BUSINESS_TOOLS[0]!)!.outputContract, 'declared')
    assert.equal(byRaw.get(REQUIRED_BUSINESS_TOOLS[1]!)!.outputContract, 'unconstrained')

    const read = await dispatchTool(booted, unconstrainedName, { levelHandle: 'h' })
    assert.equal(read.isError, false, `the tool must still execute: ${JSON.stringify(read)}`)
    assert.equal((read.value as { structuredContent?: Record<string, unknown> }).structuredContent?.stamp,
      '2026-10-02T00:00:00Z', 'the raw structured content still reaches the caller')
  } finally {
    booted.timeline.stop()
    await booted.ctx.fiber.dispose()
  }
})

test('T02-I draining refuses new dispatches, keeps in-flight ones, and disposal is idempotent', async () => {
  const scenario = businessScenario('drain', {
    behaviors: { mw_scene_create_entity: 'hang' },
    hangSeconds: 1.2,
  })
  const project = makeProject('drain', scenario, { awkward: false })
  const booted = await bootComposition(project, { overrides: { toolCallTimeoutMs: 30_000 } })
  try {
    const handle = handleOf(booted)
    // A live snapshot for T03's contract sample, taken while the composition is
    // still ready: after disposal the published table is genuinely empty.
    const readySample = {
      state: handle.state,
      serverName: handle.serverName,
      toolsPrefix: handle.toolsPrefix,
      toolNames: [...handle.toolNames],
      evidencePath: handle.evidencePath,
    }
    const writeName = expectedPublicToolName(SERVER_NAME, 'mw_scene_create_entity')
    const pending = dispatchTool(booted, writeName, { levelHandle: 'h', templateId: 1, requestId: 'r-drain', position: [0, 0, 0] }, 't02-i-in-flight')
    await waitFor(() => callsFor(project, 'mw_scene_create_entity').length === 1 ? true : undefined, 5_000,
      'the write to reach the server')

    // A zero-bound drain reports the in-flight write instead of pretending to be done.
    const probe = await handle.drain({ reason: 'T02-I probe', timeoutMs: 0 })
    assert.equal(probe.quiescent, false, 'an in-flight write must not be reported as quiescent')
    assert.equal(probe.inFlight.length, 1)
    assert.equal(probe.inFlight[0]!.toolName, writeName)
    // Keyed by the business idempotency key, not the registry callId: see the long
    // note in T02-E and `contracts/contract.json`'s operationId alias.
    assert.equal(probe.inFlight[0]!.operationId, 'r-drain')
    assert.equal(handle.state, 'draining')

    // A dispatch issued while draining is refused, and nothing is sent.
    const refused = await dispatchTool(booted, writeName, { levelHandle: 'h', templateId: 1, requestId: 'r-refused', position: [0, 0, 0] })
    assert.equal(refused.isError, true, 'a dispatch during drain must fail')
    assert.equal(callsFor(project, 'mw_scene_create_entity').length, 1, 'a refused dispatch must not reach the server')

    const settled = await pending
    assert.equal(settled.isError, false, `the in-flight write must complete normally: ${JSON.stringify(settled)}`)
    const drain = await handle.drain({ reason: 'T02-I', timeoutMs: 5_000 })
    assert.equal(drain.quiescent, true)
    assert.deepEqual(drain.unknown, [])
    assert.equal(drain.refusedDispatches >= 1, true, 'the refused dispatch must be counted')

    // The handle T03 consumes has exactly this shape.
    const report = await handle.dispose({ reason: 'T02-I' })
    assert.deepEqual(Object.keys(report).sort(),
      ['alreadyDisposed', 'connectionDisposed', 'inFlight', 'quiescent', 'reason', 'refusedDispatches', 'serverName', 'unknown'])
    assert.equal(report.alreadyDisposed, false)
    assert.equal(report.connectionDisposed, true)
    const again = await handle.dispose({ reason: 'T02-I again' })
    assert.equal(again.alreadyDisposed, true, 'disposal must be idempotent')
    assert.equal(handle.state, 'disposed')
    assert.deepEqual(ownedNames(booted), [])

    if (SAMPLE_DIR !== '') {
      mkdirSync(SAMPLE_DIR, { recursive: true })
      writeFileSync(join(SAMPLE_DIR, 'resource-handle.sample.json'),
        `${JSON.stringify(readySample, null, 2)}\n`)
      writeFileSync(join(SAMPLE_DIR, 'drain-report.sample.json'),
        `${JSON.stringify({ probe, drain, dispose: report, disposeAgain: again }, null, 2)}\n`)
    }
  } finally {
    booted.timeline.stop()
    await booted.ctx.fiber.dispose()
  }
})

test('T02-J a composition that cannot record its evidence refuses to become ready', async () => {
  const project = makeProject('evidence', businessScenario('evidence'), { awkward: false })
  // A file where the evidence directory's parent should be: mkdir cannot succeed.
  writeFileSync(join(project.projectRoot, 'blocker'), 'not a directory\n')
  const overrides = { evidenceRoot: join(project.projectRoot, 'blocker', 'evidence') }
  const error = await bootRejection(bootComposition(project, { overrides }))
  assert.match(chainText(error), /EVIDENCE_WRITE_FAILED/, 'the refusal must name the evidence failure')
  assert.match(chainText(error), /BACKEND_NOT_READY/, 'and activation must fail under the default policy')
})

test('T02-K a backend directory that cannot name the fixed entry is refused before any spawn', async () => {
  const missing = makeProject('missing-entry', businessScenario('missing', { startup: 'missing-entry' }), { awkward: false })
  const missingError = await bootRejection(bootComposition(missing))
  assert.match(chainText(missingError), /BACKEND_ENTRY_MISSING/, 'a missing entry must be named, not discovered by spawning')
  assert.equal(existsSync(missing.ledgerPath), false, 'nothing may be spawned for a backend that cannot start')

  const unusable = makeProject('unusable-root', businessScenario('unusable'), { awkward: false })
  const badRoot = join(unusable.projectRoot, 'not-a-module-name')
  mkdirSync(badRoot, { recursive: true })
  writeFileSync(join(badRoot, 'entity_server.py'), readFileSync(fixtureServerPath))
  const unusableError = await bootRejection(bootComposition(unusable, { overrides: { backendRoot: badRoot } }))
  assert.match(chainText(unusableError), /BACKEND_ROOT_NAME_UNUSABLE/,
    'a backend directory Python cannot name must be refused by name')
  assert.equal(existsSync(unusable.ledgerPath), false, 'nothing may be spawned for an unusable module path')
})

test('T02-L the required-tool contract is the real backend\'s own tool list', async () => {
  const source = readFileSync(REAL_BACKEND_PATH, 'utf8')
  const declared = [...source.matchAll(/^def (mw_[A-Za-z0-9_]+)\(/gm)].map(match => match[1]!)
  assert.ok(declared.length > 0, 'the real backend must declare its tools as mw_* functions')
  assert.equal(new Set(declared).size, declared.length, 'the real backend must not declare a tool twice')
  assert.deepEqual([...REQUIRED_BUSINESS_TOOLS].sort(), [...declared].sort(),
    'the composition contract must be exactly the real backend\'s tools')
  for (const name of WRITE_BUSINESS_TOOLS) {
    assert.equal(REQUIRED_BUSINESS_TOOLS.includes(name), true, `${name} is a write tool, so it must be required`)
  }
})

test('T02-N the built entry resolves the packaged backend sibling and composes', async () => {
  const builtEntry = join(packageDir, 'lib', 'index.js')
  const builtBackend = join(packageDir, 'lib', 'backend.js')
  assert.ok(existsSync(builtEntry), `${builtEntry} is missing — run the build before this suite`)
  assert.ok(existsSync(builtBackend), `${builtBackend} is missing — the entry resolves its backend sibling as ./backend.js`)
  assert.ok(statSync(builtEntry).mtimeMs >= statSync(sourceEntryPath).mtimeMs,
    `${builtEntry} is older than ${sourceEntryPath} — rebuild before this suite`)

  const project = makeProject('built', businessScenario('built'), { awkward: false })
  // The shipped row specifier, i.e. the path an installed profile takes.
  const booted = await bootComposition(project, { builtEntry: true })
  try {
    assert.equal(miliastraEntry(booted.ctx).fiber?.state, FIBER_ACTIVE)
    const expected = REQUIRED_BUSINESS_TOOLS.map(name => expectedPublicToolName(SERVER_NAME, name))
    assert.deepEqual(ownedNames(booted), [...expected].sort(),
      'the built entry must publish the same table as the source entry')
    const record = evidence(project).at(-1)!
    assert.equal(record.state, 'ready')
    assert.deepEqual(record.mapping.args, ['-m', 'backend.entity_server'])
  } finally {
    booted.timeline.stop()
    await booted.ctx.fiber.dispose()
  }
})

test('T02-M the Config->MCP mapping is total, pure, and never model-supplied', async () => {
  const project = makeProject('mapping', businessScenario('mapping'), { awkward: false })
  const config = {
    configVersion: 1 as const,
    projectRoot: project.projectRoot,
    backendRoot: project.backendRoot,
    pythonExecutable: PYTHON,
    evidenceRoot: project.evidenceRoot,
    serverName: SERVER_NAME,
    toolCallTimeoutMs: 1_234,
    backendModule: '',
    failOnStartupError: false,
  }
  const stdio = buildBackendStdioConfig(config)
  assert.deepEqual(stdio, {
    transport: 'stdio',
    serverName: SERVER_NAME,
    command: PYTHON,
    args: ['-m', 'backend.entity_server'],
    cwd: project.projectRoot,
    env: { ...BACKEND_ENV_ALLOWLIST },
    toolCallTimeoutMs: 1_234,
    failOnStartupError: false,
    reconnect: { ...BACKEND_RECONNECT_POLICY },
  }, 'the mapping must be exactly the documented table')
  assert.equal(backendModulePath(project.backendRoot), 'backend.entity_server')
  assert.equal(backendEntryPath(project.backendRoot), join(project.backendRoot, 'entity_server.py'))

  // The mapping must not read the child's environment or the clock: calling it
  // twice on the same config yields an equal, independent value.
  const again = buildBackendStdioConfig(config)
  assert.deepEqual(again, stdio)
  assert.notEqual(again.env, stdio.env, 'each composition must own its env object')

  // A directory Python cannot name is refused with the coded error.
  assert.throws(() => backendModulePath(join(project.projectRoot, 'not-a-module')), (error: unknown) => {
    return (error as { code?: string }).code === 'BACKEND_ROOT_NAME_UNUSABLE'
  })
})
