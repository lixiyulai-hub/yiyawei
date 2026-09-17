from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.gui import web_gui as web_gui_module
from src.gui.web import EditService
from src.gui.web import edit_service as edit_service_module
from src.gui.web_gui import WebGuiController


class FakeApp:
    default_mode = "cursor_prompt"
    output_cfg = {"script": "simplified"}
    injector_cfg = {"restore_clipboard": False, "paste_delay_ms": 23}

    def __init__(self) -> None:
        self.confirm_calls: list[dict[str, Any]] = []
        self.confirm_events: list[str] | None = None
        self.lock: TrackingLock | None = None

    def confirm_edit(self, **kwargs: Any) -> dict[str, Any]:
        if self.lock is not None:
            assert self.lock.held is False
        if self.confirm_events is not None:
            self.confirm_events.append(f"confirm:{kwargs['source_kind']}")
        self.confirm_calls.append(kwargs)
        source_kind = kwargs["source_kind"]
        return {"learned_rules": [{"source": source_kind}]}


class TrackingLock:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.held = False

    def __enter__(self) -> TrackingLock:
        assert self.held is False
        self.held = True
        self.events.append("lock:enter")
        return self

    def __exit__(self, *args: object) -> None:
        self.events.append("lock:exit")
        self.held = False


def _done_controller() -> tuple[WebGuiController, FakeApp]:
    app = FakeApp()
    controller = WebGuiController(app)
    controller.state.phase = "done"
    controller.state.raw_text = "raw before"
    controller.state.final_text = "final before"
    controller.state.record_id = "41"
    controller.state.mode = "cursor_prompt"
    controller.state.output_script = "traditional"
    controller._target_hwnd = 12
    controller._confirm_target_hwnd = 34
    controller._last_debug = {"route": {"task_type": "edit"}}
    return controller, app


def test_edit_service_is_exported_owned_and_controller_facade_is_dynamic(monkeypatch):
    controller, _ = _done_controller()
    assert isinstance(controller._edit_service, EditService)
    assert EditService is edit_service_module.EditService
    source = Path(edit_service_module.__file__).read_text(encoding="utf-8")
    assert "from src.gui.web_gui" not in source

    calls: list[tuple[dict[str, Any], object, object, object]] = []

    def delegate(payload, *, paste_text, parse_record_id, now):
        calls.append((payload, paste_text, parse_record_id, now))
        return {"ok": "delegated"}

    monkeypatch.setattr(controller._edit_service, "confirm_text", delegate)

    paste_one = lambda *args, **kwargs: True
    parse_one = lambda value: 1
    now_one = lambda: 1.0
    monkeypatch.setattr(web_gui_module, "paste_text", paste_one)
    monkeypatch.setattr(web_gui_module, "_parse_record_id", parse_one)
    monkeypatch.setattr(web_gui_module.time, "time", now_one)
    assert controller.confirm_text({"call": 1}) == {"ok": "delegated"}

    paste_two = lambda *args, **kwargs: False
    parse_two = lambda value: 2
    now_two = lambda: 2.0
    monkeypatch.setattr(web_gui_module, "paste_text", paste_two)
    monkeypatch.setattr(web_gui_module, "_parse_record_id", parse_two)
    monkeypatch.setattr(web_gui_module.time, "time", now_two)
    assert controller.confirm_text({"call": 2}) == {"ok": "delegated"}

    assert calls == [
        ({"call": 1}, paste_one, parse_one, now_one),
        ({"call": 2}, paste_two, parse_two, now_two),
    ]


@pytest.mark.parametrize("busy_attribute", ["_recording", "_processing"])
def test_edit_service_rejects_busy_with_legacy_response(busy_attribute):
    controller, _ = _done_controller()
    setattr(controller, busy_attribute, True)

    result = controller.confirm_text({"finalText": "changed"})

    assert result == {
        "ok": False,
        "error": "当前正在录音或处理中，暂不能确认。",
        "state": controller.state.to_dict(),
    }


def test_edit_service_rejects_when_phase_is_not_done():
    controller, _ = _done_controller()
    controller.state.phase = "ready"

    result = controller.confirm_text({"finalText": "changed"})

    assert result == {
        "ok": False,
        "error": "没有可确认的输出。",
        "state": controller.state.to_dict(),
    }


