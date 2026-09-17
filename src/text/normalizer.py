"""Text output normalization."""

from __future__ import annotations

from functools import lru_cache
import re


SCRIPT_AUTO = "auto"
SCRIPT_SIMPLIFIED = "simplified"
SCRIPT_TRADITIONAL = "traditional"


@lru_cache(maxsize=4)
def _converter(mode: str):
    try:
        from opencc import OpenCC
    except ImportError:
        return None
    if mode == SCRIPT_SIMPLIFIED:
        return OpenCC("t2s")
    if mode == SCRIPT_TRADITIONAL:
        return OpenCC("s2t")
    return None


SENTENCE_PUNCT_RE = re.compile(r"[。！？!?]")
ANY_PUNCT_RE = re.compile(r"[。！？!?，,、；;：:\n]")
CJK_RE = re.compile(r"[\u3400-\u9fff]")

FALLBACK_T2S = str.maketrans(
    {
        "聽": "听",
        "見": "见",
        "說": "说",
        "話": "话",
        "嗎": "吗",
        "幾": "几",
        "這": "这",
        "個": "个",
        "項": "项",
        "開": "开",
        "發": "发",
        "應": "应",
        "測": "测",
        "試": "试",
        "輸": "输",
        "構": "构",
        "風": "风",
        "險": "险",
        "據": "据",
        "證": "证",
        "數": "数",
        "據": "据",
        "標": "标",
        "準": "准",
    }
)

FALLBACK_S2T = str.maketrans(
    {
        "听": "聽",
        "见": "見",
        "说": "說",
        "话": "話",
        "吗": "嗎",
        "几": "幾",
        "这": "這",
        "个": "個",
        "项": "項",
        "开": "開",
        "发": "發",
        "应": "應",
        "测": "測",
        "试": "試",
        "输": "輸",
        "构": "構",
        "风": "風",
        "险": "險",
        "据": "據",
        "证": "證",
        "数": "數",
        "标": "標",
        "准": "準",
    }
)


def normalize_output_text(
    text: str,
    script: str = SCRIPT_SIMPLIFIED,
    punctuate: bool = True,
) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if script == SCRIPT_AUTO:
        converted = text
    else:
        converter = _converter(script)
        if converter is not None:
            converted = converter.convert(text)
        elif script == SCRIPT_SIMPLIFIED:
            converted = text.translate(FALLBACK_T2S)
        elif script == SCRIPT_TRADITIONAL:
            converted = text.translate(FALLBACK_S2T)
        else:
            converted = text
    converted = normalize_known_terms(converted)
    converted = _normalize_punctuation_spacing(converted)
    converted = _normalize_repeated_punctuation(converted)
    converted = _repair_protected_terms(converted)
    if punctuate:
        converted = _ensure_readable_punctuation(converted)
        converted = _normalize_repeated_punctuation(converted)
        converted = _repair_protected_terms(converted)
    return converted


def normalize_known_terms(text: str) -> str:
    """Normalize common spoken product/model names into their official spelling."""

    result = text or ""
    spoken_image_two = (
        r"(?<![A-Za-z])(?:页\s*)?(?:(?:E|I)\s*)?M\s*G\s*(?:2|二|二\s*点\s*零|二点零|2\s*(?:[.。点]\s*)?0)"
        r"(?=\s*(?:，|,|。|\.|、|；|;|：|:|帮|做|生成|生图|画|绘|出|写|用|$))"
    )
    result = re.sub(spoken_image_two, "image 2.0", result, flags=re.IGNORECASE)
    image_two_zero = (
        r"(?<![A-Za-z])image\s*"
        r"(?:2\s*(?:[.。点]\s*)?0|二\s*点\s*零|二点零)"
        r"(?![A-Za-z0-9])"
    )
    result = re.sub(image_two_zero, "image 2.0", result, flags=re.IGNORECASE)
    image_two_short = (
        r"(?<![A-Za-z])image\s*(?:2|二)"
        r"(?!\s*(?:[.。]\s*0|点\s*零|点零))"
        r"(?=\s*(?:，|,|。|\.|、|；|;|：|:|帮|做|生成|生图|画|绘|出|写|用|$))"
    )
    result = re.sub(image_two_short, "image 2.0", result, flags=re.IGNORECASE)
    has_visual_short_drama_context = bool(
        re.search(r"(分镜|故事板|镜头图|连续分镜|image\s*2\.0|生图|生成图|作图|图片)", result, re.IGNORECASE)
    )
    if has_visual_short_drama_context:
        result = re.sub(r"短距\s*想", "短剧，想", result)
    result = re.sub(r"AI\s*短距", "AI 短剧", result, flags=re.IGNORECASE)
    if has_visual_short_drama_context:
        result = re.sub(r"短距(?!离)", "短剧", result)
    result = re.sub(r"AI\s*短剧", "AI 短剧", result, flags=re.IGNORECASE)
    return result


