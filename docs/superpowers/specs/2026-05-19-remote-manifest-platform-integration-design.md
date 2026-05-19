# 远程 Manifest 驱动的平台自主接入 — 设计

**Status:** Approved (brainstorming) — 待用户复核后转实现计划
**Date:** 2026-05-19

## Goal

让本系统能通过读取一份远程 `.md`(内含结构化接入清单),由面向用户的聊天 agent **自主发现**接入参数、经**关键步骤人工确认(HITL)自主申请配对码**,并由独立长驻 worker 与外部平台维持**全双向持久连接**。

参照场景:类似 BotLearn 那种"把一句话发给 Agent → Agent 读 SKILL.md → 返回 claim 链接 → 用户点开完成校验"的接入流程。**BotLearn 仅为举例(example),不进契约、不进代码。**

## Locked Decisions

1. **执行主体:** 复用现有用户聊天 agent loop(`src/core/conversation_engine.py`)做发现 + HITL 申请;持久连接因聊天 loop 是请求级、销毁于请求结束,**架构上必须**置于独立长驻 worker。
2. **自主程度:** 关键步骤 HITL —— 发出外部注册请求这一步必须用户确认。
3. **终点:** 全双向持久连接(心跳 / token 刷新 / 受控入站命令)。
4. **范围:** 单一 spec,含持久连接(不拆子项目)。
5. **驱动方式:** 方案 A —— 结构化清单契约;散文不参与控制流。
6. **触发权限:** 管理员 / 运维专属,不开放给普通租户用户。理由:把整个系统注册进外部平台并对外开持久双向通道属系统级行为,多租户中任一普通用户都不应能执行。
7. **平台中立:** 契约标识与代码中不出现任何平台专名;平台名为对端 `.md` 自填的展示/日志字段。
8. **Admin 角色为前置依赖:** 现 `src/api/auth.py` 仅有普通 user + demo,无 admin 概念。本设计前置依赖一个最小 admin 标记(如 `User.is_admin` 布尔列 + 迁移 + `require_admin` 依赖),作为实现计划的第一项任务。

## Architecture

```
聊天 loop(请求级, conversation_engine)     独立长驻 worker(非请求路径)
┌──────────────────────────────┐          ┌──────────────────────────────┐
│ tool: fetch_manifest         │          │ integration_connector         │
│ tool: request_pairing_code   │          │  - 按 manifest 开持久连接     │
│   (side-effecting, HITL 闸门) │          │  - 心跳 / 重连 / token 刷新   │
│ admin-only 可见可执行        │          │  - 入站命令(白名单强制)      │
└───────────────┬──────────────┘          └───────────────┬──────────────┘
                │                                          │
                ▼                                          ▼
        platform_integration 表(凭证密文 + manifest 快照 + 状态机)
                ▲
        safe_fetch(SSRF 防护,manifest 拉取与 connector 共用)
```

聊天 loop 负责发现 + HITL 申请配对码 + 落库;`integration_connector` 接管持久连接。两者通过 `platform_integration` 表状态机解耦。

## Component: Manifest 契约(方案 A 核心)

远程 `.md` 必须含一段 fenced 块 ` ```agent-integration `(契约固定标识,平台无关),YAML 内容,经严格 pydantic 校验:

```yaml
version: 1
platform: BotLearn          # 自由字段,仅 HITL 摘要与日志用;换平台即换值,不参与逻辑分支
register:                   # 申请配对码端点
  method: POST
  url: https://api.example.com/agents/register
  body_schema: {...}        # 声明式;引擎据此构造请求体
connection:                 # 持久连接规格
  transport: websocket      # websocket | sse | poll
  url: wss://api.example.com/agent/stream
  heartbeat_seconds: 30
  token_refresh_url: https://api.example.com/agents/token
inbound_capabilities:       # 平台被允许下推的命令类型;默认全拒
  - ping
  - request_status
