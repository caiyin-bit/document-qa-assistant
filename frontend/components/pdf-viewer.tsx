"use client";

import { X } from "lucide-react";
import { API_BASE } from "@/lib/api";

export type PdfTarget = {
  doc_id: string;
  filename: string;
  page: number;
} | null;

type Props = {
  sessionId: string;
  target: PdfTarget;
  onClose: () => void;
};

export function PdfViewer({ sessionId, target, onClose }: Props) {
  if (!target) return null;
  // `#page=N` is the PDF viewer URI fragment recognised by Chrome / Safari /
  // Firefox built-in PDF viewers. Each open re-keys the iframe so jumping
  // to a different page actually scrolls — without `key` the iframe URL
  // change is treated as a no-op fragment update by the browser cache.
  const src = `${API_BASE}/sessions/${sessionId}/documents/${target.doc_id}/file#page=${target.page}`;
  return (
    <aside
      className="flex h-full w-[44%] min-w-[420px] flex-col border-l"
      style={{
        backgroundColor: "var(--app-bg)",
        borderColor: "var(--app-border-subtle)",
      }}
    >
      <header
        className="flex items-center gap-2 border-b px-3 py-2"
        style={{ borderColor: "var(--app-border-subtle)" }}
      >
        <div
          className="min-w-0 flex-1 truncate text-[12px] font-medium"
          style={{ color: "var(--app-text-primary)" }}
        >
          {target.filename}{" "}
          <span style={{ color: "var(--app-text-tertiary)" }}>
            · 第 {target.page} 页
          </span>
        </div>
        <button
          onClick={onClose}
          aria-label="close pdf viewer"
          className="rounded p-1 transition hover:opacity-70"
          style={{ color: "var(--app-text-secondary)" }}
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <iframe
        key={src}
        src={src}
        className="flex-1 w-full"
        title={target.filename}
        style={{ border: "none" }}
      />
    </aside>
  );
}
