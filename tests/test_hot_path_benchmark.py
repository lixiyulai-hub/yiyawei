from __future__ import annotations

import hashlib
import json

from scripts.benchmark_hot_path import (
    BenchmarkSample,
    append_history,
    compare_with_baseline,
    evaluate_size_budgets,
    main,
    run_benchmark,
)


def test_run_benchmark_reports_hot_path_schema():
    samples = [
        BenchmarkSample("short_plain_text", "Please polish this short sentence."),
        BenchmarkSample("risk_scan_sample", "Please remove node modules and reinstall."),
    ]

    report = run_benchmark(samples, iterations=2, warmup=0)

    assert report["schema_version"] == 1
    assert report["benchmark"]["sample_count"] == 2
    assert report["benchmark"]["run_count"] == 4
    assert report["benchmark"]["local_only"] is True
    assert report["benchmark"]["network_allowed"] is False
    assert report["benchmark"]["github_scan_allowed"] is False
    assert report["benchmark"]["obsidian_scan_allowed"] is False
    assert report["benchmark"]["asr_enabled"] is False
    assert report["benchmark"]["llm_enabled"] is False
    assert "budget_pass" in report
    assert "budgets_ms" in report
    assert "budget_results" in report
    assert "budgets_chars" in report
    assert "size_budget_results" in report

    summary = report["summary"]
    for metric in (
        "preprocess_ms",
        "risk_scan_ms",
        "route_ms",
        "context_build_ms",
        "fallback_ms",
        "quality_gate_ms",
    ):
        stats = summary["stage_ms"][metric]
        assert stats["count"] == 4
        assert {"min", "avg", "p50", "p95", "max", "total"} <= set(stats)

    for metric in ("default_non_llm_ms", "fallback_non_llm_ms"):
        stats = summary["path_ms"][metric]
        assert stats["count"] == 4
        assert stats["p95"] >= 0

    assert len(report["per_sample"]) == 2
    first = report["per_sample"][0]
    assert first["id"] == "short_plain_text"
    assert first["route"]["task_type"]
    assert first["route"]["domain"]
    assert "stage_ms" in first
    assert "path_ms" in first


