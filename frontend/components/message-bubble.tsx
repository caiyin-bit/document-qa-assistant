import { Search } from "lucide-react";
import type { Message, ToolCall } from "@/lib/types";
import { CitationCard } from "./citation-card";

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const tools =
    message.role === "assistant" && message.tools.length > 0
      ? message.tools
      : null;

  return (
    <div
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"} my-2`}
    >
      <div
        className="max-w-[80%] rounded-2xl px-4 py-2.5 text-[14px] leading-relaxed"
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
          <div className="whitespace-pre-wrap break-words">
            {message.content}
          </div>
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
          <CitationCard citations={message.citations} />
        )}
      </div>
    </div>
  );
}

function ToolChip({ tool }: { tool: ToolCall }) {
  const label =
    tool.status === "running"
      ? `${tool.name} · running…`
      : tool.status === "ok"
        ? `${tool.name}`
        : `${tool.name} · failed`;
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
