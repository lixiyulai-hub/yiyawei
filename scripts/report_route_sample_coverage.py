#!/usr/bin/env python3
"""Report coverage gaps in tests/route_samples.json."""

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

from src.auditor.task_router import DomainType, TaskType
from scripts.governance_artifacts import sha256_file, utc_now_iso


DEFAULT_SAMPLES = ROOT / "tests" / "route_samples.json"
DEFAULT_OUTPUT = ROOT / "output" / "route_sample_coverage.json"
SCRIPT_NAME = "scripts/report_route_sample_coverage.py"
ARTIFACT_VERSION = 1

TASK_TYPES: tuple[TaskType, ...] = (
    "project_evaluation",
    "code_fix",
    "ui_ux_design",
    "visual_generation",
    "presentation_deck",
    "bug_report",
    "test_plan",
    "product_planning",
    "business_analysis",
    "text_polishing",
    "generic_task",
)

DOMAIN_TYPES: tuple[DomainType, ...] = (
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
    "general",
)


def build_report(samples_path: Path, *, target_per_task: int = 20, target_per_domain: int = 3) -> dict[str, Any]:
    samples_path = samples_path.expanduser().resolve()
    raw_text = samples_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    if not isinstance(data, list):
        raise ValueError("route sample file must contain a JSON list")

    task_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    invalid_items: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    seen_inputs: dict[str, int] = {}
    duplicate_items: list[dict[str, Any]] = []

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            invalid_items.append({"index": index, "reason": "item_not_object"})
            continue
        item_id = str(item.get("id") or "").strip()
        item_input = str(item.get("input") or "").strip()
        if not item_id:
            invalid_items.append({"index": index, "reason": "missing_id"})
        elif item_id in seen_ids:
            duplicate_items.append(
                {
                    "index": index,
                    "id": item_id,
                    "reason": "duplicate_id",
                    "first_index": seen_ids[item_id],
                }
            )
        else:
            seen_ids[item_id] = index
        if not item_input:
            invalid_items.append({"index": index, "id": item_id or None, "reason": "missing_input"})
        elif item_input in seen_inputs:
            duplicate_items.append(
                {
                    "index": index,
                    "id": item_id or None,
                    "reason": "duplicate_input",
                    "first_index": seen_inputs[item_input],
                }
            )
        else:
            seen_inputs[item_input] = index
        task_type = item.get("expected_task_type")
        domain = item.get("expected_domain")
        if task_type in TASK_TYPES:
            task_counts[str(task_type)] += 1
        else:
            invalid_items.append({"index": index, "id": item.get("id"), "reason": "unknown_task_type"})
        if domain in DOMAIN_TYPES:
            domain_counts[str(domain)] += 1
        else:
            invalid_items.append({"index": index, "id": item.get("id"), "reason": "unknown_domain"})

    by_task = {
        task_type: {
            "count": task_counts.get(task_type, 0),
            "target": target_per_task,
            "gap": max(0, target_per_task - task_counts.get(task_type, 0)),
        }
        for task_type in TASK_TYPES
    }
    by_domain = {
        domain: {
            "count": domain_counts.get(domain, 0),
            "target": target_per_domain,
            "gap": max(0, target_per_domain - domain_counts.get(domain, 0)),
        }
        for domain in DOMAIN_TYPES
    }

    missing_task_types = [task for task, stats in by_task.items() if stats["count"] == 0]
    missing_domains = [domain for domain, stats in by_domain.items() if stats["count"] == 0]
    task_target_gaps = [
        {"task_type": task, **stats} for task, stats in by_task.items() if stats["gap"] > 0
    ]
    domain_target_gaps = [
        {"domain": domain, **stats} for domain, stats in by_domain.items() if stats["gap"] > 0
    ]

    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "samples_path": str(samples_path),
        "samples_sha256": sha256_file(samples_path),
        "sample_count": len(data),
        "target_per_task": target_per_task,
        "target_per_domain": target_per_domain,
        "by_task": by_task,
        "by_domain": by_domain,
        "missing_task_types": missing_task_types,
        "missing_domains": missing_domains,
        "task_target_gaps": task_target_gaps,
        "domain_target_gaps": domain_target_gaps,
        "largest_task_gaps": sorted(
            ({"task_type": task, **stats} for task, stats in by_task.items()),
            key=lambda item: (-int(item["gap"]), str(item["task_type"])),
        ),
        "largest_domain_gaps": sorted(
            ({"domain": domain, **stats} for domain, stats in by_domain.items()),
            key=lambda item: (-int(item["gap"]), str(item["domain"])),
        ),
        "invalid_items": invalid_items,
        "duplicate_items": duplicate_items,
        "status": {
            "valid": not invalid_items and not duplicate_items,
            "has_missing_buckets": bool(missing_task_types or missing_domains),
            "meets_target_depth": not task_target_gaps and not domain_target_gaps,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report route sample coverage gaps")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES), help="route_samples.json path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--target-per-task", type=int, default=20, help="target sample count per task")
    parser.add_argument("--target-per-domain", type=int, default=3, help="target sample count per domain")
    parser.add_argument("--print-json", action="store_true", help="print JSON report to stdout")
    parser.add_argument("--fail-on-invalid", action="store_true", help="return 1 for invalid or duplicate samples")
    parser.add_argument("--fail-on-missing", action="store_true", help="return 1 when any task/domain bucket is empty")
    parser.add_argument("--fail-on-target-gap", action="store_true", help="return 1 when any task/domain target gap remains")
    args = parser.parse_args(argv)

    try:
        report = build_report(
            Path(args.samples),
            target_per_task=max(1, args.target_per_task),
            target_per_domain=max(1, args.target_per_domain),
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
            f"Route samples: {report['sample_count']}; "
            f"missing task types={len(report['missing_task_types'])}; "
            f"missing domains={len(report['missing_domains'])}; "
            f"task target gaps={len(report['task_target_gaps'])}; "
            f"domain target gaps={len(report['domain_target_gaps'])}."
        )
    if args.fail_on_invalid and not report["status"]["valid"]:
        return 1
    if args.fail_on_missing and report["status"]["has_missing_buckets"]:
        return 1
    if args.fail_on_target_gap and not report["status"]["meets_target_depth"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
