from __future__ import annotations

from pathlib import Path
import sys

from scripts.run_governance_gate import main, release_commands


def test_release_commands_include_required_governance_steps():
    commands = release_commands(min_history_rows=3)
    joined = [" ".join(command) for command in commands]

    assert joined[0] == f"{sys.executable} -m pytest -q"
    assert any("report_route_sample_coverage.py" in command for command in joined)
    assert any("report_route_boundary_coverage.py" in command for command in joined)
    assert any("benchmark_hot_path.py" in command for command in joined)
    assert any("benchmark_processor_fake_llm.py" in command for command in joined)
    assert any("report_hot_path_trends.py" in command for command in joined)
    assert not any("report_candidate_review_status.py" in command for command in joined)
    assert not any("extract_failed_utterance_candidates.py" in command for command in joined)
    assert not any("build_candidate_intake_package.py" in command for command in joined)
    assert not any("build_route_sample_promotion_draft.py" in command for command in joined)
    assert not any("check_governance_artifact_freshness.py" in command for command in joined)
    assert not any("build_governance_manifest.py" in command for command in joined)
    assert not any("package_preflight.py" in command for command in joined)
    assert not any("bridge_smoke_evidence.py" in command for command in joined)
    assert not any("benchmark_processor_real_llm.py" in command for command in joined)
    assert not any("asr_manual_evidence.py" in command for command in joined)
    assert not any("plugin_poc_preflight.py" in command for command in joined)
    assert not any("scan_project_terms.py" in command for command in joined)
    assert not any("pyinstaller_readiness.py" in command for command in joined)
    assert not any("report_harness_governance.py" in command for command in joined)
    assert any("--fail-on-invariants" in command for command in joined)
    assert any("--fail-on-invalid" in command for command in joined)
    assert any("--fail-on-missing" in command for command in joined)
    assert any("--fail-on-target-gap" in command for command in joined)
    assert any("--min-history-rows 3" in command for command in joined)


def test_release_commands_can_include_optional_strict_governance_steps():
    commands = release_commands(
        min_history_rows=3,
        require_fresh_artifacts=True,
        artifact_max_age_hours=24,
    )
    joined = [" ".join(command) for command in commands]

    intake_command = next(
        command for command in joined if "build_candidate_intake_package.py" in command
    )
    failed_utterance_command = next(
        command for command in joined if "extract_failed_utterance_candidates.py" in command
    )
    candidate_command = next(
        command for command in joined if "report_candidate_review_status.py" in command
    )
    promotion_command = next(
        command for command in joined if "build_route_sample_promotion_draft.py" in command
    )
    freshness_commands = [
        command for command in joined if "check_governance_artifact_freshness.py" in command
    ]
    manifest_command = next(
        command for command in joined if "build_governance_manifest.py" in command
    )
    assert "--fail-on-invalid" in failed_utterance_command
    assert "--fail-on-unredacted-sensitive" in failed_utterance_command
    assert "--fail-on-invalid" in candidate_command
    assert "--fail-on-pending" not in candidate_command
    assert "--fail-on-invalid" in intake_command
    assert "--fail-on-pending" not in intake_command
    assert "output/route_sample_promotion_draft.json" in promotion_command
    assert len(freshness_commands) == 2
    assert "--skip-governance-manifest" in freshness_commands[0]
    assert "--skip-governance-manifest" not in freshness_commands[1]
    assert all("--fail-on-stale" in command for command in freshness_commands)
    assert all("--max-age-hours 24" in command for command in freshness_commands)
    assert "output/governance_manifest.json" in manifest_command
    assert "--fail-on-invalid" in manifest_command


def test_release_commands_can_require_package_preflight():
    commands = release_commands(min_history_rows=3, require_package_preflight=True)
    joined = [" ".join(command) for command in commands]

    package_command = next(command for command in joined if "package_preflight.py" in command)
    assert "output/package_preflight.json" in package_command
    assert "--fail-on-error" in package_command


def test_release_commands_can_require_bridge_smoke_evidence():
    commands = release_commands(min_history_rows=3, require_bridge_smoke_evidence=True)
    joined = [" ".join(command) for command in commands]

    bridge_command = next(command for command in joined if "bridge_smoke_evidence.py" in command)
    assert "output/bridge_smoke_evidence.json" in bridge_command
    assert "--fail-on-error" in bridge_command


