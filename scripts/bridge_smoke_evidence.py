#!/usr/bin/env python3
"""Build local bridge smoke evidence without touching clipboard or paste state."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso
from src.auditor.schema import AuditResult
from src.plugin_bridge.bridge import PluginBridge, PluginBridgeConfig
from src.plugin_bridge.http_daemon import create_server


DEFAULT_OUTPUT = ROOT / "output" / "bridge_smoke_evidence.json"
SCRIPT_NAME = "scripts/bridge_smoke_evidence.py"
ARTIFACT_VERSION = 1
DEFAULT_RAW_TEXT = "帮我整理这个需求，先说明问题，再生成可以发给 Cursor 的提示词。"


def build_evidence(
    *,
    root: Path = ROOT,
    raw_text: str = DEFAULT_RAW_TEXT,
    mode: str = "cursor_prompt",
    output_script: str = "simplified",
    use_fast: bool = False,
    token: str = "bridge-smoke-token",
    asr_wav: Path | None = None,
    config_path: Path | None = None,
    live_app: bool = False,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    root = root.resolve()
    checks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    source = _resolve_source_text(
        raw_text=raw_text,
        asr_wav=asr_wav,
        config_path=config_path,
        checks=checks,
        warnings=warnings,
        errors=errors,
    )
    resolved_text = str(source.get("raw_text") or "").strip()
    if not resolved_text:
        errors.append(_check("source_text", "error", "source text is empty"))
        resolved_text = raw_text.strip() or DEFAULT_RAW_TEXT

    process_fn = _build_live_process_fn(config_path) if live_app else _fake_process_text
    bridge = PluginBridge(
        process_fn,
        PluginBridgeConfig(
            enabled=True,
            host="127.0.0.1",
            ipc_port=0,
            max_body_bytes=2048,
            max_text_chars=8000,
            auth_token=token,
        ),
    )

    server = create_server(bridge, port=0).start()
    try:
        base_url = server.url
        health = _request_json(f"{base_url}/health", timeout_sec=timeout_sec)
        _record_status_check(checks, errors, "health_public", health, 200)

        unauthorized_status = _request_json(f"{base_url}/status", timeout_sec=timeout_sec)
        _record_status_check(checks, errors, "status_requires_auth", unauthorized_status, 401)

        status = _request_json(f"{base_url}/status", token=token, timeout_sec=timeout_sec)
        _record_status_check(checks, errors, "status_with_auth", status, 200)
        status_body = status.get("body") if isinstance(status.get("body"), dict) else {}
        bridge_status = status_body.get("status") if isinstance(status_body.get("status"), dict) else {}
        if bridge_status.get("host") == "127.0.0.1" and bridge_status.get("force_no_paste") is True:
            checks.append(_check("bridge_status_no_paste_loopback", "ok", "loopback and no-paste status confirmed"))
        else:
            errors.append(_check("bridge_status_no_paste_loopback", "error", "bridge status did not confirm loopback/no-paste"))

        process_payload = {
            "raw_text": resolved_text,
            "mode": mode,
            "use_fast": use_fast,
            "output_script": output_script,
            "include_debug": False,
        }
        process = _request_json(
            f"{base_url}/v1/process-text",
            data=process_payload,
            token=token,
            timeout_sec=timeout_sec,
        )
        _record_status_check(checks, errors, "process_text", process, 200)
        process_body = process.get("body") if isinstance(process.get("body"), dict) else {}
        _check_process_invariants(checks, errors, process_body)

        oversize = _request_json(
            f"{base_url}/v1/process-text",
            data={"raw_text": "x" * 3000},
            token=token,
            timeout_sec=timeout_sec,
        )
        _record_status_check(checks, errors, "oversize_rejected", oversize, 413)
    finally:
        server.shutdown()

    checks.extend(warnings)
    checks.extend(errors)
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "local_http_used": True,
        "live_app_used": bool(live_app),
        "source": {
            "kind": source.get("kind"),
            "raw_text_chars": len(resolved_text),
            "raw_text_preview": resolved_text[:120],
            "asr": source.get("asr"),
        },
        "bridge": {
            "host": "127.0.0.1",
            "auth_required": True,
            "endpoint": "/v1/process-text",
            "mode": mode,
            "output_script": output_script,
            "use_fast": use_fast,
        },
        "response_summary": {
            "final_text_present": bool(process_body.get("final_text")),
            "final_text_chars": len(str(process_body.get("final_text") or "")),
            "risk_level": ((process_body.get("result") or {}).get("risk_level") if isinstance(process_body.get("result"), dict) else None),
            "need_confirm": ((process_body.get("result") or {}).get("need_confirm") if isinstance(process_body.get("result"), dict) else None),
            "pasted": process_body.get("pasted"),
            "auto_paste_allowed": process_body.get("auto_paste_allowed"),
        },
        "source_count": len(_source_fingerprints(root)),
        "sources": _source_fingerprints(root),
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "ok_count": sum(1 for item in checks if item["status"] == "ok"),
            "warning_count": sum(1 for item in checks if item["status"] == "warning"),
            "error_count": sum(1 for item in checks if item["status"] == "error"),
        },
        "status": {
            "passed": not errors,
            "valid": not errors,
            "runtime_isolated": True,
            "no_paste_confirmed": not errors and process_body.get("pasted") is False and process_body.get("auto_paste_allowed") is False,
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "notes": [
            "Default mode uses a fake processor and real local HTTP bridge.",
            "Use --asr-wav only when local ASR dependencies and models are ready.",
            "Use --live-app only for a deliberate live LLM smoke run.",
        ],
    }


def _resolve_source_text(
    *,
    raw_text: str,
    asr_wav: Path | None,
    config_path: Path | None,
    checks: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    if not asr_wav:
        checks.append(_check("source_text", "ok", "using provided raw text"))
        return {"kind": "text", "raw_text": raw_text, "asr": {"enabled": False}}

    wav_path = asr_wav.expanduser().resolve()
    if not wav_path.exists():
        errors.append(_check("asr_wav", "error", f"wav file missing: {wav_path}"))
        return {"kind": "asr_wav", "raw_text": "", "asr": {"enabled": True, "wav_path": str(wav_path), "ok": False}}

    try:
        from src.asr import create_asr_engine
        from src.config import load_config
    except Exception as exc:
        errors.append(_check("asr_import", "error", f"ASR imports failed: {exc}"))
        return {"kind": "asr_wav", "raw_text": "", "asr": {"enabled": True, "wav_path": str(wav_path), "ok": False}}

    try:
        config = load_config(config_path)
        asr_cfg = dict(config.get("asr") or {})
        engine = create_asr_engine(asr_cfg)
        started = time.perf_counter()
        text = engine.transcribe(str(wav_path))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if not text.strip():
            warnings.append(_check("asr_transcribe", "warning", "ASR returned empty text"))
        else:
            checks.append(_check("asr_transcribe", "ok", "ASR returned text"))
        return {
            "kind": "asr_wav",
            "raw_text": text,
            "asr": {
                "enabled": True,
                "ok": bool(text.strip()),
                "wav_path": str(wav_path),
                "engine": asr_cfg.get("engine", "funasr"),
                "model": getattr(engine, "model_name", asr_cfg.get("model", "")),
                "device": getattr(engine, "device", asr_cfg.get("device", "")),
                "elapsed_ms": elapsed_ms,
                "load_ms": getattr(engine, "last_load_ms", 0),
                "infer_ms": getattr(engine, "last_infer_ms", 0),
                "fallback_used": bool(getattr(engine, "config", {}).get("fallback_used")),
            },
        }
    except Exception as exc:
        errors.append(_check("asr_transcribe", "error", str(exc)[:300]))
        return {"kind": "asr_wav", "raw_text": "", "asr": {"enabled": True, "wav_path": str(wav_path), "ok": False}}


def _build_live_process_fn(config_path: Path | None):
    from app import VoicePromptCompilerApp

    app = VoicePromptCompilerApp(config_path=str(config_path) if config_path else "config.no_paste.yaml")
    return app.process_text_for_bridge


def _fake_process_text(raw_text: str, mode: str, *, use_fast: bool = False, output_script: str | None = None) -> dict[str, Any]:
    return {
        "result": AuditResult(
            final_text=f"compiled:{raw_text}",
            mode=mode,  # type: ignore[arg-type]
            intent_summary="bridge smoke",
            risk_level="low",
            need_confirm=False,
        ),
        "record_id": None,
        "pasted": False,
        "debug": {"raw_asr_text": raw_text, "bridge_smoke": True},
        "meta": {
            "llm_provider": "fake",
            "llm_model": "fake-bridge-smoke",
            "used_fast": use_fast,
            "output_script": output_script,
            "auto_paste_allowed": False,
        },
    }


def _request_json(
    url: str,
    *,
    data: dict[str, Any] | None = None,
    token: str | None = None,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    headers = {}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers)
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            return {
                "status": response.status,
                "body": json.loads(response.read().decode("utf-8")),
            }
    except HTTPError as exc:
        return {
            "status": exc.code,
            "body": json.loads(exc.read().decode("utf-8")),
        }


def _record_status_check(
    checks: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    name: str,
    response: dict[str, Any],
    expected_status: int,
) -> None:
    actual = int(response.get("status") or 0)
    if actual == expected_status:
        checks.append(_check(name, "ok", f"HTTP {actual}"))
    else:
        errors.append(_check(name, "error", f"expected HTTP {expected_status}, got {actual}"))


def _check_process_invariants(
    checks: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    if payload.get("ok") is True and payload.get("final_text"):
        checks.append(_check("process_final_text", "ok", "final_text present"))
    else:
        errors.append(_check("process_final_text", "error", "final_text missing"))
    if payload.get("pasted") is False:
        checks.append(_check("process_no_paste", "ok", "pasted=false"))
    else:
        errors.append(_check("process_no_paste", "error", "pasted was not false"))
    if payload.get("auto_paste_allowed") is False:
        checks.append(_check("process_auto_paste_disallowed", "ok", "auto_paste_allowed=false"))
    else:
        errors.append(_check("process_auto_paste_disallowed", "error", "auto_paste_allowed was not false"))
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if result.get("risk_level") in {"low", "medium", "high"}:
        checks.append(_check("process_risk_level", "ok", f"risk_level={result.get('risk_level')}"))
    else:
        errors.append(_check("process_risk_level", "error", "risk_level missing or invalid"))


def _source_fingerprints(root: Path) -> list[dict[str, Any]]:
    paths = [
        root / "scripts" / "bridge_smoke_evidence.py",
        root / "src" / "plugin_bridge" / "bridge.py",
        root / "src" / "plugin_bridge" / "http_daemon.py",
        root / "src" / "auditor" / "schema.py",
        root / "src" / "asr" / "__init__.py",
        root / "src" / "asr" / "funasr_engine.py",
        root / "app.py",
    ]
    result = []
    for path in paths:
        exists = path.exists()
        result.append(
            {
                "path": _display_path(path, root),
                "exists": exists,
                "sha256": sha256_file(path) if exists and path.is_file() else "",
            }
        )
    return result


def _check(name: str, status: str, message: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
    }


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build local bridge smoke evidence")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON evidence output path")
    parser.add_argument("--root", default=str(ROOT), help="project root override")
    parser.add_argument("--raw-text", default=DEFAULT_RAW_TEXT, help="raw text used when --asr-wav is omitted")
    parser.add_argument("--mode", default="cursor_prompt", help="bridge processing mode")
    parser.add_argument("--output-script", default="simplified", help="simplified | traditional | auto")
    parser.add_argument("--fast", action="store_true", help="request fast processing")
    parser.add_argument("--token", default="bridge-smoke-token", help="local bearer token for the smoke daemon")
    parser.add_argument("--asr-wav", default=None, help="optional wav file to transcribe before bridge processing")
    parser.add_argument("--config", default=None, help="config path for optional ASR/live app smoke")
    parser.add_argument("--live-app", action="store_true", help="use the real Yiyawei app instead of the fake processor")
    parser.add_argument("--timeout-sec", type=float, default=5.0, help="HTTP request timeout")
    parser.add_argument("--fail-on-error", action="store_true", help="return 1 when smoke invariants fail")
    parser.add_argument("--print-json", action="store_true", help="print JSON evidence")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = build_evidence(
        root=Path(args.root),
        raw_text=str(args.raw_text),
        mode=str(args.mode),
        output_script=str(args.output_script),
        use_fast=bool(args.fast),
        token=str(args.token),
        asr_wav=Path(args.asr_wav) if args.asr_wav else None,
        config_path=Path(args.config) if args.config else None,
        live_app=bool(args.live_app),
        timeout_sec=float(args.timeout_sec),
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
            "Bridge smoke evidence: "
            f"checks={report['summary']['check_count']}, "
            f"errors={report['summary']['error_count']}, "
            f"warnings={report['summary']['warning_count']}, "
            f"no_paste={report['status']['no_paste_confirmed']}, "
            f"passed={report['status']['passed']}"
        )
    if args.fail_on_error and not report["status"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
