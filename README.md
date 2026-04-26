# 文档问答助手 (Document QA Assistant)

针对中文 PDF 的问答聊天机器人:上传 PDF → 提问 → 拿到带页码出处的答案。基于 RAG(混合召回 + 重排)+ 任意 OpenAI 协议的 LLM。

---

## 一键启动

```bash
cp .env.example .env       # 填入 GEMINI_API_KEY
docker compose up -d
```

打开 [http://localhost:3000](http://localhost:3000)。

> **首次启动** 需要 5–10 分钟下载 BGE-large-zh-v1.5(~1.3 GB) + bge-reranker-base(~280 MB)。后续秒级。
>
> 使用 docker compose 启动会自动建库 + 跑 alembic 迁移 + seed demo user。

---

## 模型 / 向量化 / API Key 配置

| 角色 | 默认 | 可换 |
|---|---|---|
| **LLM** | `gemini-2.5-flash`(经 [deeprouter.top](https://deeprouter.top) 转发) | 任何 OpenAI 协议兼容的服务(Kimi / DeepSeek / Claude / GPT 等),改 `GEMINI_BASE_URL` + `GEMINI_MODEL_ID` 即可 |
| **Embedder** | `BAAI/bge-large-zh-v1.5`(本地 CPU,1024 维) | 改 `config.yaml` 的 `embedding.model_path` |
| **Reranker** | `BAAI/bge-reranker-base`(本地 CPU) | 同上,或在 `config.yaml` 把 `reranker.enabled` 设为 `false` 关掉 |

`.env` 必填项:

```bash
GEMINI_API_KEY=sk-...           # OpenAI 协议兼容的 API key

# 可选(默认见 config.yaml + docker-compose.yml)
GEMINI_BASE_URL=https://deeprouter.top/v1
GEMINI_MODEL_ID=gemini-2.5-flash
MIN_SIMILARITY=0.35
```

---

## 使用流程(带腾讯年报演示)

仓库自带 `tests/fixtures/example/腾讯2025年度报告.pdf`(282 页)作为演示文档。

1. 打开 [http://localhost:3000](http://localhost:3000),点 **「+ 新对话」**(快捷键 `⌘K`)
2. 把 PDF 拖进左侧上传区(或点击选择,支持多份)
3. 等待解析完成(282 页约 3-5 分钟,顶部进度条 + 阶段提示:加载模型 → 提取文本 → 向量化 → 入库)
4. 解析完成会出现 **绿色横幅 + 文档摘要 + 3 个建议问题**;点 chip 直接发送,或自己输入

**演示问题:**

| 类型 | 问题 | 预期 |
|---|---|---|
| 事实精确 | 腾讯 2025 年的总收入是多少? | 7,517.66 亿元(751,766 百万元),带页码引用 |
| 数量统计 | 报告期末员工总数是多少? | 115,849 人,定位第 81 页 |
| 摘要列举 | 列出主要业务板块 | 增值服务/营销服务/金融科技及企业服务,带各板块收入 |
| 边界 | 今天天气如何? | 明确说"未找到相关信息"(NO_MATCH 模板) |

**提示:** 点引用卡片右上的 `p.99` 蓝色按钮,右侧抽屉打开 PDF 直接跳到第 99 页;`Esc` 关闭抽屉或停止生成。

**跨会话复用文档:** 新建会话后,左下角"📎 添加已有文档"下拉里能选之前传过的 PDF,免重传。

---

## 检索策略(简版)

1. **切分**:`pdfplumber` 逐页提取正文 + `extract_tables()` 把表格渲染成 markdown 追加到页末;按段落聚合 ≤500 token / 80 token 重叠 / 页边界硬切;每个 chunk 内容前加 `《文件名》第N页:` 元数据前缀;繁体 → 简体归一化(`zhconv`)
2. **召回**:**Hybrid RRF** —— 用户 query 也归一化简体,然后并行跑 (a) BGE-large-zh-v1.5 向量余弦(pgvector ivfflat,probes=10) (b) pg_trgm 字符三元组关键字(GIN 索引);两路 top-16 用 Reciprocal Rank Fusion(k=60)融合
3. **重排**:`BAAI/bge-reranker-base` cross-encoder 对融合后候选重新打分,取 top-N(默认 5)喂给 LLM
4. **生成**:LLM 工具调用 `search_documents`(可循环最多 3 次),每次只回 480 字 snippet 减少 context;3 轮内未收敛触发**强制无工具兜底**给文字答案
5. **回答约束**:严格 system prompt 要求"必须先检索 / 仅基于结果作答 / 找不到必须说未找到 / 不写 [1][2] 引用编号(前端自动渲染卡片)"

---

## 取舍(本次实现的)

| 决定 | 取舍 |
|---|---|
| **pdfplumber + 表格→markdown** | 上手快、纯 Python;但复杂版式 / 跨页表格仍会乱。换 `unstructured` / `marker` / `docling` 精度更高但慢 5-10 倍 |
| **ivfflat lists=100** | 入库快;过 5 万 chunk 后召回率掉,需要切 HNSW |
| **pg_trgm 字符三元组** | 不需要 jieba 中文分词、不需要专门 Postgres 扩展;但语义聚合不如真 BM25 + 分词 |
| **bge-reranker-base** 而非 large/v2-m3 | CPU 上 ~300ms vs ~1s;牺牲 1-2% 精度换交互体验 |
| **gemini-2.5-flash** 默认 | 中文良好 + 工具调用收敛 + 价格便宜;首字 2-5s 比 Kimi-K2.6(15-120s 不稳)快一个数量级 |
| **每条 LLM 调用 120s 应用层超时** | 防止 SSE keepalive 让流"假活";超时则进 fallback 而不是 hung |
| **session_documents M2M** | 同一份 PDF 可挂多个会话,免重传;代价是 `delete_session` 要做"孤儿清理"逻辑 |
| **没做认证** | demo 阶段所有人共享 demo user;生产前必须加 |
| **没做 PII 脱敏** | 文档内容直接存 DB / 喂 LLM;不适合敏感数据 |

---

## 如果再给两周

按 ROI 排:

1. **prompt injection 防护**:PDF 内容用分隔符 + 重申"仅作引用"包起来;现在容易被恶意 PDF 操控
2. **多文档对比** RAG:跨文档召回 + 结构化输出(表格对比同期数据)
3. **结构化指标提取**:财报场景预提取营收/毛利/费用率等常见维度,做卡片直观展示
4. **HNSW 替换 ivfflat** + **分词 BM25**:大规模索引下召回质量
5. **认证 + 多租户**:cookie/JWT 登录,文档真正隔离
6. **生产 Docker 镜像**:多阶段 build / 非 root user / health check / Tini PID 1 / k8s manifest
7. **Prometheus metrics**:LLM 时延 / 召回数 / 重排时延 / token 用量
8. **流式 PDF 上传 + 大文件分片**:当前 20MB 上限是单次内存读
9. **移动端体验**:hamburger 菜单 + 触摸优化(目前只做了基础响应式)
10. **e2e 测试覆盖 chat 路径**:目前只有 ingestion 的 e2e

---

## 项目结构

```
src/
  api/         FastAPI 路由(chat / documents / sse / reaper)
  core/        引擎 + memory_service + prompt 模板 + tool registry
  ingest/      PDF 解析 + chunker + 繁简归一化 + ingestion 管线
  tools/       search_documents(V1 唯一 tool)
  llm/         OpenAI 协议客户端(GeminiClient,通用)
  embedding/   BgeEmbedder + BgeReranker
  worker/      arq 后台 ingestion worker
  db/          alembic 迁移(0001-0004)
frontend/      Next.js 15 + React 19 + Tailwind 4
docs/          设计 spec / 实施计划 / mockups
tests/         pytest 单元 + e2e
```

## 快速运维命令

```bash
docker compose logs -f backend          # 看 chat / search 链路日志
docker compose logs -f worker           # 看 ingestion 进度
docker compose exec postgres psql -U postgres -d docqa
docker compose down -v                  # 完全重置(含数据!)
```

## 测试

```bash
# 后端单元(默认跳过 LLM e2e)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/docqa \
  uv run pytest tests/unit -q

# 前端
cd frontend && pnpm test
```

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · arq |
| 数据库 | PostgreSQL 16 · pgvector(ivfflat) · pg_trgm |
| LLM | OpenAI 协议(默认 Gemini 2.5 Flash via deeprouter) |
| Embedder / Reranker | BGE-large-zh-v1.5 / bge-reranker-base(本地 CPU) |
| PDF | pdfplumber + 自定义表格→markdown |
| 前端 | Next.js 15 · React 19 · Tailwind 4 · shadcn/ui · react-markdown |
| 容器 | docker-compose(postgres + redis + backend + worker + frontend) |
