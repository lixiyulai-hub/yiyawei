from __future__ import annotations

from datetime import datetime, timezone
import json

from scripts.build_governance_manifest import ManifestFileSpec, build_manifest, main
from scripts.governance_artifacts import sha256_file


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _artifact(path, *, script_name="script.py", status=None, **extra):
    payload = {
        "schema_version": 1,
        "artifact_version": 1,
        "script_name": script_name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if status is not None:
        payload["status"] = status
    payload.update(extra)
    _write_json(path, payload)


def test_manifest_summarizes_sources_artifacts_and_fingerprint(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    decisions = tmp_path / "decisions.json"
    coverage = tmp_path / "coverage.json"
    freshness = tmp_path / "freshness.json"
    route_samples.write_text('[{"id":"one"},{"id":"two"}]\n', encoding="utf-8")
    _write_json(decisions, {"schema_version": 1, "decisions": [{"candidate_id": "one", "review_status": "rejected"}]})
    _artifact(
        coverage,
        script_name="scripts/report_route_sample_coverage.py",
        status={"valid": True, "meets_target_depth": True},
        samples_sha256=sha256_file(route_samples),
        sample_count=2,
        by_task={"code_fix": {"count": 2, "target": 1, "gap": 0}},
        by_domain={"general": {"count": 2, "target": 1, "gap": 0}},
        task_target_gaps=[],
        domain_target_gaps=[],
    )
    _artifact(
        freshness,
        script_name="scripts/check_governance_artifact_freshness.py",
        status={"passed": True, "failure_count": 0, "warning_count": 0},
        artifact_count=1,
    )

    manifest = build_manifest(
        source_specs=[
            ManifestFileSpec("route_samples", route_samples, "source"),
            ManifestFileSpec("route_sample_candidate_review_decisions", decisions, "source"),
        ],
        artifact_specs=[
            ManifestFileSpec("route_sample_coverage", coverage, "artifact"),
            ManifestFileSpec("governance_artifact_freshness", freshness, "artifact"),
        ],
    )

    assert manifest["status"]["valid"] is True
    assert manifest["source_count"] == 2
    assert manifest["artifact_count"] == 2
    assert len(manifest["audit_fingerprint"]) == 64
    assert manifest["artifacts"][0]["summary"]["sample_count"] == 2
    assert "decisions" not in manifest["sources"][1]
    assert "items" not in manifest["sources"][0]


def test_manifest_fingerprint_changes_when_source_hash_changes(tmp_path):
    source = tmp_path / "source.json"
    artifact = tmp_path / "artifact.json"
    source.write_text('{"value": 1}\n', encoding="utf-8")
    _artifact(artifact, status={"passed": True})

    specs = [ManifestFileSpec("github_source_catalog", source, "source")]
    artifacts = [ManifestFileSpec("governance_artifact_freshness", artifact, "artifact")]
    first = build_manifest(specs, artifacts)
    source.write_text('{"value": 2}\n', encoding="utf-8")
    second = build_manifest(specs, artifacts)

    assert first["audit_fingerprint"] != second["audit_fingerprint"]
    assert first["source_fingerprint"] != second["source_fingerprint"]


def test_manifest_marks_missing_or_failed_governance_invalid(tmp_path):
    missing = tmp_path / "missing.json"
    candidate_status = tmp_path / "candidate_status.json"
    _artifact(
        candidate_status,
        script_name="scripts/report_candidate_review_status.py",
        status={"valid": True, "runtime_isolated": True},
        pending_count=1,
        candidate_count=1,
    )

    manifest = build_manifest(
        source_specs=[ManifestFileSpec("route_samples", missing, "source")],
        artifact_specs=[ManifestFileSpec("route_sample_candidate_review_status", candidate_status, "artifact")],
    )

    assert manifest["status"]["valid"] is False
    reasons = {failure["reason"] for failure in manifest["failures"]}
    assert "missing_required_file" in reasons
    assert "pending_candidates" in reasons


def test_manifest_allows_missing_optional_package_preflight(tmp_path):
    missing = tmp_path / "package_preflight.json"

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[ManifestFileSpec("package_preflight", missing, "artifact", required=False)],
    )

    assert manifest["status"]["valid"] is True
    assert manifest["artifact_count"] == 1
    assert manifest["artifacts"][0]["required"] is False
    assert manifest["artifacts"][0]["exists"] is False


def test_manifest_summarizes_failed_package_preflight(tmp_path):
    package_report = tmp_path / "package_preflight.json"
    _artifact(
        package_report,
        script_name="scripts/package_preflight.py",
        status={"passed": False, "valid": False, "error_count": 1, "warning_count": 2},
        summary={
            "check_count": 10,
            "ok_count": 7,
            "warning_count": 2,
            "error_count": 1,
            "required_dependency_count": 13,
        },
    )

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[ManifestFileSpec("package_preflight", package_report, "artifact", required=False)],
    )

    assert manifest["status"]["valid"] is False
    summary = manifest["artifacts"][0]["summary"]
    assert summary["check_count"] == 10
    assert summary["required_dependency_count"] == 13
    reasons = {failure["reason"] for failure in manifest["failures"]}
    assert "status_valid_false" in reasons
    assert "status_passed_false" in reasons


