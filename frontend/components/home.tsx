"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { listSessions } from "@/lib/api";
import { SessionsSidebar } from "@/components/sessions-sidebar";
import { ChatPane } from "@/components/chat-pane";
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
    <main className="flex h-screen w-screen overflow-hidden">
      <SessionsSidebar
        sessions={sessions}
        activeSessionId={sessionId}
        onAfterCreate={refreshSessions}
      />
      {sessionId ? (
        <ChatPane
          key={sessionId}
          sessionId={sessionId}
          onFirstMessageSent={refreshSessions}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center text-gray-500">
          选择一个会话或新建一个
        </div>
      )}
    </main>
  );
}
