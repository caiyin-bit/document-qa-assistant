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
