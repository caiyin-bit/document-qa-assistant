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
    const page = (progress as { page?: number } | null)?.page ?? doc.progress_page ?? 0;
    const total = doc.page_count;
    const pct = total ? Math.round((page / total) * 100) : 0;
    return (
      <div className="min-w-[260px] rounded-[5px] border border-amber-200 bg-amber-50 px-2 py-1.5">
        <div className="flex items-center gap-2">
          <FileBadge size="sm" />
          <span className="flex-1 truncate text-xs text-gray-700">
            {doc.filename}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-[1px] text-[10px] font-semibold text-amber-800">
            <Spinner /> 解析中
          </span>
        </div>
        <div className="mt-1.5 h-[3px] overflow-hidden rounded-sm bg-amber-100">
          <div
            className="h-full animate-pulse bg-gradient-to-r from-amber-500 to-amber-400 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="mt-1 text-[10px] text-amber-800">
          正在向量化第 {page} / {total} 页…
        </div>
      </div>
    );
  }

  if (doc.status === "ready") {
    return (
      <div className="flex min-w-[200px] items-center gap-2 rounded-[5px] border border-green-300 bg-green-50 px-2 py-1.5">
        <FileBadge size="sm" />
        <span className="flex-1 truncate text-xs text-gray-700">
          {doc.filename}
        </span>
        <span className="text-[10px] text-gray-500">{doc.page_count} 页</span>
        <span className="rounded-full bg-green-100 px-2 py-[1px] text-[10px] font-semibold text-green-800">
          ✓ 就绪
        </span>
        <button
          onClick={() => onDelete(doc.document_id)}
          className="px-1 text-gray-400 hover:text-gray-600"
          aria-label="删除文档"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  // failed
  return (
    <div className="min-w-[260px] rounded-[5px] border border-red-200 bg-red-50 px-2 py-1.5">
      <div className="flex items-center gap-2">
        <FileBadge size="sm" tone="dark" />
        <span className="flex-1 truncate text-xs text-gray-700">
          {doc.filename}
        </span>
        <span className="rounded-full bg-red-100 px-2 py-[1px] text-[10px] font-semibold text-red-800">
          ✗ 失败
        </span>
        <button
          onClick={() => onDelete(doc.document_id)}
          className="px-1 text-gray-400 hover:text-gray-600"
          aria-label="删除文档"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {doc.error_message && (
        <div className="mt-1 text-[10px] leading-snug text-red-700">
          {doc.error_message}
        </div>
      )}
    </div>
  );
}

function FileBadge({
  size = "sm",
  tone = "default",
}: {
  size?: "sm" | "md";
  tone?: "default" | "dark";
}) {
  const dim = size === "sm" ? "h-[18px] w-[18px] text-[8px]" : "h-7 w-7 text-[9px]";
  const bg = tone === "dark" ? "bg-red-600" : "bg-red-500";
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-[3px] font-bold text-white ${dim} ${bg}`}
    >
      PDF
    </span>
  );
}

function Spinner() {
  return (
    <span
      className="inline-block h-2 w-2 animate-spin rounded-full border-[1.5px] border-amber-400 border-t-transparent"
      aria-hidden="true"
    />
  );
}
