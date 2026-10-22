/**
 * T03 / DS-07 — the Cordis-side adapter for the real business ledger port.
 *
 * ## What this is
 *
 * The one implementation of {@link MiliastraBusinessLedgerPort} that talks to
 * the real ledger. It owns a single child process — `python -m
 * backend.ledger_port --root <ledgerRoot>` — and speaks newline-delimited JSON
 * to it. Every answer the lifecycle controller reads therefore comes from
 * `backend/operation_state.py`'s `OperationLedger`, i.e. from the claim /
 * record / receipt files on disk. Nothing here computes a state, a verdict or a
 * receipt: the adapter is a transport, and the port on the other end is a
 * projection.
 *
 * ## Why a child process rather than an in-process fake
 *
 * The lifecycle module was deliberately kept out of `src/index.ts` while the
 * only port available was `fixtures/t03-fake-ledger.ts`. Mounting that fixture
 * in production would have been a licence to *invent* ledger rows. This adapter
 * exists so `index.ts` can mount a real ledger instead: if the Python service
 * cannot be reached, every read throws, the lifecycle turns that into
 * `LIFECYCLE_LEDGER_UNAVAILABLE`, and `beginOperation` refuses rather than
 * guessing. A broken ledger is an error, never a silent success.
 *
 * ## What it deliberately does not do
 *
 * - It does not start the game, the editor, the elevated helper or the bridge.
 *   It spawns exactly one process, and that process (`backend/ledger_port.py`)
 *   reads and writes only inside the explicit `ledgerRoot` directory.
 * - It does not default `ledgerRoot`. `backend/operation_state.OperationLedger`
 *   has no ROOT constant on purpose; this adapter keeps that property by
 *   requiring the root from its caller. There is no path by which it reaches the
 *   real author journal by accident.
 * - It does not retry a request. A timed-out or failed call is reported to the
 *   caller; re-sending an unknown write is T06's reconcile path, not a
 *   transport retry (G01 D22).
 *
 * ## Lifecycle ownership
 *
 * The child process is an `own` {@link MiliastraResource}: the composition
 * registers {@link MiliastraPythonLedgerPort.resource} in the T03 controller's
 * table, and `dispose()` releases it. The release closes stdin, waits (bounded)
 * for exit, then kills only as a last resort — and it is reached only through
 * the controller's own resource loop, never by the backend.
 *
 * @module @miliastra/dsh-miliastra/ledger-port
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { join } from 'node:path'
import type {
  MiliastraBusinessLedgerPort,
  MiliastraOperationObservation,
  MiliastraOperationView,
  MiliastraResource,
} from './lifecycle.ts'

/** Default per-request bound for one ledger call. */
export const DEFAULT_LEDGER_REQUEST_TIMEOUT_MS = 10_000

/** Default bound for the child process to exit after stdin closes. */
export const DEFAULT_LEDGER_SHUTDOWN_TIMEOUT_MS = 3_000

/** Module path of the Python ledger port, relative to the project root. */
export const LEDGER_PORT_MODULE = 'backend.ledger_port'

/** Environment entries this adapter adds to the child. Mirrors `src/backend.ts`. */
export const LEDGER_PORT_ENV_ALLOWLIST: Readonly<Record<string, string>> = Object.freeze({
  PYTHONIOENCODING: 'utf-8',
  PYTHONUTF8: '1',
})

/** Stable failure codes for the adapter itself (never the ledger's own codes). */
export type MiliastraLedgerPortErrorCode =
  /** The child could not be started at all. */
  | 'LEDGER_PORT_SPAWN_FAILED'
  /** The child exited or its stdout closed with requests outstanding. */
  | 'LEDGER_PORT_CLOSED'
  /** A request did not settle within its bound. */
  | 'LEDGER_PORT_TIMEOUT'
  /** The service answered with `ok: false`; `ledgerCode` carries its reason. */
  | 'LEDGER_PORT_REFUSED'
  /** The service answered with a line that is not a JSON object. */
  | 'LEDGER_PORT_PROTOCOL'

/** A transport failure. The lifecycle maps this to `LIFECYCLE_LEDGER_UNAVAILABLE`. */
export class MiliastraLedgerPortError extends Error {
  /** Machine-checkable reason. */
  readonly code: MiliastraLedgerPortErrorCode
  /** The ledger's own refusal code, when the service refused rather than failed. */
  readonly ledgerCode: string | null

  constructor(code: MiliastraLedgerPortErrorCode, detail: string, ledgerCode: string | null = null) {
    super(ledgerCode === null ? `${code}: ${detail}` : `${code}: ${ledgerCode} ${detail}`)
    this.name = 'MiliastraLedgerPortError'
    this.code = code
    this.ledgerCode = ledgerCode
  }
}

