"""Master-slave disposition planning.

Three mutually exclusive policies — exactly one is in effect per run:

- ``left_wins``   以左为准盖右: overwrite the RIGHT side's mismatched fields with left values
- ``right_wins``  以右为准盖左: overwrite the LEFT side's mismatched fields with right values
- ``record_only`` 只记账不盖写: book the decision only; neither side may be modified

Mid-batch failure strategy — fixed to exactly one, never mixed:

- ``keep_successes_mark_partial``: keep successful overwrites, record failed
  keys individually in the ledger, and mark the run ``partial_success``.
  The alternative (roll back this run's successes and fail the whole run) is
  NOT used anywhere in the codebase.

Scope: field mismatches are overwritten field-by-field (all-or-nothing per
key). One-sided rows (left_only / right_only) are skipped with a trace — this
flow never inserts or deletes rows.
"""

from __future__ import annotations

import copy
from typing import Any

POLICY_LEFT_WINS = "left_wins"
POLICY_RIGHT_WINS = "right_wins"
POLICY_RECORD_ONLY = "record_only"
POLICIES = (POLICY_LEFT_WINS, POLICY_RIGHT_WINS, POLICY_RECORD_ONLY)

POLICY_LABELS = {
    POLICY_LEFT_WINS: "以左为准盖右",
    POLICY_RIGHT_WINS: "以右为准盖左",
    POLICY_RECORD_ONLY: "只记账不盖写",
}

# The one and only mid-batch failure strategy. Fixed server-side; not
# selectable per run, so the two strategies can never be mixed.
FAILURE_STRATEGY = "keep_successes_mark_partial"
FAILURE_STRATEGY_LABEL = "保留已成功盖写，失败键单独留痕，批次记部分成功（不做整批回滚）"

ACTION_OVERWRITTEN = "overwritten"
ACTION_FAILED = "failed"
ACTION_SKIPPED = "skipped"
ACTION_RECORDED = "recorded"

# Which side an overwrite policy writes to. record_only writes nowhere.
TARGET_SIDE = {
    POLICY_LEFT_WINS: "right",
    POLICY_RIGHT_WINS: "left",
    POLICY_RECORD_ONLY: None,
}

SIDE_LABELS = {"left": "左", "right": "右"}


def _key_tuple(row: dict[str, Any], align_keys: list[str]) -> tuple:
    return tuple(row.get(k) for k in align_keys)


def _index(rows: list[dict[str, Any]], align_keys: list[str]) -> dict[tuple, dict[str, Any]]:
    return {_key_tuple(r, align_keys): r for r in rows}


def plan_disposition(
    *,
    diffs: list[dict[str, Any]],
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    align_keys: list[str],
    policy: str,
) -> list[dict[str, Any]]:
    """Plan one action per diff row. Pure: reads current side rows, never mutates.

    Each action: {diff_id, align_key, kind, action, target_side, fields, reason}.
    ``fields`` items are {field, old_value, new_value} for overwrite attempts
    (old = target side's current value, new = source side's value) and
    {field, left_value, right_value} for record_only bookkeeping.
    """
    if policy not in POLICIES:
        raise ValueError(f"未知处置策略 {policy!r}；三选一：{', '.join(POLICIES)}")

    left_idx = _index(left_rows, align_keys)
    right_idx = _index(right_rows, align_keys)
    target_side = TARGET_SIDE[policy]

    actions: list[dict[str, Any]] = []
    for diff in diffs:
        align_key = diff["align_key"]
        kt = tuple(align_key.get(k) for k in align_keys)
        kind = diff["kind"]
        base = {
            "diff_id": diff.get("id"),
            "align_key": align_key,
            "kind": kind,
            "target_side": None,
            "fields": [],
            "reason": None,
        }

        if policy == POLICY_RECORD_ONLY:
            fields = []
            if kind == "field_mismatch":
                left = left_idx.get(kt) or {}
                right = right_idx.get(kt) or {}
                fields = [
                    {
                        "field": f,
                        "left_value": left.get(f),
                        "right_value": right.get(f),
                    }
                    for f in (diff.get("mismatched_fields") or [])
                ]
            actions.append({**base, "action": ACTION_RECORDED, "fields": fields})
            continue

        # Overwrite policies below; one-sided rows are never inserted/deleted.
        if kind in ("left_only", "right_only"):
            actions.append(
                {
                    **base,
                    "action": ACTION_SKIPPED,
                    "reason": "单侧缺行：主从盖写只处理字段不一致，不增删行",
                }
            )
            continue

        source_idx, target_idx = (
            (left_idx, right_idx) if policy == POLICY_LEFT_WINS else (right_idx, left_idx)
        )
        source_label = SIDE_LABELS["left" if policy == POLICY_LEFT_WINS else "right"]
        target_label = SIDE_LABELS[target_side]
        mismatched = list(diff.get("mismatched_fields") or [])
        source_row = source_idx.get(kt)
        target_row = target_idx.get(kt)

        if source_row is None:
            actions.append(
                {
                    **base,
                    "action": ACTION_FAILED,
                    "target_side": target_side,
                    "reason": f"源侧（{source_label}）当前缺少该键，无法取值盖写；请重新对账",
                }
            )
            continue
        if target_row is None:
            actions.append(
                {
                    **base,
                    "action": ACTION_FAILED,
                    "target_side": target_side,
                    "reason": f"目标侧（{target_label}）当前缺少该键，无法盖写；请重新对账",
                }
            )
            continue

        missing = [f for f in mismatched if f not in source_row]
        if missing:
            actions.append(
                {
                    **base,
                    "action": ACTION_FAILED,
                    "target_side": target_side,
                    "fields": [
                        {
                            "field": f,
                            "old_value": target_row.get(f),
                            "new_value": source_row.get(f),
                        }
                        for f in mismatched
                    ],
                    "reason": f"源侧（{source_label}）缺少字段 {', '.join(missing)}，整键拒绝盖写（防丢数据）",
                }
            )
            continue

        changes = [
            {"field": f, "old_value": target_row.get(f), "new_value": source_row[f]}
            for f in mismatched
            if target_row.get(f) != source_row[f]
        ]
        if not changes:
            actions.append(
                {
                    **base,
                    "action": ACTION_SKIPPED,
                    "reason": "目标侧已与源侧一致，无需盖写",
                }
            )
            continue
        actions.append(
            {
                **base,
                "action": ACTION_OVERWRITTEN,
                "target_side": target_side,
                "fields": changes,
            }
        )
    return actions


def apply_actions(
    rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    *,
    align_keys: list[str],
) -> list[dict[str, Any]]:
    """Return a new row list with every 'overwritten' action applied.

    Only the target side's rows are passed in; the other side is untouched.
    Input rows are not mutated.
    """
    new_rows = copy.deepcopy(rows)
    idx = _index(new_rows, align_keys)
    for action in actions:
        if action["action"] != ACTION_OVERWRITTEN:
            continue
        kt = tuple(action["align_key"].get(k) for k in align_keys)
        row = idx.get(kt)
        if row is None:  # planning already guaranteed presence; stay safe
            raise ValueError("目标侧键在落盘前消失，拒绝部分盖写")
        for change in action["fields"]:
            row[change["field"]] = change["new_value"]
    return new_rows
