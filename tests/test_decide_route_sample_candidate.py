from __future__ import annotations

import json

from pathlib import Path

from scripts.decide_route_sample_candidate import build_updated_decisions, build_validated_decision_update, main


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate(candidate_id, *, text="请修复登录接口报错。", task_type="code_fix", domain="general", **extra):
    item = {
        "candidate_id": candidate_id,
        "review_status": "review_only",
        "hot_path_allowed": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "expected_task_type": task_type,
        "expected_domain": domain,
        "current_task_type": task_type,
        "current_domain": domain,
        "suggested_route_sample": {
            "id": f"{candidate_id}_sample",
            "input": text,
            "expected_task_type": task_type,
            "expected_domain": domain,
        },
    }
    item.update(extra)
    return item


def test_build_updated_decisions_adds_rejected_record(tmp_path):
    decisions = tmp_path / "decisions.json"
    _write_json(decisions, {"schema_version": 1, "decisions": []})

    document, summary = build_updated_decisions(
        decisions,
        candidate_id="candidate_one",
        review_status="rejected",
        review_notes="重复样本。",
        reviewer="tester",
    )

    assert summary["updated_existing"] is False
    assert summary["decision_count"] == 1
    record = document["decisions"][0]
    assert record["candidate_id"] == "candidate_one"
    assert record["review_status"] == "rejected"
    assert record["review_notes"] == "重复样本。"
    assert record["reviewer"] == "tester"
    assert record["decision_source"] == "cli"


def test_build_updated_decisions_updates_existing_record(tmp_path):
    decisions = tmp_path / "decisions.json"
    _write_json(
        decisions,
        {
            "schema_version": 1,
            "decisions": [
                {
                    "candidate_id": "candidate_one",
                    "review_status": "deferred",
                    "review_notes": "先放着。",
                }
            ],
        },
    )

    document, summary = build_updated_decisions(
        decisions,
        candidate_id="candidate_one",
        review_status="rejected",
        review_notes="重复。",
        replace=True,
    )

    assert summary["updated_existing"] is True
    assert len(document["decisions"]) == 1
    assert document["decisions"][0]["review_status"] == "rejected"


def test_accepted_decision_requires_sample_id(tmp_path):
    decisions = tmp_path / "decisions.json"

    try:
        build_updated_decisions(
            decisions,
            candidate_id="candidate_one",
            review_status="accepted_to_tests",
            review_notes="人工确认。",
        )
    except ValueError as exc:
        assert "accepted decisions require --accepted-sample-id" in str(exc)
    else:
        raise AssertionError("expected accepted decision without sample id to fail")


def test_decision_cli_dry_run_does_not_modify_file(tmp_path):
    decisions = tmp_path / "decisions.json"
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(decisions, {"schema_version": 1, "decisions": []})
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("candidate_one")]})
    _write_json(reviewed, [])
    original = decisions.read_text(encoding="utf-8")

    exit_code = main(
        [
            "--candidates",
            str(candidates),
            "--reviewed-samples",
            str(reviewed),
            "--decisions",
            str(decisions),
            "--candidate-id",
            "candidate_one",
            "--status",
            "rejected",
            "--notes",
            "重复。",
        ]
    )

    assert exit_code == 0
    assert decisions.read_text(encoding="utf-8") == original


def test_decision_cli_writes_when_requested(tmp_path):
    decisions = tmp_path / "decisions.json"
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("candidate_one")]})
    _write_json(
        reviewed,
        [
            {
                "id": "sample_one",
                "input": "请修复登录接口报错。",
                "expected_task_type": "code_fix",
                "expected_domain": "general",
            }
        ],
    )

    exit_code = main(
        [
            "--candidates",
            str(candidates),
            "--reviewed-samples",
            str(reviewed),
            "--decisions",
            str(decisions),
            "--candidate-id",
            "candidate_one",
            "--status",
            "accepted_to_tests",
            "--accepted-sample-id",
            "sample_one",
            "--notes",
            "人工确认可入库。",
            "--write",
        ]
    )

    assert exit_code == 0
    data = json.loads(decisions.read_text(encoding="utf-8"))
    assert data["decisions"][0]["candidate_id"] == "candidate_one"
    assert data["decisions"][0]["accepted_sample_id"] == "sample_one"


def test_decision_cli_rejects_unsafe_decisions_output_paths(tmp_path):
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("candidate_one")]})
    _write_json(reviewed, [])

    forbidden_paths = [
        Path("app.py"),
        Path("tests/route_samples.json"),
        Path("src/not_allowed.json"),
        Path("tests/test_not_allowed.py"),
    ]
    for forbidden in forbidden_paths:
        exit_code = main(
            [
                "--candidates",
                str(candidates),
                "--reviewed-samples",
                str(reviewed),
                "--decisions",
                str(forbidden),
                "--candidate-id",
                "candidate_one",
                "--status",
                "rejected",
                "--notes",
                "危险输出路径应被拒绝。",
                "--commit",
            ]
        )
        assert exit_code == 2


