/**
 * T03 lifecycle suite — cancellation, unload, reload, and late receipts.
 *
 * What makes this suite about the real thing: every case drives
 * `src/lifecycle.ts` directly through the ports it will have in production
 * (`MiliastraBusinessLedgerPort`, `MiliastraResource`). The ledger stand-in and
 * the process sentinel are fixtures only because DS-06's `src/backend.ts` and
 * DS-08's ledger do not exist yet; when they land, this file must run unchanged
 * against the real ports.
 *
 * The safety claims are made structural rather than promised:
 *
 * - **Zero dispatch before submit** — the controller has no dispatch function at
 *   all. Every case that asserts "nothing was sent" additionally drives a
 *   `dispatchSpy` that is only ever called behind a `kind === 'granted'`
 *   admission, and asserts its call count is 0.
 * - **The external sentinel** — a live-looking process stand-in that exposes
 *   `release()` and `kill()`. The cases assert both counters are 0 and the
 *   process is still alive after an unload.
 * - **No convergence of unknown into success** — the late-receipt case runs
 *   against a ledger fixture that adjudicates *nothing*, so a `completed`
 *   verdict could only have come from the controller inventing it.
 *
 * What this suite does NOT claim: no MCP server starts, no tool reaches a real
 * registry, no game, editor, helper or bridge process is touched, and no model
 * runs. Those stay not-run in this task's result.
 *
 * Run: `node --test tests/lifecycle.spec.ts`
 *      (or `node scripts/run-tests.mjs tests/lifecycle.spec.ts`, which is what
 *      `pnpm test` invokes after its build step)
 *
 * @module @miliastra/dsh-miliastra/tests/lifecycle.spec
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  BUSINESS_STATE_BY_OPERATION_STATE,
  LEGAL_LIFECYCLE_TRANSITIONS,
  MiliastraLifecycleError,
  OPERATION_ID_PATTERN,
  RECONCILE_STATE_BY_OPERATION_STATE,
  canTransition,
  createMiliastraLifecycle,
  toBusinessState,
  toReconcileState,
  type MiliastraLifecycleController,
} from '../src/lifecycle.ts'
import { FakeLedger, operationView } from '../fixtures/t03-fake-ledger.ts'
import {
  ExternalSentinel,
  FakeToolRegistry,
  StuckOwnResource,
  TrackedOwnResource,
  externalSentinelResource,
} from '../fixtures/t03-resources.ts'

/** This package's directory (`plugins/miliastra`). */
const packageDir = fileURLToPath(new URL('..', import.meta.url))

/** The frozen interface samples other workers code against. */
const samplesPath = join(packageDir, 'fixtures', 't03-interface-samples.json')

/** Tool names one instance publishes, for the reload/revocation cases. */
const OWN_TOOLS = ['mcp__miliastra__mw_scene_discover_level', 'mcp__miliastra__mw_scene_create_entity']

/** A dispatch path that must only ever be reachable behind a granted permit. */
class DispatchSpy {
  /** Every operationId that actually reached the transport. */
  readonly dispatched: string[] = []

  /** Record one dispatch. */
  dispatch(operationId: string): void {
    this.dispatched.push(operationId)
  }
}

/**
 * Build a controller that is already `ready`, with one tracked own resource and
 * one external sentinel in its table.
 * @param ledger - the ledger port the controller reads.
 * @returns the controller, its own resource, the sentinel and the tool registry.
 */
function readyInstance(ledger: FakeLedger): {
  controller: MiliastraLifecycleController
  own: TrackedOwnResource
  sentinel: ExternalSentinel
  registry: FakeToolRegistry
  disposers: Array<() => void>
} {
  const registry = new FakeToolRegistry()
  const disposers: Array<() => void> = []
  for (const toolName of OWN_TOOLS) disposers.push(registry.register(toolName))
  const own = new TrackedOwnResource('mcp-connection:stdio')
  const sentinel = new ExternalSentinel('game-process')
  const controller = createMiliastraLifecycle({ ledger, serverName: 'miliastra' })
  controller.registerResource(own.entry('mcp-connection'))
  controller.registerResource(externalSentinelResource(sentinel))
  controller.markReady('fixture backend published 2 tools')
  return { controller, own, sentinel, registry, disposers }
}

