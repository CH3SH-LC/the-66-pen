/**
 * Configuration contract for the `miliastra` Cordis plugin.
 *
 * The Schemastery `Config` schema validates the *shape* of the operator-supplied
 * config before `apply` runs; {@link resolveMiliastraConfig} then proves the
 * *environment* (absolute paths, real files, containment) and yields the frozen
 * value the rest of the plugin composes from. Both steps run before any effect
 * registers, so an invalid config can never leave a half-mounted backend or a
 * spawned child process behind.
 *
 * No default here is a machine-specific path. `projectRoot` and
 * `pythonExecutable` are required with no fallback: a silently substituted path
 * would let a profile point the business backend at whatever checkout happens to
 * live on the machine.
 *
 * @module @miliastra/dsh-miliastra/config
 */

import { statSync } from 'node:fs'
import { isAbsolute, join, relative, resolve } from 'node:path'
import z from '@deepseek-ai/schemastery'

/** Version of the config contract itself; a resolved config carries it. */
export const MILIASTRA_CONFIG_VERSION = 1

/** Default per-MCP-tool-call timeout, matching the vendored mcp-client default. */
export const DEFAULT_TOOL_CALL_TIMEOUT_MS = 60_000

/** Lower bound accepted for `toolCallTimeoutMs`. */
export const MIN_TOOL_CALL_TIMEOUT_MS = 1_000

/** Upper bound accepted for `toolCallTimeoutMs` (one hour). */
export const MAX_TOOL_CALL_TIMEOUT_MS = 3_600_000

/**
 * Public tool namespace of one plugin instance. The vendored mcp-client builds
 * model-facing names as `mcp__<serverName>__<rawName>`, so this is the pattern
 * the whole tool table inherits.
 */
export const SERVER_NAME_PATTERN = /^[A-Za-z0-9_-]{1,32}$/

/**
 * Operator-supplied config as written in the profile patch or `cordis.yml`.
 * Fields carrying a schema default are optional here.
 */
export interface MiliastraConfigInput {
  /** Absolute path of the project checkout that owns the business backend. */
  projectRoot: string
  /** Absolute path of the Python interpreter that runs the business backend. */
  pythonExecutable: string
  /** Stable namespace segment of every model-visible tool name. */
  serverName: string
  /** Backend directory; empty selects `<projectRoot>/backend`. */
  backendRoot?: string
  /** Evidence directory; empty selects `<projectRoot>/.runtime/cordis-plugin-evidence`. */
  evidenceRoot?: string
  /** Per-tool-call timeout in milliseconds. */
  toolCallTimeoutMs?: number
  /** Composition slot for the backend module; empty selects the package's own `./backend`. */
  backendModule?: string
  /** Fail plugin activation when the backend cannot be composed or reports itself unavailable. */
  failOnStartupError?: boolean
}

/** Schema-validated config: every defaulted field is present, nothing is proven yet. */
export interface MiliastraConfigValues {
  projectRoot: string
  backendRoot: string
  pythonExecutable: string
  evidenceRoot: string
  serverName: string
  toolCallTimeoutMs: number
  backendModule: string
  failOnStartupError: boolean
}

/**
 * Fully resolved config. Every field is absolute and checked against the real
 * filesystem, except `backendModule`, which is a module specifier relative to
 * the plugin entry (see {@link MiliastraConfigValues.backendModule}).
 */
export interface ResolvedMiliastraConfig extends MiliastraConfigValues {
  /** Contract version this resolver produced. */
  readonly configVersion: typeof MILIASTRA_CONFIG_VERSION
}

/** Stable failure codes for config rejection, so callers can assert the reason. */
export type MiliastraConfigErrorCode =
  | 'MISSING_PATH'
  | 'NOT_ABSOLUTE'
  | 'NOT_A_DIRECTORY'
  | 'NOT_A_FILE'
  | 'EVIDENCE_ROOT_OUTSIDE_PROJECT'
  | 'INVALID_TIMEOUT'
  | 'INVALID_BACKEND_MODULE'

/** A config value that is unusable as given; thrown before any effect registers. */
export class MiliastraConfigError extends Error {
  /** Machine-checkable reason. */
  readonly code: MiliastraConfigErrorCode
  /** Config field responsible, when one is. */
  readonly field: string | undefined

  constructor(code: MiliastraConfigErrorCode, field: string | undefined, detail: string) {
    super(field === undefined ? `${code}: ${detail}` : `${code}: ${field} ${detail}`)
    this.name = 'MiliastraConfigError'
    this.code = code
    this.field = field
  }
}

/**
 * The plugin's Config schema. `.required()` marks the two genuinely
 * non-defaultable operator inputs; every path is validated only for being a
 * non-empty string here, because absolute-path and existence checks belong to
 * {@link resolveMiliastraConfig} where they can be reported as structured codes.
 */
export const Config = z.object({
  projectRoot: z.string().required(),
  backendRoot: z.string().default(''),
  pythonExecutable: z.string().required(),
  evidenceRoot: z.string().default(''),
  serverName: z.string().required().pattern(SERVER_NAME_PATTERN),
  toolCallTimeoutMs: z.number().step(1).min(MIN_TOOL_CALL_TIMEOUT_MS).max(MAX_TOOL_CALL_TIMEOUT_MS)
    .default(DEFAULT_TOOL_CALL_TIMEOUT_MS),
  backendModule: z.string().default(''),
  failOnStartupError: z.boolean().default(true),
}) as unknown as z<MiliastraConfigInput, MiliastraConfigValues>

