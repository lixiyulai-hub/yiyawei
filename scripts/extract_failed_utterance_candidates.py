#!/usr/bin/env python3
"""Build review-only route-sample candidates from failed utterance cases.

The cases file is a curated offline ledger of real or representative failures.
This script converts that ledger into the same candidate shape used by the
existing review/intake/promotion pipeline. It does not promote samples, does not
read runtime logs by default, and must stay out of app.py/src hot paths.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso
from src.auditor.task_router import detect_task_route


DEFAULT_CASES = ROOT / "data" / "failed_utterance_cases.json"
DEFAULT_OUTPUT = ROOT / "output" / "failed_utterance_route_sample_candidates.json"
SCRIPT_NAME = "scripts/extract_failed_utterance_candidates.py"
ARTIFACT_VERSION = 1

SAFE_REDACTION_STATUSES = {
    "no_sensitive_data",
    "redacted",
    "synthetic",
    "public",
}
UNREDACTED_REDACTION_STATUSES = {
    "",
    "raw",
    "unredacted",
    "needs_redaction",
    "unknown",
}

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
    cases_path: Path,
    *,
    limit: int | None = None,
    case_ids: set[str] | None = None,
    max_text_chars: int = 500,
) -> dict[str, Any]:
    cases_path = cases_path.expanduser().resolve()
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("failed utterance cases must be a JSON object")
    raw_cases = data.get("cases")
    if raw_cases is None:
        raw_cases = data.get("samples")
    if not isinstance(raw_cases, list):
        raise ValueError("failed utterance cases must contain a cases list")

    candidates: list[dict[str, Any]] = []
    invalid_items: list[dict[str, Any]] = []
    duplicate_items: list[dict[str, Any]] = []
    unredacted_sensitive_items: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    redacted_count = 0

    max_count = len(raw_cases) if limit is None else max(0, limit)
    for index, item in enumerate(raw_cases, start=1):
        if len(candidates) >= max_count:
            break
        if not isinstance(item, dict):
            invalid_items.append({"case_id": "", "index": index, "reason": "case_not_object"})
            continue
        case_id = str(item.get("id") or item.get("case_id") or "").strip()
        if case_ids and case_id not in case_ids:
            continue
        candidate_id = _candidate_id(case_id)
        if not case_id:
            invalid_items.append({"case_id": "", "index": index, "reason": "missing_case_id"})
            continue
        if candidate_id in seen_ids:
            duplicate_items.append(
                {
                    "candidate_id": candidate_id,
                    "case_id": case_id,
                    "index": index,
                    "first_index": seen_ids[candidate_id],
                    "reason": "duplicate_candidate_id",
                }
            )
            continue
        seen_ids[candidate_id] = index

        item_invalid = _validate_case(item, candidate_id=candidate_id, index=index)
        invalid_items.extend(item_invalid)
        if item_invalid:
            continue

        if _is_unredacted_sensitive(item):
            unredacted_sensitive_items.append(
                {
                    "candidate_id": candidate_id,
                    "case_id": case_id,
                    "index": index,
                    "reason": "sensitive_case_not_redacted",
                    "redaction_status": item.get("redaction_status") or "",
                }
            )

        candidate, changed = _build_candidate(
            item,
            candidate_id=candidate_id,
            cases_path=cases_path,
            max_text_chars=max_text_chars,
        )
        redacted_count += changed
        candidates.append(candidate)

    by_failure_mode = Counter(
        mode
        for candidate in candidates
        for mode in candidate.get("failure", {}).get("failure_modes", [])
    )
    by_review_status = Counter(str(candidate.get("case_review_status") or "") for candidate in candidates)
    by_severity = Counter(str(candidate.get("failure", {}).get("severity") or "") for candidate in candidates)
    runtime_violations = [
        item
        for item in invalid_items
        if str(item.get("reason") or "").endswith("_used")
        or item.get("reason") == "case_hot_path_allowed"
    ]
    valid = not invalid_items and not duplicate_items and not unredacted_sensitive_items
    runtime_isolated = not runtime_violations

    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "mode": "offline_failed_utterance_cases",
        "review_required": True,
        "cases_path": str(cases_path),
        "cases_sha256": sha256_file(cases_path),
        "case_count": len(raw_cases),
        "candidate_count": len(candidates),
        "by_failure_mode": dict(sorted(by_failure_mode.items())),
        "by_review_status": dict(sorted(by_review_status.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "redaction": {
            "enabled": True,
            "max_text_chars": max_text_chars,
            "redacted_count": redacted_count,
            "unredacted_sensitive_count": len(unredacted_sensitive_items),
        },
        "candidates": candidates,
        "invalid_items": invalid_items,
        "duplicate_items": duplicate_items,
        "unredacted_sensitive_items": unredacted_sensitive_items,
        "status": {
            "valid": valid,
            "runtime_isolated": runtime_isolated,
            "ready_for_review": valid and runtime_isolated,
        },
        "notes": [
            "This artifact is a review-only candidate source for failed utterances.",
            "It must not be read by app.py or src/**/*.py runtime paths.",
            "Promotion still requires manual decisions and reviewed route samples.",
        ],
    }


def _validate_case(
    item: dict[str, Any],
    *,
    candidate_id: str,
    index: int,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    required = ("raw_asr_text", "expected_task_type", "expected_domain")
    for field in required:
        if not str(item.get(field) or "").strip():
            failures.append(_invalid(candidate_id, index, f"missing_{field}"))
    if item.get("hot_path_allowed") is True:
        failures.append(_invalid(candidate_id, index, "case_hot_path_allowed"))
    if item.get("network_used") is True:
        failures.append(_invalid(candidate_id, index, "case_network_used"))
    if item.get("repo_clone_or_download_used") is True:
        failures.append(_invalid(candidate_id, index, "case_repo_clone_or_download_used"))
    suggested = item.get("suggested_route_sample")
    if suggested is not None and not isinstance(suggested, dict):
        failures.append(_invalid(candidate_id, index, "suggested_route_sample_not_object"))
    return failures


def _build_candidate(
    item: dict[str, Any],
    *,
    candidate_id: str,
    cases_path: Path,
    max_text_chars: int,
) -> tuple[dict[str, Any], int]:
    raw_text, raw_redactions = _redact_and_bound(str(item.get("raw_asr_text") or ""), max_text_chars)
    wrong_text, wrong_redactions = _redact_and_bound(str(item.get("wrong_final_text") or ""), max_text_chars)
    suggested = item.get("suggested_route_sample") if isinstance(item.get("suggested_route_sample"), dict) else {}
    suggested_sample, sample_redactions = _suggested_sample(
        item,
        suggested,
        candidate_id=candidate_id,
        input_text=raw_text,
        max_text_chars=max_text_chars,
    )
    route = detect_task_route(raw_text)
    current_task = str(item.get("observed_task_type") or route.task_type)
    current_domain = str(item.get("observed_domain") or route.domain)
    failure_modes = _string_list(item.get("failure_modes"))
    safety_flags = _string_list(item.get("safety_flags"))

    candidate = {
        "candidate_id": candidate_id,
        "review_status": "review_only",
        "case_review_status": str(item.get("review_status") or "unreviewed"),
        "hot_path_allowed": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "candidate_kind": "failed_utterance_route_sample_seed",
        "derived_from": "failed_utterance_cases_only",
        "source": {
            "kind": str(item.get("source") or "manual"),
            "cases_path": str(cases_path),
            "case_id": str(item.get("id") or item.get("case_id") or ""),
        },
        "failure": {
            "failure_modes": failure_modes,
            "severity": str(item.get("severity") or "medium"),
            "wrong_final_text_redacted": wrong_text,
            "redaction_status": str(item.get("redaction_status") or ""),
            "contains_sensitive_data": bool(item.get("contains_sensitive_data", False)),
        },
        "expected_task_type": str(item.get("expected_task_type") or ""),
        "expected_domain": str(item.get("expected_domain") or ""),
        "current_task_type": current_task,
        "current_domain": current_domain,
        "raw_asr_text_redacted": raw_text,
        "suggested_route_sample": suggested_sample,
        "risk_notes": _risk_notes(item, failure_modes, safety_flags),
    }
    return candidate, raw_redactions + wrong_redactions + sample_redactions


def _suggested_sample(
    item: dict[str, Any],
    suggested: dict[str, Any],
    *,
    candidate_id: str,
    input_text: str,
    max_text_chars: int,
) -> tuple[dict[str, Any], int]:
    redactions = 0
    sample_id = str(suggested.get("id") or f"{candidate_id}_sample").strip()
    sample_input, changed = _redact_and_bound(str(suggested.get("input") or input_text), max_text_chars)
    redactions += changed
    result: dict[str, Any] = {
        "id": sample_id,
        "spoken_type": suggested.get("spoken_type") or item.get("spoken_type") or "失败语料候选",
        "input": sample_input,
        "expected_task_type": item.get("expected_task_type") or suggested.get("expected_task_type") or "",
        "expected_domain": item.get("expected_domain") or suggested.get("expected_domain") or "",
        "output_shape": _string_list(suggested.get("output_shape") or item.get("expected_output_shape")),
        "must_keep": [],
        "must_drop": [],
    }
    for field in ("must_keep", "must_drop", "required_domain_terms", "boundary_tags"):
        values, changed = _redact_string_list(suggested.get(field), max_text_chars)
        redactions += changed
        if values:
            result[field] = values
    if suggested.get("risk"):
        result["risk"] = suggested.get("risk")
    if suggested.get("boundary_domain"):
        result["boundary_domain"] = suggested.get("boundary_domain")
    return result, redactions


def _risk_notes(
    item: dict[str, Any],
    failure_modes: list[str],
    safety_flags: list[str],
) -> list[str]:
    notes = [
        "Generated from offline failed-utterance cases only; must be manually reviewed before promotion.",
    ]
    review_notes = str(item.get("review_notes") or "").strip()
    if review_notes:
        notes.append(review_notes)
    if failure_modes:
        notes.append("Failure modes: " + ", ".join(failure_modes))
    if safety_flags:
        notes.append("Safety flags: " + ", ".join(safety_flags))
    if item.get("contains_sensitive_data") is True:
        notes.append("Sensitive case: keep redacted/synthetic before exporting to tests, docs, or candidate packages.")
    return notes


def _redact_string_list(value: Any, max_text_chars: int) -> tuple[list[str], int]:
    values = _string_list(value)
    result: list[str] = []
    count = 0
    for item in values:
        redacted, changed = _redact_and_bound(item, max_text_chars)
        count += changed
        result.append(redacted)
    return result, count


def _redact_and_bound(text: str, max_text_chars: int) -> tuple[str, int]:
    result = str(text or "")
    count = 0
    for pattern, replacement in SENSITIVE_PATTERNS:
        result, changed = pattern.subn(replacement, result)
        count += changed
    result = _bound_text(result, max_text_chars)
    return result, count


def _bound_text(text: str, max_text_chars: int) -> str:
    limit = max(20, int(max_text_chars))
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _is_unredacted_sensitive(item: dict[str, Any]) -> bool:
    status = str(item.get("redaction_status") or "").strip().lower()
    if item.get("contains_sensitive_data") is True and status in UNREDACTED_REDACTION_STATUSES:
        return True
    return False


def _candidate_id(case_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-\u3400-\u9fff]+", "_", case_id or "").strip("_")
    if not slug:
        return ""
    if slug.startswith("failed_"):
        return slug[:120]
    return f"failed_utterance_{slug}"[:120]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _invalid(candidate_id: str, index: int, reason: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "index": index,
        "reason": reason,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract failed-utterance route-sample candidates")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="failed utterance cases JSON path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="candidate artifact output path")
    parser.add_argument("--limit", type=int, default=None, help="maximum cases to emit")
    parser.add_argument("--case-id", action="append", default=[], help="emit only a specific case id; can repeat")
    parser.add_argument("--max-text-chars", type=int, default=500, help="maximum redacted text length per field")
    parser.add_argument("--print-json", action="store_true", help="print JSON artifact")
    parser.add_argument("--fail-on-invalid", action="store_true", help="return 1 when cases violate schema or isolation")
    parser.add_argument(
        "--fail-on-unredacted-sensitive",
        action="store_true",
        help="return 1 when a sensitive case is not marked redacted/synthetic",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        report = build_report(
            Path(args.cases),
            limit=args.limit,
            case_ids=set(args.case_id) if args.case_id else None,
            max_text_chars=args.max_text_chars,
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
            "Failed-utterance candidates: "
            f"{report['candidate_count']} candidates from {report['case_count']} cases, "
            f"invalid={len(report['invalid_items'])}, "
            f"unredacted_sensitive={report['redaction']['unredacted_sensitive_count']}, "
            f"runtime_isolated={report['status']['runtime_isolated']}"
        )

    invalid_failed = args.fail_on_invalid and (
        not report["status"]["valid"] or not report["status"]["runtime_isolated"]
    )
    sensitive_failed = (
        args.fail_on_unredacted_sensitive
        and report["redaction"]["unredacted_sensitive_count"] > 0
    )
    if invalid_failed or sensitive_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
