# IKB Klein Blue + Dark/Light Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current "Apple/shadcn neutral" frontend with a token-driven Klein-Blue (IKB #002FA7) aesthetic, plus a runtime dark/light theme toggle that persists per user.

**Architecture:** Two-set CSS variable theming on `[data-theme="dark"|"light"]` (the html dataset attribute). All new design tokens are namespaced `--app-*` to avoid collision with shadcn's existing `@theme inline` tokens. A small `useTheme` hook + `<ThemeToggle />` pill in the SessionsSidebar footer drives runtime switching. Anti-FOUC handled by an inline `<script>` in `layout.tsx`. Components migrate from hardcoded Tailwind colors to `bg-[var(--app-*)]` arbitrary-value classes.

**Tech Stack:** Next.js 15 (Turbopack), React 19, Tailwind 4, lucide-react, vitest. New dep: `geist` (font).

**Spec:** [docs/superpowers/specs/2026-04-25-ikb-dark-light-redesign.md](../specs/2026-04-25-ikb-dark-light-redesign.md)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `frontend/package.json` | Modify | Add `geist` dependency |
| `frontend/app/globals.css` | Modify | Add `--app-*` token blocks for `:root` (light default) and `[data-theme="dark"]`; never touch existing shadcn `@theme inline` block |
| `frontend/app/layout.tsx` | Modify | Wire Geist fonts; inline anti-FOUC script; default `<html data-theme="light">` |
| `frontend/lib/use-theme.ts` | Create | `useTheme()` hook + `readStoredTheme()` + `applyTheme()`; persist to localStorage |
| `frontend/components/theme-toggle.tsx` | Create | Pill component with sun/moon icon + "深色 · DARK" / "浅色 · LIGHT" label |
| `frontend/components/sessions-sidebar.tsx` | Modify | Migrate colors to tokens; add footer hosting `<ThemeToggle />` |
| `frontend/components/document-sidebar.tsx` | Modify | Migrate colors; upload card uses accent-bg-dim + dashed accent-border |
| `frontend/components/document-row.tsx` | Modify | Three states use `--app-status-{ok,warn,err}-{bg,fg}` tokens |
| `frontend/components/chat-pane.tsx` | Modify | Bg + input wrapper + send button to tokens; placeholder text via `--app-text-tertiary` |
| `frontend/components/message-bubble.tsx` | Modify | User/assistant bubble tokens; **add** tool-chip rendering for `message.tools[]` |
| `frontend/components/citation-card.tsx` | Modify | Card + page badge to tokens |
| `frontend/components/home.tsx` | Modify | Outer `<main>` bg → `var(--app-bg)` |
| `frontend/components/document-upload-hero.tsx` | **Delete** | Orphan after 3-col refactor; no references |
| `frontend/lib/use-theme.test.ts` | Create | Unit tests for the hook |

---

## Task 1: Install Geist, add token blocks to globals.css

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1.1: Install `geist` font package**

```bash
cd frontend && pnpm add geist
```

Expected: `geist` appears under `dependencies` in `frontend/package.json`.

- [ ] **Step 1.2: Append token blocks to `frontend/app/globals.css`**

Open the file and append these blocks at the very end (after all existing content). Do NOT modify the existing `@theme inline` or `:root { --background: ...}` shadcn blocks.

```css
/* ─────────────────────────────────────────────────────────────────
 * App-level design tokens (IKB Klein Blue + dark/light themes).
 * Namespaced --app-* to avoid collision with shadcn's @theme tokens.
 * Spec: docs/superpowers/specs/2026-04-25-ikb-dark-light-redesign.md
 * ───────────────────────────────────────────────────────────────── */

:root,
[data-theme="light"] {
  /* surfaces */
  --app-bg: #FFFFFF;
  --app-bg-sidebar: #FAFAFA;
  --app-bg-docs: #F8F8F8;
  --app-surface-elevated: #F4F4F5;
  --app-surface-input: #FFFFFF;

  /* borders */
  --app-border-subtle: #E4E4E7;
  --app-border-divider: #E4E4E7;

  /* text */
  --app-text-primary: #18181B;
  --app-text-secondary: #52525B;
  --app-text-tertiary: #71717A;
  --app-text-faint: #A1A1AA;
  --app-text-on-accent: #FFFFFF;

  /* IKB accent */
  --app-accent: #002FA7;
  --app-accent-bg: #DBEAFE;
  --app-accent-bg-dim: #EFF6FF;
  --app-accent-border: #BFDBFE;
  --app-accent-text-bright: #002FA7;
  --app-accent-text-light: #002FA7;

  /* document type (red, same in both themes) */
  --app-pdf-badge-bg: #DC2626;
  --app-pdf-badge-fg: #FFFFFF;

  /* status: ready */
  --app-status-ok-bg: #DCFCE7;
  --app-status-ok-fg: #16A34A;

  /* status: processing */
  --app-status-warn-bg: #FEF3C7;
  --app-status-warn-fg: #B45309;
  --app-status-warn-card-border: #FCD34D;

  /* status: failed */
  --app-status-err-bg: #FEE2E2;
  --app-status-err-fg: #DC2626;
  --app-status-err-card-border: #FCA5A5;
}

[data-theme="dark"] {
  /* surfaces */
  --app-bg: #0A0A0A;
  --app-bg-sidebar: #0E0E0E;
  --app-bg-docs: #0B0B0B;
  --app-surface-elevated: #141414;
  --app-surface-input: #0F0F0F;

  /* borders */
  --app-border-subtle: #1F1F1F;
  --app-border-divider: #1A1A1A;

  /* text */
  --app-text-primary: #E4E4E7;
  --app-text-secondary: #A1A1AA;
  --app-text-tertiary: #71717A;
  --app-text-faint: #52525B;
  --app-text-on-accent: #FFFFFF;

  /* IKB accent */
  --app-accent: #002FA7;
  --app-accent-bg: #001A4A;
  --app-accent-bg-dim: #00103D;
  --app-accent-border: #1E3A8A;
  --app-accent-text-bright: #6FA1F0;
  --app-accent-text-light: #93C5FD;

  /* document type */
  --app-pdf-badge-bg: #DC2626;
  --app-pdf-badge-fg: #FFFFFF;

  /* status: ready */
  --app-status-ok-bg: #0A2118;
  --app-status-ok-fg: #22C55E;

  /* status: processing */
  --app-status-warn-bg: #2A1A02;
  --app-status-warn-fg: #F59E0B;
  --app-status-warn-card-border: #3F2A0E;

  /* status: failed */
  --app-status-err-bg: #2A0E11;
  --app-status-err-fg: #EF4444;
  --app-status-err-card-border: #3F0E1A;
}
```

