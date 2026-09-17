#!/usr/bin/env python3
"""Generate review-only route-sample candidates from the GitHub source catalog.

This extractor is deliberately offline. It reads only the local catalog and
does not fetch GitHub, clone repositories, download datasets, or copy upstream
content. The output is a review queue for humans, not runtime data.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.auditor.task_router import detect_task_route


DEFAULT_CATALOG = ROOT / "data" / "github_source_catalog.json"
DEFAULT_OUTPUT = ROOT / "output" / "github_route_sample_candidates.json"
ALLOWED_RUNTIME_POLICIES = {
    "offline_candidate_source",
    "offline_reference_only",
    "index_only_no_import",
}


@dataclass(frozen=True)
class CandidateBlueprint:
    task_type: str
    domain: str
    spoken_type: str
    input_pattern: str
    sample_input: str
    output_shape: tuple[str, ...]
    must_keep: tuple[str, ...]
    must_drop: tuple[str, ...]


TASK_BLUEPRINTS: dict[str, tuple[CandidateBlueprint, ...]] = {
    "code_fix": (
        CandidateBlueprint(
            task_type="code_fix",
            domain="general",
            spoken_type="代码修复",
            input_pattern="报错 / 跑不起来 / 不知道哪里坏了 / 先定位再改",
            sample_input="这个接口突然报错跑不起来了，帮我先定位原因，再给最小修复方案。",
            output_shape=("问题定位", "最小修改方案", "验证方式"),
            must_keep=("先定位原因", "最小修复方案", "验证方式"),
            must_drop=("项目评估", "UI 设计", "闲聊回复"),
        ),
        CandidateBlueprint(
            task_type="bug_report",
            domain="general",
            spoken_type="Bug 反馈",
            input_pattern="之前能用现在不行 / 没反应 / 复现不清楚",
            sample_input="这个功能之前能用，现在点了没有反应，帮我整理成可排查的 bug 反馈。",
            output_shape=("问题摘要", "复现步骤", "期望行为与实际行为", "排查建议"),
            must_keep=("之前能用", "现在没有反应", "可排查"),
            must_drop=("项目规划", "商业分析", "闲聊回复"),
        ),
    ),
    "bug_report": (
        CandidateBlueprint(
            task_type="bug_report",
            domain="general",
            spoken_type="Bug 反馈",
            input_pattern="失败现象 / 影响范围 / 日志或报错线索不完整",
            sample_input="用户列表现在加载不出来，但我不确定是不是接口问题，帮我写成 bug 排查反馈。",
            output_shape=("问题摘要", "影响范围", "排查方向", "验收标准"),
            must_keep=("用户列表", "加载不出来", "排查"),
            must_drop=("删除用户", "项目评估", "UI 设计"),
        ),
    ),
    "test_plan": (
        CandidateBlueprint(
            task_type="test_plan",
            domain="general",
            spoken_type="测试计划",
            input_pattern="不知道测什么 / 回归测试 / 边界情况 / 异常路径",
            sample_input="这个功能我不知道该测哪些点，帮我生成回归测试计划和验收清单。",
            output_shape=("测试范围", "用例分组", "边界情况", "验收标准"),
            must_keep=("回归测试计划", "验收清单", "边界情况"),
            must_drop=("直接写代码", "项目评估", "闲聊回复"),
        ),
    ),
    "ui_ux_design": (
        CandidateBlueprint(
            task_type="ui_ux_design",
            domain="general",
            spoken_type="UI/UX 设计",
            input_pattern="不好看 / 布局乱 / 流程不顺 / 状态不完整",
            sample_input="这个设置页看起来有点乱，帮我设计 UI 布局、交互状态和验收标准。",
            output_shape=("设计目标", "用户流程", "关键界面与组件", "验收标准"),
            must_keep=("设置页", "UI 布局", "交互状态"),
            must_drop=("商业分析", "项目评估", "代码修复"),
        ),
    ),
    "product_planning": (
        CandidateBlueprint(
            task_type="product_planning",
            domain="general",
            spoken_type="产品规划",
            input_pattern="MVP / PRD / 路线图 / 功能优先级",
            sample_input="我想做这个功能，但范围有点乱，帮我拆成 MVP、优先级和版本路线图。",
            output_shape=("产品目标", "功能范围", "优先级", "版本路线图", "验收标准"),
            must_keep=("MVP", "优先级", "路线图"),
            must_drop=("是否值得开发判断", "市场规模编造", "直接写代码"),
        ),
    ),
    "business_analysis": (
        CandidateBlueprint(
            task_type="business_analysis",
            domain="general",
            spoken_type="商业分析",
            input_pattern="商业模式 / 收入成本 / 获客转化 / 留存复购",
            sample_input="帮我分析这个订阅产品的商业模式、获客渠道、转化率、留存和主要成本。",
            output_shape=("分析目标", "客户与需求", "商业模式", "获客与转化", "成本与收益"),
            must_keep=("商业模式", "获客渠道", "转化率", "留存", "成本"),
            must_drop=("代码修复", "UI 设计", "闲聊回复"),
        ),
    ),
    "text_polishing": (
        CandidateBlueprint(
            task_type="text_polishing",
            domain="general",
            spoken_type="普通文本润色",
            input_pattern="润色 / 改写 / 不要扩写 / 语气自然",
            sample_input="帮我润色这句话，语气自然一点，但不要扩写：今天的会议辛苦大家了。",
            output_shape=("润色后文本", "必要说明"),
            must_keep=("语气自然", "不要扩写", "今天的会议辛苦大家了"),
            must_drop=("项目评估", "商业分析", "开发路线图"),
        ),
    ),
    "generic_task": (
        CandidateBlueprint(
            task_type="generic_task",
            domain="general",
            spoken_type="通用任务/负样本",
            input_pattern="轻闲聊 / 普通短句 / 不应扩写",
            sample_input="我只是想随便聊一下，不要新建任务，也不要写项目方案。",
            output_shape=("轻量回复", "保留约束"),
            must_keep=("随便聊一下", "不要新建任务", "不要写项目方案"),
            must_drop=("代码修复", "项目评估", "测试计划"),
        ),
    ),
    "domain_terms": (
        CandidateBlueprint(
            task_type="project_evaluation",
            domain="general",
            spoken_type="领域词增强",
            input_pattern="行业词 / 领域问题 / 任务类型待人工确认",
            sample_input="帮我分析这个垂直领域工具是否值得开发，如果值得再拆 MVP 和验证路线。",
            output_shape=("项目澄清", "市场与用户", "风险", "MVP", "验证路线"),
            must_keep=("是否值得开发", "MVP", "验证路线"),
            must_drop=("编造市场数据", "直接写代码", "闲聊回复"),
        ),
    ),
    "task_type_taxonomy": (
        CandidateBlueprint(
            task_type="generic_task",
            domain="general",
            spoken_type="任务分类参考",
            input_pattern="任务类型边界 / 分类歧义 / 需要人工审核",
            sample_input="这句话可能是任务请求也可能只是说明，帮我判断应该走哪类处理。",
            output_shape=("候选任务类型", "判断依据", "不确定信息"),
            must_keep=("判断任务类型", "判断依据", "不确定"),
            must_drop=("直接执行", "编造上下文", "项目方案"),
        ),
    ),
    "template_fragments": (
        CandidateBlueprint(
            task_type="generic_task",
            domain="general",
            spoken_type="模板片段参考",
            input_pattern="输出结构 / 验收标准 / 模板片段",
            sample_input="帮我把这类需求整理成结构清楚的执行提示词，要包含验收标准。",
            output_shape=("任务目标", "执行步骤", "验收标准"),
            must_keep=("执行提示词", "验收标准", "结构清楚"),
            must_drop=("长篇教程", "外部原文", "运行时知识库"),
        ),
    ),
    "quality_gate": (
        CandidateBlueprint(
            task_type="generic_task",
            domain="general",
            spoken_type="质量闸门负样本",
            input_pattern="误扩写 / 误路由 / 过薄输出 / 内部 prompt 泄露",
            sample_input="帮我检查这个输出有没有把普通短句误扩写成项目方案。",
            output_shape=("风险类型", "判断依据", "修正建议"),
            must_keep=("误扩写", "普通短句", "项目方案"),
            must_drop=("直接采纳", "忽略风险", "外部调研"),
        ),
    ),
}


def build_report(
    catalog_path: Path,
    *,
    limit: int = 200,
    include_reference_only: bool = True,
) -> dict[str, Any]:
    catalog_path = catalog_path.expanduser().resolve()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, list):
        raise ValueError("GitHub source catalog must be a JSON list")

    candidates: list[dict[str, Any]] = []
    skipped_sources: list[dict[str, Any]] = []

    for source in catalog:
        if len(candidates) >= limit:
            break
        if not isinstance(source, dict):
            skipped_sources.append({"reason": "source_not_object", "source": repr(source)[:120]})
            continue

        skip_reason = _skip_reason(source, include_reference_only=include_reference_only)
        if skip_reason:
            skipped_sources.append(
                {
                    "repo": source.get("repo", ""),
                    "reason": skip_reason,
                    "runtime_policy": source.get("runtime_policy"),
                    "hot_path_allowed": source.get("hot_path_allowed"),
                }
            )
            continue

        for use_for in source.get("use_for") or []:
            for blueprint in TASK_BLUEPRINTS.get(str(use_for), ()):
                if len(candidates) >= limit:
                    break
                candidates.append(_build_candidate(source, str(use_for), blueprint, len(candidates) + 1))

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "offline_catalog_only",
        "source_catalog": str(catalog_path),
        "network_used": False,
        "repo_clone_or_download_used": False,
        "runtime_hot_path_used": False,
        "review_required": True,
        "candidate_count": len(candidates),
        "sources_scanned": len(catalog),
        "skipped_source_count": len(skipped_sources),
        "candidates": candidates,
        "skipped_sources": skipped_sources,
    }


def _skip_reason(source: dict[str, Any], *, include_reference_only: bool) -> str:
    if source.get("hot_path_allowed") is not False:
        return "hot_path_allowed_not_false"
    runtime_policy = source.get("runtime_policy")
    if runtime_policy not in ALLOWED_RUNTIME_POLICIES:
        return "runtime_policy_not_allowed"
    if not include_reference_only and runtime_policy != "offline_candidate_source":
        return "reference_only_excluded"
    if not source.get("use_for"):
        return "missing_use_for"
    return ""


def _build_candidate(
    source: dict[str, Any],
    use_for: str,
    blueprint: CandidateBlueprint,
    index: int,
) -> dict[str, Any]:
    route = detect_task_route(blueprint.sample_input)
    candidate_id = _candidate_id(source.get("repo", ""), use_for, blueprint.task_type, index)
    sample_id = candidate_id.replace("github_", "github_sample_", 1)
    return {
        "candidate_id": candidate_id,
        "review_status": "review_only",
        "hot_path_allowed": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "candidate_kind": "route_sample_seed",
        "derived_from": "catalog_metadata_only",
        "source": {
            "repo": source.get("repo", ""),
            "url": source.get("url", ""),
            "tier": source.get("tier", ""),
            "license": source.get("license", ""),
            "source_type": source.get("source_type", ""),
            "runtime_policy": source.get("runtime_policy", ""),
            "import_policy": source.get("import_policy", ""),
        },
        "use_for": [use_for],
        "expected_task_type": blueprint.task_type,
        "expected_domain": blueprint.domain,
        "current_task_type": route.task_type,
        "current_domain": route.domain,
        "spoken_type": blueprint.spoken_type,
        "input_pattern": blueprint.input_pattern,
        "suggested_route_sample": {
            "id": sample_id,
            "spoken_type": blueprint.spoken_type,
            "input": blueprint.sample_input,
            "expected_task_type": blueprint.task_type,
            "expected_domain": blueprint.domain,
            "output_shape": list(blueprint.output_shape),
            "must_keep": list(blueprint.must_keep),
            "must_drop": list(blueprint.must_drop),
        },
        "risk_notes": [
            "Generated from local catalog metadata only; no upstream issue, README, prompt, or dataset text copied.",
            "Must be manually reviewed before entering tests/route_samples.json or runtime templates.",
            "Review router mismatch before accepting if current_task_type/current_domain differ from expected values.",
        ],
    }


def _candidate_id(repo: str, use_for: str, task_type: str, index: int) -> str:
    repo_slug = re.sub(r"[^a-zA-Z0-9]+", "_", repo.lower()).strip("_") or "repo"
    use_slug = re.sub(r"[^a-zA-Z0-9]+", "_", use_for.lower()).strip("_") or "use"
    task_slug = re.sub(r"[^a-zA-Z0-9]+", "_", task_type.lower()).strip("_") or "task"
    return f"github_{repo_slug}_{use_slug}_{task_slug}_{index:03d}"[:120]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate GitHub route-sample candidates offline")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="local GitHub source catalog path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--limit", type=int, default=200, help="maximum candidate count")
    parser.add_argument(
        "--offline-candidate-only",
        action="store_true",
        help="exclude offline_reference_only and index_only_no_import sources",
    )
    parser.add_argument("--print-json", action="store_true", help="print JSON report to stdout")
    args = parser.parse_args(argv)

    try:
        report = build_report(
            Path(args.catalog),
            limit=max(1, args.limit),
            include_reference_only=not args.offline_candidate_only,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            f"Scanned {report['sources_scanned']} catalog sources; "
            f"generated {report['candidate_count']} review-only candidates; "
            f"skipped {report['skipped_source_count']} sources."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