def test_validated_accept_fails_when_reviewed_sample_missing(tmp_path):
    decisions = tmp_path / "decisions.json"
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("candidate_one")]})
    _write_json(reviewed, [])

    try:
        build_validated_decision_update(
            [candidates],
            reviewed,
            decisions,
            candidate_id="candidate_one",
            review_status="accepted_to_tests",
            accepted_sample_id="missing_sample",
            review_notes="人工确认。",
        )
    except ValueError as exc:
        assert "accepted sample id not found" in str(exc)
    else:
        raise AssertionError("expected missing accepted sample to fail")


def test_validated_accept_fails_on_task_domain_mismatch(tmp_path):
    decisions = tmp_path / "decisions.json"
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("candidate_one", task_type="code_fix")]})
    _write_json(reviewed, [{"id": "sample_one", "input": "请修复登录接口报错。", "expected_task_type": "bug_report", "expected_domain": "general"}])

    try:
        build_validated_decision_update(
            [candidates],
            reviewed,
            decisions,
            candidate_id="candidate_one",
            review_status="accepted_to_tests",
            accepted_sample_id="sample_one",
            review_notes="人工确认。",
        )
    except ValueError as exc:
        assert "task type does not match" in str(exc)
    else:
        raise AssertionError("expected task mismatch to fail")


def test_validated_accept_requires_equivalence_note_for_different_input(tmp_path):
    decisions = tmp_path / "decisions.json"
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("candidate_one", text="请修复登录接口报错。")]})
    _write_json(reviewed, [{"id": "sample_one", "input": "请修复支付接口报错。", "expected_task_type": "code_fix", "expected_domain": "general"}])

    try:
        build_validated_decision_update(
            [candidates],
            reviewed,
            decisions,
            candidate_id="candidate_one",
            review_status="accepted_to_tests",
            accepted_sample_id="sample_one",
            review_notes="人工确认。",
        )
    except ValueError as exc:
        assert "accepted sample input differs" in str(exc)
    else:
        raise AssertionError("expected input mismatch to fail")

    document, summary = build_validated_decision_update(
        [candidates],
        reviewed,
        decisions,
        candidate_id="candidate_one",
        review_status="accepted_to_tests",
        accepted_sample_id="sample_one",
        review_notes="人工确认。",
        equivalence_note="同类接口报错候选，现有样本已覆盖路由边界。",
    )
    assert summary["review_status"] == "accepted_to_tests"
    assert document["decisions"][0]["equivalence_note"]


def test_validated_decision_fails_for_unsafe_candidate(tmp_path):
    decisions = tmp_path / "decisions.json"
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("candidate_one", hot_path_allowed=True)]})
    _write_json(reviewed, [])

    try:
        build_validated_decision_update(
            [candidates],
            reviewed,
            decisions,
            candidate_id="candidate_one",
            review_status="rejected",
            review_notes="不安全。",
        )
    except ValueError as exc:
        assert "hot_path_allowed" in str(exc)
    else:
        raise AssertionError("expected unsafe candidate to fail")


def test_validated_decision_fails_for_unknown_or_duplicate_candidate(tmp_path):
    decisions = tmp_path / "decisions.json"
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("dup"), _candidate("dup")]})
    _write_json(reviewed, [])

    try:
        build_validated_decision_update(
            [candidates],
            reviewed,
            decisions,
            candidate_id="missing",
            review_status="rejected",
            review_notes="无此候选。",
        )
    except ValueError as exc:
        assert "candidate id not found" in str(exc)
    else:
        raise AssertionError("expected unknown candidate to fail")

    try:
        build_validated_decision_update(
            [candidates],
            reviewed,
            decisions,
            candidate_id="dup",
            review_status="rejected",
            review_notes="重复。",
        )
    except ValueError as exc:
        assert "appears multiple times" in str(exc)
    else:
        raise AssertionError("expected duplicate candidate to fail")


def test_validated_decision_requires_replace_for_existing_decision(tmp_path):
    decisions = tmp_path / "decisions.json"
    candidates = tmp_path / "candidates.json"
    reviewed = tmp_path / "route_samples.json"
    _write_json(decisions, {"schema_version": 1, "decisions": [{"candidate_id": "candidate_one", "review_status": "deferred", "review_notes": "先放着。"}]})
    _write_json(candidates, {"runtime_hot_path_used": False, "network_used": False, "repo_clone_or_download_used": False, "candidates": [_candidate("candidate_one")]})
    _write_json(reviewed, [])

    try:
        build_validated_decision_update(
            [candidates],
            reviewed,
            decisions,
            candidate_id="candidate_one",
            review_status="rejected",
            review_notes="重复。",
        )
    except ValueError as exc:
        assert "pass --replace" in str(exc)
    else:
        raise AssertionError("expected existing decision without replace to fail")

    document, summary = build_validated_decision_update(
        [candidates],
        reviewed,
        decisions,
        candidate_id="candidate_one",
        review_status="rejected",
        review_notes="重复。",
        replace=True,
    )
    assert summary["updated_existing"] is True
    assert document["decisions"][0]["review_status"] == "rejected"
