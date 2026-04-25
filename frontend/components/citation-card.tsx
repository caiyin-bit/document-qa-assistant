"use client";
import { useState } from "react";
import type { Citation } from "@/lib/types";

type Props = { citations: Citation[] };

export function CitationCard({ citations }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  if (!citations || citations.length === 0) return null;

  function toggle(i: number) {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  }

  return (
    <div className="mt-3 pt-3 border-t border-gray-200">
      <div className="text-[11px] font-semibold uppercase text-gray-500 mb-2">
        📚 来源（{citations.length}）
      </div>
      <div className="flex flex-col gap-1.5">
        {citations.map((c, i) => (
          <div key={i}
               onClick={() => toggle(i)}
               className="flex items-start gap-2.5 rounded-md border bg-gray-50 p-2.5 cursor-pointer hover:bg-gray-100">
            <span className="rounded bg-red-500 text-white text-[10px] font-bold px-1.5 py-1">PDF</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-gray-800">{c.filename}</div>
              <div className={`text-[11px] text-gray-600 mt-0.5 ${expanded.has(i) ? '' : 'line-clamp-2'}`}>
                {c.snippet}
              </div>
            </div>
            <span className="rounded bg-indigo-100 text-indigo-800 text-[10px] font-semibold px-1.5 py-0.5 shrink-0">
              p.{c.page_no}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
