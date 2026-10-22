/**
 * Frozen fixtures for the T03 resource half: an external process sentinel, the
 * own resources one plugin instance registers, a release that never settles, and
 * a tool registry that proves contributions are revoked.
 *
 * The sentinel stands in for "the user's game / the editor / the resident
 * helper". It is deliberately a **live-looking process stand-in with a `kill`
 * method**: the point of the tests is not that the lifecycle code forgets to
 * call `kill`, it is that the code has no way to reach it. A `dispose()` that
 * ends with `killCalls === 0` and the sentinel still alive is the honest
 * evidence EXECUTION-CONTRACT.md:49 asks for.
 *
 * @module @miliastra/dsh-miliastra/fixtures/t03-resources
 */

import type { MiliastraResource } from '../src/lifecycle.ts'

/** A process-like stand-in that records how it was treated. */
export class ExternalSentinel {
  /** Stable id, e.g. `game-process` or `elevated-helper`. */
  readonly id: string
  /** Whether the stand-in process is still running. */
  alive = true
  /** How many times anything called `release()` on it. Must stay 0. */
  releaseCalls = 0
  /** How many times anything called `kill()` on it. Must stay 0. */
  killCalls = 0

  constructor(id: string) {
    this.id = id
  }

  /** The release function the plugin must never be handed. */
  release(): void {
    this.releaseCalls += 1
    this.alive = false
  }

  /** The escalation the plugin must never be able to perform. */
  kill(): void {
    this.killCalls += 1
    this.alive = false
  }
}

/** A {@link MiliastraResource} for an external stand-in process. */
export function externalSentinelResource(sentinel: ExternalSentinel): MiliastraResource {
  const kind = sentinel.id === 'game-process' || sentinel.id === 'editor-process'
    ? 'editor-process' as const
    : sentinel.id === 'elevated-helper'
      ? 'elevated-helper' as const
      : 'editor-bridge' as const
  // Note: `release` is deliberately NOT attached, even though the sentinel has
  // one — the type forbids it, and the lifecycle controller refuses it at
  // registration. The sentinel is only ever touched through `describe()`.
  return {
    id: sentinel.id,
    kind,
    ownership: 'external',
    createdBy: 'user',
  }
}

/** One own resource whose `release()` records that it ran. */
export class TrackedOwnResource {
  /** Id in the resource table. */
  readonly id: string
  /** Everything the resource is allowed to do on release, in order. */
  readonly releaseLog: string[] = []

  constructor(id: string) {
    this.id = id
  }

  /** Also used as the resource table entry. */
  entry(kind: MiliastraResource['kind'] = 'listener'): MiliastraResource {
    return {
      id: this.id,
      kind,
      ownership: 'own',
      createdBy: 'plugin-instance',
      release: () => { this.releaseLog.push(this.id) },
    }
  }
}

/**
 * An own resource whose `release()` never settles — the "fake connection that
 * will not end" case (T03.md §6 row 7).
 *
 * `killCalls` exists so the test can prove the controller did not escalate: the
 * object exposes a `kill()`, and it must never be reached.
 */
export class StuckOwnResource {
  /** Id in the resource table. */
  readonly id: string
  /** How many times `release()` was entered. Must be exactly 1. */
  releaseCalls = 0
  /** Escalations. Must stay 0. */
  killCalls = 0
  /** Resolving this ends the stuck release, if a later test wants to. */
  private settle: (() => void) | null = null

  constructor(id: string) {
    this.id = id
  }

  /** A promise that never settles unless {@link unstick} is called. */
  release(): Promise<void> {
    this.releaseCalls += 1
    return new Promise<void>(resolve => { this.settle = resolve })
  }

  /** Let the stuck release finish. */
  unstick(): void {
    this.settle?.()
    this.settle = null
  }

  /** The escalation the controller must never reach. */
  kill(): void {
    this.killCalls += 1
  }

  /** The resource table entry. */
  entry(): MiliastraResource {
    return {
      id: this.id,
      kind: 'mcp-connection',
      ownership: 'own',
      createdBy: 'mcp-client:transport',
      release: () => this.release(),
    }
  }
}

/**
 * The smallest stand-in for `ctx.tools`: enough to prove that unload revokes
 * this instance's contributions and that re-enabling does not publish a second
 * copy of the same name.
 */
export class FakeToolRegistry {
  /** Live tool names, in registration order. */
  readonly live: string[] = []
  /** Every name ever offered, including duplicates that were refused. */
  readonly offered: string[] = []
  /** Registrations refused because the name was already live. */
  readonly duplicates: string[] = []

  /**
   * Offer a tool name.
   * @param toolName - the model-facing name.
   * @returns a disposer that removes exactly this registration.
   * @throws Error when the name is already live, mirroring ToolLayer's NamedEntries.
   */
  register(toolName: string): () => void {
    this.offered.push(toolName)
    if (this.live.includes(toolName)) {
      this.duplicates.push(toolName)
      throw new Error(`tool "${toolName}" is already registered`)
    }
    this.live.push(toolName)
    let disposed = false
    return () => {
      if (disposed) return
      disposed = true
      const index = this.live.indexOf(toolName)
      if (index >= 0) this.live.splice(index, 1)
    }
  }
}
