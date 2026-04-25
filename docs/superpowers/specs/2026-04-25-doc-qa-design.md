# Document QA Assistant — Design Spec

**Date**: 2026-04-25
**Status**: Approved (pending implementation)
**Owner**: jeff

---

## 1. 项目目标

一个 PDF 文档问答聊天机器人。用户上传 PDF 后，可以用自然语言提问，机器人**只**基于文档内容作答，并附带页码出处。文档外的问题必须如实告知"未找到"，禁止编造。

### 标准回应文案（全系统统一）

为保证 E2E 测试稳定 + 用户体验一致，定义 4 个标准固定回答：

| 场景 | 标准回应 | 断言子串 |
|---|---|---|
| 已上传文档但找不到相关信息（含文档外问题） | `在已上传文档中未找到相关信息。` | `未找到相关信息` |
| 当前会话无任何文档（empty） | `请先上传 PDF 文档以开始提问。` | `请先上传` |
| 当前会话仅有 processing 文档 | `文档正在解析中，请稍候再提问。` | `正在解析中` |
| 当前会话仅有 failed 文档 | `已上传的文档解析失败，请删除后重新上传。` | `解析失败` |

后续 prompt、E2E 断言、UI 提示均引用上述四个句子。

### 验收三类问题（基于挑战附带的腾讯 2025 年报）

| 类型 | 示例 | 验收标准 |
|---|---|---|
| 事实检索 | "2025 总营收？" | 答出数字 + 引用对应页码 |
| 章节摘要 | "总结主要业务板块" | 综合 3+ 处来源 + 列出引用页 |
| 数值/比较推理 | "2025 vs 2024 净利润增长" | 答出比较结果 + 引用两年数据所在页 |
| 边界（文档外） | "今天天气如何？" | 命中 `未找到相关信息` 子串，无 citations |

### 工程目标
- 2 天交付（演示 + 工程质量并重）
- 一键启动（`docker compose up`）
- 关键路径有测试 + 边界用例覆盖
- README 专业、有截图

---

## 2. 总体架构

```
┌─────────────────────────────────────────┐
│  前端 (Next.js 15 + React 19)            │
│  ├─ 空状态：引导式上传                   │
│  ├─ 已上传：顶部文档横条                 │
│  ├─ 聊天面板：消息流 + Citation 卡片     │
│  └─ 上传进度：SSE 订阅 (page X/Y)        │
└────────────┬─────────────────────────────┘
             │ HTTP / SSE
┌────────────▼─────────────────────────────┐
│  FastAPI 后端                             │
│  ├─ POST /sessions                        │
│  ├─ GET  /sessions                        │
│  ├─ GET    /sessions/{session_id}/messages          │
│  ├─ POST   /chat/stream                              (SSE) │
│  ├─ POST   /sessions/{session_id}/documents          │
│  ├─ GET    /sessions/{session_id}/documents          │
│  ├─ DELETE /sessions/{session_id}/documents/{document_id} │
│  └─ GET    /sessions/{session_id}/documents/{document_id}/progress (SSE) │
│        ↓                                  │
│  ConversationEngine                       │
│        ↓                                  │
│  ToolRegistry: [search_documents]         │
│        ↓                                  │
│  PgVector → top-8 chunks → Moonshot K2.6  │
└──────────────────────────────────────────┘
              │
┌─────────────▼────────────────────────────┐
│  PostgreSQL 16 + pgvector                 │
│  Tables: users, sessions, messages,       │
│          documents, document_chunks       │
└──────────────────────────────────────────┘
```

### 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI | 异步、ASGI |
| ORM | SQLAlchemy 2.0 (async) + Alembic | 异步引擎 |
| DB | PostgreSQL 16 + pgvector | 1024 维向量 |
| Embedding | BGE-large-zh-v1.5 | 本地 CPU 推理，中文友好 |
| LLM | Moonshot K2.6 (硅基流动 API) | 128k 上下文 |
| PDF 解析 | pdfplumber | 中文支持好、不乱码 |
| 前端 | Next.js 15 + React 19 + Tailwind 4 + shadcn/ui | App Router、Turbopack |
| SSE 解析 | 手写（不依赖 Vercel AI SDK） | 已有实现可复用 |
| 测试 | pytest + testcontainers / Vitest | 后端 / 前端 |
| 容器 | docker-compose (postgres + backend + frontend) | 一键启动 |

---

## 3. 数据模型

### 全部表（5 张，最小化）

