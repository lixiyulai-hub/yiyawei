"""口语审计处理器。"""

from __future__ import annotations

import json
import re
from typing import Any

from src.auditor.prompt import (
    FAST_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_fast_revision_prompt,
    build_fast_user_prompt,
    build_revision_prompt,
    build_user_prompt,
)
from src.auditor.intent_frame import looks_like_product_plan_with_visual_subtask
from src.auditor.schema import AuditResult, CorrectionItem
from src.auditor.task_compiler import (
    compile_ai_task_fallback,
    looks_like_browser_annotation_feature_request,
    looks_like_project_evaluation_build_request,
    remove_task_boilerplate,
    should_compile_ai_task_fallback,
)
from src.auditor.task_router import build_route_context, detect_task_route, required_domain_terms
from src.glossary.scanner import GlossaryScanner
from src.llm.base import BaseLLMAdapter
from src.safety.risk_checker import RiskChecker
from src.text.filler_cleaner import clean_fillers
from src.text.edit_memory import EditMemoryApplier
from src.text.normalizer import SCRIPT_SIMPLIFIED, normalize_output_text
from src.text.recording_control import strip_trailing_recording_end_phrase
from src.text.self_correction import repair_spoken_self_corrections


class AuditorProcessor:
    def __init__(
        self,
        llm: BaseLLMAdapter,
        glossary: GlossaryScanner | None = None,
        risk_checker: RiskChecker | None = None,
        enable_filler_cleaning: bool = True,
        fast_mode: bool = False,
        memory_applier: EditMemoryApplier | None = None,
    ):
        self.llm = llm
        self.glossary = glossary or GlossaryScanner()
        self.risk_checker = risk_checker or RiskChecker()
        self.enable_filler_cleaning = enable_filler_cleaning
        self.fast_mode = fast_mode
        self.memory_applier = memory_applier
        self.last_debug: dict[str, Any] = {}

    def process(
        self,
        raw_text: str,
        mode: str = "cursor_prompt",
        output_script: str = SCRIPT_SIMPLIFIED,
    ) -> AuditResult:
        raw_text = (raw_text or "").strip()
        if not raw_text:
            return AuditResult(final_text="", mode=mode)  # type: ignore[arg-type]

        audit_text = normalize_output_text(raw_text, SCRIPT_SIMPLIFIED, punctuate=False) or raw_text

        self_corrected_text, self_corrections = repair_spoken_self_corrections(audit_text)
        memory_applied: tuple[dict[str, str], ...] = ()
        if self.memory_applier is not None:
            memory_result = self.memory_applier.apply(self_corrected_text, mode, output_script)
            self_corrected_text = memory_result.text
            memory_applied = memory_result.applied
        cleaned_text = clean_fillers(self_corrected_text) if self.enable_filler_cleaning else self_corrected_text
        cleaned_text, recording_end_phrase = strip_trailing_recording_end_phrase(cleaned_text)
        route = detect_task_route(cleaned_text)
        route_context = build_route_context(cleaned_text, route=route) if mode in {"cursor_prompt", "ai_chat"} else ""
        intent_frame = route.intent_frame
        self.last_debug = {
            "raw_asr_text": raw_text,
            "asr_audit_text": audit_text,
            "corrected_text": self_corrected_text,
            "cleaned_text": cleaned_text,
            "intent_frame": intent_frame.to_dict() if intent_frame else {},
            "route": {
                "task_type": route.task_type,
                "task_label": route.task_label,
                "domain": route.domain,
                "domain_label": route.domain_label,
                "task_score": route.task_score,
                "domain_score": route.domain_score,
                "examples": [
                    {
                        "user_pattern": example.user_pattern,
                        "final_text_outline": example.final_text_outline,
                    }
                    for example in route.examples
                ],
                "template_fragments": route_context.splitlines() if route_context else [],
            },
            "route_context": route_context,
            "recording_end_phrase_removed": recording_end_phrase,
            "self_corrections": [
                {"from": item.source, "to": item.target} for item in self_corrections
            ],
            "memory_applied": list(memory_applied),
            "llm_raw_response": "",
            "llm_revision_raw_response": "",
            "fast_revision_applied": False,
            "revision_applied": False,
            "rule_task_fallback_used": False,
            "quality_gate_reason": "",
            "quality_gate_last_reason": "",
            "quality_gate_stage": "",
            "quality_gate_origin": "",
            "quality_gate_recommended_repair": "",
            "quality_gate_repair_applied": "",
            "quality_gate_attribution": {},
            "quality_gate_history": [],
        }

        glossary_hints = self.glossary.build_hints(cleaned_text)
        pre_risk = self.risk_checker.pre_scan(cleaned_text)
        self.last_debug["pre_risk"] = {
            "risk_level": pre_risk.risk_level,
            "need_confirm": pre_risk.need_confirm,
            "hits": pre_risk.hits,
            "summary": pre_risk.summary,
        }

        applied_corrections = [
            {"from": item.source, "to": item.target} for item in self_corrections
        ]

        if self.fast_mode:
            user_prompt = build_fast_user_prompt(
                raw_text=cleaned_text,
                mode=mode,
                output_script=output_script,
                original_asr_text=raw_text,
                preprocessing_notes=applied_corrections,
                glossary_hints=glossary_hints,
                route_context=route_context,
                pre_scan_risk=pre_risk.summary,
            )
            system_prompt = FAST_SYSTEM_PROMPT
        else:
            user_prompt = build_user_prompt(
                raw_text=cleaned_text,
                mode=mode,
                glossary_hints=glossary_hints,
                pre_scan_risk=pre_risk.summary,
                output_script=output_script,
                original_asr_text=raw_text,
                preprocessing_notes=applied_corrections,
                route_context=route_context,
            )
            system_prompt = SYSTEM_PROMPT

        raw_response = self.llm.generate(user_prompt, system=system_prompt)
        self.last_debug["llm_raw_response"] = raw_response
        result = self._parse_response(raw_response, mode, cleaned_text)
        if mode in {"cursor_prompt", "ai_chat"}:
            self._apply_output_guards(result, cleaned_text)

        if self.fast_mode and self._needs_revision(cleaned_text, result.final_text, mode):
            revision_prompt = build_fast_revision_prompt(
                raw_text=raw_text,
                cleaned_text=cleaned_text,
                first_final_text=result.final_text,
                mode=mode,
                output_script=output_script,
                route_context=route_context,
            )
            revision_response = self.llm.generate(
                revision_prompt,
                system=FAST_SYSTEM_PROMPT,
                options={"temperature": 0.1, "max_tokens": 360, "num_ctx": 2048},
            )
            self.last_debug["llm_revision_raw_response"] = revision_response
            revised = self._parse_response(revision_response, mode, result.final_text or cleaned_text)
            if revision_response.strip() and revised.final_text.strip():
                revised.semantic_diagnosis.extend(result.semantic_diagnosis)
                revised.output_requirements.extend(result.output_requirements)
                revised.corrections.extend(result.corrections)
                revised.deleted_segments.extend(result.deleted_segments)
                revised.constraints.extend(result.constraints)
                revised.uncertain_terms.extend(result.uncertain_terms)
                result = revised
                self.last_debug["fast_revision_applied"] = True
                self._mark_quality_gate_repair_applied("fast_revision")

        if not self.fast_mode and self._needs_revision(cleaned_text, result.final_text, mode):
            revision_prompt = build_revision_prompt(
                raw_text=raw_text,
                cleaned_text=cleaned_text,
                first_final_text=result.final_text,
                mode=mode,
                output_script=output_script,
                route_context=route_context,
            )
            revision_response = self.llm.generate(
                revision_prompt,
                system=SYSTEM_PROMPT,
                options={"temperature": 0.2},
            )
            self.last_debug["llm_revision_raw_response"] = revision_response
            revised = self._parse_response(revision_response, mode, result.final_text or cleaned_text)
            if revision_response.strip() and revised.final_text.strip():
                revised.semantic_diagnosis.extend(result.semantic_diagnosis)
                revised.output_requirements.extend(result.output_requirements)
                revised.corrections.extend(result.corrections)
                revised.deleted_segments.extend(result.deleted_segments)
                revised.constraints.extend(result.constraints)
                revised.uncertain_terms.extend(result.uncertain_terms)
                result = revised
                self.last_debug["revision_applied"] = True
                self._mark_quality_gate_repair_applied("revision")

        if mode in {"cursor_prompt", "ai_chat"}:
            self._apply_output_guards(result, cleaned_text)

        if self._needs_revision(cleaned_text, result.final_text, mode):
            quality_gate_reason = self.last_debug.get("quality_gate_reason", "")
            fallback_text = compile_ai_task_fallback(cleaned_text)
            if fallback_text:
                result.final_text = fallback_text
                result.uncertain_terms.append("rule_task_fallback_used")
                result.semantic_diagnosis.append("LLM 输出未通过质量门槛，已使用规则兜底重建 final_text。")
                self.last_debug["rule_task_fallback_used"] = True
                self.last_debug["quality_gate_reason"] = ""
                self._mark_quality_gate_repair_applied("rule_task_fallback")
            elif quality_gate_reason == "misrouted_project_evaluation_expansion":
                result.final_text = cleaned_text
                result.uncertain_terms.append("quality_gate_plain_text_fallback")
                result.semantic_diagnosis.append("LLM 输出被判定为误路由扩写，且原文不是可编译任务，已回退为清理后的原话。")
                self.last_debug["quality_gate_reason"] = ""
                self._mark_quality_gate_repair_applied("plain_text_fallback")
        else:
            self.last_debug["rule_task_fallback_used"] = False

        if mode in {"cursor_prompt", "ai_chat"}:
            result.final_text = remove_task_boilerplate(result.final_text)

        result.final_text = normalize_output_text(
            result.final_text,
            output_script,
            punctuate=(mode != "terminal_command"),
        )
        if mode in {"cursor_prompt", "ai_chat"} and output_script == SCRIPT_SIMPLIFIED:
            simplified_final = normalize_output_text(result.final_text, SCRIPT_SIMPLIFIED, punctuate=False)
            if _has_traditional_cjk(simplified_final, result.final_text):
                result.uncertain_terms.append("non_simplified_final_text")
        for item in self_corrections:
            result.corrections.append(
                CorrectionItem(**{"from": item.source, "to": item.target, "reason": item.reason})
            )
        self.last_debug["final_text"] = result.final_text
        self.last_debug["intent_summary"] = result.intent_summary
        self.last_debug["semantic_diagnosis"] = result.semantic_diagnosis
        self.last_debug["output_requirements"] = result.output_requirements

        # 规则层补强风险
        merged = self.risk_checker.merge_with_result(result, f"{raw_text}\n{cleaned_text}")
        if mode == "terminal_command" and merged.risk_level == "low":
            merged.risk_level = "medium"
            merged.need_confirm = True

        return merged

    def _parse_response(self, raw: str, default_mode: str, original_text: str = "") -> AuditResult:
        text = (raw or "").strip()
        parsed = self._extract_json(text)
        if parsed:
            result = self._from_dict(parsed, default_mode)
            if not result.final_text.strip() and original_text.strip():
                result.final_text = original_text.strip()
                result.uncertain_terms.append("empty_final_text_fallback")
            return result

        jsonish_final_text = _extract_final_text_from_jsonish_payload(text)
        if jsonish_final_text:
            return AuditResult(
                final_text=jsonish_final_text,
                mode=default_mode,  # type: ignore[arg-type]
                semantic_diagnosis=["LLM returned JSON-like text; extracted final prompt field."],
                uncertain_terms=["jsonish_final_text_extracted"],
            )

        # fallback: 整段当 final_text
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        if not cleaned and original_text.strip():
            cleaned = original_text.strip()
        return AuditResult(
            final_text=cleaned,
            mode=default_mode,  # type: ignore[arg-type]
            semantic_diagnosis=["LLM did not return valid JSON; raw response used as fallback."],
            uncertain_terms=["json_parse_failed"],
        )

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        # 直接 parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 提取 {...}
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None

    def _from_dict(self, data: dict[str, Any], default_mode: str) -> AuditResult:
        corrections_raw = data.get("corrections") or []
        corrections: list[CorrectionItem] = []
        for item in corrections_raw:
            if not isinstance(item, dict):
                continue
            frm = item.get("from") or item.get("from_") or ""
            corrections.append(
                CorrectionItem(
                    **{
                        "from": frm,
                        "to": item.get("to", ""),
                        "reason": item.get("reason", ""),
                    }
                )
            )

        mode = data.get("mode") or default_mode
        final_text = _extract_final_text_from_payload(data)
        return AuditResult(
            final_text=final_text,
            mode=mode,  # type: ignore[arg-type]
            intent_summary=str(data.get("intent_summary") or "").strip(),
            semantic_diagnosis=_coerce_string_list(data.get("semantic_diagnosis")),
            output_requirements=_coerce_string_list(data.get("output_requirements")),
            deleted_segments=_coerce_string_list(data.get("deleted_segments")),
            corrections=corrections,
            constraints=_coerce_string_list(data.get("constraints")),
            uncertain_terms=_coerce_string_list(data.get("uncertain_terms")),
            risk_level=data.get("risk_level") or "low",  # type: ignore[arg-type]
            need_confirm=bool(data.get("need_confirm", False)),
        )

    def _needs_revision(self, cleaned_text: str, final_text: str, mode: str) -> bool:
        if mode not in {"cursor_prompt", "ai_chat"}:
            return False
        verdict = _audit_final_text_quality(cleaned_text, final_text)
        if verdict:
            attribution = _build_quality_gate_attribution(
                verdict,
                cleaned_text,
                final_text,
                self.last_debug,
            )
            self.last_debug["quality_gate_reason"] = verdict
            self.last_debug["quality_gate_last_reason"] = verdict
            self.last_debug["quality_gate_stage"] = attribution["stage"]
            self.last_debug["quality_gate_origin"] = attribution["origin"]
            self.last_debug["quality_gate_recommended_repair"] = attribution["recommended_repair"]
            self.last_debug["quality_gate_attribution"] = attribution
            history = self.last_debug.setdefault("quality_gate_history", [])
            if isinstance(history, list):
                history.append(attribution)
            return True
        self.last_debug["quality_gate_reason"] = ""
        return False

    def _mark_quality_gate_repair_applied(self, repair: str) -> None:
        if not self.last_debug.get("quality_gate_history"):
            return
        self.last_debug["quality_gate_repair_applied"] = repair
        attribution = self.last_debug.get("quality_gate_attribution")
        if isinstance(attribution, dict) and attribution:
            attribution["repair_applied"] = repair
        history = self.last_debug.get("quality_gate_history")
        if isinstance(history, list) and history:
            last = history[-1]
            if isinstance(last, dict):
                last["repair_applied"] = repair

    def _apply_output_guards(self, result: AuditResult, cleaned_text: str) -> None:
        fixed_text, general_text_fixes = _apply_general_text_fixes(result.final_text)
        if general_text_fixes:
            result.final_text = fixed_text
            if "已应用通用语法兜底，修复明显病句。" not in result.semantic_diagnosis:
                result.semantic_diagnosis.append("已应用通用语法兜底，修复明显病句。")
            existing = list(self.last_debug.get("general_text_fixes") or [])
            self.last_debug["general_text_fixes"] = _dedupe(existing + general_text_fixes)

        restored_text, restored_tail = _restore_spoken_casual_tail(result.final_text, cleaned_text)
        if restored_tail:
            result.final_text = restored_text
            if "已保留用户主动说出的自然礼貌句或轻松评价句。" not in result.semantic_diagnosis:
                result.semantic_diagnosis.append("已保留用户主动说出的自然礼貌句或轻松评价句。")
            self.last_debug["restored_casual_tail"] = restored_tail


