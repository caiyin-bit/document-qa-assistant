# Ingestion Worker — 设计文档

**Date:** 2026-04-26
**Branch:** `fix/ingestion-race-and-progress` → 新分支待开
**Status:** Draft for review

## 1. 背景与目标

### 1.1 背景

当前文档解析（PDF 文本抽取 + BGE 向量化 + pgvector 写入）跑在 backend FastAPI 进程内，通过 `asyncio.create_task(_run_ingestion(...))` 启动。本会话定位过三个相关 bug：

1. `create_task` 弱引用导致任务被 GC（已修）
2. `wait_for` 超时取消使 SQLAlchemy session 进入 invalid 事务态，清理路径自爆（已修）
3. SSE 复用同一 session 拿到 identity-map 缓存的旧实例，进度永远显示 0（已修）

但**架构层面的根因仍在**：

- BGE `encode` 是同步 CPU 计算（PyTorch），跑在 event loop 里 → chat 请求在 ingestion 期间被饿死
- ingestion 任务跟 backend 进程绑死 → uvicorn `--reload` 一次代码改动就杀掉所有在跑的 task
- backend 任何崩溃都会丢任务；只有启动钩子 `cleanup_stale_documents` 把它们标 `failed`，没有重试

### 1.2 目标

- **解耦**：ingestion 在独立 worker 进程跑，backend event loop 与 chat 不再被 BGE 阻塞
- **持久**：worker / backend 任一进程崩溃后，未完成的 ingestion 自动恢复重跑
- **实时**：前端的进度反馈延迟保持在 1s 以内（沿用现有 SSE+DB 轮询）

### 1.3 非目标

- 横向扩展（短期单 worker 足够）
- 分布式编排
- 断点续跑（崩溃后整体 idempotent 重跑，不做"从 page 110 续"）

---

## 2. 架构

```
┌─────────────────┐    enqueue_job        ┌────────────┐
│    backend      │ ────────────────────▶ │   redis    │
│   (FastAPI)     │                       │  (broker)  │
│                 │                       └─────┬──────┘
│ - upload API    │                             │ BRPOP
│ - chat API      │                             ▼
│ - SSE progress  │                       ┌────────────┐
│ - BGE (query)   │   write progress      │   worker   │
│                 │ ◀──────────────────── │   (Arq)    │
└────────┬────────┘                       │            │
         │                                │ - ingest   │
         │   read progress (poll/expire)  │ - BGE      │
         ▼                                │ - chunker  │
┌─────────────────┐                       └─────┬──────┘
│    postgres     │ ◀── INSERT chunks ──────────┘
│   (pgvector)    │
└─────────────────┘
```

三个长期容器（已有 + 新增）：

| 容器 | 角色 | 是否新增 |
|---|---|---|
| `postgres` | 业务数据 + 向量 | 已有 |
| `backend` | HTTP API、SSE、chat 推理、enqueue | 已有，需改造 |
| `worker` | 文档 ingestion job runner | **新增** |
| `redis` | Arq broker | **新增** |

---

## 3. 组件细化

### 3.1 Backend（修改）

**移除**：

- `src/api/documents.py:_run_ingestion`
- `src/api/documents.py:_INGESTION_TASKS`
- `asyncio.create_task(...)` 调用

**新增**：

- 启动时持有一个 `arq.connections.RedisSettings` + `pool`（lifespan 管理）
- 上传成功后：`await arq_pool.enqueue_job("ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}")`
  - timeout 不在这里传，统一由 `arq.worker.func(..., timeout=1800)` 在 worker 端配置（见 §3.2）
- `cleanup_stale_documents` → 重命名为 `reenqueue_processing_documents`，行为：仅 enqueue + `_job_id` 去重，不动 chunks 不动状态（见 §5.3）

**保留**：

- BGE embedder 单实例（chat query embedding 仍由 backend 负责），但**所有调用必须走 `*_async` 方法**，复用 `BgeEmbedder` 内置的 single-thread executor（详见 §3.5）。直接 `embed_batch / encode_one` 这类同步入口在本次重构后视为内部使用，不该再被 await 它的 callsite 调到
- `/sessions/{sid}/documents/{did}/progress` SSE（Bug ① 修复后已正常）

