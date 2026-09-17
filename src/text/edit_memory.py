"""Local confirmed-edit memory for lightweight text corrections."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any


DISABLED_MODES = {"terminal_command"}
MAX_RULES = 500
MAX_REPLACEMENTS_PER_TEXT = 12


@dataclass(frozen=True)
class MemoryRule:
    pattern: str
    replacement: str
    mode: str = ""
    output_script: str = ""


@dataclass(frozen=True)
class MemoryApplyResult:
    text: str
    applied: tuple[dict[str, str], ...] = ()


class EditMemoryApplier:
    def __init__(self, rules: list[MemoryRule] | None = None, enabled: bool = True):
        self.enabled = enabled
        self._rules = _sort_rules(rules or [])

    def replace_rules(self, rules: list[MemoryRule]) -> None:
        self._rules = _sort_rules(rules)

    def apply(self, text: str, mode: str = "", output_script: str = "") -> MemoryApplyResult:
        if not self.enabled or not text or mode in DISABLED_MODES:
            return MemoryApplyResult(text=text or "")

        result = text
        applied: list[dict[str, str]] = []
        replacements = 0
        for rule in self._rules:
            if replacements >= MAX_REPLACEMENTS_PER_TEXT:
                break
            if rule.mode and rule.mode != mode:
                continue
            if rule.output_script and rule.output_script != output_script:
                continue
            if not _safe_rule(rule.pattern, rule.replacement):
                continue
            updated, count = _replace_literal(result, rule.pattern, rule.replacement)
            if count <= 0:
                continue
            result = updated
            replacements += count
            applied.append(
                {
                    "pattern": rule.pattern,
                    "replacement": rule.replacement,
                    "count": str(count),
                }
            )
        return MemoryApplyResult(text=result, applied=tuple(applied))


def infer_term_replacements(before_text: str, after_text: str) -> list[dict[str, Any]]:
    """Infer narrow literal replacement rules from a confirmed edit."""

    before = _compact_text(before_text)
    after = _compact_text(after_text)
    if not before or not after or before == after:
        return []
    if _looks_sensitive(before) or _looks_sensitive(after):
        return []

    rules: list[dict[str, Any]] = []
    matcher = SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        source = before[i1:i2].strip(" ，,。；;：:")
        target = after[j1:j2].strip(" ，,。；;：:")
        if _safe_rule(source, target):
            rules.append({"kind": "term_replacement", "pattern": source, "replacement": target})
    return _dedupe_rule_dicts(rules)


def infer_confirmed_edit_failure(
    *,
    source_kind: str,
    before_text: str,
    after_text: str,
    raw_asr_text: str = "",
    cleaned_text: str = "",
    final_text_before: str = "",
    route_before: dict[str, Any] | None = None,
    intent_frame_before: dict[str, Any] | None = None,
    quality_gate_attribution_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a confirmed edit as a local regression candidate."""

    route = route_before or {}
    intent_frame = intent_frame_before or {}
    quality_gate = quality_gate_attribution_before or {}
    failure_type = _infer_failure_type(
        source_kind=source_kind,
        before_text=before_text,
        after_text=after_text,
        raw_asr_text=raw_asr_text,
        cleaned_text=cleaned_text,
        final_text_before=final_text_before,
        route_before=route,
        intent_frame_before=intent_frame,
        quality_gate_attribution_before=quality_gate,
    )
    return {
        "inferred_failure_type": failure_type,
        "should_add_regression": failure_type not in {"punctuation_or_wording", "unknown"},
    }


def _sort_rules(rules: list[MemoryRule]) -> list[MemoryRule]:
    return sorted(rules[:MAX_RULES], key=lambda item: len(item.pattern), reverse=True)


