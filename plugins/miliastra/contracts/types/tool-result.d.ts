/**
 * Miliastra business tool contract, contractVersion "1".
 *
 * Hand-written to mirror `schemas/tool-result.schema.json`, `schemas/operation-request.schema.json`
 * and `schemas/ledger-record.schema.json`.  The mirror is not maintained by faith: run
 * `python -B plugins/miliastra/contracts/validate.py --ts-typecheck` and it will parse this file
 * with the vendored TypeScript compiler and cross-check every literal union below against the
 * machine-readable contract.
 *
 * Read plugin/miliastra/contracts/contract.json for the normative enums and their sources.
 */

/* ------------------------------------------------------------------ states */

/** Lifecycle of ONE business operation, as observable on disk. Authoritative. */
export type OperationState =
  | 'never-claimed'
  | 'claimed'
  | 'dispatched'
  | 'known-complete'
  | 'known-failed'
  | 'outcome-unknown';

/** T06.md:42's vocabulary. A lossy projection of OperationState - never persisted as the truth. */
export type ReconcileState = 'never-claimed' | 'known-success' | 'known-failure' | 'unknown';

/** The model-facing verdict. This is the field named `state`. */
export type BusinessState = 'rejected' | 'pending' | 'unknown' | 'failed' | 'completed';

/* ------------------------------------------------------------------ stages */

/** Per-tool-call stages. `persistence` is an input alias for `saveDiff` and must never be emitted. */
export type StageName = 'liveReadback' | 'saveDiff' | 'reopen' | 'runtime' | 'cleanup';

export type StageStatus = 'not-run' | 'pass' | 'fail' | 'blocked' | 'unknown' | 'not-applicable';

/** Task run records use a wider set. A tool call must never assert the first five. */
export type TaskStageName =
  | 'source'
  | 'offline'
  | 'loader'
  | 'mcp'
  | 'aiToolCall'
  | StageName;

export interface Stage {
  status: StageStatus;
  /** Required (non-empty) for every status other than `pass`. */
  reason?: string;
  /** Required (at least one element) when status is `pass`. Evidence for THIS stage only. */
  evidenceRef: string[];
  evidenceSha256?: string[];
  detail?: Record<string, unknown> | null;
}

export interface Stages {
  liveReadback: Stage;
  saveDiff: Stage;
  reopen: Stage;
  runtime: Stage;
  cleanup: Stage;
}

/* ------------------------------------------------------------------ errors */

/**
 * `disposition` fixes where the error was produced relative to the dispatch boundary.
 * A deterministic refusal never follows a dispatch; an unknown outcome never precedes one.
 */
export type ErrorDisposition =
  | 'refusal-before-dispatch'
  | 'version-gate'
  | 'failure-after-dispatch'
  | 'unknown-after-dispatch';

export type ErrorPhase = 'before-dispatch' | 'after-dispatch';
export type SideEffect = 'none' | 'possible' | 'observed';
export type UpstreamLayer =
  | 'business'
  | 'ledger'
  | 'queue-client'
  | 'queue-runner'
  | 'native-cli'
  | 'native-probe'
  | 'bridge';

/** Codes this surface may emit. Anything else is an upstream code and belongs in `upstream`. */
export type ToolErrorCode =
  | 'REQUEST_ID_INVALID'
  | 'REQUEST_ID_CONFLICT'
  | 'REQUEST_INCOMPLETE_CLAIM'
  | 'REQUEST_OUTCOME_UNKNOWN'
  | 'NATIVE_WRITE_REVIEW_REQUIRED'
  | 'CAPABILITY_NOT_ENABLED'
  | 'CONTRACT_VERSION_UNSUPPORTED'
  | 'INCOMPATIBLE_VERSION'
  | 'TARGET_HANDLE_INVALID'
  | 'TARGET_HANDLE_UNKNOWN'
  | 'TARGET_HANDLE_RECEIPT_CHANGED'
  | 'TARGET_HANDLE_UNVERIFIED'
  | 'TARGET_STALE_REVISION'
  | 'TEMPLATE_ID_NOT_AN_INTEGER'
  | 'TEMPLATE_NOT_SUPPORTED'
  | 'TRANSFORM_INVALID'
  | 'SCALE_NOT_POSITIVE'
  | 'LEVEL_AT_CAPACITY'
  | 'EXECUTION_LAYER_UNAVAILABLE'
  | 'EXECUTION_LAYER_BLOCKED'
  | 'EXECUTION_LAYER_BUSY'
  | 'EVIDENCE_INTEGRITY_FAILED'
  | 'UPSTREAM_RECEIPT_UNREADABLE'
  | 'UPSTREAM_PENDING'
  | 'READBACK_FAILED'
  | 'READBACK_WRONG_LEVEL'
  | 'READBACK_NOT_ACCEPTED'
  | 'CREATE_EFFECT_NOT_AS_REQUESTED'
  | 'SAVE_STATUS_NOT_SUCCESS'
  | 'SAVE_TOUCHED_PROTECTED_TARGET'
  | 'CLEANUP_IDS_EMPTY'
  | 'CLEANUP_IDS_OVER_LIMIT'
  | 'CLEANUP_IDS_DUPLICATED'
  | 'CLEANUP_IDS_NOT_UINT32'
  | 'CLEANUP_REQUEST_NOT_COMPLETE'
  | 'CLEANUP_REQUEST_NOT_A_CREATE'
  | 'CLEANUP_ID_NOT_OWNED_BY_THIS_RUN'
  | 'CLEANUP_BRIDGE_UNAVAILABLE'
  | 'CANCELLED_BEFORE_DISPATCH'
  | 'TOOL_UNAVAILABLE_IN_PROFILE';

