"use client";

import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { listMessages } from "@/lib/api";
import { useChatStream } from "@/lib/use-chat-stream";
import type { Message } from "@/lib/types";
import { MessageBubble } from "./message-bubble";

type Props = {
  sessionId: string;
  onFirstMessageSent: () => void;
};

export function ChatPane({ sessionId, onFirstMessageSent }: Props) {
  const { messages, streaming, error, send, setMessages } =
    useChatStream(sessionId);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load history when sessionId changes
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
        }));
        // Race guard: if the user already started chatting (optimistic
        // messages added by send()) before history finished loading, keep
        // their messages instead of overwriting with the empty/old history.
        // Functional update reads the latest state, immune to stale closure.
        setMessages((prev) => (prev.length === 0 ? converted : prev));
      } catch {
        // Silent: empty pane — user can still send new messages
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, setMessages]);

  // Auto-scroll to bottom on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function handleSend() {
    const wasEmpty = messages.length === 0;
    const text = input.trim();
    if (!text) return;
    setInput("");
    await send(text);
    if (wasEmpty) onFirstMessageSent();
  }

  return (
    <div className="flex h-full flex-1 flex-col">
      <ScrollArea className="flex-1 px-4 py-4">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {error && (
          <div className="my-2 rounded-md border border-orange-300 bg-orange-50 p-3 text-sm text-orange-800">
            出错了:{error}
            <Button
              variant="link"
              size="sm"
              className="ml-2 h-auto p-0 text-orange-900"
              onClick={() => {
                const last = messages.findLast((m) => m.role === "user");
                if (last) {
                  setMessages((prev) => prev.slice(0, -2));
                  send(last.content);
                }
              }}
            >
              重试
            </Button>
          </div>
        )}
        <div ref={bottomRef} />
      </ScrollArea>
      <div className="border-t border-gray-200 bg-white p-3">
        <div className="flex gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="发消息(Enter 发送,Shift+Enter 换行)"
            disabled={streaming}
            className="min-h-[60px] resize-none"
          />
          <Button
            onClick={handleSend}
            disabled={streaming || !input.trim()}
            className="self-end gap-1"
          >
            <Send className="h-4 w-4" /> 发送
          </Button>
        </div>
      </div>
    </div>
  );
}
