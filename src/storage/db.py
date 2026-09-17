"""SQLite 会话历史存储。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.text.edit_memory import (
    MemoryRule,
    infer_confirmed_edit_failure,
    infer_term_replacements,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    raw_asr_text TEXT,
    final_text TEXT,
    mode TEXT,
    asr_engine TEXT,
    llm_provider TEXT,
    llm_model TEXT,
    processing_time_ms INTEGER,
    corrections_json TEXT,
    deleted_segments_json TEXT,
    constraints_json TEXT,
    risk_level TEXT,
    need_confirm INTEGER,
    pasted_success INTEGER
);

CREATE TABLE IF NOT EXISTS confirmed_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    session_id INTEGER,
    source_kind TEXT,
    before_text TEXT,
    after_text TEXT,
    mode TEXT,
    output_script TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS memory_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_edit_id INTEGER,
    kind TEXT NOT NULL,
    pattern TEXT NOT NULL,
    replacement TEXT NOT NULL,
    mode TEXT,
    output_script TEXT,
    support_count INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(kind, pattern, replacement, mode, output_script)
);

CREATE TABLE IF NOT EXISTS confirmed_edit_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    record_id INTEGER,
    confirmed_edit_id INTEGER,
    source_kind TEXT NOT NULL,
    before_text TEXT,
    after_text TEXT,
    raw_asr_text TEXT,
    cleaned_text TEXT,
    final_text_before TEXT,
    route_before_json TEXT,
    intent_frame_before_json TEXT,
    quality_gate_attribution_before_json TEXT,
    inferred_failure_type TEXT NOT NULL,
    should_add_regression INTEGER NOT NULL DEFAULT 0
);
"""


