/**
 * T01 loader-composition suite — the REAL composition test for
 * `@miliastra/dsh-miliastra`.
 *
 * What makes this a real composition rather than a unit test: every case boots
 * the pinned dsh Loader (`boot()` from `@deepseek-ai/dsh-app-boot`) against an
 * empty `cordis.yml`, applies the package's **own shipped `cordis.patch.yml`**
 * through the real patch-dialect parser, and lets the Loader import the plugin
 * entry and settle the entry tree. Nothing calls `apply()` directly and nothing
 * assembles a context by hand.
 *
 * What is faked, and why that is enough: the `tools` service is replaced by the
 * smallest stand-in that answers `ctx.get('tools')`, because the real registry is
 * T02's subject and T01 publishes no tool. The business backend is a plain
 * fixture module reached through the plugin's own composition slot. Loader, patch
 * dialect, entry import, inject-gated activation, Schemastery config resolution,
 * and rollback are all the shipping implementation.
 *
 * What this suite does NOT claim: no MCP server starts, no tool reaches a real
 * registry, no game or editor process is touched, and no model runs. Those are
 * T02/T13 rows and stay not-run in this task's result.
 *
 * Run: `pnpm test` (builds first, then runs this file), or
 *      `node --test tests/loader-composition.spec.ts`.
 *
 * @module @miliastra/dsh-miliastra/tests/loader-composition.spec
 */

import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { boot, loadOverlayPatches } from '@deepseek-ai/dsh-app-boot'
import type { PatchOptions } from '@deepseek-ai/cordis-plugin-include'
import type { Context } from '@deepseek-ai/cordis'

/** This package's directory (`plugins/miliastra`). */
const packageDir = fileURLToPath(new URL('..', import.meta.url))

/** The source entry the Loader imports; never a build artifact. */
const sourceEntryPath = join(packageDir, 'src', 'index.ts')

/** The built entry `exports["."]` publishes; produced by `pnpm build`. */
const builtEntryPath = join(packageDir, 'lib', 'index.js')

/** The package's own bundle patch — the artifact under composition. */
const bundlePatchPath = join(packageDir, 'cordis.patch.yml')

/** Cordis `FiberState.ACTIVE`; the const enum has no runtime object (mirrors dsh-app-boot). */
const FIBER_ACTIVE = 2

/** Fixture backend that composes and reports a ready tool surface. */
const READY_BACKEND = '../tests/fixtures/t01-fake-backend.js'

/** Fixture backend that composes but declines to claim readiness. */
const DECLINING_BACKEND = '../tests/fixtures/t01-declining-backend.js'

/** Fixture module in the slot that throws while composing. */
const THROWING_BACKEND = '../tests/fixtures/t01-throwing-backend.js'

/** Fixture module in the slot that exports no `composeBackend`. */
const WRONG_SHAPE_BACKEND = '../tests/fixtures/t01-wrong-shape.js'

/** A slot target that does not exist on disk. */
const ABSENT_BACKEND = '../tests/fixtures/t01-not-built-yet.js'

/** An unrelated but valid Cordis row, used for the row-order case. */
const ORDER_PLUGIN = pathToFileURL(join(packageDir, 'tests', 'fixtures', 't01-order-plugin.js')).href

/** Observation file the ready fixture appends one JSON record per composition to. */
const OBSERVATION_FILE = 't01-fake-backend.jsonl'

/** Every temp directory this suite created; removed in `after()`. */
const tempRoots: string[] = []

/**
 * The smallest stand-in for the `tools` service.
 *
 * The real one (`@deepseek-ai/dsh-tools`) is a full registry with schemas,
 * dispatch, guards, and per-scope layers. This suite exercises exactly two facts
 * about the service: that `inject: ['tools']` gates activation on its presence,
 * and that T01 publishes nothing into it.
 */
class FakeTools {
  /** Tool names any backend asked to register, in order. */
  readonly registered: string[] = []

  /**
   * Record one registration.
   * @param definition - tool definition; only its name is read here.
   * @returns the unregister function the real registry returns.
   */
  register(definition: { name: string }): () => void {
    this.registered.push(definition.name)
    return () => {
      const index = this.registered.indexOf(definition.name)
      if (index >= 0) this.registered.splice(index, 1)
    }
  }
}