- [ ] **Step 1.3: Verify CSS parses**

```bash
cd frontend && pnpm dev
```

Expected: dev server starts without CSS parse errors. Browser DevTools → Elements → `<html>` → Computed → search for `--app-bg`. Should equal `#FFFFFF` (the `:root` light default).

- [ ] **Step 1.4: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/app/globals.css
git commit -m "feat(frontend): add --app-* design tokens for dark/light + install geist"
```

---

## Task 2: useTheme hook (TDD)

**Files:**
- Create: `frontend/lib/use-theme.ts`
- Create: `frontend/lib/use-theme.test.ts`

- [ ] **Step 2.1: Write the failing test**

Create `frontend/lib/use-theme.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { readStoredTheme, applyTheme, resolveInitialTheme } from "./use-theme";

describe("readStoredTheme", () => {
  beforeEach(() => localStorage.clear());

  it("returns null when no value", () => {
    expect(readStoredTheme()).toBeNull();
  });

  it("returns 'dark' when stored", () => {
    localStorage.setItem("docqa.theme", "dark");
    expect(readStoredTheme()).toBe("dark");
  });

  it("returns 'light' when stored", () => {
    localStorage.setItem("docqa.theme", "light");
    expect(readStoredTheme()).toBe("light");
  });

  it("returns null on invalid value", () => {
    localStorage.setItem("docqa.theme", "blue");
    expect(readStoredTheme()).toBeNull();
  });
});

describe("applyTheme", () => {
  it("sets data-theme on document.documentElement", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("persists to localStorage", () => {
    applyTheme("dark");
    expect(localStorage.getItem("docqa.theme")).toBe("dark");
  });
});

describe("resolveInitialTheme", () => {
  beforeEach(() => localStorage.clear());

  it("uses stored value when present", () => {
    localStorage.setItem("docqa.theme", "light");
    expect(resolveInitialTheme()).toBe("light");
  });

  it("falls back to dark when no stored, no matchMedia", () => {
    // jsdom's matchMedia is undefined by default
    expect(resolveInitialTheme()).toBe("dark");
  });

  it("respects prefers-color-scheme: dark when no stored value", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("dark"),
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    expect(resolveInitialTheme()).toBe("dark");
    vi.unstubAllGlobals();
  });

  it("respects prefers-color-scheme: light when no stored value", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: false,
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    expect(resolveInitialTheme()).toBe("light");
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
cd frontend && pnpm test lib/use-theme
```

Expected: FAIL with "Cannot find module './use-theme'" or similar.

- [ ] **Step 2.3: Implement the hook**

Create `frontend/lib/use-theme.ts`:

```ts
"use client";
import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "docqa.theme";

function isTheme(v: unknown): v is Theme {
  return v === "dark" || v === "light";
}

export function readStoredTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(KEY);
    return isTheme(v) ? v : null;
  } catch {
    return null;
  }
}

export function applyTheme(theme: Theme): void {
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = theme;
  }
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    /* private mode / quota — non-fatal */
  }
}

export function resolveInitialTheme(): Theme {
  const stored = readStoredTheme();
  if (stored) return stored;
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return "dark"; // brand default
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>("dark");

  // Sync to whatever the anti-FOUC script set on first paint, then own it.
  useEffect(() => {
    const initial = (document.documentElement.dataset.theme as Theme) ||
                    resolveInitialTheme();
    setTheme(initial);
    applyTheme(initial);
  }, []);

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
```

- [ ] **Step 2.4: Run tests, expect pass**

```bash
cd frontend && pnpm test lib/use-theme
```

Expected: all tests PASS (10+ assertions).

- [ ] **Step 2.5: Commit**

```bash
git add frontend/lib/use-theme.ts frontend/lib/use-theme.test.ts
git commit -m "feat(frontend): add useTheme hook with localStorage + system-preference fallback"
```

---

## Task 3: Anti-FOUC inline script + Geist fonts in layout.tsx

**Files:**
- Modify: `frontend/app/layout.tsx`

- [ ] **Step 3.1: Replace `frontend/app/layout.tsx` contents**

```tsx
import type { Metadata } from "next";
import Script from "next/script";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "文档问答助手",
  description: "PDF document QA assistant — Chinese, with page-level citations",
};

// This runs in the browser BEFORE React hydrates, so the first paint already
// has the correct data-theme on <html>. Without this, the page would briefly
// render in :root light tokens before useTheme applies the stored preference.
const ANTI_FOUC = `
try {
  var t = localStorage.getItem('docqa.theme');
  if (t !== 'dark' && t !== 'light') {
    t = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
      ? 'dark' : 'dark';
  }
  document.documentElement.dataset.theme = t;
} catch(e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="zh-CN"
      data-theme="dark"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
    >
      <head>
        <Script id="anti-fouc" strategy="beforeInteractive">
          {ANTI_FOUC}
        </Script>
      </head>
      <body className="antialiased font-sans">{children}</body>
    </html>
  );
}
```