def _audit_final_text_quality(cleaned_text: str, final_text: str) -> str:
    cleaned = _compact_for_similarity(cleaned_text)
    final = _compact_for_similarity(final_text)
    visual_subtask_misroute = _misrouted_visual_subtask_as_primary(cleaned_text, final_text)
    if visual_subtask_misroute:
        return visual_subtask_misroute
    misroute = _misrouted_project_expansion(cleaned_text, final_text)
    if misroute:
        return misroute
    missing_project_plan = _missing_project_evaluation_context(cleaned_text, final_text)
    if missing_project_plan:
        return missing_project_plan
    if len(cleaned) < 18 or len(final) < 18:
        return ""
    if _leaks_internal_prompt(final_text):
        return "internal_prompt_leak"
    if _looks_like_json_or_schema_leak(final_text):
        return "json_or_schema_leak"
    if _miscompiled_software_feedback_prompt(cleaned_text, final_text):
        return "software_feedback_prompt_leak"
    missing_browser_annotation_feature = _missing_browser_annotation_feature_context(cleaned_text, final_text)
    if missing_browser_annotation_feature:
        return missing_browser_annotation_feature
    missing_status = _missing_status_report_facts(cleaned_text, final_text)
    if missing_status:
        return missing_status
    missing_test_guidance = _missing_test_guidance_context(cleaned_text, final_text)
    if missing_test_guidance:
        return missing_test_guidance
    missing_feedback = _missing_software_feedback_context(cleaned_text, final_text)
    if missing_feedback:
        return missing_feedback
    if _has_obvious_semantic_awkwardness(final_text):
        return "semantic_awkwardness"
    if _has_suspicious_tech_asr_artifacts(final_text):
        return "technical_asr_artifact"
    if _looks_like_compiled_status_report(final_text):
        return ""
    if _has_task_structure(final_text):
        return ""
    if _looks_like_task_request(cleaned_text) and _looks_like_uncompiled_speech(final_text):
        return "spoken_artifacts_left"
    if cleaned == final and _echo_requires_revision(cleaned_text):
        return "exact_echo"
    ratio = _lcs_ratio(cleaned, final)
    if ratio >= 0.82 and _echo_requires_revision(cleaned_text):
        return "near_echo"
    return ""


