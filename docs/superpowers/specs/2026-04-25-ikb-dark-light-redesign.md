# IKB Klein Blue + Dark/Light Redesign — Design Spec

**Date**: 2026-04-25
**Status**: Approved (brainstorm gate passed)
**Mockups**: [pencil-redesign.pen](../../design/pencil-redesign.pen) — frames "DocQA Workspace (Dark)" (id `NV2a2`) and "DocQA Workspace (Light)" (id `ZPXaF`)

---

## 1. Goal

Replace the current "Apple/shadcn neutral" frontend look with a token-driven Klein-Blue / dev-tool aesthetic, and add a runtime light/dark theme toggle.

**Why**: User feedback "页面太素" (too plain). The current palette mixes indigo/gray/amber/green/red without a strong identity. The redesign picks **International Klein Blue (#002FA7)** as the singular accent, applied on top of a black-or-white surface system. The result reads as a serious, "institutional" tool (Bloomberg/Linear-light) rather than a generic chat UI.

---

## 2. Color Tokens (canonical)

All colors below are referenced as CSS custom properties (`--token-name`). The redesign introduces **two complete token sets** that swap based on `[data-theme="dark"]` vs `[data-theme="light"]` on `<html>`.

| Token | Dark | Light | Used by |
|---|---|---|---|
| `--bg` | `#0A0A0A` | `#FFFFFF` | `<body>`, ChatPane, doc card frames |
| `--bg-sidebar` | `#0E0E0E` | `#FAFAFA` | SessionsSidebar |
| `--bg-docs` | `#0B0B0B` | `#F8F8F8` | DocumentSidebar |
| `--surface-elevated` | `#141414` | `#F4F4F5` | assistant message bubble, theme toggle |
| `--surface-input` | `#0F0F0F` | `#FFFFFF` | chat input textarea |
| `--border-subtle` | `#1F1F1F` | `#E4E4E7` | doc card border, citation card border, asst bubble border |
| `--border-divider` | `#1A1A1A` | `#E4E4E7` | sidebar right edges |
| `--text-primary` | `#E4E4E7` | `#18181B` | message body, doc filenames |
| `--text-secondary` | `#A1A1AA` | `#52525B` | non-active session titles, snippet text |
| `--text-tertiary` | `#71717A` | `#71717A` | section labels, page-count meta |
| `--text-faint` | `#52525B` | `#A1A1AA` | timestamp captions on inactive sessions |
| `--accent` (IKB) | `#002FA7` | `#002FA7` | "+ 新对话" button, user bubble, send button — same in both themes |
| `--accent-bg` | `#001A4A` | `#DBEAFE` | active session card background, citation page badge background |
| `--accent-bg-dim` | `#00103D` | `#EFF6FF` | tool chip background, upload card background |
| `--accent-border` | `#1E3A8A` | `#BFDBFE` | active session card border, citation page badge border, upload card dashed border |
| `--accent-text-bright` | `#6FA1F0` | `#002FA7` | tool chip icon + text |
| `--accent-text-light` | `#93C5FD` | `#002FA7` | citation `p.NN` text, upload card title |
| `--status-ok-bg` | `#0A2118` | `#DCFCE7` | READY pill bg |
| `--status-ok-fg` | `#22C55E` | `#16A34A` | READY pill text + dot |
| `--status-warn-bg` | `#2A1A02` | `#FEF3C7` | PROCESSING pill bg, progress bar track |
| `--status-warn-fg` | `#F59E0B` | `#B45309` | PROCESSING pill text + dot, progress bar fill |
| `--status-err-bg` | `#2A0E11` | `#FEE2E2` | FAILED pill bg |
| `--status-err-fg` | `#EF4444` | `#DC2626` | FAILED pill text + dot, error message text |
| `--status-warn-card-border` | `#3F2A0E` | `#FCD34D` | PROCESSING doc card stroke |
| `--status-err-card-border` | `#3F0E1A` | `#FCA5A5` | FAILED doc card stroke |
| `--pdf-badge-bg` | `#DC2626` | `#DC2626` | PDF document-type badge — same red in both themes |
| `--pdf-badge-fg` | `#FFFFFF` | `#FFFFFF` | "PDF" text on badge |

**Typography**:
- `--font-sans`: `Geist, -apple-system, system-ui, sans-serif` — body, headings, button labels, message bubbles
- `--font-mono`: `'Geist Mono', 'JetBrains Mono', ui-monospace, monospace` — section labels (uppercase 10px), tool chips, status pills, citations, page counts, timestamps, theme toggle

Pixel sizes used in mockup: 9 / 10 / 11 / 12 / 13 / 14. Letter spacing 0.8 on uppercase mono labels.

---

## 3. Theme Infrastructure

### 3.1 CSS variables in `frontend/app/globals.css`

Add a single block at the top of the file:

```css
:root, [data-theme="light"] {
  --bg: #FFFFFF;
  --bg-sidebar: #FAFAFA;
  /* ... full light token set ... */
}

[data-theme="dark"] {
  --bg: #0A0A0A;
  --bg-sidebar: #0E0E0E;
  /* ... full dark token set ... */
}
```

`:root` defaults to light so server-rendered HTML never flashes black before client hydration. The actual chosen theme overwrites via `[data-theme="dark"]` set on `<html>` by the theme provider.

### 3.2 `frontend/lib/use-theme.ts` (new)

```ts
type Theme = "dark" | "light";
const KEY = "docqa.theme";

export function readStoredTheme(): Theme | null { /* localStorage.getItem(KEY) validated */ }
export function applyTheme(theme: Theme) { document.documentElement.dataset.theme = theme }
export function useTheme(): { theme: Theme; toggle: () => void } { /* useState + useEffect to apply + persist */ }
```

**Resolution order on first load**:
1. `localStorage.docqa.theme` if set to `"dark" | "light"`
2. `window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"`
3. Default `"dark"` (the IKB-on-black is the visual identity; this matches the brand intent)

### 3.3 Anti-FOUC inline script in `frontend/app/layout.tsx`

Insert a `<script>` tag in `<head>` that runs before React hydrates:

```html
<script dangerouslySetInnerHTML={{__html: `
  try {
    const t = localStorage.getItem('docqa.theme') ||
              (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.dataset.theme = t;
  } catch {}
`}} />
```

Without this, the page paints with `:root` light tokens and flashes when React applies the dark dataset. The 6-line script eliminates the flash.

### 3.4 `frontend/components/theme-toggle.tsx` (new)

A small mono-styled pill placed in `SessionsSidebar` footer. Shows current theme + icon, click toggles:

- Dark state: `🌙 (Moon)` icon + `深色 · DARK` label, `--accent-text-light` color
- Light state: `☀️ (Sun)` icon + `浅色 · LIGHT` label, `--accent` color

Uses `lucide-react`'s `Moon` and `Sun`.

---

## 4. Component-by-component Changes

All seven existing components migrate from hardcoded Tailwind colors to `var(--token)` references. Layout dimensions unchanged.

| Component | Key changes |
|---|---|
| [`app/globals.css`](../../../frontend/app/globals.css) | Add `:root` + `[data-theme="dark"]` variable blocks (token table §2) |
| [`app/layout.tsx`](../../../frontend/app/layout.tsx) | Add anti-FOUC inline script in `<head>`; default `<html data-theme="light">` |
| [`components/sessions-sidebar.tsx`](../../../frontend/components/sessions-sidebar.tsx) | Bg `var(--bg-sidebar)`, right border `var(--border-divider)`. "+ 新对话" button: bg `var(--accent)` + white text. Active session: bg `var(--accent-bg)` + border `var(--accent-border)` + text `var(--text-primary)`. Inactive sessions: text `var(--text-secondary)`. Section label "会话 · SESSIONS" uppercase mono `var(--text-tertiary)`. **New footer** holding `<ThemeToggle />`. |
| [`components/document-sidebar.tsx`](../../../frontend/components/document-sidebar.tsx) | Bg `var(--bg-docs)`, right border `var(--border-divider)`. Header label "文档 · DOCUMENTS" mono. Upload card at bottom: bg `var(--accent-bg-dim)` + dashed border `var(--accent-border)` + IKB icon/title. |
| [`components/document-row.tsx`](../../../frontend/components/document-row.tsx) | Three states map to status tokens: `ready`/`processing`/`failed` use `--status-{ok,warn,err}-{bg,fg}` for pill + dot, `--status-{warn,err}-card-border` for card stroke in non-ready states. Filename `var(--text-primary)`. Page count + status meta `var(--text-tertiary)` / status-fg color. PDF badge: bg `var(--pdf-badge-bg)` + text `var(--pdf-badge-fg)`. |
| [`components/chat-pane.tsx`](../../../frontend/components/chat-pane.tsx) | Bg `var(--bg)`. Input wrapper bg `var(--surface-input)` + border `var(--border-subtle)`, focus ring `var(--accent)`. Send button bg `var(--accent)` + white text. |
| [`components/message-bubble.tsx`](../../../frontend/components/message-bubble.tsx) | User bubble: bg `var(--accent)` + white text + `rounded-[16px_16px_4px_16px]`. Assistant bubble: bg `var(--surface-elevated)` + border `var(--border-subtle)` + text `var(--text-primary)` + `rounded-[16px_16px_16px_4px]`. |
| [`components/citation-card.tsx`](../../../frontend/components/citation-card.tsx) | Section label "📚 来源 · CITATIONS (N)" mono. Cards: bg `var(--bg)` + border `var(--border-subtle)`. PDF badge same. Filename `var(--text-primary)`. Snippet `var(--text-secondary)` mono 10px. Page badge: bg `var(--accent-bg)` + border `var(--accent-border)` + text `var(--accent-text-light)` mono. |
| [`components/home.tsx`](../../../frontend/components/home.tsx) | Outer `<main>` bg `var(--bg)`. (No structural change.) |

### 4.1 Tool-call visual indicator

The mockup shows an explicit "tool chip" inside assistant bubbles when `search_documents` ran — small pill with `lucide:search` icon + monospace text "search_documents · 8 chunks". This is **already present in data flow** (`useChatStream` accumulates `tools[]` per message via SSE `tool_call_started/finished` events) but the current `MessageBubble` doesn't render it. The redesign adds rendering for `message.tools` above the body text in assistant bubbles, styled with `--accent-bg-dim` / `--accent-border` / `--accent-text-bright` tokens.

---

## 5. Out of Scope

- **System-preference change while running**: First load reads `prefers-color-scheme`, but we do NOT subscribe to changes. User explicitly toggles via the pill after that. (Adds complexity for marginal value.)
- **Per-session theme**: Theme is global per-user, persisted in `localStorage`. No per-session override.
- **Animation between themes**: A simple CSS-variable swap is instant. Cross-fade animation deferred.
- **More themes** (e.g., sepia, high contrast): Architecture supports adding a third `[data-theme="X"]` block, but not in this work.
- **Tailwind 4 `@theme` directive integration**: We use raw CSS variables in `:root` / `[data-theme]`, not the `@theme` macro. Reason: the existing `globals.css` already has `@theme inline` for shadcn tokens; adding a parallel `:root[data-theme]` block keeps the redesign independent of shadcn's token names without risking collision.

---

## 6. Acceptance Criteria

1. Loading the page with no `localStorage` value AND with `prefers-color-scheme: dark` system preference shows the **dark** theme.
2. Loading with no `localStorage` value AND `prefers-color-scheme: light` shows the **light** theme.
3. Loading with no `localStorage` value AND no system preference query support (older browsers) defaults to **dark**.
4. Clicking the theme toggle in `SessionsSidebar` footer flips themes immediately, with no page reload.
5. After toggling and refreshing the page, the toggled theme persists.
6. No FOUC: page never flashes the wrong theme before settling on the chosen one.
7. All seven components render correctly in both themes — verified by visual inspection of: empty state hero, document upload progress, chat with streamed response, citations, error message banner.
8. The "+ 新对话" button, user bubble, and send button all use IKB `#002FA7` background in both themes.
9. The theme toggle pill itself shows correct icon + label for current theme.

---

## 7. Touched Files Summary

**Modified** (8 files):
- `frontend/app/globals.css`
- `frontend/app/layout.tsx`
- `frontend/components/sessions-sidebar.tsx`
- `frontend/components/document-sidebar.tsx`
- `frontend/components/document-row.tsx`
- `frontend/components/chat-pane.tsx`
- `frontend/components/message-bubble.tsx`
- `frontend/components/citation-card.tsx`

**Created** (2 files):
- `frontend/lib/use-theme.ts`
- `frontend/components/theme-toggle.tsx`

**Untouched**: backend, persona, db schema, hooks (use-chat-stream, use-documents, use-document-progress), API client (lib/api.ts), types (lib/types.ts).
