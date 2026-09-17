"""A small click-to-record GUI."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Any

try:
    import keyboard
except ImportError:
    keyboard = None  # type: ignore

from src.utils.foreground_window import (
    describe_window,
    get_foreground_window,
    get_process_name,
    get_window_process_id,
    is_window,
)


MODE_LABELS = {
    "cursor_prompt": "AI 任务需求",
    "normal_dictation": "普通听写",
    "terminal_command": "终端命令",
    "git_message": "Git 提交信息",
}

LABEL_TO_MODE = {label: mode for mode, label in MODE_LABELS.items()}

SCRIPT_LABELS = {
    "simplified": "简体中文",
    "traditional": "繁体中文",
    "auto": "自动",
}

LABEL_TO_SCRIPT = {label: script for script, label in SCRIPT_LABELS.items()}


FONT_UI = "Microsoft YaHei UI"

PALETTE = {
    "bg_top": "#fff7f4",
    "bg_mid": "#ffe2dc",
    "bg_bottom": "#f8c8bf",
    "ribbon_top": "#fffefd",
    "ribbon_warm": "#ffd8cf",
    "ribbon_cool": "#f6eef2",
    "surface": "#fff9f7",
    "surface_alt": "#fff2ee",
    "surface_lift": "#fffdfb",
    "text": "#332522",
    "muted": "#8f6b63",
    "faint": "#b48b83",
    "border": "#f1c5bc",
    "border_light": "#ffffff",
    "accent": "#df6f5f",
    "accent_hover": "#cf5e51",
    "accent_deep": "#a64236",
    "accent_soft": "#ffe1d9",
    "success": "#a45a45",
    "warning": "#b76a44",
    "error": "#a83d35",
    "text_bg": "#fffefe",
    "disabled_bg": "#ead6d1",
    "disabled_text": "#a88d86",
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix_color(left: str, right: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    a = _hex_to_rgb(left)
    b = _hex_to_rgb(right)
    channels = [round(a[i] + (b[i] - a[i]) * ratio) for i in range(3)]
    return "#{:02x}{:02x}{:02x}".format(*channels)


class GlassSwitch(tk.Canvas):
    def __init__(self, parent: tk.Misc, variable: tk.BooleanVar, **kwargs: Any):
        super().__init__(
            parent,
            width=44,
            height=24,
            bd=0,
            highlightthickness=0,
            bg=kwargs.pop("bg", PALETTE["surface_lift"]),
            cursor="hand2",
            **kwargs,
        )
        self.variable = variable
        self.bind("<Button-1>", self._toggle)
        self.variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _event: tk.Event) -> None:
        self.variable.set(not self.variable.get())

    def _draw(self) -> None:
        self.delete("all")
        selected = self.variable.get()
        track = PALETTE["accent"] if selected else "#f4d6cf"
        outline = "#e9ada2" if selected else "#f1c8bf"
        knob_x = 32 if selected else 12
        self._round_rect(1, 2, 43, 23, 12, fill=track, outline=outline, width=1)
        self.create_oval(knob_x - 8, 5, knob_x + 8, 21, fill="#fffdfb", outline="#ffffff", width=1)
        self.create_arc(knob_x - 7, 6, knob_x + 7, 19, start=35, extent=110, style=tk.ARC, outline="#ffeae5", width=1)

    def _round_rect(self, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs: Any) -> int:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self.create_polygon(points, smooth=True, splinesteps=20, **kwargs)


class GlassRecordButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Any,
        bg: str = PALETTE["surface"],
        **kwargs: Any,
    ):
        super().__init__(
            parent,
            height=46,
            bd=0,
            highlightthickness=0,
            bg=bg,
            cursor="hand2",
            **kwargs,
        )
        self._text = text
        self._command = command
        self._style = "Record.TButton"
        self._disabled = False
        self._hover = False
        self._pressed = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    def configure(self, cnf: dict[str, Any] | None = None, **kwargs: Any) -> None:  # type: ignore[override]
        options = dict(cnf or {})
        options.update(kwargs)
        if "text" in options:
            self._text = str(options.pop("text"))
        if "style" in options:
            self._style = str(options.pop("style"))
        if "state" in options:
            state = options.pop("state")
            self._disabled = state in (tk.DISABLED, "disabled")
            self.configure(cursor="arrow" if self._disabled else "hand2")
        if "command" in options:
            self._command = options.pop("command")
        if options:
            super().configure(**options)
        self._draw()

    config = configure

    def state(self) -> tuple[str, ...]:
        return ("disabled",) if self._disabled else ()

    def _on_enter(self, _event: tk.Event) -> None:
        if self._disabled:
            return
        self._hover = True
        self._draw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event: tk.Event) -> None:
        if self._disabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _event: tk.Event) -> None:
        if self._disabled:
            return
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and callable(self._command):
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 220)
        height = max(self.winfo_height(), 46)

        if self._disabled:
            top = _mix_color(PALETTE["disabled_bg"], "#fffdfb", 0.22)
            bottom = PALETTE["disabled_bg"]
            text = PALETTE["disabled_text"]
            shadow = "#efd6d0"
        elif self._style.startswith("Stop"):
            top = "#b84c3f" if not self._hover else "#c9584a"
            bottom = "#91362d" if not self._pressed else "#7d2e26"
            text = "#ffffff"
            shadow = "#d49c90"
        else:
            top = "#ee8776" if self._hover else "#e57665"
            bottom = "#cf5e51" if not self._pressed else "#b94f43"
            text = "#ffffff"
            shadow = "#e5a398"

        self._round_rect(2, 4, width - 2, height - 1, 16, fill=shadow, outline="")
        self._round_rect(0, 0, width - 4, height - 5, 15, fill=bottom, outline="#ffffff", width=1)
        self._round_rect(1, 1, width - 5, height * 0.58, 14, fill=top, outline="")
        self.create_line(12, 2, width - 18, 2, fill="#fff4ef", width=1)
        self.create_text(
            (width - 4) / 2,
            (height - 5) / 2,
            text=self._text,
            fill=text,
            font=(FONT_UI, 11, "bold"),
        )

    def _round_rect(self, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs: Any) -> int:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self.create_polygon(points, smooth=True, splinesteps=20, **kwargs)


class VoicePromptGui:
    def __init__(self, app: Any):
        self.app = app
        self.root = tk.Tk()
        self.root.title("咿呀喂")
        self.root.geometry("540x560")
        self.root.minsize(500, 500)
        self.root.configure(bg=PALETTE["bg_mid"])
        self.root.attributes("-topmost", True)
        self.root.option_add("*Font", (FONT_UI, 10))
        self.root.option_add("*TCombobox*Listbox.font", (FONT_UI, 10))
        self.root.option_add("*TCombobox*Listbox.background", PALETTE["surface_lift"])
        self.root.option_add("*TCombobox*Listbox.foreground", PALETTE["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", PALETTE["accent_soft"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", PALETTE["text"])

        self.mode_var = tk.StringVar(value=MODE_LABELS.get(app.default_mode, app.default_mode))
        default_script = (app.output_cfg or {}).get("script", "simplified")
        self.script_var = tk.StringVar(value=SCRIPT_LABELS.get(default_script, "简体中文"))
        self.fast_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就绪")
        self.target_var = tk.StringVar(value="先点目标输入框，再点击开始录音。")
        self.meta_var = tk.StringVar(value="ASR：-    LLM：-    耗时：-")

        self._recording = False
        self._auto_stop_requested = False
        self._target_hwnd: int | None = None
        self._gui_hwnds: set[int] = set()
        self._own_process_names = {"python.exe", "pythonw.exe"}
        self._global_hotkey = None
        self._events: queue.Queue[tuple[str, str, dict[str, object]]] = queue.Queue()
        self._shell_window: int | None = None
        self._target_label: ttk.Label | None = None
        self._meta_label: ttk.Label | None = None
        self.status_label: ttk.Label | None = None
        self.frame: tk.Frame | None = None
        self.bg_canvas: tk.Canvas | None = None

        self._build()
        self._register_global_toggle_hotkey()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(200, self._maybe_warm_asr)
        self.root.after(500, self._maybe_warm_fast_llm)
        self.root.after(300, self._remember_foreground_window)
        self.root.after(150, self._poll_events)

    def _build(self) -> None:
        self._configure_styles()

        self.bg_canvas = tk.Canvas(self.root, bd=0, highlightthickness=0, bg=PALETTE["bg_mid"])
        self.bg_canvas.pack(fill=tk.BOTH, expand=True)
        self.bg_canvas.bind("<Configure>", self._layout_background)

        frame = tk.Frame(self.bg_canvas, bg=PALETTE["surface"], padx=16, pady=14)
        self._shell_window = self.bg_canvas.create_window(22, 22, anchor=tk.NW, window=frame)
        self.frame = frame

        header = tk.Frame(frame, bg=PALETTE["surface"])
        header.pack(fill=tk.X)

        title_col = tk.Frame(header, bg=PALETTE["surface"])
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

        title = ttk.Label(title_col, text="咿呀喂", style="Title.TLabel")
        title.pack(anchor=tk.W)
        subtitle = ttk.Label(title_col, text="Yiyawei", style="Subtitle.TLabel")
        subtitle.pack(anchor=tk.W, pady=(2, 0))

        self.status_label = ttk.Label(header, textvariable=self.status_var, style="Ready.Status.TLabel")
        self.status_label.pack(side=tk.RIGHT, anchor=tk.N, padx=(10, 0), pady=(2, 0))

        control_card = tk.Frame(
            frame,
            bg=PALETTE["surface_lift"],
            highlightthickness=1,
            highlightbackground=PALETTE["border_light"],
            padx=12,
            pady=12,
        )
        control_card.pack(fill=tk.X, pady=(14, 10))

        selectors = tk.Frame(control_card, bg=PALETTE["surface_lift"])
        selectors.pack(fill=tk.X)
        selectors.grid_columnconfigure(0, weight=1)
        selectors.grid_columnconfigure(1, weight=1)

        mode_row = tk.Frame(selectors, bg=PALETTE["surface_lift"])
        mode_row.grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
        ttk.Label(mode_row, text="输出风格", style="FieldLabel.TLabel").pack(anchor=tk.W)
        mode_box = ttk.Combobox(
            mode_row,
            textvariable=self.mode_var,
            values=tuple(MODE_LABELS.values()),
            state="readonly",
            width=16,
            style="Soft.TCombobox",
        )
        mode_box.pack(fill=tk.X, pady=(5, 0))
        self.mode_box = mode_box

        script_row = tk.Frame(selectors, bg=PALETTE["surface_lift"])
        script_row.grid(row=0, column=1, sticky=tk.EW, padx=(8, 0))
        ttk.Label(script_row, text="输出文字", style="FieldLabel.TLabel").pack(anchor=tk.W)
        script_box = ttk.Combobox(
            script_row,
            textvariable=self.script_var,
            values=tuple(SCRIPT_LABELS.values()),
            state="readonly",
            width=16,
            style="Soft.TCombobox",
        )
        script_box.pack(fill=tk.X, pady=(5, 0))
        self.script_box = script_box

        fast_row = tk.Frame(control_card, bg=PALETTE["surface_lift"])
        fast_row.pack(anchor=tk.E, pady=(10, 0))
        ttk.Label(fast_row, text="极速模式", style="FieldLabel.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        fast_check = GlassSwitch(fast_row, self.fast_var, bg=PALETTE["surface_lift"])
        fast_check.pack(side=tk.LEFT)
        self.fast_check = fast_check

        self.record_button = GlassRecordButton(
            frame,
            text="开始录音",
            command=self.toggle_recording,
            bg=PALETTE["surface"],
        )
        self.record_button.pack(fill=tk.X, pady=(0, 10))

        info = tk.Frame(
            frame,
            bg=PALETTE["surface_alt"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            padx=11,
            pady=8,
        )
        info.pack(fill=tk.X, pady=(0, 10))
        self._target_label = ttk.Label(info, textvariable=self.target_var, wraplength=460, style="Info.TLabel")
        self._target_label.pack(anchor=tk.W)
        self._meta_label = ttk.Label(info, textvariable=self.meta_var, wraplength=460, style="Meta.TLabel")
        self._meta_label.pack(anchor=tk.W, pady=(4, 0))

        detail_header = tk.Frame(frame, bg=PALETTE["surface"])
        detail_header.pack(fill=tk.X, pady=(1, 6))
        ttk.Label(detail_header, text="对照", style="Section.TLabel").pack(side=tk.LEFT)

        detail = tk.Frame(frame, bg=PALETTE["surface"])
        detail.pack(fill=tk.BOTH, expand=True)
        detail.grid_columnconfigure(0, weight=1)
        detail.grid_columnconfigure(1, weight=1)
        detail.grid_rowconfigure(0, weight=1)
        self.raw_text = self._add_text_panel(detail, "ASR 原文", height=8, grid=(0, 0), padx=(0, 5))
        self.final_text = self._add_text_panel(detail, "最终文本", height=8, grid=(0, 1), padx=(5, 0))

        self.root.after(0, self._layout_background)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=(FONT_UI, 10), background=PALETTE["surface"], foreground=PALETTE["text"])
        style.configure("Title.TLabel", font=(FONT_UI, 16, "bold"), foreground=PALETTE["text"], background=PALETTE["surface"])
        style.configure("Subtitle.TLabel", font=(FONT_UI, 9), foreground=PALETTE["muted"], background=PALETTE["surface"])
        style.configure("Section.TLabel", font=(FONT_UI, 10, "bold"), foreground=PALETTE["accent_deep"], background=PALETTE["surface"])
        style.configure("FieldLabel.TLabel", font=(FONT_UI, 9), foreground=PALETTE["muted"], background=PALETTE["surface_lift"])
        style.configure("PanelLabel.TLabel", font=(FONT_UI, 9, "bold"), foreground=PALETTE["accent_deep"], background=PALETTE["text_bg"])
        style.configure("Info.TLabel", font=(FONT_UI, 9), foreground=PALETTE["text"], background=PALETTE["surface_alt"])
        style.configure("Meta.TLabel", font=(FONT_UI, 8), foreground=PALETTE["muted"], background=PALETTE["surface_alt"])

        status_base = {
            "font": (FONT_UI, 9, "bold"),
            "padding": (10, 4),
            "borderwidth": 0,
        }
        style.configure("Ready.Status.TLabel", **status_base, foreground=PALETTE["success"], background="#fff0eb")
        style.configure("Recording.Status.TLabel", **status_base, foreground="#ffffff", background=PALETTE["accent"])
        style.configure("Working.Status.TLabel", **status_base, foreground=PALETTE["warning"], background="#fff4df")
        style.configure("Done.Status.TLabel", **status_base, foreground=PALETTE["accent_deep"], background=PALETTE["accent_soft"])
        style.configure("Error.Status.TLabel", **status_base, foreground="#ffffff", background=PALETTE["error"])

        style.configure(
            "Record.TButton",
            font=(FONT_UI, 11, "bold"),
            foreground="#ffffff",
            background=PALETTE["accent"],
            borderwidth=0,
            focusthickness=0,
            focuscolor=PALETTE["accent"],
            padding=(14, 10),
            relief=tk.FLAT,
        )
        style.map(
            "Record.TButton",
            background=[("disabled", PALETTE["disabled_bg"]), ("pressed", PALETTE["accent_deep"]), ("active", PALETTE["accent_hover"])],
            foreground=[("disabled", PALETTE["disabled_text"])],
            relief=[("pressed", tk.SUNKEN), ("!pressed", tk.FLAT)],
        )
        style.configure(
            "Stop.Record.TButton",
            font=(FONT_UI, 11, "bold"),
            foreground="#ffffff",
            background=PALETTE["accent_deep"],
            borderwidth=0,
            focusthickness=0,
            focuscolor=PALETTE["accent_deep"],
            padding=(14, 10),
            relief=tk.FLAT,
        )
        style.map(
            "Stop.Record.TButton",
            background=[("disabled", PALETTE["disabled_bg"]), ("pressed", "#803228"), ("active", "#963a30")],
            foreground=[("disabled", PALETTE["disabled_text"])],
            relief=[("pressed", tk.SUNKEN), ("!pressed", tk.FLAT)],
        )

        style.configure(
            "Soft.TCombobox",
            fieldbackground=PALETTE["surface"],
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            arrowcolor=PALETTE["accent_deep"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border_light"],
            darkcolor=PALETTE["border"],
            padding=(8, 5),
            relief=tk.FLAT,
        )
        style.map(
            "Soft.TCombobox",
            fieldbackground=[("readonly", PALETTE["surface"])],
            bordercolor=[("focus", PALETTE["accent"]), ("hover", PALETTE["accent"])],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=PALETTE["accent_soft"],
            troughcolor=PALETTE["surface"],
            bordercolor=PALETTE["surface"],
            arrowcolor=PALETTE["accent_deep"],
            relief=tk.FLAT,
            width=10,
        )

    def _layout_background(self, event: tk.Event | None = None) -> None:
        width = int(getattr(event, "width", self.bg_canvas.winfo_width()) or self.root.winfo_width() or 540)
        height = int(getattr(event, "height", self.bg_canvas.winfo_height()) or self.root.winfo_height() or 560)
        width = max(width, 1)
        height = max(height, 1)

        self.bg_canvas.delete("bg")
        for y in range(0, height, 3):
            ratio = y / max(height - 1, 1)
            if ratio < 0.55:
                fill = _mix_color(PALETTE["bg_top"], PALETTE["bg_mid"], ratio / 0.55)
            else:
                fill = _mix_color(PALETTE["bg_mid"], PALETTE["bg_bottom"], (ratio - 0.55) / 0.45)
            self.bg_canvas.create_rectangle(0, y, width, y + 3, fill=fill, outline="", tags="bg")

        self.bg_canvas.create_polygon(
            -30,
            height * 0.18,
            width * 0.46,
            height * 0.02,
            width + 40,
            height * 0.20,
            width + 40,
            height * 0.35,
            width * 0.44,
            height * 0.20,
            -30,
            height * 0.31,
            fill=PALETTE["ribbon_top"],
            outline="",
            smooth=True,
            tags="bg",
        )
        self.bg_canvas.create_polygon(
            -35,
            height * 0.76,
            width * 0.42,
            height * 0.58,
            width + 35,
            height * 0.79,
            width + 35,
            height + 30,
            width * 0.22,
            height * 0.90,
            -35,
            height * 0.98,
            fill=PALETTE["ribbon_warm"],
            outline="",
            smooth=True,
            tags="bg",
        )
        self.bg_canvas.create_polygon(
            width * 0.66,
            -20,
            width + 40,
            height * 0.08,
            width + 40,
            height * 0.54,
            width * 0.80,
            height * 0.42,
            width * 0.76,
            height * 0.10,
            fill=PALETTE["ribbon_cool"],
            outline="",
            smooth=True,
            tags="bg",
        )

        margin = 14
        self._round_rect(margin + 4, margin + 7, width - margin + 4, height - margin + 7, 24, fill="#e8a99d", outline="", tags="bg")
        self._round_rect(margin, margin, width - margin, height - margin, 24, fill=PALETTE["surface"], outline=PALETTE["border_light"], width=1, tags="bg")
        self._round_rect(margin + 1, margin + 1, width - margin - 1, height - margin - 1, 22, fill="", outline="#fffefd", width=1, tags="bg")
        self.bg_canvas.tag_lower("bg")

        if self._shell_window is not None:
            inset = 22
            self.bg_canvas.coords(self._shell_window, inset, inset)
            self.bg_canvas.itemconfigure(self._shell_window, width=max(1, width - inset * 2), height=max(1, height - inset * 2))
        wrap = max(300, width - 92)
        if self._target_label is not None:
            self._target_label.configure(wraplength=wrap)
        if self._meta_label is not None:
            self._meta_label.configure(wraplength=wrap)

    def _round_rect(self, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs) -> int:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self.bg_canvas.create_polygon(points, smooth=True, splinesteps=20, **kwargs)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        try:
            self._unregister_global_toggle_hotkey()
            if self._recording:
                self._stop_recording()
            self.app.recorder.close()
        finally:
            self.root.destroy()

    def toggle_recording(self) -> None:
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _toggle_recording_from_hotkey(self) -> None:
        if "disabled" in self.record_button.state():
            return
        self.toggle_recording()

    def _set_status(self, text: str, style: str = "Ready.Status.TLabel") -> None:
        self.status_var.set(text)
        if self.status_label is not None:
            self.status_label.configure(style=style)

    def _set_record_button(self, text: str, style: str = "Record.TButton", disabled: bool = False) -> None:
        self.record_button.configure(text=text, style=style, state=tk.DISABLED if disabled else tk.NORMAL)

    def _register_global_toggle_hotkey(self) -> None:
        hotkey = ((self.app.config.get("hotkeys") or {}).get("gui_toggle") or "").strip()
        if not hotkey or keyboard is None:
            return
        try:
            self._global_hotkey = keyboard.add_hotkey(
                hotkey,
                lambda: self.root.after(0, self._toggle_recording_from_hotkey),
            )
            self.app.logger.info("GUI 全局录音切换快捷键: %s", hotkey)
        except Exception as exc:
            self.app.logger.warning("GUI 全局录音切换快捷键注册失败 (%s): %s", hotkey, exc)

    def _unregister_global_toggle_hotkey(self) -> None:
        if self._global_hotkey is None or keyboard is None:
            return
        try:
            keyboard.remove_hotkey(self._global_hotkey)
        except Exception:
            pass
        self._global_hotkey = None

    def _start_recording(self) -> None:
        self._target_hwnd = self._find_target_window()
        target = describe_window(self._target_hwnd)
        self.target_var.set(f"目标：{target or '未识别，请先点目标输入框'}")
        self.app.recorder.start()
        self._recording = True
        self._auto_stop_requested = False
        self._set_record_button("停止录音", "Stop.Record.TButton")
        self._set_status("录音中", "Recording.Status.TLabel")
        self._clear_output_panels("录音中...")
        self.app.logger.info("GUI 录音开始 | target_hwnd=%s target=%s", self._target_hwnd, target)
        self._start_auto_stop_monitor()

    def _stop_recording(self) -> None:
        if not self._recording:
            return
        audio = self.app.recorder.stop()
        self._recording = False
        self._set_record_button("开始录音", "Record.TButton")
        if audio is None or len(audio) == 0:
            self._set_status("未录到声音", "Error.Status.TLabel")
            self._set_text(self.final_text, "没有录到声音，请确认麦克风已选中，并稍微靠近一点再试。")
            return
        self._set_status("处理中", "Working.Status.TLabel")
        self._set_text(self.final_text, "正在处理语音，请稍等...")
        self._set_record_button("处理中", "Record.TButton", disabled=True)
        mode = LABEL_TO_MODE.get(self.mode_var.get(), self.app.default_mode)
        output_script = LABEL_TO_SCRIPT.get(self.script_var.get(), "simplified")
        use_fast = self.fast_var.get()
        target_hwnd = self._target_hwnd
        thread = threading.Thread(
            target=self._process_audio,
            args=(audio, mode, use_fast, target_hwnd, output_script),
            daemon=True,
        )
        thread.start()

    def _start_auto_stop_monitor(self) -> None:
        cfg = (self.app.config.get("recorder") or {}).get("auto_stop") or {}
        if not cfg.get("enabled", True):
            return
        threading.Thread(target=self._auto_stop_monitor, args=(cfg,), daemon=True).start()

    def _auto_stop_monitor(self, cfg: dict[str, object]) -> None:
        min_duration = float(cfg.get("min_duration_sec", 1.2))
        silence_sec = float(cfg.get("silence_sec", 2.0))
        threshold = float(cfg.get("level_threshold", 0.015))
        interval = float(cfg.get("poll_interval_sec", 0.12))
        while self._recording:
            elapsed = self.app.recorder.get_elapsed_sec()
            silent_for, level, voice_seen = self.app.recorder.update_voice_activity(threshold)
            if voice_seen and elapsed >= min_duration and silent_for >= silence_sec:
                self.app.logger.info(
                    "GUI 自动停止录音 | elapsed=%.2fs silent_for=%.2fs level=%.5f threshold=%.5f",
                    elapsed,
                    silent_for,
                    level,
                    threshold,
                )
                self._auto_stop_requested = True
                self._events.put(("auto_stop", "", {}))
                return
            time.sleep(interval)

    def _process_audio(
        self,
        audio,
        mode: str,
        use_fast: bool,
        target_hwnd: int | None,
        output_script: str,
    ) -> None:
        try:
            outcome = self.app.process_audio(
                audio,
                mode=mode,
                use_fast=use_fast,
                paste_hwnd=target_hwnd,
                output_script=output_script,
            )
            if outcome and outcome.get("pasted"):
                self._events.put(("done", "已粘贴", outcome.get("debug", {})))
            else:
                self._events.put(("done", "完成", outcome.get("debug", {}) if outcome else {}))
        except Exception as exc:
            self.app.logger.exception("GUI 处理失败: %s", exc)
            message = self._format_error(exc)
            self._events.put(
                (
                    "error",
                    message,
                    {
                        "cleaned_text": "处理失败，未生成纠错/清理文本。",
                        "final_text": f"错误：{message}",
                    },
                )
            )

    def _poll_events(self) -> None:
        try:
            while True:
                kind, message, debug = self._events.get_nowait()
                if kind == "auto_stop":
                    if self._recording:
                        self._stop_recording()
                    continue
                if kind == "done":
                    self._set_status(message, "Done.Status.TLabel")
                else:
                    self._set_status(f"错误：{message}", "Error.Status.TLabel")
                if debug:
                    self._update_debug_panels(debug)
                elif kind == "error":
                    self._set_text(self.final_text, f"错误：{message}")
                self._set_record_button("开始录音", "Record.TButton")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _remember_foreground_window(self) -> None:
        current = get_foreground_window()
        self._gui_hwnds.add(int(self.root.winfo_id()))
        if self._is_valid_target(current):
            self._target_hwnd = current
            target = describe_window(current)
            if target:
                self.target_var.set(f"目标：{target}")
        self.root.after(300, self._remember_foreground_window)

    def _find_target_window(self) -> int | None:
        self.root.update_idletasks()
        self._gui_hwnds.add(int(self.root.winfo_id()))
        current = get_foreground_window()
        if self._is_valid_target(current):
            return current
        return self._target_hwnd

    def _is_valid_target(self, hwnd: int | None) -> bool:
        if not hwnd or hwnd in self._gui_hwnds or not is_window(hwnd):
            return False
        process_name = get_process_name(get_window_process_id(hwnd)).lower()
        if process_name in self._own_process_names:
            return False
        return True

    def _format_error(self, exc: Exception) -> str:
        text = str(exc)
        if "cublas64_12.dll" in text:
            return "ASR GPU 依赖缺失，已切到 CPU 后请重启再试"
        if "localhost:11434" in text:
            return "Ollama 服务未启动"
        return text[:120] or exc.__class__.__name__

    def _maybe_warm_fast_llm(self) -> None:
        self.app.warm_fast_llm()

    def _maybe_warm_asr(self) -> None:
        self._set_status("预热 ASR", "Working.Status.TLabel")
        self.app.warm_asr()
        self.root.after(500, self._poll_asr_warm)

    def _poll_asr_warm(self) -> None:
        if self._recording:
            return
        if getattr(self.app, "_asr_warm_done", False):
            self._set_status("就绪", "Ready.Status.TLabel")
            return
        self.root.after(500, self._poll_asr_warm)

    def _clear_output_panels(self, value: str = "") -> None:
        self._set_text(self.raw_text, value)
        self._set_text(self.final_text, value)

    def _add_text_panel(
        self,
        parent: tk.Frame,
        label: str,
        height: int = 5,
        expand: bool = True,
        grid: tuple[int, int] | None = None,
        padx: int | tuple[int, int] = 0,
    ) -> tk.Text:
        panel = tk.Frame(
            parent,
            bg=PALETTE["text_bg"],
            highlightthickness=1,
            highlightbackground="#f4d4cd",
            padx=9,
            pady=6,
        )
        if grid is None:
            panel.pack(fill=tk.BOTH, expand=expand, pady=(0, 8))
        else:
            panel.grid(row=grid[0], column=grid[1], sticky=tk.NSEW, padx=padx, pady=(0, 8))
        ttk.Label(panel, text=label, style="PanelLabel.TLabel").pack(anchor=tk.W)

        body = tk.Frame(panel, bg=PALETTE["text_bg"])
        body.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        text = tk.Text(
            body,
            height=height,
            wrap=tk.WORD,
            borderwidth=0,
            highlightthickness=0,
            relief=tk.FLAT,
            bg=PALETTE["text_bg"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["accent"],
            selectbackground=PALETTE["accent_soft"],
            selectforeground=PALETTE["text"],
            font=(FONT_UI, 10),
            padx=0,
            pady=0,
            spacing1=1,
            spacing3=2,
        )
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=text.yview, style="Vertical.TScrollbar")
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        text.configure(state=tk.DISABLED)
        return text

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        widget.configure(state=tk.DISABLED)

    def _update_debug_panels(self, debug: dict[str, object]) -> None:
        raw = str(debug.get("raw_asr_text") or "")
        final = str(debug.get("final_text") or "")
        self._set_text(self.raw_text, raw)
        self._set_text(self.final_text, final)

        asr_model = debug.get("asr_model") or "-"
        asr_device = debug.get("asr_device") or "-"
        llm_model = debug.get("llm_model") or "-"
        asr_ms = debug.get("asr_elapsed_ms")
        asr_load_ms = debug.get("asr_load_ms") or 0
        asr_infer_ms = debug.get("asr_infer_ms") or 0
        llm_ms = debug.get("llm_elapsed_ms")
        fast_escalation = "，主力二审" if debug.get("fast_escalation_applied") else ""
        fallback = "，CPU备用" if debug.get("asr_fallback_used") else ""
        detail_parts = []
        if asr_load_ms:
            detail_parts.append(f"预热加载{asr_load_ms}ms")
        if asr_infer_ms:
            detail_parts.append(f"本次推理{asr_infer_ms}ms")
        detail = f"（{' / '.join(detail_parts)}）" if detail_parts else ""
        self.meta_var.set(
            f"ASR：{asr_model}/{asr_device}{fallback}，{asr_ms or '-'}ms{detail}    "
            f"LLM：{llm_model}{fast_escalation}，{llm_ms or '-'}ms"
        )


def run_gui(app: Any) -> None:
    VoicePromptGui(app).run()
