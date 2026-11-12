"""Master-slave disposition: policy exclusivity, real side-storage writes,
fixed partial-failure strategy, and count/ledger reconciliation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import pair_id_by_code, reconcile

BACKEND = Path(__file__).resolve().parent.parent
SEED_DIR = BACKEND / "app" / "fixtures" / "seed"

INV = "inventory_hq_vs_store"


def read_working(env, name: str):
    return json.loads((env / "fixtures" / name).read_text(encoding="utf-8"))


def working_bytes(env, name: str) -> bytes:
    return (env / "fixtures" / name).read_bytes()


def seed_bytes(name: str) -> bytes:
    return (SEED_DIR / name).read_bytes()


def run_disp(client, batch_id: int, policy: str | None = None) -> dict:
    body = {"batch_id": batch_id}
    if policy is not None:
        body["policy"] = policy
    resp = client.post("/api/dispositions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_record_only_never_touches_either_side(client, env):
    batch = reconcile(client, INV)
    assert batch["field_mismatch"] == 2  # SKU-100 qty + SKU-200 unit(缺字段)
    before_left = working_bytes(env, "inventory_hq.json")
    before_right = working_bytes(env, "inventory_store.json")

    run = run_disp(client, batch["id"], "record_only")

    assert run["status"] == "completed"
    assert run["policy"] == "record_only"
    assert run["target_side"] is None
    assert run["applied"] == 0 and run["failed"] == 0 and run["skipped"] == 0
    assert run["recorded"] == run["examined"] == batch["diff_total"]
    assert run["remaining_mismatch"] == 2  # 只记账：不一致原样残留
    # 两侧夹具一字节未动
    assert working_bytes(env, "inventory_hq.json") == before_left
    assert working_bytes(env, "inventory_store.json") == before_right
    # 每键一条记账留痕，字段账带左右现值
    assert len(run["entries"]) == run["examined"]
    assert all(e["action"] == "recorded" for e in run["entries"])
    qty_entry = next(
        e for e in run["entries"]
        if e["kind"] == "field_mismatch" and e["align_key"] == {"sku_id": "SKU-100", "store_id": "S01"}
    )
    assert qty_entry["fields"] == [{"field": "qty", "left_value": 120, "right_value": 118}]


def test_left_wins_overwrites_right_and_counts_reconcile(client, env):
    batch = reconcile(client, INV)
    before_left = working_bytes(env, "inventory_hq.json")

    run = run_disp(client, batch["id"], "left_wins")

    assert run["status"] == "completed"  # 全成功路径
    assert run["target_side"] == "right"
    assert (run["applied"], run["failed"], run["skipped"], run["recorded"]) == (2, 0, 2, 0)
    assert run["fields_overwritten"] == 2
    assert run["remaining_mismatch"] == 0
    assert run["pair_field_mismatch_now"] == 0

    # 右侧夹具被真实改写：SKU-100 qty 118→120，SKU-200 补上 unit
    right = { (r["sku_id"], r["store_id"]): r for r in read_working(env, "inventory_store.json") }
    assert right[("SKU-100", "S01")]["qty"] == 120
    assert right[("SKU-200", "S01")]["unit"] == "pcs"
    # 左侧夹具未动
    assert working_bytes(env, "inventory_hq.json") == before_left

    # 留痕：键 / 字段 / 旧值 / 新值
    written = [e for e in run["entries"] if e["action"] == "overwritten"]
    assert len(written) == run["applied"]
    by_key = {tuple(sorted(e["align_key"].items())): e for e in written}
    sku100 = by_key[(("sku_id", "SKU-100"), ("store_id", "S01"))]
    assert sku100["target_side"] == "right"
    assert sku100["fields"] == [{"field": "qty", "old_value": 118, "new_value": 120}]
    sku200 = by_key[(("sku_id", "SKU-200"), ("store_id", "S01"))]
    assert sku200["fields"] == [{"field": "unit", "old_value": None, "new_value": "pcs"}]
    # 跳过的是两条单侧缺行
    skipped = [e for e in run["entries"] if e["action"] == "skipped"]
    assert {e["kind"] for e in skipped} == {"left_only", "right_only"}
    assert all("不增删行" in e["reason"] for e in skipped)

    # 复跑对账：字段不一致真的清零（侧数据已更新，不是改状态）
    again = reconcile(client, INV)
    assert again["field_mismatch"] == 0
    assert again["matched"] == 3
    assert again["diff_total"] == 2  # 两条单侧缺行仍在


def test_right_wins_partial_failure_keeps_successes(client, env):
    batch = reconcile(client, INV)

    run = run_disp(client, batch["id"], "right_wins")

    # 部分成功路径：SKU-100 盖左成功，SKU-200 因源侧缺 unit 整键失败
    assert run["status"] == "partial_success"
    assert run["target_side"] == "left"
    assert (run["applied"], run["failed"], run["skipped"], run["recorded"]) == (1, 1, 2, 0)
    assert run["failure_strategy"] == "keep_successes_mark_partial"
    assert run["remaining_mismatch"] == 1  # 与差异列表及留痕对得上：2 条字段差 − 1 键成功

    # 成功键保留（不回滚）：左侧 SKU-100 qty 120→118
    left = { (r["sku_id"], r["store_id"]): r for r in read_working(env, "inventory_hq.json") }
    assert left[("SKU-100", "S01")]["qty"] == 118
    # 失败键原样：左侧 SKU-200 仍是 qty=45/unit=pcs，右侧仍缺 unit
    assert left[("SKU-200", "S01")]["qty"] == 45
    assert left[("SKU-200", "S01")]["unit"] == "pcs"
    right = { (r["sku_id"], r["store_id"]): r for r in read_working(env, "inventory_store.json") }
    assert "unit" not in right[("SKU-200", "S01")]

    # 失败键单独留痕，带原因与未遂字段账
    failed = [e for e in run["entries"] if e["action"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["align_key"] == {"sku_id": "SKU-200", "store_id": "S01"}
    assert failed[0]["target_side"] == "left"
    assert "源侧" in failed[0]["reason"] and "unit" in failed[0]["reason"]
    assert failed[0]["fields"] == [{"field": "unit", "old_value": "pcs", "new_value": None}]

    # 复跑对账：残留与留痕一致 —— 只剩 SKU-200 的 unit 不一致
    again = reconcile(client, INV)
    assert again["field_mismatch"] == 1
    assert again["diff_total"] == 3


def test_counts_always_reconcile_with_ledger(client, env):
    batch = reconcile(client, INV)
    for policy in ("record_only", "left_wins"):
        run = run_disp(client, batch["id"], policy)
        entries = run["entries"]
        assert run["examined"] == len(entries) == batch["diff_total"]
        assert run["applied"] + run["failed"] + run["skipped"] + run["recorded"] == run["examined"]
        assert run["applied"] == sum(1 for e in entries if e["action"] == "overwritten")
        assert run["failed"] == sum(1 for e in entries if e["action"] == "failed")
        assert run["skipped"] == sum(1 for e in entries if e["action"] == "skipped")
        assert run["recorded"] == sum(1 for e in entries if e["action"] == "recorded")
        assert run["fields_overwritten"] == sum(
            len(e["fields"]) for e in entries if e["action"] == "overwritten"
        )
        fm_diffs = sum(1 for e in entries if e["kind"] == "field_mismatch")
        assert run["remaining_mismatch"] == fm_diffs - run["applied"]


def test_one_run_never_writes_both_sides(client, env):
    batch = reconcile(client, INV)
    for policy, side in (("left_wins", "right"), ("right_wins", "left")):
        run = run_disp(client, batch["id"], policy)
        written_sides = {
            e["target_side"] for e in run["entries"] if e["action"] in ("overwritten", "failed")
        }
        assert written_sides <= {side}  # 同一键绝不会既盖左又盖右
        keys = [json.dumps(e["align_key"], sort_keys=True) for e in run["entries"]]
        assert len(keys) == len(set(keys))  # 每键在本批处置中只出现一次
        # 复位再跑下一个策略
        assert client.post("/api/fixtures/reset").status_code == 200


def test_rerun_same_policy_is_idempotent_skip(client, env):
    batch = reconcile(client, INV)
    first = run_disp(client, batch["id"], "left_wins")
    assert first["applied"] == 2
    second = run_disp(client, batch["id"], "left_wins")
    assert second["status"] == "completed"
    assert second["applied"] == 0
    assert second["skipped"] == second["examined"] == 4
    assert second["remaining_mismatch"] == 0
    reasons = {e["reason"] for e in second["entries"] if e["kind"] == "field_mismatch"}
    assert reasons == {"目标侧已与源侧一致，无需盖写"}


def test_invalid_policy_and_missing_batch_rejected(client):
    batch = reconcile(client, INV)
    resp = client.post("/api/dispositions", json={"batch_id": batch["id"], "policy": "both_sides"})
    assert resp.status_code == 400
    resp = client.post("/api/dispositions", json={"batch_id": 9999, "policy": "left_wins"})
    assert resp.status_code == 400


def test_default_policy_from_settings_and_put_validation(client):
    assert client.get("/api/settings").json()["default_policy"] == "record_only"
    resp = client.put("/api/settings", json={"key": "default_policy", "value": "left_wins"})
    assert resp.status_code == 200
    assert resp.json()["default_policy"] == "left_wins"

    batch = reconcile(client, INV)
    run = run_disp(client, batch["id"])  # 不传策略 → 用默认
    assert run["policy"] == "left_wins"
    assert run["applied"] == 2

    assert client.put(
        "/api/settings", json={"key": "default_policy", "value": "both"}
    ).status_code == 400
    assert client.put(
        "/api/settings", json={"key": "auto_overwrite", "value": "true"}
    ).status_code == 400


def test_reset_fixtures_restores_seed_bytes(client, env):
    batch = reconcile(client, INV)
    run_disp(client, batch["id"], "left_wins")
    assert working_bytes(env, "inventory_store.json") != seed_bytes("inventory_store.json")

    resp = client.post("/api/fixtures/reset")
    assert resp.status_code == 200
    assert set(resp.json()["restored"]) == {
        "inventory_hq.json", "inventory_store.json", "payment_gateway.json",
        "payment_ledger.json", "sku_catalog_a.json", "sku_catalog_b.json",
    }
    for name in resp.json()["restored"]:
        assert working_bytes(env, name) == seed_bytes(name)


def test_ledger_db_failure_rolls_back_side_write(client, env, monkeypatch):
    """侧存储已写、留痕落库失败 → 恢复侧存储，两边绝不各说各话。"""
    batch = reconcile(client, INV)
    before = working_bytes(env, "inventory_store.json")

    import app.repositories.dispositions as repo

    def boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "insert_run", boom)
    with pytest.raises(Exception):
        client.post("/api/dispositions", json={"batch_id": batch["id"], "policy": "left_wins"})

    assert working_bytes(env, "inventory_store.json") == before  # 侧数据被恢复
    assert client.get("/api/dispositions").json() == []  # 无半截留痕


def test_pair_sides_endpoint_shows_raw_storage(client):
    batch = reconcile(client, INV)
    run_disp(client, batch["id"], "left_wins")
    pid = pair_id_by_code(client, INV)
    sides = client.get(f"/api/pairs/{pid}/sides").json()
    sku100 = next(
        r for r in sides["right_rows"] if r["sku_id"] == "SKU-100" and r["store_id"] == "S01"
    )
    assert sku100["qty"] == 120  # 侧存储现状接口直接可见盖写结果


def test_dashboard_surfaces_disposition_state(client):
    batch = reconcile(client, INV)
    run_disp(client, batch["id"], "right_wins")
    stats = client.get("/api/dashboard").json()
    assert stats["disposition_runs"] == 1
    assert stats["last_disposition"]["status"] == "partial_success"
    assert stats["last_disposition"]["remaining_mismatch"] == 1
