from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, BrowserContext, Error, Page, sync_playwright

from src.gui import web_gui as web_gui_module
from src.gui.web_gui import WebGuiController


class FakeLogger:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def _record(self, level: str, message: object, *args: object) -> None:
        rendered = str(message)
        if args:
            try:
                rendered %= args
            except (TypeError, ValueError):
                rendered = f"{rendered} {args!r}"
        self.entries.append((level, rendered))

    def info(self, message: object, *args: object, **kwargs: object) -> None:
        self._record("info", message, *args)

    def warning(self, message: object, *args: object, **kwargs: object) -> None:
        self._record("warning", message, *args)

    def exception(self, message: object, *args: object, **kwargs: object) -> None:
        self._record("exception", message, *args)


class FakeRecorder:
    sample_rate = 16000

    def __init__(self, *, elapsed_sec: float = 1.5) -> None:
        self.elapsed_sec = elapsed_sec
        self.start_count = 0
        self.stop_count = 0
        self.close_count = 0
        self.activity_count = 0
        self.active = False
        self.auto_stop_armed = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self.start_count += 1
            self.active = True

    def stop(self) -> bytes:
        with self._lock:
            self.stop_count += 1
            self.active = False
        return b"deterministic-fake-audio"

    def get_elapsed_sec(self) -> float:
        return self.elapsed_sec

    def update_voice_activity(self, threshold: float) -> tuple[float, float, bool]:
        del threshold
        with self._lock:
            self.activity_count += 1
        if self.auto_stop_armed.is_set():
            return 1.0, 0.002, True
        return 0.0, 0.04, True

    def close(self) -> None:
        with self._lock:
            self.close_count += 1
            self.active = False


class FakeApp:
    default_mode = "cursor_prompt"
    output_cfg = {"script": "simplified"}
    injector_cfg = {"restore_clipboard": True, "paste_delay_ms": 0}

    def __init__(
        self,
        *,
        asr_ready: bool = True,
        auto_stop: bool = False,
        block_processing: bool = False,
    ) -> None:
        self.config = {
            "hotkeys": {"gui_toggle": "ctrl+."},
            "recorder": {
                "auto_stop": {
                    "enabled": auto_stop,
                    "min_duration_sec": 0.1,
                    "silence_sec": 0.1,
                    "level_threshold": 0.015,
                    "poll_interval_sec": 0.02,
                }
            },
        }
        self.logger = FakeLogger()
        self.recorder = FakeRecorder()
        self._asr_warm_done = asr_ready
        self.block_processing = block_processing
        self.processing_started = threading.Event()
        self.processing_release = threading.Event()
        self.processing_finished = threading.Event()
        self.process_count = 0
        self.process_kwargs: list[dict[str, Any]] = []
        self.confirm_calls: list[dict[str, Any]] = []
        self.warm_asr_count = 0
        self.warm_fast_llm_count = 0
        self._lock = threading.Lock()

    def warm_asr(self) -> None:
        self.warm_asr_count += 1

    def warm_fast_llm(self) -> None:
        self.warm_fast_llm_count += 1

    def mark_asr_ready(self) -> None:
        self._asr_warm_done = True

    def process_audio(self, audio: bytes, **kwargs: Any) -> dict[str, Any]:
        assert audio == b"deterministic-fake-audio"
        with self._lock:
            self.process_count += 1
            self.process_kwargs.append(dict(kwargs))
        self.processing_started.set()
        try:
            if self.block_processing and not self.processing_release.wait(timeout=4.0):
                raise TimeoutError("E2E processing gate was not released")
            return {
                "record_id": "e2e-001",
                "pasted": False,
                "debug": {
                    "raw_asr_text": "turn the selected note into a concise task",
                    "final_text": "Summarize the selected note as a concise implementation task.",
                    "asr_model": "fake-asr",
                    "asr_device": "cpu",
                    "llm_model": "fake-llm",
                    "asr_elapsed_ms": 12,
                    "llm_elapsed_ms": 34,
                    "risk_level": "low",
                },
            }
        finally:
            self.processing_finished.set()

    def confirm_edit(self, **kwargs: Any) -> dict[str, Any]:
        self.confirm_calls.append(dict(kwargs))
        return {"ok": True, "learned_rules": []}


@dataclass
class BrowserRuntime:
    browser: Browser
    name: str
    fallback_reason: str | None = None


