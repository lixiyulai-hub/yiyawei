from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import time

from scripts.check_governance_artifact_freshness import ArtifactSpec, build_report, main
from scripts.governance_artifacts import sha256_file


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _touch(path, timestamp):
    os.utime(path, (timestamp, timestamp))


def test_artifact_freshness_passes_for_valid_recent_artifacts(tmp_path):
    source = tmp_path / "source.json"
    artifact = tmp_path / "artifact.json"
    source.write_text('[{"id":"one"}]\n', encoding="utf-8")
    _write_json(
        artifact,
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "samples_sha256": sha256_file(source),
        },
    )
    now_ts = time.time()
    _touch(source, now_ts - 10)
    _touch(artifact, now_ts)

    report = build_report(
        [
            ArtifactSpec(
                key="demo",
                path=artifact,
                sources=(source,),
                sha_field="samples_sha256",
                sha_source=source,
            )
        ],
        max_age_hours=1,
    )

    assert report["status"]["passed"] is True
    assert report["failures"] == []


def test_artifact_freshness_fails_when_required_artifact_missing(tmp_path):
    source = tmp_path / "source.json"
    artifact = tmp_path / "missing.json"
    source.write_text("[]\n", encoding="utf-8")

    report = build_report([ArtifactSpec("demo", artifact, (source,))])

    assert report["status"]["passed"] is False
    assert report["failures"][0]["reason"] == "missing_artifact"


def test_artifact_freshness_warns_when_optional_artifact_missing(tmp_path):
    source = tmp_path / "source.json"
    artifact = tmp_path / "missing.json"
    source.write_text("[]\n", encoding="utf-8")

    report = build_report([ArtifactSpec("demo", artifact, (source,), required=False)])

    assert report["status"]["passed"] is True
    assert report["failures"] == []
    assert report["warnings"][0]["reason"] == "missing_optional_artifact"


