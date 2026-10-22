/**
 * W02 product-profile wiring suite.
 *
 * WHAT THIS SUITE IS FOR. `config/mw-entity-create.patch.yml` gives a real DS
 * session the bounded scene business tools and disables everything that could
 * touch a shell, the filesystem, processes, subagents or the network. What it
 * does NOT do — the C2 gap this suite closes — is mount `@miliastra/dsh-miliastra`,
 * the plugin that composes the business backend behind the write gate. This
 * suite proves the product profile now does, and that mounting it changes
 * nothing about the restriction.
 *
 * HOW IT IS REAL. The profile is not read as text and pattern-matched. It is
 * composed exactly the way `dsh` composes it: the shipped bundle patches
 * (`packages/bundle/base`, `packages/bundle/headless`) are read from the pinned
 * checkout, the profile's own patch file and the project overlays are layered on
 * top in argv order, and the whole stack is flattened by the include plugin's
 * own `applyEntryPatches` through `renderConfigDump` — the same call `boot()`
 * makes. The one case that needs a live tree then boots the REAL Loader with the
 * product profile's own insert entry and lets it settle.
 *
 * WHAT IT DOES NOT CLAIM. No MCP server starts in the composition cases, no
 * model runs, no game, editor, helper or bridge is touched, and no `tools/call`
 * is dispatched. The tool table and the write gate over a live MCP connection
 * are `backend-connection.spec.ts`'s rows (T02-A..T02-F) and are not re-claimed
 * here.
 *
 * @module @miliastra/dsh-miliastra/tests/profile-wiring.spec
 */

import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { boot, loadOverlayPatches, renderConfigDump } from '@deepseek-ai/dsh-app-boot'
import { applyEntryPatches } from '@deepseek-ai/cordis-plugin-include'
import type { Context } from '@deepseek-ai/cordis'
import type { PatchOptions } from '@deepseek-ai/cordis-plugin-include'

/** This package's directory (`plugins/miliastra`). */
const packageDir = fileURLToPath(new URL('..', import.meta.url))

/** Repository root. */
const repoRoot = resolve(packageDir, '..', '..')

/** The pinned checkout. */
const vendor = join(repoRoot, 'vendor', 'deepseek-harness')

/** Project overlay: the restriction (disables + the raw business MCP row). */
const RESTRICTION_PATCH = join(repoRoot, 'config', 'mw-entity-create.patch.yml')

/** Project overlay: the product wiring under test (mounts the plugin). */
const WIRING_PATCH = join(repoRoot, 'config', 'mw-entity-create.miliastra.patch.yml')

/** The plugin row's server namespace, as written in the wiring patch. */
const SERVER_NAME = 'miliastra'

/** Ids the product profile must leave disabled. The C2 boundary, verbatim. */
const MUST_BE_DISABLED = Object.freeze([
  'tool-bash',
  'tool-pwsh',
  'tool-jobs',
  'tool-fs',
  'tool-fs-search',
  'tool-skill',
  'tool-subagent',
  'tool-subagent-control',
  'tool-subagent-list-agents',
  'tool-subagent-fork',
  'tool-workflow',
  'tool-web',
  'tool-todo',
  'tool-goal',
  'tool-ralph',
  'code-runtime',
])

/**
 * Model-facing TOOL packages that carry a shell, filesystem, process, subagent
 * or network capability. Checked as a second, name-based net: a row can be
 * renamed while its id stays, so the id list alone is not enough.
 *
 * Deliberately scoped to `dsh-tool-*`. The restriction this profile claims is a
 * TOOL-surface restriction (MCP-BUSINESS-CONTRACT.md section 7): the sandbox,
 * subagent, workflow and web *service* rows stay enabled in the base bundle, and
 * disabling them would break unrelated wiring. What must be off is every tool
 * that would let the session reach through those services.
 */
const FORBIDDEN_PACKAGE_PATTERNS = Object.freeze([
  /dsh-tool-bash/,
  /dsh-tool-pwsh/,
  /dsh-tool-jobs/,
  /dsh-tool-fs(-search)?$/,
  /dsh-tool-subagent/,
  /dsh-tool-workflow/,
  /dsh-tool-web$/,
  /dsh-tool-skill/,
  /dsh-tool-todo/,
  /dsh-tool-goal/,
  /dsh-tool-ralph/,
  /dsh-tool-present/,
  /dsh-tool-cordis/,
])

/** Temp dirs this suite created; removed in `after()`. */
const tempRoots: string[] = []

/** One row of the composed entry list after the dump is re-parsed. */
interface DumpRow {
  readonly id: string
  readonly name?: string
  readonly disabled: boolean
  /** Nesting depth, 0 for top-level rows. */
  readonly depth: number
}