def test_manifest_allows_missing_optional_bridge_smoke_evidence(tmp_path):
    missing = tmp_path / "bridge_smoke_evidence.json"

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[ManifestFileSpec("bridge_smoke_evidence", missing, "artifact", required=False)],
    )

    assert manifest["status"]["valid"] is True
    assert manifest["artifacts"][0]["required"] is False
    assert manifest["artifacts"][0]["exists"] is False


def test_manifest_summarizes_failed_bridge_smoke_evidence(tmp_path):
    bridge_report = tmp_path / "bridge_smoke_evidence.json"
    _artifact(
        bridge_report,
        script_name="scripts/bridge_smoke_evidence.py",
        status={
            "passed": False,
            "valid": False,
            "runtime_isolated": True,
            "no_paste_confirmed": False,
            "error_count": 1,
            "warning_count": 0,
        },
        summary={"check_count": 11, "ok_count": 10, "warning_count": 0, "error_count": 1},
        local_http_used=True,
        live_app_used=False,
        source={"kind": "text"},
        bridge={"host": "127.0.0.1", "auth_required": True, "endpoint": "/v1/process-text", "mode": "cursor_prompt"},
        response_summary={
            "final_text_present": True,
            "risk_level": "low",
            "need_confirm": False,
            "pasted": True,
            "auto_paste_allowed": False,
        },
    )

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[ManifestFileSpec("bridge_smoke_evidence", bridge_report, "artifact", required=False)],
    )

    assert manifest["status"]["valid"] is False
    summary = manifest["artifacts"][0]["summary"]
    assert summary["check_count"] == 11
    assert summary["local_http_used"] is True
    assert summary["bridge"]["host"] == "127.0.0.1"
    assert summary["response"]["pasted"] is True
    reasons = {failure["reason"] for failure in manifest["failures"]}
    assert "status_valid_false" in reasons
    assert "status_passed_false" in reasons


def test_manifest_allows_missing_optional_real_llm_benchmark(tmp_path):
    missing = tmp_path / "processor_real_llm_benchmark.json"

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[ManifestFileSpec("processor_real_llm_benchmark", missing, "artifact", required=False)],
    )

    assert manifest["status"]["valid"] is True
    assert manifest["artifacts"][0]["required"] is False
    assert manifest["artifacts"][0]["exists"] is False


def test_manifest_summarizes_failed_real_llm_benchmark(tmp_path):
    real_report = tmp_path / "processor_real_llm_benchmark.json"
    _artifact(
        real_report,
        script_name="scripts/benchmark_processor_real_llm.py",
        status={"passed": False, "valid": False, "runtime_isolated": True, "failure_count": 1},
        real_llm_enabled=True,
        local_llm_http_used=True,
        external_llm_endpoint_used=False,
        skipped=False,
        benchmark={"sample_count": 1, "run_count": 1, "allow_live": True},
        config={"provider": "ollama", "model": "qwen"},
        summary={
            "sample_count": 1,
            "failure_count": 1,
            "passed_count": 0,
            "failed_count": 1,
            "revision_attempted_count": 0,
            "rule_task_fallback_used_count": 0,
            "high_risk_count": 0,
            "medium_risk_count": 0,
        },
        invariants={"passed": False, "failures": [{"sample_id": "one", "reason": "final_text_too_short"}]},
    )

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[ManifestFileSpec("processor_real_llm_benchmark", real_report, "artifact", required=False)],
    )

    assert manifest["status"]["valid"] is False
    summary = manifest["artifacts"][0]["summary"]
    assert summary["real_llm_enabled"] is True
    assert summary["local_llm_http_used"] is True
    assert summary["provider"] == "ollama"
    assert summary["summary"]["failure_count"] == 1
    reasons = {failure["reason"] for failure in manifest["failures"]}
    assert "status_valid_false" in reasons
    assert "status_passed_false" in reasons
    assert "invariants_passed_false" in reasons


