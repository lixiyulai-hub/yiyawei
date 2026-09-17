from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.benchmark_processor_fake_llm import (
    BenchmarkSample,
    evaluate_invariants,
    load_samples,
    main,
    run_benchmark,
)


def test_run_benchmark_reports_processor_fake_llm_schema():
    samples = [
        BenchmarkSample(
            sample_id="revision",
            text="我想让你帮我做一个对标美图秀秀的网站，先看他们的网站再执行我们自己网站的任务。",
            fake_behavior="internal_prompt_leak_then_rewrite",
            fake_final_text="请帮我做一个对标美图秀秀的网站。先分析它的页面结构，再执行我们自己网站的任务。",
        ),
        BenchmarkSample(
            sample_id="fallback",
            text="今天把中文口语重复表达这块口内容整理成合适的粘贴到chartGPT Claude Gemini Cursor VS Code 的终端输入框的专业文本不是普通语音转文字，而是机器人，不是机器人聊天，不是代码生成器。",
            fake_behavior="always_echo",
        ),
        BenchmarkSample(
            sample_id="risk",
            text="请帮我删除 node_modules 然后重新安装依赖，但先列出需要我确认的风险。",
            fake_behavior="risk_medium",
        ),
    ]

    report = run_benchmark(samples, iterations=2, warmup=0)

    assert report["schema_version"] == 1
    assert report["benchmark"]["sample_count"] == 3
    assert report["benchmark"]["run_count"] == 6
    assert report["benchmark"]["local_only"] is True
    assert report["benchmark"]["network_allowed"] is False
    assert report["benchmark"]["github_scan_allowed"] is False
    assert report["benchmark"]["obsidian_scan_allowed"] is False
    assert report["benchmark"]["asr_enabled"] is False
    assert report["benchmark"]["llm_enabled"] is False
    assert report["benchmark"]["real_llm_enabled"] is False
    assert report["benchmark"]["fake_llm_enabled"] is True
    assert report["benchmark"]["deterministic_fake_llm"] is True

    summary = report["summary"]
    assert summary["processor_ms"]["count"] == 6
    assert summary["llm_calls"]["count"] == 6
    assert summary["debug_counters"]["revision_attempted_count"] >= 2
    assert summary["debug_counters"]["revision_applied_count"] >= 2
    assert summary["debug_counters"]["rule_task_fallback_used_count"] >= 2
    assert summary["debug_counters"]["orchestration_escalation_count"] >= 4
    assert summary["result_counters"]["need_confirm_count"] >= 2
    assert summary["result_counters"]["medium_risk_count"] >= 2
    assert "quality_gate_reason_counts" in summary
    assert "invariants" in report
    assert len(report["per_sample"]) == 3

    fallback = next(item for item in report["per_sample"] if item["id"] == "fallback")
    assert fallback["debug_counters"]["rule_task_fallback_used_count"] == 2


def test_repository_processor_fake_llm_samples_cover_orchestration_matrix():
    samples = load_samples(Path("data/processor_fake_llm_benchmark_samples.json"))

    report = run_benchmark(samples, iterations=2, warmup=0)

    assert report["benchmark"]["sample_count"] == 24
    assert report["benchmark"]["run_count"] == 48
    summary = report["summary"]
    assert summary["debug_counters"]["revision_attempted_count"] >= 10
    assert summary["debug_counters"]["revision_applied_count"] >= 6
    assert summary["debug_counters"]["fast_revision_applied_count"] >= 2
    assert summary["debug_counters"]["rule_task_fallback_used_count"] >= 6
    assert summary["result_counters"]["need_confirm_count"] >= 2
    assert summary["result_counters"]["medium_risk_count"] >= 2
    assert summary["result_counters"]["high_risk_count"] >= 2
    assert summary["result_counters"]["rule_task_fallback_uncertain_count"] >= 6
    assert summary["result_counters"]["quality_plain_text_fallback_count"] >= 2
    assert "project_evaluation:ai_tool" in summary["route_counts"]
    assert "visual_generation:ai_tool" in summary["route_counts"]
    assert "presentation_deck:ecommerce" in summary["route_counts"]
    assert "text_polishing:general" in summary["route_counts"]
    assert "generic_task:general" in summary["route_counts"]
    assert report["invariants"]["passed"] is True

    by_id = {item["id"]: item for item in report["per_sample"]}
    assert by_id["risk_high_privacy_secret"]["result_counters"]["high_risk_count"] == 2
    assert by_id["fast_revision_success"]["debug_counters"]["fast_revision_applied_count"] == 2
    assert (
        by_id["text_polishing_misroute_guard"]["debug_counters"][
            "rule_task_fallback_used_count"
        ]
        == 2
    )
    assert (
        by_id["thin_project_evaluation_fallback"]["debug_counters"][
            "rule_task_fallback_used_count"
        ]
        == 2
    )
    assert by_id["thin_project_evaluation_fallback"]["route"]["task_type"] == "project_evaluation"
    assert by_id["thin_project_evaluation_fallback"]["route"]["domain"] == "ai_tool"
    assert by_id["smalltalk_misroute_guard"]["route"]["task_type"] == "generic_task"
    assert by_id["smalltalk_misroute_guard"]["route"]["domain"] == "general"
    assert (
        by_id["smalltalk_misroute_guard"]["result_counters"]["quality_plain_text_fallback_count"]
        == 2
    )
    assert by_id["risk_high_destructive_sql"]["result_counters"]["high_risk_count"] == 2
    assert by_id["safe_finance_explanation_counterexample"]["result_counters"]["need_confirm_count"] == 0
    assert by_id["risk_high_prisma_reset"]["result_counters"]["high_risk_count"] == 2
    assert by_id["risk_high_db_role_update"]["result_counters"]["high_risk_count"] == 2
    assert by_id["risk_medium_child_medication"]["result_counters"]["medium_risk_count"] == 2
    assert by_id["risk_medium_loan_fund_advice"]["result_counters"]["medium_risk_count"] == 2
    assert by_id["risk_high_crypto_transfer"]["result_counters"]["high_risk_count"] == 2
    assert by_id["risk_medium_medical_overdose_adult"]["result_counters"]["medium_risk_count"] == 2
    assert by_id["risk_medium_acute_chest_pain"]["result_counters"]["medium_risk_count"] == 2
    assert by_id["risk_high_payment_withdraw_bypass"]["result_counters"]["high_risk_count"] == 2
    assert by_id["risk_high_privacy_csv_group_export"]["result_counters"]["high_risk_count"] == 2
    assert by_id["safe_crypto_transfer_checklist"]["result_counters"]["need_confirm_count"] == 0
    assert by_id["safe_destructive_command_explanation"]["result_counters"]["need_confirm_count"] == 0