```python
class User:                       # 单用户 demo（硬编码 UUID）
    id: UUID PK
    name: str
    created_at: timestamp

class Session:
    id: UUID PK
    user_id: UUID FK
    created_at: timestamp
    last_active_at: timestamp
    summary: text | None              # 长会话摘要（可选启用）
    summary_until_message_id: int | None

class Message:
    id: BIGINT PK (autoincrement)     # 用于压缩边界
    session_id: UUID FK
    role: enum(user, assistant, tool)
    content: text
    tool_calls: JSONB | None
    tool_call_id: str | None
    citations: JSONB | None           # NEW — assistant 消息的来源
    created_at: timestamp

class Document:                       # NEW
    id: UUID PK
    user_id: UUID FK
    session_id: UUID FK NOT NULL      # 会话级隔离
    filename: str
    page_count: int                   # NOT NULL — 上传端点同步打开 PDF 取页数后才 INSERT
    byte_size: int
    status: enum(processing, ready, failed)
    error_message: str | None
    progress_page: int                # NOT NULL，default 0；ingestion 中递增
    uploaded_at: timestamp
    ingestion_started_at: timestamp | None   # 用于超时检测（>5min 视为 stale）

class DocumentChunk:                  # NEW
    id: UUID PK
    document_id: UUID FK CASCADE
    page_no: int                      # 1-based
    chunk_idx: int                    # 文档内序号
    content: text
    content_embedding: vector(1024)
    token_count: int
```

**索引**：
- `documents(session_id)`
- `document_chunks(document_id)`
- `document_chunks USING ivfflat (content_embedding vector_cosine_ops)` 100 lists

**Alembic**：单一 initial migration，包含 5 张表 + pgvector extension。

---

## 4. 上传 → 入库流程

```
POST /sessions/{session_id}/documents (multipart/form-data)
  1. 校验：session 归属、扩展名 .pdf、大小 ≤ 20MB
  2. 写入 temp path：data/uploads/.tmp/{uuid4}.pdf（确保此目录存在）
  3. 同步打开 temp 文件做轻量验证（<100ms）：
     a. pdfplumber.open(...) 失败 → unlink temp + 400 "无法打开 PDF（损坏？）"
     b. PDF 加密（open 抛 EncryptedPdfError）→ unlink temp + 400 "PDF 已加密"
     c. 取 page_count = len(pdf.pages)；page_count == 0 → unlink temp + 400 "空 PDF"
     注意：不在此处抽 extract_text() 检测"扫描版"——open 不抽文本，
     抽样会增加上传延迟且对带封面图的混合 PDF 误判。检测下放到 ingestion。
  4. 分配 document_id = uuid4()
  5. INSERT documents (
       id=document_id, status=processing, page_count=N,
       progress_page=0, ingestion_started_at=now()
     )
     - INSERT 失败 → unlink temp + 500
  6. 原子 rename：os.replace(temp_path, data/uploads/{document_id}.pdf)
     - rename 失败（极少见，跨设备等）→ DELETE documents row + unlink temp + 500
  7. 启动 asyncio.create_task(_ingest_with_timeout(doc_id))
  8. 返回 {document_id, status: "processing", page_count: N}

**清理保证**：任何上传失败路径都不会留下孤儿文件或孤儿 DB 行。
正式路径 `data/uploads/{document_id}.pdf` 一旦存在，必有同 ID 的 documents 行。

后台 _ingest_document(doc_id):
  total_chunks = 0
  try:
    with pdfplumber.open(file_path) as pdf:
      for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        chunks = chunker.chunk(text, page_no=i+1)
        if chunks:
          embeddings = bge.encode_batch([c.content for c in chunks])
          await db.bulk_insert_chunks(doc_id, chunks, embeddings)
          total_chunks += len(chunks)
        await db.update_document(doc_id, progress_page=i+1)

    # 扫描版/无文本检测：所有页都跑完了但没产出任何 chunk
    if total_chunks == 0:
      await db.update_document(doc_id, status='failed',
        error_message='未能从 PDF 中提取任何文本（疑似扫描版或纯图像 PDF）')
      return

    await db.update_document(doc_id, status='ready')
  except Exception as e:
    await db.update_document(doc_id, status='failed',
                              error_message=str(e)[:500])
    log.exception("ingestion failed for %s", doc_id)

GET /sessions/{session_id}/documents/{document_id}/progress (SSE)
  - 每 500ms 查询 documents 表，推送：
    event: progress
    data: {"page": progress_page, "total": page_count, "phase": "ingesting"}
  - status=ready/failed 时推送 done 事件并关闭流
```

### 启动恢复 + 超时清理（关键）

`asyncio.create_task` 是 in-memory 后台任务，进程重启 / dev reload / crash 都会丢失。需要两道防护：

**a) App startup hook**（src/main.py 启动时执行一次）：
```python
@app.on_event("startup")
async def cleanup_stale_documents():
    """把所有上次进程残留的 processing 标为 failed。
    任何重启都会重置卡死状态，与 'docker restart 历史保留' 验收兼容
    （已 ready 的文档完全不受影响）。
    """
    await db.execute("""
        UPDATE documents
           SET status = 'failed',
               error_message = '解析中断（服务重启）'
         WHERE status = 'processing'
    """)
```

**b) 单条 ingestion 软超时**（5 分钟）：
```python
# 在 _ingest_document 外层包 asyncio.wait_for
async def _ingest_with_timeout(doc_id):
    try:
        await asyncio.wait_for(_ingest_document(doc_id), timeout=300)
    except asyncio.TimeoutError:
        await db.update_document(doc_id, status='failed',
                                  error_message='解析超时（>5 分钟）')
```

这两个机制保证：
- 重启不留卡死的 processing
- 单个异常 PDF 不会无限挂起
- "重启 docker 后历史保留"验收只关注 `status=ready` 的文档，不受影响

