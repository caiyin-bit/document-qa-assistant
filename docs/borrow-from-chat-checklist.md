# 从 chat 工程借鉴到 doc-qa 的功能清单

**日期**: 2026-05-13
**用途**: doc-qa 工程改造为"运营平台智能审核助手"V1 时,需要从姊妹工程 `/Users/jeff/Work/workspace/chat`（保险经纪助手）移植/借鉴的能力清单
**范围**: 仅列借鉴项;不列 doc-qa 自身要新增的业务能力(那些走单独的 V1 spec)

---

## 0. 总览

经过两工程逐文件对比,两边在基础设施层 ~85% 同构。doc-qa 在**异步队列 / 认证 / 重排器 / 文档摄入**上是 chat 的超集。chat 工程值得借鉴到 doc-qa 的能力如下:

| 优先级 | 借鉴项 | chat 源文件 | 工作量 |
|---|---|---|---|
| P0 必需 | RRF 融合的鲁棒性增强 | `src/core/memory_service.py:40-57` | 0.5 天 |
| P0 必需 | Tool Registry 多工具版 + 三层错误兜底 | `src/core/tool_registry.py` | 0.5-1 天 |
| P0 必需 | Persona 双文件分离 + Prompt 工具规则段 | `persona/*.md` + `src/core/prompt_templates.py` | 0.5 天 |
| P0 必需 | 检索评估脚本(baseline + mode×surface 矩阵) | `scripts/eval_retrieval.py` | 1 天 |
| P1 推荐 | `messages.routing` JSONB 审计字段(思路) | `src/db/migrations/versions/0005_messages_routing.py` | 0.5 天 |
| P1 推荐 | 召回工具协议:固定查找 vs 重名澄清 | `src/tools/recall_*.py` | 思路借鉴,无工作量 |
| P2 可选 | Session 摘要压缩 | `src/core/summarizer.py` | 1 天 |
| P2 可选 | Router(instant/thinking) | `src/core/router.py` | 1 天 |

合计 P0+P1 约 **3-4 天**;P2 视 V1 范围决定。

---

## 1. P0 必需借鉴(V1 没有会出问题)

### 1.1 RRF 融合的鲁棒性增强

**doc-qa 现状**: `search_chunks_hybrid` (`src/core/memory_service.py:374-421`) 已经实现 vector + keyword + RRF 融合,基本思路正确。

**问题**: chat 工程在 V2.5.A 实现 RRF 时,经过 17 轮 spec review,沉淀了几个鲁棒性细节,doc-qa 当前实现缺这些:

```python
# chat/src/core/memory_service.py:40-57
def _rrf_fuse_scores(stages: list[list], *, k: int = 60) -> dict[UUID, float]:
    scores: dict[UUID, float] = defaultdict(float)
    for stage in stages:
        seen_in_stage: set[UUID] = set()           # (1) stage 内 dedup
        for rank, row in enumerate(stage, start=1):
            if row.id in seen_in_stage:
                continue                            # 同一 id 同一 stage 只贡献一次最佳排名
            seen_in_stage.add(row.id)
            scores[row.id] += 1.0 / (k + rank)
    return dict(scores)
```

| chat 有 / doc-qa 缺 | 影响 |
|---|---|
| **stage 内 dedup** (`seen_in_stage`) | doc-qa 当前在 chunks 场景下不会出错(chunk_id 天然唯一),但运营场景下扩展到 case_library / policy_documents 时,同一文档分多个 chunk 命中会被重复计分,影响排序 |
| **显式 tiebreak** `sorted(scores, key=lambda i: (-scores[i], i))` | RRF 在分数相等时,doc-qa 当前依赖 Python `sorted` 的隐式行为,顺序不稳定 |
| **多 stage 通用化** (`stages: list[list]`) | doc-qa 当前 hard-code 两个 stage(vector + keyword);运营场景如果加第三路(rerank top + trigram + bm25),需要泛化 |

