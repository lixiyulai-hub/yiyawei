from __future__ import annotations

import json

from scripts.extract_github_route_sample_candidates import build_report, main


def _write_catalog(path, items):
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def test_build_report_uses_catalog_only_and_marks_review_only(tmp_path):
    catalog = tmp_path / "catalog.json"
    _write_catalog(
        catalog,
        [
            {
                "repo": "SWE-bench/SWE-bench",
                "url": "https://github.com/SWE-bench/SWE-bench",
                "stars": 5000,
                "license": "MIT",
                "tier": "A",
                "source_type": "software_engineering_benchmark",
                "use_for": ["code_fix", "bug_report", "test_plan"],
                "import_policy": "extract_issue_style_and_task_shapes_only",
                "runtime_policy": "offline_candidate_source",
                "hot_path_allowed": False,
            },
            {
                "repo": "ant-design/ant-design",
                "url": "https://github.com/ant-design/ant-design",
                "stars": 98000,
                "license": "MIT",
                "tier": "B",
                "source_type": "design_system",
                "use_for": ["ui_ux_design"],
                "import_policy": "reference_ui_terms_and_acceptance_dimensions",
                "runtime_policy": "offline_reference_only",
                "hot_path_allowed": False,
            },
        ],
    )

    report = build_report(catalog)

    assert report["schema_version"] == 1
    assert report["mode"] == "offline_catalog_only"
    assert report["network_used"] is False
    assert report["repo_clone_or_download_used"] is False
    assert report["runtime_hot_path_used"] is False
    assert report["review_required"] is True
    assert report["sources_scanned"] == 2
    assert report["candidate_count"] >= 4
    assert all(item["review_status"] == "review_only" for item in report["candidates"])
    assert all(item["hot_path_allowed"] is False for item in report["candidates"])
    assert all(item["network_used"] is False for item in report["candidates"])
    assert all(item["repo_clone_or_download_used"] is False for item in report["candidates"])
    assert all(item["derived_from"] == "catalog_metadata_only" for item in report["candidates"])


def test_extractor_cli_writes_report_without_modifying_catalog(tmp_path):
    catalog = tmp_path / "catalog.json"
    out_path = tmp_path / "github_candidates.json"
    items = [
        {
            "repo": "promptfoo/promptfoo",
            "url": "https://github.com/promptfoo/promptfoo",
            "stars": 22000,
            "license": "MIT",
            "tier": "B",
            "source_type": "prompt_eval_framework",
            "use_for": ["regression_tests", "quality_gate"],
            "import_policy": "reference_assertion_patterns",
            "runtime_policy": "offline_reference_only",
            "hot_path_allowed": False,
        }
    ]
    _write_catalog(catalog, items)
    original = catalog.read_text(encoding="utf-8")

    exit_code = main(["--catalog", str(catalog), "--out", str(out_path), "--limit", "20"])

    assert exit_code == 0
    assert catalog.read_text(encoding="utf-8") == original
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["candidate_count"] >= 1
    assert data["candidates"][0]["review_status"] == "review_only"


def test_skips_hot_path_allowed_sources(tmp_path):
    catalog = tmp_path / "catalog.json"
    _write_catalog(
        catalog,
        [
            {
                "repo": "unsafe/runtime-source",
                "url": "https://github.com/unsafe/runtime-source",
                "stars": 1,
                "license": "MIT",
                "tier": "A",
                "source_type": "unsafe",
                "use_for": ["code_fix"],
                "import_policy": "none",
                "runtime_policy": "offline_candidate_source",
                "hot_path_allowed": True,
            }
        ],
    )

    report = build_report(catalog)

    assert report["candidate_count"] == 0
    assert report["skipped_source_count"] == 1
    assert report["skipped_sources"][0]["reason"] == "hot_path_allowed_not_false"


def test_candidate_shapes_match_use_for(tmp_path):
    catalog = tmp_path / "catalog.json"
    _write_catalog(
        catalog,
        [
            {
                "repo": "demo/source",
                "url": "https://github.com/demo/source",
                "stars": 10,
                "license": "MIT",
                "tier": "A",
                "source_type": "mixed",
                "use_for": [
                    "code_fix",
                    "test_plan",
                    "ui_ux_design",
                    "product_planning",
                    "business_analysis",
                    "text_polishing",
                ],
                "import_policy": "metadata_only",
                "runtime_policy": "offline_candidate_source",
                "hot_path_allowed": False,
            }
        ],
    )

    report = build_report(catalog)
    by_use_for = {}
    for candidate in report["candidates"]:
        by_use_for.setdefault(candidate["use_for"][0], set()).add(candidate["expected_task_type"])

    assert by_use_for["code_fix"] >= {"code_fix", "bug_report"}
    assert by_use_for["test_plan"] == {"test_plan"}
    assert by_use_for["ui_ux_design"] == {"ui_ux_design"}
    assert by_use_for["product_planning"] == {"product_planning"}
    assert by_use_for["business_analysis"] == {"business_analysis"}
    assert by_use_for["text_polishing"] == {"text_polishing"}


def test_offline_candidate_only_excludes_reference_sources(tmp_path):
    catalog = tmp_path / "catalog.json"
    _write_catalog(
        catalog,
        [
            {
                "repo": "offline/source",
                "url": "https://github.com/offline/source",
                "stars": 10,
                "license": "MIT",
                "tier": "A",
                "source_type": "instruction_dataset",
                "use_for": ["generic_task"],
                "import_policy": "metadata_only",
                "runtime_policy": "offline_candidate_source",
                "hot_path_allowed": False,
            },
            {
                "repo": "reference/source",
                "url": "https://github.com/reference/source",
                "stars": 10,
                "license": "MIT",
                "tier": "B",
                "source_type": "prompt_reference",
                "use_for": ["quality_gate"],
                "import_policy": "reference_only",
                "runtime_policy": "offline_reference_only",
                "hot_path_allowed": False,
            },
        ],
    )

    report = build_report(catalog, include_reference_only=False)

    assert report["candidate_count"] >= 1
    assert all(candidate["source"]["repo"] == "offline/source" for candidate in report["candidates"])
    assert any(item["reason"] == "reference_only_excluded" for item in report["skipped_sources"])