/**
 * Compose the product profile exactly the way `dsh` composes it.
 *
 * The profile root is an empty entry list; every layer is a patch list applied
 * in order — the shipped `base` bundle, the shipped `headless` bundle, the
 * profile's own patch file (empty here) and then the project overlays in argv
 * order. `applyEntryPatches` is the include plugin's own patch algorithm, the
 * same single call `boot()` makes, so a disagreement between this composition
 * and a real run is a disagreement about the files, not about the reader.
 *
 * @param withWiring - include the product wiring overlay, or stop at the
 * restriction overlay (so the same reader can show what the wiring adds).
 * @returns the composed, rendered tree.
 */
function composeProfile(withWiring: boolean): string {
  return renderConfigDump('miliastra-w02', join(vendor, 'packages', 'bundle', 'base', 'cordis.patch.yml'), [
    { label: 'composed', patches: profilePatches(withWiring) },
  ])
}

/**
 * The profile's patch stack, in `dsh` application order.
 *
 * @param withWiring - include the product wiring overlay last.
 * @returns the ordered patch list.
 */
function profilePatches(withWiring: boolean): PatchOptions[] {
  const patches: PatchOptions[] = [
    ...loadOverlayPatches('miliastra-w02', join(vendor, 'packages', 'bundle', 'base', 'cordis.patch.yml')),
    ...loadOverlayPatches('miliastra-w02', join(vendor, 'packages', 'bundle', 'headless', 'cordis.patch.yml')),
    ...loadOverlayPatches('miliastra-w02', RESTRICTION_PATCH),
  ]
  if (withWiring) patches.push(...loadOverlayPatches('miliastra-w02', WIRING_PATCH))
  return patches
}

/**
 * Flatten a composed tree into rows.
 *
 * @param entries - the composed top-level entry list.
 * @returns every row, with its nesting depth.
 */
function composedRows(entries: readonly Record<string, unknown>[]): DumpRow[] {
  const rows: DumpRow[] = []
  const visit = (entry: Record<string, unknown>, depth: number): void => {
    const id = typeof entry.id === 'string' ? entry.id : undefined
    if (id !== undefined) {
      rows.push({
        id,
        name: typeof entry.name === 'string' ? entry.name : undefined,
        disabled: entry.disabled === true,
        depth,
      })
    }
    const config = entry.config
    if (Array.isArray(config)) for (const child of config) if (child !== null && typeof child === 'object') visit(child as Record<string, unknown>, depth + 1)
    const insert = entry.insert
    if (Array.isArray(insert)) for (const child of insert) if (child !== null && typeof child === 'object') visit(child as Record<string, unknown>, depth + 1)
  }
  for (const entry of entries) visit(entry, 0)
  return rows
}

/**
 * Compose the profile layers and return the entry list `boot()` would mount.
 *
 * @param withWiring - include the product wiring overlay.
 * @returns the composed top-level entry list.
 */
function composeEntries(withWiring: boolean): Array<Record<string, unknown>> {
  return applyEntryPatches([], profilePatches(withWiring) as never, () => {}) as unknown as Array<Record<string, unknown>>
}

/**
 * Find the row carrying `id` — the top-level one when both a top-level and a
 * nested row share it, which is the id the patch layers address.
 *
 * @param rows - flattened rows.
 * @param id - row id.
 * @returns the shallowest row with that id.
 */
function rowById(rows: readonly DumpRow[], id: string): DumpRow | undefined {
  let best: DumpRow | undefined
  for (const row of rows) {
    if (row.id !== id) continue
    if (best === undefined || row.depth < best.depth) best = row
  }
  return best
}

after(() => {
  for (const root of tempRoots) rmSync(root, { recursive: true, force: true })
})

// ---- cases -----------------------------------------------------------------

test('W02-A the wiring overlay is present and mounts the plugin row', () => {
  assert.ok(existsSync(WIRING_PATCH), `${WIRING_PATCH} is missing: the product profile does not mount the plugin`)

  const rows = composedRows(composeEntries(true))
  const plugin = rowById(rows, 'miliastra')
  assert.ok(plugin !== undefined, 'the composed profile must carry a top-level row with id `miliastra`')
  assert.equal(plugin!.depth, 0, 'the plugin row must be top level, not nested in a group')
  assert.equal(plugin!.disabled, false, 'the plugin row must be live')
  assert.ok(
    plugin!.name !== undefined
      && (plugin!.name.toLowerCase().includes('miliastra')),
    `the plugin row must name the Miliastra package or the plugin entry, saw ${String(plugin!.name)}`,
  )
})

