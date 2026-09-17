#!/usr/bin/env python3
"""Offline package-readiness checks for Yiyawei."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso


DEFAULT_OUTPUT = ROOT / "output" / "package_preflight.json"
SCRIPT_NAME = "scripts/package_preflight.py"
ARTIFACT_VERSION = 1
REQUIRED_ASSETS = (
    "index.html",
    "main.js",
    "js/api-client.js",
    "js/custom-select.js",
    "js/editor-controller.js",
    "js/recording-controller.js",
    "js/settings-controller.js",
    "js/state-machine.js",
    "js/state-renderer.js",
    "js/theme-catalog.js",
    "js/theme-manager.js",
    "js/audio-visualizer.js",
    "styles.css",
    "css/tokens.css",
    "css/themes.css",
    "css/base.css",
    "css/layout.css",
    "css/controls.css",
    "css/recording.css",
    "css/editor.css",
    "icon.svg",
    "app-icon.png",
    "app-icon.ico",
)
SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|credential|cookie)", re.IGNORECASE)
ENV_ASSIGNMENT_RE = re.compile(r"^\s*\$env:([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)
APP_ARG_RE = re.compile(r"parser\.add_argument\(\s*['\"]([^'\"]+)['\"]")


def build_report(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    checks = [
        _check_python_version(),
        _check_requirements(root / "requirements.txt"),
        _check_config(root / "config.yaml", key="config_yaml"),
        _check_config(root / "config.no_paste.yaml", key="config_no_paste_yaml"),
        _check_launcher(root / "scripts" / "Start-VoicePromptCompiler.ps1", root),
        _check_web_assets(root / "src" / "gui" / "web_assets"),
        _check_app_cli(root / "app.py"),
        _check_plugin_bridge_runtime(root / "src" / "plugin_bridge"),
    ]
    flat_checks = [
        item
        for group in checks
        for item in (group if isinstance(group, list) else [group])
    ]
    errors = [item for item in flat_checks if item["status"] == "error"]
    warnings = [item for item in flat_checks if item["status"] == "warning"]
    sources = _source_fingerprints(root)
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "root": str(root),
        "source_count": len(sources),
        "sources": sources,
        "checks": flat_checks,
        "summary": {
            "check_count": len(flat_checks),
            "ok_count": sum(1 for item in flat_checks if item["status"] == "ok"),
            "warning_count": len(warnings),
            "error_count": len(errors),
            "required_dependency_count": _required_dependency_count(root / "requirements.txt"),
        },
        "status": {
            "passed": not errors,
            "valid": not errors,
            "runtime_isolated": True,
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "notes": [
            "This is an offline packaging readiness report.",
            "Warnings describe environment or operator work still needed; errors are structural blockers.",
        ],
    }


def _check_python_version() -> dict[str, Any]:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= (3, 10):
        return _ok("python_version", f"Python {version}")
    return _error("python_version", f"Python {version}; expected 3.10+")


def _check_requirements(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return [_error("requirements_file", f"missing {path}")]
    dependencies = _read_requirements(path)
    checks = [_ok("requirements_file", f"{len(dependencies)} dependencies listed")]
    for package in dependencies:
        module = _module_name_for_requirement(package)
        installed = importlib.util.find_spec(module) is not None
        status = "ok" if installed else "warning"
        checks.append(
            _check(
                f"dependency:{package}",
                status,
                f"import module {module}: {'available' if installed else 'not importable in current interpreter'}",
            )
        )
    return checks


def _check_config(path: Path, *, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return [_error(key, f"missing {path}")]
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return [_error(key, f"cannot parse YAML: {exc}")]
    if not isinstance(config, dict):
        return [_error(key, "YAML root must be an object")]

    checks = [_ok(key, "YAML parsed")]
    for section in ("app", "llm", "fast_llm", "injector", "storage", "safety", "glossary"):
        if section in config:
            checks.append(_ok(f"{key}:{section}", "present"))
        else:
            checks.append(_warning(f"{key}:{section}", "section missing"))

    secrets = _find_secret_like_values(config)
    if secrets:
        checks.append(_error(f"{key}:secret_redaction", f"secret-like config values present: {', '.join(secrets[:8])}"))
    else:
        checks.append(_ok(f"{key}:secret_redaction", "no obvious inline secrets"))

    if key == "config_no_paste_yaml":
        auto_paste = ((config.get("injector") or {}).get("auto_paste"))
        if auto_paste is False:
            checks.append(_ok(f"{key}:no_paste", "injector.auto_paste=false"))
        else:
            checks.append(_error(f"{key}:no_paste", "config.no_paste.yaml must keep injector.auto_paste=false"))

    if key == "config_yaml":
        auto_paste = ((config.get("injector") or {}).get("auto_paste"))
        if isinstance(auto_paste, bool):
            checks.append(_ok(f"{key}:auto_paste_declared", f"injector.auto_paste={auto_paste}"))
        else:
            checks.append(_warning(f"{key}:auto_paste_declared", "injector.auto_paste not declared"))
    return checks


def _check_launcher(path: Path, root: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return [_error("launcher:powershell", f"missing {path}")]
    text = path.read_text(encoding="utf-8")
    checks = [_ok("launcher:powershell", "Start-VoicePromptCompiler.ps1 present")]
    if ".venv\\Scripts\\python.exe" in text:
        checks.append(_ok("launcher:venv_python", "uses project .venv Python"))
    else:
        checks.append(_warning("launcher:venv_python", "does not reference project .venv Python"))
    if '--gui' in text or '"--gui"' in text:
        checks.append(_ok("launcher:gui_entry", "starts app.py --gui"))
    else:
        checks.append(_warning("launcher:gui_entry", "does not start app.py --gui"))
    env_names = sorted(set(ENV_ASSIGNMENT_RE.findall(text)))
    checks.append(_ok("launcher:env_assignments", f"{len(env_names)} env assignments", {"env_names": env_names}))
    hardcoded_paths = [value for value in re.findall(r"[A-Z]:\\[^\"'\r\n]+", text) if str(root) not in value]
    if hardcoded_paths:
        checks.append(
            _warning(
                "launcher:hardcoded_paths",
                "machine-specific paths should be documented or configurable",
                {"paths": hardcoded_paths[:8]},
            )
        )
    else:
        checks.append(_ok("launcher:hardcoded_paths", "no machine-specific absolute paths found"))
    return checks


def _check_web_assets(path: Path) -> list[dict[str, Any]]:
    checks = []
    if not path.exists():
        return [_error("web_assets", f"missing {path}")]
    for asset in REQUIRED_ASSETS:
        target = path / asset
        if target.exists() and target.is_file():
            checks.append(_ok(f"web_asset:{asset}", f"{target.stat().st_size} bytes"))
        else:
            checks.append(_error(f"web_asset:{asset}", "missing required GUI asset"))
    return checks


def _check_app_cli(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return [_error("app_cli", f"missing {path}")]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [_error("app_cli", f"cannot parse app.py: {exc}")]
    text = path.read_text(encoding="utf-8")
    args = sorted(set(APP_ARG_RE.findall(text)))
    required = {"--text", "--mode", "--fast", "--gui", "--tk-gui", "--script", "--daemon", "--daemon-host", "--daemon-port", "--daemon-token"}
    missing = sorted(required.difference(args))
    checks = [_ok("app_cli:syntax", f"parsed {len(list(ast.walk(tree)))} AST nodes")]
    if missing:
        checks.append(_error("app_cli:required_args", f"missing CLI args: {', '.join(missing)}"))
    else:
        checks.append(_ok("app_cli:required_args", "desktop and daemon CLI args present", {"args": args}))
    if "process_text_for_bridge" in text:
        checks.append(_ok("app_cli:bridge_no_paste_entry", "side-effect-free bridge entry present"))
    else:
        checks.append(_error("app_cli:bridge_no_paste_entry", "missing process_text_for_bridge"))
    return checks


def _check_plugin_bridge_runtime(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return [_error("plugin_bridge", f"missing {path}")]
    bridge_file = path / "bridge.py"
    daemon_file = path / "http_daemon.py"
    checks = []
    for target in (bridge_file, daemon_file):
        if target.exists():
            checks.append(_ok(f"plugin_bridge:{target.name}", "present"))
        else:
            checks.append(_error(f"plugin_bridge:{target.name}", "missing"))
    if daemon_file.exists():
        text = daemon_file.read_text(encoding="utf-8")
        if "127.0.0.1" in text and "localhost" in text:
            checks.append(_ok("plugin_bridge:loopback_guard", "loopback bind guard present"))
        else:
            checks.append(_error("plugin_bridge:loopback_guard", "missing loopback bind guard"))
        if "auth_token" in text and "Authorization" in text:
            checks.append(_ok("plugin_bridge:token_auth", "optional bearer token path present"))
        else:
            checks.append(_warning("plugin_bridge:token_auth", "token auth path not obvious"))
        if "max_body_bytes" in text and "max_text_chars" in text:
            checks.append(_ok("plugin_bridge:request_bounds", "body and text bounds present"))
        else:
            checks.append(_error("plugin_bridge:request_bounds", "request bounds missing"))
    return checks


def _source_fingerprints(root: Path) -> list[dict[str, Any]]:
    paths = [
        root / "requirements.txt",
        root / "config.yaml",
        root / "config.no_paste.yaml",
        root / "app.py",
        root / "scripts" / "Start-VoicePromptCompiler.ps1",
        root / "src" / "plugin_bridge" / "bridge.py",
        root / "src" / "plugin_bridge" / "http_daemon.py",
        root / "src" / "gui" / "web_assets" / "index.html",
        root / "src" / "gui" / "web_assets" / "main.js",
        root / "src" / "gui" / "web_assets" / "js" / "api-client.js",
        root / "src" / "gui" / "web_assets" / "js" / "custom-select.js",
        root / "src" / "gui" / "web_assets" / "js" / "editor-controller.js",
        root / "src" / "gui" / "web_assets" / "js" / "recording-controller.js",
        root / "src" / "gui" / "web_assets" / "js" / "settings-controller.js",
        root / "src" / "gui" / "web_assets" / "js" / "state-machine.js",
        root / "src" / "gui" / "web_assets" / "js" / "state-renderer.js",
        root / "src" / "gui" / "web_assets" / "js" / "theme-catalog.js",
        root / "src" / "gui" / "web_assets" / "js" / "theme-manager.js",
        root / "src" / "gui" / "web_assets" / "js" / "audio-visualizer.js",
        root / "src" / "gui" / "web_assets" / "styles.css",
        root / "src" / "gui" / "web_assets" / "css" / "tokens.css",
        root / "src" / "gui" / "web_assets" / "css" / "themes.css",
        root / "src" / "gui" / "web_assets" / "css" / "base.css",
        root / "src" / "gui" / "web_assets" / "css" / "layout.css",
        root / "src" / "gui" / "web_assets" / "css" / "controls.css",
        root / "src" / "gui" / "web_assets" / "css" / "recording.css",
        root / "src" / "gui" / "web_assets" / "css" / "editor.css",
    ]
    sources = []
    for path in paths:
        exists = path.exists()
        sources.append(
            {
                "path": _display_path(path, root),
                "exists": exists,
                "sha256": sha256_file(path) if exists and path.is_file() else "",
            }
        )
    return sources


def _read_requirements(path: Path) -> list[str]:
    dependencies = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        package = re.split(r"[<>=!~\[]", stripped, maxsplit=1)[0].strip()
        if package:
            dependencies.append(package)
    return dependencies


def _required_dependency_count(path: Path) -> int:
    return len(_read_requirements(path)) if path.exists() else 0


def _module_name_for_requirement(package: str) -> str:
    mapping = {
        "pyyaml": "yaml",
        "opencc-python-reimplemented": "opencc",
        "pyautogui": "pyautogui",
    }
    return mapping.get(package.lower(), package.replace("-", "_"))


def _find_secret_like_values(value: Any, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            if SECRET_KEY_RE.search(str(key)) and isinstance(item, str) and item.strip():
                if not item.strip().startswith("<"):
                    hits.append(child)
            hits.extend(_find_secret_like_values(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_find_secret_like_values(item, f"{prefix}[{index}]"))
    return hits


def _ok(name: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _check(name, "ok", message, data)


def _warning(name: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _check(name, "warning", message, data)


def _error(name: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _check(name, "error", message, data)


def _check(name: str, status: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "status": status,
        "message": message,
    }
    if data:
        payload["data"] = data
    return payload


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build offline package preflight evidence")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--root", default=str(ROOT), help="project root override")
    parser.add_argument("--fail-on-error", action="store_true", help="return 1 when structural package errors are found")
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = build_report(Path(args.root))
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            "Package preflight: "
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