def _build_quality_gate_attribution(
    reason: str,
    cleaned_text: str,
    final_text: str,
    debug: dict[str, Any],
) -> dict[str, Any]:
    route = debug.get("route") if isinstance(debug.get("route"), dict) else {}
    frame = debug.get("intent_frame") if isinstance(debug.get("intent_frame"), dict) else {}
    task_type = str(route.get("task_type") or "")
    artifact_type = str(frame.get("artifact_type") or "")
    task_hint = str(frame.get("task_hint") or "")

    stage = "quality_gate"
    origin = "llm_output"
    repair = "revision"

    if reason in {"exact_echo", "near_echo", "spoken_artifacts_left"}:
        stage = "post_llm_echo_check"
        origin = "llm_echo_or_undercompiled_output"
        repair = "rule_task_fallback" if _has_rule_fallback_path(cleaned_text) else "revision"
    elif reason in {"internal_prompt_leak", "json_or_schema_leak"}:
        stage = "prompt_leak_guard"
        origin = "llm_internal_template_or_schema_leak"
        repair = "rule_task_fallback" if _has_rule_fallback_path(cleaned_text) else "revision"
    elif (
        reason in {"software_feedback_prompt_leak"}
        or reason.startswith("missing_software_feedback")
        or reason.startswith("software_feedback")
    ):
        stage = "software_feedback_guard"
        origin = "compiler_or_llm_missed_software_feedback"
        repair = "rule_task_fallback"
    elif reason.startswith("missing_project_evaluation") or reason == "project_evaluation_too_thin":
        stage = "project_evaluation_guard"
        origin = "llm_output_missing_project_evaluation_sections"
        repair = "rule_task_fallback"
    elif reason == "misrouted_project_evaluation_expansion":
        stage = "plain_text_overexpansion_guard"
        origin = "llm_overexpanded_plain_text"
        repair = "plain_text_fallback"
    elif reason.startswith("missing_browser_annotation") or reason == "misrouted_browser_annotation_feature_as_ui_design":
        stage = "feature_request_guard"
        origin = "router_or_llm_confused_feature_request_with_ui_design"
        repair = "rule_task_fallback"
    elif reason in {"misrouted_visual_subtask_as_primary", "missing_product_plan_capability_context"}:
        stage = "feature_request_guard"
        origin = "router_or_llm_promoted_visual_subtask_over_product_plan"
        repair = "rule_task_fallback"
    elif reason.startswith("missing_test_guidance"):
        stage = "status_or_guidance_guard"
        origin = "llm_output_missing_source_facts"
        repair = "revision"
    elif reason.startswith("missing_") or reason in {"semantic_awkwardness", "technical_asr_artifact"}:
        stage = "semantic_integrity_guard"
        origin = "llm_output_missing_or_misnormalized_source_facts"
        repair = "revision"

    if artifact_type == "software_feedback" and origin == "llm_output":
        origin = "software_feedback_not_preserved_in_output"
        repair = "rule_task_fallback"
    elif task_hint and task_type and task_hint != task_type:
        origin = "intent_router_mismatch"
        repair = "reroute_or_rule_task_fallback"

    return {
        "reason": reason,
        "stage": stage,
        "origin": origin,
        "recommended_repair": repair,
        "route_task_type": task_type,
        "intent_task_hint": task_hint,
        "intent_artifact_type": artifact_type,
        "intent_confidence": frame.get("confidence", 0.0),
        "final_text_chars": len(final_text or ""),
        "cleaned_text_chars": len(cleaned_text or ""),
    }


