from __future__ import annotations

import json
from pathlib import Path

from scripts.report_harness_governance import build_report, main


def _write_project(root: Path, *, runtime_reference: str = "") -> None:
    auditor = root / "src" / "auditor"
    auditor.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "app.py").write_text(runtime_reference + "\n", encoding="utf-8")
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (auditor / "prompt.py").write_text(
        'SYSTEM_PROMPT = """Harness 输出合同：final_text 只能放最终文本。"""\n'
        'FAST_SYSTEM_PROMPT = """只输出 JSON，包含 final_text。"""\n',
        encoding="utf-8",
    )
    (auditor / "intent_frame.py").write_text("class IntentFrame: pass\n", encoding="utf-8")
    (auditor / "task_router.py").write_text(
        "from src.auditor.intent_frame import extract_intent_frame\n"
        "TaskDefinition(\n"
        "DomainDefinition(\n"
        "TaskPromptTemplate(\n",
        encoding="utf-8",
    )
    (auditor / "task_compiler.py").write_text(
        "def _build_demo_task(): pass\n"
        "def _looks_like_demo(): pass\n",
        encoding="utf-8",
    )
    (auditor / "processor.py").write_text(
        "intent_frame = {}\n"
        "quality_gate_attribution = {}\n"
        "quality_gate_history = []\n"
        "def _leaks_internal_prompt(text): return 'internal_prompt_leak'\n"
        "def _missing_software_feedback_context(text, final): return 'missing_software_feedback_context'\n",
        encoding="utf-8",
    )
    (root / "docs" / "harness_governance_audit_2026-06-29.md").write_text(
        "# audit\n", encoding="utf-8"
    )


def test_harness_governance_report_builds_valid_snapshot(tmp_path):
    _write_project(tmp_path)

    report = build_report(tmp_path)

    assert report["schema_version"] == 1
    assert report["runtime_hot_path_used"] is False
    assert report["network_used"] is False
    assert report["repo_clone_or_download_used"] is False
    assert report["status"]["valid"] is True
    assert report["status"]["runtime_isolated"] is True
    assert report["prompt_metrics"]["SYSTEM_PROMPT"]["present"] is True
    assert report["prompt_metrics"]["FAST_SYSTEM_PROMPT"]["present"] is True
    assert report["route_metrics"]["task_definition_count"] == 1
    assert report["route_metrics"]["task_prompt_template_count"] == 1
    assert report["quality_gate_metrics"]["has_quality_gate_attribution"] is True
    assert report["quality_gate_metrics"]["has_internal_prompt_leak_guard"] is True
    assert all(item["passed"] for item in report["contract_checks"])
    assert len(report["audit_fingerprint"]) == 64


def test_harness_governance_report_flags_runtime_reference(tmp_path):
    _write_project(tmp_path, runtime_reference='print("harness_governance_snapshot")')

    report = build_report(tmp_path)

    assert report["status"]["valid"] is False
    assert report["status"]["runtime_isolated"] is False
    assert report["status"]["runtime_reference_violation_count"] == 1
    assert report["runtime_reference_violations"][0]["path"] == "app.py"
    reasons = {item["reason"] for item in report["failures"]}
    assert "runtime_reference_violation" in reasons
    assert "contract_check_failed" in reasons


def test_harness_governance_report_cli_writes_output_and_can_fail(tmp_path):
    _write_project(tmp_path)
    out_path = tmp_path / "snapshot.json"

    exit_code = main(["--root", str(tmp_path), "--out", str(out_path), "--fail-on-invalid"])

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["script_name"] == "scripts/report_harness_governance.py"
    assert data["status"]["valid"] is True

    bad_root = tmp_path / "bad"
    bad_out = tmp_path / "bad.json"
    bad_exit = main(["--root", str(bad_root), "--out", str(bad_out), "--fail-on-invalid"])

    assert bad_exit == 1
    assert json.loads(bad_out.read_text(encoding="utf-8"))["status"]["valid"] is False


def test_harness_governance_report_stays_offline_static():
    text = Path("scripts/report_harness_governance.py").read_text(encoding="utf-8")

    forbidden = ("requests", "urllib", "socket", "subprocess", "OpenAI(", "httpx")
    assert all(pattern not in text for pattern in forbidden)