### 3.2 Worker（新增）

**目录**：`src/worker/`

```
src/worker/
  __init__.py
  main.py            # WorkerSettings + on_startup
  jobs.py            # ingest_document(ctx, doc_id_str) -> None
```

**入口**（docker-compose `command`）：

```
uv run arq src.worker.main.WorkerSettings
```

**WorkerSettings**（per-function timeout/retry 通过 `arq.worker.func(...)` 注册）：

```python
from arq.worker import func

# Single source of truth for retry policy. Don't redefine in the wrapper.
INGEST_MAX_TRIES = 2
INGEST_TIMEOUT = 1800

class WorkerSettings:
    functions = [
        func(ingest_document, name="ingest_document",
             timeout=INGEST_TIMEOUT, max_tries=INGEST_MAX_TRIES),
    ]
    redis_settings = RedisSettings.from_dsn(os.environ["REDIS_URL"])
    on_startup = _on_startup     # 预热 BGE、建 engine、attach 进 ctx
    on_shutdown = _on_shutdown   # 关 engine + embedder.close()（§3.5）
    max_jobs = 1                 # 单机单 worker，不并发解析（避免内存翻倍）
    keep_result = 60
```

> ⚠️ Arq 0.28 实测：`enqueue_job` **不**接受 `_job_timeout` kwarg，会被当成业务参数传进 `ingest_document`，引发 `TypeError`。timeout 必须放在 `func(..., timeout=...)` 或 `WorkerSettings.job_timeout`（全局默认）。

**job 函数**：

```python
async def ingest_document(ctx, doc_id_str: str) -> None:
    """Idempotent ingestion job. Step 1 wipes any partial state from a
    previous crashed try; subsequent steps run the full pipeline."""
    doc_id = UUID(doc_id_str)
    sm: async_sessionmaker = ctx["sessionmaker"]
    embedder: BgeEmbedder = ctx["embedder"]
    job_try = ctx.get("job_try", 1)

    # Reset doc + drop partial chunks. Safe because deterministic _job_id
    # (see §4.1) means at most one ingest_document for this doc_id is in
    # flight at a time. Done in its own session so its commit lands
    # before the long encode loop starts.
    async with sm() as db:
        mem = MemoryService(db)
        await mem.delete_chunks_for_document(doc_id)
        await mem.update_document(
            doc_id, status=DocumentStatus.processing,
            progress_page=0, progress_phase=None, error_message=None,
        )

    # CRITICAL ordering (review-4 命中): the try/except wraps the *whole*
    # `async with sm()` block, NOT a try inside it. Why: when CancelledError
    # fires mid-bulk_insert_chunks, the `db` session has a pending statement.
    # If the except handler ran inside the same `async with`, opening a
    # fresh session for mark-failed would race with the original session's
    # __aexit__ (which itself does rollback/close). The fresh session's
    # delete could land before the original's commit unwound, leaving
    # phantom chunks under a "failed" doc.
    #
    # By wrapping the `async with` in try/except, the original session
    # has already executed __aexit__ (rollback + close) by the time we
    # enter the handler — no race.
    try:
        async with sm() as db:
            mem = MemoryService(db)
            await _ingest_document(
                doc_id, path=UPLOADS_DIR / f"{doc_id}.pdf",
                mem=mem, embedder=embedder,
                iter_pages=iter_pages, chunker=chunk,
            )
    except asyncio.CancelledError:
        # Arq job_timeout / worker shutdown / SIGTERM all surface here.
        # `except Exception` in _ingest_document does NOT catch this
        # (CancelledError is BaseException on 3.11+).
        #
        # On the LAST try, open a fresh session to mark failed so the
        # user is unblocked instead of staring at "processing" forever
        # (delete is also blocked while processing — see §5.5). Wrapped
        # in shield+wait_for so the mark-failed write either completes
        # quickly or gives up before the outer CancelledError tears the
        # task down.
        if job_try >= INGEST_MAX_TRIES:
            async def _final_mark_failed():
                async with sm() as fresh:
                    fmem = MemoryService(fresh)
                    await _mark_failed_and_clean(
                        doc_id, "解析多次超时/中断，请删除后重试",
                        mem=fmem,
                    )
            try:
                await asyncio.shield(asyncio.wait_for(
                    _final_mark_failed(), timeout=5.0))
            except Exception:
                log.warning("final mark-failed for %s also failed", doc_id)
        raise
```

