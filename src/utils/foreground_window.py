"""Windows foreground-window helpers."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ASFW_ANY = -1
HWND_TOP = 0
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_SHOWNOACTIVATE = 4
SW_RESTORE = 9
SW_MAXIMIZE = 3
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010


def get_foreground_window() -> int | None:
    hwnd = user32.GetForegroundWindow()
    return int(hwnd) if hwnd else None


def is_window(hwnd: int | None) -> bool:
    return bool(hwnd and user32.IsWindow(wintypes.HWND(hwnd)))


def get_window_thread_id(hwnd: int | None) -> int | None:
    if not is_window(hwnd):
        return None
    pid = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(thread_id) if thread_id else None


def _is_foreground(hwnd: int) -> bool:
    return get_foreground_window() == int(hwnd)


def _wait_for_foreground(hwnd: int, attempts: int = 5, delay_sec: float = 0.025) -> bool:
    for index in range(attempts):
        if _is_foreground(hwnd):
            return True
        if index < attempts - 1:
            time.sleep(delay_sec)
    return False


def _call_if_available(name: str, *args: object) -> bool:
    func = getattr(user32, name, None)
    if not func:
        return False
    return bool(func(*args))


def _activate_window(hwnd: int, window: wintypes.HWND) -> bool:
    # SW_RESTORE changes a maximized window to its previous normal size.
    # Restore only minimized windows so activation never causes a resize flash.
    is_iconic = getattr(user32, "IsIconic", None)
    if is_iconic and is_iconic(window):
        user32.ShowWindow(window, SW_RESTORE)
    _call_if_available("BringWindowToTop", window)
    _call_if_available("SetActiveWindow", window)
    _call_if_available("SetFocus", window)
    _call_if_available(
        "SetWindowPos",
        window,
        wintypes.HWND(HWND_TOP),
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
    )
    user32.SetForegroundWindow(window)
    return _wait_for_foreground(hwnd)


def set_foreground_window(hwnd: int | None) -> bool:
    if not is_window(hwnd):
        return False
    hwnd_value = int(hwnd)
    if _is_foreground(hwnd_value):
        return True
    window = wintypes.HWND(hwnd)
    if _activate_window(hwnd_value, window):
        return True

    _call_if_available("AllowSetForegroundWindow", ASFW_ANY)
    current_thread = int(kernel32.GetCurrentThreadId())
    foreground_thread = get_window_thread_id(get_foreground_window())
    target_thread = get_window_thread_id(hwnd_value)
    attached_threads: list[int] = []
    try:
        for thread_id in (foreground_thread, target_thread):
            if not thread_id or thread_id == current_thread or thread_id in attached_threads:
                continue
            if _call_if_available("AttachThreadInput", current_thread, thread_id, True):
                attached_threads.append(thread_id)
        return _activate_window(hwnd_value, window)
    finally:
        for thread_id in reversed(attached_threads):
            _call_if_available("AttachThreadInput", current_thread, thread_id, False)


def show_window_no_activate(hwnd: int | None) -> bool:
    if not is_window(hwnd):
        return False
    window = wintypes.HWND(hwnd)
    user32.ShowWindow(window, SW_SHOWNOACTIVATE)
    user32.SetWindowPos(
        window,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )
    return True


def is_window_maximized(hwnd: int | None) -> bool:
    return bool(is_window(hwnd) and user32.IsZoomed(wintypes.HWND(hwnd)))


def maximize_window_no_activate(hwnd: int | None) -> bool:
    if not is_window(hwnd):
        return False
    window = wintypes.HWND(hwnd)
    user32.ShowWindow(window, SW_MAXIMIZE)
    user32.SetWindowPos(
        window,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )
    return True


def get_window_text(hwnd: int | None) -> str:
    if not is_window(hwnd):
        return ""
    length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
    return buffer.value


def get_window_process_id(hwnd: int | None) -> int | None:
    if not is_window(hwnd):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value) if pid.value else None


def get_process_path(pid: int | None) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def get_process_name(pid: int | None) -> str:
    path = get_process_path(pid)
    return Path(path).name if path else ""


def describe_window(hwnd: int | None) -> str:
    title = get_window_text(hwnd)
    process_name = get_process_name(get_window_process_id(hwnd))
    if process_name and title:
        return f"{process_name} - {title}"
    return title or process_name or ""