def test_release_commands_can_require_real_llm_benchmark():
    commands = release_commands(min_history_rows=3, require_real_llm_benchmark=True)
    joined = [" ".join(command) for command in commands]

    command = next(command for command in joined if "benchmark_processor_real_llm.py" in command)
    assert "--config config.no_paste.yaml" in command
    assert "output/processor_real_llm_benchmark.json" in command
    assert "--allow-live" in command
    assert "--fail-on-error" in command


def test_release_commands_can_require_asr_manual_evidence():
    commands = release_commands(min_history_rows=3, require_asr_manual_evidence=True)
    joined = [" ".join(command) for command in commands]

    command = next(command for command in joined if "asr_manual_evidence.py" in command)
    assert "--config config.no_paste.yaml" in command
    assert "--cases data/asr_manual_evidence_cases.json" in command
    assert "output/asr_manual_evidence.json" in command
    assert "--fail-on-error" in command


def test_release_commands_can_require_plugin_poc_preflight():
    commands = release_commands(min_history_rows=3, require_plugin_poc_preflight=True)
    joined = [" ".join(command) for command in commands]

    command = next(command for command in joined if "plugin_poc_preflight.py" in command)
    assert "--plugin-root integrations/vscode-cursor" in command
    assert "output/plugin_poc_preflight.json" in command
    assert "--fail-on-error" in command


def test_release_commands_can_require_project_terms_scan():
    commands = release_commands(min_history_rows=3, require_project_terms_scan=True)
    joined = [" ".join(command) for command in commands]

    command = next(command for command in joined if "scan_project_terms.py" in command)
    assert "--terms data/project_terms.json" in command
    assert "output/project_terms_scan.json" in command
    assert "--fail-on-error" in command


def test_release_commands_can_require_pyinstaller_readiness():
    commands = release_commands(min_history_rows=3, require_pyinstaller_readiness=True)
    joined = [" ".join(command) for command in commands]

    command = next(command for command in joined if "pyinstaller_readiness.py" in command)
    assert "--spec packaging/VoicePromptCompiler.spec" in command
    assert "output/pyinstaller_readiness.json" in command
    assert "--fail-on-error" in command


def test_release_commands_can_require_harness_governance():
    commands = release_commands(min_history_rows=3, require_harness_governance=True)
    joined = [" ".join(command) for command in commands]

    command = next(command for command in joined if "report_harness_governance.py" in command)
    assert "output/harness_governance_snapshot.json" in command
    assert "--fail-on-invalid" in command


def test_release_commands_can_require_candidates_reviewed_with_intake_package():
    commands = release_commands(
        min_history_rows=3,
        require_candidates_reviewed=True,
        require_fresh_artifacts=True,
        artifact_max_age_hours=24,
    )
    joined = [" ".join(command) for command in commands]

    candidate_command = next(
        command for command in joined if "report_candidate_review_status.py" in command
    )
    failed_utterance_command = next(
        command for command in joined if "extract_failed_utterance_candidates.py" in command
    )
    intake_command = next(
        command for command in joined if "build_candidate_intake_package.py" in command
    )
    promotion_command = next(
        command for command in joined if "build_route_sample_promotion_draft.py" in command
    )
    assert joined.index(failed_utterance_command) < joined.index(candidate_command)
    assert "--fail-on-invalid" in candidate_command
    assert "--fail-on-pending" in candidate_command
    assert "--fail-on-invalid" in intake_command
    assert "--fail-on-pending" in intake_command
    assert "output/route_sample_promotion_draft.json" in promotion_command