Notes:
- `data-theme="dark"` on `<html>` is the SSR default. The anti-FOUC script overrides it before React mounts if a stored / preferred value differs.
- `GeistSans.variable` and `GeistMono.variable` add `--font-geist-sans` and `--font-geist-mono` CSS vars to `<html>`.
- The body class `font-sans` is wired through Tailwind's existing `--font-sans: var(--font-sans)` from shadcn's `@theme inline`. That points at `var(--font-sans)` which Geist sets. So existing components don't need to opt in to Geist explicitly.

Wait — the existing `@theme inline` has `--font-sans: var(--font-sans)` which is a recursive reference. We need `--font-sans` to point at `var(--font-geist-sans)`.

- [ ] **Step 3.2: Wire Geist into the existing shadcn @theme block**

In `frontend/app/globals.css`, find the existing line (inside the `@theme inline { ... }` block):

```css
  --font-sans: var(--font-sans);
  --font-mono: var(--font-geist-mono);
```

Replace `--font-sans: var(--font-sans);` with:

```css
  --font-sans: var(--font-geist-sans);
```

(`--font-mono: var(--font-geist-mono)` already references the right variable; no change needed there.)

- [ ] **Step 3.3: Verify in browser**

```bash
cd frontend && pnpm dev
```

Open http://localhost:3000. DevTools → Elements → `<html>`. Computed style should have:
- `data-theme` attribute set (probably `dark` if no stored value)
- `--font-geist-sans` / `--font-geist-mono` defined
- Body text rendered in Geist (visible difference from default sans-serif if you compare before/after)

Toggle network throttle to "slow 3G" and hard-reload. The page should NOT flash a light background then settle on dark.

- [ ] **Step 3.4: Commit**

```bash
git add frontend/app/layout.tsx frontend/app/globals.css
git commit -m "feat(frontend): wire Geist fonts + anti-FOUC theme script in root layout"
```

---

## Task 4: ThemeToggle component

**Files:**
- Create: `frontend/components/theme-toggle.tsx`
- Create: `frontend/tests/theme-toggle.test.tsx`

- [ ] **Step 4.1: Write a smoke test**

Create `frontend/tests/theme-toggle.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeToggle } from "@/components/theme-toggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("renders the dark-mode label initially when default is dark", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button")).toHaveTextContent(/深色|浅色/);
  });

  it("toggles label and dataset on click", () => {
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);
    const btn = screen.getByRole("button");
    const before = btn.textContent;
    fireEvent.click(btn);
    expect(btn.textContent).not.toBe(before);
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
```

- [ ] **Step 4.2: Run, expect failure**

```bash
cd frontend && pnpm test tests/theme-toggle
```

Expected: FAIL — module not found.

- [ ] **Step 4.3: Implement the component**

Create `frontend/components/theme-toggle.tsx`:

```tsx
"use client";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/lib/use-theme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      onClick={toggle}
      type="button"
      aria-label={isDark ? "切换到浅色模式" : "切换到深色模式"}
      className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[10px] font-mono uppercase tracking-wider transition"
      style={{
        backgroundColor: "var(--app-surface-elevated)",
        borderColor: "var(--app-border-subtle)",
        color: isDark
          ? "var(--app-accent-text-light)"
          : "var(--app-accent)",
      }}
    >
      {isDark ? <Moon className="h-3 w-3" /> : <Sun className="h-3 w-3" />}
      {isDark ? "深色 · DARK" : "浅色 · LIGHT"}
    </button>
  );
}
```

- [ ] **Step 4.4: Run, expect pass**

```bash
cd frontend && pnpm test tests/theme-toggle
```

Expected: PASS.

- [ ] **Step 4.5: Commit**

```bash
git add frontend/components/theme-toggle.tsx frontend/tests/theme-toggle.test.tsx
git commit -m "feat(frontend): add ThemeToggle pill (sun/moon + DARK/LIGHT label)"
```

---

## Task 5: Migrate sessions-sidebar.tsx + add ThemeToggle in footer

**Files:**
- Modify: `frontend/components/sessions-sidebar.tsx`

- [ ] **Step 5.1: Replace `frontend/components/sessions-sidebar.tsx` contents**

