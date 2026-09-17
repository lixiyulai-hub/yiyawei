"""Wire contracts for the web GUI state and confirm payloads."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


SCHEMA_VERSION = 1
PHASE_VALUES = frozenset({"warming", "ready", "recording", "processing", "done", "error"})

_COMMON_STATE_FIELDS = (
    "phase",
    "status",
    "target",
    "rawText",
    "finalText",
    "mode",
    "outputScript",
    "useFast",
    "intelligentOutput",
    "asrModel",
    "asrDevice",
    "llmModel",
    "asrMs",
    "llmMs",
    "recordId",
    "riskLevel",
    "elapsedSec",
    "level",
    "pasted",
    "lastError",
    "updatedAt",
)
_V1_STATE_FIELDS = ("schemaVersion", "operationId", "revision", *_COMMON_STATE_FIELDS)
_CONFIRM_FIELDS = (
    "schemaVersion",
    "operationId",
    "baseRevision",
    "scope",
    "rawText",
    "finalText",
    "baseRawText",
    "baseFinalText",
)


@dataclass
class WebGuiState:
    phase: str = "warming"
    status: str = "预热 ASR"
    target: str = "先点目标输入框，再回到这里开始录音。"
    raw_text: str = ""
    final_text: str = ""
    mode: str = "cursor_prompt"
    output_script: str = "simplified"
    use_fast: bool = True
    intelligent_output: bool = True
    asr_model: str = "-"
    asr_device: str = "-"
    llm_model: str = "-"
    asr_ms: str = "-"
    llm_ms: str = "-"
    record_id: str = "-"
    risk_level: str = "-"
    elapsed_sec: float = 0.0
    level: float = 0.0
    pasted: bool = False
    last_error: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status,
            "target": self.target,
            "rawText": self.raw_text,
            "finalText": self.final_text,
            "mode": self.mode,
            "outputScript": self.output_script,
            "useFast": self.use_fast,
            "intelligentOutput": self.intelligent_output,
            "asrModel": self.asr_model,
            "asrDevice": self.asr_device,
            "llmModel": self.llm_model,
            "asrMs": self.asr_ms,
            "llmMs": self.llm_ms,
            "recordId": self.record_id,
            "riskLevel": self.risk_level,
            "elapsedSec": round(self.elapsed_sec, 1),
            "level": round(self.level, 5),
            "pasted": self.pasted,
            "lastError": self.last_error,
            "updatedAt": self.updated_at,
        }


class ContractValidationError(ValueError):
    """Raised when a wire payload does not satisfy its declared contract."""


class LegacyPayloadNotAllowedError(ContractValidationError):
    """Raised when an unversioned payload is used without an explicit opt-in."""


class UnsupportedSchemaVersionError(ContractValidationError):
    """Raised when a payload declares a schema version this module cannot read."""


@dataclass(frozen=True, slots=True)
class _StateFields:
    phase: str
    status: str
    target: str
    raw_text: str
    final_text: str
    mode: str
    output_script: str
    use_fast: bool
    intelligent_output: bool
    asr_model: str
    asr_device: str
    llm_model: str
    asr_ms: str
    llm_ms: str
    record_id: str
    risk_level: str
    elapsed_sec: float
    level: float
    pasted: bool
    last_error: str
    updated_at: float


@dataclass(frozen=True, slots=True)
class StatePayloadV1(_StateFields):
    """Validated state payload carrying global ordering information."""

    schema_version: int
    operation_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class LegacyStatePayloadV0(_StateFields):
    """Validated shape emitted by the current unversioned controller."""

    @property
    def schema_version(self) -> int:
        return 0


@dataclass(frozen=True, slots=True)
class ConfirmPayloadV1:
    """Validated optimistic-confirm request."""

    schema_version: int
    operation_id: str
    base_revision: int
    scope: str
    raw_text: str
    final_text: str
    base_raw_text: str
    base_final_text: str


class ConfirmConflictReason(str, Enum):
    OPERATION_MISMATCH = "operation_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    RAW_TEXT_MISMATCH = "raw_text_mismatch"
    FINAL_TEXT_MISMATCH = "final_text_mismatch"


@dataclass(frozen=True, slots=True)
class ConfirmConflict:
    """A side-effect-free description of an optimistic-confirm conflict."""

    reasons: tuple[ConfirmConflictReason, ...]

    @property
    def message(self) -> str:
        return "confirm base conflicts with current operation: " + ", ".join(self.reasons)


def validate_state_payload(
    payload: Mapping[str, Any], *, allow_legacy: bool = False
) -> StatePayloadV1 | LegacyStatePayloadV0:
    """Validate a state payload, requiring explicit opt-in for legacy v0."""

    payload = _require_mapping(payload)
    if "schemaVersion" not in payload:
        if not allow_legacy:
            raise LegacyPayloadNotAllowedError(
                "unversioned state payload is legacy v0; pass allow_legacy=True to accept it"
            )
        _require_fields(payload, _COMMON_STATE_FIELDS)
        return LegacyStatePayloadV0(**_validate_common_state_fields(payload))

    schema_version = _require_int(payload, "schemaVersion", minimum=0)
    if schema_version != SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"unsupported schemaVersion {schema_version}; expected {SCHEMA_VERSION}"
        )

    _require_fields(payload, _V1_STATE_FIELDS)
    operation_id = _require_string(payload, "operationId", nonempty=True)
    revision = _require_int(payload, "revision", minimum=0)
    return StatePayloadV1(
        **_validate_common_state_fields(payload),
        schema_version=schema_version,
        operation_id=operation_id,
        revision=revision,
    )


def validate_confirm_payload(payload: Mapping[str, Any]) -> ConfirmPayloadV1:
    """Validate the complete v1 optimistic-confirm request contract."""

    payload = _require_mapping(payload)
    _require_fields(payload, ("schemaVersion",))
    schema_version = _require_int(payload, "schemaVersion", minimum=0)
    if schema_version != SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"unsupported schemaVersion {schema_version}; expected {SCHEMA_VERSION}"
        )
    _require_fields(payload, _CONFIRM_FIELDS)

    scope = _require_string(payload, "scope")
    if scope not in {"raw", "final"}:
        raise ContractValidationError("field 'scope' must be 'raw' or 'final'")

    return ConfirmPayloadV1(
        schema_version=schema_version,
        operation_id=_require_string(payload, "operationId", nonempty=True),
        base_revision=_require_int(payload, "baseRevision", minimum=0),
        scope=scope,
        raw_text=_require_string(payload, "rawText"),
        final_text=_require_string(payload, "finalText"),
        base_raw_text=_require_string(payload, "baseRawText"),
        base_final_text=_require_string(payload, "baseFinalText"),
    )


def find_confirm_conflict(
    confirm: ConfirmPayloadV1, current: StatePayloadV1
) -> ConfirmConflict | None:
    """Compare a confirm base to current state without performing any side effects."""

    reasons: list[ConfirmConflictReason] = []
    if confirm.operation_id != current.operation_id:
        reasons.append(ConfirmConflictReason.OPERATION_MISMATCH)
    if confirm.base_revision != current.revision:
        reasons.append(ConfirmConflictReason.REVISION_MISMATCH)
    if confirm.base_raw_text != current.raw_text:
        reasons.append(ConfirmConflictReason.RAW_TEXT_MISMATCH)
    if confirm.base_final_text != current.final_text:
        reasons.append(ConfirmConflictReason.FINAL_TEXT_MISMATCH)
    if not reasons:
        return None
    return ConfirmConflict(tuple(reasons))


def _validate_common_state_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    phase = _require_string(payload, "phase")
    if phase not in PHASE_VALUES:
        allowed = ", ".join(sorted(PHASE_VALUES))
        raise ContractValidationError(f"field 'phase' must be one of: {allowed}")

    return {
        "phase": phase,
        "status": _require_string(payload, "status"),
        "target": _require_string(payload, "target"),
        "raw_text": _require_string(payload, "rawText"),
        "final_text": _require_string(payload, "finalText"),
        "mode": _require_string(payload, "mode"),
        "output_script": _require_string(payload, "outputScript"),
        "use_fast": _require_bool(payload, "useFast"),
        "intelligent_output": _require_bool(payload, "intelligentOutput"),
        "asr_model": _require_string(payload, "asrModel"),
        "asr_device": _require_string(payload, "asrDevice"),
        "llm_model": _require_string(payload, "llmModel"),
        "asr_ms": _require_string(payload, "asrMs"),
        "llm_ms": _require_string(payload, "llmMs"),
        "record_id": _require_string(payload, "recordId"),
        "risk_level": _require_string(payload, "riskLevel"),
        "elapsed_sec": _require_number(payload, "elapsedSec"),
        "level": _require_number(payload, "level"),
        "pasted": _require_bool(payload, "pasted"),
        "last_error": _require_string(payload, "lastError"),
        "updated_at": _require_number(payload, "updatedAt"),
    }


def _require_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ContractValidationError("payload must be a mapping")
    return payload


def _require_fields(payload: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ContractValidationError("missing required field(s): " + ", ".join(missing))


def _require_string(
    payload: Mapping[str, Any], field: str, *, nonempty: bool = False
) -> str:
    value = payload[field]
    if not isinstance(value, str):
        raise ContractValidationError(f"field '{field}' must be a string")
    if nonempty and not value.strip():
        raise ContractValidationError(f"field '{field}' must be a non-empty string")
    return value


def _require_bool(payload: Mapping[str, Any], field: str) -> bool:
    value = payload[field]
    if not isinstance(value, bool):
        raise ContractValidationError(f"field '{field}' must be a boolean")
    return value


def _require_int(payload: Mapping[str, Any], field: str, *, minimum: int) -> int:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"field '{field}' must be an integer")
    if value < minimum:
        raise ContractValidationError(f"field '{field}' must be >= {minimum}")
    return value


def _require_number(payload: Mapping[str, Any], field: str) -> float:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"field '{field}' must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ContractValidationError(f"field '{field}' must be finite")
    return number
