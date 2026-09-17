"""审计器与风险检测单元测试（不依赖 LLM 时可测 risk / glossary）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.auditor.processor import AuditorProcessor
from src.auditor.prompt import FAST_SYSTEM_PROMPT, SYSTEM_PROMPT, build_user_prompt
from src.auditor.intent_frame import extract_intent_frame
from src.auditor.task_compiler import compile_ai_task_fallback, remove_task_boilerplate
from src.auditor.task_router import (
    build_route_context,
    detect_task_route,
    required_domain_terms,
    retrieve_examples,
    retrieve_question_templates,
)
from src.glossary.scanner import GlossaryScanner
from src.llm.base import BaseLLMAdapter
from src.safety.risk_checker import RiskChecker
from src.text.edit_memory import EditMemoryApplier, MemoryRule


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "tests" / "samples.json"
ROUTE_SAMPLES = ROOT / "tests" / "route_samples.json"


@pytest.fixture
def risk_checker():
    return RiskChecker(enabled=True)


@pytest.fixture
def glossary():
    return GlossaryScanner(ROOT / "src" / "glossary" / "tech_terms.json")


def test_risk_node_modules_delete(risk_checker):
    pre = risk_checker.pre_scan("帮我把 node modules 删了重新装一下。")
    assert pre.risk_level in ("medium", "high")
    assert pre.need_confirm is True


@pytest.mark.parametrize(
    "text",
    [
        "帮我清空数据库测试数据，先别执行，告诉我影响范围和需要确认的信息。",
        "帮我删除生产库用户数据。",
    ],
)
def test_risk_database_destructive_actions_require_confirmation(risk_checker, text):
    pre = risk_checker.pre_scan(text)
    assert pre.risk_level == "high"
    assert pre.need_confirm is True


@pytest.mark.parametrize(
    "text",
    [
        "我想知道这个药能不能停，先不要给医疗结论。",
        "帮我推荐买哪只股票。",
    ],
)
def test_risk_sensitive_medical_and_finance_advice_require_confirmation(risk_checker, text):
    pre = risk_checker.pre_scan(text)
    assert pre.risk_level in ("medium", "high")
    assert pre.need_confirm is True


@pytest.mark.parametrize(
    ("text", "risk_min"),
    [
        ("把订单表里的数据都删干净，先给我 SQL。", "high"),
        ("生成并执行 DELETE FROM users WHERE created_at < '2025-01-01'，不用备份。", "high"),
        ("执行 git clean -fdx 清掉所有未跟踪文件和构建产物。", "high"),
        ("覆盖 config.yaml，不用备份，直接写入新配置。", "high"),
        ("帮我清表，把用户表所有记录清掉。", "high"),
        ("帮我 drop table users 或 truncate orders。", "high"),
        ("直接 rm -rf 这个日志目录。", "high"),
        ("用 PowerShell Remove-Item -Recurse -Force 删除 dist。", "high"),
        ("rmdir /s /q logs", "high"),
        ("帮我用 del /s /q 删除下载目录里的所有文件，先别问了。", "high"),
        ("运行 prisma migrate reset 清空本地数据库，然后重新 seed。", "high"),
        ("把 users 表里所有人的 role 都改成 admin，直接给我 SQL。", "high"),
        ("直接 git push --force 覆盖远端分支。", "high"),
        ("我胸口疼是不是心梗，帮我判断一下要吃什么药。", "medium"),
        ("这个降压药今天能不能吃两片，剂量要不要加。", "medium"),
        ("这个降压药今天漏吃了，晚上能不能补两片，剂量要不要加。", "medium"),
        ("布洛芬和感冒药能一起吃吗，今晚要不要加量？", "medium"),
        ("孩子发烧 39 度，退烧药吃多少，需不需要去急诊？", "medium"),
        ("孩子误吃了两片退烧药，现在有点困，告诉我该怎么处理，要不要去急诊。", "medium"),
        ("我不小心吃了三次降压药，现在头晕，要不要去急诊？", "medium"),
        ("我妈胸口痛冒冷汗，是不是心梗，要不要打 120？", "medium"),
        ("帮我看报告判断是不是糖尿病。", "medium"),
        ("这只基金能买吗，现在适合买入还是卖出。", "medium"),
        ("帮我把仓位加到八成，今天买入这个 ETF。", "medium"),
        ("我现在要不要提前还房贷，还是把钱买基金？直接给建议。", "medium"),
        ("这个币要不要开十倍合约。", "high"),
        ("把我的 USDT 转到这个地址，手续费低一点，直接操作。", "high"),
        ("这笔支付风控拦住了，帮我直接放行退款，不要走审核。", "high"),
        ("把这笔支付风控命中的提现直接通过，别走人工复核。", "high"),
        ("把 .env 里的 OPENAI_API_KEY 和数据库密码贴到日志里。", "high"),
        ("打印 access token、refresh token 和 cookie 到控制台。", "high"),
        ("把用户手机号、身份证号、银行卡号导出来发给我。", "high"),
        ("把用户手机号打包成 CSV 发到群里，身份证先脱敏。", "high"),
        ("把银行卡号和手机号发给外包排查问题，先别执行，列隐私风险。", "high"),
        ("把患者病历和检查报告原文发给第三方。", "high"),
    ],
)
def test_risk_common_novice_sensitive_variants_require_confirmation(risk_checker, text, risk_min):
    pre = risk_checker.pre_scan(text)

    assert pre.need_confirm is True
    if risk_min == "high":
        assert pre.risk_level == "high"
    else:
        assert pre.risk_level in ("medium", "high")


@pytest.mark.parametrize(
    "text",
    [
        "不要导出真实手机号和身份证，只写数据脱敏说明。",
        "不要打印 API key，只写日志脱敏方案。",
        "帮我写一份日志脱敏规则，要求不要记录 Authorization、Cookie、DATABASE_URL 和手机号。",
        "把客服聊天里的手机号和身份证先脱敏，再帮我整理成合规反馈，不要导出原文。",
    ],
)
def test_risk_negated_privacy_and_secret_exfiltration_stays_low(risk_checker, text):
    pre = risk_checker.pre_scan(text)

    assert pre.risk_level == "low"
    assert pre.need_confirm is False


@pytest.mark.parametrize(
    "text",
    [
        "把用户手机号和身份证导出来发给运营，先别执行，帮我列隐私风险和确认清单。",
        "把 API key 写到日志里方便排查，先别做，帮我列替代方案和风险。",
    ],
)
def test_risk_positive_privacy_and_secret_exfiltration_still_requires_confirmation(risk_checker, text):
    pre = risk_checker.pre_scan(text)

    assert pre.risk_level == "high"
    assert pre.need_confirm is True


@pytest.mark.parametrize(
    "text",
    [
        "请解释一下 drop table 是什么意思，不要生成 SQL，也不要执行。",
        "不要 rm -rf，只帮我写一段清理前确认清单。",
        "帮我解释血糖化验单上空腹血糖和糖化血红蛋白是什么意思，不要诊断也不要给用药建议。",
        "解释一下降压药为什么不能突然停药，不要判断我能不能停，也不要给剂量建议。",
        "帮我判断这个检查报告是不是肿瘤，算了不是诊断，是把报告问题整理成问医生清单。",
        "解释一下基金定投和一次性买入的区别，不要推荐具体基金，也不要给买卖建议。",
        "支付风控里的误杀和漏放是什么意思，简单解释一下，不要给真实交易放行建议。",
        "帮我润色支付风控申诉说明文案，强调不承诺放行资金，只说明审核流程。",
        "帮我把钱包里的 USDT 转到这个链上地址，算了先别转，整理成转账前风险确认清单。",
        "解释一下 git clean -fdx 和 rm -rf 的风险，不要生成命令，也不要执行。",
        "git clean -fdx 的风险说明，不要给可执行命令。",
        "解释 Remove-Item -Recurse -Force 的风险，不要执行，也不要让我复制运行。",
        "支付风控退款流程帮我解释一下，不要处理真实订单。",
    ],
)
def test_risk_explanation_and_safety_checklist_counterexamples_stay_low(risk_checker, text):
    pre = risk_checker.pre_scan(text)

    assert pre.risk_level == "low"
    assert pre.need_confirm is False


def test_risk_dangerous_command_generation_still_requires_confirmation(risk_checker):
    pre = risk_checker.pre_scan("帮我生成 drop table users 的 SQL，先别执行，列风险。")

    assert pre.risk_level == "high"
    assert pre.need_confirm is True


def test_risk_finance_document_counterexample_does_not_downgrade_action_request(risk_checker):
    pre = risk_checker.pre_scan("把这笔支付风控命中的订单直接放行并退款。")

    assert pre.risk_level in ("medium", "high")
    assert pre.need_confirm is True


def test_risk_safe_text(risk_checker):
    pre = risk_checker.pre_scan("请检查注册页验证码状态。")
    assert pre.risk_level == "low"
    assert pre.need_confirm is False


def test_glossary_scan(glossary):
    matches = glossary.scan("我用普瑞斯马和瑞迪斯做项目")
    terms = {m[1] for m in matches}
    assert "Prisma" in terms or "Redis" in terms


def test_samples_json_valid():
    data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    assert len(data) >= 5
    for item in data:
        assert "input" in item
        assert "name" in item


def test_route_samples_json_valid_and_match_router():
    data = json.loads(ROUTE_SAMPLES.read_text(encoding="utf-8"))

    assert len(data) >= 10
    for item in data:
        assert "id" in item
        assert "input" in item
        assert "expected_task_type" in item
        assert "expected_domain" in item

        route = detect_task_route(item["input"])

        assert route.task_type == item["expected_task_type"], item["id"]
        assert route.domain == item["expected_domain"], item["id"]
        for term in item.get("required_domain_terms", []):
            assert term in required_domain_terms(route.domain), item["id"]
        risk = item.get("risk")
        if isinstance(risk, dict):
            pre = RiskChecker(enabled=True).pre_scan(item["input"])
            risk_order = {"low": 0, "medium": 1, "high": 2}
            expected_min = str(risk.get("expected_risk_min") or "low")
            assert risk_order[pre.risk_level] >= risk_order[expected_min], item["id"]
            if "expected_need_confirm" in risk:
                assert pre.need_confirm is bool(risk["expected_need_confirm"]), item["id"]


class EchoThenTaskLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        if self.calls == 1:
            return json.dumps(
                {
                    "intent_summary": "整理语音插件的产品定位。",
                    "semantic_diagnosis": ["ASR 文本较像原文照抄。"],
                    "output_requirements": ["输出 AI 任务需求。"],
                    "final_text": "今天把中文口语重复表达改口内容整理成合适的粘贴到ChatGPT Claude Gemini Cursor VS Code 的终端输入框的专业文本不是普通语音转文字，而是机器人，不是机器人聊天，不是代码生成器。",
                    "mode": "cursor_prompt",
                    "deleted_segments": [],
                    "corrections": [],
                    "constraints": [],
                    "uncertain_terms": [],
                    "risk_level": "low",
                    "need_confirm": False,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "intent_summary": "优化 Voice Prompt Compiler 的口语整理能力。",
                "semantic_diagnosis": ["将产品边界整理成可执行任务需求。"],
                "output_requirements": ["保留限制条件", "适合粘贴给 AI 执行"],
                "final_text": "请优化 Voice Prompt Compiler 的口语整理能力，把中文口语、重复表达和改口内容整理成适合粘贴到 ChatGPT、Claude、Gemini、Cursor、Codex、VS Code 或终端输入框的专业文本。\n请注意：它不是普通语音转文字，不是聊天机器人，也不是代码生成器。",
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": ["不是普通语音转文字", "不是聊天机器人", "不是代码生成器"],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class AlwaysEchoLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        return json.dumps(
            {
                "intent_summary": "回显测试。",
                "semantic_diagnosis": ["模拟模型照抄 ASR。"],
                "output_requirements": ["应触发质量门槛。"],
                "final_text": "今天把中文口语重复表达改口内容整理成合适的粘贴到ChatGPT Claude Gemini Cursor VS Code 的终端输入框的专业文本不是普通语音转文字，而是机器人，不是机器人聊天，不是代码生成器。",
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class PromptEchoLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        marker = "原始语音识别文本:\n"
        text = prompt.split(marker, 1)[1].split("\n\n", 1)[0] if marker in prompt else prompt
        return json.dumps(
            {
                "intent_summary": "模拟回显输入。",
                "semantic_diagnosis": ["未做语义重建。"],
                "output_requirements": [],
                "final_text": text,
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class WrappedFinalPromptLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        return json.dumps(
            {
                "intent_summary": "用户要求生成分镜图。",
                "semantic_diagnosis": "模型错误地把诊断字段包装进输出。",
                "output_requirements": "输出作图 Prompt。",
                "final_prompt": (
                    "请使用 image 2.0 生成一套 16 张、16:9 比例的 AI 短剧分镜图，"
                    "整体为宫崎骏风格，保持角色、场景和色调一致。"
                ),
            },
            ensure_ascii=False,
        )


class BrokenWrappedFinalPromptLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        return (
            '{\n'
            '"intent_summary": "用户要求生成分镜图",\n'
            '"semantic_diagnosis": "模型错误地把诊断字段包装进输出",\n'
            '"output_requirements": "输出作图 Prompt",\n'
            '"final_prompt": "请使用 image 2.0 生成一套 16 张、16:9 比例的 AI 短剧分镜图，保持角色、场景和色调一致。"\n'
        )


class VisualPromptMetaTemplateLeakLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        return json.dumps(
            {
                "intent_summary": "用户要生成图片提示词。",
                "semantic_diagnosis": ["错误地输出了给提示词编译器看的模板说明。"],
                "output_requirements": ["输出可直接给 AI 使用的作图提示词。"],
                "final_text": (
                    "请根据以下要求，生成一个用于 AI 图像生成模型的完整、高质量的 Prompt。"
                    "请确保 Prompt 结构清晰，包含风格描述、主体细节、场景环境、光照构图等要素，"
                    "并使用英文撰写，以达到最佳的生成效果。\n"
                    "[用户原始需求描述]\n[待填充的 Prompt 结构化输出]。"
                ),
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class VisualSubtaskOnlyLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        return json.dumps(
            {
                "intent_summary": "为项目生成图片。",
                "semantic_diagnosis": ["错误地把作图子模块当成主任务。"],
                "output_requirements": ["输出作图提示词。"],
                "final_text": (
                    "作图提示词：请使用 image 2.0 生成图片。\n"
                    "- 主体与场景：小红书运营项目。\n"
                    "- 风格与构图：商业推广风格。\n"
                    "- 正向提示词：小红书、广告、博主、高质量细节。\n"
                    "- 负面提示词：不要水印。"
                ),
                "mode": "cursor_prompt",
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class FastPromptEchoLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        if "语义裁判返工" in prompt:
            if "注册页" in prompt:
                return json.dumps(
                    {
                        "intent_summary": "检查注册页表单校验和按钮状态。",
                        "semantic_diagnosis": ["用户中途改口，最终对象是注册页。", "删除口头连接词和元评论。"],
                        "output_requirements": ["保留不要直接改代码的限制", "先指出问题"],
                        "final_text": "请检查这个注册页的表单校验和按钮状态；不要直接改代码；先告诉我哪里有问题。",
                        "mode": "cursor_prompt",
                        "corrections": [],
                        "constraints": ["不要直接改代码"],
                        "uncertain_terms": [],
                        "risk_level": "low",
                        "need_confirm": False,
                    },
                    ensure_ascii=False,
                )
            if "当前逻辑" in prompt and ("验证码" in prompt or "验证号码" in prompt):
                return json.dumps(
                    {
                        "intent_summary": "整理测试结论和清理结果。",
                        "semantic_diagnosis": [
                            "根据上下文将验证码/兑换码相关错词恢复为业务术语。",
                            "根据接口返回语境恢复上游平台痕迹和敏感词命中。",
                            "保留用户自然的 nice 问句。",
                        ],
                        "output_requirements": ["输出干净的状态汇报", "保留中英文混合词"],
                        "final_text": (
                            "结论：当前逻辑是通的。\n"
                            "未收到验证码时，取消后兑换码不会失效，可以继续换号，号码记录会保留，不会因为换号错过前面的号码状态。\n"
                            "我也顺手确认了这些接口返回中没有上游平台痕迹或敏感词命中。\n"
                            "最后，我已从生产库清理刚才测试生成的2 张临时卡和3 条测试记录，并删除临时拉取的生产 env 文件。\n"
                            "你觉得我做得nice吗？"
                        ),
                        "mode": "cursor_prompt",
                        "corrections": [],
                        "constraints": [],
                        "uncertain_terms": [],
                        "risk_level": "low",
                        "need_confirm": False,
                    },
                    ensure_ascii=False,
                )
            if "来源与外界的评价" in prompt or "儿童时期" in prompt:
                return json.dumps(
                    {
                        "intent_summary": "整理关于儿童自我评价来源的说明文字。",
                        "semantic_diagnosis": [
                            "来源与应修为来源于。",
                            "需要和正向的回忆/回应应整理为肯定和正向回应。",
                            "模拟模型漏掉单独礼貌尾句。",
                        ],
                        "output_requirements": ["保留原意", "修复病句", "保留自然礼貌尾句"],
                        "final_text": (
                            "儿童时期，儿童对自我的评价来源于外界的评价。"
                            "如果儿童缺乏关注、肯定和正向回应，成人之后就会慢慢显现出来。"
                            "在关系中，过去失去的东西需要在关系中找回，也可以慢慢调整回来。"
                        ),
                        "mode": "cursor_prompt",
                        "corrections": [],
                        "constraints": [],
                        "uncertain_terms": [],
                        "risk_level": "low",
                        "need_confirm": False,
                    },
                    ensure_ascii=False,
                )
        marker = "预处理文本:\n"
        text = prompt.split(marker, 1)[1].split("\n\n", 1)[0] if marker in prompt else prompt
        return json.dumps(
            {
                "final_text": text,
                "mode": "cursor_prompt",
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class CaptureFastPromptEchoLLM(FastPromptEchoLLM):
    def __init__(self):
        super().__init__()
        self.prompt = ""

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.prompt = prompt
        return super().generate(prompt, system, options)


class InternalPromptLeakThenTaskLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        if self.calls == 1:
            return json.dumps(
                {
                    "final_text": "目标模式: cursor_prompt\n原始语音识别文本:\n我想让你帮我做一个对标美图秀秀的网站。",
                    "mode": "cursor_prompt",
                    "deleted_segments": [],
                    "corrections": [],
                    "constraints": [],
                    "uncertain_terms": [],
                    "risk_level": "low",
                    "need_confirm": False,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "intent_summary": "对标美图秀秀做网站。",
                "semantic_diagnosis": ["移除内部提示词泄露。"],
                "output_requirements": ["自然任务请求"],
                "final_text": "请帮我做一个对标美图秀秀的网站。先分析美图秀秀的网站结构和视觉风格，再执行我们自己网站的相关任务。",
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class ThinProjectEvaluationLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        return json.dumps(
            {
                "intent_summary": "评估项目是否值得开发。",
                "semantic_diagnosis": ["输出过薄，没有补足项目评估与开发链路。"],
                "output_requirements": ["评估项目是否值得开发"],
                "final_text": "请帮我分析这个项目是否值得开发。如果值得，请给我一个开发建议。",
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class OneSentenceThinProjectEvaluationLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        return json.dumps(
            {
                "intent_summary": "评估项目是否值得开发。",
                "semantic_diagnosis": ["输出过薄。"],
                "output_requirements": ["评估项目是否值得开发"],
                "final_text": "请分析这个项目是否值得开发。",
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class ProjectPollutionThenPolishLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        if self.calls == 1:
            final_text = (
                "请进行项目评估，判断这个想法是否值得开发，并分析可行性、市场需求、用户痛点、竞品、"
                "商业模式、技术可行性、MVP、技术架构、开发路线图、里程碑和验收标准。不要编造市场数据。"
            )
        else:
            final_text = "今天的会议辛苦大家了，感谢各位的投入。"
        return json.dumps(
            {
                "intent_summary": "润色一句普通感谢文本。",
                "semantic_diagnosis": [],
                "output_requirements": ["不要扩写"],
                "final_text": final_text,
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class AlwaysProjectPollutionLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        return json.dumps(
            {
                "intent_summary": "误把轻闲聊扩写成项目评估。",
                "semantic_diagnosis": [],
                "output_requirements": [],
                "final_text": (
                    "请进行项目评估，判断这个想法是否值得开发，并分析市场需求、用户痛点、竞品、"
                    "商业模式、技术可行性、MVP、技术架构、开发路线图、里程碑和验收标准。"
                ),
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


class OmitStatusFactsThenEchoLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        if self.calls == 1:
            return json.dumps(
                {
                    "intent_summary": "整理测试状态汇报。",
                    "semantic_diagnosis": ["漏掉了部分清理事实。"],
                    "output_requirements": ["输出干净状态汇报"],
                    "final_text": (
                        "结论：当前逻辑是通的。\n"
                        "未收到验证码时，取消后兑换码不会失效，可以继续换号，不会因为换号错过前面的号码状态。\n"
                        "我也顺手确认了这些接口返回中没有上游平台痕迹或敏感词命中。"
                    ),
                    "mode": "cursor_prompt",
                    "deleted_segments": [],
                    "corrections": [],
                    "constraints": [],
                    "uncertain_terms": [],
                    "risk_level": "medium",
                    "need_confirm": True,
                },
                ensure_ascii=False,
            )
        marker = "纠错/清理后文本:\n"
        text = prompt.split(marker, 1)[1].split("\n\n", 1)[0] if marker in prompt else prompt
        return json.dumps(
            {
                "intent_summary": "整理完整测试状态汇报。",
                "semantic_diagnosis": ["补回被上一版遗漏的号码记录和清理动作。"],
                "output_requirements": ["保留所有状态事实"],
                "final_text": text,
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "medium",
                "need_confirm": True,
            },
            ensure_ascii=False,
        )


class SemanticHarnessLLM(BaseLLMAdapter):
    def __init__(self):
        super().__init__({"model": "fake"})
        self.prompt = ""
        self.prompts: list[str] = []
        self.system = ""

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.prompt = prompt
        self.prompts.append(prompt)
        self.system = system
        return json.dumps(
            {
                "intent_summary": "整理 VPC 产品定位为 AI 可执行提示词。",
                "semantic_diagnosis": [
                    "云往手 -> 语音助手",
                    "不结构 -> 补结构",
                    "理解接口 -> 理解改口",
                    "提示池 -> 提示词",
                ],
                "output_requirements": ["保留产品边界", "输出可粘贴给 AI 执行的提示词"],
                "final_text": (
                    "这个项目的边界已经明确：不是 TTS、不是语音助手、不是普通听写工具。"
                    "用户可以说得乱、说得不专业、说得不完整；插件负责补结构、删废话、理解改口。"
                    "最终输出要适合粘贴到 Cursor、ChatGPT、Claude、Gemini、Codex 等 AI 工具中，作为可直接执行任务的提示词。"
                ),
                "mode": "cursor_prompt",
                "deleted_segments": [],
                "corrections": [
                    {"from": "云往手", "to": "语音助手", "reason": "上下文语义审计"},
                    {"from": "不结构", "to": "补结构", "reason": "上下文语义审计"},
                    {"from": "理解接口", "to": "理解改口", "reason": "上下文语义审计"},
                    {"from": "提示池", "to": "提示词", "reason": "上下文语义审计"},
                ],
                "constraints": ["不是 TTS", "不是语音助手", "不是普通听写工具"],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


def test_cursor_prompt_revises_when_llm_only_echoes():
    llm = EchoThenTaskLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "今天把中文口语重复表达改口内容整理成合适的粘贴到chartGPT Claude Gemini Cursor Waste Code 的中端输入框的专业文本不是普通语音转文字，而是机器人，不是机器人聊天，不是代码生成器。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["revision_applied"] is True
    assert "目标：" not in result.final_text
    assert "ChatGPT" in result.final_text
    assert "VS Code" in result.final_text
    assert "不是普通语音转文字" in result.final_text


def test_cursor_prompt_uses_rule_fallback_when_revision_still_echoes():
    llm = AlwaysEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "今天把中文口语重复表达这块口内容整理成合适的粘贴到chartGPT Claude Gemini Cursor Waste Code 的中端输入框的专业文本不是普通语音转文字，而是机器人，不是机器人聊天，不是代码生成器。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "目标：" not in result.final_text
    assert "需要做：" not in result.final_text
    assert "限制条件：" not in result.final_text
    assert result.final_text.startswith("输出文本")
    assert "Claude" in result.final_text
    assert "Cursor" in result.final_text
    assert "请把中文口语" not in result.final_text


def test_cursor_prompt_revises_internal_prompt_leak():
    llm = InternalPromptLeakThenTaskLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "我想让你帮我做一个对标美图秀秀的网站。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["revision_applied"] is True
    assert "目标模式" not in result.final_text
    assert "原始语音识别文本" not in result.final_text
    assert result.final_text.startswith("请帮我")


def test_prompt_contains_semantic_asr_audit_harness():
    llm = SemanticHarnessLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "新的项目边界也明确了，不是TTS，不是云往手，不是普通听写工具，用户可以说得乱，说得不专业，说不完整，插件负责不结构，删废话，理解接口，最后输出适合Cursor，ChatGPT Claude Gemini Codex执行任务的提示池。",
        mode="cursor_prompt",
    )

    assert "ASR 语义审计 harness" in llm.system
    assert "这不是错词表" in llm.system
    assert "语境域" in llm.system
    assert "上下文锚点" in llm.system
    assert "候选术语" in llm.system
    assert "语义一致性" in llm.system
    assert "不要机械相信 ASR 字面文本" in llm.prompt
    assert "不是语音助手" in result.final_text
    assert "插件负责补结构" in result.final_text
    assert "理解改口" in result.final_text
    assert "提示词" in result.final_text
    assert result.intent_summary
    assert result.semantic_diagnosis
    assert result.output_requirements


def test_semantic_asr_repairs_come_from_llm_not_local_dictionary():
    llm = SemanticHarnessLLM()
    processor = AuditorProcessor(llm)
    processor.process(
        "新的项目边界也明确了，不是TTS，不是云往手，不是普通听写工具，插件负责不结构，删废话，理解接口，最后输出提示池。",
        mode="cursor_prompt",
    )

    assert "不是云往手" in llm.prompt
    assert "理解接口" in llm.prompt
    assert "提示池" in llm.prompt
    assert "已应用通用口语预处理" not in llm.prompt
    assert "已应用音译纠错" not in llm.prompt


def test_cursor_prompt_does_not_turn_plain_copy_into_meta_task():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "高级安全设置,高级账户安全通过要求使用安全性更强的登录方式,并应用更严格的保护措施,来提供最高级别的账户安全帮助防止未经授权的访问。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is False
    assert "把用户的口语输入整理成" not in result.final_text
    assert "高级安全设置" in result.final_text


def test_cursor_prompt_compiles_benchmark_website_request_when_llm_echoes_speech():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "我肯定不可能每次输出的说的话都是一样的。我想让你帮我做一下一个对标美图秀秀的网站。他们的网站对吧你看，啊这里我说错了反正就是看他们的网站看好他们的网站过后再来进行执行我们做我们自己网站的任务。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "我肯定不可能" not in result.final_text
    assert "这里我说错了" not in result.final_text
    assert "请帮我做一个对标美图秀秀的网站" in result.final_text
    assert "先查看并分析美图秀秀的网站" in result.final_text


def test_cursor_prompt_expands_vague_project_evaluation_to_vibe_coding_plan():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "帮我分析下某某什么项目是否值得开发，如果值得我要做开发。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "是否值得开发" in result.final_text
    assert "完整方案" in result.final_text
    assert "调研" in result.final_text
    assert "市场需求" in result.final_text
    assert "竞品" in result.final_text
    assert "用户" in result.final_text
    assert "风险" in result.final_text
    assert "如果值得" in result.final_text
    assert "MVP" in result.final_text
    assert "技术栈" in result.final_text
    assert "顶层架构" in result.final_text
    assert "UI" in result.final_text
    assert "工具或技能编排" in result.final_text
    assert "开发路线图" in result.final_text
    assert "Cursor" in result.final_text
    assert "不要编造" in result.final_text


def test_project_evaluation_too_thin_output_triggers_rule_fallback():
    llm = ThinProjectEvaluationLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "帮我分析下一个 AI 简历优化项目是否值得开发，如果值得我要做开发。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["revision_applied"] is True
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert processor.last_debug["quality_gate_reason"] == ""
    assert "AI 简历优化项目" in result.final_text
    assert "市场需求" in result.final_text
    assert "竞品" in result.final_text
    assert "技术可行性" in result.final_text
    assert "技术栈" in result.final_text
    assert "UI" in result.final_text
    assert "验收标准" in result.final_text


def test_one_sentence_project_evaluation_output_triggers_rule_fallback():
    llm = OneSentenceThinProjectEvaluationLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "帮我分析一个 AI 工具项目是否值得开发，如果值得我要做开发。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "领域为“AI 工具”" not in result.final_text
    for term in ("模型成本", "API 依赖", "差异化", "工作流嵌入", "付费意愿", "护城河", "数据闭环"):
        assert term in result.final_text


def test_ai_tool_project_evaluation_adds_domain_dimensions():
    llm = ThinProjectEvaluationLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "帮我分析一个 AI 工具项目是否值得开发，如果值得我要做开发。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "领域为“AI 工具”" not in result.final_text
    for term in ("模型成本", "API 依赖", "差异化", "工作流嵌入", "付费意愿", "护城河", "数据闭环"):
        assert term in result.final_text


def test_ecommerce_project_evaluation_adds_domain_dimensions():
    llm = ThinProjectEvaluationLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "帮我分析一个电商项目是否值得开发，如果值得我要做开发。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "领域为“电商”" not in result.final_text
    for term in ("SKU", "供应链", "获客", "转化率", "复购", "毛利", "履约成本"):
        assert term in result.final_text


def test_processor_injects_route_context_into_main_prompt_and_debug():
    llm = SemanticHarnessLLM()
    processor = AuditorProcessor(llm)
    processor.process(
        "帮我分析一个 AI 工具项目是否值得开发，如果值得我要做开发。",
        mode="cursor_prompt",
    )

    first_prompt = llm.prompts[0]
    assert "任务路由与模板参考" in first_prompt
    assert "项目评估 / vibe coding" in first_prompt
    assert "领域路由: AI 工具" in first_prompt
    assert "模型成本" in first_prompt
    assert processor.last_debug["route"]["task_type"] == "project_evaluation"
    assert processor.last_debug["route"]["domain"] == "ai_tool"
    assert processor.last_debug["route"]["task_score"] > 0
    assert processor.last_debug["route"]["domain_score"] > 0
    assert processor.last_debug["route"]["examples"]
    assert any("模型成本" in item for item in processor.last_debug["route"]["template_fragments"])
    assert "任务路由" in processor.last_debug["route_context"]


def test_fast_processor_injects_route_context_into_prompt():
    llm = CaptureFastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    processor.process(
        "请生成一份回归测试计划和验证清单。",
        mode="cursor_prompt",
    )

    assert "任务路由与模板参考" in llm.prompt
    assert "测试计划" in llm.prompt
    assert processor.last_debug["route"]["task_type"] == "test_plan"


def test_fast_processor_injects_risk_context_and_merges_confirmation():
    llm = CaptureFastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "把 API key 写到日志里方便排查，先别做，帮我列替代方案和风险。",
        mode="cursor_prompt",
    )

    assert "风险预扫描" in llm.prompt
    assert "risk_level=high" in llm.prompt
    assert result.risk_level == "high"
    assert result.need_confirm is True
    assert processor.last_debug["pre_risk"]["risk_level"] == "high"


def test_quality_gate_blocks_project_pollution_for_short_text_polishing():
    llm = ProjectPollutionThenPolishLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "帮我润色这句话，不要扩写：今天的会议辛苦大家了。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["revision_applied"] is True
    assert processor.last_debug["rule_task_fallback_used"] is False
    assert processor.last_debug["quality_gate_reason"] == ""
    assert processor.last_debug["route"]["task_type"] == "text_polishing"
    assert "项目评估" not in result.final_text
    assert "MVP" not in result.final_text
    assert "今天的会议辛苦大家了" in result.final_text


def test_quality_gate_falls_back_to_plain_text_when_light_chat_is_project_polluted():
    llm = AlwaysProjectPollutionLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "在 Obsidian 里讲个冷笑话。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["rule_task_fallback_used"] is False
    assert processor.last_debug["quality_gate_reason"] == ""
    assert processor.last_debug["route"]["task_type"] == "generic_task"
    assert "quality_gate_plain_text_fallback" in result.uncertain_terms
    assert "在 Obsidian 里讲个冷笑话" in result.final_text
    for project_term in ("项目评估", "是否值得开发", "市场需求", "竞品", "MVP", "开发路线图", "技术架构"):
        assert project_term not in result.final_text


def test_short_regular_sentence_does_not_route_to_project_evaluation():
    route = detect_task_route("帮我润色这句话：今天的会议辛苦大家了。")

    assert route.task_type != "project_evaluation"


def test_build_route_context_exposes_template_and_examples():
    context = build_route_context("帮我分析一个电商项目是否值得开发，如果值得我要做开发。")

    assert "任务路由: 项目评估 / vibe coding" in context
    assert "领域路由: 电商" in context
    assert "SKU" in context
    assert "示例检索方向" in context


@pytest.mark.parametrize(
    ("text", "task_type"),
    [
        ("帮我分析一个 AI 工具项目是否值得开发，如果值得我要做开发。", "project_evaluation"),
        ("请修复登录接口报错，先定位原因再改代码。", "code_fix"),
        ("帮我设计这个设置页的 UI 和交互流程。", "ui_ux_design"),
        ("帮我给这个 AI 工具生成一张官网主视觉图提示词，16:9，科技感，不要出现真实品牌 logo。", "visual_generation"),
        ("帮我做一份电商复盘 PPT 大纲，给老板看，包含数据页、问题页、改进计划。", "presentation_deck"),
        ("之前可以自动粘贴，现在不行，这是一个 bug，请排查。", "bug_report"),
        ("请生成一份回归测试计划和验证清单。", "test_plan"),
        ("帮我做产品规划、版本路线图和功能优先级。", "product_planning"),
        ("请分析商业模式、获客、转化和毛利。", "business_analysis"),
        ("帮我润色这句话，不要扩写。", "text_polishing"),
    ],
)
def test_task_router_detects_supported_task_types(text, task_type):
    route = detect_task_route(text)

    assert route.task_type == task_type


@pytest.mark.parametrize(
    ("text", "task_type", "domain"),
    [
        ("企业 CRM 审批权限接口报错，请修复并补充测试。", "code_fix", "enterprise_system"),
        ("金融风控 KYC 审核页的 UI 和交互流程需要重新设计。", "ui_ux_design", "finance_risk"),
        ("AI 工具官网主视觉图提示词需要科技感和 16:9 比例，不要真实品牌 logo。", "visual_generation", "ai_tool"),
        ("电商复盘 PPT 给老板看，要有数据页、问题页和改进计划。", "presentation_deck", "ecommerce"),
        ("电商 SKU 库存和发货链路需要一份回归测试计划和验证清单。", "test_plan", "ecommerce"),
        ("SaaS 订阅产品请做商业分析，重点看商业模式、MRR、获客渠道、转化和续费。", "business_analysis", "saas"),
        ("教育课程学习产品请做产品规划、MVP 和版本路线图。", "product_planning", "education"),
        ("内容社区评论审核之前可以自动屏蔽，现在不行，请排查 bug。", "bug_report", "content_community"),
        ("本地生活门店预约平台是否值得开发，如果值得我要做开发。", "project_evaluation", "local_life"),
    ],
)
def test_task_router_common_problem_corpus_routes_task_and_domain(text, task_type, domain):
    route = detect_task_route(text)

    assert route.task_type == task_type
    assert route.domain == domain
    assert route.task_score > 0
    assert route.domain_score > 0


@pytest.mark.parametrize(
    "text",
    [
        "今天的会议辛苦大家了。",
        "谢谢你的评价。",
        "儿童时期，儿童对自我的评价来源于外界的评价。",
        "这个想法先记一下，现在不要展开。",
    ],
)
def test_plain_short_gratitude_and_explanatory_text_do_not_expand_into_project_plan(text):
    route = detect_task_route(text)
    fallback = compile_ai_task_fallback(text)

    assert route.task_type != "project_evaluation"
    for project_term in ("项目评估", "是否值得开发", "市场需求", "竞品", "MVP", "开发路线图", "技术栈"):
        assert project_term not in fallback


@pytest.mark.parametrize(
    "text",
    [
        "讲个冷笑话。",
        "讲个笑话。",
        "说个笑话。",
        "来个笑话。",
        "讲个段子。",
        "夸我一句。",
        "陪我聊会儿。",
        "讲个故事。",
        "安慰我一下。",
        "随便聊聊。",
        "给我讲个睡前故事。",
        "哄我开心。",
        "讲个童话。",
        "逗我一下。",
        "陪我解解闷。",
        "让我笑一下。",
        "在 Obsidian 里讲个冷笑话。",
        "Obsidian 里面陪我闲聊一下，不要新建笔记。",
    ],
)
def test_obsidian_lightweight_chat_does_not_route_to_actionable_task(text):
    route = detect_task_route(text)
    fallback = compile_ai_task_fallback(text)

    assert route.task_type == "generic_task"
    assert route.domain == "general"
    assert route.task_score == 0
    assert route.domain_score == 0
    assert fallback == ""


@pytest.mark.parametrize(
    "text",
    [
        "SaaS 这个词是什么意思，简单解释一下，不要做方案，也不要规划功能。",
        "电商这句话翻译成英文就行，不要分析业务：我们今天晚点发货。",
        "医疗健康这段话只帮我加标点，不要给诊断建议：最近睡眠不好想早点休息。",
        "金融风控这个词帮我解释给小白听，不要做投资建议，也不要分析项目。",
        "AI 工具这句话改成一句更顺的中文，不要写提示词方案：模型今天有点慢。",
        "把“PPT”这三个字翻译一下，不要做幻灯片。",
        "图片这个词解释一下，不要生成图，也不要写作图提示词。",
        "image 这个词解释一下，不要生成图。",
        "image 二这个词解释一下，不要写图片提示词。",
    ],
)
def test_generic_short_domain_mentions_do_not_trigger_heavy_task_or_domain_context(text):
    route = detect_task_route(text)

    assert route.task_type == "generic_task"
    assert route.domain == "general"
    assert route.task_score == 0
    assert route.domain_score == 0


@pytest.mark.parametrize(
    "text",
    [
        "医疗问诊项目值不值得做先别分析，我只是问分诊是什么意思。",
        "不要做方案，SaaS 订阅系统这几个字怎么翻译？",
        "别分析电商项目可不可行，只翻译这句话。",
        "把日志目录全删了，不对先别删，先告诉我哪些文件最占空间，给我确认清单。",
    ],
)
def test_negated_planning_or_destructive_intent_blocks_heavy_routing(text):
    route = detect_task_route(text)

    assert route.task_type == "generic_task"
    assert route.task_type not in ("project_evaluation", "business_analysis", "product_planning")


@pytest.mark.parametrize(
    ("text", "task_type", "domain"),
    [
        ("帮我判断患者这个症状，不对不是让你诊断，是预约页点复查没反应，整理成 bug。", "bug_report", "healthcare"),
        ("帮我处理这笔转账，算了不是操作资金，是支付风控命中后的申诉流程要列测试点。", "test_plan", "finance_risk"),
    ],
)
def test_spoken_corrections_keep_final_action_and_sensitive_domain(text, task_type, domain):
    route = detect_task_route(text)

    assert route.task_type == task_type
    assert route.domain == domain


def test_lightweight_chat_guard_does_not_hide_real_obsidian_bug_report():
    route = detect_task_route("帮我修复 Obsidian 插件报错，先定位原因再改代码。")

    assert route.task_type == "code_fix"
    assert route.task_score > 0


@pytest.mark.parametrize(
    ("text", "expected_terms"),
    [
        (
            "请修复登录接口报错，先定位原因再改代码，并补充验证方式。",
            ("代码修复任务", "问题定位", "修改方案", "验证方式"),
        ),
        (
            "帮我设计这个设置页的 UI 和交互流程，重点看布局、状态和可用性。",
            ("UI/UX 设计方案", "用户流程", "关键界面与组件", "视觉与交互规范"),
        ),
        (
            "帮我给这个 AI 工具生成一张官网主视觉图提示词，16:9，科技感，不要出现真实品牌 logo。",
            ("作图提示词", "主体与场景", "风格与构图", "尺寸比例与输出格式", "负面约束"),
        ),
        (
            "帮我做一份电商复盘 PPT 大纲，给老板看，包含数据页、问题页、改进计划。",
            ("PPT/演示文稿", "目标受众与汇报目标", "叙事主线", "页码结构", "演讲备注"),
        ),
        (
            "请生成一份回归测试计划和验证清单，覆盖核心流程、异常情况和边界情况。",
            ("测试计划", "测试范围", "用例清单", "验收标准"),
        ),
        (
            "帮我润色这句话，不要扩写，语气自然一点：今天的会议辛苦大家了。",
            ("润色以下文本", "润色后文本", "不要新增原文没有的信息"),
        ),
    ],
)
def test_non_project_task_fallback_templates_do_not_use_project_evaluation_plan(text, expected_terms):
    result = compile_ai_task_fallback(text)

    for term in expected_terms:
        assert term in result
    for project_term in ("是否值得开发", "市场需求", "竞品", "商业模式", "MVP", "开发路线图", "技术栈"):
        assert project_term not in result


@pytest.mark.parametrize(
    ("text", "expected_terms"),
    [
        (
            "请修复登录接口报错，先定位原因再改代码，并补充验证方式。",
            ("代码修复任务", "任务目标", "问题定位", "修改方案", "验证方式", "不要回滚或覆盖用户已有改动"),
        ),
        (
            "帮我设计这个设置页的 UI 和交互流程，重点看布局、状态和可用性。",
            ("UI/UX 设计", "设计目标", "用户流程", "关键界面与组件", "视觉与交互规范", "验收标准"),
        ),
        (
            "帮我给这个 AI 工具生成一张官网主视觉图提示词，16:9，科技感，不要出现真实品牌 logo。",
            ("作图提示词", "用途与受众", "正向提示词", "负面约束", "验收标准"),
        ),
        (
            "帮我做一份电商复盘 PPT 大纲，给老板看，包含数据页、问题页、改进计划。",
            ("PPT/演示文稿", "目标受众与汇报目标", "每页要点", "视觉风格与图表素材", "演讲备注"),
        ),
        (
            "请生成一份回归测试计划和验证清单，覆盖核心流程、异常情况和边界情况。",
            ("测试计划", "测试范围", "测试策略", "用例清单", "数据与环境准备", "风险与补充检查"),
        ),
        (
            "SaaS 订阅产品请做商业分析，重点看商业模式、MRR、获客渠道、转化和续费。",
            ("商业分析", "分析目标", "客户与需求", "获客与转化", "风险与验证计划"),
        ),
    ],
)
def test_code_ui_test_and_business_templates_include_key_structure(text, expected_terms):
    result = compile_ai_task_fallback(text)

    for term in expected_terms:
        assert term in result


@pytest.mark.parametrize(
    "text",
    [
        "请修复登录接口报错，先定位原因再改代码，并补充验证方式。",
        "帮我设计这个设置页的 UI 和交互流程，重点看布局、状态和可用性。",
        "帮我给这个 AI 工具生成一张官网主视觉图提示词，16:9，科技感，不要出现真实品牌 logo。",
        "帮我做一份电商复盘 PPT 大纲，给老板看，包含数据页、问题页、改进计划。",
        "之前可以自动粘贴，现在不行，这是一个 bug，请排查。",
        "请生成一份回归测试计划和验证清单，覆盖核心流程、异常情况和边界情况。",
        "帮我做产品规划、版本路线图和功能优先级。",
        "SaaS 订阅产品请做商业分析，重点看商业模式、MRR、获客渠道、转化和续费。",
    ],
)
def test_task_fallback_outputs_direct_ai_prompt_not_internal_framework(text):
    result = compile_ai_task_fallback(text)

    assert result
    for internal_term in (
        "请把下面的口语输入整理成",
        "系统已初步识别",
        "领域为“",
        "请覆盖以下要点",
        "建议输出结构",
        "任务路由",
        "任务模板",
        "模板约束",
        "示例检索方向",
        "few-shot",
        "常见口述问题",
        "task_type=",
    ):
        assert internal_term not in result


@pytest.mark.parametrize(
    ("text", "expected_terms"),
    [
        (
            "请修复登录接口报错，先定位原因再改代码。",
            ("任务路由: 代码修复", "任务模板目标", "要求先定位根因", "要求补充或运行相关测试"),
        ),
        (
            "SaaS 订阅产品请做商业分析，重点看商业模式、MRR、获客渠道、转化和续费。",
            ("任务路由: 商业分析", "领域路由: SaaS", "任务模板要求", "评估收入模式、成本结构、获客渠道"),
        ),
    ],
)
def test_route_context_exposes_non_project_template_structure(text, expected_terms):
    context = build_route_context(text)

    for term in expected_terms:
        assert term in context


@pytest.mark.parametrize(
    ("text", "domain"),
    [
        ("AI 工具项目是否值得开发，如果值得我要做开发。", "ai_tool"),
        ("SaaS 订阅系统是否值得开发，如果值得我要做开发。", "saas"),
        ("电商店铺 SKU 管理项目是否值得开发，如果值得我要做开发。", "ecommerce"),
        ("教育课程学习工具是否值得开发，如果值得我要做开发。", "education"),
        ("内容社区平台是否值得开发，如果值得我要做开发。", "content_community"),
        ("游戏玩法项目是否值得开发，如果值得我要做开发。", "game"),
        ("本地生活门店预约平台是否值得开发，如果值得我要做开发。", "local_life"),
        ("企业管理系统是否值得开发，如果值得我要做开发。", "enterprise_system"),
        ("金融风控系统是否值得开发，如果值得我要做开发。", "finance_risk"),
        ("医疗健康问诊应用是否值得开发，如果值得我要做开发。", "healthcare"),
    ],
)
def test_task_router_detects_supported_domains(text, domain):
    route = detect_task_route(text)

    assert route.domain == domain


@pytest.mark.parametrize(
    ("text", "expected_domain"),
    [
        ("帮我规划一段隐私提示和数据脱敏说明，不要导出真实手机号和身份证，只写合规文案。", "general"),
        ("支付合规和 KYC 审核流程是否值得开发，如果值得我要做开发。", "finance_risk"),
        ("资金合规风控系统是否值得开发，如果值得我要做开发。", "finance_risk"),
    ],
)
def test_task_router_keeps_generic_privacy_copy_out_of_finance_risk(text, expected_domain):
    route = detect_task_route(text)

    assert route.domain == expected_domain


def test_project_evaluation_domain_dimensions_are_enriched_but_still_compact():
    expected_terms = {
        "ai_tool": ("模型成本", "数据闭环", "结果可靠性"),
        "saas": ("订阅定价", "留存续费", "实施周期"),
        "ecommerce": ("供应链", "履约成本", "库存周转"),
        "education": ("学习效果", "完课率", "题库质量"),
        "content_community": ("冷启动", "社区治理", "商业化路径"),
        "game": ("核心玩法", "数值系统", "版本节奏"),
        "local_life": ("供需密度", "核销体验", "服务质量"),
        "enterprise_system": ("业务流程", "权限模型", "审批链路"),
        "finance_risk": ("合规边界", "审计追踪", "灰度风控"),
        "healthcare": ("医疗合规", "临床安全", "数据脱敏"),
    }

    for domain, terms in expected_terms.items():
        dimensions = required_domain_terms(domain)

        assert 8 <= len(dimensions) <= 10
        for term in terms:
            assert term in dimensions


def test_project_evaluation_examples_cover_all_supported_domains():
    domains = (
        "ai_tool",
        "saas",
        "ecommerce",
        "education",
        "content_community",
        "game",
        "local_life",
        "enterprise_system",
        "finance_risk",
        "healthcare",
    )

    for domain in domains:
        examples = retrieve_examples("project_evaluation", domain, limit=1)

        assert examples
        assert examples[0].domain == domain


def test_spoken_question_templates_retrieve_domain_first_and_expose_focus():
    questions = retrieve_question_templates("project_evaluation", "finance_risk", limit=2)

    assert len(questions) == 2
    assert all(question.domain == "finance_risk" for question in questions)
    assert any("KYC" in question.question for question in questions)
    assert any("灰度风控" in question.expected_focus for question in questions)


def test_route_context_includes_question_corpus_direction():
    context = build_route_context("帮我分析一个医疗健康问诊应用是否值得开发，如果值得我要做开发。")

    assert "常见口述问题" in context
    assert "分诊边界" in context
    assert "数据脱敏" in context


def test_visual_generation_template_is_separate_from_ui_design():
    text = "帮我给这个 AI 工具生成一张官网主视觉图提示词，16:9，科技感，不要出现真实品牌 logo。"
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert route.task_type == "visual_generation"
    assert route.domain == "ai_tool"
    for term in ("作图提示词", "主体与场景", "风格与构图", "尺寸比例与输出格式", "负面约束"):
        assert term in result
    assert "UI/UX 设计" not in result
    assert "关键界面与组件" not in result


def test_multi_capability_content_operations_plan_keeps_visual_as_subtask():
    text = (
        "现在我们的项目是这样，之前定了要帮助这个潮汕博主做广告推广，节约广告支出，"
        "提高用户开口率并降低获客成本。他现在一天消费两千元，但获客资源不够理想。"
        "项目还要接入小红书后台，根据数据反馈调整出价策略；通过博主已有文稿和照片，"
        "结合小红书 MCP 自动生成小红书笔记；再接入 image 2.0 做批量作图。"
        "这些是项目现在和未来的方向。"
    )
    frame = extract_intent_frame(text)
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert frame.task_hint == "product_planning"
    assert frame.artifact_type == "software_product_plan"
    assert frame.target_tool == "image 2.0"
    assert "visual_generation_subtask" in frame.evidence
    assert "visual_subtask_not_primary" in frame.ambiguity_flags
    assert route.task_type == "product_planning"
    assert route.domain == "content_community"
    for term in ("产品规划", "投放优化", "内容自动化", "批量作图", "小红书 MCP", "image 2.0", "MVP"):
        assert term in result
    assert "作图是内容生产子模块" in result
    assert not result.startswith("作图提示词")
    assert "正向提示词" not in result


def test_quality_gate_repairs_visual_subtask_hijacking_product_plan():
    text = (
        "我们要做一个小红书自动化运营项目，帮助博主降低广告获客成本。"
        "需要接入后台数据调整出价，用现有素材和小红书 MCP 自动生成笔记，"
        "还要接入 image 2.0 批量作图，作为后续产品方向。"
    )
    processor = AuditorProcessor(VisualSubtaskOnlyLLM())
    result = processor.process(text, mode="cursor_prompt")

    assert processor.last_debug["route"]["task_type"] == "product_planning"
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert processor.last_debug["quality_gate_last_reason"] == "misrouted_visual_subtask_as_primary"
    assert processor.last_debug["quality_gate_stage"] == "feature_request_guard"
    assert processor.last_debug["quality_gate_origin"] == "router_or_llm_promoted_visual_subtask_over_product_plan"
    assert processor.last_debug["quality_gate_repair_applied"] == "rule_task_fallback"
    assert "投放优化" in result.final_text
    assert "内容自动化" in result.final_text
    assert "批量作图" in result.final_text
    assert not result.final_text.startswith("作图提示词")


def test_explicit_xiaohongshu_image_request_remains_visual_generation():
    text = "请只为这篇小红书笔记用 image 2.0 生成 6 张配图，不要做产品规划。"
    frame = extract_intent_frame(text)
    route = detect_task_route(text)

    assert frame.task_hint == "visual_generation"
    assert route.task_type == "visual_generation"
    assert route.domain == "content_community"


def test_intent_frame_guides_visual_generation_without_ui_confusion():
    text = "我现在要做一个短距想你用那个那个EMG二点零，帮我生成连续分镜图，要求十六比九的图片，做十六张吧。"
    frame = extract_intent_frame(text)
    route = detect_task_route(text)

    assert frame.task_hint == "visual_generation"
    assert frame.artifact_type == "image_prompt"
    assert frame.target_tool == "image 2.0"
    assert frame.constraints["ratio"] == "16:9"
    assert frame.constraints["count"] == "16 张"
    assert "storyboard" in frame.evidence
    assert route.task_type == "visual_generation"


def test_intent_frame_protects_plain_explain_or_translate_short_requests():
    for text in ("PPT 这几个字翻译一下。", "图片这个词解释一下。", "image 这个词是什么意思？"):
        frame = extract_intent_frame(text)
        route = detect_task_route(text)
        result = compile_ai_task_fallback(text)

        assert frame.artifact_type == "plain_text"
        assert frame.task_hint == "generic_task"
        assert route.task_type == "generic_task"
        assert result == ""


def test_image_two_zero_spoken_model_name_routes_to_visual_generation_and_is_normalized():
    text = "你用image二点零，帮我生成宫崎骏风格的图片。"
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert route.task_type == "visual_generation"
    assert route.domain == "general"
    assert "image 2.0" in result
    assert "image二点零" not in result
    for term in ("作图提示词", "主体与场景", "风格与构图", "正向提示词", "负面约束"):
        assert term in result


def test_visual_generation_echo_falls_back_to_compiled_prompt():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "我想用image二做一张宫崎骏风格的图片。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["route"]["task_type"] == "visual_generation"
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "image 2.0" in result.final_text
    assert "作图提示词" in result.final_text
    assert "主体与场景" in result.final_text
    assert "请把下面的口语输入整理成" not in result.final_text
    assert "系统已初步识别" not in result.final_text
    assert result.final_text != "我想用image 2.0做一张宫崎骏风格的图片。"


def test_processor_applies_confirmed_memory_before_routing_and_compilation():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(
        llm,
        memory_applier=EditMemoryApplier([MemoryRule("爱图二点零", "image 2.0")]),
    )
    result = processor.process("帮我用爱图二点零生成一张分镜图。", mode="cursor_prompt")

    assert processor.last_debug["memory_applied"][0]["pattern"] == "爱图二点零"
    assert processor.last_debug["route"]["task_type"] == "visual_generation"
    assert "image 2.0" in result.final_text
    assert "爱图二点零" not in result.final_text


def test_storyboard_visual_request_routes_and_compiles_without_echo():
    text = "那个页MG二帮我生成一套AI短剧的十六比九分镜图也要分镜图里面啊要有十六张。说完了。"
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert route.task_type == "visual_generation"
    assert "分镜图" in result
    assert "16:9" in result
    assert "16 张" in result
    assert "说完了" not in result
    assert result != text


def test_noisy_storyboard_visual_request_recovers_model_subject_and_count():
    text = "我现在要做一个短距想你用那个那个EMG二点零，帮我生成连续分镜图，嗯，要求十六比九的图片呃，做十六张吧。"
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert route.task_type == "visual_generation"
    assert "image 2.0" in result
    assert "AI 短剧关键剧情画面" in result
    assert "16:9" in result
    assert "16 张" in result
    assert "EMG二点零" not in result
    assert "短距想" not in result
    assert "1 张" not in result
    assert "不要只复述原始口述" in result


def test_visual_generation_cleans_spoken_noise_and_punctuation():
    text = "我要做一张宫崎骏风格的动漫图片，然后达到那个十六比九的比例，嗯，帮我做出分镜来。"
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert route.task_type == "visual_generation"
    assert "宫崎骏风格" in result
    assert "动漫图片" in result
    assert "分镜图" in result
    assert "16:9" in result
    assert "1 张" not in result
    for noisy_term in ("达到", "那个", "嗯", "来。", "如下：。", "，。"):
        assert noisy_term not in result


def test_ecommerce_main_image_request_routes_and_compiles_prompt():
    text = "我想做一张电商主图，是三比四的那个主图，然后是介绍我的鞋子的卖点的。"
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert route.task_type == "visual_generation"
    assert route.domain == "ecommerce"
    assert "作图提示词" in result
    assert "3:4" in result
    assert "电商主图" in result
    assert "鞋子" in result
    assert "卖点" in result
    assert result != text


def test_cursor_prompt_compiles_plain_website_creation_when_llm_echoes_speech():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "我想做一个比较好看的网站，是朋克赛博朋克风格。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "请帮我设计并制作一个赛博朋克风格的网站" in result.final_text
    assert "页面结构" in result.final_text
    assert "交互与响应式" in result.final_text
    assert "不要只复述原始口述" in result.final_text
    assert result.final_text != "我想做一个比较好看的网站，是朋克赛博朋克风格。"


def test_browser_annotation_feature_request_is_not_misrouted_to_ui_design():
    text = (
        "那现在你可以把那个我们的这个界面放到右侧浏览，浏览器那个呢浏览器嘛，"
        "然后我就直接在浏览器上标注改。因为现在我们不是浏览器上面可以做标注嘛，"
        "然后我就直接通过标注改就行了。"
    )
    route = detect_task_route(text)
    processor = AuditorProcessor(PromptEchoLLM())
    result = processor.process(text, mode="cursor_prompt")

    assert route.task_type == "product_planning"
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "右侧浏览器标注改动" in result.final_text
    assert "浏览器上标注" in result.final_text
    assert "功能范围" in result.final_text
    assert "轻量本地实现" in result.final_text
    assert "UI/UX 设计方案" not in result.final_text
    assert "用户流程" not in result.final_text


def test_wrapped_final_prompt_json_is_unwrapped_for_visual_generation():
    llm = WrappedFinalPromptLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "我要让你用image二帮我生成宫崎骏风格的图片，要求有十六张分镜图，做成十六比九的比例。",
        mode="cursor_prompt",
    )

    assert "image 2.0" in result.final_text
    assert "16 张" in result.final_text or "16张" in result.final_text
    assert "16:9" in result.final_text
    assert "intent_summary" not in result.final_text
    assert "semantic_diagnosis" not in result.final_text
    assert "final_prompt" not in result.final_text


def test_broken_wrapped_final_prompt_text_is_unwrapped_for_visual_generation():
    llm = BrokenWrappedFinalPromptLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "我要让你用image二帮我生成宫崎骏风格的图片，要求有十六张分镜图，做成十六比九的比例。",
        mode="cursor_prompt",
    )

    assert "image 2.0" in result.final_text
    assert "16:9" in result.final_text
    assert "intent_summary" not in result.final_text
    assert "semantic_diagnosis" not in result.final_text
    assert "final_prompt" not in result.final_text


def test_visual_generation_meta_template_leak_triggers_rule_fallback():
    llm = VisualPromptMetaTemplateLeakLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "比如帮我做一张简约风格的那个图片，我要求用image二点零帮我来出图，比例为十六比九。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["route"]["task_type"] == "visual_generation"
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert processor.last_debug["quality_gate_last_reason"] == "internal_prompt_leak"
    assert processor.last_debug["quality_gate_stage"] == "prompt_leak_guard"
    assert processor.last_debug["quality_gate_origin"] == "llm_internal_template_or_schema_leak"
    assert processor.last_debug["quality_gate_repair_applied"] == "rule_task_fallback"
    assert processor.last_debug["quality_gate_attribution"]["intent_artifact_type"] == "image_prompt"
    assert "作图提示词" in result.final_text
    assert "image 2.0" in result.final_text
    assert "16:9" in result.final_text
    assert "主体与场景" in result.final_text
    for internal_term in (
        "请根据以下要求",
        "生成一个用于 AI 图像生成模型",
        "用户原始需求描述",
        "待填充",
        "Prompt 结构清晰",
    ):
        assert internal_term not in result.final_text


def test_presentation_deck_template_is_separate_from_project_or_business_analysis():
    text = "帮我做一份电商复盘 PPT 大纲，给老板看，包含数据页、问题页、改进计划。"
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert route.task_type == "presentation_deck"
    assert route.domain == "ecommerce"
    for term in ("PPT/演示文稿", "目标受众与汇报目标", "叙事主线", "页码结构", "视觉风格与图表素材", "演讲备注"):
        assert term in result
    for heavy_term in ("项目是否值得开发", "MVP", "市场需求", "商业模式"):
        assert heavy_term not in result


def test_presentation_deck_with_image_generation_keeps_image_deliverable():
    text = "帮我做一个PPT和一张图，用im g二点零帮我生成一张图，需要格式是十六比九的。"
    frame = extract_intent_frame(text)
    route = detect_task_route(text)
    result = compile_ai_task_fallback(text)

    assert route.task_type == "presentation_deck"
    assert frame.target_tool == "image 2.0"
    assert "image 2.0" in result
    assert "im g二点零" not in result
    assert "PPT/演示文稿" in result
    assert "配图/作图交付物" in result
    assert "单张配图提示词" in result
    assert "16:9" in result
    assert "不要只写 PPT 大纲" in result
    assert "制作。 PPT" not in result
    assert "：。" not in result


def test_project_evaluation_harness_is_present_in_prompts():
    user_prompt = build_user_prompt(
        raw_text="帮我分析下某某项目是否值得开发，如果值得我要做开发。",
        mode="cursor_prompt",
    )

    assert "项目评估 / vibe coding" in SYSTEM_PROMPT
    assert "市场、用户痛点、竞品" in SYSTEM_PROMPT
    assert "不要编造市场数据" in SYSTEM_PROMPT
    assert "项目是否值得开发" in FAST_SYSTEM_PROMPT
    assert "vibe coding" in user_prompt
    assert "MVP" in user_prompt


def test_fast_cursor_prompt_compiles_page_check_after_spoken_correction():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "帮我看一下这个登录页，不对不是登录页，是注册页，就是你先检查一下表单校验和按钮状态，对吧，然后不要直接改代码，先告诉我哪里有问题。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["fast_revision_applied"] is True
    assert processor.last_debug["rule_task_fallback_used"] is False
    assert "注册页" in result.final_text
    assert "登录页" not in result.final_text
    assert "对吧" not in result.final_text
    assert "不对" not in result.final_text
    assert "不要直接改代码" in result.final_text
    assert "先告诉我哪里有问题" in result.final_text


def test_fast_cursor_prompt_compiles_status_report_when_llm_echoes_speech():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "结论，当前逻辑是通的，没有收到验证码时，取消后，对换码不会失效，可以继续换号，号码记录也会保留，不会因为换号错过前面的号码状态，我也顺手确认这些接口返回里没有上游平台痕迹和敏感词命中。最后把刚才测试生成的2张临时卡和3条测试记录都从生产库清理掉了，临时拉取的生产inv文件也删除了你觉得我做得nice吗？",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["fast_revision_applied"] is True
    assert processor.last_debug["rule_task_fallback_used"] is False
    assert result.final_text.startswith("结论：当前逻辑是通的。")
    assert "未收到验证码" in result.final_text
    assert "兑换码不会失效" in result.final_text
    assert "号码记录会保留" in result.final_text
    assert "上游平台痕迹" in result.final_text
    assert "敏感词命中" in result.final_text
    assert "2 张临时卡" in result.final_text
    assert "3 条测试记录" in result.final_text
    assert "生产 env 文件" in result.final_text
    assert "你觉得我做得nice吗" in result.final_text.replace(" ", "")


def test_fast_cursor_prompt_compiles_status_report_from_real_noisy_asr():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "结论，当前逻辑是通的，没有收到验证号码时，取消后，对患马不会失效，可以继续换号，号码记录也会保留，不会因为换号错过前面的号码状态，我也顺手劝这些接口返回你，没有上有平台痕迹，和敏感司命中。最后把刚才测试生成的妈张临时卡和3条测试记录都从生产库清理掉了，您是拉去的生产inv文件也删除了你觉得我做得nice吗？",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["fast_revision_applied"] is True
    assert processor.last_debug["rule_task_fallback_used"] is False
    assert "验证码" in result.final_text
    assert "验证号码" not in result.final_text
    assert "兑换码不会失效" in result.final_text
    assert "对患马" not in result.final_text
    assert "上游平台痕迹" in result.final_text
    assert "上有平台痕迹" not in result.final_text
    assert "敏感词命中" in result.final_text
    assert "敏感司命中" not in result.final_text
    assert "2 张临时卡" in result.final_text
    assert "3 条测试记录" in result.final_text
    assert "生产 env 文件" in result.final_text
    assert "生产inv" not in result.final_text
    assert "你觉得我做得nice吗" in result.final_text.replace(" ", "")


def test_fast_cursor_prompt_repairs_explanatory_text_and_keeps_spoken_polite_tail():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "儿童时期儿童对自我的评价来源与外界的评价。儿童如果缺乏关注，需要和正向的回忆，回应成人之后就会慢慢的显现出来。在关系中，失去的东西需要在关系中找回，可以调整慢慢来，谢谢你的评价。",
        mode="cursor_prompt",
    )

    assert llm.calls == 1
    assert processor.last_debug["fast_revision_applied"] is False
    assert "来源于外界的评价" in result.final_text
    assert "来源与" not in result.final_text
    assert "肯定和正向回应" in result.final_text
    assert "谢谢你的评价" in result.final_text
    assert "general_text_fixes" in processor.last_debug


def test_fast_cursor_prompt_allows_clean_explanatory_text_to_echo():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "儿童时期，儿童对自我的评价来源于外界的评价。儿童如果缺乏关注、肯定和正向回应，成人之后就会慢慢显现出来。在关系中，失去的东西需要在关系中找回，也可以慢慢调整回来。谢谢你的评价。",
        mode="cursor_prompt",
    )

    assert llm.calls == 1
    assert processor.last_debug["quality_gate_reason"] == ""
    assert "来源于外界的评价" in result.final_text
    assert "谢谢你的评价" in result.final_text


def test_fast_cursor_prompt_repairs_pytorch_cuda_asr_context_when_llm_echoes():
    llm = CaptureFastPromptEchoLLM()
    processor = AuditorProcessor(
        llm,
        glossary=GlossaryScanner(ROOT / "src" / "glossary" / "tech_terms.json"),
        fast_mode=True,
    )
    result = processor.process(
        "速度上重启后第一次可能稍慢，因为模型预热后面正常应该明显快很多。 Asr目前还是CPU备用，这是拍touch扣达环境的问题。但从你截图看，本次ASR推理已经不到一秒，主要瓶颈已经不是ASR.",
        mode="cursor_prompt",
    )

    assert llm.calls == 1
    assert "术语规范化参考" in llm.prompt
    assert "PyTorch" in result.final_text
    assert "CUDA 环境" in result.final_text
    assert "ASR" in result.final_text
    assert "Asr" not in result.final_text
    assert "touch" not in result.final_text.lower()
    assert "扣达" not in result.final_text
    assert ".。" not in result.final_text


def test_fast_cursor_prompt_repairs_harness_context_when_llm_echoes():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "但关键不是做一个harness harness的死词典，而是理解它出现在规则约束框架、语义、审计这个上下文理，所以应该还原为harness.这就是说，这就是你说的核心，不是模型本身突然变变聪明，而是背后有一套好的harness,让小模型也能更快更稳，不是应该懂人化。",
        mode="cursor_prompt",
    )

    assert "错拼 -> harness" in result.final_text
    assert "上下文里" in result.final_text
    assert "变变聪明" not in result.final_text
    assert "懂人话" in result.final_text
    assert "懂人化" not in result.final_text


def test_cursor_prompt_compiles_test_guidance_when_llm_echoes_speech():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "你可以开始测试，但记得先重启当前编译器进程，让新代码和新perment生效。测试时可以重点是这几类英英文技术词口音不准。Part torch could at hineys torman power shop，中文同音，指词语音助手，我中文理解改口提示词改口不对，不是登录页，是注册页。自然为句谢谢你的评价。我觉得你做的我觉得我做的nice吗？状态汇报不要漏事实，事实，不要改任务请求。",
        mode="cursor_prompt",
    )

    assert "你可以开始测试" in result.final_text
    assert "重启当前编译器进程" in result.final_text
    assert "英文技术词口音不准" in result.final_text
    assert "PyTorch" in result.final_text
    assert "CUDA" in result.final_text
    assert "harness" in result.final_text
    assert "terminal" in result.final_text
    assert "PowerShell" in result.final_text
    assert "中文同音" in result.final_text
    assert "不是登录页，是注册页" in result.final_text
    assert "谢谢你的评价" in result.final_text
    assert "nice" in result.final_text
    assert "状态汇报" in result.final_text
    assert "不要漏事实" in result.final_text
    assert "不要把汇报改成任务请求" in result.final_text


def test_fast_cursor_prompt_compiles_software_feedback_when_llm_echoes_speech():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "现在我看了一下识别那个文字，中文的话应该是没什么问题。但是它对一些同义词或者说相近的词汇，它不会结合上下文，还来分析或者说推理。还有一个问题，就是我现在在我这个语音编译器上说完话过后之前是可以直接复直接复制到那个它识别到的目标界面的。比如说现在我在这个界面是codex,然后正常我说完了，我停止录音了。它分析推理出来过后，应该是直接复制粘贴到我们现在这个界面的，现在没有这个功能了。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert processor.last_debug["quality_gate_reason"] == ""
    assert processor.last_debug["quality_gate_last_reason"].startswith("software_feedback")
    assert processor.last_debug["quality_gate_stage"] == "software_feedback_guard"
    assert processor.last_debug["quality_gate_origin"] == "compiler_or_llm_missed_software_feedback"
    assert processor.last_debug["quality_gate_recommended_repair"] == "rule_task_fallback"
    assert processor.last_debug["quality_gate_repair_applied"] == "rule_task_fallback"
    assert result.final_text.startswith("请为咿呀喂（Yiyawei）实现或修复以下能力")
    assert "请检查语音指令编译器当前的以下问题" not in result.final_text
    assert "中文 ASR 字面识别基本正常" in result.final_text
    assert "LLM/harness" in result.final_text
    assert "同义词或相近词" in result.final_text
    assert "上下文做语义分析和推理" in result.final_text
    assert "自动粘贴链路需要检查" in result.final_text
    assert "Codex" in result.final_text
    assert "目标界面" in result.final_text
    assert "系统指令" not in result.final_text
    assert "现在我看了一下" not in result.final_text
    assert "比如说" not in result.final_text


def test_need_paste_feedback_compiles_to_ai_facing_task_not_system_instruction():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "我需要那个现在就是还有一个点，就是呢识别出我语音过后，它就能粘贴到那个呢识别到的界面上面。比如说现在识别到的是codex，然后它就能粘贴上去。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert result.final_text.startswith("请为咿呀喂（Yiyawei）实现或修复以下能力")
    assert "自动粘贴能力需要实现" in result.final_text
    assert "目标界面" in result.final_text
    assert "Codex" in result.final_text
    assert "请检查语音指令编译器当前的以下问题" not in result.final_text
    assert "系统指令" not in result.final_text
    assert "那个" not in result.final_text
    assert "就是呢" not in result.final_text


def test_processor_records_intent_frame_for_paste_feedback():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "这次我是提的需求，但是还是给了UI和UX的设计方案，而且没有实现自动粘贴到对话框。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["intent_frame"]["task_hint"] == "bug_report"
    assert processor.last_debug["intent_frame"]["artifact_type"] == "software_feedback"
    assert processor.last_debug["route"]["task_type"] == "bug_report"
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert processor.last_debug["quality_gate_attribution"]["intent_artifact_type"] == "software_feedback"
    assert processor.last_debug["quality_gate_repair_applied"] == "rule_task_fallback"
    assert "自动粘贴能力需要实现" in result.final_text
    assert "UI/UX 设计方案" not in result.final_text


def test_paste_taskbar_feedback_is_not_misrouted_to_ui_design():
    text = (
        "然后然后我这边粘贴过后啊，我这个界面啊，就是我们这个语音界面，"
        "它会自动弹到那个呃任务栏上面去。我需要它还是在之前窗口位置，不用自动弹到任务栏。"
    )
    route = detect_task_route(text)
    processor = AuditorProcessor(FastPromptEchoLLM(), fast_mode=True)
    result = processor.process(text, mode="cursor_prompt")

    assert route.task_type == "bug_report"
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert result.final_text.startswith("请为咿呀喂（Yiyawei）实现或修复以下能力")
    assert "粘贴后的窗口保持需要修复" in result.final_text
    assert "任务栏" in result.final_text
    assert "语音编译器窗口保持在原位置" in result.final_text
    assert "UI/UX 设计方案" not in result.final_text
    assert "用户流程" not in result.final_text


def test_ai_coding_governance_request_routes_to_product_planning_and_compiles_workflow():
    text = (
        "我现在遇到一个问题，就是我之前做的一个项目，然后被我的另外一个大模型改乱了，覆盖了本身四千行的代码，"
        "现在覆盖过后变成一千多行代码。我为了杜绝这个事情的发生，我要做哪些方面的改善和维护呢？"
        "我想你帮我提出方案和解决方法。以后，不管是你还是在codex中和，在cloud code中，我都要规避这种情况的发生。"
        "我想你把它做成一个全局，可以治理的工作方式和方法。"
    )
    route = detect_task_route(text)
    processor = AuditorProcessor(PromptEchoLLM(), fast_mode=True)
    result = processor.process(text, mode="cursor_prompt")

    assert route.task_type == "product_planning"
    assert processor.last_debug["route"]["task_type"] == "product_planning"
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "全局防覆盖治理工作流" in result.final_text or "全局防覆盖治理" in result.final_text
    assert "Codex" in result.final_text
    assert "Claude Code" in result.final_text
    assert "diff" in result.final_text.lower()
    assert "AGENTS.md" in result.final_text
    assert "AGENTS. md" not in result.final_text
    assert "Bug 反馈" not in result.final_text
    assert "可复现" not in result.final_text


def test_account_switch_automation_request_routes_to_product_planning_and_cleans_spoken_noise():
    text = (
        "因为我不知道我们现在这个软件有不有呃这个功能，就是自动知道那个呃closer他反馈给我们就说没有额度了，"
        "需要切换了。然后，嗯，后台这个软件就能自适应的，呃，自己切换账号，注入账号就无感的嘛。"
        "因为我们对标的这个软件它是可以无感的嘛。"
    )
    route = detect_task_route(text)
    processor = AuditorProcessor(PromptEchoLLM(), fast_mode=True)
    result = processor.process(text, mode="cursor_prompt")

    assert route.task_type == "product_planning"
    assert processor.last_debug["route"]["task_type"] == "product_planning"
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "自动无感切换" in result.final_text
    assert "账号额度不足" in result.final_text
    assert "有没有" in result.final_text
    assert "有不有" not in result.final_text
    assert "呃" not in result.final_text
    assert "嗯" not in result.final_text
    assert "，，" not in result.final_text
    assert not result.final_text.endswith("嘛")


def test_fast_cursor_prompt_compiles_recording_interaction_feedback():
    llm = FastPromptEchoLLM()
    processor = AuditorProcessor(llm, fast_mode=True)
    result = processor.process(
        "现在识别语音还是相当快的，但是我每次都要去点一下停止录音它能不能？比如说我现在设置一个停顿，或者说我说完了，然后就停止录音，但是不要把我说的这句我说完了录进去翻译出来。相当于是一个唤起词，比如说我说开始录音，那我们这个系统就开始录音，或者说一个结束词，然后就自动识别，我说完了，就自动结束，不要我手动去点这个开始录音和停止录音。还有就是有一些气口词，比如嗯嗯啊啊，就是常见的这样卡壳的词汇。现在我觉得最好设置一个快捷键，不和我桌面应用排斥的，就是开始触发录音。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "录音交互需要支持自动结束" in result.final_text
    assert "停顿、结束词或“我说完了”" in result.final_text
    assert "不要把这些结束词写进最终文本" in result.final_text
    assert "快捷键或按钮触发" in result.final_text
    assert "气口词和卡壳词" in result.final_text
    assert "每次都要去点一下" not in result.final_text


def test_status_report_missing_facts_triggers_revision_or_fallback():
    llm = OmitStatusFactsThenEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "结论，当前逻辑是通的，没有收到验证码时取消后兑换码不会失效，可以继续换号，号码也会保留，不会因为换号错过前面的号码状态。我也顺手确认了这些接口，返回里没有上有平台痕迹或敏感词命中。最后把刚才测试的两张临时卡和三条测试记录都从生产库清掉或临时拉取的生产或NV文件也删掉了。",
        mode="cursor_prompt",
    )

    assert llm.calls == 2
    assert processor.last_debug["revision_applied"] is True
    assert "号码" in result.final_text
    assert "保留" in result.final_text
    assert "临时卡" in result.final_text
    assert "测试记录" in result.final_text
    assert "生产" in result.final_text
    assert "NV文件" in result.final_text or "env" in result.final_text.lower()


def test_cursor_prompt_compiles_execution_difficulty_request_when_llm_echoes_speech():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "这个任务的执行难度不亚于要从新训练一个新的导模型。新的吗模型上没有指导的情况下，会说没有你的情况。什么是怎么能有power呢？我不知道你会不会执行这个任务，你来怎么执行这个任务。那你各位意见真好吧。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "重新训练一个新的" in result.final_text
    assert "指导信息" in result.final_text
    assert "power" in result.final_text
    assert "请给出你的意见" in result.final_text


def test_cursor_prompt_keeps_vpc_positioning_details_when_llm_echoes_speech():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "新的项目编辑也明确了，不是TTS，不是云往手，不是普通听写工具，用户可以说的乱说的不专业说不完整，插件负责不结构，删废话，理解接口，最后输出是何Cursor，ChatGPT Claude Gemini Codex执行任务的提示池。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert "不是 TTS" in result.final_text
    assert "不是普通听写工具" in result.final_text
    assert "删废话" in result.final_text


def test_processor_simplifies_asr_before_corrections_and_llm():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "你能聽見我說話嗎，今天是星期幾",
        mode="normal_dictation",
    )

    assert processor.last_debug["asr_audit_text"].startswith("你能听见")
    assert "听见" in result.final_text
    assert "星期几" in result.final_text


def test_quality_gate_near_echo_can_be_cleared_after_rule_fallback():
    llm = AlwaysEchoLLM()
    processor = AuditorProcessor(llm)
    processor.process(
        "今天把中文口语重复表达这块口内容整理成合适的粘贴到chartGPT Claude Gemini Cursor Waste Code 的中端输入框的专业文本不是普通语音转文字，而是机器人，不是机器人聊天，不是代码生成器。",
        mode="cursor_prompt",
    )

    assert processor.last_debug["rule_task_fallback_used"] is True
    assert processor.last_debug["quality_gate_reason"] == ""


def test_spoken_self_correction_keeps_latest_phrase():
    llm = PromptEchoLLM()
    processor = AuditorProcessor(llm)
    result = processor.process(
        "不是聊天机器人，我说错了，不是机器人聊天，不是代码生成器。",
        mode="cursor_prompt",
    )

    assert "不是机器人聊天" in result.final_text
    assert "不是聊天机器人" not in result.final_text
    assert processor.last_debug["self_corrections"]


def test_remove_task_boilerplate_strips_internal_template_sentence():
    text = remove_task_boilerplate(
        "请把中文口语、重复表达和改口内容整理成适合直接粘贴给 AI 执行的专业任务需求。\n"
        "输出文本要适合粘贴到 ChatGPT、Claude、Gemini、Cursor、VS Code 等 AI 工具。"
    )
    assert "请把中文口语" not in text
    assert text.startswith("输出文本")