```tsx
"use client";

import { useRouter } from "next/navigation";
import { Plus, X } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { createSession, deleteSession } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";
import { ThemeToggle } from "@/components/theme-toggle";

type Props = {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onAfterCreate: () => void;
};

export function SessionsSidebar({
  sessions,
  activeSessionId,
  onAfterCreate,
}: Props) {
  const router = useRouter();

  async function handleNew() {
    const { session_id } = await createSession();
    router.push(`/?session=${session_id}`);
    onAfterCreate();
  }

  async function handleDelete(e: React.MouseEvent, sid: string) {
    e.stopPropagation();
    if (!confirm("删除此会话及其所有文档与消息？此操作不可撤销。")) return;
    try {
      await deleteSession(sid);
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
      return;
    }
    if (sid === activeSessionId) {
      router.push("/");
    }
    onAfterCreate();
  }

  return (
    <aside
      className="flex h-full w-[220px] flex-col border-r"
      style={{
        backgroundColor: "var(--app-bg-sidebar)",
        borderColor: "var(--app-border-divider)",
      }}
    >
      <div className="px-3 py-3">
        <button
          onClick={handleNew}
          className="flex w-full items-center justify-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium transition hover:opacity-90"
          style={{
            backgroundColor: "var(--app-accent)",
            color: "var(--app-text-on-accent)",
          }}
        >
          <Plus className="h-4 w-4" /> 新对话
        </button>
      </div>
      <div
        className="px-3 pb-1.5 text-[10px] font-mono font-semibold uppercase tracking-wider"
        style={{ color: "var(--app-text-tertiary)" }}
      >
        会话 · SESSIONS
      </div>
      <ScrollArea className="flex-1">
        <ul className="px-2 pb-3">
          {sessions.length === 0 && (
            <li
              className="px-2 py-1.5 text-[11px]"
              style={{ color: "var(--app-text-faint)" }}
            >
              （暂无）
            </li>
          )}
          {sessions.map((s) => {
            const active = s.session_id === activeSessionId;
            return (
              <li key={s.session_id}>
                <div
                  onClick={() => router.push(`/?session=${s.session_id}`)}
                  className="group relative mb-1 cursor-pointer rounded border px-2.5 py-1.5 transition"
                  style={{
                    backgroundColor: active
                      ? "var(--app-accent-bg)"
                      : "transparent",
                    borderColor: active
                      ? "var(--app-accent-border)"
                      : "transparent",
                    color: active
                      ? "var(--app-text-primary)"
                      : "var(--app-text-secondary)",
                  }}
                >
                  <div className="truncate pr-5 text-[12px]">{s.title}</div>
                  <div
                    className="mt-0.5 text-[10px] font-mono"
                    style={{ color: "var(--app-text-faint)" }}
                  >
                    {new Date(s.created_at).toLocaleString("zh-CN")}
                  </div>
                  <button
                    onClick={(e) => handleDelete(e, s.session_id)}
                    aria-label="删除会话"
                    className="absolute right-1.5 top-1.5 rounded p-0.5 opacity-0 transition hover:bg-red-500/10 group-hover:opacity-100"
                    style={{ color: "var(--app-text-faint)" }}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
      <div
        className="border-t px-3 py-2"
        style={{ borderColor: "var(--app-border-subtle)" }}
      >
        <ThemeToggle />
      </div>
    </aside>
  );
}
```

- [ ] **Step 5.2: Verify in browser**

Hot-reload. Open http://localhost:3000. The sessions sidebar should look identical functionally (new button, list, hover X) but now in dark/light theme based on current setting. Footer at bottom shows the theme toggle pill. Click it — sidebar bg + active session card colors swap.

If Turbopack reports `Unexpected eof` (known issue), `touch frontend/components/sessions-sidebar.tsx` to retrigger.

- [ ] **Step 5.3: Commit**

```bash
git add frontend/components/sessions-sidebar.tsx
git commit -m "feat(frontend): migrate sessions-sidebar to --app-* tokens + theme toggle in footer"
```

---

## Task 6: Migrate document-sidebar.tsx

**Files:**
- Modify: `frontend/components/document-sidebar.tsx`

- [ ] **Step 6.1: Replace `frontend/components/document-sidebar.tsx` contents**

```tsx
"use client";
import { useRef, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { uploadDocument, deleteDocument } from "@/lib/api";
import type { Document } from "@/lib/types";
import { DocumentRow } from "./document-row";

type Props = {
  sessionId: string;
  docs: Document[];
  onChange: () => void;
};

export function DocumentSidebar({ sessionId, docs, onChange }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    setError(null);
    try {
      await uploadDocument(sessionId, file);
      onChange();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "上传失败");
    }
  }

  async function handleDelete(docId: string) {
    setError(null);
    try {
      await deleteDocument(sessionId, docId);
      onChange();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  }

  return (
    <aside
      className="flex h-full w-[260px] flex-col border-r"
      style={{
        backgroundColor: "var(--app-bg-docs)",
        borderColor: "var(--app-border-divider)",
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = e.dataTransfer.files[0];
        if (f) handleUpload(f);
      }}
    >
      <div
        className="px-3 pt-3 pb-1.5 text-[10px] font-mono font-semibold uppercase tracking-wider"
        style={{ color: "var(--app-text-tertiary)" }}
      >
        文档 · DOCUMENTS
      </div>

      <ScrollArea className="flex-1">
        <ul className="flex flex-col gap-1.5 px-3 pb-3">
          {docs.length === 0 ? (
            <li
              className="px-1 py-1.5 text-[11px]"
              style={{ color: "var(--app-text-faint)" }}
            >
              暂无文档
            </li>
          ) : (
            docs.map((d) => (
              <li key={d.document_id}>
                <DocumentRow
                  sessionId={sessionId}
                  doc={d}
                  onDelete={handleDelete}
                />
              </li>
            ))
          )}
        </ul>
      </ScrollArea>

      <div
        className="border-t p-3"
        style={{ borderColor: "var(--app-border-subtle)" }}
      >
        <button
          onClick={() => inputRef.current?.click()}
          className="block w-full rounded-md border-2 border-dashed px-3 py-3 text-center transition"
          style={{
            backgroundColor: dragging
              ? "var(--app-accent-bg)"
              : "var(--app-accent-bg-dim)",
            borderColor: "var(--app-accent-border)",
            color: "var(--app-accent-text-light)",
          }}
        >
          <div className="text-[20px] leading-none">📥</div>
          <div className="mt-1 text-[12px] font-semibold">
            {dragging ? "松开上传" : "拖入或点击上传 PDF"}
          </div>
          <div
            className="mt-0.5 text-[10px] font-mono"
            style={{ color: "var(--app-text-tertiary)" }}
          >
            ≤ 20MB · 可多份
          </div>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleUpload(f);
          }}
        />
        {error && (
          <div
            className="mt-2 text-[11px]"
            style={{ color: "var(--app-status-err-fg)" }}
          >
            {error}
          </div>
        )}
      </div>
    </aside>
  );
}
```

