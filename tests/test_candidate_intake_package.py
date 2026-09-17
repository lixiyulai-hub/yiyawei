from __future__ import annotations

import json

from scripts.build_candidate_intake_package import build_package, main
from scripts.governance_artifacts import sha256_file


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate(candidate_id, *, text, task_type="code_fix", domain="general", status="review_only"):
    return {
        "candidate_id": candidate_id,
        "review_status": status,
        "hot_path_allowed": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "expected_task_type": task_type,
        "expected_domain": domain,
        "current_task_type": task_type,
        "current_domain": domain,
        "suggested_route_sample": {
            "id": f"{candidate_id}_sample",
            "spoken_type": "候选样本",
            "input": text,
            "expected_task_type": task_type,
            "expected_domain": domain,
            "output_shape": ["问题定位", "验证方式"],
            "must_keep": ["定位", "验证"],
            "must_drop": ["项目评估"],
        },
    }


def test_intake_package_layers_candidates_and_renders_preview(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    decisions = tmp_path / "decisions.json"

    accepted_text = "请修复登录接口报错，先定位原因再改代码。"
    _write_json(
        reviewed,
        [
            {
                "id": "accepted_sample",
                "input": accepted_text,
                "expected_task_type": "code_fix",
                "expected_domain": "general",
            }
        ],
    )
    _write_json(
        candidates,
        {
            "runtime_hot_path_used": False,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "candidates": [
                _candidate("accepted", text=accepted_text),
                _candidate("deferred", text="帮我分析一个电商项目是否值得开发，如果值得我要做开发。", task_type="project_evaluation", domain="ecommerce"),
                _candidate("rejected", text="讲个笑话。", task_type="generic_task"),
                _candidate("pending", text="请生成一份回归测试计划和验证清单。", task_type="test_plan"),
            ],
        },
    )
    _write_json(
        decisions,
        {
            "decisions": [
                {"candidate_id": "deferred", "review_status": "deferred", "review_notes": "下一批再看。"},
                {"candidate_id": "rejected", "review_status": "rejected", "review_notes": "重复闲聊负样本。"},
            ]
        },
    )

    package = build_package([candidates], reviewed, decisions_path=decisions)

    assert package["runtime_hot_path_used"] is False
    assert package["network_used"] is False
    assert package["repo_clone_or_download_used"] is False
    assert package["reviewed_samples_sha256"] == sha256_file(reviewed)
    assert package["status"]["ready_for_intake"] is True
    assert package["status"]["ready_for_strict_release"] is False
    assert package["intake"]["accepted_count"] == 1
    assert package["intake"]["deferred_count"] == 1
    assert package["intake"]["rejected_count"] == 1
    assert package["intake"]["pending_count"] == 1
    accepted_preview = package["intake"]["accepted_sample_drafts"][0]["novice_preview_text"]
    assert "代码修复" in accepted_preview
    assert "task_type=" not in accepted_preview
    deferred_preview = package["intake"]["deferred_items"][0]["novice_preview_text"]
    assert "SKU" in deferred_preview
    assert "供应链" in deferred_preview


def test_intake_package_cli_fails_on_pending_when_requested(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    out_path = tmp_path / "intake.json"
    _write_json(reviewed, [])
    _write_json(
        candidates,
        {
            "runtime_hot_path_used": False,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "candidates": [
                _candidate("pending", text="请生成一份回归测试计划和验证清单。", task_type="test_plan")
            ],
        },
    )

    exit_code = main(
        [
            "--candidates",
            str(candidates),
            "--reviewed-samples",
            str(reviewed),
            "--out",
            str(out_path),
            "--fail-on-pending",
        ]
    )

    assert exit_code == 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["intake"]["pending_count"] == 1


def test_intake_package_cli_passes_for_resolved_candidates(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    decisions = tmp_path / "decisions.json"
    out_path = tmp_path / "intake.json"
    _write_json(reviewed, [])
    _write_json(
        candidates,
        {
            "runtime_hot_path_used": False,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "candidates": [
                _candidate("accepted", text="请修复登录接口报错，先定位原因再改代码。", status="accepted_to_tests"),
                _candidate("rejected", text="讲个笑话。", task_type="generic_task"),
            ],
        },
    )
    _write_json(
        decisions,
        {
            "decisions": [
                {
                    "candidate_id": "accepted",
                    "review_status": "accepted_to_tests",
                    "accepted_sample_id": "manual_sample",
                    "review_notes": "人工确认可入库。",
                },
                {"candidate_id": "rejected", "review_status": "rejected", "review_notes": "重复。"},
            ]
        },
    )

    exit_code = main(
        [
            "--candidates",
            str(candidates),
            "--reviewed-samples",
            str(reviewed),
            "--decisions",
            str(decisions),
            "--out",
            str(out_path),
            "--fail-on-invalid",
            "--fail-on-pending",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["ready_for_strict_release"] is True