def test_manifest_allows_missing_new_optional_receipts(tmp_path):
    specs = [
        ManifestFileSpec("asr_manual_evidence", tmp_path / "asr.json", "artifact", required=False),
        ManifestFileSpec("plugin_poc_preflight", tmp_path / "plugin.json", "artifact", required=False),
        ManifestFileSpec("project_terms_scan", tmp_path / "terms.json", "artifact", required=False),
        ManifestFileSpec("pyinstaller_readiness", tmp_path / "pyinstaller.json", "artifact", required=False),
        ManifestFileSpec("harness_governance_snapshot", tmp_path / "harness.json", "artifact", required=False),
    ]

    manifest = build_manifest(source_specs=[], artifact_specs=specs)

    assert manifest["status"]["valid"] is True
    assert manifest["artifact_count"] == 5
    assert all(not artifact["exists"] for artifact in manifest["artifacts"])


def test_manifest_summarizes_harness_governance_snapshot(tmp_path):
    harness_report = tmp_path / "harness.json"
    _artifact(
        harness_report,
        script_name="scripts/report_harness_governance.py",
        status={
            "valid": True,
            "runtime_isolated": True,
            "failure_count": 0,
            "contract_check_failed_count": 0,
            "runtime_reference_violation_count": 0,
        },
        source_count=5,
        source_fingerprint="a" * 64,
        audit_fingerprint="b" * 64,
        prompt_metrics={
            "SYSTEM_PROMPT": {"chars": 100},
            "FAST_SYSTEM_PROMPT": {"chars": 50},
            "total_chars": 150,
        },
        route_metrics={"task_definition_count": 11},
        quality_gate_metrics={
            "reason_literal_count": 20,
            "has_quality_gate_attribution": True,
            "has_internal_prompt_leak_guard": True,
        },
    )

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[
            ManifestFileSpec(
                "harness_governance_snapshot",
                harness_report,
                "artifact",
                required=False,
            )
        ],
    )

    assert manifest["status"]["valid"] is True
    summary = manifest["artifacts"][0]["summary"]
    assert summary["source_count"] == 5
    assert summary["prompt_chars"]["total"] == 150
    assert summary["route_metrics"]["task_definition_count"] == 11
    assert summary["quality_gate"]["reason_literal_count"] == 20
    assert summary["status"]["runtime_isolated"] is True


def test_manifest_summarizes_failed_new_optional_receipts(tmp_path):
    asr = tmp_path / "asr.json"
    plugin = tmp_path / "plugin.json"
    terms = tmp_path / "terms.json"
    pyinstaller = tmp_path / "pyinstaller.json"
    _artifact(asr, script_name="scripts/asr_manual_evidence.py", status={"passed": False, "valid": False}, live_asr_enabled=False, asr_engine_used=False, skipped=True, case_count=0, summary={"check_count": 1, "error_count": 1, "warning_count": 0, "wav_supplied": False})
    _artifact(plugin, script_name="scripts/plugin_poc_preflight.py", status={"passed": False, "valid": False}, summary={"check_count": 1, "error_count": 1, "warning_count": 0})
    _artifact(terms, script_name="scripts/scan_project_terms.py", status={"passed": False, "valid": False}, term_count=1, category_counts={"x": 1}, summary={"mention_file_count": 0, "error_count": 1, "warning_count": 0})
    _artifact(pyinstaller, script_name="scripts/pyinstaller_readiness.py", status={"passed": False, "valid": False}, build_executed=False, entrypoint="app.py", summary={"check_count": 1, "error_count": 1, "warning_count": 0})

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[
            ManifestFileSpec("asr_manual_evidence", asr, "artifact", required=False),
            ManifestFileSpec("plugin_poc_preflight", plugin, "artifact", required=False),
            ManifestFileSpec("project_terms_scan", terms, "artifact", required=False),
            ManifestFileSpec("pyinstaller_readiness", pyinstaller, "artifact", required=False),
        ],
    )

    assert manifest["status"]["valid"] is False
    reasons = {failure["reason"] for failure in manifest["failures"]}
    assert "status_valid_false" in reasons
    assert "status_passed_false" in reasons
    summaries = {artifact["key"]: artifact["summary"] for artifact in manifest["artifacts"]}
    assert summaries["asr_manual_evidence"]["skipped"] is True
    assert summaries["plugin_poc_preflight"]["error_count"] == 1
    assert summaries["project_terms_scan"]["term_count"] == 1
    assert summaries["pyinstaller_readiness"]["build_executed"] is False


