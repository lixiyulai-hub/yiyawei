from __future__ import annotations

import hashlib
import json

from scripts.report_hot_path_trends import build_report, load_history, main


def _row(
    generated_at: str,
    *,
    sample_count: int = 2,
    route_ms: float = 0.1,
    context_chars: float = 500.0,
    budget_pass: bool = True,
    baseline_pass: bool = True,
    routes: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_version": 1,
        "script_name": "scripts/benchmark_hot_path.py",
        "generated_at": generated_at,
        "samples_sha256": "sample-sha",
        "sample_count": sample_count,
        "run_count": sample_count * 30,
        "iterations": 30,
        "budget_pass": budget_pass,
        "baseline_pass": baseline_pass,
        "baseline_warning_count": 0 if baseline_pass else 1,
        "baseline_failure_count": 0 if baseline_pass else 1,
        "p95_ms": {
            "route_ms": route_ms,
            "default_non_llm_ms": route_ms + 1.0,
        },
        "p95_chars": {
            "route_context_chars": context_chars,
            "fallback_chars": context_chars + 100.0,
        },
        "route_sample_counts": routes or {"bug_report:general": sample_count},
    }


def test_build_report_summarizes_latest_deltas_and_routes():
    rows = [
        _row(
            "2026-06-14T00:00:00+00:00",
            sample_count=2,
            route_ms=0.1,
            routes={"bug_report:general": 2},
        ),
        _row(
            "2026-06-14T01:00:00+00:00",
            sample_count=3,
            route_ms=0.2,
            routes={"bug_report:general": 2, "ui_ux_design:saas": 1},
        ),
        _row(
            "2026-06-14T02:00:00+00:00",
            sample_count=4,
            route_ms=0.3,
            context_chars=700.0,
            routes={"bug_report:general": 2, "ui_ux_design:saas": 2},
        ),
    ]

    report = build_report(rows, window_size=2)

    assert report["schema_version"] == 1
    assert report["artifact_version"] == 1
    assert report["script_name"] == "scripts/report_hot_path_trends.py"
    assert report["row_count"] == 3
    assert report["window_size"] == 2
    assert report["latest"]["sample_count"] == 4
    assert report["health"]["all_budget_pass"] is True
    assert report["deltas"]["from_first"]["sample_count"]["delta"] == 2.0
    assert report["deltas"]["from_previous"]["p95_ms"]["route_ms"]["delta"] == 0.1
    assert report["metric_trends"]["p95_ms"]["route_ms"]["unit"] == "ms"
    assert report["metric_trends"]["p95_ms"]["route_ms"]["first"] == 0.1
    assert report["metric_trends"]["p95_ms"]["route_ms"]["latest"] == 0.3
    assert report["metric_trends"]["p95_ms"]["route_ms"]["window_avg"] == 0.25
    assert report["metric_trends"]["p95_chars"]["route_context_chars"]["latest"] == 700.0
    assert report["route_trend"]["added_routes"] == ["ui_ux_design:saas"]
    assert report["route_trend"]["count_deltas"]["ui_ux_design:saas"]["delta"] == 2
    assert report["governance"]["warning_count"] == 0
    assert report["governance"]["route_removed_count"] == 0
    assert report["governance"]["samples_sha256_values"] == ["sample-sha"]
    assert report["governance"]["sample_count_delta_from_first"]["delta"] == 2.0


