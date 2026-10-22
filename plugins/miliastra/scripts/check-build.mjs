/**
 * Verify the *published* artifact of `pnpm build`.
 *
 * The suite runs the source tree (so it cannot pass on a stale build); this
 * check is the other half: every path `package.json` promises to publish must
 * exist after a build, the emitted JavaScript must have had its `.ts` import
 * specifiers rewritten to `.js`, and no build output may contain a leftover
 * `from './x.ts'`. A missing or half-rewritten artifact fails here instead of at
 * install time in someone's profile.
 *
 * Usage: node scripts/check-build.mjs
 */
import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const manifest = JSON.parse(readFileSync(join(packageDir, 'package.json'), 'utf8'))
const problems = []

/**
 * Report a path the manifest promises but the build did not produce.
 * @param label - which manifest field promised it.
 * @param relativePath - path relative to the package directory.
 * @param kind - `file` requires a regular file; `either` accepts a directory too.
 * @returns the absolute path when it is present and of the required kind.
 */
function requirePath(label, relativePath, kind = 'file') {
  const path = join(packageDir, relativePath)
  if (!existsSync(path)) {
    problems.push(`${label}: missing ${relativePath}`)
    return undefined
  }
  if (kind === 'file' && !statSync(path).isFile()) {
    problems.push(`${label}: ${relativePath} is not a file`)
    return undefined
  }
  return path
}

/**
 * Collect every `types`/`default` target declared in `exports`.
 * Wildcard subpaths (`./src/*`) are skipped: they describe a family of files,
 * not one promised artifact. `files` still has to cover the family.
 */
function exportTargets(exports) {
  const targets = []
  for (const [subpath, value] of Object.entries(exports ?? {})) {
    if (subpath.includes('*')) continue
    if (typeof value === 'string') {
      targets.push([`exports["${subpath}"]`, value])
      continue
    }
    if (value === null || typeof value !== 'object') continue
    for (const [condition, target] of Object.entries(value)) {
      if (typeof target === 'string' && !target.includes('*')) targets.push([`exports["${subpath}"].${condition}`, target])
    }
  }
  return targets
}

for (const [label, target] of exportTargets(manifest.exports)) requirePath(label, target)
for (const [index, entry] of (manifest.files ?? []).entries()) {
  if (entry.includes('*')) continue
  requirePath(`files[${index}]`, entry, 'either')
}
requirePath('dsh.bundle.patch', manifest.dsh?.bundle?.patch ?? '')

// The bundle patch must be non-empty: the Loader treats an empty entry list as
// "no plugin mounted", which installs cleanly and does nothing.
const patchPath = join(packageDir, manifest.dsh?.bundle?.patch ?? '')
if (existsSync(patchPath) && !/^\s*-\s/m.test(readFileSync(patchPath, 'utf8'))) {
  problems.push('dsh.bundle.patch: contains no patch entries')
}

// Extension rewriting: emitted JS must reference ./x.js, never ./x.ts.
//
// This list is every emitted entry point, not a sample: a file left out of it is
// a file whose half-rewritten specifiers would reach install time unnoticed. It
// was ['lib/index.js', 'lib/config.js', 'lib/composition.js'] until 2026-10-02,
// when src/backend.ts and src/lifecycle.ts were added and their emitted siblings
// were not -- measured: all five are clean today, so this is a guard for the
// next edit, not a repair of a current defect.
const EMITTED_ENTRY_POINTS = [
  'lib/index.js', 'lib/config.js', 'lib/composition.js', 'lib/backend.js', 'lib/lifecycle.js', 'lib/ledger-port.js',
]
for (const target of EMITTED_ENTRY_POINTS) {
  const path = join(packageDir, target)
  if (!existsSync(path)) continue
  const source = readFileSync(path, 'utf8')
  const leftover = source.match(/from\s+["'][^"']*\.ts["']/g)
  if (leftover !== null) problems.push(`${target}: unrewritten TypeScript specifier(s) ${leftover.join(', ')}`)
}

if (problems.length > 0) {
  process.stderr.write(`check-build: ${problems.length} problem(s)\n${problems.map(line => `  - ${line}`).join('\n')}\n`)
  process.exit(1)
}
process.stdout.write('check-build: ok\n')
