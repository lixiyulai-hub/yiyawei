from __future__ import annotations

import json

from scripts import benchmark_processor_real_llm as real_bench
from src.llm.base import BaseLLMAdapter


class FakeRealAdapter(BaseLLMAdapter):
    def __init__(self, config):
        super().__init__(config)
        self.calls = 0

    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        self.calls += 1
        return json.dumps(
            {
                "final_text": "请分析项目价值，覆盖模型成本、API 依赖、差异化、工作流嵌入、付费意愿、护城河、数据闭环，并给出 MVP。",
                "mode": "cursor_prompt",
                "intent_summary": "real benchmark fake response",
                "semantic_diagnosis": [],
                "output_requirements": [],
                "deleted_segments": [],
                "corrections": [],
                "constraints": [],
                "uncertain_terms": [],
                "risk_level": "low",
                "need_confirm": False,
            },
            ensure_ascii=False,
        )


def _write_samples(path):
    path.write_text(
        json.dumps(
            [
                {
                    "id": "ai_tool",
                    "input": "帮我分析一个 AI 工具项目是否值得做，如果值得我要开发。",
                    "mode": "cursor_prompt",
                    "expected_task_type": "project_evaluation",
                    "expected_domain": "ai_tool",
                    "min_final_chars": 20,
                    "must_include_terms": ["模型", "API", "差异化"],
                    "min_include_count": 2,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_real_llm_benchmark_default_is_skipped_receipt(tmp_path):
    samples = tmp_path / "samples.json"
    _write_samples(samples)

    report = real_bench.build_report(samples_path=samples, allow_live=False)

    assert report["script_name"] == "scripts/benchmark_processor_real_llm.py"
    assert report["real_llm_enabled"] is False
    assert report["skipped"] is True
    assert report["status"]["passed"] is True
    assert report["benchmark"]["run_count"] == 0
    assert report["network_used"] is False


def test_real_llm_benchmark_runs_with_fake_adapter_factory(tmp_path):
    samples = tmp_path / "samples.json"
    _write_samples(samples)

    report = real_bench.build_report(
        samples_path=samples,
        allow_live=True,
        adapter_factory=lambda cfg: FakeRealAdapter(cfg),
    )

    assert report["real_llm_enabled"] is True
    assert report["local_llm_http_used"] is True
    assert report["network_used"] is False
    assert report["status"]["passed"] is True
    assert report["benchmark"]["run_count"] == 1
    assert report["summary"]["sample_count"] == 1
    assert report["per_sample"][0]["term_coverage"]["matched_count"] >= 2


def test_real_llm_benchmark_records_sample_failures(tmp_path):
    samples = tmp_path / "samples.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "polish",
                    "input": "帮我润色这句普通短句，不要扩写：今天的会我可能晚十分钟到。",
                    "mode": "cursor_prompt",
                    "expected_task_type": "text_polishing",
                    "expected_domain": "general",
                    "min_final_chars": 8,
                    "max_final_chars": 120,
                    "forbidden_terms": ["MVP", "商业模式", "技术架构"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class ThinAdapter(BaseLLMAdapter):
        def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
            return json.dumps(
                {
                    "final_text": "请从商业模式、技术架构、MVP、路线图、竞品分析、增长策略和验收标准几个方面，完整规划这个项目。",
                    "mode": "cursor_prompt",
                },
                ensure_ascii=False,
            )

    report = real_bench.build_report(
        samples_path=samples,
        allow_live=True,
        adapter_factory=lambda cfg: ThinAdapter(cfg),
    )

    assert report["status"]["passed"] is False
    assert report["summary"]["failure_count"] > 0
    reasons = {failure["reason"] for failure in report["invariants"]["failures"]}
    assert "forbidden_terms_present" in reasons or "final_text_too_long" in reasons


def test_real_llm_benchmark_cli_writes_skipped_report(tmp_path):
    samples = tmp_path / "samples.json"
    out = tmp_path / "real_llm.json"
    _write_samples(samples)

    exit_code = real_bench.main(["--samples", str(samples), "--out", str(out)])

    assert exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["skipped"] is True
    assert data["status"]["passed"] is True
    assert data["samples_sha256"] == real_bench.sha256_file(samples)
