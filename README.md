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

# Auth
SESSION_SECRET=<32-byte 随机串>   # 生产必须;dev 不设会用一个有警告的默认值
ALLOW_DEMO_LOGIN=true            # 默认 true,localhost 不登录也能用 demo 用户;生产请设 false
```

---

## 注册 / 登录 / 多用户

cookie-based session(starlette SessionMiddleware,签名 cookie / HttpOnly / SameSite=lax / 7 天 TTL),密码用 argon2 哈希。

**两种使用模式:**

| 模式 | 触发 | 行为 |
|---|---|---|
| **demo 模式** | `ALLOW_DEMO_LOGIN=true`(默认)且未登录 | 自动 fall back 到 `demo@example.com`,不需要注册;sidebar 底部显示"demo 模式"标签 |
| **真实账号** | 注册或登录后 | 文档/会话归属当前用户,sidebar 显示真名 + 退出按钮;cookie 失效 → 跳 `/login` |

**默认账号(开箱即登录):**

| email | password |
|---|---|
| `demo@example.com` | `demo` |

`scripts/seed_demo_user.py` 在 docker compose 启动时自动跑,确保这个账号一直存在。**生产环境请删除或改密码。**

**注册流程:**
1. 浏览器打开 [/register](http://localhost:3000/register),输入邮箱 + 密码(≥6 位)+ 可选昵称 → 自动登录 → 跳回主页
2. sidebar 底部出现真名 + 邮箱 tooltip,点退出按钮即清 cookie

**API endpoints:**
- `POST /auth/register` — body `{email, password, name?}`,返回 `{user_id, email, name, is_demo}` + 设置 session cookie
- `POST /auth/login` — body `{email, password}`,同上
- `POST /auth/logout` — 清 session
- `GET /auth/me` — 读当前用户;未登录且 demo 关闭时返回 401

**多租户隔离:** 每个文档/会话挂在 `user_id` 上,所有路由通过 `Depends(require_user)` 限定当前用户的资源。一个用户看不到另一个用户的会话或文档。

> 生产部署清单:`SESSION_SECRET` 设强随机 + `ALLOW_DEMO_LOGIN=false` + docker-compose 把 `https_only=True` 打开 + `CORSMiddleware` 收紧 origin 列表。

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

## 答案格式(图表 / 表格)

LLM 在合适时机可以**直接在回答里嵌入图表**,前端基于 [xviz](https://github.com/caiyin-bit/xviz)(Apache Superset 图表引擎的独立版,内核 ECharts)渲染,**v0.5.0 共 19 种类型**:

| 类型 | 适用场景 |
|---|---|
| `pie` / `donut` | 占比(各业务板块收入占比) |
| `bar` | 分组对比、同比 |
| `line` / `step` | 趋势(近 5 年营收 / 阶梯状态变化) |
| `big-number` | KPI 卡片(大数 + sparkline + 同比) |
| **`waterfall`** | **利润分解(总收入→成本→费用→净利润),比 funnel 更专业** |
| `funnel` | 转化漏斗(递减) |
| `sankey` | 流向(总收入→各业务板块) |
| `heatmap` | 二维矩阵(各板块 × 各季度同比) |
| `treemap` / `sunburst` | 多层级占比(地区 × 国家;rectangle 或 ring 形式) |
| `radar` | 多维度对比(板块在 增长率/毛利率/份额 多轴上的画像) |
| `boxplot` / `histogram` | 分布(多季度数据的离散程度 / 分箱) |
| `table` | 多行多列数据 |
| `gauge` | 单值仪表 |
| `scatter` | 散点(相关性) |
| `tree` / `graph` | 层级树 / 关系网络 |

**LLM 输出协议:** system prompt 教 LLM 在答案中插入 ```` ```chart ```` 代码块,JSON 形如:
```json
{"vizType":"bar","title":"...","xAxis":"name","metrics":["v2024","v2025"],"data":[{"name":"增值服务","v2024":313,"v2025":369}, ...]}
```
前端 markdown 渲染器拦截这个代码块 → 懒加载 xviz + ECharts → 渲染图表。echarts(~250KB gzip)是 lazy import,**没图表的对话不付下载代价**。

**触发示例(腾讯年报):**

| 提问 | 期望渲染 |
|---|---|
| "用饼图展示腾讯 2025 年各业务板块收入占比" | donut 图,4 个板块 |
| "对比 2024 vs 2025 各板块收入" | 双 series 柱状图 |
| "用折线图展示近 5 年总收入" | 单 series 平滑折线 + 渐变填充 |
| "用 KPI 卡片展示 2025 总收入,带同比" | BigNumber + sparkline + +12.7% delta |
| "用瀑布图展示从总收入到净利润的逐项扣减" | **Waterfall**:绿色为正、红色为负、终点 Total 条 |
| "用漏斗图展示从总收入到净利润" | 4 层倒梯形(等价但 Waterfall 更细) |
| "用 Sankey 图展示总收入流向" | 流向带 |
| "用 Radar 图对比各板块的增长率/毛利率/份额" | 多轴雷达图 |
| "用 Treemap 展示按业务板块和地区的收入" | 多层矩形拼贴 |

**单点事实(如"总收入是多少")模型不会强加图表,直接给文字答案 + 引用页码。**

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
| **xviz / ECharts 渲染图表** | 视觉级别和图表种类(Sankey / Funnel / BigNumber)直追 BI 产品;代价是 echarts ~250KB gzip,但用 `React.lazy` 拆出独立 chunk,无图表答案不付费 |
| **cookie session + argon2** | 比 JWT 简单(可服务端撤销),无需 Redis;代价是 `SESSION_SECRET` 一旦泄漏所有 cookie 都得轮换 |
| **`ALLOW_DEMO_LOGIN` 默认开** | localhost 体验不被注册流程打断;**生产必须关掉**否则任何匿名访问都映射到 demo 用户 |
| **没做 PII 脱敏** | 文档内容直接存 DB / 喂 LLM;不适合敏感数据 |

---

## 如果再给两周

按 ROI 排:

1. **prompt injection 防护**:PDF 内容用分隔符 + 重申"仅作引用"包起来;现在容易被恶意 PDF 操控
2. **多文档对比** RAG:跨文档召回 + 结构化输出(表格对比同期数据)
3. **结构化指标提取**:财报场景预提取营收/毛利/费用率等常见维度,做卡片直观展示
4. **HNSW 替换 ivfflat** + **分词 BM25**:大规模索引下召回质量
5. **认证生态完善**:邮箱验证、找回密码、OAuth(Google/微信),会话强制下线列表(目前 cookie 是 stateless 签名)
6. **生产 Docker 镜像**:多阶段 build / 非 root user / health check / Tini PID 1 / k8s manifest
7. **Prometheus metrics**:LLM 时延 / 召回数 / 重排时延 / token 用量
8. **流式 PDF 上传 + 大文件分片**:当前 20MB 上限是单次内存读
9. **移动端体验**:hamburger 菜单 + 触摸优化(目前只做了基础响应式)
10. **e2e 测试覆盖 chat 路径 + auth 路径**:目前只有 ingestion 的 e2e

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
| 图表 | xviz(@minimal-viz/core)+ ECharts 6,React.lazy 拆 chunk |
| 容器 | docker-compose(postgres + redis + backend + worker + frontend) |
