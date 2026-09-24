"""Browser window and paste-target management for the local web GUI."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from src.gui.web.contracts import WebGuiState


class WindowTargetHost(Protocol):
    app: Any
    state: WebGuiState
    _lock: Any
    _stop_threads: Any
    _target_hwnd: int | None
    _browser_process_id: int | None
    _browser_hwnd: int | None
    _theme_color: str
    _own_process_names: set[str]
    _system_shell_process_names: set[str]

    def _open_chromium_app_window(self, url: str) -> bool: ...

    def _track_browser_window(self) -> None: ...

    def _find_browser_window(self) -> int | None: ...

    def _is_valid_target(self, hwnd: int | None) -> bool: ...


def find_chromium_path(
    which: Callable[[str], str | None] | None = None,
) -> str:
    """Find Edge or Chrome using the legacy lookup order."""

    lookup = which or shutil.which
    for command in ("msedge", "chrome", "chrome.exe"):
        found = lookup(command)
        if found:
            return found
    candidates = [
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


class WindowTargetService:
    """Own desktop-window launch, tracking, styling, and target selection."""

    def __init__(self, host: WindowTargetHost):
        self.host = host

    def _open_desktop_window(
        self,
        url: str,
        *,
        open_url: Callable[[str], Any],
        sleep: Callable[[float], None],
    ) -> None:
        host = self.host
        if host._open_chromium_app_window(url):
            return

        host.app.logger.warning("未找到 Edge/Chrome App 模式，已退回默认浏览器打开 Web UI: %s", url)
        open_url(url)
        try:
            while not host._stop_threads.is_set():
                sleep(0.5)
        except KeyboardInterrupt:
            return

    def _open_chromium_app_window(
        self,
        url: str,
        *,
        find_browser_path: Callable[[], str],
        popen: Callable[[list[str]], Any],
        thread: Callable[..., Any],
        sleep: Callable[[float], None],
    ) -> bool:
        host = self.host
        browser_path = find_browser_path()
        if not browser_path:
            return False
        profile_dir = Path(host.app.storage.db_path).resolve().parent / "web_gui_browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            browser_path,
            f"--app={url}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--disable-extensions",
            "--window-size=700,640",
        ]
        try:
            process = popen(args)
        except OSError as exc:
            host.app.logger.warning("浏览器 App 模式启动失败: %s", exc)
            return False
        host._browser_process_id = process.pid
        thread(target=host._track_browser_window, daemon=True).start()
        try:
            while process.poll() is None and not host._stop_threads.is_set():
                sleep(0.5)
        except KeyboardInterrupt:
            return True
        finally:
            if process.poll() is None:
                process.terminate()
        return True

    def _track_browser_window(
        self,
        *,
        now: Callable[[], float],
        sleep: Callable[[float], None],
        apply_title_bar_color: Callable[[int | None, str], bool],
    ) -> None:
        host = self.host
        if not host._browser_process_id:
            return
        deadline = now() + 8
        while now() < deadline and not host._stop_threads.is_set():
            hwnd = host._find_browser_window()
            if hwnd:
                host._browser_hwnd = hwnd
                apply_title_bar_color(hwnd, host._theme_color)
                return
            sleep(0.18)

    def _find_browser_window(
        self,
        *,
        find_main_window: Callable[[int, str], int | None],
        find_window_by_title_and_process: Callable[[str, tuple[str, ...]], int | None],
    ) -> int | None:
        host = self.host
        hwnd = None
        if host._browser_process_id:
            hwnd = find_main_window(host._browser_process_id, "Yiyawei")
        if hwnd:
            return hwnd
        return find_window_by_title_and_process(
            "Yiyawei",
            ("chrome.exe", "msedge.exe"),
        )

    def apply_theme_color(
        self,
        payload: dict[str, Any],
        *,
        is_hex_color: Callable[[str], bool],
        apply_title_bar_color: Callable[[int | None, str], bool],
    ) -> dict[str, Any]:
        host = self.host
        color = str(payload.get("color") or "").strip()
        if not is_hex_color(color):
            return {"ok": False, "error": "invalid color"}
        host._theme_color = color
        if not host._browser_hwnd:
            host._browser_hwnd = host._find_browser_window()
        if host._browser_hwnd:
            apply_title_bar_color(host._browser_hwnd, color)
        return {"ok": True}

    def _remember_foreground_window(
        self,
        *,
        get_foreground_window: Callable[[], int | None],
        describe_window: Callable[[int | None], str | None],
        now: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        host = self.host
        while not host._stop_threads.is_set():
            current = get_foreground_window()
            if host._is_valid_target(current):
                host._target_hwnd = current
                target = describe_window(current)
                if target:
                    with host._lock:
                        host.state.target = f"目标：{target}"
                        host.state.updated_at = now()
            sleep(0.3)

    def _is_valid_target(
        self,
        hwnd: int | None,
        *,
        is_window: Callable[[int | None], bool],
        get_window_process_id: Callable[[int | None], int | None],
        get_process_name: Callable[[int | None], str],
    ) -> bool:
        host = self.host
        if not hwnd or not is_window(hwnd):
            return False
        # Exclude only the browser window owned by this Web GUI instance.
        # Other Chrome/Edge windows are valid user paste targets.
        if hwnd == host._browser_hwnd:
            return False
        process_name = get_process_name(get_window_process_id(hwnd)).lower()
        if process_name in host._own_process_names:
            return False
        if process_name in host._system_shell_process_names:
            return False
        return True

    def _restore_browser_window_position(
        self,
        *,
        show_window_no_activate: Callable[[int | None], bool],
        maximize_window_no_activate: Callable[[int | None], bool] | None = None,
        was_maximized: bool = False,
    ) -> None:
        host = self.host
        if not host._browser_hwnd:
            host._browser_hwnd = host._find_browser_window()
        if host._browser_hwnd:
            show_window_no_activate(host._browser_hwnd)
            if was_maximized and maximize_window_no_activate:
                maximize_window_no_activate(host._browser_hwnd)