### 删除文档

```
DELETE /sessions/{session_id}/documents/{document_id}
  1. 校验 session 归属
  2. SELECT status FROM documents WHERE id=:doc_id
     - 不存在 → 404
     - status='processing' → 409 "文档正在解析中，请等待完成或解析超时（≤5min）后再删除"
       （理由：见下方"为什么不支持删除 processing"）
     - status in ('ready', 'failed') → 继续
  3. DELETE FROM documents WHERE id=:doc_id
     (FK CASCADE 自动删 document_chunks)
  4. 删磁盘文件：os.unlink(data/uploads/{document_id}.pdf)
     (失败不阻塞 —— DB 已是真相之源；记 warn 日志)
  5. 不修改历史 messages.citations
  6. 返回 204
```

**为什么不支持删除 processing**：
- 后台 `_ingest_document` 并不知道 doc 被删，会继续 INSERT chunks → FK violation 抛错；
  或读已删文件失败抛错；产生大量 log 噪音 + 浪费 BGE 算力
- 实现 cancel 信号需引入 task 注册表 + 每页轮询 cancel flag → 复杂度激增（属 V2+）
- 用户体验上：5min 超时后会自动 failed，可立即删除；失败也可立即删除
- README 在"已知限制"小节写明此约束

**为什么不动 messages.citations**：
- citations JSONB 里存的是 `{doc_id, filename, page_no, snippet, score}` —— 自包含，不依赖 documents 表
- 历史对话保留来源信息符合用户预期（"当时这个回答的依据是什么"）
- 前端 CitationCard 渲染不需要回查 documents 表
- 避免删一个 doc 要扫全表 messages 的开销

**副作用**：删除已 ready 的文档会让该会话之后的检索不再包含它（`WHERE status='ready'` 自动过滤），符合直觉。

### Chunker 策略

约束：≤500 token / chunk，overlap 80 token，**页边界硬切**（不跨页，保证 page_no 准确）。

```python
MAX_TOKENS = 500
OVERLAP_TOKENS = 80

def chunk(text: str, page_no: int) -> list[Chunk]:
    paragraphs = [p for p in split_paragraphs(text) if p.strip()]
    if not paragraphs:
        return []   # 空白页

    chunks: list[Chunk] = []
    buf = ""        # 当前正在累积的 chunk 文本

    def flush():
        nonlocal buf
        if buf.strip():
            chunks.append(Chunk(content=buf.strip(), page_no=page_no))
        buf = ""

    for para in paragraphs:
        para_tokens = token_count(para)

        # Case 1: 单段本身就超长 → 先 flush 当前 buf，再硬切此段
        if para_tokens > MAX_TOKENS:
            flush()
            for piece in _split_oversized(para, MAX_TOKENS, OVERLAP_TOKENS):
                chunks.append(Chunk(content=piece, page_no=page_no))
            continue

        # Case 2: 加入当前 buf 仍 <= 上限 → 累积
        if token_count(buf) + para_tokens <= MAX_TOKENS:
            buf += ("\n\n" if buf else "") + para
            continue

        # Case 3: 加入会超 → flush + 用 overlap 起新 buf
        tail = take_tail_tokens(buf, OVERLAP_TOKENS)
        flush()
        buf = (tail + "\n\n" + para) if tail else para
        # 极端情况：tail + para 仍 > MAX_TOKENS（para 接近 MAX，tail 80）
        # 退化为硬切起新段
        if token_count(buf) > MAX_TOKENS:
            for piece in _split_oversized(buf, MAX_TOKENS, OVERLAP_TOKENS):
                chunks.append(Chunk(content=piece, page_no=page_no))
            buf = ""

    flush()
    return chunks


def _split_oversized(text: str, max_tokens: int, overlap: int) -> Iterator[str]:
    """超长段落 → 优先按句号切，再按 max_tokens 滑窗硬切，保证每片 ≤ max_tokens。"""
    sentences = split_sentences(text)   # "。" "！" "？" + "\n"
    buf = ""
    for s in sentences:
        if token_count(s) > max_tokens:
            # 单句也超长（少见，如表格行）→ 滑窗硬切
            if buf.strip():
                yield buf.strip()
                buf = ""
            for i in range(0, token_count(s), max_tokens - overlap):
                yield take_tokens(s, i, i + max_tokens)
            continue
        if token_count(buf) + token_count(s) <= max_tokens:
            buf += s
        else:
            if buf.strip():
                yield buf.strip()
            buf = take_tail_tokens(buf, overlap) + s
    if buf.strip():
        yield buf.strip()
```

**覆盖的边界（test_chunker.py 必测）**：
1. 空白页 → 返回 `[]`
2. 普通短段落 → 1 个 chunk
3. 多段加起来恰好 = 500 → 1 chunk
4. 多段加起来 > 500 → 多 chunk + overlap 校验
5. 单段 > 500（连续表格行/长公式） → `_split_oversized` 切分，每片 ≤ 500
6. tail+para 仍 > 500（罕见极端）→ 退化路径
7. 单句 > 500 → 滑窗硬切，无信息丢失

