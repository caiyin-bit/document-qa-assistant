import { CheckCircle2, Copy, RotateCcw, Search } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message, ToolCall } from "@/lib/types";
import { CitationCard } from "./citation-card";

// Map raw tool name → user-facing Chinese label. Keep it tiny; we only
// have one tool today, but listing here makes it easy to extend.
const TOOL_LABELS: Record<string, string> = {
  search_documents: "检索文档",
};
function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

type Props = {
  message: Message;
  isStreaming?: boolean;
  isLastAssistant?: boolean;
  onOpenPdf?: (doc_id: string, page: number, filename: string) => void;
  onRegenerate?: () => void;
};

export function MessageBubble({
  message, isStreaming, isLastAssistant, onOpenPdf, onRegenerate,
}: Props) {
  if (message.role === "system") {
    return (
      <div className="my-3 flex w-full justify-center">
        <div
          className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px]"
          style={{
            backgroundColor: "var(--app-status-ok-bg)",
            borderColor: "var(--app-status-ok-fg)",
            color: "var(--app-status-ok-fg)",
          }}
        >
          <CheckCircle2 className="h-3 w-3" />
          {message.content}
        </div>
      </div>
    );
  }

  const isUser = message.role === "user";
  const tools =
    message.role === "assistant" && message.tools.length > 0
      ? message.tools
      : null;

  return (
    <div
      className={`group/msg flex w-full ${isUser ? "justify-end" : "justify-start"} my-2`}
    >
      <div
        className="relative max-w-[80%] rounded-2xl px-4 py-2.5 text-[14px] leading-relaxed"
        style={{
          backgroundColor: isUser
            ? "var(--app-accent)"
            : "var(--app-surface-elevated)",
          color: isUser
            ? "var(--app-text-on-accent)"
            : "var(--app-text-primary)",
          border: isUser ? "none" : "1px solid var(--app-border-subtle)",
          borderRadius: isUser
            ? "16px 16px 4px 16px"
            : "16px 16px 16px 4px",
        }}
      >
        {tools && (
          <div className="mb-2.5 flex flex-wrap gap-1.5">
            {tools.map((t) => (
              <ToolChip key={t.id} tool={t} />
            ))}
          </div>
        )}
        {message.content ? (
          isUser ? (
            <div className="whitespace-pre-wrap break-words">
              {message.content}
            </div>
          ) : (
            <div className="markdown-body break-words">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content + (isStreaming ? " ▍" : "")}
              </ReactMarkdown>
            </div>
          )
        ) : (
          message.role === "assistant" && (
            <div
              className="italic animate-pulse"
              style={{ color: "var(--app-text-faint)" }}
            >
              正在思考中.....
            </div>
          )
        )}
        {message.role === "assistant" && message.citations && (
          <CitationCard citations={message.citations} onOpenPdf={onOpenPdf} />
        )}
        {!isUser && !isStreaming && message.content && (
          <MessageActions
            content={message.content}
            canRegenerate={!!isLastAssistant}
            onRegenerate={onRegenerate}
          />
        )}
      </div>
    </div>
  );
}

function MessageActions({
  content, canRegenerate, onRegenerate,
}: { content: string; canRegenerate: boolean; onRegenerate?: () => void }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  }
  return (
    <div
      className="mt-2 flex gap-1 opacity-0 transition group-hover/msg:opacity-100"
      style={{ color: "var(--app-text-tertiary)" }}
    >
      <button
        onClick={copy}
        title={copied ? "已复制" : "复制"}
        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] hover:opacity-80"
        style={{ color: "var(--app-text-secondary)" }}
      >
        {copied ? <CheckCircle2 className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        {copied ? "已复制" : "复制"}
      </button>
      {canRegenerate && onRegenerate && (
        <button
          onClick={onRegenerate}
          title="重新生成"
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] hover:opacity-80"
          style={{ color: "var(--app-text-secondary)" }}
        >
          <RotateCcw className="h-3 w-3" /> 重新生成
        </button>
      )}
    </div>
  );
}

function ToolChip({ tool }: { tool: ToolCall }) {
  const cn = toolLabel(tool.name);
  const label =
    tool.status === "running"
      ? `正在${cn}…`
      : tool.status === "ok"
        ? `已${cn}`
        : `${cn}失败`;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-[2px] text-[10px] font-mono"
      style={{
        backgroundColor: "var(--app-accent-bg-dim)",
        borderColor: "var(--app-accent-border)",
        color: "var(--app-accent-text-bright)",
      }}
    >
      <Search className="h-2.5 w-2.5" />
      {label}
    </span>
  );
}