注意：worker job **不再用 `_ingest_with_timeout`** — `arq.worker.func(timeout=...)` 已经在外层做了 cancellation。

**异常分类**（与 §5.1 / §5.2 对齐）：

- `_ingest_document` 在本次重构中 **收紧 except 范围**：只捕获**业务不可恢复**异常（`PdfValidationError`、空文本检测、内容明显损坏）→ 标 `failed` 后正常返回，job 视为完成、Arq 不重试
- 基础设施类异常（`OperationalError`、`DBAPIError`、`asyncio.TimeoutError` from network、`OSError`、`asyncpg.PostgresConnectionError`）**不再被吞**，直接传递给 Arq → 计入 `job_try` → 在 `max_tries` 内重试
- `asyncio.CancelledError` 走上面的 last-try mark-failed 路径

> ⚠️ **取消粒度限制**（reviewer 命中）：`embedder.embed_batch` 是同步 PyTorch 调用，event loop 卡在它里面时 Arq 没法注入 `CancelledError`。本设计要求让 BGE encode 走 `BgeEmbedder` 内部专用的 single-thread executor（见 §3.5），event loop 解放出来，取消粒度是"每个 batch 之间"。单 batch 不可中断这一点 V1 接受；用 subprocess 隔离是 V2 课题。

### 3.5 BGE encode 必须包进 thread + **每进程串行化**

`_ingest_document` 中的 `embedder.embed_batch(contents)` 必须从 event-loop 直接 await 同步调用改成：

```python
embeddings = await embedder.embed_batch_async(contents)  # see below
```

`BgeEmbedder` 内部持有一个**专用 single-thread executor**，并暴露显式 `close()`：

```python
class BgeEmbedder:
    def __init__(self, ...):
        # max_workers=1 强制串行：torch intra-op 默认 6 线程，并发 encode
        # 同一 model 既有数据竞争风险（dropout / quantization 内部 buffer），
        # 也会让 CPU 互相打架——单线程把每次调用排队，反而总吞吐更高。
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge")

    async def embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.embed_batch, texts)

    async def encode_one_async(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.encode_one, text)

    def close(self, *, wait: bool = False) -> None:
        """Shutdown the executor.

        cancel_futures=True drops queued-but-not-started encodes. The
        currently-running batch (if any) finishes naturally — torch can't
        be interrupted mid-tensor-op.

        wait=False (default): return immediately. The bg thread keeps
            running until the in-flight batch is done; process exit
            won't be blocked by the embedder itself but will wait for
            the non-daemon thread to finish.
        wait=True: block until in-flight finishes. Use only where you
            need the executor verifiably drained (tests).
        """
        self._executor.shutdown(wait=wait, cancel_futures=True)
```

**Lifecycle wiring**（review-4/5 命中：避免线程泄漏 + shutdown 不被卡住）：

| 进程 | 创建 | 销毁 | wait 语义 |
|---|---|---|---|
| backend | `_production_deps()` 已创建 BGE singleton | FastAPI lifespan `on_event("shutdown")` 调 `embedder.close(wait=False)` | **不等**正在跑的 encode；uvicorn reload 不被拖。in-flight batch 在后台线程自然结束，正常情况几百毫秒；最坏情况（异常长 batch）会延后进程真正退出，但**不阻塞 shutdown 调用本身** |
| worker | `WorkerSettings.on_startup` 创建 → 写入 `ctx["embedder"]` | `WorkerSettings.on_shutdown` 调 `embedder.close(wait=False)`；同时 Arq 的 `job_completion_wait`（默认无限）配合 docker compose `stop_grace_period` 决定整体上限 | **不等** encode；docker stop 给的 grace period（默认 10s）耗尽后容器被 SIGKILL，剩余 in-flight encode 被强杀。这是接受的：worker job 是幂等的，下次启动 reaper 重投，第一步幂等清理 |
| 单测 | fixture 创建 fake/真实 embedder | fixture teardown 调 `embedder.close(wait=True)` | **等**线程退出，避免 pytest 进程退出时孤儿线程；fake embedder 几乎瞬时返回，wait 不构成问题 |