def _infer_failure_type(
    *,
    source_kind: str,
    before_text: str,
    after_text: str,
    raw_asr_text: str,
    cleaned_text: str,
    final_text_before: str,
    route_before: dict[str, Any],
    intent_frame_before: dict[str, Any],
    quality_gate_attribution_before: dict[str, Any],
) -> str:
    before = _compact_text(before_text)
    after = _compact_text(after_text)
    if not before or not after or before == after:
        return "unknown"

    if source_kind == "asr_text":
        if _looks_like_asr_term_error(before, after):
            return "asr_term_error"
        if _looks_like_spoken_noise_cleanup(before, after):
            return "spoken_noise_cleanup"
        if _looks_like_intent_affecting_source_edit(before, after):
            return "intent_misroute"
        if _looks_like_punctuation_or_wording(before, after):
            return "punctuation_or_wording"
        return "unknown"

    if _quality_gate_stage(quality_gate_attribution_before) == "prompt_leak_guard":
        return "compiler_template_leak"
    if _looks_like_internal_template_leak(before):
        return "compiler_template_leak"
    if _looks_like_router_misroute(route_before, intent_frame_before, quality_gate_attribution_before):
        return "router_misroute"
    if _looks_like_software_feedback_miss(
        before,
        after,
        raw_asr_text=raw_asr_text,
        cleaned_text=cleaned_text,
        route_before=route_before,
        intent_frame_before=intent_frame_before,
        quality_gate_attribution_before=quality_gate_attribution_before,
    ):
        return "paste_feedback_missed" if _has_paste_feedback_terms(before + after + raw_asr_text + cleaned_text) else "under_compilation"
    if _looks_like_over_expansion(before, after, quality_gate_attribution_before):
        return "over_expansion"
    if _looks_like_under_compilation(before, after, final_text_before):
        return "under_compilation"
    if _looks_like_punctuation_or_wording(before, after):
        return "punctuation_or_wording"
    return "unknown"


def _quality_gate_stage(quality_gate: dict[str, Any]) -> str:
    return str(quality_gate.get("stage") or "")


def _quality_gate_origin(quality_gate: dict[str, Any]) -> str:
    return str(quality_gate.get("origin") or "")


def _quality_gate_reason(quality_gate: dict[str, Any]) -> str:
    return str(quality_gate.get("reason") or "")


def _looks_like_asr_term_error(before: str, after: str) -> bool:
    if re.search(r"image\s*2\.0", after, re.IGNORECASE) and not re.search(r"image\s*2\.0", before, re.IGNORECASE):
        return bool(re.search(r"(?:E\s*)?M\s*G|爱图|页\s*M\s*G|二点零|两点零|2\s*点\s*0|2\s*\.?\s*0", before, re.IGNORECASE))
    if _latin_or_model_token_count(after) > _latin_or_model_token_count(before):
        return _text_similarity(before, after) >= 0.45
    return False


def _looks_like_spoken_noise_cleanup(before: str, after: str) -> bool:
    if not re.search(r"(嗯|呃|啊|额|那个|就是|然后|就是说|你看|比如说|um|uh)", before, re.IGNORECASE):
        return False
    stripped = re.sub(r"(嗯|呃|啊|额|那个|就是|然后|就是说|你看|比如说|um|uh)", "", before, flags=re.IGNORECASE)
    return _text_similarity(stripped, after) >= 0.82


def _looks_like_intent_affecting_source_edit(before: str, after: str) -> bool:
    before_terms = _intent_terms(before)
    after_terms = _intent_terms(after)
    return before_terms != after_terms and bool(before_terms or after_terms)


