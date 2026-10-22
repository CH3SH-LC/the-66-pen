/**
 * Fail when something the package needs is not in `package.json` `files[]`.
 *
 * WHY: `files[]` is an allow-list, and npm drops silently. A directory that exists in
 * the checkout but is missing from the list produces a tarball that installs cleanly
 * and is missing an artifact at run time -- the failure lands in someone's profile, not
 * in CI. The G01 contract found exactly this: `plugins/miliastra/contracts/` (the
 * tool/state contract, its schemas, its TypeScript mirror and its offline validator)
 * was not in the list, so a packed tarball omitted the contract the plugin is the home
 * of (decision O-7: "either ship it or declare it, but not by omission").
 *
 * `scripts/check-build.mjs` verifies the other half -- that the paths the manifest
 * promises exist on disk. This check is the complement: every path the package NEEDS is
 * promised by `files[]`.
 *
 * What "needs" means here, in this order:
 *   1. every non-wildcard `exports` target, and `dsh.bundle.patch` -- derived from the
 *      manifest, so a new entry point is covered the moment it is declared;
 *   2. DECLARED_REQUIREMENTS below -- the entries no manifest field can express. Each
 *      one carries its reason, so dropping one is an omission rather than an accident.
 *
 * Usage: node scripts/check-package-files.mjs [--package-dir <dir>]
 */
import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Paths the package needs that no manifest field declares, with the reason each is
 * needed. Adding one here is a decision; forgetting one in `files[]` is a bug.
 */
const DECLARED_REQUIREMENTS = [
  {
    path: 'src',
    reason: 'the package ships as source plus a reproducible build, and exports["./src/*"] promises the family',
  },
  {
    path: 'contracts',
    reason: 'the G01 tool/state contract, its schemas, its TypeScript mirror and its offline validator (contract.json, validate.py); the plugin is this contract\'s home',
  },
]

const argumentIndex = process.argv.indexOf('--package-dir')
const packageDir = argumentIndex === -1
  ? resolve(dirname(fileURLToPath(import.meta.url)), '..')
  : resolve(process.argv[argumentIndex + 1])
const manifest = JSON.parse(readFileSync(join(packageDir, 'package.json'), 'utf8'))
const published = manifest.files ?? []
const problems = []

/**
 * npm publishes these even when `files[]` omits them, so `files[]` cannot be blamed
 * for their absence. https://docs.npmjs.com/cli/configuring-npm/package-json#files
 * @param relativePath - path relative to the package directory.
 * @returns whether npm includes the path regardless of `files[]`.
 */
function alwaysPublished(relativePath) {
  if (relativePath === 'package.json') return true
  return /^(readme|licen[cs]e|changelog)/i.test(relativePath)
}

/**
 * Compile one `files[]` pattern to a regular expression over relative paths.
 * Supports the npm subset actually used here: a double star followed by a slash spans
 * zero or more directories, a bare double star spans anything, a single star stays
 * inside one path segment and a question mark is one non-separator character.
 * @param pattern - one entry of the manifest `files` array.
 * @returns a regular expression anchored to the whole relative path.
 */
function globToRegExp(pattern) {
  let source = ''
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index]
    if (character === '*') {
      if (pattern[index + 1] !== '*') {
        source += '[^/]*'
      } else if (pattern[index + 2] === '/') {
        source += '(?:.*/)?'
        index += 2
      } else {
        source += '.*'
        index += 1
      }
      continue
    }
    if (character === '?') {
      source += '[^/]'
      continue
    }
    source += character.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  }
  return new RegExp(`^${source}$`)
}

/**
 * Whether `files[]` would include a path.
 * A bare name is a directory: npm includes everything beneath it, which is why
 * `"src"` alone ships the whole tree and `"contracts"` alone ships the contract.
 * @param relativePath - path relative to the package directory.
 * @param patterns - the raw manifest `files` array.
 * @returns whether at least one pattern covers the path.
 */
function covered(relativePath, patterns) {
  for (const raw of patterns) {
    const pattern = raw.replace(/^\.\//, '').replace(/\/+$/, '')
    if (pattern === relativePath) return true
    if (!pattern.includes('*') && !pattern.includes('?')) {
      if (relativePath.startsWith(`${pattern}/`)) return true
      continue
    }
    if (globToRegExp(pattern).test(relativePath)) return true
    // A trailing glob covers the whole tree beneath it, the named directory included:
    // `contracts/**` ships the contract just as `contracts` does.
    if (pattern.endsWith('**')) {
      const segments = pattern.split('/')
      const firstWildcard = segments.findIndex(segment => segment.includes('*'))
      const prefix = segments.slice(0, firstWildcard === -1 ? segments.length : firstWildcard).join('/')
      if (prefix !== '' && (relativePath === prefix || relativePath.startsWith(`${prefix}/`))) return true
    }
  }
  return false
}

/**
 * Collect every `exports` target that names one artifact.
 * Wildcard subpaths (`./src/*`) describe a family, not a file; the family's directory
 * is covered by DECLARED_REQUIREMENTS instead.
 * @param exports - the manifest's `exports` field.
 * @returns pairs of the manifest label and the relative target path.
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
      if (typeof target === 'string' && !target.includes('*')) {
        targets.push([`exports["${subpath}"].${condition}`, target])
      }
    }
  }
  return targets
}

const required = []
for (const [label, target] of exportTargets(manifest.exports)) {
  required.push({ path: target, reason: `promised by ${label}`, kind: 'file' })
}
if (typeof manifest.dsh?.bundle?.patch === 'string') {
  required.push({
    path: manifest.dsh.bundle.patch,
    reason: 'promised by dsh.bundle.patch, the layer this package inserts into a profile',
    kind: 'file',
  })
}
for (const entry of DECLARED_REQUIREMENTS) required.push({ ...entry, kind: 'either' })

const seen = new Set()
for (const { path: rawPath, reason, kind } of required) {
  const relativePath = rawPath.replace(/^\.\//, '')
  if (seen.has(relativePath)) continue
  seen.add(relativePath)

  const absolute = join(packageDir, relativePath)
  if (!existsSync(absolute)) {
    problems.push(`${relativePath}: needed but not present in the package directory (${reason})`)
    continue
  }
  if (kind === 'file' && !statSync(absolute).isFile()) {
    problems.push(`${relativePath}: needed as a file but it is a directory (${reason})`)
    continue
  }
  if (alwaysPublished(relativePath)) continue
  if (!covered(relativePath, published)) {
    problems.push(
      `${relativePath}: present on disk but missing from package.json files[] — a packed `
      + `tarball would omit it (${reason})`,
    )
  }
}

if (problems.length > 0) {
  process.stderr.write(
    `check-package-files: ${problems.length} problem(s)\n`
    + `${problems.map(problem => `  - ${problem}`).join('\n')}\n`,
  )
  process.exit(1)
}
process.stdout.write(`check-package-files: ok (${seen.size} required path(s) covered by files[])\n`)
