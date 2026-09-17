from __future__ import annotations

from dataclasses import replace

import pytest

from src.gui.web.contracts import (
    ConfirmConflictReason,
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
from src.gui.web import WebGuiState as PackageWebGuiState
from src.gui.web.state_machine import (
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
from src.gui.web_gui import WebGuiController, WebGuiState as FacadeWebGuiState


def _state_payload(**overrides):
    payload = {
        "schemaVersion": 1,
        "operationId": "operation-1",
        "revision": 1,
        "phase": "done",
        "status": "ready to confirm",
        "target": "editor",
        "rawText": "dictated text",
        "finalText": "compiled text",
        "mode": "cursor_prompt",
        "outputScript": "simplified",
        "useFast": True,
        "intelligentOutput": True,
        "asrModel": "fake-asr",
        "asrDevice": "cpu",
        "llmModel": "fake-llm",
        "asrMs": "11",
        "llmMs": "12",
        "recordId": "42",
        "riskLevel": "low",
        "elapsedSec": 1.2,
        "level": 0.25,
        "pasted": False,
        "lastError": "",
        "updatedAt": 100.0,
    }
    payload.update(overrides)
    return payload


def _state(**overrides) -> StatePayloadV1:
    result = validate_state_payload(_state_payload(**overrides))
    assert isinstance(result, StatePayloadV1)
    return result


def _confirm_payload(**overrides):
    payload = {
        "schemaVersion": 1,
        "operationId": "operation-1",
        "baseRevision": 1,
        "scope": "final",
        "rawText": "dictated text",
        "finalText": "locally edited output",
        "baseRawText": "dictated text",
        "baseFinalText": "compiled text",
    }
    payload.update(overrides)
    return payload


def _walk(start: Phase, events: list[Event]) -> list[Phase]:
    phases = [start]
    for event in events:
        phases.append(transition(phases[-1], event))
    return phases


def test_v1_state_payload_validates_all_required_fields():
    state = validate_state_payload(_state_payload())

    assert isinstance(state, StatePayloadV1)
    assert state.schema_version == 1
    assert state.operation_id == "operation-1"
    assert state.revision == 1
    assert state.final_text == "compiled text"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operationId", ""),
        ("revision", True),
        ("revision", -1),
        ("phase", "unknown"),
        ("useFast", "yes"),
        ("intelligentOutput", "yes"),
        ("elapsedSec", "1.2"),
        ("pasted", 0),
        ("updatedAt", float("inf")),
    ],
)
def test_v1_state_payload_rejects_invalid_types_and_values(field, value):
    with pytest.raises(ContractValidationError, match=field):
        validate_state_payload(_state_payload(**{field: value}))


def test_v1_state_payload_rejects_missing_field():
    payload = _state_payload()
    del payload["target"]

    with pytest.raises(ContractValidationError, match="target"):
        validate_state_payload(payload)


def test_state_payload_rejects_unsupported_schema_even_with_legacy_opt_in():
    with pytest.raises(UnsupportedSchemaVersionError, match="schemaVersion 2"):
        validate_state_payload(_state_payload(schemaVersion=2), allow_legacy=True)


def test_web_gui_state_facades_export_the_contract_type():
    assert FacadeWebGuiState is WebGuiState
    assert PackageWebGuiState is WebGuiState


def test_web_gui_state_default_payload_preserves_legacy_shape_and_types():
    payload = WebGuiState().to_dict()

    assert list(payload) == [
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
    ]
    assert payload["phase"] == "warming"
    assert payload["status"] == "预热 ASR"
    assert payload["target"] == "先点目标输入框，再回到这里开始录音。"
    assert isinstance(payload["useFast"], bool)
    assert isinstance(payload["intelligentOutput"], bool)
    assert isinstance(payload["elapsedSec"], float)
    assert isinstance(payload["level"], float)
    assert isinstance(payload["pasted"], bool)
    assert isinstance(payload["updatedAt"], float)
    assert "schemaVersion" not in payload


