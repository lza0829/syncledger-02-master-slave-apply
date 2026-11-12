from __future__ import annotations

import json
from typing import Any

import sqlite3


def _run(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if r is None else dict(r)


def _entry(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    d["align_key"] = json.loads(d.pop("align_key_json"))
    d["fields"] = json.loads(d.pop("fields_json"))
    return d


def insert_run(
    conn: sqlite3.Connection,
    *,
    run_no: str,
    batch_id: int,
    pair_id: int,
    policy: str,
    failure_strategy: str,
    status: str,
    target_side: str | None,
    counts: dict[str, int],
    note: str | None,
    error: str | None,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO disposition_runs(
            run_no, batch_id, pair_id, policy, failure_strategy, status, target_side,
            examined, applied, failed, skipped, recorded, fields_overwritten,
            remaining_mismatch, note, error, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_no,
            batch_id,
            pair_id,
            policy,
            failure_strategy,
            status,
            target_side,
            counts["examined"],
            counts["applied"],
            counts["failed"],
            counts["skipped"],
            counts["recorded"],
            counts["fields_overwritten"],
            counts["remaining_mismatch"],
            note,
            error,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def insert_entry(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    action: dict[str, Any],
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO disposition_entries(
            run_id, diff_id, align_key_json, kind, action, target_side,
            fields_json, reason, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            action.get("diff_id"),
            json.dumps(action["align_key"], ensure_ascii=False),
            action["kind"],
            action["action"],
            action.get("target_side"),
            json.dumps(action.get("fields") or [], ensure_ascii=False),
            action.get("reason"),
            created_at,
        ),
    )
    return int(cur.lastrowid)


def list_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM disposition_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_run(r) for r in rows]  # type: ignore[misc]


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    return _run(
        conn.execute("SELECT * FROM disposition_runs WHERE id=?", (run_id,)).fetchone()
    )


def list_entries(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM disposition_entries WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    return [_entry(r) for r in rows]  # type: ignore[misc]


def count_runs(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) c FROM disposition_runs").fetchone()["c"])


def latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return _run(
        conn.execute("SELECT * FROM disposition_runs ORDER BY id DESC LIMIT 1").fetchone()
    )
