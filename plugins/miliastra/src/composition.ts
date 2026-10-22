/**
 * The backend composition slot.
 *
 * `src/index.ts` owns *when* the business backend is composed and *with what*
 * resolved config; this module owns *how a backend module is found and called*.
 * T02 fills the slot with `src/backend.ts`, which maps the resolved config onto
 * the vendored `@deepseek-ai/dsh-mcp-client` stdio transport and reports what it
 * actually published. Until that module exists the slot is honestly reported as
 * `unavailable` — the plugin never registers a placeholder tool that would
 * silently succeed.
 *
 * The slot takes a plain module specifier rather than a Loader entry so the
 * plugin can report a *typed* status for a backend it could not compose. The
 * specifier is operator config, restricted to a relative form
 * ({@link resolveMiliastraConfig} rejects anything else): the model never picks
 * a command, module, or working directory.
 *
 * @module @miliastra/dsh-miliastra/composition
 */

import { existsSync } from 'node:fs'
import { extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import type { ResolvedMiliastraConfig } from './config.ts'

/**
 * How far the backend composition actually got. `ready` means the module
 * composed and reported a live tool surface; `unavailable` means it is absent
 * or refused to claim readiness; `failed` means it threw. Only `ready` may be
 * presented to a model as working.
 */
export type MiliastraBackendState = 'ready' | 'unavailable' | 'failed'

/** What the backend module reports after composing. */
export interface MiliastraBackendStatus {
  /** Composition outcome; see {@link MiliastraBackendState}. */
  state: MiliastraBackendState
  /** MCP server namespace actually used, or null when nothing composed. */
  serverName: string | null
  /** Model-visible tool names actually published, in registration order. */
  tools: readonly string[]
  /** Operator-facing reason for a non-ready state; null when ready. */
  detail: string | null
}

/**
 * The one admission port a composed backend may consult before dispatching a write.
 *
 * This is T03's `beginOperation` (`src/lifecycle.ts`), passed in as a port rather
 * than imported: `src/backend.ts` must not depend on the lifecycle module, and
 * `src/index.ts` is the only place that owns both and can hand one to the other.
 *
 * The request is exactly `MiliastraOperationRequest`: the caller's
 * `operationId` (the business idempotency key, on the wire `requestId`) and the
 * `capabilityId` the dispatch realises. The returned admission is T03's
 * `MiliastraDispatchAdmission`, read only for its discriminating `kind`: only
 * `granted` may dispatch, `existing` must be reported from the ledger, and
 * `refused` must not reach the backend at all.
 */
export type MiliastraDispatchGate = (request: {
  readonly operationId: string
  readonly capabilityId: string
}) => Promise<MiliastraDispatchAdmissionLike>

/**
 * The three outcomes a gate can report, in the permit's own vocabulary.
 *
 * A structural projection of T03's `MiliastraDispatchAdmission`, not a second
 * definition of it: every member of that union carries these fields, so the
 * real admission is assignable without either module importing the other. Only
 * the fields `src/backend.ts` reads are named — `operationState` for the
 * `existing` replay and `code` for the `refused` reason.
 */
export type MiliastraDispatchAdmissionLike =
  | {
      /** The dispatch may proceed, exactly once. */
      readonly kind: 'granted'
      readonly operationId: string
      readonly capabilityId: string
    }
  | {
      /** The business ledger already knows this operation; dispatch nothing. */
      readonly kind: 'existing'
      readonly operationId: string
      readonly capabilityId: string
      readonly operationState: string
    }
  | {
      /** This instance will not write: draining, starting, or ledger unavailable. */
      readonly kind: 'refused'
      readonly operationId: string
      readonly capabilityId: string
      readonly code: string
    }

/**
 * The contract `src/backend.ts` (T02) must satisfy.
 *
 * The module may register effects, tools, and child plugins on `ctx`: whatever
 * it registers belongs to the plugin instance's fiber and is disposed with it.
 * It must not spawn the game, the editor, the elevated helper, or the bridge.
 */
export interface MiliastraBackendModule {
  /**
   * Compose the business backend for one plugin instance.
   * @param ctx - the plugin instance context, carrying the injected `tools` service.
   * @param config - frozen resolved config; already proven to exist on disk.
   * @param gate - the dispatch permit. When supplied, every write the composed
   * table exposes is admitted through it before it reaches the transport; when
   * omitted the composition keeps only its own drain-state gate.
   * @returns the status of what was actually published.
   */
  composeBackend(
    ctx: Context,
    config: ResolvedMiliastraConfig,
    gate?: MiliastraDispatchGate,
  ): MiliastraBackendStatus | Promise<MiliastraBackendStatus>
}

/** Stable failure codes for backend composition. */
export type MiliastraCompositionErrorCode =
  | 'BACKEND_MODULE_INVALID'
  | 'BACKEND_MODULE_UNREADABLE'
  | 'BACKEND_COMPOSE_FAILED'
  | 'BACKEND_NOT_READY'

/** A backend composition failure that is the plugin's, not the model's, to fix. */
export class MiliastraCompositionError extends Error {
  /** Machine-checkable reason. */
  readonly code: MiliastraCompositionErrorCode
  /** Module specifier or `serverName` the failure belongs to. */
  readonly subject: string

  constructor(code: MiliastraCompositionErrorCode, subject: string, detail: string, options?: { cause?: unknown }) {
    super(`${code}: ${subject} ${detail}`, options)
    this.name = 'MiliastraCompositionError'
    this.code = code
    this.subject = subject
  }
}

/**
 * Default backend specifier for a plugin entry module.
 *
 * The emitted build and the source tree are both loadable (Node strips types
 * from `.ts`; the build emits `.js`), so the sibling's extension follows the
 * entry module's own extension instead of a hardcoded one that would be wrong
 * from one of the two.
 * @param entryModuleUrl - `import.meta.url` of the entry module.
 * @returns `./backend.ts` or `./backend.js`, matching the entry's extension.
 */
export function defaultBackendSpecifier(entryModuleUrl: string): string {
  return extname(fileURLToPath(entryModuleUrl)) === '.ts' ? './backend.ts' : './backend.js'
}

/**
 * Load the backend module named by `specifier`, resolved against `baseUrl`.
 *
 * A missing file is a legitimate state (the slot is not filled yet, or an
 * operator disabled it) and reports `undefined`; a file that exists but cannot
 * be imported, or that does not export `composeBackend`, is a defect and throws
 * with the module named. The distinction is deliberate: "not there yet" must not
 * look the same as "there and broken".
 *
 * @param specifier - relative module specifier, e.g. `./backend.js`.
 * @param baseUrl - the entry module URL the specifier resolves against.
 * @returns the loaded module, or `undefined` when the file is absent.
 * @throws MiliastraCompositionError when the file exists but is not a usable module.
 */
export async function importBackendModule(
  specifier: string,
  baseUrl: string,
): Promise<MiliastraBackendModule | undefined> {
  let moduleUrl: URL
  try {
    moduleUrl = new URL(specifier, baseUrl)
  } catch (error) {
    throw new MiliastraCompositionError('BACKEND_MODULE_INVALID', specifier,
      `does not resolve against ${baseUrl}`, { cause: error })
  }
  if (moduleUrl.protocol !== 'file:') {
    throw new MiliastraCompositionError('BACKEND_MODULE_INVALID', specifier,
      `must resolve to a file URL, resolved to ${moduleUrl.href}`)
  }
  if (!existsSync(fileURLToPath(moduleUrl))) return undefined

  let namespace: Record<string, unknown>
  try {
    namespace = await import(moduleUrl.href) as Record<string, unknown>
  } catch (error) {
    throw new MiliastraCompositionError('BACKEND_MODULE_UNREADABLE', specifier,
      `exists but failed to import (${moduleUrl.href})`, { cause: error })
  }
  if (typeof namespace.composeBackend !== 'function') {
    throw new MiliastraCompositionError('BACKEND_MODULE_INVALID', specifier,
      `must export a composeBackend() function; found exports: ${Object.keys(namespace).join(', ') || '(none)'}`)
  }
  return namespace as unknown as MiliastraBackendModule
}

/**
 * Call the backend slot and normalize a thrown backend into a `failed` status,
 * so the caller can apply one policy (log, or fail activation) to every
 * non-ready outcome.
 *
 * @param backend - the loaded backend module.
 * @param ctx - the plugin instance context.
 * @param config - resolved config.
 * @param gate - the dispatch permit to hand the backend, when the plugin has one.
 * @returns the backend's status, or a `failed` status describing what it threw.
 */
export async function composeBackend(
  backend: MiliastraBackendModule,
  ctx: Context,
  config: ResolvedMiliastraConfig,
  gate?: MiliastraDispatchGate,
): Promise<MiliastraBackendStatus> {
  try {
    return await backend.composeBackend(ctx, config, gate)
  } catch (error) {
    if (error instanceof MiliastraCompositionError) throw error
    return {
      state: 'failed',
      serverName: null,
      tools: [],
      detail: error instanceof Error ? error.message : String(error),
    }
  }
}
