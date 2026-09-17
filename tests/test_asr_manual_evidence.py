from __future__ import annotations

import json
import wave

from scripts import asr_manual_evidence


def _write_config(path):
    path.write_text(
        """
asr:
  engine: funasr
  model: paraformer-zh
  language: zh
  device: cpu
  fallback_device: cpu
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_asr_manual_evidence_default_is_skipped_receipt(tmp_path):
    cases = tmp_path / "cases.json"
    config = tmp_path / "config.yaml"
    cases.write_text('{"schema_version":1,"cases":[]}\n', encoding="utf-8")
    _write_config(config)

    report = asr_manual_evidence.build_report(cases_path=cases, config_path=config)

    assert report["script_name"] == "scripts/asr_manual_evidence.py"
    assert report["runtime_hot_path_used"] is False
    assert report["network_used"] is False
    assert report["live_asr_enabled"] is False
    assert report["asr_engine_used"] is False
    assert report["skipped"] is True
    assert report["status"]["passed"] is True


def test_asr_manual_evidence_inspects_wav_without_recognition(tmp_path):
    cases = tmp_path / "cases.json"
    config = tmp_path / "config.yaml"
    wav_path = tmp_path / "sample.wav"
    cases.write_text('{"schema_version":1,"cases":[]}\n', encoding="utf-8")
    _write_config(config)
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)

    report = asr_manual_evidence.build_report(
        cases_path=cases,
        config_path=config,
        wav_path=wav_path,
        expected_text="测试",
    )

    assert report["skipped"] is False
    assert report["wav"]["sample_rate"] == 16000
    assert report["wav"]["channels"] == 1
    assert report["status"]["passed"] is True


def test_asr_manual_evidence_cli_fail_flag(tmp_path):
    cases = tmp_path / "missing.json"
    config = tmp_path / "config.yaml"
    out_path = tmp_path / "asr.json"
    _write_config(config)

    exit_code = asr_manual_evidence.main(
        ["--cases", str(cases), "--config", str(config), "--out", str(out_path), "--fail-on-error"]
    )

    assert exit_code == 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["passed"] is False

