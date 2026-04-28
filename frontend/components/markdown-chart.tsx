"use client";

import { Suspense, lazy, useMemo } from "react";
import { useTheme } from "@/lib/use-theme";

// Lazy-load the entire xviz / echarts surface. echarts is ~250KB+ gzip;
// users who never see a chart-bearing answer never download it.
const ChartLoader = lazy(() =>
  import("./markdown-chart-impl").then((m) => ({ default: m.ChartLoader })),
);

type Props = {
  /** Raw text inside the ```chart fenced block */
  source: string;
};

export function MarkdownChart({ source }: Props) {
  const { theme } = useTheme();
  // Parse once per render — small JSON, not worth memoising harder.
  const parsed = useMemo(() => parseChartSpec(source), [source]);

  if (parsed.error) {
    return (
      <div
        className="my-2 rounded-md border px-3 py-2 text-[12px] font-mono"
        style={{
          backgroundColor: "var(--app-status-warn-bg)",
          borderColor: "var(--app-status-warn-card-border)",
          color: "var(--app-status-warn-fg)",
        }}
      >
        图表渲染失败 — {parsed.error}
        <pre
          className="mt-1 overflow-x-auto whitespace-pre text-[10px] opacity-70"
          style={{ color: "var(--app-text-faint)" }}
        >
          {source.trim().slice(0, 400)}
        </pre>
      </div>
    );
  }

  return (
    <div className="my-3">
      {parsed.spec.title && (
        <div
          className="mb-1 text-[12px] font-medium"
          style={{ color: "var(--app-text-secondary)" }}
        >
          {parsed.spec.title}
        </div>
      )}
      <Suspense
        fallback={
          <div
            className="flex h-[260px] items-center justify-center rounded-md text-[12px] italic"
            style={{
              backgroundColor: "var(--app-surface-elevated)",
              color: "var(--app-text-faint)",
            }}
          >
            加载图表中…
          </div>
        }
      >
        <ChartLoader spec={parsed.spec} themeName={theme} />
      </Suspense>
    </div>
  );
}

// Thin parsed shape — keep the parsed JSON's xviz fields verbatim and
// pass straight through to the chart impl. We only do shallow validation
// here so a malformed block degrades gracefully.
type ParsedSpec =
  | { error: null; spec: ChartSpec }
  | { error: string; spec: never };

export type ChartSpec = {
  vizType: string;
  title?: string;
  data?: Record<string, unknown>[];
  // Everything else is xviz formData; we forward as-is.
  [k: string]: unknown;
};

function parseChartSpec(source: string): ParsedSpec {
  try {
    const obj = JSON.parse(source);
    if (typeof obj !== "object" || obj === null) {
      return { error: "JSON 不是对象", spec: undefined as never };
    }
    if (typeof obj.vizType !== "string") {
      return { error: "缺少 vizType", spec: undefined as never };
    }
    if (!Array.isArray(obj.data)) {
      return { error: "缺少 data 数组", spec: undefined as never };
    }
    return { error: null, spec: obj as ChartSpec };
  } catch (e) {
    return {
      error: e instanceof Error ? e.message : "JSON 解析错误",
      spec: undefined as never,
    };
  }
}
