"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { getDocumentIntro, type DocIntro } from "@/lib/api";

type Props = {
  sessionId: string;
  documentId: string;
  filename: string;
  onPickQuestion: (q: string) => void;
};

/** Renders an LLM-generated 2-3 sentence summary of the doc + 3 starter
 * questions the user can click to send. Shown in the chat empty-state
 * once the first document is `ready`. Cached in localStorage so it
 * doesn't re-bill on every re-render. */
export function DocIntro({
  sessionId, documentId, filename, onPickQuestion,
}: Props) {
  const [intro, setIntro] = useState<DocIntro | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    getDocumentIntro(sessionId, documentId)
      .then((d) => { if (!cancelled) setIntro(d); })
      .catch((e) => { if (!cancelled) setErr(String(e?.message || e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sessionId, documentId]);

  return (
    <div
      className="mx-auto mt-6 max-w-2xl rounded-lg border p-4"
      style={{
        backgroundColor: "var(--app-surface-elevated)",
        borderColor: "var(--app-border-subtle)",
      }}
    >
      <div
        className="mb-2 flex items-center gap-1.5 text-[11px] font-mono font-semibold uppercase tracking-wider"
        style={{ color: "var(--app-text-tertiary)" }}
      >
        <Sparkles className="h-3 w-3" /> 文档摘要
      </div>
      {loading && (
        <div
          className="text-[13px] italic animate-pulse"
          style={{ color: "var(--app-text-faint)" }}
        >
          正在分析「{filename}」…
        </div>
      )}
      {err && (
        <div
          className="text-[12px]"
          style={{ color: "var(--app-status-err-fg)" }}
        >
          摘要加载失败：{err}
        </div>
      )}
      {intro && (
        <>
          <p
            className="text-[13px] leading-relaxed"
            style={{ color: "var(--app-text-primary)" }}
          >
            {intro.summary}
          </p>
          {intro.questions.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {intro.questions.map((q) => (
                <button
                  key={q}
                  onClick={() => onPickQuestion(q)}
                  className="rounded-full border px-3 py-1 text-[12px] transition hover:opacity-80"
                  style={{
                    backgroundColor: "var(--app-accent-bg)",
                    borderColor: "var(--app-accent-border)",
                    color: "var(--app-accent-text-light)",
                  }}
                >
                  {q}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
