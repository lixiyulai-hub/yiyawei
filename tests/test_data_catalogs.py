from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GITHUB_SOURCE_CATALOG = ROOT / "data" / "github_source_catalog.json"


def test_github_source_catalog_schema():
    data = json.loads(GITHUB_SOURCE_CATALOG.read_text(encoding="utf-8"))

    assert len(data) >= 12
    repos = set()
    for item in data:
        assert item["repo"]
        assert item["url"].startswith("https://github.com/")
        assert item["tier"] in {"A", "B", "C"}
        assert item["license"]
        assert isinstance(item["stars"], int)
        assert item["stars"] >= 0
        assert item["source_type"]
        assert item["use_for"]
        assert item["import_policy"]
        assert item["runtime_policy"] in {
            "offline_candidate_source",
            "offline_reference_only",
            "index_only_no_import",
        }
        assert item["hot_path_allowed"] is False
        repos.add(item["repo"])

    assert len(repos) == len(data)
    assert any(item["tier"] == "A" and "code_fix" in item["use_for"] for item in data)
    assert any(item["tier"] == "A" and "text_polishing" in item["use_for"] for item in data)
    assert any(item["tier"] == "B" and "quality_gate" in item["use_for"] for item in data)
