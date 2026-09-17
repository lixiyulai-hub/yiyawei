#!/usr/bin/env python3
"""Static readiness checks for the VS Code/Cursor plugin proof of concept."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso


DEFAULT_PLUGIN_ROOT = ROOT / "integrations" / "vscode-cursor"
DEFAULT_OUTPUT = ROOT / "output" / "plugin_poc_preflight.json"
SCRIPT_NAME = "scripts/plugin_poc_preflight.py"
ARTIFACT_VERSION = 1
FORBIDDEN_RUNTIME_PATTERNS = (
    "clipboard",
    "sendKeys",
    "ctrl+v",
    "Ctrl+V",
    "pyperclip",
    "exec(",
    "child_process",
)


def build_report(plugin_root: Path = DEFAULT_PLUGIN_ROOT) -> dict[str, Any]:
    plugin_root = plugin_root.resolve()
    package_path = plugin_root / "package.json"
    extension_path = plugin_root / "extension.js"
    readme_path = plugin_root / "README.md"
    checks: list[dict[str, Any]] = []
    package_data: dict[str, Any] = {}

    if package_path.exists():
        try:
            package_data = json.loads(package_path.read_text(encoding="utf-8"))
            checks.append(_ok("package_json", "package.json parsed"))
        except json.JSONDecodeError as exc:
            checks.append(_error("package_json", f"cannot parse package.json: {exc}"))
    else:
        checks.append(_error("package_json", "missing package.json"))

    if package_data:
        checks.extend(_check_package(package_data))

    if extension_path.exists():
        text = extension_path.read_text(encoding="utf-8")
        checks.append(_ok("extension_js", "extension.js present"))
        checks.extend(_check_extension_source(text))
    else:
        checks.append(_error("extension_js", "missing extension.js"))

    if readme_path.exists():
        checks.append(_ok("readme", "README present"))
    else:
        checks.append(_warning("readme", "plugin README missing"))

    errors = [check for check in checks if check["status"] == "error"]
    warnings = [check for check in checks if check["status"] == "warning"]
    sources = _source_fingerprints(plugin_root)
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "plugin_root": str(plugin_root),
        "source_count": len(sources),
        "sources": sources,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "ok_count": sum(1 for check in checks if check["status"] == "ok"),
            "warning_count": len(warnings),
            "error_count": len(errors),
        },
        "status": {
            "passed": not errors,
            "valid": not errors,
            "runtime_isolated": True,
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "notes": [
            "This checks a local editor-extension proof of concept only.",
            "The extension calls the loopback bridge; it is not a packaging or marketplace receipt.",
        ],
    }


def _check_package(data: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if data.get("main") == "./extension.js":
        checks.append(_ok("package_main", "main points to extension.js"))
    else:
        checks.append(_error("package_main", "main must be ./extension.js"))
    commands = ((data.get("contributes") or {}).get("commands") or [])
    command_ids = {item.get("command") for item in commands if isinstance(item, dict)}
    required = {"voicePromptCompiler.processSelection", "voicePromptCompiler.processInput"}
    missing = sorted(required.difference(command_ids))
    if missing:
        checks.append(_error("package_commands", f"missing commands: {', '.join(missing)}"))
    else:
        checks.append(_ok("package_commands", "selection and input commands present"))
    properties = (((data.get("contributes") or {}).get("configuration") or {}).get("properties") or {})
    bridge_url = (properties.get("voicePromptCompiler.bridgeUrl") or {}).get("default")
    if bridge_url == "http://127.0.0.1:8765":
        checks.append(_ok("package_bridge_url", "default bridge URL is loopback"))
    else:
        checks.append(_error("package_bridge_url", "default bridge URL must be http://127.0.0.1:8765"))
    return checks


def _check_extension_source(text: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if "/v1/process-text" in text:
        checks.append(_ok("extension_endpoint", "calls /v1/process-text"))
    else:
        checks.append(_error("extension_endpoint", "must call /v1/process-text"))
    if "assertLoopback" in text and "127.0.0.1" in text and "localhost" in text:
        checks.append(_ok("extension_loopback_guard", "loopback guard present"))
    else:
        checks.append(_error("extension_loopback_guard", "missing loopback guard"))
    if "Authorization" in text and "Bearer" in text:
        checks.append(_ok("extension_token", "optional bearer token path present"))
    else:
        checks.append(_warning("extension_token", "token path not obvious"))
    if "need_confirm" in text and "risk_level" in text:
        checks.append(_ok("extension_risk_review", "risk review prompt present"))
    else:
        checks.append(_warning("extension_risk_review", "risk review prompt not obvious"))
    forbidden = [pattern for pattern in FORBIDDEN_RUNTIME_PATTERNS if re.search(re.escape(pattern), text, re.IGNORECASE)]
    if forbidden:
        checks.append(_error("extension_forbidden_side_effects", f"forbidden patterns: {', '.join(sorted(set(forbidden)))}"))
    else:
        checks.append(_ok("extension_forbidden_side_effects", "no clipboard/paste/shell side effects found"))
    return checks


def _source_fingerprints(plugin_root: Path) -> list[dict[str, Any]]:
    paths = [plugin_root / "package.json", plugin_root / "extension.js", plugin_root / "README.md"]
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


def _check(name: str, status: str, message: str) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message}


def _ok(name: str, message: str) -> dict[str, Any]:
    return _check(name, "ok", message)


def _warning(name: str, message: str) -> dict[str, Any]:
    return _check(name, "warning", message)


def _error(name: str, message: str) -> dict[str, Any]:
    return _check(name, "error", message)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check VS Code/Cursor plugin POC readiness")
    parser.add_argument("--plugin-root", default=str(DEFAULT_PLUGIN_ROOT), help="plugin POC directory")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--fail-on-error", action="store_true", help="return 1 when structural errors are found")
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = build_report(Path(args.plugin_root))
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            "Plugin POC preflight: "
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
