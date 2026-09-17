#!/usr/bin/env python3
"""Report qualitative route sample boundary coverage."""

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


DEFAULT_SAMPLES = ROOT / "tests" / "route_samples.json"
DEFAULT_OUTPUT = ROOT / "output" / "route_boundary_coverage.json"
SCRIPT_NAME = "scripts/report_route_boundary_coverage.py"
ARTIFACT_VERSION = 1

REQUIRED_BOUNDARIES = (
    "domain_generic_negative",
    "spoken_correction",
    "safety_boundary",
    "safety_counterexample",
)
REQUIRED_GENERIC_NEGATIVE_DOMAINS = (
    "saas",
    "ecommerce",
    "finance_risk",
    "healthcare",
)
REQUIRED_SAFETY_DOMAINS = (
    "general",
    "finance_risk",
    "healthcare",
)
REQUIRED_COUNTEREXAMPLE_DOMAINS = (
    "general",
    "finance_risk",
    "healthcare",
)
MIN_GENERIC_NEGATIVE_DOMAIN_SAMPLES = 2
MIN_SAFETY_DOMAIN_SAMPLES = 2
MIN_COUNTEREXAMPLE_DOMAIN_SAMPLES = 2


def build_report(samples_path: Path) -> dict[str, Any]:
    samples_path = samples_path.expanduser().resolve()
    raw_text = samples_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    if not isinstance(data, list):
        raise ValueError("route sample file must contain a JSON list")

    boundary_counts: Counter[str] = Counter()
    generic_negative_domains: Counter[str] = Counter()
    safety_domains: Counter[str] = Counter()
    counterexample_domains: Counter[str] = Counter()
    invalid_items: list[dict[str, Any]] = []
    ignored_boundary_tags: list[dict[str, Any]] = []
    matched_items: list[dict[str, Any]] = []

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        task = str(item.get("expected_task_type") or "").strip()
        domain = str(item.get("expected_domain") or "").strip()
        boundary_domain = str(item.get("boundary_domain") or domain).strip()
        boundaries, ignored_tags = _normalize_boundaries(item.get("boundary_tags"))
        for ignored_tag in ignored_tags:
            ignored_boundary_tags.append(
                {
                    "index": index,
                    "id": item_id,
                    "tag": ignored_tag,
                }
            )
        if not boundaries:
            boundaries = _infer_boundaries(item)
        if boundaries and task != "generic_task" and "domain_generic_negative" in boundaries:
            invalid_items.append(
                {
                    "index": index,
                    "id": item_id,
                    "reason": "domain_generic_negative_requires_generic_task",
                }
            )
        for boundary in boundaries:
            boundary_counts[boundary] += 1
            matched_items.append(
                {
                    "id": item_id,
                    "boundary": boundary,
                    "expected_task_type": task,
                    "expected_domain": domain,
                    "boundary_domain": boundary_domain,
                }
            )
            if boundary == "domain_generic_negative":
                generic_negative_domains[boundary_domain] += 1
            if boundary == "safety_boundary":
                safety_domains[boundary_domain] += 1
            if boundary == "safety_counterexample":
                counterexample_domains[boundary_domain] += 1

    missing_boundaries = [
        boundary for boundary in REQUIRED_BOUNDARIES if boundary_counts.get(boundary, 0) == 0
    ]
    missing_generic_negative_domains = [
        domain
        for domain in REQUIRED_GENERIC_NEGATIVE_DOMAINS
        if generic_negative_domains.get(domain, 0) == 0
    ]
    missing_safety_domains = [
        domain for domain in REQUIRED_SAFETY_DOMAINS if safety_domains.get(domain, 0) == 0
    ]
    missing_counterexample_domains = [
        domain
        for domain in REQUIRED_COUNTEREXAMPLE_DOMAINS
        if counterexample_domains.get(domain, 0) == 0
    ]
    undercovered_generic_negative_domains = [
        {
            "domain": domain,
            "count": generic_negative_domains.get(domain, 0),
            "target": MIN_GENERIC_NEGATIVE_DOMAIN_SAMPLES,
        }
        for domain in REQUIRED_GENERIC_NEGATIVE_DOMAINS
        if generic_negative_domains.get(domain, 0) < MIN_GENERIC_NEGATIVE_DOMAIN_SAMPLES
    ]
    undercovered_safety_domains = [
        {
            "domain": domain,
            "count": safety_domains.get(domain, 0),
            "target": MIN_SAFETY_DOMAIN_SAMPLES,
        }
        for domain in REQUIRED_SAFETY_DOMAINS
        if safety_domains.get(domain, 0) < MIN_SAFETY_DOMAIN_SAMPLES
    ]
    undercovered_counterexample_domains = [
        {
            "domain": domain,
            "count": counterexample_domains.get(domain, 0),
            "target": MIN_COUNTEREXAMPLE_DOMAIN_SAMPLES,
        }
        for domain in REQUIRED_COUNTEREXAMPLE_DOMAINS
        if counterexample_domains.get(domain, 0) < MIN_COUNTEREXAMPLE_DOMAIN_SAMPLES
    ]

    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "samples_path": str(samples_path),
        "samples_sha256": sha256_file(samples_path),
        "sample_count": len(data),
        "required_boundaries": list(REQUIRED_BOUNDARIES),
        "required_generic_negative_domains": list(REQUIRED_GENERIC_NEGATIVE_DOMAINS),
        "required_safety_domains": list(REQUIRED_SAFETY_DOMAINS),
        "required_counterexample_domains": list(REQUIRED_COUNTEREXAMPLE_DOMAINS),
        "min_generic_negative_domain_samples": MIN_GENERIC_NEGATIVE_DOMAIN_SAMPLES,
        "min_safety_domain_samples": MIN_SAFETY_DOMAIN_SAMPLES,
        "min_counterexample_domain_samples": MIN_COUNTEREXAMPLE_DOMAIN_SAMPLES,
        "by_boundary": dict(sorted(boundary_counts.items())),
        "generic_negative_domains": dict(sorted(generic_negative_domains.items())),
        "safety_domains": dict(sorted(safety_domains.items())),
        "counterexample_domains": dict(sorted(counterexample_domains.items())),
        "missing_boundaries": missing_boundaries,
        "missing_generic_negative_domains": missing_generic_negative_domains,
        "missing_safety_domains": missing_safety_domains,
        "missing_counterexample_domains": missing_counterexample_domains,
        "undercovered_generic_negative_domains": undercovered_generic_negative_domains,
        "undercovered_safety_domains": undercovered_safety_domains,
        "undercovered_counterexample_domains": undercovered_counterexample_domains,
        "matched_items": matched_items,
        "invalid_items": invalid_items,
        "ignored_boundary_tags": ignored_boundary_tags,
        "status": {
            "valid": not invalid_items,
            "has_required_boundaries": not missing_boundaries,
            "has_required_generic_negative_domains": not missing_generic_negative_domains,
            "has_required_safety_domains": not missing_safety_domains,
            "has_required_counterexample_domains": not missing_counterexample_domains,
            "has_min_generic_negative_domain_samples": not undercovered_generic_negative_domains,
            "has_min_safety_domain_samples": not undercovered_safety_domains,
            "has_min_counterexample_domain_samples": not undercovered_counterexample_domains,
            "passed": not (
                invalid_items
                or missing_boundaries
                or missing_generic_negative_domains
                or missing_safety_domains
                or missing_counterexample_domains
                or undercovered_generic_negative_domains
                or undercovered_safety_domains
                or undercovered_counterexample_domains
            ),
        },
    }