> 设计权衡（review-5 命中）：编排端的 stop grace period（uvicorn `--graceful-timeout` / docker `stop_grace_period`）才是 shutdown 的真正预算；BGE 自己只负责"不主动延长"，由编排端的强杀兜底"不被无限拖"。

要点（review-2 命中）：

1. **不能用 `asyncio.to_thread`**（它走默认 executor，并发请求会同时进多线程跑同一个 SentenceTransformer）
2. **每进程一个 executor**：backend 进程用 backend 那个 BgeEmbedder 单实例；worker 进程用 worker 自己的实例。两进程互不影响（决策 2-a：各自加载）
3. **取消可达**：executor 内部跑同步代码时无法响应 cancel，但调用方 `await run_in_executor(...)` 是 await 点；cancel 在该 await 处生效，下一个 batch 不会再启动
4. **backend chat 路径同步改造**：`/chat` 中 user query 嵌入改用 `await embedder.encode_one_async(query)`。否则一个长 chat 还是会在 BGE encode 时阻塞别的 chat 请求

> ⚠️ 范围说明：backend 端的 `encode_one_async` 改造是为本次设计目标"chat 不被卡顿"必需，**包含在本 spec 内**。如果你想严格按 worker 拆分边界、把 chat 那个改动剥到独立 PR，唯一前提是接受改造完成前 backend chat 仍会被 query embedding 短暂阻塞（10-50ms 量级，可接受过渡期）。

代价：每次 encode 多一次 await + thread hop（~微秒），相对 encode 耗时（~百毫秒/batch）忽略不计。

### 3.3 Redis（新增）

仅作 Arq broker，不做缓存、不做 pub/sub。无持久化要求 —— 所有 job 都能从 `documents.status='processing'` 重建。

```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 3s
    timeout: 3s
    retries: 10
```

### 3.4 Schema

**无 migration 需要**。所有状态字段已经在 `documents` 表里：

- `status`（processing | ready | failed）
- `progress_page`、`progress_phase`
- `error_message`
- `ingestion_started_at`

---

## 4. 数据流

### 4.1 上传 → 入队

严格保持当前 endpoint 的落盘顺序，**只在 enqueue 一步替换 `asyncio.create_task`**：

1. 用户 `POST /sessions/{sid}/documents`（multipart PDF）
2. Backend 校验扩展名/大小、写 temp 文件、验证 PDF metadata
3. INSERT `documents` 行 (`status=processing, progress_page=0`)
4. **atomic rename** `temp/{doc_id}.pdf → uploads/{doc_id}.pdf`（保证 worker 看见的就是完整文件）
5. `await arq_pool.enqueue_job("ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}")`
   - `_job_id` 决定性 → backend 启动 reaper 重投同一 doc 时 Arq 自动去重，不会在 worker 还在跑时塞进第二条
   - 失败：catch `RedisError`，把 doc 标 `failed`（error_message="任务队列不可达"）+ 删 disk 文件，返回 503
6. 返回 200 给前端

> ⚠️ 步骤 3 与 5 不在同一事务里。极端情况（步骤 5 之前进程被杀）下 DB 行存在但 job 未入队，靠 §5.3 backend 启动时 reaper 兜底再 enqueue。

### 4.2 Worker 消费

1. Worker 通过 BRPOP 从 Redis 拿到 job
2. **预检 PDF 文件存在**（review-5 命中，§4.1 步骤 3 与 4 之间崩溃的兜底）：
   ```python
   path = UPLOADS_DIR / f"{doc_id}.pdf"
   if not path.is_file():
       await mem.update_document(doc_id, status=DocumentStatus.failed,
           error_message="上传文件未落盘，请删除后重新上传", progress_phase=None)
       return  # 业务异常 → 不 retry
   ```
