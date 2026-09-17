#!/usr/bin/env python3
"""Run the local governance gate for data/template changes."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def release_commands(
    *,
    min_history_rows: int = 1,
    require_candidates_reviewed: bool = False,
    require_fresh_artifacts: bool = False,
    require_package_preflight: bool = False,
    require_bridge_smoke_evidence: bool = False,
    require_real_llm_benchmark: bool = False,
    require_asr_manual_evidence: bool = False,
    require_plugin_poc_preflight: bool = False,
    require_project_terms_scan: bool = False,
    require_pyinstaller_readiness: bool = False,
    require_harness_governance: bool = False,
    artifact_max_age_hours: float | None = None,
) -> list[list[str]]:
    python = sys.executable
    commands = [
        [python, "-m", "pytest", "-q"],
        [python, "-m", "compileall", "app.py", "src", "tests", "scripts"],
        [
            python,
            "scripts/report_route_sample_coverage.py",
            "--out",
            "output/route_sample_coverage.json",
            "--fail-on-invalid",
            "--fail-on-missing",
            "--fail-on-target-gap",
        ],
        [
            python,
            "scripts/report_route_boundary_coverage.py",
            "--out",
            "output/route_boundary_coverage.json",
            "--fail-on-invalid",
            "--fail-on-missing",
        ],
        [
            python,
            "scripts/benchmark_hot_path.py",
            "--out",
            "output/hot_path_benchmark.json",
            "--baseline",
            "output/hot_path_benchmark_baseline.json",
            "--history",
            "output/hot_path_benchmark_history.jsonl",
            "--iterations",
            "30",
            "--fail-on-budget",
            "--fail-on-regression",
            "--append-history",
        ],
        [
            python,
            "scripts/benchmark_processor_fake_llm.py",
            "--iterations",
            "10",
            "--warmup",
            "1",
            "--out",
            "output/processor_fake_llm_benchmark.json",
            "--fail-on-invariants",
        ],
        [
            python,
            "scripts/report_hot_path_trends.py",
            "--out",
            "output/hot_path_trends.json",
            "--history",
            "output/hot_path_benchmark_history.jsonl",
            "--route-migrations",
            "data/hot_path_route_migrations.json",
            "--fail-on-latest-failure",
            "--fail-on-route-removal",
            "--fail-on-sample-drop",
            "--min-history-rows",
            str(max(1, min_history_rows)),
        ],
    ]
    if require_package_preflight:
        commands.append(
            [
                python,
                "scripts/package_preflight.py",
                "--out",
                "output/package_preflight.json",
                "--fail-on-error",
            ]
        )
    if require_bridge_smoke_evidence:
        commands.append(
            [
                python,
                "scripts/bridge_smoke_evidence.py",
                "--out",
                "output/bridge_smoke_evidence.json",
                "--fail-on-error",
            ]
        )
    if require_real_llm_benchmark:
        commands.append(
            [
                python,
                "scripts/benchmark_processor_real_llm.py",
                "--config",
                "config.no_paste.yaml",
                "--out",
                "output/processor_real_llm_benchmark.json",
                "--allow-live",
                "--fail-on-error",
            ]
        )
    if require_asr_manual_evidence:
        commands.append(
            [
                python,
                "scripts/asr_manual_evidence.py",
                "--config",
                "config.no_paste.yaml",
                "--cases",
                "data/asr_manual_evidence_cases.json",
                "--out",
                "output/asr_manual_evidence.json",
                "--fail-on-error",
            ]
        )
    if require_plugin_poc_preflight:
        commands.append(
            [
                python,
                "scripts/plugin_poc_preflight.py",
                "--plugin-root",
                "integrations/vscode-cursor",
                "--out",
                "output/plugin_poc_preflight.json",
                "--fail-on-error",
            ]
        )
    if require_project_terms_scan:
        commands.append(
            [
                python,
                "scripts/scan_project_terms.py",
                "--terms",
                "data/project_terms.json",
                "--out",
                "output/project_terms_scan.json",
                "--fail-on-error",
            ]
        )
    if require_pyinstaller_readiness:
        commands.append(
            [
                python,
                "scripts/pyinstaller_readiness.py",
                "--spec",
                "packaging/VoicePromptCompiler.spec",
                "--out",
                "output/pyinstaller_readiness.json",
                "--fail-on-error",
            ]
        )
    if require_harness_governance:
        commands.append(
            [
                python,
                "scripts/report_harness_governance.py",
                "--out",
                "output/harness_governance_snapshot.json",
                "--fail-on-invalid",
            ]
        )
    if require_candidates_reviewed or require_fresh_artifacts:
        commands.append(
            [
                python,
                "scripts/extract_failed_utterance_candidates.py",
                "--out",
                "output/failed_utterance_route_sample_candidates.json",
                "--fail-on-invalid",
                "--fail-on-unredacted-sensitive",
            ]
        )
        candidate_command = [
            python,
            "scripts/report_candidate_review_status.py",
            "--out",
            "output/route_sample_candidate_review_status.json",
            "--fail-on-invalid",
        ]
        if require_candidates_reviewed:
            candidate_command.append("--fail-on-pending")
        commands.append(candidate_command)
    if require_candidates_reviewed or require_fresh_artifacts:
        intake_command = [
            python,
            "scripts/build_candidate_intake_package.py",
            "--out",
            "output/route_sample_intake_package.json",
            "--fail-on-invalid",
        ]
        if require_candidates_reviewed:
            intake_command.append("--fail-on-pending")
        commands.append(intake_command)
        commands.append(
            [
                python,
                "scripts/build_route_sample_promotion_draft.py",
                "--out",
                "output/route_sample_promotion_draft.json",
            ]
        )
    if require_fresh_artifacts:
        command = [
            python,
            "scripts/check_governance_artifact_freshness.py",
            "--out",
            "output/governance_artifact_freshness.json",
            "--fail-on-stale",
            "--skip-governance-manifest",
        ]
        if artifact_max_age_hours is not None:
            command.extend(["--max-age-hours", str(max(0.0, artifact_max_age_hours))])
        commands.append(command)
        commands.append(
            [
                python,
                "scripts/build_governance_manifest.py",
                "--out",
                "output/governance_manifest.json",
                "--fail-on-invalid",
            ]
        )
        final_command = [
            python,
            "scripts/check_governance_artifact_freshness.py",
            "--out",
            "output/governance_artifact_freshness.json",
            "--fail-on-stale",
        ]
        if artifact_max_age_hours is not None:
            final_command.extend(["--max-age-hours", str(max(0.0, artifact_max_age_hours))])
        commands.append(final_command)
    return commands


def run_commands(commands: list[list[str]], *, cwd: Path = ROOT, dry_run: bool = False) -> int:
    for index, command in enumerate(commands, start=1):
        printable = " ".join(command)
        print(f"[{index}/{len(commands)}] {printable}")
        if dry_run:
            continue
        completed = subprocess.run(command, cwd=str(cwd), check=False)
        if completed.returncode != 0:
            print(f"[FAIL] command exited with {completed.returncode}: {printable}", file=sys.stderr)
            return completed.returncode
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Yiyawei governance gate")
    parser.add_argument("--release", action="store_true", help="run the release governance chain")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running them")
    parser.add_argument(
        "--min-history-rows",
        type=int,
        default=1,
        help="minimum hot-path history rows required by the trend gate",
    )
    parser.add_argument(
        "--require-candidates-reviewed",
        action="store_true",
        help="also fail release when offline candidate queues still have pending review items",
    )
    parser.add_argument(
        "--require-fresh-artifacts",
        action="store_true",
        help="also fail release when governance artifacts are missing, stale, or hash-mismatched",
    )
    parser.add_argument(
        "--require-package-preflight",
        action="store_true",
        help="also run offline package-readiness checks and fail on structural package errors",
    )
    parser.add_argument(
        "--require-bridge-smoke-evidence",
        action="store_true",
        help="also run deterministic local plugin bridge smoke evidence and fail on invariant errors",
    )
    parser.add_argument(
        "--require-real-llm-benchmark",
        action="store_true",
        help="also run an explicit live local-LLM processor benchmark; never part of the default release gate",
    )
    parser.add_argument(
        "--require-asr-manual-evidence",
        action="store_true",
        help="also run offline ASR wav/manual evidence checks without loading ASR by default",
    )
    parser.add_argument(
        "--require-plugin-poc-preflight",
        action="store_true",
        help="also run static checks for the VS Code/Cursor plugin proof of concept",
    )
    parser.add_argument(
        "--require-project-terms-scan",
        action="store_true",
        help="also validate governed project_terms.json and write an offline scan receipt",
    )
    parser.add_argument(
        "--require-pyinstaller-readiness",
        action="store_true",
        help="also run offline PyInstaller readiness checks without building an executable",
    )
    parser.add_argument(
        "--require-harness-governance",
        action="store_true",
        help="also build the offline harness governance snapshot for prompt/router/compiler review",
    )
    parser.add_argument(
        "--artifact-max-age-hours",
        type=float,
        default=None,
        help="optional maximum age for governance artifact generated_at timestamps",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if not args.release:
        parser.error("choose --release")
    commands = release_commands(
        min_history_rows=args.min_history_rows,
        require_candidates_reviewed=bool(args.require_candidates_reviewed),
        require_fresh_artifacts=bool(args.require_fresh_artifacts),
        require_package_preflight=bool(args.require_package_preflight),
        require_bridge_smoke_evidence=bool(args.require_bridge_smoke_evidence),
        require_real_llm_benchmark=bool(args.require_real_llm_benchmark),
        require_asr_manual_evidence=bool(args.require_asr_manual_evidence),
        require_plugin_poc_preflight=bool(args.require_plugin_poc_preflight),
        require_project_terms_scan=bool(args.require_project_terms_scan),
        require_pyinstaller_readiness=bool(args.require_pyinstaller_readiness),
        require_harness_governance=bool(args.require_harness_governance),
        artifact_max_age_hours=args.artifact_max_age_hours,
    )
    return run_commands(commands, dry_run=bool(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
