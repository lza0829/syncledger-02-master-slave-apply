"""Execute master-slave dispositions against a reconcile batch's diff list.

Guarantees this module is built around:

- Exactly one policy per run (left_wins / right_wins / record_only) — the
  three are mutually exclusive and a run never writes both sides.
- Overwrite runs really write the designated side's working fixture (side
  storage), and every written key leaves a ledger entry with
  key / field / old value / new value. record_only never touches side storage.
- Mid-batch failure strategy is fixed: keep successful overwrites, record
  failed keys individually, mark the run partial_success. Never mixed with
  whole-batch rollback.
- Reported counts (applied / failed / skipped / remaining mismatches) are
  derived from the ledger entries and from a fresh re-read of side storage —
  never from flipping diff status flags.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import fixtures_dir
from app.db import connect
from app.engines import disposition as disp
from app.engines.reconcile import compare_sides
from app.repositories import batches as batch_repo
from app.repositories import dispositions as disp_repo
from app.repositories import pairs as pair_repo


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_rows(fixture_name: str) -> list[dict[str, Any]]:
    path = fixtures_dir() / fixture_name
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"fixture {fixture_name} must be a JSON array")
    return data


def _write_rows_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _tally(actions: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "examined": len(actions),
        "applied": sum(1 for a in actions if a["action"] == disp.ACTION_OVERWRITTEN),
        "failed": sum(1 for a in actions if a["action"] == disp.ACTION_FAILED),
        "skipped": sum(1 for a in actions if a["action"] == disp.ACTION_SKIPPED),
        "recorded": sum(1 for a in actions if a["action"] == disp.ACTION_RECORDED),
        "fields_overwritten": sum(
            len(a["fields"]) for a in actions if a["action"] == disp.ACTION_OVERWRITTEN
        ),
    }


def _status_for(counts: dict[str, int], write_error: str | None) -> str:
    if write_error is not None:
        return "failed"
    if counts["failed"] > 0 and counts["applied"] > 0:
        return "partial_success"
    if counts["failed"] > 0:
        return "failed"
    return "completed"


def _remaining_mismatch(
    diffs: list[dict[str, Any]],
    *,
    align_keys: list[str],
    compare_fields: list[str],
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
) -> int:
    """Recompute, from current side storage, how many of the batch's
    field_mismatch keys still disagree. Never inferred from status flags."""
    left_idx = {tuple(r.get(k) for k in align_keys): r for r in left_rows}
    right_idx = {tuple(r.get(k) for k in align_keys): r for r in right_rows}
    remaining = 0
    for d in diffs:
        if d["kind"] != "field_mismatch":
            continue
        kt = tuple(d["align_key"].get(k) for k in align_keys)
        left = left_idx.get(kt)
        right = right_idx.get(kt)
        if left is None or right is None:
            remaining += 1
            continue
        if any(left.get(f) != right.get(f) for f in compare_fields):
            remaining += 1
    return remaining


def run_disposition(batch_id: int, policy: str | None, note: str | None = None) -> dict[str, Any]:
    conn = connect()
    fixture_backup: tuple[Path, bytes] | None = None
    try:
        batch = batch_repo.get_batch(conn, batch_id)
        if not batch:
            raise ValueError("batch not found")
        pair = pair_repo.get_pair(conn, batch["pair_id"])
        if not pair:
            raise ValueError("pair not found")

        if policy is None:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='default_policy'"
            ).fetchone()
            policy = row["value"] if row else disp.POLICY_RECORD_ONLY
        if policy not in disp.POLICIES:
            raise ValueError(f"未知处置策略 {policy!r}；三选一：{', '.join(disp.POLICIES)}")

        diffs = batch_repo.list_diffs(conn, batch_id=batch_id, limit=100000)
        diffs.reverse()  # process in recorded order
        align_keys = pair["align_keys"]
        compare_fields = pair["compare_fields"]
        left_rows = _load_rows(pair["left_fixture"])
        right_rows = _load_rows(pair["right_fixture"])

        actions = disp.plan_disposition(
            diffs=diffs,
            left_rows=left_rows,
            right_rows=right_rows,
            align_keys=align_keys,
            policy=policy,
        )

        # --- apply to side storage (overwrite policies only) ---
        target_side = disp.TARGET_SIDE[policy]
        write_error: str | None = None
        if target_side and any(a["action"] == disp.ACTION_OVERWRITTEN for a in actions):
            target_fixture = (
                pair["right_fixture"] if target_side == "right" else pair["left_fixture"]
            )
            source_rows = right_rows if target_side == "right" else left_rows
            new_rows = disp.apply_actions(source_rows, actions, align_keys=align_keys)
            path = fixtures_dir() / target_fixture
            fixture_backup = (path, path.read_bytes())
            try:
                _write_rows_atomic(path, new_rows)
            except OSError as e:
                write_error = f"目标侧存储写入失败：{e}"
                # Nothing was durably written: planned overwrites become failures.
                for a in actions:
                    if a["action"] == disp.ACTION_OVERWRITTEN:
                        a["action"] = disp.ACTION_FAILED
                        a["reason"] = write_error

        # --- recount against fresh side storage (post-write truth) ---
        fresh_left = _load_rows(pair["left_fixture"])
        fresh_right = _load_rows(pair["right_fixture"])
        remaining = _remaining_mismatch(
            diffs,
            align_keys=align_keys,
            compare_fields=compare_fields,
            left_rows=fresh_left,
            right_rows=fresh_right,
        )
        pair_fm_now = compare_sides(
            fresh_left,
            fresh_right,
            align_keys=align_keys,
            compare_fields=compare_fields,
        )["counts"]["field_mismatch"]

        counts = _tally(actions)
        counts["remaining_mismatch"] = remaining
        status = _status_for(counts, write_error)

        now = _now()
        seq = disp_repo.count_runs(conn) + 1
        run_no = f"DR-{now[:10].replace('-', '')}-{seq:04d}"
        try:
            run_id = disp_repo.insert_run(
                conn,
                run_no=run_no,
                batch_id=batch_id,
                pair_id=pair["id"],
                policy=policy,
                failure_strategy=disp.FAILURE_STRATEGY,
                status=status,
                target_side=target_side,
                counts=counts,
                note=note,
                error=write_error,
                created_at=now,
            )
            for action in actions:
                disp_repo.insert_entry(conn, run_id=run_id, action=action, created_at=now)
            conn.commit()
        except Exception:
            conn.rollback()
            if fixture_backup is not None:
                # DB ledger failed after side storage was written: restore the
                # side so storage and ledger never diverge.
                path, raw = fixture_backup
                path.write_bytes(raw)
            raise
    finally:
        conn.close()

    return get_run(run_id) | {"pair_field_mismatch_now": pair_fm_now}


def _decorate(conn, run: dict[str, Any]) -> dict[str, Any]:
    batch = batch_repo.get_batch(conn, run["batch_id"])
    pair = pair_repo.get_pair(conn, run["pair_id"])
    run["batch_no"] = batch["batch_no"] if batch else None
    run["pair_code"] = pair["code"] if pair else None
    run["pair_title"] = pair["title"] if pair else None
    run["policy_label"] = disp.POLICY_LABELS[run["policy"]]
    run["failure_strategy_label"] = disp.FAILURE_STRATEGY_LABEL
    return run


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [_decorate(conn, r) for r in disp_repo.list_runs(conn, limit=limit)]
    finally:
        conn.close()


def get_run(run_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        run = disp_repo.get_run(conn, run_id)
        if not run:
            raise ValueError("disposition run not found")
        run = _decorate(conn, run)
        run["entries"] = disp_repo.list_entries(conn, run_id)
        return run
    finally:
        conn.close()