def test_governance_gate_dry_run_prints_commands(capsys):
    exit_code = main(["--release", "--dry-run", "--min-history-rows", "2"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "pytest -q" in captured.out
    assert "benchmark_hot_path.py" in captured.out
    assert "report_hot_path_trends.py" in captured.out
    assert "--min-history-rows 2" in captured.out


def test_governance_gate_dry_run_prints_optional_strict_steps(capsys):
    exit_code = main(
        [
            "--release",
            "--dry-run",
            "--require-candidates-reviewed",
            "--require-fresh-artifacts",
            "--artifact-max-age-hours",
            "24",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "report_candidate_review_status.py" in captured.out
    assert "extract_failed_utterance_candidates.py" in captured.out
    assert "build_candidate_intake_package.py" in captured.out
    assert "build_route_sample_promotion_draft.py" in captured.out
    assert "check_governance_artifact_freshness.py" in captured.out
    assert "build_governance_manifest.py" in captured.out
    assert "--max-age-hours 24" in captured.out


def test_governance_gate_dry_run_prints_package_preflight(capsys):
    exit_code = main(["--release", "--dry-run", "--require-package-preflight"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "package_preflight.py" in captured.out
    assert "output/package_preflight.json" in captured.out
    assert "--fail-on-error" in captured.out


def test_governance_gate_dry_run_prints_bridge_smoke_evidence(capsys):
    exit_code = main(["--release", "--dry-run", "--require-bridge-smoke-evidence"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "bridge_smoke_evidence.py" in captured.out
    assert "output/bridge_smoke_evidence.json" in captured.out
    assert "--fail-on-error" in captured.out


def test_governance_gate_dry_run_prints_real_llm_benchmark(capsys):
    exit_code = main(["--release", "--dry-run", "--require-real-llm-benchmark"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "benchmark_processor_real_llm.py" in captured.out
    assert "output/processor_real_llm_benchmark.json" in captured.out
    assert "--allow-live" in captured.out
    assert "--fail-on-error" in captured.out


def test_governance_gate_dry_run_prints_new_optional_receipts(capsys):
    exit_code = main(
        [
            "--release",
            "--dry-run",
            "--require-asr-manual-evidence",
            "--require-plugin-poc-preflight",
            "--require-project-terms-scan",
            "--require-pyinstaller-readiness",
            "--require-harness-governance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "asr_manual_evidence.py" in captured.out
    assert "plugin_poc_preflight.py" in captured.out
    assert "scan_project_terms.py" in captured.out
    assert "pyinstaller_readiness.py" in captured.out
    assert "report_harness_governance.py" in captured.out
    assert "output/asr_manual_evidence.json" in captured.out
    assert "output/plugin_poc_preflight.json" in captured.out
    assert "output/project_terms_scan.json" in captured.out
    assert "output/pyinstaller_readiness.json" in captured.out
    assert "output/harness_governance_snapshot.json" in captured.out


def test_runtime_code_does_not_reference_governance_outputs():
    forbidden = (
        "github_route_sample_candidates",
        "obsidian_route_sample_candidates",
        "route_sample_candidate_review_status",
        "failed_utterance_cases",
        "failed_utterance_cases.json",
        "failed_utterance_route_sample_candidates",
        "failed_utterance_route_sample_candidates.json",
        "route_sample_intake_package",
        "route_sample_promotion_draft",
        "route_sample_coverage.json",
        "route_boundary_coverage.json",
        "hot_path_benchmark.json",
        "hot_path_benchmark_history.jsonl",
        "hot_path_trends.json",
        "processor_fake_llm_benchmark.json",
        "processor_real_llm_benchmark",
        "processor_real_llm_benchmark.json",
        "asr_manual_evidence",
        "asr_manual_evidence.json",
        "plugin_poc_preflight",
        "plugin_poc_preflight.json",
        "project_terms.json",
        "project_terms_scan",
        "project_terms_scan.json",
        "real_llm_harness_regression",
        "real_llm_harness_regression.json",
        "governance_artifact_freshness.json",
        "governance_manifest.json",
        "package_preflight",
        "package_preflight.json",
        "package_preflight_report.json",
        "package_preflight_manifest.json",
        "package_preflight_artifacts",
        "bridge_smoke_evidence",
        "bridge_smoke_evidence.json",
        "bridge_smoke_report.json",
        "bridge_smoke_artifacts",
        "run_governance_gate",
        "run_package_preflight",
        "check_package_preflight",
        "build_package_preflight",
        "run_bridge_smoke",
        "check_bridge_smoke",
        "build_bridge_smoke",
        "run_real_llm_benchmark",
        "check_real_llm_benchmark",
        "build_real_llm_benchmark",
        "build_asr_wav_evidence",
        "scan_project_terms",
        "plugin_poc_static_check",
        "run_plugin_poc_preflight",
        "extract_failed_utterance_candidates",
        "build_candidate_intake_package",
        "build_route_sample_promotion_draft",
        "build_governance_manifest",
        "pyinstaller_readiness",
        "pyinstaller_readiness.json",
        "harness_governance_snapshot",
        "harness_governance_snapshot.json",
        "report_harness_governance",
        "decide_route_sample_candidate",
    )
    runtime_paths = [Path("app.py"), *Path("src").rglob("*.py")]
    matches = []
    for path in runtime_paths:
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern in text:
                matches.append((str(path), pattern))

    assert matches == []