export interface ReconciliationRoute {
  operationId: string;
  ledgerRef: string;
  requestId?: string | null;
  journalRef?: string | null;
}

export interface UpstreamError {
  layer: UpstreamLayer;
  /** Raw code from the lower layer, e.g. NATIVE_SCENE_PREVIOUS_OUTCOME_UNRESOLVED. */
  code: string;
  message?: string | null;
}

export interface ToolError {
  code: ToolErrorCode;
  disposition: ErrorDisposition;
  phase: ErrorPhase;
  sideEffect: SideEffect;
  message: string;
  target?: string | null;
  operationId?: string | null;
  /** Mandatory when disposition is 'unknown-after-dispatch'. */
  reconcile?: ReconciliationRoute | null;
  upstream?: UpstreamError | null;
  detail?: Record<string, unknown> | null;
}

/* ------------------------------------------------------------------ result */

export type NextAction =
  | 'none'
  | 'fix-input'
  | 'poll-same-operation'
  | 'reconcile'
  | 'report-and-repair'
  | 'await-human';

export interface TargetBinding {
  levelId: number;
  sessionProcessCreation: number;
  sessionThreadCreation: number;
  sessionPid?: number | null;
  sessionImage?: string | null;
  backendProfileId: string;
  backendProfileSha256: string;
  mintedUtc: string;
  receiptSha256: string;
  revision?: string | null;
}

/**
 * Per-object outcome. A partial success is expressed here and never collapsed into the
 * top-level verdict; `not-attempted` is not a failure and the list it came from must not be
 * re-sent wholesale.
 */
export type ChangeResult =
  | 'created'
  | 'changed'
  | 'deleted'
  | 'unchanged'
  | 'refused'
  | 'not-attempted'
  | 'not-attempted:prior-unknown-outcome'
  | 'dispatched'
  | 'dispatched:threw-native'
  | 'dispatched:path-mismatch'
  | 'not-dispatched:target-changed'
  | 'not-dispatched:list-refused'
  | 'unknown';

export interface Change {
  objectId: number | null;
  result: ChangeResult;
  fields?: Record<string, unknown> | null;
  reason?: string | null;
  evidenceRef?: string | null;
}

export interface ToolResult {
  contractVersion: '1';
  capabilityId: string;
  method: string;
  operationId: string;
  caseId?: string | null;
  targetHandle: string | null;
  targetBinding?: TargetBinding;
  state: BusinessState;
  operationState?: OperationState;
  reconcileState?: ReconcileState;
  /** false exactly when state is 'pending' or 'unknown'. */
  outcomeKnown: boolean;
  /** null when not established; false only when no dispatch evidence exists. */
  writeExecuted: boolean | null;
  created?: boolean | null;
  saved?: boolean | null;
  deleted?: boolean | null;
  objectIds: number[];
  changed: Change[];
  failedItems: Change[];
  counts?: Record<string, number | null>;
  stages: Stages;
  error: ToolError | null;
  nextAction: NextAction;
  nextActionDetail?: string | null;
  /** Always false. No layer of this project retries automatically. */
  retryAttempted: false;
  replayed: boolean;
  /** Must equal (state === 'completed'); the transport's isError must equal its negation. */
  ok: boolean;
  backendKind?: string;
  notes?: string[];
}

/* ------------------------------------------------------------------ request */

/**
 * The complete argument surface of a Miliastra business tool.
 *
 * Every field that would let the caller select WHAT RUNS is structurally absent, and the
 * object is closed, so `scriptPath`, `executable`, `argv`, `shell`, `cwd`, `plan`, `pid`,
 * `tid`, `timeout`, `hash`, `queueDir`, `sessionPath`, `reviewPath`, `baselineRun`,
 * `recoveryDir`, `runId`, `helperPid`, `pinsDigest` and `deadlineUtc` cannot be represented
 * at all.  See contract.json boundary.forbiddenInToolCall.
 */
export interface OperationRequest {
  capabilityId:
    | 'scene.capabilities'
    | 'entity.discoverLevel'
    | 'entity.read'
    | 'entity.create'
    | 'entity.save'
    | 'entity.cleanupOwned'
    | 'operation.status';
  operationId: string;
  contractVersion: '1';
  caseId?: string | null;
  targetHandle?: string;
  expectedRevision?: string | null;
  templateId?: number;
  position?: [number, number, number];
  rotation?: [number, number, number];
  scale?: [number, number, number];
  objectIds?: number[];
  createdByOperationIds?: string[];
  dryRun?: boolean;
}

/* ------------------------------------------------------------------ ledger */

/** The minimum a business ledger row must carry for reconciliation. T06 owns the storage. */
export interface LedgerRecord {
  schemaVersion: 1;
  contractVersion: '1';
  operationId: string;
  caseId?: string | null;
  capabilityId: string;
  targetHandle: string | null;
  targetBinding?: Record<string, unknown> | null;
  expectedRevision?: string | null;
  payloadDigest?: string | null;
  state: OperationState;
  writeExecuted: boolean | null;
  /** The discriminator: which of these files proved the request left the process. */
  dispatchEvidence?: Array<
    | 'direct-launch-intent.json'
    | 'launch.claim'
    | 'attempt.used'
    | 'helper-request.json'
    | 'bridge-request.json'
  >;
  requestId?: string | null;
  claimSha256?: string | null;
  journalRef?: string | null;
  resultRef?: string | null;
  replayed?: boolean;
  retryAttempted: false;
  terminalReason?: string | null;
  createdUtc: string;
  updatedUtc: string;
  owner?: string | null;
}
