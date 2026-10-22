/**
 * T02: the business backend composition slot.
 *
 * `src/index.ts` decides *when* a backend is composed and with what resolved
 * config; this module owns *how*: it maps the resolved config onto the vendored
 * `@deepseek-ai/dsh-mcp-client` stdio transport, creates that client as a child
 * Cordis plugin of this plugin instance, reads back the tool table it actually
 * published into the injected `tools` registry, and reports what happened.
 *
 * WHAT THIS MODULE DOES NOT DO
 *
 * - It does not re-implement an MCP client. Handshake, tool discovery, naming
 *   (`mcp__<serverName>__<rawName>`), tool-table re-sync and transport
 *   reconnection all belong to the vendored client; this file only configures
 *   it, gates what it registers, and observes what it published.
 * - It does not start the game, the editor, the elevated helper, or the bridge.
 *   It spawns exactly one process: the configured interpreter running the fixed
 *   business module entry, the same shape the shipped entity overlay uses
 *   (`config/mw-entity-create.patch.yml`: command `python`, args
 *   `['-m', 'backend.entity_server']`, `cwd = projectRoot`).
 * - It never lets the model choose the command, the module, the working
 *   directory, or a raw payload: every one of those is derived here from the
 *   operator's resolved config.
 *
 * WHY A WRAPPED TOOL TABLE (the write gate)
 *
 * The vendored client registers its tools directly into the `tools` service.
 * The composition needs one thing that service cannot give it: a record that a
 * write was *dispatched*, so that a transport-level reconnect can restore the
 * connection without ever re-sending it. The client already never re-sends an
 * in-flight `tools/call`; this wrapper makes that a property of the
 * composition — it mints an operation id before the call, records the outcome,
 * keeps a call whose outcome was never learned as `unknown` (never retried),
 * and refuses new dispatches once the composition is draining. Reconciling an
 * `unknown` operation is T06's job, not a retry's.
 *
 * The wrapper forwards `description`, `parameters` (the MCP `inputSchema`) and
 * `output` untouched, so the schema the model sees is exactly the one the
 * vendored client derived from the server's `tools/list`; nothing here
 * rewrites, drops, or defaults a field.
 *
 * @module @miliastra/dsh-miliastra/backend
 */

