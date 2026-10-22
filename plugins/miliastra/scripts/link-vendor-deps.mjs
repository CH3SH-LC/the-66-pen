/**
 * Create this package's local `node_modules` links against the pinned dsh
 * checkout in `vendor/deepseek-harness`.
 *
 * WHY THIS EXISTS: the Cordis Loader imports a plugin entry by module
 * specifier, so the plugin's own bare imports (`@deepseek-ai/schemastery`, and
 * the test-only Loader/app-boot packages) must resolve from *this* package's
 * location. The project has no root package.json and no pnpm workspace, and the
 * pinned checkout's dependencies are already materialized on disk, so linking
 * to them is a local, offline, reproducible substitute for `pnpm install`.
 *
 * WHAT IT DOES NOT DO: no network access, no global install, no writes outside
 * `plugins/miliastra/node_modules`, no change to the pinned checkout. Every link
 * is a Windows directory junction (or an ESM-visible directory symlink off
 * Windows), which Node and Vite both resolve to the real path, so the plugin
 * shares the checkout's single copy of each module instead of a duplicate.
 * `node_modules/` is gitignored; re-run this script after a fresh clone or when
 * the pinned checkout moves.
 *
 * Usage: node plugins/miliastra/scripts/link-vendor-deps.mjs [--check]
 *   --check  report link state and exit non-zero when anything is missing.
 */
import { existsSync, lstatSync, mkdirSync, readlinkSync, rmSync, symlinkSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const packageDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(packageDir, '..', '..')
const vendor = join(repoRoot, 'vendor', 'deepseek-harness')

/** `[link name under node_modules, absolute target directory]`. */
const LINKS = [
  // Runtime dependency of src/config.ts (the plugin's Config schema).
  ['@deepseek-ai/schemastery', join(vendor, 'vendor', 'schemastery')],
  // Peer: the framework itself. Imported for types here; the Loader that loads
  // this plugin must be the same instance, which real-path resolution preserves.
  ['@deepseek-ai/cordis', join(vendor, 'vendor', 'cordis')],
  // Type-only import in the loader-composition spec (the patch-list dialect).
  ['@deepseek-ai/cordis-plugin-include', join(vendor, 'vendor', 'include')],
  // The host boot entry the loader-composition spec composes with. Its own
  // dependencies (Loader, Include, Group, js-yaml, cordis) resolve from its own
  // node_modules in the pinned checkout, so none of them need a link here.
  ['@deepseek-ai/dsh-app-boot', join(vendor, 'packages', 'boot', 'app-boot')],
  // Runtime dependency of src/backend.ts: the bridge spawns this MCP client and
  // speaks the real protocol to the backend it starts. Measured 2026-10-02:
  // without this line the junction exists on one machine and a fresh clone
  // silently composes no backend at all, because --check only validates the
  // links named here.
  ['@deepseek-ai/dsh-mcp-client', join(vendor, 'packages', 'mcp', 'mcp-client')],
  // Build tooling, from the checkout's own devDependencies.
  ['typescript', join(vendor, 'node_modules', 'typescript')],
  ['@types/node', join(vendor, 'node_modules', '@types', 'node')],
]

const checkOnly = process.argv.includes('--check')
const nodeModules = join(packageDir, 'node_modules')
const problems = []

function linkTarget(link) {
  try {
    const stat = lstatSync(link)
    if (!stat.isSymbolicLink() && !stat.isDirectory()) return undefined
    // Directory junctions read back as absolute paths; symlinks may be relative.
    return resolve(dirname(link), readlinkSync(link))
  } catch {
    return undefined
  }
}

for (const [name, target] of LINKS) {
  if (!existsSync(join(target, 'package.json'))) {
    problems.push(`${name}: vendor target missing (${target}); is the pinned checkout complete?`)
    continue
  }
  const link = join(nodeModules, name)
  const existing = linkTarget(link)
  if (existing !== undefined) {
    if (existing === target) continue
    problems.push(`${name}: points at ${existing}, expected ${target}`)
    continue
  }
  if (existsSync(link)) {
    problems.push(`${name}: ${link} exists and is not a link; remove it manually`)
    continue
  }
  if (checkOnly) {
    problems.push(`${name}: link missing (${relative(packageDir, link)})`)
    continue
  }
  mkdirSync(dirname(link), { recursive: true })
  symlinkSync(target, link, 'junction')
  process.stdout.write(`linked ${name} -> ${relative(packageDir, target)}\n`)
}

if (problems.length > 0) {
  process.stderr.write(`link-vendor-deps: ${problems.length} problem(s)\n${problems.map(line => `  - ${line}`).join('\n')}\n`)
  process.exit(1)
}
process.stdout.write(`link-vendor-deps: ok (${LINKS.length} links)${checkOnly ? ' [check]' : ''}\n`)
void pathToFileURL
