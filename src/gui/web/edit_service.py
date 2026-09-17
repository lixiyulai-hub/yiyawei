"""Edit confirmation service for the local web GUI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from src.gui.web.contracts import WebGuiState


class EditHost(Protocol):
    app: Any
    state: WebGuiState
    _lock: Any
    _recording: bool
    _processing: bool
    _confirm_target_hwnd: int | None
    _target_hwnd: int | None
    _last_debug: dict[str, Any]

    def _restore_browser_window_position(self) -> None: ...


PasteText = Callable[..., bool]
ParseRecordId = Callable[[str | int | None], int | None]
Now = Callable[[], float]


class EditService:
    """Own edit confirmation while preserving the controller contract."""

    def __init__(self, host: EditHost):
        self.host = host

    def confirm_text(
        self,
        payload: dict[str, Any],
        *,
        paste_text: PasteText,
        parse_record_id: ParseRecordId,
        now: Now,
    ) -> dict[str, Any]:
        host = self.host
        with host._lock:
            if host._recording or host._processing:
                return {"ok": False, "error": "当前正在录音或处理中，暂不能确认。", "state": host.state.to_dict()}
            if host.state.phase != "done":
                return {"ok": False, "error": "没有可确认的输出。", "state": host.state.to_dict()}
            scope = str(payload.get("scope") or "final").strip().lower()
            if scope not in {"raw", "final"}:
                scope = "final"
            base_raw = str(payload.get("baseRawText") or "")
            base_final = str(payload.get("baseFinalText") or "")
            if scope == "raw" and base_raw and base_raw != host.state.raw_text:
                return {"ok": False, "error": "识别原文已变化，请先恢复或重新确认。", "state": host.state.to_dict()}
            if scope == "final" and base_final and base_final != host.state.final_text:
                return {"ok": False, "error": "输出已变化，请先恢复或重新确认。", "state": host.state.to_dict()}
            raw_text = str(payload.get("rawText") or "").strip()
            final_text = str(payload.get("finalText") or "").strip()
            if scope == "raw" and not raw_text:
                return {"ok": False, "error": "识别原文不能为空。", "state": host.state.to_dict()}
            if scope == "final" and not final_text:
                return {"ok": False, "error": "最终输出不能为空。", "state": host.state.to_dict()}
            before_raw = host.state.raw_text
            before_final = host.state.final_text
            record_id = parse_record_id(host.state.record_id)
            mode = host.state.mode
            output_script = host.state.output_script
            target_hwnd = host._confirm_target_hwnd or host._target_hwnd
            debug_snapshot = dict(host._last_debug)

        learned: list[dict[str, Any]] = []
        if raw_text and raw_text != before_raw:
            outcome = host.app.confirm_edit(
                record_id=record_id,
                source_kind="asr_text",
                before_text=before_raw,
                after_text=raw_text,
                mode=mode,
                output_script=output_script,
                metadata={"source": "web_gui", "debug": debug_snapshot},
            )
            learned.extend(outcome.get("learned_rules") or [])
        if scope == "final" and final_text != before_final:
            outcome = host.app.confirm_edit(
                record_id=record_id,
                source_kind="final_output",
                before_text=before_final,
                after_text=final_text,
                mode=mode,
                output_script=output_script,
                metadata={"source": "web_gui", "debug": debug_snapshot},
            )
            learned.extend(outcome.get("learned_rules") or [])

        pasted = False
        if scope == "final":
            pasted = paste_text(
                final_text,
                restore_clipboard=host.app.injector_cfg.get("restore_clipboard", True),
                delay_ms=host.app.injector_cfg.get("paste_delay_ms", 150),
                target_hwnd=target_hwnd,
            )
            if pasted:
                host._restore_browser_window_position()
        with host._lock:
            host.state.raw_text = raw_text or before_raw
            if scope == "final":
                host.state.final_text = final_text
            host.state.pasted = bool(pasted)
            if scope == "raw":
                host.state.status = "已保存识别修正"
            else:
                host.state.status = "已确认并粘贴" if pasted else "已确认，粘贴失败"
            host.state.updated_at = now()
            return {
                "ok": True,
                "state": host.state.to_dict(),
                "pasted": bool(pasted),
                "scope": scope,
                "learnedRules": learned,
            }