- [ ] **Step 6.2: Verify in browser**

DocumentSidebar should match the Pencil mockup look. Drag-over highlights the upload card with a stronger blue tint. Empty state shows "暂无文档" in faint text. Toggle theme — colors flip cleanly.

- [ ] **Step 6.3: Commit**

```bash
git add frontend/components/document-sidebar.tsx
git commit -m "feat(frontend): migrate document-sidebar to --app-* tokens"
```

---

## Task 7: Migrate document-row.tsx (3 states)

**Files:**
- Modify: `frontend/components/document-row.tsx`

- [ ] **Step 7.1: Replace `frontend/components/document-row.tsx` contents**

```tsx
"use client";
import { X } from "lucide-react";
import type { Document } from "@/lib/types";
import { useDocumentProgress } from "@/lib/use-document-progress";

type Props = {
  sessionId: string;
  doc: Document;
  onDelete: (docId: string) => void;
};

export function DocumentRow({ sessionId, doc, onDelete }: Props) {
  const progress = useDocumentProgress(
    sessionId,
    doc.document_id,
    doc.status === "processing",
  );

  if (doc.status === "processing") {
    const page = (progress as { page?: number } | null)?.page ??
                 doc.progress_page ?? 0;
    const total = doc.page_count;
    const pct = total ? Math.round((page / total) * 100) : 0;
    return (
      <div
        className="min-w-[200px] rounded-md border px-2 py-1.5"
        style={{
          backgroundColor: "var(--app-status-warn-bg)",
          borderColor: "var(--app-status-warn-card-border)",
        }}
      >
        <div className="flex items-center gap-2">
          <FileBadge />
          <span
            className="flex-1 truncate text-xs"
            style={{ color: "var(--app-text-primary)" }}
          >
            {doc.filename}
          </span>
          <StatusPill kind="warn">解析中</StatusPill>
        </div>
        <div
          className="mt-1.5 h-[3px] overflow-hidden rounded-sm"
          style={{ backgroundColor: "var(--app-status-warn-bg)" }}
        >
          <div
            className="h-full transition-all"
            style={{
              width: `${pct}%`,
              backgroundColor: "var(--app-status-warn-fg)",
            }}
          />
        </div>
        <div
          className="mt-1 text-[10px] font-mono"
          style={{ color: "var(--app-status-warn-fg)" }}
        >
          向量化 {page} / {total}
        </div>
      </div>
    );
  }

  if (doc.status === "ready") {
    return (
      <div
        className="flex min-w-[200px] items-center gap-2 rounded-md border px-2 py-1.5"
        style={{
          backgroundColor: "var(--app-bg)",
          borderColor: "var(--app-border-subtle)",
        }}
      >
        <FileBadge />
        <span
          className="flex-1 truncate text-xs"
          style={{ color: "var(--app-text-primary)" }}
        >
          {doc.filename}
        </span>
        <span
          className="text-[10px] font-mono"
          style={{ color: "var(--app-text-tertiary)" }}
        >
          {doc.page_count} 页
        </span>
        <StatusPill kind="ok">✓ 就绪</StatusPill>
        <button
          onClick={() => onDelete(doc.document_id)}
          className="px-1 transition hover:opacity-70"
          aria-label="删除文档"
          style={{ color: "var(--app-text-faint)" }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  // failed
  return (
    <div
      className="min-w-[200px] rounded-md border px-2 py-1.5"
      style={{
        backgroundColor: "var(--app-bg)",
        borderColor: "var(--app-status-err-card-border)",
      }}
    >
      <div className="flex items-center gap-2">
        <FileBadge />
        <span
          className="flex-1 truncate text-xs"
          style={{ color: "var(--app-text-primary)" }}
        >
          {doc.filename}
        </span>
        <StatusPill kind="err">✗ 失败</StatusPill>
        <button
          onClick={() => onDelete(doc.document_id)}
          className="px-1 transition hover:opacity-70"
          aria-label="删除文档"
          style={{ color: "var(--app-text-faint)" }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {doc.error_message && (
        <div
          className="mt-1 text-[10px] leading-snug font-mono"
          style={{ color: "var(--app-status-err-fg)" }}
        >
          {doc.error_message}
        </div>
      )}
    </div>
  );
}

function FileBadge() {
  return (
    <span
      className="inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-sm text-[8px] font-bold font-mono"
      style={{
        backgroundColor: "var(--app-pdf-badge-bg)",
        color: "var(--app-pdf-badge-fg)",
      }}
    >
      PDF
    </span>
  );
}

function StatusPill({
  kind,
  children,
}: {
  kind: "ok" | "warn" | "err";
  children: React.ReactNode;
}) {
  const bg =
    kind === "ok"
      ? "var(--app-status-ok-bg)"
      : kind === "warn"
        ? "var(--app-status-warn-bg)"
        : "var(--app-status-err-bg)";
  const fg =
    kind === "ok"
      ? "var(--app-status-ok-fg)"
      : kind === "warn"
        ? "var(--app-status-warn-fg)"
        : "var(--app-status-err-fg)";
  return (
    <span
      className="rounded-full px-2 py-[1px] text-[10px] font-mono font-semibold"
      style={{ backgroundColor: bg, color: fg }}
    >
      {children}
    </span>
  );
}
```

- [ ] **Step 7.2: Verify all three states**

