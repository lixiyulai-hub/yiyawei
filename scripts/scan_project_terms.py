#!/usr/bin/env python3
"""Validate and summarize governed project terms as offline evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso


DEFAULT_TERMS = ROOT / "data" / "project_terms.json"
DEFAULT_OUTPUT = ROOT / "output" / "project_terms_scan.json"
SCRIPT_NAME = "scripts/scan_project_terms.py"
ARTIFACT_VERSION = 1
SCAN_DIRS = ("README.md", "docs", "tests", "scripts")
SECRET_RE = re.compile(r"(api[_-]?key|token|secret|password|cookie|credential)", re.IGNORECASE)


def build_report(*, terms_path: Path = DEFAULT_TERMS, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    checks: list[dict[str, Any]] = []
    data: dict[str, Any] = {}
    if not terms_path.exists():
        checks.append(_error("terms_file", f"missing {terms_path}"))
    else:
        try:
            data = json.loads(terms_path.read_text(encoding="utf-8"))
            checks.append(_ok("terms_file", "JSON parsed"))
        except json.JSONDecodeError as exc:
            checks.append(_error("terms_file", f"cannot parse JSON: {exc}"))

    terms = data.get("terms") if isinstance(data.get("terms"), list) else []
    if data and data.get("schema_version") != 1:
        checks.append(_error("terms_schema", "schema_version must be 1"))
    if data and not isinstance(data.get("terms"), list):
        checks.append(_error("terms_schema", "terms must be a list"))

    normalized_seen: dict[str, str] = {}
    category_counts: dict[str, int] = {}
    term_summaries: list[dict[str, Any]] = []
    for index, term in enumerate(terms):
        term_checks, summary = _check_term(term, index, normalized_seen)
        checks.extend(term_checks)
        term_summaries.append(summary)
        category = summary.get("category") or "unknown"
        category_counts[category] = category_counts.get(category, 0) + 1

    mentions = _scan_mentions(root, term_summaries)
    errors = [check for check in checks if check["status"] == "error"]
    warnings = [check for check in checks if check["status"] == "warning"]
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "terms_path": str(terms_path),
        "terms_sha256": sha256_file(terms_path) if terms_path.exists() else "",
        "term_count": len(terms),
        "category_counts": category_counts,
        "terms": term_summaries,
        "mentions": mentions,
        "checks": checks,
        "summary": {
            "term_count": len(terms),
            "category_count": len(category_counts),
            "mention_file_count": len(mentions),
            "check_count": len(checks),
            "ok_count": sum(1 for check in checks if check["status"] == "ok"),
            "warning_count": len(warnings),
            "error_count": len(errors),
        },
        "status": {
            "passed": not errors,
            "valid": not errors,
            "runtime_isolated": True,
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "notes": [
            "Project terms are governance source data only.",
            "Runtime compiler code must not read this scan report.",
        ],
    }


def _check_term(term: Any, index: int, normalized_seen: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    name = f"term:{index}"
    if not isinstance(term, dict):
        return [_error(name, "term must be an object")], {"canonical": "", "aliases": [], "category": "invalid"}
    canonical = str(term.get("canonical") or "").strip()
    category = str(term.get("category") or "").strip()
    aliases = term.get("aliases") if isinstance(term.get("aliases"), list) else []
    aliases = [str(alias).strip() for alias in aliases if str(alias).strip()]
    checks: list[dict[str, Any]] = []
    if canonical:
        checks.append(_ok(f"{name}:canonical", canonical))
    else:
        checks.append(_error(f"{name}:canonical", "missing canonical"))
    if category:
        checks.append(_ok(f"{name}:category", category))
    else:
        checks.append(_error(f"{name}:category", "missing category"))
    if aliases:
        checks.append(_ok(f"{name}:aliases", f"{len(aliases)} aliases"))
    else:
        checks.append(_warning(f"{name}:aliases", "no aliases"))
    for value in [canonical, *aliases]:
        key = value.lower()
        if not key:
            continue
        if SECRET_RE.search(value):
            checks.append(_error(f"{name}:sensitive_term", f"secret-like term is not allowed: {value}"))
        previous = normalized_seen.get(key)
        if previous and previous != canonical:
            checks.append(_error(f"{name}:duplicate_alias", f"{value} already belongs to {previous}"))
        normalized_seen[key] = canonical
    return checks, {"canonical": canonical, "aliases": aliases, "category": category}


def _scan_mentions(root: Path, terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns = []
    for term in terms:
        values = [term.get("canonical") or "", *(term.get("aliases") or [])]
        for value in values:
            if value:
                patterns.append((term.get("canonical") or value, value))
    if not patterns:
        return []

    files: list[Path] = []
    for entry in SCAN_DIRS:
        path = root / entry
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {".md", ".py", ".json"})
    mentions: list[dict[str, Any]] = []
    for path in sorted(set(files)):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if len(text) > 200_000:
            continue
        matched: dict[str, int] = {}
        lower = text.lower()
        for canonical, value in patterns:
            count = lower.count(value.lower())
            if count:
                matched[canonical] = matched.get(canonical, 0) + count
        if matched:
            mentions.append(
                {
                    "path": str(path.relative_to(root)),
                    "matched_terms": dict(sorted(matched.items())),
                    "match_count": sum(matched.values()),
                }
            )
    return mentions


def _check(name: str, status: str, message: str) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message}


def _ok(name: str, message: str) -> dict[str, Any]:
    return _check(name, "ok", message)


def _warning(name: str, message: str) -> dict[str, Any]:
    return _check(name, "warning", message)


def _error(name: str, message: str) -> dict[str, Any]:
    return _check(name, "error", message)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan governed project terms")
    parser.add_argument("--terms", default=str(DEFAULT_TERMS), help="project terms JSON")
    parser.add_argument("--root", default=str(ROOT), help="project root override")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--fail-on-error", action="store_true", help="return 1 when structural errors are found")
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = build_report(terms_path=Path(args.terms), root=Path(args.root))
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            "Project terms scan: "
            f"terms={report['summary']['term_count']}, "
            f"errors={report['summary']['error_count']}, "
            f"warnings={report['summary']['warning_count']}, "
            f"passed={report['status']['passed']}"
        )
    if args.fail_on_error and not report["status"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