3. （job 内部首步）清掉该 doc 任何残留 chunks，重置 `progress_*` 字段 → 保证 retry idempotent
4. 调用 `_ingest_document` 走原流程：逐页 extract → **`embedder.embed_batch_async(...)`** → bulk insert chunks，每个阶段写 `progress_phase`
5. 成功：`status=ready, progress_phase=NULL`
6. 失败（捕获到的业务异常）：`_mark_failed_and_clean` 写 `status=failed`；基础设施异常 raise 给 Arq retry（§5.1）
7. **崩溃**：进程死亡，job 留在 Redis "in-progress" 状态。Arq `max_tries=2` 在 worker 重启后自动重试

> ⚠️ **同步 vs async embedder API**（review-5 命中）：本设计后，`_ingest_document` 内部所有 BGE 调用必须走 `embed_batch_async / encode_one_async`。同步 `embed_batch / encode_one / embed` 入口仍存在但视为 internal helper，**不允许**在 async 调用栈中直接 await（会重新阻塞 event loop）。§7.1 加单测覆盖：grep `_ingest_document` 与 `src/api/chat.py` / `src/tools/search_documents.py`，断言不出现裸 `embedder.embed_batch(`、`embedder.encode_one(`、`embedder.embed(` 调用。

### 4.3 进度反馈（不变）

frontend SSE → backend `/progress` → DB poll（with `db.expire_all()`） → yield 事件。

---

## 5. 错误处理与恢复

### 5.1 异常分类：业务 vs 基础设施

`_ingest_document` 收紧 `except` 范围（本次重构内必做项）：

| 异常类 | 处理 | Arq 行为 |
|---|---|---|
| **业务不可恢复**：`PdfValidationError`、`total_chunks==0`（扫描版/纯图）| `_mark_failed_and_clean` → 写 `failed` + error_message → return | job 成功完成，**不**重试 |
| **基础设施瞬时错**：`OperationalError`、`DBAPIError`、`asyncpg.*ConnectionError`、`OSError`、网络相关 `asyncio.TimeoutError` | **不捕获**，直接 raise | Arq 计入 `job_try`，`max_tries` 内重试；下次重试时 job 第一步重置 |
| `CancelledError` | 见 §5.2 | 见 §5.2 |
| 其他未预期 `Exception` | **不捕获**，直接 raise（保守起见也走 retry）| Arq retry |

> 这是相对当前实现的 **行为变更**：现状是 `except Exception` 全收 → 单次 DB 闪断永久失败。重构后瞬时错可恢复。

### 5.2 Worker 进程崩溃 / shutdown / job timeout

- Arq lease key + worker heartbeat 检测 worker 死亡 → lease 过期后重投
- `arq.worker.func(timeout=1800)` 触发 → cancel job → §3.2 的 `except asyncio.CancelledError` 处理：
  - **非最后一次 try**：不动 DB，re-raise；Arq 计数 + 重投；下次的 step-1 自动清理 partial chunks
  - **最后一次 try**（`job_try >= max_tries`）：在新 session + `asyncio.shield + wait_for(5s)` 里把 doc 标 `failed`（"解析多次超时/中断..."），让用户能解锁删除
- 取消时**不复用**当前 session — connection 可能正在 query 中，复用容易 hang；postgres 端无效事务随 worker 进程退出自然回滚

### 5.3 Backend 重启（worker 可能仍在跑）

> ⚠️ Round-1 review 命中：这里早期设计是无条件 `delete_chunks_for_document + enqueue`，会从仍在跑的 worker 脚下抽 chunks。修正后行为：

```python
# cleanup_stale_documents（重命名为 reenqueue_processing_documents 更贴切）
for doc in docs_with_status_processing:
    await arq_pool.enqueue_job(
        "ingest_document", str(doc.id),
        _job_id=f"ingest:{doc.id}",
    )
```

- **不删 chunks**、**不动 doc 状态**
- `_job_id` 是关键：Arq 按 id 去重，如果 worker 当前正抓着这个 job（in-progress）或队列里已有同 id pending，enqueue 是 no-op；否则才真投
- 真正的状态重置由 worker job 自己第一步做（§3.2），那时 worker 已经独占这条 job，不存在并发 worker 的同时清理
- 等价于"Reaper 只补 enqueue，清理由 worker 真正开始时做"