def _normalize_punctuation_spacing(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text).strip()
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"([\u3400-\u9fff]),", r"\1，", text)
    text = re.sub(r",([\u3400-\u9fff])", r"，\1", text)
    text = re.sub(r"([\u3400-\u9fff]);", r"\1；", text)
    text = re.sub(r";([\u3400-\u9fff])", r"；\1", text)
    text = re.sub(r"([\u3400-\u9fff]):", r"\1：", text)
    text = re.sub(r":([\u3400-\u9fff])", r"：\1", text)
    text = re.sub(r"[ \t]*([，。！？；：、])[ \t]*", r"\1", text)
    text = re.sub(r"：。", "：", text)
    text = re.sub(r"[，,]+(?=；)", "", text)
    text = re.sub(r"[，,]+(?=。)", "", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])(?=[A-Za-z0-9])", r"\1 ", text)
    text = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", text)
    text = re.sub(r"吗[，,]", "吗？", text)
    text = re.sub(r"呢[，,]", "呢？", text)
    return text.strip()


def _normalize_repeated_punctuation(text: str) -> str:
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。．]{2,}", "。", text)
    text = re.sub(r"[！!]{2,}", "！", text)
    text = re.sub(r"[？?]{2,}", "？", text)
    text = re.sub(r"[；;]{2,}", "；", text)
    text = re.sub(r"[：:]{2,}", "：", text)
    text = re.sub(r"、{2,}", "、", text)
    return text


def _repair_protected_terms(text: str) -> str:
    text = re.sub(r"(?<![A-Za-z])image[，,。．]\s*2\.0(?![A-Za-z0-9])", "image 2.0", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])image\s+2[。．]\s*0(?![A-Za-z0-9])", "image 2.0", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b([A-Za-z0-9_-]+)\.\s*(md|json|yaml|yml|toml|txt|py|ts|tsx|js|jsx|css|html|env|ini|cfg)\b",
        r"\1.\2",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<=\d)\s*[:：]\s+(?=\d)", ":", text)
    text = re.sub(r"(?<=\d)\s+[:：]\s*(?=\d)", ":", text)
    return text.strip()


def _ensure_readable_punctuation(text: str) -> str:
    if not CJK_RE.search(text):
        return text
    if "\n" in text:
        return "\n".join(_ensure_readable_punctuation(line) if line.strip() else "" for line in text.split("\n"))
    list_match = re.match(r"^(\s*(?:[-*]|\d+[.)、])\s+)(.+)$", text)
    if list_match:
        return list_match.group(1) + _ensure_readable_punctuation(list_match.group(2))
    text = _insert_common_pause_punctuation(text)
    if SENTENCE_PUNCT_RE.search(text):
        return _ensure_sentence_end(text)
    if " " in text:
        chunks = [chunk.strip(" ，,。") for chunk in text.split(" ") if chunk.strip(" ，,。")]
        chunks = _merge_mixed_language_chunks(chunks)
        if len(chunks) > 1:
            return "".join(
                chunk + _punct_for_chunk(chunk, index, len(chunks))
                for index, chunk in enumerate(chunks)
            )
    return _ensure_sentence_end(text)


