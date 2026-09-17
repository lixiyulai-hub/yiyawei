#!/usr/bin/env python3
"""Benchmark deterministic hot-path stages for Yiyawei.

This script is intentionally local-only. It does not initialize ASR, call an
LLM, query GitHub, scan Obsidian, or read candidate corpora. The goal is to
measure whether the rule/router/template layer remains lightweight as samples
and governance assets grow.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.auditor.processor import _audit_final_text_quality
from src.auditor.task_compiler import compile_ai_task_fallback
from src.auditor.task_router import build_route_context, detect_task_route
from src.safety.risk_checker import RiskChecker
from src.text.filler_cleaner import clean_fillers
from src.text.normalizer import SCRIPT_SIMPLIFIED, normalize_output_text
from src.text.recording_control import strip_trailing_recording_end_phrase
from src.text.self_correction import repair_spoken_self_corrections
from scripts.governance_artifacts import sha256_file, utc_now_iso


DEFAULT_SAMPLES = ROOT / "data" / "hot_path_benchmark_samples.json"
DEFAULT_OUTPUT = ROOT / "output" / "hot_path_benchmark.json"
DEFAULT_BASELINE = ROOT / "output" / "hot_path_benchmark_baseline.json"
DEFAULT_HISTORY = ROOT / "output" / "hot_path_benchmark_history.jsonl"
SCRIPT_NAME = "scripts/benchmark_hot_path.py"
ARTIFACT_VERSION = 1

DEFAULT_BUDGETS_MS: dict[str, float] = {
    "preprocess_ms": 20.0,
    "risk_scan_ms": 5.0,
    "route_ms": 5.0,
    "context_build_ms": 10.0,
    "fallback_ms": 20.0,
    "quality_gate_ms": 20.0,
    "default_non_llm_ms": 60.0,
    "fallback_non_llm_ms": 80.0,
}

DEFAULT_BUDGETS_CHARS: dict[str, float] = {
    "route_context_chars": 1200.0,
    "fallback_chars": 1600.0,
}

STAGE_KEYS = (
    "preprocess_ms",
    "risk_scan_ms",
    "route_ms",
    "context_build_ms",
    "fallback_ms",
    "quality_gate_ms",
)

PATH_KEYS = (
    "default_non_llm_ms",
    "fallback_non_llm_ms",
)

SIZE_KEYS = (
    "input_chars",
    "cleaned_chars",
    "route_context_chars",
    "fallback_chars",
)

BASELINE_COMPARE_METRICS: tuple[tuple[str, str, str], ...] = (
    ("stage_ms", "preprocess_ms", "ms"),
    ("stage_ms", "risk_scan_ms", "ms"),
    ("stage_ms", "route_ms", "ms"),
    ("stage_ms", "context_build_ms", "ms"),
    ("stage_ms", "fallback_ms", "ms"),
    ("stage_ms", "quality_gate_ms", "ms"),
    ("path_ms", "default_non_llm_ms", "ms"),
    ("path_ms", "fallback_non_llm_ms", "ms"),
    ("size", "input_chars", "chars"),
    ("size", "cleaned_chars", "chars"),
    ("size", "route_context_chars", "chars"),
    ("size", "fallback_chars", "chars"),
)


@dataclass(frozen=True)
class BenchmarkSample:
    sample_id: str
    text: str


def load_samples(path: Path) -> list[BenchmarkSample]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "samples" in data:
        data = data["samples"]
    if not isinstance(data, list):
        raise ValueError("sample file must contain a JSON list or an object with a samples list")

    samples: list[BenchmarkSample] = []
    for index, item in enumerate(data, start=1):
        if isinstance(item, str):
            sample_id = f"sample_{index:03d}"
            text = item
        elif isinstance(item, dict):
            text = str(item.get("input") or "")
            sample_id = str(item.get("id") or f"sample_{index:03d}")
        else:
            raise ValueError(f"sample #{index} must be a string or object")
        text = text.strip()
        sample_id = sample_id.strip()
        if not text:
            raise ValueError(f"sample #{index} has empty input")
        samples.append(BenchmarkSample(sample_id=sample_id, text=text))

    if not samples:
        raise ValueError("sample file contains no samples")
    return samples


def preprocess_text(text: str) -> dict[str, Any]:
    raw_text = (text or "").strip()
    audit_text = normalize_output_text(raw_text, SCRIPT_SIMPLIFIED, punctuate=False) or raw_text
    self_corrected_text, self_corrections = repair_spoken_self_corrections(audit_text)
    cleaned_text = clean_fillers(self_corrected_text)
    cleaned_text, recording_end_phrase = strip_trailing_recording_end_phrase(cleaned_text)
    return {
        "raw_text": raw_text,
        "audit_text": audit_text,
        "cleaned_text": cleaned_text,
        "self_correction_count": len(self_corrections),
        "recording_end_phrase_removed": recording_end_phrase,
    }


def run_benchmark(
    samples: list[BenchmarkSample],
    *,
    iterations: int = 30,
    warmup: int = 3,
    budgets_ms: dict[str, float] | None = None,
    budgets_chars: dict[str, float] | None = None,
) -> dict[str, Any]:
    iterations = max(1, iterations)
    warmup = max(0, warmup)
    budgets = dict(DEFAULT_BUDGETS_MS)
    if budgets_ms:
        budgets.update(budgets_ms)
    size_budgets = dict(DEFAULT_BUDGETS_CHARS)
    if budgets_chars:
        size_budgets.update(budgets_chars)

    risk_checker = RiskChecker()

    for _ in range(warmup):
        for sample in samples:
            _measure_sample(sample, risk_checker)

    sample_reports: list[dict[str, Any]] = []
    all_values: dict[str, list[float]] = {key: [] for key in STAGE_KEYS + PATH_KEYS}
    all_chars: dict[str, list[float]] = {key: [] for key in SIZE_KEYS}
    route_sample_counts: dict[str, int] = {}

    for sample in samples:
        runs = [_measure_sample(sample, risk_checker) for _ in range(iterations)]
        first_run = runs[0]
        route_key = f"{first_run['route']['task_type']}:{first_run['route']['domain']}"
        route_sample_counts[route_key] = route_sample_counts.get(route_key, 0) + 1

        for run in runs:
            for key in STAGE_KEYS + PATH_KEYS:
                all_values[key].append(float(run[key]))
            for key in all_chars:
                all_chars[key].append(float(run[key]))

        quality_reasons: dict[str, int] = {}
        for run in runs:
            reason = run["quality_gate_reason"] or "pass"
            quality_reasons[reason] = quality_reasons.get(reason, 0) + 1

        sample_reports.append(
            {
                "id": sample.sample_id,
                "input_chars": first_run["input_chars"],
                "cleaned_chars": first_run["cleaned_chars"],
                "route_context_chars": first_run["route_context_chars"],
                "fallback_chars": first_run["fallback_chars"],
                "route": first_run["route"],
                "risk": first_run["risk"],
                "quality_gate_reason_counts": quality_reasons,
                "stage_ms": {key: summarize([float(run[key]) for run in runs]) for key in STAGE_KEYS},
                "path_ms": {key: summarize([float(run[key]) for run in runs]) for key in PATH_KEYS},
            }
        )

    summary = {
        "stage_ms": {key: summarize(values) for key, values in all_values.items() if key in STAGE_KEYS},
        "path_ms": {key: summarize(values) for key, values in all_values.items() if key in PATH_KEYS},
        "size": {key: summarize(values) for key, values in all_chars.items()},
        "route_sample_counts": route_sample_counts,
    }
    timing_budget_results = evaluate_budgets(summary, budgets)
    size_budget_results = evaluate_size_budgets(summary, size_budgets)
    budget_results = merge_budget_results(timing_budget_results, size_budget_results)

    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "root": str(ROOT),
        "benchmark": {
            "sample_count": len(samples),
            "iterations": iterations,
            "warmup": warmup,
            "run_count": len(samples) * iterations,
            "local_only": True,
            "network_allowed": False,
            "github_scan_allowed": False,
            "obsidian_scan_allowed": False,
            "asr_enabled": False,
            "llm_enabled": False,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "budgets_ms": budgets,
        "budgets_chars": size_budgets,
        "budget_pass": budget_results["passed"],
        "budget_results": budget_results,
        "timing_budget_results": timing_budget_results,
        "size_budget_results": size_budget_results,
        "summary": summary,
        "per_sample": sample_reports,
    }


def _measure_sample(sample: BenchmarkSample, risk_checker: RiskChecker) -> dict[str, Any]:
    preprocessed, preprocess_ms = timed(lambda: preprocess_text(sample.text))
    cleaned_text = str(preprocessed["cleaned_text"])

    risk, risk_scan_ms = timed(lambda: risk_checker.pre_scan(cleaned_text))
    route, route_ms = timed(lambda: detect_task_route(cleaned_text))
    route_context, context_build_ms = timed(lambda: build_route_context(cleaned_text))
    fallback_text, fallback_ms = timed(lambda: compile_ai_task_fallback(cleaned_text))
    quality_probe = fallback_text or cleaned_text
    quality_gate_reason, quality_gate_ms = timed(
        lambda: _audit_final_text_quality(cleaned_text, quality_probe)
    )

    default_non_llm_ms = (
        preprocess_ms
        + risk_scan_ms
        + route_ms
        + context_build_ms
        + quality_gate_ms
    )
    fallback_non_llm_ms = default_non_llm_ms + fallback_ms

    return {
        "id": sample.sample_id,
        "input_chars": len(sample.text),
        "cleaned_chars": len(cleaned_text),
        "route_context_chars": len(route_context),
        "fallback_chars": len(fallback_text),
        "preprocess_ms": preprocess_ms,
        "risk_scan_ms": risk_scan_ms,
        "route_ms": route_ms,
        "context_build_ms": context_build_ms,
        "fallback_ms": fallback_ms,
        "quality_gate_ms": quality_gate_ms,
        "default_non_llm_ms": default_non_llm_ms,
        "fallback_non_llm_ms": fallback_non_llm_ms,
        "route": {
            "task_type": route.task_type,
            "domain": route.domain,
            "task_score": route.task_score,
            "domain_score": route.domain_score,
            "example_count": len(route.examples),
        },
        "risk": {
            "risk_level": risk.risk_level,
            "need_confirm": risk.need_confirm,
            "hit_count": len(risk.hits),
        },
        "quality_gate_reason": quality_gate_reason,
    }


def timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    result = fn()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return result, elapsed_ms


def summarize(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {
            "count": 0,
            "min": 0.0,
            "avg": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "max": 0.0,
            "total": 0.0,
        }
    ordered = sorted(values)
    total = sum(ordered)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 4),
        "avg": round(total / len(ordered), 4),
        "p50": round(percentile(ordered, 50), 4),
        "p95": round(percentile(ordered, 95), 4),
        "max": round(ordered[-1], 4),
        "total": round(total, 4),
    }


def percentile(ordered_values: list[float], pct: float) -> float:
    if not ordered_values:
        return 0.0
    if len(ordered_values) == 1:
        return ordered_values[0]
    rank = (pct / 100.0) * (len(ordered_values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered_values[int(rank)]
    weight = rank - lower
    return ordered_values[lower] * (1.0 - weight) + ordered_values[upper] * weight


def evaluate_budgets(summary: dict[str, Any], budgets_ms: dict[str, float]) -> dict[str, Any]:
    failures: list[dict[str, float | str]] = []
    metric_groups = {
        **summary.get("stage_ms", {}),
        **summary.get("path_ms", {}),
    }
    for metric, budget in budgets_ms.items():
        stats = metric_groups.get(metric)
        if not stats:
            continue
        actual = float(stats.get("p95", 0.0))
        if actual > budget:
            failures.append(
                {
                    "metric": metric,
                    "budget_ms": float(budget),
                    "actual_p95_ms": round(actual, 4),
                }
            )
    return {
        "passed": not failures,
        "failures": failures,
    }


def evaluate_size_budgets(summary: dict[str, Any], budgets_chars: dict[str, float]) -> dict[str, Any]:
    failures: list[dict[str, float | str]] = []
    sizes = summary.get("size", {})
    for metric, budget in budgets_chars.items():
        stats = sizes.get(metric)
        if not stats:
            continue
        actual = float(stats.get("p95", 0.0))
        if actual > budget:
            failures.append(
                {
                    "metric": metric,
                    "budget_chars": float(budget),
                    "actual_p95_chars": round(actual, 4),
                }
            )
    return {
        "passed": not failures,
        "failures": failures,
    }


def merge_budget_results(*results: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for result in results:
        failures.extend(result.get("failures") or [])
    return {
        "passed": not failures,
        "failures": failures,
    }


def compare_with_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    warn_ratio: float = 0.10,
    fail_ratio: float = 0.25,
    min_abs_delta_ms: float = 5.0,
    min_abs_delta_chars: float = 100.0,
) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    current_summary = current.get("summary") or {}
    baseline_summary = baseline.get("summary") or {}

    for group, metric, unit in BASELINE_COMPARE_METRICS:
        current_value = _summary_p95(current_summary, group, metric)
        baseline_value = _summary_p95(baseline_summary, group, metric)
        if current_value is None or baseline_value is None:
            item = {
                "metric": metric,
                "group": group,
                "unit": unit,
                "baseline_p95": baseline_value,
                "current_p95": current_value,
                "status": "missing_metric",
            }
            failures.append(item)
            comparisons.append(item)
            continue
        delta = current_value - baseline_value
        ratio = _safe_ratio(delta, baseline_value)
        min_abs_delta = min_abs_delta_ms if unit == "ms" else min_abs_delta_chars
        status = "ok"
        row = {
            "metric": metric,
            "group": group,
            "unit": unit,
            "baseline_p95": round(baseline_value, 4),
            "current_p95": round(current_value, 4),
            "delta": round(delta, 4),
            "delta_ratio": round(ratio, 6),
            "status": status,
        }
        if delta > 0 and delta >= min_abs_delta and ratio >= fail_ratio:
            row["status"] = "fail"
            failures.append(row)
        elif delta > 0 and delta >= min_abs_delta and ratio >= warn_ratio:
            row["status"] = "warn"
            warnings.append(row)
        comparisons.append(row)

    sample_delta = int(current.get("benchmark", {}).get("sample_count", 0)) - int(
        baseline.get("benchmark", {}).get("sample_count", 0)
    )
    return {
        "baseline_generated_at": baseline.get("generated_at"),
        "current_generated_at": current.get("generated_at"),
        "baseline_sample_count": baseline.get("benchmark", {}).get("sample_count"),
        "current_sample_count": current.get("benchmark", {}).get("sample_count"),
        "sample_count_delta": sample_delta,
        "warn_ratio": warn_ratio,
        "fail_ratio": fail_ratio,
        "min_abs_delta_ms": min_abs_delta_ms,
        "min_abs_delta_chars": min_abs_delta_chars,
        "passed": not failures,
        "warnings": warnings,
        "failures": failures,
        "comparisons": comparisons,
    }


def load_json_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report must be a JSON object: {path}")
    return data


def _summary_p95(summary: dict[str, Any], group: str, metric: str) -> float | None:
    try:
        stats = summary[group][metric]
        return float(stats["p95"])
    except (KeyError, TypeError, ValueError):
        return None


def _safe_ratio(delta: float, baseline_value: float) -> float:
    if baseline_value <= 0:
        return 0.0 if delta <= 0 else float("inf")
    return delta / baseline_value


def parse_budget_overrides(items: list[str]) -> dict[str, float]:
    overrides: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"budget override must use key=value: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if key not in DEFAULT_BUDGETS_MS:
            allowed = ", ".join(sorted(DEFAULT_BUDGETS_MS))
            raise ValueError(f"unknown budget metric {key!r}; allowed: {allowed}")
        overrides[key] = float(value)
    return overrides


def parse_size_budget_overrides(items: list[str]) -> dict[str, float]:
    overrides: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"size budget override must use key=value: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if key not in DEFAULT_BUDGETS_CHARS:
            allowed = ", ".join(sorted(DEFAULT_BUDGETS_CHARS))
            raise ValueError(f"unknown size budget metric {key!r}; allowed: {allowed}")
        overrides[key] = float(value)
    return overrides


def build_history_entry(report: dict[str, Any]) -> dict[str, Any]:
    comparison = report.get("baseline_comparison") or {}
    return {
        "schema_version": 1,
        "artifact_version": report.get("artifact_version"),
        "script_name": report.get("script_name"),
        "generated_at": report.get("generated_at"),
        "sample_source": report.get("sample_source"),
        "samples_path": report.get("samples_path"),
        "samples_sha256": report.get("samples_sha256"),
        "sample_count": report.get("benchmark", {}).get("sample_count"),
        "run_count": report.get("benchmark", {}).get("run_count"),
        "iterations": report.get("benchmark", {}).get("iterations"),
        "budget_pass": report.get("budget_pass"),
        "baseline_pass": comparison.get("passed", True),
        "baseline_warning_count": len(comparison.get("warnings") or []),
        "baseline_failure_count": len(comparison.get("failures") or []),
        "p95_ms": {
            metric: _summary_p95(report.get("summary") or {}, group, metric)
            for group, metric in (
                *((("stage_ms", key) for key in STAGE_KEYS)),
                *((("path_ms", key) for key in PATH_KEYS)),
            )
        },
        "p95_chars": {
            metric: _summary_p95(report.get("summary") or {}, "size", metric)
            for metric in SIZE_KEYS
        },
        "route_sample_counts": report.get("summary", {}).get("route_sample_counts", {}),
    }


def append_history(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(build_history_entry(report), ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark local VPC hot-path stages")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES), help="sample JSON path")
    parser.add_argument("--text", default=None, help="benchmark one ad-hoc text sample")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="baseline JSON path")
    parser.add_argument("--iterations", type=int, default=30, help="measured runs per sample")
    parser.add_argument("--warmup", type=int, default=3, help="warmup runs per sample")
    parser.add_argument(
        "--budget",
        action="append",
        default=[],
        help="override a budget, for example route_ms=8 or default_non_llm_ms=70",
    )
    parser.add_argument(
        "--size-budget",
        action="append",
        default=[],
        help="override a p95 character budget, for example route_context_chars=1400",
    )
    parser.add_argument(
        "--fail-on-budget",
        action="store_true",
        help="return exit code 1 when a p95 budget is exceeded",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="return exit code 1 when baseline comparison has failures",
    )
    parser.add_argument(
        "--regression-warn-ratio",
        type=float,
        default=0.10,
        help="baseline comparison warning ratio, default 0.10",
    )
    parser.add_argument(
        "--regression-fail-ratio",
        type=float,
        default=0.25,
        help="baseline comparison failure ratio, default 0.25",
    )
    parser.add_argument(
        "--regression-min-delta-ms",
        type=float,
        default=5.0,
        help="minimum absolute p95 ms delta before baseline timing regressions count",
    )
    parser.add_argument(
        "--regression-min-delta-chars",
        type=float,
        default=100.0,
        help="minimum absolute p95 char delta before size regressions count",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="write the current report to --baseline after the run",
    )
    parser.add_argument("--history", default=str(DEFAULT_HISTORY), help="JSONL trend history output path")
    parser.add_argument("--append-history", action="store_true", help="append a compact trend row to --history")
    parser.add_argument("--print-json", action="store_true", help="print the full JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        budgets = parse_budget_overrides(args.budget)
        size_budgets = parse_size_budget_overrides(args.size_budget)
        if args.text:
            samples = [BenchmarkSample(sample_id="adhoc_text", text=args.text)]
            samples_path = None
            samples_sha256 = None
            sample_source = "adhoc_text"
        else:
            samples_path = Path(args.samples).expanduser()
            samples = load_samples(samples_path)
            samples_sha256 = sha256_file(samples_path)
            sample_source = "file"
        report = run_benchmark(
            samples,
            iterations=args.iterations,
            warmup=args.warmup,
            budgets_ms=budgets,
            budgets_chars=size_budgets,
        )
        report["sample_source"] = sample_source
        report["samples_path"] = str(samples_path) if samples_path is not None else ""
        report["samples_sha256"] = samples_sha256
        baseline_path = Path(args.baseline).expanduser()
        report["baseline_path"] = str(baseline_path)
        if args.update_baseline:
            report["baseline_comparison"] = {
                "passed": True,
                "warnings": [],
                "failures": [],
                "comparisons": [],
                "updated": True,
            }
        elif baseline_path.exists():
            baseline = load_json_report(baseline_path)
            report["baseline_comparison"] = compare_with_baseline(
                report,
                baseline,
                warn_ratio=max(0.0, args.regression_warn_ratio),
                fail_ratio=max(0.0, args.regression_fail_ratio),
                min_abs_delta_ms=max(0.0, args.regression_min_delta_ms),
                min_abs_delta_chars=max(0.0, args.regression_min_delta_chars),
            )
        elif not baseline_path.exists():
            report["baseline_comparison"] = {
                "passed": True,
                "warnings": [],
                "failures": [],
                "comparisons": [],
                "missing": True,
            }
        history_path = Path(args.history).expanduser()
        if args.append_history:
            report["history_path"] = str(history_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_text + "\n", encoding="utf-8")
    if args.update_baseline:
        baseline_path = Path(args.baseline).expanduser()
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(output_text + "\n", encoding="utf-8")
    if args.append_history:
        append_history(history_path, report)

    if args.print_json:
        print(output_text)
    else:
        _print_summary(report, out_path)
        if args.append_history:
            print(f"  history: appended ({history_path})")

    regression_failed = not report.get("baseline_comparison", {}).get("passed", True)
    if (args.fail_on_budget and not report["budget_pass"]) or (
        args.fail_on_regression and regression_failed
    ):
        return 1
    return 0


def _print_summary(report: dict[str, Any], out_path: Path) -> None:
    summary = report["summary"]
    print(f"Wrote {out_path}")
    print(
        "Hot-path benchmark: "
        f"{report['benchmark']['sample_count']} samples, "
        f"{report['benchmark']['run_count']} measured runs, "
        f"budget_pass={report['budget_pass']}"
    )
    for metric in ("route_ms", "context_build_ms", "fallback_ms", "quality_gate_ms"):
        stats = summary["stage_ms"][metric]
        budget = report["budgets_ms"].get(metric)
        print(f"  {metric}: p50={stats['p50']}ms p95={stats['p95']}ms budget={budget}ms")
    for metric in PATH_KEYS:
        stats = summary["path_ms"][metric]
        budget = report["budgets_ms"].get(metric)
        print(f"  {metric}: p50={stats['p50']}ms p95={stats['p95']}ms budget={budget}ms")
    for metric in ("route_context_chars", "fallback_chars"):
        stats = summary["size"][metric]
        budget = report.get("budgets_chars", {}).get(metric)
        print(f"  {metric}: p50={stats['p50']} p95={stats['p95']} budget={budget}")
    comparison = report.get("baseline_comparison") or {}
    if comparison.get("missing"):
        print(f"  baseline: missing ({report.get('baseline_path')})")
    elif comparison.get("updated"):
        print(f"  baseline: updated ({report.get('baseline_path')})")
    elif comparison:
        warning_count = len(comparison.get("warnings") or [])
        failure_count = len(comparison.get("failures") or [])
        print(
            "  baseline: "
            f"passed={comparison.get('passed')} "
            f"warnings={warning_count} failures={failure_count}"
        )
        for failure in comparison.get("failures") or []:
            print(
                "    regression "
                f"{failure['metric']}: p95 {failure['baseline_p95']} -> "
                f"{failure['current_p95']} {failure['unit']} "
                f"({failure['delta_ratio'] * 100:.1f}%)"
            )
    if not report["budget_pass"]:
        print("Budget failures:")
        for failure in report["budget_results"]["failures"]:
            if "actual_p95_ms" in failure:
                print(
                    "  "
                    f"{failure['metric']}: p95={failure['actual_p95_ms']}ms "
                    f"> budget={failure['budget_ms']}ms"
                )
            elif "actual_p95_chars" in failure:
                print(
                    "  "
                    f"{failure['metric']}: p95={failure['actual_p95_chars']} chars "
                    f"> budget={failure['budget_chars']} chars"
                )


if __name__ == "__main__":
    raise SystemExit(main())
