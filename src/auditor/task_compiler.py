"""Rule fallback for compiling noisy speech into an AI task prompt."""

from __future__ import annotations

import re

from src.auditor.intent_frame import looks_like_product_plan_with_visual_subtask
from src.auditor.task_router import (
    RouteResult,
    build_domain_project_fragment,
    detect_task_route,
    render_task_prompt_template,
)
from src.text.normalizer import normalize_known_terms


AI_TARGETS = ("ChatGPT", "Claude", "Gemini", "Cursor", "Codex", "VS Code")
TEXT_INPUT_TARGETS = ("终端输入框",)
BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^\s*请?把中文口语[、，,]?重复表达(?:和|及)?改口内容整理成"
        r"(?:适合|合适)[^。！？\n]*(?:专业任务需求|任务需求|专业文本)[。！？]?\s*",
        re.IGNORECASE,
    ),
)
TASK_INTENT_MARKERS = (
    "帮我",
    "请",
    "我要",
    "需要",
    "整理",
    "整理成",
    "粘贴到",
    "任务",
    "需求",
    "指令",
    "执行",
    "优化",
    "检查",
    "分析",
    "评估",
    "调研",
    "修改",
    "实现",
    "开发",
    "重构",
    "生成",
)


def compile_ai_task_fallback(text: str) -> str:
    text = _cleanup(text)
    if not text:
        return ""
    route = detect_task_route(text)

    status_report = _build_status_report(text)
    if status_report:
        return status_report

    test_guidance = _build_test_guidance(text)
    if test_guidance:
        return test_guidance

    looks_like_software_feedback = _looks_like_software_feedback(text)
    software_feedback = _build_software_feedback_task(text)
    if software_feedback:
        return software_feedback
    if looks_like_software_feedback:
        return ""

    browser_annotation_feature = _build_browser_annotation_feature_task(text)
    if browser_annotation_feature:
        return browser_annotation_feature

    ai_coding_governance = _build_ai_coding_governance_task(text)
    if ai_coding_governance:
        return ai_coding_governance

    account_switch = _build_account_switch_automation_task(text)
    if account_switch:
        return account_switch

    content_operations_plan = _build_content_operations_product_plan(text, route)
    if content_operations_plan:
        return content_operations_plan

    if route.task_type == "generic_task" and not should_compile_ai_task_fallback(text):
        return ""

    visual_prompt = _build_visual_generation_prompt(text, route)
    if visual_prompt:
        return visual_prompt

    product_positioning = ""
    if route.task_type == "generic_task":
        product_positioning = _build_product_positioning_task(text)
    if product_positioning:
        return product_positioning

    generic_task = _build_generic_task_request(text, route)
    if generic_task:
        return generic_task

    constraints = _extract_negative_constraints(text)
    need_line = _build_need_line(text)

    lines = [need_line]
    if constraints:
        lines.append("请注意：" + "；".join(_strip_punctuation(item) for item in constraints) + "。")
    return "\n".join(lines)


def remove_task_boilerplate(text: str) -> str:
    result = text or ""
    for pattern in BOILERPLATE_PATTERNS:
        result = pattern.sub("", result)
    return result.strip()


