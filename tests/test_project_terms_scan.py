from __future__ import annotations

import json

from scripts import scan_project_terms


def test_project_terms_scan_happy_path(tmp_path):
    terms = tmp_path / "project_terms.json"
    terms.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "terms": [
                    {"canonical": "Voice Prompt Compiler", "aliases": ["VPC"], "category": "product"},
                    {"canonical": "FunASR", "aliases": ["Paraformer"], "category": "asr"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("VPC uses FunASR.\n", encoding="utf-8")

    report = scan_project_terms.build_report(terms_path=terms, root=tmp_path)

    assert report["script_name"] == "scripts/scan_project_terms.py"
    assert report["runtime_hot_path_used"] is False
    assert report["term_count"] == 2
    assert report["status"]["passed"] is True
    assert report["mentions"]


def test_project_terms_scan_flags_duplicates_and_sensitive_terms(tmp_path):
    terms = tmp_path / "project_terms.json"
    terms.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "terms": [
                    {"canonical": "One", "aliases": ["shared"], "category": "x"},
                    {"canonical": "Two", "aliases": ["shared", "api_key"], "category": "x"},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = scan_project_terms.build_report(terms_path=terms, root=tmp_path)

    assert report["status"]["passed"] is False
    reasons = {check["name"].split(":")[-1] for check in report["checks"] if check["status"] == "error"}
    assert "duplicate_alias" in reasons
    assert "sensitive_term" in reasons


def test_project_terms_scan_cli_fail_flag(tmp_path):
    missing = tmp_path / "missing.json"
    out_path = tmp_path / "terms.json"

    exit_code = scan_project_terms.main(["--terms", str(missing), "--root", str(tmp_path), "--out", str(out_path), "--fail-on-error"])

    assert exit_code == 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["passed"] is False