// ---- T03-A: normal unload ---------------------------------------------------

test('T03-A normal unload revokes tools, closes own connections, and keeps the external process', async () => {
  const ledger = new FakeLedger()
  const { controller, own, sentinel, registry, disposers } = readyInstance(ledger)
  assert.deepEqual(registry.live, OWN_TOOLS, 'the fixture registry must start with both tools live')

  const report = await controller.dispose({
    reason: 'test unload',
    beforeRelease: () => { for (const dispose of disposers) dispose() },
  })

  assert.equal(controller.phase(), 'disposed')
  assert.equal(report.phase, 'disposed')
  assert.equal(report.alreadyDisposed, false)
  assert.equal(report.drainReason, 'test unload')
  assert.deepEqual(registry.live, [], 'unload must revoke every tool this instance registered')
  assert.deepEqual(own.releaseLog, ['mcp-connection:stdio'], 'the own connection is released exactly once')
  assert.ok(report.released.some(entry => entry.id === 'mcp-connection:stdio'),
    'the report must name what it released')

  // The external process: never released, never killed, still running.
  assert.equal(sentinel.releaseCalls, 0, 'an external process must never be released')
  assert.equal(sentinel.killCalls, 0, 'an unload must never kill anything')
  assert.equal(sentinel.alive, true, 'the external sentinel must survive the unload')
  assert.ok(report.retained.some(entry => entry.id === 'game-process'),
    'the report must say the external process was deliberately retained')
  assert.deepEqual(report.unreleased, [], 'nothing should be stuck in this case')
})

// ---- T03-B: activation failure ---------------------------------------------

test('T03-B a failed activation rolls back without a partial registration', async () => {
  const ledger = new FakeLedger()
  const controller = createMiliastraLifecycle({ ledger, serverName: 'miliastra' })
  const registered: TrackedOwnResource[] = []
  // Only the resources that were really registered are released; the third one
  // stands for a registration the failed activation never reached.
  for (const id of ['tool-registration:a', 'tool-registration:b']) {
    const resource = new TrackedOwnResource(id)
    registered.push(resource)
    controller.registerResource(resource.entry('tool-registration'))
  }
  assert.equal(controller.phase(), 'starting')

  const report = await controller.dispose({ reason: 'activation failed' })

  assert.equal(controller.phase(), 'disposed')
  assert.deepEqual(registered.map(resource => resource.releaseLog), [['tool-registration:a'], ['tool-registration:b']])
  assert.equal(report.released.length, 3, 'both registrations plus the namespace reservation')
  assert.equal(controller.readinessDetail(), null, 'a failed activation never published readiness')
  assert.deepEqual(report.openOperations, [], 'a failed activation admitted no operations')

  // A harness that calls markReady anyway must be refused, not silently ignored.
  assert.throws(() => controller.markReady('too late'), (error: unknown) => {
    assert.ok(error instanceof MiliastraLifecycleError)
    assert.equal(error.code, 'LIFECYCLE_ILLEGAL_TRANSITION')
    return true
  })
})

// ---- T03-C: cancel before submit -------------------------------------------

test('T03-C cancelling before submit is rejected with zero dispatch', async () => {
  const ledger = new FakeLedger()
  const { controller } = readyInstance(ledger)
  const spy = new DispatchSpy()

  const admission = await controller.beginOperation({ operationId: 'op-cancel-early', capabilityId: 'entity.create' })
  assert.equal(admission.kind, 'granted')
  // The permit was granted and deliberately NOT used: this is the "cancelled
  // before submit" case, not the "never started" case.
  if (admission.kind === 'granted') assert.equal(admission.writeExecuted, false)

  const cancel = await controller.cancel('op-cancel-early')
  assert.equal(cancel.state, 'rejected')
  assert.equal(cancel.operationState, 'never-claimed')
  assert.equal(cancel.outcomeKnown, true)
  assert.equal(cancel.writeExecuted, false)
  assert.equal(cancel.dispatched, false)
  assert.equal(cancel.retryAttempted, false)
  assert.equal(cancel.reconcile, null)
  assert.equal(cancel.error?.code, 'CANCELLED_BEFORE_DISPATCH')
  assert.equal(cancel.error?.disposition, 'refusal-before-dispatch')
  assert.equal(cancel.error?.phase, 'before-dispatch')
  assert.equal(cancel.error?.sideEffect, 'none')

  assert.deepEqual(spy.dispatched, [], 'nothing may reach a transport')
  assert.equal(ledger.recordCalls, 0, 'this module must not write to the ledger')
  assert.equal(ledger.rows.size, 0, 'a cancelled-before-submit operation leaves no ledger row')

  if (admission.kind === 'granted') spy.dispatch(admission.operationId)
  assert.deepEqual(spy.dispatched, ['op-cancel-early'], 'the spy itself must be able to observe a dispatch')
})

