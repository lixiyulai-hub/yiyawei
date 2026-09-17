from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "architecture-gates.yml"
REQUIREMENTS_PATH = ROOT / "requirements-ci.txt"
DOCUMENT_PATH = ROOT / "docs" / "architecture_stability.md"


def _load_workflow() -> dict[str, object]:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _step_commands(workflow: dict[str, object]) -> list[str]:
    jobs = workflow["jobs"]
    windows = jobs["windows"]
    return [step["run"] for step in windows["steps"] if "run" in step]


def _requirement_names() -> set[str]:
    names = set()
    for line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or value.startswith("-"):
            continue
        names.add(value.split(">", maxsplit=1)[0].split("=", maxsplit=1)[0].lower())
    return names


def test_architecture_gates_workflow_has_windows_read_only_triggered_contract():
    workflow = _load_workflow()
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8").lower()
    assert workflow["name"] == "architecture-gates"
    assert workflow["on"] == {
        "push": {"branches": ["main"]},
        "pull_request": {"branches": ["main"]},
        "workflow_dispatch": "",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets" not in workflow_text
    assert all("permissions" not in job for job in workflow["jobs"].values())
    assert workflow["concurrency"]["cancel-in-progress"] == "true"
    assert "architecture-gates" in workflow["concurrency"]["group"]

    windows = workflow["jobs"]["windows"]
    assert windows["runs-on"] == "windows-latest"
    assert int(windows["timeout-minutes"]) > 0
    assert any(step.get("uses") == "actions/checkout@v7" for step in windows["steps"])
    setup = next(step for step in windows["steps"] if step.get("uses") == "actions/setup-python@v6")
    assert setup["with"]["python-version"] == "3.11"
    assert setup["with"]["cache"] == "pip"
    assert "requirements-ci.txt" in setup["with"]["cache-dependency-path"]
    assert "requirements-dev.txt" in setup["with"]["cache-dependency-path"]


def test_architecture_gates_workflow_runs_only_declared_local_gates():
    commands = _step_commands(_load_workflow())
    joined = "\n".join(commands)
    expected = [
        "python -m pip install -r requirements-ci.txt",
        "python -m playwright install chromium",
        "python -X utf8 -m pytest -q",
        "python -X utf8 -m pytest -c pytest.e2e.ini e2e -q",
        "python -X utf8 -m compileall app.py src tests scripts e2e",
        "python scripts/package_preflight.py --out \"$env:RUNNER_TEMP/package_preflight.json\" --fail-on-error",
        "git diff --check",
    ]
    for command in expected:
        assert command in joined
    assert "secrets." not in joined.lower()
    assert "benchmark_" not in joined
    assert "run_governance_gate" not in joined
    assert "ollama" not in joined.lower()
    assert "upload-artifact" not in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_ci_requirements_keep_test_surface_lightweight_and_exclude_model_runtime():
    text = REQUIREMENTS_PATH.read_text(encoding="utf-8").lower()
    names = _requirement_names()
    assert "-r requirements-dev.txt" in text
    assert {
        "pyyaml",
        "requests",
        "sounddevice",
        "soundfile",
        "numpy",
        "pyperclip",
        "pydantic",
    }.issubset(names)
    for package in ("funasr", "modelscope", "torch", "torchaudio"):
        assert package not in names


def test_architecture_stability_document_covers_change_and_hosting_policy():
    text = DOCUMENT_PATH.read_text(encoding="utf-8").lower()
    for required in (
        "failing test first",
        "refactor commits separate from feature commits",
        "feature flag",
        "owner",
        "removal condition",
        "git bisect",
        "microphone",
        "focus",
        "ctrl+v",
        "explicitly authorizes a private github repository",
        "check context is `windows`",
        "`architecture-gates` workflow",
    ):
        assert required in text