**落地方式**:
1. 把 `_rrf_fuse_scores` 整段移植到 doc-qa 的 `memory_service.py`
2. 把 `search_chunks_hybrid` 改成调用这个通用 fuse 函数
3. 加显式 tiebreak: `sorted(scores, key=lambda cid: (-scores[cid], cid))`

**验证**: chat 工程 `tests/unit/test_memory_service_hybrid.py` 里的 dedup / tiebreak 测试用例可以直接抄过来改名。

---

### 1.2 Tool Registry 多工具版 + 三层错误兜底

**doc-qa 现状**: `src/core/tool_registry.py` 只有 31 行,为单个 `search_documents` tool 设计,缺多工具的注册/分发/错误隔离机制。

**chat 那版关键点**(`src/core/tool_registry.py`,72 行):

```python
class ToolRegistry:
    def __init__(self, memory, tools: dict[str, tuple[dict, ToolFn]]):
        self._tools = tools                              # name → (schema, fn) 字典

    @classmethod
    def default(cls, memory) -> "ToolRegistry":
        return cls(memory=memory, tools={
            "create_contact": (t_create.SCHEMA, t_create.execute_create_contact),
            "log_follow_up":  (t_follow.SCHEMA, t_follow.execute_log_follow_up),
            # ... 6 个 tool 集中注册
        })

    def schemas(self) -> list[dict]:                     # 直接喂 LLM tools 参数
        return [schema for schema, _ in self._tools.values()]

    async def execute(self, name: str, arguments: dict, context: dict) -> dict:
        entry = self._tools.get(name)
        if not entry:                                    # (1) 未知 tool 兜底
            return {"ok": False, "error": "unknown_tool", "message": f"未知工具 {name}"}
        try:
            return await fn(self._memory, context, arguments)
        except Exception as e:                           # (2) 系统错兜底
            log.exception("tool %s raised", name)
            return {"ok": False, "error": "system", "message": f"内部错误: {e}"}
```

加上每个 tool 函数内部的**业务错兜底**(在 `tools/*.py` 里返回 `{"ok": False, "error": "validation_error", ...}`),构成三层:

| 层 | 兜底位置 | 失败示例 |
|---|---|---|
| 协议错 | ToolRegistry.execute | LLM 调了不存在的 tool 名 |
| 业务错 | tool fn 内部 | 参数校验失败、对象不存在 |
| 系统错 | ToolRegistry.execute 的 try/except | DB 连接断、网络超时 |

**落地方式**: 把 doc-qa 的 `tool_registry.py` 完整替换为 chat 那版结构;`tools/` 目录从单文件改为按 tool 分文件,每个 tool 一个 `SCHEMA` + `execute_xxx` 函数。

---

### 1.3 Persona 双文件分离 + Prompt 工具规则段

**doc-qa 现状**: `persona/` 目录单文件,身份和风格揉在一起。

**chat 那版结构**:
```
persona/
├── IDENTITY.md      # 我是谁 / 我服务谁 / 我的边界
└── SOUL.md          # 我怎么说话 / 性格 / 语气 / 禁忌
```

由 `src/core/persona_loader.py`(25 行)分别加载,在 prompt 中分段渲染:

```python
# 伪代码示意
system_prompt = f"""
{IDENTITY}      # 身份段

{SOUL}          # 风格段

# 工具使用规则
{tool_usage_rules}    # ← prompt_templates.py 里组织的工具规则

# 上下文
{context}
"""
```

**为什么这样切**: 身份变更频率低、需要 spec 评审;风格调整频繁、可以 A/B 实验;工具规则跟着 tool 集合走。三件事强行揉一起后续维护痛。

**落地方式**:
1. doc-qa 的 `persona/` 拆成 `IDENTITY.md` + `SOUL.md`
2. 把 `prompt_templates.py` 里的工具调用规则段(参考 chat 工程 `src/core/prompt_templates.py` 的 system prompt 渲染)抽出来
3. 运营审核场景 V1 的 IDENTITY 草稿: "你是内容审核专家,帮审核员看具体内容并给出'通过/拒绝/打标'建议,引用相关政策条款。你不替人下判断,只给依据。"

