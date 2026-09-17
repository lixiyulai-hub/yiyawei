#!/usr/bin/env python3
"""Safely add or update an offline route-sample candidate decision.

The command edits only the manual decision file when ``--commit`` is supplied.
It does not promote samples and does not read or write runtime code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import utc_now_iso
from scripts.report_candidate_review_status import (
    DEFAULT_CANDIDATE_SOURCES,
    DEFAULT_DECISIONS,
    DEFAULT_REVIEWED_SAMPLES,
    build_report as build_status_report,
)


ALLOWED_STATUSES = {"accepted_to_tests", "rejected", "deferred"}
ACCEPTED_STATUSES = {"accepted_to_tests"}
SCRIPT_NAME = "scripts/decide_route_sample_candidate.py"


def build_validated_decision_update(
    candidate_sources: list[Path],
    reviewed_samples_path: Path,
    decisions_path: Path,
    *,
    candidate_id: str,
    review_status: str,
    review_notes: str = "",
    accepted_sample_id: str = "",
    reviewer: str = "codex",
    source: str = "cli",
    replace: bool = False,
    equivalence_note: str = "",
    strict: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_sources = [path.expanduser().resolve() for path in candidate_sources]
    reviewed_samples_path = reviewed_samples_path.expanduser().resolve()
    decisions_path = validate_decisions_path(decisions_path)
    candidate_id = candidate_id.strip()
    normalized_status = _normalize_status(review_status)
    candidates = _load_candidates(candidate_sources)
    candidate = _get_unique_candidate(candidates, candidate_id)
    reviewed_samples = _load_reviewed_samples(reviewed_samples_path)
    reviewed_by_id = {
        str(sample.get("id") or "").strip(): sample
        for sample in reviewed_samples
        if str(sample.get("id") or "").strip()
    }

    _validate_decision(
        candidate_id=candidate_id,
        review_status=normalized_status,
        review_notes=review_notes,
        accepted_sample_id=accepted_sample_id,
        reviewer=reviewer,
    )
    _validate_candidate_safety(candidate)
    _validate_acceptance(
        candidate,
        reviewed_by_id,
        review_status=normalized_status,
        accepted_sample_id=accepted_sample_id,
        equivalence_note=equivalence_note,
    )

    document, summary = build_updated_decisions(
        decisions_path,
        candidate_id=candidate_id,
        review_status=normalized_status,
        review_notes=review_notes,
        accepted_sample_id=accepted_sample_id,
        reviewer=reviewer,
        source=source,
        replace=replace,
        equivalence_note=equivalence_note,
    )

    # Validate the staged decision document using the existing review report.
    staged_path = decisions_path.parent / f".{decisions_path.name}.staged"
    try:
        staged_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        status_report = build_status_report(
            candidate_sources,
            reviewed_samples_path,
            decisions_path=staged_path,
        )
    finally:
        try:
            staged_path.unlink()
        except FileNotFoundError:
            pass

    if not status_report["status"]["valid"] or not status_report["status"]["runtime_isolated"]:
        raise ValueError("staged decision does not pass candidate review validity/runtime isolation")
    if strict and status_report["pending_count"] > 0:
        raise ValueError("staged decision still leaves pending candidates")
    summary["status_report"] = {
        "candidate_count": status_report["candidate_count"],
        "pending_count": status_report["pending_count"],
        "valid": status_report["status"]["valid"],
        "runtime_isolated": status_report["status"]["runtime_isolated"],
        "ready_for_strict_release": status_report["status"]["ready_for_strict_release"],
    }
    return document, summary


def build_updated_decisions(
    decisions_path: Path,
    *,
    candidate_id: str,
    review_status: str,
    review_notes: str = "",
    accepted_sample_id: str = "",
    reviewer: str = "codex",
    source: str = "cli",
    replace: bool = False,
    equivalence_note: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_id = candidate_id.strip()
    normalized_status = _normalize_status(review_status)
    _validate_decision(
        candidate_id=candidate_id,
        review_status=normalized_status,
        review_notes=review_notes,
        accepted_sample_id=accepted_sample_id,
        reviewer=reviewer,
    )

    document = _load_decision_document(decisions_path)
    decisions = document.setdefault("decisions", [])
    if not isinstance(decisions, list):
        raise ValueError("decision document field 'decisions' must be a list")

    new_record = {
        "candidate_id": candidate_id,
        "review_status": normalized_status,
        "review_notes": review_notes.strip(),
    }
    if accepted_sample_id.strip():
        new_record["accepted_sample_id"] = accepted_sample_id.strip()
    if equivalence_note.strip():
        new_record["equivalence_note"] = equivalence_note.strip()
    if reviewer.strip():
        new_record["reviewer"] = reviewer.strip()
    new_record["decided_at"] = utc_now_iso()
    new_record["decision_source"] = source.strip() or "cli"

    old_record: dict[str, Any] | None = None
    replaced = False
    for index, record in enumerate(decisions):
        if not isinstance(record, dict):
            continue
        if str(record.get("candidate_id") or "").strip() == candidate_id:
            if not replace:
                raise ValueError("candidate already has a decision; pass --replace to update it")
            old_record = dict(record)
            decisions[index] = new_record
            replaced = True
            break
    if not replaced:
        decisions.append(new_record)

    document["schema_version"] = int(document.get("schema_version") or 1)
    document["reviewed_at"] = utc_now_iso()[:10]
    document.setdefault("reviewer", reviewer.strip() or "codex")
    document.setdefault(
        "notes",
        "Manual governance decisions for offline GitHub/Obsidian route-sample candidates. Candidate JSON remains offline-only and must not be read by runtime code.",
    )

    summary = {
        "candidate_id": candidate_id,
        "review_status": normalized_status,
        "updated_existing": replaced,
        "old_record": old_record,
        "new_record": new_record,
        "decision_count": len(decisions),
    }
    return document, summary


def _normalize_status(status: str) -> str:
    normalized = status.strip().lower().replace("-", "_")
    if normalized == "accepted":
        return "accepted_to_tests"
    return normalized


def _validate_decision(
    *,
    candidate_id: str,
    review_status: str,
    review_notes: str,
    accepted_sample_id: str,
    reviewer: str,
) -> None:
    if not candidate_id:
        raise ValueError("candidate_id is required")
    if review_status not in ALLOWED_STATUSES:
        raise ValueError(f"review_status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if not review_notes.strip():
        raise ValueError("review notes are required")
    if review_status in ACCEPTED_STATUSES:
        if not accepted_sample_id.strip():
            raise ValueError("accepted decisions require --accepted-sample-id")
    else:
        if accepted_sample_id.strip():
            raise ValueError("rejected/deferred decisions must not include --accepted-sample-id")


def _load_candidates(paths: list[Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("candidates") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError(f"candidate source must contain a list: {path}")
        for index, candidate in enumerate(items, start=1):
            if not isinstance(candidate, dict):
                continue
            suggested = candidate.get("suggested_route_sample")
            suggested_sample = suggested if isinstance(suggested, dict) else {}
            candidate_id = str(
                candidate.get("candidate_id")
                or suggested_sample.get("id")
                or f"{path.stem}_{index:03d}"
            ).strip()
            item = dict(candidate)
            item["_candidate_id"] = candidate_id
            item["_source_file"] = str(path)
            candidates.append(item)
    return candidates


def _get_unique_candidate(candidates: list[dict[str, Any]], candidate_id: str) -> dict[str, Any]:
    matches = [candidate for candidate in candidates if candidate.get("_candidate_id") == candidate_id]
    if not matches:
        raise ValueError(f"candidate id not found: {candidate_id}")
    if len(matches) > 1:
        raise ValueError(f"candidate id appears multiple times: {candidate_id}")
    return matches[0]


def _load_reviewed_samples(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("reviewed route samples must be a JSON list")
    return [item for item in data if isinstance(item, dict)]


def _validate_candidate_safety(candidate: dict[str, Any]) -> None:
    if candidate.get("hot_path_allowed") is True:
        raise ValueError("candidate has hot_path_allowed=true")
    if candidate.get("network_used") is True:
        raise ValueError("candidate has network_used=true")
    if candidate.get("repo_clone_or_download_used") is True:
        raise ValueError("candidate has repo_clone_or_download_used=true")


def _validate_acceptance(
    candidate: dict[str, Any],
    reviewed_by_id: dict[str, dict[str, Any]],
    *,
    review_status: str,
    accepted_sample_id: str,
    equivalence_note: str,
) -> None:
    if review_status not in ACCEPTED_STATUSES:
        return
    sample_id = accepted_sample_id.strip()
    sample = reviewed_by_id.get(sample_id)
    if not sample:
        raise ValueError(f"accepted sample id not found in reviewed samples: {sample_id}")
    expected_task = str(candidate.get("expected_task_type") or "").strip()
    expected_domain = str(candidate.get("expected_domain") or "").strip()
    sample_task = str(sample.get("expected_task_type") or "").strip()
    sample_domain = str(sample.get("expected_domain") or "").strip()
    if expected_task and sample_task and expected_task != sample_task:
        raise ValueError("accepted sample task type does not match candidate")
    if expected_domain and sample_domain and expected_domain != sample_domain:
        raise ValueError("accepted sample domain does not match candidate")

    candidate_input = _candidate_input(candidate)
    sample_input = str(sample.get("input") or "")
    if _normalize_text(candidate_input) != _normalize_text(sample_input) and len(equivalence_note.strip()) < 12:
        raise ValueError("accepted sample input differs; provide --equivalence-note with rationale")


def _candidate_input(candidate: dict[str, Any]) -> str:
    suggested = candidate.get("suggested_route_sample")
    suggested_sample = suggested if isinstance(suggested, dict) else {}
    return str(candidate.get("input") or suggested_sample.get("input") or "")


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _load_decision_document(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    if not path.exists():
        return {
            "schema_version": 1,
            "reviewed_at": utc_now_iso()[:10],
            "reviewer": "codex",
            "notes": "Manual governance decisions for offline route-sample candidates.",
            "decisions": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("decision file must be a JSON object")
    data.setdefault("decisions", [])
    return data


def validate_decisions_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = ROOT.resolve()
    forbidden_exact = {
        (root / "app.py").resolve(),
        (root / "tests" / "route_samples.json").resolve(),
    }
    if resolved in forbidden_exact:
        raise ValueError("decision output path must not target runtime code or reviewed samples")
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return resolved
    parts = relative.parts
    if parts and parts[0] == "src":
        raise ValueError("decision output path must not be under src/")
    if parts and parts[0] == "tests" and resolved.suffix == ".py":
        raise ValueError("decision output path must not overwrite tests/*.py")
    return resolved


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Add or update one route-sample candidate decision")
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
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS), help="decision JSON path")
    parser.add_argument("--candidate-id", required=True, help="candidate id to decide")
    parser.add_argument("--status", required=True, choices=sorted(ALLOWED_STATUSES), help="accepted_to_tests, rejected, or deferred")
    parser.add_argument("--notes", "--review-notes", dest="notes", default="", help="manual review notes")
    parser.add_argument("--accepted-sample-id", default="", help="required for accepted_to_tests")
    parser.add_argument("--equivalence-note", default="", help="required when accepted sample input differs from candidate input")
    parser.add_argument("--reviewer", default="codex", help="reviewer name")
    parser.add_argument("--source", default="cli", help="decision source label")
    parser.add_argument("--replace", action="store_true", help="replace an existing decision for this candidate")
    parser.add_argument("--strict", action="store_true", help="also require no pending candidates after staging")
    parser.add_argument("--commit", action="store_true", help="write the updated decision file")
    parser.add_argument("--write", action="store_true", help="alias for --commit")
    parser.add_argument("--print-json", action="store_true", help="print updated decision document")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        decisions_path = validate_decisions_path(Path(args.decisions))
        candidate_sources = [Path(item) for item in args.candidates] or list(DEFAULT_CANDIDATE_SOURCES)
        document, summary = build_validated_decision_update(
            candidate_sources,
            Path(args.reviewed_samples),
            decisions_path,
            candidate_id=args.candidate_id,
            review_status=args.status,
            review_notes=args.notes,
            accepted_sample_id=args.accepted_sample_id,
            reviewer=args.reviewer,
            source=args.source,
            replace=bool(args.replace),
            equivalence_note=args.equivalence_note,
            strict=bool(args.strict),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    output_text = json.dumps(document, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    should_commit = bool(args.commit or args.write)
    if should_commit:
        decisions_path.parent.mkdir(parents=True, exist_ok=True)
        decisions_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {decisions_path}")
    else:
        print("[DRY-RUN] decision file was not modified; pass --commit to save.")
    print(
        "Decision: "
        f"{summary['candidate_id']} -> {summary['review_status']} "
        f"(updated_existing={summary['updated_existing']}, decisions={summary['decision_count']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
