"""Local web-shell GUI for the desktop app."""

from __future__ import annotations

import json
import mimetypes
import secrets
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.gui.web.contracts import WebGuiState
from src.gui.web.edit_service import EditService
from src.gui.web.recording_service import RecordingService
from src.gui.web.settings_store import WebGuiSettingsStore
from src.gui.web.server import WebGuiServer, find_free_port
from src.gui.web.window_target_service import WindowTargetService, find_chromium_path
from src.injector.paste import paste_text
from src.utils import window_style
from src.gui.simple_gui import LABEL_TO_MODE, LABEL_TO_SCRIPT, MODE_LABELS, SCRIPT_LABELS
from src.utils.foreground_window import (
    describe_window,
    get_foreground_window,
    get_process_name,
    get_window_process_id,
    is_window_maximized,
    is_window,
    maximize_window_no_activate,
    show_window_no_activate,
)


ASSETS_DIR = Path(__file__).resolve().parent / "web_assets"


class WebGuiController:
    def __init__(self, app: Any):
        self.app = app
        default_script = (app.output_cfg or {}).get("script", "simplified")
        self._settings_store = WebGuiSettingsStore.from_app(app)
        persisted = self._settings_store.load()
        self.state = WebGuiState(
            mode=app.default_mode,
            output_script=default_script,
            use_fast=persisted.get("useFast", True),
            intelligent_output=persisted.get("intelligentOutput", True),
        )
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._target_hwnd: int | None = None
        self._confirm_target_hwnd: int | None = None
        self._browser_process_id: int | None = None
        self._browser_hwnd: int | None = None
        self._browser_was_maximized = False
        self._last_debug: dict[str, Any] = {}
        self._theme_color = "#eefaf6"
        self._stop_threads = threading.Event()
        self._recording_service = RecordingService(self)
        self._edit_service = EditService(self)
        self._window_target_service = WindowTargetService(self)
        self._web_gui_session_token = secrets.token_urlsafe(32)
        self._web_gui_server = WebGuiServer(
            self,
            session_token=self._web_gui_session_token,
        )
        self._events = self._recording_service.events
        self._own_process_names = {
            "python.exe",
            "pythonw.exe",
        }
        self._system_shell_process_names = {
            "explorer.exe",
            "shellexperiencehost.exe",
            "startmenuexperiencehost.exe",
            "searchhost.exe",
            "textinputhost.exe",
            "applicationframehost.exe",
        }

    @property
    def _recording(self) -> bool:
        return self._recording_service.recording

    @_recording.setter
    def _recording(self, value: bool) -> None:
        self._recording_service.recording = value

    @property
    def _processing(self) -> bool:
        return self._recording_service.processing

    @_processing.setter
    def _processing(self, value: bool) -> None:
        self._recording_service.processing = value

    def run(self) -> None:
        url = self.start_server()
        self._start_background_workers()
        try:
            self._open_desktop_window(url)
        finally:
            self.shutdown()

    def start_server(self) -> str:
        return self._web_gui_server.start_server(
            server_factory=ThreadingHTTPServer,
            thread_factory=threading.Thread,
            find_port=_find_free_port,
        )

    def shutdown(self) -> None:
        self._stop_threads.set()
        try:
            if self._recording:
                self.app.recorder.stop()
        except Exception:
            pass
        try:
            self.app.recorder.close()
        except Exception:
            pass
        self._web_gui_server.shutdown()

    def _start_background_workers(self) -> None:
        if self.state.intelligent_output:
            self.app.warm_fast_llm()
        self.app.warm_asr()
        threading.Thread(target=self._poll_warm_state, daemon=True).start()
        threading.Thread(target=self._remember_foreground_window, daemon=True).start()
        threading.Thread(target=self._apply_events, daemon=True).start()

    def _open_desktop_window(self, url: str) -> None:
        return self._window_target_service._open_desktop_window(
            url,
            open_url=webbrowser.open,
            sleep=time.sleep,
        )

    def _open_chromium_app_window(self, url: str) -> bool:
        return self._window_target_service._open_chromium_app_window(
            url,
            find_browser_path=_find_chromium_path,
            popen=subprocess.Popen,
            thread=threading.Thread,
            sleep=time.sleep,
        )

    def _track_browser_window(self) -> None:
        return self._window_target_service._track_browser_window(
            now=time.time,
            sleep=time.sleep,
            apply_title_bar_color=window_style.apply_title_bar_color,
        )

    def _find_browser_window(self) -> int | None:
        return self._window_target_service._find_browser_window(
            find_main_window=window_style.find_main_window,
            find_window_by_title_and_process=window_style.find_window_by_title_and_process,
        )

    def apply_theme_color(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._window_target_service.apply_theme_color(
            payload,
            is_hex_color=window_style.is_hex_color,
            apply_title_bar_color=window_style.apply_title_bar_color,
        )

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.state.mode = _normalize_mode(payload.get("mode"), self.state.mode)
            self.state.output_script = _normalize_script(payload.get("outputScript"))
            self.state.use_fast = bool(payload.get("useFast", self.state.use_fast))
            previous_intelligent_output = self.state.intelligent_output
            self.state.intelligent_output = bool(
                payload.get("intelligentOutput", self.state.intelligent_output)
            )
            self._settings_store.save(
                use_fast=self.state.use_fast,
                intelligent_output=self.state.intelligent_output,
            )
            if self.state.intelligent_output and not previous_intelligent_output:
                self.app.warm_fast_llm()
            self.state.updated_at = time.time()
            return {"ok": True, "state": self.state.to_dict()}

    def _poll_warm_state(self) -> None:
        while not self._stop_threads.is_set():
            if getattr(self.app, "_asr_warm_done", False):
                with self._lock:
                    if self.state.phase == "warming":
                        self.state.phase = "ready"
                        self.state.status = "就绪"
                        self.state.updated_at = time.time()
                return
            time.sleep(0.35)

    def _remember_foreground_window(self) -> None:
        return self._window_target_service._remember_foreground_window(
            get_foreground_window=get_foreground_window,
            describe_window=describe_window,
            now=time.time,
            sleep=time.sleep,
        )

    def _is_valid_target(self, hwnd: int | None) -> bool:
        return self._window_target_service._is_valid_target(
            hwnd,
            is_window=is_window,
            get_window_process_id=get_window_process_id,
            get_process_name=get_process_name,
        )

    def _restore_browser_window_position(self) -> None:
        return self._window_target_service._restore_browser_window_position(
            show_window_no_activate=show_window_no_activate,
            maximize_window_no_activate=maximize_window_no_activate,
            was_maximized=self._browser_was_maximized,
        )

    def _apply_events(self) -> None:
        self._recording_service._apply_events()

    def bootstrap(self) -> dict[str, Any]:
        hotkey = ((self.app.config.get("hotkeys") or {}).get("gui_toggle") or "").strip()
        return {
            "state": self.get_state(),
            "modes": [{"value": key, "label": value} for key, value in MODE_LABELS.items()],
            "scripts": [{"value": key, "label": value} for key, value in SCRIPT_LABELS.items()],
            "hotkey": hotkey,
        }

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            if self._recording:
                self.state.elapsed_sec = self.app.recorder.get_elapsed_sec()
            return self.state.to_dict()

    def start_recording(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._recording_service.start_recording(
            payload,
            describe_window,
            _normalize_mode,
            _normalize_script,
        )

    def stop_recording(self, auto: bool = False) -> dict[str, Any]:
        return self._recording_service.stop_recording(auto)

    def toggle_recording(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._recording_service.toggle_recording(payload)

    def _start_auto_stop_monitor(self) -> None:
        self._recording_service._start_auto_stop_monitor()

    def _auto_stop_monitor(self, cfg: dict[str, object]) -> None:
        self._recording_service._auto_stop_monitor(cfg)

    def _process_audio(
        self,
        audio: Any,
        mode: str,
        use_fast: bool,
        intelligent_output: bool,
        target_hwnd: int | None,
        output_script: str,
    ) -> None:
        if self._browser_hwnd:
            self._browser_was_maximized = is_window_maximized(self._browser_hwnd)
        self._recording_service._process_audio(
            audio, mode, use_fast, intelligent_output, target_hwnd, output_script
        )

    def _format_error(self, exc: Exception) -> str:
        return self._recording_service._format_error(exc)

    def confirm_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._edit_service.confirm_text(
            payload,
            paste_text=paste_text,
            parse_record_id=_parse_record_id,
            now=time.time,
        )

    def _make_handler(self):
        return self._web_gui_server._make_handler(
            handler_base=BaseHTTPRequestHandler,
            assets_dir=ASSETS_DIR,
            parse_url=urlparse,
            json_loads=json.loads,
            json_dumps=json.dumps,
            json_decode_error=json.JSONDecodeError,
            guess_type=mimetypes.guess_type,
            ok=HTTPStatus.OK,
            not_found=HTTPStatus.NOT_FOUND,
            forbidden=HTTPStatus.FORBIDDEN,
        )


def _find_free_port() -> int:
    return find_free_port(socket_factory=socket.socket)


def _parse_record_id(value: str | int | None) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_chromium_path() -> str:
    return find_chromium_path(which=shutil.which)


def _normalize_mode(value: Any, default: str) -> str:
    if value in MODE_LABELS:
        return str(value)
    if value in LABEL_TO_MODE:
        return LABEL_TO_MODE[str(value)]
    return default


def _normalize_script(value: Any) -> str:
    if value in SCRIPT_LABELS:
        return str(value)
    if value in LABEL_TO_SCRIPT:
        return LABEL_TO_SCRIPT[str(value)]
    return "simplified"


def run_gui(app: Any) -> None:
    WebGuiController(app).run()
