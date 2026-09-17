"""Windows desktop-window styling helpers."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
kernel32 = ctypes.windll.kernel32

DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_BORDER_COLOR = 34
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def is_hex_color(value: str) -> bool:
    if len(value) != 7 or not value.startswith("#"):
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value[1:])


def _colorref_from_hex(value: str) -> int:
    red = int(value[1:3], 16)
    green = int(value[3:5], 16)
    blue = int(value[5:7], 16)
    return red | (green << 8) | (blue << 16)


def _text_color_for_bg(value: str) -> int:
    red = int(value[1:3], 16)
    green = int(value[3:5], 16)
    blue = int(value[5:7], 16)
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return _colorref_from_hex("#111827" if luminance > 0.58 else "#f8fafc")


def _get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
    return buffer.value


def _get_window_pid(hwnd: int) -> int | None:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value) if pid.value else None


def _get_process_name(pid: int | None) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def apply_title_bar_color(hwnd: int | None, color: str) -> bool:
    if not hwnd or not is_hex_color(color):
        return False
    caption = wintypes.DWORD(_colorref_from_hex(color))
    text = wintypes.DWORD(_text_color_for_bg(color))
    border = wintypes.DWORD(_colorref_from_hex(color))
    ok_caption = dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_CAPTION_COLOR,
        ctypes.byref(caption),
        ctypes.sizeof(caption),
    )
    dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_TEXT_COLOR,
        ctypes.byref(text),
        ctypes.sizeof(text),
    )
    dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_BORDER_COLOR,
        ctypes.byref(border),
        ctypes.sizeof(border),
    )
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        None,
        0,
        0,
        0,
        0,
        0x0001 | 0x0002 | 0x0004 | 0x0020,
    )
    return ok_caption == 0


def find_main_window(pid: int, title_hint: str = "") -> int | None:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(window_pid))
        if int(window_pid.value) != pid:
            return True
        if title_hint:
            if title_hint not in _get_window_title(hwnd):
                return True
        found.append(int(hwnd))
        return False

    user32.EnumWindows(enum_proc, 0)
    return found[0] if found else None


def find_window_by_title_and_process(
    title_hint: str,
    process_names: set[str] | tuple[str, ...] | list[str],
) -> int | None:
    wanted_processes = {name.lower() for name in process_names}
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _get_window_title(hwnd)
        if title_hint not in title:
            return True
        process_name = _get_process_name(_get_window_pid(hwnd))
        if process_name not in wanted_processes:
            return True
        found.append(int(hwnd))
        return False

    user32.EnumWindows(enum_proc, 0)
    return found[0] if found else None