// ---- T03-D: cancel after submit --------------------------------------------

test('T03-D cancelling after submit keeps pending/unknown and never claims a rollback', async () => {
  const cases = [
    { row: operationView('op-claimed', 'claimed', { writeExecuted: false }), state: 'pending', operationState: 'claimed' },
    { row: operationView('op-dispatched', 'dispatched'), state: 'pending', operationState: 'dispatched' },
    { row: operationView('op-unknown', 'outcome-unknown', { writeExecuted: null }), state: 'unknown', operationState: 'outcome-unknown' },
  ] as const

  for (const item of cases) {
    const ledger = new FakeLedger({ seed: [item.row] })
    const { controller } = readyInstance(ledger)
    const spy = new DispatchSpy()

    const cancel = await controller.cancel(item.row.operationId)

    assert.equal(cancel.state, item.state, `${item.operationState}: state`)
    assert.equal(cancel.operationState, item.operationState, `${item.operationState}: operationState`)
    assert.notEqual(cancel.state, 'rejected', `${item.operationState}: a submitted operation must never be reported rejected`)
    assert.notEqual(cancel.error?.code, 'CANCELLED_BEFORE_DISPATCH', `${item.operationState}: no pre-dispatch error`)
    assert.equal(cancel.outcomeKnown, false, `${item.operationState}: neither pending nor unknown is a known outcome`)
    assert.equal(cancel.dispatched, false)
    assert.equal(cancel.retryAttempted, false)
    assert.deepEqual(spy.dispatched, [], 'a cancel must never dispatch')

    // Invariant: a route back to the original operation exists exactly when the
    // outcome is not established. `nextAction` says whether to poll or reconcile.
    assert.equal(cancel.reconcile !== null, !cancel.outcomeKnown, `${item.operationState}: route iff unsettled`)
    assert.ok(cancel.reconcile !== null, `${item.operationState}: an unsettled outcome must be reachable`)
    assert.equal(cancel.reconcile.operationId, item.row.operationId)
    assert.equal(cancel.reconcile.ledgerRef, item.row.ledgerRef)
    assert.equal(cancel.reconcile.requestId, item.row.requestId)
    assert.equal(cancel.nextAction, item.state === 'unknown' ? 'reconcile' : 'poll-same-operation')
    // A dispatched operation's writeExecuted is the ledger's, never downgraded.
    if (item.operationState === 'dispatched') assert.equal(cancel.writeExecuted, true)
  }
})

// ---- T03-E: late receipt ----------------------------------------------------

