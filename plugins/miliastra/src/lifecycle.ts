/**
 * T03 — plugin lifecycle, cancellation, and unload for `@miliastra/dsh-miliastra`.
 *
 * ## What this module is, and what it is not
 *
 * It is the **one** place that decides whether this plugin instance is allowed
 * to hand a caller a dispatch permit, and the **one** place that decides what an
 * unload releases. It is not a second connection controller: the MCP child
 * process, its timers, its listeners and its namespace belong to the vendored
 * `@deepseek-ai/dsh-mcp-client` and are disposed by Cordis effects. This module
 * only *tracks* them so that an unload can report what it released, what it
 * deliberately left alone, and what it could not release in time.
 *
 * It is also not a second ledger. The authoritative lifecycle state of a
 * business operation is `operationState` on the business ledger (T06 / DS-08);
 * this module **reads** it through {@link MiliastraBusinessLedgerPort} and never
 * writes a competing truth. `reconcileState` and the model-facing `state` are
 * computed here as projections, by the total functions the G01 contract fixes
 * (`plugins/miliastra/contracts/contract.json` → `businessState.projection` and
 * `reconcileState.projection`) — never by an `if`/`else`, so the three
 * vocabularies cannot drift apart.
 *
 * ## Dependency status (2026-10-02, DS-07)
 *
 * T02's `src/backend.ts` (DS-06) and T06's ledger (DS-08) do not exist yet. This
 * module therefore depends on them **only through the ports declared here** and
 * carries no import of either. {@link MiliastraBusinessLedgerPort} is the frozen
 * shape of DS-08's read/observe surface; {@link MiliastraResource} is the frozen
 * shape of DS-06's resource handle. `fixtures/t03-fake-ledger.ts` and
 * `fixtures/t03-resources.ts` are executable stand-ins for both, and
 * `fixtures/t03-interface-samples.json` freezes the outcome objects a consumer
 * may read before this implementation landed. When DS-06/DS-08 merge, the joint
 * test is: swap the fixture for the real port and re-run `tests/lifecycle.spec.ts`
 * unchanged — nothing else in this file may need editing.
 *
 * ## Signature summary (the contract a consumer codes against)
 *
 * ```ts
 * createMiliastraLifecycle(options)            -> MiliastraLifecycleController
 * controller.phase()                           -> 'starting' | 'ready' | 'draining' | 'disposed'
 * controller.transition(to)                    -> void            (throws on an illegal move)
 * controller.markReady(status)                 -> void            (starting -> ready only)
 * controller.registerResource(resource)        -> void            (own requires release; external must not have one)
 * controller.beginOperation(request)           -> MiliastraDispatchAdmission   (the ONLY dispatch permit)
 * controller.cancel(operationId)               -> MiliastraCancellationOutcome (never dispatches)
 * controller.deliverReceipt(observation)       -> MiliastraLateReceiptOutcome  (never reactivates)
 * controller.pendingOperations()               -> readonly MiliastraOpenOperation[]
 * controller.resourceTable()                   -> readonly MiliastraResourceRow[]
 * controller.dispose(options?)                 -> MiliastraDisposeReport        (idempotent)
 * ```
 *
 * ## Refusal semantics (the three that matter)
 *
 * 1. **Write after begin-drain** — `beginOperation()` in `draining`/`disposed`
 *    returns `kind: 'refused'`, `state: 'rejected'`, `writeExecuted: false`,
 *    `code: 'LIFECYCLE_WRITE_REFUSED_DRAINING'`. Nothing is read, nothing is
 *    dispatched, the ledger is not even consulted.
 * 2. **Cancel before submit** — `cancel()` on an operation whose ledger row is
 *    `never-claimed` returns `state: 'rejected'` with error code
 *    `CANCELLED_BEFORE_DISPATCH` (`refusal-before-dispatch` / `before-dispatch` /
 *    `sideEffect: 'none'`). This module has no dispatch function at all, so the
 *    "zero dispatch" claim is structural, not a promise.
 * 3. **Cancel after submit** — `cancel()` on `claimed`/`dispatched` returns
 *    `state: 'pending'`, and on `outcome-unknown` returns `state: 'unknown'` with
 *    a `reconcile` route. It never returns `rejected`, never sets
 *    `writeExecuted: false`, and never claims a rollback.
 *
 * @module @miliastra/dsh-miliastra/lifecycle
 */

// ---------------------------------------------------------------------------
// 1. Closed vocabularies. Every set below is quoted from the G01 contract, not
//    invented here. Widening any of them locally is a contract break.
// ---------------------------------------------------------------------------

/**
 * The plugin instance phase. Closed 4-value set; T03.md §4 step 02.
 *
 * - `starting` — `apply()` has begun; nothing is published yet.
 * - `ready` — the backend reported a live tool surface; permits may be granted.
 * - `draining` — unloading has begun; new writes are refused, the ledger is
 *   still readable so the mainline can reconcile.
 * - `disposed` — unload finished. Terminal.
 */
export type MiliastraLifecyclePhase = 'starting' | 'ready' | 'draining' | 'disposed'

/** {@link MiliastraLifecyclePhase} as a runtime-checkable tuple. */
export const MILIASTRA_LIFECYCLE_PHASES = ['starting', 'ready', 'draining', 'disposed'] as const

/**
 * Legal phase moves. Anything not listed — including every self-transition — is
 * refused by {@link assertTransition} with `LIFECYCLE_ILLEGAL_TRANSITION`.
 *
 * `starting -> disposed` is the activation-failure path (nothing registered, so
 * nothing to drain). `starting -> draining` is a shutdown that arrived before
 * activation completed. There is deliberately no path back into `starting` or
 * `ready`: a drained instance is never resurrected, it is replaced.
 */
export const LEGAL_LIFECYCLE_TRANSITIONS: Readonly<
  Record<MiliastraLifecyclePhase, readonly MiliastraLifecyclePhase[]>
> = Object.freeze({
  starting: Object.freeze(['ready', 'draining', 'disposed'] as const),
  ready: Object.freeze(['draining'] as const),
  draining: Object.freeze(['disposed'] as const),
  disposed: Object.freeze([] as const),
})

/** The authoritative per-operation state, quoted from `contract.json` `operationState`. */
export type MiliastraOperationState =
  | 'never-claimed'
  | 'claimed'
  | 'dispatched'
  | 'known-complete'
  | 'known-failed'
  | 'outcome-unknown'