test('W02-B the raw business MCP row is superseded, not doubled', () => {
  const withoutWiring = composedRows(composeEntries(false))
  const withWiring = composedRows(composeEntries(true))

  const rawBefore = rowById(withoutWiring, 'mcp-mwentities')
  assert.ok(rawBefore !== undefined, 'the restriction overlay must still insert the raw business MCP row')
  assert.equal(rawBefore!.disabled, false, 'the raw row starts live before the wiring overlay')

  const rawAfter = rowById(withWiring, 'mcp-mwentities')
  assert.ok(rawAfter !== undefined, 'the wiring overlay targets an existing row; it must not delete it silently')
  assert.equal(rawAfter!.disabled, true,
    'two MCP connections to one business server would publish the same tools twice under two namespaces')

  // Exactly one live row composes a business MCP connection: the plugin.
  const liveBusiness = withWiring.filter(row => row.disabled === false
    && (row.id === 'miliastra'
      || (row.name !== undefined && row.name.includes('dsh-mcp-client'))))
  assert.equal(liveBusiness.length, 1,
    `exactly one live business MCP row must remain, saw ${liveBusiness.map(row => row.id).join(', ')}`)
  assert.equal(liveBusiness[0]!.id, 'miliastra', 'the surviving business row must be the plugin, not the raw client')
})

test('W02-C the restricted boundary survives the wiring overlay', () => {
  const rows = composedRows(composeEntries(true))
  for (const id of MUST_BE_DISABLED) {
    const row = rowById(rows, id)
    assert.ok(row !== undefined, `boundary row ${id} is missing from the composed profile`)
    assert.equal(row!.disabled, true, `boundary row ${id} is NOT disabled in the product profile`)
  }
})

test('W02-D no enabled row can reach a shell, the filesystem, a subagent or the network', () => {
  const rows = composedRows(composeEntries(true))
  const offenders: string[] = []
  for (const row of rows) {
    if (row.disabled) continue
    if (row.name === undefined) continue
    for (const pattern of FORBIDDEN_PACKAGE_PATTERNS) {
      if (pattern.test(row.name)) {
        offenders.push(`${row.id} -> ${row.name} (${pattern.source})`)
        break
      }
    }
  }
  assert.deepEqual(offenders, [], `enabled rows reach a forbidden capability: ${offenders.join('; ')}`)
})

test('W02-E the product profile\'s own row boots through the real Loader', async () => {
  // Take the row verbatim from the product profile, so this case cannot drift
  // from the file the operator actually runs: read the wiring overlay's insert
  // list through the real patch dialect and re-mount exactly that entry.
  const wiring = loadOverlayPatches('miliastra-w02', WIRING_PATCH)
  const inserted = wiring.flatMap(entry => entry.insert ?? []).filter(entry => entry.id === 'miliastra')
  assert.equal(inserted.length, 1, 'the wiring overlay must insert exactly one `miliastra` row')

  const row = inserted[0]!
  const config = row.config as Record<string, unknown>
  const project = mkdtempSync(join(tmpdir(), 'miliastra-w02-project-'))
  tempRoots.push(project)
  // The plugin proves `backendRoot` (default `<projectRoot>/backend`) exists
  // before it registers anything. Create it but leave it empty: the fixed entry
  // file is missing, so the honest outcome is a mounted row that reports the
  // backend as failed rather than a row that activates with tools.
  mkdirSync(join(project, 'backend'), { recursive: true })
  const python = process.env.MILIASTRA_PYTHON
  assert.ok(python !== undefined && python !== '', 'MILIASTRA_PYTHON must be set for this case')
  // The row deliberately carries environment expressions (no baked checkout
  // path), so this case supplies them the way the launcher does. No backend is
  // installed in the temp project, and `failOnStartupError` stays false so the
  // honest outcome is a mounted row that reports `unavailable` — activation
  // must not spawn a process to discover that.
  const resolvedRow: Record<string, unknown> = {
    ...row,
    name: pathToFileURL(join(packageDir, 'src', 'index.ts')).href,
    config: { ...config, projectRoot: project, pythonExecutable: python, failOnStartupError: false },
  }

  class FakeTools {
    readonly registered: string[] = []
    register(definition: { name: string }) {
      this.registered.push(definition.name)
      return () => {
        const index = this.registered.indexOf(definition.name)
        if (index >= 0) this.registered.splice(index, 1)
      }
    }
  }

  const root = mkdtempSync(join(tmpdir(), 'miliastra-w02-root-'))
  tempRoots.push(root)
  const rootConfig = join(root, 'cordis.yml')
  writeFileSync(rootConfig, '# miliastra W02 fixture root: an empty entry list\n[]\n')
  const tools = new FakeTools()
  const ctx = await boot(
    'miliastra-w02',
    rootConfig,
    [{ insert: [resolvedRow] } as unknown as PatchOptions],
    (hostCtx: Context) => { hostCtx.provide('tools', tools) },
    pathToFileURL(join(packageDir, 'package.json')).href,
  )
  try {
    const entries = [...ctx.loader.entries()].filter(entry => entry.options.id === 'miliastra')
    assert.equal(entries.length, 1, 'the Loader must mount exactly one `miliastra` entry from the product row')
    // The row mounted and settled: a row the Loader could not import would have
    // failed the boot, and a row whose plugin never applied would still be
    // PENDING. Either way this case would not reach the assertions below.
    assert.notEqual((entries[0] as unknown as { fiber?: { state?: number } }).fiber?.state, 4,
      'a row that failed to load must not be reported as DONE')
  } finally {
    await ctx.fiber.dispose()
  }
})
