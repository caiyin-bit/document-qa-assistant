"use client";

import { useRouter } from "next/navigation";
import { Plus, X } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { createSession, deleteSession } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";

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
    <aside className="flex h-full w-[220px] flex-col border-r border-gray-200 bg-gray-50">
      <div className="px-3 py-3">
        <button
          onClick={handleNew}
          className="flex w-full items-center justify-center gap-1.5 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm transition hover:bg-indigo-50 hover:text-indigo-700"
        >
          <Plus className="h-4 w-4" /> 新对话
        </button>
      </div>
      <div className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
        会话
      </div>
      <ScrollArea className="flex-1">
        <ul className="px-2 pb-3">
          {sessions.length === 0 && (
            <li className="px-2 py-1.5 text-[11px] text-gray-400">
              （暂无）
            </li>
          )}
          {sessions.map((s) => {
            const active = s.session_id === activeSessionId;
            return (
              <li key={s.session_id}>
                <div
                  onClick={() =>
                    router.push(`/?session=${s.session_id}`)
                  }
                  className={`group relative mb-1 cursor-pointer rounded border px-2.5 py-1.5 transition ${
                    active
                      ? "border-indigo-200 bg-indigo-50 text-indigo-900"
                      : "border-transparent text-gray-700 hover:bg-gray-100"
                  }`}
                >
                  <div className="truncate pr-5 text-[12px]">{s.title}</div>
                  <div className="mt-0.5 text-[10px] text-gray-400">
                    {new Date(s.created_at).toLocaleString("zh-CN")}
                  </div>
                  <button
                    onClick={(e) => handleDelete(e, s.session_id)}
                    aria-label="删除会话"
                    className="absolute right-1.5 top-1.5 rounded p-0.5 text-gray-400 opacity-0 transition hover:bg-white hover:text-red-600 group-hover:opacity-100"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
    </aside>
  );
}