---

## 5. 检索 Tool

`src/tools/search_documents.py` —— **唯一注册的 tool**。

```python
TOOL_SCHEMA = {
    "name": "search_documents",
    "description": (
        "在用户当前会话已上传的 PDF 中检索相关段落。"
        "回答任何关于文档内容的问题前必须先调用此工具。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "中文检索 query，可以是用户原问题或提取的关键词"
            }
        },
        "required": ["query"]
    }
}
```

**实现要点**：
- 检索范围：`WHERE document_id IN (SELECT id FROM documents WHERE session_id=:session_id AND status='ready')`
- 向量化 query → BGE → cosine 相似度（注：pgvector `<=>` 返回 *distance* = 1 - similarity，越小越相关）
- 取 top-K（默认 16）→ 转成 similarity → **过滤 similarity < `MIN_SIMILARITY`** （配置项，默认 0.35 起点，需校准）
  - 阈值放在 `config.yaml::retrieval.min_similarity`，可调
  - **必须做校准**：见 §13 任务 T2.5 (`scripts/calibrate_threshold.py`)
    - 用挑战附带的腾讯年报 + 3 个相关 query（"总营收"/"业务板块"/"风险因素"）
      + 3 个无关 query（"今天天气"/"梅西踢哪个俱乐部"/"如何做红烧肉"）
    - 输出每条 query 的 top-K 分数分布
    - 根据 gap 调整 default 阈值并写回 config（dev 环节完成）
- 过滤后保留前 `top_n`（默认 8）
- 同文档同页连续 chunk 合并去重
- 返回结构：

```json
{
  "ok": true,
  "found": true,
  "chunks": [
    {
      "doc_id": "uuid",
      "filename": "腾讯2025年度报告.pdf",
      "page_no": 12,
      "content": "完整 chunk 文本",
      "score": 0.823
    }
  ]
}
```

**空/低分结果**：
```json
{ "ok": true, "found": false, "chunks": [] }
```
LLM 看到 `found=false` 必须按"标准回应文案"回应（"在已上传文档中未找到相关信息"）。

**Note for issue 6 collaboration**：tool 这里返回 chunks，但 SSE `citations` 事件不在此时发；详见第 7 节。

---

## 6. Prompt 设计

按当前 session 的文档状态选模板。`_prepare_round` 查询：
```sql
SELECT
  COUNT(*) FILTER (WHERE status='ready')      AS ready,
  COUNT(*) FILTER (WHERE status='processing') AS processing,
  COUNT(*) FILTER (WHERE status='failed')     AS failed
FROM documents WHERE session_id = :sid
```

模板选择：
- `ready ≥ 1` → 模板 A（正常对话）
- `ready == 0 AND processing > 0` → 模板 B-PROCESSING
- `ready == 0 AND failed > 0 AND processing == 0` → 模板 B-FAILED
- `ready == 0 AND processing == 0 AND failed == 0` → 模板 B-EMPTY

模板 B-* 都不调 tool，直接返回固定句子。

### 6.1 模板 A：已上传文档（ready ≥ 1）

```
你是一个文档问答助手。

【可用文档】
- 腾讯2025年度报告.pdf（共 89 页）

【行为规则】
1. 任何用户问题都必须先调用 search_documents 工具检索
2. 工具返回 found=false 或 chunks 为空时，必须**完整、原样**回答：
   "在已上传文档中未找到相关信息。"
   不要补充猜测、不要解释为什么没找到、不要给替代答案
3. 工具返回 found=true 时，只能基于这些 chunks 的内容作答；
   不得使用你的常识或训练知识补充
4. 不要在回答正文中标注 [1] [2] 这类引用，前端会自动渲染来源卡片
5. 用简洁、专业的中文回答；数字保留报告中的精度
```

### 6.2 模板 B 三态

| 子模板 | 触发条件 | 固定回答 | 断言子串 |
|---|---|---|---|
| B-EMPTY | 无任何 documents 记录 | `请先上传 PDF 文档以开始提问。` | `请先上传` |
| B-PROCESSING | 仅 processing（无 ready） | `文档正在解析中，请稍候再提问。` | `正在解析中` |
| B-FAILED | 仅 failed（无 ready/processing） | `已上传的文档解析失败，请删除后重新上传。` | `解析失败` |

**实现**：B-* 模板不走 LLM、不调 tool，`_prepare_round` 直接返回 fixed response，节省 round-trip 和 token。SSE 流统一发 `text → citations(chunks=[]) → done` 三个事件（详见 §7），前端无需分支判断。

---

## 7. SSE 协议

### 现有事件（保留）
| event | data | 用途 |
|---|---|---|
| `text` | `{"delta": "..."}` | LLM 输出片段 |
| `tool_call_started` | `{"id": ..., "name": ...}` | tool 开始 |
| `tool_call_finished` | `{"id": ..., "ok": bool}` | tool 结束 |
| `done` | `{}` | 完整结束 |
| `error` | `{"message": ..., "code": ...}` | 异常 |