def _punct_for_chunk(chunk: str, index: int, total: int) -> str:
    if _looks_like_question(chunk):
        return "？"
    if index == total - 1:
        return "。"
    if len(chunk) <= 6 or chunk.startswith(("比如说", "然后", "但是", "不过", "所以", "另外", "还有", "你看")):
        return "，"
    return "。"


def _merge_mixed_language_chunks(chunks: list[str]) -> list[str]:
    merged: list[str] = []
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        if _is_short_cjk_prefix(chunk) and index + 1 < len(chunks) and _is_latin_chunk(chunks[index + 1]):
            phrase = f"{chunk} {chunks[index + 1]}"
            index += 2
            if index < len(chunks) and CJK_RE.search(chunks[index]):
                phrase = f"{phrase} {chunks[index]}"
                index += 1
            merged.append(phrase)
            continue
        if _is_latin_chunk(chunk) and merged:
            merged[-1] = f"{merged[-1]} {chunk}"
            index += 1
            if index < len(chunks) and CJK_RE.search(chunks[index]):
                merged[-1] = f"{merged[-1]} {chunks[index]}"
                index += 1
            continue
        merged.append(chunk)
        index += 1
    return merged


def _is_latin_chunk(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.+#/-]*", text))


def _is_short_cjk_prefix(text: str) -> bool:
    return text in {"你要", "我要", "就是", "这个", "那个", "用", "打开", "测试", "看看"}


def _looks_like_question(text: str) -> bool:
    stripped = text.rstrip("，,。！？!?")
    return (
        stripped.endswith(("吗", "嘛", "么", "呢", "几", "什么", "如何", "怎么样", "可不可以"))
        or stripped.startswith(("你能不能", "能不能", "是不是", "要不要"))
    )


def _insert_common_pause_punctuation(text: str) -> str:
    text = re.sub(r"(吗|嘛|呢)(?![。！？!?])", r"\1？", text)
    text = re.sub(r"(不是普通语音转文字)(?![，。！？；;])", r"\1，", text)
    text = re.sub(r"(不是机器人聊天)(?![，。！？；;])", r"\1，", text)
    text = re.sub(r"(不是代码生成器)(?![，。！？；;])", r"\1，", text)
    text = re.sub(r"(不是普通语音转文字[，,]而是[^，。！？]+)(不是)", r"\1。\2", text)
    text = re.sub(r"(高级安全设置)[，,](高级账户安全)", r"\1。\2", text)
    text = re.sub(r"(高级安全设置)\s+(高级账户安全)", r"\1。\2", text)
    text = re.sub(r"(方式)[，,](并应用)", r"\1，\2", text)
    text = re.sub(r"(方式)[。\.]\s*(并用|并应用)", r"\1，\2", text)
    text = re.sub(r"(方式)\s+(并用|并应用)", r"\1，\2", text)
    text = re.sub(r"(保护措施)[，,](来提供)", r"\1，\2", text)
    text = re.sub(r"(保护措施)[。\.]\s*(来提供)", r"\1，\2", text)
    text = re.sub(r"(保护措施)\s+(来提供)", r"\1，\2", text)
    text = re.sub(r"(账户安全)(帮助防止)", r"\1，\2", text)
    text = re.sub(r"(账户安全)[。\.]?\s*(帮助防止)", r"\1，\2", text)
    text = re.sub(r"防范[，,、\s]*(防止未经授权的访问)", r"\1", text)
    text = re.sub(r"登陆方式", "登录方式", text)
    text = re.sub(r"(你看)(?![，。！？])", r"\1，", text)
    text = re.sub(r"(比如说)(?![，。！？])", r"\1，", text)
    text = re.sub(r"(然后|但是|不过|所以|另外|还有)(?![，。！？])", r"\1，", text)
    return text


def _ensure_sentence_end(text: str) -> str:
    text = text.strip()
    if not text or re.search(r"[。！？!?]$", text):
        return text
    if text.endswith(("：", ":")):
        return text
    if _looks_like_question(text):
        return text + "？"
    return text + "。"