/** The model-facing verdict, quoted from `contract.json` `businessState`. */
export type MiliastraBusinessState = 'rejected' | 'pending' | 'unknown' | 'failed' | 'completed'

/** T06's read-time projection, quoted from `contract.json` `reconcileState`. */
export type MiliastraReconcileState = 'never-claimed' | 'known-success' | 'known-failure' | 'unknown'

/** Recovery guidance, quoted from `contract.json` `nextAction`. */
export type MiliastraNextAction =
  | 'none'
  | 'fix-input'
  | 'poll-same-operation'
  | 'reconcile'
  | 'report-and-repair'
  | 'await-human'

/**
 * `operationState` -> `state`. A total function written as a lookup table, so no
 * call site can invent a mapping (G01 D6, contract.json `businessState.projection`).
 */
export const BUSINESS_STATE_BY_OPERATION_STATE: Readonly<
  Record<MiliastraOperationState, MiliastraBusinessState>
> = Object.freeze({
  'never-claimed': 'rejected',
  claimed: 'pending',
  dispatched: 'pending',
  'known-complete': 'completed',
  'known-failed': 'failed',
  'outcome-unknown': 'unknown',
})

/**
 * `operationState` -> `reconcileState`. Same rule: a table, never a branch
 * (G01 D5, contract.json `reconcileState.projection`).
 */
export const RECONCILE_STATE_BY_OPERATION_STATE: Readonly<
  Record<MiliastraOperationState, MiliastraReconcileState>
> = Object.freeze({
  'never-claimed': 'never-claimed',
  claimed: 'unknown',
  dispatched: 'unknown',
  'known-complete': 'known-success',
  'known-failed': 'known-failure',
  'outcome-unknown': 'unknown',
})

/** `state` -> `nextAction` for the non-completed verdicts (contract.json `businessState.nextActionFor`). */
export const NEXT_ACTION_BY_BUSINESS_STATE: Readonly<
  Record<MiliastraBusinessState, MiliastraNextAction>
> = Object.freeze({
  rejected: 'fix-input',
  pending: 'poll-same-operation',
  unknown: 'reconcile',
  failed: 'report-and-repair',
  completed: 'none',
})

/**
 * Project an authoritative operation state onto the model-facing verdict.
 * @param operationState - the authoritative state read from the ledger.
 * @returns the business verdict.
 */
export function toBusinessState(operationState: MiliastraOperationState): MiliastraBusinessState {
  return BUSINESS_STATE_BY_OPERATION_STATE[operationState]
}

/**
 * Project an authoritative operation state onto T06's reconcile vocabulary.
 * @param operationState - the authoritative state read from the ledger.
 * @returns the reconcile state.
 */
export function toReconcileState(operationState: MiliastraOperationState): MiliastraReconcileState {
  return RECONCILE_STATE_BY_OPERATION_STATE[operationState]
}

/**
 * `outcomeKnown` is false exactly for `pending` and `unknown` (tool-result schema,
 * `additionalProperties: false` block 2).
 * @param state - the business verdict.
 * @returns whether the outcome is established.
 */
export function isOutcomeKnown(state: MiliastraBusinessState): boolean {
  return state !== 'pending' && state !== 'unknown'
}

/**
 * Return whether one phase move is legal.
 * @param from - current phase.
 * @param to - proposed phase.
 * @returns true when the move is listed in {@link LEGAL_LIFECYCLE_TRANSITIONS}.
 */
export function canTransition(from: MiliastraLifecyclePhase, to: MiliastraLifecyclePhase): boolean {
  return LEGAL_LIFECYCLE_TRANSITIONS[from].includes(to)
}

// ---------------------------------------------------------------------------
// 2. Errors. One class, closed code set, no string matching in callers.
// ---------------------------------------------------------------------------

/** Stable failure codes for this module. */
export type MiliastraLifecycleErrorCode =
  /** A phase move that {@link LEGAL_LIFECYCLE_TRANSITIONS} does not list. */
  | 'LIFECYCLE_ILLEGAL_TRANSITION'
  /** A write was attempted before the instance became ready. */
  | 'LIFECYCLE_NOT_READY'
  /** A resource was declared in a way that could make an unload dangerous. */
  | 'LIFECYCLE_RESOURCE_MISDECLARED'
  /** The same operationId was admitted twice through one instance. */
  | 'LIFECYCLE_OPERATION_ALREADY_ACTIVE'
  /** The operationId is not a shape the ledger contract accepts. */
  | 'LIFECYCLE_OPERATION_ID_INVALID'
  /** A late receipt arrived for an operation the ledger does not know. */
  | 'LIFECYCLE_RECEIPT_UNKNOWN_OPERATION'
  /** The ledger port could not be read; the caller must not guess. */
  | 'LIFECYCLE_LEDGER_UNAVAILABLE'
  /** `dispose()` was re-entered with a different configuration mid-flight. */
  | 'LIFECYCLE_DISPOSE_IN_PROGRESS'

/** A lifecycle rule violation. Always thrown before any side effect. */
export class MiliastraLifecycleError extends Error {
  /** Machine-checkable reason. */
  readonly code: MiliastraLifecycleErrorCode
  /** Phase the violation was detected in. */
  readonly phase: MiliastraLifecyclePhase
  /** The move that was refused, when the violation is a transition. */
  readonly requested: MiliastraLifecyclePhase | null

  constructor(
    code: MiliastraLifecycleErrorCode,
    phase: MiliastraLifecyclePhase,
    detail: string,
    requested: MiliastraLifecyclePhase | null = null,
  ) {
    super(requested === null ? `${code}: ${detail}` : `${code}: ${phase} -> ${requested} ${detail}`)
    this.name = 'MiliastraLifecycleError'
    this.code = code
    this.phase = phase
    this.requested = requested
  }
}

/**
 * Return the phase a legal move leads to, or throw.
 * @param from - current phase.
 * @param to - proposed phase.
 * @returns `to`.
 * @throws MiliastraLifecycleError `LIFECYCLE_ILLEGAL_TRANSITION` when the move is not listed.
 */