---

### 1.4 检索评估脚本(baseline + mode×surface 矩阵)

**doc-qa 现状**: 检索质量靠 dev 手工抽测,没有可重复的 baseline。

**chat 那版**: `scripts/eval_retrieval.py` + `tests/fixtures/` 下的 YAML fixture。能力:

- 跑 `vector × trigram × hybrid` 三种 mode
- 跑 `prefetch × tool` 两种 surface(直接检索 vs 走 LLM tool-call)
- 输出 JSON baseline,横向对比 recall@k / mrr
- 用法:
  ```bash
  python scripts/eval_retrieval.py --mode all --surface all --json baseline.json
  ```

**为什么 V1 就要**: 运营助手 V1 最值钱的能力是"政策 RAG + 案例召回",没基线就调不动 prompt / 阈值 / 切分粒度。早做早受益。

**落地方式**:
1. 整段移植 `scripts/eval_retrieval.py`,改实体名(`contacts`→`policy_documents`/`case_library`)
2. fixture YAML 格式照搬(`tests/fixtures/retrieval_eval.yaml`)
3. 用 50 条 mock 内容 + 20 条政策片段做第一份 baseline,记入 V1 spec

---

## 2. P1 推荐借鉴(V1 早晚要做,先做更好)

### 2.1 `messages.routing` JSONB 字段思路

**chat 那版**(`src/db/migrations/versions/0005_messages_routing.py`): `messages` 表加一列 `routing JSONB`,每条 assistant 消息把"AI 的决策上下文"(本轮选了哪个模式、为什么、用了哪些 tool 中间步骤)落库。

**为什么运营场景特别需要**: 审核场景下,"AI 为什么建议拒绝这条"是高频被问的问题。把判断链路落库:
```json
{
  "decision": "reject",
  "confidence": 0.87,
  "policy_hits": ["policy_doc:xxx#§3.2", "policy_doc:yyy#§1.5"],
  "similar_cases": ["case:aaa", "case:bbb"],
  "reasoning_summary": "...",
  "tools_used": ["search_policy", "recall_similar_cases"]
}
```

后续做 AI 准确率回测、误判分析、合规审计都靠这个字段。

**落地方式**: doc-qa 已有 `messages.citations` 字段,把 routing 字段加上去就行;一个迁移搞定。

---

### 2.2 召回工具协议:固定查找 vs 重名澄清

**chat 那版**(V2.5.A 引入): 两个召回工具区别明显:

| Tool | 协议特点 | 何时用 |
|---|---|---|
| `recall_contact` | 必返回 ≤1 条最相关或空 | 已知是哪个客户,直接查 |
| `recall_follow_up` | 重名时返回 **candidates 列表**让 LLM 跟用户澄清,下一轮带 `contact_id` 闭环 | 模糊查找,可能有歧义 |

**运营场景类比**:
- `search_policy(query)` → 返回最相关 N 条政策片段(类似 `recall_contact` 的固定查找)
- `recall_similar_cases(content_summary, candidates_threshold=...)` → 多条疑似相似案例,LLM 决定要不要让用户澄清(类似 `recall_follow_up`)

**借鉴的是协议设计思路,不是代码**。chat 工程 `src/tools/recall_follow_up.py` 的 candidates 返回格式可以参考。

---

## 3. P2 可选借鉴(V1 不一定做)

### 3.1 Session 摘要压缩

**chat 那版**: `src/core/summarizer.py`(103 行) + `sessions.summary` / `summary_until_message_id` 字段。长会话超过 60% token 上限时,LLM 自己生成"对话至此关键信息"摘要,放进 system prompt,旧消息折叠。

**doc-qa 现状**: 已经有 `sessions.summary` 和 `summary_until_message_id` 字段(`schemas.py:48-49`),但**没有 summarizer 模块**。表已建好,代码没写。

**V1 评估**: 审核场景单会话通常短(几轮就出结论),压缩需求不强。**V1 不做,留 V2**。

---

### 3.2 Router(instant/thinking)

