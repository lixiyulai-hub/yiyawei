#!/usr/bin/env python3
"""Build a review package for offline route-sample candidate intake.

The package is a human-facing governance artifact. It does not promote samples,
does not edit decisions, and does not feed runtime code. It gives reviewers one
bounded JSON file with candidate status, suggested sample drafts, novice
template previews, and provenance hashes.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso
from scripts.report_candidate_review_status import DEFAULT_CANDIDATE_SOURCES, DEFAULT_DECISIONS, DEFAULT_REVIEWED_SAMPLES, build_report as build_status_report
from src.auditor.template_preview import build_novice_template_preview, render_novice_template_preview


DEFAULT_OUTPUT = ROOT / "output" / "route_sample_intake_package.json"
SCRIPT_NAME = "scripts/build_candidate_intake_package.py"
ARTIFACT_VERSION = 1


def build_package(
    candidate_sources: list[Path],
    reviewed_samples_path: Path,
    *,
    decisions_path: Path | None = None,
    preview_limit: int = 20,
) -> dict[str, Any]:
    candidate_sources = [path.expanduser().resolve() for path in candidate_sources]
    reviewed_samples_path = reviewed_samples_path.expanduser().resolve()
    decisions_path = decisions_path.expanduser().resolve() if decisions_path else None

    status_report = build_status_report(
        candidate_sources,
        reviewed_samples_path,
        decisions_path=decisions_path,
    )
    source_candidates = _load_source_candidates(candidate_sources)
    decisions = _load_decision_records(decisions_path)
    reviewed_ids = _reviewed_ids(reviewed_samples_path)

    review_items = status_report.get("review_items") or []
    enriched: list[dict[str, Any]] = []
    accepted_drafts: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    previews_used = 0

    for item in review_items:
        candidate_id = str(item.get("candidate_id") or "")
        candidate = source_candidates.get(candidate_id, {})
        suggested_sample = _suggested_sample(candidate, item)
        input_text = str(
            suggested_sample.get("input")
            or candidate.get("input")
            or ""
        ).strip()
        preview = None
        rendered_preview = ""
        if input_text and previews_used < max(0, preview_limit):
            preview = build_novice_template_preview(input_text)
            if preview:
                rendered_preview = render_novice_template_preview(preview)
                previews_used += 1

        status = str(item.get("status") or "unreviewed")
        row = {
            "candidate_id": candidate_id,
            "status": status,
            "reason": item.get("reason") or "",
            "expected_task_type": item.get("expected_task_type") or "",
            "expected_domain": item.get("expected_domain") or "",
            "current_task_type": item.get("current_task_type") or "",
            "current_domain": item.get("current_domain") or "",
            "source_file": item.get("source_file") or "",
            "review_notes": decisions.get(candidate_id, {}).get("review_notes", ""),
            "suggested_sample": suggested_sample,
            "already_in_reviewed_samples": str(suggested_sample.get("id") or "") in reviewed_ids,
            "novice_preview": preview.to_dict() if preview else None,
            "novice_preview_text": rendered_preview,
            "review_actions": _review_actions(status),
        }
        enriched.append(row)
        if status == "accepted":
            accepted_drafts.append(row)
        elif status == "deferred":
            deferred.append(row)
        elif status == "rejected":
            rejected.append(row)
        else:
            pending.append(row)

    by_status = Counter(str(item.get("status") or "unreviewed") for item in enriched)
    runtime_isolated = bool(status_report.get("status", {}).get("runtime_isolated"))
    valid = bool(status_report.get("status", {}).get("valid"))
    all_resolved = bool(status_report.get("status", {}).get("all_candidates_resolved"))

    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "candidate_sources": [str(path) for path in candidate_sources],
        "candidate_source_hashes": {
            str(path): sha256_file(path) for path in candidate_sources if path.exists()
        },
        "reviewed_samples_path": str(reviewed_samples_path),
        "reviewed_samples_sha256": sha256_file(reviewed_samples_path),
        "decisions_path": str(decisions_path) if decisions_path else "",
        "decisions_sha256": sha256_file(decisions_path) if decisions_path and decisions_path.exists() else "",
        "status_report_summary": {
            "candidate_count": status_report.get("candidate_count", 0),
            "reviewed_sample_count": status_report.get("reviewed_sample_count", 0),
            "decision_count": status_report.get("decision_count", 0),
            "pending_count": status_report.get("pending_count", 0),
            "invalid_count": len(status_report.get("invalid_items") or []),
            "duplicate_count": len(status_report.get("duplicate_items") or []),
        },
        "by_status": dict(sorted(by_status.items())),
        "intake": {
            "accepted_count": len(accepted_drafts),
            "rejected_count": len(rejected),
            "deferred_count": len(deferred),
            "pending_count": len(pending),
            "preview_count": previews_used,
            "accepted_sample_drafts": [_compact_row(row) for row in accepted_drafts],
            "pending_review_items": [_compact_row(row) for row in pending],
            "deferred_items": [_compact_row(row) for row in deferred],
            "rejected_items": [_compact_row(row, include_preview=False) for row in rejected],
        },
        "review_items": enriched,
        "status": {
            "valid": valid,
            "runtime_isolated": runtime_isolated,
            "all_candidates_resolved": all_resolved,
            "ready_for_intake": valid and runtime_isolated,
            "ready_for_strict_release": valid and runtime_isolated and all_resolved,
        },
        "notes": [
            "This is an offline review package. It must not be read by app.py or src/**/*.py runtime paths.",
            "Accepted sample drafts are suggestions only; promotion still requires explicit review and tests/route_samples.json edits.",
            "Novice previews are bounded summaries, not full executable prompts.",
        ],
    }


def _load_source_candidates(paths: list[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        candidates = data.get("candidates") if isinstance(data, dict) else data
        if not isinstance(candidates, list):
            continue
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            suggested = candidate.get("suggested_route_sample")
            suggested_sample = suggested if isinstance(suggested, dict) else {}
            candidate_id = str(
                candidate.get("candidate_id")
                or suggested_sample.get("id")
                or f"{path.stem}_{index:03d}"
            ).strip()
            if candidate_id:
                result[candidate_id] = candidate
    return result


def _load_decision_records(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("decisions") if isinstance(data, dict) else data
    if not isinstance(records, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        candidate_id = str(record.get("candidate_id") or "").strip()
        if candidate_id:
            result[candidate_id] = record
    return result


def _reviewed_ids(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return set()
    return {str(item.get("id") or "").strip() for item in data if isinstance(item, dict)}


def _suggested_sample(candidate: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    sample = candidate.get("suggested_route_sample")
    if isinstance(sample, dict):
        return dict(sample)
    candidate_id = str(item.get("candidate_id") or "").strip()
    input_text = str(candidate.get("input") or "").strip()
    return {
        "id": f"{candidate_id}_sample" if candidate_id else "",
        "spoken_type": candidate.get("spoken_type") or "",
        "input": input_text,
        "expected_task_type": item.get("expected_task_type") or candidate.get("expected_task_type") or "",
        "expected_domain": item.get("expected_domain") or candidate.get("expected_domain") or "",
        "output_shape": candidate.get("output_shape") or [],
        "must_keep": candidate.get("must_keep") or [],
        "must_drop": candidate.get("must_drop") or [],
    }


def _review_actions(status: str) -> list[str]:
    if status == "accepted":
        return [
            "确认 tests/route_samples.json 中已有等价样本或补充 accepted_sample_id。",
            "必要时补充 boundary/fake-LLM/hot-path 样本并运行严格治理门。",
        ]
    if status == "deferred":
        return [
            "保留候选和原因，等下一批同类语料足够多再决定是否入库。",
            "如果是路由误判，先补最小回归样本，再改 router。",
        ]
    if status == "rejected":
        return ["保留拒绝原因，避免后续重复导入同质样本。"]
    return [
        "人工选择 accepted_to_tests、rejected 或 deferred。",
        "accepted_to_tests 必须带 accepted_sample_id、reviewer 或 review_notes。",
    ]


def _compact_row(row: dict[str, Any], *, include_preview: bool = True) -> dict[str, Any]:
    keys = (
        "candidate_id",
        "status",
        "reason",
        "expected_task_type",
        "expected_domain",
        "review_notes",
        "suggested_sample",
        "already_in_reviewed_samples",
        "review_actions",
    )
    result = {key: row.get(key) for key in keys}
    if include_preview:
        result["novice_preview_text"] = row.get("novice_preview_text") or ""
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an offline candidate intake package")
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
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON package output path")
    parser.add_argument("--preview-limit", type=int, default=20, help="max candidate previews to render")
    parser.add_argument("--print-json", action="store_true", help="print JSON package")
    parser.add_argument("--fail-on-invalid", action="store_true", help="return 1 when package is invalid or runtime-isolated=false")
    parser.add_argument("--fail-on-pending", action="store_true", help="return 1 when any candidate remains pending")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    candidate_sources = [Path(item) for item in args.candidates] or list(DEFAULT_CANDIDATE_SOURCES)
    decisions_path = Path(args.decisions).expanduser()
    decisions = decisions_path if decisions_path.exists() else None

    try:
        package = build_package(
            candidate_sources,
            Path(args.reviewed_samples),
            decisions_path=decisions,
            preview_limit=args.preview_limit,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    output_text = json.dumps(package, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        summary = package["status_report_summary"]
        intake = package["intake"]
        print(f"Wrote {out_path}")
        print(
            "Candidate intake package: "
            f"{summary['candidate_count']} candidates, "
            f"accepted={intake['accepted_count']}, "
            f"deferred={intake['deferred_count']}, "
            f"rejected={intake['rejected_count']}, "
            f"pending={intake['pending_count']}, "
            f"runtime_isolated={package['status']['runtime_isolated']}"
        )

    invalid_failed = args.fail_on_invalid and (
        not package["status"]["valid"] or not package["status"]["runtime_isolated"]
    )
    pending_failed = args.fail_on_pending and package["intake"]["pending_count"] > 0
    if invalid_failed or pending_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
