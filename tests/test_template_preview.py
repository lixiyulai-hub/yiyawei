from __future__ import annotations

from src.auditor.template_preview import (
    build_novice_template_preview,
    render_novice_template_preview,
)


def test_project_preview_includes_domain_focus_without_full_fallback_prompt():
    preview = build_novice_template_preview("帮我分析一个电商项目是否值得开发，如果值得我要做开发。")

    assert preview is not None
    rendered = render_novice_template_preview(preview)
    assert preview.task_type == "project_evaluation"
    assert preview.domain == "ecommerce"
    for term in ("SKU", "供应链", "获客", "转化率"):
        assert term in rendered
    assert "建议结构" in rendered
    assert "请按完整链路执行" not in rendered
    assert len(rendered) <= 1200


def test_non_project_preview_keeps_project_plan_terms_out():
    preview = build_novice_template_preview("请修复登录接口报错，先定位原因再改代码。")

    assert preview is not None
    rendered = render_novice_template_preview(preview)
    assert preview.task_type == "code_fix"
    for term in ("代码修复", "问题定位", "修改方案", "验证方式"):
        assert term in rendered
    for project_term in ("是否值得开发", "市场需求", "竞品", "商业模式", "开发路线图"):
        assert project_term not in rendered


def test_preview_returns_none_for_lightweight_chat_and_plain_short_text():
    assert build_novice_template_preview("讲个冷笑话。") is None
    assert build_novice_template_preview("今天的会议辛苦大家了。") is None


def test_preview_uses_reader_facing_words_not_internal_jargon():
    preview = build_novice_template_preview("金融风控系统是否值得开发，如果值得我要做开发。")

    assert preview is not None
    rendered = render_novice_template_preview(preview)
    assert "KYC" in rendered
    assert "灰度风控" in rendered
    for internal_term in ("task_type=", "few-shot", "route_context", "任务路由与模板参考"):
        assert internal_term not in rendered
