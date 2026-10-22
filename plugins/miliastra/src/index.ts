/**
 * Miliastra (千星奇域) authoring tools as a dsh Cordis plugin.
 *
 * Namespace (function) plugin: named `name` / `inject` / `Config` / `apply`
 * exports and **no default export** — Cordis discards a function plugin's whole
 * namespace when a default export is present alongside it, so the loader-composition
 * spec asserts the absence explicitly.
 *
 * What one instance does, in order:
 * 1. Prove the config ({@link resolveMiliastraConfig}) — absolute paths, a real
 *    interpreter, an evidence root inside the project. This runs before any
 *    effect, tool, or child process exists.
 * 2. Compose the business backend through the slot in `./composition.ts`
 *    (T02's `src/backend.ts`), which owns the MCP client and the tool table.
 * 3. Mount the T03 lifecycle controller (`./lifecycle.ts`) with the **real**
 *    ledger port (`./ledger-port.ts`), register the resource the instance owns
 *    and the external processes it must never touch, and only then publish
 *    readiness.
 * 4. Report the outcome honestly: `ready` only when the backend says it
 *    published a tool surface; otherwise `unavailable`/`failed` with the reason.
 *    With `failOnStartupError` (the default) a non-ready backend fails
 *    activation instead of leaving a mounted plugin with no tools.
 *
 * It never starts the game, the editor, the elevated helper, or the bridge, and
 * it holds no machine-specific path of its own.
 *
 * @module @miliastra/dsh-miliastra
 */

import type { Context } from '@deepseek-ai/cordis'
import {
  resolveMiliastraConfig,
  type MiliastraConfigValues,
} from './config.ts'
import {
  composeBackend,
  defaultBackendSpecifier,
  importBackendModule,
  MiliastraCompositionError,
  type MiliastraBackendStatus,
} from './composition.ts'
import { type MiliastraBackendResources } from './backend.ts'
import { createMiliastraLifecycle, type MiliastraResource } from './lifecycle.ts'
import { createMiliastraLedgerPort, defaultLedgerRoot } from './ledger-port.ts'

export { Config, MiliastraConfigError } from './config.ts'
export type {
  MiliastraConfigErrorCode,
  MiliastraConfigInput,
  MiliastraConfigValues,
  ResolvedMiliastraConfig,
} from './config.ts'
export {
  defaultBackendSpecifier,
  importBackendModule,
  MiliastraCompositionError,
} from './composition.ts'
export type {
  MiliastraBackendModule,
  MiliastraBackendState,
  MiliastraBackendStatus,
} from './composition.ts'
export {
  createMiliastraLedgerPort,
  defaultLedgerRoot,
  MiliastraLedgerPortError,
  MiliastraPythonLedgerPort,
} from './ledger-port.ts'
export type {
  MiliastraLedgerPortErrorCode,
  MiliastraPythonLedgerPortOptions,
  MiliastraReceiptBearingObservation,
} from './ledger-port.ts'
export { createMiliastraLifecycle, MiliastraLifecycleError } from './lifecycle.ts'

/** Cordis plugin name used by Loader diagnostics. */
export const name = 'miliastra'

/**
 * Services required by this plugin. `tools` is the dsh tool registry
 * (`@deepseek-ai/dsh-tools`): without it there is nowhere to publish a business
 * tool, so the fiber must stay pending rather than report a ready plugin with an
 * empty tool table.
 */
export const inject = ['tools']

/**
 * Resolve the backend specifier for one instance.
 * @param config - resolved config.
 * @param entryModuleUrl - `import.meta.url` of this module.
 * @returns the operator's specifier, or this package's own `./backend` sibling.
 */
function backendSpecifier(config: MiliastraConfigValues, entryModuleUrl: string): string {
  return config.backendModule === '' ? defaultBackendSpecifier(entryModuleUrl) : config.backendModule
}

/**
 * The external processes this plugin must never release, stop or kill.
 *
 * Registered as `external` so the ledger of what an unload touches is complete:
 * an `external` row has no release function and the controller refuses one
 * (EXECUTION-CONTRACT.md:49). The game, the editor, the elevated helper and the
 * editor bridge belong to the user and outlive every plugin instance.
 */
export const EXTERNAL_PROCESS_RESOURCES: readonly MiliastraResource[] = Object.freeze([
  Object.freeze({ id: 'game-process', kind: 'game-process', ownership: 'external', createdBy: 'user' }),
  Object.freeze({ id: 'editor-process', kind: 'editor-process', ownership: 'external', createdBy: 'user' }),
  Object.freeze({ id: 'elevated-helper', kind: 'elevated-helper', ownership: 'external', createdBy: 'user' }),
  Object.freeze({ id: 'editor-bridge', kind: 'editor-bridge', ownership: 'external', createdBy: 'user' }),
] as const) as readonly MiliastraResource[]

