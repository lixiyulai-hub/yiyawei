"""快捷键监听 - 按住录音、松开结束。"""

from __future__ import annotations

from typing import Callable

try:
    import keyboard
except ImportError:
    keyboard = None  # type: ignore


class HotkeyListener:
    """
    Windows 全局快捷键。建议管理员身份运行。
    若 keyboard 无法捕获，可用 --text 模式测试链路。
    """

    def __init__(self):
        self._hooks: list = []
        self._active_keys: set[str] = set()

    def register_hold(
        self,
        combo: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        if keyboard is None:
            raise RuntimeError("keyboard 库未安装")

        parts = [p.strip().lower() for p in combo.split("+")]
        main_key = parts[-1]
        modifiers = parts[:-1]
        state = {"held": False}

        def mods_pressed() -> bool:
            mapping = {
                "alt": keyboard.is_pressed("alt") or keyboard.is_pressed("left alt") or keyboard.is_pressed("right alt"),
                "shift": keyboard.is_pressed("shift") or keyboard.is_pressed("left shift") or keyboard.is_pressed("right shift"),
                "ctrl": keyboard.is_pressed("ctrl") or keyboard.is_pressed("left ctrl") or keyboard.is_pressed("right ctrl"),
            }
            return all(mapping.get(m, keyboard.is_pressed(m)) for m in modifiers)

        def handler(event):
            name = (event.name or "").lower()
            if name != main_key:
                return

            if event.event_type == keyboard.KEY_DOWN:
                if mods_pressed() and not state["held"]:
                    state["held"] = True
                    on_press()
            elif event.event_type == keyboard.KEY_UP:
                if state["held"]:
                    state["held"] = False
                    on_release()

        hook = keyboard.hook(handler)
        self._hooks.append(hook)

    def run_forever(self) -> None:
        if keyboard is None:
            raise RuntimeError("keyboard 库未安装")
        keyboard.wait()

    def stop(self) -> None:
        if keyboard:
            keyboard.unhook_all()
        self._hooks.clear()
