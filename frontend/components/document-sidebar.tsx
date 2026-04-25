"use client";
import { useRef, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { uploadDocument, deleteDocument } from "@/lib/api";
import type { Document } from "@/lib/types";
import { DocumentRow } from "./document-row";

type Props = {
  sessionId: string;
  docs: Document[];
  onChange: () => void;
};

export function DocumentSidebar({ sessionId, docs, onChange }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    setError(null);
    try {
      await uploadDocument(sessionId, file);
      onChange();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "上传失败");
    }
  }

  async function handleDelete(docId: string) {
    setError(null);
    try {
      await deleteDocument(sessionId, docId);
      onChange();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  }

  return (
    <aside
      className="flex h-full w-[260px] flex-col border-r border-gray-200 bg-gray-50"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = e.dataTransfer.files[0];
        if (f) handleUpload(f);
      }}
    >
      <div className="px-3 pt-3 pb-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
        文档
      </div>

      <ScrollArea className="flex-1">
        <ul className="flex flex-col gap-1.5 px-3 pb-3">
          {docs.length === 0 ? (
            <li className="px-1 py-1.5 text-[11px] text-gray-400">
              暂无文档
            </li>
          ) : (
            docs.map((d) => (
              <li key={d.document_id}>
                <DocumentRow
                  sessionId={sessionId}
                  doc={d}
                  onDelete={handleDelete}
                />
              </li>
            ))
          )}
        </ul>
      </ScrollArea>

      <div className="border-t border-gray-200 p-3">
        <button
          onClick={() => inputRef.current?.click()}
          className={`block w-full rounded-md border-2 border-dashed px-3 py-3 text-center transition ${
            dragging
              ? "border-indigo-400 bg-indigo-50 text-indigo-700"
              : "border-indigo-200 bg-gradient-to-b from-[#fafbff] to-[#f5f7ff] text-indigo-700 hover:border-indigo-300 hover:bg-indigo-50"
          }`}
        >
          <div className="text-[20px] leading-none">📥</div>
          <div className="mt-1 text-[12px] font-semibold">
            {dragging ? "松开上传" : "拖入或点击上传 PDF"}
          </div>
          <div className="mt-0.5 text-[10px] text-indigo-500">
            ≤ 20MB · 可多份
          </div>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleUpload(f);
          }}
        />
        {error && (
          <div className="mt-2 text-[11px] text-red-600">{error}</div>
        )}
        <div className="mt-2 text-center text-[10px] text-gray-400">
          点击文档可在右侧聊天中提问
        </div>
      </div>
    </aside>
  );
}