### 新增事件
| event | data | 用途 |
|---|---|---|
| `citations` | `{"chunks": Citation[]}` | 绑定 assistant final message 的来源；空数组表示无来源；**所有** chat SSE 流必发，含 B-* 模板 |

### Citation DTO

后端 → 前端唯一的引用结构。复用同一个 DTO 在 SSE event、`Message.citations` 持久化、API 响应。

```python
class Citation(BaseModel):
    doc_id: str           # UUID 字符串；前端可用于"该来源的文档是否还存在"判断
    filename: str         # 原始文件名，UI 直接显示
    page_no: int          # 1-based
    snippet: str          # = chunk.content[:480]，末尾若被截断则添加 "…"
                          #   480 字符 ≈ 卡片"展开后"完整可读；UI 默认 line-clamp-2
                          #   显示约前 120 字符（2 行），点击展开看全部
    score: float          # 检索 cosine similarity；UI 不显示，用于 debug + 排序
```

**snippet 派生规则**：
```python
def to_snippet(content: str, max_chars: int = 480) -> str:
    if len(content) <= max_chars:
        return content
    truncated = content[:max_chars].rstrip()
    return truncated + "…"
```

**Message.citations 持久化**：JSONB 数组，每元素结构同 Citation DTO；删除 documents 后历史 citations 仍可独立渲染（snippet/filename/page 自包含）。

**citations 事件的发射时机（关键）**：

不能在 `tool_call_finished` 后立刻发，会出现"答案说未找到，UI 却显示来源卡片"的不一致。
**用结构化信号决定** citations，**不**用 LLM 输出文本子串匹配（脆弱：模型可能改写文案、加空格、或正文恰好出现该短语）。

后端在每轮对话开始时就掌握三个结构化信号：

| 信号 | 来源 |
|---|---|
| `template_used` | `_prepare_round` 选模板 A 还是 B-* 时确定 |
| `tool_responses` | 本轮所有 `search_documents` 工具调用的返回（含 `found`、`chunks`） |
| `collected_chunks` | 所有 `found=true` 调用的 chunks 合并（已去重） |

**citations 决策**：
```python
if template_used.startswith("B-"):
    # B-EMPTY / B-PROCESSING / B-FAILED：根本没调 tool
    citations = []
elif not tool_responses or all(not r.found for r in tool_responses):
    # 模板 A 但所有检索都低于阈值
    citations = []
else:
    # 模板 A 且至少一次 found=true
    citations = [Citation.from_chunk(c) for c in collected_chunks]
```

发射流程（**所有** chat SSE 路径统一**必发**，包含 B-*）：
```
1. LLM 流式输出（B-* 直接 yield 固定句的 text deltas）
   → 累积 final_text；同步累积 tool_responses + collected_chunks
2. LLM 完成后按上面决策计算 citations（B-* 永远 []）
3. yield StreamEvent.citations(chunks=citations)   ← 必发，即使 chunks=[]
4. yield StreamEvent.done()
5. 持久化 assistant message 时一并写入 message.citations
```

**为什么 B-* 也发空 citations**：前端只有一条流处理路径，不需要 if/else 分支判断；
`citations` 始终是"本轮回答的最终结果"信号，UI 渲染逻辑统一为 `if msg.citations.length > 0 then render CitationCard`。

**已知边界**：模板 A + tool found=true 但 LLM 仍回"未找到"（罕见模型抖动）→ UI 会显示 citations。可接受，因为 chunks 确实作为证据传给了 LLM；如频繁发生则收紧 prompt（不通过 UI hack 修复）。

**幂等保证**：前端只在收到 `citations` 事件后才渲染 CitationCard；citations=[] 不渲染。

### 上传进度专用流
`GET /sessions/{session_id}/documents/{document_id}/progress`：
| event | data |
|---|---|
| `progress` | `{"page": 45, "total": 89, "phase": "ingesting"}` |
| `done` | `{"status": "ready" \| "failed", "error": ...}` |

---

## 8. UI 设计

### 8.1 整体布局（"D 模式"）

```
┌─────────────┬───────────────────────────────────┐
│  侧边栏     │                                   │
│  + 新对话   │   [空状态] 引导式上传区            │
│  财报问答 ✓ │       OR                          │
│  合同审阅   │   [已传] 顶部文档横条 + 聊天流     │
└─────────────┴───────────────────────────────────┘
```

- **空状态**（无文档时）：聊天面板中央显示引导块 + 大拖拽区
- **有文档时**：顶部固定一条横向文档列表 + 下方聊天流
- 输入框 disabled 直到至少 1 份文档 status=ready

### 8.2 空状态文案（"B 引导式"）

```
┌──────────────────────────────────────────┐
│                                          │
│   📄 文档问答                             │
│   上传 PDF，针对内容自由提问。            │
│   所有回答都附带原文出处。                │
│                                          │
│   ┌────────────────────────────────────┐ │
│   │           📥                        │ │
│   │   拖入 PDF 或点击上传               │ │
│   │   支持中文 · ≤20MB · 可上传多份     │ │
│   └────────────────────────────────────┘ │
│                                          │
│   先上传一份文档，然后开始提问…           │
└──────────────────────────────────────────┘
```

