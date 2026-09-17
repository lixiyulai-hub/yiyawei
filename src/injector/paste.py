"""模拟 Ctrl+V 粘贴。"""

from __future__ import annotations

import time

from src.injector import clipboard as cb
from src.utils.foreground_window import set_foreground_window


def paste_text(
    text: str,
    restore_clipboard: bool = True,
    delay_ms: int = 150,
    target_hwnd: int | None = None,
) -> bool:
    if not text:
        return False

    original = cb.get_clipboard() if restore_clipboard else ""
    if not cb.set_clipboard(text):
        print(f"[injector] 剪贴板写入失败，请手动复制:\n{text}")
        return False

    if target_hwnd and not set_foreground_window(target_hwnd):
        print(f"[injector] 目标窗口无法切到前台，请手动粘贴:\n{text}")
        return False
    time.sleep(delay_ms / 1000.0)
    try:
        import pyautogui

        pyautogui.hotkey("ctrl", "v", interval=0.03)
    except ImportError:
        print(f"[injector] pyautogui 未安装，已写入剪贴板:\n{text}")
        return True

    if restore_clipboard:
        # Electron/WebView targets may read the clipboard asynchronously after Ctrl+V.
        time.sleep(max(0.35, delay_ms / 1000.0))
        cb.set_clipboard(original)

    return True
