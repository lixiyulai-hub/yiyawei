from __future__ import annotations

import json

from scripts import bridge_smoke_evidence


def test_bridge_smoke_builds_no_paste_evidence_with_fake_processor(tmp_path):
    report = bridge_smoke_evidence.build_evidence(root=tmp_path, raw_text="hello bridge")

    assert report["script_name"] == "scripts/bridge_smoke_evidence.py"
    assert report["network_used"] is False
    assert report["runtime_hot_path_used"] is False
    assert report["local_http_used"] is True
    assert report["live_app_used"] is False
    assert report["status"]["passed"] is True
    assert report["status"]["no_paste_confirmed"] is True
    assert report["response_summary"]["final_text_present"] is True
    assert report["response_summary"]["pasted"] is False
    assert report["response_summary"]["auto_paste_allowed"] is False
    assert report["bridge"]["host"] == "127.0.0.1"


def test_bridge_smoke_cli_writes_report(tmp_path):
    out_path = tmp_path / "bridge_smoke.json"

    exit_code = bridge_smoke_evidence.main(
        [
            "--root",
            str(tmp_path),
            "--out",
            str(out_path),
            "--raw-text",
            "selected text",
            "--fail-on-error",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["passed"] is True
    assert data["source"]["raw_text_preview"] == "selected text"
    assert data["response_summary"]["pasted"] is False


def test_bridge_smoke_missing_wav_fails_cleanly(tmp_path):
    missing = tmp_path / "missing.wav"

    report = bridge_smoke_evidence.build_evidence(root=tmp_path, asr_wav=missing)

    assert report["status"]["passed"] is False
    assert report["source"]["kind"] == "asr_wav"
    assert any(check["name"] == "asr_wav" and check["status"] == "error" for check in report["checks"])


def test_bridge_smoke_cli_fail_on_error_returns_nonzero_for_missing_wav(tmp_path):
    out_path = tmp_path / "bridge_smoke.json"

    exit_code = bridge_smoke_evidence.main(
        [
            "--root",
            str(tmp_path),
            "--out",
            str(out_path),
            "--asr-wav",
            str(tmp_path / "missing.wav"),
            "--fail-on-error",
        ]
    )

    assert exit_code == 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["passed"] is False


def test_bridge_smoke_live_app_path_can_be_monkeypatched(tmp_path, monkeypatch):
    class FakeApp:
        def __init__(self, config_path=None):
            self.config_path = config_path

        def process_text_for_bridge(self, raw_text, mode, *, use_fast=False, output_script=None):
            return {
                "result": {
                    "final_text": f"live:{raw_text}",
                    "mode": mode,
                    "risk_level": "low",
                    "need_confirm": False,
                },
                "record_id": None,
                "pasted": False,
                "debug": {},
                "meta": {"auto_paste_allowed": False, "used_fast": use_fast, "output_script": output_script},
            }

    monkeypatch.setattr("app.VoicePromptCompilerApp", FakeApp)

    report = bridge_smoke_evidence.build_evidence(
        root=tmp_path,
        raw_text="live text",
        live_app=True,
        config_path=tmp_path / "config.no_paste.yaml",
    )

    assert report["live_app_used"] is True
    assert report["status"]["passed"] is True
    assert report["response_summary"]["pasted"] is False
