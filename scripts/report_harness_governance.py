#!/usr/bin/env python3
"""Build an offline harness governance snapshot.

The report records prompt-contract shape, key source hashes, route/compiler
surface metrics, QualityGate checks, and runtime isolation findings. It is a
review receipt only; runtime prompt compilation must not read its output.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import canonical_json_sha256, sha256_file, sha256_text, utc_now_iso


DEFAULT_OUTPUT = ROOT / "output" / "harness_governance_snapshot.json"
SCRIPT_NAME = "scripts/report_harness_governance.py"
ARTIFACT_VERSION = 1

HARNESS_SOURCES: tuple[tuple[str, str], ...] = (
    ("prompt", "src/auditor/prompt.py"),
    ("intent_frame", "src/auditor/intent_frame.py"),
    ("task_router", "src/auditor/task_router.py"),
    ("task_compiler", "src/auditor/task_compiler.py"),
    ("processor", "src/auditor/processor.py"),
)

OPTIONAL_EVIDENCE: tuple[tuple[str, str], ...] = (
    ("hot_path_benchmark", "output/hot_path_benchmark.json"),
    ("hot_path_trends", "output/hot_path_trends.json"),
    ("processor_fake_llm_benchmark", "output/processor_fake_llm_benchmark.json"),
    ("confirmed_edit_failures_report", "output/confirmed_edit_failures_report.json"),
    ("governance_manifest", "output/governance_manifest.json"),
)

FORBIDDEN_RUNTIME_REFERENCES: tuple[str, ...] = (
    "system_prompts_leaks",
    "mp.weixin.qq.com/s/Vqs9_V72w-KZh1Q5TSTmwA",
    "wechat_article_Vqs9",
    ".planning/skills/weixin-public-account-runs",
    "harness_governance_audit_2026-06-29",
    "harness_governance_snapshot",
    "report_harness_governance",
)


def build_report(root: Path = ROOT) -> dict[str, Any]:
    root = root.expanduser().resolve()
    sources = [_source_entry(root, key, rel_path) for key, rel_path in HARNESS_SOURCES]
    source_by_key = {str(entry["key"]): entry for entry in sources}
    prompt_source = _read_text(root / "src" / "auditor" / "prompt.py")
    processor_source = _read_text(root / "src" / "auditor" / "processor.py")
    router_source = _read_text(root / "src" / "auditor" / "task_router.py")
    compiler_source = _read_text(root / "src" / "auditor" / "task_compiler.py")
    runtime_violations = _runtime_reference_violations(root)
    contract_checks = _contract_checks(prompt_source, processor_source, router_source, runtime_violations)
    evidence = [_evidence_entry(root, key, rel_path) for key, rel_path in OPTIONAL_EVIDENCE]
    failures = _failures(sources, contract_checks, runtime_violations)
    stable_payload = {
        "sources": [_fingerprint_source(entry) for entry in sources],
        "contract_checks": contract_checks,
        "runtime_reference_violations": runtime_violations,
        "prompt_metrics": _prompt_metrics(prompt_source),
        "route_metrics": _route_metrics(router_source, compiler_source),
        "quality_gate_metrics": _quality_gate_metrics(processor_source),
    }
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "mode": "offline_harness_governance_snapshot",
        "root": str(root),
        "source_count": len(sources),
        "sources": sources,
        "source_fingerprint": canonical_json_sha256(
            {"sources": [_fingerprint_source(entry) for entry in sources]}
        ),
        "audit_fingerprint": canonical_json_sha256(stable_payload),
        "prompt_metrics": stable_payload["prompt_metrics"],
        "route_metrics": stable_payload["route_metrics"],
        "quality_gate_metrics": stable_payload["quality_gate_metrics"],
        "contract_checks": contract_checks,
        "runtime_reference_violations": runtime_violations,
        "evidence": evidence,
        "failures": failures,
        "status": {
            "valid": not failures,
            "runtime_isolated": not runtime_violations,
            "failure_count": len(failures),
            "contract_check_failed_count": sum(1 for item in contract_checks if not item["passed"]),
            "runtime_reference_violation_count": len(runtime_violations),
        },
        "adoption_boundary": {
            "adopted": [
                "harness as engineering contract",
                "prompt and route changes require reviewable receipts",
                "small reviewed deltas over long prompt accretion",
                "offline snapshot/diff discipline",
            ],
            "rejected": [
                "leaked system prompt content",
                "runtime GitHub/Weixin/Obsidian lookup",
                "default prompt bloat",
            ],
        },
        "notes": [
            "This report is offline-only governance evidence.",
            "Runtime compiler code must not read this file or the referenced external article.",
            "Use this when reviewing substantial prompt, router, compiler, or QualityGate changes.",
        ],
    }


def _source_entry(root: Path, key: str, rel_path: str) -> dict[str, Any]:
    path = (root / rel_path).resolve()
    entry: dict[str, Any] = {
        "key": key,
        "path": _display_path(root, path),
        "required": True,
        "exists": path.exists(),
    }
    if not path.exists():
        return entry
    text = path.read_text(encoding="utf-8")
    entry.update(
        {
            "size_bytes": path.stat().st_size,
            "line_count": text.count("\n") + (1 if text else 0),
            "sha256": sha256_file(path),
        }
    )
    return entry


def _evidence_entry(root: Path, key: str, rel_path: str) -> dict[str, Any]:
    path = (root / rel_path).resolve()
    entry: dict[str, Any] = {
        "key": key,
        "path": _display_path(root, path),
        "required": False,
        "exists": path.exists(),
    }
    if not path.exists():
        return entry
    entry["size_bytes"] = path.stat().st_size
    entry["sha256"] = sha256_file(path)
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            entry["json_error"] = str(exc)
            return entry
        if isinstance(data, dict):
            entry["summary"] = {
                "schema_version": data.get("schema_version"),
                "artifact_version": data.get("artifact_version"),
                "script_name": data.get("script_name"),
                "generated_at": data.get("generated_at"),
                "status": data.get("status"),
            }
    return entry


def _prompt_metrics(prompt_source: str) -> dict[str, Any]:
    constants = {
        name: _extract_string_constant(prompt_source, name)
        for name in ("SYSTEM_PROMPT", "FAST_SYSTEM_PROMPT")
    }
    metrics: dict[str, Any] = {}
    for name, value in constants.items():
        metrics[name] = {
            "present": bool(value),
            "chars": len(value),
            "non_whitespace_chars": len(re.sub(r"\s+", "", value)),
            "line_count": value.count("\n") + (1 if value else 0),
            "sha256": sha256_text(value) if value else "",
        }
    prompt_items = [item for item in metrics.values() if isinstance(item, dict)]
    metrics["total_chars"] = sum(int(item["chars"]) for item in prompt_items)
    metrics["total_non_whitespace_chars"] = sum(
        int(item["non_whitespace_chars"]) for item in prompt_items
    )
    return metrics


def _route_metrics(router_source: str, compiler_source: str) -> dict[str, Any]:
    return {
        "task_definition_count": router_source.count("TaskDefinition("),
        "domain_definition_count": router_source.count("DomainDefinition("),
        "task_prompt_template_count": router_source.count("TaskPromptTemplate("),
        "direct_task_opener_count": len(re.findall(r'"[a-z_]+":\s*"请', router_source)),
        "rule_fallback_builder_count": len(re.findall(r"def _build_[a-z0-9_]+", compiler_source)),
        "guard_helper_count": len(re.findall(r"def _looks_like_[a-z0-9_]+", compiler_source)),
    }


def _quality_gate_metrics(processor_source: str) -> dict[str, Any]:
    reasons = sorted(set(re.findall(r'return "([a-z0-9_]+)"', processor_source)))
    return {
        "reason_literal_count": len(reasons),
        "reason_literals": reasons,
        "has_quality_gate_history": "quality_gate_history" in processor_source,
        "has_quality_gate_attribution": "quality_gate_attribution" in processor_source,
        "has_internal_prompt_leak_guard": "_leaks_internal_prompt" in processor_source,
        "has_software_feedback_guard": "_missing_software_feedback_context" in processor_source,
    }


def _contract_checks(
    prompt_source: str,
    processor_source: str,
    router_source: str,
    runtime_violations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    system_prompt = _extract_string_constant(prompt_source, "SYSTEM_PROMPT")
    fast_prompt = _extract_string_constant(prompt_source, "FAST_SYSTEM_PROMPT")
    checks = [
        (
            "system_prompt_contract_present",
            bool(system_prompt and "Harness 输出合同" in system_prompt and "final_text" in system_prompt),
            "SYSTEM_PROMPT keeps the structured harness output contract.",
        ),
        (
            "fast_prompt_json_contract_present",
            bool(fast_prompt and "JSON" in fast_prompt and "final_text" in fast_prompt),
            "FAST_SYSTEM_PROMPT keeps a bounded JSON final_text contract.",
        ),
        (
            "intent_frame_wired",
            "extract_intent_frame" in router_source and "intent_frame" in processor_source,
            "IntentFrame remains wired into routing and debug state.",
        ),
        (
            "quality_gate_attribution_wired",
            "quality_gate_attribution" in processor_source and "quality_gate_history" in processor_source,
            "QualityGate attribution remains available for failure diagnosis.",
        ),
        (
            "internal_prompt_leak_guard_present",
            "_leaks_internal_prompt" in processor_source and "internal_prompt_leak" in processor_source,
            "Internal prompt/template leakage remains guarded.",
        ),
        (
            "runtime_isolation_present",
            not runtime_violations,
            "Runtime app/src files do not reference offline harness governance artifacts.",
        ),
    ]
    return [
        {"key": key, "passed": passed, "description": description}
        for key, passed, description in checks
    ]


def _runtime_reference_violations(root: Path) -> list[dict[str, Any]]:
    runtime_paths = [root / "app.py"]
    src_root = root / "src"
    if src_root.exists():
        runtime_paths.extend(sorted(src_root.rglob("*.py")))
    violations: list[dict[str, Any]] = []
    for path in runtime_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for term in FORBIDDEN_RUNTIME_REFERENCES:
            if term in text:
                violations.append(
                    {
                        "path": _display_path(root, path.resolve()),
                        "term": term,
                    }
                )
    return violations


def _failures(
    sources: list[dict[str, Any]],
    contract_checks: list[dict[str, Any]],
    runtime_violations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for source in sources:
        if not source.get("exists"):
            failures.append(
                {
                    "reason": "missing_required_source",
                    "key": source.get("key"),
                    "path": source.get("path"),
                }
            )
    for check in contract_checks:
        if not check.get("passed"):
            failures.append(
                {
                    "reason": "contract_check_failed",
                    "key": check.get("key"),
                    "description": check.get("description"),
                }
            )
    for violation in runtime_violations:
        failures.append(
            {
                "reason": "runtime_reference_violation",
                "path": violation.get("path"),
                "term": violation.get("term"),
            }
        )
    return failures


def _extract_string_constant(source: str, name: str) -> str:
    if not source:
        return ""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return ""


def _fingerprint_source(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": entry.get("key"),
        "path": entry.get("path"),
        "exists": entry.get("exists"),
        "sha256": entry.get("sha256", ""),
        "size_bytes": entry.get("size_bytes"),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build offline harness governance snapshot")
    parser.add_argument("--root", default=str(ROOT), help="project root")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="output JSON path")
    parser.add_argument("--fail-on-invalid", action="store_true", help="return 1 when snapshot is invalid")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    root = Path(args.root)
    report = build_report(root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "Harness governance snapshot: "
        f"valid={report['status']['valid']} "
        f"sources={report['source_count']} "
        f"failures={report['status']['failure_count']} "
        f"out={out_path}"
    )
    if args.fail_on_invalid and not report["status"]["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
