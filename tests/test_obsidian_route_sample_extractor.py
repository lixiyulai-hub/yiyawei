from __future__ import annotations

import json

from scripts.extract_obsidian_route_samples import build_report, main


def test_build_report_extracts_lightweight_chat_candidates(tmp_path):
    vault = tmp_path / "vault"
    note_dir = vault / "10_Projects" / "demo"
    note_dir.mkdir(parents=True)
    note = note_dir / "Audit Log.md"
    note.write_text(
        "\n".join(
            [
                "# Audit Log",
                "修复前：讲个冷笑话 误入 initial_model_call -> code。",
                "扩展样本：夸我一句 / 陪我聊会儿 / 给我讲个睡前故事。",
                "原则：route first / minimal sufficient binding / proof-backed output。",
            ]
        ),
        encoding="utf-8",
    )

    report = build_report(vault)

    assert report["files_scanned"] == 1
    assert report["candidate_count"] >= 4
    inputs = {item["input"] for item in report["candidates"]}
    assert "讲个冷笑话。" in inputs
    assert "夸我一句。" in inputs
    assert "陪我聊会儿。" in inputs
    assert "给我讲个睡前故事。" in inputs
    assert all(item["expected_task_type"] == "generic_task" for item in report["candidates"])
    assert all(item["expected_domain"] == "general" for item in report["candidates"])
    assert all(item["current_task_type"] == "generic_task" for item in report["candidates"])
    assert any(hit["label"] == "route first" for hit in report["methodology_hits"])
    assert any(hit["label"] == "proof-backed output" for hit in report["methodology_hits"])


def test_extractor_cli_writes_report_without_modifying_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "handoff.md"
    original = "祈使式闲聊误路由：安慰我一下、逗我一下、让我笑一下。\n"
    note.write_text(original, encoding="utf-8")
    out_path = tmp_path / "report.json"

    exit_code = main(["--vault", str(vault), "--out", str(out_path)])

    assert exit_code == 0
    assert note.read_text(encoding="utf-8") == original
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["candidate_count"] == 3
    assert {item["input"] for item in data["candidates"]} == {
        "安慰我一下。",
        "逗我一下。",
        "让我笑一下。",
    }
