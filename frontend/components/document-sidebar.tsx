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
      className="flex h-full w-[260px] flex-col border-r"
      style={{
        backgroundColor: "var(--app-bg-docs)",
        borderColor: "var(--app-border-divider)",
      }}
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
      <div
        className="px-3 pt-3 pb-1.5 text-[10px] font-mono font-semibold uppercase tracking-wider"
        style={{ color: "var(--app-text-tertiary)" }}
      >
        文档 · DOCUMENTS
      </div>

      <ScrollArea className="flex-1">
        <ul className="flex flex-col gap-1.5 px-3 pb-3">
          {docs.length === 0 ? (
            <li
              className="px-1 py-1.5 text-[11px]"
              style={{ color: "var(--app-text-faint)" }}
            >
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

      <div
        className="border-t p-3"
        style={{ borderColor: "var(--app-border-subtle)" }}
      >
        <button
          onClick={() => inputRef.current?.click()}
          className="block w-full rounded-md border-2 border-dashed px-3 py-3 text-center transition"
          style={{
            backgroundColor: dragging
              ? "var(--app-accent-bg)"
              : "var(--app-accent-bg-dim)",
            borderColor: "var(--app-accent-border)",
            color: "var(--app-accent-text-light)",
          }}
        >
          <div className="text-[20px] leading-none">📥</div>
          <div className="mt-1 text-[12px] font-semibold">
            {dragging ? "松开上传" : "拖入或点击上传 PDF"}
          </div>
          <div
            className="mt-0.5 text-[10px] font-mono"
            style={{ color: "var(--app-text-tertiary)" }}
          >
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
          <div
            className="mt-2 text-[11px]"
            style={{ color: "var(--app-status-err-fg)" }}
          >
            {error}
          </div>
        )}
      </div>
    </aside>
  );
}