**chat 那版**: `src/core/router.py`(106 行)。每轮对话前先用便宜模型判断"这个问题要不要切 thinking 模式",路由决策落 `messages.routing`。

**V1 评估**: 审核场景大多数判断是"看一条内容→给建议",thinking 模式 ROI 不明确。**V1 不做**。

---

## 4. 不建议借鉴

| chat 有 | 为什么不借鉴 |
|---|---|
| 6 个保险业务 tool(`create_contact` / `log_follow_up` / `recall_contact` / `recall_follow_up` / `complete_todo` / `update_user_profile`) | 业务语义完全不同,运营场景重写 |
| `user_profiles` 表(经纪人画像) | V1 不需要"运营人员画像";V2 如要做,先想清楚需要画像哪些维度,再实现 |
| `contacts` / `follow_ups` / `todos` 表 | 保险语义,运营场景用 `audit_objects` / `audit_records` / `case_library` 替代 |
| `persona/SOUL.md` 里"陪客户聊天"的语气 | 审核场景要"专业克制",风格完全不同,重写 |

---

## 5. 反向提示:doc-qa 已经比 chat 强的地方(不要重新发明)

借鉴时记得 doc-qa 这边已经领先 chat 的能力,**不要被 chat 工程的代码风格带歪反向移植**:

| doc-qa 有 / chat 没有 | 位置 | 运营 V1 直接复用 |
|---|---|---|
| arq + Redis 异步任务队列 | `src/worker/` | 政策文档批量导入、案例库写入异步化 |
| BGE async embedder(`ThreadPoolExecutor`) | `src/embedding/bge_embedder.py` | 不阻塞 event loop |
| BGE cross-encoder reranker | `src/embedding/bge_reranker.py` | 政策 RAG 的二次重排,准确率关键 |
| 用户注册/登录/cookie session | `src/api/auth.py` | 运营人员账号体系 |
| PDF 摄入流水线(parser + chunker + zh_normalize) | `src/ingest/` | Wiki/PDF 政策文档导入 |
| `messages.citations` JSONB 字段 | `src/models/schemas.py:60` | "引用 §3.2 政策"刚需 |
| 前端 PDF viewer + Citation card | `frontend/components/` | 政策原文跳读 |
| `documents` + `document_chunks` 表设计 | `src/models/schemas.py:64-117` | 重命名为 `policy_documents` 后沿用 |
| 卡住任务的 reaper | `src/api/reaper.py` | 导入任务异常恢复 |

---

## 6. 建议执行顺序(在 V1 改造里的位置)

如果同意按"在 doc-qa 工程上原地改造为运营助手 V1"路线走,本清单的执行时机:

```
V1 改造阶段 1 — 剥 doc-qa 业务壳            3-5 天
  并行执行: 借鉴项 1.3(Persona 重构)

V1 改造阶段 2 — 移植 chat 关键能力         2-3 天
  ├─ 借鉴项 1.1: RRF 鲁棒性增强            0.5 天
  ├─ 借鉴项 1.2: Tool Registry 多工具版    0.5-1 天
  └─ 借鉴项 1.4: eval_retrieval 评估脚本   1 天

V1 改造阶段 3 — 业务建模 + 4 个审核 tool   5-7 天
  并行执行: 借鉴项 2.1(routing JSONB 字段)
  参考思路: 借鉴项 2.2(召回工具协议)

V1 改造阶段 4 — 前端调整                   5-7 天

V1 改造阶段 5 — e2e + demo                 3-5 天

总计: 4-5 周到 V1 demo
```

---

## 7. 一句话总结

doc-qa 在基础设施层已经是 chat 的超集。从 chat 借鉴的不是"功能",是 chat 工程在 V2.5.A 里沉淀的**鲁棒性细节**(RRF dedup/tiebreak)、**结构化模式**(多工具注册 + 三层错误兜底 + persona 双文件 + 评估脚本)和**审计思路**(routing 字段)。合计 P0+P1 约 3-4 天工作量,但拦住的是后续改造里最容易踩的坑。
