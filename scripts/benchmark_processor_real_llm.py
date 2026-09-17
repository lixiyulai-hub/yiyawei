#!/usr/bin/env python3
"""Opt-in real LLM regression benchmark for AuditorProcessor."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso
from src.auditor.processor import AuditorProcessor
from src.config import load_config
from src.glossary.scanner import GlossaryScanner
from src.llm import create_llm_adapter
from src.llm.base import BaseLLMAdapter
from src.safety.risk_checker import RiskChecker


DEFAULT_SAMPLES = ROOT / "data" / "processor_real_llm_benchmark_samples.json"
DEFAULT_OUTPUT = ROOT / "output" / "processor_real_llm_benchmark.json"
SCRIPT_NAME = "scripts/benchmark_processor_real_llm.py"
ARTIFACT_VERSION = 1
LEAKAGE_TERMS = (
    "ASR 原始文本",
    "目标模式",
    "只输出 JSON",
    "SYSTEM_PROMPT",
    "FAST_SYSTEM_PROMPT",
    "route_context",
    "template_fragments",
)


@dataclass(frozen=True)
class RealBenchmarkSample:
    sample_id: str
    text: str
    mode: str = "cursor_prompt"
    expected_task_type: str = ""
    expected_domain: str = ""
    expected_risk_level: str = ""
    expected_need_confirm: bool | None = None
    min_final_chars: int = 1
    max_final_chars: int | None = None
    must_include_terms: tuple[str, ...] = ()
    min_include_count: int = 0
    forbidden_terms: tuple[str, ...] = ()


def load_samples(path: Path = DEFAULT_SAMPLES) -> list[RealBenchmarkSample]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "samples" in data:
        data = data["samples"]
    if not isinstance(data, list):
        raise ValueError("real LLM benchmark samples must be a JSON list or object with samples")
    samples: list[RealBenchmarkSample] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"sample #{index} must be an object")
        sample_id = str(item.get("id") or f"sample_{index:03d}").strip()
        text = str(item.get("input") or "").strip()
        if not text:
            raise ValueError(f"sample {sample_id!r} has empty input")
        expected_need_confirm = item.get("expected_need_confirm")
        samples.append(
            RealBenchmarkSample(
                sample_id=sample_id,
                text=text,
                mode=str(item.get("mode") or "cursor_prompt"),
                expected_task_type=str(item.get("expected_task_type") or ""),
                expected_domain=str(item.get("expected_domain") or ""),
                expected_risk_level=str(item.get("expected_risk_level") or ""),
                expected_need_confirm=expected_need_confirm if isinstance(expected_need_confirm, bool) else None,
                min_final_chars=int(item.get("min_final_chars") or 1),
                max_final_chars=int(item["max_final_chars"]) if item.get("max_final_chars") is not None else None,
                must_include_terms=tuple(str(term) for term in item.get("must_include_terms") or []),
                min_include_count=int(item.get("min_include_count") or 0),
                forbidden_terms=tuple(str(term) for term in item.get("forbidden_terms") or []),
            )
        )
    if not samples:
        raise ValueError("real LLM benchmark contains no samples")
    return samples


def build_report(
    *,
    samples_path: Path = DEFAULT_SAMPLES,
    config_path: Path | None = None,
    allow_live: bool = False,
    adapter_factory: Callable[[dict[str, Any]], BaseLLMAdapter] | None = None,
    max_samples: int | None = None,
) -> dict[str, Any]:
    samples = load_samples(samples_path)
    if max_samples is not None:
        samples = samples[: max(0, max_samples)]
    if not samples:
        raise ValueError("no samples selected")

    config = load_config(config_path or "config.no_paste.yaml")
    llm_cfg = dict(config.get("llm") or {})
    live_enabled = bool(allow_live)
    external_network_used = live_enabled and _is_external_endpoint(str(llm_cfg.get("base_url") or ""))
    adapter_factory = adapter_factory or create_llm_adapter
    skipped = not live_enabled
    per_sample: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    if live_enabled:
        adapter = adapter_factory(llm_cfg)
        processor = AuditorProcessor(
            adapter,
            GlossaryScanner((config.get("glossary") or {}).get("path")),
            RiskChecker(enabled=(config.get("safety") or {}).get("enabled", True)),
            enable_filler_cleaning=(config.get("text_processing") or {}).get("enable_filler_cleaning", True),
        )
        for sample in samples:
            try:
                per_sample.append(_run_sample(processor, sample))
            except Exception as exc:
                failure = _failure(sample.sample_id, "sample_exception", error=str(exc)[:300])
                failures.append(failure)
                per_sample.append(
                    {
                        "id": sample.sample_id,
                        "mode": sample.mode,
                        "elapsed_ms": 0,
                        "input_chars": len(sample.text),
                        "final_chars": 0,
                        "route": {},
                        "risk_level": "",
                        "need_confirm": None,
                        "debug": {},
                        "term_coverage": {},
                        "failures": [failure],
                    }
                )
    else:
        per_sample = []

    if live_enabled:
        for item in per_sample:
            failures.extend(item.get("failures") or [])

    status_passed = (not live_enabled) or not failures
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": external_network_used,
        "repo_clone_or_download_used": False,
        "real_llm_enabled": live_enabled,
        "local_llm_http_used": live_enabled and not external_network_used,
        "external_llm_endpoint_used": external_network_used,
        "skipped": skipped,
        "samples_path": str(samples_path),
        "samples_sha256": sha256_file(samples_path),
        "config": _redacted_config_summary(llm_cfg),
        "benchmark": {
            "sample_count": len(samples),
            "run_count": len(per_sample),
            "max_samples": max_samples,
            "allow_live": live_enabled,
        },
        "summary": _summarize(per_sample, failures),
        "per_sample": per_sample,
        "invariants": {
            "passed": status_passed,
            "failures": failures,
        },
        "status": {
            "passed": status_passed,
            "valid": status_passed,
            "runtime_isolated": True,
            "skipped": skipped,
            "failure_count": len(failures),
        },
        "notes": [
            "This benchmark is opt-in because it calls the configured real LLM.",
            "When --allow-live is omitted, the report is a skipped receipt and does not call a model.",
            "Default release gates should not depend on live model availability.",
        ],
    }


def _run_sample(processor: AuditorProcessor, sample: RealBenchmarkSample) -> dict[str, Any]:
    started = time.perf_counter()
    result = processor.process(sample.text, mode=sample.mode)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    debug = dict(processor.last_debug or {})
    route = debug.get("route") if isinstance(debug.get("route"), dict) else {}
    final_text = result.final_text or ""
    item = {
        "id": sample.sample_id,
        "mode": sample.mode,
        "elapsed_ms": elapsed_ms,
        "input_chars": len(sample.text),
        "input_preview": sample.text[:240],
        "final_chars": len(final_text),
        "final_text_preview": final_text[:500],
        "route": {
            "task_type": route.get("task_type"),
            "domain": route.get("domain"),
            "task_score": route.get("task_score"),
            "domain_score": route.get("domain_score"),
        },
        "risk_level": result.risk_level,
        "need_confirm": result.need_confirm,
        "debug": {
            "revision_attempted": bool(debug.get("llm_revision_raw_response")),
            "revision_applied": bool(debug.get("revision_applied")),
            "rule_task_fallback_used": bool(debug.get("rule_task_fallback_used")),
            "quality_gate_reason": str(debug.get("quality_gate_reason") or ""),
        },
        "term_coverage": _term_coverage(final_text, sample.must_include_terms),
        "failures": [],
    }
    item["failures"] = _evaluate_sample(sample, final_text, item, result)
    return item


def _evaluate_sample(
    sample: RealBenchmarkSample,
    final_text: str,
    item: dict[str, Any],
    result: Any,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if len(final_text) < sample.min_final_chars:
        failures.append(_failure(sample.sample_id, "final_text_too_short", actual=len(final_text), minimum=sample.min_final_chars))
    if sample.max_final_chars is not None and len(final_text) > sample.max_final_chars:
        failures.append(_failure(sample.sample_id, "final_text_too_long", actual=len(final_text), maximum=sample.max_final_chars))
    route = item.get("route") or {}
    if sample.expected_task_type and route.get("task_type") != sample.expected_task_type:
        failures.append(_failure(sample.sample_id, "task_type_mismatch", actual=route.get("task_type"), expected=sample.expected_task_type))
    if sample.expected_domain and route.get("domain") != sample.expected_domain:
        failures.append(_failure(sample.sample_id, "domain_mismatch", actual=route.get("domain"), expected=sample.expected_domain))
    if sample.expected_risk_level and result.risk_level != sample.expected_risk_level:
        failures.append(_failure(sample.sample_id, "risk_level_mismatch", actual=result.risk_level, expected=sample.expected_risk_level))
    if sample.expected_need_confirm is not None and bool(result.need_confirm) is not sample.expected_need_confirm:
        failures.append(_failure(sample.sample_id, "need_confirm_mismatch", actual=bool(result.need_confirm), expected=sample.expected_need_confirm))
    coverage = item.get("term_coverage") or {}
    if int(coverage.get("matched_count") or 0) < sample.min_include_count:
        failures.append(
            _failure(
                sample.sample_id,
                "must_include_terms_below_floor",
                actual=coverage.get("matched_count"),
                minimum=sample.min_include_count,
                missing=coverage.get("missing_terms"),
            )
        )
    forbidden_hits = [term for term in sample.forbidden_terms if term and term in final_text]
    if forbidden_hits:
        failures.append(_failure(sample.sample_id, "forbidden_terms_present", terms=forbidden_hits))
    leakage_hits = [term for term in LEAKAGE_TERMS if term in final_text]
    if leakage_hits:
        failures.append(_failure(sample.sample_id, "internal_prompt_leakage", terms=leakage_hits))
    return failures


def _term_coverage(text: str, terms: tuple[str, ...]) -> dict[str, Any]:
    matched = [term for term in terms if term and term.lower() in text.lower()]
    missing = [term for term in terms if term not in matched]
    return {
        "required_count": len(terms),
        "matched_count": len(matched),
        "matched_terms": matched,
        "missing_terms": missing,
    }


def _summarize(per_sample: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sample_count": len(per_sample),
        "failure_count": len(failures),
        "passed_count": sum(1 for item in per_sample if not item.get("failures")),
        "failed_count": sum(1 for item in per_sample if item.get("failures")),
        "revision_attempted_count": sum(1 for item in per_sample if (item.get("debug") or {}).get("revision_attempted")),
        "rule_task_fallback_used_count": sum(1 for item in per_sample if (item.get("debug") or {}).get("rule_task_fallback_used")),
        "high_risk_count": sum(1 for item in per_sample if item.get("risk_level") == "high"),
        "medium_risk_count": sum(1 for item in per_sample if item.get("risk_level") == "medium"),
    }


def _redacted_config_summary(llm_cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": llm_cfg.get("provider", ""),
        "base_url": llm_cfg.get("base_url", ""),
        "model": llm_cfg.get("model", ""),
        "timeout_sec": llm_cfg.get("timeout_sec"),
        "temperature": llm_cfg.get("temperature"),
        "max_tokens": llm_cfg.get("max_tokens"),
    }


def _is_external_endpoint(base_url: str) -> bool:
    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host not in {"", "localhost", "127.0.0.1", "::1"}


def _failure(sample_id: str, reason: str, **extra: Any) -> dict[str, Any]:
    payload = {"sample_id": sample_id, "reason": reason}
    payload.update(extra)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run opt-in real LLM processor benchmark")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES), help="sample JSON path")
    parser.add_argument("--config", default="config.no_paste.yaml", help="config path; defaults to no-paste config")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--allow-live", action="store_true", help="actually call the configured real LLM")
    parser.add_argument("--max-samples", type=int, default=None, help="limit number of samples")
    parser.add_argument("--fail-on-invariants", action="store_true", help="return 1 when benchmark invariants fail")
    parser.add_argument("--fail-on-error", action="store_true", help="alias for --fail-on-invariants")
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        report = build_report(
            samples_path=Path(args.samples).expanduser(),
            config_path=Path(args.config).expanduser() if args.config else None,
            allow_live=bool(args.allow_live),
            max_samples=args.max_samples,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            "Processor real-LLM benchmark: "
            f"allow_live={report['benchmark']['allow_live']}, "
            f"samples={report['benchmark']['sample_count']}, "
            f"runs={report['benchmark']['run_count']}, "
            f"passed={report['status']['passed']}, "
            f"failures={report['status']['failure_count']}"
        )
    if (args.fail_on_invariants or args.fail_on_error) and not report["status"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
