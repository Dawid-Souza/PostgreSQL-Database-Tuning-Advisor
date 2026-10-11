from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.security.redaction import redact_text


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return str(value)


@contextmanager
def connect():
    settings.app_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.app_sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_store() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS log_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                database_name TEXT,
                postgres_config_id TEXT,
                environment_id TEXT,
                source TEXT NOT NULL,
                min_ms REAL NOT NULL DEFAULT 0,
                lines_requested INTEGER,
                command TEXT,
                fetch_error TEXT,
                raw_bytes INTEGER NOT NULL DEFAULT 0,
                raw_truncated INTEGER NOT NULL DEFAULT 0,
                entries_count INTEGER NOT NULL DEFAULT 0,
                ignored_count INTEGER NOT NULL DEFAULT 0,
                groups_count INTEGER NOT NULL DEFAULT 0,
                recommendations_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS log_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES log_runs(id) ON DELETE CASCADE,
                normalized_query TEXT NOT NULL,
                sample_query TEXT NOT NULL,
                calls INTEGER NOT NULL,
                total_ms REAL NOT NULL,
                mean_ms REAL NOT NULL,
                max_ms REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS log_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES log_runs(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                sql_text TEXT,
                confidence REAL NOT NULL,
                evidence_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_log_groups_run_total ON log_groups(run_id, total_ms DESC);
            CREATE INDEX IF NOT EXISTS ix_log_recs_run_order ON log_recommendations(run_id, severity, confidence DESC);
            CREATE INDEX IF NOT EXISTS ix_log_runs_created ON log_runs(created_at DESC);
            """
        )


def create_run(
    *,
    database_name: str | None,
    postgres_config_id: str | None,
    environment_id: str | None,
    source: str,
    min_ms: float,
    lines_requested: int | None = None,
    command: str | None = None,
    fetch_error: str | None = None,
    raw_bytes: int = 0,
    raw_truncated: bool = False,
) -> int:
    init_store()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO log_runs (
                created_at, database_name, postgres_config_id, environment_id, source,
                min_ms, lines_requested, command, fetch_error, raw_bytes, raw_truncated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                database_name,
                postgres_config_id,
                environment_id,
                source,
                float(min_ms or 0),
                lines_requested,
                redact_text(command),
                redact_text(fetch_error),
                int(raw_bytes or 0),
                1 if raw_truncated else 0,
            ),
        )
        return int(cur.lastrowid)


def save_groups(run_id: int, groups: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO log_groups (
                run_id, normalized_query, sample_query, calls, total_ms, mean_ms, max_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    g.get("normalized_query") or "",
                    g.get("sample_query") or "",
                    int(g.get("calls") or 0),
                    float(g.get("total_ms") or 0),
                    float(g.get("mean_ms") or 0),
                    float(g.get("max_ms") or 0),
                )
                for g in groups
            ],
        )
        conn.execute("UPDATE log_runs SET groups_count = ? WHERE id = ?", (len(groups), run_id))


def save_recommendations(run_id: int, recommendations: list[Any]) -> None:
    rows = []
    for rec in recommendations:
        d = asdict(rec) if is_dataclass(rec) else dict(rec)
        rows.append(
            (
                run_id,
                d.get("kind") or "unknown",
                d.get("severity") or "low",
                d.get("title") or "",
                d.get("detail") or "",
                d.get("sql"),
                float(d.get("confidence") or 0),
                json.dumps(d.get("evidence") or {}, ensure_ascii=False, default=_json_default),
            )
        )
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO log_recommendations (
                run_id, kind, severity, title, detail, sql_text, confidence, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.execute("UPDATE log_runs SET recommendations_count = ? WHERE id = ?", (len(rows), run_id))


def update_run_counts(
    run_id: int,
    *,
    entries_count: int,
    ignored_count: int,
    groups_count: int | None = None,
    recommendations_count: int | None = None,
) -> None:
    sets = ["entries_count = ?", "ignored_count = ?"]
    params: list[Any] = [entries_count, ignored_count]
    if groups_count is not None:
        sets.append("groups_count = ?")
        params.append(groups_count)
    if recommendations_count is not None:
        sets.append("recommendations_count = ?")
        params.append(recommendations_count)
    params.append(run_id)
    with connect() as conn:
        conn.execute(f"UPDATE log_runs SET {', '.join(sets)} WHERE id = ?", params)


def get_run(run_id: int) -> dict[str, Any] | None:
    init_store()
    with connect() as conn:
        row = conn.execute("SELECT * FROM log_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def latest_run(database_name: str | None = None) -> dict[str, Any] | None:
    init_store()
    with connect() as conn:
        if database_name:
            row = conn.execute(
                "SELECT * FROM log_runs WHERE database_name = ? ORDER BY id DESC LIMIT 1",
                (database_name,),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM log_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    init_store()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM log_runs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]


def _set_autoincrement_sequence(conn: sqlite3.Connection, table_name: str, value: int = 0) -> None:
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table_name,))
    if value > 0:
        conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table_name, int(value)))


def _reset_log_sequences(conn: sqlite3.Connection) -> None:
    for table_name in ("log_runs", "log_groups", "log_recommendations"):
        _set_autoincrement_sequence(conn, table_name, 0)


def _compact_run_ids(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id FROM log_runs ORDER BY id ASC").fetchall()
    mapping = {int(row["id"]): index for index, row in enumerate(rows, start=1)}
    if not mapping:
        _reset_log_sequences(conn)
        return

    if any(old_id != new_id for old_id, new_id in mapping.items()):
        for old_id in mapping:
            temp_id = -old_id
            conn.execute("UPDATE log_recommendations SET run_id = ? WHERE run_id = ?", (temp_id, old_id))
            conn.execute("UPDATE log_groups SET run_id = ? WHERE run_id = ?", (temp_id, old_id))
            conn.execute("UPDATE log_runs SET id = ? WHERE id = ?", (temp_id, old_id))

        for old_id, new_id in mapping.items():
            temp_id = -old_id
            conn.execute("UPDATE log_runs SET id = ? WHERE id = ?", (new_id, temp_id))
            conn.execute("UPDATE log_recommendations SET run_id = ? WHERE run_id = ?", (new_id, temp_id))
            conn.execute("UPDATE log_groups SET run_id = ? WHERE run_id = ?", (new_id, temp_id))

    _set_autoincrement_sequence(conn, "log_runs", len(mapping))


def delete_runs(run_ids: list[int]) -> int:
    init_store()
    clean_ids = sorted({int(run_id) for run_id in run_ids if int(run_id) > 0})
    if not clean_ids:
        return 0
    placeholders = ",".join("?" for _ in clean_ids)
    with connect() as conn:
        conn.execute(f"DELETE FROM log_recommendations WHERE run_id IN ({placeholders})", clean_ids)
        conn.execute(f"DELETE FROM log_groups WHERE run_id IN ({placeholders})", clean_ids)
        cur = conn.execute(f"DELETE FROM log_runs WHERE id IN ({placeholders})", clean_ids)
        deleted = int(cur.rowcount or 0)
        if deleted:
            _compact_run_ids(conn)
        return deleted


def delete_all_runs() -> int:
    init_store()
    with connect() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM log_runs").fetchone()[0])
        conn.execute("DELETE FROM log_recommendations")
        conn.execute("DELETE FROM log_groups")
        conn.execute("DELETE FROM log_runs")
        _reset_log_sequences(conn)
        return total


def _paginate(total: int, page: int, page_size: int) -> dict[str, Any]:
    page_size = max(5, min(int(page_size or 50), 500))
    pages = max(1, (int(total) + page_size - 1) // page_size)
    page = max(1, min(int(page or 1), pages))
    return {"page": page, "page_size": page_size, "pages": pages, "total": int(total), "offset": (page - 1) * page_size}


def get_groups_page(run_id: int, page: int = 1, page_size: int = 50) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    init_store()
    with connect() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM log_groups WHERE run_id = ?", (run_id,)).fetchone()[0])
        p = _paginate(total, page, page_size)
        rows = conn.execute(
            """
            SELECT normalized_query, sample_query, calls,
                   round(total_ms, 2) AS total_ms,
                   round(mean_ms, 2) AS mean_ms,
                   round(max_ms, 2) AS max_ms
            FROM log_groups
            WHERE run_id = ?
            ORDER BY total_ms DESC
            LIMIT ? OFFSET ?
            """,
            (run_id, p["page_size"], p["offset"]),
        ).fetchall()
        return [dict(r) for r in rows], p


def get_recommendations_page(run_id: int, page: int = 1, page_size: int = 50) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    init_store()
    with connect() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM log_recommendations WHERE run_id = ?", (run_id,)).fetchone()[0])
        p = _paginate(total, page, page_size)
        rows = conn.execute(
            """
            SELECT kind, severity, title, detail, sql_text, confidence, evidence_json
            FROM log_recommendations
            WHERE run_id = ?
            ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END,
                     confidence DESC,
                     id ASC
            LIMIT ? OFFSET ?
            """,
            (run_id, p["page_size"], p["offset"]),
        ).fetchall()
        recs: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["sql"] = item.pop("sql_text")
            try:
                item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            except Exception:
                item["evidence"] = {}
            recs.append(item)
        return recs, p


def build_result(run_id: int, group_page: int = 1, rec_page: int = 1, page_size: int = 50) -> dict[str, Any] | None:
    run = get_run(run_id)
    if not run:
        return None
    groups, group_pagination = get_groups_page(run_id, group_page, page_size)
    recs, rec_pagination = get_recommendations_page(run_id, rec_page, page_size)
    return {
        "run": run,
        "run_id": run_id,
        "entries_count": run.get("entries_count", 0),
        "ignored_count": run.get("ignored_count", 0),
        "groups_count": run.get("groups_count", 0),
        "recommendations_count": run.get("recommendations_count", 0),
        "groups": groups,
        "recommendations": recs,
        "group_pagination": group_pagination,
        "rec_pagination": rec_pagination,
    }
