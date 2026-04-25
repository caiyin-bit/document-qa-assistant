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
