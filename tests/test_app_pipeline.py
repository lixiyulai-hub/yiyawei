from __future__ import annotations

import logging

from app import VoicePromptCompilerApp, _should_escalate_fast_audit
from src.auditor.schema import AuditResult
from src.safety.risk_checker import RiskChecker
from src.text.transcript_formatter import format_asr_transcript


def test_fast_echo_quality_reason_does_not_escalate_to_main_model():
    assert _should_escalate_fast_audit({"quality_gate_reason": "exact_echo"}) is False
    assert _should_escalate_fast_audit({"quality_gate_reason": "near_echo"}) is False


def test_critical_quality_reasons_still_escalate_to_main_model():
    assert _should_escalate_fast_audit({"quality_gate_reason": "semantic_awkwardness"}) is True
    assert _should_escalate_fast_audit({"quality_gate_reason": "technical_asr_artifact"}) is True
    assert _should_escalate_fast_audit({"quality_gate_reason": "internal_prompt_leak"}) is True
    assert _should_escalate_fast_audit({"quality_gate_reason": "spoken_artifacts_left"}) is True
    assert _should_escalate_fast_audit({"quality_gate_reason": "missing_cleanup_env"}) is True


class _FakeAuditor:
    def __init__(self, final_text: str, reason: str = ""):
        self.final_text = final_text
        self.last_debug = {"quality_gate_reason": reason}
        self.calls: list[tuple[str, str, str]] = []

    def process(self, raw_text: str, mode: str, output_script: str) -> AuditResult:
        self.calls.append((raw_text, mode, output_script))
        return AuditResult(final_text=self.final_text, mode=mode)  # type: ignore[arg-type]


def test_plugin_bridge_text_processing_has_no_paste_or_session_side_effects():
    app = VoicePromptCompilerApp.__new__(VoicePromptCompilerApp)
    app.default_mode = "cursor_prompt"
    app.output_cfg = {"script": "simplified"}
    app.config = {
        "llm": {"provider": "fake", "model": "main"},
        "fast_llm": {"provider": "fake", "model": "fast"},
    }
    app.logger = logging.getLogger("test-plugin-bridge")
    app._auditor_main = _FakeAuditor("main compiled")
    app._auditor_fast = _FakeAuditor("thin", reason="semantic_awkwardness")

    outcome = app.process_text_for_bridge("原始口述", mode="cursor_prompt", use_fast=True)

    assert outcome["result"].final_text == "main compiled"
    assert outcome["record_id"] is None
    assert outcome["pasted"] is False
    assert outcome["meta"]["auto_paste_allowed"] is False
    assert outcome["debug"]["bridge_no_paste"] is True
    assert outcome["debug"]["fast_escalation_applied"] is True
    assert app._auditor_fast.calls == [("原始口述", "cursor_prompt", "simplified")]
    assert app._auditor_main.calls == [("原始口述", "cursor_prompt", "simplified")]


def test_asr_transcript_formatter_only_changes_layout():
    raw_text = "  第一 句。第二句！\r\n\r\nThird line  "

    final_text = format_asr_transcript(raw_text)

    assert final_text == "第一 句。\n\n第二句！\n\nThird line"
    assert "".join(final_text.split()) == "".join(raw_text.split())


def test_pipeline_skips_auditors_when_intelligent_output_is_disabled():
    app = VoicePromptCompilerApp.__new__(VoicePromptCompilerApp)
    app.default_mode = "cursor_prompt"
    app.output_cfg = {"script": "simplified"}
    app.config = {"asr": {"engine": "funasr"}}
    app.injector_cfg = {"auto_paste": False}
    app.safety_cfg = {}
    app.storage = type("Storage", (), {"save": lambda self, record: 7})()
    app.logger = logging.getLogger("test-smart-output")
    app.risk_checker = RiskChecker()
    app._auditor_main = _FakeAuditor("must not run")
    app._auditor_fast = _FakeAuditor("must not run")

    outcome = app.run_pipeline(
        "第一句。第二句。",
        mode="cursor_prompt",
        intelligent_output=False,
    )

    assert outcome["result"].final_text == "第一句。\n\n第二句。"
    assert outcome["debug"]["llm_skipped"] is True
    assert outcome["debug"]["llm_elapsed_ms"] == "-"
    assert app._auditor_main.calls == []
    assert app._auditor_fast.calls == []


def test_pipeline_removes_trailing_completion_phrase_before_audit():
    app = VoicePromptCompilerApp.__new__(VoicePromptCompilerApp)
    app.default_mode = "cursor_prompt"
    app.output_cfg = {"script": "simplified"}
    app.config = {"asr": {"engine": "funasr"}}
    app.injector_cfg = {"auto_paste": False}
    app.safety_cfg = {}
    app.storage = type("Storage", (), {"save": lambda self, record: 9})()
    app.logger = logging.getLogger("test-completion-phrase")
    app.risk_checker = RiskChecker()
    app._auditor_main = _FakeAuditor("compiled prompt")
    app._auditor_fast = _FakeAuditor("compiled prompt")

    app.run_pipeline("请整理这个需求，我说完了。", mode="cursor_prompt")

    assert app._auditor_main.calls == [("请整理这个需求。", "cursor_prompt", "simplified")]
