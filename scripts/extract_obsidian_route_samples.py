#!/usr/bin/env python3
"""Extract route-sample candidates from Obsidian notes.

The extractor is read-only for the vault. It scans markdown notes for known
failure families and writes a JSON report that can be reviewed before any
sample is copied into tests/route_samples.json.
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


DEFAULT_OUTPUT = ROOT / "output" / "obsidian_route_sample_candidates.json"
SKIP_DIR_NAMES = {
    ".git",
    ".obsidian",
    ".trash",
    "node_modules",
    "__pycache__",
}
MAX_NOTE_BYTES = 350_000


@dataclass(frozen=True)
class CandidateFamily:
    key: str
    spoken_type: str
    expected_task_type: str
    expected_domain: str
    patterns: tuple[str, ...]
    output_shape: tuple[str, ...]
    must_drop: tuple[str, ...]
    reason: str


CHAT_FAILURE_FAMILIES: tuple[CandidateFamily, ...] = (
    CandidateFamily(
        key="obsidian_tell_joke_no_actionable_route",
        spoken_type="轻闲聊",
        expected_task_type="generic_task",
        expected_domain="general",
        patterns=(
            r"讲个冷笑话",
            r"讲个笑话",
            r"说个笑话",
            r"来个笑话",
            r"讲个段子",
        ),
        output_shape=("闲聊回复",),
        must_drop=("代码修复", "项目评估", "开发路线图", "测试计划"),
        reason="笑话/段子类轻闲聊不应进入 code、bug 或项目评估链路。",
    ),
    CandidateFamily(
        key="obsidian_praise_me_no_actionable_route",
        spoken_type="轻闲聊",
        expected_task_type="generic_task",
        expected_domain="general",
        patterns=("夸我一句",),
        output_shape=("闲聊回复",),
        must_drop=("代码修复", "项目评估", "排查 bug", "新建笔记"),
        reason="夸奖类祈使式闲聊不应被当成可执行开发任务。",
    ),
    CandidateFamily(
        key="obsidian_chat_with_me_no_actionable_route",
        spoken_type="轻闲聊",
        expected_task_type="generic_task",
        expected_domain="general",
        patterns=(
            r"陪我聊会儿",
            r"陪我聊一会儿",
            r"陪我聊一下",
            r"陪我闲聊一下",
            r"随便聊聊",
            r"陪我说说话",
            r"陪我解解闷",
        ),
        output_shape=("闲聊回复",),
        must_drop=("代码修复", "项目评估", "商业分析", "开发任务"),
        reason="陪聊类轻闲聊应保持轻量，不生成任务 brief。",
    ),
    CandidateFamily(
        key="obsidian_comfort_me_no_actionable_route",
        spoken_type="轻闲聊",
        expected_task_type="generic_task",
        expected_domain="general",
        patterns=(
            r"安慰我一下",
            r"哄我开心",
            r"逗我一下",
            r"让我笑一下",
        ),
        output_shape=("闲聊回复",),
        must_drop=("代码修复", "项目评估", "产品规划", "测试计划"),
        reason="安慰/逗笑类轻闲聊不应被升级成产品或代码任务。",
    ),
    CandidateFamily(
        key="obsidian_story_no_actionable_route",
        spoken_type="轻闲聊",
        expected_task_type="generic_task",
        expected_domain="general",
        patterns=(
            r"讲个故事",
            r"给我讲个睡前故事",
            r"讲个童话",
        ),
        output_shape=("闲聊回复",),
        must_drop=("代码修复", "项目评估", "内容规划", "开发路线图"),
        reason="故事类轻闲聊不应误入可执行任务链路。",
    ),
)


METHODOLOGY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"route first", "route first"),
    (r"minimal sufficient binding", "minimal sufficient binding"),
    (r"proof-backed output", "proof-backed output"),
    (r"一轮一问题窄修复", "一轮一问题窄修复"),
    (r"只改路由判定", "只改路由判定"),
    (r"失败语料库\s*->\s*路由状态机审计\s*->\s*自动回归矩阵", "失败语料库 -> 路由状态机审计 -> 自动回归矩阵"),
    (r"plain_chat\s*->\s*chat", "plain_chat -> chat"),
    (r"initial_model_call\s*->\s*code", "initial_model_call -> code"),
)


def build_report(vault: Path, limit: int = 200) -> dict[str, Any]:
    vault = vault.expanduser().resolve()
    candidates: list[dict[str, Any]] = []
    methodology_hits: list[dict[str, Any]] = []
    seen_candidates: set[tuple[str, str]] = set()
    files_scanned = 0

    for note_path in _iter_markdown_notes(vault):
        files_scanned += 1
        try:
            text = note_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = note_path.read_text(encoding="utf-8", errors="ignore")
        rel_path = _safe_relative(note_path, vault)

        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            for candidate in _extract_line_candidates(rel_path, line_number, stripped):
                key = (candidate["family"], candidate["input"])
                if key in seen_candidates:
                    continue
                seen_candidates.add(key)
                candidates.append(candidate)
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break
            methodology_hits.extend(
                _extract_methodology_hits(rel_path, line_number, stripped, limit=limit)
            )
        if len(candidates) >= limit:
            break

    return {
        "vault": str(vault),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files_scanned": files_scanned,
        "candidate_count": len(candidates),
        "methodology_hit_count": len(methodology_hits[:limit]),
        "candidates": candidates,
        "methodology_hits": methodology_hits[:limit],
    }


def _iter_markdown_notes(vault: Path) -> list[Path]:
    if not vault.exists():
        return []

    notes: list[Path] = []
    for path in vault.rglob("*.md"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        try:
            if path.stat().st_size > MAX_NOTE_BYTES:
                continue
        except OSError:
            continue
        notes.append(path)
    return sorted(notes, key=lambda item: str(item).lower())


def _extract_line_candidates(rel_path: str, line_number: int, line: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for family in CHAT_FAILURE_FAMILIES:
        for pattern in family.patterns:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                phrase = _normalize_input(match.group(0))
                route = detect_task_route(phrase)
                candidates.append(
                    {
                        "candidate_id": _candidate_id(family.key, phrase),
                        "family": family.key,
                        "spoken_type": family.spoken_type,
                        "input": phrase,
                        "expected_task_type": family.expected_task_type,
                        "expected_domain": family.expected_domain,
                        "current_task_type": route.task_type,
                        "current_domain": route.domain,
                        "confidence": "high",
                        "source": {
                            "path": rel_path,
                            "line": line_number,
                        },
                        "evidence": _trim(line),
                        "reason": family.reason,
                        "suggested_route_sample": {
                            "id": _candidate_id(family.key, phrase),
                            "spoken_type": family.spoken_type,
                            "input": phrase,
                            "expected_task_type": family.expected_task_type,
                            "expected_domain": family.expected_domain,
                            "output_shape": list(family.output_shape),
                            "must_keep": [phrase.rstrip("。！？")],
                            "must_drop": list(family.must_drop),
                        },
                    }
                )
    return candidates


def _extract_methodology_hits(
    rel_path: str,
    line_number: int,
    line: str,
    limit: int,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for pattern, label in METHODOLOGY_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            hits.append(
                {
                    "label": label,
                    "source": {
                        "path": rel_path,
                        "line": line_number,
                    },
                    "evidence": _trim(line),
                }
            )
            if len(hits) >= limit:
                break
    return hits


def _normalize_input(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip(" `\"'“”‘’：:，,；;、")
    if not cleaned:
        return ""
    if re.search(r"[。！？!?]$", cleaned):
        return cleaned
    return f"{cleaned}。"


def _candidate_id(prefix: str, phrase: str) -> str:
    compact = re.sub(r"[^\w\u3400-\u9fff]+", "_", phrase, flags=re.UNICODE).strip("_")
    compact = compact[:28] or "sample"
    return f"{prefix}_{compact}"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _trim(text: str, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract Obsidian route-sample candidates")
    parser.add_argument(
        "--vault",
        required=True,
        help="user-selected Obsidian vault path; no machine-specific default is used",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--limit", type=int, default=200, help="maximum candidate count")
    parser.add_argument("--print-json", action="store_true", help="print JSON report to stdout")
    args = parser.parse_args(argv)

    report = build_report(Path(args.vault), limit=max(1, args.limit))
    output_text = json.dumps(report, ensure_ascii=False, indent=2)

    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            f"Scanned {report['files_scanned']} markdown files; "
            f"found {report['candidate_count']} candidates and "
            f"{report['methodology_hit_count']} methodology hits."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
