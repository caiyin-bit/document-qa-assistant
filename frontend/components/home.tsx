"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createSession, listSessions } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { SessionsSidebar } from "@/components/sessions-sidebar";
import { DocumentSidebar } from "@/components/document-sidebar";
import { ChatPane } from "@/components/chat-pane";
import { useDocuments } from "@/lib/use-documents";
import { useTheme } from "@/lib/use-theme";
import type { SessionSummary } from "@/lib/types";

export function Home() {
  const params = useSearchParams();
  const router = useRouter();
  const { me, loading: authLoading } = useAuth();
  const sessionId = params.get("session");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const { toggle: toggleTheme } = useTheme();

  // Bounce to /login when auth resolves to "no user". Demo mode (when
  // ALLOW_DEMO_LOGIN=true server-side) returns a Me object too, so this
  // only fires on a real "not logged in" response.
  useEffect(() => {
    if (!authLoading && me === null) {
      router.replace("/login");
    }
  }, [authLoading, me, router]);

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

  // Global keyboard shortcuts:
  //   ⌘K / Ctrl+K → new session (matches the convention used by Linear,
  //                  Notion, Slack — fastest path to "start fresh")
  //   ⌘/ / Ctrl+/ → toggle theme (light/dark)
  // Esc handling lives inside ChatPane (stop streaming / close PDF) so
  // it has access to local state.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const meta = e.metaKey || e.ctrlKey;
      if (!meta) return;
      if (e.key === "k") {
        e.preventDefault();
        (async () => {
          try {
            const { session_id } = await createSession();
            router.push(`/?session=${session_id}`);
            refreshSessions();
          } catch {
            /* ignore */
          }
        })();
      } else if (e.key === "/") {
        e.preventDefault();
        toggleTheme();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, toggleTheme]);

  if (authLoading || me === null) {
    return (
      <main
        className="flex h-screen w-screen items-center justify-center"
        style={{
          backgroundColor: "var(--app-bg)",
          color: "var(--app-text-faint)",
        }}
      >
        加载中…
      </main>
    );
  }

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
