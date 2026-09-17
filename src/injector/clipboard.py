"""剪贴板操作。"""

from __future__ import annotations

import pyperclip


def get_clipboard() -> str:
    try:
        return pyperclip.paste()
    except pyperclip.PyperclipException:
        return ""


def set_clipboard(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException:
        return False
