"use client";

import { useCallback, useRef, useState } from "react";
import { STREAM_URL } from "./api";
import { parseSSE, type ServerEvent } from "./sse-stream";
import type { Message } from "./types";

export function useChatStream(sessionId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Held across renders so the Stop button can abort the in-flight fetch
  // on the same iteration without re-creating it on every send().
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (text: string) => {
      if (!sessionId || streaming || !text.trim()) return;
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        tools: [],
      };
      const asstMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        tools: [],
      };
      setMessages((prev) => [...prev, userMsg, asstMsg]);
      setStreaming(true);
      setError(null);

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const r = await fetch(STREAM_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, message: text }),
          signal: ctrl.signal,
        });
        if (r.status === 404) {
          // Stale session id (e.g. session was deleted server-side).
          // Drop it from the URL so the user lands on the empty state
          // and can create a fresh session.
          if (typeof window !== "undefined") {
            window.location.assign("/");
          }
          throw new Error("会话不存在或已过期，请新建会话");
        }
        if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
        for await (const ev of parseSSE(r.body)) {
          if (ev.type === "error") {
            throw new Error(`${ev.code}: ${ev.message}`);
          }
          setMessages((prev) => applyEvent(prev, ev));
        }
      } catch (e) {
        // Distinguish user-initiated abort from real network errors so
        // the chat doesn't render "出错了：AbortError" on a clean stop.
        if ((e as Error)?.name === "AbortError") {
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy.length - 1;
            if (last >= 0 && copy[last].role === "assistant") {
              copy[last] = {
                ...copy[last],
                content: copy[last].content + "\n\n_（已停止生成）_",
              };
            }
            return copy;
          });
        } else {
          setError(e instanceof Error ? e.message : "网络出错");
        }
      } finally {
        abortRef.current = null;
        setStreaming(false);
      }
    },
    [sessionId, streaming],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { messages, streaming, error, send, stop, setMessages };
}

function applyEvent(prev: Message[], ev: ServerEvent): Message[] {
  if (ev.type === "done" || ev.type === "error") return prev;
  const copy = [...prev];
  const i = copy.length - 1;
  const m = copy[i];
  if (ev.type === "text") {
    copy[i] = { ...m, content: m.content + ev.delta };
  } else if (ev.type === "tool_call_started") {
    copy[i] = {
      ...m,
      tools: [
        ...m.tools,
        { id: ev.id, name: ev.name, status: "running" as const },
      ],
    };
  } else if (ev.type === "tool_call_finished") {
    copy[i] = {
      ...m,
      tools: m.tools.map((t) =>
        t.id === ev.id
          ? { ...t, status: ev.ok ? ("ok" as const) : ("error" as const) }
          : t,
      ),
    };
  } else if (ev.type === "citations") {
    copy[i] = { ...m, citations: ev.chunks };
  }
  return copy;
}
