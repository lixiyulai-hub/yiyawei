"""Repair simple spoken self-corrections before LLM audit."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SelfCorrection:
    source: str
    target: str
    reason: str = "spoken_self_correction"


SELF_CORRECTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?P<prefix>[^，,。！？\n]{0,20}?)(?P<wrong>登录页|注册页|首页|详情页|列表页|设置页|表单|按钮|页面)"
            r"[，,、。\s]*(?:不对[，,、。\s]*)?不是(?P=wrong)[，,、。\s]*是(?P<right>登录页|注册页|首页|详情页|列表页|设置页|表单|按钮|页面)"
        ),
        r"\g<prefix>\g<right>",
    ),
    (
        re.compile(r"不是聊天机器人[，,、。\s]*(?:我)?说错了[，,、。\s]*(不是机器人聊天)"),
        r"\1",
    ),
    (
        re.compile(r"不是机器人聊天[，,、。\s]*(?:我)?说错了[，,、。\s]*(不是聊天机器人)"),
        r"\1",
    ),
    (
        re.compile(r"防范[，,、。\s]*(而不是|呃[，,、。\s]*不是)[^，,。]*?(帮助防止[^，,。]*?)[，,、。\s]*刚才错了[，,、。\s]*要改啊?"),
        r"\2",
    ),
    (
        re.compile(r"防范[，,、。\s]*(而不是|呃[，,、。\s]*不是)[^，,。]*?(帮助防止[^，,。]*?)[，,、。\s]*刚才[^，,。]*?(说错|错了)[^，,。]*?(要改|改成)啊?"),
        r"\2",
    ),
    (
        re.compile(r"(而不是|呃[，,、。\s]*不是)[^，,。]*?(防[范止][^，,。]*?)[，,、。\s]*刚才错了[，,、。\s]*要改啊?"),
        r"\2",
    ),
    (
        re.compile(r"(而不是|呃[，,、。\s]*不是)[^，,。]*?(防[范止][^，,。]*?)[，,、。\s]*刚才[^，,。]*?(说错|错了)[^，,。]*?(要改|改成)啊?"),
        r"\2",
    ),
)


def repair_spoken_self_corrections(text: str) -> tuple[str, list[SelfCorrection]]:
    if not text:
        return "", []

    result = text
    corrections: list[SelfCorrection] = []
    for pattern, replacement in SELF_CORRECTION_PATTERNS:

        def replace(match: re.Match[str]) -> str:
            target = match.expand(replacement)
            corrections.append(SelfCorrection(source=match.group(0), target=target))
            return target

        result = pattern.sub(replace, result)
    return result, corrections
