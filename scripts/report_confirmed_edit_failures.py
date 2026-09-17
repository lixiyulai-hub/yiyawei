#!/usr/bin/env python3
"""Report local confirmed-edit failures and review-only regression seeds.

This script reads the local SQLite "wrong-question notebook" produced by
confirmed edits. It is an offline governance artifact generator: it does not
touch runtime prompt compilation, does not promote samples, and does not edit
tests/route_samples.json.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso


DEFAULT_DB = ROOT / "data" / "sessions.db"
DEFAULT_OUTPUT = ROOT / "output" / "confirmed_edit_failures_report.json"
SCRIPT_NAME = "scripts/report_confirmed_edit_failures.py"
ARTIFACT_VERSION = 1

PROMOTABLE_FAILURE_TYPES = {
    "asr_term_error",
    "spoken_noise_cleanup",
    "intent_misroute",
    "router_misroute",
    "compiler_template_leak",
    "over_expansion",
    "under_compilation",
    "paste_feedback_missed",
}

FAILURE_SEVERITY = {
    "compiler_template_leak": "high",
    "paste_feedback_missed": "high",
    "intent_misroute": "high",
    "router_misroute": "high",
    "over_expansion": "high",
    "under_compilation": "medium",
    "asr_term_error": "medium",
    "spoken_noise_cleanup": "low",
    "punctuation_or_wording": "low",
    "unknown": "unknown",
}

INTERNAL_TEMPLATE_TERMS = [
    "task_type=",
    "route_context",
    "任务路由",
    "任务模板",
    "模板约束",
    "系统指令",
    "内部提示词",
]

SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b"), "<API_KEY>"),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|cookie)\s*[:=]\s*[A-Za-z0-9_.-]{8,}"), r"\1=<SECRET>"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "<PHONE>"),
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "<ID_NUMBER>"),
    (re.compile(r"(?<!\d)\d{12,}(?!\d)"), "<LONG_NUMBER>"),
    (re.compile(r"\b[A-Za-z]:\\[^\s，。；;]+"), "<LOCAL_PATH>"),
)


def build_report(
    db_path: Path,
    *,
    limit: int = 200,
    failure_types: set[str] | None = None,
    source_kinds: set[str] | None = None,
    regression_only: bool = False,
    max_text_chars: int = 500,
) -> dict[str, Any]:
    db_path = db_path.expanduser().resolve()
    db_exists = db_path.exists()
    all_rows, load_errors = _load_rows(db_path, limit=limit) if db_exists else ([], [])
    rows = _filter_rows(
        all_rows,
        failure_types=failure_types,
        source_kinds=source_kinds,
        regression_only=regression_only,
    )

    items: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    redacted_count = 0
    for row in rows:
        item, changed = _report_item(row, max_text_chars=max_text_chars)
        redacted_count += changed
        items.append(item)
        if _is_regression_candidate(row):
            candidate, changed = _regression_candidate(item, max_text_chars=max_text_chars)
            redacted_count += changed
            candidates.append(candidate)

    by_failure_type = Counter(str(row.get("inferred_failure_type") or "unknown") for row in rows)
    by_source_kind = Counter(str(row.get("source_kind") or "unknown") for row in rows)
    by_regression_flag = Counter("true" if row.get("should_add_regression") else "false" for row in rows)
    by_severity = Counter(_severity(str(row.get("inferred_failure_type") or "unknown")) for row in rows)

    valid = db_exists and not load_errors
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "mode": "offline_confirmed_edit_failure_report",
        "db_path": str(db_path),
        "db_exists": db_exists,
        "db_sha256": sha256_file(db_path) if db_exists else "",
        "load_errors": load_errors,
        "filters": {
            "limit": limit,
            "failure_types": sorted(failure_types or []),
            "source_kinds": sorted(source_kinds or []),
            "regression_only": regression_only,
            "max_text_chars": max_text_chars,
        },
        "total_loaded_count": len(all_rows),
        "filtered_count": len(rows),
        "regression_candidate_count": len(candidates),
        "by_failure_type": dict(sorted(by_failure_type.items())),
        "by_source_kind": dict(sorted(by_source_kind.items())),
        "by_regression_flag": dict(sorted(by_regression_flag.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "redaction": {
            "enabled": True,
            "max_text_chars": max_text_chars,
            "redacted_count": redacted_count,
        },
        "items": items,
        "regression_candidates": candidates,
        "status": {
            "valid": valid,
            "runtime_isolated": True,
            "has_failures": bool(rows),
            "has_regression_candidates": bool(candidates),
            "ready_for_review": valid,
        },
        "notes": [
            "This artifact is offline-only and review-only.",
            "Regression candidates are suggestions; promotion still requires manual review and explicit test edits.",
            "Redacted text is used in report fields by default to keep tester data safe.",
        ],
    }


def _load_rows(db_path: Path, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM confirmed_edit_failures
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()
    except sqlite3.Error as exc:
        return [], [{"reason": "sqlite_read_failed", "message": str(exc)}]
    return [_deserialize_row(row) for row in rows], []


def _deserialize_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["route_before"] = _loads_json_object(item.pop("route_before_json", ""))
    item["intent_frame_before"] = _loads_json_object(item.pop("intent_frame_before_json", ""))
    item["quality_gate_attribution_before"] = _loads_json_object(
        item.pop("quality_gate_attribution_before_json", "")
    )
    item["should_add_regression"] = bool(item.get("should_add_regression"))
    return item


def _loads_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    failure_types: set[str] | None,
    source_kinds: set[str] | None,
    regression_only: bool,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        if failure_types and str(row.get("inferred_failure_type") or "") not in failure_types:
            continue
        if source_kinds and str(row.get("source_kind") or "") not in source_kinds:
            continue
        if regression_only and not row.get("should_add_regression"):
            continue
        result.append(row)
    return result


def _report_item(row: dict[str, Any], *, max_text_chars: int) -> tuple[dict[str, Any], int]:
    text_fields = {}
    redactions = 0
    for field in ("before_text", "after_text", "raw_asr_text", "cleaned_text", "final_text_before"):
        redacted, changed = _redact_and_bound(str(row.get(field) or ""), max_text_chars)
        redactions += changed
        text_fields[f"{field}_redacted"] = redacted
    failure_type = str(row.get("inferred_failure_type") or "unknown")
    item = {
        "id": row.get("id"),
        "created_at": row.get("created_at") or "",
        "record_id": row.get("record_id"),
        "confirmed_edit_id": row.get("confirmed_edit_id"),
        "source_kind": row.get("source_kind") or "",
        "inferred_failure_type": failure_type,
        "severity": _severity(failure_type),
        "should_add_regression": bool(row.get("should_add_regression")),
        **text_fields,
        "route_before": row.get("route_before") or {},
        "intent_frame_before": row.get("intent_frame_before") or {},
        "quality_gate_attribution_before": row.get("quality_gate_attribution_before") or {},
        "suggested_review_action": _review_action(failure_type),
    }
    return item, redactions


def _is_regression_candidate(row: dict[str, Any]) -> bool:
    failure_type = str(row.get("inferred_failure_type") or "unknown")
    return bool(row.get("should_add_regression")) and failure_type in PROMOTABLE_FAILURE_TYPES


def _regression_candidate(
    item: dict[str, Any],
    *,
    max_text_chars: int,
) -> tuple[dict[str, Any], int]:
    failure_type = str(item.get("inferred_failure_type") or "unknown")
    expected_task_type = _expected_task_type(item)
    expected_domain = _expected_domain(item)
    source_input = _candidate_input(item)
    input_text, redactions = _redact_and_bound(source_input, max_text_chars)
    sample_id = f"confirmed_edit_failure_{item.get('id')}_sample"
    route_sample = {
        "id": sample_id,
        "spoken_type": _spoken_type(failure_type),
        "input": input_text,
        "expected_task_type": expected_task_type,
        "expected_domain": expected_domain,
        "output_shape": _output_shape(failure_type),
        "must_keep": _must_keep(item),
        "must_drop": _must_drop(failure_type),
        "boundary_tags": [failure_type, "confirmed_edit_failure"],
    }
    return {
        "candidate_id": f"confirmed_edit_failure_{item.get('id')}",
        "review_status": "review_only",
        "candidate_kind": "confirmed_edit_failure_regression_seed",
        "hot_path_allowed": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "source": {
            "kind": "confirmed_edit_failure",
            "failure_id": item.get("id"),
            "record_id": item.get("record_id"),
            "confirmed_edit_id": item.get("confirmed_edit_id"),
        },
        "failure": {
            "failure_type": failure_type,
            "severity": item.get("severity") or _severity(failure_type),
            "source_kind": item.get("source_kind") or "",
        },
        "expected_task_type": expected_task_type,
        "expected_domain": expected_domain,
        "raw_asr_text_redacted": item.get("raw_asr_text_redacted") or "",
        "before_text_redacted": item.get("before_text_redacted") or "",
        "after_text_redacted": item.get("after_text_redacted") or "",
        "suggested_route_sample": route_sample,
        "suggested_regression_case": {
            "id": sample_id,
            "failure_type": failure_type,
            "source_kind": item.get("source_kind") or "",
            "input": input_text,
            "expected_task_type": expected_task_type,
            "expected_domain": expected_domain,
            "expected_output_contains": _must_keep(item),
            "must_not_contain": _must_drop(failure_type),
            "recommended_test_layers": _recommended_layers(failure_type),
        },
        "review_notes": [
            "Review-only seed generated from a confirmed manual edit.",
            "Do not promote automatically; inspect redaction and expected behavior first.",
        ],
    }, redactions


def _expected_task_type(item: dict[str, Any]) -> str:
    failure_type = str(item.get("inferred_failure_type") or "")
    route = item.get("route_before") if isinstance(item.get("route_before"), dict) else {}
    frame = item.get("intent_frame_before") if isinstance(item.get("intent_frame_before"), dict) else {}
    intent_task = str(frame.get("task_hint") or "")
    route_task = str(route.get("task_type") or "")
    if failure_type in {"intent_misroute", "router_misroute"} and intent_task:
        return intent_task
    return route_task or intent_task or "generic_task"


def _expected_domain(item: dict[str, Any]) -> str:
    route = item.get("route_before") if isinstance(item.get("route_before"), dict) else {}
    return str(route.get("domain") or "general")


def _candidate_input(item: dict[str, Any]) -> str:
    for field in ("raw_asr_text_redacted", "cleaned_text_redacted", "before_text_redacted", "after_text_redacted"):
        text = str(item.get(field) or "").strip()
        if text:
            return text
    return ""


def _spoken_type(failure_type: str) -> str:
    labels = {
        "asr_term_error": "confirmed edit ASR term correction",
        "spoken_noise_cleanup": "confirmed edit spoken-noise cleanup",
        "intent_misroute": "confirmed edit intent correction",
        "router_misroute": "confirmed edit router correction",
        "compiler_template_leak": "confirmed edit compiler template leak",
        "over_expansion": "confirmed edit over-expansion",
        "under_compilation": "confirmed edit under-compilation",
        "paste_feedback_missed": "confirmed edit paste feedback miss",
    }
    return labels.get(failure_type, "confirmed edit failure")


def _output_shape(failure_type: str) -> list[str]:
    if failure_type == "compiler_template_leak":
        return ["final output contains only user-facing prompt text", "no internal routing/template fields"]
    if failure_type == "paste_feedback_missed":
        return ["software feedback is preserved", "auto-paste/window-position context is explicit"]
    if failure_type in {"intent_misroute", "router_misroute"}:
        return ["expected task type is selected", "source intent is preserved"]
    if failure_type == "asr_term_error":
        return ["recognized term is normalized", "compiled task keeps corrected tool/model name"]
    return ["manual correction intent is preserved", "compiled output is not a near echo"]


def _must_keep(item: dict[str, Any]) -> list[str]:
    failure_type = str(item.get("inferred_failure_type") or "")
    after = str(item.get("after_text_redacted") or "")
    if failure_type == "asr_term_error" and re.search(r"image\s*2\.0", after, re.IGNORECASE):
        return ["image 2.0"]
    if failure_type == "paste_feedback_missed":
        keep = []
        for term in ("自动粘贴", "粘贴", "目标界面", "当前界面", "任务栏", "窗口位置"):
            if term in after:
                keep.append(term)
        return keep or ["自动粘贴", "目标界面"]
    if failure_type == "compiler_template_leak":
        return ["user-facing final prompt"]
    if after:
        return [_bound_text(after, 80)]
    return []


def _must_drop(failure_type: str) -> list[str]:
    if failure_type == "compiler_template_leak":
        return INTERNAL_TEMPLATE_TERMS
    if failure_type == "over_expansion":
        return ["unrequested project plan", "unrequested task expansion"]
    return []


def _recommended_layers(failure_type: str) -> list[str]:
    mapping = {
        "asr_term_error": ["edit_memory", "normalizer", "processor"],
        "spoken_noise_cleanup": ["text_preprocessors", "processor"],
        "intent_misroute": ["intent_frame", "task_router"],
        "router_misroute": ["intent_frame", "task_router"],
        "compiler_template_leak": ["task_compiler", "processor_quality_gate"],
        "over_expansion": ["task_router", "processor_quality_gate"],
        "under_compilation": ["task_compiler", "processor_quality_gate"],
        "paste_feedback_missed": ["intent_frame", "task_router", "task_compiler", "processor_quality_gate"],
    }
    return mapping.get(failure_type, ["manual_review"])


def _review_action(failure_type: str) -> str:
    if failure_type in PROMOTABLE_FAILURE_TYPES:
        return "review_for_regression_candidate"
    if failure_type == "punctuation_or_wording":
        return "keep_as_low_priority_edit_memory_signal"
    return "inspect_manually_before_promotion"


def _severity(failure_type: str) -> str:
    return FAILURE_SEVERITY.get(failure_type, "medium")


def _redact_and_bound(text: str, max_text_chars: int) -> tuple[str, int]:
    result = str(text or "")
    count = 0
    for pattern, replacement in SENSITIVE_PATTERNS:
        result, changed = pattern.subn(replacement, result)
        count += changed
    return _bound_text(result, max_text_chars), count


def _bound_text(text: str, max_text_chars: int) -> str:
    limit = max(20, int(max_text_chars))
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report confirmed-edit failure notebook")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite sessions.db path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--limit", type=int, default=200, help="maximum rows to read")
    parser.add_argument("--failure-type", action="append", default=[], help="filter by inferred_failure_type; can repeat")
    parser.add_argument("--source-kind", action="append", default=[], help="filter by source_kind; can repeat")
    parser.add_argument("--regression-only", action="store_true", help="include only should_add_regression rows")
    parser.add_argument("--max-text-chars", type=int, default=500, help="maximum redacted text length per field")
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    parser.add_argument("--fail-on-missing-db", action="store_true", help="return 1 when the database is missing")
    parser.add_argument("--fail-on-empty", action="store_true", help="return 1 when no rows match filters")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        report = build_report(
            Path(args.db),
            limit=args.limit,
            failure_types=set(args.failure_type) if args.failure_type else None,
            source_kinds=set(args.source_kind) if args.source_kind else None,
            regression_only=bool(args.regression_only),
            max_text_chars=args.max_text_chars,
        )
    except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
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
            "Confirmed-edit failures: "
            f"loaded={report['total_loaded_count']}, "
            f"filtered={report['filtered_count']}, "
            f"regression_candidates={report['regression_candidate_count']}, "
            f"db_exists={report['db_exists']}"
        )

    if args.fail_on_missing_db and not report["db_exists"]:
        return 1
    if args.fail_on_empty and report["filtered_count"] <= 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
