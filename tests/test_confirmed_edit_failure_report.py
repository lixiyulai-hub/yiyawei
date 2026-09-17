from __future__ import annotations

import json
from pathlib import Path

from scripts.report_confirmed_edit_failures import build_report, main
from src.storage.db import SessionStorage


def _seed_storage(db_path: Path) -> SessionStorage:
    storage = SessionStorage(db_path)
    storage.save_confirmed_edit(
        session_id=1,
        source_kind="asr_text",
        before_text="请用EMG二点零生成图",
        after_text="请用image 2.0生成图",
        metadata={"debug": {"raw_asr_text": "请用EMG二点零生成图", "cleaned_text": "请用EMG二点零生成图"}},
    )
    storage.save_confirmed_edit(
        session_id=2,
        source_kind="final_output",
        before_text="task_type=visual_generation\nroute_context: 任务路由与模板参考",
        after_text="请生成一条面向 image 2.0 的用户可见作图提示词。",
        metadata={
            "debug": {
                "raw_asr_text": "帮我生成一张电商主图",
                "cleaned_text": "帮我生成一张电商主图",
                "final_text": "task_type=visual_generation\nroute_context: 任务路由与模板参考",
                "route": {"task_type": "visual_generation", "domain": "ai_tool"},
                "intent_frame": {"task_hint": "visual_generation", "artifact_type": "image_prompt"},
                "quality_gate_attribution": {
                    "reason": "internal_prompt_leak",
                    "stage": "prompt_leak_guard",
                    "origin": "llm_internal_template_or_schema_leak",
                },
            }
        },
    )
    storage.save_confirmed_edit(
        session_id=3,
        source_kind="final_output",
        before_text="你好世界",
        after_text="你好，世界。",
        metadata={"debug": {"raw_asr_text": "你好世界", "cleaned_text": "你好世界", "final_text": "你好世界"}},
    )
    return storage


def test_confirmed_edit_failure_report_summarizes_and_builds_candidates(tmp_path):
    db_path = tmp_path / "sessions.db"
    _seed_storage(db_path)

    report = build_report(db_path)

    assert report["schema_version"] == 1
    assert report["runtime_hot_path_used"] is False
    assert report["network_used"] is False
    assert report["repo_clone_or_download_used"] is False
    assert report["db_exists"] is True
    assert report["status"]["ready_for_review"] is True
    assert report["filtered_count"] == 3
    assert report["by_failure_type"]["asr_term_error"] == 1
    assert report["by_failure_type"]["compiler_template_leak"] == 1
    assert report["by_failure_type"]["punctuation_or_wording"] == 1
    assert report["regression_candidate_count"] == 2

    candidate = next(
        item
        for item in report["regression_candidates"]
        if item["failure"]["failure_type"] == "compiler_template_leak"
    )
    assert candidate["review_status"] == "review_only"
    assert candidate["hot_path_allowed"] is False
    assert candidate["network_used"] is False
    assert candidate["expected_task_type"] == "visual_generation"
    assert candidate["expected_domain"] == "ai_tool"
    assert "task_type=" in candidate["suggested_route_sample"]["must_drop"]
    assert "processor_quality_gate" in candidate["suggested_regression_case"]["recommended_test_layers"]


def test_confirmed_edit_failure_report_filters_regression_only(tmp_path):
    db_path = tmp_path / "sessions.db"
    _seed_storage(db_path)

    report = build_report(db_path, regression_only=True, failure_types={"asr_term_error"})

    assert report["filtered_count"] == 1
    assert report["items"][0]["inferred_failure_type"] == "asr_term_error"
    assert report["regression_candidate_count"] == 1
    assert report["regression_candidates"][0]["suggested_route_sample"]["must_keep"] == ["image 2.0"]


def test_confirmed_edit_failure_report_redacts_sensitive_text(tmp_path):
    db_path = tmp_path / "sessions.db"
    test_api_key = "sk-" + "test-placeholder-value"
    test_phone = "138" + "00000000"
    storage = SessionStorage(db_path)
    storage.save_confirmed_edit(
        session_id=4,
        source_kind="final_output",
        before_text=f"请记录 api_key={test_api_key} 和手机号 {test_phone}",
        after_text=f"请不要记录 api_key={test_api_key} 和手机号 {test_phone}",
        metadata={
            "debug": {
                "raw_asr_text": f"请记录 api_key={test_api_key} 和手机号 {test_phone}",
                "cleaned_text": f"请记录 api_key={test_api_key} 和手机号 {test_phone}",
                "final_text": f"请记录 api_key={test_api_key} 和手机号 {test_phone}",
            }
        },
    )

    report = build_report(db_path)
    serialized = json.dumps(report, ensure_ascii=False)

    assert test_api_key not in serialized
    assert test_phone not in serialized
    assert "<SECRET>" in serialized or "<API_KEY>" in serialized
    assert "<PHONE>" in serialized
    assert report["redaction"]["redacted_count"] >= 2


def test_confirmed_edit_failure_report_cli_writes_output_and_handles_empty(tmp_path):
    db_path = tmp_path / "sessions.db"
    out_path = tmp_path / "report.json"
    _seed_storage(db_path)

    exit_code = main(["--db", str(db_path), "--out", str(out_path), "--regression-only"])

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["filtered_count"] == 2
    assert data["regression_candidate_count"] == 2

    empty_out = tmp_path / "empty.json"
    empty_exit = main(
        [
            "--db",
            str(db_path),
            "--out",
            str(empty_out),
            "--failure-type",
            "unknown",
            "--fail-on-empty",
        ]
    )

    assert empty_exit == 1
    assert json.loads(empty_out.read_text(encoding="utf-8"))["filtered_count"] == 0


def test_confirmed_edit_failure_report_missing_db_can_fail(tmp_path):
    missing = tmp_path / "missing.db"
    out_path = tmp_path / "missing_report.json"

    exit_code = main(["--db", str(missing), "--out", str(out_path), "--fail-on-missing-db"])

    assert exit_code == 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["db_exists"] is False
    assert data["status"]["ready_for_review"] is False


def test_confirmed_edit_failure_report_stays_offline_static():
    text = Path("scripts/report_confirmed_edit_failures.py").read_text(encoding="utf-8")

    forbidden = ("requests", "urllib", "socket", "subprocess", "git ", "OpenAI(", "httpx")
    assert all(pattern not in text for pattern in forbidden)
