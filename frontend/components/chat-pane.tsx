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
        /* empty pane fallback */
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
  // Allow chat without docs (plain LLM). Block only while streaming or while
  // docs exist but none are ready (we want those questions to hit RAG).
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
        ? "向文档提问…（Enter 发送 · Shift+Enter 换行）"
        : "输入问题与助手对话…（Enter 发送）";

  return (
    <div className="flex h-full flex-1 flex-col bg-white">
      <ScrollArea className="flex-1">
        <div className="mx-auto w-full max-w-3xl px-5 py-5">
          {messages.length === 0 && (
            <div className="mt-8 text-center text-[13px] text-gray-400">
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
            <div className="my-2 rounded-md border border-orange-300 bg-orange-50 px-3 py-2 text-sm text-orange-800">
              出错了：{error}
              <button
                className="ml-2 text-orange-900 underline underline-offset-2 hover:no-underline"
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

      <div className="border-t border-gray-200 bg-white px-4 py-3">
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
            className="min-h-[40px] flex-1 resize-none rounded-md border border-gray-200 bg-white px-3 py-2 text-[13px] outline-none placeholder:text-gray-400 focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200 disabled:bg-gray-50 disabled:text-gray-400"
          />
          <button
            onClick={handleSend}
            disabled={inputDisabled || !input.trim()}
            className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-3.5 py-2 text-[13px] font-medium text-white transition hover:bg-indigo-700 disabled:bg-gray-300"
          >
            <Send className="h-3.5 w-3.5" /> 发送
          </button>
        </div>
      </div>
    </div>
  );
}
