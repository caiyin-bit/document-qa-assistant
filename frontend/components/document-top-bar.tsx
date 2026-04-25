"use client";
import { useRef, useState } from "react";
import type { Document } from "@/lib/types";
import { uploadDocument, deleteDocument } from "@/lib/api";
import { DocumentRow } from "./document-row";

type Props = {
  sessionId: string;
  docs: Document[];
  onChange: () => void;
};

export function DocumentTopBar({ sessionId, docs, onChange }: Props) {
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    setError(null);
    try {
      await uploadDocument(sessionId, file);
      onChange();
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleDelete(docId: string) {
    setError(null);
    try {
      await deleteDocument(sessionId, docId);
      onChange();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="border-b bg-gray-50 p-2">
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-[10px] uppercase font-semibold text-gray-500">文档</span>
        {docs.map(d => (
          <DocumentRow key={d.document_id} sessionId={sessionId} doc={d} onDelete={handleDelete} />
        ))}
        <button onClick={() => inputRef.current?.click()}
                className="rounded border border-dashed border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-white">
          + 添加
        </button>
        <input ref={inputRef} type="file" accept=".pdf" hidden
          onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); }} />
      </div>
      {error && <div className="text-xs text-red-600 mt-1">{error}</div>}
    </div>
  );
}
