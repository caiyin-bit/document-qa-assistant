# Document QA Assistant — Design Spec

**Date**: 2026-04-25
**Status**: Approved (pending implementation)
**Owner**: jeff

---

## 1. 项目目标

一个 PDF 文档问答聊天机器人。用户上传 PDF 后，可以用自然语言提问，机器人**只**基于文档内容作答，并附带页码出处。文档外的问题必须如实告知"未在已上传文档中找到"，禁止编造。

### 验收三类问题（基于挑战附带的腾讯 2025 年报）

| 类型 | 示例 | 验收标准 |
|---|---|---|
| 事实检索 | "2025 总营收？" | 答出数字 + 引用对应页码 |
| 章节摘要 | "总结主要业务板块" | 综合 3+ 处来源 + 列出引用页 |
| 数值/比较推理 | "2025 vs 2024 净利润增长" | 答出比较结果 + 引用两年数据所在页 |
| 边界（文档外） | "今天天气如何？" | 明确说"未在已上传文档中找到相关信息" |

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
│  ├─ GET  /sessions/{id}/messages          │
│  ├─ POST /chat/stream      (SSE)          │
│  ├─ POST /sessions/{id}/documents (上传) │
│  ├─ GET  /sessions/{id}/documents (列表)  │
│  ├─ DELETE /sessions/{id}/documents/{id}  │
│  └─ GET  /sessions/{id}/documents/{id}/progress (SSE) │
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
    page_count: int
    byte_size: int
    status: enum(processing, ready, failed)
    error_message: str | None
    progress_page: int | None         # 当前已处理到第 N 页
    uploaded_at: timestamp

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
POST /sessions/{sid}/documents (multipart/form-data)
  1. 校验：session 归属、扩展名 .pdf、大小 ≤ 20MB
  2. INSERT documents (status=processing, progress_page=0)
  3. 启动 asyncio.create_task(_ingest_document(...))
  4. 立即返回 {document_id, status: "processing"}

后台 _ingest_document(doc_id, file_path):
  try:
    pages = pdfplumber.open(...).pages       # 逐页提取
    for i, page in enumerate(pages):
      text = page.extract_text() or ""
      chunks_for_page = chunker.chunk(text, page_no=i+1)
      embeddings = bge.encode_batch([c.content for c in chunks_for_page])
      await db.bulk_insert_chunks(...)
      await db.update_document(doc_id, progress_page=i+1)
    await db.update_document(doc_id, status=ready, page_count=len(pages))
  except Exception as e:
    await db.update_document(doc_id, status=failed, error_message=str(e))

GET /sessions/{sid}/documents/{did}/progress (SSE)
  - 每 500ms 查询 documents.progress_page，推送：
    event: progress
    data: {"page": 45, "total": 89, "phase": "ingesting"}
  - status=ready/failed 时推送 done 事件并关闭流
```

### Chunker 策略

```python
def chunk(text: str, page_no: int) -> list[Chunk]:
    """
    按段落聚合到 ≤500 token，overlap 80 token。
    页边界硬切（不跨页），保证 page_no 准确。
    """
    paragraphs = split_paragraphs(text)
    chunks = []
    buf = ""
    for para in paragraphs:
        if token_count(buf + para) <= 500:
            buf += para + "\n\n"
        else:
            if buf:
                chunks.append(Chunk(content=buf, page_no=page_no))
            # overlap：取上一段末尾 80 token 接到新段开头
            buf = take_tail_tokens(buf, 80) + para + "\n\n"
    if buf:
        chunks.append(Chunk(content=buf, page_no=page_no))
    return chunks
```

边界：
- 空段落 → 跳过
- 单段超 500 token → 按句号硬切
- 整页空白 → 跳过该页（page_no 不创建 chunk）

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
- 检索范围：`WHERE document_id IN (SELECT id FROM documents WHERE session_id=:sid AND status='ready')`
- 向量化 query → BGE → cosine 检索 top-8 chunks
- 同文档同页连续 chunk 合并去重
- 返回结构：

```json
{
  "ok": true,
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

**空结果**：`{"ok": true, "chunks": []}` —— LLM 看到后必须说"未找到"。

---

## 6. Prompt 设计

```
你是一个文档问答助手。

【可用文档】
- 腾讯2025年度报告.pdf（共 89 页）

【行为规则】
1. 任何关于文档内容的问题，必须先调用 search_documents 工具检索
2. 只能基于检索到的内容回答；如果检索结果为空或不相关，必须明确说"在已上传文档中未找到相关信息"
3. 禁止使用你的常识或训练知识补充答案
4. 不要在回答正文中标注 [1] [2] 这类引用，前端会自动渲染来源卡片
5. 用简洁、专业的中文回答；如果是数字，保留报告中的精度
6. 如果用户问没上传文档的问题（如"今天天气"），礼貌说明"我只能回答你上传文档相关的问题"
```

**没上传文档时**：system prompt 注明"当前会话尚未上传文档"，LLM 不调 tool，直接引导用户上传。

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
| `citations` | `{"tool_call_id": ..., "chunks": [{filename, page_no, snippet}]}` | search_documents 返回的来源，前端用于渲染 CitationCard |

### 上传进度专用流
`GET /sessions/{sid}/documents/{did}/progress`：
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
| `tests/unit/test_pdf_parser.py` | 中文 PDF fixture：页文本提取、空白页跳过、不乱码 |
| `tests/unit/test_chunker.py` | 段落聚合、超长段落硬切、页边界、overlap 计算 |
| `tests/unit/test_api_documents.py` | 上传 happy / 大文件拒绝 / 类型错误 / 状态轮询 / 删除 |
| `tests/unit/test_search_documents.py` | 检索范围隔离（不同 session）、空结果、top-k 排序 |
| `tests/unit/test_conversation_engine.py` | 整合：tool dispatch + citations 字段写入 |
| `tests/unit/test_sse.py` | citations 事件编码 / 解码 |
| `tests/e2e/test_doc_qa.py` | 用腾讯年报跑：事实/摘要/对比/边界 4 类问题，断言含正确页码 |

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
    chat.py                   (POST /chat, /chat/stream, GET /sessions, /sessions/{id}/messages)
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

只需一个环境变量：MOONSHOT_API_KEY (硅基流动 API)

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

## 13. 工作量与时间分配

| 阶段 | 时间 | 产出 |
|---|---|---|
| Day 1 上午 | 4h | Scaffold copy + 清理 + alembic 重写 + PDF parser + chunker + 单测 |
| Day 1 下午 | 4h | 上传 API + search_documents tool + prompt 改造 + 进度 SSE + 后端 E2E |
| Day 2 上午 | 4h | 前端：empty state + top bar + 三态 row + 上传进度订阅 |
| Day 2 下午 | 4h | citation 渲染 + 历史保留验证 + README + 截图 + push GitHub |

**总计 16h** 净开发时间。

---

## 14. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| pdfplumber 对扫描版/复杂排版年报解析质量差 | 中 | 高 | E2E 用挑战附带的腾讯年报，预先验证；README 标注扫描版不支持 |
| BGE 模型首次下载慢（~1GB） | 高 | 中 | docker-compose 启动文档明确写"首次约 5-10 分钟" |
| 数值/比较类问题召回不全 | 中 | 中 | top-8 + prompt 强约束 LLM 在召回不全时如实说 |
| Moonshot API 限流 | 低 | 中 | 现有 tenacity 重试已覆盖 |
| 前端 SSE 流式与上传 SSE 流并发冲突 | 低 | 低 | 不同 endpoint，浏览器并行 |

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
