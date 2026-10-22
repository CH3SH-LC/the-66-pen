/**
 * Frozen stand-in for the T06 / DS-08 business ledger port.
 *
 * DS-08 (`backend/business_contract.py`, `backend/operation_state.py`) has not
 * been delivered. This fixture implements exactly the two methods
 * {@link MiliastraBusinessLedgerPort} declares — and nothing that could be
 * mistaken for a dispatch — so that `tests/lifecycle.spec.ts` can exercise the
 * lifecycle controller today and be re-run unchanged against the real port later.
 *
 * Two deliberate properties:
 *
 * 1. **It cannot dispatch.** There is no write path here at all. `markDispatched`
 *    only edits the in-memory row to *describe* a dispatch another layer already
 *    performed; it is never called by the controller.
 * 2. **It adjudicates nothing by default.** `recordObservation` records and
 *    returns the row **unchanged**, so a test asserting "a late receipt did not
 *    turn unknown into success" is testing the controller, not this fixture. The
 *    `adjudicate` option flips that, for the case that proves the controller
 *    *relays* a ledger verdict rather than computing one.
 *
 * @module @miliastra/dsh-miliastra/fixtures/t03-fake-ledger
 */

import { RESUMABLE_OPERATION_STATES } from '../src/lifecycle.ts'
import type {
  MiliastraBusinessLedgerPort,
  MiliastraOperationObservation,
  MiliastraOperationState,
  MiliastraOperationView,
} from '../src/lifecycle.ts'

/** The five named dispatch-evidence files (contract.json `operationState.discriminator`). */
export const DISPATCH_EVIDENCE_FILES = [
  'direct-launch-intent.json',
  'launch.claim',
  'attempt.used',
] as const

/** Options for {@link FakeLedger}. */
export interface FakeLedgerOptions {
  /** Rows the ledger starts with. */
  readonly seed?: readonly MiliastraOperationView[]
  /** When true, `readOperation` throws instead of answering. */
  readonly failReads?: boolean
  /** When true, `recordObservation` throws instead of recording. */
  readonly failWrites?: boolean
  /**
   * When set, `recordObservation` moves the row to this state — simulating a
   * ledger that adjudicated a terminal receipt. Default: leave the row as is.
   */
  readonly adjudicate?: MiliastraOperationState | null
}

/** Build one ledger row with honest defaults. */
export function operationView(
  operationId: string,
  operationState: MiliastraOperationState,
  overrides: Partial<MiliastraOperationView> = {},
): MiliastraOperationView {
  const dispatched = operationState === 'dispatched' || operationState === 'known-complete' || operationState === 'known-failed'
  return {
    operationId,
    operationState,
    ledgerRef: `ledger/${operationId}`,
    dispatchEvidence: dispatched ? [DISPATCH_EVIDENCE_FILES[0]!] : [],
    requestId: dispatched ? `req-${operationId}` : null,
    journalRef: dispatched ? `journal/${operationId}` : null,
    writeExecuted: dispatched ? true : operationState === 'claimed' ? false : null,
    ...overrides,
  }
}

/**
 * An in-memory business ledger that answers the frozen port and records every
 * call, so a test can prove a code path neither read nor wrote.
 */
export class FakeLedger implements MiliastraBusinessLedgerPort {
  /** Rows by operationId. */
  readonly rows = new Map<string, MiliastraOperationView>()
  /** Every observation handed to the ledger, in order. */
  readonly observations: MiliastraOperationObservation[] = []
  /** Every method call, as `read:<id>` / `record:<id>`, in order. */
  readonly calls: string[] = []
  /** Number of `readOperation` calls. */
  readCalls = 0
  /** Number of `recordObservation` calls. */
  recordCalls = 0
  /** Number of `listOpenOperations` calls. */
  listCalls = 0

  private readonly failReads: boolean
  private readonly failWrites: boolean
  private readonly adjudicate: MiliastraOperationState | null

  constructor(options: FakeLedgerOptions = {}) {
    this.failReads = options.failReads ?? false
    this.failWrites = options.failWrites ?? false
    this.adjudicate = options.adjudicate ?? null
    for (const row of options.seed ?? []) this.rows.set(row.operationId, row)
  }

  /**
   * Read one row. Counts the call; throws when `failReads` was set.
   * @param operationId - the operation to read.
   * @returns the row, or null when the ledger has never seen the id.
   */
  readOperation(operationId: string): MiliastraOperationView | null {
    this.calls.push(`read:${operationId}`)
    this.readCalls += 1
    if (this.failReads) throw new Error('fixture ledger: transport unavailable')
    return this.rows.get(operationId) ?? null
  }

  /**
   * Record an observation against an existing row and return the row as the
   * ledger now adjudicates it.
   * @param observation - what arrived.
   * @returns the resulting row.
   * @throws Error when the id is unknown or `failWrites` was set.
   */
  recordObservation(observation: MiliastraOperationObservation): MiliastraOperationView {
    this.calls.push(`record:${observation.operationId}`)
    this.recordCalls += 1
    if (this.failWrites) throw new Error('fixture ledger: observation rejected')
    const row = this.rows.get(observation.operationId)
    if (row === undefined) throw new Error(`fixture ledger: unknown operationId ${observation.operationId}`)
    this.observations.push(observation)
    if (this.adjudicate === null) return row
    const updated: MiliastraOperationView = { ...row, operationState: this.adjudicate }
    this.rows.set(row.operationId, updated)
    return updated
  }

  /**
   * Enumerate the rows still needing reconciliation. Counts the call; throws when
   * `failReads` was set.
   * @returns every row whose state is claimed, dispatched or outcome-unknown.
   */
  listOpenOperations(): readonly MiliastraOperationView[] {
    this.calls.push('list')
    this.listCalls += 1
    if (this.failReads) throw new Error('fixture ledger: transport unavailable')
    return [...this.rows.values()].filter(row => RESUMABLE_OPERATION_STATES.includes(row.operationState))
  }

  /**
   * **Test helper, never called by the controller.** Describe a dispatch that
   * another layer performed, so the lifecycle controller sees `dispatched`.
   * @param operationId - the operation.
   * @param evidence - the evidence files that prove it.
   * @returns the updated row.
   */
  markDispatched(operationId: string, evidence: readonly string[] = DISPATCH_EVIDENCE_FILES.slice(0, 1)): MiliastraOperationView {
    const row = this.rows.get(operationId) ?? operationView(operationId, 'claimed')
    const updated: MiliastraOperationView = {
      ...row,
      operationState: 'dispatched',
      dispatchEvidence: evidence,
      requestId: `req-${operationId}`,
      journalRef: `journal/${operationId}`,
      writeExecuted: true,
    }
    this.rows.set(operationId, updated)
    return updated
  }

  /**
   * **Test helper.** Describe a claim with no dispatch evidence yet.
   * @param operationId - the operation.
   * @returns the updated row.
   */
  markClaimed(operationId: string): MiliastraOperationView {
    const updated = operationView(operationId, 'claimed')
    this.rows.set(operationId, updated)
    return updated
  }
}