/** One fixture project tree and the paths that point into it. */
interface FixtureProject {
  /** Temp root; every path below lives under it. */
  readonly root: string
  /** Project checkout stand-in, deliberately containing CJK and spaces. */
  readonly projectRoot: string
  /** Interpreter stand-in; a real file, never executed. */
  readonly pythonExecutable: string
  /** Evidence root inside the project root. */
  readonly evidenceRoot: string
}

/**
 * Create a hermetic project tree.
 *
 * The path is deliberately awkward (CJK, spaces, parentheses): the config
 * contract promises verbatim pass-through of operator paths, and a path that
 * needs no quoting would not test that.
 * @param label - short run label used in the directory name.
 * @returns the fixture project.
 */
function makeProject(label: string): FixtureProject {
  const root = mkdtempSync(join(tmpdir(), `miliastra-t01-${label}-`))
  tempRoots.push(root)
  const projectRoot = join(root, '千星 项目 根 (fixture)')
  const pythonExecutable = join(projectRoot, '工具', 'python-stub.exe')
  mkdirSync(join(projectRoot, 'backend'), { recursive: true })
  mkdirSync(join(projectRoot, '工具'), { recursive: true })
  writeFileSync(pythonExecutable, 'fixture interpreter placeholder; this file is never executed\n')
  return { root, projectRoot, pythonExecutable, evidenceRoot: join(projectRoot, '.runtime', 'cordis-evidence') }
}

/**
 * The config an operator override row would write.
 * @param project - fixture project.
 * @param overrides - fields to replace.
 * @returns the row config.
 */
function configFor(project: FixtureProject, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    projectRoot: project.projectRoot,
    backendRoot: '',
    pythonExecutable: project.pythonExecutable,
    evidenceRoot: project.evidenceRoot,
    serverName: 'miliastra_t01',
    toolCallTimeoutMs: 5_000,
    backendModule: READY_BACKEND,
    failOnStartupError: false,
    ...overrides,
  }
}

/**
 * Compose the patch stack the way a profile would: the package's own bundle
 * patch (parsed by the real patch dialect reader), then an id-targeted override
 * of that row's config, then any extra rows the case needs.
 *
 * The row's module specifier defaults to the **source entry**: a behavioral case
 * must not be satisfiable by a stale `lib/`, so only the one case whose subject
 * is the published artifact leaves the shipped specifier in place.
 * @param project - fixture project.
 * @param options - config overrides, extra rows, and entry selection.
 * @returns the patch list and the exact config the row ends with.
 */
function composePatches(
  project: FixtureProject,
  options: {
    overrides?: Record<string, unknown>
    extraRows?: NonNullable<PatchOptions['insert']>
    extraRowsFirst?: boolean
    builtEntry?: boolean
    entryName?: string
  } = {},
): { patches: PatchOptions[], config: Record<string, unknown> } {
  const bundle = loadOverlayPatches('miliastra-test', bundlePatchPath)
  assert.ok(bundle.length > 0, 'the package must ship a non-empty cordis.patch.yml')
  const config = configFor(project, options.overrides ?? {})
  const override: PatchOptions = { id: 'miliastra', config }
  const extras = options.extraRows ?? []
  const entryName = options.builtEntry === true ? undefined : options.entryName ?? sourceEntryPath
  if (entryName !== undefined) {
    for (const patch of bundle) {
      for (const row of patch.insert ?? []) {
        if (row.id === 'miliastra') row.name = entryName
      }
    }
  }
  const patches: PatchOptions[] = options.extraRowsFirst === true
    ? [{ insert: extras }, ...bundle, override]
    : [...bundle, { insert: extras }, override]
  return { patches, config }
}

/** Result of one boot. */
interface Booted {
  /** The settled root context. */
  readonly ctx: Context
  /** The fake tool registry the composition was offered. */
  readonly tools: FakeTools
}

/**
 * Boot the package through the real Loader.
 * @param project - fixture project (its root holds the generated `cordis.yml`).
 * @param patches - patch stack from {@link composePatches}.
 * @param options - `provideTools: false` omits the `tools` service on purpose.
 * @returns the settled context and the fake registry.
 */
