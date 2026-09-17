from __future__ import annotations

from typing import Any

import pytest

from src.gui.web import RecordingService
from src.gui.web import recording_service as recording_service_module
from src.gui.web_gui import WebGuiController


class FakeLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def exception(self, *args: Any, **kwargs: Any) -> None:
        pass


class FakeRecorder:
    def __init__(self) -> None:
        self.audio: Any = b"audio"
        self.start_calls = 0
        self.stop_calls = 0
        self.elapsed = 0.0
        self.activity = (0.0, 0.0, False)
        self.thresholds: list[float] = []

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> Any:
        self.stop_calls += 1
        return self.audio

    def get_elapsed_sec(self) -> float:
        return self.elapsed

    def update_voice_activity(self, threshold: float) -> tuple[float, float, bool]:
        self.thresholds.append(threshold)
        return self.activity


class FakeApp:
    default_mode = "cursor_prompt"
    output_cfg = {"script": "simplified"}
    injector_cfg = {"restore_clipboard": True, "paste_delay_ms": 0}

    def __init__(self) -> None:
        self.config = {"recorder": {"auto_stop": {"enabled": False}}}
        self.logger = FakeLogger()
        self.recorder = FakeRecorder()
        self.process_error: Exception | None = None
        self.process_calls: list[tuple[Any, dict[str, Any]]] = []

    def process_audio(self, audio: Any, **kwargs: Any) -> dict[str, Any]:
        self.process_calls.append((audio, kwargs))
        if self.process_error is not None:
            raise self.process_error
        return {
            "record_id": 19,
            "pasted": True,
            "debug": {
                "raw_asr_text": "raw",
                "final_text": "final",
                "asr_model": "asr",
                "asr_device": "cpu",
                "llm_model": "llm",
                "asr_elapsed_ms": 12.4,
                "llm_elapsed_ms": 23.5,
                "risk_level": "low",
            },
        }


def test_controller_facades_preserve_service_flag_and_queue_aliases() -> None:
    controller = WebGuiController(FakeApp())

    assert isinstance(controller._recording_service, RecordingService)
    assert controller._recording_service.host is controller
    assert controller._events is controller._recording_service.events

    controller._recording = True
    controller._processing = True
    assert controller._recording_service.recording is True
    assert controller._recording_service.processing is True

    controller._recording_service.recording = False
    controller._recording_service.processing = False
    assert controller._recording is False
    assert controller._processing is False


def test_apply_events_calls_controller_stop_facade() -> None:
    controller = WebGuiController(FakeApp())
    calls: list[bool] = []

    def fake_stop_recording(auto: bool = False) -> dict[str, Any]:
        calls.append(auto)
        controller._stop_threads.set()
        return {"ok": True}

    controller.stop_recording = fake_stop_recording  # type: ignore[method-assign]
    controller._events.put(("auto_stop", {}))

    controller._apply_events()

    assert calls == [True]


def test_start_recording_uses_current_describe_window_and_is_idempotent(monkeypatch) -> None:
    app = FakeApp()
    controller = WebGuiController(app)
    controller._target_hwnd = 321
    described: list[int | None] = []
    normalized: list[tuple[Any, ...]] = []
    monitor_starts: list[bool] = []

    def fake_describe_window(hwnd: int | None) -> str:
        described.append(hwnd)
        return "Editor"

    def fake_normalize_mode(value: Any, default: str) -> str:
        normalized.append(("mode", value, default))
        return "plain_text"

    def fake_normalize_script(value: Any) -> str:
        normalized.append(("script", value))
        return "traditional"

    monkeypatch.setattr("src.gui.web_gui.describe_window", fake_describe_window)
    monkeypatch.setattr("src.gui.web_gui._normalize_mode", fake_normalize_mode)
    monkeypatch.setattr("src.gui.web_gui._normalize_script", fake_normalize_script)
    monkeypatch.setattr(
        controller,
        "_start_auto_stop_monitor",
        lambda: monitor_starts.append(True),
    )

    first = controller.start_recording(
        {
            "mode": "cursor_prompt",
            "outputScript": "traditional",
            "useFast": False,
            "intelligentOutput": False,
        }
    )
    second = controller.start_recording({"mode": "plain_text"})

    assert first["ok"] is True
    assert second["ok"] is True
    assert described == [321]
    assert normalized == [
        ("mode", "cursor_prompt", "cursor_prompt"),
        ("script", "traditional"),
    ]
    assert monitor_starts == [True]
    assert app.recorder.start_calls == 1
    assert controller.state.target == "目标：Editor"
    assert controller.state.mode == "plain_text"
    assert controller.state.output_script == "traditional"
    assert controller.state.use_fast is False
    assert controller.state.intelligent_output is False
    assert controller._recording is True


def test_recording_service_has_no_local_normalization_helpers() -> None:
    assert not hasattr(recording_service_module, "_normalize_mode")
    assert not hasattr(recording_service_module, "_normalize_script")