def test_artifact_freshness_fails_when_report_older_than_source(tmp_path):
    source = tmp_path / "source.json"
    artifact = tmp_path / "artifact.json"
    source.write_text("[]\n", encoding="utf-8")
    _write_json(
        artifact,
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    now_ts = time.time()
    _touch(artifact, now_ts - 20)
    _touch(source, now_ts)

    report = build_report([ArtifactSpec("demo", artifact, (source,))])

    assert any(item["reason"] == "artifact_older_than_source" for item in report["failures"])


def test_artifact_freshness_fails_on_malformed_json(tmp_path):
    source = tmp_path / "source.json"
    artifact = tmp_path / "artifact.json"
    source.write_text("[]\n", encoding="utf-8")
    artifact.write_text("{bad json}\n", encoding="utf-8")

    report = build_report([ArtifactSpec("demo", artifact, (source,))])

    assert report["status"]["passed"] is False
    assert report["failures"][0]["reason"] == "malformed_json"


def test_artifact_freshness_fails_when_generated_at_exceeds_max_age(tmp_path):
    source = tmp_path / "source.json"
    artifact = tmp_path / "artifact.json"
    source.write_text("[]\n", encoding="utf-8")
    old_time = datetime.now(timezone.utc) - timedelta(hours=5)
    _write_json(
        artifact,
        {
            "schema_version": 1,
            "generated_at": old_time.isoformat(timespec="seconds"),
        },
    )
    now_ts = time.time()
    _touch(source, now_ts - 10)
    _touch(artifact, now_ts)

    report = build_report([ArtifactSpec("demo", artifact, (source,))], max_age_hours=1)

    assert any(item["reason"] == "generated_at_exceeds_max_age" for item in report["failures"])


def test_artifact_freshness_cli_supports_path_overrides(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    hot_samples = tmp_path / "hot_samples.json"
    history = tmp_path / "history.jsonl"
    fake_samples = tmp_path / "fake_samples.json"
    failed_cases = tmp_path / "failed_cases.json"
    coverage = tmp_path / "coverage.json"
    boundary = tmp_path / "boundary.json"
    hot_report = tmp_path / "hot_report.json"
    trends = tmp_path / "trends.json"
    fake_report = tmp_path / "fake_report.json"
    real_samples = tmp_path / "real_samples.json"
    real_report = tmp_path / "missing_real_report.json"
    asr_cases = tmp_path / "asr_cases.json"
    asr_report = tmp_path / "missing_asr_report.json"
    project_terms = tmp_path / "project_terms.json"
    project_terms_report = tmp_path / "missing_project_terms_report.json"
    plugin_poc_report = tmp_path / "missing_plugin_poc_report.json"
    pyinstaller_spec = tmp_path / "VoicePromptCompiler.spec"
    pyinstaller_report = tmp_path / "missing_pyinstaller_report.json"
    failed_candidates = tmp_path / "failed_candidates.json"
    intake_package = tmp_path / "intake_package.json"
    promotion_draft = tmp_path / "promotion_draft.json"
    governance_manifest = tmp_path / "governance_manifest.json"
    out_path = tmp_path / "freshness.json"

    for source in (route_samples, hot_samples, fake_samples, real_samples, asr_cases, failed_cases):
        source.write_text("[]\n", encoding="utf-8")
    project_terms.write_text('{"schema_version":1,"terms":[]}\n', encoding="utf-8")
    pyinstaller_spec.write_text('a = Analysis(["app.py"])\n', encoding="utf-8")
    history.write_text('{"samples_sha256":"sample-sha"}\n', encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_json(coverage, {"schema_version": 1, "generated_at": now, "samples_sha256": sha256_file(route_samples)})
    _write_json(boundary, {"schema_version": 1, "generated_at": now, "samples_sha256": sha256_file(route_samples)})
    _write_json(hot_report, {"schema_version": 1, "generated_at": now, "samples_sha256": sha256_file(hot_samples)})
    _write_json(trends, {"schema_version": 1, "generated_at": now, "history_sha256": sha256_file(history)})
    _write_json(fake_report, {"schema_version": 1, "generated_at": now, "samples_sha256": sha256_file(fake_samples)})
    _write_json(failed_candidates, {"schema_version": 1, "generated_at": now, "cases_sha256": sha256_file(failed_cases)})
    _write_json(intake_package, {"schema_version": 1, "generated_at": now, "reviewed_samples_sha256": sha256_file(route_samples)})
    _write_json(promotion_draft, {"schema_version": 1, "generated_at": now, "intake_package_sha256": sha256_file(intake_package)})
    _write_json(governance_manifest, {"schema_version": 1, "generated_at": now})
    now_ts = time.time()
    for source in (route_samples, hot_samples, history, fake_samples, real_samples, asr_cases, project_terms, pyinstaller_spec, failed_cases):
        _touch(source, now_ts - 10)
    for artifact in (coverage, boundary, hot_report, trends, fake_report, failed_candidates, intake_package, promotion_draft, governance_manifest):
        _touch(artifact, now_ts)

    exit_code = main(
        [
            "--coverage-report",
            str(coverage),
            "--boundary-report",
            str(boundary),
            "--hot-path-report",
            str(hot_report),
            "--trend-report",
            str(trends),
            "--fake-llm-report",
            str(fake_report),
            "--real-llm-report",
            str(real_report),
            "--asr-manual-evidence",
            str(asr_report),
            "--plugin-poc-preflight",
            str(plugin_poc_report),
            "--project-terms-scan",
            str(project_terms_report),
            "--pyinstaller-readiness",
            str(pyinstaller_report),
            "--failed-utterance-candidates",
            str(failed_candidates),
            "--intake-package",
            str(intake_package),
            "--promotion-draft",
            str(promotion_draft),
            "--governance-manifest",
            str(governance_manifest),
            "--package-preflight",
            str(tmp_path / "missing_package_preflight.json"),
            "--bridge-smoke-evidence",
            str(tmp_path / "missing_bridge_smoke_evidence.json"),
            "--route-samples",
            str(route_samples),
            "--hot-path-samples",
            str(hot_samples),
            "--history",
            str(history),
            "--fake-llm-samples",
            str(fake_samples),
            "--real-llm-samples",
            str(real_samples),
            "--asr-cases",
            str(asr_cases),
            "--project-terms",
            str(project_terms),
            "--pyinstaller-spec",
            str(pyinstaller_spec),
            "--failed-utterance-cases",
            str(failed_cases),
            "--out",
            str(out_path),
            "--fail-on-stale",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["passed"] is True
    assert data["artifact_count"] == 16
    assert data["status"]["warning_count"] == 7


def test_artifact_freshness_fails_on_promotion_draft_intake_hash_mismatch(tmp_path):
    intake = tmp_path / "intake.json"
    promotion = tmp_path / "promotion.json"
    intake.write_text('{"ok": true}\n', encoding="utf-8")
    _write_json(
        promotion,
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "intake_package_sha256": "wrong-sha",
        },
    )

    report = build_report(
        [
            ArtifactSpec(
                key="promotion",
                path=promotion,
                sources=(intake,),
                sha_field="intake_package_sha256",
                sha_source=intake,
            )
        ]
    )

    assert report["status"]["passed"] is False
    assert report["failures"][0]["reason"] == "source_sha256_mismatch"