def test_manifest_marks_route_coverage_target_gaps_invalid(tmp_path):
    coverage = tmp_path / "coverage.json"
    _artifact(
        coverage,
        script_name="scripts/report_route_sample_coverage.py",
        status={"valid": True, "has_missing_buckets": False, "meets_target_depth": False},
        task_target_gaps=[{"task_type": "bug_report", "gap": 1}],
        domain_target_gaps=[],
    )

    manifest = build_manifest(source_specs=[], artifact_specs=[ManifestFileSpec("route_sample_coverage", coverage, "artifact")])

    assert manifest["status"]["valid"] is False
    reasons = {failure["reason"] for failure in manifest["failures"]}
    assert "coverage_target_depth_not_met" in reasons
    assert "task_target_gaps" in reasons


def test_manifest_marks_hot_path_baseline_regression_invalid(tmp_path):
    hot_path = tmp_path / "hot_path.json"
    _artifact(
        hot_path,
        script_name="scripts/benchmark_hot_path.py",
        budget_pass=True,
        baseline_comparison={
            "passed": False,
            "warnings": [],
            "failures": [{"metric": "route_ms"}],
            "baseline_sample_count": 1,
            "current_sample_count": 1,
        },
        summary={"stage_ms": {"route_ms": {"p95": 10.0}}},
    )

    manifest = build_manifest(source_specs=[], artifact_specs=[ManifestFileSpec("hot_path_benchmark", hot_path, "artifact")])

    assert manifest["status"]["valid"] is False
    assert manifest["artifacts"][0]["summary"]["baseline_comparison"]["failure_count"] == 1
    assert {failure["reason"] for failure in manifest["failures"]} == {"baseline_passed_false"}


def test_manifest_marks_hot_path_trend_health_failures_invalid(tmp_path):
    trends = tmp_path / "trends.json"
    _artifact(
        trends,
        script_name="scripts/report_hot_path_trends.py",
        row_count=2,
        latest={"budget_pass": False, "baseline_pass": False},
        health={
            "latest_budget_pass": False,
            "latest_baseline_pass": False,
            "all_budget_pass": False,
            "all_baseline_pass": False,
        },
        governance={"unreviewed_route_removed_count": 1},
    )

    manifest = build_manifest(source_specs=[], artifact_specs=[ManifestFileSpec("hot_path_trends", trends, "artifact")])

    assert manifest["status"]["valid"] is False
    reasons = {failure["reason"] for failure in manifest["failures"]}
    assert "latest_budget_pass_false" in reasons
    assert "latest_baseline_pass_false" in reasons
    assert "all_budget_pass_false" in reasons
    assert "all_baseline_pass_false" in reasons
    assert "unreviewed_route_removed" in reasons


def test_manifest_summarizes_failed_utterance_candidates_and_redaction_failures(tmp_path):
    failed_candidates = tmp_path / "failed_candidates.json"
    _artifact(
        failed_candidates,
        script_name="scripts/extract_failed_utterance_candidates.py",
        candidate_count=2,
        case_count=2,
        by_failure_mode={"smalltalk_over_expansion": 1, "privacy_exfiltration": 1},
        redaction={
            "enabled": True,
            "max_text_chars": 500,
            "redacted_count": 3,
            "unredacted_sensitive_count": 1,
        },
        status={"valid": False, "runtime_isolated": True},
    )

    manifest = build_manifest(
        source_specs=[],
        artifact_specs=[
            ManifestFileSpec(
                "failed_utterance_route_sample_candidates",
                failed_candidates,
                "artifact",
            )
        ],
    )

    assert manifest["status"]["valid"] is False
    summary = manifest["artifacts"][0]["summary"]
    assert summary["candidate_count"] == 2
    assert summary["case_count"] == 2
    assert summary["redaction"]["unredacted_sensitive_count"] == 1
    reasons = {failure["reason"] for failure in manifest["failures"]}
    assert "status_valid_false" in reasons
    assert "failed_utterance_unredacted_sensitive" in reasons


def test_manifest_cli_writes_report(tmp_path):
    out_path = tmp_path / "manifest.json"

    exit_code = main(["--out", str(out_path), "--public-snapshot", "--fail-on-invalid"])

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["script_name"] == "scripts/build_governance_manifest.py"
    assert data["release_scope"] == "public_snapshot"
    assert data["artifact_count"] == 0
    assert data["status"]["valid"] is True