@dataclass
class GuiHarness:
    app: FakeApp
    controller: WebGuiController
    context: BrowserContext
    page: Page
    url: str
    browser_name: str
    browser_fallback_reason: str | None
    console_messages: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    external_requests: list[str] = field(default_factory=list)

    def close(self) -> None:
        self.app.processing_release.set()
        self.app.mark_asr_ready()
        try:
            self.context.close()
        finally:
            server_thread = self.controller._server_thread
            self.controller.shutdown()
            if server_thread is not None:
                server_thread.join(timeout=2.0)
            self.app.processing_finished.wait(timeout=0.5)


def _system_edge_available() -> bool:
    if shutil.which("msedge"):
        return True
    candidates: list[Path] = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    return any(candidate.is_file() for candidate in candidates)


@pytest.fixture(scope="session")
def browser_runtime() -> Iterator[BrowserRuntime]:
    with sync_playwright() as playwright:
        browser: Browser | None = None
        browser_name = "chromium"
        fallback_reason: str | None = None
        if _system_edge_available():
            try:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                browser_name = "msedge"
            except Error as exc:
                fallback_reason = f"Edge launch failed: {exc}"
        else:
            fallback_reason = "System Edge executable was not found"
        if browser is None:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Error as exc:
                pytest.fail(f"No offline Playwright browser is usable: {exc}")
        try:
            yield BrowserRuntime(browser, browser_name, fallback_reason)
        finally:
            browser.close()


@pytest.fixture
def gui_session(
    browser_runtime: BrowserRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., GuiHarness]]:
    sessions: list[GuiHarness] = []

    monkeypatch.setattr(web_gui_module, "get_foreground_window", lambda: None)
    monkeypatch.setattr(web_gui_module, "describe_window", lambda hwnd: "")

    def reject_paste(*args: object, **kwargs: object) -> bool:
        raise AssertionError("E2E must not access the real paste injector")

    monkeypatch.setattr(web_gui_module, "paste_text", reject_paste)

    def start(
        *,
        viewport: tuple[int, int] = (700, 640),
        asr_ready: bool = True,
        auto_stop: bool = False,
        block_processing: bool = False,
        initial_state: dict[str, Any] | None = None,
    ) -> GuiHarness:
        app = FakeApp(
            asr_ready=asr_ready,
            auto_stop=auto_stop,
            block_processing=block_processing,
        )
        controller = WebGuiController(app)
        controller._find_browser_window = lambda: None
        if initial_state:
            with controller._lock:
                for name, value in initial_state.items():
                    setattr(controller.state, name, value)
                controller.state.updated_at = 1_700_000_000.0

        url = controller.start_server()
        controller._start_background_workers()
        parsed_url = urlparse(url)
        context = browser_runtime.browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            device_scale_factor=1,
            locale="zh-CN",
            timezone_id="Asia/Tokyo",
            color_scheme="light",
            reduced_motion="reduce",
        )
        external_requests: list[str] = []

        def route_request(route: Any, request: Any) -> None:
            parsed_request = urlparse(request.url)
            if (
                parsed_request.hostname == parsed_url.hostname
                and parsed_request.port == parsed_url.port
            ):
                route.continue_()
                return
            external_requests.append(request.url)
            route.abort()

        context.route("**/*", route_request)
        context.add_init_script(
            """
            (() => {
              try {
                localStorage.setItem("voice-prompt-compiler-theme", "silver-frost");
                localStorage.setItem("voice-prompt-compiler-theme-version", "3");
              } catch (_) {}
              window.__e2eStatePollCount = 0;
              const originalFetch = window.fetch.bind(window);
              window.fetch = (input, init) => {
                const value = typeof input === "string" ? input : input.url;
                const path = new URL(value, window.location.href).pathname;
                if (path === "/api/state") window.__e2eStatePollCount += 1;
                return originalFetch(input, init);
              };
            })();
            """
        )
        page = context.new_page()
        page.set_default_timeout(8_000)
        page.set_default_navigation_timeout(8_000)
        console_messages: list[str] = []
        page_errors: list[str] = []

        def capture_console(message: Any) -> None:
            if message.type in {"error", "warning"}:
                console_messages.append(f"{message.type}: {message.text}")

        page.on("console", capture_console)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            response = page.goto(url, wait_until="domcontentloaded")
            assert response is not None and response.ok
        except BaseException:
            context.close()
            controller.shutdown()
            raise

        harness = GuiHarness(
            app=app,
            controller=controller,
            context=context,
            page=page,
            url=url,
            browser_name=browser_runtime.name,
            browser_fallback_reason=browser_runtime.fallback_reason,
            console_messages=console_messages,
            page_errors=page_errors,
            external_requests=external_requests,
        )
        sessions.append(harness)
        return harness

    yield start

    for session in reversed(sessions):
        session.close()
