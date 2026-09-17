#!/usr/bin/env python3
"""Report review status for offline route-sample candidate queues.

This script is intentionally governance-only. It reads candidate JSON files and
the reviewed route sample library, then reports which candidates have been
accepted, rejected, deferred, or still need review. It never imports runtime
router code and never promotes candidates automatically.
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

from scripts.governance_artifacts import utc_now_iso

DEFAULT_CANDIDATE_SOURCES = (
    ROOT / "output" / "github_route_sample_candidates.json",
    ROOT / "output" / "obsidian_route_sample_candidates.json",
    ROOT / "output" / "failed_utterance_route_sample_candidates.json",
)
DEFAULT_REVIEWED_SAMPLES = ROOT / "tests" / "route_samples.json"
DEFAULT_DECISIONS = ROOT / "data" / "route_sample_candidate_review_decisions.json"
DEFAULT_OUTPUT = ROOT / "output" / "route_sample_candidate_review_status.json"
SCRIPT_NAME = "scripts/report_candidate_review_status.py"
ARTIFACT_VERSION = 1

ACCEPTED_STATUSES = {"accepted", "accepted_to_tests"}
RESOLVED_STATUSES = ACCEPTED_STATUSES | {"rejected", "deferred"}
PENDING_STATUSES = {"", "review_only", "unreviewed", "needs_review", "pending"}


def build_report(
    candidate_sources: list[Path],
    reviewed_samples_path: Path,
    *,
    decisions_path: Path | None = None,
) -> dict[str, Any]:
    reviewed_samples_path = reviewed_samples_path.expanduser().resolve()
    reviewed_samples = _load_reviewed_samples(reviewed_samples_path)
    reviewed_by_id, reviewed_by_input = _index_reviewed_samples(reviewed_samples)
    decisions = _load_decisions(decisions_path) if decisions_path else {}

    review_items: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    invalid_items: list[dict[str, Any]] = []
    duplicate_items: list[dict[str, Any]] = []
    source_reports: list[dict[str, Any]] = []
    seen_candidate_ids: dict[str, str] = {}

    for source_path in candidate_sources:
        source_path = source_path.expanduser().resolve()
        source_report, candidates = _load_candidate_source(source_path)
        source_reports.append(source_report)
        if source_report.get("missing") or source_report.get("invalid"):
            invalid_items.append(
                {
                    "candidate_id": None,
                    "source_file": str(source_path),
                    "reason": "candidate_source_unavailable",
                }
            )
            continue

        if source_report.get("runtime_hot_path_used") is True:
            invalid_items.append(
                {
                    "candidate_id": None,
                    "source_file": str(source_path),
                    "reason": "source_runtime_hot_path_used",
                }
            )
        if source_report.get("network_used") is True:
            invalid_items.append(
                {
                    "candidate_id": None,
                    "source_file": str(source_path),
                    "reason": "source_network_used",
                }
            )
        if source_report.get("repo_clone_or_download_used") is True:
            invalid_items.append(
                {
                    "candidate_id": None,
                    "source_file": str(source_path),
                    "reason": "source_repo_clone_or_download_used",
                }
            )

        for index, candidate in enumerate(candidates, start=1):
            item = _review_candidate(
                candidate,
                source_file=source_path,
                index=index,
                reviewed_by_id=reviewed_by_id,
                reviewed_by_input=reviewed_by_input,
                decisions=decisions,
            )
            candidate_id = str(item["candidate_id"])
            if candidate_id in seen_candidate_ids:
                duplicate_items.append(
                    {
                        "candidate_id": candidate_id,
                        "source_file": str(source_path),
                        "first_source_file": seen_candidate_ids[candidate_id],
                        "reason": "duplicate_candidate_id",
                    }
                )
            else:
                seen_candidate_ids[candidate_id] = str(source_path)

            review_items.append(item)
            matches.extend(item.get("matches") or [])
            invalid_items.extend(item.get("invalid_items") or [])

    by_status = Counter(str(item["status"]) for item in review_items)
    pending_count = sum(by_status.get(status, 0) for status in PENDING_STATUSES)
    runtime_violations = [
        item
        for item in invalid_items
        if str(item.get("reason") or "").endswith("_used")
        or item.get("reason") in {"candidate_hot_path_allowed"}
    ]
    valid = not invalid_items and not duplicate_items
    runtime_isolated = not runtime_violations

    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "candidate_sources": [str(path.expanduser().resolve()) for path in candidate_sources],
        "candidate_source_reports": source_reports,
        "reviewed_samples_path": str(reviewed_samples_path),
        "reviewed_sample_count": len(reviewed_samples),
        "decisions_path": str(decisions_path.expanduser().resolve()) if decisions_path else "",
        "decision_count": len(decisions),
        "candidate_count": len(review_items),
        "by_status": {
            "accepted": by_status.get("accepted", 0),
            "rejected": by_status.get("rejected", 0),
            "deferred": by_status.get("deferred", 0),
            "unreviewed": by_status.get("unreviewed", 0),
            "review_only": by_status.get("review_only", 0),
            "needs_review": by_status.get("needs_review", 0),
            "pending": by_status.get("pending", 0),
        },
        "pending_count": pending_count,
        "matches": matches,
        "review_items": [
            {key: value for key, value in item.items() if key not in {"matches", "invalid_items"}}
            for item in review_items
        ],
        "invalid_items": invalid_items,
        "duplicate_items": duplicate_items,
        "status": {
            "valid": valid,
            "runtime_isolated": runtime_isolated,
            "has_pending": pending_count > 0,
            "all_candidates_resolved": pending_count == 0,
            "ready_for_strict_release": valid and runtime_isolated and pending_count == 0,
        },
    }


def _load_reviewed_samples(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("reviewed route samples must be a JSON list")
    return [item for item in data if isinstance(item, dict)]


def _index_reviewed_samples(
    samples: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_input: dict[str, dict[str, Any]] = {}
    for item in samples:
        item_id = str(item.get("id") or "").strip()
        item_input = _normalize_text(str(item.get("input") or ""))
        if item_id and item_id not in by_id:
            by_id[item_id] = item
        if item_input and item_input not in by_input:
            by_input[item_input] = item
    return by_id, by_input


def _load_decisions(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    path = path.expanduser()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("decisions"), list):
        records = data["decisions"]
    elif isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = [
            {"candidate_id": candidate_id, **(_as_dict(value))}
            for candidate_id, value in data.items()
        ]
    else:
        raise ValueError("candidate review decisions must be a JSON list or object")

    decisions: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        candidate_id = str(record.get("candidate_id") or "").strip()
        if candidate_id:
            decisions[candidate_id] = dict(record)
    return decisions


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {"review_status": str(value)}


def _load_candidate_source(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report: dict[str, Any] = {
        "source_file": str(path),
        "exists": path.exists(),
        "candidate_count": 0,
    }
    if not path.exists():
        report["missing"] = True
        return report, []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report["invalid"] = True
        report["error"] = str(exc)
        return report, []

    if isinstance(data, dict):
        candidates = data.get("candidates") or []
        report.update(
            {
                "schema_version": data.get("schema_version"),
                "generated_at": data.get("generated_at"),
                "network_used": data.get("network_used"),
                "repo_clone_or_download_used": data.get("repo_clone_or_download_used"),
                "runtime_hot_path_used": data.get("runtime_hot_path_used"),
            }
        )
    elif isinstance(data, list):
        candidates = data
    else:
        report["invalid"] = True
        report["error"] = "candidate source must be a JSON object or list"
        return report, []

    if not isinstance(candidates, list):
        report["invalid"] = True
        report["error"] = "candidate source candidates must be a list"
        return report, []

    result = [candidate for candidate in candidates if isinstance(candidate, dict)]
    report["candidate_count"] = len(result)
    if len(result) != len(candidates):
        report["invalid"] = True
        report["error"] = "candidate list contains non-object entries"
    return report, result


def _review_candidate(
    candidate: dict[str, Any],
    *,
    source_file: Path,
    index: int,
    reviewed_by_id: dict[str, dict[str, Any]],
    reviewed_by_input: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    suggested = candidate.get("suggested_route_sample")
    suggested_sample = suggested if isinstance(suggested, dict) else {}
    candidate_id = str(
        candidate.get("candidate_id")
        or suggested_sample.get("id")
        or f"{source_file.stem}_{index:03d}"
    ).strip()
    expected_task = str(
        candidate.get("expected_task_type") or suggested_sample.get("expected_task_type") or ""
    )
    expected_domain = str(
        candidate.get("expected_domain") or suggested_sample.get("expected_domain") or ""
    )
    current_task = str(candidate.get("current_task_type") or "")
    current_domain = str(candidate.get("current_domain") or "")
    suggested_sample_id = str(suggested_sample.get("id") or "").strip()
    suggested_input = str(candidate.get("input") or suggested_sample.get("input") or "").strip()

    decision = decisions.get(candidate_id, {})
    raw_status = str(
        decision.get("review_status")
        or decision.get("decision")
        or candidate.get("review_status")
        or ""
    ).strip()
    normalized_status = _normalize_status(raw_status)

    matched_sample = None
    match_reason = ""
    if suggested_sample_id and suggested_sample_id in reviewed_by_id:
        matched_sample = reviewed_by_id[suggested_sample_id]
        match_reason = "suggested_sample_id_match"
    elif _normalize_text(suggested_input) in reviewed_by_input:
        matched_sample = reviewed_by_input[_normalize_text(suggested_input)]
        match_reason = "input_match"
    if normalized_status in {"rejected", "deferred"}:
        matched_sample = None
        match_reason = ""

    invalid_items: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []

    if candidate.get("hot_path_allowed") is True:
        invalid_items.append(_invalid(candidate_id, source_file, "candidate_hot_path_allowed"))
    if candidate.get("network_used") is True:
        invalid_items.append(_invalid(candidate_id, source_file, "candidate_network_used"))
    if candidate.get("repo_clone_or_download_used") is True:
        invalid_items.append(
            _invalid(candidate_id, source_file, "candidate_repo_clone_or_download_used")
        )

    status = normalized_status if normalized_status else "unreviewed"
    reason = "explicit_review_status" if normalized_status in RESOLVED_STATUSES else "not_reviewed"

    if matched_sample:
        sample_task = str(matched_sample.get("expected_task_type") or "")
        sample_domain = str(matched_sample.get("expected_domain") or "")
        sample_id = str(matched_sample.get("id") or "")
        if sample_task == expected_task and sample_domain == expected_domain:
            status = "accepted"
            reason = match_reason
            matches.append(
                {
                    "candidate_id": candidate_id,
                    "source_file": str(source_file),
                    "suggested_sample_id": suggested_sample_id,
                    "matched_sample_id": sample_id,
                    "status": "accepted",
                    "match_reason": match_reason,
                    "candidate_task_type": expected_task,
                    "candidate_domain": expected_domain,
                    "sample_task_type": sample_task,
                    "sample_domain": sample_domain,
                    "hot_path_allowed": bool(candidate.get("hot_path_allowed", False)),
                }
            )
        else:
            status = "deferred"
            reason = "matched_sample_task_domain_mismatch"
            invalid_items.append(
                {
                    "candidate_id": candidate_id,
                    "source_file": str(source_file),
                    "reason": "matched_sample_task_domain_mismatch",
                    "matched_sample_id": sample_id,
                    "candidate_task_type": expected_task,
                    "candidate_domain": expected_domain,
                    "sample_task_type": sample_task,
                    "sample_domain": sample_domain,
                }
            )
    elif normalized_status in ACCEPTED_STATUSES:
        status = "accepted"
        reason = "explicit_accepted_status"
        if not _has_manual_acceptance_evidence(candidate, decision):
            invalid_items.append(
                _invalid(candidate_id, source_file, "accepted_without_manual_evidence")
            )
    elif normalized_status == "rejected":
        status = "rejected"
        reason = "explicit_rejected_status"
    elif normalized_status == "deferred":
        status = "deferred"
        reason = "explicit_deferred_status"
    elif _has_router_mismatch(expected_task, expected_domain, current_task, current_domain):
        status = "deferred"
        reason = "router_mismatch_needs_review"
    elif normalized_status in PENDING_STATUSES:
        status = "unreviewed"
        reason = "not_found_in_reviewed_samples"

    return {
        "candidate_id": candidate_id,
        "source_file": str(source_file),
        "suggested_sample_id": suggested_sample_id,
        "status": status,
        "source_review_status": raw_status or "unreviewed",
        "reason": reason,
        "expected_task_type": expected_task,
        "expected_domain": expected_domain,
        "current_task_type": current_task,
        "current_domain": current_domain,
        "hot_path_allowed": bool(candidate.get("hot_path_allowed", False)),
        "network_used": bool(candidate.get("network_used", False)),
        "repo_clone_or_download_used": bool(candidate.get("repo_clone_or_download_used", False)),
        "risk_notes": list(candidate.get("risk_notes") or []),
        "matches": matches,
        "invalid_items": invalid_items,
    }


def _normalize_status(status: str) -> str:
    normalized = status.strip().lower().replace("-", "_")
    if normalized == "accepted_to_tests":
        return "accepted"
    if normalized in {"accept", "accepted"}:
        return "accepted"
    if normalized in {"reject", "rejected"}:
        return "rejected"
    if normalized in {"defer", "deferred"}:
        return "deferred"
    if normalized in PENDING_STATUSES:
        return normalized
    return normalized


def _has_manual_acceptance_evidence(
    candidate: dict[str, Any],
    decision: dict[str, Any],
) -> bool:
    for values in (candidate, decision):
        if str(values.get("accepted_sample_id") or "").strip():
            return True
        if str(values.get("review_notes") or "").strip():
            return True
        if str(values.get("reviewer") or "").strip():
            return True
    return False


def _has_router_mismatch(
    expected_task: str,
    expected_domain: str,
    current_task: str,
    current_domain: str,
) -> bool:
    return bool(
        (current_task and expected_task and current_task != expected_task)
        or (current_domain and expected_domain and current_domain != expected_domain)
    )


def _invalid(candidate_id: str, source_file: Path, reason: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "source_file": str(source_file),
        "reason": reason,
    }


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report offline candidate review status")
    parser.add_argument(
        "--candidates",
        action="append",
        default=[],
        help="candidate JSON path; can be passed multiple times",
    )
    parser.add_argument(
        "--reviewed-samples",
        default=str(DEFAULT_REVIEWED_SAMPLES),
        help="reviewed tests/route_samples.json path",
    )
    parser.add_argument(
        "--decisions",
        default=str(DEFAULT_DECISIONS),
        help="optional manual decision JSON path",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help="return 1 when candidate queues violate governance constraints",
    )
    parser.add_argument(
        "--fail-on-pending",
        action="store_true",
        help="return 1 when any candidate is still unreviewed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    candidate_sources = [Path(item) for item in args.candidates] or list(DEFAULT_CANDIDATE_SOURCES)
    decisions_path = Path(args.decisions).expanduser()
    decisions = decisions_path if decisions_path.exists() else None

    try:
        report = build_report(
            candidate_sources,
            Path(args.reviewed_samples),
            decisions_path=decisions,
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
            "Candidate review status: "
            f"{report['candidate_count']} candidates, "
            f"pending={report['pending_count']}, "
            f"invalid={len(report['invalid_items'])}, "
            f"runtime_isolated={report['status']['runtime_isolated']}"
        )

    invalid_failed = args.fail_on_invalid and (
        not report["status"]["valid"] or not report["status"]["runtime_isolated"]
    )
    pending_failed = args.fail_on_pending and report["pending_count"] > 0
    if invalid_failed or pending_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