Upload a PDF, watch the row go through:
1. **processing**: amber bg + progress bar + "向量化 X/Y" caption (mono)
2. **ready**: white/black card + green pill + page count
3. **failed**: red-bordered card + red pill + error message in mono

Toggle theme during processing — colors swap correctly.

- [ ] **Step 7.3: Commit**

```bash
git add frontend/components/document-row.tsx
git commit -m "feat(frontend): migrate document-row to status tokens (3 states)"
```

---

## Task 8: Migrate chat-pane.tsx

**Files:**
- Modify: `frontend/components/chat-pane.tsx`

- [ ] **Step 8.1: Replace `frontend/components/chat-pane.tsx` contents**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { listMessages } from "@/lib/api";
import { useChatStream } from "@/lib/use-chat-stream";
import type { Document, Message } from "@/lib/types";
import { MessageBubble } from "./message-bubble";

type Props = {
  sessionId: string;
  docs: Document[];
  onFirstMessageSent?: () => void;
};

export function ChatPane({ sessionId, docs, onFirstMessageSent }: Props) {
  const { messages, streaming, error, send, setMessages } =
    useChatStream(sessionId);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const hist = await listMessages(sessionId);
        if (cancelled) return;
        const converted: Message[] = hist.map((m, idx) => ({
          id: `hist-${idx}`,
          role: m.role,
          content: m.content ?? "",
          tools:
            m.role === "assistant" && m.tool_calls
              ? m.tool_calls.map((tc) => ({
                  id: tc.id,
                  name: tc.name,
                  status: "ok" as const,
                }))
              : [],
          citations: (m as { citations?: Message["citations"] }).citations,
        }));
        setMessages((prev) => (prev.length === 0 ? converted : prev));
      } catch {
        /* empty fallback */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, setMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const hasAny = docs.length > 0;
  const hasReady = docs.some((d) => d.status === "ready");
  const hasProcessing = docs.some((d) => d.status === "processing");
  const inputDisabled = streaming || (hasAny && !hasReady);

  async function handleSend() {
    const wasEmpty = messages.length === 0;
    const text = input.trim();
    if (!text || inputDisabled) return;
    setInput("");
    await send(text);
    if (wasEmpty && onFirstMessageSent) onFirstMessageSent();
  }

  const placeholder = streaming
    ? "回答生成中…"
    : hasProcessing && !hasReady
      ? "请等待文档解析完成…"
      : hasReady
        ? "向文档提问…  Enter 发送 · Shift+Enter 换行"
        : "输入问题与助手对话…  Enter 发送";

  return (
    <div
      className="flex h-full flex-1 flex-col"
      style={{ backgroundColor: "var(--app-bg)" }}
    >
      <ScrollArea className="flex-1">
        <div className="mx-auto w-full max-w-3xl px-5 py-5">
          {messages.length === 0 && (
            <div
              className="mt-8 text-center text-[13px]"
              style={{ color: "var(--app-text-faint)" }}
            >
              {hasReady
                ? "文档已就绪，可以开始提问了。"
                : hasProcessing
                  ? "文档解析中，稍候即可提问。"
                  : "未上传文档时也可以直接对话；上传后回答会附带原文出处。"}
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          {error && (
            <div
              className="my-2 rounded-md border px-3 py-2 text-sm"
              style={{
                backgroundColor: "var(--app-status-err-bg)",
                borderColor: "var(--app-status-err-card-border)",
                color: "var(--app-status-err-fg)",
              }}
            >
              出错了：{error}
              <button
                className="ml-2 underline underline-offset-2 hover:no-underline"
                onClick={() => {
                  const last = messages.findLast((m) => m.role === "user");
                  if (last) {
                    setMessages((prev) => prev.slice(0, -2));
                    send(last.content);
                  }
                }}
              >
                重试
              </button>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      <div
        className="border-t px-4 py-3"
        style={{
          backgroundColor: "var(--app-bg)",
          borderColor: "var(--app-border-subtle)",
        }}
      >
        <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={placeholder}
            disabled={inputDisabled}
            rows={1}
            className="min-h-[40px] flex-1 resize-none rounded-md border px-3 py-2 text-[13px] outline-none transition focus:ring-2 disabled:opacity-50"
            style={{
              backgroundColor: "var(--app-surface-input)",
              borderColor: "var(--app-border-subtle)",
              color: "var(--app-text-primary)",
            }}
          />
          <button
            onClick={handleSend}
            disabled={inputDisabled || !input.trim()}
            className="inline-flex items-center gap-1 rounded-md px-3.5 py-2 text-[13px] font-medium transition hover:opacity-90 disabled:opacity-50"
            style={{
              backgroundColor: "var(--app-accent)",
              color: "var(--app-text-on-accent)",
            }}
          >
            <Send className="h-3.5 w-3.5" /> 发送
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 8.2: Verify**

Open a session, see input bar at bottom + send button in IKB blue. Disabled state (during streaming or while doc is processing) shows reduced opacity. Input placeholder text matches the state branching above.

- [ ] **Step 8.3: Commit**

```bash
git add frontend/components/chat-pane.tsx
git commit -m "feat(frontend): migrate chat-pane to --app-* tokens"
```

---

## Task 9: Migrate message-bubble.tsx + add tool-chip rendering

**Files:**
- Modify: `frontend/components/message-bubble.tsx`

This task adds the missing tool-chip rendering noted in spec §4.1 — the data is already in `message.tools[]` from the SSE stream, but the UI currently doesn't show it.

- [ ] **Step 9.1: Replace `frontend/components/message-bubble.tsx` contents**

```tsx
import { Search } from "lucide-react";
import type { Message, ToolCall } from "@/lib/types";
import { CitationCard } from "./citation-card";

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const tools =
    message.role === "assistant" && message.tools.length > 0
      ? message.tools
      : null;

  return (
    <div
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"} my-2`}
    >
      <div
        className="max-w-[80%] rounded-2xl px-4 py-2.5 text-[14px] leading-relaxed"
        style={{
          backgroundColor: isUser
            ? "var(--app-accent)"
            : "var(--app-surface-elevated)",
          color: isUser
            ? "var(--app-text-on-accent)"
            : "var(--app-text-primary)",
          border: isUser ? "none" : "1px solid var(--app-border-subtle)",
          borderRadius: isUser
            ? "16px 16px 4px 16px"
            : "16px 16px 16px 4px",
        }}
      >
        {tools && (
          <div className="mb-2.5 flex flex-wrap gap-1.5">
            {tools.map((t) => (
              <ToolChip key={t.id} tool={t} />
            ))}
          </div>
        )}
        {message.content && (
          <div className="whitespace-pre-wrap break-words">
            {message.content}
          </div>
        )}
        {message.role === "assistant" && message.citations && (
          <CitationCard citations={message.citations} />
        )}
      </div>
    </div>
  );
}

function ToolChip({ tool }: { tool: ToolCall }) {
  // We don't yet know the chunk count from the data shape — show name + status.
  const label =
    tool.status === "running"
      ? `${tool.name} · running…`
      : tool.status === "ok"
        ? `${tool.name}`
        : `${tool.name} · failed`;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-[2px] text-[10px] font-mono"
      style={{
        backgroundColor: "var(--app-accent-bg-dim)",
        borderColor: "var(--app-accent-border)",
        color: "var(--app-accent-text-bright)",
      }}
    >
      <Search className="h-2.5 w-2.5" />
      {label}
    </span>
  );
}
```

- [ ] **Step 9.2: Verify**

Send a question against a ready document. While SSE streams, the assistant bubble should render an indigo `search_documents · running…` chip first; when the tool finishes (ok), the chip stabilizes; then text streams in below it; then citations appear at the bottom.

Toggle theme to verify chip stays readable on both backgrounds.

- [ ] **Step 9.3: Commit**

```bash
git add frontend/components/message-bubble.tsx
git commit -m "feat(frontend): migrate message-bubble + render tool-call chips"
```

---

## Task 10: Migrate citation-card.tsx

**Files:**
- Modify: `frontend/components/citation-card.tsx`

- [ ] **Step 10.1: Replace `frontend/components/citation-card.tsx` contents**

```tsx
"use client";
import { useState } from "react";
import type { Citation } from "@/lib/types";

type Props = { citations: Citation[] };

export function CitationCard({ citations }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  if (!citations || citations.length === 0) return null;

  function toggle(i: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  return (
    <div
      className="mt-3 border-t pt-3"
      style={{ borderColor: "var(--app-border-subtle)" }}
    >
      <div
        className="mb-2 flex items-center gap-1 text-[11px] font-mono font-semibold uppercase tracking-wider"
        style={{ color: "var(--app-text-tertiary)" }}
      >
        📚 来源 · CITATIONS ({citations.length})
      </div>
      <div className="flex flex-col gap-1.5">
        {citations.map((c, i) => (
          <div
            key={i}
            onClick={() => toggle(i)}
            className="flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2.5 transition hover:opacity-90"
            style={{
              backgroundColor: "var(--app-bg)",
              borderColor: "var(--app-border-subtle)",
            }}
          >
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-[9px] font-bold font-mono"
              style={{
                backgroundColor: "var(--app-pdf-badge-bg)",
                color: "var(--app-pdf-badge-fg)",
              }}
            >
              PDF
            </span>
            <div className="min-w-0 flex-1">
              <div
                className="text-[12px] font-medium"
                style={{ color: "var(--app-text-primary)" }}
              >
                {c.filename}
              </div>
              <div
                className={`mt-0.5 text-[11px] leading-snug font-mono ${
                  expanded.has(i) ? "" : "line-clamp-2"
                }`}
                style={{ color: "var(--app-text-secondary)" }}
              >
                {c.snippet}
              </div>
            </div>
            <span
              className="ml-2 shrink-0 rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold font-mono"
              style={{
                backgroundColor: "var(--app-accent-bg)",
                borderColor: "var(--app-accent-border)",
                color: "var(--app-accent-text-light)",
              }}
            >
              p.{c.page_no}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 10.2: Verify**

Citations show as cards with red PDF badge, mono filename + 2-line clipped snippet, IKB-bordered page badge `p.NN`. Click expands snippet. Theme toggle preserves contrast.

- [ ] **Step 10.3: Commit**

```bash
git add frontend/components/citation-card.tsx
git commit -m "feat(frontend): migrate citation-card to --app-* tokens"
```

---

## Task 11: Migrate home.tsx + delete orphan upload-hero

**Files:**
- Modify: `frontend/components/home.tsx`
- Delete: `frontend/components/document-upload-hero.tsx`

- [ ] **Step 11.1: Replace `frontend/components/home.tsx` contents**

```tsx
"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { listSessions } from "@/lib/api";
import { SessionsSidebar } from "@/components/sessions-sidebar";
import { DocumentSidebar } from "@/components/document-sidebar";
import { ChatPane } from "@/components/chat-pane";
import { useDocuments } from "@/lib/use-documents";
import type { SessionSummary } from "@/lib/types";

export function Home() {
  const params = useSearchParams();
  const sessionId = params.get("session");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  const refreshSessions = async () => {
    try {
      const list = await listSessions();
      setSessions(list);
    } catch {
      setSessions([]);
    }
  };

  useEffect(() => {
    refreshSessions();
  }, []);

  return (
    <main
      className="flex h-screen w-screen overflow-hidden"
      style={{ backgroundColor: "var(--app-bg)" }}
    >
      <SessionsSidebar
        sessions={sessions}
        activeSessionId={sessionId}
        onAfterCreate={refreshSessions}
      />
      {sessionId ? (
        <SessionWorkspace
          key={sessionId}
          sessionId={sessionId}
          onFirstMessageSent={refreshSessions}
        />
      ) : (
        <div
          className="flex flex-1 items-center justify-center text-sm"
          style={{ color: "var(--app-text-faint)" }}
        >
          选择一个会话或新建一个
        </div>
      )}
    </main>
  );
}

function SessionWorkspace({
  sessionId,
  onFirstMessageSent,
}: {
  sessionId: string;
  onFirstMessageSent: () => void;
}) {
  const { docs, refresh: refreshDocs } = useDocuments(sessionId);
  return (
    <>
      <DocumentSidebar
        sessionId={sessionId}
        docs={docs}
        onChange={refreshDocs}
      />
      <ChatPane
        sessionId={sessionId}
        docs={docs}
        onFirstMessageSent={onFirstMessageSent}
      />
    </>
  );
}
```

- [ ] **Step 11.2: Delete the orphan upload-hero component**

```bash
rm frontend/components/document-upload-hero.tsx
```

Verify nothing references it:

```bash
grep -r "DocumentUploadHero\|document-upload-hero" frontend/
```

Expected: no output.

- [ ] **Step 11.3: Verify**

Reload the app. Layout should look identical. Idle "no session selected" state shows centered "选择一个会话或新建一个" in faint text.

- [ ] **Step 11.4: Commit**

```bash
git add frontend/components/home.tsx
git rm frontend/components/document-upload-hero.tsx
git commit -m "feat(frontend): migrate home.tsx + drop orphaned upload-hero"
```

---

## Task 12: Browser smoke verification of acceptance criteria

This task does NOT change code — it's a manual checklist mapping spec §6 to live behavior.

**Files:** none.

- [ ] **Step 12.1: Clear `localStorage` and verify dark default**

```bash
# Make sure dev server is running
cd frontend && pnpm dev
```

In the browser:
1. DevTools → Application → Local Storage → http://localhost:3000 → delete `docqa.theme`
2. DevTools → Rendering → Emulate CSS media feature → `prefers-color-scheme: dark`
3. Hard reload (Cmd+Shift+R)

Expected: page renders dark on first paint. No flash.

- [ ] **Step 12.2: Verify light default with system preference**

1. Clear `localStorage` again
2. Emulate `prefers-color-scheme: light`
3. Hard reload

Expected: page renders light on first paint.

- [ ] **Step 12.3: Verify fallback to dark when preference unsupported**

1. Clear `localStorage`
2. In DevTools Console: `delete window.matchMedia` (best-effort; alternatively just verify the hook returns "dark" via console call to `resolveInitialTheme()`)

Expected: dark.

- [ ] **Step 12.4: Verify toggle is instant + persistent**

1. Click `<ThemeToggle />` pill → page swaps theme without reload
2. Reload page → keeps the toggled theme
3. Toggle back → still works, persists again

- [ ] **Step 12.5: Visual scan of all states (both themes)**

For both `dark` and `light`:
- [ ] Empty session list with "（暂无）" caption
- [ ] Active session card highlighted
- [ ] Hover-X delete button on session
- [ ] DocumentSidebar empty state ("暂无文档")
- [ ] DocumentRow processing state with progress bar + "向量化 X/Y"
- [ ] DocumentRow ready state with green pill
- [ ] DocumentRow failed state with red border + error message
- [ ] Upload card hover (drag-over) state
- [ ] Empty chat with idle hint
- [ ] User message bubble (IKB)
- [ ] Assistant bubble with tool chip while streaming
- [ ] Assistant bubble with citations after stream
- [ ] Error banner during a failed message
- [ ] Theme toggle pill itself

If any state looks broken (low contrast, color stuck from the wrong theme, etc.), fix the relevant component's token references and re-verify.

- [ ] **Step 12.6: Final commit (if any tweaks were made)**

```bash
git status
# If any tweaks were made:
git add -A && git commit -m "fix(frontend): visual tweaks from theme verification"
```

---

## Self-Review

**Spec coverage:**
- §2 token table → Task 1 (CSS) ✅
- §3.1 CSS variables → Task 1 ✅
- §3.2 useTheme hook → Task 2 ✅
- §3.3 anti-FOUC → Task 3 ✅
- §3.4 ThemeToggle → Task 4 ✅
- §4 component-by-component table → Tasks 5–11 ✅
- §4.1 tool chip rendering → Task 9 ✅
- §6 acceptance criteria → Task 12 ✅
- Touched files summary §7 → matches the File Structure section above ✅

**Placeholder scan:** None. Every task has full code.

**Type/name consistency:**
- `--app-*` token names spelled identically across globals.css (Task 1) and component style props (Tasks 5–11). ✅
- `applyTheme`, `readStoredTheme`, `resolveInitialTheme` defined in Task 2 — consumed by Task 4 (`useTheme`). ✅
- `ToolCall` type imported in Task 9 — already exists in `lib/types.ts` (verified in spec). ✅
- `useTheme` returned shape `{ theme, toggle }` — consumed by `ThemeToggle` in Task 4. ✅

**Spec deviation noted:** Spec §2 used unprefixed token names (`--bg`, `--accent` etc.). Plan namespaces all to `--app-*` to avoid collision with shadcn's `@theme inline` block (which already defines `--accent`, `--border` etc.). Functionally identical; documented in plan header.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-ikb-dark-light-redesign.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