### 5.3.1 Redis 完全丢失

- Redis 容器无持久化 → 所有未完成 job 全丢、`_job_id` 元数据也丢
- Backend 启动 reaper 用 `_job_id=f"ingest:{doc.id}"` enqueue 全部 `processing` doc → 真投（无去重对象）
- worker 起来后逐条消费、第一步幂等清理 → 重头跑

### 5.4 Redis 不可达（上传时）

按 §4.1 步骤 5 处理：捕获 RedisError、标 doc 为 failed、删 disk 文件、返回 503。用户删除前端那条失败 row 重传即可。

### 5.5 Worker 容器一直起不来

- DB 里 doc 永远卡在 `processing`
- 现状：用户体感跟当前一样卡死。Reaper 不能再做更多
- 监控/告警是后续课题，超出本设计

---

## 6. 配置与依赖

### 6.1 新依赖

`pyproject.toml`：

```toml
dependencies = [
  ...,
  "arq>=0.26",
  "redis>=5.0",  # arq 间接依赖，显式锁版本以防漂移
]
```

### 6.2 环境变量

- `REDIS_URL`（默认 `redis://redis:6379/0`）

### 6.3 docker-compose

新增两个 service：

```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped

worker:
  build: .
  command: sh -c "uv run arq src.worker.main.WorkerSettings"
  environment:
    DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/docqa
    REDIS_URL: redis://redis:6379/0
    HF_HOME: /root/.cache/huggingface
  volumes:
    - ./src:/app/src
    - ./config.yaml:/app/config.yaml
    - ./data/uploads:/app/data/uploads
    - ${HOME}/.cache/huggingface:/root/.cache/huggingface
  depends_on:
    postgres: { condition: service_healthy }
    redis: { condition: service_healthy }

backend:
  ...（已有，新增）
  environment:
    ...
    REDIS_URL: redis://redis:6379/0
  depends_on:
    postgres: { condition: service_healthy }
    redis: { condition: service_healthy }   # 新增
```

> Worker 与 backend 共用同一个镜像（同一个 Dockerfile），运行命令不同。HF cache bind-mount 让两个容器共享已下载的 BGE 权重，无需各自下载。**但运行时各自加载到自己的进程内存**（决策 2-a）。

---

## 7. 测试策略

### 7.1 单元

- 现有 `tests/unit/test_ingestion_*.py` 不变，覆盖 `_ingest_document` 的 happy path 与 error path
- 新增 `tests/unit/test_worker_jobs.py`：用 fake ctx 调 `ingest_document(ctx, doc_id_str)`，断言数据库终态正确，含：
  - happy path → status=ready
  - 业务异常（PdfValidationError / total_chunks==0）→ status=failed，job 正常返回
  - 基础设施异常（mock OperationalError）→ 不动 DB、re-raise（让 Arq retry）
  - **第一步幂等清理**：先注入残留 chunks，断言 job 跑完后只剩本次 run 的 chunks
  - **CancelledError 非最后一次 try**（`ctx['job_try']=1`）：job 第二步 mock 抛 cancel，断言函数 re-raise、DB **不**被动到（doc 仍 `processing`、chunks 保留至下一次重试 step-1 清理）
  - **CancelledError 最后一次 try**（`ctx['job_try']=INGEST_MAX_TRIES`）：cancel 抛出后，断言：
    - doc 被 fresh session 标 `failed`、error_message 写入
    - **partial chunks 已被清掉**（`SELECT count(*) FROM document_chunks WHERE document_id=? = 0`，review-5 命中：last-try cleanup 的核心目标）
    - DELETE API 现在不再 409
  - **MAX_TRIES 常量未漂移**（review-3 命中）：导入 `INGEST_MAX_TRIES`，断言 `WorkerSettings.functions[0].max_tries == INGEST_MAX_TRIES`，避免后续手改一处忘改另一处
  - **CancelledError handler 在 `async with` 外层**（review-4 命中）：用一个能感知 enter/exit 的 fake session，断言原 session 已 `__aexit__` 完成才进入 except；fresh session 的写入发生在原 session 关闭之后
  - **BgeEmbedder.close() 关线程**（review-4 命中）：构造 embedder、提交一次 encode、调 `close(wait=True)`、断言 `_executor._threads` 都已退出（无线程泄漏）；同时 `close(wait=False)` 立即返回但后台线程继续完成（用 mock embed 函数延迟 0.5s 验证）
  - **缺失 PDF 文件**（review-5 命中）：upload 路径下不创建 PDF，直接 enqueue 调 `ingest_document`，断言 doc 被标 `failed` 且 error_message 含"未落盘"，**不**触发 Arq retry（job 正常返回）
  - **async embedder API 不被绕过**（review-5 命中）：grep `src/ingest/ingestion.py`、`src/api/chat.py`、`src/tools/search_documents.py`，断言无裸 `\.embed_batch\(`、`\.encode_one\(`、`\.embed\(` 调用