/** Options for {@link MiliastraPythonLedgerPort}. */
export interface MiliastraPythonLedgerPortOptions {
  /** Absolute path of the Python interpreter; the same one the backend uses. */
  readonly pythonExecutable: string
  /** Absolute project root; the child's working directory, so `-m` resolves. */
  readonly projectRoot: string
  /**
   * Absolute ledger root handed to the service. **Required.** The ledger has no
   * default root, so neither does this adapter.
   */
  readonly ledgerRoot: string
  /** Per-request bound. Defaults to {@link DEFAULT_LEDGER_REQUEST_TIMEOUT_MS}. */
  readonly requestTimeoutMs?: number
  /** Namespace of the owning composition, for the resource row. */
  readonly serverName?: string | null
  /** Module path override, for tests that point at a vendored copy. */
  readonly modulePath?: string
}

/** One outstanding request. */
interface PendingRequest {
  readonly resolve: (value: unknown) => void
  readonly reject: (error: Error) => void
  readonly timer: ReturnType<typeof setTimeout>
}

/**
 * An observation that may carry the raw bottom-layer receipt body.
 *
 * `MiliastraOperationObservation` fixes what the *lifecycle* may hand over, and
 * it deliberately has no receipt: the lifecycle never holds one. An adapter is a
 * wider surface — a caller that does hold the receipt body may pass it, and the
 * ledger then adjudicates it through `late_receipt` instead of merely recording
 * a pointer to it.
 *
 * This is a widening of the port's parameter type, never of the lifecycle's:
 * declaring it here rather than editing `src/lifecycle.ts` keeps the frozen
 * interface untouched while making the extra field honest at the type level
 * instead of an unchecked cast.
 */
export interface MiliastraReceiptBearingObservation extends MiliastraOperationObservation {
  /** The raw receipt body, when the caller holds one. The ledger decides whether it attributes. */
  readonly receipt?: unknown
}

/**
 * The real ledger port.
 *
 * Lazily starts its child on the first request, so a plugin instance that never
 * touches a business operation spawns nothing. One instance per composition;
 * never share one between two controllers.
 */
export class MiliastraPythonLedgerPort implements MiliastraBusinessLedgerPort {
  private readonly options: MiliastraPythonLedgerPortOptions
  private readonly timeoutMs: number
  private child: ChildProcessWithoutNullStreams | null = null
  private stdoutBuffer = ''
  private sequence = 0
  private readonly pending = new Map<number, PendingRequest>()
  private closedReason: string | null = null
  private disposed = false
  private disposePromise: Promise<void> | null = null

  constructor(options: MiliastraPythonLedgerPortOptions) {
    this.options = options
    this.timeoutMs = options.requestTimeoutMs ?? DEFAULT_LEDGER_REQUEST_TIMEOUT_MS
  }

  // -- port methods ---------------------------------------------------------

  /**
   * Read one operation. Read-only by contract.
   * @param operationId - the business idempotency key.
   * @returns the row, or null when the ledger has never claimed the id.
   */
  async readOperation(operationId: string): Promise<MiliastraOperationView | null> {
    const result = await this.call('readOperation', { operationId }) as { view: MiliastraOperationView | null }
    return result.view
  }

  /**
   * Record an observation against an existing operation and return the row as
   * the ledger now adjudicates it. Never creates an operation; the service
   * refuses an unknown id, which surfaces as {@link MiliastraLedgerPortError}.
   * @param observation - the receipt and the operation it belongs to.
   * @returns the resulting row.
   */
  async recordObservation(observation: MiliastraReceiptBearingObservation): Promise<MiliastraOperationView> {
    const params: Record<string, unknown> = {
      operationId: observation.operationId,
      requestId: observation.requestId,
      receiptRef: observation.receiptRef,
      observedUtc: observation.observedUtc,
      detail: observation.detail,
    }
    // A caller that holds the raw receipt body hands it through untouched; the
    // ledger alone decides whether it is attributable. The lifecycle never
    // supplies one, so the common path appends and re-reads.
    if (observation.receipt !== undefined) params.receipt = observation.receipt
    const result = await this.call('recordObservation', params) as { view: MiliastraOperationView }
    return result.view
  }

  /**
   * Enumerate the operations the ledger still considers open. A reloaded
   * instance uses this to discover the previous instance's unresolved writes.
   * @returns one row per open operation.
   */
  async listOpenOperations(): Promise<readonly MiliastraOperationView[]> {
    const result = await this.call('listOpenOperations', {}) as { views: MiliastraOperationView[] }
    return result.views
  }

