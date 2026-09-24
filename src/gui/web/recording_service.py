"""Recording lifecycle service for the local web GUI."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from src.gui.web.contracts import WebGuiState


class RecordingHost(Protocol):
    app: Any
    state: WebGuiState
    _lock: Any
    _target_hwnd: int | None
    _confirm_target_hwnd: int | None
    _last_debug: dict[str, Any]
    _stop_threads: threading.Event

    def get_state(self) -> dict[str, Any]: ...

    def start_recording(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def stop_recording(self, auto: bool = False) -> dict[str, Any]: ...

    def _auto_stop_monitor(self, cfg: dict[str, object]) -> None: ...

    def _start_auto_stop_monitor(self) -> None: ...

    def _process_audio(
        self,
        audio: Any,
        mode: str,
        use_fast: bool,
        intelligent_output: bool,
        target_hwnd: int | None,
        output_script: str,
    ) -> None: ...

    def _restore_browser_window_position(self) -> None: ...

    def _format_error(self, exc: Exception) -> str: ...


class RecordingService:
    """Own recording state and operations while preserving controller facades."""

    def __init__(self, host: RecordingHost):
        self.host = host
        self.events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.recording = False
        self.processing = False

    def _apply_events(self) -> None:
        while not self.host._stop_threads.is_set():
            try:
                kind, payload = self.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "auto_stop":
                self.host.stop_recording(auto=True)

    def start_recording(
        self,
        payload: dict[str, Any],
        describe_window: Callable[[int | None], str | None],
        normalize_mode: Callable[[Any, str], str],
        normalize_script: Callable[[Any], str],
    ) -> dict[str, Any]:
        host = self.host
        with host._lock:
            if self.processing:
                return {"ok": False, "error": "上一段仍在处理中"}
            if self.recording:
                return {"ok": True, "state": host.state.to_dict()}
            mode = normalize_mode(payload.get("mode"), host.app.default_mode)
            output_script = normalize_script(payload.get("outputScript"))
            use_fast = bool(payload.get("useFast", True))
            intelligent_output = bool(
                payload.get("intelligentOutput", host.state.intelligent_output)
            )
            host.state.mode = mode
            host.state.output_script = output_script
            host.state.use_fast = use_fast
            host.state.intelligent_output = intelligent_output
            host.state.raw_text = ""
            host.state.final_text = ""
            host.state.pasted = False
            host.state.last_error = ""
            host.state.record_id = "-"
            host.state.risk_level = "-"
            target = describe_window(host._target_hwnd)
            host.state.target = f"目标：{target or '未识别，请先点目标输入框'}"
            host.state.phase = "recording"
            host.state.status = "录音中"
            host.state.updated_at = time.time()

        auto_cfg = (host.app.config.get("recorder") or {}).get("auto_stop") or {}
        configure_activity = getattr(host.app.recorder, "configure_voice_activity", None)
        if callable(configure_activity):
            configure_activity(
                level_threshold=float(auto_cfg.get("level_threshold", 0.015)),
                calibration_sec=float(auto_cfg.get("calibration_sec", 0.35)),
                speech_margin_sec=float(auto_cfg.get("speech_margin_sec", 0.18)),
            )
        host.app.recorder.start()
        self.recording = True
        host.app.logger.info("Web GUI 录音开始 | target_hwnd=%s", host._target_hwnd)
        host._start_auto_stop_monitor()
        return {"ok": True, "state": host.get_state()}

    def stop_recording(self, auto: bool = False) -> dict[str, Any]:
        host = self.host
        if not self.recording:
            return {"ok": True, "state": host.get_state()}
        audio = host.app.recorder.stop()
        self.recording = False
        if audio is None or len(audio) == 0:
            with host._lock:
                host.state.phase = "error"
                host.state.status = "未录到声音"
                host.state.final_text = "没有录到声音，请确认麦克风已选中，并稍微靠近一点再试。"
                host.state.last_error = host.state.final_text
                host.state.updated_at = time.time()
            return {"ok": False, "error": host.state.final_text, "state": host.get_state()}

        with host._lock:
            self.processing = True
            host.state.phase = "processing"
            host.state.status = "自动停止，处理中" if auto else "处理中"
            host.state.final_text = "正在处理语音，请稍等..."
            mode = host.state.mode
            output_script = host.state.output_script
            use_fast = host.state.use_fast
            intelligent_output = host.state.intelligent_output
            target_hwnd = host._target_hwnd
            host._confirm_target_hwnd = target_hwnd
            host.state.updated_at = time.time()

        threading.Thread(
            target=host._process_audio,
            args=(audio, mode, use_fast, intelligent_output, target_hwnd, output_script),
            daemon=True,
        ).start()
        return {"ok": True, "state": host.get_state()}

    def toggle_recording(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.recording:
            return self.host.stop_recording()
        return self.host.start_recording(payload)

    def _start_auto_stop_monitor(self) -> None:
        cfg = (self.host.app.config.get("recorder") or {}).get("auto_stop") or {}
        if not cfg.get("enabled", True):
            return
        threading.Thread(target=self.host._auto_stop_monitor, args=(cfg,), daemon=True).start()

    def _auto_stop_monitor(self, cfg: dict[str, object]) -> None:
        host = self.host
        min_duration = float(cfg.get("min_duration_sec", 1.2))
        silence_sec = float(cfg.get("silence_sec", 2.0))
        threshold = float(cfg.get("level_threshold", 0.015))
        interval = float(cfg.get("poll_interval_sec", 0.12))
        while self.recording and not host._stop_threads.is_set():
            elapsed = host.app.recorder.get_elapsed_sec()
            silent_for, level, voice_seen = host.app.recorder.update_voice_activity(threshold)
            with host._lock:
                host.state.elapsed_sec = elapsed
                host.state.level = level
                host.state.updated_at = time.time()
            if voice_seen and elapsed >= min_duration and silent_for >= silence_sec:
                host.app.logger.info(
                    "Web GUI 自动停止录音 | elapsed=%.2fs silent_for=%.2fs level=%.5f threshold=%.5f",
                    elapsed,
                    silent_for,
                    level,
                    threshold,
                )
                self.events.put(("auto_stop", {}))
                return
            time.sleep(interval)

    def _process_audio(
        self,
        audio: Any,
        mode: str,
        use_fast: bool,
        intelligent_output: bool,
        target_hwnd: int | None,
        output_script: str,
    ) -> None:
        host = self.host
        try:
            outcome = host.app.process_audio(
                audio,
                mode=mode,
                use_fast=use_fast,
                intelligent_output=intelligent_output,
                paste_hwnd=target_hwnd,
                output_script=output_script,
                allow_paste=True,
            )
            debug = outcome.get("debug", {}) if outcome else {}
            pasted = bool(outcome and outcome.get("pasted"))
            if pasted:
                host._restore_browser_window_position()
            with host._lock:
                host._last_debug = dict(debug) if isinstance(debug, dict) else {}
                host.state.phase = "done"
                host.state.status = "已粘贴" if pasted else "待确认"
                host.state.raw_text = str(debug.get("raw_asr_text") or "")
                host.state.final_text = str(debug.get("final_text") or "")
                host.state.asr_model = str(debug.get("asr_model") or "-")
                host.state.asr_device = str(debug.get("asr_device") or "-")
                host.state.llm_model = str(debug.get("llm_model") or "-")
                host.state.asr_ms = str(debug.get("asr_elapsed_ms") or "-")
                host.state.llm_ms = str(debug.get("llm_elapsed_ms") or "-")
                host.state.risk_level = str(debug.get("risk_level") or "-")
                host.state.record_id = str(outcome.get("record_id") if outcome else "-")
                host.state.pasted = pasted
                host.state.updated_at = time.time()
        except Exception as exc:
            host.app.logger.exception("Web GUI 处理失败: %s", exc)
            message = host._format_error(exc)
            with host._lock:
                host.state.phase = "error"
                host.state.status = "处理失败"
                host.state.final_text = f"错误：{message}"
                host.state.last_error = message
                host.state.updated_at = time.time()
        finally:
            with host._lock:
                self.processing = False

    def _format_error(self, exc: Exception) -> str:
        text = str(exc)
        if "cublas64_12.dll" in text:
            return "ASR GPU 依赖缺失，已切到 CPU 后请重启再试"
        if "localhost:11434" in text:
            return "Ollama 服务未启动"
        return text[:160] or exc.__class__.__name__