### 7.2 集成

`tests/integration/test_worker_e2e.py`：

- 用 `docker-compose.test.yml` 起 postgres + redis（无 worker container —— 测试自起 worker，便于注入 mock embedder 加速）
- 测试代码用 Arq 0.28 推荐方式构造 worker：

  ```python
  from arq.worker import Worker
  worker = Worker(
      functions=[ingest_document], redis_settings=...,
      burst=True, max_jobs=1, ctx={"sessionmaker": sm, "embedder": fake_emb},
  )
  await worker.async_run()  # burst=True → queue 空了自动退出
  ```

- 上传 → enqueue → `await worker.async_run()` → 断言 `documents.status='ready'`、chunks 数量、向量维度
- 不用 `arq.worker.run_worker`（那是同步 CLI 入口），不用 `worker.run_check`（那是 retry 计数检查辅助）

### 7.3 故障注入（P0）

- **worker 崩溃 → 重启 → 自动续跑**：在 job 第 5 页 `os._exit(1)`，重启 worker，断言最终 status=ready 且 chunks 数量 == 完整文档应有数量（验证幂等清理）
- **redis 丢失 → backend 启动 reaper 工作**：先入 job，停 redis 容器、起新 redis、重启 backend，断言任务被重新执行
- **backend restart while worker still running**（review 标 P0）：worker 在跑某个 doc 的 page 50 时，重启 backend 触发 reaper enqueue 同 `_job_id`。断言：
  - reaper 的 enqueue 因 `_job_id` 去重不真投 → Arq 入队计数仍为 1
  - worker 当前 job 不被打断，最终顺利完成
  - 没有重复 chunks，状态曲线单调推进（不出现 ready → processing 回退）
- **deterministic _job_id 去重**：连续 enqueue 同一 doc_id 三次，断言只有一条进 in-progress / queue

---

## 8. 观察性

V1 用结构化字段日志，所有 ingestion 相关行包含 `doc_id`、`job_id`、`job_try`，便于 grep 关联：

| 时机 | 位置 | 关键字段 + 内容 |
|---|---|---|
| 上传 endpoint 调用 enqueue | backend | `event=ingest.enqueue doc_id=... job_id=... result=<queued\|deduped\|redis_error>` |
| Reaper enqueue（每条 stale doc）| backend startup | `event=ingest.reaper.enqueue doc_id=... job_id=... result=<queued\|deduped\|redis_error>` |
| Job 开始 | worker | `event=ingest.start doc_id=... job_id=... job_try=... max_tries=2` |
| 第一步幂等清理 | worker | `event=ingest.reset doc_id=... deleted_chunks=N` |
| 业务异常标 failed | worker | `event=ingest.failed.business doc_id=... reason=...` |
| 基础设施异常 re-raise | worker | `event=ingest.failed.infra doc_id=... will_retry=<true\|false>` |
| Cancel | worker | `event=ingest.cancelled doc_id=... job_try=... last_try=<true\|false>` |
| 成功 | worker | `event=ingest.ready doc_id=... chunks=N pages=N elapsed_s=...` |

