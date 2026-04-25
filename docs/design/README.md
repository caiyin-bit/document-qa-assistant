# UI 设计方案 (mockups)

设计阶段对 4 个关键交互维度做了多方案对比，每个方案以 HTML mockup 呈现。最终的实施按下面"选了"列落地。

| 文件 | 主题 | 候选 | 选了 |
|---|---|---|---|
| [`layout.html`](layout.html) | 整体布局：文档列表 + 上传放在哪？ | A 左侧栏底部 / B 聊天面板顶部横条 / C 三栏 / D 空状态居中 + 传后切顶部栏 | **D** |
| [`citation.html`](citation.html) | Citation 来源卡片样式 | A 极简 chip / B 卡片式 + snippet 预览 / C 折叠面板 | **B** |
| [`upload-states.html`](upload-states.html) | 上传交互 + 状态反馈方案 | A 仅徽章 / B 进度条 + 步骤文案 / C 大型 spinner | **B** |
| [`empty-state.html`](empty-state.html) | 新会话空状态文案 | A 极简 / B 引导式 / C 引导 + 示例问题 | **B** |

## 离线查看

mockup 是纯 HTML + 共享 `_frame.css`。直接在浏览器打开任一 `.html` 即可：

```bash
open docs/design/layout.html
# 或
python -m http.server -d docs/design 8765
# 然后访问 http://localhost:8765/layout.html
```

## 选择理由（摘要，详见 spec §8）

### Q1 — 布局：D 模式
- 新会话首屏即引导上传，演示故事最强
- 已上传后自动切回顶部横条（"B 模式"），把屏幕高度让给对话流
- 比单独 A/B/C 多一步状态切换，但用户路径最自然

### Q2 — Citation：卡片式 + snippet 预览
- 红色 PDF 徽章 + 文件名 + 蓝色页码徽章 + 2 行 snippet
- 评审第一印象"答案有据可查"
- LLM 不需要产出特定引用语法（最稳定）；前端按结构化信号渲染

### Q3 — 上传反馈：进度条 + 步骤文案
- "正在向量化第 45 / 89 页…"让用户对系统有信任感
- 黄色 / 绿色 / 红色 row 三态视觉 + 删除按钮
- 失败态明确"请删除后重新上传"（不留 retry 路径以避免与 ingestion cancel 耦合）

### Q4 — 空状态：引导式
- 标题 + 副标题 + 强化拖拽区
- 不放示例问题（demo 时如果文档不匹配会很尴尬）
- "拖入 PDF 或点击上传 · 支持中文 · ≤20MB · 可上传多份"

## 实施落地位置

| 设计文件 | 对应实现 |
|---|---|
| `layout.html` (D) | [frontend/components/chat-pane.tsx](../../frontend/components/chat-pane.tsx) — `hasAny ? <DocumentTopBar/> : <DocumentUploadHero/>` |
| `citation.html` (B) | [frontend/components/citation-card.tsx](../../frontend/components/citation-card.tsx) |
| `upload-states.html` (B) | [frontend/components/document-row.tsx](../../frontend/components/document-row.tsx) — 三态 row + 进度条 |
| `empty-state.html` (B) | [frontend/components/document-upload-hero.tsx](../../frontend/components/document-upload-hero.tsx) |

## 设计-到-实施 的对照

实施后的真实截图见 [`../screenshots/`](../screenshots/)（最终交付前补齐 6 张）。
