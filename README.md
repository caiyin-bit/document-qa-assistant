# 文档问答助手 (Document QA Assistant)

针对 PDF 文档的中文问答聊天机器人。所有回答都基于上传文档的内容，并附带页码出处。

## 一键启动

```bash
cp .env.example .env       # 填入 MOONSHOT_API_KEY
docker compose up
```

> 首次启动约 5–10 分钟（下载 BGE-large-zh-v1.5 模型 ~1GB）。后续启动秒级。

打开 http://localhost:3000，点击「新对话」，拖入 PDF 开始提问。

## 配置

环境变量：

- `MOONSHOT_API_KEY` （必填）— 硅基流动 API key
- `MIN_SIMILARITY` （可选，默认 0.35）— 检索相关性阈值
  - default 0.35 基于本仓库附带的腾讯年报校准
  - 不同领域 PDF 可能需要调整：
    ```bash
    uv run python scripts/calibrate_threshold.py <session_id_with_doc>
    ```
    输出 3 相关 + 3 无关 query 的分数表 + 建议值；按需写到 `.env`

## 演示流程

1. 把 `tests/fixtures/example/腾讯2025年度报告.pdf` 拖入上传区
2. 等待解析完成（约 30 秒，89 页）
3. 提问示例：
   - **事实**：腾讯 2025 年总营业收入是多少？
   - **摘要**：请总结主要业务板块
   - **对比**：2025 年净利润相比 2024 年增长了多少？
   - **边界**：今天天气如何？  → 明确说"未找到相关信息"

## 检索策略

1. PDF 用 `pdfplumber` 逐页提取文本（不含表格结构）
2. 按段落聚合到 ≤500 token + 80 overlap，按页边界硬切
3. BGE-large-zh-v1.5 中文向量化（1024 维），存入 PostgreSQL pgvector
4. 用户提问 → BGE 编码 → 取 top-16 → 过滤 similarity < `MIN_SIMILARITY`
5. 取前 8 chunks 给 Moonshot K2.6 综合作答
6. **严格约束**：必须先检索；仅基于检索结果作答；找不到必须说"未找到"

## 出处呈现

每条回答末尾渲染来源卡片：红色 PDF 徽章 + 文件名 + 蓝色页码徽章 + 2 行 snippet 截断；点击卡片展开完整 snippet。

## 局限性

- 表格只做文本提取，不保留结构
- 数值跨年比较依赖检索同时召回到两个年份的对应字段
- 单文档建议 ≤ 20 MB / ≤ 200 页
- 扫描版/纯图像 PDF 会在解析后被标记 failed（不报错，等用户删除）
- 处理中（status=processing）的文档不支持删除（避免后台 ingestion 与删除竞态）；等 5 分钟超时后会自动 failed，可立即删除

## 项目结构

```
src/         FastAPI 后端
  api/         路由（chat、documents、sse）
  core/        引擎 + 内存服务 + prompt 模板 + tool 注册
  ingest/      PDF 解析 + chunker + ingestion 管线
  tools/       search_documents（V1 唯一 tool）
  llm/         Moonshot K2.6 客户端
  embedding/   BGE-large-zh-v1.5
  db/          SQLAlchemy 异步会话 + alembic
  models/      ORM 模型
frontend/    Next.js 15 前端
docs/        设计文档与实施计划
tests/       单元 + E2E
persona/     助手身份 + 行为准则
scripts/     bootstrap、threshold 校准
```

## 测试

```bash
# 后端单元测试（默认跳过 LLM E2E）
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/docqa \
  uv run pytest tests/unit -q

# E2E（需 MOONSHOT_API_KEY 和 tests/fixtures/example/腾讯2025年度报告.pdf）
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/docqa \
  MOONSHOT_API_KEY=sk-... \
  uv run pytest -m llm tests/e2e -v

# 前端测试
cd frontend && pnpm test
```

## 设计 Mockups

实施前做了 4 个 UI 维度的方案对比（布局 / Citation 卡片 / 上传反馈 / 空状态）。每个维度都有 HTML mockup 展示候选方案，最终选了 D / B / B / B。详见 [`docs/design/`](docs/design/)。

## 截图

参见 [`docs/screenshots/`](docs/screenshots/)：

- `01-empty-state.png` — 空状态引导
- `02-uploading.png` — 解析中（进度条）
- `03-ready.png` — 文档就绪
- `04-answer-with-citation.png` — 回答 + 来源卡片
- `05-no-answer.png` — 文档外问题
- `06-after-restart.png` — 重启后历史保留

## 如果再给一周

- bge-reranker 二次排序提升精度
- 表格 layout-aware 解析（Camelot / unstructured）
- 全局知识库模式（跨会话引用）
- 流式上传 + 大文件支持
- ingestion cancel（处理中可删除，需引入 task 注册表 + 每页轮询 cancel flag）
- 生产 Docker 镜像（当前是 dev-mode）

## 设计文档

- 设计 spec：[docs/superpowers/specs/2026-04-25-doc-qa-design.md](docs/superpowers/specs/2026-04-25-doc-qa-design.md)
- 实施计划：[docs/superpowers/plans/2026-04-25-doc-qa-implementation.md](docs/superpowers/plans/2026-04-25-doc-qa-implementation.md)

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy 2.0 (async) · Alembic |
| 数据库 | PostgreSQL 16 · pgvector |
| LLM | Moonshot K2.6（硅基流动 API） |
| 向量化 | BGE-large-zh-v1.5（1024 维） |
| PDF 解析 | pdfplumber |
| 前端 | Next.js 15 · React 19 · Tailwind 4 · shadcn/ui |
| 测试 | pytest + testcontainers · Vitest |
| 容器 | docker-compose（postgres + backend + frontend） |