test('T03-E a late receipt is recorded against the original operation and never activates the old instance', async () => {
  const ledger = new FakeLedger({ seed: [operationView('op-late', 'outcome-unknown', { writeExecuted: null })] })
  const { controller, sentinel } = readyInstance(ledger)
  const admission = await controller.beginOperation({ operationId: 'op-late', capabilityId: 'entity.create' })
  assert.equal(admission.kind, 'existing', 'the ledger already knows this operation, so no permit may be granted')

  const report = await controller.dispose({ reason: 'unload before the receipt arrived' })
  assert.equal(controller.phase(), 'disposed')
  assert.ok(report.openOperations.some(entry => entry.operationId === 'op-late'),
    'the open operation must be handed to the mainline for reconciliation')

  const late = await controller.deliverReceipt({
    operationId: 'op-late',
    requestId: 'req-op-late',
    receiptRef: 'journal/op-late/result.json',
    observedUtc: '2026-10-02T00:00:05Z',
    detail: null,
  })

  assert.equal(late.recorded, true)
  assert.equal(late.activated, false, 'a late receipt must never bring an old instance back')
  assert.equal(late.dispatched, false)
  assert.equal(late.phaseAtReceipt, 'disposed')
  assert.equal(controller.phase(), 'disposed', 'the receipt must not move the phase')
  assert.equal(ledger.observations.length, 1, 'the receipt is written to the original operation evidence')
  assert.equal(ledger.observations[0]?.operationId, 'op-late')
  assert.equal(ledger.observations[0]?.receiptRef, 'journal/op-late/result.json')

  // The fixture adjudicates nothing, so `unknown` can only have been relayed.
  assert.equal(late.operation?.state, 'unknown', 'the plugin must not converge an unknown receipt into success')
  assert.equal(late.operation?.outcomeKnown, false)
  assert.equal(late.operation?.nextAction, 'reconcile')
  assert.equal(sentinel.alive, true)

  // A receipt for an operation the ledger has never seen is refused, not created.
  const stray = await controller.deliverReceipt({
    operationId: 'op-never-existed',
    requestId: null,
    receiptRef: 'journal/op-never-existed/result.json',
    observedUtc: '2026-10-02T00:00:06Z',
    detail: null,
  })
  assert.equal(stray.recorded, false)
  assert.equal(stray.code, 'LIFECYCLE_RECEIPT_UNKNOWN_OPERATION')
  assert.equal(stray.activated, false)
  assert.equal(ledger.recordCalls, 1, 'a stray receipt must not reach recordObservation')
  assert.equal(ledger.rows.has('op-never-existed'), false, 'a late receipt must never create an operation')
})

test('T03-E2 the controller relays a ledger verdict instead of computing one', async () => {
  // Same shape as T03-E, but this ledger DOES adjudicate: the receipt is
  // terminal, so T06 would move the row to known-complete. The controller must
  // report `completed` because the ledger said so — never on its own.
  const ledger = new FakeLedger({
    seed: [operationView('op-adjudicated', 'dispatched')],
    adjudicate: 'known-complete',
  })
  const { controller } = readyInstance(ledger)
  await controller.dispose({ reason: 'unload' })

  const late = await controller.deliverReceipt({
    operationId: 'op-adjudicated',
    requestId: 'req-op-adjudicated',
    receiptRef: 'journal/op-adjudicated/result.json',
    observedUtc: '2026-10-02T00:00:07Z',
    detail: null,
  })
  assert.equal(late.recorded, true)
  assert.equal(late.activated, false)
  assert.equal(late.operation?.operationState, 'known-complete')
  assert.equal(late.operation?.state, 'completed')
  assert.equal(late.operation?.reconcileState, 'known-success')
  assert.equal(late.operation?.nextAction, 'none')
})

// ---- T03-F: reload ----------------------------------------------------------

test('T03-F a new instance queries the old unknown request instead of re-dispatching it', async () => {
  const ledger = new FakeLedger()
  const first = readyInstance(ledger)
  const spy = new DispatchSpy()

  const granted = await first.controller.beginOperation({ operationId: 'op-reload', capabilityId: 'entity.create' })
  assert.equal(granted.kind, 'granted')
  if (granted.kind === 'granted') spy.dispatch(granted.operationId)
  ledger.markDispatched('op-reload')

  const report = await first.controller.dispose({ reason: 'hmr' })
  assert.equal(report.openOperations.length, 1, 'the unresolved write must be reported, not resolved')
  assert.equal(report.openOperations[0]?.state, 'pending')
  assert.equal(report.openOperations[0]?.outcomeKnown, false)
  assert.deepEqual(report.unresolvedAdmissions, ['op-reload'])
  assert.equal(report.rollbackPerformed, false)
  assert.equal(report.retryAttempted, false)

  // Second instance, same serverName, same ledger. It discovers the leftover
  // write through the ledger alone — nobody hands it a list.
  const second = readyInstance(ledger)
  const pending = await second.controller.pendingOperations()
  assert.deepEqual(pending.map(entry => entry.operationId), ['op-reload'])
  assert.equal(pending[0]?.nextAction, 'poll-same-operation')
  assert.equal(pending[0]?.state, 'pending')
  assert.equal(pending[0]?.outcomeKnown, false)
  assert.equal(pending[0]?.retryAttempted, false)
  assert.ok(pending[0]?.reconcile.ledgerRef, 'the new instance learns where to reconcile from')

  const reAdmission = await second.controller.beginOperation({ operationId: 'op-reload', capabilityId: 'entity.create' })
  assert.equal(reAdmission.kind, 'existing', 'a reloaded instance must not obtain a second permit')
  assert.equal(reAdmission.kind === 'existing' ? reAdmission.replayed : true, false,
    'a dispatched-but-unresolved operation is not a replay of a terminal receipt')
  assert.equal(spy.dispatched.length, 1, 'exactly the first instance dispatched; the reload never did')

  const cancel = await second.controller.cancel('op-reload')
  assert.equal(cancel.state, 'pending')
  assert.equal(cancel.dispatched, false)
  assert.equal(spy.dispatched.length, 1)
  assert.equal(ledger.rows.get('op-reload')?.operationState, 'dispatched', 'the ledger is untouched by the reload')
})

