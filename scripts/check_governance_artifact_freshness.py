#!/usr/bin/env python3
"""Validate that governance artifacts are present, parseable, and fresh."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso

DEFAULT_OUTPUT = ROOT / "output" / "governance_artifact_freshness.json"
SCRIPT_NAME = "scripts/check_governance_artifact_freshness.py"
ARTIFACT_VERSION = 1


@dataclass(frozen=True)
class ArtifactSpec:
    key: str
    path: Path
    sources: tuple[Path, ...]
    sha_field: str = ""
    sha_source: Path | None = None
    required: bool = True


def default_specs() -> list[ArtifactSpec]:
    return [
        ArtifactSpec(
            key="route_sample_coverage",
            path=ROOT / "output" / "route_sample_coverage.json",
            sources=(ROOT / "tests" / "route_samples.json", ROOT / "scripts" / "report_route_sample_coverage.py"),
            sha_field="samples_sha256",
            sha_source=ROOT / "tests" / "route_samples.json",
        ),
        ArtifactSpec(
            key="route_boundary_coverage",
            path=ROOT / "output" / "route_boundary_coverage.json",
            sources=(ROOT / "tests" / "route_samples.json", ROOT / "scripts" / "report_route_boundary_coverage.py"),
            sha_field="samples_sha256",
            sha_source=ROOT / "tests" / "route_samples.json",
        ),
        ArtifactSpec(
            key="hot_path_benchmark",
            path=ROOT / "output" / "hot_path_benchmark.json",
            sources=(
                ROOT / "data" / "hot_path_benchmark_samples.json",
                ROOT / "scripts" / "benchmark_hot_path.py",
                ROOT / "src" / "auditor" / "task_router.py",
                ROOT / "src" / "auditor" / "task_compiler.py",
                ROOT / "src" / "auditor" / "processor.py",
            ),
            sha_field="samples_sha256",
            sha_source=ROOT / "data" / "hot_path_benchmark_samples.json",
        ),
        ArtifactSpec(
            key="hot_path_trends",
            path=ROOT / "output" / "hot_path_trends.json",
            sources=(ROOT / "output" / "hot_path_benchmark_history.jsonl", ROOT / "scripts" / "report_hot_path_trends.py"),
            sha_field="history_sha256",
            sha_source=ROOT / "output" / "hot_path_benchmark_history.jsonl",
        ),
        ArtifactSpec(
            key="processor_fake_llm_benchmark",
            path=ROOT / "output" / "processor_fake_llm_benchmark.json",
            sources=(
                ROOT / "data" / "processor_fake_llm_benchmark_samples.json",
                ROOT / "scripts" / "benchmark_processor_fake_llm.py",
                ROOT / "src" / "auditor" / "processor.py",
                ROOT / "src" / "auditor" / "task_router.py",
                ROOT / "src" / "auditor" / "task_compiler.py",
            ),
            sha_field="samples_sha256",
            sha_source=ROOT / "data" / "processor_fake_llm_benchmark_samples.json",
        ),
        ArtifactSpec(
            key="failed_utterance_route_sample_candidates",
            path=ROOT / "output" / "failed_utterance_route_sample_candidates.json",
            sources=(
                ROOT / "data" / "failed_utterance_cases.json",
                ROOT / "scripts" / "extract_failed_utterance_candidates.py",
            ),
            sha_field="cases_sha256",
            sha_source=ROOT / "data" / "failed_utterance_cases.json",
        ),
        ArtifactSpec(
            key="route_sample_intake_package",
            path=ROOT / "output" / "route_sample_intake_package.json",
            sources=(
                ROOT / "output" / "github_route_sample_candidates.json",
                ROOT / "output" / "obsidian_route_sample_candidates.json",
                ROOT / "output" / "failed_utterance_route_sample_candidates.json",
                ROOT / "data" / "route_sample_candidate_review_decisions.json",
                ROOT / "tests" / "route_samples.json",
                ROOT / "scripts" / "build_candidate_intake_package.py",
            ),
            sha_field="reviewed_samples_sha256",
            sha_source=ROOT / "tests" / "route_samples.json",
        ),
        ArtifactSpec(
            key="route_sample_promotion_draft",
            path=ROOT / "output" / "route_sample_promotion_draft.json",
            sources=(
                ROOT / "output" / "route_sample_intake_package.json",
                ROOT / "tests" / "route_samples.json",
                ROOT / "scripts" / "build_route_sample_promotion_draft.py",
            ),
            sha_field="intake_package_sha256",
            sha_source=ROOT / "output" / "route_sample_intake_package.json",
        ),
        ArtifactSpec(
            key="governance_manifest",
            path=ROOT / "output" / "governance_manifest.json",
            sources=(
                ROOT / "output" / "route_sample_coverage.json",
                ROOT / "output" / "route_boundary_coverage.json",
                ROOT / "output" / "route_sample_candidate_review_status.json",
                ROOT / "output" / "failed_utterance_route_sample_candidates.json",
                ROOT / "output" / "route_sample_intake_package.json",
                ROOT / "output" / "route_sample_promotion_draft.json",
                ROOT / "output" / "hot_path_benchmark.json",
                ROOT / "output" / "hot_path_trends.json",
                ROOT / "output" / "processor_fake_llm_benchmark.json",
                ROOT / "scripts" / "build_governance_manifest.py",
            ),
        ),
        ArtifactSpec(
            key="package_preflight",
            path=ROOT / "output" / "package_preflight.json",
            sources=(
                ROOT / "scripts" / "package_preflight.py",
                ROOT / "requirements.txt",
                ROOT / "config.yaml",
                ROOT / "config.no_paste.yaml",
                ROOT / "app.py",
                ROOT / "scripts" / "Start-VoicePromptCompiler.ps1",
                ROOT / "src" / "plugin_bridge" / "bridge.py",
                ROOT / "src" / "plugin_bridge" / "http_daemon.py",
            ),
            required=False,
        ),
        ArtifactSpec(
            key="bridge_smoke_evidence",
            path=ROOT / "output" / "bridge_smoke_evidence.json",
            sources=(
                ROOT / "scripts" / "bridge_smoke_evidence.py",
                ROOT / "src" / "plugin_bridge" / "bridge.py",
                ROOT / "src" / "plugin_bridge" / "http_daemon.py",
                ROOT / "src" / "auditor" / "schema.py",
                ROOT / "src" / "asr" / "__init__.py",
                ROOT / "src" / "asr" / "funasr_engine.py",
                ROOT / "app.py",
            ),
            required=False,
        ),
        ArtifactSpec(
            key="processor_real_llm_benchmark",
            path=ROOT / "output" / "processor_real_llm_benchmark.json",
            sources=(
                ROOT / "data" / "processor_real_llm_benchmark_samples.json",
                ROOT / "scripts" / "benchmark_processor_real_llm.py",
                ROOT / "src" / "auditor" / "processor.py",
                ROOT / "src" / "auditor" / "task_router.py",
                ROOT / "src" / "auditor" / "task_compiler.py",
                ROOT / "src" / "llm" / "__init__.py",
            ),
            sha_field="samples_sha256",
            sha_source=ROOT / "data" / "processor_real_llm_benchmark_samples.json",
            required=False,
        ),
        ArtifactSpec(
            key="asr_manual_evidence",
            path=ROOT / "output" / "asr_manual_evidence.json",
            sources=(
                ROOT / "data" / "asr_manual_evidence_cases.json",
                ROOT / "scripts" / "asr_manual_evidence.py",
                ROOT / "src" / "asr" / "__init__.py",
                ROOT / "src" / "asr" / "base.py",
                ROOT / "src" / "asr" / "funasr_engine.py",
                ROOT / "config.no_paste.yaml",
            ),
            sha_field="cases_sha256",
            sha_source=ROOT / "data" / "asr_manual_evidence_cases.json",
            required=False,
        ),
        ArtifactSpec(
            key="plugin_poc_preflight",
            path=ROOT / "output" / "plugin_poc_preflight.json",
            sources=(
                ROOT / "scripts" / "plugin_poc_preflight.py",
                ROOT / "integrations" / "vscode-cursor" / "package.json",
                ROOT / "integrations" / "vscode-cursor" / "extension.js",
                ROOT / "integrations" / "vscode-cursor" / "README.md",
            ),
            required=False,
        ),
        ArtifactSpec(
            key="project_terms_scan",
            path=ROOT / "output" / "project_terms_scan.json",
            sources=(
                ROOT / "data" / "project_terms.json",
                ROOT / "scripts" / "scan_project_terms.py",
            ),
            sha_field="terms_sha256",
            sha_source=ROOT / "data" / "project_terms.json",
            required=False,
        ),
        ArtifactSpec(
            key="pyinstaller_readiness",
            path=ROOT / "output" / "pyinstaller_readiness.json",
            sources=(
                ROOT / "packaging" / "VoicePromptCompiler.spec",
                ROOT / "scripts" / "pyinstaller_readiness.py",
                ROOT / "app.py",
                ROOT / "requirements.txt",
                ROOT / "config.yaml",
                ROOT / "config.no_paste.yaml",
            ),
            required=False,
        ),
    ]


def build_report(
    specs: list[ArtifactSpec],
    *,
    max_age_hours: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    artifact_reports = [_check_artifact(spec, max_age_hours=max_age_hours, now=now) for spec in specs]
    failures = [
        failure
        for artifact in artifact_reports
        for failure in artifact.get("failures", [])
    ]
    warnings = [
        warning
        for artifact in artifact_reports
        for warning in artifact.get("warnings", [])
    ]
    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "max_age_hours": max_age_hours,
        "artifact_count": len(artifact_reports),
        "artifacts": artifact_reports,
        "failures": failures,
        "warnings": warnings,
        "status": {
            "passed": not failures,
            "failure_count": len(failures),
            "warning_count": len(warnings),
        },
    }


def _check_artifact(
    spec: ArtifactSpec,
    *,
    max_age_hours: float | None,
    now: datetime,
) -> dict[str, Any]:
    artifact_path = spec.path.expanduser().resolve()
    source_paths = [path.expanduser().resolve() for path in spec.sources]
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    report: dict[str, Any] = {}

    if not artifact_path.exists():
        if spec.required:
            failures.append(_failure(spec.key, "missing_artifact", artifact_path))
        else:
            warnings.append(_failure(spec.key, "missing_optional_artifact", artifact_path))
        return _artifact_report(spec, artifact_path, source_paths, report, failures, warnings)

    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        failures.append(
            {
                "artifact": spec.key,
                "reason": "malformed_json",
                "path": str(artifact_path),
                "error": str(exc),
            }
        )
        return _artifact_report(spec, artifact_path, source_paths, report, failures, warnings)

    if not isinstance(data, dict):
        failures.append(_failure(spec.key, "artifact_not_object", artifact_path))
        return _artifact_report(spec, artifact_path, source_paths, report, failures, warnings)

    generated_at = str(data.get("generated_at") or "")
    generated_at_dt = _parse_datetime(generated_at)
    if not generated_at_dt:
        failures.append(_failure(spec.key, "missing_or_invalid_generated_at", artifact_path))
    elif max_age_hours is not None:
        age_hours = (now - generated_at_dt).total_seconds() / 3600.0
        if age_hours > max_age_hours:
            failures.append(
                {
                    "artifact": spec.key,
                    "reason": "generated_at_exceeds_max_age",
                    "path": str(artifact_path),
                    "generated_at": generated_at,
                    "age_hours": round(age_hours, 4),
                    "max_age_hours": max_age_hours,
                }
            )

    artifact_mtime = artifact_path.stat().st_mtime
    missing_sources = [path for path in source_paths if not path.exists()]
    for source_path in missing_sources:
        failures.append(
            {
                "artifact": spec.key,
                "reason": "missing_source",
                "path": str(artifact_path),
                "source": str(source_path),
            }
        )
    for source_path in source_paths:
        if not source_path.exists():
            continue
        if source_path.stat().st_mtime > artifact_mtime + 0.001:
            failures.append(
                {
                    "artifact": spec.key,
                    "reason": "artifact_older_than_source",
                    "path": str(artifact_path),
                    "source": str(source_path),
                }
            )

    if spec.sha_field and spec.sha_source is not None:
        sha_source = spec.sha_source.expanduser().resolve()
        if sha_source.exists():
            expected_sha = sha256_file(sha_source)
            actual_sha = str(data.get(spec.sha_field) or "")
            if actual_sha != expected_sha:
                failures.append(
                    {
                        "artifact": spec.key,
                        "reason": "source_sha256_mismatch",
                        "path": str(artifact_path),
                        "source": str(sha_source),
                        "field": spec.sha_field,
                        "expected_sha256": expected_sha,
                        "actual_sha256": actual_sha,
                    }
                )
        else:
            warnings.append(
                {
                    "artifact": spec.key,
                    "reason": "sha_source_missing",
                    "source": str(sha_source),
                    "field": spec.sha_field,
                }
            )

    report = {
        "generated_at": generated_at,
        "schema_version": data.get("schema_version"),
        "artifact_version": data.get("artifact_version"),
        "script_name": data.get("script_name"),
    }
    return _artifact_report(spec, artifact_path, source_paths, report, failures, warnings)


def _artifact_report(
    spec: ArtifactSpec,
    artifact_path: Path,
    source_paths: list[Path],
    report: dict[str, Any],
    failures: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": spec.key,
        "path": str(artifact_path),
        "required": spec.required,
        "exists": artifact_path.exists(),
        "source_paths": [str(path) for path in source_paths],
        "sha_field": spec.sha_field,
        "sha_source": str(spec.sha_source.expanduser().resolve()) if spec.sha_source else "",
        "report": report,
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
    }


def _failure(artifact: str, reason: str, path: Path) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "reason": reason,
        "path": str(path),
    }


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check governance artifact freshness")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=None,
        help="fail when generated_at is older than this many hours",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="return 1 when an artifact is missing, stale, malformed, or hash-mismatched",
    )
    parser.add_argument("--print-json", action="store_true", help="print JSON report")
    parser.add_argument("--coverage-report", default=None, help="override route coverage report path")
    parser.add_argument("--boundary-report", default=None, help="override route boundary coverage report path")
    parser.add_argument("--hot-path-report", default=None, help="override hot-path report path")
    parser.add_argument("--trend-report", default=None, help="override hot-path trends report path")
    parser.add_argument("--fake-llm-report", default=None, help="override fake-LLM report path")
    parser.add_argument("--real-llm-report", default=None, help="override real-LLM report path")
    parser.add_argument("--failed-utterance-candidates", default=None, help="override failed-utterance candidate artifact path")
    parser.add_argument("--intake-package", default=None, help="override route-sample intake package path")
    parser.add_argument("--promotion-draft", default=None, help="override route-sample promotion draft path")
    parser.add_argument("--governance-manifest", default=None, help="override governance manifest path")
    parser.add_argument("--package-preflight", default=None, help="override package preflight artifact path")
    parser.add_argument("--bridge-smoke-evidence", default=None, help="override bridge smoke evidence artifact path")
    parser.add_argument("--asr-manual-evidence", default=None, help="override ASR manual evidence artifact path")
    parser.add_argument("--plugin-poc-preflight", default=None, help="override plugin POC preflight artifact path")
    parser.add_argument("--project-terms-scan", default=None, help="override project terms scan artifact path")
    parser.add_argument("--pyinstaller-readiness", default=None, help="override PyInstaller readiness artifact path")
    parser.add_argument(
        "--skip-governance-manifest",
        action="store_true",
        help="skip the manifest artifact; useful before the manifest has been regenerated",
    )
    parser.add_argument("--route-samples", default=None, help="override route_samples.json source path")
    parser.add_argument("--hot-path-samples", default=None, help="override hot-path sample source path")
    parser.add_argument("--history", default=None, help="override hot-path history source path")
    parser.add_argument("--fake-llm-samples", default=None, help="override fake-LLM sample source path")
    parser.add_argument("--real-llm-samples", default=None, help="override real-LLM sample source path")
    parser.add_argument("--failed-utterance-cases", default=None, help="override failed-utterance cases source path")
    parser.add_argument("--asr-cases", default=None, help="override ASR manual cases source path")
    parser.add_argument("--project-terms", default=None, help="override project terms source path")
    parser.add_argument("--pyinstaller-spec", default=None, help="override PyInstaller spec source path")
    return parser


def specs_from_args(args: argparse.Namespace) -> list[ArtifactSpec]:
    specs = default_specs()
    if getattr(args, "skip_governance_manifest", False):
        specs = [spec for spec in specs if spec.key != "governance_manifest"]
    overrides = {
        "route_sample_coverage": {
            "path": args.coverage_report,
            "primary_source": args.route_samples,
        },
        "route_boundary_coverage": {
            "path": args.boundary_report,
            "primary_source": args.route_samples,
        },
        "hot_path_benchmark": {
            "path": args.hot_path_report,
            "primary_source": args.hot_path_samples,
        },
        "hot_path_trends": {
            "path": args.trend_report,
            "primary_source": args.history,
        },
        "processor_fake_llm_benchmark": {
            "path": args.fake_llm_report,
            "primary_source": args.fake_llm_samples,
        },
        "processor_real_llm_benchmark": {
            "path": args.real_llm_report,
            "primary_source": args.real_llm_samples,
        },
        "failed_utterance_route_sample_candidates": {
            "path": args.failed_utterance_candidates,
            "primary_source": args.failed_utterance_cases,
        },
        "route_sample_intake_package": {
            "path": args.intake_package,
            "primary_source": args.route_samples,
        },
        "route_sample_promotion_draft": {
            "path": args.promotion_draft,
            "primary_source": args.intake_package,
        },
        "governance_manifest": {
            "path": args.governance_manifest,
            "primary_source": args.promotion_draft,
        },
        "package_preflight": {
            "path": args.package_preflight,
            "primary_source": None,
        },
        "bridge_smoke_evidence": {
            "path": args.bridge_smoke_evidence,
            "primary_source": None,
        },
        "asr_manual_evidence": {
            "path": args.asr_manual_evidence,
            "primary_source": args.asr_cases,
        },
        "plugin_poc_preflight": {
            "path": args.plugin_poc_preflight,
            "primary_source": None,
        },
        "project_terms_scan": {
            "path": args.project_terms_scan,
            "primary_source": args.project_terms,
        },
        "pyinstaller_readiness": {
            "path": args.pyinstaller_readiness,
            "primary_source": args.pyinstaller_spec,
        },
    }
    result: list[ArtifactSpec] = []
    for spec in specs:
        override = overrides[spec.key]
        path = Path(override["path"]) if override.get("path") else spec.path
        if override.get("primary_source"):
            primary = Path(str(override["primary_source"]))
            sources = (primary,)
            sha_source = primary
        else:
            sources = spec.sources
            sha_source = spec.sha_source
        result.append(
            ArtifactSpec(
                key=spec.key,
                path=path,
                sources=sources,
                sha_field=spec.sha_field,
                sha_source=sha_source,
                required=spec.required,
            )
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    report = build_report(
        specs_from_args(args),
        max_age_hours=args.max_age_hours if args.max_age_hours is not None else None,
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
            "Governance artifact freshness: "
            f"{report['artifact_count']} artifacts, "
            f"passed={report['status']['passed']}, "
            f"failures={report['status']['failure_count']}, "
            f"warnings={report['status']['warning_count']}"
        )

    if args.fail_on_stale and not report["status"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