### 8.3 上传反馈（"B 进度条 + 步骤文案"）

四个状态：
1. **解析中**：黄色 row + 进度条 + "正在向量化第 45 / 89 页…"
2. **就绪**：绿色 row + 页数 + ✓ 就绪徽章
3. **失败**：红色 row + 错误说明 + "重试"链接
4. **拖拽态**：紫色高亮 + "松开以上传 PDF"

### 8.4 Citation 卡片（"B 卡片式 + snippet 预览"）

```
┌─────────────────────────────────────────┐
│ 腾讯 2025 年总营收为 6,605 亿元，         │
│ 同比增长 10%。                            │
│                                          │
│ 📚 来源（3）                              │
│ ┌─────────────────────────────────────┐ │
│ │ [PDF] 腾讯2025年度报告.pdf      p.12 │ │
│ │      2025 年公司实现营业收入人民币    │ │
│ │      6,605 亿元，同比增长 10.2%……    │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ [PDF] 腾讯2025年度报告.pdf      p.45 │ │
│ │      金融科技及企业服务业务收入达到… │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

- 红色 PDF 徽章 + 文件名 + 蓝色页码徽章
- snippet 默认显示 2 行 + 截断
- 点击卡片 → 展开完整 snippet

---

## 9. 前端组件清单

| 组件 | 来源 | 说明 |
|---|---|---|
| `<SessionsSidebar>` | 复用 chat repo | 略调样式，去掉客户列表 |
| `<ChatPane>` | 改造 chat repo | 加入 documents 状态 + 顶部嵌入 |
| `<MessageBubble>` | 改造 chat repo | 末尾加 `<CitationCard>` |
| `<DocumentUploadHero>` | 新增 | 引导式空状态 |
| `<DocumentTopBar>` | 新增 | 已上传后的顶部横条 |
| `<DocumentRow>` | 新增 | 文档行（三态视觉） |
| `<UploadProgressSse>` | 新增（hook） | 订阅 progress SSE |
| `<CitationCard>` | 新增 | 来源卡片 |

---

## 10. 测试策略

### 后端
| 文件 | 覆盖 |
|---|---|
| `tests/unit/test_pdf_parser.py` | 中文 PDF fixture：页文本提取、空白页跳过、不乱码；加密 PDF 上传报 400 |
| `tests/unit/test_chunker.py` | 7 个边界（见 §4 末）：空白页 / 短段 / 恰好 500 / 多段超 / 单段超 / tail+para 退化 / 单句超 |
| `tests/unit/test_api_documents.py` | 上传 happy / 大文件拒绝 / 非 PDF 拒绝 / 加密 PDF 拒绝 / 空 PDF 拒绝 / 校验失败时 temp 文件被清理（无孤儿） / 状态轮询 |
| `tests/unit/test_delete_document.py` | DELETE：ready/failed 成功（cascade chunks、文件移除、messages.citations 保留不变）；processing 返回 409；不存在 doc 返回 404 |
| `tests/unit/test_ingestion_scanned.py` | 扫描版/纯图像 PDF：所有页 extract_text 为空 → status=failed + 描述性 error |
| `tests/unit/test_search_documents.py` | 检索范围隔离（不同 session）/ 阈值过滤 / found=true/false 分支 / top-k 排序 / Citation DTO snippet 截断（≤480 + "…"） |
| `tests/unit/test_conversation_engine.py` | 4 模板分发（A / B-EMPTY / B-PROCESSING / B-FAILED）+ citations 结构化绑定（B-* → []，A+found=false → []，A+found=true → chunks）+ **所有路径都发 citations event**（含 B-*） |
| `tests/unit/test_startup_recovery.py` | 模拟 stale processing → startup 后被标 failed（带 error_message） |
| `tests/unit/test_sse.py` | citations / progress 事件编码解码 |
| `tests/e2e/test_doc_qa.py` | 用腾讯年报跑 4 类问题：事实/摘要/对比/边界；4 个 no-answer 子模板各断言对应子串 + citations=[] |

### 前端
| 文件 | 覆盖 |
|---|---|
| `frontend/tests/sse-stream.test.ts` | 复用：text/tool/citations/done 事件解析 |
| `frontend/tests/citation-card.test.tsx` | 渲染、点击展开、多来源 |
| `frontend/tests/upload-progress.test.ts` | progress SSE 订阅与状态切换 |

### 验收清单（手工 + 截图）
- [ ] 空状态截图（拖拽前）
- [ ] 拖拽态截图（高亮）
- [ ] 解析中截图（进度条）
- [ ] 就绪截图（绿色 row）
- [ ] 提问截图：事实类 + citation 卡片
- [ ] 提问截图：摘要类
- [ ] 提问截图：对比类
- [ ] 提问截图：文档外问题（说"未找到"）
- [ ] 失败截图（解析失败 PDF）
- [ ] 重启 docker 后历史保留截图

---

## 11. 仓库组织

### 新独立仓库
- 路径：`/Users/jeff/Work/workspace/document-qa-assistant/`
- GitHub：`document-qa-assistant`（公开）
- Git history：从零 init，**不**保留 chat repo 的历史
- README：完全为这个 challenge 写，不提"复用"

### Initial commit 包含的"基础设施"（来自 chat repo 的可复用部分）

**保留**：
```
src/
  main.py                     (依赖注入装配)
  config.py                   (config.yaml + .env)
  api/
    chat.py                   (POST /chat, /chat/stream, GET /sessions, /sessions/{session_id}/messages)
    sse.py                    (StreamEvent, encode_sse, SSEStreamingResponse)
  core/
    conversation_engine.py    (handle/handle_stream，去掉 contacts/profile/reminders 注入)
    tool_registry.py          (只注册 search_documents)
    prompt_templates.py       (改写为 doc_qa 模式)
    summarizer.py             (保留备用)
    persona_loader.py         (改写 IDENTITY/SOUL → 文档助手)
  llm/
    kimi_client.py            (chat + chat_stream)
  embedding/
    bge_embedder.py           (1024 维向量)
  db/
    session.py                (异步引擎)
    migrations/               (重写为单一 init migration)
  models/
    schemas.py                (5 张表，不含 contacts/follow_ups/todos/profiles)

