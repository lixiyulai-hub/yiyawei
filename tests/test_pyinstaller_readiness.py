from __future__ import annotations

import json

from scripts import pyinstaller_readiness


def _write_project(root):
    (root / "packaging").mkdir(parents=True)
    (root / "src" / "gui" / "web_assets").mkdir(parents=True)
    (root / "src" / "glossary").mkdir(parents=True)
    for relative in ("app.py", "requirements.txt", "config.yaml", "config.no_paste.yaml", "src/gui/web_assets/index.html", "src/glossary/tech_terms.json"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    (root / "packaging" / "VoicePromptCompiler.spec").write_text(
        """
hiddenimports = ["funasr", "modelscope", "sounddevice", "soundfile", "yaml", "opencc", "pyautogui", "pyperclip"]
from pathlib import Path
PROJECT_ROOT = Path(SPECPATH).resolve().parent
datas = [(str(PROJECT_ROOT / "config.yaml"), "."), (str(PROJECT_ROOT / "config.no_paste.yaml"), "."), (str(PROJECT_ROOT / "src/gui/web_assets"), "src/gui/web_assets"), (str(PROJECT_ROOT / "src/glossary/tech_terms.json"), "src/glossary")]
a = Analysis([str(PROJECT_ROOT / "app.py")], datas=datas, hiddenimports=hiddenimports)
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_pyinstaller_readiness_happy_path(tmp_path):
    _write_project(tmp_path)

    report = pyinstaller_readiness.build_report(
        spec_path=tmp_path / "packaging" / "VoicePromptCompiler.spec",
        root=tmp_path,
    )

    assert report["script_name"] == "scripts/pyinstaller_readiness.py"
    assert report["runtime_hot_path_used"] is False
    assert report["build_executed"] is False
    assert report["status"]["passed"] is True


def test_pyinstaller_readiness_flags_missing_spec_data(tmp_path):
    _write_project(tmp_path)
    spec = tmp_path / "packaging" / "VoicePromptCompiler.spec"
    spec.write_text('a = Analysis(["app.py"], datas=[])\n', encoding="utf-8")

    report = pyinstaller_readiness.build_report(spec_path=spec, root=tmp_path)

    assert report["status"]["passed"] is False
    assert any(check["name"] == "spec_data:config.yaml" for check in report["checks"])


def test_pyinstaller_readiness_rejects_relative_entrypoint(tmp_path):
    _write_project(tmp_path)
    spec = tmp_path / "packaging" / "VoicePromptCompiler.spec"
    spec.write_text(
        'a = Analysis(["app.py"], datas=[("config.yaml", ".")])\n',
        encoding="utf-8",
    )

    report = pyinstaller_readiness.build_report(spec_path=spec, root=tmp_path)

    assert report["status"]["passed"] is False
    assert any(
        check["name"] == "spec_entrypoint" and check["status"] == "error"
        for check in report["checks"]
    )


def test_pyinstaller_readiness_cli_writes_report(tmp_path):
    _write_project(tmp_path)
    out_path = tmp_path / "pyinstaller.json"

    exit_code = pyinstaller_readiness.main(
        [
            "--spec",
            str(tmp_path / "packaging" / "VoicePromptCompiler.spec"),
            "--root",
            str(tmp_path),
            "--out",
            str(out_path),
            "--fail-on-error",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"]["passed"] is True