import { existsSync, mkdirSync } from 'node:fs'
import { appendFileSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import * as mcpClient from '@deepseek-ai/dsh-mcp-client'
import type { StdioConfig } from '@deepseek-ai/dsh-mcp-client'
import type { ResolvedMiliastraConfig } from './config.ts'
import type { MiliastraBackendStatus, MiliastraDispatchGate } from './composition.ts'

// ---------------------------------------------------------------------------
// The mapping contract
// ---------------------------------------------------------------------------

/** Module file the fixed business entry resolves to inside `backendRoot`. */
const ENTRY_FILE_NAME = 'entity_server.py'

/** Module path suffix of the fixed business entry. */
const ENTRY_MODULE_SUFFIX = 'entity_server'

/** A directory name usable as one Python module segment, so `-m` can name it. */
const MODULE_SEGMENT_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/

/**
 * Environment entries this composition *adds* to the child's environment.
 *
 * Mirrors the two the shipped overlay sets. Everything else the child sees is
 * the vendored transport's `scrubbedParentEnv()`: the ambient environment minus
 * credential-shaped names (`/KEY|PASSWORD|SECRET|TOKEN/i`) and minus every
 * `DSH_*` name. This is an allowlist of additions, never a channel for
 * credentials — nothing the plugin holds is forwarded to the backend.
 */
export const BACKEND_ENV_ALLOWLIST: Readonly<Record<string, string>> = Object.freeze({
  PYTHONIOENCODING: 'utf-8',
  PYTHONUTF8: '1',
})

/**
 * Model-visible business tools every composition must publish.
 *
 * These are the backend's own tool names (`backend/entity_server.py`,
 * `@mcp.tool` functions). This is a *contract*, not a discovery result: the
 * composition reads the actual table from the registry and reports the
 * difference, so a server that drops, renames, or adds a tool is visible
 * instead of silently accepted. `tests/backend-connection.spec.ts` re-derives
 * this list from `backend/entity_server.py`, so the constant cannot drift from
 * the real server without failing the suite.
 */
export const REQUIRED_BUSINESS_TOOLS: readonly string[] = Object.freeze([
  'mw_graph_observe', // Read-only existing author graph port; no write permission.
  'mw_scene_capabilities',
  'mw_scene_discover_level',
  'mw_scene_read_entities',
  // T04 scene-query surface, registered by backend/scene_query_wiring.py and
  // merged into backend/entity_server.py on 2026-10-02. T02-L pins this list to
  // the real backend's own `def mw_*` set, so a registered tool has to appear
  // here or the composition contract test fails. All four are read-only.
  'mw_scene_observe_level',
  'mw_scene_page_entities',
  'mw_scene_entity_detail',
  'mw_scene_diff_level',
  'mw_scene_create_entity',
  'mw_scene_save_level',
  'mw_scene_operation_status',
  'mw_scene_cleanup_owned',
  // D04.01.03: the batch create entry. Inline structured placements only (no plan
  // file); one reviewed native create per placement under its own requestId, and a
  // later attempt re-dispatches only the placements the caller names.
  'mw_scene_create_batch',
])

/**
 * Required tools that dispatch a native write.
 *
 * Gate-worthy by construction: `backend/entity_server.py` documents these four
 * as journaled native writes (one reviewed request per `requestId`). Every
 * other required tool is treated as a read, and any published tool that is
 * neither required nor known is treated as a **write** — the gate fails closed.
 */
export const WRITE_BUSINESS_TOOLS: readonly string[] = Object.freeze([
  'mw_scene_create_entity',
  'mw_scene_save_level',
  'mw_scene_cleanup_owned',
  // D04.01.03: a batch create is N journaled native creates, so it is gated and
  // wrapped exactly like the single create.
  'mw_scene_create_batch',
])

/**
 * Transport reconnection policy handed to the vendored client.
 *
 * Reconnection restores the *connection* only: the client closes the dead
 * generation and re-runs `tools/list`, and never re-sends a `tools/call`.
 * These are the vendored client's own defaults, restated here so the
 * composition's policy is explicit rather than an omission.
 */
export const BACKEND_RECONNECT_POLICY: Readonly<Record<'enabled' | 'initialDelayMs' | 'maxDelayMs' | 'maxAttempts', boolean | number>> = Object.freeze({
  enabled: true,
  initialDelayMs: 500,
  maxDelayMs: 30_000,
  maxAttempts: 10,
})

/** Evidence file this module appends one composition record to. */
export const BACKEND_EVIDENCE_FILE = 'miliastra-backend.jsonl'

/** Schema version of the evidence record. */
export const BACKEND_EVIDENCE_VERSION = 1

/** Default bound for waiting on in-flight dispatches during a drain. */
export const DEFAULT_DRAIN_TIMEOUT_MS = 5_000

/** Stable failure codes for backend composition. */
export type MiliastraBackendErrorCode =
  | 'BACKEND_ROOT_NAME_UNUSABLE'
  | 'BACKEND_ENTRY_MISSING'
  | 'BACKEND_TOOLS_SERVICE_UNUSABLE'
  | 'BACKEND_START_FAILED'
  | 'EVIDENCE_WRITE_FAILED'
  | 'BACKEND_DRAINING'

/** A backend defect the composition refuses to paper over. */
export class MiliastraBackendError extends Error {
  /** Machine-checkable reason. */
  readonly code: MiliastraBackendErrorCode
  /** Config field, tool name, or path the failure belongs to. */
  readonly subject: string

  constructor(code: MiliastraBackendErrorCode, subject: string, detail: string, options?: { cause?: unknown }) {
    super(`${code}: ${subject} ${detail}`, options)
    this.name = 'MiliastraBackendError'
    this.code = code
    this.subject = subject
  }
}

/**
 * A dispatch refused because the composition is draining or disposed.
 * Not an unknown outcome: nothing was sent, so nothing has to be reconciled.
 */
export class MiliastraDispatchRefusedError extends Error {
  /** Machine-checkable reason. */
  readonly code = 'BACKEND_DRAINING'
  /** Public name of the tool the dispatch would have called. */
  readonly toolName: string

  constructor(toolName: string, reason: string) {
    super(`BACKEND_DRAINING: ${toolName} was not dispatched (${reason}); nothing was sent, so nothing is unknown`)
    this.name = 'MiliastraDispatchRefusedError'
    this.toolName = toolName
  }
}

// ---------------------------------------------------------------------------
// Pure mapping: resolved config -> vendored client StdioConfig
// ---------------------------------------------------------------------------

/**
 * Python module path for the fixed business entry, derived from `backendRoot`.
 *
 * `backendRoot` is the *directory* holding the entry, so the module path is
 * that directory's own name plus `entity_server`, and the child's working
 * directory is the directory's parent — the layout `python -m <pkg>.<module>`
 * requires. A directory name Python cannot use as a module segment is refused
 * by name here, instead of being handed to the interpreter to fail obscurely.
 *
 * @param backendRoot - absolute backend directory from the resolved config.
 * @returns the `-m` module path, e.g. `backend.entity_server`.
 * @throws MiliastraBackendError with `BACKEND_ROOT_NAME_UNUSABLE`.
 */
export function backendModulePath(backendRoot: string): string {
  const segment = basename(backendRoot)
  if (!MODULE_SEGMENT_PATTERN.test(segment)) {
    throw new MiliastraBackendError('BACKEND_ROOT_NAME_UNUSABLE', backendRoot,
      `must end in a Python module segment ([A-Za-z_][A-Za-z0-9_]*), got ${JSON.stringify(segment)}`)
  }
  return `${segment}.${ENTRY_MODULE_SUFFIX}`
}

/**
 * Absolute path of the entry file this composition will run.
 * @param backendRoot - absolute backend directory from the resolved config.
 * @returns the entry file path (existence is checked by the caller).
 */
export function backendEntryPath(backendRoot: string): string {
  return join(backendRoot, ENTRY_FILE_NAME)
}

/**
 * Map the resolved plugin config onto the vendored client's stdio config.
 *
 * Pure and total: no filesystem access, no environment read, no spawn. The
 * model supplies none of these values; each field is either an operator input
 * (`pythonExecutable`, `projectRoot`, `backendRoot`, `serverName`,
 * `toolCallTimeoutMs`, `failOnStartupError`) or a constant of this module
 * (argv, env allowlist, reconnect policy). Arguments are passed as `argv`
 * entries — never interpolated into a shell string.
 *
 * @param config - frozen resolved config.
 * @returns the stdio config for the vendored client.
 * @throws MiliastraBackendError when `backendRoot` cannot name a module.
 */
export function buildBackendStdioConfig(config: ResolvedMiliastraConfig): StdioConfig {
  return {
    transport: 'stdio',
    serverName: config.serverName,
    command: config.pythonExecutable,
    args: ['-m', backendModulePath(config.backendRoot)],
    cwd: dirname(config.backendRoot),
    env: { ...BACKEND_ENV_ALLOWLIST },
    toolCallTimeoutMs: config.toolCallTimeoutMs,
    // Mirrors the operator's policy onto the client's own startup policy: under
    // `failOnStartupError` the child rejects, so this module can report the real
    // cause and the plugin rolls activation back; otherwise the client keeps
    // retrying and this composition reports `unavailable` for now.
    failOnStartupError: config.failOnStartupError,
    reconnect: { ...BACKEND_RECONNECT_POLICY },
  } as StdioConfig
}

/**
 * Model-visible public name of one raw MCP tool, in the clean case.
 *
 * The complete naming rule belongs to the vendored client (`publicToolName` in
 * `@deepseek-ai/dsh-mcp-client/src/tools.ts`, which the published entry does
 * not export): the clean case is `mcp__<serverName>__<rawName>`, and a name
 * needing character replacement or truncation gains a 12-hex-char identity
 * hash. Every required business tool is ASCII `snake_case` and short, so the
 * clean case is exact for them; the suite asserts that against the vendored
 * client's own function rather than trusting this comment.
 *
 * @param serverName - configured namespace.
 * @param rawName - the server's own tool name.
 * @returns the expected public name in the clean (unnormalized) case.
 */
export function expectedPublicToolName(serverName: string, rawName: string): string {
  return `${toolNamePrefix(serverName)}${rawName}`
}

/**
 * The prefix every tool of one server necessarily begins with.
 *
 * Safe as an *ownership* test even on the lossy path: the client normalizes
 * `mcp__<serverName>__` (whose characters are already legal) and truncation
 * only ever shortens the tail, so the prefix is never rewritten.
 *
 * @param serverName - configured namespace.
 * @returns the public-name prefix.
 */
export function toolNamePrefix(serverName: string): string {
  return `mcp__${serverName}__`
}

/**
 * Absolute path of the composition's evidence record.
 * @param config - frozen resolved config.
 * @returns the evidence file path.
 */
export function backendEvidencePath(config: ResolvedMiliastraConfig): string {
  return join(config.evidenceRoot, BACKEND_EVIDENCE_FILE)
}

// ---------------------------------------------------------------------------
// Tool-table observation
// ---------------------------------------------------------------------------

/**
 * The `tools` registry surface this module reads.
 *
 * Structural on purpose: the registry is injected (`inject: ['tools']`), so
 * importing `@deepseek-ai/dsh-tools` here would add a compile-time dependency
 * the plugin does not need. Every member is optional and probed at runtime — a
 * service that cannot answer is reported as unobservable, never assumed.
 */
interface ToolRegistryLike {
  register: (definition: unknown) => () => void
  get?: (name: string, scope?: unknown) => unknown
  schemas?: (scope?: unknown) => readonly unknown[]
}

/** One tool definition as the vendored client registers it. */
interface BridgedToolDefinition {
  name: string
  description: string
  parameters: unknown
  output: unknown
  execute: (args: unknown, exec: unknown) => unknown
  finalizeContent?: (exec: unknown, result: unknown) => unknown
  [key: string]: unknown
}

/** What the registry says about one published tool. */
interface PublishedTool {
  /** Public, model-visible name. */
  readonly publicName: string
  /** Raw name recovered from the public name (clean-case rule). */
  readonly rawName: string
  /** Whether the tool dispatches a native write (unknown tools count as writes). */
  readonly classification: 'read' | 'write' | 'unexpected'
  /** Input schema as registered. */
  readonly inputSchema: unknown
  /** Model-facing output contract: the registered output schema. */
  readonly outputSchema: unknown
  /** `declared` when a structured-output schema is required, else `unconstrained`. */
  readonly outputContract: 'declared' | 'unconstrained'
  /** Description as registered. */
  readonly description: string
}

/**
 * Read one tool's structured-output contract out of its registered output
 * schema. The vendored client requires `structuredContent` exactly when the
 * server advertised an output schema it could carry through, and leaves it
 * unconstrained otherwise — so `required` is the observable difference.
 * @param output - the registered `output` member.
 * @returns the contract label.
 */
function outputContractOf(output: unknown): 'declared' | 'unconstrained' {
  const schema = (output as { schema?: { required?: unknown } } | undefined)?.schema
  const required = schema?.required
  return Array.isArray(required) && required.includes('structuredContent') ? 'declared' : 'unconstrained'
}

/**
 * Flatten an error's cause chain into one diagnostic line.
 *
 * The vendored client deliberately throws one short, uniform message at its
 * plugin boundary and keeps the real reason in `cause` (its startup wrapper is
 * `initial connection or tool synchronization failed`). Reporting only the
 * boundary message would make a duplicate tool list and an unstartable
 * interpreter read the same; the chain does not.
 *
 * @param error - the thrown value.
 * @returns distinct messages from the chain, outermost first.
 */
function errorDetail(error: unknown): string {
  const messages: string[] = []
  let current: unknown = error
  const push = (message: string | undefined): void => {
    if (message !== undefined && message !== '' && !messages.includes(message)) messages.push(message)
  }
  while (current instanceof Error) {
    push(current.message)
    if (current instanceof AggregateError) {
      for (const inner of current.errors) if (inner instanceof Error) push(inner.message)
    }
    current = current.cause
  }
  return messages.length === 0 ? String(error) : messages.join(' <- ')
}

/** Report whether a service is a registry this composition can publish into. */
function asRegistry(service: unknown): ToolRegistryLike | undefined {
  if (service === undefined || service === null || typeof service !== 'object') return undefined
  const candidate = service as Partial<ToolRegistryLike>
  return typeof candidate.register === 'function' ? candidate as ToolRegistryLike : undefined
}

/** Read the registry's own view of the visible tool names (empty when unobservable). */
function registryToolNames(registry: ToolRegistryLike): { observable: boolean, names: string[] } {
  if (registry.schemas === undefined) return { observable: false, names: [] }
  try {
    const names = registry.schemas()
      .map(schema => (schema as { name?: unknown } | undefined)?.name)
      .filter((name): name is string => typeof name === 'string')
    return { observable: true, names }
  } catch {
    return { observable: false, names: [] }
  }
}

/**
 * Classify one published tool against the business contract.
 * Unknown tools are treated as writes, so the gate fails closed.
 * @param serverName - namespace of the composition.
 * @param publicName - the model-visible name.
 * @returns the classification and the recovered raw name.
 */
function classify(serverName: string, publicName: string): {
  classification: PublishedTool['classification']
  rawName: string
} {
  for (const rawName of REQUIRED_BUSINESS_TOOLS) {
    if (publicName !== expectedPublicToolName(serverName, rawName)) continue
    return { classification: WRITE_BUSINESS_TOOLS.includes(rawName) ? 'write' : 'read', rawName }
  }
  return { classification: 'unexpected', rawName: publicName.slice(toolNamePrefix(serverName).length) }
}

/** Read one registered definition into the record the evidence reports. */
function toPublishedTool(serverName: string, definition: BridgedToolDefinition): PublishedTool {
  const { classification, rawName } = classify(serverName, definition.name)
  return {
    publicName: definition.name,
    rawName,
    classification,
    inputSchema: definition.parameters ?? null,
    outputSchema: (definition.output as { schema?: unknown } | undefined)?.schema ?? null,
    outputContract: outputContractOf(definition.output),
    description: typeof definition.description === 'string' ? definition.description : '',
  }
}

// ---------------------------------------------------------------------------
// The operation ledger
// ---------------------------------------------------------------------------

/** One write dispatch the composition has issued. */
export interface MiliastraPendingOperation {
  /**
   * Identity of the dispatch, suitable as a join key with the caller's own
   * ledger. It is the caller's `callId` when the registry supplies one (the
   * model-facing call identity T06 reconciles by), and a minted
   * `<serverName>:<rawName>:<n>` id otherwise — the handler never invents a
   * second identity for a call it was told about.
   */
  readonly operationId: string
  /** Public tool name the dispatch called. */
  readonly toolName: string
  /** Raw MCP tool name sent on the wire. */
  readonly rawName: string
  /** ISO-8601 instant the dispatch left the plugin. */
  readonly startedAtUtc: string
  /** `in-flight` until it settles; `unknown` when its outcome was never learned. */
  readonly state: 'in-flight' | 'unknown'
  /** Why the outcome is unknown, for an `unknown` operation. */
  readonly detail: string | null
}

/** Result of draining one composition. */
export interface MiliastraDrainReport {
  /** Namespace of the drained composition. */
  readonly serverName: string
  /** Why the drain ran (operator-facing). */
  readonly reason: string
  /** Dispatches still running when the drain returned, in dispatch order. */
  readonly inFlight: readonly MiliastraPendingOperation[]
  /**
   * Dispatches whose outcome was never learned, in dispatch order. They are
   * listed for reconciliation (T06); this module and the vendored client's
   * reconnect never re-send them.
   */
  readonly unknown: readonly MiliastraPendingOperation[]
  /** Dispatches refused because the composition was already draining. */
  readonly refusedDispatches: number
  /** Whether the drain reached quiescence within its bound. */
  readonly quiescent: boolean
}

/** Result of disposing one composition. */
export interface MiliastraDisposeReport extends MiliastraDrainReport {
  /** Whether the owned MCP connection and its child process were released. */
  readonly connectionDisposed: boolean
  /** Whether the composition was already disposed when this call ran. */
  readonly alreadyDisposed: boolean
}

/**
 * The resource handle T03's lifecycle controller consumes.
 *
 * Deliberately the whole surface the backend can offer: the namespace it owns,
 * the tools it published, and the two shutdown seams with their reports. It
 * exposes no transport, no child-process handle, and no queue path — PID,
 * queue, review and save paths never leave the backend.
 */
export interface MiliastraBackendResources {
  /** Namespace segment of every tool name this composition published. */
  readonly serverName: string
  /** Public-name prefix owned by this composition. */
  readonly toolsPrefix: string
  /** Public names actually published, in registration order. */
  readonly toolNames: readonly string[]
  /** Absolute path of the composition's evidence record. */
  readonly evidencePath: string
  /** `starting` before the tool table is published, then `ready`/`draining`/`disposed`. */
  readonly state: 'starting' | 'ready' | 'draining' | 'disposed'
  /**
   * Stop accepting new dispatches and wait (bounded) for in-flight ones.
   * Refused dispatches are counted; nothing is silently dropped or re-sent.
   * @param options - reason for the drain and the bound to wait for.
   */
  drain(options?: { reason?: string, timeoutMs?: number }): Promise<MiliastraDrainReport>
  /**
   * Drain, then release everything this composition owns: the published tools
   * and the MCP connection (which closes the child process). Idempotent; a
   * second call returns the settled report.
   */
  dispose(options?: { reason?: string, timeoutMs?: number }): Promise<MiliastraDisposeReport>
}

/** One composition's live bookkeeping. */
interface BackendSession {
  readonly serverName: string
  readonly prefix: string
  readonly evidencePath: string
  readonly registry: ToolRegistryLike
  /** Published tools by public name, in registration order. */
  readonly published: Map<string, PublishedTool>
  /** The registry's disposers, by public name. */
  readonly disposers: Map<string, () => void>
  /** Live and unknown write operations, by operation id. */
  readonly operations: Map<string, MiliastraPendingOperation>
  state: 'starting' | 'ready' | 'draining' | 'disposed'
  /** Set once the tool table is refused; later registrations are refused too. */
  latched: boolean
  refusedDispatches: number
  dispatchSequence: number
  disposeReport: MiliastraDisposeReport | undefined
}

/** Whether any operation of the session is still in flight. */
function hasInFlight(session: BackendSession): boolean {
  for (const operation of session.operations.values()) {
    if (operation.state === 'in-flight') return true
  }
  return false
}

/**
 * Wait, for at most `timeoutMs`, until no dispatch is in flight.
 * Polling rather than a wake-set: the wait is bounded, short, and this is a
 * shutdown path where a missed wake-up would be worse than a 50 ms poll.
 * @param session - the session to wait on.
 * @param timeoutMs - the bound.
 * @returns whether the session reached quiescence in time.
 */
async function waitForQuiescence(session: BackendSession, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + Math.max(0, timeoutMs)
  while (hasInFlight(session) && Date.now() < deadline) {
    await new Promise<void>((resolve) => { setTimeout(resolve, Math.min(50, Math.max(1, deadline - Date.now()))) })
  }
  return !hasInFlight(session)
}

/** Snapshot a session's operations into the two report buckets. */
function operationBuckets(session: BackendSession): { inFlight: MiliastraPendingOperation[], unknown: MiliastraPendingOperation[] } {
  const operations = [...session.operations.values()]
  return {
    inFlight: operations.filter(operation => operation.state === 'in-flight'),
    unknown: operations.filter(operation => operation.state === 'unknown'),
  }
}

/** Stop accepting dispatches, wait for in-flight ones, and report both buckets. */
async function drainSession(session: BackendSession, reason: string, timeoutMs: number): Promise<MiliastraDrainReport> {
  if (session.state === 'starting' || session.state === 'ready') session.state = 'draining'
  const quiescent = await waitForQuiescence(session, timeoutMs)
  return {
    serverName: session.serverName,
    reason,
    ...operationBuckets(session),
    refusedDispatches: session.refusedDispatches,
    quiescent,
  }
}

/** Release everything the session owns: published tools, then the child plugin. */
async function disposeSession(
  session: BackendSession,
  childDispose: () => Promise<void>,
  reason: string,
  timeoutMs: number,
): Promise<MiliastraDisposeReport> {
  const alreadyDisposed = session.state === 'disposed'
  // The cached report describes the call that did the work; this call reports
  // what IT observed, so a late dispose() sees `alreadyDisposed: true`.
  if (alreadyDisposed && session.disposeReport !== undefined) return { ...session.disposeReport, alreadyDisposed }
  const drain = await drainSession(session, reason, timeoutMs)
  if (!alreadyDisposed) {
    await waitForQuiescence(session, timeoutMs)
    session.state = 'disposed'
    // Unregister first, then close the connection: a tool that outlived its
    // transport would let the model dispatch into a dead child.
    for (const dispose of [...session.disposers.values()]) dispose()
    session.disposers.clear()
    await childDispose()
  }
  const report: MiliastraDisposeReport = { ...drain, connectionDisposed: true, alreadyDisposed }
  session.disposeReport ??= report
  return session.disposeReport
}

/** Build the resource handle T03 consumes for one session. */
function createHandle(session: BackendSession, childDispose: () => Promise<void>): MiliastraBackendResources {
  return {
    serverName: session.serverName,
    toolsPrefix: session.prefix,
    get toolNames(): readonly string[] { return [...session.published.keys()] },
    evidencePath: session.evidencePath,
    get state(): MiliastraBackendResources['state'] { return session.state },
    drain: (options = {}) => drainSession(session, options.reason ?? 'drain', options.timeoutMs ?? DEFAULT_DRAIN_TIMEOUT_MS),
    dispose: (options = {}) => disposeSession(session, childDispose,
      options.reason ?? 'dispose', options.timeoutMs ?? DEFAULT_DRAIN_TIMEOUT_MS),
  }
}

// ---------------------------------------------------------------------------
// The bridge the child plugin gets as its `tools` service
// ---------------------------------------------------------------------------

/** Refuse a registration once the composition has refused its tool table. */
function assertPublishable(session: BackendSession, publicName: string): void {
  if (!session.latched) return
  throw new Error(`miliastra(${session.serverName}): refusing to publish ${JSON.stringify(publicName)} — this composition already refused its tool table`)
}

/** The caller's own call identity, when the registry supplies one. */
function callIdOf(exec: unknown): string | undefined {
  if (exec === null || typeof exec !== 'object') return undefined
  const callId = (exec as { callId?: unknown }).callId
  return typeof callId === 'string' && callId !== '' ? callId : undefined
}

/**
 * The operationId shape the lifecycle permit accepts (`OPERATION_ID_PATTERN` in
 * `src/lifecycle.ts`, quoted from the G01 contract). Restated here because the
 * two modules do not import each other; the permit is the authority and it
 * refuses anything else with `LIFECYCLE_OPERATION_ID_INVALID`.
 */
const BUSINESS_OPERATION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/

/**
 * The ledger states in which an operation already has an answer.
 *
 * `known-complete` and `known-failed` are the two terminal states of
 * `backend/operation_state.py` -- a verified receipt has been published. Everything
 * else (`claimed`, `dispatched`, `outcome-unknown`) means the operation is in flight or
 * its outcome was never established, and the contract's IDEM-3 is explicit about those:
 * "claim present, result absent -> outcome unknown, dispatch nothing, retry forbidden."
 */
const SETTLED_OPERATION_STATES: ReadonlySet<string> = new Set(['known-complete', 'known-failed'])

/**
 * The business idempotency key for one dispatch, in the permit's own vocabulary.
 *
 * The model's `requestId` argument wins: the G01 contract makes it an alias of
 * `operationId` (`contract.json` `aliasesAcceptedOnInput`), so the permit, the
 * plugin's evidence record and the backend's journal all key on the string the
 * model actually wrote — which is what makes a `tool/call` and its `.runtime`
 * journal directory line up without a second mapping table.
 *
 * The registry's `callId` is the fallback. It is a provider-minted string and
 * may contain characters the pattern forbids (`:` is measured: the PTC bridge
 * mints `${callId}:ptc:${n}`), so it is used only when it already conforms.
 * The last resort is a minted `<serverName>-<rawName>-<n>`, which is unique per
 * composition and deliberately contains no `:` or `.`.
 *
 * @param args - the tool call's arguments, as the model wrote them.
 * @param exec - the registry execution record, when the registry supplies one.
 * @param session - the composition's bookkeeping (namespace + sequence).
 * @param published - the tool being dispatched.
 * @returns an id that satisfies `BUSINESS_OPERATION_ID_PATTERN`.
 */
function businessOperationId(
  args: unknown,
  exec: unknown,
  session: BackendSession,
  published: PublishedTool,
): string {
  const named = (args as { requestId?: unknown } | null | undefined)?.requestId
  if (typeof named === 'string' && BUSINESS_OPERATION_ID_PATTERN.test(named)) return named
  const supplied = callIdOf(exec)
  if (supplied !== undefined && BUSINESS_OPERATION_ID_PATTERN.test(supplied)) return supplied
  return `${session.serverName}-${published.rawName}-${session.dispatchSequence}`.slice(0, 80)
}

/**
 * Consult the permit before the dispatch leaves the composition.
 *
 * `granted` is the only outcome that returns. `existing` is not a failure of the
 * call — the business ledger already knows the operation — but from here it is
 * indistinguishable from a dispatch that must not happen, so it is refused with
 * the ledger state named and the model is expected to report it. `refused`
 * (draining, starting, or the ledger unavailable) is counted like every other
 * refused dispatch.
 *
 * @param session - the composition's bookkeeping, for the refusal counter.
 * @param published - the tool being dispatched.
 * @param gate - the permit, when the plugin supplied one.
 * @param operationId - the id the permit is asked about.
 * @throws MiliastraDispatchRefusedError when the permit is not `granted`.
 */
async function admitDispatch(
  session: BackendSession,
  published: PublishedTool,
  gate: MiliastraDispatchGate | undefined,
  operationId: string,
): Promise<void> {
  if (gate === undefined) return
  let admission: Awaited<ReturnType<MiliastraDispatchGate>>
  try {
    admission = await gate({ operationId, capabilityId: published.rawName })
  } catch (error) {
    // The permit does not only return: it *throws* for two conditions that both
    // mean "do not dispatch" — an id this instance already admitted
    // (`LIFECYCLE_OPERATION_ALREADY_ACTIVE`, measured) and an unreadable ledger
    // (`LIFECYCLE_LEDGER_UNAVAILABLE`, `src/ledger-port.ts`). Neither may escape
    // as a lifecycle error the tool layer has no mapping for, and neither may
    // fall through to the transport, so both are counted and surfaced as a
    // refusal. NOTE: refusing here is a deliberate choice for a repeat of the
    // SAME operationId from the SAME instance; the alternative — letting it
    // through so the backend replays the original receipt through
    // `consult_journal` — is a contract decision, not a bug fix. See
    // handoff.md "open decision (a)".
    session.refusedDispatches += 1
    throw new MiliastraDispatchRefusedError(published.publicName,
      `the lifecycle refused the dispatch permit for ${operationId}: `
      + (error instanceof Error ? error.message : String(error)))
  }
  if (admission.kind === 'granted') return
  if (admission.kind === 'existing') {
    // IDEM-1: "same operationId + same bound command -> replay the original receipt,
    // dispatch nothing." A SETTLED operation must therefore NOT be refused here: the
    // dispatch has to reach the backend, where `consult_journal` owns the command
    // comparison and either replays the original receipt (same command) or refuses
    // `REQUEST_ID_CONFLICT` (a different one).
    //
    // Why the comparison is not made here: this module asks the permit about
    // `{operationId, capabilityId}` and the ledger view it reads carries no binding, so
    // reproducing `operation_state.binding_for` / `binding_digest` in TypeScript would
    // be a SECOND fingerprint of the same command -- and `contract.json`'s
    // `idempotency.description` says of author.py's rules, "The business layer must not
    // weaken or duplicate them." A capabilityId-only comparison would be worse than
    // none: `mw_scene_save_level` shares one capabilityId across every level, so it
    // would call a different command "the same" and replay a receipt that does not
    // describe it.
    if (SETTLED_OPERATION_STATES.has(admission.operationState)) return
    session.refusedDispatches += 1
    throw new MiliastraDispatchRefusedError(published.publicName,
      `the business ledger carries operation ${operationId} as ${admission.operationState}, `
      + 'which is not a settled outcome: nothing is dispatched and the operation must be '
      + 'reconciled instead of re-sent')
  }
  session.refusedDispatches += 1
  throw new MiliastraDispatchRefusedError(published.publicName,
    `the lifecycle refused the dispatch permit for ${operationId} (${admission.code})`)
}

/** Wrap one write tool's execute with the operation ledger and the drain gate. */
function wrapWrite(
  session: BackendSession,
  definition: BridgedToolDefinition,
  published: PublishedTool,
  gate: MiliastraDispatchGate | undefined,
): BridgedToolDefinition['execute'] {
  const inner = definition.execute
  return async (args: unknown, exec: unknown) => {
    if (session.latched) {
      session.refusedDispatches += 1
      throw new MiliastraDispatchRefusedError(published.publicName, 'the composition refused its tool table')
    }
    if (session.state !== 'ready' && session.state !== 'starting') {
      session.refusedDispatches += 1
      throw new MiliastraDispatchRefusedError(published.publicName, `the composition is ${session.state}`)
    }
    session.dispatchSequence += 1
    const operationId = businessOperationId(args, exec, session, published)
    await admitDispatch(session, published, gate, operationId)
    const operation: MiliastraPendingOperation = {
      operationId,
      toolName: published.publicName,
      rawName: published.rawName,
      startedAtUtc: new Date().toISOString(),
      state: 'in-flight',
      detail: null,
    }
    session.operations.set(operationId, operation)
    try {
      const result = await inner(args, exec)
      session.operations.delete(operationId)
      return result
    } catch (error) {
      // Unknown, not failed: the write may or may not have reached the backend.
      // Recorded for reconciliation; never re-sent by this module, and never
      // re-sent by the client's reconnect either.
      session.operations.set(operationId, {
        ...operation,
        state: 'unknown',
        detail: error instanceof Error ? error.message : String(error),
      })
      throw error
    }
  }
}

/**
 * Create the bridge the child plugin receives as its `tools` service.
 *
 * Every registration is forwarded to the real registry (so the model reads the
 * real table), after the write gate wraps a write tool's execute. `get` and
 * `schemas` are forwarded when the registry offers them, so the client's own
 * opportunistic reads keep working.
 *
 * @param session - the composition's bookkeeping.
 * @returns the service value to provide for the child's `tools`.
 */
function createBridge(session: BackendSession, gate: MiliastraDispatchGate | undefined): ToolRegistryLike {
  const registry = session.registry
  return {
    register(definition: unknown): () => void {
      const typed = definition as BridgedToolDefinition
      assertPublishable(session, typed.name)
      const published = toPublishedTool(session.serverName, typed)
      // Reads pass through untouched; writes and anything the contract does not
      // name are gated (fail closed: an unknown tool is treated as a write).
      const forwarded = published.classification === 'read'
        ? typed
        : { ...typed, execute: wrapWrite(session, typed, published, gate) }
      const registryDispose = registry.register(forwarded)
      const dispose = (): void => {
        session.published.delete(published.publicName)
        session.disposers.delete(published.publicName)
        registryDispose()
      }
      session.published.set(published.publicName, published)
      session.disposers.set(published.publicName, dispose)
      return dispose
    },
    get: registry.get === undefined
      ? undefined
      : (name: string, scope?: unknown) => registry.get?.(name, scope),
    schemas: registry.schemas === undefined
      ? undefined
      : (scope?: unknown) => registry.schemas?.(scope) ?? [],
  }
}

// ---------------------------------------------------------------------------
// Composition
// ---------------------------------------------------------------------------

/** Live resources per composition, keyed by the plugin instance's context. */
const backendSessions = new WeakMap<object, MiliastraBackendResources>()

/**
 * The resource handle of the backend composed on `ctx`, if any.
 *
 * T03's lifecycle controller reads this to drain and release the composition it
 * is shutting down. The plugin instance's own fiber also disposes it (see
 * {@link composeBackend}), so a composition is never left to the collector.
 *
 * @param ctx - the plugin instance context, or any context derived from it.
 * @returns the handle, or undefined when no backend was composed here.
 */
export function backendResources(ctx: Context): MiliastraBackendResources | undefined {
  let current: unknown = ctx
  while (current !== undefined && current !== null) {
    const found = backendSessions.get(current as object)
    if (found !== undefined) return found
    current = (current as { parent?: unknown }).parent
  }
  return undefined
}

/** One composition record appended to the evidence file. */
interface EvidenceRecord {
  readonly schemaVersion: number
  readonly kind: 'miliastra-backend-composition'
  readonly atUtc: string
  readonly state: MiliastraBackendStatus['state']
  readonly serverName: string
  readonly detail: string | null
  readonly mapping: Readonly<Record<string, unknown>>
  readonly required: {
    readonly missing: readonly string[]
    readonly unexpected: readonly string[]
  }
  readonly tools: readonly PublishedTool[]
  readonly registry: {
    readonly observable: boolean
    readonly names: readonly string[]
    readonly mismatches: readonly string[]
  }
  readonly ledger: {
    readonly unknownOperations: readonly MiliastraPendingOperation[]
    readonly refusedDispatches: number
  }
}

/** The Config→MCP Config mapping, as the evidence reports it. */
function mappingRecord(config: ResolvedMiliastraConfig): Readonly<Record<string, unknown>> {
  const stdio = buildBackendStdioConfig(config)
  return {
    transport: 'stdio',
    command: stdio.command,
    args: [...stdio.args],
    cwd: stdio.cwd,
    envAllowlist: { ...BACKEND_ENV_ALLOWLIST },
    toolCallTimeoutMs: stdio.toolCallTimeoutMs,
    failOnStartupError: stdio.failOnStartupError,
    reconnect: { ...BACKEND_RECONNECT_POLICY },
  }
}

/**
 * Append the composition record.
 *
 * A failure to write evidence fails the composition: without the record there
 * is nothing to re-compute the published table from, so the composition must
 * not claim `ready`. The caller revokes what it published.
 */
function writeEvidence(session: BackendSession, record: EvidenceRecord): void {
  mkdirSync(dirname(session.evidencePath), { recursive: true })
  appendFileSync(session.evidencePath, `${JSON.stringify(record)}\n`, 'utf8')
}

/** Build the evidence record for one finished composition attempt. */
function evidenceRecord(
  session: BackendSession,
  config: ResolvedMiliastraConfig,
  status: MiliastraBackendStatus,
  missing: readonly string[],
  unexpected: readonly string[],
): EvidenceRecord {
  const registry = registryToolNames(session.registry)
  const mismatches: string[] = []
  if (registry.observable) {
    for (const name of session.published.keys()) {
      if (!registry.names.includes(name)) mismatches.push(`${name}: published but not visible in the registry`)
    }
  }
  return {
    schemaVersion: BACKEND_EVIDENCE_VERSION,
    kind: 'miliastra-backend-composition',
    atUtc: new Date().toISOString(),
    state: status.state,
    serverName: config.serverName,
    detail: status.detail,
    mapping: mappingRecord(config),
    required: { missing, unexpected },
    tools: [...session.published.values()],
    registry: { observable: registry.observable, names: registry.names, mismatches },
    ledger: {
      unknownOperations: operationBuckets(session).unknown,
      refusedDispatches: session.refusedDispatches,
    },
  }
}

/**
 * Compose the business backend for one plugin instance.
 *
 * The child plugin is the vendored MCP client, created on a context whose
 * `tools` service is this composition's bridge, so the client's registrations
 * pass through the write gate while the model still reads the same registry.
 *
 * @param ctx - the plugin instance context (carries the injected `tools` service).
 * @param config - frozen resolved config.
 * @param gate - the dispatch permit. Supplied by `src/index.ts` from the mounted
 * lifecycle controller; when present, every write the table exposes is admitted
 * through it before the transport sees it.
 * @returns the status of what was actually published.
 * @throws MiliastraBackendError when the composition cannot be made honest.
 */
export async function composeBackend(
  ctx: Context,
  config: ResolvedMiliastraConfig,
  gate?: MiliastraDispatchGate,
): Promise<MiliastraBackendStatus> {
  const registry = asRegistry(ctx.get('tools'))
  if (registry === undefined) {
    throw new MiliastraBackendError('BACKEND_TOOLS_SERVICE_UNUSABLE', config.serverName,
      'the injected tools service is not a registry this composition can publish into')
  }

  // Pre-spawn refusals: a backend directory that cannot name a Python module,
  // or that holds no entry, is a composition mistake and must not be
  // discovered by spawning an interpreter and reading a traceback.
  const modulePath = backendModulePath(config.backendRoot)
  const entryPath = backendEntryPath(config.backendRoot)
  if (!existsSync(entryPath)) {
    throw new MiliastraBackendError('BACKEND_ENTRY_MISSING', entryPath,
      `does not exist; the fixed business entry for module ${modulePath} is missing`)
  }

  const session: BackendSession = {
    serverName: config.serverName,
    prefix: toolNamePrefix(config.serverName),
    evidencePath: backendEvidencePath(config),
    registry,
    published: new Map(),
    disposers: new Map(),
    operations: new Map(),
    state: 'starting',
    latched: false,
    refusedDispatches: 0,
    dispatchSequence: 0,
    disposeReport: undefined,
  }

  // The child gets its own view of `tools`, so its registrations pass through
  // the gate; every other service (logger, and anything the client reads
  // opportunistically) still resolves normally.
  //
  // The bridge is provided in a service scope of its own, on the ROOT context.
  // Two measured reasons, not preference: a service provided from a fiber that
  // is still loading is invisible to plugins started beneath it (Cordis'
  // `ReflectService._getImpl` refuses an implementation whose fiber is not
  // ACTIVE yet, so the child would sit PENDING and never connect), and
  // `ctx.root`'s fiber is always active. The scope label is a fresh symbol per
  // composition, so the bridge is reachable only from the child created below
  // it — no other plugin, and no other composition, resolves it.
  const scope: unique symbol = Symbol('miliastra.backend.tools')
  const bridgeContext = ctx.root.isolate('tools', scope)
  const releaseBridge = bridgeContext.provide('tools', createBridge(session, gate))

  let childFiber: { dispose(): Promise<void> } | undefined
  try {
    const fiber = bridgeContext.plugin(mcpClient as never, buildBackendStdioConfig(config) as never)
    await fiber
    childFiber = fiber as unknown as { dispose(): Promise<void> }
  } catch (error) {
    const detail = errorDetail(error)
    const status: MiliastraBackendStatus = {
      state: 'failed',
      serverName: null,
      tools: [],
      detail: `backend did not start: ${detail}`,
    }
    await releaseBridge()
    writeEvidence(session, evidenceRecord(session, config, status, [], []))
    return status
  }

  session.state = 'ready'
  const toolNames = [...session.published.keys()]
  const missing = REQUIRED_BUSINESS_TOOLS
    .map(rawName => expectedPublicToolName(config.serverName, rawName))
    .filter(publicName => !toolNames.includes(publicName))
  const unexpected = [...session.published.values()]
    .filter(tool => tool.classification === 'unexpected')
    .map(tool => tool.publicName)

  const handle = createHandle(session, async () => {
    await childFiber?.dispose()
    await releaseBridge()
  })
  backendSessions.set(ctx, handle)

  if (missing.length > 0) {
    // A partial table is worse than none: refuse it, so the model can never
    // see a business surface this composition would not itself call ready.
    session.state = 'draining'
    session.latched = true
    for (const dispose of [...session.disposers.values()]) dispose()
    session.disposers.clear()
    session.published.clear()
    const status: MiliastraBackendStatus = {
      state: 'unavailable',
      serverName: null,
      tools: [],
      detail: `business tool table incomplete: missing ${missing.join(', ')}`,
    }
    writeEvidence(session, evidenceRecord(session, config, status, missing, unexpected))
    // The refused composition still owns a live connection; release it, so an
    // unavailable backend never keeps a child process around.
    await handle.dispose({ reason: 'incomplete-tool-table' })
    return status
  }

  // The safety net: whatever else happens, the plugin instance's fiber owns
  // this composition's tools and child process.
  ctx.effect(() => () => handle.dispose({ reason: 'plugin-fiber-disposed' }), 'miliastra.backend')

  // Drift is reported, never corrected here: a tool the contract does not name
  // is published (the model may legitimately need a new backend tool) but it is
  // named in the evidence, named in the status detail, and gated as a write.
  const status: MiliastraBackendStatus = {
    state: 'ready',
    serverName: config.serverName,
    tools: toolNames,
    detail: unexpected.length === 0
      ? null
      : `published ${unexpected.length} tool(s) outside the business contract: ${unexpected.join(', ')}`,
  }

  try {
    writeEvidence(session, evidenceRecord(session, config, status, missing, unexpected))
  } catch (error) {
    await handle.dispose({ reason: 'evidence-write-failed' })
    throw new MiliastraBackendError('EVIDENCE_WRITE_FAILED', session.evidencePath,
      'could not record the composition evidence', { cause: error })
  }

  return status
}
