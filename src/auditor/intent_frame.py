"""Lightweight semantic frame extraction for spoken task routing."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from src.text.normalizer import normalize_known_terms


@dataclass(frozen=True)
class IntentFrame:
    source_text: str
    normalized_text: str
    user_action: str = "unknown"
    artifact_type: str = "unknown"
    target_tool: str = ""
    task_hint: str = ""
    domain_hint: str = ""
    confidence: float = 0.0
    constraints: dict[str, str] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    ambiguity_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "normalized_text": self.normalized_text,
            "user_action": self.user_action,
            "artifact_type": self.artifact_type,
            "target_tool": self.target_tool,
            "task_hint": self.task_hint,
            "domain_hint": self.domain_hint,
            "confidence": self.confidence,
            "constraints": dict(self.constraints),
            "evidence": list(self.evidence),
            "ambiguity_flags": list(self.ambiguity_flags),
        }


def extract_intent_frame(text: str) -> IntentFrame:
    source = text or ""
    normalized = _cleanup(source)
    if not normalized:
        return IntentFrame(source_text=source, normalized_text="")

    constraints = _extract_constraints(normalized)
    target_tool = _extract_target_tool(normalized)
    evidence: list[str] = []
    flags: list[str] = []

    if _looks_like_light_text_request(normalized):
        action = _light_text_action(normalized)
        task_hint = "text_polishing" if action == "polish" else "generic_task"
        evidence.append("light_text_request")
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action=action,
            artifact_type="plain_text",
            target_tool=target_tool,
            task_hint=task_hint,
            confidence=0.9,
            constraints=constraints,
            evidence=tuple(evidence),
        )

    if looks_like_product_plan_with_visual_subtask(normalized):
        evidence.extend(("multi_capability_product_plan", "visual_generation_subtask"))
        flags.append("visual_subtask_not_primary")
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action="plan",
            artifact_type="software_product_plan",
            target_tool=target_tool,
            task_hint="product_planning",
            domain_hint="content_community" if re.search(r"(小红书|抖音|博主|笔记)", normalized) else "",
            confidence=0.93,
            constraints=constraints,
            evidence=tuple(evidence),
            ambiguity_flags=tuple(flags),
        )

    if _looks_like_visual_generation(normalized):
        evidence.append("visual_generation")
        if re.search(r"(分镜|故事板|镜头图|短剧)", normalized, re.IGNORECASE):
            evidence.append("storyboard")
        if re.search(r"(UI|UX|界面|页面|交互)", normalized, re.IGNORECASE):
            flags.append("visual_ui_overlap_terms")
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action="generate",
            artifact_type="image_prompt",
            target_tool=target_tool,
            task_hint="visual_generation",
            confidence=0.9,
            constraints=constraints,
            evidence=tuple(evidence),
            ambiguity_flags=tuple(flags),
        )

    if _looks_like_presentation_deck(normalized):
        evidence.append("presentation_deck")
        if re.search(r"(商业分析|项目评估|复盘|数据|指标|转化|收入)", normalized):
            flags.append("deck_business_overlap_terms")
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action="generate",
            artifact_type="presentation_deck",
            target_tool=target_tool,
            task_hint="presentation_deck",
            confidence=0.88,
            constraints=constraints,
            evidence=tuple(evidence),
            ambiguity_flags=tuple(flags),
        )

    if _looks_like_account_switch_automation(normalized):
        evidence.append("account_switch_automation")
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action="plan",
            artifact_type="software_feature_request",
            target_tool=target_tool,
            task_hint="product_planning",
            confidence=0.9,
            constraints=constraints,
            evidence=tuple(evidence),
        )

    if _looks_like_voice_compiler_feedback(normalized):
        evidence.append("voice_compiler_feedback")
        if re.search(r"(粘贴|复制|目标界面|当前界面|Codex|codeex|任务栏|窗口位置)", normalized, re.IGNORECASE):
            evidence.append("paste_or_window_feedback")
        if re.search(r"(录音|停止录音|自动停止|停顿|气口词|卡壳|唤起词|结束词)", normalized):
            evidence.append("recording_feedback")
        if _looks_like_ai_coding_governance(normalized):
            evidence.append("ai_coding_governance")
            return IntentFrame(
                source_text=source,
                normalized_text=normalized,
                user_action="plan",
                artifact_type="software_feedback",
                target_tool=target_tool,
                task_hint="product_planning",
                confidence=0.93,
                constraints=constraints,
                evidence=tuple(evidence),
            )
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action="plan" if _looks_like_recording_feature_planning(normalized) else "fix",
            artifact_type="software_feedback",
            target_tool=target_tool,
            task_hint="product_planning" if _looks_like_recording_feature_planning(normalized) else "bug_report",
            confidence=0.92,
            constraints=constraints,
            evidence=tuple(evidence),
        )

    if _looks_like_browser_annotation_feature(normalized):
        evidence.append("browser_annotation_feature")
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action="plan",
            artifact_type="browser_annotation_feature",
            target_tool=target_tool,
            task_hint="product_planning",
            confidence=0.88,
            constraints=constraints,
            evidence=tuple(evidence),
        )

    if _looks_like_ui_ux_design(normalized):
        evidence.append("ui_ux_design")
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action="design",
            artifact_type="ui_ux_spec",
            target_tool=target_tool,
            task_hint="ui_ux_design",
            confidence=0.82,
            constraints=constraints,
            evidence=tuple(evidence),
        )

    if _looks_like_code_fix(normalized):
        evidence.append("code_fix")
        return IntentFrame(
            source_text=source,
            normalized_text=normalized,
            user_action="fix",
            artifact_type="code",
            target_tool=target_tool,
            task_hint="code_fix",
            confidence=0.82,
            constraints=constraints,
            evidence=tuple(evidence),
        )

    return IntentFrame(
        source_text=source,
        normalized_text=normalized,
        target_tool=target_tool,
        constraints=constraints,
        evidence=tuple(evidence),
        ambiguity_flags=tuple(flags),
    )


def render_intent_frame_context(frame: IntentFrame) -> str:
    if not frame.normalized_text:
        return ""
    parts = [
        f"action={frame.user_action}",
        f"artifact={frame.artifact_type}",
    ]
    if frame.task_hint:
        parts.append(f"task_hint={frame.task_hint}")
    if frame.target_tool:
        parts.append(f"target_tool={frame.target_tool}")
    if frame.constraints:
        constraints = ", ".join(f"{key}={value}" for key, value in frame.constraints.items())
        parts.append(f"constraints={constraints}")
    if frame.evidence:
        parts.append("evidence=" + ",".join(frame.evidence))
    if frame.ambiguity_flags:
        parts.append("ambiguity=" + ",".join(frame.ambiguity_flags))
    return "语义框架: " + "; ".join(parts)


def _cleanup(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_known_terms(text or "")).strip()


def _extract_target_tool(text: str) -> str:
    if re.search(r"image\s*2\.0", text, re.IGNORECASE):
        return "image 2.0"
    targets = (
        ("Codex", r"(?<![A-Za-z])(?:Codex|code\s*ex|codeex)(?![A-Za-z])"),
        ("Cursor", r"(?<![A-Za-z])Cursor(?![A-Za-z])"),
        ("ChatGPT", r"(?<![A-Za-z])ChatGPT(?![A-Za-z])"),
        ("Claude", r"(?<![A-Za-z])Claude(?![A-Za-z])"),
        ("Gemini", r"(?<![A-Za-z])Gemini(?![A-Za-z])"),
        ("VS Code", r"VS\s*Code|Waste\s*Code"),
    )
    for label, pattern in targets:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return ""


def _extract_constraints(text: str) -> dict[str, str]:
    constraints: dict[str, str] = {}
    ratio = _extract_ratio(text)
    if ratio:
        constraints["ratio"] = ratio
    count = _extract_count(text)
    if count:
        constraints["count"] = count
    if re.search(r"image\s*2\.0", text, re.IGNORECASE):
        constraints["model"] = "image 2.0"
    return constraints


def _extract_ratio(text: str) -> str:
    if re.search(r"(16\s*[:：比]\s*9|十六比九)", text):
        return "16:9"
    if re.search(r"(9\s*[:：比]\s*16|九比十六)", text):
        return "9:16"
    if re.search(r"(3\s*[:：比]\s*4|三比四)", text):
        return "3:4"
    if re.search(r"(4\s*[:：比]\s*3|四比三)", text):
        return "4:3"
    if re.search(r"(1\s*[:：比]\s*1|一比一)", text):
        return "1:1"
    return ""


def _extract_count(text: str) -> str:
    without_ratios = re.sub(
        r"(16\s*[:：比]\s*9|十六比九|9\s*[:：比]\s*16|九比十六|3\s*[:：比]\s*4|三比四|4\s*[:：比]\s*3|四比三|1\s*[:：比]\s*1|一比一)",
        " ",
        text,
    )
    matches = list(re.finditer(r"(\d+|[一二两三四五六七八九十]{1,3})\s*(?:张|幅|页|镜头|分镜)", without_ratios))
    if not matches:
        return ""
    return f"{_normalize_count(matches[-1].group(1))} 张"


def _normalize_count(value: str) -> str:
    if value.isdigit():
        return str(int(value))
    mapping = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if value == "十":
        return "10"
    if value.startswith("十") and len(value) == 2:
        return str(10 + mapping.get(value[1], 0))
    if value.endswith("十") and len(value) == 2:
        return str(mapping.get(value[0], 0) * 10)
    if "十" in value and len(value) == 3:
        return str(mapping.get(value[0], 0) * 10 + mapping.get(value[2], 0))
    return str(mapping.get(value, value))


def _looks_like_light_text_request(text: str) -> bool:
    has_light_operation = bool(
        re.search(
            r"(翻译|翻成英文|译成英文|解释|是什么意思|什么意思|润色|改顺|改错别字|加标点|加个句号|读一下|压缩成一句|整理成一句)",
            text,
        )
    )
    if not has_light_operation:
        return False
    has_term_only_object = bool(
        re.search(
            r"(PPT|ppt|幻灯片|presentation|deck|图片|图像|作图|生图|海报|封面|提示词|prompt|image\s*2\.0|image).{0,16}"
            r"(这个词|这几个字|这三个字|这两个字|翻译|解释|是什么意思|什么意思|加标点|改错别字|读一下)",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"(翻译|解释|是什么意思|什么意思|加标点|改错别字|读一下).{0,16}"
            r"(PPT|ppt|幻灯片|presentation|deck|图片|图像|作图|生图|海报|封面|提示词|prompt|image\s*2\.0|image)",
            text,
            re.IGNORECASE,
        )
    )
    has_light_limiter = bool(re.search(r"(只|就|简单|一下|即可|就好|就行|不要扩写|别扩写|不要展开)", text))
    return has_term_only_object or has_light_limiter


def _light_text_action(text: str) -> str:
    if re.search(r"(翻译|翻成英文|译成英文)", text):
        return "translate"
    if re.search(r"(解释|是什么意思|什么意思)", text):
        return "explain"
    if re.search(r"(润色|改顺|改错别字|加标点)", text):
        return "polish"
    return "edit"


def _looks_like_voice_compiler_feedback(text: str) -> bool:
    if _looks_like_technical_status_text(text):
        return False
    if _looks_like_ai_coding_governance(text):
        return True
    has_context = bool(
        re.search(
            r"(咿呀喂|Yiyawei|语音编译器|语音指令编译器|语音界面|ASR|LLM|大模型|识别.*文字|识别.*文本|"
            r"识别.*界面|目标界面|当前界面|粘贴|复制|Codex|codeex|录音|停止录音|任务栏|窗口位置|口气词|气口词|卡壳)",
            text,
            re.IGNORECASE,
        )
    )
    has_issue_or_request = bool(
        re.search(
            r"(问题|不对|没有|不会|不能|应该|需要|希望|之前|现在|功能|弹到|跑到|跳到|还得|还要|自动|修复|实现|优化)",
            text,
            re.IGNORECASE,
        )
    )
    return has_context and has_issue_or_request


def _looks_like_ai_coding_governance(text: str) -> bool:
    has_ai_coder = bool(re.search(r"(大模型|Codex|codeex|cloud\s*code|claude\s*code|Claude Code|Cursor)", text, re.IGNORECASE))
    has_damage = bool(re.search(r"(改乱|覆盖|删掉|误删|回滚|冲掉|代码.{0,12}(变少|丢失)|四千行|一千多行)", text, re.IGNORECASE))
    has_governance_request = bool(re.search(r"(杜绝|规避|治理|全局|工作方式|方法|方案|解决方法|改善|维护|规范)", text))
    return has_ai_coder and has_damage and has_governance_request


def _looks_like_account_switch_automation(text: str) -> bool:
    has_context = bool(re.search(r"(这个软件|后台|对标|closer|Codex|cloud\s*code|目标软件|账号|账户)", text, re.IGNORECASE))
    has_switch = bool(re.search(r"(没有额度|额度|切换账号|换号|切号|注入账号|无感|自适应)", text))
    has_request = bool(re.search(r"(有没有|功能|需要|可以|实现|方案|解决方法|无感|自动)", text))
    return has_context and has_switch and has_request


def _looks_like_recording_feature_planning(text: str) -> bool:
    return bool(
        re.search(r"(功能规划|帮我做一个功能|规划一下|设计一个功能|实现一个功能)", text)
        and re.search(r"(自动停止录音|停止录音|快捷键|我说完了|结束词|唤起词)", text)
    )


def _looks_like_technical_status_text(text: str) -> bool:
    return bool(
        re.search(r"(PyTorch|CUDA|CPU|ASR|模型预热|推理|瓶颈|截图|环境)", text, re.IGNORECASE)
        and not re.search(r"(咿呀喂|Yiyawei|语音编译器|语音指令编译器|目标界面|当前界面|粘贴|复制|停止录音|任务栏|窗口位置|功能规划)", text)
    )


def _looks_like_browser_annotation_feature(text: str) -> bool:
    return bool(
        re.search(r"(右侧浏览器|浏览器|浏览器上|标注|批注|圈注)", text, re.IGNORECASE)
        and re.search(r"(我们的这个界面|这个界面|语音界面|编译器界面|当前界面|界面)", text)
        and re.search(r"(放到|放在|打开到|展示到|嵌入到|搬到|移到|通过.{0,12}标注|直接.{0,12}标注|标注改|批注改)", text)
    )


def _looks_like_visual_generation(text: str) -> bool:
    if _looks_like_light_text_request(text):
        return False
    return bool(
        re.search(
            r"(作图|画图|绘图|生图|生成图|文生图|图生图|图片生成|图像生成|图片提示词|图像提示词|"
            r"生图提示词|画面提示词|配图|插画|海报|封面|banner|thumbnail|主视觉|KV|主图|商品主图|"
            r"电商主图|宣传图|营销图|广告图|分镜|分镜图|故事板|镜头图|image\s*2\.0|negative prompt)",
            text,
            re.IGNORECASE,
        )
        and not _looks_like_presentation_deck(text)
    )


def looks_like_product_plan_with_visual_subtask(text: str) -> bool:
    """Return true when image generation is one module in a broader product plan."""

    normalized = _cleanup(text)
    if not normalized or _looks_like_light_text_request(normalized):
        return False
    has_visual = bool(
        re.search(
            r"(作图|画图|生图|图片生成|批量.{0,8}(?:作图|生图|图片)|配图|image\s*2(?:\.0)?)",
            normalized,
            re.IGNORECASE,
        )
    )
    has_product_scope = bool(
        re.search(
            r"(项目|产品|软件|系统|平台|功能|模块|未来.{0,6}方向|项目.{0,8}方向|接入|MCP|后台)",
            normalized,
            re.IGNORECASE,
        )
    )
    has_orchestration = bool(
        re.search(
            r"(自动化|运营|根据.{0,16}数据.{0,16}(?:调整|优化)|出价策略|批量|接入|功能|模块|方向)",
            normalized,
            re.IGNORECASE,
        )
    )
    capability_patterns = (
        r"(广告|投放|广告支出|出价|获客|转化|用户开口|咨询成本)",
        r"(小红书|抖音|内容平台|平台后台|数据反馈|运营推广|自动化运营)",
        r"(笔记|文稿|文案|素材|照片|内容生成|自动化.{0,8}(?:写|生成|编辑))",
        r"(作图|画图|生图|图片生成|批量.{0,8}(?:作图|生图|图片)|配图|image\s*2(?:\.0)?)",
    )
    capability_count = sum(
        1 for pattern in capability_patterns if re.search(pattern, normalized, re.IGNORECASE)
    )
    return has_visual and has_product_scope and has_orchestration and capability_count >= 3


def _looks_like_presentation_deck(text: str) -> bool:
    if _looks_like_light_text_request(text):
        return False
    return bool(
        re.search(
            r"(PPT|ppt|幻灯片|slides?|presentation|deck|演示文稿|演示稿|汇报材料|路演材料|提案|宣讲稿|演讲稿|讲稿|课件)",
            text,
            re.IGNORECASE,
        )
    )


def _looks_like_ui_ux_design(text: str) -> bool:
    if _looks_like_voice_compiler_feedback(text) or _looks_like_visual_generation(text):
        return False
    return bool(re.search(r"(UI|UX|界面|视觉|交互|布局|设计稿|原型|页面风格|用户体验|移动端布局)", text, re.IGNORECASE))


def _looks_like_code_fix(text: str) -> bool:
    return bool(
        re.search(r"(修复|改代码|报错|异常|错误|bug|复现|排查|定位|接口不通|保存失败|提交异常|不生效|没生效)", text, re.IGNORECASE)
        and re.search(r"(代码|文件|函数|组件|接口|API|数据库|测试失败|日志|控制台|stack trace|traceback|字段|参数|配置)", text, re.IGNORECASE)
    )