def test_edit_service_invalid_scope_falls_back_to_final_and_empty_base_skips_conflict(
    monkeypatch,
):
    controller, app = _done_controller()
    paste_calls = []

    def paste(text, **kwargs):
        paste_calls.append((text, kwargs))
        return False

    monkeypatch.setattr(web_gui_module, "paste_text", paste)
    result = controller.confirm_text(
        {
            "scope": " invalid ",
            "recordId": "999",
            "rawText": "",
            "finalText": "  final changed  ",
            "baseFinalText": "",
        }
    )

    assert result["ok"] is True
    assert result["scope"] == "final"
    assert result["pasted"] is False
    assert controller.state.raw_text == "raw before"
    assert controller.state.final_text == "final changed"
    assert controller.state.status == "已确认，粘贴失败"
    assert app.confirm_calls[0]["record_id"] == 41
    assert [call[0] for call in paste_calls] == ["final changed"]


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (
            {"scope": "raw", "rawText": "changed", "baseRawText": "stale"},
            "识别原文已变化，请先恢复或重新确认。",
        ),
        (
            {"scope": "final", "finalText": "changed", "baseFinalText": "stale"},
            "输出已变化，请先恢复或重新确认。",
        ),
        (
            {"scope": "raw", "rawText": "  ", "baseRawText": "raw before"},
            "识别原文不能为空。",
        ),
        (
            {"scope": "final", "finalText": "  ", "baseFinalText": "final before"},
            "最终输出不能为空。",
        ),
    ],
)
def test_edit_service_rejects_stale_and_empty_edits(monkeypatch, payload, error):
    controller, app = _done_controller()

    def unexpected_paste(*args, **kwargs):
        raise AssertionError("paste must not run for rejected edits")

    monkeypatch.setattr(web_gui_module, "paste_text", unexpected_paste)
    result = controller.confirm_text(payload)

    assert result == {"ok": False, "error": error, "state": controller.state.to_dict()}
    assert app.confirm_calls == []


def test_edit_service_raw_only_learns_without_paste(monkeypatch):
    controller, app = _done_controller()

    def unexpected_paste(*args, **kwargs):
        raise AssertionError("raw confirmation must not paste")

    monkeypatch.setattr(web_gui_module, "paste_text", unexpected_paste)
    result = controller.confirm_text(
        {
            "scope": "raw",
            "rawText": "  raw changed  ",
            "finalText": "ignored final",
            "baseRawText": "raw before",
        }
    )

    assert result["scope"] == "raw"
    assert result["pasted"] is False
    assert result["learnedRules"] == [{"source": "asr_text"}]
    assert controller.state.raw_text == "raw changed"
    assert controller.state.final_text == "final before"
    assert controller.state.status == "已保存识别修正"
    assert [call["source_kind"] for call in app.confirm_calls] == ["asr_text"]


def test_edit_service_final_preserves_order_metadata_paste_restore_and_response(monkeypatch):
    controller, app = _done_controller()
    events: list[str] = []
    lock = TrackingLock(events)
    controller._lock = lock
    app.lock = lock
    app.confirm_events = events
    parse_values = []
    paste_calls = []

    def parse_record_id(value):
        assert lock.held is True
        events.append("parse")
        parse_values.append(value)
        return 314

    def paste(text, **kwargs):
        assert lock.held is False
        events.append("paste")
        paste_calls.append((text, kwargs))
        return True

    def restore():
        assert lock.held is False
        events.append("restore")

    def now():
        assert lock.held is True
        events.append("now")
        return 1234.5

    monkeypatch.setattr(web_gui_module, "_parse_record_id", parse_record_id)
    monkeypatch.setattr(web_gui_module, "paste_text", paste)
    monkeypatch.setattr(web_gui_module.time, "time", now)
    monkeypatch.setattr(controller, "_restore_browser_window_position", restore)

    result = controller.confirm_text(
        {
            "scope": "final",
            "recordId": "request-id-is-ignored",
            "rawText": "  raw changed  ",
            "finalText": "  final changed  ",
            "baseFinalText": "final before",
        }
    )

    assert events == [
        "lock:enter",
        "parse",
        "lock:exit",
        "confirm:asr_text",
        "confirm:final_output",
        "paste",
        "restore",
        "lock:enter",
        "now",
        "lock:exit",
    ]
    assert parse_values == ["41"]
    assert [call["source_kind"] for call in app.confirm_calls] == [
        "asr_text",
        "final_output",
    ]
    assert all(call["record_id"] == 314 for call in app.confirm_calls)
    assert all(call["mode"] == "cursor_prompt" for call in app.confirm_calls)
    assert all(call["output_script"] == "traditional" for call in app.confirm_calls)
    assert all(
        call["metadata"]
        == {"source": "web_gui", "debug": {"route": {"task_type": "edit"}}}
        for call in app.confirm_calls
    )
    assert paste_calls == [
        (
            "final changed",
            {"restore_clipboard": False, "delay_ms": 23, "target_hwnd": 34},
        )
    ]
    assert controller.state.updated_at == 1234.5
    assert result == {
        "ok": True,
        "state": controller.state.to_dict(),
        "pasted": True,
        "scope": "final",
        "learnedRules": [
            {"source": "asr_text"},
            {"source": "final_output"},
        ],
    }
