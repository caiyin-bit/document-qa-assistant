"use client";
import { X } from "lucide-react";
import type { Document } from "@/lib/types";
import { useDocumentProgress } from "@/lib/use-document-progress";

type Props = {
  sessionId: string;
  doc: Document;
  onDelete: (docId: string) => void;
};

export function DocumentRow({ sessionId, doc, onDelete }: Props) {
  const progress = useDocumentProgress(
    sessionId,
    doc.document_id,
    doc.status === "processing",
  );

  if (doc.status === "processing") {
    const live = progress as { page?: number; phase?: string } | null;
    const page = live?.page ?? doc.progress_page ?? 0;
    const phase = live?.phase ?? "ingesting";
    const total = doc.page_count;
    const pct = total ? Math.round((page / total) * 100) : 0;
    return (
      <div
        className="min-w-[200px] rounded-md border px-2 py-1.5"
        style={{
          backgroundColor: "var(--app-status-warn-bg)",
          borderColor: "var(--app-status-warn-card-border)",
        }}
      >
        <div className="flex items-center gap-2">
          <FileBadge />
          <span
            className="flex-1 truncate text-xs"
            style={{ color: "var(--app-text-primary)" }}
          >
            {doc.filename}
          </span>
          <StatusPill kind="warn">解析中</StatusPill>
        </div>
        <div
          className="mt-1.5 h-[3px] overflow-hidden rounded-sm"
          style={{ backgroundColor: "var(--app-status-warn-bg)" }}
        >
          <div
            className="h-full transition-all"
            style={{
              width: `${pct}%`,
              backgroundColor: "var(--app-status-warn-fg)",
            }}
          />
        </div>
        <div
          className="mt-1 text-[10px] font-mono"
          style={{ color: "var(--app-status-warn-fg)" }}
        >
          {phaseDetail(phase, page, total)}
        </div>
      </div>
    );
  }

  if (doc.status === "ready") {
    return (
      <div
        className="flex min-w-[200px] items-center gap-2 rounded-md border px-2 py-1.5"
        style={{
          backgroundColor: "var(--app-bg)",
          borderColor: "var(--app-border-subtle)",
        }}
      >
        <FileBadge />
        <span
          className="flex-1 truncate text-xs"
          style={{ color: "var(--app-text-primary)" }}
        >
          {doc.filename}
        </span>
        <span
          className="text-[10px] font-mono"
          style={{ color: "var(--app-text-tertiary)" }}
        >
          {doc.page_count} 页
        </span>
        <StatusPill kind="ok">✓ 就绪</StatusPill>
        <button
          onClick={() => onDelete(doc.document_id)}
          className="px-1 transition hover:opacity-70"
          aria-label="删除文档"
          style={{ color: "var(--app-text-faint)" }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  // failed
  return (
    <div
      className="min-w-[200px] rounded-md border px-2 py-1.5"
      style={{
        backgroundColor: "var(--app-bg)",
        borderColor: "var(--app-status-err-card-border)",
      }}
    >
      <div className="flex items-center gap-2">
        <FileBadge />
        <span
          className="flex-1 truncate text-xs"
          style={{ color: "var(--app-text-primary)" }}
        >
          {doc.filename}
        </span>
        <StatusPill kind="err">✗ 失败</StatusPill>
        <button
          onClick={() => onDelete(doc.document_id)}
          className="px-1 transition hover:opacity-70"
          aria-label="删除文档"
          style={{ color: "var(--app-text-faint)" }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {doc.error_message && (
        <div
          className="mt-1 text-[10px] leading-snug font-mono"
          style={{ color: "var(--app-status-err-fg)" }}
        >
          {doc.error_message}
        </div>
      )}
    </div>
  );
}

// Maps the backend's progress_phase tag to a Chinese caption shown under the
// progress bar. The "loading" phase has no page count to show — it's the
// pre-loop window when BGE is being lazy-imported into memory (~15-30s on
// first ingestion). Falls back to a generic "解析" if phase is missing.
function phaseDetail(phase: string, page: number, total: number): string {
  if (phase === "loading") return "正在加载嵌入模型…";
  const verb =
    phase === "extracting"
      ? "提取文本"
      : phase === "embedding"
        ? "向量化"
        : phase === "inserting"
          ? "入库"
          : "解析";
  return `${verb} ${page} / ${total}`;
}

function FileBadge() {
  return (
    <span
      className="inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-sm text-[8px] font-bold font-mono"
      style={{
        backgroundColor: "var(--app-pdf-badge-bg)",
        color: "var(--app-pdf-badge-fg)",
      }}
    >
      PDF
    </span>
  );
}

function StatusPill({
  kind,
  children,
}: {
  kind: "ok" | "warn" | "err";
  children: React.ReactNode;
}) {
  const bg =
    kind === "ok"
      ? "var(--app-status-ok-bg)"
      : kind === "warn"
        ? "var(--app-status-warn-bg)"
        : "var(--app-status-err-bg)";
  const fg =
    kind === "ok"
      ? "var(--app-status-ok-fg)"
      : kind === "warn"
        ? "var(--app-status-warn-fg)"
        : "var(--app-status-err-fg)";
  return (
    <span
      className="rounded-full px-2 py-[1px] text-[10px] font-mono font-semibold"
      style={{ backgroundColor: bg, color: fg }}
    >
      {children}
    </span>
  );
}
