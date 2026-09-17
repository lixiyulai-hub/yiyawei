#!/usr/bin/env python3
"""Build a compact audit manifest for offline governance artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import canonical_json_sha256, sha256_file, utc_now_iso


DEFAULT_OUTPUT = ROOT / "output" / "governance_manifest.json"
SCRIPT_NAME = "scripts/build_governance_manifest.py"
ARTIFACT_VERSION = 1


@dataclass(frozen=True)
class ManifestFileSpec:
    key: str
    path: Path
    kind: str
    required: bool = True


def default_source_specs() -> list[ManifestFileSpec]:
    return [
        ManifestFileSpec("github_source_catalog", ROOT / "data" / "github_source_catalog.json", "source"),
        ManifestFileSpec("github_route_sample_candidates", ROOT / "output" / "github_route_sample_candidates.json", "source"),
        ManifestFileSpec("obsidian_route_sample_candidates", ROOT / "output" / "obsidian_route_sample_candidates.json", "source"),
        ManifestFileSpec("failed_utterance_cases", ROOT / "data" / "failed_utterance_cases.json", "source"),
        ManifestFileSpec("failed_utterance_route_sample_candidates", ROOT / "output" / "failed_utterance_route_sample_candidates.json", "source"),
        ManifestFileSpec("route_sample_candidate_review_decisions", ROOT / "data" / "route_sample_candidate_review_decisions.json", "source"),
        ManifestFileSpec("route_samples", ROOT / "tests" / "route_samples.json", "source"),
        ManifestFileSpec("hot_path_benchmark_samples", ROOT / "data" / "hot_path_benchmark_samples.json", "source"),
        ManifestFileSpec("processor_fake_llm_benchmark_samples", ROOT / "data" / "processor_fake_llm_benchmark_samples.json", "source"),
        ManifestFileSpec("processor_real_llm_benchmark_samples", ROOT / "data" / "processor_real_llm_benchmark_samples.json", "source"),
        ManifestFileSpec("asr_manual_evidence_cases", ROOT / "data" / "asr_manual_evidence_cases.json", "source"),
        ManifestFileSpec("project_terms", ROOT / "data" / "project_terms.json", "source"),
        ManifestFileSpec("vscode_cursor_plugin_package", ROOT / "integrations" / "vscode-cursor" / "package.json", "source"),
        ManifestFileSpec("vscode_cursor_plugin_extension", ROOT / "integrations" / "vscode-cursor" / "extension.js", "source"),
        ManifestFileSpec("pyinstaller_spec", ROOT / "packaging" / "VoicePromptCompiler.spec", "source"),
        ManifestFileSpec("hot_path_route_migrations", ROOT / "data" / "hot_path_route_migrations.json", "source"),
    ]


def default_artifact_specs() -> list[ManifestFileSpec]:
    return [
        ManifestFileSpec("route_sample_coverage", ROOT / "output" / "route_sample_coverage.json", "artifact"),
        ManifestFileSpec("route_boundary_coverage", ROOT / "output" / "route_boundary_coverage.json", "artifact"),
        ManifestFileSpec("route_sample_candidate_review_status", ROOT / "output" / "route_sample_candidate_review_status.json", "artifact"),
        ManifestFileSpec("route_sample_intake_package", ROOT / "output" / "route_sample_intake_package.json", "artifact"),
        ManifestFileSpec("route_sample_promotion_draft", ROOT / "output" / "route_sample_promotion_draft.json", "artifact"),
        ManifestFileSpec("hot_path_benchmark", ROOT / "output" / "hot_path_benchmark.json", "artifact"),
        ManifestFileSpec("hot_path_trends", ROOT / "output" / "hot_path_trends.json", "artifact"),
        ManifestFileSpec("processor_fake_llm_benchmark", ROOT / "output" / "processor_fake_llm_benchmark.json", "artifact"),
        ManifestFileSpec("processor_real_llm_benchmark", ROOT / "output" / "processor_real_llm_benchmark.json", "artifact", required=False),
        ManifestFileSpec("asr_manual_evidence", ROOT / "output" / "asr_manual_evidence.json", "artifact", required=False),
        ManifestFileSpec("plugin_poc_preflight", ROOT / "output" / "plugin_poc_preflight.json", "artifact", required=False),
        ManifestFileSpec("project_terms_scan", ROOT / "output" / "project_terms_scan.json", "artifact", required=False),
        ManifestFileSpec("pyinstaller_readiness", ROOT / "output" / "pyinstaller_readiness.json", "artifact", required=False),
        ManifestFileSpec("governance_artifact_freshness", ROOT / "output" / "governance_artifact_freshness.json", "artifact"),
        ManifestFileSpec("package_preflight", ROOT / "output" / "package_preflight.json", "artifact", required=False),
        ManifestFileSpec("bridge_smoke_evidence", ROOT / "output" / "bridge_smoke_evidence.json", "artifact", required=False),
        ManifestFileSpec("harness_governance_snapshot", ROOT / "output" / "harness_governance_snapshot.json", "artifact", required=False),
    ]


def public_source_specs() -> list[ManifestFileSpec]:
    """List only reproducible files allowed in a public snapshot."""
    return [
        ManifestFileSpec("github_source_catalog", ROOT / "data" / "github_source_catalog.json", "source"),
        ManifestFileSpec("route_samples", ROOT / "tests" / "route_samples.json", "source"),
        ManifestFileSpec("hot_path_benchmark_samples", ROOT / "data" / "hot_path_benchmark_samples.json", "source"),
        ManifestFileSpec("processor_fake_llm_benchmark_samples", ROOT / "data" / "processor_fake_llm_benchmark_samples.json", "source"),
        ManifestFileSpec("processor_real_llm_benchmark_samples", ROOT / "data" / "processor_real_llm_benchmark_samples.json", "source"),
        ManifestFileSpec("asr_manual_evidence_cases", ROOT / "data" / "asr_manual_evidence_cases.json", "source"),
        ManifestFileSpec("project_terms", ROOT / "data" / "project_terms.json", "source"),
        ManifestFileSpec("vscode_cursor_plugin_package", ROOT / "integrations" / "vscode-cursor" / "package.json", "source"),
        ManifestFileSpec("vscode_cursor_plugin_extension", ROOT / "integrations" / "vscode-cursor" / "extension.js", "source"),
        ManifestFileSpec("pyinstaller_spec", ROOT / "packaging" / "VoicePromptCompiler.spec", "source"),
    ]


def build_manifest(
    source_specs: list[ManifestFileSpec] | None = None,
    artifact_specs: list[ManifestFileSpec] | None = None,
    *,
    public_snapshot: bool = False,
) -> dict[str, Any]:
    if public_snapshot:
        source_specs = public_source_specs() if source_specs is None else source_specs
        artifact_specs = [] if artifact_specs is None else artifact_specs
    else:
        source_specs = default_source_specs() if source_specs is None else source_specs
        artifact_specs = default_artifact_specs() if artifact_specs is None else artifact_specs
    sources = [_file_entry(spec) for spec in source_specs]
    artifacts = [_file_entry(spec) for spec in artifact_specs]
    failures = [
        failure
        for entry in [*sources, *artifacts]
        for failure in entry.get("failures", [])
    ]

    stable_payload = {
        "sources": [_fingerprint_entry(entry) for entry in sources],
        "artifacts": [_fingerprint_entry(entry) for entry in artifacts],
        "failure_reasons": [failure.get("reason") for failure in failures],
    }
    source_payload = {
        "sources": [_fingerprint_entry(entry) for entry in sources],
    }
    artifact_payload = {
        "artifacts": [_fingerprint_entry(entry) for entry in artifacts],
    }

    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "release_scope": "public_snapshot" if public_snapshot else "internal_governance",
        "source_count": len(sources),
        "artifact_count": len(artifacts),
        "sources": sources,
        "artifacts": artifacts,
        "audit_fingerprint": canonical_json_sha256(stable_payload),
        "source_fingerprint": canonical_json_sha256(source_payload),
        "artifact_fingerprint": canonical_json_sha256(artifact_payload),
        "failures": failures,
        "status": {
            "valid": not failures,
            "runtime_isolated": True,
            "failure_count": len(failures),
            "missing_required_count": sum(1 for failure in failures if failure.get("reason") == "missing_required_file"),
        },
        "notes": [
            "This manifest summarizes offline governance state only.",
            "Runtime compiler code must not read this file.",
            (
                "Public snapshot mode excludes private generated output and validates only reproducible public inputs."
                if public_snapshot
                else "Internal mode requires the generated governance artifacts used by the release gate."
            ),
        ],
    }


def _file_entry(spec: ManifestFileSpec) -> dict[str, Any]:
    path = spec.path.expanduser().resolve()
    failures: list[dict[str, Any]] = []
    entry: dict[str, Any] = {
        "key": spec.key,
        "kind": spec.kind,
        "path": _display_path(path),
        "required": spec.required,
        "exists": path.exists(),
    }
    if not path.exists():
        if spec.required:
            failures.append(_failure(spec.key, "missing_required_file", path))
        entry["failures"] = failures
        return entry

    entry["size_bytes"] = path.stat().st_size
    entry["sha256"] = sha256_file(path)
    if spec.kind == "source" and path.suffix.lower() not in {".json", ".jsonl"}:
        entry["json_root_type"] = "not_json"
        entry["summary"] = {"file_type": path.suffix.lower().lstrip(".") or "text"}
        entry["failures"] = failures
        return entry
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        failures.append(
            {
                "key": spec.key,
                "reason": "malformed_json",
                "path": str(path),
                "error": str(exc),
            }
        )
        entry["failures"] = failures
        return entry

    if not isinstance(data, (dict, list)):
        failures.append(_failure(spec.key, "json_root_not_object_or_list", path))
    entry.update(_metadata(data))
    entry["summary"] = _summary_for(spec.key, data)
    failures.extend(_embedded_failures(spec.key, data, path))
    entry["failures"] = failures
    return entry


def _metadata(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"json_root_type": type(data).__name__}
    return {
        "json_root_type": "dict",
        "schema_version": data.get("schema_version"),
        "artifact_version": data.get("artifact_version"),
        "script_name": data.get("script_name"),
        "generated_at": data.get("generated_at"),
    }


def _summary_for(key: str, data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        return {"item_count": len(data)}
    if not isinstance(data, dict):
        return {"json_root_type": type(data).__name__}

    common = _common_summary(data)
    if key == "route_samples":
        return {"sample_count": len(data) if isinstance(data, list) else 0}
    if key == "github_source_catalog":
        sources = data.get("sources")
        return {**common, "source_count": len(sources) if isinstance(sources, list) else data.get("source_count")}
    if key == "failed_utterance_cases":
        cases = data.get("cases") if isinstance(data.get("cases"), list) else []
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for item in cases:
            if not isinstance(item, dict):
                continue
            status = str(item.get("review_status") or "unknown")
            severity = str(item.get("severity") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
            by_severity[severity] = by_severity.get(severity, 0) + 1
        return {
            **common,
            "case_count": len(cases),
            "by_status": by_status,
            "by_severity": by_severity,
            "runtime_hot_path_used": data.get("runtime_hot_path_used"),
            "network_used": data.get("network_used"),
            "repo_clone_or_download_used": data.get("repo_clone_or_download_used"),
        }
    if key in {"github_route_sample_candidates", "obsidian_route_sample_candidates", "failed_utterance_route_sample_candidates"}:
        redaction = data.get("redaction") if isinstance(data.get("redaction"), dict) else {}
        return {
            **common,
            "candidate_count": data.get("candidate_count"),
            "case_count": data.get("case_count"),
            "by_failure_mode": data.get("by_failure_mode"),
            "redaction": {
                "enabled": redaction.get("enabled"),
                "max_text_chars": redaction.get("max_text_chars"),
                "redacted_count": redaction.get("redacted_count"),
                "unredacted_sensitive_count": redaction.get("unredacted_sensitive_count"),
            } if redaction else {},
            "network_used": data.get("network_used"),
            "repo_clone_or_download_used": data.get("repo_clone_or_download_used"),
            "runtime_hot_path_used": data.get("runtime_hot_path_used"),
            "status": data.get("status"),
        }
    if key == "route_sample_candidate_review_decisions":
        decisions = data.get("decisions") if isinstance(data.get("decisions"), list) else []
        by_status: dict[str, int] = {}
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            status = str(decision.get("review_status") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        return {**common, "decision_count": len(decisions), "by_status": by_status}
    if key == "project_terms":
        terms = data.get("terms") if isinstance(data.get("terms"), list) else []
        by_category: dict[str, int] = {}
        for term in terms:
            if not isinstance(term, dict):
                continue
            category = str(term.get("category") or "unknown")
            by_category[category] = by_category.get(category, 0) + 1
        return {**common, "term_count": len(terms), "by_category": by_category}
    if key == "route_sample_coverage":
        return {
            **common,
            "sample_count": data.get("sample_count"),
            "task_type_count": len(data.get("by_task") or {}),
            "domain_count": len(data.get("by_domain") or {}),
            "task_target_gap_count": len(data.get("task_target_gaps") or []),
            "domain_target_gap_count": len(data.get("domain_target_gaps") or []),
            "status": data.get("status"),
        }
    if key == "route_boundary_coverage":
        return {
            **common,
            "sample_count": data.get("sample_count"),
            "by_boundary": data.get("by_boundary"),
            "status": data.get("status"),
        }
    if key == "route_sample_candidate_review_status":
        return {
            **common,
            "candidate_count": data.get("candidate_count"),
            "reviewed_sample_count": data.get("reviewed_sample_count"),
            "decision_count": data.get("decision_count"),
            "pending_count": data.get("pending_count"),
            "by_status": data.get("by_status"),
            "status": data.get("status"),
        }
    if key == "route_sample_intake_package":
        intake = data.get("intake") if isinstance(data.get("intake"), dict) else {}
        return {
            **common,
            "status_report_summary": data.get("status_report_summary"),
            "by_status": data.get("by_status"),
            "intake": {
                "accepted_count": intake.get("accepted_count"),
                "rejected_count": intake.get("rejected_count"),
                "deferred_count": intake.get("deferred_count"),
                "pending_count": intake.get("pending_count"),
                "preview_count": intake.get("preview_count"),
            },
            "status": data.get("status"),
        }
    if key == "route_sample_promotion_draft":
        return {
            **common,
            "draft_sample_count": data.get("draft_sample_count"),
            "skipped_count": data.get("skipped_count"),
            "include_existing": data.get("include_existing"),
            "status": data.get("status"),
        }
    if key == "hot_path_benchmark":
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        stage = summary.get("stage_ms") if isinstance(summary.get("stage_ms"), dict) else {}
        return {
            **common,
            "benchmark": data.get("benchmark"),
            "budget_pass": data.get("budget_pass"),
            "baseline_comparison": _baseline_summary(data.get("baseline_comparison")),
            "p95_ms": _p95_fields(stage, ("route_ms", "context_build_ms", "fallback_ms", "quality_gate_ms")),
        }
    if key == "hot_path_trends":
        governance = data.get("governance") if isinstance(data.get("governance"), dict) else {}
        health = data.get("health") if isinstance(data.get("health"), dict) else {}
        latest = data.get("latest") if isinstance(data.get("latest"), dict) else {}
        return {
            **common,
            "row_count": data.get("row_count"),
            "latest": {
                "sample_count": latest.get("sample_count"),
                "run_count": latest.get("run_count"),
                "budget_pass": latest.get("budget_pass"),
                "baseline_pass": latest.get("baseline_pass"),
                "p95_ms": latest.get("p95_ms"),
            },
            "warning_count": len(data.get("warnings") or []),
            "health": {
                "latest_budget_pass": health.get("latest_budget_pass"),
                "latest_baseline_pass": health.get("latest_baseline_pass"),
                "all_budget_pass": health.get("all_budget_pass"),
                "all_baseline_pass": health.get("all_baseline_pass"),
            },
            "governance": {
                "route_removed_count": governance.get("route_removed_count"),
                "unreviewed_route_removed_count": governance.get("unreviewed_route_removed_count"),
            },
        }
    if key == "processor_fake_llm_benchmark":
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        processor = summary.get("processor_ms") if isinstance(summary.get("processor_ms"), dict) else {}
        return {
            **common,
            "benchmark": data.get("benchmark"),
            "processor_ms_p95": processor.get("p95"),
            "debug_counters": summary.get("debug_counters"),
            "result_counters": summary.get("result_counters"),
            "invariants": data.get("invariants"),
        }
    if key == "processor_real_llm_benchmark":
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        benchmark = data.get("benchmark") if isinstance(data.get("benchmark"), dict) else {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        return {
            **common,
            "benchmark": benchmark,
            "real_llm_enabled": data.get("real_llm_enabled"),
            "local_llm_http_used": data.get("local_llm_http_used"),
            "external_llm_endpoint_used": data.get("external_llm_endpoint_used"),
            "skipped": data.get("skipped"),
            "provider": config.get("provider"),
            "model": config.get("model"),
            "summary": {
                "sample_count": summary.get("sample_count"),
                "failure_count": summary.get("failure_count"),
                "passed_count": summary.get("passed_count"),
                "failed_count": summary.get("failed_count"),
                "revision_attempted_count": summary.get("revision_attempted_count"),
                "rule_task_fallback_used_count": summary.get("rule_task_fallback_used_count"),
                "high_risk_count": summary.get("high_risk_count"),
                "medium_risk_count": summary.get("medium_risk_count"),
            },
            "invariants": data.get("invariants"),
            "status": data.get("status"),
        }
    if key == "governance_artifact_freshness":
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        return {
            **common,
            "artifact_count": data.get("artifact_count"),
            "status": status,
            "failure_count": status.get("failure_count"),
            "warning_count": status.get("warning_count"),
        }
    if key == "package_preflight":
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        return {
            **common,
            "check_count": summary.get("check_count"),
            "ok_count": summary.get("ok_count"),
            "warning_count": summary.get("warning_count"),
            "error_count": summary.get("error_count"),
            "required_dependency_count": summary.get("required_dependency_count"),
            "status": status,
        }
    if key == "bridge_smoke_evidence":
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        bridge = data.get("bridge") if isinstance(data.get("bridge"), dict) else {}
        response = data.get("response_summary") if isinstance(data.get("response_summary"), dict) else {}
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        return {
            **common,
            "check_count": summary.get("check_count"),
            "ok_count": summary.get("ok_count"),
            "warning_count": summary.get("warning_count"),
            "error_count": summary.get("error_count"),
            "local_http_used": data.get("local_http_used"),
            "live_app_used": data.get("live_app_used"),
            "source_kind": source.get("kind"),
            "bridge": {
                "host": bridge.get("host"),
                "auth_required": bridge.get("auth_required"),
                "endpoint": bridge.get("endpoint"),
                "mode": bridge.get("mode"),
            },
            "response": {
                "final_text_present": response.get("final_text_present"),
                "risk_level": response.get("risk_level"),
                "need_confirm": response.get("need_confirm"),
                "pasted": response.get("pasted"),
                "auto_paste_allowed": response.get("auto_paste_allowed"),
            },
            "status": status,
        }
    if key == "harness_governance_snapshot":
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        prompt_metrics = data.get("prompt_metrics") if isinstance(data.get("prompt_metrics"), dict) else {}
        route_metrics = data.get("route_metrics") if isinstance(data.get("route_metrics"), dict) else {}
        quality_gate_metrics = data.get("quality_gate_metrics") if isinstance(data.get("quality_gate_metrics"), dict) else {}
        return {
            **common,
            "source_count": data.get("source_count"),
            "source_fingerprint": data.get("source_fingerprint"),
            "audit_fingerprint": data.get("audit_fingerprint"),
            "prompt_chars": {
                "system": (prompt_metrics.get("SYSTEM_PROMPT") or {}).get("chars")
                if isinstance(prompt_metrics.get("SYSTEM_PROMPT"), dict)
                else None,
                "fast": (prompt_metrics.get("FAST_SYSTEM_PROMPT") or {}).get("chars")
                if isinstance(prompt_metrics.get("FAST_SYSTEM_PROMPT"), dict)
                else None,
                "total": prompt_metrics.get("total_chars"),
            },
            "route_metrics": route_metrics,
            "quality_gate": {
                "reason_literal_count": quality_gate_metrics.get("reason_literal_count"),
                "has_quality_gate_attribution": quality_gate_metrics.get("has_quality_gate_attribution"),
                "has_internal_prompt_leak_guard": quality_gate_metrics.get("has_internal_prompt_leak_guard"),
            },
            "runtime_reference_violation_count": status.get("runtime_reference_violation_count"),
            "contract_check_failed_count": status.get("contract_check_failed_count"),
            "status": status,
        }
    if key == "asr_manual_evidence":
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        wav = data.get("wav") if isinstance(data.get("wav"), dict) else {}
        return {
            **common,
            "case_count": data.get("case_count"),
            "live_asr_enabled": data.get("live_asr_enabled"),
            "asr_engine_used": data.get("asr_engine_used"),
            "skipped": data.get("skipped"),
            "wav_supplied": summary.get("wav_supplied"),
            "wav": {
                "exists": wav.get("exists"),
                "duration_sec": wav.get("duration_sec"),
                "sample_rate": wav.get("sample_rate"),
                "channels": wav.get("channels"),
            },
            "summary": summary,
            "status": status,
        }
    if key == "plugin_poc_preflight":
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        return {
            **common,
            "plugin_root": data.get("plugin_root"),
            "check_count": summary.get("check_count"),
            "warning_count": summary.get("warning_count"),
            "error_count": summary.get("error_count"),
            "status": status,
        }
    if key == "project_terms_scan":
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        return {
            **common,
            "term_count": data.get("term_count"),
            "category_counts": data.get("category_counts"),
            "mention_file_count": summary.get("mention_file_count"),
            "warning_count": summary.get("warning_count"),
            "error_count": summary.get("error_count"),
            "status": status,
        }
    if key == "pyinstaller_readiness":
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        return {
            **common,
            "build_executed": data.get("build_executed"),
            "spec_path": data.get("spec_path"),
            "entrypoint": data.get("entrypoint"),
            "check_count": summary.get("check_count"),
            "warning_count": summary.get("warning_count"),
            "error_count": summary.get("error_count"),
            "status": status,
        }
    return common


def _common_summary(data: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for field in (
        "candidate_count",
        "sample_count",
        "decision_count",
        "pending_count",
        "artifact_count",
        "row_count",
        "generated_at",
    ):
        if field in data:
            summary[field] = data.get(field)
    return summary


def _p95_fields(metrics: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        item = metrics.get(name)
        if isinstance(item, dict) and "p95" in item:
            result[name] = item.get("p95")
    return result


def _baseline_summary(value: Any) -> dict[str, Any]:
    baseline = value if isinstance(value, dict) else {}
    return {
        "passed": baseline.get("passed"),
        "warning_count": len(baseline.get("warnings") or []),
        "failure_count": len(baseline.get("failures") or []),
        "baseline_sample_count": baseline.get("baseline_sample_count"),
        "current_sample_count": baseline.get("current_sample_count"),
    }


def _embedded_failures(key: str, data: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    failures: list[dict[str, Any]] = []
    if data.get("runtime_hot_path_used") is True:
        failures.append(_failure(key, "runtime_hot_path_used", path))
    if data.get("network_used") is True:
        failures.append(_failure(key, "network_used", path))
    if data.get("repo_clone_or_download_used") is True:
        failures.append(_failure(key, "repo_clone_or_download_used", path))

    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    if status.get("valid") is False:
        failures.append(_failure(key, "status_valid_false", path))
    if status.get("passed") is False:
        failures.append(_failure(key, "status_passed_false", path))
    if status.get("runtime_isolated") is False:
        failures.append(_failure(key, "status_runtime_isolated_false", path))
    if status.get("modified_route_samples") is True:
        failures.append(_failure(key, "modified_route_samples_true", path))

    if key == "route_sample_candidate_review_status" and int(data.get("pending_count") or 0) > 0:
        failures.append(_failure(key, "pending_candidates", path))
    if key == "route_sample_coverage":
        coverage_status = data.get("status") if isinstance(data.get("status"), dict) else {}
        if coverage_status.get("has_missing_buckets") is True:
            failures.append(_failure(key, "coverage_has_missing_buckets", path))
        if coverage_status.get("meets_target_depth") is False:
            failures.append(_failure(key, "coverage_target_depth_not_met", path))
        if data.get("task_target_gaps"):
            failures.append(_failure(key, "task_target_gaps", path))
        if data.get("domain_target_gaps"):
            failures.append(_failure(key, "domain_target_gaps", path))
    if key == "route_sample_intake_package":
        intake = data.get("intake") if isinstance(data.get("intake"), dict) else {}
        if int(intake.get("pending_count") or 0) > 0:
            failures.append(_failure(key, "pending_intake_candidates", path))
    if key == "failed_utterance_route_sample_candidates":
        redaction = data.get("redaction") if isinstance(data.get("redaction"), dict) else {}
        if int(redaction.get("unredacted_sensitive_count") or 0) > 0:
            failures.append(_failure(key, "failed_utterance_unredacted_sensitive", path))
    if key == "hot_path_benchmark":
        if data.get("budget_pass") is False:
            failures.append(_failure(key, "budget_pass_false", path))
        baseline = data.get("baseline_comparison") if isinstance(data.get("baseline_comparison"), dict) else {}
        if baseline.get("passed") is False:
            failures.append(_failure(key, "baseline_passed_false", path))
    if key == "hot_path_trends":
        health = data.get("health") if isinstance(data.get("health"), dict) else {}
        governance = data.get("governance") if isinstance(data.get("governance"), dict) else {}
        if health.get("latest_budget_pass") is False:
            failures.append(_failure(key, "latest_budget_pass_false", path))
        if health.get("latest_baseline_pass") is False:
            failures.append(_failure(key, "latest_baseline_pass_false", path))
        if health.get("all_budget_pass") is False:
            failures.append(_failure(key, "all_budget_pass_false", path))
        if health.get("all_baseline_pass") is False:
            failures.append(_failure(key, "all_baseline_pass_false", path))
        if int(governance.get("unreviewed_route_removed_count") or 0) > 0:
            failures.append(_failure(key, "unreviewed_route_removed", path))
    if key == "processor_fake_llm_benchmark":
        invariants = data.get("invariants") if isinstance(data.get("invariants"), dict) else {}
        if invariants.get("passed") is False:
            failures.append(_failure(key, "invariants_passed_false", path))
    if key == "processor_real_llm_benchmark":
        invariants = data.get("invariants") if isinstance(data.get("invariants"), dict) else {}
        if invariants.get("passed") is False:
            failures.append(_failure(key, "invariants_passed_false", path))
    if key == "governance_artifact_freshness":
        freshness_status = data.get("status") if isinstance(data.get("status"), dict) else {}
        if freshness_status.get("passed") is False:
            failures.append(_failure(key, "freshness_passed_false", path))
    return failures


def _fingerprint_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": entry.get("key"),
        "kind": entry.get("kind"),
        "path": entry.get("path"),
        "exists": entry.get("exists"),
        "sha256": entry.get("sha256"),
        "summary": entry.get("summary"),
        "failures": entry.get("failures"),
    }


def _failure(key: str, reason: str, path: Path) -> dict[str, Any]:
    return {
        "key": key,
        "reason": reason,
        "path": str(path),
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a compact governance audit manifest")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON manifest output path")
    parser.add_argument("--fail-on-invalid", action="store_true", help="return 1 when required files are missing or malformed")
    parser.add_argument(
        "--public-snapshot",
        action="store_true",
        help="validate only reproducible files permitted in the public snapshot",
    )
    parser.add_argument("--print-json", action="store_true", help="print manifest JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    manifest = build_manifest(public_snapshot=args.public_snapshot)
    output_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            "Governance manifest: "
            f"{manifest['source_count']} sources, "
            f"{manifest['artifact_count']} artifacts, "
            f"valid={manifest['status']['valid']}, "
            f"fingerprint={manifest['audit_fingerprint'][:12]}"
        )
    if args.fail_on_invalid and not manifest["status"]["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