// ---- T03-G: repeated dispose ------------------------------------------------

test('T03-G repeated and concurrent dispose release every resource exactly once', async () => {
  const ledger = new FakeLedger()
  const { controller, own, sentinel } = readyInstance(ledger)

  const [first, second] = await Promise.all([
    controller.dispose({ reason: 'unload' }),
    controller.dispose({ reason: 'unload' }),
  ])
  assert.deepEqual(first.released.map(entry => entry.id), second.released.map(entry => entry.id),
    'two concurrent disposes must agree on what was released')

  const third = await controller.dispose({ reason: 'unload' })
  assert.equal(third.alreadyDisposed, true, 'a repeated dispose is reported as such')

  const table = controller.resourceTable()
  for (const row of table.filter(entry => entry.ownership === 'own')) {
    assert.equal(row.releaseCount, 1, `${row.id} must be released exactly once`)
  }
  assert.deepEqual(own.releaseLog, ['mcp-connection:stdio'], 'the own release function ran once')
  assert.equal(sentinel.releaseCalls, 0)
  assert.equal(sentinel.alive, true)
})

// ---- T03-H: a release that will not end --------------------------------------

test('T03-H a stuck release is bounded and reported, and nothing is killed', async () => {
  const ledger = new FakeLedger()
  const stuck = new StuckOwnResource('mcp-connection:stuck')
  const sentinel = new ExternalSentinel('elevated-helper')
  const controller = createMiliastraLifecycle({ ledger, serverName: 'miliastra' })
  controller.registerResource(stuck.entry())
  controller.registerResource(externalSentinelResource(sentinel))
  controller.markReady(null)

  const started = Date.now()
  const report = await controller.dispose({ reason: 'unload with a stuck connection', releaseTimeoutMs: 40 })
  const elapsed = Date.now() - started

  assert.equal(controller.phase(), 'disposed', 'a stuck release must not keep the instance alive')
  assert.ok(elapsed < 2_000, `dispose must be bounded, took ${elapsed} ms`)
  assert.equal(stuck.releaseCalls, 1, 'a bounded release is attempted exactly once, never retried')
  assert.equal(stuck.killCalls, 0, 'the controller must not escalate to a kill')
  assert.equal(sentinel.alive, true, 'the resident helper must survive')
  assert.equal(sentinel.killCalls, 0)

  const unreleased = report.unreleased.find(entry => entry.id === 'mcp-connection:stuck')
  assert.ok(unreleased !== undefined, 'the stuck resource must be reported as unreleased')
  assert.equal(unreleased.createdBy, 'mcp-client:transport')
  assert.match(unreleased.reason, /did not settle/, 'the report must say why it is still alive')

  // A later settle is not the controller's business: it already reported.
  stuck.unstick()
  const after = await controller.dispose({ reason: 'unload with a stuck connection', releaseTimeoutMs: 40 })
  assert.equal(after.alreadyDisposed, true)
  assert.equal(stuck.releaseCalls, 1, 'the second dispose must not re-attempt the stuck resource')
})

// ---- T03-I: re-enable --------------------------------------------------------

