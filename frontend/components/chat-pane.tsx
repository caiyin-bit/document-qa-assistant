"use client";

import { useEffect, useRef, useState } from "react";
import { Send, StopCircle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { listMessages } from "@/lib/api";
import { useChatStream } from "@/lib/use-chat-stream";
import type { Document, Message } from "@/lib/types";
import { MessageBubble } from "./message-bubble";
import { PdfViewer, type PdfTarget } from "./pdf-viewer";
import { DocIntro } from "./doc-intro";

type Props = {
  sessionId: string;
  docs: Document[];
  onFirstMessageSent?: () => void;
};

export function ChatPane({ sessionId, docs, onFirstMessageSent }: Props) {
  const { messages, streaming, error, send, stop, setMessages } =
    useChatStream(sessionId);
  const [input, setInput] = useState("");
  const [pdfTarget, setPdfTarget] = useState<PdfTarget>(null);
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
          citations: m.citations ?? undefined,
        }));
        setMessages((prev) => (prev.length === 0 ? converted : prev));
      } catch {
        /* empty fallback */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, setMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // Esc: stop streaming if active, else close PDF viewer if open. Single
  // global listener wins over per-element handlers, which the textarea
  // would otherwise swallow.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (streaming) {
        e.preventDefault();
        stop();
      } else if (pdfTarget) {
        e.preventDefault();
        setPdfTarget(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [streaming, stop, pdfTarget]);

  const hasReady = docs.some((d) => d.status === "ready");
  const hasProcessing = docs.some((d) => d.status === "processing");
  const firstReadyDoc = docs.find((d) => d.status === "ready");
  const inputDisabled = streaming;

  const prevDocStatusRef = useRef<Map<string, Document["status"]>>(new Map());
  useEffect(() => {
    const justReady = docs.filter(
      (d) =>
        d.status === "ready" &&
        prevDocStatusRef.current.get(d.document_id) === "processing",
    );
    prevDocStatusRef.current = new Map(
      docs.map((d) => [d.document_id, d.status]),
    );
    if (justReady.length === 0) return;
    setMessages((prev) => [
      ...prev,
      ...justReady.map((d) => ({
        id: `sys-ready-${d.document_id}`,
        role: "system" as const,
        content: `「${d.filename}」已完成解析，现在可以基于此文档提问了。`,
        tools: [],
      })),
    ]);
  }, [docs, setMessages]);

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
    : hasReady
      ? "向文档提问…  Enter 发送 · Shift+Enter 换行"
      : hasProcessing
        ? "文档解析中，可以先聊别的或稍后再针对文档提问…"
        : "输入问题与助手对话…  Enter 发送";

  return (
    <div className="flex h-full flex-1">
    <div
      className="flex h-full flex-1 flex-col min-w-0"
      style={{ backgroundColor: "var(--app-bg)" }}
    >
      <ScrollArea className="min-h-0 flex-1">
        <div className="mx-auto w-full max-w-3xl px-5 py-5">
          {messages.length === 0 && (
            <>
              <div
                className="mt-8 text-center text-[13px]"
                style={{ color: "var(--app-text-faint)" }}
              >
                {hasReady
                  ? "文档已就绪，可以开始提问了。"
                  : hasProcessing
                    ? "文档解析中，你可以先开始聊天；解析完成后会有提示。"
                    : "未上传文档时也可以直接对话；上传后回答会附带原文出处。"}
              </div>
              {hasReady && firstReadyDoc && (
                <DocIntro
                  sessionId={sessionId}
                  documentId={firstReadyDoc.document_id}
                  filename={firstReadyDoc.filename}
                  onPickQuestion={(q) => {
                    setInput("");
                    send(q);
                  }}
                />
              )}
            </>
          )}
          {messages.map((m, idx) => {
            const isLastAssistant =
              m.role === "assistant" &&
              idx === messages.length - 1 &&
              !streaming;
            return (
              <MessageBubble
                key={m.id}
                message={m}
                isStreaming={
                  streaming && idx === messages.length - 1 && m.role === "assistant"
                }
                isLastAssistant={isLastAssistant}
                onOpenPdf={(doc_id, page, filename) =>
                  setPdfTarget({ doc_id, page, filename })
                }
                onRegenerate={() => {
                  // Find last user message; drop it + the assistant; re-send.
                  const lastUserIdx = [...messages].reverse().findIndex(
                    (mm) => mm.role === "user",
                  );
                  if (lastUserIdx === -1) return;
                  const realIdx = messages.length - 1 - lastUserIdx;
                  const lastUser = messages[realIdx];
                  setMessages((prev) => prev.slice(0, realIdx));
                  send(lastUser.content);
                }}
              />
            );
          })}
          {error && (
            <div
              className="my-2 rounded-md border px-3 py-2 text-sm"
              style={{
                backgroundColor: "var(--app-status-err-bg)",
                borderColor: "var(--app-status-err-card-border)",
                color: "var(--app-status-err-fg)",
              }}
            >
              出错了：{error}
              <button
                className="ml-2 underline underline-offset-2 hover:no-underline"
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

      <div
        className="border-t px-4 py-3"
        style={{
          backgroundColor: "var(--app-bg)",
          borderColor: "var(--app-border-subtle)",
        }}
      >
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
            className="min-h-[40px] flex-1 resize-none rounded-md border px-3 py-2 text-[13px] outline-none transition focus:ring-2 disabled:opacity-50"
            style={{
              backgroundColor: "var(--app-surface-input)",
              borderColor: "var(--app-border-subtle)",
              color: "var(--app-text-primary)",
            }}
          />
          {streaming ? (
            <button
              onClick={stop}
              className="inline-flex items-center gap-1 rounded-md px-3.5 py-2 text-[13px] font-medium transition hover:opacity-90"
              style={{
                backgroundColor: "var(--app-status-err-bg)",
                color: "var(--app-status-err-fg)",
                border: "1px solid var(--app-status-err-fg)",
              }}
              title="停止生成"
            >
              <StopCircle className="h-3.5 w-3.5" /> 停止
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={inputDisabled || !input.trim()}
              className="inline-flex items-center gap-1 rounded-md px-3.5 py-2 text-[13px] font-medium transition hover:opacity-90 disabled:opacity-50"
              style={{
                backgroundColor: "var(--app-accent)",
                color: "var(--app-text-on-accent)",
              }}
            >
              <Send className="h-3.5 w-3.5" /> 发送
            </button>
          )}
        </div>
      </div>
    </div>
    <PdfViewer
      sessionId={sessionId}
      target={pdfTarget}
      onClose={() => setPdfTarget(null)}
    />
    </div>
  );
}
