#!/usr/bin/env python3
"""Offline PyInstaller readiness receipt without building an executable."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso


DEFAULT_SPEC = ROOT / "packaging" / "VoicePromptCompiler.spec"
DEFAULT_OUTPUT = ROOT / "output" / "pyinstaller_readiness.json"
SCRIPT_NAME = "scripts/pyinstaller_readiness.py"
ARTIFACT_VERSION = 1
REQUIRED_DATAS = ("config.yaml", "config.no_paste.yaml", "src/gui/web_assets", "src/glossary/tech_terms.json")
REQUIRED_IMPORTS = ("funasr", "modelscope", "sounddevice", "soundfile", "yaml", "opencc", "pyautogui", "pyperclip")


def build_report(*, spec_path: Path = DEFAULT_SPEC, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    checks: list[dict[str, Any]] = []
    spec_text = ""
    if spec_path.exists():
        spec_text = spec_path.read_text(encoding="utf-8")
        checks.append(_ok("spec_file", "spec file present"))
    else:
        checks.append(_error("spec_file", f"missing {spec_path}"))

    if spec_text:
        checks.extend(_check_spec_text(spec_text))
    checks.extend(_check_required_files(root))
    checks.extend(_check_pyinstaller_imports())

    errors = [check for check in checks if check["status"] == "error"]
    warnings = [check for check in checks if check["status"] == "warning"]
    sources = _source_fingerprints(root, spec_path)
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "build_executed": False,
        "spec_path": str(spec_path),
        "entrypoint": "app.py",
        "dist_path": str(root / "dist"),
        "build_path": str(root / "build"),
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
            "This is a readiness receipt only; it does not run PyInstaller.",
            "Actual bundle builds should be explicit and machine-specific.",
        ],
    }


def _check_spec_text(text: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        module = ast.parse(text)
    except SyntaxError as error:
        checks.append(_error("spec_syntax", f"invalid Python spec: {error.msg}"))
        return checks

    checks.append(_ok("spec_syntax", "valid Python spec"))
    if _has_project_root(module) and _has_root_relative_analysis_entrypoint(module, "app.py"):
        checks.append(_ok("spec_entrypoint", "app.py entrypoint resolves from SPECPATH project root"))
    else:
        checks.append(_error("spec_entrypoint", "spec must analyze app.py from the SPECPATH project root"))
    for item in REQUIRED_DATAS:
        if item in text:
            checks.append(_ok(f"spec_data:{item}", "included"))
        else:
            checks.append(_error(f"spec_data:{item}", "missing from datas"))
    missing_imports = [name for name in REQUIRED_IMPORTS if name not in text]
    if missing_imports:
        checks.append(_warning("spec_hiddenimports", f"not obvious in spec: {', '.join(missing_imports)}"))
    else:
        checks.append(_ok("spec_hiddenimports", "core hidden imports declared"))
    if re.search(r"OPENAI_API_KEY|token\s*=|password\s*=", text, re.IGNORECASE):
        checks.append(_error("spec_secret_scan", "secret-like text present in spec"))
    else:
        checks.append(_ok("spec_secret_scan", "no obvious secrets in spec"))
    return checks


def _has_project_root(module: ast.Module) -> bool:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "PROJECT_ROOT" for target in node.targets):
            continue
        value = node.value
        if not isinstance(value, ast.Attribute) or value.attr != "parent":
            continue
        resolved = value.value
        if not isinstance(resolved, ast.Call) or not isinstance(resolved.func, ast.Attribute) or resolved.func.attr != "resolve":
            continue
        path_call = resolved.func.value
        if not isinstance(path_call, ast.Call) or not isinstance(path_call.func, ast.Name) or path_call.func.id != "Path":
            continue
        if len(path_call.args) == 1 and isinstance(path_call.args[0], ast.Name) and path_call.args[0].id == "SPECPATH":
            return True
    return False


def _has_root_relative_analysis_entrypoint(module: ast.Module, relative: str) -> bool:
    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "Analysis" or not node.args:
            continue
        entrypoints = node.args[0]
        if not isinstance(entrypoints, (ast.List, ast.Tuple)) or len(entrypoints.elts) != 1:
            continue
        entrypoint = entrypoints.elts[0]
        if _is_project_root_path(entrypoint, relative):
            return True
    return False


def _is_project_root_path(node: ast.AST, relative: str) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "str" or len(node.args) != 1:
        return False
    expression = node.args[0]
    if not isinstance(expression, ast.BinOp) or not isinstance(expression.op, ast.Div):
        return False
    return (
        isinstance(expression.left, ast.Name)
        and expression.left.id == "PROJECT_ROOT"
        and isinstance(expression.right, ast.Constant)
        and expression.right.value == relative
    )


def _check_required_files(root: Path) -> list[dict[str, Any]]:
    checks = []
    for relative in ("app.py", "config.yaml", "config.no_paste.yaml", "requirements.txt", "src/gui/web_assets/index.html"):
        path = root / relative
        if path.exists():
            checks.append(_ok(f"file:{relative}", "present"))
        else:
            checks.append(_error(f"file:{relative}", "missing"))
    return checks


def _check_pyinstaller_imports() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if importlib.util.find_spec("PyInstaller") is None:
        checks.append(_warning("dependency:PyInstaller", "not importable in current interpreter"))
    else:
        checks.append(_ok("dependency:PyInstaller", "importable"))
    return checks


def _source_fingerprints(root: Path, spec_path: Path) -> list[dict[str, Any]]:
    paths = [
        spec_path,
        root / "app.py",
        root / "requirements.txt",
        root / "config.yaml",
        root / "config.no_paste.yaml",
        root / "src" / "gui" / "web_assets" / "index.html",
    ]
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
    parser = argparse.ArgumentParser(description="Build PyInstaller readiness receipt")
    parser.add_argument("--spec", default=str(DEFAULT_SPEC), help="PyInstaller spec path")
    parser.add_argument("--root", default=str(ROOT), help="project root override")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument("--fail-on-error", action="store_true", help="return 1 when structural errors are found")
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = build_report(spec_path=Path(args.spec), root=Path(args.root))
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            "PyInstaller readiness: "
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
