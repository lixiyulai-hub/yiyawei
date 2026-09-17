export const Phase = Object.freeze({
  WARMING: "warming",
  READY: "ready",
  RECORDING: "recording",
  PROCESSING: "processing",
  DONE: "done",
  ERROR: "error",
});

export const Event = Object.freeze({
  WARMUP_SUCCEEDED: "WARMUP_SUCCEEDED",
  WARMUP_FAILED: "WARMUP_FAILED",
  START_REQUESTED: "START_REQUESTED",
  STOP_REQUESTED: "STOP_REQUESTED",
  RECORDING_FAILED: "RECORDING_FAILED",
  PROCESS_SUCCEEDED: "PROCESS_SUCCEEDED",
  PROCESS_FAILED: "PROCESS_FAILED",
  RETRY_REQUESTED: "RETRY_REQUESTED",
  STATE_REFRESHED: "STATE_REFRESHED",
  SETTINGS_UPDATED: "SETTINGS_UPDATED",
  EDIT_STARTED: "EDIT_STARTED",
  EDIT_RESTORED: "EDIT_RESTORED",
  CONFIRM_SUCCEEDED: "CONFIRM_SUCCEEDED",
  CONFIRM_FAILED: "CONFIRM_FAILED",
  PASTE_SUCCEEDED: "PASTE_SUCCEEDED",
  PASTE_FAILED: "PASTE_FAILED",
});

export const SnapshotOrder = Object.freeze({
  NEWER: "newer",
  IDEMPOTENT: "idempotent",
});

export class InvalidTransitionError extends Error {}
export class SnapshotOrderingError extends Error {}
export class StaleRevisionError extends SnapshotOrderingError {}
export class RevisionConflictError extends SnapshotOrderingError {}
export class ContractValidationError extends TypeError {}
export class UnsupportedSchemaVersionError extends ContractValidationError {}

const PHASE_VALUES = new Set(Object.values(Phase));
const EVENT_VALUES = new Set(Object.values(Event));
const STRING_STATE_FIELDS = Object.freeze([
  "status",
  "target",
  "rawText",
  "finalText",
  "mode",
  "outputScript",
  "asrModel",
  "asrDevice",
  "llmModel",
  "asrMs",
  "llmMs",
  "recordId",
  "riskLevel",
  "lastError",
]);
const BOOLEAN_STATE_FIELDS = Object.freeze(["useFast", "pasted"]);
const NUMBER_STATE_FIELDS = Object.freeze(["elapsedSec", "level", "updatedAt"]);
const PHASE_CHANGES = new Map([
  [`${Phase.WARMING}:${Event.WARMUP_SUCCEEDED}`, Phase.READY],
  [`${Phase.WARMING}:${Event.WARMUP_FAILED}`, Phase.ERROR],
  [`${Phase.READY}:${Event.START_REQUESTED}`, Phase.RECORDING],
  [`${Phase.DONE}:${Event.START_REQUESTED}`, Phase.RECORDING],
  [`${Phase.ERROR}:${Event.START_REQUESTED}`, Phase.RECORDING],
  [`${Phase.RECORDING}:${Event.STOP_REQUESTED}`, Phase.PROCESSING],
  [`${Phase.RECORDING}:${Event.RECORDING_FAILED}`, Phase.ERROR],
  [`${Phase.PROCESSING}:${Event.PROCESS_SUCCEEDED}`, Phase.DONE],
  [`${Phase.PROCESSING}:${Event.PROCESS_FAILED}`, Phase.ERROR],
  [`${Phase.ERROR}:${Event.RETRY_REQUESTED}`, Phase.READY],
]);
const GLOBAL_SAME_PHASE_EVENTS = new Set([
  Event.STATE_REFRESHED,
  Event.SETTINGS_UPDATED,
]);
const DONE_SAME_PHASE_EVENTS = new Set([
  Event.EDIT_STARTED,
  Event.EDIT_RESTORED,
  Event.CONFIRM_SUCCEEDED,
  Event.CONFIRM_FAILED,
  Event.PASTE_SUCCEEDED,
  Event.PASTE_FAILED,
]);

export function transition(phase, event) {
  if (!PHASE_VALUES.has(phase)) {
    throw new InvalidTransitionError(`unknown phase ${JSON.stringify(phase)}`);
  }
  if (!EVENT_VALUES.has(event)) {
    throw new InvalidTransitionError(`unknown event ${JSON.stringify(event)}`);
  }

  const changed = PHASE_CHANGES.get(`${phase}:${event}`);
  if (changed !== undefined) return changed;
  if (GLOBAL_SAME_PHASE_EVENTS.has(event)) return phase;
  if (phase === Phase.DONE && DONE_SAME_PHASE_EVENTS.has(event)) return phase;
  throw new InvalidTransitionError(
    `event ${JSON.stringify(event)} is not legal while phase is ${JSON.stringify(phase)}`,
  );
}