export function assertTransition(
  from: MiliastraLifecyclePhase,
  to: MiliastraLifecyclePhase,
): MiliastraLifecyclePhase {
  if (!canTransition(from, to)) {
    throw new MiliastraLifecycleError('LIFECYCLE_ILLEGAL_TRANSITION', from,
      `is not a legal transition; legal moves are ${LEGAL_LIFECYCLE_TRANSITIONS[from].join(', ') || '(none)'}`, to)
  }
  return to
}

// ---------------------------------------------------------------------------
// 3. Ports. The frozen half of the DS-06 / DS-08 boundary.
// ---------------------------------------------------------------------------

/**
 * The G01 `operationId` shape: `^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$`
 * (`ledger-record.schema.json`, `tool-result.schema.json`).
 */
export const OPERATION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/

/**
 * What this module needs to know about one operation. A projection of
 * `ledger-record.schema.json`; T06/DS-08 owns the row, the storage and the
 * discrimination between `claimed` and `dispatched`.
 *
 * `dispatchEvidence` is **required**, not optional. An empty array means "looked,
 * found nothing" — the only thing that may produce `claimed` (contract.json
 * `OPS-4`). A ledger that cannot answer this must fail the read instead of
 * returning `claimed`.
 */
export interface MiliastraOperationView {
  /** Business idempotency key. */
  readonly operationId: string
  /** Authoritative state; the only truth. */
  readonly operationState: MiliastraOperationState
  /** Where the row lives, for the reconcile route handed to the model. */
  readonly ledgerRef: string
  /** The named files whose presence moved `claimed` -> `dispatched`. */
  readonly dispatchEvidence: readonly string[]
  /** Bottom-layer requestId once one exists; null while it does not. */
  readonly requestId: string | null
  /** Journal directory for the raw receipt; null while there is none. */
  readonly journalRef: string | null
  /** true only with observed evidence that a write reached the target. */
  readonly writeExecuted: boolean | null
}

/**
 * A late or out-of-band receipt handed to the ledger. This module never
 * interprets it: it records the observation and relays what the ledger decides.
 * `recordObservation` must not create an operation and must not dispatch.
 */
export interface MiliastraOperationObservation {
  /** Operation the receipt belongs to. */
  readonly operationId: string
  /** Bottom-layer requestId the receipt carries, when it carries one. */
  readonly requestId: string | null
  /** Project-relative or journal-relative reference to the raw receipt. */
  readonly receiptRef: string
  /** ISO-8601 instant the receipt was observed. */
  readonly observedUtc: string
  /** Human-readable note. Free text; never parsed. */
  readonly detail: string | null
}

/**
 * The DS-08 / T06 surface this module depends on. Deliberately minimal: the
 * lifecycle controller has no business adjudicating a receipt, and no ability to
 * create or re-dispatch an operation.
 */
export interface MiliastraBusinessLedgerPort {
  /**
   * Read one operation. Read-only by contract: an implementation that dispatches
   * here is a defect, not an optimisation. Returns null when the operation has
   * never been claimed in this ledger.
   */
  readOperation(operationId: string): MiliastraOperationView | null | Promise<MiliastraOperationView | null>
  /**
   * Record an observation against an **existing** operation and return the row
   * as the ledger now adjudicates it. Must not create an operation; an
   * implementation may throw for an unknown id.
   */
  recordObservation(
    observation: MiliastraOperationObservation,
  ): MiliastraOperationView | Promise<MiliastraOperationView>
  /**
   * Optional. Enumerate the operations the ledger still considers open
   * (`claimed` / `dispatched` / `outcome-unknown`). A reloaded instance needs
   * this to learn what the previous instance left behind; without it,
   * {@link MiliastraLifecycleController.pendingOperations} can only report the
   * operations the caller names explicitly. Read-only, like `readOperation`.
   */
  listOpenOperations?(): readonly MiliastraOperationView[] | Promise<readonly MiliastraOperationView[]>
}

/** The three states an operation can be in and still need reconciliation. */
export const RESUMABLE_OPERATION_STATES: readonly MiliastraOperationState[] = Object.freeze([
  'claimed',
  'dispatched',
  'outcome-unknown',
])

/** What kind of thing a resource is. */
export type MiliastraResourceKind =
  // Resources this plugin creates and must release.
  | 'mcp-connection'
  | 'tool-registration'
  | 'namespace-reservation'
  | 'listener'
  | 'timer'
  | 'temp-dir'
  | 'child-plugin'
  // Resources that belong to the user or to another process and must survive.
  | 'game-process'
  | 'editor-process'
  | 'elevated-helper'
  | 'editor-bridge'

/**
 * Kinds that may only ever be declared `external`. An `own` declaration for one
 * of these is refused at registration ({@link MiliastraLifecycleError}
 * `LIFECYCLE_RESOURCE_MISDECLARED`): "the plugin may kill the game" must be
 * unrepresentable rather than merely discouraged (EXECUTION-CONTRACT.md:49).
 */
export const EXTERNAL_ONLY_RESOURCE_KINDS: readonly MiliastraResourceKind[] = Object.freeze([
  'game-process',
  'editor-process',
  'elevated-helper',
  'editor-bridge',
])

/** Who created a resource, and therefore who may release it. */
export type MiliastraResourceOwnership =
  /** Created by this plugin instance; released by {@link MiliastraLifecycleController.dispose}. */
  | 'own'
  /** Created by the user or another process; never released by this plugin. */
  | 'external'

/** One entry in the resource table (T03.md §4 step 01). */
export interface MiliastraResource {
  /** Stable id, unique within one controller. */
  readonly id: string
  /** What it is. */
  readonly kind: MiliastraResourceKind
  /** Who owns it. */
  readonly ownership: MiliastraResourceOwnership
  /** Provenance string for the table, e.g. `mcp-client:transport`. */
  readonly createdBy: string
  /**
   * The release function. **Required** for `own`, **forbidden** for `external`
   * (a supplied one would be dead code that eventually gets called by mistake).
   */
  readonly release?: () => void | Promise<void>
}

/** One row of {@link MiliastraLifecycleController.resourceTable}. */
export interface MiliastraResourceRow {
  readonly id: string
  readonly kind: MiliastraResourceKind
  readonly ownership: MiliastraResourceOwnership
  readonly createdBy: string
  /** Whether a release function was declared. */
  readonly releasable: boolean
  /** How many times the release function has actually run (0 or 1). */
  readonly releaseCount: number
}

