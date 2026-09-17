#!/usr/bin/env python3
"""
Yiyawei（咿呀喂） - 主入口
按住快捷键说话 → ASR → 本地 LLM 审计 → 剪贴板粘贴
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.auditor.processor import AuditorProcessor
from src.config import load_config
from src.glossary.scanner import GlossaryScanner
from src.injector.paste import paste_text
from src.llm import create_llm_adapter
from src.safety.risk_checker import RiskChecker
from src.storage.db import SessionStorage
from src.text.edit_memory import EditMemoryApplier
from src.text.normalizer import SCRIPT_SIMPLIFIED
from src.text.recording_control import strip_trailing_recording_end_phrase
from src.text.transcript_formatter import format_asr_transcript
from src.utils.logger import setup_logger


def _should_escalate_fast_audit(debug: dict[str, Any]) -> bool:
    reason = str(debug.get("quality_gate_reason") or "")
    if not reason:
        return False
    return reason in {
        "semantic_awkwardness",
        "technical_asr_artifact",
        "internal_prompt_leak",
        "spoken_artifacts_left",
    } or reason.startswith("missing_")


class VoicePromptCompilerApp:
    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        app_cfg = self.config.get("app") or {}
        storage_cfg = self.config.get("storage") or {}
        self.logger = setup_logger(
            level=app_cfg.get("log_level", "INFO"),
            log_dir=storage_cfg.get("log_dir"),
        )
        self.default_mode = app_cfg.get("default_mode", "cursor_prompt")
        self.storage = SessionStorage(storage_cfg.get("db_path", "data/sessions.db"))
        memory_cfg = self.config.get("memory") or {}
        self.memory_applier = EditMemoryApplier(
            self.storage.load_memory_rules(limit=int(memory_cfg.get("max_rules", 500))),
            enabled=bool(memory_cfg.get("enabled", True)),
        )
        self.risk_checker = RiskChecker(
            enabled=(self.config.get("safety") or {}).get("enabled", True)
        )
        glossary_path = (self.config.get("glossary") or {}).get("path")
        self.glossary = GlossaryScanner(glossary_path)
        self._asr = None
        self.injector_cfg = self.config.get("injector") or {}
        self.safety_cfg = self.config.get("safety") or {}
        self.output_cfg = self.config.get("output") or {}
        self.text_processing_cfg = self.config.get("text_processing") or {}

        self._llm_main = create_llm_adapter(self.config.get("llm") or {})
        self._llm_fast = create_llm_adapter(self.config.get("fast_llm") or {})
        self._auditor_main = AuditorProcessor(
            self._llm_main,
            self.glossary,
            self.risk_checker,
            enable_filler_cleaning=self.text_processing_cfg.get("enable_filler_cleaning", True),
            memory_applier=self.memory_applier,
        )
        self._auditor_fast = AuditorProcessor(
            self._llm_fast,
            self.glossary,
            self.risk_checker,
            enable_filler_cleaning=self.text_processing_cfg.get("enable_filler_cleaning", True),
            fast_mode=True,
            memory_applier=self.memory_applier,
        )

        self._recorder = None
        self._current_mode = self.default_mode
        self._use_fast_llm = False
        self._processing = False
        self._fast_llm_warmed = False
        self._asr_warmed = False
        self._asr_warm_done = False

    @property
    def recorder(self):
        if self._recorder is None:
            from src.recorder.recorder import AudioRecorder

            rec_cfg = self.config.get("recorder") or {}
            self._recorder = AudioRecorder(
                sample_rate=rec_cfg.get("sample_rate", 16000),
                channels=rec_cfg.get("channels", 1),
                dtype=rec_cfg.get("dtype", "float32"),
                max_duration_sec=rec_cfg.get("max_duration_sec", 120),
                device=rec_cfg.get("device"),
            )
        return self._recorder

    @property
    def asr(self):
        if self._asr is None:
            from src.asr import create_asr_engine

            self._asr = create_asr_engine(self._resolve_asr_config())
        return self._asr

    def _resolve_asr_config(self) -> dict:
        return dict(self.config.get("asr") or {})

    def run_pipeline(
        self,
        raw_text: str,
        mode: str | None = None,
        use_fast: bool = False,
        intelligent_output: bool = True,
        paste_hwnd: int | None = None,
        output_script: str | None = None,
        allow_paste: bool = True,
    ) -> dict:
        mode = mode or self._current_mode or self.default_mode
        raw_text, _ = strip_trailing_recording_end_phrase(raw_text)
        t0 = time.perf_counter()
        script = output_script or self.output_cfg.get("script", SCRIPT_SIMPLIFIED)
        if intelligent_output:
            auditor = self._auditor_fast if use_fast else self._auditor_main
            llm_cfg_name = "fast_llm" if use_fast else "llm"
            llm_cfg = self.config.get(llm_cfg_name) or {}
            self.logger.info("开始审计 | mode=%s | fast=%s", mode, use_fast)
            result = auditor.process(raw_text, mode=mode, output_script=script)
            fast_elapsed_ms = int((time.perf_counter() - t0) * 1000)
            debug = dict(getattr(auditor, "last_debug", {}) or {})

            if use_fast and _should_escalate_fast_audit(debug):
                fast_reason = str(debug.get("quality_gate_reason") or "")
                fast_final_text = result.final_text
                self.logger.info("极速审计未过质量门槛，切主力模型二审 | reason=%s", fast_reason)
                main_t0 = time.perf_counter()
                main_result = self._auditor_main.process(raw_text, mode=mode, output_script=script)
                main_elapsed_ms = int((time.perf_counter() - main_t0) * 1000)
                main_debug = dict(getattr(self._auditor_main, "last_debug", {}) or {})
                if main_result.final_text.strip():
                    result = main_result
                    debug = main_debug
                    debug["fast_escalation_applied"] = True
                    debug["fast_quality_gate_reason"] = fast_reason
                    debug["fast_final_text"] = fast_final_text
                    debug["fast_llm_elapsed_ms"] = fast_elapsed_ms
                    debug["main_llm_elapsed_ms"] = main_elapsed_ms
                    llm_cfg_name = "llm"
                    llm_cfg = self.config.get("llm") or {}
        else:
            from src.auditor.schema import AuditResult

            llm_cfg = {}
            result = self.risk_checker.merge_with_result(
                AuditResult(final_text=format_asr_transcript(raw_text), mode=mode),
                raw_text,
            )
            debug = {"intelligent_output": False, "llm_skipped": True}
            self.logger.info("智能输出已关闭，跳过 LLM 审计 | mode=%s", mode)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        self.logger.info("审计完成 | %s", self.risk_checker.describe(result))
        self.logger.info("final_text: %s", result.final_text)

        pasted = False
        should_paste = bool(allow_paste) and self.injector_cfg.get("auto_paste", True)

        if result.risk_level == "high" and self.safety_cfg.get("block_auto_paste_on_high_risk", False):
            self.logger.warning("高风险内容已按配置阻止自动粘贴: %s", result.final_text)
            should_paste = False
        elif result.need_confirm and self.injector_cfg.get("confirm_in_console", False):
            self.logger.warning("需要确认 (risk=%s): %s", result.risk_level, result.final_text)
            answer = input("是否粘贴到当前输入框? [y/N]: ").strip().lower()
            should_paste = answer in ("y", "yes", "是")

        if should_paste and result.final_text:
            pasted = paste_text(
                result.final_text,
                restore_clipboard=self.injector_cfg.get("restore_clipboard", True),
                delay_ms=self.injector_cfg.get("paste_delay_ms", 150),
                target_hwnd=paste_hwnd,
            )
            if pasted:
                self.logger.info("已粘贴到当前输入框")
            else:
                self.logger.error("粘贴失败，文本已在上方日志输出")

        record = {
            "raw_asr_text": raw_text,
            "final_text": result.final_text,
            "mode": result.mode,
            "asr_engine": (self.config.get("asr") or {}).get("engine", "funasr"),
            "llm_provider": llm_cfg.get("provider", ""),
            "llm_model": llm_cfg.get("model", ""),
            "processing_time_ms": elapsed_ms,
            "corrections": [c.model_dump(by_alias=True) for c in result.corrections],
            "deleted_segments": result.deleted_segments,
            "constraints": result.constraints,
            "risk_level": result.risk_level,
            "need_confirm": result.need_confirm,
            "pasted_success": pasted,
        }
        sid = self.storage.save(record)
        self.logger.info("已保存会话 #%s", sid)
        debug.update(
            {
                "final_text": result.final_text,
                "llm_model": llm_cfg.get("model", ""),
                "llm_provider": llm_cfg.get("provider", ""),
                "llm_elapsed_ms": elapsed_ms if intelligent_output else "-",
                "mode": result.mode,
                "risk_level": result.risk_level,
                "intelligent_output": intelligent_output,
            }
        )
        return {"result": result, "record_id": sid, "pasted": pasted, "debug": debug}

    def confirm_edit(
        self,
        *,
        record_id: int | None,
        source_kind: str,
        before_text: str,
        after_text: str,
        mode: str = "",
        output_script: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        outcome = self.storage.save_confirmed_edit(
            session_id=record_id,
            source_kind=source_kind,
            before_text=before_text,
            after_text=after_text,
            mode=mode,
            output_script=output_script,
            metadata=metadata,
        )
        memory_cfg = self.config.get("memory") or {}
        self.memory_applier.replace_rules(
            self.storage.load_memory_rules(limit=int(memory_cfg.get("max_rules", 500)))
        )
        return {"ok": True, **outcome}

    def process_text_for_bridge(
        self,
        raw_text: str,
        mode: str = "cursor_prompt",
        *,
        use_fast: bool = False,
        output_script: str | None = None,
    ) -> dict:
        """Process text for plugin callers without paste or session writes."""
        mode = mode or self.default_mode
        auditor = self._auditor_fast if use_fast else self._auditor_main
        llm_cfg_name = "fast_llm" if use_fast else "llm"
        llm_cfg = self.config.get(llm_cfg_name) or {}
        script = output_script or self.output_cfg.get("script", SCRIPT_SIMPLIFIED)

        self.logger.info("plugin bridge audit start | mode=%s | fast=%s", mode, use_fast)
        t0 = time.perf_counter()
        result = auditor.process(raw_text, mode=mode, output_script=script)
        fast_elapsed_ms = int((time.perf_counter() - t0) * 1000)
        debug = dict(getattr(auditor, "last_debug", {}) or {})

        if use_fast and _should_escalate_fast_audit(debug):
            fast_reason = str(debug.get("quality_gate_reason") or "")
            fast_final_text = result.final_text
            self.logger.info(
                "plugin bridge fast audit escalated to main model | reason=%s",
                fast_reason,
            )
            main_t0 = time.perf_counter()
            main_result = self._auditor_main.process(raw_text, mode=mode, output_script=script)
            main_elapsed_ms = int((time.perf_counter() - main_t0) * 1000)
            main_debug = dict(getattr(self._auditor_main, "last_debug", {}) or {})
            if main_result.final_text.strip():
                result = main_result
                debug = main_debug
                debug["fast_escalation_applied"] = True
                debug["fast_quality_gate_reason"] = fast_reason
                debug["fast_final_text"] = fast_final_text
                debug["fast_llm_elapsed_ms"] = fast_elapsed_ms
                debug["main_llm_elapsed_ms"] = main_elapsed_ms
                llm_cfg_name = "llm"
                llm_cfg = self.config.get("llm") or {}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        debug.update(
            {
                "final_text": result.final_text,
                "llm_model": llm_cfg.get("model", ""),
                "llm_provider": llm_cfg.get("provider", ""),
                "llm_elapsed_ms": elapsed_ms,
                "mode": result.mode,
                "risk_level": result.risk_level,
                "bridge_no_paste": True,
            }
        )
        return {
            "result": result,
            "record_id": None,
            "pasted": False,
            "debug": debug,
            "meta": {
                "llm_model": llm_cfg.get("model", ""),
                "llm_provider": llm_cfg.get("provider", ""),
                "llm_elapsed_ms": elapsed_ms,
                "used_fast": use_fast,
                "auto_paste_allowed": False,
            },
        }

    def process_audio(
        self,
        audio,
        mode: str | None = None,
        use_fast: bool = False,
        intelligent_output: bool = True,
        paste_hwnd: int | None = None,
        output_script: str | None = None,
        allow_paste: bool = True,
    ) -> dict | None:
        if self._processing:
            self.logger.warning("上一段仍在处理中，请稍候")
            return
        self._processing = True
        try:
            self.logger.info("ASR 识别中...")
            t0 = time.perf_counter()
            raw = self.asr.transcribe_array(audio, self.recorder.sample_rate)
            if getattr(self.asr, "config", {}).get("fallback_used"):
                reason = getattr(self.asr, "config", {}).get("fallback_reason") or "CUDA ASR 不可用"
                self.logger.warning("%s，已切换到 CPU 备用模式。", reason)
            asr_ms = int((time.perf_counter() - t0) * 1000)
            asr_cfg = getattr(self.asr, "config", {}) or {}
            self.logger.info("ASR 完成 (%dms): %s", asr_ms, raw)
            if not raw.strip():
                self.logger.warning("未识别到有效语音")
                return None
            outcome = self.run_pipeline(
                raw,
                mode=mode,
                use_fast=use_fast,
                intelligent_output=intelligent_output,
                paste_hwnd=paste_hwnd,
                output_script=output_script,
                allow_paste=allow_paste,
            )
            outcome.setdefault("debug", {})
            outcome["debug"].update(
                {
                    "raw_asr_text": raw,
                    "asr_elapsed_ms": asr_ms,
                    "asr_engine": asr_cfg.get("engine", "funasr"),
                    "asr_model": getattr(self.asr, "model_name", asr_cfg.get("model", "")),
                    "asr_device": getattr(self.asr, "device", asr_cfg.get("device", "")),
                    "asr_compute_type": getattr(self.asr, "compute_type", asr_cfg.get("compute_type", "")),
                    "asr_fallback_used": bool(asr_cfg.get("fallback_used")),
                    "asr_load_ms": getattr(self.asr, "last_load_ms", 0),
                    "asr_infer_ms": getattr(self.asr, "last_infer_ms", 0),
                }
            )
            return outcome
        except Exception as e:
            self.logger.exception("处理失败: %s", e)
            raise
        finally:
            self._processing = False
        return None

    def warm_fast_llm(self) -> None:
        if self._fast_llm_warmed:
            return
        self._fast_llm_warmed = True

        def warm() -> None:
            try:
                self.logger.info("预热极速模型...")
                self._llm_fast.generate(
                    "返回 JSON: {\"final_text\":\"就绪\",\"mode\":\"cursor_prompt\"}",
                    system="你是快速 JSON 输出器，只返回最小 JSON。",
                    options={"max_tokens": 24, "num_ctx": 512, "temperature": 0},
                )
                self.logger.info("极速模型预热完成")
            except Exception as exc:
                self.logger.warning("极速模型预热失败: %s", exc)

        threading.Thread(target=warm, daemon=True).start()

    def warm_asr(self) -> None:
        if self._asr_warmed:
            return
        self._asr_warmed = True

        def warm() -> None:
            try:
                self.logger.info("预热 ASR 模型...")
                t0 = time.perf_counter()
                warm = getattr(self.asr, "warm", None)
                if callable(warm):
                    warm()
                else:
                    _ = self.asr
                elapsed = int((time.perf_counter() - t0) * 1000)
                self.logger.info(
                    "ASR 模型预热完成 | model=%s device=%s elapsed=%dms",
                    getattr(self.asr, "model_name", ""),
                    getattr(self.asr, "device", ""),
                    elapsed,
                )
            except Exception as exc:
                self.logger.warning("ASR 模型预热失败: %s", exc)
            finally:
                self._asr_warm_done = True

        threading.Thread(target=warm, daemon=True).start()

    def _make_hold_controller(self, mode: str, use_fast: bool = False):
        from src.recorder.recorder import HoldToRecordController

        def on_start():
            self._current_mode = mode
            self._use_fast_llm = use_fast
            self.logger.info("录音开始 [%s]", mode)

        def on_complete(audio):
            self.logger.info("录音结束，开始处理...")
            self.process_audio(audio, mode=mode, use_fast=use_fast)

        return HoldToRecordController(
            self.recorder,
            on_complete=on_complete,
            on_start=on_start,
        )

    def run_hotkeys(self) -> None:
        from src.hotkey.listener import HotkeyListener

        hotkeys = self.config.get("hotkeys") or {}
        listener = HotkeyListener()

        bindings = [
            (hotkeys.get("professional", "alt+space"), self.default_mode, False),
            (hotkeys.get("fast", "alt+shift+space"), self.default_mode, True),
            (hotkeys.get("cursor", "alt+c"), "cursor_prompt", False),
            (hotkeys.get("terminal", "alt+t"), "terminal_command", False),
        ]

        controllers = {}

        for combo, mode, use_fast in bindings:
            if not combo:
                continue
            ctrl = self._make_hold_controller(mode, use_fast)

            def make_press(c=ctrl):
                return c.on_press

            def make_release(c=ctrl):
                return c.on_release

            listener.register_hold(combo, make_press(), make_release())
            self.logger.info("已注册快捷键: %s → mode=%s fast=%s", combo, mode, use_fast)

        self.logger.info("Yiyawei（咿呀喂）已启动，按住快捷键说话，松开结束。")
        self.logger.info("建议以管理员身份运行以确保全局快捷键生效。")
        try:
            listener.run_forever()
        except KeyboardInterrupt:
            self.logger.info("退出")
        finally:
            listener.stop()
            self.recorder.close()


def main():
    parser = argparse.ArgumentParser(description="Yiyawei（咿呀喂）")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--text", default=None, help="跳过 ASR，直接审计文本")
    parser.add_argument("--mode", default=None, help="输出模式")
    parser.add_argument("--fast", action="store_true", help="使用 fast_llm")
    parser.add_argument("--gui", action="store_true", help="启动桌面 Web 玻璃界面")
    parser.add_argument("--tk-gui", action="store_true", help="启动旧版 Tk 小窗口")
    parser.add_argument("--script", default=None, help="输出文字: simplified | traditional | auto")
    parser.add_argument("--daemon", action="store_true", help="Start experimental local plugin HTTP daemon")
    parser.add_argument("--daemon-host", default="127.0.0.1", help="Plugin daemon host, loopback only")
    parser.add_argument("--daemon-port", type=int, default=17890, help="Plugin daemon port")
    parser.add_argument("--daemon-token", default=None, help="Optional bearer token for plugin daemon")
    args = parser.parse_args()

    app = VoicePromptCompilerApp(config_path=args.config)

    if args.daemon:
        from src.plugin_bridge.bridge import PluginBridge, PluginBridgeConfig
        from src.plugin_bridge.http_daemon import create_server

        bridge = PluginBridge(
            app.process_text_for_bridge,
            PluginBridgeConfig(
                enabled=True,
                host=args.daemon_host,
                ipc_port=args.daemon_port,
                auth_token=args.daemon_token,
            ),
        )
        server = create_server(bridge)
        server.start()
        app.logger.info("Plugin bridge daemon listening at %s", server.url)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            app.logger.info("Plugin bridge daemon exiting")
        finally:
            server.shutdown()
        return

    if args.text:
        app.run_pipeline(args.text, mode=args.mode, use_fast=args.fast, output_script=args.script)
        return

    if args.tk_gui:
        from src.gui.simple_gui import run_gui

        run_gui(app)
        return

    if args.gui:
        from src.gui.web_gui import run_gui

        run_gui(app)
        return

    app.run_hotkeys()


if __name__ == "__main__":
    main()
