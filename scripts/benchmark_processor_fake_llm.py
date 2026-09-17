#!/usr/bin/env python3
"""Benchmark AuditorProcessor orchestration with deterministic fake LLMs.

This benchmark is intentionally local-only. It does not initialize ASR, call a
real LLM, use network access, query GitHub, or scan Obsidian. The fake adapters
return deterministic JSON so the measured work is AuditorProcessor orchestration:
preprocessing, prompt construction, parsing, revision handling, quality guards,
rule fallback, risk merging, and debug bookkeeping.
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

from src.auditor.processor import AuditorProcessor
from src.llm.base import BaseLLMAdapter
from scripts.governance_artifacts import canonical_json_sha256, sha256_file, utc_now_iso


DEFAULT_SAMPLES = ROOT / "data" / "processor_fake_llm_benchmark_samples.json"
DEFAULT_OUTPUT = ROOT / "output" / "processor_fake_llm_benchmark.json"
SCRIPT_NAME = "scripts/benchmark_processor_fake_llm.py"
ARTIFACT_VERSION = 1

DEFAULT_INLINE_SAMPLES: tuple[dict[str, str], ...] = (
    {
        "id": "clean_task",
        "input": "请检查登录接口报错，先定位原因，不要直接改代码。",
        "fake_behavior": "clean_rewrite",
        "fake_final_text": "请检查登录接口报错。先定位原因，不要直接改代码，并补充验证方式。",
    },
    {
        "id": "revision_success",
        "input": "我想让你帮我做一个对标美图秀秀的网站，先看他们的网站再执行我们自己网站的任务。",
        "fake_behavior": "internal_prompt_leak_then_rewrite",
        "fake_final_text": "请帮我做一个对标美图秀秀的网站。先分析它的页面结构、视觉风格和核心功能，再执行我们自己网站的相关任务。",
    },
    {
        "id": "rule_fallback",
        "input": "今天把中文口语重复表达这块口内容整理成合适的粘贴到chartGPT Claude Gemini Cursor VS Code 的终端输入框的专业文本不是普通语音转文字，而是机器人，不是机器人聊天，不是代码生成器。",
        "fake_behavior": "always_echo",
    },
    {
        "id": "risk_escalation",
        "input": "请帮我删除 node_modules 然后重新安装依赖，但先列出需要我确认的风险。",
        "fake_behavior": "risk_medium",
    },
)

FAKE_BEHAVIORS = {
    "clean_rewrite",
    "internal_prompt_leak_then_rewrite",
    "always_echo",
    "risk_medium",
    "risk_high",
    "misrouted_project_expansion",
    "thin_project_evaluation",
}

REQUIRED_SAMPLE_IDS: tuple[str, ...] = (
    "clean_task",
    "revision_success",
    "rule_fallback",
    "risk_escalation",
    "fast_revision_success",
    "text_polishing_misroute_guard",
    "thin_project_evaluation_fallback",
    "smalltalk_misroute_guard",
)


@dataclass(frozen=True)
class BenchmarkSample:
    sample_id: str
    text: str
    fake_behavior: str = "clean_rewrite"
    fake_final_text: str = ""
    mode: str = "cursor_prompt"
    fast_mode: bool = False


class DeterministicFakeLLM(BaseLLMAdapter):
    """Small fake adapter that never touches the network."""

    def __init__(self, sample: BenchmarkSample):
        super().__init__(
            {
                "model": f"fake-local-{sample.fake_behavior}",
                "base_url": "local-only",
            }
        )
        self.sample = sample
        self.calls = 0
        self.prompts_seen = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        self.prompts_seen += 1
        behavior = self.sample.fake_behavior

        if behavior == "always_echo":
            return _audit_json(
                final_text=self.sample.text,
                intent_summary="fake echo",
                semantic_diagnosis=["deterministic fake echo"],
            )

        if behavior == "internal_prompt_leak_then_rewrite" and self.calls == 1:
            return _audit_json(
                final_text=f"目标模式: {self.sample.mode}\nASR 原始文本:\n{self.sample.text}",
                intent_summary="fake prompt leak",
                semantic_diagnosis=["deterministic fake prompt leak"],
            )

        if behavior == "misrouted_project_expansion":
            return _audit_json(
                final_text=(
                    "\u8bf7\u8fdb\u884c\u9879\u76ee\u8bc4\u4f30\uff1a"
                    "\u5e02\u573a\u9700\u6c42\u3001\u7528\u6237\u75db\u70b9\u3001"
                    "\u7ade\u54c1\u3001\u66ff\u4ee3\u65b9\u6848\u3001\u5546\u4e1a\u6a21\u5f0f\u3001"
                    "\u6280\u672f\u53ef\u884c\u6027\u3001MVP\u3001\u6280\u672f\u67b6\u6784\u3001"
                    "\u5f00\u53d1\u8def\u7ebf\u56fe\u548c\u9a8c\u6536\u6807\u51c6\u3002"
                ),
                intent_summary="fake misrouted project expansion",
                semantic_diagnosis=["deterministic fake over-expansion"],
            )

        if behavior == "thin_project_evaluation":
            return _audit_json(
                final_text=(
                    self.sample.fake_final_text
                    or "\u8bf7\u5206\u6790\u8fd9\u4e2a\u9879\u76ee\u662f\u5426\u503c\u5f97\u5f00\u53d1\u3002"
                ),
                intent_summary="fake thin project evaluation",
                semantic_diagnosis=["deterministic fake thin project output"],
            )

        if behavior == "risk_medium":
            return _audit_json(
                final_text=self.sample.fake_final_text or self.sample.text,
                intent_summary="fake risk escalation",
                semantic_diagnosis=["deterministic fake risk response"],
                risk_level="medium",
                need_confirm=True,
            )

        if behavior == "risk_high":
            return _audit_json(
                final_text=self.sample.fake_final_text or self.sample.text,
                intent_summary="fake high-risk escalation",
                semantic_diagnosis=["deterministic fake high-risk response"],
                risk_level="high",
                need_confirm=True,
            )

        return _audit_json(
            final_text=self.sample.fake_final_text or self.sample.text,
            intent_summary="fake clean rewrite",
            semantic_diagnosis=["deterministic fake clean response"],
        )


def _audit_json(
    *,
    final_text: str,
    intent_summary: str,
    semantic_diagnosis: list[str],
    risk_level: str = "low",
    need_confirm: bool = False,
) -> str:
    return json.dumps(
        {
            "intent_summary": intent_summary,
            "semantic_diagnosis": semantic_diagnosis,
            "output_requirements": ["local deterministic fake response"],
            "final_text": final_text,
            "mode": "cursor_prompt",
            "deleted_segments": [],
            "corrections": [],
            "constraints": [],
            "uncertain_terms": [],
            "risk_level": risk_level,
            "need_confirm": need_confirm,
        },
        ensure_ascii=False,
    )


def load_samples(path: Path) -> list[BenchmarkSample]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "samples" in data:
        data = data["samples"]
    return parse_samples(data)


def parse_samples(data: Any) -> list[BenchmarkSample]:
    if not isinstance(data, list):
        raise ValueError("sample data must be a JSON list or an object with a samples list")

    samples: list[BenchmarkSample] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"sample #{index} must be a JSON object")
        text = str(item.get("input") or "").strip()
        sample_id = str(item.get("id") or f"sample_{index:03d}").strip()
        fake_behavior = str(item.get("fake_behavior") or "clean_rewrite").strip()
        if not text:
            raise ValueError(f"sample #{index} has empty input")
        if fake_behavior not in FAKE_BEHAVIORS:
            allowed = ", ".join(sorted(FAKE_BEHAVIORS))
            raise ValueError(
                f"sample {sample_id!r} has unknown fake_behavior {fake_behavior!r}; "
                f"allowed: {allowed}"
            )
        samples.append(
            BenchmarkSample(
                sample_id=sample_id,
                text=text,
                fake_behavior=fake_behavior,
                fake_final_text=str(item.get("fake_final_text") or "").strip(),
                mode=str(item.get("mode") or "cursor_prompt").strip(),
                fast_mode=bool(item.get("fast_mode", False)),
            )
        )

    if not samples:
        raise ValueError("sample data contains no samples")
    return samples


def default_samples() -> list[BenchmarkSample]:
    return parse_samples(list(DEFAULT_INLINE_SAMPLES))


def run_benchmark(
    samples: list[BenchmarkSample],
    *,
    iterations: int = 10,
    warmup: int = 1,
) -> dict[str, Any]:
    iterations = max(1, iterations)
    warmup = max(0, warmup)

    for _ in range(warmup):
        for sample in samples:
            _measure_run(sample)

    per_sample: list[dict[str, Any]] = []
    all_runs: list[dict[str, Any]] = []
    for sample in samples:
        runs = [_measure_run(sample) for _ in range(iterations)]
        all_runs.extend(runs)
        first = runs[0]
        per_sample.append(
            {
                "id": sample.sample_id,
                "fake_behavior": sample.fake_behavior,
                "mode": sample.mode,
                "fast_mode": sample.fast_mode,
                "input_chars": len(sample.text),
                "route": first["debug"].get("route") or {},
                "processor_ms": summarize([float(run["processor_ms"]) for run in runs]),
                "llm_calls": summarize([float(run["llm_calls"]) for run in runs]),
                "final_chars": summarize([float(run["final_chars"]) for run in runs]),
                "route_context_chars": summarize(
                    [float(run["route_context_chars"]) for run in runs]
                ),
                "debug_counters": _count_debug_runs(runs),
                "result_counters": _count_result_runs(runs),
            }
        )

    summary = {
        "processor_ms": summarize([float(run["processor_ms"]) for run in all_runs]),
        "llm_calls": summarize([float(run["llm_calls"]) for run in all_runs]),
        "final_chars": summarize([float(run["final_chars"]) for run in all_runs]),
        "route_context_chars": summarize(
            [float(run["route_context_chars"]) for run in all_runs]
        ),
        "debug_counters": _count_debug_runs(all_runs),
        "result_counters": _count_result_runs(all_runs),
        "route_counts": _count_by_route(all_runs),
        "quality_gate_reason_counts": _count_debug_value(all_runs, "quality_gate_reason"),
    }

    report = {
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
            "real_llm_enabled": False,
            "fake_llm_enabled": True,
            "deterministic_fake_llm": True,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "summary": summary,
        "per_sample": per_sample,
    }
    report["invariants"] = evaluate_invariants(report)
    return report


def _measure_run(sample: BenchmarkSample) -> dict[str, Any]:
    llm = DeterministicFakeLLM(sample)
    processor = AuditorProcessor(llm, fast_mode=sample.fast_mode)
    result, processor_ms = timed(lambda: processor.process(sample.text, mode=sample.mode))
    debug = dict(processor.last_debug or {})
    return {
        "sample_id": sample.sample_id,
        "processor_ms": processor_ms,
        "llm_calls": llm.calls,
        "final_chars": len(result.final_text),
        "route_context_chars": len(str(debug.get("route_context") or "")),
        "debug": _debug_snapshot(debug),
        "result": {
            "risk_level": result.risk_level,
            "need_confirm": result.need_confirm,
            "uncertain_terms": list(result.uncertain_terms),
        },
    }


def _debug_snapshot(debug: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision_applied": bool(debug.get("revision_applied")),
        "fast_revision_applied": bool(debug.get("fast_revision_applied")),
        "revision_attempted": bool(debug.get("llm_revision_raw_response")),
        "rule_task_fallback_used": bool(debug.get("rule_task_fallback_used")),
        "quality_gate_reason": str(debug.get("quality_gate_reason") or ""),
        "general_text_fixes_count": len(debug.get("general_text_fixes") or []),
        "self_correction_count": len(debug.get("self_corrections") or []),
        "route": debug.get("route") or {},
    }


def _count_debug_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    counters = {
        "revision_attempted_count": 0,
        "revision_applied_count": 0,
        "fast_revision_applied_count": 0,
        "rule_task_fallback_used_count": 0,
        "quality_gate_reason_count": 0,
        "general_text_fix_run_count": 0,
        "self_correction_run_count": 0,
        "orchestration_escalation_count": 0,
    }
    for run in runs:
        debug = run["debug"]
        revision_attempted = bool(debug.get("revision_attempted"))
        revision_applied = bool(debug.get("revision_applied"))
        fast_revision_applied = bool(debug.get("fast_revision_applied"))
        fallback_used = bool(debug.get("rule_task_fallback_used"))
        quality_gate_reason = bool(debug.get("quality_gate_reason"))
        if revision_attempted:
            counters["revision_attempted_count"] += 1
        if revision_applied:
            counters["revision_applied_count"] += 1
        if fast_revision_applied:
            counters["fast_revision_applied_count"] += 1
        if fallback_used:
            counters["rule_task_fallback_used_count"] += 1
        if quality_gate_reason:
            counters["quality_gate_reason_count"] += 1
        if int(debug.get("general_text_fixes_count") or 0) > 0:
            counters["general_text_fix_run_count"] += 1
        if int(debug.get("self_correction_count") or 0) > 0:
            counters["self_correction_run_count"] += 1
        if revision_attempted or fallback_used or quality_gate_reason:
            counters["orchestration_escalation_count"] += 1
    return counters


def _count_result_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    counters = {
        "need_confirm_count": 0,
        "medium_risk_count": 0,
        "high_risk_count": 0,
        "quality_plain_text_fallback_count": 0,
        "rule_task_fallback_uncertain_count": 0,
    }
    for run in runs:
        result = run["result"]
        risk_level = result.get("risk_level")
        uncertain_terms = set(result.get("uncertain_terms") or [])
        if result.get("need_confirm"):
            counters["need_confirm_count"] += 1
        if risk_level == "medium":
            counters["medium_risk_count"] += 1
        if risk_level == "high":
            counters["high_risk_count"] += 1
        if "quality_gate_plain_text_fallback" in uncertain_terms:
            counters["quality_plain_text_fallback_count"] += 1
        if "rule_task_fallback_used" in uncertain_terms:
            counters["rule_task_fallback_uncertain_count"] += 1
    return counters


def _count_by_route(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        route = run["debug"].get("route") or {}
        route_key = f"{route.get('task_type', 'unknown')}:{route.get('domain', 'unknown')}"
        counts[route_key] = counts.get(route_key, 0) + 1
    return counts


def _count_debug_value(runs: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        value = str(run["debug"].get(key) or "")
        value = value or "none"
        counts[value] = counts.get(value, 0) + 1
    return counts


def evaluate_invariants(report: dict[str, Any]) -> dict[str, Any]:
    benchmark = report.get("benchmark") or {}
    summary = report.get("summary") or {}
    debug = summary.get("debug_counters") or {}
    result = summary.get("result_counters") or {}
    route_counts = summary.get("route_counts") or {}
    per_sample = report.get("per_sample") or []
    sample_ids = {
        str(item.get("id") or "")
        for item in per_sample
        if isinstance(item, dict)
    }
    iterations = int(benchmark.get("iterations") or 1)
    failures: list[dict[str, Any]] = []

    _require_bool(failures, benchmark, "local_only", True)
    _require_bool(failures, benchmark, "network_allowed", False)
    _require_bool(failures, benchmark, "github_scan_allowed", False)
    _require_bool(failures, benchmark, "obsidian_scan_allowed", False)
    _require_bool(failures, benchmark, "real_llm_enabled", False)
    _require_bool(failures, benchmark, "fake_llm_enabled", True)
    _require_bool(failures, benchmark, "deterministic_fake_llm", True)

    missing_ids = sorted(set(REQUIRED_SAMPLE_IDS) - sample_ids)
    if missing_ids:
        failures.append({"type": "missing_required_samples", "sample_ids": missing_ids})

    floors = {
        "revision_attempted_count": 4 * iterations,
        "revision_applied_count": 3 * iterations,
        "fast_revision_applied_count": iterations,
        "rule_task_fallback_used_count": 3 * iterations,
    }
    for key, minimum in floors.items():
        actual = int(debug.get(key) or 0)
        if actual < minimum:
            failures.append(
                {
                    "type": "debug_counter_below_floor",
                    "counter": key,
                    "actual": actual,
                    "minimum": minimum,
                }
            )

    result_floors = {
        "need_confirm_count": iterations,
        "medium_risk_count": iterations,
        "high_risk_count": iterations,
        "rule_task_fallback_uncertain_count": 3 * iterations,
        "quality_plain_text_fallback_count": iterations,
    }
    for key, minimum in result_floors.items():
        actual = int(result.get(key) or 0)
        if actual < minimum:
            failures.append(
                {
                    "type": "result_counter_below_floor",
                    "counter": key,
                    "actual": actual,
                    "minimum": minimum,
                }
            )

    for route_key in ("project_evaluation:ai_tool", "text_polishing:general", "generic_task:general"):
        if route_key not in route_counts:
            failures.append({"type": "missing_route_count", "route": route_key})

    smalltalk = next(
        (item for item in per_sample if isinstance(item, dict) and item.get("id") == "smalltalk_misroute_guard"),
        None,
    )
    if isinstance(smalltalk, dict):
        route = smalltalk.get("route") or {}
        counters = smalltalk.get("debug_counters") or {}
        if route.get("task_type") != "generic_task" or route.get("domain") != "general":
            failures.append(
                {
                    "type": "smalltalk_route_mismatch",
                    "route": route,
                }
            )
        result_counters = smalltalk.get("result_counters") or {}
        if int(result_counters.get("quality_plain_text_fallback_count") or 0) < iterations:
            failures.append(
                {
                    "type": "smalltalk_plain_text_fallback_missing",
                    "actual": result_counters.get("quality_plain_text_fallback_count"),
                    "minimum": iterations,
                }
            )

    return {
        "passed": not failures,
        "failures": failures,
        "required_sample_ids": list(REQUIRED_SAMPLE_IDS),
    }


def _require_bool(
    failures: list[dict[str, Any]],
    values: dict[str, Any],
    key: str,
    expected: bool,
) -> None:
    actual = values.get(key)
    if actual is not expected:
        failures.append(
            {
                "type": "boolean_invariant_mismatch",
                "key": key,
                "expected": expected,
                "actual": actual,
            }
        )


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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark AuditorProcessor with deterministic fake LLM adapters"
    )
    parser.add_argument(
        "--samples",
        default=str(DEFAULT_SAMPLES),
        help="sample JSON path; falls back to built-in samples when missing",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--iterations", type=int, default=10, help="measured runs per sample")
    parser.add_argument("--warmup", type=int, default=1, help="warmup runs per sample")
    parser.add_argument("--print-json", action="store_true", help="print the full JSON report")
    parser.add_argument(
        "--fail-on-invariants",
        action="store_true",
        help="return exit code 1 when local-only or orchestration coverage invariants fail",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        samples_path = Path(args.samples).expanduser()
        if samples_path.exists():
            samples = load_samples(samples_path)
            sample_source = str(samples_path)
            sample_source_type = "file"
            samples_sha256 = sha256_file(samples_path)
            sample_source_missing = False
        else:
            samples = default_samples()
            sample_source = "built-in"
            sample_source_type = "built_in"
            samples_sha256 = canonical_json_sha256(list(DEFAULT_INLINE_SAMPLES))
            sample_source_missing = True
        report = run_benchmark(samples, iterations=args.iterations, warmup=args.warmup)
        report["samples_path"] = sample_source
        report["sample_source"] = sample_source_type
        report["samples_sha256"] = samples_sha256
        report["samples_path_missing"] = sample_source_missing
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_text + "\n", encoding="utf-8")

    if args.print_json:
        print(output_text)
    else:
        _print_summary(report, out_path)
    if args.fail_on_invariants and not report.get("invariants", {}).get("passed", False):
        return 1
    return 0


def _print_summary(report: dict[str, Any], out_path: Path) -> None:
    benchmark = report["benchmark"]
    counters = report["summary"]["debug_counters"]
    result_counters = report["summary"]["result_counters"]
    processor_stats = report["summary"]["processor_ms"]
    print(f"Wrote {out_path}")
    print(
        "Processor fake-LLM benchmark: "
        f"{benchmark['sample_count']} samples, "
        f"{benchmark['run_count']} measured runs, "
        f"local_only={benchmark['local_only']}"
    )
    print(
        "  processor_ms: "
        f"p50={processor_stats['p50']}ms p95={processor_stats['p95']}ms"
    )
    print(
        "  debug counters: "
        f"revision_attempted={counters['revision_attempted_count']} "
        f"revision_applied={counters['revision_applied_count']} "
        f"fallback={counters['rule_task_fallback_used_count']} "
        f"orchestration_escalation={counters['orchestration_escalation_count']}"
    )
    print(
        "  risk counters: "
        f"need_confirm={result_counters['need_confirm_count']} "
        f"medium={result_counters['medium_risk_count']} "
        f"high={result_counters['high_risk_count']}"
    )
    invariants = report.get("invariants") or {}
    print(
        "  invariants: "
        f"passed={invariants.get('passed')} "
        f"failures={len(invariants.get('failures') or [])}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
