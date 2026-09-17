from __future__ import annotations

from src.utils import foreground_window


class FakeUser32:
    def __init__(self) -> None:
        self.foreground = 111
        self.valid_windows = {111, 222}
        self.threads = {111: 10, 222: 20}
        self.set_foreground_calls = 0
        self.attachments: list[tuple[int, int, bool]] = []
        self.allow_calls: list[int] = []
        self.allow_fallback = False

    def _value(self, hwnd) -> int:
        return int(getattr(hwnd, "value", hwnd) or 0)

    def GetForegroundWindow(self):
        return self.foreground

    def IsWindow(self, hwnd):
        return self._value(hwnd) in self.valid_windows

    def ShowWindow(self, hwnd, _cmd):
        return True

    def BringWindowToTop(self, hwnd):
        return True

    def SetActiveWindow(self, hwnd):
        return True

    def SetFocus(self, hwnd):
        return True

    def SetWindowPos(self, hwnd, *_args):
        return True

    def SetForegroundWindow(self, hwnd):
        self.set_foreground_calls += 1
        if self.allow_fallback or self.foreground == self._value(hwnd):
            self.foreground = self._value(hwnd)
            return True
        return False

    def AllowSetForegroundWindow(self, process_id):
        self.allow_calls.append(int(process_id))
        self.allow_fallback = True
        return True

    def AttachThreadInput(self, current_thread, target_thread, attach):
        self.attachments.append((int(current_thread), int(target_thread), bool(attach)))
        return True

    def GetWindowThreadProcessId(self, hwnd, _pid_ptr):
        return self.threads.get(self._value(hwnd), 0)


class FakeKernel32:
    def GetCurrentThreadId(self):
        return 1


def test_set_foreground_window_uses_thread_input_fallback(monkeypatch):
    fake_user32 = FakeUser32()
    monkeypatch.setattr(foreground_window, "user32", fake_user32)
    monkeypatch.setattr(foreground_window, "kernel32", FakeKernel32())
    monkeypatch.setattr(foreground_window.time, "sleep", lambda _seconds: None)

    assert foreground_window.set_foreground_window(222) is True

    assert fake_user32.foreground == 222
    assert fake_user32.set_foreground_calls >= 2
    assert fake_user32.allow_calls == [foreground_window.ASFW_ANY]
    assert (1, 10, True) in fake_user32.attachments
    assert (1, 20, True) in fake_user32.attachments
    assert fake_user32.attachments[-2:] == [(1, 20, False), (1, 10, False)]


def test_set_foreground_window_returns_true_when_already_foreground(monkeypatch):
    fake_user32 = FakeUser32()
    fake_user32.foreground = 222
    monkeypatch.setattr(foreground_window, "user32", fake_user32)

    assert foreground_window.set_foreground_window(222) is True
    assert fake_user32.set_foreground_calls == 0


def test_set_foreground_window_rejects_invalid_hwnd(monkeypatch):
    fake_user32 = FakeUser32()
    monkeypatch.setattr(foreground_window, "user32", fake_user32)

    assert foreground_window.set_foreground_window(999) is False


def test_get_window_thread_id_returns_none_for_invalid_hwnd(monkeypatch):
    fake_user32 = FakeUser32()
    monkeypatch.setattr(foreground_window, "user32", fake_user32)

    assert foreground_window.get_window_thread_id(999) is None
