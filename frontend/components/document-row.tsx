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
  const progress = useDocumentProgress(sessionId, doc.document_id,
                                        doc.status === 'processing');

  if (doc.status === 'processing') {
    const page = (progress as any)?.page ?? doc.progress_page ?? 0;
    const total = doc.page_count;
    const pct = total ? Math.round((page / total) * 100) : 0;
    return (
      <div className="rounded border border-amber-200 bg-amber-50 p-2 min-w-[260px]">
        <div className="flex items-center gap-2">
          <span className="rounded bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5">PDF</span>
          <span className="text-xs flex-1 truncate">{doc.filename}</span>
          <span className="rounded-full bg-amber-200 text-amber-900 text-[10px] px-2 py-0.5">解析中</span>
        </div>
        <div className="h-1 bg-amber-100 rounded mt-1 overflow-hidden">
          <div className="h-full bg-amber-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
        <div className="text-[10px] text-amber-800 mt-1">
          正在向量化第 {page} / {total} 页…
        </div>
      </div>
    );
  }

  if (doc.status === 'ready') {
    return (
      <div className="rounded border border-green-200 bg-green-50 p-2 flex items-center gap-2 min-w-[200px]">
        <span className="rounded bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5">PDF</span>
        <span className="text-xs flex-1 truncate">{doc.filename}</span>
        <span className="text-[10px] text-gray-500">{doc.page_count}页</span>
        <span className="rounded-full bg-green-200 text-green-900 text-[10px] px-2 py-0.5">✓ 就绪</span>
        <button onClick={() => onDelete(doc.document_id)}
                className="text-gray-400 hover:text-gray-600">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  // failed
  return (
    <div className="rounded border border-red-200 bg-red-50 p-2 min-w-[260px]">
      <div className="flex items-center gap-2">
        <span className="rounded bg-red-600 text-white text-[10px] font-bold px-1.5 py-0.5">PDF</span>
        <span className="text-xs flex-1 truncate">{doc.filename}</span>
        <span className="rounded-full bg-red-200 text-red-900 text-[10px] px-2 py-0.5">✗ 失败</span>
        <button onClick={() => onDelete(doc.document_id)}
                className="text-gray-400 hover:text-gray-600">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      {doc.error_message && (
        <div className="text-[10px] text-red-700 mt-1">{doc.error_message}</div>
      )}
    </div>
  );
}
