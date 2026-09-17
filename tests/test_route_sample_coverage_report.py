from __future__ import annotations

import hashlib
import json

from scripts.report_route_sample_coverage import build_report, main


def test_route_sample_coverage_report_counts_tasks_and_domains(tmp_path):
    samples = tmp_path / "route_samples.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "bug",
                    "input": "bug",
                    "expected_task_type": "bug_report",
                    "expected_domain": "general",
                },
                {
                    "id": "ui",
                    "input": "ui",
                    "expected_task_type": "ui_ux_design",
                    "expected_domain": "saas",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_report(samples, target_per_task=2, target_per_domain=1)

    assert report["sample_count"] == 2
    assert report["script_name"] == "scripts/report_route_sample_coverage.py"
    assert report["artifact_version"] == 1
    assert report["samples_sha256"] == hashlib.sha256(samples.read_bytes()).hexdigest()
    assert report["by_task"]["bug_report"]["count"] == 1
    assert report["by_task"]["bug_report"]["gap"] == 1
    assert report["by_task"]["ui_ux_design"]["count"] == 1
    assert report["by_domain"]["general"]["count"] == 1
    assert report["by_domain"]["saas"]["count"] == 1
    assert "business_analysis" in report["missing_task_types"]
    assert "healthcare" in report["missing_domains"]
    assert {"task_type": "bug_report", "count": 1, "target": 2, "gap": 1} in report["task_target_gaps"]
    assert report["status"]["has_missing_buckets"] is True
    assert report["status"]["meets_target_depth"] is False
    assert report["invalid_items"] == []
    assert report["duplicate_items"] == []


def test_route_sample_coverage_report_hashes_raw_bytes_for_crlf_files(tmp_path):
    samples = tmp_path / "route_samples.json"
    payload = json.dumps(
        [
            {
                "id": "generic",
                "input": "hello",
                "expected_task_type": "generic_task",
                "expected_domain": "general",
            }
        ],
        ensure_ascii=False,
        indent=2,
    ).replace("\n", "\r\n")
    samples.write_bytes(payload.encode("utf-8"))

    report = build_report(samples, target_per_task=1, target_per_domain=1)

    byte_hash = hashlib.sha256(samples.read_bytes()).hexdigest()
    text_hash = hashlib.sha256(samples.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    assert report["samples_sha256"] == byte_hash
    assert report["samples_sha256"] != text_hash


def test_route_sample_coverage_cli_writes_report(tmp_path):
    samples = tmp_path / "route_samples.json"
    out_path = tmp_path / "coverage.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "generic",
                    "input": "hello",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(["--samples", str(samples), "--out", str(out_path)])

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["sample_count"] == 1
    assert data["by_task"]["generic_task"]["count"] == 1


def test_route_sample_coverage_report_detects_duplicates_and_invalid_items(tmp_path):
    samples = tmp_path / "route_samples.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "dup",
                    "input": "same",
                    "expected_task_type": "bug_report",
                    "expected_domain": "general",
                },
                {
                    "id": "dup",
                    "input": "same",
                    "expected_task_type": "unknown",
                    "expected_domain": "missing",
                },
                {
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_report(samples, target_per_task=1, target_per_domain=1)

    assert report["status"]["valid"] is False
    assert any(item["reason"] == "duplicate_id" for item in report["duplicate_items"])
    assert any(item["reason"] == "duplicate_input" for item in report["duplicate_items"])
    assert any(item["reason"] == "unknown_task_type" for item in report["invalid_items"])
    assert any(item["reason"] == "unknown_domain" for item in report["invalid_items"])
    assert any(item["reason"] == "missing_id" for item in report["invalid_items"])
    assert any(item["reason"] == "missing_input" for item in report["invalid_items"])


def test_route_sample_coverage_cli_can_fail_on_invalid_missing_and_target_gap(tmp_path):
    samples = tmp_path / "route_samples.json"
    out_path = tmp_path / "coverage.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "generic",
                    "input": "hello",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["--samples", str(samples), "--out", str(out_path), "--fail-on-missing"]) == 1
    assert main(["--samples", str(samples), "--out", str(out_path), "--fail-on-target-gap"]) == 1
    assert main(["--samples", str(samples), "--out", str(out_path), "--fail-on-invalid"]) == 0