function requireField(snapshot, field) {
  if (!Object.prototype.hasOwnProperty.call(snapshot, field)) {
    throw new ContractValidationError(`missing required field ${JSON.stringify(field)}`);
  }
  return snapshot[field];
}

function requireV1(snapshot) {
  if (snapshot === null || typeof snapshot !== "object" || Array.isArray(snapshot)) {
    throw new ContractValidationError("v1 snapshot must be an object");
  }
  const schemaVersion = requireField(snapshot, "schemaVersion");
  if (!Number.isInteger(schemaVersion)) {
    throw new ContractValidationError("field \"schemaVersion\" must be the integer 1");
  }
  if (schemaVersion !== 1) {
    throw new UnsupportedSchemaVersionError(
      `unsupported schemaVersion ${schemaVersion}; expected 1`,
    );
  }
}

function validateOrderingFields(snapshot) {
  requireV1(snapshot);
  const operationId = requireField(snapshot, "operationId");
  if (typeof operationId !== "string" || !operationId.trim()) {
    throw new ContractValidationError("field \"operationId\" must be a non-empty string");
  }
  const revision = requireField(snapshot, "revision");
  if (!Number.isInteger(revision) || revision < 0) {
    throw new ContractValidationError(
      "field \"revision\" must be a non-negative integer",
    );
  }
}

export function validateStateSnapshotV1(snapshot) {
  validateOrderingFields(snapshot);

  const phase = requireField(snapshot, "phase");
  if (typeof phase !== "string" || !PHASE_VALUES.has(phase)) {
    throw new ContractValidationError(
      `field \"phase\" must be one of: ${Array.from(PHASE_VALUES).join(", ")}`,
    );
  }
  for (const field of STRING_STATE_FIELDS) {
    if (typeof requireField(snapshot, field) !== "string") {
      throw new ContractValidationError(`field ${JSON.stringify(field)} must be a string`);
    }
  }
  for (const field of BOOLEAN_STATE_FIELDS) {
    if (typeof requireField(snapshot, field) !== "boolean") {
      throw new ContractValidationError(`field ${JSON.stringify(field)} must be a boolean`);
    }
  }
  for (const field of NUMBER_STATE_FIELDS) {
    const value = requireField(snapshot, field);
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new ContractValidationError(`field ${JSON.stringify(field)} must be a finite number`);
    }
  }
  return snapshot;
}

export function classifySnapshotOrder(current, incoming) {
  validateOrderingFields(current);
  validateOrderingFields(incoming);
  if (incoming.revision < current.revision) {
    throw new StaleRevisionError(
      `incoming revision ${incoming.revision} is older than current revision ${current.revision}`,
    );
  }
  if (incoming.revision === current.revision) {
    if (incoming.operationId !== current.operationId) {
      throw new RevisionConflictError(
        "equal revisions must carry the same operationId "
          + `(${JSON.stringify(current.operationId)} != ${JSON.stringify(incoming.operationId)})`,
      );
    }
    return SnapshotOrder.IDEMPOTENT;
  }
  return SnapshotOrder.NEWER;
}

export function createStateMachine({
  initialPhase = Phase.WARMING,
  renderer = () => {},
} = {}) {
  let currentPhase = initialPhase;
  let currentV1Snapshot = null;

  function applyState(state) {
    const versioned = Object.prototype.hasOwnProperty.call(state, "schemaVersion");
    let order = null;

    if (versioned) {
      validateStateSnapshotV1(state);
      if (currentV1Snapshot) {
        try {
          order = classifySnapshotOrder(currentV1Snapshot, state);
        } catch (error) {
          if (error instanceof StaleRevisionError || error instanceof RevisionConflictError) {
            return { accepted: false, order: null, error };
          }
          throw error;
        }
      } else {
        order = SnapshotOrder.NEWER;
      }
    }

    currentPhase = state.phase;
    if (versioned) {
      currentV1Snapshot = {
        schemaVersion: state.schemaVersion,
        operationId: state.operationId,
        revision: state.revision,
      };
    }
    renderer(state);
    return { accepted: true, order, error: null };
  }

  return {
    applyState,
    getCurrentPhase: () => currentPhase,
  };
}
