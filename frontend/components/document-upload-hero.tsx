"use client";
import { useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";

type Props = {
  sessionId: string;
  onUploaded: () => void;
};

export function DocumentUploadHero({ sessionId, onUploaded }: Props) {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setError(null);
    try {
      await uploadDocument(sessionId, file);
      onUploaded();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="flex h-full flex-col items-center justify-center p-8 gap-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold mb-2">📄 文档问答</h1>
        <p className="text-sm text-muted-foreground max-w-md">
          上传 PDF，针对内容自由提问。所有回答都附带原文出处。
        </p>
      </div>

      <div
        className={`w-full max-w-lg cursor-pointer rounded-lg border-2 border-dashed p-10 text-center transition ${
          dragging ? "border-indigo-400 bg-indigo-50" : "border-gray-300 hover:bg-gray-50"
        }`}
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files[0];
          if (file) upload(file);
        }}
      >
        <div className="text-3xl mb-2">📥</div>
        <div className="font-medium text-gray-700 mb-1">
          {dragging ? "松开以上传 PDF" : "拖入 PDF 或点击上传"}
        </div>
        <div className="text-xs text-gray-500">支持中文 · ≤20MB · 可上传多份</div>
        <input ref={inputRef} type="file" accept=".pdf" hidden
          onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); }} />
      </div>

      {error && <div className="text-sm text-red-600">{error}</div>}
    </div>
  );
}