// ---------------------------------------------------------------------------
// 4. Outcome shapes. These are the objects a consumer (DS-06 backend, the
//    mainline coordinator) reads. Frozen samples live in
//    `fixtures/t03-interface-samples.json`.
// ---------------------------------------------------------------------------

/** An error view shaped like `tool-result.schema.json#/$defs/error`. */
export interface MiliastraLifecycleErrorView {
  readonly code: 'CANCELLED_BEFORE_DISPATCH'
  readonly disposition: 'refusal-before-dispatch'
  readonly phase: 'before-dispatch'
  readonly sideEffect: 'none'
  readonly message: string
  readonly operationId: string | null
  readonly reconcile: null
}

/** The route a caller needs to reconcile an unsettled operation (G01 D31). */
export interface MiliastraReconcileRoute {
  readonly operationId: string
  readonly ledgerRef: string
  readonly requestId: string | null
  readonly journalRef: string | null
}

/** One operation this instance knows about and has not resolved. */
export interface MiliastraOpenOperation {
  readonly operationId: string
  readonly operationState: MiliastraOperationState
  readonly state: MiliastraBusinessState
  readonly reconcileState: MiliastraReconcileState
  readonly outcomeKnown: boolean
  readonly writeExecuted: boolean | null
  readonly dispatchEvidence: readonly string[]
  readonly requestId: string | null
  readonly journalRef: string | null
  readonly ledgerRef: string
  readonly nextAction: MiliastraNextAction
  readonly reconcile: MiliastraReconcileRoute
  /** Always false: no layer in this project retries automatically (G01 D22). */
  readonly retryAttempted: false
}

/** What a caller asks for before dispatching anything. */
export interface MiliastraOperationRequest {
  /** Business idempotency key; the caller's, not this module's. */
  readonly operationId: string
  /** Business capability id, e.g. `entity.create`. */
  readonly capabilityId: string
  /** Case id, carried through to the ledger. */
  readonly caseId?: string | null
}

/**
 * The outcome of asking for a dispatch permit.
 *
 * The union is the safety property: there is no member that both carries a
 * ledger row and permits a dispatch. A reloaded instance that asks about an
 * operation the ledger already knows gets `existing` — it is structurally
 * unable to re-dispatch it (§T03 step 08, G01 LIFE-3).
 */
export type MiliastraDispatchAdmission =
  | {
      /** The caller may dispatch this operation exactly once. */
      readonly kind: 'granted'
      readonly operationId: string
      readonly capabilityId: string
      readonly phase: 'ready'
      readonly operationState: 'never-claimed'
      readonly writeExecuted: false
      readonly dispatchEvidence: readonly []
      readonly retryAttempted: false
      readonly grantedUtc: string
    }
  | {
      /** The ledger already knows this operation. Report it; dispatch nothing. */
      readonly kind: 'existing'
      readonly operationId: string
      readonly capabilityId: string
      readonly phase: MiliastraLifecyclePhase
      readonly operationState: MiliastraOperationState
      readonly state: MiliastraBusinessState
      readonly reconcileState: MiliastraReconcileState
      readonly outcomeKnown: boolean
      readonly writeExecuted: boolean | null
      readonly dispatchEvidence: readonly string[]
      readonly retryAttempted: false
      /** True only when the ledger reports a terminal success/failure already recorded. */
      readonly replayed: boolean
      readonly nextAction: MiliastraNextAction
      readonly reconcile: MiliastraReconcileRoute
      readonly reason: string
    }
  | {
      /** Refused before the ledger was consulted. Nothing was read, written or sent. */
      readonly kind: 'refused'
      readonly operationId: string
      readonly capabilityId: string
      readonly phase: MiliastraLifecyclePhase
      readonly code: 'LIFECYCLE_NOT_READY' | 'LIFECYCLE_WRITE_REFUSED_DRAINING'
      readonly state: 'rejected'
      readonly reconcileState: 'never-claimed'
      readonly outcomeKnown: true
      readonly writeExecuted: false
      readonly dispatchEvidence: readonly []
      readonly retryAttempted: false
      readonly nextAction: 'fix-input'
      readonly reconcile: null
      readonly reason: string
    }

/**
 * The outcome of a cancellation. `cancel()` **never dispatches**, so there is no
 * `dispatchPermitted` field to misuse — the only question is what the operation's
 * already-recorded state is.
 */
export interface MiliastraCancellationOutcome {
  readonly operationId: string
  /** Phase this instance was in when the cancel was evaluated. */
  readonly phase: MiliastraLifecyclePhase
  readonly operationState: MiliastraOperationState
  readonly state: MiliastraBusinessState
  readonly reconcileState: MiliastraReconcileState
  readonly outcomeKnown: boolean
  readonly writeExecuted: boolean | null
  readonly dispatchEvidence: readonly string[]
  /** Always false: this call dispatched nothing. */
  readonly dispatched: false
  /** Null unless the operation was rejected before any dispatch evidence existed. */
  readonly error: MiliastraLifecycleErrorView | null
  /**
   * Present **exactly when the outcome is not established** — i.e. iff
   * `outcomeKnown === false`. It is the pointer back to the original operation,
   * which a `pending` outcome polls and an `unknown` outcome reconciles;
   * `nextAction` says which. Null for a rejected or terminal outcome, where
   * there is nothing to go back to.
   */
  readonly reconcile: MiliastraReconcileRoute | null
  readonly nextAction: MiliastraNextAction
  readonly retryAttempted: false
  readonly reason: string
}

/** The outcome of handing a late receipt to a disposed (or draining) instance. */
export interface MiliastraLateReceiptOutcome {
  readonly operationId: string
  /** Phase when the receipt arrived. Never changes as a result of the receipt. */
  readonly phaseAtReceipt: MiliastraLifecyclePhase
  /** True when the ledger accepted the observation. */
  readonly recorded: boolean
  /** Always false: a late receipt never brings an old instance back to life. */
  readonly activated: false
  /** Always false. */
  readonly dispatched: false
  /** The ledger's view after the observation, or null when nothing was recorded. */
  readonly operation: MiliastraOpenOperation | null
  /** Why the receipt was refused; null when it was recorded. */
  readonly reason: string | null
  /** Set only when the receipt was refused. */
  readonly code: 'LIFECYCLE_RECEIPT_UNKNOWN_OPERATION' | 'LIFECYCLE_LEDGER_UNAVAILABLE' | null
}

