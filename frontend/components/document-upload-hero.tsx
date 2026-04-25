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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "上传失败");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[18px] font-semibold text-gray-900">
          📄 文档问答
        </h1>
        <p className="mt-1 text-[13px] leading-relaxed text-gray-500">
          上传 PDF，针对内容自由提问。所有回答都附带原文出处。
        </p>
      </div>

      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files[0];
          if (f) upload(f);
        }}
        className={`cursor-pointer rounded-[10px] border-2 border-dashed px-5 py-7 text-center transition ${
          dragging
            ? "border-indigo-400 bg-indigo-50 text-indigo-700"
            : "border-indigo-200 bg-gradient-to-b from-[#fafbff] to-[#f5f7ff] text-indigo-700 hover:border-indigo-300 hover:bg-indigo-50"
        }`}
      >
        <div className="mb-2 text-[28px] leading-none">📥</div>
        <div className="text-sm font-semibold text-indigo-700">
          {dragging ? "松开以上传 PDF" : "拖入 PDF 或点击上传"}
        </div>
        <div className="mt-1 text-[11px] text-indigo-500">
          支持中文 · 单文件 ≤ 20MB · 可上传多份
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload(f);
          }}
        />
      </div>

      {error && <div className="text-xs text-red-600">{error}</div>}
    </div>
  );
}