def test_load_history_ignores_blank_lines(tmp_path):
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        json.dumps(_row("2026-06-14T00:00:00+00:00"), ensure_ascii=False)
        + "\n\n"
        + json.dumps(_row("2026-06-14T01:00:00+00:00"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    rows = load_history(history_path)

    assert len(rows) == 2


def test_zero_baseline_value_uses_null_ratio_not_infinity():
    rows = [
        _row("2026-06-14T00:00:00+00:00", route_ms=0.0),
        _row("2026-06-14T01:00:00+00:00", route_ms=0.2),
    ]

    report = build_report(rows)

    assert report["metric_trends"]["p95_ms"]["route_ms"]["delta_ratio_from_first"] is None
    encoded = json.dumps(report, allow_nan=False)
    assert "Infinity" not in encoded


def test_missing_metric_values_emit_warning_not_crash():
    rows = [
        _row("2026-06-14T00:00:00+00:00", route_ms=0.1),
        _row("2026-06-14T01:00:00+00:00", route_ms=0.2),
    ]
    del rows[1]["p95_ms"]["route_ms"]  # type: ignore[index]

    report = build_report(rows)

    assert report["metric_trends"]["p95_ms"]["route_ms"]["latest"] is None
    assert any(item["type"] == "missing_metric_values" for item in report["warnings"])
    assert report["governance"]["warning_count"] == 1


def test_history_missing_or_mixed_sample_hashes_emit_warnings():
    rows = [
        _row("2026-06-14T00:00:00+00:00"),
        _row("2026-06-14T01:00:00+00:00"),
        _row("2026-06-14T02:00:00+00:00"),
    ]
    del rows[0]["samples_sha256"]
    rows[2]["samples_sha256"] = "other-sha"

    report = build_report(rows)

    warning_types = {item["type"] for item in report["warnings"]}
    assert "missing_samples_sha256" in warning_types
    assert "mixed_samples_sha256" in warning_types


def test_hot_path_trends_cli_writes_report(tmp_path):
    history_path = tmp_path / "history.jsonl"
    out_path = tmp_path / "trends.json"
    history_path.write_text(
        json.dumps(_row("2026-06-14T00:00:00+00:00"), ensure_ascii=False)
        + "\n"
        + json.dumps(_row("2026-06-14T01:00:00+00:00"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--history",
            str(history_path),
            "--out",
            str(out_path),
            "--window-size",
            "1",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["history_path"] == str(history_path.resolve())
    assert data["history_sha256"] == hashlib.sha256(history_path.read_bytes()).hexdigest()
    assert data["window_size"] == 1
    assert data["row_count"] == 2


def test_hot_path_trends_cli_fails_on_empty_or_bad_history(tmp_path):
    empty_path = tmp_path / "empty.jsonl"
    bad_path = tmp_path / "bad.jsonl"
    out_path = tmp_path / "trends.json"
    empty_path.write_text("", encoding="utf-8")
    bad_path.write_text("{bad json}\n", encoding="utf-8")

    empty_exit = main(["--history", str(empty_path), "--out", str(out_path)])
    bad_exit = main(["--history", str(bad_path), "--out", str(out_path)])

    assert empty_exit == 2
    assert bad_exit == 2


def test_hot_path_trends_cli_can_fail_on_latest_failure(tmp_path):
    history_path = tmp_path / "history.jsonl"
    out_path = tmp_path / "trends.json"
    history_path.write_text(
        json.dumps(
            _row("2026-06-14T01:00:00+00:00", budget_pass=False),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--history",
            str(history_path),
            "--out",
            str(out_path),
            "--fail-on-latest-failure",
        ]
    )

    assert exit_code == 1


def test_hot_path_trends_cli_can_fail_on_history_depth_warnings_route_removal_and_sample_drop(tmp_path):
    out_path = tmp_path / "trends.json"

    short_history = tmp_path / "short.jsonl"
    short_history.write_text(
        json.dumps(_row("2026-06-14T00:00:00+00:00"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--history",
                str(short_history),
                "--out",
                str(out_path),
                "--min-history-rows",
                "2",
            ]
        )
        == 1
    )

    warning_history = tmp_path / "warning.jsonl"
    rows = [
        _row("2026-06-14T00:00:00+00:00", route_ms=0.1),
        _row("2026-06-14T01:00:00+00:00", route_ms=0.2),
    ]
    del rows[1]["p95_ms"]["route_ms"]  # type: ignore[index]
    warning_history.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--history",
                str(warning_history),
                "--out",
                str(out_path),
                "--fail-on-warnings",
            ]
        )
        == 1
    )

    route_drop_history = tmp_path / "route-drop.jsonl"
    route_drop_history.write_text(
        json.dumps(
            _row(
                "2026-06-14T00:00:00+00:00",
                routes={"bug_report:general": 1, "ui_ux_design:saas": 1},
            ),
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps(
            _row("2026-06-14T01:00:00+00:00", routes={"bug_report:general": 1}),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--history",
                str(route_drop_history),
                "--out",
                str(out_path),
                "--fail-on-route-removal",
            ]
        )
        == 1
    )

    reviewed_migrations = tmp_path / "route-migrations.json"
    reviewed_migrations.write_text(
        json.dumps(
            {
                "migrations": [
                    {
                        "from_route": "ui_ux_design:saas",
                        "to_route": "ui_ux_design:general",
                        "review_status": "accepted_route_migration",
                        "review_notes": "Reviewed intentional route migration.",
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--history",
                str(route_drop_history),
                "--out",
                str(out_path),
                "--route-migrations",
                str(reviewed_migrations),
                "--fail-on-route-removal",
            ]
        )
        == 0
    )
    reviewed_report = json.loads(out_path.read_text(encoding="utf-8"))
    assert reviewed_report["governance"]["route_removed_count"] == 1
    assert reviewed_report["governance"]["unreviewed_route_removed_count"] == 0
    assert reviewed_report["governance"]["reviewed_removed_routes"] == ["ui_ux_design:saas"]

    sample_drop_history = tmp_path / "sample-drop.jsonl"
    sample_drop_history.write_text(
        json.dumps(_row("2026-06-14T00:00:00+00:00", sample_count=3), ensure_ascii=False)
        + "\n"
        + json.dumps(_row("2026-06-14T01:00:00+00:00", sample_count=2), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--history",
                str(sample_drop_history),
                "--out",
                str(out_path),
                "--fail-on-sample-drop",
            ]
        )
        == 1
    )