def _has_rule_fallback_path(cleaned_text: str) -> bool:
    return bool(compile_ai_task_fallback(cleaned_text))


def _compact_for_similarity(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    return re.sub(r"[，。！？、；：,.!?;:\n\r]", "", text)


def _extract_final_text_from_payload(data: dict[str, Any]) -> str:
    for key in ("final_text", "final_prompt", "prompt", "compiled_prompt"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _extract_final_text_from_jsonish_payload(text: str) -> str:
    if not text or not _looks_like_json_or_schema_leak(text):
        return ""
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    for key in ("final_text", "final_prompt", "prompt", "compiled_prompt"):
        pattern = (
            rf'"{key}"\s*:\s*"([\s\S]*?)"\s*'
            r'(?=,\s*"(?:intent_summary|semantic_diagnosis|output_requirements|final_text|final_prompt|prompt|compiled_prompt|mode|deleted_segments|corrections|constraints|uncertain_terms|risk_level|need_confirm)"\s*:|\s*[,}]?\s*$|\s*})'
        )
        match = re.search(pattern, stripped)
        if not match:
            continue
        value = match.group(1).strip()
        if not value:
            continue
        try:
            return json.loads(f'"{value}"').strip()
        except json.JSONDecodeError:
            return (
                value.replace("\\n", "\n")
                .replace('\\"', '"')
                .replace("\\/", "/")
                .strip()
            )
    return ""


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _has_task_structure(text: str) -> bool:
    return bool(re.search(r"(^|\n)(目标|背景|需要做|限制条件|要求|请你|请帮我)[:：]", text or ""))


def _misrouted_project_expansion(cleaned_text: str, final_text: str) -> str:
    if not cleaned_text or not final_text:
        return ""
    if looks_like_project_evaluation_build_request(cleaned_text):
        return ""

    route = detect_task_route(cleaned_text)
    if route.task_type not in {"text_polishing", "generic_task"}:
        return ""
    if route.task_type == "generic_task" and (
        _looks_like_task_request(cleaned_text)
        or len(_compact_for_similarity(cleaned_text)) > 80
    ):
        return ""

    project_terms = re.findall(
        r"(项目评估|是否值得开发|值得开发|可行性|市场需求|用户痛点|竞品|替代方案|商业模式|"
        r"技术可行性|MVP|技术架构|开发路线图|里程碑|验收标准|不要编造市场数据|coding agent)",
        final_text,
        re.IGNORECASE,
    )
    if len(set(project_terms)) >= 4:
        return "misrouted_project_evaluation_expansion"
    return ""


def _misrouted_visual_subtask_as_primary(cleaned_text: str, final_text: str) -> str:
    if not cleaned_text or not final_text:
        return ""
    if not looks_like_product_plan_with_visual_subtask(cleaned_text):
        return ""

    visual_template_markers = re.findall(
        r"(作图提示词|主体与场景|风格与构图|正向提示词|负面提示词|负面约束)",
        final_text,
    )
    planning_structure = bool(
        re.search(r"(产品规划|产品目标|业务目标|核心功能|功能模块|MVP|优先级|版本路线图|实施方案)", final_text)
    )
    if re.search(r"^\s*作图提示词[:：]", final_text) or (
        len(set(visual_template_markers)) >= 3 and not planning_structure
    ):
        return "misrouted_visual_subtask_as_primary"

    required_groups = (
        r"(广告|投放|出价|获客|用户开口|咨询成本)",
        r"(小红书|平台后台|数据反馈|运营)",
        r"(笔记|文稿|素材|照片|内容自动化)",
        r"(作图|配图|图片|image\s*2(?:\.0)?)",
    )
    if not planning_structure or any(
        not re.search(pattern, final_text, re.IGNORECASE) for pattern in required_groups
    ):
        return "missing_product_plan_capability_context"
    return ""


def _looks_like_compiled_status_report(text: str) -> bool:
    if not text:
        return False
    return bool(
        re.search(r"^结论[:：]", text)
        and re.search(r"(验证码|兑换码|接口返回|上游平台|敏感词|生产\s*env|测试记录|临时卡)", text, re.IGNORECASE)
    )


def _missing_status_report_facts(cleaned_text: str, final_text: str) -> str:
    if not _looks_like_status_source(cleaned_text):
        return ""
    required: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("missing_number_record_retention", ("号码记录", "号码也会保留", "号码会保留", "记录")),
        ("missing_cleanup_cards", ("临时卡",)),
        ("missing_cleanup_records", ("测试记录",)),
        ("missing_cleanup_env", ("env", "ENV", "NV文件", "inv文件", "ENV文件", "生产文件")),
    )
    for reason, source_terms in required:
        if not any(term in cleaned_text for term in source_terms):
            continue
        if reason == "missing_number_record_retention":
            if "号码记录" not in final_text and "记录会保留" not in final_text:
                return reason
        elif reason == "missing_cleanup_cards":
            if "临时卡" not in final_text:
                return reason
        elif reason == "missing_cleanup_records":
            if "测试记录" not in final_text:
                return reason
        elif reason == "missing_cleanup_env":
            if "env" not in final_text.lower() and "生产文件" not in final_text:
                return reason
    return ""


def _missing_browser_annotation_feature_context(cleaned_text: str, final_text: str) -> str:
    if not looks_like_browser_annotation_feature_request(cleaned_text):
        return ""
    if "右侧浏览器标注改动" in final_text:
        return ""
    if re.search(r"(UI/UX\s*设计方案|设计目标|用户流程|视觉与交互规范|关键界面与组件)", final_text, re.IGNORECASE):
        return "misrouted_browser_annotation_feature_as_ui_design"
    if not re.search(r"(右侧浏览器|浏览器标注|标注|批注|功能需求|实现)", final_text, re.IGNORECASE):
        return "missing_browser_annotation_feature_context"
    return ""


def _missing_test_guidance_context(cleaned_text: str, final_text: str) -> str:
    if not _looks_like_test_guidance_source(cleaned_text):
        return ""
    required = (
        ("missing_test_guidance_intro", ("开始测试", "重启", "编译器")),
        ("missing_test_guidance_items", ("测试", "重点")),
    )
    final_compact = _compact_for_similarity(final_text)
    for reason, terms in required:
        if not all(term in cleaned_text for term in terms):
            continue
        if not any(term in final_text for term in terms):
            return reason
    if "状态汇报" in cleaned_text and "状态汇报" not in final_text:
        return "missing_test_guidance_status_report"
    if "注册页" in final_text and "开始测试" not in final_text and "测试" not in final_text:
        return "missing_test_guidance_context"
    if "nice" in cleaned_text.lower() and "nice" not in final_text.lower():
        return "missing_test_guidance_casual_tail"
    if "谢谢你的评价" in cleaned_text and "谢谢你的评价" not in final_text:
        return "missing_test_guidance_polite_tail"
    if len(final_compact) < max(20, int(len(_compact_for_similarity(cleaned_text)) * 0.35)):
        return "missing_test_guidance_context"
    return ""


def _looks_like_test_guidance_source(text: str) -> bool:
    return bool(
        re.search(r"(可以开始测试|开始测试|测试时|测试重点|重点.*测试|重点.*看|验证清单|测试清单)", text)
        and re.search(r"(重启|编译器|新代码|prompt|英文|技术词|登录页|注册页|状态汇报|漏事实|任务请求|nice|评价)", text, re.IGNORECASE)
    )


def _missing_software_feedback_context(cleaned_text: str, final_text: str) -> str:
    if not _looks_like_software_feedback_source(cleaned_text):
        return ""
    if _looks_like_compiled_software_feedback(final_text):
        return ""
    final_compact = _compact_for_similarity(final_text)
    cleaned_compact = _compact_for_similarity(cleaned_text)
    if re.search(r"(同义词|相近|上下文|推理)", cleaned_text) and not re.search(
        r"(同义词|相近|上下文|语义分析|推理|harness|LLM)", final_text, re.IGNORECASE
    ):
        return "missing_software_feedback_semantic_context"
    if re.search(r"(粘贴|复制|目标界面|当前界面|Codex|codeex)", cleaned_text, re.IGNORECASE) and not re.search(
        r"(自动粘贴|粘贴|目标界面|当前界面|Codex)", final_text, re.IGNORECASE
    ):
        return "missing_software_feedback_paste_context"
    if re.search(r"(停顿|自动停止|自动结束|结束词|唤起词|我说完了|停止录音|快捷键|气口词|卡壳)", cleaned_text) and not re.search(
        r"(自动结束|自动停止|结束词|快捷键|气口词|卡壳|停顿|我说完了)", final_text
    ):
        return "missing_software_feedback_recording_context"
    if _looks_like_uncompiled_software_feedback(final_text):
        return "software_feedback_spoken_artifacts_left"
    if cleaned_compact == final_compact:
        return "software_feedback_exact_echo"
    if _lcs_ratio(cleaned_compact, final_compact) >= 0.8 and len(cleaned_compact) > 45:
        return "software_feedback_near_echo"
    return ""


def _miscompiled_software_feedback_prompt(cleaned_text: str, final_text: str) -> str:
    if not cleaned_text or not final_text:
        return ""
    if not re.search(r"(口气词|气口词|卡壳|嗯|啊|呃|那个|就是|呢|粘贴|复制|目标界面|识别到的界面|Codex|codeex)", cleaned_text, re.IGNORECASE):
        return ""
    if re.search(r"(请检查(咿呀喂|Yiyawei|语音指令编译器)当前的以下问题|文本清理需要过滤常见|显示系统指令|系统指令)", final_text):
        return "software_feedback_prompt_leak"
    return ""


def _missing_project_evaluation_context(cleaned_text: str, final_text: str) -> str:
    if not looks_like_project_evaluation_build_request(cleaned_text):
        return ""
    if not final_text.strip():
        return "missing_project_evaluation_context"

    required_groups: tuple[tuple[str, str], ...] = (
        ("missing_project_evaluation_decision", r"(是否值得|值得开发|是否可行|可行性|判断|建议做|不建议|谨慎)"),
        ("missing_project_evaluation_research", r"(调研|搜索|资料|市场|用户|痛点|竞品|替代方案|商业模式)"),
        ("missing_project_evaluation_evidence", r"(证据|依据|假设|数据|风险|成本|收益|不确定性|验证)"),
        ("missing_project_evaluation_build_plan", r"(如果值得|如果可行|MVP|开发方案|路线图|实施|里程碑|验收标准)"),
        ("missing_project_evaluation_architecture", r"(架构|技术栈|模块|API|数据结构|工程|项目初始化)"),
        ("missing_project_evaluation_ui", r"(UI|界面|交互|视觉|信息架构|产品方向)"),
    )
    for reason, pattern in required_groups:
        if not re.search(pattern, final_text, re.IGNORECASE):
            return reason

    route = detect_task_route(cleaned_text)
    if route.task_type == "project_evaluation" and route.domain != "general":
        missing_domain_terms = [
            term for term in required_domain_terms(route.domain) if term not in final_text
        ]
        if missing_domain_terms:
            return f"missing_project_evaluation_domain_{route.domain}"

    if re.search(r"(只需|简单|一句话|简单分析)", final_text):
        return "project_evaluation_too_thin"
    final_compact = _compact_for_similarity(final_text)
    cleaned_compact = _compact_for_similarity(cleaned_text)
    if len(final_compact) < max(140, int(len(cleaned_compact) * 2.2)):
        return "project_evaluation_too_thin"
    return ""


def _looks_like_software_feedback_source(text: str) -> bool:
    return bool(
        _has_software_feedback_signal(text or "")
        and re.search(
            r"(咿呀喂|Yiyawei|语音编译器|语音指令编译器|ASR|LLM|大模型|识别.*文字|识别.*文本|同义词|相近词|上下文|推理|"
            r"目标界面|当前界面|粘贴|复制|Codex|codeex|录音|停止录音|唤起词|结束词|快捷键|气口词|卡壳)",
            text or "",
            re.IGNORECASE,
        )
    )


def _has_software_feedback_signal(text: str) -> bool:
    if re.search(
        r"(还有一个问题|现在没有这个功能|之前.{0,16}(可以|会)|不会结合上下文|没有任何反馈|没有任何反应|"
        r"能不能|每次.{0,16}(点一下|手动)|应该.{0,24}(粘贴|复制|自动|停止|结束)|真\s*bug|功能.{0,16}(没有|失效|不见))",
        text or "",
        re.IGNORECASE,
    ):
        return True
    issue_words = re.findall(r"(问题|bug|不对|没有|不会|不能|应该|之前|现在|功能)", text or "", re.IGNORECASE)
    return len(issue_words) >= 2 and bool(
        re.search(r"(检查|修复|优化|回归|粘贴|复制|录音|停止|反馈|反应)", text or "", re.IGNORECASE)
    )


def _looks_like_compiled_software_feedback(text: str) -> bool:
    return bool(
        re.search(r"(请检查|请修复|需要检查|需要优化|问题)", text or "")
        and re.search(r"(咿呀喂|Yiyawei|语音指令编译器|语音编译器|ASR|LLM|harness|自动粘贴|录音)", text or "", re.IGNORECASE)
        and re.search(r"(^|\n)(1\.|2\.|- )", text or "")
    )


def _looks_like_uncompiled_software_feedback(text: str) -> bool:
    return bool(
        re.search(
            r"(现在我|我看了|看了一下|中文的话|应该是没什么问题|还有一个问题|就是说|比如说|说完话过后|"
            r"那个它识别到|它分析推理出来|现在没有这个功能了|每次都要去点一下)",
            text or "",
            re.IGNORECASE,
        )
    )


def _looks_like_status_source(text: str) -> bool:
    return bool(
        re.search(r"(结论|当前逻辑|逻辑是通的|验证码|兑换码|接口返回|上游平台|敏感词|临时卡|测试记录|生产|env|inv|NV)", text, re.IGNORECASE)
        and re.search(r"(确认|清理|清掉|删除|删掉|保留|换号|失效|命中|痕迹)", text, re.IGNORECASE)
    )


def _has_obvious_semantic_awkwardness(text: str) -> bool:
    return bool(
        re.search(r"(来源与外界|需要和正向|需要和正向的回忆|缺乏关注[，,]需要)", text or "")
    )


def _has_suspicious_tech_asr_artifacts(text: str) -> bool:
    return bool(
        re.search(r"(touch\s*扣达|拍\s*touch|扣达环境|变变聪明|上下文理|懂人化)", text or "")
    )


def _echo_requires_revision(cleaned_text: str) -> bool:
    route = detect_task_route(cleaned_text)
    return (
        route.task_type
        in {
            "project_evaluation",
            "code_fix",
            "ui_ux_design",
            "visual_generation",
            "presentation_deck",
            "bug_report",
            "test_plan",
            "product_planning",
            "business_analysis",
        }
        or
        _looks_like_task_request(cleaned_text)
        or _looks_like_uncompiled_speech(cleaned_text)
        or should_compile_ai_task_fallback(cleaned_text)
    )


def _apply_general_text_fixes(final_text: str) -> tuple[str, list[str]]:
    text = final_text or ""
    fixes: list[str] = []

    def apply(pattern: str, replacement: str, label: str) -> None:
        nonlocal text
        updated = re.sub(pattern, replacement, text)
        if updated != text:
            text = updated
            fixes.append(label)

    apply(r"来源与(?=外界)", "来源于", "source_preposition")
    apply(
        r"儿童如果缺乏关注[，,]\s*需要和正向的回忆[，,、]?\s*回应成人之后",
        "儿童如果缺乏关注、肯定和正向回应，成人之后",
        "attention_response_clause",
    )
    apply(
        r"缺乏关注[，,]\s*需要和正向的回忆[，,、]?\s*回应",
        "缺乏关注、肯定和正向回应",
        "positive_response_clause",
    )
    apply(r"需要和正向的回忆[，,、]?\s*回应", "肯定和正向回应", "positive_response_phrase")
    apply(r"慢慢的显现", "慢慢显现", "redundant_de_particle")
    apply(
        r"在关系中[，,]\s*失去的东西需要在关系中找回[，,]\s*可以调整慢慢来",
        "在关系中，失去的东西需要在关系中找回，也可以慢慢调整回来",
        "relationship_recovery_clause",
    )
    apply(r"可以调整慢慢来", "也可以慢慢调整回来", "slow_adjustment_phrase")
    apply(r"(?<![A-Za-z])(?i:asr)(?![A-Za-z])", "ASR", "asr_capitalization")
    apply(r"(?<![A-Za-z])(?i:pytorch)(?![A-Za-z])", "PyTorch", "pytorch_capitalization")
    apply(r"(?<![A-Za-z])(?i:cuda)(?![A-Za-z])", "CUDA", "cuda_capitalization")
    apply(
        r"(?:拍\s*)?(?:py\s*)?touch\s*扣达环境|(?:拍\s*)?torch\s*扣达环境|拍\s*touch\s*CUDA\s*环境",
        "PyTorch CUDA 环境",
        "pytorch_cuda_context",
    )
    apply(r"(?i)PyTorch\s+扣达环境", "PyTorch CUDA 环境", "cuda_context")
    apply(r"上下文理", "上下文里", "context_location")
    apply(r"突然变变聪明", "突然变聪明", "duplicate_smart")
    apply(r"变变聪明", "变聪明", "duplicate_smart")
    apply(r"懂人化", "懂人话", "human_language_phrase")
    apply(r"更快更稳[，,]\s*不是应该懂人话", "更快更稳、更懂人话", "human_language_phrase")
    apply(r"做一个([A-Za-z][A-Za-z0-9_.+#-]*)\s+\1的死词典", r"做一个“错拼 -> \1”的死词典", "harness_dead_dictionary")
    apply(r"这就是说[，,]\s*这就是", "这就是", "duplicate_transition")
    apply(r"([A-Za-z0-9_.+#-])\.([\u3400-\u9fff])", r"\1。\2", "latin_cjk_period")
    apply(r"(?<=[A-Za-z0-9])\.\s*$", "。", "latin_terminal_period")
    apply(r"\.。", "。", "duplicate_period")

    return text, fixes


def _restore_spoken_casual_tail(final_text: str, source_text: str) -> tuple[str, str]:
    tail = _extract_spoken_casual_tail(source_text)
    if not tail:
        return final_text, ""
    if _compact_for_similarity(tail) in _compact_for_similarity(final_text):
        return final_text, ""

    text = (final_text or "").strip()
    if not text:
        return tail, tail
    if not re.search(r"[。！？!?]$", text):
        text = f"{text}。"
    separator = "\n" if "\n" in text else ""
    return f"{text}{separator}{tail}", tail


def _extract_spoken_casual_tail(text: str) -> str:
    stripped = (text or "").strip()
    patterns = (
        r"(谢谢你(?:的)?(?:评价|建议|反馈|提醒|帮助|意见))[。！？!?，,\s]*$",
        r"(你觉得我[^。！？?]*?(?:nice|耐斯)[^。！？?]*吗)[？?。！!\s]*$",
        r"(你看我这样行不行|这样可以吗)[？?。！!\s]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, stripped, re.IGNORECASE)
        if match:
            return _ensure_spoken_tail_punctuation(match.group(1))
    return ""


def _ensure_spoken_tail_punctuation(text: str) -> str:
    result = (text or "").strip(" ，,。！？!?")
    if not result:
        return ""
    if result.endswith(("吗", "嘛", "么", "呢")):
        return f"{result}？"
    return f"{result}。"


def _looks_like_task_request(text: str) -> bool:
    return bool(
        re.search(r"(请|帮我|让你|我想让你|我要|需要).{0,32}(做|看一下|查看|分析|检查|优化|实现|执行|整理|生成)", text or "")
        or re.search(r"(这个任务|任务的执行难度|怎么执行这个任务|如何执行这个任务|给.*意见)", text or "")
    )


def _looks_like_uncompiled_speech(text: str) -> bool:
    return bool(
        re.search(
            r"(我肯定不可能每次|对吧|你看|这里我说错了|反正就是|不知道你会不会|我不确定你是否能执行|你来怎么执行|你会怎么执行|那你.*意见)",
            text or "",
            re.IGNORECASE,
        )
    )


def _leaks_internal_prompt(text: str) -> bool:
    return bool(
        re.search(
            r"(ASR 原始文本|原始语音识别文本|目标模式|输出文字|请只输出 JSON|"
            r"任务路由与模板参考|任务路由:|领域路由:|task_type=|route_context|"
            r"系统已初步识别任务类型|请把下面的口语输入整理成|请覆盖以下要点|建议输出结构|"
            r"任务模板目标|任务模板要求|模板约束|示例检索方向|few-shot|常见口述问题|"
            r"系统指令|内部提示词|内部路由|输出规范方针|用户原始需求描述|"
            r"待填充(?:的)?(?:Prompt|提示词|结构化输出)?|Prompt\s*结构(?:清晰|化输出)|"
            r"生成一个用于\s*AI\s*(?:图像生成)?模型的完整[^。]*Prompt)",
            text or "",
            re.IGNORECASE,
        )
    )


def _looks_like_json_or_schema_leak(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith("{") and any(
        token in stripped
        for token in (
            '"intent_summary"',
            '"semantic_diagnosis"',
            '"output_requirements"',
            '"final_prompt"',
            '"final_text"',
        )
    ):
        return True
    return bool(
        re.search(
            r"(^|\n)\s*\"(?:intent_summary|semantic_diagnosis|output_requirements|final_prompt|final_text)\"\s*:",
            text,
        )
        or re.search(r"\*\*(?:Scene|Style|Composition|Lighting|Prompt Structure|Subject Description|Action|Setting|Environment)\s*[:：]", text)
        or re.search(r"\(待用户补充\)", text)
    )


def _has_traditional_cjk(simplified_text: str, final_text: str) -> bool:
    return _compact_for_similarity(simplified_text) != _compact_for_similarity(final_text)


def _lcs_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    previous = [0] * (len(b) + 1)
    for char_a in a:
        current = [0]
        for index_b, char_b in enumerate(b, start=1):
            if char_a == char_b:
                current.append(previous[index_b - 1] + 1)
            else:
                current.append(max(previous[index_b], current[-1]))
        previous = current
    return previous[-1] / max(len(a), len(b))