```

规则:
- 散文部分**不参与控制流**,仅在 HITL 闸门渲染人类可读摘要。
- 未知的副作用字段、非 https、host 不在管理员配置的白名单 → 拒绝并终止,不落库。
- 校验通过的 manifest 原文快照随 integration 行一并存储(用于审计与 connector)。

## Component: 聊天 loop 工具与 HITL 机制

新增两个工具,注册进 `src/core/tool_registry.py`,**仅对带 admin 标记的用户会话可见可执行**(`tool_registry.execute` 增加角色校验)。

- `fetch_manifest(url)`:经 `safe_fetch` 拉取 → 提取并校验 manifest → 落一行 `status=draft` → 返回结构化摘要(无副作用)。
- `request_pairing_code(integration_id)`:**side-effecting**,走 HITL 闸门。

HITL 对现有引擎的改动:现引擎自动执行工具(`conversation_engine.py:189-215`)。新增**工具副作用分级**:side-effecting 工具不直接执行,引擎产出 `confirmation_required` 流事件(人类摘要 + pending-action token;token 绑定 `session_id` + `integration_id` + manifest 哈希,短 TTL),本轮结束。前端渲染确认/拒绝。用户确认后携 token 续发请求,引擎校验 token 后执行注册。拒绝/超时 → 丢弃,`status` 保持 `draft`。

## Data Flow(贴合参照场景)

1. 管理员在聊天里:`接入 X 平台: https://.../SKILL.md`
2. LLM 调 `fetch_manifest(url)` → `safe_fetch` 拉取 → 校验 manifest → `status=draft` 落库 → 返回摘要
3. LLM 调 `request_pairing_code(id)` → 引擎识别 side-effecting → 发 `confirmation_required`(摘要含:平台名、注册端点、声明的入站能力、连接目标)→ 本轮暂停
4. 用户前端确认 → 携批准 token 续发 → 引擎按 manifest 调 register 端点 → 拿到配对码/claim 链接 → 密文落库,`status=active` → 工具返回 claim 链接 → LLM 展示给用户(= 参照场景终点)
5. 后台 `integration_connector` 轮询到 `active` 行 → 开持久连接 → 心跳 / 刷 token / 受控入站

## Data Model

新增表 `platform_integration`:
- `id` (uuid, pk)
- `platform_name` (text,来自 manifest 自由字段,仅展示)
- `manifest_snapshot` (jsonb,校验通过的 manifest 原文)
- `status` (enum: `draft` | `active` | `degraded` | `disabled`)
- `created_by` (uuid fk → user;须为 admin)
- `pairing_secret_ciphertext` (bytea,配对码/token 密文)
- `token_refresh_meta` (jsonb,过期时间等)
- `created_at` / `updated_at`

凭证用独立密钥 `INTEGRATION_SECRET`(区别于 `SESSION_SECRET`)按行加密。Alembic 迁移新增此表(沿用 `src/db/migrations/versions/` 序号)。

## Security Model(方案真正的核心)

- **`safe_fetch`**(新增共用工具):仅 https;host 必须在管理员配置的平台白名单;解析 DNS 后拒绝私网 / 环回 / 链路本地 / CGNAT / 元数据(169.254.169.254)等地址;不跟随跳出白名单的重定向;超时 + 响应体大小上限。manifest 拉取与 connector 共用。
- **凭证存储:** 独立密钥按行加密,见 Data Model。
- **入站命令(双向连接的风险面):** 默认全拒;仅接受 manifest `inbound_capabilities` 显式声明、且引擎内置固定 handler 存在的命令类型;每条入站消息走严格 schema 校验;handler 集合极小、能力最小化,**不可触达任何租户文档、不可执行任意代码**;全量审计日志。
- **熔断开关:** 管理员可一键将 integration 置 `disabled` → worker 立即断连并停止 token 刷新。
- **触发权限:** admin-only,见 Locked Decisions #6。

## Error Handling

| 场景 | 处理 |
|---|---|
| 拉取失败 / manifest 非法 / host 不在白名单 | 工具返回错误,不落库 |
| register 非 2xx | 报错,保持 `draft` |
| 确认超时 / 用户拒绝 | 丢弃 pending action,保持 `draft` |
| 连接断开 | 指数退避重连 |
| token 刷新失败 | 标记 `degraded` 并告警 |
| 白名单移除运行中 integration | 下次心跳断连 |

## Testing Strategy

- **单元:** manifest schema(合法 / 非法 / 含恶意副作用字段);`safe_fetch` 各类 SSRF 地址;凭证加解密往返;HITL token 绑定与 TTL。
- **集成(mock 平台 server):** 完整 onboard happy path;HITL 拒绝路径;register 失败路径。
- **connector(mock ws server):** 心跳;断线重连;token 刷新;入站命令白名单强制;熔断开关。
- **安全用例:** 私网 IP;跳出白名单的重定向;超大 `.md`;散文注入被忽略(prose 不影响控制流);非白名单 host;未声明的入站命令被拒;非 admin 用户工具不可见 / 不可执行。

## Out of Scope

- 每用户各自接入(本设计为系统级 admin-only)。
- 多平台并发连接的调度优化(先支持 N 条独立 integration,不做跨平台编排)。
- 平台侧的注册/连接协议实现(由对端 manifest 描述,本系统仅按声明对接)。
