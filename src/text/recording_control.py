"""Helpers for removing spoken recording control phrases."""

from __future__ import annotations

import re


END_CONTROL_PHRASES = (
    "结束录音",
    "停止录音",
    "录音结束",
    "我说完了",
    "说完了",
    "就这样吧",
    "就这样",
    "完毕",
    "结束",
)

_PUNCT = " ，,。！？!?；;\n\r\t"
_SINGLE_WORD_CONTROLS = {"结束", "完毕"}
_QUOTE_CHARS = "\"'“”‘’"
_META_CONTEXT_RE = re.compile(
    r"(比如|例如|结束词|唤起词|这个词|这句|这句话|说的是|叫|叫做|设置|不用|不要|翻译|录进去|识别)$"
)


def strip_trailing_recording_end_phrase(text: str) -> tuple[str, str]:
    """Remove a trailing phrase that is meant to control recording, not content."""
    stripped = (text or "").strip()
    if not stripped:
        return "", ""

    for phrase in END_CONTROL_PHRASES:
        candidate = stripped.rstrip(_PUNCT)
        if not candidate.endswith(phrase):
            continue
        prefix_raw = candidate[: -len(phrase)]
        if _is_meta_description(prefix_raw, phrase):
            continue
        if phrase in _SINGLE_WORD_CONTROLS and prefix_raw and prefix_raw[-1] not in _PUNCT:
            continue
        cleaned = _ensure_clean_tail(prefix_raw)
        return cleaned, phrase
    return text, ""


def _is_meta_description(prefix: str, phrase: str) -> bool:
    prefix = prefix.rstrip(_PUNCT + _QUOTE_CHARS)
    if not prefix:
        return False
    context = prefix[-24:]
    if _META_CONTEXT_RE.search(context):
        return True
    if phrase in {"我说完了", "说完了", "结束"} and re.search(r"(结束词|唤起词|比如说|例如说)", context):
        return True
    return False


def _ensure_clean_tail(text: str) -> str:
    result = (text or "").strip(_PUNCT)
    if not result:
        return ""
    if re.search(r"[。！？!?]$", result):
        return result
    return result + "。"