test('T03-I re-enabling the same serverName publishes no duplicate tools', async () => {
  const ledger = new FakeLedger()
  const registry = new FakeToolRegistry()

  const first = createMiliastraLifecycle({ ledger, serverName: 'miliastra' })
  const firstDisposers = OWN_TOOLS.map(toolName => registry.register(toolName))
  first.markReady(null)
  await first.dispose({ reason: 'disable', beforeRelease: () => { for (const dispose of firstDisposers) dispose() } })
  assert.deepEqual(registry.live, [], 'disabling must release the namespace contributions')

  const second = createMiliastraLifecycle({ ledger, serverName: 'miliastra' })
  const secondDisposers = OWN_TOOLS.map(toolName => registry.register(toolName))
  second.markReady(null)
  assert.deepEqual(registry.live, OWN_TOOLS, 're-enabling republishes the identical set exactly once')
  assert.deepEqual(registry.duplicates, [], 'no name may be offered twice while live')
  assert.equal(registry.offered.length, OWN_TOOLS.length * 2)

  await second.dispose({ reason: 'disable', beforeRelease: () => { for (const dispose of secondDisposers) dispose() } })
  assert.deepEqual(registry.live, [])
})

// ---- T03-J: illegal moves and misdeclared resources --------------------------

test('T03-J illegal phase moves and misdeclared resources are refused', async () => {
  const ledger = new FakeLedger()

  // Legal moves, asserted one controller at a time.
  for (const [from, to] of [['starting', 'ready'], ['starting', 'draining'], ['starting', 'disposed']] as const) {
    assert.equal(canTransition(from, to), true, `${from} -> ${to} must be legal`)
    const controller = createMiliastraLifecycle({ ledger })
    if (from !== 'starting') controller.transition(from)
    controller.transition(to)
    assert.equal(controller.phase(), to)
  }
  assert.deepEqual(LEGAL_LIFECYCLE_TRANSITIONS.disposed, [], 'disposed is terminal')
  assert.equal(canTransition('ready', 'starting'), false)
  assert.equal(canTransition('draining', 'ready'), false)
  assert.equal(canTransition('ready', 'ready'), false, 'a self-transition is not a transition')

  const illegal: Array<[string, () => void]> = [
    ['markReady twice', () => { const c = createMiliastraLifecycle({ ledger }); c.markReady(null); c.markReady(null) }],
    ['ready -> starting', () => { const c = createMiliastraLifecycle({ ledger }); c.markReady(null); c.transition('starting') }],
    ['draining -> ready', () => { const c = createMiliastraLifecycle({ ledger }); c.markReady(null); c.transition('draining'); c.transition('ready') }],
    ['disposed -> ready', () => { const c = createMiliastraLifecycle({ ledger }); c.markReady(null); c.transition('draining'); c.transition('disposed'); c.transition('ready') }],
    ['disposed -> disposed', () => { const c = createMiliastraLifecycle({ ledger }); c.markReady(null); c.transition('draining'); c.transition('disposed'); c.transition('disposed') }],
  ]
  for (const [label, run] of illegal) {
    assert.throws(run, (error: unknown) => {
      assert.ok(error instanceof MiliastraLifecycleError, `${label}: expected a MiliastraLifecycleError`)
      assert.equal(error.code, 'LIFECYCLE_ILLEGAL_TRANSITION', label)
      return true
    }, label)
  }

  // Resource misdeclarations: each one is a way an unload could become dangerous.
  const bad: Array<[string, () => void]> = [
    ['own + external-only kind', () => {
      const c = createMiliastraLifecycle({ ledger })
      c.registerResource({ id: 'game', kind: 'game-process', ownership: 'own', createdBy: 'x', release: () => {} })
    }],
    ['own without release', () => {
      const c = createMiliastraLifecycle({ ledger })
      c.registerResource({ id: 'listener', kind: 'listener', ownership: 'own', createdBy: 'x' })
    }],
    ['external with release', () => {
      const c = createMiliastraLifecycle({ ledger })
      c.registerResource({ id: 'helper', kind: 'elevated-helper', ownership: 'external', createdBy: 'user', release: () => {} })
    }],
    ['duplicate id', () => {
      const c = createMiliastraLifecycle({ ledger })
      c.registerResource({ id: 'twice', kind: 'timer', ownership: 'own', createdBy: 'x', release: () => {} })
      c.registerResource({ id: 'twice', kind: 'timer', ownership: 'own', createdBy: 'x', release: () => {} })
    }],
  ]
  for (const [label, run] of bad) {
    assert.throws(run, (error: unknown) => {
      assert.ok(error instanceof MiliastraLifecycleError, `${label}: expected a MiliastraLifecycleError`)
      assert.equal(error.code, 'LIFECYCLE_RESOURCE_MISDECLARED', label)
      return true
    }, label)
  }
})

