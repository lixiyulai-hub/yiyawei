"""Sidecar novice-facing previews for task templates.

This module is intentionally not wired into ``AuditorProcessor``. It reuses the
small static router/template catalog so offline governance tools can show how a
spoken request would be shaped without expanding the runtime prompt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.auditor.task_router import (
    DomainType,
    TaskType,
    detect_task_route,
    get_task_prompt_template,
    get_task_template,
    required_domain_terms,
    retrieve_examples,
    retrieve_question_templates,
)


@dataclass(frozen=True)
class TemplatePreview:
    source_text: str
    task_type: TaskType
    task_label: str
    domain: DomainType
    domain_label: str
    title: str
    will_cover: tuple[str, ...]
    output_sections: tuple[str, ...]
    guardrails: tuple[str, ...]
    domain_focus: tuple[str, ...] = ()
    example: str = ""
    novice_questions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_novice_template_preview(text: str) -> TemplatePreview | None:
    """Build a compact preview for human review, or ``None`` for plain chat.

    The preview is deliberately bounded and uses reader-facing wording. It does
    not return the full executable prompt and it does not read any governance
    artifacts.
    """

    source_text = _clean(text)
    if not source_text:
        return None

    route = detect_task_route(source_text)
    if route.task_type == "generic_task" and route.task_score == 0 and route.domain_score == 0:
        return None

    task_template = get_task_template(route.task_type)
    prompt_template = get_task_prompt_template(route.task_type)
    title = prompt_template.title if prompt_template else (task_template.label if task_template else route.task_label)
    will_cover = _bounded(
        prompt_template.focus_items if prompt_template else (task_template.output_requirements if task_template else ()),
        4,
    )
    output_sections = _bounded(
        prompt_template.output_sections if prompt_template else _project_sections(route.task_type),
        6,
    )
    guardrails = _bounded(
        prompt_template.constraints if prompt_template else (task_template.guardrails if task_template else ()),
        2,
    )
    domain_focus: tuple[str, ...] = ()
    if route.task_type == "project_evaluation" and route.domain != "general":
        domain_focus = _bounded(required_domain_terms(route.domain), 6)

    examples = retrieve_examples(route.task_type, route.domain, limit=1)
    example = ""
    if examples:
        example = f"{examples[0].user_pattern} -> {examples[0].final_text_outline}"

    questions = retrieve_question_templates(route.task_type, route.domain, limit=2)
    novice_questions = tuple(
        f"{question.question}（关注：{'、'.join(question.expected_focus)}）"
        if question.expected_focus
        else question.question
        for question in questions
    )

    return TemplatePreview(
        source_text=source_text,
        task_type=route.task_type,
        task_label=route.task_label,
        domain=route.domain,
        domain_label=route.domain_label,
        title=title,
        will_cover=will_cover,
        output_sections=output_sections,
        guardrails=guardrails,
        domain_focus=domain_focus,
        example=example,
        novice_questions=novice_questions,
    )


def render_novice_template_preview(preview: TemplatePreview) -> str:
    lines = [
        f"我会把这段语音整理成：{preview.title}",
        f"识别到的方向：{preview.task_label}；领域：{preview.domain_label}。",
        "会重点覆盖：",
    ]
    lines.extend(f"- {item}" for item in preview.will_cover)
    if preview.domain_focus:
        lines.append("领域加重点：" + "、".join(preview.domain_focus) + "。")
    if preview.output_sections:
        lines.append("建议结构：" + " / ".join(preview.output_sections) + "。")
    if preview.novice_questions:
        lines.append("可追问：" + "；".join(preview.novice_questions) + "。")
    if preview.example:
        lines.append("参考表达：" + preview.example)
    if preview.guardrails:
        lines.append("边界：" + "；".join(preview.guardrails) + "。")
    return "\n".join(lines)


def _clean(text: str) -> str:
    return " ".join((text or "").strip().split())


def _bounded(items: tuple[str, ...], limit: int) -> tuple[str, ...]:
    return tuple(item for item in items if item)[:limit]


def _project_sections(task_type: TaskType) -> tuple[str, ...]:
    if task_type != "project_evaluation":
        return ()
    return (
        "项目澄清",
        "用户痛点",
        "市场与竞品",
        "商业模式",
        "技术可行性",
        "MVP 与路线图",
    )
