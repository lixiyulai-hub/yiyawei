from __future__ import annotations

import json
from pathlib import Path

from scripts.build_route_sample_promotion_draft import build_draft, main
from scripts.governance_artifacts import sha256_file


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _accepted_row(candidate_id, sample_id, text):
    return {
        "candidate_id": candidate_id,
        "status": "accepted",
        "reason": "explicit_accepted_status",
        "suggested_sample": {
            "id": sample_id,
            "spoken_type": "代码修复",
            "input": text,
            "expected_task_type": "code_fix",
            "expected_domain": "general",
            "output_shape": ["问题定位", "验证方式"],
            "must_keep": ["定位"],
            "must_drop": ["项目评估"],
        },
        "review_notes": "人工确认。",
        "novice_preview_text": "我会把这段语音整理成：代码修复",
    }


def test_promotion_draft_builds_drafts_without_modifying_route_samples(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    intake = tmp_path / "intake.json"
    _write_json(route_samples, [])
    _write_json(
        intake,
        {
            "schema_version": 1,
            "intake": {
                "accepted_sample_drafts": [
                    _accepted_row("candidate_one", "sample_one", "请修复登录接口报错。")
                ]
            },
        },
    )
    original = route_samples.read_text(encoding="utf-8")

    draft = build_draft(intake, route_samples)

    assert route_samples.read_text(encoding="utf-8") == original
    assert draft["runtime_hot_path_used"] is False
    assert draft["route_samples_sha256"] == sha256_file(route_samples)
    assert draft["intake_package_sha256"] == sha256_file(intake)
    assert draft["draft_sample_count"] == 1
    assert draft["status"]["modified_route_samples"] is False
    assert draft["draft_samples"][0]["sample"]["id"] == "sample_one"


def test_promotion_draft_skips_existing_id_and_input_by_default(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    intake = tmp_path / "intake.json"
    _write_json(
        route_samples,
        [
            {
                "id": "sample_one",
                "input": "请修复登录接口报错。",
                "expected_task_type": "code_fix",
                "expected_domain": "general",
            }
        ],
    )
    _write_json(
        intake,
        {
            "intake": {
                "accepted_sample_drafts": [
                    _accepted_row("candidate_one", "sample_one", "请修复登录接口报错。")
                ]
            }
        },
    )

    draft = build_draft(intake, route_samples)

    assert draft["draft_sample_count"] == 0
    assert draft["skipped_count"] == 1
    assert draft["skipped"][0]["reason"] == "sample_id_already_exists"


def test_promotion_draft_can_include_existing_for_review(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    intake = tmp_path / "intake.json"
    _write_json(route_samples, [{"id": "sample_one", "input": "请修复登录接口报错。"}])
    _write_json(
        intake,
        {"intake": {"accepted_sample_drafts": [_accepted_row("candidate_one", "sample_one", "请修复登录接口报错。")]}},
    )

    draft = build_draft(intake, route_samples, include_existing=True)

    assert draft["draft_sample_count"] == 1
    assert draft["draft_samples"][0]["duplicate_reason"] == "sample_id_already_exists"


def test_promotion_draft_cli_writes_output_but_not_route_samples(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    intake = tmp_path / "intake.json"
    out_path = tmp_path / "promotion.json"
    _write_json(route_samples, [])
    _write_json(
        intake,
        {"intake": {"accepted_sample_drafts": [_accepted_row("candidate_one", "sample_one", "请修复登录接口报错。")]}},
    )
    original = route_samples.read_text(encoding="utf-8")

    exit_code = main(
        [
            "--intake-package",
            str(intake),
            "--route-samples",
            str(route_samples),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    assert route_samples.read_text(encoding="utf-8") == original
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["draft_sample_count"] == 1
    assert data["draft_samples"][0]["patch_preview"] == {
        "op": "add",
        "path": "/-",
        "value": data["draft_samples"][0]["sample"],
    }


def test_promotion_draft_rejects_unsafe_output_paths(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    intake = tmp_path / "intake.json"
    _write_json(route_samples, [])
    _write_json(intake, {"intake": {"accepted_sample_drafts": []}})

    protected_route_samples = Path("tests/route_samples.json")
    original = protected_route_samples.read_text(encoding="utf-8")
    exit_code = main(
        [
            "--intake-package",
            str(intake),
            "--route-samples",
            str(route_samples),
            "--out",
            str(protected_route_samples),
        ]
    )

    assert exit_code == 2
    assert protected_route_samples.read_text(encoding="utf-8") == original

    for forbidden in ("src/not_allowed.json", "app.py", "tests/test_not_allowed.py"):
        exit_code = main(
            [
                "--intake-package",
                str(intake),
                "--route-samples",
                str(route_samples),
                "--out",
                forbidden,
            ]
        )
        assert exit_code == 2


def test_promotion_draft_rejects_unsafe_intake_flags(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    intake = tmp_path / "intake.json"
    _write_json(route_samples, [])
    _write_json(
        intake,
        {
            "runtime_hot_path_used": True,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "status": {"runtime_isolated": True},
            "intake": {"accepted_sample_drafts": []},
        },
    )

    try:
        build_draft(intake, route_samples)
    except ValueError as exc:
        assert "runtime_hot_path_used" in str(exc)
    else:
        raise AssertionError("expected unsafe intake package to fail")


def test_promotion_draft_skips_internal_duplicate_input(tmp_path):
    route_samples = tmp_path / "route_samples.json"
    intake = tmp_path / "intake.json"
    _write_json(route_samples, [])
    _write_json(
        intake,
        {
            "runtime_hot_path_used": False,
            "network_used": False,
            "repo_clone_or_download_used": False,
            "status": {"runtime_isolated": True},
            "intake": {
                "accepted_sample_drafts": [
                    _accepted_row("candidate_one", "sample_one", "请修复登录接口报错。"),
                    _accepted_row("candidate_two", "sample_two", "请修复登录接口报错。"),
                ]
            },
        },
    )

    draft = build_draft(intake, route_samples)

    assert draft["draft_sample_count"] == 1
    assert draft["skipped_count"] == 1
    assert draft["skipped"][0]["reason"] == "draft_sample_input_duplicate"


def test_promotion_draft_helper_stays_offline_static():
    text = Path("scripts/build_route_sample_promotion_draft.py").read_text(encoding="utf-8")

    forbidden = ("requests", "urllib", "socket", "subprocess", "git ", "OpenAI(", "httpx")
    assert all(pattern not in text for pattern in forbidden)