def test_hot_path_benchmark_cli_writes_report(tmp_path):
    samples_path = tmp_path / "samples.json"
    out_path = tmp_path / "hot_path_report.json"
    samples_path.write_text(
        json.dumps(
            [
                {"id": "one", "input": "Please turn this into a concise note."},
                {"id": "two", "input": "Please check this bug before changing code."},
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
    assert data["script_name"] == "scripts/benchmark_hot_path.py"
    assert data["artifact_version"] == 1
    assert data["benchmark"]["sample_count"] == 2
    assert data["benchmark"]["run_count"] == 2
    assert len(data["per_sample"]) == 2
    assert data["budgets_chars"]["route_context_chars"] == 1200.0
    assert data["budgets_chars"]["fallback_chars"] == 1600.0


def test_compare_with_baseline_detects_regression():
    baseline = {
        "generated_at": "2026-06-14T00:00:00+00:00",
        "benchmark": {"sample_count": 2},
        "summary": {
            "stage_ms": {
                "preprocess_ms": {"p95": 1.0},
                "risk_scan_ms": {"p95": 1.0},
                "route_ms": {"p95": 4.0},
                "context_build_ms": {"p95": 1.0},
                "fallback_ms": {"p95": 1.0},
                "quality_gate_ms": {"p95": 1.0},
            },
            "path_ms": {
                "default_non_llm_ms": {"p95": 20.0},
                "fallback_non_llm_ms": {"p95": 20.0},
            },
            "size": {
                "input_chars": {"p95": 100.0},
                "cleaned_chars": {"p95": 100.0},
                "route_context_chars": {"p95": 500.0},
                "fallback_chars": {"p95": 500.0},
            },
        },
    }
    current = {
        "generated_at": "2026-06-14T01:00:00+00:00",
        "benchmark": {"sample_count": 3},
        "summary": {
            "stage_ms": {
                "preprocess_ms": {"p95": 1.0},
                "risk_scan_ms": {"p95": 1.0},
                "route_ms": {"p95": 6.0},
                "context_build_ms": {"p95": 1.0},
                "fallback_ms": {"p95": 1.0},
                "quality_gate_ms": {"p95": 1.0},
            },
            "path_ms": {
                "default_non_llm_ms": {"p95": 21.0},
                "fallback_non_llm_ms": {"p95": 20.0},
            },
            "size": {
                "input_chars": {"p95": 100.0},
                "cleaned_chars": {"p95": 100.0},
                "route_context_chars": {"p95": 760.0},
                "fallback_chars": {"p95": 500.0},
            },
        },
    }

    comparison = compare_with_baseline(current, baseline, min_abs_delta_ms=1.0)

    assert comparison["passed"] is False
    assert comparison["sample_count_delta"] == 1
    failed_metrics = {item["metric"] for item in comparison["failures"]}
    assert failed_metrics == {"route_ms", "route_context_chars"}


def test_compare_with_baseline_ignores_tiny_timing_noise_by_default():
    baseline = {
        "generated_at": "2026-06-14T00:00:00+00:00",
        "benchmark": {"sample_count": 2},
        "summary": {
            "stage_ms": {
                "preprocess_ms": {"p95": 1.0},
                "risk_scan_ms": {"p95": 1.0},
                "route_ms": {"p95": 4.0},
                "context_build_ms": {"p95": 1.0},
                "fallback_ms": {"p95": 1.0},
                "quality_gate_ms": {"p95": 1.0},
            },
            "path_ms": {
                "default_non_llm_ms": {"p95": 20.0},
                "fallback_non_llm_ms": {"p95": 20.0},
            },
            "size": {
                "input_chars": {"p95": 100.0},
                "cleaned_chars": {"p95": 100.0},
                "route_context_chars": {"p95": 500.0},
                "fallback_chars": {"p95": 500.0},
            },
        },
    }
    current = {
        "generated_at": "2026-06-14T01:00:00+00:00",
        "benchmark": {"sample_count": 2},
        "summary": {
            "stage_ms": {
                "preprocess_ms": {"p95": 1.0},
                "risk_scan_ms": {"p95": 1.0},
                "route_ms": {"p95": 6.0},
                "context_build_ms": {"p95": 1.0},
                "fallback_ms": {"p95": 1.0},
                "quality_gate_ms": {"p95": 1.0},
            },
            "path_ms": {
                "default_non_llm_ms": {"p95": 20.0},
                "fallback_non_llm_ms": {"p95": 20.0},
            },
            "size": {
                "input_chars": {"p95": 100.0},
                "cleaned_chars": {"p95": 100.0},
                "route_context_chars": {"p95": 760.0},
                "fallback_chars": {"p95": 500.0},
            },
        },
    }

    comparison = compare_with_baseline(current, baseline)

    assert comparison["passed"] is False
    failed_metrics = {item["metric"] for item in comparison["failures"]}
    assert failed_metrics == {"route_context_chars"}
    route_comparison = next(
        item for item in comparison["comparisons"] if item["metric"] == "route_ms"
    )
    assert route_comparison["status"] == "ok"
    assert comparison["min_abs_delta_ms"] == 5.0


def test_compare_with_baseline_fails_on_missing_compared_metrics():
    baseline = {
        "generated_at": "2026-06-14T00:00:00+00:00",
        "benchmark": {"sample_count": 2},
        "summary": {
            "stage_ms": {"route_ms": {"p95": 4.0}},
            "path_ms": {},
            "size": {},
        },
    }
    current = {
        "generated_at": "2026-06-14T01:00:00+00:00",
        "benchmark": {"sample_count": 2},
        "summary": {
            "stage_ms": {},
            "path_ms": {},
            "size": {},
        },
    }

    comparison = compare_with_baseline(current, baseline)

    assert comparison["passed"] is False
    assert any(item["status"] == "missing_metric" for item in comparison["failures"])


def test_size_budget_detects_prompt_context_growth():
    summary = {
        "size": {
            "route_context_chars": {"p95": 1400.0},
            "fallback_chars": {"p95": 900.0},
        }
    }

    result = evaluate_size_budgets(summary, {"route_context_chars": 1200.0, "fallback_chars": 1600.0})

    assert result["passed"] is False
    assert result["failures"] == [
        {
            "metric": "route_context_chars",
            "budget_chars": 1200.0,
            "actual_p95_chars": 1400.0,
        }
    ]


def test_hot_path_benchmark_cli_appends_history(tmp_path):
    samples_path = tmp_path / "samples.json"
    out_path = tmp_path / "hot_path_report.json"
    history_path = tmp_path / "history.jsonl"
    samples_path.write_text(
        json.dumps([{"id": "one", "input": "Please check this bug before changing code."}], ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--samples",
            str(samples_path),
            "--out",
            str(out_path),
            "--history",
            str(history_path),
            "--iterations",
            "1",
            "--warmup",
            "0",
            "--append-history",
        ]
    )

    assert exit_code == 0
    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["schema_version"] == 1
    assert row["script_name"] == "scripts/benchmark_hot_path.py"
    assert row["artifact_version"] == 1
    assert row["samples_sha256"] == hashlib.sha256(samples_path.read_bytes()).hexdigest()
    assert row["sample_count"] == 1
    assert row["run_count"] == 1
    assert "route_ms" in row["p95_ms"]
    assert "route_context_chars" in row["p95_chars"]


def test_append_history_writes_compact_row(tmp_path):
    history_path = tmp_path / "history.jsonl"
    report = {
        "generated_at": "2026-06-14T00:00:00+00:00",
        "script_name": "scripts/benchmark_hot_path.py",
        "artifact_version": 1,
        "sample_source": "file",
        "samples_path": "samples.json",
        "samples_sha256": "abc123",
        "benchmark": {"sample_count": 1, "run_count": 2, "iterations": 2},
        "budget_pass": True,
        "baseline_comparison": {"passed": True, "warnings": [], "failures": []},
        "summary": {
            "stage_ms": {"route_ms": {"p95": 0.1}},
            "path_ms": {"default_non_llm_ms": {"p95": 0.2}},
            "size": {"route_context_chars": {"p95": 100.0}},
            "route_sample_counts": {"generic_task:general": 1},
        },
    }

    append_history(history_path, report)

    row = json.loads(history_path.read_text(encoding="utf-8"))
    assert row["budget_pass"] is True
    assert row["baseline_pass"] is True
    assert row["samples_sha256"] == "abc123"
    assert row["p95_ms"]["route_ms"] == 0.1
    assert row["p95_chars"]["route_context_chars"] == 100.0


def test_hot_path_benchmark_cli_updates_and_reads_baseline(tmp_path):
    samples_path = tmp_path / "samples.json"
    out_path = tmp_path / "hot_path_report.json"
    baseline_path = tmp_path / "hot_path_baseline.json"
    samples_path.write_text(
        json.dumps(
            [{"id": "one", "input": "Please check this bug before changing code."}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    create_exit = main(
        [
            "--samples",
            str(samples_path),
            "--out",
            str(out_path),
            "--baseline",
            str(baseline_path),
            "--iterations",
            "1",
            "--warmup",
            "0",
            "--update-baseline",
        ]
    )
    compare_exit = main(
        [
            "--samples",
            str(samples_path),
            "--out",
            str(out_path),
            "--baseline",
            str(baseline_path),
            "--iterations",
            "1",
            "--warmup",
            "0",
            "--fail-on-regression",
        ]
    )

    assert create_exit == 0
    assert compare_exit == 0
    assert baseline_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["baseline_path"] == str(baseline_path)
    assert data["baseline_comparison"]["passed"] is True
    assert "comparisons" in data["baseline_comparison"]