/**
 * The resource row for a composed backend's MCP connection and tool table.
 *
 * **Not currently registered.** The MCP connection, its tool table and its
 * child process are owned by the backend composition itself: `composeBackend`
 * already hangs `handle.dispose()` on the plugin instance's own
 * `ctx.effect` (`src/backend.ts`), and the vendored `@deepseek-ai/dsh-mcp-client`
 * owns the transport. Registering a second `own` row here would be a second
 * connection controller, which `src/lifecycle.ts`'s own header warns against.
 *
 * There is also a mechanical reason it is not called from `apply()`: the handle
 * is looked up with `backendResources(ctx)`, which walks `ctx.parent`, and
 * Cordis refuses that property unless the plugin declares it in `inject` —
 * measured: `Error: cannot get property "parent" without inject`, which fails
 * activation outright.
 *
 * It is kept exported because unifying the two owners is a deliberate change
 * (move the disposal from the backend's effect to this table, in
 * `src/backend.ts`) and this is the row that change would use. Until then the
 * unload report does not name the MCP connection; the plugin fiber still
 * releases it.
 *
 * @param serverName - the namespace the handle belongs to.
 * @param handle - the backend resource handle, when a backend composed.
 * @returns the row, or undefined when there is nothing to register.
 */
export function backendConnectionResource(
  serverName: string,
  handle: MiliastraBackendResources | undefined,
): MiliastraResource | undefined {
  if (handle === undefined) return undefined
  return {
    id: `mcp-connection:${serverName}`,
    kind: 'mcp-connection',
    ownership: 'own',
    createdBy: 'mcp-client:transport',
    release: async () => { await handle.dispose({ reason: 'lifecycle unload' }) },
  }
}

/**
 * Compose this plugin instance.
 *
 * @param ctx - the plugin instance context; `ctx.tools` is available (see {@link inject}).
 * @param config - config validated by {@link Config} and defaulted by Cordis.
 * @returns a promise that settles once the backend composition has been decided.
 * @throws MiliastraConfigError when the config is unusable, and
 * MiliastraCompositionError when `failOnStartupError` is set and the backend is
 * not ready.
 */
export async function apply(ctx: Context, config: MiliastraConfigValues): Promise<void> {
  // Step 1: reject an unusable config before anything can register or spawn.
  const resolved = resolveMiliastraConfig(config)

  // Step 2: mount the lifecycle controller with the REAL ledger port, and do it
  // BEFORE the backend composes, because the backend is handed a permit bound to
  // it. Mounting it afterwards — the previous order — left `beginOperation` with
  // no caller at all: the write gate consulted only its own drain state, so the
  // permit this controller owns was never asked for and T03's admission
  // semantics (`existing` replays, `refused` during drain) never applied to a
  // real dispatch.
  //
  // The port is a child process over the project's own business ledger. It is
  // deliberately not the `fixtures/t03-fake-ledger.ts` stand-in: mounting that in
  // production would let the plugin invent ledger rows. If the ledger cannot be
  // read, every lifecycle read fails closed with `LIFECYCLE_LEDGER_UNAVAILABLE`
  // and no write is admitted. Construction spawns nothing (the child starts on
  // the first request), so mounting it first costs no process.
  const { port, resource } = createMiliastraLedgerPort({
    pythonExecutable: resolved.pythonExecutable,
    projectRoot: resolved.projectRoot,
    ledgerRoot: defaultLedgerRoot(resolved.projectRoot),
    serverName: resolved.serverName,
    requestTimeoutMs: resolved.toolCallTimeoutMs,
  })
  const lifecycle = createMiliastraLifecycle({ ledger: port, serverName: resolved.serverName })

  // The ledger port is released last, and only through the controller's own
  // bounded resource loop. The composed backend's MCP connection is NOT
  // registered: the composition's own `ctx.effect` owns it (see
  // `backendConnectionResource` for why).
  lifecycle.registerResource(resource)
  for (const external of EXTERNAL_PROCESS_RESOURCES) lifecycle.registerResource(external)

  // Step 3: compose the backend through the slot, handing it the ONE permit
  // this instance has. A missing module is a legitimate state, not an
  // exception: it means no backend is wired yet.
  const specifier = backendSpecifier(resolved, import.meta.url)
  const backend = await importBackendModule(specifier, import.meta.url)
  const status: MiliastraBackendStatus = backend === undefined
    ? {
        state: 'unavailable',
        serverName: null,
        tools: [],
        detail: `backend module ${specifier} is not present in this package`,
      }
    : await composeBackend(backend, ctx, resolved,
      request => lifecycle.beginOperation(request))

  // Step 4: publish the outcome, and enforce the operator's failure policy.
  const logger = ctx.root.logger?.('miliastra')
  if (status.state !== 'ready') {
    logger?.warn('backend %C: %s', status.state, status.detail ?? 'no detail reported')
    // A backend that never became ready owns no tools, so the controller has
    // nothing to gate and nothing will dispose it: release the ledger port here.
    await lifecycle.dispose({ reason: `backend not ready: ${status.state}` })
    if (resolved.failOnStartupError) {
      throw new MiliastraCompositionError('BACKEND_NOT_READY', specifier,
        `reported state ${status.state}: ${status.detail ?? 'no detail reported'}`)
    }
    return
  }

  // Readiness is published only now: the backend reported a live tool surface
  // and the lifecycle has a real ledger to consult. A write can only be
  // dispatched after this point, so no permit is ever refused `LIFECYCLE_NOT_READY`
  // in the ready path.
  lifecycle.markReady(`backend ${status.serverName ?? ''} published ${String(status.tools.length)} tool(s)`)

  ctx.effect(() => () => { void lifecycle.dispose({ reason: 'plugin unload' }) })

  logger?.info('ready: %C tools via serverName %C', String(status.tools.length), status.serverName ?? '')
}
