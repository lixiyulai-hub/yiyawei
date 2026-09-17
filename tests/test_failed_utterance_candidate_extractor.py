from __future__ import annotations

import json
from pathlib import Path

from scripts.extract_failed_utterance_candidates import build_report, main
from scripts.governance_artifacts import sha256_file


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _case(case_id: str, **extra):
    item = {
        "id": case_id,
        "source": "manual-test",
        "raw_asr_text": "帮我润色这句普通短句，不要扩写：今天会议我可能晚十分钟到。",
        "wrong_final_text": "请制定一个大型项目方案。",
        "expected_task_type": "text_polishing",
        "expected_domain": "general",
        "observed_task_type": "project_evaluation",
        "observed_domain": "general",
        "failure_modes": ["text_polishing_over_expansion"],
        "severity": "high",
        "review_status": "accepted_to_backlog",
        "redaction_status": "no_sensitive_data",
        "contains_sensitive_data": False,
        "hot_path_allowed": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "suggested_route_sample": {
            "id": f"{case_id}_sample",
            "spoken_type": "普通润色负样本",
            "input": "帮我润色这句普通短句，不要扩写：今天会议我可能晚十分钟到。",
            "expected_task_type": "text_polishing",
            "expected_domain": "general",
            "output_shape": ["保留原意", "不新增事实"],
            "must_keep": ["晚十分钟到", "不要扩写"],
            "must_drop": ["项目方案"],
        },
    }
    item.update(extra)
    return item


def test_build_report_generates_review_only_candidates_with_provenance(tmp_path):
    cases = tmp_path / "failed_cases.json"
    _write_json(
        cases,
        {
            "schema_version": 1,
            "runtime_hot_path_used": False,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "cases": [_case("failed_text_polishing_case")],
        },
    )

    report = build_report(cases)

    assert report["schema_version"] == 1
    assert report["artifact_version"] == 1
    assert report["runtime_hot_path_used"] is False
    assert report["network_used"] is False
    assert report["repo_clone_or_download_used"] is False
    assert report["cases_sha256"] == sha256_file(cases)
    assert report["case_count"] == 1
    assert report["candidate_count"] == 1
    assert report["status"]["ready_for_review"] is True
    candidate = report["candidates"][0]
    assert candidate["candidate_id"] == "failed_text_polishing_case"
    assert candidate["review_status"] == "review_only"
    assert candidate["case_review_status"] == "accepted_to_backlog"
    assert candidate["hot_path_allowed"] is False
    assert candidate["expected_task_type"] == "text_polishing"
    assert candidate["current_task_type"] == "project_evaluation"
    assert candidate["source"]["case_id"] == "failed_text_polishing_case"
    assert "text_polishing_over_expansion" in candidate["failure"]["failure_modes"]


def test_build_report_redacts_sensitive_text_and_can_fail_unredacted_sensitive(tmp_path):
    cases = tmp_path / "failed_cases.json"
    test_api_key = "sk-" + "test-placeholder-value"
    test_phone = "138" + "00000000"
    _write_json(
        cases,
        {
            "cases": [
                _case(
                    "failed_secret_case",
                    raw_asr_text=f"把 api_key={test_api_key} 写到日志里，手机号 {test_phone} 也带上。",
                    wrong_final_text=f"请记录 api_key={test_api_key}。",
                    expected_task_type="generic_task",
                    redaction_status="raw",
                    contains_sensitive_data=True,
                    suggested_route_sample={
                        "id": "failed_secret_case_sample",
                        "input": f"把 api_key={test_api_key} 写到日志里，手机号 {test_phone} 也带上。",
                        "expected_task_type": "generic_task",
                        "expected_domain": "general",
                        "must_keep": [f"api_key={test_api_key}", test_phone],
                        "must_drop": ["直接写日志"],
                    },
                )
            ]
        },
    )

    report = build_report(cases)

    candidate = report["candidates"][0]
    serialized = json.dumps(candidate, ensure_ascii=False)
    assert test_api_key not in serialized
    assert test_phone not in serialized
    assert "<SECRET>" in serialized or "<API_KEY>" in serialized
    assert "<PHONE>" in serialized
    assert report["redaction"]["redacted_count"] >= 2
    assert report["redaction"]["unredacted_sensitive_count"] == 1
    assert report["status"]["valid"] is False

    out_path = tmp_path / "candidates.json"
    exit_code = main(
        [
            "--cases",
            str(cases),
            "--out",
            str(out_path),
            "--fail-on-unredacted-sensitive",
        ]
    )
    assert exit_code == 1


def test_cli_writes_candidate_artifact_without_modifying_cases(tmp_path):
    cases = tmp_path / "failed_cases.json"
    out_path = tmp_path / "failed_candidates.json"
    _write_json(cases, {"cases": [_case("failed_cli_case")]})
    original = cases.read_text(encoding="utf-8")

    exit_code = main(["--cases", str(cases), "--out", str(out_path), "--fail-on-invalid"])

    assert exit_code == 0
    assert cases.read_text(encoding="utf-8") == original
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["candidate_count"] == 1
    assert data["candidates"][0]["candidate_id"] == "failed_cli_case"


def test_invalid_cases_and_duplicates_are_reported(tmp_path):
    cases = tmp_path / "failed_cases.json"
    _write_json(
        cases,
        {
            "cases": [
                _case("duplicate_case"),
                _case("duplicate_case"),
                {"id": "missing_route", "raw_asr_text": "只有原始语音"},
                _case("unsafe_case", hot_path_allowed=True),
            ]
        },
    )

    report = build_report(cases)

    assert report["status"]["valid"] is False
    assert any(item["reason"] == "duplicate_candidate_id" for item in report["duplicate_items"])
    reasons = {item["reason"] for item in report["invalid_items"]}
    assert "missing_expected_task_type" in reasons
    assert "missing_expected_domain" in reasons
    assert "case_hot_path_allowed" in reasons
    assert report["status"]["runtime_isolated"] is False


def test_extractor_helper_stays_offline_static():
    text = Path("scripts/extract_failed_utterance_candidates.py").read_text(encoding="utf-8")

    forbidden = ("requests", "urllib", "socket", "subprocess", "git ", "OpenAI(", "httpx")
    assert all(pattern not in text for pattern in forbidden)
