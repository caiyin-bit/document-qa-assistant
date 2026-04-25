"use client";
import { useState } from "react";
import type { Citation } from "@/lib/types";

type Props = { citations: Citation[] };

export function CitationCard({ citations }: Props) {
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
    <div className="mt-3 border-t border-gray-100 pt-3">
      <div className="mb-2 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        📚 来源（{citations.length}）
      </div>
      <div className="flex flex-col gap-1.5">
        {citations.map((c, i) => (
          <div
            key={i}
            onClick={() => toggle(i)}
            className="flex cursor-pointer items-start gap-2.5 rounded-md border border-gray-200 bg-gray-50 px-3 py-2.5 transition hover:border-gray-300 hover:bg-gray-100"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-red-500 text-[9px] font-bold text-white">
              PDF
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-medium text-gray-800">
                {c.filename}
              </div>
              <div
                className={`mt-0.5 text-[11px] leading-snug text-gray-500 ${
                  expanded.has(i) ? "" : "line-clamp-2"
                }`}
              >
                {c.snippet}
              </div>
            </div>
            <span className="ml-2 shrink-0 rounded-sm bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-800">
              p.{c.page_no}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
