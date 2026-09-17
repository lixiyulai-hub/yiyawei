#!/usr/bin/env python3
"""Build offline ASR wav/manual evidence without touching the hot path."""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso


DEFAULT_CASES = ROOT / "data" / "asr_manual_evidence_cases.json"
DEFAULT_CONFIG = ROOT / "config.yaml"
DEFAULT_OUTPUT = ROOT / "output" / "asr_manual_evidence.json"
SCRIPT_NAME = "scripts/asr_manual_evidence.py"
ARTIFACT_VERSION = 1


def build_report(
    *,
    cases_path: Path = DEFAULT_CASES,
    config_path: Path = DEFAULT_CONFIG,
    wav_path: Path | None = None,
    expected_text: str = "",
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    cases_data, cases_checks = _load_cases(cases_path)
    checks.extend(cases_checks)
    config, config_checks = _load_config(config_path)
    checks.extend(config_checks)

    wav_summary: dict[str, Any] = {}
    if wav_path is not None:
        wav_summary, wav_checks = _inspect_wav(wav_path, expected_text=expected_text)
        checks.extend(wav_checks)
    else:
        checks.append(_warning("wav_fixture", "no wav fixture supplied; receipt is manual/skipped evidence"))

    cases = cases_data.get("cases") if isinstance(cases_data.get("cases"), list) else []
    if not cases:
        checks.append(_warning("cases", "no reviewed ASR evidence cases are listed yet"))
    else:
        for index, case in enumerate(cases):
            checks.extend(_check_case(case, index))

    errors = [check for check in checks if check["status"] == "error"]
    warnings = [check for check in checks if check["status"] == "warning"]
    sources = _source_fingerprints(cases_path, config_path, wav_path)
    asr_config = config.get("asr") if isinstance(config.get("asr"), dict) else {}
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "live_asr_enabled": False,
        "asr_engine_used": False,
        "skipped": wav_path is None,
        "cases_path": str(cases_path),
        "cases_sha256": sha256_file(cases_path) if cases_path.exists() else "",
        "config_path": str(config_path),
        "source_count": len(sources),
        "sources": sources,
        "asr_config": {
            "engine": asr_config.get("engine"),
            "model": asr_config.get("model"),
            "language": asr_config.get("language"),
            "device": asr_config.get("device"),
            "fallback_device": asr_config.get("fallback_device"),
        },
        "wav": wav_summary,
        "case_count": len(cases),
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "ok_count": sum(1 for check in checks if check["status"] == "ok"),
            "warning_count": len(warnings),
            "error_count": len(errors),
            "case_count": len(cases),
            "wav_supplied": wav_path is not None,
        },
        "status": {
            "passed": not errors,
            "valid": not errors,
            "runtime_isolated": True,
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "notes": [
            "This receipt is offline evidence only and never loads the ASR model by default.",
            "Live microphone and recognition checks remain explicit operator/manual evidence.",
        ],
    }


def _load_cases(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not path.exists():
        return {}, [_error("cases_file", f"missing {path}")]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [_error("cases_file", f"cannot parse JSON: {exc}")]
    if not isinstance(data, dict):
        return {}, [_error("cases_file", "JSON root must be an object")]
    checks = [_ok("cases_file", "JSON parsed")]
    if data.get("schema_version") != 1:
        checks.append(_error("cases_schema", "schema_version must be 1"))
    if not isinstance(data.get("cases"), list):
        checks.append(_error("cases_schema", "cases must be a list"))
    return data, checks


def _load_config(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not path.exists():
        return {}, [_error("config", f"missing {path}")]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {}, [_error("config", f"cannot parse YAML: {exc}")]
    if not isinstance(data, dict):
        return {}, [_error("config", "YAML root must be an object")]
    checks = [_ok("config", "YAML parsed")]
    asr = data.get("asr") if isinstance(data.get("asr"), dict) else {}
    if asr.get("engine") == "funasr":
        checks.append(_ok("asr_engine", "FunASR engine configured"))
    else:
        checks.append(_error("asr_engine", "asr.engine must be funasr for the current product path"))
    if asr.get("model"):
        checks.append(_ok("asr_model", f"model={asr.get('model')}"))
    else:
        checks.append(_error("asr_model", "missing asr.model"))
    return data, checks


def _inspect_wav(path: Path, *, expected_text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not path.exists():
        return {}, [_error("wav_fixture", f"missing {path}")]
    checks: list[dict[str, Any]] = []
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            sample_width = handle.getsampwidth()
    except Exception as exc:
        return {}, [_error("wav_fixture", f"cannot inspect wav: {exc}")]
    duration_sec = frame_count / sample_rate if sample_rate else 0.0
    if channels == 1:
        checks.append(_ok("wav_channels", "mono wav"))
    else:
        checks.append(_warning("wav_channels", f"{channels} channels; ASR path expects mono when possible"))
    if sample_rate == 16000:
        checks.append(_ok("wav_sample_rate", "16000 Hz"))
    else:
        checks.append(_warning("wav_sample_rate", f"{sample_rate} Hz; production recorder uses 16000 Hz"))
    if duration_sec > 0:
        checks.append(_ok("wav_duration", f"{duration_sec:.3f}s"))
    else:
        checks.append(_error("wav_duration", "wav has no frames"))
    if expected_text:
        checks.append(_ok("expected_text", "manual expected text supplied"))
    else:
        checks.append(_warning("expected_text", "no manual expected text supplied"))
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "channels": channels,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
        "sample_width": sample_width,
        "duration_sec": round(duration_sec, 4),
        "expected_text_supplied": bool(expected_text),
    }, checks


def _check_case(case: Any, index: int) -> list[dict[str, Any]]:
    if not isinstance(case, dict):
        return [_error(f"case:{index}", "case must be an object")]
    checks: list[dict[str, Any]] = []
    case_id = str(case.get("id") or f"case:{index}")
    for field in ("id", "wav_path", "expected_text"):
        if case.get(field):
            checks.append(_ok(f"{case_id}:{field}", "present"))
        else:
            checks.append(_error(f"{case_id}:{field}", "missing"))
    return checks


def _source_fingerprints(cases_path: Path, config_path: Path, wav_path: Path | None) -> list[dict[str, Any]]:
    paths = [cases_path, config_path]
    if wav_path is not None:
        paths.append(wav_path)
    sources = []
    for path in paths:
        exists = path.exists()
        sources.append(
            {
                "path": str(path),
                "exists": exists,
                "sha256": sha256_file(path) if exists and path.is_file() else "",
            }
        )
    return sources


def _check(name: str, status: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status, "message": message}
    if data:
        payload["data"] = data
    return payload


def _ok(name: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _check(name, "ok", message, data)


def _warning(name: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _check(name, "warning", message, data)


def _error(name: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _check(name, "error", message, data)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build offline ASR manual/wav evidence")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="ASR evidence case file")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="config file to inspect")
    parser.add_argument("--wav", default=None, help="optional wav fixture to inspect without recognition")
    parser.add_argument("--expected-text", default="", help="manual expected text for the wav fixture")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--fail-on-error", action="store_true", help="return 1 when structural errors are found")
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = build_report(
        cases_path=Path(args.cases),
        config_path=Path(args.config),
        wav_path=Path(args.wav) if args.wav else None,
        expected_text=str(args.expected_text or ""),
    )
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            "ASR manual evidence: "
            f"checks={report['summary']['check_count']}, "
            f"errors={report['summary']['error_count']}, "
            f"warnings={report['summary']['warning_count']}, "
            f"passed={report['status']['passed']}"
        )
    if args.fail_on_error and not report["status"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
