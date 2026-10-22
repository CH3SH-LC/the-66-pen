/**
 * W15-PERMIT F2 — a ledger port whose child is gone must answer AT ONCE.
 *
 * THE DEFECT THIS LOCKS DOWN (measured, `measure/f2-timings-before.json`):
 *
 *   call 1 -> refused in 61 ms   (the 'exit' handler's failAll still found it outstanding)
 *   call 2 -> refused in 3010 ms (the WHOLE requestTimeoutMs)
 *   call 3 -> refused in 3006 ms (the whole requestTimeoutMs, again)
 *
 * `start()` returned `this.child` unconditionally, `this.child` is never nulled, and the
 * 'exit' event had already been delivered -- so `failAll` ran against an empty pending
 * map and every later request waited out its timer.  `src/index.ts` passes this port
 * `resolved.toolCallTimeoutMs`, and the shipped creation profile sets that to 900000, so
 * a dead ledger meant a **15-minute hang on every write**.  The routing patch is what puts
 * this port on the write path, which is why the fix lands with it.
 *
 * WHAT IS ASSERTED: every call after the child is gone rejects in well under the
 * request timeout, with `LEDGER_PORT_CLOSED` -- never `LEDGER_PORT_TIMEOUT`.  A timeout is
 * the defect, so it is asserted against explicitly.
 *
 * Suite name: this file lives in `tests/`, so `scripts/run-tests.mjs` discovers it with
 * the rest.  Nothing here touches the game, the editor, the helper, the bridge, the
 * authoring journal or the network: the only process started is the interpreter this
 * package already requires, and every project root is a fresh temp directory.
 */

import { after, before, test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { MiliastraLedgerPortError, MiliastraPythonLedgerPort } from '../src/ledger-port.ts'

/** This package's directory. */
const packageDir = fileURLToPath(new URL('..', import.meta.url))

/** Repository root; the pinned checkout and the project venv live under it. */
const repoRoot = resolve(packageDir, '..', '..')

/** The project's MCP interpreter — the same one the shipped overlay uses. */
const PYTHON = join(repoRoot, '.runtime', 'mcp-venv', 'Scripts', 'python.exe')

/** Bound the port is given.  Deliberately small so the defect is visible, and still an
 *  order of magnitude above the assertion below. */
const REQUEST_TIMEOUT_MS = 3_000

/** A call after the child is gone must settle well inside this. */
const IMMEDIATE_MS = 1_000

/** A ledger child that answers exactly one request and then exits. */
const EXITING_LEDGER = `import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    sys.stdout.write(json.dumps({'id': request.get('id'), 'ok': True, 'result': {'view': None}}) + '\\n')
    sys.stdout.flush()
    break
sys.exit(0)
`

/** Every temp root this suite created; removed in `after()`. */
const tempRoots: string[] = []

/** A temp project root; the ledger port's cwd, so `-m <module>` resolves here. */
function tempProject(label: string): string {
  const root = mkdtempSync(join(tmpdir(), `miliastra-w15-ledger-${label}-`))
  tempRoots.push(root)
  mkdirSync(join(root, 'ledger'), { recursive: true })
  return root
}

/** Build a port over a temp project root. */
function portFor(projectRoot: string, modulePath?: string): MiliastraPythonLedgerPort {
  return new MiliastraPythonLedgerPort({
    pythonExecutable: PYTHON,
    projectRoot,
    ledgerRoot: join(projectRoot, 'ledger'),
    serverName: 'w15fixture',
    requestTimeoutMs: REQUEST_TIMEOUT_MS,
    ...(modulePath === undefined ? {} : { modulePath }),
  })
}

/** Call once and report how it settled, with a real timer around the call. */
async function attempt(port: MiliastraPythonLedgerPort, operationId: string) {
  const startedAt = Date.now()
  let code: string | null = null
  let message = ''
  try {
    await port.readOperation(operationId)
  } catch (error) {
    const typed = error as MiliastraLedgerPortError
    code = typed.code ?? null
    message = typed.message
  }
  return { elapsedMs: Date.now() - startedAt, code, message }
}

/** Poll until `check` is true, or fail after `timeoutMs`. */
async function waitFor(check: () => boolean, timeoutMs: number, label: string): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (check()) return
    await new Promise<void>(resolve => { setTimeout(resolve, 20) })
  }
  assert.fail(`timed out after ${timeoutMs}ms waiting for ${label}`)
}

before(() => {
  assert.ok(existsSync(PYTHON), `${PYTHON} is missing: this offline suite needs the project's MCP interpreter`)
})

after(() => {
  for (const root of tempRoots) rmSync(root, { recursive: true, force: true })
})

test('W15-F2-A a child that dies before answering refuses every call at once', async () => {
  // No `backend` package in this project root, so `python -m backend.ledger_port` exits
  // (code 1) in about 60 ms -- the exact configuration the defect was measured in.
  const project = tempProject('dead-child')
  const port = portFor(project)
  try {
    const first = await attempt(port, 'w15-f2-a-1')
    assert.equal(first.code, 'LEDGER_PORT_CLOSED', `first call: ${first.message}`)

    for (const n of [2, 3]) {
      const later = await attempt(port, `w15-f2-a-${n}`)
      assert.equal(later.code, 'LEDGER_PORT_CLOSED',
        `call ${n} must be refused as a closed port, not waited out: ${later.message}`)
      assert.notEqual(later.code, 'LEDGER_PORT_TIMEOUT',
        `call ${n} timed out instead of failing fast; the port reused its dead child`)
      assert.ok(later.elapsedMs < IMMEDIATE_MS,
        `call ${n} took ${later.elapsedMs} ms; a port whose child is gone must answer at once`)
    }
  } finally {
    await port.dispose()
  }
})

test('W15-F2-B a child that answered once and then exited refuses later calls at once', async () => {
  const project = tempProject('exiting-child')
  writeFileSync(join(project, 'w15_exiting_ledger.py'), EXITING_LEDGER, 'utf8')
  const port = portFor(project, 'w15_exiting_ledger')
  try {
    const first = await attempt(port, 'w15-f2-b-1')
    assert.equal(first.code, null, `the first call must be served: ${first.message}`)

    // The child answers and exits; wait until the port has observed that.
    await waitFor(() => !port.running, 3_000, 'the ledger child to exit')

    for (const n of [2, 3]) {
      const later = await attempt(port, `w15-f2-b-${n}`)
      assert.equal(later.code, 'LEDGER_PORT_CLOSED', `call ${n}: ${later.message}`)
      assert.ok(later.elapsedMs < IMMEDIATE_MS,
        `call ${n} took ${later.elapsedMs} ms; a port whose child has exited must answer at once`)
    }
  } finally {
    await port.dispose()
  }
})

test('W15-F2-C a disposed port refuses at once too', async () => {
  const project = tempProject('disposed')
  writeFileSync(join(project, 'w15_exiting_ledger.py'), EXITING_LEDGER, 'utf8')
  const port = portFor(project, 'w15_exiting_ledger')
  await attempt(port, 'w15-f2-c-1')
  await port.dispose()
  const after_dispose = await attempt(port, 'w15-f2-c-2')
  assert.equal(after_dispose.code, 'LEDGER_PORT_CLOSED', after_dispose.message)
  assert.ok(after_dispose.elapsedMs < IMMEDIATE_MS,
    `a disposed port took ${after_dispose.elapsedMs} ms to refuse`)
})