def _normalize_boundaries(value: Any) -> tuple[list[str], list[str]]:
    if not isinstance(value, list):
        return ([], [])
    result: list[str] = []
    ignored: list[str] = []
    for item in value:
        boundary = str(item or "").strip()
        if boundary in REQUIRED_BOUNDARIES and boundary not in result:
            result.append(boundary)
        elif boundary:
            ignored.append(boundary)
    return (result, ignored)


def _infer_boundaries(item: dict[str, Any]) -> list[str]:
    item_id = str(item.get("id") or "")
    text = str(item.get("input") or "")
    result: list[str] = []
    if "generic_" in item_id and any(
        marker in text for marker in ("不要做", "别分析", "只帮我", "就行", "就好")
    ):
        result.append("domain_generic_negative")
    if any(marker in text for marker in ("不对", "算了", "不是让你", "先别")):
        result.append("spoken_correction")
    if any(
        marker in text
        for marker in (
            "诊断建议",
            "医疗结论",
            "买卖建议",
            "投资建议",
            "清空数据库",
            "先别执行",
            "操作资金",
            "确认清单",
        )
    ):
        result.append("safety_boundary")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report route boundary coverage")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES), help="route_samples.json path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--print-json", action="store_true", help="print JSON report to stdout")
    parser.add_argument("--fail-on-missing", action="store_true", help="return 1 when required boundary coverage is missing")
    parser.add_argument("--fail-on-invalid", action="store_true", help="return 1 for invalid boundary tags")
    args = parser.parse_args(argv)

    try:
        report = build_report(Path(args.samples))
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
            "Route boundaries: "
            f"boundaries={dict(report['by_boundary'])}, "
            f"missing_generic_domains={len(report['missing_generic_negative_domains'])}, "
            f"missing_safety_domains={len(report['missing_safety_domains'])}, "
            f"undercovered_generic_domains={len(report['undercovered_generic_negative_domains'])}, "
            f"undercovered_safety_domains={len(report['undercovered_safety_domains'])}, "
            f"undercovered_counterexamples={len(report['undercovered_counterexample_domains'])}, "
            f"passed={report['status']['passed']}"
        )
    if args.fail_on_invalid and not report["status"]["valid"]:
        return 1
    if args.fail_on_missing and not report["status"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
