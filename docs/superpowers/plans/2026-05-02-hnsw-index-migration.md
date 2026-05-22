# ivfflat → HNSW 索引迁移计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `document_chunks.content_embedding` 的向量索引从 ivfflat(lists=100) 替换为 HNSW，解决数据量增长后召回率下降的问题。ivfflat 的召回依赖 probes 参数扫描聚类列表，5万 chunk 后精度明显下滑；HNSW 基于小世界图，召回率不随数据量退化。

**Architecture:** 纯数据库迁移 + 一行应用代码改动。查询 SQL 语法不变（`<=>` 距离算子 pgvector 自动路由到 HNSW 索引），仅替换索引类型和移除 ivfflat 专有的 `SET LOCAL ivfflat.probes` 会话参数。

**Tech Stack:** PostgreSQL 16 + pgvector, Alembic 迁移, SQLAlchemy async.

**Motivation:** 见 README "取舍"部分："ivfflat lists=100 入库快；过 5 万 chunk 后召回率掉，需要切 HNSW"。当前索引定义在迁移 `0001_init.py:82-83`，查询时 probes 设置在 `src/core/memory_service.py:293`。

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/db/migrations/versions/0006_ivfflat_to_hnsw.py` | Create | Alembic 迁移：删 ivfflat 索引、建 HNSW 索引 |
| `src/core/memory_service.py` | Modify | 删除 `SET LOCAL ivfflat.probes = 10`，替换为 `SET LOCAL hnsw.ef_search` |

---

## Conventions

- 每步有明确的 verify 标准才算完成
- 只动必须动的文件（Surgical Changes）
- 不加没人要求的配置项或抽象（Simplicity First）

---

## Task 1: 创建 Alembic 迁移 0006

**Files:**
- Create: `src/db/migrations/versions/0006_ivfflat_to_hnsw.py`

**决策说明：**

- **不用 `CONCURRENTLY`**：现有迁移 `0001_init.py` 的索引创建也是普通 `CREATE INDEX`，保持一致。当前数据量小（几千 chunk），锁表时间可忽略。如果未来数据量大需要在线迁移，另开迁移处理。
- **HNSW 参数硬编码**：`m=16`（每层最大连接数，精度与内存甜区）、`ef_construction=64`（构建时搜索宽度，越大索引越准但建得越慢）。不抽 config.yaml 配置——没人要求运行时可调（Simplicity First）。
- **downgrade 还原 ivfflat**：保留回退路径，虽然生产不会回退。

- [ ] **Step 1.1: 创建迁移文件**

创建 `src/db/migrations/versions/0006_ivfflat_to_hnsw.py`：

```python
"""ivfflat_to_hnsw

Revision ID: 0006_ivfflat_to_hnsw
Revises: 0005_user_auth
Create Date: 2026-05-02
"""
from alembic import op

revision = "0006_ivfflat_to_hnsw"
down_revision = "0005_user_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_document_chunks_embedding"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding ON document_chunks "
        "USING hnsw (content_embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_document_chunks_embedding"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding ON document_chunks "
        "USING ivfflat (content_embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
```

- [ ] **Step 1.2: verify — dry run 迁移不报错**

```bash
docker compose exec backend uv run alembic check
```

Expected: 无 pending migration 警告（如果 DB 已经跑过 0005），或 `alembic upgrade head` 成功执行。

- [ ] **Step 1.3: verify — 执行迁移后索引类型为 hnsw**

```bash
docker compose exec backend uv run alembic upgrade head
docker compose exec postgres psql -U postgres -d docqa -c \
  "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_document_chunks_embedding'"
```

Expected: 输出包含 `USING hnsw` 和 `m = 16, ef_construction = 64`。

---

## Task 2: 清除 memory_service 中的 ivfflat probes 设置

**Files:**
- Modify: `src/core/memory_service.py:289-293`

当前代码（`search_chunks` 方法内）：

```python
        # ivfflat default probes=1 only scans 1 of the 100 lists in our
        # index — for many queries the matching chunks live in other lists
        # and silently get 0 hits. probes≈sqrt(lists)=10 is the standard
        # accuracy/latency tradeoff. Without this, recall is very poor.
        await self.db.execute(text("SET LOCAL ivfflat.probes = 10"))
```

替换为 HNSW 的查询时搜索宽度参数。HNSW 默认 `ef_search=40`，对当前 top-k=16 的场景足够，但为了精度优先设为 100（搜索更宽，延迟增加微乎其微——向量为 1024 维，10 万级数据量下单次查询仍在毫秒级）。

- [ ] **Step 2.1: 替换 probes 为 ef_search**

将 `src/core/memory_service.py` 第 289-293 行的注释 + `SET LOCAL ivfflat.probes = 10` 替换为：

```python
        # HNSW ef_search controls how many graph nodes are examined during
        # query. Higher = better recall at marginal latency cost. Default
        # 40 is fine for top_k<=16; 100 gives headroom for edge cases.
        await self.db.execute(text("SET LOCAL hnsw.ef_search = 100"))
```

- [ ] **Step 2.2: verify — 代码中不再引用 ivfflat**

```bash
grep -rn "ivfflat" src/
```

Expected: 无输出（所有 ivfflat 引用已清除）。

- [ ] **Step 2.3: verify — 现有单元测试通过**

```bash
docker compose exec backend uv run pytest tests/unit/ -q
```

Expected: 全部通过（现有测试 mock 了 DB，不依赖索引类型；但如果 `search_chunks` 的单元测试实际执行了 SQL，确保 `SET LOCAL hnsw.ef_search` 不报错）。

---

## Task 3: 端到端验证

**Files:** 无代码改动

- [ ] **Step 3.1: 完整重建验证**

```bash
docker compose down -v
docker compose up -d
```

等待所有容器健康后：

1. 上传一份 PDF（如腾讯年报），等待解析完成
2. 提问事实类问题（"腾讯 2025 年总收入是多少？"）→ 验证返回正确答案 + 页码引用
3. 提问边界问题（"今天天气如何？"）→ 验证返回"未找到相关信息"

- [ ] **Step 3.2: verify — psql 确认索引确实是 HNSW**

```bash
docker compose exec postgres psql -U postgres -d docqa -c \
  "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_document_chunks_embedding'"
```

Expected: 包含 `USING hnsw`。

- [ ] **Step 3.3: verify — 查询日志中无 ivfflat 相关警告或错误**

```bash
docker compose logs backend --tail=50 | grep -i "ivfflat\|probes"
```

Expected: 无输出。

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| HNSW 索引构建时间比 ivfflat 长 | 当前数据量小，秒级完成；大规模时需评估 | V2 可考虑 `CONCURRENTLY` 在线建索引 |
| HNSW 索引内存占用比 ivfflat 多约 30% | 1024 维每 1000 chunk 约 +5MB，完全可接受 | 监控即可，不改方案 |
| `SET LOCAL hnsw.ef_search` 的 session 级设置可能与连接池交互 | `SET LOCAL` 在事务结束自动重置，与 asyncpg 的事务模型一致，无风险 | 无需额外处理 |

## 不在范围内（YAGNI）

- config.yaml 新增 HNSW 配置项（没人要求运行时可调）
- `CONCURRENTLY` 在线索引创建（当前数据量不需要）
- 应用层 HNSW 参数动态调整（hardcode 100 够用）
- 前端改动（纯后端基础设施变更）