def _intent_terms(text: str) -> set[str]:
    terms: set[str] = set()
    patterns = {
        "visual_generation": r"(作图|画图|生图|生成图|图片提示词|image\s*2\.0)",
        "presentation_deck": r"(PPT|ppt|slides?|presentation|deck|演示文稿|课件)",
        "software_feedback": r"(自动粘贴|粘贴|复制|目标界面|当前界面|任务栏|窗口位置)",
        "code_fix": r"(修复|报错|bug|代码|接口|函数)",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            terms.add(label)
    return terms


def _looks_like_internal_template_leak(text: str) -> bool:
    return bool(
        re.search(
            r"任务路由与模板参考|任务路由:|领域路由:|task_type=|route_context|"
            r"系统已初步识别任务类型|请把下面的口语输入整理成|请覆盖以下要点|建议输出结构|"
            r"任务模板目标|任务模板要求|模板约束|示例检索方向|few-shot|常见口述问题|"
            r"系统指令|内部提示词|内部路由|输出规范方针|用户原始需求描述",
            text,
            re.IGNORECASE,
        )
    )


def _looks_like_router_misroute(
    route_before: dict[str, Any],
    intent_frame_before: dict[str, Any],
    quality_gate_attribution_before: dict[str, Any],
) -> bool:
    if _quality_gate_origin(quality_gate_attribution_before) == "intent_router_mismatch":
        return True
    route_task = str(route_before.get("task_type") or quality_gate_attribution_before.get("route_task_type") or "")
    intent_task = str(
        intent_frame_before.get("task_hint")
        or quality_gate_attribution_before.get("intent_task_hint")
        or ""
    )
    if not route_task or not intent_task or intent_task in {"generic_task", "text_polishing"}:
        return False
    return route_task != intent_task


def _looks_like_software_feedback_miss(
    before: str,
    after: str,
    *,
    raw_asr_text: str,
    cleaned_text: str,
    route_before: dict[str, Any],
    intent_frame_before: dict[str, Any],
    quality_gate_attribution_before: dict[str, Any],
) -> bool:
    stage = _quality_gate_stage(quality_gate_attribution_before)
    origin = _quality_gate_origin(quality_gate_attribution_before)
    reason = _quality_gate_reason(quality_gate_attribution_before)
    if stage == "software_feedback_guard" or "software_feedback" in origin or reason.startswith("software_feedback"):
        return True
    if str(intent_frame_before.get("artifact_type") or "") == "software_feedback":
        return True
    if str(route_before.get("task_type") or "") in {"bug_report", "product_planning"} and _has_paste_feedback_terms(raw_asr_text + cleaned_text + after):
        return True
    return _has_paste_feedback_terms(after) and not _has_paste_feedback_terms(before)


def _has_paste_feedback_terms(text: str) -> bool:
    return bool(re.search(r"(自动粘贴|粘贴|复制|目标界面|当前界面|Codex|codeex|任务栏|窗口位置)", text, re.IGNORECASE))


def _looks_like_over_expansion(
    before: str,
    after: str,
    quality_gate_attribution_before: dict[str, Any],
) -> bool:
    if _quality_gate_stage(quality_gate_attribution_before) == "plain_text_overexpansion_guard":
        return True
    if _quality_gate_origin(quality_gate_attribution_before) == "llm_overexpanded_plain_text":
        return True
    return len(before) >= max(80, len(after) * 2) and _has_task_structure(before) and not _has_task_structure(after)


def _looks_like_under_compilation(before: str, after: str, final_text_before: str) -> bool:
    source = final_text_before or before
    if len(after) < max(60, int(len(source) * 1.35)):
        return False
    return _has_task_structure(after) and not _has_task_structure(source)


def _has_task_structure(text: str) -> bool:
    return bool(re.search(r"(^|\n)\s*[-*]\s+|目标|背景|问题|步骤|验收|输出要求|请修复|请检查|请生成", text))


def _looks_like_punctuation_or_wording(before: str, after: str) -> bool:
    if _strip_punctuation(before) == _strip_punctuation(after):
        return True
    if _text_similarity(before, after) < 0.92:
        return False
    if abs(len(before) - len(after)) > max(8, int(max(len(before), len(after)) * 0.12)):
        return False
    return not (_intent_terms(before) ^ _intent_terms(after))


def _strip_punctuation(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:\n\r\"'“”‘’（）()【】\[\]{}<>《》`~\-—_]+", "", text or "")


def _text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=_strip_punctuation(left), b=_strip_punctuation(right), autojunk=False).ratio()


def _latin_or_model_token_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z0-9_.+-]*|\d+(?:\.\d+)?", text or ""))


def _replace_literal(text: str, pattern: str, replacement: str) -> tuple[str, int]:
    if _contains_latin(pattern):
        regex = re.compile(rf"(?<![A-Za-z0-9]){re.escape(pattern)}(?![A-Za-z0-9])", re.IGNORECASE)
        return regex.subn(replacement, text)
    return text.replace(pattern, replacement), text.count(pattern)


def _safe_rule(pattern: str, replacement: str) -> bool:
    pattern = (pattern or "").strip()
    replacement = (replacement or "").strip()
    if not pattern or not replacement or pattern == replacement:
        return False
    if len(pattern) < 2 or len(pattern) > 32 or len(replacement) > 48:
        return False
    if _looks_sensitive(pattern) or _looks_sensitive(replacement):
        return False
    if re.search(r"[\r\n{}<>`]|https?://|[A-Za-z]:\\|/", pattern + replacement):
        return False
    if pattern in {"这个", "那个", "就是", "然后", "需要", "我要", "帮我", "请", "图片", "任务"}:
        return False
    return True


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _contains_latin(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def _looks_sensitive(text: str) -> bool:
    return bool(
        re.search(
            r"(api[_-]?key|secret|token|password|passwd|authorization|cookie|AKIA|sk-[A-Za-z0-9]|手机号|身份证|银行卡)",
            text or "",
            re.IGNORECASE,
        )
    )


def _dedupe_rule_dicts(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for rule in rules:
        key = (str(rule.get("pattern") or ""), str(rule.get("replacement") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(rule)
    return result
