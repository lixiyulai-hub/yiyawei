"""Versioned contracts and pure state helpers for the web GUI."""

from .contracts import (
    ConfirmConflict,
    ConfirmConflictReason,
    ConfirmPayloadV1,
    ContractValidationError,
    LegacyPayloadNotAllowedError,
    LegacyStatePayloadV0,
    StatePayloadV1,
    UnsupportedSchemaVersionError,
    WebGuiState,
    find_confirm_conflict,
    validate_confirm_payload,
    validate_state_payload,
)
from .edit_service import EditService
from .recording_service import RecordingService
from .server import WebGuiServer, find_free_port
from .state_machine import (
    EditableSnapshot,
    Event,
    InvalidTransitionError,
    Phase,
    RevisionConflictError,
    SnapshotOrder,
    StaleRevisionError,
    classify_snapshot_order,
    edit_snapshot_text,
    merge_polled_snapshot,
    restore_snapshot_text,
    snapshot_from_payload,
    transition,
)
from .window_target_service import WindowTargetService, find_chromium_path

__all__ = [
    "ConfirmConflict",
    "ConfirmConflictReason",
    "ConfirmPayloadV1",
    "ContractValidationError",
    "EditService",
    "EditableSnapshot",
    "Event",
    "InvalidTransitionError",
    "LegacyPayloadNotAllowedError",
    "LegacyStatePayloadV0",
    "Phase",
    "RevisionConflictError",
    "RecordingService",
    "SnapshotOrder",
    "StaleRevisionError",
    "StatePayloadV1",
    "UnsupportedSchemaVersionError",
    "WebGuiState",
    "WebGuiServer",
    "WindowTargetService",
    "classify_snapshot_order",
    "edit_snapshot_text",
    "find_confirm_conflict",
    "find_free_port",
    "find_chromium_path",
    "merge_polled_snapshot",
    "restore_snapshot_text",
    "snapshot_from_payload",
    "transition",
    "validate_confirm_payload",
    "validate_state_payload",
]
