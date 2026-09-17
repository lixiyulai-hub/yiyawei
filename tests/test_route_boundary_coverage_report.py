from __future__ import annotations

import hashlib
import json

from scripts.report_route_boundary_coverage import build_report, main


def test_route_boundary_coverage_report_tracks_qualitative_boundaries(tmp_path):
    samples = tmp_path / "route_samples.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "generic_saas",
                    "input": "SaaS 这句话只翻译，不要做方案。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "saas",
                    "boundary_tags": ["domain_generic_negative"],
                },
                {
                    "id": "generic_saas_2",
                    "input": "SaaS 这句话只解释，不要做方案。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "saas",
                    "boundary_tags": ["domain_generic_negative"],
                },
                {
                    "id": "generic_ecommerce",
                    "input": "电商这句只加标点，别分析。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "ecommerce",
                    "boundary_tags": ["domain_generic_negative"],
                },
                {
                    "id": "generic_ecommerce_2",
                    "input": "电商退款通知只翻译，不要做售后方案。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "ecommerce",
                    "boundary_tags": ["domain_generic_negative"],
                },
                {
                    "id": "safety_healthcare",
                    "input": "不要给医疗结论，列咨询医生的问题清单。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "healthcare",
                    "boundary_tags": ["domain_generic_negative", "safety_boundary"],
                },
                {
                    "id": "safety_healthcare_2",
                    "input": "不要诊断，只解释报告指标。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "healthcare",
                    "boundary_tags": ["domain_generic_negative", "safety_boundary"],
                },
                {
                    "id": "safety_finance",
                    "input": "不要给买卖建议，列风险因素。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "finance_risk",
                    "boundary_tags": ["domain_generic_negative", "safety_boundary"],
                },
                {
                    "id": "safety_finance_2",
                    "input": "支付风控规则只解释，不要真实放行。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "finance_risk",
                    "boundary_tags": ["domain_generic_negative", "safety_boundary"],
                },
                {
                    "id": "safety_general",
                    "input": "清空数据库前先列确认清单。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_tags": ["safety_boundary", "spoken_correction"],
                },
                {
                    "id": "safety_general_2",
                    "input": "不要执行删除，只写确认清单。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_tags": ["safety_boundary"],
                },
                {
                    "id": "counterexample_general",
                    "input": "解释 drop table，不要生成 SQL。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "general",
                    "boundary_tags": ["safety_counterexample"],
                },
                {
                    "id": "counterexample_general_2",
                    "input": "不要 rm -rf，只写确认清单。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "general",
                    "boundary_tags": ["safety_counterexample"],
                },
                {
                    "id": "counterexample_healthcare",
                    "input": "解释血糖指标，不要诊断。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "healthcare",
                    "boundary_tags": ["safety_counterexample"],
                },
                {
                    "id": "counterexample_healthcare_2",
                    "input": "润色健康免责声明，不判断病情。",
                    "expected_task_type": "text_polishing",
                    "expected_domain": "healthcare",
                    "boundary_domain": "healthcare",
                    "boundary_tags": ["safety_counterexample"],
                },
                {
                    "id": "counterexample_finance",
                    "input": "解释基金定投，不给买卖建议。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "finance_risk",
                    "boundary_tags": ["safety_counterexample"],
                },
                {
                    "id": "counterexample_finance_2",
                    "input": "润色支付风控说明，不承诺放行资金。",
                    "expected_task_type": "text_polishing",
                    "expected_domain": "finance_risk",
                    "boundary_domain": "finance_risk",
                    "boundary_tags": ["safety_counterexample"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_report(samples)

    assert report["script_name"] == "scripts/report_route_boundary_coverage.py"
    assert report["by_boundary"]["domain_generic_negative"] == 8
    assert report["by_boundary"]["safety_boundary"] == 6
    assert report["by_boundary"]["safety_counterexample"] == 6
    assert report["status"]["passed"] is True
    assert report["missing_generic_negative_domains"] == []
    assert report["missing_safety_domains"] == []
    assert report["missing_counterexample_domains"] == []
    assert report["undercovered_generic_negative_domains"] == []
    assert report["undercovered_safety_domains"] == []
    assert report["undercovered_counterexample_domains"] == []


def test_route_boundary_coverage_report_hashes_raw_bytes_for_crlf_files(tmp_path):
    samples = tmp_path / "route_samples.json"
    payload = json.dumps(
        [
            {
                "id": "generic_saas_negative",
                "input": "SaaS translate only",
                "expected_task_type": "generic_task",
                "expected_domain": "general",
                "boundary_domain": "saas",
                "boundary_tags": ["domain_generic_negative"],
            }
        ],
        ensure_ascii=False,
        indent=2,
    ).replace("\n", "\r\n")
    samples.write_bytes(payload.encode("utf-8"))

    report = build_report(samples)

    byte_hash = hashlib.sha256(samples.read_bytes()).hexdigest()
    text_hash = hashlib.sha256(samples.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    assert report["samples_sha256"] == byte_hash
    assert report["samples_sha256"] != text_hash


def test_route_boundary_coverage_cli_fails_when_required_boundary_missing(tmp_path):
    samples = tmp_path / "route_samples.json"
    out_path = tmp_path / "boundary.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "generic",
                    "input": "翻译一下。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["--samples", str(samples), "--out", str(out_path), "--fail-on-missing"]) == 1


def test_route_boundary_coverage_reports_undercovered_required_domains(tmp_path):
    samples = tmp_path / "route_samples.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "generic_saas",
                    "input": "SaaS 这句话只翻译，不要做方案。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "saas",
                    "boundary_tags": ["domain_generic_negative"],
                },
                {
                    "id": "generic_ecommerce",
                    "input": "电商这句只加标点，别分析。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "ecommerce",
                    "boundary_tags": ["domain_generic_negative"],
                },
                {
                    "id": "generic_finance",
                    "input": "基金这句话只解释，不要给买卖建议。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "finance_risk",
                    "boundary_tags": ["domain_generic_negative", "safety_boundary"],
                },
                {
                    "id": "generic_healthcare",
                    "input": "血糖指标只解释，不要诊断。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "healthcare",
                    "boundary_tags": ["domain_generic_negative", "safety_boundary"],
                },
                {
                    "id": "safety_general",
                    "input": "清空数据库前先列确认清单。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "general",
                    "boundary_tags": ["safety_boundary"],
                },
                {
                    "id": "counterexample_general",
                    "input": "解释 drop table，不生成 SQL。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "general",
                    "boundary_tags": ["safety_counterexample"],
                },
                {
                    "id": "counterexample_finance",
                    "input": "解释基金定投，不给买卖建议。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "finance_risk",
                    "boundary_tags": ["safety_counterexample"],
                },
                {
                    "id": "counterexample_healthcare",
                    "input": "解释化验指标，不给诊断建议。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_domain": "healthcare",
                    "boundary_tags": ["safety_counterexample"],
                },
                {
                    "id": "correction",
                    "input": "不对，先别做方案，只整理 bug。",
                    "expected_task_type": "bug_report",
                    "expected_domain": "general",
                    "boundary_tags": ["spoken_correction"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_report(samples)

    assert report["status"]["passed"] is False
    assert {"domain": "saas", "count": 1, "target": 2} in report[
        "undercovered_generic_negative_domains"
    ]
    assert {"domain": "general", "count": 1, "target": 2} in report[
        "undercovered_safety_domains"
    ]
    assert {"domain": "finance_risk", "count": 1, "target": 2} in report[
        "undercovered_counterexample_domains"
    ]


def test_route_boundary_coverage_reports_ignored_boundary_tags(tmp_path):
    samples = tmp_path / "route_samples.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "sample",
                    "input": "普通样本。",
                    "expected_task_type": "generic_task",
                    "expected_domain": "general",
                    "boundary_tags": ["test_boundary"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_report(samples)

    assert report["ignored_boundary_tags"] == [
        {"index": 1, "id": "sample", "tag": "test_boundary"}
    ]


def test_route_boundary_coverage_rejects_bad_generic_boundary_tag(tmp_path):
    samples = tmp_path / "route_samples.json"
    samples.write_text(
        json.dumps(
            [
                {
                    "id": "bad",
                    "input": "SaaS 续费分析。",
                    "expected_task_type": "business_analysis",
                    "expected_domain": "saas",
                    "boundary_tags": ["domain_generic_negative"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_report(samples)

    assert report["status"]["valid"] is False
    assert report["invalid_items"][0]["reason"] == "domain_generic_negative_requires_generic_task"