def test_processor_fake_llm_invariants_report_failures_for_drift():
    report = run_benchmark(
        [
            BenchmarkSample(
                sample_id="clean_task",
                text="请检查登录接口报错。",
                fake_behavior="clean_rewrite",
            )
        ],
        iterations=1,
        warmup=0,
    )

    invariants = evaluate_invariants(report)

    assert invariants["passed"] is False
    assert any(item["type"] == "missing_required_samples" for item in invariants["failures"])


def test_processor_fake_llm_benchmark_cli_writes_report(tmp_path):
    samples_path = tmp_path / "samples.json"
    out_path = tmp_path / "processor_fake_llm_benchmark.json"
    samples_path.write_text(
        json.dumps(
            [
                {
                    "id": "one",
                    "input": "请检查登录接口报错，先定位原因，不要直接改代码。",
                    "fake_behavior": "clean_rewrite",
                    "fake_final_text": "请检查登录接口报错。先定位原因，不要直接改代码。",
                },
                {
                    "id": "two",
                    "input": "请帮我删除 node_modules 然后重新安装依赖，但先列出需要我确认的风险。",
                    "fake_behavior": "risk_medium",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--samples",
            str(samples_path),
            "--out",
            str(out_path),
            "--iterations",
            "1",
            "--warmup",
            "0",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["samples_path"] == str(samples_path)
    assert data["sample_source"] == "file"
    assert data["samples_sha256"] == hashlib.sha256(samples_path.read_bytes()).hexdigest()
    assert data["script_name"] == "scripts/benchmark_processor_fake_llm.py"
    assert data["artifact_version"] == 1
    assert data["samples_path_missing"] is False
    assert data["benchmark"]["sample_count"] == 2
    assert data["benchmark"]["run_count"] == 2
    assert data["summary"]["result_counters"]["need_confirm_count"] >= 1


def test_processor_fake_llm_benchmark_marks_builtin_sample_source(tmp_path):
    missing_samples = tmp_path / "missing.json"
    out_path = tmp_path / "processor_fake_llm_benchmark.json"

    exit_code = main(
        [
            "--samples",
            str(missing_samples),
            "--out",
            str(out_path),
            "--iterations",
            "1",
            "--warmup",
            "0",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["samples_path"] == "built-in"
    assert data["sample_source"] == "built_in"
    assert data["samples_path_missing"] is True
    assert isinstance(data["samples_sha256"], str)
    assert len(data["samples_sha256"]) == 64


def test_processor_fake_llm_benchmark_cli_can_fail_on_invariants(tmp_path):
    samples_path = tmp_path / "samples.json"
    out_path = tmp_path / "processor_fake_llm_benchmark.json"
    samples_path.write_text(
        json.dumps(
            [
                {
                    "id": "clean_task",
                    "input": "请检查登录接口报错。",
                    "fake_behavior": "clean_rewrite",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--samples",
            str(samples_path),
            "--out",
            str(out_path),
            "--iterations",
            "1",
            "--warmup",
            "0",
            "--fail-on-invariants",
        ]
    )

    assert exit_code == 1
