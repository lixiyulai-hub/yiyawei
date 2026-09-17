"""Light pre-cleaning for obvious ASR fillers."""

from __future__ import annotations

import re


FILLER_TOKEN_RE = re.compile(r"(?<![\u4e00-\u9fff])(呃呃|嗯嗯|啊啊|呃|嗯|啊|额)(?![\u4e00-\u9fff])")
LEADING_FILLER_RE = re.compile(r"^(?:[嗯呃啊额]+[，,、。\s]*)+")


def clean_fillers(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = _normalize_repeated_punctuation(text)
    text = _remove_obvious_fillers(text)
    text = _remove_empty_this_phrases(text)
    text = _normalize_spoken_noise_phrases(text)
    text = _normalize_repeated_punctuation(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_repeated_punctuation(text: str) -> str:
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。\.]{2,}", "。", text)
    text = re.sub(r"[、]{2,}", "、", text)
    return text


def _remove_obvious_fillers(text: str) -> str:
    text = FILLER_TOKEN_RE.sub("", text)
    text = LEADING_FILLER_RE.sub("", text)
    text = re.sub(r"^(嗯|呃|啊|额)+(那个|就是|然后)", "", text)
    text = re.sub(r"(，|,)\s*(嗯|呃|啊|额)+(，|,)", "，", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])(呃|嗯|额)+(?=[，,、。\s])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])(呃|嗯|额)+(?=(这个|那个|就是|然后|自己|closer|[A-Za-z]))", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=(这个|那个|就是|然后))(呃|嗯|额)+(?=[A-Za-z\u4e00-\u9fff])", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(嗯那个|呃就是|啊然后)", "", text)
    return text


def _normalize_spoken_noise_phrases(text: str) -> str:
    text = re.sub(r"有不有", "有没有", text)
    text = re.sub(r"(可以|能|无感的|行不行|对不对)嘛(?=[，,。！？\s]|$)", r"\1", text)
    text = re.sub(r"([，,。；;：:])\s*嘛(?=[，,。！？\s]|$)", r"\1", text)
    text = re.sub(r"(，|,)\s*(，|,)+", "，", text)
    return text


def _remove_empty_this_phrases(text: str) -> str:
    # Keep meaningful phrases such as 这个接口/这个页面/这个按钮.
    protected = ("这个接口", "这个页面", "这个按钮", "这个问题", "这个功能", "这个模型", "这个插件")
    placeholders: dict[str, str] = {}
    for index, phrase in enumerate(protected):
        token = f"__VPC_KEEP_THIS_{index}__"
        placeholders[token] = phrase
        text = text.replace(phrase, token)

    text = re.sub(r"(，|,|\s)+这个(，|,|\s)+(嗯|呃|啊|就是|然后)(，|,|\s)+", "，", text)
    text = re.sub(r"^(这个)(，|,|\s)+(嗯|呃|啊|就是|然后)(，|,|\s)+", "", text)

    for token, phrase in placeholders.items():
        text = text.replace(token, phrase)
    return text
