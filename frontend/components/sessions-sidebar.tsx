"use client";

import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { createSession } from "@/lib/api";
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

  return (
    <aside className="flex h-full w-64 flex-col border-r border-gray-200 bg-gray-50">
      <div className="border-b border-gray-200 p-3">
        <Button onClick={handleNew} className="w-full gap-2">
          <Plus className="h-4 w-4" /> 新对话
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <ul className="p-2">
          {sessions.map((s) => {
            const active = s.session_id === activeSessionId;
            return (
              <li key={s.session_id}>
                <button
                  onClick={() => router.push(`/?session=${s.session_id}`)}
                  className={`mb-1 w-full rounded-md px-3 py-2 text-left text-sm ${
                    active
                      ? "bg-blue-100 text-blue-900"
                      : "hover:bg-gray-200"
                  }`}
                >
                  <div className="truncate">{s.title}</div>
                  <div className="text-xs text-gray-500">
                    {new Date(s.created_at).toLocaleString("zh-CN")}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
    </aside>
  );
}