frontend/
  app/, components/, lib/     (脚手架 + 通用部分，去掉客户/跟进相关)
  package.json
  tailwind.config.ts
  tsconfig.json
  Dockerfile

persona/
  IDENTITY.md                 (改写：文档问答助手身份)
  SOUL.md                     (改写：纯文本、附引用、找不到要诚实说)

docker-compose.yml            (3 服务)
Dockerfile                    (后端)
pyproject.toml + uv.lock      (Python 依赖)
config.yaml + .env.example    (配置模板)
alembic.ini                   (迁移配置)
scripts/bootstrap.sh          (一次性初始化)
README.md                     (全新)
```

**不复制**：
```
src/tools/                    (5 个保险 tool 全删)
src/core/memory_service.py    (重写：只保留 session/message + documents 操作)
src/models/schemas.py         (5 张保险表全删)
persona/*                     (重写)
tests/tools/                  (全删)
tests/e2e/                    (全删)
tests/unit/test_memory_*      (重写)
docs/superpowers/specs/       (从本 spec 重新开始)
docs/superpowers/plans/       (从本 plan 重新开始)
seed_demo_user.py             (保留逻辑，删保险特有部分)
```

### Commit 规划
1. `docs: design spec for document QA assistant` — 设计文档（本文件）
2. `docs: implementation plan` — plan 文件
3. `chore: scaffold (fastapi + pgvector + bge + moonshot + nextjs)` — 基础设施
4. （后续按 plan 中 task 逐个 commit）

---

## 12. README 大纲

```markdown
# 文档问答助手 (Document QA Assistant)

针对 PDF 文档的中文问答聊天机器人。所有回答都基于文档内容，并附带页码出处。

## 一键启动

cp .env.example .env       # 填入 MOONSHOT_API_KEY
docker compose up

打开 http://localhost:3000，点击"新对话"，拖入 PDF 开始提问。

## 配置

环境变量：
- `MOONSHOT_API_KEY` (必填) — 硅基流动 API key
- `MIN_SIMILARITY` (可选，默认 0.35) — 检索相关性阈值。default 0.35 基于腾讯年报校准；不同领域 PDF 可能需要调整，运行 `scripts/calibrate_threshold.py` 输出建议值

## 演示

1. 上传 example/腾讯2025年度报告.pdf
2. 等待解析完成（约 30 秒，89 页）
3. 提问示例：
   - 2025 年总营收？
   - 总结主要业务板块
   - 2025 vs 2024 净利润增长

## 检索策略

- PDF 用 pdfplumber 逐页提取，按段落聚合到 500 token + 80 overlap
- BGE-large-zh-v1.5 中文向量化（1024 维）
- 存储到 PostgreSQL pgvector
- 检索 top-8 chunks，由 Moonshot K2.6 综合回答
- 严格约束：必须先检索，只基于检索结果回答，找不到必须说"未找到"

## 局限性

- 表格仅做文本提取，不保留结构
- 数值跨年比较依赖检索召回到两个年份对应字段
- 单文档建议 ≤20MB / ≤200 页

## 如果再给一周

- bge-reranker 二次排序提升精度
- 表格 layout-aware 解析（Camelot / unstructured）
- 全局知识库模式（跨会话引用）
- 流式上传 + 大文件支持

## 项目结构

src/         FastAPI 后端
frontend/    Next.js 前端
docs/        设计文档与实施计划
tests/       后端测试

## 测试

pytest                              # 后端单元测试
pytest -m llm                       # E2E (需 MOONSHOT_API_KEY)
cd frontend && pnpm test            # 前端测试
```

---

## 13. 工作量与降级阶梯

### 完整版（理想 24h，按 task 切片）

| 阶段 | 时间 | 产出 |
|---|---|---|
| Day 1 上午 (4h) | T1 | Scaffold copy + 清理 + alembic 重写 + PDF parser + chunker + 单测 |
| Day 1 下午 (4h) | T2 | 上传 API + 启动恢复 + 删除端点 + search_documents tool + prompt 4 模板 |
| Day 1 晚 (1h) | T2.5 | **`scripts/calibrate_threshold.py`**：跑 3 相关 + 3 无关 query，stdout 输出分数表 + 建议阈值 + 一行 `MIN_SIMILARITY=` 示例。**不**改 config 默认值（避免本地调参泄漏 + 跨模型/PDF 漂移）；按需写到 `.env` |
| Day 1 晚 (1.5h) | T3 | citations 结构化绑定逻辑 + 后端 E2E（4 类问题，含 4 个 no-answer 子模板） |
| Day 2 上午 (4h) | T4 | 前端：empty state + top bar + 三态 row + 上传进度 SSE 订阅 |
| Day 2 下午 (4h) | T5 | citation 卡片渲染 + 输入框联动 + 历史保留验证 |
| Day 2 晚 (2h) | T6 | README + 截图 + push GitHub |
| Buffer | 3.5h | 调试、解析失败 PDF 处理、prompt 微调 |

### MVP 降级阶梯（按"如果时间不够先砍什么"排序）

> 列表越靠前，越早被砍。**P0 是必须保留的最小可演示版**。

| 优先级 | 项 | 原始范围 | 降级版 | 节省 |
|---|---|---|---|---|
| P3（先砍） | 多 PDF 同会话 | 一个会话支持多个 PDF | **单 PDF / 会话**（上传第二个时替换第一个） | -2h |
| P3 | 详细进度文案 | "正在向量化第 45/89 页…" | 仅徽章 + 转圈 | -1.5h |
| P3 | 失败重试链接 | 红 row + 重试按钮 | 红 row + "请删除后重新上传" | -0.5h |
| P3 | 前端组件单测 | citation-card / upload-progress 测试 | 跳过 | -1.5h |
| P2 | 启动恢复 hook | startup 扫 stale processing | 跳过（接受 dev 重启可能卡死） | -0.5h |
| P2 | ingestion 5min 超时 | asyncio.wait_for 包装 | 跳过 | -0.5h |
| P2 | Citation snippet 展开 | 点击卡片展开完整 snippet | 始终显示 2 行截断 | -1h |
| P2 | 拖拽态高亮 | 紫色边框 + 文案切换 | 仅虚线框 | -0.5h |
| P1 | 进度 SSE | 服务端推送进度 | 前端 polling 每 1s | -1h（其实差不多，但更稳） |
| P0（必保） | 上传 + ingestion | — | — | — |
| P0 | search + 阈值 | — | — | — |
| P0 | citations 绑定 + 渲染（基本卡片） | — | — | — |
| P0 | no-answer 行为 + 边界 E2E | — | — | — |
| P0 | docker compose 一键启动 | — | — | — |
| P0 | README + 4 张关键截图（空状态/上传中/有答案+citation/边界） | — | — | — |

**触发降级的检查点**：
- Day 1 结束时若 T1+T2+T3 未完成 → 砍掉 P3 全部
- Day 2 中午若 T4 未完成一半 → 砍掉 P2 中可砍项
- Day 2 晚 8 点若 T5 未完成 → 砍掉 P2 全部，集中保 README + 截图

**总时间评估**：
- 完整版：24h（含 4h buffer）
- 砍 P3：18h
- 砍 P3+P2：14h（最小可交付）

---

## 14. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| pdfplumber 对扫描版/复杂排版年报解析质量差 | 中 | 高 | 上传端点拒绝加密/损坏；ingestion 后 chunks=0 标 failed + 描述性 error；E2E 用挑战附带腾讯年报预先验证；README 标注扫描版不支持 |
| BGE 模型首次下载慢（~1GB） | 高 | 中 | docker-compose 启动文档明确写"首次约 5-10 分钟" |
| 数值/比较类问题召回不全 | 中 | 中 | top-8 + prompt 强约束 LLM 在召回不全时按标准句回答 |
| 相关性阈值 0.35 在不同 PDF 上不准 | 中 | 中 | 阈值通过 `MIN_SIMILARITY` 环境变量覆盖（不改 config 默认）；T2.5 跑 `calibrate_threshold.py` 输出建议值；README 写明 default 0.35 是基于腾讯年报校准，不同领域需重跑 |
| 进程重启导致 processing 卡死 | 高 | 中 | startup hook 扫 stale processing → failed；单条 ingestion 5min 超时 |
| Moonshot API 限流 | 低 | 中 | 已有 tenacity 重试 |
| 前端聊天 SSE 与上传进度 SSE 并发冲突 | 低 | 低 | 不同 endpoint，浏览器并行；EventSource 各自管理 |
| 双 PDF 同会话时 citations 来源混淆 | 低 | 低 | citation 卡片始终显示 filename + page，UI 上可区分 |

---

## 15. 不在范围内（YAGNI）

- 多用户认证（demo 单用户）
- 全局知识库（跨会话）
- PDF 预览/跳页（仅引用页码）
- 表格 layout-aware 解析
- Reranker
- 流式上传
- 生产环境 Dockerfile（dev 模式即可）
- CI/CD 配置
