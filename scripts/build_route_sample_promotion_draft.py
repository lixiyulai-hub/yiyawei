#!/usr/bin/env python3
"""Build a JSON draft for manually promoting accepted route-sample candidates.

This script is intentionally read-only with respect to ``tests/route_samples``.
It produces a bounded draft artifact that reviewers can inspect before making
explicit sample-library edits.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance_artifacts import sha256_file, utc_now_iso
from scripts.build_candidate_intake_package import DEFAULT_OUTPUT as DEFAULT_INTAKE_PACKAGE
from scripts.report_candidate_review_status import DEFAULT_REVIEWED_SAMPLES


DEFAULT_OUTPUT = ROOT / "output" / "route_sample_promotion_draft.json"
SCRIPT_NAME = "scripts/build_route_sample_promotion_draft.py"
ARTIFACT_VERSION = 1


def build_draft(
    intake_package_path: Path,
    route_samples_path: Path,
    *,
    include_existing: bool = False,
) -> dict[str, Any]:
    intake_package_path = intake_package_path.expanduser().resolve()
    route_samples_path = route_samples_path.expanduser().resolve()
    package = json.loads(intake_package_path.read_text(encoding="utf-8"))
    _validate_intake_package(package)
    route_samples = _load_route_samples(route_samples_path)
    existing_ids = {str(item.get("id") or "") for item in route_samples}
    existing_inputs = {_normalize(str(item.get("input") or "")) for item in route_samples}
    draft_ids: set[str] = set()
    draft_inputs: set[str] = set()

    draft_samples: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    accepted_rows = package.get("intake", {}).get("accepted_sample_drafts") or []
    if not isinstance(accepted_rows, list):
        accepted_rows = []

    for row in accepted_rows:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidate_id") or "")
        sample = row.get("suggested_sample")
        if not isinstance(sample, dict):
            skipped.append({"candidate_id": candidate_id, "reason": "missing_suggested_sample"})
            continue
        cleaned = _clean_sample(sample)
        sample_id = str(cleaned.get("id") or "")
        sample_input = _normalize(str(cleaned.get("input") or ""))
        if not sample_id or not sample_input:
            skipped.append({"candidate_id": candidate_id, "reason": "missing_sample_id_or_input"})
            continue
        duplicate_reason = ""
        if sample_id in existing_ids:
            duplicate_reason = "sample_id_already_exists"
        elif sample_input in existing_inputs:
            duplicate_reason = "sample_input_already_exists"
        if duplicate_reason and not include_existing:
            skipped.append(
                {
                    "candidate_id": candidate_id,
                    "sample_id": sample_id,
                    "reason": duplicate_reason,
                }
            )
            continue
        draft_duplicate_reason = ""
        if sample_id in draft_ids:
            draft_duplicate_reason = "draft_sample_id_duplicate"
        elif sample_input in draft_inputs:
            draft_duplicate_reason = "draft_sample_input_duplicate"
        if draft_duplicate_reason:
            skipped.append(
                {
                    "candidate_id": candidate_id,
                    "sample_id": sample_id,
                    "reason": draft_duplicate_reason,
                }
            )
            continue
        draft_ids.add(sample_id)
        draft_inputs.add(sample_input)
        draft_samples.append(
            {
                "candidate_id": candidate_id,
                "status": row.get("status") or "accepted",
                "reason": row.get("reason") or "",
                "sample": cleaned,
                "patch_preview": {
                    "op": "add",
                    "path": "/-",
                    "value": cleaned,
                },
                "duplicate_reason": duplicate_reason,
                "review_notes": row.get("review_notes") or "",
                "novice_preview_text": row.get("novice_preview_text") or "",
            }
        )

    return {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "runtime_hot_path_used": False,
        "network_used": False,
        "repo_clone_or_download_used": False,
        "intake_package_path": str(intake_package_path),
        "intake_package_sha256": sha256_file(intake_package_path),
        "route_samples_path": str(route_samples_path),
        "route_samples_sha256": sha256_file(route_samples_path),
        "include_existing": include_existing,
        "draft_sample_count": len(draft_samples),
        "skipped_count": len(skipped),
        "draft_samples": draft_samples,
        "skipped": skipped,
        "status": {
            "valid": True,
            "runtime_isolated": True,
            "has_drafts": bool(draft_samples),
            "modified_route_samples": False,
        },
        "notes": [
            "This artifact is a promotion draft only. It does not modify tests/route_samples.json.",
            "Reviewers must manually apply wanted samples and rerun coverage, boundary, benchmarks, and strict gate.",
        ],
    }


def validate_output_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = ROOT.resolve()
    forbidden_exact = {
        (root / "app.py").resolve(),
        (root / "tests" / "route_samples.json").resolve(),
    }
    if resolved in forbidden_exact:
        raise ValueError("promotion draft output path must not target runtime code or reviewed samples")
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return resolved
    parts = relative.parts
    if parts and parts[0] == "src":
        raise ValueError("promotion draft output path must not be under src/")
    if parts and parts[0] == "tests" and resolved.suffix == ".py":
        raise ValueError("promotion draft output path must not overwrite tests/*.py")
    return resolved


def _validate_intake_package(package: dict[str, Any]) -> None:
    if package.get("runtime_hot_path_used") is True:
        raise ValueError("intake package has runtime_hot_path_used=true")
    if package.get("network_used") is True:
        raise ValueError("intake package has network_used=true")
    if package.get("repo_clone_or_download_used") is True:
        raise ValueError("intake package has repo_clone_or_download_used=true")
    status = package.get("status") if isinstance(package.get("status"), dict) else {}
    if status.get("runtime_isolated") is False:
        raise ValueError("intake package status.runtime_isolated=false")


def _load_route_samples(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("route samples must be a JSON list")
    return [item for item in data if isinstance(item, dict)]


def _clean_sample(sample: dict[str, Any]) -> dict[str, Any]:
    allowed_order = (
        "id",
        "spoken_type",
        "input",
        "expected_task_type",
        "expected_domain",
        "output_shape",
        "must_keep",
        "must_drop",
        "required_domain_terms",
        "risk",
        "boundary_tags",
        "boundary_domain",
    )
    result: dict[str, Any] = {}
    for key in allowed_order:
        if key not in sample:
            continue
        value = sample[key]
        if value in ("", None, [], {}):
            continue
        result[key] = value
    return result


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().split())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build accepted route-sample promotion draft")
    parser.add_argument("--intake-package", default=str(DEFAULT_INTAKE_PACKAGE), help="route sample intake package path")
    parser.add_argument("--route-samples", default=str(DEFAULT_REVIEWED_SAMPLES), help="reviewed route samples path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="promotion draft output path")
    parser.add_argument("--include-existing", action="store_true", help="include drafts even when sample id/input already exists")
    parser.add_argument("--print-json", action="store_true", help="print draft JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        draft = build_draft(
            Path(args.intake_package),
            Path(args.route_samples),
            include_existing=bool(args.include_existing),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    output_text = json.dumps(draft, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        try:
            out_path = validate_output_path(Path(args.out))
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
        print(
            "Promotion draft: "
            f"drafts={draft['draft_sample_count']}, "
            f"skipped={draft['skipped_count']}, "
            f"modified_route_samples={draft['status']['modified_route_samples']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