/** A resource the unload left alone, with the reason it was left alone. */
export interface MiliastraRetainedResource {
  readonly id: string
  readonly kind: MiliastraResourceKind
  readonly reason: string
}

/** A resource the unload could not release within its bound. */
export interface MiliastraUnreleasedResource {
  readonly id: string
  readonly kind: MiliastraResourceKind
  readonly createdBy: string
  /** Why it is still alive. */
  readonly reason: string
  /** ISO-8601 instant the release attempt began, for the mainline to act on. */
  readonly attemptedUtc: string
}

/** A resource the unload actually released. */
export interface MiliastraReleasedResource {
  readonly id: string
  readonly kind: MiliastraResourceKind
  readonly releasedUtc: string
}

/**
 * What one `dispose()` did. This is the object the mainline reads to reconcile
 * an unload: it names the operations left in the ledger, the resources released,
 * the resources it could not release, and the external processes it did not
 * touch.
 */
export interface MiliastraDisposeReport {
  readonly phase: 'disposed'
  /** True when this call found the instance already disposed. */
  readonly alreadyDisposed: boolean
  /** Why draining began. */
  readonly drainReason: string
  readonly startedUtc: string
  readonly finishedUtc: string
  readonly elapsedMs: number
  /** Own resources released, in reverse registration order. */
  readonly released: readonly MiliastraReleasedResource[]
  /** Own resources still alive after the bounded wait. **Not killed.** */
  readonly unreleased: readonly MiliastraUnreleasedResource[]
  /** External resources never touched. */
  readonly retained: readonly MiliastraRetainedResource[]
  /** Operations left for reconciliation. Never cancelled, never retried. */
  readonly openOperations: readonly MiliastraOpenOperation[]
  /** operationIds this instance granted a permit for and never saw resolved. */
  readonly unresolvedAdmissions: readonly string[]
  /** Always false. Disposal is not a rollback (G01 LIFE-2, LIFE-5). */
  readonly rollbackPerformed: false
  /** Always false. */
  readonly retryAttempted: false
}

/** Options for {@link MiliastraLifecycleController.dispose}. */
export interface MiliastraDisposeOptions {
  /** Why the unload began; appears verbatim in the report. */
  readonly reason?: string
  /** Upper bound on the whole release phase, in milliseconds. */
  readonly releaseTimeoutMs?: number
  /** Called once before any resource is released, e.g. to unregister tools. */
  readonly beforeRelease?: () => void | Promise<void>
}

/** Options for {@link createMiliastraLifecycle}. */
export interface MiliastraLifecycleOptions {
  /** The business ledger port (T06 / DS-08). */
  readonly ledger: MiliastraBusinessLedgerPort
  /** Namespace this instance reserved, if any; recorded in the resource table. */
  readonly serverName?: string | null
  /** Clock injection, for deterministic tests. */
  readonly now?: () => Date
  /** Default release bound when `dispose()` does not supply one. */
  readonly releaseTimeoutMs?: number
}

/** Default bound on the whole release phase. */
export const DEFAULT_RELEASE_TIMEOUT_MS = 5_000

// ---------------------------------------------------------------------------
// 5. Implementation.
// ---------------------------------------------------------------------------

/** Per-resource bookkeeping the controller keeps alongside the declared entry. */
interface ResourceSlot {
  readonly resource: MiliastraResource
  releaseCount: number
}

/** A permit handed out by {@link MiliastraLifecycleController.beginOperation}. */
interface Admission {
  readonly operationId: string
  readonly capabilityId: string
  readonly grantedUtc: string
}

/**
 * The lifecycle controller for one plugin instance.
 *
 * Create one per instance, register the resources the instance owns, call
 * {@link markReady} only when the backend has actually reported a tool surface,
 * and call {@link dispose} from the instance's effect disposer. Never share an
 * instance between two controllers.
 */
export class MiliastraLifecycleController {
  private currentPhase: MiliastraLifecyclePhase = 'starting'
  private readonly ledger: MiliastraBusinessLedgerPort
  private readonly clock: () => Date
  private readonly defaultReleaseTimeoutMs: number
  private readonly slots: ResourceSlot[] = []
  private readonly admissions = new Map<string, Admission>()
  private readonly knownOperations = new Set<string>()
  private disposeReport: MiliastraDisposeReport | null = null
  private disposePromise: Promise<MiliastraDisposeReport> | null = null
  private readyDetail: string | null = null

  constructor(options: MiliastraLifecycleOptions) {
    this.ledger = options.ledger
    this.clock = options.now ?? (() => new Date())
    this.defaultReleaseTimeoutMs = options.releaseTimeoutMs ?? DEFAULT_RELEASE_TIMEOUT_MS
    if (options.serverName != null && options.serverName !== '') {
      this.registerResource({
        id: `namespace:${options.serverName}`,
        kind: 'namespace-reservation',
        ownership: 'own',
        createdBy: `miliastra:${options.serverName}`,
        release: () => { /* the namespace set is owned by the mcp-client effect */ },
      })
    }
  }

  // -- phase ---------------------------------------------------------------

  /** @returns the current phase. Never throws. */
  phase(): MiliastraLifecyclePhase {
    return this.currentPhase
  }

  /** @returns the backend readiness detail, or null. */
  readinessDetail(): string | null {
    return this.readyDetail
  }

  /**
   * Move to `to`, or throw.
   * @param to - the phase to enter.
   * @returns nothing.
   * @throws MiliastraLifecycleError `LIFECYCLE_ILLEGAL_TRANSITION`.
   */
  transition(to: MiliastraLifecyclePhase): void {
    if (to === this.currentPhase && to === 'disposed') {
      throw new MiliastraLifecycleError('LIFECYCLE_ILLEGAL_TRANSITION', this.currentPhase,
        'is terminal; dispose() is idempotent and does not re-enter the state machine', to)
    }
    this.currentPhase = assertTransition(this.currentPhase, to)
  }

  /**
   * Publish readiness. Only `starting -> ready` is legal, and only after the
   * backend has reported a live tool surface — never as a placeholder for
   * "activation returned".
   * @param detail - backend readiness detail for the log.
   * @throws MiliastraLifecycleError when the move is illegal.
   */
  markReady(detail: string | null = null): void {
    this.transition('ready')
    this.readyDetail = detail
  }