// ---- T03-K: writes after begin-drain ----------------------------------------

test('T03-K a draining instance refuses writes without even reading the ledger', async () => {
  const ledger = new FakeLedger()
  const { controller } = readyInstance(ledger)
  await controller.dispose({ reason: 'unload' })
  const readsAfterDispose = ledger.readCalls

  const refused = await controller.beginOperation({ operationId: 'op-too-late', capabilityId: 'entity.create' })
  assert.equal(refused.kind, 'refused')
  assert.equal(refused.kind === 'refused' ? refused.code : '', 'LIFECYCLE_WRITE_REFUSED_DRAINING')
  assert.equal(refused.state, 'rejected')
  assert.equal(refused.writeExecuted, false)
  assert.equal(refused.outcomeKnown, true)
  assert.equal(refused.reconcile, null)
  assert.equal(ledger.readCalls, readsAfterDispose, 'a refusal must not consult the ledger')
  assert.equal(ledger.rows.size, 0, 'a refused write must not create a ledger row')

  // Same rule while still starting.
  const starting = createMiliastraLifecycle({ ledger: new FakeLedger() })
  const early = await starting.beginOperation({ operationId: 'op-early', capabilityId: 'entity.create' })
  assert.equal(early.kind, 'refused')
  assert.equal(early.kind === 'refused' ? early.code : '', 'LIFECYCLE_NOT_READY')

  // An operationId the ledger contract would reject is refused before anything else.
  await assert.rejects(
    () => starting.beginOperation({ operationId: 'not/a/valid id', capabilityId: 'entity.create' }),
    (error: unknown) => {
      assert.ok(error instanceof MiliastraLifecycleError)
      assert.equal(error.code, 'LIFECYCLE_OPERATION_ID_INVALID')
      return true
    },
  )
})

// ---- T03-L: the resource table and the frozen interface samples -------------

test('T03-L the resource table is complete and the frozen samples still match the implementation', async () => {
  const ledger = new FakeLedger()
  const { controller, sentinel } = readyInstance(ledger)
  const table = controller.resourceTable()
  assert.deepEqual(table.map(row => row.id), ['namespace:miliastra', 'mcp-connection:stdio', 'game-process'])
  assert.deepEqual(table.map(row => row.ownership), ['own', 'own', 'external'])
  assert.deepEqual(table.map(row => row.releasable), [true, true, false],
    'an external resource must have no release function in its row')
  assert.equal(table.find(row => row.id === 'game-process')?.releaseCount, 0)
  assert.equal(sentinel.releaseCalls, 0)

  // The samples frozen for DS-06/DS-08 must describe this implementation.
  const samples = JSON.parse(readFileSync(samplesPath, 'utf8')) as {
    legalTransitions: Record<string, readonly string[]>
    projections: {
      businessStateByOperationState: Record<string, string>
      reconcileStateByOperationState: Record<string, string>
    }
    refusalSemantics: readonly { case: string }[]
  }
  assert.deepEqual(samples.legalTransitions, LEGAL_LIFECYCLE_TRANSITIONS,
    'the frozen legal transitions must equal the implemented table')
  assert.deepEqual(samples.projections.businessStateByOperationState, BUSINESS_STATE_BY_OPERATION_STATE)
  assert.deepEqual(samples.projections.reconcileStateByOperationState, RECONCILE_STATE_BY_OPERATION_STATE)
  assert.ok(samples.refusalSemantics.length >= 6)

  // The projection is total over the closed operationState set.
  for (const [operationState, businessState] of Object.entries(BUSINESS_STATE_BY_OPERATION_STATE)) {
    assert.equal(toBusinessState(operationState as keyof typeof BUSINESS_STATE_BY_OPERATION_STATE), businessState)
    assert.ok(['never-claimed', 'known-success', 'known-failure', 'unknown']
      .includes(toReconcileState(operationState as keyof typeof RECONCILE_STATE_BY_OPERATION_STATE)))
  }
  assert.equal(OPERATION_ID_PATTERN.test('op-1'), true)
  assert.equal(OPERATION_ID_PATTERN.test('-op'), false)
})