def test_web_gui_state_custom_payload_preserves_values_and_rounding():
    payload = WebGuiState(
        phase="done",
        status="complete",
        target="editor",
        raw_text="raw",
        final_text="final",
        mode="direct_text",
        output_script="traditional",
        use_fast=False,
        intelligent_output=False,
        asr_model="asr",
        asr_device="cpu",
        llm_model="llm",
        asr_ms="11",
        llm_ms="12",
        record_id="42",
        risk_level="low",
        elapsed_sec=1.26,
        level=0.1234567,
        pasted=True,
        last_error="none",
        updated_at=123.5,
    ).to_dict()

    assert payload == {
        "phase": "done",
        "status": "complete",
        "target": "editor",
        "rawText": "raw",
        "finalText": "final",
        "mode": "direct_text",
        "outputScript": "traditional",
        "useFast": False,
        "intelligentOutput": False,
        "asrModel": "asr",
        "asrDevice": "cpu",
        "llmModel": "llm",
        "asrMs": "11",
        "llmMs": "12",
        "recordId": "42",
        "riskLevel": "low",
        "elapsedSec": 1.3,
        "level": 0.12346,
        "pasted": True,
        "lastError": "none",
        "updatedAt": 123.5,
    }
    assert "schemaVersion" not in payload


class _MinimalFakeApp:
    default_mode = "cursor_prompt"
    output_cfg = {"script": "simplified"}


def test_current_web_gui_controller_payload_is_valid_legacy_only_with_opt_in():
    legacy_payload = WebGuiController(_MinimalFakeApp()).get_state()

    with pytest.raises(LegacyPayloadNotAllowedError, match="allow_legacy=True"):
        validate_state_payload(legacy_payload)

    state = validate_state_payload(legacy_payload, allow_legacy=True)
    assert isinstance(state, LegacyStatePayloadV0)
    assert state.schema_version == 0
    assert state.phase == "warming"


def test_legacy_payload_still_validates_existing_fields_and_types():
    legacy_payload = WebGuiController(_MinimalFakeApp()).get_state()
    legacy_payload["level"] = "quiet"

    with pytest.raises(ContractValidationError, match="level"):
        validate_state_payload(legacy_payload, allow_legacy=True)


def test_startup_flow_state_sequences():
    assert _walk(Phase.WARMING, [Event.WARMUP_SUCCEEDED]) == [
        Phase.WARMING,
        Phase.READY,
    ]
    assert _walk(Phase.WARMING, [Event.WARMUP_FAILED]) == [
        Phase.WARMING,
        Phase.ERROR,
    ]
    assert _walk(Phase.ERROR, [Event.RETRY_REQUESTED]) == [
        Phase.ERROR,
        Phase.READY,
    ]


def test_manual_recording_and_processing_flow_state_sequence():
    phases = _walk(
        Phase.READY,
        [Event.START_REQUESTED, Event.STOP_REQUESTED, Event.PROCESS_SUCCEEDED],
    )

    assert phases == [
        Phase.READY,
        Phase.RECORDING,
        Phase.PROCESSING,
        Phase.DONE,
    ]


@pytest.mark.parametrize(
    ("start", "event", "expected"),
    [
        (Phase.WARMING, Event.WARMUP_SUCCEEDED, Phase.READY),
        (Phase.WARMING, Event.WARMUP_FAILED, Phase.ERROR),
        (Phase.READY, Event.START_REQUESTED, Phase.RECORDING),
        (Phase.DONE, Event.START_REQUESTED, Phase.RECORDING),
        (Phase.ERROR, Event.START_REQUESTED, Phase.RECORDING),
        (Phase.RECORDING, Event.STOP_REQUESTED, Phase.PROCESSING),
        (Phase.RECORDING, Event.RECORDING_FAILED, Phase.ERROR),
        (Phase.PROCESSING, Event.PROCESS_SUCCEEDED, Phase.DONE),
        (Phase.PROCESSING, Event.PROCESS_FAILED, Phase.ERROR),
        (Phase.ERROR, Event.RETRY_REQUESTED, Phase.READY),
    ],
)
def test_all_legal_phase_changing_transitions(start, event, expected):
    assert transition(start, event) is expected


