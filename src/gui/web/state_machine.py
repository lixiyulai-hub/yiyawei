"""Pure state transition, ordering, and local-edit merge rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .contracts import StatePayloadV1, UnsupportedSchemaVersionError


class Phase(str, Enum):
    WARMING = "warming"
    READY = "ready"
    RECORDING = "recording"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class Event(str, Enum):
    WARMUP_SUCCEEDED = "WARMUP_SUCCEEDED"
    WARMUP_FAILED = "WARMUP_FAILED"
    START_REQUESTED = "START_REQUESTED"
    STOP_REQUESTED = "STOP_REQUESTED"
    RECORDING_FAILED = "RECORDING_FAILED"
    PROCESS_SUCCEEDED = "PROCESS_SUCCEEDED"
    PROCESS_FAILED = "PROCESS_FAILED"
    RETRY_REQUESTED = "RETRY_REQUESTED"
    STATE_REFRESHED = "STATE_REFRESHED"
    SETTINGS_UPDATED = "SETTINGS_UPDATED"
    EDIT_STARTED = "EDIT_STARTED"
    EDIT_RESTORED = "EDIT_RESTORED"
    CONFIRM_SUCCEEDED = "CONFIRM_SUCCEEDED"
    CONFIRM_FAILED = "CONFIRM_FAILED"
    PASTE_SUCCEEDED = "PASTE_SUCCEEDED"
    PASTE_FAILED = "PASTE_FAILED"


class InvalidTransitionError(ValueError):
    """Raised when an event is not legal in the current phase."""


_PHASE_CHANGES = {
    (Phase.WARMING, Event.WARMUP_SUCCEEDED): Phase.READY,
    (Phase.WARMING, Event.WARMUP_FAILED): Phase.ERROR,
    (Phase.READY, Event.START_REQUESTED): Phase.RECORDING,
    (Phase.DONE, Event.START_REQUESTED): Phase.RECORDING,
    (Phase.ERROR, Event.START_REQUESTED): Phase.RECORDING,
    (Phase.RECORDING, Event.STOP_REQUESTED): Phase.PROCESSING,
    (Phase.RECORDING, Event.RECORDING_FAILED): Phase.ERROR,
    (Phase.PROCESSING, Event.PROCESS_SUCCEEDED): Phase.DONE,
    (Phase.PROCESSING, Event.PROCESS_FAILED): Phase.ERROR,
    (Phase.ERROR, Event.RETRY_REQUESTED): Phase.READY,
}
_GLOBAL_SAME_PHASE_EVENTS = {Event.STATE_REFRESHED, Event.SETTINGS_UPDATED}
_DONE_SAME_PHASE_EVENTS = {
    Event.EDIT_STARTED,
    Event.EDIT_RESTORED,
    Event.CONFIRM_SUCCEEDED,
    Event.CONFIRM_FAILED,
    Event.PASTE_SUCCEEDED,
    Event.PASTE_FAILED,
}


def transition(phase: Phase | str, event: Event | str) -> Phase:
    """Apply one explicitly allowed event to a phase."""

    current = _coerce_phase(phase)
    action = _coerce_event(event)
    changed = _PHASE_CHANGES.get((current, action))
    if changed is not None:
        return changed
    if action in _GLOBAL_SAME_PHASE_EVENTS:
        return current
    if current is Phase.DONE and action in _DONE_SAME_PHASE_EVENTS:
        return current
    raise InvalidTransitionError(
        f"event {action.value!r} is not legal while phase is {current.value!r}"
    )


class SnapshotOrder(str, Enum):
    NEWER = "newer"
    IDEMPOTENT = "idempotent"


class SnapshotOrderingError(ValueError):
    """Base class for rejected incoming snapshot ordering."""


class StaleRevisionError(SnapshotOrderingError):
    """Raised when an incoming global revision is older than the current one."""


class RevisionConflictError(SnapshotOrderingError):
    """Raised when one revision is claimed by different operations."""


def classify_snapshot_order(
    current: StatePayloadV1, incoming: StatePayloadV1
) -> SnapshotOrder:
    """Classify an incoming snapshot using revision as the only ordering clock."""

    _require_v1(current)
    _require_v1(incoming)
    if incoming.revision < current.revision:
        raise StaleRevisionError(
            f"incoming revision {incoming.revision} is older than current revision {current.revision}"
        )
    if incoming.revision == current.revision:
        if incoming.operation_id != current.operation_id:
            raise RevisionConflictError(
                "equal revisions must carry the same operationId "
                f"({current.operation_id!r} != {incoming.operation_id!r})"
            )
        return SnapshotOrder.IDEMPOTENT
    return SnapshotOrder.NEWER


@dataclass(frozen=True, slots=True)
class EditableSnapshot:
    """Client-visible state plus immutable bases for locally editable text."""

    payload: StatePayloadV1
    base_raw_text: str
    base_final_text: str
    raw_dirty: bool = False
    final_dirty: bool = False


def snapshot_from_payload(payload: StatePayloadV1) -> EditableSnapshot:
    """Start a clean editable snapshot from an accepted server payload."""

    _require_v1(payload)
    return EditableSnapshot(
        payload=payload,
        base_raw_text=payload.raw_text,
        base_final_text=payload.final_text,
    )


def edit_snapshot_text(
    snapshot: EditableSnapshot, scope: str, text: str
) -> EditableSnapshot:
    """Apply a local text edit and mark only that field dirty."""

    if not isinstance(text, str):
        raise TypeError("edited text must be a string")
    if scope == "raw":
        return replace(
            snapshot,
            payload=replace(snapshot.payload, raw_text=text),
            raw_dirty=True,
        )
    if scope == "final":
        return replace(
            snapshot,
            payload=replace(snapshot.payload, final_text=text),
            final_dirty=True,
        )
    raise ValueError("scope must be 'raw' or 'final'")


def restore_snapshot_text(snapshot: EditableSnapshot, scope: str) -> EditableSnapshot:
    """Restore one local field to its unmodified base and clear its dirty flag."""

    if scope == "raw":
        return replace(
            snapshot,
            payload=replace(snapshot.payload, raw_text=snapshot.base_raw_text),
            raw_dirty=False,
        )
    if scope == "final":
        return replace(
            snapshot,
            payload=replace(snapshot.payload, final_text=snapshot.base_final_text),
            final_dirty=False,
        )
    raise ValueError("scope must be 'raw' or 'final'")


def merge_polled_snapshot(
    current: EditableSnapshot, incoming: StatePayloadV1
) -> EditableSnapshot:
    """Accept an ordered poll while preserving dirty local text fields."""

    classify_snapshot_order(current.payload, incoming)
    if incoming.operation_id != current.payload.operation_id:
        return snapshot_from_payload(incoming)

    raw_text = current.payload.raw_text if current.raw_dirty else incoming.raw_text
    final_text = current.payload.final_text if current.final_dirty else incoming.final_text
    merged_payload = replace(incoming, raw_text=raw_text, final_text=final_text)
    return EditableSnapshot(
        payload=merged_payload,
        base_raw_text=current.base_raw_text if current.raw_dirty else incoming.raw_text,
        base_final_text=current.base_final_text if current.final_dirty else incoming.final_text,
        raw_dirty=current.raw_dirty,
        final_dirty=current.final_dirty,
    )


def _require_v1(payload: StatePayloadV1) -> None:
    if payload.schema_version != 1:
        raise UnsupportedSchemaVersionError(
            f"unsupported schemaVersion {payload.schema_version}; expected 1"
        )


def _coerce_phase(phase: Phase | str) -> Phase:
    try:
        return Phase(phase)
    except (TypeError, ValueError) as exc:
        raise InvalidTransitionError(f"unknown phase {phase!r}") from exc


def _coerce_event(event: Event | str) -> Event:
    try:
        return Event(event)
    except (TypeError, ValueError) as exc:
        raise InvalidTransitionError(f"unknown event {event!r}") from exc