> ⚠️ 关键点（review-3 命中）：`ArqRedis.enqueue_job(..., _job_id=...)` 在去重命中时返回 `None`，否则返回 `Job` 实例。要在 enqueue 调用点把这个返回值显式分类成 `queued / deduped / redis_error` 写日志 —— 否则 reaper 到底是真投了、被 Arq 去重了、还是 Redis 失败了，全都看不见，等于黑盒。

`arq` 自带 worker 心跳 / queue size 日志，作为 worker 存活与否的二级信号。

---

## 9. 迁移与上线

1. PR 拆为两步：
   - 第 1 PR：基础设施 + 跑通 happy path（redis 容器、worker 容器、enqueue、消费）
   - 第 2 PR：错误处理（reaper 改造、retry 验证、startup 重投）
2. 本地验证：上传 282 页腾讯年报 → 流程成功 → chat 在解析期间不被卡顿
3. 旧分支 `fix/ingestion-race-and-progress` 的三个 bug fix 不动（仍然有效，作为 worker 模式的内部正确性保证）

---

## 10. 已确认决策回顾

| # | 决策 | 选项 |
|---|---|---|
| 1 | 队列中间件 | **Redis + Arq** |
| 2 | BGE 部署 | **backend + worker 各自加载（~2GB 总内存）** |
| 3 | 失败 / 崩溃恢复 | **Arq lease + max_tries=2 + backend 启动 reaper 用 `_job_id` 去重重投 + last-try fresh-session mark-failed** |
| 4 | 异常分类（review-2 增加） | **业务不可恢复 → 标 failed return；基础设施瞬时错 → re-raise 让 Arq retry** |
| 5 | BGE encode（review-2 增加 → review-3 加严 → review-5 shutdown 语义） | **`BgeEmbedder` 内置 `ThreadPoolExecutor(max_workers=1)`，所有 encode 走 `embed_batch_async / encode_one_async`**（backend chat 路径同步改造）；`close()` 默认 `wait=False`，编排端 grace period 决定上限；测试用 `wait=True` 验证无线程泄漏 |
| 6 | 文件落盘崩溃兜底（review-5 增加） | **worker job step-2 预检 `path.is_file()`**，缺文件即业务异常标 failed（错误信息直接告诉用户重传），不交给基础设施 retry 路径 |

---

## 11. 风险与遗留

- **Worker 单实例**：解析吞吐 = 1 个 doc 同时跑。后续若需并发，开 `max_jobs>1` + 评估内存。
- **Redis 无持久化**：靠 backend reaper 兜底。如未来接入告警，Redis 可加 RDB snapshot。
- **HF cache 锁**：两个容器同时下载新模型时可能冲突。当前模型已下载，不会触发；若换模型，需手动预热一次。
- **Job 入队 vs DB 写入非原子**：上传 endpoint 的 enqueue 失败留 stale row。已在 §4.1 步骤 5 显式 catch + 标 failed + 删 disk 文件。极端情况（步骤 5 之前进程被杀）靠 reaper 兜底。
- **取消粒度受限于 BGE encode 边界**：§3.5 用 `BgeEmbedder` 内置 single-thread executor（**不是** `asyncio.to_thread` 的默认 pool）让 cancel 在 batch 之间能落地，但单个 batch encode（百毫秒级）依然不可中断。极端情况（chunk 内容异常大）单 batch 时间会变长。V2 可考虑跑独立 BGE 子进程，用 SIGTERM 中断。
- **last-try mark-failed 是 best-effort**：§3.2 的 `shield + wait_for(5s)` 在 DB 也挂的极端情况会跑不完，doc 会再次卡 processing。如果触发：靠后续 backend 启动 reaper 重投 → 又走一遍 max_tries。V2 用 cron-style periodic reaper（Arq 自带 `cron_jobs`）补这个边角。
- **`max_tries` 跨重启不重置**：当前每次 backend 启动 reaper enqueue 同 `_job_id` 是 fresh job，try 计数会从 1 开始。如果一个 doc 在 V1 mark-failed 阶段失败 → 后续 backend 重启会重投并重新尝试两次。这是想要的"再给一次机会"语义但需要意识到。
