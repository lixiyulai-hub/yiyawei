from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.gui import web_gui as web_gui_module
from src.gui.web import WindowTargetService, find_chromium_path
from src.gui.web import window_target_service as service_module
from src.gui.web_gui import WebGuiController


class FakeLogger:
    def __init__(self) -> None:
        self.warnings: list[tuple[Any, ...]] = []

    def warning(self, *args: Any) -> None:
        self.warnings.append(args)


class FakeStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path


class FakeApp:
    default_mode = "cursor_prompt"
    output_cfg = {"script": "simplified"}

    def __init__(self, db_path: Path) -> None:
        self.logger = FakeLogger()
        self.storage = FakeStorage(db_path)


class FakeThread:
    instances: list[FakeThread] = []

    def __init__(self, *, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True


class ExitedProcess:
    pid = 4321
    terminated = False

    def poll(self) -> int:
        return 0


class RunningProcess:
    pid = 9876

    def __init__(self) -> None:
        self.terminated = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True


@pytest.fixture
def controller(tmp_path: Path) -> WebGuiController:
    return WebGuiController(FakeApp(tmp_path / "voice_prompt.db"))


def test_window_target_service_is_exported_owned_and_independent(controller):
    assert isinstance(controller._window_target_service, WindowTargetService)
    assert WindowTargetService is service_module.WindowTargetService
    assert find_chromium_path is service_module.find_chromium_path
    source = Path(service_module.__file__).read_text(encoding="utf-8")
    assert "from src.gui.web_gui" not in source


def test_controller_facades_pass_current_module_dependencies(monkeypatch, controller):
    calls = []

    def record(name, result=None):
        def method(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result

        return method

    service = controller._window_target_service
    monkeypatch.setattr(service, "_open_desktop_window", record("desktop"))
    monkeypatch.setattr(service, "_open_chromium_app_window", record("chromium", True))
    monkeypatch.setattr(service, "_track_browser_window", record("track"))
    monkeypatch.setattr(service, "_find_browser_window", record("find", 77))
    monkeypatch.setattr(service, "apply_theme_color", record("theme", {"ok": True}))
    monkeypatch.setattr(service, "_remember_foreground_window", record("remember"))
    monkeypatch.setattr(service, "_is_valid_target", record("valid", True))
    monkeypatch.setattr(service, "_restore_browser_window_position", record("restore"))

    open_url = lambda url: True
    popen = lambda args: None
    thread = lambda **kwargs: None
    now = lambda: 1.0
    sleep = lambda seconds: None
    find_path = lambda: "browser.exe"
    find_main = lambda pid, title: 1
    find_title = lambda title, processes: 2
    is_hex = lambda color: True
    apply_color = lambda hwnd, color: True
    foreground = lambda: 3
    describe = lambda hwnd: "window"
    valid_window = lambda hwnd: True
    window_pid = lambda hwnd: 4
    process_name = lambda pid: "target.exe"
    show = lambda hwnd: True

    monkeypatch.setattr(web_gui_module.webbrowser, "open", open_url)
    monkeypatch.setattr(web_gui_module.subprocess, "Popen", popen)
    monkeypatch.setattr(web_gui_module.threading, "Thread", thread)
    monkeypatch.setattr(web_gui_module.time, "time", now)
    monkeypatch.setattr(web_gui_module.time, "sleep", sleep)
    monkeypatch.setattr(web_gui_module, "_find_chromium_path", find_path)
    monkeypatch.setattr(web_gui_module.window_style, "find_main_window", find_main)
    monkeypatch.setattr(
        web_gui_module.window_style,
        "find_window_by_title_and_process",
        find_title,
    )
    monkeypatch.setattr(web_gui_module.window_style, "is_hex_color", is_hex)
    monkeypatch.setattr(web_gui_module.window_style, "apply_title_bar_color", apply_color)
    monkeypatch.setattr(web_gui_module, "get_foreground_window", foreground)
    monkeypatch.setattr(web_gui_module, "describe_window", describe)
    monkeypatch.setattr(web_gui_module, "is_window", valid_window)
    monkeypatch.setattr(web_gui_module, "get_window_process_id", window_pid)
    monkeypatch.setattr(web_gui_module, "get_process_name", process_name)
    monkeypatch.setattr(web_gui_module, "show_window_no_activate", show)

    controller._open_desktop_window("http://desktop")
    assert controller._open_chromium_app_window("http://chromium") is True
    controller._track_browser_window()
    assert controller._find_browser_window() == 77
    assert controller.apply_theme_color({"color": "#ffffff"}) == {"ok": True}
    controller._remember_foreground_window()
    assert controller._is_valid_target(9) is True
    controller._restore_browser_window_position()

    assert calls == [
        ("desktop", ("http://desktop",), {"open_url": open_url, "sleep": sleep}),
        (
            "chromium",
            ("http://chromium",),
            {
                "find_browser_path": find_path,
                "popen": popen,
                "thread": thread,
                "sleep": sleep,
            },
        ),
        (
            "track",
            (),
            {"now": now, "sleep": sleep, "apply_title_bar_color": apply_color},
        ),
        (
            "find",
            (),
            {
                "find_main_window": find_main,
                "find_window_by_title_and_process": find_title,
            },
        ),
        (
            "theme",
            ({"color": "#ffffff"},),
            {"is_hex_color": is_hex, "apply_title_bar_color": apply_color},
        ),
        (
            "remember",
            (),
            {
                "get_foreground_window": foreground,
                "describe_window": describe,
                "now": now,
                "sleep": sleep,
            },
        ),
        (
            "valid",
            (9,),
            {
                "is_window": valid_window,
                "get_window_process_id": window_pid,
                "get_process_name": process_name,
            },
        ),
        ("restore", (), {"show_window_no_activate": show}),
    ]


def test_open_desktop_window_falls_back_and_handles_keyboard_interrupt(monkeypatch, controller):
    opened = []
    monkeypatch.setattr(controller, "_open_chromium_app_window", lambda url: False)
    monkeypatch.setattr(web_gui_module.webbrowser, "open", lambda url: opened.append(url))

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(web_gui_module.time, "sleep", interrupt)
    assert controller._open_desktop_window("http://fallback") is None
    assert opened == ["http://fallback"]
    assert controller.app.logger.warnings == [
        ("未找到 Edge/Chrome App 模式，已退回默认浏览器打开 Web UI: %s", "http://fallback")
    ]


def test_open_chromium_captures_complete_compact_popen_args(monkeypatch, controller, tmp_path):
    FakeThread.instances = []
    popen_args = []
    process = ExitedProcess()
    monkeypatch.setattr(web_gui_module, "_find_chromium_path", lambda: "C:/Browser/browser.exe")
    monkeypatch.setattr(web_gui_module.subprocess, "Popen", lambda args: popen_args.append(args) or process)
    monkeypatch.setattr(web_gui_module.threading, "Thread", FakeThread)

    assert controller._open_chromium_app_window("http://app") is True
    profile_dir = tmp_path / "web_gui_browser_profile"
    assert profile_dir.is_dir()
    assert popen_args == [
        [
            "C:/Browser/browser.exe",
            "--app=http://app",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--disable-extensions",
            "--window-size=700,640",
        ]
    ]
    joined = " ".join(popen_args[0])
    assert "--window-size=700,570" not in joined
    assert "--window-size=760,590" not in joined
    assert "--window-size=790,610" not in joined
    assert controller._browser_process_id == 4321
    assert len(FakeThread.instances) == 1
    worker = FakeThread.instances[0]
    assert worker.target == controller._track_browser_window
    assert worker.daemon is True
    assert worker.started is True


def test_open_chromium_returns_false_and_logs_popen_oserror(monkeypatch, controller):
    monkeypatch.setattr(web_gui_module, "_find_chromium_path", lambda: "browser.exe")

    def fail(_args):
        raise OSError("launch failed")

    monkeypatch.setattr(web_gui_module.subprocess, "Popen", fail)
    assert controller._open_chromium_app_window("http://app") is False
    assert len(controller.app.logger.warnings) == 1
    warning = controller.app.logger.warnings[0]
    assert warning[0] == "浏览器 App 模式启动失败: %s"
    assert str(warning[1]) == "launch failed"


def test_open_chromium_terminates_running_process_when_stopped(monkeypatch, controller):
    FakeThread.instances = []
    process = RunningProcess()
    monkeypatch.setattr(web_gui_module, "_find_chromium_path", lambda: "browser.exe")
    monkeypatch.setattr(web_gui_module.subprocess, "Popen", lambda args: process)
    monkeypatch.setattr(web_gui_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(web_gui_module.time, "sleep", lambda seconds: controller._stop_threads.set())

    assert controller._open_chromium_app_window("http://app") is True
    assert process.terminated is True


def test_open_chromium_keyboard_interrupt_returns_true_and_terminates(monkeypatch, controller):
    process = RunningProcess()
    monkeypatch.setattr(web_gui_module, "_find_chromium_path", lambda: "browser.exe")
    monkeypatch.setattr(web_gui_module.subprocess, "Popen", lambda args: process)
    monkeypatch.setattr(web_gui_module.threading, "Thread", FakeThread)

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(web_gui_module.time, "sleep", interrupt)
    assert controller._open_chromium_app_window("http://app") is True
    assert process.terminated is True


def test_find_and_track_browser_window_use_host_facade(monkeypatch, controller):
    controller._browser_process_id = 91
    fallback_calls = []
    monkeypatch.setattr(web_gui_module.window_style, "find_main_window", lambda pid, title: 123)
    monkeypatch.setattr(
        web_gui_module.window_style,
        "find_window_by_title_and_process",
        lambda *args: fallback_calls.append(args) or 456,
    )
    assert controller._find_browser_window() == 123
    assert fallback_calls == []

    monkeypatch.setattr(web_gui_module.window_style, "find_main_window", lambda pid, title: None)
    assert controller._find_browser_window() == 456
    assert fallback_calls == [("Yiyawei", ("chrome.exe", "msedge.exe"))]

    found = []
    colors = []
    monkeypatch.setattr(controller, "_find_browser_window", lambda: found.append(True) or 789)
    monkeypatch.setattr(web_gui_module.time, "time", iter((10.0, 11.0)).__next__)
    monkeypatch.setattr(
        web_gui_module.window_style,
        "apply_title_bar_color",
        lambda hwnd, color: colors.append((hwnd, color)) or True,
    )
    controller._track_browser_window()
    assert found == [True]
    assert controller._browser_hwnd == 789
    assert colors == [(789, "#eefaf6")]


def test_track_browser_window_keeps_eight_second_deadline(monkeypatch, controller):
    controller._browser_process_id = 91
    finds = []
    sleeps = []
    monkeypatch.setattr(controller, "_find_browser_window", lambda: finds.append(True) or None)
    monkeypatch.setattr(web_gui_module.time, "time", iter((10.0, 17.0, 18.0)).__next__)
    monkeypatch.setattr(web_gui_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    controller._track_browser_window()
    assert finds == [True]
    assert sleeps == [0.18]


def test_apply_theme_color_validates_finds_and_styles_through_host(monkeypatch, controller):
    assert controller.apply_theme_color({"color": "red"}) == {
        "ok": False,
        "error": "invalid color",
    }
    colors = []
    monkeypatch.setattr(controller, "_find_browser_window", lambda: 222)
    monkeypatch.setattr(
        web_gui_module.window_style,
        "apply_title_bar_color",
        lambda hwnd, color: colors.append((hwnd, color)) or True,
    )
    assert controller.apply_theme_color({"color": "  #ffecec  "}) == {"ok": True}
    assert controller._theme_color == "#ffecec"
    assert controller._browser_hwnd == 222
    assert colors == [(222, "#ffecec")]


def test_remember_foreground_window_uses_host_validation_and_updates_state(monkeypatch, controller):
    validated = []
    monkeypatch.setattr(web_gui_module, "get_foreground_window", lambda: 333)
    monkeypatch.setattr(controller, "_is_valid_target", lambda hwnd: validated.append(hwnd) or True)
    monkeypatch.setattr(web_gui_module, "describe_window", lambda hwnd: "editor.exe - Draft")
    monkeypatch.setattr(web_gui_module.time, "time", lambda: 55.5)
    monkeypatch.setattr(web_gui_module.time, "sleep", lambda seconds: controller._stop_threads.set())

    controller._remember_foreground_window()
    assert validated == [333]
    assert controller._target_hwnd == 333
    assert controller.state.target == "目标：editor.exe - Draft"
    assert controller.state.updated_at == 55.5


@pytest.mark.parametrize(
    ("hwnd", "is_real", "process", "expected"),
    [
        (None, True, "editor.exe", False),
        (10, False, "editor.exe", False),
        (10, True, "PYTHON.EXE", False),
        (10, True, "Explorer.EXE", False),
        (10, True, "editor.exe", True),
    ],
)
def test_valid_target_preserves_window_and_process_filters(
    monkeypatch,
    controller,
    hwnd,
    is_real,
    process,
    expected,
):
    monkeypatch.setattr(web_gui_module, "is_window", lambda value: is_real)
    monkeypatch.setattr(web_gui_module, "get_window_process_id", lambda value: 808)
    monkeypatch.setattr(web_gui_module, "get_process_name", lambda pid: process)
    assert controller._is_valid_target(hwnd) is expected


def test_restore_browser_window_finds_through_host_and_shows_without_activation(
    monkeypatch,
    controller,
):
    finds = []
    shown = []
    monkeypatch.setattr(controller, "_find_browser_window", lambda: finds.append(True) or 444)
    monkeypatch.setattr(
        web_gui_module,
        "show_window_no_activate",
        lambda hwnd: shown.append(hwnd) or True,
    )
    controller._restore_browser_window_position()
    controller._restore_browser_window_position()
    assert finds == [True]
    assert shown == [444, 444]


def test_find_chromium_path_preserves_command_and_candidate_order(monkeypatch):
    commands = []

    def which(command):
        commands.append(command)
        return "C:/found/chrome.exe" if command == "chrome.exe" else None

    assert find_chromium_path(which=which) == "C:/found/chrome.exe"
    assert commands == ["msedge", "chrome", "chrome.exe"]

    candidates = []

    def exists(path):
        candidates.append(path.as_posix())
        return len(candidates) == 3

    monkeypatch.setattr(Path, "exists", exists)
    assert find_chromium_path(which=lambda command: None).replace("\\", "/") == (
        "C:/Program Files/Google/Chrome/Application/chrome.exe"
    )
    assert candidates == [
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
    ]


def test_web_gui_find_chromium_wrapper_uses_current_shutil_which(monkeypatch):
    calls = []
    monkeypatch.setattr(
        web_gui_module.shutil,
        "which",
        lambda command: calls.append(command) or "C:/edge.exe",
    )
    assert web_gui_module._find_chromium_path() == "C:/edge.exe"
    assert calls == ["msedge"]