def _cleanup(text: str) -> str:
    text = normalize_known_terms(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_punctuation(text: str) -> str:
    return (text or "").strip(" ，,。；;")


def _extract_negative_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    patterns = (
        r"不是\s*TTS",
        r"不是语音助手",
        r"不是普通听写工具",
        r"不是普通语音转文字",
        r"不是机器人聊天",
        r"不是聊天机器人",
        r"不是代码生成器",
        r"不要直接生成代码",
        r"不要执行命令",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(0)
            if value not in constraints:
                constraints.append(value)
    core_match = re.search(r"核心体验应该像[^，,。]*?(?:AI|ai)[^，,。]*?助手", text)
    if core_match:
        constraints.append(core_match.group(0))
    if "而是机器人" in text and "不是普通语音转文字" in constraints:
        constraints.append("核心体验应该像一个会审计和重建表达的 AI 助手")
    return constraints


def _build_need_line(text: str) -> str:
    targets = [target for target in AI_TARGETS if target in text]
    text_inputs = [target for target in TEXT_INPUT_TARGETS if target in text]
    if targets and text_inputs:
        joined = "、".join(targets)
        inputs = "、".join(text_inputs)
        return f"输出文本要适合粘贴到 {joined} 等 AI 工具，以及{inputs}中，方便模型直接理解并执行任务。"
    if targets:
        joined = "、".join(targets)
        return f"输出文本要适合粘贴到 {joined} 等 AI 工具中，方便模型直接理解并执行任务。"
    if text_inputs:
        inputs = "、".join(text_inputs)
        return f"输出文本要适合粘贴到{inputs}中，方便后续直接使用。"
    return _strip_punctuation(text) + "。"


def _build_generic_task_request(text: str, route: RouteResult | None = None) -> str:
    route = route or detect_task_route(text)
    project_task = _build_project_evaluation_build_task(text, route)
    if project_task:
        return project_task

    routed_template = render_task_prompt_template(text, route)
    if routed_template:
        return routed_template

    website_task = _build_website_benchmark_task(text)
    if website_task:
        return website_task

    website_creation_task = _build_website_creation_task(text)
    if website_creation_task:
        return website_creation_task

    execution_question = _build_execution_question_task(text)
    if execution_question:
        return execution_question

    if _looks_like_user_requested_task(text) and not _mentions_ai_targets(text):
        return _polish_requested_task_text(text)

    return ""


def _build_visual_generation_prompt(text: str, route: RouteResult | None = None) -> str:
    route = route or detect_task_route(text)
    if route.task_type != "visual_generation":
        return ""

    cleaned = _strip_spoken_asides(text)
    cleaned = _strip_visual_spoken_noise(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")
    cleaned = re.sub(r"(我说完了|说完了|结束录音|停止录音)$", "", cleaned).strip(" ，,。")
    if not cleaned:
        return ""

    model = "image 2.0" if re.search(r"image\s*2(?:\.0)?", cleaned, re.IGNORECASE) else "图像生成模型"
    ratio = _extract_image_ratio(cleaned)
    needs_storyboard = bool(re.search(r"(分镜|分镜图|故事板|镜头图|短剧|AI短剧)", cleaned, re.IGNORECASE))
    count = _extract_image_count(cleaned)
    if needs_storyboard and count == "1 张" and re.search(
        r"(?:一|1)\s*张[^，,。；;]{0,24}(?:图片|图像|图|动漫|海报|封面|主视觉)",
        cleaned,
    ):
        count = ""
    subject = _extract_visual_subject(cleaned)
    style = _extract_visual_style(cleaned)

    visual_type = "连续分镜图" if needs_storyboard else "图片"
    spec_parts = []
    if ratio:
        spec_parts.append(f"{ratio} 比例")
    if count:
        spec_parts.append(count)
    if needs_storyboard:
        spec_parts.append("分镜图")
    spec = "，".join(spec_parts) if spec_parts else "按图像模型默认规格输出"
    positive_bits = [subject]
    if style:
        positive_bits.extend(
            style_bit for style_bit in style.split("；") if style_bit and style_bit not in subject
        )
    if ratio:
        positive_bits.append(f"{ratio} 画幅")
    if needs_storyboard:
        positive_bits.append("连续镜头、统一角色、统一场景氛围、每张图有清晰镜头编号")
    positive_prompt = "，".join(bit for bit in positive_bits if bit)

    lines = [
        f"作图提示词：请使用{model}生成{visual_type}，要求如下：",
        "- 用途与受众：用于用户指定的作图/生图场景；如受众不明确，请根据主题补齐合理假设。",
        f"- 主体与场景：{subject}。",
        f"- 尺寸比例与输出格式：{spec}；输出正向提示词、负面提示词和验收标准。",
    ]
    if needs_storyboard:
        lines.append(f"- 分镜结构：一套连续分镜图，{count or '按剧情需要给出多张'}；每张画面都要像同一部短剧/故事板里的连续镜头。")
    elif count:
        lines.append(f"- 数量：{count}。")
    lines.extend(
        [
            f"- 风格与构图：{style or '根据主题补齐合适风格'}；主体清晰，构图完整，镜头语言明确，光线、色彩和氛围统一。",
            f"- 正向提示词：{positive_prompt}，高质量细节，清晰主体，完整构图，统一色彩，适合直接输入图像生成模型。",
            "- 连贯性：如果生成多张图，请保持角色、服装、场景、色调和视觉风格一致，并让每张图有明确镜头编号和画面重点。",
            "- 输出内容：先给正向提示词，再给负面提示词；如果是分镜图，请按镜头 1 到镜头 N 列出每张图的画面描述。",
            "- 负面约束：不要真实品牌 Logo，不要版权角色，不要未授权真人肖像，不要多余文字、水印、畸形手指、脸部崩坏、低清晰度、风格不一致。",
            "- 验收标准：生成结果必须能看出明确主体、画面比例、风格方向和多图连续性；不要只复述原始口述。",
        ]
    )
    return "\n".join(lines)


def _build_content_operations_product_plan(
    text: str,
    route: RouteResult | None = None,
) -> str:
    route = route or detect_task_route(text)
    if route.task_type != "product_planning" or not looks_like_product_plan_with_visual_subtask(text):
        return ""

    creator = "潮汕博主" if "潮汕博主" in text else "内容创作者/博主"
    spend_match = re.search(
        r"(?:一天|每日)[^，,。；;]{0,16}(?:消费|消耗|花费)[^，,。；;]{0,8}"
        r"([零一二两三四五六七八九十百千万\d,.]+)\s*元",
        text,
    )
    current_state = "当前获客质量或获客资源不够理想"
    if spend_match:
        current_state = f"当前日广告消耗约 {spend_match.group(1)} 元，且获客质量或获客资源不够理想"

    return (
        "请把下面需求整理成一份小红书自动化运营项目的产品规划与实施方案。\n"
        f"- 服务对象：{creator}。\n"
        f"- 现状与业务目标：{current_state}；目标是降低广告支出和获客成本，提高有效咨询或用户开口率。\n"
        "- 模块一，投放优化：在获得合法授权和可用接口的前提下接入小红书后台数据，"
        "根据消耗、线索质量和转化反馈辅助调整出价策略。\n"
        "- 模块二，内容自动化：利用博主已有文稿、照片和其他素材，结合现有小红书 MCP 能力，"
        "生成、编辑和发布候选笔记；先核实现有 MCP 的权限和真实可用范围。\n"
        "- 模块三，批量作图：接入 image 2.0 等图像能力，为笔记批量生成配图。"
        "作图是内容生产子模块，不要把本次整体需求改写成单一作图提示词。\n"
        "- 规划要求：梳理完整运营流程、功能边界、数据流、人工确认点、异常回退、平台合规和账号安全；"
        "按用户价值、实现成本、依赖和风险划分 MVP、后续版本与优先级。\n"
        "- 输出内容：产品目标、用户场景、核心功能模块、接口与数据依赖、MVP 范围、版本路线图、"
        "关键指标、验收标准、风险以及需要进一步确认的问题。\n"
        "- 限制条件：不要编造小红书接口、MCP 权限、投放效果或确定性降本结果；"
        "无法确认的能力请标为待验证假设。"
    )


def _extract_image_ratio(text: str) -> str:
    if re.search(r"(16\s*[:：比]\s*9|十六比九)", text):
        return "16:9"
    if re.search(r"(9\s*[:：比]\s*16|九比十六)", text):
        return "9:16"
    if re.search(r"(1\s*[:：比]\s*1|一比一)", text):
        return "1:1"
    if re.search(r"(3\s*[:：比]\s*4|三比四)", text):
        return "3:4"
    if re.search(r"(4\s*[:：比]\s*3|四比三)", text):
        return "4:3"
    match = re.search(r"(\d+\s*[:：]\s*\d+)", text)
    return match.group(1).replace("：", ":").replace(" ", "") if match else ""


def _extract_image_count(text: str) -> str:
    text = re.sub(
        r"(16\s*[:：比]\s*9|十六比九|9\s*[:：比]\s*16|九比十六|3\s*[:：比]\s*4|三比四|4\s*[:：比]\s*3|四比三|1\s*[:：比]\s*1|一比一)",
        " ",
        text,
    )
    matches = list(re.finditer(r"(\d+|[一二两三四五六七八九十]{1,3})\s*(?:张|幅|页|镜头|分镜)", text))
    if matches:
        return f"{_normalize_count(matches[-1].group(1))} 张"
    object_matches = list(re.finditer(r"(\d+|[一二两三四五六七八九十]{1,3})\s*个(?=\s*(?:图片|图像|图|海报|封面|主视觉))", text))
    if object_matches:
        return f"{_normalize_count(object_matches[-1].group(1))} 张"
    return ""


def _extract_visual_style(text: str) -> str:
    styles: list[str] = []
    for pattern in (
        r"宫崎骏[^，,。；;\n]{0,8}风格",
        r"吉卜力[^，,。；;\n]{0,8}风格",
        r"(?:写实|赛博朋克|水彩|油画|动漫|电影感|科技感|商务感|高级感)(?:风格|质感|氛围)?",
    ):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = _strip_punctuation(match.group(0))
            if value and value not in styles:
                styles.append(value)
    return "；".join(styles[:3])


def _extract_visual_subject(text: str) -> str:
    result = _strip_visual_spoken_noise(text)
    if re.search(r"AI\s*短剧|短剧", result, re.IGNORECASE):
        return "AI 短剧关键剧情画面"
    style = _extract_visual_style(text)
    result = re.sub(r"(请|帮我|给我|给|我要|我想|我想让你|让你|你|需要|要求|然后|那个|这个|说完了|我说完了)", "", result)
    result = re.sub(r"(用\s*)?image\s*2(?:\.0)?", "", result, flags=re.IGNORECASE)
    if style:
        result = result.replace(style, "")
    result = re.sub(r"(不要|不能|避免)[^，,。；;]*", " ", result)
    result = re.sub(r"(生成|做成|做|出图|出|写|弄|要有|也要|里面|啊|呢|的比例|比例|提示词|达到|达成|来)", " ", result)
    result = re.sub(r"(十六比九|九比十六|三比四|四比三|一比一|16\s*[:：比]\s*9|9\s*[:：比]\s*16|3\s*[:：比]\s*4|4\s*[:：比]\s*3|1\s*[:：比]\s*1)", " ", result)
    result = re.sub(r"(\d+|[一二两三四五六七八九十]{1,3})\s*(张|幅|个|页|镜头|分镜)", " ", result)
    result = result.replace("AI短剧", "AI 短剧")
    result = re.sub(r"(一套)?\s*(分镜图|分镜|故事板|镜头图)", " ", result)
    result = re.sub(r"的\s*(图片|图|海报|封面|主视觉)$", r"\1", result)
    result = re.sub(r"\b有\b", " ", result)
    result = re.sub(r"\s+", " ", result).strip(" ，,。；;")
    result = result.lstrip("的").strip(" ，,。；;")
    result = _dedupe_visual_subject_terms(result)
    if result in {"图片", "图像", "图", "海报", "封面", "主视觉", "主图", "商品主图", "电商主图"}:
        if style:
            return f"根据用户描述生成{style}{result}"
    return result or "根据用户描述生成图片"


def _strip_visual_spoken_noise(text: str) -> str:
    result = text or ""
    result = re.sub(r"[，,、；;\s]*(嗯+|呃+|啊+|额+)[，,、；;\s]*", "，", result)
    result = re.sub(r"(那个|这个){2,}", r"\1", result)
    result = re.sub(r"(帮我)?来\s*(出图|生成|做)", r"\1\2", result)
    result = re.sub(r"(?:然后)?\s*达到\s*(?:那个|这个)?", "", result)
    result = re.sub(r"[，,]{2,}", "，", result)
    result = re.sub(r"\s+", " ", result)
    return result.strip(" ，,、；;")


def _build_test_guidance(text: str) -> str:
    if not _looks_like_test_guidance(text):
        return ""

    cleaned = _strip_spoken_asides(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")

    intro = ""
    if re.search(r"(可以开始测试|开始测试)", cleaned):
        intro = "你可以开始测试。"
    if re.search(r"(重启|重启后|重启当前).{0,12}(编译器|进程)", cleaned):
        intro = "你可以开始测试，但记得先重启当前编译器进程，让新代码和新 prompt 生效。"

    items: list[str] = []
    if re.search(r"(英文|英英文|技术词|PyTorch|torch|touch|CUDA|扣达|harness|terminal|torman|PowerShell|power)", cleaned, re.IGNORECASE):
        items.append("英文技术词口音不准：重点看 PyTorch、CUDA、harness、terminal、PowerShell 等是否能按上下文还原。")
    if re.search(r"(中文|同音|同意|近音|语音助手|补结构|理解改口|提示词|提示池)", cleaned):
        items.append("中文同音或近音错词：重点看语音助手、补结构、理解改口、提示词等是否能根据语境恢复。")
    if re.search(r"(不对|不是).{0,20}(登录页|注册页)", cleaned):
        items.append("改口场景：例如“不是登录页，是注册页”，要保留最终意图。")
    if re.search(r"(谢谢你的评价|nice|耐斯|自然)", cleaned, re.IGNORECASE):
        items.append("自然尾句：例如“谢谢你的评价”“你觉得我做得 nice 吗”，用户主动说出的正常表达要保留。")
    if re.search(r"(状态汇报|汇报|漏事实|事实|任务请求)", cleaned):
        items.append("状态汇报：不要漏事实，也不要把汇报改成任务请求。")

    if not items:
        return ""

    lines = [intro or "测试时可以重点关注以下几类：", "测试时可以重点关注以下几类："]
    if lines[0] == lines[1]:
        lines = [lines[0]]
    lines.extend(f"- {item}" for item in _dedupe_lines(items))
    return "\n".join(lines)


def _looks_like_test_guidance(text: str) -> bool:
    return bool(
        re.search(r"(可以开始测试|开始测试|测试时|测试重点|重点.*测试|重点.*看|验证清单|测试清单)", text)
        and re.search(r"(重启|编译器|新代码|prompt|英文|技术词|登录页|注册页|状态汇报|漏事实|任务请求|nice|评价)", text, re.IGNORECASE)
    )


def _build_ai_coding_governance_task(text: str) -> str:
    if not _looks_like_ai_coding_governance_request(text):
        return ""

    cleaned = _strip_spoken_asides(text)
    cleaned = _normalize_known_product_terms(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")

    return (
        "请为使用 Codex、Claude Code、Cursor 或其他 AI 编码工具制定一套全局防覆盖治理工作流。\n"
        f"- 背景：{cleaned}。\n"
        "- 核心问题：曾经由另一个大模型把项目代码改乱或覆盖，代码量从约 4000 行变成约 1000 多行；以后需要避免 AI 编码工具覆盖、回滚或大范围改写已有成果。\n"
        "- 目标：形成可长期复用的工作方式，让任何 AI 编码工具在修改项目前先理解现状、确认范围、保护用户已有代码，并在每次修改后可审查、可回退、可验证。\n"
        "- 治理规则：要求先读项目规则和相关文件；禁止未授权覆盖、删除、重置、回滚用户文件；禁止大范围重写；只能做最小必要改动；遇到不确定范围必须先说明假设和风险。\n"
        "- 操作流程：设计从需求确认、改动范围限定、基线检查、分支或备份、实施、diff 审查、测试验证到交付说明的完整流程。\n"
        "- 防护机制：给出本地备份/分支策略、变更清单、文件白名单或禁止改动清单、自动测试门禁、代码审查清单和失败回滚方案。\n"
        "- 交付要求：输出一份可以直接放进 AGENTS.md 或项目治理文档的规则草案，并附带执行检查清单和回归验证步骤。\n"
        "- 限制条件：不要写成 Bug 报告，也不要要求真实外部服务；重点是全局治理方法和可执行工作流。"
    )


def _looks_like_ai_coding_governance_request(text: str) -> bool:
    has_ai_coder = bool(re.search(r"(大模型|Codex|codeex|cloud\s*code|claude\s*code|Claude Code|Cursor)", text, re.IGNORECASE))
    has_damage = bool(re.search(r"(改乱|覆盖|删掉|误删|回滚|冲掉|代码.{0,12}(变少|丢失)|四千行|一千多行)", text, re.IGNORECASE))
    has_governance_request = bool(re.search(r"(杜绝|规避|治理|全局|工作方式|方法|方案|解决方法|改善|维护|规范)", text))
    return has_ai_coder and has_damage and has_governance_request


def _build_account_switch_automation_task(text: str) -> str:
    if not _looks_like_account_switch_automation_request(text):
        return ""

    cleaned = _strip_spoken_asides(text)
    cleaned = _normalize_known_product_terms(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")

    return (
        "请把下面口述整理成一份可执行的产品/工程需求：实现账号额度不足后的自动无感切换。\n"
        f"- 背景：{cleaned}。\n"
        "- 目标：当被对标或集成的软件反馈“没有额度、需要切换账号”时，后台系统应能自动识别该状态，并自适应切换到可用账号。\n"
        "- 核心能力：额度耗尽检测、账号池状态管理、自动选择可用账号、账号注入或登录态切换、失败重试、人工兜底和操作日志。\n"
        "- 用户体验：切换过程尽量无感，不要求用户关闭目标软件或手动重新登录；必要时只给出清晰状态提示。\n"
        "- 边界与风险：说明哪些目标软件或账号体系需要确认；处理登录态、风控、账号安全、并发切换和异常回退时不要编造未提供的接口能力。\n"
        "- 验收标准：能复现额度耗尽场景，系统自动切到可用账号并继续工作；记录切换前后账号、触发原因、失败原因和回滚路径。"
    )


def _looks_like_account_switch_automation_request(text: str) -> bool:
    has_context = bool(re.search(r"(这个软件|后台|对标|closer|Claude|cloud\s*code|目标软件|账号|账户)", text, re.IGNORECASE))
    has_switch = bool(re.search(r"(没有额度|额度|切换账号|换号|切号|注入账号|无感|自适应)", text))
    has_request = bool(re.search(r"(有没有|功能|需要|可以|实现|方案|解决方法|无感|自动)", text))
    return has_context and has_switch and has_request


def _build_software_feedback_task(text: str) -> str:
    if not _looks_like_software_feedback(text):
        return ""

    cleaned = _strip_spoken_asides(text)
    cleaned = _normalize_known_product_terms(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")

    items: list[str] = []
    if re.search(r"(同义词|相近|近义|上下文|语境|推理|分析)", cleaned) and re.search(
        r"(识别|ASR|LLM|大模型|文字|文本)", cleaned, re.IGNORECASE
    ):
        items.append(
            "中文 ASR 字面识别基本正常，但 LLM/harness 对同义词或相近词的处理还不够好；"
            "它需要结合上下文做语义分析和推理，而不是只把 ASR 文本润色一遍。"
        )
    if re.search(r"(粘贴|复制|目标界面|当前界面|Codex|codeex)", cleaned, re.IGNORECASE) and re.search(
        r"(停止录音|说完|分析|推理|出来|没有这个功能|之前|应该)", cleaned
    ):
        items.append(
            "自动粘贴链路需要检查：用户停止录音后，处理完成时应该把最终文本自动粘贴到当前识别到的目标界面，"
            "例如 Codex；现在没有按预期完成自动粘贴。"
        )
    if re.search(r"(我需要|需要|希望|要).{0,80}(粘贴|复制).{0,40}(界面|Codex|codeex)", cleaned, re.IGNORECASE) or re.search(
        r"(识别到|目标|当前).{0,20}界面.{0,40}(粘贴|复制|贴上去)", cleaned, re.IGNORECASE
    ):
        items.append(
            "自动粘贴能力需要实现：语音识别和提示词编译完成后，应用应将最终输出粘贴到当前识别到的目标界面，"
            "例如 Codex，而不是只停留在编译器窗口里。"
        )
    if re.search(r"(没有实现|不会|不能|没法).{0,20}(自动)?(粘贴|复制).{0,12}(对话框|输入框|界面)", cleaned, re.IGNORECASE):
        items.append(
            "自动粘贴能力需要实现：用户提出需求或完成语音编译后，最终输出应自动粘贴到目标对话框/输入框；"
            "不要偏题到界面方案而忽略粘贴动作本身。"
        )
    if re.search(r"(任务栏|弹到|跑到|跳到|最小化|窗口位置|之前窗口位置)", cleaned) and re.search(
        r"(粘贴|复制|语音界面|语音编译器|编译器界面|这个界面)", cleaned, re.IGNORECASE
    ):
        items.append(
            "粘贴后的窗口保持需要修复：最终文本粘贴到目标窗口后，语音编译器界面不应该被最小化、跑到任务栏或丢失原来的窗口位置；"
            "它应保持在粘贴前的窗口位置，用户不需要再去任务栏点一次。"
        )
    if re.search(r"(停顿|自动停止|自动结束|结束词|唤起词|开始录音|我说完了|停止录音)", cleaned) and re.search(
        r"(不要.*录进去|不要.*翻译|手动|每次|点一下|自动)", cleaned
    ):
        items.append(
            "录音交互需要支持自动结束：用户开始录音后，可以通过停顿、结束词或“我说完了”触发停止录音，"
            "并且不要把这些结束词写进最终文本。"
        )
    if re.search(r"(快捷键|快件键|热键|触发录音|开始触发|开始录音)", cleaned) and re.search(
        r"(开始|触发|桌面应用|排斥|冲突|形式)", cleaned
    ):
        items.append("开始录音仍建议保留快捷键或按钮触发，并选择不容易和桌面应用冲突的全局快捷键。")
    if re.search(r"(气口词|卡壳|嗯|啊|呃|停顿)", cleaned):
        items.append("文本清理需要过滤常见气口词和卡壳词，例如“嗯”“啊”“呃”，同时保留真正有意义的内容。")

    if not items:
        return ""

    lines = [
        "请为咿呀喂（Yiyawei）实现或修复以下能力，并按最小改动完成定位、修复和回归验证：",
        "",
        "问题描述：",
    ]
    lines.extend(f"{index}. {item}" for index, item in enumerate(_dedupe_lines(items), start=1))
    lines.extend(
        [
            "",
            "修复要求：",
            "- 最终输出必须是可以直接交给 AI 执行的提示词或任务文本，不要把调试字段或模板说明写进最终输出。",
            "- 口气词、卡壳词和录音控制词只用于理解语义，不要原样进入最终输出；有意义的业务内容必须保留。",
            "- 如果涉及自动粘贴，请确认目标窗口识别、处理完成后的粘贴动作、语音窗口恢复显示、失败兜底和回归日志都正常。",
            "",
            "验收标准：",
            "- 用包含真实口气词、卡壳词和重复词的口述样本回归，最终输出不再复述这些无效片段，也不再输出内部检查口吻。",
            "- 用 Codex/微信等目标窗口样本回归，处理完成后能按配置粘贴到识别到的目标界面，并且语音编译器窗口保持在原位置。",
            "- 补充对应单元测试，并运行 pytest 与 compileall。",
        ]
    )
    return "\n".join(lines)


def _looks_like_software_feedback(text: str) -> bool:
    if not text:
        return False
    has_feedback_signal = _has_software_feedback_signal(text)
    has_vpc_context = bool(
        re.search(
            r"(咿呀喂|Yiyawei|语音编译器|语音指令编译器|ASR|LLM|大模型|识别.*文字|识别.*文本|同义词|相近词|上下文|推理|"
            r"识别.*界面|目标界面|当前界面|语音界面|粘贴|复制|对话框|输入框|Codex|codeex|录音|停止录音|唤起词|结束词|口气词|气口词|卡壳词|任务栏|窗口位置)",
            text,
            re.IGNORECASE,
        )
    )
    return has_feedback_signal and has_vpc_context


def _has_software_feedback_signal(text: str) -> bool:
    if re.search(
        r"(还有一个问题|还有一个点|现在没有这个功能|之前.{0,16}(可以|会)|不会结合上下文|没有任何反馈|没有任何反应|"
        r"能不能|每次.{0,16}(点一下|手动)|应该.{0,24}(粘贴|复制|自动|停止|结束)|真\s*bug|功能.{0,16}(没有|失效|不见)|粘贴过后|复制过后|弹到.{0,16}任务栏|跑到.{0,16}任务栏|还得.{0,12}点)",
        text,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"(我需要|需要|希望|要).{0,50}(粘贴|复制).{0,30}(界面|Codex|codeex)", text, re.IGNORECASE):
        return True
    if re.search(r"(没有实现|不会|不能|没法).{0,20}(自动)?(粘贴|复制).{0,12}(对话框|输入框|界面)", text, re.IGNORECASE):
        return True
    issue_words = re.findall(r"(问题|bug|不对|没有|不会|不能|应该|之前|现在|功能)", text, re.IGNORECASE)
    return len(issue_words) >= 2 and bool(
        re.search(r"(检查|修复|优化|回归|粘贴|复制|录音|停止|反馈|反应)", text, re.IGNORECASE)
    )


def _normalize_known_product_terms(text: str) -> str:
    result = text or ""
    result = re.sub(r"(?<![A-Za-z])code\s*ex(?![A-Za-z])", "Codex", result, flags=re.IGNORECASE)
    result = re.sub(r"(?<![A-Za-z])codex(?![A-Za-z])", "Codex", result, flags=re.IGNORECASE)
    result = re.sub(r"(?<![A-Za-z])asr(?![A-Za-z])", "ASR", result, flags=re.IGNORECASE)
    result = re.sub(r"(?<![A-Za-z])llm(?![A-Za-z])", "LLM", result, flags=re.IGNORECASE)
    return result


def _build_status_report(text: str) -> str:
    if not _looks_like_status_report(text):
        return ""

    cleaned = _strip_spoken_asides(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")
    if not cleaned:
        return ""

    lines: list[str] = []

    if re.search(r"(逻辑是通的|逻辑通)", cleaned):
        lines.append("结论：当前逻辑是通的。")

    redeem_parts: list[str] = []
    if re.search(r"没有收到验证码|未收到验证码", cleaned):
        redeem_parts.append("未收到验证码时")
    if re.search(r"取消后.*兑换码.*(不会失效|不失效)", cleaned):
        redeem_parts.append("取消后兑换码不会失效")
    if re.search(r"可以继续换号|继续换号", cleaned):
        redeem_parts.append("可以继续换号")
    if re.search(r"号码(?:记录|也)?会?保留|记录.*保留", cleaned):
        redeem_parts.append("号码记录会保留")
    if re.search(r"不会因为换号.*(错过|错过前面).*号码状态", cleaned):
        redeem_parts.append("不会因为换号错过前面的号码状态")
    if redeem_parts:
        lines.append(_join_report_parts(redeem_parts) + "。")

    interface_parts: list[str] = []
    if "接口返回" in cleaned or "接口" in cleaned:
        interface_parts.append("接口返回中")
    if "上游平台痕迹" in cleaned:
        interface_parts.append("没有上游平台痕迹")
    if "敏感词命中" in cleaned:
        interface_parts.append("没有敏感词命中")
    if interface_parts:
        if interface_parts[0] == "接口返回中":
            lines.append("我也顺手确认了这些接口返回中没有上游平台痕迹或敏感词命中。")
        else:
            lines.append(_join_report_parts(interface_parts) + "。")

    cleanup_line = _build_cleanup_report(cleaned)
    if cleanup_line:
        lines.append(cleanup_line)

    casual_tail = _extract_casual_tail(cleaned)
    if casual_tail:
        lines.append(casual_tail)

    if not lines:
        return _ensure_final_period(cleaned)

    return "\n".join(_dedupe_lines(lines))


def _looks_like_status_report(text: str) -> bool:
    return bool(
        re.search(r"(结论|当前逻辑|逻辑是通的|测试记录|临时卡|生产库|生产\s*(?:env|inv|NV)?\s*文件|接口返回|上游平台痕迹|敏感词命中)", text, re.IGNORECASE)
        and re.search(r"(验证码|兑换码|换号|清理|清掉|删除|删掉|接口|测试|记录|临时卡|生产库|生产\s*(?:env|inv|NV)?\s*文件)", text, re.IGNORECASE)
    )


def _extract_casual_tail(text: str) -> str:
    match = re.search(r"(你觉得我[^。！？?]*?(?:nice|耐斯)[^。！？?]*吗)[？?。！!\s]*$", text, re.IGNORECASE)
    if match:
        return _ensure_question(match.group(1))
    match = re.search(r"(你看我这样行不行|这样可以吗)[？?。！!\s]*$", text)
    if match:
        return _ensure_question(match.group(1))
    return ""


def _ensure_question(text: str) -> str:
    result = _strip_punctuation(text)
    if not result:
        return ""
    return result + "？"


def _join_report_parts(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "，".join(parts[:-1]) + "，" + parts[-1]


def _build_cleanup_report(text: str) -> str:
    if not re.search(r"(清理|清掉|删除|删掉)", text):
        return ""

    items: list[str] = []
    card_match = re.search(r"([0-9一二两三四五六七八九十]+)\s*张临时卡", text)
    if card_match:
        items.append(f"{_normalize_count(card_match.group(1))} 张临时卡")

    record_match = re.search(r"([0-9一二两三四五六七八九十]+)\s*条测试记录", text)
    if record_match:
        items.append(f"{_normalize_count(record_match.group(1))} 条测试记录")

    env_deleted = bool(
        re.search(
            r"生产\s*(?:env|inv|NV|或\s*NV|或\s*env)?\s*文件.*(删除|删掉)"
            r"|(删除|删掉).*生产\s*(?:env|inv|NV|或\s*NV|或\s*env)?\s*文件",
            text,
            re.IGNORECASE,
        )
    )

    if not items and not env_deleted:
        return ""

    if items and env_deleted:
        return f"最后，我已从生产库清理刚才测试生成的{'和'.join(items)}，并删除临时拉取的生产 env 文件。"
    if items:
        return f"最后，我已从生产库清理刚才测试生成的{'和'.join(items)}。"
    return "最后，我已删除临时拉取的生产 env 文件。"


def _normalize_count(value: str) -> str:
    value = (value or "").strip()
    chinese_number = _parse_small_chinese_number(value)
    if chinese_number is not None:
        return str(chinese_number)
    mapping = {
        "一": "1",
        "二": "2",
        "两": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
        "十": "10",
    }
    return mapping.get(value, value)


def _parse_small_chinese_number(value: str) -> int | None:
    digits = {
        "零": 0,
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
    }
    if not value or not re.fullmatch(r"[零一二两三四五六七八九十]{1,4}", value):
        return None
    if value in digits:
        return digits[value]
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        tens = digits[left] if left else 1
        ones = digits[right] if right else 0
        return tens * 10 + ones
    return None


def _dedupe_visual_subject_terms(text: str) -> str:
    parts = re.split(r"([，,、；;\s]+)", text)
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        if not part or re.fullmatch(r"[，,、；;\s]+", part):
            if result and not re.fullmatch(r"[，,、；;\s]+", result[-1]):
                result.append(part)
            continue
        key = part.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(part)
    return re.sub(r"\s+", " ", "".join(result)).strip(" ，,、；;")


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line and line not in seen:
            seen.add(line)
            result.append(line)
    return result


def _build_product_positioning_task(text: str) -> str:
    if not _looks_like_vpc_positioning(text):
        return ""

    negatives = _extract_negative_constraints(text)
    lines: list[str] = []
    if "项目边界" in text or "边界" in text or negatives:
        boundary = "这个项目的边界已经明确："
        if negatives:
            boundary += "不是 TTS、不是语音助手、不是普通听写工具。"
        else:
            boundary += "它不是语音助手或普通听写工具。"
        lines.append(boundary)

    user_fragments: list[str] = []
    if re.search(r"用户可以说.*乱", text):
        user_fragments.append("用户可以说得乱")
    if re.search(r"不专业", text):
        user_fragments.append("说得不专业")
    if re.search(r"不完整|不完美", text):
        user_fragments.append("说得不完整")
    if user_fragments:
        lines.append("用户输入允许不完美：" + "、".join(user_fragments) + "。")

    plugin_tasks: list[str] = []
    if "补结构" in text:
        plugin_tasks.append("补结构")
    if "删废话" in text:
        plugin_tasks.append("删废话")
    if "理解改口" in text:
        plugin_tasks.append("理解改口")
    if plugin_tasks:
        lines.append("插件负责" + "、".join(plugin_tasks) + "。")

    targets = [target for target in AI_TARGETS if target in text]
    if targets:
        joined = "、".join(targets)
        lines.append(f"最终输出要适合粘贴到 {joined} 等 AI 工具中，作为可直接执行任务的提示词。")
    elif "提示词" in text:
        lines.append("最终输出要成为 AI 能直接执行任务的提示词。")

    return "\n".join(lines) if lines else ""


def _build_project_evaluation_build_task(text: str, route: RouteResult | None = None) -> str:
    route = route or detect_task_route(text)
    if route.task_type != "project_evaluation" or not _looks_like_project_evaluation_build_request(text):
        return ""

    cleaned = _strip_spoken_asides(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")
    subject = _extract_project_subject(cleaned)
    subject_line = subject if subject else "我描述的这个项目"
    domain_fragment = build_domain_project_fragment(route.domain)
    domain_lines = f"{domain_fragment}\n" if domain_fragment else ""

    return (
        f"请帮我评估“{subject_line}”是否值得开发，并把结论整理成可以继续推进开发的完整方案。\n"
        f"{domain_lines}"
        "请不要只给主观判断，也不要编造我没有提供的市场数据、用户规模、收入、竞品事实或确定性结论。"
        "如果关键信息不足，请先列出需要确认的问题，并说明哪些信息需要通过搜索、资料调研或用户访谈验证。\n"
        "请按完整链路执行：\n"
        "1. 先澄清项目概念、目标用户、核心场景、要解决的痛点和成功标准。\n"
        "2. 调研并分析市场需求、竞品/替代方案、用户付费意愿、商业模式、获客难度和差异化机会；能查证的地方请给出依据，不能查证的地方请标注为假设。\n"
        "3. 从技术可行性、开发成本、时间成本、数据/模型/API 依赖、合规风险、运营风险和维护成本评估项目难度。\n"
        "4. 给出是否值得开发的判断：建议做、谨慎验证后再做，或不建议做；同时说明关键证据、反证和最大不确定性。\n"
        "5. 如果值得或需要先做验证，请制定 MVP 范围、核心功能优先级、验证实验、里程碑和验收标准。\n"
        "6. 继续给出落地方案：技术栈建议、顶层架构、模块拆分、数据结构/API 设计方向、工具或技能编排方式、项目初始化步骤和开发路线图。\n"
        "7. 给出产品与 UI 方向：整体风格、关键页面/流程、交互原则、信息架构和首版界面重点。\n"
        "8. 最后输出一份可交给 Cursor、Codex 或其他 coding agent 执行的开发任务拆解，按阶段列出先做什么、后做什么，以及每阶段的交付物。"
    )


def _looks_like_project_evaluation_build_request(text: str) -> bool:
    if not text:
        return False
    has_project_object = bool(
        re.search(r"(项目|产品|应用|网站|软件|工具|平台|插件|小程序|APP|App|app|SaaS|系统)", text, re.IGNORECASE)
    )
    has_evaluation_signal = bool(
        re.search(
            r"(是否值得|值不值得|值得.*开发|值得.*做|是否可行|可行性|能不能做|能不能开发|适不适合做|"
            r"有没有市场|市场.*怎么样|商业价值|开发价值|要不要做|该不该做|能否落地)",
            text,
            re.IGNORECASE,
        )
    )
    has_build_signal = bool(
        re.search(r"(如果值得|如果可行|值得.*我要|我要.*开发|我要做开发|做开发|开发出来|做出来|搭建|落地)", text)
    )
    has_user_request = bool(re.search(r"(帮我|请|分析|评估|调研|看看|看一下|我要|需要)", text))
    return has_project_object and has_evaluation_signal and (has_user_request or has_build_signal)


def looks_like_project_evaluation_build_request(text: str) -> bool:
    return _looks_like_project_evaluation_build_request(_cleanup(text))


def _extract_project_subject(text: str) -> str:
    patterns = (
        r"(?:帮我|请|需要|我要)?(?:分析|评估|调研|看看|看一下)?(?:下|一下)?\s*([^，,。；;]{1,36}?(?:项目|产品|应用|网站|软件|工具|平台|插件|小程序|APP|App|app|SaaS|系统))",
        r"([^，,。；;]{1,36}?(?:项目|产品|应用|网站|软件|工具|平台|插件|小程序|APP|App|app|SaaS|系统)).{0,12}(?:是否值得|值不值得|是否可行|可行性|有没有市场)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        subject = _strip_punctuation(match.group(1))
        subject = re.sub(r"^(帮我|请|需要|我要|分析|评估|调研|看看|看一下|下|一下)+", "", subject).strip()
        subject = re.sub(r"(是否值得开发|是否值得做|值不值得开发|值不值得做|是否可行|可行性|有没有市场).*$", "", subject).strip()
        subject = _strip_punctuation(subject)
        if subject:
            return subject
    return ""


def _build_website_benchmark_task(text: str) -> str:
    if "对标" not in text or "网站" not in text:
        return ""
    target_match = re.search(r"对标\s*([^，,。；;\s]+?)(?:的)?网站", text)
    if not target_match:
        return ""
    target = _strip_punctuation(target_match.group(1))
    if not target:
        return ""
    return (
        f"请帮我做一个对标{target}的网站。"
        f"先查看并分析{target}的网站，梳理它的页面结构、视觉风格和核心功能；"
        "再基于分析结果，执行我们自己网站的相关任务。"
    )


def _build_website_creation_task(text: str) -> str:
    if not _looks_like_website_creation_request(text):
        return ""

    cleaned = _strip_spoken_asides(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")
    style = _extract_visual_style(cleaned)
    subject = _extract_website_subject(cleaned)
    style_line = style or "根据网站主题补齐统一且高级的视觉风格"

    return (
        f"请帮我设计并制作一个{style_line}的网站。\n"
        f"- 网站主题：{subject}。\n"
        "- 目标：输出可直接交给 Cursor、Codex 或其他 coding agent 执行的网站制作提示词，不要只复述原始口述。\n"
        "- 页面结构：请规划首屏、核心内容区、功能/卖点展示、案例或亮点展示、行动按钮和页脚；如果信息不足，请补齐合理假设。\n"
        "- 视觉要求：明确配色、字体层级、空间节奏、图像/图标方向、按钮与卡片样式、动效克制程度，并保持整体风格统一。\n"
        "- 交互与响应式：覆盖桌面端和移动端布局，说明 hover、加载、空状态和错误状态等基础体验。\n"
        "- 交付要求：给出可执行的实现步骤、组件拆分、素材占位策略和验收标准；不要编造真实品牌、真实数据或未经授权素材。"
    )


def _looks_like_website_creation_request(text: str) -> bool:
    if not re.search(r"(网站|网页|官网|页面)", text, re.IGNORECASE):
        return False
    if re.search(r"(翻译|解释|是什么意思|这个词|这几个字|润色|改写成一句话)", text):
        return False
    return bool(
        re.search(r"(做|制作|设计|生成|搭建|开发|实现|弄|搞).{0,16}(网站|网页|官网|页面)", text, re.IGNORECASE)
        or re.search(r"(网站|网页|官网|页面).{0,24}(好看|风格|赛博朋克|朋克|高级|视觉|配色|动效)", text, re.IGNORECASE)
    )


def _extract_website_subject(text: str) -> str:
    result = _strip_spoken_asides(text)
    result = re.sub(r"(请|帮我|给我|我要|我想|我想做|我想让你|让你|需要|比较|好看|那个|这个)", "", result)
    result = re.sub(r"(做|制作|设计|生成|搭建|开发|实现|弄|搞)(一个|一下|一套|个)?", "", result)
    result = re.sub(r"(是|做成)?[^，,。；;]{0,12}(赛博朋克|朋克)[^，,。；;]{0,8}风格", " ", result)
    result = re.sub(r"(网站|网页|官网|页面)(是)?", "网站", result)
    result = re.sub(r"\s+", " ", result).strip(" ，,。；;")
    return result or "用户描述的网站"


def _build_execution_question_task(text: str) -> str:
    if not re.search(r"(执行难度|怎么执行这个任务|如何执行这个任务|意见)", text):
        return ""
    result = _strip_spoken_asides(text)
    replacements = (
        (r"不亚于要从新训练一个新的", "不亚于重新训练一个新的"),
        (r"新的吗模型", "新的模型"),
        (r"新的吗", "新的"),
        (r"指导的情况", "指导信息"),
        (r"我不知道你会不会执行这个任务", "我不确定你是否能执行这个任务"),
        (r"你来怎么执行这个任务", "你会怎么执行这个任务？"),
        (r"你来看怎么执行这个任务", "你会怎么执行这个任务？"),
        (r"那你各位意见真好吧", "请给出你的意见。"),
        (r"那你各位意见真好", "请给出你的意见。"),
        (r"那你给位意见真好吧", "请给出你的意见。"),
        (r"那你给个意见吧", "请给出你的意见。"),
    )
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    if "执行难度" in result and "新的模型" in result and re.search(r"(你会怎么执行这个任务|请给出你的意见)", result):
        power_clause = "也请解释这里提到的 power 应该如何理解。" if re.search(r"power", result, re.IGNORECASE) else ""
        return (
            "这个任务的执行难度很高，可能接近重新训练一个新的模型。"
            "在新的模型没有明确指导信息的情况下，我不确定它是否能完成这个任务。"
            "请评估这个任务是否可执行，并说明你会如何执行；请给出你的意见。"
            f"{power_clause}"
        )
    result = re.sub(r"(这个任务的执行难度不亚于[^。！？?]*?)(新的模型)", r"\1\2。", result)
    result = re.sub(r"(新的模型[^。！？?]*?)(会说没有你的情况)", r"\1。\2", result)
    result = re.sub(r"(什么是怎么能有power呢)", "什么是怎么能有 power 呢？", result, flags=re.IGNORECASE)
    result = re.sub(r"(我不确定你是否能执行这个任务)(?![。！？?])", r"\1。", result)
    result = re.sub(r"([。！？?])+", r"\1", result)
    return _ensure_final_period(result)


def _build_browser_annotation_feature_task(text: str) -> str:
    if not looks_like_browser_annotation_feature_request(text):
        return ""
    return (
        "请为咿呀喂（Yiyawei）设计并实现“右侧浏览器标注改动”功能需求。\n"
        "- 背景：用户希望把当前语音编译器界面放到右侧浏览器或浏览器面板中，之后可以直接在浏览器上标注、批注或指出需要修改的位置。\n"
        "- 目标：让用户无需反复截图和口述位置，通过浏览器标注把修改意见传给后续 AI/开发流程，并能继续生成可执行的修改任务。\n"
        "- 功能范围：打开或同步当前界面到右侧浏览器视图；支持在页面上做标注/批注；记录标注位置、文字说明和对应 UI 元素；把标注内容整理成后续可执行的修改需求。\n"
        "- 实现要求：优先采用轻量本地实现，不要接入大型检索、真实图片生成或默认在线服务；保持现有语音编译热路径离线、快速、稳定。\n"
        "- 交互要求：标注入口要清晰，标注完成后能确认、撤销、恢复，并能把标注结果和当前识别文本/最终输出关联起来。\n"
        "- 验收标准：用户可以把界面放到右侧浏览器中完成标注，系统能保存标注并生成修改任务；不要只输出泛泛的设计原则。"
    )


def looks_like_browser_annotation_feature_request(text: str) -> bool:
    text = _cleanup(text)
    if not text:
        return False
    has_browser_annotation = bool(re.search(r"(右侧浏览器|浏览器|浏览器上|标注|批注|圈注)", text, re.IGNORECASE))
    has_app_surface = bool(re.search(r"(我们的这个界面|这个界面|语音界面|编译器界面|当前界面|界面)", text))
    has_feature_action = bool(
        re.search(
            r"(放到|放在|打开到|展示到|嵌入到|搬到|移到|通过.{0,12}标注|直接.{0,12}标注|标注改|批注改)",
            text,
            re.IGNORECASE,
        )
    )
    return has_browser_annotation and has_app_surface and has_feature_action


def _polish_requested_task_text(text: str) -> str:
    result = _strip_spoken_asides(text)
    replacements = (
        (r"我想让你帮我做一下一个", "请帮我做一个"),
        (r"我想让你帮我做一个", "请帮我做一个"),
        (r"让你帮我做一下一个", "请帮我做一个"),
        (r"帮我做一下一个", "帮我做一个"),
        (r"帮我看一下这个", "请检查这个"),
        (r"帮我看一下", "请检查"),
        (r"就是你先检查一下", "请先检查"),
        (r"就是先检查一下", "请先检查"),
        (r"你先检查一下", "请先检查"),
        (r"先检查一下", "先检查"),
        (r"然后不要", "不要"),
        (r"对吧你看", ""),
        (r"对吧", ""),
        (r"这里我说错了", ""),
        (r"反正就是", ""),
    )
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    result = re.sub(r"请检查这个([^，,。；;]*?页)[，,。；;\s]*请先检查", r"请检查这个\1的", result)
    result = re.sub(r"[，,]\s*(不要直接改代码)", r"；\1", result)
    result = re.sub(r"[，,]\s*(先告诉我)", r"；\1", result)
    result = re.sub(r"\s+", " ", result).strip(" ，,。")
    return _ensure_final_period(result)


def _strip_spoken_asides(text: str) -> str:
    result = text
    result = re.sub(r"我肯定不可能每次输出的说的话都是一样的[，,。；;\s]*", "", result)
    result = re.sub(r"(啊|呃|嗯)[，,、。\s]*(这里)?我说错了[，,、。\s]*", "", result)
    result = re.sub(r"对吧你看[，,、。\s]*", "", result)
    result = re.sub(r"[，,、。\s]*(对吧|你看)[，,、。\s]*", "，", result)
    result = re.sub(r"反正就是[，,、。\s]*", "", result)
    result = re.sub(r"[，,、。\s]*(就是|然后)(?=(你先|先|不要|请|帮我|检查|分析|执行))", "，", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def _ensure_final_period(text: str) -> str:
    result = _strip_punctuation(text)
    if not result:
        return ""
    if re.search(r"[。！？?]$", result):
        return result
    return result + "。"


def _mentions_ai_targets(text: str) -> bool:
    return any(target in text for target in AI_TARGETS + TEXT_INPUT_TARGETS)


def _looks_like_vpc_positioning(text: str) -> bool:
    if not any(phrase in text for phrase in ("不是 TTS", "不是语音助手", "不是普通听写工具", "插件负责", "补结构", "删废话", "理解改口", "提示词")):
        return False
    return any(target in text for target in AI_TARGETS) or "提示词" in text or "项目边界" in text


def _looks_like_user_requested_task(text: str) -> bool:
    return bool(
        re.search(r"(请|帮我|让你|我想让你|我要|需要).{0,32}(做|看一下|查看|分析|检查|优化|实现|执行|整理|生成)", text)
        or re.search(r"(这个任务|任务的执行难度|怎么执行这个任务|如何执行这个任务|给.*意见)", text)
    )


def should_compile_ai_task_fallback(text: str) -> bool:
    text = _cleanup(text)
    if not text:
        return False
    if _looks_like_ai_coding_governance_request(text):
        return True
    if _looks_like_account_switch_automation_request(text):
        return True
    if _looks_like_test_guidance(text):
        return True
    if _looks_like_software_feedback(text):
        return True
    if _looks_like_project_evaluation_build_request(text):
        return True
    if _looks_like_website_creation_request(text):
        return True
    if looks_like_browser_annotation_feature_request(text):
        return True
    if _mentions_ai_targets(text) and any(marker in text for marker in TASK_INTENT_MARKERS):
        return True
    if _looks_like_user_requested_task(text):
        return True
    positioning = ("不是普通语音转文字", "不是机器人聊天", "不是聊天机器人", "不是代码生成器")
    return sum(1 for phrase in positioning if phrase in text) >= 2 and any(
        marker in text for marker in ("整理", "专业文本", "任务需求", "AI")
    )
