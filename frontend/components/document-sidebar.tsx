"use client";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, FilePlus2 } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  attachDocuments, deleteDocument, listUserLibrary, uploadDocument,
  type LibraryDocument,
} from "@/lib/api";
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
  const [libOpen, setLibOpen] = useState(false);
  const [library, setLibrary] = useState<LibraryDocument[]>([]);
  const [libLoading, setLibLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleUpload(files: File | File[]) {
    const list = Array.isArray(files) ? files : [files];
    setError(null);
    // Sequential upload — backend serialises ingestion in the same arq
    // worker anyway, and parallel POSTs would just race on the same
    // bge_executor queue. Sequential keeps progress UI sensible.
    const errors: string[] = [];
    for (const f of list) {
      try {
        await uploadDocument(sessionId, f);
        onChange();
      } catch (e: unknown) {
        errors.push(`${f.name}: ${e instanceof Error ? e.message : "上传失败"}`);
      }
    }
    if (errors.length) setError(errors.join("\n"));
  }

  async function refreshLibrary() {
    setLibLoading(true);
    try {
      setLibrary(await listUserLibrary(sessionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载文档库失败");
    } finally {
      setLibLoading(false);
    }
  }

  // Lazy-load when the dropdown opens — avoids the extra GET on every
  // session open for users who never click "import existing".
  useEffect(() => {
    if (libOpen) refreshLibrary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [libOpen, sessionId]);

  async function handleAttach(documentId: string) {
    setError(null);
    try {
      await attachDocuments(sessionId, [documentId]);
      setLibrary((prev) => prev.filter((d) => d.document_id !== documentId));
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "导入失败");
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
        const files = Array.from(e.dataTransfer.files);
        if (files.length) handleUpload(files);
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
        {/* Library picker — opens a dropdown of the user's other ready
            docs (uploaded in earlier sessions) so they can be attached
            without re-uploading. */}
        <div className="relative mb-2">
          <button
            onClick={() => setLibOpen((v) => !v)}
            className="flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-[12px] transition hover:opacity-90"
            style={{
              backgroundColor: "var(--app-bg)",
              borderColor: "var(--app-border-subtle)",
              color: "var(--app-text-secondary)",
            }}
          >
            <span className="inline-flex items-center gap-1.5">
              <FilePlus2 className="h-3.5 w-3.5" /> 添加已有文档
            </span>
            <ChevronDown
              className={`h-3.5 w-3.5 transition ${libOpen ? "rotate-180" : ""}`}
            />
          </button>
          {libOpen && (
            <div
              className="absolute bottom-full left-0 right-0 mb-1 max-h-[260px] overflow-y-auto rounded-md border shadow-lg"
              style={{
                backgroundColor: "var(--app-surface-elevated)",
                borderColor: "var(--app-border-subtle)",
              }}
            >
              {libLoading && (
                <div
                  className="px-3 py-2 text-[11px] italic"
                  style={{ color: "var(--app-text-faint)" }}
                >
                  加载中…
                </div>
              )}
              {!libLoading && library.length === 0 && (
                <div
                  className="px-3 py-2 text-[11px]"
                  style={{ color: "var(--app-text-faint)" }}
                >
                  没有可导入的文档
                </div>
              )}
              {library.map((d) => (
                <button
                  key={d.document_id}
                  onClick={() => handleAttach(d.document_id)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition hover:opacity-80"
                  style={{ color: "var(--app-text-primary)" }}
                >
                  <span
                    className="inline-flex h-[14px] w-[14px] shrink-0 items-center justify-center rounded-sm text-[7px] font-bold font-mono"
                    style={{
                      backgroundColor: "var(--app-pdf-badge-bg)",
                      color: "var(--app-pdf-badge-fg)",
                    }}
                  >
                    PDF
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[12px]">
                    {d.filename}
                  </span>
                  <span
                    className="shrink-0 text-[10px] font-mono"
                    style={{ color: "var(--app-text-tertiary)" }}
                  >
                    {d.page_count}p
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
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
          multiple
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files || []);
            if (files.length) handleUpload(files);
            e.target.value = "";  // allow re-selecting same file later
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