  // -- ownership ------------------------------------------------------------

  /**
   * The resource row the T03 controller registers, so an unload releases the
   * child process through the same bounded loop as every other own resource.
   * @returns an `own` `child-plugin` resource whose release disposes this port.
   */
  resource(): MiliastraResource {
    const name = this.options.serverName ?? 'miliastra'
    return {
      id: `ledger-port:${name}`,
      kind: 'child-plugin',
      ownership: 'own',
      createdBy: 'miliastra:ledger-port',
      release: () => this.dispose(),
    }
  }

  /** Whether the child is currently running. */
  get running(): boolean {
    return this.child !== null && this.closedReason === null
  }

  /**
   * Close the child and reject everything still outstanding. Idempotent.
   * @returns a promise that settles when the child has exited or been killed.
   */
  dispose(): Promise<void> {
    if (this.disposePromise !== null) return this.disposePromise
    this.disposed = true
    this.disposePromise = this.shutdown()
    return this.disposePromise
  }

  // -- transport ------------------------------------------------------------

  /** The child's argv: the fixed module, the explicit root, nothing else. */
  private args(): string[] {
    return ['-B', '-m', this.options.modulePath ?? LEDGER_PORT_MODULE, '--root', this.options.ledgerRoot]
  }

  /** Start the child once, and wire its streams. */
  private start(): ChildProcessWithoutNullStreams {
    if (this.child !== null) return this.child
    if (this.disposed) {
      throw new MiliastraLedgerPortError('LEDGER_PORT_CLOSED',
        'this port was disposed and never reopens; a reloaded instance gets a fresh port')
    }
    let child: ChildProcessWithoutNullStreams
    try {
      child = spawn(this.options.pythonExecutable, this.args(), {
        cwd: this.options.projectRoot,
        env: { ...LEDGER_PORT_ENV_ALLOWLIST },
        stdio: ['pipe', 'pipe', 'pipe'],
      })
    } catch (error) {
      throw new MiliastraLedgerPortError('LEDGER_PORT_SPAWN_FAILED',
        error instanceof Error ? error.message : String(error))
    }
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => { this.onStdout(chunk) })
    child.on('error', (error: Error) => {
      // A child that could not be started is as gone as one that exited: record it so
      // the next call answers at once instead of spawning again or waiting.
      this.closedReason ??= `the ledger port could not be started (${error.message})`
      this.failAll('LEDGER_PORT_SPAWN_FAILED', error.message)
    })
    child.on('exit', (code: number | null, signal: string | null) => {
      this.closedReason = `the ledger port exited (code ${String(code)}, signal ${String(signal)})`
      this.failAll('LEDGER_PORT_CLOSED', this.closedReason)
    })
    this.child = child
    return child
  }

  /** Split stdout into lines and settle each response. */
  private onStdout(chunk: string): void {
    this.stdoutBuffer += chunk
    let newline = this.stdoutBuffer.indexOf('\n')
    while (newline >= 0) {
      const line = this.stdoutBuffer.slice(0, newline).trim()
      this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1)
      if (line !== '') this.settleLine(line)
      newline = this.stdoutBuffer.indexOf('\n')
    }
  }

  /** Settle one response line against its pending request. */
  private settleLine(line: string): void {
    let parsed: { id?: unknown, ok?: unknown, result?: unknown, error?: { code?: unknown, message?: unknown } }
    try {
      parsed = JSON.parse(line) as typeof parsed
    } catch {
      this.failAll('LEDGER_PORT_PROTOCOL', `the ledger port wrote a line that is not JSON: ${line.slice(0, 200)}`)
      return
    }
    const id = typeof parsed.id === 'number' ? parsed.id : Number.NaN
    const entry = this.pending.get(id)
    if (entry === undefined) return
    this.pending.delete(id)
    clearTimeout(entry.timer)
    if (parsed.ok === true) {
      entry.resolve(parsed.result)
      return
    }
    const code = typeof parsed.error?.code === 'string' ? parsed.error.code : 'LEDGER_REFUSED'
    const message = typeof parsed.error?.message === 'string' ? parsed.error.message : 'the ledger refused the call'
    entry.reject(new MiliastraLedgerPortError('LEDGER_PORT_REFUSED', message, code))
  }

  /**
   * Why this port can no longer answer, or null while it still can.
   *
   * `closedReason` is set by the exit and error handlers, but a request can arrive
   * between the child dying and that event being delivered, so the child's own
   * `exitCode`/`signalCode` are consulted as well.  Once this reports a reason the
   * port is terminal: a reloaded instance gets a fresh port, never a resurrected one.
   *
   * Why it matters, MEASURED: with a child that had already exited, the first request
   * was refused in 67 ms because the 'exit' handler's `failAll` still found it
   * outstanding -- but every LATER request waited out the entire `requestTimeoutMs`
   * (120 002 ms measured; 900 000 ms in the production profile) because `start()`
   * handed back the dead child and the 'exit' event had already been delivered.
   * `src/index.ts` hands this port's `requestTimeoutMs` the profile's
   * `toolCallTimeoutMs`, so a dead ledger meant a 15-minute hang on every write.
   *
   * @returns the reason, or null when a request may still be attempted.
   */
  private closed(): string | null {
    if (this.closedReason !== null) return this.closedReason
    if (this.disposed) {
      this.closedReason = 'this port was disposed and never reopens; a reloaded instance gets a fresh port'
      return this.closedReason
    }
    const child = this.child
    if (child !== null && (child.exitCode !== null || child.signalCode !== null)) {
      this.closedReason = 'the ledger port child has exited, so this port answers nothing more'
      return this.closedReason
    }
    return null
  }

  /** Send one request and await its response. */
  private call(method: string, params: Record<string, unknown>): Promise<unknown> {
    // Answer a request against a port that can no longer answer BEFORE allocating a
    // sequence number or a timer.  Regression: tests/ledger-port-closed.spec.ts.
    const closed = this.closed()
    if (closed !== null) {
      return Promise.reject(new MiliastraLedgerPortError('LEDGER_PORT_CLOSED', closed))
    }
    const child = this.start()
    this.sequence += 1
    const id = this.sequence
    const line = `${JSON.stringify({ id, method, params })}\n`
    return new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new MiliastraLedgerPortError('LEDGER_PORT_TIMEOUT',
          `${method} did not settle within ${this.timeoutMs} ms`))
      }, this.timeoutMs)
      if (typeof timer === 'object' && timer !== null && typeof timer.unref === 'function') timer.unref()
      this.pending.set(id, { resolve, reject, timer })
      try {
        child.stdin.write(line)
      } catch (error) {
        this.pending.delete(id)
        clearTimeout(timer)
        reject(new MiliastraLedgerPortError('LEDGER_PORT_CLOSED',
          error instanceof Error ? error.message : String(error)))
      }
    })
  }

  /** Reject every outstanding request with one reason. */
  private failAll(code: MiliastraLedgerPortErrorCode, detail: string): void {
    for (const [id, entry] of [...this.pending.entries()]) {
      this.pending.delete(id)
      clearTimeout(entry.timer)
      entry.reject(new MiliastraLedgerPortError(code, detail))
    }
  }

  /** Close stdin, wait for exit, then kill only if the child will not go. */
  private async shutdown(): Promise<void> {
    const child = this.child
    this.child = null
    if (child === null) return
    this.failAll('LEDGER_PORT_CLOSED', 'the ledger port was disposed with requests outstanding')
    const exited = new Promise<void>(resolve => {
      if (child.exitCode !== null || child.signalCode !== null) { resolve(); return }
      child.once('exit', () => resolve())
    })
    try { child.stdin.end() } catch { /* already gone */ }
    const guard = new Promise<'timeout'>(resolve => {
      const timer = setTimeout(() => resolve('timeout'), DEFAULT_LEDGER_SHUTDOWN_TIMEOUT_MS)
      if (typeof timer === 'object' && timer !== null && typeof timer.unref === 'function') timer.unref()
    })
    const outcome = await Promise.race([exited.then(() => 'exited' as const), guard])
    if (outcome === 'timeout' && child.exitCode === null) {
      try { child.kill() } catch { /* best effort; never escalate beyond SIGTERM */ }
      await exited
    }
  }
}

/**
 * Create the real ledger port for one composition.
 * @param options - interpreter, project root and the explicit ledger root.
 * @returns the port, plus its resource row for the lifecycle controller.
 */
export function createMiliastraLedgerPort(options: MiliastraPythonLedgerPortOptions): {
  port: MiliastraPythonLedgerPort
  resource: MiliastraResource
} {
  const port = new MiliastraPythonLedgerPort(options)
  return { port, resource: port.resource() }
}

/**
 * The ledger root this project owns, derived from a project root.
 *
 * Kept as a function, not a constant, so there is exactly one place that names
 * the directory and the caller still passes it explicitly to the adapter.
 * @param projectRoot - absolute project root.
 * @returns the absolute ledger root inside `.runtime`.
 */
export function defaultLedgerRoot(projectRoot: string): string {
  return join(projectRoot, '.runtime', 'business-ledger')
}
