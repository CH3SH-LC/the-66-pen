/**
 * Run this package's specs with Node's built-in test runner.
 *
 * WHY A LAUNCHER: `node --test <dir>` treats the argument as a file to execute
 * (Node 24), and `node --test` with no argument only discovers `.test.*` /
 * `test-*.*` names — neither picks up `tests/*.spec.ts`, which is the name the
 * T01 task page fixes. This resolves the spec list itself so that
 * `pnpm test` and `pnpm test -- tests/loader-composition.spec.ts` both run
 * exactly the requested files, on every platform, without shell globbing.
 *
 * It requires the Node type-stripping feature: the specs and the package source
 * they compose are loaded as `.ts` with no build step (the build is verified
 * separately by scripts/check-build.mjs). Node 22.18+ / 24.x enables it by
 * default; the guard below fails loudly rather than running something else.
 *
 * Usage: node scripts/run-tests.mjs [spec-file ...]
 */
import { readdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const testsDir = join(packageDir, 'tests')

if (!process.features.typescript) {
  process.stderr.write(
    `run-tests: this Node (${process.version}) does not strip TypeScript types, so the .ts specs cannot load.\n`
    + 'run-tests: use Node 22.18+ (24.x recommended), where type stripping is on by default.\n',
  )
  process.exit(1)
}

const requested = process.argv.slice(2).filter(argument => !argument.startsWith('-'))
const specs = requested.length > 0
  ? requested.map(argument => resolve(packageDir, argument))
  : readdirSync(testsDir, { withFileTypes: true })
    .filter(entry => entry.isFile() && entry.name.endsWith('.spec.ts'))
    .map(entry => join(testsDir, entry.name))
    .sort()

if (specs.length === 0) {
  process.stderr.write('run-tests: no spec files found\n')
  process.exit(1)
}

process.stdout.write(`run-tests: node ${process.version}, ${specs.length} spec file(s)\n`)
for (const spec of specs) process.stdout.write(`run-tests:   ${spec}\n`)

const result = spawnSync(process.execPath, ['--test', ...specs], { cwd: packageDir, stdio: 'inherit' })
process.exit(result.status ?? 1)