def test_stop_recording_reports_empty_audio_without_processing() -> None:
    app = FakeApp()
    app.recorder.audio = b""
    controller = WebGuiController(app)
    controller._recording = True

    result = controller.stop_recording()

    assert result["ok"] is False
    assert result["error"] == "没有录到声音，请确认麦克风已选中，并稍微靠近一点再试。"
    assert controller.state.phase == "error"
    assert controller.state.status == "未录到声音"
    assert controller.state.last_error == result["error"]
    assert controller._recording is False
    assert controller._processing is False


@pytest.mark.parametrize(
    ("auto", "expected_status"),
    [(False, "处理中"), (True, "自动停止，处理中")],
)
def test_manual_and_auto_stop_start_processing_with_legacy_arguments(
    monkeypatch, auto: bool, expected_status: str
) -> None:
    app = FakeApp()
    controller = WebGuiController(app)
    controller._recording = True
    controller._target_hwnd = 456
    controller.state.mode = "plain_text"
    controller.state.output_script = "traditional"
    controller.state.use_fast = False
    threads: list[Any] = []

    class FakeThread:
        def __init__(self, *, target: Any, args: tuple[Any, ...], daemon: bool) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            threads.append(self)

        def start(self) -> None:
            pass

    monkeypatch.setattr("src.gui.web.recording_service.threading.Thread", FakeThread)

    result = controller.stop_recording(auto=auto)

    assert result["ok"] is True
    assert len(threads) == 1
    assert threads[0].target == controller._process_audio
    assert threads[0].args == (b"audio", "plain_text", False, True, 456, "traditional")
    assert threads[0].daemon is True
    assert controller._confirm_target_hwnd == 456
    assert controller.state.status == expected_status
    assert controller._recording is False
    assert controller._processing is True


def test_process_audio_success_updates_state_restores_window_and_cleans_flag(monkeypatch) -> None:
    app = FakeApp()
    controller = WebGuiController(app)
    controller._processing = True
    restored: list[bool] = []
    monkeypatch.setattr(controller, "_restore_browser_window_position", lambda: restored.append(True))

    controller._process_audio(b"audio", "cursor_prompt", False, True, 789, "simplified")

    assert app.process_calls == [
        (
            b"audio",
            {
                "mode": "cursor_prompt",
                "use_fast": False,
                "intelligent_output": True,
                "paste_hwnd": 789,
                "output_script": "simplified",
                "allow_paste": True,
            },
        )
    ]
    assert restored == [True]
    assert controller.state.phase == "done"
    assert controller.state.status == "已粘贴"
    assert controller.state.raw_text == "raw"
    assert controller.state.final_text == "final"
    assert controller.state.record_id == "19"
    assert controller._last_debug["risk_level"] == "low"
    assert controller._processing is False


def test_process_audio_error_uses_controller_formatter_and_cleans_flag(monkeypatch) -> None:
    app = FakeApp()
    app.process_error = RuntimeError("localhost:11434 unavailable")
    controller = WebGuiController(app)
    controller._processing = True
    formatted: list[Exception] = []

    def fake_format_error(exc: Exception) -> str:
        formatted.append(exc)
        return "patched error"

    monkeypatch.setattr(controller, "_format_error", fake_format_error)

    controller._process_audio(b"audio", "cursor_prompt", True, True, None, "simplified")

    assert controller.state.phase == "error"
    assert controller.state.status == "处理失败"
    assert controller.state.final_text == "错误：patched error"
    assert controller.state.last_error == "patched error"
    assert len(formatted) == 1
    assert str(formatted[0]) == "localhost:11434 unavailable"
    assert controller._processing is False


def test_auto_stop_monitor_enqueues_exactly_one_event() -> None:
    app = FakeApp()
    app.recorder.elapsed = 2.0
    app.recorder.activity = (3.0, 0.001, True)
    controller = WebGuiController(app)
    controller._recording = True

    controller._auto_stop_monitor(
        {
            "min_duration_sec": 1.2,
            "silence_sec": 2.0,
            "level_threshold": 0.015,
            "poll_interval_sec": 0,
        }
    )

    assert controller._events.qsize() == 1
    assert controller._events.get_nowait() == ("auto_stop", {})
    assert app.recorder.thresholds == [0.015]
    assert controller.state.elapsed_sec == 2.0
    assert controller.state.level == 0.001


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RuntimeError("missing cublas64_12.dll"), "ASR GPU 依赖缺失，已切到 CPU 后请重启再试"),
        (RuntimeError("connect localhost:11434"), "Ollama 服务未启动"),
        (RuntimeError("x" * 200), "x" * 160),
        (RuntimeError(), "RuntimeError"),
    ],
)
def test_format_error_preserves_legacy_messages(exc: Exception, expected: str) -> None:
    controller = WebGuiController(FakeApp())

    assert controller._format_error(exc) == expected