  // -- resources -----------------------------------------------------------

  /**
   * Add one resource to the table.
   *
   * Refuses a misdeclaration rather than deferring it to unload:
   * `own` + an external-only kind, `own` without a release function, or
   * `external` **with** one.
   *
   * @param resource - the entry to add.
   * @throws MiliastraLifecycleError `LIFECYCLE_RESOURCE_MISDECLARED`.
   */
  registerResource(resource: MiliastraResource): void {
    if (this.slots.some(slot => slot.resource.id === resource.id)) {
      throw new MiliastraLifecycleError('LIFECYCLE_RESOURCE_MISDECLARED', this.currentPhase,
        `resource id ${resource.id} is already registered; ids are unique per instance`)
    }
    if (resource.ownership === 'own' && EXTERNAL_ONLY_RESOURCE_KINDS.includes(resource.kind)) {
      throw new MiliastraLifecycleError('LIFECYCLE_RESOURCE_MISDECLARED', this.currentPhase,
        `${resource.kind} may only be declared external; an unload must never release it (${resource.id})`)
    }
    if (resource.ownership === 'own' && typeof resource.release !== 'function') {
      throw new MiliastraLifecycleError('LIFECYCLE_RESOURCE_MISDECLARED', this.currentPhase,
        `own resource ${resource.id} must declare release()`)
    }
    if (resource.ownership === 'external' && typeof resource.release === 'function') {
      throw new MiliastraLifecycleError('LIFECYCLE_RESOURCE_MISDECLARED', this.currentPhase,
        `external resource ${resource.id} must not declare release(); it belongs to another process`)
    }
    this.slots.push({ resource, releaseCount: 0 })
  }

  /**
   * Snapshot the resource table.
   * @returns one row per registered resource, in registration order.
   */
  resourceTable(): readonly MiliastraResourceRow[] {
    return this.slots.map(slot => ({
      id: slot.resource.id,
      kind: slot.resource.kind,
      ownership: slot.resource.ownership,
      createdBy: slot.resource.createdBy,
      releasable: typeof slot.resource.release === 'function',
      releaseCount: slot.releaseCount,
    }))
  }

  // -- operations ----------------------------------------------------------

  /**
   * Ask for a dispatch permit. This is the only way to obtain one.
   *
   * @param request - the operation the caller intends to run.
   * @returns `granted` (dispatch exactly once), `existing` (the ledger knows it:
   * report, never dispatch), or `refused` (this instance will not write).
   * @throws MiliastraLifecycleError `LIFECYCLE_OPERATION_ID_INVALID` when the id
   * is not the ledger contract's shape.
   */
  async beginOperation(request: MiliastraOperationRequest): Promise<MiliastraDispatchAdmission> {
    if (!OPERATION_ID_PATTERN.test(request.operationId)) {
      throw new MiliastraLifecycleError('LIFECYCLE_OPERATION_ID_INVALID', this.currentPhase,
        `operationId must match ${OPERATION_ID_PATTERN.source}, received ${JSON.stringify(request.operationId)}`)
    }
    const common = {
      operationId: request.operationId,
      capabilityId: request.capabilityId,
    } as const

    // Refusals first: a draining instance does not even read the ledger, so a
    // refusal cannot be mistaken for a ledger observation.
    if (this.currentPhase !== 'ready') {
      const code = this.currentPhase === 'starting'
        ? 'LIFECYCLE_NOT_READY' as const
        : 'LIFECYCLE_WRITE_REFUSED_DRAINING' as const
      return {
        ...common,
        kind: 'refused',
        phase: this.currentPhase,
        code,
        state: 'rejected',
        reconcileState: 'never-claimed',
        outcomeKnown: true,
        writeExecuted: false,
        dispatchEvidence: [],
        retryAttempted: false,
        nextAction: 'fix-input',
        reconcile: null,
        reason: this.currentPhase === 'starting'
          ? 'the instance has not reported a live tool surface yet'
          : `the instance is ${this.currentPhase} and no longer dispatches writes`,
      }
    }

    if (this.admissions.has(request.operationId) || this.knownOperations.has(request.operationId)) {
      throw new MiliastraLifecycleError('LIFECYCLE_OPERATION_ALREADY_ACTIVE', this.currentPhase,
        `operationId ${request.operationId} was already admitted by this instance`)
    }

    const existing = await this.readOperationOrThrow(request.operationId)
    if (existing !== null) {
      this.knownOperations.add(request.operationId)
      const projected = this.project(existing)
      return {
        ...common,
        kind: 'existing',
        phase: this.currentPhase,
        operationState: projected.operationState,
        state: projected.state,
        reconcileState: projected.reconcileState,
        outcomeKnown: projected.outcomeKnown,
        writeExecuted: projected.writeExecuted,
        dispatchEvidence: projected.dispatchEvidence,
        retryAttempted: false,
        replayed: projected.operationState === 'known-complete' || projected.operationState === 'known-failed',
        nextAction: projected.nextAction,
        reconcile: projected.reconcile,
        reason: `the business ledger already carries this operationId as ${projected.operationState}; report it instead of dispatching`,
      }
    }

    const grantedUtc = this.clock().toISOString()
    this.admissions.set(request.operationId, {
      operationId: request.operationId,
      capabilityId: request.capabilityId,
      grantedUtc,
    })
    return {
      ...common,
      kind: 'granted',
      phase: 'ready',
      operationState: 'never-claimed',
      writeExecuted: false,
      dispatchEvidence: [],
      retryAttempted: false,
      grantedUtc,
    }
  }

  /**
   * Report what is known about an operation after a dispatch was permitted.
   * Marks the admission resolved; the ledger remains the truth.
   * @param operationId - the operation that reached a terminal state.
   */
  settleOperation(operationId: string): void {
    this.admissions.delete(operationId)
    this.knownOperations.add(operationId)
  }