/** Default evidence root, relative to the project checkout. */
export const DEFAULT_EVIDENCE_SUBDIR = join('.runtime', 'cordis-plugin-evidence')

/** Return whether `value` is absent or whitespace-only. */
function isBlank(value: string): boolean {
  return value.trim() === ''
}

/** Prove an absolute path exists and is a directory. */
function requireDirectory(field: string, value: string): string {
  const absolute = resolve(value)
  if (!isAbsolute(value)) {
    throw new MiliastraConfigError('NOT_ABSOLUTE', field, `must be an absolute path, received ${JSON.stringify(value)}`)
  }
  let stat
  try {
    stat = statSync(absolute)
  } catch {
    throw new MiliastraConfigError('NOT_A_DIRECTORY', field, `does not exist: ${absolute}`)
  }
  if (!stat.isDirectory()) {
    throw new MiliastraConfigError('NOT_A_DIRECTORY', field, `is not a directory: ${absolute}`)
  }
  return absolute
}

/**
 * Resolve and prove a config value: absolute paths, real interpreter, containment.
 *
 * @param input - schema-validated config values.
 * @returns a frozen, fully resolved config.
 * @throws MiliastraConfigError when a path is blank, relative, missing, of the
 * wrong kind, escapes the project root, or when a numeric/specifier rule is
 * violated.
 */
export function resolveMiliastraConfig(input: MiliastraConfigValues): ResolvedMiliastraConfig {
  if (isBlank(input.projectRoot)) {
    throw new MiliastraConfigError('MISSING_PATH', 'projectRoot', 'is required and has no machine-specific default')
  }
  if (isBlank(input.pythonExecutable)) {
    throw new MiliastraConfigError('MISSING_PATH', 'pythonExecutable', 'is required and has no machine-specific default')
  }
  if (!SERVER_NAME_PATTERN.test(input.serverName)) {
    throw new MiliastraConfigError('MISSING_PATH', 'serverName', `must match ${SERVER_NAME_PATTERN.source}, received ${JSON.stringify(input.serverName)}`)
  }
  if (!Number.isInteger(input.toolCallTimeoutMs)
    || input.toolCallTimeoutMs < MIN_TOOL_CALL_TIMEOUT_MS
    || input.toolCallTimeoutMs > MAX_TOOL_CALL_TIMEOUT_MS) {
    throw new MiliastraConfigError('INVALID_TIMEOUT', 'toolCallTimeoutMs',
      `must be an integer within ${MIN_TOOL_CALL_TIMEOUT_MS}..${MAX_TOOL_CALL_TIMEOUT_MS}, received ${String(input.toolCallTimeoutMs)}`)
  }

  const projectRoot = requireDirectory('projectRoot', input.projectRoot)
  const backendRoot = isBlank(input.backendRoot)
    ? requireDirectory('backendRoot', join(projectRoot, 'backend'))
    : requireDirectory('backendRoot', input.backendRoot)
  const pythonExecutable = (() => {
    if (!isAbsolute(input.pythonExecutable)) {
      throw new MiliastraConfigError('NOT_ABSOLUTE', 'pythonExecutable',
        `must be an absolute path, received ${JSON.stringify(input.pythonExecutable)}`)
    }
    const absolute = resolve(input.pythonExecutable)
    let stat
    try {
      stat = statSync(absolute)
    } catch {
      throw new MiliastraConfigError('NOT_A_FILE', 'pythonExecutable', `does not exist: ${absolute}`)
    }
    if (!stat.isFile()) {
      throw new MiliastraConfigError('NOT_A_FILE', 'pythonExecutable', `is not a file: ${absolute}`)
    }
    return absolute
  })()

  const evidenceRoot = isBlank(input.evidenceRoot)
    ? join(projectRoot, DEFAULT_EVIDENCE_SUBDIR)
    : resolve(input.evidenceRoot)
  if (!isBlank(input.evidenceRoot) && !isAbsolute(input.evidenceRoot)) {
    throw new MiliastraConfigError('NOT_ABSOLUTE', 'evidenceRoot',
      `must be an absolute path, received ${JSON.stringify(input.evidenceRoot)}`)
  }
  const escape = relative(projectRoot, evidenceRoot)
  if (escape === '..' || escape.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`) || isAbsolute(escape)) {
    throw new MiliastraConfigError('EVIDENCE_ROOT_OUTSIDE_PROJECT', 'evidenceRoot',
      `must stay inside projectRoot ${projectRoot}, received ${evidenceRoot}`)
  }

  if (!isBlank(input.backendModule) && !input.backendModule.startsWith('./') && !input.backendModule.startsWith('../')) {
    throw new MiliastraConfigError('INVALID_BACKEND_MODULE', 'backendModule',
      `must be a relative module specifier, received ${JSON.stringify(input.backendModule)}`)
  }

  return Object.freeze({
    configVersion: MILIASTRA_CONFIG_VERSION,
    projectRoot,
    backendRoot,
    pythonExecutable,
    evidenceRoot,
    serverName: input.serverName,
    toolCallTimeoutMs: input.toolCallTimeoutMs,
    backendModule: input.backendModule,
    failOnStartupError: input.failOnStartupError,
  })
}
