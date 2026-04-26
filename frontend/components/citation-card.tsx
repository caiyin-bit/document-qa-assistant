"use client";
import { useState } from "react";
import type { Citation } from "@/lib/types";

type Props = {
  citations: Citation[];
  onOpenPdf?: (doc_id: string, page: number, filename: string) => void;
};

export function CitationCard({ citations, onOpenPdf }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  if (!citations || citations.length === 0) return null;

  function toggle(i: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  return (
    <div
      className="mt-3 border-t pt-3"
      style={{ borderColor: "var(--app-border-subtle)" }}
    >
      <div
        className="mb-2 flex items-center gap-1 text-[11px] font-mono font-semibold uppercase tracking-wider"
        style={{ color: "var(--app-text-tertiary)" }}
      >
        📚 来源 · CITATIONS ({citations.length})
      </div>
      <div className="flex flex-col gap-1.5">
        {citations.map((c, i) => (
          <div
            key={i}
            onClick={() => toggle(i)}
            className="flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2.5 transition hover:opacity-90"
            style={{
              backgroundColor: "var(--app-bg)",
              borderColor: "var(--app-border-subtle)",
            }}
          >
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-[9px] font-bold font-mono"
              style={{
                backgroundColor: "var(--app-pdf-badge-bg)",
                color: "var(--app-pdf-badge-fg)",
              }}
            >
              PDF
            </span>
            <div className="min-w-0 flex-1">
              <div
                className="text-[12px] font-medium"
                style={{ color: "var(--app-text-primary)" }}
              >
                {c.filename}
              </div>
              <div
                className={`mt-0.5 text-[11px] leading-snug font-mono ${
                  expanded.has(i) ? "" : "line-clamp-2"
                }`}
                style={{ color: "var(--app-text-secondary)" }}
              >
                {c.snippet}
              </div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onOpenPdf?.(c.doc_id, c.page_no, c.filename);
              }}
              title="在右侧打开 PDF 跳到该页"
              className="ml-2 shrink-0 rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold font-mono transition hover:opacity-80 hover:underline"
              style={{
                backgroundColor: "var(--app-accent-bg)",
                borderColor: "var(--app-accent-border)",
                color: "var(--app-accent-text-light)",
                cursor: onOpenPdf ? "pointer" : "default",
              }}
            >
              p.{c.page_no}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