def test_auto_stop_flow_is_exactly_once_at_state_path_boundary():
    phases = _walk(
        Phase.READY,
        [Event.START_REQUESTED, Event.STOP_REQUESTED, Event.PROCESS_SUCCEEDED],
    )

    assert phases == [
        Phase.READY,
        Phase.RECORDING,
        Phase.PROCESSING,
        Phase.DONE,
    ]
    with pytest.raises(InvalidTransitionError, match="STOP_REQUESTED"):
        transition(Phase.PROCESSING, Event.STOP_REQUESTED)


@pytest.mark.parametrize(
    "phase",
    list(Phase),
)
@pytest.mark.parametrize(
    "event",
    [Event.STATE_REFRESHED, Event.SETTINGS_UPDATED],
)
def test_refresh_and_settings_are_explicit_same_phase_events(phase, event):
    assert transition(phase, event) is phase


@pytest.mark.parametrize(
    "event",
    [
        Event.EDIT_STARTED,
        Event.EDIT_RESTORED,
        Event.CONFIRM_SUCCEEDED,
        Event.CONFIRM_FAILED,
        Event.PASTE_SUCCEEDED,
        Event.PASTE_FAILED,
    ],
)
def test_done_edit_confirm_and_paste_events_are_same_phase(event):
    assert transition(Phase.DONE, event) is Phase.DONE


def test_state_machine_rejects_unlisted_transitions_and_unknown_events():
    with pytest.raises(InvalidTransitionError, match="PROCESS_SUCCEEDED"):
        transition(Phase.READY, Event.PROCESS_SUCCEEDED)
    with pytest.raises(InvalidTransitionError, match="EDIT_STARTED"):
        transition(Phase.READY, Event.EDIT_STARTED)
    with pytest.raises(InvalidTransitionError, match="unknown event"):
        transition(Phase.READY, "POLL_CHANGED_PHASE")


def test_revision_is_the_only_snapshot_ordering_clock():
    current = _state(revision=5, updatedAt=500.0)
    newer = _state(revision=6, updatedAt=1.0)
    idempotent = _state(revision=5, updatedAt=999.0)

    assert classify_snapshot_order(current, newer) is SnapshotOrder.NEWER
    assert classify_snapshot_order(current, idempotent) is SnapshotOrder.IDEMPOTENT

    with pytest.raises(StaleRevisionError, match="older"):
        classify_snapshot_order(current, _state(revision=4, updatedAt=1000.0))
    with pytest.raises(RevisionConflictError, match="same operationId"):
        classify_snapshot_order(current, _state(revision=5, operationId="operation-2"))


def test_snapshot_order_rejects_unsupported_schema():
    unsupported = replace(_state(), schema_version=9)

    with pytest.raises(UnsupportedSchemaVersionError, match="schemaVersion 9"):
        classify_snapshot_order(_state(), unsupported)


def test_dirty_edit_poll_protection_flow_preserves_text_and_accepts_non_text():
    client = snapshot_from_payload(_state())
    client = edit_snapshot_text(client, "raw", "local raw edit")
    client = edit_snapshot_text(client, "final", "local final edit")
    assert transition(Phase.DONE, Event.EDIT_STARTED) is Phase.DONE

    incoming = _state(
        revision=2,
        status="new server status",
        rawText="server raw revision 2",
        finalText="server final revision 2",
        asrMs="21",
        elapsedSec=2.5,
        updatedAt=50.0,
    )
    merged = merge_polled_snapshot(client, incoming)

    assert transition(Phase.DONE, Event.STATE_REFRESHED) is Phase.DONE
    assert merged.payload.raw_text == "local raw edit"
    assert merged.payload.final_text == "local final edit"
    assert merged.payload.status == "new server status"
    assert merged.payload.asr_ms == "21"
    assert merged.payload.elapsed_sec == 2.5
    assert merged.base_raw_text == "dictated text"
    assert merged.base_final_text == "compiled text"
    assert merged.raw_dirty is True
    assert merged.final_dirty is True