class SessionStorage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def save(self, record: dict[str, Any]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO sessions (
                    created_at, raw_asr_text, final_text, mode,
                    asr_engine, llm_provider, llm_model, processing_time_ms,
                    corrections_json, deleted_segments_json, constraints_json,
                    risk_level, need_confirm, pasted_success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("created_at", now),
                    record.get("raw_asr_text", ""),
                    record.get("final_text", ""),
                    record.get("mode", ""),
                    record.get("asr_engine", ""),
                    record.get("llm_provider", ""),
                    record.get("llm_model", ""),
                    record.get("processing_time_ms", 0),
                    json.dumps(record.get("corrections", []), ensure_ascii=False),
                    json.dumps(record.get("deleted_segments", []), ensure_ascii=False),
                    json.dumps(record.get("constraints", []), ensure_ascii=False),
                    record.get("risk_level", "low"),
                    1 if record.get("need_confirm") else 0,
                    1 if record.get("pasted_success") else 0,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def save_confirmed_edit(
        self,
        *,
        session_id: int | None,
        source_kind: str,
        before_text: str,
        after_text: str,
        mode: str = "",
        output_script: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}
        learned_rules = infer_term_replacements(before_text, after_text)
        failure_context = _extract_failure_context(
            metadata,
            source_kind=source_kind,
            before_text=before_text,
        )
        failure_sample = infer_confirmed_edit_failure(
            source_kind=source_kind,
            before_text=before_text,
            after_text=after_text,
            raw_asr_text=failure_context["raw_asr_text"],
            cleaned_text=failure_context["cleaned_text"],
            final_text_before=failure_context["final_text_before"],
            route_before=failure_context["route_before"],
            intent_frame_before=failure_context["intent_frame_before"],
            quality_gate_attribution_before=failure_context["quality_gate_attribution_before"],
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO confirmed_edits (
                    created_at, session_id, source_kind, before_text, after_text,
                    mode, output_script, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    session_id,
                    source_kind,
                    before_text,
                    after_text,
                    mode,
                    output_script,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            edit_id = int(cur.lastrowid)
            failure_id = self._insert_confirmed_edit_failure(
                conn,
                created_at=now,
                record_id=session_id,
                confirmed_edit_id=edit_id,
                source_kind=source_kind,
                before_text=before_text,
                after_text=after_text,
                failure_context=failure_context,
                failure_sample=failure_sample,
            )
            for rule in learned_rules:
                conn.execute(
                    """
                    INSERT INTO memory_rules (
                        created_at, updated_at, source_edit_id, kind, pattern,
                        replacement, mode, output_script, support_count, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                    ON CONFLICT(kind, pattern, replacement, mode, output_script)
                    DO UPDATE SET
                        updated_at=excluded.updated_at,
                        support_count=support_count + 1,
                        active=1
                    """,
                    (
                        now,
                        now,
                        edit_id,
                        str(rule.get("kind") or "term_replacement"),
                        str(rule.get("pattern") or ""),
                        str(rule.get("replacement") or ""),
                        mode,
                        output_script,
                    ),
                )
            conn.commit()
        failure_sample = {
            "id": failure_id,
            "record_id": session_id,
            "confirmed_edit_id": edit_id,
            "source_kind": source_kind,
            **failure_sample,
        }
        return {"edit_id": edit_id, "learned_rules": learned_rules, "failure_sample": failure_sample}

    def _insert_confirmed_edit_failure(
        self,
        conn: sqlite3.Connection,
        *,
        created_at: str,
        record_id: int | None,
        confirmed_edit_id: int,
        source_kind: str,
        before_text: str,
        after_text: str,
        failure_context: dict[str, Any],
        failure_sample: dict[str, Any],
    ) -> int:
        cur = conn.execute(
            """
            INSERT INTO confirmed_edit_failures (
                created_at, record_id, confirmed_edit_id, source_kind,
                before_text, after_text, raw_asr_text, cleaned_text,
                final_text_before, route_before_json, intent_frame_before_json,
                quality_gate_attribution_before_json, inferred_failure_type,
                should_add_regression
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                record_id,
                confirmed_edit_id,
                source_kind,
                before_text,
                after_text,
                failure_context["raw_asr_text"],
                failure_context["cleaned_text"],
                failure_context["final_text_before"],
                json.dumps(failure_context["route_before"], ensure_ascii=False),
                json.dumps(failure_context["intent_frame_before"], ensure_ascii=False),
                json.dumps(failure_context["quality_gate_attribution_before"], ensure_ascii=False),
                failure_sample["inferred_failure_type"],
                1 if failure_sample["should_add_regression"] else 0,
            ),
        )
        return int(cur.lastrowid)

    def recent_confirmed_edit_failures(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM confirmed_edit_failures
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_deserialize_failure_row(row) for row in rows]

    def load_memory_rules(self, limit: int = 500) -> list[MemoryRule]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT pattern, replacement, mode, output_script
                FROM memory_rules
                WHERE active = 1 AND kind = 'term_replacement'
                ORDER BY support_count DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            MemoryRule(
                pattern=str(row["pattern"] or ""),
                replacement=str(row["replacement"] or ""),
                mode=str(row["mode"] or ""),
                output_script=str(row["output_script"] or ""),
            )
            for row in rows
        ]


def _extract_failure_context(
    metadata: dict[str, Any],
    *,
    source_kind: str,
    before_text: str,
) -> dict[str, Any]:
    debug = metadata.get("debug") if isinstance(metadata.get("debug"), dict) else metadata
    route = _dict_from(debug.get("route"))
    intent_frame = _dict_from(debug.get("intent_frame"))
    quality_gate = _dict_from(debug.get("quality_gate_attribution"))
    return {
        "raw_asr_text": str(debug.get("raw_asr_text") or ""),
        "cleaned_text": str(debug.get("cleaned_text") or ""),
        "final_text_before": str(debug.get("final_text") or before_text if source_kind == "final_output" else debug.get("final_text") or ""),
        "route_before": route,
        "intent_frame_before": intent_frame,
        "quality_gate_attribution_before": quality_gate,
    }


def _dict_from(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _deserialize_failure_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["route_before"] = _loads_json_object(item.pop("route_before_json", ""))
    item["intent_frame_before"] = _loads_json_object(item.pop("intent_frame_before_json", ""))
    item["quality_gate_attribution_before"] = _loads_json_object(
        item.pop("quality_gate_attribution_before_json", "")
    )
    item["should_add_regression"] = bool(item.get("should_add_regression"))
    return item


def _loads_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
