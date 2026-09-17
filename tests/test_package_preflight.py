from __future__ import annotations

import json

import pytest

from scripts import package_preflight


def _write_project(root):
    (root / "scripts").mkdir(parents=True)
    (root / "src" / "plugin_bridge").mkdir(parents=True)
    assets = root / "src" / "gui" / "web_assets"
    assets.mkdir(parents=True)
    (root / "requirements.txt").write_text("pyyaml>=6\nrequests>=2\n", encoding="utf-8")
    (root / "config.yaml").write_text(
        """
app:
  name: Voice Prompt Compiler
llm:
  provider: ollama
  model: qwen
fast_llm:
  provider: ollama
  model: fast
injector:
  auto_paste: true
storage:
  db_path: data/sessions.db
safety:
  enabled: true
glossary:
  path: src/glossary/tech_terms.json
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "config.no_paste.yaml").write_text(
        """
app:
  name: Voice Prompt Compiler
llm:
  provider: ollama
  model: qwen
fast_llm:
  provider: ollama
  model: fast
injector:
  auto_paste: false
storage:
  db_path: data/sessions.db
safety:
  enabled: true
glossary:
  path: src/glossary/tech_terms.json
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text(
        """
parser.add_argument("--text")
parser.add_argument("--mode")
parser.add_argument("--fast")
parser.add_argument("--gui")
parser.add_argument("--tk-gui")
parser.add_argument("--script")
parser.add_argument("--daemon")
parser.add_argument("--daemon-host")
parser.add_argument("--daemon-port")
parser.add_argument("--daemon-token")
def process_text_for_bridge():
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "scripts" / "Start-VoicePromptCompiler.ps1").write_text(
        '$Python = Join-Path $ProjectRoot ".venv\\Scripts\\python.exe"\n& $Python "app.py" "--gui"\n',
        encoding="utf-8",
    )
    (root / "src" / "plugin_bridge" / "bridge.py").write_text(
        "class PluginBridge: pass\n",
        encoding="utf-8",
    )
    (root / "src" / "plugin_bridge" / "http_daemon.py").write_text(
        '"127.0.0.1"\n"localhost"\nauth_token\nAuthorization\nmax_body_bytes\nmax_text_chars\n',
        encoding="utf-8",
    )
    for name in package_preflight.REQUIRED_ASSETS:
        target = assets / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(name, encoding="utf-8")


def test_package_preflight_happy_path_uses_temp_layout(tmp_path, monkeypatch):
    _write_project(tmp_path)
    monkeypatch.setattr(package_preflight.importlib.util, "find_spec", lambda name: object())

    report = package_preflight.build_report(tmp_path)

    assert report["script_name"] == "scripts/package_preflight.py"
    assert report["runtime_hot_path_used"] is False
    assert report["network_used"] is False
    assert report["repo_clone_or_download_used"] is False
    assert report["status"]["passed"] is True
    assert report["summary"]["required_dependency_count"] == 2
    source_paths = {source["path"].replace("\\", "/") for source in report["sources"]}
    assert "src/gui/web_assets/js/api-client.js" in source_paths
    assert "src/gui/web_assets/js/custom-select.js" in source_paths
    assert "src/gui/web_assets/js/editor-controller.js" in source_paths
    assert "src/gui/web_assets/js/recording-controller.js" in source_paths
    assert "src/gui/web_assets/js/settings-controller.js" in source_paths
    assert "src/gui/web_assets/js/state-machine.js" in source_paths
    assert "src/gui/web_assets/js/state-renderer.js" in source_paths
    assert "src/gui/web_assets/js/theme-manager.js" in source_paths
    assert "src/gui/web_assets/main.js" in source_paths
    for css_module in (
        "tokens.css",
        "themes.css",
        "base.css",
        "layout.css",
        "controls.css",
        "recording.css",
        "editor.css",
    ):
        assert f"src/gui/web_assets/css/{css_module}" in source_paths
    assert "src/gui/web_assets/app.js" not in source_paths
    names = {check["name"] for check in report["checks"]}
    assert "plugin_bridge:loopback_guard" in names
    assert "config_no_paste_yaml:no_paste" in names
    assert "app_cli:bridge_no_paste_entry" in names


@pytest.mark.parametrize(
    ("asset", "expected_check"),
    [
        ("main.js", "web_asset:main.js"),
        ("js/api-client.js", "web_asset:js/api-client.js"),
        ("js/custom-select.js", "web_asset:js/custom-select.js"),
        ("js/editor-controller.js", "web_asset:js/editor-controller.js"),
        ("js/recording-controller.js", "web_asset:js/recording-controller.js"),
        ("js/settings-controller.js", "web_asset:js/settings-controller.js"),
        ("js/state-machine.js", "web_asset:js/state-machine.js"),
        ("js/state-renderer.js", "web_asset:js/state-renderer.js"),
        ("js/theme-catalog.js", "web_asset:js/theme-catalog.js"),
        ("js/theme-manager.js", "web_asset:js/theme-manager.js"),
        ("js/audio-visualizer.js", "web_asset:js/audio-visualizer.js"),
        ("css/tokens.css", "web_asset:css/tokens.css"),
        ("css/themes.css", "web_asset:css/themes.css"),
        ("css/base.css", "web_asset:css/base.css"),
        ("css/layout.css", "web_asset:css/layout.css"),
        ("css/controls.css", "web_asset:css/controls.css"),
        ("css/recording.css", "web_asset:css/recording.css"),
        ("css/editor.css", "web_asset:css/editor.css"),
    ],
)
def test_package_preflight_reports_missing_required_files(
    tmp_path,
    monkeypatch,
    asset,
    expected_check,
):
    _write_project(tmp_path)
    (tmp_path / "src" / "gui" / "web_assets" / asset).unlink()
    monkeypatch.setattr(package_preflight.importlib.util, "find_spec", lambda name: object())

    report = package_preflight.build_report(tmp_path)

    assert report["status"]["passed"] is False
    failed = [check for check in report["checks"] if check["status"] == "error"]
    assert any(check["name"] == expected_check for check in failed)


def test_package_preflight_dependency_warnings_are_machine_independent(tmp_path, monkeypatch):
    _write_project(tmp_path)

    def fake_find_spec(name):
        return object() if name == "yaml" else None

    monkeypatch.setattr(package_preflight.importlib.util, "find_spec", fake_find_spec)

    report = package_preflight.build_report(tmp_path)

    assert report["status"]["passed"] is True
    warnings = [check for check in report["checks"] if check["status"] == "warning"]
    assert any(check["name"] == "dependency:requests" for check in warnings)


def test_package_preflight_flags_secret_like_config_values(tmp_path, monkeypatch):
    _write_project(tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "api_key: live-secret\n", encoding="utf-8")
    monkeypatch.setattr(package_preflight.importlib.util, "find_spec", lambda name: object())

    report = package_preflight.build_report(tmp_path)

    assert report["status"]["passed"] is False
    assert any(
        check["name"] == "config_yaml:secret_redaction" and check["status"] == "error"
        for check in report["checks"]
    )


def test_package_preflight_cli_writes_report_and_fail_flag(tmp_path, monkeypatch):
    _write_project(tmp_path)
    (tmp_path / "config.no_paste.yaml").write_text("injector:\n  auto_paste: true\n", encoding="utf-8")
    monkeypatch.setattr(package_preflight.importlib.util, "find_spec", lambda name: object())
    out_path = tmp_path / "report.json"

    exit_code_without_fail = package_preflight.main(["--root", str(tmp_path), "--out", str(out_path)])
    exit_code_with_fail = package_preflight.main(
        ["--root", str(tmp_path), "--out", str(out_path), "--fail-on-error"]
    )

    assert exit_code_without_fail == 0
    assert exit_code_with_fail == 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["passed"] is False
    assert data["script_name"] == "scripts/package_preflight.py"