def test_new_operation_resets_dirty_fields_and_text_bases():
    client = edit_snapshot_text(snapshot_from_payload(_state()), "final", "local edit")
    incoming = _state(
        revision=2,
        operationId="operation-2",
        rawText="next raw",
        finalText="next final",
    )

    merged = merge_polled_snapshot(client, incoming)

    assert merged.payload.operation_id == "operation-2"
    assert merged.payload.raw_text == "next raw"
    assert merged.payload.final_text == "next final"
    assert merged.base_raw_text == "next raw"
    assert merged.base_final_text == "next final"
    assert merged.raw_dirty is False
    assert merged.final_dirty is False


def test_confirm_v1_contract_requires_complete_typed_payload():
    request = validate_confirm_payload(_confirm_payload())
    assert request.scope == "final"

    missing = _confirm_payload()
    del missing["baseRawText"]
    with pytest.raises(ContractValidationError, match="baseRawText"):
        validate_confirm_payload(missing)
    with pytest.raises(ContractValidationError, match="baseRevision"):
        validate_confirm_payload(_confirm_payload(baseRevision="1"))
    with pytest.raises(ContractValidationError, match="scope"):
        validate_confirm_payload(_confirm_payload(scope="both"))
    with pytest.raises(UnsupportedSchemaVersionError, match="schemaVersion 3"):
        validate_confirm_payload(_confirm_payload(schemaVersion=3))
    with pytest.raises(UnsupportedSchemaVersionError, match="schemaVersion 3"):
        validate_confirm_payload({"schemaVersion": 3})


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"operationId": "operation-2"}, ConfirmConflictReason.OPERATION_MISMATCH),
        ({"baseRevision": 0}, ConfirmConflictReason.REVISION_MISMATCH),
        ({"baseRawText": "stale raw"}, ConfirmConflictReason.RAW_TEXT_MISMATCH),
        ({"baseFinalText": "stale final"}, ConfirmConflictReason.FINAL_TEXT_MISMATCH),
    ],
)
def test_confirm_operation_revision_and_base_mismatches_are_conflicts(override, reason):
    current = _state()
    request = validate_confirm_payload(_confirm_payload(**override))

    conflict = find_confirm_conflict(request, current)

    assert conflict is not None
    assert reason in conflict.reasons
    assert current == _state()


def test_restore_confirm_and_stale_base_flow_state_sequence():
    server = _state()
    client = snapshot_from_payload(server)
    phases = [Phase.DONE]

    client = edit_snapshot_text(client, "final", "draft output")
    phases.append(transition(phases[-1], Event.EDIT_STARTED))
    client = restore_snapshot_text(client, "final")
    phases.append(transition(phases[-1], Event.EDIT_RESTORED))
    assert client.payload.final_text == "compiled text"
    assert client.final_dirty is False

    client = edit_snapshot_text(client, "final", "confirmed output")
    phases.append(transition(phases[-1], Event.EDIT_STARTED))
    request = validate_confirm_payload(
        _confirm_payload(finalText=client.payload.final_text)
    )
    assert find_confirm_conflict(request, server) is None
    phases.append(transition(phases[-1], Event.CONFIRM_SUCCEEDED))

    changed_server = replace(server, revision=2, final_text="server changed output")
    conflict = find_confirm_conflict(request, changed_server)
    assert conflict is not None
    assert ConfirmConflictReason.REVISION_MISMATCH in conflict.reasons
    assert ConfirmConflictReason.FINAL_TEXT_MISMATCH in conflict.reasons
    phases.append(transition(phases[-1], Event.CONFIRM_FAILED))

    assert phases == [Phase.DONE] * 6