async function bootComposition(
  project: FixtureProject,
  patches: PatchOptions[],
  options: { provideTools?: boolean } = {},
): Promise<Booted> {
  const rootConfig = join(project.root, 'cordis.yml')
  writeFileSync(rootConfig, '# miliastra T01 fixture root: an empty entry list\n[]\n')
  const tools = new FakeTools()
  const ctx = await boot(
    'miliastra-test',
    rootConfig,
    patches,
    options.provideTools === false ? undefined : (hostCtx: Context) => { hostCtx.provide('tools', tools) },
    pathToFileURL(join(packageDir, 'package.json')).href,
  )
  return { ctx, tools }
}

/**
 * Assert that a boot rejected and return its error, disposing a context that
 * settled anyway so a failed expectation cannot leak a live tree.
 * @param pending - the boot promise under test.
 * @returns the rejection reason.
 */
async function bootRejection(pending: Promise<Booted>): Promise<Error> {
  const outcome = await pending.then(
    async (settled) => { await settled.ctx.fiber.dispose(); return undefined },
    (error: unknown) => error,
  )
  assert.ok(outcome instanceof Error, 'expected the composition to reject, but it settled')
  return outcome
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

/** Read the fixture's observation records, or an empty list when it never composed. */
function observations(project: FixtureProject, file = OBSERVATION_FILE): Array<Record<string, any>> {
  const path = join(project.evidenceRoot, file)
  if (!existsSync(path)) return []
  return readFileSync(path, 'utf8').split('\n').filter(line => line.trim() !== '')
    .map(line => JSON.parse(line) as Record<string, any>)
}

/** Return the single `miliastra` entry the Loader created. */
function miliastraEntry(ctx: Context): { fiber?: { state: number } } {
  const entries = [...ctx.loader.entries()].filter(entry => entry.options.id === 'miliastra')
  assert.equal(entries.length, 1, 'exactly one miliastra entry must be mounted')
  return entries[0] as unknown as { fiber?: { state: number } }
}

// ---- child-process spy ------------------------------------------------------

const require = createRequire(import.meta.url)
const childProcess = require('node:child_process') as Record<string, unknown>

/** Launch entry points the spy wraps. */
const SPY_TARGETS = ['spawn', 'spawnSync', 'exec', 'execFile', 'execSync', 'execFileSync', 'fork'] as const

/**
 * Wrap every child-process launch entry point.
 * @returns a stop function returning the per-function call counts.
 */
function installLaunchSpy(): () => Record<string, number> {
  const calls: Record<string, number> = {}
  const originals = new Map<string, unknown>()
  for (const target of SPY_TARGETS) {
    const original = childProcess[target]
    if (typeof original !== 'function') continue
    calls[target] = 0
    originals.set(target, original)
    childProcess[target] = (...args: unknown[]): unknown => {
      calls[target] = (calls[target] ?? 0) + 1
      return (original as (...inner: unknown[]) => unknown)(...args)
    }
  }
  assert.ok(originals.size > 0, 'the launch spy must wrap at least one child_process entry point')
  return () => {
    for (const [target, original] of originals) childProcess[target] = original
    return calls
  }
}

after(() => {
  for (const root of tempRoots) rmSync(root, { recursive: true, force: true })
})

// ---- cases -----------------------------------------------------------------

test('T01-A composes the built package entry through the real Loader', async () => {
  assert.ok(existsSync(builtEntryPath), `${builtEntryPath} is missing — run \`pnpm build\` before this suite`)
  // Staleness guard: this is the one case whose subject IS the published
  // artifact, so a `lib/` older than the sources would make it describe a
  // previous revision. Every other case composes the source entry and cannot be
  // satisfied by a stale build at all.
  assert.ok(statSync(builtEntryPath).mtimeMs >= statSync(sourceEntryPath).mtimeMs,
    `${builtEntryPath} is older than ${sourceEntryPath} — run \`pnpm build\` before this suite`)

  const project = makeProject('built')
  // No entry override: this case resolves the row's *shipped* module specifier,
  // i.e. the path an installed profile actually takes.
  const { patches, config } = composePatches(project, { builtEntry: true })
  const stopSpy = installLaunchSpy()
  let booted: Booted
  try {
    booted = await bootComposition(project, patches)
  } finally {
    for (const [target, count] of Object.entries(stopSpy())) {
      assert.equal(count, 0, `composition must not call child_process.${target}`)
    }
  }

  try {
    assert.equal(miliastraEntry(booted.ctx).fiber?.state, FIBER_ACTIVE, 'the miliastra entry must settle ACTIVE')

    const records = observations(project)
    assert.equal(records.length, 1, 'the backend slot must be composed exactly once')
    const record = records[0]!
    assert.equal(record.fixtureKind, 't01-fake-backend', 'the configured backend module must be the one composed')
    assert.equal(record.toolsServicePresent, true, 'the injected tools service must reach the backend')
    assert.deepEqual(record.tools, [
      'mcp__miliastra_t01__level_discover',
      'mcp__miliastra_t01__entity_read',
      'mcp__miliastra_t01__entity_create',
    ])
    assert.equal(record.childProcessesStarted, 0)

    // Verbatim path pass-through: the fixture path carries CJK, spaces, and
    // parentheses, and every resolved value must survive unchanged.
    assert.equal(record.projectRoot, project.projectRoot)
    assert.equal(record.pythonExecutable, project.pythonExecutable)
    assert.equal(record.evidenceRoot, project.evidenceRoot)
    assert.equal(record.backendRoot, join(project.projectRoot, 'backend'))
    assert.equal(record.configVersion, 1)
    assert.equal(record.toolCallTimeoutMs, 5000)
    assert.equal(record.serverName, config.serverName)

    // T01 publishes nothing itself; registering tools is T02's row.
    assert.deepEqual(booted.tools.registered, [], 'T01 must not register tools on its own')
  } finally {
    await booted.ctx.fiber.dispose()
  }
})

test('T01-B the entry has no default export and survives unwrapExports', async () => {
  const project = makeProject('unwrap')
  const module = await import(pathToFileURL(sourceEntryPath).href) as Record<string, unknown>
  assert.equal('default' in module, false, 'a default export would make the Loader discard this namespace')
  assert.equal(typeof module.name, 'string')
  assert.deepEqual(module.inject, ['tools'])
  assert.equal(typeof module.apply, 'function')
  assert.notEqual(module.Config, undefined, 'Config must be exported for the Loader to validate the row')

  const booted = await bootComposition(project, composePatches(project, { entryName: sourceEntryPath }).patches)
  try {
    const unwrapped = booted.ctx.loader.unwrapExports(module) as Record<string, unknown>
    assert.equal(unwrapped.apply, module.apply)
    assert.equal(unwrapped.name, 'miliastra')
    assert.equal(unwrapped.Config, module.Config)

    // The guard has teeth: the same unwrap on a module that DOES default-export
    // drops the named exports entirely — postmortem 0001's failure mode.
    const regressed = join(project.root, 'regressed-entry.mjs')
    writeFileSync(regressed, 'export const name = "regressed"\nexport const inject = []\nexport function apply() {}\nexport default {}\n')
    const regressedModule = await import(pathToFileURL(regressed).href) as Record<string, unknown>
    const regressedUnwrapped = booted.ctx.loader.unwrapExports(regressedModule) as Record<string, unknown>
    assert.equal(regressedUnwrapped.apply, undefined, 'a default export must be shown to discard the named exports')
  } finally {
    await booted.ctx.fiber.dispose()
  }
})

test('T01-C rejects an unusable config before composing any backend', async () => {
  interface ConfigCase { label: string, set: (project: FixtureProject) => Record<string, unknown>, code: string, field: string }
  const cases: ConfigCase[] = [
    { label: 'blank pythonExecutable', code: 'MISSING_PATH', field: 'pythonExecutable', set: () => ({ pythonExecutable: '   ' }) },
    { label: 'pythonExecutable is a directory', code: 'NOT_A_FILE', field: 'pythonExecutable', set: project => ({ pythonExecutable: project.projectRoot }) },
    { label: 'evidenceRoot escapes the project', code: 'EVIDENCE_ROOT_OUTSIDE_PROJECT', field: 'evidenceRoot', set: project => ({ evidenceRoot: join(project.root, 'outside-evidence') }) },
    { label: 'backendModule is an absolute path', code: 'INVALID_BACKEND_MODULE', field: 'backendModule', set: project => ({ backendModule: project.pythonExecutable }) },
    { label: 'projectRoot does not exist', code: 'NOT_A_DIRECTORY', field: 'projectRoot', set: project => ({ projectRoot: join(project.root, 'absent-project') }) },
  ]
  for (const item of cases) {
    const project = makeProject('config')
    const patches = composePatches(project, { overrides: { ...item.set(project), failOnStartupError: true } }).patches
    const error = await bootRejection(bootComposition(project, patches))
    const configError = errorChain(error).find(candidate => candidate.name === 'MiliastraConfigError') as
      (Error & { code?: string, field?: string }) | undefined
    assert.notEqual(configError, undefined, `${item.label}: expected a MiliastraConfigError, got: ${error.message}`)
    assert.equal(configError!.code, item.code, item.label)
    assert.equal(configError!.field, item.field, item.label)
    assert.deepEqual(observations(project), [], `${item.label}: the backend must never be composed`)
  }
})

test('T01-D lets the Config schema refuse out-of-range and malformed values', async () => {
  const project = makeProject('schema')
  const timeoutError = await bootRejection(bootComposition(project,
    composePatches(project, { overrides: { toolCallTimeoutMs: 10, failOnStartupError: true } }).patches))
  assert.match(timeoutError.message, /toolCallTimeoutMs/, 'the rejection must name the offending field')
  assert.deepEqual(observations(project), [], 'a schema rejection must not reach the backend')

  const serverError = await bootRejection(bootComposition(project,
    composePatches(project, { overrides: { serverName: 'not a server name', failOnStartupError: true } }).patches))
  assert.match(serverError.message, /serverName/)
  assert.deepEqual(observations(project), [])
})

test('T01-E stays pending on a missing tools service and composes nothing', async () => {
  const project = makeProject('notools')
  const { patches } = composePatches(project, { entryName: sourceEntryPath })
  const error = await bootRejection(bootComposition(project, patches, { provideTools: false }))
  assert.match(error.message, /pending/, 'a missing injected service must be reported as pending')
  assert.match(error.message, /tools/, 'the diagnostic must name the missing service')
  assert.deepEqual(observations(project), [], 'activation must not happen without the injected service')
})

test('T01-F activation follows inject, not patch row order', async () => {
  const orderRow = { id: 't01-order-row', name: ORDER_PLUGIN, inject: ['tools'] }
  for (const extraRowsFirst of [false, true]) {
    const project = makeProject(extraRowsFirst ? 'order-first' : 'order-last')
    const { patches } = composePatches(project, { extraRows: [orderRow], extraRowsFirst, entryName: sourceEntryPath })
    const booted = await bootComposition(project, patches)
    try {
      const layout = extraRowsFirst ? 'unrelated row first' : 'unrelated row last'
      assert.equal(miliastraEntry(booted.ctx).fiber?.state, FIBER_ACTIVE, layout)
      assert.equal(observations(project).length, 1, layout)
    } finally {
      await booted.ctx.fiber.dispose()
    }
  }
})

test('T01-G distinguishes an absent backend, a declining backend, and a broken module', async () => {
  const absent = makeProject('absent')
  const absentBoot = await bootComposition(absent, composePatches(absent, { overrides: { backendModule: ABSENT_BACKEND } }).patches)
  try {
    assert.equal(miliastraEntry(absentBoot.ctx).fiber?.state, FIBER_ACTIVE, 'the policy permits activating without a backend')
    assert.deepEqual(absentBoot.tools.registered, [])
  } finally {
    await absentBoot.ctx.fiber.dispose()
  }

  const absentStrict = makeProject('absent-strict')
  const absentError = await bootRejection(bootComposition(absentStrict,
    composePatches(absentStrict, { overrides: { backendModule: ABSENT_BACKEND, failOnStartupError: true } }).patches))
  assert.match(absentError.message, /BACKEND_NOT_READY/)

  const declining = makeProject('declining')
  const decliningBoot = await bootComposition(declining,
    composePatches(declining, { overrides: { backendModule: DECLINING_BACKEND } }).patches)
  try {
    assert.equal(miliastraEntry(decliningBoot.ctx).fiber?.state, FIBER_ACTIVE)
    assert.deepEqual(decliningBoot.tools.registered, [], 'a declined backend must publish nothing')
    assert.equal(observations(declining, 't01-declining-backend.jsonl').length, 1)
  } finally {
    await decliningBoot.ctx.fiber.dispose()
  }

  const broken = makeProject('broken')
  const brokenError = await bootRejection(bootComposition(broken,
    composePatches(broken, { overrides: { backendModule: WRONG_SHAPE_BACKEND, failOnStartupError: true } }).patches))
  assert.match(brokenError.message, /BACKEND_MODULE_INVALID/,
    'a slot target that exists but is not a backend is a defect, never the benign absent state')
  assert.deepEqual(observations(broken), [])
})

test('T01-H reports a backend that throws instead of pretending it composed', async () => {
  const project = makeProject('throwing')
  const lenient = await bootComposition(project,
    composePatches(project, { overrides: { backendModule: THROWING_BACKEND } }).patches)
  try {
    assert.equal(miliastraEntry(lenient.ctx).fiber?.state, FIBER_ACTIVE)
    assert.deepEqual(lenient.tools.registered, [], 'a failed backend must publish nothing')
  } finally {
    await lenient.ctx.fiber.dispose()
  }

  const strict = makeProject('throwing-strict')
  const error = await bootRejection(bootComposition(strict,
    composePatches(strict, { overrides: { backendModule: THROWING_BACKEND, failOnStartupError: true } }).patches))
  assert.match(error.message, /reported state failed: fixture backend exploded while composing/,
    'the backend\'s own failure message must survive into the activation diagnostic')
})

test('T01-I defaultBackendSpecifier follows the entry module it is called from', async () => {
  assert.ok(existsSync(builtEntryPath), `${builtEntryPath} is missing — run \`pnpm build\` before this suite`)
  const source = await import(pathToFileURL(join(packageDir, 'src', 'composition.ts')).href) as {
    defaultBackendSpecifier: (url: string) => string
  }
  const built = await import(pathToFileURL(join(packageDir, 'lib', 'composition.js')).href) as {
    defaultBackendSpecifier: (url: string) => string
  }
  assert.equal(source.defaultBackendSpecifier(pathToFileURL(sourceEntryPath).href), './backend.ts')
  assert.equal(built.defaultBackendSpecifier(pathToFileURL(builtEntryPath).href), './backend.js')
})

test('T01-J the shipped bundle patch names this package and mounts one row', async () => {
  // Measured gap this closes: every other case resolves the row through an
  // explicit override or an absolute path, so a typo in the *shipped* `name:`
  // left the suite green. Read the artifact as shipped, unmodified.
  const manifest = JSON.parse(readFileSync(join(packageDir, 'package.json'), 'utf8')) as {
    name: string
    dsh?: { bundle?: { patch?: string } }
  }
  assert.equal(manifest.dsh?.bundle?.patch, './cordis.patch.yml', 'the bundle patch must be declared')
  const patches = loadOverlayPatches('miliastra-test', bundlePatchPath)
  const rows = patches.flatMap(patch => patch.insert ?? [])
  assert.equal(rows.length, 1, 'the bundle patch must insert exactly one row')
  const row = rows[0] as { id?: string, name?: string, inject?: unknown, config?: Record<string, unknown> }
  assert.equal(row.id, 'miliastra', 'the row id is the handle every profile override targets')
  assert.equal(row.name, manifest.name, 'the row must name this package, resolvable from the profile node_modules')
  assert.deepEqual(Object.keys(row.config ?? {}).sort(),
    ['projectRoot', 'pythonExecutable', 'serverName'],
    'the shipped row sets operator inputs only; every other field comes from the schema default')
  assert.equal(row.inject, undefined, 'injection comes from the plugin\'s own `inject` export, not a duplicated row field')
})
