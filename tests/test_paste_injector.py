from __future__ import annotations

import types

from src.injector import paste as paste_module


def test_paste_text_restores_target_window_and_keeps_clipboard_long_enough(monkeypatch):
    clipboard_values: list[str] = []
    hotkeys: list[tuple[tuple[str, ...], dict[str, object]]] = []
    sleeps: list[float] = []

    monkeypatch.setattr(paste_module.cb, "get_clipboard", lambda: "original")
    monkeypatch.setattr(paste_module.cb, "set_clipboard", lambda text: clipboard_values.append(text) or True)
    monkeypatch.setattr(paste_module, "set_foreground_window", lambda hwnd: hwnd == 123)
    monkeypatch.setattr(paste_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    fake_pyautogui = types.SimpleNamespace(
        hotkey=lambda *args, **kwargs: hotkeys.append((tuple(args), dict(kwargs)))
    )
    monkeypatch.setitem(__import__("sys").modules, "pyautogui", fake_pyautogui)

    assert paste_module.paste_text("compiled prompt", target_hwnd=123, delay_ms=150) is True
    assert clipboard_values == ["compiled prompt", "original"]
    assert hotkeys == [(("ctrl", "v"), {"interval": 0.03})]
    assert sleeps[-1] >= 0.35


def test_paste_text_reports_failure_when_target_cannot_be_activated(monkeypatch):
    hotkeys: list[object] = []

    monkeypatch.setattr(paste_module.cb, "get_clipboard", lambda: "original")
    monkeypatch.setattr(paste_module.cb, "set_clipboard", lambda text: True)
    monkeypatch.setattr(paste_module, "set_foreground_window", lambda hwnd: False)

    fake_pyautogui = types.SimpleNamespace(hotkey=lambda *args, **kwargs: hotkeys.append(args))
    monkeypatch.setitem(__import__("sys").modules, "pyautogui", fake_pyautogui)

    assert paste_module.paste_text("compiled prompt", target_hwnd=456) is False
    assert hotkeys == []
