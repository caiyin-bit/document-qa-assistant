"use client";

import { useCallback, useState } from "react";
import { STREAM_URL } from "./api";
import { parseSSE, type ServerEvent } from "./sse-stream";
import type { Message } from "./types";

export function useChatStream(sessionId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

      try {
        const r = await fetch(STREAM_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, message: text }),
        });
        if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
        for await (const ev of parseSSE(r.body)) {
          if (ev.type === "error") {
            throw new Error(`${ev.code}: ${ev.message}`);
          }
          setMessages((prev) => applyEvent(prev, ev));
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "网络出错");
      } finally {
        setStreaming(false);
      }
    },
    [sessionId, streaming],
  );

  return { messages, streaming, error, send, setMessages };
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
  }
  return copy;
}
