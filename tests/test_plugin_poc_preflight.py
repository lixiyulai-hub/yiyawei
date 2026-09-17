from __future__ import annotations

import json

from scripts import plugin_poc_preflight


def _write_plugin(root):
    root.mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps(
            {
                "main": "./extension.js",
                "contributes": {
                    "commands": [
                        {"command": "voicePromptCompiler.processSelection"},
                        {"command": "voicePromptCompiler.processInput"},
                    ],
                    "configuration": {
                        "properties": {
                            "voicePromptCompiler.bridgeUrl": {"default": "http://127.0.0.1:8765"}
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "extension.js").write_text(
        """
const http = require("http");
function assertLoopback(url) { return ["127.0.0.1", "localhost"].includes(url.hostname); }
const endpoint = "/v1/process-text";
const headers = { Authorization: "Bearer token" };
const payload = { need_confirm: true, risk_level: "high" };
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("local bridge only\n", encoding="utf-8")


def test_plugin_poc_preflight_happy_path(tmp_path):
    plugin_root = tmp_path / "plugin"
    _write_plugin(plugin_root)

    report = plugin_poc_preflight.build_report(plugin_root)

    assert report["script_name"] == "scripts/plugin_poc_preflight.py"
    assert report["runtime_hot_path_used"] is False
    assert report["network_used"] is False
    assert report["status"]["passed"] is True


def test_plugin_poc_preflight_flags_forbidden_side_effect(tmp_path):
    plugin_root = tmp_path / "plugin"
    _write_plugin(plugin_root)
    (plugin_root / "extension.js").write_text((plugin_root / "extension.js").read_text(encoding="utf-8") + "\nclipboard.writeText('x')\n", encoding="utf-8")

    report = plugin_poc_preflight.build_report(plugin_root)

    assert report["status"]["passed"] is False
    assert any(check["name"] == "extension_forbidden_side_effects" for check in report["checks"])


def test_plugin_poc_preflight_cli_writes_report(tmp_path):
    plugin_root = tmp_path / "plugin"
    _write_plugin(plugin_root)
    out_path = tmp_path / "plugin.json"

    exit_code = plugin_poc_preflight.main(["--plugin-root", str(plugin_root), "--out", str(out_path), "--fail-on-error"])

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["passed"] is True