  /**
   * Cancel a wait. **This never dispatches and never rolls back.**
   *
   * @param operationId - the operation to stop waiting on.
   * @returns the outcome, projected from the ledger's authoritative state.
   * @throws MiliastraLifecycleError `LIFECYCLE_LEDGER_UNAVAILABLE`.
   */
  async cancel(operationId: string): Promise<MiliastraCancellationOutcome> {
    if (!OPERATION_ID_PATTERN.test(operationId)) {
      throw new MiliastraLifecycleError('LIFECYCLE_OPERATION_ID_INVALID', this.currentPhase,
        `operationId must match ${OPERATION_ID_PATTERN.source}, received ${JSON.stringify(operationId)}`)
    }
    const view = await this.readOperationOrThrow(operationId)
    const phase = this.currentPhase
    const base = { operationId, phase, dispatched: false as const, retryAttempted: false as const }

    // No claim at all: the only case in which cancelling may be reported as a
    // rejection, and the only case in which nothing was written.
    if (view === null || view.operationState === 'never-claimed') {
      this.admissions.delete(operationId)
      return {
        ...base,
        operationState: 'never-claimed',
        state: 'rejected',
        reconcileState: 'never-claimed',
        outcomeKnown: true,
        writeExecuted: false,
        dispatchEvidence: [],
        error: {
          code: 'CANCELLED_BEFORE_DISPATCH',
          disposition: 'refusal-before-dispatch',
          phase: 'before-dispatch',
          sideEffect: 'none',
          message: 'cancelled before any dispatch; nothing was written and there is nothing to reconcile',
          operationId,
          reconcile: null,
        },
        reconcile: null,
        nextAction: 'fix-input',
        reason: 'the ledger shows no claim for this operationId, so no write can have started',
      }
    }

    // A claim exists. From here on the ONLY honest answers are pending/unknown.
    const projected = this.project(view)
    const reason = view.operationState === 'outcome-unknown'
      ? 'the operation was dispatched and its outcome is not established; reconcile from the original receipt, do not re-send'
      : `the operation is ${view.operationState}; cancelling a wait does not roll it back — reconcile instead of re-sending`
    return {
      ...base,
      operationState: projected.operationState,
      state: projected.state,
      reconcileState: projected.reconcileState,
      outcomeKnown: projected.outcomeKnown,
      writeExecuted: projected.writeExecuted,
      dispatchEvidence: projected.dispatchEvidence,
      error: null,
      reconcile: projected.outcomeKnown ? null : projected.reconcile,
      nextAction: projected.nextAction,
      reason,
    }
  }

  /**
   * Hand a receipt that arrived late — after this instance stopped waiting, or
   * after it was disposed — to the ledger for the **original** operation.
   *
   * @param observation - the receipt and the operation it belongs to.
   * @returns the outcome; `activated` is always false and the phase never moves.
   */
  async deliverReceipt(observation: MiliastraOperationObservation): Promise<MiliastraLateReceiptOutcome> {
    const phaseAtReceipt = this.currentPhase
    const base = {
      operationId: observation.operationId,
      phaseAtReceipt,
      activated: false as const,
      dispatched: false as const,
    }

    let existing: MiliastraOperationView | null
    try {
      existing = await this.readOperationOrThrow(observation.operationId)
    } catch {
      return {
        ...base,
        recorded: false,
        operation: null,
        reason: 'the business ledger could not be read; the receipt was not recorded anywhere by this module',
        code: 'LIFECYCLE_LEDGER_UNAVAILABLE',
      }
    }
    if (existing === null) {
      return {
        ...base,
        recorded: false,
        operation: null,
        reason: 'the ledger does not know this operationId; a late receipt must never create an operation',
        code: 'LIFECYCLE_RECEIPT_UNKNOWN_OPERATION',
      }
    }

    let updated: MiliastraOperationView
    try {
      updated = await this.ledger.recordObservation(observation)
    } catch (error) {
      return {
        ...base,
        recorded: false,
        operation: null,
        reason: `the ledger refused the observation: ${error instanceof Error ? error.message : String(error)}`,
        code: 'LIFECYCLE_LEDGER_UNAVAILABLE',
      }
    }

    this.knownOperations.add(observation.operationId)
    this.admissions.delete(observation.operationId)
    return {
      ...base,
      recorded: true,
      operation: this.project(updated),
      reason: null,
      code: null,
    }
  }

  /**
   * The operations that are still open, read from the ledger. A reloaded
   * instance calls this **instead of** dispatching (T03.md §4 step 08).
   *
   * The set is the union of what this instance was told about and — when the
   * port offers {@link MiliastraBusinessLedgerPort.listOpenOperations} — what the
   * ledger itself reports as open, so a fresh instance can discover the previous
   * instance's unresolved writes without anyone handing it a list.
   *
   * @returns one entry per open operation, in the order discovered.
   */
  async pendingOperations(): Promise<readonly MiliastraOpenOperation[]> {
    const ids = new Set<string>([...this.admissions.keys(), ...this.knownOperations])
    if (typeof this.ledger.listOpenOperations === 'function') {
      let listed: readonly MiliastraOperationView[]
      try {
        listed = await this.ledger.listOpenOperations()
      } catch (error) {
        throw new MiliastraLifecycleError('LIFECYCLE_LEDGER_UNAVAILABLE', this.currentPhase,
          `listOpenOperations() failed: ${error instanceof Error ? error.message : String(error)}`)
      }
      for (const row of listed) ids.add(row.operationId)
    }
    const open: MiliastraOpenOperation[] = []
    for (const id of ids) {
      const view = await this.readOperationOrThrow(id)
      if (view === null) continue
      if (!RESUMABLE_OPERATION_STATES.includes(view.operationState)) continue
      open.push(this.project(view))
    }
    return open
  }

  // -- disposal ------------------------------------------------------------

  /**
   * Drain and dispose this instance.
   *
   * Order: refuse new writes, wait (bounded) for in-flight admissions to be
   * observed, release **own** resources in reverse registration order, leave
   * every external resource alone, and report the operations still open in the
   * ledger. Idempotent: the second call returns the first report unchanged.
   *
   * @param options - reason, release bound, and a pre-release hook.
   * @returns the dispose report.
   */
  async dispose(options: MiliastraDisposeOptions = {}): Promise<MiliastraDisposeReport> {
    if (this.disposeReport !== null) {
      return { ...this.disposeReport, alreadyDisposed: true }
    }
    if (this.disposePromise !== null) return this.disposePromise
    this.disposePromise = this.runDispose(options)
    return this.disposePromise
  }

