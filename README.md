# 03-syncledger（双核对账）

Syncledger — 跨库/跨系统对齐对账：双端抽取 → 对齐键对账 → 差异处置 → 批次互证。

与 Feedstitch（多源 Feed 归并）、Batchgate（作业依赖编排）主链路不同。夹具全本地，不连活库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5300 |
| API | http://localhost:10300 |

## 主链

配置对账对与对齐键 → 触发双端抽取并对齐 → 落差异行与批次计数 → 选策略执行差异处置（盖写落侧数据并留痕）→ 页面互证

## 主从处置（已落地）

差异处置页可对任意对账批次执行处置，三种策略**互斥**，单次处置只生效一种：

| 策略 | 含义 | 侧数据 |
| --- | --- | --- |
| `left_wins` | 以左为准盖右 | 右侧工作夹具被改写 |
| `right_wins` | 以右为准盖左 | 左侧工作夹具被改写 |
| `record_only` | 只记账不盖写 | 两侧一字节不动 |

- **盖写必落侧存储**：选盖写时真实改写目标侧工作夹具（`DATA_DIR/fixtures/`，随卷持久化），逐键留痕 **键 / 字段 / 旧值 / 新值**（`disposition_entries`）。只改差异状态却不动侧数据的做法在本系统不存在——残留不一致数按处置后夹具现值重算。
- **失败策略固定一种，不混用**：保留已成功盖写、失败键单独留痕（含原因）、处置批记「部分成功」（`partial_success`）；不做整批回滚。全部成功记 `completed`，一键未成记 `failed`。
- **计数对账**：处置批的 成功 / 失败 / 跳过 / 记账 之和 = 批次差异行数；仍残留字段不一致数 = 字段不一致差异数 − 成功盖写键数，且与留痕条目逐条对应。
- **范围**：主从盖写只处理字段不一致（键级全有或全无）；单侧缺行（仅左有/仅右有）跳过留痕，不增删行。
- **幂等**：同批次同策略复跑，已一致的键记「跳过」，不重复盖写。
- 页面入口：差异处置页（配策略、选批次、执行、看全成功/部分失败明细与侧数据现状）；设置页可改默认策略；「恢复种子夹具」可重置演示。

## 种子对账对

- **inventory_hq_vs_store**：总部库存 ↔ 门店库存（`sku_id`+`store_id`，比对 `qty`/`unit`）。种子中门店侧 `SKU-200/S01` 行**缺 `unit` 字段**：`left_wins` 时补齐（全成功），`right_wins` 时该键因源侧缺字段整键失败（部分成功路径）。
- **payment_vs_ledger**：支付网关 ↔ 账务流水（`txn_id`，比对 `amount`/`currency`）
- **sku_catalog_a_vs_b**：目录 A ↔ 目录 B（`sku_code`，比对 `name`/`category`）

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 测试

```bash
cd backend && python -m pytest tests/
```

## 0-1 切口

已落地：`master_slave_pick`（三策略互斥）/ `diff_disposition_flow`（处置执行+留痕+计数对账）。
未实现（留表/入口待后题）：`side_only_policy`（单侧缺行增删）/ `window_buffer` / `batch_idempotency`（强幂等键）/ 契约闸 / 审计包导出。
