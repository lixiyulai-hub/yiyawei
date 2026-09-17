from __future__ import annotations

import json

from scripts.report_candidate_review_status import build_report, main


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate(
    candidate_id: str,
    *,
    sample_id: str | None = None,
    text: str = "Please check this bug.",
    review_status: str = "review_only",
    expected_task_type: str = "bug_report",
    expected_domain: str = "general",
    current_task_type: str = "bug_report",
    current_domain: str = "general",
    **extra,
):
    item = {
        "candidate_id": candidate_id,
        "review_status": review_status,
        "hot_path_allowed": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "expected_task_type": expected_task_type,
        "expected_domain": expected_domain,
        "current_task_type": current_task_type,
        "current_domain": current_domain,
        "suggested_route_sample": {
            "id": sample_id or f"{candidate_id}_sample",
            "input": text,
            "expected_task_type": expected_task_type,
            "expected_domain": expected_domain,
        },
    }
    item.update(extra)
    return item


def test_candidate_review_report_classifies_accepted_rejected_deferred_and_unreviewed(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    decisions = tmp_path / "decisions.json"

    _write_json(
        reviewed,
        [
            {
                "id": "accepted_sample",
                "input": "Please check this bug.",
                "expected_task_type": "bug_report",
                "expected_domain": "general",
            }
        ],
    )
    _write_json(
        candidates,
        {
            "schema_version": 1,
            "runtime_hot_path_used": False,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "candidates": [
                _candidate("accepted", sample_id="accepted_sample"),
                _candidate("rejected"),
                _candidate("deferred"),
                _candidate("unreviewed", text="Please polish this sentence."),
            ],
        },
    )
    _write_json(
        decisions,
        {
            "decisions": [
                {"candidate_id": "rejected", "review_status": "rejected"},
                {"candidate_id": "deferred", "review_status": "deferred"},
            ]
        },
    )

    report = build_report([candidates], reviewed, decisions_path=decisions)

    by_id = {item["candidate_id"]: item for item in report["review_items"]}
    assert by_id["accepted"]["status"] == "accepted"
    assert by_id["accepted"]["reason"] == "suggested_sample_id_match"
    assert by_id["rejected"]["status"] == "rejected"
    assert by_id["deferred"]["status"] == "deferred"
    assert by_id["unreviewed"]["status"] == "unreviewed"
    assert report["pending_count"] == 1
    assert report["status"]["runtime_isolated"] is True
    assert len(report["matches"]) == 1


def test_candidate_review_cli_can_fail_on_pending(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    out_path = tmp_path / "review_status.json"
    _write_json(reviewed, [])
    _write_json(candidates, {"candidates": [_candidate("pending")]})

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
    assert data["pending_count"] == 1


def test_candidate_review_report_fails_if_candidate_allows_hot_path(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    _write_json(reviewed, [])
    _write_json(candidates, {"candidates": [_candidate("unsafe", hot_path_allowed=True)]})

    report = build_report([candidates], reviewed)

    assert report["status"]["valid"] is False
    assert report["status"]["runtime_isolated"] is False
    assert any(item["reason"] == "candidate_hot_path_allowed" for item in report["invalid_items"])


def test_candidate_review_report_fails_on_network_or_clone_usage(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    _write_json(reviewed, [])
    _write_json(
        candidates,
        {
            "network_used": True,
            "repo_clone_or_download_used": True,
            "runtime_hot_path_used": False,
            "candidates": [
                _candidate("net", network_used=True),
                _candidate("clone", repo_clone_or_download_used=True),
            ],
        },
    )

    report = build_report([candidates], reviewed)

    reasons = {item["reason"] for item in report["invalid_items"]}
    assert "source_network_used" in reasons
    assert "source_repo_clone_or_download_used" in reasons
    assert "candidate_network_used" in reasons
    assert "candidate_repo_clone_or_download_used" in reasons
    assert report["status"]["runtime_isolated"] is False


def test_candidate_review_accept_requires_manual_evidence(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    out_path = tmp_path / "review_status.json"
    _write_json(reviewed, [])
    _write_json(candidates, {"candidates": [_candidate("accepted", review_status="accepted_to_tests")]})

    exit_code = main(
        [
            "--candidates",
            str(candidates),
            "--reviewed-samples",
            str(reviewed),
            "--out",
            str(out_path),
            "--fail-on-invalid",
        ]
    )

    assert exit_code == 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert any(
        item["reason"] == "accepted_without_manual_evidence"
        for item in data["invalid_items"]
    )


def test_candidate_review_cli_passes_when_all_candidates_resolved(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "candidates.json"
    out_path = tmp_path / "review_status.json"
    _write_json(reviewed, [])
    _write_json(
        candidates,
        {
            "runtime_hot_path_used": False,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "candidates": [
                _candidate(
                    "accepted",
                    review_status="accepted_to_tests",
                    accepted_sample_id="manual_sample",
                ),
                _candidate("rejected", review_status="rejected"),
                _candidate("deferred", review_status="deferred"),
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
            "--fail-on-invalid",
            "--fail-on-pending",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["pending_count"] == 0
    assert data["status"]["ready_for_strict_release"] is True


def test_failed_utterance_candidate_blocks_until_manually_resolved(tmp_path):
    reviewed = tmp_path / "route_samples.json"
    candidates = tmp_path / "failed_candidates.json"
    decisions = tmp_path / "decisions.json"
    out_path = tmp_path / "review_status.json"
    _write_json(reviewed, [])
    _write_json(
        candidates,
        {
            "schema_version": 1,
            "runtime_hot_path_used": False,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "candidates": [
                    _candidate(
                        "failed_text_polishing_case",
                        text="帮我润色这句普通短句，不要扩写：今天会议我可能晚十分钟到。",
                        expected_task_type="text_polishing",
                        expected_domain="general",
                        current_task_type="text_polishing",
                        current_domain="general",
                    )
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
    assert data["pending_count"] == 1

    _write_json(
        decisions,
        {
            "decisions": [
                {
                    "candidate_id": "failed_text_polishing_case",
                    "review_status": "deferred",
                    "review_notes": "Backlog only; do not auto-promote.",
                }
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
            "--fail-on-pending",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["pending_count"] == 0
    assert data["by_status"]["deferred"] == 1