  /** The body of {@link dispose}; runs at most once. */
  private async runDispose(options: MiliastraDisposeOptions): Promise<MiliastraDisposeReport> {
    const startedUtc = this.clock().toISOString()
    const startedAt = Date.now()
    const drainReason = options.reason ?? 'unload'
    const timeoutMs = options.releaseTimeoutMs ?? this.defaultReleaseTimeoutMs
    const alreadyDisposed = false

    // 1. Stop new writes before anything else is touched.
    if (this.currentPhase !== 'disposed') {
      if (this.currentPhase === 'ready') this.transition('draining')
      else if (this.currentPhase === 'starting') this.transition('draining')
    }

    // 2. Let the owner unregister its contributions while the ledger is still
    //    readable, then record what is open — without cancelling or retrying it.
    if (options.beforeRelease !== undefined && this.currentPhase === 'draining') {
      try {
        await options.beforeRelease()
      } catch {
        // A failing pre-release hook must not abort the unload; the resource
        // loop below still runs and reports what it could not release.
      }
    }

    const openOperations = await this.collectOpenOperations()
    const unresolvedAdmissions = [...this.admissions.keys()]
    this.admissions.clear()

    // 3. Release own resources, newest first, each within the remaining budget.
    const released: MiliastraReleasedResource[] = []
    const unreleased: MiliastraUnreleasedResource[] = []
    const retained: MiliastraRetainedResource[] = []
    const deadline = Date.now() + timeoutMs

    for (const slot of [...this.slots].reverse()) {
      const { resource } = slot
      if (resource.ownership === 'external') {
        retained.push({
          id: resource.id,
          kind: resource.kind,
          reason: 'external resource: this plugin does not stop, restart or disconnect the game, the editor or the resident helper',
        })
        continue
      }
      const attemptedUtc = this.clock().toISOString()
      const budgetMs = Math.max(0, deadline - Date.now())
      const outcome = await this.releaseWithin(slot, budgetMs)
      if (outcome === 'released') {
        released.push({ id: resource.id, kind: resource.kind, releasedUtc: this.clock().toISOString() })
      } else {
        unreleased.push({
          id: resource.id,
          kind: resource.kind,
          createdBy: resource.createdBy,
          reason: outcome === 'timed-out'
            ? `release() did not settle within ${budgetMs} ms; left alive for the mainline to handle`
            : 'release() threw; the resource may still be alive, so it is not reported as released',
          attemptedUtc,
        })
      }
    }

    // 4. Terminal transition. A stuck release does not keep the instance alive.
    if (this.currentPhase === 'draining') this.transition('disposed')

    const finishedUtc = this.clock().toISOString()
    this.disposeReport = {
      phase: 'disposed',
      alreadyDisposed,
      drainReason,
      startedUtc,
      finishedUtc,
      elapsedMs: Date.now() - startedAt,
      released,
      unreleased,
      retained,
      openOperations,
      unresolvedAdmissions,
      rollbackPerformed: false,
      retryAttempted: false,
    }
    return this.disposeReport
  }

  /**
   * Run one resource's release with a bound, counting the call exactly once.
   *
   * Three outcomes, and a rejection is **not** success: a release that threw may
   * well have left the resource alive, so it is reported as unreleased rather
   * than filed under "we cleaned up". Never kills, never escalates, never retries.
   */
  private async releaseWithin(slot: ResourceSlot, budgetMs: number): Promise<'released' | 'timed-out' | 'failed'> {
    const release = slot.resource.release
    if (typeof release !== 'function') return 'failed'
    slot.releaseCount += 1
    let timer: ReturnType<typeof setTimeout> | undefined
    const guard = new Promise<'timed-out'>(resolve => {
      timer = setTimeout(() => resolve('timed-out'), budgetMs)
      if (typeof timer === 'object' && timer !== null && typeof timer.unref === 'function') timer.unref()
    })
    try {
      const settled = Promise.resolve(release()).then(
        (): 'released' => 'released',
        (): 'failed' => 'failed',
      )
      return await Promise.race([settled, guard])
    } finally {
      if (timer !== undefined) clearTimeout(timer)
    }
  }

  /**
   * Read every operation this instance was involved with, keeping the ones that
   * still need reconciliation. A ledger that cannot be read here is not allowed
   * to abort the unload: the operations are reported by id alone instead, so the
   * mainline still learns there is something to reconcile.
   */
  private async collectOpenOperations(): Promise<readonly MiliastraOpenOperation[]> {
    const ids = new Set<string>([...this.admissions.keys(), ...this.knownOperations])
    const open: MiliastraOpenOperation[] = []
    for (const id of ids) {
      const view = await this.readOperationOrThrow(id).catch((): MiliastraOperationView | null => null)
      if (view === null) continue
      if (!RESUMABLE_OPERATION_STATES.includes(view.operationState)) continue
      open.push(this.project(view))
    }
    return open
  }

  /** Read one operation, converting a port failure into a typed lifecycle error. */
  private async readOperationOrThrow(operationId: string): Promise<MiliastraOperationView | null> {
    try {
      return await this.ledger.readOperation(operationId)
    } catch (error) {
      throw new MiliastraLifecycleError('LIFECYCLE_LEDGER_UNAVAILABLE', this.currentPhase,
        `readOperation(${operationId}) failed: ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  /** Project one ledger row onto the shapes consumers read. */
  private project(view: MiliastraOperationView): MiliastraOpenOperation {
    const state = toBusinessState(view.operationState)
    return {
      operationId: view.operationId,
      operationState: view.operationState,
      state,
      reconcileState: toReconcileState(view.operationState),
      outcomeKnown: isOutcomeKnown(state),
      writeExecuted: view.writeExecuted,
      dispatchEvidence: view.dispatchEvidence,
      requestId: view.requestId,
      journalRef: view.journalRef,
      ledgerRef: view.ledgerRef,
      nextAction: NEXT_ACTION_BY_BUSINESS_STATE[state],
      reconcile: {
        operationId: view.operationId,
        ledgerRef: view.ledgerRef,
        requestId: view.requestId,
        journalRef: view.journalRef,
      },
      retryAttempted: false,
    }
  }
}

/**
 * Create a lifecycle controller for one plugin instance.
 * @param options - ledger port, optional namespace, clock, release bound.
 * @returns a controller in phase `starting`.
 */
export function createMiliastraLifecycle(options: MiliastraLifecycleOptions): MiliastraLifecycleController {
  return new MiliastraLifecycleController(options)
}
