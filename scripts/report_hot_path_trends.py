#!/usr/bin/env python3
"""Summarize hot-path benchmark history for governance reviews.

This report is intentionally offline. It reads the compact JSONL history
written by scripts/benchmark_hot_path.py and does not import runtime router,
LLM, ASR, GitHub, or Obsidian code.
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

DEFAULT_HISTORY = ROOT / "output" / "hot_path_benchmark_history.jsonl"
DEFAULT_OUTPUT = ROOT / "output" / "hot_path_trends.json"
DEFAULT_ROUTE_MIGRATIONS = ROOT / "data" / "hot_path_route_migrations.json"
SCRIPT_NAME = "scripts/report_hot_path_trends.py"
ARTIFACT_VERSION = 1


def load_history(path: Path) -> list[dict[str, Any]]:
    path = path.expanduser()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on history line {line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"history line {line_number} must be a JSON object")
            rows.append(row)
    if not rows:
        raise ValueError("history file contains no benchmark rows")
    return rows


def build_report(
    rows: list[dict[str, Any]],
    *,
    history_path: Path | None = None,
    window_size: int = 5,
    route_migrations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("history rows cannot be empty")

    window_size = max(1, window_size)
    first = rows[0]
    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    window_rows = rows[-window_size:]
    warnings = _build_warnings(rows)
    route_trend = _route_trend(first, latest)
    reviewed_removed_routes = _reviewed_removed_routes(
        route_trend["removed_routes"],
        route_migrations or [],
    )
    unreviewed_removed_routes = [
        route for route in route_trend["removed_routes"] if route not in reviewed_removed_routes
    ]

    report = {
        "schema_version": 1,
        "artifact_version": ARTIFACT_VERSION,
        "script_name": SCRIPT_NAME,
        "generated_at": utc_now_iso(),
        "history_path": str(history_path.expanduser().resolve()) if history_path else "",
        "history_sha256": sha256_file(history_path.expanduser()) if history_path else "",
        "row_count": len(rows),
        "window_size": window_size,
        "window": {
            "first_generated_at": first.get("generated_at"),
            "previous_generated_at": previous.get("generated_at") if previous else None,
            "latest_generated_at": latest.get("generated_at"),
        },
        "latest": _snapshot_row(latest),
        "metric_trends": {
            "p95_ms": _metric_trends(rows, window_rows, "p95_ms", unit="ms"),
            "p95_chars": _metric_trends(rows, window_rows, "p95_chars", unit="chars"),
        },
        "health": _health_summary(rows, latest),
        "deltas": {
            "from_first": _row_delta(latest, first),
            "from_previous": _row_delta(latest, previous) if previous else None,
        },
        "max_p95_ms": _max_metric_values(rows, "p95_ms"),
        "max_p95_chars": _max_metric_values(rows, "p95_chars"),
        "route_trend": route_trend,
        "warnings": warnings,
        "governance": {
            "warning_count": len(warnings),
            "route_removed_count": len(route_trend["removed_routes"]),
            "reviewed_route_removed_count": len(reviewed_removed_routes),
            "unreviewed_route_removed_count": len(unreviewed_removed_routes),
            "reviewed_removed_routes": reviewed_removed_routes,
            "unreviewed_removed_routes": unreviewed_removed_routes,
            "samples_sha256_values": _unique_values(rows, "samples_sha256"),
            "script_name_values": _unique_values(rows, "script_name"),
            "sample_count_delta_from_first": _scalar_delta(
                latest.get("sample_count"),
                first.get("sample_count"),
            ),
            "sample_count_delta_from_previous": _scalar_delta(
                latest.get("sample_count"),
                previous.get("sample_count") if previous else None,
            ),
        },
    }
    return report


def load_route_migrations(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    path = path.expanduser()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("migrations"), list):
        records = data["migrations"]
    elif isinstance(data, list):
        records = data
    else:
        raise ValueError("route migration file must contain a JSON list or a migrations list")
    return [record for record in records if isinstance(record, dict)]


def _reviewed_removed_routes(
    removed_routes: list[str],
    route_migrations: list[dict[str, Any]],
) -> list[str]:
    removed = set(removed_routes)
    reviewed: set[str] = set()
    for record in route_migrations:
        status = str(record.get("review_status") or record.get("status") or "").strip().lower()
        if status not in {"accepted", "accepted_route_migration", "reviewed"}:
            continue
        if not str(record.get("review_notes") or "").strip():
            continue
        route = str(record.get("from_route") or record.get("removed_route") or "").strip()
        if route in removed:
            reviewed.add(route)
    return sorted(reviewed)


def _snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": row.get("generated_at"),
        "sample_count": _int_or_none(row.get("sample_count")),
        "run_count": _int_or_none(row.get("run_count")),
        "iterations": _int_or_none(row.get("iterations")),
        "budget_pass": row.get("budget_pass"),
        "baseline_pass": row.get("baseline_pass"),
        "baseline_warning_count": _int_or_none(row.get("baseline_warning_count")),
        "baseline_failure_count": _int_or_none(row.get("baseline_failure_count")),
        "p95_ms": dict(row.get("p95_ms") or {}),
        "p95_chars": dict(row.get("p95_chars") or {}),
        "route_sample_counts": dict(row.get("route_sample_counts") or {}),
    }


def _health_summary(rows: list[dict[str, Any]], latest: dict[str, Any]) -> dict[str, Any]:
    budget_counts = _bool_counts(row.get("budget_pass") for row in rows)
    baseline_counts = _bool_counts(row.get("baseline_pass") for row in rows)
    warnings = [_number(row.get("baseline_warning_count"), 0.0) for row in rows]
    failures = [_number(row.get("baseline_failure_count"), 0.0) for row in rows]
    return {
        "latest_budget_pass": latest.get("budget_pass"),
        "latest_baseline_pass": latest.get("baseline_pass"),
        "all_budget_pass": budget_counts["false"] == 0 and budget_counts["unknown"] == 0,
        "all_baseline_pass": baseline_counts["false"] == 0 and baseline_counts["unknown"] == 0,
        "budget_pass_counts": budget_counts,
        "baseline_pass_counts": baseline_counts,
        "baseline_warning_total": int(sum(warnings)),
        "baseline_failure_total": int(sum(failures)),
        "baseline_warning_max": int(max(warnings) if warnings else 0),
        "baseline_failure_max": int(max(failures) if failures else 0),
    }


def _row_delta(current: dict[str, Any], base: dict[str, Any] | None) -> dict[str, Any]:
    if base is None:
        return {}
    return {
        "sample_count": _scalar_delta(current.get("sample_count"), base.get("sample_count")),
        "run_count": _scalar_delta(current.get("run_count"), base.get("run_count")),
        "iterations": _scalar_delta(current.get("iterations"), base.get("iterations")),
        "p95_ms": _metric_deltas(current.get("p95_ms"), base.get("p95_ms")),
        "p95_chars": _metric_deltas(current.get("p95_chars"), base.get("p95_chars")),
        "route_sample_counts": _route_count_deltas(
            current.get("route_sample_counts"),
            base.get("route_sample_counts"),
        ),
    }


def _metric_deltas(current: Any, base: Any) -> dict[str, dict[str, float | None]]:
    current_map = current if isinstance(current, dict) else {}
    base_map = base if isinstance(base, dict) else {}
    result: dict[str, dict[str, float | None]] = {}
    for metric in sorted(set(current_map) | set(base_map)):
        result[str(metric)] = _scalar_delta(current_map.get(metric), base_map.get(metric))
    return result


def _scalar_delta(current: Any, base: Any) -> dict[str, float | None]:
    current_value = _float_or_none(current)
    base_value = _float_or_none(base)
    if current_value is None or base_value is None:
        return {
            "from": base_value,
            "to": current_value,
            "delta": None,
            "delta_ratio": None,
        }
    delta = current_value - base_value
    return {
        "from": _round_number(base_value),
        "to": _round_number(current_value),
        "delta": _round_number(delta),
        "delta_ratio": _round_optional(_safe_ratio(delta, base_value), digits=6),
    }


def _metric_trends(
    rows: list[dict[str, Any]],
    window_rows: list[dict[str, Any]],
    group: str,
    *,
    unit: str,
) -> dict[str, dict[str, Any]]:
    metrics = _metric_names(rows, group)
    previous = rows[-2] if len(rows) > 1 else None
    latest = rows[-1]
    result: dict[str, dict[str, Any]] = {}

    for metric in metrics:
        first_value = _metric_value(rows[0], group, metric)
        previous_value = _metric_value(previous, group, metric) if previous else None
        latest_value = _metric_value(latest, group, metric)
        window_values = [
            value
            for row in window_rows
            if (value := _metric_value(row, group, metric)) is not None
        ]
        result[metric] = {
            "unit": unit,
            "first": _round_optional(first_value),
            "previous": _round_optional(previous_value),
            "latest": _round_optional(latest_value),
            "delta_from_first": _round_optional(_delta(latest_value, first_value)),
            "delta_ratio_from_first": _round_optional(
                _delta_ratio(latest_value, first_value),
                digits=6,
            ),
            "delta_from_previous": _round_optional(_delta(latest_value, previous_value)),
            "delta_ratio_from_previous": _round_optional(
                _delta_ratio(latest_value, previous_value),
                digits=6,
            ),
            "window_avg": _round_optional(_average(window_values)),
            "min": _round_optional(min(window_values) if window_values else None),
            "max": _round_optional(max(window_values) if window_values else None),
        }
    return result


def _metric_names(rows: list[dict[str, Any]], group: str) -> list[str]:
    names: set[str] = set()
    for row in rows:
        values = row.get(group)
        if isinstance(values, dict):
            names.update(str(key) for key in values)
    return sorted(names)


def _metric_value(row: dict[str, Any] | None, group: str, metric: str) -> float | None:
    if not row:
        return None
    values = row.get(group)
    if not isinstance(values, dict):
        return None
    return _float_or_none(values.get(metric))


def _route_count_deltas(current: Any, base: Any) -> dict[str, dict[str, int]]:
    current_map = current if isinstance(current, dict) else {}
    base_map = base if isinstance(base, dict) else {}
    result: dict[str, dict[str, int]] = {}
    for route in sorted(set(current_map) | set(base_map)):
        current_value = int(_number(current_map.get(route), 0.0))
        base_value = int(_number(base_map.get(route), 0.0))
        result[str(route)] = {
            "from": base_value,
            "to": current_value,
            "delta": current_value - base_value,
        }
    return result


def _route_trend(first: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    first_counts = {
        str(key): int(_number(value, 0.0))
        for key, value in dict(first.get("route_sample_counts") or {}).items()
    }
    latest_counts = {
        str(key): int(_number(value, 0.0))
        for key, value in dict(latest.get("route_sample_counts") or {}).items()
    }
    first_routes = set(first_counts)
    latest_routes = set(latest_counts)
    count_deltas = _route_count_deltas(latest_counts, first_counts)
    return {
        "first_route_count": len(first_routes),
        "latest_route_count": len(latest_routes),
        "added_routes": sorted(latest_routes - first_routes),
        "removed_routes": sorted(first_routes - latest_routes),
        "count_deltas": count_deltas,
        "total_sample_delta": sum(item["delta"] for item in count_deltas.values()),
    }


def _max_metric_values(rows: list[dict[str, Any]], group: str) -> dict[str, dict[str, Any]]:
    metrics: set[str] = set()
    for row in rows:
        group_values = row.get(group)
        if isinstance(group_values, dict):
            metrics.update(str(key) for key in group_values)

    result: dict[str, dict[str, Any]] = {}
    for metric in sorted(metrics):
        best_value: float | None = None
        best_index: int | None = None
        best_generated_at: Any = None
        for index, row in enumerate(rows):
            group_values = row.get(group)
            if not isinstance(group_values, dict):
                continue
            value = _float_or_none(group_values.get(metric))
            if value is None:
                continue
            if best_value is None or value > best_value:
                best_value = value
                best_index = index
                best_generated_at = row.get("generated_at")
        result[metric] = {
            "value": _round_number(best_value) if best_value is not None else None,
            "generated_at": best_generated_at,
            "index": best_index,
        }
    return result


def _build_warnings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    last_generated_at = ""
    for index, row in enumerate(rows):
        generated_at = str(row.get("generated_at") or "")
        if last_generated_at and generated_at and generated_at < last_generated_at:
            warnings.append(
                {
                    "type": "non_monotonic_generated_at",
                    "index": index,
                    "generated_at": generated_at,
                    "previous_generated_at": last_generated_at,
                }
            )
        if generated_at:
            last_generated_at = generated_at

    for group in ("p95_ms", "p95_chars"):
        metrics = _metric_names(rows, group)
        for metric in metrics:
            missing_indexes = [
                index
                for index, row in enumerate(rows)
                if _metric_value(row, group, metric) is None
            ]
            if missing_indexes:
                warnings.append(
                    {
                        "type": "missing_metric_values",
                        "group": group,
                        "metric": metric,
                        "indexes": missing_indexes,
                    }
                )
    sample_hashes = _unique_values(rows, "samples_sha256")
    if "" in sample_hashes:
        warnings.append(
            {
                "type": "missing_samples_sha256",
                "indexes": [
                    index
                    for index, row in enumerate(rows)
                    if not str(row.get("samples_sha256") or "")
                ],
            }
        )
    non_empty_hashes = [value for value in sample_hashes if value]
    if len(non_empty_hashes) > 1:
        warnings.append(
            {
                "type": "mixed_samples_sha256",
                "values": non_empty_hashes,
            }
        )
    return warnings


def _unique_values(rows: list[dict[str, Any]], key: str) -> list[str]:
    values = {str(row.get(key) or "") for row in rows}
    return sorted(values)


def _bool_counts(values: Any) -> dict[str, int]:
    counts = {"true": 0, "false": 0, "unknown": 0}
    for value in values:
        if value is True:
            counts["true"] += 1
        elif value is False:
            counts["false"] += 1
        else:
            counts["unknown"] += 1
    return counts


def _number(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return int(parsed)


def _safe_ratio(delta: float, base: float) -> float | None:
    if base == 0:
        return 0.0 if delta == 0 else None
    return delta / base


def _round_number(value: float, *, digits: int = 4) -> float:
    return round(value, digits)


def _round_optional(value: float | None, *, digits: int = 4) -> float | None:
    if value is None:
        return None
    return _round_number(value, digits=digits)


def _delta(current: float | None, base: float | None) -> float | None:
    if current is None or base is None:
        return None
    return current - base


def _delta_ratio(current: float | None, base: float | None) -> float | None:
    delta = _delta(current, base)
    if delta is None or base is None:
        return None
    return _safe_ratio(delta, base)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize hot-path benchmark trend history")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY), help="benchmark history JSONL path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSON report output path")
    parser.add_argument(
        "--route-migrations",
        default=str(DEFAULT_ROUTE_MIGRATIONS),
        help="optional reviewed route migration JSON path",
    )
    parser.add_argument("--window-size", type=int, default=5, help="number of latest rows for rolling stats")
    parser.add_argument("--print-json", action="store_true", help="print JSON report to stdout")
    parser.add_argument(
        "--fail-on-latest-failure",
        action="store_true",
        help="return exit code 1 when the latest history row failed a budget or baseline gate",
    )
    parser.add_argument(
        "--min-history-rows",
        type=int,
        default=1,
        help="return 1 when fewer history rows are present than this value",
    )
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="return 1 when the trend report contains governance warnings",
    )
    parser.add_argument(
        "--fail-on-route-removal",
        action="store_true",
        help="return 1 when latest route coverage removed a route seen in the first row",
    )
    parser.add_argument(
        "--fail-on-sample-drop",
        action="store_true",
        help="return 1 when latest sample_count is lower than the previous history row",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    history_path = Path(args.history).expanduser()

    try:
        rows = load_history(history_path)
        route_migrations = load_route_migrations(Path(args.route_migrations).expanduser())
        report = build_report(
            rows,
            history_path=history_path,
            window_size=args.window_size,
            route_migrations=route_migrations,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_json:
        print(output_text)
    else:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text + "\n", encoding="utf-8")
        _print_summary(report, out_path)

    latest = report["latest"]
    latest_failed = latest.get("budget_pass") is False or latest.get("baseline_pass") is False
    governance = report["governance"]
    if args.fail_on_latest_failure and latest_failed:
        return 1
    if report["row_count"] < max(1, args.min_history_rows):
        return 1
    if args.fail_on_warnings and governance["warning_count"] > 0:
        return 1
    if args.fail_on_route_removal and governance.get("unreviewed_route_removed_count", 0) > 0:
        return 1
    previous_delta = governance["sample_count_delta_from_previous"]
    if args.fail_on_sample_drop and previous_delta.get("delta") is not None and previous_delta["delta"] < 0:
        return 1
    return 0


def _print_summary(report: dict[str, Any], out_path: Path) -> None:
    latest = report["latest"]
    health = report["health"]
    print(f"Wrote {out_path}")
    print(
        "Hot-path trends: "
        f"{report['row_count']} rows, "
        f"latest={latest.get('generated_at')}, "
        f"budget_pass={latest.get('budget_pass')}, "
        f"baseline_pass={latest.get('baseline_pass')}"
    )
    print(
        "  latest: "
        f"samples={latest.get('sample_count')} "
        f"runs={latest.get('run_count')} "
        f"routes={len(latest.get('route_sample_counts') or {})}"
    )
    print(
        "  history health: "
        f"all_budget_pass={health['all_budget_pass']} "
        f"all_baseline_pass={health['all_baseline_pass']} "
        f"baseline_warnings={health['baseline_warning_total']} "
        f"baseline_failures={health['baseline_failure_total']}"
    )
    governance = report.get("governance") or {}
    print(
        "  governance: "
        f"warnings={governance.get('warning_count')} "
        f"route_removed={governance.get('route_removed_count')}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
